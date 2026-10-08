from fastapi.testclient import TestClient

from colony.core import chat
from colony.config import get_settings
from colony.app import app
from colony.llm.providers import ProviderResult

client = TestClient(app)

CUSTOM = [
    {"id": "coder", "name": "Coder", "model": "anthropic/claude-sonnet-4.6",
     "when": "Code questions", "instructions": "Answer with code first."},
    {"id": "friend", "name": "Friend", "model": "openai/gpt-5.5",
     "when": "Everything else", "instructions": ""},
]


def test_roles_default_then_custom_roundtrip():
    assert [r["id"] for r in client.get("/api/roles").json()["roles"]] == ["reasoning", "chitchat", "writing", "coding"]
    assert client.put("/api/roles", json={"roles": CUSTOM}).status_code == 200
    saved = client.get("/api/roles").json()["roles"]
    assert [{k: v for k, v in r.items() if k not in ("tools", "reasoning", "web_search")} for r in saved] == CUSTOM
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
    assert client.post("/api/settings", json={"openrouter_api_key": "sk-1\nMOCK_MODE=false"}).status_code == 400


def test_remember_marker_saves_memory_now_and_is_hidden(monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "false")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    get_settings.cache_clear()
    seen = {}

    def fake_reply(**kwargs):
        seen.update(kwargs)
        return ProviderResult(text="Got it!\nMEMORY_SAVE: My dog is named Kaprao.", model="openai/gpt-5.5")

    monkeypatch.setattr(chat, "generate_openrouter_reply", fake_reply)
    monkeypatch.setattr(chat.memory, "maybe_review_in_background", lambda *a: None)
    body = client.post("/api/messages", json={"message": "remember my dog is Kaprao", "role_id": "chitchat"}).json()

    assert body["reply"] == "Got it!"
    assert body["memory_saved"] is True
    assert seen["role_name"] == "Buddy" and seen["role_instructions"]
    assert "Kaprao" in chat.memory.learned_context("local", query="dog Kaprao")


def test_split_memory_marker_leaves_normal_replies_alone():
    assert chat.split_memory_marker("hello\nworld") == ("hello\nworld", None)
    assert chat.split_memory_marker("ok\n**MEMORY_SAVE: likes tea**") == ("ok", "likes tea")


def test_models_endpoint_feeds_the_dropdown():
    models = client.get("/api/models").json()["models"]
    assert all({"id", "provider", "label", "note"} <= set(m) for m in models)
    assert "perplexity/sonar" in [m["id"] for m in models]


def test_agent_can_use_any_openrouter_model_not_in_the_dropdown():
    custom = [{**CUSTOM[0], "model": "mistralai/mistral-large"}]
    assert client.put("/api/roles", json={"roles": custom}).status_code == 200
    assert client.get("/api/roles").json()["roles"][0]["model"] == "mistralai/mistral-large"


def test_user_can_drop_all_default_agents_for_their_own():
    mine = [
        {"id": "research", "name": "Research", "model": "perplexity/sonar", "when": "Look things up", "instructions": ""},
        {"id": "slides", "name": "Presentation", "model": "anthropic/claude-sonnet-4.6", "when": "Slide decks", "instructions": ""},
    ]
    client.put("/api/roles", json={"roles": mine})
    body = client.post("/api/messages", json={"message": "make slides", "role_id": "slides"}).json()
    assert (body["role_name"], body["model"]) == ("Presentation", "anthropic/claude-sonnet-4.6")


def test_pool_is_clean_and_grouped_for_the_dropdown():
    models = client.get("/api/models").json()["models"]
    ids = [m["id"] for m in models]
    assert len(ids) == len(set(ids))
    assert all(m["id"].startswith(m["provider"] + "/") for m in models)
    assert {"OpenAI", "DeepSeek", "Moonshot AI (Kimi)"} <= {m["provider_name"] for m in models}
    assert {"anthropic/claude-sonnet-5", "openai/gpt-6-sol", "moonshotai/kimi-k3"} <= set(ids)


def test_temperature_is_only_sent_to_models_that_accept_it(monkeypatch):
    from colony.llm import providers

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    get_settings.cache_clear()
    sent = {}

    def fake(url, payload, headers, timeout, provider_name, retries=1):
        sent.update(payload)
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(providers, "post_json", fake)
    for model, expect in [("anthropic/claude-sonnet-5", False), ("anthropic/claude-opus-5.5", True),
                          ("some-lab/brand-new-model", False)]:
        sent.clear()
        providers.generate_openrouter_reply(settings=get_settings(), message="hi", model_hint=model)
        assert ("temperature" in sent) is expect, model


def test_messages_are_tagged_with_the_room_they_were_typed_in():
    client.put("/api/roles", json={"roles": CUSTOM})
    group = client.post("/api/messages", json={"message": "hi all"}).json()          # group chat: Jev/fallback picks
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


