"""Memory files on disk: paths, markdown+frontmatter, state, skill/knowledge items.

Lifted from backend/app/ai_ant/self_improve.py (no regex, per repo convention).
Layout under <data_dir>/self_improve/<user_id>/:
  USER.md  MEMORY.md  INDEX.md  state.json  skills/*.md  knowledge/*.md
"""
import json
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path

from ..config import get_settings
from ..llm.http import ProviderError
from ..llm.providers import complete_chat

USER_MAX_CHARS = 1375
MEMORY_MAX_CHARS = 2200
SKILL_MAX_CHARS = 1500
KNOWLEDGE_MAX_CHARS = 1500
MAX_SKILLS = 20
MAX_KNOWLEDGE_FILES = 30

LOCK = threading.RLock()


# ── paths ─────────────────────────────────────────────────────────────────────

def _root_dir() -> Path:
    return get_settings().data_dir / "self_improve"


def _user_dir(user_id: str) -> Path:
    path = _root_dir() / user_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_md_path(user_id: str) -> Path:
    return _user_dir(user_id) / "USER.md"


def memory_md_path(user_id: str) -> Path:
    return _user_dir(user_id) / "MEMORY.md"


def _index_path(user_id: str) -> Path:
    return _user_dir(user_id) / "INDEX.md"


def _state_path(user_id: str) -> Path:
    return _user_dir(user_id) / "state.json"


def _items_dir(user_id: str, kind: str) -> Path:
    path = _user_dir(user_id) / kind
    path.mkdir(parents=True, exist_ok=True)
    return path


def delete_user(user_id: str) -> None:
    """Forget everything stored for `user_id` (a workspace being deleted)."""
    root = _root_dir().resolve()
    folder = (root / user_id).resolve()
    if folder == root or root not in folder.parents:   # never delete outside the memory folder
        raise ValueError(f"Not a memory folder: {user_id!r}")
    with LOCK:
        shutil.rmtree(folder, ignore_errors=True)


# ── file helpers ──────────────────────────────────────────────────────────────

