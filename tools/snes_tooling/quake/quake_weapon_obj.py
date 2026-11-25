"""Pack exact-color X2 weapon masks into native SNES OBJ tiles."""

from collections import defaultdict
from dataclasses import dataclass
import json
from pathlib import Path
from struct import iter_unpack, pack
from textwrap import wrap

from snes_tooling.quake.export_quake_live_weapon_reference import DESCRIPTOR, decode_production_rows
from snes_tooling.quake.generate_quake_snes_weapon_sprites import (
    BOB_OFFSETS, PLAYABLE_WEAPON_HEIGHT, PREFIX, WIDTH, common_opaque_rectangle, encode_frame,
)
from snes_tooling.quake.quake_scene_palette import flash_palette


# Color pairs grouped by their distribution in the shotgun and axe art.
PALETTES = (
    (8, 22, 23, 114, 117, 118, 119, 120, 121, 122, 123, 124, 165, 166, 167),
    (16, 17, 18, 19, 20, 21, 49, 141, 168, 169, 170, 171, 172, 173, 174),
    (48, 2, 3, 4, 5, 6, 7, 32, 33, 34, 35, 36, 139, 234, 235),
    (65, 66, 67, 68, 69, 70, 71, 72, 73, 74, 75, 76, 116, 142, 231),
    (37, 78, 232, 233, 236, 237),
)
FREE_TILES = tuple(range(128)) + tuple(range(430, 512))
CHR_CHUNK_BYTES = 1024
CHR_CHUNKS = 4
CHR_DESCRIPTOR_BYTES = 6
OAM_BYTES = 544
PLACEMENT_BYTES = CHR_DESCRIPTOR_BYTES*CHR_CHUNKS+OAM_BYTES


