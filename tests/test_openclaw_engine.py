"""Tests for OpenClaw Gateway Engine Bridge."""
import json
from pathlib import Path

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
        def __iter__(self):
            return _sse(self.read())
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
    assert entry["tools"] == {"profile": "minimal", "alsoAllow": ["web_search", "web_fetch", "memory_search", "memory_get", "cron", "read", "write", "edit", "exec"]}
    assert entry["skills"] == [] and entry["contextInjection"] == "continuation-skip"

    openclaw.ensure_agent(settings, "ws_1-coder", "Coder", tools=ToolAccess(), web_search=False)   # the user turned tools off
    assert openclaw.read_config()["agents"]["entries"]["ws_1-coder"]["tools"]["alsoAllow"] == ["memory_search", "memory_get", "cron", "read", "write", "edit"]
    assert "thinkingDefault" not in openclaw.read_config()["agents"]["entries"]["ws_1-coder"]   # "default" = the model's own

    openclaw.ensure_agent(settings, "ws_1-coder", "Coder", tools=ToolAccess(), thinking="high")      # the role's reasoning level
    assert openclaw.read_config()["agents"]["entries"]["ws_1-coder"]["thinkingDefault"] == "high"


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
        def __iter__(self):
            return _sse(self.read())

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
        def __iter__(self):
            return _sse(self.read())

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
    assert "You are Coder" in body["instructions"] and body["model"] == "openclaw/ws_1-coder"
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


def test_every_agent_has_its_own_soul_and_the_shared_user_md_is_copied_in(tmp_path):
    settings = Settings(data_dir=tmp_path)
    shared = openclaw.memory_dir(settings, "ws_1")
    openclaw._seed_memory_dir(shared)
    (shared / "USER.md").write_text("# User\n- likes tea\n")
    coder = openclaw.write_agent_files(settings, "ws_1", "ws_1-coder", "Coder", "Show code first.")
    buddy = openclaw.write_agent_files(settings, "ws_1", "ws_1-buddy", "Buddy", "")
    c, b = openclaw.agent_dir(settings, "ws_1-coder"), openclaw.agent_dir(settings, "ws_1-buddy")
    assert (c / "SOUL.md").read_text() == "# Coder\nShow code first.\n"                     # only its own persona
    assert (b / "SOUL.md").read_text() == "# Buddy\nHelp the user complete their request.\n"
    assert "Coder" in (c / "IDENTITY.md").read_text() and (c / "USER.md").read_text() == "# User\n- likes tea\n"
    rules = (c / "AGENTS.md").read_text()
    assert f"{shared}/USER.md" in rules and "memory_search" in rules and "English" in rules      # absolute paths: the agent's cwd is the project
    assert (c / "memory").is_dir() and (c / "MEMORY.md").exists() and coder != buddy
    assert not (shared / "SOUL.md").exists()                                                # the shared folder holds memory only

    assert openclaw.write_agent_files(settings, "ws_1", "ws_1-coder", "Coder", "Show code first.") == coder   # nothing changed: same tag
    (c / "AGENTS.md").write_text("old text")                                                  # a stale managed file is put right
    assert openclaw.write_agent_files(settings, "ws_1", "ws_1-coder", "Coder", "Show code first.") == coder
    assert "memory_search" in (c / "AGENTS.md").read_text()
    assert openclaw.write_agent_files(settings, "ws_1", "ws_1-coder", "Coder", "Be rude.") != coder      # edited persona: new tag

    (shared / "USER.md").write_text("# User\n- likes coffee\n")                               # the copy follows the shared file
    openclaw.write_agent_files(settings, "ws_1", "ws_1-coder", "Coder", "Be rude.")
    assert "likes coffee" in (c / "USER.md").read_text()


def test_an_edited_persona_starts_a_new_openclaw_session():
    old = openclaw.build_session_user("ws_1", "coder", "auto", "abc12345")
    assert old == "ome-ws_1-auto-coder-abc12345" and old != openclaw.build_session_user("ws_1", "coder", "auto", "ffff0000")


