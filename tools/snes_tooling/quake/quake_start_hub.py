"""Original shareware START touch volumes and fresh single-player brush state."""
from hashlib import sha256
from math import ceil, floor
from pathlib import Path
from struct import pack, pack_into
from textwrap import wrap

from snes_tooling.quake.quake_basic_gameplay import build_basic_gameplay
from snes_tooling.quake.quakec_gameplay import ENTITY_STRIDE, Program
from snes_tooling.quake.quakec_reference import ReferenceVM

START_BSP_SHA256 = "a4e907bb36bb13e82be5656342a75cfd412e843784014f76a1df5bdcb63896d0"
HUB_SCHEMA = "quake-start-hub-v1"
EPISODE_EXIT_SCHEMA = "quake-episode-exit-v1"
HUB_INCLUDE = Path("QuakeBSPHubGameplay.i")
HUB_PAYLOAD = Path("QuakeBSPHubGameplay.bin")
RECORD_BYTES = dict(SKILL=14, TELEPORT=20, EXIT=14)
WARNING_Q6 = 128  # Stock touch cooldown and centerprint time: 2 s.
WARNING_RECORD_BYTES = 16
TELEPORT_ARRIVAL_Q6 = 13  # Stock fog think at +0.2 s, rounded up at 64 Hz.
CLUE_EDICT = 4 * ENTITY_STRIDE  # Reuse START's empty basic-gameplay actor slot.

# START BSP water leaves 332–336, reduced on its signed eye-Q4 grid. The
# interval axes are X, Y, Z, X+Y, X-Y, 2X+Y and 2X-Y. Z is already the
# intersection of the stock foot (eye-45) and waist (eye-18) water tests.
_ANY = (-32768, 32767)  # All derived coordinates fit inside this span.
_POOL_SWIM_ZONES = (
    ((5120, 7168), (-640, 1408), (2361, 3081), _ANY, _ANY, _ANY, _ANY),
    ((7168, 7680), (-128, 896), (2361, 3081), _ANY, _ANY, _ANY, _ANY),
    ((7680, 12800), (-1664, 2432), (2105, 3081), (7041, 14209), (6272, 13440), _ANY, _ANY),
    ((8704, 12800), (-1664, 2432), (3081, 3209), (7041, 14209), (6272, 13440),
     (16769, 32767), (16001, 32767)),
)


def _registered_warning(entities, models, origin):
    rows = [(index, entity) for index, entity in enumerate(entities, 1)
            if entity.get("classname") == "trigger_onlyregistered" and entity.get("message")
            and not int(entity.get("spawnflags", "0")) & 512]
    messages = {entity["message"].replace(r"\n", "\n") for _, entity in rows}
    if len(rows) != 3 or len(messages) != 1:
        raise ValueError("original START shareware warning roster changed")
    return dict(message=messages.pop(), durationQ6=WARNING_Q6,
                triggers=[dict(entityNumber=index, **_trigger_bounds(entity, models, origin))
                          for index, entity in rows])


def _skill_hints(entities, models, origin):
    # Stock QuakeC tests the player's facing vector against the trigger's
    # movedir. These are the admitted headings of the original float test
    # for the two authored angles at the port's 256-step yaw resolution.
    headings = {90: [1, 127], 180: [65, 192]}
    rows = [dict(entityNumber=index, message=entity["message"],
                 yawRange=headings[int(entity["angle"])],
                 **_trigger_bounds(entity, models, origin))
            for index, entity in enumerate(entities, 1)
            if entity.get("classname") == "trigger_multiple"
            and entity.get("message", "").endswith((" skill", " skill!"))
            and entity.get("wait") == "2" and not int(entity.get("spawnflags", "0")) & 512]
    if [row["entityNumber"] for row in rows] != [226, 227, 228, 305]:
        raise ValueError("original START difficulty hint roster changed")
    return rows


