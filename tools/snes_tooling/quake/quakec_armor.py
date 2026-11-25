"""Derive E1M1 armor placement, protection and model skins from stock QuakeC."""

from snes_tooling.quake.quake_start_ambient import key_actor
from snes_tooling.quake.quakec_grunt import GruntReference
from snes_tooling.quake.quakec_shell_pickups import floor_drop, pickup_eye_bounds


def stock_armor(archive, bsp, entities, models, program):
    drop = floor_drop(bsp, models[0][10], supporting_roots=(models[3][10], models[4][10]))
    vm = GruntReference(program, models, archive, drop)
    vm.add(0, {"classname": "worldspawn"})
    pickups = []
    for number, entity in enumerate(entities, 1):
        if entity["classname"] not in ("item_armor1", "item_armor2"):
            continue
        if int(entity.get("spawnflags", 0)) or any(entity.get(k) for k in ("target", "killtarget")):
            raise ValueError("E1M1 armor requires stock unconditional single-player pickups")
        vm.t = 0
        vm.add(2, {**entity, "origin": tuple(map(float, entity["origin"].split()))})
        vm.event(2, entity["classname"])
        vm.t = vm.get(2, "nextthink")
        vm.set(2, "nextthink", 0)
        vm.event(2, "think")
        model, origin = vm.get(2, "model"), vm.get(2, "origin")
        lower, upper = pickup_eye_bounds(origin, vm.get(2, "mins"), vm.get(2, "maxs"))
        props = key_actor(dict(entityNumber=number, model=model, origin=origin), models)
        skin = int(vm.get(2, "skin"))
        vm.add(1, {"classname": "player", "health": 100})
        vm.event(2, "touch", 1)
        pickups.append(dict(**props, skin=skin, value=int(vm.get(1, "armorvalue")),
                            tenths=round(vm.get(1, "armortype") * 10), bit=int(vm.get(1, "items")),
                            sound=vm.events[-1][3], triggerEyeMinQ4=lower, triggerEyeMaxQ4=upper))
    if [(a["skin"], a["tenths"], a["value"], a["sound"]) for a in pickups] != [
            (0, 3, 100, "items/armor1.wav"), (1, 6, 150, "items/armor1.wav")]:
        raise ValueError("unexpected stock E1M1 armor inventory")
    return pickups


def armor_constants(pickups, first_row, program):
    constants = {"QC_ARMOR_COUNT": len(pickups)}
    for name in ("armortype", "armorvalue"):
        constants["QC_FIELD_" + name.upper()] = program.fields[name][1] * 2
    for index, item in enumerate(pickups):
        key = f"QC_ARMOR_{index}_"
        item["spriteRow"] = first_row + index
        for name in ("value", "tenths", "bit", "spriteRow"):
            constants[key + name.upper()] = item[name]
        for axis, lo, hi, pos in zip("XYZ", item["triggerEyeMinQ4"], item["triggerEyeMaxQ4"],
                                     item["renderOriginQ2"], strict=True):
            constants.update({key + axis + "_MIN": lo, key + axis + "_MAX": hi, key + axis: pos})
    return constants
