# HANDOFF — Local Multi-AI MVP (spin AI Ant out as a local app)

> Written 2026-09-24 by Claude (Opus) because the owner's usage ran out mid-planning.
> **Status: built in `local/` — read §9 (Progress log) first; §3/§7 below are the original plan.**
> The owner prefers **Thai** for all replies and wants detailed explanations
> (don't assume they know acronyms). Read `CLAUDE.md` at the repo root first.

---

## 1. Why this exists

Full Colony will take months to finish, and it will still have bugs when it lands.
Instead of waiting, the owner wants to ship a **very small product that solves one
problem**, get feedback, then grow it step by step. The long-term goal is to become
the core tool for solo-founder startups.

**The one problem:** people use several AIs (Claude, ChatGPT, Gemini). Each one has
different context. When they update AI "A" about their work, they're too lazy to
re-explain it to AI "B". Sometimes the text is too long to bother copy-pasting.

**Out of scope for the AI:** marketing (content clips, community). The owner said to
focus only on development.

---

## 2. What the owner has confirmed (do not re-ask)

1. **Split the AI Ant normal-chat page out as its own product.** Code:
   `backend/app/ai_ant/`, memory bank `memory bank/normal_chat/`. Leave out
   OME, Crew, CO, Colony Store, Forum and the rest.
2. **One screen, one shared context.** No switching to chatgpt.com or other sites.
3. **The user sets role → model**, e.g. Claude = reasoning, ChatGPT = chitchat,
   Gemini = writing.
4. **A decider picks which AI answers each message** (and how). The owner wants
   **Jev** as the decider (see §4).
5. **"Local" means the app runs on the user's machine and starts from a CLI
   command, but has a GUI.** It is NOT a terminal chat. The owner's reference is
   the **opencode desktop app**: a composer box, a mode picker ("Build"), a model
   picker, and a project folder + git branch shown under the box. The owner chose
   "CLI + UI combined".
6. **The UI should look like OME's.** The owner will give UI direction later.
   Don't design the final UI yet.

---

## 3. Still open — ask the owner before Step 1

These are my recommendations. The owner hasn't answered yet. The last message
offered: reply "ตามนั้น" to accept all three.

| # | Question | Recommendation | Why |
|---|---|---|---|
| Q1 | Should the AI read or write files in the opened project folder (like opencode)? | **No, not in v1** | The problem is cross-AI context. Editing files needs a permission system and tools, which is a lot of extra scope. |
| Q2 | Real desktop app (Electron/Tauri), or open in the browser? | **Browser first**: `colony` starts a localhost server and opens it, like `opencode web` | No big new dependency. Wrap it as desktop later. |
| Q3 | Same repo or a new repo? | **New top-level folder in this repo** (e.g. `local/`) | Easy to reuse ai_ant code. Move it out at real release. |

---

## 4. Jev (the decider): research so far

These notes come from web search results and review articles only. **Nobody has read
the official docs or used the API yet.**

- Jev is by **TypeSafe AI** (San Francisco). It entered **limited early access on
  2026-09-15**.
- It is a "System One" decision model. It does **not** write text. It returns typed
  values (a choice, a score, or null) with probabilities and confidence, for your
  code to branch on.
- The vendor claims ~200x faster and ~400x cheaper than LLMs on classification tasks.
- There are public examples of using it as a **model router**, which is exactly this
  use case. The Jev router picks the model, and an LLM writes the answer.
- The search results also mention "Open Jev". Nobody has checked what it is.
- Sources:
  - https://typesafe.ai/blog/introducing-system-one-models-and-jev
  - https://en.wikipedia.org/wiki/Jev_(AI_model)
  - https://www.mindstudio.ai/blog/how-to-build-model-router-with-jev
  - https://github.com/codebuffdev/springboot-ai-model-routingwithjev

**Rule (CLAUDE.md §1):** Jev is a new vendor/dependency. You **must get the owner's
approval**, and confirm they actually have API access (early access, pricing), before
wiring it in. Until then, put the decider behind one interface and use the existing
classifier.

---

## 5. What already exists in ai_ant (reuse, don't rebuild)

These are verified by reading the code and the memory bank on 2026-09-24.

- **Multi-model via OpenRouter** in one chat. `ai_ant/providers.py` and
  `ai_ant/model_client.py`. The model list is in `general_chat/model_pool.py`
  (`MODEL_POOL`).
- **Model routing:** `ai_ant/routing/registry.py::select_model()`. It picks by tier
  and cost only: light = cheapest, heavy = prefers Sonnet. It also filters by the
  capabilities the message needs. There is **no user role → model preference
  anywhere**; a grep confirmed this. The pool models are **not** tagged with
  chitchat/writing roles.
- **Manual model pick:** `manual_model` on `AiAntMessageRequest`, handled in
  `orchestrator.py::_pregate()`.
- **LLM intent classifier** (works in any language, including Thai):
  `ai_ant/mode_classifier.py`. This is the natural placeholder for the decider.
- **Shared history across models:** `orchestrator._history_messages()` sends up to
  16 prior messages (`ai_ant_history_max_messages`) no matter which model answers.
  So switching Claude → Gemini mid-chat already keeps the context.
  - ⚠️ `ai_ant/context_gate.py` evicts messages it tags off-topic or unimportant
    after 3 turns. A long "work update" given to model A *might* get evicted before
    model B sees it. **Not tested.** Check this.
- **Cross-chat memory:** under `backend/data/self_improve/<user_id>/` there are
  `USER.md`, `MEMORY.md`, `knowledge/*.md` and `skills/*.md`. Also `memory_tool.py`
  (real-time writes) and `self_improve.py` (a review every 5 turns). These are
  injected into every model's prompt via `orchestrator._memory_context()`. This is
  already file-based, which fits a local app well.
- The memory bank notes that several of these flows (the context gate especially)
  were **never verified in a real browser**.

Read before touching code: `memory bank/normal_chat/activeContext.md`,
`systemPatterns.md`, `progress.md` (the newest entries are at the top of its
"Update log").

---

## 6. Proposed architecture (mirrors opencode's server + client split)

```
colony (CLI command)
  → starts a local server (localhost) containing logic lifted from ai_ant
  → opens the UI
       ↓ every message
  Decider (existing classifier now, Jev later) → role → user's chosen model → OpenRouter
  History + memory → plain files on the user's machine (~/.colony/), shared by every model
```

- No Supabase login, no quota or subscription, no Colony Store.
- The user brings their own OpenRouter key. OpenRouter first, OpenAI as fallback,
  per CLAUDE.md. Read config through a settings object, not `os.environ`
  directly.

---

## 7. Plan (each step has a check)

**Step 0: read-only audit. Do this next. No code changes.**
List everything `backend/app/ai_ant` depends on and sort each item into
**lift / cut / rewrite**. Things to look for: Supabase auth, `subscription.py`,
`usage.py`, quota gates in `orchestrator.py`, `store_gap.py`,
`installed_skills.py`, the enterprise/OME imports (`project_context.py`,
`memory_index`, `vector_store`), crew cross-imports, and `get_settings()` fields.
→ Check: hand the owner the list before writing code.

**Step 1: core local server.**
New folder, with only chat, history and memory lifted over. Bring-your-own-key. Data
lives in `~/.colony/`.
→ Check: the API works with no Supabase. Switching model mid-chat, the new model
knows what was said. A new chat still remembers the user.

**Step 2: role → model config and the decider interface.**
The user maps reasoning/chitchat/writing (the exact role list is still to be
confirmed with the owner) to models. The decider sits behind one interface; the
first implementation uses `mode_classifier.py`.
→ Check: tests show each message type goes to the configured model.

**Step 3: plug in Jev.**
Only after the owner approves and API access is confirmed.
→ Check: run the same message set through the old decider and through Jev, and
compare.

**Step 4: CLI command.**
`colony` starts the server and opens the UI.
→ Check: one-command install and run on a clean machine.

**Step 5: OME-style UI.**
Wait for the owner's direction. Meanwhile, reuse the existing AI Ant chat
components for testing.

---

## 8. Repo rules that bit past sessions (from CLAUDE.md and memory)

- **Ask before adding any new dependency.** Name the library, what it replaces, and
  the trade-off.
- **No regex.** Propose it and ask first if you think you need one.
- Frontend type check is `npx tsc -b`, **not** `tsc --noEmit`. The latter checks
  0 files and always passes.
- Split files by domain. Don't grow grab-bag files.
- Backend modules follow the `router / schemas / logic` pattern.
- Mock data must be labelled **TEMPORARY MOCK DATA**, and the real API it will be
  replaced by must be documented.
- Log progress in `memory bank/normal_chat/progress.md` (or a new memory-bank
  folder for this product, if the owner agrees).
- Working tree note: the current branch is
  `feat/database-studio-filter-export-schema-canvas`, with many uncommitted
  frontend changes from other work. **Don't commit them as part of this.** Start
  from a fresh branch when code work begins.

---

## 9. Progress log

**2026-09-24 (later) — `local/` built by another AI, then audited + fixed by Claude (Opus).**
Owner answered the open Qs by building it: browser UI served from a localhost server,
folder `local/` in this repo, no file editing. Owner then asked for: roles defined by the
user IN THE UI (who answers what, and how), fix every audit gap, OME-style design.

Audit found → fixed:
- 🔴 Jev never worked: parser read `decisions`, real API returns `answers` → every message
  silently fell back to GPT. Rewrote `server/decider.py` against the documented shape
  (`state` now an object, `answers.role.choice/confidence`). Fallback is now visible in the UI
  ("Jev unavailable — default agent").
- 🔴 `max_tokens` 1024 → `settings.max_output_tokens` (4096).
- 🔴 XSS: AI reply went through CDN `marked` → `innerHTML` unsanitized. Replaced with a small
  escape-first markdown renderer in `server/web/index.html` (no regex, no CDN). Dropped CORS
  (UI is same-origin) so other localhost sites can't hit `/api/settings`.
- Roles are now user data: `server/roles.py` → `~/.colony/roles.json` (name, model, `when` =
  Jev criterion, `instructions` = system message). `GET/PUT /api/roles`. Old `ROLE_*_MODEL`
  env settings removed (ignored if still in `.env`). `POST /messages` takes `role_id` (message
  an agent directly, skips Jev) instead of `manual_model`.
- "Remember X" now saves immediately (`MEMORY_SAVE:` trailing-line marker, stripped from the reply).
- `pyproject.toml` → `pip install -e .` gives a real `colony` command; opens the browser by
  default (`--no-open` to skip). `web/` moved to `server/web/` so it ships in the package.
- Removed unused `langchain-typesafe` alpha dep, dead `context_gate_*` / `mode` / `attachments`
  request fields; `.env` writes reject newlines.
- UI rebuilt with OME desk tokens (240px `#0E0E0E` sidebar, "Direct Agents" list with avatars,
  `# auto` channel = Jev routes, owner bubble `12/12/2/12`, pill composer, OME modal style).
- Tests: `local/tests/` 11 passing (`.venv/bin/python -m pytest tests`).

Verified: pytest; real browser in MOCK_MODE (temp HOME, no real key): #auto send, DM an agent,
add agent via modal, XSS string rendered as text, mobile width. **NOT verified: a real Jev /
OpenRouter call** (costs the owner's credits — needs their OK). Quick check: restart the server,
send in #auto — the reply should carry a violet "Jev NN%" tag, not the yellow fallback tag.

Still open: streaming replies; file attachments UI; `providers.complete_chat` is unused;
Google Fonts is the only external request (falls back to system fonts offline);
nothing committed — `local/` is untracked on the unrelated `feat/database-studio-…` branch.

**2026-09-25 — agents fully editable + model dropdown + "Ask another agent".**
Owner: users may not want "chitchat" (want e.g. research or presentation agents), and wanted a
dropdown for the model instead of typing.
- Model field is now a `<select>` grouped by provider (label + one-line note, from
  `server/model_pool.py`, served by `GET /api/models` as `{id, provider, label, note}`) plus an
  "Other…" option that accepts ANY OpenRouter id. Pool trimmed to label/note (dropped unused
  cost/tier/good_at). Added `perplexity/sonar` and `perplexity/sonar-pro` (web-search models;
  they work here because local calls bind no tools — see normal_chat/progress.md 2026-07-16).
- "Add agent" has "Start from" presets (Research, Presentation, Coder, Writer, Chitchat); all
  fields editable after picking. Every agent — including the 3 defaults — can be edited or deleted
  (must keep ≥1). New blank agents default to Sonnet 4.6.
- Every reply has "Ask another agent ▾": re-asks the same question to a chosen agent
  (`ask(text, roleId)` → `POST /messages` with `role_id`). It appears as a new exchange in the
  chat (the question shows twice — consistent with reload).
- Agent colors now derive from the agent id so deleting/reordering doesn't recolor everyone
  (two agents can share a color — 8-color palette hashed).
- Caveats to tell the owner: a "Presentation" agent outputs a slide OUTLINE as text, not a
  .pptx file (no file generation in `local/`). Research quality/citations depend on the model —
  sonar returns citations only in the message text as the model writes them.
- Tests: 14 passing. Verified in a real browser (mock mode): preset → save → persists after
  reload; edit → "Other…"; delete default agent; Ask-another-agent menu → answer from chosen agent.

**2026-09-25 (later) — model list refreshed from OpenRouter's live catalog + Kimi added.**
`server/model_pool.py` ids/prices/param support were read from `https://openrouter.ai/api/v1/models`
(public, no key) on 2026-09-25: Claude Fable 5.1 / Opus 5.5 / Sonnet 5 / Haiku 4.5; GPT-6 Astra / Sol /
Luna; Gemini 3.1 Pro (preview) / 3.8 Flash / 3.5 Flash Lite; DeepSeek V4 Pro 0813 / V4.1 Flash;
Kimi K3 / K2.7 Code; Perplexity Sonar / Sonar Pro (Perplexity has nothing newer besides
sonar-deep-research / sonar-reasoning-pro / sonar-pro-search, not added — deep-research is slow).
Default agents + presets moved to Sonnet 5 / GPT-6 Luna / Gemini 3.8 Flash. Existing saved
`~/.colony/roles.json` keeps whatever models it had (old ids still work as "Other…").
- NEW GOTCHA: many new models reject `temperature` (Sonnet 5, Fable 5.1, all GPT-6 had
  `temperature` missing from OpenRouter `supported_parameters`). `providers.py` now sends it only
  when `model_pool.accepts_temperature(id)`; unknown/custom ids get none. Not verified live.
- `PoolModel` has `reasoning_effort` / `accepts_temperature` flags — re-derive from
  `supported_parameters` when adding models. `~provider/xxx-latest` aliases exist on OpenRouter.
- Dropdown groups use `provider_name` (fixes "Openai"/"Deepseek" casing). Tests: 16 passing.
- **Manus is NOT on OpenRouter.** Its API (`https://api.manus.ai`, docs `open.manus.im/docs`) is a
  task-based agent API (create task → results via webhook/polling, own API key), not chat
  completions. Not integrated — needs owner's decision (new provider + async flow + key).

- Owner: don't show prices in the model dropdown (users know them). Removed; notes are now only short descriptors (Fast & cheap / Cheapest / Built for code / Web search + sources) or empty.

**2026-09-25 (night) — shared-context upgrades: speaker labels + per-agent context gauge.**
- `core/context.py` (new): `plan_history()` builds what each agent sees. Assistant turns in the shared
  history are labelled `[AgentName] …` (from message metadata) and, when any label is present, a system
  note tells the model there are teammates and not to prefix its own reply (`strip_self_label` removes it if
  it does anyway). If the prompt wouldn't fit the model's window (85% of it, minus `max_output_tokens`),
  the OLDEST history messages are dropped for that agent only. Old messages without metadata stay unlabelled.
- Window sizes: `PoolModel.context` (from OpenRouter's catalog, 2026-09-25) → else a cached live lookup of
  `GET https://openrouter.ai/api/v1/models` (public, 5 s, fails quietly; skipped in mock mode) → else unknown.
- `GET /api/context?conversation_id=` → per agent `{window, used_tokens, percent, messages_sent, messages_total}`.
  Token counts are ESTIMATES (~4 chars/token ASCII, ~1.5 for Thai/CJK); no tokenizer dependency.
- UI: header "Context N%" chip (target agent, or the fullest agent in #auto) + popover with a bar per agent
  (`web/js/context.js`; green <60, amber 60–85, red ≥85). Small windows plateau ~70% because of the trimming.
- `MessageRequest.message` limit 8,000 → 100,000 chars (a pasted work update was rejected with 422).
- 400 "context length" errors now get a specific Thai message. `LOCAL_USER_ID` moved to `config.py`.
- Tests: 81 passing. Browser-verified (mock): gauge updates after sends, popover, trimming "sees the last 9 of 12",
  reopening a thread restores the gauge, phone width. NOT verified against a real model's token counts.

**2026-09-26 — rooms: group chat vs direct chats (display only).**
Owner: clicking an agent's "direct chat" still showed the group chat's messages. Now every exchange is tagged
`channel` = `"auto"` (group chat) or an agent id (that agent's direct chat): `MessageRequest.channel` (defaults to
`role_id` or `"auto"`), stored on both the user message and the assistant metadata, returned in `MessageResponse`.
Old messages have no channel → shown in the group chat. The feed (`web/js/feed.js`) keeps the whole conversation in
`state.messages` and `renderFeed()` shows one room; a reply lands in the room the message was sent from even if you
switch rooms while waiting; direct rooms have their own empty state. **Context is unchanged: every agent still sees
the whole conversation** (rooms only change what is displayed). "Ask another agent" from the group chat stays in it.
- Also: `/` and `/static/*` now send `Cache-Control: no-cache` — the browser had kept stale JS after updates
  (a tab ran old modules against the new server). One hard refresh (Cmd+Shift+R) is needed once for tabs that
  loaded the app before this change.
- Observed in the owner's real logs (old server): a 402 from OpenRouter — "can only afford 183 tokens" — i.e. the
  account has almost no credits; free models are 20 req/min and 50 req/day if < $10 credits were ever purchased
  (https://openrouter.ai/docs/api-reference/limits). Free-model 429s are the shared pool and/or that daily cap.
- Tests: 84 passing. Browser-verified (mock): group vs direct rooms separate, switching mid-reply, reload restores rooms.

## 2026-09-26 — Desktop window (Tauri)
- Direction agreed: harness with per-agent tool permissions comes later; owner chose to do the desktop app first, with **Tauri** (over pywebview/Electron).
- `local/desktop/`: Tauri 2 shell. Spawns `colony --no-open --exit-with-parent --port <free port>`, shows `dist/index.html` while booting, then navigates the window to the server. Kills the server on exit.
- `colony --exit-with-parent` (cli.py): stops the server when stdin closes — found by testing that SIGTERM/SIGKILL of the window left the Python server orphaned. Test: `tests/test_cli.py`.
- Verified: `cargo check`, `tauri dev` (server logs show the window loaded the UI), force-kill leaves no server. Not verified: visually, and the Cmd+Q path (no GUI access).
- Not done: self-contained `.app` (needs PyInstaller-style bundling → approval), native folder picker (needs the workspace/tools work first).

## 2026-09-26 — Spike: Pi (earendil-works/pi) as the tool engine
- Owner proposed using Pi's harness; approved a spike. Code: `local/spike-pi/` (README there). Pi 0.87.1, MIT, Node >= 22.19, RPC mode = JSONL over stdin/stdout.
- 19/19 offline checks pass against a fake OpenAI-compatible server (no key): approval gate via extension `tool_call` + RPC `extension_ui_request`, per-agent allow/ask/deny, per-agent `--tools`/`--system-prompt`/`--model` on one shared `--session-id`, `--no-context-files`, workspace fence for file tools, `[Agent]` labels via `message_end`.
- Not proven: real free models calling tools (owner runs `try_real_models.py` with their own key), bash containment, per-turn start-up cost with real models, history duplication (Colony vs Pi session), Node packaging.

- Real-model run (owner, 2026-09-26): nemotron-3-ultra + nemotron-3-super OK with Pi tools; glm-5.2:free has NO tool endpoint on OpenRouter (404; `supported_parameters` lacks `tools`) — Coder agent can't use tools on it; qwen3.8-27b:free hit upstream 429 (untested). Design consequence: Colony should read `supported_parameters` from OpenRouter `/models` and only allow tool permissions for models that list `tools`.

## 2026-09-26 — Agents with tools (Pi engine) shipped
Owner approved three steps; all done and verified.
1. **chat.py uses Pi only for agents with tools.** `Role.tools` = `{read: off|allow, write: off|ask|allow, bash: off|ask|allow}` (default all off; existing roles.json files load fine). `core/chat.py` branches: tools on → `engine/pi.py::run_turn`; else the old plain-chat path, untouched. Each turn is a fresh `pi --mode rpc --no-session` process: Colony's history stays the only source of truth; the shared conversation goes in as the prompt (`transcript_prompt`), the same system pieces as plain chat go in as `--system-prompt` (`llm/providers.py::system_messages` was split out of `build_messages`). The stored reply gets a `🛠 wrote x · ran y` line so other agents see what happened to the files.
2. **Approval UI.** `engine/colony-gate.ts` (Pi extension) asks via RPC `confirm`; `core/approvals.py` holds the open questions (the chat request blocks; no answer in 120 s = no); `GET /api/approvals` + `POST /api/approvals/{id}`; the feed polls every 0.8 s during a reply and draws an Allow/Deny card.
3. **Permission switches in the agent editor**, locked when OpenRouter's catalog lists no `tools` for the model (`GET /api/models/tools`; unknown = not locked; `PUT /api/roles` also refuses). Workspace folder: Settings (`WORKSPACE_DIR`) else the folder `colony` was started in (`COLONY_LAUNCH_DIR`); `/` and the home folder are refused; the desktop shell starts the server from home so the user must choose a folder.
- Safety choices: Pi gets NO environment secrets (key is in a 0600 `~/.colony/pi-agent/models.json`), `--no-context-files/--no-skills/--no-extensions/--no-approve` so a workspace can't inject prompts or extensions, file tools fenced to the workspace, bash cannot be fenced (UI warns; keep on "ask").
- Verified: 108 tests pass incl. 4 that run the REAL Pi against a fake model server (approve/deny, allow, off hides the tool, path escape, no CLAUDE.md leak); in the browser with real Pi + fake model: lock on glm-5.2:free, unlock on another model, approval card, Allow wrote the file, Deny did not.
- NOT verified: real OpenRouter models through this path inside the app (only via spike: nemotron-3-ultra/super OK); Node bundling for a shipped desktop app; Pi's auto-retry costs free quota; approvals are global (one user, one reply at a time).
- Install: `cd local/pi-runtime && npm install`. The old `spike-pi/node_modules` was deleted to save 437 MB (`npm install` there restores it).

## 2026-09-26 — Workspaces (top-level restructure)
Owner asked for: workspace → mix chat + direct chats, all sharing ONE context; each workspace's agents may use different models. After I explained my reading, they approved my 5 defaults: (1) a workspace is one continuous conversation ("New chat" becomes "New workspace"); (2) agents belong to the workspace (copied from the default team or another workspace on create, then independent); (3) memory per workspace; (4) project folder per workspace; (5) old data migrated into a first workspace "Personal".
- Backend: `core/workspaces.py` (store `~/.colony/workspaces.json`; workspace id = conversation id = memory user; id `local` for the migrated one), `core/project_folder.py`, `api/workspaces.py`; `workspace_id` on `/messages`, `/roles`, `/context`, `/memory/*`; `/conversations` and `/api/settings` folder removed. `history_max_messages` 16 → 60.
- UI: workspace switcher + create/settings modal (`web/js/workspaces.js`); `# mix` label; last workspace remembered in localStorage; switching blocked while a reply is in flight.
- Migration verified in tests, in the browser (mock) and as a dry run on a copy of the owner's real data. Nothing summarises very old context yet (proposed, not built).
- 119 tests pass. NOT committed/pushed at the time of writing.

## 2026-09-26 — Agent editor restyle + model picker
- Editor restyled after the owner's OME reference image (custom selects, permission cards with purple checkboxes; ONE "Request approvals" switch covers edit + run; old mixed settings open as "ask"). Removed the sidebar 🛠 badge at the owner's request.
- New model picker window (owner's opencode "Select model" screenshot): `web/js/model-picker.js`; `/api/models` now lists every OpenRouter model with capabilities (tools, input modalities, reasoning, context) from the cached catalog (`core/context.py::model_catalog`). Finding: today's live catalog no longer lists `z-ai/glm-5.2:free` (the default Coder model) — the picker warns "may have been removed".
- 121 tests pass; verified in the browser (search, keyboard, hover card, custom id, Escape, save). NOT committed/pushed.
- Model card restyled (owner found the small dim text hard to read): a label/value table (Model, Provider, Inputs, Tools, Reasoning, Context) at 14px, white values on muted labels, in `web/js/model-picker.js` + `.cap*` CSS. Same table in the picker's footer on narrow screens.
- Model picker bug (owner: list "hangs" when scrolling after hover): a scroll listener re-ran `highlight()` which called `scrollIntoView`, snapping the list back to the hovered row. Fixed: scrollIntoView only for arrow keys; on wide screens (>= 990px) the window shifts left and the card floats beside it; on narrow screens the table sits in a fixed-height area under the list so the list never resizes. Browser-verified at 1280 and 900 px (scrollTop holds while hovering).
- Reasoning levels per agent: DESIGN PROPOSED, NOT BUILT (awaiting owner). OpenRouter's catalog gives per-model `reasoning: {mandatory, default_enabled, supported_efforts, default_effort}`; API accepts `reasoning: {effort: none|minimal|low|medium|high|xhigh|max}`.

## 2026-09-26 — Reasoning level per agent (built)
Owner approved the design (levels limited to what the model supports; default = send nothing) and asked for a quick control on the sidebar row, not only in the editor. Done: `Role.reasoning`; catalog `reasoning_levels`; `reasoning_param()`; violet pill + menu on sidebar rows (`web/js/reasoning.js`); level buttons in the editor; picker card lists levels; Pi `--thinking` with `reasoning: true` + pass-through `thinkingLevelMap` (Pi otherwise ignored/clamped levels — found by experiment). Old built-in `medium` removed. 130 tests pass; browser-verified against the live OpenRouter catalog. Not verified: a real model call actually obeying a level (only request payloads were checked). NOT committed/pushed.

## 2026-09-26 — Attachments, capability-aware Jev, modes
Owner (with screenshots of Claude's + menu / mode menu): add files/folder, drag files into the chat, switch working mode, and Jev must know which model can't read images/video. Approved my plan; decisions: no-agent-can-read message in English; "Add folder" = set the workspace project folder (native picker awaits dependency approval); modes as proposed (no AI-decided Auto); simple filter first, uploads as base64 JSON.
- Backend: `core/attachments.py`, `api/attachments.py`, `Workspace.mode` + `agents.apply_mode`, catalog `input_modalities` used to filter agents before Jev, per-model rendering of history attachments, Pi gets images. Frontend: `attachments.js`, `mode.js`, composer redesign. Tauri: `disable_drag_drop_handler()` (cargo check OK).
- 142 tests pass; browser-verified (mock mode + live catalog: "Buddy, Writer can't read video, so Jev will only choose among the others"). NOT verified: a real vision/PDF/video model call. NOT committed/pushed.

## 2026-09-26 — Folder picker in the workspace window; mode pill always usable
Owner (focus on the local desktop app, not the web): the "Chat only" pill was disabled and should go (the mode pill is now always the mode name and always opens the menu; with no project folder the menu says tools stay off until one is chosen); the Project folder box of the New workspace / settings window got a "Browse…" button that opens the system (macOS) folder window through the Tauri dialog plugin (`chooseFolder()` in `web/js/workspaces.js`, shared with the composer folder menu). Outside the desktop app the button says to paste the path. Verified in the browser with a stubbed `window.__TAURI__.dialog`; the real macOS window is NOT verified by Claude. Also added `remote.urls` to the Tauri capability so the page served from 127.0.0.1 may call the dialog (unverified at runtime).

## 2026-09-26 — Compaction of long conversations
Owner asked whether Anthropic's compaction (platform.claude.com docs) could cut cost and the max-context problem; I read it: Claude-only, beta header `compact-2026-09-04`, signed blocks that only Claude can take back — unusable for a multi-model workspace. Owner pointed to Pi's built-in compaction; Pi's runs on Pi sessions (Colony uses `--no-session`, and plain-chat agents never touch Pi), so I ported its design instead: threshold + keep-recent + user-message cut + structured summary (Goal/Constraints/Progress/Key Decisions/Next Steps/Critical Context/Files) + iterative update. Owner approved 24k / 8k, routing model as summariser, keep all messages. Built `core/compaction.py` + store + prompt + UI note; 154 tests pass; browser-checked the summary note. NOT verified with a real model. Owner's account has ~no credits: the routing model (deepseek/deepseek-v4.1-flash, paid ~$0.30/M in, $1.20/M out) may 402, in which case the old trimming continues silently (check the server log for "Compaction failed").

## 2026-09-26 — Web search, Connectors (MCP via pi-mcp-adapter), Composio
Owner approved: web search via OpenRouter and adding `pi-mcp-adapter`; asked for connectors to go through Composio (list from OME) and to test, then document. Findings: Composio has a hosted MCP (`connect.composio.dev/mcp`, header `x-consumer-api-key`, consumer key `ck_*`) so no SDK/OAuth code was needed; OME uses Composio's developer project (different), so its connections don't carry over. Security calls made: the adapter's `mcp` tool can install servers/sign in — the gate refuses `action`/`url`; adapter config is isolated via `createMcpAdapter({config})` so a project's `.mcp.json` can't start programs. Real Pi + adapter tested against fake stdio and HTTP MCP servers (176 tests pass). NOT tried: real Composio key, real MCP servers. Nothing committed.

## 2026-09-26 — "Connect a tool" window
Owner sent OME's "Connect a tool" design as the reference for a friendlier connector UI and asked for a LONG list of tools. Built `tool-picker.js` + `apps-catalog.js` (97 apps in 9 categories + built-ins + the user's connectors, plus "type any app by name"), per-agent connector/app narrowing (`mcp_servers`, `mcp_apps`; app scope is soft, in the prompt), and replaced the editor's permission checkboxes with a Tools list. 178 tests; browser-verified. The app catalog's names are a hand-made starting list — not checked against Composio's real toolkit slugs (the agent finds tools by search). Nothing committed.

## 2026-09-26 — Real-model test run (app on :8767)
The :8767 dev server had been started from an old launch config that set `OPENROUTER_API_KEY=sk-fake`, which overrides the real key saved in `.env` (env beats dotenv) — fixed the config (in `.claude/launch.json`, per-machine) and restarted. Results and findings are in `memory bank/colony local/progress.md` ("Real-model verification"). Only code change from the run: `/api/open-url` now returns 500 if no browser could be opened. Test workspace "Claude test (free)" (id in scratchpad) left in the scratch data dir `home2/.colony`, not the owner's real data.
