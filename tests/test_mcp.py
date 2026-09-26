"""Connectors (MCP): the store, and the REAL Pi + pi-mcp-adapter talking to a fake MCP server."""
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from colony.app import app
from colony.config import Settings
from colony.core import mcp
from colony.core.agents import ToolAccess
from colony.engine import pi as engine

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
    stored = tmp_path / "mcp-servers.json"
    assert oct(stored.stat().st_mode & 0o777) == "0o600"


def test_bad_names_and_bad_servers_are_refused_with_a_reason():
    assert client.put("/api/mcp", json={"servers": {"Bad Name": {"url": "https://a.b/mcp"}}}).status_code == 400
    assert client.put("/api/mcp", json={"servers": {"ok": {"command": "x", "url": "https://a.b"}}}).status_code == 422


def test_composio_is_one_click_with_only_a_key():
    assert client.post("/api/mcp/composio", json={"key": "  "}).status_code == 400
    res = client.post("/api/mcp/composio", json={"key": "ck_abc"})
    assert res.status_code == 200
    server = mcp.load()["composio"]
    assert server.url == mcp.COMPOSIO_URL and server.headers == {"x-consumer-api-key": "ck_abc"}
    assert mcp.enabled_for_pi()["composio"] == {"url": mcp.COMPOSIO_URL, "headers": {"x-consumer-api-key": "ck_abc"}}


def test_only_enabled_servers_reach_pi():
    client.put("/api/mcp", json={"servers": {"on": {"command": "x"}, "off": {"command": "y", "enabled": False}}})
    assert list(mcp.enabled_for_pi()) == ["on"]


# ── the real Pi ───────────────────────────────────────────────────────────────────────────────

real_mcp = pytest.mark.skipif(not (engine.RUNTIME_PI.exists() and engine.MCP_ADAPTER.exists()),
                              reason="Pi or pi-mcp-adapter is not installed (npm install in local/pi-runtime)")


@pytest.fixture
def model_server():
    from .fake_llm import FakeModelServer
    server = FakeModelServer()
    yield server
    server.shutdown()


@pytest.fixture
def setup(tmp_path, model_server):
    settings = Settings(openrouter_api_key="sk-or-secret", data_dir=tmp_path, openrouter_base_url=model_server.base_url,
                        tools_turn_timeout_seconds=120.0, approval_timeout_seconds=20.0)
    log = tmp_path / "server.log"
    servers = {"fake": {"command": sys.executable, "args": [str(FAKE_SERVER), str(log)], "env": {"FAKE_SECRET": "s3cret"}}}
    (tmp_path / "ws").mkdir()

    def run(message, mcp_rule="ask", approve=lambda tool, what: True, tools=None, servers_=servers):
        return engine.run_turn(settings=settings, model="acme/model:free", system_prompt="You are Coder.", prompt=message,
                               workspace=tmp_path / "ws", tools=tools or ToolAccess(mcp=mcp_rule), approve=approve, mcp_servers=servers_)
    return run, log, model_server, tmp_path


def calls(log: Path) -> list[dict]:
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def tool_calls(log: Path) -> list[dict]:
    return [c for c in calls(log) if c.get("method") == "tools/call"]


@real_mcp
def test_a_connector_call_asks_first_then_reaches_the_server(setup):
    run, log, server, _ = setup
    asked = []
    result = run('MCP fake_echo {"text": "hi there"}', approve=lambda tool, what: asked.append((tool, what)) or True)
    assert asked and asked[0][0] == "mcp" and "fake_echo" in asked[0][1] and "hi there" in asked[0][1]
    params = tool_calls(log)[0]["params"]
    assert (params["name"], params["arguments"]) == ("echo", {"text": "hi there"})
    assert "echo ran with" in result.text and result.actions == ["used connector fake_echo"]
    assert "mcp" in server.requests[0]["tools"]


@real_mcp
def test_a_refused_connector_call_never_reaches_the_server(setup):
    run, log, _, _ = setup
    result = run('MCP fake_delete_everything {"what": "all"}', approve=lambda tool, what: False)
    assert tool_calls(log) == [] and "did not approve" in result.text and result.actions == ["used connector fake_delete_everything ✗"]


