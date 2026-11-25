"""Generate the playable 256×24 HUD from indexed Quake shareware art."""

from dataclasses import dataclass
from struct import pack, unpack_from

from snes_tooling.quake.quake_bsp_assets import PakArchive, locate_quake_pak, snes_color

WIDTH = 256
HEIGHT = 24
DIGITS = (72, 96, 120, 184, 208, 232)
FACE = 48
# Weapon OBJ owns D5C0-DFFF. The third run fits between the visible
# rows of the two 32x32 status maps (A ends at E700; B starts at EE40).
ATLAS_RUNS = ((0x9000, 160), (0xC000, 87), (0xE700, 29))


def wad_pictures(wad):
    magic, count, directory = unpack_from("<4sII", wad)
    if magic != b"WAD2" or directory + count * 32 > len(wad):
        raise ValueError("invalid Quake HUD WAD directory")
    pictures = {}
    for i in range(count):
        offset, disk, size, kind, compressed, _, name = unpack_from(
            "<IIIBBH16s", wad, directory + i * 32)
        if kind == 0x42:
            if compressed or size != disk or size < 8 or offset + size > len(wad):
                raise ValueError("invalid Quake HUD WAD picture")
            width, height = unpack_from("<II", wad, offset)
            pixels = wad[offset + 8:offset + size]
            if len(pixels) != width * height:
                raise ValueError("Quake HUD WAD picture has an invalid size")
            pictures[name.rstrip(b"\0").upper()] = width, height, pixels
    return pictures


def planar_tile(pixels, planes=8):
    return bytes(
        sum(((pixels[y * 8 + x] >> (plane + bit)) & 1) << (7 - x) for x in range(8))
        for plane in range(0, planes, 2) for y in range(8) for bit in range(2)
    )


def tile_pixels(pixels, width):
    for y in range(0, HEIGHT, 8):
        for x in range(0, width, 8):
            yield b"".join(pixels[i * width + x:i * width + x + 8] for i in range(y, y + 8))


def overlay(base, width, picture, x=0):
    w, h, pixels = picture
    for y in range(h):
        for column in range(w):
            index = pixels[y * w + column]
            if index != 255:
                base[y * width + x + column] = index


