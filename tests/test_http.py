import io
import json
import urllib.error

import pytest

from colony.llm import http
from colony.llm.http import ProviderError, post_json


class FakeResponse(io.BytesIO):
    def __init__(self, body: dict):
        super().__init__(json.dumps(body).encode())


def http_error(code: int, body: str = "boom", headers: dict | None = None):
    return urllib.error.HTTPError("http://x", code, "err", headers or {}, io.BytesIO(body.encode()))


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(http, "_BACKOFFS", (0,))


def script(monkeypatch, *outcomes):
    """Make urlopen return/raise the given outcomes in order; returns the call counter."""
    calls = []

    def fake(request, timeout, context):
        calls.append(request)
        outcome = outcomes[len(calls) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return FakeResponse(outcome)

    monkeypatch.setattr(http.urllib.request, "urlopen", fake)
    return calls


def call(**kw):
    return post_json("http://x", {"a": 1}, {"Content-Type": "application/json"}, 5, "Test", **kw)


def test_retries_once_on_503_then_succeeds(monkeypatch):
    calls = script(monkeypatch, http_error(503), {"ok": True})
    assert call() == {"ok": True}
    assert len(calls) == 2


def test_does_not_retry_permanent_errors(monkeypatch):
    calls = script(monkeypatch, http_error(400, "bad request"))
    with pytest.raises(ProviderError, match="400 bad request"):
        call()
    assert len(calls) == 1


def test_provider_error_body_surfaces_the_providers_message(monkeypatch):
    script(monkeypatch, {"error": {"message": "No credits left", "code": 402}})
    with pytest.raises(ProviderError, match="No credits left"):
        call()


def test_transient_error_body_is_retried(monkeypatch):
    calls = script(monkeypatch, {"error": {"message": "Provider overloaded"}}, {"ok": 1})
    assert call() == {"ok": 1}
    assert len(calls) == 2


def test_retries_zero_means_a_single_call(monkeypatch):
    calls = script(monkeypatch, http_error(503), {"ok": True})
    with pytest.raises(ProviderError):
        call(retries=0)
    assert len(calls) == 1


def test_network_failure_becomes_provider_error(monkeypatch):
    script(monkeypatch, urllib.error.URLError("offline"), urllib.error.URLError("offline"))
    with pytest.raises(ProviderError, match="offline"):
        call()


def test_null_content_from_a_reasoning_model_is_not_a_crash():
    from colony.llm.providers import _extract_text
    assert _extract_text({"choices": [{"message": {"content": None}}]}, "OpenRouter") == ""


def sleeps(monkeypatch):
    recorded = []
    monkeypatch.setattr(http.time, "sleep", recorded.append)
    return recorded


def test_rate_limit_is_retried_several_times_with_growing_waits(monkeypatch):
    monkeypatch.setattr(http, "_BACKOFFS", (1.5, 4.0, 8.0))
    slept = sleeps(monkeypatch)
    calls = script(monkeypatch, http_error(429), http_error(429), http_error(429), {"ok": True})
    assert call(retries=3) == {"ok": True}
    assert len(calls) == 4
    assert slept == [1.5, 4.0, 8.0]


def test_still_rate_limited_after_all_retries_reports_status_429(monkeypatch):
    sleeps(monkeypatch)
    calls = script(monkeypatch, *[http_error(429, "slow down")] * 4)
    with pytest.raises(ProviderError) as info:
        call(retries=3)
    assert info.value.status == 429
    assert len(calls) == 4


def test_retry_after_header_is_honored_but_capped(monkeypatch):
    slept = sleeps(monkeypatch)
    script(monkeypatch, http_error(429, headers={"Retry-After": "3"}), {"ok": 1})
    call()
    script(monkeypatch, http_error(429, headers={"Retry-After": "999"}), {"ok": 1})
    call()
    script(monkeypatch, http_error(429, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}), {"ok": 1})
    call()
    assert slept == [3.0, http._MAX_RETRY_AFTER, 0]  # date-form falls back to the (patched) schedule


def test_status_is_recorded_for_http_and_body_errors(monkeypatch):
    sleeps(monkeypatch)
    script(monkeypatch, http_error(401, "no"))
    with pytest.raises(ProviderError) as a:
        call()
    script(monkeypatch, {"error": {"message": "Payment required", "code": 402}})
    with pytest.raises(ProviderError) as b:
        call()
    script(monkeypatch, urllib.error.URLError("offline"), urllib.error.URLError("offline"))
    with pytest.raises(ProviderError) as c:
        call()
    assert (a.value.status, b.value.status, c.value.status) == (401, 402, None)


def test_chat_replies_retry_as_many_times_as_the_setting_says(monkeypatch):
    from colony.config import get_settings
    from colony.llm import providers

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    monkeypatch.setenv("CHAT_RETRIES", "5")
    get_settings.cache_clear()
    seen = {}

    def fake(url, payload, headers, timeout, provider_name, retries=1):
        seen["retries"] = retries
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(providers, "post_json", fake)
    providers.generate_openrouter_reply(settings=get_settings(), message="hi", model_hint="a/b")
    assert seen["retries"] == 5


def test_get_json_returns_the_object_and_reports_failures(monkeypatch):
    script(monkeypatch, {"data": [1]})
    assert http.get_json("http://x", 5, "Test") == {"data": [1]}
    script(monkeypatch, http_error(500, "down"))
    with pytest.raises(ProviderError) as info:
        http.get_json("http://x", 5, "Test")
    assert info.value.status == 500