def test_the_request_carries_only_the_name_and_permissions(monkeypatch, tmp_path):
    settings = Settings(openclaw_gateway_url="http://127.0.0.1:18789", data_dir=tmp_path)
    monkeypatch.setattr(openclaw, "ensure_agent", lambda *a, **k: None)
    seen = {}
    monkeypatch.setattr(openclaw, "_gateway_post", lambda settings, payload, model, timeout, path="", on_text=None: (seen.update(payload=payload) or
                        {"choices": [{"message": {"content": "ok"}}]}))
    openclaw.run_openclaw_turn(settings=settings, role_id="coder", role_name="Coder", role_model="ollama/x", role_instructions="SECRET PERSONA",
                               workspace_id="ws_1", channel="auto", user_message="hi", tools=ToolAccess(read="allow"))
    system = seen["payload"]["messages"][0]["content"]
    assert system.startswith("You are Coder") and "SECRET PERSONA" not in system and "Project files, read: ALLOWED" in system
    assert "Shared memory folder" not in system and "memory_search" not in system
    assert "SECRET PERSONA" in (openclaw.agent_dir(settings, "ws_1-coder") / "SOUL.md").read_text()
    assert seen["payload"]["user"].startswith("ome-ws_1-auto-coder-")


def test_a_call_is_sent_again_when_the_gateway_restarted_under_it(monkeypatch):
    settings = Settings(openclaw_gateway_url="http://127.0.0.1:18789")
    calls = []

    class Ok:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self): return b'{"ok": true}'

    def flaky(req, timeout=None):
        calls.append(1)
        if len(calls) == 1:
            import io, urllib.error
            raise urllib.error.HTTPError("u", 500, "x", {}, io.BytesIO(b"boom"))
        return Ok()

    monkeypatch.setattr(openclaw.urllib.request, "urlopen", flaky)
    monkeypatch.setattr(openclaw, "_gateway_restarted", lambda s, wait=200.0: True)
    assert openclaw._gateway_post(settings, {}, None, 5) == {"ok": True} and len(calls) == 2

    calls.clear()
    monkeypatch.setattr(openclaw, "_gateway_restarted", lambda s, wait=200.0: False)      # it stayed up: a genuine error, no second try
    with pytest.raises(ProviderError):
        openclaw._gateway_post(settings, {}, None, 5)
    assert len(calls) == 1


def test_gateway_restarted_means_it_went_down_and_came_back(monkeypatch):
    settings = Settings()
    monkeypatch.setattr(openclaw.time, "sleep", lambda s: None)
    up = iter([True, True, False, False, True])       # up, up, down, down, back
    monkeypatch.setattr(openclaw, "is_openclaw_available", lambda s=None: next(up))
    assert openclaw._gateway_restarted(settings) is True
    monkeypatch.setattr(openclaw, "is_openclaw_available", lambda s=None: True)            # never went down
    assert openclaw._gateway_restarted(settings) is False


def test_gateway_is_prepared_when_its_log_has_no_recent_preparing_line(tmp_path):
    from datetime import datetime
    settings = Settings()
    log = tmp_path / "gateway.log"
    stamp = "2026-10-10T13:23:36.124+08:00"
    at = datetime.fromisoformat(stamp).timestamp()
    log.write_text(f"{stamp} [state/agent-admission] agent database startup preparation still running agentId=main phase=models\n")
    assert openclaw.gateway_prepared(settings, log, now=at + 30) is False           # still working
    assert openclaw.gateway_prepared(settings, log, now=at + 100) is True           # quiet for more than a minute
    log.write_text("2026-10-10T13:00:00.000+08:00 [gateway] ready\n")
    assert openclaw.gateway_prepared(settings, log, now=at) is True
    assert openclaw.gateway_prepared(settings, tmp_path / "missing.log") is True    # a Gateway Colony did not start


