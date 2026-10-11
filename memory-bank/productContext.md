# Product Context — Colony Local
_What the user sees and which product decisions are settled (do not relitigate). Updated 2026-10-11._

## Decisions in force
- **Colony = UI on top of a 100% OpenClaw backend** (owner, 2026-10-09). No own agent engine, tool runner, MCP layer or memory.
- **User-defined agents**, not fixed roles; the decider routes by the user's own "when" text. Defaults: Thinker, Buddy, Writer, Coder.
- **Workspace = the context boundary:** one continuous conversation, team, memory and project folder per workspace. No "New chat": a fresh context = a new workspace.
- **Rooms are display-only;** shared context is the point. Messages carry a `channel` tag (`auto` = group, or an agent id).
- **Decider:** Jev via API (BeatAPI) → Laya local → Nemotron → first agent. The fallback is always visible, never silent.
- **Models:** the Ollama pool only (`core/models.py`; any `ollama/<id>` can be typed). OpenRouter and Kaggle are gone.
- **Agents without a project folder are chat-only.** Never `/` or home as folder.
- **No regex in our code** (plain string methods, also in JS/TS/Swift where we write new code). **Ask before adding dependencies.**
- **Reply to the owner in Thai, in prose.** UI copy is English; `core/errors.py` explanations are Thai.
- Zero budget: free tiers and local models first.

## What the user sees (web UI)
- Sidebar: workspace switcher (+ New workspace, workspace settings), `# mix`, Direct Agents, Memory viewer, Settings.
- Agent editor: Profile (name, model picker with "Test this model", when-to-answer) · Personality (SOUL.md text) · Tools (4 capability cards:
  Web search / Read / Write / Shell, role presets) · Memory (read-only files). Connectors window (MCP, Composio apps).
- Chat box: attachments (+ menu, drag/drop, paste), folder button, mode pill (Auto · Manual · Accept edits · Plan · Bypass), context gauge.
- Replies: speaker + model tag, decider confidence (`Jev 94%` / `Laya 92%`), "Saved to memory", and a collapsible **"Worked for 17s"** trace
  (commands with output, reads, writes, searches, connector calls); approval cards (Allow/Deny) when an agent with "ask" wants to write/run.
- Settings modal: OpenClaw plugins (18, 5 categories, hot reload), Ollama key + Gateway, Gateway status.

## What the user sees (Coucou app, `coco_local/`)
Island chat with room switcher (group + agents), workspace dropdown, per-agent model menu, file chip; Home = Team tab (agents) + Tools tab
(Active pills / Integrations); Settings → Colony (server URL, switch, agent editor with Memory tab). Mochi's pose follows `/api/activity`.
