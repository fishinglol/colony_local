# System Patterns — Colony Local
_Architecture as it is now (2026-10-14). Paths relative to repo root._

## 1. Layers
`web UI / Tauri` →HTTP→ `colony/api` (thin routers) → `colony/core` (logic) → `colony/engine/openclaw.py` →HTTP→ **OpenClaw Gateway :18789** → Ollama.
**Coucou** uses `colony/api` for teams, settings, decider, history, and talks to the Gateway **directly over WebSocket** (`GatewayClient`) for chat turns (§4b).
`core/` never imports `api/`. All config via `get_settings()`; never read `os.environ` in handlers. One HTTP layer: `llm/http.py` (`post_json/get_json`, retries on 429/5xx with backoff, `ProviderError`).

## 2. File map
```
colony/cli.py        `colony` command: starts Laya (unless JEV_API_KEY) and the Gateway; children die with Colony
colony/app.py        FastAPI factory, serves web/ with no-cache
colony/config.py     Settings + update_env_file
colony/schemas.py    MessageRequest(workspace_id, message, attachments, role_id, channel) / MessageResponse(+decided_by, confidence, steps, worked_s, thinking)
api/                 chat(health,messages,context,activity,openclaw/status) workspaces agents(roles,models,roles/{id}/files) tools(approvals,gate,activity/tool)
                     plugins(openclaw/plugins) mcp memory attachments settings links
core/chat.py         handle_message(): resolve workspace/role → decide → history → OpenClaw turn → persist (HTTP path)
core/native_turn.py  prepare/finish around a turn the app runs on the Gateway itself (§4b)
core/decider.py      Jev API → Laya → Nemotron → first role           core/memory_keep.py Jev decides what is kept   core/agents.py   Role, ToolAccess, apply_mode, MAX_ROLES=8
core/workspaces.py   store, team copy, folder, mode, delete          core/context.py  shared-context labels, gauge (report)
core/gate.py         approval decision for tool calls                  core/approvals.py in-memory ask/resolve   core/activity.py live status + steps
core/trace.py        tool call → human step                           core/attachments.py, core/mcp.py (edit layer over OpenClaw config)
core/errors.py       explain(): provider error → Thai                 core/project_folder.py, core/models.py (Ollama pool)
engine/openclaw.py   everything that touches the Gateway/its config (see openclaw-capabilities.md)
engine/colony-gate/  OpenClaw plugin (TS): before_tool_call → POST /api/approvals/gate; after_tool_call → POST /api/activity/tool
llm/ollama.py        model table (context windows, tools, reasoning)    store/ history.json + sqlite mirror + JsonStore (+ `history.archive_before`: `/new` moves old messages to `~/.colony/archive/<ws>/`)
web/                 index.html, app.css, js/* (main, state, api, feed, work, sidebar, workspaces, agent-editor, model-picker, settings, tool-picker, …)
```

