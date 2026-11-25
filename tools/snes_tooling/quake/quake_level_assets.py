"""Assets for no-demo Fly targets and their optional gameplay slices."""
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
from struct import iter_unpack
from types import SimpleNamespace

from snes_tooling.quake import quake_alias_format as alias
from snes_tooling.quake import quake_alias_packing as packing
from snes_tooling.quake.quake_alias_animation import ROTATION_BASES_BYTES
from snes_tooling.quake.quake_target_layout import asset_layout
from snes_tooling.quake.quake_rom_config import (
    configured_target, configured_alias_halfbank_count, configured_mesen_target,
    configured_soundtrack,
)


def json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("ascii")


def recorded_surface_clock(metadata):
    if metadata.get("target", {}).get("mode") == "fly":
        return 0.0, 0, 30
    demo = metadata["demo"]
    return (float(demo["first_server_time"]), int(demo["precise_track_pose_count"]),
            int(demo["precise_track_sample_rate_hz"]))


def normalize_brush_texinfo(prepared, replay):
    """Rebase overflowing UVs once for mesh, fragments and lightmap sampling."""
    from snes_tooling.quake import quake_bsp_brush_assets as brush
    from snes_tooling.quake import quake_bsp_assets as bsp
    source = prepared.source
    faces = list(source.faces)
    texinfo = list(source.texinfo)
    for model_id in sorted({state.inline_model for state in replay.signon_brushes}):
        model = source.models[model_id]
        for index in range(model[14], model[14] + model[15]):
            face = faces[index]
            info = texinfo[face.texinfo]
            polygon = [source.vertices[v] for v in brush._face_vertex_ids(source, face)]
            s, t = bsp.face_texture_coordinates(polygon, info)
            if all(-32768 <= bsp.round_half_away_from_zero(v * 16) <= 32767 for v in (*s, *t)):
                continue
            texture = source.textures[int(info[8])]
            if texture.name.startswith("*"):
                texture = replace(texture, width=math.lcm(texture.width, 128),
                                  height=math.lcm(texture.height, 128))
            _, _, (ds, dt) = bsp.normalized_face_texture_coordinates(polygon, info, texture)
            updated = list(info)
            updated[3] -= ds
            updated[7] -= dt
            faces[index] = replace(face, texinfo=len(texinfo))
            texinfo.append(tuple(updated))
    return replace(prepared, source=replace(source, faces=tuple(faces), texinfo=tuple(texinfo)))


def empty_alias_outputs(config, camera_hash):
    target = configured_mesen_target(config)
    count = configured_alias_halfbank_count(config)
    halfbanks = asset_layout(playback=False).alias_halfbanks
    row_offset = alias.HEADER.size
    row_end = row_offset + 8 * alias.ROW_DIRECTORY.size
    packer = packing.HalfbankPacker(row_end, max_chunks=count, physical_halfbanks=halfbanks)
    rows = packer.location(0, row_offset)
    empty = packer.location(0, row_end)
    facing = packer.place(bytes(128 * alias.FLY_FACING_RECORD.size), alignment=2)
    rotation = packer.place(ROTATION_BASES_BYTES, alignment=2)
    packer.chunks[0][:row_offset] = alias.HEADER.pack(
        alias.MAGIC, alias.VERSION, alias.HEADER.size, 8, 0, 0, 0, 0, 1,
        row_offset, empty.flat_offset, empty.flat_offset, 0, camera_hash)
    packer.chunks[0][row_offset:row_end] = alias.ROW_DIRECTORY.pack(0, 0, 0, 0, 0, 0) * 8
    payload = bytes(packer.chunks[0])
    include = alias.render_include(
        row_count=8, sprite_count=0, static_count=0, chunk_count=1,
        row_directory=rows, sprite_directory=empty, static_states=empty,
        fly_facing=facing, fly_facing_count=0, max_dynamic=0, max_visible=0,
        max_groups=0, fly_row=0, fly_row_count=8, mesen_target=target,
        rotation=rotation, physical_halfbanks=halfbanks)
    include = include.replace(b"BSP_ALIAS_ENTITY_SUPPORTED = 1", b"BSP_ALIAS_ENTITY_SUPPORTED = 0")
    metadata = dict(schema="quake-level-alias-assets-v1", version=alias.VERSION,
        mode="static-level-empty-aliases", source=dict(cameraTrackFnv1a64=f"{camera_hash:016x}"),
        instrumentation=dict(modelNames=[]), staticStateCount=0, sprites=[],
        format=dict(mesenTarget=target.name, configuredHalfbankCount=count,
            maxGsuRomBank=target.max_gsu_rom_bank,
            actualMaxGsuRomBank=packer.location(0, 32767).bank, chunkCount=1,
            chunkBytes=32768, storagePhysicalHalfbanks=halfbanks[:count],
            spriteDirectoryRecordCount=0, flyFacingCapacity=128, flyFacingRecordCount=0,
            flyFacingPackageOffset=facing.flat_offset, flyFacingBank=facing.bank,
            flyFacingAddress=facing.address),
        outputs={"QuakeBSPAliasRuntime0.bin": dict(bytes=len(payload),
            sha256=hashlib.sha256(payload).hexdigest())})
    return {Path("QuakeBSPAliasRuntime0.bin"): payload,
            Path("QuakeBSPAliasAssets.i"): include,
            Path("QuakeBSPAliasAssets.s"): alias.render_assembly(1, physical_halfbanks=halfbanks),
            Path("QuakeBSPAliasAssets.json"): json_bytes(metadata)}


