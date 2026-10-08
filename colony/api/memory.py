"""Endpoints that expose what the assistant has learned about the user (per workspace)."""
from fastapi import APIRouter, HTTPException

from .. import memory
from ..core.workspaces import WorkspaceNotFound, get_workspace

router = APIRouter()


def _workspace_id(workspace_id: str | None) -> str:
    try:
        return get_workspace(workspace_id).id
    except WorkspaceNotFound as exc:
        raise HTTPException(status_code=404, detail="That workspace doesn't exist.") from exc


@router.get("/memory/summary")
def get_memory_summary(workspace_id: str | None = None) -> dict:
    """Return the latest self-improvement summary, if any."""
    return {"summary": memory.pop_unseen_summary(_workspace_id(workspace_id))}


@router.get("/memory/context")
def get_memory_context(workspace_id: str | None = None) -> dict:
    """Return the current USER.md + MEMORY.md for inspection."""
    return {"context": memory.learned_context(_workspace_id(workspace_id)) or ""}


@router.get("/memory/daily")
def get_memory_daily(workspace_id: str | None = None) -> dict:
    """Return recent episodic daily notes for inspection."""
    ws = _workspace_id(workspace_id)
    notes = memory.list_daily_notes(ws, limit=14)
    return {"notes": [{"date": d, "content": c} for d, c in notes]}


@router.post("/memory/dream")
def trigger_memory_dream(workspace_id: str | None = None) -> dict:
    """Manually trigger background dreaming consolidation."""
    ws = _workspace_id(workspace_id)
    result = memory.run_dreaming_consolidation(ws)
    return result


@router.get("/memory/dreams")
def get_memory_dreams(workspace_id: str | None = None) -> dict:
    """Return the DREAMS.md consolidation audit log."""
    ws = _workspace_id(workspace_id)
    path = memory.dreams_md_path(ws)
    content = path.read_text(encoding="utf-8") if path.exists() else ""
    return {"dreams": content}
