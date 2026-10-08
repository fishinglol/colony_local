"""Colony Local — Episodic Memory Tier (OpenClaw Architecture).

Manages daily notes per workspace:
  <data_dir>/self_improve/<workspace_id>/daily/YYYY-MM-DD.md
Records timeline observations, decisions, tool executions, and user requests.
Follows Colony-Local conventions: no regex, thread-safe, atomic file writes.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import get_settings
from .files import LOCK, parse_frontmatter, read_text, write_text_atomic


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _now_time_str() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S UTC")


def _daily_dir(workspace_id: str) -> Path:
    path = get_settings().data_dir / "self_improve" / workspace_id / "daily"
    path.mkdir(parents=True, exist_ok=True)
    return path


def daily_note_path(workspace_id: str, date_str: str | None = None) -> Path:
    d = date_str or _today_str()
    return _daily_dir(workspace_id) / f"{d}.md"


def append_daily_observation(
    workspace_id: str,
    text: str,
    *,
    origin: str = "agent",
    date_str: str | None = None,
    tag: str | None = None,
) -> None:
    """Append a timestamped observation to today's episodic daily note."""
    clean_text = text.strip()
    if not clean_text:
        return

    path = daily_note_path(workspace_id, date_str)
    timestamp = _now_time_str()

    tag_str = f" [{tag}]" if tag else ""
    entry = f"- `{timestamp}` ({origin}){tag_str}: {clean_text}\n"

    with LOCK:
        existing = read_text(path)
        if not existing:
            current_date = date_str or _today_str()
            header = f"# Daily Notes — {current_date}\n\n## Timeline\n"
            content = header + entry
        else:
            if "## Timeline" in existing:
                content = existing.rstrip() + "\n" + entry
            else:
                content = existing.rstrip() + "\n\n## Timeline\n" + entry
        write_text_atomic(path, content)


def read_daily_note(workspace_id: str, date_str: str | None = None) -> str:
    path = daily_note_path(workspace_id, date_str)
    with LOCK:
        return read_text(path)


def list_daily_notes(workspace_id: str, limit: int = 14) -> list[tuple[str, str]]:
    """Return list of (date_str, content) sorted descending by date."""
    d = _daily_dir(workspace_id)
    with LOCK:
        paths = sorted(d.glob("*.md"), reverse=True)[:limit]
        results = []
        for p in paths:
            date_key = p.stem
            results.append((date_key, read_text(p)))
        return results


def _token_set(text: str) -> set[str]:
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


def search_daily_notes(workspace_id: str, query: str, top_k: int = 3) -> list[dict[str, Any]]:
    """Search episodic notes using token similarity (no regex)."""
    notes = list_daily_notes(workspace_id, limit=30)
    if not notes or not query.strip():
        return []

    q_tokens = _token_set(query)
    scored: list[tuple[float, str, str]] = []

    for date_str, body in notes:
        lines = body.splitlines()
        for line in lines:
            trimmed = line.strip()
            if trimmed.startswith("- `") and len(trimmed) > 15:
                score = _jaccard(q_tokens, _token_set(trimmed))
                if score > 0.05:
                    scored.append((score, date_str, trimmed))

    scored.sort(key=lambda x: x[0], reverse=True)
    results = []
    for score, date_str, line in scored[:top_k]:
        results.append({
            "date": date_str,
            "score": round(score, 3),
            "text": line,
        })
    return results
