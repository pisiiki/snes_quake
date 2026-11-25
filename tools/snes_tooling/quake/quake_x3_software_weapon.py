"""Prepare and verify software-weapon rows for native X3 scanout."""
from collections import defaultdict
from struct import Struct, pack

from snes_tooling.quake.export_quake_live_weapon_reference import (
    DESCRIPTOR, decode_production_rows,
)

X3_WIDTH = 85
X3_HEIGHT = 67
X3_PADDED_ROWS = 72
POSE_STRIDE = 0x300
RECORD = Struct("<HB4H")
X2_FOR_X3 = {127 - 3*x//2: 84 - x for x in range(X3_WIDTH)}
Y2_FOR_Y3 = {3*y//2: y for y in range(X3_PADDED_ROWS)}


def rows_for(pixels, phase):
    return {
        (X2_FOR_X3[x], Y2_FOR_Y3[y+phase]): color
        for (x, y), color in pixels.items()
        if x in X2_FOR_X3 and y+phase in Y2_FOR_Y3
    }


def x3_swizzle(value):
    return (value & ~7) | (3*value & 7)


def encode(pixels):
    rows = defaultdict(lambda: [0] * 9)
    for (x, y), color in pixels.items():
        x, y = x3_swizzle(x), x3_swizzle(y)
        address = (y & ~7)*128 + (x & ~7)*8 + (y & 7)*2
        bit = 0x80 >> (x & 7)
        words = rows[address]
        words[0] |= bit
        for plane in range(8):
            if color & (1 << plane):
                words[1+plane] |= bit
    encoded = bytearray(pack("<H", len(rows)))
    for offset, (mask, *planes) in sorted(rows.items()):
        encoded += RECORD.pack(offset, mask,
                        *(planes[p] | (planes[p+1]<<8) for p in range(0,8,2)))
    return bytes(encoded)


def decode(data, shift):
    result = {}
    count = int.from_bytes(data[:2],"little")
    section = data[2:2+count*RECORD.size]
    for address, mask, *words in RECORD.iter_unpack(section):
        y = ((address >> 10)*8 + ((address >> 1)*3 & 7)) + shift
        assert 0 <= y < X3_PADDED_ROWS
        tile_x = (address >> 6 & 15)*8
        planes = tuple(value for w in words for value in (w & 255, w >> 8))
        for col in range(8):
            bit = 0x80 >> col
            if mask & bit:
                x = tile_x + (3*col & 7)
                result[x,y] = sum(1 << i for i,p in enumerate(planes) if p & bit)
    return result


def build(metadata, descriptors, raw_rows):
    frames = metadata["frames"]
    offsets = [int(offset, 16) for bank,offset,_,_ in DESCRIPTOR.findall(descriptors)
               if bank == "0"]
    if len(offsets) != len(frames):
        raise ValueError("invalid native software view-model descriptor array")
    first = next((i for i, row in enumerate(frames)
                  if row["model"] not in ("progs/v_shot.mdl","progs/v_axe.mdl")),
                 len(frames))
    stream = bytearray()
    sizes = []
    for index, _ in enumerate(frames[first:], first):
        end = offsets[index+1] if index+1 < len(offsets) else len(raw_rows)
        pixels = decode_production_rows(raw_rows[offsets[index]:end])
        phases = [encode(rows_for(pixels,k)) for k in range(3)]
        for bob in range(-3,4):
            named = decode(phases[bob % 3], (bob//3)*2)
            match = rows_for(pixels, bob)
            assert {p:c for p,c in named.items() if p[1]<X3_HEIGHT} == {
                p:c for p,c in match.items() if p[1]<X3_HEIGHT}
        for data in phases:
            sizes.append(len(data))
            if len(data)>POSE_STRIDE:
                raise ValueError("X3 weapon phase escaped native paired-read bounds")
            stream += data + bytes(POSE_STRIDE-len(data))
    return bytes(stream), first+1, sizes
