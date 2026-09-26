# Active Context — Colony Local
_Last updated: 2026-09-26 (workspaces refactor done; tools via Pi and native window before that)_

## Where things stand right now
**Workspaces** (2026-09-26, owner's 5 decisions): the top level is now a workspace = own team (own models),
one continuous conversation, own memory, own project folder. See systemPatterns §3b. 119 pytest pass;
browser-verified in mock mode incl. the migration from legacy files (two old chats merged in time order,
legacy agents kept, per-workspace models, last workspace remembered on reload). The migration was also
dry-run on a COPY of the owner's real `~/.colony` (36 messages, 5 agents, memory intact); the real folder
migrates the first time the new server answers a request.
Earlier, working, tested and verified in the browser with a fake model:
- Multi-agent chat with Jev routing, shared context, rooms, context gauge, Thai errors.
- **Agents with tools** (Pi engine): per-agent read / edit / run permissions, approval
  cards, workspace fence, tool-support lock in the editor. See systemPatterns §7–8.
- **Native window** (`local/desktop`): opens, loads the UI (verified from server logs
  and by the owner running it), server stops with the window.

**Connect-a-tool window (2026-09-26, latest)** replaced the editor's permission checkboxes (progress.md). 178 tests pass.
**Web search + Connectors/MCP + Composio (2026-09-26):** see progress.md and systemPatterns §4f. 176 tests pass; a real Composio account/key was NOT tried (needs the owner's consumer key entered in sidebar → Connectors).
**Compaction (2026-09-26):** old part of a long conversation is summarised in the background (systemPatterns §4e); 154 tests pass; not verified with a real model.
**Newest (2026-09-26, after reasoning):** chat-box attachments (+ menu, drag-drop, paste), capability-aware Jev (filters agents by
model input modalities), and workspace modes (Auto/Manual/Accept edits/Plan/Bypass). See systemPatterns §4d. 142 tests pass.
Native folder picker approved: `tauri-plugin-dialog` now powers Add folder. The composer project control lists workspaces as projects; New project creates and opens a new workspace, and Add folder binds only the current workspace.

## Git state (IMPORTANT before committing)
- 2026-09-26: the OWNER (deliberately) committed all of `local/` + this memory bank to the branch their main worktree is on,
  **`feat/database-studio-filter-export-schema-canvas`**, as `41d4ab2` "feat(colony-local): add workspace project picker"
  (not pushed when checked). That commit also added the native folder picker (`tauri-plugin-dialog`, owner-approved), the
  composer folder button, and "chat only" workspaces (no folder = no Pi tools; the launch-folder fallback is gone).
  Do NOT move it to `feat/colony-local` unless asked. Older origin branch `feat/colony-local` stops at `e56f3bd`.
- 2026-09-26: Claude committed everything after that as "feat(colony-local): attachments, modes, compaction, web search, connectors" on the same branch (attachments, modes, compaction, web search, connectors,
  Connect-a-tool window, Browse…; 178 tests). Not pushed. The bullet below describes what was uncommitted BEFORE that commit.
- Claude's later edits (tauri capability `remote.urls` for the dialog IPC, folder-aware attachment warnings, +1 test) are
  uncommitted on top of it. The main worktree has lots of unrelated uncommitted frontend work: never switch its branch,
  never `git add -A`. Suggested (not done): drop `local/colony_local.egg-info/` from git and ignore it.
- Push only when the owner asks.

## Known rough edges / unverified
- **Real OpenRouter model through the in-app tools path has not been run** (only the
  spike script did, with nemotron-3-ultra/super OK; GLM free = no tools; Qwen = 429).
- Tauri window was not seen visually by Claude; Cmd+Q / close-button path untested
  (force-kill path is tested). A built `.app` (`npm run build`) does NOT contain Python
  or Node/Pi — needs bundling (PyInstaller-style sidecar + Node) → new dependencies,
  ask first. GUI apps don't inherit the shell PATH (`node` for Pi must be findable).
- Pi starts fresh each turn (~2–3 s overhead measured with a fake model) and retries
  429/5xx up to 3× (burns free quota). A long-lived RPC process would be faster but
  needs per-turn persona switching.
- Earlier tool calls/results aren't in later prompts — only the `🛠` summary line is
  (files are the truth; agents can re-read them).
- Approvals are global, not per workspace, so the UI **refuses to switch or delete a workspace while a
  reply is in flight** (an agent waiting for a yes/no in another workspace would just time out).
- **Long-lived conversation:** one workspace = one endless conversation. `history_max_messages` was raised
  16 → 60 and the model's window still trims the oldest messages; nothing summarises old context yet
  (proposed to the owner as a separate step, not started). 60 messages × every turn costs more tokens/latency
  and hits free-model limits sooner.
- Old global `roles.json` / `WORKSPACE_DIR` are legacy (read once by the migration, then ignored).
- The owner's team (migrated into workspace "Personal" from `roles.json`): Coder is on `z-ai/glm-5.2:free` (**no tools**, so
  the switches are locked until they pick another model); Writer is on
  `google/gemma-4-31b-it:free` again (429-prone; Claude had switched it to nemotron-3-super
  but it reverted, probably via the editor); Research uses paid `perplexity/sonar-pro`.
  Claude must not edit that file without being asked.
- Owner's OpenRouter account is near zero credits (402 seen); free-model daily cap applies.
- **Security housekeeping:** the owner pasted an OpenRouter key in chat twice. Never use
  it; remind them to delete/rotate it at openrouter.ai/settings/keys.

## Recent decisions still in force
- Pi = tool engine, one process per turn, Colony history = single truth, no Pi sessions.
- Project folder: explicit per workspace (Workspace settings); without one, agents are chat-only and Pi never starts. Never `/` or home.
- bash cannot be fenced; default "ask"; UI warns on "Allow".
- Tools require an OpenRouter key; models must list `tools` in `supported_parameters`
  (unknown = allowed, but the run may fail with a clear message).
- Colony Local stays independent of `backend/` and `frontend/`.

## Sensible next steps (none started; ask the owner)
1. Owner tries a real tools turn in the desktop app (Workspace settings → project folder, editor →
   nemotron model → ask it to create a file) and reports back; fix what breaks.
2. Commit + push the uncommitted work (above).
3. Native folder picker in Settings (Tauri dialog plugin → new dependency, ask).
4. Git checkpoint per agent turn (commit tagged `[Coder] …`) + diff view in the
   approval card — from the original plan, not built.
5. Shippable app: bundle Python and Node/Pi (ask before adding PyInstaller etc.).
6. Faster turns: keep one Pi RPC process alive per workspace.
7. Summarise/compact the older part of a workspace's conversation (memory review already learns facts; this
   would keep the thread of work). Ask the owner first.
