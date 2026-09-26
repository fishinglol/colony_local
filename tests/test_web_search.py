"""Web search per agent: OpenRouter's web plugin for plain chat, the :online model for tool agents, sources under the reply."""
from fastapi.testclient import TestClient

from colony.app import app
from colony.config import get_settings
from colony.core import chat, context
from colony.engine.pi import PiResult
from colony.llm import providers

client = TestClient(app)


def live(monkeypatch, **role):
    monkeypatch.setenv("MOCK_MODE", "false")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    get_settings.cache_clear()
    monkeypatch.setattr(context, "get_json", lambda *a, **k: {"data": []})
    monkeypatch.setattr(chat.memory, "maybe_review_in_background", lambda *a: None)
    monkeypatch.setattr(chat.compaction, "maybe_compact_in_background", lambda *a: None)
    assert client.put("/api/roles", json={"roles": [{"id": "dev", "name": "Dev", "model": "acme/model", "when": "all", **role}]}).status_code == 200


def fake_openrouter(monkeypatch, annotations=None):
    sent = []
    message = {"content": "It rained.", **({"annotations": annotations} if annotations else {})}
    monkeypatch.setattr(providers, "post_json", lambda url, payload, *a, **k: (sent.append(payload) or
                        {"model": payload["model"], "choices": [{"message": message}]}))
    return sent


def cite(url, title):
    return {"type": "url_citation", "url_citation": {"url": url, "title": title, "content": "...", "start_index": 0, "end_index": 4}}


def test_an_agent_searches_the_web_only_when_its_switch_is_on(monkeypatch):
    sent = fake_openrouter(monkeypatch)
    live(monkeypatch)
    client.post("/api/messages", json={"message": "weather?", "role_id": "dev"})
    live(monkeypatch, web_search=True)
    client.post("/api/messages", json={"message": "weather?", "role_id": "dev"})
    assert "plugins" not in sent[0] and sent[1]["plugins"] == [{"id": "web", "max_results": 5}]


def test_the_pages_it_used_are_listed_under_the_reply_without_repeats(monkeypatch):
    fake_openrouter(monkeypatch, [cite("https://a.example/x", "Weather A"), cite("https://a.example/x", "Weather A again"),
                                  cite("https://b.example/y", "Weather B")])
    live(monkeypatch, web_search=True)
    reply = client.post("/api/messages", json={"message": "weather?", "role_id": "dev"}).json()["reply"]
    assert reply == ("It rained.\n\n**Sources**\n1. [Weather A](https://a.example/x)\n2. [Weather B](https://b.example/y)")


def test_no_citations_means_no_sources_block(monkeypatch):
    fake_openrouter(monkeypatch)
    live(monkeypatch, web_search=True)
    assert client.post("/api/messages", json={"message": "hi", "role_id": "dev"}).json()["reply"] == "It rained."


def test_a_tool_agent_searches_through_the_online_model(monkeypatch, tmp_path):
    live(monkeypatch, web_search=True, tools={"read": "allow"})
    (tmp_path / "p").mkdir()
    client.patch("/api/workspaces/local", json={"folder": str(tmp_path / "p")})
    monkeypatch.setattr(chat, "supports_tools", lambda model, settings: True)
    models = []
    monkeypatch.setattr(chat, "run_turn", lambda **kw: models.append(kw["model"]) or PiResult("done", []))
    client.post("/api/messages", json={"message": "look", "role_id": "dev"})
    live(monkeypatch, tools={"read": "allow"})
    client.post("/api/messages", json={"message": "look", "role_id": "dev"})
    assert models == ["acme/model:online", "acme/model"]