def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def write_text_atomic(path: Path, content: str) -> None:
    tmp = path.with_suffix(f"{path.suffix}.tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


# ── frontmatter (no regex per project convention) ─────────────────────────────

def _format_frontmatter(meta: dict) -> str:
    lines = ["---"]
    for key in ("type", "title", "description", "timestamp"):
        if key in meta and meta[key] is not None:
            lines.append(f"{key}: {meta[key]}")
    lines.append(f"tags: [{', '.join(meta.get('tags') or [])}]")
    lines.append("---")
    return "\n".join(lines)


def _write_md_file(path: Path, meta: dict, body: str) -> None:
    content = _format_frontmatter(meta) + "\n" + body.strip() + "\n"
    write_text_atomic(path, content)


def parse_frontmatter(text: str) -> tuple[dict, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text.strip()
    meta: dict = {}
    i = 1
    while i < len(lines) and lines[i].strip() != "---":
        key, sep, value = lines[i].partition(":")
        if sep:
            key = key.strip()
            value = value.strip()
            if key == "tags":
                meta[key] = [t.strip() for t in value.strip("[]").split(",") if t.strip()]
            else:
                meta[key] = value
        i += 1
    body = "\n".join(lines[i + 1:]).strip()
    return meta, body


def _slugify(title: str) -> str:
    chars: list[str] = []
    prev_dash = False
    for ch in title.strip().lower():
        if ch.isalnum():
            chars.append(ch)
            prev_dash = False
        elif not prev_dash:
            chars.append("-")
            prev_dash = True
    return "".join(chars).strip("-") or "skill"


# ── state ─────────────────────────────────────────────────────────────────────

def _default_state() -> dict:
    return {
        "turns_since_review": 0,
        "unseen_summary": None,
        "skills_migrated": True,   # local always starts fresh
    }


def read_state(user_id: str) -> dict:
    path = _state_path(user_id)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    state = _default_state()
    write_state(user_id, state)
    return state


def write_state(user_id: str, state: dict) -> None:
    write_text_atomic(_state_path(user_id), json.dumps(state, indent=2, ensure_ascii=False) + "\n")


# ── skill / knowledge files ───────────────────────────────────────────────────

def _cap_for(kind: str) -> int:
    return SKILL_MAX_CHARS if kind == "skills" else KNOWLEDGE_MAX_CHARS


def list_files(user_id: str, kind: str) -> list[Path]:
    return sorted(_items_dir(user_id, kind).glob("*.md"))


def item_summaries(user_id: str, kind: str) -> list[dict]:
    summaries = []
    for path in list_files(user_id, kind):
        meta, _ = parse_frontmatter(read_text(path))
        summaries.append({
            "slug": path.stem,
            "title": meta.get("title", path.stem),
            "description": meta.get("description", ""),
            "type": meta.get("type", kind[:-1]),
        })
    return summaries


def _unique_slug(user_id: str, kind: str, title: str) -> str:
    base = _slugify(title)
    existing = {p.stem for p in list_files(user_id, kind)}
    if base not in existing:
        return base
    i = 2
    while f"{base}-{i}" in existing:
        i += 1
    return f"{base}-{i}"


def _regenerate_index(user_id: str) -> None:
    lines = ["# Index", "", "## Skills"]
    for s in item_summaries(user_id, "skills") or [{"title": "(none)", "slug": "", "description": ""}]:
        lines.append(f"- [{s['title']}](skills/{s['slug']}.md) — {s['description']}")
    lines += ["", "## Knowledge"]
    for k in item_summaries(user_id, "knowledge") or [{"title": "(none)", "slug": "", "description": "", "type": ""}]:
        lines.append(f"- [{k['title']}](knowledge/{k['slug']}.md) [{k['type']}] — {k['description']}")
    write_text_atomic(_index_path(user_id), "\n".join(lines).rstrip() + "\n")


def create_item_file(user_id: str, kind: str, *, item_type: str, title: str, description: str, tags: list[str], body: str) -> str:
    slug = _unique_slug(user_id, kind, title)
    capped_body = enforce_cap(body.strip(), _cap_for(kind), f"{item_type} '{title}'")
    meta = {
        "type": item_type,
        "title": title,
        "description": description or capped_body[:80],
        "tags": tags,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    _write_md_file(_items_dir(user_id, kind) / f"{slug}.md", meta, capped_body)
    _regenerate_index(user_id)
    return slug


def patch_item_file(user_id: str, kind: str, slug: str, body: str) -> bool:
    path = _items_dir(user_id, kind) / f"{slug}.md"
    if not path.exists():
        return False
    meta, _ = parse_frontmatter(read_text(path))
    meta["timestamp"] = datetime.now(timezone.utc).isoformat()
    capped_body = enforce_cap(body.strip(), _cap_for(kind), f"{meta.get('type', kind[:-1])} '{meta.get('title', slug)}'")
    _write_md_file(path, meta, capped_body)
    _regenerate_index(user_id)
    return True


# ── caps: a write over its limit is shortened by the model, else truncated ────

def rewrite_to_fit(text: str, cap: int, label: str) -> str:
    prompt = (
        f"Rewrite the following {label} content to be at most {cap} characters, "
        "keeping only the most useful, current information. Return ONLY the "
        "rewritten text, no preamble, no markdown fences."
    )
    try:
        rewritten = complete_chat(
            settings=get_settings(), system_prompt=prompt, user_prompt=text,
            temperature=0.0, max_tokens=900,
        ).strip()
        if rewritten and len(rewritten) <= cap:
            return rewritten
    except (ProviderError, OSError, KeyError, ValueError) as exc:
        print(f"[memory] rewrite-to-fit error for {label}: {exc!r} — truncating")
    return text[:cap]


def enforce_cap(text: str, cap: int, label: str) -> str:
    return text if len(text) <= cap else rewrite_to_fit(text, cap, label)
