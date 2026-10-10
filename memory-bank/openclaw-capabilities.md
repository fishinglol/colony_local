# OpenClaw capabilities check (step 1 of the OpenClaw-first migration)
_2026-10-09. Read from `openclaw-main 2/` (v2026.9.8): `docs/` and `src/`. Nothing was run against a live Gateway except as noted.
The owner's three architecture diagrams (overview, harness, memory) were checked against the source: every path they name exists
(`src/gateway|agents|daemon|cron|audit|security|tts|meeting-bot|media-generation|mcp|cli|tui`, `ui/`, `apps/ios|android|macos`,
`packages/agent-core` incl. `agent-loop.ts`, `harness/compaction`, `harness/session`, `env/kill-tree.ts`,
`src/agents/embedded-agent-runner`, `src/agents/harness/selection.ts`, `extensions/{telegram,discord,slack,whatsapp,codex,memory-*}`).
Memory diagram matches `docs/concepts/memory.md` (USER.md, MEMORY.md, memory/YYYY-MM-DD.md, DREAMS.md, dreaming sweep, pre-compaction flush)._

## How Colony talks to it today
`POST /v1/chat/completions` (enabled in `~/.openclaw/openclaw.json`: `gateway.http.endpoints.chatCompletions.enabled`), `gateway.auth.mode=none`.
Colony always sends `model: "openclaw"` = the default agent `main`; `resolve_agent_target(role_id)` is computed but **never used**
(`agent_target` unused in `engine/openclaw.py`). Per-role model goes in header `x-openclaw-model`, only for `ollama/` and `openclaw/` ids.
Session key comes from the OpenAI `user` field (`ome-<ws>-<channel>-<role>`).

## Verdicts
| Colony piece | OpenClaw can replace it? | Evidence / catch |
|---|---|---|
| Compaction (`core/compaction.py`) | **Yes** | Auto-compaction on by default (`agents.defaults.compaction.mode`, safeguard), per session, summary kept in transcript, memory flush before compaction. Catch: works on OpenClaw's own session history (see "double history"). |
| Multiple agents per workspace | **Yes, but not wired** | Isolated agents (`agents.entries.<id>`, own workspace, `agentDir`, SQLite sessions); `model: "openclaw/<agentId>"` or `x-openclaw-agent-id` selects one; `openclaw agents add`, and RPC `agents.*` mutations. Today only `main` exists in `~/.openclaw/openclaw.json`. |
| Memory (`colony/memory/*`) | **Yes in design, big migration** | OpenClaw memory = Markdown files in the *agent workspace* + dreaming + `memory_search`. Colony's layer is already a Python clone of that design, but stores under `~/.colony`. `memory.search.enabled` is **false** in the current config. Plugins: `extensions/memory-core`, `memory-lancedb`, `memory-wiki`. |
| MCP / connectors (`core/mcp.py`) | **Yes** | `mcp.servers` in OpenClaw config (Streamable HTTP / SSE / stdio), `openclaw mcp doctor <name> --probe`, hot reload. Colony would only write that config (like `api/plugins.py` already does for plugins). |
| Attachments | **Partly** | `/v1/chat/completions`: max 8 `image_url` parts from the latest user message, URL images off by default (`images.allowUrl=false`), so send data URIs. Non-image files need `/v1/responses` (`input_file`, disabled by default) or the `document-extract` plugin (enabled). |
| Approvals (`core/approvals.py`, UI cards) | **Not over HTTP** | Approval API is Gateway **WebSocket RPC** (`exec.approval.list/waitDecision/resolve`, `approval.get/resolve`, scope `operator.approvals`). No HTTP route found. Also, with `tools.profile=full` and a full-permission gateway session, host exec **skips** approvals; `tools.exec.mode` (`deny/allowlist/ask/auto/full`) is not set in our config. Colony needs a WS client, or runs in `ask`/`auto` mode and surfaces approvals itself. Unverified live. |
| Project-folder fence (`core/project_folder.py`) | **Different model** | Agent `workspace` is the default cwd, *not* a sandbox unless sandboxing is enabled (`docs/gateway/sandboxing`). Colony currently passes the folder via prompt only; do not delete the fence until OpenClaw sandbox config is set per agent. |
| Model catalog / providers | Yes for calling | `/v1/models` lists agent targets, not provider models. Picker still needs its own model list (Ollama `/api/tags`, OpenRouter). Gateway's ollama provider uses `models.providers.ollama` + auth profile `ollama:manual` in OpenClaw's own config; the key in `~/.colony/.env` is **not** what OpenClaw uses. |
| Decider / Laya | No | Not in OpenClaw (its routing is channel bindings, not "which agent answers"). Keep. |

