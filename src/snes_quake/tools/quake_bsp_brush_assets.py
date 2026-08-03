"""Pack compact E1M3 inline-brush assets for the shared SNES renderer."""

from __future__ import annotations

import hashlib
import json
import math
import struct
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import generate_quake_bsp as bsp_tools
from quake_bsp_brush_fragments import build_fragment_assets, fragment_variant_ids
from quake_brush_compact_replay import (
    COMPACT_ENTITY as COMPACT_ENTITY,
    COMPACT_EVENT as COMPACT_EVENT,
    COMPACT_REPLAY_HEADER as COMPACT_REPLAY_HEADER,
    COMPACT_REPLAY_MAGIC as COMPACT_REPLAY_MAGIC,
    COMPACT_REPLAY_VERSION as COMPACT_REPLAY_VERSION,
    COMPACT_VARIANT as COMPACT_VARIANT,
    CompactReplayBuild,
    DecodedCompactReplay as DecodedCompactReplay,
    build_compact_replay,
    decode_compact_replay,
    encode_compact_replay as encode_compact_replay,
    quantize_q3,
    require_compact_translation_only,
)
from quake_brush_replay import CanonicalBrushReplay


ASSET_MAGIC = b"QBSA"
ASSET_VERSION = 1
ASSET_HEADER = struct.Struct("<4sHHI6HQ")
ASSET_SECTION = struct.Struct("<8sBHHBH")
MODEL_RECORD = struct.Struct("<BBBB5H9h")
FACE_RECORD = struct.Struct("<HBBHH")
FACE_PLANE_RECORD = struct.Struct("<bbbh")
SHADING_RECORD = struct.Struct("<bbbB")
LIGHTMAP_RECORD = struct.Struct("<BHBBbb")
TEXTURE_RECORD = struct.Struct("<BHHHB")
ANIMATION_RECORD = struct.Struct("<BBBB10B10B")
VISUAL_STATE_RECORD = struct.Struct("<HHHBB")
VISUAL_TRANSFORM_RECORD = struct.Struct("<BB")
VISUAL_TEXTURE_RECORD = struct.Struct("<BBB")
STATIC_TRANSFORM_RECORD = struct.Struct("<HH")
ROM_BANK_BYTES = bsp_tools.ROM_BANK_BYTES
FIRST_BRUSH_TEXTURE_BANK = 42
RUNTIME_BANK_COUNT = 2
MAX_GSU_ROM_BANKS = 64
MODEL_CLASS_IDS = {
    "func_button": 1,
    "func_door": 2,
    "func_door_secret": 3,
    "func_plat": 4,
    "func_train": 5,
    "func_wall": 6,
}
SECTION_ORDER = (
    "REPLAY",
    "ROWSTATE",
    "VSTATES",
    "VTRANS",
    "VFRAG",
    "VSTATIC",
    "VTEX",
    "MODELS",
    "INDICES",
    "TEXCOORD",
    "FACES",
    "PLANES",
    "SHADING",
    "LIGHTDIR",
    "LIGHTS",
    "TEXDIR",
    "ANIM",
    "SOLID",
)
SECTION_RECORD_BYTES = {
    "REPLAY": 0,
    "ROWSTATE": 1,
    "VSTATES": VISUAL_STATE_RECORD.size,
    "VTRANS": VISUAL_TRANSFORM_RECORD.size,
    "VFRAG": 2,
    "VSTATIC": STATIC_TRANSFORM_RECORD.size,
    "VTEX": VISUAL_TEXTURE_RECORD.size,
    "MODELS": MODEL_RECORD.size,
    "INDICES": 2,
    "TEXCOORD": bsp_tools.TEXTURE_COORD_RECORD_BYTES,
    "FACES": FACE_RECORD.size,
    "PLANES": FACE_PLANE_RECORD.size,
    "SHADING": SHADING_RECORD.size,
    "LIGHTDIR": LIGHTMAP_RECORD.size,
    "LIGHTS": 1,
    "TEXDIR": TEXTURE_RECORD.size,
    "ANIM": ANIMATION_RECORD.size,
    "SOLID": 1,
}


@dataclass(frozen=True)
class BrushAssetBuild:
    outputs: dict[Path, bytes]
    metadata: dict[str, Any]


@dataclass(frozen=True)
class _ParsedBsp:
    entities: tuple[dict[str, str], ...]
    planes: tuple[tuple[object, ...], ...]
    vertices: tuple[tuple[float, float, float], ...]
    nodes: tuple[bsp_tools.Node, ...]
    texinfo: tuple[tuple[object, ...], ...]
    faces: tuple[bsp_tools.Face, ...]
    leaves: tuple[bsp_tools.Leaf, ...]
    edges: tuple[tuple[int, int], ...]
    surfedges: tuple[int, ...]
    models: tuple[tuple[object, ...], ...]
    textures: tuple[bsp_tools.MipTexture, ...]
    lighting: bytes


@dataclass(frozen=True)
class _Lightmap:
    source_face: int
    width: int
    height: int
    minimum_s: int
    minimum_t: int
    styles: tuple[int, ...]
    source_offset: int
    sample_offset: int
    samples: bytes
    missing_level: int = bsp_tools.LIGHTMAP_DARKEST_LEVEL


def _parse_bsp(bsp: bytes) -> _ParsedBsp:
    lumps = bsp_tools.lump_ranges(bsp)

    def records(index: int, fmt: str) -> tuple[tuple[object, ...], ...]:
        return tuple(
            bsp_tools.unpack_records(bsp_tools.lump_data(bsp, lumps, index), fmt)
        )

    node_records = records(bsp_tools.LUMP_NODES, "<ihh6hHH")
    face_records = records(bsp_tools.LUMP_FACES, "<hhihh4Bi")
    leaf_records = records(bsp_tools.LUMP_LEAVES, "<ii6hHH4B")
    return _ParsedBsp(
        tuple(
            bsp_tools.parse_entities(
                bsp_tools.lump_data(bsp, lumps, bsp_tools.LUMP_ENTITIES)
            )
        ),
        records(bsp_tools.LUMP_PLANES, "<ffffi"),
        tuple(
            tuple(float(value) for value in record)
            for record in records(bsp_tools.LUMP_VERTICES, "<fff")
        ),
        tuple(
            bsp_tools.Node(record[0], (record[1], record[2]), record[9], record[10])
            for record in node_records
        ),
        records(bsp_tools.LUMP_TEXINFO, "<8fii"),
        tuple(
            bsp_tools.Face(
                record[0],
                record[1],
                record[2],
                record[3],
                record[4],
                (record[5], record[6], record[7], record[8]),
                record[9],
            )
            for record in face_records
        ),
        tuple(
            bsp_tools.Leaf(record[0], record[1], record[8], record[9])
            for record in leaf_records
        ),
        tuple(
            (int(record[0]), int(record[1]))
            for record in records(bsp_tools.LUMP_EDGES, "<HH")
        ),
        tuple(int(record[0]) for record in records(bsp_tools.LUMP_SURFEDGES, "<i")),
        records(bsp_tools.LUMP_MODELS, "<9f7i"),
        tuple(
            bsp_tools.parse_textures(
                bsp_tools.lump_data(bsp, lumps, bsp_tools.LUMP_TEXTURES)
            )
        ),
        bsp_tools.lump_data(bsp, lumps, bsp_tools.LUMP_LIGHTING),
    )


def _face_vertex_ids(source: _ParsedBsp, face: bsp_tools.Face) -> tuple[int, ...]:
    output = []
    for index in range(face.first_edge, face.first_edge + face.edge_count):
        surfedge = source.surfedges[index]
        edge = source.edges[abs(surfedge)]
        output.append(edge[0] if surfedge >= 0 else edge[1])
    return tuple(output)


