"""Compile the shared QuakeC host around a separately loaded episode map."""

from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from struct import iter_unpack, pack_into

from snes_tooling.quake.quake_bsp_assets import lump_data, lump_ranges, parse_entities
from snes_tooling.quake.quake_brush_replay import BrushEntityState, CanonicalBrushRow
from snes_tooling.quake.quakec_gameplay import ENTITY_FIELDS, ENTITY_STRIDE, Program, _word, build_gameplay, sparse_initial
from snes_tooling.quake.quakec_grunt import GruntReference
from snes_tooling.quake.quakec_knight import pack_knight_roster, spawn_knights
from snes_tooling.quake.quakec_shell_pickups import PickupReference, floor_drop


def _stock_template(archive, *, include_knights=False, carry_weapons=False):
    bsp = archive.read("maps/e1m1.bsp")
    lumps = lump_ranges(bsp)
    models = tuple(iter_unpack("<9f7i", lump_data(bsp, lumps, 14)))
    entities = parse_entities(lump_data(bsp, lumps, 0))
    brushes = tuple(BrushEntityState(i, int(e["model"][1:]) + 1,
        int(e["model"][1:]), 0, (0., 0., 0.), (0., 0., 0.))
        for i, e in enumerate(entities, 1) if e.get("model") in ("*1", "*2", "*3", "*4"))
    row = CanonicalBrushRow(0, 0, 0, 0., None, ())
    _, include, metadata, payloads = build_gameplay(
        archive, bsp, entities, models, row, brushes, cover_soldier_cooldown=False,
        include_exit=False, include_knights=include_knights, carry_weapons=carry_weapons,
    )
    constants = {key: int(value) for line in include.decode("ascii").splitlines()
                 for key, value in (line.split(" = "),)}
    return constants, metadata, payloads


