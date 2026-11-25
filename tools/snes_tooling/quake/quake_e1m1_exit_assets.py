"""Stock E1M1 machinery on the normal route to the exit slipgate."""

from dataclasses import replace
from pathlib import Path

from snes_tooling.quake.quakec_grunt import GruntReference
from snes_tooling.quake.quake_e1m1_doors import ordinary_doors, add_ordinary_pose_rows
from snes_tooling.quake.quake_e1m1_secret_doors import SECRET_DOOR_MODELS, add_secret_pose_rows, secret_doors
from snes_tooling.quake.quake_e1m1_platforms import build_platforms
from snes_tooling.quake.quake_walk_hull import E1M1_EXIT_MOVER_SWEEPS


EXIT_MODELS = (5, 6, 8, 9, 25, 26, 27, 29)
EXIT_POSES = 4


def _eye_bounds(lo, hi, origin, *, touch):
    # Player bounds are relative to its body origin. Convert to eye Q4.
    margin = int(touch)
    low = [round((lo[i] - (16, 16, 32)[i] - margin + (22 if i == 2 else 0) - origin[i]) * 16)
           for i in range(3)]
    high = [round((hi[i] + (16, 16, 24)[i] + margin + (22 if i == 2 else 0) - origin[i]) * 16)
            for i in range(3)]
    if not all(-32768 <= a <= b <= 32767 for a, b in zip(low, high, strict=True)):
        raise ValueError("E1M1 exit interaction bounds exceed signed Q4")
    return dict(eyeMinQ4=low, eyeMaxQ4=high)


