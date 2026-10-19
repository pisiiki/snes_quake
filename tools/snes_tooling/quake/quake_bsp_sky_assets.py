#!/usr/bin/env python3
"""Pure Quake software-sky asset and clock contract for the SNES renderer."""

from __future__ import annotations

import hashlib
import math
import struct
from dataclasses import dataclass
from typing import Protocol, Sequence


SKY_TEXTURE_PREFIX = "sky"
SKY_SOURCE_WIDTH = 256
SKY_SOURCE_HEIGHT = 128
SKY_LAYER_SIZE = 128
SKY_SOURCE_BYTES = SKY_SOURCE_WIDTH * SKY_SOURCE_HEIGHT
SKY_SPEED = 8
SKY_REPEAT_SECONDS = 512.0
SKY_FIXED_FRACTION_BITS = 16
SKY_FIXED_MASK = 0x007F0000
SKY_FIXED_PERIOD = SKY_LAYER_SIZE << SKY_FIXED_FRACTION_BITS
SKY_PHASE_RECORD_BYTES = 3
SKY_PHASE_RECORD_FORMAT = "little-endian unsigned low 23 bits of Q16 texels"
SKY_LOGICAL_WIDTH = 128
SKY_LOGICAL_HEIGHT = 112
SKY_SPAN_MAXIMUM = 32
SKY_PROJECTION_SCALE = 378
SKY_RUNTIME_MARKER_CAPACITY = 9
MAX_QUAKE_SURFACE_TIME = 0x7FFFFFFF
SNES_NTSC_FRAMES_PER_SECOND = 60.0988138974405
FLY_CLOCK_FRACTION_BITS = 8
FLY_CLOCK_FRACTION_DENOMINATOR = 1 << FLY_CLOCK_FRACTION_BITS
FLY_CLOCK_STEP_Q24 = round(
    SKY_SPEED
    * (1 << SKY_FIXED_FRACTION_BITS)
    * FLY_CLOCK_FRACTION_DENOMINATOR
    / SNES_NTSC_FRAMES_PER_SECOND
)
FLY_CLOCK_PHASE_STEP_Q16 = FLY_CLOCK_STEP_Q24 >> FLY_CLOCK_FRACTION_BITS
FLY_CLOCK_FRACTION_STEP_Q8 = FLY_CLOCK_STEP_Q24 & (FLY_CLOCK_FRACTION_DENOMINATOR - 1)


class SkyAssetError(ValueError):
    """Raised when a source cannot satisfy the fail-closed sky contract."""


class MipTextureLike(Protocol):
    name: str
    width: int
    height: int
    pixels: bytes


@dataclass(frozen=True)
class SkyTextureContract:
    """Identity of the one canonical packed sky miptex."""

    source_miptex_id: int
    packed_texture_id: int
    name: str
    width: int
    height: int
    level_zero_bytes: int
    level_zero_sha256: str


@dataclass(frozen=True)
class SkyClock:
    """Released-WinQuake clock values with every float32 boundary explicit."""

    surface_time: float
    wrapped_time: float
    projected_phase: float
    projected_phase_float32_bits: int
    projected_phase_q16: int
    projected_phase_low23: int
    composite_shift: int


@dataclass(frozen=True)
class SkyMarkerSafety:
    """Proof summary for the canonical final-plane ownership marker."""

    marker: int
    texture_count: int
    texture_bytes: int
    colormap_rows: int
    colormap_bytes: int


@dataclass(frozen=True)
class OpaquePaletteDomain:
    """Exact canonical index domain visible before a sky-marker postpass."""

    texture_count: int
    texture_bytes: int
    source_indices: tuple[int, ...]
    colormap_count: int
    colormap_rows: int
    colormap_bytes: int
    shaded_indices: tuple[int, ...]
    alias_opaque_texels: int
    alias_indices: tuple[int, ...]
    used_indices: tuple[int, ...]
    used_indices_sha256: str
    safe_indices: tuple[int, ...]


@dataclass(frozen=True)
class SkySpanChunk:
    """One released-Quake DDA partition and its projected endpoint pixels."""

    first_x: int
    endpoint_x: int
    pixel_count: int
    full_partition: bool


def float32(value: float) -> float:
    """Round one finite Python float to IEEE-754 binary32."""

    try:
        rounded = struct.unpack("<f", struct.pack("<f", value))[0]
    except (OverflowError, struct.error) as error:
        raise SkyAssetError("sky float32 conversion overflowed") from error
    if not math.isfinite(rounded):
        raise SkyAssetError("sky float32 conversion is not finite")
    return rounded


