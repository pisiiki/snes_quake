"""Duplicate selected canonical E1M1 S/T rows into bank-safe FX3 ROM shards."""

from collections import defaultdict
from dataclasses import dataclass
from struct import Struct

import numpy as np

from snes_tooling.quake.quake_playable_layout import (
    GSU_ROM_BYTES, HALFBANK, RomAllocationError, gsu_address,
)
from snes_tooling.quake.quake_playable_world_coordinates import (
    AFFINE_DESCRIPTOR_COUNT, AFFINE_DESCRIPTOR_COUNT_MASK, AFFINE_DESCRIPTOR_FLAT_MASK,
    WORLD_COORDINATE_PREFIX, WORLD_FACE,
)

RAW_CONTOUR_MARKER = AFFINE_DESCRIPTOR_COUNT
RAW_CONTOUR_BUDGET = 6656
RAW_CONTOUR_BUCKETS = 64
RAW_CONTOUR_DIRECTORY = "BSP_WORLD_RAW_CONTOUR_DIRECTORY"
RAW_CONTOUR_SHARD = "BSP_WORLD_RAW_CONTOUR_SHARD_"
RAW_CONTOUR_POINTER = Struct("<HB")


@dataclass(frozen=True)
class RawWorldContours:
    faces: bytes
    mode_faces: tuple[int, ...]
    face_count: int
    directory_offset: int
    regions: tuple[tuple[str, int, bytes], ...]


def _descriptor(count, flat):
    return ((count & AFFINE_DESCRIPTOR_COUNT_MASK) >> 5
            | (flat & AFFINE_DESCRIPTOR_FLAT_MASK) >> 1)


def _bucket(face):
    return (face ^ (face >> 6)) & (RAW_CONTOUR_BUCKETS - 1)


def _shard_name(bucket):
    return f"{RAW_CONTOUR_SHARD}{bucket:02X}"


def _contour_bytes(records):
    return b"".join(records[name] for name in sorted(records)
                    if name.startswith(WORLD_COORDINATE_PREFIX) and name.endswith(".bin"))


def _candidate(plan, uv, face, record):
    first, count, flat, _, flags = record
    descriptor = _descriptor(count, flat)
    count &= plan.count_mask
    if not count or flags & plan.mode_mask or descriptor not in (0, RAW_CONTOUR_MARKER):
        return None
    payload = uv[first * 4:(first + count) * 4]
    if len(payload) != count * 4:
        raise ValueError("raw contour exceeds its canonical coordinate stream")
    return face, payload


def _mark_faces(plan, selected):
    faces = bytearray(plan.faces)
    for face, (_, count, flat, _, _) in enumerate(WORLD_FACE.iter_unpack(plan.faces)):
        if face in selected or _descriptor(count, flat) == RAW_CONTOUR_MARKER:
            offset = face * WORLD_FACE.size
            marker = RAW_CONTOUR_MARKER if face in selected else 0
            faces[offset + 2] = (count & plan.count_mask) | ((marker & 7) << 5)
            faces[offset + 3] = (flat & 15) | ((marker >> 3) << 4)
    return bytes(faces)


def _shard_payload(rows):
    header = bytearray((len(rows),))
    payload = bytearray()
    base = 1 + 2 * len(rows)
    for face, contour in rows:
        header.extend((face >> 6, base + len(payload)))
        payload.extend(contour)
    return bytes(header + payload)


