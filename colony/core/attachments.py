"""Files attached to chat messages, and what each model is able to do with them.

Files are saved under ~/.colony/attachments/<workspace id>/ (never inside the conversation file). A message only
keeps small references to them. When a message is sent to a model, each attachment becomes:
  - text / code files -> their content, pasted into the message (works for every model);
  - image / PDF / video / audio -> real media parts, but only if the model's catalog entry says it accepts that
    kind of input; otherwise a short note ("this model can't read images") so the shared conversation still makes
    sense to it;
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
# The `input_modalities` value OpenRouter lists for each kind of file.
NEEDS = {"image": "image", "pdf": "file", "video": "video", "audio": "audio"}
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


def unreadable(kinds: set[str], inputs: list[str] | None, with_tools: bool) -> list[str]:
    """The kinds of file (from `kinds`) that a model can't read. `inputs` is what the catalog says it accepts
    (None = unknown, so trust it). An agent that uses tools runs through Pi, which passes on images and text only."""
    blocked = []
    for kind in sorted(kinds):
        if kind == "text":
            continue
        if (with_tools and kind != "image") or (inputs is not None and NEEDS[kind] not in inputs):
            blocked.append(kind)
    return blocked


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


def render(settings: Settings, workspace_id: str, refs: list[dict], *, inputs: list[str] | None,
           recent: bool, with_tools: bool = False) -> tuple[str, list[dict]]:
    """(text to add after the message, references whose media should be attached) for one model."""
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
        elif unreadable({kind}, inputs, with_tools):
            why = "agents that use tools can only read images and text files" if with_tools and kind != "image" \
                else f"this model can't read {LABEL[kind]}"
            lines.append(f"[Attached {kind}: {name} — {why}]")
        elif recent:
            lines.append(f"[Attached {kind}: {name}]")
            media.append(ref)
        else:
            lines.append(f"[Attached {kind}: {name} — sent earlier and not repeated]")
    return ("\n\n" + "\n\n".join(lines)) if lines else "", media


def with_parts(settings: Settings, workspace_id: str, history: list[dict]) -> list[dict]:
    """History ready to send: a message that has media becomes text + the media parts."""
    ready = []
    for m in history:
        media = m.get("media")
        if not media:
            ready.append(m)
            continue
        parts = [p for p in (part(settings, workspace_id, ref) for ref in media) if p]
        ready.append({"role": m["role"], "content": [{"type": "text", "text": m["content"]}, *parts]} if parts
                     else {"role": m["role"], "content": m["content"]})
    return ready


def user_content(settings: Settings, workspace_id: str, text: str, media: list[dict]) -> str | list[dict]:
    """The user's message as a model wants it: a plain string, or text plus media parts."""
    parts = [p for p in (part(settings, workspace_id, ref) for ref in media) if p]
    return [{"type": "text", "text": text}, *parts] if parts else text


def pi_images(settings: Settings, workspace_id: str, media: list[dict]) -> list[dict]:
    """The images in Pi's own format (Pi can be handed images; tool agents get no other kind of media)."""
    images = []
    for ref in media:
        if ref["kind"] != "image":
            continue
        try:
            raw = file_path(settings, workspace_id, ref["id"]).read_bytes()
        except OSError:
            continue
        images.append({"type": "image", "data": base64.b64encode(raw).decode(), "mimeType": ref["mime"]})
    return images
