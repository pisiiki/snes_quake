"""Schema-aware pointer relocation for independently linked playable maps.

This module never writes its input directory. ``relocate_data`` returns derived
files, include replacements and a compact report for the owning build command.
The caller places each original file at the location selected by its mapper.
Pointer relocation does not move bytes or change run-time bank traversal: the
caller must keep straddling textures/UV/pool runs contiguous, or generate matching
bank lookup code. Six-bit lightmaps retain their two phase bits and bank<64 ABI.

Supported source formats: world texture/PVS/lightmap directories, QBSA v2,
QBSF v4 (relative offsets are deliberately unchanged), banked brush PVS, and
QBA1 v6 row/sprite directories. Only declared pointer fields are visited.
"""
from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import struct
import time
from typing import Callable, Mapping

from snes_tooling.quake.quake_playable_world_coordinates import (
    AFFINE_MODE_MASK, AFFINE_VARIANT_BIT, WORLD_FACE,
)

GsuMapper = Callable[[int, int], tuple[int, int]]
CpuMapper = Callable[[int], int]
TEXTURE = struct.Struct('<BHHHB')
LIGHTMAP = struct.Struct('<BHBBbb')
WORLD_PVS = struct.Struct('<HHHBB')
WORLD_NODE = struct.Struct('<HhhHH')
WORLD_PLANE = struct.Struct('<bbbh')
POSITIVE_AXES = {(64, 0, 0): 1, (0, 64, 0): 2, (0, 0, 64): 3}
WORLD_NODES_FILE = 'QuakeBSPWorldNodes.bin'
WORLD_PLANES_FILE = 'QuakeBSPWorldPlanes.bin'
WORLD_FACE_PLANES_FILE = 'QuakeBSPWorldFacePlanes.bin'
AXIAL_FACE_TAG_MASK = 0x1c
AXIAL_FACE_TAGS = {
    (32, 0, 0): 1, (0, 32, 0): 2, (0, 0, 32): 3,
    (-32, 0, 0): 4, (0, -32, 0): 5, (0, 0, -32): 6,
}
BRUSH_PVS = struct.Struct('<HB')
BRUSH_HEADER = struct.Struct('<4sHHI6HQ')
BRUSH_SECTION = struct.Struct('<8sBHHBH')
FRAGMENT_HEADER = struct.Struct('<4s15I')
ALIAS_HEADER = struct.Struct('<4s8H4IQ')
ALIAS_ROW = struct.Struct('<BBHBBH')
ALIAS_SPRITE = struct.Struct('<BBHBBBBBBhh')
BANK_BYTES = 32768


def index_quakec_functions(dense):
    """Keep original function IDs while sharing byte-identical 16-byte VM descriptors."""
    if not dense or len(dense) % 16 or len(dense) > 65536:
        raise ValueError("invalid dense QuakeC function table")
    index_bytes = len(dense) // 8
    offsets, index, records = {}, bytearray(), bytearray()
    for begin in range(0, len(dense), 16):
        record = dense[begin:begin + 16]
        if record not in offsets:
            offsets[record] = index_bytes + len(records)
            records.extend(record)
        # A larger table receives its original dense encoding.
        if offsets[record] > 65535:
            return None
        index.extend(struct.pack("<H", offsets[record]))
    return bytes(index + records) if len(index) + len(records) < len(dense) else None


def compact_face_owners(source: bytes) -> bytes | None:
    """Use one signed delta per face when every original BSP node ID fits."""
    deltas = [node - (face >> 1) for face, (node,) in enumerate(struct.iter_unpack('<H', source))]
    if len(deltas) <= 4:
        return None
    header = b''
    if max(deltas) - min(deltas) > 255:
        # A one-node correction per page of 256 faces fits the longer E1M1 tree.
        deltas = [delta + (face >> 8) for face, delta in enumerate(deltas)]
        if max(deltas) - min(deltas) > 255:
            return None
        header = struct.pack('<h', -32768)
    # Choose zero whenever possible to keep the GSU decode a single addition.
    bias = max(max(deltas) - 127, min(0, min(deltas) + 128))
    if not -32767 <= bias <= 32767:
        return None
    return header + struct.pack('<h', bias) + bytes((delta - bias) & 255 for delta in deltas)


def face_owner_format(payload: bytes) -> tuple[int, int]:
    bias, = struct.unpack_from('<h', payload)
    if bias == -32768:
        return struct.unpack_from('<h', payload, 2)[0], 4
    return bias, 2


