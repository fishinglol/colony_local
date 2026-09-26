"""Guard for what gets written into memory: block obvious prompt-injection phrases.

Plain text matching, no regex (repo rule). Scope is deliberately small: this is a
single-user app on the owner's own machine with no tools to hijack, and its whole
purpose is remembering preferences ("from now on reply in Thai", "always ..."),
so those must NOT be blocked. Only phrases that try to rewrite the assistant's
instructions are.
"""
from typing import Any

_PHRASES = {
    "instruction_override": (
        "ignore previous instruction", "ignore all previous instruction",
        "ignore the previous instruction", "ignore prior instruction",
        "disregard the system", "disregard system", "disregard the above", "disregard above",
        "disregard the prior", "disregard prior",
    ),
    "new_instructions": ("new instruction:", "new instructions:"),
    "fake_tool_fence": (
        "<tool_result", "</tool_result", "<function_result", "</function_result",
        "<tool_call", "</tool_call",
    ),
}
_ROLE_MARKERS = ("system:", "assistant:")


def find_threats(text: str) -> list[str]:
    """Return the labels of injection phrases found in `text` (empty list = clean)."""
    lowered = text.lower()
    squeezed = " ".join(lowered.split())  # collapse any whitespace run to one space
    found = [label for label, phrases in _PHRASES.items() if any(p in squeezed for p in phrases)]
    if f" {squeezed} ".find(" you are now ") != -1:
        found.append("role_hijack")
    if any(line.strip().startswith(_ROLE_MARKERS) for line in lowered.splitlines()):
        found.append("role_marker")
    return found


def sanitize(text: Any) -> str | None:
    """The text if it's safe to store, else None."""
    clean = text.strip() if isinstance(text, str) else ""
    if not clean:
        return None
    threats = find_threats(clean)
    if threats:
        print(f"[memory] Blocked write ({threats}): {clean[:80]!r}")
        return None
    return clean
