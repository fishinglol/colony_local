"""Workspaces: each has its own team (own models), one shared conversation, its own memory and project folder."""
import json

from fastapi.testclient import TestClient

from colony.app import app
from colony.config import get_settings
from colony.engine import openclaw

client = TestClient(app)


def make(name="Shop", **extra):
    res = client.post("/api/workspaces", json={"name": name, **extra})
    assert res.status_code == 200, res.text
    return res.json()


def live(monkeypatch):
    """Real (non-mock) mode with a fake OpenClaw: returns the turns it was asked to run."""
    monkeypatch.setenv("MOCK_MODE", "false")
    get_settings.cache_clear()
    monkeypatch.setattr(openclaw, "is_openclaw_available", lambda s=None: True)
    monkeypatch.setattr(openclaw, "mark_seen", lambda *a: None)
    turns = []

    def fake_turn(**kw):
        turns.append(kw)
        return openclaw.OpenClawTurnResult(reply="ok", model=kw["role_model"], session_user="ome-test")

    monkeypatch.setattr(openclaw, "run_openclaw_turn", fake_turn)
    return turns


def test_a_fresh_install_has_one_workspace_with_the_default_team():
    listed = client.get("/api/workspaces").json()["workspaces"]
    assert [(w["id"], w["name"]) for w in listed] == [("local", "Personal")]
    assert [a["name"] for a in listed[0]["agents"]] == ["Thinker", "Buddy", "Writer", "Coder"]
    assert client.get("/api/health").json()["workspaces"] == 1


def test_each_workspace_has_its_own_team_with_its_own_models():
    shop = make("Shop")
    assert [a["name"] for a in shop["agents"]] == ["Thinker", "Buddy", "Writer", "Coder"]     # starts as the default team
    custom = [{"id": "boss", "name": "Boss", "model": "acme/boss-1", "when": "everything", "instructions": ""}]
    assert client.put(f"/api/roles?workspace_id={shop['id']}", json={"roles": custom}).status_code == 200
    assert [r["id"] for r in client.get(f"/api/roles?workspace_id={shop['id']}").json()["roles"]] == ["boss"]
    assert [r["id"] for r in client.get("/api/roles?workspace_id=local").json()["roles"]][0] == "reasoning"   # untouched

    # the workspace decides which model answers
    assert client.post("/api/messages", json={"message": "hi", "workspace_id": shop["id"], "role_id": "boss"}).json()["model"] == "acme/boss-1"
    assert client.post("/api/messages", json={"message": "hi", "workspace_id": "local", "role_id": "coding"}).json()["model"] == "ollama/gpt-oss:120b"


def test_a_new_workspace_can_start_from_a_copy_of_another_team_and_then_diverge():
    team = [{"id": "boss", "name": "Boss", "model": "acme/boss-1", "when": "all", "instructions": "Be brief.",
             "tools": {"read": "allow", "write": "ask", "bash": "off"}}]
    client.put("/api/roles?workspace_id=local", json={"roles": team})
    copy = make("Copy", copy_agents_from="local")
    copied = client.get(f"/api/roles?workspace_id={copy['id']}").json()["roles"]
    assert copied[0]["model"] == "acme/boss-1" and copied[0]["tools"]["write"] == "ask"
    client.put(f"/api/roles?workspace_id={copy['id']}", json={"roles": [{**team[0], "model": "acme/other"}]})
    assert client.get("/api/roles?workspace_id=local").json()["roles"][0]["model"] == "acme/boss-1"
    assert client.post("/api/workspaces", json={"name": "X", "copy_agents_from": "nope"}).status_code == 404


def test_conversations_are_separate_per_workspace_but_one_conversation_inside_each(monkeypatch):
    turns = live(monkeypatch)
    shop = make("Shop")
    post = lambda ws, text, role, channel=None: client.post("/api/messages", json={  # noqa: E731
        "message": text, "workspace_id": ws, "role_id": role, "channel": channel or role}).json()
    post("local", "the launch code is 4242", "chitchat", "auto")
    post("local", "what is the launch code?", "coding")                    # another agent, direct chat, same workspace
    assert "4242" in json.dumps(turns[-1]["history"])
    post(shop["id"], "what is the launch code?", "coding")                 # another workspace
    assert "4242" not in json.dumps(turns[-1]["history"])
    assert [m["role"] for m in client.get(f"/api/workspaces/{shop['id']}/messages").json()["messages"]] == ["user", "assistant"]
    assert len(client.get("/api/workspaces/local/messages").json()["messages"]) == 4


def test_memory_is_kept_per_workspace(monkeypatch):
    live(monkeypatch)
    shop = make("Shop")
    folder = openclaw.memory_dir(get_settings(), shop["id"])
    openclaw._seed_memory_dir(folder)
    (folder / "MEMORY.md").write_text("# Memory\n- The cafe closes at 5pm.\n")
    assert "closes at 5pm" in client.get(f"/api/memory/context?workspace_id={shop['id']}").json()["context"]
    assert "closes at 5pm" not in client.get("/api/memory/context?workspace_id=local").json()["context"]


def test_an_explicit_remember_request_is_kept_even_if_the_agent_wrote_nothing(monkeypatch):
    live(monkeypatch)
    body = client.post("/api/messages", json={"message": "remember my dog is Kaprao", "role_id": "chitchat"}).json()
    assert body["memory_saved"] is True
    assert "Kaprao" in client.get("/api/memory/context").json()["context"]


