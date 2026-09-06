"""Resolve release-generator checkouts in primary and linked worktrees."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path


def git_common_directory(workspace: Path) -> Path | None:
    try:
        result = subprocess.run(
            (
                "git",
                "-C",
                str(workspace),
                "rev-parse",
                "--path-format=absolute",
                "--git-common-dir",
            ),
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    common = result.stdout.strip()
    return Path(common).resolve() if not result.returncode and common else None


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
