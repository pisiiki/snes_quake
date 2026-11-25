"""Export QWV4 reference art from the exact production live weapon rows.

This standalone diagnostic never changes generated ROM assets or receipts.
The source masked planar rows already include the gameplay producer's X
reflection; preserve their grid instead of rasterizing the MDL again.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import time

from snes_tooling.quake.generate_quake_snes_weapon_sprites import (
    BOB_LIMIT, HEIGHT, PLAYABLE_WEAPON_HEIGHT, PREFIX, RECORD8, WIDTH, encode_reference_frame,
)
from snes_tooling.quake.quake_bsp_assets import texture_coordinate_map
from snes_tooling.quake.quake_scene_palette import flash_palette


DESCRIPTOR = re.compile(
    r"^\s*\.word \.loword\(QuakeBSPWeaponData(\d+) \+ \$([0-9A-Fa-f]{4})\), "
    r"\$([0-9A-Fa-f]{4}), ([01]), \^QuakeBSPWeaponData\1 & \$7F\s*$", re.M)


def file_record(path):
    data = path.read_bytes()
    return dict(path=str(path.resolve()), bytes=len(data), sha256=hashlib.sha256(data).hexdigest())


def decode_production_rows(payload):
    """Decode masks and all eight planes on the production logical grid."""
    if len(payload) % RECORD8.size:
        raise ValueError("live weapon rows have a partial planar record")
    inverse = {physical: logical for logical, physical in enumerate(texture_coordinate_map())}
    pixels, addresses = {}, set()
    for address, mask, *words in RECORD8.iter_unpack(payload):
        if address & 1 or address >= 0x4000 or not mask or address in addresses:
            raise ValueError("live weapon row has an invalid or duplicate destination")
        addresses.add(address)
        physical_y = (address // 1024) * 8 + (address % 16) // 2
        physical_x = ((address % 1024) // 64) * 8
        y = inverse[physical_y]
        if y >= HEIGHT + BOB_LIMIT:
            raise ValueError("live weapon row exceeds the supported bob margin")
        planes = tuple(value for word in words for value in (word & 255, word >> 8))
        for column in range(8):
            bit = 0x80 >> column
            if mask & bit:
                color = sum((1 << plane) for plane, bits in enumerate(planes) if bits & bit)
                if not color:
                    raise ValueError("opaque live weapon texel uses QWV4 transparent index zero")
                pixels[inverse[physical_x + column], y] = color
    return pixels


def build_reference(data_dir):
    """Return QWV4 bytes and provenance for one complete production live set."""
    data_dir = Path(data_dir)
    report_path, assembly_path = (data_dir/(PREFIX+suffix) for suffix in ('.json','.i'))
    metadata = json.loads(report_path.read_bytes())
    if metadata.get('schema') != 'quake-live-x2-weapon-v1' or metadata.get('rowBytes') != RECORD8.size:
        raise ValueError('requires production live X2 weapon metadata')
    height = metadata.get('viewportHeight', HEIGHT)
    if height not in (HEIGHT, PLAYABLE_WEAPON_HEIGHT):
        raise ValueError('unsupported live weapon viewport height')
    frames = metadata.get('frames', [])
    if not 0 < len(frames) < 256 or [frame['id'] for frame in frames] != list(range(1,len(frames)+1)):
        raise ValueError('live weapon frame IDs must be a complete one-based sequence')
    assembly = assembly_path.read_text(encoding='ascii')
    start, end = assembly.find('QuakeBSPWeaponDescriptors:'), assembly.find('QuakeBSPWeaponBobRows:')
    if start < 0 or end <= start:
        raise ValueError('production weapon descriptor labels are missing')
    descriptors = tuple((int(chunk),int(offset,16),int(count,16),bool(int(flash)))
                        for chunk,offset,count,flash in DESCRIPTOR.findall(assembly[start:end]))
    if len(descriptors) != len(frames) or any(chunk for chunk,_,_,_ in descriptors):
        raise ValueError('live weapon descriptors must name the complete single production data chunk')
    if descriptors[0][3]:
        raise ValueError('QWV4 live idle frame cannot have a muzzle flash')
    rows_path = data_dir/(PREFIX+'Data0.bin')
    rows = rows_path.read_bytes()
    if len(rows) != metadata.get('spriteBytes') or hashlib.sha256(rows).hexdigest() != metadata.get('dataSha256'):
        raise ValueError('production weapon rows no longer match their metadata hash')
    starts = [offset for _,offset,_,_ in descriptors]
    if starts[0] or starts != sorted(starts) or any(offset % RECORD8.size for offset in starts):
        raise ValueError('live weapon frame offsets are not contiguous planar row boundaries')
    # The stock Super Shotgun's third recoil frame is entirely below the
    # viewport. Its descriptor legitimately shares the next frame's offset.
    for earlier, later, frame in zip(starts[:-1], starts[1:], frames[:-1], strict=True):
        if earlier == later and (frame["rowCount"] or frame["visiblePixels"]):
            raise ValueError("nonempty weapon frame has no planar rows")
    palette_path = data_dir/'QuakeBSPTexturePalette.bin'
    palette = palette_path.read_bytes()
    if len(palette) != 512 or any(word & 0x8000 for word, in struct.iter_unpack('<H',palette)):
        raise ValueError('live QWV4 reference requires a complete RGB555 scene palette')
    encoded, evidence = bytearray(), []
    for index,(frame,(_,offset,count,flash)) in enumerate(zip(frames,descriptors,strict=True)):
        next_offset = starts[index+1] if index+1 < len(starts) else len(rows)
        pixels = decode_production_rows(rows[offset:next_offset])
        visible = {position:color for position,color in pixels.items() if position[1] < height}
        visible_rows = len({(x//8,y) for x,y in visible})
        if count != frame['rowCount'] or count != visible_rows or flash != frame['flash']:
            raise ValueError(f'live frame {index+1} descriptor differs from production metadata or rows')
        if len(visible) != frame['visiblePixels']:
            raise ValueError(f'live frame {index+1} opaque coverage differs from production metadata')
        encoded.extend(encode_reference_frame(pixels,flash=flash))
        evidence.append(dict(id=index+1,animationFrame=frame['animationFrame'],
            rowBytes=next_offset-offset,visiblePixels=len(visible),flash=flash))
    poses = bytes(value for frame in range(1,len(frames)+1) for value in (frame,0))
    idle = bytes((0,*([1]*len(frames))))
    qwv = struct.pack('<4s4H',b'QWV4',WIDTH,HEIGHT,len(frames),len(frames))+poses+idle+palette+flash_palette(palette)+encoded
    return qwv, dict(schema='quake-live-weapon-reference-v1',
        model=metadata['model'],modelSha256=metadata['modelSha256'],
        orientation='production-logical-grid',frames=evidence,
        **({'viewportHeight': height} if height != HEIGHT else {}),
        inputs=[file_record(path) for path in (report_path,assembly_path,rows_path,palette_path)],
        output=dict(bytes=len(qwv),sha256=hashlib.sha256(qwv).hexdigest()))


def main(argv=None):
    started=time.monotonic()
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        if args.output.exists() or args.report.exists() or args.output.resolve()==args.report.resolve():
            raise ValueError('reference output and report must be distinct new paths')
        payload,report=build_reference(args.data_dir)
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_bytes(payload)
        report.update(passed=True,elapsedSeconds=round(time.monotonic()-started,3))
        args.report.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf-8')
        print(json.dumps(dict(passed=True,output=str(args.output.resolve()),
                             frames=len(report['frames']),elapsedSeconds=report['elapsedSeconds'])))
        return 0
    except (OSError,ValueError,KeyError) as error:
        print(json.dumps(dict(passed=False,error=str(error),elapsedSeconds=round(time.monotonic()-started,3))))
        return 1


if __name__=='__main__':
    raise SystemExit(main())