@real_mcp
def test_allow_skips_the_question(setup):
    run, log, _, _ = setup
    run('MCP fake_echo {"text": "x"}', mcp_rule="allow", approve=lambda tool, what: pytest.fail("asked"))
    assert len(tool_calls(log)) == 1


@real_mcp
def test_looking_through_the_connectors_never_asks(setup):
    run, _, _, _ = setup
    result = run("MCPSEARCH echo", approve=lambda tool, what: pytest.fail("asked"))
    assert "fake_echo" in result.text


@real_mcp
def test_an_agent_cannot_install_or_sign_in_to_connectors(setup):
    run, log, _, tmp_path = setup
    result = run("MCPINSTALL https://evil.example/mcp", mcp_rule="allow", approve=lambda tool, what: pytest.fail("asked"))
    assert "set up by the user" in result.text
    assert not (tmp_path / "ws" / ".mcp.json").exists() and tool_calls(log) == []


@real_mcp
def test_only_colonys_servers_run_never_a_projects_own_mcp_json(setup):
    run, _, _, tmp_path = setup
    decoy = tmp_path / "decoy.log"
    (tmp_path / "ws" / ".mcp.json").write_text(json.dumps({"mcpServers": {"decoy": {
        "command": sys.executable, "args": [str(FAKE_SERVER), str(decoy)]}}}))
    run("MCPSEARCH echo")
    run('MCP decoy_echo {"text": "x"}', mcp_rule="allow")
    assert not decoy.exists()                                      # a project's own config is never started


@real_mcp
def test_a_web_connector_gets_its_headers_which_is_how_composio_is_reached(setup):
    from .fake_mcp import FakeHttpMcp
    run, _, _, _ = setup
    remote = FakeHttpMcp()
    try:
        servers = {"composio": {"url": remote.url, "headers": {"x-consumer-api-key": "ck_test"}}}
        result = run('MCP composio_echo {"text": "over http"}', mcp_rule="allow", servers_=servers)
    finally:
        remote.shutdown()
    assert "echo ran with" in result.text and "over http" in result.text
    assert remote.seen and all(headers.get("x-consumer-api-key") == "ck_test" for headers, _ in remote.seen)
    assert "tools/call" in [msg.get("method") for _, msg in remote.seen]


@real_mcp
def test_connectors_off_means_the_tool_does_not_exist_for_the_model(setup):
    run, _, server, _ = setup
    run("hello", tools=ToolAccess(read="allow"))
    assert "mcp" not in server.requests[-1]["tools"]


@real_mcp
def test_no_servers_configured_means_no_connector_tool(setup):
    run, _, server, _ = setup
    run("hello", tools=ToolAccess(read="allow", mcp="ask"), servers_={})
    assert "mcp" not in server.requests[-1]["tools"]


# ── how a chat turn uses connectors ───────────────────────────────────────────────────────────

def live_chat(monkeypatch, mcp_access="ask"):
    from colony.config import get_settings
    from colony.core import chat, context
    monkeypatch.setenv("MOCK_MODE", "false")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    get_settings.cache_clear()
    monkeypatch.setattr(context, "get_json", lambda *a, **k: {"data": []})
    monkeypatch.setattr(chat.memory, "maybe_review_in_background", lambda *a: None)
    monkeypatch.setattr(chat.compaction, "maybe_compact_in_background", lambda *a: None)
    monkeypatch.setattr(chat, "supports_tools", lambda model, settings: True)
    client.put("/api/roles", json={"roles": [{"id": "dev", "name": "Dev", "model": "acme/m", "when": "all", "tools": {"mcp": mcp_access}}]})
    return chat


def test_an_agent_with_connectors_runs_through_pi_even_without_a_project_folder(monkeypatch, tmp_path):
    chat = live_chat(monkeypatch)
    client.put("/api/mcp", json={"servers": {"fake": {"command": "x"}}})
    runs = []
    monkeypatch.setattr(chat, "run_turn", lambda **kw: runs.append(kw) or engine.PiResult("done", []))
    assert client.post("/api/messages", json={"message": "use my apps", "role_id": "dev"}).json()["reply"] == "done"
    run = runs[0]
    assert run["tools"] == ToolAccess(mcp="ask") and run["mcp_servers"] == {"fake": {"command": "x", "args": []}}
    assert run["workspace"] == tmp_path / "pi-agent" / "no-folder" and run["workspace"].is_dir()
    assert "`mcp` tool" in run["system_prompt"] and "workspace folder" not in run["system_prompt"]     # no file-tool talk


