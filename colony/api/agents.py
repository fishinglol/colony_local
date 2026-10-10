"""Agent (role) endpoints and the model list that feeds the editor's dropdown."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..config import get_settings
from ..core.agents import ReasoningLevel, Role
from ..core.context import supports_tools
from ..core.errors import explain
from ..core.models import MODEL_POOL
from ..core.workspaces import WorkspaceNotFound, get_workspace, save_roles
from ..engine.openclaw import ping_model
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
                             "reasoning": info.get("reasoning", False), "reasoning_levels": None,
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
