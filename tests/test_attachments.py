"""Attached files, and the agents that can (or can't) read them; workspace modes."""
import base64

from fastapi.testclient import TestClient

from colony.app import app
from colony.config import get_settings
from colony.engine import openclaw
from colony.core.agents import ToolAccess, apply_mode

client = TestClient(app)
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")

def upload(name, raw, workspace="local"):
    return client.post(f"/api/workspaces/{workspace}/attachments", json={"name": name, "data": base64.b64encode(raw).decode()})


def live(monkeypatch, *roles):
    """Real (non-mock) mode with a fake OpenClaw: returns the list of turns it was asked to run."""
    monkeypatch.setenv("MOCK_MODE", "false")
    get_settings.cache_clear()
    monkeypatch.setattr(openclaw, "is_openclaw_available", lambda s=None: True)
    team = [{"id": r, "name": r.title(), "model": "ollama/gemma4:31b", "when": "anything", "instructions": ""} for r in roles]
    assert client.put("/api/roles", json={"roles": team}).status_code == 200
    sent = []

    def fake_turn(**kw):
        sent.append(kw)
        return openclaw.OpenClawTurnResult(reply="ok", model=kw["role_model"], session_user="ome-test")

    monkeypatch.setattr(openclaw, "run_openclaw_turn", fake_turn)
    monkeypatch.setattr(openclaw, "mark_seen", lambda *a: None)
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


def test_text_files_are_pasted_into_the_message(monkeypatch):
    sent = live(monkeypatch, "writer")
    ref = upload("todo.md", b"buy milk").json()
    client.post("/api/messages", json={"message": "what is in it?", "attachments": [ref["id"]]})
    text = sent[0]["user_message"]
    assert "what is in it?" in text and "buy milk" in text and sent[0]["media"] == []


def test_images_travel_as_media_with_the_new_message(monkeypatch):
    sent = live(monkeypatch, "vision")
    ref = upload("pic.png", PNG).json()
    reply = client.post("/api/messages", json={"message": "what is this?", "attachments": [ref["id"]]}).json()
    assert reply["role_id"] == "vision"
    assert [m["name"] for m in sent[0]["media"]] == ["pic.png"] and "[Attached image: pic.png]" in sent[0]["user_message"]


def test_files_openclaw_cannot_read_are_refused_with_a_reason(monkeypatch):
    sent = live(monkeypatch, "vision")
    ref = upload("clip.mp4", b"\x00\x00\x00\x18ftypmp42").json()
    reply = client.post("/api/messages", json={"message": "summarise", "attachments": [ref["id"]]}).json()["reply"]
    assert reply.startswith("⚠️") and "video" in reply and "images, PDFs and text files" in reply
    assert sent == [] and client.get("/api/workspaces/local/messages").json()["messages"] == []


def test_only_the_newest_files_are_sent_in_full(monkeypatch):
    sent = live(monkeypatch, "vision")
    for i in range(4):
        ref = upload(f"p{i}.png", PNG).json()
        client.post("/api/messages", json={"message": f"n{i}", "role_id": "vision", "attachments": [ref["id"]]})
    history = " ".join(m["content"] for m in sent[-1]["history"])
    assert "p0.png — sent earlier and not repeated" in history and "[Attached image: p3.png]" not in history   # the new one is in user_message
    assert "[Attached image: p1.png]" in history and "[Attached image: p2.png]" in history


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


