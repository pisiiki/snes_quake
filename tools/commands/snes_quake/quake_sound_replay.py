"""Canonical camera-bound replay and binary codec for Quake sound events."""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass

from quake_brush_replay import extract_canonical_brush_replay
from quake_demo import SoundEvent, decode_camera_entity_track


SOUND_REPLAY_MAGIC = b"QSR1"
SOUND_REPLAY_VERSION = 1
SOUND_REPLAY_HEADER = struct.Struct("<4sHHfQIIHHHH")
SOUND_REPLAY_SOUND = struct.Struct("<HB61s")
SOUND_REPLAY_EVENT = struct.Struct("<iBHHBBBhhhI")
SOUND_EVENT_START = 1
SOUND_EVENT_STOP = 2
SOUND_EVENT_STATIC = 3
SOUND_SLOT_NONE = 0xFFFF
TIME_Q16_SCALE = 1 << 16


@dataclass(frozen=True)
class ReplaySoundEvent:
    due_q16: int
    kind: int
    sound_slot: int
    entity: int
    channel: int
    volume: int
    attenuation: int
    origin: tuple[float, float, float]
    source_record: int


@dataclass(frozen=True)
class CanonicalSoundReplay:
    sample_rate_hz: int
    first_server_time: float
    camera_track_fnv1a64: int
    camera_row_count: int
    view_entity: int
    sound_names: tuple[str, ...]
    sound_precache_indices: tuple[int, ...]
    source_event_count: int
    events: tuple[ReplaySoundEvent, ...]


@dataclass(frozen=True)
class DecodedSoundReplay:
    sample_rate_hz: int
    first_server_time: float
    camera_track_fnv1a64: int
    camera_row_count: int
    view_entity: int
    sound_names: tuple[str, ...]
    sound_precache_indices: tuple[int, ...]
    events: tuple[ReplaySoundEvent, ...]


def normalize_sound_name(name: str) -> str:
    normalized = name.replace("\\", "/").lower()
    if (
        not normalized
        or normalized.startswith("/")
        or ":" in normalized
        or any(part in ("", ".", "..") for part in normalized.split("/"))
        or not normalized.endswith(".wav")
    ):
        raise ValueError(f"invalid Quake sound precache name: {name!r}")
    try:
        encoded = normalized.encode("ascii")
    except UnicodeEncodeError as error:
        raise ValueError("Quake sound names must be ASCII") from error
    if len(encoded) > 61:
        raise ValueError("Quake sound name exceeds its replay record")
    return normalized


def pak_sound_entry(name: str) -> str:
    return "sound/" + normalize_sound_name(name)


def _event_kind(event: SoundEvent) -> int:
    try:
        return {
            "start": SOUND_EVENT_START,
            "stop": SOUND_EVENT_STOP,
            "static": SOUND_EVENT_STATIC,
        }[event.kind]
    except KeyError as error:
        raise ValueError(f"unknown Quake sound event kind: {event.kind}") from error


def _coord_q3(value: float) -> int:
    quantized = round(value * 8.0)
    if not -0x8000 <= quantized <= 0x7FFF or quantized / 8.0 != value:
        raise ValueError(f"sound coordinate {value} is not signed-Q3 exact")
    return quantized


def extract_canonical_sound_replay(
    data: bytes, map_entry: str, sample_rate_hz: int
) -> CanonicalSoundReplay:
    camera = extract_canonical_brush_replay(data, map_entry, sample_rate_hz)
    track = decode_camera_entity_track(data, map_entry)
    if not track.samples:
        raise ValueError("sound replay requires camera samples")
    first_time = camera.first_server_time
    end_time = first_time + len(camera.rows) / sample_rate_hz
    selected = tuple(
        event for event in track.sound_events if event.server_time < end_time
    )
    referenced_indices = tuple(
        sorted(
            {
                event.sound_index
                for event in selected
                if event.kind != "stop"
                and 0 < event.sound_index < len(track.sound_precache)
            }
        )
    )
    sound_names = tuple(
        normalize_sound_name(track.sound_precache[index])
        for index in referenced_indices
    )
    slots = {index: slot for slot, index in enumerate(referenced_indices)}
    events: list[ReplaySoundEvent] = []
    for event in selected:
        kind = _event_kind(event)
        if kind == SOUND_EVENT_STOP:
            sound_slot = SOUND_SLOT_NONE
        else:
            if event.sound_index not in slots:
                raise ValueError(
                    f"sound event references missing precache index {event.sound_index}"
                )
            sound_slot = slots[event.sound_index]
        events.append(
            ReplaySoundEvent(
                round((event.server_time - first_time) * TIME_Q16_SCALE),
                kind,
                sound_slot,
                event.entity,
                event.channel,
                event.volume,
                event.attenuation,
                event.origin,
                event.record,
            )
        )
    if any(
        right.due_q16 < left.due_q16
        for left, right in zip(events, events[1:])
    ):
        raise ValueError("sound events are not in monotonic server-time order")
    return CanonicalSoundReplay(
        sample_rate_hz,
        first_time,
        camera.camera_track_fnv1a64,
        len(camera.rows),
        track.samples[0].view_entity,
        sound_names,
        referenced_indices,
        len(track.sound_events),
        tuple(events),
    )


