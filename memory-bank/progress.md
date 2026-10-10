# Progress — Colony Local
> **2026-10-09:** Direction changed to OpenClaw-first (Colony = UI shell). A ponytail-audit of the repo produced the cut list
> in `activeContext.md`. No code removed yet. The "Done" history below stays true for what was built, but items for Pi,
> MCP/Composio, Compaction, own memory layer and Kaggle provider are slated to be replaced by OpenClaw equivalents.
(Newest first within each phase. Dates are 2026-09-24 → 2026-10-09.)

## Done ✅

### OpenClaw Gateway Integration, Plugin Manager, & Capability Matrix (2026-10-09)
- **OpenClaw Gateway Core Engine (`colony/engine/openclaw.py`):**
  - Integrated OpenClaw Gateway running locally on port 18789 as Colony's primary execution engine.
  - Implemented `run_openclaw_turn` supporting streaming, multi-turn history, project folder context, and tool execution.
  - Connected `colony/core/chat.py` and `colony/core/context.py` to route tool-capable agents through OpenClaw Gateway.
- **Categorized OpenClaw Plugin Manager (`colony/api/plugins.py`, `colony/web/js/settings.js`):**
  - Built full REST API (`GET /api/openclaw/plugins`, `POST /api/openclaw/plugins`, `POST /api/openclaw/plugins/batch`) managing 18 real OpenClaw plugins across 5 categories: Web & Search, Automation & Scheduling, Code & Sandbox, Memory & Brain, and External Integrations.
  - Redesigned Settings modal with 3 tabs: `🔌 OpenClaw Plugins`, `🤖 AI Providers & Keys`, `🖥️ Gateway Status`.
  - Added status badges (`🟢 แนะนำเปิด`, `⚪ ทางเลือก`, `⚠️ ขั้นสูง`), human-readable descriptions, hot-reload switches, and one-click "✨ เปิดปลั๊กอินแนะนำทั้งหมด" preset. Directly mutates `~/.openclaw/openclaw.json` (`plugins.entries`) and invokes Gateway hot-reload without restarts.
- **Agent Capability & Tool Matrix (`colony/web/js/agent-editor.js`):**
  - Redesigned Agent Editor modal with 4 discrete Capability Cards: Web Search (`web_search`), Read Files (`read`), Write & Edit Files (`write`), and Shell Execution (`bash`).
  - Added role presets: Thinker (Web+Read), Buddy (Web only), Writer (Web+Read+Write), Coder (All four). Persisted to `~/.colony/workspaces.json`.
- **System Prompt Pairing & Model Grounding:**
  - Injected strict real-time grounding prompt into `colony/engine/openclaw.py`, pairing local Ollama models with OpenClaw tool schema.
  - Mandated that models never guess live Bitcoin/crypto prices, stock tickers, or 2026 facts; models are strictly directed to call `web_search`.
  - Disabled 2-stage `toolSearch` meta-tool (`"toolSearch": false` in `~/.openclaw/openclaw.json`) so DuckDuckGo `web_search` is exposed directly as a first-class tool for local models.
  - Filtered non-OpenClaw models (`kaggle/...`) from `x-openclaw-model` header to safely default to `ollama/nemotron-3-super`.
- **End-to-End Real-World Verification:**
  - Verified live Bitcoin price query: accurately returned $82k range via DuckDuckGo search from CoinMarketCap/Binance.
  - Verified 2026 iPhone query: accurately returned iPhone 18 Pro / A20 Pro specs.
  - Verified 4 daemons operational simultaneously: Ollama (11434), Laya (8790), Colony (8765), OpenClaw Gateway (18789).

