"""Paths and input relocation for the standalone SNES Quake release."""

from __future__ import annotations

from pathlib import Path


LIBSFX = Path("third_party/libSFX")
SHAREWARE_ROOT = Path("third_party/quake106")
SHAREWARE_ARCHIVE = SHAREWARE_ROOT / "quake106.zip"
CONFIG = Path("config")
PROFILES = CONFIG / "profiles"
MEDIA = Path("docs/media")
BUILD_INFO = Path("docs/BUILD_INFO.json")
RELEASE_NOTES = Path("docs/RELEASE_NOTES.md")
THIRD_PARTY = Path("docs/THIRD_PARTY.md")
REQUIREMENTS = Path("tools/requirements-build.txt")
ROOT_ENTRIES = frozenset({
    ".gitattributes", ".gitignore", ".gitmodules", "LICENSE", "README.md",
    "build.ps1", "build.sh", "config", "docs", "src", "third_party", "tools",
})
# Current metadata profiles are distinct from the retained historical weights.
COMPOSED_CACHE_PROFILE_ROOT = Path("validation/snes_quake/profiles")
COMPOSED_CACHE_OWNER_PROFILE = COMPOSED_CACHE_PROFILE_ROOT / "QuakeBSPComposedCacheOwnerProfileNotranswaterArea512PlayerFlyT792.bin"
COMPOSED_CACHE_PRIORITY_PROFILE = COMPOSED_CACHE_PROFILE_ROOT / "QuakeBSPComposedCachePriorityProfileE1M3FlyT803.json"
COMPOSED_CACHE_PROVENANCE = COMPOSED_CACHE_PROFILE_ROOT / "QuakeBSPComposedCacheE1M3FlyT803Provenance.json"
COMPOSED_CACHE_PROFILE_INPUTS = (
    COMPOSED_CACHE_OWNER_PROFILE, COMPOSED_CACHE_PRIORITY_PROFILE, COMPOSED_CACHE_PROVENANCE,
)

INPUT_RELOCATIONS = (
    (Path("config/snes_quake"), CONFIG),
    (Path("validation/snes_quake/profiles"), PROFILES),
    (Path("patches/vendor/ericw-tools"), Path("third_party/patches")),
)


def release_input_path(path: Path) -> Path:
    """Keep qualified configuration logical paths stable when exporting inputs."""
    for source, destination in INPUT_RELOCATIONS:
        if path.is_relative_to(source):
            return destination / path.relative_to(source)
    return path


def resolve_input(root: Path, path: Path) -> Path:
    """Resolve a logical build input in a source workspace or generated release."""
    if (root / "pyproject.toml").is_file():
        return root / path
    return root / release_input_path(path)


def profile_identity_path(path: Path) -> Path:
    """Keep qualified profile provenance stable when release files move."""
    if path.is_relative_to(PROFILES):
        return Path("validation/snes_quake/profiles") / path.relative_to(PROFILES)
    return path
