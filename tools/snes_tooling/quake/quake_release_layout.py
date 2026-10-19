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
