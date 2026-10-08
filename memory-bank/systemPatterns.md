# System Patterns — Colony Local

All paths are relative to the repo root (`~/Desktop/Colony-Local`; this used to be `local/` inside ColonyBridge — old
notes that say `local/x` mean `x`). Line counts as of 2026-09-29.

## File map
```
pyproject.toml            package "colony-local"; script `colony = colony.cli:main`; package-data web/* + engine/*.ts
colony/
  cli.py (107)            `colony` command: --port --host --no-open --reload --exit-with-parent; _start_laya() (local decider)
  app.py (95)             FastAPI app factory; mounts /api, serves web/ with Cache-Control: no-cache; run()
  config.py (125)         Settings (pydantic-settings, ~/.colony/.env); update_env_file()
  schemas.py (44)         MessageRequest (workspace_id, role_id, channel) / MessageResponse
  api/                    THIN routers, no logic. __init__.py mounts them under /api
    chat.py               /health /messages /context (all take/return workspace_id)
    workspaces.py         /workspaces (list, create, PATCH, DELETE) /workspaces/{id}/messages
    agents.py             /roles?workspace_id= (GET, PUT) /models (Kaggle server's models first, then catalog + capabilities) /models/test
    tools.py              /approvals (GET) /approvals/{id} (POST) /models/tools
    settings.py           /settings (GET, POST: OpenRouter key, Kaggle server URL)
    memory.py             /memory/summary /memory/context
    attachments.py        POST/GET /workspaces/{id}/attachments (JSON + base64 upload, no python-multipart)
    mcp.py                GET|PUT /mcp (connectors, secrets masked), POST /mcp/composio
    links.py              POST /open-url (open an http(s) link in the real browser)
  core/                   business logic
    chat.py (277)         handle_message(): decide -> plan history -> (Pi | plain chat) -> persist
    decider.py (86)       who answers in # mix: Laya (LAYA_URL) or Jev (OpenRouter) + visible fallback
    workspaces.py         Workspace store (~/.colony/workspaces.json): team, folder, create/copy/rename/delete, first-run migration
    agents.py             Role, ToolAccess, DEFAULT_ROLES, validate_roles (no storage: roles live in a workspace)
    context.py (145)      shared-context planning, token estimates, OpenRouter catalog cache, supports_tools
    models.py (88)        MODEL_POOL for the dropdown + per-model quirks
    errors.py             explain(): provider error -> Thai message (+ _kaggle_hint for kaggle/ models)
    approvals.py (56)     in-memory "may I do this?" questions (blocking ask, polled resolve)
    compaction.py         summary of the older part of a long conversation (background, Pi-style format)
    attachments.py        uploaded files: save/get/render per model (text pasted, media parts if the model reads them), unreadable()
    mcp.py                connectors: MCP server list (~/.colony/mcp-servers.json), masking, Composio preset
    project_folder.py     explicit folder agents with tools may use (per workspace; otherwise chat-only)
  engine/
    pi.py (249)           run_turn(): one agent turn through Pi RPC (OpenRouter or the Kaggle URL in models.json)
    colony-gate.ts        Pi extension: per-tool allow/ask/off + workspace fence + the `mcp` tool rules (looking is free, calls ask, install/sign-in refused)
  llm/
    http.py (140)         the ONE HTTP layer (retries, ProviderError)
    providers.py (276)    prompt building (system_messages/build_messages) + calls; _endpoint(): kaggle/ → Kaggle, else OpenRouter; OpenAI fallback
  memory/                 long-term memory (files, recall, review, safety)
  store/                  history.json + JsonStore (atomic JSON file)
  web/                    static UI: index.html, app.css, js/*.js (ES modules, no build step)
    js/ main.js (wiring) · state.js · api.js · dom.js · feed.js (messages, attachments in bubbles, summary note, approvals) · sidebar.js · workspaces.js (switcher,
        folder menu, Browse…) · agent-editor.js (Tools list + model/reasoning) · model-picker.js · reasoning.js · attachments.js (+ menu, drag/drop, paste, chips,
        "can't read" note) · mode.js (mode pill) · tool-picker.js (THE "Connect a tool" window: sidebar Connectors button and editor) · apps-catalog.js (97 apps + logo slugs)
        · links.js (open links in the real browser) · context.js (gauge) · settings.js · avatar.js · markdown.js
tests/                    pytest; conftest isolates every test (own DATA_DIR, MOCK_MODE)
desktop/                  Tauri 2 native window (src-tauri/src/main.rs), dist/index.html loading page
pi-runtime/               package.json pinning Pi + pi-mcp-adapter; `npm install` puts the `pi` binary here; colony-mcp.ts = isolated-config wrapper for the adapter
laya-runtime/             requirements.txt (Intel-Mac pins) + serve.py (runs laya-serve, dies when Colony's stdin closes); .venv (ignored)
kaggle/                   colony_server.py (+ .ipynb for Kaggle's File → Import): Ollama + models + cloudflared on a Kaggle GPU
spike-pi/                 throwaway experiment + evidence (README inside); run/ and node_modules are ignored
memory-bank/              these notes; docs/ = the original handoff log + restructure spec
```

