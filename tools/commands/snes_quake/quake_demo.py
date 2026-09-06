#!/usr/bin/env python3
"""Read camera samples from a classic NetQuake ``.dem`` stream."""

from __future__ import annotations

import bisect
import math
import struct
from collections.abc import Sequence
from dataclasses import dataclass


PROTOCOL_NETQUAKE = 15
DEFAULT_VIEWHEIGHT = 22

U_MOREBITS = 1 << 0
U_ORIGIN1 = 1 << 1
U_ORIGIN2 = 1 << 2
U_ORIGIN3 = 1 << 3
U_ANGLE2 = 1 << 4
U_FRAME = 1 << 6
U_ANGLE1 = 1 << 8
U_ANGLE3 = 1 << 9
U_MODEL = 1 << 10
U_COLORMAP = 1 << 11
U_SKIN = 1 << 12
U_EFFECTS = 1 << 13
U_LONGENTITY = 1 << 14

SU_VIEWHEIGHT = 1 << 0
SU_IDEALPITCH = 1 << 1
SU_PUNCH1 = 1 << 2
SU_VELOCITY1 = 1 << 5
SU_WEAPONFRAME = 1 << 12
SU_ARMOR = 1 << 13
SU_WEAPON = 1 << 14

SND_VOLUME = 1 << 0
SND_ATTENUATION = 1 << 1


@dataclass(frozen=True)
class DemoRecord:
    index: int
    view_angles: tuple[float, float, float]
    message: bytes


@dataclass(frozen=True)
class CameraSample:
    record: int
    server_time: float
    origin: tuple[float, float, float]
    view_height: int
    view_angles: tuple[float, float, float]
    map_entry: str


@dataclass(frozen=True)
class EntityBaseline:
    model_index: int
    frame: int
    origin: tuple[float, float, float]
    angles: tuple[float, float, float]


@dataclass(frozen=True)
class EntityState:
    entity_number: int
    model_index: int
    frame: int
    origin: tuple[float, float, float]
    angles: tuple[float, float, float]


@dataclass(frozen=True)
class SoundEvent:
    record: int
    server_time: float
    kind: str
    sound_index: int
    entity: int
    channel: int
    volume: int
    attenuation: int
    origin: tuple[float, float, float]


@dataclass(frozen=True)
class CameraEntitySample:
    camera: CameraSample
    entities: tuple[EntityState, ...]
    model_precache: tuple[str, ...]
    view_entity: int


@dataclass(frozen=True)
class DecodedDemoTrack:
    forced_track: int
    model_precache: tuple[str, ...]
    sound_precache: tuple[str, ...]
    sound_events: tuple[SoundEvent, ...]
    baselines: tuple[EntityState, ...]
    static_entities: tuple[EntityState, ...]
    samples: tuple[CameraEntitySample, ...]


class DemoFormatError(ValueError):
    """The demo does not conform to the classic protocol subset we consume."""


class MessageReader:
    def __init__(self, data: bytes, context: str) -> None:
        self.data = data
        self.offset = 0
        self.context = context

    @property
    def remaining(self) -> int:
        return len(self.data) - self.offset

    def read(self, size: int) -> bytes:
        end = self.offset + size
        if size < 0 or end > len(self.data):
            raise DemoFormatError(
                f"{self.context}: read of {size} bytes at {self.offset} exceeds "
                f"the {len(self.data)}-byte message"
            )
        result = self.data[self.offset : end]
        self.offset = end
        return result

    def u8(self) -> int:
        return self.read(1)[0]

    def i8(self) -> int:
        return struct.unpack("<b", self.read(1))[0]

    def u16(self) -> int:
        return struct.unpack("<H", self.read(2))[0]

    def i16(self) -> int:
        return struct.unpack("<h", self.read(2))[0]

    def i32(self) -> int:
        return struct.unpack("<i", self.read(4))[0]

    def f32(self) -> float:
        return struct.unpack("<f", self.read(4))[0]

    def string(self) -> str:
        end = self.data.find(b"\0", self.offset)
        if end < 0:
            raise DemoFormatError(f"{self.context}: unterminated protocol string")
        result = self.data[self.offset : end].decode("latin1")
        self.offset = end + 1
        return result

    def coord(self) -> float:
        return self.i16() / 8.0

    def angle(self) -> float:
        return self.i8() * (360.0 / 256.0)


