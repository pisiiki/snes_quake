"""Build the single-player E1M1 nail pickups from the stock item code."""

from snes_tooling.quake.quake_start_ambient import key_actor
from snes_tooling.quake.quakec_grunt import GruntReference
from snes_tooling.quake.quakec_shell_pickups import floor_drop, pickup_eye_bounds


def stock_nailgun(archive, bsp, entities, models, program):
    drop = floor_drop(bsp, models[0][10], supporting_roots=(models[3][10], models[4][10]))
    vm = GruntReference(program, models, archive, drop)
    vm.add(0, {"classname": "worldspawn"})
    units = []
    for number, entity in enumerate(entities, 1):
        name = entity["classname"]
        if name not in ("weapon_nailgun", "item_spikes") or int(entity.get("spawnflags", 0)) & 0x700:
            continue
        vm.t = 0
        vm.add(2, {**entity, "origin": tuple(map(float, entity["origin"].split()))})
        vm.event(2, name)
        vm.t = vm.get(2, "nextthink")
        vm.set(2, "nextthink", 0)
        vm.event(2, "think")
        origin, model = vm.get(2, "origin"), vm.get(2, "model")
        lower, upper = pickup_eye_bounds(origin, vm.get(2, "mins"), vm.get(2, "maxs"))
        record = dict(entityNumber=number, model=model, origin=origin)
        if name == "weapon_nailgun":
            record = key_actor(record, models)
        vm.add(1, {"classname": "player", "flags": 8, "health": 100, "items": 4097, "weapon": 1, "ammo_shells": 25})
        vm.event(2, "touch", 1)
        units.append(dict(**record, amount=int(vm.get(1, "ammo_nails")),
                          equipped=int(vm.get(1, "weapon")), triggerEyeMinQ4=lower, triggerEyeMaxQ4=upper))
    if [(p["entityNumber"], p["amount"]) for p in units] != [(97, 30), (102, 25), (227, 50)]:
        raise ValueError(f"stock E1M1 nail pickups changed: {units}")
    return dict(gun=units[0], boxes=units[1:])


def nailgun_constants(stock, first_row, program):
    gun = stock["gun"]
    gun["spriteRow"] = first_row
    constants = {"QC_NAIL_COUNT": len(stock["boxes"]), "QC_NAILGUN_ROW": first_row,
                 "QC_SPIKE_ROW": first_row + 1, "QC_FIELD_AMMO_NAILS": program.fields["ammo_nails"][1] * 2}
    constants["QC_FIELD_OWNER"] = program.fields["owner"][1] * 2
    constants["QC_NAIL_DAMAGE_FUNCTION"] = program.function_ids["T_Damage"]
    for index, item in enumerate((gun, *stock["boxes"])):
        prefix = f"QC_NAIL_PICKUP_{index}_"
        constants[prefix + "AMOUNT"] = item["amount"]
        for axis, lo, hi in zip("XYZ", item["triggerEyeMinQ4"], item["triggerEyeMaxQ4"], strict=True):
            constants[prefix + axis + "_MIN"] = lo
            constants[prefix + axis + "_MAX"] = hi
    for axis, coord in zip("XYZ", gun["renderOriginQ2"], strict=True):
        constants["QC_NAILGUN_" + axis] = coord
    return constants
