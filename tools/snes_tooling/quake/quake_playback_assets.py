"""Recording-specific camera packing, separate from level geometry."""
import struct
from types import SimpleNamespace

from snes_tooling.quake.quake_bsp_assets import (
    DEMO_PRECISE_TRACK_RECORD_BYTES, DEMO_TIMING_RECORD_BYTES,
    DEMO_TRACK_RECORD_BYTES, NTSC_FRAMES_PER_SECOND,
    locate_leaf, quantize_world_vertex,
)
from snes_tooling.quake.quake_camera_sampling import sample_camera_track
from snes_tooling.quake.quake_demo import extract_camera_samples, sample_newest_due_indices


def pack_playback(demo, map_entry, world_origin, nodes, planes, root, leaves,
                  playback_sample_rate_hz, demo_ordered_pose_stride, canonical_demo):
    forced_track, demo_samples = extract_camera_samples(demo, map_entry)

    demo_records: list[tuple[int, int, int, int, int]] = []
    demo_source_records: list[int] = []
    demo_source_times: list[float] = []
    demo_view_heights: list[int] = []
    demo_leaf_ids: set[int] = set()
    for sample in demo_samples:
        coordinate = quantize_world_vertex(sample.origin, world_origin)
        leaf = locate_leaf(sample.origin, nodes, planes, root)
        if leaves[leaf].contents == -2:
            raise AssertionError(
                f"demo record {sample.record} resolves to the BSP's solid leaf"
            )
        yaw = round((sample.view_angles[1] % 360.0) * 32.0 / 360.0) & 31
        # Quake's positive pitch looks down; this renderer's positive pitch
        # rotates the view direction up.
        pitch = round(-sample.view_angles[0] * 32.0 / 360.0)
        pitch = ((pitch + 16) & 31) - 16
        record = (*coordinate, yaw, pitch)
        demo_records.append(record)
        demo_source_records.append(sample.record)
        demo_source_times.append(sample.server_time)
        demo_view_heights.append(sample.view_height)
        demo_leaf_ids.add(leaf)
    if len(demo_records) < 2:
        raise AssertionError("configured demo did not produce a changing camera track")
    demo_track = b"".join(struct.pack("<bbbBb", *record) for record in demo_records)
    if len(demo_track) != len(demo_records) * DEMO_TRACK_RECORD_BYTES:
        raise AssertionError("demo track record packing is inconsistent")
    first_demo_time = demo_source_times[0]
    demo_ticks = [
        round((server_time - first_demo_time) * NTSC_FRAMES_PER_SECOND)
        for server_time in demo_source_times
    ]
    if demo_ticks[0] != 0 or any(
        right < left for left, right in zip(demo_ticks, demo_ticks[1:])
    ):
        raise AssertionError("demo timing is not monotonic")
    if demo_ticks[-1] > 0xFFFF:
        raise AssertionError("demo timing exceeds uint16 NTSC ticks")
    demo_timing = b"".join(struct.pack("<H", tick) for tick in demo_ticks)
    if len(demo_timing) != len(demo_records) * DEMO_TIMING_RECORD_BYTES:
        raise AssertionError("demo timing record packing is inconsistent")
    if any(sample.view_angles[2] != 0.0 for sample in demo_samples):
        raise AssertionError("precise demo track cannot omit nonzero roll")

    precise_source_indices = sample_newest_due_indices(
        demo_source_times, playback_sample_rate_hz
    )
    if not precise_source_indices or min(precise_source_indices) < 0:
        raise AssertionError("precise demo stream begins before its source track")
    demo_precise_records: list[tuple[int, int, int, int, int]] = []
    for sample in sample_camera_track(demo_samples, playback_sample_rate_hz):
        position_q3 = tuple(round(value * 8.0) for value in sample.origin)
        if any(value < -0x8000 or value > 0x7FFF for value in position_q3):
            raise AssertionError(
                "precise demo Q3 position exceeds signed 16-bit storage"
            )
        yaw_u16 = round((sample.view_angles[1] % 360.0) * 65536.0 / 360.0) & 0xFFFF
        pitch_u16 = round((sample.view_angles[0] % 360.0) * 65536.0 / 360.0) & 0xFFFF
        demo_precise_records.append((*position_q3, yaw_u16, pitch_u16))
    demo_precise_track = b"".join(
        struct.pack("<hhhHH", *record) for record in demo_precise_records
    )
    if (
        len(demo_precise_track)
        != len(demo_precise_records) * DEMO_PRECISE_TRACK_RECORD_BYTES
    ):
        raise AssertionError("precise demo track record packing is inconsistent")
    demo_precise_ticks = [
        round(step * NTSC_FRAMES_PER_SECOND / playback_sample_rate_hz)
        for step in range(len(demo_precise_records))
    ]
    if demo_precise_ticks[0] != 0 or any(
        right < left for left, right in zip(demo_precise_ticks, demo_precise_ticks[1:])
    ):
        raise AssertionError("precise demo timing is not monotonic")
    if demo_precise_ticks[-1] > 0xFFFF:
        raise AssertionError("precise demo timing exceeds uint16 NTSC ticks")
    demo_precise_timing = b"".join(
        struct.pack("<H", tick) for tick in demo_precise_ticks
    )
    if len(demo_precise_timing) != len(demo_precise_records) * DEMO_TIMING_RECORD_BYTES:
        raise AssertionError("precise demo timing record packing is inconsistent")
    demo_step_indices = tuple(
        range(0, len(demo_precise_records), demo_ordered_pose_stride)
    )
    if not demo_step_indices:
        raise AssertionError("precise demo stream has no 3 Hz step poses")
    # Static verifier poses are specific to the canonical demo1; external
    # demos may have different timing and skip these checks.
    if canonical_demo:
        try:
            demo_verify_near_pose = precise_source_indices.index(20)
            demo_verify_far_pose = precise_source_indices.index(456)
        except ValueError as error:
            raise AssertionError(
                "static verifier source poses are absent from the precise stream"
            ) from error
    else:
        demo_verify_near_pose = 0
        demo_verify_far_pose = 0

    return SimpleNamespace(forced_track=forced_track, demo_samples=demo_samples, demo_records=demo_records, demo_source_records=demo_source_records, demo_source_times=demo_source_times, demo_view_heights=demo_view_heights, demo_leaf_ids=demo_leaf_ids, demo_track=demo_track, first_demo_time=first_demo_time, demo_ticks=demo_ticks, demo_timing=demo_timing, precise_source_indices=precise_source_indices, demo_precise_records=demo_precise_records, demo_precise_track=demo_precise_track, demo_precise_ticks=demo_precise_ticks, demo_precise_timing=demo_precise_timing, demo_step_indices=demo_step_indices, demo_verify_near_pose=demo_verify_near_pose, demo_verify_far_pose=demo_verify_far_pose)


def disabled_playback():
    """No recording, samples or source poses are fabricated for a level target."""
    return SimpleNamespace(
        forced_track=0,
        demo_samples=[],
        demo_records=[],
        demo_source_records=[],
        demo_source_times=[],
        demo_view_heights=[],
        demo_leaf_ids=[],
        demo_track=b"",
        first_demo_time=0,
        demo_ticks=[0],
        demo_timing=b"",
        precise_source_indices=[],
        demo_precise_records=[],
        demo_precise_track=b"",
        demo_precise_ticks=[0],
        demo_precise_timing=b"",
        demo_step_indices=[],
        demo_verify_near_pose=0,
        demo_verify_far_pose=0,
    )
