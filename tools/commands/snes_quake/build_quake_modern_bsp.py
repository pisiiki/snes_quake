#!/usr/bin/env python3
"""Build an SNES-compatible E1M3 BSP with the pinned EricW toolchain."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from workspace_paths import shared_tools_root, workspace_root
from quake_release_workspace import default_git_checkout
from quake_release_layout import resolve_input

SHARED_TOOLS = shared_tools_root(__file__)
if str(SHARED_TOOLS) not in sys.path:
    sys.path.insert(0, str(SHARED_TOOLS))

from host_resources import physical_core_count  # noqa: E402
from quake_rom_config import (  # noqa: E402
    BSP_SOURCE_ERICW_MAP,
    DEFAULT_CONFIG,
    BspBuildConfig,
    configured_bsp_build,
)


TOOLS = Path(__file__).resolve().parent
EXAMPLE = workspace_root(__file__) / "src/snes_quake"
OUTPUT = EXAMPLE.parents[1] / "out/snes_quake"
WORKSPACE = workspace_root(__file__)
ERICW_SOURCE = default_git_checkout(WORKSPACE, Path("github/ericwa/ericw-tools/main"))
MAP_SOURCE_ROOT = default_git_checkout(
    WORKSPACE, Path("github/Jason2Brownlee/QuakeOfficialArchive/main")
)
MAP_ARCHIVE = MAP_SOURCE_ROOT / "bin/quake_map_source.zip"
VCPKG = default_git_checkout(WORKSPACE, Path("github/microsoft/vcpkg/master"))
DEFAULT_BUILD_ROOT = WORKSPACE / "tmp/validation/ericw-tools-snes-lightmap-area"
DEFAULT_OUTPUT = OUTPUT / "build/modern-bsp/PAK0.PAK"
DEFAULT_RECEIPT = OUTPUT / "build/modern-bsp/receipt.json"
DEFAULT_BSP_BUILD = configured_bsp_build(DEFAULT_CONFIG)
if DEFAULT_BSP_BUILD.source != BSP_SOURCE_ERICW_MAP:
    raise RuntimeError("default Quake config must select the modern EricW BSP")
PATCH = resolve_input(WORKSPACE, Path(str(DEFAULT_BSP_BUILD.tools_patch)))
MAP_ENTRY = str(DEFAULT_BSP_BUILD.map_entry)
MAP_SOURCE_NAME = str(DEFAULT_BSP_BUILD.map_member)
ERICW_COMMIT = str(DEFAULT_BSP_BUILD.tools_commit)
PROFILE = str(DEFAULT_BSP_BUILD.profile)
QBSP_PROFILE_FLAGS = DEFAULT_BSP_BUILD.qbsp_flags


@dataclass(frozen=True)
class PakEntry:
    name: str
    offset: int
    size: int


@dataclass(frozen=True)
class ToolProfile:
    name: str
    qbsp_flags: tuple[str, ...]
    vis_flags: tuple[str, ...]
    light_flags: tuple[str, ...]
    source: Path | None = None


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _fingerprint(path: Path) -> dict[str, object]:
    payload = path.read_bytes()
    return {
        "path": str(path.resolve()),
        "bytes": len(payload),
        "sha256": _sha256(payload),
    }


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _profile_tokens(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"modern BSP profile {field} must be a non-empty array")
    tokens: list[str] = []
    for index, token in enumerate(value):
        if (
            not isinstance(token, str)
            or not token
            or token != token.strip()
            or "\n" in token
            or "\r" in token
        ):
            raise ValueError(
                f"modern BSP profile {field}[{index}] must be one clean token"
            )
        tokens.append(token)
    return tuple(tokens)


def _load_profile(
    path: Path | None, configured: BspBuildConfig = DEFAULT_BSP_BUILD
) -> ToolProfile:
    if path is None:
        return ToolProfile(
            name=str(configured.profile),
            qbsp_flags=configured.qbsp_flags,
            vis_flags=configured.vis_flags,
            light_flags=configured.light_flags,
        )
    source = path.resolve()
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read modern BSP profile {source}: {error}") from error
    if not isinstance(document, dict):
        raise ValueError("modern BSP profile must be an object")
    if document.get("schema") != "quake-modern-bsp-profile-v1":
        raise ValueError("modern BSP profile has an unsupported schema")
    name = document.get("name")
    if not isinstance(name, str) or not name.strip() or name != name.strip():
        raise ValueError("modern BSP profile name must be a non-empty clean string")
    return ToolProfile(
        name=name,
        qbsp_flags=_profile_tokens(document.get("qbspFlags"), "qbspFlags"),
        vis_flags=_profile_tokens(document.get("visFlags"), "visFlags"),
        light_flags=_profile_tokens(document.get("lightFlags"), "lightFlags"),
        source=source,
    )


def _run(
    command: Sequence[str], cwd: Path, log: Path | None = None
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        list(command),
        cwd=cwd,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if log is not None:
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(completed.stdout, encoding="utf-8")
    if completed.returncode:
        tail = "\n".join(completed.stdout.splitlines()[-20:]) or "no output"
        suffix = f"; log={log.resolve()}" if log is not None else ""
        raise RuntimeError(
            f"command failed with exit {completed.returncode}: "
            f"{' '.join(command)}{suffix}\n{tail}"
        )
    return completed


def _git_output(repository: Path, *arguments: str) -> str:
    return _run(("git", "-C", str(repository), *arguments), WORKSPACE).stdout.strip()


def _normalized_git_url(value: str) -> str:
    return value.strip().removesuffix(".git").rstrip("/").casefold()


def _validate_checkout(
    source: Path, *, commit: str, repository: str, label: str
) -> None:
    if not source.is_dir():
        raise FileNotFoundError(f"{label} checkout does not exist: {source}")
    head = _git_output(source, "rev-parse", "HEAD")
    origin = _git_output(source, "remote", "get-url", "origin")
    status = _git_output(source, "status", "--porcelain", "--untracked-files=no")
    if head != commit:
        raise RuntimeError(f"{label} checkout is at {head}, expected {commit}")
    if _normalized_git_url(origin) != _normalized_git_url(repository):
        raise RuntimeError(
            f"{label} origin is {origin!r}, expected configured {repository!r}"
        )
    if status:
        raise RuntimeError(f"{label} checkout has tracked local changes")


def _workspace_state() -> dict[str, object]:
    status = _git_output(WORKSPACE, "status", "--porcelain", "--untracked-files=no")
    return {
        "commit": _git_output(WORKSPACE, "rev-parse", "HEAD"),
        "clean": not status,
        "trackedChanges": status.splitlines(),
    }


def _prepare_source(
    source: Path, build_root: Path, *, configured: BspBuildConfig, patch: Path
) -> Path:
    _validate_checkout(
        source,
        commit=str(configured.tools_commit),
        repository=str(configured.tools_repository),
        label="EricW tools",
    )
    patched = build_root / "source"
    if not patched.exists():
        patched.parent.mkdir(parents=True, exist_ok=True)
        _run(
            (
                "git",
                "-C",
                str(source),
                "worktree",
                "add",
                "--detach",
                str(patched),
                str(configured.tools_commit),
            ),
            WORKSPACE,
        )
    if _git_output(patched, "rev-parse", "HEAD") != configured.tools_commit:
        raise RuntimeError(f"cached EricW worktree has the wrong commit: {patched}")
    _run(("git", "submodule", "update", "--init", "--recursive"), patched)
    reverse = subprocess.run(
        ("git", "apply", "--check", "--reverse", str(patch)),
        cwd=patched,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if reverse.returncode:
        _run(("git", "apply", "--check", str(patch)), patched)
        _run(("git", "apply", str(patch)), patched)
    return patched


def _default_generator() -> str:
    return "Visual Studio 18 2026" if os.name == "nt" else "Ninja"


def _compiler_parallel_flags(
    generator: str, jobs: int, *, platform_name: str = os.name
) -> tuple[str, ...]:
    """Enable translation-unit parallelism for Visual Studio generators."""
    if platform_name != "nt" or not generator.startswith("Visual Studio "):
        return ()
    return (
        f"-DCMAKE_C_FLAGS=/MP{jobs}",
        f"-DCMAKE_CXX_FLAGS=/MP{jobs}",
    )


def _cmake_path(configured: Path | None) -> str:
    if configured is not None:
        path = configured.resolve()
        if not path.is_file():
            raise FileNotFoundError(f"cmake does not exist: {path}")
        return str(path)
    discovered = shutil.which("cmake")
    if discovered is not None:
        return discovered
    if os.name == "nt":
        program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        visual_studio = program_files / "Microsoft Visual Studio"
        candidates = sorted(
            visual_studio.glob(
                "*/*/Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe"
            ),
            reverse=True,
        )
        if candidates:
            return str(candidates[0])
    raise RuntimeError("cmake was not found; pass --cmake")


def _tool_path(build: Path, target: str) -> Path:
    suffix = ".exe" if os.name == "nt" else ""
    candidate = (
        build / target / ("Release" if os.name == "nt" else "") / (target + suffix)
    )
    return candidate.resolve()


def _vcpkg_configuration(
    root: Path, configured: BspBuildConfig, *, provision: bool
) -> tuple[str, Path]:
    triplet = "x64-windows" if os.name == "nt" else "x64-linux"
    resolved = root.resolve()
    _validate_checkout(
        resolved,
        commit=str(configured.vcpkg_commit),
        repository=str(configured.vcpkg_repository),
        label="vcpkg",
    )
    toolchain = resolved / "scripts/buildsystems/vcpkg.cmake"
    executable = resolved / ("vcpkg.exe" if os.name == "nt" else "vcpkg")
    bootstrap = resolved / (
        "bootstrap-vcpkg.bat" if os.name == "nt" else "bootstrap-vcpkg.sh"
    )
    required = (
        toolchain,
        *(
            resolved / "installed" / triplet / relative
            for relative in configured.vcpkg_required_cmake_configs
        ),
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing and provision:
        if not bootstrap.is_file():
            raise FileNotFoundError(f"vcpkg bootstrap script is missing: {bootstrap}")
        if not executable.is_file():
            command = (
                ("cmd.exe", "/d", "/c", str(bootstrap), "-disableMetrics")
                if os.name == "nt"
                else ("sh", str(bootstrap), "-disableMetrics")
            )
            _run(command, resolved)
        _run(
            (
                str(executable),
                "install",
                *configured.vcpkg_packages,
                "--triplet",
                triplet,
                "--disable-metrics",
            ),
            resolved,
        )
        missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "pinned vcpkg Quake dependencies are incomplete; rerun with "
            f"--provision-vcpkg; missing={missing}"
        )
    return triplet, toolchain


def _build_tools(
    args: argparse.Namespace, configured: BspBuildConfig, patch: Path
) -> dict[str, Path]:
    source = _prepare_source(
        args.ericw_source.resolve(),
        args.build_root.resolve(),
        configured=configured,
        patch=patch,
    )
    triplet, toolchain = _vcpkg_configuration(
        args.vcpkg, configured, provision=args.provision_vcpkg
    )
    build = args.build_root.resolve() / f"build-{triplet}"
    cmake = _cmake_path(args.cmake)
    configure = [
        cmake,
        "-S",
        str(source),
        "-B",
        str(build),
        "-G",
        args.cmake_generator,
    ]
    if os.name == "nt":
        configure.extend(("-A", "x64"))
    configure.extend(
        (
            f"-DCMAKE_TOOLCHAIN_FILE={toolchain}",
            f"-DVCPKG_TARGET_TRIPLET={triplet}",
            *_compiler_parallel_flags(args.cmake_generator, args.jobs),
        )
    )
    _run(configure, WORKSPACE, args.build_root / "configure.log")
    _run(
        (
            cmake,
            "--build",
            str(build),
            "--config",
            "Release",
            "--target",
            "qbsp",
            "vis",
            "light",
            "bsputil",
            "--parallel",
            str(args.jobs),
        ),
        WORKSPACE,
        args.build_root / "build.log",
    )
    result = {
        name: _tool_path(build, name) for name in ("qbsp", "vis", "light", "bsputil")
    }
    missing = [str(path) for path in result.values() if not path.is_file()]
    if missing:
        raise RuntimeError(f"EricW build omitted expected tools: {', '.join(missing)}")
    return result


def _resolve_tools(
    args: argparse.Namespace, configured: BspBuildConfig, patch: Path
) -> dict[str, Path]:
    explicit = {
        name: getattr(args, name).resolve() if getattr(args, name) else None
        for name in ("qbsp", "vis", "light", "bsputil")
    }
    if any(explicit.values()):
        if not all(explicit.values()):
            raise ValueError("pass all four of --qbsp, --vis, --light, and --bsputil")
        tools = {name: path for name, path in explicit.items() if path is not None}
        missing = [str(path) for path in tools.values() if not path.is_file()]
        if missing:
            raise FileNotFoundError(f"EricW tool does not exist: {', '.join(missing)}")
        return tools
    return _build_tools(args, configured, patch)


def _pak_entries(payload: bytes) -> tuple[PakEntry, ...]:
    if len(payload) < 12 or payload[:4] != b"PACK":
        raise ValueError("input is not a Quake PACK archive")
    directory_offset, directory_size = struct.unpack_from("<ii", payload, 4)
    if (
        directory_offset < 12
        or directory_size < 0
        or directory_size % 64
        or directory_offset + directory_size > len(payload)
    ):
        raise ValueError("Quake PAK directory is invalid")
    entries: list[PakEntry] = []
    seen: set[str] = set()
    for offset in range(directory_offset, directory_offset + directory_size, 64):
        raw_name, data_offset, size = struct.unpack_from("<56sii", payload, offset)
        name = raw_name.split(b"\0", 1)[0].decode("ascii").replace("\\", "/")
        key = name.casefold()
        if not name or key in seen or data_offset < 0 or size < 0:
            raise ValueError(f"Quake PAK entry is invalid or duplicated: {name!r}")
        if data_offset + size > len(payload):
            raise ValueError(f"Quake PAK entry escapes the archive: {name!r}")
        seen.add(key)
        entries.append(PakEntry(name, data_offset, size))
    return tuple(entries)


def _pak_read(payload: bytes, entries: Sequence[PakEntry], name: str) -> bytes:
    key = name.casefold()
    for entry in entries:
        if entry.name.casefold() == key:
            return payload[entry.offset : entry.offset + entry.size]
    raise ValueError(f"Quake PAK is missing {name!r}")


def _replace_pak_entry(
    source: Path, output: Path, name: str, replacement: bytes
) -> None:
    payload = source.read_bytes()
    entries = _pak_entries(payload)
    if not any(entry.name.casefold() == name.casefold() for entry in entries):
        raise ValueError(f"Quake PAK is missing {name!r}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    directory: list[PakEntry] = []
    with temporary.open("wb") as stream:
        stream.write(b"PACK\0\0\0\0\0\0\0\0")
        for entry in entries:
            data = (
                replacement
                if entry.name.casefold() == name.casefold()
                else payload[entry.offset : entry.offset + entry.size]
            )
            directory.append(PakEntry(entry.name, stream.tell(), len(data)))
            stream.write(data)
        directory_offset = stream.tell()
        for entry in directory:
            encoded = entry.name.encode("ascii")
            if len(encoded) > 55:
                raise ValueError(f"Quake PAK name is too long: {entry.name!r}")
            stream.write(struct.pack("<56sii", encoded, entry.offset, entry.size))
        stream.seek(4)
        stream.write(struct.pack("<ii", directory_offset, len(directory) * 64))
    temporary.replace(output)
    rebuilt = output.read_bytes()
    rebuilt_entries = _pak_entries(rebuilt)
    if _pak_read(rebuilt, rebuilt_entries, name) != replacement:
        raise RuntimeError("rebuilt Quake PAK failed replacement verification")


def _extract_map(archive: Path, member_name: str = MAP_SOURCE_NAME) -> bytes:
    with zipfile.ZipFile(archive) as source:
        matches = [
            item
            for item in source.infolist()
            if Path(item.filename).name.casefold() == Path(member_name).name.casefold()
        ]
        if len(matches) != 1:
            raise ValueError(
                f"expected one {member_name!r} in {archive}, found {len(matches)}"
            )
        return source.read(matches[0])


def build(args: argparse.Namespace) -> dict[str, Any]:
    started = time.monotonic()
    config_path = args.config.resolve()
    configured = configured_bsp_build(config_path)
    if configured.source != BSP_SOURCE_ERICW_MAP:
        raise ValueError("configured BSP source is not ericw-map")
    pak = args.pak.resolve()
    archive = args.map_archive.resolve()
    expected_archive = (
        args.map_source_root.resolve() / str(configured.map_archive)
    ).resolve()
    if archive != expected_archive:
        raise ValueError(
            f"map archive is {archive}, expected configured {expected_archive}"
        )
    patch = resolve_input(WORKSPACE, Path(str(configured.tools_patch)))
    if not pak.is_file() or not archive.is_file() or not patch.is_file():
        raise FileNotFoundError(
            "PAK, official map archive, and EricW patch are required"
        )
    _validate_checkout(
        args.map_source_root.resolve(),
        commit=str(configured.map_commit),
        repository=str(configured.map_repository),
        label="official Quake map source",
    )
    _validate_checkout(
        args.ericw_source.resolve(),
        commit=str(configured.tools_commit),
        repository=str(configured.tools_repository),
        label="EricW tools",
    )
    tools = _resolve_tools(args, configured, patch)
    profile = _load_profile(args.profile, configured)
    work = args.build_root.resolve() / "map"
    gfx = work / "gfx"
    gfx.mkdir(parents=True, exist_ok=True)
    map_source_name = Path(str(configured.map_member)).name
    map_entry = str(configured.map_entry)
    map_payload = _extract_map(archive, map_source_name)
    map_path = work / map_source_name
    map_path.write_bytes(map_payload)

    pak_payload = pak.read_bytes()
    entries = _pak_entries(pak_payload)
    shipping_bsp = _pak_read(pak_payload, entries, map_entry)
    shipping_path = work / f"shipping-{Path(map_entry).name}"
    shipping_path.write_bytes(shipping_bsp)
    _run(
        (str(tools["bsputil"]), "-extract-textures", shipping_path.name),
        work,
        work / "bsputil.log",
    )
    wad = shipping_path.with_suffix(".wad")
    if not wad.is_file():
        raise RuntimeError("bsputil did not produce the expected E1M3 texture WAD")
    shutil.copyfile(wad, gfx / "wizard.wad")

    commands = {
        "qbsp": [
            str(tools["qbsp"]),
            "-threads",
            str(args.map_threads),
            *profile.qbsp_flags,
            map_source_name,
        ],
        "vis": [
            str(tools["vis"]),
            "-threads",
            str(args.map_threads),
            *profile.vis_flags,
            map_path.with_suffix(".bsp").name,
        ],
        "light": [
            str(tools["light"]),
            "-threads",
            str(args.map_threads),
            *profile.light_flags,
            map_path.with_suffix(".bsp").name,
        ],
    }
    for name in ("qbsp", "vis", "light"):
        _run(commands[name], work, work / f"{name}.log")
    bsp = map_path.with_suffix(".bsp")
    if not bsp.is_file():
        raise RuntimeError(f"EricW toolchain did not produce {bsp.name}")
    output = args.output_pak.resolve()
    _replace_pak_entry(pak, output, map_entry, bsp.read_bytes())

    receipt: dict[str, Any] = {
        "schema": "quake-modern-bsp-build-v1",
        "profile": profile.name,
        "profileDefinition": {
            "schema": "quake-modern-bsp-profile-v1",
            "qbspFlags": list(profile.qbsp_flags),
            "visFlags": list(profile.vis_flags),
            "lightFlags": list(profile.light_flags),
            "source": (
                _fingerprint(profile.source) if profile.source is not None else None
            ),
        },
        "configuration": _fingerprint(config_path),
        "ericwCommit": configured.tools_commit,
        "source": _workspace_state(),
        "inputs": {
            "pak": _fingerprint(pak),
            "mapArchive": _fingerprint(archive),
            "map": {
                "member": map_source_name,
                "bytes": len(map_payload),
                "sha256": _sha256(map_payload),
            },
            "shippingBsp": {
                "entry": map_entry,
                "bytes": len(shipping_bsp),
                "sha256": _sha256(shipping_bsp),
            },
            "patch": _fingerprint(patch),
        },
        "tools": {name: _fingerprint(path) for name, path in tools.items()},
        "commands": commands,
        "settings": {
            "compileJobs": args.jobs,
            "cmakeGenerator": args.cmake_generator,
            "maxWorldLightmapSamples": args.max_world_lightmap_samples,
            "maxInlineModelLightmapSamples": args.max_inline_model_lightmap_samples,
            "mapThreads": args.map_threads,
        },
        "outputs": {
            "bsp": _fingerprint(bsp),
            "pak": _fingerprint(output),
        },
        "elapsedSeconds": round(time.monotonic() - started, 3),
    }
    _atomic_json(args.receipt.resolve(), receipt)
    return receipt


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pak", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--map-source-root", type=Path, default=MAP_SOURCE_ROOT)
    parser.add_argument("--map-archive", type=Path)
    parser.add_argument("--ericw-source", type=Path, default=ERICW_SOURCE)
    parser.add_argument("--vcpkg", type=Path, default=VCPKG)
    parser.add_argument("--provision-vcpkg", action="store_true")
    parser.add_argument("--build-root", type=Path, default=DEFAULT_BUILD_ROOT)
    parser.add_argument("--output-pak", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    parser.add_argument(
        "--profile",
        type=Path,
        help="experimental JSON override; omission uses rom-config.json",
    )
    parser.add_argument("--jobs", type=int, default=physical_core_count())
    parser.add_argument(
        "--map-threads",
        type=int,
        help="override the configured deterministic map-tool thread count",
    )
    parser.add_argument("--max-world-lightmap-samples", type=int)
    parser.add_argument("--max-inline-model-lightmap-samples", type=int)
    parser.add_argument("--cmake-generator", default=_default_generator())
    parser.add_argument("--cmake", type=Path)
    for name in ("qbsp", "vis", "light", "bsputil"):
        parser.add_argument(f"--{name}", type=Path)
    args = parser.parse_args(argv)
    try:
        configured = configured_bsp_build(args.config)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    if configured.source != BSP_SOURCE_ERICW_MAP:
        parser.error("--config must select bspBuild source 'ericw-map'")
    args.map_archive = args.map_archive or (
        args.map_source_root / str(configured.map_archive)
    )
    args.map_threads = (
        configured.map_threads if args.map_threads is None else args.map_threads
    )
    args.max_world_lightmap_samples = (
        configured.world_lightmap_samples
        if args.max_world_lightmap_samples is None
        else args.max_world_lightmap_samples
    )
    args.max_inline_model_lightmap_samples = (
        configured.inline_model_lightmap_samples
        if args.max_inline_model_lightmap_samples is None
        else args.max_inline_model_lightmap_samples
    )
    if args.jobs <= 0:
        parser.error("--jobs must be positive")
    if args.map_threads <= 0:
        parser.error("--map-threads must be positive")
    if args.map_threads != configured.map_threads:
        parser.error("--map-threads must match the deterministic config value")
    if args.max_world_lightmap_samples != configured.world_lightmap_samples:
        parser.error("--max-world-lightmap-samples must match rom-config.json")
    if (
        args.max_inline_model_lightmap_samples
        != configured.inline_model_lightmap_samples
    ):
        parser.error("--max-inline-model-lightmap-samples must match rom-config.json")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    started = time.monotonic()
    try:
        args = parse_args(argv)
        receipt = build(args)
    except KeyboardInterrupt:
        print(
            f"modern BSP build interrupted; elapsed={time.monotonic() - started:.3f}s",
            file=sys.stderr,
        )
        return 130
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(
            f"error: {error}; elapsed={time.monotonic() - started:.3f}s",
            file=sys.stderr,
        )
        return 1
    print(
        "modern BSP build passed: "
        f"profile={receipt['profile']} "
        f"bspSha256={receipt['outputs']['bsp']['sha256']} "
        f"pak={receipt['outputs']['pak']['path']} "
        f"elapsed={receipt['elapsedSeconds']:.3f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