def _q2_world_vertices(
    source: _ParsedBsp, world_origin: tuple[float, float, float]
) -> tuple[tuple[int, int, int], ...]:
    output = []
    for vertex in source.vertices:
        packed = tuple(
            math.floor(
                (vertex[axis] - world_origin[axis]) * 4.0 / bsp_tools.WORLD_SCALE + 0.5
            )
            for axis in range(3)
        )
        if any(value < -0x8000 or value > 0x7FFF for value in packed):
            raise ValueError("brush dependency world vertex exceeds signed Q2")
        output.append(packed)
    return tuple(output)


def _entity_definitions(
    source: _ParsedBsp,
) -> tuple[dict[int, tuple[int, dict[str, str]]], list[dict[str, Any]]]:
    by_model: dict[int, tuple[int, dict[str, str]]] = {}
    for source_index, entity in enumerate(source.entities):
        model = entity.get("model", "")
        if not model.startswith("*") or not model[1:].isdigit():
            continue
        inline_model = int(model[1:])
        if inline_model <= 0 or inline_model in by_model:
            raise ValueError(f"invalid or duplicate inline model {model!r}")
        by_model[inline_model] = (source_index, entity)
    return by_model, []


def _animation_groups(
    textures: tuple[bsp_tools.MipTexture, ...],
    directly_referenced: set[int],
) -> tuple[dict[str, dict[str, list[int]]], set[int]]:
    all_groups: dict[str, dict[str, dict[int, int]]] = {}
    for source_id, texture in enumerate(textures):
        if len(texture.name) < 3 or not texture.name.startswith("+"):
            continue
        frame = texture.name[1].lower()
        suffix = texture.name[2:].lower()
        if frame.isdigit():
            sequence = "regular"
            frame_index = int(frame)
        elif "a" <= frame <= "j":
            sequence = "alternate"
            frame_index = ord(frame) - ord("a")
        else:
            raise ValueError(
                f"animated miptex {texture.name!r} has an invalid frame name"
            )
        group = all_groups.setdefault(suffix, {"regular": {}, "alternate": {}})
        if frame_index in group[sequence]:
            raise ValueError(f"duplicate animated miptex frame {texture.name!r}")
        group[sequence][frame_index] = source_id

    selected: dict[str, dict[str, list[int]]] = {}
    closure = set(directly_referenced)
    for source_id in sorted(directly_referenced):
        name = textures[source_id].name
        if not name.startswith("+"):
            continue
        suffix = name[2:].lower()
        raw = all_groups[suffix]
        group: dict[str, list[int]] = {}
        for sequence in ("regular", "alternate"):
            indices = raw[sequence]
            if indices and sorted(indices) != list(range(max(indices) + 1)):
                raise ValueError(
                    f"animated texture family {suffix!r} has a gap in {sequence} frames"
                )
            group[sequence] = [indices[index] for index in sorted(indices)]
            closure.update(group[sequence])
        if not group["regular"]:
            raise ValueError(f"animated texture family {suffix!r} has no regular frame")
        selected[suffix] = group
    return selected, closure


def _texture_assets(
    source: _ParsedBsp,
    source_face_ids: tuple[int, ...],
    first_bank: int,
) -> tuple[
    dict[int, int],
    tuple[bytes, ...],
    bytes,
    bytes,
    dict[str, Any],
    dict[int, str],
]:
    world = source.models[0]
    world_faces = range(int(world[14]), int(world[14]) + int(world[15]))
    world_texture_ids = sorted(
        {
            int(source.texinfo[source.faces[face].texinfo][8])
            for face in world_faces
            if source.textures[
                int(source.texinfo[source.faces[face].texinfo][8])
            ].pixels
        }
    )
    world_packed = {
        source_id: packed_id for packed_id, source_id in enumerate(world_texture_ids)
    }
    direct_ids = {
        int(source.texinfo[source.faces[face].texinfo][8]) for face in source_face_ids
    }
    for source_id in direct_ids:
        if not 0 <= source_id < len(source.textures):
            raise ValueError(f"brush face names missing miptex {source_id}")
        if not source.textures[source_id].pixels:
            raise ValueError(
                f"brush face names miptex {source_id} without level-0 pixels"
            )
    animation_groups, closure_ids = _animation_groups(source.textures, direct_ids)
    masked_ids = sorted(
        source_id
        for source_id in closure_ids
        if source.textures[source_id].name.startswith("{")
    )
    if masked_ids:
        raise ValueError(
            f"brush textures require unsupported masked semantics: {masked_ids}"
        )
    extra_ids = sorted(closure_ids - set(world_packed))
    source_to_packed = dict(world_packed)
    source_to_packed.update(
        {
            source_id: len(world_packed) + offset
            for offset, source_id in enumerate(extra_ids)
        }
    )
    if len(source_to_packed) > 0x100:
        raise ValueError("brush animation closure exceeds uint8 packed texture IDs")
    payloads = tuple(source.textures[source_id].pixels for source_id in extra_ids)
    if not payloads:
        raise ValueError("brush assets unexpectedly need no extra textures")
    chunks: tuple[bytes, ...] | None = None
    placements: tuple[bsp_tools.PackedTexturePlacement, ...] | None = None
    last_error = ""
    for bank_count in range(1, MAX_GSU_ROM_BANKS - first_bank + 1):
        try:
            chunks, placements = bsp_tools.pack_texture_bank_images(
                payloads, bank_count=bank_count
            )
            break
        except ValueError as error:
            last_error = str(error)
    if chunks is None or placements is None:
        names = ", ".join(source.textures[index].name for index in extra_ids)
        raise ValueError(
            f"brush texture bank capacity overflow for [{names}]: {last_error}"
        )

    directory = bytearray()
    texture_records: list[dict[str, Any]] = []
    for source_id, placement in zip(extra_ids, placements, strict=True):
        texture = source.textures[source_id]
        bank = first_bank + placement.bank_index
        address = 0x8000 + placement.bank_offset
        flags = (
            bsp_tools.TEXTURE_FLAG_POWER_OF_TWO_AXES
            if (
                texture.width & (texture.width - 1) == 0
                and texture.height & (texture.height - 1) == 0
            )
            else 0
        )
        if placement.single_bank:
            flags |= bsp_tools.TEXTURE_FLAG_SINGLE_BANK
        directory.extend(
            TEXTURE_RECORD.pack(bank, address, texture.width, texture.height, flags)
        )
        texture_records.append(
            {
                "packedId": source_to_packed[source_id],
                "sourceMiptexId": source_id,
                "name": texture.name,
                "dimensions": [texture.width, texture.height],
                "level0Bytes": len(texture.pixels),
                "level0Sha256": hashlib.sha256(texture.pixels).hexdigest(),
                "bank": bank,
                "address": address,
                "bankSpan": placement.bank_span,
                "singleBank": placement.single_bank,
            }
        )

    animation = bytearray()
    animation_records: list[dict[str, Any]] = []
    animation_name_by_source: dict[int, str] = {}
    for suffix, group in sorted(animation_groups.items()):
        regular = group["regular"]
        alternate = group["alternate"]
        if len(regular) > 10 or len(alternate) > 10:
            raise ValueError(
                f"animated texture family {suffix!r} exceeds 10-frame bound"
            )
        regular_packed = [source_to_packed[index] for index in regular]
        alternate_packed = [source_to_packed[index] for index in alternate]
        for source_id in (*regular, *alternate):
            animation_name_by_source[source_id] = suffix
        animation.extend(
            ANIMATION_RECORD.pack(
                source_to_packed[regular[0]],
                len(regular),
                len(alternate),
                2,
                *(regular_packed + [0xFF] * (10 - len(regular_packed))),
                *(alternate_packed + [0xFF] * (10 - len(alternate_packed))),
            )
        )
        animation_records.append(
            {
                "name": suffix,
                "intervalTenths": 2,
                "regularSourceIds": regular,
                "alternateSourceIds": alternate,
                "regularPackedIds": regular_packed,
                "alternatePackedIds": alternate_packed,
            }
        )

    direct_reference_bytes = sum(
        len(source.textures[int(source.texinfo[source.faces[face].texinfo][8])].pixels)
        for face in source_face_ids
    )
    unique_closure_bytes = sum(
        len(source.textures[source_id].pixels) for source_id in closure_ids
    )
    metadata = {
        "worldPackedTextureCount": len(world_packed),
        "worldReusedSourceIds": sorted(direct_ids & set(world_packed)),
        "directSourceIds": sorted(direct_ids),
        "directTextureCount": len(direct_ids),
        "animationClosureSourceIds": sorted(closure_ids),
        "animationClosureTextureCount": len(closure_ids),
        "maskedTextureCount": len(masked_ids),
        "extraSourceIds": extra_ids,
        "extraTextureCount": len(extra_ids),
        "extraSourceBytes": sum(len(payload) for payload in payloads),
        "packedBankCount": len(chunks),
        "packedBytes": len(chunks) * ROM_BANK_BYTES,
        "deduplication": {
            "faceTextureReferences": len(source_face_ids),
            "naiveRepeatedLevel0Bytes": direct_reference_bytes,
            "uniqueAnimationClosedLevel0Bytes": unique_closure_bytes,
            "savedBytesBeforeBankPadding": (
                direct_reference_bytes - unique_closure_bytes
            ),
        },
        "textures": texture_records,
        "animations": animation_records,
        "directoryBytes": len(directory),
        "animationBytes": len(animation),
    }
    return (
        source_to_packed,
        chunks,
        bytes(directory),
        bytes(animation),
        metadata,
        animation_name_by_source,
    )


