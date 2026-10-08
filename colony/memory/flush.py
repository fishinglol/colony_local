"""Colony Local — Pre-Compaction Memory Flush (OpenClaw Architecture).

Extracts and preserves durable facts from conversation turns before compaction
summarizes or truncates them, ensuring episodic notes capture vital context.
"""
from __future__ import annotations

import logging
from typing import Any

from ..config import Settings, get_settings
from ..llm.http import ProviderError
from ..llm.providers import complete_chat
from .episodic import append_daily_observation
from .recall import save_explicit_memory
from .safety import sanitize

logger = logging.getLogger(__name__)

_FLUSH_SYSTEM = (
    "You are a memory flush worker in an AI assistant system. Before an older conversation chunk is compacted, "
    "extract any critical facts, user preferences, technical decisions, or active file paths that must not be forgotten. "
    "Do NOT summarize chit-chat. Output ONLY 1 to 4 bullet points, each starting with '- '."
)


def _deterministic_extract(messages: list[dict[str, Any]]) -> list[str]:
    """Fallback rule-based extraction when LLM is unavailable (no regex)."""
    facts = []
    for m in messages:
        content = m.get("content", "")
        role = m.get("role", "")
        lines = content.splitlines()
        for line in lines:
            trimmed = line.strip()
            lower = trimmed.lower()
            if role == "user":
                if lower.startswith(("remember ", "i prefer ", "i want ", "don't ", "do not ")):
                    facts.append(f"User preference: {trimmed}")
                elif "my name is " in lower or "call me " in lower:
                    facts.append(f"User identity: {trimmed}")
            elif role == "assistant":
                if "wrote " in lower or "edited " in lower or "ran `" in lower:
                    facts.append(f"Tool action: {trimmed}")
    return facts[:4]


def flush_memory_before_compaction(
    workspace_id: str,
    messages: list[dict[str, Any]],
    settings: Settings | None = None,
) -> int:
    """Flush key facts from messages to episodic daily notes. Returns number of facts saved."""
    if not messages:
        return 0

    s = settings or get_settings()
    extracted_bullets: list[str] = []

    # Try LLM extraction if provider keys exist and not mock mode
    has_provider = bool(s.openrouter_api_key or s.openai_api_key or s.ollama_base_url)
    if has_provider and not s.mock_mode:
        convo_lines = []
        for m in messages[-20:]:  # Last 20 messages of the chunk
            r = m.get("role", "unknown")
            c = m.get("content", "")[:300]
            convo_lines.append(f"[{r}]: {c}")
        convo_text = "\n".join(convo_lines)
        try:
            raw = complete_chat(
                settings=s,
                system_prompt=_FLUSH_SYSTEM,
                user_prompt=f"<conversation>\n{convo_text}\n</conversation>",
                temperature=0.0,
                max_tokens=300,
            )
            for line in raw.splitlines():
                trimmed = line.strip()
                if trimmed.startswith("- "):
                    clean = sanitize(trimmed[2:].strip())
                    if clean and len(clean) > 5:
                        extracted_bullets.append(clean)
        except Exception as exc:
            logger.debug("LLM memory flush failed, using deterministic fallback: %s", exc)

    if not extracted_bullets:
        extracted_bullets = _deterministic_extract(messages)

    saved_count = 0
    for fact in extracted_bullets:
        clean_fact = sanitize(fact)
        if clean_fact:
            append_daily_observation(
                workspace_id,
                clean_fact,
                origin="pre-compaction-flush",
                tag="flush",
            )
            saved_count += 1

    logger.info("Pre-compaction memory flush saved %d facts for workspace %s", saved_count, workspace_id)
    return saved_count
