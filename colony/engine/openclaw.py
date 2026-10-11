"""Colony Local — OpenClaw Gateway Engine Bridge.

Wires Colony UI and workspaces directly into the OpenClaw Gateway
(running locally on port 18789 by default).

Routes chat turns through OpenClaw's /v1/chat/completions endpoint,
leveraging OpenClaw's native multi-agent scheduling, Ollama/Cloud models,
sandboxed tools (bash/read/write), and SQLite episodic memory.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import tempfile
import threading
import time
from datetime import datetime
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ..config import Settings, get_settings
from ..core import attachments
from ..core.activity import add_action, set_activity, set_partial
from ..llm.http import ProviderError

logger = logging.getLogger(__name__)


@dataclass
class OpenClawTurnResult:
    reply: str
    model: str
    actions: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    session_user: str = ""      # the OpenClaw session this turn ran in (see mark_seen)
    thinking: str = ""          # the model's reasoning text, when the Gateway returns it


def resolve_agent_target(agent_id: str | None) -> str:
    """Sanitize agent_id for OpenClaw routing (plain string operations, no regex)."""
    if not agent_id:
        return "main"
    chars = []
    for c in agent_id:
        if c.isalnum() or c in ("-", "_"):
            chars.append(c)
        else:
            chars.append("-")
    cleaned = "".join(chars).strip("-")
    return cleaned or "main"


def build_session_user(
    workspace_id: str,
    agent_id: str | None,
    channel: str | None = None,
    persona: str = "",
) -> str:
    """Stable per-conversation session identifier passed as the OpenAI `user` field. `persona` (a short hash of the agent's
    SOUL/AGENTS text) is part of it, so editing a persona starts a fresh OpenClaw session: bootstrap files are read once per session."""
    ws = "".join(c for c in workspace_id if c.isalnum() or c in ("-", "_")) or "default"
    ch = "".join(c for c in (channel or "main") if c.isalnum() or c in ("-", "_")) or "main"
    ag = "".join(c for c in (agent_id or "anon") if c.isalnum() or c in ("-", "_")) or "anon"
    return f"ome-{ws}-{ch}-{ag}" + (f"-{persona}" if persona else "")

def config_path() -> Path:
    """OpenClaw's config file (the same override OpenClaw itself honours)."""
    return Path(os.environ.get("OPENCLAW_CONFIG_PATH") or Path.home() / ".openclaw" / "openclaw.json")