## Key patterns

### 1. Layering: api → core → llm / store / memory / engine
Routers only validate and delegate. `core/chat.py::handle_message` is the one
orchestrator; nothing under `core/` imports from `api/`. Follows the repo's
"router / schemas / logic" rule. All config via `get_settings()`; never read
`os.environ` in handlers (the two deliberate exceptions: `cli.py` sets env before
settings load, `core/project_folder.py` reads `COLONY_LAUNCH_DIR`).

### 2. One HTTP layer (`llm/http.py`)
`post_json/get_json` → `_send`: certifi SSL context, retries on 429/5xx with
backoff `(1.5, 4, 8)` s, honours `Retry-After` (capped 15 s), raises
`ProviderError(message, status, provider_message)`. Chat replies use
`settings.chat_retries` (3); **Jev uses `retries=0`, 10 s timeout** so a slow
decider never stalls chat. `core/errors.explain()` maps status → Thai advice
(429 shared pool, 403 "agentic harness only" free models, 401, 402 credits,
400 context length, 400/404 unknown model, 5xx, network). Errors are shown but
**never persisted** into history.

### 3. Decider: Laya or Jev (`core/decider.py`)
One request shape for both (Jev's "System One" protocol): `state.message` + `questions.role` = a `choice` question
whose criteria are `{role_id: role.when}`. Response: `answers.role.{choice, confidence}` (NOT `decisions` — that bug
once made Jev never work).
- **Laya** (preferred; `LAYA_URL` set): `POST {LAYA_URL}/v1/systemone`, model `multilingual` (the checkpoint that reads
  Thai), no key. Open weights (Apache-2.0, ~322M, non-generative), runs on CPU on the owner's Mac. `cli._start_laya()`
  launches `laya-runtime/.venv/bin/python laya-runtime/serve.py` in its own session (port 8790, env LAYA_DEVICE=cpu,
  LAYA_MODELS=multilingual, LAYA_MAX_LOADED=1, LAYA_THREADS=2; log `~/.colony/laya.log`) with a stdin pipe it never
  closes, and sets `LAYA_URL`; `serve.py` kills its own process group when that pipe closes, so Laya dies with Colony
  even on SIGKILL (atexit alone left orphans — found by testing). Skipped if `LAYA_URL` is already set or no venv.
- **Jev** (`LAYA_URL` unset, OpenRouter key set): `POST https://openrouter.ai/api/alpha/decisions`, `typesafe/jev-1.13`.
- `decided_by` ∈ `laya | jev | direct | only_role | fallback`; `fallback` = first agent, the UI says
  "Jev/Laya unavailable". Direct chats (`role_id` set) skip the decider. `retries=0`, 10 s timeout.

### 3b. Workspaces (`core/workspaces.py`) — the top level
A **workspace** = its own team of agents (`roles`, each with its own model/tools), **one continuous
conversation**, its own memory, and its own project folder. The workspace id doubles as the conversation
id in `history.json` and as the memory "user" in `self_improve/<id>/`, so nothing else needed a new key.
There is no "new chat": a fresh context = a new workspace. Every API that reads or writes a team, messages,
context or memory takes `workspace_id` (omitted = the first workspace). `create_workspace` starts from the
default team or a **copy** of another workspace's agents (then they diverge). Deleting removes the
conversation and the memory folder; the last workspace can't be deleted. A damaged `workspaces.json` is
copied to `workspaces.json.corrupt-<ts>` before a new one is built.
**First run** (no `workspaces.json`): builds "Personal" with id `local` from the old files — agents from
`roles.json` (else defaults), project folder from the old `WORKSPACE_DIR`, **all old chats merged into one
timeline** (backup: `history.json.bak-before-workspaces`), memory in `self_improve/local/` stays put because
the id is the same. Runs once.

### 4. Shared context (`core/context.py`)
- Every agent gets the whole conversation of the workspace from `history.json`
  (`get_prompt_messages`), capped at `history_max_messages` (**60**; was 16 when a chat was short-lived).
- Assistant turns are labelled `[AgentName] …`; `_TEAM_NOTE` (in providers.py)
  tells the model they may be someone else's words and never to prefix its own
  reply (`strip_self_label` cleans stragglers).
- If the prompt would exceed 85 % (`FILL_LIMIT`) of the model's window minus
  `max_output_tokens`, the **oldest messages are dropped**. Window = our table
  (`PoolModel.context`) else OpenRouter's public `/models` catalog (cached 6 h,
  skipped in mock mode). Token counts are **estimates** (~4 chars/token ASCII,
  ~1.5 Thai/CJK) — a gauge, not billing.
