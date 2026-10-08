"""Tests for OpenClaw Memory Architecture: Episodic Daily Notes, Flush, Dreaming, and Search."""
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from colony.app import app
from colony.config import Settings
from colony.core import local_tools
from colony.memory import (
    append_daily_observation,
    daily_note_path,
    dreams_md_path,
    flush_memory_before_compaction,
    learned_context,
    list_daily_notes,
    read_daily_note,
    run_dreaming_consolidation,
    search_daily_notes,
)

client = TestClient(app)


@pytest.fixture
def temp_workspace(tmp_path, monkeypatch):
    """Point Colony data_dir to a clean temporary directory."""
    monkeypatch.setenv("COLONY_DATA_DIR", str(tmp_path))
    from colony.config import get_settings
    get_settings.cache_clear()
    from colony.core.workspaces import list_workspaces
    return list_workspaces()[0].id


def test_episodic_daily_notes_append_and_read(temp_workspace):
    ws = temp_workspace
    append_daily_observation(ws, "User requested SQLite database migration", origin="Buddy")
    append_daily_observation(ws, "Wrote models.py with Ollama support", origin="Coder", tag="tool")

    content = read_daily_note(ws)
    assert "## Timeline" in content
    assert "User requested SQLite database migration" in content
    assert "Wrote models.py with Ollama support" in content
    assert "[tool]" in content

    notes = list_daily_notes(ws)
    assert len(notes) >= 1
    date_str, note_body = notes[0]
    assert "User requested SQLite database migration" in note_body


def test_search_daily_notes(temp_workspace):
    ws = temp_workspace
    append_daily_observation(ws, "Port configuration changed to 8767", origin="Coder")
    append_daily_observation(ws, "Created breakfast recipe in Thai", origin="Chef")

    hits = search_daily_notes(ws, "port configuration", top_k=2)
    assert len(hits) >= 1
    assert "Port configuration changed to 8767" in hits[0]["text"]


def test_pre_compaction_memory_flush(temp_workspace):
    ws = temp_workspace
    messages = [
        {"role": "user", "content": "I prefer TypeScript over plain JavaScript."},
        {"role": "assistant", "content": "Understood! I will use TypeScript."},
        {"role": "assistant", "content": "Tool action: wrote server.ts"},
    ]

    saved = flush_memory_before_compaction(ws, messages, Settings(mock_mode=True))
    assert saved >= 1

    daily_text = read_daily_note(ws)
    assert "[flush]" in daily_text
    assert "User preference: I prefer TypeScript" in daily_text


def test_dreaming_consolidation_and_dreams_log(temp_workspace):
    ws = temp_workspace
    # Seed episodic observations
    append_daily_observation(ws, "User preference: Always answer in English with code first", origin="Buddy")
    append_daily_observation(ws, "Project architecture uses OpenClaw 7 layers", origin="Coder")

    result = run_dreaming_consolidation(ws)
    assert result["status"] == "ok"
    assert result["total_promoted"] >= 1

    # Verify DREAMS.md audit log exists
    d_path = dreams_md_path(ws)
    assert d_path.exists()
    dreams_log = d_path.read_text(encoding="utf-8")
    assert "## [Dreaming Sweep" in dreams_log

    # Second run should be noop (deduplicated)
    result2 = run_dreaming_consolidation(ws)
    assert result2["status"] in ("noop", "skipped")


def test_learned_context_injects_episodic_matches(temp_workspace):
    ws = temp_workspace
    append_daily_observation(ws, "Secret password for test vault is 12345", origin="User")

    ctx = learned_context(ws, query="vault password")
    assert ctx is not None
    assert "Relevant episodic memory from daily notes:" in ctx
    assert "12345" in ctx


def test_memory_search_local_tool(tmp_path, temp_workspace):
    ws = temp_workspace
    append_daily_observation(ws, "Database uses WAL mode for concurrency", origin="Coder")

    out, action = local_tools.execute_local_tool(
        tool_name="memory_search",
        args={"query": "database WAL mode", "workspace_id": ws},
        folder=tmp_path,
        agent_name="Researcher",
    )
    assert "Episodic Daily Notes" in out
    assert "WAL mode" in out
    assert action is not None
    assert "searched memory" in action


def test_memory_api_endpoints(temp_workspace):
    ws = temp_workspace
    append_daily_observation(ws, "API test observation", origin="Test")

    # GET /api/memory/daily
    res_daily = client.get(f"/api/memory/daily?workspace_id={ws}")
    assert res_daily.status_code == 200
    assert len(res_daily.json()["notes"]) >= 1

    # POST /api/memory/dream
    res_dream = client.post(f"/api/memory/dream?workspace_id={ws}")
    assert res_dream.status_code == 200

    # GET /api/memory/dreams
    res_dreams = client.get(f"/api/memory/dreams?workspace_id={ws}")
    assert res_dreams.status_code == 200
    assert "Dreaming Sweep" in res_dreams.json()["dreams"]
