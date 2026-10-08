# Project Brief — Colony Local

## What this is
A small, self-contained **local multi-AI chat app** — its own git repo (`~/Desktop/Colony-Local`, branch `main`).
Organised in **workspaces** (project spaces, each with its own team, one shared conversation, memory and project
folder). One screen, several user-defined AI "agents" (each = a name, a model, a *when to answer* rule and a *how to
answer* rule), a decider that picks which agent answers in the group chat `# mix` (**Laya** on this computer, or Jev
on OpenRouter), and **one shared conversation + long-term memory that every agent sees**. Launched by a `colony`
command (browser) or a native window (`desktop/`, Tauri). Agents can also be given **tools** (read files, edit files,
run commands, connected apps) inside one project folder, with the user approving each write/command.

Models come from OpenRouter (any id) or, since 2026-09-29, from **the user's own Kaggle GPU** (`kaggle/<name>` ids
served by Ollama in a Kaggle notebook) — the owner has no budget, so Kaggle + Laya is the current way to run it.

It is **not** the hosted Colony product: no Supabase, no auth, no billing, no cloud backend of ours. Single user,
everything on the user's machine (`~/.colony/`). The code was lifted and simplified from ColonyBridge's
`backend/app/ai_ant/` and `general_chat/model_pool.py`, then moved out into this repo (commit `40fe948`); it shares
no runtime code with them.

## The one problem it solves
People who use several AI models keep re-explaining their context when they switch between them. Colony Local is one
place where every model already knows the whole conversation and what it has learned about you.
*"One conversation, many models, nobody needs to be told twice."*

## Goals
- One screen; add/edit/remove agents in the UI (models chosen from a picker or typed as any id) — the user, not the
  code, decides who answers what.
- Every agent sees the same history and memory ("shared context"), labelled by speaker, trimmed to its own window.
- The decider routes `# mix` messages; direct chats bypass it. When it is down the fallback is visible, never silent.
- Agents may work on the user's files safely: per-agent permissions, approval cards, a project-folder fence.
- Runs at zero cost when needed (Kaggle free GPU + Laya on the Mac).
- Long-term: the core tool for solo-founder startups (owner's words). Marketing is out of scope.

## Scope (repo root)
`colony/` (Python package: API, core logic, LLM/HTTP layer, memory, history store, Pi engine, static web UI), `tests/`,
`desktop/` (Tauri shell), `pi-runtime/` (Pi install), `laya-runtime/` (local decider), `kaggle/` (the notebook that
serves the models + `model_exam.py`, the per-model exam), `spike-pi/` (throwaway experiment, kept as evidence), `memory-bank/` (these notes + `docs/`).

## Source of truth history
- `memory-bank/docs/local-multi-ai-mvp-handoff.md` — the original running log of decisions and dated entries up to
  2026-09-26 (newest at the bottom). Newer history lives in `progress.md`.
- `memory-bank/docs/local-restructure-spec.md` — the spec for the package split (DONE).
- `spike-pi/README.md` — the experiment that justified using Pi.
- Git: this repo's `main` (see activeContext.md for what is and isn't committed).