def test_gateway_is_prepared_after_recovery_line_even_if_a_colored_preparing_line_has_no_timestamp(tmp_path):
    settings = Settings()
    log = tmp_path / "gateway.log"
    log.write_text(
        "\x1b[33mSessions remain unavailable until background inspection and preparation finish.\x1b[39m\n"
        "\x1b[90m2026-10-12T10:09:10.588+08:00\x1b[39m [state/agent-admission] agent database recovered after background inspection and preparation\n")
    assert openclaw.gateway_prepared(settings, log) is True


def test_a_turn_waits_for_the_gateway_to_finish_preparing(monkeypatch, tmp_path):
    settings = Settings(data_dir=tmp_path)
    states = iter([False, True])
    monkeypatch.setattr(openclaw, "gateway_prepared", lambda s, log=None, now=None: next(states))
    monkeypatch.setattr(openclaw, "ensure_agent", lambda *a, **k: None)
    monkeypatch.setattr(openclaw, "_gateway_post", lambda *a, **k: {"choices": [{"message": {"content": "ok"}}]})
    waited = []
    monkeypatch.setattr(openclaw, "wait_prepared", lambda s, timeout=480.0: waited.append(timeout) or True)
    res = openclaw.run_openclaw_turn(settings=settings, role_id="c", role_name="C", role_model="ollama/x", role_instructions="",
                                     workspace_id="ws_1", channel="auto", user_message="hi")
    assert res.reply == "ok" and len(waited) == 1


def test_a_403_while_the_gateway_reloads_its_config_is_sent_again_and_not_blamed_on_the_key(monkeypatch):
    import io, urllib.error
    settings = Settings(openclaw_gateway_url="http://127.0.0.1:18789")
    calls = []
    body = b'{"error":{"message":"Gateway requester authority changed","type":"permission_error"}}'

    class Ok:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self): return b'{"ok": true}'

    def reloading(req, timeout=None):
        calls.append(1)
        if len(calls) == 1:
            raise urllib.error.HTTPError("u", 403, "x", {}, io.BytesIO(body))
        return Ok()

    monkeypatch.setattr(openclaw.urllib.request, "urlopen", reloading)
    monkeypatch.setattr(openclaw.time, "sleep", lambda s: None)
    assert openclaw._gateway_post(settings, {}, None, 5) == {"ok": True} and len(calls) == 2

    from colony.core.errors import explain
    exc = ProviderError("OpenClaw Gateway request failed (403): " + body.decode(), status=403, provider_message=body.decode())
    assert "API Key" not in explain(exc, "ollama/nemotron-3-super")


def _sse(body: bytes):
    """A non-streaming reply body as the event stream the Gateway sends when `stream` is on."""
    data = json.loads(body)
    msg = data["choices"][0]["message"]
    delta = {"content": msg.get("content"), "tool_calls": [{**tc, "index": 0} for tc in msg.get("tool_calls") or []]}
    chunk = {"model": data.get("model"), "usage": data.get("usage"), "choices": [{"delta": delta}]}
    return iter([b"data: " + json.dumps(chunk).encode() + b"\n", b"data: [DONE]\n"])


def test_gateway_stream_is_read_into_a_normal_reply():
    import io
    chunks = [{"model": "openclaw/a", "choices": [{"delta": {"role": "assistant"}}]},
              {"choices": [{"delta": {"content": "Hel"}}]}, {"choices": [{"delta": {"content": "lo"}}]},
              {"choices": [], "usage": {"prompt_tokens": 7}}]
    body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
    seen = []
    data = openclaw._read_stream(io.BytesIO(body.encode()), seen.append)
    assert seen == ["Hel", "Hello"]
    assert data["choices"][0]["message"]["content"] == "Hello" and data["usage"]["prompt_tokens"] == 7


def make_skill(folder, name, description):
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(f'---\nname: {name}\ndescription: "{description}"\n---\n\n# {name}\n', encoding="utf-8")


