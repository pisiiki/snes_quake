from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from snes_tooling.shared.ld65_debug import load_debug_records, parse_debug_int
from snes_tooling.shared.lint_gsu_fx3_opcodes import (
    source_targets_fx3,
    validate_gsu_fx3_opcodes,
)
from snes_tooling.shared.lint_gsu_special_registers import (
    validate_gsu_special_registers,
)
from snes_tooling.shared.validate_gsu_cache_kernels import (
    validate_cache_kernels,
    validate_cache_manifest,
)
from snes_tooling.workspace import Workspace


LIBSFX_SOURCES = [
    ("CPU/Header.s", "CPU/Header.o", []),
    ("CPU/Library.s", "CPU/Library.o", []),
    ("CPU/Runtime.s", "CPU/Runtime.o", []),
    ("CPU/SMP.s", "CPU/SMP.o", []),
    ("SMP/System.s700", "SMP/System.o700", ["-D", "TARGET_SMP"]),
]
WORKSPACE = Workspace.discover().root
LIBSFX_WORKSPACE_PATH = Path("github/Optiroc/libSFX/master")
LIBSFX_NATIVE_TOOLS = ("ca65", "ld65")


def _complete_libsfx(candidate: Path, *, os_name: str | None = None) -> bool:
    platform = os.name if os_name is None else os_name
    suffix = ".exe" if platform == "nt" else ""
    return (candidate / "include/libSFX.i").is_file() and all(
        (candidate / "tools/cc65/bin" / f"{tool}{suffix}").is_file()
        for tool in LIBSFX_NATIVE_TOOLS
    )


def _git_common_directory(workspace: Path) -> Path | None:
    """Return Git's absolute common directory for one checkout, if available."""
    try:
        result = subprocess.run(
            (
                "git",
                "-C",
                str(workspace),
                "rev-parse",
                "--path-format=absolute",
                "--git-common-dir",
            ),
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    if result.returncode or not result.stdout.strip():
        return None
    return Path(result.stdout.strip()).resolve()


def default_libsfx(workspace: Path, *, os_name: str | None = None) -> Path:
    """Resolve the canonical libSFX checkout for this workspace layout."""
    if (workspace / "libSFX").is_dir() and (workspace / "src/snes_quake").is_dir():
        return workspace / "libSFX"
    local = workspace / LIBSFX_WORKSPACE_PATH
    if _complete_libsfx(local, os_name=os_name):
        return local
    common_directory = _git_common_directory(workspace)
    if common_directory is not None and common_directory.name == ".git":
        primary = common_directory.parent / LIBSFX_WORKSPACE_PATH
        if primary != local and _complete_libsfx(primary, os_name=os_name):
            return primary
    for parent in workspace.parents:
        candidate = parent / LIBSFX_WORKSPACE_PATH
        if _complete_libsfx(candidate, os_name=os_name):
            return candidate
    return local


DEFAULT_LIBSFX = default_libsfx(WORKSPACE)
FRESHNESS_SCHEMA = "snes-example-build-freshness-v1"
SNES_HEADER_ROM_SIZE_OFFSET = 0x27
SNES_HEADER_COMPLEMENT_OFFSET = 0x2C
SNES_HEADER_CHECKSUM_OFFSET = 0x2E
SNES_HEADER_BYTES = 0x30
ASSET_GENERATOR = Path("tools/generate_snes_example_assets.py")
PROJECT_MANIFEST = Path("snes-project.json")
PROJECT_MANIFEST_SCHEMA = "snes-example-project-v1"


@dataclass(frozen=True)
class ProjectLayout:
    """Resolved build and tooling paths for one SNES project."""

    manifest: Path | None
    asset_generator: Path
    build_dir: Path
    libsfx_build_dir: Path
    output_dir: Path
    cache_kernel_manifest: Path


def _project_path(example_dir: Path, value: object, *, field: str) -> Path:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\n" in value
        or "\r" in value
    ):
        raise ValueError(f"SNES project {field} must be one clean relative path")
    candidate = Path(value)
    if candidate.is_absolute():
        raise ValueError(f"SNES project {field} must be relative")
    return (example_dir / candidate).resolve()


