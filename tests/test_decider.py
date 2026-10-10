import io
import json
import urllib.error

import pytest

from colony.core import decider
from colony.llm import http
from colony.config import get_settings
from colony.core.agents import DEFAULT_ROLES

# Response shape copied from https://openrouter.ai/docs/guides/community/jev-tutorial
DOC_RESPONSE = {
    "id": "gen-dec-1",
    "model": "typesafe/jev-1.13-20260917",
    "provider": "TypeSafe",
    "answers": {"role": {"type": "choice", "choice": "writing", "confidence": 0.67,
                         "probabilities": {"reasoning": 0.1, "chitchat": 0.2, "writing": 0.7}}},
    "usage": {"input_tokens": 476, "output_tokens": 70, "cost": 0.00002},
}
IDS = [r.id for r in DEFAULT_ROLES]


def test_parse_documented_response():
    assert decider.parse_jev_answer(DOC_RESPONSE, IDS) == ("writing", 0.67)


def test_parse_rejects_unknown_choice():
    bad = {"answers": {"role": {"choice": "sales"}}}
    with pytest.raises(ValueError):
        decider.parse_jev_answer(bad, IDS)


def _laya(monkeypatch):
    monkeypatch.setenv("LAYA_URL", "http://127.0.0.1:8790")
    get_settings.cache_clear()
    return get_settings()


def test_direct_role_and_single_role_skip_the_decider(monkeypatch):
    settings = _laya(monkeypatch)
    monkeypatch.setattr(http.urllib.request, "urlopen", lambda *a, **k: pytest.fail("decider called"))
    writer = DEFAULT_ROLES[2]
    assert decider.decide("x", list(DEFAULT_ROLES), settings, direct_role=writer).source == "direct"
    assert decider.decide("x", [writer], settings).source == "only_role"


def test_laya_decides_without_any_key(monkeypatch):
    monkeypatch.setenv("LAYA_URL", "http://127.0.0.1:8790")
    get_settings.cache_clear()
    sent = {}

    def fake_urlopen(req, timeout, context):
        sent.update(url=req.full_url, auth=req.get_header("Authorization"), body=json.loads(req.data))
        return io.BytesIO(json.dumps(DOC_RESPONSE).encode())

    monkeypatch.setattr(http.urllib.request, "urlopen", fake_urlopen)
    result = decider.decide("ช่วยเขียนอีเมล", list(DEFAULT_ROLES), get_settings())
    assert sent["url"] == "http://127.0.0.1:8790/v1/systemone" and sent["auth"] is None
    assert sent["body"]["model"] == "multilingual"
    assert sent["body"]["questions"]["role"]["criteria"] == {r.id: r.when for r in DEFAULT_ROLES}
    assert (result.role.id, result.source, result.confidence) == ("writing", "laya", 0.67)


def test_laya_being_down_is_a_visible_fallback(monkeypatch):
    monkeypatch.setenv("LAYA_URL", "http://127.0.0.1:8790")
    get_settings.cache_clear()
    monkeypatch.setattr(http.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(urllib.error.URLError("refused")))
    assert decider.decide("hi", list(DEFAULT_ROLES), get_settings()).source == "fallback"
