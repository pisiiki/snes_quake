"""Record the two E1M1 platform trajectories and touch rules from stock progs.dat."""

from snes_tooling.quake.quakec_grunt import GruntReference


def build_platforms(program, archive, models, entities, drop, origin, eye_bounds):
    records = []
    for number, entity in enumerate(entities, 1):
        if entity.get("classname") != "func_plat":
            continue
        model = int(entity["model"][1:])
        vm = GruntReference(program, models, archive, drop)
        vm.add(0, {"classname": "worldspawn"})
        vm.add(1, {"classname": "player", "health": 100})
        vm.add(2, entity)
        vm.drop_slot = 3
        vm.pusher_slots = (2,)
        vm.event(2, "func_plat")
        if vm.get(3, "enemy") != 2 or vm.get(2, "state") != 1:
            raise ValueError(f"E1M1 platform *{model} must start down with a center trigger")
        touch = eye_bounds(vm.get(3, "absmin"), vm.get(3, "absmax"), origin, touch=True)
        vm.event(3, "touch", 1)
        def move(state):
            positions = [round(vm.get(2, "origin")[2] * 16)]
            while vm.get(2, "state") == state and len(positions) < 256:
                vm.step(1 / 64)
                positions.append(round(vm.get(2, "origin")[2] * 16))
            return positions
        ascent = move(2)
        if vm.get(2, "state") != 0:
            raise ValueError(f"E1M1 platform *{model} failed to reach its upper stop")
        wait = round((vm.get(2, "nextthink") - vm.get(2, "ltime")) * 64)
        vm.event(3, "touch", 1)
        touch_wait = round((vm.get(2, "nextthink") - vm.get(2, "ltime")) * 64)
        for _ in range(touch_wait):
            vm.step(1 / 64)
        descent = move(3)
        if (vm.get(2, "state") != 1 or len(ascent) != len(descent)
                or ascent[:1] != descent[-1:] or ascent[-1:] != descent[:1]):
            raise ValueError(f"E1M1 platform *{model} failed its stock return cycle")
        ticks = len(ascent) - 1
        thresholds = [(ticks * pose + 2) // 3 for pose in range(1, 4)]
        positions = [ascent[t] for t in (0, *thresholds)]
        floor = vm.get(2, "maxs")[2]
        records.append(dict(
            inlineModel=model, renderEntity=number, axis=2, ticksQ6=ticks,
            speed=vm.get(2, "speed"), positionsQ4=positions, positionsQ3=[q // 2 for q in positions],
            poseThresholds=thresholds, ascentQ4=ascent, descentQ4=descent, platformTouch=touch,
            waitQ6=wait, occupiedWaitQ6=touch_wait, floorEyeQ4=round((floor+46-origin[2])*16),
            riderBounds=eye_bounds(vm.get(2, "mins"), vm.get(2, "maxs"), origin, touch=False),
            moveSound=vm.get(2, "noise"), stopSound=vm.get(2, "noise1"),
        ))
    if [record["inlineModel"] for record in records] != [7, 22]:
        raise ValueError("stock E1M1 platform roster changed")
    return records
