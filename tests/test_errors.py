import pytest
from fastapi.testclient import TestClient

from colony.app import app
from colony.config import get_settings
from colony.core import chat
from colony.core.errors import explain
from colony.llm.http import ProviderError


@pytest.mark.parametrize("status,expected", [
    (429, "ถูกจำกัดจำนวนครั้ง"),
    (401, "API key"),
    (403, "API key"),
    (402, "เครดิต"),
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


def test_a_rate_limited_chat_shows_the_friendly_message_and_is_not_saved(monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "false")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    get_settings.cache_clear()

    def limited(**kw):
        raise ProviderError('OpenRouter request failed: 429 {"error":{"message":"Provider returned error"}}', status=429)

    monkeypatch.setattr(chat, "generate_openrouter_reply", limited)
    client = TestClient(app)
    body = client.post("/api/messages", json={"message": "hi", "role_id": "writing"}).json()
    assert "ถูกจำกัดจำนวนครั้ง" in body["reply"] and "Provider returned error" not in body["reply"]
    # the failed exchange isn't written to history, so re-asking doesn't double up
    assert client.get(f"/api/workspaces/{body['workspace_id']}/messages").json()["messages"] == []


def test_403_for_an_agent_only_free_model_is_explained_not_blamed_on_the_key():
    exc = ProviderError("raw", status=403, provider_message="thinkingmachines/inkling:free is only available on agentic harnesses. Try plugging it into a coding agent")
    text = explain(exc, "thinkingmachines/inkling:free")
    assert "coding agent" in text and "Test this model" in text
    assert "API key" not in text


def test_other_403s_pass_the_providers_own_words_along():
    text = explain(ProviderError("raw", status=403, provider_message="Model not enabled for your org"), "a/b")
    assert "Model not enabled for your org" in text


def test_provider_message_is_pulled_out_of_the_json_body(monkeypatch):
    import io
    import urllib.error

    from colony.llm import http

    body = '{"error":{"message":"inkling is only available on agentic harnesses","code":403}}'

    def fake(request, timeout, context):
        raise urllib.error.HTTPError("http://x", 403, "Forbidden", {}, io.BytesIO(body.encode()))

    monkeypatch.setattr(http.urllib.request, "urlopen", fake)
    with pytest.raises(ProviderError) as info:
        http.post_json("http://x", {}, {}, 5, "OpenRouter", retries=0)
    assert info.value.status == 403
    assert info.value.provider_message == "inkling is only available on agentic harnesses"


def test_test_model_endpoint_reports_success_and_failure(monkeypatch):
    from colony.api import agents as agents_api

    client = TestClient(app)
    # mock mode (the default in tests): always "works", no network
    assert client.post("/api/models/test", json={"model": "a/b"}).json()["ok"] is True

    monkeypatch.setenv("MOCK_MODE", "false")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    get_settings.cache_clear()
    monkeypatch.setattr(agents_api, "ping_model", lambda **kw: ("OK", 1.234))
    good = client.post("/api/models/test", json={"model": "qwen/x:free"}).json()
    assert good == {"ok": True, "seconds": 1.2, "preview": "OK"}

    def refuse(**kw):
        raise ProviderError("raw", status=403, provider_message="only available on agentic harnesses")

    monkeypatch.setattr(agents_api, "ping_model", refuse)
    bad = client.post("/api/models/test", json={"model": "thinkingmachines/inkling:free"}).json()
    assert bad["ok"] is False and "coding agent" in bad["message"]


def test_ping_sends_one_small_request_with_no_retries(monkeypatch):
    from colony.llm import providers

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    get_settings.cache_clear()
    seen = {}

    def fake(url, payload, headers, timeout, provider_name, retries=1):
        seen.update(payload=payload, retries=retries)
        return {"choices": [{"message": {"content": "OK"}}]}

    monkeypatch.setattr(providers, "post_json", fake)
    text, seconds = providers.ping_model(settings=get_settings(), model="z-ai/glm-5.2:free")
    assert text == "OK" and seconds >= 0
    assert seen["retries"] == 0 and seen["payload"]["max_tokens"] == 64 and seen["payload"]["model"] == "z-ai/glm-5.2:free"


def test_a_message_too_long_for_the_model_says_so_instead_of_blaming_the_model_name():
    exc = ProviderError("raw", status=400, provider_message="This model's maximum context length is 32768 tokens. However, you requested 40000")
    text = explain(exc, "z-ai/glm-5.2:free")
    assert "ยาวเกิน context" in text and "Ask another agent" in text and "ไม่รู้จัก" not in text
