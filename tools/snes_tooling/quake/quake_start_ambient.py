"""Compile fixed-pose gameplay MDL billboards through the shared asset pipeline."""
from collections import defaultdict
from hashlib import sha256
from math import cos, sin, tau
from pathlib import Path

from snes_tooling.quake import quake_alias_billboards as billboard
from snes_tooling.quake import quake_alias_format as alias
from snes_tooling.quake.quake_alias_animation import ROTATION_BASES_BYTES
from snes_tooling.quake.quake_assets import parse_mdl
from snes_tooling.quake.quake_billboard_assets import rasterize_model_variants
from snes_tooling.quake.quake_mdl_bakes import MdlBakeContext, retain_complete_bakes
from snes_tooling.quake.quake_target_layout import asset_layout
from snes_tooling.quake.quake_rom_config import (
    configured_alias_halfbank_count, configured_alias_mdl_world_units_per_texel, configured_mesen_target,
)
from snes_tooling.quake.quakec_gameplay import Program
from snes_tooling.quake.quakec_grunt import GruntReference

MODEL = "progs/zombie.mdl"
POSE = 192


def ambient_roster(archive, bsp, entities, models):
    """Run the stock spawn callback, then retain its crucified visual pose only."""
    program = Program(archive.read("progs.dat"))
    oracle = GruntReference(program, models, archive, lambda origin, mins: origin)
    oracle.add(0, {"classname": "worldspawn"})
    spatial = billboard._parse_spatial_bsp(bsp)
    result = []
    for number, entity in enumerate(entities, 1):
        if entity.get("classname") != "monster_zombie" or int(entity.get("spawnflags", "0")) & 512:
            continue
        if not int(entity.get("spawnflags", "0")) & 1:
            raise ValueError("START ambient catalog requires stock crucified zombies")
        source = {**entity, "origin": tuple(map(float, entity["origin"].split()))}
        oracle.add(number, source)
        oracle.event(number, "monster_zombie")
        origin = oracle.get(number, "origin")
        pitch, yaw, roll = oracle.get(number, "angles")
        frame = oracle.get(number, "frame")
        if oracle.get(number, "model") != MODEL or frame != POSE or pitch or roll:
            raise ValueError("stock START zombie visual identity changed")
        eye_origin = (*spatial.world_origin[:2], spatial.world_origin[2] - 22)
        result.append(dict(entityNumber=number, model=MODEL, frame=POSE,
                           origin=list(origin), yaw=round(yaw / 360 * 256) & 255,
                           originQ3=[round((value - base) * 8) for value, base in zip(origin, eye_origin)],
                           renderOriginQ2=list(billboard._origin_q2(origin, spatial.world_origin))))
    if len(result) != 9:
        raise ValueError("original START ambient zombie roster changed")
    return result


def key_actor(key, models):
    origin = tuple(key["origin"])
    world_origin = tuple((models[0][axis] + models[0][axis + 3]) * 0.5 for axis in range(3))
    eye_origin = (*world_origin[:2], world_origin[2] - 22)
    return dict(entityNumber=key["entityNumber"], model=key["model"], frame=0, origin=list(origin), yaw=0,
                originQ3=[round((value - base) * 8) for value, base in zip(origin, eye_origin, strict=True)],
                renderOriginQ2=list(billboard._origin_q2(origin, world_origin)))


