"""Build planar Quake MDL billboards and compact demo entity rows."""

from __future__ import annotations

import hashlib
import math
import struct
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from workspace_paths import shared_tools_root
from typing import Any, Iterable

import numpy as np

TOOLS = Path(__file__).resolve().parent
SHARED_TOOLS = shared_tools_root(__file__)
for dependency in (TOOLS, SHARED_TOOLS):
    if str(dependency) not in sys.path:
        sys.path.insert(0, str(dependency))

import generate_quake_bsp as bsp_tools  # noqa: E402
import quake_assets  # noqa: E402
from quake_brush_replay import (  # noqa: E402
    extract_canonical_brush_replay,
)
from quake_demo import (  # noqa: E402
    CameraEntitySample,
    EntityState,
    decode_camera_entity_track,
    sample_newest_due_indices,
)
from quake_alias_projection import coherent_axis_q7  # noqa: E402
from quake_alias_animation import (  # noqa: E402
    EF_ROTATE, FLY_ROTATE_SENTINEL, ROTATION_BASES_BYTES, mdl_yaw, rotation_phase_q16,
)
from quake_alias_format import (  # noqa: E402
    FLY_DIRECTIONAL_MASK,
    FLY_DIRECTIONAL_TAG,
    FLY_FACING_RECORD,
    GROUP_HEADER,
    HEADER,
    MAGIC,
    ROW_DIRECTORY,
    SPRITE_DIRECTORY,
    STATE_RECORD,
    VERSION,
    render_assembly,
    render_include,
)
from quake_alias_packing import (  # noqa: E402,F401
    FIRST_PHYSICAL_HALFBANK,
    HALFBANK_BYTES,
    MAX_PHYSICAL_HALFBANKS,
    STORAGE_PHYSICAL_HALFBANKS,
    HalfbankPacker,
    Location,
    cpu_load_address,
    gsu_location,
)
from quake_alias_residency import (  # noqa: E402
    runtime_sprite_usage,
    usage_metadata,
)
from quake_rom_config import (  # noqa: E402
    DEFAULT_CONFIG,
    MAX_ALIAS_HALFBANK_COUNT,
    configured_alias_sprites,
    configured_mesen_target,
    configured_playback_sample_rate,
    resolve_configured_demo,
)
from host_resources import physical_core_count  # noqa: E402
from quake_billboard_assets import (  # noqa: E402,F401
    BillboardModel,
    BillboardSprite,
    SprModel,
    SpriteRaster,
    SpriteOrientation,
    VIEW_COUNT,
    billboard_frame_count,
    canonicalize_sprite_rasters,
    billboard_frame_name,
    billboard_model_kind,
    build_model_precache_inventory,
    nearest_view,
    parse_spr,
    rasterize_billboard,
    rasterize_front_billboard,
    rasterize_model_variants,
    rasterize_spr_billboard,
    resolved_frame,
    resolved_spr_frame,
    spr_subframe,
    summarize_mdl_raster_fidelity,
)

assert MAX_PHYSICAL_HALFBANKS == MAX_ALIAS_HALFBANK_COUNT
FLY_ROW_COUNT = VIEW_COUNT
MAX_SPRITE_ID = FLY_DIRECTIONAL_MASK
PARALLEL_VARIANT_THRESHOLD = 128
ANGLE_SIN_Q6 = tuple(
    round(math.sin(index * math.tau / 32.0) * 64) for index in range(32)
)
ANGLE_COS_Q6 = tuple(
    round(math.cos(index * math.tau / 32.0) * 64) for index in range(32)
)


@dataclass(frozen=True, slots=True)
class AliasState:
    entity: int
    sprite: int
    model_index: int
    origin_q2: tuple[int, int, int]
    source_origin: tuple[float, float, float]
    leaf: int
    directional_base_sprite: int | None = None
    yaw_sin_q6: int = 0
    yaw_cos_q6: int = 0

    def packed(self) -> bytes:
        encoded_sprite = self.sprite
        if self.directional_base_sprite is not None:
            if not 0 <= self.directional_base_sprite <= FLY_DIRECTIONAL_MASK - 7:
                raise ValueError(
                    "directional fly sprite range escapes the tagged u16 key"
                )
            encoded_sprite = self.directional_base_sprite | FLY_DIRECTIONAL_TAG
        return STATE_RECORD.pack(encoded_sprite, *self.origin_q2)

    @property
    def sprite_id(self) -> int:
        return self.sprite


@dataclass(frozen=True, slots=True)
class AliasGroup:
    leaf: int
    parent: int
    tokens: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class AliasRow:
    dynamic_states: tuple[AliasState, ...]
    groups: tuple[AliasGroup, ...]
    culled_tokens: int = 0


@dataclass(frozen=True, slots=True)
class SpatialBsp:
    planes: tuple[tuple[object, ...], ...]
    nodes: tuple[bsp_tools.Node, ...]
    leaves: tuple[bsp_tools.Leaf, ...]
    visibility: bytes
    root: int
    vis_leaf_count: int
    world_origin: tuple[float, float, float]
    leaf_parents: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class AliasAssetBuild:
    chunks: tuple[bytes, ...]
    include: bytes
    assembly: bytes
    metadata: dict[str, Any]


def _parse_spatial_bsp(data: bytes) -> SpatialBsp:
    lumps = bsp_tools.lump_ranges(data)
    planes = tuple(
        bsp_tools.unpack_records(
            bsp_tools.lump_data(data, lumps, bsp_tools.LUMP_PLANES), "<ffffi"
        )
    )
    node_records = bsp_tools.unpack_records(
        bsp_tools.lump_data(data, lumps, bsp_tools.LUMP_NODES), "<ihh6hHH"
    )
    nodes = tuple(
        bsp_tools.Node(record[0], (record[1], record[2]), record[9], record[10])
        for record in node_records
    )
    leaf_records = bsp_tools.unpack_records(
        bsp_tools.lump_data(data, lumps, bsp_tools.LUMP_LEAVES), "<ii6hHH4B"
    )
    leaves = tuple(
        bsp_tools.Leaf(record[0], record[1], record[8], record[9])
        for record in leaf_records
    )
    models = bsp_tools.unpack_records(
        bsp_tools.lump_data(data, lumps, bsp_tools.LUMP_MODELS), "<9f7i"
    )
    world = models[0]
    world_origin = tuple(
        (float(world[axis]) + float(world[axis + 3])) * 0.5 for axis in range(3)
    )
    root = int(world[9])
    leaf_parents = [-1] * len(leaves)
    visited: set[int] = set()

    def visit(node_index: int) -> None:
        if node_index < 0:
            return
        if node_index in visited:
            raise ValueError("BSP node graph is not a tree")
        visited.add(node_index)
        for child in nodes[node_index].children:
            if child < 0:
                leaf = -child - 1
                if not 0 <= leaf < len(leaves):
                    raise ValueError("BSP leaf has an invalid parent reference")
                # Solid leaf zero is shared; first-parent retention also makes
                # malformed duplicate non-solid leaves deterministic.
                if leaf_parents[leaf] < 0:
                    leaf_parents[leaf] = node_index
            else:
                visit(child)

    visit(root)
    return SpatialBsp(
        planes,
        nodes,
        leaves,
        bsp_tools.lump_data(data, lumps, bsp_tools.LUMP_VISIBILITY),
        root,
        int(world[13]),
        world_origin,  # type: ignore[arg-type]
        tuple(leaf_parents),
    )


def _locate_leaf(point: tuple[float, float, float], bsp: SpatialBsp) -> int:
    return bsp_tools.locate_leaf(point, list(bsp.nodes), list(bsp.planes), bsp.root)


def _visible_leaves(camera: tuple[float, float, float], bsp: SpatialBsp) -> set[int]:
    leaf = _locate_leaf(camera, bsp)
    if not 0 <= leaf < len(bsp.leaves):
        raise ValueError("camera resolves outside the BSP leaf table")
    result = {leaf}
    pvs = bsp_tools.decompress_pvs(
        bsp.visibility, bsp.leaves[leaf].vis_offset, bsp.vis_leaf_count
    )
    for bit in range(bsp.vis_leaf_count):
        if pvs[bit >> 3] & (1 << (bit & 7)):
            result.add(bit + 1)
    return result