def _is_plausible_record_header(data: bytes, offset: int) -> bool:
    """Return True when the bytes at *offset* look like a timed demo record."""
    if offset + 16 > len(data):
        return False
    size = struct.unpack_from("<i", data, offset)[0]
    if not (0 < size <= 32768):
        return False
    if offset + 16 + size > len(data):
        return False
    # Angles must be finite floats without ridiculously large magnitudes.
    try:
        angles = struct.unpack_from("<3f", data, offset + 4)
    except struct.error:
        return False
    return all(
        isinstance(a, float) and -1000.0 < a < 1000.0 for a in angles
    )


def parse_demo_records(data: bytes) -> tuple[int, list[DemoRecord]]:
    newline = data.find(b"\n")
    if newline < 0:
        raise DemoFormatError("demo is missing its CD-track header")
    try:
        forced_track = int(data[:newline].decode("ascii"))
    except ValueError as exc:
        raise DemoFormatError("demo CD-track header is not an integer") from exc

    records: list[DemoRecord] = []
    offset = newline + 1

    # Some demos embed the server-info message directly without a timed-record
    # wrapper.  Detect that case: if the first bytes do not look like a valid
    # 16-byte record header, scan forward to the first plausible record and
    # treat everything in between as a synthetic record with identity angles.
    if offset < len(data) and not _is_plausible_record_header(data, offset):
        scan = offset
        while scan < len(data) and not _is_plausible_record_header(data, scan):
            scan += 1
        if scan >= len(data):
            raise DemoFormatError(
                "demo contains no timed records after the server-info preamble"
            )
        # Absorb everything up to the first timed record as one synthetic
        # server-info record with zero view angles.
        records.append(
            DemoRecord(0, (0.0, 0.0, 0.0), data[offset:scan])
        )
        offset = scan

    # Some demos wrap Quake messages in an extra preamble (e.g. a
    # version-print header before svc_serverinfo).  When the first
    # message byte after the optional synthetic record is not a
    # recognised svc command, scan forward to the first \x0b
    # (svc_serverinfo) and absorb the preamble.
    if (
        records
        and records[0].message
        and records[0].message[0] not in (2, 7, 11, 12, 17, 19, 20, 22, 23, 29)
        and not (records[0].message[0] & 0x80)
    ):
        preamble = records[0].message
        # Find the first svc_serverinfo (0x0b) or svc_time (0x07) byte.
        for cut in range(1, len(preamble)):
            if preamble[cut] in (0x07, 0x0B):
                records[0] = DemoRecord(0, (0.0, 0.0, 0.0), preamble[cut:])
                break

    while offset < len(data):
        if offset + 16 > len(data):
            raise DemoFormatError(f"truncated demo record header at {offset}")
        size = struct.unpack_from("<i", data, offset)[0]
        if size < 0:
            raise DemoFormatError(f"negative demo message size {size} at {offset}")
        angles = struct.unpack_from("<3f", data, offset + 4)
        begin = offset + 16
        end = begin + size
        if end > len(data):
            raise DemoFormatError(
                f"demo record {len(records)} extends past the source stream"
            )
        records.append(DemoRecord(len(records), angles, data[begin:end]))
        offset = end
    return forced_track, records


