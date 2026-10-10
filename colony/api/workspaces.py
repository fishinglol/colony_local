"""Workspace endpoints: list, create, rename / set the project folder, delete, read the conversation."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..core.agents import Mode
from ..core.project_folder import project_folder
from ..core.workspaces import (
    Workspace, WorkspaceNotFound, create_workspace, delete_workspace, get_workspace, list_workspaces, update_workspace,
)
from ..store.history import get_all_messages

router = APIRouter()


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    folder: str | None = None
    copy_agents_from: str | None = None   # another workspace's id; None = the default team


class WorkspaceUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=60)
    folder: str | None = None             # "" = chat only
    mode: Mode | None = None


def view(workspace: Workspace) -> dict:
    folder, source = project_folder(workspace.folder)
    return {
        "id": workspace.id, "name": workspace.name, "created_at": workspace.created_at,
        "folder": workspace.folder, "effective_folder": str(folder) if folder else None, "folder_source": source, "mode": workspace.mode,
        "agents": [{"id": r.id, "name": r.name, "model": r.model} for r in workspace.roles],
    }


def _not_found(exc: WorkspaceNotFound) -> HTTPException:
    return HTTPException(status_code=404, detail="That workspace doesn't exist.")


@router.get("/workspaces")
def get_workspaces() -> dict:
    return {"workspaces": [view(w) for w in list_workspaces()]}


@router.post("/workspaces")
def post_workspace(payload: WorkspaceCreate) -> dict:
    try:
        return view(create_workspace(payload.name, payload.folder, payload.copy_agents_from))
    except WorkspaceNotFound as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/workspaces/{workspace_id}")
def patch_workspace(workspace_id: str, payload: WorkspaceUpdate) -> dict:
    try:
        return view(update_workspace(workspace_id, name=payload.name, folder=payload.folder, mode=payload.mode))
    except WorkspaceNotFound as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/workspaces/{workspace_id}")
def remove_workspace(workspace_id: str) -> dict:
    try:
        delete_workspace(workspace_id)
    except WorkspaceNotFound as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok"}


@router.get("/workspaces/{workspace_id}/messages")
def get_workspace_messages(workspace_id: str) -> dict:
    """Every message of the workspace's conversation, all rooms (group chat and direct chats)."""
    try:
        workspace = get_workspace(workspace_id)
    except WorkspaceNotFound as exc:
        raise _not_found(exc) from exc
    return {"workspace_id": workspace.id, "messages": get_all_messages(workspace.id)}
