"""Stage inline static axial thresholds for playable walk hulls."""

from hashlib import sha256
import json
from itertools import accumulate, product
from math import floor
from struct import iter_unpack, pack, pack_into, unpack_from

from snes_tooling.quake.quake_playable_footing import build_e1m1_footing
from snes_tooling.quake.quake_playable_relocation import integer_definitions
from snes_tooling.quake.quake_point_tail_certificate import build_table as point_tail_table, pack_column_masks
from snes_tooling.quake.quake_walk_hull import (
    AXIAL_MOVER_FLAG, E1M1_EXIT_MOVER_AXES, E1M1_EXIT_MOVER_SWEEPS, ENTRANCE_POINT_TERMINAL,
    EXIT_MOVER_OWNER, EXIT_MOVER_TRANSLATION_BOUND, EXIT_POINT_TERMINALS,
    MOVER_TRANSLATION_BOUND, ORDINARY_SHOOT_TRIGGER_MODEL, SECRET_MODELS,
    SECRET_SELECTOR_BASE, SECRET_SHOOT_TRIGGER_MODEL, SECRET_TERMINAL_BASE, secret_axis_translation_bounds,
    static_plane_offset,
)

INLINE_WALK_MAPS = ("start", "e1m1", "e1m2", "e1m3")
COMPACT_POINT_MAPS = ("e1m4",)
MOVING_AXIAL_NODE = 0xC000
STATIC_HULL_MOVING_AXIAL_NODE = 0xE000
EXIT_TAIL_GUARD = 0xFFF8
POINT_MOVER_TAIL_GUARD = 0xFFF0


def _exit_tail_bounds(payload, meta, plane_start):
    """Bound every packed solid path by its axial XY constraints and mover travel."""
    ranges = {row["model"]: row for row in meta["modelRanges"]}
    boxes = []
    scale = 1 << meta["positionFractionBits"]
    for model, (axis, delta_min, delta_max) in E1M1_EXIT_MOVER_SWEEPS.items():
        row = ranges[model]
        sequence = meta["modelIds"]
        pos = sequence.index(model)
        following = sequence[pos + 1:pos + 2]
        empty = ranges[following[0]]["root"] if following else 0xFFFF
        solid = (EXIT_POINT_TERMINALS[model] & 0xFFFF
                 if meta["positionFractionBits"] == 3 else 0xFFFE)
        pending = [(row["root"], (-32768, -32768), (32767, 32767))]
        minimum, maximum = [32768, 32768], [-32769, -32769]
        while pending:
            node, low, high = pending.pop()
            if node == empty or any(a > b for a, b in zip(low, high, strict=True)):
                continue
            if node == solid:
                for coordinate in range(2):
                    minimum[coordinate] = min(minimum[coordinate], low[coordinate])
                    maximum[coordinate] = max(maximum[coordinate], high[coordinate])
                continue
            if not row["nodeBegin"] <= node < row["nodeEnd"] or node % 6:
                raise ValueError("exit hull bound encountered an invalid node")
            reference, front, back = unpack_from("<3H", payload, node)
            tag = reference >> 13
            front_low, back_high = list(low), list(high)
            if tag in (3, 4):
                distance, = unpack_from("<i", payload, plane_start + (reference & 0x1FF8) + 4)
                front_low[tag - 3] = max(front_low[tag - 3], distance)
                back_high[tag - 3] = min(back_high[tag - 3], distance - 1)
            pending.extend(((front, tuple(front_low), high), (back, low, tuple(back_high))))
        # The four vertical relay lamps use bevels for every horizontal point
        # plane. Their padded stock model bounds still limit the solid region.
        if "pointBoundsXY" in row and -32768 in minimum:
            lower, upper = row["pointBoundsXY"]
            minimum = [max(a, b) for a, b in zip(minimum, lower, strict=True)]
            maximum = [min(a, b) for a, b in zip(maximum, upper, strict=True)]
        if minimum[1] in (-32768, 32768):
            raise ValueError("packed exit mover must have a finite lower Y bound")
        if axis < 2 and minimum[axis] > -32768:
            minimum[axis] = max(-32768, minimum[axis] + delta_min * scale)
        if axis < 2 and maximum[axis] < 32767:
            maximum[axis] = min(32767, maximum[axis] + delta_max * scale)
        boxes.append((minimum, maximum))
    bounds = bytearray()
    step = 128 * scale
    for raw in range(0, 65536, step):
        y = raw if raw < 32768 else raw - 65536
        low_x, high_x = 32767, -32768
        for minimum, maximum in boxes:
            if minimum[1] <= y + step - 1 and maximum[1] >= y:
                low_x = min(low_x, minimum[0])
                high_x = max(high_x, maximum[0])
        bounds.extend(pack("<2H", (low_x & 0xFFFF) ^ 0x7FFF, (high_x & 0xFFFF) ^ 0x7FFF))
    return min(low[1] for low, _ in boxes), ranges[next(iter(E1M1_EXIT_MOVER_AXES))]["root"], bytes(bounds)


