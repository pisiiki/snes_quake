"""Recover canonical packed world and QBSA/QBSF files from a playable package."""

from __future__ import annotations

from hashlib import sha256
import json
import re

from snes_tooling.quake import quake_playable_relocation as relocation
from snes_tooling.quake.quake_bsp_assets import WORLD_PVS_FIRST_GSU_ROM_BANK
from snes_tooling.quake.quake_playable_layout import gsu_address
from snes_tooling.quake.quake_playable_materials import (
    PVS, pooled, original_offset, source_pixel_ranges, recover_pixel_file, restore_texture_directory,
)
from snes_tooling.quake.quake_playable_raw_contours import (
    RAW_CONTOUR_DIRECTORY, RAW_CONTOUR_SHARD, verify_raw_contours,
)
from snes_tooling.quake.quake_playable_world_lightmap import (
    RESIDENT_GRIDS, RESIDENT_ORIGINALS, restore_resident_lightmaps,
)
from snes_tooling.quake.quake_playable_world_coordinates import (
    AFFINE_DESCRIPTOR_COUNT_MASK, AFFINE_DESCRIPTOR_SEGMENT, AFFINE_MODE_MASK,
    AFFINE_VARIANT_MASK, WORLD_FACES_FILE, build_world_affine_uv_records, restore_world_face_modes,
)


BRUSH_FAMILIES = (
    "QuakeBSPBrushRuntime",
    "QuakeBSPBrushFragments",
    "QuakeBSPBrushTexturePixels",
)
SYMBOL_SEGMENTS = {
    "QuakeBSPReciprocal.bin": "BSPDATA",
    "QuakeBSPTurbulenceTable.bin": "BSP_DEMO_TIMING",
    "QuakeBSPWorldFaceTextureIds.bin": "BSP_WORLD_TEXTURE_AUX",
    "QuakeBSPWorldTextureDirectory.bin": "BSP_WORLD_TEXTURE_AUX",
    "QuakeBSPWorldPVSDirectory.bin": "BSP_WORLD_PVS_DIRECTORY",
    "QuakeBSPWorldPVSGuards.bin": "BSP_WORLD_PVS_DIRECTORY",
}


def identity(payload):
    return dict(bytes=len(payload), sha256=sha256(payload).hexdigest())


def require_identity(payload, expected, name):
    if identity(payload) != {key: expected[key] for key in ("bytes", "sha256")}:
        raise ValueError("production packed file size/SHA-256 mismatch: " + name)


def packed_file_names(world, brush):
    names = {
        name
        for name in world["outputs"]
        if name.endswith(".bin")
        and (
            name.startswith("QuakeBSPWorld")
            or name in ("QuakeBSPReciprocal.bin", "QuakeBSPTurbulenceTable.bin")
        )
    }
    names.update(
        name
        for name in brush["outputs"]
        if name.endswith(".bin") and name.startswith(BRUSH_FAMILIES)
    )
    names.update(("QuakeBSPReciprocal.bin", "QuakeBSPTurbulenceTable.bin"))
    return sorted(names)


