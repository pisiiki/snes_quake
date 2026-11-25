"""Schema-proven QBSA/QBSF FF tails, with conservative decoder guards.

This preserves every declared section, control table, pool and embedded PVS
row. Source files and classic vertex-stream offsets are never rewritten.
"""
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import re
import struct
import time

from snes_tooling.quake.quake_playable_layout import gsu_address, gsu_offset
from snes_tooling.quake.quake_playable_relocation import BRUSH_HEADER, BRUSH_SECTION, FRAGMENT_HEADER

BANK_BYTES = 32768
GUARD_BYTES = 32
VARIANT = struct.Struct('<BBhhhHHhhhHHH')
BUCKET = struct.Struct('<HHBBH')
FRAGMENT = struct.Struct('<HIBB')
FAMILIES = (("BSP_BRUSH_RUNTIME_", "QuakeBSPBrushRuntime"),
            ("BSP_BRUSH_FRAGMENTS_", "QuakeBSPBrushFragments"))


def _need(valid, message):
    if not valid:
        raise ValueError(message)


def _identity(payload):
    return dict(bytes=len(payload), sha256=sha256(payload).hexdigest())


def structural_prefixes(directory, *, guard_bytes=GUARD_BYTES):
    """Return admitted filename->prefix sizes and complete original-byte proof."""
    started = time.monotonic()
    directory = Path(directory)
    _need(type(guard_bytes) is int and guard_bytes >= GUARD_BYTES,
          'structural tails require at least the reviewed thirty-two-byte guard')
    _need(not (directory/'PlayableLayout.i').exists(), 'structural tails require unrelocated source Data')
    metadata_payload = (directory/'QuakeBSPBrushAssets.json').read_bytes()
    metadata = json.loads(metadata_payload)
    _need(metadata.get('schema') == 'quake-bsp-brush-assets' and metadata.get('version') == 2
          and 'relocation' not in metadata, 'structural tails require original QBSA v2 metadata')
    runtime, fragments = metadata['runtime'], metadata['worldComposition']['fragments']
    inputs = {'QuakeBSPBrushAssets.json': _identity(metadata_payload)}
    raw, ranges, banks, family_by_name = {}, {}, {}, {}
    for prefix, stem, section in ((*FAMILIES[0], runtime), (*FAMILIES[1], fragments)):
        first, count = section['firstBank'], section['bankCount']
        _need(type(first) is int and type(count) is int and 0 <= first < 63 and 0 < count <= 63-first,
              'structural source family has invalid classic bank bounds')
        for index in range(count):
            name = f'{stem}{index}.bin'
            payload = (directory/name).read_bytes()
            _need(len(payload) == BANK_BYTES and _identity(payload) == metadata['outputs'][name],
                  'structural source differs from its original metadata output: '+name)
            if stem == 'QuakeBSPBrushFragments':
                _need(_identity(payload) == fragments['outputs'][name], 'fragment output identity disagrees')
            _need(first+index not in banks, 'structural source families overlap')
            raw[name], ranges[name], banks[first+index] = payload, [], name
            family_by_name[name] = (prefix, index, first)
            inputs[name] = _identity(payload)

    def protect(bank, address, size, label, *, optional=False):
        if bank not in banks:
            _need(optional, 'structural live range escapes its bank family: '+label)
            return b''
        _need(type(address) is int and type(size) is int and 0x8000 <= address < 0x10000
              and 0 <= size <= BANK_BYTES-(address-0x8000), 'structural live range escapes its bank: '+label)
        name, offset = banks[bank], address-0x8000
        ranges[name].append((offset, offset+size, label))
        return raw[name][offset:offset+size]

    runtime_names = [f'QuakeBSPBrushRuntime{i}.bin' for i in range(runtime['bankCount'])]
    header = BRUSH_HEADER.unpack_from(raw[runtime_names[0]])
    _need(header[0] == b'QBSA' and header[1] == 2 and header[2] == runtime['bankCount']
          and header[9] == runtime['sectionCount'] == len(runtime['sections'])
          and runtime['headerBytes'] == BRUSH_HEADER.size
          and runtime['sectionRecordBytes'] == BRUSH_SECTION.size, 'QBSA header/directory metadata disagrees')
    directory_end = BRUSH_HEADER.size + BRUSH_SECTION.size*len(runtime['sections'])
    protect(runtime['firstBank'], 0x8000, directory_end, 'QBSA header and directory')
    seen = set()
    for index, row in enumerate(runtime['sections']):
        entry = BRUSH_SECTION.unpack_from(raw[runtime_names[0]], BRUSH_HEADER.size+index*BRUSH_SECTION.size)
        expected = (row['name'].encode().ljust(8, b'\0'), row['bank'], row['address'], row['bytes'],
                    row['recordBytes'], row['recordCount'])
        _need(entry == expected and row['name'] not in seen, 'QBSA section directory differs from metadata')
        seen.add(row['name'])
        _need(row['bank']-runtime['firstBank'] in range(runtime['bankCount']), 'QBSA section leaves runtime storage')
        _need(not row['recordBytes'] or row['recordBytes']*row['recordCount'] == row['bytes'],
              'QBSA section record count differs from its byte extent')
        payload = protect(row['bank'], row['address'], row['bytes'], 'QBSA '+row['name'])
        _need(sha256(payload).hexdigest() == row['sha256'], 'QBSA section payload hash differs: '+row['name'])
    _need(header[3] == runtime['logicalSectionBytes'] == sum(row['bytes'] for row in runtime['sections']),
          'QBSA logical section byte count differs')

    pvs = metadata['worldComposition']['leafPvs']
    protect(pvs['directoryBank'], pvs['directoryAddress'], pvs['directoryBytes'], 'brush PVS directory', optional=True)
    for index, row in enumerate(pvs.get('rowStorage', ())):
        payload = protect(row['bank'], 0x8000+row['offset'], row['bytes'], 'brush PVS RLE '+str(index), optional=True)
        if row['bank'] in banks and 'sha256' in row:
            _need(sha256(payload).hexdigest() == row['sha256'], 'embedded brush PVS row hash differs')
    for index, name in enumerate(runtime_names):
        _need(max((stop for _, stop, _ in ranges[name]), default=0) == runtime['usedBytesByBank'][index],
              'QBSA declared bank use has unattributed live storage: '+name)

    roles = fragments['bankRoles']
    control, descriptors, vertices = (roles[name] for name in ('control', 'descriptors', 'vertices'))
    control_count = fragments['controlBankCount']
    _need(fragments['version'] == 4 and fragments['headerBytes'] == FRAGMENT_HEADER.size
          and control['bankCount'] == control_count and control['firstBank'] == fragments['firstBank']
          and descriptors['firstBank'] == fragments['firstBank']+control_count
          and vertices['firstBank'] == descriptors['firstBank']+descriptors['bankCount']
          and fragments['bankCount'] == control_count+descriptors['bankCount']+vertices['bankCount']
          and fragments['lastBank'] == fragments['firstBank']+fragments['bankCount']-1,
          'QBSF role layout differs from its schema')
    head = FRAGMENT_HEADER.unpack_from(raw['QuakeBSPBrushFragments0.bin'])
    expected_head = (b'QBSF', 4, fragments['bankCount'], descriptors['firstBank']-fragments['firstBank'], descriptors['bankCount'],
                     vertices['firstBank']-fragments['firstBank'], vertices['bankCount'], fragments['variantCount'], fragments['bucketCount'],
                     fragments['fragmentCount'], fragments['vertexOccurrenceCount'], fragments['faceMaterialCount'],
                     *(control[key]['bankIndex']*65536+control[key]['offset'] for key in ('variants', 'faces', 'buckets')),
                     fragments['controlUsedBytes'])
    _need(head == expected_head, 'QBSF header differs from original role/count metadata')
    protect(fragments['firstBank'], 0x8000, FRAGMENT_HEADER.size, 'QBSF header')
    tables = {}
    for name, count, width, hash_name in (
        ('variants', fragments['variantCount'], VARIANT.size, 'variants'),
        ('faces', fragments['faceMaterialCount'], 16, 'faceMaterials'),
        ('buckets', fragments['bucketCount'], BUCKET.size, 'buckets')):
        location = control[name]
        _need(location['bank'] == fragments['firstBank']+location['bankIndex']
              and location['address'] == 0x8000+location['offset'] and 0 <= location['bankIndex'] < control_count,
              'QBSF control table has inconsistent location fields')
        tables[name] = protect(location['bank'], location['address'], count*width, 'QBSF '+name)
        _need(sha256(tables[name]).hexdigest() == fragments['directoryHashes'][hash_name],
              'QBSF control table hash differs: '+name)
    _need(FRAGMENT_HEADER.size+sum(map(len, tables.values())) == fragments['controlUsedBytes']
          == control['logicalBytes'], 'QBSF control logical byte count differs')

    def pool(role, count, width, label):
        size = role['bytes']
        _need(size == count*width and role['bankCount'] == max(1, (size+BANK_BYTES-1)//BANK_BYTES),
              'QBSF pool size/count differs: '+label)
        parts = []
        for index in range(role['bankCount']):
            used = max(0, min(BANK_BYTES, size-index*BANK_BYTES))
            parts.append(protect(role['firstBank']+index, 0x8000, used, 'QBSF '+label))
        payload = b''.join(parts)
        _need(sha256(payload).hexdigest() == role['sha256'], 'QBSF pool hash differs: '+label)
        return payload

    descriptor_data = pool(descriptors, fragments['fragmentCount'], FRAGMENT.size, 'descriptors')
    pool(vertices, fragments['vertexOccurrenceCount'], 4, 'vertices')
    for row in VARIANT.iter_unpack(tables['variants']):
        _need(row[5]+row[6] <= fragments['bucketCount'], 'QBSF variant escapes its bucket table')
    for _, first, count, _, _ in BUCKET.iter_unpack(tables['buckets']):
        _need(first+count <= fragments['fragmentCount'], 'QBSF bucket escapes its descriptor pool')
    for face, first, count, _ in FRAGMENT.iter_unpack(descriptor_data):
        _need(face < fragments['faceMaterialCount'] and first+count <= fragments['vertexOccurrenceCount'],
              'QBSF descriptor escapes its face or vertex pool')

    prefixes, records = {}, []
    for name, payload in raw.items():
        used = max((stop for _, stop, _ in ranges[name]), default=0)
        kept = min(BANK_BYTES, max(1, used+guard_bytes))
        _need(payload[kept:] == b'\xff'*(BANK_BYTES-kept), 'structural suffix contains unproven non-FF bytes: '+name)
        _need(payload[:kept]+b'\xff'*(BANK_BYTES-kept) == payload, 'structural original-byte recovery failed: '+name)
        prefixes[name] = kept
        records.append(dict(file=name, semanticBytes=used, retainedBytes=kept, savedBytes=BANK_BYTES-kept,
                            ranges=ranges[name], originalSha256=sha256(payload).hexdigest(),
                            retainedSha256=sha256(payload[:kept]).hexdigest(), restoredSha256=sha256(payload).hexdigest()))
    return prefixes, dict(schema='quake-playable-structural-compaction-v1', guardBytes=guard_bytes,
                          chunks=records, inputs=inputs, savedBytes=sum(row['savedBytes'] for row in records),
                          elapsedSeconds=round(time.monotonic()-started, 6))


def compact_brush_structure_spans(directory, spans, *, module):
    """Admit only complete canonical source spans; preserve all relative offsets."""
    spans = list(spans)
    matching = {span.name: span for span in spans if span.module == module
                and any(re.fullmatch(re.escape(prefix)+r'\d+', span.name) for prefix, _ in FAMILIES)}
    if not matching:
        return spans, dict(schema='quake-playable-structural-compaction-v1', module=module, savedBytes=0, chunks=[])
    sizes, report = structural_prefixes(directory)
    metadata = json.loads((Path(directory)/'QuakeBSPBrushAssets.json').read_bytes())
    changes = {}
    for prefix, stem, first in ((*FAMILIES[0], metadata['runtime']['firstBank']),
                                (*FAMILIES[1], metadata['worldComposition']['fragments']['firstBank'])):
        names = sorted((name for name in sizes if name.startswith(stem)), key=lambda name: int(name[len(stem):-4]))
        for filename in names:
            index = int(filename[len(stem):-4])
            name = prefix+str(index)
            _need(name in matching, 'structural source segment is missing: '+name)
            span = matching[name]
            normal = (Path(directory)/filename).read_bytes()
            _need(span.original_offset == gsu_offset(first+index, 0x8000)
                  and len(span.payload) == BANK_BYTES and span.payload == normal,
                  'structural linked image differs from its canonical source: '+name)
            changes[span.key] = replace(span, payload=span.payload[:sizes[filename]])
    _need(len(changes) == len(matching), 'structural segment count differs from source metadata')
    report['module'] = module
    return [changes.get(span.key, span) for span in spans], report


def compact_brush_structure_files(example, layout, module, files):
    """Trim admitted relocated prefixes and retain exact linker size assertions."""
    example = Path(example)
    metadata = json.loads((example/'Data/QuakeBSPBrushAssets.json').read_bytes())
    fragments = metadata['worldComposition']['fragments']
    for role_name in ('descriptors', 'vertices'):
        role = fragments['bankRoles'][role_name]
        first = role['firstBank']-fragments['firstBank']
        placements = [layout.placements[(module, f'BSP_BRUSH_FRAGMENTS_{first+i}')]
                      for i in range(role['bankCount'])]
        pointers = [gsu_address(place.offset) for place in placements]
        if role_name == 'vertices' or len(pointers) > 1:
            _need(all(bank == pointers[0][0]+i and address == 0x8000
                      for i, (bank, address) in enumerate(pointers)),
                  'structural classic pool lost its consecutive $8000 stream contract')
    changes, sizes = [], {}
    for (owner, name), placement in sorted(layout.placements.items()):
        if owner != module:
            continue
        for prefix, stem in FAMILIES:
            if not (match := re.fullmatch(re.escape(prefix)+r'(\d+)', name)):
                continue
            _need(0 < placement.size <= BANK_BYTES, 'structural allocation has an invalid prefix extent')
            if placement.size == BANK_BYTES:
                break
            filename = stem+match[1]+'.bin'
            for folder in ('Data/',):
                relative = folder+filename
                path = example/relative
                if not path.is_file():
                    continue
                blob = files.get(relative, path.read_bytes())
                _need(len(blob) == BANK_BYTES and blob[placement.size:] == b'\xff'*(BANK_BYTES-placement.size),
                      'relocated structural suffix is no longer the admitted FF tail: '+relative)
                files[relative] = blob[:placement.size]
                changes.append(dict(path=relative, originalBytes=len(blob), retainedBytes=placement.size))
            sizes[name] = placement.size
            break
    if sizes:
        relative = 'quake/DynamicBrushAssets.s'
        text = files.get(relative, (example/relative).read_bytes())
        text = text.decode('utf-8') if isinstance(text, bytes) else text
        for name, size in sizes.items():
            old = f'__{name}_SIZE__ = BSP_WORLD_ROM_BANK_BYTES'
            _need(text.count(old) == 1, 'expected one exact structural source size assertion: '+name)
            text = text.replace(old, f'__{name}_SIZE__ = ${size:X}')
        files[relative] = text.encode('utf-8')
    return dict(schema='quake-playable-structural-link-compaction-v1', changes=changes)