- `/api/context` runs the same planning for every agent → the Context chip.
- **Rooms:** each exchange stores `channel` ("auto" or an agent id) on the user
  message and in the reply's metadata. Only the UI filters by it.

### 4b. OpenRouter catalog cache (`core/context.py`)
One cached fetch of the public `GET /models` (6 h TTL, 10 min retry after a failure, skipped in mock mode) feeds
everything model-specific: `context_window`, `supports_tools`, and `model_catalog()` = `{id: {name, context, tools,
inputs (modalities), reasoning}}`. `/api/models` returns our suggested list first (`suggested: true`) then every other
catalog model, each with `capabilities`, plus `catalog: bool` (False = OpenRouter unreachable, so capabilities are
unknown, not "none"). The picker says "may have been removed" for a suggested model the live catalog no longer lists
(seen for `z-ai/glm-5.2:free`). Colony still sends **text only**; the card says so for image/video/audio models.
Tests that patch the cache must patch `_live_windows`, `_live_tools`, `_live_info` and `_live_fetched_at`.

### 4c. Reasoning level (`Role.reasoning`, `core/context.py::reasoning_param`)
`Role.reasoning` = `default | off | minimal | low | medium | high | xhigh | max`. The catalog gives each model
`reasoning: {mandatory, supported_efforts, default_effort}` → `capabilities.reasoning_levels = {efforts (low→max),
default, can_turn_off}`. `reasoning_param(model, level, settings)` returns the OpenRouter field `{"effort": level}`
(`off` → `{"effort": "none"}`) or None for: default; a model the catalog says can't reason; a level the model lacks;
`off` on an always-on model. A model not in the catalog is trusted. Plain chat passes it as `reasoning=` to
`generate_openrouter_reply`; `/models/test` tests with the level being set. **Tool agents:** Pi gets `--thinking <level>`
and its generated model entry declares `reasoning: true` + a pass-through `thinkingLevelMap` — without them Pi
sent nothing, lowered xhigh/max to high and dropped `off` (verified against the fake model server, incl. in tests).
UI: `web/js/reasoning.js` (levels, sidebar menu), the pill in `sidebar.js`, level buttons in `agent-editor.js`;
the pills need the model list, so `openWorkspace` loads it in the background and re-renders.