def _model_name(sample: CameraEntitySample, state: EntityState) -> str:
    if not 0 < state.model_index < len(sample.model_precache):
        return ""
    return sample.model_precache[state.model_index].replace("\\", "/").lower()


def _static_model_name(model_precache: tuple[str, ...], state: EntityState) -> str:
    if not 0 < state.model_index < len(model_precache):
        return ""
    return model_precache[state.model_index].replace("\\", "/").lower()


def _is_alias_model(name: str) -> bool:
    return (
        name.endswith(".mdl") and not name.rsplit("/", 1)[-1].startswith("v_")
    ) or name.endswith(".spr")


def _origin_q2(
    origin: tuple[float, float, float], world_origin: tuple[float, float, float]
) -> tuple[int, int, int]:
    result = tuple(
        int(
            math.floor(
                (origin[axis] - world_origin[axis]) * 4.0 / bsp_tools.WORLD_SCALE + 0.5
            )
        )
        for axis in range(3)
    )
    if any(value < -0x8000 or value > 0x7FFF for value in result):
        raise ValueError("alias entity origin escapes signed Q2 storage")
    return result  # type: ignore[return-value]


def _camera_forward(sample: CameraEntitySample) -> tuple[float, float, float]:
    pitch = math.radians(sample.camera.view_angles[0])
    yaw = math.radians(sample.camera.view_angles[1])
    cosine = math.cos(pitch)
    return cosine * math.cos(yaw), cosine * math.sin(yaw), -math.sin(pitch)