def _episode_prompts(entities, models, origin):
    rows = []
    # Inclusive byte-yaw endpoints from the original QuakeC facing test.
    for number, model, angle, headings in ((233, "*20", "180", [65, 192]),
                                           (239, "*21", "270", [128, 0])):
        entity = entities[number - 1]
        if tuple(entity.get(key) for key in ("classname", "model", "angle", "wait")) != (
                "trigger_multiple", model, angle, "2"):
            raise ValueError("original START Episode I prompt changed")
        rows.append(dict(entityNumber=number, message=entity["message"].replace(r"\n", "\n"),
                         yawRange=headings, **_trigger_bounds(entity, models, origin)))
    return rows


def _shootable_clue(entities, models, origin):
    entity = entities[307]
    if tuple(entity.get(k) for k in ("classname", "model", "health", "wait", "sounds")) != (
            "trigger_multiple", "*37", "1", "3", "1"):
        raise ValueError("original START shootable clue changed")
    model = models[37]
    body_origin = (*origin[:2], origin[2] - 22)
    # Model loading restores the one-unit inset on the original BBOX.
    lower = [_i16(round((model[i] - 1 - body_origin[i]) * 8), "clue minimum") for i in range(3)]
    upper = [_i16(round((model[i + 3] + 1 - body_origin[i]) * 8), "clue maximum") for i in range(3)]
    return dict(entityNumber=308, edictOffset=CLUE_EDICT, lowerQ3=lower, upperQ3=upper,
                rearmQ6=192, message=entity["message"].replace(r"\n", "\n"))


