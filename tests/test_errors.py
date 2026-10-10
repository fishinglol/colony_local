import pytest
from fastapi.testclient import TestClient

from colony.app import app
from colony.config import get_settings
from colony.core.errors import explain
from colony.llm.http import ProviderError


@pytest.mark.parametrize("status,expected", [
    (429, "ถูกจำกัดจำนวนครั้ง"),
    (401, "เรียก AI ไม่สำเร็จ"),
    (404, "ไม่รู้จักหรือเรียกโมเดล"),
    (400, "ไม่รู้จักหรือเรียกโมเดล"),
    (503, "ขัดข้องชั่วคราว"),
    (None, "เชื่อมต่ออินเทอร์เน็ต"),
])
def test_every_failure_kind_gets_a_plain_thai_explanation(status, expected):
    text = explain(ProviderError("raw {\"error\": ...}", status=status), "qwen/x:free")
    assert expected in text
    assert "raw" not in text  # never dump the provider's JSON on the user


def test_rate_limit_message_names_the_model_and_points_to_ask_another_agent():
    text = explain(ProviderError("x", status=429), "google/gemma-4-31b-it:free")
    assert "google/gemma-4-31b-it:free" in text and "Ask another agent" in text and "429" in text


def test_provider_message_is_pulled_out_of_the_json_body(monkeypatch):
    import io
    import urllib.error

    from colony.llm import http

    body = '{"error":{"message":"inkling is only available on agentic harnesses","code":403}}'

    def fake(request, timeout, context):
        raise urllib.error.HTTPError("http://x", 403, "Forbidden", {}, io.BytesIO(body.encode()))

    monkeypatch.setattr(http.urllib.request, "urlopen", fake)
    with pytest.raises(ProviderError) as info:
        http.post_json("http://x", {}, {}, 5, "Ollama", retries=0)
    assert info.value.status == 403
    assert info.value.provider_message == "inkling is only available on agentic harnesses"


def test_a_rate_limited_chat_shows_the_friendly_message_and_is_not_saved(monkeypatch):
    from colony.engine import openclaw

    monkeypatch.setenv("MOCK_MODE", "false")
    get_settings.cache_clear()
    monkeypatch.setattr(openclaw, "is_openclaw_available", lambda s=None: True)

    def limited(**kw):
        raise ProviderError('OpenClaw Gateway request failed (429): {"error":{"message":"slow down"}}', status=429)

    monkeypatch.setattr(openclaw, "run_openclaw_turn", limited)
    client = TestClient(app)
    body = client.post("/api/messages", json={"message": "hi", "role_id": "writing"}).json()
    assert "ถูกจำกัดจำนวนครั้ง" in body["reply"] and "slow down" not in body["reply"]
    # the failed exchange isn't written to history, so re-asking doesn't double up
    assert client.get(f"/api/workspaces/{body['workspace_id']}/messages").json()["messages"] == []


def test_test_model_endpoint_reports_success_and_failure(monkeypatch):
    from colony.api import agents as agents_api

    client = TestClient(app)
    # mock mode (the default in tests): always "works", no network
    assert client.post("/api/models/test", json={"model": "ollama/a"}).json()["ok"] is True

    monkeypatch.setenv("MOCK_MODE", "false")
    get_settings.cache_clear()
    monkeypatch.setattr(agents_api, "ping_model", lambda settings, model: ("OK", 1.234))
    good = client.post("/api/models/test", json={"model": "ollama/gemma4:31b"}).json()
    assert good == {"ok": True, "seconds": 1.2, "preview": "OK"}

    def refuse(settings, model):
        raise ProviderError("Ollama request failed: 404 not found", status=404)

    monkeypatch.setattr(agents_api, "ping_model", refuse)
    bad = client.post("/api/models/test", json={"model": "ollama/nope"}).json()
    assert bad["ok"] is False and "ollama pull nope" in bad["message"]


def test_ping_sends_one_small_message_through_a_lean_openclaw_agent(monkeypatch):
    from colony.engine import openclaw

    seen = {}
    monkeypatch.setattr(openclaw, "ensure_agent", lambda settings, agent_id, name, **kw: seen.update(agent=agent_id))

    def fake_post(settings, payload, model, timeout):
        seen.update(payload=payload, model=model)
        return {"choices": [{"message": {"content": "OK"}}]}

    monkeypatch.setattr(openclaw, "_gateway_post", fake_post)
    text, seconds = openclaw.ping_model(get_settings(), "ollama/gemma4:31b")
    assert text == "OK" and seconds >= 0
    assert seen["agent"] == "colony-ping" and seen["payload"]["model"] == "openclaw/colony-ping" and seen["model"] == "ollama/gemma4:31b"


def test_a_message_too_long_for_the_model_says_so_instead_of_blaming_the_model_name():
    exc = ProviderError("raw", status=400, provider_message="This model's maximum context length is 32768 tokens. However, you requested 40000")
    text = explain(exc, "ollama/gpt-oss:120b")
    assert "ยาวเกิน context" in text and "Ask another agent" in text and "ไม่รู้จัก" not in text


def test_ollama_connection_refused_explains_how_to_start_serve():
    exc = ProviderError("Ollama request failed: <urlopen error [Errno 61] Connection refused>")
    text = explain(exc, "ollama/nemotron-3-nano:30b")
    assert "ollama serve" in text
    assert "Settings" in text
    assert "Connection refused" in text


def test_ollama_404_explains_pull():
    exc = ProviderError("Ollama request failed: 404 not found", status=404)
    text = explain(exc, "ollama/nemotron-3-super")
    assert "ollama pull nemotron-3-super" in text

