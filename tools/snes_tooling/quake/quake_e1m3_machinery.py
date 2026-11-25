"""Compile the stock movements and triggers on E1M3's lift route."""

from snes_tooling.quake.quake_e1m1_exit_assets import _eye_bounds
from snes_tooling.quake.quake_start_hub import _trigger_bounds
from snes_tooling.quake.quakec_grunt import GruntReference
from snes_tooling.quake.quakec_shell_pickups import pickup_eye_bounds


# Inline BSP models and their translation axes in collision slot order.
E1M3_DOOR_TEAMS = (
    ((21, 22), 1, None, "gold"),
    ((33, 34), 1, None, None),
    ((1, 2), 0, None, None),
    ((35, 36), 0, 37, "t80"),
    ((28, 29), 0, 26, "t78"),
    ((11, 12), 1, None, None),
)
E1M3_FINAL_MOVERS = ((5, 1), (6, 0), (7, 2), (10, 0), (9, 2), (3, (2, 0)), (4, (2, 0)))
E1M3_STAIR_BUTTON = 87
E1M3_STAIR_MOVERS = ((E1M3_STAIR_BUTTON, 0), *((model, 2) for model in range(13, 18)))
E1M3_NAILGUN_DOORS = ((19, 1), (20, 1))
E1M3_AXIAL_MOVERS = (
    *((model, axis) for team, axis, _, _ in E1M3_DOOR_TEAMS for model in team),
    *E1M3_FINAL_MOVERS, *E1M3_STAIR_MOVERS, *E1M3_NAILGUN_DOORS, (38, 2),
)


def excluded_singleplayer_models(entities):
    return sorted(int(entity["model"][1:]) for entity in entities
                  if entity.get("model", "").startswith("*")
                  and int(entity.get("spawnflags", "0")) & 0x700 == 0x700)


def _contact(vm, slots, origin):
    lo = [min(vm.get(slot, "absmin")[i] for slot in slots) for i in range(3)]
    hi = [max(vm.get(slot, "absmax")[i] for slot in slots) for i in range(3)]
    return _eye_bounds(lo, hi, origin, touch=True)


def _trigger(entity, models, origin):
    trigger = _trigger_bounds(entity, models, origin)
    return dict(eyeMinQ4=trigger["triggerEyeMinQ4"], eyeMaxQ4=trigger["triggerEyeMaxQ4"])


def _group(movers, name, number, bounds, indices, wait=-1):
    duration = max(movers[index]["delayQ6"] + movers[index]["ticksQ6"]
                   for index in indices)
    return dict(id=name, triggerEntity=number, trigger=bounds, movers=list(indices),
                waitQ6=-1 if wait < 0 else round(wait * 64), durationQ6=duration)


