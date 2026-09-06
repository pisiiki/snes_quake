"""Deterministic Quake ordered-playback mixer and SNES BRR codec."""

from __future__ import annotations

import math
import struct
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

from quake_sound_replay import (
    SOUND_EVENT_STATIC,
    SOUND_EVENT_STOP,
    DecodedSoundReplay,
    ReplaySoundEvent,
)


PRECISE_CAMERA_RECORD = struct.Struct("<hhhHh")
ORDERED_SOUND_RATE_HZ = 2
DEFAULT_OUTPUT_RATE_HZ = 8000
DEFAULT_VOLUME = 0.7
BRR_BLOCK_SAMPLES = 16
BRR_BLOCK_BYTES = 9
BRR_INITIAL_SILENCE_BLOCKS = 1
BRR_END = 0x01
BRR_PCM_HEADROOM = 0.875


@dataclass(frozen=True)
class QuakeWave:
    sample_rate_hz: int
    samples: tuple[float, ...]
    loop_start: int | None


@dataclass(frozen=True)
class Listener:
    origin: tuple[float, float, float]
    right: tuple[float, float, float]


@dataclass
class MixChannel:
    active: bool = False
    sound_slot: int = 0
    entity: int = 0
    channel: int = 0
    volume: int = 0
    attenuation: int = 0
    origin: tuple[float, float, float] = (0.0, 0.0, 0.0)
    sample_position: float = 0.0


@dataclass(frozen=True)
class MixResult:
    intervals: tuple[tuple[tuple[int, ...], tuple[int, ...]], ...]
    processed_events: int
    ignored_static_sounds: int
    peak_left: int
    peak_right: int


@dataclass(frozen=True)
class EncodedInterval:
    payload: bytes
    left_bytes: int
    right_bytes: int
    squared_error: int
    peak_error: int


