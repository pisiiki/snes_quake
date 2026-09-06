#!/usr/bin/env python3
"""Audit bounded render-packet options for the checked-in SNES Quake assets.

This is deliberately a host-side experiment.  It models the rejection work
that a runtime packet builder can perform before copying geometry into GSU RAM,
then compares shared-vertex remapping with the simpler duplicated-vertex path.
No locally installed Quake data is required.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from dataclasses import dataclass
from pathlib import Path

from workspace_paths import workspace_root
from typing import Callable, Iterable


DEFAULT_DATA_DIR = workspace_root(__file__) / "src/snes_quake/Data"
WORLD_FACE_RECORD = struct.Struct("<HBBBB")
PACKET_VERTEX_RECORD = struct.Struct("<bbbB")
PACKET_INDEX_RECORD = struct.Struct("<H")
PACKET_FACE_RECORD = struct.Struct("<HBBB")
FACE_PLANE_RECORD = struct.Struct("<bbbh")
PVS_DIRECTORY_RECORD = struct.Struct("<HHHBB")
PVS_GUARD_RECORD = struct.Struct("<HB")

WORLD_FACE_COUNT = 4_419
WORLD_VERTEX_COUNT = 7_216
WORLD_INDEX_COUNT = 21_588
WORLD_PVS_ROW_BYTES = (WORLD_FACE_COUNT + 7) // 8
WORLD_PVS_ROW_COUNT = 968
WORLD_PVS_FIRST_BANK = 0x10
WORLD_FACE_FLAG_NON_DRAWABLE = 0x01
WORLD_FACE_FLAG_PLANE_CULL_GUARD = 0x02
WORLD_FACE_KNOWN_FLAGS = WORLD_FACE_FLAG_NON_DRAWABLE | WORLD_FACE_FLAG_PLANE_CULL_GUARD

# These are the effective limits of MemoryMap.i.  The packet arrays are sized
# together for 768 shared vertices.
PACKET_FACE_CAPACITY = 405
PACKET_VERTEX_CAPACITY = 768
PACKET_INDEX_CAPACITY = 0x1000 // 2

LOGICAL_WIDTH = 128
LOGICAL_HEIGHT = 112
SCREEN_ADMISSION_GUARD = 1
NEAR_DEPTH = 1
PROJECTION_SHIFT = 8
RECIPROCAL_NUMERATOR = 96 << PROJECTION_SHIFT
VIEW_FRACTION_BITS = 6
VIEW_ONE = 1 << VIEW_FRACTION_BITS
DEPTH_TABLE_FRACTION_BITS = 2
DEPTH_TABLE_ONE = 1 << DEPTH_TABLE_FRACTION_BITS
SUBPIXEL_RECIPROCAL_SHIFT = 12
SUBPIXEL_RECIPROCAL_NUMERATOR = 96 << (
    SUBPIXEL_RECIPROCAL_SHIFT + DEPTH_TABLE_FRACTION_BITS - VIEW_FRACTION_BITS
)

WAYPOINTS = (
    ("spawn", 764, (-46, -80, -7)),
    ("near", 877, (-45, -91, -6)),
    ("far", 850, (-77, -41, -13)),
)


@dataclass(frozen=True)
class Face:
    first_index: int
    vertex_count: int
    flat_color: int
    dither_color: int
    flags: int


@dataclass(frozen=True)
class Assets:
    vertices: tuple[tuple[int, int, int], ...]
    indices: tuple[int, ...]
    faces: tuple[Face, ...]
    face_planes: tuple[tuple[int, int, int, int], ...]
    pvs_rows: tuple[bytes, ...]
    sin_table: tuple[int, ...]
    cos_table: tuple[int, ...]
    reciprocal_table: tuple[int, ...]
    source_sha256: str
    vertex_fraction_bits: int = 0


@dataclass(frozen=True)
class WorldDimensions:
    face_count: int
    vertex_count: int
    index_count: int
    pvs_row_bytes: int
    pvs_row_count: int

    @property
    def pvs_last_unused_mask(self) -> int:
        remainder = self.face_count & 7
        return 0 if remainder == 0 else (0xFF << remainder) & 0xFF


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _read(path: Path, source_hash: "hashlib._Hash") -> bytes:
    payload = path.read_bytes()
    source_hash.update(path.name.encode("ascii"))
    source_hash.update(struct.pack("<I", len(payload)))
    source_hash.update(payload)
    return payload


def load_world_dimensions(data_dir: Path) -> WorldDimensions:
    """Load configured packed-world dimensions from generated metadata."""

    try:
        metadata = json.loads(
            (data_dir / "QuakeBSPMetadata.json").read_text(encoding="ascii")
        )
        packing = metadata["world"]["packing"]
        face_pvs = packing["face_pvs"]
        dimensions = WorldDimensions(
            face_count=packing["face_count"],
            vertex_count=packing["vertex_count"],
            index_count=packing["index_count"],
            pvs_row_bytes=face_pvs["decoded_row_bytes"],
            pvs_row_count=face_pvs["row_count"],
        )
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("world metadata has invalid packed dimensions") from error
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value <= 0
        for value in (
            dimensions.face_count,
            dimensions.vertex_count,
            dimensions.index_count,
            dimensions.pvs_row_bytes,
            dimensions.pvs_row_count,
        )
    ):
        raise ValueError("world metadata has invalid packed dimensions")
    if dimensions.pvs_row_bytes != (dimensions.face_count + 7) // 8:
        raise ValueError("world metadata face-PVS row width disagrees")
    return dimensions


def decode_zero_runs(encoded: bytes, decoded_bytes: int) -> bytes:
    """Decode one exact Quake-style zero-run row, rejecting trailing data."""

    output = bytearray()
    cursor = 0
    while len(output) < decoded_bytes:
        if cursor >= len(encoded):
            raise ValueError("truncated face-PVS row")
        value = encoded[cursor]
        cursor += 1
        if value:
            output.append(value)
            continue
        if cursor >= len(encoded):
            raise ValueError("truncated face-PVS zero run")
        run = encoded[cursor]
        cursor += 1
        if not run:
            raise ValueError("face-PVS zero run has zero length")
        if len(output) + run > decoded_bytes:
            raise ValueError("face-PVS zero run exceeds decoded row")
        output.extend(bytes(run))
    if cursor != len(encoded):
        raise ValueError("face-PVS row has trailing data")
    return bytes(output)


def validate_pvs_placement(data_dir: Path) -> None:
    """Reject metadata whose directory/guards escape the actual PVS2 tail."""
    metadata = json.loads((data_dir / "QuakeBSPMetadata.json").read_text(encoding="utf-8"))
    pvs = metadata["world"]["packing"]["face_pvs"]
    payload_bytes = (data_dir / "QuakeBSPWorldPVS2.bin").stat().st_size
    directory_bytes = (data_dir / "QuakeBSPWorldPVSDirectory.bin").stat().st_size
    guard_bytes = (data_dir / "QuakeBSPWorldPVSGuards.bin").stat().st_size
    directory = 0x8000 + ((payload_bytes + 7) & ~7)
    guards = directory + directory_bytes
    if (
        guards + guard_bytes > 0x10000
        or pvs.get("directory_gsu_rom_bank") != 0x12
        or pvs.get("directory_gsu_rom_address") != directory
        or pvs["quantization_guard"].get("gsu_rom_bank") != 0x12
        or pvs["quantization_guard"].get("gsu_rom_address") != guards
    ):
        raise ValueError("face-PVS directory/guard placement disagrees with bank 18 tail")


def load_assets(data_dir: Path = DEFAULT_DATA_DIR) -> Assets:
    validate_pvs_placement(data_dir)
    dimensions = load_world_dimensions(data_dir)
    source_hash = hashlib.sha256()
    vertex_bytes = _read(data_dir / "QuakeBSPWorldVertices.bin", source_hash)
    index_bytes = _read(data_dir / "QuakeBSPWorldIndices0.bin", source_hash) + _read(
        data_dir / "QuakeBSPWorldIndices1.bin", source_hash
    )
    face_bytes = _read(data_dir / "QuakeBSPWorldFaces.bin", source_hash)
    plane_bytes = _read(data_dir / "QuakeBSPWorldFacePlanes.bin", source_hash)
    directory = _read(data_dir / "QuakeBSPWorldPVSDirectory.bin", source_hash)
    guard_bytes = _read(data_dir / "QuakeBSPWorldPVSGuards.bin", source_hash)
    sin_bytes = _read(data_dir / "QuakeBSPSin.bin", source_hash)
    cos_bytes = _read(data_dir / "QuakeBSPCos.bin", source_hash)
    reciprocal_bytes = _read(data_dir / "QuakeBSPReciprocal.bin", source_hash)

    if len(vertex_bytes) != dimensions.vertex_count * 4:
        raise ValueError("world vertex asset has the wrong size")
    if len(index_bytes) != dimensions.index_count * 2:
        raise ValueError("world index assets have the wrong combined size")
    if len(face_bytes) != dimensions.face_count * WORLD_FACE_RECORD.size:
        raise ValueError("world face asset has the wrong size")
    if len(plane_bytes) != dimensions.face_count * FACE_PLANE_RECORD.size:
        raise ValueError("world face-plane asset has the wrong size")
    if len(directory) % PVS_DIRECTORY_RECORD.size:
        raise ValueError("face-PVS directory is not record aligned")
    if len(guard_bytes) % PVS_GUARD_RECORD.size:
        raise ValueError("face-PVS guards are not record aligned")
    if len(sin_bytes) != 32 or len(cos_bytes) != 32 or len(reciprocal_bytes) != 2048:
        raise ValueError("projection lookup tables have the wrong size")

    vertices = tuple(
        (
            x * 4 + (residual & 3),
            y * 4 + ((residual >> 2) & 3),
            z * 4 + ((residual >> 4) & 3),
        )
        for x, y, z, residual in struct.iter_unpack("<bbbB", vertex_bytes)
    )
    indices = tuple(value for (value,) in struct.iter_unpack("<H", index_bytes))
    faces = tuple(Face(*record) for record in WORLD_FACE_RECORD.iter_unpack(face_bytes))
    planes = tuple(FACE_PLANE_RECORD.iter_unpack(plane_bytes))
    if max(indices) >= len(vertices):
        raise ValueError("world index escapes the vertex asset")
    for face in faces:
        if face.flags & ~WORLD_FACE_KNOWN_FLAGS:
            raise ValueError("world face uses unknown flag bits")
        if face.vertex_count == 0:
            if not (face.flags & WORLD_FACE_FLAG_NON_DRAWABLE) or (
                face.flags & WORLD_FACE_FLAG_PLANE_CULL_GUARD
            ):
                raise ValueError("non-drawable world face has invalid flags")
        elif face.flags & WORLD_FACE_FLAG_NON_DRAWABLE:
            raise ValueError("drawable world face has the non-drawable flag")
        if face.first_index + face.vertex_count > len(indices):
            raise ValueError("world face escapes the index assets")

    guards = tuple(PVS_GUARD_RECORD.iter_unpack(guard_bytes))
    if len({offset for offset, _mask in guards}) != len(guards):
        raise ValueError("face-PVS guards contain a duplicate byte offset")
    for offset, mask in guards:
        if offset >= dimensions.pvs_row_bytes or not mask:
            raise ValueError("face-PVS guard escapes the decoded row")
        if (
            offset == dimensions.pvs_row_bytes - 1
            and mask & dimensions.pvs_last_unused_mask
        ):
            raise ValueError("face-PVS guard sets nonexistent face bits")

    chunk_cache: dict[int, bytes] = {}
    pvs_rows: list[bytes] = []
    for leaf, (address, encoded_bytes, face_count, bank, flags) in enumerate(
        PVS_DIRECTORY_RECORD.iter_unpack(directory)
    ):
        if flags:
            raise ValueError(f"leaf {leaf} has nonzero face-PVS flags")
        chunk_index = bank - WORLD_PVS_FIRST_BANK
        if chunk_index < 0:
            raise ValueError(f"leaf {leaf} has an invalid face-PVS bank")
        if chunk_index not in chunk_cache:
            chunk_cache[chunk_index] = _read(
                data_dir / f"QuakeBSPWorldPVS{chunk_index}.bin", source_hash
            )
        chunk = chunk_cache[chunk_index]
        offset = address - 0x8000
        if offset < 0 or offset + encoded_bytes > len(chunk):
            raise ValueError(f"leaf {leaf} face-PVS row escapes chunk {chunk_index}")
        row = bytearray(
            decode_zero_runs(
                chunk[offset : offset + encoded_bytes], dimensions.pvs_row_bytes
            )
        )
        for guard_offset, mask in guards:
            row[guard_offset] |= mask
        if row[-1] & dimensions.pvs_last_unused_mask:
            raise ValueError(f"leaf {leaf} face-PVS row sets nonexistent face bits")
        if sum(value.bit_count() for value in row) != face_count:
            raise ValueError(f"leaf {leaf} face-PVS count disagrees with its directory")
        pvs_rows.append(bytes(row))

    if len(pvs_rows) != dimensions.pvs_row_count:
        raise ValueError(
            f"face-PVS directory does not contain all {dimensions.pvs_row_count} rows"
        )
    return Assets(
        vertices,
        indices,
        faces,
        planes,
        tuple(pvs_rows),
        tuple(value for (value,) in struct.iter_unpack("<b", sin_bytes)),
        tuple(value for (value,) in struct.iter_unpack("<b", cos_bytes)),
        tuple(value for (value,) in struct.iter_unpack("<H", reciprocal_bytes)),
        source_hash.hexdigest(),
        2,
    )


def visible_face_ids(
    row: bytes, *, face_count: int = WORLD_FACE_COUNT
) -> tuple[int, ...]:
    """Expand one PVS bitset using its configured world-face count."""

    if face_count < 1:
        raise ValueError("world face count must be positive")
    output: list[int] = []
    for byte_index, original in enumerate(row):
        value = original
        while value:
            bit = (value & -value).bit_length() - 1
            face = byte_index * 8 + bit
            if face < face_count:
                output.append(face)
            value &= value - 1
    return tuple(output)


def drawable_face_ids(assets: Assets, face_ids: Iterable[int]) -> tuple[int, ...]:
    return tuple(
        face_id
        for face_id in face_ids
        if assets.faces[face_id].vertex_count >= 3
        and not (assets.faces[face_id].flags & WORLD_FACE_FLAG_NON_DRAWABLE)
    )


def resource_usage(assets: Assets, face_ids: Iterable[int]) -> dict[str, int]:
    ids = tuple(face_ids)
    source_vertices: set[int] = set()
    index_count = 0
    for face_id in ids:
        face = assets.faces[face_id]
        face_indices = assets.indices[
            face.first_index : face.first_index + face.vertex_count
        ]
        source_vertices.update(face_indices)
        index_count += face.vertex_count
    return {
        "faces": len(ids),
        "sourceUniqueVertices": len(source_vertices),
        "duplicatedVertices": index_count,
        "indices": index_count,
    }


def _fits(usage: dict[str, int], strategy: str) -> bool:
    vertices = (
        usage["sourceUniqueVertices"]
        if strategy == "shared"
        else usage["duplicatedVertices"]
    )
    return (
        usage["faces"] <= PACKET_FACE_CAPACITY
        and vertices <= PACKET_VERTEX_CAPACITY
        and usage["indices"] <= PACKET_INDEX_CAPACITY
    )


def _signed16(value: int) -> int:
    value &= 0xFFFF
    return value - 0x10000 if value & 0x8000 else value


def _signed8(value: int) -> int:
    value &= 0xFF
    return value - 0x100 if value & 0x80 else value


def _pack_vertex_q2(assets: Assets, vertex: tuple[int, int, int]) -> bytes:
    if not 0 <= assets.vertex_fraction_bits <= 2:
        raise ValueError("packet vertex precision cannot be represented as Q2")
    q2 = tuple(component << (2 - assets.vertex_fraction_bits) for component in vertex)
    bases = tuple(component // 4 for component in q2)
    residual = (q2[0] & 3) | ((q2[1] & 3) << 2) | ((q2[2] & 3) << 4)
    return struct.pack("<bbbB", *bases, residual)


def _signed_mul_shift6(source: int, multiplier: int) -> int:
    """Mirror SuperFX signed-low-byte MULT followed by six ASRs."""

    return (_signed8(source) * _signed8(multiplier)) >> 6


def _signed_shift6(value: int) -> int:
    """Mirror the GSU arithmetic shift of a signed Q12 product to Q6."""

    return _signed16(value >> 6)


ViewTransform = Callable[
    ["Assets", tuple[int, int, int], tuple[int, int, int], int, int],
    tuple[int, int, int],
]


def project_vertex(
    assets: Assets,
    vertex: tuple[int, int, int],
    camera: tuple[int, int, int],
    yaw: int,
    pitch: int = 0,
    *,
    view_transform: ViewTransform | None = None,
) -> tuple[int, int] | None:
    transform = transform_vertex if view_transform is None else view_transform
    right, view_up, view_depth = transform(assets, vertex, camera, yaw, pitch)
    if view_depth < NEAR_DEPTH * VIEW_ONE or view_depth >= 256 * VIEW_ONE:
        return None
    table_depth = max(
        NEAR_DEPTH * DEPTH_TABLE_ONE,
        (view_depth + (VIEW_ONE // DEPTH_TABLE_ONE // 2))
        >> (VIEW_FRACTION_BITS - DEPTH_TABLE_FRACTION_BITS),
    )
    reciprocal = assets.reciprocal_table[table_depth]
    return (
        _signed16(64 + ((right * reciprocal) >> SUBPIXEL_RECIPROCAL_SHIFT)),
        _signed16(56 - ((view_up * reciprocal) >> SUBPIXEL_RECIPROCAL_SHIFT)),
    )


def transform_vertex(
    assets: Assets,
    vertex: tuple[int, int, int],
    camera: tuple[int, int, int],
    yaw: int,
    pitch: int = 0,
) -> tuple[int, int, int]:
    """Mirror the selector's Q6 view transform without integer-unit collapse."""
    coordinate_scale = 1 << assets.vertex_fraction_bits
    dx, dy, dz = (vertex[axis] - camera[axis] * coordinate_scale for axis in range(3))

    def to_q6(value: int) -> int:
        return (
            value
            if assets.vertex_fraction_bits == 0
            else value >> assets.vertex_fraction_bits
        )

    forward = to_q6(dx * assets.cos_table[yaw]) + to_q6(dy * assets.sin_table[yaw])
    right = to_q6(dy * assets.cos_table[yaw]) - to_q6(dx * assets.sin_table[yaw])

    view_up = to_q6(dz * assets.cos_table[pitch]) - _signed_shift6(
        forward * assets.sin_table[pitch]
    )
    view_depth = _signed_shift6(forward * assets.cos_table[pitch]) + to_q6(
        dz * assets.sin_table[pitch]
    )
    return right, view_up, view_depth


