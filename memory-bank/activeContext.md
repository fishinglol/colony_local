# Active Context — Colony Local
_Last updated: 2026-09-30 (model shootout on Kaggle done; new recommended team below)_

## Where things stand right now
**The owner has no money and the OpenRouter balance is negative** (2026-09-29), so nothing can use OpenRouter any more:
- **Chat models run on the owner's free Kaggle GPU** (2× T4 16 GB, ~30 GPU-hours/week). Agents pick model ids
  `kaggle/<ollama name>`; Colony sends them to `KAGGLE_BASE_URL` (Settings field). The notebook `kaggle/colony_server.py`
  (also `kaggle/colony_server.ipynb` for File → Import) installs Ollama, pulls **qwen3:8b, gemma3:12b, glm4:9b**, loads them
  into the GPUs and opens a cloudflared quick tunnel; ready in ~6.5-7 min. The URL changes on every run.
- **Laya decides who answers in `# mix`**, running on the owner's Mac (Intel i5 2017, 8 GB, no GPU): `colony` starts it
  itself from `laya-runtime/` (port 8790, ~770 MB RAM, 0.3-0.5 s per decision) and it dies with Colony. Replies show
  a `Laya NN%` tag. OpenRouter's Jev is still used only when Laya isn't installed and an OpenRouter key exists.
