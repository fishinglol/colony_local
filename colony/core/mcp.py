"""Connectors: the MCP servers agents with the "connectors" permission can use.

One list for the whole app, kept in ~/.colony/mcp-servers.json (0600, it holds API keys). A server is either a
local program (`command` + `args` + `env`, spoken to over stdin/stdout) or a web address (`url` + `headers`).
Pi's MCP adapter does the talking; Colony only decides which servers exist and which agents may use them
(see engine/pi.py and colony-gate.ts). Secrets never go to the browser: reads show them masked, and a masked
value sent back unchanged means "keep what is stored".
"""
import json
import os
import threading
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

from ..config import get_settings

MASK = "••••••••"
MAX_SERVERS = 20
COMPOSIO_URL = "https://connect.composio.dev/mcp"
_LOCK = threading.RLock()
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


def _path() -> Path:
    return get_settings().data_dir / "mcp-servers.json"


def _valid_name(name: str) -> bool:
    return 0 < len(name) <= 40 and all(c in _NAME_CHARS for c in name)


def load() -> dict[str, McpServer]:
    with _LOCK:
        try:
            raw = json.loads(_path().read_text(encoding="utf-8")).get("servers") or {}
        except (OSError, ValueError, AttributeError):
            return {}
        servers = {}
        for name, item in raw.items():
            try:
                servers[name] = McpServer(**item)
            except (TypeError, ValueError):
                continue
        return servers


def _write(servers: dict[str, McpServer]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"servers": {n: s.model_dump() for n, s in servers.items()}}, f, indent=2)
    os.replace(tmp, path)


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
    with _LOCK:
        stored = load()
        for name, server in incoming.items():
            if not _valid_name(name):
                raise ValueError("A connector's name may only use lowercase letters, digits, - and _.")
            old = stored.get(name)
            for field in ("env", "headers"):
                values = getattr(server, field)
                for key, value in values.items():
                    if value == MASK:
                        values[key] = (getattr(old, field, {}) or {}).get(key, "") if old else ""
        _write(incoming)
        return incoming


def enabled_for_pi() -> dict[str, dict]:
    """What Pi's MCP adapter is told: the enabled servers, in its own config format."""
    servers = {}
    for name, server in load().items():
        if not server.enabled:
            continue
        if server.command:
            servers[name] = {"command": server.command, "args": server.args, **({"env": server.env} if server.env else {})}
        else:
            servers[name] = {"url": server.url, **({"headers": server.headers} if server.headers else {})}
    return servers


def composio(consumer_key: str) -> McpServer:
    """Composio Connect: one address for 1000+ apps; the agent connects each app on first use (docs.composio.dev)."""
    return McpServer(url=COMPOSIO_URL, headers={"x-consumer-api-key": consumer_key.strip()})
