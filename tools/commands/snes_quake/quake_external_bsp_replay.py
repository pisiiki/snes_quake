"""Canonical fixed-rate replay and binary codec for external BSP entities."""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass

from quake_brush_replay import fnv1a64
from quake_demo import (
    CameraSample,
    decode_camera_entity_track,
    sample_newest_due_indices,
)


EXTERNAL_BSP_REPLAY_MAGIC = b"QER1"
EXTERNAL_BSP_REPLAY_VERSION = 1
EXTERNAL_BSP_REPLAY_HEADER = struct.Struct("<4sHHfQIIIHH")
EXTERNAL_BSP_REPLAY_MODEL = struct.Struct("<HB61s")
EXTERNAL_BSP_REPLAY_SNAPSHOT = struct.Struct("<IH")
EXTERNAL_BSP_REPLAY_STATE = struct.Struct("<HHBhhhbbb")


@dataclass(frozen=True, order=True)
class ExternalBspEntityState:
    entity_number: int
    model_slot: int
    frame: int
    origin: tuple[float, float, float]
    angles: tuple[float, float, float]


@dataclass(frozen=True)
class ExternalBspRow:
    camera: CameraSample
    entities: tuple[ExternalBspEntityState, ...]


@dataclass(frozen=True)
class CanonicalExternalBspReplay:
    sample_rate_hz: int
    first_server_time: float
    camera_track_fnv1a64: int
    model_names: tuple[str, ...]
    model_precache_indices: tuple[int, ...]
    source_sample_count: int
    rows: tuple[ExternalBspRow, ...]


@dataclass(frozen=True)
class DecodedExternalBspReplay:
    sample_rate_hz: int
    first_server_time: float
    camera_track_fnv1a64: int
    model_names: tuple[str, ...]
    model_precache_indices: tuple[int, ...]
    rows: tuple[tuple[ExternalBspEntityState, ...], ...]


def external_bsp_model_name(name: str, map_entry: str) -> str | None:
    normalized = name.replace("\\", "/").lower()
    if (
        normalized.startswith("*")
        or not normalized.endswith(".bsp")
        or normalized == map_entry.replace("\\", "/").lower()
    ):
        return None
    return normalized


def _encode_camera_rows(rows: tuple[ExternalBspRow, ...]) -> bytes:
    output = bytearray()
    for row in rows:
        camera = row.camera
        if camera.view_angles[2] != 0.0:
            raise ValueError("precise camera track cannot omit nonzero roll")
        position_q3 = tuple(round(value * 8.0) for value in camera.origin)
        if any(value < -0x8000 or value > 0x7FFF for value in position_q3):
            raise ValueError("precise camera Q3 position exceeds int16 storage")
        yaw = round((camera.view_angles[1] % 360.0) * 65536.0 / 360.0) & 0xFFFF
        pitch = round((camera.view_angles[0] % 360.0) * 65536.0 / 360.0) & 0xFFFF
        output.extend(struct.pack("<hhhHH", *position_q3, yaw, pitch))
    return bytes(output)


def extract_canonical_external_bsp_replay(
    data: bytes, map_entry: str, sample_rate_hz: int
) -> CanonicalExternalBspReplay:
    track = decode_camera_entity_track(data, map_entry)
    source_times = [sample.camera.server_time for sample in track.samples]
    source_indices = sample_newest_due_indices(source_times, sample_rate_hz)
    selected_models: dict[int, str] = {}
    for states in (
        track.baselines,
        *(track.samples[source_index].entities for source_index in source_indices),
    ):
        for state in states:
            if not 0 < state.model_index < len(track.model_precache):
                continue
            name = external_bsp_model_name(
                track.model_precache[state.model_index], map_entry
            )
            if name is not None:
                selected_models[state.model_index] = name
    model_precache_indices = tuple(sorted(selected_models))
    model_names = tuple(selected_models[index] for index in model_precache_indices)
    model_slots = {
        model_index: slot for slot, model_index in enumerate(model_precache_indices)
    }
    rows: list[ExternalBspRow] = []
    for source_index in source_indices:
        source = track.samples[source_index]
        entities = tuple(
            ExternalBspEntityState(
                state.entity_number,
                model_slots[state.model_index],
                state.frame,
                state.origin,
                state.angles,
            )
            for state in source.entities
            if state.model_index in model_slots
        )
        rows.append(ExternalBspRow(source.camera, entities))
    canonical_rows = tuple(rows)
    return CanonicalExternalBspReplay(
        sample_rate_hz,
        source_times[0],
        fnv1a64(_encode_camera_rows(canonical_rows)),
        model_names,
        model_precache_indices,
        len(track.samples),
        canonical_rows,
    )


