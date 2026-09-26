"""Reasoning level per agent: chosen from what the model supports, sent to OpenRouter (and to Pi for tool agents)."""
from fastapi.testclient import TestClient

from colony.app import app
from colony.config import get_settings
from colony.core import chat, context
from colony.engine.pi import PiResult
from colony.llm import providers

client = TestClient(app)

CATALOG = {"data": [
    {"id": "acme/thinker", "name": "Acme: Thinker", "context_length": 100_000, "supported_parameters": ["tools", "reasoning"],
     "reasoning": {"mandatory": False, "default_effort": "medium", "supported_efforts": ["max", "high", "medium", "low", "none"]}},
    {"id": "acme/always-on", "name": "Acme: Always On", "context_length": 100_000, "supported_parameters": ["tools", "reasoning"],
     "reasoning": {"mandatory": True, "default_effort": "high", "supported_efforts": ["high", "low"]}},
    {"id": "acme/plain", "name": "Acme: Plain", "context_length": 8000, "supported_parameters": ["tools"]},
]}


def catalog(monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "false")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    get_settings.cache_clear()
    for name, empty in (("_live_windows", {}), ("_live_tools", {}), ("_live_info", {}), ("_live_fetched_at", 0.0)):
        monkeypatch.setattr(context, name, empty)
    monkeypatch.setattr(context, "get_json", lambda *a, **k: CATALOG)
    monkeypatch.setattr(chat.memory, "maybe_review_in_background", lambda *a: None)


def team(model, reasoning, tools=None):
    return [{"id": "dev", "name": "Dev", "model": model, "when": "all", "instructions": "", "reasoning": reasoning, **({"tools": tools} if tools else {})}]


def test_an_agent_has_one_reasoning_level_and_unknown_levels_are_refused():
    assert client.get("/api/roles").json()["roles"][0]["reasoning"] == "default"
    assert client.put("/api/roles", json={"roles": team("acme/x", "high")}).json()["roles"][0]["reasoning"] == "high"
    assert client.put("/api/roles", json={"roles": team("acme/x", "turbo")}).status_code == 422


def test_levels_per_model_come_from_the_catalog_lowest_to_highest(monkeypatch):
    catalog(monkeypatch)
    models = {m["id"]: m["capabilities"]["reasoning_levels"] for m in client.get("/api/models").json()["models"]}
    assert models["acme/thinker"] == {"efforts": ["low", "medium", "high", "max"], "default": "medium", "can_turn_off": True}
    assert models["acme/always-on"] == {"efforts": ["low", "high"], "default": "high", "can_turn_off": False}
    assert models["acme/plain"] is None


def test_only_levels_the_model_supports_are_sent(monkeypatch):
    catalog(monkeypatch)
    settings = get_settings()
    send = lambda model, level: context.reasoning_param(model, level, settings)  # noqa: E731
    assert send("acme/thinker", "default") is None                                  # the model's own choice: send nothing
    assert send("acme/thinker", "high") == {"effort": "high"}
    assert send("acme/thinker", "off") == {"effort": "none"}
    assert send("acme/always-on", "low") == {"effort": "low"}
    assert send("acme/always-on", "off") is None and send("acme/always-on", "medium") is None      # can't: left out, not an error
    assert send("acme/plain", "high") is None                                       # the catalog says it can't reason at all
    assert send("not/in-catalog", "low") == {"effort": "low"}                       # unknown model: trust the user


def test_plain_chat_sends_the_chosen_level_and_default_sends_nothing(monkeypatch):
    catalog(monkeypatch)
    sent = []
    monkeypatch.setattr(providers, "post_json", lambda url, payload, *a, **k: (sent.append(payload) or
                        {"model": payload["model"], "choices": [{"message": {"content": "ok"}}]}))
    for level in ("default", "low", "off"):
        client.put("/api/roles", json={"roles": team("acme/thinker", level)})
        client.post("/api/messages", json={"message": "hi", "role_id": "dev"})
    assert [p.get("reasoning") for p in sent] == [None, {"effort": "low"}, {"effort": "none"}]


def test_the_old_built_in_medium_is_gone(monkeypatch):
    catalog(monkeypatch)
    sent = []
    monkeypatch.setattr(providers, "post_json", lambda url, payload, *a, **k: (sent.append(payload) or
                        {"model": payload["model"], "choices": [{"message": {"content": "ok"}}]}))
    client.put("/api/roles", json={"roles": team("openai/gpt-6-sol", "default")})    # used to get effort "medium" from a built-in flag
    client.post("/api/messages", json={"message": "hi", "role_id": "dev"})
    assert "reasoning" not in sent[0]


def test_tool_agents_hand_the_level_to_pi(monkeypatch, tmp_path):
    catalog(monkeypatch)
    (tmp_path / "project").mkdir()
    client.patch("/api/workspaces/local", json={"folder": str(tmp_path / "project")})
    monkeypatch.setattr(chat, "supports_tools", lambda model, settings: True)
    seen = []
    monkeypatch.setattr(chat, "run_turn", lambda **kw: seen.append(kw["thinking"]) or PiResult("done", []))
    for level in ("default", "high", "off"):
        client.put("/api/roles", json={"roles": team("acme/thinker", level, {"read": "allow"})})
        client.post("/api/messages", json={"message": "look", "role_id": "dev"})
    assert seen == [None, "high", "off"]


def test_test_this_model_uses_the_level_being_set(monkeypatch):
    from colony.api import agents

    catalog(monkeypatch)
    used = []
    monkeypatch.setattr(agents, "ping_model", lambda **kw: used.append(kw["reasoning"]) or ("OK", 0.1))
    for level in ("default", "low"):
        assert client.post("/api/models/test", json={"model": "acme/thinker", "reasoning": level}).json()["ok"] is True
    assert used == [None, {"effort": "low"}]
