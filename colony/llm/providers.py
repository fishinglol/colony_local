"""Colony Local — OpenRouter / OpenAI chat calls.

Lifted from backend/app/ai_ant/providers.py. Builds the prompt and payload; the
HTTP itself (SSL, retries, error handling) lives in llm/http.py.
"""
import time
from dataclasses import dataclass

from ..config import Settings
from ..core.models import accepts_temperature
from .http import ProviderError, post_json

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
OPENAI_BASE = "https://api.openai.com/v1"
MEMORY_SAVE_PREFIX = "MEMORY_SAVE:"

_SYSTEM_PROMPT = (
    "You are Colony Local — a multi-AI assistant that lets you talk to multiple AI models "
    "from one place, with shared memory across all of them. "
    "Reply helpfully and concisely. Always reply in the same language the user writes in. "
    "If the request involves external sending, publishing, deleting, payments, or irreversible changes, "
    "explain that you cannot execute such actions and suggest what the user should do instead. "
    f"If the user explicitly asks you to remember something, confirm it and end your reply with one "
    f"last line exactly like: {MEMORY_SAVE_PREFIX} <the fact to remember, one sentence>"
)


_TEAM_NOTE = (
    "This chat has several teammates who take turns answering, each possibly running on a different AI model. "
    "Earlier assistant messages begin with the teammate's name in [brackets], e.g. [Coder]; they may have been "
    "written by someone other than you. Use them as shared context, and don't claim another teammate's words as your own. "
    "Never start your own reply with a [Name] prefix."
)


WEB_PLUGIN = {"id": "web", "max_results": 5}   # OpenRouter's web search: the results are put in front of any model


@dataclass(frozen=True)
class ProviderResult:
    text: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    sources: tuple[tuple[str, str], ...] = ()    # (title, url) of the pages a web search used


def _identity_system_message(model: str) -> dict:
    return {
        "role": "system",
        "content": (
            f'You are currently being served as the model "{model}" via OpenRouter. '
            "If asked what model, LLM, or version you are, state this exact identity."
        ),
    }


def _role_system_message(role_name: str, instructions: str) -> dict:
    content = f'In this workspace you answer as the teammate "{role_name}".'
    if instructions.strip():
        content += f" How the user wants this teammate to answer:\n{instructions.strip()}"
    return {"role": "system", "content": content}


def system_messages(
    model: str, role_name: str, role_instructions: str,
    memory_context: str | None, attributed_history: bool = False, earlier_summary: str | None = None,
) -> list[dict]:
    """Everything a model is told before the conversation starts (identity, role, team note, summary, memory)."""
    messages: list[dict] = [{"role": "system", "content": _SYSTEM_PROMPT}, _identity_system_message(model)]
    if role_name:
        messages.append(_role_system_message(role_name, role_instructions))
    if attributed_history:
        messages.append({"role": "system", "content": _TEAM_NOTE})
    if earlier_summary:
        messages.append({
            "role": "system",
            "content": (
                "This conversation began before the messages below. The older messages were replaced by this summary "
                f"(written by an assistant; the newest messages are exact):\n{earlier_summary}"
            ),
        })
    if memory_context:
        messages.append({
            "role": "system",
            "content": (
                f"Relevant context about this user (long-term memory, learned preferences):\n{memory_context}\n\n"
                "Apply remembered preferences when they fit; use the rest only if relevant."
            ),
        })
    return messages


def build_messages(
    model: str, message: str | list[dict], role_name: str, role_instructions: str,
    memory_context: str | None, history: list[dict] | None,
    attributed_history: bool = False, earlier_summary: str | None = None,
) -> list[dict]:
    """The exact message list sent to a model. Also used to measure how full its context is."""
    messages = system_messages(model, role_name, role_instructions, memory_context, attributed_history, earlier_summary)
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": message})
    return messages


def openrouter_headers(settings: Settings) -> dict:
    return {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/local-colony",
        "X-Title": "Colony Local",
    }


def openai_headers(settings: Settings) -> dict:
    return {"Authorization": f"Bearer {settings.openai_api_key}", "Content-Type": "application/json"}


def _extract_text(data: dict, provider_name: str) -> str:
    try:
        # Reasoning models can return content=null when they spend the whole token
        # budget thinking; treat that as "no text" rather than a malformed response.
        return (data["choices"][0]["message"].get("content") or "").strip()
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        keys = list(data.keys()) if isinstance(data, dict) else []
        raise ProviderError(f"Unexpected {provider_name} response shape: {exc}. Keys: {keys}") from exc


def _sources(data: dict) -> tuple[tuple[str, str], ...]:
    """The pages OpenRouter's web search cited (message.annotations of type url_citation), without repeats."""
    try:
        notes = data["choices"][0]["message"].get("annotations") or []
    except (KeyError, IndexError, TypeError, AttributeError):
        return ()
    seen: dict[str, str] = {}
    for note in notes:
        cite = note.get("url_citation") if isinstance(note, dict) and note.get("type") == "url_citation" else None
        if isinstance(cite, dict) and isinstance(cite.get("url"), str) and cite["url"] not in seen:
            seen[cite["url"]] = str(cite.get("title") or cite["url"])
    return tuple((title, url) for url, title in seen.items())