## 3. Decider (`core/decider.py`)
One request shape (Jev "System One"): `POST /v1/systemone`, `state.message`, `questions.role` = `choice` with criteria `{role_id: role.when}`; answer in `answers.role.{choice, confidence}`.
Ordered endpoints, first that answers wins; `retries=0`, 10 s each:
1. **Jev API** if `JEV_API_KEY`: `{JEV_URL}/v1/systemone`, Bearer key, `JEV_MODEL`, header `User-Agent: colony-local` (Cloudflare 403/1010 without it). Free model: 1 req/min until first top-up (10/min after) → 429 → next.
2. **Laya** if `LAYA_URL` (model `multilingual`, reads Thai, no key).
3. **Nemotron** via Ollama only when neither is configured. 4. First role = `fallback` (shown in UI).
Each role's criterion also lists its skills' names/descriptions (`skills` arg, built in `chat.py`).
`decided_by` ∈ jev | laya | nemotron | direct | mention | only_role | fallback. **`@Name`** (role name or id, any case, whole word; `mentioned_role`) in a group message picks that role with no decider call (a handoff, §4b, is the LAST line of an agent's reply starting with `@Name`). Direct chats and single-agent teams skip the decider.

## 4. A turn (`core/chat.py` + `engine/openclaw.py`)
- Conversation id = workspace id. History = all non-evicted messages, labelled by speaker; OpenClaw keeps its own per-session history, so Colony sends only **unseen** messages (`unseen`/`mark_seen`, `openclaw_seen.json`).
- Each role = one OpenClaw agent `<workspace_id>-<role_id>`; request model `openclaw/<id>`, real model in header `x-openclaw-model` (only `ollama/…`/`openclaw/…` ids). Session key = OpenAI `user` field (+ persona hash, so editing a persona starts a fresh session).
- `ensure_agent` writes the agent entry (lean: profile `minimal`, `alsoAllow` = only the role's tools, `skills` = names of the agent's own skills (none by default), `contextInjection: continuation-skip`) and waits for hot reload. First turn of a new agent can take ~1 min.
- Gateway readiness: `gateway_prepared` reads the log; a 500 "Sessions remain unavailable" is retried once; no Gateway = a clear notice (not saved to the conversation).
- Attachments (HTTP path): images as data-URI parts (≤8, 20 MB); text pasted; PDFs via `/v1/responses` `input_file`; audio/video refused with a notice. (Native turns: §4b.)
- After the turn: usage recorded (context gauge), memory net (`keep_if_worth`), steps/`worked_s` attached to reply + stored metadata.

## 4b. Native turn (`core/native_turn.py`, app ↔ Gateway)
`POST /api/turns/prepare {workspace_id, message, role_id?, channel, attachments}` → `{native, turn_id, agent_id, role_id, role_name, model, session, cwd, permission_mode, message, attachments, decided_by, confidence}` or `{native:false, reason}`.
No `role_id` = group chat: `decide()` picks (skills in the criteria). `message` = capability text (incl. the teammate list: each other role's name + `when`, `capability_text(teammates=…)`; the agent may tell the user to `@Name` a teammate, there is no agent-to-agent handoff yet) + unseen team lines (slash commands dropped) + user text (+ pasted text files). `attachments` = images (`type:image`) and PDFs (`type:file`) base64 for `chat.send`.
The app runs `sessions.create` (fence) → `sessions.patch` (model) → `sessions.messages.subscribe` → `chat.send`, then `POST /api/turns/finish {turn_id, reply, failed}`: strips the self label, `keep_if_worth`, steps (from the plugin's `after_tool_call`), `append_exchange`, `mark_seen`.
Gateway wire notes: events `agent` (stream lifecycle/assistant/tool/usage), `chat` (state status/delta/final/error), `exec.approval.requested` → `exec.approval.resolve {id, decision}`; handshake needs a signed device identity (v3 payload) and the `connect.challenge` nonce/ts.

**Handoff and `/new` (2026-10-14):** `prepare` with `handoff_from` (sender role id) + `hops` runs a teammate. Refused (404) unless the sender exists, the target has `accepts_handoff` and `hops <= MAX_HOPS` (3). The message is framed "[Sender hands you this task…]", `decided_by=handoff`, no `keep_if_worth`. `finish` detects a handoff (`_handoff`: LAST line `@Name task`, name or id, not itself) and returns `{handoff: {role_id, role_name, message, from, hops}}` while `hops < 3`; a handoff reply is stored with no user row (`append_exchange(user_message=None)`, metadata `handed_by`). A saved command whose first word is `/new` archives everything before it (`archive_before(keep_last=2)`) and empties the agents' usage gauge (`openclaw.forget_usage`). The app loops prepare → Gateway → finish while `finish` returns a handoff.

## 5. Memory (OpenClaw's design, Colony only provides folders)
Shared per workspace: `<project folder>/.colony/` (no folder: `~/.colony/self_improve/<ws>/`): `USER.md`, `MEMORY.md`, `memory/YYYY-MM-DD.md`. Per agent `~/.colony/openclaw-agents/<agent_id>/`: `AGENTS.md` (rules + absolute paths),
`SOUL.md` (only its persona), `IDENTITY.md`, a `USER.md` copy (re-copied each turn), own `MEMORY.md`/`DREAMS.md`. Agents WRITE shared files by absolute path; every agent SEARCHES them via
`agents.entries.<id>.memory.search.extraPaths` (keyword-only, `provider: none`; prompt says search in the user's language AND English). `core/memory_keep.py::keep_if_worth` (after each turn, only for roles that cannot write the files themselves and when the files didn't change): Jev `choice` question `keep` (about_user / fact_or_decision / nothing, via `decider.ask_choice`, Laya fallback) →
the user's own sentence is appended to USER.md / MEMORY.md; the model alone saved only ~half the time and fenced agents cannot write. Dreaming (nightly 03:00) promotes into the agent's PRIVATE MEMORY.md. Symlinks don't work (indexer ignores them).

## 6. Tools & approvals
Per-agent `ToolAccess` (read off|allow, write/bash/mcp off|ask|allow) + `web_search`; workspace **mode** (`apply_mode`) can only restrict. Enforcement is the **colony-gate** plugin inside OpenClaw:
Colony `gate.decide` applies permissions + mode + project-folder fence (symlink-safe), shows an approval card for "ask", blocks until answered. Colony unreachable = blocked (fail closed). **In native sessions (`:native-` in the session key) it only handles `write`/`edit`/`apply_patch` and connector tools** (the request carries `native: true`; a chat-only team's memory-folder writes pass): OpenClaw's session permission mode + `sessionRoot` fence + native approvals decide the rest (§4b, activeContext), because the Gateway only asks before `exec`. It guards everything in the HTTP fallback.
Gate bypasses: `web_search`, `memory_search/get`, `skills_read`, reads under the agent's own `skills/`, memory-folder reads/writes and the Gateway's own `main` agent bypass. MCP connectors live in OpenClaw `mcp.servers` (`<server>__*` allowlist per role).

**Skills** are per agent: folders with `SKILL.md` in `openclaw-agents/<agent>/skills/` (`engine/openclaw.py::add_skills/list_skills/remove_skill`; API `GET|POST /api/roles/{id}/skills`, `DELETE …/{folder}`).
`ensure_agent` lists their names in the agent's `skills` allowlist; a model reads one via `skills_read`/`read`; the trace step is "Used skill". Only that agent has them, in any room.

## 7. Workspaces (`core/workspaces.py`)
`workspaces.json`: id, name, folder, mode, roles. Create = copy a team, and (unless `folder` is given, `""` = chat only) a new project folder `~/Documents/Colony Projects/<name>` (`PROJECTS_DIR`); delete removes its OpenClaw agents (`remove_agents`) and memory folder, not the project folder. First-run migration put legacy roles into "Personal".

## 8. Frontend rules (web)
Plain ES modules, no build, no regex, no framework. Markdown renderer is ours (`js/markdown.js`) with a test guard. Hard-refresh after UI changes (server sends no-cache).

## 9. Coucou front-end (`coco_local/`, Swift)
Fork of open-source Coucou (MIT code, not Mochi/sounds). No agent logic, keys or memory of its own: Colony HTTP for teams/settings/history, **Gateway WebSocket for chat turns**. Colony calls: `/api/workspaces`, `/workspaces/{id}/messages`, `POST /api/messages` (`channel`, `role_id`, `attachments`),
`/api/activity` (1 s poll → Mochi pose), `GET|PUT /api/roles`, `/api/models`, `/api/models/test`, `/api/roles/{id}/files`, `/api/roles/{id}/skills` (+ `/skills/github`), `/api/turns/prepare|finish`, `/api/approvals`, attachments upload, `/api/health`, `/api/openclaw/status`, Laya `/health`.
- **Two lanes, shared only by the window.** Colony lane (Team page) = everything in `NotchBuddy/Sources/App/Colony/`; Coucou lane (Tools page, hooks → `nb-hook` → `nb.sock` → pills, Settings → Agents) is upstream code and stays untouched, nothing there reads Colony or the Gateway. New Colony code goes in `Colony/`; only small seams in upstream files.
- Files in `NotchBuddy/Sources/App/Colony/`: `ColonyService` (HTTP), `ColonyStore` (shared state, `ChatHeight`), `ColonyChatView`, `ColonyHomeView` (Team/Tools as two sliding pages: tab click or two-finger swipe; Team = `store.tasks`, Tools = `state.tasks` integration pills), `ColonySettingsView`, `GatewayClient` (actor: direct WebSocket to the OpenClaw Gateway, device key in Keychain, scopes read/write/approvals/admin; `chat()` streams status/delta/tool/approval/final, `commands()`, `agents()`, `resolveApproval()`; Settings → Colony → Gateway "Test connection"). `ColonyStore.runDirect` drives a turn and falls back to `POST /api/messages`. New Swift files were added to the `.xcodeproj` by script because xcodegen isn't installed (the six files moved into `Colony/` by editing their `path =` in `project.pbxproj`; Xcode still shows them in the flat App group until xcodegen runs).
- Seams in upstream files (keep small; upstream rule: don't restyle shipped views): `IslandRootView::CompactMiniGrid` (Mochis beside the notch: group 1 = shown Colony agents, group 2 = integration pills; swipe or 5 s auto-flip, dots between groups), `IslandViewContent` (`.prompt`/`.overview` switch), `IslandRootView`/`IslandWindowController` (height, auto-close, drag fixes, `reanchorToScreen` on `didChangeScreenParameters` so the island follows an external display being plugged/unplugged),
  `IslandViewContent::ApprovalView` (Colony and Gateway questions: `pillId == "colony"`; `colony-` ids answered via `POST /api/approvals/{id}`, `gateway-` ids via `GatewayClient.resolveApproval`), `FileDropView`, `UploadSequenceEngine`, `UploadCanvasView`, `ChatMarkdownView` (Thai bold), `SettingsView` (Colony row; Chat hidden while Colony on; AI pills hidden).
- Handoff: `ColonyService.finishTurn` returns a `Handoff`; `ColonyStore.send` loops `prepareTurn(handoff:)` + `runDirect(onHandoff:)` and drops its local pending message after the first reload (else it shows twice). Settings → agent → Tools → "Accept tasks from teammates" (`accepts_handoff` in the role dict). `LiveBubble` follows the stream at most every 0.4 s. A slash command never uploads the attached window context (`/new` must reach the team-command path, not the decider).
- Reminders: every agent gets OpenClaw's `cron` tool (`_tool_allowlist`). `ColonyStore.watchReminders()` (started in `AppDelegate`) keeps a Gateway connection (`GatewayClient.watchReminders`: `sessions.subscribe` + listener for event `cron` action `finished`) and shows a ⏰ card in the chat + expands the island. Verified live 2026-10-12 with `@Coder remind me in 2 minutes`: agent created the job (`automations` tool, `at` relative or offset time; a wall-clock time written with `Z` is UTC and fires hours late), it fired, the card appeared. The card is not saved in history.
- UserDefaults (domain `fr.louisraille.NotchBuddy`): `colonyChatEnabled` (true), `colonyBaseURL`, `colonyWorkspaceId`, `colonyDirectGateway` (true; false = always the HTTP path), `gatewayURL` (`ws://127.0.0.1:18789`), `mochiOnDesktop`.
- Build: `cd coco_local/NotchBuddy && xcodegen --spec project.yml --project . && xcodebuild -scheme NotchBuddy -configuration Debug build SWIFT_OPTIMIZATION_LEVEL=-O GCC_OPTIMIZATION_LEVEL=s SWIFT_COMPILATION_MODE=wholemodule ENABLE_TESTABILITY=NO`.
  `brew install xcodegen` fails on macOS 13 → use `xcodegen.zip` 2.46.0 from GitHub releases. Release needs a profile we don't have. `.xcodeproj` is generated; new Swift files appear only after xcodegen.
  Run `~/Library/Developer/Xcode/DerivedData/NotchBuddy-*/Build/Products/Debug/Coucou.app`.

## 10. Gotchas that bit us
- Jev answers under `answers`, not `decisions`. BeatAPI needs a User-Agent. Free Jev = 1 req/min.
- A real key in `~/.colony/.env` leaks into tests unless conftest blanks it (it does for `JEV_API_KEY`).
- **Gateway can die and Colony does not restart it** (2026-10-10: shutdown failed; zombie child kept the owner lease → new Gateway refused). Restarting Colony reaps the zombie.
- **Which process owns what:** the Tauri window (`tauri://localhost` in Activity Monitor) is only a UI; closing it changes nothing for OpenClaw or Coucou. The Python `colony --no-open` process (:8765) owns the Gateway (:18789) and is what Coucou's Team chat needs; kill that and Gateway + Team chat stop.
- **Gateway "not running" with Colony up** usually means `openclaw-main 2/dist` is half built (`~/.colony/openclaw.log`: "missing dist/entry.(m)js"; the watchdog gives up after 3 restarts). Fix: `cd "openclaw-main 2" && pnpm build`, then restart Colony.
- OpenClaw: multi-agent needs `agents.ownership: explicit`; `toolSearch: false` or small models can't find tools; a bare `.ts` in `plugins.load.paths` is never loaded (needs a folder + `openclaw.plugin.json`
  with `activation.onStartup`); `before_tool_call` default 15 s limit (raised to approval timeout + 10 s); FastAPI route order: `/approvals/gate` before `/approvals/{id}`.
- Config writes race with agent DB preparation after startup → Gateway restarts itself ("hot reload recovery"); `_gateway_post` waits and resends once.
- `usage.prompt_tokens` is the sum over a tool loop (gauge can read 37k for a turn that is ~5k).
- BSD `sed -i` needs `-i ''`; a stale server on :8765 serves old code; children of `colony` must die with it (stdin-pipe lifeline + killpg).
- MAX_ROLES = 8 (a 9th is a 400).
- Creating and deleting workspaces quickly on the live system (live tests) edits OpenClaw config; the Gateway reloads itself and can leave an agent's "startup preparation was superseded" (`/new` then hangs on "Getting the team ready…"). A Colony restart clears it.
- **Restart race (fixed 2026-10-14)**: after `launchctl kickstart -k dev.colony.local` the old Gateway still answered for a second or two (its watcher shell stops it after the old Colony is gone), so the new Colony logged "already running — using it" and then had no Gateway. `cli._start_openclaw` now keeps watching a Gateway it found (`OPENCLAW_ADOPT_POLL_S`, 3 misses in a row) and starts its own when it is gone ("The Gateway on the port is gone — starting one"). Covered by `tests/test_cli.py` (fake listener); not seen to fire on the real machine yet.
