# Project Brief — Colony Local
_Read order for a new AI: this file → `activeContext.md` → `systemPatterns.md` (+ `openclaw-capabilities.md` before touching `engine/openclaw.py`). `handoff.md` is the owner's hand-off note. Updated 2026-10-12._

## What it is
A small, self-contained **local multi-AI chat app** (repo `~/Desktop/Colony-Local`, branch `feature/openclaw-architecture`).
- **Workspaces** (project spaces): each has its own team of agents, ONE shared conversation, shared memory, and a project folder (a new workspace gets its own under `~/Documents/Colony Projects/<name>`, setting `PROJECTS_DIR`; `folder: ""` = chat only).
- **Agents** are user-defined: name, model (Ollama), *when to answer* rule, *how to answer* rule, tool permissions.
- **Rooms:** `# mix` (group chat; a *decider* picks who answers) and one direct room per agent. Rooms are display-only: every agent sees the whole conversation.
- **Backend = OpenClaw.** Colony is the workspaces + decider + team/skill/memory-folder service (and a fallback approval gate); every agent turn (model call, tools, sessions, permissions, approvals, compaction, memory) runs in the OpenClaw Gateway, which the Coucou app now talks to directly.
- Single user, everything on this Mac (`~/.colony/`). No Supabase/auth/billing. Not the hosted Colony product.

## The one problem it solves
"One conversation, many models, nobody needs to be told twice."

## Front-ends (all talk to the same HTTP API on :8765)
1. Web UI `colony/web/` (plain ES modules, served by FastAPI) — launched by the `colony` command.
2. Tauri window `desktop/` wrapping the same UI.
3. **Coucou desktop app `coco_local/`** (Swift, notch/menu bar) — untracked, own `.git`. Talks to the Gateway directly for chat (WebSocket) and to Colony for teams/settings/history.

## Scope (repo root)
`colony/` (Python package) · `tests/` · `desktop/` (Tauri) · `coco_local/` (Coucou fork) · `laya-runtime/` (local decider, optional) ·
`openclaw-main 2/` (OpenClaw v2026.9.8 source, gitignored, ~3.6 GB) · `memory-bank/` (these notes).

## Goals / non-goals
- Goal: the user (not the code) decides who answers what; agents can safely work on files (per-agent permissions, approval cards, folder fence);
  runs at zero cost (Ollama + OpenClaw local, Jev free tier). Long-term: core tool for solo-founder startups.
- Non-goals: marketing, accounts, multi-user, own agent engine (deleted: Pi, own loop, OpenRouter/Kaggle providers).
