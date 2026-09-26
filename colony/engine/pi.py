"""Runs one agent turn that may use tools (read/write files, run commands) through Pi.

Pi (https://github.com/earendil-works/pi) is the engine: it talks to the model, runs the tool loop and does
the file work. Colony stays in charge of everything else: which agent answers, the shared conversation
and memory (they arrive as the system prompt and the prompt), and who may do what (colony-gate.ts).

Each turn is a fresh `pi --mode rpc --no-session` process: Colony's own history is the single source of truth,
so there is no second conversation store to keep in step. See local/spike-pi/README.md for how this was proven.
"""
import json
import os
import queue
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..config import Settings
from ..core.agents import ToolAccess
from ..llm.http import ProviderError

GATE = Path(__file__).with_name("colony-gate.ts")
RUNTIME_DIR = Path(__file__).resolve().parents[2] / "pi-runtime"
RUNTIME_PI = RUNTIME_DIR / "node_modules" / ".bin" / "pi"
MCP_EXTENSION = RUNTIME_DIR / "colony-mcp.ts"
MCP_ADAPTER = RUNTIME_DIR / "node_modules" / "pi-mcp-adapter" / "index.ts"
PROVIDER = "colony"
# Pi's tools run with what we pass here; nothing else from our environment (API keys!) is handed over.
_ENV_PASSTHROUGH = ("PATH", "HOME", "USER", "LANG", "LC_ALL", "TMPDIR", "SHELL")

TOOLS_NOTE = (
    "You can work on files in the user's workspace folder with the tools you were given. Stay inside that folder. "
    "Some actions need the user's approval and may be refused; if one is, say what you wanted to do and carry on "
    "without it. When you are done, say briefly what you did and where."
)

MCP_NOTE = (
    "You can use the user's connected apps through the `mcp` tool: search for a tool (`search`), look at its parameters "
    "(`describe`), then call it (`tool` + `args`). Each call may need the user's approval and may be refused; if one is, say what "
    "you wanted to do and carry on. You cannot add, install or sign in to connectors; the user does that in Colony's settings."
)

# (tool, what it wants to do) -> allowed?
Approver = Callable[[str, str], bool]


class EngineError(RuntimeError):
    """The tools engine itself failed (not the AI model). `user_message` is safe to show the user."""

    def __init__(self, user_message: str):
        super().__init__(user_message)
        self.user_message = user_message


@dataclass(frozen=True)
class PiResult:
    text: str
    actions: list[str]   # what the agent did, e.g. ["wrote notes.txt", "ran `pytest`"]


def transcript_prompt(history: list[dict], message: str) -> str:
    """Pi takes one prompt, so the shared conversation goes in as text (assistant lines already carry [Name])."""
    if not history:
        return message
    lines = [f"User: {m['content']}" if m["role"] == "user" else m["content"] for m in history]
    return "Conversation so far:\n\n" + "\n\n".join(lines) + f"\n\n---\nThe user's new message:\n{message}"


# Levels are sent to OpenRouter as they are (Pi's own "off" becomes OpenRouter's "none").
_THINKING_LEVELS = {"off": "none", "minimal": "minimal", "low": "low", "medium": "medium", "high": "high", "xhigh": "xhigh", "max": "max"}


def _thinking_config(thinking: str | None) -> dict:
    """Pi only sends a thinking level for a model it is told can reason, and it lowers levels the model doesn't
    declare (xhigh/max became high; off sent nothing) — so declare them all and pass each through unchanged."""
    return {"reasoning": True, "thinkingLevelMap": dict(_THINKING_LEVELS)} if thinking else {}


def find_pi(settings: Settings) -> str | None:
    for candidate in (settings.pi_bin, str(RUNTIME_PI)):
        if candidate and Path(candidate).exists():
            return candidate
    return shutil.which("pi")


def _write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def _summarize(tool: str, args: dict) -> str:
    path = str(args.get("path") or args.get("file_path") or "")
    if tool == "write":
        return f"wrote {path}"
    if tool == "edit":
        return f"edited {path}"
    if tool == "read":
        return f"read {path}"
    if tool == "bash":
        command = str(args.get("command") or "")
        return f"ran `{command[:60]}{'…' if len(command) > 60 else ''}`"
    if tool == "mcp":
        return f"used connector {args.get('tool')}" if args.get("tool") else "looked through the connectors"
    return f"{tool} {path}".strip()


def _provider_error(text: str) -> ProviderError:
    """Pi reports a failed model call as '429: {json}' or a plain sentence; give it back its status."""
    head, _, rest = text.partition(":")
    status = int(head) if head.strip().isdigit() else 502
    detail = rest.strip() or text
    try:
        body = json.loads(detail)
        error = body.get("error", body) if isinstance(body, dict) else {}
        detail = (error.get("metadata") or {}).get("raw") or error.get("message") or detail
    except (ValueError, AttributeError):
        pass
    return ProviderError(text[:300], status=status, provider_message=str(detail)[:300])


def _tail(process: subprocess.Popen) -> str:
    try:
        return process.stderr.read().decode(errors="replace").strip()[-300:] if process.stderr else ""
    except (OSError, ValueError):
        return ""