def restore_face_owners(payload: bytes) -> bytes:
    bias, start = face_owner_format(payload)
    return b''.join(struct.pack('<H', (face >> 1) - ((face >> 8) if start == 4 else 0) + bias + delta)
                    for face, (delta,) in enumerate(struct.iter_unpack('b', payload[start:])))


def inline_axial_node_planes(nodes: bytes, planes: bytes) -> bytes:
    """Tag positive axial nodes with an exact signed 14-bit plane distance."""
    plane_records = tuple(WORLD_PLANE.iter_unpack(planes))
    if len(plane_records) > 0x4000:
        raise ValueError('playable BSP node plane indices exceed 14 bits')
    packed = bytearray()
    for plane, front, back, first, count in WORLD_NODE.iter_unpack(nodes):
        if plane >= len(plane_records):
            raise ValueError('BSP node refers to a missing plane')
        x, y, z, distance = plane_records[plane]
        axis = POSITIVE_AXES.get((x, y, z))
        if axis and -0x2000 <= distance < 0x2000 and plane < 2048 and count < 32:
            count |= plane << 5
            plane = (axis << 14) | (distance & 0x3fff)
        packed.extend(WORLD_NODE.pack(plane, front, back, first, count))
    return bytes(packed)


def restore_axial_node_planes(nodes: bytes, planes: bytes) -> bytes:
    """Recover the source node indices and reject tags inconsistent with their planes."""
    plane_records = tuple(WORLD_PLANE.iter_unpack(planes))
    unpacked = bytearray()
    for plane, front, back, first, count in WORLD_NODE.iter_unpack(nodes):
        axis = plane >> 14
        if axis:
            original_plane = count >> 5
            if original_plane >= len(plane_records):
                raise ValueError('tagged BSP node refers to a missing plane')
            x, y, z, distance = plane_records[original_plane]
            encoded = ((plane & 0x3fff) ^ 0x2000) - 0x2000
            if POSITIVE_AXES.get((x, y, z)) != axis or encoded != distance:
                raise ValueError('tagged BSP node differs from its source plane')
            plane, count = original_plane, count & 31
        unpacked.extend(WORLD_NODE.pack(plane, front, back, first, count))
    return bytes(unpacked)


def _axial_face_flags(faces: bytes, planes: bytes, *, restore: bool, mode_mask: int,
                      count_mask: int) -> bytes:
    """Use reserved face-flag bits without touching canonical plane records."""
    output = bytearray(faces)
    for index, (face, plane) in enumerate(zip(
            WORLD_FACE.iter_unpack(faces), WORLD_PLANE.iter_unpack(planes), strict=True)):
        _, count, _, _, flags = face
        if flags & AFFINE_VARIANT_BIT & ~mode_mask:
            raise ValueError('world face has a conflicting reserved flag bit')
        tag = AXIAL_FACE_TAGS.get(plane[:3], 0) if (count & count_mask) >= 3 and not flags & 3 else 0
        packed_tag = tag << 2
        stored_tag = flags & AXIAL_FACE_TAG_MASK
        if stored_tag != (packed_tag if restore else 0):
            raise ValueError('world face axial tag differs from its source plane')
        offset = index * WORLD_FACE.size + WORLD_FACE.size - 1
        output[offset] = (flags & ~AXIAL_FACE_TAG_MASK) if restore else flags | packed_tag
    return bytes(output)


def inline_axial_face_flags(faces: bytes, planes: bytes, *, mode_mask=AFFINE_MODE_MASK,
                            count_mask=0xFF) -> bytes:
    return _axial_face_flags(faces, planes, restore=False, mode_mask=mode_mask,
                            count_mask=count_mask)


def restore_axial_face_flags(faces: bytes, planes: bytes, *, mode_mask=AFFINE_MODE_MASK,
                             count_mask=0xFF) -> bytes:
    return _axial_face_flags(faces, planes, restore=True, mode_mask=mode_mask,
                            count_mask=count_mask)


def _identity(bank: int, address: int) -> tuple[int, int]:
    return bank, address


def _cpu_identity(address: int) -> int:
    return address


