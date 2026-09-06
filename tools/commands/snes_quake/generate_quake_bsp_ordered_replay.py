#!/usr/bin/env python3
"""Generate a host-side packed packet replay at a deterministic source stride."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from workspace_paths import shared_tools_root, workspace_root
from typing import Any


TOOLS = Path(__file__).resolve().parent
EXAMPLE = workspace_root(__file__) / "src/snes_quake"
SHARED = shared_tools_root(__file__)
sys.path[:0] = [str(TOOLS), str(SHARED)]

import quake_bsp_demo_contract as demo_contract  # noqa: E402
import quake_bsp_packet_oracle as packet_oracle  # noqa: E402
from snes_tooling.shared.generated_outputs import GeneratedOutputError, sync_generated_outputs  # noqa: E402
from quake_brush_replay import fnv1a64  # noqa: E402


DEFAULT_OUTPUT = EXAMPLE / "Data"
DEFAULT_DATA_DIR = EXAMPLE / "Data"
BINARY_PATH = Path("QuakeBSPOrderedReplay.bin")
REPORT_PATH = Path("QuakeBSPOrderedReplay.json")
FULL_RATE_BINARY_PATH = Path("QuakeBSPOrderedReplay20Hz.bin")
FULL_RATE_REPORT_PATH = Path("QuakeBSPOrderedReplay20Hz.json")
PRECISE_TRACK_PATH = Path("QuakeBSPDemoPrecise.bin")
METADATA_PATH = Path("QuakeBSPMetadata.json")

MAGIC = b"QOR1"
VERSION = 1
HEADER = struct.Struct("<4s8HQQI")
FRAME_RECORD = struct.Struct("<HbbbBbBHI")
FACE_RECORD = struct.Struct("<H")


@dataclass(frozen=True)
class OrderedFrame:
    source_pose: int
    camera: packet_oracle.CameraState
    source_faces: tuple[int, ...]
    vertex_count: int
    index_count: int
    rejections: packet_oracle.Rejections = packet_oracle.Rejections()


@dataclass(frozen=True)
class OrderedReplay:
    source_pose_count: int
    source_rate_hz: int
    step_rate_hz: int
    stride: int
    track_fnv1a64: int
    metadata_fnv1a64: int
    frames: tuple[OrderedFrame, ...]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def packed_camera(
    metadata: dict[str, Any], sample: tuple[int, ...]
) -> packet_oracle.CameraState:
    start = tuple(
        int(value) for value in metadata["selection"]["player_start_coordinate"]
    )
    signature = demo_contract.precise_track_signature(
        sample,
        metadata["world"]["quantization"]["origin"],
        start,
        0,
    )
    yaw, pitch, x, y, z, _technique = signature
    position = tuple(
        demo_contract.signed8(start[axis] + value)
        for axis, value in enumerate((x, y, z))
    )
    return packet_oracle.CameraState(position, yaw & 31, demo_contract.signed5(pitch))


def build_replay(
    data_dir: Path, *, stride: int = demo_contract.ORDERED_POSE_STRIDE
) -> OrderedReplay:
    metadata, samples, _ticks = demo_contract.load_precise_schedule_contract(data_dir)
    if stride < 1 or demo_contract.PRECISE_SAMPLE_RATE_HZ % stride:
        raise ValueError("ordered replay stride must divide the precise sample rate")
    world = packet_oracle.load_world(data_dir)
    source_poses = tuple(range(0, len(samples), stride))
    frames: list[OrderedFrame] = []
    for source_pose in source_poses:
        camera = packed_camera(metadata, samples[source_pose])
        selector_camera = packet_oracle.CameraState(
            camera.position, camera.yaw & 31, camera.pitch & 31
        )
        packet = packet_oracle.build_render_packet(world, selector_camera)
        frames.append(
            OrderedFrame(
                source_pose=source_pose,
                camera=camera,
                source_faces=packet.source_face_ids,
                vertex_count=packet.vertex_count,
                index_count=packet.index_count,
                rejections=packet.rejections,
            )
        )
    track = (data_dir / PRECISE_TRACK_PATH).read_bytes()
    metadata_bytes = (data_dir / METADATA_PATH).read_bytes()
    return OrderedReplay(
        source_pose_count=len(samples),
        source_rate_hz=demo_contract.PRECISE_SAMPLE_RATE_HZ,
        step_rate_hz=demo_contract.PRECISE_SAMPLE_RATE_HZ // stride,
        stride=stride,
        track_fnv1a64=fnv1a64(track),
        metadata_fnv1a64=fnv1a64(metadata_bytes),
        frames=tuple(frames),
    )


def encode_replay(replay: OrderedReplay) -> bytes:
    if not replay.frames or len(replay.frames) > 0xFFFF:
        raise ValueError("ordered replay frame count is outside uint16")
    if not 0 < replay.source_pose_count <= 0xFFFF:
        raise ValueError("ordered replay source row count is outside uint16")
    payload = bytearray()
    records = bytearray()
    expected_poses = tuple(range(0, replay.source_pose_count, replay.stride))
    actual_poses = tuple(frame.source_pose for frame in replay.frames)
    if actual_poses != expected_poses:
        raise ValueError("ordered replay poses do not follow the configured stride")
    for frame in replay.frames:
        if not frame.source_faces or len(frame.source_faces) > 0xFFFF:
            raise ValueError("ordered packet face count is outside uint16")
        x, y, z = frame.camera.position
        if any(not -128 <= value <= 127 for value in (x, y, z, frame.camera.pitch)):
            raise ValueError("ordered packed camera is outside signed-byte range")
        if not 0 <= frame.camera.yaw <= 0xFF:
            raise ValueError("ordered packed yaw is outside uint8")
        face_offset = len(payload)
        for face in frame.source_faces:
            payload.extend(FACE_RECORD.pack(face))
        records.extend(
            FRAME_RECORD.pack(
                frame.source_pose,
                x,
                y,
                z,
                frame.camera.yaw,
                frame.camera.pitch,
                0,
                len(frame.source_faces),
                face_offset,
            )
        )
    payload_offset = HEADER.size + len(records)
    header = HEADER.pack(
        MAGIC,
        VERSION,
        HEADER.size,
        FRAME_RECORD.size,
        len(replay.frames),
        replay.source_pose_count,
        replay.stride,
        replay.source_rate_hz,
        replay.step_rate_hz,
        replay.track_fnv1a64,
        replay.metadata_fnv1a64,
        payload_offset,
    )
    return header + records + payload


def decode_replay(data: bytes) -> OrderedReplay:
    if len(data) < HEADER.size:
        raise ValueError("ordered replay is shorter than its header")
    (
        magic,
        version,
        header_bytes,
        record_bytes,
        frame_count,
        source_pose_count,
        stride,
        source_rate_hz,
        step_rate_hz,
        track_hash,
        metadata_hash,
        payload_offset,
    ) = HEADER.unpack_from(data)
    if (
        magic != MAGIC
        or version != VERSION
        or header_bytes != HEADER.size
        or record_bytes != FRAME_RECORD.size
        or not frame_count
        or not source_pose_count
        or not stride
        or not source_rate_hz
        or not step_rate_hz
        or payload_offset != HEADER.size + frame_count * FRAME_RECORD.size
        or payload_offset > len(data)
    ):
        raise ValueError("ordered replay header is invalid")
    frames: list[OrderedFrame] = []
    expected_face_offset = 0
    for ordinal in range(frame_count):
        offset = HEADER.size + ordinal * FRAME_RECORD.size
        (
            source_pose,
            x,
            y,
            z,
            yaw,
            pitch,
            reserved,
            face_count,
            face_offset,
        ) = FRAME_RECORD.unpack_from(data, offset)
        if reserved or not face_count or face_offset != expected_face_offset:
            raise ValueError("ordered replay frame directory is invalid")
        first = payload_offset + face_offset
        last = first + face_count * FACE_RECORD.size
        if last > len(data):
            raise ValueError("ordered replay packet faces escape the payload")
        source_faces = tuple(
            value for (value,) in FACE_RECORD.iter_unpack(data[first:last])
        )
        if len(set(source_faces)) != len(source_faces):
            raise ValueError("ordered replay packet contains duplicate faces")
        frames.append(
            OrderedFrame(
                source_pose=source_pose,
                camera=packet_oracle.CameraState((x, y, z), yaw, pitch),
                source_faces=source_faces,
                vertex_count=0,
                index_count=0,
            )
        )
        expected_face_offset += face_count * FACE_RECORD.size
    if payload_offset + expected_face_offset != len(data):
        raise ValueError("ordered replay has trailing or unreferenced packet bytes")
    replay = OrderedReplay(
        source_pose_count=source_pose_count,
        source_rate_hz=source_rate_hz,
        step_rate_hz=step_rate_hz,
        stride=stride,
        track_fnv1a64=track_hash,
        metadata_fnv1a64=metadata_hash,
        frames=tuple(frames),
    )
    expected_poses = tuple(range(0, source_pose_count, stride))
    if tuple(frame.source_pose for frame in frames) != expected_poses:
        raise ValueError("ordered replay source poses are not canonical")
    return replay


def outputs_for(
    replay: OrderedReplay,
    *,
    binary_path: Path = BINARY_PATH,
    report_path: Path = REPORT_PATH,
) -> dict[Path, bytes]:
    binary = encode_replay(replay)
    decoded = decode_replay(binary)
    if len(decoded.frames) != len(replay.frames):
        raise AssertionError("ordered replay round trip changed its frame count")
    face_stream = b"".join(
        FACE_RECORD.pack(face) for frame in replay.frames for face in frame.source_faces
    )
    camera_stream = b"".join(
        struct.pack(
            "<bbbBb", *frame.camera.position, frame.camera.yaw, frame.camera.pitch
        )
        for frame in replay.frames
    )
    source_pose_stream = b"".join(
        struct.pack("<H", frame.source_pose) for frame in replay.frames
    )
    capacity = capacity_report(replay)
    report: dict[str, Any] = {
        "schema": "quake-bsp-ordered-packed-replay-v1",
        "binary": {
            "path": binary_path.name,
            "bytes": len(binary),
            "sha256": sha256(binary),
            "magic": MAGIC.decode("ascii"),
            "version": VERSION,
            "headerBytes": HEADER.size,
            "frameRecordBytes": FRAME_RECORD.size,
            "faceRecordBytes": FACE_RECORD.size,
        },
        "source": {
            "preciseTrack": PRECISE_TRACK_PATH.name,
            "preciseTrackFnv1a64": f"{replay.track_fnv1a64:016x}",
            "metadata": METADATA_PATH.name,
            "metadataFnv1a64": f"{replay.metadata_fnv1a64:016x}",
        },
        "schedule": {
            "sourceRateHz": replay.source_rate_hz,
            "stepRateHz": replay.step_rate_hz,
            "stride": replay.stride,
            "sourceRows": replay.source_pose_count,
            "orderedRows": len(replay.frames),
            "firstSourcePose": replay.frames[0].source_pose,
            "lastSourcePose": replay.frames[-1].source_pose,
            "sourcePoseStreamSha256": sha256(source_pose_stream),
            "cameraStreamSha256": sha256(camera_stream),
        },
        "packets": {
            "totalFaceReferences": sum(
                len(frame.source_faces) for frame in replay.frames
            ),
            "minimumFaces": min(len(frame.source_faces) for frame in replay.frames),
            "maximumFaces": max(len(frame.source_faces) for frame in replay.frames),
            "maximumVertices": max(frame.vertex_count for frame in replay.frames),
            "maximumIndices": max(frame.index_count for frame in replay.frames),
            "sourceFaceStreamSha256": sha256(face_stream),
            "capacity": capacity,
        },
    }
    return {
        binary_path: binary,
        report_path: (json.dumps(report, indent=2, sort_keys=True) + "\n").encode(
            "ascii"
        ),
    }


def capacity_report(replay: OrderedReplay) -> dict[str, Any]:
    """Summarize runtime packet-capacity rejections across one ordered replay."""

    fields = ("face_capacity", "vertex_capacity", "index_capacity")
    labels = {name: name.removesuffix("_capacity") for name in fields}
    rows = []
    totals = {labels[name]: 0 for name in fields}
    maximums = {labels[name]: 0 for name in fields}
    for frame in replay.frames:
        values = {
            labels[name]: int(getattr(frame.rejections, name)) for name in fields
        }
        if not any(values.values()):
            continue
        rows.append({"sourcePose": frame.source_pose, **values})
        for name, value in values.items():
            totals[name] += value
            maximums[name] = max(maximums[name], value)
    return {
        "limits": {
            "faces": packet_oracle.admission.PACKET_FACE_CAPACITY,
            "vertices": packet_oracle.admission.PACKET_VERTEX_CAPACITY,
            "indices": packet_oracle.admission.PACKET_INDEX_CAPACITY,
        },
        "fits": not rows,
        "overflowPoseCount": len(rows),
        "overflowTotals": totals,
        "maximumOverflow": maximums,
        "overflowPoses": rows,
    }


def require_capacity(replay: OrderedReplay) -> None:
    """Reject an ordered replay that the runtime would silently truncate."""

    report = capacity_report(replay)
    if report["fits"]:
        return
    first = report["overflowPoses"][0]
    raise ValueError(
        "ordered packets exceed runtime capacity: "
        f"poses={report['overflowPoseCount']} first={first} "
        f"maximum={report['maximumOverflow']}"
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help="source packed assets and precise camera schedule",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--stride",
        type=int,
        default=demo_contract.ORDERED_POSE_STRIDE,
        help="source-pose stride (must divide the precise sample rate)",
    )
    parser.add_argument(
        "--include-full-rate",
        action="store_true",
        help="also emit the canonical stride-one 20 Hz replay",
    )
    parser.add_argument(
        "--allow-capacity-overflow",
        action="store_true",
        help="emit diagnostic replay evidence even when runtime packets truncate",
    )
    parser.add_argument("--check", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    started = time.perf_counter()
    args = parse_args(argv)
    try:
        replay = build_replay(args.data_dir, stride=args.stride)
        outputs = outputs_for(replay)
        full_rate_replay: OrderedReplay | None = None
        if args.include_full_rate:
            full_rate_replay = build_replay(args.data_dir, stride=1)
            outputs.update(
                outputs_for(
                    full_rate_replay,
                    binary_path=FULL_RATE_BINARY_PATH,
                    report_path=FULL_RATE_REPORT_PATH,
                )
            )
        if not args.allow_capacity_overflow:
            if full_rate_replay is not None:
                require_capacity(full_rate_replay)
            require_capacity(replay)
        sync_generated_outputs(outputs, args.output, check=args.check)
    except GeneratedOutputError as error:
        print(
            "generated ordered replay is stale: "
            f"{error} elapsed={time.perf_counter() - started:.3f}s",
            file=sys.stderr,
        )
        return 1
    except (OSError, ValueError) as error:
        print(
            f"ordered packed replay failed: {error} "
            f"elapsed={time.perf_counter() - started:.3f}s",
            file=sys.stderr,
        )
        return 1
    action = "verified" if args.check else "generated"
    report = json.loads(outputs[REPORT_PATH])
    summary = (
        f"{action} {report['schedule']['orderedRows']} ordered packed rows: "
        f"faces={report['packets']['minimumFaces']}.."
        f"{report['packets']['maximumFaces']}, bytes={report['binary']['bytes']}"
    )
    if full_rate_replay is not None:
        full_report = json.loads(outputs[FULL_RATE_REPORT_PATH])
        summary += (
            f", fullRateRows={full_report['schedule']['orderedRows']}, "
            f"fullRateBytes={full_report['binary']['bytes']}"
        )
    print(f"{summary}, elapsed={time.perf_counter() - started:.3f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
