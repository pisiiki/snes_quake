"""Audit leaf-clipped Quake brush fragments on the canonical 2 Hz route."""

from __future__ import annotations

import hashlib
import json
import math
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import generate_quake_bsp as bsp_tools
from quake_brush_replay import CanonicalBrushReplay, step_row_indices


PLANE_EPSILON = 1e-7
FRAGMENT_MAGIC = b"QBSF"
FRAGMENT_VERSION = 3
FRAGMENT_HEADER = struct.Struct("<4s15I")
VARIANT_RECORD = struct.Struct("<BBhhhHHhhhHHH")
BUCKET_RECORD = struct.Struct("<HHBBH")
FRAGMENT_RECORD = struct.Struct("<HIBB")
FACE_MATERIAL_RECORD = struct.Struct("<HHHBbbhhBBB")
VERTEX_RECORD_BYTES = 4
ROM_BANK_BYTES = bsp_tools.ROM_BANK_BYTES
SIGNED_Q4_AXIS_SPAN_LIMIT = 0x8000


@dataclass(frozen=True)
class Fragment:
    source_face: int
    leaf: int
    polygon: tuple[tuple[float, float, float], ...]


@dataclass(frozen=True)
class FragmentAssetBuild:
    outputs: dict[Path, bytes]
    metadata: dict[str, Any]
    variant_leaf_groups: tuple[dict[int, tuple[int, int]], ...]


def _world_leaf_parents(source: Any, root: int) -> tuple[int, ...]:
    """Return each reachable leaf's owning world-node index."""

    parents = [-1] * len(source.leaves)
    stack = [root]
    while stack:
        node_index = stack.pop()
        for child in source.nodes[node_index].children:
            if child >= 0:
                stack.append(child)
                continue
            leaf = ~child
            if not 0 <= leaf < len(parents):
                raise ValueError(f"world node {node_index} has invalid leaf {leaf}")
            previous = parents[leaf]
            if previous < 0:
                parents[leaf] = node_index
            elif leaf != 0 and previous != node_index:
                raise ValueError(f"world leaf {leaf} has multiple parents")
    return tuple(0xFFFF if parent < 0 else parent for parent in parents)


def _face_vertex_ids(source: Any, face: Any) -> tuple[int, ...]:
    output = []
    for index in range(face.first_edge, face.first_edge + face.edge_count):
        surfedge = source.surfedges[index]
        edge = source.edges[abs(surfedge)]
        output.append(edge[0] if surfedge >= 0 else edge[1])
    return tuple(output)


def _q3(value: float) -> int:
    quantized = round(value * 8.0)
    if quantized / 8.0 != value or not -0x8000 <= quantized <= 0x7FFF:
        raise ValueError("fragment-audit origin is not exact signed Q3")
    return quantized


def _clip_half(
    polygon: tuple[tuple[float, float, float], ...],
    plane: tuple[object, ...],
    keep_front: bool,
) -> tuple[tuple[float, float, float], ...]:
    if not polygon:
        return ()
    normal = tuple(float(plane[axis]) for axis in range(3))
    distance = float(plane[3])
    output: list[tuple[float, float, float]] = []
    previous = polygon[-1]
    previous_distance = (
        sum(previous[axis] * normal[axis] for axis in range(3)) - distance
    )
    previous_inside = (
        previous_distance >= -PLANE_EPSILON
        if keep_front
        else previous_distance <= PLANE_EPSILON
    )
    for current in polygon:
        current_distance = (
            sum(current[axis] * normal[axis] for axis in range(3)) - distance
        )
        current_inside = (
            current_distance >= -PLANE_EPSILON
            if keep_front
            else current_distance <= PLANE_EPSILON
        )
        if current_inside != previous_inside:
            denominator = previous_distance - current_distance
            fraction = (
                0.0 if abs(denominator) <= 1e-20 else previous_distance / denominator
            )
            output.append(
                tuple(
                    previous[axis] + (current[axis] - previous[axis]) * fraction
                    for axis in range(3)
                )
            )
        if current_inside:
            output.append(current)
        previous = current
        previous_distance = current_distance
        previous_inside = current_inside
    clean: list[tuple[float, float, float]] = []
    for vertex in output:
        if not clean or vertex != clean[-1]:
            clean.append(vertex)
    if len(clean) > 1 and clean[0] == clean[-1]:
        clean.pop()
    return tuple(clean)


