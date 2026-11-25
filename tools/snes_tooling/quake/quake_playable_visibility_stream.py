"""Build guarded face visibility rows for a playable MSU archive."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct

from snes_tooling.quake.quake_bsp_assets import decompress_pvs
from snes_tooling.quake.quake_playable_layout import HALFBANK
from snes_tooling.quake.quake_playable_relocation import WORLD_PVS, integer_definitions


@dataclass(frozen=True)
class VisibilityStream:
    payload: bytes
    row_count: int
    row_bytes: int
    stride: int

    def include(self, offset: int) -> bytes:
        # Archive header, then two stored bytes for each source byte.
        seek = 64 + 2 * offset
        if not 0 <= seek < seek + 2 * len(self.payload) <= 1 << 32:
            raise ValueError("visibility stream escapes the MSU seek range")
        return (
            "PLAYABLE_VISIBILITY_STREAM = 1\n"
            "VISIBILITY_STREAM_REQUEST = $51E1\n"
            f"VISIBILITY_STREAM_SEEK = ${seek:08X}\n"
            f"VISIBILITY_STREAM_SHIFT = {self.stride.bit_length()}\n"
            f"VISIBILITY_STREAM_ROW_COUNT = {self.row_count}\n"
            f"VISIBILITY_STREAM_ROW_BYTES = {self.row_bytes}\n"
        ).encode("ascii")


def build_visibility_stream(data: Path) -> VisibilityStream:
    fields = integer_definitions((data / "QuakeBSPScene.i").read_text(encoding="utf-8"))
    row_bytes = fields["BSP_WORLD_FACE_BITSET_BYTES"]
    row_count = fields["BSP_WORLD_VIS_LEAF_COUNT"] + 1
    first_bank = fields["BSP_WORLD_PVS_FIRST_GSU_ROM_BANK"]
    chunk_count = fields["BSP_WORLD_PVS_CHUNK_COUNT"]
    chunks = [(data / f"QuakeBSPWorldPVS{i}.bin").read_bytes() for i in range(chunk_count)]
    directory = (data / "QuakeBSPWorldPVSDirectory.bin").read_bytes()
    guard = (data / "QuakeBSPWorldPVSGuards.bin").read_bytes()
    if len(directory) != row_count * WORLD_PVS.size or not 0 < row_bytes < HALFBANK:
        raise ValueError("invalid world visibility directory or row width")
    guards = tuple(struct.iter_unpack("<HB", guard))
    if len(guards) != fields["BSP_WORLD_PVS_GUARD_RECORD_COUNT"] or any(
        index >= row_bytes or not mask for index, mask in guards
    ):
        raise ValueError("invalid world visibility guard")
    # A power-of-two stride needs no mutable index table or MMIO multiplier.
    stride = 1 << (row_bytes + 3).bit_length()
    rows = bytearray(row_count * stride)
    for leaf, (address, size, visible, bank, _flags) in enumerate(WORLD_PVS.iter_unpack(directory)):
        chunk, offset = bank - first_bank, address - HALFBANK
        if not 0 <= chunk < len(chunks) or not 0 <= offset < offset + size <= len(chunks[chunk]):
            raise ValueError(f"world visibility leaf {leaf} escapes its source chunk")
        row = bytearray(decompress_pvs(chunks[chunk][offset:offset + size], 0, row_bytes * 8))
        for index, mask in guards:
            row[index] |= mask
        if int.from_bytes(row, "little").bit_count() != visible:
            raise ValueError(f"world visibility leaf {leaf} disagrees with the guarded face count")
        start = leaf * stride
        struct.pack_into("<HH", rows, start, size, visible)
        rows[start + 4:start + 4 + row_bytes] = row
    return VisibilityStream(bytes(rows), row_count, row_bytes, stride)