### 4d. Attachments, capability filter, modes
Files live in `~/.colony/attachments/<workspace>/<id>` (+ `<id>.json`); a message stores small refs (`attachments` on the user
message). `core/attachments.py`: `kind_of` (by extension, else UTF-8 text, else refused), `unreadable(kinds, inputs, with_tools)`
(catalog `input_modalities`: image→image, pdf→file, video→video, audio→audio; unknown model = trusted; tool agents = image only),
`render` (per model: text pasted / media flagged / note "this model can't read X"), `with_parts`/`user_content` (turn refs into
chat-completions parts), `pi_images`. `context.plan_history` renders each history message for the model that will read it
(`Sight`) and keeps only the newest `KEEP_RECENT`=3 attachment messages in full. `chat.handle_message` filters candidate agents
BEFORE Jev (`decide` gets only capable roles); direct chat to an incapable agent, or nobody capable, returns an English notice
(not saved). Modes: `Workspace.mode`, `agents.apply_mode(tools, mode)` → effective ToolAccess (never enables a missing tool;
plan = read only + `PLAN_NOTE` in the system prompt). UI: `web/js/attachments.js`, `web/js/mode.js`.

### 4e. Compaction (`core/compaction.py`)
`view(workspace_id)` → `(summary | None, messages after the summarised part)`; used by `chat.handle_message` and `context.report`
(the gauge). `compact()` when est. tokens (summary + messages) > `compact_at_tokens`: `_cut()` keeps ~`compact_keep_tokens` of the
newest messages and moves the cut forward to a USER message; the older span is serialised as `[User]: … [Buddy]: …` (each message
capped at 6000 chars, 🛠 lines kept so the summary can list files), summarised in ≤60k-char chunks each updating the running summary
(`<previous-summary>` + `<conversation>`), passed through `memory.safety.sanitize` (an instruction-like summary is refused), saved with
`set_compaction`. The summary reaches models as a system message (`system_messages(..., earlier_summary)`), so it works for plain chat and
Pi alike. A summary whose `through_id` message no longer exists is ignored. Background thread + per-workspace guard + 5-min backoff.
Tests patch `compaction.complete_chat`.

### 4f. Web search, connectors (MCP), Composio
- `Role.web_search` → `generate_openrouter_reply(web_search=True)` adds `plugins:[WEB_PLUGIN]`; `_sources()` reads `annotations`; `chat._sources_block`
  appends "**Sources**". Tool agents: model id `+ ":online"` (Pi passes the id through). The OpenAI fallback ignores it.
- `ToolAccess.mcp`; `apply_mode`: manual/accept_edits → ask, bypass → allow, plan → off. `chat.effective_tools()` zeroes `mcp` when no server is enabled and,
  without a project folder, keeps ONLY `mcp` (file tools need a fenced folder). `run_turn(..., mcp_servers=)` writes `agent_dir/mcp-turn.json` (0600), adds
  `-e pi-runtime/colony-mcp.ts` and env `COLONY_MCP_FILE`; `colony-mcp.ts` calls `createMcpAdapter({config})` — an ISOLATED config, so the adapter's usual merge of
  `~/.config/mcp`, `~/.agents`, and the workspace's `.mcp.json`/`.pi/mcp.json` never happens (a repo could otherwise start programs).
