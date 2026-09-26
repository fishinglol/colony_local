# Spec — Restructure `local/` (Colony Local) without changing behavior

> **STATUS 2026-09-25: DONE (Steps 0–4), executed and verified by the director. 47 tests pass; UI walked through in a real browser with zero console errors. Kept for reference.**

**Director:** Claude (Opus). **Implementer:** any coding AI. Do the steps in order, one at a
time, and run the checks after each step. The director reviews the result before the next step.

**Priority:** the app must keep working at every step. This is a cleanup, not a rewrite.
No new features, no new dependencies, no behavior changes — except the one bug fix in Step 0.

## Rules (from the repo owner)
- **No regex anywhere in `local/`.** Use `in`, `startswith`, `split`, character loops. If you
  think you need one, stop and ask.
- **No new dependencies.** Standard library + what `pyproject.toml` already lists.
- **No drive-by edits.** A diff line must trace to a step below.
- Don't grow grab-bag files; a new domain gets its own file.
- Config only through `get_settings()`; never read `os.environ` in business logic.
- Answer the owner in Thai when reporting back.

## Where things are today
`local/` = `cli.py`, `server/*.py` (flat), `server/web/index.html` (one 847-line file:
213 CSS + 498 JS), `tests/` (16 tests, all passing). Run tests from `local/`:
`.venv/bin/python -m pytest -q tests -p no:warnings`

## Target layout
```
local/
  pyproject.toml              # script: colony = colony.cli:main ; package "colony" ; package-data web/**
  colony/
    cli.py                    # was local/cli.py
    app.py                    # was server/main.py (create_app + run)
    config.py                 # unchanged content
    schemas.py                # unchanged content
    api/                      # thin HTTP layer, no logic
      __init__.py             # builds one APIRouter from the modules below
      chat.py                 # /health, /messages, /conversations, /conversations/{id}
      agents.py               # /roles (GET, PUT), /models
      settings.py             # /settings (GET, POST)
      memory.py               # /memory/summary, /memory/context
    core/
      chat.py                 # was orchestrator.py
      decider.py
      agents.py               # was roles.py
      models.py               # was model_pool.py
    llm/
      http.py                 # NEW: the only place that calls urlopen for AI APIs
      providers.py            # was server/providers.py, minus dead code
    store/
      json_store.py
      history.py              # was server/memory.py (conversation history)
    memory/                   # was server/self_improve.py, split (Step 3)
      __init__.py             # re-exports the public functions (see Step 3)
      files.py  recall.py  review.py  safety.py
    web/
      index.html  app.css  js/…   (Step 4)
  tests/                      # imports updated; add the new tests named below
```
Public URLs (`/api/...`) and JSON shapes must not change. The UI keeps working untouched.

---

## Step 0 — Fix "remember this" being silently blocked (do first, small)

**Bug (verified 2026-09-25):** `self_improve._sanitize` runs `scan_for_threats(text, "strict")`,
whose `persistence_poison` patterns block "from now on", "always do/reply/…", "remember to",
"whenever … run". So the owner's core use case — "remember I want replies in Thai" — is
**refused**, `save_explicit_memory` returns `None`, yet the model's reply already said
"Got it, I'll remember". The user is told something false.
```
save_explicit_memory("local", "From now on reply to me in Thai.")  -> None
save_explicit_memory("local", "User prefers Thai; always reply in Thai.") -> None
```
Those patterns exist for a multi-tenant SaaS where strangers' text feeds the memory. This app is
one person's own machine and its whole purpose is remembering their preferences.

**Do:**
1. Write failing tests first (in `tests/test_memory.py`): the three strings above must save
   (returns a path/slug, not `None`), and the file must exist under
   `<DATA_DIR>/self_improve/local/knowledge/`.
2. Make them pass by changing `_sanitize` to scan with scope `"all"` instead of `"strict"`
   (one word). Keep blocking real injection phrases (e.g. "ignore previous instructions").
3. In `orchestrator.handle_message`: if a `MEMORY_SAVE` marker was present but nothing was
   saved (`fact` is truthy and `memory_saved` is False), append one line to the reply so the
   user isn't misled: `\n\n_(ไม่สามารถบันทึกความจำนี้ได้)_`. Test it by making
   `save_explicit_memory` return `None`.

**Check:** full test suite green.

---

## Step 1 — Rename the package and reorganize folders (move files, change imports only)

1. `git mv` per the layout above (`server/` → `colony/`, `cli.py` → `colony/cli.py`,
   `roles.py` → `core/agents.py`, `orchestrator.py` → `core/chat.py`, `model_pool.py` →
   `core/models.py`, `memory.py` → `store/history.py`, `main.py` → `app.py`,
   `router.py` split into the four `api/*.py` files, `threat_scanner.py` stays put for now
   → it moves in Step 3). Keep `web/` inside `colony/web/`.
