"""Compile the authored E1M2 mechanisms needed to reach the exit."""

from dataclasses import replace
from pathlib import Path

from snes_tooling.quake.quake_e1m1_exit_assets import _eye_bounds
from snes_tooling.quake.quake_start_hub import _trigger_bounds
from snes_tooling.quake.quakec_grunt import GruntReference
from snes_tooling.quake.quakec_shell_pickups import pickup_eye_bounds


E1M2_MOVER_MODELS = (2, 3, 11, 10, 49, 50, 39, 40, 16, 23, 24, 25, 26, 27, 33, 34)
E1M2_MOVER_AXES = (2, 2, 1, 1, 0, 0, 0, 0, 2, 0, 0, 0, 0, 2, 1, 1)
E1M2_EXCLUDED_MODELS = (61,)
E1M2_MACHINERY_INCLUDE = Path("QuakeBSPE1M2Machinery.i")
POSE_COUNT = 4


def build_e1m2_machinery(program, archive, models, entities, drop):
    authored = {e.get("model"): (i, e) for i, e in enumerate(entities, 1) if "model" in e}

    def brush(model, classname, **fields):
        number, entity = authored[f"*{model}"]
        if entity["classname"] != classname or any(entity.get(key) != value for key, value in fields.items()):
            raise ValueError(f"E1M2 route brush *{model} changed")
        return number, entity

    mover_classes = tuple("func_button" if model in (11, 16) else "func_door"
                          for model in E1M2_MOVER_MODELS)
    expected_targets = {2: "t50", 3: "t50", 10: "t58", **dict.fromkeys(range(23, 28), "t73"),
                        33: "t110", 49: "t122"}
    origin = tuple((models[0][i] + models[0][i + 3]) * .5 for i in range(3))
    vm = GruntReference(program, models, archive, drop)
    vm.add(0, entities[0])
    vm.add(1, {"classname": "player", "health": 100})
    movers, slots = [], {}
    for slot, (model, classname, axis) in enumerate(zip(E1M2_MOVER_MODELS, mover_classes, E1M2_MOVER_AXES,
                                                        strict=True), 2):
        fields = {"targetname": expected_targets[model]} if model in expected_targets else {}
        if model in (11, 16):
            fields["target"] = "t58" if model == 11 else "t65"
        number, entity = brush(model, classname, **fields)
        slots[model] = slot
        vm.add(slot, entity)
        vm.event(slot, classname)
        start, end = (tuple(round(v * 16) for v in vm.get(slot, field)) for field in ("pos1", "pos2"))
        axes = [i for i, (a, b) in enumerate(zip(start, end, strict=True)) if a != b]
        if axes != [axis] or any(start[i] for i in range(3) if i != axis):
            raise ValueError(f"E1M2 route mover *{model} must translate on one axis")
        lo, hi = start[axis], end[axis]
        speed = vm.get(slot, "speed")
        ticks = max(6, round(abs(hi - lo) * 4 / speed))
        # Only the authored endpoint geometry fits alongside the other maps.
        positions = [lo] * (POSE_COUNT - 1) + [hi]
        movers.append(dict(inlineModel=model, renderEntity=number, axis=axis, positionsQ4=positions,
                           positionsQ3=[q // 2 for q in positions], ticksQ6=ticks, delayQ6=0,
                           poseThresholds=[(ticks * i + POSE_COUNT - 2) // (POSE_COUNT - 1)
                                           for i in range(1, POSE_COUNT)],
                           speed=speed, wait=vm.get(slot, "wait")))

    def trigger(model, target):
        number, entity = brush(model, "trigger_once", target=target)
        bounds = _trigger_bounds(entity, models, origin)
        return number, dict(eyeMinQ4=bounds["triggerEyeMinQ4"], eyeMaxQ4=bounds["triggerEyeMaxQ4"])

    def solid_touch(models):
        bounds = [(vm.get(slots[model], "absmin"), vm.get(slots[model], "absmax")) for model in models]
        lo = [min(a[i] for a, _ in bounds) for i in range(3)]
        hi = [max(b[i] for _, b in bounds) for i in range(3)]
        return _eye_bounds(lo, hi, origin, touch=True)

    def linked_door(models):
        first, second = (slots[model] for model in models)
        vm.drop_slot = len(movers) + 2
        vm.set(first, "nextthink", 0)
        vm.event(first, "LinkDoors")
        if (vm.get(first, "enemy") != second or vm.get(second, "enemy") != first
                or vm.get(first, "trigger_field")):
            raise ValueError(f"E1M2 route door team changed: {models}")
        return solid_touch(models)

    def group(name, indices, source, *, wait=-1):
        trigger_entity, bounds = source
        return dict(id=name, triggerEntity=trigger_entity, trigger=bounds,
                    waitQ6=-1 if wait < 0 else round(wait * 64), movers=list(indices),
                    durationQ6=max(movers[i]["delayQ6"] + movers[i]["ticksQ6"] for i in indices))

    key_number, key_entity = 115, entities[114]
    if (key_entity.get("classname"), key_entity.get("target"), key_entity.get("spawnflags")) != (
            "item_key1", "t122", "2048"):
        raise ValueError("E1M2 silver key changed")
    key_slot = len(movers) + 3
    vm.add(key_slot, {**key_entity, "origin": tuple(map(float, key_entity["origin"].split()))})
    vm.event(key_slot, "item_key1")
    vm.t = vm.get(key_slot, "nextthink")
    vm.set(key_slot, "nextthink", 0)
    vm.event(key_slot, "think")
    key_origin, key_mins, key_maxs = (vm.get(key_slot, field) for field in ("origin", "mins", "maxs"))
    key_lo, key_hi = pickup_eye_bounds(tuple(a - b for a, b in zip(key_origin, origin, strict=True)), key_mins, key_maxs)
    if vm.get(key_slot, "items") != 131072 or vm.get(key_slot, "solid") != 1:
        raise ValueError("E1M2 key did not become the stock silver key pickup")
    key = dict(entityNumber=key_number, model=vm.get(key_slot, "model"), origin=key_origin,
               trigger=dict(eyeMinQ4=key_lo, eyeMaxQ4=key_hi))

    _, delayed = brush(20, "trigger_once", target="t73", targetname="t65")
    brush(61, "func_wall", spawnflags="1792")
    bridge_button, bridge = movers[2:4]
    floorplate = movers[8]
    if bridge["positionsQ4"][0] == 0 or bridge["positionsQ4"][-1] != 0:
        raise ValueError("E1M2 bridge must start at its stock translated pose")
    bridge["delayQ6"] = bridge_button["ticksQ6"]
    for mover in movers[9:14]:
        mover["delayQ6"] = floorplate["ticksQ6"] + round(float(delayed["delay"]) * 64)
    groups = [
        group("t50", range(0, 2), trigger(4, "t50")),
        group("bridge", range(2, 4), (bridge_button["renderEntity"], solid_touch((11,)))),
        group("shortcut", range(4, 6), (key_number, key["trigger"])),
        group("silver", range(6, 8), (movers[6]["renderEntity"], linked_door((39, 40)))),
        group("t73", range(8, 14), (floorplate["renderEntity"], solid_touch((16,)))),
        group("exit", range(14, 16), trigger(35, "t110")),
    ]
    linked_door((49, 50))
    linked_door((33, 34))
    return dict(movers=movers, groups=groups, silverKey=key, excludedModels=list(E1M2_EXCLUDED_MODELS))


def _posed(source, mover, pose):
    origin = [0.] * 3
    origin[mover["axis"]] = mover["positionsQ3"][pose] / 8
    if "secondAxis" in mover:
        origin[mover["secondAxis"]] = mover["secondPositionsQ3"][pose] / 8
    return replace(source, origin=tuple(origin))


def e1m2_signon_brushes(brushes, machinery):
    """Use the stock initial mover transforms in the visual baseline."""
    by_model = {m["inlineModel"]: m for m in machinery["movers"]}
    return tuple(_posed(state, by_model[state.inline_model], 0) if state.inline_model in by_model else state
                 for state in brushes if state.inline_model not in machinery["excludedModels"])


def add_e1m2_pose_rows(rows, brushes, machinery):
    """Add shared pose rows whose individual variants remain independently selectable."""
    by_model = {state.inline_model: state for state in brushes}
    movers = machinery["movers"]
    if len(rows) != 1:
        raise ValueError("E1M2 route mover rows require one basic gameplay row")
    base = rows[0]
    result = tuple(replace(base, index=pose, brushes=tuple(sorted((
        *base.brushes, *(_posed(by_model[mover["inlineModel"]], mover, pose) for mover in movers),
    )))) for pose in range(POSE_COUNT))
    for mover in movers:
        mover["poseRows"] = list(range(POSE_COUNT))
    return result


def e1m2_machinery_constants(machinery):
    movers, groups = machinery["movers"], machinery["groups"]
    gold_key = "goldKey" in machinery
    key_group = "gold" if gold_key else "silver"
    lines = [
        f"QC_E1M2_GROUP_COUNT = {len(groups)}", f"QC_EXIT_MOVER_COUNT = {len(movers)}",
        f"QC_EXIT_VARIANT_SLOTS = {(max(m['inlineModel'] for m in movers) + 2) & ~1}",
        f"QC_E1M2_SILVER_GROUP = {next(i for i, group in enumerate(groups) if group['id'] == key_group)}",
    ]
    if gold_key:
        lines.append("QC_E1M3_GOLD_KEY = 1")
        lines.append(f"QC_E1M3_PLATFORM = {next(i for i, m in enumerate(movers) if 'useTriggers' in m)}")
        lines.append(f"QC_E1M3_SHOT_GROUP = {next(i for i, group in enumerate(groups) if group['id'] == 't12')}")
        from snes_tooling.quake.quake_e1m3_machinery import E1M3_STAIR_BUTTON
        lines.append(f"QC_E1M3_SHOT_TERMINAL = {65536 - E1M3_STAIR_BUTTON}")
        for slot in range(16):
            i = next(i for i, mover in enumerate(movers) if mover["poseSlot"] == slot)
            lines.append(f"QC_E1M3_PACKED_MOVER_{slot} = {i}")
    return ("\n".join(lines) + "\n").encode("ascii")


def e1m2_machinery_outputs(machinery):
    """Pack native S-CPU table rows in stock group order, with signed Q4 bounds."""
    movers, groups = machinery["movers"], machinery["groups"]
    lines = []

    def words(name, values):
        lines.append(name + ":")
        values = tuple(values)
        if any(type(value) is not int or not -32768 <= value <= 65535 for value in values):
            raise ValueError(f"E1M2 route table {name} exceeds a native word")
        for i in range(0, len(values), 8):
            lines.append("        .word " + ", ".join(f"${value & 0xffff:04X}" for value in values[i:i+8]))

    def bounds(trigger):
        return (value + 32768 for pair in zip(trigger["eyeMinQ4"], trigger["eyeMaxQ4"], strict=True)
                for value in pair)

    words("QCE1M2GroupBounds", (value for group in groups for value in bounds(group["trigger"])))
    words("QCE1M2GroupWait", (group["waitQ6"] for group in groups))
    words("QCE1M2GroupDuration", (group["durationQ6"] for group in groups))
    words("QCE1M2GroupFirst", (group["movers"][0] for group in groups))
    words("QCE1M2GroupCount", (len(group["movers"]) for group in groups))
    words("QCE1M2MoverDelay", (mover["delayQ6"] for mover in movers))
    words("QCE1M2MoverAxis", (mover["axis"] for mover in movers))
    for i in range(POSE_COUNT - 1):
        words(f"QCE1M2MoverThreshold{i + 1}", (mover["poseThresholds"][i] for mover in movers))
    for fraction in (4, 3):
        words(f"QCE1M2MoverPositionsQ{fraction}",
              (value for mover in movers for value in mover[f"positionsQ{fraction}"]))
    key = machinery["goldKey"] if "goldKey" in machinery else machinery["silverKey"]
    words("QCE1M2KeyBounds", bounds(key["trigger"]))
    if "goldKey" in machinery:
        offsets, index, secondary = [], [], []
        pooled = {}

        def trajectory(values):
            values = tuple(values)
            if values not in pooled:
                pooled[values] = len(offsets) * 2
                offsets.extend(values)
            return pooled[values]

        for mover in movers:
            ticks = mover["ticksQ6"]
            start, end = mover["positionsQ4"][::3]
            values = mover.get("trajectoryQ4") or [start + (end - start) * step // ticks for step in range(ticks + 1)]
            index.append(trajectory(values))
            secondary.append(trajectory(mover["secondTrajectoryQ4"]) if "secondTrajectoryQ4" in mover else -1)
        platform, = (m for m in movers if "useTriggers" in m)
        words("QCE1M3PlatformUseAbove", bounds(platform["useTriggers"][0]))
        words("QCE1M3PlatformUseBelow", bounds(platform["useTriggers"][1]))
        words("QCE1M3PlatformCenterTouch", bounds(platform["centerTouch"]))
        lines += ['        .pushseg', '        .segment "BSP_QUAKEC_MOVER_PATHS"']
        words("QCE1M3MoverDuration", (m["ticksQ6"] for m in movers))
        words("QCE1M3MoverReturnAt", (m["ticksQ6"] + m["returnWaitQ6"] if "returnWaitQ6" in m else 0
                                    for m in movers))
        words("QCE1M3MoverOffsetIndex", index)
        words("QCE1M3MoverSecondaryIndex", secondary)
        words("QCE1M3MoverOffsetQ4", offsets)
        words("QCE1M3VisualShift", (mover["poseSlot"] * 2 for mover in movers))
        for field, axis in (("eyeMinQ4", 0), ("eyeMaxQ4", 0), ("eyeMinQ4", 1), ("eyeMaxQ4", 1)):
            label = ("Min" if field == "eyeMinQ4" else "Max") + "XY"[axis]
            words("QCE1M3Rider" + label, (m["rider"][field][axis] + 32768 if "rider" in m else 0
                                         for m in movers))
        words("QCE1M3RiderFloor", (m["rider"]["floorQ4"] if "rider" in m else 0 for m in movers))
        lines.append("        .popseg")
    return {E1M2_MACHINERY_INCLUDE: ("\n".join(lines) + "\n").encode("ascii")}
