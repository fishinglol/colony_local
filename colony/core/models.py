"""Models offered in the agent editor's dropdown: the Ollama models OpenClaw runs (context windows in llm/ollama.py).

Any other Ollama model id can still be typed in the editor's "Other…" option; this list is a convenience, not a limit.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class PoolModel:
    model_id: str
    label: str
    note: str


MODEL_POOL: tuple[PoolModel, ...] = (
    PoolModel("ollama/nemotron-3-nano:30b", "Nemotron 3 Nano 30B", "Router / Fast"),
    PoolModel("ollama/nemotron-3-super",    "Nemotron 3 Super",    "Reasoning"),
    PoolModel("ollama/nemotron-3-ultra",    "Nemotron 3 Ultra",    "Top Reasoning"),
    PoolModel("ollama/gemma4:31b",          "Gemma 4 31B",         "Writer / Chat"),
    PoolModel("ollama/gpt-oss:20b",         "GPT OSS 20B",         "Code / Data"),
    PoolModel("ollama/gpt-oss:120b",        "GPT OSS 120B",        "Deep Code"),
)
