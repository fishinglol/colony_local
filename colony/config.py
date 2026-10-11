"""Colony Local — settings.

All config goes through get_settings(). Never read env vars directly in
route handlers or business logic.

Config file: ~/.colony/.env  (created on first run with instructions)
"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

LOCAL_DATA_DIR = Path.home() / ".colony"
_ENV_FILE = LOCAL_DATA_DIR / ".env"


class Settings(BaseSettings):
    # ── OpenClaw Engine (Gateway on port 18789) ──────────────────────────────
    openclaw_gateway_enabled: bool = True
    openclaw_gateway_url: str = "http://127.0.0.1:18789"
    openclaw_gateway_token: str | None = None

    # ── Ollama API (Local or Cloud endpoint) ──────────────────────────────────
    ollama_base_url: str = "http://localhost:11434"
    ollama_api_key: str | None = None
    ollama_context_window: int = 32_768

    # Laya (open-weight, runs on this computer) decides which agent answers when set.
    # `colony` sets it itself when laya-runtime/ is installed (cli.py).
    laya_url: str | None = None

    # Jev as an API (https://docs.beatapi.io/decisions). When the key is set it decides before Laya does, and
    # `colony` doesn't start the local Laya. jev-1.13-free is $0 but rate limited; jev-1.13 bills input tokens only.
    jev_api_key: str | None = None
    jev_url: str = "https://api.beatapi.io"
    jev_model: str = "jev-1.13-free"

    # ── Agent tools (files + commands, run by OpenClaw) ──────────────────
    # Old global "workspace folder" setting; only read once, to give the first workspace its project folder
    # (core/workspaces.py). Each workspace now has its own folder.
    workspace_dir: Path | None = None

    approval_timeout_seconds: float = 120.0       # no answer to "allow this?" in time = no

    # ── Data ──────────────────────────────────────────────────────────────────
    data_dir: Path = LOCAL_DATA_DIR

    # ── Feature flags ─────────────────────────────────────────────────────────
    history_max_messages: int = 60     # one workspace = one long conversation; OpenClaw compacts each agent's session itself
    max_attachment_mb: int = 20        # per attached file
    projects_dir: Path = Path.home() / "Documents" / "Colony Projects"     # each new workspace gets its own project folder here
    mock_mode: bool = False           # True → skip real LLM calls (dev/test)

    # ── Server ────────────────────────────────────────────────────────────────
    host: str = "127.0.0.1"
    port: int = 8765

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


def ensure_env_file() -> None:
    """Write a starter .env if none exists, so the user knows what to fill in."""
    _ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    if _ENV_FILE.exists():
        return
    _ENV_FILE.write_text(
        "# Colony Local — configuration\n"
        "# Set your API keys here, then restart the server.\n\n"
        "OLLAMA_API_KEY=\n\n"
        "# Roles (which AI answers what, and how) are edited in the app UI\n"
        "# and stored in ~/.colony/roles.json.\n",
        encoding="utf-8",
    )


def update_env_file(updates: dict[str, str]) -> None:
    """Update or add environment variable key-value pairs in ~/.colony/.env."""
    for key, val in updates.items():
        if "\n" in val or "\r" in val:
            raise ValueError(f"{key} must be a single line.")
    ensure_env_file()
    lines = _ENV_FILE.read_text(encoding="utf-8").splitlines() if _ENV_FILE.exists() else []
    existing_keys: set[str] = set()
    new_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in line:
            key, _, _ = line.partition("=")
            key = key.strip()
            if key in updates:
                new_lines.append(f"{key}={updates[key]}")
                existing_keys.add(key)
                continue
        new_lines.append(line)

    for key, val in updates.items():
        if key not in existing_keys:
            new_lines.append(f"{key}={val}")

    _ENV_FILE.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    get_settings.cache_clear()

