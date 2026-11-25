"""Build E1M1's stock switchable light styles in the playable renderer's palette."""
from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
from struct import Struct

import numpy as np

from snes_tooling.quake import quake_bsp_assets as bsp
from snes_tooling.quake import quake_bsp_brush_assets as brush
from snes_tooling.quake.evaluate_quake_bsp_precomposed_surfaces import (
    Lightmap, TEXTURE_COORDINATE_RECORD, load_assets,
)
from snes_tooling.quake.quake_face_colors import face_color
from snes_tooling.quake.quake_lightmap_packing import unpack_six_bit_samples
from snes_tooling.quake.quake_playable_layout import gsu_offset
from snes_tooling.quake.quake_uniform_brush_materials import load_materials


STYLE_32_OFF = 16  # The five lamps named t3 start lit. The other four styles start dark.
FLUORESCENT_OFF = 32
FLUORESCENT_PATTERN = b"mmamammmmammamamaaamammma"
ALL_ON = 15
MASK_COUNT = 64
COLOR_PAGE_SPLIT = 2048
COLOR_ROW_BYTES = 512
GRID_TAG = 0xFE
GRID_POINTER = Struct("<BH")
GRID_DESCRIPTOR = Struct("<HHBB")
REPAIR = Struct("<BHH3s")
STREAM_SEGMENT = "BSP_E1M1_LIGHT_STYLES_64"
FIVE_STYLE_SEGMENT = "BSP_E1M1_LIGHT_STYLES_32"
FOUR_STYLE_SEGMENT = "BSP_E1M1_LIGHT_STYLES"
REPAIR_SEGMENT = "BSP_E1M1_LIGHT_STYLE_POINTERS"
DIRECTORY_SEGMENT = "BSP_E1M1_SWITCHED_GRID_DIRECTORY"
REFERENCE_COLORS = "QuakeBSPSwitchedFaceColors.bin"


def style_bit(style):
    if style == 10:
        return FLUORESCENT_OFF
    if style == 32:
        return STYLE_32_OFF
    return 1 << (style - 33) if 33 <= style <= 36 else 0


def style_mask(styles):
    return sum(style_bit(style) for style in styles)


def sample_levels(lighting, face, count, active):
    """Use the 'a' and 'm' values (0 and 264) passed to Quake lightstyle."""
    total = np.zeros(count, dtype=np.int32)
    for plane, style in enumerate(face.light_styles):
        if style == 255:
            break
        bit = style_bit(style)
        if bit and not (active ^ (STYLE_32_OFF | FLUORESCENT_OFF)) & bit:
            continue
        start = face.light_offset + plane * count
        total += np.frombuffer(lighting, dtype=np.uint8, count=count, offset=start)
    levels = np.clip((255 * 256 - total * bsp.QUAKE_NEUTRAL_LIGHT_STYLE_SCALE) >> 10, 0, 63)
    return levels.astype(np.uint8).tobytes()


