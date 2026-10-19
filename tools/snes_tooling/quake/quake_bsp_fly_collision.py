"""Build and query the bounded SNES fly-camera collision field."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Protocol, Sequence

import numpy as np
from numpy.typing import NDArray


SCHEMA = "quake-bsp-fly-collision-v1"
ROM_HALF_BANK_BYTES = 0x8000
ROM_HALF_BANK_RESERVATION = 2


class NodeLike(Protocol):
    plane: int
    children: tuple[int, int]


def _coordinate_axis(minimum: int, maximum: int, *, label: str) -> NDArray[np.int16]:
    if minimum < -128 or maximum > 127 or minimum > maximum:
        raise ValueError(f"collision {label} bounds escape signed-byte storage")
    return np.arange(minimum, maximum + 1, dtype=np.int16)


def classify_solid_grid(
    nodes: Sequence[NodeLike],
    planes: Sequence[tuple[tuple[int, int, int], int]],
    root: int,
    coordinate_min: tuple[int, int, int],
    coordinate_max: tuple[int, int, int],
) -> tuple[NDArray[np.bool_], int]:
    """Resolve every clamped integer point through the packed signed-16 BSP."""

    if not nodes or not 0 <= root < len(nodes) or len(nodes) >= 0x8000:
        raise ValueError("collision BSP root or node count is invalid")
    if not planes or len(planes) >= 0x8000:
        raise ValueError("collision BSP plane count is invalid")

    xs = _coordinate_axis(coordinate_min[0], coordinate_max[0], label="X")
    ys = _coordinate_axis(coordinate_min[1], coordinate_max[1], label="Y")
    zs = _coordinate_axis(coordinate_min[2], coordinate_max[2], label="Z")
    z_grid, y_grid, x_grid = np.meshgrid(zs, ys, xs, indexing="ij", copy=False)
    shape = (len(zs), len(ys), len(xs))
    x_points = np.broadcast_to(x_grid, shape).ravel()
    y_points = np.broadcast_to(y_grid, shape).ravel()
    z_points = np.broadcast_to(z_grid, shape).ravel()

    node_planes = np.asarray([node.plane for node in nodes], dtype=np.int32)
    front_children = np.asarray([node.children[0] for node in nodes], dtype=np.int16)
    back_children = np.asarray([node.children[1] for node in nodes], dtype=np.int16)
    if np.any(node_planes < 0) or np.any(node_planes >= len(planes)):
        raise ValueError("collision BSP node references an invalid plane")
    for children in (front_children, back_children):
        if np.any(children >= len(nodes)):
            raise ValueError("collision BSP node references an invalid child")

    packed_planes = np.asarray(
        [(*normal, distance) for normal, distance in planes], dtype=np.int16
    )
    current = np.full(x_points.size, root, dtype=np.int16)
    iterations = 0
    while True:
        active = np.flatnonzero(current >= 0)
        if not active.size:
            break
        if iterations >= len(nodes):
            raise ValueError("collision BSP traversal did not terminate")
        node_indices = current[active].astype(np.int32)
        selected_planes = packed_planes[node_planes[node_indices]]

        # Match the GSU packet selector exactly: every product, addition, and
        # final distance subtraction wraps as a signed 16-bit operation.
        dot = (selected_planes[:, 0] * x_points[active]).astype(np.int16)
        dot = (dot + selected_planes[:, 1] * y_points[active]).astype(np.int16)
        dot = (dot + selected_planes[:, 2] * z_points[active]).astype(np.int16)
        front = (dot - selected_planes[:, 3]).astype(np.int16) >= 0
        current[active] = np.where(
            front, front_children[node_indices], back_children[node_indices]
        ).astype(np.int16)
        iterations += 1

    # Quake child -1 is leaf zero, the unique solid leaf. Other negative
    # children are non-solid contents and remain flyable.
    return (current == -1).reshape(shape), iterations


def collision_lookup(
    map_payload: bytes,
    dictionary: bytes,
    column_id_bits: int,
    coordinate_min: tuple[int, int, int],
    coordinate_max: tuple[int, int, int],
    point: tuple[int, int, int],
) -> bool:
    """Query one integer point using the exact runtime map/dictionary layout."""

    counts = tuple(coordinate_max[axis] - coordinate_min[axis] + 1 for axis in range(3))
    if any(
        point[axis] < coordinate_min[axis] or point[axis] > coordinate_max[axis]
        for axis in range(3)
    ):
        raise ValueError("collision point escapes the generated bounds")
    x = point[0] - coordinate_min[0]
    y = point[1] - coordinate_min[1]
    z = point[2] - coordinate_min[2]
    column_bit = (y * counts[0] + x) * column_id_bits
    column_byte = column_bit >> 3
    if column_byte >= len(map_payload):
        raise ValueError("collision column bit offset escapes the map")
    column_word = int.from_bytes(
        map_payload[column_byte : column_byte + 2].ljust(2, b"\0"), "little"
    )
    column_id = (column_word >> (column_bit & 7)) & ((1 << column_id_bits) - 1)
    dictionary_bit = column_id * counts[2] + z
    dictionary_byte = dictionary_bit >> 3
    if dictionary_byte >= len(dictionary):
        raise ValueError("collision column ID escapes the dictionary")
    return bool(dictionary[dictionary_byte] & (1 << (dictionary_bit & 7)))


def build_collision_assets(
    nodes: Sequence[NodeLike],
    planes: Sequence[tuple[tuple[int, int, int], int]],
    root: int,
    coordinate_min: tuple[int, int, int],
    coordinate_max: tuple[int, int, int],
    *,
    node_payload: bytes,
    plane_payload: bytes,
) -> tuple[dict[Path, bytes], dict[str, object]]:
    """Create the canonical XY-column dictionary consumed by the S-CPU."""

    solid, traversal_iterations = classify_solid_grid(
        nodes, planes, root, coordinate_min, coordinate_max
    )
    z_count, y_count, x_count = solid.shape
    column_bytes = (z_count + 7) // 8
    packed = np.packbits(solid, axis=0, bitorder="little")
    columns = np.moveaxis(packed, 0, -1).reshape(x_count * y_count, column_bytes)
    dictionary_rows, column_ids = np.unique(columns, axis=0, return_inverse=True)
    if len(dictionary_rows) > 0x10000:
        raise ValueError("collision dictionary exceeds unsigned-word IDs")
    if not np.array_equal(dictionary_rows[column_ids], columns):
        raise AssertionError("collision dictionary does not reconstruct every column")

    column_id_bits = max(1, (len(dictionary_rows) - 1).bit_length())
    id_bit_indices = np.arange(column_id_bits, dtype=np.uint16)
    id_bits = (
        (column_ids.astype(np.uint16)[:, np.newaxis] >> id_bit_indices) & 1
    ).astype(np.uint8)
    map_payload = np.packbits(id_bits.reshape(-1), bitorder="little").tobytes()
    expected_map_bytes = (len(column_ids) * column_id_bits + 7) // 8
    if len(map_payload) != expected_map_bytes:
        raise AssertionError("collision ID map bit packing changed size")

    dictionary_bits = np.unpackbits(dictionary_rows, axis=1, bitorder="little")[
        :, :z_count
    ]
    dictionary = np.packbits(dictionary_bits.reshape(-1), bitorder="little").tobytes()
    payload = map_payload + dictionary
    payload_chunks = tuple(
        payload[offset : offset + ROM_HALF_BANK_BYTES]
        for offset in range(0, len(payload), ROM_HALF_BANK_BYTES)
    )
    if any(len(chunk) > ROM_HALF_BANK_BYTES for chunk in payload_chunks):
        raise AssertionError("collision payload chunk exceeds one ROM halfbank")
    if len(payload_chunks) > ROM_HALF_BANK_RESERVATION:
        raise AssertionError(
            "collision payload exceeds the fixed ROM halfbank reservation"
        )
    if len(payload) > 0x10000:
        raise AssertionError("collision payload exceeds one 64 KiB WRAM bank")

    include = "\n".join(
        (
            "; Generated by tools/generate_quake_bsp.py. Do not edit.",
            "BSP_COLLISION_SCHEMA_VERSION = 1",
            f"BSP_COLLISION_MIN_X = {coordinate_min[0]}",
            f"BSP_COLLISION_MIN_Y = {coordinate_min[1]}",
            f"BSP_COLLISION_MIN_Z = {coordinate_min[2]}",
            f"BSP_COLLISION_MAX_X = {coordinate_max[0]}",
            f"BSP_COLLISION_MAX_Y = {coordinate_max[1]}",
            f"BSP_COLLISION_MAX_Z = {coordinate_max[2]}",
            f"BSP_COLLISION_X_COUNT = {x_count}",
            f"BSP_COLLISION_Y_COUNT = {y_count}",
            f"BSP_COLLISION_Z_COUNT = {z_count}",
            f"BSP_COLLISION_COLUMN_BYTES = {column_bytes}",
            f"BSP_COLLISION_COLUMN_COUNT = {x_count * y_count}",
            f"BSP_COLLISION_DICTIONARY_COUNT = {len(dictionary_rows)}",
            f"BSP_COLLISION_COLUMN_ID_BITS = {column_id_bits}",
            f"BSP_COLLISION_MAP_BYTES = {len(map_payload)}",
            f"BSP_COLLISION_DICTIONARY_OFFSET = {len(map_payload)}",
            f"BSP_COLLISION_DICTIONARY_BYTES = {len(dictionary)}",
            f"BSP_COLLISION_PAYLOAD_BYTES = {len(payload)}",
            f"BSP_COLLISION_PACKED_CHUNK_COUNT = {len(payload_chunks)}",
            *(
                "BSP_COLLISION_PACKED_"
                f"{index}_BYTES = "
                f"{len(payload_chunks[index]) if index < len(payload_chunks) else 0}"
                for index in range(ROM_HALF_BANK_RESERVATION)
            ),
            "",
        )
    ).encode("ascii")

    source_hash = hashlib.sha256()
    source_hash.update(node_payload)
    source_hash.update(plane_payload)
    padded_payload_chunks = (
        *payload_chunks,
        *(b"" for _ in range(ROM_HALF_BANK_RESERVATION - len(payload_chunks))),
    )
    raw_outputs = {
        **{
            Path(f"QuakeBSPCollisionPacked{index}.bin"): chunk
            for index, chunk in enumerate(padded_payload_chunks)
        },
        Path("QuakeBSPCollision.i"): include,
    }
    report: dict[str, object] = {
        "schema": SCHEMA,
        "source": {
            "nodePlaneSha256": source_hash.hexdigest(),
            "nodeCount": len(nodes),
            "planeCount": len(planes),
            "rootNode": root,
            "solidLeaf": 0,
            "classification": (
                "signed-16 packed Q6 BSP traversal; child -1 is solid leaf zero"
            ),
        },
        "bounds": {
            "minimum": list(coordinate_min),
            "maximum": list(coordinate_max),
            "counts": [x_count, y_count, z_count],
            "pointCount": int(solid.size),
        },
        "storage": {
            "order": (
                "packed little-endian XY column IDs followed by packed "
                "little-endian dictionary Z bits"
            ),
            "columnIdBits": column_id_bits,
            "mapBytes": len(map_payload),
            "columnBytes": column_bytes,
            "dictionaryRows": len(dictionary_rows),
            "dictionaryBytes": len(dictionary),
            "dictionaryOffset": len(map_payload),
            "payloadBytes": len(payload),
            "payloadChunkBytes": [len(chunk) for chunk in payload_chunks],
            "romHalfbanks": len(payload_chunks),
            "wramBytes": len(payload),
        },
        "coverage": {
            "solidPoints": int(np.count_nonzero(solid)),
            "emptyPoints": int(solid.size - np.count_nonzero(solid)),
            "maximumTraversalIterations": traversal_iterations,
            "exactDictionaryReconstruction": True,
        },
        "outputs": {
            str(path): {
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
            for path, payload in raw_outputs.items()
        },
    }
    report_payload = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode(
        "ascii"
    )
    return {
        **raw_outputs,
        Path("QuakeBSPCollision.json"): report_payload,
    }, report
