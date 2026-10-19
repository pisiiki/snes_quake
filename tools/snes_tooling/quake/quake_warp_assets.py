"""Reserve an OBJ palette by generating colour-equivalent runtime asset views."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
import time

import numpy as np

from snes_tooling.quake import audit_quake_bsp_sky_assets as audit
from snes_tooling.quake.quake_bsp_sky_assets import audit_opaque_palette_domain, is_quake_sky_texture_name
from snes_tooling.quake.quake_joint_background import tile_bytes, palette_words
from snes_tooling.quake.quake_warp_profile import DepthProfile
from snes_tooling.quake.quake_background_motion import motion_assets, oam_bytes
from snes_tooling.shared.generated_outputs import sync_generated_outputs, OwnedFileFamily

SWAPS = ((218, 80), (219, 128), (220, 129), (221, 157), (222, 158))
RESERVED = frozenset(range(209, 224))


def permutation():
    values = list(range(256))
    for a, b in SWAPS:
        values[a], values[b] = values[b], values[a]
    return bytes(values)


def remap_colormap(payload, mapping):
    original = np.frombuffer(payload, dtype=np.uint8).reshape(-1, 256)
    p = np.frombuffer(mapping, dtype=np.uint8)
    inverse = np.argsort(p)
    return p[original[:, inverse]].tobytes()


def remap_alias(chunks, metadata, mapping):
    """Only sprite rectangles are index+1 pixels; headers and directories are data."""
    header = audit.ALIAS_HEADER.unpack_from(chunks[0])
    if header[0] != b'QBA1':
        raise ValueError('unsupported alias container')
    storage = metadata['format']['storagePhysicalHalfbanks']
    package = b''.join(chunks)
    output = [bytearray(chunk) for chunk in chunks]
    encoded = bytes([0]+[mapping[value-1]+1 for value in range(1, 256)])
    rectangles = set()
    for i in range(header[4]):
        record = audit.ALIAS_SPRITE_RECORD.unpack_from(package, header[10]+i*audit.ALIAS_SPRITE_RECORD.size)
        bank, _, address, width, height = record[:5]
        physical = bank if bank < 0x40 else 64+(bank-0x60)*2+(address >= 0x8000)
        first = address & 0x7fff
        chunk = storage.index(physical)
        last = first+width*height
        if last > len(chunks[chunk]):
            raise ValueError('alias pixels cross their physical halfbank')
        rectangles.add((chunk, first, last))
        output[chunk][first:last] = chunks[chunk][first:last].translate(encoded)
    return list(map(bytes, output)), len(rectangles)


def remap_sky_include(text, mapping):
    text = re.sub(r'(^BSP_WORLD_SKY_MARKER_\d+ = )(\d+)',
                  lambda m: m[1]+str(mapping[int(m[2])]), text, flags=re.MULTILINE)
    def macro(m):
        return re.sub(r'\$([0-9A-Fa-f]{2})', lambda v: f'${mapping[int(v[1], 16)]:02X}', m[0])
    return re.sub(r'\.macro BSP_SKY_EMIT_FACE_MARKER_LUT\b.*?\.endmacro', macro, text, flags=re.DOTALL)


def generate(example, config, *, check=False):
    started = time.perf_counter()
    data = example.resolve()/'Data'
    model_bytes = config.read_bytes()
    model = json.loads(model_bytes)
    if model.get('schema') != 'quake-joint-background-v1' or model.get('objPalette') != 5:
        raise ValueError('a frozen palette-5 joint-background model is required')
    bindings = {}
    def read(name):
        return audit._read(data/name, bindings)
    metadata, world, _, _ = audit._world_textures(data, bindings)
    records = metadata['world']['packing']['exact_textures']['pixel_chunks']
    world_banks = {r['gsu_rom_bank']: read(f'QuakeBSPWorldTexturePixels{i}.bin') for i, r in enumerate(records)}
    _, brush = audit._brush_textures(data, bindings, world_banks)
    alias_metadata, alias_pixels = audit._alias_opaque_pixels(data, bindings)
    cm_names = ('QuakeBSPLightmapColormap.bin', 'QuakeBSPLightmapLevelZeroColormap.bin')
    maps = [read(name) for name in cm_names]
    domain = audit_opaque_palette_domain([t for t in world+brush if not is_quake_sky_texture_name(t.name)],
                                         maps, alias_pixels)
    used = set(domain.used_indices)
    for texture in world:
        if is_quake_sky_texture_name(texture.name):
            used.update(texture.pixels)
    sky = json.loads(read('QuakeBSPSkyAssets.json'))
    markers = {a['marker'] for a in sky['faceMarkers']['assignments']}
    mapping = permutation()
    mapped_used = {mapping[i] for i in used}
    if mapped_used & RESERVED or mapped_used & {mapping[i] for i in markers}:
        raise ValueError('reserved OBJ colours or sky markers collide with reachable opaque output')
    if mapping[0] != 0 or mapping[48] != 48 or mapping[64] != 64 or mapping[239] != 239:
        raise ValueError('clear/opaque-black/textureless/diagnostic indices changed')
    if any((i >= 224) != (mapping[i] >= 224) for i in range(256)):
        raise ValueError('fullbright threshold changed')
    original_palette = np.frombuffer(read('QuakeBSPTexturePalette.bin'), dtype='<u2')
    result_palette = original_palette[np.argsort(np.frombuffer(mapping, dtype=np.uint8))].copy()
    result_palette[209:224] = np.frombuffer(palette_words(model), dtype='<u2')
    if any(result_palette[mapping[i]] != original_palette[i] for i in used):
        raise ValueError('opaque scene RGB555 colours changed')
    outputs = {}
    for pattern in ('QuakeBSPWorldTexturePixels*.bin', 'QuakeBSPBrushTexturePixels*.bin',
                    'QuakeBSPComposedCacheChunk*.bin', 'QuakeBSPComposedCacheDirectoryPayload.bin'):
        for path in sorted(data.glob(pattern)):
            payload = read(path.name)
            # Composed data are already shaded canonical palette indices.
            if 'Composed' in path.name and set(payload.translate(mapping)) & RESERVED:
                raise ValueError(f'composed cache violates palette reservation: {path.name}')
            outputs[Path(path.name)] = payload.translate(mapping)
    for name, payload in zip(cm_names, maps, strict=True):
        remapped = remap_colormap(payload, mapping)
        original = np.frombuffer(payload, dtype=np.uint8).reshape(-1, 256)
        actual = np.frombuffer(remapped, dtype=np.uint8).reshape(-1, 256)
        p = np.frombuffer(mapping, dtype=np.uint8)
        if not np.array_equal(actual[:, p], p[original]):
            raise ValueError('colormap conjugation failed')
        outputs[Path(name)] = remapped
    chunks = [read(f'QuakeBSPAliasRuntime{i}.bin') for i in range(alias_metadata['format']['chunkCount'])]
    remapped, rectangles = remap_alias(chunks, alias_metadata, mapping)
    for i, payload in enumerate(remapped):
        outputs[Path(f'QuakeBSPAliasRuntime{i}.bin')] = payload
    outputs[Path('QuakeBSPSkyAssets.i')] = remap_sky_include(read('QuakeBSPSkyAssets.i').decode(), mapping).encode()
    for name in ('QuakeBSPComposedCacheAssets.s', 'QuakeBSPAliasAssets.s'):
        text = read(name).decode()
        text = re.sub(r'\.incbin "Data/([^"]+)"',
                      lambda m: '.incbin "Data/'+('Warp/' if Path(m[1]) in outputs else '')+m[1]+'"', text)
        outputs[Path(name)] = text.encode()
    outputs[Path('QuakeBSPTexturePalette.bin')] = result_palette.astype('<u2').tobytes()
    outputs[Path('WarpBackgroundTile.bin')] = tile_bytes(model)
    outputs[Path('WarpBackgroundPalette.bin')] = palette_words(model)
    outputs[Path('WarpDepthProfile.i')] = DepthProfile.from_record(model).assembly().encode()
    phases, motion = motion_assets(model, read('QuakeBSPDemoPrecise.bin'))
    outputs[Path('WarpBackgroundMotion.bin')] = phases
    outputs[Path('WarpBackgroundOam.bin')] = oam_bytes()
    enabled = int(any(motion['backgroundMotion']['gains']))
    outputs[Path('WarpMotionProfile.i')] = (
        '; Four offline-trained gains; runtime reads one packed X/Y phase per demo pose.\n'
        f'WARP_BACKGROUND_MOTION_ENABLED = {enabled}\n'
        f'WARP_BACKGROUND_MOTION_POSES = {motion["poses"]}\n').encode()
    outputs[Path('WarpPaletteMap.bin')] = mapping
    proof = {'schema': 'quake-warp-runtime-assets-v1', 'passed': True, 'swaps': SWAPS,
             'canonicalOpaqueDomain': asdict(domain), 'finalUsedIndices': sorted(mapped_used),
             'skyMarkers': sorted(markers), 'remappedSkyMarkers': sorted(mapping[i] for i in markers),
             'reservedVisibleIndices': sorted(RESERVED), 'sceneColorsPreserved': True,
             'colormapConjugationVerified': True, 'aliasRectangles': rectangles,
             'runtimeRemappingInstructions': 0, 'textureBytes': 2048, 'cgramUploadBytesAddedPerFrame': 0,
             'backgroundMotion': motion, 'backgroundObjects': 20,
             'inputs': {str(p.relative_to(data)): hashlib.sha256(v).hexdigest() for p, v in bindings.items()},
             'modelSha256': hashlib.sha256(model_bytes).hexdigest(),
             'generatorSha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
             'outputs': {str(p): {'bytes': len(v), 'sha256': hashlib.sha256(v).hexdigest()} for p, v in outputs.items()}}
    outputs[Path('WarpAssets.json')] = (json.dumps(proof, indent=2)+'\n').encode()
    sync_generated_outputs(outputs, data/'Warp', check=check,
                           owned_families=[OwnedFileFamily('Quake', suffix) for suffix in ('.bin', '.s', '.i')]
                           +[OwnedFileFamily('Warp', suffix) for suffix in ('.bin', '.i', '.json')])
    return {'passed': True, 'outputs': len(outputs), 'check': check,
            'elapsedSeconds': round(time.perf_counter()-started, 3)}