### Current date in every prompt (2026-10-01)
`providers._identity_system_message` now adds "Right now it is <weekday YYYY-MM-DD HH:MM> (the user's local time)…" so
models can tell what is overdue (before, no model knew today's date). Covers plain chat and Pi (shared `system_messages`).
Motivation: the owner wants a daily-life use (morning briefing over their Obsidian vault `Fais OS/my own schedule`:
`Main.md` + `Brain Dump.md`, simple-table to-do lists with deadlines) and worried small models are not smart enough.
Plan agreed: workspace "Daily" with project folder = the vault folder, Planner (gemma4, read-only, write = ask) + Writer;
models propose, the owner decides; deterministic date maths belongs in code, not the model; test against the real files
(known answers: "Record voice" overdue since 2026-09-29 14:00, "make colony work" due 2026-10-01) on the next Kaggle run.
Tests 188 → 189. One test failed once during an abnormally slow run (8 min); re-run: 189 pass (suspected timeout flake
under load, test not identified).

### Model shootout on Kaggle (2026-09-30)
Ran 5 candidates through `kaggle/model_exam.py` (Thai chat/writing/reasoning/facts, Python code, Pi file-write) on a T4×2
run of `colony-models-eval`; cancelled after 31 min. Winner set: gemma4:12b + ornith:9b + qwen3.5:9b (see activeContext).
Also: `errors._kaggle_hint` now says "model failed, server still up" for HTTP 500 (was "notebook stopped"); notebook script
has `PRELOAD` and skips a model whose pull fails instead of aborting. Tests 187 → 188.

### Kaggle provider + Laya decider (2026-09-29, owner has no money; OpenRouter balance negative)
- **Kaggle provider.** `llm/providers._endpoint()`: a model id `kaggle/<name>` → `{KAGGLE_BASE_URL}/chat/completions`,
  no key, no OpenRouter-only fields (reasoning, web plugin); used by chat, "Test this model" (longer timeout: first request
  loads the model), `complete_chat`. `engine/pi.py` writes the Kaggle URL into Pi's models.json for `kaggle/` models (no
  OpenRouter key needed). Context window for Kaggle models = `KAGGLE_CONTEXT_WINDOW` (16384 = the notebook's
  OLLAMA_CONTEXT_LENGTH). `/api/models` lists the server's models first as "Kaggle (your GPU)". Settings has a
  "Kaggle server URL" field (`/api/settings` accepts it with/without `/v1`, "" clears). Thai errors: no URL / model not
  pulled / notebook down (`core/errors._kaggle_hint`). The identity system message no longer says "via OpenRouter".
- **Kaggle notebook** `kaggle/colony_server.py` (+ `.ipynb`): background setup script (untar Ollama, `ollama serve`,
  pull + preload qwen3:8b, gemma3:12b, glm4:9b, cloudflared quick tunnel); the cell prints progress and the URL.
  Run it as Save & Run All with GPU. Verified on the owner's account: ready in ~6.5 min.
- **Laya decider.** `core/decider.py`: `LAYA_URL` set → the same Jev-shaped request to `{LAYA_URL}/v1/systemone`,
  model `multilingual`, no key, `decided_by = "laya"` (UI tag `Laya NN%`, fallback tag says "Jev/Laya unavailable").
  `cli._start_laya()` starts `laya-runtime/serve.py` (port 8790) when `laya-runtime/.venv` exists and sets `LAYA_URL`;
  `serve.py` kills its own process group when Colony's stdin pipe closes (verified for SIGTERM and SIGKILL).
  `laya-runtime/requirements.txt` pins what works on an Intel Mac: Python 3.11 (pyenv 3.11.13), laya[serve] 0.3.21,
  torch 2.2.2, transformers <5, numpy <2 (torch has no newer Intel-Mac builds; transformers 5 needs newer torch).
- **Real results:** Thai routing mostly right (misses noted in activeContext); Gemma/GLM 2-5 s, Qwen3 ~16 s; Pi tool turn
  on `kaggle/qwen3:8b` wrote a file; glm4:9b doesn't call tools.
- Tests: `tests/test_kaggle.py` (7, incl. real Pi against the fake model server) + 2 Laya tests in `test_decider.py`.
  178 → 187.