def test_skills_are_added_from_a_folder_listed_and_given_only_to_that_agent(monkeypatch, tmp_path):
    settings = Settings(openclaw_gateway_url="http://127.0.0.1:18789", data_dir=tmp_path / "data")
    one, many = tmp_path / "zebra", tmp_path / "pack"
    make_skill(one, "zebra-protocol", "Use for the mascot name.")
    make_skill(many / "a", "alpha", "First.")
    make_skill(many / "b", "beta", "Second.")
    assert openclaw.add_skills(settings, "ws_1-coder", one) == ["zebra"]
    assert openclaw.add_skills(settings, "ws_1-coder", many) == ["a", "b"]
    assert [s["name"] for s in openclaw.list_skills(settings, "ws_1-coder")] == ["alpha", "beta", "zebra-protocol"]
    assert openclaw.list_skills(settings, "ws_1-coder")[2]["description"] == "Use for the mascot name."
    assert openclaw.list_skills(settings, "ws_1-writer") == []
    make_skill(settings.data_dir / "openclaw-agents" / "ws_1-writer" / "skills" / "repo" / "nested", "nested-skill", "From a cloned repo.")
    assert [(s["name"], s["folder"]) for s in openclaw.list_skills(settings, "ws_1-writer")] == [("nested-skill", "repo/nested")]
    assert openclaw.remove_skill(settings, "ws_1-writer", "repo/nested") is True
    assert openclaw.remove_skill(settings, "ws_1-writer", "repo") is False         # not a skill folder itself

    openclaw.write_config({"agents": {"entries": {"main": {}}}})
    monkeypatch.setattr(openclaw, "_known_agents", {"ws_1-coder": None})
    monkeypatch.setattr(openclaw.time, "sleep", lambda s: None)
    monkeypatch.setattr(openclaw, "_gateway_lists", lambda *a, **k: True, raising=False)
    try:
        openclaw.ensure_agent(settings, "ws_1-coder", "Coder", wait_seconds=0)
    except ProviderError:
        pass                                    # no Gateway here; the config is written before it waits
    assert openclaw.read_config()["agents"]["entries"]["ws_1-coder"]["skills"] == ["alpha", "beta", "zebra-protocol"]

    assert openclaw.remove_skill(settings, "ws_1-coder", "a") is True
    assert openclaw.remove_skill(settings, "ws_1-coder", "../../x") is False       # never outside the skills folder
    assert [s["folder"] for s in openclaw.list_skills(settings, "ws_1-coder")] == ["b", "zebra"]


def test_skills_api_adds_lists_and_removes(tmp_path):
    ws = TestClient(app).post("/api/workspaces", json={"name": "S"}).json()["id"]
    c = TestClient(app)
    role = {"id": "coder", "name": "Coder", "model": "ollama/test", "when": "code"}
    c.put(f"/api/roles?workspace_id={ws}", json={"roles": [role]})
    make_skill(tmp_path / "src" / "zebra", "zebra-protocol", "Mascot.")
    url = f"/api/roles/coder/skills?workspace_id={ws}"
    assert c.post(url, json={"path": str(tmp_path / "src")}).json()["skills"][0]["name"] == "zebra-protocol"
    assert c.post(url, json={"path": str(tmp_path / "missing")}).status_code == 400
    assert c.post(url, json={"path": str(tmp_path)}).status_code == 400          # no SKILL.md anywhere inside
    assert c.delete(f"/api/roles/coder/skills/zebra?workspace_id={ws}").json()["skills"] == []
    assert c.get(f"/api/roles/nobody/skills?workspace_id={ws}").status_code == 404