## DONE 2026-10-09: problems 1 and 2 below are fixed (verified live on workspace "my business")
- **One OpenClaw agent per Colony role**: id = `<workspace_id>-<role_id>` lowercased (`engine/openclaw.py::agent_id_for`), added on first use by
  `ensure_agent` (writes `agents.entries.<id>` = `{name, workspace}` into `~/.openclaw/openclaw.json`, hot reload, then waits until
  `/v1/models` lists `openclaw/<id>`). Requests use `model: "openclaw/<id>"`; the model is still chosen per turn with `x-openclaw-model`.
  **Gotcha found live:** a second agent makes OpenClaw reject the config ("multi-agent rosters require agents.ownership=explicit", reload
  skipped) until `agents.ownership: "explicit"` is set; `ensure_agent` sets it and keeps `main`. Agent workspace = `~/.colony/openclaw-agents/<id>`,
  deliberately **not** the user's project folder (OpenClaw writes bootstrap/memory files into an agent workspace).
- **No more double history**: OpenClaw keeps its own history per session (key = OpenAI `user` field; verified: same key remembers, other key does not).
  Colony now sends, after a session's first turn, only the messages that session has not seen (`unseen`/`mark_seen`; marker file
  `~/.colony/openclaw_seen.json` = last Colony message id each session answered). New session or marker gone (compaction) = recent history once.
  Verified: Buddy recalled a secret from its own session and a word that Coder (another agent) said in between.
- Tests: `conftest` points `OPENCLAW_CONFIG_PATH` at a temp file (tests never touch the real `~/.openclaw`); 4 new tests; suite 181 passed.
- Still open: Colony's own `memory_context` is not sent on the OpenClaw path (so Colony memory is currently unused there), and the persona
  system prompt is resent every turn.
- **FIXED 2026-10-10: the ~46k-token prompt.** Measured `usage.prompt_tokens` for "5+5" per agent config (all through `/v1/chat/completions`):
  | agent config | prompt tokens |
  |---|---|
  | `tools.profile=full` (what the gateway default gave us) | ~46-47k |
  | `coding` profile | 34.3k |
  | `minimal` | 7.4k |
  | `minimal` + web_search | 7.9k |
  | + read | 9.9k |
  | + write, edit | 10.4k |
  | + exec | 11.0k |
  | same + `skills: []` | 9.2k |
  | same + `contextInjection: "never"` | 6.7k |
  | same + both | **4.9k** (~89% less) |
  Removing only `BOOTSTRAP.md` from a workspace saves 1.8k. `ensure_agent` now writes every agent as `{profile: minimal, alsoAllow: [only what the
  Colony role has: web_search / read / write+edit / exec], skills: [], contextInjection: "never"}` and updates it (5 s wait for the hot reload) when
  the user changes the role's tools. Live: Buddy (web only) = 3.6k tokens and found a live Bitcoin price; Coder in a workspace WITH a project folder
  (all tools) = 5.0k tokens and read a file + ran `echo` correctly. Without a project folder Colony turns file/exec tools off (existing rule), so Coder
  correctly says it cannot run commands. Caveats: `contextInjection: "never"` also stops OpenClaw injecting MEMORY.md/USER.md, revisit when memory
  moves to OpenClaw (try `continuation-skip`); MCP/connector tools are not in the allowlist yet; a new agent's very first call can be slow (agent
  database preparation) and `/context detail` is not available over the HTTP API (the model just receives the text); deleting a Colony workspace
  does not remove its OpenClaw agents (config entries + `~/.colony/openclaw-agents/<id>` + `~/.openclaw/agents/<id>`); there is no cleanup yet.

