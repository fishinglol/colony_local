"""Colony Local — user-defined roles.

A role is one "AI teammate" the user sets up in the UI:
  - name:         shown in the sidebar and on each reply
  - model:        Ollama model id (ollama/<name>) that answers as this role
  - when:         plain-language rule for WHEN this role should answer
                  (the decider's choice criterion)
  - instructions: plain-language rule for HOW this role should answer
                  (sent to the model as a system message)
  - tools:        what the role may do to files on this computer (nothing by default)
  - reasoning:    how hard the model thinks: "default" (the model's own setting) or a level the model supports
  - web_search:   may search the web

Roles belong to a workspace (see core/workspaces.py).
"""
from typing import Literal

from pydantic import BaseModel, Field, field_validator

MAX_ROLES = 8


class ToolAccess(BaseModel):
    """What an agent may do in the workspace folder. "ask" = the user approves each action first."""
    read: Literal["off", "allow"] = "off"
    write: Literal["off", "ask", "allow"] = "off"   # create and edit files
    bash: Literal["off", "ask", "allow"] = "off"    # run commands
    mcp: Literal["off", "ask", "allow"] = "off"     # use the connectors (MCP servers) set up in Connectors
    mcp_servers: list[str] | None = None            # which connectors; None = every enabled one
    mcp_apps: list[str] = Field(default_factory=list, max_length=60)   # apps the agent is told to stay within (Composio); [] = any

    @property
    def any_on(self) -> bool:
        return self.read != "off" or self.write != "off" or self.bash != "off" or self.mcp != "off"

    def policy(self) -> dict[str, str]:
        """Per-tool rule for the approval gate. Reading needs no approval."""
        return {"write": self.write, "edit": self.write, "bash": self.bash, "mcp": self.mcp}


# How much freedom the workspace's agents get to change things, whatever each agent is set to (see apply_mode).
Mode = Literal["auto", "manual", "accept_edits", "plan", "bypass"]

PLAN_NOTE = (
    "PLAN MODE: you may read and look around, but you must not create, edit or delete anything or run commands. "
    "Investigate, then reply with a clear step-by-step plan of what you would do, and wait for the user to switch modes and say go."
)


def apply_mode(tools: ToolAccess, mode: Mode) -> ToolAccess:
    """What an agent may do under the workspace's mode. A mode never switches on a tool the agent doesn't have.
    auto = the agent's own settings; manual = ask before every change; accept_edits = file edits go through,
    commands and connectors still ask; plan = read only; bypass = everything the agent has goes through without asking."""
    if mode == "auto" or not tools.any_on:
        return tools
    if mode == "plan":
        return ToolAccess(read="allow", write="off", bash="off", mcp="off")
    ruled = {"manual": ("ask", "ask", "ask"), "accept_edits": ("allow", "ask", "ask"), "bypass": ("allow", "allow", "allow")}[mode]
    return tools.model_copy(update={
        "write": ruled[0] if tools.write != "off" else "off",
        "bash": ruled[1] if tools.bash != "off" else "off",
        "mcp": ruled[2] if tools.mcp != "off" else "off"})


ReasoningLevel = Literal["default", "off", "minimal", "low", "medium", "high", "xhigh", "max"]


class Role(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=40)
    model: str = Field(min_length=3, max_length=120)
    when: str = Field(min_length=1, max_length=500)
    instructions: str = Field(default="", max_length=2000)
    tools: ToolAccess = Field(default_factory=ToolAccess)
    reasoning: ReasoningLevel = "default"
    web_search: bool = False     # let the model search the web (OpenClaw's web_search tool)

    @field_validator("model")
    @classmethod
    def _model_has_provider(cls, v: str) -> str:
        if "/" not in v:
            raise ValueError("model must be an Ollama id like 'ollama/gemma4:31b'")
        return v.strip()


DEFAULT_ROLES: list[Role] = [
    Role(
        id="reasoning", name="Thinker", model="ollama/nemotron-3-super",
        when="Complex analysis, multi-step reasoning, math, planning, weighing decisions.",
        instructions="Think step by step. Be precise and show the key reasoning.",
    ),
    Role(
        id="chitchat", name="Buddy", model="ollama/nemotron-3-nano:30b",
        when="Casual conversation, greetings, opinions, quick factual questions.",
        instructions="Be friendly and brief.",
    ),
    Role(
        id="writing", name="Writer", model="ollama/gemma4:31b",
        when="Writing, editing, summarizing, translating, drafting emails or documents.",
        instructions="Write clearly and match the tone the user asks for.",
    ),
    Role(
        id="coding", name="Coder", model="ollama/gpt-oss:120b",
        when="Writing, debugging or explaining code, technical design, scripts and commands.",
        instructions="Show the code first, then a short explanation. Point out edge cases.",
    ),
]


def validate_roles(roles: list[Role]) -> list[Role]:
    """The roles unchanged, or ValueError saying what is wrong with the list."""
    if not roles:
        raise ValueError("Keep at least one role.")
    if len(roles) > MAX_ROLES:
        raise ValueError(f"At most {MAX_ROLES} roles.")
    ids = [r.id for r in roles]
    if len(set(ids)) != len(ids):
        raise ValueError("Role ids must be unique.")
    return roles