@dataclass(frozen=True)
class SwitchableLights:
    stride: int
    payload: bytes
    # For the world and the packed brush tables, (record index, stream offset).
    faces: tuple[tuple[tuple[int, int], ...], tuple[tuple[int, int], ...]]
    brush_directory: tuple[int, int]

    @property
    def directory_bytes(self):
        return GRID_DESCRIPTOR.size * sum(map(len, self.faces))

    def replace_pointers(self, buffer, table, grids, start=0):
        result = bytearray(buffer)
        repairs = bytearray()
        for face, offset in self.faces[table]:
            at = start + face * brush.LIGHTMAP_RECORD.size
            original = bytes(result[at:at + GRID_POINTER.size])
            if len(original) != GRID_POINTER.size or original[0] in (0xFF, GRID_TAG):
                raise ValueError("switchable light requires a resident lightmap")
            bank, address, width, height, _, _ = brush.LIGHTMAP_RECORD.unpack_from(result, at)
            descriptor = len(grids) * GRID_DESCRIPTOR.size
            grids.append((offset, bank, address, width * height))
            repairs.extend(REPAIR.pack(table, face, descriptor, original))
            GRID_POINTER.pack_into(result, at, GRID_TAG, descriptor)
        return bytes(result), bytes(repairs)

    def resident_grid_directory(self, rom, grids):
        """Prove the runtime predicate against every linked switched grid variant."""
        directory = bytearray()
        for offset, bank, address, count in grids:
            if bank >= 0x40 or not 0 < count <= 512:
                raise ValueError("switchable grid needs group-aligned resident samples")
            start = gsu_offset(bank, address)
            size = (count * 6 + 7) // 8
            if address + size > 0x10000 or offset + 1 + count > self.stride:
                raise ValueError("switchable grid crosses its linked sample range")
            decoded = unpack_six_bit_samples(rom[start:start + size], 0, count)
            resident = bytes(sample | 0xC0 for sample in decoded)
            matches = set()
            varying = 0
            for mask in range(MASK_COUNT):
                start = mask * self.stride + offset + 1  # Skip the Flat color.
                if self.payload[start:start + count] == resident:
                    matches.add(mask)
                    varying |= mask ^ ALL_ON
            required = (MASK_COUNT - 1) ^ varying
            if matches != {mask for mask in range(MASK_COUNT) if not (mask ^ ALL_ON) & required}:
                raise ValueError(f"switched grid {offset:#x} lacks an exact resident style predicate")
            directory.extend(GRID_DESCRIPTOR.pack(offset, address, required, bank))
        if len(directory) != self.directory_bytes:
            raise ValueError("linked switched grid directory differs from its allocation")
        return bytes(directory)

    def color_tables(self, original):
        """One byte per face selects its intensity sequence in the face's page."""
        pages = ({}, {})
        tokens = []
        for table, (rows, colors) in enumerate(zip(self.faces, original, strict=True)):
            offsets = dict(rows)
            result = bytearray()
            for index, color in enumerate(colors):
                if index in offsets:
                    offset = offsets[index]
                    pattern = bytes(self.payload[m * self.stride + offset] for m in range(MASK_COUNT))
                    if pattern[ALL_ON] != color:
                        raise ValueError("fully illuminated Flat face differs from its original color")
                else:
                    pattern = bytes([color]) * MASK_COUNT
                patterns = pages[int(table == 1 or index >= COLOR_PAGE_SPLIT)]
                token = patterns.setdefault(pattern, len(patterns))
                if token >= 256:
                    raise ValueError("E1M1 switchable color page exceeds its byte index")
                result.append(token)
            tokens.append(bytes(result))
        rows = bytearray(MASK_COUNT * COLOR_ROW_BYTES)
        for page, patterns in enumerate(pages):
            for pattern, index in patterns.items():
                rows[256 * page + index::COLOR_ROW_BYTES] = pattern
        return tuple(tokens), bytes(rows)

    def linked_grids(self, module, segment_files):
        names = [name for name in ("BSP_WORLD_LIGHTMAP_DIRECTORY", "BSP_WORLD_LIGHTMAP_DIRECTORY_TAIL")
                 if (module, name) in segment_files]
        parts = [Path(segment_files[module, name]).read_bytes() for name in names]
        grids = []
        combined, repairs = self.replace_pointers(b"".join(parts), 0, grids)
        changed = {}
        cursor = 0
        for name, original in zip(names, parts, strict=True):
            changed[module, name] = combined[cursor:cursor + len(original)]
            cursor += len(original)
        bank, start = self.brush_directory
        key = (module, f"BSP_BRUSH_RUNTIME_{bank}")
        changed[key], brush_repairs = self.replace_pointers(Path(segment_files[key]).read_bytes(), 1, grids, start)
        return changed, repairs + brush_repairs, grids


