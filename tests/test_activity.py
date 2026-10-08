"""Tests for Real-Time Activity Tracking and Command Status."""
from fastapi.testclient import TestClient
import pytest

from colony.app import app
from colony.core import activity
from colony.schemas import MessageResponse

client = TestClient(app)


def test_activity_lifecycle():
    ws_id = "test_act_ws"

    # Initially idle
    act = activity.get_activity(ws_id)
    assert act["active"] is False
    assert act["step"] == "idle"

    # Set routing step
    activity.set_activity(
        ws_id,
        step="routing",
        detail="Routing intent via Nemotron-3-nano...",
    )
    act = activity.get_activity(ws_id)
    assert act["active"] is True
    assert act["step"] == "routing"
    assert "Nemotron-3-nano" in act["detail"]

    # Set tool call with command
    activity.set_activity(
        ws_id,
        step="tool_call",
        detail="Coder is running bash_command...",
        command="bash_command git status",
        agent_name="Coder",
        model="gpt-oss:120b",
    )
    activity.add_action(ws_id, "ran `git status`")

    act = activity.get_activity(ws_id)
    assert act["step"] == "tool_call"
    assert act["command"] == "bash_command git status"
    assert act["agent_name"] == "Coder"
    assert act["model"] == "gpt-oss:120b"
    assert act["actions"] == ["ran `git status`"]

    # Clear activity
    activity.clear_activity(ws_id)
    act_cleared = activity.get_activity(ws_id)
    assert act_cleared["active"] is False


def test_activity_api_endpoint():
    ws_id = "local"
    activity.set_activity(
        ws_id,
        step="thinking",
        detail="Nemotron 3 Super is reasoning...",
        command="read_file colony/config.py",
        agent_name="Researcher",
    )

    res = client.get(f"/api/activity?workspace_id={ws_id}")
    assert res.status_code == 200
    data = res.json()
    assert data["active"] is True
    assert data["step"] == "thinking"
    assert data["command"] == "read_file colony/config.py"
    assert data["agent_name"] == "Researcher"

    activity.clear_activity(ws_id)
