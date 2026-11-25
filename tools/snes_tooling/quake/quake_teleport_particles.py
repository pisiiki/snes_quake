"""Rasterize the stock TE_TELEPORT particle cloud for the gameplay billboard renderer."""
from math import hypot

from snes_tooling.quake.quake_billboard_assets import BillboardSprite, reduce_coverage_aware_raster

MODEL = "effects/te_teleport.spr"
FRAMES = 7
STRIPS = 3


def teleport_sprites(model_id, density):
    # WinQuake R_TeleportSplash uses its client rand(), independently of progs.dat.
    # Use the Windows CRT sequence so fresh packages reproduce the same cloud.
    seed = 1

    def rand():
        nonlocal seed
        seed = (214013 * seed + 2531011) & 0xffffffff
        return (seed >> 16) & 32767

    cloud = []
    for x in range(-16, 16, 4):
        for y in range(-16, 16, 4):
            for z in range(-24, 32, 4):
                life = 0.2 + (rand() & 7) * 0.02
                color = 7 + (rand() & 7)
                location = (x + (rand() & 3), y + (rand() & 3), z + (rand() & 3))
                speed = 50 + (rand() & 63)
                norm = hypot(x, y, z) or 1
                velocity = (y * speed / norm, x * speed / norm, z * speed / norm)
                cloud.append((life, color, location, velocity))

    for frame in range(FRAMES):
        seconds = frame / 20
        # Each gameplay frame advances pt_slowgrav by sv_gravity * dt * .05.
        fall = 40 * frame * (frame - 1) / (2 * 20 * 20)
        points = [
            (location[0] + velocity[0] * seconds, round(-location[1] - velocity[1] * seconds),
             round(location[2] + velocity[2] * seconds - fall), color)
            for life, color, location, velocity in cloud if seconds <= life
        ]
        left = min(x for _, x, _, _ in points)
        top = max(z for _, _, z, _ in points)
        width = max(x for _, x, _, _ in points) - left + 1
        height = top - min(z for _, _, z, _ in points) + 1
        pixels = [0] * (width * height)
        for _, x, z, color in sorted(points, reverse=True):
            pixels[(top - z) * width + x - left] = 0x100 | color
        from snes_tooling.quake.quake_playable_sprite_stream import CACHE_BYTES
        for strip in range(STRIPS):
            first, end = height * strip // STRIPS, height * (strip + 1) // STRIPS
            strip_height = end - first
            stored_width, stored_height, stored = reduce_coverage_aware_raster(
                width, strip_height, tuple(pixels[first * width:end * width]), density)
            if len(stored) > CACHE_BYTES:
                raise ValueError("teleport cloud strip exceeds the live sprite cache")
            yield BillboardSprite(stored_width, stored_height, left, top - first, stored, width, strip_height,
                                  model_id, frame * STRIPS + strip, 0)
