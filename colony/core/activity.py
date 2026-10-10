"""Colony Local — Real-Time Activity & Status Tracker (OpenClaw Architecture).

Tracks live execution status, current phase, active tool/command, and action trail
so the user has complete visibility into what the system is executing in real time.
"""
from __future__ import annotations

import threading
import time
from typing import Any

_LOCK = threading.RLock()

# Mapping workspace_id -> activity state
_ACTIVITIES: dict[str, dict[str, Any]] = {}


def set_activity(
    workspace_id: str,
    *,
    step: str,
    detail: str,
    command: str | None = None,
    agent_name: str | None = None,
    model: str | None = None,
) -> None:
    """Update active execution state for a workspace."""
    with _LOCK:
        curr = _ACTIVITIES.get(workspace_id) or {
            "workspace_id": workspace_id,
            "actions": [],
            "started_at": time.time(),
        }
        curr.update({
            "active": True,
            "step": step,
            "detail": detail,
            "command": command or curr.get("command"),
            "agent_name": agent_name or curr.get("agent_name"),
            "model": model or curr.get("model"),
            "updated_at": time.time(),
        })
        _ACTIVITIES[workspace_id] = curr


def add_action(workspace_id: str, action: str) -> None:
    """Record a completed tool/command action in the active trace."""
    clean = action.strip()
    if not clean:
        return
    with _LOCK:
        curr = _ACTIVITIES.get(workspace_id)
        if curr is not None:
            actions: list[str] = curr.setdefault("actions", [])
            if clean not in actions:
                actions.append(clean)


def add_step(workspace_id: str, step: dict[str, Any]) -> None:
    """Record one finished tool call (core/trace.py::describe) in the active turn. Ignored when no turn is running."""
    with _LOCK:
        curr = _ACTIVITIES.get(workspace_id)
        if curr is not None:
            curr.setdefault("steps", []).append({**step, "at": time.time()})


def take_steps(workspace_id: str) -> list[dict[str, Any]]:
    """The steps recorded so far in this workspace's running turn."""
    with _LOCK:
        return list((_ACTIVITIES.get(workspace_id) or {}).get("steps", []))


def get_activity(workspace_id: str) -> dict[str, Any]:
    """Retrieve current real-time activity for a workspace."""
    with _LOCK:
        curr = _ACTIVITIES.get(workspace_id)
        if not curr or not curr.get("active"):
            return {
                "active": False,
                "step": "idle",
                "detail": "",
                "command": None,
                "agent_name": None,
                "model": None,
                "actions": [],
                "steps": [],
            }
        return dict(curr)


def clear_activity(workspace_id: str) -> None:
    """Clear activity when turn completes."""
    with _LOCK:
        _ACTIVITIES.pop(workspace_id, None)
