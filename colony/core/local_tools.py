"""Colony Local — Native Tools Execution & Fencing.

Implements safe workspace tools (read_file, write_file, edit_file, bash_command, web_search)
fenced to the project folder, integrated with Colony's human-in-the-loop Approval Cards.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from .approvals import approvals

# JSON Schemas in OpenAI/Ollama tool calling standard
LOCAL_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a text file inside the project workspace folder.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to the file inside workspace"}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or overwrite a file in the project workspace folder. Requires user approval.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to the file"},
                    "content": {"type": "string", "description": "Full file content to write"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Replace a target block of text in an existing file. Requires user approval.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to the file"},
                    "old_text": {"type": "string", "description": "Exact text to find and replace"},
                    "new_text": {"type": "string", "description": "Replacement text"},
                },
                "required": ["path", "old_text", "new_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bash_command",
            "description": "Run a shell/bash command in the project workspace folder. Requires user approval.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command line to execute"}
                },
                "required": ["command"],
            },
        },
    },
]


def _safe_path(folder: Path, relative_path: str) -> Path:
    """Ensure path stays within workspace folder fence."""
    cleaned = Path(relative_path).expanduser()
    if cleaned.is_absolute():
        resolved = cleaned.resolve()
    else:
        resolved = (folder / cleaned).resolve()

    try:
        resolved.relative_to(folder.resolve())
    except ValueError as exc:
        raise PermissionError(f"Access denied: path '{relative_path}' escapes project workspace folder") from exc
    return resolved


def execute_local_tool(
    *,
    tool_name: str,
    args: dict[str, Any],
    folder: Path,
    agent_name: str,
    timeout: float = 60.0,
    approval_timeout: float = 120.0,
) -> tuple[str, str | None]:
    """Execute a tool. Returns (result_string, action_summary_or_None)."""
    if tool_name == "read_file":
        rel_path = args.get("path", "")
        target = _safe_path(folder, rel_path)
        if not target.exists():
            return f"Error: file '{rel_path}' does not exist.", None
        if not target.is_file():
            return f"Error: '{rel_path}' is not a file.", None
        try:
            content = target.read_text(encoding="utf-8", errors="replace")
            # Truncate if too long (50KB cap)
            if len(content) > 50_000:
                content = content[:50_000] + "\n...[truncated]"
            return content, None
        except Exception as exc:
            return f"Error reading file '{rel_path}': {exc}", None

    elif tool_name == "write_file":
        rel_path = args.get("path", "")
        content = args.get("content", "")
        target = _safe_path(folder, rel_path)

        # Ask human approval via Colony Approval Card
        approved = approvals.ask(
            agent=agent_name,
            tool="write",
            title=f"Write {rel_path}",
            message=f"{agent_name} wants to write {len(content)} characters to {rel_path}",
            timeout=approval_timeout,
        )
        if not approved:
            return "User denied permission to write this file.", None

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"Successfully wrote {rel_path} ({len(content)} bytes).", f"wrote {rel_path}"

    elif tool_name == "edit_file":
        rel_path = args.get("path", "")
        old_text = args.get("old_text", "")
        new_text = args.get("new_text", "")
        target = _safe_path(folder, rel_path)

        if not target.exists():
            return f"Error: file '{rel_path}' does not exist.", None

        file_content = target.read_text(encoding="utf-8", errors="replace")
        if old_text not in file_content:
            return f"Error: target text not found in '{rel_path}'.", None

        # Ask human approval
        approved = approvals.ask(
            agent=agent_name,
            tool="edit",
            title=f"Edit {rel_path}",
            message=f"{agent_name} wants to edit {rel_path}",
            timeout=approval_timeout,
        )
        if not approved:
            return "User denied permission to edit this file.", None

        new_file_content = file_content.replace(old_text, new_text, 1)
        target.write_text(new_file_content, encoding="utf-8")
        return f"Successfully edited {rel_path}.", f"edited {rel_path}"

    elif tool_name == "bash_command":
        cmd = args.get("command", "")
        # Ask human approval
        approved = approvals.ask(
            agent=agent_name,
            tool="command",
            title=f"Run command",
            message=f"{agent_name} wants to run: {cmd}",
            timeout=approval_timeout,
        )
        if not approved:
            return "User denied permission to run this command.", None

        try:
            res = subprocess.run(
                cmd,
                shell=True,
                cwd=folder,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            out = (res.stdout + "\n" + res.stderr).strip()
            if not out:
                out = f"[Command exited with code {res.returncode}]"
            elif len(out) > 30_000:
                out = out[:30_000] + "\n...[output truncated]"
            return out, f"ran `{cmd[:30]}`"
        except subprocess.TimeoutExpired:
            return f"Error: Command timed out after {timeout} seconds.", f"timeout `{cmd[:30]}`"
        except Exception as exc:
            return f"Error running command: {exc}", None

    return f"Unknown tool: {tool_name}", None
