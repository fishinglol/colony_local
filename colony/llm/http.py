"""The one place that talks HTTP to AI APIs (OpenRouter, OpenAI, Jev).

Moved out of providers.py so every caller shares the same SSL setup, retry rules
and error messages. Callers that can't afford to wait (the Jev decider) pass
retries=0.
"""
import json
import logging
import ssl
import time
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

try:
    import certifi
    _SSL_CONTEXT: ssl.SSLContext | None = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CONTEXT = None

# Wait before retry #1, #2, #3… (the last value repeats). Free models are throttled by a
# pool shared with everyone, so a second or two is rarely enough — back off harder.
_BACKOFFS = (1.5, 4.0, 8.0)
_MAX_RETRY_AFTER = 15.0  # never let a Retry-After header make the user wait longer than this
_TRANSIENT_KEYWORDS = (
    "timeout", "rate limit", "overloaded", "throttled",
    "try again", "temporary", "transient", "service unavailable",
    "bad gateway", "gateway timeout",
)


class ProviderError(RuntimeError):
    """An AI provider call failed. `status` is the HTTP/provider error code when there is one
    (None for network problems), so callers can explain it to the user."""

    def __init__(self, message: str, status: int | None = None, provider_message: str | None = None):
        super().__init__(message)
        self.status = status
        self.provider_message = provider_message  # the provider's own words, when it gave any


def _is_transient_http_error(code: int) -> bool:
    return code in (429, 500, 502, 503, 504)


def _is_transient_provider_error(err_data: dict) -> bool:
    code = err_data.get("code")
    if isinstance(code, int) and _is_transient_http_error(code):
        return True
    message = str(err_data.get("message") or "").lower()
    return any(keyword in message for keyword in _TRANSIENT_KEYWORDS)


def _message_from_body(detail: str) -> str:
    """The `error.message` from a provider's JSON error body, else the start of the raw body."""
    try:
        err = json.loads(detail).get("error")
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])
    except (ValueError, AttributeError):
        pass
    return detail[:200]


def _wait_seconds(attempt: int, retry_after: str | None = None) -> float:
    """How long to sleep after failed attempt number `attempt` (1-based)."""
    if retry_after:
        try:
            return min(max(float(retry_after), 0.0), _MAX_RETRY_AFTER)
        except ValueError:
            pass  # a date-form Retry-After: fall back to our own schedule
    return _BACKOFFS[min(attempt - 1, len(_BACKOFFS) - 1)]


def post_json(url: str, payload: dict, headers: dict, timeout: float, provider_name: str, retries: int = 1) -> dict:
    """POST `payload` as JSON and return the decoded JSON object.

    Retries transient failures (429/5xx, network errors, provider `error` bodies that
    look temporary) up to `retries` more times, waiting longer each time (see _BACKOFFS)
    or as long as the provider's Retry-After header says (capped). Anything else raises ProviderError
    carrying the provider's own message.
    """
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST",
    )
    return _send(request, timeout, provider_name, retries)


def get_json(url: str, timeout: float, provider_name: str, headers: dict | None = None) -> dict:
    """GET a JSON object (no retries — callers use this for optional lookups)."""
    request = urllib.request.Request(url, headers=headers or {}, method="GET")
    return _send(request, timeout, provider_name, retries=0)


def _send(request: urllib.request.Request, timeout: float, provider_name: str, retries: int) -> dict:
    attempts = retries + 1
    for attempt in range(1, attempts + 1):
        last_try = attempt == attempts
        try:
            with urllib.request.urlopen(request, timeout=timeout, context=_SSL_CONTEXT) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if not last_try and _is_transient_http_error(exc.code):
                wait = _wait_seconds(attempt, exc.headers.get("Retry-After") if exc.headers else None)
                logger.warning("Transient HTTP %s from %s (attempt %s). Retrying in %.1fs…", exc.code, provider_name, attempt, wait)
                time.sleep(wait)
                continue
            raise ProviderError(
                f"{provider_name} request failed: {exc.code} {detail}",
                status=exc.code, provider_message=_message_from_body(detail),
            ) from exc
        except OSError as exc:
            if not last_try:
                wait = _wait_seconds(attempt)
                logger.warning("Network error from %s (attempt %s): %s. Retrying in %.1fs…", provider_name, attempt, exc, wait)
                time.sleep(wait)
                continue
            raise ProviderError(f"{provider_name} request failed: {exc}") from exc

        if not isinstance(data, dict):
            raise ProviderError(f"Unexpected {provider_name} response format: {type(data).__name__}")
        if "error" in data:
            err = data["error"]
            err_dict = err if isinstance(err, dict) else {}
            msg = err_dict.get("message") or str(err)
            code = err_dict.get("code")
            code_str = f" (code: {code})" if code is not None else ""
            if not last_try and _is_transient_provider_error(err_dict):
                wait = _wait_seconds(attempt)
                logger.warning("Transient provider error from %s (attempt %s): %s%s. Retrying in %.1fs…", provider_name, attempt, msg, code_str, wait)
                time.sleep(wait)
                continue
            raise ProviderError(
                f"{provider_name} error: {msg}{code_str}",
                status=code if isinstance(code, int) else None, provider_message=str(msg),
            )
        return data
    raise ProviderError(f"{provider_name} request failed after {attempts} attempts.")
