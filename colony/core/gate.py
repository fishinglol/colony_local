"""The decision behind every tool call an OpenClaw agent makes: run it, make the user say yes first, or refuse it.

OpenClaw asks (colony/engine/colony-gate.ts, a plugin hooked before each tool call) and does what this says. The rules are
the ones the user set in Colony: the agent's own tool permissions, narrowed by the workspace mode (see apply_mode), and the
project-folder fence. Policy lives here rather than in OpenClaw's config so a change in the UI applies to the very next call.
A question that nobody answers in time counts as "no".
"""
from pathlib import Path

from ..config import Settings
from ..engine.openclaw import agent_id_for, memory_dir
from .agents import Role, apply_mode
from .approvals import approvals
from .project_folder import project_folder
from .workspaces import Workspace, list_workspaces

SHOWN = 600     # characters of file content / command shown in an approval question
FILE_TOOLS = ("read", "write", "edit")


def _find(agent_id: str) -> tuple[Workspace, Role] | None:
    for workspace in list_workspaces():
        for role in workspace.roles:
            if agent_id_for(workspace.id, role.id) == agent_id:
                return workspace, role
    return None


def _kind(tool: str) -> str:
    """read | write | edit | bash | mcp (a connector's `<server>__<tool>`) | other."""
    if tool in FILE_TOOLS:
        return tool
    if tool == "apply_patch":
        return "write"
    if tool in ("exec", "process", "bash"):
        return "bash"
    return "mcp" if "__" in tool else "other"


def escapes(folder: Path, path: object) -> bool:
    """True when `path` (relative to the folder, or absolute) points outside it. Symlinks are followed."""
    if not isinstance(path, str) or not path:
        return False
    try:
        Path(folder, Path(path).expanduser()).resolve().relative_to(folder)
    except ValueError:
        return True
    return False


def describe(tool: str, kind: str, params: dict) -> str:
    path = str(params.get("path") or "")
    if kind == "bash":
        return f"Run this command:\n{str(params.get('command') or '')[:SHOWN]}"
    if kind == "write":
        return f"Write {path}:\n{str(params.get('content') or '')[:SHOWN]}"
    if kind == "edit":
        edits = params.get("edits") if isinstance(params.get("edits"), list) else []
        changes = "\n".join(f"- {str(e.get('oldText', ''))[:200]}\n+ {str(e.get('newText', ''))[:200]}" for e in edits if isinstance(e, dict))
        return f"Edit {path}:\n{changes[:SHOWN]}"
    return f"Use connector tool {tool}:\n{str(params)[:SHOWN]}"


def _no(reason: str) -> dict:
    return {"allow": False, "reason": reason}


def decide(settings: Settings, agent_id: str, tool: str, params: dict) -> dict:
    """{"allow": bool, "reason": str}. May block while the user decides."""
    found = _find(agent_id)
    if found is None:
        return _no("Colony does not know this agent.")
    workspace, role = found
    tools = apply_mode(role.tools, workspace.mode)
    kind = _kind(tool)
    if tool in ("memory_search", "memory_get"):      # read-only, and only over this workspace's own memory folder
        return {"allow": True, "reason": ""}
    # The team's memory files are the agents' own notes: any role may read and write them, by absolute path, with no question.
    # (A relative path would resolve in the project folder, so it follows the normal rules below.)
    path = params.get("path")
    if kind in FILE_TOOLS and isinstance(path, str) and Path(path).is_absolute() and not escapes(memory_dir(settings, workspace.id), path):
        return {"allow": True, "reason": ""}
    folder, _ = project_folder(workspace.folder)
    if kind in FILE_TOOLS or kind == "bash":
        if folder is None:
            return _no("This workspace has no project folder, so files and commands are off.")
        if kind in FILE_TOOLS and escapes(folder, params.get("path")):
            return _no("That path is outside the project folder, so it is off limits.")
    if kind == "read":
        return {"allow": True, "reason": ""} if tools.read != "off" else _no("Reading files is not allowed for this agent.")
    rule = tools.policy().get({"write": "write", "edit": "edit"}.get(kind, kind))
    if rule is None or rule == "off":
        return _no(f"The {tool} tool is not allowed for this agent.")
    if rule == "allow":
        return {"allow": True, "reason": ""}
    shown_as = kind if kind in ("write", "edit", "bash", "mcp") else tool
    ok = approvals.ask(agent=role.name, tool=shown_as, title=shown_as, message=describe(tool, kind, params),
                       timeout=settings.approval_timeout_seconds)
    return {"allow": True, "reason": ""} if ok else _no("The user did not approve this action.")
