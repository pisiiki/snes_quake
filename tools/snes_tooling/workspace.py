"""Resolve paths within a standalone SNES Quake release checkout."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


WORKSPACE_ENVIRONMENT_VARIABLE = "SNES_WORKSPACE"
RELEASE_WORKSPACE_MARKERS = ("third_party/libSFX", "src/snes_quake")


class WorkspaceError(ValueError):
    """Raised when a path is not a standalone SNES Quake release."""


@dataclass(frozen=True)
class Workspace:
    """Validated paths for one standalone release checkout."""

    root: Path

    def __post_init__(self) -> None:
        root = self.root.expanduser().resolve()
        if not all((root / marker).exists() for marker in RELEASE_WORKSPACE_MARKERS):
            rendered = " + ".join(RELEASE_WORKSPACE_MARKERS)
            raise WorkspaceError(
                f"SNES release {root} is missing the required layout: {rendered}"
            )
        object.__setattr__(self, "root", root)

    @classmethod
    def discover(cls, override: Path | str | None = None) -> Workspace:
        """Resolve an explicit, environment, or package-relative release root."""

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
            "cannot discover the standalone SNES release; "
            f"set {WORKSPACE_ENVIRONMENT_VARIABLE} or pass an explicit root"
        )

    @property
    def is_release(self) -> bool:
        return True

    def path(self, *parts: str) -> Path:
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
