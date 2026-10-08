"""Colony Local — orchestrator.

Rewritten from backend/app/ai_ant/orchestrator.py.
Removed: subscription/quota gate, plan gating, cross-workspace memory,
          project_context, installed_skills, usage recording, Supabase auth.
Kept:     memory context injection, history injection, self_improve trigger.

Single user. Everything is scoped to one workspace: its team of agents, its one conversation (conversation id =
workspace id) and its memory (memory user = workspace id).
"""
import logging
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .. import memory
from ..config import get_settings
from ..engine.pi import MCP_NOTE, TOOLS_NOTE, EngineError, run_turn, transcript_prompt
from ..llm.providers import (
    MEMORY_SAVE_PREFIX,
    ProviderError,
    generate_openai_reply,
    generate_openrouter_reply,
    is_kaggle,
    system_messages,
)
from ..llm.ollama import is_ollama, generate_ollama_chat
from .agent_loop import run_agent_loop
from ..schemas import MessageRequest, MessageResponse
from ..store.history import append_exchange
from ..engine import openclaw
from . import attachments, compaction, mcp
from .agents import PLAN_NOTE, Role, ToolAccess, apply_mode
from .approvals import approvals
from .context import input_modalities, plan_history, reasoning_param, strip_self_label, supports_tools
from .decider import decide
from .errors import explain
from .project_folder import project_folder
from .workspaces import get_workspace

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def split_memory_marker(reply: str) -> tuple[str, str | None]:
    """Strip a trailing 'MEMORY_SAVE: <fact>' line. Returns (clean_reply, fact)."""
    lines = reply.rstrip().splitlines()
    if not lines:
        return reply, None
    last = lines[-1].strip().strip("`*_ ")
    if not last.startswith(MEMORY_SAVE_PREFIX):
        return reply, None
    fact = last[len(MEMORY_SAVE_PREFIX):].strip()
    return "\n".join(lines[:-1]).rstrip(), (fact or None)


def _actions_line(actions: list[str]) -> str:
    """What the agent did to the user's files, added under its reply (so every teammate sees it too)."""
    unique = list(dict.fromkeys(actions))
    shown = " · ".join(unique[:10]) + (f" · +{len(unique) - 10} more" if len(unique) > 10 else "")
    return f"\n\n🛠 {shown}" if unique else ""


def _notice(workspace_id: str, text: str, meta: dict, model: str = "none") -> MessageResponse:
    """A reply from Colony itself (a problem to fix), not from a model. Not saved to the conversation."""
    return MessageResponse(workspace_id=workspace_id, message_id=f"msg_{uuid4().hex}", reply=text,
                           model=model, created_at=_now(), **meta)


def _cannot_read(role: Role, bad: list[str], with_tools: bool, others: list[Role]) -> str:
    text = f"⚠️ {role.name} (`{role.model}`) can't read {attachments.labels(bad)}"
    text += " — agents that use tools can only read images and text files." if with_tools else "."
    if others:
        return text + f" Ask {', '.join(o.name for o in others)} instead, or change {role.name}'s model."
    return text + f" Change {role.name}'s model to one that accepts it (the model picker's Inputs row shows what each model reads)."


def _nobody_can_read(roles: list[Role], refs: list[dict], blocked, tools_on: bool) -> str:
    media = sorted({r["kind"] for r in refs if r["kind"] != "text"})
    missing = [k for k in media if all(k in blocked(r) for r in roles)]
    files = ", ".join(r["name"] for r in refs)
    if not missing:
        return f"⚠️ No single agent can read all of these files ({attachments.labels(media)}) — send them in separate messages."
    return (f"⚠️ None of the agents in this workspace can read {attachments.labels(missing)} (attached: {files}). "
            "Edit an agent and pick a model that accepts it — the model picker's Inputs row shows what each model reads — or remove the file."
            + (" Agents that use tools can only read images and text files." if tools_on else ""))