## DONE 2026-10-10: MCP / connectors moved to OpenClaw (migration step 2)
- Storage: connectors now live in OpenClaw's config, `mcp.servers` in `~/.openclaw/openclaw.json` (Colony no longer has `~/.colony/mcp-servers.json`;
  none existed on this Mac, so nothing to migrate). `core/mcp.py` is only the editing layer (validation, masking, MASK-keeps-stored-value) over
  `engine/openclaw.read_config/write_config`; the Connectors window and `/api/mcp` are unchanged. `config_lock` (engine/openclaw.py) guards every
  read-modify-write of that file (agents, plugins, connectors). `write_config` now chmods it 0600 (it was 644; connector API keys live there).
- Mapping: command servers -> `{command,args,env}`; URL servers -> `{url,headers,transport}` with transport `streamable-http` (OpenClaw's own
  default for a bare URL is legacy SSE, so we set it; only a URL ending in `/sse` stays `sse`). Settings Colony cannot show (OAuth, toolFilter,
  timeouts, servers with neither command nor url) are preserved on every save.
- Access: `ensure_agent` adds `<server>__*` to the role's `alsoAllow` for each connector ticked for it (OpenClaw names tools `<server>__<tool>`).
  The system prompt lists the connectors, keeps the Composio "only these apps" restriction, and for mode "ask" tells the agent to say what it will do
  and wait for a yes.
- Verified live with `tests/fake_mcp.py`: `openclaw mcp doctor fake --probe` = ok; Coder (connector ticked) called `fake__echo` and returned the real
  output; Buddy (not ticked) correctly could not; prompt = 3.7k tokens with a connector.
- **(Regression below was fixed the same day by the gate plugin, see the approvals section.)** Colony's per-call approval for connectors ("ask") was NOT enforced. OpenClaw's MCP tool approvals only apply to
  the Codex runtime (`openclaw mcp configure <server> --approval ...`); the built-in runtime we use runs the tool. "ask" now only changes the prompt
  (a polite request to confirm in chat). Real enforcement needs the approvals work (WebSocket RPC) in migration step 5.
- Removed: `enabled_for_pi`, `core/mcp` file storage, `_no_folder_dir`. Tests: `test_mcp.py` rewritten around the OpenClaw config (183 passed).

## DONE 2026-10-10: approvals ("ask") enforced again through a Colony gate plugin in OpenClaw (migration step 5a)
Closes the regression above (connector "ask", and also write/edit/exec "ask", which stopped being enforced when Pi was removed).
- How: `colony/engine/colony-gate/` is an OpenClaw plugin (manifest `openclaw.plugin.json` + `package.json` + `index.ts`). It hooks `before_tool_call`
  and POSTs `{agent_id, tool, params}` to Colony `POST /api/approvals/gate`; Colony (`core/gate.py::decide`) applies the role's permissions, the
  workspace mode (`apply_mode`) and the project-folder fence; for "ask" it puts a card in front of the user (existing `core/approvals.py` + UI cards)
  and blocks until the answer; the plugin then returns `{block:true, blockReason}` or lets the call run. Colony unreachable = blocked (fail closed).
  `web_search` and the Gateway's own `main` agent are never gated (so OpenClaw keeps working for the user without Colony).
- `engine/openclaw._register_gate` (called from `ensure_agent`) adds the folder to `plugins.load.paths`, enables the plugin and raises its hook limit
  (`plugins.entries.colony-gate.hooks.timeouts.before_tool_call` = approval timeout + 10 s). `colony` passes `COLONY_URL` to the Gateway it starts.
- **Gotchas found live (a half-built version existed that looked enabled but never fired):**
  1. A bare `.ts` file in `plugins.load.paths` shows "enabled/loaded" in the CLI but the **Gateway never loads it** (not in the "N plugins" startup list);
     it must be a folder with `openclaw.plugin.json` having `activation.onStartup: true`. Check `[gateway] http server listening (N plugins: ...)` in the log.
  2. `openclaw plugins inspect <id>` (without `--runtime`) shows no hooks even when fine; it never proves the Gateway process loaded it.
  3. `before_tool_call` has a 15 s default limit and fails closed, so a human decision needs the raised limit (verified: answered after 22 s, ran).
  4. FastAPI route order: `POST /approvals/gate` must be declared before `POST /approvals/{approval_id}` or it gets a 422.
  5. A Gateway started by hand (not by `colony`) has no `COLONY_URL`; the plugin falls back to port 8765.
