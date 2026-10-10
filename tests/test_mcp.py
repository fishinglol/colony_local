"""Connectors (MCP): kept in OpenClaw's own config (mcp.servers); Colony edits, masks and validates them."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from colony.app import app
from colony.core import mcp
from colony.engine import openclaw
from colony.core.agents import ToolAccess

client = TestClient(app)
FAKE_SERVER = Path(__file__).with_name("fake_mcp.py")


# ── the store ─────────────────────────────────────────────────────────────────────────────────

def test_a_server_is_a_command_or_a_url_never_both_or_neither():
    assert mcp.McpServer(command="npx", args=["-y", "x"]).command == "npx"
    assert mcp.McpServer(url="https://example.com/mcp").url == "https://example.com/mcp"
    for bad in ({}, {"command": "x", "url": "https://a.b"}, {"url": "ftp://a.b"}):
        with pytest.raises(ValueError):
            mcp.McpServer(**bad)


def test_secrets_are_masked_for_the_browser_and_a_masked_value_keeps_what_is_stored(tmp_path):
    first = client.put("/api/mcp", json={"servers": {"composio": {"url": "https://connect.composio.dev/mcp", "headers": {"x-consumer-api-key": "ck_real"}}}})
    assert first.status_code == 200
    shown = client.get("/api/mcp").json()["servers"]["composio"]
    assert shown["headers"] == {"x-consumer-api-key": mcp.MASK} and "ck_real" not in json.dumps(client.get("/api/mcp").json())
    shown["enabled"] = False
    client.put("/api/mcp", json={"servers": {"composio": shown}})                   # the browser sends the mask back
    assert mcp.load()["composio"].headers == {"x-consumer-api-key": "ck_real"} and mcp.load()["composio"].enabled is False
    assert oct(openclaw.config_path().stat().st_mode & 0o777) == "0o600"        # the config holds the key


def test_bad_names_and_bad_servers_are_refused_with_a_reason():
    assert client.put("/api/mcp", json={"servers": {"Bad Name": {"url": "https://a.b/mcp"}}}).status_code == 400
    assert client.put("/api/mcp", json={"servers": {"ok": {"command": "x", "url": "https://a.b"}}}).status_code == 422


def test_composio_is_one_click_with_only_a_key():
    assert client.post("/api/mcp/composio", json={"key": "  "}).status_code == 400
    res = client.post("/api/mcp/composio", json={"key": "ck_abc"})
    assert res.status_code == 200
    server = mcp.load()["composio"]
    assert server.url == mcp.COMPOSIO_URL and server.headers == {"x-consumer-api-key": "ck_abc"}
    entry = openclaw.read_config()["mcp"]["servers"]["composio"]                # what OpenClaw's MCP client reads
    assert entry == {"enabled": True, "url": mcp.COMPOSIO_URL, "transport": "streamable-http",
                     "headers": {"x-consumer-api-key": "ck_abc"}}


def test_only_enabled_servers_are_offered_to_agents():
    client.put("/api/mcp", json={"servers": {"on": {"command": "x"}, "off": {"command": "y", "enabled": False}}})
    assert mcp.enabled_names() == ["on"]


def test_saving_keeps_what_openclaw_has_that_colony_cannot_show():
    openclaw.write_config({"tools": {"profile": "full"}, "mcp": {"servers": {
        "oauth-only": {"url": "https://a.b/mcp", "auth": "oauth"},                       # a url server with an OpenClaw-only setting
        "weird": {"enabled": True}}}})                                                   # neither command nor url: Colony cannot show it
    shown = client.get("/api/mcp").json()["servers"]
    assert "weird" not in shown and "oauth-only" in shown
    client.put("/api/mcp", json={"servers": {"mine": {"command": "x"}, "oauth-only": shown["oauth-only"]}})
    cfg = openclaw.read_config()
    assert cfg["tools"] == {"profile": "full"}                                           # the rest of the config is untouched
    assert cfg["mcp"]["servers"]["weird"] == {"enabled": True}                           # not part of the list Colony shows
    assert cfg["mcp"]["servers"]["oauth-only"]["auth"] == "oauth"                        # extra OpenClaw settings survive an edit
    client.put("/api/mcp", json={"servers": {"mine": {"command": "x"}}})                 # removing a shown server removes it
    assert set(openclaw.read_config()["mcp"]["servers"]) == {"mine", "weird"}


def test_an_agent_is_allowed_exactly_the_connectors_ticked_for_it(monkeypatch, tmp_path):
    from colony.config import Settings
    openclaw.write_config({})
    monkeypatch.setattr(openclaw.urllib.request, "urlopen",
                        lambda url, timeout=None: (_ for _ in ()).throw(OSError("no gateway in tests")))
    settings = Settings(data_dir=tmp_path)
    with pytest.raises(Exception):
        openclaw.ensure_agent(settings, "ws_1-coder", "Coder", tools=ToolAccess(mcp="allow"), connectors=["composio", "docs"],
                              wait_seconds=0.1)
    allow = openclaw.read_config()["agents"]["entries"]["ws_1-coder"]["tools"]["alsoAllow"]
    assert allow == ["composio__*", "docs__*", "read", "write", "edit", "memory_search", "memory_get"]      # read/write/edit: the shared memory files


def test_links_open_in_the_real_browser_and_only_web_addresses(monkeypatch):
    import webbrowser
    opened = []
    monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(url) or True)
    assert client.post("/api/open-url", json={"url": "https://accounts.example.com/oauth?x=1"}).status_code == 200
    assert client.post("/api/open-url", json={"url": "file:///etc/passwd"}).status_code == 400
    assert client.post("/api/open-url", json={"url": "javascript:alert(1)"}).status_code == 400
    assert opened == ["https://accounts.example.com/oauth?x=1"]
    monkeypatch.setattr(webbrowser, "open", lambda url: False)
    assert client.post("/api/open-url", json={"url": "https://a.example/"}).status_code == 500


def test_modes_keep_which_connectors_an_agent_may_use():
    tools = ToolAccess(mcp="allow", mcp_servers=["composio"], mcp_apps=["Gmail"])
    from colony.core.agents import apply_mode
    assert apply_mode(tools, "manual") == ToolAccess(mcp="ask", mcp_servers=["composio"], mcp_apps=["Gmail"])
