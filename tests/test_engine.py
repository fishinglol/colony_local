"""The Pi engine (colony/engine/pi.py). Two layers:
- a fake `pi` program that speaks Pi's RPC protocol, to test Colony's side (approvals, errors, what it hands Pi);
- the real Pi against a fake model server, to test the whole thing including the approval gate (skipped if Pi isn't installed).
"""
import json
import os
import stat
import sys
import textwrap

import pytest

from colony.config import Settings
from colony.core.agents import ToolAccess
from colony.engine import pi as engine
from colony.llm.http import ProviderError

FAKE_PI = textwrap.dedent('''\
    #!{python}
    import json, os, sys, time
    out = lambda rec: (sys.stdout.write(json.dumps(rec) + "\\n"), sys.stdout.flush())
    agent_dir = os.environ["PI_CODING_AGENT_DIR"]
    json.dump({{"argv": sys.argv[1:], "env": sorted(os.environ), "cwd": os.getcwd(), "policy": os.environ.get("COLONY_POLICY")}},
              open(os.path.join(agent_dir, "fake-run.json"), "w"))
    prompt = json.loads(sys.stdin.readline())["message"]
    if prompt == "CRASH":
        sys.stderr.write("boom: node too old"); sys.exit(3)
    if prompt == "HANG":
        time.sleep(60)
    if prompt.startswith("WRITE"):
        out({{"type": "tool_execution_start", "toolCallId": "1", "toolName": "write", "args": {{"path": "notes.txt"}}}})
        out({{"type": "extension_ui_request", "id": "q1", "method": "confirm", "title": "write", "message": "Write notes.txt:\\nhi"}})
        answer = json.loads(sys.stdin.readline())
        ok = answer.get("confirmed") is True
        out({{"type": "tool_execution_end", "toolCallId": "1", "toolName": "write", "isError": not ok}})
        text = "wrote it" if ok else "they said no"
    elif prompt == "FAIL429":
        out({{"type": "message_end", "message": {{"role": "assistant", "content": [], "stopReason": "error",
              "errorMessage": '429: {{"error":{{"message":"Provider returned error","metadata":{{"raw":"rate limited upstream"}}}}}}'}}}})
        out({{"type": "agent_settled"}}); sys.exit(0)
    else:
        text = "ok"
    out({{"type": "message_end", "message": {{"role": "assistant", "content": [{{"type": "text", "text": text}}]}}}})
    out({{"type": "agent_settled"}})
''')


@pytest.fixture
def fake_pi(tmp_path):
    path = tmp_path / "fake-pi"
    path.write_text(FAKE_PI.format(python=sys.executable))
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


@pytest.fixture
def settings(tmp_path, fake_pi):
    return Settings(openrouter_api_key="sk-or-secret", data_dir=tmp_path, pi_bin=str(fake_pi),
                    tools_turn_timeout_seconds=30.0, approval_timeout_seconds=5.0)


def turn(settings, tmp_path, message="hi", approve=lambda tool, what: True, tools=None, **kw):
    workspace = tmp_path / "ws"
    workspace.mkdir(exist_ok=True)
    return engine.run_turn(settings=settings, model="acme/model:free", system_prompt="You are Coder.", prompt=message,
                           workspace=workspace, tools=tools or ToolAccess(read="allow", write="ask"), approve=approve, **kw)


def test_approved_action_is_reported(settings, tmp_path):
    asked = []
    result = turn(settings, tmp_path, "WRITE", approve=lambda tool, what: asked.append((tool, what)) or True)
    assert asked == [("write", "Write notes.txt:\nhi")]
    assert (result.text, result.actions) == ("wrote it", ["wrote notes.txt"])


def test_refused_action_is_marked_and_the_agent_carries_on(settings, tmp_path):
    result = turn(settings, tmp_path, "WRITE", approve=lambda tool, what: False)
    assert (result.text, result.actions) == ("they said no", ["wrote notes.txt ✗"])


