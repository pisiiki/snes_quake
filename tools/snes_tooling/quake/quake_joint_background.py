"""Exact repeated-texture assignment and RGB555 palette learning from RGB L1 histograms."""
from __future__ import annotations

import numpy as np

RGB5 = ((np.arange(32) << 3) | (np.arange(32) >> 2)).astype(np.int64)
TEXEL = ((np.arange(224)[:, None] % 64)*64 + np.arange(256)[None, :] % 64)


def texture_groups(block_size=1):
    if block_size not in (1, 2):
        raise ValueError('texture block size must be 1 or 2')
    n = 64//block_size
    return np.arange(4096).reshape(n, block_size, n, block_size).transpose(0, 2, 1, 3).reshape(n*n, -1)


def expand_indices(indices, block_size):
    groups = texture_groups(block_size)
    result = np.empty(4096, dtype=np.uint8)
    result[groups] = np.asarray(indices)[:, None]
    return result


def quantize(rgb):
    return ((np.asarray(rgb, dtype=np.uint16)*31+127)//255).astype(np.uint8)


def color_costs(histogram):
    """L1 cost of every RGB555 channel value at every repeated texel."""
    h = np.asarray(histogram, dtype=np.int64)
    if h.shape not in ((4096, 3, 32), (1024, 3, 32)) or np.any(h < 0):
        raise ValueError('nonnegative 4096 or 1024 x RGB x 32 histogram required')
    cost = np.empty_like(h)
    cost[..., 0] = (h * RGB5).sum(axis=-1)
    derivative = (2*np.cumsum(h, axis=-1)[..., :-1]-h.sum(axis=-1)[..., None])*np.diff(RGB5)
    cost[..., 1:] = cost[..., :1] + np.cumsum(derivative, axis=-1)
    return cost


def assignments(cost, palette):
    p = np.asarray(palette, dtype=np.uint8)
    if p.shape != (15, 3) or np.any(p > 31):
        raise ValueError('15 visible RGB555 colours required')
    errors = sum(cost[:, channel, p[:, channel]] for channel in range(3))
    indices = np.argmin(errors, axis=1)
    return indices, int(errors[np.arange(len(cost)), indices].sum())


def medians(histogram):
    h = np.asarray(histogram, dtype=np.int64)
    return np.argmax(np.cumsum(h, axis=-1)*2 >= h.sum(axis=-1)[..., None], axis=-1).astype(np.uint8)


def fit_palette(histogram, *, seed=690, starts=3, iterations=24, block_size=1):
    """Alternate exact texel assignments and weighted channel medians.

    This is a deterministic bounded local search, not a globally optimal palette.
    Counts include every repeated occurrence and every observed presentation.
    """
    h = np.asarray(histogram, dtype=np.int64)
    if block_size != 1:
        h = h[texture_groups(block_size)].sum(axis=1)
    cost = color_costs(h)
    preferred = medians(h)
    weights = h[:, 0].sum(axis=1)
    rng = np.random.default_rng(seed)
    best = None
    for start in range(starts):
        palette = [medians(h.sum(axis=0))]
        # Weighted error seeding spreads centres in the actual texel loss space.
        for _ in range(14):
            p = np.array(palette)
            error = np.min(sum(cost[:, c, p[:, c]] for c in range(3)), axis=1)
            floor = sum(cost[np.arange(len(h)), c, preferred[:, c]] for c in range(3))
            mass = np.maximum(0, error-floor).astype(float)
            if mass.sum() == 0:
                mass = weights.astype(float)
            index = (int(np.argmax(mass)) if start == 0 else
                     int(rng.choice(len(h), p=mass/mass.sum()))) if mass.sum() else 0
            palette.append(preferred[index])
        palette = np.array(palette, dtype=np.uint8)
        previous = None
        for _ in range(iterations):
            indices, error = assignments(cost, palette)
            if previous == error:
                break
            previous = error
            for index in range(15):
                cluster = h[indices == index].sum(axis=0)
                if cluster.sum():
                    palette[index] = medians(cluster)
        indices, error = assignments(cost, palette)
        candidate = (error, palette.tobytes(), indices.astype(np.uint8).tobytes())
        if best is None or candidate < best:
            best = candidate
    error, palette, indices = best
    return {'paletteQ5': np.frombuffer(palette, dtype=np.uint8).reshape(15, 3).tolist(),
            'textureHex': expand_indices(np.frombuffer(indices, dtype=np.uint8)+1, block_size).tobytes().hex(),
            **({'textureBlockSize': block_size, 'logicalTextureSize': 64//block_size} if block_size != 1 else {}),
            'backgroundError': error, 'starts': starts, 'maximumIterations': iterations}


def texture_rgb5(model):
    palette = np.asarray(model['paletteQ5'], dtype=np.uint8)
    texture = np.frombuffer(bytes.fromhex(model['textureHex']), dtype=np.uint8)
    if texture.shape != (4096,) or np.any((texture < 1) | (texture > 15)):
        raise ValueError('texture must contain exactly 4096 nontransparent 4bpp indices')
    groups = texture_groups(model.get('textureBlockSize', 1))
    if not np.all(texture[groups] == texture[groups[:, :1]]):
        raise ValueError('texture violates its tied chunky blocks')
    return palette[texture-1]


def tile_bytes(model):
    """64 consecutive SNES 4bpp tiles; the runtime uploads eight strided rows."""
    pixels = np.frombuffer(bytes.fromhex(model['textureHex']), dtype=np.uint8).reshape(64, 64)
    texture_rgb5(model)
    output = bytearray()
    for ty in range(8):
        for tx in range(8):
            tile = pixels[ty*8:ty*8+8, tx*8:tx*8+8]
            for first_plane in (0, 2):
                for row in tile:
                    for plane in (first_plane, first_plane+1):
                        output.append(sum(int((value >> plane) & 1) << (7-x) for x, value in enumerate(row)))
    return bytes(output)


def palette_words(model):
    colors = np.asarray(model['paletteQ5'], dtype=np.uint16)
    texture_rgb5(model)
    return (colors[:, 0] | colors[:, 1] << 5 | colors[:, 2] << 10).astype('<u2').tobytes()
