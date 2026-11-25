"""Generate exact constant-color proofs for missing-lightmap brush materials."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import time

from snes_tooling.quake.audit_quake_bsp_sky_assets import AuditError, _banked_payload
from snes_tooling.quake.quake_bsp_brush_assets import decode_runtime_sections
from snes_tooling.shared.generated_outputs import sync_generated_outputs

HEADER = Path('UniformBrushMaterials.i')
TEXTURE = struct.Struct('<BHHHB')
LIGHTMAP = struct.Struct('<BHBBbb')
UNKNOWN = 0xFFFF


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _integer(value, label, minimum, maximum):
    _require(type(value) is int and minimum <= value <= maximum,
             f'{label} is outside its supported integer domain')
    return value


def classify_material(pixels, width, height, colormap, level, *, flags=0, name=''):
    """Inspect the complete texture in the actual linked palette domain."""
    _integer(width, 'texture width', 1, 0xFFFF)
    _integer(height, 'texture height', 1, 0xFFFF)
    _integer(level, 'missing lightmap level', 0, 63)
    _require(len(pixels) == width * height,
             'uniform material texture dimensions differ from its payload')
    _require(len(colormap) == 64 * 256,
             'uniform material requires the complete runtime colormap')
    if flags & ~3 or name.casefold().startswith('sky'):
        return UNKNOWN
    colors = {colormap[level * 256 + texel] for texel in set(pixels)}
    return next(iter(colors)) if len(colors) == 1 else UNKNOWN


def missing_levels(payload):
    _require(len(payload) % LIGHTMAP.size == 0,
             'uniform material lightmap directory is unaligned')
    levels = set()
    for bank, address, width, height, minimum_s, minimum_t in LIGHTMAP.iter_unpack(payload):
        if bank != 0xFF:
            continue
        _require(0xC0 <= address <= 0xFF
                 and (width, height, minimum_s, minimum_t) == (0, 0, 0, 0),
                 'uniform material has malformed missing-lightmap encoding')
        levels.add(address - 0xC0)
    return tuple(sorted(levels))


def load_materials(data):
    """Validate dense global IDs and read the linked canonical texels."""
    data = Path(data)
    bindings = {}

    def read(relative, metadata=None):
        relative = Path(relative)
        _require(not relative.is_absolute() and '..' not in relative.parts,
                 'uniform material input escapes Data')
        payload = (data / relative).read_bytes()
        if metadata is not None:
            record = metadata.get('outputs', {}).get(relative.name)
            _require(isinstance(record, dict)
                     and record.get('bytes') == len(payload)
                     and record.get('sha256') == hashlib.sha256(payload).hexdigest(),
                     'uniform material input binding differs: ' + relative.as_posix())
        bindings[relative.as_posix()] = payload
        return payload

    world = json.loads(read('QuakeBSPMetadata.json'))
    brush = json.loads(read('QuakeBSPBrushAssets.json'))
    exact = world['world']['packing']['exact_textures']
    world_directory = read('QuakeBSPWorldTextureDirectory.bin', world)
    _require(len(world_directory) % TEXTURE.size == 0,
             'uniform material world texture directory is unaligned')
    world_records = list(TEXTURE.iter_unpack(world_directory))
    _require(len(exact['textures']) == len(world_records),
             'uniform material world texture metadata count differs')
    runtime_count = _integer(brush['runtime']['bankCount'], 'brush runtime bank count', 1, 63)
    sections = decode_runtime_sections(tuple(read(f'QuakeBSPBrushRuntime{i}.bin', brush)
                                             for i in range(runtime_count)))
    extra_directory = sections['TEXDIR']
    _require(len(extra_directory) % TEXTURE.size == 0,
             'uniform material brush texture directory is unaligned')
    extra_records = list(TEXTURE.iter_unpack(extra_directory))
    info = brush['textures']
    _require(info['worldPackedTextureCount'] == len(world_records)
             and info['extraTextureCount'] == len(extra_records)
             and len(info['textures']) == len(extra_records),
             'uniform material global texture namespace differs')
    banks = {}

    def add_bank(bank, filename, metadata):
        _integer(bank, 'texture ROM bank', 0, 255)
        _require(bank not in banks, 'uniform material texture bank is duplicated')
        normal = read(filename, metadata)
        _require(len(normal) == 0x8000,
                 'uniform material texture banks must contain 32768 bytes')
        banks[bank] = normal

    for i, record in enumerate(exact['pixel_chunks']):
        filename = f'QuakeBSPWorldTexturePixels{i}.bin'
        _require(record['file'] == filename, 'uniform material world bank filename differs')
        add_bank(record['gsu_rom_bank'], filename, world)
    if extra_records:
        first_bank = min(record['bank'] for record in info['textures'])
        bank_count = _integer(info['packedBankCount'], 'brush texture bank count', 1, 63)
        for i in range(bank_count):
            add_bank(first_bank + i, f'QuakeBSPBrushTexturePixels{i}.bin', brush)

    textures = []
    for i, record in enumerate(world_records + extra_records):
        bank, address, width, height, flags = record
        _integer(width, 'texture width', 1, 0xFFFF)
        _integer(height, 'texture height', 1, 0xFFFF)
        _require(address >= 0x8000, 'uniform material texture address is outside its bank')
        if flags & 1:
            _require(not (width & (width - 1) or height & (height - 1)),
                     'uniform material power-of-two flag contradicts dimensions')
        if flags & 2:
            _require((address & 0x7FFF) + width * height <= 0x8000,
                     'uniform material single-bank flag contradicts dimensions')
        if i < len(world_records):
            metadata = exact['textures'][i]
            expected = (metadata['gsu_rom_bank'], metadata['gsu_rom_address'],
                        metadata['width'], metadata['height'], metadata['directory_flags'])
            _require(metadata['packed_id'] == i and record == expected,
                     'uniform material world texture identity differs')
            size, digest = metadata['level0_bytes'], metadata['level0_sha256']
        else:
            metadata = info['textures'][i - len(world_records)]
            expected = (metadata['bank'], metadata['address'], *metadata['dimensions'])
            _require(metadata['packedId'] == i and record[:4] == expected,
                     'uniform material brush texture identity differs')
            size, digest = metadata['level0Bytes'], metadata['level0Sha256']
        _require(size == width * height, 'uniform material declared texture size differs')
        _require(isinstance(metadata['name'], str) and metadata['name'],
                 'uniform material texture name is missing')
        try:
            normal = _banked_payload(banks, bank, address, size)
        except AuditError as error:
            raise ValueError(str(error)) from error
        _require(hashlib.sha256(normal).hexdigest() == digest,
                 'uniform material source texture hash differs')
        textures.append(dict(name=metadata['name'], width=width, height=height,
                             flags=flags, pixels=normal))
    _require(0 < len(textures) <= 256, 'uniform material texture count escapes uint8 identity')
    levels = missing_levels(sections['LIGHTDIR'])
    colormap = read('QuakeBSPLightmapColormap.bin', world)
    _require(len(colormap) == 64 * 256, 'uniform material runtime colormap size differs')
    colors = tuple(classify_material(texture['pixels'], texture['width'], texture['height'],
                                    colormap, level, flags=texture['flags'], name=texture['name'])
                   for level in levels for texture in textures)
    return textures, levels, colors, bindings


def encode_header(texture_count, levels, colors, bindings):
    _integer(texture_count, 'uniform material texture count', 1, 256)
    _require(tuple(sorted(set(levels))) == tuple(levels)
             and all(type(level) is int and 0 <= level < 64 for level in levels),
             'uniform material levels are invalid')
    _require(len(colors) == texture_count * len(levels), 'uniform material table dimensions differ')
    _require(all(type(color) is int and (0 <= color <= 255 or color == UNKNOWN) for color in colors),
             'uniform material result is invalid')
    lines = [
        '; Generated exact material proof; canonical palette indices.',
        '; FFFF retains the ordinary renderer; colors are level-major u16.',
        '.ifndef BSP_BRUSH_UNIFORM_TEXTURE_COUNT',
        *(f'; {name} bytes={len(payload)} sha256={hashlib.sha256(payload).hexdigest()}'
          for name, payload in sorted(bindings.items())),
        f'BSP_BRUSH_UNIFORM_TEXTURE_COUNT = {texture_count}',
        f'BSP_BRUSH_UNIFORM_LEVEL_COUNT = {len(levels)}',
        'F3_BSP_BRUSH_UNIFORM_TEXTURE_COUNT = BSP_BRUSH_UNIFORM_TEXTURE_COUNT',
        'F3_BSP_BRUSH_UNIFORM_LEVEL_COUNT = BSP_BRUSH_UNIFORM_LEVEL_COUNT',
        '.macro BSP_EMIT_BRUSH_UNIFORM_LEVELS',
    ]
    if levels:
        lines.append('    .byte ' + ', '.join(f'${0xC0 + level:02X}' for level in levels))
    lines += ['.endmacro', '.macro BSP_EMIT_BRUSH_UNIFORM_COLORS']
    for start in range(0, len(colors), 8):
        lines.append('    .word ' + ', '.join(f'${color:04X}' for color in colors[start:start + 8]))
    lines += ['.endmacro', '.macro F3_BSP_EMIT_BRUSH_UNIFORM_LEVELS',
              '    BSP_EMIT_BRUSH_UNIFORM_LEVELS', '.endmacro',
              '.macro F3_BSP_EMIT_BRUSH_UNIFORM_COLORS', '    BSP_EMIT_BRUSH_UNIFORM_COLORS',
              '.endmacro', '.endif', '']
    return '\n'.join(lines).encode('ascii')


def generate(example, *, check=False):
    started = time.perf_counter()
    data = Path(example) / 'Data'
    textures, levels, colors, bindings = load_materials(data)
    payload = encode_header(len(textures), levels, colors, bindings)
    sync_generated_outputs({HEADER: payload}, data / 'Fly3x', check=check)
    return dict(textureCount=len(textures), encodedLevels=[0xC0 + level for level in levels],
                uniformEntries=sum(color != UNKNOWN for color in colors),
                fallbackEntries=sum(color == UNKNOWN for color in colors),
                tableBytes=len(levels) + 2 * len(colors),
                inputs=[dict(name=name, bytes=len(value), sha256=hashlib.sha256(value).hexdigest())
                        for name, value in sorted(bindings.items())],
                headerSha256=hashlib.sha256(payload).hexdigest(),
                elapsedSeconds=round(time.perf_counter() - started, 6))
