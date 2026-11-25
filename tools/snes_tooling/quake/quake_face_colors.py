"""Bake one natural RGB555 palette index for each playable BSP face."""

from hashlib import sha256
import json
from pathlib import Path

import numpy as np

from snes_tooling.quake import quake_bsp_assets as bsp
from snes_tooling.quake import quake_bsp_brush_assets as brush
from snes_tooling.quake.evaluate_quake_bsp_precomposed_surfaces import (
    Lightmap, TEXTURE_COORDINATE_RECORD, _decode_lightmap_directory,
    _lightmap_levels, load_assets,
)
from snes_tooling.quake.quake_bsp_brush_fragments import FACE_MATERIAL_RECORD
from snes_tooling.quake.quake_uniform_brush_materials import load_materials

FILE = 'QuakeBSPFaceColors.bin'
WORLD_RECORD_BYTES = 6
WORLD_COLOR_OFFSET = 4
BRUSH_COLOR_OFFSET = FACE_MATERIAL_RECORD.size - 1


def face_color(polygon, texture, lightmap, missing_level, colormap, palette):
    # Test texel centers in Q4 against the convex texture-space polygon.
    polygon = np.asarray(polygon, dtype=np.int64)
    minimum = polygon.min(axis=0) // 16
    maximum = (polygon.max(axis=0) + 15) // 16
    s = np.arange(minimum[0], maximum[0])
    t = np.arange(minimum[1], maximum[1])
    positive = np.ones((len(t), len(s)), dtype=bool)
    negative = positive.copy()
    for (x0, y0), (x1, y1) in zip(polygon, np.roll(polygon, -1, axis=0), strict=True):
        side = (x1 - x0) * (16 * t[:, None] + 8 - y0) - (y1 - y0) * (16 * s + 8 - x0)
        positive &= side >= 0
        negative &= side <= 0
    covered = positive | negative
    if not covered.any():
        s, t = (np.array([value]) for value in polygon.sum(axis=0) // (16 * len(polygon)))
        covered = np.ones((1, 1), dtype=bool)

    width, height = texture['width'], texture['height']
    pixels = np.frombuffer(texture['pixels'], dtype=np.uint8).reshape(height, width)
    texels = pixels[t[:, None] % height, s % width]
    if texture['name'].startswith('*'):
        lit = texels
    else:
        levels = missing_level if lightmap.samples is None else _lightmap_levels(lightmap, s, t)
        lit = colormap[levels, texels]
    colors = palette[lit[covered]]
    delta = palette * len(colors) - colors.sum(axis=0)
    return int(np.argmin((delta * delta).sum(axis=1)))


def brush_material_location(metadata):
    fragments = metadata['worldComposition']['fragments']
    return fragments['bankRoles']['control']['faces'], fragments['faceMaterialCount']


def install_colors(records, colors, offset, stride):
    result = bytearray(records)
    if offset + (len(colors) - 1) * stride >= len(result):
        raise ValueError('baked face colors escape their record table')
    result[offset:offset + len(colors) * stride:stride] = colors
    return bytes(result)


def bake_face_colors(data):
    data = Path(data)
    world = load_assets(data)
    textures, _, _, bindings = load_materials(data)
    words = np.fromfile(data / 'QuakeBSPTexturePalette.bin', dtype='<u2').astype(np.int64)
    if len(words) != 256:
        raise ValueError('baked face colors require the native 256-entry palette')
    palette = (words[:, None] >> np.array([0, 5, 10])) & 31
    world_lights = _decode_lightmap_directory((data / 'QuakeBSPWorldLightmapDirectory.bin').read_bytes())

    def bake(polygon, texture_id, lightmap, address):
        if len(polygon) < 3 or texture_id >= len(textures):
            return 0  # Omitted or non-renderable source face.
        return face_color(polygon, textures[texture_id], lightmap, address & 63, world.colormap, palette)

    world_colors = bytes(
        bake(world.face_texture_coordinates[first:first + count], texture_id, lightmap, directory[1])
        for (first, count), texture_id, lightmap, directory in zip(
            world.faces, world.face_texture_ids, world.lightmaps, world_lights, strict=True)
    )
    metadata = json.loads(bindings['QuakeBSPBrushAssets.json'])
    sections = brush.decode_runtime_sections(tuple(
        bindings[f'QuakeBSPBrushRuntime{i}.bin'] for i in range(metadata['runtime']['bankCount'])))
    coords = sections['TEXCOORD']
    if 'TEXCOORD' in metadata['runtime'].get('offlineSourceGeometry', {}):
        name = 'QuakeBSPBrushBakeTexcoord.bin'
        coords = (data / name).read_bytes()
        identity = dict(bytes=len(coords), sha256=sha256(coords).hexdigest())
        if identity != metadata['outputs'][name] or identity != metadata['runtime']['offlineSourceGeometry']['TEXCOORD']:
            raise ValueError('brush color bake coordinates differ from the authored geometry')
    coordinates = tuple(TEXTURE_COORDINATE_RECORD.iter_unpack(coords))
    by_source = {}
    for face, light in zip(brush.FACE_RECORD.iter_unpack(sections['FACES']),
                           brush.LIGHTMAP_RECORD.iter_unpack(sections['LIGHTDIR']), strict=True):
        first, count, texture_id, _, source = face
        bank, address, width, height, minimum_s, minimum_t = light
        samples = None
        if bank != 0xFF:
            phase = bank >> bsp.LIGHTMAP_PHASE_SHIFT
            offset = bsp.lightmap_location_sample_offset(address, phase)
            samples = bsp.unpack_six_bit_samples(sections['LIGHTS'], offset, width * height)
        lightmap = Lightmap(bank, address, width, height, minimum_s * 16, minimum_t * 16, samples)
        by_source[source] = bake(coordinates[first:first + count], texture_id, lightmap, address)

    location, count = brush_material_location(metadata)
    packed = (data / f"QuakeBSPBrushFragments{location['bankIndex']}.bin").read_bytes()
    start = location['offset']
    records = packed[start:start + count * FACE_MATERIAL_RECORD.size]
    return world_colors, bytes(by_source[row[0]] for row in FACE_MATERIAL_RECORD.iter_unpack(records))
