from fastapi.testclient import TestClient

from colony.app import app
from colony.config import get_settings
from colony.core import context
from colony.engine import openclaw

client = TestClient(app)


def msg(kind, text, name=None, mid=None):
    m = {"role": kind, "content": text, "id": mid or text}
    if name:
        m["metadata"] = {"role_name": name}
    return m


# ── who said what ─────────────────────────────────────────────────────────────
def test_later_agents_see_earlier_replies_labelled_with_the_speaker(monkeypatch):
    sent = []
    monkeypatch.setenv("MOCK_MODE", "false")
    get_settings.cache_clear()
    monkeypatch.setattr(openclaw, "is_openclaw_available", lambda s=None: True)
    monkeypatch.setattr(openclaw, "mark_seen", lambda *a: None)

    def fake_turn(**kw):
        sent.append(kw["history"])
        return openclaw.OpenClawTurnResult(reply=f"answer {len(sent)}", model=kw["role_model"], session_user="ome-t")

    monkeypatch.setattr(openclaw, "run_openclaw_turn", fake_turn)
    client.post("/api/messages", json={"message": "We sell kites.", "role_id": "reasoning"})
    client.post("/api/messages", json={"message": "Write a slogan.", "role_id": "writing"})
    assert sent[0] == []                                                                # nobody has spoken yet
    assert {"role": "assistant", "content": "[Thinker] answer 1"} in sent[1]           # the writer sees who said it


def test_a_reply_that_copies_the_label_style_has_it_removed():
    assert context.strip_self_label("[Coder] here you go", "Coder") == "here you go"
    assert context.strip_self_label("  [Coder]   hi", "Coder") == "hi"
    assert context.strip_self_label("[Writer] not mine", "Coder") == "[Writer] not mine"
    assert context.strip_self_label("plain", "Coder") == "plain"


def test_history_keeps_the_newest_messages_up_to_the_limit_and_their_ids():
    messages = [msg("user", f"hello {i}") for i in range(80)] + [{"role": "assistant", "content": "", "id": "empty"}]
    history, ids = context.labelled_history(get_settings(), "local", messages)
    assert len(history) == len(ids) == get_settings().history_max_messages == 60
    assert history[-1]["content"] == "hello 79" and ids[-1] == "hello 79"


# ── windows ───────────────────────────────────────────────────────────────────
def test_windows_come_from_the_ollama_table_else_the_default():
    s = get_settings()
    assert context.context_window("ollama/gemma4:31b", s) == 262_144
    assert context.context_window("ollama/never-heard-of-it", s) == s.ollama_context_window
    assert context.supports_tools("ollama/gemma4:31b") and context.supports_tools("ollama/x")


# ── the gauge endpoint ────────────────────────────────────────────────────────
def test_context_endpoint_shows_the_prompt_size_openclaw_reported(monkeypatch):
    empty = {a["role_id"]: a for a in client.get("/api/context").json()["agents"]}
    assert set(empty) == {"reasoning", "chitchat", "writing", "coding"}
    assert empty["coding"]["used_tokens"] is None and empty["coding"]["percent"] is None      # no turn yet
    assert empty["coding"]["window"] == 262_144 and empty["coding"]["messages_total"] == 0

    settings = get_settings()
    openclaw._record_usage(settings, openclaw.agent_id_for("local", "coding"), "ollama/gpt-oss:120b", 26_214)
    row = next(a for a in client.get("/api/context").json()["agents"] if a["role_id"] == "coding")
    assert row["used_tokens"] == 26_214 and row["percent"] == 10.0
    assert openclaw.last_prompt_tokens(settings, "nobody") is None


def test_models_without_a_table_entry_use_the_default_window():
    client.put("/api/roles", json={"roles": [{"id": "x", "name": "X", "model": "ollama/mystery:1b", "when": "any", "instructions": ""}]})
    row = client.get("/api/context").json()["agents"][0]
    assert row["window"] == get_settings().ollama_context_window and row["percent"] is None


def test_slash_commands_and_their_replies_are_not_part_of_the_team_conversation():
    from colony.core.context import drop_commands
    chat = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"},
            {"role": "user", "content": "/status"}, {"role": "assistant", "content": "🦞 OpenClaw 2026"},
            {"role": "user", "content": "what is 2+2?"}, {"role": "assistant", "content": "4"}]
    assert [m["content"] for m in drop_commands(chat)] == ["hi", "hello", "what is 2+2?", "4"]