def _clip_face_to_world(
    source: Any,
    root: int,
    source_face: int,
    polygon: tuple[tuple[float, float, float], ...],
) -> tuple[Fragment, ...]:
    face = source.faces[source_face]
    source_plane = source.planes[face.plane]
    direction = -1.0 if face.side else 1.0
    face_normal = tuple(float(source_plane[axis]) * direction for axis in range(3))
    output: list[Fragment] = []
    stack = [(root, polygon)]
    while stack:
        node_index, vertices = stack.pop()
        if len(vertices) < 3:
            continue
        if node_index < 0:
            output.append(Fragment(source_face, -1 - node_index, vertices))
            continue
        node = source.nodes[node_index]
        plane = source.planes[node.plane]
        normal = tuple(float(plane[axis]) for axis in range(3))
        distance = float(plane[3])
        distances = tuple(
            sum(vertex[axis] * normal[axis] for axis in range(3)) - distance
            for vertex in vertices
        )
        minimum, maximum = min(distances), max(distances)
        if minimum >= -PLANE_EPSILON and maximum <= PLANE_EPSILON:
            dot = sum(face_normal[axis] * normal[axis] for axis in range(3))
            stack.append((node.children[0 if dot >= 0.0 else 1], vertices))
        elif minimum >= -PLANE_EPSILON:
            stack.append((node.children[0], vertices))
        elif maximum <= PLANE_EPSILON:
            stack.append((node.children[1], vertices))
        else:
            front = _clip_half(vertices, plane, True)
            back = _clip_half(vertices, plane, False)
            stack.append((node.children[1], back))
            stack.append((node.children[0], front))
    return tuple(output)


