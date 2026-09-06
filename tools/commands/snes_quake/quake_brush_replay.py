"""Canonical fixed-rate replay and binary codec for Quake inline models."""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass

from quake_demo import (
    CameraSample,
    EntityState,
    decode_camera_entity_track,
    sample_newest_due_indices,
)


BRUSH_REPLAY_MAGIC = b"QBR2"
BRUSH_REPLAY_VERSION = 2
BRUSH_REPLAY_SAMPLE_RATE_HZ = 20
BRUSH_REPLAY_STEP_RATE_HZ = 2
BRUSH_REPLAY_TEXTURE_RATE_HZ = 10
BRUSH_REPLAY_HEADER = struct.Struct("<4sHHfQIII")
BRUSH_REPLAY_SNAPSHOT = struct.Struct("<IH")
BRUSH_REPLAY_STATE = struct.Struct("<HHHBhhhbbb")
FNV1A64_OFFSET = 0xCBF29CE484222325
FNV1A64_PRIME = 0x100000001B3


@dataclass(frozen=True, order=True)
class BrushEntityState:
    entity_number: int
    model_index: int
    inline_model: int
    frame: int
    origin: tuple[float, float, float]
    angles: tuple[float, float, float]


@dataclass(frozen=True)
class CanonicalBrushRow:
    index: int
    source_index: int
    source_record: int
    server_time: float
    camera: CameraSample
    brushes: tuple[BrushEntityState, ...]


@dataclass(frozen=True)
class CanonicalBrushReplay:
    forced_track: int
    sample_rate_hz: int
    first_server_time: float
    camera_track_fnv1a64: int
    model_precache: tuple[str, ...]
    source_sample_count: int
    signon_brushes: tuple[BrushEntityState, ...]
    rows: tuple[CanonicalBrushRow, ...]


@dataclass(frozen=True)
class DecodedBrushReplay:
    sample_rate_hz: int
    first_server_time: float
    camera_track_fnv1a64: int
    rows: tuple[tuple[BrushEntityState, ...], ...]


def _inline_model(name: str) -> int | None:
    if not name.startswith("*") or not name[1:].isdigit():
        return None
    model = int(name[1:])
    return model if model > 0 else None


def _brush_state(
    state: EntityState, model_precache: tuple[str, ...]
) -> BrushEntityState | None:
    if state.model_index <= 0 or state.model_index >= len(model_precache):
        return None
    inline_model = _inline_model(model_precache[state.model_index])
    if inline_model is None:
        return None
    return BrushEntityState(
        state.entity_number,
        state.model_index,
        inline_model,
        state.frame,
        state.origin,
        state.angles,
    )


def active_inline_brushes(
    states: tuple[EntityState, ...], model_precache: tuple[str, ...]
) -> tuple[BrushEntityState, ...]:
    """Keep only current, renderable non-world BSP packet entities."""
    return tuple(
        brush
        for state in states
        if (brush := _brush_state(state, model_precache)) is not None
    )


def fnv1a64(data: bytes) -> int:
    value = FNV1A64_OFFSET
    for byte in data:
        value = ((value ^ byte) * FNV1A64_PRIME) & 0xFFFFFFFFFFFFFFFF
    return value


def encode_precise_camera_track(rows: tuple[CanonicalBrushRow, ...]) -> bytes:
    records = bytearray()
    for row in rows:
        camera = row.camera
        if camera.view_angles[2] != 0.0:
            raise ValueError("precise camera track cannot omit nonzero roll")
        position_q3 = tuple(round(value * 8.0) for value in camera.origin)
        if any(value < -0x8000 or value > 0x7FFF for value in position_q3):
            raise ValueError("precise camera Q3 position exceeds int16 storage")
        yaw = round((camera.view_angles[1] % 360.0) * 65536.0 / 360.0) & 0xFFFF
        pitch = (
            round((camera.view_angles[0] % 360.0) * 65536.0 / 360.0) & 0xFFFF
        )
        records.extend(struct.pack("<hhhHH", *position_q3, yaw, pitch))
    return bytes(records)


def extract_canonical_brush_replay(
    data: bytes,
    map_entry: str,
    sample_rate_hz: int = BRUSH_REPLAY_SAMPLE_RATE_HZ,
) -> CanonicalBrushReplay:
    """Point-sample camera and brush state with one shared timeline mapping."""
    track = decode_camera_entity_track(data, map_entry)
    source_times = [sample.camera.server_time for sample in track.samples]
    source_indices = sample_newest_due_indices(source_times, sample_rate_hz)
    rows: list[CanonicalBrushRow] = []
    for index, source_index in enumerate(source_indices):
        source = track.samples[source_index]
        brushes = active_inline_brushes(source.entities, track.model_precache)
        rows.append(
            CanonicalBrushRow(
                index,
                source_index,
                source.camera.record,
                source.camera.server_time,
                source.camera,
                brushes,
            )
        )
    signon_brushes = tuple(
        brush
        for state in track.baselines
        if (brush := _brush_state(state, track.model_precache)) is not None
    )
    canonical_rows = tuple(rows)
    return CanonicalBrushReplay(
        track.forced_track,
        sample_rate_hz,
        source_times[0],
        fnv1a64(encode_precise_camera_track(canonical_rows)),
        track.model_precache,
        len(track.samples),
        signon_brushes,
        canonical_rows,
    )