@dataclass(frozen=True)
class StatusHud:
    graphics: bytes
    map_words: tuple
    variants: tuple
    tile_count: int
    armor_digits: tuple
    quad_face: bytes
    nail_icon: bytes
    pain_faces: bytes
    atlas_runs: tuple = ATLAS_RUNS
    obj_graphics: bytes = b""
    obj_glyphs: bytes = b""
    obj_vram: int = 0
    obj_first: int = 128
    obj_count: int = 0
    obj_replaced_tiles: int = 0

    @property
    def priority(self):
        return 0x2000 if self.obj_graphics else 0

    @property
    def maps(self):
        words = tuple(tile | self.priority for tile in self.map_words)
        words += tuple(tile - 0x100 for tile in words)
        return pack(f"<{len(words)}H", *words)

    @property
    def glyphs(self):
        words = tuple(tile for glyph in self.variants for tile in glyph) + self.armor_digits
        tiles = pack(f"<{len(words)}H", *(tile | self.priority for tile in words))
        return tiles + self.quad_face + self.nail_icon + self.pain_faces + self.obj_glyphs + self.obj_graphics

    @property
    def payload(self):
        return self.graphics + self.maps + self.glyphs

    def assembly(self, cpu_address, maps, glyphs):
        second = min(self.tile_count, self.atlas_runs[0][1]) * 64
        middle = min(max(self.tile_count - self.atlas_runs[0][1], 0), self.atlas_runs[1][1]) * 64
        entries = len(self.map_words) * 2
        quad = glyphs + len(self.variants) * 18 + len(self.armor_digits) * 2
        nails = quad + len(self.quad_face)
        face = self.variants[21]
        rows = "".join(f"HUD_FACE_ROW_{i} = ${face[3*i]*64:04X}\n" for i in range(3))
        rows += "".join(f"HUD_AMMO_ROW_{i} = ${self.map_words[32*i+20]*64:04X}\n" for i in range(3))
        obj = ""
        if self.obj_graphics:
            obj_glyphs = nails + len(self.nail_icon) + len(self.pain_faces)
            obj_tiles = obj_glyphs + len(self.obj_glyphs)
            obj = (
                f"HUD_OBJ_GLYPHS = ${obj_glyphs:06X}\n"
                f"HUD_OBJ_TILES = ${obj_tiles:06X}\n"
                f"HUD_OBJ_BYTES = {len(self.obj_graphics)}\n"
                f"HUD_OBJ_VRAM = ${self.obj_vram:04X}\n"
                f"HUD_OBJ_FIRST = {self.obj_first}\n"
                f"HUD_OBJ_COUNT = {self.obj_count}\n"
            )
        return (
            rows +
            f"HUD_NAIL_ICON = ${nails:06X}\n"
            f"HUD_QUAD_FACE = ${quad:06X}\n"
            f"HUD_PAIN_FACES = ${nails + len(self.nail_icon):06X}\n"
            f"HUD_ATLAS = ${cpu_address:06X}\n"
            f"HUD_ATLAS_SPLIT = {second}\n"
            f"HUD_ATLAS_TAIL_BYTES = {middle}\n"
            f"HUD_ATLAS_EXTRA_BYTES = {len(self.graphics) - second - middle}\n"
            f"HUD_MAP_A_DATA = ${maps:06X}\n"
            f"HUD_MAP_B_DATA = ${maps + entries:06X}\n"
            f"HUD_VARIANT_DATA = ${glyphs:06X}\n"
            f"HUD_ARMOR_DIGITS = ${glyphs + len(self.variants) * 18:06X}\n"
            f"HUD_MAP_BYTES = {entries}\n" + obj
        ).encode("ascii")


