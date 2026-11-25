"""Cartridge representation of world, lift/button and linked entrance hulls."""

from hashlib import sha256
import json
from pathlib import Path
from struct import iter_unpack, pack

from snes_tooling.quake.quake_bsp_assets import lump_data, lump_ranges

EMPTY = -1
SOLID = -2
NORMAL_SCALE = 1 << 14
NODE_BYTES = 6
PLANE_BYTES = 8
ENTRANCE_OWNER = {1: 2, 2: 4}
ENTRANCE_POINT_TERMINAL = {1: -5, 2: -6}
# Stock E1M1 route movers, in native pose-table order. Axis, minimum and
# maximum displacement are checked against the generated QuakeC stops.
E1M1_EXIT_MOVER_SWEEPS = {
    5: (0, -96, 0), 6: (0, 0, 94), 8: (1, -240, 0), 9: (1, -4, 0),
    25: (0, 0, 4), 26: (1, 0, 4), 27: (1, -4, 0), 29: (0, -136, 0),
    7: (2, -152, 0), 22: (2, -400, 0),
    15: (2, -66, 0), 17: (1, 0, 104), 19: (1, -4, 0),
    34: (2, -16, 0), 35: (2, -16, 0), 36: (2, -16, 0), 37: (2, -16, 0), 38: (1, -120, 0),
}
E1M1_EXIT_MOVER_AXES = {model: sweep[0] for model, sweep in E1M1_EXIT_MOVER_SWEEPS.items()}
EXIT_POINT_TERMINALS = {model: -32 - index for index, model in enumerate(E1M1_EXIT_MOVER_AXES)}
# Tags above the exit-team selectors name the two independent horizontal translations.
SECRET_MODELS = (10, 13, 14, 21, 23, 41, 43)
SECRET_SHOOT_TRIGGER_MODEL = 40
ORDINARY_SHOOT_TRIGGER_MODEL = 16
SECRET_SELECTOR_BASE = 128
SECRET_TERMINAL_BASE = -64
EXIT_MOVER_OWNER = 6
EXIT_MOVER_TRANSLATION_BOUND = max(max(-lo, hi) for _, lo, hi in E1M1_EXIT_MOVER_SWEEPS.values())
MOVER_TRANSLATION_BOUND = 232
PLANE_OFFSET_MASK = 0x1FF8
STATIC_PLANE_HIGH_BIT = 0x2000
AXIAL_MOVER_FLAG = 4


def secret_axis_translation_bounds(legs, axis, fraction_bits):
    """Conservatively quantize the complete authored secret-door sweep."""
    factor = 1 << (4 - fraction_bits)
    deltas = [leg["travelQ4"] for leg in legs if leg["axis"] == axis]
    low = sum(min(0, delta) for delta in deltas) // factor
    high = (sum(max(0, delta) for delta in deltas) + factor - 1) // factor
    return low, high


def static_plane_offset(reference):
    return (reference & PLANE_OFFSET_MASK) | ((reference & 2) << 12)


def static_plane_reference(offset):
    return (offset & PLANE_OFFSET_MASK) | ((offset & STATIC_PLANE_HIGH_BIT) >> 12)


