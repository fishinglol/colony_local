"""Background review: every N turns the model reads the recent chat and updates USER.md,
MEMORY.md and the skill/knowledge files. Never allowed to break a chat turn."""
import json
import threading

from ..config import get_settings
from ..llm.http import ProviderError
from ..llm.providers import complete_chat
from ..store.history import get_recent_messages
from .files import (
    LOCK, MAX_SKILLS, MEMORY_MAX_CHARS, SKILL_MAX_CHARS, USER_MAX_CHARS,
    create_item_file, enforce_cap, item_summaries, list_files, memory_md_path, patch_item_file,
    read_state, read_text, user_md_path, write_state, write_text_atomic,
)
from .safety import sanitize

_REVIEW_MESSAGE_LIMIT = 16
_ENTRY_PREVIEW_CHARS = 60


# ── turn counting + trigger ───────────────────────────────────────────────────

def note_turn(user_id: str) -> bool:
    interval = get_settings().self_improve_interval_turns
    if interval <= 0:
        return False
    with LOCK:
        state = read_state(user_id)
        state["turns_since_review"] = int(state.get("turns_since_review", 0)) + 1
        due = state["turns_since_review"] >= interval
        if due:
            state["turns_since_review"] = 0
        write_state(user_id, state)
    return due


def maybe_review_in_background(user_id: str, conversation_id: str) -> None:
    try:
        settings = get_settings()
        if not settings.self_improve_enabled or settings.mock_mode:
            return
        if not (settings.openrouter_api_key or settings.openai_api_key):
            return
        if not note_turn(user_id):
            return
        threading.Thread(
            target=run_review, args=(user_id, conversation_id), daemon=True,
        ).start()
    except Exception as exc:
        print(f"[memory] trigger error: {exc!r} — skipping")


# ── the review ────────────────────────────────────────────────────────────────

_REVIEW_SYSTEM_PROMPT = (
    "You maintain two small markdown files plus a folder of SKILL files and a "
    "folder of KNOWLEDGE files, for one user of a local AI assistant.\n\n"
    f"USER.md = who the user is: persona, preferences, personal details. Hard cap {USER_MAX_CHARS} characters.\n"
    f"MEMORY.md = current situational context: what they're working on right now. Hard cap {MEMORY_MAX_CHARS} characters.\n"
    "SKILL FILES = one file per reusable how-to for this user's class of tasks.\n"
    f"KNOWLEDGE FILES = one file per standalone fact/dataset/process/api/metric. Cap {SKILL_MAX_CHARS} chars each.\n\n"
    "IMPORTANT — overflow becomes a NEW LINKED FILE, never a longer one: if a topic needs more than 2-3 lines "
    "of detail, do NOT stuff it into MEMORY.md or USER.md. Create a knowledge file and leave only a one-line "
    "pointer using a relative markdown link, e.g. 'See [Acme pricing](knowledge/acme-pricing.md) for details.'\n\n"
    "Review the conversation against the CURRENT file contents below. For USER.md and MEMORY.md, return the FULL "
    "replacement text ONLY if something changed — use null for a file that doesn't need to change. NEVER exceed a "
    "file's character cap; when content would grow past it, drop the least useful or most stale information.\n\n"
    "For skills and knowledge: prefer PATCHING an existing file over creating a near-duplicate.\n\n"
    "Reply with ONLY a JSON object, no markdown fences:\n"
    '{"user_md": "..." | null, "memory_md": "..." | null, '
    '"skills_add": [{"title": "...", "description": "...", "tags": ["..."], "body": "..."}], '
    '"skills_patch": [{"slug": "...", "body": "..."}], '
    '"knowledge_add": [{"title": "...", "type": "dataset|process|api|metric|note", '
    '"description": "...", "tags": ["..."], "body": "..."}], '
    '"knowledge_patch": [{"slug": "...", "body": "..."}]}\n'
    'Use empty arrays for fields with nothing. If nothing at all is worth saving, reply {"nothing": true}. '
    "Write in the user's language."
)


