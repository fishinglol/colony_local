"""Agent (role) endpoints and the model list that feeds the editor's dropdown."""
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..config import get_settings
from ..core.agents import ReasoningLevel, Role
from ..core.context import supports_tools
from ..core.errors import explain
from ..core.models import MODEL_POOL
from ..core.workspaces import WorkspaceNotFound, get_workspace, save_roles
from ..engine.openclaw import (add_skills, add_skills_from_github, agent_dir, agent_id_for, identity_md, list_skills, memory_dir, ping_model, remove_skill,
                               soul_md)
from ..llm.http import ProviderError
from ..llm.ollama import OLLAMA_CLOUD_MODELS, normalize_ollama_model_id

router = APIRouter()


class RolesPayload(BaseModel):
    roles: list[Role]


def _workspace(workspace_id: str | None):
    try:
        return get_workspace(workspace_id)
    except WorkspaceNotFound as exc:
        raise HTTPException(status_code=404, detail="That workspace doesn't exist.") from exc


@router.get("/roles")
def get_roles(workspace_id: str | None = None) -> RolesPayload:
    """The team of a workspace (the first one if none is named)."""
    return RolesPayload(roles=_workspace(workspace_id).roles)


@router.put("/roles")
def put_roles(payload: RolesPayload, workspace_id: str | None = None) -> RolesPayload:
    workspace = _workspace(workspace_id)
    for role in payload.roles:
        if role.tools.any_on and not supports_tools(role.model):
            raise HTTPException(status_code=400, detail=(
                f"{role.name}: the model {role.model} can't use tools. Pick another model, or switch its tools off."))
    try:
        return RolesPayload(roles=save_roles(workspace.id, payload.roles))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _read(path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


@router.get("/roles/{role_id}/files")
def get_role_files(role_id: str, workspace_id: str | None = None) -> dict:
    """What an agent is, as the files OpenClaw reads for it: soul (persona), identity, its own memory and the team's shared memory."""
    workspace = _workspace(workspace_id)
    role = next((r for r in workspace.roles if r.id == role_id), None)
    if role is None:
        raise HTTPException(status_code=404, detail="That agent doesn't exist.")
    settings = get_settings()
    mine, shared = agent_dir(settings, agent_id_for(workspace.id, role.id)), memory_dir(settings, workspace.id)
    daily = sorted((shared / "memory").glob("*.md"), reverse=True)[:7]
    return {
        "role_id": role.id, "name": role.name,
        "soul": _read(mine / "SOUL.md") or soul_md(role.name, role.instructions).strip(),     # not written until its first turn
        "identity": _read(mine / "IDENTITY.md") or identity_md(role.name).strip(),
        "rules": _read(mine / "AGENTS.md"),
        "user": _read(shared / "USER.md"),
        "memory": _read(shared / "MEMORY.md"),
        "private_memory": _read(mine / "MEMORY.md"),
        "dreams": _read(mine / "DREAMS.md"),
        "daily": [{"date": p.stem, "content": _read(p)} for p in daily],
        "paths": {"agent": str(mine), "shared": str(shared)},
        "started": mine.exists(),
    }


class SkillSource(BaseModel):
    path: str = Field(min_length=1, max_length=1000)    # a folder with SKILL.md, or a folder of such folders


def _agent_id(role_id: str, workspace_id: str | None) -> str:
    workspace = _workspace(workspace_id)
    if not any(r.id == role_id for r in workspace.roles):
        raise HTTPException(status_code=404, detail="That agent doesn't exist.")
    return agent_id_for(workspace.id, role_id)


@router.get("/roles/{role_id}/skills")
def get_skills(role_id: str, workspace_id: str | None = None) -> dict:
    """The skills this agent has (only this agent can use them)."""
    return {"skills": list_skills(get_settings(), _agent_id(role_id, workspace_id))}


@router.post("/roles/{role_id}/skills")
def post_skills(role_id: str, payload: SkillSource, workspace_id: str | None = None) -> dict:
    """Give this agent the skill(s) found in a folder on this Mac. The folder is copied; the original stays where it is."""
    settings, agent_id = get_settings(), _agent_id(role_id, workspace_id)
    source = Path(payload.path).expanduser()
    if not source.is_dir():
        raise HTTPException(status_code=400, detail="That folder doesn't exist.")
    if not add_skills(settings, agent_id, source):
        raise HTTPException(status_code=400, detail="No skill found there: a skill is a folder with a SKILL.md file.")
    return {"skills": list_skills(settings, agent_id)}


class GithubSource(BaseModel):
    url: str = Field(min_length=1, max_length=300)


@router.post("/roles/{role_id}/skills/github")
def post_skills_github(role_id: str, payload: GithubSource, workspace_id: str | None = None) -> dict:
    """Give this agent the skills found in a public GitHub repository (downloaded now, once)."""
    settings, agent_id = get_settings(), _agent_id(role_id, workspace_id)
    try:
        added = add_skills_from_github(settings, agent_id, payload.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not added:
        raise HTTPException(status_code=400, detail="No skill found in that repository: a skill is a folder with a SKILL.md file.")
    return {"skills": list_skills(settings, agent_id)}


@router.delete("/roles/{role_id}/skills/{folder:path}")
def delete_skill(role_id: str, folder: str, workspace_id: str | None = None) -> dict:
    settings, agent_id = get_settings(), _agent_id(role_id, workspace_id)
    if not remove_skill(settings, agent_id, folder):
        raise HTTPException(status_code=404, detail="That skill doesn't exist.")
    return {"skills": list_skills(settings, agent_id)}


def _levels(info: dict) -> dict | None:
    """The thinking levels OpenClaw offers an Ollama model (low|medium|high|max), or None when the model does not reason."""
    if not info.get("reasoning"):
        return None
    return {"efforts": ["low", "medium", "high", "max"], "default": None, "can_turn_off": info.get("can_turn_off", True)}


@router.get("/models")
def get_models() -> dict:
    """The models the picker offers (the Ollama models OpenClaw runs), each with what it can do."""
    models = []
    for m in MODEL_POOL:
        info = OLLAMA_CLOUD_MODELS.get(normalize_ollama_model_id(m.model_id), {})
        models.append({
            "id": m.model_id, "provider": "ollama", "provider_name": "Ollama Cloud / Local",
            "source": "ollama", "source_label": "Ollama API",
            "label": m.label, "note": m.note, "suggested": True,
            "capabilities": {"tools": info.get("tools", True), "inputs": ["text", "image", "file"],
                             "reasoning": info.get("reasoning", False), "reasoning_levels": _levels(info),
                             "context": info.get("context")},
        })
    return {"models": models, "catalog": True}


class ModelTestRequest(BaseModel):
    model: str = Field(min_length=3, max_length=120)
    reasoning: ReasoningLevel = "default"     # sent by older editors; models are tested with their own default


@router.post("/models/test")
def test_model(payload: ModelTestRequest) -> dict:
    """Send one tiny message to a model so the user can see it works before giving it an agent."""
    settings = get_settings()
    if settings.mock_mode:
        return {"ok": True, "seconds": 0.0, "preview": "[mock] OK"}
    try:
        model = payload.model.strip()
        preview, seconds = ping_model(settings, model)
    except ProviderError as exc:
        return {"ok": False, "message": explain(exc, payload.model.strip())}
    return {"ok": True, "seconds": round(seconds, 1), "preview": preview}