def _pack_lightmaps(
    source: _ParsedBsp, source_face_ids: tuple[int, ...]
) -> tuple[list[_Lightmap], bytes, dict[str, Any]]:
    records: list[_Lightmap] = []
    samples = bytearray()
    lit_count = 0
    maximum = 0
    for source_face in source_face_ids:
        face = source.faces[source_face]
        polygon = [source.vertices[index] for index in _face_vertex_ids(source, face)]
        texture = source.texinfo[face.texinfo]
        coordinate_s = [
            sum(float(texture[axis]) * vertex[axis] for axis in range(3))
            + float(texture[3])
            for vertex in polygon
        ]
        coordinate_t = [
            sum(float(texture[axis + 4]) * vertex[axis] for axis in range(3))
            + float(texture[7])
            for vertex in polygon
        ]
        minimum_s = math.floor(min(coordinate_s) / 16.0)
        minimum_t = math.floor(min(coordinate_t) / 16.0)
        maximum_s = math.ceil(max(coordinate_s) / 16.0)
        maximum_t = math.ceil(max(coordinate_t) / 16.0)
        width = maximum_s - minimum_s + 1
        height = maximum_t - minimum_t + 1
        if not (-128 <= minimum_s <= 127 and -128 <= minimum_t <= 127):
            raise ValueError(f"brush face {source_face} lightmap minimum exceeds int8")
        if not (1 <= width <= 255 and 1 <= height <= 255):
            raise ValueError(
                f"brush face {source_face} lightmap dimensions exceed uint8"
            )
        try:
            style_count = face.light_styles.index(255)
        except ValueError:
            style_count = 4
        if face.light_offset == -1:
            if style_count:
                raise ValueError(f"brush face {source_face} has styles without samples")
            texture_id = int(texture[8])
            if not 0 <= texture_id < len(source.textures):
                raise ValueError(
                    f"unlightmapped brush face {source_face} has invalid texture"
                )
            missing_level = bsp_tools.missing_lightmap_level(
                source.textures[texture_id].name
            )
            records.append(
                _Lightmap(
                    source_face,
                    0,
                    0,
                    0,
                    0,
                    (),
                    -1,
                    0,
                    b"",
                    missing_level,
                )
            )
            continue
        sample_count = width * height
        required = sample_count * style_count
        if (
            face.light_offset < 0
            or style_count <= 0
            or face.light_offset + required > len(source.lighting)
        ):
            raise ValueError(f"brush face {source_face} lightmap escapes source lump")
        packed = bytearray(sample_count)
        for sample_index in range(sample_count):
            accumulated = sum(
                source.lighting[face.light_offset + style * sample_count + sample_index]
                * bsp_tools.QUAKE_NEUTRAL_LIGHT_STYLE_SCALE
                for style in range(style_count)
            )
            inverted = max(0, 255 * 256 - accumulated)
            packed[sample_index] = min(63, max(1 << 6, inverted >> 2) >> 8)
        if len(packed) > bsp_tools.LIGHTMAP_FACE_CACHE_BYTES:
            raise ValueError(
                f"brush face {source_face} lightmap needs {len(packed)} "
                f"bytes; face-cache bound is "
                f"{bsp_tools.LIGHTMAP_FACE_CACHE_BYTES}"
            )
        offset = len(samples)
        samples.extend(packed)
        records.append(
            _Lightmap(
                source_face,
                width,
                height,
                minimum_s,
                minimum_t,
                tuple(face.light_styles[:style_count]),
                face.light_offset,
                offset,
                bytes(packed),
            )
        )
        lit_count += 1
        maximum = max(maximum, len(packed))
    metadata = {
        "faceCount": len(records),
        "lightmappedFaceCount": lit_count,
        "unlightmappedFaceCount": len(records) - lit_count,
        "sampleBytes": len(samples),
        "maximumFaceSampleBytes": maximum,
        "faceCacheCapacityBytes": bsp_tools.LIGHTMAP_FACE_CACHE_BYTES,
        "sourceRecordsSha256": hashlib.sha256(
            json.dumps(
                [
                    {
                        "face": record.source_face,
                        "dimensions": [record.width, record.height],
                        "minimum": [record.minimum_s, record.minimum_t],
                        "styles": list(record.styles),
                        "sourceOffset": record.source_offset,
                        "samples": record.samples.hex(),
                    }
                    for record in records
                ],
                sort_keys=True,
                separators=(",", ":"),
            ).encode("ascii")
        ).hexdigest(),
    }
    return records, bytes(samples), metadata


def _lightmap_directory(records: list[_Lightmap], bank: int, address: int) -> bytes:
    output = bytearray()
    for record in records:
        if not record.samples:
            level = bsp_tools.LIGHTMAP_ENCODED_LEVEL_BIAS + record.missing_level
            output.extend(LIGHTMAP_RECORD.pack(0xFF, level, 0, 0, 0, 0))
            continue
        sample_address = address + record.sample_offset
        if sample_address > 0xFFFF:
            raise ValueError(
                f"brush lightmap face {record.source_face} crosses a ROM bank"
            )
        output.extend(
            LIGHTMAP_RECORD.pack(
                bank,
                sample_address,
                record.width,
                record.height,
                record.minimum_s,
                record.minimum_t,
            )
        )
    return bytes(output)


