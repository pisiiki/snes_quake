"""Transport-neutral E1M3 demo playback contracts."""

from __future__ import annotations

import json
import struct
from bisect import bisect_right
from pathlib import Path

from workspace_paths import workspace_root
from typing import Any, Sequence

import quake_bsp_validation as validation

DATA_DIR = workspace_root(__file__) / "src/snes_quake/Data"

TRACK_RECORD = struct.Struct("<bbbBb")

TIMING_RECORD = struct.Struct("<H")

PRECISE_TRACK_RECORD = struct.Struct("<hhhHH")

def _generated_sample_rate_hz(data_dir: Path = DATA_DIR) -> int:
    try:
        metadata = json.loads(
            (data_dir / "QuakeBSPMetadata.json").read_text(encoding="ascii")
        )
        sample_rate = metadata["demo"]["precise_track_sample_rate_hz"]
    except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return 20
    if not isinstance(sample_rate, int) or sample_rate <= 0:
        return 20
    return sample_rate


PRECISE_SAMPLE_RATE_HZ = _generated_sample_rate_hz()

STEP_SAMPLE_RATE_HZ = 2

ORDERED_POSE_STRIDE = PRECISE_SAMPLE_RATE_HZ // STEP_SAMPLE_RATE_HZ

def _generated_source_identity(data_dir: Path = DATA_DIR) -> tuple[str, str]:
    try:
        metadata = json.loads(
            (data_dir / "QuakeBSPMetadata.json").read_text(encoding="ascii")
        )
        map_entry = str(metadata["demo"]["map_entry"])
        demo_entry = str(metadata["demo"]["entry"])
    except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return "maps/e1m3.bsp", "demo1.dem"
    return map_entry, demo_entry


EXPECTED_MAP, EXPECTED_DEMO = _generated_source_identity()

SCHEDULES = {"ordered": 0, "realtime": 1}

REALTIME_RATE_SHIFTS = {"realtime": 0, "half": 1, "quarter": 2}

DEFAULT_RENDERED_FRAMES = 32


def source_tick_for_rate(elapsed_video_ticks: int, rate_shift: int) -> int:
    if elapsed_video_ticks < 0:
        raise ValueError("elapsed video ticks must be nonnegative")
    if rate_shift not in REALTIME_RATE_SHIFTS.values():
        raise ValueError("realtime rate shift must be 0, 1, or 2")
    return elapsed_video_ticks >> rate_shift


def step_pose_indices(pose_count: int) -> tuple[int, ...]:
    if pose_count < 1:
        raise ValueError("step schedule requires a non-empty canonical track")
    return tuple(range(0, pose_count, ORDERED_POSE_STRIDE))


def newest_due_pose(ticks: Sequence[int], tick: int) -> int:
    if not ticks or tick < ticks[0]:
        raise ValueError("playback tick precedes a non-empty canonical schedule")
    return bisect_right(ticks, tick) - 1


def restart_cursor_ready(
    schedule: str,
    telemetry: Any,
    expected_pose: int,
    ordered_stride: int = ORDERED_POSE_STRIDE,
) -> bool:
    """Accept pose zero either loaded or already staged by ordered playback."""

    if telemetry.demo_track_pose == expected_pose:
        return True
    if schedule != "ordered" or telemetry.demo_track_pose != ordered_stride:
        return False
    epoch = telemetry.demo_schedule_revision
    return any(
        pose == 0 and slot_epoch == epoch
        for pose, slot_epoch in zip(
            getattr(telemetry, "slot_demo_poses", ()),
            getattr(telemetry, "slot_demo_epochs", ()),
            strict=True,
        )
    )


def signed8(value: int) -> int:
    value &= 0xFF
    return value - 0x100 if value & 0x80 else value


def signed5(value: int) -> int:
    value &= 31
    return value - 32 if value & 16 else value


def command_signature(command: validation.CameraCommand) -> tuple[int, ...]:
    """Return camera identity without the monotonically increasing revision."""
    return (
        command.yaw,
        command.pitch,
        command.x,
        command.y,
        command.z,
        command.technique,
    )