- Rejected on the way: moving to Kaggle only for rate limits (first answer: top up $10 — owner has no money); local
  Ollama (Mac too weak); OpenJev (hardware).

### Logos + Colony theme for the tool window (2026-09-26)
Real app logos: the page loads `https://logos.composio.dev/api/<slug>` (Composio's logo service; 94 of the 97 catalogue apps have one, mapping in `web/js/apps-catalog.js`
`logoSlug`; AWS S3, Evernote, WooCommerce and typed-in apps get a lettered tile; offline = letters too). Note that service returns a generic placeholder (HTTP 200) for
unknown slugs, so a slug must be checked by comparing the image, not the status code. Colony's own tools use symbol tiles. The window now uses the app's tokens: sidebar
surface, violet accent for selection/scope/pills (same as the mode and reasoning pills), white primary button, `--ok`/`--warn` statuses. Logos are fetched by the browser at run time (a request to
Composio per visible logo); bundling copies locally would need downloading ~95 SVGs (not done, ask first).

### Sidebar "Connectors" = the Connect-a-tool window (2026-09-26, owner correction)
The owner had asked for the CONNECTORS window itself to be redesigned after the OME reference; Claude first built the design only inside the agent editor and left the old
Connectors window. Fixed: the sidebar button now opens the same `tool-picker.js` window (standalone mode: an agent dropdown in the header, every change saved to that agent
at once); the old window and `connectors.js` are gone (link opener moved to `links.js`). New in the list: "Add a connector" (form for any MCP server), per-item
"Remove … from Colony" (deletes the server/key globally), and "Sign in to <App>" (puts a request in the chat). Lesson: when a request names an existing screen, change THAT screen.

### Real-model verification (2026-09-26, free models + a little paid; via the app on :8767)
PASSED with real OpenRouter models: Jev routing (decided_by "jev"); image → Qwen 3.8 vision said "Red"; Jev filtered out text-only agents (`only_role`); English
notices for unreadable files; text file to a text-only model; shared context; Pi tool agent write with approve/deny and read; Plan mode (no write, a 4-step plan);
reasoning low/off on Qwen; Pi + image (Gemma vision said "Blue"); **MCP**: fake stdio server via a real model (ask/deny), and the REAL remote server
DeepWiki (`https://mcp.deepwiki.com/mcp`, free, no key) — `read_wiki_structure` answered correctly; **compaction** with a free routing model (88 msgs ≈ 26.5k tokens →
gauge 9.1k, summary kept every fact, recall from the summary alone worked); **web search** plain (Sources list with real BBC/Reuters links) and via Pi (`:online`).
NOT verified: Composio (no key), PDF/audio/video to a real model, the desktop app's Browse/link opening.
Findings: OpenRouter needs **≥ $0.50 balance for requests with files (PDF) or audio** (402 "requires at least $0.50 in balance for files/audio"), even on `:free`
models; some free models (e.g. `thinkingmachines/inkling-small:free`) are coding-agent-only (403); Qwen free often 429s (shared pool); MAX_ROLES = 8 (a 9th agent
is refused with 400). Idea not built: send PDFs through OpenRouter's file-parser plugin so text-only models can read them (needs checking of cost/balance rules).

### "Connect a tool" window (2026-09-26, after the owner's OME reference image)
- The agent editor's checkboxes (permissions, web) became a **Tools** list + `＋ Connect a tool`, which opens `web/js/tool-picker.js`: search, category pills,
  left list (~103 items: project files, edit files, commands, web search, "Every app in Composio", **97 apps** from `web/js/apps-catalog.js`, your own connectors),
  right panel = "This agent can / Needs approval before / Access scope" (Ask each time | Allow freely), Connect tool / Save changes / Disconnect. Stays open after
  connecting (Cancel becomes Done) so many apps can be added. Any other app can be typed by name (Composio has 1000+). Missing Composio key = inline key box.
