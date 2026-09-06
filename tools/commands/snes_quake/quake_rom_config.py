"""Load the authoritative Quake SNES ROM build configuration."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from workspace_paths import workspace_root
from typing import Any

from quake_demo import discover_demo_map


CONFIG_NAME = "rom-config.json"
CONFIG_SCHEMA = "quake-snes-rom-build-v1"
DEFAULT_CONFIG = workspace_root(__file__) / "config" / CONFIG_NAME
DEFAULT_PLAYBACK_SAMPLE_RATE_HZ = 20
PLAYBACK_STEP_SAMPLE_RATE_HZ = 2
TEXTURE_ANIMATION_RATE_HZ = 10
DEFAULT_SOUNDTRACK_SAMPLE_RATE_HZ = 8000
DEFAULT_SOUNDTRACK_VOLUME = 0.7
DEFAULT_ALIAS_HALFBANK_COUNT = 16
MAX_ALIAS_HALFBANK_COUNT = 17
DEFAULT_MDL_WORLD_UNITS_PER_TEXEL = 1
MIN_MDL_WORLD_UNITS_PER_TEXEL = 1.0
MAX_MDL_WORLD_UNITS_PER_TEXEL = 2.0
MESENCE_NIGHTLY_TARGET = "mesence-nightly"
DEFAULT_MESEN_TARGET = MESENCE_NIGHTLY_TARGET
BSP_SOURCE_PAK = "pak"
BSP_SOURCE_ERICW_MAP = "ericw-map"
BSP_SOURCES = frozenset((BSP_SOURCE_PAK, BSP_SOURCE_ERICW_MAP))


@dataclass(frozen=True)
class DemoSource:
    kind: str
    locator: str
    config_path: Path

    @property
    def file_path(self) -> Path | None:
        if self.kind != "file":
            return None
        candidate = Path(self.locator).expanduser()
        if not candidate.is_absolute():
            candidate = self.config_path.parent / candidate
        return candidate.resolve()


@dataclass(frozen=True)
class ResolvedDemo:
    source: DemoSource
    payload: bytes
    map_entry: str
    sha256: str

    @property
    def label(self) -> str:
        path = self.source.file_path
        return path.name if path is not None else self.source.locator

    def metadata(self) -> dict[str, Any]:
        return {
            "source": self.source.kind,
            "locator": self.source.locator,
            "entry": self.label,
            "mapEntry": self.map_entry,
            "bytes": len(self.payload),
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class SoundtrackConfig:
    enabled: bool
    sample_rate_hz: int
    volume: float


@dataclass(frozen=True)
class SkyConfig:
    enabled: bool


@dataclass(frozen=True)
class AliasSpriteConfig:
    halfbank_count: int
    mdl_world_units_per_texel: float


@dataclass(frozen=True)
class MesenTarget:
    name: str
    max_alias_halfbank_count: int
    max_gsu_rom_bank: int


@dataclass(frozen=True)
class BspBuildConfig:
    """Portable, hash-pinned source and tool contract for one configured BSP."""

    source: str
    map_entry: str | None = None
    map_repository: str | None = None
    map_commit: str | None = None
    map_archive: str | None = None
    map_member: str | None = None
    tools_repository: str | None = None
    tools_commit: str | None = None
    tools_patch: str | None = None
    profile: str | None = None
    qbsp_flags: tuple[str, ...] = ()
    vis_flags: tuple[str, ...] = ()
    light_flags: tuple[str, ...] = ()
    map_threads: int = 1
    world_lightmap_samples: int = 512
    inline_model_lightmap_samples: int = 256
    vcpkg_repository: str | None = None
    vcpkg_commit: str | None = None
    vcpkg_packages: tuple[str, ...] = ()
    vcpkg_required_cmake_configs: tuple[str, ...] = ()


MESEN_TARGETS = {
    MESENCE_NIGHTLY_TARGET: MesenTarget(
        MESENCE_NIGHTLY_TARGET,
        MAX_ALIAS_HALFBANK_COUNT,
        0x6F,
    ),
}


def load_rom_config(config_path: Path | None = None) -> dict[str, Any]:
    path = (config_path or DEFAULT_CONFIG).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"ROM build config does not exist: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"ROM build config is invalid JSON: {path}") from error
    if not isinstance(value, dict):
        raise ValueError("ROM build config must contain a JSON object")
    if value.get("schema") != CONFIG_SCHEMA:
        raise ValueError(f"ROM build config schema must be {CONFIG_SCHEMA!r}")
    return value


def configured_demo_source(config_path: Path | None = None) -> DemoSource:
    path = (config_path or DEFAULT_CONFIG).resolve()
    config = load_rom_config(path)
    demo = config.get("demo")
    if not isinstance(demo, dict):
        raise ValueError("ROM build config demo must be an object")
    kind = demo.get("source")
    locator = demo.get("path")
    if kind not in {"file", "pak"}:
        raise ValueError("ROM build demo source must be 'file' or 'pak'")
    if not isinstance(locator, str) or not locator.strip():
        raise ValueError("ROM build demo path must be a non-empty string")
    locator = locator.strip().replace("\\", "/")
    if kind == "pak" and (
        Path(locator).is_absolute()
        or locator.startswith("/")
        or (len(locator) >= 2 and locator[1] == ":")
        or ".." in Path(locator).parts
    ):
        raise ValueError("ROM build PAK demo path must be a safe relative entry")
    source = DemoSource(kind, locator, path)
    file_path = source.file_path
    if file_path is not None and not file_path.is_file():
        raise FileNotFoundError(f"configured loose demo does not exist: {file_path}")
    return source


def configured_playback_sample_rate(config_path: Path | None = None) -> int:
    """Return the shared fixed-rate camera/brush sampling contract."""

    config = load_rom_config(config_path)
    playback = config.get("playback", {})
    if not isinstance(playback, dict):
        raise ValueError("ROM build config playback must be an object")
    rate = playback.get("sampleRateHz", DEFAULT_PLAYBACK_SAMPLE_RATE_HZ)
    if isinstance(rate, bool) or not isinstance(rate, int) or rate <= 0:
        raise ValueError("ROM build playback sampleRateHz must be a positive integer")
    if rate > 0xFFFF:
        raise ValueError("ROM build playback sampleRateHz exceeds uint16 storage")
    if rate % PLAYBACK_STEP_SAMPLE_RATE_HZ:
        raise ValueError(
            "ROM build playback sampleRateHz must be divisible by the 2 Hz "
            "ordered-playback rate"
        )
    if rate % TEXTURE_ANIMATION_RATE_HZ:
        raise ValueError(
            "ROM build playback sampleRateHz must be divisible by the 10 Hz "
            "Quake texture-animation clock"
        )
    return rate


def configured_soundtrack(config_path: Path | None = None) -> SoundtrackConfig:
    """Return the fixed-rate SNES real-time mixer contract."""

    config = load_rom_config(config_path)
    sound = config.get("sound", {})
    if not isinstance(sound, dict):
        raise ValueError("ROM build config sound must be an object")
    enabled = sound.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError("ROM build sound enabled must be a boolean")
    sample_rate = sound.get("sampleRateHz", DEFAULT_SOUNDTRACK_SAMPLE_RATE_HZ)
    if isinstance(sample_rate, bool) or not isinstance(sample_rate, int):
        raise ValueError("ROM build sound sampleRateHz must be an integer")
    if sample_rate != DEFAULT_SOUNDTRACK_SAMPLE_RATE_HZ:
        raise ValueError(
            "ROM build sound sampleRateHz must be 8000 for the real-time mixer"
        )
    volume = sound.get("volume", DEFAULT_SOUNDTRACK_VOLUME)
    if (
        isinstance(volume, bool)
        or not isinstance(volume, (int, float))
        or not math.isfinite(volume)
        or not 0.0 <= volume <= 1.0
    ):
        raise ValueError("ROM build sound volume must be from 0.0 to 1.0")
    return SoundtrackConfig(enabled, sample_rate, float(volume))


def configured_sky(config_path: Path | None = None) -> SkyConfig:
    """Return whether sky-named surfaces use the dedicated sky renderer."""

    config = load_rom_config(config_path)
    sky = config.get("sky", {})
    if not isinstance(sky, dict):
        raise ValueError("ROM build config sky must be an object")
    enabled = sky.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError("ROM build sky enabled must be a boolean")
    return SkyConfig(enabled)


def _required_clean_string(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\n" in value
        or "\r" in value
    ):
        raise ValueError(f"ROM build {field} must be one clean non-empty string")
    return value


def _safe_relative_string(value: object, field: str) -> str:
    rendered = _required_clean_string(value, field).replace("\\", "/")
    path = Path(rendered)
    if (
        path.is_absolute()
        or rendered.startswith("/")
        or (len(rendered) >= 2 and rendered[1] == ":")
        or ".." in path.parts
    ):
        raise ValueError(f"ROM build {field} must be a safe relative path")
    return rendered


def _commit(value: object, field: str) -> str:
    rendered = _required_clean_string(value, field)
    if re.fullmatch(r"[0-9a-f]{40}", rendered) is None:
        raise ValueError(f"ROM build {field} must be a full lowercase Git commit")
    return rendered


def _tokens(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"ROM build {field} must be a non-empty token array")
    return tuple(
        _required_clean_string(token, f"{field}[{index}]")
        for index, token in enumerate(value)
    )


def _require_exact_keys(
    value: dict[object, object], expected: set[str], field: str
) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(str(item) for item in actual - expected)
        details = []
        if missing:
            details.append(f"missing={missing}")
        if unknown:
            details.append(f"unknown={unknown}")
        raise ValueError(f"ROM build {field} fields are invalid; {'; '.join(details)}")


def configured_bsp_build(config_path: Path | None = None) -> BspBuildConfig:
    """Return the deterministic stock-or-modern BSP materialization contract."""

    config = load_rom_config(config_path)
    value = config.get("bspBuild", {"source": BSP_SOURCE_PAK})
    if not isinstance(value, dict):
        raise ValueError("ROM build config bspBuild must be an object")
    source = value.get("source", BSP_SOURCE_PAK)
    if source not in BSP_SOURCES:
        choices = ", ".join(repr(item) for item in sorted(BSP_SOURCES))
        raise ValueError(f"ROM build bspBuild source must be one of: {choices}")
    if source == BSP_SOURCE_PAK:
        if set(value) - {"source"}:
            raise ValueError("ROM build stock bspBuild accepts only source")
        return BspBuildConfig(source=source)

    _require_exact_keys(
        value,
        {"source", "mapEntry", "mapSource", "tools", "limits", "vcpkg"},
        "bspBuild",
    )

    map_source = value.get("mapSource")
    tools = value.get("tools")
    limits = value.get("limits")
    vcpkg = value.get("vcpkg")
    if not all(isinstance(item, dict) for item in (map_source, tools, limits, vcpkg)):
        raise ValueError(
            "ROM build modern bspBuild requires mapSource, tools, limits, and vcpkg objects"
        )
    assert isinstance(map_source, dict)
    assert isinstance(tools, dict)
    assert isinstance(limits, dict)
    assert isinstance(vcpkg, dict)
    _require_exact_keys(
        map_source, {"repository", "commit", "archive", "member"}, "bspBuild mapSource"
    )
    _require_exact_keys(
        tools,
        {
            "repository",
            "commit",
            "patch",
            "profile",
            "qbspFlags",
            "visFlags",
            "lightFlags",
            "mapThreads",
        },
        "bspBuild tools",
    )
    _require_exact_keys(
        limits,
        {"worldLightmapSamples", "inlineModelLightmapSamples"},
        "bspBuild limits",
    )
    _require_exact_keys(
        vcpkg,
        {"repository", "commit", "packages", "requiredCmakeConfigs"},
        "bspBuild vcpkg",
    )
    map_threads = tools.get("mapThreads")
    world_limit = limits.get("worldLightmapSamples")
    inline_limit = limits.get("inlineModelLightmapSamples")
    if map_threads != 1:
        raise ValueError(
            "ROM build bspBuild tools mapThreads must be 1 for determinism"
        )
    if world_limit != 512 or inline_limit != 256:
        raise ValueError(
            "ROM build bspBuild lightmap limits must retain the 512/256 runtime contract"
        )
    packages = _tokens(vcpkg.get("packages"), "bspBuild vcpkg packages")
    if any(re.fullmatch(r"[a-z0-9][a-z0-9-]*", item) is None for item in packages):
        raise ValueError("ROM build bspBuild vcpkg packages contain an invalid name")
    required_configs = vcpkg.get("requiredCmakeConfigs")
    if not isinstance(required_configs, list) or not required_configs:
        raise ValueError(
            "ROM build bspBuild vcpkg requiredCmakeConfigs must be a non-empty array"
        )
    return BspBuildConfig(
        source=source,
        map_entry=_safe_relative_string(value.get("mapEntry"), "bspBuild mapEntry"),
        map_repository=_required_clean_string(
            map_source.get("repository"), "bspBuild mapSource repository"
        ),
        map_commit=_commit(map_source.get("commit"), "bspBuild mapSource commit"),
        map_archive=_safe_relative_string(
            map_source.get("archive"), "bspBuild mapSource archive"
        ),
        map_member=_safe_relative_string(
            map_source.get("member"), "bspBuild mapSource member"
        ),
        tools_repository=_required_clean_string(
            tools.get("repository"), "bspBuild tools repository"
        ),
        tools_commit=_commit(tools.get("commit"), "bspBuild tools commit"),
        tools_patch=_safe_relative_string(tools.get("patch"), "bspBuild tools patch"),
        profile=_required_clean_string(tools.get("profile"), "bspBuild tools profile"),
        qbsp_flags=_tokens(tools.get("qbspFlags"), "bspBuild tools qbspFlags"),
        vis_flags=_tokens(tools.get("visFlags"), "bspBuild tools visFlags"),
        light_flags=_tokens(tools.get("lightFlags"), "bspBuild tools lightFlags"),
        map_threads=map_threads,
        world_lightmap_samples=world_limit,
        inline_model_lightmap_samples=inline_limit,
        vcpkg_repository=_required_clean_string(
            vcpkg.get("repository"), "bspBuild vcpkg repository"
        ),
        vcpkg_commit=_commit(vcpkg.get("commit"), "bspBuild vcpkg commit"),
        vcpkg_packages=packages,
        vcpkg_required_cmake_configs=tuple(
            _safe_relative_string(item, f"bspBuild vcpkg requiredCmakeConfigs[{index}]")
            for index, item in enumerate(required_configs)
        ),
    )


def configured_mesen_target(config_path: Path | None = None) -> MesenTarget:
    """Return the explicit GSU-ROM mapping capability selected by the build."""

    config = load_rom_config(config_path)
    name = config.get("mesenTarget", DEFAULT_MESEN_TARGET)
    if not isinstance(name, str) or name not in MESEN_TARGETS:
        choices = ", ".join(repr(value) for value in MESEN_TARGETS)
        raise ValueError(f"ROM build mesenTarget must be one of: {choices}")
    return MESEN_TARGETS[name]


def configured_alias_sprites(config_path: Path | None = None) -> AliasSpriteConfig:
    """Return the bounded QBA1 capacity and explicit MDL storage density."""

    config = load_rom_config(config_path)
    target = configured_mesen_target(config_path)
    alias = config.get("aliasSprites", {})
    if not isinstance(alias, dict):
        raise ValueError("ROM build config aliasSprites must be an object")
    count = alias.get("halfbankCount", DEFAULT_ALIAS_HALFBANK_COUNT)
    if (
        isinstance(count, bool)
        or not isinstance(count, int)
        or not DEFAULT_ALIAS_HALFBANK_COUNT <= count <= target.max_alias_halfbank_count
    ):
        raise ValueError(
            "ROM build aliasSprites halfbankCount must be an integer from "
            f"{DEFAULT_ALIAS_HALFBANK_COUNT} through "
            f"{target.max_alias_halfbank_count} for mesenTarget {target.name!r}"
        )
    density = alias.get("mdlWorldUnitsPerTexel", DEFAULT_MDL_WORLD_UNITS_PER_TEXEL)
    if isinstance(density, bool) or not isinstance(density, (int, float)):
        raise ValueError(
            "ROM build aliasSprites mdlWorldUnitsPerTexel must be a finite number "
            f"from {MIN_MDL_WORLD_UNITS_PER_TEXEL} through "
            f"{MAX_MDL_WORLD_UNITS_PER_TEXEL}"
        )
    density = float(density)
    if not math.isfinite(density) or not (
        MIN_MDL_WORLD_UNITS_PER_TEXEL <= density <= MAX_MDL_WORLD_UNITS_PER_TEXEL
    ):
        raise ValueError(
            "ROM build aliasSprites mdlWorldUnitsPerTexel must be a finite number "
            f"from {MIN_MDL_WORLD_UNITS_PER_TEXEL} through "
            f"{MAX_MDL_WORLD_UNITS_PER_TEXEL}"
        )
    return AliasSpriteConfig(count, density)


def configured_alias_halfbank_count(config_path: Path | None = None) -> int:
    """Return the bounded physical-halfbank budget for QBA1 sprites."""

    return configured_alias_sprites(config_path).halfbank_count


def configured_alias_mdl_world_units_per_texel(
    config_path: Path | None = None,
) -> float:
    """Return the configured MDL storage-raster density."""

    return configured_alias_sprites(config_path).mdl_world_units_per_texel


def resolve_configured_demo(
    pak_reader: Callable[[str], bytes],
    config_path: Path | None = None,
) -> ResolvedDemo:
    source = configured_demo_source(config_path)
    return resolve_demo_source(source, pak_reader)


def resolve_demo_source(
    source: DemoSource,
    pak_reader: Callable[[str], bytes],
) -> ResolvedDemo:
    """Read one explicit demo source and derive its single BSP entry."""

    file_path = source.file_path
    payload = (
        file_path.read_bytes() if file_path is not None else pak_reader(source.locator)
    )
    if not payload:
        raise ValueError(f"configured demo is empty: {source.locator}")
    return ResolvedDemo(
        source,
        payload,
        discover_demo_map(payload),
        hashlib.sha256(payload).hexdigest(),
    )


def configured_input_paths(config_path: Path | None = None) -> tuple[Path, ...]:
    source = configured_demo_source(config_path)
    file_path = source.file_path
    return (source.config_path, *(() if file_path is None else (file_path,)))
