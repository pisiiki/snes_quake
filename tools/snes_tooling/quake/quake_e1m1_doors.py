"""E1M1's remaining stock func_door chains and far-side button."""

from dataclasses import replace

from snes_tooling.quake.quakec_grunt import GruntReference


DOOR_MODELS = (15, 17, 19, 34, 35, 36, 37, 38)
SHOOT_TRIGGER = 16
SHOT_TERMINAL = -72


def ordinary_doors(program, archive, models, entities, drop, origin, eye_bounds):
    from snes_tooling.quake.quake_start_hub import _trigger_bounds

    by_model = {e["model"]: (n, e) for n, e in enumerate(entities, 1) if "model" in e}
    doors = []
    for model in DOOR_MODELS:
        number, ent = by_model[f"*{model}"]
        button = ent["classname"] == "func_button"
        vm = GruntReference(program, models, archive, drop)
        vm.pusher_slots = (2,)
        vm.add(0, {"classname": "worldspawn"})
        vm.add(1, {"classname": "player", "health": 100})
        vm.add(2, ent)
        vm.event(2, ent["classname"])
        if not button:
            vm.drop_slot = 3
            vm.set(2, "nextthink", 0)
            vm.event(2, "LinkDoors")
        endpoints = [[round(q * 16) for q in vm.get(2, n)] for n in ("pos1", "pos2")]
        axis, = (i for i, (a, b) in enumerate(zip(*endpoints)) if a != b)
        rest, active = (p[axis] for p in endpoints)
        wait = round(vm.get(2, "wait") * 64)
        vm.event(2, "use", 1)
        path = [rest]
        while vm.get(2, "state") == 2 and len(path) < 128:
            vm.step(1 / 64)
            path.append(round(vm.get(2, "origin")[axis] * 16))
        if path[-1] != active or len(path) < 2:
            raise ValueError(f"stock E1M1 *{model} did not reach its authored position")
        sounds = [ev[3] for ev in vm.events if ev[0] == "sound"]
        returning = []
        if wait > 0:
            while vm.get(2, "state") == 0:
                vm.step(1 / 64)
            returning = [active]
            while vm.get(2, "state") == 3 and len(returning) <= len(path):
                vm.step(1 / 64)
                returning.append(round(vm.get(2, "origin")[axis] * 16))
            if len(returning) != len(path) or returning[-1] != rest:
                raise ValueError(f"stock E1M1 *{model} did not return")
        if button:
            sn, sensor = number, ent
        else:
            (sn, sensor), = ((i, e) for i, e in enumerate(entities, 1)
                             if e.get("target") == ent["targetname"] and e["classname"].startswith("trigger_"))
        tones = [(i, e) for i, e in enumerate(entities, 1)
                 if e["classname"] == "light" and e.get("targetname") == sensor.get("target")]
        hint = dict(hintBounds=_trigger_bounds(ent, models, origin)) if "message" in ent else {}
        pusher = {}
        if model == 15:
            if axis != 2 or wait <= 0 or vm.get(2, "blocked") != program.function_ids["door_blocked"]:
                raise ValueError("t4 hydraulic pusher differs from stock")
            pusher = dict(riderBounds=eye_bounds(vm.get(2, "mins"), vm.get(2, "maxs"), origin, touch=False),
                          floorEyeQ4=round((vm.get(2, "maxs")[2] + 46 - origin[2]) * 16))
        doors.append(dict(**hint, **pusher, inlineModel=model, renderEntity=number, axis=axis, startQ4=rest, endQ4=active,
                          outwardQ4=path, returnQ4=returning, durationQ6=len(path) - 1, waitQ6=wait,
                          speed=vm.get(2, "speed"), damage=vm.get(2, "dmg"), sounds=sounds,
                          button=button, message=ent.get("message", ""), sensor=sn,
                          triggerModel=int(sensor["model"][1:]), triggerClass=sensor["classname"],
                          shotHealth=int(sensor.get("health","0")), target=sensor.get("target"),
                          triggerNoise=int(sensor.get("sounds",0)),
                          spawnflags=int(ent.get("spawnflags",0)), triggerSpawnflags=int(sensor.get("spawnflags",0)),
                          lightStyles=[int(e["style"]) for _, e in tones],
                          **_trigger_bounds(sensor, models, origin)))
    return doors


def add_ordinary_pose_rows(rows, brushes, doors):
    by_model = {b.inline_model: b for b in brushes}
    sources = [by_model[d["inlineModel"]] for d in doors]
    def state(door, brush, distance):
        start, stop = door["startQ4"], door["endQ4"]
        direction = 1 if stop > start else -1
        offset = start + direction * min(abs(stop - start), distance * 64)
        origin = tuple(offset / 16 if i == door["axis"] else 0. for i in range(3))
        return replace(brush, origin=origin)
    stops = [(abs(d["endQ4"] - d["startQ4"]) + 63) // 64 for d in doors]
    for door in doors:
        door["visualRows"] = [0]
    base = rows[0].brushes
    closed = tuple(state(d, b, 0) for d, b in zip(doors, sources, strict=True))
    rows = [replace(row, brushes=(*row.brushes, *closed)) for row in rows]
    for distance in range(1, max(stops) + 1):
        poses = []
        for door, brush, last in zip(doors, sources, stops, strict=True):
            poses.append(state(door, brush, distance))
            if distance <= last:
                door["visualRows"].append(len(rows))
        rows.append(replace(rows[0], index=len(rows), brushes=(*base, *poses)))
    return rows