def test_project_folder_is_checked_and_never_the_whole_disk(tmp_path):
    (tmp_path / "proj").mkdir()
    (tmp_path / "file.txt").write_text("x")
    shop = make("Shop", folder=str(tmp_path / "proj"))
    assert shop["folder"] == str((tmp_path / "proj").resolve()) and shop["folder_source"] == "workspace"
    for bad in ("/", "~", "relative/path", str(tmp_path / "nope"), str(tmp_path / "file.txt")):
        assert client.patch(f"/api/workspaces/{shop['id']}", json={"folder": bad}).status_code == 400, bad
        assert client.post("/api/workspaces", json={"name": "Y", "folder": bad}).status_code == 400, bad
    cleared = client.patch(f"/api/workspaces/{shop['id']}", json={"folder": ""}).json()
    assert cleared["folder"] is None


def test_rename_and_delete_a_workspace_with_its_conversation_memory_and_openclaw_agents(monkeypatch):
    live(monkeypatch)
    shop = make("Shop")
    assert client.patch(f"/api/workspaces/{shop['id']}", json={"name": "  Coffee   shop "}).json()["name"] == "Coffee shop"
    client.post("/api/messages", json={"message": "remember a fact", "workspace_id": shop["id"], "role_id": "chitchat"})
    memory_dir = get_settings().data_dir / "self_improve" / shop["id"]
    assert memory_dir.exists()
    mine, other = openclaw.agent_id_for(shop["id"], "chitchat"), openclaw.agent_id_for("local", "chitchat")
    agent_dir = openclaw.config_path().parent / "agents" / mine
    agent_dir.mkdir(parents=True)
    openclaw.write_config({"agents": {"entries": {"main": {}, mine: {"name": "Buddy"}, other: {"name": "Buddy"}}}})

    assert client.delete(f"/api/workspaces/{shop['id']}").status_code == 200
    assert not memory_dir.exists() and not agent_dir.exists()
    assert set(openclaw.read_config()["agents"]["entries"]) == {"main", other}      # only that workspace's agents went
    assert client.get(f"/api/workspaces/{shop['id']}/messages").status_code == 404
    assert client.post("/api/messages", json={"message": "hi", "workspace_id": shop["id"]}).status_code == 404
    assert client.delete("/api/workspaces/local").status_code == 400          # the last one stays
    for path in ("/api/roles", "/api/context", "/api/memory/context"):
        assert client.get(path, params={"workspace_id": shop["id"]}).status_code == 404, path


def test_without_a_workspace_id_the_first_workspace_is_used():
    body = client.post("/api/messages", json={"message": "hi", "role_id": "coding"}).json()
    assert body["workspace_id"] == "local"


def test_the_old_single_space_becomes_the_first_workspace(tmp_path, monkeypatch):
    data = get_settings().data_dir
    (tmp_path / "old-project").mkdir()
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path / "old-project"))       # the old global folder setting
    get_settings.cache_clear()
    (data / "roles.json").write_text(json.dumps({"roles": [
        {"id": "solo", "name": "Solo", "model": "acme/solo", "when": "all", "instructions": ""}]}))
    msg = lambda role, text, at, **extra: {"id": f"m-{text}", "role": role, "content": text, "created_at": at, **extra}  # noqa: E731
    (data / "history.json").write_text(json.dumps({"trace_events": [], "conversations": [
        {"id": "conv_new", "title": "second", "created_at": "2026-09-25T10:00:00", "updated_at": "2026-09-25T10:00:00",
         "messages": [msg("user", "new question", "2026-09-25T10:00:00", channel="auto"), msg("assistant", "new answer", "2026-09-25T10:00:00")]},
        {"id": "conv_old", "title": "first", "created_at": "2026-09-24T09:00:00", "updated_at": "2026-09-24T09:00:00",
         "messages": [msg("user", "old question", "2026-09-24T09:00:00", channel="auto"), msg("assistant", "old answer", "2026-09-24T09:00:00")]}]}))
    memory_dir = data / "self_improve" / "local"
    memory_dir.mkdir(parents=True)
    (memory_dir / "MEMORY.md").write_text("The user likes tea.")

    workspaces = client.get("/api/workspaces").json()["workspaces"]
    assert [(w["id"], w["name"]) for w in workspaces] == [("local", "Personal")]
    assert workspaces[0]["folder"] == str((tmp_path / "old-project").resolve())
    assert [a["id"] for a in workspaces[0]["agents"]] == ["solo"]
    messages = client.get("/api/workspaces/local/messages").json()["messages"]
    assert [m["content"] for m in messages] == ["old question", "old answer", "new question", "new answer"]   # one timeline
    assert "likes tea" in client.get("/api/memory/context").json()["context"]                                # memory didn't move
    assert (data / "history.json.bak-before-workspaces").exists()

    assert client.get("/api/workspaces").json()["workspaces"] == workspaces                                  # runs only once
    assert len(client.get("/api/workspaces/local/messages").json()["messages"]) == 4


def test_a_damaged_workspaces_file_is_kept_not_overwritten():
    client.get("/api/workspaces")
    path = get_settings().data_dir / "workspaces.json"
    path.write_text("{ this is not json, but it is long enough to matter")
    assert client.get("/api/workspaces").json()["workspaces"][0]["name"] == "Personal"
    assert list(get_settings().data_dir.glob("workspaces.json.corrupt-*"))


def test_an_agent_left_on_a_non_ollama_model_is_told_to_pick_one(monkeypatch):
    turns = live(monkeypatch)
    old = [{"id": "boss", "name": "Boss", "model": "anthropic/claude-sonnet-5", "when": "all", "instructions": ""}]
    client.put("/api/roles?workspace_id=local", json={"roles": old})
    body = client.post("/api/messages", json={"message": "hi", "role_id": "boss"}).json()
    assert "not an Ollama model" in body["reply"] and "Boss" in body["reply"] and turns == []
    assert client.get("/api/workspaces/local/messages").json()["messages"] == []
