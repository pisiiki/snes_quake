"""Retain WinQuake's original Sbar_IntermissionOverlay artwork and coordinates."""
from collections import defaultdict
from struct import iter_unpack, pack, unpack_from

from snes_tooling.quake.quake_bsp_assets import texture_tilemap_bytes
from snes_tooling.quake.quake_status_hud import wad_pictures

FILE = "QuakeIntermission.qim"
# Right-aligned 3-digit minutes, seconds, secrets, total secrets, kills, total kills.
SLOTS = ([(x, 64) for x in (160, 184, 208, 246, 266)] +
         [(x, y) for y in (104, 144) for x in (160, 184, 208, 240, 264, 288)])
RECORDS = 1 + 10 * len(SLOTS)


def pictures(archive):
    def pic(blob):
        width, height = unpack_from("<II", blob)
        pixels = blob[8:]
        if len(pixels) != width * height:
            raise ValueError("invalid intermission qpic")
        return width, height, pixels

    wad = wad_pictures(archive.read("gfx.wad"))
    return [pic(archive.read("gfx/complete.lmp")), pic(archive.read("gfx/inter.lmp")),
            wad[b"NUM_COLON"], wad[b"NUM_SLASH"], *(wad[f"NUM_{n}".encode()] for n in range(10))]


def source_graphics(archive):
    return b"QIM1" + b"".join(pack("<HH", w, h) + pixels for w, h, pixels in pictures(archive))


def planar_stream(archive, palette):
    pics = pictures(archive)
    tilemap = [v for (v,) in iter_unpack("<H", texture_tilemap_bytes())]
    packets = []
    for width, height in ((128, 100), (85, 67)):
        def command(layers):
            cells = defaultdict(lambda: bytearray(9))
            for source, ox, oy in layers:
                pw, ph, pixels = pics[source]
                for y in range((oy * height + 199) // 200, ((oy + ph) * height + 199) // 200):
                    for x in range((ox * width + 319) // 320, ((ox + pw) * width + 319) // 320):
                        v = pixels[(y * 200 // height - oy) * pw + x * 320 // width - ox]
                        if v == 255 and source != 0:
                            continue
                        if width == 128:
                            # X2 mirrors logical sample pairs. Reflecting the raw
                            # 256-dot tilemap chooses the other pixel in each
                            # mosaic pair on these packed 8bpp source tiles.
                            u, vrow = 2 * (width - 1 - x), 2 * y
                            tile = tilemap[(vrow // 8) * 32 + u // 8]
                            row = 7 - vrow % 8 if tile & 0x8000 else vrow % 8
                            offset = (tile & 1023) * 64 + row * 2
                            bit = u % 8 if tile & 0x4000 else 7 - u % 8
                        else:
                            sample_x = width - 1 - x
                            offset = (y // 8 * 16 + sample_x // 8) * 64 + ((y % 8 * 3) & 7) * 2
                            bit = 7 - ((sample_x % 8 * 3) & 7)
                        value = palette[v]
                        cell = cells[offset]
                        pixel = 1 << bit
                        cell[0] |= pixel
                        for plane in range(8):
                            if value & (1 << plane):
                                cell[1 + plane] |= pixel
            return pack("<H", len(cells)) + b"".join(pack("<H", off) + cell for off, cell in sorted(cells.items()))

        packets.append(command(((0, 64, 24), (1, 0, 56), (2, 234, 64), (3, 232, 104), (3, 232, 144))))
        packets.extend(command(((4 + digit, x, y),)) for x, y in SLOTS for digit in range(10))
    for start in (0, RECORDS):
        maximum = len(packets[start]) + sum(max(len(packet) - 2 for packet in packets[pos:pos + 10])
                                           for pos in range(start + 1, start + RECORDS, 10))
        if maximum > (8192 if start else 8192 - 1024):
            raise ValueError("intermission overlay overlaps the live thinker cache")
    index = bytearray()
    payload = bytearray()
    for packet in packets:
        index.extend(pack("<I", len(packets) * 4 + len(payload)))
        payload.extend(packet)
    if len(index) + len(payload) > 65536:
        raise ValueError("intermission packet offsets exceed their native word")
    return bytes(index + payload)
