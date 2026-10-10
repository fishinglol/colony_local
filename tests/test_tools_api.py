"""Agents with tools: the chat path, the approval questions, workspace setting, and the model tool-support lock."""

from fastapi.testclient import TestClient

from colony.app import app
from colony.config import get_settings
from colony.core import chat

client = TestClient(app)

TOOLS_ON = {"read": "allow", "write": "ask", "bash": "off"}
CODER = {"id": "coder", "name": "Coder", "model": "acme/coder", "when": "code", "instructions": "Be short.", "tools": TOOLS_ON}
BUDDY = {"id": "buddy", "name": "Buddy", "model": "acme/buddy", "when": "chat", "instructions": ""}


def live(monkeypatch, tmp_path, workspace=True):
    """Not mock mode, with a key, a workspace folder, and a model catalog that says every model can use tools."""
    monkeypatch.setenv("MOCK_MODE", "false")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    get_settings.cache_clear()
    monkeypatch.setattr(chat, "supports_tools", lambda model, settings: True)
    monkeypatch.setattr(chat.memory, "maybe_review_in_background", lambda *a: None)
    client.put("/api/roles", json={"roles": [CODER, BUDDY]})
    if workspace:
        (tmp_path / "project").mkdir(exist_ok=True)
        assert client.patch("/api/workspaces/local", json={"folder": str(tmp_path / "project")}).status_code == 200
    else:
        client.patch("/api/workspaces/local", json={"folder": ""})


def test_no_answer_in_time_means_no(monkeypatch, tmp_path):
    from colony.core.approvals import approvals
    assert approvals.ask(agent="Coder", tool="bash", title="bash", message="rm -rf", timeout=0.05) is False


def test_editor_cannot_save_tools_on_a_model_that_has_none(monkeypatch):
    from colony.api import agents
    monkeypatch.setattr(agents, "supports_tools", lambda model: model != "acme/coder")
    res = client.put("/api/roles", json={"roles": [CODER, BUDDY]})
    assert res.status_code == 400 and "can't use tools" in res.json()["detail"] and "Coder" in res.json()["detail"]
    assert client.put("/api/roles", json={"roles": [{**CODER, "tools": {}}, BUDDY]}).status_code == 200  # tools off: fine


def test_model_tool_support_comes_from_the_ollama_table():
    ask = lambda m: client.get("/api/models/tools", params={"model": m}).json()["supported"]  # noqa: E731
    assert ask("ollama/gemma4:31b") is True and ask("ollama/not-in-the-table") is True      # unknown: don't lock it
