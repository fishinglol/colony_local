# OpenClaw wiring reference
_How Colony uses OpenClaw v2026.9.8 (`openclaw-main 2/`, no `.git`; version = its `package.json`). If it is replaced, re-verify `/readyz`, `x-openclaw-model`, plugin config keys in `api/plugins.py`, and the items below. 2026-10-12._

## Division of labour
| Concern | Owner | How |
|---|---|---|
| Model calls, sessions, compaction | OpenClaw | `POST /v1/chat/completions` (`gateway.http.endpoints.chatCompletions.enabled`), `gateway.auth.mode=none` (loopback). Auto-compaction (`safeguard`) verified live; Colony never compacts. |
| Agents | OpenClaw, config written by Colony | `agents.entries.<workspace>-<role>` = `{name, workspace, profile: minimal, alsoAllow, skills: [<this agent's own skill names>], contextInjection: continuation-skip}`; `agents.ownership: explicit`. Prompt ≈ 3.6–6k tokens (was ~46k with `tools.profile=full`). |
| Tools | OpenClaw | allowlist per role: `web_search`, `read`, `write`+`edit`, `exec`, `<server>__*`; `tools.toolSearch=false`. With a project folder the file tools are exactly the role's; without one every agent keeps read/write/edit (memory files). |
| Approvals | **OpenClaw** for native turns; Colony plugin for the HTTP fallback | Native: session `permissionMode` (`guarded` = a human approves exec) → events `exec.approval.requested`, answered with `exec.approval.resolve` over the WebSocket. OpenClaw only asks before `exec` (not before write/edit), so file-changing and connector tools are still sent to Colony's gate in native sessions (`native: true`). Fallback: `engine/colony-gate/` (systemPatterns §6). Not available over HTTP natively. |
| Memory | OpenClaw files, Colony folders | shared `self_improve/<ws>/` + per-agent dir; `memory.search` keyword-only; nightly dreaming; `systemAgent=main`, heartbeat `0m`, `skills.workshop.autonomous=off` so nothing runs without the user. |
| MCP | OpenClaw `mcp.servers` | `core/mcp.py` is only the editing layer (validation, masking). URL servers use `streamable-http`; `/sse` URLs stay `sse`. |
| Plugins | OpenClaw `plugins.entries` | `api/plugins.py` exposes 18 (Web & Search, Automation, Code & Sandbox, Memory & Brain, Integrations) with hot reload. |
| Routing (who answers) | **Colony** | OpenClaw has multi-agent routing (`bindings`: channel/account/peer/guild → `agentId`, `docs/concepts/agent-bindings.md`) but only for inbound channel messages; Colony addresses agents by explicit `agentId` (`chat.send`, completions), so the decider and `@Name` stay in Colony. Agent-to-agent: OpenClaw has `sessions_spawn`/`sessions_send` (`tools.agentToAgent`, `subagents.allowAgents`), unused: child sessions would not reach the shared conversation and fence/approval inheritance is unverified. Handoff is Colony's (systemPatterns §4b). |
| Project-folder fence | **OpenClaw** (native turns) / Colony gate (fallback) | Native: `sessions.create {cwd, permissionMode}` makes the project folder the session's `sessionRoot` (needs operator.admin); anything outside → "Path escapes sandbox root". Fallback: the gate. Agent workspaces are NOT the user's project folder. |
| Chat from the app | **OpenClaw WebSocket** | Coucou `GatewayClient`: `chat.send`, `sessions.*`, `commands.list`, `agents.list`, events `agent`/`chat`/`exec.approval.*`. Needs a signed device identity as `openclaw-macos`/`ui`; loopback auto-pairs and (auth `none`) grants admin. |

## Config keys Colony sets in `~/.openclaw/openclaw.json` (all via `config_lock`, file chmod 0600)
`agents.ownership`, `agents.entries.*`, `agents.defaults.systemAgent`, `agents.defaults.heartbeat.every`, `memory.search.*`, `tools.toolSearch`,
`gateway.http.endpoints.{chatCompletions,responses}`, `plugins.load.paths` + `plugins.entries.colony-gate` (hook timeout), `mcp.servers`, `models.providers.ollama.*` (set by user/OpenClaw).

## Behaviours worth remembering
- Per-turn model: header `x-openclaw-model`; non-OpenClaw ids make the Gateway answer 404, so Colony sends it only for `ollama/…`/`openclaw/…`.
- `ensure_agent` rewrites stale entries on a role's next turn; waits up to 150 s for a new agent; a changed tool set takes ~5 s hot reload.
- A gate plugin must be a folder with `openclaw.plugin.json` (`activation.onStartup: true`); check the `[gateway] http server listening (N plugins: …)` log line.
- `openclaw plugins inspect <id>` without `--runtime` shows no hooks even when fine.
- Images: ≤8 `image_url` parts / 20 MB per request, data URIs. PDFs: `/v1/responses` (enabled, 10 pages) — OpenClaw keeps file text out of the session, later turns can't re-read it.
- Compaction caveat: a brand-new session in a long conversation is seeded with only the last `HISTORY_MAX_MESSAGES` (60).
- Dreaming promotion needs recalls across several days (min score 0.75, 3 recalls, 3 distinct queries) — not configurable, not yet seen to fire naturally.
- Cross-language memory search would need embeddings (Ollama `bge-m3`/`nomic-embed-text` ~0.3–1.2 GB); not done, owner decides.
- Gateway failure modes: start-up SQLite admission (HTTP 500 for ~10 s), "Sessions remain unavailable" for minutes, self-restart on config reload races, and a failed shutdown leaving a lease (see systemPatterns §10).

- OpenClaw's `/new` archives the agent's model session only; the Colony conversation is archived by Colony (`archive_before`).

## Gateway RPCs the app uses (WebSocket, protocol v4)
`connect` (device-signed) · `agents.list` · `commands.list` · `sessions.create {key, agentId, cwd, permissionMode}` · `sessions.patch {key, model}` · `sessions.messages.subscribe` · `chat.send {sessionKey:"agent:<id>:<name>", agentId, message, attachments, idempotencyKey}` · `exec.approval.resolve {id, decision: allow-once|allow-always|deny}`.
Not used: `skills.install` (ClawHub slug / upload / dependency installers only, no git URL), `sessions.delete` (needs operator.admin; test sessions were cleaned with it once), Control UI (:18789/ → 503, runtime/UI build ids differ).