def _coord_q3(value: float) -> int:
    quantized = round(value * 8.0)
    if not -0x8000 <= quantized <= 0x7FFF or quantized / 8.0 != value:
        raise ValueError(f"external BSP coordinate {value} is not signed-Q3 exact")
    return quantized


def _angle_i8(value: float) -> int:
    quantized = round(value * 256.0 / 360.0)
    if not -0x80 <= quantized <= 0x7F or quantized * 360.0 / 256.0 != value:
        raise ValueError(f"external BSP angle {value} is not signed-byte exact")
    return quantized


def encode_external_bsp_replay(replay: CanonicalExternalBspReplay) -> bytes:
    if not replay.rows:
        raise ValueError("external BSP replay requires rows")
    if (
        replay.sample_rate_hz <= 0
        or not math.isfinite(replay.first_server_time)
        or replay.first_server_time < 0.0
        or len(replay.model_names) != len(replay.model_precache_indices)
        or len(replay.model_names) >= 0x8000
    ):
        raise ValueError("external BSP replay has an invalid canonical contract")
    snapshots: list[tuple[ExternalBspEntityState, ...]] = []
    snapshot_ids: dict[tuple[ExternalBspEntityState, ...], int] = {}
    row_ids: list[int] = []
    for row_index, row in enumerate(replay.rows):
        if tuple(sorted(row.entities)) != row.entities or any(
            left.entity_number >= right.entity_number
            for left, right in zip(row.entities, row.entities[1:])
        ):
            raise ValueError(
                f"external BSP row {row_index} has noncanonical entity order"
            )
        snapshot_id = snapshot_ids.get(row.entities)
        if snapshot_id is None:
            snapshot_id = len(snapshots)
            if snapshot_id > 0xFFFF:
                raise ValueError("external BSP replay has too many snapshots")
            snapshot_ids[row.entities] = snapshot_id
            snapshots.append(row.entities)
        row_ids.append(snapshot_id)
    states = [state for snapshot in snapshots for state in snapshot]
    output = bytearray(
        EXTERNAL_BSP_REPLAY_HEADER.pack(
            EXTERNAL_BSP_REPLAY_MAGIC,
            EXTERNAL_BSP_REPLAY_VERSION,
            replay.sample_rate_hz,
            replay.first_server_time,
            replay.camera_track_fnv1a64,
            len(row_ids),
            len(snapshots),
            len(states),
            len(replay.model_names),
            EXTERNAL_BSP_REPLAY_MODEL.size,
        )
    )
    for model_index, name in zip(
        replay.model_precache_indices, replay.model_names, strict=True
    ):
        encoded = name.encode("ascii")
        if not 0 < model_index <= 0xFFFF or not 0 < len(encoded) <= 61:
            raise ValueError("external BSP model identity exceeds its record")
        output.extend(
            EXTERNAL_BSP_REPLAY_MODEL.pack(
                model_index, len(encoded), encoded.ljust(61, b"\0")
            )
        )
    output.extend(struct.pack(f"<{len(row_ids)}H", *row_ids))
    state_offset = 0
    for snapshot in snapshots:
        output.extend(EXTERNAL_BSP_REPLAY_SNAPSHOT.pack(state_offset, len(snapshot)))
        state_offset += len(snapshot)
    for state in states:
        if (
            not 0 < state.entity_number <= 0xFFFF
            or not 0 <= state.model_slot < len(replay.model_names)
            or not 0 <= state.frame <= 0xFF
        ):
            raise ValueError("external BSP entity identity exceeds its record")
        output.extend(
            EXTERNAL_BSP_REPLAY_STATE.pack(
                state.entity_number,
                state.model_slot,
                state.frame,
                *(_coord_q3(value) for value in state.origin),
                *(_angle_i8(value) for value in state.angles),
            )
        )
    return bytes(output)