def inverse_mapper(world, brush, segments):
    """Map actual separate allocations back to metadata's canonical file banks."""
    mapping = []

    def add(segment, bank, address=0x8000):
        if segment in segments:
            row = segments[segment]
            if row.get("storage") == "msu":
                return  # Archived original bytes contain canonical pointers.
            mapping.append(
                (row["gsuBank"], row["gsuAddress"], row["bytes"], bank, address)
            )

    exact = world["world"]["packing"]["exact_textures"]
    for family, prefix in (
        ("coordinate_chunks", "BSP_WORLD_TEXCOORD_"),
        ("pixel_chunks", "BSP_WORLD_TEXTURE_"),
    ):
        if family == "pixel_chunks" and pooled(segments):
            continue
        for index, item in enumerate(exact[family]):
            add(
                prefix + str(index),
                item["gsu_rom_bank"],
                item.get("gsu_rom_address", 0x8000),
            )
    for index, item in enumerate(exact["lightmaps"]["sample_chunks"]):
        add(
            "BSP_WORLD_LIGHTMAP_" + str(index),
            item["gsu_rom_bank"],
            item.get("gsu_rom_address", 0x8000),
        )
    for index, _ in enumerate(world["world"]["packing"]["face_pvs"]["chunks"]):
        add("BSP_WORLD_PVS_" + str(index), WORLD_PVS_FIRST_GSU_ROM_BANK + index)
    families = (
        ("BSP_BRUSH_TEXTURE_", brush["capacity"]["firstBrushBank"]),
        ("BSP_BRUSH_RUNTIME_", brush["runtime"]["firstBank"]),
        ("BSP_BRUSH_FRAGMENTS_", brush["worldComposition"]["fragments"]["firstBank"]),
    )
    for prefix, bank in families:
        for segment in segments:
            if match := re.fullmatch(re.escape(prefix) + r"(\d+)", segment):
                add(segment, bank + int(match[1]))

    for name in segments:
        if name.startswith(PVS):
            add(name, *gsu_address(original_offset(name)))

    def inverse(bank, address):
        candidates = [
            (old_bank, old_base + address - base)
            for actual_bank, base, size, old_bank, old_base in mapping
            if actual_bank == bank and base <= address < base + size
        ]
        if len(candidates) != 1:
            raise ValueError(
                f"production pointer {bank:02X}:{address:04X} has no unique canonical allocation"
            )
        return candidates[0]

    return inverse


def segment_name(filename):
    exact = {
        "FaceOwners": "FACE_OWNERS", "FacePlanes": "FACE_PLANES", "Faces": "FACES",
        "Leaves": "LEAVES", "Marksurfaces": "MARKSURFACES", "NodeParents": "NODE_PARENTS",
        "Nodes": "NODES", "Planes": "PLANES", "Shading": "SHADING", "Vertices": "VERTICES",
    }
    if filename.startswith("QuakeBSPWorld") and filename[13:-4] in exact:
        return "BSP_WORLD_" + exact[filename[13:-4]]
    families = (
        ("QuakeBSPBrushRuntime", "BSP_BRUSH_RUNTIME_"),
        ("QuakeBSPBrushFragments", "BSP_BRUSH_FRAGMENTS_"),
        ("QuakeBSPBrushTexturePixels", "BSP_BRUSH_TEXTURE_"),
        ("QuakeBSPWorldTexturePixels", "BSP_WORLD_TEXTURE_"),
        ("QuakeBSPWorldTextureCoordinates", "BSP_WORLD_TEXCOORD_"),
        ("QuakeBSPWorldLightmapSamples", "BSP_WORLD_LIGHTMAP_"),
        ("QuakeBSPWorldPVS", "BSP_WORLD_PVS_"),
        ("QuakeBSPWorldIndices", "BSP_WORLD_INDICES_"),
        ("QuakeBSPWorldVisibility", "BSP_WORLD_VISIBILITY_"),
    )
    for stem, prefix in families:
        if match := re.fullmatch(re.escape(stem) + r"(\d+)\.bin", filename):
            return prefix + match[1]
    return None


