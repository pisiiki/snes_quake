#!/usr/bin/env python3
# ruff: noqa: E402, F405
"""Pack a configured Quake level and optional demo for SuperFX."""

from __future__ import annotations

from snes_tooling import Workspace

import argparse
import hashlib
import json
import math
import struct
import sys
import time
from pathlib import Path


TOOLS_DIR = Workspace.discover().path('tools', 'snes_tooling', 'quake')
SHARED_TOOLS_DIR = Workspace.discover().shared_tools


from snes_tooling.shared.generated_outputs import (
    GeneratedOutputError,
    sync_generated_outputs,
)  # noqa: E402
from snes_tooling.quake.quake_bsp_fly_collision import build_collision_assets  # noqa: E402
from snes_tooling.quake.quake_bsp_edge_refinement import (
    PACKED_AFFINE_REFINEMENT_POLICY, packed_world_edge_candidates,
    refine_packed_face_coordinates, refine_world_face_edges,
)
from snes_tooling.quake.quake_bsp_cull_planes import (
    CAMERA_Q2_DOMAIN, WORLD_CULL_POLICY, derive_world_cull_plane,
)
from snes_tooling.quake.quake_camera_sampling import CAMERA_SAMPLING_CONTRACT, sample_camera_track
from snes_tooling.quake.quake_scene_sampling import SCENE_SAMPLING_CONTRACT
from snes_tooling.quake.quake_demo import (  # noqa: E402
    DEFAULT_VIEWHEIGHT,
    extract_camera_samples,
    sample_newest_due_indices,
)
from snes_tooling.quake.quake_rom_config import (  # noqa: E402
    DEFAULT_CONFIG,
    DEFAULT_PLAYBACK_SAMPLE_RATE_HZ,
    DemoSource,
    configured_playback_sample_rate,
    configured_target,
    configured_sky,
    resolve_configured_demo,
    resolve_demo_source,
)

# Keep this module as the stable CLI and import facade for existing consumers.
from snes_tooling.quake.quake_bsp_assets import *  # noqa: E402,F401,F403


def require_world_geometry(directory, payloads, *, origin, scale):
    """Reject a changed saved-corpus geometry before starting a visibility bake."""
    directory = Path(directory)
    quantization = json.loads((directory / 'QuakeBSPMetadata.json').read_bytes())['world']['quantization']
    if (list(origin) != quantization['origin']
            or scale / 4 != quantization['world_units_per_quantized_unit']
            or quantization['fraction_bits'] != 2):
        raise ValueError('world coordinate frame differs before visibility bake')
    changed = [name for name, value in payloads.items()
               if (directory / name).read_bytes() != value]
    if changed:
        raise ValueError('world geometry differs before visibility bake: ' + ', '.join(changed))
    print(f'world geometry preflight: {len(payloads)} binary files match {directory}',
          file=sys.stderr, flush=True)


