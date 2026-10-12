"""Colony Local — what the team keeps in its shared memory files.

An agent fenced to a project folder cannot write the memory files, and models say "noted" without writing, so after each
turn Colony asks Jev (same API as the decider) what the user's message is. Nothing here matches words: Jev reads the meaning,
in any language. The user's own sentence is what gets written. Jev classifies, it does not write text.
"""
import logging

from ..config import Settings
from ..engine import openclaw
from ..store.history import get_all_messages
from .decider import ask_choice

logger = logging.getLogger(__name__)

KINDS = {
    "about_user": "The user states something lasting about themselves: their name, who they are, what they do, their preferences, "
                  "habits, people or pets in their life, or asks to be remembered.",
    "fact_or_decision": "A lasting fact, decision or rule about the user's project, work or world that will matter in later conversations.",
    "confirms_assistant": "The user confirms or accepts a fact the assistant just stated about them or their work "
                          "(yes, correct, that's right, remember it), so what the assistant said is the thing to keep.",
    "nothing": "Small talk, any question to the assistant (including asking whether it remembers something), a request for a task, "
               "or something that only matters right now.",
}
FILES = {"about_user": "USER.md", "fact_or_decision": "MEMORY.md", "confirms_assistant": "USER.md"}


def keep_if_worth(settings: Settings, workspace_id: str, user_text: str, before: str) -> bool:
    """Append the user's message to USER.md or MEMORY.md when Jev says it is worth keeping and the turn did not already change
    the files (the model wrote them itself). True when it wrote."""
    if not user_text.strip() or openclaw.snapshot_memory(settings, workspace_id) != before:
        return False
    said = next((m["content"] for m in reversed(get_all_messages(workspace_id)) if m.get("role") == "assistant" and m.get("content")), "")
    state = f"Assistant: {said[:500]}\nUser: {user_text[:1000]}" if said else user_text[:1000]
    asked = ask_choice(settings, state, "Is the user's last message worth keeping in long-term memory, and where?", KINDS, question="keep")
    if not asked or asked[0] not in FILES:
        return False
    # a bare "yes, remember it" says nothing on its own: keep what it confirmed, with the user's words
    text = f"{said.strip()[:300]} (user: {user_text.strip()[:100]})" if asked[0] == "confirms_assistant" else user_text.strip()[:400]
    line = f"- {text}\n"
    notes = openclaw.memory_dir(settings, workspace_id) / FILES[asked[0]]
    if line in notes.read_text(encoding="utf-8"):
        return False
    with notes.open("a", encoding="utf-8") as f:
        f.write(line)
    logger.info("memory: kept a message in %s (%s via %s)", notes.name, asked[0], asked[2])
    return True
