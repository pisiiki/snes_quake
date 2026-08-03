"""Build and decode the compact QBSE replay used by Quake brush assets."""

from __future__ import annotations

import hashlib
import math
import struct
from dataclasses import dataclass
from typing import Any

from quake_brush_replay import (
    BRUSH_REPLAY_SAMPLE_RATE_HZ,
    BRUSH_REPLAY_STEP_RATE_HZ,
    BrushEntityState,
    CanonicalBrushReplay,
    canonical_server_time,
    require_translation_only,
    step_row_indices,
)


COMPACT_REPLAY_MAGIC = b"QBSE"
COMPACT_REPLAY_VERSION = 1
COMPACT_REPLAY_HEADER = struct.Struct("<4sHHQ8H")
COMPACT_ENTITY = struct.Struct("<BBBBHhhh")
COMPACT_VARIANT = struct.Struct("<H")
COMPACT_EVENT = struct.Struct("<HB")


@dataclass(frozen=True)
class DecodedCompactReplay:
    """Losslessly expanded QBSE rows plus its fixed-rate contract."""

    sample_rate_hz: int
    camera_track_fnv1a64: int
    step_stride: int
    texture_clock_bias: int
    rows: tuple[tuple[BrushEntityState, ...], ...]


@dataclass(frozen=True)
class CompactReplayBuild:
    payload: bytes
    metadata: dict[str, Any]
    slot_by_entity: dict[int, int]
    local_variant_by_state: dict[BrushEntityState, int]
    row_transforms: tuple[tuple[tuple[int, int], ...], ...]


def quantize_q3(value: float, *, label: str) -> int:
    """Return an exact signed Q3 coordinate with a contextual error label."""
    quantized = round(value * 8.0)
    if not -0x8000 <= quantized <= 0x7FFF:
        raise ValueError(f"{label} exceeds signed Q3 storage")
    if quantized / 8.0 != value:
        raise ValueError(f"{label} is not protocol Q3 exact")
    return quantized


def _signed_15(value: int) -> int:
    return value & 0x7FFF


def _decode_signed_15(value: int) -> int:
    value &= 0x7FFF
    return value - 0x8000 if value & 0x4000 else value


def require_compact_translation_only(replay: CanonicalBrushReplay) -> None:
    """Reject rotation in both replay rows and the signon brush state."""
    require_translation_only(replay)
    for state in replay.signon_brushes:
        if state.angles != (0.0, 0.0, 0.0):
            raise ValueError(
                "nonzero brush angle at sample signon, "
                f"entity {state.entity_number}, inline model "
                f"*{state.inline_model}: {state.angles}"
            )


