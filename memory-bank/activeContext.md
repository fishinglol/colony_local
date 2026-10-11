# Active Context — Colony Local
_Current state, open work, owner rules. Updated 2026-10-12. History: `progress.md`. Hand-off for the owner: `handoff.md`._

## State right now
- Stack runs locally: Colony :8765 → OpenClaw Gateway :18789 → Ollama. Decider = **Jev API** (`JEV_API_KEY` in `~/.colony/.env`, model `jev-1.13-free`); local Laya is not started while the key is set.
- Three front-ends (web, Tauri, Coucou). Coucou is the one the owner shapes: it talks to the **Gateway directly** for chat (see "How a turn runs"); Colony is still the team/workspace/decider/memory service.
- 152 tests pass (`.venv/bin/python -m pytest -q tests`). Nothing is committed (branch `feature/openclaw-architecture`, many uncommitted changes; `coco_local/` untracked with its own `.git`).
- One workspace left: **my business** (`ws_76c8b897db`). Its folder `~/Desktop/my-business` was deleted at the owner's request, so it is chat-only until a folder is set (new workspaces get one automatically).
- A Colony restart restarts the Gateway: ~2.5–3 min until `readyz` shows the event loop not degraded; WebSocket connections reset before that.

## How a turn runs now
- Direct chat and `# mix` (message with or without images/PDFs): app → `POST /api/turns/prepare` (`core/native_turn.py`: decider when no `role_id`, `ensure_agent`, persona files, unseen team context + capability text, attachments, fence) → `GatewayClient.chat` (WebSocket: status, deltas, tool steps, approvals) → `POST /api/turns/finish` (saves to the shared conversation, memory keep, seen marker). Code: `ColonyStore.runDirect`.
- Fallback (`POST /api/messages` → `core/chat.py`, HTTP chat-completions): used when `prepare` says `native:false` (video/audio, missing file, Gateway not ready), when the Gateway cannot be reached at all, with `colonyDirectGateway=false`, and by the web UI/Tauri. Still guarded by colony-gate.
- Slash commands (`/status`, `/skill …`): menu from Gateway `commands.list`, agent's own chat only; sent as typed; the command and its reply are dropped from the context agents get (`context.drop_commands`).

## Native permissions (OpenClaw decides, not Colony)
`prepare` returns `cwd` (project folder, or the team's memory folder when the workspace has none) and `permission_mode` (`guarded` if the agent may write/run commands or has no folder, else `read-only`; workspace mode `plan` strips write/bash first). The app calls `sessions.create {key, agentId, cwd, permissionMode}` (needs **operator.admin**, which the loopback Gateway with `auth.mode=none` grants on connect), then `sessions.patch {model}` (retried on "Retry the request"). Session name `native-<session_user>-<hash(root|mode)>`: another fence = another session.
colony-gate skips `before_tool_call` for session keys containing `:native-`; `after_tool_call` reporting stays (steps). Verified live: read inside the root ok; `/etc/hosts` → "Path escapes sandbox root"; `exec` → native approval card (allow/deny respected); 0 gate calls.
Costs the owner accepted (option B): with a project folder the agent cannot write the shared memory files (outside the root) — Colony keeps what the user asks to remember (`keep_if_asked`, `agents_md(writable=False)`); the tool allowlist is exactly the role's file tools (`_tool_allowlist(fenced=True)`); per-agent write=`ask` is not expressible (guarded lets writes inside the root through and asks for commands).

## Skills
Per agent, in `openclaw-agents/<agent>/skills/<name>/SKILL.md` (nested `skills/<group>/<name>` also counts). Settings → Colony → agent → **Skills**: Add from folder, **Add from GitHub** (`add_skills_from_github`, shallow clone, https://github.com only; Colony-side because Gateway `skills.install` takes ClawHub slugs/uploads, not git URLs), remove. The agent's `skills` allowlist is written by `ensure_agent`; the decider sees each agent's skill names. An agent can also install a skill from chat (folder or GitHub link via `exec`) — asks the user per file. An agent opens a skill with OpenClaw's `skills_read` (name only); `_tool_allowlist(skills=True)` adds exactly that tool, never `read` (project files stay off) — without it the call answers "Tool skills_read not found". A skill whose `metadata.openclaw.requires.env` is unset (e.g. ScrapeCreators' `SCRAPECREATORS_API_KEY`) is `eligible:false` / not `modelVisible`, so the agent cannot open it: check `skills.status` before blaming the fence. Verified 2026-10-12 end to end with `dietrichgebert/ponytail` (6 skills): private chat and `# mix` (decider picked the skill's owner).

## Open work (not done)
1. **Gateway watchdog**: restart a dead Gateway from `colony/cli.py::_start_openclaw` (and reap the zombie).
2. **Gateway has no auth on loopback** (`auth.mode=none`): any local program can connect and get operator.admin. Set a Gateway password if that matters (then the app needs it).
3. Jev free tier = 1 req/min: top up or `JEV_MODEL=jev-1.13`; no Settings field for `JEV_API_KEY` yet.
4. Coucou: rename/delete workspace from the app; edit memory files; reasoning pills hidden; the "/" menu is mouse-only. The native flows were verified with Swift/Node harnesses and the owner's screenshots, not a full manual pass; release build needs a signing profile (unsigned dev builds also trigger Keychain prompts for the device key).
5. The HTTP fallback path and colony-gate can be deleted once native turns are trusted (then web/Tauri need their own Gateway client).
6. Cross-language memory search (embeddings) and a natural dreaming-promotion run are unverified. OpenClaw Control UI (:18789/) answers 503: its runtime and UI build ids differ.
7. Set a folder for "my business" (default would be `~/Documents/Colony Projects/my business`).
8. Decide whether to vendor/commit `coco_local/`.

## Owner rules (apply to every task)
- Reply in Thai, prose. Don't paste or log API keys; if one appears in chat, say to rotate it. Commit only when asked.
- Ask before adding dependencies. No regex in our code. Simplest working solution; check the memory bank before touching an area.
- Changing something security-relevant (permissions, scopes, deleting data) → explain and let the owner choose; the owner decides option A/B/C style.
- Coucou upstream rule: don't restyle shipped views; add new views / small seams; never hand-edit `.xcodeproj` (xcodegen isn't installed here, so new Swift files were added to `project.pbxproj` by script). With Colony on, Settings shows General, Active pills, Agents, Integrations, Colony, Shortcuts (only **Chat** hidden).
- Laya stays supported as the fallback decider.

## Facts that are easy to get wrong
- `~/.colony/.env` env vars: real shell env wins. Tests must not read the real `.env` (conftest blanks keys, sets `PROJECTS_DIR`).
- `GatewayClient` keeps its device key in the Keychain; a freshly compiled unsigned test binary waits forever on a Keychain prompt (looks like a WebSocket hang; Gateway log: `handshake timeout … ws_upgrade_started`). Test copies must swap `deviceKey()` for a file.
- A `gateway-client`/`backend` WebSocket client is "headless": exec approvals fail. Use `client.id=openclaw-macos`, `mode=ui` with a device identity.
- The OpenClaw source folder `openclaw-main 2/` is gitignored; Colony starts the Gateway from it (needs Node ≥24.16).
- A new workspace without a `folder` gets `~/Documents/Colony Projects/<name>`; `folder: ""` means chat only.
- Memory, SOUL.md, approvals, compaction, MCP are OpenClaw-side — don't rebuild them in Colony.
