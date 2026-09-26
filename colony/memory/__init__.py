"""Long-term memory the assistant learns about the user (USER.md / MEMORY.md / knowledge files).

Public API — everything else is internal to the package:
  learned_context(user_id, query)      text injected into every prompt
  save_explicit_memory(user_id, fact)  "remember this" -> written immediately
  pop_unseen_summary(user_id)          what the last background review changed
  maybe_review_in_background(...)      called after each chat turn
  forget(user_id)                      delete everything stored for that user (a deleted workspace)
Memory is kept per workspace: callers pass the workspace id as `user_id`.
"""
from .files import delete_user as forget
from .recall import learned_context, pop_unseen_summary, save_explicit_memory
from .review import maybe_review_in_background

__all__ = ["forget", "learned_context", "maybe_review_in_background", "pop_unseen_summary", "save_explicit_memory"]