def _material_record(
    source: _ParsedBsp,
    face: bsp_tools.Face,
    polygon: list[tuple[float, float, float]],
    world_origin: tuple[float, float, float],
    texture_families: list[int],
) -> tuple[int, int, int, int]:
    plane = source.planes[face.plane]
    direction = -1.0 if face.side else 1.0
    normal = tuple(float(plane[axis]) * direction for axis in range(3))
    centroid = tuple(
        sum(vertex[axis] for vertex in polygon) / len(polygon) for axis in range(3)
    )
    packed_centroid = tuple(
        (
            bsp_tools.round_half_up(
                (centroid[axis] - world_origin[axis]) / bsp_tools.WORLD_SCALE
            )
            if centroid[axis] >= world_origin[axis]
            else -bsp_tools.round_half_up(
                (world_origin[axis] - centroid[axis]) / bsp_tools.WORLD_SCALE
            )
        )
        for axis in range(3)
    )
    if any(
        value < bsp_tools.WORLD_COORD_MIN or value > bsp_tools.WORLD_COORD_MAX
        for value in packed_centroid
    ):
        raise ValueError("brush face centroid exceeds signed-byte storage")
    source_texture = int(source.texinfo[face.texinfo][8])
    family = texture_families[source_texture]
    base_shade = (
        family * bsp_tools.APPARENT_LIGHT_LEVELS
        + bsp_tools.orientation_light_level(normal)
    )
    return (*packed_centroid, base_shade)


def _model_and_geometry_assets(
    source: _ParsedBsp,
    replay: CanonicalBrushReplay,
    palette: bytes,
    source_to_packed: dict[int, int],
    source_face_ids: tuple[int, ...],
) -> tuple[dict[str, bytes], dict[int, tuple[int, ...]], dict[str, Any]]:
    definitions, _unused = _entity_definitions(source)
    signon = {state.inline_model: state for state in replay.signon_brushes}
    active_models = {state.inline_model for row in replay.rows for state in row.brushes}
    world = source.models[0]
    world_origin = tuple(
        (float(world[axis]) + float(world[axis + 3])) * 0.5 for axis in range(3)
    )
    world_q2 = _q2_world_vertices(source, world_origin)
    expected_world_vertices = b"".join(
        bsp_tools.pack_q2_world_vertex(vertex) for vertex in world_q2
    )
    source_palette = bsp_tools.quake_palette(palette)
    _hues, texture_families, _material_palette = bsp_tools.build_material_palette(
        list(source.textures),
        source_palette,
        list(source.texinfo),
        list(source.faces),
    )

    models = bytearray()
    indices = bytearray()
    texture_coordinates = bytearray()
    faces = bytearray()
    planes = bytearray()
    shading = bytearray()
    model_face_textures: dict[int, tuple[int, ...]] = {}
    model_records: list[dict[str, Any]] = []
    seen_source_faces: list[int] = []
    referenced_vertices: set[int] = set()
    referenced_texinfo: set[int] = set()
    for packed_model, inline_model in enumerate(sorted(signon)):
        baseline = signon[inline_model]
        if inline_model not in definitions:
            raise ValueError(f"signon brush model *{inline_model} has no BSP entity")
        source_entity, definition = definitions[inline_model]
        model = source.models[inline_model]
        source_first_face = int(model[14])
        source_face_count = int(model[15])
        first_packed_face = len(faces) // FACE_RECORD.size
        first_packed_index = len(indices) // 2
        model_texture_ids: list[int] = []
        for source_face in range(
            source_first_face, source_first_face + source_face_count
        ):
            if source_face != source_face_ids[len(seen_source_faces)]:
                raise AssertionError("brush source-face order is inconsistent")
            seen_source_faces.append(source_face)
            face = source.faces[source_face]
            vertex_ids = _face_vertex_ids(source, face)
            if not 3 <= len(vertex_ids) <= 0xFF:
                raise ValueError(f"brush face {source_face} index count exceeds uint8")
            first_index = len(indices) // 2
            if first_index + len(vertex_ids) > 0x10000:
                raise ValueError(
                    f"brush face {source_face} exceeds uint16 index addressing"
                )
            for vertex_id in vertex_ids:
                indices.extend(struct.pack("<H", vertex_id))
                referenced_vertices.add(vertex_id)
            texture = source.texinfo[face.texinfo]
            source_texture = int(texture[8])
            packed_texture = source_to_packed[source_texture]
            model_texture_ids.append(source_texture)
            referenced_texinfo.add(face.texinfo)
            polygon = [source.vertices[index] for index in vertex_ids]
            for vertex in polygon:
                coordinate_s = sum(
                    float(texture[axis]) * vertex[axis] for axis in range(3)
                ) + float(texture[3])
                coordinate_t = sum(
                    float(texture[axis + 4]) * vertex[axis] for axis in range(3)
                ) + float(texture[7])
                s_q4 = bsp_tools.round_half_away_from_zero(coordinate_s * 16.0)
                t_q4 = bsp_tools.round_half_away_from_zero(coordinate_t * 16.0)
                if not (-0x8000 <= s_q4 <= 0x7FFF and -0x8000 <= t_q4 <= 0x7FFF):
                    raise ValueError(
                        f"brush face {source_face} texture coordinate exceeds signed Q4"
                    )
                texture_coordinates.extend(struct.pack("<hh", s_q4, t_q4))
            faces.extend(
                FACE_RECORD.pack(
                    first_index,
                    len(vertex_ids),
                    packed_texture,
                    face.texinfo,
                    source_face,
                )
            )
            polygon_q2 = [world_q2[index] for index in vertex_ids]
            normal, distance = bsp_tools.quantized_face_plane(polygon_q2)
            planes.extend(FACE_PLANE_RECORD.pack(*normal, distance))
            shading.extend(
                SHADING_RECORD.pack(
                    *_material_record(
                        source,
                        face,
                        polygon,
                        world_origin,
                        texture_families,
                    )
                )
            )
        model_face_textures[inline_model] = tuple(model_texture_ids)
        bounds = tuple(round(float(model[index])) for index in range(6))
        if any(float(model[index]) != bounds[index] for index in range(6)) or any(
            not -0x8000 <= value <= 0x7FFF for value in bounds
        ):
            raise ValueError(f"brush model *{inline_model} bounds exceed exact int16")
        origin_q3 = tuple(
            quantize_q3(value, label=f"brush model *{inline_model} baseline origin")
            for value in baseline.origin
        )
        class_name = definition.get("classname", "")
        class_id = MODEL_CLASS_IDS.get(class_name)
        if class_id is None:
            raise ValueError(
                f"brush model *{inline_model} has unsupported class {class_name!r}"
            )
        model_index_count = len(indices) // 2 - first_packed_index
        flags = 1 if inline_model in active_models else 2
        models.extend(
            MODEL_RECORD.pack(
                baseline.entity_number,
                inline_model,
                class_id,
                flags,
                source_first_face,
                source_face_count,
                first_packed_face,
                first_packed_index,
                model_index_count,
                *bounds,
                *origin_q3,
            )
        )
        model_records.append(
            {
                "packedModel": packed_model,
                "entity": baseline.entity_number,
                "inlineModel": inline_model,
                "modelPrecacheIndex": baseline.model_index,
                "sourceEntity": source_entity,
                "classname": class_name,
                "everActiveInReplay": inline_model in active_models,
                "sourceFirstFace": source_first_face,
                "sourceFaceCount": source_face_count,
                "packedFirstFace": first_packed_face,
                "packedFirstIndex": first_packed_index,
                "packedIndexCount": model_index_count,
                "sourceBounds": [*bounds[:3], *bounds[3:]],
                "baselineOriginQ3": list(origin_q3),
            }
        )

    if tuple(seen_source_faces) != source_face_ids:
        raise AssertionError("brush geometry lost source-face identity")
    texinfo_source_bytes = b"".join(
        struct.pack("<8fii", *source.texinfo[index])
        for index in sorted(referenced_texinfo)
    )
    sections = {
        "MODELS": bytes(models),
        "INDICES": bytes(indices),
        "TEXCOORD": bytes(texture_coordinates),
        "FACES": bytes(faces),
        "PLANES": bytes(planes),
        "SHADING": bytes(shading),
    }
    metadata = {
        "modelCount": len(model_records),
        "everActiveModelCount": len(active_models),
        "signonOnlyModelCount": len(model_records) - len(active_models),
        "faceCount": len(source_face_ids),
        "indexCount": len(indices) // 2,
        "referencedWorldVertexCount": len(referenced_vertices),
        "worldVertexDependency": {
            "file": "QuakeBSPWorldVertices.bin",
            "recordBytes": 4,
            "sourceVertexCount": len(world_q2),
            "bytes": len(expected_world_vertices),
            "sha256": hashlib.sha256(expected_world_vertices).hexdigest(),
            "referencedIdsMinimum": min(referenced_vertices),
            "referencedIdsMaximum": max(referenced_vertices),
        },
        "referencedTexinfoCount": len(referenced_texinfo),
        "referencedTexinfoIds": sorted(referenced_texinfo),
        "referencedTexinfoSha256": hashlib.sha256(texinfo_source_bytes).hexdigest(),
        "sourceFaceIdsSha256": hashlib.sha256(
            b"".join(struct.pack("<H", face) for face in source_face_ids)
        ).hexdigest(),
        "models": model_records,
    }
    return sections, model_face_textures, metadata


