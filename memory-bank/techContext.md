# Tech Context — Colony Local

All commands run from the repo root `~/Desktop/Colony-Local` (there is no `local/` folder any more).

## Stack
- **Backend:** Python (venv at `.venv`, currently 3.14.6; `requires-python >=3.10`),
  FastAPI ≥0.115, uvicorn[standard], pydantic ≥2 + pydantic-settings, certifi.
  Dev: pytest, httpx. **No other runtime dependencies** (HTTP is stdlib `urllib`).
- **UI:** plain HTML/CSS + ES-module JS served by the same FastAPI app (same
  origin → no CORS, deliberately). No bundler, no framework, no npm for the UI.
- **Native window:** Tauri 2 (Rust 1.98, `tauri` crate 2.11.x, npm `@tauri-apps/cli` ^2,
  Node 24; `tauri-plugin-dialog` for the folder picker).
- **Tool engine:** Pi `@earendil-works/pi-coding-agent` **0.87.1** (MIT, TypeScript, needs Node ≥22.19) +
  `pi-mcp-adapter`, pinned in `pi-runtime/package.json` (~437 MB of node_modules).
- **Models:** OpenRouter (any id; OpenAI is a legacy plain-chat fallback) **or the owner's Kaggle GPU**: ids
  `kaggle/<ollama name>` → Ollama behind a cloudflared quick tunnel in a Kaggle notebook (`kaggle/colony_server.py`).
  Current Kaggle models: gemma4:12b, ornith:9b, qwen3.5:9b (all tool-capable; see activeContext "Model shootout").
- **Decider:** Laya (`laya[serve]==0.3.21`, Apache-2.0, mmBERT "multilingual" checkpoint ~322M, non-generative) in
  `laya-runtime/.venv` — Python 3.11 (pyenv 3.11.13), torch 2.2.2, transformers <5, numpy <2 (the only combo that runs
  on an Intel Mac). Weights in `~/.cache/huggingface`. Started by `colony` on port 8790. Jev (OpenRouter) otherwise.
- **Owner's hardware:** MacBook Pro 13" 2017, Intel i5 dual-core 2.3 GHz, 8 GB RAM, Intel Iris Plus 640, macOS Ventura
  13.7.8 — cannot run chat LLMs locally (hence Kaggle); fine for Laya (~770 MB RAM).
- **Kaggle:** free 2× Tesla T4 (15 GB each), 31 GB RAM, ~57 GB disk, ~30 GPU-hours/week, runs up to 12 h.

## How to run / verify
```bash
# once
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
(cd pi-runtime && npm install)                # only needed for agents with tools
(cd desktop && npm install)                   # only needed for the native window
~/.pyenv/versions/3.11.13/bin/python -m venv laya-runtime/.venv \
  && laya-runtime/.venv/bin/pip install -r laya-runtime/requirements.txt   # local decider (optional)

# run
.venv/bin/colony                              # server + Laya + opens the browser
.venv/bin/colony --reload --no-open           # dev: restart on code change
(cd desktop && npm run dev)                   # native window (first Rust compile ~7 min; the script is `dev`)

# test
.venv/bin/python -m pytest -q                 # 187 tests, ~50 s (real-Pi tests skip if pi-runtime missing)
(cd desktop/src-tauri && cargo check)         # Rust compiles
```
- Kaggle side: see activeContext "How the owner runs it" (Save & Run All with GPU → Logs → URL → Settings).
- CLI flags: `--port` (default 8765) `--host` `--no-open` `--reload` `--exit-with-parent` (desktop shell only).
- **Testing against the real stack without touching the owner's data:** start Colony with a throwaway HOME, e.g.
  `HOME=<scratch>/home HF_HOME=~/.cache/huggingface OPENROUTER_API_KEY= .venv/bin/colony --no-open --port 8769`
  (HF_HOME keeps Laya from re-downloading), then drive `/api/settings`, `/api/roles`, `/api/messages` with curl/python.
  This is how the 2026-09-29 Kaggle run was verified. Kill it with `pkill -f "colony --no-open --port 8769"` (Laya follows).
- **Tools path with no API key:** run `tests/fake_llm.py`'s server on a fixed port, start colony with
  `HOME=<throwaway> OPENROUTER_API_KEY=sk-fake OPENROUTER_BASE_URL=http://127.0.0.1:<port>/v1 .venv/bin/colony --no-open --port 8767`,
  send `WRITE hello.txt hi` to a tools-enabled agent (custom id like `acme/fake-a`).
- `.claude/launch.json` (untracked, per machine) may hold preview configs `colony-local-mock` (8766) / `colony-local-tools`
  (8767) with scratchpad HOMEs — recreate when needed. Hard refresh (Cmd+Shift+R) once after UI changes.