def run_turn(
    *, settings: Settings, model: str, system_prompt: str, prompt: str, workspace: Path,
    tools: ToolAccess, approve: Approver, thinking: str | None = None, images: list[dict] | None = None,
    mcp_servers: dict[str, dict] | None = None,
) -> PiResult:
    """Let `model` work on `prompt` in `workspace` with the tools `tools` allows. Blocks until it is done.
    Raises EngineError (engine problem), ProviderError (the model call failed)."""
    pi = find_pi(settings)
    if not pi:
        raise EngineError("ยังไม่ได้ติดตั้ง Pi (ตัวรันเครื่องมือของ agent) รัน `npm install` ในโฟลเดอร์ `local/pi-runtime` ก่อน แล้วลองใหม่")
    if not settings.openrouter_api_key:
        raise EngineError("agent ที่ใช้เครื่องมือต้องมี OpenRouter API key ตั้งค่าที่ **Settings** ก่อน")

    agent_dir = settings.data_dir / "pi-agent"
    _write_private(agent_dir / "models.json", json.dumps({"providers": {PROVIDER: {
        "baseUrl": settings.openrouter_base_url, "api": "openai-completions",
        "apiKey": settings.openrouter_api_key,
        "models": [{"id": model, **_thinking_config(thinking)}],
    }}}))
    _write_private(agent_dir / "system-prompt.md", system_prompt)
    use_mcp = tools.mcp != "off" and bool(mcp_servers)
    if use_mcp:
        if not (MCP_EXTENSION.exists() and MCP_ADAPTER.exists()):
            raise EngineError("ยังไม่ได้ติดตั้งตัวเชื่อม MCP รัน `npm install` ในโฟลเดอร์ `local/pi-runtime` ก่อน แล้วลองใหม่")
        _write_private(agent_dir / "mcp-turn.json", json.dumps({"mcpServers": mcp_servers}))
    tools = tools if use_mcp or tools.mcp == "off" else tools.model_copy(update={"mcp": "off"})   # no servers = no connector tool

    command = [
        pi, "--mode", "rpc", "--no-session", "--provider", PROVIDER, "--model", model,
        "--system-prompt", str(agent_dir / "system-prompt.md"), "--tools", ",".join(tools.pi_tools()),
        # Nothing but what Colony hands over: no CLAUDE.md, skills, extensions or settings from the workspace.
        "--no-context-files", "--no-skills", "--no-prompt-templates", "--no-themes", "--no-extensions", "--no-approve",
        "-e", str(GATE),
        *(["-e", str(MCP_EXTENSION)] if use_mcp else []),
    ]
    if thinking:                      # off | minimal | low | medium | high | xhigh | max (None = the model's own default)
        command += ["--thinking", thinking]
    env = {k: os.environ[k] for k in _ENV_PASSTHROUGH if k in os.environ}
    env.update({
        "PI_CODING_AGENT_DIR": str(agent_dir), "PI_OFFLINE": "1", "PI_SKIP_VERSION_CHECK": "1", "PI_TELEMETRY": "0",
        "COLONY_POLICY": json.dumps(tools.policy()),
        **({"COLONY_MCP_FILE": str(agent_dir / "mcp-turn.json")} if use_mcp else {}),
        "COLONY_APPROVAL_TIMEOUT_MS": str(int(settings.approval_timeout_seconds * 1000) + 5000),
    })
    try:
        process = subprocess.Popen(command, cwd=workspace, env=env, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as exc:
        raise EngineError(f"เปิด Pi ไม่ได้: {exc}") from exc

    lines: queue.Queue[bytes | None] = queue.Queue()

    def read_stdout() -> None:
        for line in process.stdout:  # type: ignore[union-attr]
            lines.put(line)
        lines.put(None)

    threading.Thread(target=read_stdout, daemon=True).start()

    def send(record: dict) -> None:
        process.stdin.write(json.dumps(record).encode() + b"\n")  # type: ignore[union-attr]
        process.stdin.flush()  # type: ignore[union-attr]

    text, actions, running, errors = "", [], {}, []
    deadline = time.monotonic() + settings.tools_turn_timeout_seconds
    try:
        send({"id": "prompt", "type": "prompt", "message": prompt, **({"images": images} if images else {})})
        while True:
            try:
                line = lines.get(timeout=1.0)
            except queue.Empty:
                if time.monotonic() > deadline:
                    raise EngineError("agent ใช้เวลานานเกินไป จึงหยุดให้ ลองแบ่งงานให้เล็กลงแล้วส่งใหม่")
                continue
            if line is None:
                raise EngineError(f"Pi หยุดทำงานกลางคัน {_tail(process)}".strip())
            record = json.loads(line)
            kind = record.get("type")
            if kind == "extension_ui_request" and record.get("method") == "confirm":
                try:
                    allowed = bool(approve(str(record.get("title")), str(record.get("message"))))
                except Exception:  # never leave Pi waiting: an error while asking means "no"
                    allowed = False
                send({"type": "extension_ui_response", "id": record["id"], "confirmed": allowed})
            elif kind == "tool_execution_start":
                running[record["toolCallId"]] = _summarize(record["toolName"], record.get("args") or {})
            elif kind == "tool_execution_end":
                done = running.pop(record["toolCallId"], record["toolName"])
                actions.append(done + (" ✗" if record.get("isError") else ""))
            elif kind == "message_end" and record["message"].get("role") == "assistant":
                message = record["message"]
                if message.get("stopReason") == "error" or message.get("errorMessage"):
                    errors.append(str(message.get("errorMessage") or "error"))
                said = "".join(p.get("text", "") for p in message.get("content", []) if isinstance(p, dict) and p.get("type") == "text")
                if said.strip():
                    text = said.strip()
            elif kind == "agent_settled":
                break
    finally:
        try:
            process.stdin.close()  # type: ignore[union-attr]
            process.wait(timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            process.kill()

    if not text and errors:
        raise _provider_error(errors[-1])
    return PiResult(text or "I could not generate a response.", actions)
