"""Place suitable HUD glyph tiles in the existing weapon OBJ palettes."""

from dataclasses import replace
from struct import pack, unpack

from snes_tooling.quake.generate_quake_snes_weapon_sprites import BOB_OFFSETS
from snes_tooling.quake.quake_status_hud import ATLAS_RUNS, planar_tile

WORLD_LINES = 200
OBJ_TILES_END = 0xD5C0
OBJ_FIRST = 112
OBJ_PER_DIGIT = 2
OBJ_COUNT = 6 * OBJ_PER_DIGIT


def tile_ids(runs):
    return tuple(start // 64 + index for start, count in runs for index in range(count))


def unpack_hud_tile(tile):
    return bytes(sum(((tile[plane * 8 + y * 2 + bit] >> (7 - x)) & 1) << (plane + bit)
                     for plane in range(0, 8, 2) for bit in range(2))
                 for y in range(8) for x in range(8))


def textureless_display_palette(hud, natural, diagnostic, *, weapon_obj):
    """Keep shared HUD colors while allocating the complete world lightmap ramp."""
    used = set()
    for art in (hud.graphics, hud.quad_face, hud.nail_icon, hud.pain_faces):
        for at in range(0, len(art), 64):
            used.update(unpack_hud_tile(art[at:at + 64]))
    if 239 in used:
        raise ValueError("status HUD uses the textureless hole diagnostic color")

    # Keep the BG2 font ink and the menu font. The hybrid HUD can also use
    # any OBJ palette bank, so its world ramp fits below the OBJ slots.
    reserved = used | {14} | set(range(128 if weapon_obj else 240, 256))
    free = set(range(1, 239)) - reserved
    white = 63 if 63 in free else max((index for index in free if index < 128), default=0)
    shades = bytes((0, *sorted(free - {white})[:62], white))
    if len(shades) != 64 or not white:
        raise ValueError("status HUD leaves no room for the 64-color world lightmap ramp")
    if len(natural) != len(diagnostic) or len(natural) != 512:
        raise ValueError("invalid playable display palette extent")

    palette = bytearray(512)
    palette[478:480] = diagnostic[478:480]
    for index in reserved - {239}:
        palette[index * 2:index * 2 + 2] = natural[index * 2:index * 2 + 2]
    for shade, index in enumerate(shades):
        palette[index * 2:index * 2 + 2] = diagnostic[shade * 2:shade * 2 + 2]
    return bytes(palette), shades[::-1]


def sprite_mask(background, glyph, signatures, banks):
    changes = tuple(None if signatures[old] == signatures[new] else signatures[new]
                    for old, new in zip(background, glyph, strict=True))
    needed = set(changes) - {None}
    if not needed:
        return None
    for bank, entries in enumerate(banks):
        if needed <= entries.keys():
            return bank, planar_tile(bytes(entries.get(color, 0) for color in changes), planes=4)
    return None


def number_sprites(codes, limit):
    for value in range(512):
        base = 11 if value < limit else 1
        digits = [0] * (3 - len(str(value))) + [base + int(digit) for digit in str(value)]
        counts = tuple(sum(bool(code) for digit in digits for code in codes[digit][row:row + 3])
                       for row in range(0, 9, 3))
        yield (sum(counts), *counts)


def validate_sprite_budget(codes, poses):
    health = tuple(map(max, zip(*number_sprites(codes, 26), strict=True)))
    ammo = tuple(map(max, zip(*number_sprites(codes, 11), strict=True)))
    count, *rows = (a + b for a, b in zip(health, ammo, strict=True))
    # Weapon OAM uses 8px objects and doubles the logical bob displacement.
    # Count all of its evaluated objects, including ones behind the HUD.
    weapon_total = max(len(pose.objects) for pose in poses)
    line_total = max(rows[(line - WORLD_LINES) // 8]
                     + sum((line - y - 2 * bob) % 256 < 8 for _, y, _, _ in pose.objects)
                     for pose in poses for bob in BOB_OFFSETS for line in range(WORLD_LINES, 224))
    if (OBJ_FIRST < weapon_total or line_total > 32 or count == 0
            or max(sum(bool(code) for code in glyph) for glyph in codes) > OBJ_PER_DIGIT):
        raise ValueError(f"HUD OBJ layout exceeds the budget: {count=} {weapon_total=} {line_total=}")


def pack_status_hud_overlays(hud, palettes, poses):
    signatures = tuple(zip(*(unpack("<256H", palette) for palette in palettes), strict=True))
    banks = tuple({signatures[128 + bank * 16 + nibble]: nibble for nibble in range(1, 16)}
                  for bank in range(8))
    ids = tile_ids(hud.atlas_runs)[:hud.tile_count]
    pixels = {key: unpack_hud_tile(hud.graphics[index * 64:(index + 1) * 64])
              for index, key in enumerate(ids)}
    blank = hud.variants[0]
    digit_variants = hud.variants[1:21]
    masks = tuple(tuple(sprite_mask(pixels[base], pixels[ink], signatures, banks)
                        for base, ink in zip(blank, glyph, strict=True)) for glyph in digit_variants)
    retained = set(hud.map_words) | set(blank) | set(hud.armor_digits)
    retained.update(tile for glyph in hud.variants[21:] for tile in glyph)
    retained.update(tile for glyph, row in zip(digit_variants, masks, strict=True)
                    for tile, mask in zip(glyph, row, strict=True) if mask is None)
    tiles, descriptors = {}, {}
    codes, glyphs = [bytes(9)], [blank]
    for glyph, row in zip(digit_variants, masks, strict=True):
        cells, new_glyph = bytearray(), []
        for base, ink, mask in zip(blank, glyph, row, strict=True):
            if ink in retained:
                cells.append(0)
                new_glyph.append(ink)
            else:
                bank, graphics = mask
                tile = tiles.setdefault(graphics, len(tiles))
                cells.append(descriptors.setdefault((bank, tile), 1 + len(descriptors)))
                new_glyph.append(base)
        codes.append(bytes(cells))
        glyphs.append(tuple(new_glyph))

    validate_sprite_budget(codes, poses)
    obj_graphics = b"".join(tiles)
    obj_vram = OBJ_TILES_END - len(obj_graphics)
    head, tail, extra = ATLAS_RUNS
    runs = (head, (tail[0], (obj_vram - tail[0]) // 64), extra)
    originals = {key: hud.graphics[index * 64:(index + 1) * 64] for index, key in enumerate(ids)}
    keep = tuple(key for key in ids if key in retained)
    graphics = b"".join(originals[key] for key in keep)
    if (len(graphics) + len(obj_graphics) >= len(hud.graphics) or len(keep) > len(tile_ids(runs))
            or obj_vram < tail[0]):
        raise ValueError("HUD overlays did not reclaim VRAM within the existing allocation")
    remap = dict(zip(keep, tile_ids(runs)[:len(keep)], strict=True))
    for row in range(3):
        face = tuple(remap[tile] for tile in hud.variants[21][row * 3:row * 3 + 3])
        ammo = tuple(remap[tile] for tile in hud.map_words[row * 32 + 20:row * 32 + 23])
        if any(end != start + 2 or mid != start + 1 for start, mid, end in (face, ammo)):
            raise ValueError("HUD overlays split a directly uploaded portrait or icon row")
    first_tile = 256 + (obj_vram - tail[0]) // 32
    words = (0, *((first_tile + tile) | (bank << 9) | 0x3000 for bank, tile in descriptors))
    obj_glyphs = bytearray()
    for row in codes:
        records = [(column % 3 * 8, column // 3 * 8, words[code])
                   for column, code in enumerate(row) if code]
        # Local y=$28 becomes offscreen y=$F0 after adding the digit's y=$C8.
        records.extend([(0, 0xF0 - WORLD_LINES, 0)] * (OBJ_PER_DIGIT - len(records)))
        obj_glyphs.extend(b"".join(pack("<BBH", *record) for record in records))
    return replace(hud, graphics=graphics, tile_count=len(keep),
                   map_words=tuple(remap[tile] for tile in hud.map_words),
                   variants=tuple(tuple(remap[tile] for tile in glyph)
                                  for glyph in (*glyphs, *hud.variants[21:])),
                   armor_digits=tuple(remap[tile] for tile in hud.armor_digits), atlas_runs=runs,
                   obj_graphics=obj_graphics, obj_glyphs=bytes(obj_glyphs),
                   obj_vram=obj_vram, obj_first=OBJ_FIRST, obj_count=OBJ_COUNT,
                   obj_replaced_tiles=hud.tile_count - len(keep))
