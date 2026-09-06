"""Resolve the SNES workspace root from source and release tool layouts."""

from __future__ import annotations

from pathlib import Path
import sys

from quake_release_layout import release_input_path


SOURCE_TOOLING_ROOT = Path("tools/snes_tooling")
RELEASE_TOOLING_ROOT = Path("tools/snes_tooling")
RELEASE_WORKSPACE_MODULE = SOURCE_TOOLING_ROOT / "release_workspace.py"


def workspace_root(source: str | Path) -> Path:
    """Return the nearest parent containing the SNES Quake source tree."""

    resolved = Path(source).resolve()
    for candidate in resolved.parents:
        if (candidate / "src/snes_quake").is_dir() and (
            candidate / "tools"
        ).is_dir():
            return candidate
    raise RuntimeError(f"cannot locate SNES workspace from {resolved}")


def shared_tools_root(source: str | Path) -> Path:
    """Return shared commands in either the source or public-release layout."""

    return workspace_root(source) / "tools/commands/shared"


def release_source_path(path: Path) -> Path:
    """Map a source-checkout path into the stable public-release layout."""

    if path == RELEASE_WORKSPACE_MODULE:
        return RELEASE_TOOLING_ROOT / "workspace.py"
    return release_input_path(path)


# A standalone release imports its shipped package directly. Source workspaces
# keep using their configured environment and editable package.
_root = workspace_root(__file__)
if not (_root / "pyproject.toml").is_file():
    sys.path.insert(0, str(_root / "tools"))