def _warning_oam(message):
    """Use the existing 8x8 menu font and stock centerprint Y at 224 lines."""
    glyphs = bytearray()
    lines = [line for original in message.upper().split("\n")
             for line in (wrap(original, width=32, break_long_words=False) or [""])]
    if not 1 <= len(lines) <= 4 or any(len(line) > 32 for line in lines):
        raise ValueError("START centerprint does not fit the hardware sprite rows")
    for row, line in enumerate(lines):
        left = (256 - 8 * len(line)) // 2
        for col, char in enumerate(line):
            if not 32 <= ord(char) <= 90:
                raise ValueError("START warning uses a glyph outside the menu font")
            if char != " ":
                glyphs.extend((left + 8 * col, 78 + row * 8, 0xC0 + ord(char) - 32, 0x3F))
    return glyphs + bytes((0, 240, 0, 0)) * (128 - len(glyphs) // 4) + bytes(32)


def hub_static_models(entities):
    """Spawn-normal skill, serverflags=0: episode gates are invisible/non-solid."""
    classes = {"func_wall", "func_door", "func_bossgate"}
    result = tuple(sorted(int(entity["model"][1:]) for entity in entities
                          if entity.get("classname") in classes
                          and entity.get("model", "").startswith("*")
                          and not int(entity.get("spawnflags", "0")) & 512))
    if result != (4, 5, 6, 7, 26, 29, 38, 48):
        raise ValueError("original START fresh-shareware brush roster changed")
    return result


def _i16(value, label):
    if type(value) is not int or not -32768 <= value <= 32767:
        raise ValueError(label + " escapes a signed native word")
    return value


def _q4(point, origin):
    return [_i16(round((value - base) * 16), "hub eye coordinate")
            for value, base in zip(point, origin, strict=True)]


def _trigger_bounds(entity, models, origin):
    model = models[int(entity["model"][1:])]
    # Mod_LoadBrushModel restores the one-unit BSP inset; SV_LinkEdict pads
    # triggers by one more unit. Player linked bounds are [-17,-17,-25]
    # through [17,17,33]. Convert the overlapping player body to eye height22.
    low = [model[axis] - 2 - (33 if axis == 2 else 17) + (22 if axis == 2 else 0)
           for axis in range(3)]
    high = [model[axis + 3] + 2 + (25 if axis == 2 else 17) + (22 if axis == 2 else 0)
            for axis in range(3)]
    return dict(triggerEyeMinQ4=[_i16(ceil((v - o) * 16), "hub trigger minimum")
                                for v, o in zip(low, origin, strict=True)],
                triggerEyeMaxQ4=[_i16(floor((v - o) * 16), "hub trigger maximum")
                                for v, o in zip(high, origin, strict=True)])


def hub_descriptor(archive, entities, models):
    origin = tuple((models[0][axis] + models[0][axis + 3]) * .5 for axis in range(3))
    program = Program(archive.read("progs.dat"))
    oracle = ReferenceVM(program, models)
    oracle.add(0, {"classname": "worldspawn"})
    destinations = {}
    for index, entity in enumerate(entities, 1):
        if entity.get("classname") != "info_teleport_destination":
            continue
        item = {**entity, "origin": tuple(map(float, entity["origin"].split()))}
        oracle.add(index, item)
        oracle.event(index, "info_teleport_destination")
        position = oracle.get(index, "origin")
        mangle = oracle.get(index, "mangle")
        if mangle[0] != 0 or mangle[2] != 0:
            raise ValueError("START teleport destination requires nonzero pitch/roll")
        name = entity["targetname"]
        if name in destinations:
            raise ValueError("START teleport destination is ambiguous")
        destinations[name] = dict(destinationEyeQ4=_q4((*position[:2], position[2] + 22), origin),
                                  destinationYaw=round(mangle[1] / 360 * 256) & 255)
    skills, teleports, exits, ignored, unavailable = [], [], [], [], []
    for index, entity in enumerate(entities, 1):
        if int(entity.get("spawnflags", "0")) & 512:
            continue
        kind = entity.get("classname")
        if kind not in ("trigger_setskill", "trigger_teleport", "trigger_changelevel"):
            continue
        common = dict(entityNumber=index, **_trigger_bounds(entity, models, origin))
        if kind == "trigger_setskill":
            skill = int(entity["message"])
            if skill not in range(4):
                raise ValueError("START skill trigger is outside0..3")
            skills.append(dict(**common, skill=skill))
        elif kind == "trigger_teleport":
            destination = destinations.get(entity.get("target"))
            if destination is None:
                ignored.append(dict(**common, target=entity.get("target"),
                                    reason="stock target is removed info_null, not a teleport destination"))
            else:
                teleports.append(dict(**common, **destination))
        elif entity.get("map") == "e1m1":
            exits.append(dict(**common, destination="e1m1"))
        else:
            unavailable.append(dict(**common, destination=entity.get("map")))
    if sorted(item["skill"] for item in skills) != list(range(4)) or len(teleports) != 6 or len(exits) != 1:
        raise ValueError("original START skill/teleport/Episode1 trigger roster changed")
    return dict(schema=HUB_SCHEMA, skills=skills, teleports=teleports, exits=exits,
                registeredWarning=_registered_warning(entities, models, origin),
                skillHints=_skill_hints(entities, models, origin),
                episodePrompts=_episode_prompts(entities, models, origin),
                poolSwimZonesQ4=_POOL_SWIM_ZONES,
                shootableClue=_shootable_clue(entities, models, origin),
                teleportArrivalDelayQ6=TELEPORT_ARRIVAL_Q6), dict(
        ignoredTeleports=ignored, unavailableExits=unavailable,
        staticInlineModels=list(hub_static_models(entities)),
        overlap="inclusive linked trigger/player bounds in signed eye Q4",
        destinationTransform="original info_teleport_destination spawn callback, including body Z+27")


EPISODE_EXITS = {"e1m1": "e1m2", "e1m2": "e1m3", "e1m3": "e1m4"}


def episode_exit_descriptor(entities, models, source):
    target = EPISODE_EXITS[source]
    origin = tuple((models[0][axis] + models[0][axis + 3]) * .5 for axis in range(3))
    exits = [
        dict(entityNumber=index, destination=target, **_trigger_bounds(entity, models, origin))
        for index, entity in enumerate(entities, 1)
        if entity.get("classname") == "trigger_changelevel" and entity.get("map") == target
        and not int(entity.get("spawnflags", "0")) & 512
    ]
    if len(exits) != 1:
        raise ValueError(f"original {source} requires one authored {target} exit")
    hub = dict(schema=EPISODE_EXIT_SCHEMA, skills=[], teleports=[], exits=exits)
    if source == "e1m1":
        cameras = []
        for index, entity in enumerate(entities, 1):
            if entity["classname"] != "info_intermission":
                continue
            pitch, yaw, roll = map(float, entity["mangle"].split())
            if roll:
                raise ValueError("unsupported rolled E1M1 intermission camera")
            cameras.append(dict(entity=index, eyeQ4=_q4(map(float, entity["origin"].split()), origin),
                                yaw=round(yaw * 256 / 360) & 255, pitch=-round(pitch * 256 / 360)))
        if len(cameras) != 4:
            raise ValueError("the original E1M1 intermission requires four camera entities")
        monsters = [int(e.get("spawnflags", 0)) for e in entities if e["classname"].startswith("monster_")]
        hub["intermission"] = dict(cameras=cameras, monsters=[sum(not flags & mask for flags in monsters)
                                                              for mask in (256, 512, 1024, 1024)])
        trigger, = ((i, e) for i, e in enumerate(entities, 1) if e["classname"] == "trigger_teleport")
        destination, = ((i, e) for i, e in enumerate(entities, 1)
                        if e["classname"] == "info_teleport_destination"
                        and e.get("targetname") == trigger[1]["target"])
        if trigger[1] != {"classname": "trigger_teleport", "model": "*20", "target": "t6"} or (
                int(destination[1].get("angle", 0)) != 0):
            raise ValueError("E1M1 teleport requires its original east-facing t6 destination")
        x, y, z = map(float, destination[1]["origin"].split())
        hub["teleports"] = [dict(entityNumber=trigger[0], destinationEntity=destination[0],
                                 **_trigger_bounds(trigger[1], models, origin),
                                 destinationEyeQ4=_q4((x, y, z + 27 + 22), origin), destinationYaw=0)]
        model = models[int(trigger[1]["model"][1:])]
        hub["teleportAmbientEyeQ4"] = _q4([(model[i] + model[i + 3]) * 0.5 for i in range(3)], origin)
        hub["teleportArrivalDelayQ6"] = TELEPORT_ARRIVAL_Q6
        hints, removers = [], []
        for number, entity in enumerate(entities, 1):
            if entity["classname"] == "trigger_multiple" and "message" in entity:
                if entity.get("wait") != "5" or entity.get("sounds") != "2" or entity.get("delay"):
                    raise ValueError("E1M1 hint no longer has the stock touch behavior")
                angle = entity.get("angle")
                if angle not in (None, "270"):
                    raise ValueError("unsupported E1M1 prompt heading")
                flags = int(entity.get("spawnflags", 0))
                hints.append(dict(entityNumber=number, message=entity["message"],
                                  targetname=entity.get("targetname"), spawnflags=flags,
                                  yawRange=[128, 0] if angle else [0, 255],
                                  **_trigger_bounds(entity, models, origin)))
            elif entity["classname"] == "trigger_once" and entity.get("killtarget") in ("t31", "t32"):
                if entity.get("target") != entity["killtarget"] or entity.get("delay"):
                    raise ValueError("E1M1 hint remover has another linked action")
                removers.append(dict(entityNumber=number, killtarget=entity["killtarget"],
                                     spawnflags=int(entity.get("spawnflags", 0)),
                                     **_trigger_bounds(entity, models, origin)))
        if ([row["targetname"] for row in hints] != ["t32", "t31", None]
                or [row["killtarget"] for row in removers] != ["t31", "t32"]
                or [row["spawnflags"] for row in hints + removers] != [3072, 3072, 0, 3072, 3072]):
            raise ValueError("E1M1 hint and killtarget roster changed")
        hub["hints"] = dict(triggers=hints, removers=removers, durationQ6=128, cooldownQ6=320)
        secrets = []
        for number, entity in enumerate(entities, 1):
            if entity["classname"] != "trigger_secret":
                continue
            if set(entity) != {"classname", "model"}:
                raise ValueError("E1M1 secret has nondefault trigger behavior")
            secrets.append(dict(entityNumber=number, **_trigger_bounds(entity, models, origin)))
        if len(secrets) != 6:
            raise ValueError("stock E1M1 must have six discovery volumes")
        hub["secrets"] = dict(triggers=secrets, message="You found a secret area!", sound="misc/secret.wav")
        panel, = (ent for ent in entities if ent["classname"] == "func_door_secret" and ent.get("message"))
        hub["secretDoorHint"] = panel["message"]
        door, = (ent for ent in entities if ent.get("model") == "*38" and ent["classname"] == "func_door")
        hub["ordinaryDoorHint"] = door["message"]
    return hub


def hub_centerprints(hub):
    """Return the touch records and the full native message-slot order."""
    if "hints" in hub:
        rows = hub["hints"]["triggers"]
        messages = tuple(row["message"] for row in rows)
        if "secrets" in hub:
            messages += (hub["secrets"]["message"],)
        if "secretDoorHint" in hub:
            messages += (hub["secretDoorHint"],)
        if "ordinaryDoorHint" in hub:
            messages += (hub["ordinaryDoorHint"],)
        return rows, messages
    warning = hub["registeredWarning"]
    rows = [dict(trigger, message=warning["message"]) for trigger in warning["triggers"]]
    rows.extend(hub.get("skillHints", ()))
    rows.extend(hub.get("episodePrompts", ()))
    messages = tuple(row["message"] for row in rows)
    if "shootableClue" in hub:
        messages += (hub["shootableClue"]["message"],)
    return rows, messages


def hub_outputs(hub=None):
    from snes_tooling.quake.quake_playable_maps import id_for
    episode_exit = hub is not None and hub["schema"] == EPISODE_EXIT_SCHEMA
    constants = dict(QC_HUB_ENABLED=int(hub is not None and not episode_exit), QC_HUB_TELEPORT_COOLDOWN=45)
    if episode_exit:
        constants["QC_EPISODE_EXIT_ENABLED"] = 1
    if episode_exit and (hub["skills"] or len(hub["exits"]) != 1 or len(hub["teleports"]) > 1):
        raise ValueError("invalid episode teleport or changelevel roster")
    if episode_exit and hub["teleports"]:
        constants["QC_E1M1_TELEPORT"] = 1
        destination = hub["teleports"][0]["destinationEyeQ4"]
        for axis, coordinate, offset, ambient in zip(
                "XYZ", destination, (32 * 16, 0, -22 * 16), hub["teleportAmbientEyeQ4"], strict=True):
            constants[f"QC_TELEPORT_FOG_{axis}"] = (coordinate + offset + 32) // 64
            constants[f"QC_TELEPORT_AMBIENT_{axis}"] = ambient
            constants[f"QC_TELEPORT_BODY_{axis}"] = coordinate // 2
    if hub and "intermission" in hub:
        final = hub["intermission"]
        constants["QC_INTERMISSION_COUNT"] = len(final["cameras"])
        for i, camera in enumerate(final["cameras"]):
            for name, value in zip(("X", "Y", "Z", "YAW", "PITCH"),
                                   (*camera["eyeQ4"], camera["yaw"], camera["pitch"]), strict=True):
                constants[f"QC_INTERMISSION_{i}_{name}"] = value
        for i, count in enumerate(final["monsters"]):
            constants[f"QC_INTERMISSION_{i}_MONSTERS"] = count
    payload = bytearray()
    for name, field in (("SKILL", "skills"), ("TELEPORT", "teleports"), ("EXIT", "exits")):
        rows = hub[field] if hub else ()
        constants.update({f"QC_HUB_{name}_COUNT": len(rows), f"QC_HUB_{name}_OFFSET": len(payload),
                          f"QC_HUB_{name}_RECORD_BYTES": RECORD_BYTES[name]})
        for row in rows:
            low, high = row["triggerEyeMinQ4"], row["triggerEyeMaxQ4"]
            if len(low) != 3 or len(high) != 3 or any(a > b for a, b in zip(low, high, strict=True)):
                raise ValueError("hub trigger bounds must be three inclusive intervals")
            words = [_i16(value, "hub trigger bound") for pair in zip(low, high, strict=True) for value in pair]
            if name == "SKILL":
                value = row["skill"]
                if type(value) is not int or value not in range(4):
                    raise ValueError("hub skill is outside0..3")
                words.append(value)
            elif name == "TELEPORT":
                if len(row["destinationEyeQ4"]) != 3:
                    raise ValueError("hub teleport destination must have three coordinates")
                words.extend(_i16(value, "hub destination") for value in row["destinationEyeQ4"])
                yaw = row["destinationYaw"]
                if type(yaw) is not int or not 0 <= yaw <= 255:
                    raise ValueError("hub teleport yaw must be an integer byte")
                words.append(yaw)
            else:
                target = row["destination"]
                if target not in (EPISODE_EXITS.values() if episode_exit else ("e1m1",)):
                    raise ValueError("authored exit has an unsupported destination")
                target_id = id_for(target)
                words.append(target_id)
                constants["QC_EPISODE_EXIT_MAP_ID"] = target_id
                if episode_exit:
                    constants["QC_HUB_EXIT_MIN_X"] = low[0]
                    span = high[0] - low[0] + 1
                    if not 1 <= span <= 65535:
                        raise ValueError("episode exit span overflows a native word")
                    constants["QC_HUB_EXIT_X_SPAN"] = span
            if len(words) * 2 != RECORD_BYTES[name]:
                raise ValueError("hub native record width differs from its contract")
            payload += pack("<" + "H" * len(words), *(value & 65535 for value in words))
    if hub and "teleportArrivalDelayQ6" in hub:
        delay = hub["teleportArrivalDelayQ6"]
        if type(delay) is not int or not 0 < delay < constants["QC_HUB_TELEPORT_COOLDOWN"]:
            raise ValueError("teleport arrival delay exceeds the cooldown")
        constants["QC_HUB_ARRIVAL_Q6"] = delay
    if hub and (not episode_exit or "hints" in hub):
        warning = hub["hints"] if episode_exit else hub["registeredWarning"]
        rows, messages = hub_centerprints(hub)
        constants.update(QC_HUB_WARNING_OFFSET=len(payload),
                         QC_HUB_WARNING_COUNT=len(rows),
                         QC_HUB_WARNING_Q6=warning["durationQ6"],
                         QC_HUB_WARNING_RECORD_BYTES=WARNING_RECORD_BYTES)
        for row in rows:
            words = [value for pair in zip(row["triggerEyeMinQ4"], row["triggerEyeMaxQ4"], strict=True)
                     for value in pair]
            yaw_min, yaw_max = row.get("yawRange", (0, 255))
            if not (0 <= yaw_min <= 255 and 0 <= yaw_max <= 255):
                raise ValueError("START centerprint has an invalid yaw range")
            payload += pack("<6h2H", *words, yaw_min, ((yaw_max - yaw_min) & 255) + 1)
        if episode_exit:
            constants.update(QC_E1M1_HINTS=1, QC_HINT_REPEAT_Q6=warning["cooldownQ6"],
                             QC_HINT_DISMISS_OFFSET=len(payload))
            for remover in warning["removers"]:
                gate = next(i for i, row in enumerate(rows) if row["targetname"] == remover["killtarget"])
                bounds = [v for pair in zip(remover["triggerEyeMinQ4"], remover["triggerEyeMaxQ4"], strict=True)
                          for v in pair]
                payload += pack("<6hH", *bounds, 2 * gate)
        if "secrets" in hub:
            secret_rows = hub["secrets"]["triggers"]
            constants.update(QC_SECRET_COUNT=len(secret_rows), QC_SECRET_OFFSET=len(payload),
                             QC_SECRET_GATE=messages.index(hub["secrets"]["message"]) + 1)
            if "secretDoorHint" in hub:
                constants["QC_SECRET_DOOR_HINT_GATE"] = messages.index(hub["secretDoorHint"]) + 1
            if "ordinaryDoorHint" in hub:
                constants["QC_ORD_DOOR_HINT_GATE"] = messages.index(hub["ordinaryDoorHint"]) + 1
            for i, row in enumerate(secret_rows):
                bounds = [v for pair in zip(row["triggerEyeMinQ4"], row["triggerEyeMaxQ4"], strict=True)
                          for v in pair]
                payload += pack("<6hH", *bounds, 1 << i)
        clue = hub.get("shootableClue")
        if clue is not None:
            constants.update(QC_HUB_CLUE_GATE=len(rows) + 1, QC_HUB_CLUE_EDICT=clue["edictOffset"],
                             QC_HUB_CLUE_REARM_Q6=clue["rearmQ6"])
        tables = {message: _warning_oam(message) for message in dict.fromkeys(messages)}
        constants["QC_HUB_WARNING_OAM_TABLE_OFFSET"] = len(payload)
        slots = len(messages)
        offset = len(payload) + slots * 2
        offsets = {}
        for message, table in tables.items():
            offsets[message] = offset
            offset += len(table)
        payload += pack("<" + "H" * slots, *(offsets[message] for message in messages))
        constants["QC_HUB_WARNING_OAM_OFFSET"] = len(payload)
        payload += b"".join(tables.values())
        if "poolSwimZonesQ4" in hub:
            zones = hub["poolSwimZonesQ4"]
            if len(zones) != 4 or any(len(zone) != 7 for zone in zones):
                raise ValueError("START swim zones require four seven-axis records")
            for axis, name in enumerate(("X", "Y")):
                lower = min(zone[axis][0] for zone in zones)
                upper = max(zone[axis][1] for zone in zones)
                constants.update({f"QC_HUB_SWIM_{name}_MIN": lower,
                                  f"QC_HUB_SWIM_{name}_SPAN": upper - lower})
            constants["QC_HUB_SWIM_OFFSET"] = len(payload)
            for zone in zones:
                for lo, hi in zone:
                    _i16(hi, "swim bound")
                    if hi <= _i16(lo, "swim bound"):
                        raise ValueError("START swim zone has an empty interval")
                    payload += pack("<hH", lo, hi - lo)
            constants["QC_HUB_SWIM_END"] = len(payload)
    constants["QC_HUB_BYTES"] = len(payload)
    include = "".join(f"{key} = {value}\n" for key, value in constants.items()).encode("ascii")
    return {HUB_INCLUDE: include, HUB_PAYLOAD: bytes(payload)}


def build_gameplay(archive, bsp, entities, models, row, brushes):
    if sha256(bsp).hexdigest() != START_BSP_SHA256:
        raise ValueError("START hub requires the original shareware BSP")
    active = set(hub_static_models(entities))
    brushes = tuple(brush for brush in brushes if brush.inline_model in active)
    rows, include, metadata, outputs = build_basic_gameplay(archive, bsp, entities, models, row, brushes)
    hub, provenance = hub_descriptor(archive, entities, models)
    # The common shot trace already clips solid edicts to their linked box.
    # Leave damage to the clue's own rearm logic instead of the combat VM.
    clue = hub["shootableClue"]
    edict_path = Path("QuakeBSPQuakeCEdicts.bin")
    edicts = bytearray(outputs[edict_path])
    if len(edicts) != CLUE_EDICT + ENTITY_STRIDE or any(edicts[CLUE_EDICT:]):
        raise ValueError("START's empty clue edict is unavailable")
    fields = Program(archive.read("progs.dat")).fields
    for field, coords in (("mins", clue["lowerQ3"]), ("maxs", clue["upperQ3"])):
        pack_into("<3h", edicts, CLUE_EDICT + fields[field][1] * 2, *coords)
    pack_into("<H", edicts, CLUE_EDICT + fields["solid"][1] * 2, 2 * 64)  # SOLID_BBOX.
    outputs[edict_path] = bytes(edicts)
    from snes_tooling.quake.quake_start_ambient import ambient_roster
    from snes_tooling.quake.quake_assets import parse_mdl
    ambient = ambient_roster(archive, bsp, entities, models)
    outputs[Path("QuakeBSPGruntFrames.bin")] = bytes(len(parse_mdl(archive.read("progs/zombie.mdl")).frames))
    metadata = {**metadata, "schema": "quake-start-gameplay-v1", "hub": hub, "hubProvenance": provenance,
                "staticAmbientMdls": ambient}
    return rows, include, metadata, {**outputs, **hub_outputs(hub)}
