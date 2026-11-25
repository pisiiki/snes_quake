"""Pack a bounded cartridge VM slice of the stock shareware E1M1 program."""

from dataclasses import replace
from math import atan, degrees
from hashlib import file_digest, sha256
from pathlib import Path
from struct import calcsize, iter_unpack, pack, unpack_from

from snes_tooling.quake.quakec_reference import asf, asi
from snes_tooling.quake.quakec_shell_pickups import (
    INVENTORY_OPS, SHELL_FIELDS, SHELL_OPERANDS, SHELL_SOUND, floor_drop,
)
from snes_tooling.quake.quakec_grunt import (
    ACTOR_FIELDS, COMBAT_BITMAP_OPS, COMBAT_OPERANDS, GRUNT_SLOT,
    DOG_BITMAP_OPS, DOG_GLOBAL_WORDS, DOG_OPERANDS, DOG_SOUNDS, GRUNT_SOUNDS, Q3_FIELDS, START_TIME, GruntReference,
)
from snes_tooling.quake.quakec_knight import KNIGHT_GLOBAL_WORDS, KNIGHT_OPERANDS, KNIGHT_SOUNDS, cover_knight
from snes_tooling.quake.quakec_shotgun import SHOT_FIELDS, SHOT_GLOBALS, SHOT_OPERANDS
from snes_tooling.quake import quakec_patrol
from snes_tooling.quake.quake_e1m1_exit_assets import add_exit_pose_rows, build_exit_machinery, exit_machinery_outputs

PROGRAM_HASH = "f2619787f9aa0f057246eea1665b622b4691b5c5a800b1a46133d1fe8b771580"
BSP_HASH = "7b7061ec63c3e8ecb9c0e0a8075f18823efea6578666d57d601c191bcaf16c26"
ENTITY_STRIDE = 512
SCALE = 64
DOOR_STEPS = 16
BUTTON_STEPS = 2
ENTRANCE_STEPS = 16
# Stock Quake's VM ABI includes three return words and eight three-word parameters.
ABI_WORDS = 32


class Program:
    def __init__(self, data):
        if sha256(data).hexdigest() != PROGRAM_HASH:
            raise ValueError("E1M1 gameplay requires the original shareware progs.dat")
        version, crc, *header = unpack_from("<15i", data)
        if (version, crc) != (6, 5927):
            raise ValueError("unsupported QuakeC ABI")

        def records(index, fmt):
            start, count = header[index * 2:index * 2 + 2]
            return tuple(iter_unpack(fmt, data[start:start + count * calcsize(fmt)]))

        self.strings = bytes(v for v, in records(4, "<B"))
        self.functions = records(3, "<7i8B")
        self.names = tuple(self.string(fn[4]) for fn in self.functions)
        self.function_ids = {name: i for i, name in enumerate(self.names)}
        self.statements = records(0, "<Hhhh")
        self.initial = tuple(v for v, in records(5, "<I"))
        self.fields = {self.string(name): (kind, offset)
                       for kind, offset, name in records(2, "<HHi")}
        self.entity_fields = header[-1]
        self.types = {}
        self.globals = {self.string(name): offset for _, offset, name in records(1, "<HHi")}
        for kind, offset, _ in records(1, "<HHi"):
            kind &= 0x7fff
            for i in range(3 if kind == 3 else 1):
                self.types[offset + i] = 2 if kind == 3 else kind

    def string(self, index):
        return self.strings[index:self.strings.index(0, index)].decode("latin1")


def _word(kind, value, vm):
    if kind == 1:
        # All supported string operations compare contents. Stock null is 0.
        name = vm.string(value)
        return vm.string_ids.setdefault(name, len(vm.string_ids))
    if kind == 2:
        fixed = round(asf(value) * SCALE)
        if not -32768 <= fixed <= 32767:
            raise ValueError(f"QuakeC numeric value out of range: {asf(value)}")
        return fixed & 0xffff
    if kind == 4:
        return value * ENTITY_STRIDE
    if kind == 5:
        return value * 2
    if 0 <= value <= 0xffff:
        return value
    raise ValueError(f"untyped QuakeC value out of range: {value:#x}")


# Operand widths in source cells. The branch displacement is translated to a
# cartridge code offset and is separate from the global-cell operands.
_OPERANDS = {
    0:(3,0,0), 1:(1,1,1), 2:(3,3,1), 3:(1,3,3), 4:(3,1,3), 5:(1,1,1), 6:(1,1,1),
    7:(3,3,3), 8:(1,1,1), 9:(3,3,3), 10:(1,1,1), 11:(3,3,1), 12:(1,1,1),
    13:(1,1,1), 15:(1,1,1), 17:(1,1,1), 18:(1,1,1), 19:(1,1,1), 20:(1,1,1),
    21:(1,1,1), 22:(1,1,1), 23:(1,1,1),
    24:(1,1,1), 25:(1,1,3), 26:(1,1,1), 27:(1,1,1), 29:(1,1,1),
    30:(1,1,1), 31:(1,1,0), 32:(3,3,0), 34:(1,1,0),
    37:(1,1,0), 38:(3,1,0), 39:(1,1,0), 40:(1,1,0), 42:(1,1,0),
    43:(3,0,0), 44:(1,0,1), 46:(1,0,1), 47:(1,0,1), 48:(1,0,1), 49:(1,0,0), 50:(1,0,0),
    51:(1,0,0), 52:(1,0,0), 53:(1,0,0), 54:(1,0,0), 55:(1,0,0), 56:(1,0,0),
    60:(1,1,0), 61:(0,0,0), 62:(1,1,1), 63:(1,1,1), 64:(1,1,1), 65:(1,1,1),
}
# Reserve the same encoded instruction size for every source statement.
RECORD_BYTES = 8
BUILTINS = {1, 2, 3, 4, 7, 8, 9, 12, 13, 14, 15, 16, 17, 18, 21, 22, 24, 32, 38, 40, 44, 48, 49, 52, 56, 67}
OPERAND_WORDS = {**{key: round(value * SCALE) for key, value in SHOT_OPERANDS.items()}, **SHELL_OPERANDS, **COMBAT_OPERANDS}
# W_FireAxe's trace length and impact offset operate on Q3 world coordinates.
OPERAND_WORDS.update({(3436, 1): 64 * 8, (3445, 1): 4 * 8})
# Stock IT_AXE (4096) does not fit Q6. The bounded weapon slice only
# compares or copies this enum, and 511 cannot alias a supported weapon.
# The Z component of W_FireAxe's (0, 0, 16) trace origin is also Q3.
GLOBAL_WORDS = {253: 511 * SCALE, 2631: 16 * 8}
ENTITY_FIELDS = (
    "classname", "target", "targetname", "noise", "noise1", "noise2",
    "owner", "enemy", "state", "frame", "pos1", "pos2", "finaldest",
    "ltime", "nextthink", "think", "think1", "touch", "use", "blocked",
    "origin", "velocity", "speed", "wait", "dmg", "spawnflags", "health",
    "takedamage", "message", "killtarget", "delay", "max_health",
)


def _wait_for_state(vm, entity, state):
    for _ in range(1500):
        if vm.get(entity, "state") == state:
            return
        vm.step(0.01)
    raise ValueError(f"stock QuakeC trace did not reach state {state}")


