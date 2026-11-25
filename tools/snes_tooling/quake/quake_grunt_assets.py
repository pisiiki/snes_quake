"""Package live enemy animations through the shared MDL billboard pipeline."""
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

from snes_tooling.quake import quake_alias_billboards as billboard
from snes_tooling.quake import quake_alias_format as alias
from snes_tooling.quake import quake_explosion_particles as explosion
from snes_tooling.quake.quake_alias_animation import ROTATION_BASES_BYTES
from snes_tooling.quake.quake_assets import parse_mdl
from snes_tooling.quake.quake_billboard_assets import parse_spr, rasterize_model_variants, rasterize_spr_billboard
from snes_tooling.quake.quake_mdl_bakes import MdlBakeContext, retain_complete_bakes
from snes_tooling.quake.quakec_knight import KNIGHT_MODEL
from snes_tooling.quake.quake_target_layout import asset_layout
from snes_tooling.quake.quake_rom_config import (
    configured_alias_halfbank_count, configured_alias_mdl_world_units_per_texel,
    configured_mesen_target,
)


SOLDIER_FRAMES = (*range(29), *range(40, 90))
E1M1_SOLDIER_FRAMES = (*SOLDIER_FRAMES, *range(90, 114))
# Keep directional density and all stock animation phases within the
# source ROM's remaining sprite banks. The VM still runs every stock frame.
DOG_FRAME_GROUPS = (
    (range(0, 8), (0, 3, 7)),
    (range(8, 17), (8, 16)),
    (range(17, 26), (17, 25)),
    (range(26, 32), (26,)),
    (range(32, 48), (38,)),
    (range(48, 60), (48, 50, 53, 56)),
    (range(60, 69), (60, 64, 68)),
    (range(69, 78), (69,)),
    (range(78, 86), (78,)),
)
DOG_FRAMES = tuple(frame for _, retained in DOG_FRAME_GROUPS for frame in retained)
DOG_FRAME_ROWS = bytes(
    len(E1M1_SOLDIER_FRAMES) + DOG_FRAMES.index(min(retained, key=lambda candidate: abs(frame - candidate)))
    for group, retained in DOG_FRAME_GROUPS for frame in group
)

# Keep each stock animation family distinct. The cartridge executes every
# 20 Hz QuakeC frame while several consecutive frames can reuse one billboard.
KNIGHT_FRAME_GROUPS = (
    (range(0, 9), (0, 4)),
    (range(9, 17), (9, 12, 15)),
    (range(17, 28), (17, 23, 27)),
    (range(28, 31), (29,)),
    (range(31, 42), (31, 38)),
    (range(42, 53), (42, 47, 52)),
    (range(53, 67), (53, 59, 64)),
    (range(67, 76), (69,)),
    (range(76, 86), (80, 85)),
    (range(86, 97), (90, 96)),
)
KNIGHT_FRAMES = tuple(frame for _, retained in KNIGHT_FRAME_GROUPS for frame in retained)


def knight_frame_rows():
    return bytes(KNIGHT_FRAMES.index(min(retained, key=lambda candidate: abs(frame - candidate)))
                 for group, retained in KNIGHT_FRAME_GROUPS for frame in group)


def actor_frame_rows(include_dogs):
    frames = E1M1_SOLDIER_FRAMES if include_dogs else SOLDIER_FRAMES
    rows = bytes(frames.index(frame) if frame in frames else 0 for frame in range(frames[-1] + 1))
    return rows + DOG_FRAME_ROWS if include_dogs else rows


