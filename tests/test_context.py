import pytest
from fastapi.testclient import TestClient

from colony.app import app
from colony.config import get_settings
from colony.core import chat, context
from colony.core.agents import Role
from colony.llm import http, providers
from colony.llm.http import ProviderError

client = TestClient(app)


@pytest.fixture(autouse=True)
def fresh_live_cache(monkeypatch):
    monkeypatch.setattr(context, "_live_windows", {})
    monkeypatch.setattr(context, "_live_info", {})
    monkeypatch.setattr(context, "_live_fetched_at", 0.0)


def role(model="z-ai/glm-5.2:free", name="Coder"):
    return Role(id=name.lower(), name=name, model=model, when="x", instructions="")


def msg(kind, text, name=None):
    m = {"role": kind, "content": text}
    if name:
        m["metadata"] = {"role_name": name}
    return m


def live(monkeypatch, sent):
    """Non-mock mode with a fake provider that records the messages each model receives."""
    monkeypatch.setenv("MOCK_MODE", "false")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    get_settings.cache_clear()
    monkeypatch.setattr(chat.memory, "maybe_review_in_background", lambda *a: None)

    def fake(url, payload, headers, timeout, provider_name, retries=1):
        sent.append(payload["messages"])
        return {"model": payload["model"], "choices": [{"message": {"content": f"answer {len(sent)}"}}]}

    monkeypatch.setattr(providers, "post_json", fake)


# ── token estimates ───────────────────────────────────────────────────────────
def test_estimates_are_roughly_right_for_english_and_denser_for_thai():
    assert context.estimate_tokens("") == 0
    assert context.estimate_tokens("a" * 400) == 100
    assert context.estimate_tokens("ก" * 300) == 200  # Thai counts ~1.5 chars/token


# ── who said what ─────────────────────────────────────────────────────────────
def test_later_agents_see_earlier_replies_labelled_with_the_speaker(monkeypatch):
    sent = []
    live(monkeypatch, sent)
    first = client.post("/api/messages", json={"message": "We sell kites.", "role_id": "reasoning"}).json()
    client.post("/api/messages", json={"message": "Write a slogan.", "role_id": "writing"})

    def texts(messages, kind):
        return [m["content"] for m in messages if m["role"] == kind]

    assert not any("teammates" in t for t in texts(sent[0], "system"))       # nobody else has spoken yet
    assert "[Thinker] answer 1" in texts(sent[1], "assistant")                 # the writer sees who said it
    assert any("[brackets]" in t for t in texts(sent[1], "system"))            # ...and is told about teammates


def test_a_reply_that_copies_the_label_style_has_it_removed():
    assert context.strip_self_label("[Coder] here you go", "Coder") == "here you go"
    assert context.strip_self_label("  [Coder]   hi", "Coder") == "hi"
    assert context.strip_self_label("[Writer] not mine", "Coder") == "[Writer] not mine"
    assert context.strip_self_label("plain", "Coder") == "plain"


def test_old_messages_without_a_speaker_are_left_as_they_were():
    plan = context.plan_history(
        model="qwen/qwen3.8-27b:free", role=role(), settings=get_settings(), memory_context=None,
        messages=[msg("user", "hi"), msg("assistant", "hello")],
    )
    assert [m["content"] for m in plan.history] == ["hi", "hello"] and plan.attributed is False


# ── small windows ─────────────────────────────────────────────────────────────
def test_a_small_context_window_drops_the_oldest_messages_first(monkeypatch):
    monkeypatch.setenv("MAX_OUTPUT_TOKENS", "100")
    get_settings.cache_clear()
    monkeypatch.setattr(context, "context_window", lambda model, settings: 1500)
    messages = [msg("user" if i % 2 == 0 else "assistant", f"m{i:02d} " + "x" * 396) for i in range(12)]  # ~100 tokens each
    plan = context.plan_history(model="a/b", role=role(), settings=get_settings(), memory_context=None, messages=messages)
    assert 0 < plan.sent < plan.total == 12
    assert plan.history[-1]["content"].startswith("m11") and not any(m["content"].startswith("m00") for m in plan.history)
    assert plan.tokens <= int(1500 * context.FILL_LIMIT) - 100


