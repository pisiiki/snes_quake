#!/usr/bin/env python3
"""Generate and build the public SNES Quake release from Quake shareware."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from workspace_paths import workspace_root
from typing import Any, Callable, Iterator, Mapping, Sequence

from snes_tooling.shared.snes_example_build import require_cc65_tool

import quake_mesen_mapping
import quake_release_dependencies as release_dependencies
import quake_release_layout as layout
from quake_rom_config import BSP_SOURCE_ERICW_MAP, configured_bsp_build


RELEASE_ROOT = workspace_root(__file__)
RELEASE_EXAMPLE_PATH = Path("src/snes_quake")
RELEASE_CONFIG_PATH = layout.CONFIG / "rom-config.json"
RELEASE_TOOLS_PATH = Path("tools/commands/snes_quake")
RELEASE_PROFILES_PATH = layout.PROFILES
RELEASE_OUTPUT_PATH = Path("out/snes_quake")
SHAREWARE_ARCHIVE = layout.SHAREWARE_ARCHIVE
RESOURCE_MEMBER = "resource.1"
GENERATED_ASSET_MANIFEST = RELEASE_EXAMPLE_PATH / "generated-assets.json"
QUALIFIED_ASSET_NAMES = (
    "QuakeBSPAliasVisibility.i",
    "QuakeBSPAliasVisibility.json",
    "QuakeBSPAliasVisibility.s",
    "QuakeBSPAliasVisibilityDisabled.bin",
    "QuakeBSPAliasVisibilityEnabled.bin",
    "QuakeBSPReferenceSoundReplay.bin",
)
PYTHON_BYTECODE_SUFFIXES = frozenset({".pyc", ".pyo"})
PYTHON_MIN_VERSION = (3, 11)
PYTHON_MAX_VERSION = (3, 15)
NUMPY_VERSION = "2.3.5"
PILLOW_VERSION = "12.0.0"
PF_AVX2_INSTRUCTIONS_AVAILABLE = 40
ASSET_MODE_REGENERATED = "regenerated-avx2"
ASSET_MODE_QUALIFIED = "verified-qualified-assets"


@dataclass(frozen=True)
class FileIdentity:
    size: int
    sha256: str

    def verify(self, path: Path, label: str) -> None:
        actual_size = path.stat().st_size
        actual_sha256 = sha256_file(path)
        if actual_size != self.size or actual_sha256 != self.sha256:
            raise RuntimeError(
                f"{label} is not the canonical Quake shareware file: "
                f"{actual_size} bytes/{actual_sha256}, expected "
                f"{self.size} bytes/{self.sha256}"
            )


ARCHIVE_IDENTITY = FileIdentity(
    9_094_045,
    "ec6c9d34b1ae0252ac0066045b6611a7919c2a0d78a3a66d9387a8f597553239",
)
RESOURCE_IDENTITY = FileIdentity(
    9_086_574,
    "c192c9c71bee41750dd7d14c99378766d61e077977b9d13d1a457b8d9eabe34a",
)
LHA_MEMBERS: Mapping[str, FileIdentity] = {
    "ID1/PAK0.PAK": FileIdentity(
        18_689_235,
        "35a9c55e5e5a284a159ad2a62e0e8def23d829561fe2f54eb402dbc0a9a946af",
    ),
    "SLICNSE.TXT": FileIdentity(
        10_036,
        "070cdf6a6410adef8fb5f83a4e5ccdb9e2301d2e48d460bb3a67a0f5ba9d70a8",
    ),
    "README.TXT": FileIdentity(
        19_087,
        "9ade267c7e22a1c4c4aa8fa3dd58ad3354c173ae2cfc39344093cea534316d61",
    ),
}
ROM_IDENTITY = FileIdentity(
    4_194_304,
    "e29ac927c09491be760844dcdfe4ca06cc48ce9f3cc5ffbbddc55d12d935971e",
)
SYMBOL_IDENTITY = FileIdentity(
    161_245,
    "25a991b81bfc8677724f2d80c0def1b1470304f6c6e7e59845b66cdbd9c9a15f",
)
RELEASE_MANIFEST = RELEASE_OUTPUT_PATH / "build/release-manifest.json"
RELEASE_VIDEO_BYTES = 9_449_440
RELEASE_VIDEO_SHA256 = "c7c6b994a1e9ef009cca4d4a9a7abfe32171d0b406e079b14c86382712a24590"
REQUIRED_COVERAGE_ROLES = (
    "fly",
    "ordered2",
    "ordered20",
    "realtime",
    "referenceLaunch",
    "referenceSample101",
    "referenceSample951",
    "releaseVideo",
    "runtimeMenu",
    "scenarioWorldFly",
    "scenarios",
)
DEFAULT_FEATURE_VALUES: Mapping[str, object] = {
    "technique": 4,
    "textures": True,
    "lightmap": True,
    "turbulentLiquids": True,
    "dynamicBrushes": True,
    "mdlBillboards": True,
    "noFramebufferClear": True,
}
LIBSFX_COMMIT = release_dependencies.LIBSFX.commit
LIBSFX_ORIGIN = release_dependencies.LIBSFX.repository
LIBSFX_PATH = release_dependencies.LIBSFX.path
CC65_COMMIT = release_dependencies.CC65_COMMIT
CC65_ORIGIN = release_dependencies.CC65_REPOSITORY
TAR_TIMEOUT_SECONDS = 120
TAR_PROBE_TIMEOUT_SECONDS = 10


CommandRunner = Callable[..., subprocess.CompletedProcess[Any]]


def host_supports_avx2(cpuinfo: Path = Path("/proc/cpuinfo")) -> bool:
    """Return whether this process can safely launch the pinned AVX2 tools."""

    if sys.platform == "win32":
        try:
            return bool(
                ctypes.windll.kernel32.IsProcessorFeaturePresent(  # type: ignore[attr-defined]
                    PF_AVX2_INSTRUCTIONS_AVAILABLE
                )
            )
        except (AttributeError, OSError):
            return False
    if sys.platform.startswith("linux"):
        try:
            lines = cpuinfo.read_text(encoding="ascii", errors="ignore").splitlines()
        except OSError:
            return False
        return any(
            key.strip() in {"flags", "Features"} and "avx2" in value.split()
            for line in lines
            for key, separator, value in (line.partition(":"),)
            if separator
        )
    return False


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


@contextmanager
def atomic_path(destination: Path) -> Iterator[Path]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        yield temporary
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def _is_libarchive_bsdtar(executable: str) -> bool:
    try:
        result = subprocess.run(
            [executable, "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            text=True,
            timeout=TAR_PROBE_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    banner = str(result.stdout or "").casefold()
    return result.returncode == 0 and ("bsdtar" in banner or "libarchive" in banner)


def find_bsdtar() -> str:
    candidates = ("tar.exe", "bsdtar.exe") if os.name == "nt" else ("bsdtar", "tar")
    for candidate in candidates:
        executable = shutil.which(candidate)
        if executable is not None and _is_libarchive_bsdtar(executable):
            return executable
    raise FileNotFoundError(
        "libarchive bsdtar was not found; install a libarchive bsdtar package "
        "or pass its executable with --tar"
    )


def find_git() -> str:
    candidates = ("git.exe", "git") if os.name == "nt" else ("git",)
    for candidate in candidates:
        executable = shutil.which(candidate)
        if executable is not None:
            return executable
    raise FileNotFoundError("git is required to verify release submodules")


class SharewareResource:
    """A verified DeICE/LHA resource opened without executing its installer."""

    def __init__(
        self,
        path: Path,
        *,
        tar_executable: str,
        member_identities: Mapping[str, FileIdentity],
        runner: CommandRunner,
    ) -> None:
        self.path = path
        self.tar_executable = tar_executable
        self.member_identities = member_identities
        self.runner = runner

    def extract_member(self, member: str, destination: Path) -> Path:
        identity = self.member_identities.get(member)
        if identity is None:
            raise ValueError(f"unsupported shareware member: {member}")
        destination = Path(destination)
        with atomic_path(destination) as temporary:
            with temporary.open("wb") as output:
                try:
                    result = self.runner(
                        [self.tar_executable, "-xOf", str(self.path), member],
                        stdout=output,
                        stderr=subprocess.PIPE,
                        check=False,
                        timeout=TAR_TIMEOUT_SECONDS,
                    )
                except subprocess.TimeoutExpired as error:
                    raise RuntimeError(
                        f"archive extractor timed out extracting {member} after "
                        f"{TAR_TIMEOUT_SECONDS} seconds"
                    ) from error
            if result.returncode:
                detail = (
                    bytes(result.stderr or b"")
                    .decode("utf-8", errors="replace")
                    .strip()
                )
                raise RuntimeError(
                    f"archive extractor could not extract {member} from resource.1"
                    + (f": {detail}" if detail else "")
                )
            identity.verify(temporary, member)
        return destination


class SharewareArchive:
    """Reader for the exact, complete Quake 1.06 shareware distribution."""

    def __init__(
        self,
        path: Path,
        *,
        tar_executable: str | None = None,
        archive_identity: FileIdentity = ARCHIVE_IDENTITY,
        resource_identity: FileIdentity = RESOURCE_IDENTITY,
        member_identities: Mapping[str, FileIdentity] = LHA_MEMBERS,
        runner: CommandRunner | None = None,
    ) -> None:
        self.path = Path(path)
        self.tar_executable = tar_executable
        self.archive_identity = archive_identity
        self.resource_identity = resource_identity
        self.member_identities = member_identities
        self.runner = runner or subprocess.run

    def verify(self) -> dict[str, object]:
        if not self.path.is_file():
            raise FileNotFoundError(f"Quake shareware archive not found: {self.path}")
        self.archive_identity.verify(self.path, "quake106.zip")
        return {
            "path": str(self.path.resolve()),
            "bytes": self.archive_identity.size,
            "sha256": self.archive_identity.sha256,
        }

    @contextmanager
    def open_resource(self) -> Iterator[SharewareResource]:
        self.verify()
        with tempfile.TemporaryDirectory(prefix="quake-shareware-") as temporary_dir:
            resource_path = Path(temporary_dir) / RESOURCE_MEMBER
            with zipfile.ZipFile(self.path) as archive:
                matches = [
                    item
                    for item in archive.infolist()
                    if item.filename == RESOURCE_MEMBER
                ]
                if len(matches) != 1:
                    raise RuntimeError(
                        f"quake106.zip must contain exactly one {RESOURCE_MEMBER}"
                    )
                if matches[0].file_size != self.resource_identity.size:
                    raise RuntimeError(
                        f"{RESOURCE_MEMBER} has unexpected ZIP size "
                        f"{matches[0].file_size}"
                    )
                with (
                    archive.open(matches[0]) as source,
                    resource_path.open("wb") as output,
                ):
                    shutil.copyfileobj(source, output, length=1024 * 1024)
            self.resource_identity.verify(resource_path, RESOURCE_MEMBER)
            yield SharewareResource(
                resource_path,
                tar_executable=self.tar_executable or find_bsdtar(),
                member_identities=self.member_identities,
                runner=self.runner,
            )


def extract_shareware_notices(
    archive: Path | SharewareArchive,
    destination: Path,
    *,
    tar_executable: str | None = None,
) -> tuple[Path, Path]:
    source = (
        archive
        if isinstance(archive, SharewareArchive)
        else SharewareArchive(archive, tar_executable=tar_executable)
    )
    destination = Path(destination)
    with source.open_resource() as resource:
        license_path = resource.extract_member(
            "SLICNSE.TXT", destination / "SLICNSE.TXT"
        )
        readme_path = resource.extract_member("README.TXT", destination / "README.TXT")
    return license_path, readme_path


def normalize_git_origin(value: str) -> str:
    normalized = value.strip().replace("\\", "/").rstrip("/")
    if normalized.lower().endswith(".git"):
        normalized = normalized[:-4]
    return normalized.lower()


def capture_command(
    command: Sequence[str], cwd: Path, *, runner: CommandRunner | None = None
) -> str:
    result = (runner or subprocess.run)(
        list(command),
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(
            f"command failed with exit {result.returncode}: {' '.join(command)}\n"
            f"{result.stdout or ''}"
        )
    return str(result.stdout or "").strip()


def verify_git_checkout(
    path: Path,
    *,
    name: str,
    commit: str,
    expected_origin: str,
    runner: CommandRunner | None = None,
) -> dict[str, str]:
    path = path.resolve()
    if not path.is_dir() or not (path / ".git").exists():
        raise FileNotFoundError(f"{name} submodule is not initialized: {path}")
    git = find_git()
    head = capture_command([git, "rev-parse", "HEAD"], path, runner=runner).lower()
    origin = capture_command([git, "remote", "get-url", "origin"], path, runner=runner)
    status = capture_command(
        [git, "status", "--porcelain", "--untracked-files=all"],
        path,
        runner=runner,
    )
    if head != commit:
        raise RuntimeError(f"{name} is at {head}, expected pinned {commit}")
    if normalize_git_origin(origin) != normalize_git_origin(expected_origin):
        raise RuntimeError(f"{name} origin is {origin!r}, expected {expected_origin}")
    if status:
        raise RuntimeError(f"{name} submodule has local changes")
    return {"commit": head, "origin": origin}


def verify_libsfx_submodule(
    libsfx: Path, *, runner: CommandRunner | None = None
) -> dict[str, str]:
    return verify_git_checkout(
        libsfx,
        name="libSFX",
        commit=LIBSFX_COMMIT,
        expected_origin=LIBSFX_ORIGIN,
        runner=runner,
    )


def verify_cc65_submodule(
    cc65: Path, *, runner: CommandRunner | None = None
) -> dict[str, str]:
    return verify_git_checkout(
        cc65,
        name="cc65",
        commit=CC65_COMMIT,
        expected_origin=CC65_ORIGIN,
        runner=runner,
    )


def verify_python_build_environment() -> dict[str, object]:
    version = tuple(sys.version_info[:3])
    if sys.implementation.name != "cpython" or not (
        PYTHON_MIN_VERSION <= version[:2] < PYTHON_MAX_VERSION
    ):
        raise RuntimeError(
            "SNES Quake requires CPython 3.11-3.14; "
            f"selected interpreter is {version[0]}.{version[1]}.{version[2]}"
        )
    try:
        numpy = importlib.import_module("numpy")
    except (ImportError, OSError) as error:
        raise RuntimeError(
            "NumPy is missing or unusable; install the hash-locked "
            "requirements-build.txt with the selected interpreter"
        ) from error
    actual_numpy = getattr(numpy, "__version__", None)
    if actual_numpy != NUMPY_VERSION:
        raise RuntimeError(
            f"SNES Quake requires NumPy {NUMPY_VERSION}; found {actual_numpy!r}"
        )
    try:
        pillow = importlib.import_module("PIL")
    except (ImportError, OSError) as error:
        raise RuntimeError(
            "Pillow is missing or unusable; install the hash-locked "
            "requirements-build.txt with the selected interpreter"
        ) from error
    actual_pillow = getattr(pillow, "__version__", None)
    if actual_pillow != PILLOW_VERSION:
        raise RuntimeError(
            f"SNES Quake requires Pillow {PILLOW_VERSION}; found {actual_pillow!r}"
        )
    return {
        "implementation": sys.implementation.name,
        "version": ".".join(str(value) for value in version),
        "numpy": actual_numpy,
        "pillow": actual_pillow,
    }


def verify_release_inputs(
    release_root: Path,
    shareware_path: Path,
    *,
    runner: CommandRunner | None = None,
) -> dict[str, object]:
    release_root = release_root.resolve()
    if not release_root.is_dir():
        raise FileNotFoundError(f"release root not found: {release_root}")
    config = release_root / RELEASE_CONFIG_PATH
    repositories = release_dependencies.configured_bsp_repositories(config)
    libsfx = release_root / LIBSFX_PATH
    shareware = SharewareArchive(shareware_path).verify()
    return {
        "schema": "quake-bsp-public-preflight-v4",
        "releaseRoot": str(release_root),
        "python": verify_python_build_environment(),
        "shareware": shareware,
        "libSFX": verify_libsfx_submodule(libsfx, runner=runner),
        "cc65": verify_cc65_submodule(libsfx / "tools/cc65", runner=runner),
        "bspRepositories": {
            repository.path.as_posix(): verify_git_checkout(
                release_root / repository.path,
                name=repository.role,
                commit=repository.commit,
                expected_origin=repository.repository,
                runner=runner,
            )
            for repository in repositories
        },
    }


def run_checked(command: Sequence[str], cwd: Path) -> dict[str, Any]:
    started = time.monotonic()
    output = capture_command(command, cwd)
    return {
        "command": Path(command[1] if len(command) > 1 else command[0]).name,
        "elapsedSeconds": round(time.monotonic() - started, 3),
        "output": output,
    }


def generator_commands(
    release_root: Path, pak: Path, data: Path, *, check: bool
) -> tuple[tuple[str, list[str]], ...]:
    tools = release_root / RELEASE_TOOLS_PATH
    profiles = release_root / RELEASE_PROFILES_PATH
    config = release_root / RELEASE_CONFIG_PATH
    pak_output = [
        "--pak",
        str(pak),
        "--config",
        str(config),
        "--output",
        str(data),
    ]
    data_output = ["--data-dir", str(data), "--output", str(data)]
    checked = ["--check"] if check else []
    metadata = data / "QuakeBSPMetadata.json"
    packet_oracle = data / "QuakeBSPPacketOracle.json"
    return (
        (
            "world",
            [
                sys.executable,
                str(tools / "generate_quake_bsp.py"),
                *pak_output,
                *checked,
            ],
        ),
        (
            "packet-oracle",
            [
                sys.executable,
                str(tools / "quake_bsp_packet_oracle.py"),
                "--data-dir",
                str(data),
                "--check" if check else "--write",
                str(packet_oracle),
            ],
        ),
        (
            "ordered-replay",
            [
                sys.executable,
                str(tools / "generate_quake_bsp_ordered_replay.py"),
                *data_output,
                "--include-full-rate",
                *checked,
            ],
        ),
        (
            "brush",
            [
                sys.executable,
                str(tools / "generate_quake_brush_replay.py"),
                *pak_output,
                *checked,
            ],
        ),
        (
            "alias-billboards",
            [
                sys.executable,
                str(tools / "generate_quake_alias_billboards.py"),
                *pak_output,
                *checked,
            ],
        ),
        (
            "soundtrack",
            [
                sys.executable,
                str(tools / "generate_quake_snes_soundtrack.py"),
                *pak_output,
                *checked,
            ],
        ),
        (
            "monster",
            [
                sys.executable,
                str(tools / "generate_quake_monster_cameras.py"),
                "--pak",
                str(pak),
                "--metadata",
                str(metadata),
                "--output",
                str(data),
                *checked,
            ],
        ),
        (
            "composed-cache",
            [
                sys.executable,
                str(tools / "generate_quake_bsp_composed_cache.py"),
                *data_output,
                "--profile-dir",
                str(profiles),
                *checked,
            ],
        ),
        (
            "sky",
            [
                sys.executable,
                str(tools / "generate_quake_bsp_sky_assets.py"),
                *data_output,
                "--endpoint-corpus",
                str(profiles / "QuakeBSPSkyEndpointCorpus.json"),
                *checked,
            ],
        ),
        (
            "turbulence",
            [
                sys.executable,
                str(tools / "generate_quake_bsp_turbulence_assets.py"),
                *data_output,
                *checked,
            ],
        ),
    )


def materialize_configured_pak(
    release_root: Path, stock_pak: Path, temporary_root: Path
) -> tuple[Path, dict[str, Any] | None]:
    """Retain the configured level archive for assets and the reference tool."""

    tools = release_root / RELEASE_TOOLS_PATH
    output_root = release_root / RELEASE_OUTPUT_PATH
    config = release_root / RELEASE_CONFIG_PATH
    configured = configured_bsp_build(config)
    if configured.source != BSP_SOURCE_ERICW_MAP:
        return stock_pak, None
    output = output_root / "build/modern-bsp/PAK0.PAK"
    receipt = output_root / "build/modern-bsp-receipt.json"
    command = [
        sys.executable,
        str(tools / "build_quake_modern_bsp.py"),
        "--pak",
        str(stock_pak),
        "--config",
        str(config),
        "--map-source-root",
        str(release_root / release_dependencies.MAP_SOURCE_PATH),
        "--ericw-source",
        str(release_root / release_dependencies.ERICW_TOOLS_PATH),
        "--vcpkg",
        str(release_root / release_dependencies.VCPKG_PATH),
        "--provision-vcpkg",
        "--build-root",
        str(output_root / "build/modern-bsp-tools"),
        "--output-pak",
        str(output),
        "--receipt",
        str(receipt),
    ]
    step = run_checked(command, release_root)
    if not output.is_file() or not receipt.is_file():
        raise RuntimeError("modern BSP materialization omitted its PAK or receipt")
    document = json.loads(receipt.read_text(encoding="utf-8"))
    pak_identity = document.get("outputs", {}).get("pak", {})
    if (
        document.get("schema") != "quake-modern-bsp-build-v1"
        or pak_identity.get("bytes") != output.stat().st_size
        or pak_identity.get("sha256") != sha256_file(output)
    ):
        raise RuntimeError("modern BSP materialization receipt is stale")
    step["name"] = "modern-bsp"
    step["receipt"] = {
        "path": str(receipt.relative_to(release_root)).replace("\\", "/"),
        "sha256": sha256_file(receipt),
    }
    return output, step


DNFO_FIELD = re.compile(r'(?:^|,)([A-Za-z][A-Za-z0-9_]*)=(?:"((?:\\.|[^"])*)"|([^,]*))')


def dnfo_dependencies(debug_info: Path, example_dir: Path) -> set[Path]:
    dependencies: set[Path] = set()
    for line in debug_info.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("file\t"):
            continue
        fields: dict[str, str] = {}
        for match in DNFO_FIELD.finditer(line.split("\t", 1)[1]):
            quoted, plain = match.group(2), match.group(3)
            fields[match.group(1)] = (
                quoted.replace(r"\"", '"').replace(r"\\", "\\")
                if quoted is not None
                else plain.strip()
            )
        if "name" not in fields:
            raise RuntimeError(f"malformed file record in {debug_info}")
        dependency = Path(fields["name"])
        if not dependency.is_absolute():
            dependency = example_dir / dependency
        dependencies.add(dependency.resolve())
    if not dependencies:
        raise RuntimeError(f"no assembler dependencies found in {debug_info}")
    return dependencies


def verify_dependency_closure(debug_info: Path, release_root: Path) -> int:
    release_root = release_root.resolve()
    dependencies = dnfo_dependencies(debug_info, debug_info.parent)
    outside = sorted(
        str(path) for path in dependencies if not path.is_relative_to(release_root)
    )
    if outside:
        raise RuntimeError(
            "ROM build used dependencies outside the release root:\n"
            + "\n".join(outside)
        )
    return len(dependencies)


def load_generated_asset_contract(release_root: Path) -> dict[str, Any]:
    path = release_root / GENERATED_ASSET_MANIFEST
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"cannot read generated-asset contract: {path}") from error
    if not isinstance(document, dict):
        raise RuntimeError("generated-asset contract must contain a JSON object")
    files = document.get("files")
    summary = document.get("summary")
    if (
        document.get("schema") != "quake-bsp-public-generated-assets-v1"
        or not isinstance(files, list)
        or not isinstance(summary, dict)
        or summary.get("count") != len(files)
        or type(summary.get("bytes")) is not int
    ):
        raise RuntimeError("generated-asset contract has an invalid schema or summary")
    seen: set[str] = set()
    byte_count = 0
    for index, entry in enumerate(files):
        if not isinstance(entry, dict):
            raise RuntimeError(f"generated-asset files[{index}] must be an object")
        name = entry.get("path")
        size = entry.get("bytes")
        digest = entry.get("sha256")
        if (
            not isinstance(name, str)
            or not name
            or Path(name).name != name
            or name in seen
            or type(size) is not int
            or size < 0
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        ):
            raise RuntimeError(f"generated-asset files[{index}] is invalid")
        seen.add(name)
        byte_count += size
    if byte_count != summary["bytes"]:
        raise RuntimeError("generated-asset contract byte summary is invalid")
    asset_set = hashlib.sha256()
    for entry in files:
        asset_set.update(
            entry["path"].encode("ascii")
            + b"\0"
            + str(entry["bytes"]).encode("ascii")
            + b"\0"
            + entry["sha256"].encode("ascii")
            + b"\n"
        )
    if document.get("assetSetSha256") != asset_set.hexdigest():
        raise RuntimeError("generated-asset set digest is invalid")
    qualified = document.get("qualifiedInputs")
    if not isinstance(qualified, list) or tuple(qualified) != QUALIFIED_ASSET_NAMES:
        raise RuntimeError("generated-asset qualified-input set is invalid")
    config = document.get("configuration")
    config_path = release_root / RELEASE_CONFIG_PATH
    if (
        not isinstance(config, dict)
        or config.get("path") != RELEASE_CONFIG_PATH.as_posix()
        or type(config.get("bytes")) is not int
        or not isinstance(config.get("sha256"), str)
    ):
        raise RuntimeError("generated-asset configuration binding is invalid")
    FileIdentity(config["bytes"], config["sha256"]).verify(
        config_path, "rom-config.json"
    )
    try:
        quake_mesen_mapping.validate_contract(document.get("mesenMapping"), config_path)
    except ValueError as error:
        raise RuntimeError("generated-asset MesenCE mapping is invalid") from error
    return document


def prepare_generated_data(release_root: Path, data: Path) -> None:
    """Reset Data to the small, source-qualified inputs shipped in the release."""
    contract = load_generated_asset_contract(release_root)
    entries = {entry["path"]: entry for entry in contract["files"]}
    data.mkdir(parents=True, exist_ok=True)
    for name in QUALIFIED_ASSET_NAMES:
        if name not in entries:
            raise RuntimeError(f"qualified generated input is undeclared: {name}")
        path = data / name
        entry = entries[name]
        FileIdentity(entry["bytes"], entry["sha256"]).verify(path, name)
    for path in data.iterdir():
        if path.is_dir():
            raise RuntimeError(
                f"generated Data contains an unexpected directory: {path}"
            )
        if path.name not in QUALIFIED_ASSET_NAMES:
            path.unlink()


def validate_packet_contract(
    release_root: Path, data: Path, contract: Mapping[str, Any]
) -> dict[str, Any]:
    try:
        oracle = json.loads((data / "QuakeBSPPacketOracle.json").read_text("utf-8"))
        packet = contract["packetContract"]
        faces = oracle["contract"]["streams"]["faces"]
        capacities = oracle["contract"]["capacities"]
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
    ) as error:
        raise RuntimeError("packet-oracle contract is missing or unreadable") from error
    expected_faces = {
        "format": "<HBBB",
        "recordBytes": 5,
        "storage": "canonical contiguous bytes",
    }
    expected_capacities = {
        "facePlanes": 405,
        "faces": 405,
        "indices": 2048,
        "vertices": 768,
    }
    if (
        oracle.get("schema") != 3
        or faces != expected_faces
        or capacities != expected_capacities
        or packet
        != {
            "oracleSchema": 3,
            "faces": expected_faces,
            "capacities": expected_capacities,
            "firstIndexAccess": "adjacent bytewise little-endian",
        }
    ):
        raise RuntimeError("release requires the schema-3 contiguous five-byte packet")
    source = (
        release_root / RELEASE_EXAMPLE_PATH / "quake/PacketEmissionAndTextureSetup.sgs"
    ).read_text(encoding="utf-8")
    required_source = (
        "StorePacketFaceFirstIndex:",
        "moveb   (R10), R5",
        "with    R5\n        hib",
        "LoadPacketFaceFirstIndex:",
        "moveb   R0, (R10)",
        "add     #BSP_FACE_RECORD_BYTES",
    )
    if any(fragment not in source for fragment in required_source):
        raise RuntimeError("packaged source lacks bytewise five-byte face access")
    return {
        "oracleSchema": 3,
        "faces": expected_faces,
        "capacities": expected_capacities,
        "firstIndexAccess": "adjacent bytewise little-endian",
    }


def validate_generated_assets(release_root: Path, data: Path) -> dict[str, Any]:
    release_root = release_root.resolve()
    data = data.resolve()
    contract = load_generated_asset_contract(release_root)
    entries = {entry["path"]: entry for entry in contract["files"]}
    expected = {(data / name).resolve() for name in entries}
    actual = {path.resolve() for path in data.rglob("*") if path.is_file()}
    missing = sorted(str(path.relative_to(release_root)) for path in expected - actual)
    extra = sorted(str(path.relative_to(release_root)) for path in actual - expected)
    if missing or extra:
        details = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if extra:
            details.append("extra: " + ", ".join(extra))
        raise RuntimeError(
            "generated Data set differs from the build contract; " + "; ".join(details)
        )
    mismatched = []
    for name, entry in entries.items():
        path = data / name
        if path.is_file() and (
            path.stat().st_size != entry["bytes"]
            or sha256_file(path) != entry["sha256"]
        ):
            mismatched.append(name)
    if mismatched:
        raise RuntimeError(
            "generated Data identities differ from the build contract: "
            + ", ".join(sorted(mismatched))
        )
    actual_summary: dict[str, Any] = {
        "count": len(actual),
        "bytes": sum(path.stat().st_size for path in actual),
    }
    if actual_summary != contract["summary"]:
        raise RuntimeError(
            "generated Data totals differ from the build contract: "
            f"{actual_summary}, expected {contract['summary']}"
        )
    try:
        quake_mesen_mapping.validate_alias_metadata(
            contract["mesenMapping"],
            release_root / RELEASE_CONFIG_PATH,
            data / "QuakeBSPAliasAssets.json",
        )
    except (KeyError, ValueError) as error:
        raise RuntimeError("generated alias MesenCE mapping is stale") from error
    actual_summary["packetContract"] = validate_packet_contract(
        release_root, data, contract
    )
    return actual_summary


def validate_release_qualification_contract(
    release_root: Path, contract: Mapping[str, Any]
) -> dict[str, Any]:
    source_revision = contract.get("sourceRevision")
    coverage = contract.get("defaultFeatureCoverage")
    if (
        not isinstance(source_revision, str)
        or re.fullmatch(r"[0-9a-f]{40}", source_revision) is None
        or not isinstance(coverage, dict)
        or coverage.get("schema") != "quake-default-feature-release-binding-v2"
        or coverage.get("status") != "pass"
        or tuple(coverage.get("evidenceRoles", ())) != REQUIRED_COVERAGE_ROLES
    ):
        raise RuntimeError("release qualification binding is missing or stale")
    features = coverage.get("defaultFeatures")
    if not isinstance(features, dict):
        raise RuntimeError("default-feature release gate is missing")
    for name, value in DEFAULT_FEATURE_VALUES.items():
        feature = features.get(name)
        if (
            not isinstance(feature, dict)
            or feature.get("enabled") is not True
            or feature.get("value") != value
            or feature.get("oracle") != "renderer-native-reference"
        ):
            raise RuntimeError(f"default-feature release gate is stale: {name}")
    evidence = coverage.get("evidence")
    if (
        not isinstance(evidence, dict)
        or evidence.get("schema") != "quake-default-feature-semantic-evidence-v1"
        or not isinstance(evidence.get("sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", evidence["sha256"]) is None
    ):
        raise RuntimeError("default-feature evidence binding is invalid")
    declaration = coverage.get("declaration")
    if (
        not isinstance(declaration, dict)
        or type(declaration.get("bytes")) is not int
        or declaration["bytes"] <= 0
        or not isinstance(declaration.get("sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", declaration["sha256"]) is None
    ):
        raise RuntimeError("default-feature declaration binding is invalid")
    video = coverage.get("releaseVideo")
    video_identity = video.get("video") if isinstance(video, dict) else None
    observed = video.get("observedFeatureState") if isinstance(video, dict) else None
    if (
        not isinstance(video, dict)
        or video.get("romSha256") != ROM_IDENTITY.sha256
        or video.get("sequenceComplete") is not True
        or type(video.get("frameCount")) is not int
        or video["frameCount"] <= 0
        or not isinstance(observed, dict)
        or not observed
        or any(
            DEFAULT_FEATURE_VALUES.get(name) != value
            for name, value in observed.items()
        )
        or not isinstance(video_identity, dict)
        or type(video_identity.get("bytes")) is not int
        or video_identity["bytes"] != RELEASE_VIDEO_BYTES
        or video_identity.get("sha256") != RELEASE_VIDEO_SHA256
    ):
        raise RuntimeError(
            "release video is not bound to current default-feature evidence"
        )
    return {"sourceRevision": source_revision, "defaultFeatureCoverage": coverage}


def capture_release_package_files(release_root: Path) -> list[dict[str, Any]]:
    """Hash the shipped surface while excluding toolchain and build products."""
    release_root = release_root.resolve()
    example = RELEASE_EXAMPLE_PATH
    data = example / "Data"
    config = release_root / RELEASE_CONFIG_PATH
    repositories = (
        release_dependencies.release_repositories(config)
        if config.is_file()
        else (release_dependencies.LIBSFX,)
    )
    excluded_prefixes = {
        Path(".git"),
        Path(".venv"),
        *(repository.path for repository in repositories),
        Path("out"),
        Path("src/reference_renderer/vcpkg"),
        example / ".build",
        example / ".build_libsfx",
    }
    excluded_outputs = {
        example / name
        for name in ("quake.sfc", "quake.cpu.sym", "quake.dmap", "quake.dnfo")
    }
    entries: list[dict[str, Any]] = []
    for root, directories, files in os.walk(release_root, topdown=True):
        relative_root = Path(root).relative_to(release_root)
        retained = []
        for name in sorted(directories):
            relative = relative_root / name
            candidate = release_root / relative
            if candidate.is_symlink():
                raise RuntimeError(
                    f"release package directory is a symlink: {relative}"
                )
            if name == "__pycache__":
                continue
            if any(
                relative == prefix or prefix in relative.parents
                for prefix in excluded_prefixes
            ):
                continue
            retained.append(name)
        directories[:] = retained
        for name in sorted(files):
            relative = relative_root / name
            path = release_root / relative
            if path.is_symlink() or not path.is_file():
                raise RuntimeError(f"release package file is not regular: {relative}")
            if path.suffix.lower() in PYTHON_BYTECODE_SUFFIXES:
                continue
            if relative in excluded_outputs:
                continue
            if data in relative.parents and name not in QUALIFIED_ASSET_NAMES:
                continue
            entries.append(
                {
                    "path": relative.as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
    if not entries:
        raise RuntimeError("release package file set is empty")
    return sorted(entries, key=lambda entry: entry["path"])


def _entry_set_sha256(entries: Sequence[Mapping[str, Any]]) -> str:
    digest = hashlib.sha256()
    for entry in entries:
        digest.update(
            entry["path"].encode("utf-8")
            + b"\0"
            + str(entry["bytes"]).encode("ascii")
            + b"\0"
            + entry["sha256"].encode("ascii")
            + b"\n"
        )
    return digest.hexdigest()


def release_manifest_document(
    release_root: Path,
    *,
    contract: Mapping[str, Any],
    preflight: Mapping[str, Any],
    package_files: list[dict[str, Any]],
    generated_assets: Mapping[str, Any],
) -> dict[str, Any]:
    output = release_root / RELEASE_OUTPUT_PATH
    rom = output / "quake.sfc"
    symbols = output / "quake.cpu.sym"
    oracle_entry = next(
        (
            entry
            for entry in contract["files"]
            if entry["path"] == "QuakeBSPPacketOracle.json"
        ),
        None,
    )
    if oracle_entry is None:
        raise RuntimeError("generated-asset contract omits the packet oracle")
    return {
        "schema": "snes-quake-release-qualification-v2",
        "sourceRevision": contract["sourceRevision"],
        "assetPreparation": {
            "sourceRegeneration": ASSET_MODE_REGENERATED,
            "fallback": ASSET_MODE_QUALIFIED,
        },
        "toolchain": {
            "python": preflight["python"],
            "libSFX": preflight["libSFX"],
            "cc65": preflight["cc65"],
            "bspRepositories": preflight.get("bspRepositories", {}),
        },
        "shareware": {
            "bytes": ARCHIVE_IDENTITY.size,
            "sha256": ARCHIVE_IDENTITY.sha256,
        },
        "configuration": contract["configuration"],
        "mesenMapping": contract["mesenMapping"],
        "defaultFeatureCoverage": contract["defaultFeatureCoverage"],
        "generatedAssets": {
            "assetSetSha256": contract["assetSetSha256"],
            "summary": contract["summary"],
            "files": contract["files"],
        },
        "packetContract": {
            **generated_assets["packetContract"],
            "oracle": oracle_entry,
        },
        "rom": {
            "path": str(rom.relative_to(release_root)).replace("\\", "/"),
            "bytes": ROM_IDENTITY.size,
            "sha256": ROM_IDENTITY.sha256,
        },
        "symbols": {
            "path": str(symbols.relative_to(release_root)).replace("\\", "/"),
            "bytes": SYMBOL_IDENTITY.size,
            "sha256": SYMBOL_IDENTITY.sha256,
        },
        "files": package_files,
        "fileSummary": {
            "count": len(package_files),
            "bytes": sum(entry["bytes"] for entry in package_files),
            "sha256": _entry_set_sha256(package_files),
        },
    }


def write_or_verify_release_manifest(
    release_root: Path, document: Mapping[str, Any], *, check: bool
) -> dict[str, Any]:
    path = release_root / RELEASE_MANIFEST
    payload = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("ascii")
    if check:
        if not path.is_file() or path.read_bytes() != payload:
            raise RuntimeError("release qualification manifest is missing or stale")
    else:
        with atomic_path(path) as temporary:
            temporary.write_bytes(payload)
    return {
        "path": RELEASE_MANIFEST.as_posix(),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def build_release(
    release_root: Path,
    shareware_path: Path,
    *,
    assets_only: bool = False,
    check: bool = False,
    qualified_assets: bool = False,
    tar_executable: str | None = None,
) -> dict[str, Any]:
    release_root = release_root.resolve()
    if not release_root.is_dir():
        raise FileNotFoundError(f"release root not found: {release_root}")
    example = release_root / RELEASE_EXAMPLE_PATH
    data = example / "Data"
    libsfx = release_root / LIBSFX_PATH
    if not assets_only and not check:
        # Platform entry points bootstrap these before invoking this command.
        # Reject a direct invocation before costly map/asset regeneration.
        for tool in ("ca65", "ld65"):
            require_cc65_tool(libsfx, tool)
    avx2_available = host_supports_avx2()
    asset_mode = (
        ASSET_MODE_QUALIFIED
        if qualified_assets or not avx2_available
        else ASSET_MODE_REGENERATED
    )
    result: dict[str, Any] = {
        "schema": "quake-bsp-public-build-v2",
        "releaseRoot": str(release_root),
        "shareware": str(shareware_path.resolve()),
        "check": check,
        "assetsOnly": assets_only,
        "assetMode": asset_mode,
        "hostAvx2": avx2_available,
        "steps": [],
    }
    contract = load_generated_asset_contract(release_root)
    qualification = validate_release_qualification_contract(release_root, contract)
    package_files = capture_release_package_files(release_root)
    result["qualification"] = qualification
    result["preflight"] = verify_release_inputs(release_root, shareware_path)
    if asset_mode == ASSET_MODE_REGENERATED:
        if not check:
            prepare_generated_data(release_root, data)
        shareware = SharewareArchive(shareware_path, tar_executable=tar_executable)
        with tempfile.TemporaryDirectory(prefix="quake-build-") as temporary_dir:
            pak = Path(temporary_dir) / "PAK0.PAK"
            with shareware.open_resource() as resource:
                resource.extract_member("ID1/PAK0.PAK", pak)
            pak, modern_step = materialize_configured_pak(
                release_root, pak, Path(temporary_dir)
            )
            if modern_step is not None:
                result["steps"].append(modern_step)
            for name, command in generator_commands(
                release_root, pak, data, check=check
            ):
                step = run_checked(command, release_root)
                step["name"] = name
                result["steps"].append(step)
    result["generatedAssets"] = validate_generated_assets(release_root, data)
    if assets_only:
        return result

    output = release_root / RELEASE_OUTPUT_PATH
    rom = output / "quake.sfc"
    if not check:
        build_tool = release_root / "tools/commands/shared/snes_example_build.py"
        command = [
            sys.executable,
            str(build_tool),
            str(example),
            "--libsfx",
            str(libsfx),
            "--name",
            "quake",
            "--skip-asset-generation",
            "--json",
        ]
        step = run_checked(command, release_root)
        step["name"] = "rom"
        result["steps"].append(step)
    ROM_IDENTITY.verify(rom, "quake.sfc")
    symbols = output / "quake.cpu.sym"
    SYMBOL_IDENTITY.verify(symbols, "quake.cpu.sym")
    result["rom"] = {
        "path": str(rom),
        "bytes": ROM_IDENTITY.size,
        "sha256": ROM_IDENTITY.sha256,
    }
    result["dependencyCount"] = verify_dependency_closure(
        output / "quake.dnfo", release_root
    )
    manifest = release_manifest_document(
        release_root,
        contract=contract,
        preflight=result["preflight"],
        package_files=package_files,
        generated_assets=result["generatedAssets"],
    )
    result["manifest"] = write_or_verify_release_manifest(
        release_root, manifest, check=check
    )
    return result


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-root", type=Path, default=RELEASE_ROOT)
    parser.add_argument(
        "--shareware",
        "--archive",
        dest="shareware",
        type=Path,
        help="complete, unmodified quake106.zip shareware package",
    )
    parser.add_argument("--assets-only", action="store_true")
    parser.add_argument(
        "--qualified-assets",
        action="store_true",
        help="skip AVX2 source regeneration and verify the qualified assets",
    )
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="verify shareware and pinned toolchain inputs, then exit",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify existing assets and ROM without modifying them",
    )
    parser.add_argument("--tar", dest="tar_executable")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.preflight and (args.assets_only or args.check or args.qualified_assets):
        parser.error("--preflight cannot be combined with a build mode")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    started = time.perf_counter()
    args = parse_args(argv)
    release_root = args.release_root.resolve()
    shareware = args.shareware or release_root / SHAREWARE_ARCHIVE
    try:
        result = (
            verify_release_inputs(release_root, shareware)
            if args.preflight
            else build_release(
                release_root,
                shareware,
                assets_only=args.assets_only,
                check=args.check,
                qualified_assets=args.qualified_assets,
                tar_executable=args.tar_executable,
            )
        )
    except (OSError, RuntimeError, ValueError, zipfile.BadZipFile) as error:
        print(
            f"error after {time.perf_counter() - started:.3f}s: {error}",
            file=sys.stderr,
        )
        return 2
    elapsed = time.perf_counter() - started
    if args.json:
        result["elapsedSeconds"] = round(elapsed, 3)
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        action = "verified" if args.check or args.preflight else "built"
        target = (
            "release inputs"
            if args.preflight
            else "assets"
            if args.assets_only
            else "assets and quake.sfc"
        )
        mode = "" if args.preflight else f" via {result['assetMode']}"
        print(
            f"{action} {target} from canonical quake106.zip{mode}; "
            f"elapsed={elapsed:.3f}s"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