def _secret_tail_bounds(payload, meta, plane_start, secret_doors):
    """Prove whole-ray misses and bound omitted visits for the axial tail."""
    bits = meta["positionFractionBits"]
    models = SECRET_MODELS
    if bits == 3:
        models += (SECRET_SHOOT_TRIGGER_MODEL, ORDINARY_SHOOT_TRIGGER_MODEL)
    rows = meta["modelRanges"][-len(models):]
    if (tuple(row["model"] for row in rows) != models
            or tuple(door["inlineModel"] for door in secret_doors) != SECRET_MODELS):
        raise ValueError("secret trace tail and mover data disagree")
    travel = {door["inlineModel"]: door["legs"] for door in secret_doors}
    boxes = []
    for index, row in enumerate(rows):
        legs = travel.get(row["model"], ())
        miss = rows[index + 1]["root"] if index + 1 < len(rows) else 0xFFFF
        hit = (SECRET_TERMINAL_BASE - index) & 0xFFFF if bits == 3 else 0xFFFE
        node = row["root"]
        if row["nodeEnd"] - row["nodeBegin"] != 6 * 6:
            raise ValueError("secret trace tail requires a six-node brush")
        lower, upper = [-32768] * 3, [32767] * 3
        planes = []
        for _ in range(6):
            if node % 6 or not row["nodeBegin"] <= node < row["nodeEnd"]:
                raise ValueError("secret trace tail continuation escaped its brush")
            reference, front, back = unpack_from("<3H", payload, node)
            axis = (reference >> 13) - 3
            moving = index < len(SECRET_MODELS) and axis < 2
            if not 0 <= axis < 3 or reference & 7 != (EXIT_MOVER_OWNER if moving else 0):
                raise ValueError("secret trace tail requires authored axial planes")
            if (front == miss) == (back == miss):
                raise ValueError("secret trace tail must have one miss child")
            plane = reference & 0x1FF8
            if not row["planeBegin"] <= plane < row["planeEnd"]:
                raise ValueError("secret trace tail plane escaped its brush")
            selector = plane_start + meta["exitPlaneTable"] + (plane - meta["exitPlaneFirst"]) // 8
            expected = SECRET_SELECTOR_BASE + 2 * index + axis if moving else 255
            if not 0 <= selector < len(payload) or payload[selector] != expected:
                raise ValueError("secret trace tail plane selects an unexpected mover")
            distance, = unpack_from("<i", payload, plane_start + plane + 4)
            low, high = secret_axis_translation_bounds(legs, axis, bits)
            lo, hi = distance + low, distance + high
            if not -32768 <= lo <= hi <= 32767:
                raise ValueError("secret trace tail threshold does not fit a signed word")
            continuing_front = back == miss
            planes.append((axis, lo, hi, continuing_front))
            if continuing_front:
                lower[axis] = max(lower[axis], lo)
            else:
                upper[axis] = min(upper[axis], hi - 1)
            node = front if continuing_front else back
        if node != hit:
            raise ValueError("secret trace tail has an unexpected hit leaf")
        boxes.append((lower, upper, planes))

    table = bytearray()
    first_debt = more_debt = 0
    band = 256 << bits
    for raw_y in range(0, 65536, band):
        y0 = raw_y if raw_y < 32768 else raw_y - 65536
        y1 = y0 + band - 1
        active = [(lo[0], hi[0]) for lo, hi, _ in boxes if lo[1] <= y1 and y0 <= hi[1]]
        x0 = min((lo for lo, _ in active), default=32767)
        x1 = max((hi for _, hi in active), default=-32768)
        table.extend(pack("<2H", (x0 & 0xFFFF) ^ 0x7FFF, (x1 & 0xFFFF) ^ 0x7FFF))
        for xlo, xhi in ((-32768, x0 - 1), (x1 + 1, 32767)):
            if xlo > xhi:
                continue
            domain_lo, domain_hi = (xlo, y0, -32768), (xhi, y1, 32767)
            work = splits = per_entry = 0
            for _, _, planes in boxes:
                preceding_splits = 0
                for depth, (axis, lo, hi, continuing_front) in enumerate(planes, 1):
                    if (continuing_front and domain_hi[axis] < lo
                            or not continuing_front and domain_lo[axis] >= hi):
                        break
                    if domain_lo[axis] < hi and domain_hi[axis] >= lo:
                        preceding_splits += 1
                else:
                    raise ValueError("secret trace tail certificate lacks a rejecting plane")
                # Each fixed split point belongs to at most one of the ray's
                # disjoint (lo, hi] intervals, even across repeated entries.
                work += depth * (1 + splits)
                per_entry += depth
                splits += preceding_splits
            # The shortcut retains one EMPTY visit for each entry.
            first_debt = max(first_debt, work + splits)
            more_debt = max(more_debt, per_entry)
    return bytes(table), first_debt, more_debt, 6 * len(models)