def encode_sound_replay(replay: CanonicalSoundReplay) -> bytes:
    if (
        replay.sample_rate_hz <= 0
        or not math.isfinite(replay.first_server_time)
        or replay.first_server_time < 0.0
        or replay.camera_row_count <= 0
        or not 0 < replay.view_entity <= 0xFFFF
        or len(replay.sound_names) != len(replay.sound_precache_indices)
        or len(replay.sound_names) >= SOUND_SLOT_NONE
    ):
        raise ValueError("sound replay has an invalid canonical contract")
    output = bytearray(
        SOUND_REPLAY_HEADER.pack(
            SOUND_REPLAY_MAGIC,
            SOUND_REPLAY_VERSION,
            replay.sample_rate_hz,
            replay.first_server_time,
            replay.camera_track_fnv1a64,
            replay.camera_row_count,
            len(replay.events),
            len(replay.sound_names),
            SOUND_REPLAY_SOUND.size,
            SOUND_REPLAY_EVENT.size,
            replay.view_entity,
        )
    )
    if tuple(sorted(set(replay.sound_precache_indices))) != (
        replay.sound_precache_indices
    ):
        raise ValueError("sound precache identities are not canonical")
    for index, name in zip(
        replay.sound_precache_indices, replay.sound_names, strict=True
    ):
        encoded = normalize_sound_name(name).encode("ascii")
        if not 0 < index <= 0xFFFF:
            raise ValueError("sound precache index exceeds its record")
        output.extend(
            SOUND_REPLAY_SOUND.pack(index, len(encoded), encoded.ljust(61, b"\0"))
        )
    previous_due = -(1 << 31)
    for event in replay.events:
        if (
            event.kind not in (SOUND_EVENT_START, SOUND_EVENT_STOP, SOUND_EVENT_STATIC)
            or not -(1 << 31) <= event.due_q16 < (1 << 31)
            or event.due_q16 < previous_due
            or not 0 <= event.entity <= 0xFFFF
            or not 0 <= event.channel <= 7
            or not 0 <= event.volume <= 255
            or not 0 <= event.attenuation <= 255
            or not 0 <= event.source_record <= 0xFFFFFFFF
        ):
            raise ValueError("sound replay contains an invalid event")
        if event.kind == SOUND_EVENT_STOP:
            if event.sound_slot != SOUND_SLOT_NONE:
                raise ValueError("stop event unexpectedly references a sound")
        elif not 0 <= event.sound_slot < len(replay.sound_names):
            raise ValueError("sound event references a missing sound slot")
        output.extend(
            SOUND_REPLAY_EVENT.pack(
                event.due_q16,
                event.kind,
                event.sound_slot,
                event.entity,
                event.channel,
                event.volume,
                event.attenuation,
                *(_coord_q3(value) for value in event.origin),
                event.source_record,
            )
        )
        previous_due = event.due_q16
    return bytes(output)


def decode_sound_replay(data: bytes) -> DecodedSoundReplay:
    if len(data) < SOUND_REPLAY_HEADER.size:
        raise ValueError("truncated sound replay header")
    (
        magic,
        version,
        sample_rate,
        first_time,
        camera_hash,
        row_count,
        event_count,
        sound_count,
        sound_bytes,
        event_bytes,
        view_entity,
    ) = SOUND_REPLAY_HEADER.unpack_from(data)
    if (
        magic != SOUND_REPLAY_MAGIC
        or version != SOUND_REPLAY_VERSION
        or sample_rate <= 0
        or not math.isfinite(first_time)
        or first_time < 0.0
        or row_count <= 0
        or view_entity == 0
        or sound_bytes != SOUND_REPLAY_SOUND.size
        or event_bytes != SOUND_REPLAY_EVENT.size
    ):
        raise ValueError("sound replay has an invalid header")
    expected = (
        SOUND_REPLAY_HEADER.size
        + sound_count * sound_bytes
        + event_count * event_bytes
    )
    if len(data) != expected:
        raise ValueError(f"sound replay has {len(data)} bytes; expected {expected}")
    cursor = SOUND_REPLAY_HEADER.size
    names: list[str] = []
    indices: list[int] = []
    for _ in range(sound_count):
        index, name_bytes, payload = SOUND_REPLAY_SOUND.unpack_from(data, cursor)
        cursor += sound_bytes
        if index == 0 or not 0 < name_bytes <= len(payload):
            raise ValueError("sound replay has an invalid sound record")
        name = normalize_sound_name(payload[:name_bytes].decode("ascii"))
        indices.append(index)
        names.append(name)
    if indices != sorted(set(indices)):
        raise ValueError("sound precache identities are not canonical")
    events: list[ReplaySoundEvent] = []
    previous_due = -(1 << 31)
    for _ in range(event_count):
        values = SOUND_REPLAY_EVENT.unpack_from(data, cursor)
        cursor += event_bytes
        due, kind, slot, entity, channel, volume, attenuation = values[:7]
        if (
            kind not in (SOUND_EVENT_START, SOUND_EVENT_STOP, SOUND_EVENT_STATIC)
            or due < previous_due
            or channel > 7
            or (kind == SOUND_EVENT_STOP and slot != SOUND_SLOT_NONE)
            or (kind != SOUND_EVENT_STOP and slot >= sound_count)
        ):
            raise ValueError("sound replay has an invalid event record")
        events.append(
            ReplaySoundEvent(
                due,
                kind,
                slot,
                entity,
                channel,
                volume,
                attenuation,
                tuple(value / 8.0 for value in values[7:10]),
                values[10],
            )
        )
        previous_due = due
    return DecodedSoundReplay(
        sample_rate,
        first_time,
        camera_hash,
        row_count,
        view_entity,
        tuple(names),
        tuple(indices),
        tuple(events),
    )