def recover_file(filename, expected, segments, labels, read_segment, *, source_first=None):
    size = expected["bytes"]
    if not size:
        return b""
    if source_first is not None and pooled(segments):
        return recover_pixel_file(size, source_first, segments, read_segment)
    if filename == "QuakeBSPWorldLightmapDirectory.bin":
        return b"".join(
            read_segment(segments[name])
            for name in (
                "BSP_WORLD_LIGHTMAP_DIRECTORY",
                "BSP_WORLD_LIGHTMAP_DIRECTORY_TAIL",
            )
            if name in segments
        )
    segment = segment_name(filename)
    if segment in segments:
        payload = read_segment(segments[segment])
        if filename == "QuakeBSPWorldFaceOwners.bin" and len(payload) < size:
            _, header = relocation.face_owner_format(payload)
            if (len(payload) - header) * 2 != size:
                raise ValueError("production face-owner delta count disagrees with the BSP")
            return relocation.restore_face_owners(payload)
        if (
            filename.startswith(
                ("QuakeBSPBrushTexturePixels", "QuakeBSPWorldTexturePixels",
                 "QuakeBSPBrushRuntime", "QuakeBSPBrushFragments")
            )
            and len(payload) < size
        ):
            # Only admitted FF tails may be omitted by the linker. The final
            # post-inverse size/SHA check in recover_packed_files proves every
            # restored byte against both original metadata and sourceAssets.
            return payload + b"\xff" * (size - len(payload))
        return payload
    if (address := labels.get(filename[:-4].lower())) is not None:
        # Virtual MSU load addresses can overlap the GSU ROM address space.
        named = segments.get(SYMBOL_SEGMENTS.get(filename))
        candidates = (named,) if named is not None else segments.values()
        containers = [
            row
            for row in candidates
            if row["linkerAddress"] <= address
            and address + size <= row["linkerAddress"] + row["bytes"]
        ]
        if len(containers) != 1:
            raise ValueError(
                "production packed symbol lacks one complete segment: " + filename
            )
        row = containers[0]
        offset = address - row["linkerAddress"]
        return read_segment(row)[offset : offset + size]
    if filename.startswith("QuakeBSPWorldTexturePixels"):
        padding = bytes([255]) * size
        if identity(padding)["sha256"] == expected["sha256"]:
            return padding
    raise ValueError(
        "production packed file has no symbol/segment or exact padding proof: "
        + filename
    )


def restore_brush_files(raw, brush, inverse, *, segments=None):
    runtime = brush["runtime"]
    for section in runtime["sections"]:
        if section["name"] not in ("TEXDIR", "LIGHTDIR"):
            continue
        filename = f"QuakeBSPBrushRuntime{section['bank'] - runtime['firstBank']}.bin"
        payload = bytearray(raw[filename])
        offset, size = section["address"] - 0x8000, section["bytes"]
        transform = (
            relocation.relocate_textures
            if section["name"] == "TEXDIR"
            else relocation.relocate_lightmaps
        )
        if section["name"] == "TEXDIR" and segments is not None and pooled(segments):
            originals = [(row["bank"], row["address"]) for row in brush["textures"]["textures"]]
            restored = restore_texture_directory(payload[offset : offset + size], originals, segments)
        else:
            restored = transform(payload[offset : offset + size], inverse)
        payload[offset : offset + size] = restored
        raw[filename] = bytes(payload)
    filename = "QuakeBSPBrushRuntime0.bin"
    payload = bytearray(raw[filename])
    for index in range(relocation.BRUSH_HEADER.unpack_from(payload)[-2]):
        offset = relocation.BRUSH_HEADER.size + index * relocation.BRUSH_SECTION.size
        row = list(relocation.BRUSH_SECTION.unpack_from(payload, offset))
        row[1], row[2] = inverse(row[1], row[2])
        relocation.BRUSH_SECTION.pack_into(payload, offset, *row)
    raw[filename] = bytes(payload)
    pvs = brush["worldComposition"]["leafPvs"]
    bank, runtime_first = pvs["directoryBank"], brush["runtime"]["firstBank"]
    if bank >= runtime_first:
        filename = f"QuakeBSPBrushRuntime{bank - runtime_first}.bin"
    else:
        filename = f"QuakeBSPBrushTexturePixels{bank - brush['capacity']['firstBrushBank']}.bin"
    payload = bytearray(raw[filename])
    offset, size = pvs["directoryAddress"] - 0x8000, pvs["directoryBytes"]
    payload[offset : offset + size] = relocation.relocate_brush_pvs(
        payload[offset : offset + size], inverse
    )
    raw[filename] = bytes(payload)