class NetQuakeCameraParser:
    """Recover camera and packet-entity snapshots from protocol 15."""

    def __init__(self) -> None:
        self.protocol = PROTOCOL_NETQUAKE
        self.view_entity = 0
        self.view_height = DEFAULT_VIEWHEIGHT
        self.server_time = 0.0
        self.map_entry = ""
        self.model_precache: tuple[str, ...] = ("",)
        self.sound_precache: tuple[str, ...] = ("",)
        self.sound_events: list[SoundEvent] = []
        self.baselines: dict[int, EntityBaseline] = {}
        self.static_entities: list[EntityState] = []
        self.origins: dict[int, tuple[float, float, float]] = {}
        self.entity_states: dict[int, EntityState] = {}
        self.current_entities: set[int] = set()
        self.updated_entities: set[int] = set()

    @staticmethod
    def _baseline(reader: MessageReader) -> EntityBaseline:
        model_index = reader.u8()
        frame = reader.u8()
        reader.read(2)  # colormap, skin
        origin = []
        angles = []
        for _axis in range(3):
            origin.append(reader.coord())
            angles.append(reader.angle())
        return EntityBaseline(model_index, frame, tuple(origin), tuple(angles))

    def _server_info(self, reader: MessageReader) -> None:
        self.protocol = reader.i32()
        if self.protocol != PROTOCOL_NETQUAKE:
            raise DemoFormatError(
                f"{reader.context}: expected protocol 15, got {self.protocol}"
            )
        reader.u8()  # max clients
        reader.u8()  # game type
        reader.string()  # level title
        models: list[str] = []
        while True:
            value = reader.string()
            if not value:
                break
            models.append(value.lower())
        sounds: list[str] = []
        while True:
            value = reader.string()
            if not value:
                break
            sounds.append(value.replace("\\", "/").lower())
        self.model_precache = ("", *models)
        self.sound_precache = ("", *sounds)
        self.map_entry = next(
            (
                value
                for value in models
                if value.startswith("maps/") and value.endswith(".bsp")
            ),
            "",
        )
        self.baselines.clear()
        self.static_entities.clear()
        self.origins.clear()
        self.entity_states.clear()
        self.current_entities.clear()
        self.updated_entities.clear()
        self.sound_events.clear()
        self.view_entity = 0
        self.view_height = DEFAULT_VIEWHEIGHT
        self.server_time = 0.0

    def _fast_update(self, reader: MessageReader, command: int) -> None:
        bits = command & 0x7F
        if bits & U_MOREBITS:
            bits |= reader.u8() << 8
        entity = reader.u16() if bits & U_LONGENTITY else reader.u8()
        baseline = self.baselines.get(
            entity,
            EntityBaseline(0, 0, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
        )

        model_index = reader.u8() if bits & U_MODEL else baseline.model_index
        frame = reader.u8() if bits & U_FRAME else baseline.frame
        if bits & U_COLORMAP:
            reader.u8()
        if bits & U_SKIN:
            reader.u8()
        if bits & U_EFFECTS:
            reader.u8()

        origin = list(baseline.origin)
        angles = list(baseline.angles)
        if bits & U_ORIGIN1:
            origin[0] = reader.coord()
        if bits & U_ANGLE1:
            angles[0] = reader.angle()
        if bits & U_ORIGIN2:
            origin[1] = reader.coord()
        if bits & U_ANGLE2:
            angles[1] = reader.angle()
        if bits & U_ORIGIN3:
            origin[2] = reader.coord()
        if bits & U_ANGLE3:
            angles[2] = reader.angle()
        self.origins[entity] = tuple(origin)
        self.entity_states[entity] = EntityState(
            entity, model_index, frame, tuple(origin), tuple(angles)
        )
        self.current_entities.add(entity)
        self.updated_entities.add(entity)

    def _client_data(self, reader: MessageReader) -> None:
        bits = reader.u16()
        self.view_height = reader.i8() if bits & SU_VIEWHEIGHT else DEFAULT_VIEWHEIGHT
        if bits & SU_IDEALPITCH:
            reader.i8()
        for axis in range(3):
            if bits & (SU_PUNCH1 << axis):
                reader.i8()
            if bits & (SU_VELOCITY1 << axis):
                reader.i8()
        reader.i32()  # items is always sent by protocol 15
        if bits & SU_WEAPONFRAME:
            reader.u8()
        if bits & SU_ARMOR:
            reader.u8()
        if bits & SU_WEAPON:
            reader.u8()
        reader.i16()  # health
        reader.read(6)  # ammo, shells, nails, rockets, cells, active weapon

    def _sound(self, reader: MessageReader, record: int) -> None:
        fields = reader.u8()
        volume = reader.u8() if fields & SND_VOLUME else 255
        attenuation = reader.u8() if fields & SND_ATTENUATION else 64
        packed = reader.u16()
        sound_index = reader.u8()
        origin = tuple(reader.coord() for _axis in range(3))
        self.sound_events.append(
            SoundEvent(
                record,
                self.server_time,
                "start",
                sound_index,
                packed >> 3,
                packed & 7,
                volume,
                attenuation,
                origin,
            )
        )

    def _stop_sound(self, reader: MessageReader, record: int) -> None:
        packed = reader.u16()
        self.sound_events.append(
            SoundEvent(
                record,
                self.server_time,
                "stop",
                0,
                packed >> 3,
                packed & 7,
                0,
                0,
                (0.0, 0.0, 0.0),
            )
        )

    def _static_sound(self, reader: MessageReader, record: int) -> None:
        origin = tuple(reader.coord() for _axis in range(3))
        sound_index = reader.u8()
        volume = reader.u8()
        attenuation = reader.u8()
        self.sound_events.append(
            SoundEvent(
                record,
                self.server_time,
                "static",
                sound_index,
                0,
                0,
                volume,
                attenuation,
                origin,
            )
        )

    @staticmethod
    def _temporary_entity(reader: MessageReader) -> None:
        kind = reader.u8()
        if kind in (5, 6, 9, 13):
            reader.read(14)  # entity plus start/end coordinates
        elif kind in (0, 1, 2, 3, 4, 7, 8, 10, 11):
            reader.read(6)
        elif kind == 12:
            reader.read(8)
        else:
            raise DemoFormatError(f"{reader.context}: unknown temp entity {kind}")

    def parse_message(self, data: bytes, record: int) -> None:
        reader = MessageReader(data, f"demo record {record}")
        while reader.remaining:
            command = reader.u8()
            if command & 0x80:
                self._fast_update(reader, command)
            elif command == 1:  # svc_nop
                continue
            elif command == 2:  # svc_disconnect
                continue
            elif command == 3:  # svc_updatestat
                reader.read(5)
            elif command == 4:  # svc_version
                self.protocol = reader.i32()
            elif command == 5:  # svc_setview
                self.view_entity = reader.u16()
            elif command == 6:  # svc_sound
                self._sound(reader, record)
            elif command == 7:  # svc_time
                server_time = reader.f32()
                if server_time != self.server_time:
                    self.current_entities.clear()
                self.server_time = server_time
            elif command in (8, 9, 26):  # print/stufftext/centerprint
                reader.string()
            elif command == 10:  # svc_setangle
                reader.read(3)
            elif command == 11:  # svc_serverinfo
                self._server_info(reader)
            elif command == 12:  # svc_lightstyle
                reader.u8()
                reader.string()
            elif command == 13:  # svc_updatename
                reader.u8()
                reader.string()
            elif command == 14:  # svc_updatefrags
                reader.read(3)
            elif command == 15:  # svc_clientdata
                self._client_data(reader)
            elif command == 16:  # svc_stopsound
                self._stop_sound(reader, record)
            elif command == 17:  # svc_updatecolors
                reader.read(2)
            elif command == 18:  # svc_particle
                reader.read(11)
            elif command == 19:  # svc_damage
                reader.read(8)
            elif command == 20:  # svc_spawnstatic
                baseline = self._baseline(reader)
                self.static_entities.append(
                    EntityState(
                        0x8000 + len(self.static_entities),
                        baseline.model_index,
                        baseline.frame,
                        baseline.origin,
                        baseline.angles,
                    )
                )
            elif command == 22:  # svc_spawnbaseline
                entity = reader.u16()
                baseline = self._baseline(reader)
                self.baselines[entity] = baseline
                self.origins.setdefault(entity, baseline.origin)
            elif command == 23:  # svc_temp_entity
                self._temporary_entity(reader)
            elif command in (24, 25):  # pause/signon number
                reader.u8()
            elif command in (27, 28, 30, 33):
                continue
            elif command == 29:  # svc_spawnstaticsound
                self._static_sound(reader, record)
            elif command in (31, 34):  # finale/cutscene
                reader.string()
            elif command == 32:  # svc_cdtrack
                reader.read(2)
            else:
                # Unknown / client-specific svc — skip without payload so
                # the remainder of the block stays parseable.
                pass


def sample_newest_due_indices(
    source_times: Sequence[float], sample_rate_hz: int
) -> list[int]:
    """Map a fixed-rate clock to the newest point sample due at each step."""
    if (
        len(source_times) < 2
        or sample_rate_hz <= 0
        or any(right < left for left, right in zip(source_times, source_times[1:]))
    ):
        raise ValueError("fixed-step sampling requires monotonic source times")
    first_time = source_times[0]
    sample_count = math.ceil((source_times[-1] - first_time) * sample_rate_hz)
    return [
        bisect.bisect_right(source_times, first_time + step / sample_rate_hz) - 1
        for step in range(sample_count)
    ]


def discover_demo_maps(data: bytes) -> tuple[str, ...]:
    """Return distinct BSP entries announced by a demo, in stream order."""

    _forced_track, records = parse_demo_records(data)
    parser = NetQuakeCameraParser()
    maps: list[str] = []
    for record in records:
        previous = parser.map_entry
        parser.parse_message(record.message, record.index)
        if parser.map_entry and parser.map_entry != previous:
            if parser.map_entry not in maps:
                maps.append(parser.map_entry)
    if not maps:
        raise DemoFormatError("demo contains no BSP entry in svc_serverinfo")
    return tuple(maps)


def discover_demo_map(data: bytes) -> str:
    """Return the sole BSP selected by a single-map playback demo."""

    maps = discover_demo_maps(data)
    if len(maps) != 1:
        raise DemoFormatError(
            "ROM playback requires one BSP per demo; announced " + ", ".join(maps)
        )
    return maps[0]


def decode_camera_entity_track(data: bytes, map_entry: str) -> DecodedDemoTrack:
    forced_track, records = parse_demo_records(data)
    parser = NetQuakeCameraParser()
    samples: list[CameraEntitySample] = []
    expected_map = map_entry.lower()
    for record in records:
        parser.parse_message(record.message, record.index)
        entity_origin = parser.origins.get(parser.view_entity)
        if (
            entity_origin is None
            or parser.view_entity not in parser.updated_entities
            or parser.map_entry != expected_map
        ):
            continue
        origin = (
            entity_origin[0],
            entity_origin[1],
            entity_origin[2] + parser.view_height,
        )
        camera = CameraSample(
            record=record.index,
            server_time=parser.server_time,
            origin=origin,
            view_height=parser.view_height,
            view_angles=record.view_angles,
            map_entry=parser.map_entry,
        )
        samples.append(
            CameraEntitySample(
                camera,
                tuple(
                    parser.entity_states[entity]
                    for entity in sorted(parser.current_entities)
                    if entity in parser.entity_states
                ),
                parser.model_precache,
                parser.view_entity,
            )
        )
    if not samples:
        raise DemoFormatError(f"demo contains no camera samples for {map_entry}")
    baselines = tuple(
        EntityState(
            entity,
            baseline.model_index,
            baseline.frame,
            baseline.origin,
            baseline.angles,
        )
        for entity, baseline in sorted(parser.baselines.items())
    )
    return DecodedDemoTrack(
        forced_track,
        parser.model_precache,
        parser.sound_precache,
        tuple(parser.sound_events),
        baselines,
        tuple(parser.static_entities),
        tuple(samples),
    )


def extract_camera_entity_samples(
    data: bytes, map_entry: str
) -> tuple[int, list[CameraEntitySample]]:
    track = decode_camera_entity_track(data, map_entry)
    return track.forced_track, list(track.samples)


def extract_camera_samples(
    data: bytes, map_entry: str
) -> tuple[int, list[CameraSample]]:
    """Retain the original camera-only API and byte-for-byte source values."""
    track = decode_camera_entity_track(data, map_entry)
    return track.forced_track, [sample.camera for sample in track.samples]
