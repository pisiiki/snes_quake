"""Exercise stock knight callbacks and pack the authored map roster."""

from struct import pack

from snes_tooling.quake.quakec_grunt import (
    ACTOR_FIELDS, DOG_GLOBAL_WORDS, GRUNT_SLOT, GruntReference, Q3_FIELDS,
)
from snes_tooling.quake.quakec_reference import asi


KNIGHT_MODEL = "progs/knight.mdl"
KNIGHT_SOUNDS = tuple(f"knight/{name}.wav" for name in (
    "kdeath", "khurt", "ksight", "sword1", "sword2", "idle",
))
KNIGHT_GLOBAL_WORDS = {key: value for key, value in DOG_GLOBAL_WORDS.items() if key != 9312}
KNIGHT_OPERANDS = {(287, 1): 80 * 8, (423, 1): 60 * 8, (452, 1): 60 * 8, (400, 0): 30 * 8}


def spawn_knights(spawn, entities, first_slot):
    roster = [(number, entity) for number, entity in enumerate(entities, 1)
              if entity["classname"] == "monster_knight"]
    spawn.drop_slot = first_slot + len(roster)
    spawn.add(spawn.drop_slot, {})
    return [spawn.spawn_grunt(slot, number, entity)
            for slot, (number, entity) in enumerate(roster, first_slot)]


def pack_knight_roster(spawn, knights, hull_origin, fields, conversion, stride):
    """Encode the shared sparse actor initializer without carrying a second VM."""
    rows = []
    for knight in knights:
        slot = knight["slot"]
        values = {}
        for name in dict.fromkeys((*fields, *ACTOR_FIELDS)):
            kind, offset = spawn.program.fields[name]
            for axis in range(3 if kind == 3 else 1):
                at = offset + axis
                raw = spawn.e[slot][at]
                if name in Q3_FIELDS:
                    value = spawn.get(slot, name)[axis]
                    if name in ("origin", "absmin", "absmax"):
                        value -= hull_origin[axis]
                    value = round(value * 8) & 0xffff
                elif name == "flags":
                    value = int(spawn.get(slot, name))
                elif name == "pausetime" and spawn.get(slot, name) >= 1e6:
                    value = 0x7fff
                else:
                    value = conversion(2 if kind == 3 else kind, raw, spawn)
                if value:
                    values[at * 2] = value
        rows.append(values)
    offsets = sorted({at for row in rows for at in row})
    if offsets and offsets[-1] >= stride:
        raise ValueError("knight fields exceed the shared edict stride")
    initial = b"".join(
        pack(f"<{1 + len(offsets)}H", knight["authoredSpawnflags"] & 0x700,
             *(row.get(at, 0) for at in offsets))
        for knight, row in zip(knights, rows, strict=True)
    )
    return initial, pack(f"<{len(offsets)}H", *offsets)


def cover_knight(vm, spawn):
    """Observe stock melee, charge, dodging, pain and death code before packing."""
    actor = GRUNT_SLOT
    edicts = {slot: cells.copy() for slot, cells in spawn.e.items()}
    globals_ = spawn.g.copy()
    initial = GruntReference(vm.program, vm.models, vm.archive, lambda origin, mins: origin)
    initial.e = {slot: cells.copy() for slot, cells in edicts.items()}
    initial.s = vm.s.copy()
    initial.spawn_grunt(actor, 0, {"classname": "monster_knight", "origin": "0 0 0"})
    edicts[actor] = initial.e[actor]
    saved = (vm.e, vm.g, vm.t, vm.client, vm.combat, vm.visible, vm.hits,
             vm.forced_random, vm.rng.getstate())

    def reset(distance, random):
        vm.e = {slot: cells.copy() for slot, cells in edicts.items()}
        vm.g = globals_.copy()
        vm.t = 5
        vm.client, vm.combat = 1, True
        vm.visible = vm.hits = True
        vm.forced_random = random
        vm.set(actor, "nextthink", 5)
        vm.t = 5
        vm.set(1, "origin", (distance, 0, 0))
        vm.link(1)
        vm.set(actor, "enemy", 1)
        vm.set(actor, "goalentity", 1)

    def animate(name, ticks):
        if name:
            vm.event(actor, name)
        for _ in range(ticks):
            vm.t = vm.get(actor, "nextthink")
            vm.event(actor, "think")

    try:
        reset(150, 0.125)
        vm.visible = False
        vm.set(actor, "enemy", 0)
        animate("knight_stand1", 9)
        animate("knight_walk1", 14)
        for distance in (40, 160):
            reset(distance, 0.125)
            vm.set(actor, "enemy", 0)
            vm.set(actor, "goalentity", 0)
            vm.set(actor, "angles", (0, 0, 0))
            vm.event(actor, "FindTarget")
            if vm.get(actor, "enemy") != 1:
                raise ValueError("stock knight did not see the nearby player")
            animate("knight_run1", 8)
        for distance in (40, 72, 96, 160):
            for random in (0.05, 0.35, 0.7, 0.95):
                reset(distance, random)
                animate("knight_run1", 8)
                animate("knight_attack", 14)
                if distance == 40 and vm.get(1, "health") >= 100:
                    raise ValueError("stock knight melee did not damage the player")
        for visible, hits, water in ((False, False, False), (True, False, False), (True, True, True)):
            reset(80, 0.125)
            vm.visible, vm.hits = visible, hits
            vm.g[79] = vm.g[80] = asi(water)
            vm.event(actor, "CheckAttack")
        for attack in ("knight_atk1", "knight_runatk1"):
            for distance, visible in ((40, True), (150, True), (40, False)):
                reset(distance, 0.125)
                vm.visible = visible
                animate(attack, 12)
        for random in (0.05, 0.7, 0.95):
            reset(40, random)
            vm.g[4], vm.g[7], vm.g[10], vm.g[13] = actor, 1, 1, asi(10)
            vm.event(1, "T_Damage")
            vm.g[4], vm.g[7], vm.g[10], vm.g[13] = actor, 1, 1, asi(10)
            vm.event(1, "T_Damage")
            animate(None, 13)
            vm.g[4], vm.g[7], vm.g[10], vm.g[13] = actor, 1, 1, asi(60)
            vm.event(1, "T_Damage")
            animate(None, 12)
            if vm.get(actor, "health") > 0:
                raise ValueError("stock knight death did not run")
        for blocked in range(1, 6):
            reset(40, 0.125)
            vm.g[4], vm.g[7] = 1, actor
            vm.trace_visibility = iter([False] * blocked + [True])
            vm.event(actor, "CanDamage")
        vm.trace_visibility = None
    finally:
        (vm.e, vm.g, vm.t, vm.client, vm.combat, vm.visible, vm.hits,
         vm.forced_random, rng) = saved
        vm.rng.setstate(rng)
        vm.trace_visibility = None
