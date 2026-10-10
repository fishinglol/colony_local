"""Colony Local — decider.

Picks which of the USER-DEFINED roles should answer a message. Each role's `when` text is one choice criterion, so the
user fully controls the rules. A local Laya server (LAYA_URL, POST /v1/systemone) answers if it is set; otherwise
nemotron-3-nano on Ollama does; if neither answers, the first role does.
"""
import json
import logging
from dataclasses import dataclass

from ..config import Settings
from ..llm.http import ProviderError, post_json
from .agents import Role

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeciderResult:
    role: Role
    confidence: float   # the decider's confidence for the chosen role (0–1)
    source: str         # "laya" | "nemotron" | "direct" | "only_role" | "fallback"


def decide(message: str, roles: list[Role], settings: Settings, direct_role: Role | None = None) -> DeciderResult:
    """Pick which role answers.

    direct_role set (user messaged a role directly) → no decision.
    One role only → no decision to make.
    Any decider failure → first role, source="fallback" (shown in the UI).
    """
    if direct_role:
        return DeciderResult(role=direct_role, confidence=1.0, source="direct")
    if len(roles) == 1:
        return DeciderResult(role=roles[0], confidence=1.0, source="only_role")
    if settings.laya_url:
        # Laya speaks Jev's protocol; "multilingual" is its checkpoint that reads Thai.
        url, headers, model, source = (f"{settings.laya_url}/v1/systemone", {"Content-Type": "application/json"},
                                       "multilingual", "laya")
    else:
        ollama_res = decide_via_ollama(message, roles, settings)
        if ollama_res:
            role_id, conf = ollama_res
            role = next(r for r in roles if r.id == role_id)
            return DeciderResult(role=role, confidence=conf, source="nemotron")
        return DeciderResult(role=roles[0], confidence=0.0, source="fallback")

    payload = {
        "model": model,
        "state": {"message": message[:2000]},
        "questions": {
            "role": {
                "type": "choice",
                "instructions": "Which teammate should answer this message?",
                "criteria": {r.id: r.when for r in roles},
            }
        },
    }
    try:
        # retries=0: the decider sits on the hot path of every message, so fail fast and fall back.
        data = post_json(url, payload, headers, timeout=10.0, provider_name=source.capitalize(), retries=0)
        role_id, confidence = parse_jev_answer(data, [r.id for r in roles])
    except (ProviderError, KeyError, ValueError, TypeError) as exc:
        logger.warning("%s decider failed (%s) — falling back to first agent", source, exc)
        return DeciderResult(role=roles[0], confidence=0.0, source="fallback")

    role = next(r for r in roles if r.id == role_id)
    return DeciderResult(role=role, confidence=confidence, source=source)


def parse_jev_answer(data: dict, role_ids: list[str]) -> tuple[str, float]:
    """Return (role_id, confidence) from a Decisions API response."""
    answer = (data.get("answers") or {}).get("role") or {}
    choice = answer.get("choice")
    if choice not in role_ids:
        raise ValueError(f"Jev returned no valid role: {data}")
    confidence = answer.get("confidence")
    if not isinstance(confidence, (int, float)):
        confidence = (answer.get("probabilities") or {}).get(choice, 0.0)
    return str(choice), float(confidence)


def decide_via_ollama(message: str, roles: list[Role], settings: Settings) -> tuple[str, float] | None:
    """Use nemotron-3-nano:30b via Ollama to pick the best role."""
    from ..llm.ollama import generate_ollama_chat
    prompt = (
        "You are an intent routing decider in a multi-agent chat system.\n"
        "Select the single best teammate to answer the user's message based on their rules.\n\n"
        "Teammates:\n"
        + "\n".join(f"- ID '{r.id}' ({r.name}): When to answer -> {r.when}" for r in roles)
        + f"\n\nUser message: {message[:1000]}\n\n"
        "Return ONLY a JSON object with this exact shape: {\"role_id\": \"<chosen_id>\", \"confidence\": 0.95}"
    )
    try:
        reply = generate_ollama_chat(
            model="nemotron-3-nano:30b",
            messages=[{"role": "user", "content": prompt}],
            settings=settings,
            timeout=8.0,
        )
        text = reply.text.strip()
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            parsed = json.loads(text[start : end + 1])
            chosen_id = parsed.get("role_id")
            if any(r.id == chosen_id for r in roles):
                conf = float(parsed.get("confidence", 0.9))
                return chosen_id, conf
    except Exception as exc:
        logger.debug("Ollama decider failed: %s", exc)
    return None

