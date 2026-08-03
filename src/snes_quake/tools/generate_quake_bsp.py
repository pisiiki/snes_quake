#!/usr/bin/env python3
# ruff: noqa: F405
"""Pack deterministic E1M3 BSP29 geometry and demo1 camera data for SuperFX."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
import sys
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parent
SHARED_TOOLS_DIR = TOOLS_DIR.parents[1] / "shared" / "tools"
for dependency_dir in (TOOLS_DIR, SHARED_TOOLS_DIR):
    if str(dependency_dir) not in sys.path:
        sys.path.insert(0, str(dependency_dir))

from generated_outputs import GeneratedOutputError, sync_generated_outputs  # noqa: E402
from quake_demo import (  # noqa: E402
    DEFAULT_VIEWHEIGHT,
    extract_camera_samples,
    sample_newest_due_indices,
)

# Keep this module as the stable CLI and import facade for existing consumers.
from quake_bsp_assets import *  # noqa: E402,F401,F403


def generate(pak_path: Path) -> tuple[dict[Path, bytes], dict[str, object]]:
    pak_bytes = pak_path.read_bytes()
    archive = PakArchive(pak_path)
    bsp = archive.read(BSP_ENTRY)
    demo = archive.read(DEMO_ENTRY)
    palette_bytes = archive.read(PALETTE_ENTRY)
    colormap_bytes = archive.read(COLORMAP_ENTRY)
    if len(palette_bytes) != 768:
        raise ValueError("Quake palette must contain 768 bytes")
    (
        texture_depth_lut,
        texture_depth_colormap,
        lightmap_colormap_map,
    ) = texture_shading_assets(colormap_bytes)
    lightmap_level_zero = lightmap_level_zero_colormap(colormap_bytes)
    lightmap_colormap = lightmap_natural_colormap(colormap_bytes)
    lumps = lump_ranges(bsp)

    entities = parse_entities(lump_data(bsp, lumps, LUMP_ENTITIES))
    start, start_angle = player_start(entities)
    planes = unpack_records(lump_data(bsp, lumps, LUMP_PLANES), "<ffffi")
    vertices = [
        tuple(record)
        for record in unpack_records(lump_data(bsp, lumps, LUMP_VERTICES), "<fff")
    ]
    node_records = unpack_records(lump_data(bsp, lumps, LUMP_NODES), "<ihh6hHH")
    nodes = [
        Node(record[0], (record[1], record[2]), record[9], record[10])
        for record in node_records
    ]
    texinfo = unpack_records(lump_data(bsp, lumps, LUMP_TEXINFO), "<8fii")
    face_records = unpack_records(lump_data(bsp, lumps, LUMP_FACES), "<hhihh4Bi")
    faces = [
        Face(
            record[0],
            record[1],
            record[2],
            record[3],
            record[4],
            (record[5], record[6], record[7], record[8]),
            record[9],
        )
        for record in face_records
    ]
    leaf_records = unpack_records(lump_data(bsp, lumps, LUMP_LEAVES), "<ii6hHH4B")
    leaves = [
        Leaf(record[0], record[1], record[8], record[9]) for record in leaf_records
    ]
    marksurfaces = [
        record[0]
        for record in unpack_records(lump_data(bsp, lumps, LUMP_MARKSURFACES), "<H")
    ]
    edges = [
        (record[0], record[1])
        for record in unpack_records(lump_data(bsp, lumps, LUMP_EDGES), "<HH")
    ]
    surfedges = [
        record[0]
        for record in unpack_records(lump_data(bsp, lumps, LUMP_SURFEDGES), "<i")
    ]
    models = unpack_records(lump_data(bsp, lumps, LUMP_MODELS), "<9f7i")
    textures = parse_textures(lump_data(bsp, lumps, LUMP_TEXTURES))
    visibility = lump_data(bsp, lumps, LUMP_VISIBILITY)
    lighting = lump_data(bsp, lumps, LUMP_LIGHTING)

    def polygon_for_face(face: Face) -> list[tuple[float, float, float]]:
        polygon: list[tuple[float, float, float]] = []
        for index in range(face.first_edge, face.first_edge + face.edge_count):
            surfedge = surfedges[index]
            edge = edges[abs(surfedge)]
            vertex_index = edge[0] if surfedge >= 0 else edge[1]
            polygon.append(vertices[vertex_index])
        return polygon

    def texture_for_face(face: Face) -> str | None:
        texture_index = int(texinfo[face.texinfo][8])
        texture = textures[texture_index]
        if not texture.pixels:
            return None
        return texture.name

    def material_record_for_face(
        face: Face, polygon: list[tuple[float, float, float]]
    ) -> tuple[int, int, int, int]:
        if not polygon:
            raise ValueError("cannot color an empty face polygon")
        plane = planes[face.plane]
        direction = -1.0 if face.side else 1.0
        normal = tuple(float(plane[axis]) * direction for axis in range(3))
        centroid = tuple(
            sum(vertex[axis] for vertex in polygon) / len(polygon) for axis in range(3)
        )
        packed_centroid = tuple(
            (
                round_half_up((centroid[axis] - world_origin[axis]) / WORLD_SCALE)
                if centroid[axis] >= world_origin[axis]
                else -round_half_up((world_origin[axis] - centroid[axis]) / WORLD_SCALE)
            )
            for axis in range(3)
        )
        if any(
            value < WORLD_COORD_MIN or value > WORLD_COORD_MAX
            for value in packed_centroid
        ):
            raise AssertionError(
                f"face centroid exceeds signed-byte storage: {packed_centroid}"
            )
        texture_id = int(texinfo[face.texinfo][8])
        family = (
            texture_families[texture_id]
            if 0 <= texture_id < len(texture_families)
            else 0
        )
        base_shade = family * APPARENT_LIGHT_LEVELS + orientation_light_level(normal)
        return (*packed_centroid, base_shade)

    def colors_for_face(
        face: Face, polygon: list[tuple[float, float, float]]
    ) -> tuple[int, int]:
        plane = planes[face.plane]
        direction = -1.0 if face.side else 1.0
        normal = tuple(float(plane[axis]) * direction for axis in range(3))
        centroid = tuple(
            sum(vertex[axis] for vertex in polygon) / len(polygon) for axis in range(3)
        )
        return lit_face_colors(normal, centroid, world_mins, world_maxs)

    world_model = models[0]
    world_first_face = int(world_model[14])
    world_face_count = int(world_model[15])
    if world_first_face != 0:
        raise AssertionError("the world-model face stream must start at face zero")
    (
        world_lightmap_directory,
        world_lightmap_chunks,
        world_lightmap_records,
    ) = pack_world_lightmaps(
        faces[world_first_face : world_first_face + world_face_count],
        vertices,
        edges,
        surfedges,
        texinfo,
        textures,
        lighting,
    )
    if len(world_lightmap_chunks) != 5:
        raise AssertionError("E1M3 combined lightmaps must occupy five ROM banks")
    world_mins = tuple(float(world_model[axis]) for axis in range(3))
    world_maxs = tuple(float(world_model[axis + 3]) for axis in range(3))
    world_origin = tuple(
        (world_mins[axis] + world_maxs[axis]) * 0.5 for axis in range(3)
    )
    source_palette = quake_palette(palette_bytes)
    family_hues, texture_families, material_palette = build_material_palette(
        textures, source_palette, texinfo, faces
    )
    start_coordinate = quantize_world_vertex(start, world_origin)
    root = int(world_model[9])
    vis_leaf_count = int(world_model[13])
    spawn_leaf = locate_leaf(start, nodes, planes, root)
    pvs = decompress_pvs(visibility, leaves[spawn_leaf].vis_offset, vis_leaf_count)
    visible_leaves = {spawn_leaf}
    for bit in range(vis_leaf_count):
        if pvs[bit >> 3] & (1 << (bit & 7)):
            visible_leaves.add(bit + 1)
    pvs_faces: set[int] = set()
    for leaf_index in visible_leaves:
        leaf = leaves[leaf_index]
        begin = leaf.first_mark_surface
        pvs_faces.update(marksurfaces[begin : begin + leaf.mark_surface_count])

    source_polygons: dict[int, list[tuple[float, float, float]]] = {}
    source_face_colors: dict[int, tuple[int, int]] = {}
    texture_names: set[str] = set()
    for face_index in sorted(pvs_faces):
        face = faces[face_index]
        source_polygon = polygon_for_face(face)
        polygon = clip_to_budget(source_polygon, start)
        if len(polygon) < 3 or polygon_area(polygon) < 1.0:
            continue
        texture_name = texture_for_face(face)
        if texture_name is None:
            continue
        texture_names.add(texture_name)
        source_polygons[face_index] = polygon
        source_face_colors[face_index] = colors_for_face(face, source_polygon)

    if not source_polygons:
        raise ValueError("the clipped spawn PVS contains no drawable faces")
    order = bsp_draw_order(nodes, planes, start, set(source_polygons), root)

    packed_vertices: list[tuple[int, int, int]] = []
    vertex_lookup: dict[tuple[int, int, int], int] = {}
    packed_indices: list[int] = []
    packed_faces = bytearray()
    packed_face_planes = bytearray()
    spawn_front_faces = 0
    winding_validation_triangles = 0
    winding_ambiguous_triangles = 0
    winding_mismatched_triangles = 0
    for face_index in order:
        polygon = source_polygons[face_index]
        quantized: list[tuple[int, int, int]] = []
        for vertex in polygon:
            value = quantize_vertex(vertex, start)
            if not quantized or value != quantized[-1]:
                quantized.append(value)
        if len(quantized) > 1 and quantized[0] == quantized[-1]:
            quantized.pop()
        if len(quantized) < 3 or len(quantized) > 255:
            continue
        first_index = len(packed_indices)
        for value in quantized:
            vertex_index = vertex_lookup.get(value)
            if vertex_index is None:
                vertex_index = len(packed_vertices)
                if vertex_index > 0xFFFF:
                    raise ValueError("packed vertex index exceeds 16 bits")
                vertex_lookup[value] = vertex_index
                packed_vertices.append(value)
            packed_indices.append(vertex_index)
        flat, dither = source_face_colors[face_index]
        packed_faces.extend(
            struct.pack("<HBBBB", first_index, len(quantized), flat, dither, 0)
        )
        normal, distance = quantized_face_plane(quantized)
        packed_face_planes.extend(struct.pack("<bbbh", *normal, distance))

        # Quake world polygons point toward solid space; an interior camera at
        # the centered origin sees the negative side of the oriented plane.
        spawn_facing = -distance < 0
        spawn_front_faces += int(spawn_facing)
        for index in range(1, len(quantized) - 1):
            triangle = (quantized[0], quantized[index], quantized[index + 1])
            edge_a = tuple(triangle[1][axis] - triangle[0][axis] for axis in range(3))
            edge_b = tuple(triangle[2][axis] - triangle[0][axis] for axis in range(3))
            triangle_normal = (
                edge_a[1] * edge_b[2] - edge_a[2] * edge_b[1],
                edge_a[2] * edge_b[0] - edge_a[0] * edge_b[2],
                edge_a[0] * edge_b[1] - edge_a[1] * edge_b[0],
            )
            if not any(triangle_normal):
                winding_ambiguous_triangles += 1
                continue
            projected = tuple(spawn_project(vertex) for vertex in triangle)
            if any(vertex is None for vertex in projected):
                continue
            a, b, c = projected
            assert a is not None and b is not None and c is not None
            winding = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
            if abs(winding) <= 4:
                winding_ambiguous_triangles += 1
                continue
            winding_validation_triangles += 1
            if (winding < 0) != spawn_facing:
                # Coarse int8 world quantization can collapse a thin face or
                # move one projected vertex across an edge. The compact spawn
                # scene is retained only as generation evidence; runtime uses
                # the complete BSP packet and its source face identity.
                winding_mismatched_triangles += 1

    # Preserve the complete world model in source face order for runtime BSP
    # traversal. The bounded arrays above remain the currently rendered fast
    # path; these banked assets are the full-map working foundation.
    world_vertex_mins = tuple(
        min(float(vertex[axis]) for vertex in vertices) for axis in range(3)
    )
    world_vertex_maxs = tuple(
        max(float(vertex[axis]) for vertex in vertices) for axis in range(3)
    )
    world_quantized_vertices = [
        quantize_world_vertex(vertex, world_origin) for vertex in vertices
    ]
    world_q2_vertices = [
        tuple(
            int(
                math.floor(
                    (float(vertex[axis]) - world_origin[axis]) * 4.0 / WORLD_SCALE + 0.5
                )
            )
            for axis in range(3)
        )
        for vertex in vertices
    ]
    if any(
        coordinate < -0x8000 or coordinate > 0x7FFF
        for vertex in world_q2_vertices
        for coordinate in vertex
    ):
        raise AssertionError("Q2 world vertex exceeds signed-word storage")
    world_coordinate_min = tuple(
        min(vertex[axis] for vertex in world_quantized_vertices) for axis in range(3)
    )
    world_coordinate_max = tuple(
        max(vertex[axis] for vertex in world_quantized_vertices) for axis in range(3)
    )

    forced_track, demo_samples = extract_camera_samples(demo, BSP_ENTRY)
    demo_records: list[tuple[int, int, int, int, int]] = []
    demo_source_records: list[int] = []
    demo_source_times: list[float] = []
    demo_view_heights: list[int] = []
    demo_leaf_ids: set[int] = set()
    for sample in demo_samples:
        coordinate = quantize_world_vertex(sample.origin, world_origin)
        leaf = locate_leaf(sample.origin, nodes, planes, root)
        if leaves[leaf].contents == -2:
            raise AssertionError(
                f"demo record {sample.record} resolves to E1M3's solid leaf"
            )
        yaw = round((sample.view_angles[1] % 360.0) * 32.0 / 360.0) & 31
        # Quake's positive pitch looks down; this renderer's positive pitch
        # rotates the view direction up.
        pitch = round(-sample.view_angles[0] * 32.0 / 360.0)
        pitch = ((pitch + 16) & 31) - 16
        record = (*coordinate, yaw, pitch)
        demo_records.append(record)
        demo_source_records.append(sample.record)
        demo_source_times.append(sample.server_time)
        demo_view_heights.append(sample.view_height)
        demo_leaf_ids.add(leaf)
    if len(demo_records) < 2:
        raise AssertionError("demo1 did not produce a changing E1M3 camera track")
    demo_track = b"".join(struct.pack("<bbbBb", *record) for record in demo_records)
    if len(demo_track) != len(demo_records) * DEMO_TRACK_RECORD_BYTES:
        raise AssertionError("demo track record packing is inconsistent")
    first_demo_time = demo_source_times[0]
    demo_ticks = [
        round((server_time - first_demo_time) * NTSC_FRAMES_PER_SECOND)
        for server_time in demo_source_times
    ]
    if demo_ticks[0] != 0 or any(
        right < left for left, right in zip(demo_ticks, demo_ticks[1:])
    ):
        raise AssertionError("demo timing is not monotonic")
    if demo_ticks[-1] > 0xFFFF:
        raise AssertionError("demo timing exceeds uint16 NTSC ticks")
    demo_timing = b"".join(struct.pack("<H", tick) for tick in demo_ticks)
    if len(demo_timing) != len(demo_records) * DEMO_TIMING_RECORD_BYTES:
        raise AssertionError("demo timing record packing is inconsistent")
    if any(sample.view_angles[2] != 0.0 for sample in demo_samples):
        raise AssertionError("precise demo track cannot omit nonzero roll")
    precise_source_indices = sample_newest_due_indices(
        demo_source_times, DEMO_PRECISE_SAMPLE_RATE_HZ
    )
    if not precise_source_indices or min(precise_source_indices) < 0:
        raise AssertionError("precise demo stream begins before its source track")
    demo_precise_records: list[tuple[int, int, int, int, int]] = []
    for source_index in precise_source_indices:
        sample = demo_samples[source_index]
        position_q3 = tuple(round(value * 8.0) for value in sample.origin)
        if any(value < -0x8000 or value > 0x7FFF for value in position_q3):
            raise AssertionError(
                "precise demo Q3 position exceeds signed 16-bit storage"
            )
        yaw_u16 = round((sample.view_angles[1] % 360.0) * 65536.0 / 360.0) & 0xFFFF
        pitch_u16 = round((sample.view_angles[0] % 360.0) * 65536.0 / 360.0) & 0xFFFF
        demo_precise_records.append((*position_q3, yaw_u16, pitch_u16))
    demo_precise_track = b"".join(
        struct.pack("<hhhHH", *record) for record in demo_precise_records
    )
    if (
        len(demo_precise_track)
        != len(demo_precise_records) * DEMO_PRECISE_TRACK_RECORD_BYTES
    ):
        raise AssertionError("precise demo track record packing is inconsistent")
    if DEMO_PRECISE_SAMPLE_RATE_HZ % DEMO_STEP_SAMPLE_RATE_HZ:
        raise AssertionError("step sample rate must divide the canonical rate")
    demo_precise_ticks = [
        round(step * NTSC_FRAMES_PER_SECOND / DEMO_PRECISE_SAMPLE_RATE_HZ)
        for step in range(len(demo_precise_records))
    ]
    if demo_precise_ticks[0] != 0 or any(
        right < left for left, right in zip(demo_precise_ticks, demo_precise_ticks[1:])
    ):
        raise AssertionError("precise demo timing is not monotonic")
    if demo_precise_ticks[-1] > 0xFFFF:
        raise AssertionError("precise demo timing exceeds uint16 NTSC ticks")
    demo_precise_timing = b"".join(
        struct.pack("<H", tick) for tick in demo_precise_ticks
    )
    if len(demo_precise_timing) != len(demo_precise_records) * DEMO_TIMING_RECORD_BYTES:
        raise AssertionError("precise demo timing record packing is inconsistent")
    demo_step_indices = tuple(range(0, len(demo_precise_records), DEMO_STEP_STRIDE))
    if not demo_step_indices:
        raise AssertionError("precise demo stream has no 2 Hz step poses")
    try:
        demo_verify_near_pose = precise_source_indices.index(20)
        demo_verify_far_pose = precise_source_indices.index(456)
    except ValueError as error:
        raise AssertionError(
            "static verifier source poses are absent from the precise stream"
        ) from error

    referenced_texture_ids = sorted(
        {
            int(texinfo[face.texinfo][8])
            for face in faces[world_first_face : world_first_face + world_face_count]
            if 0 <= int(texinfo[face.texinfo][8]) < len(textures)
            and textures[int(texinfo[face.texinfo][8])].pixels
        }
    )
    packed_texture_ids = {
        source_id: packed_id
        for packed_id, source_id in enumerate(referenced_texture_ids)
    }
    if len(referenced_texture_ids) > 255:
        raise AssertionError("exact texture working set exceeds byte IDs")

    world_indices: list[int] = []
    world_texture_coordinates = bytearray()
    world_face_texture_ids = bytearray()
    world_faces = bytearray()
    world_face_planes = bytearray()
    world_shading_records = bytearray()
    world_drawable_faces = 0
    world_max_face_vertices = 0
    world_flat_color_counts = [0] * (DRAWABLE_COLOR_COUNT + 1)
    world_checker_color_counts: dict[str, int] = {}
    world_material_family_counts = [0] * TEXTURE_FAMILY_COUNT
    world_texture_names: set[str] = set()
    world_pvs_quantization_guard_faces: set[int] = set()
    for face_index in range(world_first_face, world_first_face + world_face_count):
        face = faces[face_index]
        source_indices: list[int] = []
        for edge_index in range(face.first_edge, face.first_edge + face.edge_count):
            surfedge = surfedges[edge_index]
            edge = edges[abs(surfedge)]
            vertex_index = edge[0] if surfedge >= 0 else edge[1]
            source_indices.append(vertex_index)

        first_index = len(world_indices)
        if first_index > 0xFFFF or first_index + len(source_indices) > 0x10000:
            raise AssertionError("full-world index stream exceeds uint16 addressing")
        # Retain one index for every source surfedge, including faces that
        # collapse after Q2 quantization. Face records can therefore preserve
        # their original BSP-order offsets while count=0 rejects nondrawables.
        world_indices.extend(source_indices)
        texture_record = texinfo[face.texinfo]
        source_texture_id = int(texture_record[8])
        world_face_texture_ids.append(packed_texture_ids.get(source_texture_id, 0xFF))
        for vertex_index in source_indices:
            vertex = vertices[vertex_index]
            s = sum(
                float(texture_record[axis]) * vertex[axis] for axis in range(3)
            ) + float(texture_record[3])
            t = sum(
                float(texture_record[axis + 4]) * vertex[axis] for axis in range(3)
            ) + float(texture_record[7])
            s_q4 = round_half_away_from_zero(s * 16.0)
            t_q4 = round_half_away_from_zero(t * 16.0)
            if not (-0x8000 <= s_q4 <= 0x7FFF and -0x8000 <= t_q4 <= 0x7FFF):
                raise AssertionError(
                    f"face {face_index} texture coordinate exceeds signed Q4: {(s_q4, t_q4)}"
                )
            world_texture_coordinates.extend(struct.pack("<hh", s_q4, t_q4))
        quantized: list[tuple[int, int, int]] = []
        quantized_q2: list[tuple[int, int, int]] = []
        for vertex_index in source_indices:
            value = world_quantized_vertices[vertex_index]
            if not quantized or value != quantized[-1]:
                quantized.append(value)
            value_q2 = world_q2_vertices[vertex_index]
            if not quantized_q2 or value_q2 != quantized_q2[-1]:
                quantized_q2.append(value_q2)
        if len(quantized) > 1 and quantized[0] == quantized[-1]:
            quantized.pop()
        if len(quantized_q2) > 1 and quantized_q2[0] == quantized_q2[-1]:
            quantized_q2.pop()

        source_polygon = polygon_for_face(face)
        texture_name = texture_for_face(face)
        shading_record = material_record_for_face(face, source_polygon)
        world_shading_records.extend(struct.pack("<bbbB", *shading_record))
        drawable = (
            len(quantized_q2) >= 3
            and len(source_indices) <= 255
            and polygon_area(source_polygon) >= 1.0
            and texture_name is not None
        )
        if drawable:
            assert texture_name is not None
            world_texture_names.add(texture_name)
            # Retain the qualified legacy source colors for reference-renderer
            # audits. Runtime packet construction overwrites these two bytes
            # with the material/distance lookup result before rasterization.
            flat, dither = colors_for_face(face, source_polygon)
            normal, distance = quantized_face_plane(quantized_q2)
            world_faces.extend(
                struct.pack("<HBBBB", first_index, len(source_indices), flat, dither, 0)
            )
            world_max_face_vertices = max(world_max_face_vertices, len(source_indices))
            world_face_planes.extend(struct.pack("<bbbh", *normal, distance))
            world_drawable_faces += 1
            world_material_family_counts[
                shading_record[3] // APPARENT_LIGHT_LEVELS
            ] += 1
            world_flat_color_counts[flat] += 1
            checker_key = f"{dither & 0x0F}+{dither >> 4}"
            world_checker_color_counts[checker_key] = (
                world_checker_color_counts.get(checker_key, 0) + 1
            )
            source_spans = tuple(
                max(vertex[axis] for vertex in source_polygon)
                - min(vertex[axis] for vertex in source_polygon)
                for axis in range(3)
            )
            if any(
                0.0 < span < PVS_QUANTIZATION_GUARD_MAX_SOURCE_SPAN
                for span in source_spans
            ):
                # A sub-unit source sliver can expand after Q2 quantization and
                # become visible outside
                # Quake's source-space PVS. Admit these rare faces globally so
                # the packed geometry keeps VIS conservative for every camera.
                world_pvs_quantization_guard_faces.add(face_index - world_first_face)
        else:
            world_faces.extend(struct.pack("<HBBBB", first_index, 0, 0, 0, 1))
            normal, distance = quantized_face_plane(quantized_q2)
            world_face_planes.extend(struct.pack("<bbbh", *normal, distance))

    if len(world_faces) != world_face_count * FACE_RECORD_BYTES:
        raise AssertionError("full-world face table lost BSP face identity")
    if len(world_face_planes) != world_face_count * FACE_PLANE_RECORD_BYTES:
        raise AssertionError("full-world face-plane table lost BSP face identity")
    if len(world_shading_records) != world_face_count * WORLD_SHADING_RECORD_BYTES:
        raise AssertionError("full-world shading table lost BSP face identity")
    if len(world_face_texture_ids) != world_face_count:
        raise AssertionError("full-world texture-ID table lost BSP face identity")
    source_world_index_count = sum(
        face.edge_count
        for face in faces[world_first_face : world_first_face + world_face_count]
    )
    if len(world_indices) != source_world_index_count:
        raise AssertionError(
            f"full-world index stream lost source surfedges: "
            f"{len(world_indices)} != {source_world_index_count}"
        )
    if (
        len(world_texture_coordinates)
        != source_world_index_count * TEXTURE_COORD_RECORD_BYTES
    ):
        raise AssertionError(
            "full-world texture-coordinate stream lost source surfedges"
        )

    packed_drawable_faces = validate_drawable_face_colors(
        bytes(packed_faces), label="bounded spawn packet"
    )
    if packed_drawable_faces != len(packed_faces) // FACE_RECORD_BYTES:
        raise AssertionError("bounded spawn packet contains a nondrawable face")
    if (
        validate_drawable_face_colors(bytes(world_faces), label="full world")
        != world_drawable_faces
    ):
        raise AssertionError("full-world drawable-face count is inconsistent")

    world_node_bytes = b"".join(
        struct.pack(
            "<HhhHH",
            node.plane,
            node.children[0],
            node.children[1],
            node.first_face,
            node.face_count,
        )
        for node in nodes
    )
    world_node_parents, world_face_owners, world_reachable_node_count = (
        build_world_node_topology(nodes, root, world_first_face, world_face_count)
    )
    world_node_parent_bytes = b"".join(
        struct.pack("<H", parent) for parent in world_node_parents
    )
    world_face_owner_bytes = b"".join(
        struct.pack("<H", owner) for owner in world_face_owners
    )
    world_plane_bytes = b"".join(
        struct.pack("<bbbh", *normal, distance)
        for normal, distance in (
            quantized_bsp_plane(plane, world_origin) for plane in planes
        )
    )
    world_leaf_bytes = b"".join(
        struct.pack(
            "<iHH", leaf.vis_offset, leaf.first_mark_surface, leaf.mark_surface_count
        )
        for leaf in leaves
    )
    world_marksurface_bytes = b"".join(
        struct.pack("<H", face_index) for face_index in marksurfaces
    )
    world_vertex_bytes = b"".join(
        pack_q2_world_vertex(vertex) for vertex in world_q2_vertices
    )
    world_index_bytes = b"".join(struct.pack("<H", index) for index in world_indices)
    world_index_chunks = (
        world_index_bytes[:ROM_BANK_BYTES],
        world_index_bytes[ROM_BANK_BYTES:],
    )
    world_texture_coordinate_chunks = tuple(
        bytes(world_texture_coordinates[offset : offset + ROM_BANK_BYTES])
        for offset in range(0, len(world_texture_coordinates), ROM_BANK_BYTES)
    )
    if len(world_texture_coordinate_chunks) != 3:
        raise AssertionError(
            "E1M3 exact texture coordinates must occupy three ROM banks"
        )

    texture_payloads = tuple(
        textures[source_id].pixels for source_id in referenced_texture_ids
    )
    texture_pixels = b"".join(texture_payloads)
    texture_pixel_chunks, texture_placements = pack_texture_bank_images(
        texture_payloads, bank_count=6
    )
    texture_directory = bytearray()
    exact_texture_records: list[dict[str, object]] = []
    for packed_id, source_id in enumerate(referenced_texture_ids):
        texture = textures[source_id]
        placement = texture_placements[packed_id]
        bank = WORLD_TEXTURE_FIRST_GSU_ROM_BANK + placement.bank_index
        address = 0x8000 + placement.bank_offset
        flags = (
            TEXTURE_FLAG_POWER_OF_TWO_AXES
            if (
                texture.width & (texture.width - 1) == 0
                and texture.height & (texture.height - 1) == 0
            )
            else 0
        )
        if placement.single_bank:
            flags |= TEXTURE_FLAG_SINGLE_BANK
        texture_directory.extend(
            struct.pack(
                "<BHHHB",
                bank,
                address,
                texture.width,
                texture.height,
                flags,
            )
        )
        exact_texture_records.append(
            {
                "packed_id": packed_id,
                "source_miptex_id": source_id,
                "name": texture.name,
                "width": texture.width,
                "height": texture.height,
                "mip_offsets": list(texture.mip_offsets),
                "texture_lump_offset": texture.lump_offset,
                "level0_bytes": len(texture.pixels),
                "level0_sha256": hashlib.sha256(texture.pixels).hexdigest(),
                "gsu_rom_bank": bank,
                "gsu_rom_address": address,
                "bank_span": placement.bank_span,
                "single_bank": placement.single_bank,
                "sampler_route": (
                    "single-bank" if placement.single_bank else "cross-bank"
                ),
                "directory_flags": flags,
                "wrap_flags": flags & TEXTURE_FLAG_POWER_OF_TWO_AXES,
            }
        )
    if (
        len(texture_directory)
        != len(referenced_texture_ids) * TEXTURE_DIRECTORY_RECORD_BYTES
    ):
        raise AssertionError("exact texture directory is inconsistently packed")
    exact_palette_words = tuple(snes_color(color) for color in source_palette)
    exact_palette = b"".join(struct.pack("<H", word) for word in exact_palette_words)
    reconstructed_palette = tuple(
        tuple((((word >> shift) & 31) * 255 + 15) // 31 for shift in (0, 5, 10))
        for word in exact_palette_words
    )
    palette_channel_errors = [
        abs(source_palette[index][channel] - reconstructed_palette[index][channel])
        for index in range(256)
        for channel in range(3)
    ]
    world_visibility_chunks = (
        visibility[:ROM_BANK_BYTES],
        visibility[ROM_BANK_BYTES:],
    )
    if not world_index_chunks[0] or not world_visibility_chunks[0]:
        raise AssertionError("full-world index and visibility data must not be empty")
    if any(
        len(chunk) > ROM_BANK_BYTES
        for chunk in (
            *world_index_chunks,
            *world_visibility_chunks,
            *world_texture_coordinate_chunks,
            *texture_pixel_chunks,
            *world_lightmap_chunks,
        )
    ):
        raise AssertionError("full-world bank chunk exceeds 32 KiB")

    # Precompute one directly consumable face-visibility row for every leaf in
    # the world hull.  This intentionally duplicates Quake's leaf-to-face
    # expansion offline: the GSU only has to resolve a leaf and inflate 553
    # bytes, avoiding thousands of random leaf/marksurface ROM reads per frame.
    world_face_bitset_bytes = (world_face_count + 7) // 8
    pvs_guard_masks: dict[int, int] = {}
    for face_index in sorted(world_pvs_quantization_guard_faces):
        byte_offset = face_index >> 3
        pvs_guard_masks[byte_offset] = pvs_guard_masks.get(byte_offset, 0) | (
            1 << (face_index & 7)
        )
    pvs_guard_bytes = b"".join(
        struct.pack("<HB", byte_offset, mask)
        for byte_offset, mask in sorted(pvs_guard_masks.items())
    )
    if len(pvs_guard_bytes) != len(pvs_guard_masks) * WORLD_PVS_GUARD_RECORD_BYTES:
        raise AssertionError("face-PVS guard records are inconsistently packed")
    pvs_rows: list[tuple[bytes, int]] = []
    for leaf_index in range(vis_leaf_count + 1):
        # Quake's leaf zero is solid and uses the all-visible fallback.  A fly
        # camera has no collision, so retain that authentic conservative policy.
        visible_world_faces: set[int] = (
            set(range(world_face_count)) if leaf_index == 0 else set()
        )
        if leaf_index != 0:
            leaf_pvs = decompress_pvs(
                visibility, leaves[leaf_index].vis_offset, vis_leaf_count
            )
            visible_leaf_indices = {leaf_index}
            visible_leaf_indices.update(
                bit + 1
                for bit in range(vis_leaf_count)
                if leaf_pvs[bit >> 3] & (1 << (bit & 7))
            )
            for visible_leaf_index in visible_leaf_indices:
                leaf = leaves[visible_leaf_index]
                begin = leaf.first_mark_surface
                for face_index in marksurfaces[begin : begin + leaf.mark_surface_count]:
                    if (
                        world_first_face
                        <= face_index
                        < world_first_face + world_face_count
                    ):
                        visible_world_faces.add(face_index - world_first_face)

        face_bits = bytearray(world_face_bitset_bytes)
        for face_index in visible_world_faces:
            face_bits[face_index >> 3] |= 1 << (face_index & 7)
        compressed = zero_run_encode(bytes(face_bits))
        pvs_rows.append(
            (
                compressed,
                len(visible_world_faces | world_pvs_quantization_guard_faces),
            )
        )

    pvs_chunks: list[bytearray] = [bytearray()]
    pvs_directory = bytearray()
    for compressed, face_count in pvs_rows:
        if len(compressed) > ROM_BANK_BYTES:
            raise AssertionError("one face-PVS row exceeds a 32 KiB ROM bank")
        if len(pvs_chunks[-1]) + len(compressed) > ROM_BANK_BYTES:
            pvs_chunks.append(bytearray())
        chunk_index = len(pvs_chunks) - 1
        chunk_offset = len(pvs_chunks[-1])
        pvs_chunks[-1].extend(compressed)
        pvs_directory.extend(
            struct.pack(
                "<HHHBB",
                0x8000 + chunk_offset,
                len(compressed),
                face_count,
                WORLD_PVS_FIRST_GSU_ROM_BANK + chunk_index,
                0,
            )
        )
    if len(pvs_directory) != (vis_leaf_count + 1) * WORLD_PVS_DIRECTORY_RECORD_BYTES:
        raise AssertionError("face-PVS directory lost a world leaf")
    if len(pvs_directory) + len(pvs_guard_bytes) > ROM_BANK_BYTES:
        raise AssertionError("face-PVS directory and guards exceed one ROM bank")
    if any(len(chunk) > ROM_BANK_BYTES for chunk in pvs_chunks):
        raise AssertionError("face-PVS chunk exceeds a 32 KiB ROM bank")

    distance_lookup = material_distance_lut()
    shading_lookup = material_shading_table()
    world_shading_bytes = (
        bytes(world_shading_records) + distance_lookup + shading_lookup
    )
    if len(world_shading_bytes) > ROM_BANK_BYTES:
        raise AssertionError("full-world shading asset exceeds one 32 KiB ROM bank")

    world_info: dict[str, object] = {
        "root_node": root,
        "first_face": world_first_face,
        "origin": world_origin,
        "coordinate_min": world_coordinate_min,
        "coordinate_max": world_coordinate_max,
        "vertex_count": len(world_quantized_vertices),
        "index_count": len(world_indices),
        "face_count": world_face_count,
        "max_face_vertices": world_max_face_vertices,
        "drawable_face_count": world_drawable_faces,
        "nondrawable_face_count": world_face_count - world_drawable_faces,
        "node_count": len(nodes),
        "reachable_node_count": world_reachable_node_count,
        "plane_count": len(planes),
        "leaf_count": len(leaves),
        "vis_leaf_count": vis_leaf_count,
        "marksurface_count": len(marksurfaces),
        "visibility_bytes": len(visibility),
        "shading_record_bytes": WORLD_SHADING_RECORD_BYTES,
        "shading_distance_lut_bytes": len(distance_lookup),
        "shading_table_bytes": len(shading_lookup),
        "shading_bytes": len(world_shading_bytes),
        "texture_count": len(referenced_texture_ids),
        "texture_coordinate_bytes": len(world_texture_coordinates),
        "texture_coordinate_0_bytes": len(world_texture_coordinate_chunks[0]),
        "texture_coordinate_1_bytes": len(world_texture_coordinate_chunks[1]),
        "texture_coordinate_2_bytes": len(world_texture_coordinate_chunks[2]),
        "face_texture_id_bytes": len(world_face_texture_ids),
        "texture_directory_bytes": len(texture_directory),
        "texture_pixel_bytes": len(texture_pixels),
        "texture_pixel_chunk_count": len(texture_pixel_chunks),
        "lightmap_directory_bytes": len(world_lightmap_directory),
        "lightmap_chunk_count": len(world_lightmap_chunks),
        "lightmap_sample_bytes": sum(len(chunk) for chunk in world_lightmap_chunks),
        "lightmap_max_face_sample_bytes": max(
            (int(record.get("sample_bytes", 0)) for record in world_lightmap_records),
            default=0,
        ),
        "lightmapped_face_count": sum(
            bool(record["lightmapped"]) for record in world_lightmap_records
        ),
        "vertex_record_bytes": 4,
        "index_record_bytes": 2,
        "indices_0_bytes": len(world_index_chunks[0]),
        "indices_1_bytes": len(world_index_chunks[1]),
        "visibility_0_bytes": len(world_visibility_chunks[0]),
        "visibility_1_bytes": len(world_visibility_chunks[1]),
        "face_bitset_bytes": world_face_bitset_bytes,
        "pvs_directory_bytes": len(pvs_directory),
        "pvs_guard_record_count": len(pvs_guard_masks),
        "pvs_guard_bytes": len(pvs_guard_bytes),
        "pvs_chunk_count": len(pvs_chunks),
        "pvs_compressed_bytes": sum(len(chunk) for chunk in pvs_chunks),
        "demo_pose_count": len(demo_records),
        "demo_track_bytes": len(demo_track),
        "demo_timing_bytes": len(demo_timing),
        "demo_duration_ticks": demo_ticks[-1],
        "demo_precise_pose_count": len(demo_precise_records),
        "demo_precise_track_bytes": len(demo_precise_track),
        "demo_precise_timing_bytes": len(demo_precise_timing),
        "demo_precise_duration_ticks": demo_precise_ticks[-1],
        "demo_step_pose_count": len(demo_step_indices),
        "demo_verify_near_pose": demo_verify_near_pose,
        "demo_verify_far_pose": demo_verify_far_pose,
        "start_coordinate": start_coordinate,
    }

    vertex_bytes = b"".join(struct.pack("<bbb", *vertex) for vertex in packed_vertices)
    index_bytes = b"".join(struct.pack("<H", index) for index in packed_indices)
    palette_words = [snes_color(color) for color in material_palette]
    output_palette = b"".join(struct.pack("<H", word) for word in palette_words)
    sin_table = bytes(
        round(math.sin(index * math.tau / 32) * 64) & 0xFF for index in range(32)
    )
    cos_table = bytes(
        round(math.cos(index * math.tau / 32) * 64) & 0xFF for index in range(32)
    )
    reciprocal = b"".join(
        struct.pack(
            "<H",
            0
            if depth_q4 < (NEAR_DEPTH << DEPTH_TABLE_FRACTION_BITS)
            else round(RECIPROCAL_NUMERATOR / depth_q4),
        )
        for depth_q4 in range(256 << DEPTH_TABLE_FRACTION_BITS)
    )
    divide_q12_reciprocal = divide_q12_reciprocal_table()
    expand_left, expand_right = expansion_tables()
    yaw_index = round(start_angle * 32 / 360) & 31

    outputs = {
        Path("QuakeBSPVertices.bin"): vertex_bytes,
        Path("QuakeBSPIndices.bin"): index_bytes,
        Path("QuakeBSPFaces.bin"): bytes(packed_faces),
        Path("QuakeBSPFacePlanes.bin"): bytes(packed_face_planes),
        Path("QuakeBSPPalette.bin"): output_palette,
        Path("QuakeBSPTilemap.bin"): tilemap_bytes(),
        Path("QuakeBSPTexturePalette.bin"): exact_palette,
        Path("QuakeBSPTextureTilemap.bin"): texture_tilemap_bytes(),
        Path("QuakeBSPTextureCoordinateMap.bin"): texture_coordinate_map(),
        Path("QuakeBSPTextureDepthShade.bin"): texture_depth_lut,
        Path("QuakeBSPTextureColormap.bin"): texture_depth_colormap,
        Path("QuakeBSPLightmapColormapMap.bin"): lightmap_colormap_map,
        Path("QuakeBSPLightmapLevelZeroColormap.bin"): lightmap_level_zero,
        Path("QuakeBSPLightmapColormap.bin"): lightmap_colormap,
        Path("QuakeBSPSin.bin"): sin_table,
        Path("QuakeBSPCos.bin"): cos_table,
        Path("QuakeBSPReciprocal.bin"): reciprocal,
        Path("QuakeBSPDivideQ12Reciprocal.bin"): divide_q12_reciprocal,
        Path("QuakeBSPExpandLeft.bin"): expand_left,
        Path("QuakeBSPExpandRight.bin"): expand_right,
        Path("QuakeBSPWorldVertices.bin"): world_vertex_bytes,
        Path("QuakeBSPWorldIndices0.bin"): world_index_chunks[0],
        Path("QuakeBSPWorldIndices1.bin"): world_index_chunks[1],
        Path("QuakeBSPWorldFaces.bin"): bytes(world_faces),
        Path("QuakeBSPWorldFacePlanes.bin"): bytes(world_face_planes),
        Path("QuakeBSPWorldShading.bin"): world_shading_bytes,
        Path("QuakeBSPWorldTextureCoordinates0.bin"): world_texture_coordinate_chunks[
            0
        ],
        Path("QuakeBSPWorldTextureCoordinates1.bin"): world_texture_coordinate_chunks[
            1
        ],
        Path("QuakeBSPWorldTextureCoordinates2.bin"): world_texture_coordinate_chunks[
            2
        ],
        Path("QuakeBSPWorldFaceTextureIds.bin"): bytes(world_face_texture_ids),
        Path("QuakeBSPWorldTextureDirectory.bin"): bytes(texture_directory),
        Path("QuakeBSPWorldLightmapDirectory.bin"): world_lightmap_directory,
        Path("QuakeBSPWorldNodes.bin"): world_node_bytes,
        Path("QuakeBSPWorldNodeParents.bin"): world_node_parent_bytes,
        Path("QuakeBSPWorldFaceOwners.bin"): world_face_owner_bytes,
        Path("QuakeBSPWorldPlanes.bin"): world_plane_bytes,
        Path("QuakeBSPWorldLeaves.bin"): world_leaf_bytes,
        Path("QuakeBSPWorldMarksurfaces.bin"): world_marksurface_bytes,
        Path("QuakeBSPWorldVisibility0.bin"): world_visibility_chunks[0],
        Path("QuakeBSPWorldVisibility1.bin"): world_visibility_chunks[1],
        Path("QuakeBSPWorldPVSDirectory.bin"): bytes(pvs_directory),
        Path("QuakeBSPWorldPVSGuards.bin"): pvs_guard_bytes,
        Path("QuakeBSPDemoTrack.bin"): demo_track,
        Path("QuakeBSPDemoTiming.bin"): demo_timing,
        Path("QuakeBSPDemoPrecise30Hz.bin"): demo_precise_track,
        Path("QuakeBSPDemoPrecise30HzTiming.bin"): demo_precise_timing,
        Path("QuakeBSPScene.i"): (
            table_include(
                len(packed_vertices),
                len(packed_indices),
                len(packed_faces) // FACE_RECORD_BYTES,
                yaw_index,
            )
            + world_table_include(world_info)
        ),
    }
    outputs.update(
        {
            Path(f"QuakeBSPWorldPVS{index}.bin"): bytes(chunk)
            for index, chunk in enumerate(pvs_chunks)
        }
    )
    outputs.update(
        {
            Path(f"QuakeBSPWorldTexturePixels{index}.bin"): chunk
            for index, chunk in enumerate(texture_pixel_chunks)
        }
    )
    outputs.update(
        {
            Path(f"QuakeBSPWorldLightmapSamples{index}.bin"): chunk
            for index, chunk in enumerate(world_lightmap_chunks)
        }
    )
    metadata: dict[str, object] = {
        "source": {
            "pak_path_hint": QUAKE_PAK_PATH_HINT,
            "pak_entry": BSP_ENTRY,
            "pak_sha256": hashlib.sha256(pak_bytes).hexdigest(),
            "bsp_sha256": hashlib.sha256(bsp).hexdigest(),
            "bsp_version": BSP_VERSION,
            "palette_entry": PALETTE_ENTRY,
            "palette_sha256": hashlib.sha256(palette_bytes).hexdigest(),
            "colormap_entry": COLORMAP_ENTRY,
            "colormap_sha256": hashlib.sha256(colormap_bytes).hexdigest(),
            "lighting_bytes": len(lighting),
            "lighting_sha256": hashlib.sha256(lighting).hexdigest(),
            "demo_entry": DEMO_ENTRY,
            "demo_sha256": hashlib.sha256(demo).hexdigest(),
        },
        "selection": {
            "player_start": list(start),
            "player_start_coordinate": list(start_coordinate),
            "player_angle": start_angle,
            "player_leaf": spawn_leaf,
            "pvs_leaf_count": len(visible_leaves),
            "pvs_face_count": len(pvs_faces),
            "clip_world_units": CLIP_WORLD,
            "world_units_per_quantized_unit": WORLD_SCALE,
            "clipped_face_count": len(packed_faces) // FACE_RECORD_BYTES,
            "vertex_count": len(packed_vertices),
            "polygon_index_count": len(packed_indices),
            "texture_names": sorted(texture_names),
        },
        "world": {
            "model_index": 0,
            "root_node": root,
            "first_face": world_first_face,
            "face_count": world_face_count,
            "vis_leaf_count": vis_leaf_count,
            "source_bounds": {
                "mins": list(world_mins),
                "maxs": list(world_maxs),
                "vertex_mins": list(world_vertex_mins),
                "vertex_maxs": list(world_vertex_maxs),
            },
            "source_counts": {
                "planes": len(planes),
                "vertices": len(vertices),
                "nodes": len(nodes),
                "texinfo": len(texinfo),
                "faces": len(faces),
                "world_faces": world_face_count,
                "world_polygon_indices": source_world_index_count,
                "leaves": len(leaves),
                "marksurfaces": len(marksurfaces),
                "edges": len(edges),
                "surfedges": len(surfedges),
                "models": len(models),
                "visibility_bytes": len(visibility),
            },
            "quantization": {
                "origin": list(world_origin),
                "world_units_per_quantized_unit": WORLD_SCALE / 4,
                "fraction_bits": 2,
                "storage": "three signed int8 integer bases plus one xyz residual byte",
                "coordinate_min": list(world_coordinate_min),
                "coordinate_max": list(world_coordinate_max),
            },
            "packing": {
                "vertex_count": len(world_quantized_vertices),
                "index_count": len(world_indices),
                "face_count": world_face_count,
                "drawable_face_count": world_drawable_faces,
                "nondrawable_face_count": world_face_count - world_drawable_faces,
                "node_count": len(nodes),
                "plane_count": len(planes),
                "leaf_count": len(leaves),
                "marksurface_count": len(marksurfaces),
                "visibility_bytes": len(visibility),
                "vertex_record_bytes": 4,
                "vertex_record_format": "<bbbB; Q2 xyz = signed base*4 + packed 2-bit residual",
                "index_record_bytes": 2,
                "index_record_format": "<H",
                "face_record_bytes": FACE_RECORD_BYTES,
                "face_record_format": "<HBBBB",
                "face_plane_record_bytes": FACE_PLANE_RECORD_BYTES,
                "face_plane_record_format": "<bbbh",
                "face_plane_source": (
                    "largest-area triangle in the packed Q2 polygon fan, "
                    "or an always-culled plane for collapsed faces"
                ),
                "shading_file": "QuakeBSPWorldShading.bin",
                "shading_record_bytes": WORLD_SHADING_RECORD_BYTES,
                "shading_record_format": "<bbbB signed centroid xyz, family*9+orientation light",
                "shading_record_count": world_face_count,
                "shading_record_bytes_total": len(world_shading_records),
                "shading_distance_lut_offset": len(world_shading_records),
                "shading_distance_lut_bytes": len(distance_lookup),
                "shading_table_offset": len(world_shading_records)
                + len(distance_lookup),
                "shading_table_record_bytes": WORLD_SHADING_TABLE_RECORD_BYTES,
                "shading_table_bytes": len(shading_lookup),
                "shading_asset_bytes": len(world_shading_bytes),
                "shading_gsu_rom_bank": WORLD_SHADING_GSU_ROM_BANK,
                "exact_textures": {
                    "texture_count": len(referenced_texture_ids),
                    "textures": exact_texture_records,
                    "coordinate_file_pattern": "QuakeBSPWorldTextureCoordinates{0,1,2}.bin",
                    "coordinate_record_format": "<hh signed Q4 s,t per source world index",
                    "coordinate_record_bytes": TEXTURE_COORD_RECORD_BYTES,
                    "coordinate_bytes": len(world_texture_coordinates),
                    "coordinate_chunks": [
                        {
                            "file": f"QuakeBSPWorldTextureCoordinates{index}.bin",
                            "bytes": len(chunk),
                            "gsu_rom_bank": WORLD_TEXCOORD_FIRST_GSU_ROM_BANK + index,
                        }
                        for index, chunk in enumerate(world_texture_coordinate_chunks)
                    ],
                    "face_texture_id_file": "QuakeBSPWorldFaceTextureIds.bin",
                    "face_texture_id_bytes": len(world_face_texture_ids),
                    "face_texture_id_semantics": "packed texture ID; 255 means no embedded miptex",
                    "directory_file": "QuakeBSPWorldTextureDirectory.bin",
                    "directory_record_format": "<BHHHB bank,address,width,height,flags",
                    "directory_flag_bits": {
                        "power_of_two_axes": TEXTURE_FLAG_POWER_OF_TWO_AXES,
                        "single_bank": TEXTURE_FLAG_SINGLE_BANK,
                    },
                    "directory_record_bytes": TEXTURE_DIRECTORY_RECORD_BYTES,
                    "directory_bytes": len(texture_directory),
                    "packing_strategy": (
                        "bank-aligned multi-bank textures, then deterministic "
                        "first-fit decreasing single-bank textures"
                    ),
                    "pixel_file_pattern": "QuakeBSPWorldTexturePixels{0..5}.bin",
                    "pixel_bytes": len(texture_pixels),
                    "stored_pixel_bytes": sum(
                        len(chunk) for chunk in texture_pixel_chunks
                    ),
                    "bank_padding_bytes": (
                        sum(len(chunk) for chunk in texture_pixel_chunks)
                        - len(texture_pixels)
                    ),
                    "single_bank_texture_count": sum(
                        placement.single_bank for placement in texture_placements
                    ),
                    "cross_bank_texture_count": sum(
                        not placement.single_bank for placement in texture_placements
                    ),
                    "pixel_chunks": [
                        {
                            "file": f"QuakeBSPWorldTexturePixels{index}.bin",
                            "bytes": len(chunk),
                            "gsu_rom_bank": WORLD_TEXTURE_FIRST_GSU_ROM_BANK + index,
                        }
                        for index, chunk in enumerate(texture_pixel_chunks)
                    ],
                    "palette_file": "QuakeBSPTexturePalette.bin",
                    "palette_source": PALETTE_ENTRY,
                    "palette_conversion": "independent round(R,G,B * 31 / 255) to BGR555",
                    "palette_max_channel_error": max(palette_channel_errors),
                    "palette_mean_channel_error": sum(palette_channel_errors)
                    / len(palette_channel_errors),
                    "depth_shading": {
                        "depth_lut_file": "QuakeBSPTextureDepthShade.bin",
                        "depth_lut_bytes": len(texture_depth_lut),
                        "depth_input": "HIB of Q6 camera-space depth (four-unit buckets)",
                        "near_distance": TEXTURE_SHADE_NEAR_DISTANCE,
                        "far_distance": TEXTURE_SHADE_FAR_DISTANCE,
                        "colormap_file": "QuakeBSPTextureColormap.bin",
                        "colormap_source": COLORMAP_ENTRY,
                        "colormap_first_level": TEXTURE_DEPTH_COLORMAP_FIRST_LEVEL,
                        "colormap_last_level": TEXTURE_DEPTH_COLORMAP_LAST_LEVEL,
                        "depth_colormap_levels": TEXTURE_DEPTH_COLORMAP_LEVELS,
                        "packed_colormap_levels": TEXTURE_COLORMAP_LEVELS,
                        "colormap_bytes": len(texture_depth_colormap),
                        "fullbright_indices": [224, 255],
                    },
                    "lightmaps": {
                        "directory_file": "QuakeBSPWorldLightmapDirectory.bin",
                        "directory_record_bytes": LIGHTMAP_DIRECTORY_RECORD_BYTES,
                        "directory_bytes": len(world_lightmap_directory),
                        "sample_file_pattern": "QuakeBSPWorldLightmapSamples{0..4}.bin",
                        "sample_bytes": sum(
                            len(chunk) for chunk in world_lightmap_chunks
                        ),
                        "max_face_sample_bytes": max(
                            (
                                int(record.get("sample_bytes", 0))
                                for record in world_lightmap_records
                            ),
                            default=0,
                        ),
                        "sample_chunks": [
                            {
                                "file": f"QuakeBSPWorldLightmapSamples{index}.bin",
                                "bytes": len(chunk),
                                "gsu_rom_bank": WORLD_LIGHTMAP_FIRST_GSU_ROM_BANK
                                + index,
                            }
                            for index, chunk in enumerate(world_lightmap_chunks)
                        ],
                        "lightmapped_faces": sum(
                            bool(record["lightmapped"])
                            for record in world_lightmap_records
                        ),
                        "unlightmapped_faces": sum(
                            not bool(record["lightmapped"])
                            for record in world_lightmap_records
                        ),
                        "missing_dark_faces": sum(
                            not bool(record["lightmapped"])
                            and record["missing_level"] == LIGHTMAP_DARKEST_LEVEL
                            for record in world_lightmap_records
                        ),
                        "missing_bypass_faces": sum(
                            not bool(record["lightmapped"])
                            and record["missing_level"] == 0
                            for record in world_lightmap_records
                        ),
                        "missing_level_encoding": (
                            "bank FF; address C0 + fallback colormap level"
                        ),
                        "source_lighting_bytes": len(lighting),
                        "source_lighting_sha256": hashlib.sha256(lighting).hexdigest(),
                        "sample_grid_units": 16,
                        "sample_format": "one precombined 6-bit colormap level per byte",
                        "static_style_scale_8_8": QUAKE_NEUTRAL_LIGHT_STYLE_SCALE,
                        "interpolation_fraction_bits": 4,
                        "colormap_map_file": "QuakeBSPLightmapColormapMap.bin",
                        "colormap_level_zero_file": (
                            "QuakeBSPLightmapLevelZeroColormap.bin"
                        ),
                        "colormap_min_exact_level": LIGHTMAP_MIN_EXACT_COLORMAP_LEVEL,
                        "colormap_approximation": (
                            "source levels 1..9 map to level 10; source level 0 "
                            "and levels 10..63 are exact"
                        ),
                    },
                },
                "node_record_bytes": WORLD_NODE_RECORD_BYTES,
                "node_record_format": "<HhhHH",
                "node_parent_record_bytes": WORLD_NODE_PARENT_RECORD_BYTES,
                "node_parent_record_format": "<H; $ffff for root/unreachable",
                "face_owner_record_bytes": WORLD_FACE_OWNER_RECORD_BYTES,
                "face_owner_record_format": "<H BSP node index",
                "reachable_node_count": world_reachable_node_count,
                "plane_record_bytes": WORLD_PLANE_RECORD_BYTES,
                "plane_record_format": "<bbbh",
                "leaf_record_bytes": WORLD_LEAF_RECORD_BYTES,
                "leaf_record_format": "<iHH",
                "marksurface_record_bytes": WORLD_MARKSURFACE_RECORD_BYTES,
                "marksurface_record_format": "<H",
                "face_order": "original BSP world-model face order",
                "nondrawable_encoding": "face count byte is zero",
                "index_chunks": [
                    {
                        "file": "QuakeBSPWorldIndices0.bin",
                        "bytes": len(world_index_chunks[0]),
                    },
                    {
                        "file": "QuakeBSPWorldIndices1.bin",
                        "bytes": len(world_index_chunks[1]),
                    },
                ],
                "visibility_chunks": [
                    {
                        "file": "QuakeBSPWorldVisibility0.bin",
                        "bytes": len(world_visibility_chunks[0]),
                    },
                    {
                        "file": "QuakeBSPWorldVisibility1.bin",
                        "bytes": len(world_visibility_chunks[1]),
                    },
                ],
                "face_pvs": {
                    "directory_file": "QuakeBSPWorldPVSDirectory.bin",
                    "directory_bytes": len(pvs_directory),
                    "directory_record_bytes": WORLD_PVS_DIRECTORY_RECORD_BYTES,
                    "directory_record_format": "<HHHBB",
                    "row_count": len(pvs_rows),
                    "decoded_row_bytes": world_face_bitset_bytes,
                    "encoding": "zero bytes encoded as 0,count; nonzero bytes literal",
                    "face_count_semantics": "unique BSP world-model face identities",
                    "quantization_guard": {
                        "policy": (
                            "globally admit drawable faces with a nonzero source-axis "
                            "span below one Quake unit; Q2 packing can otherwise "
                            "expand them outside source VIS"
                        ),
                        "maximum_source_span_exclusive": (
                            PVS_QUANTIZATION_GUARD_MAX_SOURCE_SPAN
                        ),
                        "face_count": len(world_pvs_quantization_guard_faces),
                        "face_ids": sorted(world_pvs_quantization_guard_faces),
                        "file": "QuakeBSPWorldPVSGuards.bin",
                        "record_format": "<HB byte offset, OR mask",
                        "record_bytes": WORLD_PVS_GUARD_RECORD_BYTES,
                        "record_count": len(pvs_guard_masks),
                        "bytes": len(pvs_guard_bytes),
                    },
                    "verification": "host hashes the decoded face bitset byte-for-byte",
                    "chunks": [
                        {
                            "file": f"QuakeBSPWorldPVS{index}.bin",
                            "bytes": len(chunk),
                        }
                        for index, chunk in enumerate(pvs_chunks)
                    ],
                    "compressed_bytes": sum(len(chunk) for chunk in pvs_chunks),
                },
                "texture_names": sorted(world_texture_names),
            },
        },
        "demo": {
            "entry": DEMO_ENTRY,
            "map_entry": BSP_ENTRY,
            "sha256": hashlib.sha256(demo).hexdigest(),
            "source_bytes": len(demo),
            "forced_cd_track": forced_track,
            "source_camera_samples": len(demo_samples),
            "sample_retention": "all reconstructed source camera samples",
            "camera_origin_semantics": (
                "view-entity origin plus protocol-15 svc_clientdata view height"
            ),
            "default_view_height": DEFAULT_VIEWHEIGHT,
            "packed_view_height_values": sorted(set(demo_view_heights)),
            "track_pose_count": len(demo_records),
            "distinct_packed_pose_count": len(set(demo_records)),
            "consecutive_repeated_pose_count": sum(
                left == right for left, right in zip(demo_records, demo_records[1:])
            ),
            "track_record_bytes": DEMO_TRACK_RECORD_BYTES,
            "track_bytes": len(demo_track),
            "timing_record_bytes": DEMO_TIMING_RECORD_BYTES,
            "timing_bytes": len(demo_timing),
            "precise_track_record_bytes": DEMO_PRECISE_TRACK_RECORD_BYTES,
            "precise_track_bytes": len(demo_precise_track),
            "precise_track_pose_count": len(demo_precise_records),
            "precise_track_sample_rate_hz": DEMO_PRECISE_SAMPLE_RATE_HZ,
            "precise_timing_record_bytes": DEMO_TIMING_RECORD_BYTES,
            "precise_timing_bytes": len(demo_precise_timing),
            "precise_duration_ticks": demo_precise_ticks[-1],
            "precise_timing_quantization": ("round(n * ntsc_frames_per_second / 30)"),
            "precise_track_duration_seconds": (
                len(demo_precise_records) / DEMO_PRECISE_SAMPLE_RATE_HZ
            ),
            "precise_track_distinct_source_samples": len(set(precise_source_indices)),
            "precise_track_sampling": (
                "newest source transform due at n/30 seconds; no interpolation"
            ),
            "precise_track_encoding": (
                "absolute signed Q3 xyz; uint16-turn yaw/pitch; roll omitted "
                "because every source sample is zero"
            ),
            "step_sample_rate_hz": DEMO_STEP_SAMPLE_RATE_HZ,
            "step_stride": DEMO_STEP_STRIDE,
            "step_pose_count": len(demo_step_indices),
            "step_pose_indices": list(demo_step_indices),
            "step_sampling": ("canonical 30 Hz indices n*15; no second camera stream"),
            "first_source_record": demo_source_records[0],
            "last_source_record": demo_source_records[-1],
            "first_server_time": demo_source_times[0],
            "last_server_time": demo_source_times[-1],
            "duration_seconds": demo_source_times[-1] - demo_source_times[0],
            "ntsc_frames_per_second": NTSC_FRAMES_PER_SECOND,
            "duration_ticks": demo_ticks[-1],
            "distinct_timing_ticks": len(set(demo_ticks)),
            "same_tick_sample_count": len(demo_ticks) - len(set(demo_ticks)),
            "timing_quantization": (
                "round((svc_time - first_server_time) * ntsc_frames_per_second)"
            ),
            "pose_timing": [
                {
                    "track_pose": index,
                    "source_record": source_record,
                    "server_time": server_time,
                    "relative_seconds": server_time - first_demo_time,
                    "ntsc_tick": tick,
                }
                for index, (source_record, server_time, tick) in enumerate(
                    zip(demo_source_records, demo_source_times, demo_ticks, strict=True)
                )
            ],
            "distinct_leaf_count": len(demo_leaf_ids),
            "coordinate_encoding": "map-centered signed int8 at 16 Quake units",
            "angle_encoding": "32-step yaw; inverted signed 32-step pitch",
            "playback": {
                "ordered": (
                    "advance one canonical 2 Hz source-time pose per staged frame"
                ),
                "realtime_snes": (
                    "publish only the newest canonical 30 Hz pose due at the "
                    "monotonic NTSC tick; skip obsolete due poses"
                ),
                "realtime_cpp": (
                    "select floor(elapsed_seconds * 30) from the same stream"
                ),
                "interpolation_cpp": "none (cl_nolerp-equivalent transform sampling)",
            },
        },
        "render": {
            "logical_resolution": [LOGICAL_WIDTH, LOGICAL_HEIGHT],
            "physical_resolution": [PHYSICAL_WIDTH, PHYSICAL_HEIGHT],
            "bits_per_pixel": BITS_PER_PIXEL,
            "exact_texture_experiment": {
                "bits_per_pixel": 8,
                "logical_framebuffer_bytes": 128 * 128,
                "visible_tile_bytes": LOGICAL_WIDTH * LOGICAL_HEIGHT,
                "tile_count": (LOGICAL_WIDTH // 8) * (LOGICAL_HEIGHT // 8),
                "presentation": "one source tile repeated as normal/H/V/HV mosaic-2 quad",
                "coordinate_permutation": [0, 2, 4, 6, 7, 5, 3, 1],
                "physical_pixel_scale": [2, 2],
                "palette_entries": 256,
                "lightmaps": False,
                "shading": False,
                "filter": "nearest",
                "wrap": "per-axis modulo original miptex width/height",
            },
            "lightmap_texture_experiment": {
                "technique": 4,
                "bits_per_pixel": 8,
                "texture_filter": "nearest",
                "lightmap_grid_units": 16,
                "lightmap_filter": "bilinear with four-bit fractions",
                "light_styles": (
                    "all baked planes statically combined at neutral 8.8 scale 264"
                ),
                "colormap": "original Quake palette-index remaps",
                "colormap_exact_levels": [10, 63],
                "colormap_identity_level": 0,
                "colormap_clamped_levels": [1, 9],
                "fullbright_indices": [224, 255],
                "z_buffer": False,
                "framebuffer_clear": False,
            },
            "face_record_bytes": FACE_RECORD_BYTES,
            "face_plane_record_bytes": FACE_PLANE_RECORD_BYTES,
            "near_depth_quantized_units": NEAR_DEPTH,
            "view_fraction_bits": VIEW_FRACTION_BITS,
            "depth_table_fraction_bits": DEPTH_TABLE_FRACTION_BITS,
            "reciprocal_numerator": RECIPROCAL_NUMERATOR,
            "reciprocal_entry_bytes": 2,
            "reciprocal_entry_count": 256 << DEPTH_TABLE_FRACTION_BITS,
            "projection_shift": PROJECTION_SHIFT,
            "projection_focal_pixels": 96,
            "spawn_front_face_count": spawn_front_faces,
            "spawn_back_face_count": len(packed_faces) // FACE_RECORD_BYTES
            - spawn_front_faces,
            "winding_validation_triangles": winding_validation_triangles,
            "winding_ambiguous_triangles": winding_ambiguous_triangles,
            "winding_mismatched_triangles": winding_mismatched_triangles,
            "default_technique": (
                "BSP-order painter with depth-shaded 8bpp level-0 miptex indices"
            ),
            "palette_rgb": [list(color) for color in material_palette],
            "clear_color": {
                "index": CLEAR_COLOR_INDEX,
                "rgb": list(CLEAR_COLOR_RGB),
                "purpose": "test-only poison and unwritten-geometry diagnostics",
            },
            "face_color_mapping": {
                "source": "embedded texture pixels, oriented face normal, centroid distance",
                "light_direction": list(FACE_LIGHT_DIRECTION),
                "texture_family_count": TEXTURE_FAMILY_COUNT,
                "texture_family_hues": list(family_hues),
                "physical_colors_per_family": PHYSICAL_COLORS_PER_FAMILY,
                "apparent_light_levels_per_family": APPARENT_LIGHT_LEVELS,
                "family_drawable_face_counts": world_material_family_counts,
                "texture_families": {
                    texture.name: texture_families[index]
                    for index, texture in enumerate(textures)
                    if texture.pixels and texture.name in world_texture_names
                },
                "orientation_formula": "round((0.25 + 0.75*max(0,dot(normal,(2,-3,5))))*8)",
                "centroid_storage": "map-centered signed int8 xyz at 16 Quake units",
                "distance_formula": "max(abs(delta)) + middle(abs(delta))/2 + min(abs(delta))/4",
                "distance_bucket_formula": "clamp(trunc((distance-8)/13),0,7)",
                "distance_bucket_count": DISTANCE_BUCKET_COUNT,
                "shade_formula": "round(base_light*(10-distance_bucket)/10)",
                "flat_quantization": "brighter physical color of an apparent level",
                "checker_quantization": "solid or adjacent-palette checker within one material ramp",
                "drawable_palette_indices": [1, DRAWABLE_COLOR_COUNT],
                "reserved_clear_index": CLEAR_COLOR_INDEX,
                "flat_index_histogram": {
                    str(index): world_flat_color_counts[index]
                    for index in range(1, DRAWABLE_COLOR_COUNT + 1)
                },
                "checker_pair_histogram": dict(
                    sorted(world_checker_color_counts.items())
                ),
                "uses_face_orientation": True,
                "uses_face_position": False,
                "uses_camera_distance": True,
                "uses_texture_color": True,
            },
        },
        "outputs": {},
    }
    metadata["outputs"] = {
        str(path): {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        for path, data in outputs.items()
    }
    outputs[Path("QuakeBSPMetadata.json")] = (
        json.dumps(metadata, indent=2, sort_keys=True) + "\n"
    ).encode("ascii")
    return outputs, metadata


def write_or_check(outputs: dict[Path, bytes], output_dir: Path, check: bool) -> None:
    try:
        sync_generated_outputs(
            outputs,
            output_dir,
            check=check,
            owned_families=OWNED_OUTPUT_FAMILIES,
        )
    except GeneratedOutputError as error:
        raise SystemExit(f"generated SNES Quake assets are stale:\n{error}") from None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pak", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    pak_path = locate_quake_pak(args.pak)
    outputs, metadata = generate(pak_path)
    write_or_check(outputs, args.output, args.check)
    selection = metadata["selection"]
    world = metadata["world"]
    assert isinstance(world, dict)
    packing = world["packing"]
    assert isinstance(packing, dict)
    action = "verified" if args.check else "generated"
    print(
        f"{action} {selection['clipped_face_count']} faces, "
        f"{selection['vertex_count']} vertices, and "
        f"{selection['polygon_index_count']} indices for the bounded path; "
        f"full world has {packing['face_count']} face records, "
        f"{packing['vertex_count']} vertices, and {packing['index_count']} indices"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
