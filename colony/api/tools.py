"""Endpoints for agent tools: the approval questions, and whether a model can use tools at all."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import get_settings
from ..core.approvals import approvals
from ..core.context import supports_tools

router = APIRouter()


class Answer(BaseModel):
    approve: bool


@router.get("/approvals")
def get_approvals() -> dict:
    """Actions an agent is waiting to do until the user says yes or no (the UI polls this during a reply)."""
    return {"approvals": approvals.pending()}


@router.post("/approvals/{approval_id}")
def answer_approval(approval_id: str, answer: Answer) -> dict:
    if not approvals.resolve(approval_id, answer.approve):
        raise HTTPException(status_code=404, detail="That question was already answered or has timed out.")
    return {"status": "ok"}


@router.get("/models/tools")
def model_supports_tools(model: str) -> dict:
    """true / false / null (unknown). The editor locks the tool switches when this is false."""
    return {"supported": supports_tools(model.strip(), get_settings())}