def _result(data: dict, text: str, model: str) -> ProviderResult:
    usage = data.get("usage") or {}
    return ProviderResult(
        sources=_sources(data),
        text=text or "I could not generate a response.",
        model=data.get("model") or model,
        input_tokens=usage.get("prompt_tokens") if isinstance(usage.get("prompt_tokens"), int) else None,
        output_tokens=usage.get("completion_tokens") if isinstance(usage.get("completion_tokens"), int) else None,
    )


def generate_openrouter_reply(
    *, settings: Settings, message: str | list[dict], model_hint: str,
    role_name: str = "",
    role_instructions: str = "",
    memory_context: str | None = None,
    history: list[dict] | None = None,
    attributed_history: bool = False,
    earlier_summary: str | None = None,
    reasoning: dict | None = None,     # OpenRouter's `reasoning` field; None = the model's own default
    web_search: bool = False,          # let OpenRouter search the web for this request
) -> ProviderResult:
    if not settings.openrouter_api_key:
        raise ProviderError("OPENROUTER_API_KEY is not configured.")

    model = model_hint if "/" in model_hint else settings.openrouter_default_model
    payload: dict = {
        "model": model,
        "messages": build_messages(model, message, role_name, role_instructions, memory_context, history, attributed_history, earlier_summary),
        "max_tokens": settings.max_output_tokens,
    }
    if accepts_temperature(model):
        payload["temperature"] = 0.7
    if reasoning:
        payload["reasoning"] = reasoning
    if web_search:
        payload["plugins"] = [WEB_PLUGIN]

    data = post_json(
        f"{OPENROUTER_BASE}/chat/completions", payload, openrouter_headers(settings),
        settings.openrouter_timeout_seconds, "OpenRouter", retries=settings.chat_retries,
    )
    return _result(data, _extract_text(data, "OpenRouter"), model)


def ping_model(*, settings: Settings, model: str, reasoning: dict | None = None) -> tuple[str, float]:
    """One tiny real request to `model`, no retries. Returns (reply preview, seconds).
    Raises ProviderError if the model can't be used — the point of the "Test this model" button."""
    if not settings.openrouter_api_key:
        raise ProviderError("OPENROUTER_API_KEY is not configured.", status=401)
    payload: dict = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with the single word: OK"}],
        "max_tokens": 64,
    }
    if reasoning:
        payload["reasoning"] = reasoning
    started = time.monotonic()
    data = post_json(
        f"{OPENROUTER_BASE}/chat/completions", payload, openrouter_headers(settings),
        min(settings.openrouter_timeout_seconds, 60.0), "OpenRouter", retries=0,
    )
    return _extract_text(data, "OpenRouter")[:60], time.monotonic() - started


def generate_openai_reply(
    *, settings: Settings, message: str | list[dict], model_hint: str,
    role_name: str = "",
    role_instructions: str = "",
    memory_context: str | None = None,
    history: list[dict] | None = None,
    attributed_history: bool = False,
    earlier_summary: str | None = None,
) -> ProviderResult:
    """OpenAI fallback — only used when openrouter_api_key is absent."""
    if not settings.openai_api_key:
        raise ProviderError("OPENAI_API_KEY is not configured.")

    model = settings.openai_default_model
    payload = {
        "model": model,
        "messages": build_messages(model, message, role_name, role_instructions, memory_context, history, attributed_history, earlier_summary),
        "max_tokens": settings.max_output_tokens,
    }
    data = post_json(
        f"{OPENAI_BASE}/chat/completions", payload, openai_headers(settings),
        settings.openai_timeout_seconds, "OpenAI", retries=settings.chat_retries,
    )
    result = _result(data, _extract_text(data, "OpenAI"), model)
    return ProviderResult(result.text, model, result.input_tokens, result.output_tokens)


def complete_chat(
    *, settings: Settings, system_prompt: str, user_prompt: str,
    temperature: float = 0.0, max_tokens: int = 400,
) -> str:
    """Minimal single-turn completion for internal tasks (memory review).
    OpenRouter primary, OpenAI fallback."""
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
    if settings.openrouter_api_key:
        payload: dict = {
            "model": settings.openrouter_routing_model, "messages": messages,
            "max_tokens": max_tokens, "temperature": temperature,
        }
        data = post_json(
            f"{OPENROUTER_BASE}/chat/completions", payload, openrouter_headers(settings),
            settings.openrouter_timeout_seconds, "OpenRouter",
        )
        return _extract_text(data, "OpenRouter")
    if settings.openai_api_key:
        payload = {"model": settings.openai_default_model, "messages": messages, "max_tokens": max_tokens}
        data = post_json(
            f"{OPENAI_BASE}/chat/completions", payload, openai_headers(settings),
            settings.openai_timeout_seconds, "OpenAI",
        )
        return _extract_text(data, "OpenAI")
    raise ProviderError("No AI provider configured (set OPENROUTER_API_KEY in ~/.colony/.env).")