@dataclass(frozen=True)
class WeaponPose:
    tiles: tuple[bytes, ...]
    objects: tuple[tuple[int, int, int, int], ...]

    def oam(self, indices, bob):
        """Encode a complete OAM image for the selected VRAM tile placement."""
        if len(indices) != len(self.tiles) or set(indices) - set(FREE_TILES):
            raise ValueError('weapon tile placement overlaps live VRAM')
        if len(set(indices)) != len(indices) or bob not in BOB_OFFSETS:
            raise ValueError('weapon tile placement or bob is invalid')
        image = bytearray(bytes((0, 240, 0, 0))*128 + bytes(32))
        obj = 0
        for x, y, local_tile, bank in self.objects:
            y += 2*bob
            if y >= 2*PLAYABLE_WEAPON_HEIGHT:
                continue
            tile = indices[local_tile]
            image[obj*4:obj*4+4] = bytes((x & 255, y & 255, tile & 255,
                                           0x10 | (bank << 1) | (tile >> 8)))
            image[512+obj//4] |= (x >> 8) << (2*(obj%4))
            obj += 1
        return bytes(image)


def planar_tile(pixels):
    """Encode a 4x4 logical tile at twice that size on each axis."""
    out = bytearray()
    for first in (0, 2):
        for y in range(4):
            pair = bytes(
                sum(3 << (6-2*x) for x in range(4) if pixels[y*4+x] & (1 << plane))
                for plane in (first, first+1)
            )
            out.extend(pair*2)
    return bytes(out)


def permute_words(palette, forward):
    if len(palette) != 2*len(forward):
        raise ValueError('weapon palette extent differs from its index map')
    result = bytearray(len(palette))
    for old, new in enumerate(forward):
        result[new*2:new*2+2] = palette[old*2:old*2+2]
    return bytes(result)


def permute_colormap(colormap, forward):
    if len(colormap) % 256:
        raise ValueError('colormap contains a partial palette row')
    inverse = bytes(forward.index(i) for i in range(256))
    result = bytearray(len(colormap))
    for first in range(0, len(colormap), 256):
        row = colormap[first:first+256].translate(forward)
        result[first:first+256] = bytes(row[i] for i in inverse)
    return bytes(result)


def alias_pixel_ranges(chunks, physical):
    """Bind each biased QBA sprite's texels to its canonical source bank."""
    from snes_tooling.quake.quake_gameplay_production_aliases import HEADER, SPRITE, original_location

    header = HEADER.unpack_from(chunks[0])
    if header[:3] != (b'QBA1', 6, HEADER.size) or header[8] != len(chunks):
        raise ValueError('invalid canonical weapon-palette alias carrier')
    data = b''.join(chunks)
    if len(physical) < len(chunks):
        raise ValueError('QBA alias carrier has fewer physical banks than populated chunks')
    locations = [original_location(bank) for bank in physical[:len(chunks)]]
    ranges = [set() for _ in chunks]
    for i in range(header[4]):
        bank, _, addr, width, height, *_ = SPRITE.unpack_from(data, header[10]+i*SPRITE.size)
        if not width or not height:
            continue
        matches = [(j, addr-base) for j, (b, base) in enumerate(locations)
                   if b == bank and 0 <= addr-base <= len(chunks[j])-width*height]
        if len(matches) != 1:
            raise ValueError('QBA sprite pixels escape one canonical bank')
        j, first = matches[0]
        ranges[j].add((first, first+width*height))
    for rows in ranges:
        ordered = sorted(rows)
        if any(a[1] > b[0] for a, b in zip(ordered, ordered[1:])):
            raise ValueError('QBA sprite ranges overlap')
    return ranges


def permute_alias_pixels(payload, ranges, forward, *, source_offset=0):
    encoded = bytes((0, *(forward[i]+1 for i in range(255))))
    result = bytearray(payload)
    for first, end in ranges:
        low = max(first-source_offset, 0)
        high = min(end-source_offset, len(payload))
        if low < high:
            result[low:high] = payload[low:high].translate(encoded)
    return bytes(result)


def pack_pose(footprint, slots):
    # World pixels already carry the producer's horizontal reflection.
    x0 = min(WIDTH-1-x for x, _ in footprint)
    y0 = min(y for _, y in footprint)
    masks = defaultdict(lambda: bytearray(16))
    for (x, y), color in footprint.items():
        tx, dx = divmod(WIDTH-1-x-x0, 4)
        ty, dy = divmod(y-y0, 4)
        bank, nibble = slots[color]
        masks[tx, ty, bank][4*dy+dx] = nibble
    tiles, objects, slivers = {}, [], [0]*224
    for (tx, ty, bank), mask in sorted(masks.items()):
        tile = tiles.setdefault(planar_tile(mask), len(tiles))
        x, y = 2*x0+8*tx, 2*y0+8*ty
        objects.append((x, y, tile, bank))
        for line in range(y, y+8):
            slivers[line] += 1
    if len(objects) > 128 or max(slivers) > 32:
        raise ValueError('weapon pose exceeds the PPU object budget')
    return WeaponPose(tuple(tiles), tuple(objects))


def pack_weapon(footprints, palette, shotgun_count, *, fixed=()):
    """Return an exact palette permutation, native geometry and safe shotgun bounds."""
    base = tuple(value for value, in iter_unpack('<H', palette))
    flash = tuple(value for value, in iter_unpack('<H', flash_palette(palette)))
    pairs = tuple(zip(base, flash, strict=True))
    # Sky marker tokens never reach CGRAM. Preserve their original ordering
    # and reserve their indices before assigning hardware palette slots.
    locked = {0, *range(240, 256), *fixed}
    banks = sorted(range(7), key=lambda bank: (
        -sum(128+16*bank+slot not in locked for slot in range(1, 16)), bank,
    ))
    choices = {}
    targets = {i: i for i in locked}
    for bank, group in zip(banks, PALETTES):
        open_slots = (slot for slot in range(1, 16) if 128+16*bank+slot not in locked)
        for index in group:
            pair = pairs[index]
            source = next((i for i, value in enumerate(pairs) if value == pair and i not in targets), None)
            slot = next(open_slots, None)
            if source is None or slot is None:
                raise ValueError('weapon color group conflicts with a fixed palette index')
            choices[pair] = bank, slot
            targets[source] = 128+16*bank+slot
    indices = set(range(256))
    targets.update(zip(sorted(indices-targets.keys()), sorted(indices-set(targets.values())), strict=True))
    forward = bytes(targets[i] for i in range(256))
    slots = {i: choices[pair] for i, pair in enumerate(pairs) if pair in choices}
    poses = tuple(pack_pose(pixels, slots) for pixels in footprints)
    if sum(sorted((len(pose.tiles) for pose in poses), reverse=True)[:2]) > len(FREE_TILES):
        raise ValueError('two largest weapon poses cannot reside in VRAM together')
    shotgun = [{(x, y+bob): color for (x, y), color in pixels.items()
                if 0 <= y+bob < PLAYABLE_WEAPON_HEIGHT}
               for pixels in footprints[:shotgun_count] for bob in BOB_OFFSETS]
    return forward, poses, common_opaque_rectangle(shotgun, hidden=False)


def build_weapon_assets(weapon, palette, *, fixed):
    meta = json.loads(weapon[Path(PREFIX+'.json')])
    include = weapon[Path(PREFIX+'.i')].decode('ascii')
    starts = [int(offset, 16) for bank, offset, _, _ in DESCRIPTOR.findall(include) if bank == '0']
    rows = weapon[Path(PREFIX+'Data0.bin')]
    if len(starts) != len(meta['frames']) or not starts or starts[0] != 0:
        raise ValueError('OBJ descriptors do not cover the shared live weapon')
    footprints = [decode_production_rows(rows[a:b])
                  for a, b in zip(starts, starts[1:]+[len(rows)], strict=True)]
    shotgun_count = sum(row['model'] == 'progs/v_shot.mdl' for row in meta['frames'])
    obj_count = sum(row['model'] in ('progs/v_shot.mdl', 'progs/v_axe.mdl') for row in meta['frames'])
    if any(row['model'] in ('progs/v_shot.mdl', 'progs/v_axe.mdl') for row in meta['frames'][obj_count:]):
        raise ValueError('hardware weapon frames must precede staged weapon frames')
    forward, poses, core = pack_weapon(footprints[:obj_count], palette, shotgun_count, fixed=fixed)
    if obj_count < len(footprints):
        # The S-CPU merges these masks directly into the selected WRAM page.
        # Its colors must use the same hardware permutation as world pixels.
        encoded = b''.join(encode_frame(footprint, forward) for footprint in footprints[obj_count:])
        suffix = starts[obj_count]
        if len(encoded) != len(rows) - suffix:
            raise ValueError('weapon palette permutation changed its masked row count')
        # Hardware poses exclusively read OBJ tiles. Only the staged poses
        # need the software row stream, whose first descriptor now starts at 0.
        def staged_descriptor(match):
            start, end = match.span(2)
            offset = max(0, int(match[2], 16) - suffix)
            return include[match.start():start] + f'{offset:04X}' + include[end:match.end()]

        weapon[Path(PREFIX+'.i')] = DESCRIPTOR.sub(staged_descriptor, include).encode('ascii')
        weapon[Path(PREFIX+'Data0.bin')] = encoded
    return forward, poses, core


def encode_display_tints(palettes):
    """Precompute native flashes and the stock Quad and Biosuit shifts for CGRAM."""
    payload = bytearray()
    for palette in palettes:
        words = tuple(word for word, in iter_unpack('<H', palette))
        if len(words) != 256:
            raise ValueError('invalid hardware weapon palette extent')
        for tint in ((10, 0, 0), (8, 4, 0)):
            # Color zero is the backdrop and did not receive BG color math.
            payload += pack('<H', words[0])
            payload += pack('<255H', *(sum(min(31, ((word >> shift) & 31) + add) << shift
                                           for shift, add in zip((0, 5, 10), tint, strict=True))
                                        for word in words[1:]))
    for strength, color in ((30, (0, 0, 31)), (20, (0, 31, 0))):
        for palette in palettes:
            for (word,) in iter_unpack('<H', palette):
                rgb = [(word >> shift) & 31 for shift in (0, 5, 10)]
                shifted = [source + ((target - source) * strength // 256)
                           for source, target in zip(rgb, color, strict=True)]
                payload += pack('<H', shifted[0] | shifted[1] << 5 | shifted[2] << 10)
    return bytes(payload)


def centerprint_rows(message):
    return [line for original in message.upper().splitlines()
            for line in (wrap(original, width=32, break_long_words=False) or [''])]


def encode_centerprints(messages, *, line_capacity=4, pickup_rows=False):
    """Pack BG2 tilemap rows and scroll to center odd-width lines exactly."""
    payload = bytearray(2 * len(messages))
    offsets = {}
    for message in dict.fromkeys(messages):
        lines = centerprint_rows(message)
        if not 1 <= len(lines) <= line_capacity <= 4 or any(len(line) > 32 for line in lines):
            raise ValueError('centerprint exceeds the background tilemap rows')
        offsets[message] = len(payload)
        tilemap = [0xC0] * (line_capacity * 2 * 32)
        scroll = bytearray(pack('<BHHBHH', 32, 0, 63, 46, 0, 0) if pickup_rows else pack('<BHH', 78, 0, 0))
        for row, line in enumerate(lines):
            if any(not 32 <= ord(char) <= 90 for char in line):
                raise ValueError('centerprint contains a glyph outside the menu font')
            left = (32 - len(line)) // 2
            start = 64 * row + left
            tilemap[start:start + len(line)] = [0x20C0 + ord(char) - 32 for char in line]
            # Tilemap rows are separated by a transparent row. Scan ten
            # lines per text row and shift odd-width lines by half a tile.
            x = -4 if len(line) & 1 else 0
            y = 16 * row - (78 + 10 * row) - 1
            scroll.extend(pack('<Bhh', 10, x, y))
        payload.extend(pack(f'<{len(tilemap)}H', *tilemap))
        payload.extend(scroll + b'\0')
    payload[:2 * len(messages)] = pack(f'<{len(messages)}H', *(offsets[m] for m in messages))
    return bytes(payload)


def encode_obj_assets(poses):
    """Build ROM graphics and two placements per pose for double buffering."""
    graphics, metadata = bytearray(), bytearray()
    for pose in poses:
        offset = len(graphics)
        graphics.extend(b''.join(pose.tiles))
        count = len(pose.tiles)
        for indices in (FREE_TILES[:count], FREE_TILES[-count:]):
            chunks = []
            for start in range(count):
                tile = indices[start]
                vram = (0x8000 if tile < 256 else 0xc000) + (tile & 255)*32
                if (not chunks or chunks[-1][0] + chunks[-1][2] != vram
                        or chunks[-1][2] == CHR_CHUNK_BYTES):
                    chunks.append([vram, offset+32*start, 0])
                chunks[-1][2] += 32
            if len(chunks) > CHR_CHUNKS:
                raise ValueError('OBJ pose exceeds the staged VRAM upload budget')
            chunks += [[0, 0, 0]]*(CHR_CHUNKS-len(chunks))
            metadata += b''.join(pack('<3H', *chunk) for chunk in chunks)
            metadata.extend(pose.oam(indices, 0))
    return bytes(graphics), bytes(metadata)


def assembly_include(offsets, *, centerprint_lines=4):
    from snes_tooling.quake.quake_playable_layout import cpu_address
    lines = [f"WEAPON_OBJ_CHR = ${cpu_address(offsets[1]):06X}",
             f"WEAPON_OBJ_CHUNKS = {CHR_CHUNKS}",
             f"WEAPON_OBJ_CHR_DESC = {CHR_DESCRIPTOR_BYTES}",
             "WEAPON_OBJ_POINTER_BYTES = 3",
             f"WEAPON_OBJ_CENTERPRINT_LINES = {centerprint_lines}",
             f"WEAPON_OBJ_TINTS = ${cpu_address(offsets[-2]):06X}",
             f"WEAPON_OBJ_CENTERPRINTS = ${cpu_address(offsets[-1]):06X}"]
    lines += [f"WeaponObjPoseAddresses = ${cpu_address(offsets[-3]):06X}"]
    return ("\n".join(lines)+"\n").encode("ascii")


def weapon_palette_map(package, manifest=None):
    """Load and authenticate the permutation from a built playable ROM."""
    from hashlib import sha256

    package = Path(package)
    if manifest is None:
        manifest = json.loads((package/"quake-playable-build.json").read_bytes())
    rows = manifest.get("weaponObj")
    if rows is None:
        return None
    entry = rows[0]
    with (package/"quake-playable.sfc").open("rb") as rom:
        rom.seek(entry["offset"])
        mapping = rom.read(entry["bytes"])
    if (len(mapping) != 256 or len(set(mapping)) != 256 or mapping[0] != 0
            or mapping[240:] != bytes(range(240, 256))
            or sha256(mapping).hexdigest() != entry["sha256"]):
        raise ValueError("invalid weapon OBJ palette permutation")
    return mapping