def test_a_native_turn_is_prepared_then_saved_to_the_conversation(monkeypatch):
    c = TestClient(app)
    ws = c.post("/api/workspaces", json={"name": "N"}).json()["id"]
    role = {"id": "coder", "name": "Coder", "model": "ollama/gemma4:31b", "when": "code", "instructions": "Be brief."}
    c.put(f"/api/roles?workspace_id={ws}", json={"roles": [role]})
    monkeypatch.setenv("MOCK_MODE", "false")
    get_settings.cache_clear()
    monkeypatch.setattr(openclaw, "is_openclaw_available", lambda settings=None: True)
    monkeypatch.setattr(openclaw, "gateway_prepared", lambda settings, **k: True)
    seen = {}
    monkeypatch.setattr(openclaw, "ensure_agent", lambda settings, agent_id, name, **k: seen.update(agent=agent_id, **k))

    prep = c.post("/api/turns/prepare", json={"workspace_id": ws, "role_id": "coder", "message": "hello there"}).json()
    assert prep["native"] is True and prep["agent_id"] == openclaw.agent_id_for(ws, "coder")
    assert prep["model"] == "ollama/gemma4:31b" and prep["session"].startswith("native-ome-")
    assert "You are Coder" in prep["message"] and prep["message"].endswith("hello there")
    assert seen["agent"] == prep["agent_id"]

    done = c.post("/api/turns/finish", json={"turn_id": prep["turn_id"], "reply": "[Coder] hi!"}).json()
    assert done["saved"] is True
    messages = c.get(f"/api/workspaces/{ws}/messages").json()["messages"]
    assert [m["content"] for m in messages][-2:] == ["hello there", "hi!"]      # the user's own words, and the reply without its label
    assert messages[-1]["metadata"]["role_id"] == "coder" and messages[-1]["metadata"]["decided_by"] == "direct"
    assert c.post("/api/turns/finish", json={"turn_id": prep["turn_id"], "reply": "x"}).status_code == 404

    # a file that is not there: the app is told to use the normal path, which explains it
    assert c.post("/api/turns/prepare", json={"workspace_id": ws, "role_id": "coder", "message": "see",
                                              "attachments": ["0" * 32]}).json() == {"native": False, "reason": "attachments"}

    # an image and a text file: the image travels as an attachment, the text is pasted under the message
    import base64
    up = lambda name, raw: c.post(f"/api/workspaces/{ws}/attachments", json={"name": name, "data": base64.b64encode(raw).decode()}).json()
    png, txt = up("red.png", b"\x89PNG fake"), up("n.txt", b"hello notes")
    prep = c.post("/api/turns/prepare", json={"workspace_id": ws, "role_id": "coder", "message": "look",
                                              "attachments": [png["id"], txt["id"]]}).json()
    assert prep["native"] is True and [(a["type"], a["fileName"]) for a in prep["attachments"]] == [("image", "red.png")]
    assert "hello notes" in prep["message"]
    c.post("/api/turns/finish", json={"turn_id": prep["turn_id"], "reply": "ok"})
    last_user = c.get(f"/api/workspaces/{ws}/messages").json()["messages"][-2]
    assert [a["name"] for a in last_user["attachments"]] == ["red.png", "n.txt"]


def test_a_group_chat_turn_asks_the_decider_who_answers(monkeypatch):
    from colony.core import native_turn
    from colony.core.decider import DeciderResult
    c = TestClient(app)
    ws = c.post("/api/workspaces", json={"name": "Mix"}).json()["id"]
    roles = [{"id": "a", "name": "Ann", "model": "ollama/x", "when": "chat"}, {"id": "b", "name": "Bo", "model": "ollama/y", "when": "code"}]
    c.put(f"/api/roles?workspace_id={ws}", json={"roles": roles})
    monkeypatch.setenv("MOCK_MODE", "false")
    get_settings.cache_clear()
    monkeypatch.setattr(openclaw, "is_openclaw_available", lambda settings=None: True)
    monkeypatch.setattr(openclaw, "gateway_prepared", lambda settings, **k: True)
    monkeypatch.setattr(openclaw, "ensure_agent", lambda *a, **k: None)
    monkeypatch.setattr(native_turn, "decide", lambda message, roles, settings, **k: DeciderResult(role=roles[1], confidence=0.8, source="jev"))

    prep = c.post("/api/turns/prepare", json={"workspace_id": ws, "message": "fix this bug", "channel": "auto"}).json()
    assert prep["role_id"] == "b" and prep["decided_by"] == "jev" and prep["agent_id"] == openclaw.agent_id_for(ws, "b")
    c.post("/api/turns/finish", json={"turn_id": prep["turn_id"], "reply": "done"})
    last = c.get(f"/api/workspaces/{ws}/messages").json()["messages"][-1]
    assert last["metadata"]["role_id"] == "b" and last["metadata"]["decided_by"] == "jev" and last["metadata"]["channel"] == "auto"


