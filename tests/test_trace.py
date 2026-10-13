"""What an agent did in a turn: steps from OpenClaw's tool reports, shown under the reply; per-agent files for the settings window."""
import json

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


def test_web_steps_keep_the_pages_that_were_read():
    wrap = lambda x: f"\n<<<EXTERNAL_UNTRUSTED_CONTENT id=\"a\">>>\nSource: Web Search\n---\n{x}\n<<<END_EXTERNAL_UNTRUSTED_CONTENT id=\"a\">>>"
    hit = {"title": wrap("Global SaaS Market"), "url": "https://www.kenresearch.com/saas", "snippet": wrap("USD 408 billion"), "siteName": wrap("kenresearch")}
    body = json.dumps({"results": [hit, {"title": "no link", "url": "javascript:x"}]})
    step = trace.describe("web_search", {"query": "saas growth"}, body)
    assert step["sources"] == [{"title": "Global SaaS Market", "url": "https://www.kenresearch.com/saas", "site": "kenresearch", "snippet": "USD 408 billion"}]
    page = trace.describe("web_fetch", {"url": "https://a.dev/x"}, json.dumps({"title": "A"}))
    assert page["sources"][0]["url"] == "https://a.dev/x" and page["sources"][0]["site"] == "a.dev"
    assert "sources" not in trace.describe("web_search", {"query": "x"}, None, "boom")


def test_a_finished_tool_call_becomes_a_step_of_the_running_turn():
    ws = client.get("/api/workspaces").json()["workspaces"][0]["id"]
    agent = openclaw.agent_id_for(ws, "coding")
    body = {"agent_id": agent, "tool": "exec", "params": {"command": "pwd"}, "result": "/tmp", "duration_ms": 12}
    assert client.post("/api/activity/tool", json=body).status_code == 200     # no turn running: ignored
    assert take_steps(ws) == []
    set_activity(ws, step="thinking", detail="x", role_id="coding")
    client.post("/api/activity/tool", json=body)
    steps = take_steps(ws, "coding")
    assert len(steps) == 1 and steps[0]["detail"] == "pwd" and steps[0]["output"] == "/tmp"
    assert client.get(f"/api/activity?workspace_id={ws}").json()["steps"][0]["title"] == "Ran command"
    clear_activity(ws, "coding")
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


def test_two_agents_answering_at_once_keep_their_own_steps():
    from colony.core.activity import add_step, get_activity
    ws = "ws_parallel"
    set_activity(ws, step="running", detail="a", role_id="chitchat")
    set_activity(ws, step="running", detail="b", role_id="reasoning")
    add_step(ws, {"title": "buddy search"}, "chitchat")
    add_step(ws, {"title": "thinker search 1"}, "reasoning")
    add_step(ws, {"title": "thinker search 2"}, "reasoning")
    assert [s["title"] for s in take_steps(ws, "reasoning")] == ["thinker search 1", "thinker search 2"]
    assert len(get_activity(ws)["steps"]) == 3                       # the live view shows the whole workspace
    clear_activity(ws, "reasoning")                                  # the first to finish must not take the other's steps
    assert [s["title"] for s in take_steps(ws, "chitchat")] == ["buddy search"]
    add_step(ws, {"title": "late"}, "chitchat")
    clear_activity(ws, "chitchat")
    assert take_steps(ws, "chitchat") == []


def test_using_a_skill_is_a_step_with_its_name():
    step = trace.describe("skills_read", {"name": "zebra"}, "text")
    assert (step["kind"], step["title"], step["detail"]) == ("skill", "Used skill", "zebra")