def mapped(mapper: GsuMapper, bank: int, address: int) -> tuple[int, int]:
    if type(bank) is not int or not 0 <= bank <= 255 or not 0 <= address <= 65535:
        raise ValueError('source pointer is outside the byte-bank/word-address ABI')
    result = mapper(bank, address)
    if (not isinstance(result, tuple) or len(result) != 2
            or any(type(value) is not int for value in result)
            or not 0 <= result[0] <= 255 or not 0 <= result[1] <= 65535):
        raise ValueError('mapper must return an in-range (bank, address) tuple')
    return result


def _records(payload: bytes, record: struct.Struct, label: str):
    if len(payload) % record.size:
        raise ValueError(f'{label} has a partial {record.size}-byte record')
    return record.iter_unpack(payload)


def relocate_textures(payload: bytes, mapper: GsuMapper) -> bytes:
    out = bytearray()
    for bank, address, width, height, flags in _records(payload, TEXTURE, 'texture directory'):
        if not width or not height:
            raise ValueError('texture directory contains empty dimensions')
        bank, address = mapped(mapper, bank, address)
        out.extend(TEXTURE.pack(bank, address, width, height, flags))
    return bytes(out)


def relocate_lightmaps(payload: bytes, mapper: GsuMapper) -> bytes:
    out = bytearray()
    for encoded, address, width, height, minimum_s, minimum_t in _records(payload, LIGHTMAP, 'lightmap directory'):
        if encoded == 255:
            # 0xFF is the missing-lightmap/encoded constant-level sentinel.
            out.extend(LIGHTMAP.pack(encoded, address, width, height, minimum_s, minimum_t))
            continue
        if not width or not height:
            raise ValueError('lightmap pointer has empty dimensions')
        bank, new_address = mapped(mapper, encoded & 63, address)
        if bank >= 64:
            raise ValueError('six-bit lightmap bank exceeds 0x3F; phase bits would be destroyed')
        encoded = bank | (encoded & 192)
        if encoded == 255:
            raise ValueError('relocated lightmap pointer collides with the 0xFF sentinel')
        out.extend(LIGHTMAP.pack(encoded, new_address, width, height, minimum_s, minimum_t))
    return bytes(out)


def relocate_world_pvs(payload: bytes, mapper: GsuMapper) -> bytes:
    out = bytearray()
    for address, size, face_count, bank, flags in _records(payload, WORLD_PVS, 'world PVS directory'):
        if not size:
            raise ValueError('world PVS directory has an empty encoded row')
        bank, address = mapped(mapper, bank, address)
        out.extend(WORLD_PVS.pack(address, size, face_count, bank, flags))
    return bytes(out)


def relocate_brush_pvs(payload: bytes, mapper: GsuMapper) -> bytes:
    return b''.join(BRUSH_PVS.pack(new_address, new_bank)
        for address, bank in _records(payload, BRUSH_PVS, 'brush PVS directory')
        for new_bank, new_address in (mapped(mapper, bank, address),))


def integer_definitions(text: str) -> dict[str, int]:
    """Read generated scalar assignments; expressions are not evaluated."""
    result = {}
    for match in re.finditer(r'^[ \t]*([A-Za-z_][A-Za-z_0-9]*)[ \t]*=[ \t]*(\$[0-9A-Fa-f]+|[0-9]+)[ \t]*(?:;[^\r\n]*)?\r?$', text, re.M):
        name, literal = match.groups()
        if name in result:
            raise ValueError(f'duplicate generated include scalar: {name}')
        result[name] = int(literal[1:], 16) if literal.startswith('$') else int(literal)
    return result


def patch_include_values(text: str, values: Mapping[str, int], *, append=False) -> str:
    """Replace only explicitly named integer definitions, preserving newlines."""
    newline = '\r\n' if '\r\n' in text else '\n'
    for name, value in values.items():
        if type(value) is not int or not 0 <= value <= 0xFFFFFFFF:
            raise ValueError(f'invalid generated scalar value: {name}')
        pattern = re.compile(r'^(?P<prefix>[ \t]*' + re.escape(name)
            + r'[ \t]*=[ \t]*)(?P<literal>\$[0-9A-Fa-f]+|[0-9]+)(?P<tail>[ \t]*(?:;[^\r\n]*)?\r?)$', re.M)
        matches = list(pattern.finditer(text))
        if len(matches) != 1:
            if not matches and append:
                text += ('' if not text or text.endswith(('\n', '\r')) else newline)
                text += f'{name} = ${value:X}{newline}'
                continue
            raise ValueError(f'expected one literal definition for {name}, found {len(matches)}')
        def replace(match):
            literal = match['literal']
            replacement = (f'${value:0{max(len(literal)-1, 2)}X}'
                           if literal.startswith('$') else str(value))
            return match['prefix'] + replacement + match['tail']
        text = pattern.sub(replace, text)
    return text


