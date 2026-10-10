"""Colony Local — orchestrator: one message in, the decider picks an agent, the agent's turn runs in OpenClaw.

Single user. Everything is scoped to one workspace: its team of agents, its one conversation (conversation id =
workspace id) and its memory folder (engine/openclaw.py::memory_dir).
"""
import logging
import time
from datetime import datetime, timezone
from uuid import uuid4

from ..config import get_settings
from ..llm.http import ProviderError
from ..schemas import MessageRequest, MessageResponse
from ..store.history import append_exchange, get_all_messages
from ..engine import openclaw
from . import attachments, mcp
from .agents import Role, ToolAccess, apply_mode
from .context import labelled_history, strip_self_label
from .decider import decide
from .errors import explain
from ..llm.ollama import is_ollama
from .project_folder import project_folder
from .workspaces import get_workspace

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _actions_line(actions: list[str]) -> str:
    """What the agent did to the user's files, added under its reply (so every teammate sees it too)."""
    unique = list(dict.fromkeys(actions))
    shown = " · ".join(unique[:10]) + (f" · +{len(unique) - 10} more" if len(unique) > 10 else "")
    return f"\n\n🛠 {shown}" if unique else ""


def _notice(workspace_id: str, text: str, meta: dict, model: str = "none") -> MessageResponse:
    """A reply from Colony itself (a problem to fix), not from a model. Not saved to the conversation."""
    return MessageResponse(workspace_id=workspace_id, message_id=f"msg_{uuid4().hex}", reply=text,
                           model=model, created_at=_now(), **meta)


