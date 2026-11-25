"""Derive and audit whole-tail bounds for the stock E1M1 Q3 resume grid."""

from functools import cache
from hashlib import sha256
from itertools import product
from struct import iter_unpack

from snes_tooling.quake.quake_playable_footing import _plane_bounds


EMPTY = 0xFFFF
VISIT_LIMIT = 4096


def pack_column_masks(masks):
    """Use one nibble per column when the full set fits a small dictionary."""
    values = bytes(sorted(set(masks)))
    if len(values) > 16 or len(masks) % 2:
        return masks, b""
    codes = {mask: code for code, mask in enumerate(values)}
    packed = bytes(codes[low] | (codes[high] << 4)
                   for low, high in zip(masks[::2], masks[1::2], strict=True))
    return packed, values


def side_bounds(plane, low, high):
    coefficients, plane_low, plane_high = plane
    dot_low = dot_high = 0
    for coefficient, begin, end in zip(coefficients, low, high, strict=True):
        a, b = begin * coefficient, end * coefficient
        dot_low += min(a, b)
        dot_high += max(a, b)
    if min(dot_low, dot_low - plane_high) < -(1 << 31) or max(dot_high, dot_high - plane_low) >= 1 << 31:
        raise ValueError("point-tail proof would overflow the native distance")
    return dot_low >= plane_high, dot_high < plane_low


def cell_debts(nodes, planes, models, low, high):
    first = repeated = stack = cumulative_splits = 0
    for model, next_model in zip(models, (*models[1:], {"root": EMPTY}), strict=True):
        continuation = next_model["root"]
        split_planes = set()

        @cache
        def depth(node):
            if node == continuation:
                return 0, 0
            if node >= 0x8000:
                return None
            if node % 6 or not model["nodeBegin"] <= node < model["nodeEnd"]:
                raise ValueError("point-tail child escapes its authored model")
            reference, front, back = nodes[node // 6]
            front_only, back_only = side_bounds(planes[reference], low, high)
            if front_only or back_only:
                result = depth(front if front_only else back)
                return (result[0] + 1, result[1]) if result is not None else None
            front_result, back_result = depth(front), depth(back)
            if front_result is None or back_result is None:
                return None
            # Only Z changes within one vertical ray. A horizontal plane may
            # choose either side across a cell but cannot split an individual ray.
            split = bool(planes[reference][0][2])
            if split:
                split_planes.add(reference)
            return 1 + max(front_result[0], back_result[0]), split + max(front_result[1], back_result[1])

        result = depth(model["root"])
        if result is None:
            return None
        visits, extra_stack = result
        # Split points are fixed for one ray and the live intervals (lo, hi]
        # are disjoint. Therefore a plane can push only once, across all
        # entries to this model. Later models inherit its additional intervals.
        cumulative_splits += len(split_planes)
        first += visits * (1 + cumulative_splits)
        repeated += visits
        stack += extra_stack
    # Reserve the additional EMPTY visits created by internal splits. Each
    # outer entry retains its original single EMPTY visit in the runtime path.
    return first + cumulative_splits, repeated, stack


def build_table(raw_hull, meta, constants, gameplay, minimum, maximum, cell_size, depth):
    if (sha256(raw_hull).hexdigest() != meta["sha256"]
            or meta["positionFractionBits"] != 3 or meta["roots"][0] != 0):
        raise ValueError("point-tail certification requires the checked Q3 E1M1 hull")
    models = tuple(meta["modelRanges"][1:])
    if tuple(model["model"] for model in models[:5]) != (3, 4, 1, 2, 5):
        raise ValueError("point-tail model order changed")
    nodes = tuple(iter_unpack("<3H", raw_hull[:meta["nodes"] * 6]))
    planes = _plane_bounds(raw_hull, nodes, meta, constants, gameplay)
    x_range, y_range, z_range = [range(a, b + 1) for a, b in zip(minimum, maximum, strict=True)]
    if len(z_range) != 8:
        raise ValueError("point-tail column requires eight height cells")
    table = bytearray()
    maximum_debts = [0, 0, 0]
    certified = 0
    for y, x in product(y_range, x_range):
        mask = 0
        for bit, z in enumerate(z_range):
            low = (x * cell_size, y * cell_size, z * cell_size - depth)
            high = ((x + 1) * cell_size - 1, (y + 1) * cell_size - 1, (z + 1) * cell_size - 1)
            if min(low) < -32768 or max(high) > 32767:
                raise ValueError("point-tail grid crosses a signed coordinate boundary")
            debts = cell_debts(nodes, planes, models, low, high)
            if debts is None or debts[0] >= VISIT_LIMIT or debts[2] > meta["stackEntries"]:
                continue
            mask |= 1 << bit
            certified += 1
            maximum_debts = [max(a, b) for a, b in zip(maximum_debts, debts, strict=True)]
        table.append(mask)
    if not certified:
        raise ValueError("point-tail grid did not certify any cells")
    return bytes(table), tuple(maximum_debts), certified
