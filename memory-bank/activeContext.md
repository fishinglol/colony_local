# Active Context — Colony Local
_Last updated: 2026-10-09 (direction change to OpenClaw-first recorded; before it: OpenClaw Gateway + Plugin Manager + Agent Capabilities + Ollama system prompt pairing complete)_

## ✅ SOUL.md per agent (2026-10-10, fourth pass; replaces the shared-SOUL.md note above)
Owner: "each AI's identity differs, SOUL.md must be one per agent". Now each agent has its OWN OpenClaw workspace
`~/.colony/openclaw-agents/<agent_id>/` with AGENTS.md (memory rules), SOUL.md (only its persona), IDENTITY.md (its name), a USER.md COPY
and its own MEMORY.md/memory/ (where OpenClaw's dreaming writes for that agent). The team's memory stays shared in
`~/.colony/self_improve/<ws>/` (MEMORY.md, USER.md, memory/YYYY-MM-DD.md): agents WRITE there by absolute path and every agent
SEARCHES it through `agents.entries.<id>.memory.search.extraPaths`. `write_agent_files` runs each turn (persona hash = session tag; USER.md
is re-copied shared -> agent each turn).
- Tried first: symlinks (MEMORY.md/USER.md/memory -> shared) inside the agent folder: OpenClaw's indexer ignores symlinks ("No memory files
  found"), so not usable. Real files + extraPaths work (CLI and live).
- Live: Writer ends with BANANA, Coder with PAPAYA from their own SOUL.md; both knew a fact from shared USER.md; Writer saved a fact to
  shared MEMORY.md and Coder found it with memory_search.
- Consequences: dreaming promotion now lands in the agent's PRIVATE MEMORY.md (not the shared one); the Memory window in the UI shows the
  shared folder only. Deleting a workspace removes the agent folders too (`remove_agents`).
- Gauge caveat: `usage.prompt_tokens` is the sum over the model calls of a tool loop, so a turn with several tool calls shows e.g. 37k
  although a plain turn is ~5k. 128 tests pass.

## ✅ Persona in SOUL.md, memory rules in AGENTS.md (2026-10-10, third pass)
- `engine/openclaw.write_team_files` writes the workspace's **SOUL.md** (one `## <Name>` section per role = its instructions from the agent
  editor), **AGENTS.md** (shared-memory rules with absolute paths, "never say saved unless it succeeded", bilingual `memory_search`) and
  a one-line IDENTITY.md (stops OpenClaw seeding its ~1.5 KB persona templates). OpenClaw injects them on a session's first turn.
- The per-request system message is now only "You are <Name> (persona = `## <Name>` of SOUL.md)" + permission lines (web/read/write/exec,
  connectors, project folder). Prompt tokens per agent ~4.1-4.8k (was 17.5k seen for a coder before).
- Because bootstrap files are read once per session, the session key carries a hash of SOUL+AGENTS (`build_session_user(..., persona)`):
  editing a persona starts a fresh OpenClaw session (history is re-sent once). Live: BANANA persona obeyed from SOUL.md alone; after
  editing to PAPAYA the next turn used PAPAYA; another role in the same workspace was unaffected.
- One SOUL.md is shared by all roles of a Colony workspace (the folder is shared for memory), so each agent sees the others' persona
  text too (small). Per-role folders would need symlinks for memory — not done.
- Found: the Gateway restarts itself ("hot reload recovery: cron monitor") when a config reload races with a new agent's database
  preparation right after startup -> that request got HTTP 500. `_gateway_post` now waits for the Gateway to come back and re-sends once
  (only if it really went down); `ensure_agent` waits 150 s. 128 tests pass.

## ✅ Dreaming / Colony-down / cross-language memory (2026-10-10, second pass)
- **Dreaming promotion proven** with a throwaway agent: 4 `memory search` queries -> `memory promote --apply` (thresholds lowered
  by CLI flags) wrote the line into MEMORY.md with `<!-- trigger -->`/`<!-- importance -->` tags. At the DEFAULT thresholds (min-score
  0.75, 3 recalls, 3 distinct queries; internal, not configurable in config) the same note scored 0.642 after 4 recalls on one day, so the nightly job
  promotes only what is recalled across several days. Candidates only come from `memory_search` hits.
