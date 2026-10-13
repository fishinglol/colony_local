"""Colony Local — conversation history.

Lifted from backend/app/ai_ant/memory.py.
Changes:
- Imports use local config/json_store
- Removed project_id (not used in local)
- Data path: ~/.colony/history.json
"""
import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from ..config import get_settings
from .json_store import JsonStore


def _store() -> JsonStore:
    return JsonStore(
        get_settings().data_dir / "history.json",
        {"conversations": [], "trace_events": []},
    )


def create_conversation_id() -> str:
    return f"conv_{uuid4().hex}"


def create_message_id() -> str:
    return f"msg_{uuid4().hex}"


def append_exchange(
    *,
    conversation_id: str,
    user_message: str | None,
    assistant_response: dict[str, Any],
    channel: str = "auto",
    attachments: list[dict[str, Any]] | None = None,
) -> tuple[str | None, str]:
    """Append one user+assistant exchange. Returns (user_msg_id, assistant_msg_id).
    `user_message=None`: only the reply is stored (a teammate answering a handoff; nobody typed anything)."""
    now = datetime.now(timezone.utc).isoformat()
    store = _store()
    data = store.read()
    conversations = data.get("conversations", [])
    existing = next((c for c in conversations if c.get("id") == conversation_id), None)
    if not existing:
        existing = {
            "id": conversation_id,
            "title": (user_message or "")[:64],
            "messages": [],
            "created_at": now,
            "updated_at": now,
            "topic_summary": None,
        }
        conversations.insert(0, existing)

    user_msg_id = create_message_id() if user_message is not None else None
    assistant_msg_id = create_message_id()
    existing["updated_at"] = now
    existing["messages"].extend(([
        {
            "id": user_msg_id,
            "role": "user",
            "content": user_message,
            "channel": channel,
            **({"attachments": attachments} if attachments else {}),
            "created_at": now,
            "evicted": False,
            "evicted_to": None,
            "topic_status": None,
            "importance": None,
            "topic_confidence": None,
            "evict_eligible_since_turn": None,
        }] if user_message is not None else []) + [
        {
            "id": assistant_msg_id,
            "role": "assistant",
            "content": assistant_response.get("reply", ""),
            "metadata": assistant_response,
            "created_at": now,
        },
    ])
    data["conversations"] = conversations
    store.write(data)
    try:
        from .sqlite_history import append_exchange_sqlite
        append_exchange_sqlite(
            conversation_id=conversation_id,
            user_message=user_message,
            assistant_response=assistant_response,
            channel=channel,
            attachments=attachments,
        )
    except Exception:
        pass
    return user_msg_id, assistant_msg_id


def get_recent_messages(conversation_id: str, limit: int = 16) -> list[dict[str, Any]]:
    """Unfiltered — includes evicted messages (for self_improve review)."""
    data = _store().read()
    for c in data.get("conversations", []):
        if c.get("id") == conversation_id:
            return c.get("messages", [])[-limit:]
    return []


def get_all_messages(conversation_id: str) -> list[dict[str, Any]]:
    """Unfiltered, unbounded — for context_gate bookkeeping."""
    data = _store().read()
    for c in data.get("conversations", []):
        if c.get("id") == conversation_id:
            return c.get("messages", [])
    return []


def get_prompt_messages(conversation_id: str, limit: int = 16) -> list[dict[str, Any]]:
    """Like get_recent_messages but filters out evicted messages first."""
    messages = [m for m in get_all_messages(conversation_id) if not m.get("evicted")]
    return messages[-limit:]


def count_user_messages(conversation_id: str) -> int:
    return sum(1 for m in get_all_messages(conversation_id) if m.get("role") == "user")


def get_topic_summary(conversation_id: str) -> str | None:
    data = _store().read()
    for c in data.get("conversations", []):
        if c.get("id") == conversation_id:
            return c.get("topic_summary")
    return None


def set_topic_summary(conversation_id: str, summary: str) -> None:
    store = _store()
    data = store.read()
    for c in data.get("conversations", []):
        if c.get("id") == conversation_id:
            c["topic_summary"] = summary
            store.write(data)
            return


def tag_message_topic(
    conversation_id: str,
    message_id: str,
    *,
    status: str,
    importance: str,
    confidence: float,
    current_turn_index: int,
) -> None:
    store = _store()
    data = store.read()
    for c in data.get("conversations", []):
        if c.get("id") != conversation_id:
            continue
        for msg in c.get("messages", []):
            if msg.get("id") != message_id:
                continue
            msg["topic_status"] = status
            msg["importance"] = importance
            msg["topic_confidence"] = confidence
            if status == "off_topic" or importance == "unimportant":
                msg["evict_eligible_since_turn"] = current_turn_index
            store.write(data)
            return


def evict_message(conversation_id: str, message_id: str, *, evicted_to: str) -> None:
    store = _store()
    data = store.read()
    for c in data.get("conversations", []):
        if c.get("id") != conversation_id:
            continue
        messages = c.get("messages", [])
        for i, msg in enumerate(messages):
            if msg.get("id") == message_id:
                msg["evicted"] = True
                msg["evicted_to"] = evicted_to
                if i + 1 < len(messages) and messages[i + 1].get("role") == "assistant":
                    messages[i + 1]["evicted"] = True
                store.write(data)
                return


def list_conversations() -> list[dict[str, Any]]:
    """Return summary of all conversations (newest first)."""
    data = _store().read()
    result = []
    for c in data.get("conversations", []):
        result.append({
            "id": c.get("id", ""),
            "title": c.get("title", ""),
            "updated_at": c.get("updated_at", ""),
        })
    return result


def archive_before(conversation_id: str, keep_last: int) -> int:
    """Move every message except the last `keep_last` out of the conversation into
    ~/.colony/archive/<conversation_id>/<timestamp>.json, so a conversation the user started over ("/new") stays small
    for the app but is kept. The file is written before anything is removed. Returns how many messages moved."""
    store = _store()
    data = store.read()
    for c in data.get("conversations", []):
        if c.get("id") != conversation_id:
            continue
        messages = c.get("messages", [])
        old = messages[:-keep_last] if keep_last else list(messages)
        if not old:
            return 0
        now = datetime.now(timezone.utc)
        folder = get_settings().data_dir / "archive" / conversation_id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{now.strftime('%Y%m%d-%H%M%S')}.json").write_text(
            json.dumps({"conversation_id": conversation_id, "archived_at": now.isoformat(), "messages": old},
                       ensure_ascii=False, indent=1), encoding="utf-8")
        c["messages"] = messages[len(old):]
        store.write(data)
        return len(old)
    return 0


def delete_conversation(conversation_id: str) -> None:
    store = _store()
    data = store.read()
    data["conversations"] = [c for c in data.get("conversations", []) if c.get("id") != conversation_id]
    store.write(data)