def audit_leaf_clipped_fragments(
    source: Any, replay: CanonicalBrushReplay
) -> dict[str, Any]:
    """Measure a separate fragment pool over all 149 canonical step rows."""

    root = int(source.models[0][9])
    cache: dict[
        tuple[int, tuple[int, int, int]],
        tuple[Fragment, ...],
    ] = {}
    fields = (
        "activeModels",
        "sourceFaces",
        "sourceIndices",
        "uniqueSourceVertices",
        "fragments",
        "fragmentVertexReferences",
        "uniqueFragmentVerticesQ8",
        "fragmentPolygonIndices",
        "fragmentTriangleIndices",
        "maximumFragmentsInOneLeaf",
        "maximumSourceFaceExpansion",
        "sameLeafFragmentPairs",
    )
    maxima = {field: 0 for field in fields}
    maximum_rows = {field: 0 for field in fields}
    route_records: list[dict[str, int]] = []
    for row_index in step_row_indices(len(replay.rows)):
        row = replay.rows[row_index]
        counts = {field: 0 for field in fields}
        counts["activeModels"] = len(row.brushes)
        source_vertices: set[int] = set()
        fragment_vertices: set[tuple[int, int, int]] = set()
        leaf_fragments: dict[int, int] = {}
        for state in row.brushes:
            model = source.models[state.inline_model]
            first_face = int(model[14])
            for source_face in range(first_face, first_face + int(model[15])):
                face = source.faces[source_face]
                vertex_ids = _face_vertex_ids(source, face)
                source_vertices.update(vertex_ids)
                counts["sourceFaces"] += 1
                counts["sourceIndices"] += len(vertex_ids)
                origin_q3 = tuple(_q3(value) for value in state.origin)
                key = (source_face, origin_q3)
                fragments = cache.get(key)
                if fragments is None:
                    origin = tuple(value / 8.0 for value in origin_q3)
                    polygon = tuple(
                        tuple(
                            source.vertices[vertex][axis] + origin[axis]
                            for axis in range(3)
                        )
                        for vertex in vertex_ids
                    )
                    fragments = _clip_face_to_world(source, root, source_face, polygon)
                    cache[key] = fragments
                counts["fragments"] += len(fragments)
                counts["maximumSourceFaceExpansion"] = max(
                    counts["maximumSourceFaceExpansion"], len(fragments)
                )
                for fragment in fragments:
                    leaf, polygon = fragment.leaf, fragment.polygon
                    leaf_fragments[leaf] = leaf_fragments.get(leaf, 0) + 1
                    counts["fragmentVertexReferences"] += len(polygon)
                    counts["fragmentPolygonIndices"] += len(polygon)
                    counts["fragmentTriangleIndices"] += (len(polygon) - 2) * 3
                    fragment_vertices.update(
                        tuple(round(value * 256.0) for value in vertex)
                        for vertex in polygon
                    )
        counts["uniqueSourceVertices"] = len(source_vertices)
        counts["uniqueFragmentVerticesQ8"] = len(fragment_vertices)
        counts["maximumFragmentsInOneLeaf"] = max(leaf_fragments.values(), default=0)
        counts["sameLeafFragmentPairs"] = sum(
            count * (count - 1) // 2 for count in leaf_fragments.values()
        )
        for field, value in counts.items():
            if value > maxima[field]:
                maxima[field] = value
                maximum_rows[field] = row_index
        route_records.append({"row": row_index, **counts})
    route_bytes = json.dumps(
        route_records, sort_keys=True, separators=(",", ":")
    ).encode("ascii")
    fragment_pool_bytes = (
        maxima["uniqueFragmentVerticesQ8"] * 6
        + maxima["fragmentPolygonIndices"] * 2
        + maxima["fragments"] * 17
    )
    return {
        "design": (
            "clip translated source polygons through the world BSP, retain "
            "solid and empty leaf keys for world/brush composition"
        ),
        "stepRowCount": len(route_records),
        "stepRowsFormula": "row = n * 15",
        "clipEpsilon": PLANE_EPSILON,
        "intersectionAuditQuantization": "signed Q8",
        "maxima": maxima,
        "maximumRows": maximum_rows,
        "routeAuditSha256": hashlib.sha256(route_bytes).hexdigest(),
        "cachedSourceFacePoseCount": len(cache),
        "separateFragmentPoolBytes": fragment_pool_bytes,
        "existingPacketCapacities": {
            "vertices": 768,
            "indices": 2048,
            "faces": 341,
        },
    }


def _axis_code(values: tuple[object, ...], source_face: int, label: str) -> int:
    components = tuple(float(value) for value in values)
    nonzero = [(axis, value) for axis, value in enumerate(components) if value != 0.0]
    if len(nonzero) != 1 or abs(nonzero[0][1]) != 1.0:
        raise ValueError(
            f"brush face {source_face} {label} texture axis is not signed unit"
        )
    axis, value = nonzero[0]
    return (axis + 1) * (1 if value > 0.0 else -1)


def _runtime_axis_coordinate_q4(
    source_face: int,
    axis_label: str,
    vertex_q2: tuple[int, int, int],
    axis_code: int,
    offset: int,
    origin_q3: tuple[int, int, int],
    world_origin_q0: tuple[int, int, int],
) -> int:
    axis = abs(axis_code) - 1
    coordinate = (
        vertex_q2[axis] * 64
        + world_origin_q0[axis] * 16
        - origin_q3[axis] * 2
    )
    if axis_code < 0:
        coordinate = -coordinate
    coordinate += offset * 16
    if not -0x8000 <= coordinate <= 0x7FFF:
        raise ValueError(
            f"brush face {source_face} {axis_label} runtime texture coordinate "
            f"{coordinate} exceeds signed Q4"
        )
    return coordinate


