"""Models offered in the agent editor's dropdown.

Adapted from backend/app/general_chat/model_pool.py. Ids, context windows and parameter
support below were read from https://openrouter.ai/api/v1/models on 2026-09-25. No prices
are shown on purpose: users already know what each model costs.
Any other OpenRouter id can still be typed in the editor's "Other…" option, and
`~provider/name-latest` aliases (e.g. `~anthropic/claude-opus-latest`) always
point at the newest version, so this list is a convenience, not a limit.
"""
from dataclasses import dataclass

PROVIDER_NAMES = {
    "anthropic": "Anthropic",
    "openai": "OpenAI",
    "google": "Google",
    "deepseek": "DeepSeek",
    "moonshotai": "Moonshot AI (Kimi)",
    "perplexity": "Perplexity",
    "qwen": "Qwen",
    "nvidia": "NVIDIA",
    "z-ai": "Z.ai (GLM)",
    "ollama": "Ollama Cloud",
}


@dataclass(frozen=True)
class PoolModel:
    provider: str
    model_id: str
    label: str
    note: str
    # Several new models (Sonnet 5, GPT-6, Fable 5.1) don't accept `temperature`.
    accepts_temperature: bool = True
    # Max context window in tokens (from OpenRouter's catalog). 0 = unknown.
    context: int = 0


MODEL_POOL: tuple[PoolModel, ...] = (
    PoolModel("anthropic",  "anthropic/claude-fable-5.1",        "Claude Fable 5.1",         "", accepts_temperature=False, context=1_000_000),
    PoolModel("anthropic",  "anthropic/claude-opus-5.5",         "Claude Opus 5.5",          "", context=1_000_000),
    PoolModel("anthropic",  "anthropic/claude-sonnet-5",         "Claude Sonnet 5",          "", accepts_temperature=False, context=1_000_000),
    PoolModel("anthropic",  "anthropic/claude-haiku-4.5",        "Claude Haiku 4.5",         "Fast & cheap", context=200_000),
    PoolModel("openai",     "openai/gpt-6-astra",                "GPT-6 Astra",              "", accepts_temperature=False, context=1_050_000),
    PoolModel("openai",     "openai/gpt-6-sol",                  "GPT-6 Sol",                "", accepts_temperature=False, context=1_050_000),
    PoolModel("openai",     "openai/gpt-6-luna",                 "GPT-6 Luna",               "Cheapest", accepts_temperature=False, context=1_050_000),
    PoolModel("google",     "google/gemini-3.1-pro-preview",     "Gemini 3.1 Pro (preview)", "", context=1_048_576),
    PoolModel("google",     "google/gemini-3.8-flash",           "Gemini 3.8 Flash",         "", context=1_048_576),
    PoolModel("google",     "google/gemini-3.5-flash-lite",      "Gemini 3.5 Flash Lite",    "", context=1_048_576),
    PoolModel("deepseek",   "deepseek/deepseek-v4-pro-0813",     "DeepSeek V4 Pro (0813)",   "", context=1_048_576),
    PoolModel("deepseek",   "deepseek/deepseek-v4.1-flash",      "DeepSeek V4.1 Flash",      "", context=1_048_576),
    PoolModel("moonshotai", "moonshotai/kimi-k3",                "Kimi K3",                  "", context=1_048_576),
    PoolModel("moonshotai", "moonshotai/kimi-k2.7-code",         "Kimi K2.7 Code",           "Built for code", context=262_144),
    PoolModel("perplexity", "perplexity/sonar",                  "Perplexity Sonar",         "Web search + sources", context=127_072),
    PoolModel("perplexity", "perplexity/sonar-pro",              "Perplexity Sonar Pro",     "Deeper web search + sources", context=200_000),
    # Free tier (rate-limited; fine for testing). Reasoning effort is left to each model's
    # default so hidden reasoning doesn't eat the token budget. Some free models (Inkling,
    # Poolside, Cohere North, Liquid, Nemotron 3.5 Lightning) are "agentic harness only" and
    # answer 403 in a plain chat app — deliberately not listed. Use "Test this model" first.
    PoolModel("qwen",       "qwen/qwen3.8-27b:free",                 "Qwen3.8 27B (free)",           "Free", context=262_144),
    PoolModel("nvidia",     "nvidia/nemotron-3-ultra-550b-a55b:free", "Nemotron 3 Ultra 550B (free)", "Free", context=1_000_000),
    PoolModel("google",     "google/gemma-4-31b-it:free",            "Gemma 4 31B (free)",           "Free", context=262_144),
    PoolModel("nvidia",     "nvidia/nemotron-3-super-120b-a12b:free", "Nemotron 3 Super 120B (free)", "Free", context=262_144),
    PoolModel("z-ai",       "z-ai/glm-5.2:free",                     "GLM 5.2 (free)",               "Free · 32k context", context=32_768),
    # Ollama Cloud / Free models
    PoolModel("ollama",     "ollama/nemotron-3-nano:30b",            "Nemotron 3 Nano 30B",          "Router / Fast", context=128_000),
    PoolModel("ollama",     "ollama/nemotron-3-super",               "Nemotron 3 Super",             "Reasoning", context=262_144),
    PoolModel("ollama",     "ollama/nemotron-3-ultra",               "Nemotron 3 Ultra",             "Top Reasoning", context=1_000_000),
    PoolModel("ollama",     "ollama/gemma4:31b",                     "Gemma 4 31B",                  "Writer / Chat", context=262_144),
    PoolModel("ollama",     "ollama/gpt-oss:20b",                    "GPT OSS 20B",                  "Code / Data", context=128_000),
    PoolModel("ollama",     "ollama/gpt-oss:120b",                   "GPT OSS 120B",                 "Deep Code", context=262_144),
)


def _find(model_id: str) -> PoolModel | None:
    return next((m for m in MODEL_POOL if m.model_id == model_id), None)


def accepts_temperature(model_id: str) -> bool:
    """Unknown (custom) ids get no temperature: newer models increasingly reject
    it, and omitting it just means the provider's default."""
    entry = _find(model_id)
    return bool(entry and entry.accepts_temperature)


def known_context_window(model_id: str) -> int | None:
    """Context window (tokens) for a model in the pool, else None."""
    entry = _find(model_id)
    return (entry.context or None) if entry else None
