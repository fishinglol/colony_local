"""Settings endpoints (API key). Values are stored in ~/.colony/.env."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import get_settings, update_env_file

router = APIRouter()


class SettingsUpdateRequest(BaseModel):
    openrouter_api_key: str | None = None
    kaggle_base_url: str | None = None      # "" = forget it
    ollama_base_url: str | None = None
    ollama_api_key: str | None = None


@router.get("/settings")
def get_settings_view() -> dict:
    s = get_settings()
    key = s.openrouter_api_key or ""
    masked_key = f"{key[:7]}...{key[-4:]}" if len(key) > 12 else ("(not set)" if not key else "******")
    ollama_key = s.ollama_api_key or ""
    masked_ollama_key = f"{ollama_key[:7]}...{ollama_key[-4:]}" if len(ollama_key) > 12 else ("(not set)" if not ollama_key else "******")
    return {
        "has_openrouter_key": bool(s.openrouter_api_key),
        "openrouter_key_masked": masked_key,
        "kaggle_base_url": s.kaggle_base_url or "",
        "ollama_base_url": s.ollama_base_url or "http://localhost:11434",
        "has_ollama_key": bool(s.ollama_api_key),
        "ollama_key_masked": masked_ollama_key,
        "jev_model": s.jev_model,
        "mock_mode": s.mock_mode,
        "data_dir": str(s.data_dir),
    }


@router.post("/settings")
def update_settings_endpoint(payload: SettingsUpdateRequest) -> dict:
    updates: dict[str, str] = {}
    if payload.openrouter_api_key is not None and payload.openrouter_api_key.strip():
        updates["OPENROUTER_API_KEY"] = payload.openrouter_api_key.strip()
    if payload.kaggle_base_url is not None:
        updates["KAGGLE_BASE_URL"] = _kaggle_url(payload.kaggle_base_url)
    if payload.ollama_base_url is not None and payload.ollama_base_url.strip():
        updates["OLLAMA_BASE_URL"] = payload.ollama_base_url.strip().rstrip("/")
    if payload.ollama_api_key is not None:
        updates["OLLAMA_API_KEY"] = payload.ollama_api_key.strip()
    if updates:
        try:
            update_env_file(updates)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", "updated": list(updates.keys())}


def _kaggle_url(raw: str) -> str:
    """The notebook prints its tunnel address; accept it with or without /v1 or a trailing slash."""
    url = raw.strip().rstrip("/")
    if not url:
        return ""
    if not url.startswith(("https://", "http://")) or " " in url:
        raise HTTPException(status_code=400, detail="Kaggle URL must start with https://")
    return url if url.endswith("/v1") else url + "/v1"
