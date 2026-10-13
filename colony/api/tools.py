"""Endpoints for agent tools: the approval questions, and whether a model can use tools at all."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import get_settings
from ..core.approvals import approvals
from ..core.context import supports_tools
from ..core.activity import add_step
from ..core.gate import _find, decide
from ..core.trace import describe

router = APIRouter()


class Answer(BaseModel):
    approve: bool


@router.get("/approvals")
def get_approvals() -> dict:
    """Actions an agent is waiting to do until the user says yes or no (the UI polls this during a reply)."""
    return {"approvals": approvals.pending()}


class GateCall(BaseModel):
    agent_id: str
    tool: str
    params: dict = {}
    native: bool = False     # the call comes from a session the app runs on the Gateway (its fence is already in place)


@router.post("/approvals/gate")
def gate(call: GateCall) -> dict:
    """Called by OpenClaw (colony-gate.ts) before each tool call. Blocks while the user is being asked."""
    return decide(get_settings(), call.agent_id, call.tool, call.params, native=call.native)


class ToolResult(BaseModel):
    agent_id: str
    tool: str
    params: dict = {}
    result: object = None
    error: str | None = None
    duration_ms: int | None = None


@router.post("/activity/tool")
def tool_finished(call: ToolResult) -> dict:
    """Called by OpenClaw (colony-gate, after each tool call): becomes a step under the agent's reply."""
    found = _find(call.agent_id)
    if found is not None:
        add_step(found[0].id, describe(call.tool, call.params, call.result, call.error, call.duration_ms), found[1].id)
    return {"status": "ok"}


@router.post("/approvals/{approval_id}")
def answer_approval(approval_id: str, answer: Answer) -> dict:
    if not approvals.resolve(approval_id, answer.approve):
        raise HTTPException(status_code=404, detail="That question was already answered or has timed out.")
    return {"status": "ok"}


@router.get("/models/tools")
def model_supports_tools(model: str) -> dict:
    """true / false. The editor locks the tool switches when this is false."""
    return {"supported": supports_tools(model.strip())}
