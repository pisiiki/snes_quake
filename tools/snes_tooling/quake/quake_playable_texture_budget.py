"""Semantic texture budgets and verified FF-tail compaction before allocation.

The world pruner preserves complete referenced banks. Optional compaction
keeps every live texel and embedded PVS record, including live FF bytes, and
omits only schema-unreferenced suffixes proven FF in the source. Original source Data remains untouched; derived linker views are
trimmed separately after pointer relocation.
"""
from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import re
import struct
import time

from snes_tooling.quake.quake_playable_layout import gsu_offset

TEXTURE = struct.Struct('<BHHHB')
WORLD_CHUNK = re.compile(r'BSP_WORLD_TEXTURE_(\d+)')
BANK_BYTES = 32768


def _directories(directory: Path):
    inputs = {}
    def read(name):
        payload = (directory/name).read_bytes()
        inputs[name] = sha256(payload).hexdigest()
        return payload
    result = [('world', 'QuakeBSPWorldTextureDirectory.bin', read('QuakeBSPWorldTextureDirectory.bin'))]
    metadata_path = directory/'QuakeBSPBrushAssets.json'
    if metadata_path.is_file():
        metadata = json.loads(read(metadata_path.name))
        if metadata.get('schema') != 'quake-bsp-brush-assets' or metadata.get('version') != 2:
            raise ValueError('texture pruning requires QBSA v2 source metadata')
        if 'relocation' in metadata:
            raise ValueError('texture pruning requires original, unrelocated source metadata')
        runtime = metadata['runtime']
        matches = [row for row in runtime['sections'] if row['name'] == 'TEXDIR']
        if len(matches) != 1:
            raise ValueError('QBSA metadata must identify one TEXDIR section')
        row = matches[0]
        index = row['bank']-runtime['firstBank']
        if not 0 <= index < runtime['bankCount'] or not 0x8000 <= row['address'] < 0x10000:
            raise ValueError('QBSA TEXDIR source location is invalid')
        filename = f'QuakeBSPBrushRuntime{index}.bin'
        chunk = read(filename)
        first = row['address']-0x8000
        payload = chunk[first:first+row['bytes']]
        if len(payload) != row['bytes'] or row['recordBytes'] != TEXTURE.size:
            raise ValueError('QBSA TEXDIR source extent is invalid')
        if len(payload) != row['recordCount']*TEXTURE.size:
            raise ValueError('QBSA TEXDIR source record count is invalid')
        if row.get('sha256') is not None and sha256(payload).hexdigest() != row['sha256']:
            raise ValueError('QBSA TEXDIR source payload differs from its metadata')
        result.append(('brush', filename+':TEXDIR', payload))
    return result, inputs


def _texture_ranges(payload: bytes, label: str):
    if len(payload) % TEXTURE.size:
        raise ValueError(f'{label} contains a partial texture directory record')
    for index, (bank, address, width, height, flags) in enumerate(TEXTURE.iter_unpack(payload)):
        if not width or not height:
            raise ValueError(f'{label} texture {index} has empty dimensions')
        first = gsu_offset(bank, address)
        size = width*height
        if first+size > 0x300000:
            raise ValueError(f'{label} texture {index} escapes GSU ROM storage')
        if flags & 2 and address+size > 65536:
            raise ValueError(f'{label} texture {index} falsely claims a single-bank extent')
        yield index, first, first+size


