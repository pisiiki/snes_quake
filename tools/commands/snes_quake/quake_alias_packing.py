"""Halfbank packing and address mapping for Quake alias assets."""

from __future__ import annotations

from dataclasses import dataclass


HALFBANK_BYTES = 0x8000
STORAGE_PHYSICAL_HALFBANKS = (
    tuple(range(87, 94))
    + (14,)
    + tuple(range(56, 63))
    + (37,)
    + (15,)
)
FIRST_PHYSICAL_HALFBANK = STORAGE_PHYSICAL_HALFBANKS[0]
MAX_PHYSICAL_HALFBANKS = len(STORAGE_PHYSICAL_HALFBANKS)


@dataclass(frozen=True, slots=True)
class Location:
    chunk: int
    offset: int
    bank: int
    address: int

    @property
    def flat_offset(self) -> int:
        return self.chunk * HALFBANK_BYTES + self.offset


class HalfbankPacker:
    def __init__(
        self,
        reserved_bytes: int,
        *,
        max_chunks: int = MAX_PHYSICAL_HALFBANKS,
    ) -> None:
        if not 0 <= reserved_bytes <= HALFBANK_BYTES:
            raise ValueError("invalid first-halfbank reservation")
        if not 1 <= max_chunks <= MAX_PHYSICAL_HALFBANKS:
            raise ValueError("invalid alias halfbank limit")
        self.chunks = [bytearray(b"\xff" * HALFBANK_BYTES)]
        self.cursors = [reserved_bytes]
        self.chunk = 0
        self.cursor = reserved_bytes
        self.payload_bytes = 0
        self.max_chunks = max_chunks

    def place(self, payload: bytes, *, alignment: int = 1) -> Location:
        if not payload:
            raise ValueError("cannot place an empty alias asset block")
        if len(payload) > HALFBANK_BYTES:
            raise ValueError("alias asset block crosses a 32 KiB halfbank")
        if alignment <= 0 or alignment & (alignment - 1):
            raise ValueError("alias asset alignment must be a positive power of two")
        cursor = (self.cursor + alignment - 1) & -alignment
        if cursor + len(payload) > HALFBANK_BYTES:
            next_chunk = self.chunk + 1
            if next_chunk >= self.max_chunks:
                raise ValueError(
                    f"alias assets exceed {self.max_chunks} reserved GSU halfbanks"
                )
            self.chunk = next_chunk
            self.chunks.append(bytearray(b"\xff" * HALFBANK_BYTES))
            self.cursors.append(0)
            cursor = 0
        self.chunks[self.chunk][cursor : cursor + len(payload)] = payload
        self.cursor = cursor + len(payload)
        self.cursors[self.chunk] = self.cursor
        self.payload_bytes += len(payload)
        bank, address = gsu_location(self.chunk, cursor)
        return Location(self.chunk, cursor, bank, address)

    def place_compact(self, payload: bytes, *, alignment: int = 1) -> Location:
        """Best-fit one block into any existing halfbank tail, adding one if needed."""

        location = self.try_place_compact(payload, alignment=alignment)
        if location is None:
            raise ValueError(
                f"alias assets exceed {self.max_chunks} reserved GSU halfbanks"
            )
        return location

    def try_place_compact(
        self, payload: bytes, *, alignment: int = 1
    ) -> Location | None:
        """Best-fit a block without mutating the packer when capacity is exhausted."""

        if not payload:
            raise ValueError("cannot place an empty alias asset block")
        if len(payload) > HALFBANK_BYTES:
            raise ValueError("alias asset block crosses a 32 KiB halfbank")
        if alignment <= 0 or alignment & (alignment - 1):
            raise ValueError("alias asset alignment must be a positive power of two")
        candidates: list[tuple[int, int, int]] = []
        for chunk, tail in enumerate(self.cursors):
            cursor = (tail + alignment - 1) & -alignment
            remaining = HALFBANK_BYTES - cursor - len(payload)
            if remaining >= 0:
                candidates.append((remaining, chunk, cursor))
        if not candidates:
            if len(self.chunks) >= self.max_chunks:
                return None
            return self.place(payload, alignment=alignment)
        _remaining, chunk, cursor = min(candidates)
        self.chunks[chunk][cursor : cursor + len(payload)] = payload
        self.cursors[chunk] = cursor + len(payload)
        if chunk == self.chunk:
            self.cursor = self.cursors[chunk]
        self.payload_bytes += len(payload)
        bank, address = gsu_location(chunk, cursor)
        return Location(chunk, cursor, bank, address)


def gsu_location(chunk: int, offset: int = 0) -> tuple[int, int]:
    """Map QBA1 physical halfbanks to FX3 GSU ROMB addresses."""

    if not 0 <= chunk < MAX_PHYSICAL_HALFBANKS:
        raise ValueError("alias chunk is outside its reserved physical halfbanks")
    if not 0 <= offset < HALFBANK_BYTES:
        raise ValueError("alias offset is outside a physical halfbank")
    physical = STORAGE_PHYSICAL_HALFBANKS[chunk]
    if physical < 64:
        return physical, 0x8000 + offset
    relative = physical - 64
    return 0x60 + (relative >> 1), (0x8000 if relative & 1 else 0) + offset


def cpu_load_address(chunk: int) -> int:
    """Return the linker address for one GSU-direct alias halfbank."""

    if not 0 <= chunk < MAX_PHYSICAL_HALFBANKS:
        raise ValueError("alias chunk is outside its reserved physical halfbanks")
    physical = STORAGE_PHYSICAL_HALFBANKS[chunk]
    if physical < 64:
        return 0x808000 + physical * 0x10000
    if physical >= 96:
        return 0xC00000 + (physical - 96) * HALFBANK_BYTES
    return 0x600000 + (physical - 64) * HALFBANK_BYTES
