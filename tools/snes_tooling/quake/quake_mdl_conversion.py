"""Coverage-aware conversion of retained quarter-unit MDL masters."""
from __future__ import annotations

import numpy as np

CONVERSION_VERSION = 'quarter-area-coverage-contrast-v1'


def palette_colors(words):
    if len(words) != 256:
        raise ValueError('MDL conversion requires 256 RGB555 palette words')
    return np.array([[(int(v) >> shift) & 31 for shift in (0, 5, 10)]
                     for v in words], dtype=float)


def integrate(master, dimensions, palette):
    """Integrate uniform final-cell footprints without coloring transparency."""
    width, height = dimensions
    mh, mw = master.shape
    coverage = np.zeros((height, width))
    mean = np.zeros((height, width, 3))
    minimum = np.zeros_like(mean)
    maximum = np.zeros_like(mean)
    for y in range(height):
        y0, y1 = y * mh / height, (y + 1) * mh / height
        iy = np.arange(int(np.floor(y0)), int(np.ceil(y1)))
        wy = np.maximum(0, np.minimum(iy + 1, y1) - np.maximum(iy, y0))
        for x in range(width):
            x0, x1 = x * mw / width, (x + 1) * mw / width
            ix = np.arange(int(np.floor(x0)), int(np.ceil(x1)))
            wx = np.maximum(0, np.minimum(ix + 1, x1) - np.maximum(ix, x0))
            weights = np.outer(wy, wx)
            region = master[np.ix_(iy, ix)]
            weights *= region != 0
            total = weights.sum()
            coverage[y, x] = total / ((x1 - x0) * (y1 - y0))
            if total:
                colors = palette[np.maximum(region.astype(int) - 1, 0)]
                mean[y, x] = (colors * weights[:, :, None]).sum(axis=(0, 1)) / total
                opaque = colors[weights > 0]
                minimum[y, x], maximum[y, x] = opaque.min(axis=0), opaque.max(axis=0)
    return coverage, mean, minimum, maximum


def restore_contrast(mean, coverage, minimum, maximum, strength):
    """Bound the mask-aware contrast target before source-palette snapping."""
    h, w = coverage.shape
    numerator = np.zeros_like(mean)
    denominator = np.zeros_like(coverage)
    p = np.pad(mean * coverage[:, :, None], ((1, 1), (1, 1), (0, 0)))
    a = np.pad(coverage, ((1, 1), (1, 1)))
    for y, ky in enumerate((1, 2, 1)):
        for x, kx in enumerate((1, 2, 1)):
            numerator += p[y:y+h, x:x+w] * ky * kx
            denominator += a[y:y+h, x:x+w] * ky * kx
    low = numerator / np.maximum(denominator[:, :, None], 1e-12)
    return np.clip(mean + strength * (mean - low), minimum, maximum)


def convert_master(master, dimensions, words, *, contrast=0.5):
    """Return biased-u8 pixels and coverage evidence; preserve tiny projectiles."""
    palette = palette_colors(words)
    coverage, mean, minimum, maximum = integrate(master, dimensions, palette)
    target = restore_contrast(mean, coverage, minimum, maximum, contrast)
    indices = np.unique(master[master != 0]).astype(int) - 1
    output = np.zeros(coverage.shape, dtype=np.uint8)
    mask = coverage >= 0.5
    tiny_fallback = bool(indices.size and not mask.any())
    if tiny_fallback:
        # A real subpixel projectile must not become an empty sprite. Preserve
        # one strongest-covered cell, with deterministic row-major tie order.
        mask.flat[int(coverage.argmax())] = True
    if indices.size:
        choices = palette[indices]
        distance = ((target[:, :, None, :] - choices[None, None, :, :]) ** 2).sum(axis=3)
        selected = indices[distance.argmin(axis=2)] + 1
        output[mask] = selected[mask].astype(np.uint8)
    metrics = dict(
        projectedOpaqueArea=float(coverage.sum()),
        opaquePixels=int(mask.sum()),
        alphaSquaredError=float(((mask.astype(float) - coverage) ** 2).sum()),
        pixelCount=int(mask.size), tinyCoverageFallback=int(tiny_fallback),
    )
    return output, metrics
