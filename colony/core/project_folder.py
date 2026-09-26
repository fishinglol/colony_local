"""The folder agents with tools may work in ("project folder"), one per workspace.

It must be chosen for that workspace. Without one, agents remain chat-only. Never the whole disk or the home
folder: one wrong click there would hand every file you own to an AI.
"""
from pathlib import Path


def check_folder(path: Path | str) -> Path:
    """The folder as an absolute path, or ValueError saying why it can't be used."""
    folder = Path(path).expanduser()
    if not folder.is_absolute():
        raise ValueError("Give the full path of the folder, like /Users/you/my-project.")
    folder = folder.resolve()
    if not folder.is_dir():
        raise ValueError(f"{folder} is not a folder that exists.")
    if folder == Path(folder.anchor) or folder == Path.home().resolve():
        raise ValueError("Pick a project folder, not your whole disk or home folder.")
    return folder


def project_folder(chosen: str | None) -> tuple[Path | None, str]:
    """(folder, "workspace" | "none") for a workspace's chosen folder."""
    if chosen:
        try:
            return check_folder(chosen), "workspace"
        except ValueError:
            pass
    return None, "none"
