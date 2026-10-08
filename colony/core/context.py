"""What each agent sees of a chat, and how full its context window is.

Every agent shares one history, but models have very different context windows
(a free GLM has 32k, a Gemini has 1M). So before a model is called we:
  1. label who said what ("[Coder] ..."), so it can tell teammates apart;
  2. drop the oldest messages if the prompt wouldn't fit its window;
and the UI can ask how full each agent's window currently is.
Token counts are ESTIMATES (no tokenizer dependency) — good enough for a gauge.
"""
import math
import time
from dataclasses import dataclass

from .. import memory
from ..config import Settings
from ..llm.http import ProviderError, get_json
from ..llm.ollama import OLLAMA_CLOUD_MODELS, is_ollama, normalize_ollama_model_id
from ..llm.providers import OPENROUTER_BASE, build_messages
from . import attachments, compaction
from .agents import Role
from .models import known_context_window

FILL_LIMIT = 0.85  # never plan to fill more than this share of a window (rest = room for the reply)
_LIVE_TTL = 6 * 3600.0
_LIVE_RETRY = 600.0

_live_windows: dict[str, int] = {}
_live_tools: dict[str, bool] = {}     # model id -> whether OpenRouter says it can use tools
_live_info: dict[str, dict] = {}      # model id -> {name, inputs, reasoning, reasoning_levels}: what the model page shows

# Reasoning levels from lowest to highest; "none" (off) is handled separately.
REASONING_ORDER = ("minimal", "low", "medium", "high", "xhigh", "max")
_live_fetched_at = 0.0


def estimate_tokens(text: str) -> int:
    """Rough token count: ~4 characters per token for ASCII text, ~1.5 for Thai/CJK/emoji."""
    ascii_chars = sum(1 for ch in text if ord(ch) < 128)
    return math.ceil(ascii_chars / 4 + (len(text) - ascii_chars) / 1.5)


def _refresh_live_windows() -> None:
    """Fill the cache from OpenRouter's public model catalog (no key needed). Fails quietly."""
    global _live_fetched_at
    now = time.monotonic()
    try:
        data = get_json(f"{OPENROUTER_BASE}/models", timeout=5.0, provider_name="OpenRouter")
        _live_windows.clear()
        _live_tools.clear()
        _live_info.clear()
        for m in data.get("data") or []:
            if not (isinstance(m, dict) and m.get("id")):
                continue
            if isinstance(m.get("context_length"), int):
                _live_windows[m["id"]] = m["context_length"]
            params = m.get("supported_parameters")
            if isinstance(params, list):
                _live_tools[m["id"]] = "tools" in params
            inputs = (m.get("architecture") or {}).get("input_modalities")
            reasoning = m.get("reasoning") if isinstance(m.get("reasoning"), dict) else None
            levels = None
            if reasoning and isinstance(reasoning.get("supported_efforts"), list):
                offered = [x for x in REASONING_ORDER if x in reasoning["supported_efforts"]]
                levels = {"efforts": offered, "default": reasoning.get("default_effort"), "can_turn_off": not reasoning.get("mandatory")}
            _live_info[m["id"]] = {
                "reasoning_levels": levels,
                "name": m.get("name") if isinstance(m.get("name"), str) else "",
                "inputs": [str(x) for x in inputs] if isinstance(inputs, list) else None,
                "reasoning": ("reasoning" in params) if isinstance(params, list) else None,
            }
        _live_fetched_at = now
    except ProviderError:
        _live_fetched_at = now - _LIVE_TTL + _LIVE_RETRY  # try again in a few minutes, not every request


def _ensure_live_catalog() -> None:
    if time.monotonic() - _live_fetched_at > _LIVE_TTL or not _live_fetched_at:
        _refresh_live_windows()


def context_window(model_id: str, settings: Settings) -> int | None:
    """Max context (tokens): our table first, then OpenRouter's live catalog. None if unknown."""
    if model_id.startswith("kaggle/"):
        return settings.kaggle_context_window
    if is_ollama(model_id):
        clean = normalize_ollama_model_id(model_id)
        info = OLLAMA_CLOUD_MODELS.get(clean)
        return info.get("context", settings.ollama_context_window) if info else settings.ollama_context_window
    known = known_context_window(model_id)
    if known or settings.mock_mode:
        return known
    _ensure_live_catalog()
    return _live_windows.get(model_id)


def model_catalog(settings: Settings) -> dict[str, dict]:
    """Every model OpenRouter lists, with what it can do: {id: {name, context, tools, inputs, reasoning}}.
    Empty in mock mode or when OpenRouter can't be reached; a field is None when the catalog doesn't say."""
    if settings.mock_mode:
        return {}
    _ensure_live_catalog()
    return {
        model_id: {**info, "context": _live_windows.get(model_id), "tools": _live_tools.get(model_id)}
        for model_id, info in _live_info.items()
    }


def reasoning_param(model_id: str, level: str, settings: Settings) -> dict | None:
    """The `reasoning` field to send for an agent's chosen level, or None to leave the model on its own default.
    A level the model is known not to support (or "off" for a model that can't be switched off) is left out."""
    if level == "default":
        return None
    info = model_catalog(settings).get(model_id) or {}
    if info.get("reasoning") is False:            # listed, and it can't reason: nothing to set
        return None
    known = info.get("reasoning_levels")
    if known is not None:
        if level == "off" and not known["can_turn_off"]:
            return None
        if level != "off" and level not in known["efforts"]:
            return None
    return {"effort": "none" if level == "off" else level}


