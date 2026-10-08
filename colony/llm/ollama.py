"""Colony Local — Ollama Cloud / Local API client.

Handles calls to Ollama chat completions, supporting tool calling, streaming,
and the cloud models:
- nemotron-3-nano:30b
- nemotron-3-super
- nemotron-3-ultra
- gemma4:31b
- gpt-oss:20b
- gpt-oss:120b
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from ..config import Settings, get_settings
from .http import ProviderError, get_json, post_json

OLLAMA_PREFIX = "ollama/"

OLLAMA_CLOUD_MODELS = {
    "nemotron-3-nano:30b": {"context": 128_000, "tools": True, "reasoning": False},
    "nemotron-3-super": {"context": 262_144, "tools": True, "reasoning": True},
    "nemotron-3-ultra": {"context": 1_000_000, "tools": True, "reasoning": True},
    "gemma4:31b": {"context": 262_144, "tools": True, "reasoning": False},
    "gpt-oss:20b": {"context": 128_000, "tools": True, "reasoning": False},
    "gpt-oss:120b": {"context": 262_144, "tools": True, "reasoning": True},
}


def normalize_ollama_model_id(model_id: str) -> str:
    """Strip ollama/ prefix if present."""
    if model_id.startswith(OLLAMA_PREFIX):
        return model_id[len(OLLAMA_PREFIX):]
    return model_id


def is_ollama(model_id: str) -> bool:
    clean = normalize_ollama_model_id(model_id)
    return model_id.startswith(OLLAMA_PREFIX) or clean in OLLAMA_CLOUD_MODELS


@dataclass(frozen=True)
class OllamaToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class OllamaReply:
    text: str
    model: str
    tool_calls: list[OllamaToolCall]
    input_tokens: int | None = None
    output_tokens: int | None = None


def ollama_headers(settings: Settings) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if settings.ollama_api_key:
        headers["Authorization"] = f"Bearer {settings.ollama_api_key}"
    return headers


def generate_ollama_chat(
    *,
    model: str,
    messages: list[dict[str, Any]],
    settings: Settings,
    tools: list[dict[str, Any]] | None = None,
    temperature: float | None = None,
    timeout: float = 120.0,
) -> OllamaReply:
    """Send a chat completion request to the Ollama API."""
    clean_model = normalize_ollama_model_id(model)
    base_url = settings.ollama_base_url.rstrip("/")

    # Use standard /v1/chat/completions endpoint supported by Ollama
    endpoint = f"{base_url}/v1/chat/completions"

    payload: dict[str, Any] = {
        "model": clean_model,
        "messages": messages,
        "stream": False,
    }
    if temperature is not None:
        payload["temperature"] = temperature
    if tools:
        payload["tools"] = tools

    try:
        data = post_json(
            endpoint,
            payload,
            headers=ollama_headers(settings),
            timeout=timeout,
            provider_name="Ollama",
        )
    except ProviderError:
        # Fallback to native /api/chat if /v1/ is not available
        native_endpoint = f"{base_url}/api/chat"
        native_payload = {
            "model": clean_model,
            "messages": messages,
            "stream": False,
        }
        if tools:
            native_payload["tools"] = tools
        data = post_json(
            native_endpoint,
            native_payload,
            headers=ollama_headers(settings),
            timeout=timeout,
            provider_name="Ollama",
        )

    # Parse response
    content = ""
    tool_calls: list[OllamaToolCall] = []

    if "choices" in data and data["choices"]:
        msg = data["choices"][0].get("message", {})
        content = msg.get("content") or ""
        raw_tools = msg.get("tool_calls") or []
        for idx, t in enumerate(raw_tools):
            fn = t.get("function", {})
            name = fn.get("name", "")
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}
            tool_calls.append(
                OllamaToolCall(
                    id=t.get("id") or f"call_{idx}",
                    name=name,
                    arguments=args,
                )
            )
    elif "message" in data:
        # Native /api/chat response
        msg = data["message"]
        content = msg.get("content") or ""
        raw_tools = msg.get("tool_calls") or []
        for idx, t in enumerate(raw_tools):
            fn = t.get("function", {})
            tool_calls.append(
                OllamaToolCall(
                    id=f"call_{idx}",
                    name=fn.get("name", ""),
                    arguments=fn.get("arguments") or {},
                )
            )

    usage = data.get("usage", {})
    return OllamaReply(
        text=content.strip(),
        model=clean_model,
        tool_calls=tool_calls,
        input_tokens=usage.get("prompt_tokens") or data.get("prompt_eval_count"),
        output_tokens=usage.get("completion_tokens") or data.get("eval_count"),
    )