def prune_unused_world_texture_spans(directory: Path, spans, *, module=None):
    """Return ``(filtered_spans, report)`` for one original map asset family.

    Both the world directory and optional QBSA TEXDIR are visited. Brush
    records that address separate brush texture banks are ignored, while any
    brush use of world storage keeps the corresponding world chunks alive.
    Source/build binding is the caller's responsibility; the report preserves
    all inspected file and chunk hashes for that binding.
    """
    started = time.monotonic()
    directory = Path(directory)
    if (directory/'PlayableLayout.i').exists():
        raise ValueError('texture pruning must run before Data pointer relocation')
    spans = list(spans)
    if module is None:
        modules = {span.module for span in spans}
        if len(modules) != 1:
            raise ValueError('choose a module explicitly for a combined span list')
        module = modules.pop()
    chunks = sorted((int(match[1]), span) for span in spans if span.module == module
        and (match := WORLD_CHUNK.fullmatch(span.name)))
    if not chunks or [index for index, _ in chunks] != list(range(len(chunks))):
        raise ValueError('world texture source chunks must be a contiguous zero-based family')
    base = chunks[0][1].original_offset-chunks[0][0]*BANK_BYTES
    regions = []
    for index, span in chunks:
        if span.original_offset != base+index*BANK_BYTES or not 0 < len(span.payload) <= BANK_BYTES:
            raise ValueError('world texture source chunks violate their classic 32KiB storage ABI')
        regions.append((span.original_offset, span.original_offset+len(span.payload), index, span))
    needed, footprints, directory_counts = set(), {}, {}
    directories, input_hashes = _directories(directory)
    for kind, label, payload in directories:
        count = 0
        for record, first, last in _texture_ranges(payload, label):
            count += 1
            overlaps = [(a, b, index, span) for a, b, index, span in regions if a < last and first < b]
            if kind == 'brush' and not overlaps:
                continue
            cursor = first
            for begin, end, index, _ in overlaps:
                if begin > cursor:
                    raise ValueError(f'{label} texture {record} crosses missing world texture storage')
                cursor = max(cursor, min(end, last))
                needed.add(index)
                local_first, local_last = max(first, begin)-begin, min(last, end)-begin
                footprints.setdefault(index, []).append((local_first, local_last))
            if cursor != last:
                raise ValueError(f'{label} texture {record} escapes declared world texture chunks')
        directory_counts[label] = count
    # Keep the complete referenced prefix. The conventional sampler and build
    # contract advance from a first bank; removing an interior gap would save
    # no allocation while making that ABI needlessly harder to preserve.
    retained = set(range(max(needed, default=0)+1))
    kept_keys = {(span.module, span.name) for index, span in chunks if index in retained}
    removed = [span for index, span in chunks if index not in retained]
    filtered = [span for span in spans if span.module != module or not WORLD_CHUNK.fullmatch(span.name)
                or (span.module, span.name) in kept_keys]
    required = []
    for index, span in chunks:
        if index not in needed:
            continue
        ranges = sorted(footprints[index])
        merged = []
        for first, last in ranges:
            if merged and first <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(last, merged[-1][1]))
            else:
                merged.append((first, last))
        required.append(dict(index=index, name=span.name, referencedBytes=sum(b-a for a,b in merged),
                             requiredPrefixBytes=max(b for _, b in merged), ranges=merged))
    report = dict(schema='quake-playable-world-texture-budget-v1', module=module,
        sourceInputs=input_hashes, directoryRecordCounts=directory_counts,
        originalChunks=len(chunks), retainedChunks=len(retained),
        retainedUnreferencedChunks=[span.name for index, span in chunks if index in retained-needed],
        removedChunks=[span.name for span in removed], removedBytes=sum(len(span.payload) for span in removed),
        requiredChunks=required,
        sourceChunks={span.name:dict(bytes=len(span.payload), originalOffset=span.original_offset,
            sha256=sha256(span.payload).hexdigest()) for _, span in chunks},
        elapsedSeconds=round(time.monotonic()-started,6))
    return filtered, report


def _compact_source(directory, span, size, inputs):
    """Prove that a prefix retains the actual linked image."""
    if not 0 < size <= len(span.payload):
        raise ValueError('texture compact prefix escapes its source segment')
    match = re.fullmatch(r'BSP_(WORLD|BRUSH)_TEXTURE_(\d+)', span.name)
    family = 'World' if match[1] == 'WORLD' else 'Brush'
    filename = f'QuakeBSP{family}TexturePixels{match[2]}.bin'
    source = (directory/filename).read_bytes()
    inputs[filename] = dict(bytes=len(source), sha256=sha256(source).hexdigest())
    if span.payload != source:
        raise ValueError('linked texture differs from its source: '+filename)
    if source[size:] != b'\xff'*(len(source)-size):
        raise ValueError('texture compact suffix is not verified unused FF padding: '+filename)
    return replace(span, payload=span.payload[:size])


