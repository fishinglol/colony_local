"""HTTP layer — thin routers, no business logic. Mounted at /api by colony.app."""
from fastapi import APIRouter

from . import agents, attachments, chat, links, mcp, memory, plugins, settings, tools, workspaces

router = APIRouter()
for module in (chat, agents, attachments, links, mcp, memory, plugins, settings, tools, workspaces):
    router.include_router(module.router)
