"""Colony Local — Core Agent Loop & Tool Batch Admission (OpenClaw Architecture).

Controls step-by-step turn execution:
LLM call -> Tool call detection -> Tool Batch Admission -> Human Approval -> Tool execution -> Feed results -> Continue.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import Settings
from ..llm.ollama import generate_ollama_chat, is_ollama
from .local_tools import LOCAL_TOOL_DEFINITIONS, execute_local_tool

logger = logging.getLogger(__name__)


@dataclass
class AgentLoopOutcome:
    reply: str
    actions: list[str] = field(default_factory=list)
    model: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None


def run_agent_loop(
    *,
    model: str,
    messages: list[dict[str, Any]],
    settings: Settings,
    folder: Path | None,
    agent_name: str,
    workspace_id: str | None = None,
    tools_enabled: bool = True,
    max_turns: int = 8,
) -> AgentLoopOutcome:
    """Execute the multi-turn agent loop until model finishes or max turns reached."""
    working_messages = list(messages)
    actions: list[str] = []
    final_text = ""
    tools_def = LOCAL_TOOL_DEFINITIONS if (tools_enabled and folder) else None

    turn = 0
    while turn < max_turns:
        turn += 1

        if workspace_id:
            from .activity import set_activity
            set_activity(
                workspace_id,
                step="thinking",
                detail=f"{agent_name} is reasoning (turn {turn})...",
                agent_name=agent_name,
                model=model,
            )

        # Call model
        reply = generate_ollama_chat(
            model=model,
            messages=working_messages,
            settings=settings,
            tools=tools_def,
        )

        final_text = reply.text

        # If no tool calls, model produced final text answer
        if not reply.tool_calls:
            break

        # If model requested tools
        # 1. Append assistant message containing tool calls
        working_messages.append({
            "role": "assistant",
            "content": reply.text or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": tc.arguments},
                }
                for tc in reply.tool_calls
            ],
        })

        # 2. Tool Batch Admission & Execution
        for tc in reply.tool_calls:
            cmd_info = tc.arguments.get("command") or tc.arguments.get("path") or tc.arguments.get("query") or ""
            if workspace_id:
                from .activity import set_activity
                set_activity(
                    workspace_id,
                    step="tool_call",
                    detail=f"{agent_name} is running {tc.name}...",
                    command=f"{tc.name} {cmd_info}".strip(),
                    agent_name=agent_name,
                    model=model,
                )

            if not folder:
                tool_output = "Error: no project workspace folder configured for file tools."
                action_item = None
            else:
                tool_output, action_item = execute_local_tool(
                    tool_name=tc.name,
                    args=tc.arguments,
                    folder=folder,
                    agent_name=agent_name,
                    timeout=settings.tools_turn_timeout_seconds,
                    approval_timeout=settings.approval_timeout_seconds,
                )

            if action_item:
                actions.append(action_item)
                if workspace_id:
                    from .activity import add_action, set_activity
                    add_action(workspace_id, action_item)
                    set_activity(
                        workspace_id,
                        step="tool_result",
                        detail=f"{agent_name}: {action_item}",
                        command=f"{tc.name} {cmd_info}".strip(),
                        agent_name=agent_name,
                        model=model,
                    )

            # 3. Inject tool result back to message history
            working_messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "name": tc.name,
                "content": str(tool_output),
            })

    return AgentLoopOutcome(
        reply=final_text,
        actions=actions,
        model=model,
    )
