"""Read side of memory: what gets injected into every prompt, and explicit "remember this" saves."""
from pathlib import Path

from .files import (
    MAX_KNOWLEDGE_FILES, LOCK, create_item_file, list_files, memory_md_path,
    parse_frontmatter, read_state, read_text, user_md_path, write_state,
)
from .safety import sanitize

_RELEVANT_FILE_TOP_K = 3


# ── relevance ranking (token-hash, no embedding dep) ─────────────────────────
# Replaces enterprise.memory.memory_index.embed(). Good enough for <30 files.

def _token_set(text: str) -> set[str]:
    """Split text into lowercase tokens (no regex per project convention)."""
    tokens: set[str] = set()
    current: list[str] = []
    for ch in text.lower():
        if ch.isalnum():
            current.append(ch)
        elif current:
            tokens.add("".join(current))
            current = []
    if current:
        tokens.add("".join(current))
    return tokens


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _select_relevant_files(files: list[Path], query: str, top_k: int = _RELEVANT_FILE_TOP_K) -> list[Path]:
    if not files:
        return []
    query_tokens = _token_set(query)
    scored: list[tuple[float, Path]] = []
    for path in files:
        meta, body = parse_frontmatter(read_text(path))
        text = f"{meta.get('title', '')} {meta.get('description', '')} {' '.join(meta.get('tags') or [])} {body[:200]}"
        scored.append((_jaccard(query_tokens, _token_set(text)), path))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [path for _, path in scored[:top_k]]


# ── prompt injection (read side) ──────────────────────────────────────────────

def learned_context(user_id: str, query: str | None = None) -> str | None:
    """USER.md + MEMORY.md always, plus top-K relevant skill/knowledge files."""
    with LOCK:
        user_md = read_text(user_md_path(user_id)).strip()
        memory_md = read_text(memory_md_path(user_id)).strip()
        skill_files = list_files(user_id, "skills")
        knowledge_files = list_files(user_id, "knowledge")

    all_files = skill_files + knowledge_files
    selected = _select_relevant_files(all_files, query) if query else all_files

    bodies = []
    for path in selected:
        meta, body = parse_frontmatter(read_text(path))
        if body:
            bodies.append(f"{meta.get('title', path.stem)}: {body}")

    parts: list[str] = []
    if user_md:
        parts.append("Who this user is (USER.md):\n" + user_md)
    if memory_md:
        parts.append("Current situational memory (MEMORY.md):\n" + memory_md)
    if all_files and query:
        parts.append(
            f"(You have {len(all_files)} learned skill/knowledge files in total — "
            "only the ones most relevant to this message are included below.)"
        )
    if bodies:
        parts.append("Relevant learned skills/knowledge for this message:\n" + "\n".join(f"- {b}" for b in bodies))
    if query:
        from .episodic import search_daily_notes
        daily_hits = search_daily_notes(user_id, query, top_k=2)
        if daily_hits:
            hit_lines = [f"{h['date']}: {h['text']}" for h in daily_hits]
            parts.append("Relevant episodic memory from daily notes:\n" + "\n".join(hit_lines))
    return "\n\n".join(parts) if parts else None


def pop_unseen_summary(user_id: str) -> str | None:
    with LOCK:
        state = read_state(user_id)
        summary = state.get("unseen_summary")
        if summary:
            state["unseen_summary"] = None
            write_state(user_id, state)
    return summary


def save_explicit_memory(user_id: str, fact: str) -> str | None:
    clean = sanitize(fact)
    if not clean:
        return None
    with LOCK:
        if len(list_files(user_id, "knowledge")) >= MAX_KNOWLEDGE_FILES:
            return None
        title = clean.splitlines()[0][:60]
        return create_item_file(
            user_id, "knowledge",
            item_type="note", title=title, description=clean[:120],
            tags=["explicit-remember"], body=clean,
        )
