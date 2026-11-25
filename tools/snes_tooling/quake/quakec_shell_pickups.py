
"""Stock E1M1 item spawn and pickup coverage for the cartridge VM."""
from math import ceil, floor
from struct import iter_unpack, unpack_from

from snes_tooling.quake.quake_bsp_assets import lump_data, lump_ranges
from snes_tooling.quake.quakec_reference import asf, asi
from snes_tooling.quake.quakec_shotgun import ShotgunReference


SHELL_SOUND = "weapons/lock4.wav"
SHELL_FIELDS = ("classname", "touch", "solid", "model", "netname", "weapon", "aflag")
# Hash-bound stock statements manipulating the raw .items field. The other
# bitwise statements operate on Q6 floats, and .weapon stays Q6.
INVENTORY_OPS = {4419, 4420, 4421, 4422, 4447, 4554, 4560, 4566, 4572, 4578}
SHELL_OPERANDS = {
    (4419, 0): 256, (4419, 1): 512, (4420, 1): 1024, (4421, 1): 2048,
    (4447, 1): 256, (4554, 1): 64, (4560, 1): 8, (4566, 1): 2,
    (4572, 1): 4, (4578, 1): 1,
}


def floor_drop(bsp, root, *, supporting_roots=()):
    """Find the first solid boundary of an item-sized vertical hull trace."""
    lumps = lump_ranges(bsp)
    planes = tuple(iter_unpack("<4fi", lump_data(bsp, lumps, 1)))
    nodes = tuple(iter_unpack("<ihh", lump_data(bsp, lumps, 9)))

    def drop(origin, mins):
        # PF_droptofloor traces down 256 units; SV_HullForEntity selects
        # the 32-unit hull and translates by clip_mins minus item mins.
        offset = tuple(a - b for a, b in zip((-16, -16, -24), mins, strict=True))
        x, y, top = (a - b for a, b in zip(origin, offset, strict=True))

        def first_solid(node, upper, lower, entry=None):
            if node < 0:
                return (upper, entry) if node == -2 else None
            plane, front, back = nodes[node]
            nx, ny, nz, dist, kind = planes[plane]
            constant = nx * x + ny * y - dist
            upper_d, lower_d = constant + nz * upper, constant + nz * lower
            if upper_d >= 0 and lower_d >= 0:
                return first_solid(front, upper, lower, entry)
            if upper_d < 0 and lower_d < 0:
                return first_solid(back, upper, lower, entry)
            mid = -constant / nz
            near, far = (front, back) if upper_d >= 0 else (back, front)
            hit = first_solid(near, upper, mid, entry)
            return hit if hit is not None else first_solid(far, mid, lower, (nz, kind))

        hits = (first_solid(node, top, top - 256) for node in (root, *supporting_roots))
        floors = [hit[0] for hit in hits if hit is not None and hit[1] == (1., 2)]
        if not floors:
            raise ValueError(f"stock shell did not drop onto an axial floor: {origin}")
        # DIST_EPSILON in WinQuake's SV_RecursiveHullCheck, on the open side.
        return (*origin[:2], max(floors) + offset[2] + 1 / 32)

    return drop


def pickup_eye_bounds(origin, mins, maxs):
    """Stock linked item/player overlap expressed as inclusive Q4 eye bounds."""
    # SV_LinkEdict pads FL_ITEM by 15 in XY and the player by 1 in XYZ.
    player_lo, player_hi = (-16, -16, -24), (16, 16, 32)
    padding, eye = (15, 15, 0), (0, 0, 22)
    lower, upper = [], []
    for axis in range(3):
        base = origin[axis] + eye[axis]
        lower.append(ceil((base + mins[axis] - padding[axis] - player_hi[axis] - 1) * 16))
        upper.append(floor((base + maxs[axis] + padding[axis] - player_lo[axis] + 1) * 16))
    return lower, upper


