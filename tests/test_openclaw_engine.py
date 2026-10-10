"""Tests for OpenClaw Gateway Engine Bridge."""
import json
import pytest
from fastapi.testclient import TestClient

from colony.app import app
from colony.config import Settings, get_settings
from colony.core.agents import ToolAccess
from colony.engine import openclaw
from colony.llm.http import ProviderError


def test_resolve_agent_target():
    assert openclaw.resolve_agent_target("thinker") == "thinker"
    assert openclaw.resolve_agent_target("agent_01") == "agent_01"
    assert openclaw.resolve_agent_target("agent with spaces!") == "agent-with-spaces"
    assert openclaw.resolve_agent_target(None) == "main"
    assert openclaw.resolve_agent_target("") == "main"


def test_build_session_user():
    user = openclaw.build_session_user("ws_123", "thinker", "main")
    assert user == "ome-ws_123-main-thinker"

    user_anon = openclaw.build_session_user("ws_xyz", None, None)
    assert user_anon == "ome-ws_xyz-main-anon"


def test_is_openclaw_available(monkeypatch):
    settings = Settings(openclaw_gateway_url="http://127.0.0.1:18789")

    # When probe succeeds
    class FakeResp:
        status = 200
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    monkeypatch.setattr(openclaw.urllib.request, "urlopen", lambda url, timeout=None: FakeResp())
    assert openclaw.is_openclaw_available(settings) is True

    # Warming up: the port answers, but /readyz says 503 — not available yet
    seen = []

    def fake_warming(url, timeout=None):
        seen.append(url)
        raise openclaw.urllib.error.HTTPError(url, 503, "not ready", {}, None)

    monkeypatch.setattr(openclaw.urllib.request, "urlopen", fake_warming)
    assert openclaw.is_openclaw_available(settings) is False
    assert seen == ["http://127.0.0.1:18789/readyz"]

    # When probe fails
    def fake_fail(*args, **kwargs):
        raise OSError("Connection refused")

    monkeypatch.setattr(openclaw.urllib.request, "urlopen", fake_fail)
    assert openclaw.is_openclaw_available(settings) is False


def test_get_openclaw_status(monkeypatch):
    settings = Settings(
        openclaw_gateway_enabled=True,
        openclaw_gateway_url="http://127.0.0.1:18789",
        openclaw_gateway_token="secret_token",
    )
    monkeypatch.setattr(openclaw, "is_openclaw_available", lambda s=None: True)
    status = openclaw.get_openclaw_status(settings)
    assert status["enabled"] is True
    assert status["available"] is True
    assert status["url"] == "http://127.0.0.1:18789"
    assert status["has_token"] is True


def test_run_openclaw_turn_success(monkeypatch):
    settings = Settings(
        openclaw_gateway_url="http://127.0.0.1:18789",
        openclaw_gateway_token="test_tok",
    )

    class FakeChatResp:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self):
            return json.dumps({
                "model": "openclaw/thinker",
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": "Analysis complete.",
                        "tool_calls": [{
                            "function": {
                                "name": "bash",
                                "arguments": '{"command": "pytest"}',
                            }
                        }]
                    }
                }]
            }).encode("utf-8")

    monkeypatch.setattr(openclaw.urllib.request, "urlopen", lambda req, timeout=None: FakeChatResp())
    monkeypatch.setattr(openclaw, "ensure_agent", lambda *a, **k: None)

    res = openclaw.run_openclaw_turn(
        settings=settings,
        role_id="thinker",
        role_name="Thinker",
        role_model="nemotron-3-super",
        role_instructions="think step by step",
        workspace_id="ws_01",
        channel="mix",
        user_message="Analyze project",
    )

    assert res.reply == "Analysis complete."
    assert res.model == "openclaw/thinker"
    assert len(res.actions) == 1
    assert "bash" in res.actions[0]