def _hull(bsp, origin, *, point, static_models=None, exit_movers=False,
          axial_movers=(), moving_bevels=False, point_targets=(), explobox=None):
    lumps = lump_ranges(bsp)
    planes = tuple(iter_unpack("<4fi", lump_data(bsp, lumps, 1)))
    if point:
        contents = tuple(
            row[0] for row in iter_unpack("<ii6hHH4B", lump_data(bsp, lumps, 10))
        )

        def child_node(n):
            return n if n >= 0 else SOLID if contents[~n] == SOLID else EMPTY

        nodes = tuple(
            (plane, child_node(front), child_node(back))
            for plane, front, back, *_ in iter_unpack(
                "<ihh6hHH", lump_data(bsp, lumps, 5)
            )
        )
    else:
        nodes = tuple(iter_unpack("<ihh", lump_data(bsp, lumps, 9)))
    scale = 8 if point else 16
    models = tuple(iter_unpack("<9f7i", lump_data(bsp, lumps, 14)))
    eye_origin = (origin[0], origin[1], origin[2] - 22)
    all_nodes = []
    all_planes = []
    third_coefficients = []
    static_plane_offsets = {}
    roots = []
    depths = []
    plane_bases = []
    model_ids = (0, 3, 4, 1, 2) if static_models is None else tuple(static_models)
    if exit_movers:
        if static_models is not None:
            raise ValueError("E1M1 exit movers require the translated hull")
        model_ids += (*E1M1_EXIT_MOVER_AXES, *SECRET_MODELS)
        if point:
            model_ids += (SECRET_SHOOT_TRIGGER_MODEL, ORDINARY_SHOOT_TRIGGER_MODEL)
    exit_indices = {model: index for index, model in enumerate(E1M1_EXIT_MOVER_AXES)} if exit_movers else {}
    axial_owners = {
        model: {axis: index + 1 + lane * len(axial_movers)
                for lane, axis in enumerate(axes if isinstance(axes, tuple) else (axes,))}
        for index, (model, axes) in enumerate(axial_movers)
    }
    bevel_owners = {}
    exit_first_plane = None
    exit_selectors = bytearray()
    model_ranges = []
    following = dict(zip(model_ids, model_ids[1:]))
    roots_by_model = {}
    for model in model_ids:
        root = models[model][9 if point else 10]
        owner = ENTRANCE_OWNER.get(model, 0) if static_models is None else 0
        exit_index = exit_indices.get(model)
        secret_index = SECRET_MODELS.index(model) if exit_movers and model in SECRET_MODELS else None
        if exit_index is not None and exit_first_plane is None:
            exit_first_plane = len(all_planes) * PLANE_BYTES
        exit_axis = E1M1_EXIT_MOVER_AXES[model] if exit_index is not None else None
        node_begin = len(all_nodes) * NODE_BYTES
        depth = {}

        def visit(node):
            if node in (EMPTY, SOLID):
                return 0
            if not 0 <= node < len(nodes):
                raise ValueError("invalid player hull node or terminal")
            if node not in depth:
                _, front, back = nodes[node]
                depth[node] = 1 + max(visit(front), visit(back))
            return depth[node]

        depths.append(visit(root))
        if static_models is None and model in (3, 4) and not point and len(depth) != 6:
            raise ValueError("gameplay mover hull must have six axial planes")
        remap_nodes = {
            node: (len(all_nodes) + i) * NODE_BYTES
            for i, node in enumerate(sorted(depth))
        }
        roots.append(remap_nodes[root])
        roots_by_model[model] = remap_nodes[root]
        plane_ids = sorted({nodes[node][0] for node in depth})
        remap_planes = {}
        plane_bases.append(len(all_planes) * PLANE_BYTES)
        for plane_id in plane_ids:
            nx, ny, nz, distance, plane_type = planes[plane_id]
            normal = (nx, ny, nz)
            third_coefficient = 0
            exit_lane = None
            model_axes = axial_owners.get(model, {})
            axial_owner = model_axes.get(plane_type, 0)
            rebased = distance - sum(
                n * p for n, p in zip(normal, eye_origin, strict=True)
            )
            if plane_type < 3:
                if normal != tuple(int(i == plane_type) for i in range(3)):
                    raise ValueError("invalid axial player hull plane")
                tag = 3 + plane_type
                if static_models is None and model == 3 and plane_type == 2:
                    tag = 6
                if static_models is None and model == 4 and plane_type == 0:
                    tag = 7
                distance_fixed = round(rebased * scale)
                if plane_type == exit_axis:
                    exit_lane = 0
                # Translated door/button planes can move by up to 232 units.
                minimum = -32768 + (
                    MOVER_TRANSLATION_BOUND * scale if tag in (6, 7) else 0
                )
                maximum = 32767
                if owner and plane_type == 1:
                    minimum += MOVER_TRANSLATION_BOUND * scale
                    maximum -= MOVER_TRANSLATION_BOUND * scale
                if exit_lane is not None:
                    minimum += EXIT_MOVER_TRANSLATION_BOUND * scale
                    maximum -= EXIT_MOVER_TRANSLATION_BOUND * scale
                if not minimum <= distance_fixed <= maximum:
                    raise ValueError(
                        "axial hull distance overflows signed position word"
                    )
                plane = (axial_owner, 0, distance_fixed)
            else:
                if model in axial_owners and not moving_bevels:
                    raise ValueError(f"axial mover *{model} has an oblique collision plane")
                axes = tuple(i for i, n in enumerate(normal) if n)
                if (static_models is None and model in (3, 4)) or axes not in (
                    (0, 1),
                    (0, 2),
                    (1, 2),
                    *(((0, 1, 2),) if static_models is not None else ()),
                ):
                    raise ValueError("unsupported oblique player hull plane")
                tag = 6 if len(axes) == 3 else ((0, 1), (0, 2), (1, 2)).index(axes)
                coefficients = tuple(
                    round(normal[axis] * NORMAL_SCALE) for axis in axes
                )
                translated = tuple(axis for axis in axes if axis in model_axes)
                if translated:
                    if len(axes) != 2 or len(translated) > 1:
                        raise ValueError("moving bevel requires a two-axis BSP plane")
                    axial_axis, = translated
                    axial_owner = model_axes[axial_axis]
                rebased_q18 = round(rebased * scale * NORMAL_SCALE)
                translation_margin = (
                    abs(coefficients[axes.index(1)]) * MOVER_TRANSLATION_BOUND * scale
                    if owner and 1 in axes
                    else 0
                )
                if exit_axis in axes:
                    exit_lane = axes.index(exit_axis) + 1
                    translation_margin = abs(coefficients[exit_lane - 1]) * EXIT_MOVER_TRANSLATION_BOUND * scale
                if (
                    sum(abs(n) * 32768 for n in coefficients)
                    + abs(rebased_q18)
                    + translation_margin
                    >= 2**31
                ):
                    raise ValueError(
                        "player hull distance overflows signed 32-bit arithmetic"
                    )
                if len(coefficients) == 3:
                    third_coefficient = coefficients[2]
                plane = (*coefficients[:2], rebased_q18)
            bevel_owner = axial_owner if tag < 3 else 0
            key = (tag, *plane, third_coefficient, bevel_owner)
            offset = (
                static_plane_offsets.get(key) if static_models is not None else None
            )
            if offset is None:
                offset = len(all_planes) * PLANE_BYTES
                if offset >= (0x4000 if static_models is not None else 0x2000):
                    raise ValueError(
                        "player hull plane offset exhausts its packed field"
                    )
                all_planes.append(plane)
                third_coefficients.append(third_coefficient)
                static_plane_offsets[key] = offset
            if bevel_owner:
                bevel_owners[offset] = (bevel_owner - 1, coefficients[axes.index(axial_axis)])
            packed_offset = static_plane_reference(offset) if static_models is not None else offset
            plane_owner = AXIAL_MOVER_FLAG if axial_owner else owner
            if secret_index is not None:
                if plane_type > 2:
                    raise ValueError("E1M1 secret panel has a nonaxial collision plane")
                selector = SECRET_SELECTOR_BASE + 2 * secret_index + plane_type if plane_type < 2 else 255
                exit_selectors.append(selector)
                if plane_type < 2:
                    plane_owner = EXIT_MOVER_OWNER
            elif exit_movers and model in (SECRET_SHOOT_TRIGGER_MODEL, ORDINARY_SHOOT_TRIGGER_MODEL):
                exit_selectors.append(255)
            elif exit_index is not None:
                if exit_lane is None:
                    exit_selectors.append(255)
                else:
                    exit_selectors.append(exit_index * 4 + exit_lane)
                    plane_owner = EXIT_MOVER_OWNER
            remap_planes[plane_id] = packed_offset | (tag << 13) | plane_owner
        for node in sorted(depth):
            plane, front, back = nodes[node]
            all_nodes.append(
                (
                    model,
                    remap_planes[plane],
                    remap_nodes.get(front, front),
                    remap_nodes.get(back, back),
                )
            )
        model_ranges.append(
            dict(
                model=model,
                **({"pointBoundsXY": [[round((models[model][i] - 2 - origin[i]) * scale) for i in range(2)],
                                      [round((models[model][i + 3] + 2 - origin[i]) * scale) for i in range(2)]]}
                   if point and model in exit_indices else {}),
                root=roots_by_model[model],
                nodeBegin=node_begin,
                nodeEnd=len(all_nodes) * NODE_BYTES,
                planeBegin=plane_bases[-1],
                planeEnd=len(all_planes) * PLANE_BYTES,
                owner=owner,
            )
        )

    def child(model, value):
        if value == EMPTY and model in following:
            return roots_by_model[following[model]]
        if exit_movers and point and value == SOLID:
            if model == ORDINARY_SHOOT_TRIGGER_MODEL:
                return (-72) & 0xffff
            if model in SECRET_MODELS:
                return (SECRET_TERMINAL_BASE - SECRET_MODELS.index(model)) & 0xffff
            if model == SECRET_SHOOT_TRIGGER_MODEL:
                return (SECRET_TERMINAL_BASE - len(SECRET_MODELS)) & 0xffff
        if static_models is None and point and value == SOLID and model:
            return EXIT_POINT_TERMINALS.get(model, ENTRANCE_POINT_TERMINAL.get(model, -model)) & 0xFFFF
        if point and value == SOLID and model in point_targets:
            return -model & 0xFFFF
        return value & 0xFFFF

    box_root = None
    if explobox is not None:
        if point or not exit_movers:
            raise ValueError("the movable box hull requires the E1M1 player hull")
        box_root = len(all_nodes) * NODE_BYTES
        player_min, player_max = (-16, -16, -24), (16, 16, 32)
        for axis in range(3):
            # Brush against the stock player hull, using the rebased body origin.
            lower = explobox["origin"][axis] + explobox["mins"][axis] - player_max[axis]
            upper = explobox["origin"][axis] + explobox["maxs"][axis] - player_min[axis]
            for high, distance in enumerate((lower, upper)):
                inside = (len(all_nodes) + 1) * NODE_BYTES if (axis, high) != (2, 1) else SOLID
                outside = roots[0]
                ref = ((3 + axis) << 13) | (len(all_planes) * PLANE_BYTES)
                all_nodes.append((-1, ref, outside if high else inside, inside if high else outside))
                all_planes.append((0, 0, round((distance - eye_origin[axis]) * scale)))
                exit_selectors.append(255)
    if len(all_nodes) * NODE_BYTES >= 0x8000:
        raise ValueError("player hull node offsets exceed the signed range")
    # A large static hull only needs third coefficients for its XYZ planes.
    # Move those planes to a prefix and retain ordinary node/plane records.
    if static_models is not None and len(all_nodes) * NODE_BYTES + len(all_planes) * 10 > 0x8000:
        order = sorted(range(len(all_planes)), key=lambda i: not third_coefficients[i])
        offsets = {old * PLANE_BYTES: static_plane_reference(new * PLANE_BYTES)
                   for new, old in enumerate(order)}
        all_nodes = [(model, (ref & (0xE000 | AXIAL_MOVER_FLAG)) | offsets[static_plane_offset(ref)], front, back)
                     for model, ref, front, back in all_nodes]
        all_planes = [all_planes[i] for i in order]
        third_coefficients = [third_coefficients[i] for i in order if third_coefficients[i]]
        bevel_owners = {static_plane_offset(offsets[offset]): owner for offset, owner in bevel_owners.items()}
    node_data = b"".join(
        pack("<3H", ref, child(model, front), child(model, back))
        for model, ref, front, back in all_nodes
    )
    plane_data = b"".join(pack("<2hi", *plane) for plane in all_planes)
    payload = node_data + plane_data
    if exit_movers:
        # Native 16-bit loads read one byte beyond each selector.
        payload += bytes(exit_selectors) + b"\0"
    if static_models is not None:
        payload += b"".join(pack("<h", value) for value in third_coefficients)
    metadata = dict(
        schema=f"quake-e1m1-{'shot' if point else 'walk'}-hull-v1",
        bspSha256=sha256(bsp).hexdigest(),
        bytes=len(payload),
        sha256=sha256(payload).hexdigest(),
        nodes=len(all_nodes),
        planes=len(all_planes),
        roots=roots,
        stackEntries=sum(depths),
        positionFractionBits=3 if point else 4,
        normalFractionBits=14,
    )
    if box_root is not None:
        metadata["exploboxRoot"] = box_root
        metadata["stackEntries"] += 6
    if static_models is None:
        metadata.update(
            modelIds=list(model_ids), modelRanges=model_ranges, entranceOwnerMask=6
        )
    if exit_movers:
        metadata.update(exitMoverModels=list(exit_indices), exitPlaneFirst=exit_first_plane,
                        exitPlaneTable=len(plane_data))
    if static_models is not None:
        metadata["thirdCoefficientOffset"] = len(node_data) + len(plane_data)
        metadata["threeAxisPlanes"] = sum(bool(value) for value in third_coefficients)
    if bevel_owners:
        metadata["movingBevelPlanes"] = [[offset, *owner] for offset, owner in sorted(bevel_owners.items())]
    return payload, metadata, len(node_data), plane_bases


