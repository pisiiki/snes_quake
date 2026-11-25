"""Refine world boundaries using existing, exactly collinear BSP vertices."""

from __future__ import annotations

from collections import defaultdict
from fractions import Fraction
from functools import reduce
from math import gcd
from typing import Sequence


EDGE_REFINEMENT_POLICY = "existing-source-and-q2-collinear-endpoints-v1"
# Production ROM assets and their independent reference view must agree.
PRODUCTION_PACKED_EDGE_SCOPE = "bsp-all-exact"


def _sub(a, b):
    return tuple(x - y for x, y in zip(a, b, strict=True))


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b, strict=True))


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _line_key(a, b):
    delta = _sub(b, a)
    divisor = reduce(gcd, (abs(value) for value in delta))
    if not divisor:
        return None
    direction = tuple(value // divisor for value in delta)
    if next(value for value in direction if value) < 0:
        direction = tuple(-value for value in direction)
    return direction, _cross(direction, a)


def _interior(point, a, b):
    edge, offset = _sub(b, a), _sub(point, a)
    return _cross(edge, offset) == (0, 0, 0) and 0 < _dot(edge, offset) < _dot(edge, edge)


def refine_world_face_edges(
    source_vertices: Sequence[Sequence[float]],
    packed_q2_vertices: Sequence[Sequence[int]],
    contours: Sequence[Sequence[int]],
    eligible: Sequence[bool],
) -> tuple[tuple[tuple[int, ...], ...], dict[str, object]]:
    """Insert shared endpoints strictly inside the same source and Q2 edge.

    Source float values are compared as exact rationals. Original vertices stay
    in order; no point is moved, created, or admitted from an ineligible face.
    This changes topology only. Callers must retain original contours for
    polygon-derived shading, planes, eligibility, and other non-topology data.
    """
    if len(source_vertices) != len(packed_q2_vertices):
        raise ValueError("source and packed vertex counts differ")
    if len(contours) != len(eligible):
        raise ValueError("contour and eligibility counts differ")
    source = [tuple(Fraction(value) for value in point) for point in source_vertices]
    denominator = max((value.denominator for point in source for value in point), default=1)
    exact = [tuple(int(value * denominator) for value in point) for point in source]
    if any(Fraction(value, denominator) != original
           for point, original_point in zip(exact, source, strict=True)
           for value, original in zip(point, original_point, strict=True)):
        raise ValueError("source denominators must share a power-of-two scale")
    line_points = defaultdict(dict)
    edge_keys = {}
    for face, (ids, enabled) in enumerate(zip(contours, eligible, strict=True)):
        if not enabled:
            continue
        for edge, (start, end) in enumerate(zip(ids, (*ids[1:], *ids[:1]), strict=True)):
            key = _line_key(exact[start], exact[end])
            edge_keys[face, edge] = key
            if key is None:
                continue
            for vertex in (start, end):
                parameter = _dot(key[0], exact[vertex])
                old = line_points[key].get(parameter)
                if old is None or vertex < old:
                    line_points[key][parameter] = vertex
    refined = []
    changed = []
    for face, ids in enumerate(contours):
        output, changes = [], []
        for edge, (start, end) in enumerate(zip(ids, (*ids[1:], *ids[:1]), strict=True)):
            output.append(start)
            key = edge_keys.get((face, edge))
            if key is None:
                continue
            first, last = (_dot(key[0], exact[vertex]) for vertex in (start, end))
            inside = sorted(
                ((parameter, vertex) for parameter, vertex in line_points[key].items()
                 if min(first, last) < parameter < max(first, last)
                 and _interior(packed_q2_vertices[vertex], packed_q2_vertices[start],
                               packed_q2_vertices[end])),
                reverse=first > last,
            )
            # Distinct exact source junctions can pack to the same Q2 point.
            # Keep one deterministic representative instead of a zero-length edge.
            inserted, used = [], set()
            for _, vertex in inside:
                packed = tuple(packed_q2_vertices[vertex])
                if packed not in used:
                    used.add(packed)
                    inserted.append(vertex)
            output.extend(inserted)
            if inserted:
                changes.append({"edge": edge, "from": start, "to": end, "inserted": inserted})
        refined.append(tuple(output))
        if changes:
            changed.append({"face": face, "oldCount": len(ids), "newCount": len(output), "edges": changes})
    return tuple(refined), {
        "policy": EDGE_REFINEMENT_POLICY,
        "refined_face_count": len(changed),
        "inserted_index_count": sum(item["newCount"] - item["oldCount"] for item in changed),
        "maximum_face_vertices": max(map(len, refined), default=0),
        "faces": changed,
    }


PACKED_AFFINE_REFINEMENT_POLICY = "existing-eligible-q2-edge-endpoints-exact-affine-q4-v1"


def packed_world_edge_candidates(packed_q2_vertices, contours, eligible, *,
                                 source_vertices=None, extra_contours=()):
    """Return exact interior endpoints shared with eligible encoded edge lines.

    This second stage concerns encoded geometry only: a source-collinear point
    can quantize off its source line, and conversely a source junction can pack
    exactly onto a neighboring edge. No position moves or vertex is created.
    Texture interpolation is checked separately before any candidate is used.
    """
    if len(contours) != len(eligible):
        raise ValueError("contour and eligibility counts differ")
    if extra_contours and (source_vertices is None
                           or len(source_vertices) != len(packed_q2_vertices)):
        raise ValueError("extra BSP contours require matching exact source vertices")
    line_points = defaultdict(dict)
    keys = {}
    for face, (ids, enabled) in enumerate(zip(contours, eligible, strict=True)):
        if not enabled:
            continue
        for edge, (first, last) in enumerate(zip(ids, (*ids[1:], *ids[:1]), strict=True)):
            key = _line_key(packed_q2_vertices[first], packed_q2_vertices[last])
            keys[face, edge] = key
            if key is None:
                continue
            for vertex in (first, last):
                parameter = _dot(key[0], packed_q2_vertices[vertex])
                old = line_points[key].get(parameter)
                if old is None or vertex < old:
                    line_points[key][parameter] = vertex
    extra_points = defaultdict(dict)
    source = ([tuple(Fraction(value) for value in point) for point in source_vertices]
              if extra_contours else ())
    for ids in extra_contours:
        for first, last in zip(ids, (*ids[1:], *ids[:1]), strict=True):
            key = _line_key(packed_q2_vertices[first], packed_q2_vertices[last])
            if key is None:
                continue
            for vertex in (first, last):
                parameter = _dot(key[0], packed_q2_vertices[vertex])
                old = extra_points[key].get(parameter)
                if old is None or vertex < old:
                    extra_points[key][parameter] = vertex
    candidates = []
    for face, ids in enumerate(contours):
        edges = []
        for edge, (first, last) in enumerate(zip(ids, (*ids[1:], *ids[:1]), strict=True)):
            key = keys.get((face, edge))
            if key is None:
                edges.append(())
                continue
            aa, bb = (_dot(key[0], packed_q2_vertices[v]) for v in (first, last))
            points = dict(line_points[key])
            for parameter, vertex in extra_points[key].items():
                if parameter not in points and _interior(source[vertex], source[first], source[last]):
                    points[parameter] = vertex
            interior = sorted(((parameter, vertex) for parameter, vertex in points.items()
                               if min(aa, bb) < parameter < max(aa, bb)), reverse=aa > bb)
            edges.append(tuple((vertex, Fraction(parameter - aa, bb - aa))
                               for parameter, vertex in interior))
        candidates.append(tuple(edges))
    return tuple(candidates)


def refine_packed_face_coordinates(contour, coordinates_q4, candidates):
    """Preserve every old ST and admit only integral exact affine Q4 junctions.

    The Q2 parameter preserves both the continuous encoded boundary and its
    affine endpoint ST field. Rounding an inserted ST is forbidden. This is a
    topology proof, not a claim that discrete projected pixels stay unchanged.
    """
    if not len(contour) == len(coordinates_q4) == len(candidates):
        raise ValueError("contour, ST and candidate edge counts differ")
    if any(len(st) != 2 or any(not isinstance(value, int) for value in st)
           for st in coordinates_q4):
        raise ValueError("old Q4 texture coordinates must be integer pairs")
    output, coordinates, accepted, rejected = [], [], [], []
    for edge, first in enumerate(contour):
        output.append(first)
        coordinates.append(tuple(coordinates_q4[edge]))
        first_st, last_st = coordinates_q4[edge], coordinates_q4[(edge + 1) % len(contour)]
        previous = Fraction(0)
        for vertex, parameter in candidates[edge]:
            if not previous < parameter < 1:
                raise ValueError("packed junction parameters must be strictly ordered interior points")
            previous = parameter
            exact = tuple(Fraction(a) + (b - a) * parameter
                          for a, b in zip(first_st, last_st, strict=True))
            item = {"edge": edge, "from": first, "to": contour[(edge + 1) % len(contour)],
                    "inserted": vertex, "parameter": str(parameter),
                    "exactST": [str(value) for value in exact]}
            if any(value.denominator != 1 for value in exact):
                rejected.append(item)
                continue
            output.append(vertex)
            coordinates.append(tuple(int(value) for value in exact))
            accepted.append(item)
    return tuple(output), tuple(coordinates), {"accepted": accepted, "rejectedNonintegralST": rejected}
