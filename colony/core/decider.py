"""Colony Local — decider.

Picks which of the USER-DEFINED roles should answer a message. Each role's `when` text is one choice criterion, so the
user fully controls the rules. Jev's API (JEV_API_KEY, POST /v1/systemone on api.beatapi.io) answers if its key is
set, then a local Laya server (LAYA_URL, same protocol) if it is set; then nemotron-3-nano on Ollama;
if none answers, the first role does.
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
    source: str         # "jev" | "laya" | "nemotron" | "direct" | "mention" | "only_role" | "fallback"


def mentioned_role(message: str, roles: list[Role]) -> Role | None:
    """The role named after an "@" in the message ("@Coder fix this", by name or id, any case); the first mention wins."""
    text = message.lower()
    at = text.find("@")
    while at != -1:
        rest = text[at + 1:]
        found = [(len(key), r) for r in roles for key in (r.name.lower(), r.id.lower())
                 if key and rest.startswith(key) and (len(rest) == len(key) or not rest[len(key)].isalnum())]
        if found:
            return max(found, key=lambda f: f[0])[1]
        at = text.find("@", at + 1)
    return None


def decide(message: str, roles: list[Role], settings: Settings, direct_role: Role | None = None,
           skills: dict[str, str] | None = None) -> DeciderResult:
    """Pick which role answers.

    direct_role set (user messaged a role directly) → no decision.
    One role only → no decision to make.
    "@Name" in the message → that role answers.
    Any decider failure → first role, source="fallback" (shown in the UI).
    `skills` maps a role id to a line about what its skills do; it is added to that role's criterion.
    """
    when = {r.id: f"{r.when} Its skills: {skills[r.id]}" if skills and skills.get(r.id) else r.when for r in roles}
    if direct_role:
        return DeciderResult(role=direct_role, confidence=1.0, source="direct")
    if len(roles) == 1:
        return DeciderResult(role=roles[0], confidence=1.0, source="only_role")
    if named := mentioned_role(message, roles):      # "@Coder …": the user picked, nothing to decide
        return DeciderResult(role=named, confidence=1.0, source="mention")
    # An explicit User-Agent: Cloudflare in front of BeatAPI rejects urllib's default one (403, error 1010).
    json_header = {"Content-Type": "application/json", "User-Agent": "colony-local"}
    endpoints = []   # tried in order; the first that answers wins
    if settings.jev_api_key:
        endpoints.append((f"{settings.jev_url.rstrip('/')}/v1/systemone",
                          {**json_header, "Authorization": f"Bearer {settings.jev_api_key}"}, settings.jev_model, "jev"))
    if settings.laya_url:
        # Laya speaks Jev's protocol; "multilingual" is its checkpoint that reads Thai.
        endpoints.append((f"{settings.laya_url}/v1/systemone", json_header, "multilingual", "laya"))

    for url, headers, model, source in endpoints:
        payload = {
            "model": model,
            "state": {"message": message[:2000]},
            "questions": {
                "role": {
                    "type": "choice",
                    "instructions": "Which teammate should answer this message?",
                    "criteria": when,
                }
            },
        }
        try:
            # retries=0: the decider sits on the hot path of every message, so fail fast and try the next one.
            data = post_json(url, payload, headers, timeout=10.0, provider_name=source.capitalize(), retries=0)
            role_id, confidence = parse_jev_answer(data, [r.id for r in roles])
        except (ProviderError, KeyError, ValueError, TypeError) as exc:
            logger.warning("%s decider failed (%s)", source, exc)   # never logs the key: only the error
            continue
        role = next(r for r in roles if r.id == role_id)
        return DeciderResult(role=role, confidence=confidence, source=source)

    # No endpoint set or none answered (Jev's free tier answers once a minute): ask nemotron before giving up,
    # so a rate limit doesn't silently hand every message to the first agent.
    ollama_res = decide_via_ollama(message, roles, settings, when)
    if ollama_res and any(r.id == ollama_res[0] for r in roles):
        role = next(r for r in roles if r.id == ollama_res[0])
        return DeciderResult(role=role, confidence=ollama_res[1], source="nemotron")
    return DeciderResult(role=roles[0], confidence=0.0, source="fallback")


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


def decide_via_ollama(message: str, roles: list[Role], settings: Settings, when: dict[str, str] | None = None) -> tuple[str, float] | None:
    """Use nemotron-3-nano:30b via Ollama to pick the best role."""
    from ..llm.ollama import generate_ollama_chat
    prompt = (
        "You are an intent routing decider in a multi-agent chat system.\n"
        "Select the single best teammate to answer the user's message based on their rules.\n\n"
        "Teammates:\n"
        + "\n".join(f"- ID '{r.id}' ({r.name}): When to answer -> {(when or {}).get(r.id, r.when)}" for r in roles)
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