def _entrance_include(metadata, prefix):
    ranges = {row["model"]: row for row in metadata["modelRanges"]}
    lines = [
        f"{prefix}_ENTRANCE_OWNER_MASK = 6",
        f"{prefix}_BUTTON_PLANE_END = {ranges[4]['planeEnd']}",
    ]
    for leaf, model in enumerate((1, 2)):
        row = ranges[model]
        for field, value in (
            ("ROOT", row["root"]),
            ("NODE_BEGIN", row["nodeBegin"]),
            ("NODE_END", row["nodeEnd"]),
            ("PLANE", row["planeBegin"]),
            ("PLANE_END", row["planeEnd"]),
            ("OWNER", row["owner"]),
        ):
            lines.append(f"{prefix}_ENTRANCE_{leaf}_{field} = {value}")
    if "exitMoverModels" in metadata:
        lines += [f"{prefix}_EXIT_PLANE_FIRST = {metadata['exitPlaneFirst']}",
                  f"{prefix}_EXIT_PLANE_TABLE = {metadata['exitPlaneTable']}"]
    return ("\n".join(lines) + "\n").encode("ascii")


def player_hull_outputs(bsp, origin, *, exit_movers=False, explobox=None):
    payload, metadata, node_bytes, plane_bases = _hull(bsp, origin, point=False, exit_movers=exit_movers, explobox=explobox)
    root = metadata["roots"][0]
    depth = metadata["stackEntries"]
    include = (
        f"BSP_PLAYER_WALK = 1\nWALK_HULL_ROOT = {root}\n"
        f"WALK_HULL_PLANES = {node_bytes}\n"
        f"WALK_DOOR_PLANE = {plane_bases[1]}\n"
        f"WALK_BUTTON_PLANE = {plane_bases[2]}\n"
        f"WALK_HULL_STACK_ENTRIES = {depth}\n"
        f"WALK_HULL_BYTES = {len(payload)}\n"
    ).encode("ascii")
    if "exploboxRoot" in metadata:
        include += f"WALK_EXPLOBOX_ROOT = {metadata['exploboxRoot']}\n".encode("ascii")
    include += _entrance_include(metadata, "WALK")
    return {
        Path("QuakeBSPWalkHull.bin"): payload,
        Path("QuakeBSPWalkHull.json"): (json.dumps(metadata, indent=2) + "\n").encode(
            "ascii"
        ),
    }, include


