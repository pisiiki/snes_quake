"""Provision and verify the pinned SNES workspace toolchain."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from snes_tooling.shared.snes_example_build import project_layout
from snes_tooling.workspace import Workspace, WorkspaceError


SCHEMA = "snes-clean-host-toolchain-v1"
ENVIRONMENT_RECEIPT_SCHEMA = "snes-python-environment-v1"
NATIVE_RECEIPT_SCHEMA = "snes-native-tool-v1"
QUALIFICATION_SCHEMA = "snes-clean-host-qualification-v1"
EXPECTED_LOCK_PINS = {
    "colorama": "0.4.6",
    "iniconfig": "2.1.0",
    "numpy": "2.3.5",
    "packaging": "25.0",
    "pillow": "12.0.0",
    "pip": "25.2",
    "pluggy": "1.5.0",
    "pygments": "2.19.2",
    "pytest": "8.4.2",
    "ruff": "0.12.0",
    "setuptools": "80.9.0",
    "wheel": "0.45.1",
}
EXPECTED_LOCK_PACKAGES = frozenset(EXPECTED_LOCK_PINS)
PORTABLE_PATH_PATTERN = re.compile(
    r"(?i)(?:\b[a-z]:[\\/][^\s`'\"<>|]*|/(?:home|Users)/[\w.-]+|\banaconda3\b)"
)
WORKSPACE_ONLY_SOURCE_PATTERN = re.compile(
    r'(?i)(?<![\w.-])src[\\/](?!(?:snes_quake|shared)(?:[\\/]|$|[\s`\'"<>|]))'
)
OPTIONAL_COMMANDS = ("bsdtar", "cmake", "ffmpeg", "make")
Runner = Callable[..., subprocess.CompletedProcess[str]]


class BootstrapError(RuntimeError):
    """Raised when the clean-host contract cannot be satisfied."""


@dataclass(frozen=True)
class ToolchainSpec:
    """Validated machine-readable toolchain contract."""

    path: Path
    document: dict[str, Any]

    def table(self, *keys: str) -> dict[str, Any]:
        value: Any = self.document
        for key in keys:
            if not isinstance(value, dict) or key not in value:
                raise BootstrapError(
                    f"{self.path.name} is missing table {'.'.join(keys)}; "
                    "restore it from the checkout"
                )
            value = value[key]
        if not isinstance(value, dict):
            raise BootstrapError(f"{self.path.name} {'.'.join(keys)} must be a table")
        return value

    def strings(self, *keys: str) -> tuple[str, ...]:
        table = self.table(*keys[:-1]) if len(keys) > 1 else self.document
        value = table.get(keys[-1])
        if not isinstance(value, list) or not all(
            isinstance(item, str) and item for item in value
        ):
            raise BootstrapError(
                f"{self.path.name} {'.'.join(keys)} must be a string array"
            )
        return tuple(value)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _fingerprint(path: Path) -> dict[str, object]:
    resolved = path.resolve()
    return {
        "path": str(resolved),
        "bytes": resolved.stat().st_size,
        "sha256": _sha256(resolved),
    }


def _write_json(path: Path, document: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return value if isinstance(value, dict) else None


def _tail(output: str, line_count: int = 20) -> str:
    lines = [line for line in output.splitlines() if line.strip()]
    return "\n".join(lines[-line_count:]) or "no output"


def _run(
    command: Sequence[str | Path],
    *,
    cwd: Path,
    runner: Runner = subprocess.run,
    environment: Mapping[str, str] | None = None,
    timeout: int = 1800,
) -> subprocess.CompletedProcess[str]:
    rendered = tuple(str(item) for item in command)
    try:
        result = runner(
            rendered,
            cwd=cwd,
            env=None if environment is None else dict(environment),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise BootstrapError(f"could not run {rendered[0]}: {error}") from error
    if result.returncode:
        detail = _tail((result.stdout or "") + "\n" + (result.stderr or ""))
        raise BootstrapError(
            f"command failed with exit {result.returncode}: {' '.join(rendered)}\n"
            f"{detail}"
        )
    return result


def load_spec(workspace: Workspace) -> ToolchainSpec:
    """Load and structurally validate the root toolchain contract."""

    path = workspace.path("toolchain.toml")
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise BootstrapError(
            f"missing {path}; restore toolchain.toml from the checkout"
        ) from error
    except tomllib.TOMLDecodeError as error:
        raise BootstrapError(f"invalid {path}: {error}") from error
    if document.get("schema") != SCHEMA:
        raise BootstrapError(
            f"unsupported {path.name} schema {document.get('schema')!r}; "
            f"expected {SCHEMA!r}"
        )
    spec = ToolchainSpec(path, document)
    spec.table("python")
    spec.table("workspace", "libsfx")
    spec.table("workspace", "mesen")
    spec.table("workspace", "vcpkg")
    spec.strings("workspace", "vcpkg", "packages")
    spec.strings("workspace", "vcpkg", "required_cmake_configs")
    spec.strings("workspace", "required_submodules")
    spec.strings("workspace", "optional_submodules")
    spec.strings("portability", "audited_files")
    return spec


def host_platform(
    *, sys_platform: str | None = None, machine: str | None = None
) -> str:
    """Return the supported manifest platform name or fail with recovery."""

    operating_system = sys.platform if sys_platform is None else sys_platform
    architecture = platform.machine() if machine is None else machine
    normalized = architecture.casefold()
    if normalized not in {"amd64", "x86_64"}:
        raise BootstrapError(
            f"unsupported host architecture {architecture!r}; use Windows or "
            "Linux/WSL x86-64 as declared by toolchain.toml"
        )
    if operating_system == "win32":
        return "windows-x86_64"
    if operating_system.startswith("linux"):
        return "linux-x86_64"
    raise BootstrapError(
        f"unsupported host platform {operating_system!r}; use Windows or "
        "Linux/WSL x86-64 as declared by toolchain.toml"
    )


def verify_environment_contract(
    workspace: Workspace,
    spec: ToolchainSpec,
    *,
    version_info: Sequence[int] | None = None,
) -> dict[str, object]:
    """Verify the Python spec, lock closure, hashes, and platform markers."""

    python = spec.table("python")
    expected_version = python.get("version")
    if expected_version != "3.13.9" or python.get("requires") != ">=3.13,<3.14":
        raise BootstrapError(
            "toolchain.toml must lock Python 3.13.9 and the >=3.13,<3.14 API range"
        )
    observed = tuple(sys.version_info[:3] if version_info is None else version_info[:3])
    if observed != (3, 13, 9):
        raise BootstrapError(
            f"unsupported bootstrap Python {'.'.join(map(str, observed))}; "
            "create environment.yml (Python 3.13.9) and rerun with that interpreter"
        )

    environment_path = workspace.path("environment.yml")
    environment_text = environment_path.read_text(encoding="utf-8")
    for required in ("python=3.13.9", "pip=25.2", "requirements-dev.lock"):
        if required not in environment_text:
            raise BootstrapError(
                f"{environment_path.name} is missing {required!r}; restore the "
                "locked environment specification"
            )

    lock_name = python.get("lock")
    if lock_name != "requirements-dev.lock":
        raise BootstrapError(
            "toolchain.toml python.lock must name requirements-dev.lock"
        )
    lock_path = workspace.path(lock_name)
    lock_text = lock_path.read_text(encoding="utf-8")
    locked = {
        match.group(1).casefold(): match.group(2)
        for match in re.finditer(r"(?m)^([A-Za-z0-9_.-]+)==([^\s;]+)", lock_text)
    }
    if locked != EXPECTED_LOCK_PINS:
        raise BootstrapError(
            "requirements-dev.lock package closure changed: "
            f"expected={EXPECTED_LOCK_PINS} observed={locked}; regenerate and review "
            "the complete cross-platform lock"
        )
    package_lines = re.split(r"(?m)(?=^[A-Za-z0-9_.-]+==)", lock_text)
    unhashed = [
        line.split("==", 1)[0]
        for line in package_lines
        if "==" in line and not re.search(r"--hash=sha256:[0-9a-f]{64}(?:\s|$)", line)
    ]
    if unhashed:
        raise BootstrapError(f"requirements-dev.lock has unhashed pins: {unhashed}")
    if 'sys_platform == "win32"' not in lock_text:
        raise BootstrapError("requirements-dev.lock is missing the Windows marker")
    for package in ("numpy", "pillow", "ruff"):
        section = next(
            line for line in package_lines if line.casefold().startswith(f"{package}==")
        )
        if len(re.findall(r"--hash=sha256:[0-9a-f]{64}", section)) != 2:
            raise BootstrapError(
                f"requirements-dev.lock {package} must hash Windows and Linux wheels"
            )
    return {
        "python": expected_version,
        "environment": str(environment_path),
        "environmentSha256": _sha256(environment_path),
        "lock": str(lock_path),
        "lockSha256": _sha256(lock_path),
        "packages": sorted(locked),
    }


def portability_violations(
    workspace: Workspace, spec: ToolchainSpec
) -> tuple[str, ...]:
    """Return undeclared developer-local paths in the primary setup surface."""

    portability = spec.table("portability")
    allowed = portability.get("allowed_windows_prefixes", [])
    if not isinstance(allowed, list) or not all(
        isinstance(item, str) for item in allowed
    ):
        raise BootstrapError("toolchain.toml portability prefixes must be strings")
    violations: list[str] = []
    for relative in spec.strings("portability", "audited_files"):
        path = workspace.root / relative
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as error:
            raise BootstrapError(
                f"cannot audit portability file {path}: {error}"
            ) from error
        for line_number, line in enumerate(lines, start=1):
            for match in PORTABLE_PATH_PATTERN.finditer(line):
                token = match.group(0)
                if any(
                    token.casefold().startswith(item.casefold()) for item in allowed
                ):
                    continue
                violations.append(f"{relative}:{line_number}:{token}")
    return tuple(violations)


def verify_portability(workspace: Workspace, spec: ToolchainSpec) -> dict[str, object]:
    violations = portability_violations(workspace, spec)
    if violations:
        raise BootstrapError(
            "undeclared developer-local paths found: "
            + ", ".join(violations)
            + "; replace them with workspace-relative discovery or an explicit override"
        )
    return {"auditedFiles": list(spec.strings("portability", "audited_files"))}


def _resolve_command(
    name: str,
    explicit: str | Path | None = None,
    *,
    which: Callable[[str], str | None] = shutil.which,
) -> Path:
    requested = str(explicit) if explicit is not None else name
    direct = Path(requested).expanduser()
    if direct.is_file():
        return direct.resolve()
    found = which(requested)
    if found:
        return Path(found).resolve()
    override = f"SNES_{name.upper().replace('.', '_')}"
    raise BootstrapError(
        f"required command {name!r} was not found; install it or pass its path "
        f"explicitly (environment override {override})"
    )


def find_msbuild(
    explicit: str | Path | None = None,
    *,
    which: Callable[[str], str | None] = shutil.which,
    runner: Runner = subprocess.run,
    environ: Mapping[str, str] = os.environ,
) -> Path:
    """Find Visual Studio MSBuild without an interactive PATH assumption."""

    if explicit is not None:
        return _resolve_command("msbuild.exe", explicit, which=which)
    path_match = which("msbuild.exe")
    if path_match:
        return Path(path_match).resolve()
    roots = tuple(
        Path(value) / "Microsoft Visual Studio/Installer/vswhere.exe"
        for key in ("ProgramFiles", "ProgramFiles(x86)")
        if (value := environ.get(key))
    )
    for vswhere in roots:
        if not vswhere.is_file():
            continue
        result = runner(
            (
                str(vswhere),
                "-latest",
                "-products",
                "*",
                "-requires",
                "Microsoft.Component.MSBuild",
                "-find",
                r"MSBuild\**\Bin\MSBuild.exe",
            ),
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                candidate = Path(line.strip())
                if candidate.is_file():
                    return candidate.resolve()
    raise BootstrapError(
        "Visual Studio MSBuild is required to build pinned cc65 and MesenCE; "
        "install the Desktop development with C++ workload or pass --msbuild"
    )


def find_cmake(
    explicit: str | Path | None = None,
    *,
    which: Callable[[str], str | None] = shutil.which,
    environ: Mapping[str, str] = os.environ,
) -> Path:
    """Find CMake on PATH or inside Visual Studio without a drive assumption."""

    if explicit is not None:
        return _resolve_command("cmake", explicit, which=which)
    if path_match := which("cmake"):
        return Path(path_match).resolve()
    candidates = tuple(
        sorted(
            (
                path
                for key in ("ProgramFiles", "ProgramFiles(x86)")
                if (value := environ.get(key))
                for path in (Path(value) / "Microsoft Visual Studio").glob(
                    "*/*/Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe"
                )
            ),
            reverse=True,
        )
    )
    if candidates:
        return candidates[0].resolve()
    raise BootstrapError(
        "CMake is required to reproduce the configured Quake BSP; install it "
        "or pass --cmake / set SNES_CMAKE before provisioning"
    )


def _msvc_toolset(msbuild: Path) -> str | None:
    try:
        installation = msbuild.parents[3]
    except IndexError:
        return None
    roots = installation.glob(
        "MSBuild/Microsoft/VC/v*/Platforms/x64/PlatformToolsets/v*"
    )
    names = sorted(
        (path.name for path in roots if re.fullmatch(r"v\d+", path.name)),
        key=lambda value: int(value[1:]),
    )
    return names[-1] if names else None


def _git_head(path: Path, git: Path, runner: Runner) -> str:
    return _run(
        (git, "-C", path, "rev-parse", "HEAD"), cwd=path, runner=runner
    ).stdout.strip()


def submodule_state(
    workspace: Workspace,
    relative: str,
    git: Path,
    *,
    runner: Runner = subprocess.run,
) -> dict[str, str]:
    result = _run(
        (git, "-C", workspace.root, "submodule", "status", "--", relative),
        cwd=workspace.root,
        runner=runner,
    )
    line = result.stdout.rstrip("\r\n")
    if not line:
        raise BootstrapError(
            f"{relative} is not a declared submodule; restore .gitmodules and the gitlink"
        )
    marker = line[0]
    fields = line[1:].split()
    if len(fields) < 2:
        raise BootstrapError(f"could not parse submodule status for {relative}: {line}")
    states = {" ": "current", "-": "missing", "+": "stale", "U": "conflict"}
    return {
        "path": relative,
        "commit": fields[0],
        "state": states.get(marker, "unknown"),
    }


def ensure_submodule(
    workspace: Workspace,
    relative: str,
    git: Path,
    *,
    provision: bool,
    runner: Runner = subprocess.run,
) -> dict[str, str]:
    state = submodule_state(workspace, relative, git, runner=runner)
    if state["state"] != "current" and provision:
        _run(
            (
                git,
                "-C",
                workspace.root,
                "submodule",
                "update",
                "--init",
                "--",
                relative,
            ),
            cwd=workspace.root,
            runner=runner,
        )
        state = submodule_state(workspace, relative, git, runner=runner)
    if state["state"] != "current":
        raise BootstrapError(
            f"required submodule {relative} is {state['state']}; rerun "
            "bootstrap_workspace.py --provision to restore its pinned gitlink"
        )
    return state


def _ensure_nested_cc65(
    libsfx: Path,
    git: Path,
    *,
    provision: bool,
    runner: Runner,
) -> str:
    result = _run(
        (git, "-C", libsfx, "submodule", "status", "--", "tools/cc65"),
        cwd=libsfx,
        runner=runner,
    )
    line = result.stdout.rstrip("\r\n")
    marker = line[0] if line else "?"
    if marker != " " and provision:
        _run(
            (git, "-C", libsfx, "submodule", "update", "--init", "--", "tools/cc65"),
            cwd=libsfx,
            runner=runner,
        )
        result = _run(
            (git, "-C", libsfx, "submodule", "status", "--", "tools/cc65"),
            cwd=libsfx,
            runner=runner,
        )
        line = result.stdout.rstrip("\r\n")
        marker = line[0] if line else "?"
    if marker != " ":
        state = {"-": "missing", "+": "stale", "U": "conflict"}.get(marker, "unknown")
        raise BootstrapError(
            f"pinned libSFX tools/cc65 submodule is {state}; rerun "
            "bootstrap_workspace.py --provision"
        )
    return line[1:].split()[0]


def _native_receipt(workspace: Workspace, name: str) -> Path:
    return workspace.path("tmp", "toolchain", "receipts", f"{name}.json")


def _receipt_matches(
    path: Path,
    *,
    source: Path,
    commit: str,
    outputs: Sequence[Path],
) -> bool:
    receipt = _read_json(path)
    if receipt is None or receipt.get("schema") != NATIVE_RECEIPT_SCHEMA:
        return False
    if (
        receipt.get("source") != str(source.resolve())
        or receipt.get("commit") != commit
    ):
        return False
    recorded = receipt.get("outputs")
    if not isinstance(recorded, list) or len(recorded) != len(outputs):
        return False
    try:
        current = [_fingerprint(output) for output in outputs]
    except OSError:
        return False
    return recorded == current


def _write_native_receipt(
    path: Path,
    *,
    name: str,
    source: Path,
    commit: str,
    outputs: Sequence[Path],
    command: Sequence[str | Path],
) -> None:
    _write_json(
        path,
        {
            "schema": NATIVE_RECEIPT_SCHEMA,
            "name": name,
            "source": str(source.resolve()),
            "commit": commit,
            "outputs": [_fingerprint(output) for output in outputs],
            "command": [str(item) for item in command],
        },
    )


def ensure_libsfx(
    workspace: Workspace,
    spec: ToolchainSpec,
    git: Path,
    *,
    platform_name: str,
    provision: bool,
    override: Path | None = None,
    msbuild_override: str | Path | None = None,
    make_override: str | Path | None = None,
    runner: Runner = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
) -> dict[str, object]:
    """Resolve pinned libSFX and provision its pinned cc65 host tools."""

    table = spec.table("workspace", "libsfx")
    local = workspace.root / str(table["path"])
    explicit = override is not None
    libsfx = override.expanduser().resolve() if explicit else local
    if not explicit:
        ensure_submodule(
            workspace, str(table["path"]), git, provision=provision, runner=runner
        )
    header = libsfx / str(table["header"])
    if not header.is_file():
        raise BootstrapError(
            f"libSFX header is missing: {header}; initialize the pinned submodule "
            "or pass --libsfx with a complete checkout"
        )
    cc65_commit = _ensure_nested_cc65(libsfx, git, provision=provision, runner=runner)
    suffix = "windows" if platform_name == "windows-x86_64" else "linux"
    outputs = (
        libsfx / str(table[f"assembler_{suffix}"]),
        libsfx / str(table[f"linker_{suffix}"]),
    )
    cc65 = libsfx / str(table["cc65_submodule"])
    receipt = _native_receipt(workspace, "cc65")
    current = all(path.is_file() for path in outputs) and (
        explicit
        or _receipt_matches(receipt, source=cc65, commit=cc65_commit, outputs=outputs)
    )
    command: list[str | Path] = []
    if not current and provision:
        if platform_name == "windows-x86_64":
            msbuild = find_msbuild(
                msbuild_override, which=which, runner=runner, environ=os.environ
            )
            solution = cc65 / "src/cc65.sln"
            if not solution.is_file():
                raise BootstrapError(
                    f"pinned cc65 Visual Studio solution is missing: {solution}"
                )
            command = [
                msbuild,
                solution,
                "/m",
                "/t:ca65;ld65",
                "/p:Configuration=Release",
                "/p:Platform=x64",
                "/verbosity:minimal",
                "/nologo",
            ]
            if toolset := _msvc_toolset(msbuild):
                command.append(f"/p:PlatformToolset={toolset}")
        else:
            make = _resolve_command("make", make_override, which=which)
            command = [
                make,
                "-C",
                cc65,
                "bin",
                "-j",
                str(max(1, os.cpu_count() or 1)),
            ]
        _run(command, cwd=cc65, runner=runner)
        if not all(path.is_file() for path in outputs):
            raise BootstrapError(
                "pinned cc65 build completed without ca65/ld65; inspect its build "
                "output and rerun bootstrap_workspace.py --provision"
            )
        if not explicit:
            _write_native_receipt(
                receipt,
                name="cc65",
                source=cc65,
                commit=cc65_commit,
                outputs=outputs,
                command=command,
            )
        current = True
    if not current:
        missing = [str(path) for path in outputs if not path.is_file()]
        reason = f"missing {missing}" if missing else "missing or stale build receipt"
        raise BootstrapError(
            f"pinned cc65 is not current ({reason}); rerun "
            "bootstrap_workspace.py --provision"
        )
    for output in outputs:
        _run((output, "--version"), cwd=workspace.root, runner=runner, timeout=30)
    return {
        "path": str(libsfx),
        "override": explicit,
        "cc65Commit": cc65_commit,
        "tools": [_fingerprint(path) for path in outputs],
        "receipt": None if explicit else str(receipt),
    }


def ensure_mesen(
    workspace: Workspace,
    spec: ToolchainSpec,
    git: Path,
    environment_python: Path,
    *,
    platform_name: str,
    provision: bool,
    override: Path | None = None,
    msbuild_override: str | Path | None = None,
    runner: Runner = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
) -> dict[str, object]:
    """Resolve or build the pinned instrumented Mesen target."""

    table = spec.table("workspace", "mesen")
    relative = str(table["path"])
    if platform_name != "windows-x86_64":
        if override is not None:
            raise BootstrapError(
                "--mesen is only supported by the Windows workspace gate"
            )
        ensure_submodule(workspace, relative, git, provision=provision, runner=runner)
        return {
            "status": "not-applicable",
            "reason": "workspace Mesen qualification is Windows-only; Linux/WSL release boundary remains supported",
        }

    explicit = override is not None
    source = workspace.root / relative
    if not explicit:
        ensure_submodule(workspace, relative, git, provision=provision, runner=runner)
    executable = (
        override.expanduser().resolve()
        if explicit
        else source / str(table["executable_windows"])
    )
    output_root = executable.parent
    companions = tuple(
        output_root / Path(str(relative_path)).name
        for relative_path in table["companions_windows"]
    )
    outputs = (executable, *companions)
    if explicit:
        missing = [str(path) for path in outputs if not path.is_file()]
        if missing:
            raise BootstrapError(
                f"explicit Mesen override is incomplete: {missing}; pass the canonical "
                "instrumented Mesen.exe"
            )
        return {
            "path": str(executable),
            "override": True,
            "outputs": [_fingerprint(path) for path in outputs],
        }

    commit = _git_head(source, git, runner)
    receipt = _native_receipt(workspace, "mesen")
    current = _receipt_matches(receipt, source=source, commit=commit, outputs=outputs)
    command: list[str | Path] = []
    if not current and provision:
        msbuild = find_msbuild(
            msbuild_override, which=which, runner=runner, environ=os.environ
        )
        build_script = workspace.shared_tools / "build_mesen.py"
        log = workspace.path("tmp", "validation", "ticket558", "mesen-build.log")
        command = [
            environment_python,
            build_script,
            "--source",
            source,
            "--msbuild",
            msbuild,
            "--log",
            log,
        ]
        _run(command, cwd=workspace.root, runner=runner, timeout=3600)
        missing = [str(path) for path in outputs if not path.is_file()]
        if missing:
            raise BootstrapError(
                f"Mesen build completed without required runtime files {missing}; "
                f"inspect {log}"
            )
        _write_native_receipt(
            receipt,
            name="mesen",
            source=source,
            commit=commit,
            outputs=outputs,
            command=command,
        )
        current = True
    if not current:
        raise BootstrapError(
            "instrumented Mesen is missing or stale relative to its pinned source; "
            "rerun bootstrap_workspace.py --provision to rebuild and bind it"
        )
    return {
        "path": str(executable),
        "override": False,
        "commit": commit,
        "protocol": table["protocol"],
        "capabilities": table["capabilities"],
        "outputs": [_fingerprint(path) for path in outputs],
        "receipt": str(receipt),
    }


def ensure_vcpkg(
    workspace: Workspace,
    spec: ToolchainSpec,
    git: Path,
    *,
    platform_name: str,
    provision: bool,
    override: Path | None = None,
    runner: Runner = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
    environ: Mapping[str, str] = os.environ,
) -> dict[str, object]:
    """Resolve vcpkg and provision the pinned Quake native dependency closure."""

    table = spec.table("workspace", "vcpkg")
    explicit = override is not None
    root = (
        override.expanduser().resolve()
        if explicit
        else workspace.root / str(table["path"])
    )
    if not explicit:
        ensure_submodule(
            workspace, str(table["path"]), git, provision=provision, runner=runner
        )
    suffix = "windows" if platform_name == "windows-x86_64" else "linux"
    executable = root / str(table[f"executable_{suffix}"])
    toolchain = root / str(table["toolchain"])
    bootstrap_script = root / str(table[f"bootstrap_{suffix}"])
    triplet = table.get(f"triplet_{suffix}")
    if not isinstance(triplet, str) or not triplet:
        raise BootstrapError(
            f"toolchain.toml workspace.vcpkg.triplet_{suffix} must be a string"
        )
    packages = spec.strings("workspace", "vcpkg", "packages")
    config_paths = tuple(
        root / "installed" / triplet / relative
        for relative in spec.strings("workspace", "vcpkg", "required_cmake_configs")
    )
    if not toolchain.is_file() or not bootstrap_script.is_file():
        raise BootstrapError(
            f"vcpkg checkout is incomplete at {root}; initialize its pinned "
            "submodule or pass --vcpkg with a complete checkout"
        )
    commit = "explicit-override" if explicit else _git_head(root, git, runner)
    receipt = _native_receipt(workspace, "vcpkg")
    outputs = (executable, toolchain, *config_paths)
    current = all(path.is_file() for path in outputs) and (
        explicit
        or _receipt_matches(receipt, source=root, commit=commit, outputs=outputs)
    )
    if not current and provision:
        if not explicit or not executable.is_file():
            if platform_name == "windows-x86_64":
                command_shell = _resolve_command(
                    "cmd.exe", environ.get("COMSPEC"), which=which
                )
                bootstrap_command: list[str | Path] = [
                    command_shell,
                    "/d",
                    "/c",
                    bootstrap_script,
                    "-disableMetrics",
                ]
            else:
                shell = _resolve_command("sh", which=which)
                bootstrap_command = [shell, bootstrap_script, "-disableMetrics"]
            _run(bootstrap_command, cwd=root, runner=runner, timeout=1800)
        if not executable.is_file():
            raise BootstrapError(
                f"vcpkg bootstrap completed without {executable}; inspect its "
                "output and rerun bootstrap_workspace.py --provision"
            )
        install_command: list[str | Path] = [
            executable,
            "install",
            *packages,
            "--triplet",
            triplet,
            "--disable-metrics",
        ]
        _run(install_command, cwd=root, runner=runner, timeout=7200)
        missing = [str(path) for path in outputs if not path.is_file()]
        if missing:
            raise BootstrapError(
                "vcpkg dependency installation completed without the declared "
                f"Quake closure {missing}; inspect the install output"
            )
        if not explicit:
            _write_native_receipt(
                receipt,
                name="vcpkg",
                source=root,
                commit=commit,
                outputs=outputs,
                command=install_command,
            )
        current = True
    if not current:
        missing = [str(path) for path in outputs if not path.is_file()]
        detail = f"; missing dependency files: {missing}" if missing else ""
        raise BootstrapError(
            "pinned vcpkg dependency closure is missing or stale; rerun "
            "bootstrap_workspace.py --provision before configured Quake "
            f"qualification{detail}"
        )
    _run((executable, "version"), cwd=root, runner=runner, timeout=60)
    return {
        "path": str(root),
        "override": explicit,
        "commit": commit,
        "triplet": triplet,
        "packages": list(packages),
        "executable": _fingerprint(executable),
        "toolchain": _fingerprint(toolchain),
        "dependencyConfigs": [_fingerprint(path) for path in config_paths],
        "receipt": None if explicit else str(receipt),
    }


def _environment_python(environment: Path, platform_name: str) -> Path:
    relative = (
        Path("Scripts/python.exe")
        if platform_name == "windows-x86_64"
        else Path("bin/python")
    )
    return environment / relative


def _environment_console(environment: Path, platform_name: str) -> Path:
    relative = (
        Path("Scripts/snes-workspace-bootstrap.exe")
        if platform_name == "windows-x86_64"
        else Path("bin/snes-workspace-bootstrap")
    )
    return environment / relative


def ensure_python_environment(
    workspace: Workspace,
    spec: ToolchainSpec,
    *,
    platform_name: str,
    provision: bool,
    override: Path | None = None,
    runner: Runner = subprocess.run,
) -> dict[str, object]:
    """Create/check only the explicitly workspace-owned Python environment."""

    python_table = spec.table("python")
    environment = (
        override.expanduser().resolve()
        if override is not None
        else (workspace.root / str(python_table["environment"])).resolve()
    )
    if environment == Path(sys.base_prefix).resolve() or environment == workspace.root:
        raise BootstrapError(
            f"refusing to mutate unrelated/base environment {environment}; choose an "
            "empty workspace-owned --environment directory"
        )
    receipt_path = environment / ".snes-bootstrap.json"
    receipt = _read_json(receipt_path)
    python = _environment_python(environment, platform_name)
    lock = workspace.root / str(python_table["lock"])
    desired = {
        "schema": ENVIRONMENT_RECEIPT_SCHEMA,
        "workspace": str(workspace.root),
        "pythonVersion": python_table["version"],
        "lockSha256": _sha256(lock),
        "pyprojectSha256": _sha256(workspace.path("pyproject.toml")),
    }
    if environment.exists() and receipt is None:
        raise BootstrapError(
            f"environment directory already exists without an ownership receipt: "
            f"{environment}; move it aside or choose a new --environment path"
        )
    if not environment.exists():
        if not provision:
            raise BootstrapError(
                f"workspace environment is missing: {environment}; rerun "
                "bootstrap_workspace.py --provision"
            )
        environment.parent.mkdir(parents=True, exist_ok=True)
        _run(
            (sys.executable, "-m", "venv", environment),
            cwd=workspace.root,
            runner=runner,
        )
        _write_json(receipt_path, {**desired, "state": "created"})
        receipt = _read_json(receipt_path)
    current = (
        receipt is not None
        and all(receipt.get(key) == value for key, value in desired.items())
        and receipt.get("state") == "ready"
    )
    if not current and provision:
        if not python.is_file():
            raise BootstrapError(
                f"owned environment has no interpreter: {python}; choose a new empty "
                "--environment path and provision again"
            )
        _run(
            (
                python,
                "-m",
                "pip",
                "install",
                "--require-hashes",
                "--only-binary=:all:",
                "-r",
                lock,
            ),
            cwd=workspace.root,
            runner=runner,
        )
        _run(
            (
                python,
                "-m",
                "pip",
                "install",
                "--no-deps",
                "--no-build-isolation",
                "--editable",
                workspace.root,
            ),
            cwd=workspace.root,
            runner=runner,
        )
        _write_json(receipt_path, {**desired, "state": "ready"})
        current = True
    if not current:
        raise BootstrapError(
            f"workspace environment is stale: {environment}; rerun "
            "bootstrap_workspace.py --provision to apply the locked dependencies"
        )
    _run((python, "-m", "pip", "check"), cwd=workspace.root, runner=runner)
    _run(
        (
            python,
            "-c",
            "import importlib.metadata, snes_tooling; "
            "assert importlib.metadata.version('snes-tooling') == '0.1.0'",
        ),
        cwd=workspace.root,
        runner=runner,
    )
    console = _environment_console(environment, platform_name)
    if not console.is_file():
        raise BootstrapError(
            f"installed bootstrap console is missing: {console}; rerun --provision"
        )
    _run((console, "--help"), cwd=workspace.root, runner=runner, timeout=60)
    return {
        "path": str(environment),
        "python": _fingerprint(python),
        "console": str(console),
        "receipt": str(receipt_path),
    }


def optional_tools(
    *, which: Callable[[str], str | None] = shutil.which
) -> list[dict[str, object]]:
    """Report optional utilities without turning their absence into failure."""

    return [
        {"name": name, "available": bool(path := which(name)), "path": path}
        for name in OPTIONAL_COMMANDS
    ]


def verify_release_boundary(
    release_root: Path,
    spec: ToolchainSpec,
    platform_name: str,
    *,
    check_commands: bool = True,
    which: Callable[[str], str | None] = shutil.which,
) -> dict[str, object]:
    """Verify one standalone release's closed Windows or Linux dependency set."""

    key = {"windows": "windows", "linux": "linux"}.get(platform_name)
    if key is None:
        raise BootstrapError("release platform must be 'windows' or 'linux'")
    root = release_root.expanduser().resolve()
    if not (root / "third_party/libSFX").is_dir() or not (root / "src/snes_quake").is_dir():
        raise BootstrapError(
            f"release root {root} lacks third_party/libSFX + src/snes_quake; generate the "
            "standalone release before checking its dependency boundary"
        )
    table = spec.table("release", key)
    required_files = table.get("required_files")
    required_commands = table.get("required_commands")
    if not isinstance(required_files, list) or not isinstance(required_commands, list):
        raise BootstrapError(f"toolchain.toml release.{key} contract is malformed")
    missing = [
        relative for relative in required_files if not (root / relative).is_file()
    ]
    if missing:
        raise BootstrapError(
            f"standalone {key} release is missing owned dependencies {missing}; "
            "regenerate the release rather than borrowing workspace files"
        )
    leaked: list[str] = []
    local_paths: list[str] = []
    for relative in ("build.ps1", "build.sh", "src/snes_quake/Makefile"):
        path = root / relative
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if (
            "examples/" in text
            or WORKSPACE_ONLY_SOURCE_PATTERN.search(text)
            or "../../github/" in text
            or any(not (root / target).is_file() for target in re.findall(
                r"tools/snes_tooling(?:_cli\.py|/[A-Za-z0-9_./-]+\.py)", text
            ))
        ):
            leaked.append(relative)
        if PORTABLE_PATH_PATTERN.search(text):
            local_paths.append(relative)
    if leaked:
        raise BootstrapError(
            f"standalone {key} release references excluded workspace files: {leaked}"
        )
    if local_paths:
        raise BootstrapError(
            f"standalone {key} release contains developer-local paths: {local_paths}; "
            "regenerate it with portable command discovery and explicit overrides"
        )
    commands = []
    for name in required_commands:
        resolved = which(str(name)) if check_commands else None
        if check_commands and not resolved:
            raise BootstrapError(
                f"standalone {key} release requires {name!r}; install it or use the "
                f"documented {key} build host before running the build script"
            )
        commands.append({"name": name, "path": resolved, "checked": check_commands})
    return {
        "platform": key,
        "root": str(root),
        "ownedFiles": list(required_files),
        "commands": commands,
        "workspaceLeakage": [],
    }