def test_a_big_window_keeps_everything_up_to_the_history_limit(monkeypatch):
    monkeypatch.setattr(context, "context_window", lambda model, settings: 1_000_000)
    messages = [msg("user", f"hello {i}") for i in range(80)]
    plan = context.plan_history(model="a/b", role=role(), settings=get_settings(), memory_context=None, messages=messages)
    assert plan.sent == get_settings().history_max_messages == 60 and plan.total == 80


# ── finding a model's window ──────────────────────────────────────────────────
def test_pool_models_use_the_built_in_table_without_any_network(monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "false")
    get_settings.cache_clear()
    monkeypatch.setattr(context, "get_json", lambda *a, **k: pytest.fail("network used"))
    assert context.context_window("z-ai/glm-5.2:free", get_settings()) == 32_768


def test_unknown_models_are_looked_up_once_in_openrouters_catalog(monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "false")
    get_settings.cache_clear()
    calls = []

    def fake_catalog(url, timeout, provider_name, headers=None):
        calls.append(url)
        return {"data": [{"id": "lab/new-model", "context_length": 50_000}, {"id": "bad"}]}

    monkeypatch.setattr(context, "get_json", fake_catalog)
    assert context.context_window("lab/new-model", get_settings()) == 50_000
    assert context.context_window("lab/new-model", get_settings()) == 50_000
    assert context.context_window("lab/other", get_settings()) is None
    assert len(calls) == 1


def test_a_failed_catalog_lookup_gives_unknown_and_is_not_retried_every_time(monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "false")
    get_settings.cache_clear()
    calls = []

    def down(url, timeout, provider_name, headers=None):
        calls.append(1)
        raise ProviderError("offline")

    monkeypatch.setattr(context, "get_json", down)
    assert context.context_window("lab/x", get_settings()) is None
    assert context.context_window("lab/x", get_settings()) is None
    assert len(calls) == 1


# ── the gauge endpoint ────────────────────────────────────────────────────────
def test_context_endpoint_reports_each_agent_and_grows_with_the_chat():
    empty = {a["role_id"]: a for a in client.get("/api/context").json()["agents"]}
    assert set(empty) == {"reasoning", "chitchat", "writing", "coding"}
    assert empty["coding"]["window"] == 32_768 and empty["coding"]["messages_total"] == 0

    conv = client.post("/api/messages", json={"message": "hello " * 200, "role_id": "coding"}).json()["workspace_id"]
    client.post("/api/messages", json={"message": "and more " * 200, "role_id": "coding"})
    later = {a["role_id"]: a for a in client.get(f"/api/context?workspace_id={conv}").json()["agents"]}
    assert later["coding"]["messages_total"] == 4 and later["coding"]["messages_sent"] == 4
    assert later["coding"]["used_tokens"] > empty["coding"]["used_tokens"]
    assert later["coding"]["percent"] > empty["coding"]["percent"]
    # same chat, but the 32k agent is a bigger fraction of its window than the 1M one
    assert later["coding"]["percent"] > later["chitchat"]["percent"]


def test_an_agent_on_a_model_with_no_known_window_shows_tokens_but_no_percent():
    client.put("/api/roles", json={"roles": [{"id": "x", "name": "X", "model": "lab/mystery", "when": "any", "instructions": ""}]})
    row = client.get("/api/context").json()["agents"][0]
    assert row["window"] is None and row["percent"] is None and row["used_tokens"] > 0


def test_a_long_pasted_update_is_accepted_and_counts_toward_the_gauge():
    long_update = "Status update: shipped the kite landing page. " * 1000  # ~46k characters
    r = client.post("/api/messages", json={"message": long_update, "role_id": "coding"})
    assert r.status_code == 200
    conv = r.json()["workspace_id"]
    row = next(a for a in client.get(f"/api/context?workspace_id={conv}").json()["agents"] if a["role_id"] == "coding")
    assert row["used_tokens"] > 10_000 and row["percent"] > 30  # a big share of the 32k window