- Backend follow-up: `ToolAccess.mcp_servers` (which connectors; None = all enabled) and `ToolAccess.mcp_apps` (apps the agent is told to stay within — a
  SOFT scope in the system prompt; the approval card still shows every action; Composio's single consumer-key server can't be filtered per app). One
  scope level (`mcp`) covers all of an agent's connected apps. Tests 176 → 178. Browser-verified against the reference layout.

### Web search + Connectors / MCP + Composio (2026-09-26)
- **Web search** per agent (`Role.web_search`, editor switch "Search the web"): plain chat sends OpenRouter's `plugins: [{"id":"web","max_results":5}]`;
  Pi agents run the `:online` model id. Cited pages (`message.annotations` type `url_citation`) are listed under the reply as **Sources**.
  ~$0.007 per message (Exa) even on free models, so it needs credits. Off by default. Perplexity models already search natively.
- **Connectors (MCP)** through `pi-mcp-adapter` 2.37 (MIT, owner-approved; installed in `local/pi-runtime`, +121 npm packages). `ToolAccess.mcp`
  (off/ask/allow) is a 4th permission ("Use connected apps"); servers live in `~/.colony/mcp-servers.json` (0600) managed from the sidebar's
  **Connectors** window (`core/mcp.py`, `api/mcp.py`, `web/js/connectors.js`); secrets are masked in the UI. Works without a project folder
  (Pi then runs in `~/.colony/pi-agent/no-folder`).
- **Composio** (owner's chosen connector hub): one hosted MCP address `https://connect.composio.dev/mcp` + header `x-consumer-api-key: ck_…`
  (the *consumer* key from Composio's consumer dashboard). "Add Composio" needs only that key; the agent then discovers/connects apps itself via
  Composio's 7 meta-tools and shows an OAuth link (links open in the real browser through `POST /api/open-url`). The chips list in the window is
  OME's connector catalog (`frontend/src/lib/store/storeConnectors.ts`) turned into "Connect my X" prompt starters.
- Verified with the REAL Pi + adapter against fake MCP servers (stdio and streamable-HTTP incl. headers): ask/allow/off, refusal never reaches
  the server, search/describe never ask, install/auth/url refused, a project's own `.mcp.json` never started. Tests 154 → 176.
  NOT verified: a real Composio account/key, real MCP servers (GitHub, Notion…), a real model choosing the `mcp` tool well.

### Compaction of long conversations (2026-09-26)
- `core/compaction.py`, modelled on Pi's compaction (MIT; format + iterative update + cut at a user message), NOT Anthropic's
  Claude-only API feature (beta, signed blocks, single provider). After a reply, a background thread summarises the older part
  when the conversation passes `COMPACT_AT_TOKENS` (24k est.) and keeps ~`COMPACT_KEEP_TOKENS` (8k) of the newest word for word,
  using the routing model (`openrouter_routing_model`, same as memory review). One summary per workspace in `history.json`
  (`compaction: {summary, through_id, created_at}`), updated on each compaction; messages are never deleted. Every agent gets it as a
  system message. UI: a "Messages above were summarised for the AIs · View summary" note. Failure = old trimming continues, retry
  after 5 min. Tests 143 → 154. NOT verified: a real summariser call (only a fake), real token savings, summary quality.

### Attachments, capability-aware Jev, modes (2026-09-26)
- `+` menu (Add files or photos ⌘U / Add folder), drag-and-drop anywhere, paste, chips above the text box; files upload as
  base64 JSON (no python-multipart). Text files are pasted into the message for any model; images/PDF/video/audio become real
  content parts only for models whose catalog `input_modalities` include them. Jev only chooses among agents that can read
  the attachment (deterministic filter in `core/chat.py`), and a Colony notice (English) says what to change when nobody/the
  chosen agent can't. Older attachments are notes in the shared history; only the newest 3 attachment messages are sent in full.
  Tool agents (Pi) get images + text only. Mode pill (Auto / Manual / Accept edits / Plan / Bypass), per workspace, applied over
  each agent's own permissions (`agents.apply_mode`). "Add folder" opens Workspace settings (native picker = Tauri dialog plugin,
  a new dependency, NOT approved yet). Tauri window: `disable_drag_drop_handler()` so the page receives dropped files.
  Tests 130 → 142; browser-verified in mock mode and against the live catalog. NOT verified: a real vision/PDF/video model call.

### Reasoning levels (2026-09-26)
- Per-agent reasoning level (default/off/minimal…max) limited to what each model supports (OpenRouter catalog), as a violet pill
  menu on the sidebar row + level buttons in the editor; sent to OpenRouter and, for tool agents, to Pi (`--thinking`, with a
  pass-through level map). Removed the hard-coded `medium` effort. Model-picker scroll bug fixed. Tests 121 → 130.

### Model picker + agent editor restyle (2026-09-26)
- Agent editor restyled after the owner's OME reference (custom selects, purple-checkbox permission cards: Read / Create & edit /
  Run / Request approvals — one approvals switch for both edit and run). Sidebar tool badge removed at the owner's request.
