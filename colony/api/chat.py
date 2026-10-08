"""Chat endpoints: health, send a message, how full each agent's context is."""
import logging

from fastapi import APIRouter, HTTPException

from ..config import get_settings
from ..core.chat import handle_message
from ..core.context import report
from ..core.workspaces import WorkspaceNotFound, get_workspace, list_workspaces
from ..engine.pi import find_pi
from ..schemas import MessageRequest, MessageResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health")
def health() -> dict:
    s = get_settings()
    return {
        "status": "ok",
        "has_openrouter_key": bool(s.openrouter_api_key),
        "has_openai_key": bool(s.openai_api_key),
        "mock_mode": s.mock_mode,
        "data_dir": str(s.data_dir),
        "jev_model": s.jev_model,
        "workspaces": len(list_workspaces()),
        "tools": {"pi_installed": bool(find_pi(s))},
    }


@router.post("/messages", response_model=MessageResponse)
def post_message(request: MessageRequest) -> MessageResponse:
    """Send a message into a workspace, get a reply. Jev picks the agent unless role_id is set."""
    try:
        return handle_message(request)
    except WorkspaceNotFound as exc:
        raise HTTPException(status_code=404, detail="That workspace doesn't exist.") from exc
    except Exception as exc:
        logger.exception("Unexpected error in /messages")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/context")
def get_context(workspace_id: str | None = None) -> dict:
    """How full each of this workspace's agents' context windows is (estimates)."""
    try:
        workspace = get_workspace(workspace_id)
    except WorkspaceNotFound as exc:
        raise HTTPException(status_code=404, detail="That workspace doesn't exist.") from exc
    return {"agents": report(workspace.id, workspace.roles, get_settings())}


@router.get("/activity")
def get_activity_status(workspace_id: str | None = None) -> dict:
    """Live activity status of the currently running turn in a workspace."""
    try:
        ws_id = get_workspace(workspace_id).id
    except WorkspaceNotFound:
        ws_id = workspace_id or "local"
    from ..core.activity import get_activity
    return get_activity(ws_id)
