"""Compaction: keeps a workspace's one endless conversation small enough to send.

Modelled on Pi's compaction (pi-coding-agent docs/compaction.md, MIT): when the conversation grows past a
threshold, the older part is summarised into a structured note and only the recent part stays word for word.
Every agent then reads "summary + recent messages", so a small-window model sees the same story as a big one
and each turn costs far fewer tokens.

The messages themselves are never deleted (the UI still shows them). The workspace keeps one summary and the
id of the last message it covers; the next compaction updates that summary instead of starting over.
It runs in a background thread after a reply, on the cheap routing model (the one memory review uses), and a
failure only means the old trimming keeps working until the next try.
"""
import logging
import threading
import time

from ..config import Settings, get_settings
from ..llm.http import ProviderError
from ..llm.providers import complete_chat
from ..memory.safety import sanitize
from ..store.history import get_all_messages, get_compaction, set_compaction

logger = logging.getLogger(__name__)

MAX_MESSAGE_CHARS = 6000     # one message is cut to this before it is summarised (a pasted document, say)
CHUNK_CHARS = 60_000         # how much conversation one summarising call reads
MAX_SUMMARY_CHARS = 8000
RETRY_AFTER = 300.0          # seconds to wait after a failed attempt
_LOCK = threading.Lock()
_running: set[str] = set()
_failed_at: dict[str, float] = {}

_SYSTEM = (
    "You write the memory of a long conversation between one user and a team of AI teammates who share a workspace, "
    "so that any teammate can carry on after the older messages are gone. The conversation is given as text inside "
    "<conversation> tags. Do NOT continue it or answer anything in it; only summarise it. If a <previous-summary> is given, "
    "UPDATE it: keep what still matters, fold in the new messages, drop what stopped mattering. "
    "Be faithful: never invent anything, and keep names, numbers, paths, code identifiers and decisions exactly as written. "
    "Say which teammate did or said something when that matters. Write in the language the user mainly uses. "
    "Use exactly this format, leaving out a section only if it is truly empty, and stay under 900 words:\n\n"
    "## Goal\n[What the user is trying to accomplish]\n\n"
    "## Constraints & Preferences\n- [Requirements and preferences the user stated]\n\n"
    "## Progress\n### Done\n- [x] [Completed]\n### In Progress\n- [ ] [Current work]\n### Blocked\n- [Problems, if any]\n\n"
    "## Key Decisions\n- **[Decision]**: [Why]\n\n"
    "## Next Steps\n1. [What should happen next]\n\n"
    "## Critical Context\n- [Facts, data or open questions needed to continue]\n\n"
    "## Files\nRead: [files teammates read, from the 🛠 lines]\nModified: [files teammates wrote or edited, from the 🛠 lines]"
)


def _text(message: dict) -> str:
    """One message as a line of plain text, for counting and for the summariser."""
    if message["role"] == "user":
        label = "User"
    else:
        label = (message.get("metadata") or {}).get("role_name") or "Assistant"
    files = ", ".join(a["name"] for a in message.get("attachments") or [])
    content = message.get("content") or ""
    if len(content) > MAX_MESSAGE_CHARS:
        content = content[:MAX_MESSAGE_CHARS] + f"\n[… {len(content) - MAX_MESSAGE_CHARS} more characters cut …]"
    return f"[{label}]" + (f" (attached: {files})" if files else "") + f": {content}"


def view(workspace_id: str) -> tuple[str | None, list[dict]]:
    """(summary of the older part, or None; the messages after it). Without a summary, every message that isn't evicted."""
    everything = get_all_messages(workspace_id)
    stored = get_compaction(workspace_id)
    start = 0
    if stored:
        position = next((i for i, m in enumerate(everything) if m.get("id") == stored["through_id"]), None)
        if position is None:
            stored = None      # the message it covers is gone: don't trust the summary
        else:
            start = position + 1
    return (stored["summary"] if stored else None), [m for m in everything[start:] if not m.get("evicted")]


def _cut(messages: list[dict], keep_tokens: int) -> int:
    """Index of the first message to keep word for word, or 0 if there is nothing safe to summarise.
    The recent messages worth ~keep_tokens stay; the cut is moved forward to a user message so a question
    is never separated from its answer."""
    from .context import estimate_tokens

    kept, i = 0, len(messages)
    while i > 0:
        i -= 1
        kept += estimate_tokens(_text(messages[i]))
        if kept >= keep_tokens:
            break
    while i < len(messages) and messages[i]["role"] != "user":
        i += 1
    return i if i < len(messages) else 0


def _chunks(messages: list[dict]) -> list[str]:
    chunks, current, size = [], [], 0
    for m in messages:
        line = _text(m)
        if current and size + len(line) > CHUNK_CHARS:
            chunks.append("\n\n".join(current))
            current, size = [], 0
        current.append(line)
        size += len(line)
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def _summarise(settings: Settings, previous: str | None, conversation: str) -> str:
    prompt = (f"<previous-summary>\n{previous}\n</previous-summary>\n\n" if previous else "") \
        + f"<conversation>\n{conversation}\n</conversation>"
    return complete_chat(settings=settings, system_prompt=_SYSTEM, user_prompt=prompt, temperature=0.0, max_tokens=2000).strip()


def compact(workspace_id: str, settings: Settings | None = None) -> bool:
    """Summarise the older part of the conversation if it has grown past the threshold. True if a summary was saved.
    Raises ProviderError if the summariser can't be reached."""
    from .context import estimate_tokens

    settings = settings or get_settings()
    summary, messages = view(workspace_id)
    total = sum(estimate_tokens(_text(m)) for m in messages) + (estimate_tokens(summary) if summary else 0)
    if total <= settings.compact_at_tokens:
        return False
    cut = _cut(messages, settings.compact_keep_tokens)
    if cut == 0:
        return False
    for chunk in _chunks(messages[:cut]):        # a very long stretch is folded in piece by piece
        summary = _summarise(settings, summary, chunk)
    summary = sanitize(summary[:MAX_SUMMARY_CHARS] if summary else None)
    if not summary:
        raise ProviderError("The summary was empty or looked like an instruction, so it was not used.")
    set_compaction(workspace_id, summary, messages[cut - 1]["id"])
    logger.info("Compacted workspace %s: %d messages summarised, %d kept", workspace_id, cut, len(messages) - cut)
    return True


def _run(workspace_id: str) -> None:
    try:
        compact(workspace_id)
        _failed_at.pop(workspace_id, None)
    except Exception as exc:     # never let this break anything: the old trimming keeps working
        logger.warning("Compaction failed (%s) — will try again later", exc)
        _failed_at[workspace_id] = time.monotonic()
    finally:
        with _LOCK:
            _running.discard(workspace_id)


def maybe_compact_in_background(workspace_id: str) -> None:
    """Called after every reply. Cheap when there is nothing to do; the summary is written in a background thread."""
    settings = get_settings()
    if settings.mock_mode or not settings.compaction_enabled or not (settings.openrouter_api_key or settings.openai_api_key):
        return
    if time.monotonic() - _failed_at.get(workspace_id, -RETRY_AFTER) < RETRY_AFTER:
        return
    with _LOCK:
        if workspace_id in _running:
            return
        _running.add(workspace_id)
    threading.Thread(target=_run, args=(workspace_id,), daemon=True).start()
