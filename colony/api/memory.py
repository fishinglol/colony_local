"""Endpoints that show what the team remembers (per workspace): the plain files in its shared memory folder."""
from fastapi import APIRouter, HTTPException

from ..config import get_settings
from ..core.workspaces import WorkspaceNotFound, get_workspace
from ..engine.openclaw import memory_dir

router = APIRouter()


def _folder(workspace_id: str | None):
    try:
        return memory_dir(get_settings(), get_workspace(workspace_id).id)
    except WorkspaceNotFound as exc:
        raise HTTPException(status_code=404, detail="That workspace doesn't exist.") from exc


def _read(path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


@router.get("/memory/context")
def get_memory_context(workspace_id: str | None = None) -> dict:
    """USER.md and MEMORY.md as the agents see them."""
    folder = _folder(workspace_id)
    return {"context": "\n\n".join(t for t in (_read(folder / "USER.md"), _read(folder / "MEMORY.md")) if t)}


@router.get("/memory/daily")
def get_memory_daily(workspace_id: str | None = None) -> dict:
    """The newest daily notes (memory/YYYY-MM-DD.md)."""
    notes = sorted((_folder(workspace_id) / "memory").glob("*.md"), reverse=True)[:14]
    return {"notes": [{"date": p.stem, "content": _read(p)} for p in notes]}