def _trace(vm):
    vm.event(3, "touch", 1)
    events = []
    for state, name in ((2, "opening"), (0, "open"), (3, "closing"), (1, "closed")):
        _wait_for_state(vm, 2, state)
        events.append(dict(event=name, time=round(vm.t, 4), z=vm.get(2, "origin")[2]))
    normal_statements = vm.statement_count

    # Cover a second press while opening, a press at the open stop, and
    # reversing a close on contact, including the stock damage callback.
    vm.event(3, "touch", 1)
    _wait_for_state(vm, 2, 2)
    _wait_for_state(vm, 3, 1)
    vm.event(3, "touch", 1)
    _wait_for_state(vm, 2, 0)
    _wait_for_state(vm, 3, 1)
    vm.event(3, "touch", 1)
    _wait_for_state(vm, 3, 1)
    # The player can stand on the open door. A reversal immediately
    # after closing starts also takes SUB_CalcMove's short-distance path.
    for index, delay in enumerate((0.07, 0.5)):
        if index:
            vm.event(3, "touch", 1)
        _wait_for_state(vm, 2, 3)
        vm.step(delay)
        vm.step(0.01, block=True)
        _wait_for_state(vm, 2, 0)
        _wait_for_state(vm, 2, 1)
    return events, normal_statements


def sparse_initial(initial):
    """Store nonzero native words after QuakeCInit clears the whole destination."""
    if len(initial) % 2 or len(initial) > 0x8000:
        raise ValueError("sparse QuakeC initializer exceeds its signed word-offset format")
    words = bytearray()
    for offset in range(0, len(initial), 2):
        if initial[offset:offset+2] != b"\0\0":
            words += pack("<H", offset) + initial[offset:offset+2]
    return bytes(words) + pack("<H", 0xffff)


def _pack_code(program, trace, operands, *, e1m1_armor=False):
    code_pcs = set(trace.pcs)
    functions = {}
    for name in trace.stats:
        function_id = program.function_ids[name]
        start, first_local, locals_count, _, _, _, parms, *widths = program.functions[function_id]
        if start < 0:
            if -start not in BUILTINS:
                raise ValueError(f"unsupported runtime builtin {name}")
            functions[function_id] = (start, 0, 0, [])
        else:
            functions[function_id] = (start, first_local, locals_count, widths[:parms])
            code_pcs.add(start)
    # Keep a trap at every unobserved branch target or fallthrough. The
    # packed bytecode can omit the interiors of unsupported paths.
    for pc in trace.pcs:
        op, a, b, _ = program.statements[pc]
        if op in (49, 50, 61):
            code_pcs.add(pc + (a if op == 61 else b))
        if op not in (0, 43, 61):
            code_pcs.add(pc + 1)
    code_pcs = sorted(code_pcs)
    offsets = {pc: i * RECORD_BYTES for i, pc in enumerate(code_pcs)}
    used = set(range(ABI_WORDS)) | set(SHOT_GLOBALS.values()) | {
        program.globals[name] for name in ("sight_entity_time", "skill")
    }
    for _, first, count, widths in functions.values():
        used.update(range(first, first + max(count, sum(widths))))
    for pc in trace.pcs:
        op, *args = program.statements[pc]
        for i, (arg, width) in enumerate(zip(args, _OPERANDS[op], strict=True)):
            if (pc, i) in operands:
                continue
            used.update(range(arg, arg + width))
    globals_map = {index: i * 2 for i, index in enumerate(sorted(used))}
    adapted = {key: 2 * (len(used) + i) for i, key in enumerate(operands)}
    code = bytearray()
    for pc in code_pcs:
        if pc not in trace.pcs:
            code += pack("<4H", 0xffff, pc, 0, 0)
            continue
        op, *args = program.statements[pc]
        encoded = [adapted[pc, i] if (pc, i) in adapted else globals_map[arg] if width else 0
                   for i, (arg, width) in enumerate(zip(args, _OPERANDS[op], strict=True))]
        if op in (49, 50, 61):
            branch = 0 if op == 61 else 1
            encoded[branch] = offsets[pc + args[branch]]
        if pc in INVENTORY_OPS or (e1m1_armor and pc in (4462, 4477)) or pc in COMBAT_BITMAP_OPS or pc in DOG_BITMAP_OPS or pc == 8064:
            if op not in (64, 65):
                raise ValueError(f"stock inventory opcode changed at {pc}")
            op += 2
        if e1m1_armor and pc == 1432:
            if (op, *args) != (1, 1595, 1583, 1596):
                raise ValueError("stock T_Damage armor calculation moved")
            op = 68  # stock binary32 armor product, rounded by the following ceil
        if e1m1_armor and pc in (8033, 8071):
            if (op, *args) != (0, 0, 0, 0):
                raise ValueError("stock ThrowGib or ThrowHead completion moved")
            op = 69
            encoded[1] = int(pc == 8071)
        code += pack("<4H", op * 2, *encoded)
    table = bytearray()
    for index in range(max(functions) + 1):
        if index not in functions:
            table += pack("<HHHBB8x", 0x8000, 0, 0, 0, 0)
            continue
        start, first, count, widths = functions[index]
        table += pack("<HHHBB8B", start & 0xffff if start < 0 else offsets[start],
                      globals_map[first] if count or widths else 0, count * 2, len(widths), 0,
                      *(w * 2 for w in widths), *([0] * (8 - len(widths))))
    return bytes(code), bytes(table), globals_map, offsets



ENTRANCE_FIELDS = ENTITY_FIELDS + ("attack_finished", "solid", "movetype", "model")


def _spawn_entrance(spawn, entities):
    """Link the stock pair without advancing the already initialized world."""
    original_time = spawn.t
    original_drop = spawn.drop_slot
    original_edicts = {key: value.copy() for key, value in spawn.e.items()}
    first = max(spawn.e) + 1
    slots = (first, first + 1)
    trigger = first + 2
    authored = {
        entity["model"]: (number, entity)
        for number, entity in enumerate(entities, 1)
        if entity.get("model") in ("*1", "*2")
    }
    if set(authored) != {"*1", "*2"}:
        raise ValueError("stock E1M1 entrance models changed")
    leaves = []
    # Spawn() is only used by LinkDoors to allocate its trigger here. Keep
    # the established grunt drop edict and all roster IDs unchanged.
    spawn.drop_slot = trigger
    try:
        for slot, model in zip(slots, ("*1", "*2"), strict=True):
            number, entity = authored[model]
            if entity["classname"] != "func_door" or entity.get("targetname"):
                raise ValueError("stock entrance must be an unkeyed touch door")
            spawn.add(slot, entity)
            spawn.event(slot, "func_door")
            leaves.append(dict(renderEntity=number, inlineModel=int(model[1:]), slot=slot))
        for slot in slots:
            # A server pusher clears nextthink immediately before executing
            # LinkDoors. Service just that callback, not world/NPC clocks.
            spawn.set(slot, "nextthink", 0)
            spawn.event(slot, "LinkDoors")
    finally:
        spawn.drop_slot = original_drop
    if spawn.t != original_time or any(spawn.e[key] != value for key, value in original_edicts.items()):
        raise ValueError("offline entrance linking changed an existing edict or clock")
    if trigger not in spawn.e or spawn.get(trigger, "owner") != first:
        raise ValueError("stock entrance did not create its linked trigger")
    if tuple(spawn.get(slot, "enemy") for slot in slots) != (slots[1], slots[0]):
        raise ValueError("stock entrance team linkage changed")
    for leaf in leaves:
        slot = leaf["slot"]
        travel = spawn.get(slot, "pos2")
        if any(abs(travel[axis]) > 0.001 for axis in (0, 2)):
            raise ValueError("stock entrance must translate only along Y")
        leaf.update(origin=spawn.get(slot, "pos1"), travel=(0., travel[1], 0.),
                    travelQ6=round(abs(travel[1]) * SCALE),
                    direction=-1 if travel[1] < 0 else 1,
                    speed=spawn.get(slot, "speed"), wait=spawn.get(slot, "wait"),
                    mins=spawn.get(slot, "mins"), maxs=spawn.get(slot, "maxs"))
    spawn.pusher_slots = (*spawn.pusher_slots, *slots)
    trigger_data = dict(slot=trigger, owner=first,
                        mins=spawn.get(trigger, "mins"), maxs=spawn.get(trigger, "maxs"),
                        absmin=spawn.get(trigger, "absmin"), absmax=spawn.get(trigger, "absmax"),
                        touch=spawn.get(trigger, "touch"), cooldownSeconds=1)
    return leaves, trigger_data


