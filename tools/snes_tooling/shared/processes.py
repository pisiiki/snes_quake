"""Shared Python command construction and bounded process error contracts."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import os
from pathlib import Path
import subprocess
import sys


class CommandFailure(RuntimeError):
    """A child process failed with its output retained in the exception."""


def python_command(workspace: Path, module: str, *arguments: str) -> list[str]:
    """Run the same package entry point in an installed or standalone checkout."""
    if not module.startswith("snes_tooling."):
        raise ValueError(f"not an owned command module: {module}")
    name = module.removeprefix("snes_tooling.").replace("_", "-")
    return [sys.executable, str(workspace / "tools/snes_tooling_cli.py"), name, *arguments]


def capture_command(
    command: Sequence[str], cwd: Path, *, runner: Callable | None = None,
) -> str:
    """Capture merged diagnostics and raise the same error for every caller."""
    result = (runner or subprocess.run)(
        list(command), cwd=cwd, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, check=False,
    )
    if result.returncode:
        raise CommandFailure(
            f"command failed with exit {result.returncode}: {' '.join(command)}\n"
            f"{result.stdout or ''}"
        )
    return str(result.stdout or "").strip()


def python_child_environment(
    package_root: Path,
    *,
    environment: Mapping[str, str] | None = None,
    path_separator: str | None = None,
) -> dict[str, str]:
    """Prepend one checkout's package root to a preserved child environment."""

    child = dict(os.environ if environment is None else environment)
    separator = os.pathsep if path_separator is None else path_separator
    package_entry = str(package_root.resolve())
    existing = child.get("PYTHONPATH")
    entries = existing.split(separator) if existing else []
    normalized_package = os.path.normcase(os.path.normpath(package_entry))
    retained = [
        entry
        for entry in entries
        if os.path.normcase(os.path.normpath(entry)) != normalized_package
    ]
    child["PYTHONPATH"] = separator.join((package_entry, *retained))
    return child