def test_chat_routes_to_openclaw_when_available(monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "false")
    get_settings.cache_clear()

    monkeypatch.setattr(openclaw, "is_openclaw_available", lambda s=None: True)

    def fake_turn(**kwargs):
        return openclaw.OpenClawTurnResult(
            reply="Answer from OpenClaw Gateway",
            model="openclaw/coder",
            actions=["git status"],
        )

    monkeypatch.setattr(openclaw, "run_openclaw_turn", fake_turn)

    client = TestClient(app)
    res = client.post("/api/messages", json={
        "workspace_id": "local",
        "message": "check git",
        "role_id": "coding",
    })
    assert res.status_code == 200
    data = res.json()
    assert "Answer from OpenClaw Gateway" in data["reply"]
    assert "git status" in data["actions"]


def test_openclaw_status_api():
    client = TestClient(app)
    res = client.get("/api/openclaw/status")
    assert res.status_code == 200
    data = res.json()
    assert "enabled" in data
    assert "available" in data
    assert "url" in data


def test_each_role_gets_its_own_openclaw_agent_added_to_the_config(monkeypatch, tmp_path):
    settings = Settings(openclaw_gateway_url="http://127.0.0.1:18789", data_dir=tmp_path)
    openclaw.write_config({"agents": {"entries": {"main": {}}}, "tools": {"profile": "full"}})

    class Models:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self):
            return json.dumps({"data": [{"id": "openclaw"}, {"id": "openclaw/ws_1-coder"}]}).encode()

    monkeypatch.setattr(openclaw.urllib.request, "urlopen", lambda url, timeout=None: Models())
    assert openclaw.agent_id_for("ws_1", "Coder") == "ws_1-coder"
    monkeypatch.setattr(openclaw.time, "sleep", lambda s: None)
    openclaw.ensure_agent(settings, "ws_1-coder", "Coder", tools=ToolAccess(read="allow", bash="ask"), web_search=True)

    cfg = openclaw.read_config()
    assert cfg["agents"]["ownership"] == "explicit"            # OpenClaw rejects a roster without it
    assert set(cfg["agents"]["entries"]) == {"main", "ws_1-coder"}
    assert cfg["agents"]["entries"]["ws_1-coder"]["workspace"].startswith(str(tmp_path))   # never the user's project
    assert cfg["tools"] == {"profile": "full"}                  # the rest of the config is untouched
    entry = cfg["agents"]["entries"]["ws_1-coder"]              # lean: only the tools the role has (46k -> ~5k tokens)
    assert entry["tools"] == {"profile": "minimal", "alsoAllow": ["web_search", "read", "write", "edit", "memory_search", "memory_get", "exec"]}
    assert entry["skills"] == [] and entry["contextInjection"] == "continuation-skip"

    openclaw.ensure_agent(settings, "ws_1-coder", "Coder", tools=ToolAccess(), web_search=False)   # the user turned tools off
    assert openclaw.read_config()["agents"]["entries"]["ws_1-coder"]["tools"]["alsoAllow"] == ["read", "write", "edit", "memory_search", "memory_get"]


def test_ensure_agent_fails_clearly_when_the_gateway_never_lists_it(monkeypatch, tmp_path):
    settings = Settings(openclaw_gateway_url="http://127.0.0.1:18789", data_dir=tmp_path)
    monkeypatch.setattr(openclaw.urllib.request, "urlopen", lambda url, timeout=None: (_ for _ in ()).throw(OSError("down")))
    with pytest.raises(ProviderError):
        openclaw.ensure_agent(settings, "ws_1-x", "X", wait_seconds=0.2)