def _no_folder_dir(settings) -> Path:
    """Where Pi runs when the workspace has no project folder (only connectors are on, so nothing is read or written here)."""
    empty = settings.data_dir / "pi-agent" / "no-folder"
    empty.mkdir(parents=True, exist_ok=True)
    return empty


def _sources_block(sources) -> str:
    """The pages a web search used, as a short list under the reply."""
    if not sources:
        return ""
    return "\n\n**Sources**\n" + "\n".join(f"{i}. [{title}]({url})" for i, (title, url) in enumerate(sources[:6], 1))


def handle_message(request: MessageRequest) -> MessageResponse:
    """Main entry point — one request, one synchronous response."""
    settings = get_settings()
    workspace = get_workspace(request.workspace_id)          # raises WorkspaceNotFound
    workspace_id = conversation_id = workspace.id
    folder, _ = project_folder(workspace.folder)

    # A workspace without a folder is still a useful place to talk. Keep each
    # agent's saved permissions, but do not start Pi until there is a directory
    # that can safely fence its file tools.
    all_connectors = mcp.enabled_for_pi()

    def connectors_for(role: Role) -> dict[str, dict]:
        """The connectors this agent may use: the ones set up, narrowed to the ones ticked for it."""
        chosen = role.tools.mcp_servers
        return {name: cfg for name, cfg in all_connectors.items() if chosen is None or name in chosen}

    def effective_tools(role: Role) -> ToolAccess:
        tools = apply_mode(role.tools, workspace.mode)
        if not connectors_for(role):
            tools = tools.model_copy(update={"mcp": "off"})
        # Connectors don't touch the disk, so they work without a folder; file tools and commands need one to be fenced.
        return tools if folder else ToolAccess(mcp=tools.mcp, mcp_servers=tools.mcp_servers, mcp_apps=tools.mcp_apps)

    # ── 1. Which agents can read the attached files, then Jev picks among them ────
    roles = workspace.roles
    text = request.message.strip() or "Please look at the attached file(s)."
    channel = request.channel or request.role_id or "auto"
    try:
        refs = attachments.resolve(settings, workspace_id, request.attachments)
    except attachments.AttachmentError as exc:
        return _notice(workspace_id, f"⚠️ {exc}", {"channel": channel})
    kinds = {r["kind"] for r in refs}

    def blocked(role: Role) -> list[str]:
        return attachments.unreadable(kinds, input_modalities(role.model, settings), effective_tools(role).any_on)

    direct = next((r for r in roles if r.id == request.role_id), None)
    if direct and blocked(direct):
        able = [r for r in roles if r is not direct and not blocked(r)]
        return _notice(workspace_id, _cannot_read(direct, blocked(direct), effective_tools(direct).any_on, able), {"channel": channel})
    candidates = roles if direct else [r for r in roles if not blocked(r)]
    if not candidates:
        return _notice(workspace_id, _nobody_can_read(roles, refs, blocked, any(effective_tools(r).any_on for r in roles)), {"channel": channel})

    from .activity import set_activity
    set_activity(workspace_id, step="routing", detail="Routing intent (Nemotron-3-nano / Jev)...")

    decision = decide(message=text, roles=candidates, settings=settings, direct_role=direct)
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

    # ── 2. Shared history + long-term memory (same for every model) ───────────
    # Labelled by speaker, and trimmed if this model's context window is too small for it.
    memory_context = memory.learned_context(workspace_id, query=text)
    # The files are described (or attached) the way THIS model can take them.
    note, media = attachments.render(settings, workspace_id, refs, inputs=input_modalities(role.model, settings),
                                     recent=True, with_tools=tools.any_on)
    full_text = text + note
    earlier_summary, recent_messages = compaction.view(conversation_id)
    plan = plan_history(
        model=role.model, role=role, settings=settings, memory_context=memory_context,
        messages=recent_messages, next_message=full_text, earlier_summary=earlier_summary,
        workspace_id=workspace_id, with_tools=tools.any_on, next_media=len(media),
    )

    # ── 3. Call the role's model ──────────────────────────────────────────────
    actions: list[str] = []
    if settings.mock_mode:
        reply_text = f"[mock] {role.name} ({role.model}) — {text[:80]}" + (f" [+{len(refs)} file(s)]" if refs else "")
        actual_model = role.model
    elif (
        settings.openclaw_gateway_enabled
        and openclaw.is_openclaw_available(settings)
        and not is_kaggle(role.model)
        and not is_ollama(role.model)
        and (role.model.startswith("openclaw/") or not (settings.openrouter_api_key or settings.openai_api_key))
    ):
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
                history=plan.history,
            )
            reply_text = openclaw_res.reply
            actual_model = openclaw_res.model
            actions = openclaw_res.actions
        except ProviderError as exc:
            logger.error("OpenClaw Gateway turn error: %s", exc)
            return MessageResponse(
                workspace_id=workspace_id, message_id=f"msg_{uuid4().hex}",
                reply=explain(exc, role.model),
                model=role.model, created_at=_now(), **meta,
            )
    elif not (settings.openrouter_api_key or settings.openai_api_key or is_kaggle(role.model) or is_ollama(role.model)):
        return MessageResponse(
            workspace_id=workspace_id, message_id=f"msg_{uuid4().hex}",
            reply="⚠️ ยังไม่ได้ตั้งค่า API key หรือเชื่อมต่อ OpenClaw Gateway — ตรวจสอบที่ Settings",
            model="none", created_at=_now(), **meta,
        )
    elif is_ollama(role.model):
        from ..llm.providers import build_messages
        messages = build_messages(
            role.model, full_text, role.name, role.instructions, memory_context,
            plan.history, plan.attributed, earlier_summary,
        )
        try:
            if tools.any_on:
                loop_res = run_agent_loop(
                    model=role.model,
                    messages=messages,
                    settings=settings,
                    folder=folder,
                    agent_name=role.name,
                    workspace_id=workspace_id,
                    tools_enabled=True,
                )
                reply_text, actual_model, actions = loop_res.reply, role.model, loop_res.actions
            else:
                chat_res = generate_ollama_chat(
                    model=role.model,
                    messages=messages,
                    settings=settings,
                )
                reply_text, actual_model = chat_res.text, role.model
        except ProviderError as exc:
            logger.error("Provider error (ollama): %s", exc)
            return MessageResponse(
                workspace_id=workspace_id, message_id=f"msg_{uuid4().hex}",
                reply=explain(exc, role.model),
                model=role.model, created_at=_now(), **meta,
            )
    elif tools.any_on:
        # An agent with tools runs through Pi; agents without tools take the plain chat path below.
        def refuse(reply: str) -> MessageResponse:
            return _notice(workspace_id, reply, meta, role.model)

        if supports_tools(role.model, settings) is False:
            return refuse(f"⚠️ โมเดล `{role.model}` ใช้เครื่องมือไม่ได้ กด ✎ ที่ agent นี้แล้วเลือกโมเดลอื่น หรือปิดสิทธิ์เครื่องมือ")
        system = "\n\n".join(m["content"] for m in system_messages(
            role.model, role.name, role.instructions, memory_context, plan.attributed, earlier_summary))
        if tools.pi_tools() != ["mcp"]:
            system += "\n\n" + TOOLS_NOTE
        if tools.mcp != "off":
            system += "\n\n" + MCP_NOTE
            if tools.mcp_apps and "composio" in connectors_for(role):
                system += (f" Through Composio use only these apps: {', '.join(tools.mcp_apps)}. "
                           "If the user asks for another app, say it is not connected to you and stop.")
        if workspace.mode == "plan":
            system += "\n\n" + PLAN_NOTE
        level = reasoning_param(role.model, role.reasoning, settings)
        try:
            result = run_turn(
                settings=settings, model=role.model + (":online" if role.web_search and not is_kaggle(role.model) else ""), system_prompt=system,
                thinking=None if level is None else ("off" if level["effort"] == "none" else level["effort"]),
                prompt=transcript_prompt(plan.history, full_text), tools=tools, mcp_servers=connectors_for(role),
                workspace=folder or _no_folder_dir(settings),
                images=attachments.pi_images(settings, workspace_id, media),
                approve=lambda tool, what: approvals.ask(
                    agent=role.name, tool=tool, title=tool, message=what, timeout=settings.approval_timeout_seconds),
            )
        except EngineError as exc:
            logger.error("Tools engine error: %s", exc)
            return refuse(f"⚠️ {exc.user_message}")
        except ProviderError as exc:
            logger.error("Provider error (tools): %s", exc)
            return refuse(explain(exc, role.model))
        reply_text, actual_model, actions = result.text, role.model, result.actions
    else:
        via_openrouter = bool(settings.openrouter_api_key) or is_kaggle(role.model)
        generate = generate_openrouter_reply if via_openrouter else generate_openai_reply
        # OpenRouter takes the agent's reasoning level; the OpenAI fallback has no such setting.
        extra = {"reasoning": reasoning_param(role.model, role.reasoning, settings), "web_search": role.web_search} \
            if via_openrouter else {}
        instructions = role.instructions
        if not folder and role.tools.any_on:
            instructions += "\n\nThis workspace has no project folder, so this is chat only. Do not claim to read, edit, or run anything on the user's computer."
        if role.tools.mcp != "off" and not connectors_for(role):
            instructions += "\n\nNo connectors are set up yet, so you cannot use the user's apps. Do not claim to."
        try:
            result = generate(
                **extra,
                settings=settings,
                message=attachments.user_content(settings, workspace_id, full_text, media),
                model_hint=role.model,
                role_name=role.name,
                role_instructions=instructions,
                memory_context=memory_context,
                history=attachments.with_parts(settings, workspace_id, plan.history),
                attributed_history=plan.attributed,
                earlier_summary=earlier_summary,
            )
        except ProviderError as exc:
            logger.error("Provider error: %s", exc)
            return MessageResponse(
                workspace_id=workspace_id, message_id=f"msg_{uuid4().hex}",
                reply=explain(exc, role.model),
                model=role.model, created_at=_now(), **meta,
            )
        reply_text, actual_model = result.text + _sources_block(getattr(result, "sources", ())), result.model

    # ── 4. "Remember this" → save now, not at the next 5-turn review ──────────
    reply_text, fact = split_memory_marker(strip_self_label(reply_text, role.name))
    memory_saved = bool(fact and memory.save_explicit_memory(workspace_id, fact))
    if fact and not memory_saved:
        # The model already said "I'll remember"; don't leave the user believing it.
        reply_text += "\n\n_(บันทึกความจำนี้ไม่ได้)_"
    reply_text += _actions_line(actions)

    # ── 5. Persist + background review ────────────────────────────────────────
    _, assistant_msg_id = append_exchange(
        conversation_id=conversation_id,
        user_message=text,
        attachments=refs,
        assistant_response={"reply": reply_text, "model": actual_model, **meta},
        channel=channel,
    )
    # OpenClaw Architecture: record episodic daily observation & trigger dreaming
    try:
        obs_text = f"User asked: {text[:80]} -> {role.name} answered"
        if actions:
            obs_text += f" [Actions: {', '.join(actions)}]"
        memory.append_daily_observation(workspace_id, obs_text, origin=role.name)
        memory.maybe_dream_in_background(workspace_id)
    except Exception as exc:
        logger.debug("Episodic observation recording skipped: %s", exc)

    memory.maybe_review_in_background(workspace_id, conversation_id)
    compaction.maybe_compact_in_background(workspace_id)

    from .activity import clear_activity
    clear_activity(workspace_id)

    return MessageResponse(
        workspace_id=workspace_id, message_id=assistant_msg_id,
        reply=reply_text, model=actual_model, memory_saved=memory_saved,
        actions=actions,
        created_at=_now(), **meta,
    )
