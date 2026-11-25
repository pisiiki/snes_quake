"""Certify stock E1M1 actor footing over complete Q3 cells and mover sweeps."""

from collections import defaultdict
from functools import cache
from hashlib import sha256
from itertools import groupby, product
import json
from struct import iter_unpack, pack, unpack_from

from snes_tooling.quake.quake_playable_relocation import integer_definitions
from snes_tooling.quake.quake_walk_hull import (
    E1M1_EXIT_MOVER_SWEEPS, PLANE_OFFSET_MASK, SECRET_MODELS, SECRET_SELECTOR_BASE,
    secret_axis_translation_bounds,
)


CELL = 128
PROBE_DEPTH = 36 * 8
RADII = (128, 256)
AXES = ((0, 1), (0, 2), (1, 2), (0,), (1,), (2,), (2,), (0,))
# Each constituent pack fits the original cartridge footprint. The upper-ROM
# table coalesces their proven cells, using the same native rectangle format.
ROW_BUDGET = 150
WIDE_ROWS = 148


def _plane_bounds(payload, nodes, meta, constants, gameplay):
    def down(name):
        return -((constants[name] + 7) // 8), 0

    legacy = {6: down("QC_DOOR_TRAVEL"), 7: down("QC_BUTTON_TRAVEL")}
    entrance = {2: down("QC_ENTRANCE_0_TRAVEL"),
                4: (0, constants["QC_ENTRANCE_1_TRAVEL"] // 8)}
    movers = tuple(meta["exitMoverModels"])
    secrets = gameplay["stockExitMachinery"]["secretDoors"]
    if movers != tuple(E1M1_EXIT_MOVER_SWEEPS) or tuple(row["inlineModel"] for row in secrets) != SECRET_MODELS:
        raise ValueError("footing certificate requires the linked mover order")
    plane_start = len(nodes) * 6
    selector_start = plane_start + meta["exitPlaneTable"]
    planes = {}
    for reference in {reference for reference, _, _ in nodes}:
        kind, owner, offset = reference >> 13, reference & 6, reference & PLANE_OFFSET_MASK
        first, second, distance = unpack_from("<hhi", payload, plane_start + offset)
        coeffs = [0, 0, 0]
        for axis, coefficient in zip(AXES[kind], (first, second) if kind < 3 else (1,), strict=True):
            coeffs[axis] = coefficient
        translations = (0, 0)
        if kind in legacy:
            if owner:
                raise ValueError("legacy footing plane has another mover owner")
            translations = legacy[kind]
        elif owner in entrance:
            translations = tuple(coeffs[1] * value for value in entrance[owner])
        elif owner == 6:
            selector_index = (offset - meta["exitPlaneFirst"]) // 8
            if selector_index < 0:
                raise ValueError("footing plane has no exit mover selector")
            selector = payload[selector_start + selector_index]
            if selector >= SECRET_SELECTOR_BASE:
                index, axis = divmod(selector - SECRET_SELECTOR_BASE, 2)
                if index >= len(secrets) or AXES[kind] != (axis,):
                    raise ValueError("footing plane has an invalid secret translation")
                translations = secret_axis_translation_bounds(secrets[index]["legs"], axis, 3)
            else:
                slot, lane = divmod(selector, 4)
                if slot >= len(movers) or lane > 2:
                    raise ValueError("footing plane has an invalid exit mover selector")
                axis, lower, upper = E1M1_EXIT_MOVER_SWEEPS[movers[slot]]
                if ((lane == 0 and AXES[kind] != (axis,))
                        or (lane and (kind >= 3 or AXES[kind][lane - 1] != axis))):
                    raise ValueError("footing plane has an invalid translated axis")
                translations = coeffs[axis] * lower * 8, coeffs[axis] * upper * 8
        planes[reference] = coeffs, distance + min(translations), distance + max(translations)
    return planes


def _distance_interval(plane, lower, upper):
    coefficients, distance_min, distance_max = plane
    dot_low = dot_high = 0
    for first, last, coefficient in zip(lower, upper, coefficients, strict=True):
        a, b = first * coefficient, last * coefficient
        dot_low += min(a, b)
        dot_high += max(a, b)
    if min(dot_low, dot_low - distance_max) < -(1 << 31) or max(dot_high, dot_high - distance_min) >= 1 << 31:
        raise ValueError("footing certificate would overflow the point-trace distance")
    return dot_low - distance_max, dot_high - distance_min


def _uniform_contents(nodes, planes, low, high, *, solid):
    @cache
    def visit(node):
        if node >= 0x8000:
            return (node != 0xFFFF) == solid
        reference, front, back = nodes[node // 6]
        first, last = _distance_interval(planes[reference], low, high)
        return (last < 0 or visit(front)) and (first >= 0 or visit(back))

    return visit(0)


def _vertical_child_windows(normal_z, first, last, lo, hi):
    """Bound the native Q12 interval and possible push for each child."""
    whole = lo, hi
    if normal_z == 0:
        # Each individual ray and frozen mover pose selects exactly one side.
        return whole if last >= 0 else None, whole if first < 0 else None, False

    # For fixed XY and a 36-unit drop the distance change is the same for
    # every start in this cell. Zero is front at either endpoint.
    denominator = PROBE_DEPTH * abs(normal_z)
    if normal_z > 0:
        near_only = last >= denominator
        far_only = first < 0
        lower, upper = max(first, 0), min(last, denominator - 1)
    else:
        near_only = first < -denominator
        far_only = last >= 0
        lower, upper = max(-last, 1), min(-first, denominator)

    near = whole if near_only else None
    far = whole if far_only else None
    may_push = False
    if lower <= upper:
        # WalkFraction uses the original endpoints at every node. The near
        # subtree is visited at lo < crossing, the far subtree at crossing <= hi.
        earliest = lower * 4096 // denominator
        latest = upper * 4096 // denominator
        if latest > lo and not near_only:
            near = lo, min(hi, latest)
        if earliest <= hi and not far_only:
            far = max(lo, earliest), hi
        may_push = max(earliest, lo + 1) <= min(latest, hi)
    if normal_z > 0:
        return near, far, may_push
    return far, near, may_push


def _vertical_trace_budget(nodes, planes, x, y, feet, height, stack_limit):
    low = x, y, feet - PROBE_DEPTH
    high = x + CELL - 1, y + CELL - 1, feet + height - 1
    if min(low) < -32768 or max(high) > 32767:
        return None

    @cache
    def start_distances(reference):
        plane = planes[reference]
        # The cartridge evaluates both full endpoints even in a clipped child.
        _distance_interval(plane, low, high)
        return _distance_interval(plane, (x, y, feet), high)

    @cache
    def traversal_bound(node, lo, hi):
        if node >= 0x8000:
            return 1, 0
        reference, front, back = nodes[node // 6]
        first, last = start_distances(reference)
        front_window, back_window, may_push = _vertical_child_windows(
            planes[reference][0][2], first, last, lo, hi)
        a, depth_a = traversal_bound(front, *front_window) if front_window is not None else (0, 0)
        b, depth_b = traversal_bound(back, *back_window) if back_window is not None else (0, 0)
        visits = a + b if may_push else max(a, b)
        return 1 + visits, max(depth_a, depth_b) + int(may_push)

    visits, depth = traversal_bound(0, 0, 4096)
    return (visits, depth) if visits < 4096 and depth <= stack_limit else None


def _depth_slab(nodes, planes, x, y, feet, height, first, last, *, solid):
    # One Q12 fraction tick moves less than one Q3 coordinate. The padding
    # includes either branch when the native crossing rounds down at a plane.
    low = x, y, feet - last - 1
    high = x + CELL - 1, y + CELL - 1, feet + height - first
    return _uniform_contents(nodes, planes, low, high, solid=solid)


def _vertical_ray_certificate(nodes, planes, x, y, feet, stack_limit):
    mid = PROBE_DEPTH // 2
    if _depth_slab(nodes, planes, x, y, feet, CELL, mid, mid, solid=True):
        return _vertical_trace_budget(nodes, planes, x, y, feet, CELL, stack_limit)
    return None


def _relative_support(nodes, planes, stack_limit):
    height = CELL // 2
    step = 9  # Each sample is an exact multiple of 128 native Q12 ticks.
    drop_limit = PROBE_DEPTH // 2

    @cache
    def first_solid(x, y, feet):
        for drop in range(0, PROBE_DEPTH + 1, step):
            if _depth_slab(nodes, planes, x, y, feet, height, drop, drop, solid=True):
                limits = _vertical_trace_budget(nodes, planes, x, y, feet, height, stack_limit)
                return (drop, *limits) if limits is not None else None
        return None

    @cache
    def empty_center_depth(x, y, feet):
        for drop in range(drop_limit, 0, -step):
            if _depth_slab(nodes, planes, x, y, feet, height, 0, drop, solid=False):
                return drop
        return 0

    def certify(x, y, feet, radius):
        limits = []
        for start in (feet, feet + height):
            center = first_solid(x, y, start)
            if center is None:
                return None
            limits.append(center[1:])
            # The stock corner test compares hit height to the center hit
            # minus 18 units. A provably empty prefix bounds the earliest
            # center hit. A known solid sample bounds each latest corner hit.
            maximum_drop = empty_center_depth(x, y, start) + drop_limit
            for dx, dy in product((-radius, radius), repeat=2):
                corner = first_solid(x + dx, y + dy, start)
                if corner is None or corner[0] > maximum_drop:
                    return None
                limits.append(corner[1:])
        return tuple(map(max, zip(*limits, strict=True)))

    return certify


def _roster_cells(data, constants):
    edicts = (data / "QuakeBSPQuakeCEdicts.bin").read_bytes()
    field_bytes = (data / "QuakeBSPQuakeCGruntFields.bin").read_bytes()
    count = constants["QC_GRUNT_INIT_WORDS"]
    fields = [field for field, in iter_unpack("<H", field_bytes[:2 * count])]
    if len(fields) != count:
        raise ValueError("footing certificate requires all roster initializer fields")
    origin = constants["QC_FIELD_ORIGIN"]
    first = fields.index(origin)
    if fields[first:first + 3] != [origin, origin + 2, origin + 4]:
        raise ValueError("footing certificate requires consecutive edict origin fields")
    for slot in range(constants["QC_GRUNT_COUNT"]):
        address = constants["QC_GRUNT"] + slot * (len(fields) + 1) * 2
        x, y, z = unpack_from("<3h", edicts, address + 2 + first * 2)
        edict = constants["QC_GRUNT"] + slot * constants["QC_ENTITY_STRIDE"]
        radius = RADII[edict >= constants["QC_DOG_FIRST"]]
        yield x // CELL, y // CELL, (z - 24 * 8) // CELL, radius


def _runs(values):
    for _, run in groupby(enumerate(sorted(values)), key=lambda row: row[1] - row[0]):
        numbers = [value for _, value in run]
        yield numbers[0], numbers[-1]


def _rectangle_cells(box):
    z, radius, left, right, top, bottom = box
    return {(x, y, z, radius) for x, y in product(range(left, right + 1), range(top, bottom + 1))}


def _coverage_rectangles(cells, old_boxes, row_budget=ROW_BUDGET):
    planes = defaultdict(lambda: defaultdict(set))
    for x, y, z, radius in cells:
        planes[z, radius][y].add(x)

    shapes = {}
    for (z, radius), rows in planes.items():
        for top in rows:
            common = rows[top].copy()
            bottom = top
            while common:
                for left, right in _runs(common):
                    span = range(left, right + 1)
                    if any(all(x in rows.get(row, ()) for x in span) for row in (top - 1, bottom + 1)):
                        continue
                    box = z, radius, left, right, top, bottom
                    shapes[box] = _rectangle_cells(box)
                bottom += 1
                common.intersection_update(rows.get(bottom, ()))

    # Grow coverage using static area only. First preserve cells from the
    # original table, then prefer the most additional proven area. Sorting
    # makes the tie break independent of Python's set iteration order.
    candidates = sorted(shapes)
    required = set().union(*(_rectangle_cells(box) for box in old_boxes))
    remaining = set(cells)
    selected = []
    while remaining and candidates and len(selected) < row_budget:
        best = max(candidates, key=lambda box: (len(required & shapes[box]), len(remaining & shapes[box])))
        if remaining.isdisjoint(shapes[best]):
            break
        selected.append(best)
        candidates.remove(best)
        required.difference_update(shapes[best])
        remaining.difference_update(shapes[best])
    return old_boxes if required else selected


def build_e1m1_footing(data, payload, meta):
    """Return exact coverage rectangles and constants for the native lookup."""
    constants = integer_definitions((data / "QuakeBSPBrushAssets.i").read_text(encoding="ascii"))
    gameplay = json.loads((data / "QuakeBSPQuakeCGameplay.json").read_bytes())
    if (meta["positionFractionBits"] != 3 or meta["roots"][0] != 0
            or sha256(payload).hexdigest() != meta["sha256"]):
        raise ValueError("footing certificate requires the verified raw E1M1 point hull")
    nodes = tuple(iter_unpack("<3H", payload[:meta["nodes"] * 6]))
    planes = _plane_bounds(payload, nodes, meta, constants, gameplay)
    roster = tuple(_roster_cells(data, constants))

    def neighborhood(horizontal, vertical):
        offsets = tuple(product(range(-horizontal, horizontal + 1), range(-horizontal, horizontal + 1),
                                range(-vertical, vertical + 1)))
        return {(x + dx, y + dy, z + dz, radius) for x, y, z, radius in roster for dx, dy, dz in offsets}

    candidates = neighborhood(9, 2)
    @cache
    def ray(x, y, z):
        return _vertical_ray_certificate(nodes, planes, x, y, z, meta["stackEntries"])

    @cache
    def feet_may_be_empty(x, y, z):
        high = x + CELL - 1, y + CELL - 1, z + CELL - 1
        return not _uniform_contents(nodes, planes, (x, y, z), high, solid=True)

    def midpoint_support(x, y, feet, radius):
        center = ray(x, y, feet)
        if center is None:
            return None
        corners = [ray(x + dx, y + dy, feet) for dx, dy in product((-radius, radius), repeat=2)]
        if any(result is None for result in corners):
            return None
        return tuple(map(max, zip(center, *corners, strict=True)))

    rows = defaultdict(list)
    bounds = {}
    midpoint_cells = set()
    relative_support = _relative_support(nodes, planes, meta["stackEntries"])
    for x, y, z, radius in candidates:
        px, py, feet = x * CELL, y * CELL, z * CELL
        # Spend the lookup budget on cells where an actor can stand above ground.
        # Other cells keep the ordinary five probes, including fully embedded footprints.
        if not feet_may_be_empty(px, py, feet):
            continue
        limits = midpoint_support(px, py, feet, radius)
        if limits is not None:
            rows[z, radius, y].append(x)
            bounds[x, y, z, radius] = limits
            midpoint_cells.add((x, y, z, radius))
            continue
        limits = relative_support(px, py, feet, radius)
        if limits is not None:
            bounds[x, y, z, radius] = limits

    vertical = defaultdict(list)
    for (z, radius, y), columns in rows.items():
        for left, right in _runs(columns):
            vertical[z, radius, left, right].append(y)
    boxes = [(z, radius, left, right, top, bottom)
             for (z, radius, left, right), vertical_rows in vertical.items()
             for top, bottom in _runs(vertical_rows)]
    boxes.sort(key=lambda box: (-(box[3] - box[2] + 1) * (box[5] - box[4] + 1), box))
    original = boxes[:ROW_BUDGET]
    local_boxes = _coverage_rectangles(bounds, original)
    # The larger area uses the cheaper midpoint proof. Its selection and
    # the local center-relative selection depend only on static map inputs.
    for x, y, z, radius in neighborhood(36, 8) - candidates:
        px, py, feet = x * CELL, y * CELL, z * CELL
        if feet_may_be_empty(px, py, feet):
            limits = midpoint_support(px, py, feet, radius)
            if limits is not None:
                midpoint_cells.add((x, y, z, radius))
                bounds[x, y, z, radius] = limits
    wide_boxes = _coverage_rectangles(midpoint_cells, original, WIDE_ROWS)
    constituents = local_boxes + wide_boxes
    union = set().union(*map(_rectangle_cells, constituents))
    # The constituents themselves always cover the exact union within their
    # combined row count, even if greedy recompression cannot improve it.
    selected = _coverage_rectangles(union, constituents, len(constituents))
    if not selected:
        raise ValueError("no E1M1 footing cells admitted")

    x_min, x_max = min(box[2] for box in selected), max(box[3] for box in selected)
    y_min, y_max = min(box[4] for box in selected), max(box[5] for box in selected)
    z_min, z_max = min(box[0] for box in selected), max(box[0] for box in selected)
    nx, ny, nz = x_max - x_min + 1, y_max - y_min + 1, z_max - z_min + 1
    if max(nx, ny, nz) > 256:
        raise ValueError("footing cell coordinates exceed byte indexes")
    records = bytearray()
    directory = []
    covered = set().union(*map(_rectangle_cells, selected))
    max_visits = max(bounds[cell][0] for cell in covered)
    max_stack = max(bounds[cell][1] for cell in covered)
    for radius, z in product(RADII, range(z_min, z_max + 1)):
        directory.append(len(records))
        for _, _, left, right, top, bottom in sorted(box for box in selected if box[:2] == (z, radius)):
            records.extend((left - x_min, right - x_min, top - y_min, bottom - y_min))
    directory.append(len(records))
    index = pack(f"<{len(directory)}H", *directory)
    if len(index) + len(records) > 0x8000:
        raise ValueError("footing table exceeds a single mapped upper-ROM bank")
    return index + records, {
        "PLAYABLE_SHOT_SUPPORT_MIN_X": x_min * CELL & 0xFFFF,
        "PLAYABLE_SHOT_SUPPORT_MIN_Y": y_min * CELL & 0xFFFF,
        "PLAYABLE_SHOT_SUPPORT_MIN_Z": z_min * CELL & 0xFFFF,
        "PLAYABLE_SHOT_SUPPORT_SPAN_X": nx * CELL,
        "PLAYABLE_SHOT_SUPPORT_SPAN_Y": ny * CELL,
        "PLAYABLE_SHOT_SUPPORT_SPAN_Z": nz * CELL,
        "PLAYABLE_SHOT_SUPPORT_HEIGHTS": nz,
        "PLAYABLE_SHOT_SUPPORT_DIRECTORY_BYTES": len(index),
        "PLAYABLE_SHOT_SUPPORT_BYTES": len(index) + len(records),
        "PLAYABLE_SHOT_SUPPORT_MAX_VISITS": max_visits,
        "PLAYABLE_SHOT_SUPPORT_MAX_STACK": max_stack,
        "PLAYABLE_SHOT_SUPPORT_CELLS": len(covered),
    }