def _parse_review_json(raw: str) -> dict | None:
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        parsed = json.loads(raw[start:end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _transcript(conversation_id: str) -> str:
    lines: list[str] = []
    for msg in get_recent_messages(conversation_id, _REVIEW_MESSAGE_LIMIT):
        role = "User" if msg.get("role") == "user" else "Assistant"
        text = str(msg.get("content") or "").strip()
        if text:
            lines.append(f"{role}: {text[:500]}")
    return "\n".join(lines)


def _item_context_lines(user_id: str, kind: str) -> str:
    summaries = item_summaries(user_id, kind)
    if not summaries:
        return "(none)"
    return "\n".join(f"{s['slug']}: {s['title']} — {s['description']}" for s in summaries)


def _preview(text: str) -> str:
    return text[:_ENTRY_PREVIEW_CHARS] + ("…" if len(text) > _ENTRY_PREVIEW_CHARS else "")

def run_review(user_id: str, conversation_id: str) -> str | None:
    try:
        transcript = _transcript(conversation_id)
        if not transcript:
            return None
        with LOCK:
            user_md = read_text(user_md_path(user_id))
            memory_md = read_text(memory_md_path(user_id))
            skill_lines = _item_context_lines(user_id, "skills")
            knowledge_lines = _item_context_lines(user_id, "knowledge")

        user_msg = (
            f"CURRENT USER.md:\n{user_md.strip() or '(empty)'}\n\n"
            f"CURRENT MEMORY.md:\n{memory_md.strip() or '(empty)'}\n\n"
            f"CURRENT SKILL FILES (slug: title — description):\n{skill_lines}\n\n"
            f"CURRENT KNOWLEDGE FILES (slug: title — description):\n{knowledge_lines}\n\n"
            f"RECENT CONVERSATION:\n{transcript}"
        )
        raw = complete_chat(
            settings=get_settings(), system_prompt=_REVIEW_SYSTEM_PROMPT, user_prompt=user_msg,
            temperature=0.0, max_tokens=900,
        )
        result = _parse_review_json(raw)
        if not result or result.get("nothing"):
            return None
        return _apply_review(user_id, result)
    except (ProviderError, OSError, KeyError, ValueError) as exc:
        print(f"[memory] review error for {user_id}: {exc!r} — skipping")
        return None


def _apply_review(user_id: str, result: dict) -> str | None:
    new_user_md = sanitize(result.get("user_md"))
    new_memory_md = sanitize(result.get("memory_md"))
    skills_add = [i for i in (result.get("skills_add") or []) if isinstance(i, dict)]
    skills_patch = [i for i in (result.get("skills_patch") or []) if isinstance(i, dict)]
    knowledge_add = [i for i in (result.get("knowledge_add") or []) if isinstance(i, dict)]
    knowledge_patch = [i for i in (result.get("knowledge_patch") or []) if isinstance(i, dict)]

    summary_parts: list[str] = []
    with LOCK:
        if new_user_md:
            capped = enforce_cap(new_user_md, USER_MAX_CHARS, "USER.md")
            write_text_atomic(user_md_path(user_id), capped + "\n")
            summary_parts.append("อัปเดต USER.md")
        if new_memory_md:
            capped = enforce_cap(new_memory_md, MEMORY_MAX_CHARS, "MEMORY.md")
            write_text_atomic(memory_md_path(user_id), capped + "\n")
            summary_parts.append("อัปเดต MEMORY.md")

        count = len(list_files(user_id, "skills"))
        for item in skills_add:
            title = sanitize(item.get("title"))
            body = sanitize(item.get("body"))
            if not title or not body:
                continue
            if count >= MAX_SKILLS:
                break
            tags = [t for t in (item.get("tags") or []) if isinstance(t, str)][:5]
            description = sanitize(item.get("description")) or ""
            create_item_file(user_id, "skills", item_type="skill", title=title, description=description, tags=tags, body=body)
            count += 1
            summary_parts.append(f"สกิลใหม่: '{_preview(title)}'")
        for item in skills_patch:
            slug = str(item.get("slug") or "").strip()
            body = sanitize(item.get("body"))
            if slug and body and patch_item_file(user_id, "skills", slug, body):
                summary_parts.append(f"อัปเดตสกิล: '{slug}'")

        for item in knowledge_add:
            title = sanitize(item.get("title"))
            body = sanitize(item.get("body"))
            if not title or not body:
                continue
            tags = [t for t in (item.get("tags") or []) if isinstance(t, str)][:5]
            description = sanitize(item.get("description")) or ""
            create_item_file(user_id, "knowledge", item_type=str(item.get("type") or "note"), title=title, description=description, tags=tags, body=body)
            summary_parts.append(f"ความรู้ใหม่: '{_preview(title)}'")
        for item in knowledge_patch:
            slug = str(item.get("slug") or "").strip()
            body = sanitize(item.get("body"))
            if slug and body and patch_item_file(user_id, "knowledge", slug, body):
                summary_parts.append(f"อัปเดตความรู้: '{slug}'")

        if not summary_parts:
            return None
        state = read_state(user_id)
        summary = "เรียนรู้จากบทสนทนา — " + " · ".join(summary_parts)
        state["unseen_summary"] = summary
        write_state(user_id, state)
    print(f"[memory] {user_id}: {summary}")
    return summary
