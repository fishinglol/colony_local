"""Files attached to chat messages, and what each model is able to do with them.

Files are saved under ~/.colony/attachments/<workspace id>/ (never inside the conversation file). A message only
keeps small references to them. When a message is sent to a model, each attachment becomes:
  - text / code files -> their content, pasted into the message (works for every model);
  - images -> image parts and PDFs -> file parts (OpenClaw reads their text itself); audio and video -> a short note
    that they can't be read, so the shared conversation still makes sense;
and only the last few attachment messages are sent in full, so an old photo isn't re-uploaded on every turn.
"""
import base64
import json
from pathlib import Path
from uuid import uuid4

from ..config import Settings

_MIME = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp",
    ".pdf": "application/pdf",
    ".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime", ".mpeg": "video/mpeg", ".mpg": "video/mpeg",
    ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4", ".ogg": "audio/ogg", ".flac": "audio/flac", ".aac": "audio/aac",
}
_KIND = {"image": (".png", ".jpg", ".jpeg", ".gif", ".webp"), "pdf": (".pdf",),
         "video": (".mp4", ".webm", ".mov", ".mpeg", ".mpg"), "audio": (".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac")}
LABEL = {"image": "images", "pdf": "PDFs", "video": "video", "audio": "audio"}

KEEP_RECENT = 3            # only the newest messages with files are sent to the model in full
MAX_TEXT_CHARS = 60_000    # a text file longer than this is cut, with a note
MAX_FILES = 10             # per message


class AttachmentError(ValueError):
    """A file that can't be attached; the message is safe to show the user."""


def _root(settings: Settings, workspace_id: str) -> Path:
    return settings.data_dir / "attachments" / workspace_id


def _valid_id(attachment_id: str) -> bool:
    return len(attachment_id) == 32 and all(c in "0123456789abcdef" for c in attachment_id)


def kind_of(name: str, raw: bytes) -> str:
    """image | pdf | video | audio | text. Anything else that isn't readable text is refused."""
    suffix = Path(name).suffix.lower()
    for kind, suffixes in _KIND.items():
        if suffix in suffixes:
            return kind
    try:
        raw.decode("utf-8")
        binary = b"\0" in raw[:8192]
    except UnicodeDecodeError:
        binary = True
    if binary:
        raise AttachmentError(f"“{name}” isn't a kind of file Colony can read yet (images, PDFs, video, audio and text/code files are).")
    return "text"


def save(settings: Settings, workspace_id: str, name: str, raw: bytes) -> dict:
    """Store an uploaded file. Returns its reference {id, name, kind, mime, size}."""
    name = Path(name).name.strip()[:120] or "file"
    limit = settings.max_attachment_mb * 1024 * 1024
    if not raw:
        raise AttachmentError(f"“{name}” is empty.")
    if len(raw) > limit:
        raise AttachmentError(f"“{name}” is bigger than {settings.max_attachment_mb} MB.")
    kind = kind_of(name, raw)
    ref = {"id": uuid4().hex, "name": name, "kind": kind,
           "mime": _MIME.get(Path(name).suffix.lower(), "text/plain" if kind == "text" else "application/octet-stream"),
           "size": len(raw)}
    folder = _root(settings, workspace_id)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / ref["id"]).write_bytes(raw)
    (folder / f"{ref['id']}.json").write_text(json.dumps(ref), encoding="utf-8")
    return ref


def get(settings: Settings, workspace_id: str, attachment_id: str) -> dict | None:
    """The reference of a saved file, or None."""
    if not _valid_id(attachment_id):
        return None
    try:
        return json.loads((_root(settings, workspace_id) / f"{attachment_id}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def file_path(settings: Settings, workspace_id: str, attachment_id: str) -> Path:
    return _root(settings, workspace_id) / attachment_id


def resolve(settings: Settings, workspace_id: str, ids: list[str]) -> list[dict]:
    """References for the ids a message names. Raises AttachmentError for one that doesn't exist."""
    refs = []
    for attachment_id in ids[:MAX_FILES]:
        ref = get(settings, workspace_id, attachment_id)
        if ref is None:
            raise AttachmentError("One of the attached files is no longer there. Attach it again.")
        refs.append(ref)
    return refs


def unreadable(kinds: set[str]) -> list[str]:
    """The kinds of file (from `kinds`) no agent can read: every agent runs through OpenClaw, which takes images, PDFs and text."""
    return sorted(k for k in kinds if k not in ("text", "image", "pdf"))


def labels(kinds: list[str]) -> str:
    names = [LABEL[k] for k in kinds]
    return " and ".join([", ".join(names[:-1]), names[-1]] if len(names) > 1 else names)


def _data_uri(ref: dict, raw: bytes) -> str:
    return f"data:{ref['mime']};base64,{base64.b64encode(raw).decode()}"


def part(settings: Settings, workspace_id: str, ref: dict) -> dict | None:
    """The chat-completions content part carrying this file, or None if the file is gone."""
    try:
        raw = file_path(settings, workspace_id, ref["id"]).read_bytes()
    except OSError:
        return None
    kind = ref["kind"]
    if kind == "image":
        return {"type": "image_url", "image_url": {"url": _data_uri(ref, raw)}}
    if kind == "pdf":
        return {"type": "file", "file": {"filename": ref["name"], "file_data": _data_uri(ref, raw)}}
    if kind == "video":
        return {"type": "video_url", "video_url": {"url": _data_uri(ref, raw)}}
    return {"type": "input_audio", "input_audio": {"data": base64.b64encode(raw).decode(), "format": Path(ref["name"]).suffix.lower().lstrip(".")}}


def render(settings: Settings, workspace_id: str, refs: list[dict], *, recent: bool) -> tuple[str, list[dict]]:
    """(text to add after the message, references whose media should be attached)."""
    lines, media = [], []
    for ref in refs:
        name, kind = ref["name"], ref["kind"]
        if kind == "text":
            if not recent:
                lines.append(f"[Attached file: {name} — its content was sent earlier and is not repeated]")
                continue
            try:
                text = file_path(settings, workspace_id, ref["id"]).read_bytes().decode("utf-8", errors="replace")
            except OSError:
                lines.append(f"[Attached file: {name} — no longer available]")
                continue
            cut = "\n[…file cut here, it is longer than Colony sends…]" if len(text) > MAX_TEXT_CHARS else ""
            lines.append(f"[Attached file: {name}]\n```\n{text[:MAX_TEXT_CHARS]}{cut}\n```")
        elif unreadable({kind}):
            lines.append(f"[Attached {kind}: {name} — agents that run through OpenClaw can only read images, PDFs and text files]")
        elif recent:
            lines.append(f"[Attached {kind}: {name}]")
            media.append(ref)
        else:
            lines.append(f"[Attached {kind}: {name} — sent earlier and not repeated]")
    return ("\n\n" + "\n\n".join(lines)) if lines else "", media
