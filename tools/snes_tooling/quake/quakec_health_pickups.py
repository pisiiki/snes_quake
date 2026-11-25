"""Prepare the regular and Megahealth pickups from original E1M1 QuakeC."""

from snes_tooling.quake.quakec_shell_pickups import PickupReference, floor_drop, pickup_eye_bounds


HEALTH_CUES = {"Small": "items/r_item1.wav", "Large": "items/health1.wav"}
MEGA_CUE = "items/r_item2.wav"
HEALTH_MODELS = {"maps/b_bh10.bsp": (15, "Small"), "maps/b_bh25.bsp": (25, "Large"),
                 "maps/b_bh100.bsp": (100, "Mega")}


def stock_health_boxes(archive, bsp, entities, models):
    from snes_tooling.quake.quakec_gameplay import Program

    drop = floor_drop(bsp, models[0][10], supporting_roots=(models[3][10], models[4][10]))
    spawn = PickupReference(Program(archive.read("progs.dat")), models, archive, drop)
    spawn.add(0, {"classname": "worldspawn"})
    boxes = []
    for entity_id, entity in enumerate(entities, 1):
        if entity["classname"] != "item_health":
            continue
        if int(entity.get("spawnflags", "0")) & 0x700 or any(entity.get(key) for key in
                ("target", "targetname", "killtarget", "message")):
            raise ValueError("E1M1 health host requires regular pickups without skill or target overrides")
        spawn.t = 0.0
        spawn.add(2, {**entity, "origin": tuple(map(float, entity["origin"].split()))})
        spawn.event(2, "item_health")
        spawn.t = spawn.get(2, "nextthink")
        spawn.set(2, "nextthink", 0)
        spawn.event(2, "think")
        model = spawn.get(2, "model")
        amount, size = HEALTH_MODELS[model]
        if (spawn.get(2, "solid"), spawn.get(2, "flags"), spawn.get(2, "healamount"),
                spawn.get(2, "noise")) != (1, 768, amount, MEGA_CUE if size == "Mega" else HEALTH_CUES[size]):
            raise ValueError(f"stock health placement or cue changed for edict {entity_id}")
        origin = spawn.get(2, "origin")
        lower, upper = pickup_eye_bounds(origin, spawn.get(2, "mins"), spawn.get(2, "maxs"))
        boxes.append(dict(entityNumber=entity_id, model=model, origin=origin, amount=amount,
                          size=size, sound=spawn.get(2, "noise"), triggerEyeMinQ4=lower, triggerEyeMaxQ4=upper))
    regular = [box for box in boxes if box["size"] != "Mega"]
    mega = [box for box in boxes if box["size"] == "Mega"]
    if len(regular) != 12 or [box["entityNumber"] for box in mega] != [201, 255]:
        raise ValueError("stock E1M1 health inventory changed")
    # Preserve the twelve existing logical bits independently of the renderer's edict order.
    return regular + mega


def health_include(shells, health, entity_order, *, nails=(), boxes=()):
    """Bind logical pickup masks to the sorted external BSP renderer slots."""
    if len(entity_order) > 32 or set(entity_order) != {box["entityNumber"] for box in (*shells, *health, *nails, *boxes)}:
        raise ValueError("live E1M1 pickup visibility must fit the external mask")
    regular_count = sum(box["size"] != "Mega" for box in health)
    constants = {"QC_HEALTH_COUNT": len(health), "QC_REGULAR_HEALTH_COUNT": regular_count}
    if regular_count < len(health):
        constants["QC_MEGA_COUNT"] = len(health) - regular_count
    for group, boxes in (("SHELL", shells), ("HEALTH", health), ("NAIL", nails), ("EXPLOBOX", boxes)):
        for index, box in enumerate(boxes):
            prefix = f"QC_{group}_{index}"
            slot = entity_order.index(box["entityNumber"])
            constants[f"{prefix}_RENDER_BIT"] = 1 << (slot % 16)
            constants[f"{prefix}_RENDER_HIGH"] = slot // 16
            if group == "HEALTH":
                constants[f"{prefix}_AMOUNT"] = box["amount"]
                constants[f"{prefix}_SOUND"] = ("Small", "Large", "Mega").index(box["size"])
                for axis, lower, upper in zip("XYZ", box["triggerEyeMinQ4"], box["triggerEyeMaxQ4"], strict=True):
                    constants[f"{prefix}_{axis}_MIN"] = lower
                    constants[f"{prefix}_{axis}_MAX"] = upper
    return "".join(f"{name} = {value}\n" for name, value in constants.items()).encode("ascii")
