"""Pack stock landing cues and a point-contents tree reduced to water."""

from functools import cache
from pathlib import Path
from struct import iter_unpack, pack

from snes_tooling.quake.quake_bsp_assets import lump_data, lump_ranges
from snes_tooling.quake.quake_snes_realtime_sound import resample_wave_pcm
from snes_tooling.quake.quake_snes_soundtrack import encode_brr, parse_quake_wave

LANDING_INCLUDE = Path("QuakeBSPLanding.i")
LANDING_WATER = Path("QuakeBSPLandingWater.bin")
WATER_NODE_BYTES = 14
CONTENTS_WATER = -3
WATER_TERMINAL = -1
DRY_TERMINAL = -2
LANDING_SAMPLES = (
    ("Land", "player/land.wav"),
    ("LandHard", "player/land2.wav"),
    ("LandWater", "player/h2ojump.wav"),
)


def water_tree(bsp, origin):
    lumps = lump_ranges(bsp)
    planes = tuple(iter_unpack("<4fi", lump_data(bsp, lumps, 1)))
    nodes = tuple(iter_unpack("<ihh6hHH", lump_data(bsp, lumps, 5)))
    leaves = tuple(row[0] for row in iter_unpack("<ii6hHH4B", lump_data(bsp, lumps, 10)))
    root = next(iter_unpack("<9f7i", lump_data(bsp, lumps, 14)))[9]
    # SV_CheckWater samples one unit above the bottom of the player hull.
    # Convert a Q4 eye position to that point with a 22-unit view height.
    feet_origin = (*origin[:2], origin[2] - 45)
    packed = {}

    @cache
    def prune(index):
        if index < 0:
            return WATER_TERMINAL if leaves[~index] == CONTENTS_WATER else DRY_TERMINAL
        plane, front, back, *_ = nodes[index]
        front, back = prune(front), prune(back)
        if front == back:
            return front
        nx, ny, nz, distance, _ = planes[plane]
        normal = (nx, ny, nz)
        coefficients = tuple(round(component * 16384) for component in normal)
        bias = round((sum(n * value for n, value in zip(normal, feet_origin, strict=True))
                      - distance) * 16 * 16384)
        if abs(bias) + sum(abs(c) * 32768 for c in coefficients) >= 2**31:
            raise ValueError("landing point-contents plane exceeds signed 32-bit arithmetic")
        return packed.setdefault((front, back, *coefficients, bias), len(packed) * WATER_NODE_BYTES)

    root_offset = prune(root)
    if len(packed) * WATER_NODE_BYTES >= 0x8000:
        raise ValueError("landing point-contents offsets exceed a signed word")
    return root_offset, b"".join(pack("<5hi", *row) for row in packed)


def landing_water_outputs(bsp, origin):
    root, water = water_tree(bsp, origin)
    return {
        LANDING_INCLUDE: f"WALK_LANDING_WATER_ROOT = {root & 0xffff}\n".encode("ascii"),
        LANDING_WATER: water,
    }


def landing_outputs(archive, bsp, origin):
    outputs = landing_water_outputs(bsp, origin)
    for stem, name in LANDING_SAMPLES:
        wave = parse_quake_wave(archive.read("sound/" + name))
        pcm = resample_wave_pcm(wave, output_rate_hz=4000, bandlimit=True)
        outputs[Path(f"QuakeBSP{stem}.brr")] = encode_brr(pcm + (0,) * (-len(pcm) % 16))
    return outputs
