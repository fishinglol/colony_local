# Tech Context — Colony Local

## Stack
- **Backend:** Python (venv at `local/.venv`, currently 3.14.6; `requires-python >=3.10`),
  FastAPI ≥0.115, uvicorn[standard], pydantic ≥2 + pydantic-settings, certifi.
  Dev: pytest, httpx. **No other runtime dependencies** (HTTP is stdlib `urllib`).
- **UI:** plain HTML/CSS + ES-module JS served by the same FastAPI app (same
  origin → no CORS, deliberately). No bundler, no framework, no npm for the UI.
- **Native window:** Tauri 2 (Rust 1.98, `tauri` crate 2.11.x, npm `@tauri-apps/cli` ^2,
  Node 24). Only `serde_json` besides Tauri in `Cargo.toml`.
- **Tool engine:** Pi `@earendil-works/pi-coding-agent` **0.87.1** (MIT, TypeScript,
  needs Node ≥22.19), pinned in `pi-runtime/package.json` (~437 MB of node_modules).
- **AI provider:** OpenRouter (primary). OpenAI is a legacy fallback for plain chat
  only (tools require OpenRouter). Jev = OpenRouter's alpha decisions endpoint.

## How to run / verify
```bash
# once
cd local && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
cd local/pi-runtime && npm install            # only needed for agents with tools
cd local/desktop && npm install               # only needed for the native window

# run
cd local && .venv/bin/colony                  # server + opens the browser
.venv/bin/colony --reload --no-open           # dev: restart on code change
cd local/desktop && npm run dev               # native window (first Rust compile ~7 min)
                                               #   (the script is `dev`; there is no `tauri` script)

# test
cd local && .venv/bin/python -m pytest -q     # 176 tests, ~30 s (real-Pi tests skip if pi-runtime missing)
cd local/desktop/src-tauri && cargo check     # Rust compiles
```
- CLI flags: `--port` (default 8765) `--host` `--no-open` `--reload`
  `--exit-with-parent` (desktop shell only). The folder you start `colony` from is the default project folder.
- **Verifying UI changes in the Claude preview browser:** `.claude/launch.json`
  (untracked, per-machine) has `colony-local-mock` (MOCK_MODE, port 8766) and
  `colony-local-tools` (port 8767). Their `HOME=` paths point into a session
  scratchpad — recreate when needed. For the **tools path with no API key**:
  run `tests/fake_llm.py`'s `_Handler` on a fixed port (see `test_engine.py` /
  the 2026-09-26 handoff entry), then start colony with
  `HOME=<throwaway> OPENROUTER_API_KEY=sk-fake OPENROUTER_BASE_URL=http://127.0.0.1:<port>/v1 WORKSPACE_DIR=<folder> .venv/bin/colony --no-open --port 8767`;
  send `WRITE hello.txt hi` to a tools-enabled agent (custom model id like
  `acme/fake-a` so the OpenRouter catalog doesn't lock it).
- **Hard refresh (Cmd+Shift+R) once** after UI changes; the server already sends
  `no-cache`.

## Configuration (`colony/config.py`, env or `~/.colony/.env`)
| Setting (env) | Default | Notes |
|---|---|---|
| `OPENROUTER_API_KEY` | none | set in the Settings modal, never in chat/code |
| `WORKSPACE_DIR` | none | legacy: only read once to give the first workspace its project folder |
| `PI_BIN` | none → `local/pi-runtime/node_modules/.bin/pi` → PATH | |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | used by Pi only; tests point it at a fake |
| `TOOLS_TURN_TIMEOUT_SECONDS` / `APPROVAL_TIMEOUT_SECONDS` | 600 / 120 | |
| `CHAT_RETRIES` | 3 | plain chat only |
| `MAX_ATTACHMENT_MB` | 20 | per attached file |
| `COMPACTION_ENABLED` / `COMPACT_AT_TOKENS` / `COMPACT_KEEP_TOKENS` | true / 24000 / 8000 | summarise the old part of a long conversation |
| `HISTORY_MAX_MESSAGES` / `MAX_OUTPUT_TOKENS` | 60 / 4096 | |
| `JEV_MODEL` / `JEV_DECISIONS_URL` | `typesafe/jev-1.13` / alpha decisions URL | |
| `MOCK_MODE` | false | skips real LLM calls (tests, UI dev) |
| `DATA_DIR` | `~/.colony` | |
| `HOST` / `PORT` | 127.0.0.1 / 8765 | |
| `SELF_IMPROVE_ENABLED` / `SELF_IMPROVE_INTERVAL_TURNS` | true / 5 | memory review |

## HTTP API (`/api`)
`GET|PUT /mcp` (connectors, secrets masked), `POST /mcp/composio` (`{key}`), `POST /open-url` (`{url}`) · `POST /workspaces/{id}/attachments` (`{name, data: base64}` → `{id, name, kind, mime, size}`), `GET /workspaces/{id}/attachments/{aid}` · `PATCH /workspaces/{id}` also takes `mode` ·
`GET /health` (incl. `tools: {pi_installed}`) ·
`POST /messages` (`{message?, attachments? (ids), workspace_id?, role_id?, channel?}`; blocks until the
reply, including any approval waits) · `GET|POST /workspaces`, `PATCH|DELETE /workspaces/{id}`,
`GET /workspaces/{id}/messages` (also returns `compaction`) · `GET /context?workspace_id=` · `GET|PUT /roles?workspace_id=` · `GET /models` (all catalog models + capabilities, `catalog` flag) · `POST /models/test` (`{model, reasoning?}`) ·
`GET /models/tools?model=` (`supported: true|false|null`) · `GET /approvals` ·
`POST /approvals/{id}` (`{approve}`) · `GET|POST /settings` (API key) · `GET /memory/summary`, `/memory/context` (`?workspace_id=`).
`workspace_id` omitted = the first workspace.

## OpenRouter facts worth knowing
- Public `GET https://openrouter.ai/api/v1/models` (no key) gives `context_length`
  and `supported_parameters` (contains `"tools"` if the model can call tools).
- Free models: 20 req/min; **50 req/day if <$10 credits ever bought** (1000 if ≥$10);
  429s often mean an upstream shared pool is full, not your quota.
- Tool-capable & verified with Pi: `nvidia/nemotron-3-ultra-550b-a55b:free`,
  `nvidia/nemotron-3-super-120b-a12b:free`. `qwen/qwen3.8-27b:free` advertises tools
  (untested — 429 at the time). **`z-ai/glm-5.2:free` cannot use tools** (404 "No
  endpoints found that support tool use"); paid `z-ai/glm-5.2` can.
- Owner's account has almost no credits: paid models (e.g. `perplexity/sonar-pro`)
  may return 402.

## Constraints from the repo / owner
- No regex anywhere (owner rule); ask before adding any dependency; reply to the
  owner in Thai; explain in detailed prose, not terse bullets.
- `CLAUDE.md` says check `memory bank/` first — this folder is the one for `local/`.
