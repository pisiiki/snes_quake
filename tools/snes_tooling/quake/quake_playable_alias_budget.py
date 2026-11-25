"""Trim sprite-control chunks and compact empty or fixed-ambient QBA images."""
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path

from snes_tooling.quake.quake_alias_animation import ROTATION_BASES_BYTES
from snes_tooling.quake import quake_alias_format as alias

NAME = "QuakeBSPAliasRuntime0.bin"
GUARD = 32


def split_live_sprite_tail(directory, spans, module):
    """Keep QBA control and early pixels resident, and stream the exact suffix."""
    from snes_tooling.quake.quake_alias_packing import gsu_location
    from snes_tooling.quake.quake_playable_link import integer_definitions
    from snes_tooling.quake.quake_playable_sprite_stream import CACHE_BYTES

    directory = Path(directory)
    metadata = json.loads((directory / "QuakeBSPAliasAssets.json").read_bytes())
    fields = integer_definitions((directory / "QuakeBSPAliasAssets.i").read_text())
    span = next(span for span in spans if span.key == (module, "BSP_ALIAS_0"))
    payload = span.payload
    expected = metadata["outputs"][NAME]
    if len(payload) != 32768 or sha256(payload).hexdigest() != expected["sha256"]:
        raise ValueError("live alias source does not match its complete bank")
    header = alias.HEADER.unpack_from(payload)
    if header[:3] != (alias.MAGIC, alias.VERSION, alias.HEADER.size) or header[5]:
        raise ValueError("live alias tail requires v6 control without static states")
    bank, base = gsu_location(0, physical_halfbanks=tuple(metadata["format"]["storagePhysicalHalfbanks"]))
    control_end = max(header[9] + header[3] * alias.ROW_DIRECTORY.size,
                      header[10] + header[4] * alias.SPRITE_DIRECTORY.size,
                      fields["BSP_ALIAS_FLY_FACING_ADDRESS"] - base + 128 * alias.FLY_FACING_RECORD.size,
                      fields["BSP_ALIAS_ROTATION_PHASES_CPU_ADDRESS"] - (bank << 16) - base + 256 * 4)
    for index in range(header[3]):
        row = alias.ROW_DIRECTORY.unpack_from(payload, header[9] + index * alias.ROW_DIRECTORY.size)
        if row[1]:
            if row[0] != bank or row[2] < base:
                raise ValueError("live alias states leave resident control")
            control_end = max(control_end, row[2] - base + row[1] * alias.STATE_RECORD.size)
        if row[4]:
            if row[3] != bank or row[5] < base:
                raise ValueError("live alias groups leave resident control")
            cursor = row[5] - base
            for _ in range(row[4]):
                _, _, count = alias.GROUP_HEADER.unpack_from(payload, cursor)
                cursor += alias.GROUP_HEADER.size + count
            control_end = max(control_end, cursor)
    rasters = set()
    for index in range(header[4]):
        row = alias.SPRITE_DIRECTORY.unpack_from(payload, header[10] + index * alias.SPRITE_DIRECTORY.size)
        if row[0] == bank and base <= row[2] < base + len(payload):
            start = row[2] - base
            size = row[3] * row[4]
            if not size or start + size > len(payload):
                raise ValueError("live alias pixels escape their source bank")
            rasters.add((start, size))
    split = next((cut for cut, _ in sorted(rasters) if cut >= control_end + GUARD
                  and all(start + size <= cut if start < cut else size <= CACHE_BYTES
                          for start, size in rasters)), None)
    if split is None:
        raise ValueError("live alias has no safe sprite-tail boundary")
    return [replace(item, payload=payload[:split]) if item.key == span.key else item for item in spans], payload[split:]


