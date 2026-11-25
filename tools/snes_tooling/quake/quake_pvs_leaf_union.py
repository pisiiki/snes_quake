"""Bake conservative source VIS for every native signed-byte camera position."""
from __future__ import annotations

from fractions import Fraction
from functools import reduce
from math import gcd, lcm

import numpy as np


def source_lattice_planes(planes, origin, scale):
    """Express the original binary floats exactly on the native camera lattice."""
    scale = Fraction(float(scale))
    rows = []
    bounded = True
    for plane in planes:
        normal = [Fraction(float(value)) for value in plane[:3]]
        constant = sum(n * Fraction(float(o)) for n, o in zip(normal, origin)) - Fraction(float(plane[3]))
        values = [n * scale for n in normal] + [-constant]
        denominator = lcm(*(value.denominator for value in values))
        integers = [int(value * denominator) for value in values]
        divisor = reduce(gcd, integers)
        if divisor == 0:
            raise ValueError('source BSP plane has no separating expression')
        row = [value // divisor for value in integers]
        bounded &= 128 * sum(abs(value) for value in row[:3]) + abs(row[3]) < 2 ** 63
        rows.append(row)
    # Unusual BSP float exponents still remain exact; ordinary maps use int64.
    return np.asarray(rows, dtype=np.int64 if bounded else object)


def leaf_ids(points, node_planes, children, planes, root, *, packed=False):
    """Match Quake's back-at-equality lookup and native signed-word arithmetic."""
    current = np.full(len(points), root, dtype=np.int32)
    for _ in range(len(children) + 1):
        active = np.flatnonzero(current >= 0)
        if not len(active):
            return -current - 1
        ids = current[active]
        selected = planes[node_planes[ids]]
        distance = np.sum(points[active] * selected[:, :3], axis=1) - selected[:, 3]
        if packed:
            distance = ((distance + 32768) & 65535) - 32768
        current[active] = children[ids, (distance <= 0).astype(np.int32)]
    raise ValueError('BSP camera traversal did not terminate')


def _camera_mapping(source_planes, packed_planes, nodes, contents, root, origin,
                    *, scale=16, axis=range(-128, 128), batch_x=4, closed_contacts=False):
    node_planes = np.asarray([n.plane for n in nodes], dtype=np.int32)
    children = np.asarray([n.children for n in nodes], dtype=np.int32)
    source_nodes = np.column_stack((node_planes, children))
    source = source_lattice_planes(source_planes, origin, scale)
    packed = np.asarray([(*normal, distance) for normal, distance in packed_planes], dtype=np.int32)
    contents = np.asarray(contents)
    pairs = np.zeros((len(contents), len(contents)), dtype=bool)
    cameras = valid_count = different = 0
    values = np.asarray(axis, dtype=np.int32)
    if batch_x < 1 or not len(values) or np.any((values < -128) | (values > 127)):
        raise ValueError('camera batches require the native signed-byte domain')
    for first in range(0, len(values), batch_x):
        points = np.stack(np.meshgrid(values[first:first + batch_x], values, values,
                                     indexing='ij'), axis=-1).reshape(-1, 3)
        src = leaf_ids(points, node_planes, children, source, root)
        if np.any((src < 0) | (src >= len(contents))):
            raise ValueError('source camera escaped world leaf range')
        valid = contents[src] != -2
        # Source-solid positions have no interior visibility obligation. Native
        # leaf zero still retains the existing all-visible fallback unchanged.
        if closed_contacts:
            from .packed_visibility.camera_regions import closed_leaf_contacts
            owners, contacts = closed_leaf_contacts(points, source_nodes, source, root)
            if np.any(contacts >= len(contents)):
                raise ValueError('source camera contact escaped world leaf range')
            open_contacts = contents[contacts] != -2
            contact_points = points[owners[open_contacts]]
            packed_contacts = leaf_ids(contact_points, node_planes, children, packed, root, packed=True)
            pairs[packed_contacts, contacts[open_contacts]] = True
        dst = leaf_ids(points[valid], node_planes, children, packed, root, packed=True)
        src = src[valid]
        if np.any((dst < 0) | (dst >= len(contents))):
            raise ValueError('packed camera escaped world leaf range')
        pairs[dst, src] = True
        cameras += len(points)
        valid_count += len(src)
        different += int(np.count_nonzero(src != dst))
    mapping = tuple(tuple(np.flatnonzero(row).tolist()) for row in pairs)
    return mapping, dict(cameraCount=cameras, nonSolidSourceCameras=valid_count,
                         differingLeafCameras=different)


def union_rows(rows, mapping):
    """Only add visibility; read every union from the original, unmodified rows."""
    if len(rows) != len(mapping) or not rows or len({len(row) for row in rows}) != 1:
        raise ValueError('PVS mapping requires one equally sized row per world leaf')
    original = np.asarray([list(row) for row in rows], dtype=np.uint8)
    merged = original.copy()
    changed = []
    for leaf, sources in enumerate(mapping):
        if any(source < 0 or source >= len(rows) for source in sources):
            raise ValueError('PVS union source is outside world leaf range')
        if sources:
            merged[leaf] |= np.bitwise_or.reduce(original[list(sources)], axis=0)
        added = int(np.unpackbits(merged[leaf] ^ original[leaf]).sum())
        if added:
            changed.append(dict(packedLeaf=leaf, sourceLeaves=list(sources), addedFaceBits=added))
    return tuple(bytes(row) for row in merged), changed


def conservative_rows(rows, *, planes, packed_planes, nodes, leaves, root, origin, scale, camera_step=None,
                      closed_contacts=False):
    """Exhaustively bind source leaf VIS to the native BSP traversal."""
    if camera_step is None:
        mapping, counts = _camera_mapping(planes, packed_planes, nodes,
            [leaf.contents for leaf in leaves[:len(rows)]], root, origin, scale=scale,
            closed_contacts=closed_contacts)
        extent = 128
    else:
        from snes_tooling.quake.quake_pvs_camera_lattice import fine_camera_mapping

        if scale != 16 or camera_step not in (4, 8):
            raise ValueError("unsupported playable camera lattice")
        mapping, counts = fine_camera_mapping(
            planes, packed_planes, nodes, leaves[:len(rows)], root, origin, step=camera_step,
            closed_contacts=closed_contacts,
        )
        extent = 128 * (16 // camera_step)
    merged, changes = union_rows(rows, mapping)
    report = dict(contract=('finite-s8-camera-pvs-union-v1' if camera_step is None
                           else 'finite-playable-camera-pvs-union-v2'),
        cameraDomain=dict(minimum=-extent, maximum=extent - 1, axes=3),
        sourceScope='all source non-solid camera positions; packed solid fallback preserved',
        sourceArithmetic='exact integer expression of original BSP dyadic planes on native camera lattice',
        planeTie='back', packedArithmetic=('signed-byte products and signed-word sum/subtract'
            if camera_step is None else 'exact sign of the packed plane at the fine camera'),
        **counts, ambiguousPackedLeaves=sum(any(src != leaf for src in row)
                                            for leaf, row in enumerate(mapping)),
        changedRows=len(changes), addedFaceBits=sum(row['addedFaceBits'] for row in changes),
        changes=changes)
    if camera_step is not None:
        report['cameraDomain']['quakeUnitsPerStep'] = camera_step
    if closed_contacts:
        report.update(contract='finite-closed-source-camera-pvs-union-v3',
                      planeTie='packed back; union exact nonsolid source contacts')
    if report['cameraCount'] != (2 * extent) ** 3:
        raise ValueError('PVS camera proof did not cover the complete native domain')
    return merged, report