def compact_brush_texture_spans(directory, spans, *, module):
    """Remove only schema-proven FF tails; leave pointer and live-FF bytes intact."""
    started = time.monotonic()
    directory = Path(directory)
    if (directory/'PlayableLayout.i').exists():
        raise ValueError('texture compaction must run before Data pointer relocation')
    spans = list(spans)
    chunks = {int(match[1]): span for span in spans if span.module == module
              and (match := re.fullmatch(r'BSP_BRUSH_TEXTURE_(\d+)', span.name))}
    if not chunks:
        return spans, dict(schema='quake-playable-brush-texture-compaction-v1', module=module,
                           savedBytes=0, chunks=[], elapsedSeconds=round(time.monotonic()-started,6))
    if sorted(chunks) != list(range(len(chunks))):
        raise ValueError('brush texture chunks must be one contiguous zero-based family')
    metadata_payload = (directory/'QuakeBSPBrushAssets.json').read_bytes()
    metadata = json.loads(metadata_payload)
    if metadata.get('schema') != 'quake-bsp-brush-assets' or metadata.get('version') != 2 or 'relocation' in metadata:
        raise ValueError('brush compaction requires original QBSA v2 metadata')
    first_bank = metadata['capacity']['firstBrushBank']
    ranges = {index: [] for index in chunks}
    inputs = {'QuakeBSPBrushAssets.json': dict(bytes=len(metadata_payload), sha256=sha256(metadata_payload).hexdigest())}

    def protect(bank, address, size, label):
        index = bank-first_bank
        if index not in chunks:
            return
        offset = address-0x8000
        if size < 0 or offset < 0 or offset+size > BANK_BYTES:
            raise ValueError('brush compact live range crosses a bank: '+label)
        ranges[index].append((offset, offset+size, label))

    directories, original_inputs = _directories(directory)
    inputs.update({name: dict(sha256=digest) for name,digest in original_inputs.items()})
    for _, label, payload in directories:
        for record, (bank,address,width,height,flags) in enumerate(TEXTURE.iter_unpack(payload)):
            if not width or not height:
                raise ValueError('brush compact texture has empty dimensions')
            begin = gsu_offset(bank,address)
            end = begin+width*height
            touched = [index for index,span in chunks.items()
                       if span.original_offset < end and begin < span.original_offset+len(span.payload)]
            if touched:
                if not flags & 2 or len(touched) != 1 or bank-first_bank != touched[0]:
                    raise ValueError('brush texture compaction requires single-bank image footprints')
                protect(bank,address,width*height,label+':'+str(record))
    pvs = metadata['worldComposition']['leafPvs']
    protect(pvs['directoryBank'],pvs['directoryAddress'],pvs['directoryBytes'],'brush-PVS-directory')
    for index, row in enumerate(pvs.get('rowStorage', ())):
        protect(row['bank'],0x8000+row['offset'],row['bytes'],'brush-PVS-RLE:'+str(index))
    changes, records = {}, []
    for index, span in sorted(chunks.items()):
        if len(span.payload) != BANK_BYTES or span.original_offset != gsu_offset(first_bank+index,0x8000):
            raise ValueError('brush compact source segment does not match its canonical bank')
        kept = max(1, max((end for _,end,_ in ranges[index]), default=0))
        changes[span.key] = _compact_source(directory,span,kept,inputs)
        records.append(dict(name=span.name,originalBytes=len(span.payload),retainedBytes=kept,
                            savedBytes=len(span.payload)-kept,ranges=ranges[index],
                            originalSha256=sha256(span.payload).hexdigest(),
                            retainedSha256=sha256(changes[span.key].payload).hexdigest()))
    result = [changes.get(span.key,span) for span in spans]
    return result, dict(schema='quake-playable-brush-texture-compaction-v1',module=module,
                        savedBytes=sum(row['savedBytes'] for row in records),chunks=records,
                        sourceInputs=inputs,elapsedSeconds=round(time.monotonic()-started,6))


def compact_last_world_texture_span(directory, spans, *, module):
    """Trim only the final retained classic bank, preserving all bank strides."""
    started = time.monotonic()
    directory = Path(directory)
    spans, footprint = prune_unused_world_texture_spans(directory,spans,module=module)
    chunks = [span for span in spans if span.module == module and WORLD_CHUNK.fullmatch(span.name)]
    final = max(chunks,key=lambda span:int(WORLD_CHUNK.fullmatch(span.name)[1]))
    live = next((row for row in footprint['requiredChunks'] if row['name'] == final.name), None)
    size = max(1, live['requiredPrefixBytes'] if live else 0)
    inputs = {}
    replacement = _compact_source(Path(directory),final,size,inputs)
    result = [replacement if span.key == final.key else span for span in spans]
    return result, dict(schema='quake-playable-world-texture-tail-compaction-v1',module=module,
                        name=final.name,originalBytes=len(final.payload),retainedBytes=size,
                        savedBytes=len(final.payload)-size,sourceInputs=inputs,
                        elapsedSeconds=round(time.monotonic()-started,6))
