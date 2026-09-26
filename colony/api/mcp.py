"""Connectors (MCP servers): list them, change them, add Composio with just a key."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..core import mcp

router = APIRouter()


class Servers(BaseModel):
    servers: dict[str, mcp.McpServer]


class ComposioKey(BaseModel):
    key: str


def _view() -> dict:
    return {"servers": {name: mcp.masked(server) for name, server in mcp.load().items()}}


@router.get("/mcp")
def get_servers() -> dict:
    return _view()


@router.put("/mcp")
def put_servers(payload: Servers) -> dict:
    try:
        mcp.save(payload.servers)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _view()


@router.post("/mcp/composio")
def add_composio(payload: ComposioKey) -> dict:
    """Composio Connect: 1000+ apps behind one address. The key is the "consumer key" from Composio's dashboard."""
    if not payload.key.strip():
        raise HTTPException(status_code=400, detail="Paste your Composio consumer key first.")
    servers = mcp.load()
    servers["composio"] = mcp.composio(payload.key)
    mcp.save(servers)
    return _view()
