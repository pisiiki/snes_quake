"""Host the original E1M1 soldier callbacks for the bounded cartridge VM."""
from math import atan2, degrees

from snes_tooling.quake.quakec_reference import ReferenceVM, asf, asi
from snes_tooling.quake.quakec_shell_pickups import PickupReference

GRUNT_SLOT = 7
START_TIME = 2
GRUNT_SOUNDS = (
    "soldier/sight1.wav", "soldier/sattck1.wav", "soldier/pain1.wav",
    "soldier/pain2.wav", "soldier/death1.wav", "soldier/idle.wav",
)
DOG_SOUNDS = ("dog/dsight.wav", "dog/dattack1.wav", "dog/dpain1.wav",
              "dog/ddeath.wav", "dog/idle.wav")
DOG_BITMAP_OPS = {15672, 15871}
# CanDamage probes four corners of the Q3 target. The leap also sets its
# initial vertical velocity directly in Q3.
DOG_GLOBAL_WORDS = {
    1513: 15 * 8, 1514: 15 * 8, 1526: -(15 * 8) & 0xffff, 1527: -(15 * 8) & 0xffff,
    1539: -(15 * 8) & 0xffff, 1540: 15 * 8, 1552: 15 * 8, 1553: -(15 * 8) & 0xffff,
    9312: 200 * 8,
}
DOG_OPERANDS = {
    (15630, 1): 100 * 8, (15656, 1): 300 * 8, (15672, 1): 512,
    (15864, 1): 8, (15867, 1): 300 * 8, (15871, 1): 512, (15875, 1): 512,
    (16084, 1): 80 * 8, (16087, 1): 150 * 8,
}
Q3_FIELDS = {"origin", "view_ofs", "mins", "maxs", "absmin", "absmax", "size", "velocity"}
ACTOR_FIELDS = (
    *sorted(Q3_FIELDS), "angles", "flags", "solid", "model", "movetype",
    "th_stand", "th_walk", "th_run", "th_missile", "th_melee", "th_pain", "th_die",
    "attack_finished", "attack_state", "pausetime", "show_hostile", "pain_finished",
    "ideal_yaw", "yaw_speed", "oldenemy", "goalentity", "movetarget",
    "effects", "ammo_shells", "v_angle",
)
COMBAT_BITMAP_OPS = {1008, 1012, 1402, 1446, 1447, 1448, 1460, 1494, 1537, 8388, 8395}
COMBAT_OPERANDS = {
    (742, 1): 120 * 8, (745, 1): 500 * 8, (748, 1): 1000 * 8,
    (1008, 1): 128, (1012, 1): 0,
    (1402, 1): 32, (1446, 0): 8192, (1446, 1): 16384, (1447, 1): 32768,
    (1460, 1): 8, (1494, 1): 64, (1537, 1): 32,
    (8388, 1): 1, (8392, 1): 1, (8395, 1): 2, (8399, 1): 2,
}


