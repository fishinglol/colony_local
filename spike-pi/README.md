# Spike: Pi as the tool-running engine behind Colony's agents

Throwaway experiment (not wired into `colony/`). Question: can [Pi](https://github.com/earendil-works/pi) run the
agents' file/bash tools while Colony keeps its own job (routing, shared context, memory)?

```bash
cd local/spike-pi && npm install
python spike.py              # 19 offline checks: Pi talks to fake_llm.py, no key, no network
python try_real_models.py    # your free OpenRouter models, with YOUR key in the environment
```

## How it is wired
Each agent turn starts a fresh `pi --mode rpc` process on the **same session id** (`--session-id <conversation>`) with that
agent's `--provider/--model`, `--system-prompt` (its persona), `--tools` (its allowlist) and `-e extensions/colony-gate.ts`.

`extensions/colony-gate.ts` (Colony's part inside Pi):
- per-tool policy `allow | ask | deny` from `COLONY_POLICY`; "ask" goes over RPC as an `extension_ui_request` that Colony's UI answers
- file tools can't touch paths outside the workspace folder
- stamps replies `[AgentName] ` so other agents can tell who said what (same idea as Colony's own labels)

## Proven offline (`python spike.py`)
Approve/deny before a write · allow/deny per agent · read-only agents aren't even offered write/bash · two agents on two
models with two personas share one conversation · agent's own system prompt replaces Pi's · `CLAUDE.md` in the folder is
loaded into every agent unless `--no-context-files` · agents can't read/write outside the workspace · speaker labels.

## Real free models (owner ran `try_real_models.py`, 2026-09-26)
- `nvidia/nemotron-3-ultra-550b-a55b:free` and `nvidia/nemotron-3-super-120b-a12b:free`: wrote and read files with Pi's tools. Pi's auto-retry rode out "Nvidia: Service temporarily overloaded" (each retry costs free quota).
- `z-ai/glm-5.2:free`: **404 "No endpoints found that support tool use"** — the free endpoint has no tool support (OpenRouter's public `/models` shows no `tools` in its `supported_parameters`; the paid `z-ai/glm-5.2` has it). Not a Pi problem, and Colony's Coder agent currently uses this model.
- `qwen/qwen3.8-27b:free`: 429 "temporarily rate-limited upstream" (shared pool) on every attempt; it does advertise tools, so this is capacity, not capability. Untested.
- Rule that follows: only offer tools to a model whose `supported_parameters` includes `tools` (read it from `GET https://openrouter.ai/api/v1/models`, no key needed).

## NOT proven
- `bash` can't be fenced by path: keep it `deny`/`ask`; Pi itself says to sandbox (container/VM) for real isolation
- ~2 s start-up per turn (measured with the fake model); a long-lived RPC process would be faster but needs per-turn persona switching
- Two stores of history (Colony's `history.json` vs Pi's session files) and the context gauge / trimming on top of Pi's compaction
- Shipping Node (>= 22.19) with the desktop app
