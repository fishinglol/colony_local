"""Colony Local — Jev decider.

Asks Jev (TypeSafe's decision model, served by OpenRouter's Decisions API)
which of the USER-DEFINED roles should answer a message. Each role's `when`
text becomes one Jev choice criterion, so the user fully controls the rules.

API (https://openrouter.ai/docs/guides/community/jev-tutorial):
  POST https://openrouter.ai/api/alpha/decisions
  request:  {"model", "state": {...}, "questions": {"role": {"type": "choice",
             "instructions", "criteria": {role_id: when}}}}
  response: {"answers": {"role": {"choice", "confidence", "probabilities"}}, ...}

Auth: the existing openrouter_api_key.
"""
import logging
from dataclasses import dataclass

from ..config import Settings
from ..llm.http import ProviderError, post_json
from ..llm.providers import openrouter_headers
from .agents import Role

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeciderResult:
    role: Role
    confidence: float   # Jev's confidence for the chosen role (0–1)
    source: str         # "jev" | "direct" | "only_role" | "fallback"


def decide(message: str, roles: list[Role], settings: Settings, direct_role: Role | None = None) -> DeciderResult:
    """Pick which role answers.

    direct_role set (user messaged a role directly) → skip Jev.
    One role only → no decision to make.
    Any Jev failure → first role, source="fallback" (shown in the UI).
    """
    if direct_role:
        return DeciderResult(role=direct_role, confidence=1.0, source="direct")
    if len(roles) == 1:
        return DeciderResult(role=roles[0], confidence=1.0, source="only_role")
    if not settings.openrouter_api_key:
        return DeciderResult(role=roles[0], confidence=0.0, source="fallback")

    payload = {
        "model": settings.jev_model,
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
        # retries=0: Jev sits on the hot path of every message, so fail fast and fall back.
        data = post_json(
            settings.jev_decisions_url, payload, openrouter_headers(settings),
            timeout=10.0, provider_name="Jev", retries=0,
        )
        role_id, confidence = parse_jev_answer(data, [r.id for r in roles])
    except (ProviderError, KeyError, ValueError, TypeError) as exc:
        logger.warning("Jev decider failed (%s) — falling back to first agent", exc)
        return DeciderResult(role=roles[0], confidence=0.0, source="fallback")

    role = next(r for r in roles if r.id == role_id)
    return DeciderResult(role=role, confidence=confidence, source="jev")


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
