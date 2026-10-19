#!/usr/bin/env python3
"""Apply and check the complete SNES Quake reference-renderer format policy."""

from __future__ import annotations

import argparse
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence, TextIO


_CONSTRUCTOR_COLON = re.compile(rb"^(?P<indent>[ \t]*)(?P<head>[^?\r\n]*\))[ \t]+:$")


class ReferenceFormatError(RuntimeError):
    pass


@dataclass(frozen=True)
class FormatResult:
    path: Path
    original: bytes
    formatted: bytes
    constructor_colons: int

    @property
    def changed(self) -> bool:
        return self.original != self.formatted


def _without_line_ending(line: bytes) -> tuple[bytes, bytes]:
    if line.endswith(b"\r\n"):
        return line[:-2], b"\r\n"
    if line.endswith(b"\n") or line.endswith(b"\r"):
        return line[:-1], line[-1:]
    return line, b""


def _leading_whitespace(line: bytes) -> bytes:
    return line[: len(line) - len(line.lstrip(b" \t"))]


def _starts_constructor_initializer_list(
    lines: Sequence[bytes],
    colon_index: int,
    indent: bytes,
) -> bool:
    """Reject expression colons and accept a list ending at the function body."""

    saw_initializer = False
    for line in lines[colon_index + 1 :]:
        body, _ending = _without_line_ending(line)
        stripped = body.strip()
        if not stripped:
            continue
        leading = _leading_whitespace(body)
        if len(leading) < len(indent):
            return False
        if leading != indent:
            continue
        if stripped == b"{":
            return saw_initializer
        if stripped.startswith((b"#", b"}")) or stripped.endswith(b";"):
            return False
        if not saw_initializer and not re.match(rb"^(?:::)?[A-Za-z_~]", stripped):
            return False
        saw_initializer = True
    return False


def normalize_constructor_initializer_colons(data: bytes) -> tuple[bytes, int]:
    """Move Clang-Format's constructor `) :` token pair onto separate lines."""

    lines = data.splitlines(keepends=True)
    normalized: list[bytes] = []
    changes = 0
    for index, line in enumerate(lines):
        body, ending = _without_line_ending(line)
        match = _CONSTRUCTOR_COLON.fullmatch(body)
        if match is None or not _starts_constructor_initializer_list(
            lines, index, match.group("indent")
        ):
            normalized.append(line)
            continue
        indent = match.group("indent")
        normalized.append(indent + match.group("head") + ending)
        normalized.append(indent + b":" + ending)
        changes += 1
    return b"".join(normalized), changes


def _run_clang_format(clang_format: Path, style_file: Path, path: Path) -> bytes:
    completed = subprocess.run(
        (
            str(clang_format),
            f"--style=file:{style_file}",
            f"--assume-filename={path}",
            "--",
            str(path),
        ),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ReferenceFormatError(
            f"clang-format failed for {path} with exit {completed.returncode}: {detail}"
        )
    return completed.stdout


def _format_one(clang_format: Path, style_file: Path, path: Path) -> FormatResult:
    original = path.read_bytes()
    clang_formatted = _run_clang_format(clang_format, style_file, path)
    formatted, constructor_colons = normalize_constructor_initializer_colons(
        clang_formatted
    )
    return FormatResult(path, original, formatted, constructor_colons)


def format_files(
    clang_format: Path,
    style_file: Path,
    files: Sequence[Path],
) -> list[FormatResult]:
    ordered = sorted(
        (path.resolve() for path in files), key=lambda path: str(path).lower()
    )
    if not ordered:
        raise ReferenceFormatError("no reference-renderer files were provided")
    missing = [path for path in ordered if not path.is_file()]
    if missing:
        raise ReferenceFormatError(
            "formatter inputs do not exist: " + ", ".join(str(path) for path in missing)
        )
    workers = min(len(ordered), os.cpu_count() or 1)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        return list(
            executor.map(
                lambda path: _format_one(clang_format, style_file, path), ordered
            )
        )


def _atomic_write(path: Path, payload: bytes) -> None:
    mode = stat.S_IMODE(path.stat().st_mode)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def apply_format_policy(
    clang_format: Path,
    style_file: Path,
    files: Sequence[Path],
    *,
    check: bool,
    output: TextIO = sys.stdout,
) -> int:
    started = time.perf_counter()
    results = format_files(clang_format, style_file, files)
    changed = [result for result in results if result.changed]
    colon_count = sum(result.constructor_colons for result in results)
    if check and changed:
        for result in changed:
            print(f"ERROR nonconforming reference format: {result.path}", file=output)
        elapsed = time.perf_counter() - started
        print(
            "FAIL reference formatting: "
            f"mode=check files={len(results)} nonconforming={len(changed)} "
            f"constructor_colons={colon_count} elapsed={elapsed:.3f}s",
            file=output,
        )
        return 1
    if not check:
        for result in changed:
            _atomic_write(result.path, result.formatted)
    elapsed = time.perf_counter() - started
    print(
        "PASS reference formatting: "
        f"mode={'check' if check else 'write'} files={len(results)} "
        f"changed={len(changed)} constructor_colons={colon_count} "
        f"elapsed={elapsed:.3f}s",
        file=output,
    )
    return 0


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clang-format", type=Path, required=True)
    parser.add_argument("--style-file", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("files", nargs="+", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    started = time.perf_counter()
    args = _parse_args(argv)
    try:
        if not args.clang_format.is_file():
            raise ReferenceFormatError(
                f"clang-format executable does not exist: {args.clang_format}"
            )
        if not args.style_file.is_file():
            raise ReferenceFormatError(
                f"Clang-Format policy does not exist: {args.style_file}"
            )
        return apply_format_policy(
            args.clang_format.resolve(),
            args.style_file.resolve(),
            args.files,
            check=args.check,
        )
    except (OSError, ReferenceFormatError) as error:
        elapsed = time.perf_counter() - started
        print(
            f"ERROR reference formatting: {error} elapsed={elapsed:.3f}s",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
