"""Tests for Ollama Client and Decider Routing."""
import json
import pytest

from colony.config import Settings
from colony.core.agents import DEFAULT_ROLES
from colony.core import decider
from colony.llm import ollama
from colony.llm.http import ProviderError


def test_normalize_and_detect_ollama_models():
    assert ollama.normalize_ollama_model_id("ollama/nemotron-3-nano:30b") == "nemotron-3-nano:30b"
    assert ollama.normalize_ollama_model_id("gemma4:31b") == "gemma4:31b"

    assert ollama.is_ollama("nemotron-3-nano:30b") is True
    assert ollama.is_ollama("nemotron-3-super") is True
    assert ollama.is_ollama("nemotron-3-ultra") is True
    assert ollama.is_ollama("gemma4:31b") is True
    assert ollama.is_ollama("gpt-oss:20b") is True
    assert ollama.is_ollama("gpt-oss:120b") is True
    assert ollama.is_ollama("ollama/custom-llama") is True
    assert ollama.is_ollama("anthropic/claude-sonnet-4.6") is False


def test_generate_ollama_chat_v1_endpoint(monkeypatch):
    settings = Settings(ollama_base_url="http://127.0.0.1:11434", ollama_api_key="secret-ollama")
    captured = {}

    def fake_post_json(url, payload, headers=None, timeout=None, provider_name=None):
        captured["url"] = url
        captured["payload"] = payload
        captured["headers"] = headers
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Hello from Nemotron!",
                    }
                }
            ],
            "usage": {"prompt_tokens": 12, "completion_tokens": 5},
        }

    monkeypatch.setattr(ollama, "post_json", fake_post_json)

    reply = ollama.generate_ollama_chat(
        model="nemotron-3-nano:30b",
        messages=[{"role": "user", "content": "hi"}],
        settings=settings,
    )

    assert captured["url"] == "http://127.0.0.1:11434/v1/chat/completions"
    assert captured["payload"]["model"] == "nemotron-3-nano:30b"
    assert captured["headers"]["Authorization"] == "Bearer secret-ollama"
    assert reply.text == "Hello from Nemotron!"
    assert reply.tool_calls == []
    assert reply.input_tokens == 12
    assert reply.output_tokens == 5


def test_generate_ollama_chat_parses_tool_calls(monkeypatch):
    settings = Settings(ollama_base_url="http://127.0.0.1:11434")

    def fake_post_json(url, payload, headers=None, timeout=None, provider_name=None):
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Let me read that file for you.",
                        "tool_calls": [
                            {
                                "id": "call_abc123",
                                "type": "function",
                                "function": {
                                    "name": "read_file",
                                    "arguments": '{"path": "README.md"}',
                                },
                            }
                        ],
                    }
                }
            ]
        }

    monkeypatch.setattr(ollama, "post_json", fake_post_json)

    reply = ollama.generate_ollama_chat(
        model="nemotron-3-super",
        messages=[{"role": "user", "content": "read README.md"}],
        settings=settings,
        tools=[{"type": "function", "function": {"name": "read_file"}}],
    )

    assert len(reply.tool_calls) == 1
    assert reply.tool_calls[0].id == "call_abc123"
    assert reply.tool_calls[0].name == "read_file"
    assert reply.tool_calls[0].arguments == {"path": "README.md"}


def test_generate_ollama_chat_fallback_to_api_chat(monkeypatch):
    settings = Settings(ollama_base_url="http://127.0.0.1:11434")
    calls = []

    def fake_post_json(url, payload, headers=None, timeout=None, provider_name=None):
        calls.append(url)
        if url.endswith("/v1/chat/completions"):
            raise ProviderError("Not Found", status=404)
        return {
            "message": {
                "role": "assistant",
                "content": "Native Ollama chat reply",
            }
        }

    monkeypatch.setattr(ollama, "post_json", fake_post_json)

    reply = ollama.generate_ollama_chat(
        model="gemma4:31b",
        messages=[{"role": "user", "content": "test fallback"}],
        settings=settings,
    )

    assert len(calls) == 2
    assert calls[0] == "http://127.0.0.1:11434/v1/chat/completions"
    assert calls[1] == "http://127.0.0.1:11434/api/chat"
    assert reply.text == "Native Ollama chat reply"


def test_decide_via_ollama_routes_to_agent(monkeypatch):
    settings = Settings(ollama_base_url="http://127.0.0.1:11434")

    def fake_chat(**kwargs):
        return ollama.OllamaReply(
            text='{"role_id": "writing", "confidence": 0.94}',
            model="nemotron-3-nano:30b",
            tool_calls=[],
        )

    monkeypatch.setattr(ollama, "generate_ollama_chat", fake_chat)

    res = decider.decide_via_ollama("write a blog post", list(DEFAULT_ROLES), settings)
    assert res is not None
    role_id, confidence = res
    assert role_id == "writing"
    assert confidence == 0.94


def test_decide_via_ollama_returns_none_on_error(monkeypatch):
    settings = Settings(ollama_base_url="http://127.0.0.1:11434")

    def fake_chat(**kwargs):
        raise RuntimeError("Ollama connection failed")

    monkeypatch.setattr(ollama, "generate_ollama_chat", fake_chat)

    res = decider.decide_via_ollama("test error", list(DEFAULT_ROLES), settings)
    assert res is None