def face_is_front_facing(
    plane: tuple[int, int, int, int],
    camera: tuple[int, int, int],
    coordinate_scale: int = 1,
) -> bool:
    nx, ny, nz, distance = plane
    dot = _signed16(_signed8(nx) * _signed8(camera[0]) * coordinate_scale)
    dot = _signed16(dot + _signed8(ny) * _signed8(camera[1]) * coordinate_scale)
    dot = _signed16(dot + _signed8(nz) * _signed8(camera[2]) * coordinate_scale)
    # Quake's world faces are wound toward solid space. An interior camera
    # sees the negative side of the oriented polygon plane.
    return _signed16(dot - distance) < 0


def projection_stages(
    assets: Assets,
    drawable: tuple[int, ...],
    camera: tuple[int, int, int],
    yaw: int,
    pitch: int = 0,
    *,
    view_transform: ViewTransform | None = None,
) -> tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]]:
    """Return front-facing, near-valid, and screen-bbox candidate face IDs."""

    front: list[int] = []
    near: list[int] = []
    screen: list[int] = []
    for face_id in drawable:
        face = assets.faces[face_id]
        guarded = bool(face.flags & WORLD_FACE_FLAG_PLANE_CULL_GUARD)
        if not guarded and not face_is_front_facing(
            assets.face_planes[face_id],
            camera,
            1 << assets.vertex_fraction_bits,
        ):
            continue
        front.append(face_id)
        source_indices = assets.indices[
            face.first_index : face.first_index + face.vertex_count
        ]
        transform = transform_vertex if view_transform is None else view_transform
        depths = tuple(
            transform(assets, assets.vertices[index], camera, yaw, pitch)[2]
            for index in source_indices
        )
        projected = tuple(
            project_vertex(
                assets,
                assets.vertices[index],
                camera,
                yaw,
                pitch,
                view_transform=transform,
            )
            for index in source_indices
        )
        near_valid = False
        screen_candidate = False
        for index in range(1, len(projected) - 1):
            triangle = (projected[0], projected[index], projected[index + 1])
            if any(vertex is None for vertex in triangle):
                continue
            near_valid = True
            points = tuple(vertex for vertex in triangle if vertex is not None)
            xs = tuple(point[0] for point in points)
            # DrawTriangle clamps each projected Y to this guard band before
            # sorting; model that before applying the visible-screen bbox.
            ys = tuple(max(-16, min(127, point[1])) for point in points)
            # The current rasterizer rejects a triangle with one invalid fan
            # vertex, clamps Y, and clips horizontal spans.  Bounding-box
            # overlap is the cheap conservative pre-copy rejection available
            # to the planned runtime builder.
            if (
                max(xs) >= -SCREEN_ADMISSION_GUARD
                and min(xs) < LOGICAL_WIDTH + SCREEN_ADMISSION_GUARD
                and max(ys) >= -SCREEN_ADMISSION_GUARD
                and min(ys) < LOGICAL_HEIGHT + SCREEN_ADMISSION_GUARD
            ):
                screen_candidate = True
                break
        # A face crossing the near plane, or wholly between the camera and the
        # near plane, can still own forward pixel-center rays. Admit it
        # conservatively and leave exact clipping/coverage to the renderer.
        near_intersecting = any(
            depth < NEAR_DEPTH * VIEW_ONE for depth in depths
        ) and any(0 < depth < 256 * VIEW_ONE for depth in depths)
        if near_intersecting:
            near_valid = True
            screen_candidate = True
        if near_valid:
            near.append(face_id)
        if screen_candidate:
            screen.append(face_id)
    return tuple(front), tuple(near), tuple(screen)