- **Model picker window** after opencode's "Select model": search, Suggested + all ~460 OpenRouter models by maker, arrow-key / hover
  capability card (reads text/images/video/files/audio, tools, reasoning, context limit), custom-id row, Escape closes only the picker.
  `/api/models` now returns the whole catalog with capabilities. Tests 119 → 121.

### Workspaces (2026-09-26)
- New top level: **workspace** = own team (own models), one continuous conversation, own memory, own project
  folder. `core/workspaces.py`, `core/project_folder.py` (renamed from `workspace.py`), `api/workspaces.py`,
  `web/js/workspaces.js`; `workspace_id` replaces `conversation_id` everywhere; "New chat" and Recent Chats
  removed; sidebar shows a workspace switcher; the group chat is labelled `# mix`.
- First-run migration into "Personal" (id `local`): legacy agents, old chats merged into one timeline (backup
  file), memory in place, old folder setting → its project folder. Dry-run on a copy of the owner's real data OK.
- `history_max_messages` 16 → 60; Settings modal lost the folder field (API key only); `--workspace` CLI flag and
  `LOCAL_USER_ID` removed.
- Tests 108 → 119 (`test_workspaces.py` + a `node --check` test for every JS module, which caught a real
  quote typo that blanked the page).

### Agents with tools + native window (2026-09-26)
- Tauri 2 desktop shell (`desktop/`): free port, loading page, navigates to the server,
  stops it on exit; `--exit-with-parent` watchdog (fixes orphaned server on force-quit);
  starts the server from home so a workspace must be chosen.
- Pi spike (`spike-pi/`, 19 offline checks + real-model script): proved approval gate,
  per-agent permissions, shared conversation across models/personas, workspace fence,
  `[Agent]` labels, `--no-context-files`. Real models: nemotron-3-ultra & super OK, GLM
  free has no tool endpoint, Qwen rate-limited.
- **Step 1:** `Role.tools`; `engine/pi.py`; `chat.py` uses Pi only for tools-enabled agents;
  `🛠` actions line; `system_messages()` split out of `build_messages()`.
