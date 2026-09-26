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
