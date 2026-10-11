"""The approval gate: what Colony answers when OpenClaw asks "may this agent run this tool?" (see core/gate.py)."""
import pytest
from fastapi.testclient import TestClient

from colony.app import app
from colony.config import get_settings
from colony.core import gate
from colony.engine import openclaw

client = TestClient(app)


def team(tmp_path, **tools):
    """A workspace with a project folder and one agent, "coder", with these tool permissions."""
    ws = client.post("/api/workspaces", json={"name": "Shop", "folder": str(tmp_path)}).json()["id"]
    role = {"id": "coder", "name": "Coder", "model": "ollama/test", "when": "code", "tools": tools}
    assert client.put(f"/api/roles?workspace_id={ws}", json={"roles": [role]}).status_code == 200
    return ws, openclaw.agent_id_for(ws, "coder")


def ask(agent_id, tool, **params):
    return gate.decide(get_settings(), agent_id, tool, params)


@pytest.fixture
def answers(monkeypatch):
    """Stand in for the user: records each question and answers with `.reply`."""
    class Answers:
        reply, asked = True, []
    box = Answers()

    def fake_ask(**kw):
        box.asked.append(kw)
        return box.reply
    monkeypatch.setattr(gate.approvals, "ask", fake_ask)
    return box


def test_the_gate_route_is_not_swallowed_by_the_approval_id_route(tmp_path):
    ws, agent = team(tmp_path, read="allow")
    res = client.post("/api/approvals/gate", json={"agent_id": agent, "tool": "read", "params": {"path": "a.txt"}})
    assert res.status_code == 200 and res.json() == {"allow": True, "reason": ""}   # not a 422 from /approvals/{id}


def test_an_unknown_agent_is_refused():
    assert ask("ws_nobody-coder", "read", path="a.txt")["allow"] is False


def test_allow_runs_without_asking_and_off_is_refused(tmp_path, answers):
    ws, agent = team(tmp_path, read="allow", write="allow", bash="off")
    assert ask(agent, "read", path="a.txt")["allow"] is True
    assert ask(agent, "write", path="a.txt", content="x")["allow"] is True
    assert ask(agent, "exec", command="ls")["allow"] is False
    assert answers.asked == []


def test_ask_waits_for_the_user_and_does_what_they_said(tmp_path, answers):
    ws, agent = team(tmp_path, bash="ask")
    answers.reply = True
    assert ask(agent, "exec", command="echo hi")["allow"] is True
    answers.reply = False
    denied = ask(agent, "exec", command="echo hi")
    assert denied["allow"] is False and "not approve" in denied["reason"]
    assert [q["tool"] for q in answers.asked] == ["bash", "bash"] and "echo hi" in answers.asked[0]["message"]


def test_a_connector_call_is_asked_about_by_the_connector_permission(tmp_path, answers):
    ws, agent = team(tmp_path, mcp="ask")
    assert ask(agent, "fake__echo", text="hi")["allow"] is True
    assert answers.asked[0]["tool"] == "mcp" and "fake__echo" in answers.asked[0]["message"]
    off_ws, off_agent = team(tmp_path, mcp="off")
    assert ask(off_agent, "fake__echo", text="hi")["allow"] is False


def test_files_and_commands_stay_inside_the_project_folder(tmp_path, answers):
    ws, agent = team(tmp_path, read="allow", write="allow", bash="allow")
    assert ask(agent, "read", path="../secret.txt")["allow"] is False
    assert ask(agent, "write", path="/etc/hosts", content="x")["allow"] is False
    (tmp_path / "link").symlink_to("/etc")
    assert ask(agent, "read", path="link/hosts")["allow"] is False      # a symlink out of the folder is still out


