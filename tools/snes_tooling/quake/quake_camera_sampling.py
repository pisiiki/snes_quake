"""Bake fixed-rate demo cameras; playback consumes poses without interpolation.

Quake's CL_LerpPoint/CL_RelinkEntities define the linear position and wrapped
Euler-angle blend. This is a fixed server-time resampling contract, not a replay
of Quake's mutable client clock or V_CalcRefdef (bob, roll, punch, stair easing).
Entity sampling is owned separately by quake_scene_sampling.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
import bisect
import math

from snes_tooling.quake.quake_demo import CameraSample, sample_newest_due_indices


CAMERA_SAMPLING_CONTRACT = (
    "offline Quake linear camera at n/sampleRateHz; shortest Euler angles; "
    "100ms interval cap; no runtime interpolation"
)


def interpolate_camera(left: CameraSample, right: CameraSample, time: float) -> CameraSample:
    """Blend one camera interval, preserving recorded endpoints and cuts.

    Equal timestamps select the last record. Never extrapolate or blend across
    a map/view-entity change, U_NOLERP, or a >100-unit player-origin jump. Such
    cuts hold the old pose until the new timestamp, avoiding early teleports.
    View height is discrete client state, not player movement to interpolate.
    """
    if time >= right.server_time:
        return replace(right, server_time=time)
    if time <= left.server_time:
        return replace(left, server_time=time)
    old = (*left.origin[:2], left.origin[2] - left.view_height)
    new = (*right.origin[:2], right.origin[2] - right.view_height)
    cut = (left.map_entry != right.map_entry or left.view_entity != right.view_entity
           or right.no_lerp or any(abs(b - a) > 100.0 for a, b in zip(old, new)))
    if cut:
        return replace(left, server_time=time)
    interval = min(right.server_time - left.server_time, 0.1)
    fraction = max(0.0, min(1.0, (time - (right.server_time - interval)) / interval))
    position = tuple(a + fraction * (b - a) for a, b in zip(old, new))
    angles = []
    for a, b in zip(left.view_angles, right.view_angles):
        delta = b - a
        # Keep Quake's sign for an exactly 180-degree rotation.
        if delta > 180.0:
            delta -= 360.0
        elif delta < -180.0:
            delta += 360.0
        angles.append(a + fraction * delta)
    return replace(left, server_time=time,
                   origin=(*position[:2], position[2] + left.view_height),
                   view_angles=tuple(angles))


def sample_camera_track(source: Sequence[CameraSample], rate: int) -> tuple[CameraSample, ...]:
    """Bake n/rate seconds, on the existing endpoint-exclusive demo clock."""
    times = [sample.server_time for sample in source]
    if any(not math.isfinite(value) for value in times):
        raise ValueError("camera timestamps must be finite")
    due = sample_newest_due_indices(times, rate)
    result = []
    for step, index in enumerate(due):
        time = times[0] + step / rate
        following = bisect.bisect_right(times, times[index])
        if following == len(source):
            result.append(replace(source[index], server_time=time))
            continue
        # Last record at each timestamp owns that snapshot; no zero-length lerp.
        following = bisect.bisect_right(times, times[following]) - 1
        result.append(interpolate_camera(source[index], source[following], time))
    return tuple(result)