def start_ambient_alias_prefix(directory, metadata=None):
    """Prove fixed-pose gameplay QBA control and pixel extents without opening the PAK."""
    directory = Path(directory)
    metadata = metadata or json.loads((directory / "QuakeBSPAliasAssets.json").read_bytes())
    if metadata.get("mode") != "static-level-ambient":
        return None
    from snes_tooling.quake.quake_playable_link import integer_definitions
    from snes_tooling.quake.quake_alias_animation import ROTATION_BASES
    from snes_tooling.quake.quake_alias_packing import gsu_location, cpu_load_address
    world = json.loads((directory / "QuakeBSPMetadata.json").read_bytes())
    gameplay = json.loads((directory / "QuakeBSPQuakeCGameplay.json").read_bytes())
    target = world.get("target", {})
    route_keys = {"maps/e1m2.bsp": ("E1M2", "silverKey", "progs/w_s_key.mdl", 115),
                  "maps/e1m3.bsp": ("E1M3", "goldKey", "progs/w_g_key.mdl", 218)}
    route_key = route_keys.get(target.get("map")) if target.get("gameplay") == "basic" else None
    map_name = route_key[0] if route_key else "START"
    actor_count, model, frame = (1, route_key[2], 0) if route_key else (9, "progs/zombie.mdl", 192)

    def need(value, message):
        if not value:
            raise ValueError(f"{map_name} alias prefix: " + message)

    need(route_key or (target.get("map") == "maps/start.bsp" and target.get("gameplay") == "start-hub"),
         "unsupported fixed-pose gameplay map")
    actors = gameplay.get("staticAmbientMdls", [])
    need(len(actors) == actor_count and not gameplay.get("stockGrunts")
         and len({actor["entityNumber"] for actor in actors}) == actor_count,
         "the authored static roster changed")
    if route_key:
        key = gameplay["stockExitMachinery"][route_key[1]]
        need(actors[0]["entityNumber"] == key["entityNumber"] == route_key[3]
             and actors[0]["origin"] == key["origin"] and key["model"] == model,
             "key render identity differs from the pickup")
    need(all(actor["model"] == model and actor["frame"] == frame
             and type(actor["yaw"]) is int and 0 <= actor["yaw"] <= 255 for actor in actors),
         "authored ambient model/frame/facing changed")
    payload = (directory / NAME).read_bytes()
    expected = metadata["outputs"][NAME]
    need(len(payload) == expected["bytes"] == 32768
         and sha256(payload).hexdigest() == expected["sha256"], "source size/SHA differs")
    fmt = metadata["format"]
    need(metadata.get("schema") == "quake-level-alias-assets-v1"
         and metadata.get("version") == alias.VERSION and metadata.get("staticStateCount") == 0
         and fmt["chunkCount"] == 1 and fmt["chunkBytes"] == 32768
         and fmt["flyFacingCapacity"] == 128 and fmt["flyFacingRecordCount"] == actor_count,
         "one-bank QBA v6 control contract changed")
    fields = integer_definitions((directory / "QuakeBSPAliasAssets.i").read_text(encoding="utf-8"))
    required = dict(BSP_ALIAS_ASSET_VERSION=6, BSP_ALIAS_ROW_COUNT=8, BSP_ALIAS_FLY_ROW=0,
                    BSP_ALIAS_FLY_ROW_COUNT=8, BSP_ALIAS_VIEW_COUNT=8, BSP_ALIAS_SPRITE_COUNT=8,
                    BSP_ALIAS_STATIC_STATE_COUNT=0, BSP_ALIAS_CHUNK_COUNT=1,
                    BSP_ALIAS_MAX_DYNAMIC_STATES=actor_count, BSP_ALIAS_MAX_VISIBLE_STATES=actor_count,
                    BSP_ALIAS_FLY_FACING_COUNT=actor_count, BSP_ALIAS_ENTITY_SUPPORTED=1,
                    BSP_ALIAS_ROW_RECORD_BYTES=alias.ROW_DIRECTORY.size,
                    BSP_ALIAS_SPRITE_RECORD_BYTES=alias.SPRITE_DIRECTORY.size,
                    BSP_ALIAS_STATE_RECORD_BYTES=alias.STATE_RECORD.size,
                    BSP_ALIAS_FLY_FACING_RECORD_BYTES=alias.FLY_FACING_RECORD.size,
                    BSP_ALIAS_GROUP_HEADER_BYTES=alias.GROUP_HEADER.size,
                    BSP_ALIAS_FLY_DIRECTIONAL_TAG=alias.FLY_DIRECTIONAL_TAG,
                    BSP_ALIAS_FLY_DIRECTIONAL_MASK=alias.FLY_DIRECTIONAL_MASK,
                    BSP_ALIAS_TOKEN_STATIC=128)
    need(all(fields.get(key) == value for key, value in required.items()), "generated include disagrees")
    header = alias.HEADER.unpack_from(payload)
    need(header[:9] == (alias.MAGIC, alias.VERSION, alias.HEADER.size, 8, 8, 0, actor_count, actor_count, 1)
         and header[9] == alias.HEADER.size and header[12] == 0
         and header[13] == int(metadata["source"]["cameraTrackFnv1a64"], 16), "header disagrees")
    physical = tuple(fmt["storagePhysicalHalfbanks"])
    bank, base = gsu_location(0, physical_halfbanks=physical)
    extents = [(0, alias.HEADER.size)]
    def extent(offset, size):
        need(type(offset) is int and type(size) is int and 0 <= offset <= 32768
             and 0 <= size <= 32768 - offset, "declared extent escapes bank0")
        extents.append((offset, offset + size))
        return offset
    def pointer(pointer_bank, address, size):
        need(pointer_bank == bank and base <= address, "pointer leaves the sole source bank")
        return extent(address - base, size)
    def declared(stem, size):
        return pointer(fields[stem + "_BANK"], fields[stem + "_ADDRESS"], size)
    rowdir = declared("BSP_ALIAS_ROW_DIRECTORY", 8 * alias.ROW_DIRECTORY.size)
    spritedir = declared("BSP_ALIAS_SPRITE_DIRECTORY", 8 * alias.SPRITE_DIRECTORY.size)
    static = declared("BSP_ALIAS_STATIC_STATES", 0)
    need((rowdir, spritedir, static) == header[9:12], "header/directory locations disagree")
    expected_states = tuple((alias.FLY_DIRECTIONAL_TAG, *actor["renderOriginQ2"]) for actor in actors)
    for index in range(8):
        state_bank, count, state_address, group_bank, groups, group_address = alias.ROW_DIRECTORY.unpack_from(payload, rowdir + index * alias.ROW_DIRECTORY.size)
        need(count == actor_count and groups == fields["BSP_ALIAS_MAX_GROUPS"] and groups > 0, "row counts disagree")
        states = pointer(state_bank, state_address, count * alias.STATE_RECORD.size)
        actual = tuple(alias.STATE_RECORD.unpack_from(payload, states + item * alias.STATE_RECORD.size) for item in range(count))
        need(actual == expected_states, "state words disagree with the scripted roster")
        cursor = pointer(group_bank, group_address, 0)
        covered, leaves = [], []
        for _ in range(groups):
            extent(cursor, alias.GROUP_HEADER.size)
            leaf, _parent, tokens = alias.GROUP_HEADER.unpack_from(payload, cursor)
            cursor += alias.GROUP_HEADER.size
            need(tokens > 0, "empty leaf group")
            extent(cursor, tokens)
            covered.extend(payload[cursor:cursor + tokens]);leaves.append(leaf);cursor += tokens
        need(sorted(covered) == list(range(actor_count)) and len(set(leaves)) == groups,
             "leaf groups do not cover each scripted actor exactly once")
    facing = declared("BSP_ALIAS_FLY_FACING", 128 * alias.FLY_FACING_RECORD.size)
    need(facing == fmt["flyFacingPackageOffset"] and fields["BSP_ALIAS_FLY_FACING_BANK"] == fmt["flyFacingBank"]
         and fields["BSP_ALIAS_FLY_FACING_ADDRESS"] == fmt["flyFacingAddress"], "facing include/metadata disagree")
    for index, actor in enumerate(actors):
        need(alias.FLY_FACING_RECORD.unpack_from(payload, facing + index * alias.FLY_FACING_RECORD.size)
             == ROTATION_BASES[actor["yaw"]], "facing basis differs from authored yaw")
    need(payload[facing + actor_count * alias.FLY_FACING_RECORD.size:facing + 128 * alias.FLY_FACING_RECORD.size]
         == bytes((128 - actor_count) * alias.FLY_FACING_RECORD.size), "reserved facing capacity changed")
    cpu_base = cpu_load_address(0, physical_halfbanks=physical)
    rotation = extent(fields["BSP_ALIAS_ROTATION_BASES_CPU_ADDRESS"] - cpu_base, len(ROTATION_BASES_BYTES))
    need(payload[rotation:rotation + len(ROTATION_BASES_BYTES)] == ROTATION_BASES_BYTES, "rotation basis changed")
    need(fields["BSP_ALIAS_ROTATION_PHASES_CPU_ADDRESS"] == fields["BSP_ALIAS_ROTATION_BASES_CPU_ADDRESS"] + len(ROTATION_BASES_BYTES),
         "rotation phase address changed")
    # Keep the complete addressable phase window, even though START's fly-row0
    # does not consume sampled demo phases. It lies below the final sprite end.
    extent(fields["BSP_ALIAS_ROTATION_PHASES_CPU_ADDRESS"] - cpu_base, 256 * 4)
    sprites = metadata["sprites"]
    need(len(sprites) == fmt["spriteDirectoryRecordCount"] == 8
         and metadata["instrumentation"]["modelNames"] == [model], "eight-view catalog changed")
    pixel_extents = []
    for index in range(8):
        row = alias.SPRITE_DIRECTORY.unpack_from(payload, spritedir + index * alias.SPRITE_DIRECTORY.size)
        need(row[1] == 0 and row[3] > 0 and row[4] > 0 and row[7] == frame and row[8] == index
             and sprites[index]["id"] == index and sprites[index]["frame"] == frame
             and sprites[index]["sourceView"] == index, "sprite frame/view/dimensions changed")
        offset = pointer(row[0], row[2], row[3] * row[4])
        pixels = payload[offset:offset + row[3] * row[4]]
        need(sum(bool(value) for value in pixels) == sprites[index]["opaqueTexels"], "sprite opaque extent disagrees")
        pixel_extents.append(dict(sprite=index, offset=offset, bytes=len(pixels)))
    end = max(stop for _, stop in extents)
    retained = (end + GUARD + 15) & -16
    need(retained <= 32768 and payload[end:] == b"\xff" * (32768 - end), "retired suffix/guard is not entirely FF")
    return dict(schema=f"quake-{map_name.lower()}-ambient-alias-prefix-v1", retainedBytes=retained,
                semanticBytes=end, guardBytes=retained - end, savedBytes=32768 - retained,
                originalBytes=32768, sourceSha256=expected["sha256"], pixelExtents=pixel_extents,
                rowsValidated=8, actorsValidated=actor_count, viewsValidated=8,
                includeSha256=sha256((directory / "QuakeBSPAliasAssets.i").read_bytes()).hexdigest(),
                gameplaySha256=sha256((directory / "QuakeBSPQuakeCGameplay.json").read_bytes()).hexdigest())


