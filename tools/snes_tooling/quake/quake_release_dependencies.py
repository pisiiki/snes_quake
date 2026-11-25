"""libSFX provenance for standalone source release verification."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import snes_tooling.quake.quake_release_layout as layout


@dataclass(frozen=True, slots=True)
class PinnedRepository:
    role: str
    path: Path
    repository: str
    commit: str


LIBSFX = PinnedRepository(
    "libSFX",
    layout.LIBSFX,
    "https://github.com/Optiroc/libSFX.git",
    "61b3ea97e398333c1b7a6f62a53f1112fdfb6070",
)
