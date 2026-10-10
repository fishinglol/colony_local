"""Connectors: the MCP servers agents with the "connectors" permission can use.

OpenClaw owns them: they live in OpenClaw's own config (`mcp.servers` in ~/.openclaw/openclaw.json, which we write 0600
because it holds API keys) and OpenClaw's built-in MCP client connects to them and exposes their tools as
`<server>__<tool>`. Colony keeps only the friendly editing layer for its Connectors window: validation, masking, and
which agents may use which server (see engine/openclaw.py::ensure_agent). Secrets never go to the browser: reads show
them masked, and a masked value sent back unchanged means "keep what is stored". Servers OpenClaw knows about that
Colony cannot show (OAuth, extra fields) are left untouched.
"""
from typing import Any

from pydantic import BaseModel, Field, model_validator

from ..engine.openclaw import config_lock, read_config, write_config

MASK = "••••••••"
MAX_SERVERS = 20
COMPOSIO_URL = "https://connect.composio.dev/mcp"
_NAME_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789_-"


class McpServer(BaseModel):
    command: str | None = Field(default=None, max_length=300)
    args: list[str] = Field(default_factory=list, max_length=40)
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = Field(default=None, max_length=500)
    headers: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True

    @model_validator(mode="after")
    def _one_kind(self) -> "McpServer":
        self.command = (self.command or "").strip() or None
        self.url = (self.url or "").strip() or None
        if bool(self.command) == bool(self.url):
            raise ValueError("Give either a command to run or a URL, not both and not neither.")
        if self.url and not self.url.startswith(("https://", "http://")):
            raise ValueError("The URL must start with https:// (or http:// for a server on this computer).")
        return self


def _valid_name(name: str) -> bool:
    return 0 < len(name) <= 40 and all(c in _NAME_CHARS for c in name)


def _entries(cfg: dict[str, Any]) -> dict[str, dict]:
    return (cfg.get("mcp") or {}).get("servers") or {}


def _read(entry: dict[str, Any]) -> McpServer:
    return McpServer(
        command=entry.get("command"), args=[str(a) for a in entry.get("args") or []],
        env={k: str(v) for k, v in (entry.get("env") or {}).items()},
        url=entry.get("url"), headers={k: str(v) for k, v in (entry.get("headers") or {}).items()},
        enabled=entry.get("enabled", True))


def _entry_for(server: McpServer, old: dict[str, Any] | None) -> dict[str, Any]:
    """OpenClaw's config entry for this server, keeping any settings of its own we do not manage (timeouts, toolFilter, ...)."""
    entry = {k: v for k, v in (old or {}).items() if k not in ("command", "args", "env", "url", "headers", "transport")}
    entry["enabled"] = server.enabled
    if server.command:
        entry["command"], entry["args"] = server.command, server.args
        if server.env:
            entry["env"] = server.env
    else:
        entry["url"] = server.url
        # OpenClaw defaults a URL to the legacy SSE transport; modern servers (Composio included) speak streamable HTTP.
        entry["transport"] = "sse" if server.url.rstrip("/").endswith("/sse") else "streamable-http"
        if server.headers:
            entry["headers"] = server.headers
    return entry


def load() -> dict[str, McpServer]:
    servers = {}
    for name, entry in _entries(read_config()).items():
        try:
            servers[name] = _read(entry)
        except (TypeError, ValueError, AttributeError):
            continue
    return servers


def enabled_names() -> list[str]:
    return [name for name, server in load().items() if server.enabled]


def masked(server: McpServer) -> dict:
    """The server as the browser may see it: every secret value hidden."""
    body = server.model_dump()
    body["env"] = {k: MASK for k in server.env}
    body["headers"] = {k: MASK for k in server.headers}
    return body


def save(incoming: dict[str, McpServer]) -> dict[str, McpServer]:
    """Replace the whole list. A value equal to MASK keeps what was stored under the same name and key.
    Raises ValueError for a bad name or too many servers."""
    if len(incoming) > MAX_SERVERS:
        raise ValueError(f"At most {MAX_SERVERS} connectors.")
    for name in incoming:
        if not _valid_name(name):
            raise ValueError("A connector's name may only use lowercase letters, digits, - and _.")
    with config_lock:
        cfg = read_config()
        entries = _entries(cfg)
        stored = load()
        for name, server in incoming.items():
            old = stored.get(name)
            for field in ("env", "headers"):
                values = getattr(server, field)
                for key, value in values.items():
                    if value == MASK:
                        values[key] = (getattr(old, field, {}) or {}).get(key, "") if old else ""
        # Servers Colony cannot show are not in `stored`, so they are not part of "the whole list" and stay as they are.
        kept = {n: e for n, e in entries.items() if n not in stored}
        cfg.setdefault("mcp", {})["servers"] = {**kept, **{n: _entry_for(s, entries.get(n)) for n, s in incoming.items()}}
        write_config(cfg)
        return incoming


def composio(consumer_key: str) -> McpServer:
    """Composio Connect: one address for 1000+ apps; the agent connects each app on first use (docs.composio.dev)."""
    return McpServer(url=COMPOSIO_URL, headers={"x-consumer-api-key": consumer_key.strip()})
