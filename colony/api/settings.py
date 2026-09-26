"""Settings endpoints (API key). Values are stored in ~/.colony/.env."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import get_settings, update_env_file

router = APIRouter()


class SettingsUpdateRequest(BaseModel):
    openrouter_api_key: str | None = None


@router.get("/settings")
def get_settings_view() -> dict:
    s = get_settings()
    key = s.openrouter_api_key or ""
    masked_key = f"{key[:7]}...{key[-4:]}" if len(key) > 12 else ("(not set)" if not key else "******")
    return {
        "has_openrouter_key": bool(s.openrouter_api_key),
        "openrouter_key_masked": masked_key,
        "jev_model": s.jev_model,
        "mock_mode": s.mock_mode,
        "data_dir": str(s.data_dir),
    }


@router.post("/settings")
def update_settings_endpoint(payload: SettingsUpdateRequest) -> dict:
    updates: dict[str, str] = {}
    if payload.openrouter_api_key is not None and payload.openrouter_api_key.strip():
        updates["OPENROUTER_API_KEY"] = payload.openrouter_api_key.strip()
    if updates:
        try:
            update_env_file(updates)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", "updated": list(updates.keys())}
