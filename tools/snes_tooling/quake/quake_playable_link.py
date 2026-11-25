"""Staging bridge from LevelLayout placements to independent ld65 modules.

All preparation functions are pure with respect to the staged example: they
return derived files for the owning build command to publish. Each non-CPU
segment gets one explicit MEMORY region and one binary output; native 128 ROM
fill regions remain in place, retaining the ordinary four-MiB linker output.
The first 32 KiB of each linked output retain the CPU halfbank file offsets.
The packager copies only the windows reserved for CPU code and metadata.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from struct import Struct
import time

from snes_tooling.quake.quake_bsp_brush_assets import VISUAL_TEXTURE_RECORD, decode_runtime_sections
from snes_tooling.quake.quake_playable_layout import (
    HALFBANK, WORLD_LIGHTMAP_SAMPLES, LevelLayout, cpu_address, gsu_address, link_address,
)
from snes_tooling.quake.quake_playable_maps import MAP_NAMES, native_constants
from snes_tooling.quake.quake_playable_sprite_stream import pixel_mapper, stream_files
from snes_tooling.quake.quake_playable_materials import declare_material_segments, derived_material_files, MATERIAL
from snes_tooling.quake.quake_playable_alias_budget import compact_empty_alias_files
from snes_tooling.quake.quake_playable_structural_budget import compact_brush_structure_files
from snes_tooling.quake.quake_playable_relocation import (
    WORLD_FACE_PLANES_FILE, WORLD_NODES_FILE, WORLD_PLANES_FILE,
    inline_axial_face_flags, inline_axial_node_planes,
    integer_definitions, patch_include_values, relocate_data,
)

CPU_BANK_SEGMENTS = frozenset(('CODE', 'RODATA', 'LIBSFX', 'LIBSFX_PKG',
    'HEADER', 'VECTORS', 'NULL'))
RUN_AREAS = {'BSP_QUAKEC': 'QCCPU', 'BSP_WALK_HULL': 'WALKCPU', 'BSP_SHOT_HULL': 'SHOTCPU'}
SEGMENT_LINE = re.compile(r'^(?P<indent>[ \t]*)(?P<name>\w+):(?P<attrs>[^;\r\n]+);(?P<tail>[^\r\n]*)$', re.M)
INTEGER = r'(\$[A-Fa-f0-9]+|[0-9]+)'


def _number(literal):
    return int(literal[1:], 16) if literal.startswith('$') else int(literal)


def _attribute(attrs, name):
    match = re.search(r'\b'+re.escape(name)+r'\s*=\s*([^,;]+)', attrs)
    return match[1].strip() if match else None


def _replace_attribute(attrs, name, value):
    pattern = re.compile(r'(\b'+re.escape(name)+r'\s*=\s*)([^,;]+)')
    if len(pattern.findall(attrs)) != 1:
        raise ValueError(f'expected one {name} attribute')
    return pattern.sub(lambda match: match[1]+value, attrs)


def _section(text, label):
    match = re.search(r'(?m)^'+re.escape(label)+r'\s*\{', text)
    if not match:
        raise ValueError(f'missing linker {label} block')
    close = text.find('}', match.end())
    if close < 0 or '{' in text[match.end():close]:
        raise ValueError(f'unsupported nested/incomplete linker {label} block')
    return match.end(), close


def _entries(text, label):
    begin, end = _section(text, label)
    rows = list(SEGMENT_LINE.finditer(text, begin, end))
    result = {m['name']: m for m in rows}
    if len(result) != len(rows):
        raise ValueError(f'duplicate linker {label} entry')
    return result


def require_segment_declarations(template, names):
    segments = _entries(template, 'SEGMENTS')
    missing = sorted(name for name in names if name not in segments)
    if missing:
        raise ValueError(f"no linker segment declaration for {', '.join(missing)}")


def _placement(layout, module, name):
    try:
        return layout.placements[module, name]
    except KeyError as error:
        raise ValueError(f'map {module} is missing placement {name}') from error


def _gsu(layout, module, name):
    placement = _placement(layout, module, name)
    if placement.storage != 'gsu':
        raise ValueError(f'{name} is sampled by GSU but was allocated to {placement.storage}')
    return gsu_address(placement.offset)


def rewrite_linker_configuration(template: str, layout: LevelLayout, module: int,
                                 bins_directory: Path) -> tuple[str, dict[str, Path]]:
    """Bind segments to exact linker addresses; retain load/run distinctions."""
    if module not in range(len(MAP_NAMES)):
        raise ValueError('playable module ID is not registered')
    newline = '\r\n' if '\r\n' in template else '\n'
    memory = _entries(template, 'MEMORY')
    segments = _entries(template, 'SEGMENTS')
    placements = {name: p for (m, name), p in layout.placements.items() if m == module}
    additions, paths, replacements = [], {}, []
    for name, placement in sorted(placements.items()):
        if name in CPU_BANK_SEGMENTS:
            if name in segments and _attribute(segments[name]['attrs'], 'load') != 'ROM0':
                raise ValueError(f'{name} must remain in the module CPU bank')
            continue
        if name not in segments:
            raise ValueError(f'no linker segment declaration for {name}')
        entry = segments[name]
        attrs = entry['attrs']
        for field in ('align_load', 'align'):
            literal = _attribute(attrs, field)
            if literal is not None:
                if not re.fullmatch(INTEGER, literal):
                    raise ValueError(f'{name} uses an unsupported {field} expression')
                alignment = _number(literal)
                if alignment < 1 or placement.link % alignment:
                    raise ValueError(f'{name} placement {placement.link:06X} violates {field}={literal}')
        area = 'P_'+name
        path = (Path(bins_directory)/f'{name}.bin').resolve()
        if any(character in str(path) for character in ('"', '\n', '\r')):
            raise ValueError('linker binary path contains unsupported characters')
        additions.append(f'    {area}: start = ${placement.link:06X}, size = ${placement.size:X}, '
                         f'file = "{path.as_posix()}", fill = yes, fillval = $FF, define = yes;')
        attrs = _replace_attribute(attrs, 'load', area)
        # Explicit native starts (e.g. composed directory $82D000) retain an
        # exact start contract at their assigned new location.
        if _attribute(attrs, 'start') is not None:
            attrs = _replace_attribute(attrs, 'start', f'${placement.link:06X}')
        replacements.append((entry.start(), entry.end(),
            entry['indent']+name+':'+attrs+';'+entry['tail']))
        paths[name] = path
        if name in RUN_AREAS:
            run_name = RUN_AREAS[name]
            if _attribute(entry['attrs'], 'run') != run_name or run_name not in memory:
                raise ValueError(f'{name} lost its expected {run_name} run area')
            run = memory[run_name]
            attrs = _replace_attribute(run['attrs'], 'start', f'${placement.cpu:06X}')
            attrs = _replace_attribute(attrs, 'size', f'${placement.size:X}')
            replacements.append((run.start(), run.end(),
                run['indent']+run_name+':'+attrs+';'+run['tail']))
    if 'ROM0' not in memory:
        raise ValueError('native linker configuration has no ROM0')
    rom0 = memory['ROM0']
    base = 0x808000+module*0x10000
    attrs = _replace_attribute(rom0['attrs'], 'start', f'${base:06X}')
    reserved = layout.cpu_module_ranges(module)
    remainder = ''
    if len(reserved) == 2:
        code_end, metadata_start = reserved[0][1], reserved[1][0]
        attrs = _replace_attribute(attrs, 'size', f'${code_end:X}')
        # Output fill preserves the original file offsets, but no CPU segment
        # can be linked into the window now allocated to cartridge data.
        remainder = (f'{newline}    ROM0_GAP: start = ${base+code_end:06X}, '
                     f'size = ${metadata_start-code_end:X}, fill = yes, fillval = $FF;'
                     f'{newline}    ROM0_META: start = ${base+metadata_start:06X}, '
                     f'size = ${HALFBANK-metadata_start:X}, fill = yes, fillval = $FF;')
    replacements.append((rom0.start(), rom0.end(), rom0['indent']+'ROM0:'+attrs+';'+rom0['tail']+remainder))
    for name in ('HEADER', 'VECTORS'):
        entry = segments[name]
        old = _attribute(entry['attrs'], 'start')
        if old is None or not re.fullmatch(INTEGER, old):
            raise ValueError(f'{name} must have an explicit native start')
        value = _number(old)
        if value >> 16 != 0x80:
            raise ValueError(f'{name} is not based in native bank 80')
        attrs = _replace_attribute(entry['attrs'], 'start', f'${value+module*0x10000:06X}')
        if len(reserved) == 2:
            attrs = _replace_attribute(attrs, 'load', 'ROM0_META')
        replacements.append((entry.start(), entry.end(), entry['indent']+name+':'+attrs+';'+entry['tail']))
    for begin, end, replacement in sorted(replacements, reverse=True):
        template = template[:begin]+replacement+template[end:]
    _, memory_end = _section(template, 'MEMORY')
    template = template[:memory_end]+newline+newline.join(additions)+newline+template[memory_end:]
    return template, paths


def cpu_pointer_mapper(layout: LevelLayout, module: int):
    """Map old CPU/linker ROM mirrors to the new canonical CPU mirror."""
    def pointer(address):
        bank, word = address >> 16, address & 65535
        if 0x80 <= bank < 0xC0 and word >= 0x8000:
            offset = (bank-0x80)*HALFBANK+word-0x8000
        elif 0x60 <= bank < 0x70:
            offset = 0x200000+address-0x600000
        elif 0xC0 <= bank < 0xD0:
            offset = 0x300000+address-0xC00000
        elif 0xF0 <= bank <= 0xFF:
            offset = address-0xC00000
        else:
            raise ValueError(f'unsupported original CPU ROM mirror {address:06X}')
        spans = [s for s in layout.spans.values() if s.module == module
                 and s.original_offset <= offset < s.original_offset+len(s.payload)]
        if len(spans) != 1:
            raise ValueError(f'unresolved original CPU pointer {address:06X}')
        span = spans[0]
        placement = _placement(layout, module, span.name)
        return placement.cpu+offset-span.original_offset
    return pointer


def world_address_bindings(layout: LevelLayout, module: int) -> dict[str, int]:
    values = {'BSP_PROJECTION_RECIPROCAL_ROM_BANK': _gsu(layout, module, 'BSPDATA')[0]}
    for stem, name in (
        ('WORLD_VERTICES', 'BSP_WORLD_VERTICES'), ('WORLD_FACES', 'BSP_WORLD_FACES'),
        ('WORLD_FACE_PLANES', 'BSP_WORLD_FACE_PLANES'), ('WORLD_NODES', 'BSP_WORLD_NODES'),
        ('WORLD_PLANES', 'BSP_WORLD_PLANES'), ('WORLD_NODE_PARENTS', 'BSP_WORLD_NODE_PARENTS'),
        ('WORLD_SHADING', 'BSP_WORLD_SHADING'),
    ):
        bank, address = _gsu(layout, module, name)
        values[stem+'_ROM_BANK'], values[stem+'_ROM_ADDRESS'] = bank, address
    b0, a0 = _gsu(layout, module, 'BSP_WORLD_INDICES_0')
    b1, a1 = _gsu(layout, module, 'BSP_WORLD_INDICES_1')
    if a0 != a1:
        raise ValueError('world index chunks require one common address base')
    values.update(WORLD_INDICES0_ROM_BANK=b0, WORLD_INDICES1_ROM_BANK=b1, WORLD_INDICES_ROM_ADDRESS=a0)
    bank, address = _gsu(layout, module, 'BSP_WORLD_FACE_OWNERS')
    values.update(WORLD_FACE_OWNERS_ROM_BANK=bank, BSP_WORLD_FACE_OWNERS_ROM_ADDRESS=address)
    for prefix, first_key, base_key in (
        ('BSP_WORLD_TEXCOORD_', 'WORLD_TEXCOORD_FIRST_ROM_BANK', 'WORLD_TEXCOORD_ROM_ADDRESS'),
        ('BSP_WORLD_TEXTURE_', 'BSP_WORLD_TEXTURE_FIRST_GSU_ROM_BANK', None),
        ('BSP_DIVIDE_Q12_RECIPROCAL_', 'GSU_DIVIDE_Q12_RECIPROCAL_FIRST_ROM_BANK', None),
    ):
        chunks = sorted((int(match[1]), name) for (m, name) in layout.placements
            if m == module and (match := re.fullmatch(re.escape(prefix)+r'(\d+)', name)))
        if prefix == "BSP_WORLD_TEXCOORD_" and module in getattr(layout, "world_coordinate_modules", ()):
            continue
        if not chunks and prefix == "BSP_WORLD_TEXTURE_" and any(
                m == module and name.startswith(MATERIAL) for m, name in layout.placements):
            continue
        first = _gsu(layout, module, chunks[0][1])
        for index, name in chunks:
            if _gsu(layout, module, name) != (first[0]+index, first[1]) or first[0]+index >= 64 or first[1] != 0x8000:
                raise ValueError(f'{prefix} readers require consecutive classic banks at $8000')
        values[first_key] = first[0]
        if base_key:
            values[base_key] = first[1]
    head = _placement(layout, module, 'BSP_WORLD_LIGHTMAP_DIRECTORY')
    head_bank, head_address = _gsu(layout, module, 'BSP_WORLD_LIGHTMAP_DIRECTORY')
    tail = layout.placements.get((module, 'BSP_WORLD_LIGHTMAP_DIRECTORY_TAIL'))
    if tail is not None:
        tail_bank, tail_address = _gsu(layout, module, 'BSP_WORLD_LIGHTMAP_DIRECTORY_TAIL')
        if (tail_bank != head_bank or tail_address != head_address+head.size
                or tail_address+tail.size > 65536):
            raise ValueError('split lightmap directory must remain contiguous inside one GSU 64KiB bank')
    return values


def linker_load_bindings(template: str, layout: LevelLayout, module: int) -> dict[str, int]:
    memory = _entries(template, 'MEMORY')
    values = {}
    for name, entry in _entries(template, 'SEGMENTS').items():
        load = _attribute(entry['attrs'], 'load')
        if not load or not re.fullmatch(r'ROM\d+', load):
            continue
        placement = layout.placements.get((module, name))
        if placement is not None:
            address = placement.link
        else:
            # Zero-size/optional source segments retain their native area.
            literal = _attribute(entry['attrs'], 'start') or _attribute(memory[load]['attrs'], 'start')
            if literal is None or not re.fullmatch(INTEGER, literal):
                raise ValueError(f'cannot establish empty segment contract for {name}')
            address = _number(literal)
        values['BSP_ROM_LOAD_'+name] = address
        values['BSP_ROM_LOAD_BANK_'+name] = address >> 16
    return values


def brush_stream_bindings(layout: LevelLayout, module: int, fields: dict[str, int]):
    values = {}
    first = fields['BSP_BRUSH_FRAGMENT_FIRST_BANK']
    for kind in ('DESCRIPTORS', 'VERTICES'):
        index = fields['BSP_BRUSH_FRAGMENT_'+kind+'_FIRST_BANK']-first
        if index < 0:
            raise ValueError('brush stream precedes its fragment family')
        _, address = _gsu(layout, module, f'BSP_BRUSH_FRAGMENTS_{index}')
        values['BSP_BRUSH_FRAGMENT_'+kind+'_ROM_ADDRESS'] = address
    return values


def _replace_scalar(text, name, value):
    # Explicitly named generated expressions may be folded to the derived value.
    pattern = re.compile(r'^([ \t]*'+re.escape(name)+r'[ \t]*=[ \t]*)[^;\r\n]+([ \t]*(?:;[^\r\n]*)?\r?)$', re.M)
    if len(pattern.findall(text)) != 1:
        raise ValueError(f'expected one generated assignment for {name}')
    return pattern.sub(lambda match: match[1]+f'${value:X}'+match[2], text)


def _extra_include(text, mapper, cpu_mapper):
    fields = integer_definitions(text)
    for stem in ('BSP_SKY_PHASE', 'BSP_TURBULENCE_PHASE'):
        bank_name, address_name = stem+'_GSU_ROM_BANK', stem+'_GSU_ROM_ADDRESS'
        if bank_name not in fields:
            continue
        bank, address = mapper(fields[bank_name], fields[address_name])
        updates = {bank_name: bank, address_name: address}
        end_name = stem+'_GSU_ROM_END_ADDRESS'
        if end_name in fields:
            end = address+fields[end_name]-fields[address_name]
            if not 0 <= end <= 65536:
                raise ValueError(f'{stem} table crosses its mapped GSU bank')
            updates[end_name] = end
        cpu_name = stem+'_CPU_ROM_ADDRESS'
        if cpu_name in fields:
            updates[cpu_name] = cpu_mapper(fields[cpu_name])
        text = patch_include_values(text, updates)
    return text


def relocate_phase_assertions(text, *, start, sky_bytes, turbulence_bytes, table_bytes):
    """Keep generated phase label assertions bound to the linked segment."""
    labels = {'QuakeBSPSkyPhases': start, 'QuakeBSPSkyPhasesEnd': start+sky_bytes,
              'QuakeBSPTurbulencePhases': start+sky_bytes,
              'QuakeBSPTurbulenceTableEnd': start+sky_bytes+turbulence_bytes+table_bytes}
    def replace(match):
        return match[1]+f'${labels[match[2]]:06X}'
    pattern = re.compile(r'(\.assert (QuakeBSPSkyPhases(?:End)?|QuakeBSPTurbulencePhases|QuakeBSPTurbulenceTableEnd) = )\$[0-9A-Fa-f]+')
    result, count = pattern.subn(replace, text)
    if count != 2:
        raise ValueError('expected two generated phase address assertions')
    return result


@dataclass(frozen=True)
class ModulePreparation:
    files: dict[str, bytes]
    segment_files: dict[str, Path]
    report: dict


def remaining_address_contracts(example: Path) -> list[dict]:
    """List owned-source location assertions still requiring an explicit contract.

    These are diagnostics, never filtered from the assembler input. Capacity,
    overlap, width and size assertions remain authoritative during assembly.
    """
    requirements = []
    for relative in ('quake.s', 'quake/SkyRenderer.s', 'quake/TurbulenceRenderer.s'):
        path = Path(example)/relative
        if not path.is_file():
            continue
        for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            stripped = line.strip()
            if not stripped.startswith('.assert '):
                continue
            fixed_load = re.search(r'__\w+_LOAD__\s*=\s*\$[A-Fa-f0-9]+', stripped)
            fixed_phase_bank = re.search(r'BSP_(?:SKY|TURBULENCE)_PHASE_GSU_ROM_BANK\s*=\s*\$', stripped)
            old_adjacency = any(phrase in stripped for phrase in (
                'Face-PVS directory must follow aligned PVS2',
                'configured demo track no longer follows face-PVS chunk 3',
                'Lightmap colormaps no longer follow demo timing'))
            if fixed_load or fixed_phase_bank or old_adjacency:
                requirements.append(dict(path=relative, line=number, assertion=stripped))
    return requirements


def compact_texture_files(example, layout, module, files):
    """Apply admitted prefix sizes after pointer relocation, without changing sources."""
    changes = []
    brush_sizes = {}
    for (owner,name), placement in sorted(layout.placements.items()):
        match = re.fullmatch(r'BSP_(WORLD|BRUSH)_TEXTURE_(\d+)',name)
        if owner != module or match is None or placement.size == HALFBANK:
            continue
        if not 0 < placement.size < HALFBANK:
            raise ValueError('compact texture allocation has an invalid extent')
        family,index = match.groups()
        filename = f"QuakeBSP{'World' if family == 'WORLD' else 'Brush'}TexturePixels{index}.bin"
        for prefix in ('Data/',):
            relative = prefix+filename
            path = example/relative
            if not path.is_file():
                continue
            blob = files.get(relative,path.read_bytes())
            if len(blob) != HALFBANK or blob[placement.size:] != b'\xff'*(HALFBANK-placement.size):
                raise ValueError('relocated texture tail no longer matches the admitted FF prefix: '+relative)
            files[relative] = blob[:placement.size]
            changes.append(dict(path=relative,originalBytes=len(blob),retainedBytes=placement.size))
        if family == 'BRUSH':
            brush_sizes[int(index)] = placement.size
    if brush_sizes:
        relative = 'quake/DynamicBrushAssets.s'
        text = (example/relative).read_text(encoding='utf-8')
        for index,size in sorted(brush_sizes.items()):
            old = f'__BSP_BRUSH_TEXTURE_{index}_SIZE__ = BSP_WORLD_ROM_BANK_BYTES'
            if text.count(old) != 1:
                raise ValueError('expected one complete brush texture size assertion')
            text = text.replace(old,f'__BSP_BRUSH_TEXTURE_{index}_SIZE__ = ${size:X}')
        if 3 in brush_sizes:
            old = 'BSP_WORLD_ROM_BANK_BYTES - BSP_BRUSH_LINKED_PVS_OFFSET - BSP_BRUSH_LINKED_PVS_BYTES'
            if text.count(old) != 1:
                raise ValueError('expected one brush-PVS trailing slice')
            text = text.replace(old,f'${brush_sizes[3]:X} - BSP_BRUSH_LINKED_PVS_OFFSET - BSP_BRUSH_LINKED_PVS_BYTES')
            text = text.replace('BSP_BRUSH_LINKED_PVS_OFFSET + BSP_BRUSH_LINKED_PVS_BYTES <= BSP_WORLD_ROM_BANK_BYTES',
                                f'BSP_BRUSH_LINKED_PVS_OFFSET + BSP_BRUSH_LINKED_PVS_BYTES <= ${brush_sizes[3]:X}')
        files[relative] = text.encode('utf-8')
    return changes


def playable_brush_override_slot_mask(data: Path, brush: dict[str, int]) -> int | None:
    """Return exact slot membership when every override fits one word."""
    banks = ((data/f"QuakeBSPBrushRuntime{index}.bin").read_bytes()
             for index in range(brush["BSP_BRUSH_RUNTIME_BANK_COUNT"]))
    overrides = decode_runtime_sections(banks)["VTEX"]
    if len(overrides) != brush["BSP_BRUSH_VTEX_COUNT"] * VISUAL_TEXTURE_RECORD.size:
        raise ValueError("canonical brush override count disagrees with its include")
    slots = {slot for slot, _, _ in VISUAL_TEXTURE_RECORD.iter_unpack(overrides)}
    if any(slot >= 16 for slot in slots):
        return None
    return sum(1 << slot for slot in slots)


def _readonly_quakec_fields(records, descriptors, globals_data, host_globals):
    # The three return words and eight argument vectors, plus host-published
    # globals, can change outside bytecode result and STORE instructions.
    writable = set(range(0, 64, 2))
    writable.update(host_globals)
    for entry, first, size, argc, _, *widths in descriptors:
        if entry < 0x8000:
            writable.update(range(first, first + max(size, sum(widths[:argc])), 2))
    result_ops = set(range(1, 31)) | {44, 46, 47, 48} | set(range(62, 69))
    result_ops.remove(16)              # Explicit trap.
    vectors = {3, 4, 7, 9, 25}
    fields = {}
    for token, _, b, c in records:
        opcode = token // 2
        if opcode in result_ops:
            writable.update(range(c, c + (6 if opcode in vectors else 2), 2))
        if 31 <= opcode <= 36:
            writable.update(range(b, b + (6 if opcode == 32 else 2), 2))
    for index, (token, _, b, _) in enumerate(records):
        if not (48 <= token <= 60 and token % 2 == 0):
            continue
        if b in writable or b % 2 or b + 2 > len(globals_data):
            return {}                 # Keep the live-field handler on every record.
        (field,) = Struct('<H').unpack_from(globals_data, b)
        fields[index] = field
    return fields


_IFNOT_COMPARISONS = {
    **dict.fromkeys((10, 12, 13, 14), 'Equal'),
    **dict.fromkeys((15, 17, 18, 19), 'NotEqual'),
    20: 'LessEqual', 21: 'GreaterEqual', 22: 'Less', 23: 'Greater',
    **dict.fromkeys((44, 46, 47, 48), 'Not'),
    62: 'And', 63: 'Or',
}


def linked_builtin_descriptors(indexed: bytes, count: int) -> bytes:
    """Link the unused first-local word of builtin descriptors, preserving all offsets."""
    table_bytes = 2 * count
    if not 0 < table_bytes <= len(indexed) or (len(indexed) - table_bytes) % 16:
        raise ValueError('invalid indexed QuakeC function extent')
    selectors = {
        1: 'ShotgunMakeVectors', 7: 'ShotgunRandom', 9: 'GruntNormalize',
        12: 'QCVectorLengthBuiltin', 13: 'GruntVectorYaw', 16: 'ShotgunTrace',
        17: 'QCCheckClientBuiltin', 32: 'GruntWalkMove', 44: 'ShotgunAim',
        49: 'GruntChangeYaw', 52: 'ShotgunWriteByte', 56: 'ShotgunWriteCoord',
        67: 'GruntMoveToGoal',
    }
    word = Struct('<H')
    offsets = {value for value, in word.iter_unpack(indexed[:table_bytes])}
    if offsets != set(range(table_bytes, len(indexed), 16)):
        raise ValueError('indexed QuakeC functions do not name their complete descriptor pool')
    result = []
    cursor = 0
    for offset in sorted(offsets):
        entry, = word.unpack_from(indexed, offset)
        if entry <= 0x8000:          # Script PC or invalid descriptor sentinel
            continue
        handler = selectors.get(0x10000 - entry, 'QCGenericBuiltin')
        result.append(f'        .incbin "Data/PlayableQuakeCFunctions.bin", {cursor}, {offset + 2 - cursor}\n')
        result.append(f'        .assert ^{handler} = ^QuakeCInvoke, lderror, "QuakeC builtin escaped its caller bank"\n')
        result.append(f'        .word .loword({handler} - 1)\n')
        cursor = offset + 4
    result.append(f'        .incbin "Data/PlayableQuakeCFunctions.bin", {cursor}, {len(indexed) - cursor}\n')
    return ''.join(result).encode('ascii')


def linked_quakec_code(code: bytes, functions: bytes, globals_data=b'', host_globals=(),
                       *, self_global=None) -> tuple[bytes, dict]:
    """Verify the immutable packed VM graph and emit relocated near targets."""
    statement = Struct('<4H')
    function = Struct('<HHHBB8B')
    if not code or len(code) >= 0x8000 or len(code) % statement.size:
        raise ValueError('linked QuakeC bytecode has an invalid extent')
    if not functions or len(functions) % function.size:
        raise ValueError('linked QuakeC function descriptors have an invalid extent')

    def require_target(value: int) -> None:
        if value % statement.size or not 0 <= value < len(code):
            raise ValueError(f'linked QuakeC target {value:#06x} does not name a record')

    descriptors = tuple(function.iter_unpack(functions))
    records = tuple(statement.iter_unpack(code))
    scripts = [row for row in descriptors if row[0] < 0x8000]
    bounded_locals = all(
        not size or (first % 2 == 0 and size % 2 == 0 and first + size <= len(globals_data))
        for _, first, size, *_ in scripts
    )
    # The native word load sees both the byte count and its padding byte.
    single_scalar = (all(row[4] == 0 for row in scripts)
                     and {row[5] for row in scripts if row[3] == 1} == {2})
    fields = _readonly_quakec_fields(records, descriptors, globals_data, host_globals) if globals_data else {}
    entries = [row[0] for row in scripts]
    for target in entries:
        require_target(target)
    branches = fallthroughs = placeholders = explicit_traps = 0
    terminal = {0, 16, 43, 45, 61, 69}
    lines = []
    for index, (token, a, b, c) in enumerate(records):
        if token == 0xffff:
            placeholders += 1
            handler = 'QCOpUnrecorded'
        else:
            if token & 1 or token > 2 * 69:
                raise ValueError(f'unknown packed QuakeC token {token:#06x}')
            opcode = token // 2
            if opcode in (49, 50, 61):
                require_target(a if opcode == 61 else b)
                branches += 1
            if opcode not in terminal:
                require_target((index + 1) * statement.size)
                fallthroughs += 1
            if opcode in (16, 45):
                explicit_traps += 1
            handler = f'QCLinkedOp{opcode}'
            if index in fields and a == self_global:
                handler = {25: 'QCLoadSelfVector', 30: 'QCAddressSelf'}.get(opcode, 'QCLoadSelf')
            elif opcode == 32 and b in (8, 14, 20, 26, 32):
                handler = f'QCStoreVectorParm{(b - 8) // 6}'
            elif (opcode in _IFNOT_COMPARISONS and c % 2 == 0 and c + 2 <= len(globals_data)
                  and records[index + 1][:2] == (50 * 2, c)):
                # The ordinary IFNOT remains a valid direct jump or function entry.
                # Only the preceding producer can forward the value it just stored.
                handler = 'QCIfNot' + _IFNOT_COMPARISONS[opcode]
        b = fields.get(index, b)
        lines.append(f'        .word .loword({handler}), ${a:04X}, ${b:04X}, ${c:04X}\n')
    return ''.join(lines).encode('ascii'), dict(records=len(lines), nativeEntries=len(entries),
        branches=branches, fallthroughs=fallthroughs, placeholders=placeholders,
        explicitTraps=explicit_traps, literalFields=len(fields), boundedLocals=bounded_locals,
        singleScalarArgument=single_scalar)


def prepare_module_files(example: Path, layout: LevelLayout, module: int,
                         bins_directory: Path, *, tape_boot=None) -> ModulePreparation:
    started = time.monotonic()
    example = Path(example)
    if (example/'Data/PlayableLayout.i').exists():
        raise ValueError('module Data is already relocated; restage original receipt-bound inputs before preparing again')
    template = (example/'Map.cfg').read_text(encoding='utf-8')
    material_plan = getattr(layout, 'material_plans', {}).get(module)
    if material_plan is not None:
        template = declare_material_segments(template, material_plan)
    linker, paths = rewrite_linker_configuration(template, layout, module, bins_directory)
    mapper = lambda bank, address: layout.relocate(module, bank, address)
    cpu_mapper = cpu_pointer_mapper(layout, module)
    sprite_mapper = pixel_mapper(layout, module)
    visibility_stream = getattr(layout, 'visibility_streams', {}).get(module)
    options = dict(alias_pixel_mapper=sprite_mapper, stream_world_visibility=visibility_stream is not None,
                   stream_world_coordinates=module in getattr(layout, "world_coordinate_modules", ()))
    lightmap_plan = getattr(layout, 'world_lightmap_plans', {}).get(module)
    if lightmap_plan is not None:
        unpack_bank = _gsu(layout, module, 'GSU_LIGHTMAP_UNPACK_ROM_CODE')[0]
        if _gsu(layout, module, 'F3_GSU_LIGHTMAP_UNPACK_ROM_CODE')[0] != unpack_bank:
            raise ValueError("X2 and X3 lightmap helpers must share their executable bank")
        options['world_lightmap_unpack_bank'] = unpack_bank
    derived = relocate_data(example/'Data', mapper, cpu_mapper, **options)
    files = {'Map.cfg': linker.encode('utf-8'),
             **{'Data/'+name: value for name, value in derived.files.items()}}
    files['Data/' + WORLD_NODES_FILE] = inline_axial_node_planes(
        (example/'Data'/WORLD_NODES_FILE).read_bytes(),
        (example/'Data'/WORLD_PLANES_FILE).read_bytes(),
    )
    files.update(stream_files(layout, module))
    texture_compaction = compact_texture_files(example,layout,module,files)
    structural_compaction = compact_brush_structure_files(example,layout,module,files)
    empty_alias = compact_empty_alias_files(example,layout,module,files)
    if material_plan is not None:
        material_files, _ = derived_material_files(example, layout, material_plan, files)
        files.update(material_files)
    # Regenerate exact linker assertions from declared alias segment IDs;
    # CPU runtime mirrors and linker LOAD addresses are different namespaces.
    for relative in ('Data/QuakeBSPAliasAssets.s',):
        if not (example/relative).is_file():
            continue
        text = files.get(relative, (example/relative).read_bytes()).decode('utf-8')
        def alias_assertion(match):
            address = _placement(layout, module, 'BSP_ALIAS_'+match[2]).link
            return match[1]+f'${address:06X}'
        text = re.sub(r'(\.assert __BSP_ALIAS_(\d+)_LOAD__ = )\$[0-9A-Fa-f]+', alias_assertion, text)
        files[relative] = text.encode('utf-8')
    for relative in ('Data/QuakeBSPSkyAssets.i', 'Data/QuakeBSPTurbulenceAssets.i'):
        if (example/relative).is_file():
            text = files.get(relative, (example/relative).read_bytes()).decode('utf-8')
            files[relative] = _extra_include(text, mapper, cpu_mapper).encode('utf-8')
    sky = integer_definitions(files['Data/QuakeBSPSkyAssets.i'].decode('utf-8'))
    turbulence = integer_definitions(files['Data/QuakeBSPTurbulenceAssets.i'].decode('utf-8'))
    for relative in ('Data/QuakeBSPSkyAssets.s', 'Data/QuakeBSPTurbulenceAssets.s'):
        text = (example/relative).read_text(encoding='utf-8')
        files[relative] = relocate_phase_assertions(text,
            start=_placement(layout, module, 'BSP_DEMO_TIMING').link,
            sky_bytes=sky['BSP_SKY_PHASE_BYTES'], turbulence_bytes=turbulence['BSP_TURBULENCE_PHASE_BYTES'],
            table_bytes=turbulence['BSP_TURBULENCE_TABLE_BYTES']).encode('utf-8')
    empty_composed = getattr(layout, 'empty_composed', False)
    relative = 'Data/QuakeBSPComposedCache.i'
    if not empty_composed and (example/relative).is_file():
        text = (example/relative).read_text(encoding='utf-8')
        fields = integer_definitions(text)
        bank, address = _gsu(layout, module, 'BSP_COMPOSED_DIRECTORY')
        for name, value in {
            'BSP_COMPOSED_DIRECTORY_PHYSICAL_BANK': _placement(layout, module, 'BSP_COMPOSED_DIRECTORY').offset//HALFBANK,
            'BSP_COMPOSED_DIRECTORY_GSU_ROM_BANK': bank,
            'BSP_COMPOSED_DIRECTORY_GSU_ROM_ADDRESS': address,
            'BSP_COMPOSED_DESCRIPTOR_GSU_ROM_ADDRESS': address+fields['BSP_COMPOSED_CACHE_FACE_DIRECTORY_BYTES'],
        }.items():
            text = _replace_scalar(text, name, value)
        files[relative] = text.encode('utf-8')
    for relative in ('Data/QuakeBSPComposedCacheAssets.s',):
        if not empty_composed and (example/relative).is_file():
            text = (example/relative).read_text(encoding='utf-8')
            text = re.sub(r'(\.assert __BSP_COMPOSED_DIRECTORY_LOAD__ = )\$[0-9A-Fa-f]+',
                r'\g<1>BSP_ROM_LOAD_BSP_COMPOSED_DIRECTORY', text)
            old = '.assert __BSP_COMPOSED_DIRECTORY_LOAD__ >= __GSU_SKY_ROM_CODE_LOAD__ + __GSU_SKY_ROM_CODE_SIZE__'
            if text.count(old) != 1:
                raise ValueError('expected one generated composed/sky overlap assertion')
            text = text.replace(old, old+' .or (__BSP_COMPOSED_DIRECTORY_LOAD__ + __BSP_COMPOSED_DIRECTORY_SIZE__ <= __GSU_SKY_ROM_CODE_LOAD__)')
            files[relative] = text.encode('utf-8')
    values = linker_load_bindings(template, layout, module)
    if (MAP_NAMES[module] == 'e1m3'
            and (empty_alias or {}).get('schema') == 'quake-e1m3-ambient-alias-prefix-v1'):
        # Asset compaction has proved an immutable fixed-facing gold key.
        values['PLAYABLE_RESIDENT_FIXED_ALIAS'] = 1
    if module in getattr(layout, 'indexed_quakec', ()):
        values['PLAYABLE_INDEXED_QUAKEC_FUNCTIONS'] = 1
        files['Data/PlayableQuakeCFunctions.bin'] = layout.indexed_quakec[module]
    if module in getattr(layout, 'face_owner_formats', {}):
        bias, header = layout.face_owner_formats[module]
        values['PLAYABLE_FACE_OWNER_BIAS'] = bias & 0xffff
        values['PLAYABLE_FACE_OWNER_HEADER'] = header
        files['Data/QuakeBSPWorldFaceOwners.bin'] = layout.spans[module, 'BSP_WORLD_FACE_OWNERS'].payload
    if getattr(layout, 'compact_q12_reciprocals', False):
        values['PLAYABLE_COMPACT_Q12_RECIPROCALS'] = 1
        for index in (1, 2):
            table = layout.spans[module, f'BSP_DIVIDE_Q12_RECIPROCAL_{index}']
            files[f'Data/QuakeBSPDivideQ12Compact{index}.bin'] = table.payload
    if empty_composed:
        values['PLAYABLE_EMPTY_COMPOSED'] = 1
        if MAP_NAMES[module] in ('e1m2', 'e1m3'):
            values['PLAYABLE_SHORT_LIGHTMAP_CARRY'] = 1
    if hasattr(layout, "weapon_obj"):
        values["PLAYABLE_WEAPON_OBJ"] = 1
    if hasattr(layout, "textureless_palettes"):
        palette, rows = layout.textureless_palettes[module]
        files["Data/QuakeBSPPlayableTextureless.bin"] = palette + rows
        values["PLAYABLE_TEXTURELESS_WHITE"] = rows[0]
    walk_resume = layout.spans.get((module, "BSP_CPU_WALK_RESUME"))
    if walk_resume is not None:
        files["Data/PlayableWalkResume.bin"] = walk_resume.payload
        values["PLAYABLE_E1M1_WALK_RESUME_BYTES"] = len(walk_resume.payload)
    values.update(world_address_bindings(layout, module))
    for stem, name in (('SKY', 'QuakeBSPSkyAssets.i'), ('TURBULENCE', 'QuakeBSPTurbulenceAssets.i')):
        phase = integer_definitions(files['Data/'+name].decode('utf-8'))
        values['BSP_'+stem+'_PHASE_EXPECTED_ROM_BANK'] = phase['BSP_'+stem+'_PHASE_GSU_ROM_BANK']
    source_brush = integer_definitions((example/'Data/QuakeBSPBrushAssets.i').read_text(encoding='utf-8'))
    values.update(brush_stream_bindings(layout, module, source_brush))
    if override_mask := playable_brush_override_slot_mask(example/"Data", source_brush):
        values["PLAYABLE_BRUSH_OVERRIDE_SLOT_MASK"] = override_mask
    values['BSP_BRUSH_LINKED_PVS_SOURCE_OFFSET'] = source_brush['BSP_BRUSH_PVS_DIRECTORY_ADDRESS'] - 0x8000
    values['BSP_GSU_ROM2_BANK'] = _gsu(layout, module, 'GSU_AUX_CODE')[0]
    values['BSP_GSU_ROM3_BANK'] = _gsu(layout, module, 'GSU_TEXTURE_GENERAL_ROM_CODE')[0]
    values.update(PLAYABLE_MAP_ID=module, PLAYABLE_AXIAL_NODE_RECORDS=1,
                  BSP_COLLISION_CPU_ROM_BASE=_placement(layout, module, 'BSP_COLLISION_PACKED_0').cpu)
    if MAP_NAMES[module] == 'e1m1':
        values['PLAYABLE_LARGE_VERTEX_PACKET'] = 1
        values['PLAYABLE_E1M1_MOVING_PLANE_ADD'] = 1
        values['PLAYABLE_E1M1_LAZY_QC_OPERANDS'] = 1
        values['PLAYABLE_E1M1_LINKED_QC_CODE'] = 1
        if module in getattr(layout, 'indexed_quakec', ()):
            values['PLAYABLE_E1M1_LINKED_BUILTINS'] = 1
            files['Data/PlayableQuakeCBuiltins.i'] = linked_builtin_descriptors(
                layout.indexed_quakec[module], source_brush['QC_FUNCTION_COUNT'])
        code = _placement(layout, module, 'BSP_QUAKEC')
        bytecode = _placement(layout, module, 'BSP_QUAKEC_BYTECODE')
        if code.link >> 16 == bytecode.link >> 16:
            values['PLAYABLE_E1M1_VM_PBR_DISPATCH'] = 1
        qc_data = example / 'Data'
        host_vectors = {
            'QC_GLOBAL_FORWARD', 'QC_GLOBAL_UP', 'QC_GLOBAL_RIGHT',
            'QC_GLOBAL_TRACE_ENDPOS', 'QC_GLOBAL_TRACE_NORMAL',
        }
        host_globals = [offset + width
                        for name, offset in source_brush.items() if name.startswith('QC_GLOBAL_')
                        for width in range(0, 6 if name in host_vectors else 2, 2)]
        files['Data/PlayableQuakeCCode.i'], vm = linked_quakec_code(
            (qc_data / 'QuakeBSPQuakeCCode.bin').read_bytes(),
            (qc_data / 'QuakeBSPQuakeCFunctions.bin').read_bytes(),
            (qc_data / 'QuakeBSPQuakeCGlobals.bin').read_bytes(),
            host_globals, self_global=source_brush['QC_GLOBAL_SELF'])
        if vm['literalFields']:
            values['PLAYABLE_E1M1_LINKED_QC_FIELDS'] = 1
        if vm['boundedLocals']:
            values['PLAYABLE_E1M1_BOUNDED_QC_LOCALS'] = 1
        if vm['singleScalarArgument']:
            values['PLAYABLE_E1M1_SINGLE_SCALAR_ARG'] = 1
        values['PLAYABLE_E1M1_FOOTING'] = 1
    if MAP_NAMES[module] in ('e1m2', 'e1m3', 'e1m4'):
        values['PLAYABLE_PACKET_VIEW_REUSE'] = 1
    if MAP_NAMES[module] in ('e1m2', 'e1m4'):
        values['PLAYABLE_PACKET_SCREEN_REUSE'] = 1
    values.update(integer_definitions(native_constants(layout.cpu_module_count, tape_boot=tape_boot)))
    include = ['; Derived address contract for one independently linked playable map.',
        '.include "Data/QuakeBSPPlayableSpriteStream.i"',
        '; Pointer-bearing Data was relocated before this module was assembled.',
        '.ifndef __QUAKE_PLAYABLE_LAYOUT_I__', '__QUAKE_PLAYABLE_LAYOUT_I__ = 1']
    if visibility_stream is not None:
        plan, offset = visibility_stream
        files['Data/QuakeBSPPlayableVisibility.i'] = plan.include(offset)
        include.append('.include "Data/QuakeBSPPlayableVisibility.i"')
    if options['stream_world_coordinates']:
        from snes_tooling.quake.quake_playable_world_coordinates import WORLD_FACES_FILE, coordinate_include
        coordinates = coordinate_include(layout, module)
        affine = getattr(layout, 'world_affine_uv', {}).get(module)
        if affine is not None:
            coordinates += affine.assembly()
            if affine.descriptor_bytes:
                bank, address = gsu_address(layout.affine_descriptor_offsets[module])
                values.update(WORLD_AFFINE_DESCRIPTOR_ROM_BANK=bank,
                              WORLD_AFFINE_DESCRIPTOR_ROM_ADDRESS=address)
            raw_contours = getattr(layout, 'raw_world_contours', {}).get(module)
            if raw_contours is not None:
                from snes_tooling.quake.quake_playable_raw_contours import RAW_CONTOUR_MARKER
                bank, address = gsu_address(raw_contours.directory_offset)
                values.update(WORLD_RAW_CONTOUR_DIRECTORY_BANK=bank,
                              WORLD_RAW_CONTOUR_DIRECTORY_ADDRESS=address,
                              WORLD_RAW_CONTOUR_MARKER=RAW_CONTOUR_MARKER)
            faces = raw_contours.faces if raw_contours is not None else affine.faces
            files['Data/' + WORLD_FACES_FILE] = inline_axial_face_flags(
                faces, (example/'Data'/WORLD_FACE_PLANES_FILE).read_bytes(),
                mode_mask=affine.mode_mask, count_mask=affine.count_mask)
            values['PLAYABLE_AXIAL_FACE_FLAGS'] = 1
        files['Data/QuakeBSPPlayableWorldCoordinates.i'] = coordinates
        include.append('.include "Data/QuakeBSPPlayableWorldCoordinates.i"')
    if MAP_NAMES[module] == 'e1m1':
        values['PLAYABLE_RECTANGULAR_POT_SAMPLER'] = 1
        # Resident world and packed brush samples both decode to $C0..$FF.
        values['PLAYABLE_SIGNED_LIGHTMAP_INTERPOLATION'] = 1
        values['PLAYABLE_LIGHTMAP_ZERO_T'] = 1
    if empty_composed and MAP_NAMES[module] != 'start':
        values['PLAYABLE_LAZY_WORLD_LIGHTMAP'] = 1
    if lightmap_plan is not None:
        if MAP_NAMES[module] == 'e1m2':
            values['PLAYABLE_SAME_T_LIGHTMAP_BLOCK'] = 1
        # Both the streamed world grids and packed brush grids decode to $C0–$FF.
        if MAP_NAMES[module] in ('e1m3', 'e1m4'):
            values['PLAYABLE_SIGNED_LIGHTMAP_INTERPOLATION'] = 1
            values['PLAYABLE_LIGHTMAP_ZERO_T'] = 1
        offsets = []
        for name, chunk in zip(WORLD_LIGHTMAP_SAMPLES[:len(lightmap_plan.chunks)], lightmap_plan.chunks, strict=True):
            placement = layout.placements.get((module, name))
            if placement and (placement.storage != 'msu' or layout.spans[module, name].payload != chunk):
                raise ValueError("world lightmap carrier disagrees with its canonical MSU plan")
            offsets.append(placement.offset if placement else None)
        files['Data/QuakeBSPPlayableWorldLightmap.i'] = lightmap_plan.include(tuple(offsets))
        include.append('.include "Data/QuakeBSPPlayableWorldLightmap.i"')
        resident = getattr(layout, 'resident_world_lightmaps', {}).get(module)
        if resident is not None:
            plan, offset = resident
            directory = 'Data/QuakeBSPWorldLightmapDirectory.bin'
            files[directory] = plan.relocate((example / directory).read_bytes(), *gsu_address(offset))
            values['PLAYABLE_RESIDENT_WORLD_LIGHTMAPS'] = 1
    if module in getattr(layout, "intermission", {}):
        values["INTERMISSION_SEEK"] = 64 + 2 * layout.intermission[module][1]
    if (module, "BSP_CPU_X3_WEAPON_VIEW") in layout.placements:
        _, offset, first_pose, pose_count = layout.x3_software_weapon
        values.update(PLAYABLE_X3_SOFTWARE_WEAPON=1, X3_WEAPON_SEEK=64 + 2*offset,
                      X3_WEAPON_FIRST_POSE=first_pose, X3_WEAPON_POSE_COUNT=pose_count)
    switched = getattr(layout, "switchable_lights", {}).get(module)
    if switched:
        lights, colors, offset = switched
        values["PLAYABLE_SWITCHED_LIGHTS"] = 1
        values["SWITCHED_LIGHT_STRIDE"] = lights.stride
        values["SWITCHED_COLOR_SEEK"] = 64 + 2 * offset
        values["SWITCHED_GRID_SEEK"] = 64 + 2 * (offset + len(colors))
        values["SWITCHED_GRID_DIRECTORY"] = cpu_address(layout.switched_grid_directory[module])
    scene_values = integer_definitions(files['Data/QuakeBSPScene.i'].decode('utf-8'))
    for name, value in sorted(values.items()):
        if name in scene_values:
            if scene_values[name] != value:
                raise ValueError(f'{name}: layout {value:#x} disagrees with relocated scene {scene_values[name]:#x}')
            include.append(f'.assert {name} = ${value:X}, lderror, "Playable layout disagrees with relocated scene: {name}"')
        else:
            include.append(f'{name} = ${value:X}')
    include += ['.endif', '']
    files['Data/PlayableLayout.i'] = '\n'.join(include).encode('ascii')
    for suffix in ('s', 'sgs', 's700'):
        if (example/f'quake.{suffix}').is_file():
            files[f'quake-playable.{suffix}'] = (
                '; Derived playable module; conventional live renderer.\n'
                + ('.include "Data/PlayableLayout.i"\n' if suffix != 's700' else '')
                +
                f'.include "quake.{suffix}"\n').encode('ascii')
    return ModulePreparation(files, paths, dict(schema='quake-playable-link-preparation-v1',
        module=module, files=len(files), separateSegmentFiles=len(paths), relocation=derived.report,
        materialPool=material_plan.report() if material_plan is not None else None,
        emptyAliasCompaction=empty_alias,
        textureCompaction=texture_compaction,
        structuralCompaction=structural_compaction,
        remainingLocationContracts=remaining_address_contracts(example),
        cpuBankCopyBytes=HALFBANK, nativeHeaderStart=0x80FFB0+module*0x10000,
        nativeVectorsStart=0x80FFE0+module*0x10000,
        elapsedSeconds=round(time.monotonic()-started, 6)))
