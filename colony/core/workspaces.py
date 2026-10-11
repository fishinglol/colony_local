"""Workspaces: the top level of Colony Local.

A workspace is one project space. It has its own team of agents (each with its own model), ONE continuous
conversation that every agent sees (the group chat and each agent's direct chat are rooms inside it),
its own long-term memory, and its own project folder for agents with tools.

The workspace id doubles as its conversation id (history.json) and as its memory user (self_improve/<id>).
Stored in ~/.colony/workspaces.json. The first workspace ("Personal", id "local") is built from the old
single-space files the first time this runs.
"""
import json
import shutil
import threading
from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field

from ..engine import openclaw
from ..config import Settings, get_settings
from ..store.history import delete_conversation
from ..store.json_store import JsonStore
from .agents import DEFAULT_ROLES, Mode, Role, validate_roles
from .project_folder import check_folder

FIRST_WORKSPACE_ID = "local"   # also the id memory used before workspaces existed, so nothing moves
_LOCK = threading.RLock()


class WorkspaceNotFound(KeyError):
    pass


class Workspace(BaseModel):
    id: str
    name: str = Field(min_length=1, max_length=60)
    folder: str | None = None          # project folder for agents with tools (None = chat only)
    roles: list[Role]
    created_at: str
    mode: Mode = "auto"                 # how freely agents with tools may change things (see agents.apply_mode)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _store() -> JsonStore:
    return JsonStore(get_settings().data_dir / "workspaces.json", None)


def _new_project_folder(name: str) -> str:
    """A fresh project folder for a new workspace, under Settings.projects_dir: <name>, or <name> 2, 3... if that is taken."""
    safe = "".join(c if c.isalnum() or c in " -_" else "-" for c in name).strip(" -_") or "workspace"
    base = get_settings().projects_dir
    folder, n = base / safe, 2
    while folder.exists():
        folder, n = base / f"{safe} {n}", n + 1
    folder.mkdir(parents=True)
    return str(folder)


def _clean_name(name: str) -> str:
    name = " ".join(name.split())
    if not name:
        raise ValueError("Give the workspace a name.")
    return name[:60]


# ── first run: turn the old single space into the first workspace ─────────────────────────────

def _legacy_roles(settings: Settings) -> list[Role]:
    path = settings.data_dir / "roles.json"
    raw = []
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8")).get("roles") or []
        except (OSError, ValueError, AttributeError):
            raw = []
    roles = []
    for item in raw:
        try:
            roles.append(Role(**item))
        except (TypeError, ValueError):
            continue
    return roles or [r.model_copy(deep=True) for r in DEFAULT_ROLES]


def _merge_old_chats(settings: Settings) -> None:
    """All old chats become the first workspace's one conversation, in time order. The old file is kept."""
    path = settings.data_dir / "history.json"
    if not path.exists():
        return
    store = JsonStore(path, {"conversations": [], "trace_events": []})
    data = store.read()
    old = [c for c in data.get("conversations", []) if c.get("id") != FIRST_WORKSPACE_ID]
    if not old:
        return
    backup = path.with_name("history.json.bak-before-workspaces")
    if not backup.exists():
        shutil.copy2(path, backup)
    messages = [m for c in reversed(old) for m in c.get("messages", [])]
    messages.sort(key=lambda m: m.get("created_at") or "")      # stable: an exchange keeps its order
    kept = [c for c in data.get("conversations", []) if c.get("id") == FIRST_WORKSPACE_ID]
    now = _now()
    merged = kept[0] if kept else {"id": FIRST_WORKSPACE_ID, "title": "Personal", "created_at": now, "topic_summary": None}
    merged["messages"] = sorted(merged.get("messages", []) + messages, key=lambda m: m.get("created_at") or "")
    merged["updated_at"] = merged["messages"][-1].get("created_at", now) if merged["messages"] else now
    data["conversations"] = [merged]
    store.write(data)


def _first_workspace(settings: Settings) -> Workspace:
    folder = None
    if settings.workspace_dir:
        try:
            folder = str(check_folder(settings.workspace_dir))
        except ValueError:
            folder = None
    _merge_old_chats(settings)
    return Workspace(id=FIRST_WORKSPACE_ID, name="Personal", folder=folder, roles=_legacy_roles(settings), created_at=_now())


