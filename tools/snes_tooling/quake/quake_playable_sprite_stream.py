"""Mandatory MSU pixel chunks behind virtual QBA sprite pointer tags."""
import struct

from snes_tooling.quake.quake_alias_format import HEADER, SPRITE_DIRECTORY
from snes_tooling.quake.quake_playable_layout import HALFBANK, gsu_offset

PREFIX = "BSP_ALIAS_"
VIRTUAL_BANK = 0x80
CACHE_BYTES = 0x600


def source_spans(layout, module):
    return sorted((int(name[len(PREFIX):]), span) for (owner, name), span in layout.spans.items()
                  if owner == module and name.startswith(PREFIX) and name[len(PREFIX):].isdigit())


def pixel_mapper(layout, module):
    """Only QBA sprite pixels may acquire a virtual tag; control stays in ROM."""
    tail = getattr(layout, "sprite_tails", {}).get(module)
    if tail is not None:
        first = layout.spans[module, "BSP_ALIAS_0"]
        tail_start = first.original_offset + len(first.payload)
        tail_bank = VIRTUAL_BANK + len(source_spans(layout, module))
        if tail_bank > 0xff:
            raise ValueError("sprite tail virtual bank exceeds one byte")

    def pointer(bank, address):
        offset = gsu_offset(bank, address)
        if tail is not None and tail_start <= offset < tail_start + len(tail[1]):
            return tail_bank, offset - tail_start
        matches = [span for span in layout.spans.values() if span.module == module
                   and span.original_offset <= offset < span.original_offset + len(span.payload)]
        if len(matches) != 1:
            raise ValueError("sprite pixel pointer lacks one original alias span")
        span = matches[0]
        suffix = span.name.removeprefix(PREFIX)
        if not span.name.startswith(PREFIX) or not suffix.isdigit():
            raise ValueError("sprite pixel pointer leaves its original QBA family")
        index = int(suffix)
        placement = layout.placements[span.key]
        if placement.storage == "msu":
            if not 1 <= index < VIRTUAL_BANK or len(span.payload) != HALFBANK:
                raise ValueError("invalid virtual sprite pixel chunk")
            return VIRTUAL_BANK + index, offset - span.original_offset
        if index or placement.storage != "gsu":
            raise ValueError("only sprite control chunk zero may remain resident")
        return layout.relocate(module, bank, address)
    return pointer


def stream_files(layout, module):
    """Emit actual encoded MSU file seek bases, not GSU or CPU mirror addresses."""
    spans = source_spans(layout, module)
    tail = getattr(layout, "sprite_tails", {}).get(module)
    if not spans or [index for index, _ in spans] != list(range(len(spans))):
        raise ValueError("streamed QBA chunks must be a zero-based source family")
    if len(spans) > VIRTUAL_BANK:
        raise ValueError("sprite virtual bank tag exceeds one byte")
    header = HEADER.unpack_from(spans[0][1].payload)
    if header[:3] != (b"QBA1", 6, HEADER.size) or header[8] != len(spans):
        raise ValueError("streamed sprite header disagrees with its source spans")
    mapper = pixel_mapper(layout, module)
    for sprite in range(header[4]):
        row = SPRITE_DIRECTORY.unpack_from(spans[0][1].payload, header[10] + sprite * SPRITE_DIRECTORY.size)
        bank, address = mapper(row[0], row[2])
        extent = len(tail[1]) if tail is not None and bank == VIRTUAL_BANK + len(spans) else HALFBANK
        if bank >= VIRTUAL_BANK and (not 0 < row[3] * row[4] <= CACHE_BYTES
                                    or address + row[3] * row[4] > extent):
            raise ValueError("streamed sprite raster exceeds its fixed cache/source extent")
    table = bytearray()
    for index, span in spans:
        placement = layout.placements[span.key]
        if not index:
            if placement.storage != "gsu":
                raise ValueError("sprite control chunk zero must remain resident")
            seek = 0
        else:
            if placement.storage != "msu" or placement.size != HALFBANK:
                raise ValueError("sprite pixel chunks must be complete mandatory MSU images")
            seek = 64 + 2 * placement.offset
            if not 0 <= seek <= 0xFFFFFFFF:
                raise ValueError("encoded sprite MSU seek exceeds uint32")
        table += struct.pack("<I", seek)
    if tail is not None:
        table += struct.pack("<I", 64 + 2 * tail[0])
    include = ("; Generated final-module sprite stream binding; source baselines omit it.\n"
        ".ifndef __QUAKE_PLAYABLE_SPRITE_STREAM_I__\n"
        "__QUAKE_PLAYABLE_SPRITE_STREAM_I__ = 1\n"
        + ("PLAYABLE_SPRITE_STREAM = 1\n" if len(spans) > 1 else "")
        +
        f"SPRITE_STREAM_BANK_COUNT = {len(table) // 4}\n"
        "SPRITE_STREAM_BANK_RECORD_BYTES = 4\n"
        ".endif\n").encode("ascii")
    return {"Data/QuakeBSPPlayableSpriteStream.i": include,
            "Data/QuakeBSPPlayableSpriteStream.bin": bytes(table)}