def test_no_project_folder_means_no_files_or_commands(answers):
    ws = client.post("/api/workspaces", json={"name": "Chat only", "folder": ""}).json()["id"]
    role = {"id": "coder", "name": "Coder", "model": "ollama/test", "when": "code", "tools": {"bash": "allow", "read": "allow"}}
    client.put(f"/api/roles?workspace_id={ws}", json={"roles": [role]})
    verdict = ask(openclaw.agent_id_for(ws, "coder"), "exec", command="ls")
    assert verdict["allow"] is False and "project folder" in verdict["reason"]


def test_the_workspace_mode_overrides_the_agents_own_setting(tmp_path, answers):
    ws, agent = team(tmp_path, bash="allow")
    client.patch(f"/api/workspaces/{ws}", json={"mode": "manual"})        # manual = ask before every change
    ask(agent, "exec", command="ls")
    assert len(answers.asked) == 1
    client.patch(f"/api/workspaces/{ws}", json={"mode": "plan"})          # plan = read only
    assert ask(agent, "exec", command="ls")["allow"] is False


def test_registering_the_gate_sets_a_long_hook_limit_and_replaces_a_stale_path():
    cfg = {"plugins": {"load": {"paths": ["/x/other", "/old/colony/engine/colony-gate.ts"]}}}
    assert openclaw._register_gate(cfg, 120) is True
    assert cfg["plugins"]["load"]["paths"] == ["/x/other", str(openclaw.GATE_PLUGIN)]
    entry = cfg["plugins"]["entries"]["colony-gate"]
    assert entry["enabled"] is True and entry["hooks"]["timeouts"]["before_tool_call"] == 130_000   # default 15 s would cut a user off
    assert openclaw._register_gate(cfg, 120) is False                       # second time: nothing to change
    assert (openclaw.GATE_PLUGIN / "openclaw.plugin.json").exists() and (openclaw.GATE_PLUGIN / "index.ts").exists()


def test_any_role_may_keep_the_shared_memory_files_but_nothing_else_outside_its_folder(tmp_path, answers):
    ws, agent = team(tmp_path, read="off", write="off")            # a chat-only role
    mem = openclaw.memory_dir(get_settings(), ws)
    assert ask(agent, "write", path=str(mem / "MEMORY.md"), content="x")["allow"] is True
    assert ask(agent, "read", path=str(mem / "memory" / "2026-10-10.md"))["allow"] is True
    assert ask(agent, "edit", path="MEMORY.md")["allow"] is False   # a relative path would land in the project folder
    assert ask(agent, "write", path=str(mem / ".." / "other" / "MEMORY.md"), content="x")["allow"] is False
    assert ask(agent, "write", path=str(tmp_path / "a.txt"), content="x")["allow"] is False   # project files still need the permission
    assert answers.asked == []


def test_each_agent_has_its_own_workspace_and_all_search_the_shared_memory_folder(monkeypatch, tmp_path):
    from colony.config import Settings
    settings = Settings(openclaw_gateway_url="http://127.0.0.1:1", data_dir=tmp_path)
    monkeypatch.setattr(openclaw.urllib.request, "urlopen", lambda url, timeout=None: (_ for _ in ()).throw(OSError("no gateway")))
    mem = openclaw.memory_dir(settings, "ws_1")
    for role in ("coder", "buddy"):
        with pytest.raises(Exception):
            openclaw.ensure_agent(settings, f"ws_1-{role}", role, memory=mem, wait_seconds=0.1)
    entries = openclaw.read_config()["agents"]["entries"]
    assert entries["ws_1-coder"]["workspace"] != entries["ws_1-buddy"]["workspace"]          # one workspace (SOUL.md) per agent
    assert entries["ws_1-coder"]["workspace"] == str(openclaw.agent_dir(settings, "ws_1-coder"))
    for role in ("coder", "buddy"):
        assert entries[f"ws_1-{role}"]["memory"] == {"search": {"extraPaths": [str(mem)]}}    # ...and one shared memory
    assert (mem / "MEMORY.md").exists() and (mem / "USER.md").exists() and (mem / "memory").is_dir()