def derive_inline_walk_hull(payload, meta, *, shot_size=None, compact_point=False,
                            secret_doors=None, point_mover_tail=False, live_exit_axial=True):
    nodes, planes = meta["nodes"], meta["planes"]
    plane_start = nodes * 6
    third_start = plane_start + planes * 8
    moving = (meta["schema"] in ("quake-e1m1-walk-hull-v1", "quake-e1m1-shot-hull-v1")
              and meta.get("entranceOwnerMask") == 6)
    static_fraction = {"quake-basic-walk-hull-v1": 4, "quake-basic-shot-hull-v1": 3}
    static = (meta["schema"] in static_fraction
              and meta["positionFractionBits"] == static_fraction[meta["schema"]]
              and meta.get("moverPolicy") == "authored-static"
              and meta.get("thirdCoefficientOffset") == third_start)
    exit_movers = meta.get("exitMoverModels", [])
    axial_movers = meta.get("axialMoverModels", [])
    moving_bevels = {offset for offset, _, _ in meta.get("movingBevelPlanes", [])}
    exit_first = meta.get("exitPlaneFirst", planes * 8)
    if exit_movers and (not moving or tuple(exit_movers) != tuple(E1M1_EXIT_MOVER_AXES)
                        or not 0 <= exit_first < planes * 8 or exit_first % 8
                        or meta.get("exitPlaneTable") != planes * 8):
        raise ValueError("inline walk hull requires the stock E1M1 exit mover selectors")
    if point_mover_tail and not (exit_movers and secret_doors
                                 and meta["schema"] == "quake-e1m1-shot-hull-v1"):
        raise ValueError("point mover tail requires the authored Q3 E1M1 mover hull")
    selector_bytes = (planes * 8 - exit_first) // 8 + 1 if exit_movers else 0
    if (not (moving or static)
            or not 0 < nodes * 8 < 0x8000
            or not 0 < planes <= (2048 if static else 1024)
            or len(payload) != third_start + (planes * 2 if static else selector_bytes)
            or len(payload) != meta["bytes"]
            or sha256(payload).hexdigest() != meta["sha256"]):
        raise ValueError("inline walk hull requires a checked source hull")
    if compact_point and (not static or meta["positionFractionBits"] != 3 or axial_movers or exit_movers):
        raise ValueError("compact point hull needs static Q3 geometry")

    raw_nodes = tuple(iter_unpack("<3H", payload[:plane_start]))
    if compact_point:
        # Only axial traversals read the immediate threshold at offset six.
        offsets = tuple(accumulate((8 if 3 <= ref >> 13 <= 5 else 6 for ref, _, _ in raw_nodes),
                                   initial=0))
    else:
        offsets = range(0, (nodes+1)*8, 8)

    terminals = {0xfffe, 0xffff}
    if meta["schema"] == "quake-e1m1-shot-hull-v1":
        terminals.update((SECRET_TERMINAL_BASE - index) & 0xffff for index in range(len(SECRET_MODELS) + 2))
        terminals.update(EXIT_POINT_TERMINALS.get(model, ENTRANCE_POINT_TERMINAL.get(model, -model)) & 0xffff
                         for model in meta["modelIds"] if model)

    def offset(child):
        if child in terminals:
            return child
        index, remainder = divmod(child, 6)
        if not 0 <= index < nodes or remainder:
            raise ValueError("inline walk hull child is outside its node table")
        return offsets[index]

    root = offset(meta["roots"][0])
    if root >= 0x8000:
        raise ValueError("inline walk hull requires a node root")
    records = bytearray()
    exit_axial_fields = {}
    secret_axes = 2 * len(SECRET_MODELS)
    other_plane_users = set()
    oblique_bound = moving and bool(exit_movers)
    translation_limit = max(EXIT_MOVER_TRANSLATION_BOUND, MOVER_TRANSLATION_BOUND) * (1 << meta["positionFractionBits"])
    for reference, front, back in raw_nodes:
        if exit_movers and reference in (EXIT_TAIL_GUARD, POINT_MOVER_TAIL_GUARD):
            raise ValueError("exit tail guard conflicts with a packed hull plane")
        tag = reference >> 13
        plane = static_plane_offset(reference) if static else reference & 0x1ff8
        owner = reference & (AXIAL_MOVER_FLAG if static else 7)
        if exit_movers and (owner != EXIT_MOVER_OWNER or tag < 3):
            other_plane_users.add(plane)
        if static and owner == AXIAL_MOVER_FLAG and axial_movers:
            if tag < 3:
                if plane not in moving_bevels:
                    raise ValueError("static hull has an invalid moving bevel reference")
            else:
                mover, = unpack_from("<H", payload, plane_start + plane)
                if not 1 <= mover <= meta.get("axialMoverOffsetCount", len(axial_movers)) or not 3 <= tag <= 5:
                    raise ValueError("static hull has an invalid axial mover reference")
        elif owner == EXIT_MOVER_OWNER and exit_movers and exit_first <= plane < planes * 8:
            selector = payload[third_start + (plane - exit_first) // 8]
            secret_xy = (SECRET_SELECTOR_BASE <= selector < SECRET_SELECTOR_BASE + secret_axes
                         and tag == 3 + (selector & 1))
            if not secret_xy and (selector // 4 >= len(exit_movers) or selector % 4 not in ((0,) if tag >= 3 else (1, 2))):
                raise ValueError("inline walk hull has an invalid exit translation selector")
            if tag >= 3:
                if tag > 5:
                    raise ValueError("exit axial selector must have a static axis tag")
                live_word = (selector - SECRET_SELECTOR_BASE if secret_xy
                             else secret_axes + selector // 4)
                fields = (2 * live_word, 2 * (tag - 3))
                if exit_axial_fields.setdefault(plane, fields) != fields:
                    raise ValueError("exit axial plane has conflicting live displacement fields")
        elif plane >= planes * 8 or (static and (owner or tag == 7)) or (moving and owner not in (0, 2, 4)):
            raise ValueError("inline walk hull encountered an invalid plane reference")
        if oblique_bound and tag < 3:
            a, b, distance = unpack_from("<hhi", payload, plane_start + plane)
            l1 = abs(a) + abs(b)
            # One owned translation can change an axis by this raw coordinate bound.
            oblique_bound = l1 <= 0x6000 and (
                l1 * (32768 + translation_limit) + abs(distance) < 2**31
            )
        threshold = 0
        if static and owner == AXIAL_MOVER_FLAG and tag >= 3:
            threshold, reference = reference, STATIC_HULL_MOVING_AXIAL_NODE
        elif exit_movers and (tag >= 6 or 3 <= tag <= 5 and owner):
            # Route moving axial nodes through the cold decoder. Static axial
            # nodes can then branch on the tag without testing ownership.
            threshold = reference
            reference = MOVING_AXIAL_NODE
        elif 3 <= tag <= 5 and not owner:
            distance, = unpack_from("<i", payload, plane_start + plane + 4)
            if not -32768 <= distance <= 32767:
                raise ValueError("inline hull axial distance exceeds a signed word")
            threshold = (distance & 0xffff) ^ 0x7fff
        records.extend(pack("<3H", reference, offset(front), offset(back)))
        if not compact_point or 3 <= tag <= 5:
            records.extend(pack("<H", threshold))
    extras = {}
    trailing = b""
    if exit_movers:
        lower, original, bounds = _exit_tail_bounds(payload, meta, plane_start)
        guard = offset(original)
        if not -32768 < lower <= 32767 or len(records) >= 0x8000:
            raise ValueError("exit tail guard exceeds the inline hull range")
        clone = len(records)
        records.extend(records[guard:guard + 8])
        tail = next((offset(row["root"]) for row in meta["modelRanges"] if row["model"] == SECRET_MODELS[0]), 0xffff)
        records[guard:guard + 8] = pack("<4H", EXIT_TAIL_GUARD, clone, tail, (lower & 0xFFFF) ^ 0x7FFF)
        if point_mover_tail:
            first_mover = meta["modelRanges"][1]
            if first_mover["model"] != 3 or len(records) >= 0x8000:
                raise ValueError("point mover tail has no valid first brush entry")
            entry = offset(first_mover["root"])
            clone = len(records)
            records.extend(records[entry:entry + 8])
            records[entry:entry + 8] = pack("<4H", POINT_MOVER_TAIL_GUARD, clone, 0xFFFF, 0)
            extras["PLAYABLE_WALK_HULL_MOVER_TAIL_GUARD"] = POINT_MOVER_TAIL_GUARD
        extras.update(PLAYABLE_WALK_HULL_EXIT_GUARD=EXIT_TAIL_GUARD,
                      PLAYABLE_WALK_HULL_EXIT_BOUNDS=len(records) + len(payload) - plane_start)
        trailing = bounds
        if meta["positionFractionBits"] == 3:
            extras["PLAYABLE_WALK_HULL_FOOT_FRACTION"] = extras["PLAYABLE_WALK_HULL_EXIT_BOUNDS"] + len(bounds)
            trailing += b"".join(pack("<H", i * 4096 // 288) for i in range(288))
        if secret_doors is not None:
            bounds, first, more, stack = _secret_tail_bounds(payload, meta, plane_start, secret_doors)
            extras.update(PLAYABLE_WALK_HULL_SECRET_BOUNDS=len(records) + len(payload) - plane_start + len(trailing),
                          PLAYABLE_WALK_HULL_SECRET_FIRST_DEBT=first,
                          PLAYABLE_WALK_HULL_SECRET_MORE_DEBT=more,
                          PLAYABLE_WALK_HULL_SECRET_STACK_ENTRIES=stack)
            trailing += bounds
    plane_data = payload[plane_start:]
    if exit_movers and live_exit_axial:
        if not exit_axial_fields or other_plane_users.intersection(exit_axial_fields):
            raise ValueError("exit axial selector shares a plane with a coefficient reader")
        plane_data = bytearray(plane_data)
        for plane, fields in exit_axial_fields.items():
            if plane_data[plane:plane + 4] != b"\0" * 4:
                raise ValueError("exit axial selector requires unused coefficient words")
            pack_into("<HH", plane_data, plane, *fields)
        extras["PLAYABLE_WALK_HULL_LIVE_EXIT_AXIAL"] = secret_axes
    derived = bytes(records) + plane_data + trailing
    third = len(records) + planes * 8
    constants = dict(PLAYABLE_WALK_HULL_ROOT=root, PLAYABLE_WALK_HULL_PLANES=len(records),
                     PLAYABLE_WALK_HULL_THIRD=third, PLAYABLE_WALK_HULL_BYTES=len(derived))
    constants.update(extras)
    if oblique_bound:
        constants["PLAYABLE_WALK_HULL_OBLIQUE_BOUND"] = 1
    if len(derived) > 0x8000:
        # Keep the node/plane hot path in its halfbank. The shot hull's
        # spare space can hold the walk-only third coefficients.
        if moving or shot_size is None or third > 0x8000 or shot_size + len(derived) - third > 0x8000:
            raise ValueError("inline walk hull cannot fit the walk and shot halfbanks")
        constants["PLAYABLE_WALK_HULL_SPLIT_THIRD"] = 1
    return derived, constants


def inline_e1m1_shot_moving_ranks(payload, constants):
    """Bind exact live exit axial ranks to unused packed node tag bits."""
    plane_start = constants["PLAYABLE_WALK_HULL_PLANES"]
    if plane_start % 8 or not constants.get("PLAYABLE_WALK_HULL_EXIT_GUARD"):
        raise ValueError("moving ranks require the packed E1M1 point hull")
    bound = max(EXIT_MOVER_TRANSLATION_BOUND, MOVER_TRANSLATION_BOUND) * 8
    # The two platforms and hydraulic door temporarily publish candidate
    # offsets during nested Q4 rider sweeps. Keep their original decoder.
    optional_live_slots = range(0, 64, 2)
    temporary_slots = (44, 46, 48)
    nodes = []
    for node, (tag, _, _, reference) in enumerate(iter_unpack("<4H", payload[:plane_start])):
        if tag != MOVING_AXIAL_NODE or reference & 7 != EXIT_MOVER_OWNER:
            continue
        plane = plane_start + (reference & 0x1ff8)
        slot, axis, distance = unpack_from("<HHi", payload, plane)
        if (slot not in optional_live_slots or axis not in (0, 2, 4)
                or reference >> 13 != 3 + axis // 2 or not -32768 + bound <= distance <= 32767 - bound):
            raise ValueError("invalid E1M1 moving axial rank")
        if slot not in temporary_slots:
            nodes.append((node, slot, axis, distance))
    keys = sorted({(slot, distance) for _, slot, _, distance in nodes})
    if not 0 < len(keys) <= 64:
        raise ValueError("E1M1 moving axial ranks exceed the WRAM allocation")
    ids = {key: index * 2 for index, key in enumerate(keys)}
    packed = bytearray(payload)
    for node, slot, axis, distance in nodes:
        tag = 0xc100 + axis * 128 + ids[slot, distance]
        pack_into("<H", packed, node * 8, tag)
    rows = b"".join(pack("<H", slot) for slot, _ in keys)
    rows += b"".join(pack("<h", distance) for _, distance in keys)
    return bytes(packed), rows


def _order_e1m1_inline_nodes(payload, constants, order):
    plane_start = constants["PLAYABLE_WALK_HULL_PLANES"]
    if (not 0 < plane_start < 0x8000 or plane_start % 8
            or "PLAYABLE_WALK_HULL_EXIT_GUARD" not in constants):
        raise ValueError("axis ranges require an inline E1M1 exit hull")
    groups = {axis: [] for axis in order}
    for offset in range(0, plane_start, 8):
        tag, front, back, threshold = unpack_from("<4H", payload, offset)
        axis = tag >> 13
        group = axis if axis in groups and not tag & 7 else None
        groups[group].append((offset, tag, front, back, threshold))
    if not all(groups.values()):
        raise ValueError("E1M1 inline hull is missing a dispatch group")
    ordered = [row for group in groups.values() for row in group]
    offsets = {row[0]: 8 * index for index, row in enumerate(ordered)}
    ends = dict(zip(order, accumulate(8 * len(group) for group in groups.values()), strict=True))

    def retarget(node):
        if node >= 0x8000:
            return node
        if node not in offsets:
            raise ValueError("E1M1 inline hull child is not a node")
        return offsets[node]

    # Guard and mover tags and both guard children follow the same rules as
    # ordinary nodes. Negative terminal handles retain their exact identity.
    nodes = b"".join(pack("<4H", tag, retarget(front), retarget(back), threshold)
                     for _, tag, front, back, threshold in ordered)
    return nodes + payload[plane_start:], offsets, ends


def order_e1m1_shot_axes(payload, constants, *, z_only=False):
    """Group static point planes by axis before the oblique and moving nodes."""
    order = (5, None) if z_only else (5, 3, 4, None)
    result, offsets, ends = _order_e1m1_inline_nodes(payload, constants, order)
    return result, {
        **constants,
        "PLAYABLE_WALK_HULL_ROOT": offsets[constants["PLAYABLE_WALK_HULL_ROOT"]],
        **{f"PLAYABLE_WALK_HULL_STATIC_{name}_END": ends[axis]
           for axis, name in ((5, "Z"), (3, "X"), (4, "Y")) if axis in ends},
    }


def order_e1m1_walk_axes(payload, constants, meta):
    """Group player hull nodes by static axis and retarget external entries."""
    result, offsets, ends = _order_e1m1_inline_nodes(payload, constants, (None, 3, 5, 4))

    def packed_node(offset):
        index, remainder = divmod(offset, 6)
        if remainder or index * 8 not in offsets:
            raise ValueError("authored player hull entry does not name a node")
        return offsets[index * 8]

    constants = {
        **constants,
        "PLAYABLE_WALK_HULL_ROOT": offsets[constants["PLAYABLE_WALK_HULL_ROOT"]],
        "PLAYABLE_WALK_HULL_AXIS_COLD_END": ends[None],
        "PLAYABLE_WALK_HULL_AXIS_X_END": ends[3],
        "PLAYABLE_WALK_HULL_AXIS_Z_END": ends[5],
        "PLAYABLE_WALK_HULL_EXPLOBOX_ROOT": packed_node(meta["exploboxRoot"]),
    }
    ranges = {row["model"]: row for row in meta["modelRanges"]}
    for leaf, model in enumerate((1, 2)):
        row = ranges[model]
        begin, end = row["nodeBegin"], row["nodeEnd"]
        retained = [packed_node(node) for node in range(begin, end, 6)]
        if (row["owner"] != 2 * (leaf + 1) or not retained or (end - begin) % 6
                or retained != list(range(retained[0], retained[-1] + 8, 8))
                or retained[-1] >= ends[None] or not begin <= row["root"] < end):
            raise ValueError("authored entrance nodes need a contiguous cold hull range")
        prefix = f"PLAYABLE_WALK_HULL_ENTRANCE_{leaf}_"
        constants.update({
            prefix + "NODE_BEGIN": retained[0], prefix + "NODE_END": retained[-1] + 8,
            prefix + "ROOT": packed_node(row["root"]),
        })
    return result, constants


def _static_hull_prefix(packed, plane_start, node, visits, low, high, *, owner_mask):
    """Follow immutable planes that put an entire cell on one side."""
    axes = ((0, 1), (0, 2), (1, 2))
    while node < 0x8000 and visits > 1:
        if node % 8 or node >= plane_start:
            raise ValueError("hull resume grid encountered an invalid node")
        tag, front, back, threshold = unpack_from("<4H", packed, node)
        kind = tag >> 13
        if kind >= 6 or tag & owner_mask:
            break
        at = plane_start + (tag & 0x1ff8)
        ca, cb, distance = unpack_from("<hhi", packed, at)
        if kind >= 3:
            packed_distance = (threshold ^ 0xffff) - 0x8000
            if packed_distance != distance:
                raise ValueError("hull resume threshold differs from its plane")
            least = low[kind - 3] - packed_distance
            most = high[kind - 3] - packed_distance
        else:
            a, b = axes[kind]
            edge_a = sorted((ca * low[a], ca * high[a]))
            edge_b = sorted((cb * low[b], cb * high[b]))
            dot_low, dot_high = edge_a[0] + edge_b[0], edge_a[1] + edge_b[1]
            least, most = dot_low - distance, dot_high - distance
            if min(dot_low, least) < -(1 << 31) or max(dot_high, most) >= (1 << 31):
                break
        if least >= 0:
            node = front
        elif most < 0:
            node = back
        else:
            break
        visits -= 1
    return node, visits


def build_explobox_walk_resume(data):
    """Pack the Q4 cell indices and skipped visits for the E1M1 explobox hull."""
    meta = json.loads((data / "QuakeBSPWalkHull.json").read_bytes())
    if meta["schema"] != "quake-e1m1-walk-hull-v1" or meta["positionFractionBits"] != 4:
        raise ValueError("explobox resume grid requires the E1M1 Q4 walk hull")
    packed = (data / "PlayableWalkHull.bin").read_bytes()
    constants = integer_definitions((data / "PlayableWalkHull.i").read_text(encoding="ascii"))
    root = constants["PLAYABLE_WALK_HULL_EXPLOBOX_ROOT"]
    plane_start = constants["PLAYABLE_WALK_HULL_PLANES"]
    prefix_budget = 64
    cell = 256 * 16
    entries = {(root, 0): 0}
    indices = bytearray()
    for y, x, z in product(range(-7, 7), range(-5, 5), range(-2, 2)):
        low = (x * cell, y * cell, z * cell - 18 * 16)
        high = tuple((axis + 1) * cell - 1 for axis in (x, y, z))
        node, remaining = _static_hull_prefix(packed, plane_start, root, prefix_budget, low, high, owner_mask=7)
        if 0x8000 <= node < 0xfffe:
            raise ValueError("explobox resume grid reached an unsupported terminal")
        entry = node, prefix_budget - remaining
        index = entries.setdefault(entry, len(entries))
        if index > 255:
            raise ValueError("explobox resume grid exceeds byte indexes")
        indices.append(index)
    return bytes(indices) + b"".join(pack("<HH", *entry) for entry in entries)


def _shot_pair_resume(packed, constants, visits, *, depth=19):
    """Map cells with the same sufficiently deep immutable path to one record."""
    root = constants["PLAYABLE_WALK_HULL_ROOT"]
    planes = constants["PLAYABLE_WALK_HULL_PLANES"]
    width = 256 * 8
    axes = {"X": range(-5, 5), "Y": range(-7, 7), "Z": range(-2, 2)}
    if not 0 < depth < visits:
        raise ValueError("point prefix must leave a visit for its destination")
    cells, paths = bytearray(), {}
    for y, x, z in product(axes["Y"], axes["X"], axes["Z"]):
        low = (x * width, y * width, z * width)
        high = tuple(n + width - 1 for n in low)
        path = [root]
        offset = 0
        for _ in range(depth):
            node = path[-1]
            if node >= 0x8000:
                break
            child, remaining = _static_hull_prefix(packed, planes, node, 2, low, high, owner_mask=6)
            if remaining == 2:
                break
            front, back = unpack_from("<2H", packed, node + 2)
            if front == back:
                break
            path.append(child)
        else:
            offset = paths.setdefault(tuple(path), 2 * (len(paths) + 1))
            if offset > 255:
                raise ValueError("point-hull cell path exceeds byte offsets")
        cells.append(offset)

    # Zero names the fallback. A successful cell carries its destination's
    # byte offset directly so the CPU needs only two byte reads and a compare.
    nodes = (root, *(path[-1] for path in paths))
    payload = bytes(cells) + pack(f"<{len(nodes)}H", *nodes)
    prefix = "PLAYABLE_SHOT_PAIR_"
    return payload, {
        **{prefix + f"{axis}_MIN": bounds.start & 0xffff for axis, bounds in axes.items()},
        **{prefix + f"{axis}_CELLS": len(bounds) for axis, bounds in axes.items()},
        prefix + "CELL_BYTES": len(cells),
        prefix + "VISITS": visits - depth,
        prefix + "BYTES": len(payload),
    }


def _shot_resume_grid(packed, constants, geometry, shot_meta, *, mover_tail_inputs=None):
    """Prove single-child prefixes for complete 128-unit cells and vertical probes."""
    root = constants["PLAYABLE_WALK_HULL_ROOT"]
    plane_start = constants["PLAYABLE_WALK_HULL_PLANES"]
    world = geometry["world"]
    if geometry["source"]["bsp_sha256"] != shot_meta["bspSha256"] or shot_meta["positionFractionBits"] != 3:
        raise ValueError("point-hull resume grid requires matching Q3 stock BSP geometry")
    origin = world["quantization"]["origin"]
    bounds = world["source_bounds"]
    cell = 128
    probe = 36
    visit_limit = 4096
    # The point hull is rebased to the original eye minus the stock view height.
    eye = (*origin[:2], origin[2] - 22)
    lo = [floor((v - o - m) / cell) for v, o, m in zip(bounds["mins"], eye, (16, 16, 0), strict=True)]
    hi = [floor((v - o + m) / cell) for v, o, m in zip(bounds["maxs"], eye, (16, 16, probe), strict=True)]
    extent = [b - a + 1 for a, b in zip(lo, hi, strict=True)]
    if extent != [18, 28, 8] or any(not -32 <= a <= b < 32 for a, b in zip(lo, hi, strict=True)):
        raise ValueError("unsupported E1M1 point-hull resume grid bounds")

    scale = 8
    unique = {(root, visit_limit): 0}
    cells = bytearray()
    # X changes slower than Z. Each Y row contains 18 eight-byte columns.
    for y, x, z in product(range(lo[1], hi[1] + 1), range(lo[0], hi[0] + 1), range(lo[2], hi[2] + 1)):
        low = (x * cell * scale, y * cell * scale, (z * cell - probe) * scale)
        high = tuple((v + 1) * cell * scale - 1 for v in (x, y, z))
        entry = _static_hull_prefix(packed, plane_start, root, visit_limit, low, high, owner_mask=6)
        row = unique.setdefault(entry, len(unique))
        if row > 255:
            raise ValueError("point-hull resume dictionary exceeds byte indexes")
        cells.append(row)
    table = b"".join(pack("<HH", *entry) for entry in unique)
    # Many XY columns have identical vertical paths. Keep constant-time
    # lookup for every cell without growing the point-hull halfbank.
    columns = [bytes(cells[i:i + 8]) for i in range(0, len(cells), 8)]
    distinct = dict.fromkeys(columns)
    if len(distinct) > 256:
        raise ValueError("point-hull vertical-column dictionary exceeds byte indexes")
    ids = {column: i for i, column in enumerate(distinct)}
    column_ids = bytes(ids[column] for column in columns)
    folded = b"".join(distinct)
    if b"".join(folded[8*i:8*i + 8] for i in column_ids) != cells:
        raise ValueError("point-hull vertical-column expansion differs from proven cells")
    indices = column_ids + folded
    grid = indices + table
    mover_constants = {}
    if mover_tail_inputs is not None:
        raw_hull, brush_constants, gameplay = mover_tail_inputs
        masks, debts, count = point_tail_table(raw_hull, shot_meta, brush_constants, gameplay,
                                               lo, hi, cell * scale, probe * scale)
        mover_constants = {
            "PLAYABLE_SHOT_TAIL_MASK_OFFSET": len(grid),
            "PLAYABLE_SHOT_TAIL_MASK_BYTES": len(masks),
            "PLAYABLE_SHOT_TAIL_FIRST_DEBT": debts[0],
            "PLAYABLE_SHOT_TAIL_MORE_DEBT": debts[1],
            "PLAYABLE_SHOT_TAIL_STACK_ENTRIES": debts[2],
            "PLAYABLE_SHOT_TAIL_CERTIFIED_CELLS": count,
        }
        grid += masks
    return grid, {
        **{f"PLAYABLE_SHOT_RESUME_MIN_{axis}": value & 0xffff for axis, value in zip("XYZ", lo, strict=True)},
        "PLAYABLE_SHOT_RESUME_COLUMNS": len(column_ids),
        "PLAYABLE_SHOT_RESUME_INDEX_BYTES": len(indices),
        "PLAYABLE_SHOT_RESUME_DELTA": probe * scale,
        "PLAYABLE_SHOT_RESUME_VISITS": visit_limit,
        "PLAYABLE_SHOT_RESUME_BYTES": len(grid),
        **mover_constants,
    }


def _shot_oblique_bounds(packed, constants):
    """Build conservative same-side X limits for six hot E1M1 point planes."""
    # The authored point hull reuses these planes in the saved E1M1 tape.
    selected = ((0x2010, True), (0x0028, True), (0x0048, False),
                (0x0050, False), (0x20C0, False), (0x20F0, False))
    mask = 0x1ff8
    plane_start = constants["PLAYABLE_WALK_HULL_PLANES"]
    offsets = {ref & mask for ref, _ in selected}
    references = {offset: set() for offset in offsets}
    for ref, _, _, _ in iter_unpack("<4H", packed[:plane_start]):
        if ref & mask in references:
            references[ref & mask].add(ref)
    directory = bytearray(max(offsets) // 4 + 2)
    rows = bytearray()
    for ref, back in selected:
        offset = ref & mask
        ca, cb, distance = unpack_from("<hhi", packed, plane_start + offset)
        axis = ref >> 13
        if (references[offset] != {ref} or axis not in (0, 1) or ca <= 0 or not cb
                or (ca + abs(cb)) * 32768 + abs(distance) >= 1 << 31):
            raise ValueError("point oblique bounds require a unique, non-wrapping X plane")
        # In the register tracer from is the maximum signed value, and to
        # is the minimum. Both are reverse-biased as 32767 - coordinate.
        b_offset = 2 + 2 * axis
        if (cb > 0) != back:
            b_offset += 6
        pack_into("<H", directory, offset // 4, len(rows) | b_offset | int(back))
        for high in range(32767, -32768, -2048):
            low = high - 2047
            first = -((cb * low - distance) // ca)
            last = -((cb * high - distance) // ca)
            limit = 32768 + min(first, last) if back else 32768 - max(first, last)
            rows.extend(pack("<H", min(65535, max(0, limit))))
    return bytes(directory + rows), len(directory)


def inline_e1m1_shot_bounds(payload, constants):
    """Put static point-plane bounds descriptors in their unused node words."""
    if "PLAYABLE_WALK_HULL_STATIC_Z_END" not in constants:
        raise ValueError("inline point bounds require the fixed E1M1 point records")
    rows, directory_size = _shot_oblique_bounds(payload, constants)
    result = bytearray(payload)
    for node in range(0, constants["PLAYABLE_WALK_HULL_PLANES"], 8):
        reference, _, _, unused = unpack_from("<4H", payload, node)
        if reference >= 0x6000 or reference & 7:
            continue
        index = (reference & 0x1ff8) // 4
        if unused:
            raise ValueError("static point plane does not have a free threshold word")
        descriptor = unpack_from("<H", rows, index)[0] if index < directory_size else 0
        if not descriptor and reference < 0x2000:
            plane = constants["PLAYABLE_WALK_HULL_PLANES"] + (reference & 0x1ff8)
            ca, cb, distance = unpack_from("<hhi", payload, plane)
            if ca == 11585 and abs(cb) == ca:
                threshold = -((-distance) // ca)
                if -8192 <= threshold < 8192:
                    # The signed result fits both the original point-plane math
                    # and the checked add/subtract path in the runtime.
                    descriptor = 0x8000 | (0x4000 if cb < 0 else 0) | (threshold + 8192)
        pack_into("<H", result, node + 6, descriptor)
    constants = {**constants, "PLAYABLE_WALK_HULL_INLINE_BOUNDS": 1}
    return bytes(result), constants, rows, directory_size


def _e1m2_mover_plane_table(payload, meta, gameplay, fraction):
    """Prove the direct cache index and the signed threshold for every pose."""
    movers = gameplay["stockExitMachinery"]["movers"]
    if (meta["bspSha256"] != gameplay["bspSha256"]
            or meta["positionFractionBits"] != fraction
            or meta["axialMoverModels"] != [row["inlineModel"] for row in movers]):
        raise ValueError("E1M2 mover planes require the matching authored hull")
    plane_start = meta["nodes"] * 6
    if sha256(payload).hexdigest() != meta["sha256"]:
        raise ValueError("E1M2 mover planes require a verified hull payload")
    rows = [set() for _ in movers]
    for reference, _, _ in iter_unpack("<3H", payload[:plane_start]):
        if reference & AXIAL_MOVER_FLAG == 0:
            continue
        plane = static_plane_offset(reference)
        owner, _, distance = unpack_from("<Hhi", payload, plane_start + plane)
        if not (1 <= owner <= len(movers) and plane < 0x2000 and plane < meta["planes"] * 8):
            raise ValueError("E1M2 mover plane index exceeds its table")
        mover = movers[owner - 1]
        if reference >> 13 != mover["axis"] + 3 or not all(
            -32768 <= distance + delta <= 32767 for delta in mover[f"positionsQ{fraction}"]
        ):
            raise ValueError("E1M2 mover plane needs a wide distance")
        rows[owner - 1].add((plane, distance))
    if any(len(row) != 2 for row in rows):
        raise ValueError("E1M2 mover requires exactly two axial planes")
    first = min(plane for row in rows for plane, _ in row)
    last = max(plane for row in rows for plane, _ in row)
    payload = b"".join(pack("<Hh", (plane - first) // 4, distance)
                       for row in rows for plane, distance in sorted(row))
    return payload, first // 4, (last - first) // 4 + 2


def prepare_inline_walk_hull(example, *, check=False):
    data = example / "Data"
    payload = (data / "QuakeBSPWalkHull.bin").read_bytes()
    meta = json.loads((data / "QuakeBSPWalkHull.json").read_bytes())
    gameplay = {}
    if meta.get("axialMoverModels") or meta.get("exitMoverModels"):
        gameplay = json.loads((data / "QuakeBSPQuakeCGameplay.json").read_bytes())
    exit_machinery = gameplay.get("stockExitMachinery") or {}
    e1m2_movers = "silverKey" in exit_machinery
    secret_doors = exit_machinery.get("secretDoors")
    shot_source = data / "QuakeBSPShotHull.bin"
    shot_size = shot_source.stat().st_size
    outputs = {}
    shot_constants = None
    if meta["schema"] == "quake-e1m1-walk-hull-v1" or e1m2_movers:
        shot_meta = json.loads(shot_source.with_suffix(".json").read_bytes())
        shot_payload = shot_source.read_bytes()
        point_mover_tail = bool(shot_meta.get("exitMoverModels") and secret_doors)
        shot, shot_constants = derive_inline_walk_hull(shot_payload, shot_meta, secret_doors=secret_doors,
                                                        point_mover_tail=point_mover_tail)
        if shot_meta["schema"] == "quake-e1m1-shot-hull-v1" and shot_meta.get("exitMoverModels"):
            shot, shot_constants = order_e1m1_shot_axes(shot, shot_constants)
        outputs["PlayableShotHull.bin"] = shot
        shot_size = len(shot)
    walk, constants = derive_inline_walk_hull(
        payload, meta, shot_size=shot_size, secret_doors=secret_doors)
    if "PLAYABLE_WALK_HULL_EXIT_GUARD" in constants:
        walk, constants = order_e1m1_walk_axes(walk, constants, meta)
    outputs["PlayableWalkHull.bin"] = walk
    if shot_constants is not None:
        if shot_meta.get("exitMoverModels"):
            geometry = json.loads((data / "QuakeBSPMetadata.json").read_bytes())
            mover_inputs = None
            if point_mover_tail:
                brush_constants = integer_definitions((data / "QuakeBSPBrushAssets.i").read_text(encoding="ascii"))
                mover_inputs = (shot_payload, brush_constants, gameplay)
            grid, resume_constants = _shot_resume_grid(
                outputs["PlayableShotHull.bin"], shot_constants, geometry, shot_meta,
                mover_tail_inputs=mover_inputs)
            if point_mover_tail:
                mask_start = resume_constants.pop("PLAYABLE_SHOT_TAIL_MASK_OFFSET")
                packed, dictionary = pack_column_masks(grid[mask_start:])
                outputs["PlayableShotTailMask.bin"] = packed + dictionary
                if dictionary:
                    resume_constants["PLAYABLE_SHOT_TAIL_PACKED_BYTES"] = len(packed)
                    resume_constants["PLAYABLE_SHOT_TAIL_DICTIONARY_BYTES"] = len(dictionary)
                grid = grid[:mask_start]
                resume_constants["PLAYABLE_SHOT_RESUME_BYTES"] = len(grid)
            if len(outputs["PlayableShotHull.bin"]) + len(grid) > 0x8000:
                raise ValueError("point-hull resume grid exceeds its halfbank")
            outputs["PlayableShotResume.bin"] = grid
            constants.update(resume_constants)
            shot, shot_constants, bounds, directory_size = inline_e1m1_shot_bounds(shot, shot_constants)
            outputs["PlayableShotHull.bin"] = shot
            outputs["PlayableShotObliqueBounds.bin"] = bounds
            shot, rows = inline_e1m1_shot_moving_ranks(shot, shot_constants)
            outputs["PlayableShotHull.bin"] = shot
            outputs["PlayableShotMovingRanks.bin"] = rows
            pair, pair_constants = _shot_pair_resume(shot, shot_constants,
                                                     resume_constants["PLAYABLE_SHOT_RESUME_VISITS"])
            outputs["PlayableShotPair.bin"] = pair
            constants.update(pair_constants)
            constants["PLAYABLE_SHOT_MOVING_RANK_BYTES"] = len(rows)
            constants["PLAYABLE_SHOT_OBLIQUE_DIRECTORY_BYTES"] = directory_size
            constants["PLAYABLE_SHOT_OBLIQUE_BYTES"] = len(bounds)
            if secret_doors:
                support, support_constants = build_e1m1_footing(data, shot_payload, shot_meta)
                outputs["PlayableShotSupport.bin"] = support
                constants.update(support_constants)
        if shot_constants.pop("PLAYABLE_WALK_HULL_OBLIQUE_BOUND", 0):
            constants["PLAYABLE_POINT_OBLIQUE_BOUND"] = 1
        constants.update({name.replace("WALK", "SHOT"): value for name, value in shot_constants.items()})
    header = "".join(f"{name} = {value}\n" for name, value in constants.items()).encode("ascii")
    outputs["PlayableWalkHull.i"] = header
    if e1m2_movers:
        sizes = {}
        for name, fraction in (("Walk", 4), ("Shot", 3)):
            source = data / f"QuakeBSP{name}Hull.bin"
            source_meta = json.loads(source.with_suffix(".json").read_bytes())
            table, first, size = _e1m2_mover_plane_table(source.read_bytes(), source_meta, gameplay, fraction)
            outputs[f"PlayableE1M2Mover{name}.bin"] = table
            sizes[f"QC_E1M2_Q{fraction}_FIRST"] = first
            sizes[f"QC_E1M2_Q{fraction}_BYTES"] = size
        outputs["PlayableE1M2MoverPlanes.i"] = "".join(
            f"{name} = {value}\n" for name, value in sizes.items()).encode("ascii")
    _write_derived_hulls(data, outputs, check)


def prepare_compact_point_hull(example, *, check=False):
    data = example / "Data"
    source = data / "QuakeBSPShotHull.bin"
    metadata = json.loads(source.with_suffix(".json").read_bytes())
    payload, constants = derive_inline_walk_hull(source.read_bytes(), metadata, compact_point=True)
    header = "".join(f"{name.replace('WALK', 'SHOT')} = {value}\n"
                     for name, value in constants.items()).encode("ascii")
    _write_derived_hulls(data, {"PlayableShotHull.bin": payload, "PlayableShotHull.i": header}, check)


def _write_derived_hulls(data, outputs, check):
    for name, content in outputs.items():
        path = data / name
        if path.is_file() and path.read_bytes() == content:
            continue
        if check:
            raise ValueError(f"stale derived playable walk hull: {name}")
        path.write_bytes(content)
