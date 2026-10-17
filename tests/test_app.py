from fastapi.testclient import TestClient

from colony.app import app

client = TestClient(app)

CUSTOM = [
    {"id": "coder", "name": "Coder", "model": "ollama/gpt-oss:120b",
     "when": "Code questions", "instructions": "Answer with code first."},
    {"id": "friend", "name": "Friend", "model": "ollama/gemma4:31b",
     "when": "Everything else", "instructions": ""},
]


def test_roles_default_then_custom_roundtrip():
    assert [r["id"] for r in client.get("/api/roles").json()["roles"]] == ["reasoning", "chitchat", "writing", "coding"]
    assert client.put("/api/roles", json={"roles": CUSTOM}).status_code == 200
    saved = client.get("/api/roles").json()["roles"]
    assert [{k: v for k, v in r.items() if k not in ("tools", "reasoning", "web_search", "accepts_handoff", "delegates")} for r in saved] == CUSTOM
    assert all(r["tools"] == {"read": "off", "write": "off", "bash": "off", "mcp": "off", "mcp_servers": None, "mcp_apps": []} for r in saved)  # tools are off unless switched on
    assert all(r["reasoning"] == "default" for r in saved)                                  # and reasoning is the model's own


def test_roles_validation():
    bad_model = [{**CUSTOM[0], "model": "sonnet"}]
    assert client.put("/api/roles", json={"roles": bad_model}).status_code == 422
    dup = [CUSTOM[0], {**CUSTOM[1], "id": "coder"}]
    assert client.put("/api/roles", json={"roles": dup}).status_code == 400
    assert client.put("/api/roles", json={"roles": []}).status_code == 400


def test_message_directly_to_a_role_and_history_is_shared():
    client.put("/api/roles", json={"roles": CUSTOM})
    first = client.post("/api/messages", json={"message": "fix my loop", "role_id": "coder"}).json()
    assert (first["role_name"], first["decided_by"], first["model"]) == ("Coder", "direct", CUSTOM[0]["model"])
    conv = first["workspace_id"]
    second = client.post("/api/messages", json={"message": "thanks", "role_id": "friend"}).json()
    assert second["role_name"] == "Friend"
    msgs = client.get(f"/api/workspaces/{conv}/messages").json()["messages"]
    assert [m["metadata"]["role_name"] for m in msgs if m["role"] == "assistant"] == ["Coder", "Friend"]


def test_settings_reject_multiline_key():
    assert client.post("/api/settings", json={"ollama_api_key": "k-1\nMOCK_MODE=false"}).status_code == 400


def test_models_endpoint_feeds_the_dropdown():
    body = client.get("/api/models").json()
    models = body["models"]
    ids = [m["id"] for m in models]
    assert len(ids) == len(set(ids)) and "ollama/gemma4:31b" in ids
    assert body["catalog"] is True
    for m in models:
        assert {"id", "provider", "label", "note"} <= set(m)
        assert m["source"] == "ollama" and m["source_label"] == "Ollama API"
        assert set(m["capabilities"]) == {"tools", "inputs", "reasoning", "reasoning_levels", "context"}


def test_agent_can_use_any_ollama_model_not_in_the_dropdown():
    custom = [{**CUSTOM[0], "model": "ollama/some-new-model:7b"}]
    assert client.put("/api/roles", json={"roles": custom}).status_code == 200
    assert client.get("/api/roles").json()["roles"][0]["model"] == "ollama/some-new-model:7b"


def test_messages_are_tagged_with_the_room_they_were_typed_in():
    client.put("/api/roles", json={"roles": CUSTOM})
    group = client.post("/api/messages", json={"message": "hi all"}).json()          # group chat: the decider/fallback picks
    assert group["channel"] == "auto"
    conv = group["workspace_id"]
    dm = client.post("/api/messages", json={"message": "just us", "role_id": "friend"}).json()
    assert dm["channel"] == "friend"
    asked = client.post("/api/messages", json={"message": "hi all", "role_id": "coder", "channel": "auto"}).json()
    assert asked["channel"] == "auto" and asked["role_id"] == "coder"  # "Ask another agent" from the group chat stays in it

    msgs = client.get(f"/api/workspaces/{conv}/messages").json()["messages"]
    rooms = [(m["role"], m["channel"] if m["role"] == "user" else m["metadata"]["channel"]) for m in msgs]
    assert rooms == [("user", "auto"), ("assistant", "auto"), ("user", "friend"), ("assistant", "friend"),
                     ("user", "auto"), ("assistant", "auto")]