- Pi exposes connectors as ONE tool `mcp` (`search`/`describe`/`connect`/`tool`+`args`/`action`/`url`…). `colony-gate.ts`: rule off → block all; `action` or `url`
  present (install / sign-in) → ALWAYS blocked (connectors are the user's to set up); no `tool` (only looking) → allowed; a `tool` call → allow/ask. The approval
  card reads "wants to use a connected app" with the tool + args. `MCP_NOTE` in the system prompt explains the tool; TOOLS_NOTE (file talk) is skipped for connector-only agents.
- Store `core/mcp.py`: `McpServer` = command(+args, env) XOR url(+headers) + enabled; `masked()`/`MASK` for the browser, a masked value sent back keeps the stored secret;
  names are lowercase letters/digits/-/_; `enabled_for_pi()` produces Pi's format; `composio(key)`.
- Composio facts (docs.composio.dev/llms.txt, /docs/composio-connect.md): Connect MCP = `https://connect.composio.dev/mcp`, streamable HTTP, header `x-consumer-api-key`
  (`ck_*`, from the CONSUMER dashboard). Consumer vs developer projects are separate: OME's backend uses the developer project (SDK + `link.create`), so OME's
  connected accounts are NOT visible here. Tools: COMPOSIO_SEARCH_TOOLS, GET_TOOL_SCHEMAS, MULTI_EXECUTE_TOOL, MANAGE_CONNECTIONS, WAIT_FOR_CONNECTIONS, REMOTE_WORKBENCH, REMOTE_BASH_TOOL
  (the last two run remote code: keep connector approval on). Per-user sessions via REST/SDK (`tool_router/session`) exist but were not needed for a single-user app.
- UI: there is ONE window, `web/js/tool-picker.js`: opened from the sidebar's Connectors button (standalone: agent dropdown, saves to the agent immediately, manages servers/keys via the "Add a connector" item) or from the agent editor (edits the editor's draft). Link opener: `web/js/links.js`. Per-agent tools are chosen in `web/js/tool-picker.js` (see progress.md) which edits a draft `{read, write, bash, mcp, mcp_servers, mcp_apps, web_search}` kept by `agent-editor.js`.
- Per-agent narrowing: `ToolAccess.mcp_servers` filters `mcp.enabled_for_pi()` in `chat.connectors_for(role)`; `mcp_apps` adds "use only these apps" to the system prompt when Composio is allowed.
- Tests: `tests/test_mcp.py` (real Pi + adapter + `tests/fake_mcp.py` stdio/HTTP; skipped if pi-runtime lacks the adapter), `tests/test_web_search.py`; `fake_llm.py` understands `MCP`, `MCPSEARCH`, `MCPINSTALL`.

### 4g. Kaggle provider (the owner's own GPU) — `llm/providers.py`, `engine/pi.py`, `kaggle/`
- A model id `kaggle/<name>` (e.g. `kaggle/qwen3:8b`) means "the model `<name>` on the Ollama server behind
  `KAGGLE_BASE_URL`" (the notebook's cloudflared tunnel + `/v1`). `providers._endpoint(settings, model)` returns
  (URL, headers, provider name, id to send); every call site uses it: `generate_openrouter_reply` (drops the OpenRouter-only
  `reasoning` and web `plugins` fields), `ping_model` (full timeout: the first request loads the model), `complete_chat`
  (when `OPENROUTER_ROUTING_MODEL` is a `kaggle/` id). No key is sent. `chat.handle_message` doesn't demand an OpenRouter
  key for a `kaggle/` agent and never adds `:online`.
- Pi: for a `kaggle/` model `run_turn` writes the Kaggle URL (apiKey "kaggle", ignored by Ollama) and the bare model name
  into `models.json`.
- `context.context_window` returns `KAGGLE_CONTEXT_WINDOW` (16384) for `kaggle/` ids — must equal the notebook's
  `OLLAMA_CONTEXT_LENGTH`, or Ollama silently cuts the prompt. Tools/inputs/reasoning are "unknown" (= allowed).
