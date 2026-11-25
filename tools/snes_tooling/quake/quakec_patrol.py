"""Pack the immutable E1M1 path_corner links shared by soldier patrols."""
from struct import pack


# The stock spawn oracle uses full edicts. At runtime only the immutable
# destination, its origin and its successor are needed by movetogoal/touch.
ORACLE_FIRST = 96
TOKEN_BASE = 0x8000
RECORD_BYTES = 8


def spawn_corners(vm, entities):
    corners = [entity for entity in entities if entity["classname"] == "path_corner"]
    for slot, corner in enumerate(corners, ORACLE_FIRST):
        vm.add(slot, {**corner, "origin": tuple(map(float, corner["origin"].split()))})
    return corners


def corner_token(slot):
    return TOKEN_BASE + (slot - ORACLE_FIRST) * RECORD_BYTES


def pack_corners(corners, origin):
    names = {corner["targetname"]: corner_token(slot) for slot, corner in enumerate(corners, ORACLE_FIRST)}
    if len(names) != len(corners) or any(corner["target"] not in names for corner in corners):
        raise ValueError("E1M1 patrols require uniquely named, linked path corners")
    data = bytearray()
    for corner in corners:
        point = tuple(round((float(n) - base) * 8) for n, base in zip(corner["origin"].split(), origin, strict=True))
        data.extend(pack("<3hH", *point, names[corner["target"]]))
    return data


def cover_patrol(trace, spawn, slot):
    """Collect both soldier walk sounds, a complete cycle and sight acquisition."""
    trace.e = {key: value.copy() for key, value in spawn.e.items()}
    trace.g = spawn.g.copy()
    trace.combat = True
    trace.client = 0
    for value in (0.01, 0.95):
        trace.forced_random = value
        for frame in range(1, 25):
            trace.event(slot, f"army_walk{frame}")
    trace.client = 1
    trace.visible = True
    position = trace.get(slot, "origin")
    trace.set(1, "origin", (position[0] + 16, position[1], position[2]))
    trace.link(1)
    trace.event(slot, "army_walk1")
    if trace.get(slot, "enemy") != 1:
        raise ValueError("stock E1M1 patrol did not enter combat")
    # A soldier with a path target also takes the stock death-use branch.
    # Its path_corner has no use callback, but SUB_UseTargets still runs.
    trace.event(slot, "monster_death_use")
    trace.set(1, "health", 0)
    trace.event(slot, "ai_run")
    trace.combat = False
    trace.forced_random = None