## Configuration (`colony/config.py`, env or `~/.colony/.env`)
| Setting (env) | Default | Notes |
|---|---|---|
| `OPENROUTER_API_KEY` | none | set in the Settings modal, never in chat/code (owner's balance is negative now) |
| `KAGGLE_BASE_URL` | none | Settings modal; the notebook's tunnel URL + `/v1`; changes every run |
| `KAGGLE_CONTEXT_WINDOW` | 16384 | must equal the notebook's `CONTEXT` / OLLAMA_CONTEXT_LENGTH |
| `LAYA_URL` | set by `colony` when `laya-runtime/.venv` exists | local decider instead of Jev |
| `OPENROUTER_ROUTING_MODEL` | `deepseek/deepseek-v4.1-flash` | memory review + compaction; a `kaggle/…` id sends them to Kaggle |
| `WORKSPACE_DIR` | none | legacy: only read once to give the first workspace its project folder |
| `PI_BIN` | none → `pi-runtime/node_modules/.bin/pi` → PATH | |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | used by Pi only; tests point it at a fake |
| `TOOLS_TURN_TIMEOUT_SECONDS` / `APPROVAL_TIMEOUT_SECONDS` | 600 / 120 | |
| `CHAT_RETRIES` | 3 | plain chat only |
| `MAX_ATTACHMENT_MB` | 20 | per attached file |
| `COMPACTION_ENABLED` / `COMPACT_AT_TOKENS` / `COMPACT_KEEP_TOKENS` | true / 24000 / 8000 | summarise the old part of a long conversation |
| `HISTORY_MAX_MESSAGES` / `MAX_OUTPUT_TOKENS` | 60 / 4096 | |
| `JEV_MODEL` / `JEV_DECISIONS_URL` | `typesafe/jev-1.13` / alpha decisions URL | |
| `MOCK_MODE` | false | skips real LLM calls (tests, UI dev) |
| `DATA_DIR` | `~/.colony` | |
| `HOST` / `PORT` | 127.0.0.1 / 8765 | Laya uses 8790 (fixed, `cli.LAYA_PORT`) |
| `SELF_IMPROVE_ENABLED` / `SELF_IMPROVE_INTERVAL_TURNS` | true / 5 | memory review |

## HTTP API (`/api`)
`GET|PUT /mcp` (connectors, secrets masked), `POST /mcp/composio` (`{key}`), `POST /open-url` (`{url}`) · `POST /workspaces/{id}/attachments` (`{name, data: base64}` → `{id, name, kind, mime, size}`), `GET /workspaces/{id}/attachments/{aid}` · `PATCH /workspaces/{id}` also takes `mode` and `folder` ·
`GET /health` (incl. `tools: {pi_installed}`) ·
`POST /messages` (`{message?, attachments? (ids), workspace_id?, role_id?, channel?}`; blocks until the
reply, including any approval waits; response has `decided_by`, `confidence`, `role_name`, `model`) · `GET|POST /workspaces`, `PATCH|DELETE /workspaces/{id}`,
`GET /workspaces/{id}/messages` (also returns `compaction`) · `GET /context?workspace_id=` · `GET|PUT /roles?workspace_id=` · `GET /models` (Kaggle models first, then catalog models + capabilities, `catalog` flag) · `POST /models/test` (`{model, reasoning?}`) ·
`GET /models/tools?model=` (`supported: true|false|null`) · `GET /approvals` ·
`POST /approvals/{id}` (`{approve}`) · `GET|POST /settings` (`openrouter_api_key`, `kaggle_base_url`) · `GET /memory/summary`, `/memory/context` (`?workspace_id=`).
`workspace_id` omitted = the first workspace. Laya: `POST http://127.0.0.1:8790/v1/systemone`, `GET /health`.

## OpenRouter facts worth knowing (currently unusable: balance negative)
- Public `GET https://openrouter.ai/api/v1/models` (no key) gives `context_length`
  and `supported_parameters` (contains `"tools"` if the model can call tools).
- Free models: 20 req/min; **50 req/day if <$10 credits ever bought** (1000 if ≥$10);
  429s often mean an upstream shared pool is full, not your quota.
- Tool-capable & verified with Pi: `nvidia/nemotron-3-ultra-550b-a55b:free`, `nvidia/nemotron-3-super-120b-a12b:free`.
  **`z-ai/glm-5.2:free` cannot use tools** (404); paid `z-ai/glm-5.2` can.

## Constraints from the owner
- No regex anywhere in our code; ask before adding any dependency; reply to the owner in Thai, explain in detailed prose.
- Zero budget right now: prefer free paths (Kaggle, Laya) and say so when something would cost money.
- Check this memory bank first at the start of a session (the owner asks for it).
