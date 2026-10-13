"""What an agent did during a turn, as short steps the chat can show ("Ran command", "Read file", "Searched memory", ...).

OpenClaw reports each finished tool call to Colony (colony-gate plugin, after_tool_call). A step keeps what a person
wants to see: what it was, the command or path, a bounded piece of the output, whether it worked and how long it took.
"""
import json
from typing import Any
from urllib.parse import urlparse

OUTPUT_LIMIT = 3000


def _text(result: Any) -> str:
    """The readable text of a tool result (OpenClaw wraps it as {content: [{type: "text", text}]} or similar)."""
    if result is None:
        return ""
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        content = result.get("content")
        if isinstance(content, list):
            parts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
            if parts:
                return "\n".join(parts)
        for key in ("output", "stdout", "text", "aggregated"):
            if isinstance(result.get(key), str):
                return result[key]
    try:
        return json.dumps(result, ensure_ascii=False, indent=1)
    except (TypeError, ValueError):
        return str(result)


def _clean(value: Any) -> str:
    """Web results arrive wrapped in <<<EXTERNAL_UNTRUSTED_CONTENT>>> / "Source: Web Search" / "---" lines: keep only the text."""
    lines = str(value or "").splitlines()
    return " ".join(l.strip() for l in lines if l.strip() and not l.startswith(("<<<", "Source:")) and l.strip() != "---")


def _sources(tool: str, params: dict, text: str) -> list[dict]:
    """The pages a web tool really returned: [{title, url, site, snippet}], so the chat can show what was read."""
    try:
        data = json.loads(text)
    except ValueError:
        data = {}
    data = data if isinstance(data, dict) else {}
    if tool == "web_fetch":
        found = [{"title": data.get("title"), "url": params.get("url") or data.get("url")}]
    else:
        found = [r for r in data.get("results") or [] if isinstance(r, dict)]
    out = []
    for r in found:
        url = str(r.get("url") or "")
        if urlparse(url).scheme not in ("http", "https"):
            continue
        host = urlparse(url).netloc
        out.append({"title": _clean(r.get("title")) or host, "url": url, "site": _clean(r.get("siteName")) or host,
                    "snippet": _clean(r.get("snippet"))[:300]})
    return out


def _where(params: dict) -> str:
    path = str(params.get("path") or params.get("file") or params.get("file_path") or "")
    offset, limit = params.get("offset"), params.get("limit")
    if path and isinstance(offset, int) and isinstance(limit, int):
        return f"{path}#L{offset}-{offset + limit - 1}"
    return path


def describe(tool: str, params: dict | None, result: Any = None, error: str | None = None, ms: int | None = None) -> dict:
    """One step: {tool, kind, title, detail, output, ok, ms}."""
    params = params if isinstance(params, dict) else {}
    kind, title, detail = "other", tool, ""
    if tool in ("exec", "bash", "process"):
        kind, title, detail = "command", "Ran command", str(params.get("command") or params.get("action") or "")
    elif tool == "read":
        kind, title, detail = "read", "Read", _where(params)
    elif tool in ("write", "apply_patch"):
        kind, title, detail = "write", "Wrote", _where(params)
    elif tool == "edit":
        kind, title, detail = "write", "Edited", _where(params)
    elif tool == "skills_read":
        kind, title, detail = "skill", "Used skill", str(params.get("name") or "")
    elif tool == "memory_search":
        kind, title, detail = "memory", "Searched memory", str(params.get("query") or "")
    elif tool == "memory_get":
        kind, title, detail = "memory", "Read memory", _where(params)
    elif tool == "web_search":
        kind, title, detail = "web", "Searched the web", str(params.get("query") or "")
    elif tool == "web_fetch":
        kind, title, detail = "web", "Opened a page", str(params.get("url") or "")
    elif "__" in tool:
        server, _, name = tool.partition("__")
        kind, title, detail = "connector", f"Used {server}", name
    else:
        detail = json.dumps(params, ensure_ascii=False)[:200] if params else ""
    output = (error or _text(result)).strip()
    step = {"tool": tool, "kind": kind, "title": title, "detail": detail[:600], "output": output[:OUTPUT_LIMIT],
            "ok": not error, "ms": ms}
    if kind == "web" and not error:
        step["sources"] = _sources(tool, params, output)      # parsed before the output is cut at OUTPUT_LIMIT
    return step
