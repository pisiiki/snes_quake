#!/usr/bin/env python3
"""Build the CMake/vcpkg C++23 SNES Quake reference renderer."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from workspace_paths import workspace_root
from typing import Sequence


EXAMPLE_DIR = workspace_root(__file__) / "src/snes_quake"
OUTPUT = EXAMPLE_DIR.parents[1] / "out/snes_quake"
WORKSPACE = EXAMPLE_DIR.parents[1]
BUILD_SCRIPT = Path(__file__).resolve()
APP_DIR = workspace_root(__file__) / "src/reference_renderer"
SOURCE = APP_DIR / "main.cpp"
CMAKE_PROJECT = APP_DIR / "CMakeLists.txt"
VCPKG_MANIFEST = APP_DIR / "vcpkg.json"
VCPKG_DIR = APP_DIR / "vcpkg"
VCPKG_BASELINE = "4e82e29f14eac2b3422f18f72c7524d04f19924e"
VCPKG_REPOSITORY = "https://github.com/microsoft/vcpkg.git"
BUILD_DIR = WORKSPACE / "out/reference_renderer/release"
BUILD_RECEIPT = BUILD_DIR / ".build-receipt.json"
BUILD_RECEIPT_SCHEMA = "quake-reference-renderer-build-v1"
EXECUTABLE = BUILD_DIR / (
    "quake_bsp_reference_renderer.exe"
    if os.name == "nt"
    else "quake_bsp_reference_renderer"
)


def _vswhere_candidates() -> tuple[Path, ...]:
    roots = tuple(
        Path(value)
        for name in ("ProgramFiles(x86)", "ProgramFiles")
        if (value := os.environ.get(name))
    )
    return tuple(
        root / "Microsoft Visual Studio/Installer/vswhere.exe" for root in roots
    )


def find_visual_studio() -> Path | None:
    for vswhere in _vswhere_candidates():
        if not vswhere.is_file():
            continue
        result = subprocess.run(
            [
                str(vswhere),
                "-latest",
                "-products",
                "*",
                "-requires",
                "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                "-property",
                "installationPath",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            return Path(result.stdout.strip().splitlines()[-1])
    return None


def _find_program(name: str, visual_studio_relative: str) -> Path:
    if resolved := shutil.which(name):
        return Path(resolved)
    installation = find_visual_studio()
    if installation is not None:
        candidate = installation / visual_studio_relative
        if candidate.is_file():
            return candidate
    raise RuntimeError(f"{name} was not found on PATH or in Visual Studio")


def find_cmake() -> Path:
    return _find_program(
        "cmake",
        "Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe",
    )


def find_ninja() -> Path:
    return _find_program(
        "ninja",
        "Common7/IDE/CommonExtensions/Microsoft/CMake/Ninja/ninja.exe",
    )


def visual_studio_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["VCPKG_DISABLE_METRICS"] = "1"
    if os.name != "nt":
        return environment
    installation = find_visual_studio()
    if installation is None:
        raise RuntimeError("Visual Studio C++ tools were not found")
    developer_shell = installation / "Common7/Tools/VsDevCmd.bat"
    if not developer_shell.is_file():
        raise RuntimeError(
            f"Visual Studio developer shell is missing: {developer_shell}"
        )
    result = subprocess.run(
        f'call "{developer_shell}" -no_logo -arch=x64 -host_arch=x64 >nul && set',
        shell=True,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"cannot initialize the Visual Studio environment:\n{result.stdout}"
        )
    for line in result.stdout.splitlines():
        if "=" in line:
            name, value = line.split("=", 1)
            environment[name] = value
    return environment


def _run(command: Sequence[str], *, cwd: Path, environment: dict[str, str]) -> str:
    result = subprocess.run(
        [str(value) for value in command],
        cwd=cwd,
        env=environment,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed with exit {result.returncode}:\n"
            f"  {' '.join(str(value) for value in command)}\n{result.stdout}"
        )
    return result.stdout


def ensure_vcpkg(environment: dict[str, str]) -> Path:
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("git is required to provision the app-local vcpkg checkout")
    fresh_checkout = not (VCPKG_DIR / ".git").is_dir()
    if fresh_checkout:
        VCPKG_DIR.mkdir(parents=True, exist_ok=True)
        _run([git, "init"], cwd=VCPKG_DIR, environment=environment)
        _run(
            [git, "remote", "add", "origin", VCPKG_REPOSITORY],
            cwd=VCPKG_DIR,
            environment=environment,
        )
    current = ""
    if not fresh_checkout:
        current = _run(
            [git, "rev-parse", "HEAD"], cwd=VCPKG_DIR, environment=environment
        ).strip()
    if current != VCPKG_BASELINE:
        _run(
            [git, "fetch", "--depth", "1", "origin", VCPKG_BASELINE],
            cwd=VCPKG_DIR,
            environment=environment,
        )
        _run(
            [git, "checkout", "--detach", "FETCH_HEAD"],
            cwd=VCPKG_DIR,
            environment=environment,
        )

    executable = VCPKG_DIR / ("vcpkg.exe" if os.name == "nt" else "vcpkg")
    if not executable.is_file():
        if os.name == "nt":
            _run(
                ["cmd.exe", "/d", "/c", "bootstrap-vcpkg.bat", "-disableMetrics"],
                cwd=VCPKG_DIR,
                environment=environment,
            )
        else:
            _run(
                ["sh", "bootstrap-vcpkg.sh", "-disableMetrics"],
                cwd=VCPKG_DIR,
                environment=environment,
            )
    return executable


def _build_inputs() -> tuple[Path, ...]:
    return (
        *sorted(APP_DIR.glob("*.cpp")),
        *sorted(APP_DIR.glob("*.hpp")),
        CMAKE_PROJECT,
        VCPKG_MANIFEST,
        APP_DIR / "CMakePresets.json",
        BUILD_SCRIPT,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _fingerprint(path: Path) -> dict[str, object]:
    return {
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _input_manifest(paths: Sequence[Path]) -> list[dict[str, object]]:
    resolved = tuple(path.resolve() for path in paths)
    common_parent = Path(os.path.commonpath([str(path.parent) for path in resolved]))
    records = []
    for path in resolved:
        records.append(
            {
                "path": path.relative_to(common_parent).as_posix(),
                **_fingerprint(path),
            }
        )
    return sorted(records, key=lambda record: str(record["path"]))


def _output_manifest(runtime: Path) -> dict[str, dict[str, object]]:
    outputs = {"executable": _fingerprint(EXECUTABLE)}
    if os.name == "nt":
        outputs["runtime"] = _fingerprint(runtime)
    return outputs


def _cached_build_is_current(inputs: list[dict[str, object]], runtime: Path) -> bool:
    if (
        not EXECUTABLE.is_file()
        or not BUILD_RECEIPT.is_file()
        or (os.name == "nt" and not runtime.is_file())
    ):
        return False
    try:
        receipt = json.loads(BUILD_RECEIPT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        receipt.get("schema") == BUILD_RECEIPT_SCHEMA
        and receipt.get("inputs") == inputs
        and receipt.get("outputs") == _output_manifest(runtime)
    )


def _write_build_receipt(inputs: list[dict[str, object]], runtime: Path) -> None:
    receipt = {
        "schema": BUILD_RECEIPT_SCHEMA,
        "inputs": inputs,
        "outputs": _output_manifest(runtime),
    }
    BUILD_RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    temporary = BUILD_RECEIPT.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    temporary.replace(BUILD_RECEIPT)


def build(*, force: bool = False) -> dict[str, object]:
    build_inputs = _build_inputs()
    missing = [path for path in build_inputs if not path.is_file()]
    if missing:
        raise RuntimeError(f"reference-renderer input is missing: {missing[0]}")
    input_manifest = _input_manifest(build_inputs)
    runtime = BUILD_DIR / ("SDL3.dll" if os.name == "nt" else "")
    if not force and _cached_build_is_current(input_manifest, runtime):
        return {
            "executable": str(EXECUTABLE),
            "buildReceipt": str(BUILD_RECEIPT),
            "rebuilt": False,
            "compiler": "cmake-vcpkg-cached",
            "elapsedSeconds": 0.0,
        }

    environment = visual_studio_environment()
    ensure_vcpkg(environment)
    cmake = find_cmake()
    ninja = find_ninja()
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    configure = [
        str(cmake),
        "--fresh",
        "-S",
        str(APP_DIR),
        "-B",
        str(BUILD_DIR),
        "-G",
        "Ninja",
        f"-DCMAKE_MAKE_PROGRAM={ninja}",
        "-DCMAKE_BUILD_TYPE=Release",
        f"-DCMAKE_TOOLCHAIN_FILE={VCPKG_DIR / 'scripts/buildsystems/vcpkg.cmake'}",
    ]
    if os.name == "nt":
        configure.append("-DVCPKG_TARGET_TRIPLET=x64-windows")

    started = time.perf_counter()
    _run(configure, cwd=APP_DIR, environment=environment)
    _run(
        [
            str(cmake),
            "--build",
            str(BUILD_DIR),
            "--config",
            "Release",
            "--target",
            "quake_bsp_reference_renderer",
        ],
        cwd=APP_DIR,
        environment=environment,
    )
    elapsed = time.perf_counter() - started
    if not EXECUTABLE.is_file():
        raise RuntimeError("CMake reported success without creating the executable")
    if os.name == "nt" and not runtime.is_file():
        raise RuntimeError(
            "CMake did not deploy the SDL3 runtime beside the executable"
        )
    ending_manifest = _input_manifest(build_inputs)
    if ending_manifest != input_manifest:
        raise RuntimeError("reference-renderer inputs changed during the build")
    _write_build_receipt(ending_manifest, runtime)
    return {
        "executable": str(EXECUTABLE),
        "buildReceipt": str(BUILD_RECEIPT),
        "rebuilt": True,
        "compiler": "cmake-ninja-vcpkg-c++23",
        "elapsedSeconds": round(elapsed, 6),
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--print-path", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = build(force=args.force)
    except RuntimeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2))
    elif args.print_path:
        print(result["executable"])
    else:
        state = "built" if result["rebuilt"] else "cached"
        print(
            f"reference renderer: {state} {result['executable']} "
            f"({result['compiler']}, {result['elapsedSeconds']:.3f}s)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