def _hash_streams(streams: tuple[tuple[str, bytes], ...]) -> dict[str, str]:
    combined = hashlib.sha256()
    output: dict[str, str] = {}
    for name, payload in streams:
        output[f"{name}Sha256"] = sha256(payload)
        combined.update(name.encode("ascii") + b"\0")
        combined.update(struct.pack("<I", len(payload)))
        combined.update(payload)
    output["combinedSha256"] = combined.hexdigest()
    return output


def build_packet(
    assets: Assets, candidates: tuple[int, ...], strategy: str
) -> dict[str, object]:
    if strategy not in {"shared", "duplicated"}:
        raise ValueError(f"unknown packet strategy {strategy!r}")

    selected: list[int] = []
    source_vertices: set[int] = set()
    packed_vertex_count = 0
    index_count = 0
    for face_id in candidates:
        face = assets.faces[face_id]
        source_indices = assets.indices[
            face.first_index : face.first_index + face.vertex_count
        ]
        added_vertices = (
            len(set(source_indices) - source_vertices)
            if strategy == "shared"
            else len(source_indices)
        )
        if (
            len(selected) + 1 > PACKET_FACE_CAPACITY
            or packed_vertex_count + added_vertices > PACKET_VERTEX_CAPACITY
            or index_count + len(source_indices) > PACKET_INDEX_CAPACITY
        ):
            continue
        selected.append(face_id)
        source_vertices.update(source_indices)
        packed_vertex_count += added_vertices
        index_count += len(source_indices)

    vertex_bytes = bytearray()
    index_bytes = bytearray()
    face_bytes = bytearray()
    plane_bytes = bytearray()
    vertex_lookup: dict[int, int] = {}
    packed_vertices = 0
    packed_indices = 0
    for face_id in selected:
        source_face = assets.faces[face_id]
        source_indices = assets.indices[
            source_face.first_index : source_face.first_index + source_face.vertex_count
        ]
        first_index = packed_indices
        for source_index in source_indices:
            if strategy == "shared":
                packed_index = vertex_lookup.get(source_index)
                if packed_index is None:
                    packed_index = packed_vertices
                    vertex_lookup[source_index] = packed_index
                    vertex_bytes.extend(
                        _pack_vertex_q2(assets, assets.vertices[source_index])
                    )
                    packed_vertices += 1
            else:
                packed_index = packed_vertices
                vertex_bytes.extend(
                    _pack_vertex_q2(assets, assets.vertices[source_index])
                )
                packed_vertices += 1
            index_bytes.extend(struct.pack("<H", packed_index))
            packed_indices += 1
        face_bytes.extend(
            PACKET_FACE_RECORD.pack(
                first_index,
                source_face.vertex_count,
                source_face.flat_color,
                source_face.dither_color,
            )
        )
        plane_bytes.extend(FACE_PLANE_RECORD.pack(*assets.face_planes[face_id]))

    source_face_bytes = b"".join(struct.pack("<H", face_id) for face_id in selected)
    streams = (
        ("sourceFaces", source_face_bytes),
        ("vertices", bytes(vertex_bytes)),
        ("indices", bytes(index_bytes)),
        ("faces", bytes(face_bytes)),
        ("facePlanes", bytes(plane_bytes)),
    )
    return {
        "strategy": strategy,
        "selectionOrder": "ascending world face id; skip any face that exceeds a capacity",
        "candidateFaces": len(candidates),
        "selectedFaces": len(selected),
        "droppedFaces": len(candidates) - len(selected),
        "sourceUniqueVertices": len(source_vertices),
        "packedVertices": packed_vertices,
        "indices": packed_indices,
        "bytes": {
            "vertices": len(vertex_bytes),
            "indices": len(index_bytes),
            "faces": len(face_bytes),
            "facePlanes": len(plane_bytes),
        },
        "hashes": _hash_streams(streams),
    }