def trunc0_div(numerator: int, denominator: int) -> int:
    """Divide signed integers with C/C++ truncation toward zero."""

    if denominator <= 0:
        raise SkyAssetError("sky integer denominator must be positive")
    magnitude = abs(numerator) // denominator
    return -magnitude if numerator < 0 else magnitude


def advance_fly_clock(
    phase_low23: int, fraction_q8: int, ticks: int = 1
) -> tuple[int, int]:
    """Advance the deterministic unpaused-NTSC fly clock without floats."""

    if not 0 <= phase_low23 < SKY_FIXED_PERIOD:
        raise SkyAssetError("fly sky phase is outside unsigned low-23 storage")
    if not 0 <= fraction_q8 < FLY_CLOCK_FRACTION_DENOMINATOR:
        raise SkyAssetError("fly sky residual is outside unsigned Q8 storage")
    if not isinstance(ticks, int) or ticks < 0:
        raise SkyAssetError("fly sky tick count must be a nonnegative integer")
    accumulator = (
        (phase_low23 << FLY_CLOCK_FRACTION_BITS)
        + fraction_q8
        + ticks * FLY_CLOCK_STEP_Q24
    ) % (SKY_FIXED_PERIOD << FLY_CLOCK_FRACTION_BITS)
    return (
        accumulator >> FLY_CLOCK_FRACTION_BITS,
        accumulator & (FLY_CLOCK_FRACTION_DENOMINATOR - 1),
    )


def surface_time_for_phase(phase_low23: int) -> float:
    """Return an exact binary time whose Quake phase is ``phase_low23``."""

    if not 0 <= phase_low23 < SKY_FIXED_PERIOD:
        raise SkyAssetError("fly sky phase is outside unsigned low-23 storage")
    return phase_low23 / float(SKY_SPEED << SKY_FIXED_FRACTION_BITS)


def round_nearest_even_div(numerator: int, denominator: int) -> int:
    """Round a nonnegative integer quotient to nearest, ties to even."""

    if numerator < 0 or denominator <= 0:
        raise SkyAssetError("sky nearest-even division requires nonnegative operands")
    quotient, remainder = divmod(numerator, denominator)
    if remainder * 2 > denominator or (remainder * 2 == denominator and quotient & 1):
        quotient += 1
    return quotient


def three_quarter_sqrt(value: int) -> tuple[int, int]:
    """Return the deterministic 3/4-rounded root and exact floor remainder.

    If ``r = floor(sqrt(value))`` and ``R = value - r*r``, then
    ``sqrt(value) - r >= 3/4`` is exactly ``16*R >= 24*r + 9``.  For integer
    ``R`` that is equivalently ``R >= r + ceil(r/2) + 1``, the comparison the
    SNES uses.  Equality rounds up.
    """

    if value < 0:
        raise SkyAssetError("sky square root requires a nonnegative radicand")
    floor_root = math.isqrt(value)
    remainder = value - floor_root * floor_root
    threshold = floor_root + (floor_root + 1) // 2 + 1
    rounded = floor_root + int(remainder >= threshold)
    return rounded, remainder


def nearest_even_sqrt(value: int) -> tuple[int, int]:
    """Return the nearest integer root, ties to even, and floor remainder."""

    if value < 0:
        raise SkyAssetError("sky square root requires a nonnegative radicand")
    floor_root = math.isqrt(value)
    remainder = value - floor_root * floor_root
    upper_distance = 2 * floor_root + 1 - remainder
    round_up = remainder > upper_distance or (
        remainder == upper_distance and bool(floor_root & 1)
    )
    return floor_root + int(round_up), remainder


def faulty_base15_square(value: int) -> int:
    """Model the rejected unmasked ``swap(base**2) << 6`` square term."""

    if value < 0:
        raise SkyAssetError("faulty sky square model requires a nonnegative value")
    base = value >> 15
    base_square = base * base
    if base_square > 0xFFFF:
        raise SkyAssetError("faulty sky square model escapes its 16-bit product")
    return value * value + ((base_square >> 8) << 22)


def faulty_base15_floor_sqrt(value: int, *, bits: int = 21) -> int:
    """Reproduce the rejected greedy root using the faulty base-2^15 square."""

    if value < 0 or bits <= 0:
        raise SkyAssetError("faulty sky root requires a nonnegative value and bits")
    root = 0
    for bit in range(bits - 1, -1, -1):
        trial = root | (1 << bit)
        if faulty_base15_square(trial) <= value:
            root = trial
    return root