def grunt_alias_outputs(archive, bsp, config, camera_hash, grunt, *, include_dogs=False, ambient=(), armor=(), powerups=(), spike=None):
    if grunt["model"] == KNIGHT_MODEL:
        names = (KNIGHT_MODEL, *(actor["model"] for actor in ambient))
        frame_sets = (KNIGHT_FRAMES, *((actor["frame"],) for actor in ambient))
        frame_rows = knight_frame_rows()
    else:
        names = (grunt["model"], "progs/dog.mdl") if include_dogs else (grunt["model"],)
        frame_sets = (E1M1_SOLDIER_FRAMES, DOG_FRAMES) if include_dogs else (SOLDIER_FRAMES,)
        frame_rows = actor_frame_rows(include_dogs)
    enemy_models = len(names)
    if spike:
        names += (spike,)
        frame_sets += ((0,),)
    names += tuple(item["model"] for item in armor)
    frame_sets += tuple((item["frame"],) for item in armor)
    if include_dogs:
        names += ("progs/backpack.mdl",)
        frame_sets += ((0,),)
    names += tuple(item["model"] for item in powerups)
    frame_sets += tuple((item["frame"],) for item in powerups)
    if include_dogs:
        names += ("progs/g_nail.mdl", "progs/spike.mdl", "progs/g_shot.mdl")
        frame_sets += ((0,), (0,), (0,))
    if powerups:
        from snes_tooling.quake.quakec_gibs import MODELS
        names += MODELS
        frame_sets += ((0,),) * len(MODELS)
        names += ("progs/s_explod.spr", explosion.MODEL)
        frame_sets += (tuple(range(6)), tuple(range(sum(map(len, explosion.tile_frames())))))
    origin = tuple(grunt["origin"])
    spatial = billboard._parse_spatial_bsp(bsp)
    leaf = billboard._locate_leaf(origin, spatial)
    group = billboard.AliasGroup(leaf, spatial.leaf_parents[leaf], (0,))
    state = billboard.AliasState(
        grunt["entityNumber"], 0, 0, billboard._origin_q2(origin, spatial.world_origin),
        origin, leaf, directional_base_sprite=0, yaw_sin_q6=-128, yaw_cos_q6=0,
    )
    payloads = {name: archive.read(name) for name in names if name != explosion.MODEL}
    models = {name: parse_mdl(payload) for name, payload in payloads.items() if name.endswith(".mdl")}
    density = configured_alias_mdl_world_units_per_texel(config)
    context = MdlBakeContext.from_palette(archive.read('gfx/palette.lmp'))
    masters = retain_complete_bakes(models, context, density=density)
    sprites = []
    for model, (name, frames) in enumerate(zip(names, frame_sets, strict=True)):
        requests = tuple((frame, view) for frame in frames for view in range(8))
        if name == explosion.MODEL:
            sprites.extend(explosion.particle_sprites(model, density))
            continue
        if name.endswith(".spr"):
            source = parse_spr(payloads[name])
            for frame in frames:
                sprite = rasterize_spr_billboard(source, frame_index=frame, model_id=model)
                sprites.extend(replace(sprite, view=view) for view in range(8))
            continue
        source = models[name]
        if enemy_models <= model < enemy_models + len(armor):
            skin = armor[model - enemy_models]["skin"]
            source = replace(source, skins=(source.skins[skin],))
        baked = rasterize_model_variants((source, model, density, requests, context))
        if tuple((sprite.frame, sprite.view) for sprite in baked) != requests:
            raise ValueError("gameplay enemy animation sprites are out of order")
        sprites.extend(baked)
    if powerups:
        from snes_tooling.quake.quake_teleport_particles import MODEL, teleport_sprites
        first_single_view = len(sprites)
        sprites.extend(teleport_sprites(len(names), density))
        names += (MODEL,)
        from snes_tooling.quake.quake_combat_particles import MODEL as impact_model, impact_sprites
        sprites.extend(impact_sprites(len(names), density))
        names += (impact_model,)
    if grunt["model"] == KNIGHT_MODEL or armor:
        # Live poses address the sprite directory directly. Its row index
        # still selects the native render mode, but the immutable seed can
        # share one record across all rows.
        live_rows = first_single_view // 8 + len(sprites) - first_single_view if powerups else len(sprites) // 8
        rows = (billboard.AliasRow((state,), (group,)),) * live_rows
    else:
        rows = tuple(billboard.AliasRow(
            (replace(state, sprite=i * 8, directional_base_sprite=i * 8),), (group,),
        ) for i in range(len(sprites) // 8))
    rows += (rows[0],) * 8
    limit = configured_alias_halfbank_count(config)
    halfbanks = asset_layout(playback=False, map_entry="maps/e1m1.bsp" if include_dogs else None).alias_halfbanks
    st, pixels = billboard._pack_sprites_exact(
        rows, (), sprites, max_chunks=limit, rotation_payload=ROTATION_BASES_BYTES,
        physical_halfbanks=halfbanks,
    )
    chunks = st.packer.chunks
    count = len(chunks)
    rowdir = st.packer.location(0, alias.HEADER.size)
    directory = st.sprite_directory_location
    chunks[0][:alias.HEADER.size] = alias.HEADER.pack(
        alias.MAGIC, alias.VERSION, alias.HEADER.size, len(rows), len(sprites), 0, 1, 1,
        count, rowdir.offset, directory.flat_offset, st.static_location.flat_offset, 0, camera_hash,
    )
    chunks[0][rowdir.offset:st.row_directory_end] = b"".join(st.row_records)
    records = bytearray()
    for sprite in sprites:
        location = pixels[sprite.storage_raster]
        records += alias.SPRITE_DIRECTORY.pack(
            location.bank, sprite.model, location.address, sprite.width, sprite.height,
            sprite.projected_width, sprite.projected_height, sprite.frame, sprite.view, sprite.left, sprite.top,
        )
    chunks[directory.chunk][directory.offset:directory.offset + len(records)] = records
    target = configured_mesen_target(config)
    include = alias.render_include(
        row_count=len(rows), sprite_count=len(sprites), static_count=0, chunk_count=count,
        row_directory=rowdir, sprite_directory=directory, static_states=st.static_location,
        fly_facing=st.fly_facing_location, fly_facing_count=1, max_dynamic=1, max_visible=1,
        max_groups=1, fly_row=len(rows)-8, fly_row_count=8, mesen_target=target,
        rotation=st.rotation_location, physical_halfbanks=halfbanks,
    )
    outputs = {Path(f"QuakeBSPAliasRuntime{i}.bin"): bytes(chunk) for i, chunk in enumerate(chunks)}
    metadata = dict(
        schema="quake-level-alias-assets-v1", version=alias.VERSION, mode="static-level-grunt",
        source=dict(cameraTrackFnv1a64=f"{camera_hash:016x}", modelSha256=sha256(payloads[names[0]]).hexdigest()),
        instrumentation=dict(modelNames=list(names)), staticStateCount=0, mdlMasters=masters,
        rasterDensity=dict(mdlWorldUnitsPerTexel=density),
        rasterStorage=dict(variantCount=len(sprites), uniqueRasterCount=len(pixels),
            logicalPixelBytes=sum(len(sprite.storage_raster) for sprite in sprites),
            uniquePixelBytes=sum(len(raster) for raster in pixels),
            policy="exact-width-height-pixels; frame/view records share pixel pointers"),
        sprites=[dict(id=i, model=sprite.model, frame=sprite.frame, sourceView=sprite.view,
                      opaqueTexels=sum(bool(pixel & 0xff00) for pixel in sprite.pixels))
                 for i, sprite in enumerate(sprites)],
        format=dict(
            mesenTarget=target.name, configuredHalfbankCount=limit, maxGsuRomBank=target.max_gsu_rom_bank,
            actualMaxGsuRomBank=max(st.packer.location(i, 32767).bank for i in range(count)),
            chunkCount=count, chunkBytes=32768, storagePhysicalHalfbanks=halfbanks[:limit],
            spriteDirectoryRecordCount=len(sprites), flyFacingCapacity=128, flyFacingRecordCount=1,
            flyFacingPackageOffset=st.fly_facing_location.flat_offset, flyFacingBank=st.fly_facing_location.bank,
            flyFacingAddress=st.fly_facing_location.address,
        ),
        outputs={path.name: dict(bytes=len(blob), sha256=sha256(blob).hexdigest()) for path, blob in outputs.items()},
    )
    outputs.update({
        Path("QuakeBSPAliasAssets.i"): include,
        Path("QuakeBSPAliasAssets.s"): alias.render_assembly(count, physical_halfbanks=halfbanks),
        Path("QuakeBSPGruntFrames.bin"): frame_rows,
    })
    return outputs, metadata