def _cover_entrance(vm, spawn, leaves, trigger):
    """Exercise stock callbacks independently of the later lift fixture."""
    vm.e = {key: value.copy() for key, value in spawn.e.items()}
    vm.g = spawn.g.copy()
    vm.t = spawn.t
    vm.pusher_slots = spawn.pusher_slots
    first, second = (leaf["slot"] for leaf in leaves)
    source = trigger["slot"]
    events = []

    def record(label):
        events.append(dict(event=label, time=round(vm.t, 4),
                           states=[vm.get(slot, "state") for slot in (first, second)],
                           origins=[vm.get(slot, "origin") for slot in (first, second)]))

    def touch():
        vm.event(source, "touch", 1)

    # These branches are reachable from an actual trigger overlap, even if
    # the normal demo route contains only a healthy player.
    vm.event(first, "touch", 1)
    health = vm.get(1, "health")
    vm.set(1, "health", 0)
    touch()
    vm.set(1, "health", health)
    drop = vm.drop_slot
    original_drop = vm.e[drop].copy()
    vm.set(drop, "health", 100)
    vm.set(drop, "classname", "monster_army")
    vm.event(source, "touch", drop)
    vm.e[drop] = original_drop
    # Keep rejection-path coverage separate from the canonical lifecycle:
    # the original program is the authority on whether a given actor touches.
    vm.e = {key: value.copy() for key, value in spawn.e.items()}
    vm.g = spawn.g.copy()
    vm.t = spawn.t
    record("closed")
    touch()
    record("opening")
    touch()  # trigger's original one-second cooldown
    _wait_for_state(vm, first, 0)
    _wait_for_state(vm, second, 0)
    record("open")
    for _ in range(110):
        vm.step(0.01)
    touch()  # hold a linked pair at the open stop
    record("held-open")
    _wait_for_state(vm, first, 3)
    record("closing")
    vm.step(0.07)
    vm.step(0.01, blocked_actor=first)
    record("blocked-reversed")
    _wait_for_state(vm, first, 0)
    _wait_for_state(vm, first, 1)
    _wait_for_state(vm, second, 1)
    record("closed-again")
    # Reopen while closing: door_use and the team loop need both branches.
    for _ in range(110):
        vm.step(0.01)
    touch()
    _wait_for_state(vm, first, 3)
    vm.step(0.05)
    touch()
    record("retouched-reversed")
    _wait_for_state(vm, first, 0)
    _wait_for_state(vm, first, 1)
    for _ in range(110):
        vm.step(0.01)
    touch()
    vm.step(0.07)
    vm.step(0.01, blocked_actor=first)
    record("opening-blocked-reversed")
    _wait_for_state(vm, first, 1)
    _wait_for_state(vm, second, 1)
    for _ in range(110):
        vm.step(0.01)
    touch()
    _wait_for_state(vm, first, 3)
    vm.step(0.05)
    vm.step(0.01, blocked_actor=second)
    record("second-blocked-reversed")
    _wait_for_state(vm, first, 1)
    _wait_for_state(vm, second, 0)
    _wait_for_state(vm, second, 1)
    return events


