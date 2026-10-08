"""Agent (role) endpoints and the model list that feeds the editor's dropdown."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..config import get_settings
from ..core.agents import ReasoningLevel, Role
from ..core.context import model_catalog, reasoning_param, supports_tools
from ..core.errors import explain
from ..core.models import MODEL_POOL, PROVIDER_NAMES, known_context_window
from ..core.workspaces import WorkspaceNotFound, get_workspace, save_roles
from ..llm.http import ProviderError, get_json
from ..llm.providers import KAGGLE_PREFIX, ping_model

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
        if role.tools.any_on and supports_tools(role.model, get_settings()) is False:
            raise HTTPException(status_code=400, detail=(
                f"{role.name}: the model {role.model} can't use tools. Pick another model, or switch its tools off."))
    try:
        return RolesPayload(roles=save_roles(workspace.id, payload.roles))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _capabilities(info: dict | None, context: int | None) -> dict:
    """What a model can do, as far as OpenRouter's catalog says (None = it doesn't say)."""
    info = info or {}
    return {"tools": info.get("tools"), "inputs": info.get("inputs"), "reasoning": info.get("reasoning"),
            "reasoning_levels": info.get("reasoning_levels"), "context": info.get("context") or context}


def _kaggle_models(settings) -> list[dict]:
    """The models the user's Kaggle server has pulled (empty when no URL is set or the notebook is off)."""
    if not settings.kaggle_base_url or settings.mock_mode:
        return []
    try:
        data = get_json(f"{settings.kaggle_base_url}/models", timeout=5.0, provider_name="Kaggle")
    except ProviderError:
        return []
    ids = [m["id"] for m in data.get("data") or [] if isinstance(m, dict) and isinstance(m.get("id"), str)]
    return [{
        "id": KAGGLE_PREFIX + model_id, "provider": "kaggle", "provider_name": "Kaggle (your GPU)",
        "label": model_id, "note": "Free", "suggested": False,
        "capabilities": {"tools": None, "inputs": None, "reasoning": None, "reasoning_levels": None,
                         "context": settings.kaggle_context_window},
    } for model_id in ids]


@router.get("/models")
def get_models() -> dict:
    """Every model the picker can offer: our suggested list first, then everything OpenRouter lists.
    Each carries its capabilities (files/tools, images, video, reasoning, context) when the catalog is reachable."""
    settings = get_settings()
    catalog = model_catalog(settings)
    models = [
        {
            "id": m.model_id, "provider": m.provider, "provider_name": PROVIDER_NAMES.get(m.provider, m.provider),
            "label": m.label, "note": m.note, "suggested": True,
            "capabilities": _capabilities(catalog.get(m.model_id), known_context_window(m.model_id)),
        }
        for m in MODEL_POOL
    ]
    models = _kaggle_models(settings) + models
    listed = {m["id"] for m in models}
    for model_id, info in sorted(catalog.items(), key=lambda item: item[0]):
        if model_id in listed:
            continue
        maker, _, rest = model_id.partition("/")
        name = info.get("name") or model_id
        provider_name, sep, label = name.partition(": ")      # OpenRouter names look like "Google: Gemini 3 Flash"
        models.append({
            "id": model_id, "provider": maker.lstrip("~"), "provider_name": provider_name if sep else PROVIDER_NAMES.get(maker, maker),
            "label": label if sep else name, "note": "Free" if model_id.endswith(":free") else "", "suggested": False,
            "capabilities": _capabilities(info, None),
        })
    return {"models": models, "catalog": bool(catalog)}     # catalog: False = OpenRouter's list could not be read


class ModelTestRequest(BaseModel):
    model: str = Field(min_length=3, max_length=120)
    reasoning: ReasoningLevel = "default"     # test with the level the agent will use


@router.post("/models/test")
def test_model(payload: ModelTestRequest) -> dict:
    """Send one tiny message to a model so the user can see it works before giving it an agent."""
    settings = get_settings()
    if settings.mock_mode:
        return {"ok": True, "seconds": 0.0, "preview": "[mock] OK"}
    try:
        model = payload.model.strip()
        preview, seconds = ping_model(settings=settings, model=model, reasoning=reasoning_param(model, payload.reasoning, settings))
    except ProviderError as exc:
        return {"ok": False, "message": explain(exc, payload.model.strip())}
    return {"ok": True, "seconds": round(seconds, 1), "preview": preview}
