"""Bake the stock client particle burst into bounded view-parallel gameplay sprites."""

from dataclasses import replace
from functools import lru_cache

from snes_tooling.quake.quake_billboard_assets import BillboardSprite, reduce_coverage_aware_raster
from snes_tooling.quake.quake_playable_sprite_stream import CACHE_BYTES

MODEL = "effects/explobox-particles.spr"
RAMPS = ((111, 110, 109, 108, 107, 106, 104, 102), (111, 109, 107, 105, 103, 101, 99, 97))


def particle_steps():
    # WinQuake R_ParticleExplosion, using an independent client CRT stream.
    seed = 1

    def rand():
        nonlocal seed
        seed = (214013 * seed + 2531011) & 0xffffffff
        return (seed >> 16) & 32767

    cloud = []
    for index in range(1024):
        ramp = rand() & 3
        origin, velocity = [], []
        for _ in range(3):
            origin.append((rand() & 31) - 16)
            velocity.append((rand() & 511) - 256)
        cloud.append((index & 1, ramp, 111, origin, velocity))

    while cloud:
        yield tuple((origin[0], round(-origin[1]), round(origin[2]), color)
                    for _, _, color, origin, _ in cloud)
        advanced = []
        for kind, ramp, _, origin, velocity in cloud:
            ramp += (10 if kind else 15) / 20
            if ramp >= 8:
                continue
            position = [p + v / 20 for p, v in zip(origin, velocity)]
            speed = [v * (1.2 if kind else 0.95) for v in velocity]
            speed[2] -= 40 / 20
            advanced.append((kind, ramp, RAMPS[kind][int(ramp)], position, speed))
        cloud = advanced


def strips(points, axis):
    ordered = sorted(points, key=lambda p: p[axis])
    start = 0
    while start < len(ordered):
        end = start + 1
        while end < len(ordered) and ordered[end][axis] - ordered[start][axis] < 255:
            end += 1
        yield ordered[start:end]
        start = end


@lru_cache(maxsize=1)
def tile_frames():
    frames = []
    for step, points in enumerate(particle_steps()):
        if step % 2:
            continue
        # Tight bounds both preserve far-flung particles and avoid streaming empty tiles.
        tiles = [tile for column in strips(points, 1) for tile in strips(column, 2)]
        frames.append(tuple(sorted(tiles, key=len, reverse=True)))
    return tuple(frames)


def particle_sprites(model_id, density):
    row = 0
    for tiles in tile_frames():
        for tile in tiles:
            left, right = min(p[1] for p in tile), max(p[1] for p in tile)
            bottom, top = min(p[2] for p in tile), max(p[2] for p in tile)
            width, height = right - left + 1, top - bottom + 1
            pixels = [0] * (width * height)
            for _, x, z, color in sorted(tile, reverse=True):
                pixels[(top - z) * width + x - left] = color | 0x100
            units = max(1, density)
            while True:
                w, h, data = reduce_coverage_aware_raster(width, height, tuple(pixels), units)
                if len(data) <= CACHE_BYTES:
                    break
                units += 1
            sprite = BillboardSprite(w, h, left, top, data, width, height, model_id, row)
            for view in range(8):
                yield replace(sprite, view=view)
            row += 1