- **Verified 2026-09-29 end to end with no OpenRouter key** (a throwaway-HOME copy of Colony, not the owner's data): Laya
  routed Thai messages; Gemma/GLM replied in 2-5 s, Qwen3 ~16 s (it thinks first); a Pi tool turn with `kaggle/qwen3:8b`
  wrote a real file (`🛠 wrote hello.txt`).
- 189 pytest pass. **Nothing from 2026-09-29 is committed** (see Git state).

Everything built before (2026-09-24 → 09-26) still stands: workspaces, rooms, Pi tool agents with approvals, attachments,
modes, compaction, web search (OpenRouter-only), connectors/MCP/Composio, reasoning levels, Tauri window. See progress.md.

## Model shootout (2026-09-30) and the recommended team
The owner asked for models with different "personalities" that fit Kaggle. Candidates came from Ollama/Hugging Face
(the 7 models in gumloop.com's open-weight article are all 300B-1.6T, none fit; only the Qwen3.5 family has small
sizes). `kaggle/model_exam.py` runs one exam per model through a throwaway Colony (5 Thai/English prompts + a Pi file-write
tool test). Results, same conversation for all (so later models saw earlier answers; slow times include model swapping
because all 5 = ~33 GB don't fit in VRAM at once):
- **gemma4:12b** (Google, ~8 GB): best Thai (natural, polite, correct), code correct, tools OK, but slow (20-100 s) and
  verbose. → Buddy, Writer, Thinker.
- **ornith:9b** (Deep Reinforce, 5.6 GB, coding-tuned): code correct, tools OK, Thai OK but sprinkles Chinese words
  ("奖励", "预期"), imitates the "[Buddy]" label and says "คร้า". → Coder.
- **qwen3.5:9b** (Alibaba, 6.6 GB, vision): good Thai chat/writing, tools OK, 6-20 s when loaded, BUT answered the
  reasoning question in Chinese and its code returned `nums[1]` of the non-unique sorted list (wrong for [5,5,3]).
  → all-rounder / image input; not the first choice for Thinker.
- **lfm2.5:8b** (Liquid AI, 5.2 GB): fastest (1-3 s) but Thai is broken/hallucinated, leaks `<think>` text, no tool call.
  → not for Thai chat. Dropped.
- **scb10x/typhoon2.1-gemma3-12b** (Thai-specialised): UNTESTED — every request returned HTTP 500 from the server
  (probably GPU memory while swapping). Worth retesting alone.
- Not chosen: granite4.1 (no Thai), glm-4.7-flash (19 GB), mistral-nemo (old), SEA-LION (30B+), everything in the article.
`kaggle/colony_server.py` now pulls **gemma4:12b, ornith:9b, qwen3.5:9b** (~21 GB, all preloaded; ready in ~7 min).
Recommended team: Buddy/Writer/Thinker → `kaggle/gemma4:12b`, Coder → `kaggle/ornith:9b`, `kaggle/qwen3.5:9b` for images.
Kaggle weekly GPU quota showed only **15 h left** on 2026-09-30 (30 h/week, resets weekly); that exam run used 31 min.
Earlier (2026-09-29) team `qwen3:8b` / `gemma3:12b` / `glm4:9b` is obsolete (glm4:9b never calls tools).
Kaggle notebooks on the owner's account: `colony-server` (old models), `colony-models-eval` (current file, use this one).
The owner's real workspace ("testt", in `~/.colony`) was still on
OpenRouter free models when they last started Colony: they must paste the Kaggle URL in Settings and switch each agent.
The "Kaggle (your GPU)" group shows in the model picker only while a run is up and its URL is saved.

## How the owner runs it (taught to them in Thai, 2026-09-29)
1. kaggle.com → Your Work → `colony_server` (https://www.kaggle.com/code/faislol/colony-server) → Edit → check
   Settings → Accelerator = GPU T4 ×2 → Save Version → "Save & Run All (Commit)" → Advanced Settings →
   "Run with GPU for this session" → Save. It runs in the background: the tab may be closed.
2. Logs tab → after ~7 min a box with `https://….trycloudflare.com` → Colony → Settings → Kaggle server URL → Save.
3. `cd ~/Desktop/Colony-Local && .venv/bin/colony` (or the window: `cd desktop && npm run dev`). Ctrl+C stops it (and Laya).
4. When done: notebook → Logs → ⋮ → View versions → ⋯ on the running version → Cancel (else it burns GPU quota for up to
   12 h). Claude cancelled the first real run after ~2 h (7386 s) at the owner's request.
- The owner also ran the cell interactively in the editor once (output under the cell). That works while the tab stays
  open; stop it with ⋮ next to "Draft Session" → Stop session. Earlier interactive runs died (see Kaggle lessons).

## Kaggle lessons (learned the hard way on 2026-09-29)
- Interactive editor runs died repeatedly during the big downloads; Ollama's `install.sh` (progress bar) killed the
  session every time. So the script untars `ollama-linux-amd64.tar.zst` itself (installs `zstd` if missing) and does all
  slow work in a background shell script; the cell only prints progress every 15 s.
- **Save & Run All with GPU (a background "version") is the reliable way.**
- Importing a notebook makes Kaggle auto-start a run WITHOUT a GPU → cancel it (Version History → ⋯ → Cancel).
- Driving Kaggle's editor from Chrome is fragile: it is a cross-origin iframe (no JS access), typing long text times out,
  keys typed in command mode become Jupyter shortcuts (cmd+a + Delete once deleted every cell). Use File → Import.
- Test notebook `notebookb3ee55e564` is empty junk from that; the owner may delete it.
- Kaggle account: user `faislol`, phone-verified, internet on. Claude must not sign in or verify for the owner.

## Git state (IMPORTANT before committing)
- The repo is standalone now: `~/Desktop/Colony-Local`, branch `main`, **no remote**. `40fe948` "Continue Colony Local as
  its own project" moved it out of ColonyBridge (history = the old `local/` subtree split). Code lives at the repo ROOT;
  there is no `local/` folder any more (old notes that say `local/...` mean the repo root).
- Uncommitted: the memory bank moved `docs/memory-bank/` → `memory-bank/` and the two docs `docs/*.md` →
  `memory-bank/docs/` (git shows deletes + untracked); all 2026-09-29 code (Kaggle provider, Laya decider, `kaggle/`,
  `laya-runtime/`, tests). Commit only when the owner asks; push is impossible until a remote is added.

## Known rough edges / unverified
- Laya is weaker than Jev on hard calls: "เหนื่อยจัง วันนี้งานเยอะมาก" went to Coder (0.86); a strategy message went to
  Writer until "strategy" was added to Thinker's "when". Clear, specific "when" rules matter (owner was told).
- Qwen3 thinks before answering (slow) and the tiny "Test this model" budget returns an empty preview. A Qwen reply once
  began with a "[Strategy]" label. GLM4 answered a casual Thai message in poor Thai.
- Anyone with the tunnel URL can use the models while a run is up (no auth).
- Memory review and compaction use `OPENROUTER_ROUTING_MODEL` (OpenRouter) → they fail quietly now. They work on Kaggle
  with `OPENROUTER_ROUTING_MODEL=kaggle/gemma3:12b` in `~/.colony/.env` (not set; no UI).
- Web search is an OpenRouter plugin → unavailable for Kaggle models (the field is not sent).
- Pi starts fresh per turn; approvals are global (UI refuses to switch workspace mid-reply); earlier tool results aren't
  in later prompts (only the `🛠` line). A built `.app` contains no Python, Node/Pi or Laya. Tauri Cmd+Q untested.
- **Security housekeeping:** the owner pasted an OpenRouter key in chat twice. Never use it; remind them to rotate it.

## Recent decisions still in force
- Zero budget: no paid services. Chat models on Kaggle, decider (Laya) on the Mac. OpenJev rejected (needs a 24 GB
  NVIDIA GPU or Apple Silicon, no CPU mode); local Ollama rejected (the Mac is too weak).
- Pi = tool engine, one process per turn, Colony history = single truth, no Pi sessions. Tool agents need an OpenRouter
  key OR a `kaggle/` model with the URL set.
- Project folder explicit per workspace; without one agents are chat-only. Never `/` or home.
- Ask before adding dependencies (Laya + its pins were approved: "use it on our computer").
- No regex in our code (the Kaggle script finds the tunnel URL with string methods).
- Reply to the owner in Thai, in prose.

## Sensible next steps (none started; ask the owner)
0. **Daily-life use (agreed 2026-10-01):** workspace "Daily" over the owner's Obsidian vault (`~/Documents/GraniteVault-new/Fais OS`,
   notes in `my own schedule/`), morning briefing; then test it on the real files on the next Kaggle run (see progress.md).
1. Owner switches their real workspace to the Kaggle models and uses it; fix what breaks.
2. Commit everything (memory-bank move + 2026-09-29 work).
3. Point memory review/compaction at a Kaggle model (setting or UI).
4. Qwen3 thinking control (map the agent's reasoning level to Ollama's `reasoning_effort`).
5. Auth on the tunnel; show in Colony whether the Kaggle server is up.
6. Older ideas: git checkpoint per agent turn + diff in approvals; long-lived Pi process; shippable app bundle.
