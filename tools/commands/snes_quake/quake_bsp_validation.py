"""Transport-neutral SNES Quake renderer validation contracts.

This module contains only data decoding and pure validation logic. Live
emulator transports belong in backend-specific probe modules.
"""

from __future__ import annotations

import hashlib
import json
import re
import struct
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence
from workspace_paths import workspace_root

NATIVE_WIDTH = 256

NATIVE_HEIGHT = 224

LOGICAL_WIDTH = 128

LOGICAL_HEIGHT = 112

SELECTOR_OBSERVATION_UNAVAILABLE = 0xFFFF

SELECTOR_OBSERVATION_SYMBOLS = (
    "active_bsp_node_count",
    "active_packet_drawable_count",
    "active_packet_front_count",
    "active_packet_near_count",
    "active_packet_screen_count",
    "active_packet_painter_node_count",
)

CAMERA_WORDS = 8

CONTROL_BUTTONS = ("left", "right", "up", "down", "a", "b", "x", "y", "l", "r")

CONTROL_REVISION_ADVANCES = {
    button: 1 if button in ("left", "right", "up", "down", "l", "r") else 2
    for button in CONTROL_BUTTONS
}

BG_PAGE_BY_TILE_ADDRESS = {0x0000: 0, 0x4000: 1}

TEXTURE_PAGE_BY_TILE_ADDRESS = {0x0000: 0, 0x2000: 1}

TEXTURE_VISIBLE_PAGE_BYTES = 0x3800

TEXTURE_TILEMAP_BYTES = 0x0800

# Expand a planar row byte into eight independent byte lanes, ordered from
# source bit 7 through bit 0. Shifting one expanded value by its plane number
# and ORing all eight planes decodes a complete tile row with integer ops.
_PLANAR_BYTE_LUT = tuple(
    sum(((value >> (7 - x)) & 1) << (x * 8) for x in range(8)) for value in range(256)
)

PACKET_FIXTURE_NAME = "QuakeBSPPacketOracle.json"

PACKET_FIXTURE_SCHEMA = 3

PACKET_VERTEX_BYTES = 4

PACKET_INDEX_BYTES = 2

# Canonical compact packet faces are contiguous first-index/count/flat/dither
# records. Super FX code must access the unaligned first-index field bytewise.
PACKET_FACE_BYTES = 5

PACKET_FACE_PLANE_BYTES = 5

PACKET_VERTEX_CAPACITY = 768

PACKET_INDEX_CAPACITY = 2_048

PACKET_FACE_CAPACITY = 405

PACKET_SIDECARS_ADDRESS = 0x141B0

PACKET_SIDECAR_BYTES = 4

PACKET_SOURCE_FACES_ADDRESS = 0x18860

PACKET_INDICES_ADDRESS = 0x15200

PACKET_FACES_ADDRESS = 0x16202

PACKET_VERTICES_ADDRESS = 0x1B100

PACKET_STREAM_CONTRACT = {
    "vertices": {
        "format": "<bbbB",
        "recordBytes": PACKET_VERTEX_BYTES,
        "semantics": "Q2 xyz = signed base*4 + packed 2-bit residual",
    },
    "indices": {"format": "<H", "recordBytes": PACKET_INDEX_BYTES},
    "faces": {
        "format": "<HBBB",
        "recordBytes": PACKET_FACE_BYTES,
        "storage": "canonical contiguous bytes",
    },
    "facePlanes": {
        "format": "<bbbh",
        "recordBytes": PACKET_FACE_PLANE_BYTES,
    },
    "sourceFaceIds": {"format": "<H", "recordBytes": 2, "hostOnly": True},
}

PACKET_COUNTS_RECORD = struct.Struct("<HHH")

PACKET_GUARD_OK = 0xA55A

PACKET_GUARD_LAYOUT_CONSTANTS = {
    "facePlanes": "GSU_FACE_PLANES_GUARD_OFFSET",
    "projectionCache": "GSU_PROJECTION_CACHE_GUARD_OFFSET",
}

_LAYOUT_CONSTANT_PATTERN = re.compile(
    r"^\s*([A-Z][A-Z0-9_]*)\s*=\s*\$([0-9A-Fa-f]+)\s*(?:;.*)?$"
)


def memory_map_offsets(path: Path, names: Sequence[str]) -> dict[str, int]:
    """Resolve literal offsets from the same memory map used by the ROM."""
    required = set(names)
    values: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _LAYOUT_CONSTANT_PATTERN.match(line)
        if match is not None and match.group(1) in required:
            values[match.group(1)] = int(match.group(2), 16)
    missing = sorted(required - values.keys())
    if missing:
        raise ValueError(
            "memory map lacks literal offsets: " + ", ".join(missing)
        )
    if any(not 0 <= value < 0x10000 for value in values.values()):
        raise ValueError("memory map offset escapes one GSU RAM bank")
    return values


def packet_guard_layout(path: Path) -> dict[str, int]:
    """Read the literal GSU guard offsets owned by one assembled memory map."""
    return memory_map_offsets(path, tuple(PACKET_GUARD_LAYOUT_CONSTANTS.values()))