def verify_linked_affine_descriptors(canonical, linked_faces, descriptor_payload, *,
                                     segments=None, read_segment=None):
    plan = build_world_affine_uv_records(canonical, extra_modes=True, descriptor_modes=True)
    if not plan.descriptor_bytes:
        raise ValueError("world affine descriptor encoding has no canonical descriptors")
    faces = (verify_raw_contours(plan, canonical, segments, read_segment)
             if segments and RAW_CONTOUR_DIRECTORY in segments else plan.faces)
    expected_faces = relocation.inline_axial_face_flags(
        faces, canonical[relocation.WORLD_FACE_PLANES_FILE],
        mode_mask=plan.mode_mask, count_mask=plan.count_mask)
    require_identity(linked_faces, identity(expected_faces), "linked affine face records")
    require_identity(descriptor_payload, identity(plan.descriptor_bytes), "linked affine descriptor table")


def recover_packed_files(directory, segments, labels, read_segment, expected, *, palette_inverse=None):
    """Return exact original file bytes, or fail before publishing any bundle."""
    metadata, outputs = {}, {}
    for filename in ("QuakeBSPMetadata.json", "QuakeBSPBrushAssets.json"):
        if filename not in expected:
            raise ValueError(
                "playable report lacks packed-world sourceAssets; rebuild it or supply --input-closure"
            )
        payload = (directory / filename).read_bytes()
        require_identity(payload, expected[filename], filename)
        outputs[filename] = payload
        metadata[filename] = json.loads(payload)
    world, brush = (
        metadata["QuakeBSPMetadata.json"],
        metadata["QuakeBSPBrushAssets.json"],
    )
    if brush.get("schema") != "quake-bsp-brush-assets" or brush.get("version") != 2:
        raise ValueError("production brush recovery requires original QBSA v2 metadata")
    original_outputs = dict(world["outputs"], **brush["outputs"])
    labels = {
        (key.decode() if isinstance(key, bytes) else key).lower(): value
        for key, value in labels.items()
    }
    raw = {}
    pixel_ranges = source_pixel_ranges(world, brush) if pooled(segments) else {}

    def read_world_file(segment):
        payload = read_segment(segment)
        if palette_inverse is not None and segment.get("segment", "").startswith("BSP_SHARED_TEXEL_"):
            return payload.translate(palette_inverse)
        return payload

    for filename in packed_file_names(world, brush):
        if filename not in expected:
            raise ValueError(
                "playable report lacks a packed-world input identity: " + filename
            )
        if filename in original_outputs and any(
            expected[filename][key] != original_outputs[filename][key]
            for key in ("bytes", "sha256")
        ):
            raise ValueError(
                "production packed metadata and sourceAssets disagree: " + filename
            )
        raw[filename] = recover_file(
            filename, expected[filename], segments, labels, read_world_file,
            source_first=pixel_ranges.get(filename),
        )
    from snes_tooling.quake.quake_face_colors import FILE, brush_material_location, install_colors
    from snes_tooling.quake.quake_switchable_lights import (
        ALL_ON, COLOR_PAGE_SPLIT, COLOR_ROW_BYTES, FIVE_STYLE_SEGMENT, FOUR_STYLE_SEGMENT, MASK_COUNT,
        REFERENCE_COLORS, REPAIR_SEGMENT, STREAM_SEGMENT, restore_grid_pointers,
    )
    switched = b""
    modern_lights = STREAM_SEGMENT in segments or FIVE_STYLE_SEGMENT in segments
    if modern_lights or FOUR_STYLE_SEGMENT in segments:
        if STREAM_SEGMENT in segments:
            segment, extent = STREAM_SEGMENT, MASK_COUNT * COLOR_ROW_BYTES
        elif FIVE_STYLE_SEGMENT in segments:
            segment, extent = FIVE_STYLE_SEGMENT, 32 * COLOR_ROW_BYTES
        else:
            segment, extent = FOUR_STYLE_SEGMENT, 16 * 256
        switched = read_segment(segments[segment])[:extent]
        restore_grid_pointers(raw, brush, read_segment(segments[REPAIR_SEGMENT]))
    location, brush_count = brush_material_location(brush)
    brush_segment = f"BSP_BRUSH_FRAGMENTS_{location['bankIndex']}"
    face_segments = (
        ("BSP_WORLD_FACES", WORLD_FACES_FILE, 4, 6, len(raw[WORLD_FACES_FILE]) // 6),
        (brush_segment, f"QuakeBSPBrushFragments{location['bankIndex']}.bin", location['offset'] + 15, 16, brush_count),
    )
    if any('faceColors' in segments.get(name, {}) for name, *_ in face_segments):
        baked = bytearray()
        for name, filename, offset, stride, count in face_segments:
            row = segments[name]['faceColors']
            if (row['offset'], row['stride'], row['bytes']) != (offset, stride, count):
                raise ValueError('baked color metadata differs from its face table')
            colors = raw[filename][offset:offset + count * stride:stride]
            require_identity(colors, row, 'linked baked face colors')
            baked.extend(colors)
            legacy = read_segment(row['original'])
            require_identity(legacy, row['original'], 'archived legacy face bytes')
            raw[filename] = install_colors(raw[filename], legacy, offset, stride)
        if switched:
            tables = switched if palette_inverse is None else switched.translate(palette_inverse)
            outputs[REFERENCE_COLORS] = tables + bytes(baked)
            if modern_lights:
                row = switched[ALL_ON * COLOR_ROW_BYTES:(ALL_ON + 1) * COLOR_ROW_BYTES]
                baked = (bytes(baked[:COLOR_PAGE_SPLIT]).translate(row[:256]) +
                         bytes(baked[COLOR_PAGE_SPLIT:]).translate(row[256:]))
            else:
                baked = bytes(baked).translate(switched[-256:])
        outputs[FILE] = bytes(baked) if palette_inverse is None else bytes(baked).translate(palette_inverse)
    nodes, planes = relocation.WORLD_NODES_FILE, relocation.WORLD_PLANES_FILE
    if identity(raw[nodes]) != {key: expected[nodes][key] for key in ("bytes", "sha256")}:
        raw[nodes] = relocation.restore_axial_node_planes(raw[nodes], raw[planes])
    face_segment = segments.get("BSP_WORLD_FACES", {})
    mode_bits = face_segment.get("affineUvModeBits")
    if mode_bits is not None and mode_bits not in (AFFINE_MODE_MASK, AFFINE_VARIANT_MASK):
        raise ValueError("unsupported world face affine mode bits")
    descriptors = face_segment.get("affineUvDescriptors", False)
    descriptor_row = segments.get(AFFINE_DESCRIPTOR_SEGMENT)
    axial_bits = face_segment.get("axialCullModeBits")
    if (type(descriptors) is not bool or descriptors != (descriptor_row is not None)
            or (descriptors and (mode_bits != AFFINE_VARIANT_MASK
                                 or axial_bits != relocation.AXIAL_FACE_TAG_MASK
                                 or descriptor_row.get("storage") != "gsu"))):
        raise ValueError("unsupported world face affine descriptor encoding")
    raw_directory = RAW_CONTOUR_DIRECTORY in segments
    raw_shards = any(name.startswith(RAW_CONTOUR_SHARD) for name in segments)
    if raw_directory != raw_shards or (raw_directory and not descriptors):
        raise ValueError("unsupported world raw contour encoding")
    linked_faces = raw[WORLD_FACES_FILE]
    if axial_bits is not None:
        if axial_bits != relocation.AXIAL_FACE_TAG_MASK:
            raise ValueError("unsupported world face axial culling bits")
        raw[WORLD_FACES_FILE] = relocation.restore_axial_face_flags(
            raw[WORLD_FACES_FILE], raw[relocation.WORLD_FACE_PLANES_FILE],
            mode_mask=mode_bits or AFFINE_MODE_MASK,
            count_mask=0xFF ^ AFFINE_DESCRIPTOR_COUNT_MASK if descriptors else 0xFF)
    if mode_bits is not None:
        raw[WORLD_FACES_FILE] = restore_world_face_modes(
            raw[WORLD_FACES_FILE], mode_mask=mode_bits, descriptors=descriptors)
    inverse = inverse_mapper(world, brush, segments)
    lightmap_stores = {row.get("storage", "gsu") for name, row in segments.items()
                       if re.fullmatch(r"BSP_WORLD_LIGHTMAP_[0-4]", name)}
    if len(lightmap_stores) > 1:
        raise ValueError("mixed resident and streamed world lightmap samples")
    resident_rows = {name for name in (RESIDENT_GRIDS, RESIDENT_ORIGINALS) if name in segments}
    if resident_rows and (len(resident_rows) != 2 or lightmap_stores != {"msu"}):
        raise ValueError("Incomplete resident lightmap package")
    for filename, transform in (
        ("QuakeBSPWorldTextureDirectory.bin", relocation.relocate_textures),
        ("QuakeBSPWorldLightmapDirectory.bin", relocation.relocate_lightmaps),
        ("QuakeBSPWorldPVSDirectory.bin", relocation.relocate_world_pvs),
    ):
        if filename == "QuakeBSPWorldTextureDirectory.bin" and pooled(segments):
            originals = [(row["gsu_rom_bank"], row["gsu_rom_address"])
                         for row in world["world"]["packing"]["exact_textures"]["textures"]]
            raw[filename] = restore_texture_directory(raw[filename], originals, segments)
        elif filename == "QuakeBSPWorldPVSDirectory.bin" and segments.get(
                "BSP_WORLD_PVS_DIRECTORY", {}).get("storage") == "msu":
            continue
        elif filename == "QuakeBSPWorldLightmapDirectory.bin" and lightmap_stores == {"msu"}:
            if resident_rows:
                hot = segments[RESIDENT_GRIDS]
                if hot["storage"] != "gsu" or segments[RESIDENT_ORIGINALS]["storage"] != "msu":
                    raise ValueError("Resident lightmap package has incorrect storage")
                bank, address = gsu_address(hot["offset"])
                if (hot["gsuBank"], hot["gsuAddress"]) != (bank, address):
                    raise ValueError("Resident lightmap placement disagrees with the cartridge mapping")
                chunks = world["world"]["packing"]["exact_textures"]["lightmaps"]["sample_chunks"]
                canonical = {row["gsu_rom_bank"]: raw[row["file"]] for row in chunks}
                raw[filename] = restore_resident_lightmaps(
                    raw[filename], read_segment(segments[RESIDENT_ORIGINALS]),
                    bank, address, read_segment(hot), canonical)
            continue
        else:
            raw[filename] = transform(raw[filename], inverse)
    restore_brush_files(raw, brush, inverse, segments=segments)
    for filename, payload in raw.items():
        require_identity(payload, expected[filename], filename)
    if descriptors:
        verify_linked_affine_descriptors(
            raw, linked_faces, read_segment(descriptor_row),
            segments=segments, read_segment=read_segment)
    outputs.update(raw)
    receipt = dict(
        schema="quake-gameplay-production-world-v1",
        worldRenderer="packed-gsu-q4-projective-block8-lightmap-v1",
        files=sorted(outputs),
        worldMetadata=identity(outputs["QuakeBSPMetadata.json"]),
        brushMetadata=identity(outputs["QuakeBSPBrushAssets.json"]),
        binaryFiles=len(raw),
        binaryBytes=sum(len(payload) for payload in raw.values()),
    )
    return outputs, receipt
