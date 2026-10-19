"""Integer camera-plane contract for the SNES HDMA implementation (T659).

Angles are recorded u16 turns, positions are Quake units / 16. Source angles
are the renderer's 256-step Q6 basis; target angles use a 4096-step Q12 sine.
This module is also the independent register oracle for native probes.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path
import time

import numpy as np
from snes_tooling.quake.quake_warp_profile import DepthProfile

Q = 4096
PROFILE = (213, 205, 437)
Y = tuple(3 + 7 * i for i in range(32))
INV_DEPTH = tuple(round(4 * float(np.interp(y, (0, 111.5, 223), PROFILE))) for y in Y)
V = tuple(round((221 - 2 * y) * Q / 384) for y in Y)
SIN = tuple(round(math.sin(i * math.tau / 4096) * Q) for i in range(1025))
SIN6 = tuple(round(math.sin(i * math.tau / 256) * 64) for i in range(256))
DUAL = tuple(round(SIN6[i] * 64 * Q / (SIN6[i] ** 2 + SIN6[(i + 64) % 256] ** 2)) for i in range(256))
# Nearest half-Q12 denominator, limited to the forward-facing ray domain.
RECIP = tuple(round(Q * Q / max(512, i * 2)) for i in range(3073))
LOG = (0,) + tuple(round(math.log2(i) * 1024) for i in range(1, 32768))
EXP = tuple(round(2 ** (i / 1024)) for i in range(15360))
BLANK = (0, 0, 0, 0, 96, 96, 96, 96)
IDENTITY = (-85, 0, 0, 85, 85, 0, 85, 0)


def mul(a, b, shift=12):
    """Quarter-square multiply, with a full product fallback for large inputs."""
    a, b = int(a), int(b)
    if abs(a) + abs(b) < 16384:
        magnitude = (abs(a) + abs(b)) ** 2 // 4096 - (abs(a) - abs(b)) ** 2 // 4096
        value = (-magnitude if (a < 0) != (b < 0) else magnitude) >> (shift - 10)
    else:
        value = a * b >> shift
    if not -32768 <= value <= 32767:
        raise OverflowError((a, b, shift))
    return value


def sin(angle):
    index = ((angle + 8) & 65535) >> 4
    quadrant, offset = divmod(index, 1024)
    value = SIN[1024 - offset if quadrant & 1 else offset]
    return -value if quadrant & 2 else value


def camera_terms(source, target, precise=True):
    """Camera tuples: x/y/z Q4, yaw/pitch u16; source has low angle bytes zero."""
    sy, cy = DUAL[(source[3] >> 8) & 255], DUAL[((source[3] >> 8) + 64) & 255]
    sp, cp = DUAL[(source[4] >> 8) & 255], DUAL[((source[4] >> 8) + 64) & 255]
    trig = sin if precise else lambda angle: SIN6[(angle >> 8) & 255] * 64
    ts, tc, ps, pc = trig(target[3]), trig(target[3] + 16384), trig(target[4]), trig(target[4] + 16384)
    q, r = mul(sy, ts) + mul(cy, tc), mul(cy, ts) - mul(sy, tc)
    pq, cq = mul(ps, q), mul(pc, q)
    rotation = (q, -mul(ps, r), mul(pc, r),
                mul(sp, r), mul(sp, pq) + mul(cp, pc), mul(cp, ps) - mul(sp, cq),
                -mul(cp, r), mul(sp, pc) - mul(cp, pq), mul(cp, cq) + mul(sp, ps))
    dx, dy, dz = [int(target[i]) - int(source[i]) for i in range(3)]
    horizontal = mul(cy, dx) + mul(sy, dy)
    translation = (mul(cy, dy) - mul(sy, dx),
                   mul(cp, dz) - mul(sp, horizontal),
                   mul(cp, horizontal) + mul(sp, dz))
    return rotation, translation


def log_scale(value, factor, source_focal=64):
    if value == 0:
        return 0
    if abs(value) >= 32768:
        raise OverflowError(value)
    index = LOG[abs(value)] + factor
    if index >= len(EXP):
        raise OverflowError(index)
    if source_focal == 64:
        magnitude = EXP[index] if index >= 0 else int(index >= -1024)
    else:
        magnitude = round(2**(index/1024) * source_focal/64)
    return -magnitude if value < 0 else magnitude


def projection_terms(rotation, translation, bands=32, profile=None, source_focal=64):
    """Affine rays/cofactors and piecewise depth, accumulated with eight guard bits."""
    r = rotation
    first_v = 2293 if bands == 32 else 2229
    step_shift = 11 if bands == 32 else 10
    accum = [(mul(r[row*3], -21) + mul(r[row*3+1], first_v) + r[row*3+2]) << 8
             for row in range(3)]
    steps = [r[row*3+1] * -19115 >> step_shift for row in range(3)]
    constants = []
    for row in (0, 1):
        a, b, c = r[row*3:row*3+3]
        cross = mul(a, r[7]) - mul(b, r[6])
        accum.append((mul(cross, first_v) + mul(a, r[8]) - mul(c, r[6])) << 8)
        steps.append(cross * -19115 >> step_shift)
        constants.append(-mul(cross, -21) + mul(b, r[8]) - mul(c, r[7]))
    bottom, bottom_steps = [], []
    profile = profile or DepthProfile()
    coefficients = profile.coefficients(bands)
    def interpolate(delta, name):
        coefficient, shift = coefficients[name]
        return delta*coefficient >> shift
    for axis, t in enumerate(translation):
        focal = source_focal if axis < 2 else 64
        top, middle, end = [mul(t, (q*4*focal+32)//64, 10) for q in profile.depths]
        accum.append((top << 8) + interpolate(middle-top, 'leftStart'))
        steps.append(interpolate(middle-top, 'leftStep'))
        bottom.append((middle << 8) + interpolate(end-middle, 'rightStart'))
        bottom_steps.append(interpolate(end-middle, 'rightStep'))
    return accum, steps, constants, bottom, bottom_steps


def fallback_registers(source_focal=64):
    """Static Mode7 crop when the retained source has no matching HDMA table."""
    if source_focal == 64:
        return IDENTITY
    scale = (85 * source_focal + 32) // 64
    x = 85 - ((85 - 43) * (64 - source_focal) + 32) // 64
    y = (37 * (64 - source_focal) + 63) // 64
    return (-scale, 0, 0, scale, x, y, x, y - 1)


def registers(source, target, precise=True, bands=32, pivot_search=False, profile=None,
              source_focal=64):
    """32 projective tangents with a fixed pivot; legacy search is diagnostic."""
    if bands not in (16, 32):
        raise ValueError('only candidate 16 and legacy 32 band evaluations are defined')
    if not 32 < source_focal <= 64:
        raise ValueError('source focal must be in (32, 64]')
    if source == target and source_focal == 64:
        return np.tile(IDENTITY, (32, 1))
    profile = profile or DepthProfile()
    split = profile.coefficients(bands)['split']
    try:
        rotation, translation = camera_terms(source, target, precise)
        accum, steps, constants, bottom, bottom_steps = projection_terms(rotation, translation, bands, profile, source_focal)
    except OverflowError:
        return np.tile(BLANK, (32, 1))
    result = []
    ys = Y if bands == 32 else tuple(6+14*i for i in range(16))
    for band, y in enumerate(ys):
        if band == split:
            accum[5:], steps[5:] = bottom[:], bottom_steps[:]
        ray = [a >> 8 for a in accum[:3]]
        tx, ty, tz = [a >> 8 for a in accum[5:]]
        cofactors = (accum[3] >> 8, constants[0], accum[4] >> 8, constants[1])
        accum = [a + step for a, step in zip(accum, steps)]
        try:
            remaining = Q - tz
            if not 513 <= ray[2] < 6144 or not 0 < remaining < 32768:
                result.append(BLANK)
                continue
            factor = LOG[remaining] - LOG[ray[2]]
            projected = [tx + log_scale(ray[0], factor, source_focal), ty + log_scale(ray[1], factor, source_focal)]
            if any(not -32768 <= p < 32768 for p in projected):
                raise OverflowError(projected)
            center = [43*256 + projected[0]*4, 37*256 - projected[1]*4]
            slope_factor = factor - LOG[ray[2]] + 6569  # log2(4096/48), Q10.
            slopes = [log_scale(value, slope_factor, source_focal) * (-1 if i < 2 else 1)
                      for i, value in enumerate(cofactors)]
            origin = [center[row] + (slopes[row*2]+1)//2 for row in (0, 1)]
            best = None
            for dx in ((-1, 0) if pivot_search else (0,)):
                for dy in ((-1, 0) if pivot_search else (0,)):
                    terms = [(slopes[row*2]*dx & ~63) + slopes[row*2+1]*dy - (slopes[row*2+1]*(dy-y-1) & 63) for row in (0, 1)]
                    centers = [(origin[row]-terms[row]+128)//256 for row in (0, 1)]
                    error = sum((centers[row]*256+terms[row]-origin[row])**2 for row in (0, 1))
                    if best is None or error < best[0]:
                        best = error, (*slopes, *centers, centers[0]+dx-128, centers[1]+dy-y-1)
            values = best[1]
            result.append(values if all(-4096 <= v <= 4095 for v in values[4:]) else BLANK)
        except OverflowError:
            result.append(BLANK)
    return np.repeat(np.array(result, dtype=np.int64), 32//bands, axis=0)


def emit_tables():
    lines = ['; Generated by quake_snes_hdma.py --write-tables. Camera-only constants.', '.segment "HDMA_WARP_CODE"']
    for name, values in (("HdmaSine", SIN), ("HdmaDualSine", DUAL + DUAL[:64]),
                         ("HdmaReciprocal", RECIP), ("HdmaInverseDepth", INV_DEPTH),
                         ("HdmaRayY", V), ("HdmaSquare", tuple(min(i, 256-i) ** 2 for i in range(256)))):
        lines.append(name + ':')
        for first in range(0, len(values), 12):
            lines.append('        .word ' + ', '.join(f'${v & 65535:04X}' for v in values[first:first+12]))
    lines.append('HdmaPivotResidue:')
    for y in Y:
        for first in range(0, 64, 16):
            lines.append('        .byte '+', '.join(str((-v*(y+1)) & 63) for v in range(first, first+16)))
    lines += ['.segment "HDMA_SQUARE_TABLE"', 'HdmaQuarterSquare:']
    for first in range(0, 16384, 16):
        lines.append('        .word ' + ', '.join(f'${i*i//4096:04X}' for i in range(first, first+16)))
    return '\n'.join(lines) + '\n'


def generated_tables(path):
    outputs = {path: emit_tables()}
    for suffix, segment, label, values in (
            ('LogLow', 'HDMA_LOG_LOW', 'HdmaLog', LOG[:16384]),
            ('LogHigh', 'HDMA_LOG_HIGH', 'HdmaLogHigh', LOG[16384:]),
            ('Exp', 'HDMA_EXP', 'HdmaExp', EXP)):
        lines = ['; Generated by quake_snes_hdma.py --write-tables.',
                 f'.segment "{segment}"', label+':']
        for first in range(0, len(values), 16):
            lines.append('        .word '+', '.join(f'${v:04X}' for v in values[first:first+16]))
        outputs[path.with_name('HdmaWarp'+suffix+'.s')] = '\n'.join(lines)+'\n'
    return outputs


def main():
    started = time.perf_counter()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write-tables', type=Path)
    parser.add_argument('--check-tables', type=Path)
    args = parser.parse_args()
    if args.write_tables:
        for path, payload in generated_tables(args.write_tables).items():
            path.write_text(payload, encoding='utf-8', newline='\n')
    if args.check_tables:
        for path, payload in generated_tables(args.check_tables).items():
            if path.read_text(encoding='utf-8') != payload:
                raise SystemExit(f'{path.name} stale; elapsedSeconds={time.perf_counter()-started:.3f}')
    print(f'HDMA constants OK; elapsedSeconds={time.perf_counter()-started:.3f}')


if __name__ == '__main__':
    main()
