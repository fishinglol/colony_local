"""Tests for OpenClaw Gateway Engine Bridge."""
import json
import pytest
from fastapi.testclient import TestClient

from colony.app import app
from colony.config import Settings, get_settings
from colony.core import chat
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

    monkeypatch.setattr(openclaw.urllib.request, "urlopen", lambda req, timeout=None: FakeResp())
    assert openclaw.is_openclaw_available(settings) is True

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
    monkeypatch.setattr(openclaw, "is_openclaw_available", lambda s: True)
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

    monkeypatch.setattr(chat.memory, "maybe_review_in_background", lambda *a: None)
    monkeypatch.setattr(openclaw, "is_openclaw_available", lambda s: True)

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
