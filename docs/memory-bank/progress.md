# Progress — Colony Local
(Newest first within each phase. Dates are 2026-09-24 → 2026-09-26.)

## Done ✅

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
- Owner runs a real tools turn in the app; fix what surfaces.
- Commit/push everything from the tools + desktop work (see activeContext.md → Git state).
- Native folder picker; git checkpoint per agent turn; diff view in approvals.
- Shippable installer (bundle Python + Node/Pi) — needs dependency approval.
- Long-lived Pi process for faster turns; streaming replies (currently one blocking POST).
- Optional: per-conversation approvals; a way to see/undo what an agent changed.

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
- Silent fallbacks: Jev failures and tool refusals must be visible.