- Verified live: exec ask+approve (after 22 s) ran and returned the real output; exec ask+deny blocked; connector (`fake__echo`) ask+approve ran the real MCP
  tool; connector ask+deny blocked; the `main` agent ran `echo` with zero Colony calls. `tests/test_gate.py` (9 tests) covers decide(), the route order,
  the folder fence (incl. symlinks), modes, and `_register_gate`. Suite: all pass.
- Side effect to know: any non-`main` agent in this OpenClaw is gated by Colony (unknown to Colony = refused; Colony down = blocked).

## DONE 2026-10-10: compaction is OpenClaw's (migration step 3)
- **Verified live that OpenClaw's built-in auto-compaction works with our lean agents + Ollama cloud models.** Test: a probe agent, model context
  temporarily capped at 24,000 tokens (`models.providers.ollama.models[].contextTokens`, reverted), a secret planted in the first message, then ~11 long
  turns (~2.8k tokens each). The session's prompt dropped (14.3k -> 6.7k) and stayed under the ~18k prompt budget (the log line is
  `[context-pressure-diagnostic] ... route=compact_only`), and the secret was still recalled after compaction. Without a cap, `nemotron-3-super` on
  Ollama cloud has a large window: a session reached 39.5k tokens with no compaction at all, so it simply triggers much later (default mode `safeguard`,
  `agents.defaults.compaction.*`). Log noise "Session maintenance yielded to a foreground turn" is benign (optional post-turn work yields to the next message).
- Code: `core/chat.py` computes `via_openclaw` before building history. For an OpenClaw turn the history is **all non-evicted messages**, never
  `compaction.view` (a message Colony had summarised away would not be found by the `unseen` marker and the whole history would be resent), and
  Colony's `maybe_compact_in_background` is skipped. Colony's compaction still runs for the plain-chat path (OpenRouter/OpenAI, no tools), which is the
  only thing left that needs it. Test: `test_openclaw_is_given_the_whole_conversation_and_colony_does_not_compact_it`.
- Not done on purpose: `core/compaction.py` is NOT deleted (plain path still uses it, and its `flush_memory_before_compaction` belongs to the memory step).
  A brand-new OpenClaw session in a long conversation is seeded with only the recent `history_max_messages` (60) messages, not Colony's old summary
  (none exist on this Mac: no stored compaction). The per-agent "context gauge" in the UI (`core/context.report`) still estimates Colony-style
  windows and is not meaningful for OpenClaw sessions.

## DONE 2026-10-10: memory is OpenClaw's (migration step 4)
- **Finding that shaped it:** Colony's own memory held no real knowledge. The real workspace's `USER.md` was a log of "User asked: ... -> Buddy answered"
  lines (the LLM fact-extractor needs OpenRouter/OpenAI credit, which is dead), and on the OpenClaw path nothing was injected anyway, so it was write-only.
- Design (the lazy one): **the OpenClaw agents' workspace IS the Colony workspace's memory folder** `~/.colony/self_improve/<workspace_id>/`
  (`engine/openclaw.memory_dir`). Every role agent of that workspace shares it: `AGENTS.md` (our tiny rules, seeded so OpenClaw does not write its big template),
  `MEMORY.md`, `USER.md`, `memory/YYYY-MM-DD.md`. OpenClaw also creates `SOUL.md`/`IDENTITY.md` there (small). Colony's Memory window and
  `/api/memory/*` read the same files (`episodic.py` daily dir renamed `daily/` -> `memory/` to match OpenClaw).
- `contextInjection` is now `continuation-skip`: the folder's files are injected on a session's FIRST turn only (so a brand-new session of any agent knows the
  memory without costing tokens on later turns). Memory written mid-session by another agent reaches an already-open session only if it reads the file.
- Every agent now has `read/write/edit` in its allowlist (about +2.5k tokens, so ~5-6k per turn); `core/gate.py` lets ANY role read/write/edit files
  under its workspace's memory folder (absolute paths only) with no question, and still applies the normal permissions and project-folder fence to everything else.
- The system prompt tells the model the folder, to decide per message whether it holds a lasting fact, to edit USER.md/MEMORY.md as its first action, and never to
  claim it saved without the tool call. Capability lines were renamed "Project files, read/write/edit" (they said "Write / Edit Files: DISABLED", which made the
  model refuse the memory write), and the tool names fixed (read/write/edit/exec).
