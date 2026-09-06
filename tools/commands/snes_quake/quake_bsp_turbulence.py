#!/usr/bin/env python3
"""Pure fixed-point contract for released-Quake turbulent surfaces.

WinQuake selects a 128-entry sine row with ``int(cl.time * 20)`` and
cross-warps the integer part of 16.16 S/T before sampling a 64x64 level-zero
texture.  The SNES contract retains those periods and the cross-axis lookup,
but quantizes the nonnegative 0..16-texel displacement to unsigned Q4 so one
128-byte table is sufficient for cartridge RAM.
"""

from __future__ import annotations

import hashlib
import math
import struct
from dataclasses import dataclass
from typing import Sequence


TURBULENCE_CYCLE = 128
TURBULENCE_SPEED = 20
TURBULENCE_AMPLITUDE = 8
TURBULENCE_TEXTURE_SIZE = 64
TURBULENCE_COORD_FRACTION_BITS = 4
TURBULENCE_COORD_MASK_Q4 = (TURBULENCE_TEXTURE_SIZE << 4) - 1
TURBULENCE_PHASE_FRACTION_BITS = 16
TURBULENCE_PHASE_MASK = (TURBULENCE_CYCLE << 16) - 1
TURBULENCE_PHASE_RECORD_BYTES = 3
SNES_NTSC_FRAMES_PER_SECOND = 60.0988138974405
FLY_CLOCK_FRACTION_BITS = 8
FLY_CLOCK_FRACTION_DENOMINATOR = 1 << FLY_CLOCK_FRACTION_BITS
FLY_CLOCK_STEP_Q24 = round(
    TURBULENCE_SPEED
    * (1 << TURBULENCE_PHASE_FRACTION_BITS)
    * FLY_CLOCK_FRACTION_DENOMINATOR
    / SNES_NTSC_FRAMES_PER_SECOND
)
FLY_CLOCK_PHASE_STEP_Q16 = FLY_CLOCK_STEP_Q24 >> FLY_CLOCK_FRACTION_BITS
FLY_CLOCK_FRACTION_STEP_Q8 = FLY_CLOCK_STEP_Q24 & (
    FLY_CLOCK_FRACTION_DENOMINATOR - 1
)

# round(128*sin(i*pi/64)), i=0..32, frozen so generation never depends on a
# platform libm.  The peak would make biased Q4 value 256 and is deliberately
# saturated to 255: the documented maximum error is 1/16 texel at three rows.
_SINE_QUARTER_Q4 = (
    0,
    6,
    13,
    19,
    25,
    31,
    37,
    43,
    49,
    55,
    60,
    66,
    71,
    76,
    81,
    86,
    91,
    95,
    99,
    103,
    106,
    110,
    113,
    116,
    118,
    121,
    122,
    124,
    126,
    127,
    127,
    128,
    128,
)


class TurbulenceError(ValueError):
    """Raised when an input cannot satisfy the fixed turbulence contract."""


@dataclass(frozen=True)
class TurbulenceClock:
    """One coherent Q16 time phase and the integer table row it selects."""

    surface_time: float
    phase_q16: int
    phase: int


def is_turbulent_texture_name(name: str) -> bool:
    """Return Quake's BSP miptex semantic for a turbulent surface."""

    return name.startswith("*")


def turbulent_material(name: str) -> str:
    """Classify a turbulent miptex for provenance without changing semantics."""

    if not is_turbulent_texture_name(name):
        raise TurbulenceError("turbulent texture names must begin with '*'")
    folded = name.casefold()
    for material in ("water", "slime", "lava", "teleport"):
        if material in folded:
            return material
    return "other"


def _signed_sine_q4(index: int) -> int:
    index &= TURBULENCE_CYCLE - 1
    if index <= 32:
        return _SINE_QUARTER_Q4[index]
    if index <= 64:
        return _SINE_QUARTER_Q4[64 - index]
    if index <= 96:
        return -_SINE_QUARTER_Q4[index - 64]
    return -_SINE_QUARTER_Q4[128 - index]


def build_turbulence_table() -> bytes:
    """Build the 128-byte biased Q4 displacement table."""

    return bytes(
        min(255, max(0, 128 + _signed_sine_q4(index)))
        for index in range(TURBULENCE_CYCLE)
    )


def table_sha256() -> str:
    return hashlib.sha256(build_turbulence_table()).hexdigest()


def require_turbulent_texture(width: int, height: int, payload: bytes) -> None:
    """Reject dimensions that the released-Quake 64x64 sampler cannot wrap."""

    if width <= 0 or height <= 0:
        raise TurbulenceError("turbulent texture dimensions must be positive")
    if width & (width - 1) or height & (height - 1):
        raise TurbulenceError("turbulent texture axes must be powers of two")
    if width != TURBULENCE_TEXTURE_SIZE or height != TURBULENCE_TEXTURE_SIZE:
        raise TurbulenceError("turbulent textures must be exactly 64x64")
    if len(payload) != width * height:
        raise TurbulenceError("turbulent level-zero payload size disagrees")


def turbulence_clock(surface_time: float) -> TurbulenceClock:
    """Convert finite nonnegative renderer time to modulo-128 Q16 phase."""

    if not math.isfinite(surface_time) or surface_time < 0.0:
        raise TurbulenceError("turbulence surface time must be finite and nonnegative")
    projected_q16 = math.trunc(
        surface_time
        * TURBULENCE_SPEED
        * (1 << TURBULENCE_PHASE_FRACTION_BITS)
    )
    phase_q16 = projected_q16 & TURBULENCE_PHASE_MASK
    return TurbulenceClock(
        surface_time=surface_time,
        phase_q16=phase_q16,
        phase=phase_q16 >> TURBULENCE_PHASE_FRACTION_BITS,
    )