def generate(
    pak_path: Path,
    demo_path: Path | None = None,
    *,
    config_path: Path | None = None,
    packed_edge_scope: str = "eligible-world",
    require_world_geometry_from: Path | None = None,
) -> tuple[dict[Path, bytes], dict[str, object]]:
    if packed_edge_scope not in ("eligible-world", "bsp-all-exact"):
        raise ValueError(f"unknown packed edge refinement scope: {packed_edge_scope}")
    if demo_path is not None and config_path is not None:
        raise ValueError("demo_path and config_path are mutually exclusive")
    pak_bytes = pak_path.read_bytes()
    archive = PakArchive(pak_path)
    if demo_path is None:
        config_path = config_path or DEFAULT_CONFIG
        target = configured_target(config_path)
        selected_demo = (resolve_configured_demo(archive.read, config_path)
                         if target["mode"] == "demo" else None)
        playback_sample_rate_hz = configured_playback_sample_rate(config_path)
        sky_enabled = configured_sky(config_path).enabled
    else:
        target = {}
        selected_demo = resolve_demo_source(
            DemoSource("file", str(demo_path.resolve()), DEFAULT_CONFIG),
            archive.read,
        )
        playback_sample_rate_hz = DEFAULT_PLAYBACK_SAMPLE_RATE_HZ
        sky_enabled = True
    if playback_sample_rate_hz % DEMO_STEP_SAMPLE_RATE_HZ:
        raise ValueError("ordered playback rate must divide the configured rate")
    demo_ordered_pose_stride = playback_sample_rate_hz // DEMO_STEP_SAMPLE_RATE_HZ
    demo = selected_demo.payload if selected_demo is not None else b""
    map_entry = selected_demo.map_entry if selected_demo is not None else target["map"]
    bsp = archive.read(map_entry)
    bsp_sha256 = hashlib.sha256(bsp).hexdigest()
    if selected_demo is None and target.get("bspSha256", bsp_sha256) != bsp_sha256:
        raise ValueError(f"PAK {map_entry} does not match the configured original BSP SHA-256")
    canonical_demo = (
        selected_demo is not None
        and selected_demo.source.kind == "pak"
        and selected_demo.source.locator == DEMO_ENTRY
    )
    from snes_tooling.quake.quake_target_layout import asset_layout
    layout = asset_layout(selected_demo is not None, map_entry)
    palette_bytes = archive.read(PALETTE_ENTRY)
    colormap_bytes = archive.read(COLORMAP_ENTRY)
    if len(palette_bytes) != 768:
        raise ValueError("Quake palette must contain 768 bytes")
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
        world_lightmap_packing,
    ) = pack_world_lightmaps(
        faces[world_first_face : world_first_face + world_face_count],
        vertices,
        edges,
        surfedges,
        texinfo,
        textures,
        lighting,
        sky_enabled=sky_enabled,
        first_bank=layout.lightmap_first,
        maximum_bank_count=layout.lightmap_count,
    )
    world_lightmap_chunk_count = len(world_lightmap_chunks)
    world_lightmap_chunks = (
        *world_lightmap_chunks,
        *(b"" for _ in range(layout.lightmap_count - world_lightmap_chunk_count)),
    )
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
            struct.pack("<HBBB", first_index, len(quantized), flat, dither)
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

    from snes_tooling.quake.quake_playback_assets import pack_playback, disabled_playback
    playback = (pack_playback(demo, map_entry, world_origin, nodes, planes, root,
                             leaves, playback_sample_rate_hz,
                             demo_ordered_pose_stride, canonical_demo)
                if selected_demo is not None else disabled_playback())

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
    world_face_stream_padding_records = 0
    world_pvs_quantization_guard_faces: set[int] = set()
    world_plane_cull_guard_faces: set[int] = set()
    world_planar_cull_shifts: dict[int, int] = {}
    world_source_contours = []
    world_refinement_eligible = []
    for face in faces[world_first_face : world_first_face + world_face_count]:
        contour = tuple(
            edges[abs(surfedge)][0 if surfedge >= 0 else 1]
            for surfedge in surfedges[face.first_edge : face.first_edge + face.edge_count]
        )
        world_source_contours.append(contour)
        world_refinement_eligible.append(
            len(contour) <= 255
            and polygon_has_area([vertices[index] for index in contour])
            and polygon_has_area([world_q2_vertices[index] for index in contour])
            and texture_for_face(face) is not None
        )
    world_refined_contours, world_edge_refinement = refine_world_face_edges(
        vertices, world_q2_vertices, world_source_contours, world_refinement_eligible
    )
    if world_edge_refinement["maximum_face_vertices"] > 255:
        raise AssertionError("refined world polygon exceeds byte vertex count")
    world_packed_candidates = packed_world_edge_candidates(
        world_q2_vertices, world_refined_contours, world_refinement_eligible,
        source_vertices=vertices,
        extra_contours=tuple(
            tuple(edges[abs(surfedge)][0 if surfedge >= 0 else 1]
                  for surfedge in surfedges[face.first_edge : face.first_edge + face.edge_count])
            for face in faces
        ) if packed_edge_scope == "bsp-all-exact" else (),
    )
    world_packed_refinement = {
        "policy": PACKED_AFFINE_REFINEMENT_POLICY, "scope": packed_edge_scope,
        "inserted_index_count": 0,
        "refined_face_count": 0, "maximum_face_vertices": 0, "faces": [],
        "rejected_nonintegral_st": [],
    }
    world_edge_refinement["packed_affine_refinement"] = world_packed_refinement
    for face_index in range(world_first_face, world_first_face + world_face_count):
        face = faces[face_index]
        source_indices: list[int] = []
        for edge_index in range(face.first_edge, face.first_edge + face.edge_count):
            surfedge = surfedges[edge_index]
            edge = edges[abs(surfedge)]
            vertex_index = edge[0] if surfedge >= 0 else edge[1]
            source_indices.append(vertex_index)

        emitted_indices = world_refined_contours[face_index - world_first_face]
        source_polygon = [vertices[vertex_index] for vertex_index in source_indices]
        emitted_polygon = [vertices[vertex_index] for vertex_index in emitted_indices]
        texture_record = texinfo[face.texinfo]
        source_texture_id = int(texture_record[8])
        world_face_texture_ids.append(packed_texture_ids.get(source_texture_id, 0xFF))
        if 0 <= source_texture_id < len(textures):
            coordinate_s, coordinate_t, _ = normalized_face_texture_coordinates(
                emitted_polygon,
                texture_record,
                textures[source_texture_id],
            )
        else:
            coordinate_s, coordinate_t = face_texture_coordinates(
                emitted_polygon, texture_record
            )
        emitted_st_q4 = []
        for s, t in zip(coordinate_s, coordinate_t, strict=True):
            s_q4 = round_half_away_from_zero(s * 16.0)
            t_q4 = round_half_away_from_zero(t * 16.0)
            if not (-0x8000 <= s_q4 <= 0x7FFF and -0x8000 <= t_q4 <= 0x7FFF):
                raise AssertionError(
                    f"face {face_index} texture coordinate exceeds signed Q4: {(s_q4, t_q4)}"
                )
            emitted_st_q4.append((s_q4, t_q4))
        emitted_indices, emitted_st_q4, packed_changes = refine_packed_face_coordinates(
            emitted_indices, emitted_st_q4,
            world_packed_candidates[face_index - world_first_face],
        )
        if len(emitted_indices) > 255:
            raise AssertionError(f"world face {face_index} refined polygon exceeds byte vertex count")
        if packed_changes["accepted"]:
            world_packed_refinement["faces"].append({
                "face": face_index - world_first_face, "insertions": packed_changes["accepted"],
            })
            world_packed_refinement["refined_face_count"] += 1
            world_packed_refinement["inserted_index_count"] += len(packed_changes["accepted"])
        for rejected in packed_changes["rejectedNonintegralST"]:
            world_packed_refinement["rejected_nonintegral_st"].append({
                "face": face_index - world_first_face, **rejected,
            })
        world_packed_refinement["maximum_face_vertices"] = max(
            world_packed_refinement["maximum_face_vertices"], len(emitted_indices)
        )
        coordinate_bank_records = ROM_BANK_BYTES // TEXTURE_COORD_RECORD_BYTES
        coordinate_bank_offset = len(world_indices) % coordinate_bank_records
        if coordinate_bank_offset + len(emitted_indices) > coordinate_bank_records:
            padding_records = coordinate_bank_records - coordinate_bank_offset
            world_indices.extend([0] * padding_records)
            world_texture_coordinates.extend(
                bytes(padding_records * TEXTURE_COORD_RECORD_BYTES)
            )
            world_face_stream_padding_records += padding_records

        first_index = len(world_indices)
        if first_index > 0xFFFF or first_index + len(emitted_indices) > 0x10000:
            raise AssertionError("full-world index stream exceeds uint16 addressing")
        # Preserve every source surfedge and face identity; exact boundary
        # junctions add indices only. Polygon-derived inputs retain the original
        # contour so planes, material/shading, colors and eligibility stay fixed.
        world_indices.extend(emitted_indices)
        for s_q4, t_q4 in emitted_st_q4:
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

        texture_name = texture_for_face(face)
        shading_record = material_record_for_face(face, source_polygon)
        world_shading_records.extend(struct.pack("<bbbB", *shading_record))
        drawable = (
            len(quantized_q2) >= 3
            and len(source_indices) <= 255
            and polygon_has_area(source_polygon)
            and polygon_has_area(quantized_q2)
            and texture_name is not None
        )
        if drawable:
            assert texture_name is not None
            if world_face_texture_ids[-1] == 0xFF:
                raise AssertionError(f'drawable world face {face_index} has no packed texture')
            world_texture_names.add(texture_name)
            # Retain the qualified legacy source colors for reference-renderer
            # audits. Runtime packet construction overwrites these two bytes
            # with the material/distance lookup result before rasterization.
            flat, dither = colors_for_face(face, source_polygon)
            try:
                cull = derive_world_cull_plane(quantized_q2)
            except ValueError as error:
                raise AssertionError(f"world face {face_index} cull proof failed: {error}") from error
            normal, distance = cull.normal, cull.distance
            flags = 0
            if cull.guarded:
                # A nonplanar Q2 boundary has no single geometric backface
                # plane. Project it and let its unchanged contour clip/raster.
                flags |= WORLD_FACE_FLAG_PLANE_CULL_GUARD
                world_plane_cull_guard_faces.add(face_index - world_first_face)
            else:
                assert cull.normal_shift is not None
                world_planar_cull_shifts[cull.normal_shift] = (
                    world_planar_cull_shifts.get(cull.normal_shift, 0) + 1
                )
            world_faces.extend(
                struct.pack(
                    "<HBBBB", first_index, len(emitted_indices), flat, dither, flags
                )
            )
            world_max_face_vertices = max(world_max_face_vertices, len(emitted_indices))
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
            world_faces.extend(
                struct.pack(
                    "<HBBBB",
                    first_index,
                    0,
                    0,
                    0,
                    WORLD_FACE_FLAG_NON_DRAWABLE,
                )
            )
            normal, distance = quantized_face_plane(quantized_q2)
            world_face_planes.extend(struct.pack("<bbbh", *normal, distance))

    if len(world_faces) != world_face_count * WORLD_FACE_RECORD_BYTES:
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
    total_refined_indices = (world_edge_refinement["inserted_index_count"]
                             + world_packed_refinement["inserted_index_count"])
    if (
        len(world_indices) - world_face_stream_padding_records
        != source_world_index_count + total_refined_indices
    ):
        raise AssertionError(
            f"full-world index stream lost source surfedges: "
            f"{len(world_indices)} - {world_face_stream_padding_records} != "
            f"{source_world_index_count} + {total_refined_indices}"
        )
    if (
        len(world_texture_coordinates)
        != len(world_indices) * TEXTURE_COORD_RECORD_BYTES
    ):
        raise AssertionError("parallel world face streams lost source surfedges")

    packed_drawable_faces = validate_drawable_face_colors(
        bytes(packed_faces), label="bounded spawn packet"
    )
    if packed_drawable_faces != len(packed_faces) // FACE_RECORD_BYTES:
        raise AssertionError("bounded spawn packet contains a nondrawable face")
    if (
        validate_drawable_face_colors(
            bytes(world_faces),
            label="full world",
            record_bytes=WORLD_FACE_RECORD_BYTES,
        )
        != world_drawable_faces
    ):
        raise AssertionError("full-world drawable-face count is inconsistent")

    (
        world_node_parents,
        world_face_owners,
        world_reachable_node_count,
        world_max_node_depth,
    ) = (
        build_world_node_topology(nodes, root, world_first_face, world_face_count)
    )
    # Quake appends hull-0 nodes for brush submodels after the world tree.
    # They are unreachable from model 0's root and have their own generated
    # brush representation, so exclude that suffix from the runtime world BSP.
    world_nodes = nodes[:world_reachable_node_count]
    world_node_bytes = b"".join(
        struct.pack(
            "<HhhHH",
            node.plane,
            node.children[0],
            node.children[1],
            node.first_face,
            node.face_count,
        )
        for node in world_nodes
    )
    world_node_parent_bytes = b"".join(
        struct.pack("<H", parent) for parent in world_node_parents
    )
    world_face_owner_bytes = b"".join(
        struct.pack("<H", owner) for owner in world_face_owners
    )
    world_plane_records = tuple(
        quantized_bsp_plane(plane, world_origin) for plane in planes
    )
    world_plane_bytes = b"".join(
        struct.pack("<bbbh", *normal, distance)
        for normal, distance in world_plane_records
    )
    world_leaf_bytes = b"".join(
        struct.pack(
            "<iHH", leaf.vis_offset, leaf.first_mark_surface, leaf.mark_surface_count
        )
        for leaf in leaves
    )
    # Only the world model's leaves participate in fly-camera traversal.
    # Modern QBSPs may append private solid leaves for brush submodels after
    # model 0's visleaf range; those leaves are unreachable from `root` and do
    # not change the packed collision field.
    world_leaf_count = vis_leaf_count + 1
    if world_leaf_count > len(leaves):
        raise AssertionError(
            f"world model declares {world_leaf_count} leaves, BSP has {len(leaves)}"
        )
    solid_world_leaf_indices = [
        index
        for index, leaf in enumerate(leaves[:world_leaf_count])
        if leaf.contents == -2
    ]
    if solid_world_leaf_indices != [0]:
        raise AssertionError(
            f"packed fly collision requires unique solid leaf zero, got "
            f"{solid_world_leaf_indices} within the world model"
        )
    collision_outputs, collision_report = build_collision_assets(
        world_nodes,
        world_plane_records,
        root,
        world_coordinate_min,
        world_coordinate_max,
        node_payload=world_node_bytes,
        plane_payload=world_plane_bytes,
    )
    world_marksurface_bytes = b"".join(
        struct.pack("<H", face_index) for face_index in marksurfaces
    )
    if len(world_q2_vertices) * 4 > ROM_BANK_BYTES:
        # Unreferenced and exactly coincident Q2 vertices need no ROM slot.
        compact = []
        by_point = {}
        by_index = {}
        for index in sorted(set(world_indices)):
            point = world_q2_vertices[index]
            if point not in by_point:
                by_point[point] = len(compact)
                compact.append(point)
            by_index[index] = by_point[point]
        world_indices = [by_index[index] for index in world_indices]
        world_q2_vertices = compact
        if len(compact) * 4 > ROM_BANK_BYTES:
            raise ValueError("referenced world vertices exceed one ROM halfbank")
    world_vertex_bytes = b"".join(
        pack_q2_world_vertex(vertex) for vertex in world_q2_vertices
    )
    if (
        len(world_texture_coordinates)
        != len(world_indices) * TEXTURE_COORD_RECORD_BYTES
    ):
        raise AssertionError("parallel world index/texture-coordinate streams diverged")
    world_index_bytes = b"".join(struct.pack("<H", index) for index in world_indices)
    world_index_chunks = (
        world_index_bytes[:ROM_BANK_BYTES],
        world_index_bytes[ROM_BANK_BYTES:],
    )
    coordinate_bank_count = layout.coordinate_count
    coordinate_first_bank = layout.coordinate_first
    raw_world_texture_coordinate_chunks = tuple(
        bytes(world_texture_coordinates[offset : offset + ROM_BANK_BYTES])
        for offset in range(0, len(world_texture_coordinates), ROM_BANK_BYTES)
    )
    if len(raw_world_texture_coordinate_chunks) > coordinate_bank_count:
        raise AssertionError(
            "world texture coordinates exceed the fixed ROM bank reservation: "
            f"{len(raw_world_texture_coordinate_chunks)} > "
            f"{coordinate_bank_count}"
        )
    world_texture_coordinate_chunks = (
        *raw_world_texture_coordinate_chunks,
        *(
            b""
            for _ in range(
                coordinate_bank_count - len(raw_world_texture_coordinate_chunks)
            )
        ),
    )

    texture_payloads = tuple(
        textures[source_id].pixels for source_id in referenced_texture_ids
    )
    texture_pixels = b"".join(texture_payloads)
    texture_pixel_chunks, texture_placements = pack_texture_bank_images(
        texture_payloads, bank_count=layout.texture_count
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
        if texture.name.startswith("*"):
            flags |= TEXTURE_FLAG_TURBULENT
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

    if require_world_geometry_from is not None:
        require_world_geometry(require_world_geometry_from, {
            'QuakeBSPWorldVertices.bin': world_vertex_bytes,
            'QuakeBSPWorldFaces.bin': bytes(world_faces),
            'QuakeBSPWorldFacePlanes.bin': bytes(world_face_planes),
            'QuakeBSPWorldNodes.bin': world_node_bytes,
            'QuakeBSPWorldPlanes.bin': world_plane_bytes,
            'QuakeBSPWorldLeaves.bin': world_leaf_bytes,
            **{f'QuakeBSPWorldIndices{i}.bin': value for i, value in enumerate(world_index_chunks)},
            **{f'QuakeBSPWorldTextureCoordinates{i}.bin': value
               for i, value in enumerate(world_texture_coordinate_chunks)},
        }, origin=world_origin, scale=WORLD_SCALE)

    # Precompute one directly consumable face-visibility row for every leaf in
    # the world hull.  This intentionally duplicates Quake's leaf-to-face
    # expansion offline: the GSU only has to resolve a leaf and inflate the
    # bytes, avoiding thousands of random leaf/marksurface ROM reads per frame.
    world_face_bitset_bytes = (world_face_count + 7) // 8
    pvs_guard_masks: dict[int, int] = {}
    for face_index in sorted(world_pvs_quantization_guard_faces):
        byte_offset = face_index >> 3
        pvs_guard_masks[byte_offset] = pvs_guard_masks.get(byte_offset, 0) | (
            1 << (face_index & 7)
        )
    # The native guard loop has a nonempty ABI. Admitting one extra face is
    # conservative; for the all-visible fallback this bit is already set.
    if not pvs_guard_masks:
        pvs_guard_masks[0] = 1
        world_pvs_quantization_guard_faces.add(0)
    pvs_guard_bytes = b"".join(
        struct.pack("<HB", byte_offset, mask)
        for byte_offset, mask in sorted(pvs_guard_masks.items())
    )
    if len(pvs_guard_bytes) != len(pvs_guard_masks) * WORLD_PVS_GUARD_RECORD_BYTES:
        raise AssertionError("face-PVS guard records are inconsistently packed")
    source_pvs_rows: list[bytes] = []
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
        source_pvs_rows.append(bytes(face_bits))

    playable_camera_step = 4 if target.get("gameplay") in ("e1m1-button-door", "basic", "start-hub") else None
    standalone_fly = target.get("standaloneFly", False)
    # Retain authored portal VIS and union exact source/packed leaf contacts.
    from snes_tooling.quake.quake_pvs_leaf_union import conservative_rows
    conservative_pvs, pvs_leaf_union = conservative_rows(source_pvs_rows,
        planes=planes, packed_planes=world_plane_records, nodes=world_nodes,
        leaves=leaves, root=root, origin=world_origin, scale=WORLD_SCALE,
        camera_step=None if standalone_fly else playable_camera_step, closed_contacts=standalone_fly)
    guard_bits = sum(1 << face for face in world_pvs_quantization_guard_faces)
    pvs_rows = [(zero_run_encode(row), (int.from_bytes(row, 'little') | guard_bits).bit_count())
                for row in conservative_pvs]

    from snes_tooling.quake.packed_visibility.packing import pack_rows
    packed_pvs = pack_rows(pvs_rows, guard_bytes=len(pvs_guard_bytes),
        first_bank=WORLD_PVS_FIRST_GSU_ROM_BANK, bank_count=layout.pvs_count)
    pvs_chunks = packed_pvs['chunks']
    pvs_directory = packed_pvs['directory']
    if len(pvs_directory) != (vis_leaf_count + 1) * WORLD_PVS_DIRECTORY_RECORD_BYTES:
        raise AssertionError("face-PVS directory lost a world leaf")
    pvs_chunk_count = packed_pvs['chunkCount']
    pvs_directory_address = packed_pvs['directoryAddress']
    pvs_guard_address = packed_pvs['guardAddress']

    distance_lookup = material_distance_lut()
    shading_lookup = material_shading_table()
    world_shading_bytes = (
        bytes(world_shading_records) + distance_lookup + shading_lookup
    )
    if len(world_shading_bytes) > ROM_BANK_BYTES:
        raise AssertionError("full-world shading asset exceeds one 32 KiB ROM bank")

    world_info: dict[str, object] = {
        "playable_camera_position_units": 16 if standalone_fly else playable_camera_step,
        "root_node": root,
        "first_face": world_first_face,
        "origin": world_origin,
        "coordinate_min": world_coordinate_min,
        "coordinate_max": world_coordinate_max,
        "vertex_count": len(world_q2_vertices),
        "index_count": len(world_indices),
        "face_count": world_face_count,
        "max_face_vertices": world_max_face_vertices,
        "drawable_face_count": world_drawable_faces,
        "nondrawable_face_count": world_face_count - world_drawable_faces,
        "plane_cull_guard_face_count": len(world_plane_cull_guard_faces),
        "node_count": len(world_nodes),
        "reachable_node_count": world_reachable_node_count,
        "max_node_depth": world_max_node_depth,
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
        "face_stream_padding_records": world_face_stream_padding_records,
        "texture_coordinate_0_bytes": len(world_texture_coordinate_chunks[0]),
        "texture_coordinate_1_bytes": len(world_texture_coordinate_chunks[1]),
        "texture_coordinate_2_bytes": len(world_texture_coordinate_chunks[2]),
        "texture_coordinate_3_bytes": len(world_texture_coordinate_chunks[3]) if coordinate_bank_count == 4 else 0,
        "texture_coordinate_first_bank": coordinate_first_bank,
        "texture_aux_prefix_bytes": len(world_texture_coordinate_chunks[2]) if selected_demo is not None else 0,
        "face_texture_id_bytes": len(world_face_texture_ids),
        "texture_directory_bytes": len(texture_directory),
        "texture_pixel_bytes": len(texture_pixels),
        "texture_pixel_chunk_count": len(texture_pixel_chunks),
        "lightmap_directory_bytes": len(world_lightmap_directory),
        "lightmap_chunk_count": world_lightmap_chunk_count,
        "lightmap_first_bank": layout.lightmap_first,
        "lightmap_directory_bank": layout.lightmap_directory_gsu_bank,
        "lightmap_directory_address": layout.lightmap_directory_address,
        "lightmap_unpack_bank": layout.unpack_code,
        "lightmap_logical_sample_count": world_lightmap_packing.logical_sample_count,
        "lightmap_packed_bytes": sum(len(chunk) for chunk in world_lightmap_chunks),
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
        "pvs_directory_rom_bank": WORLD_PVS_FIRST_GSU_ROM_BANK + 2,
        "pvs_directory_rom_address": pvs_directory_address,
        "pvs_guard_rom_address": pvs_guard_address,
        "pvs_guard_record_count": len(pvs_guard_masks),
        "pvs_guard_bytes": len(pvs_guard_bytes),
        "pvs_chunk_count": pvs_chunk_count,
        "face_owner_bank": layout.face_owner_bank,
        "pvs_compressed_bytes": sum(len(chunk) for chunk in pvs_chunks),
        "demo_playback_supported": int(selected_demo is not None),
        "initial_eye_q8": tuple(round((start[i] + (DEFAULT_VIEWHEIGHT if i == 2 else 0) - world_origin[i]) / WORLD_SCALE * 256) & 0xFFFF for i in range(3)),
        "demo_pose_count": len(playback.demo_records),
        "demo_track_bytes": len(playback.demo_track),
        "demo_timing_bytes": len(playback.demo_timing),
        "demo_duration_ticks": playback.demo_ticks[-1],
        "demo_precise_pose_count": len(playback.demo_precise_records),
        "demo_precise_track_bytes": len(playback.demo_precise_track),
        "demo_precise_timing_bytes": len(playback.demo_precise_timing),
        "demo_precise_duration_ticks": playback.demo_precise_ticks[-1],
        "demo_precise_sample_rate_hz": playback_sample_rate_hz,
        "demo_ordered_pose_stride": demo_ordered_pose_stride,
        "demo_step_pose_count": len(playback.demo_step_indices),
        "demo_verify_near_pose": playback.demo_verify_near_pose,
        "demo_verify_far_pose": playback.demo_verify_far_pose,
        "start_coordinate": start_coordinate,
        "collision_payload_bytes": collision_report["storage"]["payloadBytes"],
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
            (
                0
                if depth_q4 < (NEAR_DEPTH << DEPTH_TABLE_FRACTION_BITS)
                else round(RECIPROCAL_NUMERATOR / depth_q4)
            ),
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
        Path("QuakeBSPDemoTrack.bin"): playback.demo_track,
        Path("QuakeBSPDemoTiming.bin"): playback.demo_timing,
        Path("QuakeBSPDemoPrecise.bin"): playback.demo_precise_track,
        Path("QuakeBSPDemoPreciseTiming.bin"): playback.demo_precise_timing,
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
    outputs.update(collision_outputs)
    if selected_demo is None and target.get("gameplay") in ("e1m1-button-door", "basic", "start-hub"):
        from snes_tooling.quake.quake_bsp_assets import stock_orientation_tilemap
        from snes_tooling.quake.quake_walk_hull import player_hull_outputs, shotgun_hull_outputs
        if target["gameplay"] in ("basic", "start-hub"):
            from snes_tooling.quake.quake_walk_hull import static_level_hull_outputs
            selected = None
            if target["gameplay"] == "start-hub":
                from snes_tooling.quake.quake_start_hub import hub_static_models
                selected = hub_static_models(parse_entities(lump_data(bsp, lumps, LUMP_ENTITIES)))
            name = Path(target["map"]).stem
            movers = dict(e1m2=name == "e1m2", e1m3=name == "e1m3")
            walk_assets, walk_include = static_level_hull_outputs(
                bsp, world_origin, point=False, static_models=selected, **movers)
            shot_assets, shot_include = static_level_hull_outputs(
                bsp, world_origin, point=True, static_models=selected, **movers)
        else:
            from snes_tooling.quake.quakec_explobox import spawn_explobox
            from snes_tooling.quake.quakec_gameplay import Program
            from snes_tooling.quake.quakec_grunt import GruntReference
            from snes_tooling.quake.quakec_shell_pickups import floor_drop
            world_models = tuple(struct.iter_unpack("<9f7i", lump_data(bsp, lumps, 14)))
            drop = floor_drop(bsp, world_models[0][10], supporting_roots=(world_models[3][10], world_models[4][10]))
            vm = GruntReference(Program(archive.read("progs.dat")), world_models, archive, drop)
            box = spawn_explobox(vm, entities, 1)
            walk_assets, walk_include = player_hull_outputs(bsp, world_origin, exit_movers=True, explobox=box)
            shot_assets, shot_include = shotgun_hull_outputs(bsp, world_origin, exit_movers=True)
        outputs.update(walk_assets)
        outputs.update(shot_assets)
        outputs[Path("QuakeBSPScene.i")] += walk_include + shot_include
        for kind in ("", "Texture"):
            raw_tilemap = outputs[Path(f"QuakeBSP{kind}Tilemap.bin")]
            outputs[Path(f"QuakeBSP{kind}DisplayTilemap.bin")] = stock_orientation_tilemap(raw_tilemap)
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
    if coordinate_bank_count == 4:
        outputs[Path("QuakeBSPWorldTextureCoordinates3.bin")] = world_texture_coordinate_chunks[3]
    metadata: dict[str, object] = {
        "source": {
            "pak_path_hint": QUAKE_PAK_PATH_HINT,
            "pak_entry": map_entry,
            "pak_sha256": hashlib.sha256(pak_bytes).hexdigest(),
            "bsp_sha256": bsp_sha256,
            "bsp_version": BSP_VERSION,
            "palette_entry": PALETTE_ENTRY,
            "palette_sha256": hashlib.sha256(palette_bytes).hexdigest(),
            "colormap_entry": COLORMAP_ENTRY,
            "colormap_sha256": hashlib.sha256(colormap_bytes).hexdigest(),
            "lighting_bytes": len(lighting),
            "lighting_sha256": hashlib.sha256(lighting).hexdigest(),
            "demo_entry": (selected_demo.label if selected_demo is not None else None),
            "demo_source": (selected_demo.source.kind if selected_demo is not None else None),
            "demo_locator": (selected_demo.source.locator if selected_demo is not None else None),
            "demo_sha256": (selected_demo.sha256 if selected_demo is not None else None),
        },
        "selection": {
            "sky_enabled": sky_enabled,
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
            "fly_collision": collision_report,
            "edge_refinement": world_edge_refinement,
            "packing": {
                "vertex_count": len(world_q2_vertices),
                "index_count": len(world_indices),
                "face_count": world_face_count,
                "drawable_face_count": world_drawable_faces,
                "nondrawable_face_count": world_face_count - world_drawable_faces,
                "plane_cull_guard_face_count": len(world_plane_cull_guard_faces),
                "node_count": len(world_nodes),
                "plane_count": len(planes),
                "leaf_count": len(leaves),
                "marksurface_count": len(marksurfaces),
                "visibility_bytes": len(visibility),
                "vertex_record_bytes": 4,
                "vertex_record_format": "<bbbB; Q2 xyz = signed base*4 + packed 2-bit residual",
                "index_record_bytes": 2,
                "index_record_format": "<H",
                "face_record_bytes": WORLD_FACE_RECORD_BYTES,
                "face_record_format": "<HBBBB",
                "face_plane_record_bytes": FACE_PLANE_RECORD_BYTES,
                "face_plane_record_format": "<bbbh",
                "face_plane_source": (
                    "culling-only: exact-Q2 planar front-halfspace support with a "
                    "narrow-contour raster margin and minimum wrap-free normal "
                    "downscale; guarded nonplanar faces "
                    "retain their original Q6 plane; collapsed faces stay rejected"
                ),
                "face_plane_policy": {
                    "policy": WORLD_CULL_POLICY,
                    "camera_q2_domain": list(CAMERA_Q2_DOMAIN),
                    "normal_rounding": "nearest-even(original Q6 normal / 2**shift)",
                    "distance_rule": "ceil(max(n.camera) over raster front halfspace intersect camera box)",
                    "raster_front_margin": "one Q2 coordinate envelope for contours at most two Q2 units wide",
                    "signed16_proof": "minimum shift whose complete final n.camera-D range fits signed16; modular intermediate words preserve the final result",
                    "planar_face_count": sum(world_planar_cull_shifts.values()),
                    "planar_normal_shift_counts": {
                        str(shift): count for shift, count in sorted(world_planar_cull_shifts.items())
                    },
                },
                "face_flag_bits": {
                    "non_drawable": WORLD_FACE_FLAG_NON_DRAWABLE,
                    "plane_cull_guard": WORLD_FACE_FLAG_PLANE_CULL_GUARD,
                },
                "plane_cull_guard": {
                    "policy": (
                        "bypass plane-only backface rejection exactly for nonplanar "
                        "drawable Q2 boundaries; planar faces use a proved conservative cull plane"
                    ),
                    "face_count": len(world_plane_cull_guard_faces),
                    "face_ids": sorted(world_plane_cull_guard_faces),
                },
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
                    "face_boundary_padding_records": world_face_stream_padding_records,
                    "face_boundary_policy": (
                        "pad parallel index and texture-coordinate streams so one "
                        "face never crosses a 32 KiB coordinate ROM bank"
                    ),
                    "coordinate_chunks": [
                        {
                            "file": f"QuakeBSPWorldTextureCoordinates{index}.bin",
                            "bytes": len(chunk),
                            "gsu_rom_bank": coordinate_first_bank + index,
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
                        "turbulent": TEXTURE_FLAG_TURBULENT,
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
                    "lightmaps": {
                        "directory_file": "QuakeBSPWorldLightmapDirectory.bin",
                        "directory_record_bytes": LIGHTMAP_DIRECTORY_RECORD_BYTES,
                        "directory_bytes": len(world_lightmap_directory),
                        "sample_file_pattern": (
                            "QuakeBSPWorldLightmapSamples"
                            f"{{0..{layout.lightmap_count - 1}}}.bin"
                        ),
                        "logical_sample_count": (
                            world_lightmap_packing.logical_sample_count
                        ),
                        "packed_bytes": sum(
                            len(chunk) for chunk in world_lightmap_chunks
                        ),
                        "packed_padding_bits": world_lightmap_packing.padding_bits,
                        "unique_face_payload_count": (
                            world_lightmap_packing.unique_payload_count
                        ),
                        "carrier_sample_count": (
                            world_lightmap_packing.carrier_sample_count
                        ),
                        "alignment_padding_samples": (
                            world_lightmap_packing.alignment_padding_samples
                        ),
                        "stored_sample_count": (
                            world_lightmap_packing.carrier_sample_count
                            + world_lightmap_packing.alignment_padding_samples
                        ),
                        "deduplicated_sample_count": (
                            world_lightmap_packing.logical_sample_count
                            - world_lightmap_packing.carrier_sample_count
                        ),
                        "logical_samples_sha256": (
                            world_lightmap_packing.logical_sha256
                        ),
                        "packed_samples_sha256": (
                            world_lightmap_packing.packed_sha256
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
                                "gsu_rom_bank": layout.lightmap_first
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
                        "sample_format": (
                            "four little-endian six-bit colormap levels per "
                            "three bytes; every directory address is "
                            "four-sample group aligned"
                        ),
                        "static_style_scale_8_8": QUAKE_NEUTRAL_LIGHT_STYLE_SCALE,
                        "interpolation_fraction_bits": 4,
                        "colormap_file": "QuakeBSPLightmapColormap.bin",
                        "colormap_level_zero_file": (
                            "QuakeBSPLightmapLevelZeroColormap.bin"
                        ),
                        "colormap_approximation": (
                            "none; source levels 0..63 use their original Quake rows"
                        ),
                    },
                },
                "node_record_bytes": WORLD_NODE_RECORD_BYTES,
                "node_record_format": "<HhhHH",
                "node_parent_record_bytes": WORLD_NODE_PARENT_RECORD_BYTES,
                "node_parent_record_format": "<H; $ffff for root",
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
                    "directory_gsu_rom_bank": WORLD_PVS_FIRST_GSU_ROM_BANK + 2,
                    "directory_gsu_rom_address": pvs_directory_address,
                    "directory_record_bytes": WORLD_PVS_DIRECTORY_RECORD_BYTES,
                    "directory_record_format": "<HHHBB",
                    "row_count": len(pvs_rows),
                    "decoded_row_bytes": world_face_bitset_bytes,
                    "encoding": "zero bytes encoded as 0,count; nonzero bytes literal",
                    "face_count_semantics": "unique BSP world-model face identities",
                    "camera_leaf_union": pvs_leaf_union,
                    "encoded_contour_visibility": {"status": "not-run", "policy": "original-bsp-pvs"},
                    "unique_encoded_rows": packed_pvs['uniqueRows'],
                    "shared_row_bytes_saved": packed_pvs['savedBytes'],
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
                        "gsu_rom_bank": WORLD_PVS_FIRST_GSU_ROM_BANK + 2,
                        "gsu_rom_address": pvs_guard_address,
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
        "demo": ({
            "entry": (selected_demo.label if selected_demo is not None else None),
            "source": (selected_demo.source.kind if selected_demo is not None else None),
            "locator": (selected_demo.source.locator if selected_demo is not None else None),
            "map_entry": map_entry,
            "sha256": (selected_demo.sha256 if selected_demo is not None else None),
            "source_bytes": len(demo),
            "forced_cd_track": playback.forced_track,
            "source_camera_samples": len(playback.demo_samples),
            "sample_retention": "all reconstructed source camera samples",
            "camera_origin_semantics": (
                "view-entity origin plus protocol-15 svc_clientdata view height"
            ),
            "default_view_height": DEFAULT_VIEWHEIGHT,
            "packed_view_height_values": sorted(set(playback.demo_view_heights)),
            "track_pose_count": len(playback.demo_records),
            "distinct_packed_pose_count": len(set(playback.demo_records)),
            "consecutive_repeated_pose_count": sum(
                left == right for left, right in zip(playback.demo_records, playback.demo_records[1:])
            ),
            "track_record_bytes": DEMO_TRACK_RECORD_BYTES,
            "track_bytes": len(playback.demo_track),
            "timing_record_bytes": DEMO_TIMING_RECORD_BYTES,
            "timing_bytes": len(playback.demo_timing),
            "precise_track_record_bytes": DEMO_PRECISE_TRACK_RECORD_BYTES,
            "precise_track_bytes": len(playback.demo_precise_track),
            "precise_track_pose_count": len(playback.demo_precise_records),
            "precise_track_sample_rate_hz": playback_sample_rate_hz,
            "precise_timing_record_bytes": DEMO_TIMING_RECORD_BYTES,
            "precise_timing_bytes": len(playback.demo_precise_timing),
            "precise_duration_ticks": playback.demo_precise_ticks[-1],
            "precise_timing_quantization": (
                "round(n * ntsc_frames_per_second / sample_rate_hz)"
            ),
            "precise_track_duration_seconds": (
                len(playback.demo_precise_records) / playback_sample_rate_hz
            ),
            "precise_track_distinct_source_samples": len(set(playback.precise_source_indices)),
            "precise_track_sampling": CAMERA_SAMPLING_CONTRACT,
            "scene_sampling": SCENE_SAMPLING_CONTRACT,
            "precise_track_repeated_poses": sum(
                a == b for a, b in zip(playback.demo_precise_records, playback.demo_precise_records[1:])
            ),
            "precise_track_encoding": (
                "absolute signed Q3 xyz; uint16-turn yaw/pitch; roll omitted "
                "because every source sample is zero"
            ),
            "step_sample_rate_hz": DEMO_STEP_SAMPLE_RATE_HZ,
            "ordered_pose_stride": demo_ordered_pose_stride,
            "step_pose_count": len(playback.demo_step_indices),
            "step_pose_indices": list(playback.demo_step_indices),
            "step_sampling": (
                "canonical sample-rate indices n*orderedPoseStride; "
                "no second camera stream"
            ),
            "first_source_record": playback.demo_source_records[0],
            "last_source_record": playback.demo_source_records[-1],
            "first_server_time": playback.demo_source_times[0],
            "last_server_time": playback.demo_source_times[-1],
            "duration_seconds": playback.demo_source_times[-1] - playback.demo_source_times[0],
            "ntsc_frames_per_second": NTSC_FRAMES_PER_SECOND,
            "duration_ticks": playback.demo_ticks[-1],
            "distinct_timing_ticks": len(set(playback.demo_ticks)),
            "same_tick_sample_count": len(playback.demo_ticks) - len(set(playback.demo_ticks)),
            "timing_quantization": (
                "round((svc_time - first_server_time) * ntsc_frames_per_second)"
            ),
            "pose_timing": [
                {
                    "track_pose": index,
                    "source_record": source_record,
                    "server_time": server_time,
                    "relative_seconds": server_time - playback.first_demo_time,
                    "ntsc_tick": tick,
                }
                for index, (source_record, server_time, tick) in enumerate(
                    zip(playback.demo_source_records, playback.demo_source_times, playback.demo_ticks, strict=True)
                )
            ],
            "distinct_leaf_count": len(playback.demo_leaf_ids),
            "coordinate_encoding": "map-centered signed int8 at 16 Quake units",
            "angle_encoding": "32-step yaw; inverted signed 32-step pitch",
            "playback": {
                "ordered": (
                    "advance one canonical 3 Hz source-time pose per staged frame"
                ),
                "realtime_snes": (
                    "publish only the newest canonical configured-rate pose due at the "
                    "monotonic NTSC tick; skip obsolete due poses"
                ),
                "realtime_cpp": (
                    "select floor(elapsed_seconds * sampleRateHz) from the same stream"
                ),
                "interpolation_cpp": "none (offline interpolated camera poses)",
            },
        } if selected_demo is not None else {"enabled": False, "map_entry": map_entry}),
        **({"target": target} if selected_demo is None else {}),
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
                "BSP-order painter with projective lightmapped 8bpp level-0 miptex indices"
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pak", type=Path)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    parser.add_argument('--require-world-geometry', type=Path,
                        help='require matching frozen world geometry before the visibility bake')
    parser.add_argument("--packed-edge-scope", choices=("eligible-world", "bsp-all-exact"),
                        default="eligible-world")
    args = parser.parse_args(argv)
    started = time.perf_counter()
    try:
        pak_path = locate_quake_pak(args.pak)
        outputs, metadata = generate(pak_path, config_path=args.config,
                                     packed_edge_scope=args.packed_edge_scope,
                                     require_world_geometry_from=args.require_world_geometry)
        write_or_check(outputs, args.output, args.check)
    except BaseException:
        print(
            f"SNES Quake asset generation failed after "
            f"{time.perf_counter() - started:.3f}s",
            file=sys.stderr,
        )
        raise
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
        f"{packing['vertex_count']} vertices, and {packing['index_count']} indices; "
        f"elapsed={time.perf_counter() - started:.3f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