def ambient_alias_outputs(archive, bsp, config, camera_hash, actors):
    (model_name, frame), = {(actor["model"], actor["frame"]) for actor in actors}
    spatial = billboard._parse_spatial_bsp(bsp)
    states, leaves = [], defaultdict(list)
    for index, actor in enumerate(actors):
        origin = tuple(actor["origin"])
        leaf = billboard._locate_leaf(origin, spatial)
        if spatial.leaves[leaf].contents == -2:
            raise ValueError("fixed-pose actor origin lies in a solid render leaf")
        yaw = actor["yaw"] * tau / 256
        states.append(billboard.AliasState(actor["entityNumber"], 0, 0,
                      tuple(actor["renderOriginQ2"]), origin, leaf,
                      directional_base_sprite=0, yaw_sin_q6=round(sin(yaw) * 64),
                      yaw_cos_q6=round(cos(yaw) * 64)))
        leaves[leaf].append(index)
    groups = tuple(billboard.AliasGroup(leaf, spatial.leaf_parents[leaf], tuple(tokens))
                   for leaf, tokens in sorted(leaves.items()))
    rows = (billboard.AliasRow(tuple(states), groups),) * 8
    model_payload = archive.read(model_name)
    model = parse_mdl(model_payload)
    density = configured_alias_mdl_world_units_per_texel(config)
    context = MdlBakeContext.from_palette(archive.read("gfx/palette.lmp"))
    masters = retain_complete_bakes({model_name: model}, context, density=density)
    views = tuple((frame, view) for view in range(8))
    sprites = rasterize_model_variants((model, 0, density, views, context))
    if tuple((sprite.frame, sprite.view) for sprite in sprites) != views:
        raise ValueError("fixed-pose sprites do not cover one complete eight-view pose")
    limit = configured_alias_halfbank_count(config)
    halfbanks = asset_layout(playback=False).alias_halfbanks
    st, pixels = billboard._pack_sprites_exact(rows, (), sprites, max_chunks=limit,
                   rotation_payload=ROTATION_BASES_BYTES, physical_halfbanks=halfbanks)
    chunks = st.packer.chunks
    count = len(chunks)
    rowdir = st.packer.location(0, alias.HEADER.size)
    directory = st.sprite_directory_location
    chunks[0][:alias.HEADER.size] = alias.HEADER.pack(
        alias.MAGIC, alias.VERSION, alias.HEADER.size, len(rows), len(sprites), 0,
        len(states), len(states), count, rowdir.offset, directory.flat_offset,
        st.static_location.flat_offset, 0, camera_hash)
    chunks[0][rowdir.offset:st.row_directory_end] = b"".join(st.row_records)
    records = bytearray()
    for sprite in sprites:
        location = pixels[sprite.storage_raster]
        records += alias.SPRITE_DIRECTORY.pack(location.bank, sprite.model, location.address,
                    sprite.width, sprite.height, sprite.projected_width, sprite.projected_height,
                    sprite.frame, sprite.view, sprite.left, sprite.top)
    chunks[directory.chunk][directory.offset:directory.offset + len(records)] = records
    target = configured_mesen_target(config)
    include = alias.render_include(row_count=len(rows), sprite_count=len(sprites), static_count=0,
        chunk_count=count, row_directory=rowdir, sprite_directory=directory, static_states=st.static_location,
        fly_facing=st.fly_facing_location, fly_facing_count=len(states), max_dynamic=len(states),
        max_visible=len(states), max_groups=len(groups), fly_row=0, fly_row_count=8, mesen_target=target,
        rotation=st.rotation_location, physical_halfbanks=halfbanks)
    outputs = {Path(f"QuakeBSPAliasRuntime{i}.bin"): bytes(chunk) for i, chunk in enumerate(chunks)}
    metadata = dict(schema="quake-level-alias-assets-v1", version=alias.VERSION, mode="static-level-ambient",
        source=dict(cameraTrackFnv1a64=f"{camera_hash:016x}", modelSha256=sha256(model_payload).hexdigest()),
        instrumentation=dict(modelNames=[model_name]), staticStateCount=0, mdlMasters=masters,
        rasterDensity=dict(mdlWorldUnitsPerTexel=density),
        rasterStorage=dict(variantCount=len(sprites), uniqueRasterCount=len(pixels),
            logicalPixelBytes=sum(len(sprite.storage_raster) for sprite in sprites),
            uniquePixelBytes=sum(len(raster) for raster in pixels),
            policy=("exact-width-height-pixels; all nine actors share one frame/view catalog"
                    if model_name == MODEL else "exact-width-height-pixels; one fixed frame/view catalog")),
        sprites=[dict(id=i, frame=sprite.frame, sourceView=sprite.view,
                      opaqueTexels=sum(bool(pixel & 0xff00) for pixel in sprite.pixels))
                 for i, sprite in enumerate(sprites)],
        format=dict(mesenTarget=target.name, configuredHalfbankCount=limit, maxGsuRomBank=target.max_gsu_rom_bank,
            actualMaxGsuRomBank=max(st.packer.location(i, 32767).bank for i in range(count)),
            chunkCount=count, chunkBytes=32768, storagePhysicalHalfbanks=halfbanks[:limit],
            spriteDirectoryRecordCount=len(sprites), flyFacingCapacity=128, flyFacingRecordCount=len(states),
            flyFacingPackageOffset=st.fly_facing_location.flat_offset, flyFacingBank=st.fly_facing_location.bank,
            flyFacingAddress=st.fly_facing_location.address),
        outputs={path.name: dict(bytes=len(blob), sha256=sha256(blob).hexdigest()) for path, blob in outputs.items()})
    outputs.update({Path("QuakeBSPAliasAssets.i"): include,
                    Path("QuakeBSPAliasAssets.s"): alias.render_assembly(count, physical_halfbanks=halfbanks),
                    Path("QuakeBSPGruntFrames.bin"): bytes(len(model.frames) if model_name == MODEL else 90)})
    return outputs, metadata