def _resolve_animated_texture(
    source_texture: int,
    entity_frame: int,
    tenths: int,
    animations: dict[str, dict[str, list[int]]],
    textures: tuple[bsp_tools.MipTexture, ...],
) -> int:
    name = textures[source_texture].name
    if not name.startswith("+"):
        return source_texture
    group = animations[name[2:].lower()]
    sequence = (
        group["alternate"] if entity_frame and group["alternate"] else group["regular"]
    )
    return sequence[(tenths // 2) % len(sequence)]


def _visual_states(
    source: _ParsedBsp,
    replay: CanonicalBrushReplay,
    compact: CompactReplayBuild,
    model_face_textures: dict[int, tuple[int, ...]],
    source_to_packed: dict[int, int],
) -> tuple[dict[str, bytes], dict[str, Any]]:
    directly_referenced = {
        texture for textures in model_face_textures.values() for texture in textures
    }
    animations, _closure = _animation_groups(source.textures, directly_referenced)
    keys: dict[
        tuple[tuple[tuple[int, int], ...], tuple[tuple[int, int, int], ...]],
        int,
    ] = {}
    row_ids = bytearray()
    state_records: list[
        tuple[tuple[tuple[int, int], ...], tuple[tuple[int, int, int], ...]]
    ] = []
    for row, transforms in zip(replay.rows, compact.row_transforms, strict=True):
        tenths = (
            row.index + compact.metadata["textureAnimationClock"]["textureClockBias"]
        ) // 3
        textures: list[tuple[int, int, int]] = []
        for state in row.brushes:
            slot = compact.slot_by_entity[state.entity_number]
            for local_face, source_texture in enumerate(
                model_face_textures[state.inline_model]
            ):
                if not source.textures[source_texture].name.startswith("+"):
                    continue
                resolved_source = _resolve_animated_texture(
                    source_texture,
                    state.frame,
                    tenths,
                    animations,
                    source.textures,
                )
                textures.append((slot, local_face, source_to_packed[resolved_source]))
        key = (transforms, tuple(textures))
        state_id = keys.get(key)
        if state_id is None:
            state_id = len(state_records) + 1
            if state_id > 0xFF:
                raise ValueError(
                    "resolved brush visual states exceed uint8 bound "
                    f"(needed at canonical row {row.index})"
                )
            keys[key] = state_id
            state_records.append(key)
        row_ids.append(state_id)

    directories = bytearray()
    transform_entries = bytearray()
    texture_entries = bytearray()
    max_transforms = 0
    max_textures = 0
    for transforms, textures in state_records:
        first_transform = len(transform_entries) // VISUAL_TRANSFORM_RECORD.size
        first_texture = len(texture_entries) // VISUAL_TEXTURE_RECORD.size
        if len(transforms) > 0xFF or len(textures) > 0xFF:
            raise ValueError("one resolved brush visual state exceeds uint8 counts")
        directories.extend(
            VISUAL_STATE_RECORD.pack(
                first_transform,
                first_texture,
                0,
                len(transforms),
                len(textures),
            )
        )
        for slot, local_variant in reversed(transforms):
            transform_entries.extend(VISUAL_TRANSFORM_RECORD.pack(slot, local_variant))
        for slot, local_face, packed_texture in textures:
            texture_entries.extend(
                VISUAL_TEXTURE_RECORD.pack(slot, local_face, packed_texture)
            )
        max_transforms = max(max_transforms, len(transforms))
        max_textures = max(max_textures, len(textures))
    sections = {
        "ROWSTATE": bytes(row_ids),
        "VSTATES": bytes(directories),
        "VTRANS": bytes(transform_entries),
        "VTEX": bytes(texture_entries),
    }
    metadata = {
        "disabledStateId": 0,
        "firstEnabledStateId": 1,
        "visualStateCount": len(state_records),
        "rowStateBytes": len(row_ids),
        "rowStateSha256": hashlib.sha256(row_ids).hexdigest(),
        "stateRecordBytes": VISUAL_STATE_RECORD.size,
        "transformRecordBytes": VISUAL_TRANSFORM_RECORD.size,
        "resolvedTextureRecordBytes": VISUAL_TEXTURE_RECORD.size,
        "transformRecordCount": len(transform_entries) // VISUAL_TRANSFORM_RECORD.size,
        "resolvedTextureRecordCount": len(texture_entries)
        // VISUAL_TEXTURE_RECORD.size,
        "maximumTransformsPerState": max_transforms,
        "maximumResolvedTexturesPerState": max_textures,
        "contract": (
            "row ID is indexed by the canonical camera row; state 0 disables "
            "brushes, IDs 1..N atomically select transforms and exact resolved "
            "animated-face texture identities"
        ),
        "timingStorage": "none",
    }
    return sections, metadata


def _compact_to_fragment_variants(
    replay: CanonicalBrushReplay, compact: CompactReplayBuild
) -> bytes:
    first_by_entity = {
        record["entity"]: record["firstVariant"]
        for record in compact.metadata["entities"]
    }
    geometry_ids = fragment_variant_ids(replay)
    mapping: list[int | None] = [None] * compact.metadata["variantCount"]
    for state, local_variant in compact.local_variant_by_state.items():
        global_variant = first_by_entity[state.entity_number] + local_variant
        key = (
            state.inline_model,
            *(
                quantize_q3(value, label="fragment variant origin")
                for value in state.origin
            ),
        )
        mapping[global_variant] = geometry_ids[key]
    if any(value is None for value in mapping):
        raise AssertionError("compact-to-fragment variant mapping has a hole")
    return b"".join(struct.pack("<H", value) for value in mapping if value is not None)


def _static_fragment_variants(replay: CanonicalBrushReplay) -> bytes:
    """Map signon-only fly entities directly to camera-independent QBSF poses."""
    replayed_entities = {
        state.entity_number for row in replay.rows for state in row.brushes
    }
    geometry_ids = fragment_variant_ids(replay)
    records = bytearray()
    for state in sorted(
        (
            item
            for item in replay.signon_brushes
            if item.entity_number not in replayed_entities
        ),
        key=lambda item: (item.entity_number, item.inline_model),
        reverse=True,
    ):
        key = (
            state.inline_model,
            *(
                quantize_q3(value, label="static fragment origin")
                for value in state.origin
            ),
        )
        records.extend(
            STATIC_TRANSFORM_RECORD.pack(state.entity_number, geometry_ids[key])
        )
    return bytes(records)


def _fragment_link_bounds(
    compact: CompactReplayBuild,
    visual_sections: dict[str, bytes],
    compact_to_fragments: bytes,
    static_fragments: bytes,
    fragment_metadata: dict[str, Any],
    variant_leaf_groups: tuple[dict[int, tuple[int, int]], ...],
) -> dict[str, int]:
    """Prove the non-solid link demand for replay and full-map fly snapshots."""
    variants = fragment_metadata["variants"]

    def non_solid(variant: int) -> tuple[int, int]:
        record = variants[variant]
        return (
            int(record["fragmentCount"]) - int(record["solidFragmentCount"]),
            int(record["nonSolidBucketCount"]),
        )

    fragment_ids = struct.unpack(
        f"<{len(compact_to_fragments) // 2}H", compact_to_fragments
    )
    entities = sorted(compact.metadata["entities"], key=lambda item: item["slot"])
    states = visual_sections["VSTATES"]
    transforms = visual_sections["VTRANS"]
    replay_maximum = 0
    replay_leaf_marker_maximum = 0

    def group_bounds(variant_ids: Iterable[int]) -> tuple[int, int]:
        groups: dict[int, tuple[int, int]] = {}
        for variant in variant_ids:
            for leaf, (fragments, vertices) in variant_leaf_groups[variant].items():
                old_fragments, old_vertices = groups.get(leaf, (0, 0))
                groups[leaf] = (
                    old_fragments + fragments,
                    old_vertices + vertices,
                )
        if not groups:
            return 0, 0
        # Four frustum planes can each add at most one vertex to one convex
        # source polygon. This is a camera-independent allocation bound.
        return (
            max(fragments for fragments, _vertices in groups.values()),
            max(vertices + 4 * fragments for fragments, vertices in groups.values()),
        )

    replay_group_fragments = 0
    replay_group_projected_vertices = 0
    state_fragment_variants: list[tuple[int, ...]] = []
    for state_offset in range(0, len(states), VISUAL_STATE_RECORD.size):
        first_transform, _first_texture, _reserved, count, _texture_count = (
            VISUAL_STATE_RECORD.unpack_from(states, state_offset)
        )
        demand = 0
        leaf_marker_demand = 0
        active_fragment_variants: list[int] = []
        for index in range(count):
            slot, local_variant = VISUAL_TRANSFORM_RECORD.unpack_from(
                transforms,
                (first_transform + index) * VISUAL_TRANSFORM_RECORD.size,
            )
            compact_variant = int(entities[slot]["firstVariant"]) + local_variant
            fragment_variant = fragment_ids[compact_variant]
            active_fragment_variants.append(fragment_variant)
            links, leaf_markers = non_solid(fragment_variant)
            demand += links
            leaf_marker_demand += leaf_markers
        state_fragment_variants.append(tuple(active_fragment_variants))
        replay_maximum = max(replay_maximum, demand)
        replay_leaf_marker_maximum = max(replay_leaf_marker_maximum, leaf_marker_demand)
        group_fragments, group_vertices = group_bounds(active_fragment_variants)
        replay_group_fragments = max(replay_group_fragments, group_fragments)
        replay_group_projected_vertices = max(
            replay_group_projected_vertices, group_vertices
        )
    static_bounds = [
        non_solid(variant)
        for _entity, variant in struct.iter_unpack(
            STATIC_TRANSFORM_RECORD.format, static_fragments
        )
    ]
    static_maximum = sum(links for links, _leaf_markers in static_bounds)
    static_leaf_markers = sum(leaf_markers for _links, leaf_markers in static_bounds)
    static_variants = tuple(
        variant
        for _entity, variant in struct.iter_unpack(
            STATIC_TRANSFORM_RECORD.format, static_fragments
        )
    )
    fly_group_fragments = 0
    fly_group_projected_vertices = 0
    for replay_variants in state_fragment_variants:
        group_fragments, group_vertices = group_bounds(
            (*replay_variants, *static_variants)
        )
        fly_group_fragments = max(fly_group_fragments, group_fragments)
        fly_group_projected_vertices = max(fly_group_projected_vertices, group_vertices)
    return {
        "recordBytes": 4,
        "replayMaximumNonSolidLinks": replay_maximum,
        "staticBaselineNonSolidLinks": static_maximum,
        "flyCombinedMaximumNonSolidLinks": replay_maximum + static_maximum,
        "replayMaximumLeafMarkers": replay_leaf_marker_maximum,
        "staticBaselineLeafMarkers": static_leaf_markers,
        "flyCombinedMaximumLeafMarkers": (
            replay_leaf_marker_maximum + static_leaf_markers
        ),
        "replayMaximumLeafGroupFragments": replay_group_fragments,
        "replayMaximumLeafGroupProjectedVertices": (replay_group_projected_vertices),
        "flyCombinedMaximumLeafGroupFragments": fly_group_fragments,
        "flyCombinedMaximumLeafGroupProjectedVertices": (fly_group_projected_vertices),
    }


def _exclusion_audit(
    source: _ParsedBsp, replay: CanonicalBrushReplay
) -> dict[str, Any]:
    signon_models = {state.inline_model for state in replay.signon_brushes}
    definitions, _unused = _entity_definitions(source)
    inline_exclusions: list[dict[str, Any]] = []
    for inline_model in sorted(set(definitions) - signon_models):
        source_entity, entity = definitions[inline_model]
        classname = entity.get("classname", "")
        spawnflags = int(entity.get("spawnflags", "0"))
        if classname.startswith("trigger_"):
            reason = "nonrendered trigger collision/hull volume"
        elif classname == "func_wall" and spawnflags & 0x700 == 0x700:
            reason = "inhibited on all single-player skill levels"
        else:
            reason = "not spawned into the demo signon"
        inline_exclusions.append(
            {
                "sourceEntity": source_entity,
                "inlineModel": inline_model,
                "classname": classname,
                "spawnflags": spawnflags,
                "reason": reason,
            }
        )
    zero_model_triggers = [
        {
            "sourceEntity": source_entity,
            "classname": entity.get("classname", ""),
            "reason": "trigger has no nonzero inline render model",
        }
        for source_entity, entity in enumerate(source.entities)
        if entity.get("classname", "").startswith("trigger_")
        and (not entity.get("model") or entity.get("model") in {"0", "*0"})
    ]
    mdl_precache = [
        {
            "modelPrecacheIndex": index,
            "name": name,
            "reason": "alias/MDL model is outside inline BSP brush assets",
        }
        for index, name in enumerate(replay.model_precache)
        if name.lower().endswith(".mdl")
    ]
    return {
        "inlineModelCount": len(inline_exclusions),
        "inlineModels": inline_exclusions,
        "zeroModelTriggerCount": len(zero_model_triggers),
        "zeroModelTriggers": zero_model_triggers,
        "mdlPrecacheCount": len(mdl_precache),
        "mdlPrecache": mdl_precache,
        "worldModel": {
            "inlineModel": 0,
            "reason": "already supplied by QuakeBSPWorld* assets",
        },
        "unusedBspHullData": {
            "headnodesPerModel": 4,
            "packedHeadnodesPerModel": 0,
            "reason": (
                "visual rendering consumes draw faces; collision hull "
                "headnodes and clipnodes remain intentionally unpacked"
            ),
        },
    }


def _solid_leaf_bitset(source: _ParsedBsp) -> bytes:
    output = bytearray((len(source.leaves) + 7) // 8)
    for leaf, record in enumerate(source.leaves):
        if record.contents == -2:
            output[leaf >> 3] |= 1 << (leaf & 7)
    return bytes(output)


def _place_runtime_sections(
    sections: dict[str, bytes],
    record_counts: dict[str, int],
    first_bank: int,
    leaf_count: int,
) -> tuple[tuple[bytes, ...], dict[str, Any]]:
    if tuple(sections) != SECTION_ORDER:
        raise AssertionError("brush runtime sections are not in canonical order")
    if first_bank + RUNTIME_BANK_COUNT > MAX_GSU_ROM_BANKS:
        raise ValueError(
            f"brush runtime bank bound overflows bank {MAX_GSU_ROM_BANKS - 1}"
        )
    reserve = ASSET_HEADER.size + len(SECTION_ORDER) * ASSET_SECTION.size
    used = [reserve, 0]
    placements: dict[str, tuple[int, int]] = {}
    lights = sections["LIGHTS"]
    if len(lights) > ROM_BANK_BYTES:
        raise ValueError(
            f"brush LIGHTS asset needs {len(lights)} bytes; one-bank bound "
            f"is {ROM_BANK_BYTES}"
        )
    placements["LIGHTS"] = (1, 0)
    used[1] = len(lights)
    candidates = sorted(
        (name for name in SECTION_ORDER if name != "LIGHTS"),
        key=lambda name: (-len(sections[name]), SECTION_ORDER.index(name)),
    )
    for name in candidates:
        payload = sections[name]
        if len(payload) > ROM_BANK_BYTES:
            raise ValueError(
                f"brush {name} asset needs {len(payload)} bytes; one-bank "
                f"bound is {ROM_BANK_BYTES}"
            )
        for bank_index in range(RUNTIME_BANK_COUNT):
            alignment = 2 if SECTION_RECORD_BYTES[name] > 1 else 1
            offset = (used[bank_index] + alignment - 1) // alignment * alignment
            if offset + len(payload) <= ROM_BANK_BYTES:
                placements[name] = (bank_index, offset)
                used[bank_index] = offset + len(payload)
                break
        else:
            raise ValueError(
                f"brush {name} asset cannot fit the {RUNTIME_BANK_COUNT}-bank "
                f"runtime bound; used bytes are {used}"
            )

    storage = [bytearray([0xFF]) * ROM_BANK_BYTES for _ in range(RUNTIME_BANK_COUNT)]
    directory = bytearray()
    section_metadata: list[dict[str, Any]] = []
    for name in SECTION_ORDER:
        bank_index, offset = placements[name]
        payload = sections[name]
        bank = first_bank + bank_index
        address = 0x8000 + offset
        count = record_counts[name]
        if count > 0xFFFF:
            raise ValueError(f"brush {name} record count exceeds uint16")
        directory.extend(
            ASSET_SECTION.pack(
                name.encode("ascii"),
                bank,
                address,
                len(payload),
                SECTION_RECORD_BYTES[name],
                count,
            )
        )
        storage[bank_index][offset : offset + len(payload)] = payload
        section_metadata.append(
            {
                "name": name,
                "bank": bank,
                "address": address,
                "bytes": len(payload),
                "recordBytes": SECTION_RECORD_BYTES[name],
                "recordCount": count,
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    logical_bytes = sum(len(payload) for payload in sections.values())
    header = ASSET_HEADER.pack(
        ASSET_MAGIC,
        ASSET_VERSION,
        RUNTIME_BANK_COUNT,
        logical_bytes,
        record_counts["MODELS"],
        record_counts["FACES"],
        record_counts["INDICES"],
        record_counts["TEXDIR"],
        leaf_count,
        len(SECTION_ORDER),
        int.from_bytes(hashlib.sha256(sections["REPLAY"]).digest()[:8], "little"),
    )
    storage[0][: ASSET_HEADER.size] = header
    storage[0][ASSET_HEADER.size : ASSET_HEADER.size + len(directory)] = directory
    metadata = {
        "magic": ASSET_MAGIC.decode("ascii"),
        "version": ASSET_VERSION,
        "headerBytes": ASSET_HEADER.size,
        "sectionRecordBytes": ASSET_SECTION.size,
        "sectionCount": len(SECTION_ORDER),
        "firstBank": first_bank,
        "bankCount": RUNTIME_BANK_COUNT,
        "logicalSectionBytes": logical_bytes,
        "usedBytesByBank": used,
        "freeBytesByBank": [ROM_BANK_BYTES - value for value in used],
        "sections": section_metadata,
    }
    return tuple(bytes(bank) for bank in storage), metadata


def decode_runtime_sections(
    runtime_banks: Iterable[bytes],
) -> dict[str, bytes]:
    """Read the self-describing QBSA directory used by tests and host tools."""

    banks = tuple(runtime_banks)
    if not banks or any(len(bank) != ROM_BANK_BYTES for bank in banks):
        raise ValueError("runtime bank images must each contain 32 KiB")
    (
        magic,
        version,
        bank_count,
        _logical_bytes,
        _models,
        _faces,
        _indices,
        _textures,
        _leaf_bits,
        section_count,
        _replay_hash,
    ) = ASSET_HEADER.unpack_from(banks[0])
    if magic != ASSET_MAGIC or version != ASSET_VERSION or bank_count != len(banks):
        raise ValueError("unsupported brush runtime asset header")
    directory_end = ASSET_HEADER.size + section_count * ASSET_SECTION.size
    if directory_end > len(banks[0]):
        raise ValueError("truncated brush runtime section directory")
    entries = []
    for index in range(section_count):
        entries.append(
            ASSET_SECTION.unpack_from(
                banks[0], ASSET_HEADER.size + index * ASSET_SECTION.size
            )
        )
    first_bank = min(entry[1] for entry in entries)
    output: dict[str, bytes] = {}
    for (
        raw_name,
        bank,
        address,
        size,
        _record_bytes,
        _record_count,
    ) in entries:
        name = raw_name.rstrip(b"\0").decode("ascii")
        bank_index = bank - first_bank
        offset = address - 0x8000
        if (
            name in output
            or not 0 <= bank_index < len(banks)
            or not 0 <= offset <= ROM_BANK_BYTES
            or offset + size > ROM_BANK_BYTES
        ):
            raise ValueError("brush runtime section range is invalid")
        output[name] = banks[bank_index][offset : offset + size]
    return output


def build_brush_assets(
    bsp: bytes,
    palette: bytes,
    replay: CanonicalBrushReplay,
    *,
    first_texture_bank: int = FIRST_BRUSH_TEXTURE_BANK,
) -> BrushAssetBuild:
    """Build all static, replay, texture, and composition assets as one set."""

    if len(palette) != 768:
        raise ValueError("Quake palette must contain exactly 768 bytes")
    require_compact_translation_only(replay)
    source = _parse_bsp(bsp)
    signon_models = sorted({state.inline_model for state in replay.signon_brushes})
    if len(signon_models) != len(replay.signon_brushes):
        raise ValueError("signon brush models/entities are not one-to-one")
    source_face_ids = tuple(
        source_face
        for inline_model in signon_models
        for source_face in range(
            int(source.models[inline_model][14]),
            int(source.models[inline_model][14]) + int(source.models[inline_model][15]),
        )
    )
    (
        source_to_packed,
        texture_chunks,
        texture_directory,
        animation,
        texture_metadata,
        _animation_name_by_source,
    ) = _texture_assets(source, source_face_ids, first_texture_bank)
    geometry_sections, model_face_textures, geometry_metadata = (
        _model_and_geometry_assets(
            source,
            replay,
            palette,
            source_to_packed,
            source_face_ids,
        )
    )
    lightmaps, light_samples, lightmap_metadata = _pack_lightmaps(
        source, source_face_ids
    )
    compact = build_compact_replay(replay)
    compact_to_fragments = _compact_to_fragment_variants(replay, compact)
    static_fragments = _static_fragment_variants(replay)
    visual_sections, visual_metadata = _visual_states(
        source,
        replay,
        compact,
        model_face_textures,
        source_to_packed,
    )
    runtime_first_bank = first_texture_bank + len(texture_chunks)
    light_bank = runtime_first_bank + 1
    light_directory = _lightmap_directory(lightmaps, light_bank, 0x8000)
    solid = _solid_leaf_bitset(source)
    sections = {
        "REPLAY": compact.payload,
        **visual_sections,
        "VFRAG": compact_to_fragments,
        "VSTATIC": static_fragments,
        **geometry_sections,
        "LIGHTDIR": light_directory,
        "LIGHTS": light_samples,
        "TEXDIR": texture_directory,
        "ANIM": animation,
        "SOLID": solid,
    }
    sections = {name: sections[name] for name in SECTION_ORDER}
    record_counts = {
        "REPLAY": 1,
        "ROWSTATE": len(replay.rows),
        "VSTATES": len(visual_sections["VSTATES"]) // VISUAL_STATE_RECORD.size,
        "VTRANS": len(visual_sections["VTRANS"]) // VISUAL_TRANSFORM_RECORD.size,
        "VFRAG": len(compact_to_fragments) // 2,
        "VSTATIC": len(static_fragments) // STATIC_TRANSFORM_RECORD.size,
        "VTEX": len(visual_sections["VTEX"]) // VISUAL_TEXTURE_RECORD.size,
        "MODELS": len(geometry_sections["MODELS"]) // MODEL_RECORD.size,
        "INDICES": len(geometry_sections["INDICES"]) // 2,
        "TEXCOORD": len(geometry_sections["TEXCOORD"])
        // bsp_tools.TEXTURE_COORD_RECORD_BYTES,
        "FACES": len(geometry_sections["FACES"]) // FACE_RECORD.size,
        "PLANES": len(geometry_sections["PLANES"]) // FACE_PLANE_RECORD.size,
        "SHADING": len(geometry_sections["SHADING"]) // SHADING_RECORD.size,
        "LIGHTDIR": len(light_directory) // LIGHTMAP_RECORD.size,
        "LIGHTS": len(light_samples),
        "TEXDIR": len(texture_directory) // TEXTURE_RECORD.size,
        "ANIM": len(animation) // ANIMATION_RECORD.size,
        "SOLID": len(solid),
    }
    runtime_chunks, runtime_metadata = _place_runtime_sections(
        sections, record_counts, runtime_first_bank, len(source.leaves)
    )
    decoded_sections = decode_runtime_sections(runtime_chunks)
    if decoded_sections != sections:
        raise AssertionError("self-describing brush runtime sections do not round-trip")
    if decode_compact_replay(decoded_sections["REPLAY"]).rows != tuple(
        row.brushes for row in replay.rows
    ):
        raise AssertionError("published compact replay does not round-trip")

    fragment_assets = build_fragment_assets(
        source,
        replay,
        source_to_packed,
        source_face_ids,
        first_bank=runtime_first_bank + len(runtime_chunks),
        maximum_bank_count=(
            MAX_GSU_ROM_BANKS - runtime_first_bank - len(runtime_chunks)
        ),
    )
    runtime_texcoord_span = fragment_assets.metadata[
        "lightmappedTexcoordAxisSpanQ4"
    ]
    lightmap_metadata["maximumTexcoordAxisSpanQ4"] = runtime_texcoord_span[
        "maximum"
    ]
    lightmap_metadata["runtimeTexcoordAxisSpanQ4"] = runtime_texcoord_span
    link_bounds = _fragment_link_bounds(
        compact,
        visual_sections,
        compact_to_fragments,
        static_fragments,
        fragment_assets.metadata,
        fragment_assets.variant_leaf_groups,
    )
    visual_metadata["staticBaselineCount"] = (
        len(static_fragments) // STATIC_TRANSFORM_RECORD.size
    )
    visual_metadata["staticBaselineRecordBytes"] = STATIC_TRANSFORM_RECORD.size
    visual_metadata["staticBaselineSha256"] = hashlib.sha256(
        static_fragments
    ).hexdigest()
    authority_states = (
        *replay.signon_brushes,
        *(state for row in replay.rows for state in row.brushes),
    )
    visual_metadata["maximumEntityId"] = max(
        state.entity_number for state in authority_states
    )
    visual_metadata["maximumInlineModel"] = max(
        state.inline_model for state in authority_states
    )
    visual_metadata["fragmentLinkBounds"] = link_bounds
    fragment_audit = fragment_assets.metadata["routeAudit"]
    outputs = {
        **{
            Path(f"QuakeBSPBrushTexturePixels{index}.bin"): chunk
            for index, chunk in enumerate(texture_chunks)
        },
        **{
            Path(f"QuakeBSPBrushRuntime{index}.bin"): chunk
            for index, chunk in enumerate(runtime_chunks)
        },
        **fragment_assets.outputs,
    }
    exclusions = _exclusion_audit(source, replay)
    last_bank = fragment_assets.metadata["lastBank"]
    if last_bank >= MAX_GSU_ROM_BANKS:
        raise ValueError(
            f"brush package ends at bank {last_bank}; maximum is "
            f"{MAX_GSU_ROM_BANKS - 1}"
        )
    output_records = {
        path.as_posix(): {
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        for path, payload in sorted(
            outputs.items(), key=lambda item: item[0].as_posix()
        )
    }
    metadata = {
        "schema": "quake-bsp-brush-assets",
        "version": ASSET_VERSION,
        "source": {
            "bspSha256": hashlib.sha256(bsp).hexdigest(),
            "paletteSha256": hashlib.sha256(palette).hexdigest(),
        },
        "coverage": {
            "signonRenderableModels": len(signon_models),
            "signonInlineModelIds": signon_models,
            "replayedEntitySlots": len(compact.slot_by_entity),
            "excludedInlineModels": exclusions["inlineModelCount"],
        },
        "geometry": geometry_metadata,
        "textures": texture_metadata,
        "lightmaps": lightmap_metadata,
        "replay": compact.metadata,
        "visualStates": visual_metadata,
        "compactToFragmentVariants": {
            "recordBytes": 2,
            "recordCount": len(compact_to_fragments) // 2,
            "bytes": len(compact_to_fragments),
            "sha256": hashlib.sha256(compact_to_fragments).hexdigest(),
            "lookup": (
                "QBSE entity firstVariant + VTRANS localVariant indexes "
                "VFRAG; its uint16 value indexes the QBSF variant directory"
            ),
        },
        "worldComposition": {
            "solidLeafCount": sum(leaf.contents == -2 for leaf in source.leaves),
            "leafCount": len(source.leaves),
            "solidLeafBitsetBytes": len(solid),
            "solidLeafBitsetSha256": hashlib.sha256(solid).hexdigest(),
            "fragments": fragment_assets.metadata,
        },
        "exclusions": exclusions,
        "runtime": runtime_metadata,
        "capacity": {
            "mapping": "self-describing FX3 LoROM, no sidecar",
            "romBankBytes": ROM_BANK_BYTES,
            "romBankCount": MAX_GSU_ROM_BANKS,
            "firstBrushBank": first_texture_bank,
            "lastBrushBank": last_bank,
            "brushBankCount": last_bank - first_texture_bank + 1,
            "brushPackageBytes": (last_bank - first_texture_bank + 1) * ROM_BANK_BYTES,
            "remainingRomBanks": MAX_GSU_ROM_BANKS - last_bank - 1,
            "remainingRomBytes": (MAX_GSU_ROM_BANKS - last_bank - 1) * ROM_BANK_BYTES,
            "cartridgeRamWorkingSets": {
                "currentVisualState": {
                    "activeBitsetBytes": (len(compact.slot_by_entity) + 7) // 8,
                    "localVariantBytes": len(compact.slot_by_entity),
                    "totalBytes": (
                        (len(compact.slot_by_entity) + 7) // 8
                        + len(compact.slot_by_entity)
                    ),
                },
                "maximumFaceLightmapCacheBytes": (bsp_tools.LIGHTMAP_FACE_CACHE_BYTES),
                "separateBrushFragmentPoolBytes": fragment_audit[
                    "separateFragmentPoolBytes"
                ],
            },
        },
        "outputs": output_records,
    }
    return BrushAssetBuild(outputs, metadata)
