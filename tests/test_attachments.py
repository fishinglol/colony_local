"""Attached files, and the agents that can (or can't) read them; workspace modes."""
import base64

from fastapi.testclient import TestClient

from colony.app import app
from colony.config import get_settings
from colony.core import chat, context
from colony.core.agents import ToolAccess, apply_mode
from colony.engine.pi import PiResult
from colony.llm import providers

client = TestClient(app)
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")

CATALOG = {"data": [
    {"id": "acme/text-only", "name": "Text Only", "context_length": 100_000, "supported_parameters": ["tools"],
     "architecture": {"input_modalities": ["text"]}},
    {"id": "acme/vision", "name": "Vision", "context_length": 100_000, "supported_parameters": ["tools"],
     "architecture": {"input_modalities": ["text", "image", "file"]}},
    {"id": "acme/video", "name": "Video", "context_length": 100_000, "supported_parameters": ["tools"],
     "architecture": {"input_modalities": ["text", "image", "video"]}},
]}


def upload(name, raw, workspace="local"):
    return client.post(f"/api/workspaces/{workspace}/attachments", json={"name": name, "data": base64.b64encode(raw).decode()})


def live(monkeypatch, *models):
    monkeypatch.setenv("MOCK_MODE", "false")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    get_settings.cache_clear()
    for name, empty in (("_live_windows", {}), ("_live_tools", {}), ("_live_info", {}), ("_live_fetched_at", 0.0)):
        monkeypatch.setattr(context, name, empty)
    monkeypatch.setattr(context, "get_json", lambda *a, **k: CATALOG)
    monkeypatch.setattr(chat.memory, "maybe_review_in_background", lambda *a: None)
    team = [{"id": mid.split("/")[1], "name": mid.split("/")[1].title(), "model": mid, "when": "anything", "instructions": ""} for mid in models]
    assert client.put("/api/roles", json={"roles": team}).status_code == 200
    sent = []
    monkeypatch.setattr(providers, "post_json", lambda url, payload, *a, **k: (sent.append(payload) or
                        {"model": payload["model"], "choices": [{"message": {"content": "ok"}}]}))
    return sent


def test_upload_saves_the_file_and_gives_it_back():
    ref = upload("notes.txt", b"hello").json()
    assert (ref["name"], ref["kind"], ref["size"]) == ("notes.txt", "text", 5)
    got = client.get(f"/api/workspaces/local/attachments/{ref['id']}")
    assert got.status_code == 200 and got.content == b"hello"
    assert upload("pic.png", PNG).json()["kind"] == "image"
    assert client.get("/api/workspaces/local/attachments/nope").status_code == 404
    assert client.get("/api/workspaces/local/attachments/" + "0" * 32).status_code == 404


def test_uploads_that_cannot_work_are_refused_with_a_reason(monkeypatch):
    monkeypatch.setenv("MAX_ATTACHMENT_MB", "1")
    get_settings.cache_clear()
    assert "bigger than 1 MB" in upload("big.txt", b"a" * (1024 * 1024 + 1)).json()["detail"]
    assert "isn't a kind of file" in upload("program.bin", b"\x00\x01\x02\xff").json()["detail"]
    assert upload("empty.txt", b"").status_code == 400
    assert upload("x.txt", b"x", workspace="nope").status_code == 404
    assert client.post("/api/workspaces/local/attachments", json={"name": "x.txt", "data": "!!!not base64"}).status_code == 400


def test_a_message_keeps_its_attachments_and_a_file_alone_is_enough():
    ref = upload("notes.txt", b"hello").json()
    reply = client.post("/api/messages", json={"attachments": [ref["id"]]}).json()
    assert "[+1 file(s)]" in reply["reply"]
    user = [m for m in client.get("/api/workspaces/local/messages").json()["messages"] if m["role"] == "user"][0]
    assert [a["name"] for a in user["attachments"]] == ["notes.txt"] and user["content"]
    assert client.post("/api/messages", json={}).status_code == 422
    assert "no longer there" in client.post("/api/messages", json={"message": "x", "attachments": ["0" * 32]}).json()["reply"]


def test_text_files_are_pasted_into_the_message_for_any_model(monkeypatch):
    sent = live(monkeypatch, "acme/text-only")
    ref = upload("todo.md", b"buy milk").json()
    client.post("/api/messages", json={"message": "what is in it?", "attachments": [ref["id"]]})
    content = sent[0]["messages"][-1]["content"]
    assert isinstance(content, str) and "what is in it?" in content and "buy milk" in content