def _camera_billboard_axes(
    sample: CameraEntitySample,
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Return the ROM's quantized screen-right and screen-up axes."""

    yaw_index, pitch_index = _packed_camera_angles(sample)
    pitch_sin = ANGLE_SIN_Q6[pitch_index & 31] / 64.0
    pitch_cos = ANGLE_COS_Q6[pitch_index & 31] / 64.0
    yaw_sin = ANGLE_SIN_Q6[yaw_index] / 64.0
    yaw_cos = ANGLE_COS_Q6[yaw_index] / 64.0
    return (
        (-yaw_sin, yaw_cos, 0.0),
        (-pitch_sin * yaw_cos, -pitch_sin * yaw_sin, pitch_cos),
    )


def _segment_avoids_solid(
    start: tuple[float, float, float],
    end: tuple[float, float, float],
    bsp: SpatialBsp,
) -> bool:
    """Return whether one segment remains in non-solid render-BSP leaves."""

    stack = [(bsp.root, start, end)]
    while stack:
        node_index, first, last = stack.pop()
        while node_index >= 0:
            node = bsp.nodes[node_index]
            plane = bsp.planes[node.plane]
            first_distance = (
                first[0] * float(plane[0])
                + first[1] * float(plane[1])
                + first[2] * float(plane[2])
                - float(plane[3])
            )
            last_distance = (
                last[0] * float(plane[0])
                + last[1] * float(plane[1])
                + last[2] * float(plane[2])
                - float(plane[3])
            )
            if first_distance >= 0.0 and last_distance >= 0.0:
                node_index = node.children[0]
                continue
            if first_distance < 0.0 and last_distance < 0.0:
                node_index = node.children[1]
                continue
            fraction = first_distance / (first_distance - last_distance)
            middle = tuple(
                first[axis] + (last[axis] - first[axis]) * fraction for axis in range(3)
            )
            first_side = 0 if first_distance >= 0.0 else 1
            stack.append((node.children[1 - first_side], middle, last))
            node_index = node.children[first_side]
            last = middle
        leaf = -node_index - 1
        if not 0 <= leaf < len(bsp.leaves):
            raise ValueError("alias visibility segment escaped the BSP leaf table")
        if bsp.leaves[leaf].contents == -2:
            return False
    return True


def _segments_avoid_solid(
    start: tuple[float, float, float],
    ends: tuple[tuple[float, float, float], ...],
    bsp: SpatialBsp,
) -> np.ndarray:
    """Vectorize exact BSP segment classification for one billboard."""
    if not ends:
        return np.empty(0, dtype=np.bool_)
    endpoints = np.asarray(ends, dtype=np.float64)
    origin = np.asarray(start, dtype=np.float64)
    directions = endpoints - origin
    clear = np.ones(len(ends), dtype=np.bool_)
    stack: list[tuple[int, np.ndarray, np.ndarray, np.ndarray]] = [
        (
            bsp.root,
            np.arange(len(ends), dtype=np.intp),
            np.zeros(len(ends), dtype=np.float64),
            np.ones(len(ends), dtype=np.float64),
        )
    ]

    def push(
        node: int,
        indices: np.ndarray,
        first: np.ndarray,
        last: np.ndarray,
        mask: np.ndarray,
    ) -> None:
        if np.any(mask):
            stack.append((node, indices[mask], first[mask], last[mask]))

    while stack:
        node_index, indices, first_t, last_t = stack.pop()
        alive = clear[indices]
        if not np.any(alive):
            continue
        indices = indices[alive]
        first_t = first_t[alive]
        last_t = last_t[alive]
        if node_index < 0:
            leaf = -node_index - 1
            if not 0 <= leaf < len(bsp.leaves):
                raise ValueError("alias visibility segments escaped the BSP leaf table")
            if bsp.leaves[leaf].contents == -2:
                clear[indices] = False
            continue
        node = bsp.nodes[node_index]
        plane = bsp.planes[node.plane]
        normal = np.asarray(plane[:3], dtype=np.float64)
        origin_distance = float(origin @ normal) - float(plane[3])
        slopes = directions[indices] @ normal
        first_distance = origin_distance + slopes * first_t
        last_distance = origin_distance + slopes * last_t
        front = (first_distance >= 0.0) & (last_distance >= 0.0)
        back = (first_distance < 0.0) & (last_distance < 0.0)
        push(node.children[0], indices, first_t, last_t, front)
        push(node.children[1], indices, first_t, last_t, back)
        split = ~(front | back)
        if not np.any(split):
            continue
        split_indices = indices[split]
        split_first = first_t[split]
        split_last = last_t[split]
        split_first_distance = first_distance[split]
        split_last_distance = last_distance[split]
        fraction = split_first_distance / (split_first_distance - split_last_distance)
        middle = split_first + (split_last - split_first) * fraction
        starts_front = split_first_distance >= 0.0
        push(
            node.children[0],
            split_indices,
            split_first,
            middle,
            starts_front,
        )
        push(
            node.children[1],
            split_indices,
            middle,
            split_last,
            starts_front,
        )
        push(
            node.children[1],
            split_indices,
            split_first,
            middle,
            ~starts_front,
        )
        push(
            node.children[0],
            split_indices,
            middle,
            split_last,
            ~starts_front,
        )
    return clear


def _wrap_i16(value: int) -> int:
    return ((value + 0x8000) & 0xFFFF) - 0x8000


def _alias_mul_shift(value: int, multiplier: int, shift: int) -> int:
    return _wrap_i16((value * multiplier) >> shift)


def _packed_camera_coordinate(
    sample: CameraEntitySample, bsp: SpatialBsp
) -> tuple[int, int, int]:
    """Match the precise Q3 camera's coarse signed-byte GSU handoff."""
    return tuple(
        (
            (
                round(sample.camera.origin[axis] * 8.0)
                - round(bsp.world_origin[axis] * 8.0)
            )
            * 2
        )
        // 256
        for axis in range(3)
    )  # type: ignore[return-value]


def _packed_camera_angles(sample: CameraEntitySample) -> tuple[int, int]:
    """Match the precise u16 angles' rounded five-bit CPU handoff."""
    yaw_u16 = round((sample.camera.view_angles[1] % 360.0) * 65536.0 / 360.0) & 0xFFFF
    pitch_u16 = round((sample.camera.view_angles[0] % 360.0) * 65536.0 / 360.0) & 0xFFFF
    pitch_i16 = _wrap_i16(pitch_u16)
    yaw = ((yaw_u16 + 0x0400) & 0xFFFF) >> 11
    pitch = ((-pitch_i16 + 0x0400) & 0xFFFF) >> 11
    return yaw, pitch


def _projected_opaque_anchors(
    state: AliasState,
    sprite: BillboardSprite,
    sample: CameraEntitySample,
    bsp: SpatialBsp,
) -> tuple[tuple[float, float], ...]:
    """Return opaque source texels sampled by the visible packed rectangle."""
    source_width, source_height, source_pixels = sprite.visibility_raster
    camera = _packed_camera_coordinate(sample, bsp)
    yaw, pitch = _packed_camera_angles(sample)
    dx = _wrap_i16(state.origin_q2[0] - camera[0] * 4)
    dy = _wrap_i16(state.origin_q2[1] - camera[1] * 4)
    dz = _wrap_i16(state.origin_q2[2] - camera[2] * 4)
    forward = _wrap_i16(
        _alias_mul_shift(dx, ANGLE_COS_Q6[yaw], 2)
        + _alias_mul_shift(dy, ANGLE_SIN_Q6[yaw], 2)
    )
    right = _wrap_i16(
        _alias_mul_shift(dy, ANGLE_COS_Q6[yaw], 2)
        - _alias_mul_shift(dx, ANGLE_SIN_Q6[yaw], 2)
    )
    up = _wrap_i16(
        _alias_mul_shift(dz, ANGLE_COS_Q6[pitch], 2)
        - _alias_mul_shift(forward, ANGLE_SIN_Q6[pitch], 6)
    )
    depth = _wrap_i16(
        _alias_mul_shift(forward, ANGLE_COS_Q6[pitch], 6)
        + _alias_mul_shift(dz, ANGLE_SIN_Q6[pitch], 2)
    )
    if depth < 64:
        return ()

    left_component = _wrap_i16(right + sprite.left * 4)
    right_component = _wrap_i16(left_component + sprite.projected_width * 4)
    horizontal = coherent_axis_q7(left_component, right_component, depth, 8192, 1)
    top_component = _wrap_i16(up + sprite.top * 4)
    bottom_component = _wrap_i16(top_component - sprite.projected_height * 4)
    vertical = coherent_axis_q7(top_component, bottom_component, depth, 7168, -1)
    if horizontal is None or vertical is None:
        return ()
    left_q7, right_q7 = horizontal
    top_q7, bottom_q7 = vertical
    span_x_q7 = right_q7 - left_q7
    span_y_q7 = bottom_q7 - top_q7
    first_x = (left_q7 + 63) >> 7
    last_x = (right_q7 - 64) >> 7
    first_y = (top_q7 + 63) >> 7
    last_y = (bottom_q7 - 64) >> 7
    if (
        first_x >= 128
        or last_x < 0
        or last_x < first_x
        or first_y >= 112
        or last_y < 0
        or last_y < first_y
    ):
        return ()

    anchors: set[tuple[float, float]] = set()
    for y in range(max(0, first_y), min(111, last_y) + 1):
        source_y = min(
            source_height - 1,
            max(0, ((y * 128 + 64 - top_q7) * source_height) // span_y_q7),
        )
        for x in range(max(0, first_x), min(127, last_x) + 1):
            source_x = min(
                source_width - 1,
                max(
                    0,
                    ((x * 128 + 64 - left_q7) * source_width) // span_x_q7,
                ),
            )
            if source_pixels[source_y * source_width + source_x] & 0x0100:
                anchors.add(
                    (
                        sprite.left
                        + (source_x + 0.5) * sprite.projected_width / source_width,
                        sprite.top
                        - (source_y + 0.5) * sprite.projected_height / source_height,
                    )
                )
    return tuple(
        sorted(
            anchors,
            key=lambda point: (
                point[0] * point[0] + point[1] * point[1],
                point,
            ),
        )
    )


def _alias_has_world_visibility(
    state: AliasState,
    sprite: BillboardSprite,
    sample: CameraEntitySample,
    bsp: SpatialBsp,
) -> bool:
    """Retain an alias if any sampled opaque billboard point sees the camera."""
    anchors = _projected_opaque_anchors(state, sprite, sample, bsp)
    if not anchors:
        return False
    right, up = _camera_billboard_axes(sample)
    origin = tuple(
        bsp.world_origin[axis] + state.origin_q2[axis] * bsp_tools.WORLD_SCALE / 4.0
        for axis in range(3)
    )

    def endpoint(horizontal: float, vertical: float) -> tuple[float, float, float]:
        return tuple(
            origin[axis] + right[axis] * horizontal + up[axis] * vertical
            for axis in range(3)
        )  # type: ignore[return-value]

    # Center/extremal probes cheaply accept most visible entities; only fully
    # covered candidates need exact sampled-opaque-center testing.
    probes = (
        anchors[0],
        min(anchors, key=lambda point: point[0]),
        max(anchors, key=lambda point: point[0]),
        min(anchors, key=lambda point: point[1]),
        max(anchors, key=lambda point: point[1]),
    )
    camera_coordinate = _packed_camera_coordinate(sample, bsp)
    camera_origin = tuple(
        bsp.world_origin[axis] + camera_coordinate[axis] * bsp_tools.WORLD_SCALE
        for axis in range(3)
    )
    for horizontal, vertical in probes:
        if _segment_avoids_solid(camera_origin, endpoint(horizontal, vertical), bsp):
            return True
    endpoints = tuple(
        endpoint(horizontal, vertical) for horizontal, vertical in anchors
    )
    return bool(np.any(_segments_avoid_solid(camera_origin, endpoints, bsp)))


def _depth(origin: tuple[float, float, float], sample: CameraEntitySample) -> float:
    forward = _camera_forward(sample)
    return sum(
        (origin[axis] - sample.camera.origin[axis]) * forward[axis] for axis in range(3)
    )


VariantKey = tuple[str, int, int]


def _variant_key(
    state: EntityState,
    name: str,
    models: dict[str, BillboardModel],
    *,
    camera_origin: tuple[float, float, float] | None = None,
    viewer_bearing: float | None = None,
    server_time: float = 0.0,
) -> VariantKey:
    model = models[name]
    if isinstance(model, SprModel):
        frame = resolved_spr_frame(model, state.frame)
        return name, frame, spr_subframe(model, frame, server_time)
    frame = resolved_frame(model, state.frame)
    yaw = mdl_yaw(model, state.angles[1], server_time)
    if viewer_bearing is None:
        if camera_origin is None:
            return name, frame, 0
        viewer_bearing = math.degrees(math.atan2(
            camera_origin[1] - state.origin[1], camera_origin[0] - state.origin[0]))
    relative = (viewer_bearing - yaw) % 360.0
    view = int(math.floor(relative / 45.0 + 0.5)) & (VIEW_COUNT - 1)
    return name, frame, view


def _state_sprite(
    state: EntityState,
    name: str,
    sprite_ids: dict[str | VariantKey, int],
    models: dict[str, BillboardModel] | None,
    *,
    camera_origin: tuple[float, float, float] | None = None,
    viewer_bearing: float | None = None,
    server_time: float = 0.0,
) -> int:
    # Preserve the historical test/tool API while generators supply variants.
    if models is None:
        return sprite_ids[name]
    key = _variant_key(
        state,
        name,
        models,
        camera_origin=camera_origin,
        viewer_bearing=viewer_bearing,
        server_time=server_time,
    )
    sprite = sprite_ids[key]
    if sprite > MAX_SPRITE_ID:
        raise ValueError("alias sprite identity escapes the u16 state key")
    return sprite


def _alias_state(
    state: EntityState,
    name: str,
    sprite_ids: dict[str | VariantKey, int],
    bsp: SpatialBsp,
    models: dict[str, BillboardModel] | None = None,
    *,
    camera_origin: tuple[float, float, float] | None = None,
    viewer_bearing: float | None = None,
    server_time: float = 0.0,
    fly: bool = False,
) -> AliasState:
    leaf = _locate_leaf(state.origin, bsp)
    sprite = _state_sprite(
        state,
        name,
        sprite_ids,
        models,
        camera_origin=camera_origin,
        viewer_bearing=viewer_bearing,
        server_time=server_time,
    )
    directional_base_sprite: int | None = None
    yaw_sin_q6 = 0
    yaw_cos_q6 = 0
    if fly and models is not None and not isinstance(models[name], SprModel):
        frame = resolved_frame(models[name], state.frame)
        directional_base_sprite = sprite_ids[(name, frame, 0)]
        yaw = math.radians(state.angles[1])
        yaw_sin_q6 = round(math.sin(yaw) * 64)
        yaw_cos_q6 = round(math.cos(yaw) * 64)
        if models[name].header.flags & EF_ROTATE:
            yaw_sin_q6, yaw_cos_q6 = FLY_ROTATE_SENTINEL, 0
    return AliasState(
        state.entity_number,
        sprite,
        state.model_index,
        _origin_q2(state.origin, bsp.world_origin),
        state.origin,
        leaf,
        directional_base_sprite,
        yaw_sin_q6,
        yaw_cos_q6,
    )


def build_rows(
    sampled: Iterable[CameraEntitySample],
    initial_entities: tuple[EntityState, ...],
    static_entities: tuple[EntityState, ...],
    model_precache: tuple[str, ...],
    sprite_ids: dict[str | VariantKey, int],
    bsp: SpatialBsp,
    sprites: tuple[BillboardSprite, ...] | None = None,
    models: dict[str, BillboardModel] | None = None,
) -> tuple[tuple[AliasState, ...], tuple[AliasRow, ...]]:
    sampled = tuple(sampled)
    if not sampled:
        raise ValueError("alias replay requires at least one sampled camera row")
    static_states = tuple(
        _alias_state(
            state,
            name,
            sprite_ids,
            bsp,
            models,
            server_time=sampled[0].camera.server_time,
        )
        for state in static_entities
        if _is_alias_model(name := _static_model_name(model_precache, state))
        and (name in sprite_ids or models is not None and name in models)
    )
    if len(static_states) >= 0x80:
        raise ValueError("static alias state count escapes seven-bit row tokens")

    def grouped_row(
        sample: CameraEntitySample,
        dynamic_states: tuple[AliasState, ...],
        visible: set[int] | None,
        *,
        include_static: bool = True,
    ) -> AliasRow:
        members: dict[int, list[tuple[float, int, int]]] = defaultdict(list)
        culled_tokens = 0

        def add(state: AliasState, token: int) -> None:
            nonlocal culled_tokens
            entry = (_depth(state.source_origin, sample), state.entity, token)
            if (
                visible is not None
                and sprites is not None
                and not _alias_has_world_visibility(
                    state,
                    sprites[state.sprite_id],
                    sample,
                    bsp,
                )
            ):
                culled_tokens += 1
                return
            members[state.leaf].append(entry)

        for index, state in enumerate(dynamic_states):
            add(state, index)
        if include_static:
            for index, state in enumerate(static_states):
                if visible is None or state.leaf in visible:
                    add(state, 0x80 | index)
        groups: list[AliasGroup] = []
        for leaf, entries in sorted(members.items()):
            if not 0 <= leaf < len(bsp.leaf_parents):
                raise ValueError("alias entity resolves outside the BSP leaf table")
            if bsp.leaves[leaf].contents == -2:
                continue
            parent = bsp.leaf_parents[leaf]
            if parent < 0:
                raise ValueError("visible alias leaf has no owning BSP node")
            # Far-to-near painter order; lower entity IDs win equal-depth ties.
            ordered = sorted(entries, key=lambda item: (-item[0], -item[1]))
            groups.append(AliasGroup(leaf, parent, tuple(item[2] for item in ordered)))
        token_count = sum(len(group.tokens) for group in groups)
        if len(groups) >= 0x100 or token_count >= 0x80:
            raise ValueError("alias row escapes compact group/token storage")
        return AliasRow(dynamic_states, tuple(groups), culled_tokens)

    rows: list[AliasRow] = []
    for sample in sampled:
        visible = _visible_leaves(sample.camera.origin, bsp)
        dynamic_states = tuple(
            _alias_state(
                state,
                name,
                sprite_ids,
                bsp,
                models,
                camera_origin=sample.camera.origin,
                server_time=sample.camera.server_time,
            )
            for state in sample.entities
            if state.entity_number != sample.view_entity
            and _is_alias_model(name := _model_name(sample, state))
            and (name in sprite_ids or models is not None and name in models)
            and _locate_leaf(state.origin, bsp) in visible
        )
        if len(dynamic_states) >= 0x80:
            raise ValueError("dynamic alias state count escapes seven-bit row tokens")
        rows.append(grouped_row(sample, dynamic_states, visible))

    # Free flight uses baseline poses for all networked entities, including
    # outside the initial PVS, plus every spawn-static model reachable later.
    first = sampled[0]
    fly_entities = tuple(
        (state, name)
        for state in initial_entities
        if state.entity_number != first.view_entity
        and _is_alias_model(name := _static_model_name(model_precache, state))
        and (name in sprite_ids or models is not None and name in models)
    ) + tuple(
        (state, name)
        for state in static_entities
        if _is_alias_model(name := _static_model_name(model_precache, state))
        and (name in sprite_ids or models is not None and name in models)
    )
    if len(fly_entities) >= 0x80:
        raise ValueError("fly alias state count escapes seven-bit row tokens")
    # Keep eight ABI-compatible fly rows, but encode MDLs as a view-zero base
    # plus their exact facing. Runtime chooses the view from entity-to-camera
    # bearing, so moving sideways cannot retain a stale camera-yaw silhouette.
    for orbit in range(FLY_ROW_COUNT):
        viewer_bearing = orbit * 45.0 + 180.0
        fly_dynamic_states = tuple(
            _alias_state(
                state,
                name,
                sprite_ids,
                bsp,
                models,
                viewer_bearing=viewer_bearing,
                server_time=first.camera.server_time,
                fly=True,
            )
            for state, name in fly_entities
        )
        rows.append(grouped_row(first, fly_dynamic_states, None, include_static=False))
    return static_states, tuple(rows)


def _group_bytes(groups: tuple[AliasGroup, ...]) -> bytes:
    payload = bytearray()
    for group in groups:
        payload.extend(GROUP_HEADER.pack(group.leaf, group.parent, len(group.tokens)))
        payload.extend(group.tokens)
    return bytes(payload)


@dataclass(slots=True)
class _PackedAliasStructure:
    packer: HalfbankPacker
    row_directory_end: int
    sprite_directory_location: Location
    static_location: Location
    static_payload: bytes
    fly_facing_location: Location
    fly_facing_payload: bytes
    rotation_location: Location | None
    row_records: tuple[bytes, ...]
    snapshot_locations: dict[bytes, Location]
    group_locations: dict[bytes, Location]


def _pack_alias_structure(
    rows: tuple[AliasRow, ...],
    static_states: tuple[AliasState, ...],
    sprite_count: int,
    *,
    deduplicate_rows: bool = True,
    max_chunks: int = MAX_PHYSICAL_HALFBANKS,
    rotation_payload: bytes = b"",
) -> _PackedAliasStructure:
    """Pack every non-pixel QBA block before bounded sprite selection."""

    row_directory_end = HEADER.size + len(rows) * ROW_DIRECTORY.size
    packer = HalfbankPacker(row_directory_end, max_chunks=max_chunks)
    sprite_directory_location = packer.place(
        b"\xff" * (sprite_count * SPRITE_DIRECTORY.size), alignment=2
    )
    static_payload = b"".join(state.packed() for state in static_states)
    static_location = (
        packer.place(static_payload, alignment=2)
        if static_payload
        else Location(0, row_directory_end, *gsu_location(0, row_directory_end))
    )
    if len(rows) < FLY_ROW_COUNT:
        raise ValueError("alias rows omit the fly suffix")
    fly_rows = rows[-FLY_ROW_COUNT:]
    fly_state_count = len(fly_rows[0].dynamic_states)
    fly_facing = tuple(
        (state.yaw_sin_q6, state.yaw_cos_q6) for state in fly_rows[0].dynamic_states
    )
    if any(
        len(row.dynamic_states) != fly_state_count
        or tuple((state.yaw_sin_q6, state.yaw_cos_q6) for state in row.dynamic_states)
        != fly_facing
        for row in fly_rows
    ):
        raise ValueError("fly rows disagree on their camera-independent facing table")
    fly_facing_payload = b"".join(
        FLY_FACING_RECORD.pack(*facing) for facing in fly_facing
    )
    fly_facing_location = (
        packer.place(fly_facing_payload, alignment=2)
        if fly_facing_payload
        else Location(0, 0, 0, 0)
    )
    rotation_location = packer.place(rotation_payload, alignment=2) if rotation_payload else None
    snapshot_locations: dict[bytes, Location] = {}
    group_locations: dict[bytes, Location] = {}
    row_records: list[bytes] = []
    for row in rows:
        snapshot = b"".join(state.packed() for state in row.dynamic_states)
        snapshot_location = (
            snapshot_locations.get(snapshot) if deduplicate_rows else None
        )
        if snapshot and snapshot_location is None:
            snapshot_location = packer.place(snapshot, alignment=2)
            if deduplicate_rows:
                snapshot_locations[snapshot] = snapshot_location
        elif not snapshot:
            snapshot_location = Location(0, 0, 0, 0)

        groups = _group_bytes(row.groups)
        group_location = group_locations.get(groups) if deduplicate_rows else None
        if groups and group_location is None:
            group_location = packer.place(groups, alignment=2)
            if deduplicate_rows:
                group_locations[groups] = group_location
        elif not groups:
            group_location = Location(0, 0, 0, 0)
        assert snapshot_location is not None
        assert group_location is not None
        row_records.append(
            ROW_DIRECTORY.pack(
                snapshot_location.bank,
                len(row.dynamic_states),
                snapshot_location.address,
                group_location.bank,
                len(row.groups),
                group_location.address,
            )
        )
    return _PackedAliasStructure(
        packer,
        row_directory_end,
        sprite_directory_location,
        static_location,
        static_payload,
        fly_facing_location,
        fly_facing_payload,
        rotation_location,
        tuple(row_records),
        snapshot_locations,
        group_locations,
    )


def _sprite_bytes(sprite: BillboardSprite) -> bytes:
    return sprite.encoded_pixels


def _pack_sprites_exact(
    rows: tuple[AliasRow, ...],
    static_states: tuple[AliasState, ...],
    sprites: tuple[BillboardSprite, ...],
    *,
    max_chunks: int,
    rotation_payload: bytes = b"",
) -> tuple[_PackedAliasStructure, dict[SpriteRaster, Location]]:
    """Pack every exact frame/view raster or reject the configured density."""

    structure = _pack_alias_structure(
        rows, static_states, len(sprites), max_chunks=max_chunks, rotation_payload=rotation_payload
    )
    locations: dict[SpriteRaster, Location] = {}
    payloads = {sprite.storage_raster for sprite in sprites}
    for payload in sorted(payloads, key=lambda item: (-len(item), item)):
        location = structure.packer.try_place_compact(payload.pixels, alignment=2)
        if location is None:
            required = sum(map(len, payloads))
            capacity = max_chunks * HALFBANK_BYTES
            raise ValueError(
                "exact alias sprites do not fit the configured density: "
                f"{len(sprites)} variants need {required} unique pixel bytes "
                f"plus directories and replay rows in {capacity} reserved bytes"
            )
        locations[payload] = location
    return structure, locations


def build_sprite_atlas(
    sampled: tuple[CameraEntitySample, ...],
    initial_entities: tuple[EntityState, ...],
    static_entities: tuple[EntityState, ...],
    model_precache: tuple[str, ...],
    models: dict[str, BillboardModel],
    bsp: SpatialBsp,
    *,
    mdl_world_units_per_texel: float = 1,
) -> tuple[dict[VariantKey, int], tuple[BillboardSprite, ...]]:
    """Project retained MDL angles and exact time-selected IDSP subframes."""

    retained_variants: set[VariantKey] = set()

    def retain(
        state: EntityState,
        name: str,
        *,
        camera_origin: tuple[float, float, float] | None = None,
        viewer_bearing: float | None = None,
        server_time: float = 0.0,
    ) -> None:
        key = _variant_key(
            state,
            name,
            models,
            camera_origin=camera_origin,
            viewer_bearing=viewer_bearing,
            server_time=server_time,
        )
        if isinstance(models[name], SprModel):
            retained_variants.add(key)
        else:
            retained_variants.update((name, key[1], view) for view in range(VIEW_COUNT))

    for state in static_entities:
        name = _static_model_name(model_precache, state)
        if _is_alias_model(name) and name in models:
            retain(
                state,
                name,
                server_time=sampled[0].camera.server_time if sampled else 0.0,
            )
    for sample in sampled:
        visible = _visible_leaves(sample.camera.origin, bsp)
        for state in sample.entities:
            name = _model_name(sample, state)
            if (
                state.entity_number != sample.view_entity
                and _is_alias_model(name)
                and name in models
                and _locate_leaf(state.origin, bsp) in visible
            ):
                retain(
                    state,
                    name,
                    camera_origin=sample.camera.origin,
                    server_time=sample.camera.server_time,
                )
    fly_entities = tuple(
        (state, name)
        for state in initial_entities
        if sampled
        and state.entity_number != sampled[0].view_entity
        and _is_alias_model(name := _static_model_name(model_precache, state))
        and name in models
    ) + tuple(
        (state, name)
        for state in static_entities
        if _is_alias_model(name := _static_model_name(model_precache, state))
        and name in models
    )
    for orbit in range(FLY_ROW_COUNT):
        for state, name in fly_entities:
            retain(
                state,
                name,
                viewer_bearing=orbit * 45.0 + 180.0,
                server_time=sampled[0].camera.server_time if sampled else 0.0,
            )

    ordered = tuple(sorted(retained_variants))
    if len(ordered) > MAX_SPRITE_ID + 1:
        raise ValueError("alias variant count escapes the u16 state key")
    model_ids = {name: index for index, name in enumerate(sorted(models))}
    sprite_ids = {variant: index for index, variant in enumerate(ordered)}
    task_variants = {
        name: tuple(
            (frame, view)
            for variant_name, frame, view in ordered
            if variant_name == name
        )
        for name in sorted({name for name, _frame, _view in ordered})
        if not isinstance(models[name], SprModel)
    }
    tasks = tuple(
        (
            models[name],
            model_ids[name],
            mdl_world_units_per_texel,
            task_variants[name],
        )
        for name in task_variants
    )
    if len(ordered) >= PARALLEL_VARIANT_THRESHOLD and len(tasks) > 1:
        with ProcessPoolExecutor(
            max_workers=min(physical_core_count(), len(tasks))
        ) as executor:
            groups = tuple(executor.map(rasterize_model_variants, tasks))
    else:
        groups = tuple(rasterize_model_variants(task) for task in tasks)
    projected = {
        (name, frame, view): sprite
        for name, group in zip(task_variants, groups, strict=True)
        for (frame, view), sprite in zip(task_variants[name], group, strict=True)
    }
    projected.update(
        {
            key: rasterize_spr_billboard(
                models[key[0]],
                frame_index=key[1],
                subframe=key[2],
                model_id=model_ids[key[0]],
            )
            for key in ordered
            if isinstance(models[key[0]], SprModel)
        }
    )
    sprites = tuple(projected[key] for key in ordered)
    if len(sprites) != len(ordered):
        raise AssertionError("parallel alias projection lost a retained variant")
    return sprite_ids, sprites


def build_alias_assets(
    pak_path: Path,
    *,
    config_path: Path = DEFAULT_CONFIG,
) -> AliasAssetBuild:
    archive = bsp_tools.PakArchive(pak_path)
    mesen_target = configured_mesen_target(config_path)
    alias_config = configured_alias_sprites(config_path)
    max_halfbanks = alias_config.halfbank_count
    mdl_world_units_per_texel = alias_config.mdl_world_units_per_texel
    selected_demo = resolve_configured_demo(archive.read, config_path)
    sample_rate = configured_playback_sample_rate(config_path)
    track = decode_camera_entity_track(selected_demo.payload, selected_demo.map_entry)
    precache_inventory, used_sprite_names = build_model_precache_inventory(
        archive.read, track.model_precache, track.samples
    )
    source_indices = sample_newest_due_indices(
        [sample.camera.server_time for sample in track.samples], sample_rate
    )
    sampled = tuple(track.samples[index] for index in source_indices)
    canonical = extract_canonical_brush_replay(
        selected_demo.payload, selected_demo.map_entry, sample_rate
    )
    if len(sampled) != len(canonical.rows):
        raise AssertionError("alias and camera replay row counts disagree")
    bsp_payload = archive.read(selected_demo.map_entry)
    spatial = _parse_spatial_bsp(bsp_payload)
    bsp_lumps = bsp_tools.lump_ranges(bsp_payload)
    bsp_texinfo = bsp_tools.unpack_records(
        bsp_tools.lump_data(bsp_payload, bsp_lumps, bsp_tools.LUMP_TEXINFO),
        "<8fii",
    )
    unit_texinfo_count = sum(
        math.isclose(
            math.sqrt(sum(float(component) ** 2 for component in record[0:3])),
            1.0,
            abs_tol=1e-6,
        )
        and math.isclose(
            math.sqrt(sum(float(component) ** 2 for component in record[4:7])),
            1.0,
            abs_tol=1e-6,
        )
        for record in bsp_texinfo
    )
    model_names = {
        name
        for sample in sampled
        for state in sample.entities
        if state.entity_number != sample.view_entity
        and _is_alias_model(name := _model_name(sample, state))
    }
    model_names.update(
        name
        for state in track.baselines
        if _is_alias_model(name := _static_model_name(track.model_precache, state))
        and (not name.endswith(".spr") or name in used_sprite_names)
    )
    model_names.update(
        name
        for state in track.static_entities
        if _is_alias_model(name := _static_model_name(track.model_precache, state))
        and (not name.endswith(".spr") or name in used_sprite_names)
    )
    ordered_names = tuple(sorted(model_names))
    if len(ordered_names) > 0xFF:
        raise ValueError("alias model count escapes u8 sprite metadata")
    models: dict[str, BillboardModel] = {
        name: (
            parse_spr(archive.read(name))
            if name.endswith(".spr")
            else quake_assets.parse_mdl(archive.read(name))
        )
        for name in ordered_names
    }
    unsupported_sprites = tuple(
        name
        for name, model in models.items()
        if isinstance(model, SprModel)
        and model.orientation != SpriteOrientation.VIEW_PARALLEL
    )
    if unsupported_sprites:
        raise ValueError(
            "demo-used IDSP sprites require unsupported orientations: "
            + ", ".join(unsupported_sprites)
        )
    all_sprite_ids, all_projected_sprites = build_sprite_atlas(
        sampled,
        track.baselines,
        track.static_entities,
        track.model_precache,
        models,
        spatial,
        mdl_world_units_per_texel=mdl_world_units_per_texel,
    )
    all_projected_payloads = canonicalize_sprite_rasters(all_projected_sprites)
    all_ordered_variants = tuple(
        variant
        for variant, _sprite in sorted(all_sprite_ids.items(), key=lambda item: item[1])
    )
    projected_payload_by_key = dict(zip(all_ordered_variants, all_projected_payloads))
    model_ids = {name: index for index, name in enumerate(ordered_names)}
    front_sprites = {
        name: (
            all_projected_sprites[all_sprite_ids[(name, 0, 0)]]
            if (name, 0, 0) in all_sprite_ids
            else (
                rasterize_spr_billboard(models[name], model_id=model_ids[name])
                if isinstance(models[name], SprModel)
                else rasterize_billboard(
                    models[name],
                    mdl_world_units_per_texel=mdl_world_units_per_texel,
                    model_id=model_ids[name],
                )
            )
        )
        for name in ordered_names
    }
    full_static, full_rows = build_rows(
        sampled,
        track.baselines,
        track.static_entities,
        track.model_precache,
        all_sprite_ids,
        spatial,
        all_projected_sprites,
        models,
    )
    fly_row = len(sampled)
    demo_usage_all, fly_usage_all = runtime_sprite_usage(
        full_static, full_rows, fly_row, len(all_projected_sprites)
    )
    runtime_ids = {
        index
        for index, (demo, fly) in enumerate(zip(demo_usage_all, fly_usage_all))
        if demo or fly
    }
    runtime_names = {all_ordered_variants[index][0] for index in runtime_ids}
    retained_keys = {all_ordered_variants[index] for index in runtime_ids}
    retained_keys.update((name, 0, 0) for name in runtime_names)
    ordered_variants = tuple(sorted(retained_keys))
    projected_by_key = dict(zip(all_ordered_variants, all_projected_sprites))
    projected_sprites = tuple(
        projected_by_key.get(key, front_sprites[key[0]]) for key in ordered_variants
    )
    compact_ids = {key: index for index, key in enumerate(ordered_variants)}
    sprite_ids = {
        key: compact_ids.get(key, compact_ids[(key[0], 0, 0)])
        for key in all_sprite_ids
        if key[0] in runtime_names
    }
    active_models = {name: models[name] for name in runtime_names}
    demo_usage = tuple(
        demo_usage_all[all_sprite_ids[key]] if key in all_sprite_ids else 0
        for key in ordered_variants
    )
    fly_usage = tuple(
        fly_usage_all[all_sprite_ids[key]] if key in all_sprite_ids else 0
        for key in ordered_variants
    )
    projected_payloads = tuple(
        projected_payload_by_key.get(key, front_sprites[key[0]].storage_raster)
        for key in ordered_variants
    )
    static_states, rows = build_rows(
        sampled,
        track.baselines,
        track.static_entities,
        track.model_precache,
        sprite_ids,
        spatial,
        projected_sprites,
        active_models,
    )
    if len(rows) != fly_row + FLY_ROW_COUNT:
        raise AssertionError("eight alias fly rows must follow the sampled demo rows")
    sprites = runtime_sprites = projected_sprites
    logical_to_runtime = tuple(range(len(sprites)))
    structure, pixel_locations = _pack_sprites_exact(
        rows,
        static_states,
        sprites,
        max_chunks=max_halfbanks,
        rotation_payload=ROTATION_BASES_BYTES + b"".join(
            struct.pack("<H", rotation_phase_q16(sample.camera.server_time))
            for sample in sampled
        ),
    )
    packer = structure.packer
    row_directory_offset = HEADER.size
    row_directory_end = structure.row_directory_end
    sprite_directory_bytes = len(runtime_sprites) * SPRITE_DIRECTORY.size
    sprite_directory_location = structure.sprite_directory_location
    static_payload = structure.static_payload
    static_location = structure.static_location
    fly_facing_location = structure.fly_facing_location
    fly_facing_payload = structure.fly_facing_payload
    snapshot_locations = structure.snapshot_locations
    group_locations = structure.group_locations
    row_records = structure.row_records
    sprite_records: list[bytes] = []
    runtime_sprite_payloads = tuple(sprite.storage_raster for sprite in runtime_sprites)
    for sprite, payload in zip(runtime_sprites, runtime_sprite_payloads, strict=True):
        location = pixel_locations[payload]
        sprite_records.append(
            SPRITE_DIRECTORY.pack(
                location.bank,
                sprite.model,
                location.address,
                sprite.width,
                sprite.height,
                sprite.projected_width,
                sprite.projected_height,
                sprite.frame,
                sprite.view,
                sprite.left,
                sprite.top,
            )
        )
    sprite_payloads = tuple(sprite.storage_raster for sprite in sprites)
    sprite_locations = [pixel_locations[payload] for payload in sprite_payloads]
    chunk_count = len(packer.chunks)
    sprite_directory_offset = sprite_directory_location.flat_offset
    row_directory_location = Location(
        0,
        row_directory_offset,
        *gsu_location(0, row_directory_offset),
    )
    actual_max_gsu_rom_bank = max(
        gsu_location(index, HALFBANK_BYTES - 1)[0] for index in range(chunk_count)
    )
    if actual_max_gsu_rom_bank > mesen_target.max_gsu_rom_bank:
        raise AssertionError("generated alias pointer exceeds selected MesenCE target")
    max_dynamic = max((len(row.dynamic_states) for row in rows), default=0)
    max_visible = max(
        (sum(len(group.tokens) for group in row.groups) for row in rows), default=0
    )
    max_groups = max((len(row.groups) for row in rows), default=0)
    culled_counts = tuple(row.culled_tokens for row in rows[:-FLY_ROW_COUNT])
    header = HEADER.pack(
        MAGIC,
        VERSION,
        HEADER.size,
        len(rows),
        len(runtime_sprites),
        len(static_states),
        max_dynamic,
        max_visible,
        chunk_count,
        row_directory_offset,
        sprite_directory_offset,
        static_location.flat_offset,
        len(static_payload),
        canonical.camera_track_fnv1a64,
    )
    first = packer.chunks[0]
    first[: HEADER.size] = header
    first[row_directory_offset:row_directory_end] = b"".join(row_records)
    sprite_directory_chunk = packer.chunks[sprite_directory_location.chunk]
    sprite_directory_end = sprite_directory_location.offset + sprite_directory_bytes
    sprite_directory_chunk[sprite_directory_location.offset : sprite_directory_end] = (
        b"".join(sprite_records)
    )
    chunks = tuple(bytes(chunk) for chunk in packer.chunks)
    include = render_include(
        row_count=len(rows),
        sprite_count=len(runtime_sprites),
        static_count=len(static_states),
        chunk_count=chunk_count,
        row_directory=row_directory_location,
        sprite_directory=sprite_directory_location,
        static_states=static_location,
        fly_facing=fly_facing_location,
        fly_facing_count=len(fly_facing_payload) // FLY_FACING_RECORD.size,
        max_dynamic=max_dynamic,
        max_visible=max_visible,
        max_groups=max_groups,
        fly_row=fly_row,
        fly_row_count=FLY_ROW_COUNT,
        mesen_target=mesen_target,
        rotation=structure.rotation_location,
    )
    assembly = render_assembly(chunk_count)
    projected_unique_payloads = set(projected_payloads)
    all_projected_unique_payloads = set(all_projected_payloads)
    front_payloads = {front_sprites[name].storage_raster for name in runtime_names}
    runtime_payloads = {
        projected_payloads[index]
        for index, (demo, fly) in enumerate(zip(demo_usage, fly_usage, strict=True))
        if demo or fly
    }
    unused_resident_payloads = set(pixel_locations) - front_payloads - runtime_payloads
    if unused_resident_payloads:
        raise AssertionError("alias packer retained an unused non-front payload")
    model_metadata = []
    for model_id, name in enumerate(ordered_names):
        model = models[name]
        is_spr = isinstance(model, SprModel)
        used = tuple(
            (sprite_id, frame, view)
            for sprite_id, (variant_name, frame, view) in enumerate(ordered_variants)
            if variant_name == name
        )
        model_metadata.append(
            {
                "id": model_id,
                "name": name,
                "kind": billboard_model_kind(model),
                "sourceFrameCount": billboard_frame_count(model),
                "usedFrames": sorted({frame for _sprite, frame, _view in used}),
                "projectedViews": []
                if is_spr
                else sorted({view for _sprite, _frame, view in used}),
                "selectedSubframes": sorted({view for _sprite, _frame, view in used})
                if is_spr
                else [],
                **(
                    {
                        "orientationType": int(model.orientation),
                        "orientation": "view-plane-parallel",
                        "syncType": model.sync_type,
                    }
                    if is_spr
                    else {"flags": model.header.flags, "rotates": bool(model.header.flags & EF_ROTATE)}
                ),
                "variantCount": len(used),
                "variants": [sprite for sprite, _frame, _view in used],
                "residentVariantCount": len(used),
            }
        )
    variant_metadata = []
    for sprite_id, ((name, frame, view), sprite, location) in enumerate(
        zip(ordered_variants, sprites, sprite_locations, strict=True)
    ):
        variant_metadata.append(
            {
                "id": sprite_id,
                "runtimeId": logical_to_runtime[sprite_id],
                "model": ordered_names.index(name),
                "name": name,
                "kind": billboard_model_kind(models[name]),
                "frame": frame,
                "frameName": billboard_frame_name(models[name], frame),
                "projectedView": 0 if isinstance(models[name], SprModel) else view,
                "selectedSubframe": view if isinstance(models[name], SprModel) else 0,
                "sourceFrame": sprite.frame,
                "sourceFrameName": billboard_frame_name(models[name], sprite.frame),
                "sourceView": 0 if isinstance(models[name], SprModel) else sprite.view,
                "sourceSubframe": sprite.view
                if isinstance(models[name], SprModel)
                else 0,
                "storageWidth": sprite.width,
                "storageHeight": sprite.height,
                "worldWidth": sprite.projected_width,
                "worldHeight": sprite.projected_height,
                "left": sprite.left,
                "top": sprite.top,
                "opaqueTexels": sum(bool(pixel & 0xFF00) for pixel in sprite.pixels),
                "pixelBank": location.bank,
                "pixelAddress": location.address,
                "pixelBytes": len(sprite.pixels),
                "pixelSha256": hashlib.sha256(_sprite_bytes(sprite)).hexdigest(),
            }
        )
    all_states = tuple(static_states) + tuple(
        state for row in rows for state in row.dynamic_states
    )
    effect_variant_ids = {
        index
        for index, (name, _frame, _view) in enumerate(ordered_variants)
        if name.endswith(".spr")
    }
    effect_runtime_ids = {logical_to_runtime[index] for index in effect_variant_ids}
    mdl_variant_ids = set(range(len(ordered_variants))) - effect_variant_ids

    def kind_residency(usage: tuple[int, ...], variants: set[int]) -> dict[str, int]:
        return usage_metadata(
            usage,
            variants=variants,
            payloads=sprite_payloads,
        )

    demo_residency = usage_metadata(demo_usage)
    fly_residency = usage_metadata(fly_usage)

    def row_effect_entities(row: AliasRow) -> list[int]:
        entities: set[int] = set()
        for group in row.groups:
            for token in group.tokens:
                state = (
                    static_states[token & 0x7F]
                    if token & 0x80
                    else row.dynamic_states[token]
                )
                if state.sprite_id in effect_runtime_ids:
                    entities.add(state.entity)
        return sorted(entities)

    effect_rows = [
        {"row": index, "entityIds": entities}
        for index, row in enumerate(rows)
        if (entities := row_effect_entities(row))
    ]
    effect_state_rows = [
        {
            "row": row_index,
            "states": [
                {"index": state_index, "entity": state.entity}
                for state_index, state in enumerate(row.dynamic_states)
                if state.sprite_id in effect_runtime_ids
            ],
        }
        for row_index, row in enumerate(rows)
        if any(state.sprite_id in effect_runtime_ids for state in row.dynamic_states)
    ]
    mdl_fidelity = summarize_mdl_raster_fidelity(
        (
            sprite
            for (name, _frame, _view), sprite in zip(
                all_ordered_variants, all_projected_sprites, strict=True
            )
            if not name.endswith(".spr")
        ),
        mdl_world_units_per_texel,
    )
    metadata: dict[str, Any] = {
        "schema": "quake-bsp-billboards-v8",
        "version": VERSION,
        "source": {
            "pakPathHint": bsp_tools.QUAKE_PAK_PATH_HINT,
            "mapEntry": selected_demo.map_entry,
            "demoEntry": selected_demo.label,
            "demoSource": selected_demo.source.kind,
            "demoLocator": selected_demo.source.locator,
            "demoSha256": selected_demo.sha256,
            "bspSha256": hashlib.sha256(bsp_payload).hexdigest(),
            "modelPrecache": precache_inventory,
            "bspTextureDensity": {
                "texinfoCount": len(bsp_texinfo),
                "unitAxisPairCount": unit_texinfo_count,
                "worldUnitsPerOrdinaryTexel": 1,
            },
        },
        "contract": {
            "projection": "exact protocol frame; MDLs independently project all eight yaw views and IDSP view-plane-parallel effects preserve source pixels and pivot before runtime-use compaction and exact payload deduplication",
            "scale": f"density-one MDL projections partition at exact rational multiples of {mdl_world_units_per_texel} Quake world units per texel before modal reduction while density-one opacity controls offline visibility; IDSP effects preserve exact source pixels and pivots",
            "capacity": f"retain every demo/fly survivor plus each active model's exact frame 0 / view 0 raster; fail generation when the complete configured-density set exceeds {max_halfbanks} halfbanks",
            "transparency": "biased u8 texel: zero transparent and palette index plus one opaque; IDSP index 255 is source transparency and is never encoded opaque",
            "lighting": "baked MDL skin or exact IDSP palette index; world/brush lightmaps do not modify billboard texels",
            "occlusion": "demo tokens whose sampled opaque billboard cells have no non-solid BSP line to the camera are culled; retained and fly sprites compose whole after opaque geometry",
            "entityOrder": "origin forward depth, far to near, deterministic entity tie",
            "animation": "valid protocol frame selected exactly; invalid frame falls back to frame zero like Quake; IDSP groups select cumulative intervals from server time",
            "flyEntities": "eight ABI rows sharing camera-independent states; original origins and MDL extents; runtime bearing selects eight views, with EF_ROTATE yaw advancing at 100 degrees per second",
        },
        "rasterDensity": {
            "mdlWorldUnitsPerTexel": mdl_world_units_per_texel,
            "mdlVisibilityWorldUnitsPerTexel": 1,
            "mdlReduction": "identity"
            if mdl_world_units_per_texel == 1
            else "opaque-block-preserving-modal-palette-v1",
            "idspSourcePixelsPreserved": True,
            "mdlFidelity": mdl_fidelity,
        },
        "timeline": {
            "sampleRateHz": sample_rate,
            "rowCount": len(sampled),
            "assetRowCount": len(rows),
            "flyRow": fly_row,
            "flyRowCount": FLY_ROW_COUNT,
            "cameraTrackFnv1a64": f"{canonical.camera_track_fnv1a64:016x}",
            "uniqueDynamicSnapshots": len(snapshot_locations),
            "uniqueGroupStreams": len(group_locations),
            "maximumDynamicStates": max_dynamic,
            "maximumVisibleStates": max_visible,
            "maximumGroups": max_groups,
            "occlusionCulledTokens": sum(culled_counts),
            "rowsWithOcclusionCulls": sum(bool(count) for count in culled_counts),
            "maximumOcclusionCullsPerRow": max(culled_counts, default=0),
            "occlusionCullCountsSha256": hashlib.sha256(
                b"".join(struct.pack("<H", count) for count in culled_counts)
            ).hexdigest(),
        },
        "models": model_metadata,
        "sprites": variant_metadata,
        "instrumentation": {
            "modelNames": list(ordered_names),
            "modelKinds": [
                billboard_model_kind(models[name]) for name in ordered_names
            ],
            "staticEntityIds": [state.entity for state in static_states],
            "effectRows": effect_rows,
            "effectStates": effect_state_rows,
            "effectRowCount": len(effect_rows),
            "effectEntityIds": sorted(
                {entity for row in effect_rows for entity in row["entityIds"]}
            ),
        },
        "residency": {
            "policy": "all exact requested frame/view variants are mandatory; identity-only raster deduplication; capacity overflow is fatal",
            "generatedVariantCount": len(all_projected_sprites),
            "cartridgeVariantCount": len(sprites),
            "runtimeSpriteRecordCount": len(runtime_sprites),
            "excludedGeneratedVariantCount": len(all_projected_sprites) - len(sprites),
            "requestedVariantCount": sum(
                bool(demo or fly) for demo, fly in zip(demo_usage, fly_usage)
            ),
            "requestedPayloadCount": len(runtime_payloads),
            "requestedPayloadBytes": sum(map(len, runtime_payloads)),
            "residentRequestedPayloadCount": len(
                runtime_payloads & pixel_locations.keys()
            ),
            "residentRequestedPayloadBytes": sum(
                map(len, runtime_payloads & pixel_locations.keys())
            ),
            "frontPayloadCount": len(front_payloads),
            "frontPayloadBytes": sum(map(len, front_payloads)),
            "unusedResidentPayloadCount": len(unused_resident_payloads),
            "unusedResidentPayloadBytes": sum(map(len, unused_resident_payloads)),
            "demo": demo_residency,
            "fly": fly_residency,
            "effects": {
                "demo": kind_residency(demo_usage, effect_variant_ids),
                "fly": kind_residency(fly_usage, effect_variant_ids),
                "physicalHalfbanks": sorted(
                    {
                        STORAGE_PHYSICAL_HALFBANKS[sprite_locations[index].chunk]
                        for index in effect_variant_ids
                    }
                ),
            },
            "mdls": {
                "demo": kind_residency(demo_usage, mdl_variant_ids),
                "fly": kind_residency(fly_usage, mdl_variant_ids),
                "residentRequestedVariantCount": len(mdl_variant_ids),
            },
        },
        "coverage": {
            "projectedViews": sorted(
                {view for _name, _frame, view in ordered_variants}
            ),
            "sourceFrames": sorted({frame for _name, frame, _view in ordered_variants}),
            "retainedAnimationFrames": len(
                {(name, frame) for name, frame, _view in ordered_variants}
            ),
            "stateReferences": len(all_states),
            "variantCount": len(sprites),
            "residentRequestedVariantCount": len(sprites),
            "projectedUniqueSpriteRasters": len(all_projected_unique_payloads),
            "runtimeCandidateUniqueSpriteRasters": len(projected_unique_payloads),
            "uniqueResidentSpriteRasters": len(pixel_locations),
            "exactSpriteRasterDeduplications": len(all_projected_sprites)
            - len(all_projected_unique_payloads),
            "residentSpriteRasterReuses": len(sprites) - len(pixel_locations),
            "deduplicationStage": "complete encoded width/height/pixel rasters are canonicalized immediately after source billboard rasterization, before visibility and residency; exact identity only",
            "deduplicationTransforms": ["identity"],
            "rawPixelBytes": sum(
                len(sprite.pixels) for sprite in all_projected_sprites
            ),
            "residentPixelReferenceBytes": sum(
                len(sprite.pixels) for sprite in sprites
            ),
            "uniquePixelBytes": sum(len(payload) for payload in pixel_locations),
        },
        "staticStateCount": len(static_states),
        "format": {
            "mesenTarget": mesen_target.name,
            "configuredHalfbankCount": max_halfbanks,
            "maxGsuRomBank": mesen_target.max_gsu_rom_bank,
            "actualMaxGsuRomBank": actual_max_gsu_rom_bank,
            "headerBytes": HEADER.size,
            "rowDirectoryRecordBytes": ROW_DIRECTORY.size,
            "spriteDirectoryRecordBytes": SPRITE_DIRECTORY.size,
            "spriteDirectoryRecordCount": len(runtime_sprites),
            "stateRecordBytes": STATE_RECORD.size,
            "flyFacingRecordBytes": FLY_FACING_RECORD.size,
            "flyFacingRecordCount": len(fly_facing_payload) // FLY_FACING_RECORD.size,
            "flyFacingPackageOffset": fly_facing_location.flat_offset,
            "flyFacingBank": fly_facing_location.bank,
            "flyFacingAddress": fly_facing_location.address,
            "flyDirectionalSpriteTag": FLY_DIRECTIONAL_TAG,
            "groupHeaderBytes": GROUP_HEADER.size,
            "firstPhysicalHalfbank": FIRST_PHYSICAL_HALFBANK,
            "storagePhysicalHalfbanks": list(
                STORAGE_PHYSICAL_HALFBANKS[:max_halfbanks]
            ),
            "reclaimedSoundPhysicalHalfbanks": [],
            "reclaimedPvsPhysicalHalfbanks": [15] if max_halfbanks > 16 else [],
            "chunkCount": chunk_count,
            "chunkBytes": HALFBANK_BYTES,
            "reservedCapacityBytes": max_halfbanks * HALFBANK_BYTES,
            "usedThroughByte": packer.chunk * HALFBANK_BYTES + packer.cursor,
            "freeTailBytes": HALFBANK_BYTES - packer.cursor,
            "freeCapacityBytes": sum(
                HALFBANK_BYTES - cursor for cursor in packer.cursors
            ) + (max_halfbanks - len(packer.chunks)) * HALFBANK_BYTES,
            "placedPayloadBytes": packer.payload_bytes,
        },
        "outputs": {
            f"QuakeBSPAliasRuntime{index}.bin": {
                "bytes": len(chunk),
                "sha256": hashlib.sha256(chunk).hexdigest(),
            }
            for index, chunk in enumerate(chunks)
        },
    }
    return AliasAssetBuild(chunks, include, assembly, metadata)