def test_a_session_is_sent_only_what_it_has_not_seen(tmp_path):
    settings = Settings(data_dir=tmp_path)
    history = [{"role": "user", "content": "q1"}, {"role": "assistant", "content": "[Buddy] a1"},
               {"role": "user", "content": "q2"}, {"role": "assistant", "content": "[Coder] a2"}]
    ids = ["m1", "m2", "m3", "m4"]
    assert openclaw.unseen(settings, "s", history, ids) == history            # new session: everything, once
    openclaw.mark_seen(settings, "s", "m2")                                    # it answered up to m2
    assert [m["content"] for m in openclaw.unseen(settings, "s", history, ids)] == ["q2", "[Coder] a2"]
    openclaw.mark_seen(settings, "s", "m4")
    assert openclaw.unseen(settings, "s", history, ids) == []                  # nothing new since its last answer
    assert openclaw.unseen(settings, "other", history, ids) == history        # sessions are independent
    openclaw.mark_seen(settings, "s", "gone")                                  # marker no longer in view (compacted)
    assert openclaw.unseen(settings, "s", history, ids) == history


def test_run_turn_sends_only_new_messages_to_the_roles_own_agent(monkeypatch, tmp_path):
    settings = Settings(openclaw_gateway_url="http://127.0.0.1:18789", data_dir=tmp_path)
    monkeypatch.setattr(openclaw, "ensure_agent", lambda *a, **k: None)
    sent = {}

    class Resp:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self):
            return json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode()

    def fake_urlopen(req, timeout=None):
        sent.update(json.loads(req.data))
        return Resp()

    monkeypatch.setattr(openclaw.urllib.request, "urlopen", fake_urlopen)
    history = [{"role": "user", "content": "old"}, {"role": "assistant", "content": "[Buddy] mine"},
               {"role": "assistant", "content": "[Coder] other agent"}]
    res = openclaw.run_openclaw_turn(
        settings=settings, role_id="chitchat", role_name="Buddy", role_model="ollama/x", role_instructions="",
        workspace_id="ws_1", channel="auto", user_message="new question", history=history, history_ids=["a", "b", "c"])
    assert sent["model"] == "openclaw/ws_1-chitchat"
    assert len(sent["messages"]) == 5                  # system + 3 first-time history + the new message
    openclaw.mark_seen(settings, res.session_user, "b")
    openclaw.run_openclaw_turn(
        settings=settings, role_id="chitchat", role_name="Buddy", role_model="ollama/x", role_instructions="",
        workspace_id="ws_1", channel="auto", user_message="next", history=history, history_ids=["a", "b", "c"])
    bodies = [m["content"] for m in sent["messages"] if m["role"] != "system"]
    assert bodies == ["[Coder] other agent", "next"]   # its own earlier turns are not sent again


def test_openclaw_is_given_the_whole_conversation(monkeypatch):
    from colony.store.history import append_exchange, get_all_messages

    monkeypatch.setenv("MOCK_MODE", "false")
    get_settings.cache_clear()
    monkeypatch.setattr(openclaw, "is_openclaw_available", lambda s=None: True)

    for i in range(3):
        append_exchange(conversation_id="local", user_message=f"q{i}", assistant_response={"reply": f"a{i}", "role_name": "Buddy"})
    ids = [m["id"] for m in get_all_messages("local")]
    seen = {}

    def fake_turn(**kwargs):
        seen.update(kwargs)
        return openclaw.OpenClawTurnResult(reply="ok", model="openclaw/x", session_user="s")

    monkeypatch.setattr(openclaw, "run_openclaw_turn", fake_turn)
    res = TestClient(app).post("/api/messages", json={"workspace_id": "local", "message": "next", "role_id": "coding"})
    assert res.status_code == 200
    # every message is offered, so the marker of a session that last answered anywhere in it is found and nothing is sent twice
    assert seen["history_ids"] == ids
    assert [m["content"] for m in seen["history"]][-2:] == ["q2", "[Buddy] a2"]
    new_ids = [m["id"] for m in get_all_messages("local")]
    assert openclaw._read_seen(get_settings())["s"] == new_ids[-1]    # the reply it just gave is what it has now seen


