"""Agents with tools: the chat path, the approval questions, workspace setting, and the model tool-support lock."""
import threading
import time

from fastapi.testclient import TestClient

from colony.app import app
from colony.config import get_settings
from colony.core import chat, context
from colony.core.agents import ToolAccess
from colony.engine.pi import PiResult

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


def test_tool_access_translates_to_pi_tools_and_rules():
    access = ToolAccess(read="allow", write="ask", bash="off")
    assert access.pi_tools() == ["read", "grep", "find", "ls", "write", "edit"]
    assert access.policy() == {"write": "ask", "edit": "ask", "bash": "off"}
    assert not ToolAccess().any_on and ToolAccess(bash="ask").any_on


def test_agent_with_tools_runs_through_pi_and_its_actions_are_shown_and_kept(monkeypatch, tmp_path):
    live(monkeypatch, tmp_path)
    seen = {}

    def fake_run(**kw):
        seen.update(kw)
        return PiResult("Done, I made the file.", ["wrote notes.txt", "read plan.md"])

    monkeypatch.setattr(chat, "run_turn", fake_run)
    monkeypatch.setattr(chat, "generate_openrouter_reply", lambda **kw: (_ for _ in ()).throw(AssertionError("plain chat used")))
    first = client.post("/api/messages", json={"message": "make notes.txt", "role_id": "coder"}).json()
    assert first["reply"] == "Done, I made the file.\n\n🛠 wrote notes.txt · read plan.md"
    assert seen["model"] == "acme/coder" and seen["tools"].write == "ask" and seen["workspace"] == (tmp_path / "project").resolve()
    assert "Be short." in seen["system_prompt"] and "workspace folder" in seen["system_prompt"]
    assert seen["prompt"] == "make notes.txt"

    # the next agent (no tools, plain chat) sees what happened to the files, labelled with who did it
    sent = {}
    monkeypatch.setattr(chat, "generate_openrouter_reply", lambda **kw: sent.update(kw) or type("R", (), {"text": "ok", "model": "acme/buddy"})())
    client.post("/api/messages", json={"message": "what changed?", "role_id": "buddy"})
    assert "[Coder] Done, I made the file." in sent["history"][1]["content"] and "wrote notes.txt" in sent["history"][1]["content"]

    # and a tools agent later gets the shared conversation as its prompt
    client.post("/api/messages", json={"message": "now add tests", "role_id": "coder"})
    assert seen["prompt"].startswith("Conversation so far:") and "[Coder] Done" in seen["prompt"] and seen["prompt"].endswith("now add tests")


def test_agent_without_tools_never_touches_the_engine(monkeypatch, tmp_path):
    live(monkeypatch, tmp_path)
    monkeypatch.setattr(chat, "run_turn", lambda **kw: (_ for _ in ()).throw(AssertionError("engine used")))
    monkeypatch.setattr(chat, "generate_openrouter_reply", lambda **kw: type("R", (), {"text": "hi", "model": "acme/buddy"})())
    assert client.post("/api/messages", json={"message": "hey", "role_id": "buddy"}).json()["reply"] == "hi"


def test_tools_agent_without_a_folder_chats_without_starting_pi(monkeypatch, tmp_path):
    live(monkeypatch, tmp_path, workspace=False)
    (tmp_path / "launch-folder").mkdir()
    monkeypatch.setenv("COLONY_LAUNCH_DIR", str(tmp_path / "launch-folder"))
    monkeypatch.setattr(chat, "run_turn", lambda **kw: (_ for _ in ()).throw(AssertionError("engine used")))
    sent = {}
    monkeypatch.setattr(chat, "generate_openrouter_reply", lambda **kw: sent.update(kw) or type("R", (), {"text": "I can help with that.", "model": "acme/coder"})())
    assert client.post("/api/messages", json={"message": "x", "role_id": "coder"}).json()["reply"] == "I can help with that."
    assert "chat only" in sent["role_instructions"]

    live(monkeypatch, tmp_path)
    monkeypatch.setattr(chat, "supports_tools", lambda model, settings: False)
    assert "ใช้เครื่องมือไม่ได้" in client.post("/api/messages", json={"message": "x", "role_id": "coder"}).json()["reply"]