def handle_message(request: MessageRequest) -> MessageResponse:
    """Main entry point — one request, one synchronous response. Every agent's turn runs in OpenClaw."""
    started = time.monotonic()
    settings = get_settings()
    workspace = get_workspace(request.workspace_id)          # raises WorkspaceNotFound
    workspace_id = conversation_id = workspace.id
    folder, _ = project_folder(workspace.folder)

    all_connectors = mcp.enabled_names()

    def connectors_for(role: Role) -> list[str]:
        """The connectors this agent may use: the ones set up, narrowed to the ones ticked for it."""
        chosen = role.tools.mcp_servers
        return [name for name in all_connectors if chosen is None or name in chosen]

    def effective_tools(role: Role) -> ToolAccess:
        tools = apply_mode(role.tools, workspace.mode)
        if not connectors_for(role):
            tools = tools.model_copy(update={"mcp": "off"})
        # Connectors don't touch the disk, so they work without a folder; file tools and commands need one to be fenced.
        return tools if folder else ToolAccess(mcp=tools.mcp, mcp_servers=tools.mcp_servers, mcp_apps=tools.mcp_apps)

    # ── 1. Attached files, then the decider picks an agent ────────────────────
    roles = workspace.roles
    text = request.message.strip() or "Please look at the attached file(s)."
    channel = request.channel or request.role_id or "auto"
    try:
        refs = attachments.resolve(settings, workspace_id, request.attachments)
    except attachments.AttachmentError as exc:
        return _notice(workspace_id, f"⚠️ {exc}", {"channel": channel})
    unreadable = attachments.unreadable({r["kind"] for r in refs})
    if unreadable:
        return _notice(workspace_id, f"⚠️ Agents run through OpenClaw, which can only read images, PDFs and text files, not {attachments.labels(unreadable)}.",
                       {"channel": channel})

    direct = next((r for r in roles if r.id == request.role_id), None)

    from .activity import add_step, clear_activity, set_activity, take_steps
    set_activity(workspace_id, step="routing", detail="Routing intent (Nemotron-3-nano / Laya)...")

    decision = decide(message=text, roles=roles, settings=settings, direct_role=direct)
    role = decision.role
    tools = effective_tools(role)
    set_activity(
        workspace_id,
        step="thinking",
        agent_name=role.name,
        model=role.model,
        detail=f"{role.name} ({role.model}) is preparing response...",
    )
    # Where this was typed: the group chat ("auto") or an agent's direct chat. Display only.
    meta = {
        "channel": channel,
        "role_id": role.id,
        "role_name": role.name,
        "decided_by": decision.source,
        "confidence": decision.confidence,
    }
    if not settings.mock_mode and not (is_ollama(role.model) or role.model.startswith("openclaw/")):
        clear_activity(workspace_id)
        return _notice(workspace_id, f"⚠️ {role.name} uses `{role.model}`, which is not an Ollama model, and Colony now runs only Ollama models "
                       f"through OpenClaw. Click ✎ on {role.name} and pick one from the list.", meta)

    # ── 2. The conversation, labelled by speaker ──────────────────────────────
    # OpenClaw keeps and compacts each agent's own session, so it gets the whole conversation to pick "what this session has
    # not seen" from (engine/openclaw.py::unseen); a message that was cut out of the history would no longer be found and
    # the whole history would be sent again.
    note, media = attachments.render(settings, workspace_id, refs, recent=True)
    full_text = text + note
    messages = [m for m in get_all_messages(conversation_id) if not m.get("evicted")]
    history, history_ids = labelled_history(settings, workspace_id, messages, next_media=len(media))

    # ── 3. The agent's turn in OpenClaw ───────────────────────────────────────
    actions: list[str] = []
    actual_model = role.model
    openclaw_session = None
    memory_before = ""
    thinking = ""
    if settings.mock_mode:
        from .trace import describe       # a believable trace so the UI can be tried without a Gateway
        for tool, params, out in (("exec", {"command": "ls -la"}, "total 8\n-rw-r--r--  README.md"), ("read", {"path": "README.md"}, "# Demo"),
                                  ("memory_search", {"query": text[:40]}, "no results")):
            add_step(workspace_id, describe(tool, params, out, None, 120))
        reply_text = f"[mock] {role.name} ({role.model}) — {text[:80]}" + (f" [+{len(refs)} file(s)]" if refs else "")
    elif not (settings.openclaw_gateway_enabled and openclaw.is_openclaw_available(settings)):
        return _notice(workspace_id, "⚠️ OpenClaw Gateway ยังไม่พร้อม — รอสักครู่หลังเปิด `colony` หรือตรวจสอบที่ Settings", meta)
    else:
        memory_before = openclaw.snapshot_memory(settings, workspace_id)
        try:
            openclaw_res = openclaw.run_openclaw_turn(
                settings=settings,
                role_id=role.id,
                role_name=role.name,
                role_model=role.model,
                role_instructions=role.instructions,
                workspace_id=workspace_id,
                channel=channel,
                user_message=full_text,
                history=history,
                history_ids=history_ids,
                tools=tools,
                web_search=role.web_search,
                connectors=connectors_for(role),
                media=media,
                folder=folder,
            )
            reply_text = openclaw_res.reply
            # the Gateway names the agent (openclaw/<id>); what a person wants to see is the model that answered
            actual_model = role.model if openclaw_res.model.startswith("openclaw/") else openclaw_res.model
            actions = openclaw_res.actions
            thinking = openclaw_res.thinking
            openclaw_session = openclaw_res.session_user
        except ProviderError as exc:
            logger.error("OpenClaw Gateway turn error: %s", exc)
            return MessageResponse(
                workspace_id=workspace_id, message_id=f"msg_{uuid4().hex}",
                reply=explain(exc, role.model),
                model=role.model, created_at=_now(), **meta,
            )

    # ── 4. "Remember this": the agent writes the memory files; if it didn't, Colony keeps the user's own words ─────
    reply_text = strip_self_label(reply_text, role.name)
    memory_saved = bool(openclaw_session and openclaw.keep_if_asked(settings, workspace_id, text, memory_before))
    reply_text += _actions_line(actions)

    steps, worked_s = take_steps(workspace_id), round(time.monotonic() - started, 1)
    meta = {**meta, "steps": steps, "worked_s": worked_s, "thinking": thinking or None}

    # ── 5. Persist ────────────────────────────────────────────────────────────
    _, assistant_msg_id = append_exchange(
        conversation_id=conversation_id,
        user_message=text,
        attachments=refs,
        assistant_response={"reply": reply_text, "model": actual_model, **meta},
        channel=channel,
    )
    if openclaw_session:
        openclaw.mark_seen(settings, openclaw_session, assistant_msg_id)

    clear_activity(workspace_id)

    return MessageResponse(
        workspace_id=workspace_id, message_id=assistant_msg_id,
        reply=reply_text, model=actual_model, memory_saved=memory_saved,
        actions=actions,
        created_at=_now(), **meta,
    )
