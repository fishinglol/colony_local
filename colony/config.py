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
    # ── AI providers ──────────────────────────────────────────────────────────
    # Primary: OpenRouter. Fallback: OpenAI. Same convention as Colony backend.
    openrouter_api_key: str | None = None
    openrouter_default_model: str = "anthropic/claude-haiku-4.5"
    openrouter_routing_model: str = "deepseek/deepseek-v4.1-flash"
    openrouter_timeout_seconds: float = 120.0
    # How many times to retry a chat reply that fails for a temporary reason (rate limit, 5xx).
    chat_retries: int = 3

    openai_api_key: str | None = None
    openai_default_model: str = "gpt-5-mini"
    openai_timeout_seconds: float = 30.0

    # ── Jev decider (via OpenRouter) ──────────────────────────────────────────
    # Uses the same openrouter_api_key — no separate key needed.
    jev_model: str = "typesafe/jev-1.13"
    jev_decisions_url: str = "https://openrouter.ai/api/alpha/decisions"

    # ── Agent tools (files + commands, run by the Pi engine) ──────────────────
    # Old global "workspace folder" setting; only read once, to give the first workspace its project folder
    # (core/workspaces.py). Each workspace now has its own folder.
    workspace_dir: Path | None = None
    pi_bin: str | None = None                 # path to Pi; unset = look in local/pi-runtime, then PATH
    openrouter_base_url: str = "https://openrouter.ai/api/v1"   # used by Pi; tests point it at a fake server
    tools_turn_timeout_seconds: float = 600.0     # one agent turn with tools, including waiting for approvals
    approval_timeout_seconds: float = 120.0       # no answer to "allow this?" in time = no

    # ── Data ──────────────────────────────────────────────────────────────────
    data_dir: Path = LOCAL_DATA_DIR

    # ── Feature flags ─────────────────────────────────────────────────────────
    self_improve_enabled: bool = True
    self_improve_interval_turns: int = 5
    history_max_messages: int = 60     # one workspace = one long conversation; the model's window trims further
    max_output_tokens: int = 4096
    max_attachment_mb: int = 20        # per attached file
    compaction_enabled: bool = True    # summarise the old part of a long conversation (core/compaction.py)
    compact_at_tokens: int = 24_000    # start summarising when the conversation is this big (estimate)
    compact_keep_tokens: int = 8_000   # ...and keep about this much of the newest messages word for word
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
        "OPENROUTER_API_KEY=\n\n"
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