def test_an_explicit_remember_request_is_kept_even_when_the_model_wrote_nothing(tmp_path):
    from colony.config import Settings
    settings = Settings(data_dir=tmp_path)
    ws = "ws_1"
    notes = openclaw.memory_dir(settings, ws) / "USER.md"
    before = openclaw.snapshot_memory(settings, ws)                    # also creates the starter files

    assert openclaw.keep_if_asked(settings, ws, "วันนี้อากาศดีจัง", before) is False          # small talk is not kept
    assert openclaw.keep_if_asked(settings, ws, "ช่วยจำไว้ให้หน่อย: ฉันชื่อสมชาย", before) is True
    assert "ฉันชื่อสมชาย" in notes.read_text(encoding="utf-8")

    before = openclaw.snapshot_memory(settings, ws)
    notes.write_text(notes.read_text(encoding="utf-8") + "- ชื่อ: สมชาย\n", encoding="utf-8")   # this time the model wrote it itself
    assert openclaw.keep_if_asked(settings, ws, "remember that my dog is Mochi", before) is False
    assert notes.read_text(encoding="utf-8").count("\n") == 3          # nothing was added on top of the model's own note


def test_memory_search_is_allowed_for_every_agent_and_set_up_keyword_only():
    from colony.engine import openclaw
    assert {"memory_search", "memory_get"} <= set(openclaw._tool_allowlist(None, False, []))
    cfg = {"memory": {"search": {"enabled": False}}}
    assert openclaw._enable_memory_search(cfg) is True
    assert cfg["memory"]["search"] == {"enabled": True, "provider": "none"}
    assert openclaw._enable_memory_search(cfg) is False        # already set: no config write, no reload wait


def test_background_work_nobody_asked_for_is_switched_off_once():
    from colony.engine import openclaw
    cfg = {}
    assert openclaw._quiet_background(cfg) is True
    assert cfg["skills"]["workshop"]["autonomous"]["mode"] == "off" and cfg["agents"]["defaults"]["heartbeat"]["every"] == "0m"
    assert openclaw._quiet_background(cfg) is False


def test_an_agent_may_read_its_own_skills_and_no_one_elses(tmp_path, answers):
    ws, agent = team(tmp_path, read="off")
    mine = openclaw.skills_dir(get_settings(), agent) / "zebra" / "SKILL.md"
    other = openclaw.skills_dir(get_settings(), openclaw.agent_id_for(ws, "writer")) / "zebra" / "SKILL.md"
    assert ask(agent, "skills_read", name="zebra")["allow"] is True
    assert ask(agent, "read", path=str(mine))["allow"] is True
    assert answers.asked == []
    assert ask(agent, "read", path=str(other))["allow"] is True         # another agent's skill is outside its own: the user is asked
    assert len(answers.asked) == 1


def test_installing_a_skill_by_chat_asks_the_user_for_every_file(tmp_path, answers):
    ws, agent = team(tmp_path, read="off", write="off")
    source = tmp_path.parent / "elsewhere" / "zebra"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("---\nname: zebra\n---\n")
    (source / "helper.md").write_text("x")
    mine = openclaw.skills_dir(get_settings(), agent) / "zebra" / "SKILL.md"
    assert ask(agent, "read", path=str(source / "SKILL.md"))["allow"] is True      # outside the folder, but asked first
    assert ask(agent, "read", path=str(source / "helper.md"))["allow"] is True      # a file inside a skill folder
    assert ask(agent, "write", path=str(mine), content="x")["allow"] is True        # even though write is off
    assert len(answers.asked) == 3
    assert ask(agent, "read", path=str(mine))["allow"] is True                       # reading its own skill is not a question
    assert len(answers.asked) == 3
    (tmp_path.parent / "elsewhere" / "secret.txt").write_text("s")
    assert ask(agent, "read", path=str(tmp_path.parent / "elsewhere" / "secret.txt"))["allow"] is False   # not a skill folder
    answers.reply = False
    assert ask(agent, "write", path=str(mine), content="x")["allow"] is False        # "no" is respected