def brush_runtime_layout(path: Path) -> dict[str, int]:
    offsets = memory_map_offsets(path, ("GSU_FACE_PLANES_OFFSET", "GSU_SOURCE_FACE_IDS_OFFSET"))
    state, tokens = offsets["GSU_FACE_PLANES_OFFSET"], offsets["GSU_SOURCE_FACE_IDS_OFFSET"]
    if state <= tokens or (state - tokens) % 2:
        raise ValueError("brush state does not follow whole mixed tokens")
    return {"state": 0x10000 + state, "staticCursor": 0x10000 + state + 0x12,
            "mixedTokenCapacity": (state - tokens) // 2}


BRUSH_RUNTIME_LAYOUT = brush_runtime_layout(workspace_root(__file__) / "src/snes_quake/MemoryMap.i")
PACKET_FACE_PLANES_ADDRESS = BRUSH_RUNTIME_LAYOUT["state"]


def packet_guard_addresses(
    face_capacity: int = PACKET_FACE_CAPACITY,
    *,
    layout: Mapping[str, int] | None = None,
) -> tuple[tuple[str, int], ...]:
    """Return current guard addresses, including the capacity-sized sidecars."""

    if face_capacity < 1:
        raise ValueError("packet face capacity must be positive")
    moving = {
        "facePlanes": 0x1985E,
        "projectionCache": 0x1B060,
    }
    if layout is not None:
        for name, constant in PACKET_GUARD_LAYOUT_CONSTANTS.items():
            if constant not in layout:
                raise ValueError(f"packet guard layout lacks {constant}")
            moving[name] = 0x10000 + int(layout[constant])
    return (
        ("vertexRemap", 0x13BFC),
        ("selectedFaces", 0x141AE),
        (
            "admissionSidecars",
            PACKET_SIDECARS_ADDRESS + face_capacity * PACKET_SIDECAR_BYTES,
        ),
        ("vertices", 0x1BD00),
        ("indices", 0x16200),
        ("painterNodes", 0x187FE),
        ("facePlanes", moving["facePlanes"]),
        ("projectionCache", moving["projectionCache"]),
    )


PACKET_GUARD_ADDRESSES = packet_guard_addresses()

WAYPOINT_ORDER = ("spawn", "near", "far", "return-spawn")

PACKET_FIXTURE_ORDER = ("spawn", "near", "far", "yaw", "pitch", "return-spawn")


def decode_8bpp_tile(data: bytes, tile: int, x: int, y: int) -> int:
    """Decode one standard SNES planar 8bpp tile pixel."""

    base = tile * 64
    bit = 7 - x
    value = 0
    for plane in range(8):
        pair = plane // 2
        offset = base + pair * 16 + y * 2 + (plane & 1)
        value |= ((data[offset] >> bit) & 1) << plane
    return value


@lru_cache(maxsize=8)
def _texture_tilemap_plan(
    tilemap: bytes,
) -> tuple[tuple[int, tuple[tuple[int, bool], ...]], ...]:
    """Group logical mosaic destinations by their source planar tile row."""

    destinations_by_source: dict[int, list[tuple[int, bool]]] = {}
    for y in range(LOGICAL_HEIGHT):
        # BG1VOFS=-1 compensates for the SNES one-row BG origin, so each
        # vertical mosaic pair is anchored at physical source row 2y.
        physical_y = y * 2
        map_y, pixel_y = divmod(physical_y, 8)
        for map_x in range(LOGICAL_WIDTH // 4):
            entry = struct.unpack_from("<H", tilemap, (map_y * 32 + map_x) * 2)[0]
            source_y = 7 - pixel_y if entry & 0x8000 else pixel_y
            source = (entry & 0x03FF) * 64 + source_y * 2
            destination = y * LOGICAL_WIDTH + map_x * 4
            destinations_by_source.setdefault(source, []).append(
                (destination, bool(entry & 0x4000))
            )
    return tuple(
        (source, tuple(destinations))
        for source, destinations in destinations_by_source.items()
    )


def decode_texture_logical_screen(data: bytes, tilemap: bytes) -> bytes:
    """Decode the logical 128x112 plane selected by the 2x mosaic viewport."""

    if len(data) != TEXTURE_VISIBLE_PAGE_BYTES:
        raise ValueError(
            "8bpp visible page must be "
            f"{TEXTURE_VISIBLE_PAGE_BYTES} bytes, got {len(data)}"
        )
    if len(tilemap) != TEXTURE_TILEMAP_BYTES:
        raise ValueError(
            f"8bpp tilemap must be {TEXTURE_TILEMAP_BYTES} bytes, got {len(tilemap)}"
        )
    logical = bytearray(LOGICAL_WIDTH * LOGICAL_HEIGHT)
    lut = _PLANAR_BYTE_LUT
    for source, destinations in _texture_tilemap_plan(bytes(tilemap)):
        pixels = (
            lut[data[source]]
            | lut[data[source + 1]] << 1
            | lut[data[source + 16]] << 2
            | lut[data[source + 17]] << 3
            | lut[data[source + 32]] << 4
            | lut[data[source + 33]] << 5
            | lut[data[source + 48]] << 6
            | lut[data[source + 49]] << 7
        ).to_bytes(8, "little")
        # The logical viewport samples physical x coordinates 0, 2, 4, 6.
        # H-flipped tilemap cells therefore select source pixels 7, 5, 3, 1.
        forward = pixels[::2]
        reverse = pixels[7::-2]
        for destination, horizontal_flip in destinations:
            logical[destination : destination + 4] = (
                reverse if horizontal_flip else forward
            )
    return bytes(logical)


SCALAR_SYMBOLS = (
    "yaw_index",
    "pitch_level",
    "camera_x",
    "camera_y",
    "camera_z",
    "technique",
    "control_revision",
    "scheduled_frame_valid",
    "demo_mode",
    "demo_schedule",
    "demo_playback_rate_shift",
    "demo_ordered_pose_stride",
    "demo_offset",
    "demo_timing_offset",
    "demo_next_pose",
    "demo_track_pose",
    "demo_pose_due_tick",
    "demo_pose_counter",
    "demo_source_due_counter",
    "demo_coalesced_counter",
    "demo_playhead_tick",
    "demo_schedule_revision",
    "demo_loop_counter",
    "video_tick",
    "coverage_debug",
    "runtime_menu_open",
    "runtime_menu_selection",
    "runtime_menu_draft_playback",
    "render_coverage_mode",
    "producer_slot",
    "ready_slot",
    "upload_slot",
    "frame_ready",
    "upload_active",
    "upload_target",
    "upload_chunk",
    "stage_frame_required",
    "render_counter",
    "present_counter",
    "gsu_job_counter",
    "staging_dma_counter",
    "vram_chunk_counter",
    "page_flip_counter",
    "presented_coverage_mode",
    "active_leaf",
    "active_pvs_face_count",
    "active_pvs_revision",
    "active_selection_revision",
    "active_pvs_encoded_bytes",
    "active_bsp_node_count",
    "active_packet_vertex_count",
    "active_packet_index_count",
    "active_packet_face_count",
    "active_packet_plane_count",
    "active_packet_overflow_face",
    "active_packet_overflow_vertex",
    "active_packet_overflow_index",
    "active_packet_revision",
    "active_packet_camera_revision",
    "active_packet_guard_status",
    "active_packet_drawable_count",
    "active_packet_front_count",
    "active_packet_near_count",
    "active_packet_screen_count",
    "active_packet_painter_node_count",
    "active_packet_error",
    "render_demo_pose",
    "render_demo_due_tick",
    "render_demo_epoch",
    "presented_demo_pose",
    "presented_demo_due_tick",
    "presented_demo_epoch",
)

ARRAY_SYMBOLS = {
    "render_camera": CAMERA_WORDS * 2,
    "render_brush_visual_state": 2,
    "slot_camera": CAMERA_WORDS * 2 * 2,
    "slot_brush_visual_state": 2 * 2,
    "slot_coverage_mode": 2 * 2,
    "slot_demo_pose": 2 * 2,
    "slot_demo_due_tick": 2 * 2,
    "slot_demo_epoch": 2 * 2,
    "presented_camera": CAMERA_WORDS * 2,
    "presented_brush_visual_state": 2,
}

REQUIRED_SYMBOLS = (*SCALAR_SYMBOLS, *ARRAY_SYMBOLS)

SYMBOL_SIZES = {**{name: 2 for name in SCALAR_SYMBOLS}, **ARRAY_SYMBOLS}

SKY_PHASE_LOW23_MASK = (1 << 23) - 1

SKY_PIPELINE_PHASE_SYMBOLS = (
    "render_sky_phase_q16",
    "staging_sky_phase_q16",
    "slot_sky_phase_q16",
    "presented_sky_phase_q16",
)

SKY_PIPELINE_PRESENCE_SYMBOLS = (
    "render_sky_present",
    "staging_sky_present",
    "slot_sky_present",
    "presented_sky_present",
)

SKY_PIPELINE_SYMBOL_SIZES = {
    "render_sky_phase_q16": 4,
    "staging_sky_phase_q16": 4,
    "slot_sky_phase_q16": 8,
    "presented_sky_phase_q16": 4,
    "render_sky_present": 2,
    "staging_sky_present": 2,
    "slot_sky_present": 4,
    "presented_sky_present": 2,
}

SKY_PIPELINE_SYMBOLS = tuple(SKY_PIPELINE_SYMBOL_SIZES)

SYMBOL_PATTERN = re.compile(
    r"^\s*[A-Za-z]+\s+([0-9A-Fa-f]{6,8})\s+\.([A-Za-z_][A-Za-z0-9_]*)\s*$"
)


class VerificationError(RuntimeError):
    """Raised when live renderer state violates the acceptance contract."""


@dataclass(frozen=True)
class CameraCommand:
    yaw: int
    pitch: int
    x: int
    y: int
    z: int
    technique: int
    revision: int
    visual_state: int = 0
    overlay_flags: int = 0
    alias_row: int = 0


@dataclass(frozen=True)
class Controls:
    yaw: int
    pitch: int
    x: int
    y: int
    z: int
    technique: int
    revision: int


@dataclass(frozen=True)
class Telemetry:
    controls: Controls
    producer_slot: int
    ready_slot: int
    upload_slot: int
    frame_ready: int
    upload_active: int
    upload_target: int
    upload_chunk: int
    render_counter: int
    present_counter: int
    active_leaf: int
    active_pvs_face_count: int
    active_pvs_revision: int
    active_selection_revision: int
    active_pvs_encoded_bytes: int
    active_bsp_node_count: int | None
    packet: "PacketTelemetry"
    render_camera: CameraCommand
    slot_cameras: tuple[CameraCommand, CameraCommand]
    presented_camera: CameraCommand
    demo_mode: int = 0
    demo_schedule: int = 0
    demo_playback_rate_shift: int = 0
    demo_offset: int = 0
    demo_timing_offset: int = 0
    demo_next_pose: int = 0
    demo_track_pose: int = 0
    demo_pose_due_tick: int = 0
    demo_pose_counter: int = 0
    demo_source_due_counter: int = 0
    demo_coalesced_counter: int = 0
    demo_playhead_tick: int = 0
    demo_schedule_revision: int = 0
    demo_loop_counter: int = 0
    video_tick: int = 0
    stage_frame_required: int = 0
    gsu_job_counter: int = 0
    staging_dma_counter: int = 0
    vram_chunk_counter: int = 0
    page_flip_counter: int = 0
    coverage_debug: int = 0
    render_coverage_mode: int = 0
    slot_coverage_modes: tuple[int, int] = (0, 0)
    presented_coverage_mode: int = 0
    runtime_menu_open: int = 0
    runtime_menu_selection: int = 0
    runtime_menu_draft_playback: int = 0
    render_demo_pose: int = 0xFFFF
    render_demo_due_tick: int = 0
    render_demo_epoch: int = 0
    slot_demo_poses: tuple[int, int] = (0xFFFF, 0xFFFF)
    slot_demo_due_ticks: tuple[int, int] = (0, 0)
    slot_demo_epochs: tuple[int, int] = (0, 0)
    presented_demo_pose: int = 0xFFFF
    presented_demo_due_tick: int = 0
    presented_demo_epoch: int = 0


@dataclass(frozen=True)
class SkyPhasePresence:
    """One immutable sky result carried beside a renderer frame identity."""

    phase_low23: int
    sky_present: int

    def record(self) -> dict[str, int]:
        return {"phaseLow23": self.phase_low23, "skyPresent": self.sky_present}


@dataclass(frozen=True)
class SkyPipelineState:
    """Render, staging, immutable slots, and presented sky sidecars."""

    rendered: SkyPhasePresence
    staged: SkyPhasePresence
    slots: tuple[SkyPhasePresence, SkyPhasePresence]
    presented: SkyPhasePresence

    def identities(self) -> tuple[tuple[str, SkyPhasePresence], ...]:
        return (
            ("rendered", self.rendered),
            ("staged", self.staged),
            ("slot0", self.slots[0]),
            ("slot1", self.slots[1]),
            ("presented", self.presented),
        )


@dataclass(frozen=True)
class ControlResult:
    button: str
    before: Controls
    after: Controls


@dataclass(frozen=True)
class PacketTelemetry:
    vertex_count: int
    index_count: int
    face_count: int
    plane_count: int
    overflow_face: int
    overflow_vertex: int
    overflow_index: int
    revision: int
    camera_revision: int
    guard_status: int
    drawable_face_count: int | None
    front_face_count: int | None
    near_face_count: int | None
    screen_face_count: int | None
    painter_node_count: int | None
    error_flags: int


@dataclass(frozen=True)
class PacketFixture:
    name: str
    camera: tuple[int, int, int]
    yaw: int
    pitch: int
    leaf: int
    leaf_node_visits: int
    painter_induced_nodes: int
    stage_counts: dict[str, int]
    overflow_counts: dict[str, int]
    counts: dict[str, int]
    byte_counts: dict[str, int]
    source_face_ids: tuple[int, ...]
    source_faces_absent_from_spawn: tuple[int, ...]
    hashes: dict[str, str]


def parse_cpu_symbols(text: str) -> dict[str, int]:
    symbols: dict[str, int] = {}
    for line in text.splitlines():
        match = SYMBOL_PATTERN.match(line)
        if match:
            symbols[match.group(2)] = int(match.group(1), 16)
    return symbols


def require_symbols(symbols: dict[str, int]) -> dict[str, int]:
    missing = [name for name in REQUIRED_SYMBOLS if name not in symbols]
    if missing:
        raise ValueError("symbol file lacks required labels: " + ", ".join(missing))
    return {name: symbols[name] for name in REQUIRED_SYMBOLS}


def require_sky_pipeline_symbols(symbols: Mapping[str, int]) -> dict[str, int]:
    """Select the complete sky sidecar symbol set, rejecting partial probes."""

    missing = [name for name in SKY_PIPELINE_SYMBOLS if name not in symbols]
    if missing:
        raise ValueError(
            "symbol file lacks atomic sky pipeline labels: " + ", ".join(missing)
        )
    selected: dict[str, int] = {}
    for name in SKY_PIPELINE_SYMBOLS:
        value = symbols[name]
        if type(value) is not int or not 0 <= value <= 0xFFFFFF:
            raise ValueError(f"sky pipeline symbol {name!r} is not a 24-bit address")
        selected[name] = value
    return selected


def sky_pipeline_memory_window(symbols: Mapping[str, int]) -> tuple[int, int]:
    selected = require_sky_pipeline_symbols(symbols)
    start = min(selected.values())
    end = max(
        selected[name] + SKY_PIPELINE_SYMBOL_SIZES[name]
        for name in SKY_PIPELINE_SYMBOLS
    )
    return start, end - start


def decode_sky_pipeline_state(
    memory: bytes, *, memory_base: int, symbols: Mapping[str, int]
) -> SkyPipelineState:
    """Decode the atomic sky sidecars from one coherent memory snapshot."""

    selected = require_sky_pipeline_symbols(symbols)

    def word(name: str, byte_offset: int = 0) -> int:
        offset = selected[name] - memory_base + byte_offset
        if offset < 0 or offset + 2 > len(memory):
            raise ValueError(f"symbol {name!r} escapes the sky memory window")
        return int.from_bytes(memory[offset : offset + 2], "little")

    def state(phase_name: str, presence_name: str, index: int = 0) -> SkyPhasePresence:
        phase_offset = index * 4
        low = word(phase_name, phase_offset)
        high = word(phase_name, phase_offset + 2)
        if high & ~0x007F:
            raise ValueError(f"{phase_name}[{index}] sets reserved phase bits")
        present = word(presence_name, index * 2)
        if present not in (0, 1):
            raise ValueError(f"{presence_name}[{index}] is not a Boolean sky result")
        return SkyPhasePresence(low | (high << 16), present)

    return SkyPipelineState(
        rendered=state("render_sky_phase_q16", "render_sky_present"),
        staged=state("staging_sky_phase_q16", "staging_sky_present"),
        slots=(
            state("slot_sky_phase_q16", "slot_sky_present", 0),
            state("slot_sky_phase_q16", "slot_sky_present", 1),
        ),
        presented=state("presented_sky_phase_q16", "presented_sky_present"),
    )


def symbol_memory_window(symbols: dict[str, int]) -> tuple[int, int]:
    start = min(symbols.values())
    end = max(symbols[name] + SYMBOL_SIZES[name] for name in REQUIRED_SYMBOLS)
    return start, end - start


def decode_telemetry(
    memory: bytes, *, memory_base: int, symbols: dict[str, int]
) -> Telemetry:
    def word(name: str, index: int = 0) -> int:
        offset = symbols[name] - memory_base + index * 2
        if offset < 0 or offset + 2 > len(memory):
            raise ValueError(f"symbol {name!r} escapes the telemetry memory window")
        return int.from_bytes(memory[offset : offset + 2], "little")

    def camera(name: str, index: int = 0) -> CameraCommand:
        values = [
            word(name, index * CAMERA_WORDS + field) for field in range(CAMERA_WORDS)
        ]
        packed_mode = values[5]
        visual_name = {
            "render_camera": "render_brush_visual_state",
            "slot_camera": "slot_brush_visual_state",
            "presented_camera": "presented_brush_visual_state",
        }[name]
        return CameraCommand(
            *values[:5],
            packed_mode & 0xFF,
            values[6],
            word(visual_name, index),
            packed_mode >> 8,
            values[7],
        )

    observations = {name: word(name) for name in SELECTOR_OBSERVATION_SYMBOLS}
    unavailable = {
        name
        for name, value in observations.items()
        if value == SELECTOR_OBSERVATION_UNAVAILABLE
    }
    if unavailable and len(unavailable) != len(observations):
        available = sorted(set(observations) - unavailable)
        raise ValueError(
            "selector observation telemetry mixes unavailable and live fields: "
            f"unavailable={sorted(unavailable)}, live={available}"
        )

    def observation(name: str) -> int | None:
        value = observations[name]
        return None if value == SELECTOR_OBSERVATION_UNAVAILABLE else value

    return Telemetry(
        controls=Controls(
            yaw=word("yaw_index"),
            pitch=word("pitch_level"),
            x=word("camera_x"),
            y=word("camera_y"),
            z=word("camera_z"),
            technique=word("technique"),
            revision=word("control_revision"),
        ),
        producer_slot=word("producer_slot"),
        ready_slot=word("ready_slot"),
        upload_slot=word("upload_slot"),
        frame_ready=word("frame_ready"),
        upload_active=word("upload_active"),
        upload_target=word("upload_target"),
        upload_chunk=word("upload_chunk"),
        render_counter=word("render_counter"),
        present_counter=word("present_counter"),
        active_leaf=word("active_leaf"),
        active_pvs_face_count=word("active_pvs_face_count"),
        active_pvs_revision=word("active_pvs_revision"),
        active_selection_revision=word("active_selection_revision"),
        active_pvs_encoded_bytes=word("active_pvs_encoded_bytes"),
        active_bsp_node_count=observation("active_bsp_node_count"),
        packet=PacketTelemetry(
            vertex_count=word("active_packet_vertex_count"),
            index_count=word("active_packet_index_count"),
            face_count=word("active_packet_face_count"),
            plane_count=word("active_packet_plane_count"),
            overflow_face=word("active_packet_overflow_face"),
            overflow_vertex=word("active_packet_overflow_vertex"),
            overflow_index=word("active_packet_overflow_index"),
            revision=word("active_packet_revision"),
            camera_revision=word("active_packet_camera_revision"),
            guard_status=word("active_packet_guard_status"),
            drawable_face_count=observation("active_packet_drawable_count"),
            front_face_count=observation("active_packet_front_count"),
            near_face_count=observation("active_packet_near_count"),
            screen_face_count=observation("active_packet_screen_count"),
            painter_node_count=observation("active_packet_painter_node_count"),
            error_flags=word("active_packet_error"),
        ),
        render_camera=camera("render_camera"),
        slot_cameras=(camera("slot_camera", 0), camera("slot_camera", 1)),
        presented_camera=camera("presented_camera"),
        demo_mode=word("demo_mode"),
        demo_schedule=word("demo_schedule"),
        demo_playback_rate_shift=word("demo_playback_rate_shift"),
        demo_offset=word("demo_offset"),
        demo_timing_offset=word("demo_timing_offset"),
        demo_next_pose=word("demo_next_pose"),
        demo_track_pose=word("demo_track_pose"),
        demo_pose_due_tick=word("demo_pose_due_tick"),
        demo_pose_counter=word("demo_pose_counter"),
        demo_source_due_counter=word("demo_source_due_counter"),
        demo_coalesced_counter=word("demo_coalesced_counter"),
        demo_playhead_tick=word("demo_playhead_tick"),
        demo_schedule_revision=word("demo_schedule_revision"),
        demo_loop_counter=word("demo_loop_counter"),
        video_tick=word("video_tick"),
        stage_frame_required=word("stage_frame_required"),
        gsu_job_counter=word("gsu_job_counter"),
        staging_dma_counter=word("staging_dma_counter"),
        vram_chunk_counter=word("vram_chunk_counter"),
        page_flip_counter=word("page_flip_counter"),
        coverage_debug=word("coverage_debug"),
        render_coverage_mode=word("render_coverage_mode"),
        slot_coverage_modes=(
            word("slot_coverage_mode", 0),
            word("slot_coverage_mode", 1),
        ),
        presented_coverage_mode=word("presented_coverage_mode"),
        runtime_menu_open=word("runtime_menu_open"),
        runtime_menu_selection=word("runtime_menu_selection"),
        runtime_menu_draft_playback=word("runtime_menu_draft_playback"),
        render_demo_pose=word("render_demo_pose"),
        render_demo_due_tick=word("render_demo_due_tick"),
        render_demo_epoch=word("render_demo_epoch"),
        slot_demo_poses=(word("slot_demo_pose", 0), word("slot_demo_pose", 1)),
        slot_demo_due_ticks=(
            word("slot_demo_due_tick", 0),
            word("slot_demo_due_tick", 1),
        ),
        slot_demo_epochs=(word("slot_demo_epoch", 0), word("slot_demo_epoch", 1)),
        presented_demo_pose=word("presented_demo_pose"),
        presented_demo_due_tick=word("presented_demo_due_tick"),
        presented_demo_epoch=word("presented_demo_epoch"),
    )


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def packet_evidence(session: Any, telemetry: Any) -> dict[str, Any]:
    """Hash every published packet stream under the canonical runtime layout."""
    packet = telemetry.packet
    face_count = packet.face_count
    source_faces = session.read_memory(
        "gsuRam", PACKET_SOURCE_FACES_ADDRESS, face_count * 2
    )
    vertices = session.read_memory(
        "gsuRam", PACKET_VERTICES_ADDRESS, packet.vertex_count * PACKET_VERTEX_BYTES
    )
    indices = session.read_memory(
        "gsuRam", PACKET_INDICES_ADDRESS, packet.index_count * PACKET_INDEX_BYTES
    )
    faces = session.read_memory(
        "gsuRam", PACKET_FACES_ADDRESS, face_count * PACKET_FACE_BYTES
    )
    face_planes = session.read_memory(
        "gsuRam", PACKET_FACE_PLANES_ADDRESS, face_count * PACKET_FACE_PLANE_BYTES
    )
    return {
        "leaf": telemetry.active_leaf,
        "sourceFacesSha256": _sha256(source_faces),
        "verticesSha256": _sha256(vertices),
        "indicesSha256": _sha256(indices),
        "facesSha256": _sha256(faces),
        "facePlanesSha256": _sha256(face_planes),
        "vertexCount": packet.vertex_count,
        "indexCount": packet.index_count,
        "faceCount": face_count,
    }


def load_packet_fixtures(
    path: Path, *, include_orientation: bool = False
) -> tuple[PacketFixture, ...]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(
            f"cannot load packet oracle fixture {path}: {error}"
        ) from error
    if (
        not isinstance(document, dict)
        or document.get("schema") != PACKET_FIXTURE_SCHEMA
    ):
        raise ValueError(
            f"packet oracle fixture must use schema {PACKET_FIXTURE_SCHEMA}"
        )
    contract = document.get("contract")
    if not isinstance(contract, dict):
        raise ValueError("packet oracle fixture lacks its packet contract")
    if contract.get("streams") != PACKET_STREAM_CONTRACT:
        raise ValueError("packet oracle fixture has a stale stream layout")
    if contract.get("capacities") != {
        "vertices": PACKET_VERTEX_CAPACITY,
        "indices": PACKET_INDEX_CAPACITY,
        "faces": PACKET_FACE_CAPACITY,
        "facePlanes": PACKET_FACE_CAPACITY,
    }:
        raise ValueError("packet oracle fixture has stale packet capacities")
    if document.get("returnSpawnByteIdentical") is not True:
        raise ValueError("packet oracle fixture does not certify the spawn return")
    records = document.get("fixtures")
    if not isinstance(records, list) or len(records) != 6:
        raise ValueError(
            "packet oracle fixture must contain exactly six camera fixtures"
        )

    def integer_dict(record: Any, name: str, keys: tuple[str, ...]) -> dict[str, int]:
        if not isinstance(record, dict) or set(record) != set(keys):
            raise ValueError(f"packet fixture {name!r} has invalid keys")
        values = {key: value for key, value in record.items()}
        if any(not isinstance(value, int) or value < 0 for value in values.values()):
            raise ValueError(f"packet fixture {name!r} contains invalid counts")
        return values

    fixtures: list[PacketFixture] = []
    for raw in records:
        if not isinstance(raw, dict):
            raise ValueError("packet waypoint fixture must be an object")
        name = raw.get("name")
        camera = raw.get("camera")
        source_ids = raw.get("sourceFaceIds")
        absent = raw.get("sourceFacesAbsentFromSpawn")
        hashes = raw.get("hashes")
        if not isinstance(name, str):
            raise ValueError("packet waypoint fixture lacks a name")
        if (
            not isinstance(camera, list)
            or len(camera) != 3
            or any(
                not isinstance(value, int) or not -128 <= value <= 127
                for value in camera
            )
        ):
            raise ValueError(f"packet fixture {name!r} has an invalid camera")
        if (
            not isinstance(source_ids, list)
            or any(
                not isinstance(value, int) or not 0 <= value <= 0xFFFF
                for value in source_ids
            )
            or len(source_ids) != len(set(source_ids))
        ):
            raise ValueError(f"packet fixture {name!r} has invalid source-face IDs")
        if (
            not isinstance(absent, list)
            or any(
                not isinstance(value, int) or not 0 <= value <= 0xFFFF
                for value in absent
            )
            or len(absent) != len(set(absent))
        ):
            raise ValueError(
                f"packet fixture {name!r} has invalid absent-face evidence"
            )
        if not isinstance(hashes, dict) or any(
            not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None
            for value in hashes.values()
        ):
            raise ValueError(f"packet fixture {name!r} has invalid hashes")
        required_hashes = {
            "verticesSha256",
            "indicesSha256",
            "facesSha256",
            "facePlanesSha256",
            "sourceFacesSha256",
            "runtimePacketSha256",
        }
        if set(hashes) != required_hashes:
            raise ValueError(f"packet fixture {name!r} has incomplete stream hashes")

        counts = integer_dict(raw.get("counts"), name, ("vertices", "indices", "faces"))
        byte_counts = integer_dict(
            raw.get("bytes"), name, ("vertices", "indices", "faces", "facePlanes")
        )
        stages = integer_dict(
            raw.get("stageCounts"),
            name,
            (
                "pvsFaces",
                "drawableFaces",
                "frontFacingFaces",
                "nearValidFaces",
                "screenCandidateFaces",
                "selectedFaces",
            ),
        )
        overflows = integer_dict(
            raw.get("capacityRejections"),
            name,
            ("face_capacity", "vertex_capacity", "index_capacity"),
        )
        if (
            counts["faces"] != len(source_ids)
            or stages["selectedFaces"] != counts["faces"]
        ):
            raise ValueError(f"packet fixture {name!r} has inconsistent face counts")
        expected_bytes = {
            "vertices": counts["vertices"] * PACKET_VERTEX_BYTES,
            "indices": counts["indices"] * PACKET_INDEX_BYTES,
            "faces": counts["faces"] * PACKET_FACE_BYTES,
            "facePlanes": counts["faces"] * PACKET_FACE_PLANE_BYTES,
        }
        if byte_counts != expected_bytes:
            raise ValueError(f"packet fixture {name!r} has inconsistent byte counts")
        if (
            counts["vertices"] > PACKET_VERTEX_CAPACITY
            or counts["indices"] > PACKET_INDEX_CAPACITY
            or counts["faces"] > PACKET_FACE_CAPACITY
        ):
            raise ValueError(f"packet fixture {name!r} exceeds a packet capacity")
        source_payload = b"".join(struct.pack("<H", value) for value in source_ids)
        if _sha256(source_payload) != hashes["sourceFacesSha256"]:
            raise ValueError(f"packet fixture {name!r} source-face hash disagrees")

        scalar_fields = (
            "yaw",
            "pitch",
            "leaf",
            "leafNodeVisits",
            "painterInducedNodes",
        )
        if any(not isinstance(raw.get(field), int) for field in scalar_fields):
            raise ValueError(f"packet fixture {name!r} has invalid scalar fields")
        fixtures.append(
            PacketFixture(
                name=name,
                camera=tuple(camera),
                yaw=raw["yaw"],
                pitch=raw["pitch"],
                leaf=raw["leaf"],
                leaf_node_visits=raw["leafNodeVisits"],
                painter_induced_nodes=raw["painterInducedNodes"],
                stage_counts=stages,
                overflow_counts=overflows,
                counts=counts,
                byte_counts=byte_counts,
                source_face_ids=tuple(source_ids),
                source_faces_absent_from_spawn=tuple(absent),
                hashes=dict(hashes),
            )
        )

    if tuple(fixture.name for fixture in fixtures) != PACKET_FIXTURE_ORDER:
        raise ValueError("packet camera fixtures are not in the accepted order")
    spawn_source_faces = set(fixtures[0].source_face_ids)
    for fixture in fixtures:
        derived_absent = tuple(
            sorted(set(fixture.source_face_ids) - spawn_source_faces)
        )
        if fixture.source_faces_absent_from_spawn != derived_absent:
            raise ValueError(
                f"packet fixture {fixture.name!r} absent-from-spawn faces "
                "disagree with its source-face IDs"
            )
    if any(not fixtures[index].source_faces_absent_from_spawn for index in (1, 2)):
        raise ValueError(
            "non-spawn packet fixtures contain no geometry absent from spawn"
        )
    if (
        fixtures[0].counts != fixtures[-1].counts
        or fixtures[0].hashes != fixtures[-1].hashes
    ):
        raise ValueError("return packet fixture is not byte-identical to spawn")
    by_name = {fixture.name: fixture for fixture in fixtures}
    order = PACKET_FIXTURE_ORDER if include_orientation else WAYPOINT_ORDER
    return tuple(by_name[name] for name in order)


def validate_packet_counts(packet: PacketTelemetry) -> None:
    if not 0 <= packet.vertex_count <= PACKET_VERTEX_CAPACITY:
        raise VerificationError(
            f"packet vertex count is out of range: {packet.vertex_count}"
        )
    if not 0 <= packet.index_count <= PACKET_INDEX_CAPACITY:
        raise VerificationError(
            f"packet index count is out of range: {packet.index_count}"
        )
    if not 0 <= packet.face_count <= PACKET_FACE_CAPACITY:
        raise VerificationError(
            f"packet face count is out of range: {packet.face_count}"
        )
    if packet.plane_count != packet.face_count:
        raise VerificationError(
            f"packet plane count {packet.plane_count} does not match face count {packet.face_count}"
        )


def packet_publication_complete(telemetry: Telemetry) -> bool:
    """Return whether shared packet counts belong to one finished selector."""
    packet = telemetry.packet
    return (
        packet.revision != 0xFFFF
        and telemetry.active_selection_revision
        == packet.revision
        == packet.camera_revision
    )


def signed_word(value: int) -> int:
    value &= 0xFFFF
    return value - 0x10000 if value & 0x8000 else value


def manual_fixture_failures(telemetry: Telemetry, fixture: PacketFixture) -> list[str]:
    actual_camera_q8 = tuple(
        signed_word(value)
        for value in (telemetry.controls.x, telemetry.controls.y, telemetry.controls.z)
    )
    expected_camera_q8 = tuple(value << 8 for value in fixture.camera)
    failures: list[str] = []
    if telemetry.demo_mode != 0:
        failures.append(f"demo mode is {telemetry.demo_mode}, expected manual mode 0")
    if actual_camera_q8 != expected_camera_q8:
        failures.append(
            f"camera is {tuple(value / 256 for value in actual_camera_q8)}, "
            f"expected {fixture.camera}"
        )
    actual_yaw = telemetry.controls.yaw & 0x1F
    if actual_yaw != fixture.yaw:
        failures.append(f"yaw is {actual_yaw}, expected {fixture.yaw}")
    actual_pitch = signed_word(telemetry.controls.pitch)
    if actual_pitch != fixture.pitch:
        failures.append(f"pitch is {actual_pitch}, expected {fixture.pitch}")
    return failures


def counter_delta(before: int, after: int) -> int:
    return (after - before) & 0xFFFF


def signed_delta(before: int, after: int) -> int:
    value = counter_delta(before, after)
    return value - 0x10000 if value & 0x8000 else value


def presentation_failures(
    current: Telemetry,
    active_page: int,
    previous: Telemetry | None = None,
    previous_page: int | None = None,
) -> list[str]:
    failures: list[str] = []
    if current.upload_target not in (0, 1):
        failures.append(f"upload_target {current.upload_target} is not a page")
    elif active_page != (current.upload_target ^ 1):
        failures.append(
            f"visible page {active_page} is not opposite upload_target {current.upload_target}"
        )
    if current.upload_slot not in (0, 1):
        failures.append(f"upload_slot {current.upload_slot} is not a slot")
    if current.upload_active not in (0, 1):
        failures.append(f"upload_active {current.upload_active} is not boolean")
    if not 0 <= current.upload_chunk <= 8:
        failures.append(f"upload_chunk {current.upload_chunk} is outside 0..8")
    if current.coverage_debug not in (0, 1, 2):
        failures.append(
            f"coverage_debug {current.coverage_debug} is not production/phase 0/phase 1"
        )
    if current.render_coverage_mode not in (0, 1, 2):
        failures.append(
            f"render coverage mode {current.render_coverage_mode} is outside 0..2"
        )
    if current.presented_coverage_mode not in (0, 1, 2):
        failures.append(
            f"presented coverage mode {current.presented_coverage_mode} is outside 0..2"
        )
    for slot, mode in enumerate(current.slot_coverage_modes):
        if mode not in (0, 1, 2):
            failures.append(f"slot {slot} coverage mode {mode} is outside 0..2")
    if current.demo_schedule not in (0, 1):
        failures.append(
            f"demo schedule {current.demo_schedule} is not ordered/realtime"
        )
    if current.demo_playback_rate_shift not in (0, 1, 2):
        failures.append(
            "demo playback rate shift "
            f"{current.demo_playback_rate_shift} is outside 0..2"
        )
    if current.presented_camera.technique not in (2, 4, 7):
        failures.append(
            f"presented technique {current.presented_camera.technique} is not "
            "one of the supported renderers 2, 4, or 7"
        )
    if not 0 <= current.presented_camera.yaw < 32:
        failures.append(
            f"presented yaw {current.presented_camera.yaw} is outside 0..31"
        )
    if not 0 <= current.presented_camera.pitch < 32:
        failures.append(
            f"presented pitch {current.presented_camera.pitch} is outside 0..31"
        )
    if (
        current.upload_active == 0
        and current.upload_slot in (0, 1)
        and current.present_counter >= 2
        and current.presented_camera != current.slot_cameras[current.upload_slot]
    ):
        failures.append(
            "idle presented camera does not match the committed upload slot"
        )
    if (
        current.upload_active == 0
        and current.upload_slot in (0, 1)
        and current.present_counter >= 2
        and current.presented_coverage_mode
        != current.slot_coverage_modes[current.upload_slot]
    ):
        failures.append(
            "idle presented coverage mode does not match the committed upload slot"
        )
    if (
        current.upload_active == 0
        and current.upload_slot in (0, 1)
        and current.present_counter >= 2
        and (
            current.presented_demo_pose != current.slot_demo_poses[current.upload_slot]
            or current.presented_demo_due_tick
            != current.slot_demo_due_ticks[current.upload_slot]
            or current.presented_demo_epoch
            != current.slot_demo_epochs[current.upload_slot]
        )
    ):
        failures.append("idle presented demo metadata does not match upload slot")

    if previous is not None:
        delta = counter_delta(previous.present_counter, current.present_counter)
        flip_delta = counter_delta(
            previous.page_flip_counter, current.page_flip_counter
        )
        if previous_page is None:
            failures.append("previous page is required with previous telemetry")
        elif active_page != (previous_page ^ (flip_delta & 1)):
            failures.append(
                f"visible page parity disagrees with {flip_delta} page flips"
            )
        if delta == 0 and current.presented_camera != previous.presented_camera:
            failures.append("presented camera changed without a presentation commit")
        if (
            delta == 0
            and current.presented_coverage_mode != previous.presented_coverage_mode
        ):
            failures.append(
                "presented coverage mode changed without a presentation commit"
            )
        if delta == 0 and (
            current.presented_demo_pose != previous.presented_demo_pose
            or current.presented_demo_due_tick != previous.presented_demo_due_tick
            or current.presented_demo_epoch != previous.presented_demo_epoch
        ):
            failures.append("presented demo metadata changed without a commit")
    return failures


def validate_control_results(results: Sequence[ControlResult]) -> None:
    if tuple(result.button for result in results) != CONTROL_BUTTONS:
        raise VerificationError(
            f"control sequence must be {CONTROL_BUTTONS}, got {tuple(r.button for r in results)}"
        )
    for result in results:
        actual_advances = counter_delta(result.before.revision, result.after.revision)
        expected_advances = CONTROL_REVISION_ADVANCES[result.button]
        if actual_advances != expected_advances:
            raise VerificationError(
                f"{result.button}: control revision advanced by {actual_advances}, "
                f"expected {expected_advances}"
            )

    by_button = {result.button: result for result in results}
    left = by_button["left"]
    right = by_button["right"]
    up = by_button["up"]
    down = by_button["down"]
    if left.after.yaw != ((left.before.yaw - 1) & 31):
        raise VerificationError("left: yaw did not step one slot counter-clockwise")
    if right.after.yaw != ((right.before.yaw + 1) & 31):
        raise VerificationError("right: yaw did not step one slot clockwise")
    if signed_delta(up.before.pitch, up.after.pitch) != 1:
        raise VerificationError("up: pitch did not increase by one level")
    if signed_delta(down.before.pitch, down.after.pitch) != -1:
        raise VerificationError("down: pitch did not decrease by one level")

    validate_opposite_xyz(by_button["x"], by_button["b"], context="x/b")
    strafe_left = control_xyz_delta(by_button["y"])
    strafe_right = control_xyz_delta(by_button["a"])
    if strafe_left[:2] == (0, 0) or strafe_right != tuple(
        -value for value in strafe_left
    ):
        raise VerificationError("y/a: strafe camera deltas are not opposites")
    if strafe_left[2] != 0:
        raise VerificationError("y/a: strafe changed world Z")

    for button in ("l", "r"):
        placement = by_button[button]
        before = (
            placement.before.yaw,
            placement.before.x,
            placement.before.y,
            placement.before.z,
        )
        after = (
            placement.after.yaw,
            placement.after.x,
            placement.after.y,
            placement.after.z,
        )
        if placement.after.pitch != 0 or before == after:
            raise VerificationError(
                f"{button}: monster-camera placement did not replace the fly pose"
            )


def control_xyz_delta(result: ControlResult) -> tuple[int, int, int]:
    """Return one control pulse's signed camera displacement."""

    return (
        signed_delta(result.before.x, result.after.x),
        signed_delta(result.before.y, result.after.y),
        signed_delta(result.before.z, result.after.z),
    )


def validate_opposite_xyz(
    forward: ControlResult,
    backward: ControlResult,
    *,
    context: str,
) -> tuple[int, int, int]:
    """Require a nonzero forward pulse and an exactly opposite backward pulse."""

    forward_delta = control_xyz_delta(forward)
    backward_delta = control_xyz_delta(backward)
    if forward_delta == (0, 0, 0):
        raise VerificationError(f"{context}: forward movement is zero")
    if backward_delta != tuple(-value for value in forward_delta):
        raise VerificationError(
            f"{context}: forward/backward XYZ deltas are not opposites"
        )
    return forward_delta
