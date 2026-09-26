"""Attach files to a workspace's chat: upload one (JSON + base64, so no extra dependency), or fetch it back."""
import base64
import binascii

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..config import get_settings
from ..core import attachments
from ..core.workspaces import WorkspaceNotFound, get_workspace

router = APIRouter()


class Upload(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    data: str            # the file's bytes, base64


@router.post("/workspaces/{workspace_id}/attachments")
def upload(workspace_id: str, payload: Upload) -> dict:
    settings = get_settings()
    try:
        workspace = get_workspace(workspace_id)
        raw = base64.b64decode(payload.data, validate=True)
        return attachments.save(settings, workspace.id, payload.name, raw)
    except WorkspaceNotFound as exc:
        raise HTTPException(status_code=404, detail="That workspace doesn't exist.") from exc
    except (binascii.Error, ValueError) as exc:    # AttachmentError is a ValueError
        raise HTTPException(status_code=400, detail=str(exc) if isinstance(exc, attachments.AttachmentError) else "The file couldn't be read.") from exc


@router.get("/workspaces/{workspace_id}/attachments/{attachment_id}")
def download(workspace_id: str, attachment_id: str) -> FileResponse:
    settings = get_settings()
    ref = attachments.get(settings, workspace_id, attachment_id)
    if ref is None:
        raise HTTPException(status_code=404, detail="That file is gone.")
    headers = {"Content-Disposition": "inline", "X-Content-Type-Options": "nosniff"}
    return FileResponse(attachments.file_path(settings, workspace_id, attachment_id), media_type=ref["mime"], headers=headers)