def test_an_agent_is_told_who_its_teammates_are_and_what_they_do(monkeypatch):
    c = TestClient(app)
    ws = c.post("/api/workspaces", json={"name": "Team"}).json()["id"]
    roles = [{"id": "a", "name": "Ann", "model": "ollama/x", "when": "casual chat"},
             {"id": "b", "name": "Bo", "model": "ollama/y", "when": "debugging code"}]
    c.put(f"/api/roles?workspace_id={ws}", json={"roles": roles})
    monkeypatch.setenv("MOCK_MODE", "false")
    get_settings.cache_clear()
    monkeypatch.setattr(openclaw, "is_openclaw_available", lambda settings=None: True)
    monkeypatch.setattr(openclaw, "gateway_prepared", lambda settings, **k: True)
    monkeypatch.setattr(openclaw, "ensure_agent", lambda *a, **k: None)

    msg = c.post("/api/turns/prepare", json={"workspace_id": ws, "role_id": "a", "message": "hi"}).json()["message"]
    assert "* Bo: debugging code" in msg and "takes work" not in msg      # the teammate and what it is for
    assert "* Ann:" not in msg                            # not itself
    solo = c.post("/api/workspaces", json={"name": "Solo"}).json()["id"]
    c.put(f"/api/roles?workspace_id={solo}", json={"roles": roles[:1]})
    msg = c.post("/api/turns/prepare", json={"workspace_id": solo, "role_id": "a", "message": "hi"}).json()["message"]
    assert "teammates" not in msg                         # alone in the team: nothing to say


def test_a_reply_that_ends_with_an_at_name_hands_the_task_to_a_teammate_who_accepts_it(monkeypatch):
    c = TestClient(app)
    ws = c.post("/api/workspaces", json={"name": "Hand"}).json()["id"]
    roles = [{"id": "a", "name": "Ann", "model": "ollama/x", "when": "chat"},
             {"id": "b", "name": "Bo", "model": "ollama/y", "when": "review code", "accepts_handoff": True},
             {"id": "c", "name": "Cy", "model": "ollama/z", "when": "write"}]          # Cy does not take work
    c.put(f"/api/roles?workspace_id={ws}", json={"roles": roles})
    monkeypatch.setenv("MOCK_MODE", "false")
    get_settings.cache_clear()
    monkeypatch.setattr(openclaw, "is_openclaw_available", lambda settings=None: True)
    monkeypatch.setattr(openclaw, "gateway_prepared", lambda settings, **k: True)
    monkeypatch.setattr(openclaw, "ensure_agent", lambda *a, **k: None)
    prep = lambda **b: c.post("/api/turns/prepare", json={"workspace_id": ws, **b})
    finish = lambda p, reply: c.post("/api/turns/finish", json={"turn_id": p["turn_id"], "reply": reply}).json()

    first = prep(role_id="a", message="check my code").json()
    assert "* Bo: review code [takes work from you]" in first["message"] and "* Cy: write\n" in first["message"] + "\n"
    done = finish(first, "Here it is.\n@bo please review the function above.")
    assert done["handoff"] == {"role_id": "b", "role_name": "Bo", "message": "please review the function above.", "from": "a", "hops": 1}
    assert "handoff" not in finish(prep(role_id="a", message="x").json(), "@Cy write it")     # Cy accepts nothing
    assert "handoff" not in finish(prep(role_id="a", message="x").json(), "Ask @Bo about it")  # not the last line's start

    second = prep(role_id="b", message=done["handoff"]["message"], handoff_from="a", hops=1).json()
    assert second["decided_by"] == "handoff" and "Ann hands you this task" in second["message"]
    finish(second, "[Bo] Looks fine.")
    msgs = c.get(f"/api/workspaces/{ws}/messages").json()["messages"]
    assert msgs[-1]["content"] == "Looks fine." and msgs[-1]["metadata"]["handed_by"] == "Ann"
    assert msgs[-2]["content"] != done["handoff"]["message"]                    # the task is not stored as something the user said

    # refused: Cy does not accept handoffs, an unknown sender, too many hops
    assert prep(role_id="c", message="t", handoff_from="a", hops=1).status_code == 404
    assert prep(role_id="b", message="t", handoff_from="zzz", hops=1).status_code == 404
    assert prep(role_id="b", message="t", handoff_from="a", hops=4).status_code == 404
    # the last allowed hop does not hand on again
    last = prep(role_id="b", message="t", handoff_from="a", hops=3).json()
    roles[0]["accepts_handoff"] = True
    c.put(f"/api/roles?workspace_id={ws}", json={"roles": roles})
    assert "handoff" not in finish(last, "@Ann your turn")


