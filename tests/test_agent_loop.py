"""Tests for Local Tools Execution, Workspace Fencing, and Multi-Turn Agent Loop."""
from pathlib import Path
import pytest

from colony.config import Settings
from colony.core.approvals import approvals
from colony.core import local_tools
from colony.core.agent_loop import run_agent_loop
from colony.llm import ollama


def test_safe_path_fencing(tmp_path):
    project_dir = tmp_path / "workspace"
    project_dir.mkdir()

    # Valid relative paths inside folder
    p1 = local_tools._safe_path(project_dir, "file.txt")
    assert p1 == project_dir / "file.txt"

    p2 = local_tools._safe_path(project_dir, "sub/dir/file.txt")
    assert p2 == project_dir / "sub/dir/file.txt"

    # Path traversal attack attempting to escape project folder
    with pytest.raises(PermissionError):
        local_tools._safe_path(project_dir, "../outside.txt")

    with pytest.raises(PermissionError):
        local_tools._safe_path(project_dir, "/etc/passwd")


def test_read_file_tool(tmp_path):
    f = tmp_path / "hello.txt"
    f.write_text("Hello, World!", encoding="utf-8")

    out, action = local_tools.execute_local_tool(
        tool_name="read_file",
        args={"path": "hello.txt"},
        folder=tmp_path,
        agent_name="Coder",
    )
    assert out == "Hello, World!"
    assert action is None

    # Non-existent file
    out_missing, _ = local_tools.execute_local_tool(
        tool_name="read_file",
        args={"path": "missing.txt"},
        folder=tmp_path,
        agent_name="Coder",
    )
    assert "does not exist" in out_missing


def test_write_file_with_approval(tmp_path, monkeypatch):
    # Mock approval to accept
    monkeypatch.setattr(approvals, "ask", lambda **kw: True)

    out, action = local_tools.execute_local_tool(
        tool_name="write_file",
        args={"path": "test.txt", "content": "colony-local rocks"},
        folder=tmp_path,
        agent_name="Coder",
    )
    assert (tmp_path / "test.txt").read_text(encoding="utf-8") == "colony-local rocks"
    assert "Successfully wrote" in out
    assert action == "wrote test.txt"


def test_write_file_denied_by_user(tmp_path, monkeypatch):
    # Mock approval to deny
    monkeypatch.setattr(approvals, "ask", lambda **kw: False)

    out, action = local_tools.execute_local_tool(
        tool_name="write_file",
        args={"path": "denied.txt", "content": "should not exist"},
        folder=tmp_path,
        agent_name="Coder",
    )
    assert not (tmp_path / "denied.txt").exists()
    assert "User denied permission" in out
    assert action is None


def test_edit_file_tool(tmp_path, monkeypatch):
    monkeypatch.setattr(approvals, "ask", lambda **kw: True)
    f = tmp_path / "sample.py"
    f.write_text("def run():\n    return 1\n", encoding="utf-8")

    out, action = local_tools.execute_local_tool(
        tool_name="edit_file",
        args={"path": "sample.py", "old_text": "return 1", "new_text": "return 42"},
        folder=tmp_path,
        agent_name="Coder",
    )
    assert f.read_text(encoding="utf-8") == "def run():\n    return 42\n"
    assert "Successfully edited" in out
    assert action == "edited sample.py"


def test_bash_command_tool(tmp_path, monkeypatch):
    monkeypatch.setattr(approvals, "ask", lambda **kw: True)

    out, action = local_tools.execute_local_tool(
        tool_name="bash_command",
        args={"command": "echo 'running bash in colony'"},
        folder=tmp_path,
        agent_name="Coder",
    )
    assert "running bash in colony" in out
    assert action == "ran `echo 'running bash in colony'`"


def test_run_agent_loop_single_turn_no_tools(tmp_path, monkeypatch):
    settings = Settings()

    def fake_chat(**kw):
        return ollama.OllamaReply(
            text="I can assist you directly without tools.",
            model="gpt-oss:20b",
            tool_calls=[],
        )

    monkeypatch.setattr("colony.core.agent_loop.generate_ollama_chat", fake_chat)

    outcome = run_agent_loop(
        model="gpt-oss:20b",
        messages=[{"role": "user", "content": "hello"}],
        settings=settings,
        folder=tmp_path,
        agent_name="Assistant",
    )

    assert outcome.reply == "I can assist you directly without tools."
    assert outcome.actions == []


def test_run_agent_loop_executes_tool_and_replies(tmp_path, monkeypatch):
    settings = Settings()
    (tmp_path / "notes.txt").write_text("Secret notes content", encoding="utf-8")

    turns = [
        # Turn 1: Model requests tool call
        ollama.OllamaReply(
            text="Checking notes...",
            model="nemotron-3-super",
            tool_calls=[
                ollama.OllamaToolCall(
                    id="call_1",
                    name="read_file",
                    arguments={"path": "notes.txt"},
                )
            ],
        ),
        # Turn 2: Model finishes with final answer after receiving tool response
        ollama.OllamaReply(
            text="The notes contain: Secret notes content",
            model="nemotron-3-super",
            tool_calls=[],
        ),
    ]

    call_count = 0

    def fake_chat(**kw):
        nonlocal call_count
        res = turns[call_count]
        call_count += 1
        return res

    monkeypatch.setattr("colony.core.agent_loop.generate_ollama_chat", fake_chat)

    outcome = run_agent_loop(
        model="nemotron-3-super",
        messages=[{"role": "user", "content": "Read my notes"}],
        settings=settings,
        folder=tmp_path,
        agent_name="Researcher",
    )

    assert call_count == 2
    assert outcome.reply == "The notes contain: Secret notes content"