def _train(vm, slot, number, model):
    # Execute the stock Find/use/think callbacks to obtain actual transformed
    # path positions and deadlines, including the pause at the first corner.
    vm.event(slot, "func_train")
    vm.event(slot, "think")
    start = vm.get(slot, "origin")
    vm.event(slot, "use")
    corner = vm.get(slot, "finaldest")
    first_end = vm.get(slot, "nextthink")
    vm.set(slot, "ltime", first_end)
    vm.event(slot, "think")
    second_start = vm.get(slot, "nextthink")
    vm.set(slot, "ltime", second_start)
    vm.event(slot, "think")
    end = vm.get(slot, "finaldest")
    second_end = vm.get(slot, "nextthink")
    if any(point[1] != 0 for point in (start, corner, end)) or (
            start[0] != corner[0] or corner[2] != end[2]):
        raise ValueError(f"E1M3 train *{model} no longer follows its Z and X legs")
    first = round(first_end * 64)
    pause = round((second_start - first_end) * 64)
    second = round((second_end - second_start) * 64)
    total = first + pause + second
    times = (0, (first + 1) // 2, first, total)

    def sweep(a, b, steps):
        lo, hi = round(a * 16), round(b * 16)
        return [lo + (hi - lo) * step // steps for step in range(steps + 1)]

    z = sweep(start[2], corner[2], first) + [round(corner[2] * 16)] * (pause + second)
    x = [round(start[0] * 16)] * (first + pause) + sweep(corner[0], end[0], second)
    poses = [z[age] for age in times]
    return dict(inlineModel=model, renderEntity=number, axis=2, secondAxis=0,
                positionsQ4=poses, positionsQ3=[q // 2 for q in poses],
                secondPositionsQ3=[x[age] // 2 for age in times],
                trajectoryQ4=z, secondTrajectoryQ4=x, ticksQ6=total, delayQ6=0,
                poseThresholds=list(times[1:]))


def build_e1m3_machinery(program, archive, models, entities, drop):
    authored = {entity.get("model"): (number, entity)
                for number, entity in enumerate(entities, 1) if "model" in entity}
    origin = tuple((models[0][axis] + models[0][axis + 3]) * .5 for axis in range(3))
    vm = GruntReference(program, models, archive, drop)
    vm.add(0, entities[0])
    vm.add(1, {"classname": "player", "health": 100})
    vm.drop_slot = len(E1M3_AXIAL_MOVERS) + 2
    for slot, corner in enumerate((e for e in entities if e["classname"] == "path_corner"), 100):
        vm.add(slot, {**corner, "origin": tuple(map(float, corner["origin"].split()))})
    movers = []
    slots = {}
    for slot, (model, axis) in enumerate(E1M3_AXIAL_MOVERS, 2):
        number, entity = authored[f"*{model}"]
        if isinstance(axis, tuple):
            if entity["classname"] != "func_train" or entity.get("targetname") != "t5":
                raise ValueError(f"E1M3 model *{model} is no longer a t5 train")
            slots[model] = slot
            vm.add(slot, entity)
            movers.append(_train(vm, slot, number, model))
            continue
        kind = "func_button" if model in (5, E1M3_STAIR_BUTTON) else "func_plat" if model == 38 else "func_door"
        if entity["classname"] != kind:
            raise ValueError(f"E1M3 model *{model} is no longer {kind}")
        slots[model] = slot
        vm.add(slot, entity)
        vm.event(slot, kind)
        start, end = (tuple(round(v * 16) for v in vm.get(slot, field)) for field in ("pos1", "pos2"))
        if [i for i in range(3) if start[i] != end[i]] != [axis]:
            raise ValueError(f"E1M3 door *{model} changed its translation axis")
        speed = vm.get(slot, "speed")
        ticks = max(6, round(abs(end[axis] - start[axis]) * 4 / speed))
        positions = [round(start[axis] + (end[axis] - start[axis]) * pose / 3) for pose in range(4)]
        if kind == "func_button":
            positions[1] = positions[0]
            positions[2] = positions[0]
        record = dict(inlineModel=model, renderEntity=number, axis=axis, positionsQ4=positions,
                      positionsQ3=[q // 2 for q in positions], ticksQ6=ticks, delayQ6=0,
                      poseThresholds=[(ticks * (2 * step - 1) + 5) // 6 for step in range(1, 4)])
        if model in (9, 38):
            # The solid floor is a rectangle. BSP model bounds have one extra
            # unit on every side. The standing hull adds the player radius
            # and the 24-unit lower extent before conversion to an eye height.
            mins = [models[model][i] + 1 for i in range(3)]
            maxs = [models[model][i + 3] - 1 for i in range(3)]
            record["rider"] = dict(
                eyeMinQ4=[round((mins[i] - 16 - origin[i]) * 16) for i in range(2)],
                eyeMaxQ4=[round((maxs[i] + 16 - origin[i]) * 16) for i in range(2)],
                floorQ4=round((maxs[2] + 24 + 22 - origin[2]) * 16))
        movers.append(record)

    groups = []
    # The plat spawn also creates an engine-owned center-touch entity.
    vm.drop_slot += 1
    for team, _, trigger_model, name in E1M3_DOOR_TEAMS:
        first, second = (slots[model] for model in team)
        vm.set(first, "nextthink", 0)
        vm.event(first, "LinkDoors")
        if vm.get(first, "enemy") != second or vm.get(second, "enemy") != first:
            raise ValueError(f"E1M3 door team {team} changed")
        trigger_field = vm.get(first, "trigger_field")
        number = movers[first - 2]["renderEntity"]
        if trigger_model is not None:
            number, entity = authored[f"*{trigger_model}"]
            if name == "t78":
                _, relay = authored["*30"]
                if (relay.get("targetname"), relay.get("target")) != ("t76", name):
                    raise ValueError("E1M3 trap floor no longer follows the stock relay")
                for index in (first - 2, second - 2):
                    movers[index]["delayQ6"] = round(float(relay["delay"]) * 64)
            if (entity["classname"], entity.get("target"), vm.get(first, "targetname")) != (
                    "trigger_once", "t76" if name == "t78" else name, name):
                raise ValueError(f"E1M3 door team {team} no longer matches its stock trigger")
            bounds = _trigger(entity, models, origin)
        elif name == "gold":
            if trigger_field or vm.get(first, "items") != 262144:
                raise ValueError("E1M3 lock no longer requires the gold key")
            bounds = _contact(vm, (first, second), origin)
        else:
            if not trigger_field or vm.get(trigger_field, "owner") != first:
                raise ValueError(f"E1M3 door team {team} has no stock automatic trigger")
            bounds = _contact(vm, (trigger_field,), origin)
            vm.drop_slot += 1
        indices = [first - 2, second - 2]
        wait = vm.get(first, "wait")
        groups.append(_group(movers, name or f"door-{team[0]}", number, bounds, indices, wait))

    _, button = authored["*5"]
    _, relay = authored["*8"]
    if (button.get("target"), relay.get("targetname"), relay.get("target")) != ("t5", "t5", "t10"):
        raise ValueError("E1M3 exit button no longer drives its stock lift relay")
    button_index = slots[5] - 2
    for model, _ in E1M3_FINAL_MOVERS[1:]:
        index = slots[model] - 2
        target = relay["target"] if model == 9 else button["target"]
        if vm.get(slots[model], "targetname") != target:
            raise ValueError(f"E1M3 exit mover *{model} lost its stock target")
        delay = round(float(relay["delay"]) * 64) if model == 9 else 0
        movers[index]["delayQ6"] = movers[button_index]["ticksQ6"] + delay
        if model not in (3, 4):
            movers[index]["returnWaitQ6"] = round(vm.get(slots[model], "wait") * 64)
    final_indices = [slots[model] - 2 for model, _ in E1M3_FINAL_MOVERS]
    trains = [movers[slots[model] - 2] for model in (3, 4)]
    train_duration = max(train["ticksQ6"] for train in trains)
    for train in trains:
        for axis in ("trajectoryQ4", "secondTrajectoryQ4"):
            train[axis] += [train[axis][-1]] * (train_duration - train["ticksQ6"])
        train["ticksQ6"] = train_duration
        train["poseThresholds"][-1] = train_duration
    final = _group(movers, "t5", movers[button_index]["renderEntity"],
                   _contact(vm, (slots[5],), origin), final_indices)
    final["durationQ6"] = max(mover["delayQ6"] + mover["ticksQ6"] + (
        mover["ticksQ6"] + mover["returnWaitQ6"] if "returnWaitQ6" in mover else 0
    ) for mover in (movers[index] for index in final_indices))
    groups.append(final)

    stair_button = slots[E1M3_STAIR_BUTTON]
    if vm.get(stair_button, "takedamage") != 1 or vm.get(stair_button, "target") != "t12":
        raise ValueError("E1M3 stair switch no longer fires t12 when shot")
    stair_indices = [slots[model] - 2 for model, _ in E1M3_STAIR_MOVERS]
    stair_duration = max(movers[index]["ticksQ6"] for index in stair_indices[1:])
    thresholds = [(stair_duration * (2 * step - 1) + 5) // 6 for step in range(1, 4)]
    for model, _ in E1M3_STAIR_MOVERS[1:]:
        if vm.get(slots[model], "targetname") != "t12":
            raise ValueError(f"E1M3 stair *{model} lost its stock target")
        stair = movers[slots[model] - 2]
        ticks = stair["ticksQ6"]
        start, end = stair["positionsQ4"][::3]
        values = [start + (end - start) * min(age, ticks) // ticks for age in range(stair_duration + 1)]
        pose_times = [0, stair_duration // 3, stair_duration * 2 // 3, stair_duration]
        stair.update(ticksQ6=stair_duration, delayQ6=movers[stair_button - 2]["ticksQ6"],
                     trajectoryQ4=values, positionsQ4=[values[age] for age in pose_times],
                     positionsQ3=[values[age] // 2 for age in pose_times], poseThresholds=thresholds)
    stair_group = _group(movers, "t12", movers[stair_button - 2]["renderEntity"],
                         _contact(vm, (stair_button,), origin), stair_indices)
    groups.append(stair_group)

    number, tripwire = authored["*18"]
    if (tripwire["classname"], tripwire.get("target")) != ("trigger_once", "t13"):
        raise ValueError("E1M3 Nailgun tripwire no longer targets t13")
    door_indices = []
    for model, _ in E1M3_NAILGUN_DOORS:
        slot = slots[model]
        if vm.get(slot, "targetname") != "t13" or not int(vm.get(slot, "spawnflags")) & 1:
            raise ValueError(f"E1M3 Nailgun door *{model} must start open")
        index = slot - 2
        movers[index]["returnWaitQ6"] = round(vm.get(slot, "wait") * 64)
        door_indices.append(index)
    trap = _group(movers, "t13", number, _trigger(tripwire, models, origin), door_indices)
    trap["durationQ6"] = max(movers[i]["ticksQ6"] * 2 + movers[i]["returnWaitQ6"] for i in door_indices)
    groups.append(trap)

    platform = movers[slots[38] - 2]
    upper_number, upper_use = authored["*42"]
    _, lower_use = authored["*43"]
    if (upper_use.get("target"), lower_use.get("target"), vm.get(slots[38], "targetname")) != (
            "t82", "t82", "t82"):
        raise ValueError("E1M3 key-area lift no longer has both stock triggers")
    platform["useTriggers"] = [_trigger(entity, models, origin) for entity in (upper_use, lower_use)]
    platform["useTriggerEntity"] = upper_number
    platform["centerTouch"] = _contact(vm, (len(movers) + 2,), origin)
    # Leaves with the same timer only need one packed visual pose.
    linked = ((21, 22), (33, 34), (1, 2), (28, 29), (6, 10), (11, 12),
              tuple(range(13, 18)), (3, 4), (19, 20))
    representative = {model: team[0] for team in linked for model in team}
    packed = {}
    for mover in movers:
        model = mover["inlineModel"]
        shared = representative.get(model, model)
        source = movers[slots[shared] - 2]
        if any(mover[field] != source[field] for field in ("poseThresholds", "ticksQ6", "delayQ6")):
            raise ValueError(f"E1M3 brush *{model} cannot share visual timing with *{shared}")
        mover["poseSlot"] = packed.setdefault(shared, len(packed))
    if len(packed) != 16:
        raise ValueError("E1M3 visual pose mapping exceeds two packed words")

    (key_number, key_entity), = ((i, e) for i, e in enumerate(entities, 1)
                                 if e["classname"] == "item_key2")
    slot = vm.drop_slot
    vm.add(slot, {**key_entity, "origin": tuple(map(float, key_entity["origin"].split()))})
    vm.event(slot, "item_key2")
    vm.t = vm.get(slot, "nextthink")
    vm.set(slot, "nextthink", 0)
    vm.event(slot, "think")
    key_origin, mins, maxs = (vm.get(slot, field) for field in ("origin", "mins", "maxs"))
    lo, hi = pickup_eye_bounds(tuple(a - b for a, b in zip(key_origin, origin, strict=True)), mins, maxs)
    if vm.get(slot, "items") != 262144 or vm.get(slot, "solid") != 1:
        raise ValueError("E1M3 key did not become the stock gold key pickup")
    key = dict(entityNumber=key_number, model=vm.get(slot, "model"), origin=key_origin,
               trigger=dict(eyeMinQ4=lo, eyeMaxQ4=hi))
    return dict(movers=movers, groups=groups, goldKey=key,
                excludedModels=excluded_singleplayer_models(entities))
