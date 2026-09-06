"""Resolve the pinned repositories required by a standalone Quake release."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from quake_rom_config import BSP_SOURCE_ERICW_MAP, configured_bsp_build
import quake_release_layout as layout


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
CC65_COMMIT = "cc3c40c54e51b2d9a22b63c85c418a2b11763377"
CC65_REPOSITORY = "https://github.com/cc65/cc65.git"
ERICW_TOOLS_PATH = Path("third_party/ericw-tools")
MAP_SOURCE_PATH = Path("third_party/quake-map-source")
VCPKG_PATH = Path("third_party/vcpkg")


def configured_bsp_repositories(config_path: Path) -> tuple[PinnedRepository, ...]:
    """Map the config-owned modern BSP inputs into the release layout."""

    configured = configured_bsp_build(config_path)
    if configured.source != BSP_SOURCE_ERICW_MAP:
        return ()
    values = (
        (
            "EricW BSP tools",
            ERICW_TOOLS_PATH,
            configured.tools_repository,
            configured.tools_commit,
        ),
        (
            "official Quake map source",
            MAP_SOURCE_PATH,
            configured.map_repository,
            configured.map_commit,
        ),
        ("vcpkg", VCPKG_PATH, configured.vcpkg_repository, configured.vcpkg_commit),
    )
    if any(repository is None or commit is None for _, _, repository, commit in values):
        raise ValueError("modern BSP repository configuration is incomplete")
    return tuple(
        PinnedRepository(role, path, str(repository), str(commit))
        for role, path, repository, commit in values
    )


def release_repositories(config_path: Path) -> tuple[PinnedRepository, ...]:
    return (LIBSFX, *configured_bsp_repositories(config_path))
