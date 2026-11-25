"""Mandatory playable MSU image and checked composite cartridge publication."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import struct

from snes_tooling.quake.quake_playable_layout import (
    CODE_NAMES, CPU_MODULE_METADATA_OFFSET, GSU_ROM_BYTES, HALFBANK, Placement, ROM_BYTES,
)
from snes_tooling.quake.quake_playable_maps import MAP_NAMES, default_map_for_count, id_for
from snes_tooling.quake.quake_playable_relocation import (
    AXIAL_FACE_TAG_MASK, inline_axial_face_flags,
)
from snes_tooling.quake.quake_playable_raw_contours import RAW_CONTOUR_DIRECTORY, RAW_CONTOUR_MARKER
from snes_tooling.quake.quake_playable_world_lightmap import RESIDENT_GRIDS, RESIDENT_ORIGINALS
from snes_tooling.quake.quake_playable_world_coordinates import AFFINE_DESCRIPTOR_SEGMENT
from snes_tooling.quake.quake_face_colors import (
    BRUSH_COLOR_OFFSET, FACE_MATERIAL_RECORD, WORLD_COLOR_OFFSET, WORLD_RECORD_BYTES, install_colors,
)
from snes_tooling.shared.ld65_debug import load_required_ld65_labels

HEADER_BYTES = 64
MAGIC = b"QPL1"
BOOT_TABLE_OFFSET = CPU_MODULE_METADATA_OFFSET


def archive_bytes(image: bytes, binding: bytes, *, map_count=2) -> bytes:
    if len(binding) != 16:
        raise ValueError("playable archive requires a 16-byte package binding")
    if not 2 <= map_count <= len(MAP_NAMES):
        raise ValueError("playable archive has an unsupported module count")
    header = MAGIC + binding + struct.pack("<III", 1, map_count, len(image))
    header = header.ljust(HEADER_BYTES, b"\0")
    # A complemented byte detects a truncated MSU stream even when the data
    # byte itself is zero. The runtime validates each pair before publishing.
    paired = bytearray(2*len(image))
    paired[0::2] = image
    paired[1::2] = image.translate(bytes(255-i for i in range(256)))
    return header + paired


def verify_archive_read(archive: bytes, source_offset: int, size: int, binding: bytes) -> bytes:
    """Host form of the same header/pair contract used by the S-CPU loader."""
    if archive[:20] != MAGIC + binding:
        raise ValueError("incompatible playable archive")
    if source_offset < 0 or size < 0:
        raise ValueError("negative playable archive range")
    first, last = HEADER_BYTES+2*source_offset, HEADER_BYTES+2*(source_offset+size)
    payload = archive[first:last]
    if len(payload) != size*2 or any(a ^ b != 255 for a, b in zip(payload[0::2], payload[1::2])):
        raise ValueError("truncated or corrupt playable archive payload")
    return payload[0::2]


def binding_include(binding: bytes) -> bytes:
    if len(binding) != 16:
        raise ValueError("playable binding length")
    values = ", ".join(f"${value:02X}" for value in binding)
    # Source classes: canonical linear CPU ROM; fast LoROM modules; virtual
    # MSU-only load images at $40:0000. Avoid unsupported multi-arg .define.
    return ("; Generated mandatory playable archive identity.\n"
        ".macro PLAYABLE_ARCHIVE_BINDING\n"
        f"        .byte {values}\n.endmacro\n"
        ".define PLAYABLE_MSU_OFFSET(source) ($40 + 2 * (((^(source) >= $C0) * ((source) - $C00000)) + ((^(source) >= $80) .and (^(source) < $C0)) * (((^(source) - $80) * $8000) + (.loword(source) & $7FFF)) + ((^(source) >= $60) .and (^(source) < $70)) * ((source) - $400000) + ((^(source) >= $40) .and (^(source) < $50)) * (source)))\n"
    ).encode("ascii")


def _checksum(image):
    # The fixed 4 MiB LoROM image is a power of two; header checksum fields
    # sum to 510 independently of the checksum's actual value.
    image[0x7FDC:0x7FE0] = b"\xff\xff\0\0"
    checksum = sum(image) & 0xFFFF
    struct.pack_into("<HH", image, 0x7FDC, checksum ^ 0xFFFF, checksum)


def compose(layout, module_roms, module_symbols, segment_files, binding: bytes, *, tape_boot=None):
    """Merge only allocated ranges; identical explicit shared data is allowed.

    module_roms are linker staging images whose first halfbank contains each
    module's complete CPU bank. Other segment payloads have isolated outputs.
    """
    rom = bytearray(b"\xff" * ROM_BYTES)
    side_image = bytearray(b"\xff" * ROM_BYTES)
    written = {}
    boots = []

    def place(buffer, offset, payload, key, *, shared=False):
        end = offset + len(payload)
        if end > len(buffer):
            buffer.extend(b"\xff"*(end-len(buffer)))
        for start, stop, other, old in written.setdefault(id(buffer), []):
            if offset < stop and start < end:
                lo, hi = max(start, offset), min(stop, end)
                if not shared or bytes(buffer[lo:hi]) != payload[lo-offset:hi-offset]:
                    raise ValueError(f"conflicting playable image ranges: {key} / {other}")
        buffer[offset:end] = payload
        written[id(buffer)].append((offset, end, key, payload))

    count = len(module_roms)
    if not 2 <= count <= len(MAP_NAMES) or len(module_symbols) != count:
        raise ValueError("playable publication requires matching registered CPU modules")
    for module in range(count):
        ranges = layout.cpu_module_ranges(module)
        code_limit = 0x8000 + ranges[0][1]
        source = Path(module_roms[module]).read_bytes()
        if len(source) < HALFBANK:
            raise ValueError("truncated linked playable CPU bank")
        if len(ranges) == 2:
            gap_start, gap_end = ranges[0][1], ranges[1][0]
            if source[gap_start:gap_end] != b"\xff" * (gap_end-gap_start):
                raise ValueError(f"CPU-{module} wrote into the reserved cartridge-data window")
        for first, end in ranges:
            place(rom, module*HALFBANK+first, source[first:end], f"CPU-{module}/{first:04x}")
        symbols = load_required_ld65_labels(Path(module_symbols[module]), ("BootVector",))
        boot = symbols["BootVector"]
        if boot >> 16 != 0x80+module or not 0x8000 <= (boot & 0xffff) < code_limit:
            raise ValueError("playable BootVector is outside its CPU module")
        boots.append(boot)
    table = b"".join(value.to_bytes(3, "little") for value in boots)
    default = id_for(default_map_for_count(count, tape_boot=tape_boot))
    trampoline_required = default != 0 or tape_boot is not None
    envelope = len(table) + (4 if trampoline_required else 0)
    if rom[BOOT_TABLE_OFFSET:BOOT_TABLE_OFFSET+envelope] != b"\xff"*envelope:
        raise ValueError("playable boot table overlaps CPU code")
    rom[BOOT_TABLE_OFFSET:BOOT_TABLE_OFFSET+len(table)] = table
    if trampoline_required:
        code_limit = 0x8000 + layout.cpu_module_ranges(default)[0][1]
        symbols = load_required_ld65_labels(Path(module_symbols[default]), ("PlayableColdBoot",))
        cold = symbols["PlayableColdBoot"]
        if cold >> 16 != 0x80+default or not 0x8000 <= (cold & 0xffff) < code_limit:
            raise ValueError("playable cold entry is outside the default CPU module")
        trampoline = BOOT_TABLE_OFFSET + len(table)
        rom[trampoline:trampoline+4] = b"\x5c" + cold.to_bytes(3, "little")
        rom[0x7FFC:0x7FFE] = (0x8000+trampoline).to_bytes(2, "little")

    spc = []
    rows = []
    affine_uv = []
    affine_regions = []
    face_color_rows = []
    from snes_tooling.quake.quake_switchable_lights import DIRECTORY_SEGMENT, REPAIR_SEGMENT, STREAM_SEGMENT
    switched_files = {}
    switched_repairs = {}
    switched_grids = {}
    for module, (lights, _, _) in getattr(layout, "switchable_lights", {}).items():
        changed, switched_repairs[module], switched_grids[module] = lights.linked_grids(module, segment_files)
        switched_files.update(changed)
    affine_plans = getattr(layout, "world_affine_uv", {})
    for key, placement in sorted(layout.placements.items()):
        module, name = key
        if name in CODE_NAMES:
            continue
        path = Path(segment_files[key])
        payload = switched_files[key] if key in switched_files else path.read_bytes()
        if len(payload) != placement.size:
            raise ValueError(f"linked segment changed its allocated extent: {key}")
        if name == "SMPCODE":
            spc.append((layout.spans[key].run, len(payload), sha256(payload).hexdigest()))
        baked = None
        if module in getattr(layout, 'face_colors', {}):
            world_colors, brush_colors = layout.face_colors[module]
            location = layout.brush_color_locations[module]
            if name == 'BSP_WORLD_FACES':
                baked = (world_colors, WORLD_COLOR_OFFSET, WORLD_RECORD_BYTES)
            elif name == f"BSP_BRUSH_FRAGMENTS_{location['bankIndex']}":
                baked = (brush_colors, location['offset'] + BRUSH_COLOR_OFFSET, FACE_MATERIAL_RECORD.size)
        linked_payload = payload
        if baked is not None:
            colors, offset, stride = baked
            payload = install_colors(payload, colors, offset, stride)
        if placement.storage == "msu":
            place(side_image, placement.offset, payload, key, shared=True)
        else:
            place(rom, placement.offset, payload, key, shared=True)
        row = dict(module=module, segment=name, path=str(path),
                   sha256=sha256(payload).hexdigest(), **placement.summary())
        if baked is not None:
            row['faceColors'] = {'offset': offset, 'stride': stride,
                                 'bytes': len(colors), 'sha256': sha256(colors).hexdigest()}
            legacy = linked_payload[offset:offset + len(colors) * stride:stride]
            face_color_rows.append((row, legacy))
        if name == "BSP_WORLD_FACES" and module in affine_plans:
            plan = affine_plans[module]
            planes = Path(segment_files[(module, "BSP_WORLD_FACE_PLANES")]).read_bytes()
            raw_contours = getattr(layout, "raw_world_contours", {}).get(module)
            faces = raw_contours.faces if raw_contours is not None else plan.faces
            expected_faces = inline_axial_face_flags(
                faces, planes, mode_mask=plan.mode_mask, count_mask=plan.count_mask)
            if placement.storage != "gsu" or linked_payload != expected_faces:
                raise ValueError("linked world face records disagree with the exact affine plan")
            affine_regions.append(row)
            row["affineUvModeBits"] = plan.mode_mask
            row["axialCullModeBits"] = AXIAL_FACE_TAG_MASK
            mode_faces = raw_contours.mode_faces if raw_contours is not None else plan.mode_faces
            report = dict(module=module, map=MAP_NAMES[module], offset=placement.offset,
                          faceCount=plan.face_count, modeFaces=mode_faces,
                          faceRecordsSha256=row["sha256"])
            if plan.descriptor_bytes:
                offset = layout.affine_descriptor_offsets[module]
                size = len(plan.descriptor_bytes)
                if not 0 <= offset < offset + size <= GSU_ROM_BYTES:
                    raise ValueError("world affine descriptor table escapes GSU ROM")
                descriptor = dict(module=module, segment=AFFINE_DESCRIPTOR_SEGMENT,
                    sha256=sha256(plan.descriptor_bytes).hexdigest(),
                    **Placement(offset, size, "gsu").summary())
                place(rom, offset, plan.descriptor_bytes, (module, AFFINE_DESCRIPTOR_SEGMENT))
                rows.append(descriptor)
                affine_regions.append(descriptor)
                row["affineUvDescriptors"] = True
                report["descriptors"] = {key: descriptor[key] for key in ("offset", "bytes", "sha256")}
            if raw_contours is not None:
                for name, offset, blob in raw_contours.regions:
                    raw_row = dict(module=module, segment=name, sha256=sha256(blob).hexdigest(),
                                   **Placement(offset, len(blob), "gsu").summary())
                    place(rom, offset, blob, (module, name))
                    rows.append(raw_row)
                    affine_regions.append(raw_row)
                    if name == RAW_CONTOUR_DIRECTORY:
                        report["rawContours"] = dict(marker=RAW_CONTOUR_MARKER,
                            faces=raw_contours.face_count, shards=len(raw_contours.regions)-1,
                            bytes=sum(len(payload) for _, _, payload in raw_contours.regions),
                            directorySha256=raw_row["sha256"])
            affine_uv.append(report)
        rows.append(row)
    if len(spc) != count or any(row != spc[0] for row in spc):
        raise ValueError("all playable modules must share exactly the same SPC driver and samples")
    sprite_tails = []
    for module, (offset, payload) in sorted(getattr(layout, "sprite_tails", {}).items()):
        if hasattr(layout, "weapon_obj"):
            from snes_tooling.quake.quake_weapon_obj import permute_alias_pixels
            payload = permute_alias_pixels(payload, layout.weapon_alias_ranges[module][0],
                                           layout.weapon_obj[0], source_offset=HALFBANK-len(payload))
        place(side_image, offset, payload, (module, "sprite tail"))
        sprite_tails.append(dict(module=module, segment="BSP_ALIAS_TAIL", storage="msu", offset=offset,
                                 bytes=len(payload), sha256=sha256(payload).hexdigest()))
    visibility = []
    for module, (plan, offset) in sorted(getattr(layout, "visibility_streams", {}).items()):
        if module not in range(count) or offset < ROM_BYTES:
            raise ValueError("world visibility stream escapes the playable sidecar")
        place(side_image, offset, plan.payload, (module, "visibility"))
        visibility.append(dict(module=module, offset=offset, rows=plan.row_count,
            rowBytes=plan.row_bytes, stride=plan.stride, bytes=len(plan.payload),
            sha256=sha256(plan.payload).hexdigest()))
    for module, (payload, offset) in getattr(layout, "intermission", {}).items():
        place(side_image, offset, payload, (module, "intermission"))
        rows.append(dict(module=module, segment="intermission", sha256=sha256(payload).hexdigest(),
                         **Placement(offset, len(payload), "msu").summary()))
    if hasattr(layout, "x3_software_weapon"):
        payload, offset, _, _ = layout.x3_software_weapon
        place(side_image, offset, payload, (0, "X3 software weapon"))
        rows.append(dict(module=0, segment="BSP_X3_SOFTWARE_WEAPON", sha256=sha256(payload).hexdigest(),
                         **Placement(offset, len(payload), "msu").summary()))
    for module, (lights, colors, offset) in getattr(layout, "switchable_lights", {}).items():
        payload = colors + lights.payload
        for name, position, blob in ((STREAM_SEGMENT, offset, payload),
                                     (REPAIR_SEGMENT, offset + len(payload), switched_repairs[module])):
            place(side_image, position, blob, (module, name))
            rows.append(dict(module=module, segment=name, sha256=sha256(blob).hexdigest(),
                             **Placement(position, len(blob), "msu").summary()))
    # Keep exact source recovery possible through the sidecar. The renderer
    # only needs the in-record palette byte and never reads these old values.
    for row, legacy in face_color_rows:
        offset = len(side_image)
        place(side_image, offset, legacy, (row['module'], row['segment'], 'legacy face bytes'))
        row['faceColors']['original'] = dict(segment='legacy face bytes', storage='msu', offset=offset,
            bytes=len(legacy), sha256=sha256(legacy).hexdigest())
    for module, (plan, offset) in getattr(layout, 'resident_world_lightmaps', {}).items():
        originals = plan.originals
        for name, storage, buffer, address, payload in (
            (RESIDENT_GRIDS, "gsu", rom, offset, plan.payload),
            (RESIDENT_ORIGINALS, "msu", side_image, len(side_image), originals),
        ):
            place(buffer, address, payload, (module, name))
            rows.append(dict(module=module, segment=name, sha256=sha256(payload).hexdigest(),
                             **Placement(address, len(payload), storage).summary()))
    for module, (lights, _, _) in getattr(layout, "switchable_lights", {}).items():
        payload = lights.resident_grid_directory(rom, switched_grids[module])
        offset = layout.switched_grid_directory[module]
        place(rom, offset, payload, (module, DIRECTORY_SEGMENT))
        rows.append(dict(module=module, segment=DIRECTORY_SEGMENT, sha256=sha256(payload).hexdigest(),
                         **Placement(offset, len(payload), "cpu").summary()))
    status_hud = None
    if hasattr(layout, "status_hud"):
        hud, graphics, maps, glyphs = layout.status_hud
        place(rom, graphics, hud.graphics, "shared status HUD graphics")
        place(rom, maps, hud.maps, "shared status HUD maps")
        place(rom, glyphs, hud.glyphs, "shared status HUD glyphs")
        status_hud = dict(offset=graphics, mapsOffset=maps, glyphsOffset=glyphs,
                          bytes=len(hud.payload), tiles=hud.tile_count, sha256=sha256(hud.payload).hexdigest())
        if hud.obj_graphics:
            status_hud.update(backgroundVramBytes=len(hud.graphics), spriteVramBytes=len(hud.obj_graphics),
                              gameplayVramSaved=64 * hud.obj_replaced_tiles - len(hud.obj_graphics),
                              spriteOamSlots=hud.obj_count)
    weapon_obj = []
    if hasattr(layout, "pickup_blend"):
        place(rom, layout.presentation_offsets["pickup-blend"], layout.pickup_blend, "pickup color shifts")
    if hasattr(layout, "weapon_obj"):
        for i, (offset, payload) in enumerate(zip(layout.weapon_obj_offsets, layout.weapon_obj_payloads, strict=True)):
            place(rom, offset, payload, ("shared", "weapon OBJ", i))
            weapon_obj.append(dict(offset=offset, bytes=len(payload), sha256=sha256(payload).hexdigest()))
    _checksum(rom)
    for row in affine_regions:
        offset, size = row["offset"], row["bytes"]
        if sha256(rom[offset:offset+size]).hexdigest() != row["sha256"]:
            raise ValueError(f"final playable ROM changed linked affine data: {row['segment']}")
    side_image[:ROM_BYTES] = rom
    industrial_audio = getattr(layout, "industrial_audio", None)
    if industrial_audio is not None:
        ambient_offset = len(side_image)
        side_image.extend(industrial_audio.payload)
    archive = archive_bytes(bytes(side_image), binding, map_count=count)
    if industrial_audio is not None:
        # Bytes 32..35 publish the first checked data/complement pair. Original
        # graphics offsets are stable as the four sound loops follow the image.
        archive = archive[:32] + struct.pack("<I", HEADER_BYTES + 2*ambient_offset) + archive[36:]
    return bytes(rom), archive, dict(schema="quake-playable-package-v1", boots=boots,
        defaultMap=MAP_NAMES[default], moduleCount=count,
        **({"tapeBoot": tape_boot.report()} if tape_boot is not None else {}),
        romBytes=len(rom), romSha256=sha256(rom).hexdigest(), archiveBytes=len(archive),
        archiveSha256=sha256(archive).hexdigest(), binding=binding.hex(),
        **({"industrialAudio": industrial_audio.report} if industrial_audio is not None else {}),
        spc=dict(run=spc[0][0], bytes=spc[0][1], sha256=spc[0][2]), segments=rows,
        visibilityStreams=visibility, spriteTails=sprite_tails,
        **({"affineWorldCoordinates": affine_uv} if affine_uv else {}),
        **({"statusHud": status_hud} if status_hud else {}),
        **({"weaponObj": weapon_obj} if weapon_obj else {}))
