"""A direct-chat turn whose model run happens in the OpenClaw Gateway, driven by the app over the Gateway's own WebSocket.

The app asks `prepare` for what to send (the agent is set up and told who it is, and what it has not seen yet), runs the turn
with the Gateway itself (live status, tool steps, approvals come straight from OpenClaw), then calls `finish` with the reply
so it joins the team's conversation like any other. Anything `prepare` cannot do natively (files attached, Gateway not
ready) answers {"native": false} and the app falls back to POST /api/messages.
"""
import base64
import hashlib
import time
from datetime import datetime, timezone
from uuid import uuid4

from ..config import get_settings
from ..engine import openclaw
from ..schemas import MessageRequest
from ..store.history import append_exchange, archive_before, get_all_messages
from . import attachments as files, mcp
from .activity import clear_activity, set_activity, take_steps
from .agents import Role, ToolAccess, apply_mode
from .context import drop_commands, labelled_history, strip_self_label
from .decider import decide
from .memory_keep import keep_if_worth
from .project_folder import project_folder
from .workspaces import get_workspace

MAX_HOPS = 3                        # an agent may hand work on at most this many times after the user's message
_turns: dict[str, dict] = {}        # turn id -> what finish needs; a turn the app never finishes is simply dropped with the process


def _not_native(reason: str) -> dict:
    return {"native": False, "reason": reason}


def prepare(request: MessageRequest) -> dict:
    """Set the agent up in OpenClaw and say what to send it. {native: true, turn_id, agent_id, session, model, message}."""
    settings = get_settings()
    workspace = get_workspace(request.workspace_id)
    try:
        refs = files.resolve(settings, workspace.id, request.attachments)
    except files.AttachmentError:
        return _not_native("attachments")       # the normal path tells the user what is wrong with the file
    if files.unreadable({r["kind"] for r in refs}):
        return _not_native("attachments")
    if settings.mock_mode or not (settings.openclaw_gateway_enabled and openclaw.is_openclaw_available(settings)):
        return _not_native("gateway")
    if not openclaw.gateway_prepared(settings):
        return _not_native("preparing")

    text = request.message.strip() or "Please look at the attached file(s)."
    sender = None
    if request.handoff_from:    # a teammate hands this agent a task: only to an agent that accepts them, and not forever
        sender = next((r for r in workspace.roles if r.id == request.handoff_from), None)
        target = next((r for r in workspace.roles if r.id == request.role_id), None)
        if sender is None or target is None or sender.id == target.id or not target.accepts_handoff or request.hops > MAX_HOPS:
            raise ValueError("That handoff is not allowed.")
    if request.role_id:         # an agent's own chat: nothing to decide
        role = next((r for r in workspace.roles if r.id == request.role_id), None)
        if role is None:
            raise ValueError("That agent doesn't exist.")
        decided_by, confidence = "direct", 1.0
    else:                       # the group chat: the decider picks who answers (it also knows what each agent's skills do)
        skills = {r.id: "; ".join(f"{k['name']} ({k['description'][:100]})"
                                  for k in openclaw.list_skills(settings, openclaw.agent_id_for(workspace.id, r.id)))
                  for r in workspace.roles}
        decision = decide(message=text, roles=workspace.roles, settings=settings, skills=skills)
        role, decided_by, confidence = decision.role, decision.source, decision.confidence

    folder, _ = project_folder(workspace.folder)
    chosen = role.tools.mcp_servers
    all_connectors = [n for n in mcp.enabled_names() if chosen is None or n in chosen]
    tools = apply_mode(role.tools, workspace.mode)
    connectors = all_connectors if tools.mcp != "off" else []
    if not all_connectors:
        tools = tools.model_copy(update={"mcp": "off"})
    if not folder:      # connectors need no folder; files and commands do (they are fenced to it)
        tools = ToolAccess(mcp=tools.mcp, mcp_servers=tools.mcp_servers, mcp_apps=tools.mcp_apps)

    agent_id = openclaw.agent_id_for(workspace.id, role.id)
    memory = openclaw.memory_dir(settings, workspace.id)
    openclaw.ensure_agent(settings, agent_id, role.name, tools=tools, web_search=role.web_search, connectors=connectors,
                          folder=str(folder) if folder else None, memory=memory,
                          thinking=role.reasoning if _can_think(role) else "default")
    persona = openclaw.write_agent_files(settings, workspace.id, agent_id, role.name, role.instructions, memory_writable=openclaw.memory_writable(tools, folder))
    channel = request.channel or request.role_id or "auto"
    session_user = openclaw.build_session_user(workspace.id, role.id, channel, persona)

    messages = drop_commands([m for m in get_all_messages(workspace.id) if not m.get("evicted")])
    history, ids = labelled_history(settings, workspace.id, messages)
    missed = openclaw.unseen(settings, session_user, history, ids)[-10:]
    parts = [openclaw.capability_text(settings, agent_id, role.name, tools, role.web_search, connectors, str(folder) if folder else None,
                                         [(r.name, r.when, r.accepts_handoff) for r in workspace.roles if r.id != role.id])]
    if missed:
        parts.append("[The team's conversation since you last answered]\n" + "\n".join(
            f"{'User' if m['role'] == 'user' else 'Teammate'}: {m['content']}" for m in missed if m.get("content")))
    note, media = files.render(settings, workspace.id, refs, recent=True)        # text files are pasted; images and PDFs travel as attachments
    if sender:
        parts.append(f"[{sender.name} hands you this task. Answer it for the team; the user can see your reply]\n{text}")
        decided_by, confidence = "handoff", 1.0
    else:
        parts.append(f"[The user's message]\n{text}{note}")
    sent = []
    for ref in media[:openclaw.MAX_IMAGES]:
        raw = files.file_path(settings, workspace.id, ref["id"]).read_bytes()
        sent.append({"type": "image" if ref["kind"] == "image" else "file", "mimeType": ref["mime"], "fileName": ref["name"],
                     "content": base64.b64encode(raw).decode()})

    set_activity(workspace.id, step="thinking", agent_name=role.name, model=role.model,
                 detail=f"{role.name} ({role.model}) is preparing response...", role_id=role.id)   # starts collecting its steps
    turn_id = f"turn_{uuid4().hex}"
    _turns[turn_id] = {"workspace_id": workspace.id, "role": role, "channel": channel, "text": text, "refs": refs, "session_user": session_user,
                       "decided_by": decided_by, "confidence": confidence,
                       "handed_by": sender.name if sender else None, "hops": request.hops,
                       "memory_before": openclaw.snapshot_memory(settings, workspace.id),
                       "agent_writes_memory": openclaw.memory_writable(tools, folder), "started": time.monotonic()}
    # The Gateway fences the session itself: to the project folder (or, with none, to the team's memory files) and, when the
    # agent may write or run commands, asks the user before commands run (guarded); otherwise it is read-only.
    can_change = tools.write != "off" or tools.bash != "off"
    permission_mode = "guarded" if (not folder or can_change) else "read-only"
    root = str(folder) if folder else str(memory)
    fence = hashlib.sha1(f"{root}|{permission_mode}".encode()).hexdigest()[:6]      # a different fence is a different session
    return {"native": True, "turn_id": turn_id, "agent_id": agent_id, "model": role.model, "role_id": role.id, "role_name": role.name,
            "decided_by": decided_by, "confidence": confidence,
            "session": "native-" + openclaw.resolve_agent_target(session_user) + "-" + fence,
            "cwd": root, "permission_mode": permission_mode, "message": "\n\n".join(parts), "attachments": sent}


