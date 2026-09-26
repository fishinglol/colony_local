# Project Brief — Colony Local

## What this is
A small, self-contained **local multi-AI chat app**, in `local/` at the repo
root. Organised in **workspaces** (project spaces, each with its own team, one shared conversation,
memory and project folder). One screen, several user-defined AI "agents" (each = a name, an
OpenRouter model, a *when to answer* rule and a *how to answer* rule), a
decider ("Jev") that picks which agent answers in the group chat, and **one
shared conversation + long-term memory that every agent sees**. Launched by a
`colony` command (browser) or a native window (`local/desktop`, Tauri). Agents
can also be given **tools** (read files, edit files, run commands) inside one
workspace folder, with the user approving each write/command.

It is **not** part of the hosted Colony product (`backend/`, `frontend/`): no
Supabase, no auth, no billing, no cloud. Single user, everything on the user's
machine (`~/.colony/`). The code was lifted and simplified from
`backend/app/ai_ant/` (orchestrator/providers) and `general_chat/model_pool.py`,
but it shares no runtime code with them.

## The one problem it solves
People who use several AI models keep re-explaining their context when they
switch between them. Colony Local is one place where every model already knows
the whole conversation and what it has learned about you.

## Goals
- One screen; add/edit/remove agents in the UI (models chosen from a dropdown or
  typed as any OpenRouter id) — the user, not the code, decides who answers what.
- Every agent sees the same history and memory ("shared context"), labelled by
  speaker, and is trimmed to fit its own context window.
- Jev routes `# mix` (group chat) messages; direct chats bypass it. When Jev is down the
  fallback is visible, never silent.
- Agents may work on the user's files safely: per-agent permissions, approval
  cards, a workspace fence.
- Long-term: the core tool for solo-founder startups (owner's words). Marketing
  is explicitly out of scope.

## Scope
- Covers: everything under `local/` — `colony/` (Python package: API, core
  logic, LLM/HTTP layer, memory, history store, Pi engine, static web UI),
  `tests/`, `desktop/` (Tauri shell), `pi-runtime/` (Pi install), `spike-pi/`
  (throwaway experiment, kept as evidence), plus its docs in
  `docs/exec-plans/active/local-*.md`.
- Does NOT cover: `backend/`, `frontend/`, the other memory-bank areas. Nothing
  in `local/` imports from them.

## Source of truth history
- `docs/exec-plans/active/local-multi-ai-mvp-handoff.md` — the running log of
  decisions and dated progress entries (long; newest entries at the bottom).
- `docs/exec-plans/active/local-restructure-spec.md` — the spec for the package
  split (DONE).
- `local/spike-pi/README.md` — the experiment that justified using Pi.
- Branch on origin: `feat/colony-local` (see activeContext.md for what is and
  isn't committed).