2. Split `router.py` by URL group only. Do not change any handler body. `api/__init__.py`
   exposes `router` that includes the four sub-routers; `app.py` mounts it at `/api`.
3. Fix every import. Add an `__init__.py` to each new package.
4. `pyproject.toml`: `colony = "colony.cli:main"`, `packages` = all `colony*` packages,
   package-data must include `web/*` and (after Step 4) `web/js/*`. Remove the old `py-modules`.
5. Update `../.claude/launch.json` only if the command it runs changed (it runs `.venv/bin/colony`,
   so it shouldn't).
6. Update tests' imports (`server.` → `colony.…`). In `tests/test_app.py`, the patches on
   `orchestrator.self_improve` and `orchestrator.generate_openrouter_reply` change to the new
   module names — same behavior, new names.
7. Reinstall: `.venv/bin/pip install -q -e ".[dev]"`.

**Check:**
- `pytest` all green (same count as before Step 1, plus Step 0's).
- Smoke run (mock mode, throwaway HOME so `~/.colony` is untouched):
  ```
  HOME=$(mktemp -d) MOCK_MODE=true .venv/bin/colony --no-open --port 8799 &
  curl -s localhost:8799/api/health                       # status ok, roles list
  curl -s localhost:8799/ | head -c 200                   # the HTML page
  curl -s -XPOST localhost:8799/api/messages -H 'content-type: application/json' \
       -d '{"message":"hi","role_id":"chitchat"}'         # "[mock] Buddy …"
  kill %1
  ```
- `grep -rn "from server\|import server" local/ --include=*.py` returns nothing.

---

## Step 2 — One HTTP client (`llm/http.py`), delete dead code

Today `providers.py`, `decider.py` and `self_improve.py` each build their own SSL context
and call `urlopen`. `providers.py` also contains two things nothing uses.

1. Create `colony/llm/http.py` with the single SSL context (certifi if importable) and:
   `post_json(url, payload, headers, timeout, provider_name, retries=1) -> dict`
   — **move, don't rewrite,** the existing logic from `providers._execute_request_with_retry`
   (transient HTTP codes 429/500/502/503/504, provider `error` objects, 1.5 s backoff,
   `ProviderError` messages). `retries=0` means no retry.
2. `providers.py` builds its payloads and calls `post_json`. Keep `generate_openrouter_reply`,
   `generate_openai_reply` (OpenAI stays as the fallback per repo rules), the
   `temperature`/`reasoning` rules, the role and memory system messages, and the
   `MEMORY_SAVE` marker text — unchanged.
3. **Delete dead code:** `_prepare_attachment_blocks`, the `attachments` parameters, and the
   `Attachment` schema (the request schema no longer accepts attachments; nothing passes them).
   Keep `complete_chat` — Step 3 uses it.
4. `decider.py` calls `post_json(..., retries=0)` (latency matters: Jev is on the hot path).
   It must still fail open: any error → `source="fallback"`, first agent answers.
5. Tests: the three tests in `test_decider.py` and `test_temperature…` in `test_app.py` patch
   `urllib`/`_safe_execute_and_extract` today. Change them to patch the one place
   (`colony.llm.http` — its `urlopen`, or `post_json`). Add tests in `tests/test_http.py`:
   retries once on HTTP 503 then succeeds; does not retry on 400; raises `ProviderError` with
   the provider's message when the body is `{"error": {"message": "…"}}`; `retries=0` makes a
   single call.

**Check:** `grep -rn "urlopen" colony/` shows only `llm/http.py`. `grep -rn "_SSL_CONTEXT"` ditto.
Tests green. Smoke run as in Step 1.

---

## Step 3 — Split `self_improve.py` into `colony/memory/`, and rewrite the scanner without regex

Move code, don't change logic. Boundaries (function names, in current file order):

| New file | Contents |
|---|---|
| `memory/files.py` | constants (`USER_MAX_CHARS` … `_RELEVANT_FILE_TOP_K`), `_LOCK`, paths (`_root_dir` … `_items_dir`), `_read_text`, `_write_text_atomic`, frontmatter + `_slugify`, state (`_default_state` … `_write_state`), skill/knowledge files (`_cap_for` … `_patch_item_file`) |
| `memory/recall.py` | relevance ranking (`_token_set`, `_jaccard`, `_select_relevant_files`), `learned_context`, `pop_unseen_summary`, `save_explicit_memory` |
| `memory/review.py` | `note_turn`, `maybe_review_in_background`, the review (`run_review`, `_apply_review`, `_parse_review_json`, `_transcript`, `_item_context_lines`, `_rewrite_to_fit`, `_enforce_cap`, …) |
| `memory/safety.py` | `_sanitize` + the new scanner (below) |
| `memory/__init__.py` | re-export **exactly**: `learned_context`, `pop_unseen_summary`, `save_explicit_memory`, `maybe_review_in_background` |

- `review._call_review_llm` (a fourth copy of the HTTP call) becomes
  `providers.complete_chat(system_prompt=…, user_prompt=…, temperature=0.0, max_tokens=900)`.
  **Check how the caller handles failures** (`maybe_review_in_background` must still swallow
  every error so a failed review never breaks a chat turn) and keep that behavior; add a test
  where `complete_chat` raises and the chat request still succeeds.
- `core/chat.py` and `api/memory.py` import from the `colony.memory` package;
  the tests' patch target becomes `colony.core.chat.memory.maybe_review_in_background`
  (or however the import is spelled — keep patches pointing at the name `chat.py` looks up).

### The scanner (`memory/safety.py`) — replaces `threat_scanner.py`, no regex
Delete `threat_scanner.py`. `safety.py` exposes `find_threats(text) -> list[str]` and
`_sanitize` uses it. Owner decision: plain text matching. Lower-case the text once, then use
`in` / line `startswith`. Scope: **only what can matter in a single-user app with no tools** —
prompt-injection phrases. Drop the SaaS-era `persistence_poison`, `exfiltration_*`,
`tool_hijack`, `base64_exfil` labels (they blocked legitimate memories; see Step 0).
Labels and phrases:
- `instruction_override`: "ignore previous instruction", "ignore all previous instruction",
  "ignore the previous instruction", "disregard the system", "disregard the above",
  "disregard prior", "disregard system"
- `role_hijack`: "you are now "
- `new_instructions`: "new instruction:" , "new instructions:"
- `role_marker`: any line that, stripped, starts with "system:" or "assistant:"
- `fake_tool_fence`: "<tool_result", "</tool_result", "<function_result", "</function_result",
  "<tool_call", "</tool_call"

Tests (`tests/test_memory.py`): each label fires on one example and **doesn't** fire on
"My dog is named Kaprao." / "From now on reply to me in Thai." / "Please remember to call Mom
whenever I mention the dentist." (all three must be saveable).

**Check:** no `re` import anywhere in `colony/` (`grep -rn "^import re\|re\.compile" colony/`
is empty). `self_improve.py` and `threat_scanner.py` are gone. Tests green. Smoke run.

---

## Step 4 — Split the UI into files (no build step, no framework)

`colony/web/index.html` today = `<style>` (213 lines) + markup + `<script>` (498 lines).

1. Move the CSS verbatim to `web/app.css`; `index.html` links `/static/app.css`
   (the server already serves `web/` at `/static`).
2. Move the JS into ES modules under `web/js/` and load with
   `<script type="module" src="/static/js/main.js">`. Suggested modules (each one concern):
   `api.js` (`api`, error handling), `markdown.js` (`esc`, `renderMarkdown` and helpers — pure,
   no DOM), `state.js` (roles, target, conversationId, busy, model pool), `sidebar.js`
   (agents + threads lists, header), `feed.js` (messages, typing, ask-another menu, `ask`/`send`),
   `agent-editor.js` (modal, presets, model dropdown), `settings.js` (settings + memory modals),
   `main.js` (wiring + init). No inline `onclick=` exists today; keep it that way.
3. Cross-module calls go through explicit `import`/`export` — no `window.` globals.
4. Don't change any markup, class name, text, or behavior. `pyproject.toml` package-data
   must include `web/js/*`.

**Check (real browser, not just curl):** start the mock server (see Step 1 smoke, or use
the `colony-local-mock` entry in `../.claude/launch.json`), open it and confirm, with the
console open and **zero errors**: page loads with 3 agents; send in `# auto` → reply with a
"Jev unavailable" tag; click an agent and send; add an agent from a preset → it persists after
reload; edit an agent and choose "Other…" in the model list; delete an agent; "Ask another
agent" re-asks; Settings and Memory modals open; narrow the window to ~375 px and the sidebar
toggles from the ☰ button. Add `tests/test_web.py` that checks `GET /` returns HTML
referencing `/static/app.css` and `/static/js/main.js`, and that each of those URLs returns 200.

---

## Definition of done (director checks these)
- All tests green; test count went up (Steps 0, 2, 3, 4 add tests).
- `colony` boots from a fresh venv install (`pip install -e .`) and the smoke run passes.
- No `server` package, no `re`, one `urlopen` site, `git status` shows only intended files.
- `local/` still untracked/uncommitted — do **not** commit; the owner decides when.
- One paragraph per step in your report: what moved, what you verified and how, anything you
  chose differently from this spec and why.

## Not verified by anyone yet (don't claim it is)
A real call to Jev / OpenRouter with the owner's key. The owner will test it themselves;
everything above is provable in mock mode.