def _can_think(role: Role) -> bool:
    from ..llm.ollama import OLLAMA_CLOUD_MODELS, normalize_ollama_model_id
    return bool(OLLAMA_CLOUD_MODELS.get(normalize_ollama_model_id(role.model), {}).get("reasoning"))


def finish(turn_id: str, reply: str | None, failed: bool = False) -> dict:
    """The turn ended: save it to the team's conversation (or just close it when it failed)."""
    turn = _turns.pop(turn_id, None)
    if turn is None:
        raise KeyError(turn_id)
    settings, workspace_id, role = get_settings(), turn["workspace_id"], turn["role"]
    steps = take_steps(workspace_id, role.id)
    clear_activity(workspace_id, role.id)
    if failed or not (reply or "").strip():
        return {"saved": False}
    reply_text = strip_self_label(reply, role.name)
    # the agent writes the memory files itself when it can (AGENTS.md); Colony asks Jev only for agents that cannot
    memory_saved = (not turn["agent_writes_memory"] and not turn["handed_by"]
                    and keep_if_worth(settings, workspace_id, turn["text"], turn["memory_before"]))
    meta = {"channel": turn["channel"], "role_id": role.id, "role_name": role.name, "decided_by": turn["decided_by"],
            "confidence": turn["confidence"],
            "steps": steps, "worked_s": round(time.monotonic() - turn["started"], 1), "thinking": None}
    if turn["handed_by"]:       # nobody typed this task: the reply stands alone, marked as an answer to a teammate
        meta["handed_by"] = turn["handed_by"]
    _, message_id = append_exchange(conversation_id=workspace_id, user_message=None if turn["handed_by"] else turn["text"],
                                    attachments=turn["refs"], assistant_response={"reply": reply_text, "model": role.model, **meta},
                                    channel=turn["channel"])
    openclaw.mark_seen(settings, turn["session_user"], message_id)
    done = {"saved": True, "message_id": message_id, "memory_saved": memory_saved,
            "created_at": datetime.now(timezone.utc).isoformat()}
    if turn["text"].split()[:1] == ["/new"]:    # the user started over: what came before goes to ~/.colony/archive, the app shows only this
        done["archived"] = archive_before(workspace_id, keep_last=2)
        openclaw.forget_usage(settings, [openclaw.agent_id_for(workspace_id, r.id) for r in get_workspace(workspace_id).roles])
    handoff = _handoff(reply_text, get_workspace(workspace_id).roles, role) if turn["hops"] < MAX_HOPS else None
    if handoff:                 # the app runs the teammate's turn next (POST /turns/prepare with handoff_from)
        done["handoff"] = {"role_id": handoff[0].id, "role_name": handoff[0].name, "message": handoff[1], "from": role.id,
                           "hops": turn["hops"] + 1}
    return done


def _handoff(reply: str, roles: list[Role], sender: Role) -> tuple[Role, str] | None:
    """The teammate a reply hands work to: its LAST line starts with "@Name" (name or id, any case) of another agent that accepts
    handoffs. Returns (that role, the rest of the line as the task)."""
    lines = [line.strip() for line in reply.strip().splitlines() if line.strip()]
    if not lines or not lines[-1].startswith("@"):
        return None
    rest = lines[-1][1:]
    best = None
    for r in roles:
        if r.id == sender.id or not r.accepts_handoff:
            continue
        for key in (r.name, r.id):
            n = len(key)
            if key and rest.lower().startswith(key.lower()) and (len(rest) == n or not rest[n].isalnum()) and (best is None or n > best[1]):
                best = (r, n)
    if best is None:
        return None
    task = rest[best[1]:].strip(" \t:,-—")
    return best[0], task or "Please continue from my message above."
