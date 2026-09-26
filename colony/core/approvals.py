"""Questions an agent's tool asks the user ("may I write this file?") while a reply is being made.

The chat request that is running the agent blocks in `ask()`; the UI polls `pending()` and answers
through `resolve()`. Nobody answering in time counts as "no".
"""
import threading
from dataclasses import dataclass, field
from itertools import count


@dataclass
class Approval:
    id: str
    agent: str
    tool: str
    title: str
    message: str
    answered: threading.Event = field(default_factory=threading.Event)
    approved: bool = False


class Approvals:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._open: dict[str, Approval] = {}
        self._ids = count(1)

    def ask(self, *, agent: str, tool: str, title: str, message: str, timeout: float) -> bool:
        """Wait for the user's answer. True only for an explicit yes."""
        with self._lock:
            approval = Approval(f"ap{next(self._ids)}", agent, tool, title, message)
            self._open[approval.id] = approval
        try:
            approval.answered.wait(timeout)
            return approval.approved
        finally:
            with self._lock:
                self._open.pop(approval.id, None)

    def pending(self) -> list[dict]:
        with self._lock:
            return [{"id": a.id, "agent": a.agent, "tool": a.tool, "title": a.title, "message": a.message}
                    for a in self._open.values()]

    def resolve(self, approval_id: str, approve: bool) -> bool:
        """Record the user's answer. False if it no longer exists (already answered or timed out)."""
        with self._lock:
            approval = self._open.get(approval_id)
        if approval is None:
            return False
        approval.approved = approve
        approval.answered.set()
        return True


approvals = Approvals()
