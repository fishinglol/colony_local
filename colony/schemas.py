"""Colony Local — request/response schemas.

Simplified from backend/app/ai_ant/schemas.py:
- Removed plan_id, plan_name, route_source, approval_required (no quota)
- Removed workspace_id, project_id, connected_connectors (not in local)
- Removed AiAntIntent/AiAntExecutionMode (overkill for local)
"""
from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class MessageRequest(BaseModel):
    workspace_id: str | None = None   # which workspace's conversation; None = the first workspace
    # Generous on purpose: pasting a long work update is the point of a shared context.
    message: str = Field(default="", max_length=100_000)
    attachments: list[str] = Field(default_factory=list, max_length=10)   # ids from POST /workspaces/{id}/attachments
    role_id: str | None = None   # message one role directly — skips Jev
    # Which room the user typed in: "auto" (the group chat) or an agent id (that agent's direct chat).
    # Only decides where the message is DISPLAYED; every agent still sees the whole conversation.
    channel: str | None = Field(default=None, max_length=40)

    @model_validator(mode="after")
    def _something_to_send(self) -> "MessageRequest":
        if not self.message.strip() and not self.attachments:
            raise ValueError("Write a message or attach a file.")
        return self


class MessageResponse(BaseModel):
    workspace_id: str
    message_id: str
    reply: str
    model: str
    role_id: str | None = None
    role_name: str | None = None
    channel: str = "auto"
    decided_by: str | None = None      # "jev" | "direct" | "only_role" | "fallback"
    confidence: float | None = None
    memory_saved: bool = False
    created_at: datetime
