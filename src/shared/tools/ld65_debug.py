"""Parsers for the ld65 debug-record and VICE-label output formats."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from pathlib import Path


FIELD_PATTERN = re.compile(
    r'(?:^|,)([A-Za-z][A-Za-z0-9_]*)=(?:"((?:\\.|[^"])*)"|([^,]*))'
)
LABEL_PATTERN = re.compile(
    r"^\s*(?P<tag>[A-Za-z]+)\s+"
    r"(?P<address>[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})\s+"
    r"\.(?P<name>\S+)\s*$"
)
LABEL_RECORD_TAG = "al"


def parse_ld65_labels(text: str, *, source: str = "label text") -> dict[str, int]:
    """Parse strict ld65 ``-Ln`` output into unprefixed label names.

    Blank lines and surrounding whitespace are accepted. Exported label names
    retain embedded dots. Scoped ``@`` and generated ``LOCAL-MACRO`` labels
    are omitted because ``-Ln`` does not preserve enough scope information to
    distinguish repeated local names. ld65 2.19 sanitizes the latter to
    ``LOCAL_MACRO``, so both spellings are recognized. Identical duplicate
    exported records are harmless, while an exported label assigned more than
    one address is rejected.
    """
    labels: dict[str, int] = {}
    first_lines: dict[str, int] = {}
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue

        match = LABEL_PATTERN.fullmatch(line)
        if match is None:
            raise ValueError(f"malformed ld65 label record in {source}:{line_number}")
        if match.group("tag") != LABEL_RECORD_TAG:
            raise ValueError(
                f"unsupported ld65 label tag {match.group('tag')!r} "
                f"in {source}:{line_number}"
            )

        name = match.group("name")
        address = int(match.group("address"), 16)
        if name.startswith("@") or name.startswith(("LOCAL-MACRO", "LOCAL_MACRO")):
            continue
        previous = labels.get(name)
        if previous is not None and previous != address:
            raise ValueError(
                f"conflicting ld65 label {name!r} in {source}:{line_number}: "
                f"0x{address:08X} differs from 0x{previous:08X} "
                f"on line {first_lines[name]}"
            )
        if previous is None:
            labels[name] = address
            first_lines[name] = line_number
    return labels


def load_ld65_labels(path: Path) -> dict[str, int]:
    """Load an ld65 ``-Ln`` file as strict UTF-8 and parse its labels."""
    label_path = Path(path)
    return parse_ld65_labels(
        label_path.read_text(encoding="utf-8"), source=str(label_path)
    )


def require_ld65_labels(
    labels: Mapping[str, int],
    required: Iterable[str],
    *,
    source: str = "symbol file",
) -> dict[str, int]:
    """Select required labels, reporting every missing name together."""
    names = tuple(required)
    missing = [name for name in names if name not in labels]
    if missing:
        raise ValueError(f"{source} lacks required labels: {', '.join(missing)}")
    return {name: labels[name] for name in names}


def parse_debug_int(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError(f"invalid ld65 integer {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError as error:
            raise ValueError(f"invalid ld65 integer {value!r}") from error
    raise ValueError(f"invalid ld65 integer {value!r}")


def unescape_debug_string(value: str) -> str:
    return value.replace(r'\"', '"').replace(r"\\", "\\")


def parse_debug_record(text: str) -> tuple[str, dict[str, str]] | None:
    line = text.rstrip("\r\n")
    if not line or "\t" not in line:
        return None

    kind, payload = line.split("\t", 1)
    fields: dict[str, str] = {}
    for match in FIELD_PATTERN.finditer(payload):
        quoted, plain = match.group(2), match.group(3)
        fields[match.group(1)] = (
            unescape_debug_string(quoted) if quoted is not None else plain.strip()
        )
    return kind, fields


def load_debug_records(path: Path) -> dict[str, list[dict[str, str]]]:
    if not path.is_file():
        raise FileNotFoundError(path)

    records: dict[str, list[dict[str, str]]] = {}
    for text in path.read_text(encoding="utf-8", errors="replace").splitlines():
        record = parse_debug_record(text)
        if record is None:
            continue
        kind, fields = record
        records.setdefault(kind, []).append(fields)
    return records