# ── the store ───────────────────────────────────────────────────────────────────────────────

def _load() -> list[Workspace]:
    path = get_settings().data_dir / "workspaces.json"
    raw = _store().read()
    if not isinstance(raw, dict) and path.exists() and path.stat().st_size > 8:
        shutil.copy2(path, path.with_name(f"workspaces.json.corrupt-{int(datetime.now().timestamp())}"))   # keep it, then start over
    workspaces = []
    for item in (raw.get("workspaces", []) if isinstance(raw, dict) else []):
        try:
            workspaces.append(Workspace(**item))
        except (TypeError, ValueError):
            continue
    if not workspaces:
        first = _first_workspace(get_settings())
        _save([first])
        return [first]
    return workspaces


def _save(workspaces: list[Workspace]) -> None:
    _store().write({"workspaces": [w.model_dump() for w in workspaces]})


def list_workspaces() -> list[Workspace]:
    with _LOCK:
        return _load()


def get_workspace(workspace_id: str | None) -> Workspace:
    """The workspace with this id; None means the first one. Raises WorkspaceNotFound."""
    workspaces = list_workspaces()
    if workspace_id is None:
        return workspaces[0]
    found = next((w for w in workspaces if w.id == workspace_id), None)
    if found is None:
        raise WorkspaceNotFound(workspace_id)
    return found


def create_workspace(name: str, folder: str | None = None, copy_agents_from: str | None = None) -> Workspace:
    """A new, empty workspace: its own conversation and memory. Its agents start as a copy of another
    workspace's team, or the default team. With no `folder` given it gets a new project folder of its own
    (folder "" means chat only, on purpose)."""
    with _LOCK:
        workspaces = _load()
        if copy_agents_from:
            source = next((w for w in workspaces if w.id == copy_agents_from), None)
            if source is None:
                raise WorkspaceNotFound(copy_agents_from)
            roles = [r.model_copy(deep=True) for r in source.roles]
        else:
            roles = [r.model_copy(deep=True) for r in DEFAULT_ROLES]
        name = _clean_name(name)
        if folder is None:
            folder = _new_project_folder(name)
        created = Workspace(
            id=f"ws_{uuid4().hex[:10]}", name=name, roles=roles, created_at=_now(),
            folder=str(check_folder(folder)) if folder and folder.strip() else None,
        )
        _save([*workspaces, created])
        return created


def update_workspace(workspace_id: str, *, name: str | None = None, folder: str | None = None,
                     mode: Mode | None = None) -> Workspace:
    """Rename, change the project folder (folder "" = chat only) and/or the mode."""
    with _LOCK:
        workspaces = _load()
        target = next((w for w in workspaces if w.id == workspace_id), None)
        if target is None:
            raise WorkspaceNotFound(workspace_id)
        if name is not None:
            target.name = _clean_name(name)
        if folder is not None:
            target.folder = str(check_folder(folder)) if folder.strip() else None
        if mode is not None:
            target.mode = mode
        _save(workspaces)
        return target


def delete_workspace(workspace_id: str) -> None:
    """Delete a workspace with its conversation and memory. The last one can't be deleted."""
    with _LOCK:
        workspaces = _load()
        if not any(w.id == workspace_id for w in workspaces):
            raise WorkspaceNotFound(workspace_id)
        if len(workspaces) == 1:
            raise ValueError("Keep at least one workspace.")
        _save([w for w in workspaces if w.id != workspace_id])
    delete_conversation(workspace_id)
    openclaw.remove_agents(get_settings(), workspace_id)


def save_roles(workspace_id: str, roles: list[Role]) -> list[Role]:
    """Replace this workspace's team. Raises ValueError if the list is invalid."""
    validate_roles(roles)
    with _LOCK:
        workspaces = _load()
        target = next((w for w in workspaces if w.id == workspace_id), None)
        if target is None:
            raise WorkspaceNotFound(workspace_id)
        target.roles = roles
        _save(workspaces)
        return roles
