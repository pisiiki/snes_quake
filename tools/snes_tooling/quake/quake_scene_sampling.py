"""Shared offline scene sampling on the unchanged fixed-rate camera timeline.

The last record at a timestamp owns discrete state. Continuous transforms,
including U_NOLERP/MOVETYPE_STEP entities, blend toward the next snapshot over
at most 100 ms; genuine cuts remain at their recorded timestamp. This offline
presentation policy does not emulate a live client's interpolation delay.
All consumers receive the same Q3 positions and protocol angles.
"""
from __future__ import annotations

import bisect
from dataclasses import replace
import math

from snes_tooling.quake.quake_camera_sampling import sample_camera_track
from snes_tooling.quake.quake_demo import CameraEntitySample, EntityFrame, EntityState


SCENE_SAMPLING_CONTRACT = 'quake-scene-linear-step-q3-angle8-cuts-canonical-time-v2'


def interval_reason(left: EntityFrame, right: EntityFrame, before: EntityState,
                    after: EntityState | None) -> str:
    if left.map_entry != right.map_entry or left.map_generation != right.map_generation:
        return 'map-change'
    if left.model_precache != right.model_precache:
        return 'precache-change'
    if after is None or after.model_index == 0:
        return 'removed'
    if before.entity_number != after.entity_number or before.model_index != after.model_index:
        return 'identity-change'
    # NetQuake sets U_NOLERP for MOVETYPE_STEP, not just discontinuities.
    # Smooth its recorded movement offline too; the checks below still reject
    # missing history and teleports, independently of that legacy flag.
    if (before.message_time != left.server_time or after.message_time != right.server_time
            or after.previous_message_time != left.server_time):
        return 'missing-previous-update'
    if any(abs(b-a) > 100 for a, b in zip(before.origin, after.origin)):
        return 'teleport'
    return 'eligible'


def quantize_transform(state: EntityState) -> EntityState:
    if any(not math.isfinite(v) for v in (*state.origin, *state.angles)):
        raise ValueError('scene transform must be finite')
    position = tuple(round(value*8) for value in state.origin)
    if any(not -32768 <= value <= 32767 for value in position):
        raise ValueError('scene position exceeds signed Q3 storage')
    angles = tuple(((round(value*256/360)+128) % 256-128)*360/256 for value in state.angles)
    return replace(state, origin=tuple(value/8 for value in position), angles=angles)


def interpolate_entity(before: EntityState, after: EntityState, left_time: float,
                       right_time: float, time: float) -> EntityState:
    if time >= right_time:
        return after
    if time <= left_time:
        return before
    duration = min(right_time-left_time, .1)
    fraction = max(0., min(1., (time-right_time+duration)/duration))
    angles = []
    for a, b in zip(before.angles, after.angles):
        delta = b-a
        if delta > 180:
            delta -= 360
        elif delta < -180:
            delta += 360
        angles.append(a+fraction*delta)
    return replace(before, origin=tuple(a+fraction*(b-a) for a,b in zip(before.origin, after.origin)),
                   angles=tuple(angles))


class SceneSampler:
    def __init__(self, frames):
        self.frames = tuple(frames)
        self.times = tuple(frame.server_time for frame in frames)
        if not self.times or any(not math.isfinite(t) for t in self.times) or any(
                b < a for a,b in zip(self.times, self.times[1:])):
            raise ValueError('scene frames require finite monotonic timestamps')

    def sample(self, time):
        if not math.isfinite(time):
            raise ValueError('scene sample time must be finite')
        index = max(0, bisect.bisect_right(self.times, time)-1)
        left = self.frames[index]
        next_index = bisect.bisect_right(self.times, left.server_time)
        right = None if next_index == len(self.frames) else self.frames[
            bisect.bisect_right(self.times, self.times[next_index])-1]
        after = {} if right is None else {state.entity_number:state for state in right.entities}
        states, decisions = [], []
        for state in left.entities:
            following = after.get(state.entity_number)
            reason = 'end-of-track' if right is None else interval_reason(left, right, state, following)
            raw = state if reason != 'eligible' else interpolate_entity(
                state, following, left.server_time, right.server_time, time)
            sampled = quantize_transform(raw)
            states.append(sampled)
            decisions.append(dict(entity=state.entity_number, reason=reason,
                interpolated=(raw.origin != state.origin or raw.angles != state.angles),
                positionError=max(abs(a-b) for a,b in zip(raw.origin, sampled.origin)),
                angleError=max(abs((a-b+180)%360-180) for a,b in zip(raw.angles, sampled.angles))))
        return left, tuple(states), decisions


def sample_scene_track(track, rate):
    """Keep the existing camera ABI, with entity provenance and scene time distinct."""
    cameras = sample_camera_track([sample.camera for sample in track.samples], rate)
    sampler = SceneSampler(track.entity_frames)
    camera_times = [sample.camera.server_time for sample in track.samples]
    result = []
    for camera in cameras:
        left, entities, _ = sampler.sample(camera.server_time)
        source = track.samples[bisect.bisect_right(camera_times, camera.server_time)-1]
        result.append(CameraEntitySample(camera, entities, left.model_precache or source.model_precache,
                                        source.view_entity, left.server_time, left.record))
    return tuple(result)
