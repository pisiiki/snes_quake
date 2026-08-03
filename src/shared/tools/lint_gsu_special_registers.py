"""Reject unsafe SuperFX special-register use and LOOP target setup."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


CACHE_BEGIN = "gsu_cache_kernel_begin"
CACHE_END = "gsu_cache_kernel_end"
MAX_MACRO_DEPTH = 32

INCLUDE_PATTERN = re.compile(r'^\s*\.include\s+["\']([^"\']+)["\']', re.IGNORECASE)
MACRO_PATTERN = re.compile(
    r"^\s*\.macro\s+([A-Za-z_@.][A-Za-z0-9_@.]*)\s*(.*)$",
    re.IGNORECASE,
)
MACRO_END_PATTERN = re.compile(r"^\s*\.endmac(?:ro)?\b", re.IGNORECASE)
DEFINE_PATTERN = re.compile(
    r"^\s*\.define\s+([A-Za-z_@.][A-Za-z0-9_@.]*)\s+(.+)$",
    re.IGNORECASE,
)
ASSIGNMENT_PATTERN = re.compile(
    r"^\s*([A-Za-z_@.][A-Za-z0-9_@.]*)\s*(?:=|\.set)\s*"
    r"([A-Za-z_@.][A-Za-z0-9_@.]*|\$[0-9A-Fa-f]+|0[xX][0-9A-Fa-f]+|[0-9]+)\s*$",
    re.IGNORECASE,
)
LABEL_PATTERN = re.compile(r"^\s*([A-Za-z_@.][A-Za-z0-9_@.]*)\s*:\s*")
LOOP_TARGET_PATTERN = re.compile(r"^[A-Za-z_@.][A-Za-z0-9_@.]*$")
OPCODE_PATTERN = re.compile(r"^\s*([A-Za-z_@.][A-Za-z0-9_@.]*)\b\s*(.*)$")
REGISTER_PATTERN = re.compile(r"R(1[0-5]|[0-9])", re.IGNORECASE)

DESTINATION_OPS = frozenset(
    ("move", "moves", "moveb", "movew", "ibt", "iwt", "lea", "lm", "lms")
)
SELECTOR_OPS = frozenset(("to", "with"))
MUTATION_OPS = frozenset(("inc", "dec"))
OPCODE_ALIASES = {
    "mto": "to",
    "mwith": "with",
    "minc": "inc",
    "mdec": "dec",
    "mibt": "ibt",
    "miwt": "iwt",
    "mlea": "lea",
    "mlm": "lm",
    "mlms": "lms",
}


@dataclass(frozen=True)
class RegisterPolicy:
    register: str
    purpose: str
    allowed_helpers: frozenset[str]
    annotation: str | None = None


REGISTER_POLICIES = {
    "r14": RegisterPolicy(
        register="R14",
        purpose="Game Pak ROM-buffer address",
        allowed_helpers=frozenset(("gsu_set_rom_buffer_address",)),
        annotation="allow-r14-rom-buffer",
    ),
    "r15": RegisterPolicy(
        register="R15",
        purpose="program counter",
        allowed_helpers=frozenset(("jal", "mjal", "gsu_absolute_goto")),
    ),
}
APPROVED_HELPERS = frozenset(
    helper for policy in REGISTER_POLICIES.values() for helper in policy.allowed_helpers
)


@dataclass(frozen=True)
class SourceLine:
    path: Path
    number: int
    text: str


@dataclass(frozen=True)
class Macro:
    name: str
    parameters: tuple[str, ...]
    body: tuple[SourceLine, ...]


@dataclass(frozen=True)
class LintViolation:
    path: Path
    line: int
    kernel: str
    register: str
    instruction: str
    purpose: str
    message: str | None = None

    def format(self) -> str:
        if self.message:
            return (
                f"{self.path}:{self.line}: {self.register} is the {self.purpose}; "
                f"{self.message}: {self.instruction.strip()}"
            )
        scope = (
            "global GSU code"
            if self.kernel == "global"
            else f"cache kernel {self.kernel!r}"
        )
        return (
            f"{self.path}:{self.line}: {self.register} is the {self.purpose}; "
            f"unsafe destination in {scope}: "
            f"{self.instruction.strip()}"
        )


@dataclass(frozen=True)
class LintReport:
    source: Path
    kernels: tuple[str, ...]
    statements: int
    violations: tuple[LintViolation, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "source": str(self.source),
            "kernels": list(self.kernels),
            "statements": self.statements,
            "violations": [violation.format() for violation in self.violations],
        }


class SpecialRegisterLintError(ValueError):
    def __init__(self, violations: Sequence[LintViolation]) -> None:
        self.violations = tuple(violations)
        super().__init__("\n".join(violation.format() for violation in violations))


@dataclass
class _ScanState:
    kernel: str | None = None
    statements: int = 0
    previous_instruction: SourceLine | None = None
    loop_target: str | None = None
    loop_target_seen: bool = False


def _split_comment(text: str) -> tuple[str, str]:
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
            quote = (
                None if quote == character else character if quote is None else quote
            )
            continue
        if character == ";" and quote is None:
            return text[:index], text[index + 1 :]
    return text, ""


def _strip_comment(text: str) -> str:
    return _split_comment(text)[0]


def _annotations(text: str) -> frozenset[str]:
    comment = _split_comment(text)[1].lower()
    return frozenset(
        name
        for name, policy in REGISTER_POLICIES.items()
        if policy.annotation
        and re.search(
            rf"\bgsu-lint:\s*{re.escape(policy.annotation)}\b",
            comment,
        )
    )


def _split_operands(text: str) -> list[str]:
    operands: list[str] = []
    current: list[str] = []
    quote: str | None = None
    depth = 0

    for character in text:
        if character in ('"', "'"):
            quote = (
                None if quote == character else character if quote is None else quote
            )
        elif quote is None and character in "({[":
            depth += 1
        elif quote is None and character in ")}]":
            depth = max(0, depth - 1)
        elif quote is None and depth == 0 and character == ",":
            operands.append("".join(current).strip())
            current.clear()
            continue
        current.append(character)

    tail = "".join(current).strip()
    if tail or operands:
        operands.append(tail)
    return operands


def _statement(text: str) -> tuple[str, list[str]] | None:
    text = _strip_comment(text).strip()
    while True:
        match = LABEL_PATTERN.match(text)
        if not match:
            break
        text = text[match.end() :]
    if not text or text.startswith("."):
        return None

    match = OPCODE_PATTERN.match(text)
    if not match:
        return None
    return match.group(1).lower(), _split_operands(match.group(2))


def _leading_labels(text: str) -> tuple[str, ...]:
    text = _strip_comment(text)
    labels: list[str] = []
    while match := LABEL_PATTERN.match(text):
        labels.append(match.group(1).lower())
        text = text[match.end() :]
    return tuple(labels)


def _macro_parameters(text: str) -> tuple[str, ...]:
    if not text.strip():
        return ()
    if "," in text:
        return tuple(
            value.strip().lower() for value in _split_operands(text) if value.strip()
        )
    return tuple(value.lower() for value in text.split())


def _read_lines(path: Path) -> list[SourceLine]:
    return [
        SourceLine(path=path, number=index, text=text)
        for index, text in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
        )
    ]


def _resolve_include(name: str, source: Path, include_dirs: Sequence[Path]) -> Path:
    candidates = (
        source.parent / name,
        *(directory / name for directory in include_dirs),
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(f"{source}: unable to resolve include {name!r}")


def _collect_macros(
    path: Path,
    include_dirs: Sequence[Path],
    macros: dict[str, Macro],
    defines: dict[str, str],
    visited: set[Path],
) -> None:
    path = path.resolve()
    if path in visited:
        return
    visited.add(path)
    lines = _read_lines(path)
    index = 0

    while index < len(lines):
        line = lines[index]
        code = _strip_comment(line.text)
        include = INCLUDE_PATTERN.match(code)
        if include:
            included = _resolve_include(include.group(1), path, include_dirs)
            _collect_macros(included, include_dirs, macros, defines, visited)
            index += 1
            continue

        define = DEFINE_PATTERN.match(code)
        if define:
            defines[define.group(1).lower()] = define.group(2).strip()
            index += 1
            continue

        assignment = ASSIGNMENT_PATTERN.match(code)
        if assignment:
            defines[assignment.group(1).lower()] = assignment.group(2).strip()
            index += 1
            continue

        macro_start = MACRO_PATTERN.match(code)
        if not macro_start:
            index += 1
            continue

        name = macro_start.group(1)
        body: list[SourceLine] = []
        index += 1
        while index < len(lines) and not MACRO_END_PATTERN.match(
            _strip_comment(lines[index].text)
        ):
            body.append(lines[index])
            index += 1
        if index >= len(lines):
            raise ValueError(f"{path}:{line.number}: unterminated macro {name!r}")
        macros[name.lower()] = Macro(
            name=name,
            parameters=_macro_parameters(macro_start.group(2)),
            body=tuple(body),
        )
        index += 1


def _substitute_macro(text: str, macro: Macro, arguments: Sequence[str]) -> str:
    output = text
    for index, parameter in enumerate(macro.parameters):
        value = arguments[index] if index < len(arguments) else ""
        output = re.sub(
            r"\{" + re.escape(parameter) + r"\}", value, output, flags=re.IGNORECASE
        )
        output = re.sub(
            r"(?<![A-Za-z0-9_@.])" + re.escape(parameter) + r"(?![A-Za-z0-9_@.])",
            value,
            output,
            flags=re.IGNORECASE,
        )
    return output


def _register(operand: str, defines: dict[str, str]) -> str | None:
    value = operand.strip()
    visited: set[str] = set()
    while True:
        match = REGISTER_PATTERN.fullmatch(value)
        if match:
            return f"r{int(match.group(1))}"
        try:
            number = int(value[1:], 16) if value.startswith("$") else int(value, 0)
        except ValueError:
            number = -1
        if 0 <= number <= 15:
            return f"r{number}"
        name = value.lower()
        if name in visited or name not in defines:
            return None
        visited.add(name)
        value = defines[name].strip()


def _special_register(operand: str, defines: dict[str, str]) -> str | None:
    register = _register(operand, defines)
    return register if register in REGISTER_POLICIES else None


def _writes_romb_source(
    text: str,
    macros: dict[str, Macro],
    defines: dict[str, str],
    stack: tuple[str, ...] = (),
) -> bool:
    """Return whether the final effective instruction explicitly updates R0."""

    parsed = _statement(text)
    if not parsed:
        return False
    opcode, operands = parsed
    normalized = OPCODE_ALIASES.get(opcode, opcode)
    if operands and normalized in DESTINATION_OPS | MUTATION_OPS:
        return _register(operands[0], defines) == "r0"

    macro = macros.get(opcode)
    if macro:
        if len(stack) >= MAX_MACRO_DEPTH or opcode in stack:
            return False
        final_instruction: str | None = None
        for body_line in macro.body:
            expanded = _substitute_macro(body_line.text, macro, operands)
            if _statement(expanded):
                final_instruction = expanded
        return final_instruction is not None and _writes_romb_source(
            final_instruction, macros, defines, (*stack, opcode)
        )

    replacement = defines.get(opcode)
    if replacement:
        if len(stack) >= MAX_MACRO_DEPTH or opcode in stack:
            return False
        suffix = ", ".join(operands)
        return _writes_romb_source(
            f"{replacement} {suffix}".rstrip(),
            macros,
            defines,
            (*stack, opcode),
        )
    return False


def _expand_effective_instructions(
    text: str,
    macros: dict[str, Macro],
    defines: dict[str, str],
    expanded_macros: frozenset[str],
    stack: tuple[str, ...] = (),
) -> list[str]:
    """Expand one source statement into its emitted instruction sequence."""

    parsed = _statement(text)
    if not parsed:
        return [text] if _leading_labels(text) else []
    label_lines = [f"{label}:" for label in _leading_labels(text)]
    opcode, operands = parsed
    macro = macros.get(opcode)
    if macro:
        if opcode not in expanded_macros and not any(
            _register(operand, defines) == "r13" for operand in operands
        ):
            return [text]
        if len(stack) >= MAX_MACRO_DEPTH or opcode in stack:
            # Some libSFX CPU state macros recurse through conditional assembly.
            # They are opaque to this linear emitted-instruction check.
            return [text]
        output = label_lines
        for body_line in macro.body:
            expanded = _substitute_macro(body_line.text, macro, operands)
            output.extend(
                _expand_effective_instructions(
                    expanded, macros, defines, expanded_macros, (*stack, opcode)
                )
            )
        return output

    replacement = defines.get(opcode)
    if replacement:
        if len(stack) >= MAX_MACRO_DEPTH or opcode in stack:
            return [text]
        suffix = ", ".join(operands)
        return label_lines + _expand_effective_instructions(
            f"{replacement} {suffix}".rstrip(),
            macros,
            defines,
            expanded_macros,
            (*stack, opcode),
        )
    return [text]


def _macros_containing_romb(
    macros: dict[str, Macro], defines: dict[str, str]
) -> frozenset[str]:
    """Find the small macro closure that can emit a ROMB instruction."""

    result: set[str] = set()
    changed = True
    while changed:
        changed = False
        for name, macro in macros.items():
            if name in result:
                continue
            for line in macro.body:
                parsed = _statement(line.text)
                if not parsed:
                    continue
                opcode = parsed[0]
                visited: set[str] = set()
                while opcode in defines and opcode not in visited:
                    visited.add(opcode)
                    replacement = _statement(defines[opcode])
                    if not replacement:
                        break
                    opcode = replacement[0]
                if opcode == "romb" or opcode in result:
                    result.add(name)
                    changed = True
                    break
    return frozenset(result)


def _macros_containing_loop(
    macros: dict[str, Macro], defines: dict[str, str]
) -> frozenset[str]:
    """Find the macro closure that can emit a LOOP instruction."""

    result: set[str] = set()
    changed = True
    while changed:
        changed = False
        for name, macro in macros.items():
            if name in result:
                continue
            for line in macro.body:
                parsed = _statement(line.text)
                if not parsed:
                    continue
                opcode = parsed[0]
                visited: set[str] = set()
                while opcode in defines and opcode not in visited:
                    visited.add(opcode)
                    replacement = _statement(defines[opcode])
                    if not replacement:
                        break
                    opcode = replacement[0]
                if opcode == "loop" or opcode in result:
                    result.add(name)
                    changed = True
                    break
    return frozenset(result)


def _loop_target_operand(operand: str, defines: dict[str, str]) -> str | None:
    value = operand.strip()
    if not value.startswith("#"):
        return None
    value = value[1:].strip()
    visited: set[str] = set()
    while value.lower() in defines and value.lower() not in visited:
        name = value.lower()
        visited.add(name)
        value = defines[name].strip()
        if value.startswith("#"):
            value = value[1:].strip()
    return value.lower() if LOOP_TARGET_PATTERN.fullmatch(value) else None


def _check_loop_contract(
    origin: SourceLine,
    text: str,
    state: _ScanState,
    defines: dict[str, str],
    violations: list[LintViolation],
) -> None:
    for label in _leading_labels(text):
        if label == state.loop_target:
            state.loop_target_seen = True

    parsed = _statement(text)
    if not parsed:
        return
    opcode, operands = parsed
    normalized = OPCODE_ALIASES.get(opcode, opcode)
    if (
        operands
        and normalized in DESTINATION_OPS | SELECTOR_OPS | MUTATION_OPS
        and _register(operands[0], defines) == "r13"
    ):
        state.loop_target = (
            _loop_target_operand(operands[1], defines)
            if normalized == "iwt" and len(operands) == 2
            else None
        )
        state.loop_target_seen = False

    if normalized != "loop":
        return

    message: str | None = None
    if state.loop_target is None:
        message = "initialize R13 with iwt R13, #label before LOOP"
    elif not state.loop_target_seen:
        message = f"R13 target {state.loop_target!r} has no matching label before LOOP"
    if message:
        violations.append(
            LintViolation(
                path=origin.path,
                line=origin.number,
                kernel=state.kernel or "global",
                register="R13",
                instruction=_strip_comment(text).strip(),
                purpose="LOOP target register",
                message=message,
            )
        )
    # Project policy deliberately consumes the lexical setup even though the
    # hardware retains R13, preventing an unrelated later LOOP from reusing it.
    state.loop_target = None
    state.loop_target_seen = False


def _macros_writing_register(
    register: str,
    macros: dict[str, Macro],
    defines: dict[str, str],
) -> frozenset[str]:
    """Find macros whose emitted closure can write one fixed register."""

    result: set[str] = set()
    callers: dict[str, set[str]] = {}
    for name, macro in macros.items():
        for line in macro.body:
            parsed = _statement(line.text)
            if not parsed:
                continue
            opcode, operands = parsed
            visited: set[str] = set()
            while opcode in defines and opcode not in visited:
                visited.add(opcode)
                suffix = ", ".join(operands)
                replacement = _statement(f"{defines[opcode]} {suffix}".rstrip())
                if not replacement:
                    break
                opcode, operands = replacement
            normalized = OPCODE_ALIASES.get(opcode, opcode)
            if operands and (
                (
                    normalized in DESTINATION_OPS | SELECTOR_OPS | MUTATION_OPS
                    and _register(operands[0], defines) == register
                )
                or any(_register(operand, defines) == register for operand in operands)
            ):
                result.add(name)
            if opcode in macros:
                callers.setdefault(opcode, set()).add(name)

    pending = list(result)
    while pending:
        callee = pending.pop()
        for caller in callers.get(callee, ()):
            if caller not in result:
                result.add(caller)
                pending.append(caller)
    return frozenset(result)


def _check_statement(
    origin: SourceLine,
    text: str,
    kernel: str,
    macros: dict[str, Macro],
    defines: dict[str, str],
    violations: list[LintViolation],
    stack: tuple[str, ...] = (),
    allowed_registers: frozenset[str] = frozenset(),
    checked_registers: frozenset[str] = frozenset(REGISTER_POLICIES),
    expand_macros: frozenset[str] | None = None,
) -> int:
    parsed = _statement(text)
    if not parsed:
        return 0
    opcode, operands = parsed

    helper_registers = frozenset(
        name
        for name, policy in REGISTER_POLICIES.items()
        if opcode in policy.allowed_helpers
    )

    normalized = OPCODE_ALIASES.get(opcode, opcode)
    target: str | None = None
    if operands and normalized in DESTINATION_OPS | SELECTOR_OPS | MUTATION_OPS:
        target = _special_register(operands[0], defines)
    annotations = _annotations(text)
    if annotations and target not in annotations:
        names = ", ".join(
            REGISTER_POLICIES[name].annotation or name for name in annotations
        )
        raise ValueError(
            f"{origin.path}:{origin.number}: annotation {names!r} is valid only "
            "on its matching special-register destination"
        )
    if target in checked_registers:
        if target not in allowed_registers and target not in annotations:
            policy = REGISTER_POLICIES[target]
            violations.append(
                LintViolation(
                    path=origin.path,
                    line=origin.number,
                    kernel=kernel,
                    register=policy.register,
                    instruction=_strip_comment(text).strip(),
                    purpose=policy.purpose,
                )
            )
        return 1

    macro = macros.get(opcode)
    if macro:
        if (
            expand_macros is not None
            and opcode not in expand_macros
            and not any(
                _register(operand, defines) in checked_registers for operand in operands
            )
        ):
            return 1
        if len(stack) >= MAX_MACRO_DEPTH or opcode in stack:
            chain = " -> ".join((*stack, opcode))
            raise ValueError(
                f"{origin.path}:{origin.number}: recursive macro expansion: {chain}"
            )
        statements = 0
        for body_line in macro.body:
            expanded = _substitute_macro(body_line.text, macro, operands)
            statements += _check_statement(
                origin,
                expanded,
                kernel,
                macros,
                defines,
                violations,
                (*stack, opcode),
                allowed_registers | helper_registers,
                checked_registers,
                expand_macros,
            )
        return max(1, statements)

    replacement = defines.get(opcode)
    if replacement:
        if len(stack) >= MAX_MACRO_DEPTH or opcode in stack:
            chain = " -> ".join((*stack, opcode))
            raise ValueError(
                f"{origin.path}:{origin.number}: recursive define expansion: {chain}"
            )
        suffix = ", ".join(operands)
        expanded = f"{replacement} {suffix}".rstrip()
        return _check_statement(
            origin,
            expanded,
            kernel,
            macros,
            defines,
            violations,
            (*stack, opcode),
            allowed_registers | helper_registers,
            checked_registers,
            expand_macros,
        )

    if opcode in APPROVED_HELPERS:
        return 1
    return 1


def _skip_macro(lines: Sequence[SourceLine], index: int) -> int:
    start = lines[index]
    index += 1
    while index < len(lines):
        if MACRO_END_PATTERN.match(_strip_comment(lines[index].text)):
            return index + 1
        index += 1
    raise ValueError(f"{start.path}:{start.number}: unterminated macro definition")


def _scan_file(
    path: Path,
    include_dirs: Sequence[Path],
    macros: dict[str, Macro],
    defines: dict[str, str],
    expanded_macros: frozenset[str],
    r14_macros: frozenset[str],
    r15_macros: frozenset[str],
    state: _ScanState,
    kernels: list[str],
    violations: list[LintViolation],
    include_stack: tuple[Path, ...],
) -> None:
    path = path.resolve()
    if path in include_stack:
        chain = " -> ".join(str(value) for value in (*include_stack, path))
        raise ValueError(f"recursive include while scanning cache kernel: {chain}")

    lines = _read_lines(path)
    index = 0
    while index < len(lines):
        line = lines[index]
        code = _strip_comment(line.text)
        if MACRO_PATTERN.match(code):
            index = _skip_macro(lines, index)
            continue

        include = INCLUDE_PATTERN.match(code)
        if include:
            included = _resolve_include(include.group(1), path, include_dirs)
            _scan_file(
                included,
                include_dirs,
                macros,
                defines,
                expanded_macros,
                r14_macros,
                r15_macros,
                state,
                kernels,
                violations,
                (*include_stack, path),
            )
            index += 1
            continue

        parsed = _statement(code)
        if not parsed:
            _check_loop_contract(line, line.text, state, defines, violations)
            index += 1
            continue
        opcode, operands = parsed

        if opcode == CACHE_BEGIN:
            if state.kernel:
                raise ValueError(
                    f"{path}:{line.number}: cache kernel {state.kernel!r} is already open"
                )
            if not operands or not operands[0]:
                raise ValueError(
                    f"{path}:{line.number}: cache kernel is missing a name"
                )
            state.kernel = operands[0]
            state.loop_target = None
            state.loop_target_seen = False
            kernels.append(state.kernel)
            index += 1
            continue

        if opcode == CACHE_END:
            if not state.kernel:
                raise ValueError(
                    f"{path}:{line.number}: cache kernel end has no matching begin"
                )
            end_name = operands[0] if operands else ""
            if end_name.lower() != state.kernel.lower():
                raise ValueError(
                    f"{path}:{line.number}: cache kernel end {end_name!r} "
                    f"does not match {state.kernel!r}"
                )
            state.kernel = None
            state.loop_target = None
            state.loop_target_seen = False
            index += 1
            continue

        if state.kernel:
            state.statements += _check_statement(
                line,
                line.text,
                state.kernel,
                macros,
                defines,
                violations,
            )
        else:
            normalized = OPCODE_ALIASES.get(opcode, opcode)
            # R14 ownership applies to every GSU instruction. Outside declared
            # cache kernels, R15 remains available for dynamic continuations,
            # but immediate jumps must use the canonical absolute-goto helper.
            r14_related = (
                opcode in r14_macros
                or (
                    operands
                    and normalized in DESTINATION_OPS | SELECTOR_OPS | MUTATION_OPS
                    and _register(operands[0], defines) == "r14"
                )
                or (
                    opcode in macros
                    and any(
                        _register(operand, defines) == "r14" for operand in operands
                    )
                )
                or bool(_annotations(line.text))
            )
            r15_related = opcode in r15_macros or (
                operands
                and normalized == "iwt"
                and _register(operands[0], defines) == "r15"
            )
            if r14_related or r15_related:
                checked_registers = frozenset(
                    register
                    for register, related in (
                        ("r14", r14_related),
                        ("r15", r15_related),
                    )
                    if related
                )
                expanded = (r14_macros if r14_related else frozenset()) | (
                    r15_macros if r15_related else frozenset()
                )
                _check_statement(
                    line,
                    line.text,
                    "global",
                    macros,
                    defines,
                    violations,
                    checked_registers=checked_registers,
                    expand_macros=expanded,
                )
        for effective in _expand_effective_instructions(
            line.text, macros, defines, expanded_macros
        ):
            _check_loop_contract(line, effective, state, defines, violations)
            effective_statement = _statement(effective)
            if effective_statement and effective_statement[0] == "romb":
                previous = state.previous_instruction
                if previous is None or not _writes_romb_source(
                    previous.text, macros, defines
                ):
                    violations.append(
                        LintViolation(
                            path=line.path,
                            line=line.number,
                            kernel=state.kernel or "global",
                            register="R0",
                            instruction=_strip_comment(effective).strip(),
                            purpose="ROMB bank-source register",
                            message=(
                                "load or mutate R0 in the immediately preceding "
                                "instruction"
                            ),
                        )
                    )
            if effective_statement:
                state.previous_instruction = SourceLine(
                    path=line.path,
                    number=line.number,
                    text=effective,
                )
        index += 1


def lint_gsu_special_registers(
    source: Path,
    *,
    include_dirs: Iterable[Path] = (),
) -> LintReport:
    source = source.resolve()
    include_paths = tuple(Path(path).resolve() for path in include_dirs)
    macros: dict[str, Macro] = {}
    defines: dict[str, str] = {}
    _collect_macros(source, include_paths, macros, defines, set())
    romb_macros = _macros_containing_romb(macros, defines)
    r14_macros = _macros_writing_register("r14", macros, defines)
    r15_macros = _macros_writing_register("r15", macros, defines)
    expanded_macros = (
        romb_macros
        | _macros_containing_loop(macros, defines)
        | _macros_writing_register("r13", macros, defines)
    )
    state = _ScanState()
    kernels: list[str] = []
    violations: list[LintViolation] = []
    _scan_file(
        source,
        include_paths,
        macros,
        defines,
        expanded_macros,
        r14_macros,
        r15_macros,
        state,
        kernels,
        violations,
        (),
    )
    if state.kernel:
        raise ValueError(f"{source}: cache kernel {state.kernel!r} has no matching end")
    return LintReport(
        source=source,
        kernels=tuple(kernels),
        statements=state.statements,
        violations=tuple(violations),
    )


def validate_gsu_special_registers(
    source: Path,
    *,
    include_dirs: Iterable[Path] = (),
) -> LintReport:
    report = lint_gsu_special_registers(source, include_dirs=include_dirs)
    if report.violations:
        raise SpecialRegisterLintError(report.violations)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Lint global R14 ownership, R14/R15 writes in GSU cache kernels, "
            "global ROMB source-register handoffs, and LOOP/R13 target setup."
        )
    )
    parser.add_argument("sources", nargs="+", type=Path)
    parser.add_argument("--include", action="append", default=[], type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        reports = [
            validate_gsu_special_registers(source, include_dirs=args.include)
            for source in args.sources
        ]
    except SpecialRegisterLintError as error:
        print("GSU special-register lint failed:", file=sys.stderr)
        for violation in error.violations:
            print(violation.format(), file=sys.stderr)
        return 1
    except (OSError, ValueError) as error:
        print(f"GSU special-register lint failed: {error}", file=sys.stderr)
        return 1

    for report in reports:
        print(
            f"GSU special-register lint: {report.source.name} "
            f"kernels={len(report.kernels)} statements={report.statements}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