def decode_external_bsp_replay(data: bytes) -> DecodedExternalBspReplay:
    if len(data) < EXTERNAL_BSP_REPLAY_HEADER.size:
        raise ValueError("truncated external BSP replay header")
    (
        magic,
        version,
        sample_rate,
        first_server_time,
        camera_hash,
        row_count,
        snapshot_count,
        state_count,
        model_count,
        model_bytes,
    ) = EXTERNAL_BSP_REPLAY_HEADER.unpack_from(data)
    if (
        magic != EXTERNAL_BSP_REPLAY_MAGIC
        or version != EXTERNAL_BSP_REPLAY_VERSION
        or sample_rate <= 0
        or row_count <= 0
        or snapshot_count <= 0
        or model_bytes != EXTERNAL_BSP_REPLAY_MODEL.size
        or not math.isfinite(first_server_time)
        or first_server_time < 0.0
    ):
        raise ValueError("external BSP replay has an invalid header")
    expected = (
        EXTERNAL_BSP_REPLAY_HEADER.size
        + model_count * model_bytes
        + row_count * 2
        + snapshot_count * EXTERNAL_BSP_REPLAY_SNAPSHOT.size
        + state_count * EXTERNAL_BSP_REPLAY_STATE.size
    )
    if len(data) != expected:
        raise ValueError(
            f"external BSP replay has {len(data)} bytes; expected {expected}"
        )
    cursor = EXTERNAL_BSP_REPLAY_HEADER.size
    model_names: list[str] = []
    model_indices: list[int] = []
    for _ in range(model_count):
        model_index, name_bytes, payload = EXTERNAL_BSP_REPLAY_MODEL.unpack_from(
            data, cursor
        )
        cursor += model_bytes
        if model_index == 0 or not 0 < name_bytes <= len(payload):
            raise ValueError("external BSP replay has an invalid model record")
        name = payload[:name_bytes].decode("ascii")
        if external_bsp_model_name(name, "") is None:
            raise ValueError("external BSP replay model is not an external BSP")
        model_indices.append(model_index)
        model_names.append(name)
    if model_indices != sorted(set(model_indices)):
        raise ValueError("external BSP model precache identities are not canonical")
    row_ids = struct.unpack_from(f"<{row_count}H", data, cursor)
    cursor += row_count * 2
    ranges: list[tuple[int, int]] = []
    for _ in range(snapshot_count):
        offset, count = EXTERNAL_BSP_REPLAY_SNAPSHOT.unpack_from(data, cursor)
        cursor += EXTERNAL_BSP_REPLAY_SNAPSHOT.size
        if offset > state_count or count > state_count - offset:
            raise ValueError("external BSP snapshot escapes the state array")
        ranges.append((offset, count))
    states: list[ExternalBspEntityState] = []
    for _ in range(state_count):
        values = EXTERNAL_BSP_REPLAY_STATE.unpack_from(data, cursor)
        cursor += EXTERNAL_BSP_REPLAY_STATE.size
        entity, model_slot, frame = values[:3]
        if entity == 0 or model_slot >= model_count:
            raise ValueError("external BSP replay has an invalid entity state")
        states.append(
            ExternalBspEntityState(
                entity,
                model_slot,
                frame,
                tuple(value / 8.0 for value in values[3:6]),
                tuple(value * 360.0 / 256.0 for value in values[6:9]),
            )
        )
    snapshots = tuple(
        tuple(states[offset : offset + count]) for offset, count in ranges
    )
    if any(row >= len(snapshots) for row in row_ids):
        raise ValueError("external BSP row references a missing snapshot")
    for snapshot in snapshots:
        if tuple(sorted(snapshot)) != snapshot or any(
            left.entity_number >= right.entity_number
            for left, right in zip(snapshot, snapshot[1:])
        ):
            raise ValueError("external BSP snapshot entity order is not canonical")
    return DecodedExternalBspReplay(
        sample_rate,
        first_server_time,
        camera_hash,
        tuple(model_names),
        tuple(model_indices),
        tuple(snapshots[row] for row in row_ids),
    )