def step_row_indices(
    row_count: int,
    sample_rate_hz: int = BRUSH_REPLAY_SAMPLE_RATE_HZ,
    step_rate_hz: int = BRUSH_REPLAY_STEP_RATE_HZ,
) -> tuple[int, ...]:
    if row_count <= 0 or sample_rate_hz <= 0 or step_rate_hz <= 0:
        raise ValueError("replay row count and sample rates must be positive")
    if sample_rate_hz % step_rate_hz:
        raise ValueError("step sample rate must divide the canonical sample rate")
    return tuple(range(0, row_count, sample_rate_hz // step_rate_hz))


def require_translation_only(replay: CanonicalBrushReplay) -> None:
    """Reject visual rotation where a translation-only consumer would lie."""
    for row in replay.rows:
        for state in row.brushes:
            if state.angles != (0.0, 0.0, 0.0):
                raise ValueError(
                    "nonzero brush angle at "
                    f"sample {row.index}, entity {state.entity_number}, "
                    f"inline model *{state.inline_model}: {state.angles}"
                )


def canonical_server_time(
    first_server_time: float, sample_rate_hz: int, row_index: int
) -> float:
    """Return the fixed playback clock, independent of selected source time."""
    if (
        not math.isfinite(first_server_time)
        or first_server_time < 0.0
        or sample_rate_hz <= 0
        or row_index < 0
    ):
        raise ValueError("canonical replay clock arguments are invalid")
    return first_server_time + row_index / sample_rate_hz


def _coord_q3(value: float) -> int:
    quantized = round(value * 8.0)
    if quantized < -0x8000 or quantized > 0x7FFF:
        raise ValueError(f"brush coordinate {value} exceeds signed Q3 storage")
    if quantized / 8.0 != value:
        raise ValueError(f"brush coordinate {value} is not protocol Q3 exact")
    return quantized


def _angle_i8(value: float) -> int:
    quantized = round(value * 256.0 / 360.0)
    if quantized < -0x80 or quantized > 0x7F:
        raise ValueError(f"brush angle {value} exceeds protocol signed-byte storage")
    decoded = quantized * 360.0 / 256.0
    if decoded != value:
        raise ValueError(f"brush angle {value} is not protocol i8 exact")
    return quantized


def _pack_state(state: BrushEntityState) -> bytes:
    if not 0 < state.entity_number <= 0xFFFF:
        raise ValueError("brush entity number must fit nonzero uint16 storage")
    if not 0 < state.model_index <= 0xFFFF:
        raise ValueError(
            "brush model-precache index must fit nonzero uint16 storage"
        )
    if not 0 < state.inline_model <= 0xFFFF:
        raise ValueError("inline model identity exceeds uint16 storage")
    if not 0 <= state.frame <= 0xFF:
        raise ValueError("brush frame exceeds uint8 storage")
    return BRUSH_REPLAY_STATE.pack(
        state.entity_number,
        state.model_index,
        state.inline_model,
        state.frame,
        *(_coord_q3(value) for value in state.origin),
        *(_angle_i8(value) for value in state.angles),
    )


def encode_brush_replay(replay: CanonicalBrushReplay) -> bytes:
    """Pack full active sets while deduplicating fixed-rate snapshots."""
    if not replay.rows:
        raise ValueError("cannot encode an empty brush replay")
    if (
        not 0 < replay.sample_rate_hz <= 0xFFFF
        or replay.sample_rate_hz % BRUSH_REPLAY_STEP_RATE_HZ
        or replay.sample_rate_hz % BRUSH_REPLAY_TEXTURE_RATE_HZ
    ):
        raise ValueError(
            "brush replay sample rate must fit uint16 and be divisible by "
            "the 2 Hz step and 10 Hz texture clocks"
        )
    if not math.isfinite(replay.first_server_time) or replay.first_server_time < 0.0:
        raise ValueError(
            "brush replay first server time must be finite and nonnegative"
        )
    if not 0 <= replay.camera_track_fnv1a64 <= 0xFFFFFFFFFFFFFFFF:
        raise ValueError("brush replay camera fingerprint exceeds uint64 storage")
    if tuple(row.index for row in replay.rows) != tuple(range(len(replay.rows))):
        raise ValueError("brush replay rows must have contiguous canonical indices")
    snapshots: list[tuple[BrushEntityState, ...]] = []
    snapshot_ids: dict[tuple[BrushEntityState, ...], int] = {}
    row_ids: list[int] = []
    for row in replay.rows:
        if tuple(sorted(row.brushes)) != row.brushes:
            raise ValueError(f"brush state at sample {row.index} is not sorted")
        if any(
            left.entity_number >= right.entity_number
            for left, right in zip(row.brushes, row.brushes[1:])
        ):
            raise ValueError(
                f"brush state at sample {row.index} has duplicate entity identities"
            )
        snapshot_id = snapshot_ids.get(row.brushes)
        if snapshot_id is None:
            snapshot_id = len(snapshots)
            if snapshot_id > 0xFFFF:
                raise ValueError("brush replay has too many unique snapshots")
            snapshot_ids[row.brushes] = snapshot_id
            snapshots.append(row.brushes)
        row_ids.append(snapshot_id)

    if len(snapshots) > 0x10000:
        raise ValueError("brush replay has too many unique snapshots")
    states = [state for snapshot in snapshots for state in snapshot]
    output = bytearray(
        BRUSH_REPLAY_HEADER.pack(
            BRUSH_REPLAY_MAGIC,
            BRUSH_REPLAY_VERSION,
            replay.sample_rate_hz,
            replay.first_server_time,
            replay.camera_track_fnv1a64,
            len(row_ids),
            len(snapshots),
            len(states),
        )
    )
    output.extend(struct.pack(f"<{len(row_ids)}H", *row_ids))
    state_offset = 0
    for snapshot in snapshots:
        if len(snapshot) > 0xFFFF:
            raise ValueError("brush snapshot exceeds uint16 state count")
        output.extend(BRUSH_REPLAY_SNAPSHOT.pack(state_offset, len(snapshot)))
        state_offset += len(snapshot)
    for state in states:
        output.extend(_pack_state(state))
    return bytes(output)


def decode_brush_replay(data: bytes) -> DecodedBrushReplay:
    if len(data) < BRUSH_REPLAY_HEADER.size:
        raise ValueError("truncated brush replay header")
    (
        magic,
        version,
        rate,
        first_server_time,
        camera_track_fnv1a64,
        row_count,
        snapshot_count,
        state_count,
    ) = BRUSH_REPLAY_HEADER.unpack_from(data)
    if magic != BRUSH_REPLAY_MAGIC or version != BRUSH_REPLAY_VERSION:
        raise ValueError("unsupported brush replay format")
    if (
        rate <= 0
        or rate % BRUSH_REPLAY_STEP_RATE_HZ
        or rate % BRUSH_REPLAY_TEXTURE_RATE_HZ
        or not math.isfinite(first_server_time)
        or first_server_time < 0.0
        or row_count <= 0
        or snapshot_count <= 0
        or snapshot_count > 0x10000
    ):
        raise ValueError("brush replay has an invalid canonical contract")
    row_bytes = row_count * 2
    directory_bytes = snapshot_count * BRUSH_REPLAY_SNAPSHOT.size
    expected = (
        BRUSH_REPLAY_HEADER.size
        + row_bytes
        + directory_bytes
        + state_count * BRUSH_REPLAY_STATE.size
    )
    if len(data) != expected:
        raise ValueError(
            f"brush replay has {len(data)} bytes; expected exactly {expected}"
        )
    cursor = BRUSH_REPLAY_HEADER.size
    row_ids = struct.unpack_from(f"<{row_count}H", data, cursor) if row_count else ()
    cursor += row_bytes
    directory = tuple(
        BRUSH_REPLAY_SNAPSHOT.unpack_from(
            data, cursor + index * BRUSH_REPLAY_SNAPSHOT.size
        )
        for index in range(snapshot_count)
    )
    cursor += directory_bytes
    states: list[BrushEntityState] = []
    for index in range(state_count):
        raw = BRUSH_REPLAY_STATE.unpack_from(
            data, cursor + index * BRUSH_REPLAY_STATE.size
        )
        if raw[0] == 0 or raw[1] == 0 or raw[2] == 0:
            raise ValueError("brush replay state has a zero entity or model identity")
        states.append(
            BrushEntityState(
                raw[0],
                raw[1],
                raw[2],
                raw[3],
                tuple(value / 8.0 for value in raw[4:7]),
                tuple(value * 360.0 / 256.0 for value in raw[7:10]),
            )
        )
    snapshots: list[tuple[BrushEntityState, ...]] = []
    for offset, count in directory:
        if offset + count > len(states):
            raise ValueError("brush replay snapshot escapes the state array")
        snapshot = tuple(states[offset : offset + count])
        if any(
            left.entity_number >= right.entity_number
            for left, right in zip(snapshot, snapshot[1:])
        ):
            raise ValueError(
                "brush replay snapshot does not have strictly increasing "
                "entity identities"
            )
        snapshots.append(snapshot)
    if any(snapshot_id >= len(snapshots) for snapshot_id in row_ids):
        raise ValueError("brush replay row names a missing snapshot")
    return DecodedBrushReplay(
        rate,
        first_server_time,
        camera_track_fnv1a64,
        tuple(snapshots[index] for index in row_ids),
    )