def pointer_include_patches(text: str, mapper: GsuMapper, cpu_mapper: CpuMapper = _cpu_identity,
                            *, extra_pairs=(), extra_bank_only=(), stream_world_visibility=False,
                            stream_world_coordinates=False, world_lightmap_unpack_bank=None) -> dict[str, int]:
    """Explicit generated-include ABI; no broad suffix or byte-pattern scan."""
    source = integer_definitions(text)
    pairs = (
        ('BSP_WORLD_TEXTURE_DIRECTORY_GSU_ROM_BANK', 'BSP_WORLD_TEXTURE_DIRECTORY_GSU_ROM_ADDRESS'),
        ('BSP_WORLD_FACE_TEXTURE_ID_GSU_ROM_BANK', 'BSP_WORLD_FACE_TEXTURE_ID_GSU_ROM_ADDRESS'),
        ('BSP_WORLD_LIGHTMAP_DIRECTORY_GSU_ROM_BANK', 'BSP_WORLD_LIGHTMAP_DIRECTORY_GSU_ROM_ADDRESS'),
        ('BSP_WORLD_PVS_DIRECTORY_ROM_BANK', 'BSP_WORLD_PVS_DIRECTORY_ROM_ADDRESS'),
        ('BSP_WORLD_PVS_GUARD_ROM_BANK', 'BSP_WORLD_PVS_GUARD_ROM_ADDRESS'),
        ('BSP_BRUSH_PVS_DIRECTORY_BANK', 'BSP_BRUSH_PVS_DIRECTORY_ADDRESS'),
        ('BSP_BRUSH_FRAGMENT_VARIANTS_BANK', 'BSP_BRUSH_FRAGMENT_VARIANTS_ADDRESS'),
        ('BSP_BRUSH_FRAGMENT_FACES_BANK', 'BSP_BRUSH_FRAGMENT_FACES_ADDRESS'),
        ('BSP_BRUSH_FRAGMENT_BUCKETS_BANK', 'BSP_BRUSH_FRAGMENT_BUCKETS_ADDRESS'),
        ('BSP_ALIAS_ROW_DIRECTORY_BANK', 'BSP_ALIAS_ROW_DIRECTORY_ADDRESS'),
        ('BSP_ALIAS_SPRITE_DIRECTORY_BANK', 'BSP_ALIAS_SPRITE_DIRECTORY_ADDRESS'),
        ('BSP_ALIAS_STATIC_STATES_BANK', 'BSP_ALIAS_STATIC_STATES_ADDRESS'),
        ('BSP_ALIAS_FLY_FACING_BANK', 'BSP_ALIAS_FLY_FACING_ADDRESS'),
        *extra_pairs,
    )
    bank_only = (
        'BSP_WORLD_SHADING_GSU_ROM_BANK', 'BSP_WORLD_TEXTURE_COORD_FIRST_GSU_ROM_BANK',
        'BSP_WORLD_TEXTURE_FIRST_GSU_ROM_BANK', 'BSP_WORLD_LIGHTMAP_FIRST_GSU_ROM_BANK',
        'BSP_WORLD_PVS_FIRST_GSU_ROM_BANK', 'BSP_WORLD_FACE_OWNERS_ROM_BANK',
        'BSP_LIGHTMAP_UNPACK_ROM_BANK', 'BSP_BRUSH_RUNTIME_FIRST_BANK',
        'BSP_BRUSH_TEXTURE_FIRST_BANK', 'BSP_BRUSH_FRAGMENT_FIRST_BANK',
        'BSP_BRUSH_FRAGMENT_DESCRIPTORS_FIRST_BANK', 'BSP_BRUSH_FRAGMENT_VERTICES_FIRST_BANK',
        *extra_bank_only,
    )
    out = {}
    # The generated scene shares one bank between face IDs and the material
    # directory, but emits only the latter's bank name. Relocate both bases.
    face_address = 'BSP_WORLD_FACE_TEXTURE_ID_GSU_ROM_ADDRESS'
    if face_address in source and 'BSP_WORLD_FACE_TEXTURE_ID_GSU_ROM_BANK' not in source:
        bank, address = mapped(mapper, source['BSP_WORLD_TEXTURE_DIRECTORY_GSU_ROM_BANK'],
                               source[face_address])
        out[face_address] = address
    for bank_name, address_name in pairs:
        if stream_world_visibility and bank_name.startswith("BSP_WORLD_PVS_"):
            continue
        if bank_name not in source:
            continue
        if address_name not in source:
            raise ValueError(f'generated include omitted paired address: {address_name}')
        bank, address = mapped(mapper, source[bank_name], source[address_name])
        out.update({bank_name: bank, address_name: address})
        if bank_name == 'BSP_BRUSH_PVS_DIRECTORY_BANK' and 'BSP_BRUSH_PVS_BANK' in source:
            out['BSP_BRUSH_PVS_BANK'] = bank
    for name in bank_only:
        if stream_world_visibility and name == "BSP_WORLD_PVS_FIRST_GSU_ROM_BANK":
            continue
        if stream_world_coordinates and name == "BSP_WORLD_TEXTURE_COORD_FIRST_GSU_ROM_BANK":
            continue
        if world_lightmap_unpack_bank is not None:
            if name == "BSP_WORLD_LIGHTMAP_FIRST_GSU_ROM_BANK":
                continue
            if name == "BSP_LIGHTMAP_UNPACK_ROM_BANK" and name in source:
                out[name] = world_lightmap_unpack_bank
                continue
        if name in source:
            out[name] = mapped(mapper, source[name], 0x8000)[0]
    for name in ('BSP_ALIAS_ROTATION_BASES_CPU_ADDRESS', 'BSP_ALIAS_ROTATION_PHASES_CPU_ADDRESS'):
        if name in source:
            address = cpu_mapper(source[name])
            if type(address) is not int or not 0 <= address <= 0xFFFFFF:
                raise ValueError(f'CPU mapper returned invalid address for {name}')
            out[name] = address
    return out


