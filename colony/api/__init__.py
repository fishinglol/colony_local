"""HTTP layer — thin routers, no business logic. Mounted at /api by colony.app."""
from fastapi import APIRouter

from . import agents, attachments, chat, memory, settings, tools, workspaces

router = APIRouter()
for module in (chat, agents, attachments, settings, memory, tools, workspaces):
    router.include_router(module.router)
