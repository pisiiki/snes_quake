"""Exact authored/packed BSP leaf pairs on the finer playable camera grid."""

from itertools import product

import numpy as np

from snes_tooling.quake.quake_pvs_leaf_union import source_lattice_planes


OCTANTS = np.asarray(tuple(product((0, 1), repeat=3)), dtype=np.int16)


def walk_boxes(low, width, state, planes, node_planes, children, *, stop_at_ties=False):
    """Walk each integer box until it reaches a leaf or straddles a split."""
    state = state.copy()
    high = low + width - 1
    pending = np.flatnonzero(state >= 0)
    for _ in range(len(children) + 1):
        if not len(pending):
            return state
        nodes = state[pending]
        rows = planes[node_planes[nodes]]
        normals = rows[:, :3]
        lower, upper = low[pending], high[pending]
        minimum = np.sum(normals * np.where(normals >= 0, lower, upper), axis=1) - rows[:, 3]
        maximum = np.sum(normals * np.where(normals >= 0, upper, lower), axis=1) - rows[:, 3]
        known = (minimum > 0) | (maximum < 0 if stop_at_ties else maximum <= 0)
        finished = pending[known]
        following = children[nodes[known], (maximum[known] <= 0).astype(np.int32)]
        state[finished] = following
        pending = finished[following >= 0]
    raise ValueError("playable camera box traversal did not terminate")


def audit_brick(lower, width, root, source_planes, packed_planes, node_planes, children, solid, pairs,
                *, closed_contacts=False):
    low = np.asarray([lower], dtype=np.int16)
    source = np.asarray([root], dtype=np.int32)
    packed = source.copy()
    completed = valid = differing = 0
    while len(low):
        volume = width**3
        source = walk_boxes(low, width, source, source_planes, node_planes, children,
                            stop_at_ties=closed_contacts)
        source_leaf = np.maximum(-source - 1, 0)
        if np.any(source_leaf >= len(solid)):
            raise ValueError("source camera escaped world leaf range")
        source_solid = (source < 0) & solid[source_leaf]
        completed += int(source_solid.sum()) * volume
        low, source, packed = low[~source_solid], source[~source_solid], packed[~source_solid]
        if not len(low):
            break
        packed = walk_boxes(low, width, packed, packed_planes, node_planes, children)
        terminal = (source < 0) & (packed < 0)
        source_ids = -source[terminal] - 1
        packed_ids = -packed[terminal] - 1
        if np.any(packed_ids >= len(solid)):
            raise ValueError("packed camera escaped world leaf range")
        pairs[packed_ids, source_ids] = True
        resolved = len(source_ids) * volume
        completed += resolved
        valid += resolved
        differing += int(np.count_nonzero(source_ids != packed_ids)) * volume
        low, source, packed = low[~terminal], source[~terminal], packed[~terminal]
        if not len(low):
            break
        if width == 1:
            if not closed_contacts or np.any(packed >= 0):
                raise ValueError("one playable lattice position still straddles a split")
            from .packed_visibility.camera_regions import closed_leaf_contacts
            nodes = np.column_stack((node_planes, children))
            owners, contacts = closed_leaf_contacts(low, nodes, source_planes, root)
            if np.any(contacts >= len(solid)):
                raise ValueError("source camera contact escaped world leaf range")
            open_contacts = ~solid[contacts]
            pairs[-packed[owners[open_contacts]] - 1, contacts[open_contacts]] = True
            primary = walk_boxes(low, 1, source, source_planes, node_planes, children)
            primary_valid = ~solid[-primary - 1]
            completed += len(low)
            valid += int(np.count_nonzero(primary_valid))
            differing += int(np.count_nonzero(primary_valid & (primary != packed)))
            break
        width //= 2
        low = (low[:, None, :] + OCTANTS[None, :, :] * width).reshape(-1, 3)
        source, packed = np.repeat(source, 8), np.repeat(packed, 8)
    return completed, valid, differing


def coefficient_bound(planes, extent):
    return max(extent * sum(abs(int(value)) for value in row[:3]) + abs(int(row[3])) for row in planes)


def fine_camera_mapping(planes, packed_planes, nodes, leaves, root, origin, *, step, closed_contacts=False):
    if step not in (4, 8):
        raise ValueError("expected a 4- or 8-unit playable camera grid")
    ratio = 16 // step
    extent = 128 * ratio
    node_planes = np.asarray([node.plane for node in nodes], dtype=np.int32)
    children = np.asarray([node.children for node in nodes], dtype=np.int32)
    solid = np.asarray([leaf.contents == -2 for leaf in leaves])
    exact_source = source_lattice_planes(planes, origin, step)
    if coefficient_bound(exact_source, extent) >= 2**63:
        exact_source = exact_source.astype(object)
    exact_packed = np.asarray([(*normal, distance) for normal, distance in packed_planes], dtype=np.int32)
    normals = exact_packed[:, :3]
    if np.any(np.abs(normals) > 64) or coefficient_bound(exact_packed, 128) >= 2**15:
        raise ValueError("packed BSP exceeds the playable camera plane bound")
    # The per-axis fine camera residual is in [0, 3]. Bound the largest
    # positive and negative corrections separately for the native sign test.
    if np.any(np.maximum(normals, 0).sum(axis=1) > 111) or np.any(np.maximum(-normals, 0).sum(axis=1) > 111):
        raise ValueError("packed BSP exceeds the playable camera residual bound")
    exact_packed[:, 3] *= ratio
    pairs = np.zeros((len(leaves), len(leaves)), dtype=bool)
    brick_width = 256
    totals = np.zeros(3, dtype=np.int64)
    for lower in product(range(-extent, extent, brick_width), repeat=3):
        counts = audit_brick(
            lower, brick_width, root, exact_source, exact_packed, node_planes, children, solid, pairs,
            closed_contacts=closed_contacts,
        )
        if counts[0] != brick_width**3:
            raise ValueError("playable camera proof lost lattice positions")
        totals += counts
    complete, valid, differing = map(int, totals)
    return tuple(tuple(np.flatnonzero(row).tolist()) for row in pairs), dict(
        cameraCount=complete, nonSolidSourceCameras=valid, differingLeafCameras=differing
    )
