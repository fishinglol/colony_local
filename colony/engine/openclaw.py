"""Colony Local — OpenClaw Gateway Engine Bridge.

Wires Colony UI and workspaces directly into the OpenClaw Gateway
(running locally on port 18789 by default).

Routes chat turns through OpenClaw's /v1/chat/completions endpoint,
leveraging OpenClaw's native multi-agent scheduling, Ollama/Cloud models,
sandboxed tools (bash/read/write), and SQLite episodic memory.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from ..config import Settings, get_settings
from ..core.activity import add_action, set_activity
from ..llm.http import ProviderError

logger = logging.getLogger(__name__)


@dataclass
class OpenClawTurnResult:
    reply: str
    model: str
    actions: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)


def resolve_agent_target(agent_id: str | None) -> str:
    """Sanitize agent_id for OpenClaw routing (plain string operations, no regex)."""
    if not agent_id:
        return "main"
    chars = []
    for c in agent_id:
        if c.isalnum() or c in ("-", "_"):
            chars.append(c)
        else:
            chars.append("-")
    cleaned = "".join(chars).strip("-")
    return cleaned or "main"


def build_session_user(
    workspace_id: str,
    agent_id: str | None,
    channel: str | None = None,
) -> str:
    """Stable per-conversation session identifier passed as the OpenAI `user` field."""
    ws = "".join(c for c in workspace_id if c.isalnum() or c in ("-", "_")) or "default"
    ch = "".join(c for c in (channel or "main") if c.isalnum() or c in ("-", "_")) or "main"
    ag = "".join(c for c in (agent_id or "anon") if c.isalnum() or c in ("-", "_")) or "anon"
    return f"ome-{ws}-{ch}-{ag}"


def is_openclaw_available(settings: Settings | None = None) -> bool:
    """Quick non-blocking probe to verify OpenClaw Gateway is reachable."""
    s = settings or get_settings()
    if not s.openclaw_gateway_enabled:
        return False
    url = f"{s.openclaw_gateway_url.rstrip('/')}/health"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=0.8) as resp:
            return resp.status in (200, 204)
    except Exception:
        # Fallback probe to root
        try:
            req = urllib.request.Request(s.openclaw_gateway_url.rstrip("/"), method="GET")
            with urllib.request.urlopen(req, timeout=0.8) as resp:
                return resp.status < 500
        except Exception:
            return False


def get_openclaw_status(settings: Settings | None = None) -> dict[str, Any]:
    """Detailed health status of OpenClaw Gateway."""
    s = settings or get_settings()
    available = is_openclaw_available(s)
    return {
        "enabled": s.openclaw_gateway_enabled,
        "available": available,
        "url": s.openclaw_gateway_url,
        "has_token": bool(s.openclaw_gateway_token),
    }


def run_openclaw_turn(
    *,
    settings: Settings,
    role_id: str,
    role_name: str,
    role_model: str,
    role_instructions: str,
    workspace_id: str,
    channel: str | None,
    user_message: str,
    history: list[dict] | None = None,
    system_prompt: str | None = None,
    timeout: float = 120.0,
) -> OpenClawTurnResult:
    """Execute one turn through OpenClaw Gateway.
    
    Streams status to ActivityTracker so live commands show up on Colony UI.
    """
    gateway_url = settings.openclaw_gateway_url.rstrip("/")
    endpoint = f"{gateway_url}/v1/chat/completions"

    agent_target = resolve_agent_target(role_id)
    model = f"openclaw/{agent_target}"
    session_user = build_session_user(workspace_id, role_id, channel)

    headers = {
        "Content-Type": "application/json",
    }
    if settings.openclaw_gateway_token:
        headers["Authorization"] = f"Bearer {settings.openclaw_gateway_token}"
    if role_model and "/" in role_model:
        headers["x-openclaw-model"] = role_model

    # Assemble messages
    messages: list[dict[str, Any]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    elif role_instructions:
        messages.append({"role": "system", "content": f"You are {role_name}. {role_instructions}"})

    for entry in (history or [])[-10:]:
        content = entry.get("content") or ""
        from_id = entry.get("fromAgentId") or entry.get("role") or ""
        if not content:
            continue
        if from_id in ("user", "human"):
            messages.append({"role": "user", "content": content})
        elif from_id == role_id:
            messages.append({"role": "assistant", "content": content})
        else:
            messages.append({"role": "user", "content": f"[{from_id}]: {content}"})

    messages.append({"role": "user", "content": user_message})

    payload = {
        "model": model,
        "messages": messages,
        "user": session_user,
        "stream": False,
    }

    set_activity(
        workspace_id=workspace_id,
        step="running",
        detail=f"OpenClaw Gateway executing turn ({role_name})...",
        agent_name=role_name,
        model=role_model,
    )

    try:
        body_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(endpoint, data=body_bytes, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        err_msg = exc.read().decode("utf-8", errors="replace")
        logger.error("OpenClaw Gateway HTTP %s: %s", exc.code, err_msg)
        raise ProviderError(
            f"OpenClaw Gateway request failed ({exc.code}): {err_msg[:200]}",
            status=exc.code,
            provider_message=err_msg,
        ) from exc
    except OSError as exc:
        logger.error("OpenClaw Gateway connection error: %s", exc)
        raise ProviderError(
            f"OpenClaw Gateway unreachable at {gateway_url} ({exc})",
            status=None,
        ) from exc

    # Parse response
    choices = data.get("choices") or []
    if not choices:
        raise ProviderError("OpenClaw Gateway returned no completion choices")

    msg = choices[0].get("message") or {}
    reply_text = (msg.get("content") or "").strip()
    actual_model = data.get("model") or role_model

    actions: list[str] = []
    # Check for tool_calls in message
    tool_calls = msg.get("tool_calls") or []
    for tc in tool_calls:
        fn = tc.get("function") or {}
        name = fn.get("name") or "tool"
        raw_args = fn.get("arguments") or ""
        desc = f"{name} {raw_args}".strip()
        actions.append(desc[:80])
        set_activity(workspace_id, step="tool", detail=f"Executing tool {name}", command=desc[:80], agent_name=role_name)
        add_action(workspace_id, desc[:80])

    # Check for custom action headers or notes
    notes = data.get("actions") or []
    if isinstance(notes, list):
        for n in notes:
            if isinstance(n, str) and n not in actions:
                actions.append(n)

    return OpenClawTurnResult(
        reply=reply_text,
        model=actual_model,
        actions=actions,
    )