def empty_alias_prefix(directory):
    directory = Path(directory)
    metadata = json.loads((directory / "QuakeBSPAliasAssets.json").read_bytes())
    if metadata.get("mode") == "static-level-ambient":
        return start_ambient_alias_prefix(directory, metadata)
    if metadata.get("mode") != "static-level-empty-aliases":
        return None
    if (metadata.get("sprites") != [] or metadata.get("staticStateCount") != 0
            or metadata["format"]["chunkCount"] != 1
            or metadata["format"]["flyFacingCapacity"] != 128):
        raise ValueError("empty alias tail requires the canonical empty roster")
    from snes_tooling.quake.quake_level_assets import empty_alias_outputs
    from snes_tooling.quake.quake_playable_maps import config_for
    from snes_tooling import Workspace
    world = json.loads((directory / "QuakeBSPMetadata.json").read_bytes())
    name = Path(world["target"]["map"]).stem
    config = Workspace.discover().root / "config/snes_quake" / config_for(name)
    camera_hash = int(metadata["source"]["cameraTrackFnv1a64"], 16)
    canonical = empty_alias_outputs(config, camera_hash)[Path(NAME)]
    payload = (directory / NAME).read_bytes()
    expected = metadata["outputs"][NAME]
    if (payload != canonical or len(payload) != expected["bytes"]
            or sha256(payload).hexdigest() != expected["sha256"]):
        raise ValueError("empty alias control bytes differ from their exact producer")
    # Retain the header, eight empty rows, complete facing and basis tables,
    # and the full 256-entry CPU phase table address even though it is idle.
    end = (alias.HEADER.size + 8 * alias.ROW_DIRECTORY.size
           + 128 * alias.FLY_FACING_RECORD.size + len(ROTATION_BASES_BYTES)
           + 256 * 4)
    retained = (end + GUARD + 15) & -16
    if len(payload) != 32768 or payload[retained:] != b"\xff" * (32768 - retained):
        raise ValueError("empty alias retired suffix must be entirely FF")
    return dict(schema="quake-empty-alias-prefix-v1", retainedBytes=retained,
                semanticBytes=end, guardBytes=retained - end,
                savedBytes=32768 - retained, originalBytes=32768,
                sourceSha256=expected["sha256"])


