import io
import json
import urllib.error

import pytest

from colony.core import decider
from colony.llm import http
from colony.config import get_settings
from colony.core.agents import DEFAULT_ROLES, Role

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


def test_jev_api_decides_first_and_laya_is_the_fallback(monkeypatch):
    monkeypatch.setenv("JEV_API_KEY", "test-key")
    monkeypatch.setenv("LAYA_URL", "http://127.0.0.1:8790")
    get_settings.cache_clear()
    urls = []

    def fake_urlopen(req, timeout, context):
        urls.append(req.full_url)
        if "beatapi" in req.full_url:
            assert req.get_header("Authorization") == "Bearer test-key"
            assert json.loads(req.data)["model"] == "jev-1.13-free"
            raise urllib.error.URLError("down")      # the API is unreachable → Laya answers
        return io.BytesIO(json.dumps(DOC_RESPONSE).encode())

    monkeypatch.setattr(http.urllib.request, "urlopen", fake_urlopen)
    result = decider.decide("hi", list(DEFAULT_ROLES), get_settings())
    assert urls == ["https://api.beatapi.io/v1/systemone", "http://127.0.0.1:8790/v1/systemone"]
    assert result.source == "laya" and result.role.id == "writing"

    monkeypatch.setattr(http.urllib.request, "urlopen", lambda req, timeout, context: io.BytesIO(json.dumps(DOC_RESPONSE).encode()))
    assert decider.decide("hi", list(DEFAULT_ROLES), get_settings()).source == "jev"


def test_rate_limited_jev_falls_through_to_nemotron(monkeypatch):
    monkeypatch.setenv("JEV_API_KEY", "test-key")
    get_settings.cache_clear()
    monkeypatch.setattr(http.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(urllib.error.URLError("429")))
    monkeypatch.setattr(decider, "decide_via_ollama", lambda m, roles, s, when=None: ("writing", 0.8))
    result = decider.decide("hi", list(DEFAULT_ROLES), get_settings())
    assert (result.role.id, result.source) == ("writing", "nemotron")


def test_the_decider_is_told_what_each_agents_skills_do(monkeypatch):
    from colony.core import decider
    seen = {}
    monkeypatch.setenv("JEV_API_KEY", "k")
    get_settings.cache_clear()
    monkeypatch.setattr(decider, "post_json", lambda url, payload, *a, **k: seen.update(payload) or {"answers": {"role": {"choice": "b", "confidence": 1}}})
    roles = [Role(id="a", name="A", model="ollama/x", when="chat"), Role(id="b", name="B", model="ollama/x", when="write")]
    res = decider.decide("hi", roles, get_settings(), skills={"b": "slides (makes decks)"})
    assert res.role.id == "b"
    assert seen["questions"]["role"]["criteria"] == {"a": "chat", "b": "write Its skills: slides (makes decks)"}


def test_an_at_mention_picks_the_role_without_the_decider(monkeypatch):
    monkeypatch.setattr(http.urllib.request, "urlopen", lambda *a, **k: pytest.fail("decider called"))
    roles = list(DEFAULT_ROLES)
    first, second = roles[0], roles[1]
    got = decider.decide(f"hey @{second.name.upper()} please help", roles, get_settings())
    assert (got.role.id, got.source) == (second.id, "mention")
    assert decider.mentioned_role(f"mail me@{first.name}x.com", roles) is None     # not a whole word
    assert decider.mentioned_role("no mention here", roles) is None