def _json(payload: bytes) -> dict:
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise ValueError('asset metadata must be a JSON object')
    return value


def _json_bytes(value: dict) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode('utf-8')


@dataclass(frozen=True)
class RelocationResult:
    files: dict[str, bytes]
    include_patches: dict[str, dict[str, int]]
    report: dict


class _Files:
    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.source: dict[str, bytes] = {}
        self.changed: dict[str, bytes] = {}

    def exists(self, name):
        return (self.directory / name).is_file()

    def get(self, name):
        if name not in self.source:
            self.source[name] = (self.directory / name).read_bytes()
        return self.changed.get(name, self.source[name])

    def original(self, name):
        self.get(name)
        return self.source[name]

    def put(self, name, payload):
        if payload != self.original(name):
            self.changed[name] = bytes(payload)

    def family(self, prefix):
        members = sorted((int(m[1]), p.name) for p in self.directory.glob(prefix + '*.bin')
            if (m := re.fullmatch(re.escape(prefix) + r'(\d+)\.bin', p.name)))
        if members and [n for n, _ in members] != list(range(len(members))):
            raise ValueError(f'{prefix} chunks are not a zero-based contiguous source family')
        return [name for _, name in members]


def _classic_span(files: _Files, bank_files: Mapping[int, str], bank, address, size):
    if bank not in bank_files or not 0x8000 <= address < 0x10000 or not 0 <= size <= 0x10000-address:
        raise ValueError('source brush pointer escapes its declared classic bank')
    name = bank_files[bank]
    payload = files.get(name)
    offset = address - 0x8000
    if offset + size > len(payload):
        raise ValueError('source brush pointer escapes its generated file')
    return name, offset, payload[offset:offset+size]


def _rewrite_span(files, bank_files, bank, address, old_size, replacement):
    name, offset, _ = _classic_span(files, bank_files, bank, address, old_size)
    if len(replacement) != old_size:
        raise ValueError('relocation must preserve source record extents')
    output = bytearray(files.get(name))
    output[offset:offset+old_size] = replacement
    files.put(name, output)


