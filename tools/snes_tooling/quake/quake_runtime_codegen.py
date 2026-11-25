"""Generate runtime proofs and independently assembled X3 renderer copies."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import time

from snes_tooling import Workspace
from snes_tooling.quake import quake_fly3x_codegen, quake_uniform_brush_materials
from snes_tooling.shared.generated_outputs import sync_generated_outputs


WORLD_LIGHTMAP_PROOF_INPUTS = (
    'QuakeBSPWorldFaces.bin', 'QuakeBSPWorldLightmapDirectory.bin',
    *(f'QuakeBSPWorldTextureCoordinates{index}.bin' for index in range(3)),
)
WORLD_LIGHTMAP_PROOF_HEADER = Path('WorldLightmapProof.i')


def generate_display_inputs(example, *, check=False):
    from snes_tooling.quake.quake_scene_palette import flash_palette
    from snes_tooling.quake.quake_start_hub import hub_outputs

    data = Path(example) / 'Data'
    palette = flash_palette((data / 'QuakeBSPTexturePalette.bin').read_bytes())
    outputs = {Path('QuakeBSPFlashPalette.bin'): palette}
    metadata = json.loads((data / 'QuakeBSPMetadata.json').read_bytes())
    if metadata.get('target', {}).get('mode') != 'fly':
        # The GSU include linter follows the shared gameplay header even
        # when the assembler disables that feature for the demo.
        outputs.update(hub_outputs())
    sync_generated_outputs(outputs, data, check=check)


def generate_world_lightmap_proof(example, *, check=False):
    """Qualify emitted world UVs without changing any content asset bytes."""
    started = time.perf_counter()
    data = Path(example) / 'Data'
    extra = ('QuakeBSPWorldTextureCoordinates3.bin',) if (data/'QuakeBSPWorldTextureCoordinates3.bin').is_file() else ()
    payloads = {name: (data/name).read_bytes() for name in (*WORLD_LIGHTMAP_PROOF_INPUTS, *extra)}
    face_struct, lightmap_struct, coordinate_struct = (
        struct.Struct('<HBBBB'), struct.Struct('<BHBBbb'), struct.Struct('<hh'))
    faces, lightmaps, *coordinate_banks = payloads.values()
    if len(faces) % face_struct.size or len(lightmaps) % lightmap_struct.size:
        raise ValueError('World lightmap proof has unaligned face/directory records')
    if len(faces) // face_struct.size != len(lightmaps) // lightmap_struct.size:
        raise ValueError('World lightmap proof face/directory counts differ')
    for index, bank in enumerate(coordinate_banks):
        if len(bank) % coordinate_struct.size or len(bank) > 0x8000:
            raise ValueError('World lightmap proof has an invalid coordinate bank')
        if len(bank) < 0x8000 and any(coordinate_banks[index+1:]):
            raise ValueError('World lightmap proof coordinate banks have a gap')
    coordinates = tuple(tuple(coordinate_struct.iter_unpack(bank)) for bank in coordinate_banks)
    coordinate_count = sum(map(len, coordinates))
    lit = missing = nondrawable = maximum_width = maximum_height = 0
    maximum_spans = [0, 0]
    unsafe = []
    for face_index, (face, lightmap) in enumerate(zip(
            face_struct.iter_unpack(faces), lightmap_struct.iter_unpack(lightmaps), strict=True)):
        first, count, *_ = face
        if first + count > coordinate_count:
            raise ValueError(f'World lightmap proof face {face_index} escapes coordinates')
        coordinate_bank, local_first = first >> 13, first & 0x1FFF
        if count and (coordinate_bank >= len(coordinates)
                      or local_first + count > len(coordinates[coordinate_bank])):
            raise ValueError(f'World lightmap proof face {face_index} escapes its coordinate bank')
        if not count:
            nondrawable += 1
            continue
        bank, _address, width, height, minimum_s, minimum_t = lightmap
        if bank == 0xFF:
            missing += 1
            continue
        if not width or not height:
            raise ValueError(f'World lightmap proof face {face_index} has an empty grid')
        lit += 1
        maximum_width = max(maximum_width, width)
        maximum_height = max(maximum_height, height)
        # Signed MULT needs width<128; both complete grid axis diameters must
        # stay below 32768 for interpolation between validated endpoints.
        face_safe = width < 128 and height <= 128
        vertices = coordinates[coordinate_bank][local_first:local_first+count]
        for axis, (minimum, dimension) in enumerate(((minimum_s, width), (minimum_t, height))):
            values = [coordinate[axis] for coordinate in vertices]
            lower, upper = minimum*256, (minimum+dimension-1)*256
            span = max(values)-min(values)
            maximum_spans[axis] = max(maximum_spans[axis], span)
            face_safe &= lower <= min(values) <= max(values) <= upper and span < 0x8000
        if not face_safe:
            unsafe.append(face_index)
    proven = bool(lit) and not unsafe
    files = [{'name': name, 'bytes': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()}
             for name, payload in payloads.items()]
    lines = [
        '; Generated source-only world lightmap qualification; no content payload.',
        '; Static source bounds only; runtime endpoint validation is also required.',
        '; Closed signed-Q4 grid, axis span <32768, width 1..127, height 1..128.',
        f'; faces={len(faces)//face_struct.size} coordinates={coordinate_count} '
        f'lit={lit} missing={missing} nondrawable={nondrawable} unsafe={len(unsafe)}',
        *(f"; {item['name']} bytes={item['bytes']} sha256={item['sha256']}" for item in files),
        f'BSP_WORLD_LIGHTMAP_CLOSED_GRID_PROVEN = {int(proven)}',
        f'F3_BSP_WORLD_LIGHTMAP_CLOSED_GRID_PROVEN = {int(proven)}',
    ]
    output = ('\n'.join(lines)+'\n').encode('ascii')
    sync_generated_outputs({WORLD_LIGHTMAP_PROOF_HEADER: output}, data/'Fly3x', check=check)
    return {'proven': proven, 'faces': len(faces)//face_struct.size, 'coordinates': coordinate_count,
            'lightmappedDrawableFaces': lit, 'missingFaces': missing, 'nondrawableFaces': nondrawable,
            'unsafeFaceCount': len(unsafe), 'firstUnsafeFaces': unsafe[:8],
            'maximumWidth': maximum_width, 'maximumHeight': maximum_height,
            'maximumAxisSpansQ4': maximum_spans, 'inputs': files,
            'headerSha256': hashlib.sha256(output).hexdigest(),
            'elapsedSeconds': round(time.perf_counter()-started, 6)}


def generate(example, *, check=False, config=None):
    """Generate the renderer and validate its content bindings."""
    started = time.perf_counter()
    example = example.resolve()
    generate_display_inputs(example, check=check)
    uniform_materials = quake_uniform_brush_materials.generate(example, check=check)
    from snes_tooling.quake.quake_alias_visibility_projection import require_bindings
    visibility = json.loads((example/'Data/QuakeBSPAliasVisibility.json').read_text())
    world_metadata = json.loads((example/'Data/QuakeBSPMetadata.json').read_bytes())
    if world_metadata.get('target', {}).get('mode') != 'fly':
        archive = visibility['archive']
        require_bindings(archive, example/'Data')
    lightmap_proof = generate_world_lightmap_proof(example, check=check)
    copies = quake_fly3x_codegen.generate(example, check=check)
    return {'passed': True, 'worldLightmapProof': lightmap_proof,
            'uniformBrushMaterials': uniform_materials,
            'rendererCopiesChanged': len(copies['changed']),
            'elapsedSeconds': round(time.perf_counter()-started, 3)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--example', type=Path, default=Workspace.discover().quake_example)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--config', type=Path, help='ROM configuration; default: asset-bound workspace config')
    args = parser.parse_args(argv)
    started = time.perf_counter()
    try:
        result = generate(args.example, check=args.check, config=args.config)
    except Exception as error:
        result = {'passed': False, 'error': str(error)}
    result['elapsedSeconds'] = round(time.perf_counter()-started, 3)
    print(json.dumps(result))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