def pack_phase_q16(phase_q16: int) -> bytes:
    if not 0 <= phase_q16 <= TURBULENCE_PHASE_MASK:
        raise TurbulenceError("turbulence phase escapes unsigned low-23 storage")
    return phase_q16.to_bytes(TURBULENCE_PHASE_RECORD_BYTES, "little")


def unpack_phase_q16(record: bytes) -> int:
    if len(record) != TURBULENCE_PHASE_RECORD_BYTES:
        raise TurbulenceError("turbulence phase record must contain three bytes")
    value = int.from_bytes(record, "little")
    if value > TURBULENCE_PHASE_MASK:
        raise TurbulenceError("turbulence phase record sets the reserved high bit")
    return value


def build_demo_phase_asset(
    first_server_time: float, pose_count: int, sample_rate_hz: int
) -> bytes:
    """Pack canonical time-derived Q16 phases, one per source render command."""

    if pose_count <= 0:
        raise TurbulenceError("turbulence phase asset requires at least one pose")
    if sample_rate_hz <= 0:
        raise TurbulenceError("turbulence phase asset requires a positive rate")
    turbulence_clock(first_server_time)
    records = bytearray()
    for source_pose in range(pose_count):
        surface_time = first_server_time + source_pose / sample_rate_hz
        records.extend(pack_phase_q16(turbulence_clock(surface_time).phase_q16))
    return bytes(records)


def phase_asset_record(asset: bytes, source_pose: int) -> int:
    if len(asset) % TURBULENCE_PHASE_RECORD_BYTES:
        raise TurbulenceError("turbulence phase asset is not record aligned")
    pose_count = len(asset) // TURBULENCE_PHASE_RECORD_BYTES
    if not 0 <= source_pose < pose_count:
        raise TurbulenceError("turbulence phase pose is outside the asset")
    offset = source_pose * TURBULENCE_PHASE_RECORD_BYTES
    return unpack_phase_q16(asset[offset : offset + TURBULENCE_PHASE_RECORD_BYTES])


def advance_fly_clock(
    phase_q16: int, fraction_q8: int, ticks: int = 1
) -> tuple[int, int]:
    """Advance the unpaused NTSC fly clock without floating-point state."""

    if not 0 <= phase_q16 <= TURBULENCE_PHASE_MASK:
        raise TurbulenceError("fly turbulence phase escapes unsigned low-23 storage")
    if not 0 <= fraction_q8 < FLY_CLOCK_FRACTION_DENOMINATOR:
        raise TurbulenceError("fly turbulence residual escapes unsigned Q8 storage")
    if not isinstance(ticks, int) or ticks < 0:
        raise TurbulenceError("fly turbulence ticks must be a nonnegative integer")
    accumulator = (
        (phase_q16 << FLY_CLOCK_FRACTION_BITS)
        + fraction_q8
        + ticks * FLY_CLOCK_STEP_Q24
    ) % ((TURBULENCE_PHASE_MASK + 1) << FLY_CLOCK_FRACTION_BITS)
    return (
        accumulator >> FLY_CLOCK_FRACTION_BITS,
        accumulator & (FLY_CLOCK_FRACTION_DENOMINATOR - 1),
    )


def warped_texel_coordinates_q4(
    s_q4: int,
    t_q4: int,
    phase: int,
    table: Sequence[int] | bytes | bytearray | memoryview | None = None,
) -> tuple[int, int]:
    """Cross-warp signed Q4 coordinates and return wrapped 64x64 texels."""

    active = build_turbulence_table() if table is None else table
    if len(active) != TURBULENCE_CYCLE:
        raise TurbulenceError("turbulence table must contain 128 bytes")
    if not 0 <= phase < TURBULENCE_CYCLE:
        raise TurbulenceError("turbulence phase must be in 0..127")
    s_displacement_q4 = int(active[((t_q4 >> 4) + phase) & 127])
    t_displacement_q4 = int(active[((s_q4 >> 4) + phase) & 127])
    if not 0 <= s_displacement_q4 <= 255 or not 0 <= t_displacement_q4 <= 255:
        raise TurbulenceError("turbulence table entries must be unsigned bytes")
    return (
        ((s_q4 + s_displacement_q4) >> 4) & 63,
        ((t_q4 + t_displacement_q4) >> 4) & 63,
    )


def sample_turbulent_texture(
    payload: bytes,
    width: int,
    height: int,
    s_q4: int,
    t_q4: int,
    phase: int,
    table: Sequence[int] | bytes | bytearray | memoryview | None = None,
) -> int:
    """Sample one fullbright level-zero texel through the fixed warp."""

    require_turbulent_texture(width, height, payload)
    s, t = warped_texel_coordinates_q4(s_q4, t_q4, phase, table)
    return payload[t * width + s]


def table_contract_bytes() -> bytes:
    """Hashable ABI summary used by reference/native instrumentation."""

    return struct.pack(
        "<8H",
        TURBULENCE_CYCLE,
        TURBULENCE_SPEED,
        TURBULENCE_AMPLITUDE,
        TURBULENCE_TEXTURE_SIZE,
        TURBULENCE_COORD_FRACTION_BITS,
        TURBULENCE_PHASE_FRACTION_BITS,
        FLY_CLOCK_PHASE_STEP_Q16,
        FLY_CLOCK_FRACTION_STEP_Q8,
    ) + build_turbulence_table()
