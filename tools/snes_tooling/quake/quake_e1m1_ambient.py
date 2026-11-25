"""Compile E1M1's stationary industrial mix from original QuakeC spawn calls."""
from dataclasses import dataclass
from hashlib import sha256
from struct import iter_unpack

from snes_tooling.quake.quake_bsp_assets import PakArchive, lump_data, lump_ranges, parse_entities
from snes_tooling.quake.quake_snes_realtime_sound import resample_wave_pcm
from snes_tooling.quake.quake_snes_soundtrack import encode_brr, parse_quake_wave
from snes_tooling.quake.quakec_gameplay import Program
from snes_tooling.quake.quakec_reference import ReferenceVM, asf

# Keep the original loop periods. The brighter sparks use most of the shared
# sample region, while the drone's spectrum lies almost entirely below 450 Hz.
SOURCES = (("ambience/comp1.wav", 2000), ("ambience/drone6.wav", 1200),
           ("ambience/fl_hum1.wav", 1700), ("ambience/buzz1.wav", 3800))
CLASSES = {"ambient_comp_hum", "ambient_drone", "light_fluoro", "light_fluorospark"}
HEARING_LIMIT_Q4 = 5344


class AmbientVM(ReferenceVM):
    def builtin(self, builtin_id, name):
        if name != "ambientsound":
            return super().builtin(builtin_id, name)
        self.events.append((name, tuple(asf(x) for x in self.g[4:7]), self.string(self.g[7]),
                            asf(self.g[10]), asf(self.g[13])))


@dataclass(frozen=True)
class AmbientBank:
    include: bytes
    payload: bytes
    report: dict


def build_ambient_bank(archive: PakArchive) -> AmbientBank:
    bsp = archive.read("maps/e1m1.bsp")
    lumps = lump_ranges(bsp)
    world = next(iter_unpack("<9f7i", lump_data(bsp, lumps, 14)))
    return _compile(archive, bsp, lumps, tuple((world[i] + world[i + 3]) * .5 for i in range(3)))


def emitter_y_bands(positions):
    """Keep each emitter in every 16-bit Y band touching its audible interval."""
    masks = [0] * 16
    radius = HEARING_LIMIT_Q4 - 1
    for index, y in enumerate(positions):
        first = ((y - radius) & 0xffff) >> 12
        last = ((y + radius) & 0xffff) >> 12
        if last < first:
            last += len(masks)
        for band in range(first, last + 1):
            masks[band & 15] |= 1 << index
    return masks


def _compile(archive, bsp, lumps, center):
    program = Program(archive.read("progs.dat"))
    names = [name for name, _ in SOURCES]
    spots = []
    for entity_number, entity in enumerate(parse_entities(lump_data(bsp, lumps, 0)), 1):
        classname = entity["classname"]
        if classname not in CLASSES or int(entity.get("spawnflags", "0")) & 256:
            continue
        vm = AmbientVM(program, ())
        vm.add(0, {"classname": "worldspawn"})
        vm.add(1, dict(classname=classname, style=entity.get("style", 0),
                       origin=tuple(map(float, entity["origin"].split()))))
        vm.event(1, classname)
        [(_, position, name, gain, attenuation)] = [event for event in vm.events if event[0] == "ambientsound"]
        if attenuation != 3 or gain not in (.5, 1):
            raise ValueError(f"unsupported stock ambience at {position}: {name}, {gain}, {attenuation}")
        spots.append(dict(entity=entity_number, kind=classname, sound=name, slot=names.index(name), gain=gain,
                          attenuation=attenuation, origin=list(position),
                          eyeQ4=[round((x - base) * 16) for x, base in zip(position, center, strict=True)]))
    if [sum(row["slot"] == slot for row in spots) for slot in range(4)] != [4, 1, 6, 2]:
        raise ValueError("expected all thirteen original E1M1 industrial emitters")
    waves = []
    payload = bytearray()
    for name, rate in SOURCES:
        raw = archive.read("sound/" + name)
        wave = parse_quake_wave(raw, name)
        if wave.loop_start != 0:
            raise ValueError("original stationary wave must loop from sample zero")
        pcm = resample_wave_pcm(wave, output_rate_hz=rate, bandlimit=True)
        data = bytearray(encode_brr(pcm, initial_silence=False, first_filter_zero=True))
        data[-9] |= 3
        pitch = round(len(pcm) / len(wave.samples) * wave.sample_rate_hz * 4096 / 32000)
        waves.append(dict(name=name, sourceSha256=sha256(raw).hexdigest(), sourceRate=wave.sample_rate_hz,
                          sourceSamples=len(wave.samples), loopStart=wave.loop_start, pitch=pitch,
                          samples=len(pcm), offset=len(payload), bytes=len(data), sha256=sha256(data).hexdigest()))
        payload.extend(data)
    lines = [f"INDUSTRIAL_HEARING_LIMIT_Q4 = {HEARING_LIMIT_Q4}",
             f"INDUSTRIAL_BANK_BYTES = {len(payload)}"]
    for slot, wave in enumerate(waves):
        for key in ("pitch", "bytes", "offset"):
            lines.append(f"INDUSTRIAL_{key.upper()}_{slot} = {wave[key]}")
    lines.append(".macro INDUSTRIAL_SOURCE_TABLE")
    for row in spots:
        values = [*row['eyeQ4'], row['slot'] * 2, round(row['gain'] * 128)]
        lines.append(".word " + ",".join(f"${n & 65535:04x}" for n in values))
    lines.append(".endmacro")
    masks = emitter_y_bands([row["eyeQ4"][1] for row in spots])
    lines.append(".macro INDUSTRIAL_Y_BANDS")
    lines.append(".word " + ",".join(f"${n:04x}" for n in masks))
    lines.append(".endmacro")
    return AmbientBank(("\n".join(lines) + "\n").encode("ascii"), bytes(payload),
                       dict(originalSpawns=spots, waves=waves, bytes=len(payload), sha256=sha256(payload).hexdigest()))