def _source_state(workspace: Workspace, git: Path, runner: Runner) -> dict[str, object]:
    commit = _git_head(workspace.root, git, runner)
    status = _run(
        (git, "-C", workspace.root, "status", "--porcelain", "--untracked-files=no"),
        cwd=workspace.root,
        runner=runner,
    ).stdout.splitlines()
    return {"commit": commit, "trackedChanges": status, "clean": not status}


def qualify_workspace(
    workspace: Workspace,
    spec: ToolchainSpec,
    environment: Mapping[str, object],
    libsfx: Mapping[str, object],
    mesen: Mapping[str, object],
    git: Path,
    *,
    report: Path,
    pak: Path,
    runner: Runner = subprocess.run,
) -> dict[str, object]:
    """Build both ROMs and probe canonical Mesen from the owned environment."""

    started = time.monotonic()
    source = _source_state(workspace, git, runner)
    if not source["clean"]:
        raise BootstrapError(
            "clean-host qualification requires no tracked changes; commit the ticket "
            "implementation before running --qualify"
        )
    python = Path(str(environment["path"])) / (
        "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
    )
    libsfx_path = Path(str(libsfx["path"]))
    mesen_path = mesen.get("path")
    if not isinstance(mesen_path, str):
        raise BootstrapError(
            "workspace qualification requires the Windows instrumented Mesen target"
        )
    qualification = spec.table("workspace", "qualification")
    small_example = workspace.root / str(qualification["small_example"])
    small_name = str(qualification["small_rom_name"])
    quake_rom = workspace.root / str(qualification["playable_rom"])
    commands: list[dict[str, object]] = []

    def run_record(
        command: Sequence[str | Path],
        timeout: int = 1800,
        *,
        cwd: Path | None = None,
    ) -> None:
        command_started = time.monotonic()
        result = _run(
            command,
            cwd=workspace.root if cwd is None else cwd,
            runner=runner,
            timeout=timeout,
        )
        commands.append(
            {
                "command": [str(item) for item in command],
                "elapsedSeconds": round(time.monotonic() - command_started, 3),
                "outputTail": _tail(result.stdout or "", 5),
            }
        )

    with tempfile.TemporaryDirectory(prefix="snes-bootstrap-smoke-") as temporary:
        unrelated = Path(temporary)
        run_record(
            (
                python,
                "-c",
                "import importlib.metadata, snes_tooling; "
                "print(importlib.metadata.version('snes-tooling'))",
            ),
            timeout=60,
            cwd=unrelated,
        )
        commands[-1]["unrelatedCwd"] = temporary
        run_record(
            (environment["console"], "--help"),
            timeout=60,
            cwd=unrelated,
        )
        commands[-1]["unrelatedCwd"] = temporary
    run_record(
        (
            python,
            "-m",
            "snes_tooling.shared.snes_example_build",
            small_example,
            "--libsfx",
            libsfx_path,
            "--name",
            small_name,
            "--json",
        )
    )
    small_rom = project_layout(small_example).output_dir / f"{small_name}.sfc"
    run_record(
        (
            python,
            workspace.shared_tools / "probe_mesen_sessions.py",
            small_rom,
            "--mesen",
            mesen_path,
            "--sessions",
            "2",
            "--frames",
            "2",
            "--json",
        ),
        timeout=300,
    )
    run_record((python, workspace.quake_tools / "build_quake_project.py", "--libsfx", libsfx_path,
                "--pak", pak), timeout=7200)
    from snes_tooling.quake.quakec_powerups import ARTIFACT_TRACKS
    audio = [quake_rom.with_name(f"{quake_rom.stem}-{track}.pcm") for track in sorted(ARTIFACT_TRACKS)]
    document: dict[str, object] = {
        "schema": QUALIFICATION_SCHEMA,
        "status": "pass",
        "source": source,
        "scope": "Windows clean checkout: package, assets, FX3 ROM, Quake ROM, Mesen",
        "inputs": {
            "environmentLock": _fingerprint(workspace.path("requirements-dev.lock")),
            "toolchain": _fingerprint(workspace.path("toolchain.toml")),
            "sourcePak": _fingerprint(pak),
        },
        "outputs": {
            "smallRom": _fingerprint(small_rom),
            "quakeRom": _fingerprint(quake_rom),
            "quakeMsu": _fingerprint(quake_rom.with_suffix(".msu")),
            "quakeAudio": [_fingerprint(track) for track in audio],
        },
        "commands": commands,
        "elapsedSeconds": round(time.monotonic() - started, 3),
    }
    _write_json(report.resolve(), document)
    digest = _sha256(report.resolve())
    report.with_suffix(report.suffix + ".sha256").write_text(
        f"{digest}  {report.name}\n", encoding="utf-8"
    )
    return {**document, "report": str(report.resolve()), "reportSha256": digest}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--environment", type=Path)
    parser.add_argument("--libsfx", type=Path)
    parser.add_argument("--mesen", type=Path)
    parser.add_argument("--git")
    parser.add_argument("--msbuild")
    parser.add_argument("--make")
    parser.add_argument("--pak", type=Path)
    parser.add_argument("--provision", action="store_true")
    parser.add_argument("--qualify", action="store_true")
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("tmp/validation/ticket558/clean-host-qualification.json"),
    )
    parser.add_argument("--release-root", type=Path)
    parser.add_argument(
        "--release-platform", choices=("windows", "linux", "both"), default="both"
    )
    parser.add_argument(
        "--static-release",
        action="store_true",
        help="validate release closure without requiring foreign-host commands",
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def bootstrap(
    args: argparse.Namespace,
    *,
    runner: Runner = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
    environ: Mapping[str, str] = os.environ,
) -> dict[str, object]:
    """Execute one idempotent preflight/provision/qualification request."""

    workspace = Workspace.discover(args.workspace)
    if workspace.is_release:
        raise BootstrapError(
            "run the standalone release's build.ps1/build.sh; use --release-root from "
            "a source checkout to audit its dependency boundary"
        )
    spec = load_spec(workspace)
    platform_name = host_platform()
    supported = spec.document.get("supported_platforms")
    if not isinstance(supported, list) or platform_name not in supported:
        raise BootstrapError(f"host {platform_name} is not declared in toolchain.toml")
    result: dict[str, object] = {
        "schema": SCHEMA,
        "platform": platform_name,
        "workspace": str(workspace.root),
        "mode": "provision" if args.provision else "check",
        "environmentContract": verify_environment_contract(workspace, spec),
        "portability": verify_portability(workspace, spec),
    }
    if args.release_root is not None:
        platforms = (
            ("windows", "linux")
            if args.release_platform == "both"
            else (args.release_platform,)
        )
        result["releaseBoundaries"] = [
            verify_release_boundary(
                args.release_root,
                spec,
                name,
                check_commands=not args.static_release,
                which=which,
            )
            for name in platforms
        ]
        return result

    pak: Path | None = None
    if args.qualify:
        pak = args.pak
        if pak is None and environ.get("QUAKE_PAK"):
            pak = Path(environ["QUAKE_PAK"])
        if pak is None:
            raise BootstrapError(
                "clean-host qualification requires the licensed Quake PAK0.PAK; "
                "pass --pak or set QUAKE_PAK before provisioning"
            )
        pak = pak.expanduser().resolve()
        if not pak.is_file():
            raise BootstrapError(
                f"Quake PAK override does not exist: {pak}; correct --pak/QUAKE_PAK"
            )

    git_override = args.git or environ.get("SNES_GIT")
    git = _resolve_command("git", git_override, which=which)
    environment_override = args.environment
    if environment_override is None and environ.get("SNES_TOOLCHAIN_ENV"):
        environment_override = Path(environ["SNES_TOOLCHAIN_ENV"])
    environment = ensure_python_environment(
        workspace,
        spec,
        platform_name=platform_name,
        provision=args.provision,
        override=environment_override,
        runner=runner,
    )
    libsfx_override = args.libsfx
    if libsfx_override is None and environ.get("SNES_LIBSFX"):
        libsfx_override = Path(environ["SNES_LIBSFX"])
    msbuild_override = args.msbuild or environ.get("SNES_MSBUILD")
    make_override = args.make or environ.get("SNES_MAKE")
    libsfx = ensure_libsfx(
        workspace,
        spec,
        git,
        platform_name=platform_name,
        provision=args.provision,
        override=libsfx_override,
        msbuild_override=msbuild_override,
        make_override=make_override,
        runner=runner,
        which=which,
    )
    mesen_override = args.mesen
    if mesen_override is None and environ.get("SNES_MESEN"):
        mesen_override = Path(environ["SNES_MESEN"])
    environment_python = Path(str(environment["python"]["path"]))
    mesen = ensure_mesen(
        workspace,
        spec,
        git,
        environment_python,
        platform_name=platform_name,
        provision=args.provision,
        override=mesen_override,
        msbuild_override=msbuild_override,
        runner=runner,
        which=which,
    )
    optional_submodules = [
        submodule_state(workspace, relative, git, runner=runner)
        for relative in spec.strings("workspace", "optional_submodules")
    ]
    result.update(
        {
            "git": str(git),
            "pythonEnvironment": environment,
            "libSFX": libsfx,
            "mesen": mesen,
            "optionalSubmodules": optional_submodules,
            "optionalTools": optional_tools(which=which),
        }
    )
    if args.qualify:
        assert pak is not None
        result["qualification"] = qualify_workspace(
            workspace,
            spec,
            environment,
            libsfx,
            mesen,
            git,
            report=(workspace.root / args.report).resolve()
            if not args.report.is_absolute()
            else args.report,
            pak=pak,
            runner=runner,
        )
    return result


def main(argv: Sequence[str] | None = None) -> int:
    started = time.monotonic()
    try:
        args = parse_args(argv)
        result = bootstrap(args)
    except (BootstrapError, OSError, WorkspaceError) as error:
        print(
            f"ERROR SNES workspace bootstrap: {error} "
            f"elapsed={time.monotonic() - started:.3f}s",
            file=sys.stderr,
        )
        return 1
    elapsed = time.monotonic() - started
    result["elapsedSeconds"] = round(elapsed, 3)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        qualification = " qualified=true" if "qualification" in result else ""
        releases = len(result.get("releaseBoundaries", []))
        release_summary = f" releaseBoundaries={releases}" if releases else ""
        print(
            f"PASS SNES workspace bootstrap: mode={result['mode']} "
            f"platform={result['platform']}{qualification}{release_summary} "
            f"elapsed={elapsed:.3f}s"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