def test_new_moves_the_old_conversation_to_the_archive_and_keeps_only_the_command(monkeypatch):
    import json as _json
    c = TestClient(app)
    ws = c.post("/api/workspaces", json={"name": "Fresh", "folder": ""}).json()["id"]
    c.put(f"/api/roles?workspace_id={ws}", json={"roles": [{"id": "a", "name": "Ann", "model": "ollama/x", "when": "chat"}]})
    monkeypatch.setenv("MOCK_MODE", "false")
    get_settings.cache_clear()
    monkeypatch.setattr(openclaw, "is_openclaw_available", lambda settings=None: True)
    monkeypatch.setattr(openclaw, "gateway_prepared", lambda settings, **k: True)
    monkeypatch.setattr(openclaw, "ensure_agent", lambda *a, **k: None)
    say = lambda text, reply: c.post("/api/turns/finish", json={
        "turn_id": c.post("/api/turns/prepare", json={"workspace_id": ws, "role_id": "a", "message": text}).json()["turn_id"],
        "reply": reply}).json()
    for i in range(3):
        assert "archived" not in say(f"question {i}", f"answer {i}")
    settings = get_settings()
    openclaw._record_usage(settings, openclaw.agent_id_for(ws, "a"), "ollama/x", 5000)
    assert openclaw.last_prompt_tokens(settings, openclaw.agent_id_for(ws, "a")) == 5000
    done = say("/new", "New session started.")
    assert done["archived"] == 6
    assert openclaw.last_prompt_tokens(settings, openclaw.agent_id_for(ws, "a")) is None      # its gauge starts empty again
    shown = c.get(f"/api/workspaces/{ws}/messages").json()["messages"]
    assert [m["content"] for m in shown] == ["/new", "New session started."]
    files = sorted((get_settings().data_dir / "archive" / ws).glob("*.json"))
    assert len(files) == 1
    kept = _json.loads(files[0].read_text(encoding="utf-8"))["messages"]
    assert [m["content"] for m in kept] == ["question 0", "answer 0", "question 1", "answer 1", "question 2", "answer 2"]


def test_a_github_link_becomes_a_clone_url_and_only_github_over_https_is_accepted(tmp_path, monkeypatch):
    assert openclaw.github_clone_url("https://github.com/ScrapeCreators/social-media-research-skills") == \
        "https://github.com/ScrapeCreators/social-media-research-skills.git"
    assert openclaw.github_clone_url("https://github.com/o/r/tree/main/skills").endswith("/o/r.git")
    for bad in ("http://github.com/o/r", "https://evil.example/o/r", "https://github.com/o", "git@github.com:o/r.git", "file:///etc"):
        with pytest.raises(ValueError):
            openclaw.github_clone_url(bad)

    # the clone is stubbed: a repository with two skills in it
    def fake_run(cmd, **kw):
        repo = Path(cmd[-1])
        make_skill(repo / "skills" / "one", "one", "First.")
        make_skill(repo / "two", "two", "Second.")
        (repo / "README.md").write_text("x")
        return type("Done", (), {"returncode": 0, "stderr": ""})()
    monkeypatch.setattr(openclaw.subprocess, "run", fake_run)
    settings = Settings(openclaw_gateway_url="http://127.0.0.1:1", data_dir=tmp_path)
    assert openclaw.add_skills_from_github(settings, "ws_1-coder", "https://github.com/o/r") == ["one", "two"]
    assert [s["name"] for s in openclaw.list_skills(settings, "ws_1-coder")] == ["one", "two"]


