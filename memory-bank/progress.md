# Progress — Colony Local
_Compact changelog, newest first. Details of "how" live in `systemPatterns.md` / `openclaw-capabilities.md`._

## 2026-10-11/12 — Coucou ↔ Gateway directly, skills, native permissions
- **Skills per agent**: folders under the agent's workspace, allowlist in OpenClaw config, gate allows reading them, decider sees them; Settings → Skills (folder, GitHub, remove); agents can install from chat.
- **Gateway client** (`GatewayClient.swift`): WebSocket + device identity; direct chat for agent rooms and `# mix` (decider in `prepare`), live status, tool steps, native approvals, "/" command menu, image/PDF attachments. Colony endpoints `/api/turns/prepare|finish`.
- **Native permissions**: session `cwd` + `permissionMode` fence by OpenClaw, colony-gate skipped for `:native-` sessions; memory writes inside a project folder handled by Colony (`keep_if_asked`).
- New workspaces get their own project folder; 3 old workspaces and the empty `my-business` folder deleted at the owner's request; test sessions/devices cleaned.
- Fixes found on the way: slash-command replies polluted team context (`drop_commands`), Keychain prompt hangs unsigned test binaries, Gateway handshake resets for ~2.5 min after restart.

## 2026-10-11 — Coucou front-end + Jev API
- `coco_local/` (Coucou fork) became a Colony client: rooms, workspace switch, model menu, Home, Settings → Colony, attachments, status dots.
- Coucou fixes: file-drop hang, accidental desktop Mochi, real inactivity auto-close, Thai `**bold**`, chat island height, optimized build.
- Decider: Jev through BeatAPI (+ Laya fallback, local Laya skipped with key), UA fix for Cloudflare 1010, `Jev NN%` tag, tests. Gateway incident + zombie lease documented.
- Memory bank rewritten compact.

## 2026-10-10 — UI + OpenClaw 100%
- Minimal web theme; "Worked for Ns" trace (`after_tool_call` → `/api/activity/tool`); agent settings window (Profile/Personality/Tools/Memory); `GET /api/roles/{id}/files`.
- One OpenClaw agent folder + SOUL.md per agent, shared memory via `extraPaths`; persona in SOUL.md, rules in AGENTS.md; persona-hash session key.
- Gateway readiness handling (`gateway_prepared`, retry on 500, wait after restart); dreaming/`memory_search`/PDF via `/v1/responses` verified.
- **Cut-over:** deleted `llm/providers.py`, `core/compaction.py`, `colony/memory/*`, OpenRouter/OpenAI/Kaggle settings and code, Jev branch (re-added 2026-10-11); models = Ollama pool.
- Migration steps done: per-role agents + no double history, lean agents (46k → ~5k tokens), MCP → `mcp.servers`, approvals via colony-gate plugin, compaction, memory, attachments, context gauge, workspace-delete cleanup.

## 2026-10-09 — Direction change: OpenClaw-first
- Owner decision: Colony = UI shell, backend 100% OpenClaw. `colony.cli` starts the Gateway; Pi, own agent loop, `pi-runtime/` removed; `openclaw-main 2/` gitignored.
- Plugin Manager (`api/plugins.py`, 18 plugins), Agent Capability cards, grounding prompt, `toolSearch:false`.

## Before 2026-10-09 (one line each)
- 2026-09-30/10-01: Kaggle GPU provider and model exam (later removed). 2026-09-29: Laya local decider, workspaces (owner's 5 decisions), project folder, approvals, MCP/Composio, context chip.
- 2026-09-24→26: MVP lifted from ColonyBridge `ai_ant`, package split, history store, Tauri shell, model picker, reasoning levels, attachments, compaction, memory layer (all since replaced by OpenClaw equivalents).