def supports_tools(model_id: str, settings: Settings) -> bool | None:
    """Can this model call tools (read/write files, run commands)? OpenRouter's catalog says.
    None = unknown (offline, mock mode, or a model the catalog doesn't list) — callers should allow it."""
    if is_ollama(model_id):
        clean = normalize_ollama_model_id(model_id)
        info = OLLAMA_CLOUD_MODELS.get(clean)
        return info.get("tools", True) if info else True
    if settings.mock_mode:
        return None
    _ensure_live_catalog()
    return _live_tools.get(model_id)


def input_modalities(model_id: str, settings: Settings) -> list[str] | None:
    """What kinds of input the model accepts per the catalog (text, image, file, audio, video). None = unknown."""
    if settings.mock_mode:
        return None
    _ensure_live_catalog()
    return (_live_info.get(model_id) or {}).get("inputs")


MEDIA_TOKENS = 1500   # rough size of one attached image/PDF/video for the window estimate


@dataclass(frozen=True)
class HistoryPlan:
    history: list[dict]   # messages to send, oldest first, agent-labelled
    attributed: bool      # True if any assistant message carries a [Name] label
    sent: int             # how many history messages this agent will see
    total: int            # how many exist in the chat
    tokens: int           # estimated size of the whole prompt (before the user's next message)
    window: int | None    # the model's context window, if known


def _labelled(message: dict, seen: "Sight") -> tuple[dict, bool]:
    content = message["content"]
    if message["role"] == "assistant":
        name = (message.get("metadata") or {}).get("role_name")
        if name:
            return {"role": "assistant", "content": f"[{name}] {content}"}, True
    item = {"role": message["role"], "content": content}
    if message.get("attachments"):
        note, media = attachments.render(
            seen.settings, seen.workspace_id, message["attachments"], inputs=seen.inputs,
            recent=message.get("id") in seen.recent, with_tools=seen.with_tools)
        item["content"] = content + note
        if media:
            item["media"] = media
    return item, False


@dataclass(frozen=True)
class Sight:
    """What one model can see of attached files."""
    settings: Settings
    workspace_id: str
    inputs: list[str] | None
    with_tools: bool
    recent: frozenset       # ids of the messages whose files are sent in full


def plan_history(*, model: str, role: Role, settings: Settings, memory_context: str | None,
                 messages: list[dict], next_message: str = "", workspace_id: str = "",
                 with_tools: bool = False, next_media: int = 0,
                 earlier_summary: str | None = None) -> HistoryPlan:
    usable = [m for m in messages if m.get("content")]
    limit = settings.history_max_messages
    recent = usable[-limit:] if limit > 0 else usable
    # The new message's files count as one of the recent few; the rest of the budget goes to the newest earlier ones.
    with_files = [m["id"] for m in recent if m.get("attachments")]
    keep = attachments.KEEP_RECENT - (1 if next_media else 0)
    seen = Sight(settings, workspace_id, input_modalities(model, settings), with_tools,
                 frozenset(with_files[-keep:] if keep > 0 else []))
    pairs = [_labelled(m, seen) for m in recent]

    def build(history: list[dict], attributed: bool) -> list[dict]:
        return build_messages(model, next_message, role.name, role.instructions, memory_context, history, attributed, earlier_summary)

    def size(history: list[dict], attributed: bool) -> int:
        return sum(estimate_tokens(m["content"]) for m in build(history, attributed)) \
            + MEDIA_TOKENS * (next_media + sum(len(m.get("media", [])) for m in history))

    window = context_window(model, settings)
    if window:
        budget = int(window * FILL_LIMIT) - settings.max_output_tokens
        while pairs and size([p[0] for p in pairs], any(p[1] for p in pairs)) > budget:
            pairs.pop(0)  # forget the oldest message first

    history = [p[0] for p in pairs]
    attributed = any(p[1] for p in pairs)
    return HistoryPlan(history, attributed, len(history), len(usable), size(history, attributed), window)


def strip_self_label(reply: str, role_name: str) -> str:
    """Models sometimes copy the [Name] label style onto their own reply; remove it."""
    label = f"[{role_name}]"
    text = reply.lstrip()
    return text[len(label):].lstrip() if text.startswith(label) else reply


def report(workspace_id: str, roles: list[Role], settings: Settings) -> list[dict]:
    """How full each agent's context window would be if it were asked something now."""
    summary, messages = compaction.view(workspace_id)
    last_question = next((m["content"] for m in reversed(messages) if m["role"] == "user"), None)
    memory_context = memory.learned_context(workspace_id, query=last_question)
    rows = []
    for role in roles:
        plan = plan_history(model=role.model, role=role, settings=settings, memory_context=memory_context,
                            messages=messages, workspace_id=workspace_id, earlier_summary=summary)
        rows.append({
            "role_id": role.id, "name": role.name, "model": role.model,
            "window": plan.window, "used_tokens": plan.tokens,
            "percent": round(100 * plan.tokens / plan.window, 1) if plan.window else None,
            "messages_sent": plan.sent, "messages_total": plan.total,
        })
    return rows
