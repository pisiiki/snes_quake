#!/usr/bin/env python3
"""Generate and build the public SNES Quake release from Quake shareware."""

from __future__ import annotations

import argparse
import hashlib
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
from typing import Any, Callable, Iterator, Mapping, Sequence


RELEASE_ROOT = Path(__file__).resolve().parents[3]
RELEASE_EXAMPLE_PATH = Path("src/snes_quake")
SHAREWARE_ARCHIVE = Path("quake106/quake106.zip")
RESOURCE_MEMBER = "resource.1"
GENERATED_ASSET_BYTES = 2_402_024
GENERATED_ASSET_NAMES = (
    "QuakeBSPBrushAssets.i",
    "QuakeBSPBrushAssets.json",
    *(f"QuakeBSPBrushFragments{index}.bin" for index in range(15)),
    "QuakeBSPBrushReplay30Hz.bin",
    "QuakeBSPBrushReplay30Hz.json",
    *(f"QuakeBSPBrushRuntime{index}.bin" for index in range(2)),
    *(f"QuakeBSPBrushTexturePixels{index}.bin" for index in range(4)),
    "QuakeBSPCos.bin",
    "QuakeBSPDemoPrecise30Hz.bin",
    "QuakeBSPDemoPrecise30HzTiming.bin",
    "QuakeBSPDemoTiming.bin",
    "QuakeBSPDemoTrack.bin",
    "QuakeBSPDivideQ12Reciprocal.bin",
    "QuakeBSPExpandLeft.bin",
    "QuakeBSPExpandRight.bin",
    "QuakeBSPFacePlanes.bin",
    "QuakeBSPFaces.bin",
    "QuakeBSPIndices.bin",
    "QuakeBSPLightmapColormap.bin",
    "QuakeBSPLightmapColormapMap.bin",
    "QuakeBSPLightmapLevelZeroColormap.bin",
    "QuakeBSPMetadata.json",
    "QuakeBSPMonsterCameras.bin",
    "QuakeBSPMonsterCameras.i",
    "QuakeBSPMonsterCameras.json",
    "QuakeBSPPalette.bin",
    "QuakeBSPReciprocal.bin",
    "QuakeBSPScene.i",
    "QuakeBSPSin.bin",
    "QuakeBSPTemporalPalette.json",
    "QuakeBSPTextureColormap.bin",
    "QuakeBSPTextureCoordinateMap.bin",
    "QuakeBSPTextureDepthShade.bin",
    "QuakeBSPTexturePalette.bin",
    *(f"QuakeBSPTexturePaletteTemporal{index}.bin" for index in range(2)),
    "QuakeBSPTextureTilemap.bin",
    "QuakeBSPTilemap.bin",
    "QuakeBSPVertices.bin",
    "QuakeBSPWorldFaceOwners.bin",
    "QuakeBSPWorldFacePlanes.bin",
    "QuakeBSPWorldFaceTextureIds.bin",
    "QuakeBSPWorldFaces.bin",
    *(f"QuakeBSPWorldIndices{index}.bin" for index in range(2)),
    "QuakeBSPWorldLeaves.bin",
    "QuakeBSPWorldLightmapDirectory.bin",
    *(f"QuakeBSPWorldLightmapSamples{index}.bin" for index in range(5)),
    "QuakeBSPWorldMarksurfaces.bin",
    "QuakeBSPWorldNodeParents.bin",
    "QuakeBSPWorldNodes.bin",
    *(f"QuakeBSPWorldPVS{index}.bin" for index in range(3)),
    "QuakeBSPWorldPVSDirectory.bin",
    "QuakeBSPWorldPVSGuards.bin",
    "QuakeBSPWorldPlanes.bin",
    "QuakeBSPWorldShading.bin",
    *(f"QuakeBSPWorldTextureCoordinates{index}.bin" for index in range(3)),
    "QuakeBSPWorldTextureDirectory.bin",
    *(f"QuakeBSPWorldTexturePixels{index}.bin" for index in range(6)),
    "QuakeBSPWorldVertices.bin",
    *(f"QuakeBSPWorldVisibility{index}.bin" for index in range(2)),
)


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
    2_097_152,
    "918c7b2599f1bee1bfde18e9ce86f1041649d689bafd2a4151f630c4effda962",
)
LIBSFX_COMMIT = "61b3ea97e398333c1b7a6f62a53f1112fdfb6070"
LIBSFX_ORIGIN = "https://github.com/Optiroc/libSFX.git"
LIBSFX_PATH = Path("libSFX")
CC65_COMMIT = "cc3c40c54e51b2d9a22b63c85c418a2b11763377"
CC65_ORIGIN = "https://github.com/cc65/cc65.git"
TAR_TIMEOUT_SECONDS = 120
TAR_PROBE_TIMEOUT_SECONDS = 10


CommandRunner = Callable[..., subprocess.CompletedProcess[Any]]


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