def test_images_go_only_to_models_that_read_them_and_jev_only_chooses_among_them(monkeypatch):
    sent = live(monkeypatch, "acme/text-only", "acme/vision")
    ref = upload("pic.png", PNG).json()
    seen = []
    monkeypatch.setattr(chat, "decide", lambda **kw: seen.append([r.id for r in kw["roles"]]) or __import__("colony.core.decider", fromlist=["x"]).DeciderResult(kw["roles"][0], 1.0, "jev"))
    reply = client.post("/api/messages", json={"message": "what is this?", "attachments": [ref["id"]]}).json()
    assert seen == [["vision"]] and reply["role_id"] == "vision"          # Jev never sees the agent that can't read it
    parts = sent[0]["messages"][-1]["content"]
    assert parts[0]["type"] == "text" and parts[1]["type"] == "image_url" and parts[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_a_direct_message_to_an_agent_that_cannot_read_the_file_says_so_in_english(monkeypatch):
    sent = live(monkeypatch, "acme/text-only", "acme/vision")
    ref = upload("pic.png", PNG).json()
    reply = client.post("/api/messages", json={"message": "look", "role_id": "text-only", "attachments": [ref["id"]]}).json()["reply"]
    assert "can't read images" in reply and "Ask Vision instead" in reply
    assert sent == []                                                     # nothing was sent to a model
    assert client.get("/api/workspaces/local/messages").json()["messages"] == []


def test_when_nobody_can_read_a_file_the_user_is_told_what_to_change(monkeypatch):
    sent = live(monkeypatch, "acme/text-only", "acme/vision")
    ref = upload("clip.mp4", b"\x00\x00\x00\x18ftypmp42").json()
    reply = client.post("/api/messages", json={"message": "summarise", "attachments": [ref["id"]]}).json()["reply"]
    assert reply.startswith("⚠️ None of the agents in this workspace can read video") and "clip.mp4" in reply and "Inputs" in reply
    assert sent == []


def test_a_model_that_cannot_see_an_old_image_is_told_it_existed(monkeypatch):
    sent = live(monkeypatch, "acme/text-only", "acme/vision")
    ref = upload("pic.png", PNG).json()
    client.post("/api/messages", json={"message": "what is this?", "role_id": "vision", "attachments": [ref["id"]]})
    client.post("/api/messages", json={"message": "and your view, text model?", "role_id": "text-only"})
    history = sent[1]["messages"]
    old = [m for m in history if isinstance(m["content"], str) and "pic.png" in m["content"]]
    assert old and "this model can't read images" in old[0]["content"]
    assert not any(isinstance(m["content"], list) for m in history)      # no image went to the text model


def test_only_the_newest_files_are_sent_in_full(monkeypatch):
    sent = live(monkeypatch, "acme/vision")
    for i in range(4):
        ref = upload(f"p{i}.png", PNG).json()
        client.post("/api/messages", json={"message": f"n{i}", "role_id": "vision", "attachments": [ref["id"]]})
    last = sent[-1]["messages"]
    images = sum(1 for m in last if isinstance(m["content"], list) for p in m["content"] if p["type"] == "image_url")
    assert images == 3
    assert any("p0.png" in m["content"] and "not repeated" in m["content"] for m in last if isinstance(m["content"], str))


def test_tool_agents_get_images_through_pi_but_not_other_media(monkeypatch, tmp_path):
    live(monkeypatch, "acme/vision")
    (tmp_path / "project").mkdir()
    client.patch("/api/workspaces/local", json={"folder": str(tmp_path / "project")})
    client.put("/api/roles", json={"roles": [{"id": "vision", "name": "Vision", "model": "acme/vision", "when": "x", "tools": {"read": "allow"}}]})
    monkeypatch.setattr(chat, "supports_tools", lambda model, settings: True)
    seen = []
    monkeypatch.setattr(chat, "run_turn", lambda **kw: seen.append(kw["images"]) or PiResult("done", []))
    png = upload("pic.png", PNG).json()
    client.post("/api/messages", json={"message": "look", "attachments": [png["id"]]})
    assert seen[0][0]["type"] == "image" and seen[0][0]["mimeType"] == "image/png"
    pdf = upload("doc.pdf", b"%PDF-1.4").json()
    reply = client.post("/api/messages", json={"message": "read", "attachments": [pdf["id"]]}).json()["reply"]
    assert "gents that use tools can only read images and text files" in reply and len(seen) == 1


# ── modes ────────────────────────────────────────────────────────────────────────────────────

def test_modes_change_how_freely_an_agent_with_tools_may_act():
    tools = ToolAccess(read="allow", write="ask", bash="allow")
    assert apply_mode(tools, "auto") == tools
    assert apply_mode(tools, "manual") == ToolAccess(read="allow", write="ask", bash="ask")
    assert apply_mode(tools, "accept_edits") == ToolAccess(read="allow", write="allow", bash="ask")
    assert apply_mode(tools, "bypass") == ToolAccess(read="allow", write="allow", bash="allow")
    assert apply_mode(tools, "plan") == ToolAccess(read="allow", write="off", bash="off")
    only_read = ToolAccess(read="allow")
    assert apply_mode(only_read, "bypass") == only_read                  # a mode never switches on a tool the agent lacks
    none = ToolAccess()
    assert apply_mode(none, "plan") == none and not apply_mode(none, "plan").any_on


def test_the_mode_belongs_to_the_workspace_and_reaches_the_tools_engine(monkeypatch, tmp_path):
    live(monkeypatch, "acme/vision")
    (tmp_path / "project").mkdir()
    client.patch("/api/workspaces/local", json={"folder": str(tmp_path / "project")})
    client.put("/api/roles", json={"roles": [{"id": "vision", "name": "Vision", "model": "acme/vision", "when": "x",
                                              "tools": {"read": "allow", "write": "ask", "bash": "ask"}}]})
    monkeypatch.setattr(chat, "supports_tools", lambda model, settings: True)
    runs = []
    monkeypatch.setattr(chat, "run_turn", lambda **kw: runs.append((kw["tools"], kw["system_prompt"])) or PiResult("done", []))
    assert client.get("/api/workspaces").json()["workspaces"][0]["mode"] == "auto"
    assert client.patch("/api/workspaces/local", json={"mode": "plan"}).json()["mode"] == "plan"
    assert client.patch("/api/workspaces/local", json={"mode": "chaos"}).status_code == 422
    client.post("/api/messages", json={"message": "go"})
    assert runs[0][0] == ToolAccess(read="allow", write="off", bash="off") and "PLAN MODE" in runs[0][1]
    client.patch("/api/workspaces/local", json={"mode": "bypass"})
    client.post("/api/messages", json={"message": "go"})
    assert runs[1][0] == ToolAccess(read="allow", write="allow", bash="allow") and "PLAN MODE" not in runs[1][1]