def build_basic_gameplay(archive, bsp, entities, models, row, brushes, *, map_name=""):
    include_knights = any(entity["classname"] == "monster_knight" for entity in entities)
    constants, stock, payloads = _stock_template(
        archive, include_knights=include_knights, carry_weapons=map_name == "e1m2")
    program = Program(archive.read("progs.dat"))
    if map_name == "e1m2":
        constants["QC_CAMPAIGN_ITEMS"] = 1
    solid_ids = tuple(sorted({b.inline_model for b in brushes
        if entities[b.entity_number - 1]["classname"] not in ("func_illusionary", "func_water")}))
    drop = floor_drop(bsp, models[0][10],
                      supporting_roots=tuple(models[i][10] for i in solid_ids))
    spawn = GruntReference(program, models, archive, drop) if include_knights else PickupReference(
        program, models, archive, drop)
    spawn.add(0, {"classname": "worldspawn"})
    spawn.add(1, {"classname": "player", "health": 100})
    shells = spawn.spawn_shells(entities, expected_count=None)
    if len(shells) > 16:
        raise ValueError("basic gameplay supports at most 16 shell pickup triggers")
    first_slot = 4 + len(shells)
    grunt_start = first_slot * ENTITY_STRIDE
    knights = spawn_knights(spawn, entities, first_slot) if include_knights else []
    drop_slot = first_slot + len(knights)
    original = payloads[Path("QuakeBSPQuakeCEdicts.bin")]
    edicts = bytearray(grunt_start if knights else grunt_start + ENTITY_STRIDE)
    edicts[:2 * ENTITY_STRIDE] = original[:2 * ENTITY_STRIDE]
    # Reuse the hash-qualified stock item callback/model/string encoding. The
    # map supplies placement and trigger bounds, independently of this ABI.
    shell_template = original[4*ENTITY_STRIDE:5*ENTITY_STRIDE]
    for i, shell in enumerate(shells):
        at = (4+i) * ENTITY_STRIDE
        edicts[at:at+ENTITY_STRIDE] = shell_template
        # item_shells supplies aflag=20/40; the shared ammo_touch callback
        # consumes this scalar. Its opaque nonzero VM model handle means
        # visible; the independent BSP sprite records select the authored
        # small/large model and are hidden through the shell bitmask.
        pack_into("<H", edicts, at+program.fields["aflag"][1]*2, shell["amount"]*64)
    start = next(e for e in entities if e["classname"] == "info_player_start")
    origin = tuple(map(float, start["origin"].split()))
    hull_origin = tuple(round((models[0][i]+models[0][i+3])*.5) - (22 if i == 2 else 0)
                        for i in range(3))
    for axis in range(3):
        word = round((origin[axis]-hull_origin[axis]) * 8)
        pack_into("<H", edicts, ENTITY_STRIDE+constants["QC_FIELD_ORIGIN"]+2*axis, word & 0xffff)
    constants = {key: value for key, value in constants.items()
                 if not key.startswith("QC_SHELL_") or key in ("QC_SHELL_COUNT", "QC_SHELL_SOUND")}
    constants.update(QC_BASIC_GAMEPLAY=1, QC_HAS_PUSHERS=0,
        QC_ENTRANCE_COUNT=0, QC_ENTRANCE_INIT_OFFSET=0,
        QC_ENTRANCE_INIT_TARGET=0, QC_ENTRANCE_INIT_BYTES=0,
        QC_EDICT_BYTES=(drop_slot + 1) * ENTITY_STRIDE, QC_SHELL_COUNT=len(shells),
        QC_GRUNT=grunt_start, QC_GRUNT_DROP=drop_slot * ENTITY_STRIDE,
        QC_GRUNT_COUNT=0, QC_GRUNT_INIT_WORDS=0)
    for i, shell in enumerate(shells):
        for axis, lower, upper in zip("XYZ", shell["triggerEyeMinQ4"], shell["triggerEyeMaxQ4"], strict=True):
            constants[f"QC_SHELL_{i}_{axis}_MIN"] = lower
            constants[f"QC_SHELL_{i}_{axis}_MAX"] = upper
    payloads[Path("QuakeBSPQuakeCEdicts.bin")] = bytes(edicts)
    payloads[Path("QuakeBSPQuakeCGruntFields.bin")] = b""
    payloads[Path("QuakeBSPGruntFrames.bin")] = bytes(90)
    metadata = {**stock, "schema": "quake-basic-gameplay-v1",
        "bspSha256": sha256(bsp).hexdigest(), "edictsBytes": constants["QC_EDICT_BYTES"],
        "buttonEntity": None, "doorEntity": None, "stockTrace": [],
        "stockEntranceDoors": [], "entranceTrigger": None, "stockEntranceTrace": [],
        "stockGrunts": [], "stockGrunt": None,
        "stockShells": {**stock["stockShells"], "boxes": shells},
        "scope": {"movers": "authored-static", "monsterAi": False,
                  "walk": True, "jump": True, "shotgun": True, "shellPickups": True}}
    if knights:
        spawn.string_ids = metadata.pop("knightStringIds")
        roster, fields = pack_knight_roster(
            spawn, knights, hull_origin, ENTITY_FIELDS, _word, ENTITY_STRIDE)
        payloads[Path("QuakeBSPQuakeCEdicts.bin")] = bytes(edicts) + roster
        payloads[Path("QuakeBSPQuakeCGruntFields.bin")] = fields
        from snes_tooling.quake.quake_grunt_assets import knight_frame_rows
        payloads[Path("QuakeBSPGruntFrames.bin")] = knight_frame_rows()
        constants.update(QC_GRUNT_COUNT=len(knights), QC_GRUNT_INIT_WORDS=len(fields) // 2)
        metadata.update(stockGrunts=knights, stockGrunt=knights[0], stockKnights=knights)
        metadata["scope"]["monsterAi"] = True
    if map_name == "e1m2":
        payloads[Path("QuakeBSPQuakeCInitSparse.bin")] = sparse_initial(
            payloads[Path("QuakeBSPQuakeCGlobals.bin")] + edicts[:grunt_start])
    # Inline models retain their signon poses. Only the subsequently merged
    # pickup visibility states belong to this frame's mutable brush row.
    rows = (replace(row, index=0, brushes=()),)
    if map_name in ("e1m2", "e1m3"):
        from snes_tooling.quake.quake_e1m2_machinery import (
            add_e1m2_pose_rows, build_e1m2_machinery,
            e1m2_machinery_constants, e1m2_machinery_outputs,
        )

        builder = build_e1m2_machinery
        key_kind = "silverKey"
        if map_name == "e1m3":
            from snes_tooling.quake.quake_e1m3_machinery import build_e1m3_machinery
            builder = build_e1m3_machinery
            key_kind = "goldKey"
        machinery = builder(program, archive, models, entities, drop)
        rows = add_e1m2_pose_rows(rows, brushes, machinery)
        from snes_tooling.quake.quake_start_ambient import key_actor

        metadata["stockExitMachinery"] = machinery
        metadata["staticAmbientMdls"] = [key_actor(machinery[key_kind], models)]
        metadata["scope"]["movers"] = "authored-route-machinery"
        payloads.update(e1m2_machinery_outputs(machinery))
        if knights:
            from snes_tooling.quake.quake_grunt_assets import KNIGHT_FRAMES
            key = metadata["staticAmbientMdls"][0]
            constants.update(QC_KNIGHT_KEY_ROW=len(KNIGHT_FRAMES), QC_KNIGHT_KEY_YAW=key["yaw"])
            if map_name == "e1m2":
                constants["QC_SPIKE_ROW"] = len(KNIGHT_FRAMES) + 1
            constants.update({f"QC_KNIGHT_KEY_{axis}": coordinate
                              for axis, coordinate in zip("XYZ", key["renderOriginQ2"], strict=True)})
    include = "".join(f"{key} = {value}\n" for key, value in constants.items()).encode("ascii")
    if map_name in ("e1m2", "e1m3"):
        include += e1m2_machinery_constants(machinery)
    return rows, include, metadata, payloads