def shotgun_hull_outputs(bsp, origin, *, exit_movers=False):
    payload, metadata, node_bytes, _ = _hull(bsp, origin, point=True, exit_movers=exit_movers)
    include = (
        f"SHOT_HULL_ROOT = {metadata['roots'][0]}\n"
        f"SHOT_HULL_PLANES = {node_bytes}\n"
        f"SHOT_HULL_STACK_ENTRIES = {metadata['stackEntries']}\n"
        f"SHOT_HULL_BYTES = {len(payload)}\n"
    ).encode("ascii")
    include += _entrance_include(metadata, "SHOT")
    return {
        Path("QuakeBSPShotHull.bin"): payload,
        Path("QuakeBSPShotHull.json"): (json.dumps(metadata, indent=2) + "\n").encode(
            "ascii"
        ),
    }, include


def static_level_hull_outputs(bsp, origin, *, point, static_models=None, e1m2=False, e1m3=False):
    """Union world and solid inline hulls with optional axial brush motion."""
    from snes_tooling.quake.quake_bsp_assets import parse_entities

    entities = parse_entities(lump_data(bsp, lump_ranges(bsp), 0))
    solid_classes = {
        "func_wall",
        "func_door",
        "func_door_secret",
        "func_plat",
        "func_train",
        "func_button",
        "func_episodegate",
        "func_bossgate",
    }
    model_ids = (
        0,
        *sorted(
            {
                int(e["model"][1:])
                for e in entities
                if e.get("classname") in solid_classes
                and e.get("model", "").startswith("*")
            }
        ),
    )
    if static_models is not None:
        selected = tuple(static_models)
        if (any(type(model) is not int or model <= 0 for model in selected)
                or len(set(selected)) != len(selected)
                or not set(selected) <= set(model_ids[1:])):
            raise ValueError("static hull model filter contains an invalid solid brush")
        model_ids = (0, *sorted(selected))
    axial_movers = ()
    point_targets = ()
    if e1m2:
        from snes_tooling.quake.quake_e1m2_machinery import (
            E1M2_EXCLUDED_MODELS, E1M2_MOVER_AXES, E1M2_MOVER_MODELS,
        )
        model_ids = tuple(model for model in model_ids if model not in E1M2_EXCLUDED_MODELS)
        axial_movers = tuple(zip(E1M2_MOVER_MODELS, E1M2_MOVER_AXES, strict=True))
        if not set(E1M2_MOVER_MODELS) <= set(model_ids):
            raise ValueError("E1M2 collision is missing an authored mover")
    if e1m3:
        from snes_tooling.quake.quake_e1m3_machinery import (
            E1M3_AXIAL_MOVERS, E1M3_STAIR_BUTTON, excluded_singleplayer_models,
        )
        excluded = set(excluded_singleplayer_models(entities))
        model_ids = tuple(model for model in model_ids if model not in excluded)
        axial_movers = E1M3_AXIAL_MOVERS
        point_targets = (E1M3_STAIR_BUTTON,)
        if not {model for model, _ in axial_movers} <= set(model_ids):
            raise ValueError("E1M3 collision is missing an authored mover")
    translated = [
        e
        for e in entities
        if e.get("model", "").startswith("*")
        and int(e["model"][1:]) in model_ids
        and any(float(v) for v in e.get("origin", "0 0 0").split())
    ]
    if translated:
        raise ValueError(
            "static gameplay collision requires authored zero-origin inline brushes"
        )
    payload, metadata, node_bytes, _ = _hull(
        bsp, origin, point=point, static_models=model_ids, axial_movers=axial_movers,
        moving_bevels=e1m3, point_targets=point_targets,
    )
    if axial_movers:
        metadata["axialMoverModels"] = [model for model, _ in axial_movers]
        if any(isinstance(axes, tuple) for _, axes in axial_movers):
            metadata["axialMoverOffsetCount"] = len(axial_movers) * 2
    metadata.update(
        schema=f"quake-basic-{'shot' if point else 'walk'}-hull-v1",
        inlineModels=list(model_ids[1:]),
        moverPolicy="authored-static",
    )
    kind, prefix = ("Shot", "SHOT") if point else ("Walk", "WALK")
    include = (
        (
            ""
            if point
            else "BSP_PLAYER_WALK = 1\nWALK_DOOR_PLANE = 8192\nWALK_BUTTON_PLANE = 8192\n"
        )
        + f"{prefix}_HULL_ROOT = {metadata['roots'][0]}\n"
        + f"{prefix}_HULL_PLANES = {node_bytes}\n"
        + f"{prefix}_HULL_THIRD_COEFFICIENTS = {metadata['thirdCoefficientOffset']}\n"
        + f"{prefix}_HULL_STACK_ENTRIES = {metadata['stackEntries']}\n"
        + f"{prefix}_HULL_BYTES = {len(payload)}\n"
    ).encode("ascii")
    if metadata["planes"] * PLANE_BYTES > STATIC_PLANE_HIGH_BIT:
        include += f"{prefix}_HULL_EXTENDED_PLANES = 1\n".encode("ascii")
    if bevels := metadata.get("movingBevelPlanes"):
        lines = [f"{prefix}_MOVING_BEVEL_COUNT = {len(bevels)}"]
        for index, (offset, mover, coefficient) in enumerate(bevels):
            for field, value in zip(("OFFSET", "MOVER", "COEFFICIENT"), (offset, mover, coefficient), strict=True):
                lines.append(f"{prefix}_MOVING_BEVEL_{index}_{field} = {value}")
        include += ("\n".join(lines) + "\n").encode("ascii")
    return {
        Path(f"QuakeBSP{kind}Hull.bin"): payload,
        Path(f"QuakeBSP{kind}Hull.json"): (
            json.dumps(metadata, indent=2) + "\n"
        ).encode("ascii"),
    }, include
