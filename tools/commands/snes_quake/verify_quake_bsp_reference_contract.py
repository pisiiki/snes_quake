#!/usr/bin/env python3
"""Capture or compare the Quake reference renderer's behavioral contract."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from workspace_paths import workspace_root
import statistics
import subprocess
import sys
import time
from typing import Any, Sequence


TOOLS = Path(__file__).resolve().parent
EXAMPLE = workspace_root(__file__) / "src/snes_quake"
OUTPUT = EXAMPLE.parents[1] / "out/snes_quake"
WORKSPACE = EXAMPLE.parents[1]
DATA = EXAMPLE / "Data"
DEFAULT_EXECUTABLE = (
    WORKSPACE / "out/reference_renderer/release/quake_bsp_reference_renderer.exe"
)
DEFAULT_OUTPUT = WORKSPACE / "tmp/validation/quake-reference-contract.json"
POSE = 101
MAXIMUM_RELATIVE_SLOWDOWN = 0.25
PERFORMANCE_ABSOLUTE_SLACK_SECONDS = 0.05


@dataclass(frozen=True)
class ContractCase:
    name: str
    arguments: tuple[str, ...] = ()


CASES = (
    ContractCase("technique-4", ("--external-bsp-models",)),
    ContractCase(
        "technique-2",
        ("--lighting", "none", "--external-bsp-models"),
    ),
    ContractCase(
        "technique-7",
        ("--no-textures", "--lighting", "lightmap", "--external-bsp-models"),
    ),
    ContractCase("technique-4-minimal", ("--no-brushes", "--no-entities", "--no-sound")),
)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def fingerprint(path: Path) -> dict[str, object]:
    payload = path.read_bytes()
    return {
        "bytes": len(payload),
        "sha256": sha256_bytes(payload),
    }


def directory_fingerprint(path: Path) -> dict[str, object]:
    records = []
    total_bytes = 0
    for child in sorted(
        candidate for candidate in path.rglob("*") if candidate.is_file()
    ):
        identity = fingerprint(child)
        total_bytes += int(identity["bytes"])
        records.append(
            {
                "path": child.relative_to(path).as_posix(),
                **identity,
            }
        )
    payload = json.dumps(records, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "files": len(records),
        "bytes": total_bytes,
        "manifestSha256": sha256_bytes(payload),
    }


def normalized_json(value: Any, key: str = "") -> Any:
    """Remove output-directory identity while retaining semantic JSON values."""
    if isinstance(value, dict):
        return {
            name: normalized_json(child, name) for name, child in sorted(value.items())
        }
    if isinstance(value, list):
        return [normalized_json(child, key) for child in value]
    if isinstance(value, str) and key.lower().endswith("path"):
        return Path(value).name
    return value


def artifact_contract(case_directory: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for path in sorted(case_directory.iterdir()):
        if not path.is_file() or path.name == "stdout.txt":
            continue
        payload = path.read_bytes()
        if path.suffix == ".json":
            document = json.loads(payload.decode("utf-8"))
            payload = json.dumps(
                normalized_json(document),
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        records.append(
            {
                "path": path.name,
                "contractBytes": len(payload),
                "contractSha256": sha256_bytes(payload),
            }
        )
    return records


def required_inputs(executable: Path, pak: Path) -> dict[str, Path]:
    return {
        "executable": executable,
        "pak": pak,
        "orderedReplay": DATA / "QuakeBSPOrderedReplay20Hz.bin",
        "cameraTrack": DATA / "QuakeBSPDemoPrecise.bin",
        "brushReplay": DATA / "QuakeBSPBrushReplay.bin",
        "externalBspReplay": DATA / "QuakeBSPExternalModels.bin",
        "soundReplay": DATA / "QuakeBSPReferenceSoundReplay.bin",
        "aliasMetadata": DATA / "QuakeBSPAliasAssets.json",
    }


def output_arguments(case: ContractCase, case_directory: Path) -> list[str]:
    arguments = [
        "--output-prefix",
        str(case_directory / "frame"),
        "--brush-albedo-indices",
        str(case_directory / "brush-albedo.idx"),
        "--brush-lightmap-indices",
        str(case_directory / "brush-lightmap.idx"),
        "--brush-render-indices",
        str(case_directory / "brush-render.idx"),
        "--packed-brush-albedo-indices",
        str(case_directory / "packed-brush-albedo.idx"),
        "--packed-brush-lightmap-indices",
        str(case_directory / "packed-brush-lightmap.idx"),
        "--packed-brush-render-indices",
        str(case_directory / "packed-brush-render.idx"),
        "--packed-alias-render-indices",
        str(case_directory / "packed-alias-render.idx"),
    ]
    if "--no-textures" not in case.arguments:
        arguments.extend(
            (
                "--quake-sky-indices",
                str(case_directory / "presentation.idx"),
            )
        )
    return arguments


def renderer_command(
    executable: Path,
    pak: Path,
    case: ContractCase,
    case_directory: Path,
) -> list[str]:
    return [
        str(executable),
        "--pak",
        str(pak),
        "--map",
        "maps/e1m3.bsp",
        "--data-dir",
        str(DATA),
        "--ordered-replay",
        str(DATA / "QuakeBSPOrderedReplay20Hz.bin"),
        "--realtime-demo",
        str(DATA / "QuakeBSPDemoPrecise.bin"),
        "--brush-replay",
        str(DATA / "QuakeBSPBrushReplay.bin"),
        "--external-bsp-replay",
        str(DATA / "QuakeBSPExternalModels.bin"),
        "--sound-replay",
        str(DATA / "QuakeBSPReferenceSoundReplay.bin"),
        "--alias-assets",
        str(DATA),
        "--demo-pose",
        str(POSE),
        *case.arguments,
        *output_arguments(case, case_directory),
        "--report-only",
    ]


def run_process(
    command: Sequence[str],
) -> tuple[subprocess.CompletedProcess[bytes], float]:
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=WORKSPACE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    return completed, time.perf_counter() - started


def run_case(
    executable: Path,
    pak: Path,
    case: ContractCase,
    artifacts: Path,
) -> dict[str, object]:
    case_directory = artifacts / case.name
    case_directory.mkdir(parents=True, exist_ok=False)
    completed, elapsed = run_process(
        renderer_command(executable, pak, case, case_directory)
    )
    (case_directory / "stdout.txt").write_bytes(completed.stdout)
    if completed.returncode:
        detail = completed.stdout.decode("utf-8", errors="replace")[-2000:]
        raise RuntimeError(
            f"reference contract case {case.name} failed with "
            f"exit {completed.returncode}:\n{detail}"
        )
    return {
        "name": case.name,
        "arguments": list(case.arguments),
        "stdout": {
            "bytes": len(completed.stdout),
            "sha256": sha256_bytes(completed.stdout),
        },
        "artifacts": artifact_contract(case_directory),
        "elapsedSeconds": round(elapsed, 6),
    }


def run_performance(
    executable: Path,
    pak: Path,
    artifacts: Path,
    runs: int,
) -> dict[str, object]:
    durations: list[float] = []
    for ordinal in range(runs):
        run_directory = artifacts / "performance" / f"run-{ordinal:02d}"
        run_directory.mkdir(parents=True, exist_ok=False)
        completed, elapsed = run_process(
            renderer_command(executable, pak, CASES[0], run_directory)
        )
        if completed.returncode:
            raise RuntimeError(
                f"reference performance run {ordinal} failed with "
                f"exit {completed.returncode}"
            )
        durations.append(elapsed)
    return {
        "case": CASES[0].name,
        "runs": runs,
        "samplesSeconds": [round(value, 6) for value in durations],
        "medianSeconds": round(statistics.median(durations), 6),
    }


def git_head() -> str:
    result = subprocess.run(
        ("git", "-C", str(WORKSPACE), "rev-parse", "HEAD"),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def capture(
    *,
    executable: Path,
    pak: Path,
    artifacts: Path,
    jobs: int,
    performance_runs: int,
) -> dict[str, object]:
    inputs = required_inputs(executable, pak)
    missing = [path for path in inputs.values() if not path.is_file()]
    if missing:
        raise RuntimeError(f"reference contract input is missing: {missing[0]}")
    if artifacts.exists():
        raise RuntimeError(
            f"reference contract artifact directory already exists: {artifacts}"
        )
    artifacts.parent.mkdir(parents=True, exist_ok=True)

    help_result, _help_elapsed = run_process((str(executable), "--help"))
    self_test, _self_test_elapsed = run_process((str(executable), "--self-test"))
    if help_result.returncode or self_test.returncode:
        raise RuntimeError(
            "reference contract preflight failed: "
            f"help={help_result.returncode}, self-test={self_test.returncode}"
        )
    if (
        self_test.stdout != b"self-test=PASS\r\n"
        and self_test.stdout != b"self-test=PASS\n"
    ):
        raise RuntimeError("reference self-test returned unexpected output")

    with ThreadPoolExecutor(max_workers=jobs) as executor:
        futures = [
            executor.submit(run_case, executable, pak, case, artifacts)
            for case in CASES
        ]
        cases = [future.result() for future in futures]
    for case in cases:
        case.pop("elapsedSeconds")

    return {
        "schema": "quake-reference-contract-v1",
        "commit": git_head(),
        "inputs": {
            **{name: fingerprint(path) for name, path in inputs.items()},
            "dataDirectory": directory_fingerprint(DATA),
        },
        "contract": {
            "help": {
                "bytes": len(help_result.stdout),
                "lines": len(help_result.stdout.splitlines()),
                "sha256": sha256_bytes(help_result.stdout),
            },
            "selfTest": self_test.stdout.decode("ascii").strip(),
            "pose": POSE,
            "cases": cases,
        },
        "performancePolicy": {
            "maximumRelativeSlowdown": MAXIMUM_RELATIVE_SLOWDOWN,
            "absoluteSlackSeconds": PERFORMANCE_ABSOLUTE_SLACK_SECONDS,
        },
        "performance": run_performance(executable, pak, artifacts, performance_runs),
    }


def first_difference(expected: Any, actual: Any, path: str = "contract") -> str | None:
    if type(expected) is not type(actual):
        return f"{path}: type {type(expected).__name__} != {type(actual).__name__}"
    if isinstance(expected, dict):
        if expected.keys() != actual.keys():
            return f"{path}: keys {sorted(expected)} != {sorted(actual)}"
        for key in expected:
            if difference := first_difference(
                expected[key], actual[key], f"{path}.{key}"
            ):
                return difference
        return None
    if isinstance(expected, list):
        if len(expected) != len(actual):
            return f"{path}: length {len(expected)} != {len(actual)}"
        for index, value in enumerate(expected):
            if difference := first_difference(value, actual[index], f"{path}[{index}]"):
                return difference
        return None
    if expected != actual:
        return f"{path}: {expected!r} != {actual!r}"
    return None


def compare(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, object]:
    mismatches: list[str] = []
    if difference := first_difference(
        baseline.get("contract"), candidate.get("contract")
    ):
        mismatches.append(difference)
    baseline_inputs = dict(baseline.get("inputs", {}))
    candidate_inputs = dict(candidate.get("inputs", {}))
    baseline_inputs.pop("executable", None)
    candidate_inputs.pop("executable", None)
    if difference := first_difference(baseline_inputs, candidate_inputs, "inputs"):
        mismatches.append(difference)

    policy = baseline.get("performancePolicy", {})
    relative = float(policy.get("maximumRelativeSlowdown", 0.0))
    slack = float(policy.get("absoluteSlackSeconds", 0.0))
    baseline_median = float(baseline["performance"]["medianSeconds"])
    candidate_median = float(candidate["performance"]["medianSeconds"])
    limit = baseline_median * (1.0 + relative) + slack
    if candidate_median > limit:
        mismatches.append(
            f"performance.medianSeconds: {candidate_median:.6f} exceeds {limit:.6f}"
        )
    return {
        "passed": not mismatches,
        "baselineCommit": baseline.get("commit"),
        "candidateCommit": candidate.get("commit"),
        "mismatches": mismatches,
        "performance": {
            "baselineMedianSeconds": baseline_median,
            "candidateMedianSeconds": candidate_median,
            "maximumSeconds": round(limit, 6),
        },
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, default=DEFAULT_EXECUTABLE)
    parser.add_argument("--pak", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--artifacts", type=Path)
    parser.add_argument("--compare", type=Path)
    parser.add_argument("--jobs", type=int, default=len(CASES))
    parser.add_argument("--performance-runs", type=int, default=5)
    args = parser.parse_args(argv)
    if args.jobs < 1 or args.jobs > len(CASES):
        parser.error(f"--jobs must be in 1..{len(CASES)}")
    if args.performance_runs < 3:
        parser.error("--performance-runs must be at least 3")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    started = time.perf_counter()
    output = args.output.resolve()
    artifacts = (
        args.artifacts.resolve()
        if args.artifacts is not None
        else output.with_suffix("").with_name(output.stem + "-artifacts")
    )
    try:
        report = capture(
            executable=args.executable.resolve(),
            pak=args.pak.resolve(),
            artifacts=artifacts,
            jobs=args.jobs,
            performance_runs=args.performance_runs,
        )
        if args.compare is not None:
            baseline = json.loads(args.compare.read_text(encoding="utf-8"))
            report["comparison"] = compare(baseline, report)
        report["elapsedSeconds"] = round(time.perf_counter() - started, 6)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        elapsed = time.perf_counter() - started
        print(
            f"FAIL Quake reference contract: {error}; elapsed={elapsed:.3f}s",
            file=sys.stderr,
        )
        return 1
    comparison = report.get("comparison")
    if isinstance(comparison, dict) and not comparison["passed"]:
        print(
            "FAIL Quake reference contract: "
            f"{comparison['mismatches'][0]}; output={output}; "
            f"elapsed={report['elapsedSeconds']:.3f}s",
            file=sys.stderr,
        )
        return 2
    action = "matched" if comparison is not None else "captured"
    print(
        f"PASS Quake reference contract: {action} {len(CASES)} cases; "
        f"output={output}; elapsed={report['elapsedSeconds']:.3f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