def compact_empty_alias_spans(directory, spans, *, module):
    proof = empty_alias_prefix(directory)
    if proof is None:
        return list(spans), None
    matching = [span for span in spans if span.module == module and span.name == "BSP_ALIAS_0"]
    if len(matching) != 1 or matching[0].payload != (Path(directory) / NAME).read_bytes():
        raise ValueError("empty alias native span differs from the canonical source")
    old = matching[0]
    return [replace(span, payload=span.payload[:proof["retainedBytes"]])
            if span.key == old.key else span for span in spans], proof


def compact_empty_alias_files(example, layout, module, files):
    proof = empty_alias_prefix(Path(example) / "Data")
    tail = getattr(layout, "sprite_tails", {}).get(module)
    if proof is None and tail is None:
        return None
    size = proof["retainedBytes"] if proof is not None else 32768 - len(tail[1])
    if layout.placements[module, "BSP_ALIAS_0"].size != size:
        raise ValueError("empty alias prefix allocation differs from its proof")
    for folder in ("Data/",):
        relative = folder + NAME
        path = Path(example) / relative
        if not path.is_file():
            continue
        payload = files.get(relative, path.read_bytes())
        suffix = b"\xff" * (32768 - size) if tail is None else tail[1]
        if len(payload) != 32768 or payload[size:] != suffix:
            raise ValueError("relocated alias suffix differs from the proven source bytes")
        files[relative] = payload[:size]
        assembly = folder + "QuakeBSPAliasAssets.s"
        text = files.get(assembly, (Path(example) / assembly).read_bytes()).decode("utf-8")
        old = "QuakeBSPAliasRuntime0End - QuakeBSPAliasRuntime0 = $8000"
        if text.count(old) != 1:
            raise ValueError("expected one exact empty alias assembly size contract")
        files[assembly] = text.replace(old, f"QuakeBSPAliasRuntime0End - QuakeBSPAliasRuntime0 = ${size:X}").encode("utf-8")
    return proof


def restore_empty_alias_extent(directory, chunks):
    if len(chunks) == 1 and len(chunks[0]) == 32768:
        return chunks  # Historical packages retain the complete source bank.
    proof = empty_alias_prefix(directory)
    if proof is None:
        return chunks
    if len(chunks) != 1 or len(chunks[0]) != proof["retainedBytes"]:
        raise ValueError("empty alias recovery extent differs from its source proof")
    return [chunks[0] + b"\xff" * (proof["originalBytes"] - len(chunks[0]))]
