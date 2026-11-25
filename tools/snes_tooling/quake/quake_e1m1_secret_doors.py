"""Derive E1M1's two-stage sliding panels from the original QuakeC callbacks."""

from dataclasses import replace

from snes_tooling.quake.quakec_reference import ReferenceVM


SECRET_DOOR_MODELS = (10, 13, 14, 21, 23, 41, 43)
VISUAL_STEP_Q4 = 64  # One native Q2 brush coordinate is four Quake units.


def _leg(vm):
    start = tuple(round(v * 16) for v in vm.get(2, "origin"))
    for tick in range(1, 257):
        vm.step(1 / 64)
        if not any(vm.get(2, "velocity")):
            end = tuple(round(v * 16) for v in vm.get(2, "origin"))
            axes = [axis for axis in range(3) if start[axis] != end[axis]]
            if len(axes) != 1 or axes[0] == 2:
                raise ValueError("E1M1 secret door must slide along one horizontal axis per leg")
            axis = axes[0]
            return dict(axis=axis, travelQ4=end[axis] - start[axis], durationQ6=tick)
    raise ValueError("E1M1 secret door did not reach its stock stop")


def _wait(vm):
    ticks = round((vm.get(2, "nextthink") - vm.get(2, "ltime")) * 64)
    if not 0 < ticks <= 320:
        raise ValueError("invalid E1M1 secret door dwell time")
    for _ in range(ticks):
        vm.step(1 / 64)
    return ticks


def secret_doors(program, entities, models):
    from snes_tooling.quake.quake_start_hub import _trigger_bounds

    lamps = [e for e in entities if e.get("targetname") == "t3" and e["classname"] == "light"]
    if len(lamps) != 5 or any(e.get("style") != "32" or int(e.get("spawnflags", 0)) & 1 for e in lamps):
        raise ValueError("E1M1 t3 must address five initially lit style-32 lamps")
    controls = [e for e in entities if e.get("target") == "t3"]
    if [(e["classname"], e.get("model"), e.get("sounds")) for e in controls] != [
            ("trigger_once", "*11", "3"), ("trigger_once", "*12", "3")]:
        raise ValueError("E1M1 t3 must use both original one-shot sound triggers")
    control_bits = {e["model"]: 1 << i for i, e in enumerate(controls)}
    origin = tuple((models[0][i] + models[0][i + 3]) / 2 for i in range(3))
    doors = []
    for number, ent in enumerate(entities, 1):
        if ent.get("classname") != "func_door_secret":
            continue
        vm = ReferenceVM(program, models)
        vm.pusher_slots = (2,)
        vm.add(0, {"classname": "worldspawn"})
        vm.add(1, {"classname": "player", "health": 100})
        vm.add(2, ent)
        vm.event(2, "func_door_secret")
        shootable = bool(vm.get(2, "takedamage"))
        sounds = [vm.get(2, key) for key in ("noise1", "noise2", "noise3")]
        vm.event(2, "use", 1)
        first = _leg(vm)
        first_wait = _wait(vm)
        second = _leg(vm)
        permanent = int(ent.get("spawnflags", "0")) & 1 != 0
        open_wait = 0
        if not permanent:
            open_wait = _wait(vm)
            for opening in (second, first):
                closing = _leg(vm)
                if (closing["axis"] != opening["axis"] or closing["travelQ4"] != -opening["travelQ4"]
                        or closing["durationQ6"] != opening["durationQ6"]):
                    raise ValueError("stock E1M1 secret door did not retrace its opening movement")
                if opening is second and _wait(vm) != first_wait:
                    raise ValueError("stock E1M1 secret door used asymmetric corner waits")
        target = ent.get("targetname")
        links = []
        for link_number, source in enumerate(entities, 1):
            if not target or source.get("target") != target:
                continue
            if source["classname"] not in ("trigger_once", "trigger_multiple"):
                raise ValueError("unsupported E1M1 secret door activation")
            links.append(dict(entityNumber=link_number, inlineModel=int(source["model"][1:]),
                              shot=bool(int(source.get("health", "0"))),
                              once=source["classname"] == "trigger_once",
                              **_trigger_bounds(source, models, origin)))
            if target == "t3":
                links[-1]["t3TriggerBit"] = control_bits[source["model"]]
        doors.append(dict(renderEntity=number, inlineModel=int(ent["model"][1:]), shootable=shootable,
                          links=links, touchMessage=ent.get("message", ""), sounds=sounds,
                          speed=vm.get(2, "speed"), legs=[first, second], cornerWaitQ6=first_wait,
                          openWaitQ6=open_wait, permanent=permanent,
                          **_trigger_bounds(ent, models, origin)))
    if tuple(row["inlineModel"] for row in doors) != SECRET_DOOR_MODELS:
        raise ValueError("stock E1M1 secret door roster changed")
    return doors


def add_secret_pose_rows(rows, brushes, doors):
    sources = {s.inline_model: s for s in brushes}
    for door in doors:
        door["visualRows"] = [0]
    closed = tuple(sources[d["inlineModel"]] for d in doors)
    base = rows[0].brushes
    rows = [replace(row, brushes=(*row.brushes, *closed)) for row in rows]
    distances = [sum(abs(leg["travelQ4"]) for leg in d["legs"]) for d in doors]
    for distance in range(VISUAL_STEP_Q4, max(distances) + 1, VISUAL_STEP_Q4):
        poses = []
        for door, source, total in zip(doors, closed, distances, strict=True):
            remaining = min(distance, total)
            position = [0., 0., 0.]
            for leg in door["legs"]:
                delta = min(remaining, abs(leg["travelQ4"]))
                position[leg["axis"]] = (delta if leg["travelQ4"] > 0 else -delta) / 16
                remaining -= delta
            poses.append(replace(source, origin=tuple(position)))
            if distance <= total:
                door["visualRows"].append(len(rows))
        rows.append(replace(rows[0], index=len(rows), brushes=(*base, *poses)))
    return rows