- **Step 2:** `colony-gate.ts` + `core/approvals.py` + `/api/approvals`; Allow/Deny cards in the feed.
- **Step 3:** permission switches in the agent editor, locked via `/api/models/tools`
  (OpenRouter `supported_parameters`); `PUT /roles` refuses tools on unsupported models;
  Workspace folder in Settings; tool summary in the direct-chat header (the sidebar badge was removed at the owner's request).
- Tests grew 85 → 108, incl. real-Pi tests against `tests/fake_llm.py`; browser-verified
  (lock, unlock, approval card, Allow writes, Deny doesn't).

### Rooms, gauge, robustness (2026-09-25)
- Group chat vs direct-chat **rooms** (display-only; context still shared); `Cache-Control: no-cache`
  for UI files; pushed to `origin/feat/colony-local` (`0f1920e`, `d4a80ce`).
- Per-agent **context-window gauge** + trimming of oldest messages; speaker labels `[Name]`.
- **Retries/backoff + Thai error messages** (`llm/http.py`, `core/errors.py`); "Test this model" button.
- Message limit raised 8 000 → 100 000 chars (long updates hit 422).
- Free-model defaults; latest model list + Kimi; no prices in the dropdown; Manus dropped.
- **Restructure into a package** (Steps 0–4 of `local-restructure-spec.md`): api/core/llm/memory/store/web split,
  UI split into ES modules, self_improve split into `memory/`.

### Foundation (2026-09-24)
- Local FastAPI app + `colony` CLI + OME-styled UI; user-editable agents (name/model/when/how);
  Jev decider integration (fixed: response key is `answers`); shared context + memory;
  explicit "remember" via `MEMORY_SAVE:` marker; injection guard by plain-text phrases;
  own escape-first markdown renderer (fixed XSS from `marked`+innerHTML); no CORS.
- Audit bugs fixed (Jev parser, strict memory scan lying about success, multi-line key injection, etc.).

## Remaining / next 🔜
### OpenClaw-first migration (added 2026-10-09, in order, owner says go per step)
0. ✅ Pi + own agent loop removed (see activeContext).
1. Decide how `openclaw-main 2/` lives in the repo (submodule / gitignore / vendor) and get it running from source.
2. Make `colony.cli` start/stop the OpenClaw Gateway from that folder; show its status in the UI.
3. ✅ compaction handed to OpenClaw (2026-10-10). (see `openclaw-capabilities.md`, order revised there) Verify OpenClaw can replace: approvals to UI, session compaction, multiple agents/rooms, attachments.
4. ✅ attachments (images) via OpenClaw (2026-10-10). ✅ memory handed to OpenClaw (2026-10-10). ✅ MCP moved to OpenClaw (2026-10-10). Delete Pi stack and own tool loop (see cut list in `activeContext.md`), then hand over MCP, memory, compaction.
5. Prune tests, rewrite the legacy sections of `systemPatterns.md`, commit when the owner asks.
- Owner moves their real workspace onto the Kaggle models; fix what surfaces.
- Commit the memory-bank move + 2026-09-29 work (no remote yet).
- Memory review / compaction on a Kaggle model; Qwen3 thinking control; auth on the tunnel; "is Kaggle up?" indicator.
- Git checkpoint per agent turn; diff view in approvals; long-lived Pi process; streaming replies.
- Shippable installer (bundle Python + Node/Pi + Laya) — needs dependency approval.

## Explicitly rejected (do not rebuild) ❌
- **Delegating implementation to opencode** ("คุณทำไม่ใช่ให้มันทำ") and any "handoff" talk.
- **Manus** as a model/provider.
- **Wrapping opencode / Claude Code as the harness** (their big prompts would flatten
  every agent's personality; Pi with our own prompt was chosen).
- **Pi sessions as the conversation store** (would duplicate Colony's history); using
  `--continue`/`--session-id`.
- **pywebview / Electron** for the window (Tauri chosen).
- **Prices in the model dropdown.**
- **Regex** in any of our code; `marked`/raw innerHTML for model text; CORS.
- **Room-isolated context** (rooms are display only).
- Silent fallbacks: decider (Jev/Laya) failures and tool refusals must be visible.
- **OpenJev** as the decider (needs a 24 GB NVIDIA GPU or Apple Silicon; no CPU mode). **Running chat models on the
  owner's Mac** (Intel, 8 GB). **Ollama's install.sh on Kaggle** (its progress output killed the session).