def test_fenced_to_a_project_folder_an_agent_gets_exactly_its_role_s_file_tools():
    allow = openclaw._tool_allowlist(ToolAccess(read="allow", write="off", bash="off"), False, [], fenced=True)
    assert allow == ["memory_search", "memory_get", "cron", "read"]
    assert "exec" in openclaw._tool_allowlist(ToolAccess(bash="ask"), False, [], fenced=True)
    assert openclaw._tool_allowlist(ToolAccess(), False, [], fenced=True) == ["memory_search", "memory_get", "cron"]    # a chat-only role
    assert "write" in openclaw._tool_allowlist(ToolAccess(), False, [], fenced=False)     # no folder: it keeps the memory files
    assert "keeps" not in openclaw.agents_md(Path("/m"), writable=False) and "cannot edit" in openclaw.agents_md(Path("/m"), writable=False)


def test_a_native_turn_is_fenced_by_the_gateway_to_the_project_folder(monkeypatch, tmp_path):
    from colony.core import native_turn
    c = TestClient(app)
    folder = tmp_path / "proj"
    folder.mkdir()
    ws = c.post("/api/workspaces", json={"name": "F", "folder": str(folder)}).json()["id"]
    roles = [{"id": "w", "name": "Writer", "model": "ollama/x", "when": "w", "tools": {"read": "allow", "write": "ask"}},
             {"id": "r", "name": "Reader", "model": "ollama/x", "when": "r", "tools": {"read": "allow"}},
             {"id": "t", "name": "Talker", "model": "ollama/x", "when": "t"}]
    c.put(f"/api/roles?workspace_id={ws}", json={"roles": roles})
    monkeypatch.setenv("MOCK_MODE", "false")
    get_settings.cache_clear()
    monkeypatch.setattr(openclaw, "is_openclaw_available", lambda settings=None: True)
    monkeypatch.setattr(openclaw, "gateway_prepared", lambda settings, **k: True)
    monkeypatch.setattr(openclaw, "ensure_agent", lambda *a, **k: None)
    got = {r: c.post("/api/turns/prepare", json={"workspace_id": ws, "role_id": r, "message": "x"}).json() for r in ("w", "r", "t")}
    assert got["w"]["permission_mode"] == "guarded" and got["w"]["cwd"] == str(folder)
    assert got["r"]["permission_mode"] == "read-only" and got["t"]["permission_mode"] == "read-only"
    assert got["w"]["session"].startswith("native-ome-") and got["w"]["session"] != got["r"]["session"]
    c.patch(f"/api/workspaces/{ws}", json={"mode": "plan"})        # plan = read only, whatever the agent may do
    assert c.post("/api/turns/prepare", json={"workspace_id": ws, "role_id": "w", "message": "x"}).json()["permission_mode"] == "read-only"

    nofolder = c.post("/api/workspaces", json={"name": "N", "folder": ""}).json()["id"]
    c.put(f"/api/roles?workspace_id={nofolder}", json={"roles": [roles[2]]})
    chat_only = c.post("/api/turns/prepare", json={"workspace_id": nofolder, "role_id": "t", "message": "x"}).json()
    assert chat_only["cwd"] == str(openclaw.memory_dir(get_settings(), nofolder)) and chat_only["permission_mode"] == "guarded"
