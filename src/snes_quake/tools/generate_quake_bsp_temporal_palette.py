#!/usr/bin/env python3
"""Generate two low-flicker BGR555 phases for Quake's RGB888 palette."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


TOOLS = Path(__file__).resolve().parent
EXAMPLE = TOOLS.parent
SHARED = EXAMPLE.parent / "shared/tools"
sys.path[:0] = [str(TOOLS), str(SHARED)]

from generate_quake_bsp import (  # noqa: E402
    PALETTE_ENTRY,
    PakArchive,
    locate_quake_pak,
    quake_palette,
    snes_color,
)
from generated_outputs import GeneratedOutputError, sync_generated_outputs  # noqa: E402


DEFAULT_OUTPUT = EXAMPLE / "Data"
STATIC_PALETTE = Path("QuakeBSPTexturePalette.bin")
PHASE_PATHS = (
    Path("QuakeBSPTexturePaletteTemporal0.bin"),
    Path("QuakeBSPTexturePaletteTemporal1.bin"),
)
REPORT_PATH = Path("QuakeBSPTemporalPalette.json")
PALETTE_COLORS = 256
CHANNELS = 3
LUMA_WEIGHTS = (54, 183, 19)


@dataclass(frozen=True)
class TemporalPalette:
    phase_words: tuple[tuple[int, ...], tuple[int, ...]]
    report: dict[str, Any]


def expand_channel(code: int) -> int:
    if not 0 <= code <= 31:
        raise ValueError("BGR555 channel code must be in 0..31")
    return (code * 255 + 15) // 31


def unpack_word(word: int) -> tuple[int, int, int]:
    return word & 31, (word >> 5) & 31, (word >> 10) & 31


def pack_word(channels: tuple[int, int, int]) -> int:
    red, green, blue = channels
    return red | (green << 5) | (blue << 10)


def best_channel_pair(source: int) -> tuple[int, int]:
    """Choose an equal/adjacent pair with the best two-frame RGB888 mean."""

    candidates = (
        (low, high)
        for low in range(32)
        for high in range(low, min(low + 1, 31) + 1)
    )
    return min(
        candidates,
        key=lambda pair: (
            abs(expand_channel(pair[0]) + expand_channel(pair[1]) - 2 * source),
            pair[1] - pair[0],
            pair,
        ),
    )


def orient_color_pairs(
    pairs: tuple[tuple[int, int], tuple[int, int], tuple[int, int]]
) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """Assign pair endpoints to minimize per-color phase-luma flicker."""

    candidates = []
    for mask in range(1 << CHANNELS):
        first = tuple(
            pair[(mask >> channel) & 1] for channel, pair in enumerate(pairs)
        )
        second = tuple(
            pair[1 - ((mask >> channel) & 1)]
            for channel, pair in enumerate(pairs)
        )
        luma_delta = sum(
            weight * (expand_channel(left) - expand_channel(right))
            for weight, left, right in zip(
                LUMA_WEIGHTS, first, second, strict=True
            )
        )
        candidates.append((abs(luma_delta), first, second))
    _delta, first, second = min(candidates)
    return first, second


def palette_bytes(words: tuple[int, ...]) -> bytes:
    return b"".join(struct.pack("<H", word) for word in words)


def palette_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def generate_temporal_palette(source_data: bytes) -> TemporalPalette:
    source = quake_palette(source_data)
    static_words = tuple(snes_color(color) for color in source)
    first_words: list[int] = []
    second_words: list[int] = []
    baseline_errors: list[int] = []
    temporal_errors_twice: list[int] = []
    phase_jumps: list[int] = []
    changed_entries = 0

    for color, static_word in zip(source, static_words, strict=True):
        pairs = tuple(best_channel_pair(channel) for channel in color)
        first, second = orient_color_pairs(pairs)
        first_word = pack_word(first)
        second_word = pack_word(second)
        first_words.append(first_word)
        second_words.append(second_word)
        changed_entries += first_word != second_word
        for channel, static_code, first_code, second_code in zip(
            color, unpack_word(static_word), first, second, strict=True
        ):
            baseline_errors.append(expand_channel(static_code) - channel)
            temporal_errors_twice.append(
                expand_channel(first_code) + expand_channel(second_code) - 2 * channel
            )
            phase_jumps.append(
                abs(expand_channel(first_code) - expand_channel(second_code))
            )

    baseline_abs = [abs(error) for error in baseline_errors]
    temporal_abs = [abs(error) / 2 for error in temporal_errors_twice]
    sample_count = len(baseline_errors)
    baseline_mae = sum(baseline_abs) / sample_count
    temporal_mae = sum(temporal_abs) / sample_count
    baseline_rmse = math.sqrt(
        sum(error * error for error in baseline_errors) / sample_count
    )
    temporal_rmse = math.sqrt(
        sum(error * error for error in temporal_errors_twice)
        / (4 * sample_count)
    )
    no_worse = all(
        temporal <= baseline
        for temporal, baseline in zip(temporal_abs, baseline_abs, strict=True)
    )
    phase_words = (tuple(first_words), tuple(second_words))
    phase_data = tuple(palette_bytes(words) for words in phase_words)
    report: dict[str, Any] = {
        "schema": "quake-bsp-temporal-palette-v1",
        "source": {
            "entry": PALETTE_ENTRY,
            "bytes": len(source_data),
            "sha256": palette_sha256(source_data),
        },
        "staticNearest": {
            "bytes": PALETTE_COLORS * 2,
            "sha256": palette_sha256(palette_bytes(static_words)),
            "meanAbsoluteChannelError": baseline_mae,
            "rootMeanSquareChannelError": baseline_rmse,
            "maximumChannelError": max(baseline_abs),
        },
        "temporalPair": {
            "paletteBytes": PALETTE_COLORS * 2,
            "phaseSha256": [palette_sha256(data) for data in phase_data],
            "changedEntries": changed_entries,
            "improvedChannels": sum(
                temporal < baseline
                for temporal, baseline in zip(
                    temporal_abs, baseline_abs, strict=True
                )
            ),
            "meanAbsoluteChannelError": temporal_mae,
            "rootMeanSquareChannelError": temporal_rmse,
            "maximumChannelError": max(temporal_abs),
            "maximumPhaseChannelJump": max(phase_jumps),
            "individualChannelsNeverWorse": no_worse,
            "meanAbsoluteErrorReductionPercent": (
                (baseline_mae - temporal_mae) * 100 / baseline_mae
            ),
        },
    }
    if (
        not no_worse
        or temporal_mae >= baseline_mae
        or temporal_rmse >= baseline_rmse
        or max(phase_jumps) > 9
    ):
        raise AssertionError("temporal palette did not improve its bounded objective")
    return TemporalPalette(phase_words, report)


def outputs_for(palette: TemporalPalette) -> dict[Path, bytes]:
    outputs = {
        path: palette_bytes(words)
        for path, words in zip(PHASE_PATHS, palette.phase_words, strict=True)
    }
    outputs[REPORT_PATH] = (
        json.dumps(palette.report, indent=2, sort_keys=True) + "\n"
    ).encode("ascii")
    return outputs


def verify_static_palette(output: Path, report: dict[str, Any]) -> None:
    path = output / STATIC_PALETTE
    if not path.is_file():
        raise FileNotFoundError(
            f"{path} is missing; generate the main SNES Quake assets first"
        )
    actual = palette_sha256(path.read_bytes())
    expected = report["staticNearest"]["sha256"]
    if actual != expected:
        raise RuntimeError(
            f"{STATIC_PALETTE} is not the source-derived nearest palette: "
            f"{actual} != {expected}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pak", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    source = PakArchive(locate_quake_pak(args.pak)).read(PALETTE_ENTRY)
    palette = generate_temporal_palette(source)
    verify_static_palette(args.output, palette.report)
    try:
        sync_generated_outputs(
            outputs_for(palette),
            args.output,
            check=args.check,
        )
    except GeneratedOutputError as error:
        raise SystemExit(f"generated temporal palette is stale:\n{error}") from None
    metrics = palette.report["temporalPair"]
    action = "verified" if args.check else "generated"
    print(
        f"{action} two 256-color temporal palettes: "
        f"MAE={metrics['meanAbsoluteChannelError']:.6f}, "
        f"improvement={metrics['meanAbsoluteErrorReductionPercent']:.2f}%"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
