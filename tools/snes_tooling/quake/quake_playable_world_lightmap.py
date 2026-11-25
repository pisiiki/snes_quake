"""Keep canonical packed world-lightmap samples in the playable MSU sidecar."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from struct import Struct

from snes_tooling.quake.quake_lightmap_packing import (
    lightmap_location_sample_offset, unpack_six_bit_samples,
)
from snes_tooling.quake.quake_playable_relocation import LIGHTMAP, integer_definitions


RESIDENT_GRIDS = "BSP_WORLD_LIGHTMAP_RESIDENT"
RESIDENT_ORIGINALS = "BSP_WORLD_LIGHTMAP_RESIDENT_ORIGINALS"
RESIDENT_BANK_TAG = 0x80
RESIDENT_NIBBLE_WIDTH_TAG = 0x80
ORIGINAL_NIBBLE_TAG = 0x80
LIGHTMAP_POINTER = Struct("<BH")
ORIGINAL_POINTER = Struct("<HBH")


@dataclass(frozen=True)
class ResidentLightmaps:
    payload: bytes
    pointers: tuple[tuple[int, int, int, int], ...]
    nibble_offsets: frozenset[int]

    @property
    def originals(self):
        return b"".join(
            ORIGINAL_POINTER.pack(face, bank | ORIGINAL_NIBBLE_TAG if offset in self.nibble_offsets else bank, address)
            for face, bank, address, offset in self.pointers
        )

    def relocate(self, directory, bank, address):
        if not 0 <= bank < 0x70 or not 0x8000 <= address < address + len(self.payload) <= 0x10000:
            raise ValueError("Resident lightmaps must fit a GSU ROM bank's upper half")
        result = bytearray(directory)
        for face, original_bank, original_address, offset in self.pointers:
            at = face * LIGHTMAP.size
            if LIGHTMAP_POINTER.unpack_from(result, at) != (original_bank, original_address):
                raise ValueError("Resident lightmap directory changed after selection")
            LIGHTMAP_POINTER.pack_into(result, at, bank | RESIDENT_BANK_TAG, address + offset)
            if offset in self.nibble_offsets:
                result[at + LIGHTMAP_POINTER.size] |= RESIDENT_NIBBLE_WIDTH_TAG
        return bytes(result)


def resident_nibble_grid(raw, count):
    """Encode a six-bit grid whose exact range fits in four-bit deltas."""
    samples = unpack_six_bit_samples(raw, 0, count)
    base = min(samples)
    if max(samples) - base > 15:
        return None
    deltas = bytes(sample - base for sample in samples)
    output = bytearray((base | 0xc0,))
    for index in range(0, count - 1, 2):
        output.append(deltas[index] | deltas[index + 1] << 4)
    if count & 1:
        output.append(deltas[-1])
    return bytes(output)


def build_resident_lightmaps(directory, streamed, faces, *, nibbles=False):
    if not faces or any(type(face) is not int or not 0 <= face < streamed.face_count for face in faces):
        raise ValueError("Resident lightmap selection has an invalid face index")
    if len(set(faces)) != len(faces):
        raise ValueError("Resident lightmap selection contains a repeated face")
    grids = {False: [], True: []}
    for face in sorted(faces):
        at = face * LIGHTMAP.size
        bank, address, width, height, _, _ = LIGHTMAP.unpack_from(directory, at)
        start = address - 0x8000
        count = width * height
        size = (3 * count + 3) // 4
        if not streamed.first_bank <= bank < streamed.first_bank + len(streamed.chunks):
            raise ValueError(f"Resident lightmap face {face} has no canonical grid")
        raw = streamed.chunks[bank - streamed.first_bank][start:start + size]
        if len(raw) != size or not size:
            raise ValueError(f"Resident lightmap face {face} escapes its source carrier")
        if nibbles and width >= RESIDENT_NIBBLE_WIDTH_TAG:
            raise ValueError(f"Resident lightmap face {face} uses the reserved nibble width bit")
        compact = resident_nibble_grid(raw, count) if nibbles else None
        if compact is not None and len(compact) < len(raw):
            grids[True].append((face, bank, address, compact))
        else:
            grids[False].append((face, bank, address, raw))

    payload = bytearray()
    pointers = []
    nibble_offsets = set()
    for compact, rows in grids.items():
        offsets = {}
        for face, bank, address, raw in rows:
            if raw not in offsets:
                if not compact:
                    payload.extend(bytes(-len(payload) % 3))
                offset = len(payload)
                offsets[raw] = offset
                if compact:
                    nibble_offsets.add(offset)
                payload.extend(raw)
            pointers.append((face, bank, address, offsets[raw]))
    if len(payload) > 0x8000:
        raise ValueError("Resident lightmap selection exceeds the upper half of one ROM bank")
    return ResidentLightmaps(bytes(payload), tuple(sorted(pointers)), frozenset(nibble_offsets))


def restore_resident_lightmaps(directory, originals, bank, address, payload, canonical_banks):
    restored = bytearray(directory)
    entries = tuple(LIGHTMAP.iter_unpack(directory))
    marked = {face for face, (source, *_rest) in enumerate(entries)
              if source != 0xff and source & RESIDENT_BANK_TAG}
    if not marked:
        raise ValueError("Resident world lightmap archive contains no marked faces")
    for face, source_bank, source_address in ORIGINAL_POINTER.iter_unpack(originals):
        packed_nibbles = bool(source_bank & ORIGINAL_NIBBLE_TAG)
        source_bank &= ~ORIGINAL_NIBBLE_TAG
        if face not in marked or source_bank not in canonical_banks:
            raise ValueError("Resident lightmap repair names an unexpected face or bank")
        current_bank, current_address, width, height, _, _ = entries[face]
        if packed_nibbles:
            if not width & RESIDENT_NIBBLE_WIDTH_TAG:
                raise ValueError(f"Resident lightmap face {face} is missing its nibble width tag")
            width &= RESIDENT_NIBBLE_WIDTH_TAG - 1
        count = width * height
        size = (3 * count + 3) // 4
        offset = current_address - address
        source = source_address - 0x8000
        canonical = canonical_banks[source_bank]
        if (current_bank != bank | RESIDENT_BANK_TAG
                or not 0 <= source < source + size <= len(canonical)):
            raise ValueError(f"Resident lightmap face {face} has an invalid canonical range")
        expected = canonical[source:source + size]
        if packed_nibbles:
            expected = resident_nibble_grid(expected, count)
        if (expected is None or not 0 <= offset < offset + len(expected) <= len(payload)
                or payload[offset:offset + len(expected)] != expected):
            raise ValueError(f"Resident lightmap face {face} differs from its canonical packed grid")
        at = face * LIGHTMAP.size
        LIGHTMAP_POINTER.pack_into(restored, at, source_bank, source_address)
        restored[at + LIGHTMAP_POINTER.size] = width
        marked.remove(face)
    if marked:
        raise ValueError("Resident lightmap repair is missing marked faces")
    return bytes(restored)


@dataclass(frozen=True)
class WorldLightmapPlan:
    first_bank: int
    chunks: tuple[bytes, ...]
    face_count: int
    lit_faces: int
    maximum_samples: int

    def include(self, offsets: tuple[int | None, ...]) -> bytes:
        """Offset is physical source offset in QPL1 before byte pairing."""
        if len(offsets) != len(self.chunks):
            raise ValueError("world lightmap offsets and canonical banks disagree")
        sizes, seeks = [], []
        for chunk, offset in zip(self.chunks, offsets, strict=True):
            if bool(chunk) != (offset is not None):
                raise ValueError("missing nonempty world lightmap MSU extent")
            size = len(chunk)
            seek = 0 if offset is None else 64 + 2 * offset
            if offset is not None and not 0x400000 <= offset < offset + size <= ((1 << 32) - 64) // 2:
                raise ValueError("world lightmap samples escape the MSU seek range")
            sizes.append(f"${size:04X}")
            seeks.append(f"${seek:08X}")
        return ("PLAYABLE_WORLD_LIGHTMAP_STREAM = 1\n"
                "WORLD_LIGHTMAP_REQUEST_TAG = $4000\n"
                f"WORLD_LIGHTMAP_FIRST_BANK = ${self.first_bank:02X}\n"
                f"WORLD_LIGHTMAP_CHUNK_COUNT = {len(self.chunks)}\n"
                ".macro WORLD_LIGHTMAP_CHUNK_SIZES\n"
                f"        .word {', '.join(sizes)}\n.endmacro\n"
                ".macro WORLD_LIGHTMAP_CHUNK_SEEKS\n"
                f"        .dword {', '.join(seeks)}\n.endmacro\n").encode("ascii")


def build_world_lightmap_plan(data: Path) -> WorldLightmapPlan:
    fields = integer_definitions((data / "QuakeBSPScene.i").read_text(encoding="utf-8"))
    first = fields["BSP_WORLD_LIGHTMAP_FIRST_GSU_ROM_BANK"]
    faces = fields["BSP_WORLD_FACE_COUNT"]
    count = max(4, fields.get("BSP_WORLD_LIGHTMAP_CHUNK_COUNT", 4))
    chunks = tuple((data / f"QuakeBSPWorldLightmapSamples{index}.bin").read_bytes() for index in range(count))
    directory = (data / "QuakeBSPWorldLightmapDirectory.bin").read_bytes()
    if len(directory) != faces * LIGHTMAP.size or not 0 <= first <= 60:
        raise ValueError("invalid world lightmap face or bank count")
    if any(len(chunk) > 0x8000 for chunk in chunks):
        raise ValueError("world lightmap carrier exceeds its canonical bank")
    lit_faces = 0
    maximum = 0
    for face, (bank, address, width, height, _s, _t) in enumerate(LIGHTMAP.iter_unpack(directory)):
        if bank == 0xff:
            continue
        count = width * height
        index, start = bank - first, address - 0x8000
        size = (3 * count + 3) // 4
        if not 0 <= index < len(chunks) or not 0 < count <= 0x200:
            raise ValueError(f"world lightmap face {face} has invalid bank, phase or dimensions")
        if not 0 <= start < start + size <= len(chunks[index]) or start % 3:
            raise ValueError(f"world lightmap face {face} escapes its group-aligned carrier")
        unpacked = unpack_six_bit_samples(chunks[index], lightmap_location_sample_offset(address, 0), count)
        cpu = decode_groups(chunks[index][start:start + size], count)
        if cpu != bytes(value | 0xc0 for value in unpacked):
            raise AssertionError(f"world lightmap face {face} CPU decoder differs from canonical decoding")
        lit_faces += 1
        maximum = max(maximum, count)
    return WorldLightmapPlan(first, chunks, faces, lit_faces, maximum)


def decode_groups(raw: bytes, count: int) -> bytes:
    """Mirror the 65816 decoder and expose final-group overread bugs."""
    if len(raw) != (3 * count + 3) // 4 or count < 0:
        raise ValueError("invalid world lightmap group range")
    result = bytearray()
    source = iter(raw)
    while len(result) < count:
        a = next(source)
        result.append(0xc0 | (a & 63))
        if len(result) == count:
            break
        b = next(source)
        result.append(0xc0 | (a >> 6) | ((b & 15) << 2))
        if len(result) == count:
            break
        c = next(source)
        result.append(0xc0 | (b >> 4) | ((c & 3) << 4))
        if len(result) == count:
            break
        result.append(0xc0 | (c >> 2))
    if next(source, None) is not None:
        raise AssertionError("world lightmap CPU decoder left unread bytes")
    return bytes(result)