- **Measured model reliability (nemotron-3-super via Ollama cloud): it saved a "remember this" request only about half of the time and still answered "saved".**
  Prompt wording/ordering did not fix it (noisy 0-3 of 3). So `engine/openclaw.keep_if_asked` is a deterministic net: if the user's message has an explicit
  keyword (`จำไว้`, `จำด้วย`, `remember`) and MEMORY.md/USER.md did not change during the turn, Colony appends the user's own words to USER.md and sets the
  "Saved to memory" tag. Small talk is never saved by it. Facts the user does not flag are only saved if the model chooses to.
- Colony's own note-taking (daily observation, dreaming, LLM review, compaction) now runs only on the plain-chat path (`core/chat.py`), so no more junk lines.
- Verified live: 3 explicit requests saved (small talk not), then a DIFFERENT agent in a brand-new session answered name, coffee and project correctly cold, and
  `/api/memory/context` showed the same files. 12 gate/memory tests, suite passes.
- NOT verified: OpenClaw's own dreaming/consolidation (memory-core plugin) into `MEMORY.md` (nightly sweep), and `memory_search` (`memory.search.enabled` is false;
  `read` of the injected files is enough for now). The old junk `USER.md` of workspace `ws_76c8b897db` was renamed `USER.colony-log.md` (nothing deleted).
- Not deleted: `colony/memory/*` (plain-chat path and the viewer still use it). Delete it together with the plain-chat path.

## DONE 2026-10-10: attachments (migration step 6)
- Before: text files were pasted into the message (worked), but **images were silently dropped on the OpenClaw path** (the note said "[Attached image]" and nothing
  was sent); PDF/audio/video were dropped the same way unless an agent had tools.
- Now: `engine/openclaw.run_openclaw_turn(media=...)` puts images on the new user message as `image_url` data-URI parts (the Gateway takes up to 8 per request,
  20 MB total, png/jpeg/gif/webp; uploads are on unless `gateway.uploads.enabled` is false). Earlier messages' images are not re-sent (their note says so).
- `core/chat.py`: `goes_to_openclaw(role)` / `images_and_text_only(role)` decide, before routing, which agents can take which files, so a PDF/audio/video for an agent
  that runs through OpenClaw gets a clear notice up front ("agents that run through OpenClaw can only read images and text files") instead of vanishing.
- Verified live (temp workspace): a solid-red PNG to Coder (gemma4:31b) -> "สีแดง"; a blue PNG to Buddy (nemotron-3-super) -> "สีฟ้า" (so it reads images too);
  a text file -> content used correctly; a PDF -> the notice. 2 new tests; suite passes.
- NOT supported (and was not before either): PDF, audio, video through OpenClaw. Future path: the Gateway's `POST /v1/responses` takes `input_file` (PDF text via the
  `document-extract` plugin, already enabled) but is off by default (`gateway.http.endpoints.responses.enabled`) and is a different request shape; or OpenClaw's own `pdf`
  tool, which needs a vision/PDF model configured (`agents.defaults.pdfModel`/`imageModel`). Not worth building until someone needs PDFs.

## Problems found in the current bridge (original findings; 1 and 2 are now fixed, see above)
1. **Double history.** `buildAgentPrompt` (`src/gateway/openai-http.ts`) folds *all* request messages into one agent message, and the
   session (key from `user`) already stores earlier turns. Colony resends the full history every turn, so OpenClaw sees it twice and
   its compaction summarises duplicates. Fix idea: send system + only the new user message when the session already has history, and
   inject other agents' lines as a short "what others said since your last turn" block (needed for Colony's shared conversation).
2. **All roles share agent `main`** (see above) so per-role workspaces, memory files and tool policy are not separated.
3. `memory.search.enabled=false`, no `tools.exec.mode`, `gateway.auth.mode=none` (loopback only, fine for now).

## Suggested order (revised after this check)
1. Fix double history + route each Colony role to its own OpenClaw agent (create via `openclaw agents add` / RPC; model per agent).
2. MCP: write `mcp.servers` via Colony settings, delete `core/mcp.py` + `api/mcp.py`, then plan/connector prompt notes.
3. Compaction: turn off Colony's, rely on OpenClaw (after step 1, since it depends on session history being single-sourced).
4. Memory: pick one owner; enable `memory.search`, point the agent workspace at the Colony workspace folder, retire `colony/memory/`.
5. Approvals: add a small WS client (or choose `tools.exec.mode`), then retire `core/approvals.py`. Attachments last.