def build_compact_replay(replay: CanonicalBrushReplay) -> CompactReplayBuild:
    """Build one canonical QBSE event stream and its asset metadata."""
    if not replay.rows:
        raise ValueError("compact brush replay cannot be empty")
    if replay.sample_rate_hz != BRUSH_REPLAY_SAMPLE_RATE_HZ:
        raise ValueError("compact brush replay must use the canonical 30 Hz rate")
    if len(replay.rows) > 0xFFFF:
        raise ValueError("compact brush replay row count exceeds uint16")
    require_compact_translation_only(replay)

    states_by_entity: dict[int, set[BrushEntityState]] = {}
    for row in replay.rows:
        for state in row.brushes:
            states_by_entity.setdefault(state.entity_number, set()).add(state)
    entity_ids = sorted(states_by_entity)
    if len(entity_ids) > 0x7F:
        raise ValueError("compact brush replay exceeds 127 entity slots")

    descriptors = bytearray()
    variants = bytearray()
    slot_by_entity = {
        entity_number: slot for slot, entity_number in enumerate(entity_ids)
    }
    local_variant_by_state: dict[BrushEntityState, int] = {}
    first_variant = 0
    descriptor_metadata: list[dict[str, Any]] = []
    for entity_number in entity_ids:
        entity_states = sorted(
            states_by_entity[entity_number],
            key=lambda state: (
                state.frame,
                *(quantize_q3(value, label="brush origin") for value in state.origin),
            ),
        )
        model_ids = {state.inline_model for state in entity_states}
        model_indices = {state.model_index for state in entity_states}
        if len(model_ids) != 1 or len(model_indices) != 1:
            raise ValueError(
                f"compact brush entity {entity_number} changes model identity"
            )
        inline_model = entity_states[0].inline_model
        if model_indices != {inline_model + 1}:
            raise ValueError(
                f"compact brush entity {entity_number} has a noncanonical "
                "model-precache identity"
            )
        if not 0 < entity_number <= 0xFF or not 0 < inline_model <= 0xFF:
            raise ValueError("compact brush entity/model identity exceeds uint8")
        origins_q3 = tuple(
            tuple(quantize_q3(value, label="brush origin") for value in state.origin)
            for state in entity_states
        )
        changing_axes = [
            axis
            for axis in range(3)
            if len({origin[axis] for origin in origins_q3}) > 1
        ]
        if len(changing_axes) > 1:
            raise ValueError(
                f"compact brush entity {entity_number} moves on multiple axes"
            )
        motion_axis = changing_axes[0] if changing_axes else 0xFF
        base_origin = origins_q3[0]
        if len(entity_states) > 0xFF:
            raise ValueError(
                f"compact brush entity {entity_number} exceeds 255 variants"
            )
        if first_variant + len(entity_states) > 0xFFFF:
            raise ValueError("compact brush variants exceed uint16 addressing")
        descriptors.extend(
            COMPACT_ENTITY.pack(
                entity_number,
                inline_model,
                motion_axis,
                len(entity_states),
                first_variant,
                *base_origin,
            )
        )
        for local_variant, (state, origin_q3) in enumerate(
            zip(entity_states, origins_q3, strict=True)
        ):
            if not 0 <= state.frame <= 1:
                raise ValueError(
                    f"compact brush entity {entity_number} frame "
                    f"{state.frame} exceeds one-bit storage"
                )
            coordinate = 0 if motion_axis == 0xFF else origin_q3[motion_axis]
            if not -0x4000 <= coordinate <= 0x3FFF:
                raise ValueError(
                    f"compact brush entity {entity_number} motion coordinate "
                    "exceeds signed 15-bit Q3 storage"
                )
            variants.extend(
                COMPACT_VARIANT.pack(_signed_15(coordinate) | (state.frame << 15))
            )
            local_variant_by_state[state] = local_variant
        descriptor_metadata.append(
            {
                "slot": slot_by_entity[entity_number],
                "entity": entity_number,
                "inlineModel": inline_model,
                "modelPrecacheIndex": inline_model + 1,
                "motionAxis": None if motion_axis == 0xFF else motion_axis,
                "baseOriginQ3": list(base_origin),
                "firstVariant": first_variant,
                "variantCount": len(entity_states),
            }
        )
        first_variant += len(entity_states)

    events = bytearray()
    previous: dict[int, BrushEntityState] = {}
    event_count = 0
    transition_count = 0
    row_transforms: list[tuple[tuple[int, int], ...]] = []
    for row in replay.rows:
        current = {state.entity_number: state for state in row.brushes}
        changed = [
            entity
            for entity in entity_ids
            if previous.get(entity) != current.get(entity)
        ]
        if changed:
            if len(changed) > 0xFF:
                raise ValueError(
                    f"compact brush event at row {row.index} exceeds 255 changes"
                )
            events.extend(COMPACT_EVENT.pack(row.index, len(changed)))
            for entity in changed:
                slot = slot_by_entity[entity]
                state = current.get(entity)
                events.append(slot | (0x80 if state is not None else 0))
                if state is not None:
                    events.append(local_variant_by_state[state])
            event_count += 1
            transition_count += len(changed)
        row_transforms.append(
            tuple(
                (
                    slot_by_entity[state.entity_number],
                    local_variant_by_state[state],
                )
                for state in row.brushes
            )
        )
        previous = current

    step_stride = replay.sample_rate_hz // BRUSH_REPLAY_STEP_RATE_HZ
    texture_clock_bias = math.floor(replay.first_server_time * replay.sample_rate_hz)
    for row in replay.rows:
        derived_tenths = (row.index + texture_clock_bias) // (
            replay.sample_rate_hz // 10
        )
        source_tenths = math.floor(
            canonical_server_time(
                replay.first_server_time, replay.sample_rate_hz, row.index
            )
            * 10
        )
        if derived_tenths != source_tenths:
            raise AssertionError(
                f"integer texture clock diverges at canonical row {row.index}"
            )
    header = COMPACT_REPLAY_HEADER.pack(
        COMPACT_REPLAY_MAGIC,
        COMPACT_REPLAY_VERSION,
        replay.sample_rate_hz,
        replay.camera_track_fnv1a64,
        len(replay.rows),
        len(entity_ids),
        event_count,
        transition_count,
        first_variant,
        step_stride,
        texture_clock_bias,
        0,
    )
    payload = bytes(header + descriptors + variants + events)
    decoded = decode_compact_replay(payload)
    expected = tuple(row.brushes for row in replay.rows)
    if decoded.rows != expected:
        raise AssertionError("compact brush replay does not round-trip exactly")
    metadata = {
        "magic": COMPACT_REPLAY_MAGIC.decode("ascii"),
        "version": COMPACT_REPLAY_VERSION,
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "headerBytes": COMPACT_REPLAY_HEADER.size,
        "entityRecordBytes": COMPACT_ENTITY.size,
        "variantRecordBytes": COMPACT_VARIANT.size,
        "eventHeaderBytes": COMPACT_EVENT.size,
        "rowCount": len(replay.rows),
        "entitySlotCount": len(entity_ids),
        "eventRowCount": event_count,
        "transitionCount": transition_count,
        "variantCount": first_variant,
        "stepStride": step_stride,
        "stepRows": {
            "count": len(step_row_indices(len(replay.rows))),
            "formula": "row = n * stepStride",
            "last": step_row_indices(len(replay.rows))[-1],
        },
        "timingStorage": "none; row index is the canonical camera index",
        "textureAnimationClock": {
            "tenthsFormula": "(rowIndex + textureClockBias) / 3, integer floor",
            "textureClockBias": texture_clock_bias,
            "firstServerTime": replay.first_server_time,
        },
        "entities": descriptor_metadata,
    }
    return CompactReplayBuild(
        payload,
        metadata,
        slot_by_entity,
        local_variant_by_state,
        tuple(row_transforms),
    )


