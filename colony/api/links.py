"""Open a web address in the user's real browser (the desktop window can't follow links out of the app itself)."""
import webbrowser

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class Link(BaseModel):
    url: str


@router.post("/open-url")
def open_url(link: Link) -> dict:
    if not link.url.startswith(("https://", "http://")):
        raise HTTPException(status_code=400, detail="Only web addresses can be opened.")
    webbrowser.open(link.url)
    return {"status": "ok"}