- `/api/models` asks `{KAGGLE_BASE_URL}/models` (5 s, errors ignored) and lists those first as "Kaggle (your GPU)".
  `/api/settings` stores `KAGGLE_BASE_URL` (accepts with/without `/v1`; must start with http(s)://; "" clears).
  The Settings modal (`#fKaggle`) saves it and reloads the model list.
- Errors: `errors._kaggle_hint` — 401 = no URL set, 400/404 = model not pulled, anything else = "the notebook has probably
  stopped: run it again and paste the new URL" (Thai).
- The notebook (`kaggle/colony_server.py`): writes `/tmp/setup.sh` and runs it in the background (own session); it installs
  Ollama from the tarball (NOT install.sh), starts `ollama serve` (OLLAMA_CONTEXT_LENGTH, OLLAMA_MAX_LOADED_MODELS=3,
  OLLAMA_KEEP_ALIVE=-1), pulls + preloads each model (`/api/generate` with only `model`), starts cloudflared
  (`--http-host-header localhost:11434`), appending lines to `/tmp/colony-status.txt`. The cell loop prints those lines,
  "… N s, X GB of models so far" every 15 s, then the URL (found with `startswith/endswith`, no regex), then a heartbeat
  every 5 min. `.ipynb` = the same source as one cell, regenerated from the `.py` by a tiny script (keep them in sync).

### 5. Prompt building is split on purpose
`providers.system_messages()` = identity + role + team note + memory context;
`build_messages()` = those + history + the new message (plain chat).
The tools path reuses `system_messages()` as Pi's system prompt so both paths
behave the same.

### 6. Memory (`colony/memory/`)
Markdown files under `~/.colony/self_improve/local/` (USER.md, MEMORY.md,
items by kind, INDEX). `recall.learned_context(user_id, query)` injects a bounded,
relevance-ranked slice (token-set Jaccard) into every prompt. Two write paths:
(a) explicit — the model ends its reply with a `MEMORY_SAVE: <fact>` line;
`chat.split_memory_marker` strips it and `save_explicit_memory` writes it now (if
saving fails the reply gets a "couldn't save" note, so the model's "I'll
remember" isn't a lie); (b) `review.maybe_review_in_background` every
`self_improve_interval_turns` (5) using `complete_chat`. `safety.py` blocks
prompt-injection *phrases* by plain-text matching (no regex; deliberately not
"from now on/always", which are legitimate preferences).

### 7. Agents with tools → Pi (`engine/pi.py`)
- `Role.tools = ToolAccess{read: off|allow, write: off|ask|allow, bash: off|ask|allow}`.
  `pi_tools()` → Pi tool names (`read,grep,find,ls` / `write,edit` / `bash`);
  `policy()` → the gate's per-tool rule.
- `chat.handle_message` branches: `role.tools.any_on` → refuse politely if no
  workspace / model can't use tools (`supports_tools() is False`); else
  `run_turn(...)`; **else the plain-chat path, untouched**.
- **One fresh `pi --mode rpc --no-session` process per turn.** Colony's history
  is the only conversation store. The shared conversation is passed as the
  prompt text (`transcript_prompt`: "Conversation so far: … The user's new
  message: …"); system prompt = `system_messages()` + `TOOLS_NOTE`, written to
  `~/.colony/pi-agent/system-prompt.md`.
- Pi config lives in `~/.colony/pi-agent/` (`PI_CODING_AGENT_DIR`): a generated
  `models.json` with provider `colony` (OpenRouter base URL + the key, or the Kaggle URL for `kaggle/` models — file
  mode 0600 — and just the one model id), so **any** model id works even if Pi's bundled catalog lacks it.
  Verified on Kaggle: qwen3:8b calls tools; glm4:9b does not (answers with code instead).
- **Locked-down launch:** `--no-context-files --no-skills --no-prompt-templates
  --no-themes --no-extensions --no-approve` (only our `-e colony-gate.ts` loads);
  environment = PATH/HOME/USER/LANG/LC_ALL/TMPDIR/SHELL + `PI_*` + `COLONY_*`
  only — **no API keys in the environment** (a bash tool could print them).
- **Approval gate (`colony-gate.ts`):** on each `tool_call`: (1) block any path
  outside `ctx.cwd` (the workspace) for all file tools; (2) reads pass; (3) by
  policy: `allow` / `off` (block) / `ask` → RPC `confirm` (title = tool name,
  message = what it wants to do; timeout 120 s + 5 s) → no answer = no. bash can
  **not** be path-fenced — the UI warns, keep it on "ask".
- **Approvals path:** `pi.run_turn(approve=…)` → `approvals.ask()` **blocks the
  chat request thread** (sync FastAPI endpoints run in a threadpool) until the UI
  calls `POST /api/approvals/{id}`; UI polls `GET /api/approvals` every 0.8 s
  while a reply is pending. Approvals are global (single user).
- Result: Pi's last non-empty assistant text + `actions` (`wrote x`, `edited y`,
  `read z`, ``ran `cmd` ``, ` ✗` when blocked/failed) appended as `🛠 …` so the
  next agent (and the user) see what changed. Pi's model errors
  (`assistant_error`, e.g. `429: {json}`) become `ProviderError` with the status,
  so `explain()` applies; engine failures raise `EngineError(user_message)`.
- Pi auto-retries a failed model call up to 3× (each costs free-tier quota).

### 8. Project folder (`core/project_folder.py`)
Each workspace has an optional `folder` (Workspace settings in the UI); none → the folder `colony` was
started in (`COLONY_LAUNCH_DIR`, set by `cli.py`). `check_folder` requires an absolute, existing directory
and **refuses `/` and the home folder**. The desktop shell starts the server *from home*, so a desktop user
must set a project folder per workspace. (The word "workspace" now means the project space; the folder is
called "project folder" in code and UI to avoid the clash.)

### 9. Frontend (`web/`) — plain ES modules, no build, no framework
`state.js` holds mutable UI state (`workspaces, workspaceId, roles (= the open workspace's team), target,
messages, pending, approvals, tools, modelPool`). `workspaces.js` = switcher menu at the top of the sidebar,
create/settings modal, `openWorkspace()` (loads team + messages; remembers the last one in localStorage;
refuses to switch while a reply is in flight because approvals are global). `feed.js::renderFeed()` redraws the
current room from `state.messages` (+ typing indicator + approval cards);
`ask()` captures the channel at send time so switching rooms mid-reply doesn't
misfile it. Modules import each other in cycles but only call across them inside
functions (safe). `markdown.js` is an escape-first renderer (**no regex, no
innerHTML of raw model text**). The server sends `Cache-Control: no-cache` for
UI files; after a UI change the user may need one hard refresh (Cmd+Shift+R).
A test (`test_web.py`) checks every `$('id')` the scripts use exists in
`index.html`.

### 10. Desktop shell (`desktop/src-tauri/src/main.rs`)
Rust picks a free port, spawns `colony --no-open --exit-with-parent --port N`
(cwd = home) with **piped stdin held open**; the server thread reads stdin and
SIGTERMs itself when it closes — so the server dies even if the window is
force-quit (signals alone left it orphaned; found by testing). The window shows
`dist/index.html` ("Starting Colony…") then navigates to the server; failures
are written into that page. Server command lookup: `$COLONY_BIN` →
`<repo>/.venv/bin/colony` (via CARGO_MANIFEST_DIR/../../) → PATH. Because the window runs the `colony` command,
Laya starts with it too.

## On-disk data (`~/.colony/`, or `$DATA_DIR`)
`.env` (OPENROUTER_API_KEY, KAGGLE_BASE_URL; WORKSPACE_DIR only read once by the migration), `workspaces.json`
(workspaces + their teams; `roles.json` is the legacy file, ignored after migration), `history.json`
(one conversation per workspace), `self_improve/<workspace id>/…` (memory), `pi-agent/` (models.json, system-prompt.md,
Pi's own files), `laya.log`. Writes go through `JsonStore` (atomic temp-file + replace). Laya's weights live in the
Hugging Face cache (`~/.cache/huggingface`, ~1.3 GB).

## Testing conventions
- `tests/conftest.py` autouse fixture: own `DATA_DIR`, `MOCK_MODE=true`, empty keys.
  Tests that need the real path set `MOCK_MODE=false` + a key and monkeypatch
  `chat.run_turn` / `generate_openrouter_reply`.
- **Never let a test touch the real `~/.colony/.env`:** `update_env_file` writes
  the module constant `config._ENV_FILE` — monkeypatch it (see `test_tools_api.py`).
- `tests/test_workspaces.py`: team/model isolation, copy-then-diverge, separate conversations and memory,
  per-workspace project folder, delete, and the first-run migration from legacy files.
- `tests/test_engine.py`: a fake `pi` program (Python script speaking Pi's RPC
  protocol) tests Colony's side; four tests run the **real Pi** against
  `tests/fake_llm.py` (OpenAI-compatible fake) and are skipped if
  `pi-runtime` isn't installed.
- `tests/test_kaggle.py`: a tiny non-streaming fake Ollama (`/v1/models`, `/v1/chat/completions`) checks routing,
  missing fields, errors, context size, chat with no OpenRouter key, Settings + picker; plus a real-Pi turn against
  `fake_llm.py` with a `kaggle/` model. `test_decider.py` covers Laya (URL, no auth, model `multilingual`, fallback).
  (`fake_llm.py` only streams — plain chat needs the non-streaming fake.)
- `tests/test_attachments.py` (files, capability filter, modes), `test_compaction.py` (patch `compaction.complete_chat`), `test_web_search.py`, `test_mcp.py` (store + REAL Pi + adapter
  against `tests/fake_mcp.py`, a dependency-free MCP server over stdio or HTTP; skipped if the adapter isn't installed). `fake_llm.py` understands `MCP`, `MCPSEARCH`, `MCPINSTALL`.
- `test_web.py`: every `$('id')` used by the JS exists in index.html, and every script passes `node --check` (a single unescaped quote once blanked the page).
- Real-model checks are NOT in pytest (they cost quota): run scripts against a dev server (see progress.md "Real-model verification").
- Fake-program first-run can be slow on macOS (Gatekeeper); keep timeouts generous.

## Gotchas that already bit us
- Jev's response key is `answers`, not `decisions`.
- `Settings` reads `~/.colony/.env` at import — monkeypatching `_ENV_FILE` does
  not change what `Settings()` reads; set env vars in tests.
- BSD `sed -i` needs `-i ''` on macOS; use python for edits in scripts.
- A stale server on port 8765 serves OLD code (looks like a 404 on new routes);
  `colony --reload` avoids it.
- Several new models reject `temperature` (`accepts_temperature`); free models are
  20 req/min and 50/day under $10 of credits; some free models are "agentic
  harness only" (403) or have no tool endpoint (404, e.g. `z-ai/glm-5.2:free`).
- **Env vars beat `~/.colony/.env`.** A dev server started with `OPENROUTER_API_KEY=sk-fake` (an old launch config) silently ignored the real key the owner saved in Settings
  (401). Start dev servers WITHOUT key env vars; the preview config `colony-local-tools` (in `.claude/launch.json`, per machine) now only sets HOME and the routing model.
- **MAX_ROLES = 8** (a 9th agent is a 400). OpenRouter requires **≥ $0.50 balance for requests carrying files (PDF) or audio**, even on `:free` models (402).
- `logos.composio.dev/api/<slug>` answers **200 with a generic placeholder** for unknown slugs: compare the image, not the status, when adding logo slugs.
- The preview screenshot tool often shows the previous frame: wait a second and screenshot again before judging a UI.
- Writing a new `history.json` message field (`attachments`) or conversation field (`compaction`) is safe: the store keeps unknown keys and readers use `.get`.
- **Laya on an Intel Mac:** PyTorch's last Intel-Mac build is 2.2.2 (Python ≤ 3.12) and transformers 5 won't run on it
  (`NameError: nn`) → Python 3.11 + transformers <5 + numpy <2. `laya.Router` takes `default=`/`model=`, not `subfolder=`.
  Running `laya-serve --help` STARTS the server (no help flag).
- **A child started from `colony` must die with it:** `atexit` + `terminate()` left Laya (and its worker processes)
  running after Colony was stopped → stdin-pipe lifeline + `killpg`, same idea as the desktop shell.
- **Kaggle:** see activeContext "Kaggle lessons" (use Save & Run All with GPU; never Ollama's install.sh; import makes a
  CPU run you must cancel; the editor is a cross-origin iframe).
