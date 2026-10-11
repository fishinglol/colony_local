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

# Steps (finished tool calls) of the running turns, per (workspace_id, role_id): agents of one workspace can answer at the same
# time, and each reply must carry only its own agent's steps.
_STEPS: dict[tuple[str, str], list[dict[str, Any]]] = {}


def _steps_key(workspace_id: str, role_id: str | None) -> tuple[str, str] | None:
    """The running turn a step belongs to; None when that agent has no turn running."""
    return (workspace_id, role_id) if (workspace_id, role_id) in _STEPS else None


def set_activity(
    workspace_id: str,
    *,
    step: str,
    detail: str,
    command: str | None = None,
    agent_name: str | None = None,
    model: str | None = None,
    role_id: str | None = None,
) -> None:
    """Update active execution state for a workspace. `role_id` (when known) starts collecting that agent's steps."""
    with _LOCK:
        if role_id is not None:
            _STEPS.setdefault((workspace_id, role_id), [])
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


def set_partial(workspace_id: str, role_id: str, agent_name: str, text: str) -> None:
    """The reply as far as the model has written it, shown by the UI while the turn is still running."""
    with _LOCK:
        curr = _ACTIVITIES.get(workspace_id)
        if curr is not None:
            curr["partial"] = {"role_id": role_id, "agent_name": agent_name, "text": text}


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


def add_step(workspace_id: str, step: dict[str, Any], role_id: str | None = None) -> None:
    """Record one finished tool call (core/trace.py::describe) in this agent's running turn. Ignored when it has no turn running."""
    with _LOCK:
        key = _steps_key(workspace_id, role_id)
        if key is not None:
            _STEPS[key].append({**step, "at": time.time()})


def take_steps(workspace_id: str, role_id: str | None = None) -> list[dict[str, Any]]:
    """The steps recorded so far in this agent's running turn."""
    with _LOCK:
        key = _steps_key(workspace_id, role_id)
        return list(_STEPS[key]) if key is not None else []


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
                "partial": None,
            }
        steps = sorted((st for (ws, _), items in _STEPS.items() if ws == workspace_id for st in items), key=lambda st: st["at"])
        return {**curr, "steps": steps}


def clear_activity(workspace_id: str, role_id: str | None = None) -> None:
    """Clear activity when a turn completes: the workspace's live status and this agent's steps (other agents' turns keep theirs)."""
    with _LOCK:
        _ACTIVITIES.pop(workspace_id, None)
        _STEPS.pop((workspace_id, role_id), None)