def test_an_error_while_asking_counts_as_no(settings, tmp_path):
    def broken(tool, what):
        raise RuntimeError("UI exploded")

    assert turn(settings, tmp_path, "WRITE", approve=broken).text == "they said no"


def test_pi_is_started_locked_down_and_gets_no_secrets(settings, tmp_path):
    turn(settings, tmp_path, tools=ToolAccess(read="allow", write="ask", bash="off"))
    agent_dir = tmp_path / "pi-agent"
    ran = json.loads((agent_dir / "fake-run.json").read_text())
    argv = ran["argv"]
    assert argv[argv.index("--tools") + 1] == "read,grep,find,ls,write,edit"          # no bash unless switched on
    assert argv[argv.index("--model") + 1] == "acme/model:free" and argv[argv.index("--provider") + 1] == "colony"
    for flag in ("--no-session", "--no-context-files", "--no-skills", "--no-extensions", "--no-approve"):
        assert flag in argv
    assert "--thinking" not in argv                                                    # the model's own reasoning unless the agent picks one
    assert argv[argv.index("-e") + 1].endswith("colony-gate.ts")
    assert (agent_dir / "system-prompt.md").read_text() == "You are Coder."
    assert json.loads(ran["policy"]) == {"write": "ask", "edit": "ask", "bash": "off", "mcp": "off"}
    assert ran["cwd"] == str((tmp_path / "ws").resolve())
    # the key lives in a private file for Pi, not in its environment (a bash tool could print the environment)
    assert not any("KEY" in name for name in ran["env"])
    models = agent_dir / "models.json"
    assert json.loads(models.read_text())["providers"]["colony"]["models"] == [{"id": "acme/model:free"}]
    assert stat.S_IMODE(models.stat().st_mode) == 0o600


def test_the_agents_reasoning_level_is_handed_to_pi(settings, tmp_path):
    turn(settings, tmp_path, thinking="low")
    argv = json.loads((tmp_path / "pi-agent" / "fake-run.json").read_text())["argv"]
    assert argv[argv.index("--thinking") + 1] == "low"
    model = json.loads((tmp_path / "pi-agent" / "models.json").read_text())["providers"]["colony"]["models"][0]
    assert model["reasoning"] is True and model["thinkingLevelMap"]["xhigh"] == "xhigh" and model["thinkingLevelMap"]["off"] == "none"


def test_a_failed_model_call_becomes_a_provider_error_with_its_status(settings, tmp_path):
    with pytest.raises(ProviderError) as caught:
        turn(settings, tmp_path, "FAIL429")
    assert caught.value.status == 429 and "rate limited upstream" in caught.value.provider_message


def test_engine_problems_are_explained_not_raised_raw(settings, tmp_path):
    with pytest.raises(engine.EngineError, match="boom: node too old"):
        turn(settings, tmp_path, "CRASH")
    with pytest.raises(engine.EngineError, match="นานเกินไป"):
        turn(settings.model_copy(update={"tools_turn_timeout_seconds": 1.0}), tmp_path, "HANG")


def test_missing_pi_or_key_says_what_to_do(settings, tmp_path, monkeypatch):
    with pytest.raises(engine.EngineError, match="API key"):
        turn(settings.model_copy(update={"openrouter_api_key": None}), tmp_path)
    monkeypatch.setattr(engine, "RUNTIME_PI", tmp_path / "nowhere")
    monkeypatch.setattr(engine.shutil, "which", lambda name: None)
    with pytest.raises(engine.EngineError, match="pi-runtime"):
        turn(settings.model_copy(update={"pi_bin": None}), tmp_path)


def test_the_shared_conversation_goes_in_as_the_prompt():
    assert engine.transcript_prompt([], "hello") == "hello"
    text = engine.transcript_prompt([{"role": "user", "content": "plan it"}, {"role": "assistant", "content": "[Thinker] step 1"}], "do step 1")
    assert text.startswith("Conversation so far:\n\nUser: plan it\n\n[Thinker] step 1")
    assert text.endswith("The user's new message:\ndo step 1")