def test_engine_and_provider_failures_become_readable_replies_and_are_not_saved(monkeypatch, tmp_path):
    from colony.engine.pi import EngineError
    from colony.llm.http import ProviderError
    live(monkeypatch, tmp_path)
    monkeypatch.setattr(chat, "run_turn", lambda **kw: (_ for _ in ()).throw(EngineError("Pi หยุดทำงานกลางคัน")))
    body = client.post("/api/messages", json={"message": "x", "role_id": "coder"}).json()
    assert body["reply"] == "⚠️ Pi หยุดทำงานกลางคัน"
    monkeypatch.setattr(chat, "run_turn", lambda **kw: (_ for _ in ()).throw(ProviderError("x", status=429)))
    assert "ถูกจำกัดจำนวนครั้ง" in client.post("/api/messages", json={"message": "x", "role_id": "coder"}).json()["reply"]
    assert client.get(f"/api/workspaces/{body['workspace_id']}/messages").json()["messages"] == []


def test_the_user_answers_the_agents_approval_question_through_the_api(monkeypatch, tmp_path):
    live(monkeypatch, tmp_path)
    monkeypatch.setattr(chat, "run_turn", lambda **kw: PiResult(
        "wrote it" if kw["approve"]("write", "Write notes.txt:\nhi") else "they said no", []))
    for answer, expected in ((True, "wrote it"), (False, "they said no")):
        done = {}
        thread = threading.Thread(target=lambda: done.update(client.post("/api/messages", json={"message": "go", "role_id": "coder"}).json()))
        thread.start()
        pending = []
        for _ in range(100):
            pending = client.get("/api/approvals").json()["approvals"]
            if pending:
                break
            time.sleep(0.05)
        assert pending and pending[0]["agent"] == "Coder" and pending[0]["tool"] == "write" and "notes.txt" in pending[0]["message"]
        assert client.post(f"/api/approvals/{pending[0]['id']}", json={"approve": answer}).status_code == 200
        thread.join(timeout=10)
        assert done["reply"] == expected
        assert client.post(f"/api/approvals/{pending[0]['id']}", json={"approve": True}).status_code == 404  # already answered
        assert client.get("/api/approvals").json()["approvals"] == []


def test_no_answer_in_time_means_no(monkeypatch, tmp_path):
    from colony.core.approvals import approvals
    assert approvals.ask(agent="Coder", tool="bash", title="bash", message="rm -rf", timeout=0.05) is False


def test_editor_cannot_save_tools_on_a_model_that_has_none(monkeypatch):
    from colony.api import agents
    monkeypatch.setattr(agents, "supports_tools", lambda model, settings: model != "acme/coder")
    res = client.put("/api/roles", json={"roles": [CODER, BUDDY]})
    assert res.status_code == 400 and "can't use tools" in res.json()["detail"] and "Coder" in res.json()["detail"]
    assert client.put("/api/roles", json={"roles": [{**CODER, "tools": {}}, BUDDY]}).status_code == 200  # tools off: fine


def test_model_tool_support_comes_from_openrouters_catalog(monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "false")
    get_settings.cache_clear()
    monkeypatch.setattr(context, "_live_tools", {})
    monkeypatch.setattr(context, "_live_info", {})
    monkeypatch.setattr(context, "_live_windows", {})
    monkeypatch.setattr(context, "_live_fetched_at", 0.0)
    monkeypatch.setattr(context, "get_json", lambda *a, **k: {"data": [
        {"id": "z-ai/glm-5.2:free", "context_length": 131072, "supported_parameters": ["max_tokens", "temperature"]},
        {"id": "nvidia/nemotron-3-ultra-550b-a55b:free", "context_length": 1000000, "supported_parameters": ["tools", "max_tokens"]},
        {"id": "old/model", "context_length": 8000}]})
    ask = lambda m: client.get("/api/models/tools", params={"model": m}).json()["supported"]  # noqa: E731
    assert ask("z-ai/glm-5.2:free") is False and ask("nvidia/nemotron-3-ultra-550b-a55b:free") is True
    assert ask("old/model") is None and ask("not/listed") is None      # unknown: don't lock it