def verify_release_inputs(
    release_root: Path,
    shareware_path: Path,
    *,
    runner: CommandRunner | None = None,
) -> dict[str, object]:
    release_root = release_root.resolve()
    if not release_root.is_dir():
        raise FileNotFoundError(f"release root not found: {release_root}")
    libsfx = release_root / LIBSFX_PATH
    shareware = SharewareArchive(shareware_path).verify()
    return {
        "schema": "quake-bsp-public-preflight-v1",
        "releaseRoot": str(release_root),
        "shareware": shareware,
        "libSFX": verify_libsfx_submodule(libsfx, runner=runner),
        "cc65": verify_cc65_submodule(libsfx / "tools/cc65", runner=runner),
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
    tools = release_root / RELEASE_EXAMPLE_PATH / "tools"
    common = ["--pak", str(pak), "--output", str(data)]
    checked = ["--check"] if check else []
    metadata = data / "QuakeBSPMetadata.json"
    return (
        (
            "world",
            [
                sys.executable,
                str(tools / "generate_quake_bsp.py"),
                *common,
                *checked,
            ],
        ),
        (
            "brush",
            [
                sys.executable,
                str(tools / "generate_quake_brush_replay.py"),
                *common,
                *checked,
            ],
        ),
        (
            "monster",
            [
                sys.executable,
                str(tools / "generate_quake_monster_cameras.py"),
                *common,
                "--metadata",
                str(metadata),
                *checked,
            ],
        ),
        (
            "temporal",
            [
                sys.executable,
                str(tools / "generate_quake_bsp_temporal_palette.py"),
                *common,
                *checked,
            ],
        ),
    )


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


def validate_generated_assets(release_root: Path, data: Path) -> dict[str, int]:
    release_root = release_root.resolve()
    data = data.resolve()
    expected = {(data / name).resolve() for name in GENERATED_ASSET_NAMES}
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
            "generated Data set differs from the build contract; "
            + "; ".join(details)
        )
    actual_summary = {
        "count": len(actual),
        "bytes": sum(path.stat().st_size for path in actual),
    }
    if (
        len(GENERATED_ASSET_NAMES) != actual_summary["count"]
        or GENERATED_ASSET_BYTES != actual_summary["bytes"]
    ):
        raise RuntimeError(
            "generated Data totals differ from the build contract: "
            f"{actual_summary}, expected "
            f"{{'count': {len(GENERATED_ASSET_NAMES)}, "
            f"'bytes': {GENERATED_ASSET_BYTES}}}"
        )
    return actual_summary


def build_release(
    release_root: Path,
    shareware_path: Path,
    *,
    assets_only: bool = False,
    check: bool = False,
    tar_executable: str | None = None,
) -> dict[str, Any]:
    release_root = release_root.resolve()
    if not release_root.is_dir():
        raise FileNotFoundError(f"release root not found: {release_root}")
    example = release_root / RELEASE_EXAMPLE_PATH
    data = example / "Data"
    libsfx = release_root / LIBSFX_PATH
    result: dict[str, Any] = {
        "schema": "quake-bsp-public-build-v1",
        "releaseRoot": str(release_root),
        "shareware": str(shareware_path.resolve()),
        "check": check,
        "assetsOnly": assets_only,
        "steps": [],
    }
    result["preflight"] = verify_release_inputs(release_root, shareware_path)
    shareware = SharewareArchive(shareware_path, tar_executable=tar_executable)
    with tempfile.TemporaryDirectory(prefix="quake-build-") as temporary_dir:
        pak = Path(temporary_dir) / "PAK0.PAK"
        with shareware.open_resource() as resource:
            resource.extract_member("ID1/PAK0.PAK", pak)
        for name, command in generator_commands(release_root, pak, data, check=check):
            step = run_checked(command, release_root)
            step["name"] = name
            result["steps"].append(step)
    result["generatedAssets"] = validate_generated_assets(release_root, data)
    if assets_only:
        return result

    rom = example / "quake.sfc"
    if not check:
        build_tool = release_root / "src/shared/tools/snes_example_build.py"
        command = [
            sys.executable,
            str(build_tool),
            str(example),
            "--libsfx",
            str(libsfx),
            "--name",
            "quake",
            "--json",
        ]
        step = run_checked(command, release_root)
        step["name"] = "rom"
        result["steps"].append(step)
    ROM_IDENTITY.verify(rom, "quake.sfc")
    result["rom"] = {
        "path": str(rom),
        "bytes": ROM_IDENTITY.size,
        "sha256": ROM_IDENTITY.sha256,
    }
    result["dependencyCount"] = verify_dependency_closure(
        example / "quake.dnfo", release_root
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
    if args.preflight and (args.assets_only or args.check):
        parser.error("--preflight cannot be combined with --assets-only or --check")
    return args


def main(argv: Sequence[str] | None = None) -> int:
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
                tar_executable=args.tar_executable,
            )
        )
    except (OSError, RuntimeError, ValueError, zipfile.BadZipFile) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if args.json:
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
        print(f"{action} {target} from canonical quake106.zip")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
