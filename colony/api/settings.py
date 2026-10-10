"""Settings endpoints (Ollama + OpenClaw Gateway). Values are stored in ~/.colony/.env."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import get_settings, update_env_file

router = APIRouter()


class SettingsUpdateRequest(BaseModel):
    ollama_base_url: str | None = None
    ollama_api_key: str | None = None
    openclaw_gateway_enabled: bool | None = None
    openclaw_gateway_url: str | None = None
    openclaw_gateway_token: str | None = None


@router.get("/settings")
def get_settings_view() -> dict:
    s = get_settings()
    ollama_key = s.ollama_api_key or ""
    masked_ollama_key = f"{ollama_key[:7]}...{ollama_key[-4:]}" if len(ollama_key) > 12 else ("(not set)" if not ollama_key else "******")
    gw_token = s.openclaw_gateway_token or ""
    masked_gw_token = f"{gw_token[:7]}...{gw_token[-4:]}" if len(gw_token) > 12 else ("(not set)" if not gw_token else "******")
    return {
        "ollama_base_url": s.ollama_base_url or "http://localhost:11434",
        "has_ollama_key": bool(s.ollama_api_key),
        "ollama_key_masked": masked_ollama_key,
        "openclaw_gateway_enabled": s.openclaw_gateway_enabled,
        "openclaw_gateway_url": s.openclaw_gateway_url,
        "has_openclaw_token": bool(s.openclaw_gateway_token),
        "openclaw_token_masked": masked_gw_token,
        "mock_mode": s.mock_mode,
        "data_dir": str(s.data_dir),
    }


@router.post("/settings")
def update_settings_endpoint(payload: SettingsUpdateRequest) -> dict:
    updates: dict[str, str] = {}
    if payload.ollama_base_url is not None and payload.ollama_base_url.strip():
        updates["OLLAMA_BASE_URL"] = payload.ollama_base_url.strip().rstrip("/")
    if payload.ollama_api_key is not None:
        updates["OLLAMA_API_KEY"] = payload.ollama_api_key.strip()
    if payload.openclaw_gateway_enabled is not None:
        updates["OPENCLAW_GATEWAY_ENABLED"] = "true" if payload.openclaw_gateway_enabled else "false"
    if payload.openclaw_gateway_url is not None and payload.openclaw_gateway_url.strip():
        updates["OPENCLAW_GATEWAY_URL"] = payload.openclaw_gateway_url.strip().rstrip("/")
    if payload.openclaw_gateway_token is not None:
        updates["OPENCLAW_GATEWAY_TOKEN"] = payload.openclaw_gateway_token.strip()
    if updates:
        try:
            update_env_file(updates)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", "updated": list(updates.keys())}
