# Colony — Claude Code Guidelines

Behavioral guidelines for working on this codebase.
Karpathy principles (§1–4) apply to all tasks.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

---

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.
- If a good open-source library or tool would do the job better than hand-rolled code
  (e.g. an agent framework, a parser, a validation lib), **stop and ask me to approve it
  before adding the dependency.** Name the library, what it replaces, and the trade-off.
  Do not silently add new dependencies.

---

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.


## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```



## 5. Consult the Memory Bank Before Starting Work

**ก่อนทำงานส่วนไหน ไปเช็ค Memory Bank ของส่วนนั้นก่อนเสมอ**

`memory-bank/` is flat and compact (~26 KB total). Read in this order before touching code:
`projectbrief.md` → `activeContext.md` → `systemPatterns.md` (+ `openclaw-capabilities.md` before
touching `engine/openclaw.py`). `progress.md` is history only.

When you change something, update the matching file in place: replace stale text, don't append
dated sections, keep each file short.


Do not begin work without checking the memory bank.