def track_signature(
    pose: tuple[int, int, int, int, int],
    start: tuple[int, int, int],
    technique: int,
) -> tuple[int, ...]:
    x, y, z, yaw, pitch = pose
    return (
        yaw,
        pitch & 31,
        (x - start[0]) & 0xFF,
        (y - start[1]) & 0xFF,
        (z - start[2]) & 0xFF,
        technique,
    )


def precise_track_signature(
    pose: tuple[int, ...],
    origin: Sequence[float],
    start: tuple[int, int, int],
    technique: int,
) -> tuple[int, ...]:
    """Match the ROM's exact Q3 load followed by its current coarse GSU handoff."""
    if len(pose) != 5 or len(origin) != 3:
        raise ValueError("invalid precise camera or world origin")
    camera_q8 = tuple(
        (pose[axis] - round(float(origin[axis]) * 8.0)) * 2
        for axis in range(3)
    )
    relative = tuple(
        ((camera_q8[axis] - (start[axis] << 8)) & 0xFFFF) >> 8
        for axis in range(3)
    )
    yaw = ((pose[3] + 0x0400) & 0xFFFF) >> 11
    pitch = ((-pose[4] + 0x0400) & 0xFFFF) >> 11
    return (yaw, pitch, *relative, technique)


def command_global_position(
    command: validation.CameraCommand, start: tuple[int, int, int]
) -> tuple[int, int, int]:
    """Undo StageCommand's start-relative unsigned-byte camera encoding."""
    return (
        signed8(start[0] + command.x),
        signed8(start[1] + command.y),
        signed8(start[2] + command.z),
    )


def load_contract(
    data_dir: Path = DATA_DIR,
) -> tuple[dict[str, Any], tuple[tuple[int, int, int, int, int], ...]]:
    metadata = json.loads(
        (data_dir / "QuakeBSPMetadata.json").read_text(encoding="ascii")
    )
    demo = metadata.get("demo", {})
    source = metadata.get("source", {})
    if source.get("pak_entry") != EXPECTED_MAP or demo.get("map_entry") != EXPECTED_MAP:
        raise validation.VerificationError(
            "generated package is not the requested E1M3 map"
        )
    if source.get("demo_entry") != demo.get("entry"):
        raise validation.VerificationError(
            "source and demo stream metadata disagree"
        )
    payload = (data_dir / "QuakeBSPDemoTrack.bin").read_bytes()
    if len(payload) % TRACK_RECORD.size:
        raise validation.VerificationError("demo track is not five-byte record aligned")
    poses = tuple(TRACK_RECORD.iter_unpack(payload))
    if len(poses) != demo.get("track_pose_count") or len(payload) != demo.get(
        "track_bytes"
    ):
        raise validation.VerificationError(
            "demo metadata disagrees with the packed track"
        )
    if len(poses) < 2 or len(poses) != demo.get("source_camera_samples"):
        raise validation.VerificationError(
            "demo track does not retain every reconstructed source camera sample"
        )
    return metadata, poses


def load_schedule_contract(
    data_dir: Path = DATA_DIR,
) -> tuple[
    dict[str, Any],
    tuple[tuple[int, int, int, int, int], ...],
    tuple[int, ...],
]:
    metadata, poses = load_contract(data_dir)
    demo = metadata["demo"]
    payload = (data_dir / "QuakeBSPDemoTiming.bin").read_bytes()
    if len(payload) % TIMING_RECORD.size:
        raise validation.VerificationError("demo timing is not uint16 aligned")
    ticks = tuple(value[0] for value in TIMING_RECORD.iter_unpack(payload))
    timing_rows = demo.get("pose_timing", [])
    if (
        len(ticks) != len(poses)
        or len(payload) != demo.get("timing_bytes")
        or len(timing_rows) != len(poses)
    ):
        raise validation.VerificationError(
            "demo timing, track, source mapping, and metadata counts disagree"
        )
    if ticks[0] != 0 or any(right < left for left, right in zip(ticks, ticks[1:])):
        raise validation.VerificationError(
            "demo timing ticks are not monotonic"
        )
    for index, (tick, row) in enumerate(zip(ticks, timing_rows, strict=True)):
        if row["track_pose"] != index or row["ntsc_tick"] != tick:
            raise validation.VerificationError(
                f"demo timing source mapping disagrees at pose {index}"
            )
    if ticks[-1] != demo.get("duration_ticks"):
        raise validation.VerificationError(
            "demo duration tick disagrees with final pose"
        )
    return metadata, poses, ticks