def _distribution(values: Iterable[int]) -> dict[str, int | float]:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("cannot summarize an empty distribution")

    def percentile(numerator: int, denominator: int) -> int:
        return ordered[(len(ordered) - 1) * numerator // denominator]

    middle = len(ordered) // 2
    median: int | float = (
        ordered[middle]
        if len(ordered) & 1
        else (ordered[middle - 1] + ordered[middle]) / 2
    )
    return {
        "min": ordered[0],
        "median": median,
        "p90": percentile(9, 10),
        "p95": percentile(19, 20),
        "max": ordered[-1],
    }


def audit_all_pvs(assets: Assets) -> dict[str, object]:
    rows: list[tuple[int, int, int, int]] = []
    shared_fit = 0
    duplicated_fit = 0
    decoded_hash = hashlib.sha256()
    resource_hash = hashlib.sha256()
    for leaf, row in enumerate(assets.pvs_rows):
        decoded_hash.update(row)
        visible = visible_face_ids(row, face_count=len(assets.faces))
        drawable = drawable_face_ids(assets, visible)
        usage = resource_usage(assets, drawable)
        rows.append(
            (
                len(visible),
                usage["faces"],
                usage["sourceUniqueVertices"],
                usage["indices"],
            )
        )
        resource_hash.update(struct.pack("<5H", leaf, *rows[-1]))
        if leaf:
            shared_fit += int(_fits(usage, "shared"))
            duplicated_fit += int(_fits(usage, "duplicated"))

    ordinary = rows[1:]
    return {
        "rows": len(rows),
        "nonSolidRows": len(ordinary),
        "decodedRowsSha256": decoded_hash.hexdigest(),
        "resourceRowsSha256": resource_hash.hexdigest(),
        "fullPacketFit": {
            "sharedVertices": shared_fit,
            "duplicatedVertices": duplicated_fit,
        },
        "distributions": {
            "visibleFaces": _distribution(row[0] for row in ordinary),
            "drawableFaces": _distribution(row[1] for row in ordinary),
            "sharedVertices": _distribution(row[2] for row in ordinary),
            "indicesAndDuplicatedVertices": _distribution(row[3] for row in ordinary),
        },
        "selectedLeaves": {
            str(leaf): {
                "visibleFaces": rows[leaf][0],
                "drawableFaces": rows[leaf][1],
                "sharedVertices": rows[leaf][2],
                "indicesAndDuplicatedVertices": rows[leaf][3],
            }
            for leaf in (0, 764, 850, 877)
        },
    }


def analyze_waypoint(
    assets: Assets, name: str, leaf: int, camera: tuple[int, int, int]
) -> dict[str, object]:
    visible = visible_face_ids(assets.pvs_rows[leaf], face_count=len(assets.faces))
    drawable = drawable_face_ids(assets, visible)
    yaw_records: list[dict[str, object]] = []
    for yaw in range(32):
        front, near, screen = projection_stages(assets, drawable, camera, yaw)
        yaw_records.append(
            {
                "yaw": yaw,
                "frontFacing": resource_usage(assets, front),
                "nearValid": resource_usage(assets, near),
                "screenCandidates": resource_usage(assets, screen),
                "sharedPacket": build_packet(assets, screen, "shared"),
                "duplicatedPacket": build_packet(assets, screen, "duplicated"),
            }
        )
    matrix_payload = json.dumps(
        yaw_records, sort_keys=True, separators=(",", ":")
    ).encode("ascii")
    return {
        "name": name,
        "leaf": leaf,
        "camera": list(camera),
        "visible": resource_usage(assets, visible),
        "drawable": resource_usage(assets, drawable),
        "yawMatrixSha256": sha256(matrix_payload),
        "maxScreenCandidates": {
            key: max(record["screenCandidates"][key] for record in yaw_records)
            for key in (
                "faces",
                "sourceUniqueVertices",
                "duplicatedVertices",
                "indices",
            )
        },
        "minSharedSelectedFaces": min(
            record["sharedPacket"]["selectedFaces"] for record in yaw_records
        ),
        "maxSharedDroppedFaces": max(
            record["sharedPacket"]["droppedFaces"] for record in yaw_records
        ),
        "maxDuplicatedDroppedFaces": max(
            record["duplicatedPacket"]["droppedFaces"] for record in yaw_records
        ),
        "yaws": yaw_records,
    }


def build_report(data_dir: Path = DEFAULT_DATA_DIR) -> dict[str, object]:
    assets = load_assets(data_dir)
    waypoints = [analyze_waypoint(assets, *waypoint) for waypoint in WAYPOINTS]
    waypoint_payload = json.dumps(
        waypoints, sort_keys=True, separators=(",", ":")
    ).encode("ascii")
    return {
        "schema": 1,
        "sourceSha256": assets.source_sha256,
        "capacities": {
            "faces": PACKET_FACE_CAPACITY,
            "vertices": PACKET_VERTEX_CAPACITY,
            "indices": PACKET_INDEX_CAPACITY,
        },
        "projectionModel": {
            "logicalResolution": [LOGICAL_WIDTH, LOGICAL_HEIGHT],
            "nearDepth": NEAR_DEPTH,
            "yawSteps": 32,
            "screenTest": "fully projectable fan bbox plus conservative admission of near-straddling faces",
        },
        "allPvs": audit_all_pvs(assets),
        "waypointMatrixSha256": sha256(waypoint_payload),
        "waypoints": waypoints,
        "decision": {
            "retain": "shared vertex remapping with capacity-aware fallback",
            "reject": "duplicated vertices",
            "reason": "shared remapping preserves materially more screen candidates within the 768-vertex limit",
        },
    }


def compact_report(report: dict[str, object]) -> str:
    audit = report["allPvs"]
    capacities = report["capacities"]
    lines = [
        "SNES Quake packet compaction experiment: pass",
        f"capacities: {capacities['faces']} faces, {capacities['vertices']} vertices, {capacities['indices']} indices",
        "full drawable PVS fit: "
        f"shared {audit['fullPacketFit']['sharedVertices']}/{audit['nonSolidRows']}, "
        f"duplicated {audit['fullPacketFit']['duplicatedVertices']}/{audit['nonSolidRows']}",
    ]
    for waypoint in report["waypoints"]:
        maximum = waypoint["maxScreenCandidates"]
        lines.append(
            f"{waypoint['name']} leaf {waypoint['leaf']}: max screen candidates "
            f"{maximum['faces']}f/{maximum['sourceUniqueVertices']} shared-v/"
            f"{maximum['duplicatedVertices']} duplicate-v/{maximum['indices']}i; "
            f"shared max dropped {waypoint['maxSharedDroppedFaces']}, "
            f"duplicate max dropped {waypoint['maxDuplicatedDroppedFaces']}"
        )
    lines.append(f"matrix sha256: {report['waypointMatrixSha256']}")
    lines.append("decision: retain shared remapping; reject duplicated vertices")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument(
        "--json", action="store_true", help="print the complete stable report"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_report(args.data_dir)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(compact_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