def _runtime_fragment_axis_span_q4(
    source_face: int, axis_label: str, coordinates: list[int]
) -> int:
    span = max(coordinates) - min(coordinates)
    if span >= SIGNED_Q4_AXIS_SPAN_LIMIT:
        raise ValueError(
            f"brush face {source_face} {axis_label} runtime texture-coordinate "
            f"span {span} exceeds signed Q4 no-wrap bound"
        )
    return span


def _q2_vertex(
    vertex: tuple[float, float, float],
    world_origin: tuple[float, float, float],
) -> tuple[int, int, int]:
    return tuple(
        math.floor(
            (vertex[axis] - world_origin[axis]) * 4.0 / bsp_tools.WORLD_SCALE + 0.5
        )
        for axis in range(3)
    )


def _variant_sources(
    replay: CanonicalBrushReplay,
) -> dict[tuple[int, int, int, int], int]:
    variants: dict[tuple[int, int, int, int], int] = {}
    for state in replay.signon_brushes:
        key = (state.inline_model, *(_q3(value) for value in state.origin))
        variants[key] = variants.get(key, 0) | 1
    for row in replay.rows:
        for state in row.brushes:
            key = (state.inline_model, *(_q3(value) for value in state.origin))
            variants[key] = variants.get(key, 0) | 2
    return variants


def fragment_variant_ids(
    replay: CanonicalBrushReplay,
) -> dict[tuple[int, int, int, int], int]:
    """Return the exact QBSF directory index for each geometry pose."""

    return {key: index for index, key in enumerate(sorted(_variant_sources(replay)))}


def _face_material_directory(
    source: Any,
    source_face_ids: tuple[int, ...],
    source_to_packed: dict[int, int],
) -> tuple[bytes, dict[int, int], dict[int, tuple[int, int, int, int]]]:
    output = bytearray()
    packed_by_source = {
        source_face: packed for packed, source_face in enumerate(source_face_ids)
    }
    model_and_local: dict[int, tuple[int, int]] = {}
    runtime_material_by_source: dict[int, tuple[int, int, int, int]] = {}
    for inline_model, model in enumerate(source.models[1:], start=1):
        first = int(model[14])
        for local_face, source_face in enumerate(range(first, first + int(model[15]))):
            model_and_local[source_face] = (inline_model, local_face)
    for packed_face, source_face in enumerate(source_face_ids):
        face = source.faces[source_face]
        info = source.texinfo[face.texinfo]
        source_texture = int(info[8])
        inline_model, local_face = model_and_local[source_face]
        s_offset, t_offset = round(float(info[3])), round(float(info[7]))
        if (
            float(info[3]) != s_offset
            or float(info[7]) != t_offset
            or not -0x8000 <= s_offset <= 0x7FFF
            or not -0x8000 <= t_offset <= 0x7FFF
        ):
            raise ValueError(
                f"brush face {source_face} affine texture offset exceeds int16"
            )
        if local_face > 0xFF:
            raise ValueError(f"brush model *{inline_model} local face exceeds uint8")
        s_axis = _axis_code(tuple(info[:3]), source_face, "S")
        t_axis = _axis_code(tuple(info[4:7]), source_face, "T")
        runtime_material_by_source[source_face] = (
            s_axis,
            t_axis,
            s_offset,
            t_offset,
        )
        output.extend(
            FACE_MATERIAL_RECORD.pack(
                source_face,
                face.texinfo,
                packed_face,
                source_to_packed[source_texture],
                s_axis,
                t_axis,
                s_offset,
                t_offset,
                inline_model,
                local_face,
                face.side & 1,
            )
        )
    return bytes(output), packed_by_source, runtime_material_by_source


