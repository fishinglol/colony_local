"""Colony Local — Background Dreaming & Memory Consolidation (OpenClaw Architecture).

Gated background consolidation that:
1. Gathers episodic daily notes (past 7 days).
2. Deterministic gate: filters duplicates, noise, and trivial entries.
3. Consolidates durable facts into MEMORY.md and USER.md within character budgets.
4. Logs consolidation history and audit trail into DREAMS.md.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import Settings, get_settings
from .episodic import list_daily_notes
from .files import (
    LOCK,
    MEMORY_MAX_CHARS,
    USER_MAX_CHARS,
    memory_md_path,
    read_text,
    user_md_path,
    write_text_atomic,
)
from .safety import sanitize

logger = logging.getLogger(__name__)

_DREAM_LOCK = threading.Lock()
_dream_running: set[str] = set()
_last_dream_at: dict[str, float] = {}
DREAM_INTERVAL = 300.0  # seconds between background dream runs per workspace


def _now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def dreams_md_path(workspace_id: str) -> Path:
    from .files import _user_dir
    return _user_dir(workspace_id) / "DREAMS.md"


def _extract_candidates_from_notes(notes: list[tuple[str, str]]) -> list[str]:
    """Deterministic filter (no regex): extract valid facts from daily notes."""
    candidates = []
    seen = set()

    for date_str, content in notes:
        for line in content.splitlines():
            trimmed = line.strip()
            # Expecting lines like: - `12:00:00 UTC` (agent): ...
            if not trimmed.startswith("- `"):
                continue
            colon_idx = trimmed.find("): ")
            if colon_idx != -1:
                fact_body = trimmed[colon_idx + 3:].strip()
            else:
                fact_body = trimmed.lstrip("- `").strip()

            if not fact_body or len(fact_body) < 8:
                continue

            lower = fact_body.lower()
            # Deterministic noise gate
            if any(lower.startswith(skip) for skip in ("hello", "thanks", "ok", "yes", "sure", "got it")):
                continue

            clean = sanitize(fact_body)
            if clean and clean not in seen:
                seen.add(clean)
                candidates.append(clean)

    return candidates


def run_dreaming_consolidation(
    workspace_id: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Execute dreaming consolidation pass for a workspace."""
    notes = list_daily_notes(workspace_id, limit=7)
    if not notes:
        return {"status": "skipped", "reason": "no episodic daily notes", "promoted": 0}

    candidates = _extract_candidates_from_notes(notes)
    if not candidates:
        return {"status": "skipped", "reason": "no valid candidates", "promoted": 0}

    with LOCK:
        mem_path = memory_md_path(workspace_id)
        existing_mem = read_text(mem_path).strip()
        existing_mem_lines = {l.strip() for l in existing_mem.splitlines() if l.strip()}

        user_path = user_md_path(workspace_id)
        existing_user = read_text(user_path).strip()
        existing_user_lines = {l.strip() for l in existing_user.splitlines() if l.strip()}

        promoted_mem: list[str] = []
        promoted_user: list[str] = []

        for cand in candidates:
            cand_bullet = f"- {cand}"
            lower = cand.lower()
            is_user = "user preference:" in lower or "user identity:" in lower or lower.startswith("user ")

            if is_user:
                if cand_bullet in existing_user_lines or cand in existing_user:
                    continue
                promoted_user.append(cand_bullet)
            else:
                if cand_bullet in existing_mem_lines or cand in existing_mem:
                    continue
                promoted_mem.append(cand_bullet)

        if not promoted_mem and not promoted_user:
            return {"status": "noop", "message": "all facts already consolidated", "promoted": 0}

        # Update MEMORY.md
        if promoted_mem:
            header = "# Project Situational Memory (MEMORY.md)\n"
            base = existing_mem or header
            new_mem = base.rstrip() + "\n" + "\n".join(promoted_mem) + "\n"
            if len(new_mem) > MEMORY_MAX_CHARS:
                # Prune oldest lines if exceeding budget
                lines = new_mem.splitlines()
                while len("\n".join(lines) + "\n") > MEMORY_MAX_CHARS and len(lines) > 5:
                    lines.pop(2)  # remove line right below header
                new_mem = "\n".join(lines) + "\n"
            write_text_atomic(mem_path, new_mem)

        # Update USER.md
        if promoted_user:
            header = "# User Profile & Preferences (USER.md)\n"
            base = existing_user or header
            new_user = base.rstrip() + "\n" + "\n".join(promoted_user) + "\n"
            if len(new_user) > USER_MAX_CHARS:
                lines = new_user.splitlines()
                while len("\n".join(lines) + "\n") > USER_MAX_CHARS and len(lines) > 5:
                    lines.pop(2)
                new_user = "\n".join(lines) + "\n"
            write_text_atomic(user_path, new_user)

        # Log dreaming consolidation to DREAMS.md
        total_promoted = len(promoted_mem) + len(promoted_user)
        dreams_path = dreams_md_path(workspace_id)
        existing_dreams = read_text(dreams_path)
        log_entry = (
            f"## [Dreaming Sweep — {_now_str()}]\n"
            f"- Candidates scanned: {len(candidates)}\n"
            f"- Promoted to MEMORY.md: {len(promoted_mem)}\n"
            f"- Promoted to USER.md: {len(promoted_user)}\n\n"
        )
        write_text_atomic(dreams_path, existing_dreams + log_entry)

    logger.info("Dreaming consolidation completed for %s: %d promoted", workspace_id, total_promoted)
    return {
        "status": "ok",
        "candidates": len(candidates),
        "promoted_memory": len(promoted_mem),
        "promoted_user": len(promoted_user),
        "total_promoted": total_promoted,
    }


def _dream_worker(workspace_id: str) -> None:
    try:
        run_dreaming_consolidation(workspace_id)
        _last_dream_at[workspace_id] = time.monotonic()
    except Exception as exc:
        logger.warning("Background dreaming failed for workspace %s: %s", workspace_id, exc)
    finally:
        with _DREAM_LOCK:
            _dream_running.discard(workspace_id)


def maybe_dream_in_background(workspace_id: str) -> None:
    """Schedule dreaming consolidation in the background if interval elapsed."""
    now = time.monotonic()
    last = _last_dream_at.get(workspace_id, 0.0)
    if now - last < DREAM_INTERVAL:
        return

    with _DREAM_LOCK:
        if workspace_id in _dream_running:
            return
        _dream_running.add(workspace_id)

    threading.Thread(target=_dream_worker, args=(workspace_id,), daemon=True).start()
