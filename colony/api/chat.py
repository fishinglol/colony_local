"""Chat endpoints: health, send a message, how full each agent's context is."""
import logging

from fastapi import APIRouter, HTTPException

from ..config import get_settings
from ..core.chat import handle_message
from ..core.context import report
from ..core.workspaces import WorkspaceNotFound, get_workspace, list_workspaces
from ..store.history import get_all_messages
from ..schemas import MessageRequest, MessageResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health")
def health() -> dict:
    s = get_settings()
    return {
        "status": "ok",
        "has_ollama_key": bool(s.ollama_api_key),
        "mock_mode": s.mock_mode,
        "data_dir": str(s.data_dir),
        "workspaces": len(list_workspaces()),
    }


@router.post("/messages", response_model=MessageResponse)
def post_message(request: MessageRequest) -> MessageResponse:
    """Send a message into a workspace, get a reply. The decider picks the agent unless role_id is set."""
    try:
        return handle_message(request)
    except WorkspaceNotFound as exc:
        raise HTTPException(status_code=404, detail="That workspace doesn't exist.") from exc
    except Exception as exc:
        logger.exception("Unexpected error in /messages")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/context")
def get_context(workspace_id: str | None = None) -> dict:
    """How full each of this workspace's agents' context windows is (the prompt size OpenClaw reported for each agent's last turn)."""
    try:
        workspace = get_workspace(workspace_id)
    except WorkspaceNotFound as exc:
        raise HTTPException(status_code=404, detail="That workspace doesn't exist.") from exc
    return {"agents": report(workspace.id, workspace.roles, get_settings(), len(get_all_messages(workspace.id)))}


@router.get("/activity")
def get_activity_status(workspace_id: str | None = None) -> dict:
    """Live activity status of the currently running turn in a workspace."""
    try:
        ws_id = get_workspace(workspace_id).id
    except WorkspaceNotFound:
        ws_id = workspace_id or "local"
    from ..core.activity import get_activity
    return get_activity(ws_id)


@router.get("/openclaw/status")
def openclaw_status() -> dict:
    """Check connectivity and health of OpenClaw Gateway."""
    from ..engine.openclaw import get_openclaw_status
    return get_openclaw_status(get_settings())