class PickupReference(ShotgunReference):
    def __init__(self, program, models, archive, drop):
        super().__init__(program, models)
        self.archive = archive
        self.drop = drop
        self.console = []

    def builtin(self, builtin_id, name):
        g = self.g
        if name == "precache_model":
            self.builtins[name, builtin_id] += 1
            g[1] = g[4]
        elif name in ("setsize", "setmodel") and (
            name == "setsize" or not self.string(g[7]).startswith("*")
        ):
            self.builtins[name, builtin_id] += 1
            if name == "setmodel":
                model = self.string(g[7])
                payload = self.archive.read(model)
                at, _ = lump_ranges(payload)[14]
                bounds = unpack_from("<6f", payload, at)
                lo, hi = tuple(v - 1 for v in bounds[:3]), tuple(v + 1 for v in bounds[3:])
                self.set(g[4], "model", model)
            else:
                lo, hi = tuple(map(asf, g[7:10])), tuple(map(asf, g[10:13]))
            self.set(g[4], "mins", lo)
            self.set(g[4], "maxs", hi)
            self.set(g[4], "size", tuple(b - a for a, b in zip(lo, hi, strict=True)))
            self.link(g[4])
        elif name == "droptofloor":
            self.builtins[name, builtin_id] += 1
            i = g[28]
            self.set(i, "origin", self.drop(self.get(i, "origin"), self.get(i, "mins")))
            self.set(i, "flags", int(self.get(i, "flags")) | 512)  # FL_ONGROUND.
            self.set(i, "groundentity", 0)
            self.link(i)
            g[1] = asi(1)
        elif name == "ftos":
            self.builtins[name, builtin_id] += 1
            value = asf(g[4])
            g[1] = self.key(str(int(value)) if value.is_integer() else f"{value:.1f}")
        elif name in ("sprint", "stuffcmd"):
            self.builtins[name, builtin_id] += 1
            self.console.append((name, g[4], self.string(g[7])))
        else:
            super().builtin(builtin_id, name)

    def spawn_shells(self, entities, *, expected_count=3):
        boxes = []
        old_time = self.t
        for entity_number, entity in enumerate(entities, 1):
            # Stock single-player normal skill filters NOT_MEDIUM.
            if entity["classname"] != "item_shells" or int(entity.get("spawnflags", "0")) & 512:
                continue
            slot = 4 + len(boxes)
            origin = tuple(map(float, entity["origin"].split()))
            self.add(slot, {**entity, "origin": origin})
            self.t = old_time
            self.event(slot, "item_shells")
            self.t = self.get(slot, "nextthink")
            self.set(slot, "nextthink", 0)
            self.event(slot, "think")
            placed = self.get(slot, "origin")
            if (self.get(slot, "solid"), self.get(slot, "flags")) != (1, 768):
                raise ValueError("stock shell did not become an on-ground item trigger")
            mins, maxs = (self.get(slot, field) for field in ("mins", "maxs"))
            lo, hi = pickup_eye_bounds(placed, mins, maxs)
            boxes.append(dict(entityNumber=entity_number, model=self.get(slot, "model"),
                              origin=placed, amount=int(self.get(slot, "aflag")),
                              triggerEyeMinQ4=lo, triggerEyeMaxQ4=hi))
        self.t = old_time
        if expected_count is not None and len(boxes) != expected_count:
            raise ValueError("stock E1M1 single-player shell inventory changed")
        return boxes

    def cover_shells(self, spawn):
        self.e[1] = spawn.e[1].copy()
        self.s.update(spawn.s)
        for health, before, after, consumed in (
            (0, 25, 25, False), (100, 100, 100, False), (100, 95, 100, True),
            (100, 0, 20, True), (100, 25, 45, True),
        ):
            self.e[4] = spawn.e[4].copy()
            self.set(1, "health", health)
            self.set(1, "ammo_shells", before)
            self.set(1, "currentammo", before)
            sounds = len(self.events)
            self.event(4, "touch", 1)
            expected_model = "" if consumed else spawn.get(4, "model")
            if (self.get(1, "ammo_shells"), self.get(1, "currentammo"),
                self.get(4, "solid"), self.get(4, "model")) != (
                after, after, int(not consumed), expected_model
            ):
                raise ValueError("stock shell callback did not match the expected pickup")
            if consumed and self.events[sounds:] != [("sound", 1, 3., SHELL_SOUND, 1., 1.)]:
                raise ValueError("stock shell pickup sound changed")