def test_connectors_on_but_none_set_up_means_a_plain_reply_that_does_not_pretend(monkeypatch):
    chat = live_chat(monkeypatch)
    monkeypatch.setattr(chat, "run_turn", lambda **kw: (_ for _ in ()).throw(AssertionError("Pi must not start")))
    sent = {}
    monkeypatch.setattr(chat, "generate_openrouter_reply", lambda **kw: sent.update(kw) or type("R", (), {"text": "ok", "model": "acme/m"})())
    client.post("/api/messages", json={"message": "hi", "role_id": "dev"})
    assert "No connectors are set up" in sent["role_instructions"]


def test_the_workspace_mode_governs_connector_calls(monkeypatch):
    chat = live_chat(monkeypatch, mcp_access="allow")
    client.put("/api/mcp", json={"servers": {"fake": {"command": "x"}}})
    seen = []
    monkeypatch.setattr(chat, "run_turn", lambda **kw: seen.append(kw["tools"].mcp) or engine.PiResult("done", []))
    for mode in ("auto", "manual", "accept_edits", "bypass", "plan"):
        client.patch("/api/workspaces/local", json={"mode": mode})
        client.post("/api/messages", json={"message": "go", "role_id": "dev"})
    # plan = read only, so a connector agent then has nothing to do and simply chats
    assert seen == ["allow", "ask", "ask", "allow"]


def test_links_open_in_the_real_browser_and_only_web_addresses(monkeypatch):
    import webbrowser
    opened = []
    monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(url))
    assert client.post("/api/open-url", json={"url": "https://accounts.example.com/oauth?x=1"}).status_code == 200
    assert client.post("/api/open-url", json={"url": "file:///etc/passwd"}).status_code == 400
    assert client.post("/api/open-url", json={"url": "javascript:alert(1)"}).status_code == 400
    assert opened == ["https://accounts.example.com/oauth?x=1"]


def test_an_agent_only_gets_the_connectors_ticked_for_it_and_stays_within_its_apps(monkeypatch):
    chat = live_chat(monkeypatch)
    client.put("/api/mcp", json={"servers": {"composio": {"url": "https://connect.composio.dev/mcp"}, "files": {"command": "x"}}})
    runs = []
    monkeypatch.setattr(chat, "run_turn", lambda **kw: runs.append(kw) or engine.PiResult("done", []))

    def agent(tools):
        client.put("/api/roles", json={"roles": [{"id": "dev", "name": "Dev", "model": "acme/m", "when": "all", "tools": tools}]})
        client.post("/api/messages", json={"message": "go", "role_id": "dev"})
        return runs[-1]

    assert sorted(agent({"mcp": "ask"})["mcp_servers"]) == ["composio", "files"]                      # None = every connector
    only = agent({"mcp": "ask", "mcp_servers": ["composio"], "mcp_apps": ["Gmail", "Notion"]})
    assert list(only["mcp_servers"]) == ["composio"]
    assert "use only these apps: Gmail, Notion" in only["system_prompt"]
    assert "use only these apps" not in agent({"mcp": "ask", "mcp_servers": ["files"], "mcp_apps": ["Gmail"]})["system_prompt"]   # no Composio, no app talk
    count = len(runs)
    client.put("/api/roles", json={"roles": [{"id": "dev", "name": "Dev", "model": "acme/m", "when": "all", "tools": {"mcp": "ask", "mcp_servers": ["gone"]}}]})
    monkeypatch.setattr(chat, "generate_openrouter_reply", lambda **kw: type("R", (), {"text": "ok", "model": "acme/m"})())
    client.post("/api/messages", json={"message": "go", "role_id": "dev"})
    assert len(runs) == count                                                                          # a connector that no longer exists = plain chat


def test_modes_keep_which_connectors_an_agent_may_use():
    tools = ToolAccess(mcp="allow", mcp_servers=["composio"], mcp_apps=["Gmail"])
    from colony.core.agents import apply_mode
    assert apply_mode(tools, "manual") == ToolAccess(mcp="ask", mcp_servers=["composio"], mcp_apps=["Gmail"])