def restore_grid_pointers(files, meta, repairs):
    section = next(r for r in meta["runtime"]["sections"] if r["name"] == "LIGHTDIR")
    names = ("QuakeBSPWorldLightmapDirectory.bin",
             f"QuakeBSPBrushRuntime{section['bank'] - meta['runtime']['firstBank']}.bin")
    buffers = tuple(bytearray(files[name]) for name in names)
    for table, index, offset, original in REPAIR.iter_unpack(repairs):
        at = (section["address"] - 0x8000 if table else 0) + index * brush.LIGHTMAP_RECORD.size
        if GRID_POINTER.unpack_from(buffers[table], at) != (GRID_TAG, offset):
            raise ValueError("linked switchable light does not point to its archived face")
        buffers[table][at:at + GRID_POINTER.size] = original
    for name, result in zip(names, buffers, strict=True):
        files[name] = bytes(result)


def build_switchable_lights(data, pak, *, palette_map=None):
    data = Path(data)
    if b"\0" + FLUORESCENT_PATTERN + b"\0" not in pak.read("progs.dat"):
        raise ValueError("original fluorescent light style is missing")
    source = brush._parse_bsp(pak.read("maps/e1m1.bsp"))
    world = load_assets(data)
    textures, _, _, bindings = load_materials(data)
    colors = np.fromfile(data / "QuakeBSPTexturePalette.bin", dtype="<u2").astype(np.int64)
    palette = (colors[:, None] >> np.array([0, 5, 10])) & 31
    if palette_map is None:
        palette_map = bytes(range(256))
    brush_meta = json.loads(bindings["QuakeBSPBrushAssets.json"])
    runtime = brush_meta["runtime"]
    sections = brush.decode_runtime_sections(tuple(
        bindings[f"QuakeBSPBrushRuntime{i}.bin"] for i in range(runtime["bankCount"])))
    coordinates = sections["TEXCOORD"]
    if "TEXCOORD" in runtime.get("offlineSourceGeometry", {}):
        coordinates = (data / "QuakeBSPBrushBakeTexcoord.bin").read_bytes()
    coordinates = tuple(TEXTURE_COORDINATE_RECORD.iter_unpack(coordinates))
    directory = next(entry for entry in runtime["sections"] if entry["name"] == "LIGHTDIR")
    brush_directory = (directory["bank"] - runtime["firstBank"], directory["address"] - 0x8000)

    faces = ([], [])
    masks = [bytearray() for _ in range(MASK_COUNT)]

    def add(table, index, face, polygon, texture, light):
        mask = style_mask(face.light_styles)
        if not mask:
            return
        if light.bank == 0xFF or face.light_offset < 0 or not polygon:
            raise ValueError("missing source light samples on a switched face")
        count = light.width * light.height
        choices = {}
        faces[table].append((index, len(masks[0])))
        for active, output in enumerate(masks):
            local = active & mask
            if local not in choices:
                levels = sample_levels(source.lighting, face, count, local)
                color = face_color(polygon, textures[texture], replace(light, samples=levels),
                                   0, world.colormap, palette)
                choices[local] = bytes((palette_map[color],)) + bytes(0xC0 | value for value in levels)
            output.extend(choices[local])

    first_world = source.models[0][14]
    for index, ((first, count), texture, light) in enumerate(zip(
            world.faces, world.face_texture_ids, world.lightmaps, strict=True)):
        add(0, index, source.faces[first_world + index], world.face_texture_coordinates[first:first + count],
            texture, light)
    for index, (face, light) in enumerate(zip(brush.FACE_RECORD.iter_unpack(sections["FACES"]),
                                             brush.LIGHTMAP_RECORD.iter_unpack(sections["LIGHTDIR"]), strict=True)):
        first, count, texture, _, source_id = face
        if source_id >= len(source.faces):
            continue  # Separately sourced brush models have their own lighting lump.
        bank, address, width, height, s, t = light
        add(1, index, source.faces[source_id], coordinates[first:first + count], texture,
            Lightmap(bank, address, width, height, s * 16, t * 16, None))
    stride = len(masks[0])
    if not 0 < stride < 0x8000 or any(len(row) != stride for row in masks):
        raise ValueError("switchable light banks must have equal, word-addressable extents")
    return SwitchableLights(stride, b"".join(masks), tuple(tuple(rows) for rows in faces), brush_directory)
