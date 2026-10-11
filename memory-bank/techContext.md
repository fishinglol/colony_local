# Tech Context — Colony Local
_Stack, config, how to run and test. All commands from repo root. Updated 2026-10-12._

## Stack
- **Backend:** Python 3.14 in `.venv` (`requires-python >=3.10`), FastAPI, uvicorn, pydantic(+settings), certifi. HTTP is stdlib `urllib`. Dev: pytest, httpx. **No other deps.**
- **UI:** plain HTML/CSS/ES modules, no bundler. **Tauri 2** window in `desktop/`. **Coucou** Swift app in `coco_local/` (XcodeGen, macOS 13+).
- **Engine:** OpenClaw Gateway from source (`openclaw-main 2/`, Node 24.16, `node openclaw.mjs gateway run --allow-unconfigured`), started by `colony.cli`.
- **Models:** Ollama (cloud or local, :11434) through OpenClaw: nemotron-3-nano:30b, nemotron-3-super, nemotron-3-ultra, gemma4:31b, gpt-oss:20b/120b.
- **Decider:** Jev API (api.beatapi.io) → Laya (`laya-runtime/`, optional) → Nemotron/Ollama.

## Processes / ports
| Port | Process | Notes |
|---|---|---|
| 8765 | `colony.cli` (FastAPI + web UI) | `--no-open --reload --port --host` |
| 18789 | OpenClaw Gateway | started by Colony; `/readyz` 200 ≈ 1 min, agent DBs minutes later; log `~/.colony/openclaw.log` |
| 8790 | Laya | only when no `JEV_API_KEY`; `/health`; log `~/.colony/laya.log`; ~1.5 GB RAM |
| 11434 | Ollama | local models / embeddings if ever needed |

## Config (`colony/config.py`; env vars **beat** `~/.colony/.env`)
`OLLAMA_BASE_URL`, `OLLAMA_API_KEY`, `OLLAMA_CONTEXT_WINDOW` · `OPENCLAW_GATEWAY_ENABLED/URL/TOKEN` · `JEV_API_KEY` (never in chat/logs), `JEV_URL`
(`https://api.beatapi.io`), `JEV_MODEL` (`jev-1.13-free` | `jev-1.13`) · `LAYA_URL` (set by `colony` unless Jev key) · `DATA_DIR` (`~/.colony`) ·
`HISTORY_MAX_MESSAGES` (60) · `MAX_ATTACHMENT_MB` (20) · `PROJECTS_DIR` (`~/Documents/Colony Projects`, a new workspace's folder) · `APPROVAL_TIMEOUT_SECONDS` (120) · `MOCK_MODE` · `HOST`/`PORT`. `WORKSPACE_DIR` is read once by the legacy migration.
OpenClaw's own config is `~/.openclaw/openclaw.json` (path override `OPENCLAW_CONFIG_PATH`); its Ollama key is separate from `~/.colony/.env`.

## On-disk (`~/.colony/`)
`.env` · `workspaces.json` (workspaces + teams) · `history.json` (+ `colony.sqlite` mirror) · `self_improve/<ws>/` (shared memory) ·
`openclaw-agents/<agent_id>/` (per-agent files) · `openclaw_seen.json`, `openclaw_usage.json` · `attachments/<ws>/` · `openclaw-agents/<agent>/skills/` · logs. Project folders live wherever the workspace says (default `~/Documents/Colony Projects/<name>`).
Writes go through `JsonStore` (atomic temp + replace). Unknown JSON keys are preserved.

## Run / test
```bash
.venv/bin/colony                          # server + Gateway (+ Laya if no Jev key) + opens browser
.venv/bin/colony --reload --no-open       # dev
.venv/bin/python -m pytest -q tests       # 152 pass, ~40 s. NOT bare pytest (it would collect openclaw-main 2/)
(cd desktop && npm run dev)               # Tauri window
```
Coucou build: see `systemPatterns.md` §9. Laya on an Intel Mac needs Python 3.11 + transformers <5 + numpy <2 (`laya-runtime/requirements.txt`).

## Test conventions
`tests/conftest.py` autouse: own `DATA_DIR` and `PROJECTS_DIR`, `MOCK_MODE=true`, blank `LAYA_URL`/`JEV_API_KEY`, temp `OPENCLAW_CONFIG_PATH`, fake Gateway log.
Never touch the real `~/.colony/.env` (`config._ENV_FILE`) or `~/.openclaw`. `test_web.py` checks every `$('id')` exists and every JS file passes `node --check`.
Real-model checks are scripts against a throwaway-HOME dev server, not pytest.