def test_rooms_only_change_what_is_shown_every_agent_still_sees_everything(monkeypatch):
    from colony.llm import providers

    sent = []
    monkeypatch.setenv("MOCK_MODE", "false")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    get_settings.cache_clear()
    monkeypatch.setattr(chat.memory, "maybe_review_in_background", lambda *a: None)
    monkeypatch.setattr(providers, "post_json", lambda url, payload, *a, **k: (sent.append(payload["messages"]) or
                        {"model": payload["model"], "choices": [{"message": {"content": "ok"}}]}))
    client.put("/api/roles", json={"roles": CUSTOM})
    first = client.post("/api/messages", json={"message": "secret plan: launch on Friday", "role_id": "friend"}).json()  # a direct chat
    client.post("/api/messages", json={"message": "what's the plan?", "role_id": "coder"})  # a different room
    seen_by_coder = " ".join(m["content"] for m in sent[-1])
    assert "launch on Friday" in seen_by_coder


def test_model_picker_list_has_suggestions_first_then_the_whole_catalog_with_capabilities(monkeypatch):
    from colony.core import context

    monkeypatch.setenv("MOCK_MODE", "false")
    get_settings.cache_clear()
    monkeypatch.setattr(context, "_live_windows", {})
    monkeypatch.setattr(context, "_live_tools", {})
    monkeypatch.setattr(context, "_live_info", {})
    monkeypatch.setattr(context, "_live_fetched_at", 0.0)
    monkeypatch.setattr(context, "get_json", lambda *a, **k: {"data": [
        {"id": "google/gemini-3.8-flash", "name": "Google: Gemini 3.8 Flash", "context_length": 1_048_576,
         "architecture": {"input_modalities": ["text", "image", "video"]}, "supported_parameters": ["tools", "reasoning"],
         "reasoning": {"mandatory": True, "default_effort": "medium", "supported_efforts": ["high", "medium", "low", "none"]}},
        {"id": "acme/vision-1:free", "name": "Acme: Vision 1 (free)", "context_length": 32_000,
         "architecture": {"input_modalities": ["text", "image"]}, "supported_parameters": ["max_tokens"]},
        {"id": "solo/no-colon", "name": "Plain Name", "context_length": 8000}]})
    models = {m["id"]: m for m in client.get("/api/models").json()["models"]}
    body = client.get("/api/models").json()
    first = body["models"]
    assert body["catalog"] is True
    assert first[0]["suggested"] and [m["id"] for m in first if not m["suggested"]] == ["acme/vision-1:free", "solo/no-colon"]   # ours first, the rest by id

    gemini = models["google/gemini-3.8-flash"]                       # one of ours: capabilities filled from the catalog
    assert gemini["suggested"] and gemini["capabilities"] == {
        "tools": True, "inputs": ["text", "image", "video"], "reasoning": True, "context": 1_048_576,
        "reasoning_levels": {"efforts": ["low", "medium", "high"], "default": "medium", "can_turn_off": False}}   # "none" is not a level
    acme = models["acme/vision-1:free"]
    assert (acme["provider_name"], acme["label"], acme["note"], acme["suggested"]) == ("Acme", "Vision 1 (free)", "Free", False)
    assert acme["capabilities"]["tools"] is False and acme["capabilities"]["reasoning"] is False
    assert acme["capabilities"]["reasoning_levels"] is None
    plain = models["solo/no-colon"]
    assert plain["provider_name"] == "solo" and plain["label"] == "Plain Name"
    assert plain["capabilities"]["inputs"] is None and plain["capabilities"]["tools"] is None      # the catalog didn't say


def test_model_picker_list_still_works_without_the_catalog():
    body = client.get("/api/models").json()                           # mock mode: no network
    models = body["models"]
    assert body["catalog"] is False
    assert all(m["suggested"] for m in models)
    assert all(set(m["capabilities"]) == {"tools", "inputs", "reasoning", "reasoning_levels", "context"} for m in models)
    sonnet = next(m for m in models if m["id"] == "anthropic/claude-sonnet-5")
    assert sonnet["capabilities"]["context"] == 1_000_000 and sonnet["capabilities"]["inputs"] is None


def test_model_picker_sources_categorization():
    body = client.get("/api/models").json()
    models = body["models"]
    ollama_models = [m for m in models if m.get("source") == "ollama"]
    openrouter_models = [m for m in models if m.get("source") == "openrouter"]

    assert len(ollama_models) >= 6
    assert any(m["id"] == "ollama/nemotron-3-nano:30b" for m in ollama_models)
    assert any(m["id"] == "ollama/gpt-oss:120b" for m in ollama_models)
    for om in ollama_models:
        assert om["source_label"] == "Ollama API"
        assert om["provider"] == "ollama"

    assert len(openrouter_models) >= 5
    for or_m in openrouter_models:
        assert or_m["source_label"] == "OpenRouter"

