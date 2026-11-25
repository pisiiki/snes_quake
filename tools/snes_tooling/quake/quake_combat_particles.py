"""View-facing client particle bursts from WinQuake R_RunParticleEffect."""

from snes_tooling.quake.quake_billboard_assets import BillboardSprite, reduce_coverage_aware_raster

MODEL = "effects/combat-impact.spr"
FRAMES = 5
# TE_SPIKE, TE_GUNSHOT, and the blood counts issued for pellets, spikes and melee.
STYLES = ((0, 10), (0, 20), (72, 8), (72, 18), (72, 40), (72, 80))


def impact_sprites(model_id, density):
    for style, (base_color, count) in enumerate(STYLES):
        seed = 1

        def random():
            nonlocal seed
            seed = (214013 * seed + 2531011) & 0xffffffff
            return (seed >> 16) & 32767

        particles = []
        for _ in range(count):
            life = random() % 5
            color = base_color + (random() & 7)
            position = tuple((random() & 15) - 8 for _ in range(3))
            particles.append((life, color, position))
        for age in range(FRAMES):
            # The emitter itself supplies the shared velocity. Only gravity
            # changes the particles' positions relative to the emitter.
            fall = round(40 * (age * 2) * (age * 2 - 1) / 800)
            top = 7 - fall
            pixels = [0] * 256
            for life, color, (_, y, z) in particles:
                if age <= life:
                    pixels[(7 - z) * 16 + (7 - y)] = 0x100 | color
            width, height, reduced = reduce_coverage_aware_raster(16, 16, tuple(pixels), density)
            # A burst faces the view. Its eight directions have the same pixels.
            yield BillboardSprite(width, height, -7, top, reduced, 16, 16,
                                  model_id, FRAMES * style + age, 0)