def build_exit_machinery(program, archive, models, entities, drop):
    authored = {entity.get("model"): (number, entity) for number, entity in enumerate(entities, 1)}
    vm = GruntReference(program, models, archive, drop)
    vm.add(0, {"classname": "worldspawn"})
    vm.add(1, {"classname": "player", "health": 100})
    origin = tuple(round((models[0][i] + models[0][i + 3]) * .5) for i in range(3))
    expected = (
        ("func_door", None, None), ("func_door", None, None),
        ("func_door", "t2", None), ("func_button", None, "t2"),
        ("func_button", None, "t9"), ("func_button", None, "t9"),
        ("func_button", None, "t9"), ("func_door", "t10", None),
    )
    movers = []
    for slot, (model, contract) in enumerate(zip(EXIT_MODELS, expected, strict=True), 2):
        number, entity = authored[f"*{model}"]
        kind = entity["classname"]
        if (kind, entity.get("targetname"), entity.get("target")) != contract:
            raise ValueError(f"stock E1M1 exit mover *{model} changed")
        vm.add(slot, entity)
        vm.event(slot, kind)
        start = tuple(round(v * 16) for v in vm.get(slot, "pos1"))
        end = tuple(round(v * 16) for v in vm.get(slot, "pos2"))
        axes = [i for i, (a, b) in enumerate(zip(start, end, strict=True)) if a != b]
        if len(axes) != 1 or any(start[i] for i in range(3) if i != axes[0]):
            raise ValueError("E1M1 exit mover requires one axial translation")
        axis = axes[0]
        sweep_axis, low, high = E1M1_EXIT_MOVER_SWEEPS[model]
        if axis != sweep_axis or not all(low * 16 <= pose <= high * 16 for pose in (start[axis], end[axis])):
            raise ValueError("E1M1 exit mover exceeds its packed collision sweep bound")
        ticks = max(6, round(abs(end[axis] - start[axis]) * 4 / vm.get(slot, "speed")))
        positions = [round(start[axis] + (end[axis] - start[axis]) * pose / (EXIT_POSES - 1))
                     for pose in range(EXIT_POSES)]
        if kind == "func_button":
            # Buttons travel only a few units. Share the resting pose until
            # the stock move finishes so they need just two packed variants.
            positions[1:-1] = [start[axis]] * (EXIT_POSES - 2)
        record = dict(inlineModel=model, renderEntity=number, axis=axis, positionsQ4=positions,
                      positionsQ3=[value // 2 for value in positions], ticksQ6=ticks,
                      poseThresholds=[(ticks * pose + EXIT_POSES - 2) // (EXIT_POSES - 1)
                                      for pose in range(1, EXIT_POSES)],
                      speed=vm.get(slot, "speed"), wait=vm.get(slot, "wait"))
        if kind == "func_button":
            record["touch"] = _eye_bounds(vm.get(slot, "mins"), vm.get(slot, "maxs"), origin, touch=True)
        movers.append(record)
    counters = [entity for entity in entities if entity.get("classname") == "trigger_counter"
                and entity.get("targetname") == "t9"]
    if len(counters) != 1 or counters[0].get("target") != "t10" or counters[0].get("count") != "3":
        raise ValueError("stock E1M1 exit counter changed")
    # Stock LinkDoors creates its auto-touch trigger around the linked team.
    vm.drop_slot = len(EXIT_MODELS) + 2
    vm.set(2, "nextthink", 0)
    vm.event(2, "LinkDoors")
    trigger = vm.drop_slot
    if vm.get(trigger, "owner") != 2 or vm.get(2, "enemy") != 3 or vm.get(3, "enemy") != 2:
        raise ValueError("stock E1M1 second door did not link its two leaves")
    doors = _eye_bounds(vm.get(trigger, "absmin"), vm.get(trigger, "absmax"), origin, touch=True)
    movers.extend(build_platforms(program, archive, models, entities, drop, origin, _eye_bounds))
    return dict(movers=movers, doorTouch=doors, doorWaitQ6=round(movers[0]["wait"] * 64),
                counterRequired=3, secretDoors=secret_doors(program, entities, models),
                ordinaryDoors=ordinary_doors(program, archive, models, entities, drop, origin, _eye_bounds))


def add_exit_pose_rows(rows, brushes, machinery):
    by_model = {state.inline_model: state for state in brushes if state.inline_model is not None}

    def posed(pose):
        result = []
        for mover in machinery["movers"]:
            source = by_model[mover["inlineModel"]]
            origin = tuple(mover["positionsQ3"][pose] / 8 if axis == mover["axis"] else 0.
                           for axis in range(3))
            result.append(replace(source, origin=origin))
        return tuple(result)

    initial = posed(0)
    rows = [replace(row, brushes=(*row.brushes, *initial)) for row in rows]
    pose_rows = [0]
    base = rows[0].brushes[:-len(initial)]
    for pose in range(1, EXIT_POSES):
        pose_rows.append(len(rows))
        rows.append(replace(rows[0], index=len(rows), brushes=(*base, *posed(pose))))
    for mover in machinery["movers"]:
        mover["poseRows"] = pose_rows
    # Each brush is clipped into the world BSP at every displayable height.
    # The packed Q2 geometry advances one coordinate per four Quake units.
    platforms = [mover for mover in machinery["movers"] if "platformTouch" in mover]
    for mover in platforms:
        mover["visualRows"] = [0]
    for height in range(1, 1 + max(-m["positionsQ4"][0] // 64 for m in platforms)):
        selected = {m["renderEntity"]: m for m in platforms}
        posed_brushes = []
        for state in rows[0].brushes:
            mover = selected.get(state.entity_number)
            if mover:
                bottom = mover["positionsQ4"][0] // 16
                state = replace(state, origin=(0., 0., float(min(0, bottom + height * 4))))
                if height <= -bottom // 4:
                    mover["visualRows"].append(len(rows))
            posed_brushes.append(state)
        rows.append(replace(rows[0], index=len(rows), brushes=tuple(posed_brushes)))
    rows = add_secret_pose_rows(rows, brushes, machinery["secretDoors"])
    rows = add_ordinary_pose_rows(rows, brushes, machinery["ordinaryDoors"])
    # Packed slots are ordered by authored entity, including movers interleaved with the exit team.
    return [replace(row, brushes=tuple(sorted(row.brushes, key=lambda state: state.entity_number))) for row in rows]


def exit_machinery_outputs(machinery):
    movers = machinery["movers"]
    lines = []

    def words(name, values):
        lines.append(name + ":")
        values = tuple(values)
        for index in range(0, len(values), 8):
            lines.append("        .word " + ", ".join(f"${value & 0xffff:04X}" for value in values[index:index + 8]))

    secret_doors = machinery["secretDoors"]
    ordinary = machinery["ordinaryDoors"]
    visual_doors = [*secret_doors, *ordinary]
    words("QCSecretModels", (d["inlineModel"] for d in visual_doors))
    words("QCOrdDuration", (d["durationQ6"] for d in ordinary))
    words("QCOrdRest", (d["startQ4"] for d in ordinary))
    words("QCOrdWait", (max(0, d["waitQ6"]) for d in ordinary))
    # The hydraulic pusher moves from its actual blocked or unblocked position.
    # Only the other seven doors index their original sampled trajectories.
    for label, key in (("QCOrdOut", "outwardQ4"), ("QCOrdBack", "returnQ4")):
        words(label + "Base", (sum(len(d[key]) for d in ordinary[1:i]) for i in range(len(ordinary))))
        words(label, (value for d in ordinary[1:] for value in d[key]))
    words("QCOrdFlags", ((d["spawnflags"] | d["triggerSpawnflags"]) & 0x700 for d in ordinary))
    words("QCOrdBoxes", (v for d in ordinary for lo, hi in zip(d["triggerEyeMinQ4"],
        d["triggerEyeMaxQ4"], strict=True) for v in (lo, hi - lo + 1)))
    hint, = (d["hintBounds"] for d in ordinary if "hintBounds" in d)
    words("QCOrdHintBox", (v for lo, hi in zip(hint["triggerEyeMinQ4"], hint["triggerEyeMaxQ4"],
                                               strict=True) for v in (lo, hi - lo + 1)))
    # Only touch boxes intersecting the player's signed 64-unit Y cell can fire.
    interest = [0] * 64
    for bit, box in enumerate([*ordinary[1:], hint]):
        first, last = box["triggerEyeMinQ4"][1] // 1024, box["triggerEyeMaxQ4"][1] // 1024
        for cell in range(first, last + 1):
            interest[cell & 63] |= 1 << bit
    lines.extend(("QCOrdTouchYMask:", "        .byte " + ", ".join(map(str, interest))))
    shot_owners = [2 * i if door["shootable"] else 255 for i, door in enumerate(secret_doors)]
    shot_owners += [2 * i for i, door in enumerate(secret_doors) for link in door["links"] if link["shot"]]
    lines.extend(("QCSecretShotOwners:", "        .byte " + ", ".join(map(str, shot_owners))))
    words("QCSecretFirstAxis", (2 * d["legs"][0]["axis"] for d in secret_doors))
    words("QCSecretFirstSign", (d["legs"][0]["travelQ4"] < 0 for d in secret_doors))
    words("QCSecretSecondSign", (d["legs"][1]["travelQ4"] < 0 for d in secret_doors))
    words("QCSecretTravelQ5", (2 * sum(abs(r["travelQ4"]) for r in d["legs"]) for d in secret_doors))
    words("QCSecretOpenWait", (d["openWaitQ6"] for d in secret_doors))
    touches = [(index, trigger) for index, d in enumerate(secret_doors)
               for trigger in d["links"] if not trigger["shot"]]
    if [(i, t["inlineModel"], t["once"]) for i, t in touches[:2]] != [(0, 11, True), (0, 12, True)]:
        raise ValueError("E1M1 t3 lights must share the two one-shot controls of secret door *10")
    words("QCT3TouchBits", (trigger["t3TriggerBit"] for _, trigger in touches[:2]))
    words("QCSecretTouchOwners", (2 * index for index, _ in touches))
    words("QCSecretTouchBoxes", (v for _, box in touches for lo, hi in zip(
        box["triggerEyeMinQ4"], box["triggerEyeMaxQ4"], strict=True) for v in (lo, hi - lo + 1)))
    words("QCSecretHintBox", (v for lo, hi in zip(secret_doors[-1]["triggerEyeMinQ4"],
        secret_doors[-1]["triggerEyeMaxQ4"], strict=True) for v in (lo, hi - lo + 1)))
    words("QCExitPositionsQ4", (q for mover in movers for q in mover["positionsQ4"]))
    words("QCExitPositionsQ3", (q for mover in movers for q in mover["positionsQ3"]))
    words("QCExitDurations", (mover["ticksQ6"] for mover in movers))
    words("QCExitPoseThresholds", (q for mover in movers for q in (*mover["poseThresholds"], 0)))
    words("QCExitBits", (1 << i for i in range(len(movers))))
    platforms = [mover for mover in movers if "platformTouch" in mover]
    # Check every runtime position against its independent stock VM sample.
    for mover in platforms:
        for name, sign in (("ascentQ4", 1), ("descentQ4", -1)):
            path = mover[name]
            if any(value != path[0] + sign * round(i * 75 / 2)
                   for i, value in enumerate(path[:-1])):
                raise ValueError("E1M1 stock platform trajectory differs from its native Q5 velocity")
    words("QCPlatformBottom", (m["positionsQ4"][0] for m in platforms))
    hydraulic = ordinary[0]
    if (hydraulic["inlineModel"], hydraulic["speed"], hydraulic["damage"], hydraulic["endQ4"]) != (15, 100, 2, 0):
        raise ValueError("unexpected hydraulic door")
    pushers = [*platforms, hydraulic]
    words("QCPlatformFloor", (m["floorEyeQ4"] for m in pushers))
    words("QCPlatformWait", (m["waitQ6"] for m in platforms))
    words("QCPlatformOccupiedWait", (m["occupiedWaitQ6"] for m in platforms))
    for index, m in enumerate(pushers):
        bounds = m["riderBounds"]
        words("QCPlatformRider" + str(index), (value for lo, hi in
              zip(bounds["eyeMinQ4"][:2], bounds["eyeMaxQ4"][:2], strict=True)
              for value in (lo, hi - lo + 1)))
    boxes = [machinery["doorTouch"], *(mover["touch"] for mover in movers if "touch" in mover),
             *(mover["platformTouch"] for mover in platforms)]
    words("QCExitTouchBoxes", (value for box in boxes
        for low, high in zip(box["eyeMinQ4"], box["eyeMaxQ4"], strict=True) for value in (low, high - low + 1)))
    include = (f"QC_EXIT_MOVER_COUNT = {len(movers)}\nQC_EXIT_POSE_COUNT = {EXIT_POSES}\n"
               f"QC_T3_LIGHT_STYLE = 32\nQC_FLUORESCENT_STYLE = 10\n"
               f"QC_SECRET_DOOR_COUNT = {len(secret_doors)}\nQC_SECRET_DOOR_TOUCH_COUNT = {len(touches)}\n"
               f"QC_ORD_DOOR_COUNT = {len(ordinary)}\nQC_MOVING_DOOR_POSES = {len(visual_doors)}\n"
               f"QC_E1M1_PLATFORM_FIRST = {len(movers)-len(platforms)}\n"
               f"QC_EXIT_DOOR_WAIT = {machinery['doorWaitQ6']}\n"
               f"QC_EXIT_FIRST_Y = {min(box['eyeMinQ4'][1] for box in boxes)}\n"
               f"QC_EXIT_VARIANT_SLOTS = {max(*EXIT_MODELS, *SECRET_DOOR_MODELS) + 1}\n").encode("ascii")
    return include, {Path("QuakeBSPExitMovers.i"): ("\n".join(lines) + "\n").encode("ascii")}
