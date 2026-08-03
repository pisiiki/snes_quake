"""Reject GSU constructs whose encoding is incompatible or unsafe on FX3."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


INCLUDE_PATTERN = re.compile(r'^\s*\.include\s+["\']([^"\']+)["\']', re.IGNORECASE)
LABEL_PATTERN = re.compile(r"^\s*[A-Za-z_@.][A-Za-z0-9_@.]*\s*:\s*")
OPCODE_PATTERN = re.compile(r"^\s*([A-Za-z_@.][A-Za-z0-9_@.]*)\b")
LOOP_LITERAL_PATTERN = re.compile(
    r"^\s*move\s+r12\s*,\s*#\s*(?P<literal>\$[0-9a-f]+|%[01]+|[0-9]+)\s*$",
    re.IGNORECASE,
)
FX3_INCLUDE = "snes_fx3.i"
INCOMPATIBLE_OPCODES = {
    "merge": "FX3 repurposes MERGE as its clear-command interface",
}
RAW_DELAY_SLOT_OPCODES = {
    "bcc",
    "bcs",
    "beq",
    "bge",
    "blt",
    "bmi",
    "bne",
    "bpl",
    "bra",
    "bvc",
    "bvs",
    "jmp",
    "ljmp",
    "loop",
}
MULTI_INSTRUCTION_DELAY_PSEUDOS = {
    "lm",
    "lms",
    "mlm",
    "mlms",
    "moves",
    "msm",
    "msms",
    "sm",
    "sms",
}
REGISTER_MOVE_PATTERN = re.compile(
    r"^\s*move\s+r(?:1[0-5]|[0-9])\s*,\s*r(?:1[0-5]|[0-9])\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Fx3OpcodeViolation:
    path: Path
    line: int
    opcode: str
    reason: str

    def format(self) -> str:
        return f"{self.path}:{self.line}: {self.reason}"


@dataclass(frozen=True)
class Fx3OpcodeLintReport:
    source: Path
    files: tuple[Path, ...]
    statements: int
    violations: tuple[Fx3OpcodeViolation, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "source": str(self.source),
            "files": [str(path) for path in self.files],
            "statements": self.statements,
            "violations": [violation.format() for violation in self.violations],
        }


class Fx3OpcodeLintError(ValueError):
    def __init__(self, violations: Sequence[Fx3OpcodeViolation]) -> None:
        self.violations = tuple(violations)
        super().__init__("\n".join(violation.format() for violation in violations))


def _strip_comment(text: str) -> str:
    quote: str | None = None
    escaped = False
    for index, character in enumerate(text):
        if escaped:
            escaped = False
            continue
        if character == "\\" and quote:
            escaped = True
            continue
        if character in ('"', "'"):
            quote = None if quote == character else character if quote is None else quote
            continue
        if character == ";" and quote is None:
            return text[:index]
    return text


def _opcode(text: str) -> str | None:
    text = _strip_comment(text).strip()
    while True:
        label = LABEL_PATTERN.match(text)
        if not label:
            break
        text = text[label.end() :]
    if not text or text.startswith("."):
        return None
    match = OPCODE_PATTERN.match(text)
    return match.group(1).lower() if match else None


def _unsafe_loop_literal(text: str) -> str | None:
    text = _strip_comment(text).strip()
    while True:
        label = LABEL_PATTERN.match(text)
        if not label:
            break
        text = text[label.end() :]
    match = LOOP_LITERAL_PATTERN.match(text)
    if not match:
        return None
    literal = match.group("literal")
    if literal.startswith("$"):
        value = int(literal[1:], 16)
    elif literal.startswith("%"):
        value = int(literal[1:], 2)
    else:
        value = int(literal, 10)
    return literal if 0x80 <= value <= 0xFF else None


def _unsafe_delay_slot_pseudo(text: str, opcode: str) -> str | None:
    if opcode in MULTI_INSTRUCTION_DELAY_PSEUDOS:
        return opcode.upper()
    code = _strip_comment(text).strip()
    while True:
        label = LABEL_PATTERN.match(code)
        if not label:
            break
        code = code[label.end() :]
    return "MOVE" if REGISTER_MOVE_PATTERN.fullmatch(code) else None


def _resolve_include(name: str, source: Path, include_dirs: Sequence[Path]) -> Path:
    for candidate in (source.parent / name, *(path / name for path in include_dirs)):
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(f"{source}: unable to resolve include {name!r}")


def _scan(
    path: Path,
    include_dirs: Sequence[Path],
    visited: set[Path],
    files: list[Path],
    violations: list[Fx3OpcodeViolation],
) -> int:
    path = path.resolve()
    if path in visited:
        return 0
    visited.add(path)
    files.append(path)
    statements = 0
    delay_slot_branch: tuple[int, str] | None = None
    for number, text in enumerate(
        path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
    ):
        code = _strip_comment(text)
        include = INCLUDE_PATTERN.match(code)
        if include:
            statements += _scan(
                _resolve_include(include.group(1), path, include_dirs),
                include_dirs,
                visited,
                files,
                violations,
            )
            continue
        opcode = _opcode(code)
        if not opcode:
            continue
        statements += 1
        if delay_slot_branch:
            pseudo = _unsafe_delay_slot_pseudo(code, opcode)
            if pseudo:
                branch_line, branch_opcode = delay_slot_branch
                violations.append(
                    Fx3OpcodeViolation(
                        path,
                        number,
                        pseudo,
                        f"{pseudo} expands to multiple GSU instructions in the "
                        f"{branch_opcode.upper()} delay slot from line "
                        f"{branch_line}; use one explicit instruction",
                    )
                )
        delay_slot_branch = (
            (number, opcode) if opcode in RAW_DELAY_SLOT_OPCODES else None
        )
        reason = INCOMPATIBLE_OPCODES.get(opcode)
        if reason:
            violations.append(
                Fx3OpcodeViolation(path, number, opcode.upper(), reason)
            )
        loop_literal = _unsafe_loop_literal(code)
        if loop_literal:
            violations.append(
                Fx3OpcodeViolation(
                    path,
                    number,
                    "MOVE",
                    f"MOVE R12,#{loop_literal} selects sign-extending IBT; "
                    "use IWT for unsigned LOOP counts from 128 through 255",
                )
            )
    return statements


def source_targets_fx3(source: Path) -> bool:
    for text in source.read_text(encoding="utf-8", errors="replace").splitlines():
        include = INCLUDE_PATTERN.match(_strip_comment(text))
        if include and Path(include.group(1).replace("\\", "/")).name.lower() == FX3_INCLUDE:
            return True
    return False


def lint_gsu_fx3_opcodes(
    source: Path, *, include_dirs: Iterable[Path] = ()
) -> Fx3OpcodeLintReport:
    source = source.resolve()
    include_paths = tuple(Path(path).resolve() for path in include_dirs)
    files: list[Path] = []
    violations: list[Fx3OpcodeViolation] = []
    statements = _scan(source, include_paths, set(), files, violations)
    return Fx3OpcodeLintReport(
        source=source,
        files=tuple(files),
        statements=statements,
        violations=tuple(violations),
    )


def validate_gsu_fx3_opcodes(
    source: Path, *, include_dirs: Iterable[Path] = ()
) -> Fx3OpcodeLintReport:
    report = lint_gsu_fx3_opcodes(source, include_dirs=include_dirs)
    if report.violations:
        raise Fx3OpcodeLintError(report.violations)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sources", nargs="+", type=Path)
    parser.add_argument("--include", action="append", default=[], type=Path)
    args = parser.parse_args()
    try:
        reports = [
            validate_gsu_fx3_opcodes(source, include_dirs=args.include)
            for source in args.sources
        ]
    except Fx3OpcodeLintError as error:
        print("GSU FX3 opcode lint failed:", file=sys.stderr)
        for violation in error.violations:
            print(violation.format(), file=sys.stderr)
        return 1
    except (OSError, ValueError) as error:
        print(f"GSU FX3 opcode lint failed: {error}", file=sys.stderr)
        return 1
    for report in reports:
        print(
            f"GSU FX3 opcode lint: {report.source.name} "
            f"files={len(report.files)} statements={report.statements}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