def encode_compact_replay(replay: CanonicalBrushReplay) -> bytes:
    """Encode state changes only; canonical row indices remain the sole clock."""
    return build_compact_replay(replay).payload


def decode_compact_replay(data: bytes) -> DecodedCompactReplay:
    """Expand a QBSE event stream into all canonical brush rows."""
    if len(data) < COMPACT_REPLAY_HEADER.size:
        raise ValueError("truncated compact brush replay header")
    (
        magic,
        version,
        sample_rate,
        camera_hash,
        row_count,
        entity_count,
        event_count,
        transition_count,
        variant_count,
        step_stride,
        texture_clock_bias,
        reserved,
    ) = COMPACT_REPLAY_HEADER.unpack_from(data)
    if magic != COMPACT_REPLAY_MAGIC or version != COMPACT_REPLAY_VERSION:
        raise ValueError("unsupported compact brush replay")
    if (
        sample_rate != BRUSH_REPLAY_SAMPLE_RATE_HZ
        or row_count == 0
        or entity_count > 0x7F
        or step_stride != sample_rate // BRUSH_REPLAY_STEP_RATE_HZ
        or reserved
    ):
        raise ValueError("compact brush replay contract is invalid")
    cursor = COMPACT_REPLAY_HEADER.size
    descriptor_bytes = entity_count * COMPACT_ENTITY.size
    variant_bytes = variant_count * COMPACT_VARIANT.size
    if cursor + descriptor_bytes + variant_bytes > len(data):
        raise ValueError("truncated compact brush replay tables")
    descriptors = tuple(
        COMPACT_ENTITY.unpack_from(data, cursor + slot * COMPACT_ENTITY.size)
        for slot in range(entity_count)
    )
    cursor += descriptor_bytes
    raw_variants = tuple(
        COMPACT_VARIANT.unpack_from(data, cursor + index * 2)[0]
        for index in range(variant_count)
    )
    cursor += variant_bytes

    variants: list[tuple[BrushEntityState, ...]] = []
    for entity, inline_model, axis, count, first, bx, by, bz in descriptors:
        if (
            entity == 0
            or inline_model == 0
            or axis not in {0, 1, 2, 0xFF}
            or count == 0
            or first + count > len(raw_variants)
        ):
            raise ValueError("compact brush entity descriptor is invalid")
        states: list[BrushEntityState] = []
        base = (bx, by, bz)
        for packed in raw_variants[first : first + count]:
            origin = list(base)
            coordinate = _decode_signed_15(packed)
            if axis == 0xFF:
                if coordinate != 0:
                    raise ValueError("static compact brush variant moves")
            else:
                origin[axis] = coordinate
            states.append(
                BrushEntityState(
                    entity,
                    inline_model + 1,
                    inline_model,
                    packed >> 15,
                    tuple(value / 8.0 for value in origin),
                    (0.0, 0.0, 0.0),
                )
            )
        variants.append(tuple(states))

    event_rows: dict[int, tuple[tuple[int, int | None], ...]] = {}
    seen_transitions = 0
    previous_row = -1
    for _event in range(event_count):
        if cursor + COMPACT_EVENT.size > len(data):
            raise ValueError("truncated compact brush event")
        row, change_count = COMPACT_EVENT.unpack_from(data, cursor)
        cursor += COMPACT_EVENT.size
        if row <= previous_row or row >= row_count or change_count == 0:
            raise ValueError("compact brush event row is invalid")
        changes: list[tuple[int, int | None]] = []
        for _change in range(change_count):
            if cursor >= len(data):
                raise ValueError("truncated compact brush transition")
            tag = data[cursor]
            cursor += 1
            slot = tag & 0x7F
            if slot >= entity_count:
                raise ValueError("compact brush transition names a missing slot")
            variant: int | None = None
            if tag & 0x80:
                if cursor >= len(data):
                    raise ValueError("truncated compact brush active transition")
                variant = data[cursor]
                cursor += 1
                if variant >= len(variants[slot]):
                    raise ValueError("compact brush transition names a missing variant")
            changes.append((slot, variant))
        if len({slot for slot, _variant in changes}) != len(changes):
            raise ValueError("compact brush event changes one slot twice")
        event_rows[row] = tuple(changes)
        seen_transitions += change_count
        previous_row = row
    if cursor != len(data) or seen_transitions != transition_count:
        raise ValueError("compact brush replay size/count is inconsistent")

    active: dict[int, int] = {}
    rows: list[tuple[BrushEntityState, ...]] = []
    for row in range(row_count):
        for slot, variant in event_rows.get(row, ()):
            if variant is None:
                active.pop(slot, None)
            else:
                active[slot] = variant
        rows.append(
            tuple(variants[slot][variant] for slot, variant in sorted(active.items()))
        )
    return DecodedCompactReplay(
        sample_rate,
        camera_hash,
        step_stride,
        texture_clock_bias,
        tuple(rows),
    )
