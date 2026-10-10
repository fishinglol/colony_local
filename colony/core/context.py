"""What each agent sees of a chat, and how full its context window is.

Every agent shares one conversation. Before a turn, the messages OpenClaw's session has not seen yet are labelled by speaker
("[Coder] ...") so a model can tell teammates apart. The context gauge shows the prompt size OpenClaw reported for each
agent's last turn (the real size of its session, which OpenClaw compacts itself) against the model's window.
"""
from dataclasses import dataclass

from ..config import Settings
from ..engine import openclaw
from ..llm.ollama import OLLAMA_CLOUD_MODELS, is_ollama, normalize_ollama_model_id
from . import attachments
from .agents import Role


def context_window(model_id: str, settings: Settings) -> int:
    """Max context (tokens) of a model: our table of the Ollama models, else the configured default."""
    info = OLLAMA_CLOUD_MODELS.get(normalize_ollama_model_id(model_id)) if is_ollama(model_id) else None
    return (info or {}).get("context", settings.ollama_context_window)


def supports_tools(model_id: str) -> bool:
    """Can this model call tools? Models we have no note on are assumed to."""
    info = OLLAMA_CLOUD_MODELS.get(normalize_ollama_model_id(model_id)) if is_ollama(model_id) else None
    return (info or {}).get("tools", True)


@dataclass(frozen=True)
class Sight:
    """What an agent can see of attached files."""
    settings: Settings
    workspace_id: str
    recent: frozenset       # ids of the messages whose files are sent in full


def _labelled(message: dict, seen: Sight) -> dict:
    content = message["content"]
    if message["role"] == "assistant":
        name = (message.get("metadata") or {}).get("role_name")
        return {"role": "assistant", "content": f"[{name}] {content}" if name else content}
    item = {"role": message["role"], "content": content}
    if message.get("attachments"):
        note, _ = attachments.render(seen.settings, seen.workspace_id, message["attachments"], recent=message.get("id") in seen.recent)
        item["content"] = content + note
    return item


def labelled_history(settings: Settings, workspace_id: str, messages: list[dict], next_media: int = 0) -> tuple[list[dict], list[str]]:
    """(the newest `history_max_messages` messages that have text, labelled by speaker; their ids)."""
    usable = [m for m in messages if m.get("content")]
    recent = usable[-settings.history_max_messages:] if settings.history_max_messages > 0 else usable
    # The new message's files count as one of the recent few; the rest of the budget goes to the newest earlier ones.
    with_files = [m["id"] for m in recent if m.get("attachments")]
    keep = attachments.KEEP_RECENT - (1 if next_media else 0)
    seen = Sight(settings, workspace_id, frozenset(with_files[-keep:] if keep > 0 else []))
    return [_labelled(m, seen) for m in recent], [m["id"] for m in recent]


def strip_self_label(reply: str, role_name: str) -> str:
    """Models sometimes copy the [Name] label style onto their own reply; remove it."""
    label = f"[{role_name}]"
    text = reply.lstrip()
    return text[len(label):].lstrip() if text.startswith(label) else reply


def report(workspace_id: str, roles: list[Role], settings: Settings, total_messages: int) -> list[dict]:
    """How full each agent's session is: the prompt size OpenClaw reported for its last turn (None before its first turn)."""
    rows = []
    for role in roles:
        window = context_window(role.model, settings)
        used = openclaw.last_prompt_tokens(settings, openclaw.agent_id_for(workspace_id, role.id))
        rows.append({
            "role_id": role.id, "name": role.name, "model": role.model,
            "window": window, "used_tokens": used,
            "percent": round(100 * used / window, 1) if used is not None else None,
            "messages_total": total_messages,
        })
    return rows