- **Colony down, Gateway up** (tested with a standalone Gateway): `read` is blocked with "Colony is not running, so nobody can approve
  this action..."; `memory_search`/`memory_get` now bypass the gate (`FREE` in colony-gate/index.ts) and work. Kept fail-closed on purpose;
  `main` is never gated. Nothing else runs agent tools without the user: `_quiet_background` sets `skills.workshop.autonomous.mode=off`
  (removes the weekly per-agent skill review jobs) and `agents.defaults.heartbeat.every=0m` (setting `systemAgent` had silently started a 30-min
  heartbeat on `main`; removed). Only the 03:00 dreaming job remains.
- **Cross-language search**: kept keyword-only (no embedding download). The system prompt now tells the agent to search in the
  user's language AND English; live: Thai question over English notes -> both facts found (before: "no results"). Real embeddings
  need a download (Ollama `bge-m3`/`nomic-embed-text` ~0.3-1.2 GB via local `ollama serve`, or `@openclaw/llama-cpp-provider`); the stored
  OLLAMA_API_KEY is rejected by ollama.com (401), so cloud embeddings are untested. Not done; owner decides.
- Stale agent entries (written by older Colony versions) are rewritten on that role's next turn by `ensure_agent`.
- 123 tests pass.

## ✅ Untested items tested and fixed (2026-10-10)
- **memory_search** was disabled in `~/.openclaw/openclaw.json` (`memory.search.enabled:false`). `ensure_agent` now sets keyword-only
  search (`provider:"none"`, no embedding key) and gives every agent `memory_search`/`memory_get`; the gate allows both. Live: English
  and Thai queries over MEMORY.md / memory/*.md found the right line. Keyword-only = no cross-language match (Thai question vs English
  note found nothing).
- **Dreaming**: memory-core's nightly job (`0 3 * * *`) was failing "Agent-less cron job has no resolvable owner" (multi-agent roster).
  `ensure_agent` now sets `agents.defaults.systemAgent.agentId = main`; a manual run swept all workspace folders
  ("dreaming promotion complete workspaces=5") and created DREAMS.md in them. Promotion itself (needs recall thresholds over days)
  is NOT verified.
- **PDF**: Colony sends turns with a PDF to the Gateway's `/v1/responses` (enabled + 10 pages by `ensure_agent`; `_as_responses`).
  Live: "PINEAPPLE, 1234 baht" from a hand-made PDF. OpenClaw keeps file text out of the session, so later turns can't re-read it.
  Audio/video still unsupported (clear notice).
- Agents on a non-Ollama model get "pick an Ollama model" instead of silently using the Gateway default.
- First turn of a brand-new agent can take ~1 min: `ensure_agent` waits 60 s (was 20); `explain` has a "still preparing, resend" message.
- Gateway-down + non-`main` agent => tools blocked (gate fails closed) is by design, not changed. 122 tests pass.

## ✅ OpenClaw 100% cut-over (2026-10-10, owner decision)
Deleted: `llm/providers.py` (OpenRouter/OpenAI chat), `core/compaction.py`, the whole `colony/memory/` package, the Jev branch of
`core/decider.py`, OpenRouter catalog code in `core/context.py`, `OPENROUTER_*`/`OPENAI_*`/`JEV_*`/compaction settings, 9 test files.
Every agent turn runs in OpenClaw; no Gateway = a clear notice (mock mode aside). Models = the Ollama pool only (`core/models.py`).
- **Context gauge** (`core/context.report`): the `usage.prompt_tokens` the Gateway reported for each agent's last turn
  (`engine/openclaw._record_usage` -> `~/.colony/openclaw_usage.json`), over the model's window; "no turn yet" before the first answer.
- **Workspace delete** (`engine/openclaw.remove_agents`): drops its agents from `openclaw.json`, `~/.openclaw/agents/<id>`, seen/usage
  markers and its memory folder (verified live). `colony-ping` is a permanent helper agent for "Test this model" (`openclaw.ping_model`).
- **Memory window** (`api/memory.py`) just reads USER.md / MEMORY.md / memory/*.md of the workspace folder; dreaming UI removed.
- `core/errors.explain`: Gateway HTTP errors (429, context too long) now get their real explanation; "can't connect" only when status is None.
- Still Colony-side by choice: Laya/Nemotron decider (`decide_via_ollama` calls Ollama directly), `llm/ollama.py` model table.
- Live check: model test 31 s (first agent prep), reply + agent-written memory, gauge 17.5k/262k for a coder, delete cleanup. 119 tests pass.
Reasoning-level pills stay hidden (Ollama models list no levels); `Role.reasoning` is stored but unused.

## 🗑️ Kaggle removed (2026-10-10, owner decision)
`kaggle/` folder, `tests/test_kaggle.py`, the `kaggle/<name>` model prefix, `KAGGLE_BASE_URL`/`KAGGLE_CONTEXT_WINDOW`, the Settings field,
the picker group and `errors._kaggle_hint` are gone. Every "Kaggle" mention further down in the memory-bank is history only.
OpenRouter / the OpenAI fallback plain-chat path stays. Suite: 191 passed.

## ⚠️ DIRECTION CHANGE (2026-10-09, owner decision): OpenClaw-first, Colony = UI shell
**Owner's words:** wants `openclaw-main 2` and Colony's UI, with every backend system 100% OpenClaw's.
**Chosen path ("path 2", tight coupling):** Colony stops being its own agent backend and becomes the UI shell of OpenClaw.
- **Source:** `openclaw-main 2/` (package `openclaw` v2026.9.8, ~3.6 GB, currently *untracked* in git; has `dist/`). This is the
  OpenClaw Colony runs, not an external/global install (`openclaw` is not on PATH on this Mac).
- **Who owns what (target):** OpenClaw owns model calls (Ollama/Kaggle/OpenRouter), the tool executor, plugins/MCP, sessions,
  memory, approvals and sandbox. Colony owns only the UI (workspaces/rooms/agent editor/settings/feed) and talks to OpenClaw
  through its Gateway (`http://127.0.0.1:18789`, `openclaw_gateway_url`). Colony should also start/stop OpenClaw itself
  from the source folder (extend `colony.cli`), so the user opens one app.
- **Status: PLAN ONLY. Nothing has been deleted or rewritten in code yet.** The code below still describes today's hybrid.
- **Cut list from the ponytail-audit (do only when the owner says go, one step at a time, tests green between steps):**
  1. `pi-runtime/` (534 MB), `spike-pi/`, `colony/engine/pi.py`, `colony/engine/colony-gate.ts` (+ `engine/*.ts` in
     `pyproject.toml` package-data).
  2. `colony/core/agent_loop.py`, `colony/core/local_tools.py`; in `colony/core/chat.py` the `is_ollama` and Pi `tools.any_on`
     branches (keep mock + OpenClaw); drop `openclaw_gateway_enabled` gating.
  3. Candidates to hand to OpenClaw (verify OpenClaw can do it first): `core/mcp.py` + `api/mcp.py` (connectors),
     `core/approvals.py`, `core/project_folder.py`, `core/compaction.py`, `colony/memory/*` (~1,100 lines; OpenClaw has
     "Memory & Brain" plugins), `llm/ollama.py` + `llm/providers.py` (shrink to a model-list helper for the picker).
  4. Tests tied to removed code: `test_engine`, `test_agent_loop`, `test_mcp`, `test_ollama`, `test_kaggle`, parts of
     `test_tools_api`, `test_web_search`, `test_attachments`, `test_workspaces`, `test_reasoning`.
  5. Owner decides: `laya-runtime/` (1.0 GB, the `# mix` decider; not duplicated by OpenClaw unless it routes multi-agent
     itself) and `kaggle/` (can stay: just a GPU Ollama host OpenClaw points at).
- **Open questions to check in `openclaw-main 2` before cutting:** can it send approval requests back to a UI; does its session
  compaction replace ours; does it support multiple named agents/rooms per workspace; how are attachments/images passed;
  how to launch it from source (Node version, build state: `node_modules` looks incomplete) and how to vendor it
  (submodule / gitignore / in-repo).
- **Done 2026-10-09:** `colony.cli` now starts the OpenClaw Gateway from `openclaw-main 2/` itself (`_start_openclaw`, ~35 s to
  come up, log `~/.colony/openclaw.log`; skipped if :18789 already answers) and a tiny `sh` watcher stops it when Colony exits
  (uvicorn re-raises SIGTERM so `atexit` does not run). Verified: start, a real chat turn through OpenClaw to
  `ollama/nemotron-3-super` (Ollama cloud, key in `~/.colony/.env`, never in the repo), and gateway exit ~6 s after Colony SIGTERM.
  Laya was not running during that test (decider falls back to the first agent).
- **Done 2026-10-09 (step 4a of the cut list): Pi and the own agent loop are gone.** Deleted `pi-runtime/`, `spike-pi/`,
  `engine/pi.py`, `engine/colony-gate.ts`, `core/agent_loop.py`, `core/local_tools.py`, `Settings.pi_bin/openrouter_base_url/
  tools_turn_timeout_seconds/approval_timeout_seconds`, `ToolAccess.pi_tools`, `attachments.pi_images`, the `tools.pi_installed`
  health field and the "Pi not installed" UI note. `core/chat.py` now has three paths: mock, OpenClaw, plain chat
  (OpenRouter/OpenAI/Kaggle, no tools). Any agent with tools, or any `ollama/` model, goes to OpenClaw; if the Gateway is down
  the user gets a clear "Gateway not ready" notice. Consequence: **Kaggle + tools no longer works** (OpenClaw gate excludes
  `kaggle/`), and plan-mode / connector (MCP) notes were only in the Pi prompt, so they are not sent to OpenClaw yet.
  Tests: removed ~20 Pi-bound tests and `test_engine.py`/`test_agent_loop.py`; `pytest tests` = 177 passed. Not committed.
  Note: run `pytest tests`, not bare `pytest` (it would also collect `openclaw-main 2/`). Still kept for now: `core/approvals.py`
  + `/api/approvals` + UI cards (OpenClaw approval bridge unverified), `core/mcp.py`, `llm/ollama.py`, `llm/providers.py`.
  First chat right after Colony starts can come back empty while the Gateway is still warming up (port open, ~35 s).
- **Done 2026-10-09 (step 0, running from source made solid):**
  - `openclaw-main 2/` is now in `.gitignore` (not vendored, not a submodule). It has no `.git` of its own, so the only
    version record is `package.json` = **2026.9.8**; if it is ever replaced, re-verify `/readyz`, `x-openclaw-model` and the
    plugin config keys used by `colony/api/plugins.py`.
  - Gateway readiness = `GET /readyz` (200). The port opens ~35 s after start but `/readyz` only turns 200 ~10 s later, and
    `/` stays 503 forever. `is_openclaw_available` now probes `/readyz` (old probe treated any HTTP answer, even 503, as up,
    which is why the first chat after start came back empty). While warming up, chat shows the "Gateway not ready" notice.
  - `colony.cli._start_openclaw`: skipped in mock mode or when `openclaw_gateway_enabled` is off (so `test_cli` no longer
    spawns a real gateway); prints a warning if Node or `openclaw-main 2/openclaw.mjs` is missing; reuses a Gateway already on
    :18789; a background thread prints "ready" or "exited (code N), see ~/.colony/openclaw.log". Test for the probe added.
- **Step 1 done 2026-10-09 (read-only):** capability check of OpenClaw vs Colony pieces is in `openclaw-capabilities.md` (verdict per
  piece, two bridge bugs found: double history, all roles on agent `main`, and a revised migration order). Read it before cutting more.
- **Done 2026-10-09 (migration step 1):** per-role OpenClaw agents + no double history; details and the `agents.ownership: explicit` gotcha in
  `openclaw-capabilities.md`. Note `~/.openclaw/openclaw.json` now has `agents.ownership=explicit` and one entry per used role.
  Next in order: MCP via `mcp.servers`, then compaction, memory, approvals. Also open: ~46k prompt tokens per turn (tool profile).
- **Done 2026-10-10:** prompt cut from ~46k to ~3.6-5k tokens per turn by making each OpenClaw agent lean (see the table in `openclaw-capabilities.md`).
  Still open: orphaned OpenClaw agents after deleting a workspace; `contextInjection: never` vs memory migration; MCP tool allowlist.
- **Done 2026-10-10 (migration step 2): MCP moved to OpenClaw** (`mcp.servers`, per-role `<server>__*` allowlist). Known regression: connector "ask"
  approvals are not enforced until the approvals step. Next: compaction, memory, approvals, attachments.
- **Done 2026-10-10 (migration step 5a): approvals enforced via the colony-gate OpenClaw plugin** (details + gotchas in `openclaw-capabilities.md`). `core/approvals.py`,
  `core/gate.py`, `/api/approvals*` and the UI cards are now the live approval path (keep them). Next: compaction, memory, attachments.
- **Done 2026-10-10 (migration step 3): compaction handed to OpenClaw** (verified live; details in `openclaw-capabilities.md`). Colony's `compaction.py`
  stays only for the plain-chat path. Next: memory (Colony memory vs OpenClaw MEMORY.md; revisit `contextInjection: never`), attachments, then the UI gauge.
- **Done 2026-10-10 (migration step 4): memory handed to OpenClaw** (shared per-workspace memory folder = the agents' workspace; first-turn injection; gate lets any role keep
  its memory files; plus a deterministic net for explicit "remember" because the model only saves ~half). Details/caveats in `openclaw-capabilities.md`. Next: attachments, the UI context gauge, cleanup of orphaned agents.
- **Done 2026-10-10 (migration step 6): attachments** -- images now reach OpenClaw agents (they were dropped); text files already worked; PDF/audio/video get a clear
  notice (details in `openclaw-capabilities.md`). The step-by-step migration list is now done except cleanup: UI context gauge, orphaned agents on workspace delete,
  deleting `colony/memory/*` + `compaction.py` + the plain-chat path (`llm/providers.py`, `llm/ollama.py`) when the owner decides.
- Everything below this section is the **pre-change** state; read it as "what exists today / what is being replaced".


## Where things stand right now
**Fully local 4-daemon autonomous stack is online and operational** (2026-10-09):
- **Core Engine & Tool Executor: OpenClaw Gateway** runs locally on port 18789 (`openclaw gateway run --allow-unconfigured`). Colony routes execution through `colony/engine/openclaw.py` (`run_openclaw_turn`), passing agent identity, capability boundaries, project workspace folders, and conversation history.
- **Local Inference: Ollama** runs locally on port 11434 (`ollama serve`), hosting `nemotron-3-super`, `qwen3.5:9b`, and other local models.
- **Local Routing: Laya Decider** runs on port 8790 (`laya-runtime/serve.py`), deciding who answers in `# mix` (~770 MB RAM, 0.3-0.5s per turn).
- **Frontend & Orchestrator: Colony Local** runs on port 8765 (`colony.cli --reload`), featuring the multi-agent UI, tabbed Settings, Plugin Manager, and Agent Editor.

### Key Architectural Enhancements (2026-10-09)
1. **Categorized OpenClaw Plugin Manager (`colony/api/plugins.py`, `colony/web/js/settings.js`):**
   - Settings modal redesigned into 3 tabs: `🔌 OpenClaw Plugins`, `🤖 AI Providers & Keys`, and `🖥️ Gateway Status`.
   - Exposes 18 real OpenClaw plugins across 5 categories: Web & Search, Automation & Scheduling, Code & Sandbox, Memory & Brain, and External Integrations.
   - Shows status badges (`🟢 แนะนำเปิด`, `⚪ ทางเลือก`, `⚠️ ขั้นสูง`), human-readable descriptions, hot-reload switches, and a one-click "✨ เปิดปลั๊กอินแนะนำทั้งหมด" preset.
   - Directly mutates `~/.openclaw/openclaw.json` (`plugins.entries`) and invokes Gateway hot-reload without downtime.
2. **Agent Capability & Tool Matrix (`colony/web/js/agent-editor.js`, `colony/core/chat.py`):**
   - Redesigned Agent Editor modal with 4 discrete Capability Cards: Web Search (`web_search`), Read Files (`read`), Write & Edit Files (`write`), and Shell Execution (`bash`).
   - Role presets automatically configure capabilities: Thinker (Web+Read), Buddy (Web only), Writer (Web+Read+Write), Coder (All four). Persisted in `~/.colony/workspaces.json`.
3. **Paired Ollama with OpenClaw System Prompt (Real-Time Grounding):**
   - Injected strict grounding prompt into `colony/engine/openclaw.py` explicitly pairing local Ollama models with OpenClaw tool awareness.
   - Mandates that models never hallucinate live financial prices (Bitcoin, stocks), current events, or 2026 facts; models are strictly directed to call `web_search`.
   - Fixed OpenClaw's 2-stage `toolSearch` meta-tool bottleneck: added `"toolSearch": false` under `"tools"` in `~/.openclaw/openclaw.json`, exposing DuckDuckGo `web_search` directly as a first-class tool for local open-weights models.
   - Filtered non-OpenClaw models (`kaggle/...`) from `x-openclaw-model` header so Gateway safely defaults to `ollama/nemotron-3-super`.
4. **Verified Live End-to-End:**
   - Real-time Bitcoin query verified: returned live $82,135 - $82,160 range cited from CoinMarketCap & Binance via DuckDuckGo.
   - 2026 iPhone query verified: returned iPhone 18 Pro / A20 Pro specs via search.

### Previous Kaggle / Cloud GPU Background (2026-09-29 / 09-30)
- **Chat models also runnable on Kaggle GPU** (2× T4 16 GB): `kaggle/<ollama name>` sends requests to `KAGGLE_BASE_URL` when cloud GPU is preferred over local.
- **Laya on Mac:** runs on the owner's Mac (Intel i5 2017, 8 GB, no GPU).


## Model shootout (2026-09-30) and the recommended team
The owner asked for models with different "personalities" that fit Kaggle. Candidates came from Ollama/Hugging Face
(the 7 models in gumloop.com's open-weight article are all 300B-1.6T, none fit; only the Qwen3.5 family has small
sizes). `kaggle/model_exam.py` runs one exam per model through a throwaway Colony (5 Thai/English prompts + a Pi file-write
tool test). Results, same conversation for all (so later models saw earlier answers; slow times include model swapping
because all 5 = ~33 GB don't fit in VRAM at once):
- **gemma4:12b** (Google, ~8 GB): best Thai (natural, polite, correct), code correct, tools OK, but slow (20-100 s) and
  verbose. → Buddy, Writer, Thinker.
- **ornith:9b** (Deep Reinforce, 5.6 GB, coding-tuned): code correct, tools OK, Thai OK but sprinkles Chinese words
  ("奖励", "预期"), imitates the "[Buddy]" label and says "คร้า". → Coder.
- **qwen3.5:9b** (Alibaba, 6.6 GB, vision): good Thai chat/writing, tools OK, 6-20 s when loaded, BUT answered the
  reasoning question in Chinese and its code returned `nums[1]` of the non-unique sorted list (wrong for [5,5,3]).
  → all-rounder / image input; not the first choice for Thinker.
- **lfm2.5:8b** (Liquid AI, 5.2 GB): fastest (1-3 s) but Thai is broken/hallucinated, leaks `<think>` text, no tool call.
  → not for Thai chat. Dropped.
- **scb10x/typhoon2.1-gemma3-12b** (Thai-specialised): UNTESTED — every request returned HTTP 500 from the server
  (probably GPU memory while swapping). Worth retesting alone.
- Not chosen: granite4.1 (no Thai), glm-4.7-flash (19 GB), mistral-nemo (old), SEA-LION (30B+), everything in the article.
`kaggle/colony_server.py` now pulls **gemma4:12b, ornith:9b, qwen3.5:9b** (~21 GB, all preloaded; ready in ~7 min).
Recommended team: Buddy/Writer/Thinker → `kaggle/gemma4:12b`, Coder → `kaggle/ornith:9b`, `kaggle/qwen3.5:9b` for images.
Kaggle weekly GPU quota showed only **15 h left** on 2026-09-30 (30 h/week, resets weekly); that exam run used 31 min.
Earlier (2026-09-29) team `qwen3:8b` / `gemma3:12b` / `glm4:9b` is obsolete (glm4:9b never calls tools).
Kaggle notebooks on the owner's account: `colony-server` (old models), `colony-models-eval` (current file, use this one).
The owner's real workspace ("testt", in `~/.colony`) was still on
OpenRouter free models when they last started Colony: they must paste the Kaggle URL in Settings and switch each agent.
The "Kaggle (your GPU)" group shows in the model picker only while a run is up and its URL is saved.

## How the owner runs it (taught to them in Thai, 2026-09-29)
1. kaggle.com → Your Work → `colony_server` (https://www.kaggle.com/code/faislol/colony-server) → Edit → check
   Settings → Accelerator = GPU T4 ×2 → Save Version → "Save & Run All (Commit)" → Advanced Settings →
   "Run with GPU for this session" → Save. It runs in the background: the tab may be closed.
2. Logs tab → after ~7 min a box with `https://….trycloudflare.com` → Colony → Settings → Kaggle server URL → Save.
3. `cd ~/Desktop/Colony-Local && .venv/bin/colony` (or the window: `cd desktop && npm run dev`). Ctrl+C stops it (and Laya).
4. When done: notebook → Logs → ⋮ → View versions → ⋯ on the running version → Cancel (else it burns GPU quota for up to
   12 h). Claude cancelled the first real run after ~2 h (7386 s) at the owner's request.
- The owner also ran the cell interactively in the editor once (output under the cell). That works while the tab stays
  open; stop it with ⋮ next to "Draft Session" → Stop session. Earlier interactive runs died (see Kaggle lessons).

## Kaggle lessons (learned the hard way on 2026-09-29)
- Interactive editor runs died repeatedly during the big downloads; Ollama's `install.sh` (progress bar) killed the
  session every time. So the script untars `ollama-linux-amd64.tar.zst` itself (installs `zstd` if missing) and does all
  slow work in a background shell script; the cell only prints progress every 15 s.
- **Save & Run All with GPU (a background "version") is the reliable way.**
- Importing a notebook makes Kaggle auto-start a run WITHOUT a GPU → cancel it (Version History → ⋯ → Cancel).
- Driving Kaggle's editor from Chrome is fragile: it is a cross-origin iframe (no JS access), typing long text times out,
  keys typed in command mode become Jupyter shortcuts (cmd+a + Delete once deleted every cell). Use File → Import.
- Test notebook `notebookb3ee55e564` is empty junk from that; the owner may delete it.
- Kaggle account: user `faislol`, phone-verified, internet on. Claude must not sign in or verify for the owner.

## Git state (IMPORTANT before committing)
- The repo is standalone now: `~/Desktop/Colony-Local`, active branch `feature/openclaw-architecture`.
- Changes pending:
  - `colony/api/plugins.py` (new router for OpenClaw plugin manager)
  - `colony/api/__init__.py`, `colony/api/settings.py`
  - `colony/core/chat.py`, `colony/core/context.py`
  - `colony/engine/openclaw.py` (system prompt grounding, tool schemas, header filtering)
  - `colony/web/app.css`, `colony/web/index.html`, `colony/web/js/agent-editor.js`, `colony/web/js/settings.js`
  - `memory-bank/*.md`
- Commit only when the owner asks.

## Known rough edges / unverified
- **OpenClaw `toolSearch` meta-tool:** OpenClaw defaults to hiding tools behind a 2-stage search tool. We disabled this with `"toolSearch": false` in `~/.openclaw/openclaw.json` so DuckDuckGo `web_search` is exposed directly to local models.
- **OpenClaw `x-openclaw-model` header:** OpenClaw Gateway returns HTTP 404 if passed non-OpenClaw models (`kaggle/...`). Filtered in `colony/engine/openclaw.py` so it defaults to `ollama/nemotron-3-super`.
- **OpenClaw Gateway SQLite admission on restart:** On restart, OpenClaw Gateway validates `openclaw-agent.sqlite` (~5-10 s). Requests during this window receive HTTP 500 (`AgentDatabaseAdmissionError`). Once admitted, it runs normally.
- Laya is weaker than Jev on hard calls: "เหนื่อยจัง วันนี้งานเยอะมาก" went to Coder (0.86); a strategy message went to Writer until "strategy" was added to Thinker's "when". Clear, specific "when" rules matter.
- **Security housekeeping:** Never commit keys or paste them in chats.

## Recent decisions still in force
- Zero budget: fully local 4-daemon stack on the Mac (Ollama + Laya + Colony + OpenClaw Gateway). Kaggle GPU optional for heavier models.
- OpenClaw Gateway = Primary tool engine & plugin host (`colony/engine/openclaw.py`).
- Project folder explicit per workspace; without one agents are chat-only. Never `/` or home.
- No regex in our code (owner rule).
- Reply to the owner in Thai, in prose.

## Active Background Daemons (Verified Online)
- Port 11434: `ollama serve`
- Port 8790: `laya-runtime/serve.py` (spawned via Colony)
- Port 8765: `colony.cli --reload`
- Port 18789: `openclaw gateway run --allow-unconfigured`

