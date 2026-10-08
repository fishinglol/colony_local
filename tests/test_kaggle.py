"""Agents on the user's own Kaggle server: model ids "kaggle/<name>" go to KAGGLE_BASE_URL instead of OpenRouter."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from colony.app import app
from colony.config import Settings, get_settings
from colony.core import chat
from colony.core.context import context_window
from colony.core.errors import explain
from colony.llm.http import ProviderError
from colony.llm.providers import complete_chat, generate_openrouter_reply

client = TestClient(app)
BUDDY = {"id": "buddy", "name": "Buddy", "model": "kaggle/qwen3:8b", "when": "chat", "instructions": ""}


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _json(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._json(200, {"object": "list", "data": [{"id": "qwen3:8b"}, {"id": "gemma3:12b"}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append({"path": self.path, "body": body, "auth": self.headers.get("Authorization")})
        if body["model"] == "missing":
            return self._json(404, {"error": {"message": "model 'missing' not found"}})
        self._json(200, {"model": body["model"], "choices": [{"message": {"role": "assistant", "content": "hi from kaggle"}}],
                         "usage": {"prompt_tokens": 7, "completion_tokens": 3}})


@pytest.fixture
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    srv.requests = []
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()


def url(srv):
    return f"http://127.0.0.1:{srv.server_address[1]}/v1"


def test_a_kaggle_model_goes_to_the_kaggle_server_without_openrouter_fields(server):
    settings = Settings(kaggle_base_url=url(server), openrouter_api_key=None)
    result = generate_openrouter_reply(settings=settings, message="hey", model_hint="kaggle/qwen3:8b",
                                       reasoning={"effort": "high"}, web_search=True)
    sent = server.requests[-1]
    assert result.text == "hi from kaggle"
    assert sent["path"] == "/v1/chat/completions" and sent["body"]["model"] == "qwen3:8b"
    assert "reasoning" not in sent["body"] and "plugins" not in sent["body"] and sent["auth"] is None


def test_background_jobs_can_use_a_kaggle_model(server):
    settings = Settings(kaggle_base_url=url(server), openrouter_routing_model="kaggle/gemma3:12b", openrouter_api_key="sk-or")
    assert complete_chat(settings=settings, system_prompt="s", user_prompt="u") == "hi from kaggle"
    assert server.requests[-1]["body"]["model"] == "gemma3:12b"


def test_kaggle_without_a_url_or_a_missing_model_explains_what_to_do(server):
    with pytest.raises(ProviderError) as missing_url:
        generate_openrouter_reply(settings=Settings(kaggle_base_url=None), message="x", model_hint="kaggle/qwen3:8b")
    assert "Settings" in explain(missing_url.value, "kaggle/qwen3:8b")
    with pytest.raises(ProviderError) as missing_model:
        generate_openrouter_reply(settings=Settings(kaggle_base_url=url(server), chat_retries=0), message="x", model_hint="kaggle/missing")
    assert "MODELS" in explain(missing_model.value, "kaggle/missing")
    assert "notebook" in explain(ProviderError("down", status=530), "kaggle/qwen3:8b")


def test_kaggle_models_use_the_notebooks_context_size():
    assert context_window("kaggle/qwen3:8b", Settings(kaggle_context_window=8192)) == 8192


def test_chatting_with_a_kaggle_agent_needs_no_openrouter_key(server, monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "false")
    monkeypatch.setenv("KAGGLE_BASE_URL", url(server))
    get_settings.cache_clear()
    monkeypatch.setattr(chat, "input_modalities", lambda model, settings: None)
    monkeypatch.setattr(chat.memory, "maybe_review_in_background", lambda *a: None)
    client.put("/api/roles", json={"roles": [BUDDY]})
    reply = client.post("/api/messages", json={"message": "hello", "role_id": "buddy"}).json()
    assert reply["reply"] == "hi from kaggle"
    assert server.requests[-1]["body"]["messages"][-1] == {"role": "user", "content": "hello"}


def test_settings_store_the_kaggle_url_and_the_picker_lists_its_models(server, monkeypatch, tmp_path):
    from colony import config
    monkeypatch.setattr(config, "_ENV_FILE", tmp_path / ".env")
    assert client.post("/api/settings", json={"kaggle_base_url": url(server)[:-3] + "/"}).status_code == 200
    assert f"KAGGLE_BASE_URL={url(server)}" in (tmp_path / ".env").read_text()
    assert client.post("/api/settings", json={"kaggle_base_url": "ftp://nope"}).status_code == 400

    monkeypatch.setenv("MOCK_MODE", "false")
    monkeypatch.setenv("KAGGLE_BASE_URL", url(server))
    get_settings.cache_clear()
    monkeypatch.setattr("colony.api.agents.model_catalog", lambda settings: {})
    models = client.get("/api/models").json()["models"]
    assert [m["id"] for m in models[:2]] == ["kaggle/qwen3:8b", "kaggle/gemma3:12b"]
    assert models[0]["provider_name"] == "Kaggle (your GPU)"


def test_tool_agents_on_kaggle_run_through_pi_against_the_kaggle_server(tmp_path):
    from colony.core.agents import ToolAccess
    from colony.engine import pi as engine
    from .fake_llm import FakeModelServer
    if not engine.find_pi(Settings()):
        pytest.skip("pi-runtime not installed")
    srv = FakeModelServer()
    try:
        workspace = tmp_path / "ws"
        workspace.mkdir()
        settings = Settings(kaggle_base_url=srv.base_url, openrouter_api_key=None, data_dir=tmp_path, tools_turn_timeout_seconds=90.0)
        result = engine.run_turn(settings=settings, model="kaggle/qwen3:8b", system_prompt="You are Coder.",
                                 prompt="WRITE k.txt from-kaggle", workspace=workspace,
                                 tools=ToolAccess(read="allow", write="allow"), approve=lambda tool, what: True)
        assert (workspace / "k.txt").read_text() == "from-kaggle" and result.actions == ["wrote k.txt"]
        assert srv.requests[0]["model"] == "qwen3:8b"
    finally:
        srv.shutdown()


def test_a_500_from_the_kaggle_server_blames_the_model_not_the_notebook():
    from colony.core.errors import explain
    msg = explain(ProviderError("boom", status=500), "kaggle/ornith:9b")
    assert "ornith:9b" in msg and "GPU" in msg and "หยุดไปแล้ว" not in msg