def build_raw_contours(allocator, plan, directory, visibility):
    """Prefer broadly visible contours within the exact raw byte budget."""
    uv = _contour_bytes({path.name: path.read_bytes()
                         for path in directory.glob(f"{WORLD_COORDINATE_PREFIX}*.bin")})
    faces = tuple(WORLD_FACE.iter_unpack(plan.faces))
    rows = np.frombuffer(visibility.payload, dtype=np.uint8).reshape(visibility.row_count, visibility.stride)
    # Leaf zero is the all-visible fallback. Rank by the ordinary camera
    # leaves, keeping the original face order as the deterministic tie-break.
    masks = rows[1:, 4:4 + visibility.row_bytes]
    leaf_counts = np.unpackbits(masks, axis=1, bitorder="little")[:, :len(faces)].sum(axis=0)
    candidates = []
    for face, record in enumerate(faces):
        row = _candidate(plan, uv, face, record)
        if row is not None:
            candidates.append(row)
    candidates.sort(key=lambda row: (-int(leaf_counts[row[0]]), row[0]))

    directory_bytes = RAW_CONTOUR_BUCKETS * RAW_CONTOUR_POINTER.size
    selected = []
    sizes = {}
    total = directory_bytes
    for row in candidates:
        face, contour = row
        bucket = _bucket(face)
        added = 2 + len(contour) + (bucket not in sizes)
        if total + added <= RAW_CONTOUR_BUDGET and sizes.get(bucket, 0) + added <= 255:
            selected.append(row)
            total += added
            sizes[bucket] = sizes.get(bucket, 0) + added

    original = allocator.intervals.copy()
    while selected:
        shards = defaultdict(list)
        for row in sorted(selected):
            shards[_bucket(row[0])].append(row)
        blobs = {_shard_name(bucket): _shard_payload(rows) for bucket, rows in shards.items()}
        sizes = {name: len(payload) for name, payload in blobs.items()}
        sizes[RAW_CONTOUR_DIRECTORY] = directory_bytes
        try:
            offsets = {
                name: allocator.allocate(size, name, low=0, high=GSU_ROM_BYTES, alignment=2)
                for name, size in sorted(sizes.items(), key=lambda item: (-item[1], item[0]))
            }
        except RomAllocationError:
            allocator.intervals = original.copy()
            selected.pop()
            continue
        break
    else:
        raise ValueError("no bank-safe ROM placement for E1M1 raw contours")

    pointers = bytearray(directory_bytes)
    for bucket in shards:
        bank, address = gsu_address(offsets[_shard_name(bucket)])
        RAW_CONTOUR_POINTER.pack_into(pointers, bucket * RAW_CONTOUR_POINTER.size, address, bank)
    blobs[RAW_CONTOUR_DIRECTORY] = bytes(pointers)
    face_ids = {face for face, _ in selected}
    mode_faces = list(plan.mode_faces)
    mode_faces[0] += mode_faces[-1] - len(face_ids)
    mode_faces[-1] = len(face_ids)
    return RawWorldContours(
        _mark_faces(plan, face_ids), tuple(mode_faces), len(face_ids), offsets[RAW_CONTOUR_DIRECTORY],
        tuple((name, offsets[name], blob) for name, blob in sorted(blobs.items())),
    )


def _read_region(row, read_segment):
    offset, size = row["offset"], row["bytes"]
    if (row["storage"] != "gsu" or not 0 <= offset < offset + size <= GSU_ROM_BYTES
            or offset // HALFBANK != (offset + size - 1) // HALFBANK):
        raise ValueError("raw contour segment escapes one GSU ROM bank")
    if gsu_address(offset) != (row["gsuBank"], row["gsuAddress"]):
        raise ValueError("raw contour segment GSU address differs from its placement")
    payload = read_segment(row)
    if len(payload) != size:
        raise ValueError("raw contour segment size differs from its placement")
    return payload


def verify_raw_contours(plan, records, segments, read_segment):
    """Prove every raw ROM pointer and texel against the canonical MSU rows."""
    uv = _contour_bytes(records)
    faces = list(WORLD_FACE.iter_unpack(plan.faces))
    directory_row = segments.get(RAW_CONTOUR_DIRECTORY)
    shards = {name: row for name, row in segments.items() if name.startswith(RAW_CONTOUR_SHARD)}
    if directory_row is None or not shards:
        raise ValueError("missing raw contour directory or shards")
    directory = _read_region(directory_row, read_segment)
    if len(directory) != RAW_CONTOUR_BUCKETS * RAW_CONTOUR_POINTER.size:
        raise ValueError("raw contour directory has the wrong extent")
    selected = set()
    used = len(directory)
    for bucket, (address, bank) in enumerate(RAW_CONTOUR_POINTER.iter_unpack(directory)):
        row = shards.pop(_shard_name(bucket), None)
        if row is None:
            if address or bank:
                raise ValueError("raw contour directory names an absent shard")
            continue
        payload = _read_region(row, read_segment)
        if (bank, address) != (row["gsuBank"], row["gsuAddress"]) or not 1 < len(payload) <= 255:
            raise ValueError("raw contour directory does not name the exact shard")
        count = payload[0]
        cursor = 1 + 2 * count
        if not count or cursor > len(payload):
            raise ValueError("raw contour shard header escapes its payload")
        previous = -1
        for tag, offset in zip(payload[1:cursor:2], payload[2:cursor:2], strict=True):
            face = (tag << 6) | ((bucket ^ tag) & (RAW_CONTOUR_BUCKETS - 1))
            if tag <= previous or face >= len(faces) or face in selected or offset != cursor:
                raise ValueError("raw contour shard has an invalid face tag or offset")
            previous = tag
            candidate = _candidate(plan, uv, face, faces[face])
            if candidate is None:
                raise ValueError("raw contour overrides an affine descriptor")
            contour = candidate[1]
            end = cursor + len(contour)
            if payload[cursor:end] != contour:
                raise ValueError("raw ROM contour differs from its canonical S/T bytes")
            selected.add(face)
            cursor = end
        if cursor != len(payload):
            raise ValueError("raw contour shard has trailing bytes")
        used += len(payload)
    if shards or not selected or used > RAW_CONTOUR_BUDGET:
        raise ValueError("raw contour package has extra shards or exceeds its budget")
    return _mark_faces(plan, selected)