# ── the real Pi, against a fake model server ────────────────────────────────────────────────────
real_pi = pytest.mark.skipif(not engine.RUNTIME_PI.exists(), reason="Pi is not installed (npm install in local/pi-runtime)")


@pytest.fixture
def model_server():
    from .fake_llm import FakeModelServer
    server = FakeModelServer()
    yield server
    server.shutdown()


@pytest.fixture
def real_settings(tmp_path, model_server):
    return Settings(openrouter_api_key="sk-or-secret", data_dir=tmp_path, openrouter_base_url=model_server.base_url,
                    tools_turn_timeout_seconds=90.0, approval_timeout_seconds=20.0)


@real_pi
def test_real_pi_writes_a_file_only_after_approval(real_settings, tmp_path, model_server):
    asked = []
    turn(real_settings, tmp_path, "WRITE yes.txt hello", approve=lambda tool, what: asked.append((tool, what)) or True)
    assert (tmp_path / "ws" / "yes.txt").read_text() == "hello"
    assert asked and asked[0][0] == "write" and "yes.txt" in asked[0][1]
    result = turn(real_settings, tmp_path, "WRITE no.txt nope", approve=lambda tool, what: False)
    assert not (tmp_path / "ws" / "no.txt").exists()
    assert "did not approve" in result.text and result.actions == ["wrote no.txt ✗"]
    assert model_server.requests[0]["auth"] == "Bearer sk-or-secret"


@real_pi
def test_real_pi_allow_skips_the_question_and_off_hides_the_tool(real_settings, tmp_path, model_server):
    result = turn(real_settings, tmp_path, "WRITE free.txt ok", approve=lambda tool, what: pytest.fail("asked"),
                  tools=ToolAccess(read="allow", write="allow"))
    assert (tmp_path / "ws" / "free.txt").exists() and result.actions == ["wrote free.txt"]
    turn(real_settings, tmp_path, "hello", tools=ToolAccess(read="allow"))
    assert sorted(model_server.requests[-1]["tools"]) == ["find", "grep", "ls", "read"]


@real_pi
def test_real_pi_cannot_leave_the_workspace(real_settings, tmp_path):
    outside = tmp_path / "secret.txt"
    outside.write_text("TOP-SECRET")
    tools = ToolAccess(read="allow", write="allow")
    turn(real_settings, tmp_path, "WRITE ../escaped.txt x", tools=tools)
    assert not (tmp_path / "escaped.txt").exists()
    assert "TOP-SECRET" not in turn(real_settings, tmp_path, f"READ {outside}", tools=tools).text
    (tmp_path / "ws" / "inside.txt").write_text("INSIDE-OK")
    assert "INSIDE-OK" in turn(real_settings, tmp_path, "READ inside.txt", tools=tools).text


@real_pi
def test_real_pi_gets_only_what_colony_hands_it(real_settings, tmp_path, model_server):
    (tmp_path / "ws").mkdir()
    (tmp_path / "ws" / "CLAUDE.md").write_text("PROJECT RULE: talk like a pirate")
    turn(real_settings, tmp_path, "hello")
    sent = model_server.requests[-1]
    assert "You are Coder." in " ".join(sent["system"]) and "pirate" not in " ".join(sent["system"])
    assert sent["model"] == "acme/model:free"


@real_pi
def test_real_pi_sends_exactly_the_reasoning_level_the_agent_chose(real_settings, tmp_path, model_server):
    sent = {}
    for level in (None, "low", "xhigh", "max", "off"):        # xhigh/max/off used to be lowered or dropped by Pi
        turn(real_settings, tmp_path, "hello", thinking=level)
        sent[level] = model_server.requests[-1]["reasoning"]
    assert sent == {None: {}, "low": {"reasoning_effort": "low"}, "xhigh": {"reasoning_effort": "xhigh"},
                    "max": {"reasoning_effort": "max"}, "off": {"reasoning_effort": "none"}}