def quake_sky_ray_numerators(
    yaw: int,
    pitch: int,
    u: int,
    v: int,
    sin_table: Sequence[int],
    cos_table: Sequence[int],
) -> tuple[int, int, int]:
    """Return the exact common-denominator-64 packed-view sky ray.

    Preserving these numerators through normalization is required. Dividing
    the components by 64 first moves real corpus samples across texel edges.
    """

    if len(sin_table) != 32 or len(cos_table) != 32:
        raise SkyAssetError("sky projection requires complete 32-entry Q6 tables")
    if any(not -128 <= value <= 127 for value in (*sin_table, *cos_table)):
        raise SkyAssetError("sky projection tables escape signed-byte Q6")
    if not 0 <= u < SKY_LOGICAL_WIDTH or not 0 <= v < SKY_LOGICAL_HEIGHT:
        raise SkyAssetError("sky projection coordinate escapes the logical frame")
    yaw_sin = sin_table[yaw & 31]
    yaw_cos = cos_table[yaw & 31]
    pitch_sin = sin_table[pitch & 31]
    pitch_cos = cos_table[pitch & 31]
    du = u - (SKY_LOGICAL_WIDTH // 2)
    dv = (SKY_LOGICAL_HEIGHT // 2) - v
    return (
        64 * pitch_cos * yaw_cos - 64 * du * yaw_sin - dv * pitch_sin * yaw_cos,
        64 * pitch_cos * yaw_sin + 64 * du * yaw_cos - dv * pitch_sin * yaw_sin,
        192 * (64 * pitch_sin + dv * pitch_cos),
    )


def quake_sky_exact_integer_endpoint(
    yaw: int,
    pitch: int,
    u: int,
    v: int,
    phase_q16: int,
    sin_table: Sequence[int],
    cos_table: Sequence[int],
) -> tuple[int, int]:
    """Project one packed-view endpoint with the parity-exact integer oracle."""

    ray = quake_sky_ray_numerators(yaw, pitch, u, v, sin_table, cos_table)
    magnitude = math.isqrt(sum(component * component for component in ray))
    if magnitude == 0:
        raise SkyAssetError("sky integer view direction cannot be normalized")
    scale = SKY_PROJECTION_SCALE << SKY_FIXED_FRACTION_BITS
    return tuple(
        phase_q16 + trunc0_div(scale * component, magnitude) for component in ray[:2]
    )


def quake_sky_three_quarter_integer_endpoint(
    yaw: int,
    pitch: int,
    u: int,
    v: int,
    phase_q16: int,
    sin_table: Sequence[int],
    cos_table: Sequence[int],
) -> tuple[int, int]:
    """Project with the full-corpus 3/4-rounded magnitude contract."""

    ray = quake_sky_ray_numerators(yaw, pitch, u, v, sin_table, cos_table)
    magnitude, _remainder = three_quarter_sqrt(
        sum(component * component for component in ray)
    )
    if magnitude == 0:
        raise SkyAssetError("sky integer view direction cannot be normalized")
    scale = SKY_PROJECTION_SCALE << SKY_FIXED_FRACTION_BITS
    return tuple(
        phase_q16 + trunc0_div(scale * component, magnitude) for component in ray[:2]
    )


def quake_sky_nearest_integer_endpoint(
    yaw: int,
    pitch: int,
    u: int,
    v: int,
    phase_q16: int,
    sin_table: Sequence[int],
    cos_table: Sequence[int],
) -> tuple[int, int]:
    """Project with nearest-even integer magnitude for regression evidence."""

    ray = quake_sky_ray_numerators(yaw, pitch, u, v, sin_table, cos_table)
    magnitude, _remainder = nearest_even_sqrt(
        sum(component * component for component in ray)
    )
    if magnitude == 0:
        raise SkyAssetError("sky integer view direction cannot be normalized")
    scale = SKY_PROJECTION_SCALE << SKY_FIXED_FRACTION_BITS
    return tuple(
        phase_q16 + trunc0_div(scale * component, magnitude) for component in ray[:2]
    )


def quake_sky_faulty_square_endpoint(
    yaw: int,
    pitch: int,
    u: int,
    v: int,
    phase_q16: int,
    sin_table: Sequence[int],
    cos_table: Sequence[int],
) -> tuple[int, int]:
    """Project through the rejected unmasked base-2^15 square implementation."""

    ray = quake_sky_ray_numerators(yaw, pitch, u, v, sin_table, cos_table)
    magnitude = faulty_base15_floor_sqrt(
        sum(faulty_base15_square(abs(component)) for component in ray)
    )
    if magnitude == 0:
        raise SkyAssetError("faulty sky view direction cannot be normalized")
    scale = SKY_PROJECTION_SCALE << SKY_FIXED_FRACTION_BITS
    return tuple(
        phase_q16 + trunc0_div(scale * component, magnitude) for component in ray[:2]
    )


def quake_sky_truncated_integer_endpoint(
    yaw: int,
    pitch: int,
    u: int,
    v: int,
    phase_q16: int,
    sin_table: Sequence[int],
    cos_table: Sequence[int],
) -> tuple[int, int]:
    """Return the rejected early-component-truncation design for audit only."""

    exact = quake_sky_ray_numerators(yaw, pitch, u, v, sin_table, cos_table)
    ray = tuple(trunc0_div(component, 64) for component in exact)
    magnitude = math.isqrt(sum(component * component for component in ray))
    if magnitude == 0:
        raise SkyAssetError("truncated sky view direction cannot be normalized")
    scale = SKY_PROJECTION_SCALE << SKY_FIXED_FRACTION_BITS
    return tuple(
        phase_q16 + trunc0_div(scale * component, magnitude) for component in ray[:2]
    )


def quake_sky_normalized_reciprocal_endpoint(
    yaw: int,
    pitch: int,
    u: int,
    v: int,
    phase_q16: int,
    sin_table: Sequence[int],
    cos_table: Sequence[int],
    *,
    reciprocal_fraction_bits: int = 17,
) -> tuple[int, int]:
    """Project via the tested nearest-even normalized reciprocal contract."""

    if reciprocal_fraction_bits <= 0:
        raise SkyAssetError("sky reciprocal precision must be positive")
    ray = quake_sky_ray_numerators(yaw, pitch, u, v, sin_table, cos_table)
    magnitude = math.isqrt(sum(component * component for component in ray))
    if magnitude == 0:
        raise SkyAssetError("sky reciprocal view direction cannot be normalized")
    magnitude_bits = magnitude.bit_length()
    reciprocal_scale_bits = reciprocal_fraction_bits + magnitude_bits
    reciprocal = round_nearest_even_div(1 << reciprocal_scale_bits, magnitude)
    result_shift = reciprocal_scale_bits - SKY_FIXED_FRACTION_BITS
    if result_shift < 0:
        raise SkyAssetError("sky reciprocal precision cannot produce Q16 output")
    divisor = 1 << result_shift
    return tuple(
        phase_q16 + trunc0_div(SKY_PROJECTION_SCALE * component * reciprocal, divisor)
        for component in ray[:2]
    )


def quake_sky_three_quarter_reciprocal_endpoint(
    yaw: int,
    pitch: int,
    u: int,
    v: int,
    phase_q16: int,
    sin_table: Sequence[int],
    cos_table: Sequence[int],
    *,
    reciprocal_fraction_bits: int,
) -> tuple[int, int]:
    """Project a 3/4-rounded magnitude through a nearest-even reciprocal."""

    if reciprocal_fraction_bits <= 0:
        raise SkyAssetError("sky reciprocal precision must be positive")
    ray = quake_sky_ray_numerators(yaw, pitch, u, v, sin_table, cos_table)
    magnitude, _remainder = three_quarter_sqrt(
        sum(component * component for component in ray)
    )
    if magnitude == 0:
        raise SkyAssetError("sky reciprocal view direction cannot be normalized")
    reciprocal_scale_bits = reciprocal_fraction_bits + magnitude.bit_length()
    reciprocal = round_nearest_even_div(1 << reciprocal_scale_bits, magnitude)
    result_shift = reciprocal_scale_bits - SKY_FIXED_FRACTION_BITS
    if result_shift < 0:
        raise SkyAssetError("sky reciprocal precision cannot produce Q16 output")
    divisor = 1 << result_shift
    return tuple(
        phase_q16 + trunc0_div(SKY_PROJECTION_SCALE * component * reciprocal, divisor)
        for component in ray[:2]
    )


def _float32_multiply(left: float, right: float) -> float:
    return float32(float32(left) * float32(right))


def _float32_add(left: float, right: float) -> float:
    return float32(float32(left) + float32(right))


def quake_sky_reference_float_endpoint(
    yaw: int,
    pitch: int,
    u: int,
    v: int,
    projected_phase: float,
    sin_table: Sequence[int],
    cos_table: Sequence[int],
) -> tuple[int, int]:
    """Mirror every binary32 boundary in the committed packed C++ oracle."""

    quake_sky_ray_numerators(yaw, pitch, u, v, sin_table, cos_table)
    yaw_sin = sin_table[yaw & 31]
    yaw_cos = cos_table[yaw & 31]
    pitch_sin = sin_table[pitch & 31]
    pitch_cos = cos_table[pitch & 31]
    forward = (
        pitch_cos * yaw_cos / 4096,
        pitch_cos * yaw_sin / 4096,
        pitch_sin / 64,
    )
    right = (-yaw_sin / 64, yaw_cos / 64, 0.0)
    up = (
        -pitch_sin * yaw_cos / 4096,
        -pitch_sin * yaw_sin / 4096,
        pitch_cos / 64,
    )
    wu = float32(
        _float32_multiply(8192.0, float32(u - SKY_LOGICAL_WIDTH // 2))
        / float32(SKY_LOGICAL_WIDTH)
    )
    wv = float32(
        _float32_multiply(8192.0, float32(SKY_LOGICAL_HEIGHT // 2 - v))
        / float32(SKY_LOGICAL_WIDTH)
    )
    endpoint = [
        _float32_add(
            _float32_add(
                _float32_multiply(4096.0, float32(forward_component)),
                _float32_multiply(wu, float32(right_component)),
            ),
            _float32_multiply(wv, float32(up_component)),
        )
        for forward_component, right_component, up_component in zip(
            forward, right, up, strict=True
        )
    ]
    endpoint[2] = _float32_multiply(endpoint[2], 3.0)
    squared = _float32_add(
        _float32_add(
            _float32_multiply(endpoint[0], endpoint[0]),
            _float32_multiply(endpoint[1], endpoint[1]),
        ),
        _float32_multiply(endpoint[2], endpoint[2]),
    )
    magnitude = float32(math.sqrt(squared))
    if magnitude <= 0.0:
        raise SkyAssetError("sky float view direction cannot be normalized")
    inverse = float32(float32(1.0) / magnitude)
    return tuple(
        math.trunc(
            _float32_multiply(
                _float32_add(
                    float32(projected_phase),
                    _float32_multiply(
                        float(SKY_PROJECTION_SCALE),
                        _float32_multiply(component, inverse),
                    ),
                ),
                float(1 << SKY_FIXED_FRACTION_BITS),
            )
        )
        for component in endpoint[:2]
    )


def quake_sky_span_chunks(first_x: int, last_x: int) -> tuple[SkySpanChunk, ...]:
    """Partition one face run exactly like released Quake's 32-pixel DDA."""

    if not 0 <= first_x <= last_x < SKY_LOGICAL_WIDTH:
        raise SkyAssetError("sky span escapes the logical row")
    chunks: list[SkySpanChunk] = []
    current = first_x
    remaining = last_x - first_x + 1
    while remaining:
        count = min(SKY_SPAN_MAXIMUM, remaining)
        remaining -= count
        if remaining:
            endpoint = current + count
            full_partition = True
        elif count > 1:
            endpoint = current + count - 1
            full_partition = False
        else:
            endpoint = current
            full_partition = False
        chunks.append(SkySpanChunk(current, endpoint, count, full_partition))
        current = endpoint
    return tuple(chunks)


def quake_sky_dda_step(current: int, endpoint: int, chunk: SkySpanChunk) -> int:
    """Return Quake's floor-/trunc0-split signed DDA step."""

    if chunk.pixel_count == 1:
        return 0
    difference = endpoint - current
    if chunk.full_partition:
        return difference // SKY_SPAN_MAXIMUM
    return trunc0_div(difference, chunk.pixel_count - 1)


def quake_sky_texel_pair(endpoint: tuple[int, int]) -> tuple[int, int]:
    """Reduce one signed Q16 endpoint to its modulo-128 source texels."""

    return (
        (endpoint[0] & SKY_FIXED_MASK) >> SKY_FIXED_FRACTION_BITS,
        (endpoint[1] & SKY_FIXED_MASK) >> SKY_FIXED_FRACTION_BITS,
    )


def is_quake_sky_texture_name(name: str) -> bool:
    """Match released Quake's case-sensitive three-byte ``sky`` prefix."""

    return name.startswith(SKY_TEXTURE_PREFIX)


def require_quake_sky_texture(texture: MipTextureLike) -> None:
    """Reject a sky miptex that cannot provide Quake's two 128-square layers."""

    if not is_quake_sky_texture_name(texture.name):
        raise SkyAssetError("sky texture name does not use the case-sensitive prefix")
    if texture.width != SKY_SOURCE_WIDTH or texture.height != SKY_SOURCE_HEIGHT:
        raise SkyAssetError("Quake sky miptex must be exactly 256x128")
    if len(texture.pixels) != SKY_SOURCE_BYTES:
        raise SkyAssetError("Quake sky miptex must contain 32768 level-zero bytes")


def classify_single_packed_sky(
    textures: Sequence[MipTextureLike], referenced_texture_ids: Sequence[int]
) -> SkyTextureContract:
    """Bind the canonical map's one referenced sky to its packed byte ID."""

    if len(referenced_texture_ids) > 0xFF:
        raise SkyAssetError("packed texture IDs exceed byte storage")
    if len(set(referenced_texture_ids)) != len(referenced_texture_ids):
        raise SkyAssetError("referenced texture IDs are not unique")
    candidates: list[tuple[int, int, MipTextureLike]] = []
    for packed_id, source_id in enumerate(referenced_texture_ids):
        if not 0 <= source_id < len(textures):
            raise SkyAssetError("referenced miptex ID is outside the texture lump")
        texture = textures[source_id]
        if is_quake_sky_texture_name(texture.name):
            require_quake_sky_texture(texture)
            candidates.append((source_id, packed_id, texture))
    if len(candidates) != 1:
        raise SkyAssetError(
            "canonical packed world must reference exactly one Quake sky miptex"
        )
    source_id, packed_id, texture = candidates[0]
    return SkyTextureContract(
        source_miptex_id=source_id,
        packed_texture_id=packed_id,
        name=texture.name,
        width=texture.width,
        height=texture.height,
        level_zero_bytes=len(texture.pixels),
        level_zero_sha256=hashlib.sha256(texture.pixels).hexdigest(),
    )


def require_opaque_marker_safety(
    textures: Sequence[MipTextureLike],
    colormap: bytes,
    *,
    marker: int = 0xFF,
) -> SkyMarkerSafety:
    """Prove a marker cannot be produced by an opaque texture/colormap path.

    Callers must omit textures routed exclusively through the sky postpass.
    Padding is intentionally absent: only directory-bounded level-zero payloads
    belong in ``textures``.
    """

    if not 0 <= marker <= 0xFF:
        raise SkyAssetError("sky ownership marker must fit one byte")
    texture_bytes = 0
    for texture in textures:
        if not texture.pixels:
            raise SkyAssetError("opaque marker proof received a missing texture")
        texture_bytes += len(texture.pixels)
        if marker in texture.pixels:
            raise SkyAssetError(
                f"opaque texture {texture.name!r} contains sky marker {marker}"
            )
    if not colormap or len(colormap) % 256:
        raise SkyAssetError(
            "opaque marker proof requires complete 256-byte colormap rows"
        )
    for offset, output in enumerate(colormap):
        source = offset & 0xFF
        if output == marker and source != marker:
            raise SkyAssetError(
                "colormap can synthesize the sky marker from a non-marker texel"
            )
    return SkyMarkerSafety(
        marker=marker,
        texture_count=len(textures),
        texture_bytes=texture_bytes,
        colormap_rows=len(colormap) // 256,
        colormap_bytes=len(colormap),
    )


def audit_opaque_palette_domain(
    textures: Sequence[MipTextureLike],
    colormaps: Sequence[bytes],
    alias_opaque_pixels: bytes,
) -> OpaquePaletteDomain:
    """Return every index reachable through canonical non-sky opaque paths.

    ``textures`` must contain only directory-bounded level-zero payloads that
    can reach the ordinary world/brush sampler. ``alias_opaque_pixels`` must
    already exclude transparent cells. The audit intentionally maps only
    source indices that actually occur, rather than treating unused colormap
    columns as reachable colors.
    """

    if not textures:
        raise SkyAssetError("opaque palette audit requires at least one texture")
    source_indices: set[int] = set()
    texture_bytes = 0
    for texture in textures:
        if not texture.pixels:
            raise SkyAssetError("opaque palette audit received a missing texture")
        texture_bytes += len(texture.pixels)
        source_indices.update(texture.pixels)
    if not colormaps:
        raise SkyAssetError("opaque palette audit requires at least one colormap")
    shaded_indices: set[int] = set()
    colormap_rows = 0
    colormap_bytes = 0
    for colormap in colormaps:
        if not colormap or len(colormap) % 256:
            raise SkyAssetError("opaque palette audit found a partial colormap row")
        rows = len(colormap) // 256
        colormap_rows += rows
        colormap_bytes += len(colormap)
        for row in range(rows):
            base = row * 256
            shaded_indices.update(colormap[base + index] for index in source_indices)
    alias_indices = set(alias_opaque_pixels)
    used_indices = source_indices | shaded_indices | alias_indices
    ordered_used = tuple(sorted(used_indices))
    return OpaquePaletteDomain(
        texture_count=len(textures),
        texture_bytes=texture_bytes,
        source_indices=tuple(sorted(source_indices)),
        colormap_count=len(colormaps),
        colormap_rows=colormap_rows,
        colormap_bytes=colormap_bytes,
        shaded_indices=tuple(sorted(shaded_indices)),
        alias_opaque_texels=len(alias_opaque_pixels),
        alias_indices=tuple(sorted(alias_indices)),
        used_indices=ordered_used,
        used_indices_sha256=hashlib.sha256(bytes(ordered_used)).hexdigest(),
        safe_indices=tuple(sorted(set(range(256)) - used_indices)),
    )


def assign_sky_face_markers(
    domain: OpaquePaletteDomain, face_ids: Sequence[int]
) -> tuple[tuple[int, int], ...]:
    """Assign bounded safe markers in deterministic face-ID order.

    The renderer only needs to distinguish sky from ordinary opaque output;
    separate sky faces do not need separate palette values.  Reuse the
    runtime's bounded marker set when a BSP contains more sky faces than the
    palette proof exposes safe values for.
    """

    ordered_faces = tuple(sorted(face_ids))
    if not ordered_faces or len(set(ordered_faces)) != len(ordered_faces):
        raise SkyAssetError("sky marker assignment requires unique face IDs")
    if any(not 0 <= face <= 0xFFFF for face in ordered_faces):
        raise SkyAssetError("sky marker face ID escapes uint16 storage")
    markers = domain.safe_indices[:SKY_RUNTIME_MARKER_CAPACITY]
    if not markers:
        raise SkyAssetError("opaque palette domain has no safe sky marker")
    return tuple(
        (face, markers[index % len(markers)])
        for index, face in enumerate(ordered_faces)
    )


def quake_sky_clock(surface_time: float) -> SkyClock:
    """Mirror Quake's double reduction, then float32 clock and phase math."""

    if (
        not math.isfinite(surface_time)
        or surface_time < 0.0
        or surface_time > MAX_QUAKE_SURFACE_TIME
    ):
        raise SkyAssetError("Quake sky surface time must be finite and nonnegative")
    cycles = int(surface_time / SKY_REPEAT_SECONDS)
    wrapped = float32(surface_time - cycles * SKY_REPEAT_SECONDS)
    projected = float32(wrapped * float32(float(SKY_SPEED)))
    projected_bits = struct.unpack("<I", struct.pack("<f", projected))[0]
    # Multiplication by 2^16 is exact for this bounded normal float. Truncation
    # matches the C++ cast used by the fixed-point span sampler.
    projected_q16 = math.trunc(float32(projected * (1 << SKY_FIXED_FRACTION_BITS)))
    projected_low23 = projected_q16 & SKY_FIXED_MASK | (
        projected_q16 & ((1 << SKY_FIXED_FRACTION_BITS) - 1)
    )
    return SkyClock(
        surface_time=surface_time,
        wrapped_time=wrapped,
        projected_phase=projected,
        projected_phase_float32_bits=projected_bits,
        projected_phase_q16=projected_q16,
        projected_phase_low23=projected_low23,
        composite_shift=(projected_q16 >> SKY_FIXED_FRACTION_BITS)
        & (SKY_LAYER_SIZE - 1),
    )


def pack_phase_low23(value: int) -> bytes:
    """Pack one directly consumable modulo-128 Q16 phase in three bytes."""

    if not 0 <= value < (1 << 23):
        raise SkyAssetError("sky phase record is outside unsigned 23-bit storage")
    return value.to_bytes(SKY_PHASE_RECORD_BYTES, "little")


def unpack_phase_low23(record: bytes) -> int:
    """Decode one fail-closed three-byte sky phase record."""

    if len(record) != SKY_PHASE_RECORD_BYTES:
        raise SkyAssetError("sky phase record must contain exactly three bytes")
    value = int.from_bytes(record, "little")
    if value & ~((1 << 23) - 1):
        raise SkyAssetError("sky phase record sets the reserved high bit")
    return value


def build_demo_phase_asset(
    first_server_time: float, pose_count: int, sample_rate_hz: int
) -> bytes:
    """Pack one exact modulo-128 Q16 phase for every canonical source pose."""

    if pose_count <= 0:
        raise SkyAssetError("sky phase asset requires at least one source pose")
    if sample_rate_hz <= 0:
        raise SkyAssetError("sky phase asset requires a positive sample rate")
    # Validate the origin even if the final pose count is one.
    quake_sky_clock(first_server_time)
    records = bytearray()
    for source_pose in range(pose_count):
        surface_time = first_server_time + source_pose / sample_rate_hz
        records.extend(
            pack_phase_low23(quake_sky_clock(surface_time).projected_phase_low23)
        )
    return bytes(records)


def phase_asset_record(asset: bytes, source_pose: int) -> int:
    """Read one canonical source-pose record, rejecting malformed assets."""

    if len(asset) == 0 or len(asset) % SKY_PHASE_RECORD_BYTES:
        raise SkyAssetError("sky phase asset has an invalid byte count")
    pose_count = len(asset) // SKY_PHASE_RECORD_BYTES
    if not 0 <= source_pose < pose_count:
        raise SkyAssetError("sky source pose is outside the phase asset")
    offset = source_pose * SKY_PHASE_RECORD_BYTES
    return unpack_phase_low23(asset[offset : offset + SKY_PHASE_RECORD_BYTES])


def schedule_phase_low23(
    asset: bytes,
    schedule: str,
    *,
    source_pose: int | None = None,
    explicit_surface_time: float | None = None,
) -> int:
    """Resolve schedule time without allowing presentation cadence to leak in."""

    if schedule in {"ordered", "realtime", "live"}:
        if source_pose is None or explicit_surface_time is not None:
            raise SkyAssetError("demo sky schedules require exactly one source pose")
        return phase_asset_record(asset, source_pose)
    if schedule in {"fly", "static"}:
        if source_pose is not None or explicit_surface_time is None:
            raise SkyAssetError(
                "fly/static sky requires exactly one explicit surface time"
            )
        return quake_sky_clock(explicit_surface_time).projected_phase_low23
    raise SkyAssetError(f"unknown sky schedule: {schedule}")


def compose_quake_sky_tile(texture: MipTextureLike, composite_shift: int) -> bytes:
    """Build Quake's masked foreground and opaque background sampling rows."""

    require_quake_sky_texture(texture)
    if not 0 <= composite_shift < SKY_LAYER_SIZE:
        raise SkyAssetError("sky composite shift is outside 0..127")
    tile = bytearray(SKY_SOURCE_BYTES)
    for y in range(SKY_LAYER_SIZE):
        foreground_y = (y + composite_shift) & (SKY_LAYER_SIZE - 1)
        for x in range(SKY_LAYER_SIZE):
            foreground_x = (x + composite_shift) & (SKY_LAYER_SIZE - 1)
            foreground = texture.pixels[foreground_y * SKY_SOURCE_WIDTH + foreground_x]
            background = texture.pixels[y * SKY_SOURCE_WIDTH + SKY_LAYER_SIZE + x]
            row = y * SKY_SOURCE_WIDTH
            tile[row + x] = foreground if foreground != 0 else background
            tile[row + SKY_LAYER_SIZE + x] = background
    return bytes(tile)


def sample_quake_sky_tile(tile: bytes, s_q16: int, t_q16: int) -> int:
    """Apply the released sampler's signed-16.16 modulo mask."""

    if len(tile) != SKY_SOURCE_BYTES:
        raise SkyAssetError("composited sky tile must contain 32768 bytes")
    s_bits = s_q16 & 0xFFFFFFFF
    t_bits = t_q16 & 0xFFFFFFFF
    offset = ((t_bits & SKY_FIXED_MASK) >> 8) + ((s_bits & SKY_FIXED_MASK) >> 16)
    return tile[offset]