def read_config() -> dict[str, Any]:
    try:
        return json.loads(config_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        logger.error("Failed to read OpenClaw config: %s", exc)
        return {}


config_lock = threading.RLock()   # hold it around every read-modify-write of the config (agents, plugins, connectors)


def write_config(cfg: dict[str, Any]) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.chmod(0o600)   # connector API keys live in here
    tmp.replace(path)


_known_agents: dict[str, dict] = {}     # agent id -> the config entry we last made sure of


def agent_id_for(workspace_id: str, role_id: str) -> str:
    """One OpenClaw agent per Colony role (role ids repeat across workspaces, so the workspace is part of the id)."""
    return resolve_agent_target(f"{workspace_id}-{role_id}").lower()


def memory_dir(settings: Settings, workspace_id: str) -> Path:
    """The OpenClaw workspace shared by every agent of one Colony workspace. Its MEMORY.md, USER.md and memory/YYYY-MM-DD.md
    are the team's memory: every agent searches them (extraPaths) and writes them, and Colony's Memory window just shows them."""
    return settings.data_dir / "self_improve" / workspace_id


def agent_dir(settings: Settings, agent_id: str) -> Path:
    """The OpenClaw workspace of ONE agent: its own AGENTS.md, SOUL.md, IDENTITY.md, USER.md copy and dreaming output.
    OpenClaw reads persona files only from an agent's workspace, so this is what makes each agent's identity its own."""
    return settings.data_dir / "openclaw-agents" / agent_id


def skills_dir(settings: Settings, agent_id: str) -> Path:
    """The skills only this agent has: one folder per skill, each with a SKILL.md. OpenClaw finds them in the agent's workspace."""
    return agent_dir(settings, agent_id) / "skills"


def _frontmatter(skill_md: Path) -> dict[str, str]:
    """name / description from the `---` block at the top of a SKILL.md (single-line values only)."""
    try:
        lines = skill_md.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    if not lines or lines[0].strip() != "---":
        return {}
    found: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        key, _, value = line.partition(":")
        if key in ("name", "description") and value.strip():
            found[key] = value.strip().strip("\"'")
    return found


def list_skills(settings: Settings, agent_id: str) -> list[dict[str, str]]:
    """The skills this agent has: [{name, description, folder}]. `folder` is the path under the skills folder; a skill
    one group folder down (skills/<group>/<name>/SKILL.md, what a cloned repo looks like) counts too, as it does for OpenClaw."""
    root = skills_dir(settings, agent_id)
    out = []
    for skill_md in sorted(root.glob("SKILL.md")) + sorted(root.glob("*/SKILL.md")) + sorted(root.glob("*/*/SKILL.md")):
        folder = skill_md.parent
        meta = _frontmatter(skill_md)
        out.append({"name": meta.get("name", folder.name), "description": meta.get("description", ""),
                    "folder": folder.relative_to(root).as_posix()})
    return out


def add_skills(settings: Settings, agent_id: str, source: Path) -> list[str]:
    """Copy the skill in `source` (a folder with SKILL.md) or every skill folder inside it to this agent. Returns the folder names added."""
    found = [source] if (source / "SKILL.md").is_file() else [f for f in sorted(source.iterdir()) if (f / "SKILL.md").is_file()]
    root = skills_dir(settings, agent_id)
    for folder in found:
        shutil.copytree(folder, root / folder.name, dirs_exist_ok=True)
    return [f.name for f in found]


def github_clone_url(url: str) -> str:
    """https://github.com/<owner>/<repo>[.git | /tree/...] -> the https clone URL. Only github.com over https is accepted."""
    parsed = urlparse(url.strip())
    parts = [p for p in parsed.path.split("/") if p]
    if parsed.scheme != "https" or parsed.netloc not in ("github.com", "www.github.com") or len(parts) < 2:
        raise ValueError("Paste a GitHub repository link, like https://github.com/owner/repo")
    return f"https://github.com/{parts[0]}/{parts[1].removesuffix('.git')}.git"


def add_skills_from_github(settings: Settings, agent_id: str, url: str) -> list[str]:
    """Clone a public GitHub repository (shallow, into a temporary folder) and copy every skill in it (a folder with a
    SKILL.md) straight into this agent's skills folder. Returns the folder names added."""
    clone_url = github_clone_url(url)
    with tempfile.TemporaryDirectory(prefix="colony-skills-") as tmp:
        target = Path(tmp) / "repo"
        try:
            done = subprocess.run(["git", "clone", "--depth", "1", "--quiet", clone_url, str(target)], capture_output=True, text=True,
                                  timeout=120, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError("Could not download that repository (is git installed, and is the link right?).") from exc
        if done.returncode != 0:
            raise ValueError("Could not download that repository: it may be private or the link is wrong.")
        found = [p.parent for p in sorted(target.rglob("SKILL.md")) if ".git" not in p.parts and len(p.relative_to(target).parts) <= 4]
        root = skills_dir(settings, agent_id)
        added = []
        for folder in found:
            name = folder.name if folder != target else target.name and clone_url.rsplit("/", 1)[-1].removesuffix(".git")
            shutil.copytree(folder, root / name, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".git"))
            added.append(name)
        return added


def remove_skill(settings: Settings, agent_id: str, folder: str) -> bool:
    """Take one skill away from this agent. `folder` is a folder path from list_skills (nothing outside the skills folder is touched)."""
    root = skills_dir(settings, agent_id).resolve()
    target = (root / folder).resolve()
    if target == root or root not in target.parents or not (target / "SKILL.md").is_file():
        return False
    shutil.rmtree(target)
    return True


def agents_md(memory: Path, writable: bool = True) -> str:
    """AGENTS.md of an agent: how the team's shared memory works. OpenClaw reads it into the session's first turn.
    `writable` is False when the agent is fenced to a project folder: the memory files are outside it, so Colony keeps what
    the user asks to be remembered and the agent only searches them."""
    if writable:
        keeping = f"""The folder {memory} is the team's shared memory: plain files every teammate reads and writes, with the read, write and edit tools,
always allowed for these files. Use absolute paths, and write there (not in this workspace).
- MEMORY.md: lasting facts and decisions.  USER.md: what you know about the user (preferences, background).  memory/YYYY-MM-DD.md: daily notes.
- USER.md in your own workspace is only a copy of the shared one, made before each turn.

## Keeping things
For every user message decide whether it holds a lasting fact worth keeping (name, preference, pet, decision, project detail).
If it does, your first action is a tool call: edit {memory}/USER.md for facts about the user, {memory}/MEMORY.md for anything else
(read the file first, keep existing lines, add one short line). After the tool result, confirm briefly.
Never say you saved something unless that tool call succeeded."""
    else:
        keeping = f"""The folder {memory} is the team's shared memory (MEMORY.md, USER.md, memory/YYYY-MM-DD.md). You are fenced to the project
folder, so you cannot edit those files. When the user asks you to remember something, Colony writes it there for you:
just confirm briefly. Do not try to write those files yourself."""
    return f"""# Team memory (managed by Colony)
{keeping}

## Recalling things
Call memory_search (it covers the shared memory and your own notes). It matches words, not meaning, and not across languages: search
again with the key words in the user's language AND in English (and a synonym) before you say nothing was found.
"""


def soul_md(name: str, instructions: str) -> str:
    """SOUL.md of one agent: who it is (set in Colony's agent editor)."""
    return f"# {name}\n{instructions.strip() or 'Help the user complete their request.'}\n"


def identity_md(name: str) -> str:
    return f"# Identity\n- **Name:** {name}\n"


def _write_if_changed(path: Path, text: str) -> None:
    if not path.exists() or path.read_text(encoding="utf-8") != text:
        path.write_text(text, encoding="utf-8")


def _seed_memory_dir(path: Path) -> None:
    """The team's shared memory folder: MEMORY.md, USER.md, memory/ for daily notes."""
    (path / "memory").mkdir(parents=True, exist_ok=True)
    for name, text in (("MEMORY.md", "# Memory\n"), ("USER.md", "# User\n")):
        if not (path / name).exists():
            (path / name).write_text(text, encoding="utf-8")


def write_agent_files(settings: Settings, workspace_id: str, agent_id: str, name: str, instructions: str,
                      memory_writable: bool = True) -> str:
    """Write one agent's persona files into its own workspace and copy the shared USER.md in (OpenClaw injects USER.md from the
    agent's workspace). Returns a short hash of the persona files: the session tag (they are read once per session)."""
    shared, mine = memory_dir(settings, workspace_id), agent_dir(settings, agent_id)
    _seed_memory_dir(shared)
    (mine / "memory").mkdir(parents=True, exist_ok=True)       # OpenClaw's dreaming writes its own notes here
    rules, soul, identity = agents_md(shared, memory_writable), soul_md(name, instructions), identity_md(name)
    _write_if_changed(mine / "AGENTS.md", rules)
    _write_if_changed(mine / "SOUL.md", soul)
    _write_if_changed(mine / "IDENTITY.md", identity)
    _write_if_changed(mine / "USER.md", (shared / "USER.md").read_text(encoding="utf-8"))
    if not (mine / "MEMORY.md").exists():
        (mine / "MEMORY.md").write_text("# Memory\n", encoding="utf-8")      # long-term notes OpenClaw's dreaming promotes for this agent
    return hashlib.sha1((rules + soul + identity).encode("utf-8")).hexdigest()[:8]


MAX_IMAGES = 8      # the Gateway's limit of image_url parts per request
REMEMBER_WORDS = ("จำไว้", "จำด้วย", "remember")     # an explicit "keep this" request, in Thai or English


def snapshot_memory(settings: Settings, workspace_id: str) -> str:
    """Everything in MEMORY.md and USER.md right now, to see whether a turn changed them."""
    folder = memory_dir(settings, workspace_id)
    _seed_memory_dir(folder)      # so creating the starter files is never mistaken for a change
    return "".join((folder / name).read_text(encoding="utf-8") if (folder / name).exists() else "" for name in ("MEMORY.md", "USER.md"))


def keep_if_asked(settings: Settings, workspace_id: str, user_text: str, before: str) -> bool:
    """The model decides what to write into the memory files and does not always (measured: it saved about half of the explicit
    "remember this" requests and still said "saved"). So when the user explicitly asked and nothing changed, Colony adds their own
    words to USER.md. True when it did."""
    if not any(word in user_text.lower() for word in REMEMBER_WORDS) or snapshot_memory(settings, workspace_id) != before:
        return False
    notes = memory_dir(settings, workspace_id) / "USER.md"
    with notes.open("a", encoding="utf-8") as f:
        f.write(f"- {user_text.strip()[:400]}\n")
    return True


def _tool_allowlist(tools: Any, web_search: bool, connectors: list[str], fenced: bool = False, skills: bool = False) -> list[str]:
    """OpenClaw tool names for what the Colony role switched on. A connector's tools are named <server>__<tool>.
    Without a project folder (`fenced` False) every agent gets read/write/edit: its only files are the shared memory files, so
    it can keep them. Fenced to a project folder, it gets exactly the file tools the role has. memory_search/memory_get always."""
    allowed = ["web_search"] if web_search else []
    allowed += [f"{name}__*" for name in connectors] + ["memory_search", "memory_get"]
    if not fenced or getattr(tools, "read", "off") != "off":
        allowed.append("read")
    if not fenced or getattr(tools, "write", "off") != "off":
        allowed += ["write", "edit"]
    if getattr(tools, "bash", "off") != "off":
        allowed.append("exec")
    if skills:
        allowed.append("skills_read")   # opens one of the agent's own skills; not the project's files
    return allowed


GATE_PLUGIN = Path(__file__).with_name("colony-gate")      # a plugin folder: manifest + index.ts


def _register_gate(cfg: dict[str, Any], approval_seconds: float) -> bool:
    """Make OpenClaw load the colony-gate plugin (asks Colony before every tool call). True if the config changed.

    The hook's default time limit is 15 s and it fails closed, which would block every action the user is still deciding on,
    so its limit is raised a little above Colony's own approval timeout.
    """
    plugins = cfg.setdefault("plugins", {})
    load = plugins.setdefault("load", {})
    paths = [p for p in load.get("paths", []) if "colony-gate" not in p] + [str(GATE_PLUGIN)]
    entry = {"enabled": True, "hooks": {"timeouts": {"before_tool_call": int((approval_seconds + 10) * 1000)}}}
    entries = plugins.setdefault("entries", {})
    changed = load.get("paths") != paths or entries.get("colony-gate") != entry
    load["paths"], entries["colony-gate"] = paths, entry
    return changed


def _enable_memory_search(cfg: dict[str, Any]) -> bool:
    """Turn on OpenClaw's memory_search over the agents' memory files, keyword-only (provider "none"): no embedding key needed.
    True if the config changed."""
    want = {"enabled": True, "provider": "none"}
    search = cfg.setdefault("memory", {}).setdefault("search", {})
    if all(search.get(k) == v for k, v in want.items()):
        return False
    search.update(want)
    return True


def _set_system_agent(cfg: dict[str, Any]) -> bool:
    """With several explicit agents OpenClaw's background jobs (memory dreaming, heartbeats) need an owner; `main` always exists."""
    defaults = cfg.setdefault("agents", {}).setdefault("defaults", {})
    if defaults.get("systemAgent", {}).get("agentId"):
        return False
    defaults["systemAgent"] = {"agentId": "main"}
    return True


def _quiet_background(cfg: dict[str, Any]) -> bool:
    """Colony agents act only when the user asks. Switch off what OpenClaw would otherwise run on its own and bill to the model:
    the skill workshop (writes skills by itself, reviews every agent weekly) and the 30-minute heartbeat that starts once a
    system agent is set. Dreaming stays on. True if the config changed."""
    defaults = cfg.setdefault("agents", {}).setdefault("defaults", {})
    heartbeat = defaults.setdefault("heartbeat", {})
    workshop = cfg.setdefault("skills", {}).setdefault("workshop", {}).setdefault("autonomous", {})
    if workshop.get("mode") == "off" and heartbeat.get("every") == "0m":
        return False
    workshop["mode"], heartbeat["every"] = "off", "0m"
    return True


def ensure_agent(settings: Settings, agent_id: str, name: str, tools: Any = None, web_search: bool = False,
                 connectors: list[str] | None = None, folder: str | None = None, memory: Path | None = None,
                 thinking: str = "default", wait_seconds: float = 150.0) -> None:
    """Make sure OpenClaw has this agent, set up lean: add/update it in OpenClaw's config (hot reload) and wait until listed.

    Lean on purpose: OpenClaw's default prompt is ~46k tokens (every tool schema + skills + bootstrap files); with only the
    role's tools and no skills it is ~5k (an agent's own skills, added in Colony, are the only ones it gets) (measured 2026-10-09). The persona travels in the system prompt; the workspace files
    (our tiny AGENTS.md, MEMORY.md, USER.md) are injected only on a session's first turn (contextInjection "continuation-skip").
    The agent's workspace is its own folder (persona files; never the user's project folder, because OpenClaw writes its own files
    into an agent workspace); the Colony workspace's shared memory folder is added to its memory search. The model is chosen per turn (x-openclaw-model), not stored here.
    """
    allow = _tool_allowlist(tools, web_search, connectors or [], fenced=bool(folder), skills=bool(list_skills(settings, agent_id)))
    with config_lock:
        cfg = read_config()
        agents = cfg.setdefault("agents", {})
        entries = agents.setdefault("entries", {})
        existing = entries.get(agent_id)
        workspace = str(agent_dir(settings, agent_id))
        want = {"name": name, "workspace": workspace, "tools": {"profile": "minimal", "alsoAllow": allow},
                "contextInjection": "continuation-skip",
                "skills": [skill["name"] for skill in list_skills(settings, agent_id)]}     # only this agent's own skills
        if thinking != "default":   # the role's reasoning level; "default" leaves the model's own setting
            want["thinkingDefault"] = thinking
        if memory:      # the team's shared memory is searched from every agent's own workspace
            want["memory"] = {"search": {"extraPaths": [str(memory)]}}
        if folder:
            want["cwd"] = folder    # relative paths in file tools and commands start in the project folder
        gate_added = _register_gate(cfg, settings.approval_timeout_seconds) | _enable_memory_search(cfg) | _set_system_agent(cfg) | _enable_responses(cfg) | _quiet_background(cfg)
        if existing != want or gate_added:
            Path(workspace).mkdir(parents=True, exist_ok=True)
            if memory:
                _seed_memory_dir(memory)
            entries.setdefault("main", {})   # keep the existing default agent once there is more than one
            entries[agent_id] = want
            agents["ownership"] = "explicit"  # OpenClaw refuses a multi-agent roster without this
            write_config(cfg)
            _known_agents.pop(agent_id, None)
            if existing is not None or gate_added:
                time.sleep(5)   # ponytail: OpenClaw gives no "reloaded" signal for an edit (~3 s seen); a fixed wait on a rare change
        if _known_agents.get(agent_id) == want:
            return
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(settings.openclaw_gateway_url.rstrip("/") + "/v1/models", timeout=2) as resp:
                    ids = [m.get("id") for m in json.loads(resp.read().decode("utf-8")).get("data", [])]
            except (OSError, ValueError):
                ids = []
            if f"openclaw/{agent_id}" in ids:
                _known_agents[agent_id] = want
                return
            time.sleep(0.5)
    raise ProviderError(f"OpenClaw did not pick up agent {agent_id} (config change not applied; see ~/.colony/openclaw.log)")


# What each OpenClaw session has already been told. OpenClaw keeps its own history per session, so after the first turn we
# send only the messages it has not seen (other agents' replies, the user's messages to other agents), not the whole chat.
def _seen_file(settings: Settings) -> Path:
    return settings.data_dir / "openclaw_seen.json"


def _read_seen(settings: Settings) -> dict[str, str]:
    try:
        return json.loads(_seen_file(settings).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def unseen(settings: Settings, session_user: str, history: list[dict], ids: list[str]) -> list[dict]:
    """The part of `history` (ids = its Colony message ids, same order) after the last message this session answered.
    No marker, or the marked message is gone (compaction, new session): the whole recent history, once."""
    marker = _read_seen(settings).get(session_user)
    if marker in ids:
        return history[ids.index(marker) + 1:]
    return history


def mark_seen(settings: Settings, session_user: str, message_id: str) -> None:
    """Record that this session has now seen the conversation up to `message_id` (the reply it just gave)."""
    seen = _read_seen(settings)
    seen[session_user] = message_id
    _seen_file(settings).write_text(json.dumps(seen), encoding="utf-8")


def _usage_file(settings: Settings) -> Path:
    return settings.data_dir / "openclaw_usage.json"


def _record_usage(settings: Settings, agent_id: str, model: str, prompt_tokens: int) -> None:
    """The prompt size OpenClaw reported for this agent's last turn: the real size of its session, for the context gauge."""
    try:
        usage = json.loads(_usage_file(settings).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        usage = {}
    usage[agent_id] = {"prompt_tokens": prompt_tokens, "model": model}
    _usage_file(settings).write_text(json.dumps(usage), encoding="utf-8")


def last_prompt_tokens(settings: Settings, agent_id: str) -> int | None:
    """Prompt tokens of this agent's last turn, or None when it has not answered yet (or its model has changed since)."""
    try:
        return json.loads(_usage_file(settings).read_text(encoding="utf-8")).get(agent_id, {}).get("prompt_tokens")
    except (OSError, ValueError):
        return None


def remove_agents(settings: Settings, workspace_id: str) -> None:
    """Forget a deleted workspace: its OpenClaw agents (config entries + their state folders), its sessions' markers, its memory folder."""
    prefix = resolve_agent_target(workspace_id).lower() + "-"
    with config_lock:
        cfg = read_config()
        entries = cfg.get("agents", {}).get("entries", {})
        gone = [a for a in entries if a.startswith(prefix)]
        for agent_id in gone:
            del entries[agent_id]
            _known_agents.pop(agent_id, None)
            shutil.rmtree(config_path().parent / "agents" / agent_id, ignore_errors=True)
            shutil.rmtree(agent_dir(settings, agent_id), ignore_errors=True)
        if gone:
            write_config(cfg)
    for path, key in ((_seen_file(settings), "ome-" + workspace_id + "-"), (_usage_file(settings), prefix)):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        path.write_text(json.dumps({k: v for k, v in data.items() if not k.startswith(key)}), encoding="utf-8")
    root = (settings.data_dir / "self_improve").resolve()
    folder = memory_dir(settings, workspace_id).resolve()
    if root in folder.parents:      # never delete outside the memory folder
        shutil.rmtree(folder, ignore_errors=True)


GATEWAY_LOG = Path.home() / ".colony" / "openclaw.log"      # where `colony` sends the Gateway's output (cli.py)
_PREPARING = ("startup preparation still running", "remains degraded", "Sessions remain unavailable")


def gateway_prepared(settings: Settings, log: Path | None = None, now: float | None = None) -> bool:
    """Is the Gateway done preparing its agents' databases? /readyz turns 200 well before that (about a minute after start; the
    preparation takes a few minutes), and until then every run fails with HTTP 500 and a config change can send the Gateway into a
    restart. It repeats a "still running"/"degraded" line about once a minute while it works, so: no such line in the last 75 s."""
    try:
        lines = (log or GATEWAY_LOG).read_text(encoding="utf-8", errors="replace").splitlines()[-400:]
    except OSError:
        return True         # a Gateway not started by Colony: nothing to look at
    now = time.time() if now is None else now
    for line in reversed(lines):
        if any(mark in line for mark in _PREPARING):
            try:
                return now - datetime.fromisoformat(line[:29]).timestamp() > 75
            except ValueError:
                return False
    return True


def wait_prepared(settings: Settings, timeout: float = 480.0) -> bool:
    """Wait (up to `timeout` seconds) until gateway_prepared(); False if it never was."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if gateway_prepared(settings):
            return True
        time.sleep(5)
    return False


def _gateway_restarted(settings: Settings, wait: float = 200.0) -> bool:
    """After a failed call: did the Gateway restart itself? (OpenClaw does after a config reload it cannot apply live, e.g. while a
    new agent's database is still being prepared.) If it went down, wait for it to come back and say True; if it stayed up, False."""
    for _ in range(10):
        if not is_openclaw_available(settings):
            break
        time.sleep(1)
    else:
        return False
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if is_openclaw_available(settings):
            return True
        time.sleep(3)
    return False


def _read_stream(resp: Any, on_text: Any) -> dict:
    """Read a chat-completions event stream; `on_text(text so far)` runs on every chunk. Returns what the non-streaming call would."""
    text, reasoning, usage, model, calls = "", "", {}, None, {}
    for raw in resp:
        line = raw.decode("utf-8", errors="replace").strip()
        if not line.startswith("data:") or line.endswith("[DONE]"):
            continue
        chunk = json.loads(line[5:])
        model = chunk.get("model") or model
        usage = chunk.get("usage") or usage
        delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
        reasoning += delta.get("reasoning_content") or ""
        for tc in delta.get("tool_calls") or []:       # arrives in pieces: name once, arguments in fragments
            fn = tc.get("function") or {}
            call = calls.setdefault(tc.get("index", 0), {"function": {"name": "", "arguments": ""}})["function"]
            call["name"] += fn.get("name") or ""
            call["arguments"] += fn.get("arguments") or ""
        if delta.get("content"):
            text += delta["content"]
            on_text(text)
    return {"model": model, "usage": usage,
            "choices": [{"message": {"content": text, "reasoning_content": reasoning, "tool_calls": list(calls.values())}}]}


def _gateway_post(settings: Settings, payload: dict, model: str | None, timeout: float, path: str = "/v1/chat/completions",
                  _retry: bool = True, on_text: Any = None) -> dict:
    """POST a chat completion to the Gateway. `model` (ollama/…) is the real model the agent should use for this call.
    With `on_text`, the reply is streamed and `on_text(text so far)` is called as it grows; the result has the same shape.
    If the Gateway restarted under the call, it is sent once more when the Gateway is back."""
    if on_text:
        payload = {**payload, "stream": True, "stream_options": {"include_usage": True}}
    gateway_url = settings.openclaw_gateway_url.rstrip("/")
    headers = {"Content-Type": "application/json"}
    if settings.openclaw_gateway_token:
        headers["Authorization"] = f"Bearer {settings.openclaw_gateway_token}"
    if model and (model.startswith("ollama/") or model.startswith("openclaw/")):
        headers["x-openclaw-model"] = model
    req = urllib.request.Request(gateway_url + path, data=json.dumps(payload).encode("utf-8"),
                                 headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return _read_stream(resp, on_text) if on_text else json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        err_msg = exc.read().decode("utf-8", errors="replace")
        logger.error("OpenClaw Gateway HTTP %s: %s", exc.code, err_msg)
        unprepared = "remain unavailable" in err_msg or "preparation" in err_msg      # the Gateway is still preparing its agents
        if _retry and exc.code == 403 and "authority changed" in err_msg:     # the Gateway was applying a config change mid-request
            time.sleep(6)
            return _gateway_post(settings, payload, model, timeout, path, _retry=False, on_text=on_text)
        if _retry and exc.code >= 500 and ((unprepared and wait_prepared(settings)) or _gateway_restarted(settings)):
            return _gateway_post(settings, payload, model, timeout, path, _retry=False, on_text=on_text)
        raise ProviderError(f"OpenClaw Gateway request failed ({exc.code}): {err_msg[:200]}",
                            status=exc.code, provider_message=err_msg) from exc
    except OSError as exc:
        logger.error("OpenClaw Gateway connection error: %s", exc)
        if _retry and _gateway_restarted(settings):
            return _gateway_post(settings, payload, model, timeout, path, _retry=False, on_text=on_text)
        raise ProviderError(f"OpenClaw Gateway unreachable at {gateway_url} ({exc})", status=None) from exc


def _enable_responses(cfg: dict[str, Any]) -> bool:
    """Turn on the Gateway's /v1/responses endpoint, which (unlike chat/completions) takes PDFs. True if the config changed."""
    want = {"enabled": True, "files": {"pdf": {"maxPages": 10}}}
    endpoints = cfg.setdefault("gateway", {}).setdefault("http", {}).setdefault("endpoints", {})
    if endpoints.get("responses") == want:
        return False
    endpoints["responses"] = want
    return True


def _data_source(url: str, name: str | None = None) -> dict:
    """{"type": "base64", ...} for a data: URI (what /v1/responses takes for images and files)."""
    head, _, data = url.partition(",")
    source = {"type": "base64", "media_type": head[len("data:"):].split(";")[0], "data": data}
    if name:
        source["filename"] = name
    return source


def _as_responses(payload: dict, pdfs: list[dict]) -> dict:
    """The same turn as an OpenResponses request: system prompt -> instructions, the new message carries the PDFs too."""
    items, instructions = [], ""
    for m in payload["messages"]:
        if m["role"] == "system":
            instructions += m["content"] + "\n\n"
            continue
        content = m["content"]
        if isinstance(content, list):
            content = [{"type": "input_text", "text": c["text"]} if c["type"] == "text"
                       else {"type": "input_image", "source": _data_source(c["image_url"]["url"])} for c in content]
        items.append({"type": "message", "role": m["role"], "content": content})
    new = items[-1]
    if isinstance(new["content"], str):
        new["content"] = [{"type": "input_text", "text": new["content"]}]
    new["content"] += [{"type": "input_file", "source": _data_source(p["file"]["file_data"], p["file"]["filename"])} for p in pdfs]
    return {"model": payload["model"], "user": payload["user"], "stream": False, "instructions": instructions.strip(), "input": items}


def ping_model(settings: Settings, model: str) -> tuple[str, float]:
    """One tiny message to `model` through a lean OpenClaw agent: (start of the reply, seconds). For "Test this model"."""
    wait_prepared(settings)
    ensure_agent(settings, "colony-ping", "Model test")
    started = time.monotonic()
    data = _gateway_post(settings, {"model": "openclaw/colony-ping", "stream": False, "user": "ome-ping",
                                    "messages": [{"role": "user", "content": "Reply with the single word OK."}]}, model, 60.0)
    choices = data.get("choices") or []
    if not choices:
        raise ProviderError("OpenClaw Gateway returned no completion choices")
    return ((choices[0].get("message") or {}).get("content") or "").strip()[:60], time.monotonic() - started


def is_openclaw_available(settings: Settings | None = None) -> bool:
    """Quick probe: True only when the Gateway says it is ready (/readyz = 200; it answers 503 while still warming up)."""
    s = settings or get_settings()
    if not s.openclaw_gateway_enabled:
        return False
    try:
        with urllib.request.urlopen(s.openclaw_gateway_url.rstrip("/") + "/readyz", timeout=0.8):
            return True
    except Exception:  # refused, timeout, or HTTP 503 (not ready yet)
        return False


def get_openclaw_status(settings: Settings | None = None) -> dict[str, Any]:
    """Detailed health status of OpenClaw Gateway."""
    s = settings or get_settings()
    available = is_openclaw_available(s)
    return {
        "enabled": s.openclaw_gateway_enabled,
        "available": available,
        "url": s.openclaw_gateway_url,
        "has_token": bool(s.openclaw_gateway_token),
    }


def capability_text(settings: Settings, agent_id: str, role_name: str, tools: Any, web_search: bool,
                    connectors: list[str], folder: str | None) -> str:
    """What this turn tells the agent about itself: who it is and which tools it has (the system part of a turn)."""
    cap_lines = []
    if web_search:
        cap_lines.append("- Web search: ENABLED (tool `web_search`). You have no live data: for prices, news, weather or anything recent, "
                         "call it first and never answer from memory.")
    else:
        cap_lines.append("- Web search: DISABLED (rely on what you know and on workspace files)")
    if tools:
        r = getattr(tools, "read", "off")
        w = getattr(tools, "write", "off")
        b = getattr(tools, "bash", "off")
        cap_lines.append(f"- Project files, read: {'ALLOWED (tool: read)' if r != 'off' else 'DISABLED'}")
        cap_lines.append(f"- Project files, write/edit: {'ALLOWED (tools: write, edit)' if w != 'off' else 'DISABLED'}")
        cap_lines.append(f"- Run commands: {'ALLOWED (tool: exec)' if b != 'off' else 'DISABLED'}")
    if connectors:
        cap_lines.append(f"- Connected apps (MCP servers): {', '.join(connectors)}. Their tools are named <server>__<tool>.")
        apps = getattr(tools, "mcp_apps", None)
        if apps and "composio" in connectors:
            cap_lines.append(f"  * Through Composio use only these apps: {', '.join(apps)}. If the user asks for another app, say it is not connected to you and stop.")
    if folder:
        cap_lines.append(f"- Workspace Project Folder: {folder}")
    skills = list_skills(settings, agent_id)
    if skills:
        cap_lines.append("- Your skills (open one with tool `skills_read`, always allowed). When a request matches a skill, call "
                         "`skills_read` with its name first and follow it:\n" + "\n".join(
                             f"  * {k['name']}: {k['description'][:160]}" for k in skills))
    cap_lines.append(f"- Your skills folder: {skills_dir(settings, agent_id)}. To add a skill the user points you to (a folder with SKILL.md), "
                     "read its files and write each to <skills folder>/<skill name>/<same relative path>; the user is asked to approve each file. "
                     "If it is a GitHub link and you may run commands, `git clone --depth 1` it into a temporary folder, "
                     "then `cp -r` only the folders that contain a SKILL.md, each straight into your skills folder "
                     "(<skills folder>/<skill name>/SKILL.md), never the whole repository. "
                     "The skill works from the user's next message.")

    return f"You are {role_name} (your persona is in SOUL.md).\n" + "\n".join(cap_lines)


def run_openclaw_turn(
    *,
    settings: Settings,
    role_id: str,
    role_name: str,
    role_model: str,
    role_instructions: str,
    workspace_id: str,
    channel: str | None,
    user_message: str,
    history: list[dict] | None = None,
    history_ids: list[str] | None = None,
    system_prompt: str | None = None,
    tools: Any = None,
    web_search: bool = False,
    connectors: list[str] | None = None,
    media: list[dict] | None = None,
    folder: str | None = None,
    reasoning: str = "default",
    timeout: float = 600.0,
) -> OpenClawTurnResult:
    """Execute one turn through OpenClaw Gateway.
    
    Streams status to ActivityTracker so live commands show up on Colony UI.
    """
    # Each Colony role is its own OpenClaw agent; each agent's persona lives in its own workspace's SOUL.md, the memory rules in its AGENTS.md.
    agent_id = agent_id_for(workspace_id, role_id)
    connectors = connectors if getattr(tools, "mcp", "off") != "off" else []
    memory = memory_dir(settings, workspace_id)
    if not gateway_prepared(settings):
        set_activity(workspace_id, step="preparing", agent_name=role_name, model=role_model,
                     detail="OpenClaw is still preparing its agents (after a start this takes a few minutes)…")
        wait_prepared(settings)
    ensure_agent(settings, agent_id, role_name, tools=tools, web_search=web_search, connectors=connectors,
                 folder=str(folder) if folder else None, memory=memory, thinking=reasoning)
    model = f"openclaw/{agent_id}"
    persona = write_agent_files(settings, workspace_id, agent_id, role_name, role_instructions, memory_writable=not folder)
    session_user = build_session_user(workspace_id, role_id, channel, persona)

    # Assemble messages
    messages: list[dict[str, Any]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    else:
        messages.append({"role": "system", "content": capability_text(settings, agent_id, role_name, tools, web_search, connectors, folder)})

    # Agent replies in the history already carry their "[Name]" label; roles are kept as they are.
    new_to_session = unseen(settings, session_user, history or [], history_ids or [])
    for entry in new_to_session[-10:]:
        if entry.get("content"):
            messages.append({"role": entry["role"], "content": entry["content"]})

    # Images ride along as data-URI image_url parts on the new message (the endpoint takes up to 8; other media never gets here).
    media = media or []
    parts = [p for p in (attachments.part(settings, workspace_id, ref) for ref in [r for r in media if r["kind"] == "image"][:MAX_IMAGES]) if p]
    pdfs = [p for p in (attachments.part(settings, workspace_id, ref) for ref in media if ref["kind"] == "pdf") if p]
    messages.append({"role": "user", "content": [{"type": "text", "text": user_message}, *parts] if parts else user_message})

    payload = {
        "model": model,
        "messages": messages,
        "user": session_user,
        "stream": False,
    }

    set_activity(
        workspace_id=workspace_id,
        step="running",
        detail=f"OpenClaw Gateway executing turn ({role_name})...",
        agent_name=role_name,
        model=role_model,
    )

    if pdfs:        # chat/completions has no PDF part; the OpenResponses endpoint does and OpenClaw extracts the text itself
        data = _gateway_post(settings, _as_responses(payload, pdfs), role_model, timeout, path="/v1/responses")
        texts = [c.get("text", "") for item in data.get("output") or [] if item.get("type") == "message" for c in item.get("content") or []]
        msg = {"content": "".join(texts)}
        usage = {"prompt_tokens": (data.get("usage") or {}).get("input_tokens")}
    else:
        data = _gateway_post(settings, payload, role_model, timeout,
                             on_text=lambda text: set_partial(workspace_id, role_id, role_name, text))
        choices = data.get("choices") or []
        if not choices:
            raise ProviderError("OpenClaw Gateway returned no completion choices")
        msg = choices[0].get("message") or {}
        usage = data.get("usage") or {}
    reply_text = (msg.get("content") or "").strip()
    actual_model = data.get("model") or role_model
    prompt_tokens = usage.get("prompt_tokens")
    if isinstance(prompt_tokens, int):
        _record_usage(settings, agent_id, role_model, prompt_tokens)

    actions: list[str] = []
    # Check for tool_calls in message
    tool_calls = msg.get("tool_calls") or []
    for tc in tool_calls:
        fn = tc.get("function") or {}
        name = fn.get("name") or "tool"
        raw_args = fn.get("arguments") or ""
        desc = f"{name} {raw_args}".strip()
        actions.append(desc[:80])
        set_activity(workspace_id, step="tool", detail=f"Executing tool {name}", command=desc[:80], agent_name=role_name)
        add_action(workspace_id, desc[:80])

    # Check for custom action headers or notes
    notes = data.get("actions") or []
    if isinstance(notes, list):
        for n in notes:
            if isinstance(n, str) and n not in actions:
                actions.append(n)

    thinking = msg.get("reasoning_content") or msg.get("reasoning") or ""
    return OpenClawTurnResult(
        thinking=thinking if isinstance(thinking, str) else "",
        reply=reply_text,
        model=actual_model,
        actions=actions,
        session_user=session_user,
    )