def _u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def parse_quake_wave(data: bytes, name: str = "wave") -> QuakeWave:
    """Decode the PCM payload and Quake cue-point loop from one WAV."""

    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError(f"Quake sound is not RIFF/WAVE: {name}")
    riff_bytes = _u32(data, 4)
    if riff_bytes < 4 or riff_bytes > len(data) - 8:
        raise ValueError(f"Quake WAV RIFF bounds are invalid: {name}")
    riff_end = 8 + riff_bytes
    fmt: bytes | None = None
    pcm: bytes | None = None
    loop_start: int | None = None
    cursor = 12
    while cursor + 8 <= riff_end:
        chunk_bytes = _u32(data, cursor + 4)
        payload = cursor + 8
        if payload > riff_end or chunk_bytes > riff_end - payload:
            if fmt is not None and pcm is not None:
                break
            raise ValueError(f"Quake WAV chunk escapes RIFF: {name}")
        chunk = data[cursor : cursor + 4]
        if chunk == b"fmt ":
            fmt = data[payload : payload + chunk_bytes]
        elif chunk == b"data":
            pcm = data[payload : payload + chunk_bytes]
        elif chunk == b"cue " and chunk_bytes >= 28 and _u32(data, payload):
            loop_start = _u32(data, payload + 24)
        cursor = payload + chunk_bytes + (chunk_bytes & 1)
    if fmt is None or len(fmt) < 16 or pcm is None:
        raise ValueError(f"Quake WAV lacks PCM format or data: {name}")
    encoding, channels, sample_rate = struct.unpack_from("<HHI", fmt)
    bits = _u16(fmt, 14)
    if (
        encoding != 1
        or channels != 1
        or sample_rate == 0
        or sample_rate > 192000
        or bits not in (8, 16)
        or len(pcm) % (bits // 8)
    ):
        raise ValueError(f"Quake WAV has unsupported PCM parameters: {name}")
    if bits == 8:
        samples = tuple((value - 128) / 128.0 for value in pcm)
    else:
        samples = tuple(
            struct.unpack_from("<h", pcm, offset)[0] / 32768.0
            for offset in range(0, len(pcm), 2)
        )
    if not samples:
        raise ValueError(f"Quake WAV contains no samples: {name}")
    if loop_start is not None and loop_start >= len(samples):
        raise ValueError(f"Quake WAV loop point escapes samples: {name}")
    return QuakeWave(sample_rate, samples, loop_start)


def decode_precise_listeners(data: bytes) -> tuple[Listener, ...]:
    if not data or len(data) % PRECISE_CAMERA_RECORD.size:
        raise ValueError("precise camera track is not ten-byte record aligned")
    listeners = []
    for offset in range(0, len(data), PRECISE_CAMERA_RECORD.size):
        x, y, z, yaw, _pitch = PRECISE_CAMERA_RECORD.unpack_from(data, offset)
        radians = yaw * math.tau / 65536.0
        listeners.append(
            Listener(
                (x / 8.0, y / 8.0, z / 8.0),
                (math.sin(radians), -math.cos(radians), 0.0),
            )
        )
    return tuple(listeners)


def _dot(left: tuple[float, float, float], right: tuple[float, float, float]) -> float:
    return left[0] * right[0] + left[1] * right[1] + left[2] * right[2]


def _sub(
    left: tuple[float, float, float], right: tuple[float, float, float]
) -> tuple[float, float, float]:
    return left[0] - right[0], left[1] - right[1], left[2] - right[2]


class OrderedSoundMixer:
    """Match the reference mix using the ordered 2 Hz listener schedule."""

    def __init__(
        self,
        replay: DecodedSoundReplay,
        waves: Sequence[QuakeWave],
        listeners: Sequence[Listener],
        *,
        output_rate_hz: int = DEFAULT_OUTPUT_RATE_HZ,
        volume: float = DEFAULT_VOLUME,
    ) -> None:
        if len(waves) != len(replay.sound_names):
            raise ValueError("sound waveform count disagrees with QSR1")
        if len(listeners) != replay.camera_row_count:
            raise ValueError("listener count disagrees with QSR1")
        if output_rate_hz <= 0 or replay.sample_rate_hz % ORDERED_SOUND_RATE_HZ:
            raise ValueError("invalid ordered soundtrack rate")
        if not math.isfinite(volume) or not 0.0 <= volume <= 1.0:
            raise ValueError("soundtrack volume must be from 0.0 to 1.0")
        self.replay = replay
        self.waves = tuple(waves)
        self.listeners = tuple(listeners)
        self.output_rate_hz = output_rate_hz
        self.volume = volume
        self.dynamic = [MixChannel() for _ in range(8)]
        self.statics: list[MixChannel] = []
        self.next_event = 0
        self.timeline_seconds = min(
            0.0,
            replay.events[0].due_q16 / 65536.0 if replay.events else 0.0,
        )
        self.processed_events = 0
        self.ignored_static_sounds = 0

    @staticmethod
    def _normalize(channel: MixChannel, wave: QuakeWave) -> None:
        if channel.sample_position < len(wave.samples):
            return
        if wave.loop_start is None:
            channel.active = False
            return
        length = len(wave.samples) - wave.loop_start
        channel.sample_position = wave.loop_start + math.fmod(
            channel.sample_position - wave.loop_start, length
        )

    def _advance_channel(self, channel: MixChannel, seconds: float) -> None:
        if channel.active and seconds > 0.0:
            wave = self.waves[channel.sound_slot]
            channel.sample_position += seconds * wave.sample_rate_hz
            self._normalize(channel, wave)

    def _advance_channels(self, seconds: float) -> None:
        for channel in (*self.dynamic, *self.statics):
            self._advance_channel(channel, seconds)

    def _remaining(self, channel: MixChannel) -> float:
        if not channel.active:
            return 0.0
        wave = self.waves[channel.sound_slot]
        return (len(wave.samples) - channel.sample_position) / wave.sample_rate_hz

    def _pick_dynamic(self, entity: int, channel_number: int) -> MixChannel:
        if channel_number:
            for candidate in self.dynamic:
                if (
                    candidate.active
                    and candidate.entity == entity
                    and candidate.channel == channel_number
                ):
                    return candidate
        selected: MixChannel | None = None
        least_life = math.inf
        for candidate in self.dynamic:
            if (
                candidate.active
                and candidate.entity == self.replay.view_entity
                and entity != self.replay.view_entity
            ):
                continue
            life = self._remaining(candidate)
            if life < least_life:
                least_life = life
                selected = candidate
        if selected is None:
            raise AssertionError("dynamic sound channel selection failed")
        return selected

    def _apply(self, event: ReplaySoundEvent) -> None:
        self.processed_events += 1
        if event.kind == SOUND_EVENT_STOP:
            for channel in self.dynamic:
                if (
                    channel.active
                    and channel.entity == event.entity
                    and channel.channel == event.channel
                ):
                    channel.active = False
                    break
            return
        if event.kind == SOUND_EVENT_STATIC:
            if self.waves[event.sound_slot].loop_start is None:
                self.ignored_static_sounds += 1
                return
            self.statics.append(
                MixChannel(
                    True,
                    event.sound_slot,
                    0,
                    0,
                    event.volume,
                    event.attenuation,
                    event.origin,
                )
            )
            return
        selected = self._pick_dynamic(event.entity, event.channel)
        selected.active = True
        selected.sound_slot = event.sound_slot
        selected.entity = event.entity
        selected.channel = event.channel
        selected.volume = event.volume
        selected.attenuation = event.attenuation
        selected.origin = event.origin
        selected.sample_position = 0.0

    def _seek_zero(self) -> None:
        while self.next_event < len(self.replay.events):
            event = self.replay.events[self.next_event]
            due = event.due_q16 / 65536.0
            if due > 0.0:
                break
            self._advance_channels(due - self.timeline_seconds)
            self.timeline_seconds = due
            self._apply(event)
            self.next_event += 1
        self._advance_channels(-self.timeline_seconds)
        self.timeline_seconds = 0.0

    def _spatial_volume(
        self, channel: MixChannel, listener: Listener
    ) -> tuple[float, float]:
        master = channel.volume / 255.0
        if channel.entity == self.replay.view_entity:
            return master, master
        delta = _sub(channel.origin, listener.origin)
        distance = math.sqrt(_dot(delta, delta))
        direction = (
            tuple(component / distance for component in delta)
            if distance > 0.0
            else (0.0, 0.0, 0.0)
        )
        pan = _dot(listener.right, direction)  # type: ignore[arg-type]
        attenuation = distance * channel.attenuation / 64000.0
        distance_gain = 1.0 - attenuation
        return (
            master * max(0.0, (1.0 - pan) * distance_gain),
            master * max(0.0, (1.0 + pan) * distance_gain),
        )

    def _mix_channel(self, channel: MixChannel) -> float:
        if not channel.active:
            return 0.0
        wave = self.waves[channel.sound_slot]
        self._normalize(channel, wave)
        if not channel.active:
            return 0.0
        first = int(channel.sample_position)
        second = first + 1
        if second >= len(wave.samples):
            second = wave.loop_start if wave.loop_start is not None else first
        fraction = channel.sample_position - first
        sample = (
            wave.samples[first]
            + (wave.samples[second] - wave.samples[first]) * fraction
        )
        channel.sample_position += wave.sample_rate_hz / self.output_rate_hz
        self._normalize(channel, wave)
        return sample

    def mix(self) -> MixResult:
        self._seek_zero()
        stride = self.replay.sample_rate_hz // ORDERED_SOUND_RATE_HZ
        interval_frames = self.output_rate_hz // ORDERED_SOUND_RATE_HZ
        if self.output_rate_hz % ORDERED_SOUND_RATE_HZ:
            raise ValueError("output rate must divide into half-second intervals")
        interval_count = (self.replay.camera_row_count + stride - 1) // stride
        duration_frames = round(
            self.replay.camera_row_count
            * self.output_rate_hz
            / self.replay.sample_rate_hz
        )
        intervals: list[tuple[tuple[int, ...], tuple[int, ...]]] = []
        peak_left = 0
        peak_right = 0
        global_frame = 0
        for interval in range(interval_count):
            listener = self.listeners[min(interval * stride, len(self.listeners) - 1)]
            dynamic_gains = [
                self._spatial_volume(channel, listener) for channel in self.dynamic
            ]
            static_gains = [
                self._spatial_volume(channel, listener) for channel in self.statics
            ]
            left: list[int] = []
            right: list[int] = []
            for _ in range(interval_frames):
                if global_frame >= duration_frames:
                    left.append(0)
                    right.append(0)
                    global_frame += 1
                    continue
                threshold = (2 * global_frame + 1) * 65536
                changed = False
                while self.next_event < len(self.replay.events):
                    event = self.replay.events[self.next_event]
                    if 2 * event.due_q16 * self.output_rate_hz > threshold:
                        break
                    self._apply(event)
                    self.next_event += 1
                    changed = True
                if changed:
                    dynamic_gains = [
                        self._spatial_volume(channel, listener)
                        for channel in self.dynamic
                    ]
                    static_gains = [
                        self._spatial_volume(channel, listener)
                        for channel in self.statics
                    ]
                mixed_left = 0.0
                mixed_right = 0.0
                for channel, gains in zip(self.dynamic, dynamic_gains, strict=True):
                    if not channel.active:
                        continue
                    sample = self._mix_channel(channel)
                    mixed_left += sample * gains[0]
                    mixed_right += sample * gains[1]
                for channel, gains in zip(self.statics, static_gains, strict=True):
                    if not channel.active:
                        continue
                    sample = self._mix_channel(channel)
                    mixed_left += sample * gains[0]
                    mixed_right += sample * gains[1]
                pcm_left = round(
                    max(-1.0, min(1.0, mixed_left * self.volume))
                    * BRR_PCM_HEADROOM
                    * 32767
                )
                pcm_right = round(
                    max(-1.0, min(1.0, mixed_right * self.volume))
                    * BRR_PCM_HEADROOM
                    * 32767
                )
                left.append(pcm_left)
                right.append(pcm_right)
                peak_left = max(peak_left, abs(pcm_left))
                peak_right = max(peak_right, abs(pcm_right))
                global_frame += 1
                self.timeline_seconds += 1.0 / self.output_rate_hz
            intervals.append((tuple(left), tuple(right)))
        return MixResult(
            tuple(intervals),
            self.processed_events,
            self.ignored_static_sounds,
            peak_left,
            peak_right,
        )


def _as_i16(value: int) -> int:
    return ((value + 0x8000) & 0xFFFF) - 0x8000


def _prediction(filter_number: int, first: int, second: int) -> int:
    first = _as_i16(first)
    second = _as_i16(second)
    if filter_number == 0:
        return 0
    if filter_number == 1:
        return first - (first >> 4)
    if filter_number == 2:
        return (first << 1) + (-(first + (first << 1)) >> 5) - second + (second >> 4)
    if filter_number == 3:
        return (
            (first << 1)
            + (-(first + (first << 2) + (first << 3)) >> 6)
            - second
            + ((second + (second << 1)) >> 4)
        )
    raise ValueError("invalid BRR filter")


def _clamp_encoder(value: int) -> int:
    narrowed = _as_i16(value)
    if narrowed == value:
        return value
    return _as_i16(0x7FFF - (value >> 24))


def _encode_candidate(
    pcm: Sequence[int], shift: int, filter_number: int, first: int, second: int
) -> tuple[int, bytes, int, int]:
    step = 1 << shift
    nibbles: list[int] = []
    squared_error = 0
    previous = first
    before_previous = second
    for sample in pcm:
        predicted = _prediction(filter_number, previous, before_previous) >> 1
        delta = (sample >> 1) - predicted
        adjusted = delta + (step << 2) + (step >> 2)
        quantized = 0
        if adjusted > 0:
            quantized = adjusted // (step // 2) if step > 1 else adjusted * 2
            quantized = min(15, quantized)
        quantized -= 8
        decoded_delta = (quantized << shift) >> 1
        nibble = quantized & 0x0F
        before_previous = previous
        previous = _clamp_encoder(predicted + decoded_delta) * 2
        error = sample - previous
        squared_error += error * error
        nibbles.append(nibble)
    packed = bytes(
        (nibbles[index] << 4) | nibbles[index + 1]
        for index in range(0, BRR_BLOCK_SAMPLES, 2)
    )
    return squared_error, packed, _as_i16(previous), _as_i16(before_previous)


def encode_brr(
    pcm: Sequence[int],
    *,
    initial_silence: bool = True,
    first_filter_zero: bool = False,
) -> bytes:
    if not pcm or len(pcm) % BRR_BLOCK_SAMPLES:
        raise ValueError("BRR PCM must contain a non-empty whole number of blocks")
    if any(not -32768 <= sample <= 32767 for sample in pcm):
        raise ValueError("BRR PCM sample exceeds signed 16-bit range")
    output = bytearray()
    first = 0
    second = 0
    if initial_silence:
        output.extend(bytes(BRR_BLOCK_BYTES))
    block_count = len(pcm) // BRR_BLOCK_SAMPLES
    for block_index in range(block_count):
        block = pcm[
            block_index * BRR_BLOCK_SAMPLES : (block_index + 1) * BRR_BLOCK_SAMPLES
        ]
        best: tuple[int, int, int, bytes, int, int] | None = None
        for shift in range(13):
            filter_numbers = (
                (0,) if first_filter_zero and block_index == 0 else range(4)
            )
            for filter_number in filter_numbers:
                error, packed, next_first, next_second = _encode_candidate(
                    block, shift, filter_number, first, second
                )
                candidate = (
                    error,
                    shift,
                    filter_number,
                    packed,
                    next_first,
                    next_second,
                )
                if best is None or candidate[:3] < best[:3]:
                    best = candidate
        assert best is not None
        error, shift, filter_number, packed, first, second = best
        del error
        header = (shift << 4) | (filter_number << 2)
        if block_index + 1 == block_count:
            header |= BRR_END
        output.append(header)
        output.extend(packed)
    return bytes(output)


def decode_brr(payload: bytes) -> tuple[int, ...]:
    if not payload or len(payload) % BRR_BLOCK_BYTES:
        raise ValueError("BRR payload is not block aligned")
    output: list[int] = []
    first = 0
    second = 0
    for offset in range(0, len(payload), BRR_BLOCK_BYTES):
        header = payload[offset]
        shift = header >> 4
        filter_number = (header >> 2) & 3
        for encoded in payload[offset + 1 : offset + BRR_BLOCK_BYTES]:
            for nibble in (encoded >> 4, encoded & 0x0F):
                if shift <= 12:
                    sample = ((nibble if nibble < 8 else nibble - 16) << shift) >> 1
                else:
                    sample = 2048 if nibble < 8 else -2048
                sample += _prediction(filter_number, first, second)
                sample = max(-32768, min(32767, sample))
                if sample > 0x3FFF:
                    sample -= 0x8000
                elif sample < -0x4000:
                    sample += 0x8000
                second = first
                first = sample
                output.append(first * 2)
    return tuple(output)


def _encode_interval(
    interval: tuple[tuple[int, ...], tuple[int, ...]],
) -> EncodedInterval:
    left_pcm, right_pcm = interval
    left = encode_brr(left_pcm)
    right = encode_brr(right_pcm)
    squared_error = 0
    peak_error = 0
    for source, encoded in ((left_pcm, left), (right_pcm, right)):
        decoded = decode_brr(encoded)[BRR_BLOCK_SAMPLES:]
        for expected, actual in zip(source, decoded, strict=True):
            error = expected - actual
            squared_error += error * error
            peak_error = max(peak_error, abs(error))
    return EncodedInterval(
        left + right, len(left), len(right), squared_error, peak_error
    )


def encode_intervals(
    intervals: Sequence[tuple[tuple[int, ...], tuple[int, ...]]],
    *,
    workers: int,
) -> tuple[EncodedInterval, ...]:
    if workers <= 0:
        raise ValueError("BRR worker count must be positive")
    if workers == 1 or len(intervals) <= 1:
        return tuple(_encode_interval(interval) for interval in intervals)
    with ProcessPoolExecutor(max_workers=min(workers, len(intervals))) as executor:
        return tuple(executor.map(_encode_interval, intervals, chunksize=1))


def load_waves(
    replay: DecodedSoundReplay, reader: Callable[[str], bytes]
) -> tuple[QuakeWave, ...]:
    return tuple(
        parse_quake_wave(reader("sound/" + name), name) for name in replay.sound_names
    )


def soundtrack_bank_payloads(
    intervals: Sequence[EncodedInterval], *, intervals_per_bank: int
) -> tuple[bytes, ...]:
    if intervals_per_bank <= 0:
        raise ValueError("soundtrack intervals-per-bank must be positive")
    return tuple(
        b"".join(
            interval.payload
            for interval in intervals[offset : offset + intervals_per_bank]
        )
        for offset in range(0, len(intervals), intervals_per_bank)
    )


def fnv1a64(data: Iterable[int]) -> int:
    value = 0xCBF29CE484222325
    for byte in data:
        value ^= byte
        value = value * 0x100000001B3 & 0xFFFFFFFFFFFFFFFF
    return value