class GruntReference(PickupReference):
    """Stock soldiers, one local client, and controlled trace outcomes."""

    def __init__(self, *args):
        super().__init__(*args)
        self.client = 0
        self.visible = True
        self.trace_visibility = None
        self.combat = False
        self.hits = True
        self.forced_random = None
        self.path_corners = ()
        self.drop_slot = GRUNT_SLOT + 1
        self.check_bottom = True

    def builtin(self, number, name):
        g = self.g
        if name == "setmodel" and self.string(g[7]).endswith(".mdl"):
            self.set(g[4], "model", self.string(g[7]))
        elif name == "checkclient":
            g[1] = self.client if self.get(1, "health") > 0 else 0
        elif name == "walkmove":
            g[1] = asi(asf(g[7]) == 0)
        elif name == "checkbottom":
            g[1] = asi(self.check_bottom)
        elif name in ("movetogoal", "particle", "dprint"):
            pass
        elif name == "spawn":
            self.add(self.drop_slot, {})
            g[1] = self.drop_slot
        elif name == "vectoyaw":
            g[1] = asi(int(degrees(atan2(asf(g[5]), asf(g[4])))) % 360)
        elif name == "ChangeYaw":
            actor = g[28]
            x, yaw, z = self.get(actor, "angles")
            diff = (self.get(actor, "ideal_yaw") - yaw + 180) % 360 - 180
            step = self.get(actor, "yaw_speed")
            self.set(actor, "angles", (x, (yaw + min(step, max(-step, diff))) % 360, z))
        elif name == "random" and self.forced_random is not None:
            g[1] = asi(self.forced_random)
        elif name == "traceline" and self.combat:
            shooter = g[13]
            other = 1 if shooter >= GRUNT_SLOT else GRUNT_SLOT
            ignore = bool(asf(g[10]))
            alive = bool(self.get(other, "solid"))
            visible = self.visible if self.trace_visibility is None else next(self.trace_visibility)
            hit = visible and self.hits and not ignore and alive
            fraction = 0.5 if hit or not visible else 1
            g[70] = asi(fraction)
            g[71:74] = [asi(asf(g[i]) + (asf(g[i + 3]) - asf(g[i])) * fraction) for i in range(4, 7)]
            g[74:77] = [0, 0, asi(1)]
            g[78] = other if hit else 0
        elif name == "normalize":
            return ReferenceVM.builtin(self, number, name)
        else:
            return super().builtin(number, name)
        self.builtins[name, number] += 1

    def spawn_grunts(self, entities, *, include_dogs=False):
        soldiers = [(number, entity) for number, entity in enumerate(entities, 1)
                    if entity["classname"] == "monster_army"]
        if not soldiers or soldiers[0][0] != 22:
            raise ValueError("stock E1M1 grunt roster changed")
        dogs = [(number, entity) for number, entity in enumerate(entities, 1)
                if include_dogs and entity["classname"] == "monster_dog"]
        roster = soldiers + dogs
        self.drop_slot = GRUNT_SLOT + len(roster)
        self.add(self.drop_slot, {})
        return [self.spawn_grunt(slot, number, entity)
                for slot, (number, entity) in enumerate(roster, GRUNT_SLOT)]

    def spawn_grunt(self, slot, number, entity):
        origin = tuple(map(float, entity["origin"].split()))
        spawn = {key: value for key, value in entity.items()
                 if key != "target" or self.path_corners}
        self.add(slot, {**spawn, "origin": origin})
        self.event(slot, entity["classname"])
        old = self.t
        self.t = self.get(slot, "nextthink")
        self.event(slot, "think")
        self.t = old
        self.set(slot, "nextthink", START_TIME + 0.1 + ((slot - GRUNT_SLOT) % 6) / 64)
        flags = int(entity.get("spawnflags", 0))
        self.set(slot, "spawnflags", flags & 3)
        self.set(1, "view_ofs", (0, 0, 22))
        self.set(1, "mins", (-16, -16, -24))
        self.set(1, "maxs", (16, 16, 32))
        self.set(1, "size", (32, 32, 56))
        self.set(1, "solid", 3)
        self.set(1, "flags", 8)
        self.set(1, "takedamage", 2)
        self.set(1, "th_die", self.program.function_ids["SUB_Null"])
        return dict(entityNumber=number, slot=slot, model=self.get(slot, "model"),
                    authoredOrigin=origin, authoredYaw=float(entity.get("angle", 0)),
                    origin=self.get(slot, "origin"), angles=self.get(slot, "angles"),
                    health=int(self.get(slot, "health")), authoredSpawnflags=flags, target=entity.get("target"))

    def cover_axe(self):
        saved = (self.t, self.combat, self.visible, self.hits,
                 self.e, self.g, self.s, self.rng.getstate())
        self.e = {slot: cells.copy() for slot, cells in self.e.items()}
        self.g = self.g.copy()
        self.s = self.s.copy()
        try:
            self.t, self.combat = 5, True
            health = self.get(GRUNT_SLOT, "health")
            for visible, hit, damage in ((True, False, 0), (False, False, 0),
                                         (True, True, 20), (True, True, 40)):
                self.visible, self.hits = visible, hit
                self.event(1, "W_FireAxe")
                if self.get(GRUNT_SLOT, "health") != health - damage:
                    raise ValueError("stock axe hit and damage coverage changed")
                self.t += 1
        finally:
            (self.t, self.combat, self.visible, self.hits, self.e, self.g,
             self.s, rng) = saved
            self.rng.setstate(rng)

    def cover_grunt(self, spawn):
        self.combat = True
        self.client = 1
        initial_edicts = {k: v.copy() for k, v in spawn.e.items()}
        initial_globals = self.g.copy()

        def reset(position):
            self.e = {k: v.copy() for k, v in initial_edicts.items()}
            self.g = initial_globals.copy()
            self.t = START_TIME
            self.set(1, "origin", position)
            self.link(1)
            self.visible = self.hits = True

        def think():
            self.t = max(self.t + 0.01, self.get(GRUNT_SLOT, "nextthink"))
            self.event(GRUNT_SLOT, "think")

        for pos, visible, awake in (
            ((560, 72, 40), False, False),
            ((680, 208, 72), True, False),
            ((604, 736, 104), True, False),
            ((616, -1200, 40), True, False),
            ((560, 72, 40), True, True),
        ):
            reset(pos)
            self.visible = visible
            for _ in range(12):
                think()
            if bool(self.get(GRUNT_SLOT, "enemy")) != awake:
                raise ValueError("stock grunt perception differs from fixture")
        # A single actor can only hear its own recent sight event. Exercise
        # the stock early return when it has just lost its enemy.
        reset((560, 72, 40))
        self.g[self.program.globals["sight_entity"]] = GRUNT_SLOT
        self.g[self.program.globals["sight_entity_time"]] = asi(self.t)
        self.event(GRUNT_SLOT, "FindTarget")
        for pos in ((560, 72, 40), (360, 72, 40), (0, 72, 40)):
            reset(pos)
            self.forced_random = 0.02
            for _ in range(55):
                think()
            if self.get(1, "health") >= 100:
                raise ValueError("stock grunt did not damage the player")
            self.visible = False
            for _ in range(14):
                think()
            self.visible = True
            self.hits = False
            for _ in range(14):
                think()
            self.hits = True
            self.set(1, "origin", (616, -1200, 40))
            self.link(1)
            for _ in range(14):
                think()
            self.set(1, "origin", pos)
            self.link(1)
            self.forced_random = 0.95
            self.set(1, "health", 4)
            for _ in range(5):
                think()
            self.forced_random = 0.02
            for _ in range(55):
                think()

        # Sweep independent stock random decisions (attack acceptance,
        # cooldown, strafing side and refire) in addition to forced cases.
        self.forced_random = None
        for seed in range(8):
            self.rng.seed(seed)
            reset((560, 72, 40))
            for _ in range(95):
                think()

        for random in (0.02, 0.35, 0.8):
            reset((560, 72, 40))
            self.forced_random = random
            self.set(1, "button0", 1)
            self.event(1, "W_WeaponFrame")
            if self.get(GRUNT_SLOT, "health") != 6:
                raise ValueError("stock shotgun did not apply six pellets of damage")
            for _ in range(16):
                think()
            self.t += 1
            self.event(1, "W_WeaponFrame")
            if self.get(GRUNT_SLOT, "health") > 0 or self.get(GRUNT_SLOT, "takedamage"):
                raise ValueError("stock soldier death was not reached")
            for _ in range(14):
                think()

        # A later attack can reach the same target after death disabled damage.
        dead_soldier = self.e[GRUNT_SLOT].copy()
        self.g[4], self.g[7], self.g[10], self.g[13] = GRUNT_SLOT, 1, 1, asi(4)
        self.event(1, "T_Damage")
        if self.e[GRUNT_SLOT] != dead_soldier:
            raise ValueError("stock damage changed a damage-disabled soldier")

        # A second soldier can follow a recent sight event or retaliate
        # against the actual attacker. Pack those stock branches as well.
        reset((560, 72, 40))
        second = GRUNT_SLOT + 1
        self.set(second, "origin", (620, 96, 40))
        self.link(second)
        think()
        self.event(second, "FindTarget")
        if self.get(second, "enemy") != 1:
            raise ValueError("a second grunt did not acquire the stock sight target")
        self.g[4], self.g[7], self.g[10], self.g[13] = second, GRUNT_SLOT, GRUNT_SLOT, asi(4)
        self.event(GRUNT_SLOT, "T_Damage")
        if self.get(second, "enemy") != GRUNT_SLOT or self.get(second, "oldenemy") != 1:
            raise ValueError("stock grunt infighting did not preserve the old target")
        self.set(GRUNT_SLOT, "health", 0)
        self.event(second, "ai_run")
        if self.get(second, "enemy") != 1:
            raise ValueError("stock grunt did not return to the player after infighting")

        self.combat = False
        self.forced_random = None
