#!/usr/bin/env python3
"""Build byte-exact bounded render packets from the configured complete world.

The runtime contract has four independently staged little-endian streams:

* vertices: packed ``<bbbB>`` Q2 coordinates (signed bases plus residual bits);
* indices: packed ``<H>`` packet-local vertex indices;
* faces: packed ``<HBBB>`` first-index/count/flat/dither records; and
* face planes: packed signed ``<bbbh>`` Q6 records aligned with face order.

Candidate faces are enumerated in ascending world-face order, rejected with the
same Q2-coordinate/Q6-view/Q12-projection model as the renderer, and admitted
with shared global vertex IDs under the 405-face/768-vertex/2,048-index limits.  Vertex and
index spans retain that admission order.  Only face and plane records are then
emitted in packed-BSP far/node/near order for the painter.  ``source_face_ids``
is a host-only sidecar used to prove ordering and live packet identity.

The oracle reads the configured ``QuakeBSPWorld*`` assets and packed demo
track.  Exact renderer lookup tables are derived locally so the bounded
player-start geometry can never substitute for the full-world streams.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from workspace_paths import workspace_root
from typing import Iterable

import analyze_quake_bsp_packets as admission


DEFAULT_DATA_DIR = workspace_root(__file__) / "src/snes_quake/Data"
DEFAULT_FIXTURE = DEFAULT_DATA_DIR / "QuakeBSPPacketOracle.json"
METADATA_PATH = "QuakeBSPMetadata.json"
DEMO_TRACK_PATH = "QuakeBSPDemoTrack.bin"
DEMO_TRACK_RECORD = struct.Struct("<bbbBb")
NEAR_FIXTURE_POSE = 20
FAR_FIXTURE_POSE = 456

NODE_RECORD = struct.Struct("<HhhHH")
PLANE_RECORD = struct.Struct("<bbbh")
COUNTS_RECORD = struct.Struct("<HHH")
WORLD_NODE_COUNT = 2_942
WORLD_PLANE_COUNT = 2_736
WORLD_ROOT_NODE = 0
SHADING_RECORD = struct.Struct("<bbbB")
APPARENT_LIGHT_LEVELS = 9
TEXTURE_FAMILY_COUNT = 3
DISTANCE_LUT_BYTES = 128
DISTANCE_BUCKET_COUNT = 8
SHADE_TABLE_RECORD_BYTES = 2

SIN_TABLE = (
    0,
    12,
    24,
    36,
    45,
    53,
    59,
    63,
    64,
    63,
    59,
    53,
    45,
    36,
    24,
    12,
    0,
    -12,
    -24,
    -36,
    -45,
    -53,
    -59,
    -63,
    -64,
    -63,
    -59,
    -53,
    -45,
    -36,
    -24,
    -12,
)
COS_TABLE = (
    64,
    63,
    59,
    53,
    45,
    36,
    24,
    12,
    0,
    -12,
    -24,
    -36,
    -45,
    -53,
    -59,
    -63,
    -64,
    -63,
    -59,
    -53,
    -45,
    -36,
    -24,
    -12,
    0,
    12,
    24,
    36,
    45,
    53,
    59,
    63,
)
RECIPROCAL_TABLE = tuple(
    (
        0
        if depth_q4 < admission.NEAR_DEPTH * admission.DEPTH_TABLE_ONE
        else round(admission.SUBPIXEL_RECIPROCAL_NUMERATOR / depth_q4)
    )
    for depth_q4 in range(256 * admission.DEPTH_TABLE_ONE)
)


@dataclass(frozen=True)
class Node:
    plane: int
    front_child: int
    back_child: int
    first_face: int
    face_count: int


@dataclass(frozen=True)
class World:
    assets: admission.Assets
    nodes: tuple[Node, ...]
    bsp_planes: tuple[tuple[int, int, int, int], ...]
    node_parents: tuple[int, ...]
    face_owners: tuple[int, ...]
    shading: tuple[tuple[int, int, int, int], ...]
    distance_lut: bytes
    shade_table: bytes
    root: int
    source_files: tuple[str, ...]
    source_sha256: str


@dataclass(frozen=True)
class CameraState:
    position: tuple[int, int, int]
    yaw: int
    pitch: int


@dataclass(frozen=True)
class Rejections:
    face_capacity: int = 0
    vertex_capacity: int = 0
    index_capacity: int = 0


@dataclass(frozen=True)
class Admission:
    face_ids: tuple[int, ...]
    source_vertex_ids: tuple[int, ...]
    first_indices: tuple[int, ...]
    vertices: bytes
    indices: bytes
    rejections: Rejections


@dataclass(frozen=True)
class Packet:
    camera: CameraState
    leaf: int
    leaf_node_visits: int
    stage_counts: dict[str, int]
    rejections: Rejections
    source_face_ids: tuple[int, ...]
    source_vertex_ids: tuple[int, ...]
    vertices: bytes
    indices: bytes
    faces: bytes
    face_planes: bytes

    @property
    def vertex_count(self) -> int:
        return len(self.vertices) // 4

    @property
    def index_count(self) -> int:
        return len(self.indices) // 2

    @property
    def face_count(self) -> int:
        return len(self.faces) // admission.PACKET_FACE_RECORD.size

    @property
    def face_plane_count(self) -> int:
        return len(self.face_planes) // admission.FACE_PLANE_RECORD.size

    def hashes(self) -> dict[str, str]:
        source_faces = b"".join(
            struct.pack("<H", face_id) for face_id in self.source_face_ids
        )
        streams = (
            ("vertices", self.vertices),
            ("indices", self.indices),
            ("faces", self.faces),
            ("facePlanes", self.face_planes),
        )
        output = {f"{name}Sha256": _sha256(payload) for name, payload in streams}
        output["sourceFacesSha256"] = _sha256(source_faces)
        output["runtimePacketSha256"] = _framed_hash(
            (
                (
                    "counts",
                    COUNTS_RECORD.pack(
                        self.vertex_count, self.index_count, self.face_count
                    ),
                ),
                *streams,
            )
        )
        return output


def fixture_states(
    data_dir: Path = DEFAULT_DATA_DIR,
) -> tuple[tuple[str, CameraState], ...]:
    """Derive canonical fly fixtures from the configured packed demo track."""

    payload = (data_dir / DEMO_TRACK_PATH).read_bytes()
    if len(payload) % DEMO_TRACK_RECORD.size:
        raise ValueError("configured packed demo track has a partial record")
    records = tuple(DEMO_TRACK_RECORD.iter_unpack(payload))
    if len(records) <= FAR_FIXTURE_POSE:
        raise ValueError(
            "configured packed demo track is too short for canonical packet fixtures"
        )

    def state(record: tuple[int, int, int, int, int]) -> CameraState:
        return CameraState(tuple(record[:3]), record[3], record[4] & 0x1F)

    spawn = state(records[0])
    return (
        ("spawn", spawn),
        ("near", state(records[NEAR_FIXTURE_POSE])),
        ("far", state(records[FAR_FIXTURE_POSE])),
        ("yaw", CameraState(spawn.position, (spawn.yaw + 8) & 0x1F, spawn.pitch)),
        ("pitch", CameraState(spawn.position, spawn.yaw, (spawn.pitch + 3) & 0x1F)),
        ("return-spawn", spawn),
    )


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _framed_hash(streams: Iterable[tuple[str, bytes]]) -> str:
    digest = hashlib.sha256()
    for name, payload in streams:
        digest.update(name.encode("ascii") + b"\0")
        digest.update(struct.pack("<I", len(payload)))
        digest.update(payload)
    return digest.hexdigest()


def _signed8(value: int) -> int:
    value &= 0xFF
    return value - 0x100 if value & 0x80 else value


def _signed16(value: int) -> int:
    value &= 0xFFFF
    return value - 0x10000 if value & 0x8000 else value


def signed_pitch(value: int) -> int:
    value &= 0x1F
    return value - 0x20 if value & 0x10 else value


def _pack_q2_vertex(vertex: tuple[int, int, int]) -> bytes:
    bases = tuple(component // 4 for component in vertex)
    residual = (vertex[0] & 3) | ((vertex[1] & 3) << 2) | ((vertex[2] & 3) << 4)
    return struct.pack("<bbbB", *bases, residual)


def _unpack_q2_vertices(payload: bytes) -> tuple[tuple[int, int, int], ...]:
    return tuple(
        (
            x * 4 + (residual & 3),
            y * 4 + ((residual >> 2) & 3),
            z * 4 + ((residual >> 4) & 3),
        )
        for x, y, z, residual in struct.iter_unpack("<bbbB", payload)
    )


def _front_side(plane: tuple[int, int, int, int], camera: tuple[int, int, int]) -> bool:
    nx, ny, nz, distance = plane
    dot = _signed16(_signed8(nx) * _signed8(camera[0]))
    dot = _signed16(dot + _signed8(ny) * _signed8(camera[1]))
    dot = _signed16(dot + _signed8(nz) * _signed8(camera[2]))
    return _signed16(dot - distance) >= 0


def _validate_camera(camera: CameraState) -> None:
    if (
        len(camera.position) != 3
        or any(type(value) is not int for value in camera.position)
        or any(value < -128 or value > 127 for value in camera.position)
    ):
        raise ValueError("camera position must contain three signed bytes")
    if type(camera.yaw) is not int or not 0 <= camera.yaw < 32:
        raise ValueError("camera yaw must be in 0..31")
    if type(camera.pitch) is not int or not 0 <= camera.pitch < 32:
        raise ValueError("camera pitch must be in 0..31")


def load_world(data_dir: Path = DEFAULT_DATA_DIR) -> World:
    """Load and validate only the checked-in complete-world streams."""

    admission.validate_pvs_placement(data_dir)
    digest = hashlib.sha256()
    source_files: list[str] = []

    try:
        metadata = json.loads((data_dir / METADATA_PATH).read_text(encoding="utf-8"))
        world_metadata = metadata["world"]
        packing = world_metadata["packing"]
        vertex_count = int(packing["vertex_count"])
        index_count = int(packing["index_count"])
        face_count = int(packing["face_count"])
        node_count = int(packing["node_count"])
        plane_count = int(packing["plane_count"])
        root_node = int(world_metadata["root_node"])
        pvs_row_count = int(world_metadata["vis_leaf_count"]) + 1
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("world metadata lacks a valid runtime layout") from error
    if (
        min(
            vertex_count,
            index_count,
            face_count,
            node_count,
            plane_count,
            pvs_row_count,
        )
        < 1
    ):
        raise ValueError("world metadata has an empty runtime layout")
    if not 0 <= root_node < node_count:
        raise ValueError("world metadata root node escapes the node table")
    pvs_row_bytes = (face_count + 7) // 8
    pvs_tail_mask = 0xFF if not face_count & 7 else (1 << (face_count & 7)) - 1

    def read(name: str) -> bytes:
        if not name.startswith("QuakeBSPWorld"):
            raise ValueError("oracle source is not a complete-world stream")
        payload = (data_dir / name).read_bytes()
        source_files.append(name)
        digest.update(name.encode("ascii"))
        digest.update(struct.pack("<I", len(payload)))
        digest.update(payload)
        return payload

    vertex_bytes = read("QuakeBSPWorldVertices.bin")
    index_bytes = read("QuakeBSPWorldIndices0.bin") + read("QuakeBSPWorldIndices1.bin")
    face_bytes = read("QuakeBSPWorldFaces.bin")
    face_plane_bytes = read("QuakeBSPWorldFacePlanes.bin")
    node_bytes = read("QuakeBSPWorldNodes.bin")
    node_parent_bytes = read("QuakeBSPWorldNodeParents.bin")
    face_owner_bytes = read("QuakeBSPWorldFaceOwners.bin")
    shading_bytes = read("QuakeBSPWorldShading.bin")
    bsp_plane_bytes = read("QuakeBSPWorldPlanes.bin")
    directory = read("QuakeBSPWorldPVSDirectory.bin")
    guard_bytes = read("QuakeBSPWorldPVSGuards.bin")

    expected_sizes = (
        (vertex_bytes, vertex_count * 4, "world vertices"),
        (index_bytes, index_count * 2, "world indices"),
        (
            face_bytes,
            face_count * admission.WORLD_FACE_RECORD.size,
            "world faces",
        ),
        (
            face_plane_bytes,
            face_count * admission.FACE_PLANE_RECORD.size,
            "world face planes",
        ),
        (node_bytes, node_count * NODE_RECORD.size, "world nodes"),
        (node_parent_bytes, node_count * 2, "world node parents"),
        (
            face_owner_bytes,
            face_count * 2,
            "world face owners",
        ),
        (
            shading_bytes,
            face_count * SHADING_RECORD.size
            + DISTANCE_LUT_BYTES
            + TEXTURE_FAMILY_COUNT
            * APPARENT_LIGHT_LEVELS
            * DISTANCE_BUCKET_COUNT
            * SHADE_TABLE_RECORD_BYTES,
            "world shading",
        ),
        (bsp_plane_bytes, plane_count * PLANE_RECORD.size, "world planes"),
    )
    for payload, expected, description in expected_sizes:
        if len(payload) != expected:
            raise ValueError(f"{description} asset has the wrong size")
    if len(directory) % admission.PVS_DIRECTORY_RECORD.size:
        raise ValueError("world face-PVS directory is not record aligned")
    if len(guard_bytes) % admission.PVS_GUARD_RECORD.size:
        raise ValueError("world face-PVS guards are not record aligned")

    vertices = tuple(
        (
            x * 4 + (residual & 3),
            y * 4 + ((residual >> 2) & 3),
            z * 4 + ((residual >> 4) & 3),
        )
        for x, y, z, residual in struct.iter_unpack("<bbbB", vertex_bytes)
    )
    indices = tuple(value for (value,) in struct.iter_unpack("<H", index_bytes))
    faces = tuple(
        admission.Face(*record)
        for record in admission.WORLD_FACE_RECORD.iter_unpack(face_bytes)
    )
    face_planes = tuple(admission.FACE_PLANE_RECORD.iter_unpack(face_plane_bytes))
    if max(indices) >= len(vertices):
        raise ValueError("world index escapes the vertex stream")
    for face in faces:
        if face.first_index + face.vertex_count > len(indices):
            raise ValueError("world face escapes the index streams")

    nodes = tuple(Node(*record) for record in NODE_RECORD.iter_unpack(node_bytes))
    node_parents = tuple(
        value for (value,) in struct.iter_unpack("<H", node_parent_bytes)
    )
    face_owners = tuple(
        value for (value,) in struct.iter_unpack("<H", face_owner_bytes)
    )
    shading_record_bytes = face_count * SHADING_RECORD.size
    shading = tuple(SHADING_RECORD.iter_unpack(shading_bytes[:shading_record_bytes]))
    distance_lut = shading_bytes[
        shading_record_bytes : shading_record_bytes + DISTANCE_LUT_BYTES
    ]
    shade_table = shading_bytes[shading_record_bytes + DISTANCE_LUT_BYTES :]
    for centroid_x, centroid_y, centroid_z, base_shade in shading:
        if not all(
            -128 <= value <= 127 for value in (centroid_x, centroid_y, centroid_z)
        ):
            raise ValueError("world shading centroid escapes signed-byte storage")
        if base_shade >= TEXTURE_FAMILY_COUNT * APPARENT_LIGHT_LEVELS:
            raise ValueError("world shading base index escapes material families")
    if len(distance_lut) != DISTANCE_LUT_BYTES or any(
        bucket >= DISTANCE_BUCKET_COUNT for bucket in distance_lut
    ):
        raise ValueError("world shading distance LUT is invalid")
    if len(shade_table) != (
        TEXTURE_FAMILY_COUNT
        * APPARENT_LIGHT_LEVELS
        * DISTANCE_BUCKET_COUNT
        * SHADE_TABLE_RECORD_BYTES
    ):
        raise ValueError("world shading apparent-shade table is invalid")
    for flat, dither in struct.iter_unpack("<BB", shade_table):
        if flat == 0 or not 1 <= (dither & 0x0F) <= 15 or not 1 <= (dither >> 4) <= 15:
            raise ValueError("world shading table emits diagnostic pink")
    bsp_planes = tuple(PLANE_RECORD.iter_unpack(bsp_plane_bytes))
    for node in nodes:
        if node.plane >= len(bsp_planes):
            raise ValueError("world node references an invalid plane")
        for child in (node.front_child, node.back_child):
            if child >= len(nodes):
                raise ValueError("world node references an invalid child")
    if node_parents[root_node] != 0xFFFF:
        raise ValueError("world root must use the parent-table sentinel")
    reachable = {root_node}
    stack = [root_node]
    while stack:
        node_index = stack.pop()
        for child in (nodes[node_index].front_child, nodes[node_index].back_child):
            if child < 0:
                continue
            if child in reachable:
                raise ValueError("world BSP contains a cycle or repeated node")
            if node_parents[child] != node_index:
                raise ValueError("world node-parent table disagrees with BSP children")
            reachable.add(child)
            stack.append(child)
    for face_id, owner in enumerate(face_owners):
        if owner not in reachable:
            raise ValueError("world face owner is not reachable from the world root")
        node = nodes[owner]
        if not node.first_face <= face_id < node.first_face + node.face_count:
            raise ValueError("world face-owner table disagrees with node face ranges")

    guards = tuple(admission.PVS_GUARD_RECORD.iter_unpack(guard_bytes))
    if len({offset for offset, _mask in guards}) != len(guards):
        raise ValueError("world face-PVS guards contain a duplicate byte offset")
    for offset, mask in guards:
        if offset >= pvs_row_bytes or not mask:
            raise ValueError("world face-PVS guard escapes the decoded row")
        if offset == pvs_row_bytes - 1 and mask & ~pvs_tail_mask:
            raise ValueError("world face-PVS guard sets nonexistent faces")

    chunk_cache: dict[int, bytes] = {}
    pvs_rows: list[bytes] = []
    for leaf, (address, encoded_bytes, face_count, bank, flags) in enumerate(
        admission.PVS_DIRECTORY_RECORD.iter_unpack(directory)
    ):
        if flags:
            raise ValueError(f"leaf {leaf} has nonzero face-PVS flags")
        chunk_index = bank - admission.WORLD_PVS_FIRST_BANK
        if chunk_index < 0:
            raise ValueError(f"leaf {leaf} has an invalid face-PVS bank")
        if chunk_index not in chunk_cache:
            chunk_cache[chunk_index] = read(f"QuakeBSPWorldPVS{chunk_index}.bin")
        chunk = chunk_cache[chunk_index]
        offset = address - 0x8000
        if offset < 0 or offset + encoded_bytes > len(chunk):
            raise ValueError(f"leaf {leaf} face-PVS row escapes its chunk")
        row = bytearray(
            admission.decode_zero_runs(
                chunk[offset : offset + encoded_bytes],
                pvs_row_bytes,
            )
        )
        for guard_offset, mask in guards:
            row[guard_offset] |= mask
        if row[-1] & ~pvs_tail_mask:
            raise ValueError(f"leaf {leaf} face-PVS row sets nonexistent faces")
        if sum(value.bit_count() for value in row) != face_count:
            raise ValueError(f"leaf {leaf} face-PVS count disagrees with directory")
        pvs_rows.append(bytes(row))
    if len(pvs_rows) != pvs_row_count:
        raise ValueError(f"world face-PVS directory must contain {pvs_row_count} rows")

    assets = admission.Assets(
        vertices=vertices,
        vertex_fraction_bits=2,
        indices=indices,
        faces=faces,
        face_planes=face_planes,
        pvs_rows=tuple(pvs_rows),
        sin_table=SIN_TABLE,
        cos_table=COS_TABLE,
        reciprocal_table=RECIPROCAL_TABLE,
        source_sha256=digest.hexdigest(),
    )
    return World(
        assets=assets,
        nodes=nodes,
        bsp_planes=bsp_planes,
        node_parents=node_parents,
        face_owners=face_owners,
        shading=shading,
        distance_lut=distance_lut,
        shade_table=shade_table,
        root=root_node,
        source_files=tuple(source_files),
        source_sha256=digest.hexdigest(),
    )


def locate_leaf(world: World, camera: tuple[int, int, int]) -> tuple[int, int]:
    node_index = world.root
    visited: set[int] = set()
    while node_index >= 0:
        if node_index >= len(world.nodes):
            raise ValueError("BSP traversal references an invalid node")
        if node_index in visited:
            raise ValueError("BSP traversal contains a node cycle")
        visited.add(node_index)
        node = world.nodes[node_index]
        child = (
            node.front_child
            if _front_side(world.bsp_planes[node.plane], camera)
            else node.back_child
        )
        node_index = child
    leaf = ~node_index
    if not 0 <= leaf < len(world.assets.pvs_rows):
        raise ValueError("BSP traversal resolves outside the face-PVS rows")
    return leaf, len(visited)


def admit_shared_faces(
    assets: admission.Assets, candidates: Iterable[int]
) -> Admission:
    candidate_ids = tuple(candidates)
    if candidate_ids != tuple(sorted(set(candidate_ids))):
        raise ValueError("packet candidates must be unique ascending face IDs")

    selected: list[int] = []
    source_vertex_ids: list[int] = []
    vertex_lookup: dict[int, int] = {}
    first_indices: list[int] = []
    packed_indices: list[int] = []
    face_drops = vertex_drops = index_drops = 0
    for face_id in candidate_ids:
        if not 0 <= face_id < len(assets.faces):
            raise ValueError("packet candidate face ID is outside the world stream")
        face = assets.faces[face_id]
        if face.vertex_count < 3 or (
            face.flags & admission.WORLD_FACE_FLAG_NON_DRAWABLE
        ):
            raise ValueError("packet candidate is not a drawable world face")
        source_indices = assets.indices[
            face.first_index : face.first_index + face.vertex_count
        ]
        if len(source_indices) != face.vertex_count or any(
            index >= len(assets.vertices) for index in source_indices
        ):
            raise ValueError("packet candidate has malformed source indices")
        added_vertices = sum(
            1 for source_id in set(source_indices) if source_id not in vertex_lookup
        )
        if len(selected) >= admission.PACKET_FACE_CAPACITY:
            face_drops += 1
            continue
        if len(source_vertex_ids) + added_vertices > admission.PACKET_VERTEX_CAPACITY:
            vertex_drops += 1
            continue
        if len(packed_indices) + len(source_indices) > admission.PACKET_INDEX_CAPACITY:
            index_drops += 1
            continue

        selected.append(face_id)
        first_indices.append(len(packed_indices))
        for source_id in source_indices:
            packet_id = vertex_lookup.get(source_id)
            if packet_id is None:
                packet_id = len(source_vertex_ids)
                vertex_lookup[source_id] = packet_id
                source_vertex_ids.append(source_id)
            packed_indices.append(packet_id)

    vertex_bytes = b"".join(
        _pack_q2_vertex(assets.vertices[source_id]) for source_id in source_vertex_ids
    )
    index_bytes = b"".join(struct.pack("<H", value) for value in packed_indices)
    return Admission(
        face_ids=tuple(selected),
        source_vertex_ids=tuple(source_vertex_ids),
        first_indices=tuple(first_indices),
        vertices=vertex_bytes,
        indices=index_bytes,
        rejections=Rejections(face_drops, vertex_drops, index_drops),
    )


def far_to_near_order(
    world: World, selected: Iterable[int], camera: tuple[int, int, int]
) -> tuple[int, ...]:
    selected_ids = tuple(selected)
    if len(selected_ids) != len(set(selected_ids)):
        raise ValueError("BSP painter input contains duplicate faces")
    selected_set = set(selected_ids)
    if any(
        face_id < 0 or face_id >= len(world.assets.faces) for face_id in selected_set
    ):
        raise ValueError("BSP painter input contains an invalid face")

    output: list[int] = []
    emitted: set[int] = set()
    visiting: set[int] = set()
    visited: set[int] = set()

    def visit(node_index: int) -> None:
        if node_index < 0:
            leaf = ~node_index
            if not 0 <= leaf < len(world.assets.pvs_rows):
                raise ValueError("BSP painter traversal references an invalid leaf")
            return
        if node_index >= len(world.nodes):
            raise ValueError("BSP painter traversal references an invalid node")
        if node_index in visiting:
            raise ValueError("BSP painter traversal contains a node cycle")
        if node_index in visited:
            raise ValueError("BSP painter traversal revisits a node")
        visiting.add(node_index)
        node = world.nodes[node_index]
        if node.first_face + node.face_count > len(world.assets.faces):
            raise ValueError("BSP painter node escapes the world face stream")
        front = _front_side(world.bsp_planes[node.plane], camera)
        far_child = node.back_child if front else node.front_child
        near_child = node.front_child if front else node.back_child
        visit(far_child)
        for face_id in range(node.first_face, node.first_face + node.face_count):
            if face_id in selected_set:
                if face_id in emitted:
                    raise ValueError("BSP painter emits a selected face twice")
                emitted.add(face_id)
                output.append(face_id)
        visit(near_child)
        visiting.remove(node_index)
        visited.add(node_index)

    visit(world.root)
    if emitted != selected_set:
        raise ValueError("selected faces are absent from the world BSP root")
    return tuple(output)


def induced_painter_nodes(world: World, selected: Iterable[int]) -> frozenset[int]:
    """Return accepted-face owners and their ancestors up to the world root."""

    marked: set[int] = set()
    for face_id in selected:
        if not 0 <= face_id < len(world.face_owners):
            raise ValueError("induced painter input contains an invalid face")
        node = world.face_owners[face_id]
        while node != 0xFFFF and node not in marked:
            marked.add(node)
            node = world.node_parents[node]
    if marked and world.root not in marked:
        raise ValueError("induced painter tree does not terminate at the world root")
    return frozenset(marked)


def material_face_colors(
    world: World, face_id: int, camera: tuple[int, int, int]
) -> tuple[int, int]:
    centroid_x, centroid_y, centroid_z, base_shade = world.shading[face_id]
    distances = sorted(
        (
            abs(centroid_x - camera[0]),
            abs(centroid_y - camera[1]),
            abs(centroid_z - camera[2]),
        )
    )
    distance = distances[2] + distances[1] // 2 + distances[0] // 4
    bucket = world.distance_lut[min(distance, len(world.distance_lut) - 1)]
    offset = (base_shade * DISTANCE_BUCKET_COUNT + bucket) * 2
    flat, dither = world.shade_table[offset : offset + 2]
    if flat == 0 or (dither & 0x0F) == 0 or (dither >> 4) == 0:
        raise ValueError("drawable material face uses diagnostic pink")
    return flat, dither


def serialize_admission(
    world: World,
    camera: CameraState,
    leaf: int,
    leaf_visits: int,
    stage_counts: dict[str, int],
    admitted: Admission,
) -> Packet:
    draw_order = far_to_near_order(world, admitted.face_ids, camera.position)
    first_by_face = dict(zip(admitted.face_ids, admitted.first_indices, strict=True))
    face_bytes = bytearray()
    plane_bytes = bytearray()
    for face_id in draw_order:
        source = world.assets.faces[face_id]
        flat, dither = material_face_colors(world, face_id, camera.position)
        face_bytes.extend(
            admission.PACKET_FACE_RECORD.pack(
                first_by_face[face_id],
                source.vertex_count,
                flat,
                dither,
            )
        )
        plane_bytes.extend(
            admission.FACE_PLANE_RECORD.pack(*world.assets.face_planes[face_id])
        )
    packet = Packet(
        camera=camera,
        leaf=leaf,
        leaf_node_visits=leaf_visits,
        stage_counts=stage_counts,
        rejections=admitted.rejections,
        source_face_ids=draw_order,
        source_vertex_ids=admitted.source_vertex_ids,
        vertices=admitted.vertices,
        indices=admitted.indices,
        faces=bytes(face_bytes),
        face_planes=bytes(plane_bytes),
    )
    validate_packet(world, packet)
    return packet


def build_render_packet(
    world: World,
    camera: CameraState,
    *,
    view_transform: admission.ViewTransform | None = None,
) -> Packet:
    _validate_camera(camera)
    leaf, visits = locate_leaf(world, camera.position)
    visible = admission.visible_face_ids(
        world.assets.pvs_rows[leaf], face_count=len(world.assets.faces)
    )
    drawable = admission.drawable_face_ids(world.assets, visible)
    front, near, screen = admission.projection_stages(
        world.assets,
        drawable,
        camera.position,
        camera.yaw,
        camera.pitch,
        view_transform=view_transform,
    )
    admitted = admit_shared_faces(world.assets, screen)
    stage_counts = {
        "pvsFaces": len(visible),
        "drawableFaces": len(drawable),
        "frontFacingFaces": len(front),
        "nearValidFaces": len(near),
        "screenCandidateFaces": len(screen),
        "selectedFaces": len(admitted.face_ids),
    }
    return serialize_admission(world, camera, leaf, visits, stage_counts, admitted)


def validate_packet(world: World, packet: Packet) -> None:
    if len(packet.vertices) % 4:
        raise ValueError("packet vertex stream is not record aligned")
    if len(packet.indices) % 2:
        raise ValueError("packet index stream is not record aligned")
    if len(packet.faces) % admission.PACKET_FACE_RECORD.size:
        raise ValueError("packet face stream is not record aligned")
    if len(packet.face_planes) % admission.FACE_PLANE_RECORD.size:
        raise ValueError("packet face-plane stream is not record aligned")
    if packet.vertex_count > admission.PACKET_VERTEX_CAPACITY:
        raise ValueError("packet exceeds the vertex capacity")
    if packet.index_count > admission.PACKET_INDEX_CAPACITY:
        raise ValueError("packet exceeds the index capacity")
    if packet.face_count > admission.PACKET_FACE_CAPACITY:
        raise ValueError("packet exceeds the face capacity")
    if packet.face_plane_count > admission.PACKET_FACE_CAPACITY:
        raise ValueError("packet exceeds the face-plane capacity")
    if packet.face_plane_count != packet.face_count:
        raise ValueError("packet face-plane count disagrees with face count")
    if len(packet.source_face_ids) != packet.face_count:
        raise ValueError("packet source-face sidecar disagrees with face count")
    if len(packet.source_vertex_ids) != packet.vertex_count:
        raise ValueError("packet source-vertex sidecar disagrees with vertex count")
    if len(set(packet.source_face_ids)) != packet.face_count:
        raise ValueError("packet source-face sidecar contains duplicates")
    if len(set(packet.source_vertex_ids)) != packet.vertex_count:
        raise ValueError("packet source-vertex sidecar contains duplicates")

    packet_vertices = _unpack_q2_vertices(packet.vertices)
    for packet_id, source_id in enumerate(packet.source_vertex_ids):
        if not 0 <= source_id < len(world.assets.vertices):
            raise ValueError("packet source vertex escapes the world stream")
        if packet_vertices[packet_id] != world.assets.vertices[source_id]:
            raise ValueError("packet vertex bytes disagree with source vertices")
    packet_indices = tuple(
        value for (value,) in struct.iter_unpack("<H", packet.indices)
    )
    if any(index >= packet.vertex_count for index in packet_indices):
        raise ValueError("packet index escapes emitted vertices")
    remap = {
        source_id: packet_id
        for packet_id, source_id in enumerate(packet.source_vertex_ids)
    }

    intervals: list[tuple[int, int]] = []
    plane_records = tuple(admission.FACE_PLANE_RECORD.iter_unpack(packet.face_planes))
    for position, record in enumerate(
        admission.PACKET_FACE_RECORD.iter_unpack(packet.faces)
    ):
        first_index, count, flat, dither = record
        source_id = packet.source_face_ids[position]
        if not 0 <= source_id < len(world.assets.faces):
            raise ValueError("packet source face escapes the world stream")
        source = world.assets.faces[source_id]
        expected_flat, expected_dither = material_face_colors(
            world, source_id, packet.camera.position
        )
        if (count, flat, dither) != (
            source.vertex_count,
            expected_flat,
            expected_dither,
        ):
            raise ValueError("packet face record disagrees with its source face")
        if plane_records[position] != world.assets.face_planes[source_id]:
            raise ValueError("packet face plane disagrees with its source face")
        end = first_index + count
        if end > packet.index_count:
            raise ValueError("packet face index span escapes the index stream")
        source_indices = world.assets.indices[
            source.first_index : source.first_index + source.vertex_count
        ]
        expected = tuple(remap[source_index] for source_index in source_indices)
        if packet_indices[first_index:end] != expected:
            raise ValueError("packet remapped indices disagree with the source face")
        intervals.append((first_index, end))
    cursor = 0
    for begin, end in sorted(intervals):
        if begin != cursor:
            raise ValueError("packet face index spans are not contiguous")
        cursor = end
    if cursor != packet.index_count:
        raise ValueError("packet face index spans do not cover the index stream")


def _fixture_record(name: str, packet: Packet, world: World) -> dict[str, object]:
    return {
        "name": name,
        "camera": list(packet.camera.position),
        "yaw": packet.camera.yaw,
        "pitch": signed_pitch(packet.camera.pitch),
        "leaf": packet.leaf,
        "leafNodeVisits": packet.leaf_node_visits,
        "painterInducedNodes": len(
            induced_painter_nodes(world, packet.source_face_ids)
        ),
        "stageCounts": packet.stage_counts,
        "capacityRejections": asdict(packet.rejections),
        "counts": {
            "vertices": packet.vertex_count,
            "indices": packet.index_count,
            "faces": packet.face_count,
        },
        "bytes": {
            "vertices": len(packet.vertices),
            "indices": len(packet.indices),
            "faces": len(packet.faces),
            "facePlanes": len(packet.face_planes),
        },
        "sourceFaceIds": list(packet.source_face_ids),
        "hashes": packet.hashes(),
    }


def build_fixture_document(data_dir: Path = DEFAULT_DATA_DIR) -> dict[str, object]:
    world = load_world(data_dir)
    states = fixture_states(data_dir)
    packets = [
        (name, build_render_packet(world, state)) for name, state in states
    ]
    spawn_faces = set(packets[0][1].source_face_ids)
    fixtures = []
    for name, packet in packets:
        record = _fixture_record(name, packet, world)
        record["sourceFacesAbsentFromSpawn"] = sorted(
            set(packet.source_face_ids) - spawn_faces
        )
        fixtures.append(record)
    spawn = packets[0][1]
    returned = packets[-1][1]
    return {
        "schema": 3,
        "sourceSha256": world.source_sha256,
        "sourceFiles": list(world.source_files),
        "cameraSource": {
            "file": DEMO_TRACK_PATH,
            "sha256": _sha256((data_dir / DEMO_TRACK_PATH).read_bytes()),
        },
        "contract": {
            "selection": "ascending world-face ID; drawable/front/near/screen rejection; skip on face, then vertex, then index capacity",
            "painterOrder": "packed-Q6 signed-16 wrapped dot-distance; >=0 selects front/child 0; emit far child, node faces ascending, near child",
            "remap": "shared global vertex IDs assigned on first use in ascending admission order",
            "shading": "per emitted face: signed-byte centroid distance surrogate -> 128-byte bucket LUT; family/orientation base plus bucket -> flat/checker LUT",
            "streams": {
                "vertices": {
                    "format": "<bbbB",
                    "recordBytes": admission.PACKET_VERTEX_RECORD.size,
                    "semantics": "Q2 xyz = signed base*4 + packed 2-bit residual",
                },
                "indices": {
                    "format": "<H",
                    "recordBytes": admission.PACKET_INDEX_RECORD.size,
                },
                "faces": {
                    "format": "<HBBB",
                    "recordBytes": admission.PACKET_FACE_RECORD.size,
                    "storage": "canonical contiguous bytes",
                },
                "facePlanes": {
                    "format": "<bbbh",
                    "recordBytes": admission.FACE_PLANE_RECORD.size,
                },
                "sourceFaceIds": {
                    "format": "<H",
                    "recordBytes": 2,
                    "hostOnly": True,
                },
            },
            "capacities": {
                "vertices": admission.PACKET_VERTEX_CAPACITY,
                "indices": admission.PACKET_INDEX_CAPACITY,
                "faces": admission.PACKET_FACE_CAPACITY,
                "facePlanes": admission.PACKET_FACE_CAPACITY,
            },
            "runtimeHashFraming": "for counts,vertices,indices,faces,facePlanes: ASCII name + NUL, u32 little-endian byte length, payload; counts=<vertex_count,index_count,face_count> as <HHH>",
            "sourceFaceIds": "host-only <H> evidence sidecar in painter order",
            "painterNodeMask": "accepted face owners plus parent links to world root",
        },
        "returnSpawnByteIdentical": (
            spawn.vertices,
            spawn.indices,
            spawn.faces,
            spawn.face_planes,
        )
        == (
            returned.vertices,
            returned.indices,
            returned.faces,
            returned.face_planes,
        ),
        "fixtures": fixtures,
    }


def fixture_bytes(document: dict[str, object]) -> bytes:
    return (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")


def compact_report(document: dict[str, object]) -> str:
    lines = ["SNES Quake full-world packet oracle: pass"]
    for fixture in document["fixtures"]:
        counts = fixture["counts"]
        lines.append(
            f"{fixture['name']}: leaf {fixture['leaf']}, "
            f"{counts['faces']}f/{counts['vertices']}v/{counts['indices']}i, "
            f"packet {fixture['hashes']['runtimePacketSha256']}"
        )
    lines.append(
        f"return spawn byte-identical: {str(document['returnSpawnByteIdentical']).lower()}"
    )
    lines.append(f"fixture sha256: {_sha256(fixture_bytes(document))}")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--json", action="store_true", help="print complete JSON")
    actions.add_argument(
        "--write",
        nargs="?",
        type=Path,
        const=DEFAULT_FIXTURE,
        help="write the deterministic fixture (default: checked-in path)",
    )
    actions.add_argument(
        "--check",
        nargs="?",
        type=Path,
        const=DEFAULT_FIXTURE,
        help="compare with the checked-in fixture",
    )
    return parser.parse_args()


def main() -> int:
    started = time.perf_counter()
    args = parse_args()
    document = build_fixture_document(args.data_dir)
    payload = fixture_bytes(document)
    if args.write is not None:
        args.write.parent.mkdir(parents=True, exist_ok=True)
        args.write.write_bytes(payload)
        print(
            f"wrote {args.write} ({len(payload)} bytes, sha256 {_sha256(payload)}, "
            f"elapsed {time.perf_counter() - started:.3f}s)"
        )
    elif args.check is not None:
        if not args.check.is_file() or args.check.read_bytes() != payload:
            raise SystemExit(f"packet oracle fixture differs: {args.check}")
        print(
            f"packet oracle fixture check: pass ({_sha256(payload)}, "
            f"elapsed {time.perf_counter() - started:.3f}s)"
        )
    elif args.json:
        print(payload.decode("utf-8"), end="")
        print(
            f"packet oracle JSON: pass (elapsed {time.perf_counter() - started:.3f}s)",
            file=sys.stderr,
        )
    else:
        print(
            f"{compact_report(document)}\nelapsed: {time.perf_counter() - started:.3f}s"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