def test_images_travel_to_openclaw_as_data_uri_parts_on_the_new_message(monkeypatch, tmp_path):
    import base64
    from colony.core import attachments
    settings = Settings(openclaw_gateway_url="http://127.0.0.1:18789", data_dir=tmp_path)
    monkeypatch.setattr(openclaw, "ensure_agent", lambda *a, **k: None)
    png = b"\x89PNG\r\n\x1a\nfake"
    ref = attachments.save(settings, "ws_1", "red.png", png)
    sent = {}

    class Resp:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self):
            return json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode()

    def fake_urlopen(req, timeout=None):
        sent.update(json.loads(req.data))
        return Resp()

    monkeypatch.setattr(openclaw.urllib.request, "urlopen", fake_urlopen)
    openclaw.run_openclaw_turn(settings=settings, role_id="coder", role_name="Coder", role_model="ollama/x", role_instructions="",
                               workspace_id="ws_1", channel="auto", user_message="what colour?", media=[ref])
    content = sent["messages"][-1]["content"]
    assert content[0] == {"type": "text", "text": "what colour?"}
    assert content[1]["image_url"]["url"] == "data:image/png;base64," + base64.b64encode(png).decode()
    openclaw.run_openclaw_turn(settings=settings, role_id="coder", role_name="Coder", role_model="ollama/x", role_instructions="",
                               workspace_id="ws_1", channel="auto", user_message="plain")
    assert sent["messages"][-1]["content"] == "plain"                  # no media: still a plain string


def test_a_pdf_goes_to_the_responses_endpoint_as_an_input_file(monkeypatch, tmp_path):
    import base64
    from colony.core import attachments
    settings = Settings(openclaw_gateway_url="http://127.0.0.1:18789", data_dir=tmp_path)
    monkeypatch.setattr(openclaw, "ensure_agent", lambda *a, **k: None)
    pdf = b"%PDF-1.4 fake"
    ref = attachments.save(settings, "ws_1", "report.pdf", pdf)
    seen = {}

    def fake_post(settings, payload, model, timeout, path="/v1/chat/completions"):
        seen.update(path=path, payload=payload, model=model)
        return {"model": "ollama/x", "output": [{"type": "message", "content": [{"type": "output_text", "text": "It says hi."}]}],
                "usage": {"input_tokens": 321}}

    monkeypatch.setattr(openclaw, "_gateway_post", fake_post)
    res = openclaw.run_openclaw_turn(settings=settings, role_id="coder", role_name="Coder", role_model="ollama/x", role_instructions="Be brief.",
                                     workspace_id="ws_1", channel="auto", user_message="summarise", media=[ref])
    assert res.reply == "It says hi." and seen["path"] == "/v1/responses" and seen["model"] == "ollama/x"
    body = seen["payload"]
    assert "Be brief." in body["instructions"] and body["model"] == "openclaw/ws_1-coder"
    last = body["input"][-1]["content"]
    assert last[0] == {"type": "input_text", "text": "summarise"}
    assert last[1] == {"type": "input_file", "source": {"type": "base64", "media_type": "application/pdf",
                                                        "data": base64.b64encode(pdf).decode(), "filename": "report.pdf"}}
    assert openclaw.last_prompt_tokens(settings, "ws_1-coder") == 321


def test_responses_endpoint_and_system_agent_are_switched_on_once():
    cfg = {}
    assert openclaw._enable_responses(cfg) is True and cfg["gateway"]["http"]["endpoints"]["responses"]["enabled"] is True
    assert openclaw._enable_responses(cfg) is False
    assert openclaw._set_system_agent(cfg) is True and cfg["agents"]["defaults"]["systemAgent"] == {"agentId": "main"}
    assert openclaw._set_system_agent(cfg) is False
    owned = {"agents": {"defaults": {"systemAgent": {"agentId": "ops"}}}}
    assert openclaw._set_system_agent(owned) is False and owned["agents"]["defaults"]["systemAgent"]["agentId"] == "ops"
