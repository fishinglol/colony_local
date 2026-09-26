# Product Context — Colony Local

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
- **Sidebar:** `# mix` channel (the group chat; Jev picks who answers), **Direct Agents** (one row per
  agent; the header of a direct chat lists what that agent may do), Memory (this workspace's), Settings (API key).
- **Rooms:** the mix chat (`auto` internally) and each agent's direct chat are separate
  *displays* inside a workspace. Switching rooms changes only what is shown; **every agent still
  receives the whole conversation**. Messages carry a `channel` tag.
- **Agent editor:** name, **model picker** (a "Select model" window styled after opencode's: search box,
  a Suggested group then every OpenRouter model grouped by maker, hover/arrow keys show a card of what the
  model can do — reads text/images/video/files/audio, can use tools, reasoning, context limit; typing an id
  like `provider/name` offers it as a custom model; "Test this model" pings it), *When should this agent
  answer?*, *How should it answer?*, and **Tools** (a list of what is connected, each row with its logo and scope, plus ＋ Connect a tool which opens the
  same window as the sidebar Connectors button; locked to web search only when the model can't use tools). Selects are custom-styled (no native
  glossy look) with a small badge for the model's maker.
- **Reasoning level per agent** (only for models that can reason): a violet **pill on the agent's sidebar row**
  (`Reasoning Medium ▾`) opens a small menu to change it without opening the editor; the editor has the same
  choice as level buttons under the model. Choices come from OpenRouter's per-model metadata: Default (shows the
  model's own level), Off (only if the model can be switched off), then exactly the levels it supports.
- **Chat box:** `+` menu (Add files or photos ⌘U / Add folder), drag files anywhere, paste images; chips above the text. Bottom row: **folder button** (native folder window in the
  desktop app; without a folder agents are chat-only), **mode pill** (Auto · Manual · Accept edits · Plan · Bypass), send. Jev only picks agents whose model can read the attachment; a Colony notice
  (English) says what to change when nobody can.
- **Tools per agent = the "Connect a tool" window** (sidebar **Connectors** button, or the Tools list in the agent editor): search, category pills, ~105 tools (project files, edit files,
  commands, web search, **97 apps through Composio** with real logos, your own MCP servers, "Add a connector"), right panel *This agent can / Needs approval before / Access scope*
  (Ask each time | Allow freely). Users bring their own Composio consumer key (ck_…); nothing is shared.
- **Web search** per agent (OpenRouter, ~$0.007 per message; Sources listed under the reply). **Long conversations** are summarised in the background (a "summarised for the AIs · View summary" note).
- **Context chip** (top right): estimated % of each agent's context window used
  by this chat.
- **Approval cards:** when a tools-enabled agent wants to write a file or run a
  command, an Allow/Deny card appears under its typing indicator.
- **Memory viewer:** what every agent knows about the user. Saying "remember …"
  saves immediately; otherwise a background review runs every 5 turns.
- Replies show speaker name, model tag, Jev confidence (or a "Jev unavailable —
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

## Users
Single local user (owner first; later solo founders). No accounts. The API key
is the user's own OpenRouter key, entered in Settings and stored in
`~/.colony/.env`. **Never use a key pasted in chat** — tell the user to rotate
it (it has happened twice).
