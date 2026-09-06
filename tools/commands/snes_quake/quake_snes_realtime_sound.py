"""Deterministic 8 kHz BRR sources and an eight-voice Quake mix schedule."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from fractions import Fraction
from typing import Sequence

from quake_snes_soundtrack import (
    BRR_BLOCK_BYTES,
    BRR_BLOCK_SAMPLES,
    BRR_END,
    BRR_PCM_HEADROOM,
    Listener,
    QuakeWave,
    encode_brr,
)
from quake_sound_replay import (
    SOUND_EVENT_START,
    SOUND_EVENT_STATIC,
    SOUND_EVENT_STOP,
    DecodedSoundReplay,
    ReplaySoundEvent,
)


OUTPUT_RATE_HZ = 8000
NTSC_FRAMES_PER_SECOND = 60.0988138974405
DSP_OUTPUT_RATE_HZ = 32000
DSP_PITCH = round(OUTPUT_RATE_HZ * 4096 / DSP_OUTPUT_RATE_HZ)
VOICE_COUNT = 8
STREAM_BUFFER_COUNT = 4
CHUNK_BLOCKS = 64
CHUNK_SAMPLES = CHUNK_BLOCKS * BRR_BLOCK_SAMPLES
CHUNK_BYTES = CHUNK_BLOCKS * BRR_BLOCK_BYTES
CHUNK_TRANSFER_PACKETS = CHUNK_BYTES // 3
CACHE_CHUNK_CAPACITY = 77
SAMPLE_FLAG_LOOP = 0x01
UPLOAD_FLAG_TERMINAL = 0x01
MIX_COMMAND_START = 1
MIX_COMMAND_STOP = 2
MIX_COMMAND_VOLUME = 3
MIX_COMMAND_COMPLETE = 4


@dataclass(frozen=True)
class EncodedSound:
    slot: int
    chunks: tuple[bytes, ...]
    source_samples: int
    encoded_samples: int
    loop_start: int | None
    initial_chunk_count: int
    loop_chunk: int | None
    squared_error: int
    peak_error: int

    @property
    def payload_bytes(self) -> int:
        return len(self.chunks) * CHUNK_BYTES


@dataclass(frozen=True)
class MixCommand:
    due_tick: int
    opcode: int
    voice: int
    sound_slot: int
    left: int
    right: int


@dataclass(frozen=True)
class MixSchedule:
    commands: tuple[MixCommand, ...]
    duration_ticks: int
    processed_events: int
    source_starts: int
    source_statics: int
    source_stops: int
    inaudible_events: int
    hardware_starts: int
    hardware_stops: int
    hardware_steals: int
    static_restarts: int
    volume_updates: int
    peak_active_voices: int


@dataclass
class _Voice:
    active: bool = False
    static: bool = False
    sound_slot: int = 0
    entity: int = 0
    channel: int = 0
    origin: tuple[float, float, float] = (0.0, 0.0, 0.0)
    volume: int = 0
    attenuation: int = 0
    end_tick: int | None = None
    left: int = 0
    right: int = 0
    generation: int = 0


def _rounded_pcm_block(
    samples: Sequence[int], *, loop_extension: Sequence[int] = ()
) -> tuple[int, ...]:
    if not samples:
        return (0,) * BRR_BLOCK_SAMPLES
    remainder = len(samples) % BRR_BLOCK_SAMPLES
    if not remainder:
        return tuple(samples)
    needed = BRR_BLOCK_SAMPLES - remainder
    if loop_extension:
        raise ValueError(
            "looping PCM must end on a complete BRR block instead of replaying "
            "loop-head padding"
        )
    extension = (0,) * needed
    return tuple(samples) + extension


def _block_aligned_sample_count(
    source_count: int, source_rate_hz: int, output_rate_hz: int
) -> int:
    if source_count == 0:
        return 0
    numerator = source_count * output_rate_hz
    denominator = source_rate_hz * BRR_BLOCK_SAMPLES
    block_count = max(1, (numerator * 2 + denominator) // (denominator * 2))
    return block_count * BRR_BLOCK_SAMPLES


def resample_wave_pcm(
    wave: QuakeWave,
    *,
    output_rate_hz: int = OUTPUT_RATE_HZ,
) -> tuple[int, ...]:
    """Linearly resample one mono Quake wave with deterministic Q15 output."""

    if output_rate_hz <= 0:
        raise ValueError("output sample rate must be positive")
    if not wave.samples:
        raise ValueError("cannot resample an empty Quake wave")

    def resample_segment(
        samples: Sequence[float], output_samples: int, *, exact_rate: bool
    ) -> tuple[int, ...]:
        result: list[int] = []
        for index in range(output_samples):
            position = (
                index * wave.sample_rate_hz / output_rate_hz
                if exact_rate
                else index * len(samples) / output_samples
            )
            first = min(int(position), len(samples) - 1)
            second = min(first + 1, len(samples) - 1)
            fraction = position - first
            value = samples[first] + (samples[second] - samples[first]) * fraction
            result.append(round(max(-1.0, min(1.0, value)) * BRR_PCM_HEADROOM * 32767))
        return tuple(result)

    if wave.loop_start is not None:
        before_loop = wave.samples[: wave.loop_start]
        loop = wave.samples[wave.loop_start :]
        return resample_segment(
            before_loop,
            _block_aligned_sample_count(
                len(before_loop), wave.sample_rate_hz, output_rate_hz
            ),
            exact_rate=False,
        ) + resample_segment(
            loop,
            _block_aligned_sample_count(len(loop), wave.sample_rate_hz, output_rate_hz),
            exact_rate=False,
        )

    output_samples = max(
        1, round(len(wave.samples) * output_rate_hz / wave.sample_rate_hz)
    )
    return resample_segment(wave.samples, output_samples, exact_rate=True)


def _encode_pcm_chunks(
    pcm: Sequence[int], *, loop_extension: Sequence[int] = ()
) -> tuple[tuple[bytes, ...], int, int, int]:
    encoded_chunks: list[bytes] = []
    squared_error = 0
    peak_error = 0
    for offset in range(0, len(pcm), CHUNK_SAMPLES):
        source = pcm[offset : offset + CHUNK_SAMPLES]
        block_pcm = _rounded_pcm_block(
            source,
            loop_extension=(
                loop_extension if offset + CHUNK_SAMPLES >= len(pcm) else ()
            ),
        )
        encoded = bytearray(
            encode_brr(
                block_pcm,
                initial_silence=False,
                first_filter_zero=True,
            )
        )
        final_chunk = offset + CHUNK_SAMPLES >= len(pcm)
        last_header = len(encoded) - BRR_BLOCK_BYTES
        if not final_chunk or loop_extension:
            encoded[last_header] |= BRR_END | 0x02
        else:
            encoded[last_header] |= BRR_END
        decoded = _decode_chunk(bytes(encoded))
        for expected, actual in zip(block_pcm, decoded, strict=True):
            error = expected - actual
            squared_error += error * error
            peak_error = max(peak_error, abs(error))
        encoded.extend(bytes(CHUNK_BYTES - len(encoded)))
        encoded_chunks.append(bytes(encoded))
    return (
        tuple(encoded_chunks),
        sum(
            min(CHUNK_SAMPLES, max(0, len(pcm) - index * CHUNK_SAMPLES))
            for index in range(len(encoded_chunks))
        ),
        squared_error,
        peak_error,
    )


def encode_sound(slot: int, wave: QuakeWave) -> EncodedSound:
    """Encode independently restartable fixed-size BRR stream chunks."""

    pcm = resample_wave_pcm(wave)
    loop_start = None
    if wave.loop_start is not None:
        loop_start = _block_aligned_sample_count(
            wave.loop_start,
            wave.sample_rate_hz,
            OUTPUT_RATE_HZ,
        )
        if not 0 <= loop_start < len(pcm):
            raise ValueError("resampled Quake loop point escapes its waveform")
    loop_pcm = pcm[loop_start:] if loop_start is not None else ()
    initial, initial_samples, initial_squared, initial_peak = _encode_pcm_chunks(
        pcm,
        loop_extension=loop_pcm,
    )
    loop_chunk = None
    loop_chunks: tuple[bytes, ...] = ()
    loop_samples = loop_squared = loop_peak = 0
    if loop_start not in (None, 0):
        loop_chunk = len(initial)
        loop_chunks, loop_samples, loop_squared, loop_peak = _encode_pcm_chunks(
            loop_pcm,
            loop_extension=loop_pcm,
        )
    elif loop_start == 0:
        loop_chunk = 0
    encoded_chunks = initial + loop_chunks
    if not encoded_chunks:
        raise AssertionError("encoded sound unexpectedly has no chunks")
    return EncodedSound(
        slot,
        encoded_chunks,
        len(pcm),
        initial_samples + loop_samples,
        loop_start,
        len(initial),
        loop_chunk,
        initial_squared + loop_squared,
        max(initial_peak, loop_peak),
    )


def _decode_chunk(payload: bytes) -> tuple[int, ...]:
    from quake_snes_soundtrack import decode_brr

    return decode_brr(payload)


def select_cached_sounds(
    encoded: Sequence[EncodedSound],
    schedule: MixSchedule,
    *,
    chunk_capacity: int = CACHE_CHUNK_CAPACITY,
) -> tuple[int, ...]:
    """Select complete samples by replay concurrency and resident efficiency."""

    if chunk_capacity < 0:
        raise ValueError("cache chunk capacity must be non-negative")
    commands_at: dict[int, list[MixCommand]] = {}
    for command in schedule.commands:
        commands_at.setdefault(command.due_tick, []).append(command)
    active: list[int | None] = [None] * VOICE_COUNT
    active_ticks: Counter[int] = Counter()
    deadline_ticks: Counter[int] = Counter()
    starts: Counter[int] = Counter()
    peak_concurrency: Counter[int] = Counter()
    for tick in range(schedule.duration_ticks + 1):
        for command in commands_at.get(tick, ()):
            if command.opcode == MIX_COMMAND_START:
                active[command.voice] = command.sound_slot
                starts[command.sound_slot] += 1
            elif command.opcode == MIX_COMMAND_STOP:
                active[command.voice] = None
            elif command.opcode == MIX_COMMAND_COMPLETE:
                active = [None] * VOICE_COUNT
        active_counts = Counter(slot for slot in active if slot is not None)
        active_ticks.update(active_counts)
        active_count = sum(active_counts.values())
        deadline_ticks.update(
            {
                slot: count * active_count * active_count
                for slot, count in active_counts.items()
            }
        )
        for slot, count in active_counts.items():
            peak_concurrency[slot] = max(peak_concurrency[slot], count)

    # Solve the complete-sample cache as a small deterministic 0/1 knapsack.
    # Each active tick consumes 125/960 of a 1024-sample chunk; weight it by the
    # square of whole-mix concurrency so the cache reduces the replay's burst
    # bandwidth instead of only its aggregate traffic. Every start also preloads
    # the remaining ring lookahead. A sample used by three or more simultaneous
    # voices receives a dominant bonus because one shared ARAM copy avoids a
    # synchronized refill burst.
    candidates = tuple(sound for sound in encoded if active_ticks[sound.slot])
    base_benefits = {
        sound.slot: Fraction(deadline_ticks[sound.slot] * 125, 960)
        + starts[sound.slot] * min(len(sound.chunks) - 1, STREAM_BUFFER_COUNT - 1)
        for sound in candidates
    }
    deadline_bonus = sum(base_benefits.values(), start=Fraction(1))
    states: list[tuple[Fraction, tuple[int, ...]] | None] = [None] * (
        chunk_capacity + 1
    )
    states[0] = (Fraction(0), ())
    for sound in candidates:
        chunks = len(sound.chunks)
        benefit = base_benefits[sound.slot] + deadline_bonus * max(
            peak_concurrency[sound.slot] - 2, 0
        )
        for used in range(chunk_capacity, chunks - 1, -1):
            previous = states[used - chunks]
            if previous is None:
                continue
            candidate = (previous[0] + benefit, previous[1] + (sound.slot,))
            current = states[used]
            if (
                current is None
                or candidate[0] > current[0]
                or (candidate[0] == current[0] and candidate[1] < current[1])
            ):
                states[used] = candidate
    best_used = 0
    best = states[0]
    assert best is not None
    for used, candidate in enumerate(states[1:], start=1):
        if candidate is None:
            continue
        if candidate[0] > best[0] or (
            candidate[0] == best[0]
            and (used < best_used or (used == best_used and candidate[1] < best[1]))
        ):
            best_used = used
            best = candidate
    return best[1]


def _dot(left: tuple[float, float, float], right: tuple[float, float, float]) -> float:
    return left[0] * right[0] + left[1] * right[1] + left[2] * right[2]


def _spatial_gain(
    *,
    entity: int,
    view_entity: int,
    volume: int,
    attenuation: int,
    origin: tuple[float, float, float],
    listener: Listener,
) -> tuple[float, float]:
    master = volume / 255.0
    if entity == view_entity:
        return master, master
    delta = tuple(origin[index] - listener.origin[index] for index in range(3))
    distance = math.sqrt(_dot(delta, delta))
    direction = (
        tuple(component / distance for component in delta)
        if distance > 0.0
        else (0.0, 0.0, 0.0)
    )
    pan = _dot(listener.right, direction)  # type: ignore[arg-type]
    distance_gain = 1.0 - distance * attenuation / 64000.0
    return (
        master * max(0.0, (1.0 - pan) * distance_gain),
        master * max(0.0, (1.0 + pan) * distance_gain),
    )


def _dsp_volumes(left: float, right: float, volume: float) -> tuple[int, int]:
    return (
        round(max(0.0, min(1.0, left * volume)) * 127),
        round(max(0.0, min(1.0, right * volume)) * 127),
    )


def _event_tick(event: ReplaySoundEvent) -> int:
    return max(0, round(event.due_q16 * NTSC_FRAMES_PER_SECOND / 65536.0))


def build_mix_schedule(
    replay: DecodedSoundReplay,
    waves: Sequence[QuakeWave],
    listeners: Sequence[Listener],
    precise_timing_ticks: Sequence[int],
    *,
    volume: float,
) -> MixSchedule:
    """Precompute bounded S-DSP voice decisions; the SNES performs the mix."""

    if len(waves) != len(replay.sound_names):
        raise ValueError("wave count disagrees with sound replay")
    if len(listeners) != replay.camera_row_count:
        raise ValueError("listener count disagrees with sound replay")
    if len(precise_timing_ticks) != replay.camera_row_count:
        raise ValueError("timing count disagrees with sound replay")
    if not 0.0 <= volume <= 1.0:
        raise ValueError("sound volume must be between zero and one")

    duration_ticks = round(
        replay.camera_row_count * NTSC_FRAMES_PER_SECOND / replay.sample_rate_hz
    )
    event_buckets: dict[int, list[ReplaySoundEvent]] = {}
    static_events: dict[int, list[ReplaySoundEvent]] = {}
    source_starts = source_statics = source_stops = 0
    for event in replay.events:
        if event.kind == SOUND_EVENT_STATIC:
            source_statics += 1
            static_events.setdefault(event.sound_slot, []).append(event)
        else:
            source_starts += int(event.kind == SOUND_EVENT_START)
            source_stops += int(event.kind == SOUND_EVENT_STOP)
            event_buckets.setdefault(_event_tick(event), []).append(event)

    boundary_rows = tuple(range(0, replay.camera_row_count, replay.sample_rate_hz // 2))
    boundary_at = {precise_timing_ticks[row]: row for row in boundary_rows}
    voices = [_Voice() for _ in range(VOICE_COUNT)]
    commands: list[MixCommand] = []
    inaudible_events = hardware_starts = hardware_stops = 0
    hardware_steals = static_restarts = volume_updates = peak_active_voices = 0
    generation = 0

    def event_volumes(event: ReplaySoundEvent, listener: Listener) -> tuple[int, int]:
        gains = _spatial_gain(
            entity=event.entity,
            view_entity=replay.view_entity,
            volume=event.volume,
            attenuation=event.attenuation,
            origin=event.origin,
            listener=listener,
        )
        return _dsp_volumes(*gains, volume)

    def static_volumes(slot: int, listener: Listener) -> tuple[int, int]:
        left = right = 0.0
        for event in static_events.get(slot, ()):
            gains = _spatial_gain(
                entity=0,
                view_entity=replay.view_entity,
                volume=event.volume,
                attenuation=event.attenuation,
                origin=event.origin,
                listener=listener,
            )
            left += gains[0]
            right += gains[1]
        return _dsp_volumes(left, right, volume)

    def emit_stop(tick: int, voice_index: int) -> None:
        nonlocal hardware_stops
        voice = voices[voice_index]
        if not voice.active:
            return
        commands.append(MixCommand(tick, MIX_COMMAND_STOP, voice_index, 0xFF, 0, 0))
        voices[voice_index] = _Voice(generation=voice.generation + 1)
        hardware_stops += 1

    def emit_start(
        tick: int,
        voice_index: int,
        *,
        slot: int,
        left: int,
        right: int,
        static: bool,
        entity: int,
        channel: int,
        origin: tuple[float, float, float],
        event_volume: int,
        attenuation: int,
        end_tick: int | None,
    ) -> None:
        nonlocal generation, hardware_starts, hardware_steals
        if voices[voice_index].active:
            hardware_steals += 1
        generation += 1
        commands.append(
            MixCommand(tick, MIX_COMMAND_START, voice_index, slot, left, right)
        )
        voices[voice_index] = _Voice(
            True,
            static,
            slot,
            entity,
            channel,
            origin,
            event_volume,
            attenuation,
            end_tick,
            left,
            right,
            generation,
        )
        hardware_starts += 1

    def refresh_static(tick: int, listener: Listener) -> None:
        nonlocal static_restarts, volume_updates
        dynamic_count = sum(voice.active and not voice.static for voice in voices)
        desired_count = VOICE_COUNT - dynamic_count
        ranked = sorted(
            (
                (
                    max(*static_volumes(slot, listener)),
                    slot,
                    static_volumes(slot, listener),
                )
                for slot in static_events
            ),
            key=lambda item: (-item[0], item[1]),
        )
        desired = {slot for score, slot, _gains in ranked[:desired_count] if score > 0}
        for voice_index, voice in enumerate(tuple(voices)):
            if voice.active and voice.static and voice.sound_slot not in desired:
                emit_stop(tick, voice_index)
        active_slots = {
            voice.sound_slot for voice in voices if voice.active and voice.static
        }
        for _score, slot, gains in ranked:
            if slot not in desired or slot in active_slots:
                continue
            try:
                voice_index = next(
                    index for index, voice in enumerate(voices) if not voice.active
                )
            except StopIteration:
                break
            source = static_events[slot][0]
            emit_start(
                tick,
                voice_index,
                slot=slot,
                left=gains[0],
                right=gains[1],
                static=True,
                entity=0,
                channel=0,
                origin=source.origin,
                event_volume=source.volume,
                attenuation=source.attenuation,
                end_tick=None,
            )
            active_slots.add(slot)
            static_restarts += int(tick != 0)
        for voice_index, voice in enumerate(tuple(voices)):
            if not voice.active:
                continue
            gains = (
                static_volumes(voice.sound_slot, listener)
                if voice.static
                else _dsp_volumes(
                    *_spatial_gain(
                        entity=voice.entity,
                        view_entity=replay.view_entity,
                        volume=voice.volume,
                        attenuation=voice.attenuation,
                        origin=voice.origin,
                        listener=listener,
                    ),
                    volume,
                )
            )
            if gains != (voice.left, voice.right):
                commands.append(
                    MixCommand(
                        tick,
                        MIX_COMMAND_VOLUME,
                        voice_index,
                        voice.sound_slot,
                        gains[0],
                        gains[1],
                    )
                )
                voice.left, voice.right = gains
                volume_updates += 1

    listener = listeners[0]
    all_ticks = sorted(set(event_buckets) | set(boundary_at) | {duration_ticks})
    cursor = 0
    while cursor <= duration_ticks:
        candidates = [tick for tick in all_ticks if tick >= cursor]
        natural = [
            voice.end_tick
            for voice in voices
            if voice.active and voice.end_tick is not None and voice.end_tick >= cursor
        ]
        if not candidates and not natural:
            break
        tick = min((*candidates, *natural))
        if tick > duration_ticks:
            break
        for voice_index, voice in enumerate(tuple(voices)):
            if voice.active and voice.end_tick is not None and voice.end_tick <= tick:
                emit_stop(tick, voice_index)
        if tick in boundary_at:
            listener = listeners[boundary_at[tick]]
        for event in event_buckets.get(tick, ()):
            if event.kind == SOUND_EVENT_STOP:
                for voice_index, voice in enumerate(tuple(voices)):
                    if (
                        voice.active
                        and not voice.static
                        and voice.entity == event.entity
                        and voice.channel == event.channel
                    ):
                        emit_stop(tick, voice_index)
                        break
                continue
            if event.kind != SOUND_EVENT_START:
                continue
            gains = event_volumes(event, listener)
            if max(gains) == 0:
                inaudible_events += 1
                continue
            matching = [
                index
                for index, voice in enumerate(voices)
                if voice.active
                and not voice.static
                and event.channel
                and voice.entity == event.entity
                and voice.channel == event.channel
            ]
            free = [index for index, voice in enumerate(voices) if not voice.active]
            if matching:
                voice_index = matching[0]
            elif free:
                voice_index = free[0]
            else:
                eligible = [
                    index
                    for index, voice in enumerate(voices)
                    if not (
                        not voice.static
                        and voice.entity == replay.view_entity
                        and event.entity != replay.view_entity
                    )
                ]
                if not eligible:
                    eligible = list(range(VOICE_COUNT))
                voice_index = min(
                    eligible,
                    key=lambda index: (
                        not voices[index].static,
                        max(voices[index].left, voices[index].right),
                        voices[index].end_tick
                        if voices[index].end_tick is not None
                        else duration_ticks + 1,
                        index,
                    ),
                )
            wave = waves[event.sound_slot]
            end_tick = None
            if wave.loop_start is None:
                end_tick = tick + max(
                    1,
                    round(
                        len(wave.samples) * NTSC_FRAMES_PER_SECOND / wave.sample_rate_hz
                    ),
                )
            emit_start(
                tick,
                voice_index,
                slot=event.sound_slot,
                left=gains[0],
                right=gains[1],
                static=False,
                entity=event.entity,
                channel=event.channel,
                origin=event.origin,
                event_volume=event.volume,
                attenuation=event.attenuation,
                end_tick=end_tick,
            )
        if tick in boundary_at:
            refresh_static(tick, listener)
        peak_active_voices = max(
            peak_active_voices, sum(voice.active for voice in voices)
        )
        all_ticks = [value for value in all_ticks if value > tick]
        cursor = tick + 1

    for voice_index, voice in enumerate(tuple(voices)):
        if voice.active:
            emit_stop(duration_ticks, voice_index)
    commands.append(MixCommand(duration_ticks, MIX_COMMAND_COMPLETE, 0xFF, 0xFF, 0, 0))
    commands.sort(key=lambda command: command.due_tick)
    return MixSchedule(
        tuple(commands),
        duration_ticks,
        len(replay.events),
        source_starts,
        source_statics,
        source_stops,
        inaudible_events,
        hardware_starts,
        hardware_stops,
        hardware_steals,
        static_restarts,
        volume_updates,
        peak_active_voices,
    )
