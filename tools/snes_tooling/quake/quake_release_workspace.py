"""Resolve release-generator checkouts in primary and linked worktrees."""

from __future__ import annotations

from snes_tooling.workspace import git_common_directory as git_common_directory
import tempfile
from collections.abc import Callable
from pathlib import Path


def release_work_root(workspace: Path) -> Path:
    """Keep release work together beside the primary development checkout."""
    common = git_common_directory(workspace)
    primary = common.parent if common is not None and common.name == ".git" else workspace
    return primary.parent / "snes_quake_releases"


def new_qualification_checkout(workspace: Path, mode: str) -> Path:
    """Place fresh clones independently of the input release checkout's location."""
    root = release_work_root(workspace)
    root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=f"quake-{mode}-", dir=root))


def default_git_checkout(
    workspace: Path,
    relative: Path,
    *,
    common_directory_resolver: Callable[[Path], Path | None] = git_common_directory,
) -> Path:
    """Prefer a populated checkout here, then in the linked-worktree primary."""

    local = workspace / relative
    if (local / ".git").exists():
        return local
    common_directory = common_directory_resolver(workspace)
    if common_directory is not None and common_directory.name == ".git":
        primary = common_directory.parent / relative
        if (primary / ".git").exists():
            return primary
    return local
