from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from ld65_debug import load_debug_records, parse_debug_int
from lint_gsu_fx3_opcodes import source_targets_fx3, validate_gsu_fx3_opcodes
from lint_gsu_special_registers import validate_gsu_special_registers
from validate_gsu_cache_kernels import (
    validate_cache_kernels,
    validate_cache_manifest,
)


LIBSFX_SOURCES = [
    ("CPU/Header.s", "CPU/Header.o", []),
    ("CPU/Library.s", "CPU/Library.o", []),
    ("CPU/Runtime.s", "CPU/Runtime.o", []),
    ("CPU/SMP.s", "CPU/SMP.o", []),
    ("SMP/System.s700", "SMP/System.o700", ["-D", "TARGET_SMP"]),
]
WORKSPACE = Path(__file__).resolve().parents[3]


def default_libsfx(workspace: Path) -> Path:
    """Resolve the canonical libSFX checkout for this workspace layout."""
    if (workspace / "libSFX").is_dir() and (
        workspace / "src/snes_quake"
    ).is_dir():
        return workspace / "libSFX"
    return workspace / "github/Optiroc/libSFX/master"


DEFAULT_LIBSFX = default_libsfx(WORKSPACE)
FRESHNESS_SCHEMA = "snes-example-build-freshness-v1"
SNES_HEADER_ROM_SIZE_OFFSET = 0x27
SNES_HEADER_COMPLEMENT_OFFSET = 0x2C
SNES_HEADER_CHECKSUM_OFFSET = 0x2E
SNES_HEADER_BYTES = 0x30


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
            f"HEADER segment at {header_offset} lies outside {rom} "
            f"({len(image)} bytes)"
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
    return example_dir / ".build" / f"{name}.freshness.json"


def _write_snes_example_freshness(
    example_dir: Path,
    libsfx_dir: Path,
    name: str,
) -> Path:
    ca65 = cc65_tool_path(libsfx_dir, "ca65")
    ld65 = cc65_tool_path(libsfx_dir, "ld65")
    outputs = {
        "rom": example_dir / f"{name}.sfc",
        "symbols": example_dir / f"{name}.cpu.sym",
        "map": example_dir / f"{name}.dmap",
        "debugInfo": example_dir / f"{name}.dnfo",
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
) -> dict[str, Any]:
    """Require an existing example build to match its assembler dependencies."""
    example_dir = example_dir.resolve()
    debug_info = example_dir / f"{name}.dnfo"
    outputs = {
        "rom": rom.resolve() if rom is not None else example_dir / f"{name}.sfc",
        "symbols": example_dir / f"{name}.cpu.sym",
        "map": example_dir / f"{name}.dmap",
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


def run_checked(command: list[str], cwd: Path) -> dict[str, Any]:
    started = time.monotonic()
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    elapsed = round(time.monotonic() - started, 3)
    if result.returncode:
        raise RuntimeError(
            f"command failed with exit {result.returncode}: {' '.join(command)}\n{result.stdout}"
        )
    return {"command": command[0], "elapsedSeconds": elapsed}


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
    example_dir: Path, libsfx_dir: Path, flags: list[str]
) -> tuple[list[dict[str, Any]], list[Path]]:
    ca65 = cc65_tool_path(libsfx_dir, "ca65")
    include_dir = libsfx_dir / "include"
    build_dir = example_dir / ".build_libsfx"
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
    example_dir: Path, libsfx_dir: Path, name: str
) -> dict[str, Any]:
    build_dir = example_dir / ".build"
    build_dir.mkdir(parents=True, exist_ok=True)

    ca65 = cc65_tool_path(libsfx_dir, "ca65")
    ld65 = cc65_tool_path(libsfx_dir, "ld65")
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

    commands, objects = assemble_libsfx(example_dir, libsfx_dir, flags)

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
                f"{name}.cpu.sym",
                "-m",
                f"{name}.dmap",
                "-vm",
                "--dbgfile",
                f"{name}.dnfo",
                "-o",
                f"{name}.sfc",
                *[str(path) for path in objects],
            ],
            example_dir,
        )
    )

    rom_path = example_dir / f"{name}.sfc"
    checksum = patch_snes_rom_checksum(
        rom_path,
        example_dir / f"{name}.dnfo",
    )
    kernels = validate_cache_kernels(
        example_dir / f"{name}.dnfo",
        segment_name=None,
        require=False,
    )
    manifest_path = example_dir / "GSUCacheKernels.json"
    if kernels:
        validate_cache_manifest(kernels, manifest_path, segment_name=None)
    freshness = _write_snes_example_freshness(example_dir, libsfx_dir, name)
    return {
        "rom": str(rom_path),
        "romBytes": rom_path.stat().st_size,
        "romChecksum": checksum,
        "usesGsu": uses_gsu,
        "commands": commands,
        "specialRegisterLint": (
            special_register_lint.to_dict() if special_register_lint else None
        ),
        "fx3OpcodeLint": fx3_opcode_lint.to_dict() if fx3_opcode_lint else None,
        "cacheKernels": [kernel.to_dict() for kernel in kernels],
        "cacheKernelManifest": str(manifest_path) if kernels else None,
        "freshnessReceipt": str(freshness),
    }


def infer_example_name(example_dir: Path) -> str:
    makefile = example_dir / "Makefile"
    if not makefile.is_file():
        raise FileNotFoundError(f"example Makefile not found: {makefile}")
    matches = re.findall(
        r"^\s*name\s*:?=\s*([A-Za-z0-9_]+)\s*(?:#.*)?$",
        makefile.read_text(encoding="utf-8"),
        flags=re.MULTILINE,
    )
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one simple 'name :=' assignment in {makefile}, "
            f"found {len(matches)}"
        )
    return matches[0]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build one libSFX SNES example deterministically."
    )
    parser.add_argument("example_dir", type=Path)
    parser.add_argument("--libsfx", type=Path, default=DEFAULT_LIBSFX)
    parser.add_argument("--name", help="override the Makefile's ROM name")
    parser.add_argument("--json", action="store_true", help="print the build record")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    example_dir = args.example_dir.resolve()
    libsfx_dir = args.libsfx.resolve()
    name = args.name or infer_example_name(example_dir)
    if not (example_dir / f"{name}.s").is_file():
        raise FileNotFoundError(
            f"example CPU source not found: {example_dir / f'{name}.s'}"
        )
    result = build_snes_example(example_dir, libsfx_dir, name)
    if args.json:
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(
            f"built {result['rom']} ({result['romBytes']} bytes, "
            f"gsu={str(result['usesGsu']).lower()})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