def project_layout(example_dir: Path) -> ProjectLayout:
    """Load an optional project manifest while preserving legacy defaults."""

    example_dir = example_dir.resolve()
    manifest = example_dir / PROJECT_MANIFEST
    defaults = {
        "assetGenerator": ASSET_GENERATOR.as_posix(),
        "buildDirectory": ".build",
        "libsfxBuildDirectory": ".build_libsfx",
        "outputDirectory": ".",
        "cacheKernelManifest": "GSUCacheKernels.json",
    }
    if not manifest.is_file():
        document: dict[str, object] = {
            "schema": PROJECT_MANIFEST_SCHEMA,
            **defaults,
        }
        manifest_path: Path | None = None
    else:
        try:
            value = json.loads(manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError(f"SNES project manifest is invalid JSON: {manifest}") from error
        if not isinstance(value, dict):
            raise ValueError(f"SNES project manifest must be an object: {manifest}")
        allowed = {"schema", *defaults}
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise ValueError(
                f"SNES project manifest has unknown field {unknown[0]!r}: {manifest}"
            )
        if value.get("schema") != PROJECT_MANIFEST_SCHEMA:
            raise ValueError(
                f"SNES project manifest schema must be {PROJECT_MANIFEST_SCHEMA!r}"
            )
        document = {**defaults, **value}
        manifest_path = manifest
    return ProjectLayout(
        manifest=manifest_path,
        asset_generator=_project_path(
            example_dir, document["assetGenerator"], field="assetGenerator"
        ),
        build_dir=_project_path(
            example_dir, document["buildDirectory"], field="buildDirectory"
        ),
        libsfx_build_dir=_project_path(
            example_dir,
            document["libsfxBuildDirectory"],
            field="libsfxBuildDirectory",
        ),
        output_dir=_project_path(
            example_dir, document["outputDirectory"], field="outputDirectory"
        ),
        cache_kernel_manifest=_project_path(
            example_dir,
            document["cacheKernelManifest"],
            field="cacheKernelManifest",
        ),
    )


def cc65_tool_path(
    libsfx_dir: Path,
    tool_name: str,
    *,
    os_name: str | None = None,
) -> Path:
    """Return a bundled cc65 tool using the native host executable name."""
    host_os = os.name if os_name is None else os_name
    suffix = ".exe" if host_os == "nt" else ""
    return libsfx_dir / "tools" / "cc65" / "bin" / f"{tool_name}{suffix}"


def require_cc65_tool(libsfx_dir: Path, tool_name: str) -> Path:
    path = cc65_tool_path(libsfx_dir, tool_name)
    if not path.is_file():
        raise FileNotFoundError(
            f"pinned cc65 tool is not built: {path}; run the release build entry "
            "point without --check first"
        )
    return path


def _stale_build(message: str) -> RuntimeError:
    return RuntimeError(f"stale SNES build: {message}; rerun without --no-build")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _fingerprint(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    return {
        "path": str(resolved),
        "bytes": resolved.stat().st_size,
        "sha256": _sha256_file(resolved),
    }


def patch_snes_rom_checksum(rom: Path, debug_info: Path) -> dict[str, int]:
    """Patch and verify the checksum fields in an ld65-linked SNES ROM."""
    headers = [
        segment
        for segment in load_debug_records(debug_info).get("seg", ())
        if segment.get("name") == "HEADER"
    ]
    if len(headers) != 1:
        raise ValueError(
            f"expected one HEADER segment in {debug_info}, found {len(headers)}"
        )
    try:
        header_offset = parse_debug_int(headers[0]["ooffs"])
    except (KeyError, ValueError) as error:
        raise ValueError(
            f"HEADER segment in {debug_info} lacks a valid output offset"
        ) from error

    image = bytearray(rom.read_bytes())
    if header_offset < 0 or header_offset + SNES_HEADER_BYTES > len(image):
        raise ValueError(
            f"HEADER segment at {header_offset} lies outside {rom} ({len(image)} bytes)"
        )
    rom_size_code = image[header_offset + SNES_HEADER_ROM_SIZE_OFFSET]
    declared_bytes = 1 << (rom_size_code + 10)
    if declared_bytes != len(image):
        raise ValueError(
            f"SNES header declares {declared_bytes} ROM bytes but {rom} has "
            f"{len(image)}"
        )

    complement_offset = header_offset + SNES_HEADER_COMPLEMENT_OFFSET
    checksum_offset = header_offset + SNES_HEADER_CHECKSUM_OFFSET
    image[complement_offset : checksum_offset + 2] = b"\xff\xff\x00\x00"
    checksum = sum(image) & 0xFFFF
    complement = checksum ^ 0xFFFF
    image[complement_offset : complement_offset + 2] = complement.to_bytes(2, "little")
    image[checksum_offset : checksum_offset + 2] = checksum.to_bytes(2, "little")

    stored_complement = int.from_bytes(
        image[complement_offset : complement_offset + 2], "little"
    )
    stored_checksum = int.from_bytes(
        image[checksum_offset : checksum_offset + 2], "little"
    )
    if stored_checksum != checksum or stored_complement != complement:
        raise RuntimeError(f"failed to patch SNES checksum in {rom}")
    if stored_checksum ^ stored_complement != 0xFFFF:
        raise RuntimeError(f"invalid SNES checksum complement in {rom}")
    rom.write_bytes(image)
    return {
        "checksum": checksum,
        "complement": complement,
        "headerOffset": header_offset,
    }


def _freshness_path(example_dir: Path, name: str) -> Path:
    return project_layout(example_dir).build_dir / f"{name}.freshness.json"


def _normalize_ld65_labels(path: Path) -> None:
    """Freeze ld65's platform-native label newlines to the release contract."""

    payload = path.read_bytes()
    canonical = payload.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    canonical = canonical.replace(b"\n", b"\r\n")
    if canonical == payload:
        return
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(canonical)
    temporary.replace(path)


def _write_snes_example_freshness(
    example_dir: Path,
    libsfx_dir: Path,
    name: str,
) -> Path:
    layout = project_layout(example_dir)
    ca65 = require_cc65_tool(libsfx_dir, "ca65")
    ld65 = require_cc65_tool(libsfx_dir, "ld65")
    outputs = {
        "rom": layout.output_dir / f"{name}.sfc",
        "symbols": layout.output_dir / f"{name}.cpu.sym",
        "map": layout.output_dir / f"{name}.dmap",
        "debugInfo": layout.output_dir / f"{name}.dnfo",
    }
    link_inputs = (
        example_dir / "Map.cfg",
        Path(__file__),
        ca65,
        ld65,
    )
    receipt = {
        "schema": FRESHNESS_SCHEMA,
        "name": name,
        "outputs": {key: _fingerprint(path) for key, path in outputs.items()},
        "linkInputs": [_fingerprint(path) for path in link_inputs],
    }
    destination = _freshness_path(example_dir, name)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    temporary.replace(destination)
    return destination


def _require_fingerprint(
    recorded: object,
    current_path: Path,
    *,
    role: str,
) -> None:
    if not isinstance(recorded, dict):
        raise _stale_build(f"malformed {role} fingerprint")
    current_path = current_path.resolve()
    if recorded.get("path") != str(current_path):
        raise _stale_build(f"{role} path changed to {current_path}")
    if not current_path.is_file():
        raise _stale_build(f"missing {role} {current_path}")
    current = _fingerprint(current_path)
    if (
        recorded.get("bytes") != current["bytes"]
        or recorded.get("sha256") != current["sha256"]
    ):
        raise _stale_build(f"{role} content changed: {current_path}")


def require_snes_example_fresh(
    example_dir: Path,
    name: str,
    *,
    rom: Path | None = None,
    asset_generator_arguments: Sequence[str] = (),
) -> dict[str, Any]:
    """Require an existing example build to match its assembler dependencies."""
    example_dir = example_dir.resolve()
    layout = project_layout(example_dir)
    run_example_asset_generator(
        example_dir,
        check=True,
        arguments=asset_generator_arguments,
    )
    debug_info = layout.output_dir / f"{name}.dnfo"
    outputs = {
        "rom": rom.resolve() if rom is not None else layout.output_dir / f"{name}.sfc",
        "symbols": layout.output_dir / f"{name}.cpu.sym",
        "map": layout.output_dir / f"{name}.dmap",
        "debugInfo": debug_info,
    }
    for output in outputs.values():
        if not output.is_file():
            raise _stale_build(f"missing output {output}")

    receipt_path = _freshness_path(example_dir, name)
    if not receipt_path.is_file():
        raise _stale_build(f"missing build receipt {receipt_path}")
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise _stale_build(f"malformed build receipt {receipt_path}") from error
    if (
        receipt.get("schema") != FRESHNESS_SCHEMA
        or receipt.get("name") != name
        or not isinstance(receipt.get("outputs"), dict)
        or not isinstance(receipt.get("linkInputs"), list)
    ):
        raise _stale_build(f"malformed build receipt {receipt_path}")
    for key, output in outputs.items():
        _require_fingerprint(receipt["outputs"].get(key), output, role=f"{key} output")
    for recorded in receipt["linkInputs"]:
        if not isinstance(recorded, dict) or not isinstance(recorded.get("path"), str):
            raise _stale_build(f"malformed build receipt {receipt_path}")
        _require_fingerprint(
            recorded,
            Path(recorded["path"]),
            role="link input",
        )

    records = load_debug_records(debug_info).get("file", ())
    if not records:
        raise _stale_build(f"{debug_info} has no dependency records")

    dependencies: set[Path] = set()
    for record in records:
        try:
            recorded_name = record["name"]
            recorded_size = parse_debug_int(record["size"])
            recorded_mtime = parse_debug_int(record["mtime"])
        except (KeyError, ValueError) as error:
            raise _stale_build(
                f"malformed dependency record in {debug_info}"
            ) from error
        dependency = Path(recorded_name)
        if not dependency.is_absolute():
            dependency = example_dir / dependency
        dependency = dependency.resolve()
        if dependency in dependencies:
            continue
        dependencies.add(dependency)
        if not dependency.is_file():
            raise _stale_build(f"missing dependency {dependency}")
        current = dependency.stat()
        if current.st_size != recorded_size:
            raise _stale_build(
                f"dependency {dependency} changed size "
                f"({recorded_size} -> {current.st_size})"
            )
        current_mtime = int(current.st_mtime)
        if current_mtime != recorded_mtime:
            raise _stale_build(
                f"dependency {dependency} changed modification time "
                f"({recorded_mtime} -> {current_mtime})"
            )

    return {
        "debugInfo": str(debug_info),
        "dependencyCount": len(dependencies),
        "outputs": [str(output) for output in outputs.values()],
        "receipt": str(receipt_path),
    }


def run_checked(
    command: list[str],
    cwd: Path,
    *,
    echo_output: bool = False,
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    if echo_output:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        assert process.stdout is not None
        output: list[str] = []
        try:
            for line in process.stdout:
                output.append(line)
                print(line, end="", file=sys.stderr, flush=True)
            returncode = process.wait()
        except KeyboardInterrupt:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise
        stdout = "".join(output)
    else:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        returncode = result.returncode
        stdout = result.stdout
    elapsed = round(time.monotonic() - started, 3)
    if returncode:
        raise RuntimeError(
            f"command failed with exit {returncode}: {' '.join(command)}\n{stdout}"
        )
    return {"command": command[0], "elapsedSeconds": elapsed}


def python_child_environment(
    package_root: Path,
    *,
    environment: Mapping[str, str] | None = None,
    path_separator: str | None = None,
) -> dict[str, str]:
    """Prepend one checkout's package root to a preserved child environment."""

    child = dict(os.environ if environment is None else environment)
    separator = os.pathsep if path_separator is None else path_separator
    package_entry = str(package_root.resolve())
    existing = child.get("PYTHONPATH")
    entries = existing.split(separator) if existing else []
    normalized_package = os.path.normcase(os.path.normpath(package_entry))
    retained = [
        entry
        for entry in entries
        if os.path.normcase(os.path.normpath(entry)) != normalized_package
    ]
    child["PYTHONPATH"] = separator.join((package_entry, *retained))
    return child


def package_root() -> Path:
    """Resolve the package parent when a child process actually needs it."""

    return Path(__file__).resolve().parents[2]


def run_example_asset_generator(
    example_dir: Path,
    *,
    check: bool = False,
    arguments: Sequence[str] = (),
) -> dict[str, Any] | None:
    """Run an example's optional deterministic asset-generation hook."""

    layout = project_layout(example_dir)
    generator = layout.asset_generator
    if not generator.is_file():
        if layout.manifest is not None:
            raise FileNotFoundError(
                f"configured SNES asset generator does not exist: {generator}"
            )
        return None
    command = [sys.executable, str(generator)]
    command.extend(arguments)
    if check:
        command.append("--check")
    result = run_checked(
        command,
        example_dir,
        echo_output=True,
        environment=python_child_environment(package_root()),
    )
    return {**result, "script": str(generator), "check": check}


def prepare_example_assets(
    example_dir: Path,
    *,
    skip_generation: bool = False,
    arguments: Sequence[str] = (),
) -> dict[str, Any] | None:
    """Generate assets, or explicitly record that existing outputs are reused."""

    if not skip_generation:
        return run_example_asset_generator(example_dir, arguments=arguments)
    layout = project_layout(example_dir)
    generator = layout.asset_generator
    if not generator.is_file():
        if layout.manifest is not None:
            raise FileNotFoundError(
                f"configured SNES asset generator does not exist: {generator}"
            )
        return None
    return {
        "script": str(generator),
        "skipped": True,
        "reason": "--skip-asset-generation",
        "elapsedSeconds": 0.0,
    }


def assembler_flags(libsfx_dir: Path) -> list[str]:
    include_dir = libsfx_dir / "include"
    config_include_dir = include_dir / "Configurations"
    return [
        "-D",
        "__STACKSIZE__=$100",
        "-D",
        "__ZPADSIZE__=$10",
        "-D",
        "__ZNMISIZE__=$10",
        "-D",
        "__RPADSIZE__=$100",
        "-D",
        "__DEBUG__=1",
        "-g",
        "-U",
        "-I",
        "./",
        "-I",
        str(include_dir),
        "-I",
        str(config_include_dir),
    ]


def assemble_libsfx(
    example_dir: Path,
    libsfx_dir: Path,
    flags: list[str],
    *,
    build_dir: Path | None = None,
) -> tuple[list[dict[str, Any]], list[Path]]:
    ca65 = require_cc65_tool(libsfx_dir, "ca65")
    include_dir = libsfx_dir / "include"
    build_dir = build_dir or project_layout(example_dir).libsfx_build_dir
    commands: list[dict[str, Any]] = []
    objects: list[Path] = []

    for source_name, object_name, extra_flags in LIBSFX_SOURCES:
        source = include_dir / source_name
        output = build_dir / object_name
        output.parent.mkdir(parents=True, exist_ok=True)
        commands.append(
            run_checked(
                [str(ca65), *flags, *extra_flags, "-o", str(output), str(source)],
                example_dir,
            )
        )
        objects.append(output)

    return commands, objects


def build_snes_example(
    example_dir: Path,
    libsfx_dir: Path,
    name: str,
    *,
    skip_asset_generation: bool = False,
    asset_generator_arguments: Sequence[str] = (),
) -> dict[str, Any]:
    started = time.monotonic()
    layout = project_layout(example_dir)
    asset_generation = prepare_example_assets(
        example_dir,
        skip_generation=skip_asset_generation,
        arguments=asset_generator_arguments,
    )
    build_dir = layout.build_dir
    build_dir.mkdir(parents=True, exist_ok=True)
    layout.output_dir.mkdir(parents=True, exist_ok=True)

    config_include_dir = libsfx_dir / "include" / "Configurations"
    flags = assembler_flags(libsfx_dir)
    gsu_source = example_dir / f"{name}.sgs"
    uses_gsu = gsu_source.is_file()
    special_register_lint = (
        validate_gsu_special_registers(
            gsu_source,
            include_dirs=(example_dir, libsfx_dir / "include", config_include_dir),
        )
        if uses_gsu
        else None
    )
    cpu_source = example_dir / f"{name}.s"
    fx3_opcode_lint = (
        validate_gsu_fx3_opcodes(
            gsu_source,
            include_dirs=(example_dir, libsfx_dir / "include", config_include_dir),
        )
        if uses_gsu and cpu_source.is_file() and source_targets_fx3(cpu_source)
        else None
    )

    ca65 = require_cc65_tool(libsfx_dir, "ca65")
    ld65 = require_cc65_tool(libsfx_dir, "ld65")

    commands, objects = assemble_libsfx(
        example_dir,
        libsfx_dir,
        flags,
        build_dir=layout.libsfx_build_dir,
    )

    cpu_object = build_dir / f"{name}.o"
    commands.append(
        run_checked(
            [str(ca65), *flags, "-o", str(cpu_object), f"{name}.s"], example_dir
        )
    )
    objects.append(cpu_object)
    if uses_gsu:
        gsu_object = build_dir / f"{name}.ogs"
        commands.append(
            run_checked(
                [
                    str(ca65),
                    *flags,
                    "-D",
                    "TARGET_GSU",
                    "-o",
                    str(gsu_object),
                    f"{name}.sgs",
                ],
                example_dir,
            )
        )
        objects.append(gsu_object)

    smp_source = example_dir / f"{name}.s700"
    uses_smp = smp_source.is_file()
    if uses_smp:
        smp_object = build_dir / f"{name}.o700"
        commands.append(
            run_checked(
                [
                    str(ca65),
                    *flags,
                    "-D",
                    "TARGET_SMP",
                    "-o",
                    str(smp_object),
                    smp_source.name,
                ],
                example_dir,
            )
        )
        objects.append(smp_object)

    commands.append(
        run_checked(
            [
                str(ld65),
                "--cfg-path",
                "./",
                "--cfg-path",
                str(config_include_dir),
                "-C",
                "Map.cfg",
                "-Ln",
                str(layout.output_dir / f"{name}.cpu.sym"),
                "-m",
                str(layout.output_dir / f"{name}.dmap"),
                "-vm",
                "--dbgfile",
                str(layout.output_dir / f"{name}.dnfo"),
                "-o",
                str(layout.output_dir / f"{name}.sfc"),
                *[str(path) for path in objects],
            ],
            example_dir,
        )
    )
    _normalize_ld65_labels(layout.output_dir / f"{name}.cpu.sym")

    rom_path = layout.output_dir / f"{name}.sfc"
    checksum = patch_snes_rom_checksum(
        rom_path,
        layout.output_dir / f"{name}.dnfo",
    )
    kernels = validate_cache_kernels(
        layout.output_dir / f"{name}.dnfo",
        segment_name=None,
        require=False,
    )
    manifest_path = layout.cache_kernel_manifest
    if kernels:
        validate_cache_manifest(kernels, manifest_path, segment_name=None)
    freshness = _write_snes_example_freshness(example_dir, libsfx_dir, name)
    return {
        "rom": str(rom_path),
        "romBytes": rom_path.stat().st_size,
        "romChecksum": checksum,
        "usesGsu": uses_gsu,
        "usesSmp": uses_smp,
        "assetGeneration": asset_generation,
        "commands": commands,
        "specialRegisterLint": (
            special_register_lint.to_dict() if special_register_lint else None
        ),
        "fx3OpcodeLint": fx3_opcode_lint.to_dict() if fx3_opcode_lint else None,
        "cacheKernels": [kernel.to_dict() for kernel in kernels],
        "cacheKernelManifest": str(manifest_path) if kernels else None,
        "freshnessReceipt": str(freshness),
        "elapsedSeconds": round(time.monotonic() - started, 3),
    }


def infer_example_name(example_dir: Path) -> str:
    makefile = example_dir / "Makefile"
    if not makefile.is_file():
        raise FileNotFoundError(f"example Makefile not found: {makefile}")
    matches = re.findall(
        r"^\s*name\s*:?=\s*([A-Za-z0-9_./\\-]+)\s*(?:#.*)?$",
        makefile.read_text(encoding="utf-8"),
        flags=re.MULTILINE,
    )
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one simple 'name :=' assignment in {makefile}, "
            f"found {len(matches)}"
        )
    return Path(matches[0].replace("\\", "/")).name


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build one libSFX SNES example deterministically."
    )
    parser.add_argument("example_dir", type=Path)
    parser.add_argument("--libsfx", type=Path, default=DEFAULT_LIBSFX)
    parser.add_argument("--name", help="override the Makefile's ROM name")
    parser.add_argument(
        "--skip-asset-generation",
        action="store_true",
        help=(
            "reuse existing generated assets for source-only iteration; "
            "omit this option for final acceptance builds"
        ),
    )
    parser.add_argument(
        "--asset-generator-argument",
        action="append",
        default=[],
        metavar="ARG",
        help="forward one repeatable argument to the example asset generator",
    )
    parser.add_argument("--json", action="store_true", help="print the build record")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    started = time.monotonic()
    args = parse_args(argv)
    try:
        example_dir = args.example_dir.resolve()
        libsfx_dir = args.libsfx.resolve()
        name = args.name or infer_example_name(example_dir)
        if not (example_dir / f"{name}.s").is_file():
            raise FileNotFoundError(
                f"example CPU source not found: {example_dir / f'{name}.s'}"
            )
        result = build_snes_example(
            example_dir,
            libsfx_dir,
            name,
            skip_asset_generation=args.skip_asset_generation,
            asset_generator_arguments=tuple(args.asset_generator_argument),
        )
    except KeyboardInterrupt:
        print(
            f"INTERRUPTED SNES example build after {time.monotonic() - started:.3f}s",
            file=sys.stderr,
        )
        return 130
    except (OSError, RuntimeError, ValueError) as error:
        print(
            f"ERROR SNES example build after "
            f"{time.monotonic() - started:.3f}s: {error}",
            file=sys.stderr,
        )
        return 2
    if args.json:
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(
            f"built {result['rom']} ({result['romBytes']} bytes, "
            f"gsu={str(result['usesGsu']).lower()}, "
            f"elapsed={result['elapsedSeconds']:.3f}s)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
