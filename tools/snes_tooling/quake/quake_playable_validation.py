"""Build-time cache capture and linked-PVS checks for relocated playable maps."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re
import struct
from tempfile import TemporaryDirectory
import time

from snes_tooling.shared import snes_example_build as native
from snes_tooling.quake.quake_linked_thunk import validate_world_frustum_thunk, validate_world_vertex_pointer
from snes_tooling.shared.ld65_debug import load_debug_records, parse_debug_int
from snes_tooling.shared.validate_gsu_cache_kernels import write_cache_manifest

BANK_BYTES = 32768
POINTER = struct.Struct('<HB')


def capture_module_manifest(example: Path, libsfx: Path, *, name='quake-playable',
                            manifest_name='GSUCacheKernels-playable.json', cpu_assembly_only=False,
                            required_symbols=()) -> dict:
    """Check CPU assembly or link the module and verify its cache profile.

    This is the existing disposable native preflight sequence. It does not run
    asset/source generation against already-relocated Data, modify shared cache
    profiles, invent a placeholder binding, or bypass the normal build checks.
    The subsequent normal build validates this captured per-module manifest.
    """
    started = time.monotonic()
    example, libsfx = Path(example).resolve(), Path(libsfx).resolve()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', name):
        raise ValueError('invalid playable module source name')
    manifest = example/manifest_name
    flags = ['-I', str(example), *native.assembler_flags(libsfx), '--bin-include-dir', str(example)]
    for package in native.libsfx_packages(example):
        flags.extend(('-D', 'SFXPKG_'+native.LIBSFX_PACKAGES[package]))
    ca65 = native.require_cc65_tool(libsfx, 'ca65')
    sources = [('s', [])]
    if not cpu_assembly_only:
        sources.append(('sgs', ['-D', 'TARGET_GSU']))
        if (example/f'{name}.s700').is_file():
            sources.append(('s700', ['-D', 'TARGET_SMP']))
    with TemporaryDirectory(prefix='quake-playable-cache-') as directory:
        scratch = Path(directory)
        objects = []
        for suffix, defines in sources:
            source = example/f'{name}.{suffix}'
            if not source.is_file():
                raise ValueError(f'missing module source: {source}')
            target = scratch/f'module.{suffix}.o'
            native.run_checked([str(ca65), *flags, *defines, '-o', str(target), str(source)], scratch)
            objects.append(target)
        if cpu_assembly_only:
            return dict(passed=True, cpuAssembly=True,
                        elapsedSeconds=round(time.monotonic()-started, 3))
        _, support = native.assemble_libsfx(example, libsfx, flags, build_dir=scratch/'libs')
        native.link_example_objects(example, libsfx, name, support+objects, scratch)
        debug = scratch/f'{name}.dnfo'
        linked_symbols = {}
        if required_symbols:
            symbols = load_debug_records(debug)["sym"]
            for label in required_symbols:
                addresses = {parse_debug_int(row["val"]) for row in symbols
                             if row.get("name") == label and "val" in row and "seg" in row}
                if len(addresses) != 1:
                    raise ValueError(f"expected one linked address for {label}, found {len(addresses)}")
                linked_symbols[label] = addresses.pop()
        kernels = native.validate_cache_kernels(debug, segment_name=None, require=True)
        thunk_contract = validate_world_frustum_thunk(debug)
        vertex_contract = validate_world_vertex_pointer(debug)
        # The writer independently revalidates the deterministic profile it
        # emitted. Cache alignment/size/bank constraints were checked above.
        write_cache_manifest(kernels, manifest, segment_name=None)
        debug_hash = sha256(debug.read_bytes()).hexdigest()
    return dict(passed=True, cpuAssembly=True, gsuAssembly=True, linked=True,
        cacheKernelCount=len(kernels), cacheManifestVerified=True,
        linkedThunkVerified=True, worldFrustumThunk=thunk_contract,
        linkedWorldVertexVerified=True, worldVertexPointer=vertex_contract,
        **({"requiredSymbols": linked_symbols} if required_symbols else {}),
        manifest=str(manifest), manifestSha256=sha256(manifest.read_bytes()).hexdigest(),
        preflightDebugSha256=debug_hash, elapsedSeconds=round(time.monotonic()-started, 3))


def _source_brush_banks(metadata: dict) -> dict[int, str]:
    if metadata.get('schema') != 'quake-bsp-brush-assets' or metadata.get('version') != 2:
        raise ValueError('linked playable PVS requires original QBSA v2 metadata')
    if 'relocation' in metadata:
        raise ValueError('linked playable PVS expects original source-local metadata')
    fragments = metadata['worldComposition']['fragments']
    result = {}
    for first, count, prefix in (
        (metadata['capacity']['firstBrushBank'], metadata['textures']['reservedBankCount'], 'BSP_BRUSH_TEXTURE_'),
        (metadata['runtime']['firstBank'], metadata['runtime']['bankCount'], 'BSP_BRUSH_RUNTIME_'),
        (fragments['firstBank'], fragments['bankCount'], 'BSP_BRUSH_FRAGMENTS_'),
    ):
        if not 0 <= first < 64 or not 0 <= count <= 64-first:
            raise ValueError('source brush family escapes its classic-bank ABI')
        for index in range(count):
            if first+index in result:
                raise ValueError('source brush bank families overlap')
            result[first+index] = prefix+str(index)
    return result


def _linked_gsu_pointer(address: int) -> tuple[int, int]:
    bank, word = address >> 16, address & 65535
    if 0x80 <= bank < 0xC0 and word >= 0x8000:
        return bank & 127, word
    if 0x60 <= bank < 0x70:
        return bank, word
    raise ValueError(f'linked brush PVS storage is not GSU-readable: {address:06X}')


def validate_linked_segment_brush_pvs(debug_path: Path, metadata: dict) -> dict:
    """Check real separate ld65 outputs through a verified canonical projection.

    Metadata describes original classic-bank locations. Declared segment IDs
    identify their linked files and bases. Actual relocated directory pointers
    must resolve into exactly one declared linked row region; they are then
    inverse-mapped to source locations. Passing that directory and the actual
    linked row bytes to the unchanged native-ROM validator proves the original
    combined family hash, RLE bounds and conservative guard bits. No pixel or
    pointer-looking byte scan is used and no synthetic ROM is written to disk.
    """
    started = time.monotonic()
    debug_path = Path(debug_path).resolve()
    names = _source_brush_banks(metadata)
    records = load_debug_records(debug_path)
    segments = {}
    for row in records.get('seg', ()):
        name = row.get('name')
        if name in segments:
            raise ValueError(f'duplicate linked segment: {name}')
        segments[name] = row
    cache = {}
    pvs = metadata['worldComposition']['leafPvs']
    source_directory_offset = pvs['directoryAddress']-0x8000

    def read_source_region(bank, offset, size):
        if bank not in names or not 0 <= offset < BANK_BYTES or not 0 < size <= BANK_BYTES-offset:
            raise ValueError('source brush PVS region is invalid')
        name = names[bank]
        row = segments.get(name)
        pooled_name = f'BSP_MATERIAL_PVS_{bank*BANK_BYTES+offset:06X}'
        pooled_row = segments.get(pooled_name)
        if pooled_row is not None:
            if row is not None or (bank, offset, size) != (
                    pvs['directoryBank'], source_directory_offset, pvs['directoryBytes']):
                raise ValueError('pooled brush PVS must uniquely name the original directory')
            name, row, offset = pooled_name, pooled_row, 0
        if row is None or not all(key in row for key in ('start', 'size', 'oname', 'ooffs')):
            raise ValueError(f'linked brush PVS segment is missing stored output: {name}')
        segment_size = parse_debug_int(row['size'])
        if pooled_row is not None and segment_size != size:
            raise ValueError('pooled brush PVS directory extent differs from its source')
        if offset+size > segment_size:
            raise ValueError('brush PVS region escapes its linked segment')
        linked_bank, linked_address = _linked_gsu_pointer(parse_debug_int(row['start']))
        if linked_address+offset+size > 65536:
            raise ValueError('linked brush PVS region crosses a GSU bank')
        path = Path(row['oname'])
        path = (path if path.is_absolute() else debug_path.parent/path).resolve()
        if path not in cache:
            cache[path] = path.read_bytes()
        first = parse_debug_int(row['ooffs'])+offset
        payload = cache[path][first:first+size]
        if first < 0 or len(payload) != size:
            raise ValueError('linked brush PVS output file is truncated')
        return linked_bank, linked_address+offset, payload

    if pvs['directoryRecordBytes'] != POINTER.size or pvs['directoryBytes'] != pvs['leafCount']*POINTER.size:
        raise ValueError('source brush PVS directory dimensions are invalid')
    _, _, directory = read_source_region(pvs['directoryBank'], source_directory_offset, pvs['directoryBytes'])
    rows = []
    projection_end = pvs['directoryBank']*BANK_BYTES+source_directory_offset+len(directory)
    for source in pvs['rowStorage']:
        bank, address, payload = read_source_region(source['bank'], source['offset'], source['bytes'])
        rows.append(dict(bank=bank, address=address, payload=payload,
            sourceBank=source['bank'], sourceOffset=source['offset']))
        projection_end = max(projection_end, source['bank']*BANK_BYTES+source['offset']+len(payload))
    canonical = bytearray()
    for address, bank in POINTER.iter_unpack(directory):
        matches = [row for row in rows if row['bank'] == bank
                   and row['address'] <= address < row['address']+len(row['payload'])]
        if len(matches) != 1:
            raise ValueError('linked brush PVS row pointer escapes declared relocated storage')
        row = matches[0]
        old_address = 0x8000+row['sourceOffset']+address-row['address']
        canonical.extend(POINTER.pack(old_address, row['sourceBank']))
    projection = bytearray(b'\xff'*projection_end)
    first = pvs['directoryBank']*BANK_BYTES+source_directory_offset
    projection[first:first+len(canonical)] = canonical
    for row in rows:
        first = row['sourceBank']*BANK_BYTES+row['sourceOffset']
        projection[first:first+len(row['payload'])] = row['payload']
    from snes_tooling.quake.brush_pvs import validate_rom_leaf_pvs
    result = validate_rom_leaf_pvs(bytes(projection), metadata)
    result.update(artifactMode='linked-segment-files', pointerProjectionVerified=True,
        linkedFiles={str(path):sha256(payload).hexdigest() for path,payload in cache.items()},
        debugSha256=sha256(debug_path.read_bytes()).hexdigest(),
        elapsedSeconds=round(time.monotonic()-started, 3))
    return result