def load_precise_track_contract(
    data_dir: Path = DATA_DIR,
) -> tuple[dict[str, Any], tuple[tuple[int, ...], ...]]:
    metadata, poses, _ticks = load_schedule_contract(data_dir)
    demo = metadata["demo"]
    payload = (data_dir / "QuakeBSPDemoPrecise.bin").read_bytes()
    if len(payload) % PRECISE_TRACK_RECORD.size:
        raise validation.VerificationError(
            "precise demo track is not ten-byte record aligned"
        )
    samples = tuple(PRECISE_TRACK_RECORD.iter_unpack(payload))
    if (
        len(samples) != demo.get("precise_track_pose_count")
        or len(payload) != demo.get("precise_track_bytes")
        or demo.get("precise_track_record_bytes") != PRECISE_TRACK_RECORD.size
        or demo.get("precise_track_sample_rate_hz") != PRECISE_SAMPLE_RATE_HZ
    ):
        raise validation.VerificationError(
            "precise demo track and metadata disagree"
        )
    if not samples:
        raise validation.VerificationError("precise fixed-rate track is empty")
    # External demos pack every source sample into the step track while
    # the precise track stays at the configured fixed rate, so a count comparison is
    # only valid for the canonical tiny demo.
    if demo.get("entry") == "demo1.dem" and len(samples) < len(poses):
        raise validation.VerificationError(
            "precise fixed-rate track does not cover the source demo"
        )
    if demo.get("precise_track_sampling") != (
        "newest source transform due at n/sampleRateHz; no interpolation"
    ):
        raise validation.VerificationError(
            "precise demo sampling contract is not fixed-rate point sampling"
        )
    return metadata, samples


def load_precise_schedule_contract(
    data_dir: Path = DATA_DIR,
) -> tuple[
    dict[str, Any],
    tuple[tuple[int, ...], ...],
    tuple[int, ...],
]:
    metadata, samples = load_precise_track_contract(data_dir)
    demo = metadata["demo"]
    payload = (data_dir / "QuakeBSPDemoPreciseTiming.bin").read_bytes()
    if len(payload) % TIMING_RECORD.size:
        raise validation.VerificationError(
            "precise demo timing is not uint16 aligned"
        )
    ticks = tuple(value[0] for value in TIMING_RECORD.iter_unpack(payload))
    expected_steps = step_pose_indices(len(samples))
    if (
        len(ticks) != len(samples)
        or len(payload) != demo.get("precise_timing_bytes")
        or demo.get("precise_timing_record_bytes") != TIMING_RECORD.size
        or ticks[-1] != demo.get("precise_duration_ticks")
        or demo.get("step_sample_rate_hz") != STEP_SAMPLE_RATE_HZ
        or demo.get("ordered_pose_stride") != ORDERED_POSE_STRIDE
        or demo.get("step_pose_count") != len(expected_steps)
        or tuple(demo.get("step_pose_indices", ())) != expected_steps
    ):
        raise validation.VerificationError(
            "precise demo schedule and metadata disagree"
        )
    if ticks[0] != 0 or any(
        right < left for left, right in zip(ticks, ticks[1:])
    ):
        raise validation.VerificationError(
            "precise demo timing ticks are not monotonic"
        )
    return metadata, samples, ticks


def validate_packet(telemetry: validation.Telemetry, context: str) -> None:
    packet = telemetry.packet
    validation.validate_packet_counts(packet)
    failures = []
    if packet.guard_status != validation.PACKET_GUARD_OK:
        failures.append(f"guard=0x{packet.guard_status:04x}")
    if packet.error_flags:
        failures.append(f"error=0x{packet.error_flags:04x}")
    overflows = (packet.overflow_face, packet.overflow_vertex, packet.overflow_index)
    if overflows != (0, 0, 0):
        failures.append(f"capacityOverflows={overflows}")
    if failures:
        raise validation.VerificationError(
            f"{context}: invalid packet: {', '.join(failures)}"
        )