def _brush(files: _Files, mapper: GsuMapper):
    if not files.exists('QuakeBSPBrushAssets.json'):
        return [], None
    metadata = _json(files.original('QuakeBSPBrushAssets.json'))
    if metadata.get('schema') != 'quake-bsp-brush-assets' or metadata.get('version') != 2:
        raise ValueError('relocator supports QBSA metadata version 2 only')
    bank_files = {}
    families = (
        ('QuakeBSPBrushTexturePixels', metadata['capacity']['firstBrushBank']),
        ('QuakeBSPBrushRuntime', metadata['runtime']['firstBank']),
        ('QuakeBSPBrushFragments', metadata['worldComposition']['fragments']['firstBank']),
    )
    for prefix, first in families:
        for index, name in enumerate(files.family(prefix)):
            if first + index in bank_files:
                raise ValueError('source brush families overlap')
            bank_files[first + index] = name
    first_runtime = metadata['runtime']['firstBank']
    first_name = bank_files[first_runtime]
    header = BRUSH_HEADER.unpack_from(files.get(first_name))
    if header[0] != b'QBSA' or header[1] != 2 or header[2] != len(files.family('QuakeBSPBrushRuntime')):
        raise ValueError('invalid QBSA v2 source header')
    section_count = header[-2]
    expected = {section['name']: section for section in metadata['runtime']['sections']}
    if section_count != len(expected) or BRUSH_HEADER.size + section_count*BRUSH_SECTION.size > BANK_BYTES:
        raise ValueError('QBSA section directory count is invalid')
    records = []
    extra_pairs = []
    for index in range(section_count):
        pos = BRUSH_HEADER.size + index*BRUSH_SECTION.size
        name_bytes, bank, address, size, record_bytes, count = BRUSH_SECTION.unpack_from(files.original(first_name), pos)
        name = name_bytes.rstrip(b'\0').decode('ascii')
        if name not in expected:
            raise ValueError(f'unknown QBSA section {name!r}')
        entry = expected.pop(name)
        if (bank, address, size, record_bytes, count) != tuple(entry[k] for k in ('bank','address','bytes','recordBytes','recordCount')):
            raise ValueError(f'QBSA {name} section disagrees with its source metadata')
        _, _, payload = _classic_span(files, bank_files, bank, address, size)
        if name == 'TEXDIR':
            _rewrite_span(files, bank_files, bank, address, size, relocate_textures(payload, mapper))
        elif name == 'LIGHTDIR':
            _rewrite_span(files, bank_files, bank, address, size, relocate_lightmaps(payload, mapper))
        new_bank, new_address = mapped(mapper, bank, address)
        records.append((pos, BRUSH_SECTION.pack(name_bytes, new_bank, new_address, size, record_bytes, count)))
        extra_pairs.append((f'BSP_BRUSH_{name}_BANK', f'BSP_BRUSH_{name}_ADDRESS'))
    output = bytearray(files.get(first_name))
    for pos, record in records:
        output[pos:pos+len(record)] = record
    files.put(first_name, output)
    # QBSF carries package-relative indices/offsets, not absolute ROM pointers.
    fragments = metadata['worldComposition']['fragments']
    fragment_names = files.family('QuakeBSPBrushFragments')
    fragment_header = FRAGMENT_HEADER.unpack_from(files.get(fragment_names[0]))
    if fragment_header[0] != b'QBSF' or fragment_header[1] != 4 or fragment_header[2] != len(fragment_names):
        raise ValueError('invalid QBSF v4 source header')
    pvs = metadata['worldComposition']['leafPvs']
    if pvs['directoryRecordBytes'] != BRUSH_PVS.size or pvs['directoryBytes'] != pvs['leafCount']*BRUSH_PVS.size:
        raise ValueError('only explicit banked brush PVS directories are supported')
    _, _, payload = _classic_span(files, bank_files, pvs['directoryBank'], pvs['directoryAddress'], pvs['directoryBytes'])
    _rewrite_span(files, bank_files, pvs['directoryBank'], pvs['directoryAddress'], len(payload), relocate_brush_pvs(payload, mapper))
    return extra_pairs, metadata


