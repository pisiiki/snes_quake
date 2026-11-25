"""Build the console rows and mixed-case font used by E1M1 pickups."""

from struct import pack, unpack_from
from textwrap import wrap

from snes_tooling.quake.quake_bsp_assets import PakArchive, locate_quake_pak

# IDs follow PickupNotice.s. The last pickup wraps into the following row.
MESSAGES = (
    "You got the shells", "You got the nails", "You got the nailgun", "You got armor",
    "You receive 15 health", "You receive 25 health", "You receive 100 health",
    "You got the Quad Damage", "You got the Biosuit", "You get 5 shells",
    "You got the Double-barrelled Shotgun",
)
MAP_VRAM = 0xBA00
FONT_VRAM = 0xBB00


def console_font(wad):
    count, directory = unpack_from("<II", wad, 4)
    for i in range(count):
        offset, stored, size, kind, compression, _, name = unpack_from(
            "<IIIBBH16s", wad, directory + 32 * i)
        if name.rstrip(bytes(1)).upper() == b"CONCHARS":
            if (kind, compression, stored, size) != (68, 0, 16384, 16384):
                raise ValueError("unexpected shareware console font format")
            return wad[offset:offset + size]
    raise ValueError("missing shareware CONCHARS")


def build_pickup_display(pak_path=None):
    font = console_font(PakArchive(locate_quake_pak(pak_path)).read("gfx.wad"))
    rows = [""] + [row for message in MESSAGES for row in wrap(message, width=30, break_on_hyphens=False)]
    if len(rows) != 13 or rows[-1] != "Shotgun":
        raise ValueError("pickup message IDs disagree with the client console width")
    chars = sorted(set("".join(rows)) - {" "})
    graphics = bytearray()
    tiles = {" ": 0xC0}
    for char in chars:
        tiles[char] = 0x2000 + (FONT_VRAM - 0x6000 + len(graphics)) // 32
        origin = (ord(char) // 16) * 8 * 128 + (ord(char) % 16) * 8
        mask = [sum(int(bool(font[origin + 128*y + x])) << (7-x) for x in range(8)) for y in range(8)]
        graphics.extend(value for row in mask for value in (0, row))
        graphics.extend(value for row in mask for value in (row, row))
    if FONT_VRAM + len(graphics) > 0xC000:
        raise ValueError("pickup glyphs overlap the HUD atlas tail")
    maps = b"".join(pack("<32H", *(tiles[c] for c in (" " + row).ljust(32))) for row in rows)
    return maps, bytes(graphics)


def build_pickup_blend():
    """One small component table covers all scene palettes, flash ages and artifacts."""
    channels = bytearray()
    for channel, target in enumerate((215, 186, 69)):
        for artifact, power in (((0, 0, 0), 0), ((0, 0, 255), 30), ((0, 255, 0), 20)):
            for remaining in range(1, 31):
                strength = 50 * remaining // 30
                for value in range(32):
                    source = value * 8
                    bonus = source + ((target - source) * strength // 256)
                    final = bonus + ((artifact[channel] - bonus) * power // 256)
                    channels.append(final >> 3)
    # A16 reads one byte of lookahead. Keep it in the same bank, too.
    return bytes(channels) + bytes(1)


def pack_pickup_blend(channels):
    """Encode each 32-color row as a starting color and 31 one-bit increments."""
    if len(channels) != 3 * 90 * 32 + 1:
        raise ValueError("unexpected pickup blend table size")
    rows = bytearray()
    for start in range(0, len(channels) - 1, 32):
        row = channels[start:start + 32]
        steps = [b - a for a, b in zip(row, row[1:])]
        if any(step not in (0, 1) for step in steps):
            raise ValueError("pickup blend row is not monotone in unit steps")
        rows.extend(pack("<BI", row[0], sum(step << i for i, step in enumerate(steps))))
    return bytes(rows)
