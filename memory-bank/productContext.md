# Product Context — Colony Local
> **2026-10-09 product decision (owner, do not relitigate):** the product is "Colony's UI on top of a 100% OpenClaw backend".
> Colony no longer builds its own agent engine, tool runner, connector layer or memory; it adds the multi-agent, workspace
> and room experience on top of OpenClaw. Open: whether Laya's `# mix` routing stays (OpenClaw may not duplicate it).

## Why this exists
The owner uses several AI models (a reasoning one, a chatty one, a writing one,
a coding one) and was tired of re-briefing each when switching. The MVP proves
one idea: *one conversation, many models, nobody needs to be told twice.*

## What the user sees
- **Workspace switcher** (top of the sidebar): each workspace is a project space with its own team
  of agents (each agent can use a different model), ONE conversation every agent shares, its own memory
  and its own project folder. Menu: switch, ＋ New workspace (start from the default team or a copy of
  another workspace's agents), ⚙ Workspace settings (rename, project folder, delete). There is no
  "New chat": a fresh context = a new workspace.
- **Sidebar:** `# mix` channel (the group chat; the decider — Laya on this computer, or Jev — picks who answers), **Direct Agents** (one row per
  agent; the header of a direct chat lists what that agent may do), Memory (this workspace's), Settings (API key).
- **Rooms:** the mix chat (`auto` internally) and each agent's direct chat are separate
  *displays* inside a workspace. Switching rooms changes only what is shown; **every agent still
  receives the whole conversation**. Messages carry a `channel` tag.
- **Agent editor:** name, **model picker** (a "Select model" window styled after opencode's: search box,
  a Suggested group then every OpenRouter/Ollama model grouped by maker, hover/arrow keys show a card of what the
  model can do — reads text/images/video/files/audio, can use tools, reasoning, context limit; typing an id
  like `provider/name` offers it as a custom model; "Test this model" pings it), *When should this agent
  answer?*, *How should it answer?*, and **Agent Capability Cards** (4 intuitive cards: 🌐 Web Search, 📖 Read Files,
  ✏️ Write Files, ⚡ Shell Execution) with one-click role presets (Thinker, Buddy, Writer, Coder). Also supports the
  legacy Connect-a-tool picker for external connectors.
- **Reasoning level per agent** (only for models that can reason): a violet **pill on the agent's sidebar row**
  (`Reasoning Medium ▾`) opens a small menu to change it without opening the editor; the editor has the same
  choice as level buttons under the model. Choices come from OpenRouter's per-model metadata: Default (shows the
  model's own level), Off (only if the model can be switched off), then exactly the levels it supports.
- **Chat box:** `+` menu (Add files or photos ⌘U / Add folder), drag files anywhere, paste images; chips above the text. Bottom row: **folder button** (native folder window in the
  desktop app; without a folder agents are chat-only), **mode pill** (Auto · Manual · Accept edits · Plan · Bypass), send. Jev only picks agents whose model can read the attachment; a Colony notice
  (English) says what to change when nobody can.
- **Tools per agent:** Managed via OpenClaw Gateway capabilities or the legacy "Connect a tool" window (sidebar **Connectors** button): search, category pills, ~105 tools (project files, edit files,
  commands, web search, **97 apps through Composio** with real logos, your own MCP servers, "Add a connector"), right panel *This agent can / Needs approval before / Access scope*
  (Ask each time | Allow freely). Users bring their own Composio consumer key (ck_…); nothing is shared.
- **Web search** per agent: Handled through OpenClaw Gateway (`web_search` via DuckDuckGo, keyless, grounded) or OpenRouter plugin. **Long conversations** are summarised in the background (a "summarised for the AIs · View summary" note).
- **Context chip** (top right): estimated % of each agent's context window used
  by this chat.
- **Approval cards:** when a tools-enabled agent wants to write a file or run a
  command, an Allow/Deny card appears under its typing indicator.
- **Memory viewer:** what every agent knows about the user. Saying "remember …"
  saves immediately; otherwise a background review runs every 5 turns.
- **Settings:** Tabbed Settings modal with 3 sections:
  1. `🔌 OpenClaw Plugins`: Categorized manager for 18 OpenClaw plugins across 5 categories, with recommendation badges, descriptions, hot-reload toggles, and one-click recommended preset.
  2. `🤖 AI Providers & Keys`: API keys (OpenRouter), Kaggle GPU Server URL.
  3. `🖥️ Gateway Status`: Real-time status indicator for OpenClaw Gateway (port 18789).
- Replies show speaker name, model tag, decider confidence (`Laya 92%` or `Jev 67%`; or a "Jev/Laya unavailable —
  default agent" warning), a "Saved to memory" tag, and a `🛠 wrote x · ran y`
  line when tools were used. "Ask another agent ▾" re-asks the same question.
- UI copy is English; **error explanations are Thai** (`core/errors.py`), and the
  owner communicates in Thai.

## Product decisions already made (do not relitigate)
- **User-defined agents**, not fixed roles; the decider criteria are the user's
  own "when" text. Defaults: Thinker (reasoning), Buddy (chitchat), Writer,
  Coder — all on **free OpenRouter models** while testing.
- **No prices in the model dropdown** ("users already know").
- **Manus dropped.** Kimi added. Model list = latest OpenRouter ids (see
  `core/models.py`), and any id can be typed.
- **Reasoning:** default = send nothing (the model's own setting; the old built-in `medium` for some models is gone);
  a level the model doesn't support is left out, not sent; models that can't reason show no control.
- **Rooms are display-only**; shared context is the product's point.
- **Workspace = the context boundary** (2026-09-26, owner's 5 decisions): one continuous conversation per
  workspace (no threads inside); agents belong to the workspace (copied on create, then independent);
  memory per workspace; project folder per workspace; old data migrated into a "Personal" workspace.
- **Colony's own `history.json` is the single source of truth** for the
  conversation, even for tool turns (Pi runs `--no-session`, see systemPatterns).
- **Pi (earendil-works/pi) is the tool engine** — chosen over writing a harness
  from scratch and over wrapping opencode (its prompt would flatten agents'
  personalities). Agent personality comes from the user's "how to answer" text +
  permissions, not from the harness prompt.
- **Tauri** for the native window (over pywebview/Electron).
- **The owner wants me (Claude) to implement directly**, not delegate to opencode,
  and to stop talking about "handoff".
- **No regex in code** (owner rule): plain string methods only, including in JS,
  TypeScript and Python; there is a test guarding the markdown renderer.
- **Ask before adding dependencies** (repo `CLAUDE.md`). Approved so far: Tauri
  (+ npm `@tauri-apps/cli`), Pi (`@earendil-works/pi-coding-agent`).
- Marketing / landing is out of scope.
- **Zero budget (2026-09-29):** the owner has no money and OpenRouter is negative. Chat models run on the owner's
  free **Kaggle** GPU (Ollama: qwen3:8b, gemma3:12b, glm4:9b; the user starts a notebook run and pastes its URL);
  **Laya** (open weights, CPU) replaces Jev on the owner's Mac. OpenJev and local chat models were rejected (hardware).
  The architecture the owner has in mind: Colony → decider → Research / Code / Write "harnesses" (search/RAG,
  Pi/tools, files) → different open-weight models. Rooms, Jev-style routing and shared context stay as they are.

## Users
Single local user (owner first; later solo founders). No accounts. The API key
is the user's own OpenRouter key, entered in Settings and stored in
`~/.colony/.env`. **Never use a key pasted in chat** — tell the user to rotate
it (it has happened twice).