def _aliases(files: _Files, mapper: GsuMapper, pixel_mapper=None):
    names = files.family('QuakeBSPAliasRuntime')
    if not names:
        return
    source = b''.join(files.original(name) for name in names)
    if any(len(files.original(name)) != BANK_BYTES for name in names):
        raise ValueError('QBA1 source chunks must be exactly 32 KiB')
    header = ALIAS_HEADER.unpack_from(source)
    if header[0] != b'QBA1' or header[1] != 6 or header[2] != ALIAS_HEADER.size or header[8] != len(names):
        raise ValueError('invalid QBA1 v6 source header')
    out = bytearray(source)
    for index in range(header[3]):
        pos = header[9] + index*ALIAS_ROW.size
        if pos < ALIAS_HEADER.size or pos+ALIAS_ROW.size > len(out):
            raise ValueError('QBA1 row directory escapes source package')
        dynamic_bank, dynamic_count, dynamic_address, group_bank, group_count, group_address = ALIAS_ROW.unpack_from(source, pos)
        if dynamic_count:
            dynamic_bank, dynamic_address = mapped(mapper, dynamic_bank, dynamic_address)
        if group_count:
            group_bank, group_address = mapped(mapper, group_bank, group_address)
        ALIAS_ROW.pack_into(out, pos, dynamic_bank, dynamic_count, dynamic_address, group_bank, group_count, group_address)
    for index in range(header[4]):
        pos = header[10] + index*ALIAS_SPRITE.size
        if pos < ALIAS_HEADER.size or pos+ALIAS_SPRITE.size > len(out):
            raise ValueError('QBA1 sprite directory escapes source package')
        row = list(ALIAS_SPRITE.unpack_from(source, pos))
        row[0], row[2] = mapped(pixel_mapper or mapper, row[0], row[2])
        ALIAS_SPRITE.pack_into(out, pos, *row)
    for index, name in enumerate(names):
        files.put(name, out[index*BANK_BYTES:(index+1)*BANK_BYTES])


def _world_metadata(metadata: dict, mapper: GsuMapper) -> dict:
    output = deepcopy(metadata)
    packing = output['world']['packing']
    exact = packing['exact_textures']
    for row in exact['textures']:
        row['gsu_rom_bank'], row['gsu_rom_address'] = mapped(mapper, row['gsu_rom_bank'], row['gsu_rom_address'])
    for family in ('coordinate_chunks', 'pixel_chunks'):
        for row in exact[family]:
            row['gsu_rom_bank'], row['gsu_rom_address'] = mapped(mapper, row['gsu_rom_bank'], row.get('gsu_rom_address', 0x8000))
    for row in exact['lightmaps']['sample_chunks']:
        row['gsu_rom_bank'], row['gsu_rom_address'] = mapped(mapper, row['gsu_rom_bank'], row.get('gsu_rom_address', 0x8000))
    pvs = packing['face_pvs']
    pvs['directory_gsu_rom_bank'], pvs['directory_gsu_rom_address'] = mapped(mapper, pvs['directory_gsu_rom_bank'], pvs['directory_gsu_rom_address'])
    guard = pvs['quantization_guard']
    guard['gsu_rom_bank'], guard['gsu_rom_address'] = mapped(mapper, guard['gsu_rom_bank'], guard['gsu_rom_address'])
    if 'shading_gsu_rom_bank' in packing:
        packing['shading_gsu_rom_bank'], packing['shading_gsu_rom_address'] = mapped(mapper, packing['shading_gsu_rom_bank'], 0x8000)
    return output


def _brush_metadata(metadata: dict, mapper: GsuMapper) -> dict:
    output = deepcopy(metadata)
    runtime = output['runtime']
    runtime['firstBank'] = mapped(mapper, runtime['firstBank'], 0x8000)[0]
    for row in runtime['sections']:
        row['bank'], row['address'] = mapped(mapper, row['bank'], row['address'])
    for row in output['textures']['textures']:
        row['bank'], row['address'] = mapped(mapper, row['bank'], row['address'])
    fragments = output['worldComposition']['fragments']
    # Keep source bankIndex/offset fields: they describe unchanged logical files.
    fragments['firstBank'] = mapped(mapper, fragments['firstBank'], 0x8000)[0]
    fragments['lastBank'] = mapped(mapper, fragments['lastBank'], 0x8000)[0]
    for role in fragments['bankRoles'].values():
        role['firstBank'] = mapped(mapper, role['firstBank'], 0x8000)[0]
    for name in ('variants', 'faces', 'buckets'):
        row = fragments['bankRoles']['control'][name]
        row['bank'], row['address'] = mapped(mapper, row['bank'], row['address'])
    pvs = output['worldComposition']['leafPvs']
    pvs['directoryBank'], pvs['directoryAddress'] = mapped(mapper, pvs['directoryBank'], pvs['directoryAddress'])
    pvs['bank'] = pvs['directoryBank']
    for row in pvs['rowStorage']:
        row['bank'], row['address'] = mapped(mapper, row['bank'], 0x8000+row['offset'])
        # offset remains local to the unchanged logical input file.
    return output