def _fragment_banks(
    control: bytes,
    descriptors: bytes,
    vertices: bytes,
) -> tuple[tuple[bytes, ...], int, int]:
    descriptor_banks = max(1, (len(descriptors) + ROM_BANK_BYTES - 1) // ROM_BANK_BYTES)
    vertex_banks = max(1, (len(vertices) + ROM_BANK_BYTES - 1) // ROM_BANK_BYTES)
    chunks = [control.ljust(ROM_BANK_BYTES, b"\xff")]
    chunks.extend(
        descriptors[offset : offset + ROM_BANK_BYTES].ljust(ROM_BANK_BYTES, b"\xff")
        for offset in range(0, descriptor_banks * ROM_BANK_BYTES, ROM_BANK_BYTES)
    )
    chunks.extend(
        vertices[offset : offset + ROM_BANK_BYTES].ljust(ROM_BANK_BYTES, b"\xff")
        for offset in range(0, vertex_banks * ROM_BANK_BYTES, ROM_BANK_BYTES)
    )
    return tuple(chunks), descriptor_banks, vertex_banks


def build_fragment_assets(
    source: Any,
    replay: CanonicalBrushReplay,
    source_to_packed: dict[int, int],
    source_face_ids: tuple[int, ...],
    *,
    first_bank: int,
    maximum_bank_count: int,
) -> FragmentAssetBuild:
    """Pack the selected camera-independent sparse-leaf fragment design."""

    root = int(source.models[0][9])
    leaf_parents = _world_leaf_parents(source, root)
    leaf_head_count = int(source.models[0][13]) + 1
    reachable_leaves = {
        leaf for leaf, parent in enumerate(leaf_parents) if parent != 0xFFFF
    }
    if reachable_leaves != set(range(leaf_head_count)):
        raise ValueError("world render hull is not the contiguous VIS-leaf domain")
    world = source.models[0]
    world_origin = tuple(
        (float(world[axis]) + float(world[axis + 3])) * 0.5 for axis in range(3)
    )
    world_origin_q0 = tuple(round(value) for value in world_origin)
    (
        face_directory,
        packed_face_by_source,
        runtime_material_by_source,
    ) = _face_material_directory(source, source_face_ids, source_to_packed)
    variants = _variant_sources(replay)
    variant_ids = fragment_variant_ids(replay)
    variant_directory = bytearray()
    buckets = bytearray()
    descriptors = bytearray()
    vertices = bytearray()
    variant_metadata: list[dict[str, Any]] = []
    variant_leaf_groups: list[dict[int, tuple[int, int]]] = []
    maximum_bucket_leaf = 0
    solid_bucket_count = 0
    non_solid_bucket_total = 0
    maximum_lightmapped_texcoord_span: dict[str, Any] | None = None
    for inline_model, x_q3, y_q3, z_q3 in variant_ids:
        flags = variants[(inline_model, x_q3, y_q3, z_q3)]
        origin = (x_q3 / 8.0, y_q3 / 8.0, z_q3 / 8.0)
        model = source.models[inline_model]
        fragments: list[Fragment] = []
        for source_face in range(int(model[14]), int(model[14]) + int(model[15])):
            polygon = tuple(
                tuple(source.vertices[vertex][axis] + origin[axis] for axis in range(3))
                for vertex in _face_vertex_ids(source, source.faces[source_face])
            )
            fragments.extend(_clip_face_to_world(source, root, source_face, polygon))
        fragments.sort(key=lambda item: (item.leaf, -item.source_face))
        first_bucket = len(buckets) // BUCKET_RECORD.size
        bucket_count = 0
        cursor = 0
        solid_fragments = 0
        non_solid_bucket_count = 0
        non_solid_groups: dict[int, tuple[int, int]] = {}
        bounds_min_q2 = [0x7FFF, 0x7FFF, 0x7FFF]
        bounds_max_q2 = [-0x8000, -0x8000, -0x8000]
        while cursor < len(fragments):
            leaf = fragments[cursor].leaf
            group_end = cursor + 1
            while group_end < len(fragments) and fragments[group_end].leaf == leaf:
                group_end += 1
            count = group_end - cursor
            if count > 0xFF:
                raise ValueError(
                    f"brush variant *{inline_model} {origin} leaf {leaf} "
                    f"needs {count} fragments; uint8 bound is 255"
                )
            first_fragment = len(descriptors) // FRAGMENT_RECORD.size
            if first_fragment > 0xFFFF:
                raise ValueError(
                    "brush fragment count exceeds uint16 sparse-bucket indexing"
                )
            solid = source.leaves[leaf].contents == -2
            maximum_bucket_leaf = max(maximum_bucket_leaf, leaf)
            if solid:
                if leaf != 0:
                    raise ValueError(f"solid brush bucket uses nonzero leaf {leaf}")
                solid_bucket_count += 1
            else:
                if not 0 < leaf < leaf_head_count:
                    raise ValueError(
                        f"non-solid brush bucket leaf {leaf} escapes VIS domain"
                    )
                non_solid_bucket_total += 1
            parent = leaf_parents[leaf]
            if not solid and parent == 0xFFFF:
                raise ValueError(f"non-solid brush leaf {leaf} has no world parent")
            buckets.extend(
                BUCKET_RECORD.pack(
                    leaf, first_fragment, count, int(solid), parent
                )
            )
            bucket_count += 1
            non_solid_bucket_count += int(not solid)
            if not solid:
                non_solid_groups[leaf] = (
                    count,
                    sum(
                        len(fragment.polygon)
                        for fragment in fragments[cursor:group_end]
                    ),
                )
            for fragment in fragments[cursor:group_end]:
                first_vertex = len(vertices) // VERTEX_RECORD_BYTES
                fragment_index = len(descriptors) // FRAGMENT_RECORD.size
                if len(fragment.polygon) > 0xFF:
                    raise ValueError(
                        f"brush fragment face {fragment.source_face} "
                        "exceeds uint8 vertex count"
                    )
                descriptors.extend(
                    FRAGMENT_RECORD.pack(
                        packed_face_by_source[fragment.source_face],
                        first_vertex,
                        len(fragment.polygon),
                        int(solid),
                    )
                )
                s_axis, t_axis, s_offset, t_offset = runtime_material_by_source[
                    fragment.source_face
                ]
                lightmapped = source.faces[fragment.source_face].light_offset != -1
                coordinates_q4: tuple[list[int], list[int]] = ([], [])
                for vertex in fragment.polygon:
                    vertex_q2 = _q2_vertex(vertex, world_origin)
                    if not solid:
                        for axis, coordinate in enumerate(vertex_q2):
                            bounds_min_q2[axis] = min(
                                bounds_min_q2[axis], coordinate
                            )
                            bounds_max_q2[axis] = max(
                                bounds_max_q2[axis], coordinate
                            )
                    if lightmapped:
                        for axis_index, (axis_label, axis_code, offset) in enumerate(
                            (("S", s_axis, s_offset), ("T", t_axis, t_offset))
                        ):
                            coordinates_q4[axis_index].append(
                                _runtime_axis_coordinate_q4(
                                    fragment.source_face,
                                    axis_label,
                                    vertex_q2,
                                    axis_code,
                                    offset,
                                    (x_q3, y_q3, z_q3),
                                    world_origin_q0,
                                )
                            )
                    vertices.extend(bsp_tools.pack_q2_world_vertex(vertex_q2))
                if lightmapped:
                    for axis_label, axis_coordinates in zip("ST", coordinates_q4):
                        span = _runtime_fragment_axis_span_q4(
                            fragment.source_face, axis_label, axis_coordinates
                        )
                        if (
                            maximum_lightmapped_texcoord_span is None
                            or span > maximum_lightmapped_texcoord_span["maximum"]
                        ):
                            maximum_lightmapped_texcoord_span = {
                                "maximum": span,
                                "sourceFace": fragment.source_face,
                                "axis": axis_label,
                                "inlineModel": inline_model,
                                "originQ3": [x_q3, y_q3, z_q3],
                                "fragment": fragment_index,
                            }
            solid_fragments += count if solid else 0
            cursor = group_end
        if first_bucket > 0xFFFF or bucket_count > 0xFFFF:
            raise ValueError(
                f"brush variant *{inline_model} sparse bucket range exceeds uint16"
            )
        if non_solid_bucket_count:
            bounds_center_q2 = [
                (minimum + maximum) // 2
                for minimum, maximum in zip(bounds_min_q2, bounds_max_q2)
            ]
            bounds_extent_q2 = [
                max(center - minimum, maximum - center)
                for minimum, maximum, center in zip(
                    bounds_min_q2, bounds_max_q2, bounds_center_q2
                )
            ]
        else:
            bounds_min_q2 = [0, 0, 0]
            bounds_max_q2 = [0, 0, 0]
            bounds_center_q2 = [0, 0, 0]
            bounds_extent_q2 = [0, 0, 0]
        variant_directory.extend(
            VARIANT_RECORD.pack(
                inline_model,
                flags,
                x_q3,
                y_q3,
                z_q3,
                first_bucket,
                bucket_count,
                *bounds_center_q2,
                *bounds_extent_q2,
            )
        )
        variant_metadata.append(
            {
                "inlineModel": inline_model,
                "originQ3": [x_q3, y_q3, z_q3],
                "signonBaseline": bool(flags & 1),
                "usedByReplay": bool(flags & 2),
                "firstBucket": first_bucket,
                "bucketCount": bucket_count,
                "nonSolidBucketCount": non_solid_bucket_count,
                "fragmentCount": len(fragments),
                "solidFragmentCount": solid_fragments,
                "boundsMinQ2": bounds_min_q2,
                "boundsMaxQ2": bounds_max_q2,
                "boundsCenterQ2": bounds_center_q2,
                "boundsExtentQ2": bounds_extent_q2,
            }
        )
        variant_leaf_groups.append(non_solid_groups)
    if maximum_lightmapped_texcoord_span is None:
        raise ValueError("brush fragment package contains no lightmapped face")
    variant_offset = FRAGMENT_HEADER.size
    face_offset = variant_offset + len(variant_directory)
    bucket_offset = face_offset + len(face_directory)
    control_used = bucket_offset + len(buckets)
    if control_used > ROM_BANK_BYTES:
        raise ValueError(
            f"brush fragment control asset needs {control_used} bytes; "
            f"one-bank bound is {ROM_BANK_BYTES}"
        )
    descriptor_bank_count = max(
        1, (len(descriptors) + ROM_BANK_BYTES - 1) // ROM_BANK_BYTES
    )
    vertex_bank_count = max(1, (len(vertices) + ROM_BANK_BYTES - 1) // ROM_BANK_BYTES)
    bank_count = 1 + descriptor_bank_count + vertex_bank_count
    if bank_count > maximum_bank_count:
        raise ValueError(
            f"brush fragment package needs {bank_count} banks; available "
            f"bound from bank {first_bank} is {maximum_bank_count}"
        )
    header = FRAGMENT_HEADER.pack(
        FRAGMENT_MAGIC,
        FRAGMENT_VERSION,
        bank_count,
        1,
        descriptor_bank_count,
        1 + descriptor_bank_count,
        vertex_bank_count,
        len(variant_metadata),
        len(buckets) // BUCKET_RECORD.size,
        len(descriptors) // FRAGMENT_RECORD.size,
        len(vertices) // VERTEX_RECORD_BYTES,
        len(source_face_ids),
        variant_offset,
        face_offset,
        bucket_offset,
        control_used,
    )
    control = header + bytes(variant_directory) + face_directory + bytes(buckets)
    chunks, checked_descriptor_banks, checked_vertex_banks = _fragment_banks(
        control, bytes(descriptors), bytes(vertices)
    )
    if (
        len(chunks) != bank_count
        or checked_descriptor_banks != descriptor_bank_count
        or checked_vertex_banks != vertex_bank_count
    ):
        raise AssertionError("brush fragment bank packing is inconsistent")
    if FRAGMENT_HEADER.unpack_from(chunks[0]) != FRAGMENT_HEADER.unpack(header):
        raise AssertionError("brush fragment header does not round-trip")
    outputs = {
        Path(f"QuakeBSPBrushFragments{index}.bin"): chunk
        for index, chunk in enumerate(chunks)
    }
    audit = audit_leaf_clipped_fragments(source, replay)
    metadata = {
        "magic": FRAGMENT_MAGIC.decode("ascii"),
        "version": FRAGMENT_VERSION,
        "storageContract": (
            "camera-independent (inline model,Q3 origin) variants; sparse "
            "leaf buckets with parent nodes; conservative center/extent Q2 bounds "
            "cover every non-solid fragment; contiguous Q2 xyz vertices; face "
            "directory reconstructs affine texture/lightmap coordinates"
        ),
        "firstBank": first_bank,
        "lastBank": first_bank + bank_count - 1,
        "bankCount": bank_count,
        "headerBytes": FRAGMENT_HEADER.size,
        "controlUsedBytes": control_used,
        "variantRecordBytes": VARIANT_RECORD.size,
        "bucketRecordBytes": BUCKET_RECORD.size,
        "fragmentRecordBytes": FRAGMENT_RECORD.size,
        "faceMaterialRecordBytes": FACE_MATERIAL_RECORD.size,
        "vertexRecordBytes": VERTEX_RECORD_BYTES,
        "variantCount": len(variant_metadata),
        "signonBaselineVariantCount": sum(
            item["signonBaseline"] for item in variant_metadata
        ),
        "replayVariantCount": sum(item["usedByReplay"] for item in variant_metadata),
        "signonOnlyVariantCount": sum(
            item["signonBaseline"] and not item["usedByReplay"]
            for item in variant_metadata
        ),
        "bucketCount": len(buckets) // BUCKET_RECORD.size,
        "fragmentCount": len(descriptors) // FRAGMENT_RECORD.size,
        "vertexOccurrenceCount": len(vertices) // VERTEX_RECORD_BYTES,
        "faceMaterialCount": len(source_face_ids),
        "lightmappedTexcoordAxisSpanQ4": {
            **maximum_lightmapped_texcoord_span,
            "exclusiveLimit": SIGNED_Q4_AXIS_SPAN_LIMIT,
            "coordinateContract": (
                "exact unwrapped BrushComputeAxisCoordinate result from each "
                "published Q2 occurrence, Q3 variant origin, signed unit axis, "
                "and integer offset"
            ),
        },
        "leafDomain": {
            "headCount": leaf_head_count,
            "reachableWorldLeafCount": len(reachable_leaves),
            "maximumBucketLeaf": maximum_bucket_leaf,
            "solidFallbackLeaf": 0,
            "solidBucketCount": solid_bucket_count,
            "nonSolidBucketCount": non_solid_bucket_total,
        },
        "logicalBytes": (control_used + len(descriptors) + len(vertices)),
        "bankRoles": {
            "control": {
                "bank": first_bank,
                "variantOffset": variant_offset,
                "faceMaterialOffset": face_offset,
                "bucketOffset": bucket_offset,
            },
            "descriptors": {
                "firstBank": first_bank + 1,
                "bankCount": descriptor_bank_count,
                "bytes": len(descriptors),
                "sha256": hashlib.sha256(descriptors).hexdigest(),
            },
            "vertices": {
                "firstBank": first_bank + 1 + descriptor_bank_count,
                "bankCount": vertex_bank_count,
                "bytes": len(vertices),
                "sha256": hashlib.sha256(vertices).hexdigest(),
                "encoding": (
                    "signed int8 bases plus packed two-bit XYZ residuals, "
                    "Q2 after WORLD_SCALE"
                ),
            },
        },
        "directoryHashes": {
            "variants": hashlib.sha256(variant_directory).hexdigest(),
            "buckets": hashlib.sha256(buckets).hexdigest(),
            "faceMaterials": hashlib.sha256(face_directory).hexdigest(),
        },
        "variants": variant_metadata,
        "routeAudit": audit,
        "outputs": {
            path.as_posix(): {
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
            for path, payload in outputs.items()
        },
    }
    return FragmentAssetBuild(outputs, metadata, tuple(variant_leaf_groups))