def build_outputs(pak_path, config):
    from snes_tooling.quake.quake_assets import PakArchive
    from snes_tooling.quake.quake_bsp_assets import (
        lump_ranges, lump_data, parse_entities, player_start, LUMP_ENTITIES, LUMP_MODELS,
    )
    from snes_tooling.quake.quake_demo import CameraSample, DEFAULT_VIEWHEIGHT
    from snes_tooling.quake.quake_brush_replay import (
        BrushEntityState, CanonicalBrushReplay, CanonicalBrushRow,
        encode_brush_replay, encode_precise_camera_track, fnv1a64,
    )
    from snes_tooling.quake.quake_bsp_brush_assets import build_brush_assets, prepare_brush_source
    from snes_tooling.quake.generate_quake_brush_replay import asset_include
    from snes_tooling.quake import generate_quake_snes_weapon_sprites as weapon
    from snes_tooling.quake import generate_quake_snes_soundtrack as sound
    from snes_tooling.quake import generate_quake_alias_visibility as visibility
    from snes_tooling.quake import quake_alias_visibility_projection as projection
    target = configured_target(config)
    if target["mode"] != "fly":
        raise ValueError("static level producer requires a Fly-only target")
    archive = PakArchive(pak_path)
    bsp = archive.read(target["map"])
    lumps = lump_ranges(bsp)
    entities = parse_entities(lump_data(bsp, lumps, LUMP_ENTITIES))
    start, angle = player_start(entities)
    eye = (*start[:2], start[2] + DEFAULT_VIEWHEIGHT)
    camera = CameraSample(0, 0.0, eye, DEFAULT_VIEWHEIGHT, (0.0, angle, 0.0), target["map"])
    row = CanonicalBrushRow(0, 0, 0, 0.0, camera, ())
    fingerprint = fnv1a64(encode_precise_camera_track((row,)))
    model_count = len(lump_data(bsp, lumps, LUMP_MODELS)) // 64
    precache = ("", target["map"], *(f"*{i}" for i in range(1, model_count)))
    brushes = []
    for index, entity in enumerate(entities, start=1):
        model = entity.get("model", "")
        classname = entity.get("classname", "")
        if not model.startswith("*") or not model[1:].isdigit():
            continue
        if classname.startswith("trigger_"):
            continue
        if classname not in {
            "func_wall", "func_illusionary", "func_door", "func_door_secret", "func_plat",
            "func_train", "func_button", "func_water", "func_episodegate", "func_bossgate",
        }:
            raise ValueError(f"unsupported visible inline entity: {classname}")
        number = int(model[1:])
        origin = tuple(float(v) for v in entity.get("origin", "0 0 0").split())
        # Quake brush `angle` specifies movement direction, not rendered rotation.
        brushes.append(BrushEntityState(index, number + 1, number, 0, origin, (0., 0., 0.)))
    if target.get("gameplay") == "start-hub":
        from snes_tooling.quake.quake_start_hub import hub_static_models
        active = set(hub_static_models(entities))
        brushes = [brush for brush in brushes if brush.inline_model in active]
    rows = (row,)
    gameplay, gameplay_include = {}, b""
    if target.get("gameplay") in ("e1m1-button-door", "basic", "start-hub"):
        name = Path(target["map"]).stem
        builder_options = {}
        if target["gameplay"] == "basic":
            from snes_tooling.quake.quake_basic_gameplay import build_basic_gameplay as build_gameplay
            builder_options["map_name"] = name
        elif target["gameplay"] == "start-hub":
            from snes_tooling.quake.quake_start_hub import build_gameplay
        else:
            from snes_tooling.quake.quakec_gameplay import build_gameplay
        models = tuple(iter_unpack("<9f7i", lump_data(bsp, lumps, LUMP_MODELS)))
        rows, gameplay_include, gameplay_meta, gameplay = build_gameplay(
            archive, bsp, entities, models, row, brushes, **builder_options)
        if name in ("e1m2", "e1m3"):
            from snes_tooling.quake.quake_e1m2_machinery import e1m2_signon_brushes
            brushes = e1m2_signon_brushes(brushes, gameplay_meta["stockExitMachinery"])
        from snes_tooling.quake.quake_landing import landing_outputs
        origin = tuple((models[0][axis] + models[0][axis + 3]) * .5 for axis in range(3))
        gameplay.update(landing_outputs(archive, bsp, origin))
        from snes_tooling.quake.quake_start_hub import EPISODE_EXITS, episode_exit_descriptor, hub_outputs
        if name in EPISODE_EXITS:
            exit_table = episode_exit_descriptor(entities, models, name)
            gameplay_meta = {**gameplay_meta, "hub": exit_table}
            gameplay.update(hub_outputs(exit_table))
        if target.get("gameplay") == "e1m1-button-door":
            from snes_tooling.quake.quakec_health_pickups import stock_health_boxes
            gameplay_meta["stockHealth"] = {"boxes": stock_health_boxes(archive, bsp, entities, models)}
        gameplay[Path("QuakeBSPQuakeCGameplay.json")] = json_bytes(gameplay_meta)
    replay = CanonicalBrushReplay(0, 30, 0.0, fingerprint, precache, 0, tuple(brushes), rows)
    external, payloads, active_rows, active_entities = None, None, b"", ()
    if gameplay and gameplay_meta["stockShells"]["boxes"]:
        from snes_tooling.quake.quake_external_bsp_replay import (
            CanonicalExternalBspReplay, ExternalBspEntityState, ExternalBspRow,
        )
        from snes_tooling.quake.quake_external_bsp_snes import encode_external_active_rows
        shells = gameplay_meta["stockShells"]["boxes"]
        health = gameplay_meta.get("stockHealth", {}).get("boxes", [])
        nails = gameplay_meta.get("stockNailgun", {}).get("boxes", [])
        boxes = [gameplay_meta["stockExplobox"]] if "stockExplobox" in gameplay_meta else []
        pickups = sorted((*shells, *health, *nails, *boxes), key=lambda box: box["entityNumber"])
        names = tuple(sorted({box["model"] for box in pickups}))
        states = tuple(ExternalBspEntityState(
            box["entityNumber"], names.index(box["model"]), 0,
            tuple(round(axis * 8) / 8 for axis in box["origin"]), (0., 0., 0.),
        ) for box in pickups)
        external = CanonicalExternalBspReplay(
            replay.sample_rate_hz, replay.first_server_time, replay.camera_track_fnv1a64,
            names, tuple(range(len(precache), len(precache) + len(names))),
            replay.source_sample_count, tuple(ExternalBspRow(row.camera, states) for row in rows),
        )
        payloads = {name: archive.read(name) for name in names}
        active_rows, active_meta = encode_external_active_rows(external)
        active_entities = tuple(active_meta["entityIds"])
        if active_entities != tuple(box["entityNumber"] for box in pickups):
            raise ValueError("pickup renderer mask order differs from stock entity order")
        if health:
            from snes_tooling.quake.quakec_health_pickups import health_include
            gameplay_include += health_include(shells, health, active_entities, nails=nails, boxes=boxes)
    prepared, replay = prepare_brush_source(
        bsp, replay, external_replay=external, external_model_payloads=payloads,
    )
    prepared = normalize_brush_texinfo(prepared, replay)
    assets = build_brush_assets(
        bsp, archive.read("gfx/palette.lmp"), replay, prepared_source=prepared,
        external_active_rows=active_rows, external_active_entities=active_entities,
        platform_bottoms={m["inlineModel"]: m["positionsQ4"][0] // 2
                          for m in gameplay_meta.get("stockExitMachinery", {}).get("movers", [])
                          if "visualRows" in m} if gameplay else {},
        fragment_gameplay=bool(gameplay),
        independent_inline_entities=tuple(leaf["renderEntity"] for leaf in (
            *gameplay_meta.get("stockEntranceDoors", []),
            *gameplay_meta.get("stockExitMachinery", {}).get("movers", []),
            *gameplay_meta.get("stockExitMachinery", {}).get("secretDoors", []),
            *gameplay_meta.get("stockExitMachinery", {}).get("ordinaryDoors", []),
        )) if gameplay else (),
    )
    from snes_tooling.quake.quake_entrance_visuals import entrance_visual_outputs
    entrance_outputs, entrance_visuals = entrance_visual_outputs(
        replay, gameplay_meta if gameplay else {}, assets.metadata,
        external_entity_ids=prepared.external_entity_ids,
    )
    metadata = {**assets.metadata, "runtimeReplay": dict(supported=True, mode="static-level",
        canonicalRowCount=len(rows), runtimeRowCount=len(rows), blockers=[]),
        "entranceVisualOverrides": entrance_visuals}
    outputs = {**assets.outputs, **gameplay, **entrance_outputs}
    from snes_tooling.quake.quake_start_hub import HUB_INCLUDE, hub_outputs
    if HUB_INCLUDE not in outputs:
        outputs.update(hub_outputs())
    outputs[Path("QuakeBSPBrushAssets.i")] = asset_include(metadata) + gameplay_include
    outputs[Path("QuakeBSPBrushAssets.json")] = json_bytes(metadata)
    # QBSE orders external slots after inline slots. The canonical interchange
    # replay instead orders all states by their original entity number.
    canonical_rows = tuple(replace(row, brushes=tuple(sorted(row.brushes))) for row in replay.rows)
    outputs[Path("QuakeBSPBrushReplay.bin")] = encode_brush_replay(replace(replay, rows=canonical_rows))
    outputs[Path("QuakeBSPBrushReplay.json")] = json_bytes(dict(mode="static-level", map=target["map"]))
    if gameplay and gameplay_meta.get("stockGrunt"):
        from snes_tooling.quake.quake_grunt_assets import grunt_alias_outputs
        grunt_assets, grunt_meta = grunt_alias_outputs(
            archive, bsp, config, fingerprint, gameplay_meta["stockGrunt"],
            include_dogs=bool(gameplay_meta.get("stockDogs")), ambient=gameplay_meta.get("staticAmbientMdls", ()),
            armor=gameplay_meta.get("stockArmor", ()), powerups=gameplay_meta.get("stockPowerups", ()),
            spike=gameplay_meta.get("campaignWeapons", {}).get("spikeModel"),
        )
        outputs.update(grunt_assets)
        outputs[Path("QuakeBSPAliasAssets.json")] = json_bytes(grunt_meta)
    elif gameplay and gameplay_meta.get("staticAmbientMdls"):
        from snes_tooling.quake.quake_start_ambient import ambient_alias_outputs
        ambient_assets, ambient_meta = ambient_alias_outputs(
            archive, bsp, config, fingerprint, gameplay_meta["staticAmbientMdls"])
        outputs.update(ambient_assets)
        outputs[Path("QuakeBSPAliasAssets.json")] = json_bytes(ambient_meta)
    else:
        outputs.update(empty_alias_outputs(config, fingerprint))
    if gameplay:
        outputs.update(weapon.build_live_outputs(archive, gameplay_meta["stockShotgun"]["viewSequence"],
                                                axe_sequence=gameplay_meta["stockAxe"]["viewSequence"],
                                                nailgun="stockNailgun" in gameplay_meta or "campaignWeapons" in gameplay_meta))
    else:
        outputs[Path("QuakeBSPWeaponSprites.i")] = weapon.assembly(b"", b"\0", [], [])
        outputs[Path("QuakeBSPWeaponSpritesData0.bin")] = b""
    outputs[Path("QuakeBSPWeaponSpritesMask.i")] = (
        "BSP_X2_WEAPON_COMMON_CORE_PROVEN = 0\n" + "".join(
            f"BSP_X2_WEAPON_OPAQUE_{axis} = 0\n" for axis in ("X_FIRST", "Y_FIRST", "X_END", "Y_END"))).encode()
    soundtrack = configured_soundtrack(config)
    if soundtrack.enabled:
        raise ValueError("Fly-only level has no recorded soundtrack")
    disabled, _ = sound._disabled_outputs(config_path=config, demo=None,
        replay_payload=b"", camera_payload=b"", sample_rate_hz=soundtrack.sample_rate_hz,
        volume=soundtrack.volume)
    outputs.update(disabled)
    empty = SimpleNamespace(source_rows=0, ordered_rows=0, stride=10,
                            dictionary_count=0, maximum_records=0, maximum_mask_bytes=0)
    outputs[Path("QuakeBSPAliasVisibility.i")] = visibility._render_include(empty, empty, reuse_bytes=0) + (
        "BSP_ALIAS_ARCHIVE_VERSION = 3\n"
        "BSP_ALIAS_ARCHIVE_MAX_DECODED_BYTES = 0\nBSP_ALIAS_ARCHIVE_PAYLOAD_BYTES = 0\n"
    ).encode()
    outputs[Path("QuakeBSPAliasVisibility.s")] = projection.assembly()
    for name in ("QuakeBSPAliasVisibilityArchive0.bin", "QuakeBSPAliasVisibilityArchive1.bin",
                 "QuakeBSPAliasVisibilityDirectory.bin"):
        outputs[Path(name)] = b""
    for name in (visibility.TEMPORAL_ENABLED_NAME, visibility.TEMPORAL_DISABLED_NAME, visibility.PREDECESSOR_NAME):
        outputs[name] = b""
    outputs[Path("QuakeBSPAliasVisibility.json")] = json_bytes(dict(mode="static-level", enabled=False))
    return outputs
