"""Validate linked SuperFX instruction-cache kernel declarations."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ld65_debug import load_debug_records, parse_debug_int


CACHE_BYTES = 512
CACHE_LINE_BYTES = 16
DEFAULT_SEGMENT = "GSUCODE"
SINGLE_SEGMENT_MANIFEST_SCHEMA = 1
MULTI_SEGMENT_MANIFEST_SCHEMA = 2
MARKER_PATTERN = re.compile(
    r"^__GSU_CACHE_KERNEL_(?P<name>[A-Za-z_][A-Za-z0-9_]*)_"
    r"(?P<kind>START|CACHE|END)$"
)
REQUIRED_MARKERS = frozenset(("START", "CACHE", "END"))


@dataclass(frozen=True)
class CacheKernel:
    name: str
    segment: str
    start: int
    end: int

    @property
    def size(self) -> int:
        return self.end - self.start

    @property
    def cbr(self) -> int:
        return self.start & 0xFFFF

    @property
    def window_end(self) -> int:
        return self.start + CACHE_BYTES - 1

    @property
    def remaining(self) -> int:
        return CACHE_BYTES - self.size

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "segment": self.segment,
            "start": f"0x{self.start:06x}",
            "end": f"0x{self.end:06x}",
            "bytes": self.size,
            "cbr": f"0x{self.cbr:04x}",
            "windowEnd": f"0x{self.window_end:06x}",
            "remainingBytes": self.remaining,
        }


def _linked_segments(
    records: dict[str, list[dict[str, str]]],
) -> dict[int, dict[str, str]]:
    segments: dict[int, dict[str, str]] = {}
    for segment in records.get("seg", []):
        if not all(field in segment for field in ("id", "name", "start", "size")):
            continue
        segment_id = parse_debug_int(segment["id"])
        if segment_id in segments:
            raise ValueError(f"duplicate linked segment id {segment_id}")
        segments[segment_id] = segment
    return segments


def _segment_bounds(segment: dict[str, str]) -> tuple[int, int]:
    required = ("id", "start", "size")
    if not all(field in segment for field in required):
        raise ValueError(
            f"{segment.get('name', '<unnamed>')!r} segment is missing linked "
            "address metadata"
        )
    start = parse_debug_int(segment["start"])
    return start, start + parse_debug_int(segment["size"])


def validate_cache_kernels(
    path: Path,
    *,
    segment_name: str | None = None,
    require: bool = True,
) -> list[CacheKernel]:
    records = load_debug_records(path)
    marker_records: dict[str, dict[str, dict[str, str]]] = {}

    for symbol in records.get("sym", []):
        match = MARKER_PATTERN.fullmatch(symbol.get("name", ""))
        if not match:
            continue
        if symbol.get("type") != "lab" or not all(
            field in symbol for field in ("seg", "val")
        ):
            raise ValueError(
                f"cache marker {symbol.get('name')!r} is not a linked label"
            )

        name = match.group("name")
        kind = match.group("kind")
        markers = marker_records.setdefault(name, {})
        if kind in markers:
            raise ValueError(f"cache kernel {name!r} has duplicate {kind} markers")
        markers[kind] = symbol

    if not marker_records:
        if require:
            raise ValueError("no GSU cache kernels were declared")
        return []

    segments = _linked_segments(records)
    kernels: list[CacheKernel] = []

    for name, markers in sorted(marker_records.items()):
        missing = sorted(REQUIRED_MARKERS - markers.keys())
        if missing:
            raise ValueError(f"cache kernel {name!r} is missing {', '.join(missing)}")
        marker_segments = {
            parse_debug_int(marker["seg"]) for marker in markers.values()
        }
        if len(marker_segments) != 1:
            raise ValueError(f"cache kernel {name!r} crosses linked segments")
        marker_segment_id = marker_segments.pop()
        segment = segments.get(marker_segment_id)
        if segment is None:
            raise ValueError(
                f"cache kernel {name!r} references unknown linked segment "
                f"{marker_segment_id}"
            )
        actual_segment = str(segment["name"])
        if segment_name is not None and actual_segment != segment_name:
            continue
        segment_start, segment_end = _segment_bounds(segment)

        start = parse_debug_int(markers["START"]["val"])
        cache = parse_debug_int(markers["CACHE"]["val"])
        end = parse_debug_int(markers["END"]["val"])
        kernel = CacheKernel(
            name=name,
            segment=actual_segment,
            start=start,
            end=end,
        )

        if start % CACHE_LINE_BYTES:
            raise ValueError(
                f"cache kernel {name!r} starts at 0x{start:06x}, not a 16-byte boundary"
            )
        if cache != start:
            raise ValueError(
                f"cache kernel {name!r} CACHE is at 0x{cache:06x}, "
                f"expected 0x{start:06x}"
            )
        if kernel.size <= 0:
            raise ValueError(f"cache kernel {name!r} is empty or has reversed markers")
        if kernel.size > CACHE_BYTES:
            raise ValueError(
                f"cache kernel {name!r} is {kernel.size} bytes; maximum is {CACHE_BYTES}"
            )
        if start < segment_start or end > segment_end:
            raise ValueError(f"cache kernel {name!r} lies outside {actual_segment}")
        if start >> 16 != kernel.window_end >> 16:
            raise ValueError(
                f"cache kernel {name!r} cache window crosses a 64 KiB bank"
            )
        kernels.append(kernel)

    if require and not kernels:
        scope = "linked image" if segment_name is None else repr(segment_name)
        raise ValueError(f"no GSU cache kernels were declared in {scope}")
    return kernels


def _manifest_kernels(
    manifest: dict[str, Any],
) -> tuple[dict[str, tuple[str, int, int]], set[str]]:
    schema = manifest.get("schema")
    raw_kernels = manifest.get("kernels")
    if not isinstance(raw_kernels, list):
        raise ValueError("GSU cache layout manifest kernels must be a list")

    expected: dict[str, tuple[str, int, int]] = {}
    if schema == SINGLE_SEGMENT_MANIFEST_SCHEMA:
        segment = manifest.get("segment")
        if not isinstance(segment, str) or not segment:
            raise ValueError("single-segment cache manifest has no segment")
        segments = {segment}
    elif schema == MULTI_SEGMENT_MANIFEST_SCHEMA:
        raw_segments = manifest.get("segments")
        if (
            not isinstance(raw_segments, list)
            or not raw_segments
            or any(not isinstance(value, str) or not value for value in raw_segments)
            or raw_segments != sorted(set(raw_segments))
        ):
            raise ValueError(
                "multi-segment cache manifest segments must be unique and sorted"
            )
        segments = set(raw_segments)
    else:
        raise ValueError(
            "GSU cache layout manifest schema must be "
            f"{SINGLE_SEGMENT_MANIFEST_SCHEMA} or {MULTI_SEGMENT_MANIFEST_SCHEMA}"
        )

    used_segments: set[str] = set()
    for index, value in enumerate(raw_kernels):
        required = {"name", "start", "end"}
        if schema == MULTI_SEGMENT_MANIFEST_SCHEMA:
            required.add("segment")
        if not isinstance(value, dict) or not required.issubset(value):
            raise ValueError(f"GSU cache layout manifest kernel {index} is incomplete")
        name = str(value["name"])
        if name in expected:
            raise ValueError(f"GSU cache layout manifest repeats kernel {name!r}")
        segment = (
            str(value["segment"])
            if schema == MULTI_SEGMENT_MANIFEST_SCHEMA
            else next(iter(segments))
        )
        if segment not in segments:
            raise ValueError(
                f"GSU cache layout manifest kernel {name!r} uses undeclared "
                f"segment {segment!r}"
            )
        used_segments.add(segment)
        expected[name] = (
            segment,
            parse_debug_int(value["start"]),
            parse_debug_int(value["end"]),
        )
    if schema == MULTI_SEGMENT_MANIFEST_SCHEMA and used_segments != segments:
        missing = sorted(segments - used_segments)
        raise ValueError(
            "multi-segment cache manifest has no kernels for " + ", ".join(missing)
        )
    return expected, segments


def validate_cache_manifest(
    kernels: list[CacheKernel],
    path: Path,
    *,
    segment_name: str | None = None,
) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"GSU cache layout manifest does not exist: {path}")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("GSU cache layout manifest is not an object")
    expected, manifest_segments = _manifest_kernels(manifest)
    if segment_name is not None:
        if segment_name not in manifest_segments:
            raise ValueError(
                f"GSU cache layout manifest does not declare segment {segment_name!r}"
            )
        expected = {
            name: value for name, value in expected.items() if value[0] == segment_name
        }
    actual = {
        kernel.name: (kernel.segment, kernel.start, kernel.end) for kernel in kernels
    }
    if expected.keys() != actual.keys():
        missing = sorted(expected.keys() - actual.keys())
        added = sorted(actual.keys() - expected.keys())
        details = []
        if missing:
            details.append(f"missing={','.join(missing)}")
        if added:
            details.append(f"added={','.join(added)}")
        raise ValueError(f"GSU cache kernel set changed ({'; '.join(details)})")

    for name, expected_range in expected.items():
        if actual[name] == expected_range:
            continue
        expected_segment, expected_start, expected_end = expected_range
        actual_segment, actual_start, actual_end = actual[name]
        raise ValueError(
            f"cache kernel {name!r} moved: "
            f"expected {expected_segment} "
            f"0x{expected_start:06x}..0x{expected_end:06x}, "
            f"linked {actual_segment} "
            f"0x{actual_start:06x}..0x{actual_end:06x}"
        )


def write_cache_manifest(
    kernels: list[CacheKernel],
    path: Path,
    *,
    segment_name: str | None = None,
) -> None:
    """Write a deterministic manifest from already validated linked kernels."""
    ordered = sorted(
        kernels,
        key=lambda kernel: (
            kernel.segment,
            kernel.start,
            kernel.end,
            kernel.name,
        ),
    )
    if not ordered:
        raise ValueError("cannot write an empty GSU cache layout manifest")
    segments = sorted({kernel.segment for kernel in ordered})
    if segment_name is not None and segments != [segment_name]:
        raise ValueError(f"cache kernels do not exclusively belong to {segment_name!r}")
    if len(segments) == 1:
        manifest = {
            "schema": SINGLE_SEGMENT_MANIFEST_SCHEMA,
            "segment": segments[0],
            "kernels": [
                {
                    "name": kernel.name,
                    "start": f"0x{kernel.start:06x}",
                    "end": f"0x{kernel.end:06x}",
                }
                for kernel in ordered
            ],
        }
    else:
        manifest = {
            "schema": MULTI_SEGMENT_MANIFEST_SCHEMA,
            "segments": segments,
            "kernels": [
                {
                    "name": kernel.name,
                    "segment": kernel.segment,
                    "start": f"0x{kernel.start:06x}",
                    "end": f"0x{kernel.end:06x}",
                }
                for kernel in ordered
            ],
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(manifest, indent=2) + "\n").encode("utf-8"))
    validate_cache_manifest(kernels, path, segment_name=segment_name)


def format_kernel(kernel: CacheKernel) -> str:
    return (
        f"GSU cache kernel {kernel.name}: start=0x{kernel.start:06x} "
        f"end=0x{kernel.end:06x} bytes={kernel.size} cbr=0x{kernel.cbr:04x} "
        f"window=0x{kernel.start:06x}..0x{kernel.window_end:06x} "
        f"remaining={kernel.remaining}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate GSU cache-kernel symbols in an ld65 debug file."
    )
    parser.add_argument("debug_info", type=Path)
    parser.add_argument(
        "--segment",
        help="validate only one linked segment (default: all declared segments)",
    )
    parser.add_argument("--allow-empty", action="store_true")
    manifest_group = parser.add_mutually_exclusive_group()
    manifest_group.add_argument("--manifest", type=Path)
    manifest_group.add_argument("--write-manifest", type=Path)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        kernels = validate_cache_kernels(
            args.debug_info,
            segment_name=args.segment,
            require=not args.allow_empty,
        )
        if args.manifest:
            validate_cache_manifest(
                kernels,
                args.manifest,
                segment_name=args.segment,
            )
        elif args.write_manifest:
            write_cache_manifest(
                kernels,
                args.write_manifest,
                segment_name=args.segment,
            )
    except (OSError, ValueError) as error:
        print(f"GSU cache validation failed: {error}", file=sys.stderr)
        return 1

    if args.json:
        print(
            json.dumps({"kernels": [kernel.to_dict() for kernel in kernels]}, indent=2)
        )
    else:
        for kernel in kernels:
            print(format_kernel(kernel))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
