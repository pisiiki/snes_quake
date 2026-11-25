"""Derive conservative world culling data from the encoded Q2 boundary.

These five-byte planes control admission only. Raster geometry, texture
coordinates, source shading planes, materials and face identities remain
independent. Nonplanar polygons use the existing projection guard.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from itertools import product
from math import ceil
from typing import Sequence

from snes_tooling.quake.quake_bsp_assets import quantized_face_plane


WORLD_CULL_POLICY = "exact-q2-planar-lp-raster-margin-v2"
CAMERA_Q2_DOMAIN = (-512, 511)
Point = tuple[int, int, int]


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b, strict=True))


def _sub(a, b):
    return tuple(x - y for x, y in zip(a, b, strict=True))


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def raster_front_margin(polygon: Sequence[Point], normal: Point) -> int:
    """Widen the front half-space for narrow planar connector contours."""
    for first, last in zip(polygon, (*polygon[1:], polygon[0]), strict=True):
        side = _cross(normal, _sub(last, first))
        if not any(side):
            continue
        offsets = [_dot(side, point) for point in polygon]
        span = max(offsets) - min(offsets)
        if span * span <= 4 * _dot(side, side):
            # At most two Q2 units across this in-plane direction. Keep a
            # one-Q2 coordinate band around the edge-on facing boundary.
            return sum(map(abs, normal))
    return 0


def _front_support(normal: Point, distance: int, objective: Point) -> Fraction:
    """Exact support of a box cut by the true Q2 front half-space.

    Every vertex is a box corner or a cutting-plane/box-edge intersection.
    Enumerating those vertices proves the linear objective's maximum over
    the complete continuous domain, including points between native cameras.
    """
    corners = list(product(CAMERA_Q2_DOMAIN, repeat=3))
    signed = {point: _dot(normal, point) - distance for point in corners}
    candidates = [tuple(map(Fraction, point)) for point in corners if signed[point] <= 0]
    for index, first in enumerate(corners):
        for last in corners[index + 1:]:
            if sum(a != b for a, b in zip(first, last, strict=True)) != 1:
                continue
            d1, d2 = signed[first], signed[last]
            if (d1 < 0 < d2) or (d2 < 0 < d1):
                ratio = Fraction(d1, d1 - d2)
                candidates.append(tuple(Fraction(a) + (b - a) * ratio
                                        for a, b in zip(first, last, strict=True)))
    if not candidates:
        raise ValueError("true front half-space does not intersect the camera Q2 domain")
    return max(_dot(objective, point) for point in candidates)


def _evaluation_range(normal: Point, distance: int) -> tuple[int, int]:
    low, high = CAMERA_Q2_DOMAIN
    return (
        sum(value * (low if value >= 0 else high) for value in normal) - distance,
        sum(value * (high if value >= 0 else low) for value in normal) - distance,
    )


@dataclass(frozen=True)
class WorldCullPlane:
    normal: Point
    distance: int
    guarded: bool
    normal_shift: int | None
    exact_front_support: Fraction | None
    evaluation_range: tuple[int, int] | None


def derive_world_cull_plane(polygon: Sequence[Point]) -> WorldCullPlane:
    """Return the existing binary format with proved conservative admission.

    A planar contour has one exact integer geometric plane N.camera <= D.
    Expand its front half-space by the bounded raster margin where applicable.
    For stored normal n, set d=ceil(max(n.camera)) over that expanded half-space
    intersected with the full camera box. Try the original Q6 normal first, then
    round its components to nearest/even after successive power-of-two
    downscales. Choose the first whose complete evaluation range is signed16.

    Native LMULT low words and word ADD/SUB compute the same expression modulo
    65536. Its proved final range [-32768,32767] makes that signed result equal
    to the unwrapped expression, even if intermediate additions wrap. No new
    per-frame arithmetic, format flags, or plane-derived raster inputs result.
    """
    if len(polygon) < 3:
        raise ValueError("world culling requires at least three Q2 vertices")
    first = polygon[0]
    crosses = [_cross(_sub(polygon[index], first), _sub(polygon[index + 1], first))
               for index in range(1, len(polygon) - 1)]
    actual_normal = max(crosses, key=lambda normal: _dot(normal, normal))
    if actual_normal == (0, 0, 0):
        raise ValueError("world culling received a collapsed Q2 contour")
    actual_distance = _dot(actual_normal, first)
    old_normal, old_distance = quantized_face_plane(list(polygon))
    if any(_dot(actual_normal, point) != actual_distance for point in polygon):
        return WorldCullPlane(old_normal, old_distance, True, None, None, None)
    front_distance = actual_distance + raster_front_margin(polygon, actual_normal)
    for shift in range(8):
        normal = tuple(round(Fraction(value, 1 << shift)) for value in old_normal)
        if normal == (0, 0, 0) or _dot(normal, actual_normal) <= 0:
            continue
        support = _front_support(actual_normal, front_distance, normal)
        distance = ceil(support)
        span = _evaluation_range(normal, distance)
        if -32768 <= distance <= 32767 and -32768 <= span[0] and span[1] <= 32767:
            return WorldCullPlane(normal, distance, False, shift, support, span)
    raise ValueError(
        f"no conservative signed16 cull plane fits Q2 contour: "
        f"normal={actual_normal}, distance={actual_distance}, vertices={len(polygon)}"
    )
