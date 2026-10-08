"""Tests for Colony Local SQLite Session & History Layer."""
from pathlib import Path
import sqlite3
import pytest

from colony.config import Settings
from colony.store import sqlite_history, history


@pytest.fixture
def temp_data_dir(tmp_path, monkeypatch):
    """Point Colony data_dir to a clean temporary directory."""
    monkeypatch.setenv("COLONY_DATA_DIR", str(tmp_path))
    from colony.config import get_settings
    get_settings.cache_clear()
    return tmp_path


def test_sqlite_init_db_creates_tables(temp_data_dir):
    sqlite_history.init_db()
    db_path = temp_data_dir / "colony.sqlite"
    assert db_path.exists()

    with sqlite_history.get_connection() as conn:
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        table_names = {r["name"] for r in tables}
        assert "conversations" in table_names
        assert "messages" in table_names


def test_append_exchange_sqlite_inserts_conversation_and_messages(temp_data_dir):
    conv_id = "conv_test_1"
    user_msg = "Hello, what models are available?"
    assistant_resp = {
        "reply": "You have Nemotron, Gemma, and GPT-OSS models ready.",
        "role_id": "chitchat",
        "role_name": "Buddy",
        "model": "nemotron-3-nano:30b",
        "decided_by": "ollama",
        "confidence": 0.95,
    }

    u_id, a_id = sqlite_history.append_exchange_sqlite(
        conversation_id=conv_id,
        user_message=user_msg,
        assistant_response=assistant_resp,
        channel="mix",
    )

    assert u_id.startswith("msg_")
    assert a_id.startswith("msg_")

    messages = sqlite_history.list_messages_sqlite(conv_id)
    assert len(messages) == 2

    # Verify user message
    assert messages[0]["id"] == u_id
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == user_msg
    assert messages[0]["channel"] == "mix"

    # Verify assistant message
    assert messages[1]["id"] == a_id
    assert messages[1]["role"] == "assistant"
    assert messages[1]["content"] == assistant_resp["reply"]
    assert messages[1]["role_id"] == "chitchat"
    assert messages[1]["role_name"] == "Buddy"
    assert messages[1]["model"] == "nemotron-3-nano:30b"
    assert messages[1]["decided_by"] == "ollama"
    assert messages[1]["confidence"] == 0.95


def test_append_multiple_exchanges_maintains_order(temp_data_dir):
    conv_id = "conv_test_ordering"

    for i in range(3):
        sqlite_history.append_exchange_sqlite(
            conversation_id=conv_id,
            user_message=f"Question {i}",
            assistant_response={"reply": f"Answer {i}"},
        )

    messages = sqlite_history.list_messages_sqlite(conv_id)
    assert len(messages) == 6
    assert [m["content"] for m in messages] == [
        "Question 0", "Answer 0",
        "Question 1", "Answer 1",
        "Question 2", "Answer 2",
    ]


def test_history_dual_write_integrates_sqlite(temp_data_dir):
    conv_id = "conv_dual_write"
    u_id, a_id = history.append_exchange(
        conversation_id=conv_id,
        user_message="Dual write test",
        assistant_response={"reply": "Saved to JSON and SQLite"},
    )

    # Verify JSON store has it
    recent_json = history.get_recent_messages(conv_id)
    assert len(recent_json) == 2
    assert recent_json[0]["content"] == "Dual write test"

    # Verify SQLite store has it
    sqlite_msgs = sqlite_history.list_messages_sqlite(conv_id)
    assert len(sqlite_msgs) == 2
    assert sqlite_msgs[0]["content"] == "Dual write test"
    assert sqlite_msgs[1]["content"] == "Saved to JSON and SQLite"