def build_status_hud(pak_path=None, *, palette_map=None):
    pak = PakArchive(locate_quake_pak(pak_path))
    pictures = wad_pictures(pak.read("gfx.wad"))
    palette = pak.read("gfx/palette.lmp")
    colors = [snes_color(tuple(palette[i:i + 3])) for i in range(0, 768, 3)]
    # BG color index zero is transparent. Use an exactly equal palette entry
    # for opaque black in the original art.
    black = colors.index(colors[0], 1)
    width, height, original = pictures[b"SBAR"]
    if (width, height) != (320, HEIGHT):
        raise ValueError("unsupported original Quake status bar size")
    bar = bytearray(b"".join(original[y * width:y * width + 3]
                           + original[y * width + 67:(y + 1) * width] for y in range(HEIGHT)))
    well = b"".join(bar[y * WIDTH + DIGITS[0]:y * WIDTH + DIGITS[0] + 24] for y in range(HEIGHT))
    for x in DIGITS:
        for y in range(HEIGHT):
            bar[y * WIDTH + x:y * WIDTH + x + 24] = well[y * 24:(y + 1) * 24]
    ammo_back = bytearray(b"".join(bar[y*WIDTH+160:y*WIDTH+184] for y in range(HEIGHT)))
    overlay(bar, WIDTH, pictures[b"SB_SHELLS"], 160)
    face = bytearray(b"".join(bar[y * WIDTH + FACE:y * WIDTH + FACE + 24] for y in range(HEIGHT)))
    atlas = {}
    ids = [addr // 64 + tile for addr, count in ATLAS_RUNS for tile in range(count)]
    def register(pixels, width):
        result = []
        indexed = bytes(pixels).replace(b"\0", bytes([black]))
        if palette_map is not None:
            indexed = indexed.translate(palette_map)
        for tile in tile_pixels(indexed, width):
            if tile not in atlas:
                if len(atlas) == len(ids):
                    raise ValueError("status HUD exceeds its shared VRAM atlas")
                atlas[tile] = ids[len(atlas)]
            result.append(atlas[tile])
        return tuple(result)

    map_words = register(bar, WIDTH)
    variants = [register(well, 24)]
    for prefix in (b"NUM_", b"ANUM_"):
        for digit in range(10):
            glyph = bytearray(well)
            overlay(glyph, 24, pictures[prefix + str(digit).encode("ascii")])
            variants.append(register(glyph, 24))
    for index in range(1, 6):
        glyph = bytearray(face)
        overlay(glyph, 24, pictures[f"FACE{index}".encode("ascii")])
        variants.append(register(glyph, 24))
    # The 256-wide bar leaves 48 pixels for armor. Use the original 24px icon
    # and one 8px tile per digit, keeping all armor graphics resident.
    icon_base = b"".join(bar[y * WIDTH:y * WIDTH + 24] for y in range(HEIGHT))
    variants.append(register(icon_base, 24))
    for name in (b"SB_ARMOR1", b"SB_ARMOR2"):
        image = bytearray(icon_base)
        overlay(image, 24, pictures[name])
        variants.append(register(image, 24))
    digits = []
    for digit in range(10):
        _, _, pixels = pictures[b"NUM_" + str(digit).encode("ascii")]
        # Sample the center of each 3x3 source cell against an opaque dark well.
        tile = bytes(v if v != 255 else black for y in range(8) for x in range(8)
                     for v in (pixels[(3*y+1)*24+3*x+1],))
        digits.append(register(tile * 3, 8)[0])
    # FACE1's nine tiles occupy three short, contiguous rows in the base atlas.
    # Powerups can replace them without sacrificing nine more resident tiles.
    slots = variants[21]
    face_cells = {y * 32 + FACE//8 + x for y in range(3) for x in range(3)}
    if (any(slots[3*y+x] != slots[3*y]+x for y in range(3) for x in range(3))
            or any(tile in slots for n, tile in enumerate(map_words) if n not in face_cells)
            or any(tile in slots for n, variant in enumerate(variants) if n != 21 for tile in variant)
            or set(slots).intersection(digits)):
        raise ValueError("HUD Quad face requires nine replaceable FACE1 tiles")
    def portrait(name):
        image = bytearray(face)
        overlay(image, 24, pictures[name])
        indexed = bytes(image).replace(b"\0", bytes([black]))
        if palette_map is not None:
            indexed = indexed.translate(palette_map)
        return b"".join(planar_tile(tile) for tile in tile_pixels(indexed, 24))

    quad = portrait(b"FACE_QUAD")
    pain_faces = b"".join(portrait(f"FACE_P{i}".encode("ascii")) for i in range(1, 6))
    ammo_cells = [y*32+x for y in range(3) for x in range(20, 23)]
    ammo_ids = [map_words[n] for n in ammo_cells]
    other_ids = {tile for n, tile in enumerate(map_words) if n not in ammo_cells}
    other_ids.update(tile for variant in variants for tile in variant)
    if (len(set(ammo_ids)) != 9 or set(ammo_ids).intersection(other_ids) or set(ammo_ids).intersection(digits)
            or any(ammo_ids[3*y+x] != ammo_ids[3*y]+x for y in range(3) for x in range(3))):
        raise ValueError("HUD nails require the nine exclusive shell icon tiles")
    overlay(ammo_back, 24, pictures[b"SB_NAILS"])
    ammo = bytes(ammo_back).replace(b"\0", bytes([black]))
    if palette_map is not None:
        ammo = ammo.translate(palette_map)
    nail_icon = b"".join(planar_tile(tile) for tile in tile_pixels(ammo, 24))
    return StatusHud(b"".join(planar_tile(tile) for tile in atlas), map_words, tuple(variants),
                     len(atlas), tuple(digits), quad, nail_icon, pain_faces)
