"""Recover the E1M1 Super Shotgun and its firing paths from stock QuakeC."""

from snes_tooling.quake.quake_start_ambient import key_actor
from snes_tooling.quake.quakec_grunt import GruntReference
from snes_tooling.quake.quakec_reference import ReferenceVM
from snes_tooling.quake.quakec_shell_pickups import floor_drop, pickup_eye_bounds


def cover_fire(trace, spawn, program, models, archive):
    """Preserve both original firing paths, including a single remaining shell."""
    result = {}
    for shells, pellets, cost, sound in ((5, 14, 2, "weapons/shotgn2.wav"), (1, 6, 1, "weapons/guncock.wav")):
        vm = GruntReference(program, models, archive, None)
        vm.add(0, {"classname": "worldspawn"})
        vm.add(1, {"classname": "player", "health": 100, "weapon": 2, "items": 4099, "button0": 1,
                   "ammo_shells": shells, "currentammo": shells, "absmin": (-17, -17, -25), "size": (32, 32, 56)})
        vm.event(1, "W_WeaponFrame")
        if (len(vm.rays), vm.get(1, "ammo_shells"), round(vm.get(1, "attack_finished"), 2),
                [event[3] for event in vm.events if event[0] == "sound"]) != (pellets, shells - cost, 0.7, [sound]):
            raise ValueError("original Super Shotgun firing behavior changed")
        trace.pcs.update(vm.pcs)
        trace.stats.update(vm.stats)
        view = ReferenceVM(program, models)
        view.e[1] = vm.e[1].copy()
        sequence = []
        for _ in range(8):
            frame = int(view.get(1, "weaponframe"))
            sequence.append((round(view.t * 60), frame))
            if not frame:
                break
            view.t = view.get(1, "nextthink")
            view.event(1, "think")
        if sequence != [(6 * i, frame) for i, frame in enumerate((1, 2, 3, 4, 5, 6, 0))]:
            raise ValueError("stock Super Shotgun animation schedule changed")
        result["double" if shells > 1 else "single"] = dict(pellets=pellets, shellCost=cost, sound=sound)
    # Ordinary shell boxes call W_BestWeapon and W_SetCurrentAmmo even while
    # the player holds another gun. Keep those post-pickup branches too.
    for weapon, items in ((1, 4099), (2, 4099), (4, 4103)):
        vm = GruntReference(program, models, archive, None)
        vm.s.update(spawn.s)
        vm.e[0] = spawn.e[0].copy()
        vm.e[4] = spawn.e[4].copy()
        vm.add(1, {"classname": "player", "health": 100, "flags": 8, "items": items, "weapon": weapon,
                   "ammo_shells": 5, "ammo_nails": 8, "currentammo": 8 if weapon == 4 else 5})
        vm.event(4, "touch", 1)
        if vm.get(1, "ammo_shells") != 25:
            raise ValueError("stock shell pickup with the Super Shotgun changed")
        trace.pcs.update(vm.pcs)
        trace.stats.update(vm.stats)
    return dict(**result, viewSequence=sequence, cooldownSeconds=0.7)


def stock_pickup(archive, bsp, entities, models, program, row):
    drop = floor_drop(bsp, models[0][10], supporting_roots=(models[3][10], models[4][10]))
    vm = GruntReference(program, models, archive, drop)
    vm.add(0, {"classname": "worldspawn"})
    (number, entity), = [(i, e) for i, e in enumerate(entities, 1) if e["classname"] == "weapon_supershotgun"
                         and not int(e.get("spawnflags", 0)) & 0x100]
    vm.add(2, {**entity, "origin": tuple(map(float, entity["origin"].split()))})
    vm.event(2, entity["classname"])
    vm.t = vm.get(2, "nextthink")
    vm.event(2, "think")
    origin = vm.get(2, "origin")
    item = key_actor(dict(entityNumber=number, model=vm.get(2, "model"), origin=origin), models)
    lo, hi = pickup_eye_bounds(origin, vm.get(2, "mins"), vm.get(2, "maxs"))
    vm.add(1, {"classname": "player", "health": 100, "flags": 8, "items": 4097, "weapon": 1, "ammo_shells": 25})
    vm.event(2, "touch", 1)
    amount = int(vm.get(1, "ammo_shells") - 25)
    if (number, item["model"], amount, vm.get(1, "weapon")) != (273, "progs/g_shot.mdl", 5, 2):
        raise ValueError("original Easy Super Shotgun pickup changed")
    return dict(**item, amount=amount, spriteRow=row, triggerEyeMinQ4=lo, triggerEyeMaxQ4=hi)