def build_gameplay(archive, bsp, entities, models, row, brushes, *, cover_soldier_cooldown=True,
                   include_exit=True, include_knights=False, carry_weapons=False):
    if sha256(bsp).hexdigest() != BSP_HASH:
        raise ValueError("E1M1 gameplay requires the original shareware BSP")
    program = Program(archive.read("progs.dat"))
    actors = {entity.get("model"): (i, entity) for i, entity in enumerate(entities, 1)
              if entity.get("model") in ("*3", "*4")}
    door_id, door = actors["*3"]
    button_id, button = actors["*4"]
    if (door["classname"], button["classname"], door["targetname"], button["target"]) != (
            "func_door", "func_button", "t1", "t1"):
        raise ValueError("stock E1M1 gameplay entities changed")
    drop = floor_drop(bsp, models[0][10])
    spawn = GruntReference(program, models, archive, drop)
    spawn.add(0, {"classname":"worldspawn"})
    spawn.add(1, {"classname":"player", "health":100})
    for slot, entity in ((2, door), (3, button)):
        spawn.add(slot, entity)
        spawn.event(slot, entity["classname"])
    spawn.step(0.1)  # Finish the stock LinkDoors think before cartridge boot.
    shells = spawn.spawn_shells(entities)
    spawn.drop = floor_drop(bsp, models[0][10], supporting_roots=(models[3][10], models[4][10]))
    spawn.path_corners = quakec_patrol.spawn_corners(spawn, entities) if include_exit else ()
    grunts = spawn.spawn_grunts(entities, include_dogs=include_exit)
    for slot in range(quakec_patrol.ORACLE_FIRST, quakec_patrol.ORACLE_FIRST + len(spawn.path_corners)):
        del spawn.e[slot]
    grunt = grunts[0]
    dogs = [actor for actor in grunts if actor["model"] == "progs/dog.mdl"]
    entrance, entrance_trigger = _spawn_entrance(spawn, entities)
    trace = GruntReference(program, models, archive, drop)
    trace.g = spawn.g.copy()
    trace.e = {key: value.copy() for key, value in spawn.e.items()}
    trace.s = spawn.s.copy()
    trace.drop_slot = spawn.drop_slot
    trace.pusher_slots = spawn.pusher_slots
    events, normal_statements = _trace(trace)
    entrance_events = _cover_entrance(trace, spawn, entrance, entrance_trigger)
    shotgun = trace.cover_shotgun(spawn)
    trace.cover_axe()
    if include_exit:
        from snes_tooling.quake.quakec_powerups import cover_quad_damage
        cover_quad_damage(trace, program, models, archive)
    if include_exit or carry_weapons:
        from snes_tooling.quake import quakec_super_shotgun
        super_fire = quakec_super_shotgun.cover_fire(trace, spawn, program, models, archive)
    trace.cover_shells(spawn)
    spawn.set(1, "velocity", (120, 120, 0))
    trace.cover_shells(spawn)
    spawn.set(1, "velocity", (0, 0, 0))
    combat_globals, combat_rng = trace.g.copy(), trace.rng.getstate()
    trace.cover_grunt(spawn)
    trace.g = combat_globals
    trace.rng.setstate(combat_rng)
    trace.g[program.globals["skill"]] = asi(3)
    trace.cover_grunt(spawn)
    if cover_soldier_cooldown:
        # A new hit during the pain cooldown returns without starting an animation.
        soldier = GRUNT_SLOT + 1
        trace.set(soldier, "pain_finished", trace.t + 1)
        before = trace.statement_count
        trace.event(soldier, "army_pain")
        if trace.statement_count - before != 4:
            raise ValueError("stock soldier pain cooldown did not return immediately")
    overkill = []
    if include_exit:
        from snes_tooling.quake import quakec_gibs
        overkill = quakec_gibs.cover_overkill(trace, program, models, archive)
        # The swept native nail feeds the same stock touch-blood VM callback.
        nail_hit = GruntReference(program, models, archive, None)
        nail_hit.add(1, {"classname": "spike", "origin": (0, 0, 0), "velocity": (1000, 0, 0)})
        nail_hit.g[4] = asi(9)
        nail_hit.event(1, "spawn_touchblood")
        trace.pcs.update(nail_hit.pcs)
        trace.stats.update(nail_hit.stats)
    if dogs:
        from snes_tooling.quake.quakec_dog import cover_dog
        cover_dog(trace, spawn, dogs[0]["slot"])
    if include_knights:
        cover_knight(trace, spawn)
    if spawn.path_corners:
        patrol = next(grunt for grunt in grunts if grunt["target"])
        quakec_patrol.cover_patrol(trace, spawn, patrol["slot"])
    operands = OPERAND_WORDS | DOG_OPERANDS if dogs else OPERAND_WORDS
    if include_exit:
        operands = operands | quakec_gibs.OPERANDS | {(3556, 1): 0}
    if include_exit or carry_weapons:
        operands = operands | {(3722, 0): 0, (4462, 1): 256, (4477, 1): 512}
    if include_knights:
        operands = operands | KNIGHT_OPERANDS
    box_slot = None
    if include_exit:
        from snes_tooling.quake.quakec_explobox import spawn_explobox, stock_explobox
        box = stock_explobox(archive, bsp, entities, models, program, trace)
        box_slot = max(spawn.e) + 1
        spawn_explobox(spawn, entities, box_slot)
        operands = operands | {(11337, 1): 32 * 8}
    code, functions, global_map, offsets = _pack_code(program, trace, operands, e1m1_armor=include_exit or carry_weapons)

    spawn.string_ids = {"": 0}
    global_words = GLOBAL_WORDS | DOG_GLOBAL_WORDS if dogs else GLOBAL_WORDS
    if include_exit:
        global_words = global_words | quakec_gibs.GLOBAL_WORDS
    if include_knights:
        global_words = global_words | KNIGHT_GLOBAL_WORDS
    if box_slot is not None:
        # CanDamage retries the stock obstruction trace at four Q3 offsets.
        global_words = dict(global_words)
        for pc in (1339, 1350, 1361, 1372):
            base = program.statements[pc][2]
            global_words.update({base + axis: round(asf(program.initial[base + axis]) * 8) & 0xffff
                                 for axis in range(3)})
    globals_data = b"".join(
        pack("<H", global_words[i] if i in global_words else
             _word(program.types.get(i, 0), program.initial[i], spawn))
        for i in global_map
    )
    globals_data += b"".join(pack("<H", word) for word in operands.values())
    edicts = bytearray((max(spawn.e) + 1) * ENTITY_STRIDE)
    grunt_slots = range(GRUNT_SLOT, GRUNT_SLOT + len(grunts))
    entrance_slots = {leaf['slot'] for leaf in entrance} | {entrance_trigger['slot']}
    grunt_fields = set()
    hull_origin = tuple(round((models[0][i] + models[0][i + 3]) * 0.5)
                        - (22 if i == 2 else 0) for i in range(3))
    for slot, data in spawn.e.items():
        if 4 <= slot < GRUNT_SLOT:
            fields = SHELL_FIELDS
        elif slot == 1:
            fields = ENTITY_FIELDS + SHOT_FIELDS + ACTOR_FIELDS + ("items",)
        elif slot in grunt_slots or slot == box_slot:
            fields = ENTITY_FIELDS + ACTOR_FIELDS
        elif slot in entrance_slots:
            fields = ENTRANCE_FIELDS
        else:
            fields = ENTITY_FIELDS
        for name in dict.fromkeys(fields):
            kind, offset = program.fields[name]
            for i in range(3 if kind == 3 else 1):
                raw = data[offset + i]
                if name in ("items", "flags"):
                    value = int(asf(raw))
                elif name == "pausetime" and asf(raw) >= 1e6:
                    value = 0x7fff
                elif name in ("movetarget", "goalentity") and raw >= quakec_patrol.ORACLE_FIRST:
                    value = quakec_patrol.corner_token(raw)
                elif (slot == 1 or slot in grunt_slots or slot == box_slot) and name in Q3_FIELDS:
                    coordinate = asf(raw)
                    if slot != 1 and name in ("origin", "absmin", "absmax"):
                        coordinate -= hull_origin[i]
                    value = round(coordinate * 8) & 0xffff
                else:
                    value = _word(2 if kind == 3 else kind, raw, spawn)
                relative = (offset + i) * 2
                if slot in grunt_slots and value:
                    grunt_fields.add(relative)
                at = slot * ENTITY_STRIDE + relative
                edicts[at:at + 2] = pack("<H", value)
    # Non-actor edicts use the original dense prefix. Only fields that
    # initialize at least one soldier need room in the cartridge roster.
    field_offsets = sorted(grunt_fields)
    # WinQuake's single-player spawn exclusions are host flags. Keep them
    # separate from the QuakeC-visible flags and the fixed-point fields.
    grunt_data = b"".join(pack("<H", soldier["authoredSpawnflags"] & 0x700) + b"".join(
        edicts[slot * ENTITY_STRIDE + field:slot * ENTITY_STRIDE + field + 2]
        for field in field_offsets
    ) for slot, soldier in zip(grunt_slots, grunts, strict=True))
    end = {door_id: spawn.get(2, "pos2"), button_id: spawn.get(3, "pos2")}
    moving = {s.entity_number: s for s in brushes if s.entity_number in end}
    entrances_by_id = {leaf["renderEntity"]: leaf for leaf in entrance}
    closed_entrance = tuple(s for s in brushes if s.entity_number in entrances_by_id)
    if len(closed_entrance) != 2:
        raise ValueError("entrance visuals require both authored brushes")
    rows = []
    for door_step in range(DOOR_STEPS + 1):
        for button_step in range(BUTTON_STEPS + 1):
            progress = {door_id: door_step / DOOR_STEPS, button_id: button_step / BUTTON_STEPS}
            poses = tuple(replace(moving[entity], origin=tuple(
                round((a + b * progress[entity]) * 8) / 8
                for a, b in zip(moving[entity].origin, end[entity], strict=True)))
                for entity in sorted(moving))
            index = len(rows)
            rows.append(replace(row, index=index, brushes=(*closed_entrance, *poses)))


    first_entrance_row = len(rows)
    pose_rows = [0]
    stationary = tuple(moving[entity] for entity in sorted(moving))
    for pose in range(1, ENTRANCE_STEPS + 1):
        poses = tuple(replace(state, origin=tuple(
            round((a + b * pose / ENTRANCE_STEPS) * 8) / 8
            for a, b in zip(state.origin, entrances_by_id[state.entity_number]["travel"], strict=True)))
            for state in closed_entrance)
        pose_rows.append(len(rows))
        rows.append(replace(row, index=len(rows), brushes=(*poses, *stationary)))
    for leaf in entrance:
        leaf["poseRows"] = pose_rows
    exit_machinery, exit_include, exit_outputs = None, b"", {}
    if include_exit:
        exit_machinery = build_exit_machinery(program, archive, models, entities, drop)
        rows = add_exit_pose_rows(rows, brushes, exit_machinery)
        exit_include, exit_outputs = exit_machinery_outputs(exit_machinery)
    entrance_init_offset = GRUNT_SLOT * ENTITY_STRIDE + len(grunt_data)
    entrance_init_target = entrance[0]["slot"] * ENTITY_STRIDE
    entrance_init = bytes(edicts[entrance_init_target:])


    constants = dict(BSP_QUAKEC_GAMEPLAY=1, QC_GLOBAL_BYTES=len(globals_data),
                     QC_ENTITY_STRIDE=ENTITY_STRIDE, QC_EDICT_BYTES=len(edicts),
                     QC_DOOR_STEPS=DOOR_STEPS, QC_BUTTON_STEPS=BUTTON_STEPS,
                     QC_DOOR_TRAVEL=round(-end[door_id][2] * SCALE),
                     QC_BUTTON_TRAVEL=round(-end[button_id][0] * SCALE),
                     QC_FUNCTION_COUNT=len(functions) // 16,
                     QC_CODE_BYTES=len(code))
    if box_slot is not None:
        radius_order = [1] + [actor["slot"] for actor in sorted(grunts, key=lambda a: a["entityNumber"])]
        constants.update({f"QC_RADIUS_EDICT_{i}": slot * ENTITY_STRIDE for i, slot in enumerate(radius_order)})
        constants.update(QC_RADIUS_COUNT=len(radius_order), QC_EXPLOBOX=box_slot * ENTITY_STRIDE,
                         QC_EXPLOBOX_SOUND=spawn.string_ids[box["sound"]],
                         QC_FIELD_CHAIN=program.fields["chain"][1] * 2)
    if carry_weapons:
        constants.update(QC_SSG_SOUND=spawn.string_ids[super_fire["double"]["sound"]],
                         QC_NAIL_DAMAGE_FUNCTION=program.function_ids["T_Damage"])
    constants.update(QC_ENTRANCE_COUNT=2, QC_ENTRANCE_STEPS=ENTRANCE_STEPS,
        QC_ENTRANCE_FIRST_ROW=first_entrance_row,
        QC_ENTRANCE_TRIGGER=entrance_trigger["slot"] * ENTITY_STRIDE,
        QC_ENTRANCE_INIT_OFFSET=entrance_init_offset,
        QC_ENTRANCE_INIT_TARGET=entrance_init_target,
        QC_ENTRANCE_INIT_BYTES=len(entrance_init),
        QC_ENTRANCE_TRIGGER_COOLDOWN=SCALE)
    world_origin = tuple(round((models[0][i] + models[0][i+3]) * .5) for i in range(3))
    eye_min, eye_max = [], []
    for axis, direction in enumerate("XYZ"):
        # SV_TouchLinks compares linked abs-bounds inclusively. Both the
        # player's and trigger's boxes include LinkEdict's one-unit margin.
        viewheight = 22 if axis == 2 else 0
        lower = entrance_trigger["absmin"][axis] - (spawn.get(1, "maxs")[axis] + 1) + viewheight
        upper = entrance_trigger["absmax"][axis] - (spawn.get(1, "mins")[axis] - 1) + viewheight
        eye_min.append(round((lower-world_origin[axis])*16))
        eye_max.append(round((upper-world_origin[axis])*16))
        constants[f"QC_ENTRANCE_TRIGGER_{direction}_MIN"] = eye_min[-1]
        constants[f"QC_ENTRANCE_TRIGGER_{direction}_MAX"] = eye_max[-1]
        constants[f"QC_ENTRANCE_TRIGGER_WORLD_{direction}_MIN"] = round(entrance_trigger["mins"][axis])
        constants[f"QC_ENTRANCE_TRIGGER_WORLD_{direction}_MAX"] = round(entrance_trigger["maxs"][axis])
    entrance_trigger.update(triggerEyeMinQ4=eye_min, triggerEyeMaxQ4=eye_max,
                           overlap="inclusive linked abs-bounds; player box includes one-unit margin")
    for i, leaf in enumerate(entrance):
        constants[f"QC_ENTRANCE_{i}"] = leaf["slot"] * ENTITY_STRIDE
        constants[f"QC_ENTRANCE_{i}_TRAVEL"] = leaf["travelQ6"]
        constants[f"QC_ENTRANCE_{i}_DIRECTION"] = leaf["direction"]
        constants[f"QC_ENTRANCE_{i}_MOVE"] = 2
        constants[f"QC_ENTRANCE_RENDER_ENTITY_{i}"] = leaf["renderEntity"]
        constants[f"QC_ENTRANCE_INLINE_MODEL_{i}"] = leaf["inlineModel"]
        for axis, direction in enumerate("XYZ"):
            lower = leaf["mins"][axis] - (16 if axis < 2 else 32)
            upper = leaf["maxs"][axis] + (16 if axis < 2 else 24)
            constants[f"QC_ENTRANCE_{i}_MIN_{direction}"] = round(lower)
            constants[f"QC_ENTRANCE_{i}_MAX_{direction}"] = round(upper)
    for i, name in enumerate(("SELF", "OTHER", "WORLD", "TIME"), 28):
        constants["QC_GLOBAL_" + name] = global_map[i]
    constants.update({f"QC_GLOBAL_{name}": global_map[index] for name, index in SHOT_GLOBALS.items()})
    constants.update(QC_WEAPON_FRAME=program.function_ids["W_WeaponFrame"],
                     QC_SHOTGUN_FUNCTION=program.function_ids["W_FireShotgun"],
                     QC_SHOTGUN_SOUND=spawn.string_ids["weapons/guncock.wav"],
                     QC_AXE_FUNCTION=program.function_ids["W_FireAxe"],
                     QC_AXE_HIT_SOUND=spawn.string_ids["player/axhit2.wav"])
    lift_samples = {role: dict(name=spawn.get(slot, field)) for role, slot, field in (
        ("Button", 3, "noise"), ("Move", 2, "noise2"), ("Stop", 2, "noise1"),
    )}
    for role, sample in lift_samples.items():
        constants[f"QC_LIFT_{role.upper()}_SOUND"] = spawn.string_ids[sample["name"]]
    constants.update(QC_GRUNT=GRUNT_SLOT * ENTITY_STRIDE, QC_GRUNT_DROP=spawn.drop_slot * ENTITY_STRIDE,
                     QC_GRUNT_COUNT=len(grunts), QC_GRUNT_INIT_WORDS=len(field_offsets),
                     QC_GRUNT_START_TIME=START_TIME * SCALE, QC_GRUNT_START_YAW=128,
                     QC_GLOBAL_SKILL=global_map[program.globals["skill"]],
                     QC_GLOBAL_SIGHT_ENTITY_TIME=global_map[program.globals["sight_entity_time"]])
    if dogs:
        from snes_tooling.quake.quake_grunt_assets import DOG_FRAMES, E1M1_SOLDIER_FRAMES
        constants["QC_BACKPACK_ROW"] = len(E1M1_SOLDIER_FRAMES) + len(DOG_FRAMES)
        constants["QC_BACKPACK_COUNT"] = dogs[0]["slot"] - GRUNT_SLOT
        constants["QC_PATROL_TOKEN"] = quakec_patrol.TOKEN_BASE
        constants["QC_PATROL_TABLE"] = len(field_offsets) * 2
        constants.update(QC_DOG_FIRST=dogs[0]["slot"] * ENTITY_STRIDE,
                         QC_DOG_FRAME_MAP_OFFSET=114)
        for i, sound_name in enumerate(DOG_SOUNDS):
            constants[f"QC_DOG_SOUND_{i}"] = spawn.string_ids.setdefault(sound_name, len(spawn.string_ids))
    if include_knights:
        constants["QC_KNIGHT_ROSTER"] = 1
        for index, name in enumerate(KNIGHT_SOUNDS):
            constants[f"QC_KNIGHT_SOUND_{index}"] = spawn.string_ids.setdefault(name, len(spawn.string_ids))
    for i, sound_name in enumerate(GRUNT_SOUNDS):
        constants[f"QC_GRUNT_SOUND_{i}"] = spawn.string_ids[sound_name]
    constants.update(QC_SHELL_COUNT=len(shells), QC_SHELL_SOUND=spawn.string_ids[SHELL_SOUND])
    armor = []
    powerups = []
    if include_exit:
        constants["QC_INPUT_REPLAY_CELL_BYTES"] = 4
        from snes_tooling.quake.quakec_armor import armor_constants, stock_armor
        from snes_tooling.quake.quake_grunt_assets import E1M1_SOLDIER_FRAMES, DOG_FRAMES
        from snes_tooling.quake.quakec_nailgun import nailgun_constants, stock_nailgun
        armor = stock_armor(archive, bsp, entities, models, program)
        nailgun = stock_nailgun(archive, bsp, entities, models, program)
        constants.update(armor_constants(armor, len(E1M1_SOLDIER_FRAMES) + len(DOG_FRAMES), program))
    if dogs:
        constants["QC_BACKPACK_ROW"] += len(armor)
    if include_exit:
        from snes_tooling.quake.quakec_powerups import powerup_constants, stock_powerups
        powerups = stock_powerups(archive, bsp, entities, models, program, constants["QC_BACKPACK_ROW"] + 1)
        constants.update(powerup_constants(powerups, program))
        constants.update(nailgun_constants(nailgun, constants["QC_BACKPACK_ROW"] + 1 + len(powerups), program))
        constants["QC_PICKUP_NOTICES"] = 4
        constants["QC_EXPLOSION_MODEL"] = spawn.string_ids[box["explosionModel"]]
        constants["QC_QUAD_SOUND"] = spawn.string_ids["items/damage3.wav"]
        from snes_tooling.quake.quake_liquid_hull import liquid_hull
        liquid, liquid_data = liquid_hull(bsp, (*hull_origin[:2], hull_origin[2] + 22))
        constants.update(QC_LIQUID_ROOT=liquid["root"] * 16, QC_LIQUID_CEILING=liquid["ceilingQ4"])
        ssg = quakec_super_shotgun.stock_pickup(archive, bsp, entities, models, program, constants["QC_SPIKE_ROW"] + 1)
        constants["QC_SSG_ROW"] = ssg["spriteRow"]
        constants["QC_SSG_AMOUNT"] = ssg["amount"]
        constants["QC_SSG_SOUND"] = spawn.string_ids[super_fire["double"]["sound"]]
        for axis, pos, lo, hi in zip("XYZ", ssg["renderOriginQ2"], ssg["triggerEyeMinQ4"], ssg["triggerEyeMaxQ4"], strict=True):
            constants["QC_SSG_" + axis] = pos
            constants[f"QC_SSG_{axis}_MIN"] = lo
            constants[f"QC_SSG_{axis}_MAX"] = hi
        constants["QC_STOCK_AIM"] = 1
        constants["QC_NAIL_BLOOD"] = program.function_ids["spawn_touchblood"]
        constants["QC_EDICT_FIELD_BYTES"] = 2 * max(offset + (3 if kind == 3 else 1)
                                                    for kind, offset in program.fields.values())
        constants["QC_GIB_FIRST_ROW"] = constants["QC_SSG_ROW"] + 1
        constants["QC_EXPLOSION_ROW"] = constants["QC_GIB_FIRST_ROW"] + len(quakec_gibs.MODELS)
        from snes_tooling.quake import quake_explosion_particles as explosion
        first = constants["QC_EXPLOSION_ROW"] + len(box["frames"])
        box["particleModel"] = explosion.MODEL
        box["particleRows"] = []
        for frame, tiles in enumerate(explosion.tile_frames()):
            end = first + len(tiles)
            if end > 255:
                raise ValueError("explosion particle rows exceed the native pose byte")
            constants[f"QC_EXPLOSION_FIRST_{frame}"] = first
            constants[f"QC_EXPLOSION_END_{frame}"] = end
            box["particleRows"].append([first, end])
            first = end
        constants["QC_EXPLOSION_PHASES"] = len(box["particleRows"])
        # Private counters and the original emitter live past the stock edict fields.
        constants["QC_EXPLOSION_LIFE"] = 402
        constants["QC_EXPLOSION_EMITTER"] = 404
        constants["QC_TELEPORT_FOG_ROW"] = first
        from snes_tooling.quake import quake_combat_particles as impacts, quake_teleport_particles as teleport
        constants["QC_IMPACT_ROW"] = first + teleport.FRAMES * teleport.STRIPS
        if constants["QC_IMPACT_ROW"] + impacts.FRAMES * len(impacts.STYLES) > 256:
            raise ValueError("combat particle rows exceed the native pose byte")
        constants["QC_TELEFRAG_KILLED"] = program.function_ids["Killed"]
        constants["QC_GLOBAL_KILLED_MONSTERS"] = global_map[program.globals["killed_monsters"]]
        constants["QC_BACKPACK_MODEL"] = spawn.string_ids["progs/backpack.mdl"]
        constants["QC_GIB_SOUND"] = spawn.string_ids[quakec_gibs.DEATH_SOUND]
        constants["QC_FIELD_AVELOCITY"] = 2 * program.fields["avelocity"][1]
        for index, model in enumerate(quakec_gibs.MODELS):
            constants[f"QC_GIB_MODEL_{index}"] = spawn.string_ids[model]
    for i, shell in enumerate(shells):
        for axis, lo, hi in zip("XYZ", shell["triggerEyeMinQ4"], shell["triggerEyeMaxQ4"], strict=True):
            constants[f"QC_SHELL_{i}_{axis}_MIN"] = lo
            constants[f"QC_SHELL_{i}_{axis}_MAX"] = hi
    for name in dict.fromkeys(ENTITY_FIELDS + SHOT_FIELDS + SHELL_FIELDS + ACTOR_FIELDS + ("items",)):
        constants["QC_FIELD_" + name.upper()] = program.fields[name][1] * 2
    for name in ("ammo_nails", "ammo_rockets", "ammo_cells", "armorvalue", "armortype"):
        constants["QC_FIELD_" + name.upper()] = program.fields[name][1] * 2
    from snes_tooling.quake.quake_bsp_assets import lump_data, lump_ranges
    lumps = lump_ranges(bsp)
    planes = tuple(iter_unpack("<4fi", lump_data(bsp, lumps, 1)))
    nodes = tuple(iter_unpack("<ihh", lump_data(bsp, lumps, 9)))
    for model_id, name, axis, slot in ((3, "DOOR", 2, 2), (4, "BUTTON", 0, 3)):
        constants[f"QC_{name}"] = slot * ENTITY_STRIDE
        bounds = {}
        node = models[model_id][10]
        for _ in range(6):
            plane_id, front, back = nodes[node]
            *normal, distance, plane_type = planes[plane_id]
            if (plane_type not in range(3) or normal[plane_type] != 1
                    or sum(abs(v) for v in normal) != 1 or (front == -1) == (back == -1)):
                raise ValueError("selected mover hull is not an axial box")
            minimum = back == -1
            bounds[plane_type, minimum] = round(distance)
            node = front if minimum else back
        if node != -2 or len(bounds) != 6:
            raise ValueError("selected mover hull is not an axial solid box")
        for i, direction in enumerate("XYZ"):
            constants[f"QC_{name}_MIN_{direction}"] = bounds[i, True]
            constants[f"QC_{name}_MAX_{direction}"] = bounds[i, False]
        constants[f"QC_{name}_MOVE"] = axis * 2
    include = "".join(f"{key} = {value}\n" for key, value in constants.items()).encode() + exit_include
    with archive.path.open("rb") as source:
        pak_digest = file_digest(source, "sha256").hexdigest()
    from snes_tooling.quake.quake_snes_realtime_sound import resample_wave_pcm
    from snes_tooling.quake.quake_snes_soundtrack import encode_brr, parse_quake_wave
    def encode_sound(name, metadata, rate=8000, *, looping=False, impact_capacity=None):
        from snes_tooling.quake.quake_snes_realtime_sound import _block_aligned_sample_count
        source = archive.read("sound/" + name)
        wave = parse_quake_wave(source)
        pcm = resample_wave_pcm(wave, output_rate_hz=rate, bandlimit=True)
        if looping:
            if wave.loop_start is None:
                raise ValueError(f"stock motor {name} lacks its WAV loop point")
            start = _block_aligned_sample_count(wave.loop_start, wave.sample_rate_hz, rate)
            intro = bytearray(encode_brr(pcm[:start]))
            loop = bytearray(encode_brr(pcm[start:], initial_silence=False, first_filter_zero=True))
            intro[-9] &= ~1
            loop[-9] |= 3
            brr = bytes(intro + loop)
            metadata["loopByteOffset"] = len(intro)
        else:
            if impact_capacity is not None:
                max_samples = (impact_capacity // 9 - 1) * 16  # One initial silent BRR block.
                if len(pcm) > max_samples:
                    fade_samples = rate // 100
                    pcm = pcm[:max_samples - fade_samples] + tuple(
                        round(sample * (fade_samples - i - 1) / fade_samples)
                        for i, sample in enumerate(pcm[max_samples - fade_samples:max_samples])
                    )
                    metadata["soundTailFadeSamples"] = fade_samples
            brr = encode_brr(pcm + (0,) * (-len(pcm) % 16))
            if impact_capacity is not None and len(brr) != impact_capacity:
                raise ValueError(f"{name} no longer fits the shared impact allocation")
        metadata.update(soundSourceSha256=sha256(source).hexdigest(), soundBrrSha256=sha256(brr).hexdigest(),
                        soundBrrBytes=len(brr), soundSampleRateHz=rate)
        return brr

    stock_shells = dict(boxes=shells, sound=SHELL_SOUND)
    shot_brr = encode_sound(shotgun["shotSound"], shotgun)
    shell_brr = encode_sound(SHELL_SOUND, stock_shells)
    stock_axe = dict(reach=64, damage=20, hitTick=12, cooldownQ6=32,
                     viewSequence=((0, 1), (6, 2), (12, 3), (18, 4), (24, 0)),
                     swingSound=dict(name="weapons/ax1.wav"), wallSound=dict(name="player/axhit2.wav"))
    axe_swing = encode_sound(stock_axe["swingSound"]["name"], stock_axe["swingSound"])
    axe_wall = encode_sound(stock_axe["wallSound"]["name"], stock_axe["wallSound"])
    talk = dict(name="misc/talk.wav")
    talk_brr = encode_sound(talk["name"], talk)
    teleport_arrival = dict(name="misc/r_tele1.wav")
    teleport_brr = encode_sound(teleport_arrival["name"], teleport_arrival)
    secret = dict(name="misc/secret.wav")
    secret_brr = encode_sound(secret["name"], secret, rate=6000)
    jump = dict(name="player/plyrjmp8.wav")
    jump_brr = encode_sound(jump["name"], jump)
    swim = [dict(name=f"misc/water{i}.wav") for i in (1, 2)]
    swim_brr = [encode_sound(sample["name"], sample) for sample in swim]
    gasps = [dict(name=f"player/gasp{i}.wav") for i in (1, 2)]
    gasp_brr = [encode_sound(sample["name"], sample, rate=4000) for sample in gasps]
    from snes_tooling.quake.quakec_health_pickups import HEALTH_CUES
    health_sounds = {size: dict(name=name) for size, name in HEALTH_CUES.items()}
    health_brr = {Path(f"QuakeBSPHealth{size}.brr"): encode_sound(sample["name"], sample, rate=4000)
                  for size, sample in health_sounds.items()}
    lift_brr = {}
    for role, sample in lift_samples.items():
        name = sample["name"]
        payload = encode_sound(name, sample, rate=6000 if role in ("Move", "Stop") else 8000, looping=role == "Move")
        if role == "Move":
            lift_brr[Path("QuakeBSPLiftLoop.i")] = f"QC_LIFT_LOOP_BYTE = {sample['loopByteOffset']}\n".encode("ascii")
        lift_brr[Path(f"QuakeBSPLift{role}.brr")] = payload
    grunt_audio = {}
    grunt_brr = {}
    for i, name in enumerate(GRUNT_SOUNDS):
        grunt_audio[name] = {}
        grunt_brr[Path(f"QuakeBSPGruntSound{i}.brr")] = encode_sound(name, grunt_audio[name], rate=4000)
    grunt["sounds"] = grunt_audio
    dog_audio = {}
    dog_samples = bytearray()
    dog_offsets = []
    for name in DOG_SOUNDS:
        dog_offsets.append(len(dog_samples))
        dog_audio[name] = cue = dict(name=name)
        dog_samples.extend(encode_sound(name, cue, rate=2000))
    dog_constants = [f"QC_DOG_AUDIO_OFFSET_{i} = {offset}" for i, offset in enumerate(dog_offsets)]
    # All modules share the resident SPC program and sample addresses after
    # a warm map change. Only E1M1 uploads this particular overlay.
    dog_constants.append(f"QC_ARMOR_AUDIO_OFFSET = {len(dog_samples)}")
    dog_samples.extend(encode_sound("items/armor1.wav", {}, rate=2000))
    from snes_tooling.quake.quakec_health_pickups import MEGA_CUE
    dog_constants.append(f"QC_MEGA_AUDIO_OFFSET = {len(dog_samples)}")
    dog_samples.extend(encode_sound(MEGA_CUE, {}, rate=2000))
    # The selectable E1M1 actors and both lifts share the map's audio upload.
    platform_audio = {}
    for i, name in enumerate(("plats/plat1.wav", "plats/plat2.wav", "doors/basesec1.wav", "doors/basesec2.wav")):
        offset = len(dog_samples)
        platform_audio[name] = sample = dict(name=name)
        dog_samples.extend(encode_sound(name, sample, rate=2000, looping=i in (0, 2)))
        loop = offset + sample.get("loopByteOffset", 0)
        dog_constants.extend((f"QC_PLATFORM_AUDIO_{i} = {offset}", f"QC_PLATFORM_LOOP_{i} = {loop}"))
    dog_constants.append(f"QC_QUAD_ATTACK_AUDIO = {len(dog_samples)}")
    quad_attack = {"name": "items/damage3.wav"}
    dog_samples.extend(encode_sound(quad_attack["name"], quad_attack, rate=2000))
    from snes_tooling.quake.quakec_gibs import DEATH_SOUND
    dog_constants.append(f"QC_GIB_AUDIO = {len(dog_samples)}")
    dog_samples.extend(encode_sound(DEATH_SOUND, {}, rate=2000))
    # On E1M1 the cold shotgun allocation holds its independent low-rate
    # fallback and six weapon/impact samples. Other maps keep the original
    # full 8 kHz shotgun at the same DSP address.
    nail_audio = {}
    nail_prefix = bytearray(encode_sound(shotgun["shotSound"], {}, rate=2000))
    # Keep the 2,961-byte impact extent across all warm maps. Retain the full
    # common tink and move its extra bytes from the quieter ricochet tails.
    nail_cues = (
        ("weapons/rocket1i.wav", None), ("weapons/pkup.wav", None),
        ("weapons/tink1.wav", 243), ("weapons/ric1.wav", 441),
        ("weapons/ric2.wav", 1053), ("weapons/ric3.wav", 1224),
    )
    for i, (name, impact_capacity) in enumerate(nail_cues):
        dog_constants.append(f"QC_NAIL_AUDIO_OFFSET_{i} = {len(nail_prefix)}")
        nail_audio[name] = cue = dict(name=name)
        nail_prefix.extend(encode_sound(name, cue, rate=4000 if impact_capacity else 2000,
                                        impact_capacity=impact_capacity))
    slot_bytes = nail_audio["weapons/rocket1i.wav"]["soundBrrBytes"]
    dog_constants.append(f"QC_WEAPON_SLOT_BYTES = {slot_bytes}")
    if dogs or carry_weapons:
        sound = super_fire["double"]
        ssg_brr = encode_sound(sound["sound"], sound, rate=2000)
        if len(ssg_brr) > slot_bytes:
            raise ValueError("Super Shotgun sample exceeds the shared weapon voice slot")
        grunt_brr[Path("QuakeBSPSuperShotgun.brr")] = ssg_brr.ljust(slot_bytes, bytes(1))
    nail_prefix.extend(bytes(max(0, len(shot_brr) - len(nail_prefix))))
    dog_constants.append(f"QC_WEAPON_AUDIO_BYTES = {len(nail_prefix)}")
    dog_constants.append(f"QC_STOCK_SHOT_BYTES = {len(shot_brr)}")
    dog_constants.append(f"QC_DOG_AUDIO_BYTES = {len(nail_prefix) + len(dog_samples)}")
    dog_constants.append(f"QC_ARRIVAL_AUDIO_BYTES = {len(teleport_brr)}")
    knight_audio = {}
    knight_samples = bytearray()
    for index, name in enumerate(KNIGHT_SOUNDS):
        dog_constants.append(f"QC_KNIGHT_AUDIO_OFFSET_{index} = {len(knight_samples)}")
        knight_audio[name] = cue = dict(name=name)
        knight_samples.extend(encode_sound(name, cue, rate=2000))
    dog_constants.append(f"QC_KNIGHT_AUDIO_BYTES = {len(knight_samples)}")
    dog_constants.append(f"QC_MAP_AUDIO_BYTES = {max(len(dog_samples), len(knight_samples), len(teleport_brr))}")
    grunt_brr[Path("QuakeBSPDogAudio.i")] = ("\n".join(dog_constants) + "\n").encode("ascii")
    if dogs:
        grunt_brr[Path("QuakeBSPDogAudio.brr")] = bytes(nail_prefix + dog_samples)
    if include_knights:
        grunt_brr[Path("QuakeBSPKnightAudio.brr")] = bytes((nail_prefix if carry_weapons else b"") + knight_samples)
    grunt_atan = b"".join(pack("<H", round(degrees(atan(i / 64)) * SCALE)) for i in range(65))
    meta = dict(pakSha256=pak_digest, schema="quakec-e1m1-v1", progsSha256=PROGRAM_HASH, bspSha256=BSP_HASH,
                buttonEntity=button_id - 1, doorEntity=door_id - 1,
                stockEntranceDoors=entrance, entranceTrigger=entrance_trigger,
                stockEntranceTrace=entrance_events,
                numericFractionBits=6, stockTrace=events,
                stockNormalStatementExecutions=normal_statements,
                stockFunctions=sorted(trace.stats), stockStatementCount=len(trace.pcs),
                stockShotgun=shotgun, stockAxe=stock_axe, stockShells=stock_shells, stockGrunt=grunt, stockGrunts=grunts, stockDogs=dogs,
                stockTalk=talk, stockOverkill=overkill,
                stockTeleportArrival=teleport_arrival,
                stockSecret=secret,
                stockJump=jump, stockSwim=swim, stockGasps=gasps, stockLiftSounds=lift_samples,
                stockHealthSounds=health_sounds,
                sourceStatementByOffset={v:k for k,v in offsets.items()},
                globalsBytes=len(globals_data), edictsBytes=len(edicts))
    if carry_weapons:
        meta["campaignWeapons"] = dict(spikeModel="progs/spike.mdl", superShotgun=super_fire)
    if armor:
        meta["stockArmor"] = armor
        meta["stockExplobox"] = box
        meta["stockNailgun"] = dict(nailgun, sounds=nail_audio)
        meta["stockSuperShotgun"] = dict(pickup=ssg, **super_fire)
    if powerups:
        meta["stockLiquids"] = liquid
        meta["stockPowerups"] = powerups
        meta["quadAttackSound"] = quad_attack
    if exit_machinery is not None:
        meta["stockExitMachinery"] = exit_machinery
        meta["stockPlatformSounds"] = platform_audio
    if dogs:
        meta["stockDogSounds"] = dog_audio
    if include_knights:
        meta["stockKnightSounds"] = knight_audio
        meta["knightStringIds"] = spawn.string_ids
    sparse_init = sparse_initial(globals_data + edicts[:GRUNT_SLOT * ENTITY_STRIDE]) if exit_machinery else b""
    return tuple(rows), include, meta, {
        **({Path("QuakeBSPQuakeCInitSparse.bin"): bytes(sparse_init)} if sparse_init else {}),
        **exit_outputs,
        **({Path("QuakeBSPLiquids.bin"): liquid_data} if powerups else {}),
        Path("QuakeBSPQuakeCCode.bin"): code,
        Path("QuakeBSPQuakeCFunctions.bin"): functions, Path("QuakeBSPQuakeCGlobals.bin"): globals_data,
        Path("QuakeBSPQuakeCEdicts.bin"): bytes(edicts[:GRUNT_SLOT * ENTITY_STRIDE]) + grunt_data + entrance_init,
        Path("QuakeBSPQuakeCGruntFields.bin"): pack(f"<{len(field_offsets)}H", *field_offsets)
            + quakec_patrol.pack_corners(spawn.path_corners, hull_origin),
        Path("QuakeBSPShotgun.brr"): shot_brr,
        Path("QuakeBSPAxeSwing.brr"): axe_swing,
        Path("QuakeBSPAxeWall.brr"): axe_wall,
        Path("QuakeBSPTalk.brr"): talk_brr,
        Path("QuakeBSPTeleportArrival.brr"): teleport_brr,
        Path("QuakeBSPSecret.brr"): secret_brr,
        Path("QuakeBSPJump.brr"): jump_brr,
        Path("QuakeBSPSwim1.brr"): swim_brr[0],
        Path("QuakeBSPSwim2.brr"): swim_brr[1],
        Path("QuakeBSPGasp1.brr"): gasp_brr[0],
        Path("QuakeBSPGasp2.brr"): gasp_brr[1],
        Path("QuakeBSPShellPickup.brr"): shell_brr,
        Path("QuakeBSPGruntAtan.bin"): grunt_atan,
        **health_brr,
        **lift_brr,
        **grunt_brr,
    }
