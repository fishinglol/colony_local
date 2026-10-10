"""What an agent did in a turn: steps from OpenClaw's tool reports, shown under the reply; per-agent files for the settings window."""
from fastapi.testclient import TestClient

from colony.app import app
from colony.config import get_settings
from colony.core import trace
from colony.core.activity import clear_activity, set_activity, take_steps
from colony.engine import openclaw

client = TestClient(app)


def test_steps_say_what_happened_in_plain_words():
    cmd = trace.describe("exec", {"command": "ls -la"}, {"content": [{"type": "text", "text": "a\nb"}]}, None, 40)
    assert (cmd["kind"], cmd["title"], cmd["detail"], cmd["output"], cmd["ok"], cmd["ms"]) == ("command", "Ran command", "ls -la", "a\nb", True, 40)
    assert trace.describe("read", {"path": "src/a.ts", "offset": 1, "limit": 45}, "x")["detail"] == "src/a.ts#L1-45"
    assert trace.describe("edit", {"path": "a.py"})["title"] == "Edited"
    assert trace.describe("memory_search", {"query": "budget"})["kind"] == "memory"
    assert trace.describe("web_search", {"query": "btc"})["title"] == "Searched the web"
    conn = trace.describe("composio__GITHUB_LIST", {"repo": "x"})
    assert (conn["kind"], conn["title"], conn["detail"]) == ("connector", "Used composio", "GITHUB_LIST")
    failed = trace.describe("exec", {"command": "false"}, None, "exit 1")
    assert failed["ok"] is False and failed["output"] == "exit 1"
    assert len(trace.describe("exec", {"command": "x"}, "y" * 10_000)["output"]) == trace.OUTPUT_LIMIT


def test_a_finished_tool_call_becomes_a_step_of_the_running_turn():
    ws = client.get("/api/workspaces").json()["workspaces"][0]["id"]
    agent = openclaw.agent_id_for(ws, "coding")
    body = {"agent_id": agent, "tool": "exec", "params": {"command": "pwd"}, "result": "/tmp", "duration_ms": 12}
    assert client.post("/api/activity/tool", json=body).status_code == 200     # no turn running: ignored
    assert take_steps(ws) == []
    set_activity(ws, step="thinking", detail="x")
    client.post("/api/activity/tool", json=body)
    steps = take_steps(ws)
    assert len(steps) == 1 and steps[0]["detail"] == "pwd" and steps[0]["output"] == "/tmp"
    assert client.get(f"/api/activity?workspace_id={ws}").json()["steps"][0]["title"] == "Ran command"
    clear_activity(ws)
    assert client.post("/api/activity/tool", json={**body, "agent_id": "nobody"}).status_code == 200


def test_a_reply_carries_its_steps_and_time():
    body = client.post("/api/messages", json={"message": "hi", "role_id": "coding"}).json()   # mock mode adds a demo trace
    assert [s["kind"] for s in body["steps"]] == ["command", "read", "memory"] and body["worked_s"] is not None
    saved = client.get(f"/api/workspaces/{body['workspace_id']}/messages").json()["messages"][-1]["metadata"]
    assert len(saved["steps"]) == 3 and "worked_s" in saved                          # kept with the message


def test_the_settings_window_can_read_an_agents_files(tmp_path):
    s = get_settings()
    ws = client.get("/api/workspaces").json()["workspaces"][0]["id"]
    before = client.get(f"/api/roles/coding/files?workspace_id={ws}").json()
    assert before["started"] is False and "# Coder" in before["soul"] and before["name"] == "Coder"      # a preview until its first turn

    openclaw.write_agent_files(s, ws, openclaw.agent_id_for(ws, "coding"), "Coder", "Show code first.")
    shared = openclaw.memory_dir(s, ws)
    (shared / "MEMORY.md").write_text("# Memory\n- tea is good\n")
    (shared / "memory" / "2026-10-05.md").write_text("# day\n- met Somchai\n")
    after = client.get(f"/api/roles/coding/files?workspace_id={ws}").json()
    assert after["started"] is True and "Show code first." in after["soul"] and "Coder" in after["identity"]
    assert "tea is good" in after["memory"] and after["daily"][0]["date"] == "2026-10-05" and "memory_search" in after["rules"]
    assert client.get(f"/api/roles/nobody/files?workspace_id={ws}").status_code == 404