def relocate_data(directory: Path, mapper: GsuMapper = _identity,
                  cpu_mapper: CpuMapper = _cpu_identity, *, metadata_outputs=False,
                  alias_pixel_mapper=None, stream_world_visibility=False,
                  stream_world_coordinates=False, world_lightmap_unpack_bank=None) -> RelocationResult:
    """Return changed derived files without mutating Data or its receipts.

    Metadata outputs are opt-in: relocated JSON uses a new top-level marker and
    preserves source-local offsets/counts. Legacy metadata validators that assume
    contiguous classic banks must not be run against this derived view.
    """
    started = time.monotonic()
    if metadata_outputs and (stream_world_visibility or stream_world_coordinates or world_lightmap_unpack_bank is not None):
        raise ValueError("streamed world assets have no relocated GSU ROM metadata view")
    files = _Files(directory)
    for name, transform in (
        ('QuakeBSPWorldTextureDirectory.bin', relocate_textures),
        ('QuakeBSPWorldLightmapDirectory.bin', relocate_lightmaps),
        ('QuakeBSPWorldPVSDirectory.bin', relocate_world_pvs),
    ):
        if stream_world_visibility and transform is relocate_world_pvs:
            continue
        if world_lightmap_unpack_bank is not None and transform is relocate_lightmaps:
            continue
        if files.exists(name):
            files.put(name, transform(files.get(name), mapper))
    extra_pairs, brush_metadata = _brush(files, mapper)
    _aliases(files, mapper, alias_pixel_mapper)
    patches = {}
    for name in ('QuakeBSPScene.i', 'QuakeBSPBrushAssets.i', 'QuakeBSPAliasAssets.i'):
        if files.exists(name):
            text = files.get(name).decode('utf-8')
            patch = pointer_include_patches(text, mapper, cpu_mapper, extra_pairs=extra_pairs,
                                            stream_world_visibility=stream_world_visibility,
                                            stream_world_coordinates=stream_world_coordinates,
                                            world_lightmap_unpack_bank=world_lightmap_unpack_bank)
            files.put(name, patch_include_values(text, patch).encode('utf-8'))
            patches[name] = patch
    if files.exists('QuakeBSPAliasAssets.s'):
        text = files.get('QuakeBSPAliasAssets.s').decode('utf-8')
        def assertion(match):
            value = cpu_mapper(int(match[2], 16))
            if type(value) is not int or not 0 <= value <= 0xFFFFFF:
                raise ValueError('CPU mapper returned an invalid alias LOAD address')
            return match[1] + f'${value:06X}'
        text = re.sub(r'(\.assert __BSP_ALIAS_\d+_LOAD__ = )\$([0-9A-Fa-f]+)', assertion, text)
        files.put('QuakeBSPAliasAssets.s', text.encode('utf-8'))
    if metadata_outputs:
        transformed = {}
        if files.exists('QuakeBSPMetadata.json'):
            transformed['QuakeBSPMetadata.json'] = _world_metadata(_json(files.original('QuakeBSPMetadata.json')), mapper)
        if brush_metadata is not None:
            transformed['QuakeBSPBrushAssets.json'] = _brush_metadata(brush_metadata, mapper)
        for name, metadata in transformed.items():
            metadata['relocation'] = {'schema': 'quake-rom-pointer-relocation-v1',
                'sourceMetadataSha256': hashlib.sha256(files.original(name)).hexdigest(),
                'sourceLocalOffsetsPreserved': True}
            for output_name, row in metadata.get('outputs', {}).items():
                if output_name in files.changed and isinstance(row, dict):
                    row.update(bytes=len(files.changed[output_name]), sha256=hashlib.sha256(files.changed[output_name]).hexdigest())
            files.put(name, _json_bytes(metadata))
    source_hash = hashlib.sha256()
    for name, payload in sorted(files.source.items()):
        source_hash.update(name.encode('utf-8')+b'\0'+hashlib.sha256(payload).digest())
    return RelocationResult(dict(files.changed), patches,
        {'schema': 'quake-rom-pointer-relocation-v1', 'inputAggregateSha256': source_hash.hexdigest(),
         'inputFiles': len(files.source), 'changedFiles': len(files.changed),
         'changedBytes': sum(map(len, files.changed.values())),
         'elapsedSeconds': round(time.monotonic()-started, 6)})
