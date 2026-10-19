"""Resolve workspace-owned paths without depending on the caller's CWD."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


WORKSPACE_ENVIRONMENT_VARIABLE = "SNES_WORKSPACE"
SOURCE_WORKSPACE_MARKERS = ("pyproject.toml", "src", "tools")
RELEASE_WORKSPACE_MARKERS = ("third_party/libSFX", "src/snes_quake")
WORKSPACE_MARKER_SETS = (SOURCE_WORKSPACE_MARKERS, RELEASE_WORKSPACE_MARKERS)


def git_common_directory(root: Path) -> Path | None:
    """Resolve only the named checkout, never a containing repository."""
    if not (root / ".git").exists():
        return None
    try:
        result = subprocess.run(
            ("git", "-C", str(root), "rev-parse", "--path-format=absolute", "--git-common-dir"),
            capture_output=True, text=True, check=False,
        )
    except OSError:
        return None
    if result.returncode or not result.stdout.strip():
        return None
    return Path(result.stdout.strip()).resolve()


def primary_checkout(root: Path) -> Path:
    """Return the owning primary checkout, or the explicit non-Git root."""
    common = git_common_directory(root)
    return common.parent if common is not None and common.name == ".git" else root




class WorkspaceError(ValueError):
    """Raised when a path is not a supported SNES workspace checkout."""


@dataclass(frozen=True)
class Workspace:
    """Validated paths for one SNES source checkout."""

    root: Path

    def __post_init__(self) -> None:
        root = self.root.expanduser().resolve()
        if not any(
            all((root / marker).exists() for marker in markers)
            for markers in WORKSPACE_MARKER_SETS
        ):
            rendered = " or ".join(
                " + ".join(markers) for markers in WORKSPACE_MARKER_SETS
            )
            raise WorkspaceError(
                f"SNES workspace {root} is missing a supported layout: {rendered}"
            )
        object.__setattr__(self, "root", root)

    @classmethod
    def discover(cls, override: Path | str | None = None) -> Workspace:
        """Resolve an explicit, environment, or editable-source workspace."""

        if override is not None:
            return cls(Path(override))
        configured = os.environ.get(WORKSPACE_ENVIRONMENT_VARIABLE)
        if configured:
            return cls(Path(configured))
        for candidate in Path(__file__).resolve().parents:
            try:
                return cls(candidate)
            except WorkspaceError:
                continue
        raise WorkspaceError(
            "cannot discover the SNES checkout from the installed package; "
            f"set {WORKSPACE_ENVIRONMENT_VARIABLE} or pass an explicit root"
        )

    @classmethod
    def containing(cls, source: Path | str) -> Workspace:
        """Resolve a source file's owning checkout through the same layout contract."""
        path = Path(source).expanduser().resolve()
        for candidate in (path, *path.parents):
            try:
                return cls(candidate)
            except WorkspaceError:
                continue
        raise WorkspaceError(f"cannot locate SNES workspace containing {path}")

    def package_path(self, *parts: str) -> Path:
        """Resolve first-party code and its packaged resources."""
        return self.path("tools", "snes_tooling", *parts)

    @property
    def generated_data(self) -> Path:
        return self.quake_example / "Data"

    @property
    def validation_output(self) -> Path:
        return self.path("tmp", "validation")

    @property
    def reference_renderer(self) -> Path:
        return self.path("src", "reference_renderer")

    @property
    def is_release(self) -> bool:
        """Return whether this is the standalone public-release layout."""

        return all(
            (self.root / marker).exists() for marker in RELEASE_WORKSPACE_MARKERS
        )

    def path(self, *parts: str) -> Path:
        """Return a path rooted in this checkout."""

        return self.root.joinpath(*parts)

    @property
    def shared_tools(self) -> Path:
        return self.path("tools", "commands", "shared")

    @property
    def quake_example(self) -> Path:
        return self.path("src", "snes_quake")

    @property
    def quake_tools(self) -> Path:
        return self.path("tools", "commands", "snes_quake")

    @property
    def state_of_the_art_snes_docs(self) -> Path:
        return self.path("docs", "state-of-the-art-snes")
