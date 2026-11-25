"""Compile the authored explosive box and exercise its stock QuakeC callbacks."""

from math import dist

from snes_tooling.quake.quakec_grunt import GruntReference
from snes_tooling.quake.quakec_reference import asf, asi
from snes_tooling.quake.quakec_shell_pickups import floor_drop


class ExploboxReference(GruntReference):
    """Server builtins used by the original barrel_explode and T_RadiusDamage."""

    def __init__(self, program, models, archive, drop):
        super().__init__(program, models, archive, drop)
        self.unobstructed = True
        self.removed = set()
        self.particles = []
        self.combat = True

    def builtin(self, number, name):
        g = self.g
        if name == "findradius":
            origin = tuple(map(asf, g[4:7]))
            radius, chain = asf(g[7]), 0
            for entity in sorted(self.e):
                if not self.get(entity, "solid"):
                    continue
                center = tuple(o + (a + b) * 0.5 for o, a, b in zip(
                    self.get(entity, "origin"), self.get(entity, "mins"), self.get(entity, "maxs")))
                if dist(center, origin) <= radius:
                    self.set(entity, "chain", chain)
                    chain = entity
            g[1] = chain
        elif name == "particle":
            self.particles.append((tuple(map(asf, g[4:7])), tuple(map(asf, g[7:10])), asf(g[10]), asf(g[13])))
        elif name == "traceline":
            g[70] = asi(1 if self.unobstructed else 0.5)
            g[78] = 0
        elif name == "setmodel" and self.string(g[7]).endswith(".spr"):
            self.set(g[4], "model", self.string(g[7]))
        elif name == "remove":
            self.removed.add(g[4])
            self.set(g[4], "model", "")
            self.set(g[4], "solid", 0)
            self.set(g[4], "nextthink", 0)
        else:
            return super().builtin(number, name)
        self.builtins[name, number] += 1


def spawn_explobox(vm, entities, slot):
    authored = [(n, e) for n, e in enumerate(entities, 1) if e["classname"] == "misc_explobox"]
    if len(authored) != 1 or int(authored[0][1].get("spawnflags", 0)):
        raise ValueError("expected the single stock E1M1 explosive box on all skills")
    entity_number, entity = authored[0]
    spawn = tuple(map(float, entity["origin"].split()))
    vm.add(slot, {**entity, "origin": spawn})
    vm.event(slot, "misc_explobox")
    return dict(entityNumber=entity_number, model=vm.get(slot, "model"), origin=vm.get(slot, "origin"),
                mins=vm.get(slot, "mins"), maxs=vm.get(slot, "maxs"), health=int(vm.get(slot, "health")),
                solid=int(vm.get(slot, "solid")), damageable=int(vm.get(slot, "takedamage")),
                deathFunction=vm.get(slot, "th_die"))


def stock_explobox(archive, bsp, entities, models, program, trace=None):
    drop = floor_drop(bsp, models[0][10], supporting_roots=(models[3][10], models[4][10]))
    for distance, visible, expected_health in ((96, True, 88), (96, False, 200), (240, True, 200)):
        vm = ExploboxReference(program, models, archive, drop)
        vm.t = 2
        vm.add(0, {"classname": "worldspawn"})
        box = spawn_explobox(vm, entities, 2)
        origin = box["origin"]
        vm.add(1, dict(classname="player", health=200, takedamage=2, solid=2, flags=8, movetype=3,
                       origin=(origin[0] + distance, origin[1], origin[2]),
                       mins=(-16, -16, -24), maxs=(16, 16, 32)))
        vm.link(1)
        vm.pcs.clear()
        vm.stats.clear()
        vm.unobstructed = visible
        vm.g[4], vm.g[7], vm.g[10], vm.g[13] = 2, 1, 1, asi(10)
        vm.event(1, "T_Damage")
        if vm.get(2, "health") != 10 or not vm.get(2, "solid"):
            raise ValueError("stock explosive box failed to survive the first hit")
        vm.g[4], vm.g[7], vm.g[10], vm.g[13] = 2, 1, 1, asi(10)
        vm.event(1, "T_Damage")
        if vm.get(1, "health") != expected_health or vm.get(2, "solid") or vm.get(2, "takedamage"):
            raise ValueError("stock explosive box radius, obstruction or death behavior changed")
        if vm.particles != [(origin, (0, 0, 0), 75, 255)]:
            raise ValueError("stock barrel failed to emit its client explosion at the original box origin")
        frames = []
        box.update(explosionModel=vm.get(2, "model"), explosionOrigin=vm.get(2, "origin"),
                   sound=next(e[3] for e in vm.events if e[0] == "sound"))
        while 2 not in vm.removed and len(frames) <= 6:
            frames.append(int(vm.get(2, "frame")))
            vm.t = vm.get(2, "nextthink")
            vm.set(2, "nextthink", 0)
            vm.event(2, "think")
        if frames != list(range(6)) or 2 not in vm.removed:
            raise ValueError("unexpected stock explosive box animation or removal")
        box["frames"] = frames
        if trace is not None:
            trace.pcs.update(vm.pcs)
            trace.stats.update(vm.stats)
    # The nearby Easy soldier can be killed by the radius without a second shot.
    vm = ExploboxReference(program, models, archive, drop)
    vm.t = 2
    vm.add(0, {"classname": "worldspawn"})
    vm.add(1, {"classname": "player", "health": 100})
    soldier = next((i, e) for i, e in enumerate(entities, 1) if e["classname"] == "monster_army"
                   and e["origin"] == "80 2024 -184" and not int(e.get("spawnflags", 0)) & 256)
    vm.spawn_grunt(7, *soldier)
    spawn_explobox(vm, entities, 2)
    vm.set(1, "origin", (origin[0] + 96, origin[1], origin[2]))
    vm.link(1)
    vm.pcs.clear()
    vm.stats.clear()
    vm.g[4], vm.g[7], vm.g[10], vm.g[13] = 2, 1, 1, asi(20)
    vm.event(1, "T_Damage")
    if vm.get(7, "model") != "progs/h_guard.mdl" or vm.get(7, "health") != -99 or vm.get(1, "health") != -12:
        raise ValueError("stock explosive box failed its nearby actor and player damage controls")
    if trace is not None:
        trace.pcs.update(vm.pcs)
        trace.stats.update(vm.stats)
    return box
