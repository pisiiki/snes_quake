#!/usr/bin/env python3
"""Shared deterministic E1M3 BSP29 parsing and asset-packing primitives."""

from __future__ import annotations

import math
import struct
import sys
from dataclasses import dataclass
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parent
SHARED_TOOLS_DIR = TOOLS_DIR.parents[1] / "shared" / "tools"
for dependency_dir in (TOOLS_DIR, SHARED_TOOLS_DIR):
    if str(dependency_dir) not in sys.path:
        sys.path.insert(0, str(dependency_dir))

from generated_outputs import OwnedFileFamily  # noqa: E402


BSP_ENTRY = "maps/e1m3.bsp"
DEMO_ENTRY = "demo1.dem"
PALETTE_ENTRY = "gfx/palette.lmp"
COLORMAP_ENTRY = "gfx/colormap.lmp"
QUAKE_PAK_PATH_HINT = "id1/PAK0.PAK"
BSP_VERSION = 29
LUMP_COUNT = 15
LUMP_ENTITIES = 0
LUMP_PLANES = 1
LUMP_TEXTURES = 2
LUMP_VERTICES = 3
LUMP_VISIBILITY = 4
LUMP_NODES = 5
LUMP_TEXINFO = 6
LUMP_FACES = 7
LUMP_LIGHTING = 8
LUMP_LEAVES = 10
LUMP_MARKSURFACES = 11
LUMP_EDGES = 12
LUMP_SURFEDGES = 13
LUMP_MODELS = 14

WORLD_SCALE = 16.0
CLIP_UNITS = 64
CLIP_WORLD = WORLD_SCALE * CLIP_UNITS
LOGICAL_WIDTH = 128
LOGICAL_HEIGHT = 112
PHYSICAL_WIDTH = 256
PHYSICAL_HEIGHT = 224
BITS_PER_PIXEL = 4
DRAWABLE_COLOR_COUNT = 15
CLEAR_COLOR_INDEX = 0
CLEAR_COLOR_RGB = (255, 0, 255)
FACE_RECORD_BYTES = 6
FACE_PLANE_RECORD_BYTES = 5
WORLD_NODE_RECORD_BYTES = 10
WORLD_NODE_PARENT_RECORD_BYTES = 2
WORLD_FACE_OWNER_RECORD_BYTES = 2
WORLD_PLANE_RECORD_BYTES = 5
WORLD_LEAF_RECORD_BYTES = 8
WORLD_MARKSURFACE_RECORD_BYTES = 2
WORLD_PVS_DIRECTORY_RECORD_BYTES = 8
WORLD_PVS_GUARD_RECORD_BYTES = 3
WORLD_PVS_FIRST_GSU_ROM_BANK = 0x10
WORLD_SHADING_GSU_ROM_BANK = 0x16
WORLD_TEXCOORD_FIRST_GSU_ROM_BANK = 0x17
WORLD_TEXTURE_DIRECTORY_GSU_ROM_BANK = 0x19
WORLD_TEXTURE_FIRST_GSU_ROM_BANK = 0x1A
WORLD_LIGHTMAP_DIRECTORY_GSU_ROM_BANK = 0x20
WORLD_LIGHTMAP_FIRST_GSU_ROM_BANK = 0x21
TEXTURE_DIRECTORY_RECORD_BYTES = 8
TEXTURE_FLAG_POWER_OF_TWO_AXES = 1
TEXTURE_FLAG_SINGLE_BANK = 2
TEXTURE_COORD_RECORD_BYTES = 4
LIGHTMAP_DIRECTORY_RECORD_BYTES = 7
LIGHTMAP_FACE_CACHE_BYTES = 256
LIGHTMAP_ENCODED_LEVEL_BIAS = 0xC0
LIGHTMAP_DARKEST_LEVEL = 63
TEXTURE_DEPTH_SHADE_LUT_BYTES = 256
TEXTURE_DEPTH_COLORMAP_FIRST_LEVEL = 31
TEXTURE_DEPTH_COLORMAP_LAST_LEVEL = 58
TEXTURE_DEPTH_COLORMAP_LEVELS = (
    TEXTURE_DEPTH_COLORMAP_LAST_LEVEL - TEXTURE_DEPTH_COLORMAP_FIRST_LEVEL + 1
)
# Keep the existing depth-shade rows first so technique 3's compact indices
# remain byte-identical. The remaining RAM fits every lightmap row except 1-9;
# those extremely rare brightest samples map to row 10.
TEXTURE_COLORMAP_SOURCE_LEVELS = (
    *range(32, 59),
    *range(10, 32),
    *range(59, 64),
)
TEXTURE_COLORMAP_LEVELS = 1 + len(TEXTURE_COLORMAP_SOURCE_LEVELS)
TEXTURE_COLORMAP_BYTES = TEXTURE_COLORMAP_LEVELS * 256
LIGHTMAP_COLORMAP_MAP_BYTES = 64
TEXTURE_COLORMAP_RAM_HIGH_BYTE = 0xC8
LIGHTMAP_MIN_EXACT_COLORMAP_LEVEL = 10
QUAKE_NEUTRAL_LIGHT_STYLE_SCALE = 264
TEXTURE_SHADE_NEAR_DISTANCE = 8
TEXTURE_SHADE_FAR_DISTANCE = 99
DEMO_TRACK_RECORD_BYTES = 5
DEMO_TIMING_RECORD_BYTES = 2
DEMO_PRECISE_TRACK_RECORD_BYTES = struct.calcsize("<hhhHH")
DEMO_PRECISE_SAMPLE_RATE_HZ = 30
DEMO_STEP_SAMPLE_RATE_HZ = 2
DEMO_STEP_STRIDE = DEMO_PRECISE_SAMPLE_RATE_HZ // DEMO_STEP_SAMPLE_RATE_HZ
NTSC_FRAMES_PER_SECOND = 60.0988138974405
PVS_QUANTIZATION_GUARD_MAX_SOURCE_SPAN = 1.0
WORLD_COORD_MIN = -128
WORLD_COORD_MAX = 127
ROM_BANK_BYTES = 0x8000
DIVIDE_Q12_MAX_DENOMINATOR = 0x7FFF
DIVIDE_Q12_RECIPROCAL_SCALE_BITS = 27
DIVIDE_Q12_RECIPROCAL_LIMB_BITS = 15
DIVIDE_Q12_RECIPROCAL_ENTRY_BYTES = 4
NEAR_DEPTH = 1
# The compact world path keeps view coordinates in Q6 and indexes reciprocal
# depth in quarter units.  A Q12 reciprocal then projects with one signed
# multiply while preserving the shared sub-unit edge coordinates.
VIEW_FRACTION_BITS = 6
DEPTH_TABLE_FRACTION_BITS = 2
PROJECTION_SHIFT = 12
RECIPROCAL_NUMERATOR = 96 << (
    PROJECTION_SHIFT + DEPTH_TABLE_FRACTION_BITS - VIEW_FRACTION_BITS
)
SPAWN_PROJECTION_SHIFT = 8
SPAWN_RECIPROCAL_NUMERATOR = 96 << SPAWN_PROJECTION_SHIFT
FACE_LIGHT_DIRECTION = (2.0, -3.0, 5.0)
FACE_POSITION_WEIGHTS = (0.18, -0.12, 0.20)
FACE_LIGHT_AMBIENT = 0.00
FACE_LIGHT_DIRECTIONAL = 0.90
FACE_LIGHT_POSITIONAL = 0.30
FACE_LIGHT_BLACK_POINT = 0.06
FACE_PALETTE_RGB = (
    (36, 32, 40),
    (51, 42, 44),
    (67, 52, 48),
    (82, 62, 52),
    (97, 71, 57),
    (112, 81, 61),
    (128, 91, 65),
    (143, 101, 69),
    (158, 119, 83),
    (173, 137, 98),
    (188, 155, 112),
    (203, 174, 127),
    (218, 192, 141),
    (233, 210, 156),
    (248, 228, 170),
)
TEXTURE_FAMILY_COUNT = 3
PHYSICAL_COLORS_PER_FAMILY = 5
APPARENT_LIGHT_LEVELS = PHYSICAL_COLORS_PER_FAMILY * 2 - 1
HUE_BIN_COUNT = 72
MINIMUM_FAMILY_HUE_SEPARATION = 38.0
MATERIAL_RAMP_POSITIONS = (0.18, 0.32, 0.48, 0.70, 1.0)
MATERIAL_DARK_VALUE = 16.0 / 255.0
WORLD_SHADING_RECORD_BYTES = 4
DISTANCE_BUCKET_COUNT = 8
DISTANCE_LUT_BYTES = 128
WORLD_SHADING_TABLE_RECORD_BYTES = 2
WORLD_SHADING_TABLE_BYTES = (
    TEXTURE_FAMILY_COUNT
    * APPARENT_LIGHT_LEVELS
    * DISTANCE_BUCKET_COUNT
    * WORLD_SHADING_TABLE_RECORD_BYTES
)
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "Data"
# This generator reserves the complete namespace, including named assets and
# variable-count numbered chunks. The packet oracle is JSON and remains owned
# by its independent producer.
OWNED_OUTPUT_FAMILIES = (OwnedFileFamily(prefix="QuakeBSPWorld", suffix=".bin"),)


def divide_q12_reciprocal_parts(denominator: int) -> tuple[int, int]:
    """Return base-2^15 limbs for ceil(2^27 / denominator)."""
    if not 1 <= denominator <= DIVIDE_Q12_MAX_DENOMINATOR:
        raise ValueError("Q12 reciprocal denominator is outside 1..32767")
    reciprocal = (
        (1 << DIVIDE_Q12_RECIPROCAL_SCALE_BITS) + denominator - 1
    ) // denominator
    limb_mask = (1 << DIVIDE_Q12_RECIPROCAL_LIMB_BITS) - 1
    return reciprocal >> DIVIDE_Q12_RECIPROCAL_LIMB_BITS, reciprocal & limb_mask


def divide_q12_reciprocal_table() -> bytes:
    """Pack one little-endian high/low reciprocal-limb pair per denominator."""
    return b"".join(
        struct.pack("<HH", *divide_q12_reciprocal_parts(denominator))
        for denominator in range(1, DIVIDE_Q12_MAX_DENOMINATOR + 1)
    )


def divide_q12_with_reciprocal(numerator: int, denominator: int) -> int:
    """Mirror the exact estimate-and-correct algorithm intended for the GSU."""
    if not 0 <= numerator < denominator <= DIVIDE_Q12_MAX_DENOMINATOR:
        raise ValueError("Q12 ratio must satisfy 0 <= numerator < denominator")
    high_limb, low_limb = divide_q12_reciprocal_parts(denominator)
    estimate = numerator * high_limb + (
        numerator * low_limb >> DIVIDE_Q12_RECIPROCAL_LIMB_BITS
    )
    return estimate - int(estimate * denominator > numerator << 12)


@dataclass(frozen=True)
class Face:
    plane: int
    side: int
    first_edge: int
    edge_count: int
    texinfo: int
    light_styles: tuple[int, int, int, int] = (255, 255, 255, 255)
    light_offset: int = -1


@dataclass(frozen=True)
class Leaf:
    contents: int
    vis_offset: int
    first_mark_surface: int
    mark_surface_count: int


@dataclass(frozen=True)
class Node:
    plane: int
    children: tuple[int, int]
    first_face: int
    face_count: int


@dataclass(frozen=True)
class MipTexture:
    name: str
    width: int
    height: int
    mip_offsets: tuple[int, int, int, int]
    lump_offset: int
    pixels: bytes


@dataclass(frozen=True)
class PackedTexturePlacement:
    absolute_offset: int
    bank_index: int
    bank_offset: int
    bank_span: int

    @property
    def single_bank(self) -> bool:
        return self.bank_span == 1


def pack_texture_bank_images(
    texture_payloads: tuple[bytes, ...], *, bank_count: int
) -> tuple[tuple[bytes, ...], tuple[PackedTexturePlacement, ...]]:
    """Pack exact textures while keeping every bank-sized texture in one bank."""
    if bank_count <= 0:
        raise ValueError("texture bank count must be positive")
    if any(not payload for payload in texture_payloads):
        raise ValueError("exact texture payloads must not be empty")

    capacity = bank_count * ROM_BANK_BYTES
    source_bytes = sum(len(payload) for payload in texture_payloads)
    if source_bytes > capacity:
        raise ValueError(
            f"exact textures need {source_bytes} bytes but only {capacity} are available"
        )

    storage = bytearray([0xFF]) * capacity
    used = [0] * bank_count
    placements: list[PackedTexturePlacement | None] = [None] * len(texture_payloads)

    # Multi-bank textures start at bank boundaries so crossing them requires
    # only the natural $FFFF->$8000 bank increment. Sort by size, then packed
    # texture ID, to make the layout independent of incidental iteration order.
    next_bank = 0
    multi_bank_ids = sorted(
        (
            texture_id
            for texture_id, payload in enumerate(texture_payloads)
            if len(payload) > ROM_BANK_BYTES
        ),
        key=lambda texture_id: (-len(texture_payloads[texture_id]), texture_id),
    )
    for texture_id in multi_bank_ids:
        payload = texture_payloads[texture_id]
        bank_span = (len(payload) + ROM_BANK_BYTES - 1) // ROM_BANK_BYTES
        if next_bank + bank_span > bank_count:
            raise ValueError("multi-bank exact textures exceed available ROM banks")
        absolute_offset = next_bank * ROM_BANK_BYTES
        storage[absolute_offset : absolute_offset + len(payload)] = payload
        for bank_index in range(next_bank, next_bank + bank_span - 1):
            used[bank_index] = ROM_BANK_BYTES
        final_bank = next_bank + bank_span - 1
        used[final_bank] = len(payload) - (bank_span - 1) * ROM_BANK_BYTES
        placements[texture_id] = PackedTexturePlacement(
            absolute_offset=absolute_offset,
            bank_index=next_bank,
            bank_offset=0,
            bank_span=bank_span,
        )
        next_bank += bank_span

    # First-fit decreasing fills the remaining per-bank tails. The packed ID
    # tie-break makes the result deterministic, and no texture in this pass may
    # cross a bank boundary.
    single_bank_ids = sorted(
        (
            texture_id
            for texture_id, payload in enumerate(texture_payloads)
            if len(payload) <= ROM_BANK_BYTES
        ),
        key=lambda texture_id: (-len(texture_payloads[texture_id]), texture_id),
    )
    for texture_id in single_bank_ids:
        payload = texture_payloads[texture_id]
        for bank_index, bank_used in enumerate(used):
            if bank_used + len(payload) > ROM_BANK_BYTES:
                continue
            absolute_offset = bank_index * ROM_BANK_BYTES + bank_used
            storage[absolute_offset : absolute_offset + len(payload)] = payload
            used[bank_index] += len(payload)
            placements[texture_id] = PackedTexturePlacement(
                absolute_offset=absolute_offset,
                bank_index=bank_index,
                bank_offset=bank_used,
                bank_span=1,
            )
            break
        else:
            raise ValueError(
                "exact textures fit in aggregate but cannot be packed without "
                "crossing a bank"
            )

    if any(placement is None for placement in placements):
        raise AssertionError("exact texture bank packing lost a texture")
    packed_placements = tuple(
        placement for placement in placements if placement is not None
    )
    chunks = tuple(
        bytes(storage[offset : offset + ROM_BANK_BYTES])
        for offset in range(0, capacity, ROM_BANK_BYTES)
    )
    return chunks, packed_placements


class PakArchive:
    def __init__(self, path: Path) -> None:
        self.path = path
        data = path.read_bytes()
        if len(data) < 12 or data[:4] != b"PACK":
            raise ValueError(f"{path} is not a Quake PAK archive")
        directory_offset, directory_size = struct.unpack_from("<II", data, 4)
        if directory_size % 64 or directory_offset + directory_size > len(data):
            raise ValueError("invalid Quake PAK directory")
        entries: dict[str, tuple[int, int]] = {}
        for offset in range(directory_offset, directory_offset + directory_size, 64):
            raw_name, file_offset, file_size = struct.unpack_from(
                "<56sII", data, offset
            )
            name = raw_name.split(b"\0", 1)[0].decode("ascii").lower()
            if file_offset + file_size > len(data):
                raise ValueError(f"PAK entry {name!r} escapes the archive")
            entries[name] = (file_offset, file_size)
        self._data = data
        self._entries = entries

    def read(self, name: str) -> bytes:
        try:
            offset, size = self._entries[name.lower()]
        except KeyError as exc:
            raise FileNotFoundError(f"{name!r} is missing from {self.path}") from exc
        return self._data[offset : offset + size]


def locate_quake_pak(explicit: Path | None) -> Path:
    if explicit is not None:
        if not explicit.is_file():
            raise FileNotFoundError(explicit)
        return explicit
    candidates = (
        Path(r"C:\Program Files (x86)\Steam\steamapps\common\Quake\id1\PAK0.PAK"),
        Path(r"C:\Program Files\Steam\steamapps\common\Quake\id1\PAK0.PAK"),
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("Quake PAK0.PAK was not found; pass --pak explicitly")


def lump_ranges(bsp: bytes) -> list[tuple[int, int]]:
    header_size = 4 + LUMP_COUNT * 8
    if len(bsp) < header_size:
        raise ValueError("truncated BSP header")
    version = struct.unpack_from("<i", bsp, 0)[0]
    if version != BSP_VERSION:
        raise ValueError(f"expected BSP29, got version {version}")
    output = []
    for index in range(LUMP_COUNT):
        offset, size = struct.unpack_from("<ii", bsp, 4 + index * 8)
        if offset < 0 or size < 0 or offset + size > len(bsp):
            raise ValueError(f"BSP lump {index} escapes the file")
        output.append((offset, size))
    return output


def lump_data(bsp: bytes, lumps: list[tuple[int, int]], index: int) -> bytes:
    offset, size = lumps[index]
    return bsp[offset : offset + size]


def unpack_records(data: bytes, fmt: str) -> list[tuple[object, ...]]:
    size = struct.calcsize(fmt)
    if len(data) % size:
        raise ValueError(f"lump size {len(data)} is not a multiple of {size}")
    return list(struct.iter_unpack(fmt, data))


def parse_entities(data: bytes) -> list[dict[str, str]]:
    text = data.rstrip(b"\0").decode("latin1")
    entities: list[dict[str, str]] = []
    cursor = 0
    while True:
        begin = text.find("{", cursor)
        if begin < 0:
            break
        end = text.find("}", begin + 1)
        if end < 0:
            raise ValueError("unterminated BSP entity")
        block = text[begin + 1 : end]
        tokens: list[str] = []
        token_cursor = 0
        while True:
            quote = block.find('"', token_cursor)
            if quote < 0:
                break
            quote_end = block.find('"', quote + 1)
            if quote_end < 0:
                raise ValueError("unterminated entity string")
            tokens.append(block[quote + 1 : quote_end])
            token_cursor = quote_end + 1
        if len(tokens) % 2:
            raise ValueError("entity has an odd key/value token count")
        entities.append(dict(zip(tokens[0::2], tokens[1::2], strict=True)))
        cursor = end + 1
    return entities


def player_start(
    entities: list[dict[str, str]],
) -> tuple[tuple[float, float, float], float]:
    for entity in entities:
        if entity.get("classname") == "info_player_start":
            origin = tuple(float(value) for value in entity["origin"].split())
            if len(origin) != 3:
                raise ValueError("info_player_start origin must have three components")
            return (origin[0], origin[1], origin[2]), float(entity.get("angle", "0"))
    raise ValueError("BSP has no info_player_start")


def parse_textures(data: bytes) -> list[MipTexture]:
    if len(data) < 4:
        raise ValueError("truncated texture lump")
    count = struct.unpack_from("<i", data, 0)[0]
    if count < 0 or 4 + count * 4 > len(data):
        raise ValueError("invalid texture directory")
    textures: list[MipTexture] = []
    for index in range(count):
        offset = struct.unpack_from("<i", data, 4 + index * 4)[0]
        if offset == -1:
            textures.append(MipTexture("missing", 0, 0, (0, 0, 0, 0), -1, b""))
            continue
        if offset < 0 or offset + 40 > len(data):
            raise ValueError(f"invalid miptex {index} offset")
        raw_name, width, height, mip0, mip1, mip2, mip3 = struct.unpack_from(
            "<16s6I", data, offset
        )
        name = raw_name.split(b"\0", 1)[0].decode("ascii")
        pixel_count = width * height
        start = offset + mip0
        if not width or not height or start + pixel_count > len(data):
            raise ValueError(f"invalid miptex {name!r}")
        textures.append(
            MipTexture(
                name,
                width,
                height,
                (mip0, mip1, mip2, mip3),
                offset,
                data[start : start + pixel_count],
            )
        )
    return textures


def decompress_pvs(data: bytes, offset: int, leaf_count: int) -> bytes:
    row_bytes = (leaf_count + 7) // 8
    if offset < 0:
        return b"\xff" * row_bytes
    output = bytearray()
    cursor = offset
    while len(output) < row_bytes:
        if cursor >= len(data):
            raise ValueError("truncated BSP PVS")
        value = data[cursor]
        cursor += 1
        if value:
            output.append(value)
            continue
        if cursor >= len(data):
            raise ValueError("truncated BSP PVS zero run")
        run = data[cursor]
        cursor += 1
        if not run or len(output) + run > row_bytes:
            raise ValueError("invalid BSP PVS zero run")
        output.extend(b"\0" * run)
    return bytes(output)


def locate_leaf(
    point: tuple[float, float, float],
    nodes: list[Node],
    planes: list[tuple[object, ...]],
    root: int,
) -> int:
    node_index = root
    while node_index >= 0:
        node = nodes[node_index]
        nx, ny, nz, distance, _ = planes[node.plane]
        side = 0 if point[0] * nx + point[1] * ny + point[2] * nz - distance >= 0 else 1
        node_index = node.children[side]
    return -node_index - 1


def clip_axis(
    polygon: list[tuple[float, float, float]],
    axis: int,
    boundary: float,
    keep_less: bool,
) -> list[tuple[float, float, float]]:
    if not polygon:
        return []
    output: list[tuple[float, float, float]] = []
    previous = polygon[-1]
    previous_inside = (
        previous[axis] <= boundary if keep_less else previous[axis] >= boundary
    )
    for current in polygon:
        current_inside = (
            current[axis] <= boundary if keep_less else current[axis] >= boundary
        )
        if current_inside != previous_inside:
            denominator = current[axis] - previous[axis]
            fraction = (
                0.0 if denominator == 0 else (boundary - previous[axis]) / denominator
            )
            intersection = tuple(
                previous[i] + (current[i] - previous[i]) * fraction for i in range(3)
            )
            output.append((intersection[0], intersection[1], intersection[2]))
        if current_inside:
            output.append(current)
        previous = current
        previous_inside = current_inside
    return output


def clip_to_budget(
    polygon: list[tuple[float, float, float]], origin: tuple[float, float, float]
) -> list[tuple[float, float, float]]:
    output = polygon
    for axis in range(3):
        output = clip_axis(output, axis, origin[axis] - CLIP_WORLD, keep_less=False)
        output = clip_axis(output, axis, origin[axis] + CLIP_WORLD, keep_less=True)
    return output


def quantize_vertex(
    vertex: tuple[float, float, float], origin: tuple[float, float, float]
) -> tuple[int, int, int]:
    values = tuple(
        int(math.floor((vertex[i] - origin[i]) / WORLD_SCALE + 0.5)) for i in range(3)
    )
    if any(value < -CLIP_UNITS or value > CLIP_UNITS for value in values):
        raise AssertionError(f"clipped vertex quantized out of range: {values}")
    return values[0], values[1], values[2]


def quantize_world_vertex(
    vertex: tuple[float, float, float], origin: tuple[float, float, float]
) -> tuple[int, int, int]:
    """Quantize a full-world vertex around the model midpoint into signed bytes."""
    values = tuple(
        int(math.floor((vertex[axis] - origin[axis]) / WORLD_SCALE + 0.5))
        for axis in range(3)
    )
    if any(value < WORLD_COORD_MIN or value > WORLD_COORD_MAX for value in values):
        raise AssertionError(
            f"world vertex quantized out of signed-byte range: {values}"
        )
    return values[0], values[1], values[2]


def quantized_bsp_plane(
    plane: tuple[object, ...], origin: tuple[float, float, float]
) -> tuple[tuple[int, int, int], int]:
    """Convert a BSP plane to Q6 in the map-centered quantized coordinate space."""
    source_normal = tuple(float(plane[axis]) for axis in range(3))
    normal = tuple(round(component * 64) for component in source_normal)
    distance = round(
        (float(plane[3]) - sum(source_normal[axis] * origin[axis] for axis in range(3)))
        * 64
        / WORLD_SCALE
    )
    if not any(normal) or any(
        component < -64 or component > 64 for component in normal
    ):
        raise AssertionError(f"invalid Q6 BSP normal {normal}")
    if distance < -0x8000 or distance > 0x7FFF:
        raise AssertionError(f"Q6 BSP plane distance exceeds int16: {distance}")
    return (normal[0], normal[1], normal[2]), distance


def polygon_area(polygon: list[tuple[float, float, float]]) -> float:
    if len(polygon) < 3:
        return 0.0
    origin = polygon[0]
    area = 0.0
    for index in range(1, len(polygon) - 1):
        a = tuple(polygon[index][axis] - origin[axis] for axis in range(3))
        b = tuple(polygon[index + 1][axis] - origin[axis] for axis in range(3))
        cross = (
            a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0],
        )
        area += math.sqrt(sum(value * value for value in cross)) * 0.5
    return area


def quantized_face_plane(
    polygon: list[tuple[int, int, int]],
) -> tuple[tuple[int, int, int], int]:
    """Return a stable packed-polygon winding plane in Q6.

    Q2 rounding can bend a source-collinear edge into a tiny triangle. Use
    the largest fan cross instead of the first nonzero cross so culling follows
    the geometry that is actually rasterized without letting a rounding sliver
    redefine the whole face.
    """
    origin = polygon[0]
    crosses: list[tuple[int, int, int]] = []
    for index in range(1, len(polygon) - 1):
        a = tuple(polygon[index][axis] - origin[axis] for axis in range(3))
        b = tuple(polygon[index + 1][axis] - origin[axis] for axis in range(3))
        candidate = (
            a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0],
        )
        if any(candidate):
            crosses.append(candidate)
    if not crosses:
        # A fully collapsed face contributes no pixels and should always cull.
        return (0, 0, 0), 1
    cross = max(crosses, key=lambda value: sum(component**2 for component in value))

    magnitude = math.sqrt(sum(component * component for component in cross))
    normal = tuple(round(component * 64 / magnitude) for component in cross)
    if not any(normal) or any(
        component < -64 or component > 64 for component in normal
    ):
        raise AssertionError(f"invalid Q6 face normal {normal}")
    distances = [
        sum(normal[axis] * vertex[axis] for axis in range(3)) for vertex in polygon
    ]
    distance = round(sum(distances) / len(distances))
    if distance < -0x8000 or distance > 0x7FFF:
        raise AssertionError(f"Q6 relative-plane distance exceeds int16: {distance}")
    return (normal[0], normal[1], normal[2]), distance


def pack_q2_world_vertex(vertex: tuple[int, int, int]) -> bytes:
    """Pack signed Q2 xyz as three int8 bases and one residual-bit byte."""

    bases = tuple(component // 4 for component in vertex)
    if any(component < -128 or component > 127 for component in bases):
        raise AssertionError("Q2 world-vertex base exceeds signed-byte storage")
    residual = (vertex[0] & 3) | ((vertex[1] & 3) << 2) | ((vertex[2] & 3) << 4)
    return struct.pack("<bbbB", *bases, residual)


def spawn_project(vertex: tuple[int, int, int]) -> tuple[int, int] | None:
    x, depth, z = vertex
    if depth < NEAR_DEPTH:
        return None
    reciprocal = round(SPAWN_RECIPROCAL_NUMERATOR / depth)
    return (
        64 + ((-x * reciprocal) >> SPAWN_PROJECTION_SHIFT),
        56 - ((z * reciprocal) >> SPAWN_PROJECTION_SHIFT),
    )


def snes_color(rgb: tuple[int, int, int]) -> int:
    r, g, b = (round(component * 31 / 255) for component in rgb)
    return r | (g << 5) | (b << 10)


def round_half_up(value: float) -> int:
    """Match C++ lround for the nonnegative values used by material packing."""
    return math.floor(value + 0.5)


def round_half_away_from_zero(value: float) -> int:
    """Deterministically match C/C++ lround for signed texture coordinates."""
    return math.floor(value + 0.5) if value >= 0.0 else math.ceil(value - 0.5)


def quake_palette(data: bytes) -> tuple[tuple[int, int, int], ...]:
    if len(data) != 256 * 3:
        raise ValueError("Quake palette must contain exactly 256 RGB colors")
    return tuple(tuple(data[index * 3 : index * 3 + 3]) for index in range(256))


def rgb_to_hsv(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    red, green, blue = rgb
    maximum = max(rgb)
    minimum = min(rgb)
    delta = maximum - minimum
    value = maximum / 255.0
    if maximum == 0:
        return 0.0, 0.0, value
    saturation = delta / maximum
    if delta == 0:
        return 0.0, saturation, value
    if maximum == red:
        hue = 60.0 * math.fmod((green - blue) / delta, 6.0)
    elif maximum == green:
        hue = 60.0 * ((blue - red) / delta + 2.0)
    else:
        hue = 60.0 * ((red - green) / delta + 4.0)
    return hue + 360.0 if hue < 0.0 else hue, saturation, value


def circular_hue_distance(first: float, second: float) -> float:
    direct = abs(first - second)
    return min(direct, 360.0 - direct)


def hue_bin(hue: float) -> int:
    return min(HUE_BIN_COUNT - 1, max(0, math.floor(hue * HUE_BIN_COUNT / 360.0)))


def hue_bin_center(index: int) -> float:
    return (index + 0.5) * 360.0 / HUE_BIN_COUNT


def texture_histograms(textures: list[MipTexture]) -> list[list[int]]:
    histograms: list[list[int]] = []
    for texture in textures:
        histogram = [0] * 256
        for palette_index in texture.pixels:
            histogram[palette_index] += 1
        histograms.append(histogram)
    return histograms


def nearest_texture_family(hue: float, family_hues: tuple[float, ...]) -> int:
    return min(
        range(len(family_hues)),
        key=lambda family: circular_hue_distance(hue, family_hues[family]),
    )


def texture_family_fractions(
    histogram: list[int],
    palette: tuple[tuple[int, int, int], ...],
    family_hues: tuple[float, ...],
) -> list[float]:
    fractions = [0.0] * TEXTURE_FAMILY_COUNT
    considered = 0.0
    for palette_index, pixels in enumerate(histogram):
        if not pixels:
            continue
        hue, saturation, value = rgb_to_hsv(palette[palette_index])
        if value < 0.025 or saturation < 0.12:
            continue
        fractions[nearest_texture_family(hue, family_hues)] += pixels
        considered += pixels
    if considered:
        fractions = [fraction / considered for fraction in fractions]
    return fractions


def select_texture_family_hues(
    histograms: list[list[int]],
    palette: tuple[tuple[int, int, int], ...],
    face_usage: list[int],
) -> tuple[float, ...]:
    histogram = [0.0] * HUE_BIN_COUNT
    for texture_id, texture_histogram in enumerate(histograms):
        if not face_usage[texture_id]:
            continue
        weighted_bins = [0.0] * HUE_BIN_COUNT
        texture_weight = 0.0
        for palette_index, pixels in enumerate(texture_histogram):
            if not pixels:
                continue
            hue, saturation, value = rgb_to_hsv(palette[palette_index])
            if value < 0.04 or saturation < 0.12:
                continue
            weight = pixels * saturation**1.5 * value**0.6
            weighted_bins[hue_bin(hue)] += weight
            texture_weight += weight
        if texture_weight <= 0.0:
            continue
        scale = math.sqrt(face_usage[texture_id]) / texture_weight
        for index, weight in enumerate(weighted_bins):
            histogram[index] += weight * scale

    if sum(histogram) <= 0.0:
        return 25.0, 70.0, 235.0
    best_hues = (25.0, 70.0, 235.0)
    best_cost = math.inf
    for first in range(HUE_BIN_COUNT):
        for second in range(first + 1, HUE_BIN_COUNT):
            for third in range(second + 1, HUE_BIN_COUNT):
                candidate = tuple(
                    hue_bin_center(index) for index in (first, second, third)
                )
                if (
                    min(
                        circular_hue_distance(candidate[0], candidate[1]),
                        circular_hue_distance(candidate[0], candidate[2]),
                        circular_hue_distance(candidate[1], candidate[2]),
                    )
                    < MINIMUM_FAMILY_HUE_SEPARATION
                ):
                    continue
                cost = 0.0
                for index, weight in enumerate(histogram):
                    if weight:
                        hue = hue_bin_center(index)
                        distance = min(
                            circular_hue_distance(hue, family_hue)
                            for family_hue in candidate
                        )
                        cost += weight * distance * distance
                if cost < best_cost:
                    best_cost = cost
                    best_hues = candidate
    return best_hues


def weighted_quantile(
    samples: list[tuple[float, float]], quantile: float, fallback: float
) -> float:
    if not samples:
        return fallback
    samples.sort(key=lambda sample: sample[0])
    target = sum(weight for _, weight in samples) * quantile
    cumulative = 0.0
    for value, weight in samples:
        cumulative += weight
        if cumulative >= target:
            return value
    return samples[-1][0]


def hsv_to_rgb555(hue: float, saturation: float, value: float) -> tuple[int, int, int]:
    chroma = value * saturation
    sector = hue / 60.0
    secondary = chroma * (1.0 - abs(math.fmod(sector, 2.0) - 1.0))
    red = green = blue = 0.0
    sector_index = math.floor(sector) % 6
    if sector_index == 0:
        red, green = chroma, secondary
    elif sector_index == 1:
        red, green = secondary, chroma
    elif sector_index == 2:
        green, blue = chroma, secondary
    elif sector_index == 3:
        green, blue = secondary, chroma
    elif sector_index == 4:
        red, blue = secondary, chroma
    else:
        red, blue = chroma, secondary
    match = value - chroma

    def quantize(channel: float) -> int:
        level = min(31, max(0, round_half_up((channel + match) * 31.0)))
        return (level * 255 + 15) // 31

    return quantize(red), quantize(green), quantize(blue)


def build_material_palette(
    textures: list[MipTexture],
    palette: tuple[tuple[int, int, int], ...],
    texinfo: list[tuple[object, ...]],
    faces: list[Face],
) -> tuple[tuple[float, ...], list[int], tuple[tuple[int, int, int], ...]]:
    histograms = texture_histograms(textures)
    face_usage = [0] * len(textures)
    for face in faces:
        texture_id = int(texinfo[face.texinfo][8])
        if 0 <= texture_id < len(face_usage):
            face_usage[texture_id] += 1
    if not any(face_usage):
        raise ValueError("BSP faces do not reference any embedded textures")

    family_hues = select_texture_family_hues(histograms, palette, face_usage)
    used_textures = [index for index, usage in enumerate(face_usage) if usage]
    baseline = [0.0] * TEXTURE_FAMILY_COUNT
    for texture_id in used_textures:
        fractions = texture_family_fractions(
            histograms[texture_id], palette, family_hues
        )
        for family in range(TEXTURE_FAMILY_COUNT):
            baseline[family] += fractions[family] / len(used_textures)

    smoothing = 0.03
    texture_families: list[int] = []
    for histogram in histograms:
        fractions = texture_family_fractions(histogram, palette, family_hues)
        texture_families.append(
            max(
                range(TEXTURE_FAMILY_COUNT),
                key=lambda family: (fractions[family] + smoothing)
                / (baseline[family] + smoothing),
            )
        )

    saturation_samples: list[list[tuple[float, float]]] = [
        [] for _ in range(TEXTURE_FAMILY_COUNT)
    ]
    value_samples: list[list[tuple[float, float]]] = [
        [] for _ in range(TEXTURE_FAMILY_COUNT)
    ]
    for texture_id in used_textures:
        family = texture_families[texture_id]
        aligned_pixels = 0.0
        for palette_index, pixels in enumerate(histograms[texture_id]):
            hue, saturation, value = rgb_to_hsv(palette[palette_index])
            if (
                value >= 0.025
                and saturation >= 0.12
                and circular_hue_distance(hue, family_hues[family]) <= 50.0
            ):
                aligned_pixels += pixels
        if aligned_pixels <= 0.0:
            continue
        scale = math.sqrt(face_usage[texture_id]) / aligned_pixels
        for palette_index, pixels in enumerate(histograms[texture_id]):
            if not pixels:
                continue
            hue, saturation, value = rgb_to_hsv(palette[palette_index])
            if (
                value < 0.025
                or saturation < 0.12
                or circular_hue_distance(hue, family_hues[family]) > 50.0
            ):
                continue
            weight = pixels * scale
            saturation_samples[family].append((saturation, weight))
            value_samples[family].append((value, weight))

    endpoints: list[tuple[float, float, float]] = []
    for family in range(TEXTURE_FAMILY_COUNT):
        saturation = min(
            0.72,
            max(0.48, weighted_quantile(saturation_samples[family], 0.75, 0.58)),
        )
        source_bright = weighted_quantile(value_samples[family], 0.97, 0.38)
        endpoints.append(
            (
                family_hues[family],
                saturation,
                min(0.86, max(0.74, 0.55 + 0.60 * source_bright)),
            )
        )

    material_palette: list[tuple[int, int, int]] = [CLEAR_COLOR_RGB]
    for hue, saturation, value in endpoints:
        for position in MATERIAL_RAMP_POSITIONS:
            material_palette.append(
                hsv_to_rgb555(
                    hue,
                    saturation * (0.60 + 0.40 * position),
                    MATERIAL_DARK_VALUE + (value - MATERIAL_DARK_VALUE) * position,
                )
            )
    if len(material_palette) != 16 or len(set(material_palette)) != 16:
        raise AssertionError("material palette must contain 16 distinct colors")
    return family_hues, texture_families, tuple(material_palette)


def orientation_light_level(normal: tuple[float, float, float]) -> int:
    normal_length = math.sqrt(sum(component * component for component in normal))
    light_length = math.sqrt(
        sum(component * component for component in FACE_LIGHT_DIRECTION)
    )
    if normal_length <= 0.0:
        raise ValueError("face normal must be nonzero")
    lambert = max(
        0.0,
        min(
            1.0,
            sum(normal[axis] * FACE_LIGHT_DIRECTION[axis] for axis in range(3))
            / (normal_length * light_length),
        ),
    )
    brightness = 0.25 + 0.75 * lambert
    return min(
        APPARENT_LIGHT_LEVELS - 1,
        max(
            0,
            math.floor(brightness * (APPARENT_LIGHT_LEVELS - 1) + 0.5),
        ),
    )


def distance_surrogate(
    centroid: tuple[int, int, int], camera: tuple[int, int, int]
) -> int:
    distances = sorted(abs(centroid[axis] - camera[axis]) for axis in range(3))
    return distances[2] + distances[1] // 2 + distances[0] // 4


def distance_bucket(distance: int) -> int:
    return min(DISTANCE_BUCKET_COUNT - 1, max(0, (distance - 8) // 13))


def material_face_colors(base_shade: int, bucket: int) -> tuple[int, int]:
    family, base_light = divmod(base_shade, APPARENT_LIGHT_LEVELS)
    light = (base_light * (10 - bucket) + 5) // 10
    low = 1 + family * PHYSICAL_COLORS_PER_FAMILY + light // 2
    high = 1 + family * PHYSICAL_COLORS_PER_FAMILY + (light + 1) // 2
    if not (1 <= low <= DRAWABLE_COLOR_COUNT and 1 <= high <= DRAWABLE_COLOR_COUNT):
        raise AssertionError("drawable material shade escaped palette indices 1..15")
    return high, (high << 4) | low


def material_shading_table() -> bytes:
    output = bytearray()
    for base_shade in range(TEXTURE_FAMILY_COUNT * APPARENT_LIGHT_LEVELS):
        for bucket in range(DISTANCE_BUCKET_COUNT):
            output.extend(material_face_colors(base_shade, bucket))
    if len(output) != WORLD_SHADING_TABLE_BYTES or 0 in output:
        raise AssertionError("material lookup table is invalid")
    return bytes(output)


def material_distance_lut() -> bytes:
    output = bytes(distance_bucket(distance) for distance in range(DISTANCE_LUT_BYTES))
    if len(output) != DISTANCE_LUT_BYTES or max(output) >= DISTANCE_BUCKET_COUNT:
        raise AssertionError("material distance lookup table is invalid")
    return output


def lit_face_colors(
    normal: tuple[float, float, float],
    centroid: tuple[float, float, float],
    bounds_min: tuple[float, float, float],
    bounds_max: tuple[float, float, float],
) -> tuple[int, int]:
    """Quantize orientation and world position into flat/checker shade indices."""
    normal_length = math.sqrt(sum(component * component for component in normal))
    if normal_length <= 0.0:
        raise ValueError("face normal must be nonzero")
    light_length = math.sqrt(
        sum(component * component for component in FACE_LIGHT_DIRECTION)
    )
    lambert = sum(normal[axis] * FACE_LIGHT_DIRECTION[axis] for axis in range(3)) / (
        normal_length * light_length
    )
    lambert = max(0.0, min(1.0, lambert))

    normalized_position: list[float] = []
    for axis in range(3):
        span = bounds_max[axis] - bounds_min[axis]
        if span <= 0.0:
            raise ValueError("world color bounds must have positive spans")
        value = (centroid[axis] - bounds_min[axis]) * 2.0 / span - 1.0
        normalized_position.append(max(-1.0, min(1.0, value)))
    position_light = 0.5 + sum(
        FACE_POSITION_WEIGHTS[axis] * normalized_position[axis] for axis in range(3)
    )
    position_light = max(0.0, min(1.0, position_light))

    raw_intensity = (
        FACE_LIGHT_AMBIENT
        + FACE_LIGHT_DIRECTIONAL * lambert
        + FACE_LIGHT_POSITIONAL * position_light
    )
    intensity = (raw_intensity - FACE_LIGHT_BLACK_POINT) / (
        1.0 - FACE_LIGHT_BLACK_POINT
    )
    intensity = max(0.0, min(1.0, intensity))
    flat_level = min(
        DRAWABLE_COLOR_COUNT - 1,
        math.floor(intensity * (DRAWABLE_COLOR_COUNT - 1) + 0.5),
    )
    checker_level = min(
        DRAWABLE_COLOR_COUNT * 2 - 2,
        math.floor(intensity * (DRAWABLE_COLOR_COUNT * 2 - 2) + 0.5),
    )
    checker_low = 1 + checker_level // 2
    checker_high = checker_low + checker_level % 2
    return 1 + flat_level, (checker_high << 4) | checker_low


def validate_drawable_face_colors(face_records: bytes, *, label: str) -> int:
    """Reject any drawable face that uses the reserved clear-color index."""
    if len(face_records) % FACE_RECORD_BYTES:
        raise AssertionError(f"{label} face stream is not record-aligned")

    drawable_faces = 0
    for offset in range(0, len(face_records), FACE_RECORD_BYTES):
        face_index = offset // FACE_RECORD_BYTES
        vertex_count = face_records[offset + 2]
        if vertex_count == 0:
            continue
        flat = face_records[offset + 3]
        checker = face_records[offset + 4]
        indices = (flat, checker & 0x0F, checker >> 4)
        if vertex_count < 3:
            raise AssertionError(
                f"{label} face {face_index} has invalid vertex count {vertex_count}"
            )
        if any(not 1 <= index <= DRAWABLE_COLOR_COUNT for index in indices):
            raise AssertionError(
                f"{label} face {face_index} uses reserved clear-color index "
                f"in flat/checker values {flat:#04x}/{checker:#04x}"
            )
        drawable_faces += 1
    return drawable_faces


def bsp_draw_order(
    nodes: list[Node],
    planes: list[tuple[object, ...]],
    point: tuple[float, float, float],
    selected: set[int],
    root: int,
) -> list[int]:
    output: list[int] = []
    emitted: set[int] = set()

    def visit(node_index: int) -> None:
        if node_index < 0:
            return
        node = nodes[node_index]
        nx, ny, nz, distance, _ = planes[node.plane]
        side = 0 if point[0] * nx + point[1] * ny + point[2] * nz - distance >= 0 else 1
        visit(node.children[side ^ 1])
        for face_index in range(node.first_face, node.first_face + node.face_count):
            if face_index in selected and face_index not in emitted:
                emitted.add(face_index)
                output.append(face_index)
        visit(node.children[side])

    visit(root)
    output.extend(sorted(selected - emitted))
    return output


def build_world_node_topology(
    nodes: list[Node], root: int, first_face: int, face_count: int
) -> tuple[tuple[int, ...], tuple[int, ...], int]:
    """Map world faces to owners and reachable nodes to their unique parents."""

    if not 0 <= root < len(nodes):
        raise ValueError("world BSP root escapes the node table")
    if first_face < 0 or face_count < 0:
        raise ValueError("world BSP face range is invalid")

    unseen = -2
    parents = [unseen] * len(nodes)
    parents[root] = -1
    owners = [-1] * face_count
    stack = [root]
    reachable = 0
    while stack:
        node_index = stack.pop()
        node = nodes[node_index]
        reachable += 1

        begin = node.first_face - first_face
        end = begin + node.face_count
        if begin < 0 or end > face_count:
            raise ValueError(
                f"world node {node_index} face range escapes the world model"
            )
        for face_id in range(begin, end):
            if owners[face_id] >= 0:
                raise ValueError(f"world face {face_id} has multiple owning BSP nodes")
            owners[face_id] = node_index

        for child in node.children:
            if child < 0:
                continue
            if child >= len(nodes):
                raise ValueError(f"world node {node_index} has an invalid child")
            if parents[child] != unseen:
                raise ValueError(
                    f"world BSP child {child} is revisited (cycle or multiple parents)"
                )
            parents[child] = node_index
            stack.append(child)

    missing = [face_id for face_id, owner in enumerate(owners) if owner < 0]
    if missing:
        raise ValueError(
            f"world BSP root does not own {len(missing)} world-model faces"
        )

    encoded_parents = tuple(0xFFFF if parent < 0 else parent for parent in parents)
    return encoded_parents, tuple(owners), reachable


def tilemap_bytes() -> bytes:
    output = bytearray()
    for row in range(32):
        for column in range(32):
            tile = row * 32 + column if row < PHYSICAL_HEIGHT // 8 else 0
            output.extend(struct.pack("<H", tile))
    return bytes(output)


def texture_tilemap_bytes() -> bytes:
    """Map each 8x8 8bpp source tile to an exact 2x2 mosaic tile quad."""
    output = bytearray()
    for row in range(32):
        for column in range(32):
            if row < PHYSICAL_HEIGHT // 8 and column < PHYSICAL_WIDTH // 8:
                tile = (row // 2) * (LOGICAL_WIDTH // 8) + column // 2
                if column & 1:
                    tile |= 0x4000
                if row & 1:
                    tile |= 0x8000
            else:
                tile = 0
            output.extend(struct.pack("<H", tile))
    return bytes(output)


def texture_coordinate_map() -> bytes:
    """Swizzle logical pixels so mosaic plus tile flips produces exact 2x."""
    permutation = (0, 2, 4, 6, 7, 5, 3, 1)
    return bytes(
        (coordinate & ~7) | permutation[coordinate & 7] for coordinate in range(128)
    )


def texture_shading_assets(colormap: bytes) -> tuple[bytes, bytes, bytes]:
    """Build compact depth/lightmap remaps from Quake's original colormap."""
    table_bytes = 64 * 256
    if len(colormap) != table_bytes + 1 or colormap[-1] != 32:
        raise ValueError(
            "Quake colormap must contain 64 palette maps and 32 fullbrights"
        )
    distance_span = TEXTURE_SHADE_FAR_DISTANCE - TEXTURE_SHADE_NEAR_DISTANCE
    level_span = TEXTURE_DEPTH_COLORMAP_LEVELS - 1
    # GSU view depth is Q6. HIB extracts depth / 4 in one instruction, so the
    # LUT uses four-world-unit buckets and returns a compact row number.
    depth_lut = bytes(
        (
            max(
                0,
                min(
                    distance_span,
                    bucket * 4 - TEXTURE_SHADE_NEAR_DISTANCE,
                ),
            )
            * level_span
            + distance_span // 2
        )
        // distance_span
        for bucket in range(TEXTURE_DEPTH_SHADE_LUT_BYTES)
    )
    # Compact row zero is literal identity. Rows 1..27 deliberately retain
    # technique 3's old Quake rows 32..58; later rows supply nearly the full
    # static-lightmap range without changing an existing depth-shade index.
    shade_rows = bytes(range(256)) + b"".join(
        colormap[level * 256 : (level + 1) * 256]
        for level in TEXTURE_COLORMAP_SOURCE_LEVELS
    )
    if len(shade_rows) != TEXTURE_COLORMAP_BYTES:
        raise AssertionError("texture shading colormap has the wrong size")
    if any(
        shade_rows[level * 256 + index] != index
        for level in range(TEXTURE_COLORMAP_LEVELS)
        for index in range(224, 256)
    ):
        raise AssertionError("Quake fullbright indices changed in a shading row")

    compact_by_source = {
        source_level: compact_level
        for compact_level, source_level in enumerate(
            TEXTURE_COLORMAP_SOURCE_LEVELS, start=1
        )
    }
    lightmap_map = bytes(
        TEXTURE_COLORMAP_RAM_HIGH_BYTE
        + (
            0
            if source_level == 0
            else compact_by_source[max(LIGHTMAP_MIN_EXACT_COLORMAP_LEVEL, source_level)]
        )
        for source_level in range(64)
    )
    if len(lightmap_map) != LIGHTMAP_COLORMAP_MAP_BYTES:
        raise AssertionError("lightmap colormap map has the wrong size")
    return depth_lut, shade_rows, lightmap_map


def lightmap_level_zero_colormap(colormap: bytes) -> bytes:
    """Retain Quake's non-identity brightest row for the lightmap renderer."""
    table_bytes = 64 * 256
    if len(colormap) != table_bytes + 1 or colormap[-1] != 32:
        raise ValueError(
            "Quake colormap must contain 64 palette maps and 32 fullbrights"
        )
    return colormap[:256]


def lightmap_natural_colormap(colormap: bytes) -> bytes:
    """Lay out one directly addressable page per interpolated light level."""
    table_bytes = 64 * 256
    if len(colormap) != table_bytes + 1 or colormap[-1] != 32:
        raise ValueError(
            "Quake colormap must contain 64 palette maps and 32 fullbrights"
        )
    levels = (0, *([10] * 9), *range(10, 64))
    return b"".join(colormap[level * 256 : (level + 1) * 256] for level in levels)


# Keep the historical helper name as a source-compatible two-result wrapper
# for out-of-tree analysis scripts. New code should consume all three assets.
def texture_depth_shading_assets(colormap: bytes) -> tuple[bytes, bytes]:
    depth_lut, shade_rows, _ = texture_shading_assets(colormap)
    return depth_lut, shade_rows


def missing_lightmap_level(texture_name: str) -> int:
    """Return Quake's fallback row for one face without baked samples."""

    bypasses_lightmap = texture_name.casefold().startswith(("sky", "*"))
    return 0 if bypasses_lightmap else LIGHTMAP_DARKEST_LEVEL


def pack_world_lightmaps(
    faces: list[Face],
    vertices: list[tuple[float, float, float]],
    edges: list[tuple[int, int]],
    surfedges: list[int],
    texinfo: list[tuple[object, ...]],
    textures: list[MipTexture],
    lighting: bytes,
) -> tuple[bytes, tuple[bytes, ...], list[dict[str, object]]]:
    """Pack one neutral-style 6-bit sample grid per source world face."""

    directory = bytearray()
    chunks: list[bytearray] = [bytearray()]
    records: list[dict[str, object]] = []

    for face_index, face in enumerate(faces):
        polygon: list[tuple[float, float, float]] = []
        for edge_index in range(face.first_edge, face.first_edge + face.edge_count):
            surfedge = surfedges[edge_index]
            edge = edges[abs(surfedge)]
            polygon.append(vertices[edge[0] if surfedge >= 0 else edge[1]])
        if not polygon:
            raise ValueError(f"world face {face_index} has no lightmap polygon")

        texture_record = texinfo[face.texinfo]
        coordinates_s = [
            sum(float(texture_record[axis]) * vertex[axis] for axis in range(3))
            + float(texture_record[3])
            for vertex in polygon
        ]
        coordinates_t = [
            sum(float(texture_record[axis + 4]) * vertex[axis] for axis in range(3))
            + float(texture_record[7])
            for vertex in polygon
        ]
        min_block_s = math.floor(min(coordinates_s) / 16.0)
        min_block_t = math.floor(min(coordinates_t) / 16.0)
        max_block_s = math.ceil(max(coordinates_s) / 16.0)
        max_block_t = math.ceil(max(coordinates_t) / 16.0)
        width = max_block_s - min_block_s + 1
        height = max_block_t - min_block_t + 1
        if not (-128 <= min_block_s <= 127 and -128 <= min_block_t <= 127):
            raise ValueError(
                f"world face {face_index} lightmap minimum exceeds signed bytes"
            )
        if not (1 <= width <= 255 and 1 <= height <= 255):
            raise ValueError(
                f"world face {face_index} has unsupported lightmap dimensions "
                f"{width}x{height}"
            )

        try:
            style_count = face.light_styles.index(255)
        except ValueError:
            style_count = 4
        if any(style != 255 for style in face.light_styles[style_count:]):
            raise ValueError(f"world face {face_index} has unterminated light styles")

        if face.light_offset == -1:
            if style_count != 0:
                raise ValueError(
                    f"unlightmapped world face {face_index} retains light styles"
                )
            texture_id = int(texture_record[8])
            if not 0 <= texture_id < len(textures):
                raise ValueError(
                    f"unlightmapped world face {face_index} has invalid texture"
                )
            texture_name = textures[texture_id].name
            missing_level = missing_lightmap_level(texture_name)
            encoded_level = LIGHTMAP_ENCODED_LEVEL_BIAS + missing_level
            directory.extend(struct.pack("<BHBBbb", 0xFF, encoded_level, 0, 0, 0, 0))
            records.append(
                {
                    "face": face_index,
                    "lightmapped": False,
                    "missing_level": missing_level,
                    "texture": texture_name,
                    "styles": [],
                    "source_offset": -1,
                }
            )
            continue
        if face.light_offset < 0 or style_count <= 0:
            raise ValueError(f"world face {face_index} has invalid light metadata")

        sample_count = width * height
        required = sample_count * style_count
        if (
            face.light_offset > len(lighting)
            or required > len(lighting) - face.light_offset
        ):
            raise ValueError(
                f"world face {face_index} light samples escape the lighting lump"
            )

        packed = bytearray(sample_count)
        for sample_index in range(sample_count):
            accumulated = sum(
                lighting[face.light_offset + style * sample_count + sample_index]
                * QUAKE_NEUTRAL_LIGHT_STYLE_SCALE
                for style in range(style_count)
            )
            inverted = max(0, 255 * 256 - accumulated)
            darkness_8_8 = max(1 << 6, inverted >> 2)
            packed[sample_index] = min(63, darkness_8_8 >> 8)

        if len(packed) > ROM_BANK_BYTES:
            raise ValueError(f"world face {face_index} lightmap exceeds one ROM bank")
        if len(chunks[-1]) + len(packed) > ROM_BANK_BYTES:
            chunks.append(bytearray())
        chunk_index = len(chunks) - 1
        address = 0x8000 + len(chunks[-1])
        chunks[-1].extend(packed)
        bank = WORLD_LIGHTMAP_FIRST_GSU_ROM_BANK + chunk_index
        directory.extend(
            struct.pack(
                "<BHBBbb",
                bank,
                address,
                width,
                height,
                min_block_s,
                min_block_t,
            )
        )
        records.append(
            {
                "face": face_index,
                "lightmapped": True,
                "styles": list(face.light_styles[:style_count]),
                "source_offset": face.light_offset,
                "texture_min": [min_block_s * 16, min_block_t * 16],
                "dimensions": [width, height],
                "sample_bytes": sample_count,
                "gsu_rom_bank": bank,
                "gsu_rom_address": address,
                "min_level": min(packed),
                "max_level": max(packed),
            }
        )

    if len(directory) != len(faces) * LIGHTMAP_DIRECTORY_RECORD_BYTES:
        raise AssertionError("lightmap directory lost world-face identity")
    return bytes(directory), tuple(bytes(chunk) for chunk in chunks), records


def expansion_tables() -> tuple[bytes, bytes]:
    left = bytearray()
    right = bytearray()
    for value in range(256):
        expanded = 0
        for pixel in range(8):
            if value & (0x80 >> pixel):
                expanded |= 3 << (14 - pixel * 2)
        left.append((expanded >> 8) & 0xFF)
        right.append(expanded & 0xFF)
    return bytes(left), bytes(right)


def zero_run_encode(data: bytes) -> bytes:
    """Encode zero spans as ``0, count`` pairs, matching Quake VIS semantics."""
    output = bytearray()
    index = 0
    while index < len(data):
        if data[index]:
            output.append(data[index])
            index += 1
            continue
        end = index
        while end < len(data) and not data[end] and end - index < 255:
            end += 1
        output.extend((0, end - index))
        index = end
    return bytes(output)


def table_include(
    vertex_count: int, index_count: int, face_count: int, yaw_index: int
) -> bytes:
    sin_values = [round(math.sin(index * math.tau / 32) * 64) for index in range(32)]
    cos_values = [round(math.cos(index * math.tau / 32) * 64) for index in range(32)]
    move_scale = 32
    lines = [
        "; Generated by tools/generate_quake_bsp.py. Do not edit.",
        f"BSP_VERTEX_COUNT       = {vertex_count}",
        f"BSP_INDEX_COUNT        = {index_count}",
        f"BSP_FACE_COUNT         = {face_count}",
        f"BSP_FACE_RECORD_BYTES  = {FACE_RECORD_BYTES}",
        f"BSP_FACE_PLANE_RECORD_BYTES = {FACE_PLANE_RECORD_BYTES}",
        f"BSP_START_YAW_INDEX    = {yaw_index}",
        f"BSP_WORLD_SCALE        = {int(WORLD_SCALE)}",
        f"BSP_NEAR_DEPTH         = {NEAR_DEPTH}",
        f"BSP_VIEW_FRACTION_BITS = {VIEW_FRACTION_BITS}",
        f"BSP_DEPTH_TABLE_FRACTION_BITS = {DEPTH_TABLE_FRACTION_BITS}",
        f"BSP_RECIPROCAL_NUMERATOR = {RECIPROCAL_NUMERATOR}",
        f"BSP_PROJECTION_SHIFT   = {PROJECTION_SHIFT}",
        "",
        ".macro BSP_CAMERA_MOVE_TABLES",
        "BSPCameraMoveCos:",
        "        .word "
        + ", ".join(
            str(round(value * move_scale / 64) & 0xFFFF) for value in cos_values
        ),
        "BSPCameraMoveSin:",
        "        .word "
        + ", ".join(
            str(round(value * move_scale / 64) & 0xFFFF) for value in sin_values
        ),
        ".endmacro",
        "",
    ]
    return "\n".join(lines).encode("ascii")


def world_table_include(info: dict[str, object]) -> bytes:
    origin = info["origin"]
    coordinate_min = info["coordinate_min"]
    coordinate_max = info["coordinate_max"]
    assert isinstance(origin, tuple)
    assert isinstance(coordinate_min, tuple)
    assert isinstance(coordinate_max, tuple)
    lines = [
        "; Full E1M3 world package and demo1 track; generated for runtime traversal.",
        f"BSP_WORLD_ROOT_NODE = {info['root_node']}",
        f"BSP_WORLD_FIRST_FACE = {info['first_face']}",
        f"BSP_WORLD_VERTEX_COUNT = {info['vertex_count']}",
        f"BSP_WORLD_INDEX_COUNT = {info['index_count']}",
        f"BSP_WORLD_FACE_COUNT = {info['face_count']}",
        f"BSP_WORLD_MAX_FACE_VERTICES = {info['max_face_vertices']}",
        f"BSP_WORLD_DRAWABLE_FACE_COUNT = {info['drawable_face_count']}",
        f"BSP_WORLD_NONDRAWABLE_FACE_COUNT = {info['nondrawable_face_count']}",
        f"BSP_WORLD_NODE_COUNT = {info['node_count']}",
        f"BSP_WORLD_PLANE_COUNT = {info['plane_count']}",
        f"BSP_WORLD_LEAF_COUNT = {info['leaf_count']}",
        f"BSP_WORLD_VIS_LEAF_COUNT = {info['vis_leaf_count']}",
        f"BSP_WORLD_MARKSURFACE_COUNT = {info['marksurface_count']}",
        f"BSP_WORLD_VISIBILITY_BYTES = {info['visibility_bytes']}",
        f"BSP_WORLD_VERTEX_RECORD_BYTES = {info['vertex_record_bytes']}",
        f"BSP_WORLD_INDEX_RECORD_BYTES = {info['index_record_bytes']}",
        f"BSP_WORLD_FACE_RECORD_BYTES = {FACE_RECORD_BYTES}",
        f"BSP_WORLD_FACE_PLANE_RECORD_BYTES = {FACE_PLANE_RECORD_BYTES}",
        f"BSP_WORLD_SHADING_RECORD_BYTES = {info['shading_record_bytes']}",
        f"BSP_WORLD_SHADING_DISTANCE_LUT_OFFSET = {int(info['face_count']) * WORLD_SHADING_RECORD_BYTES}",
        f"BSP_WORLD_SHADING_DISTANCE_LUT_BYTES = {DISTANCE_LUT_BYTES}",
        f"BSP_WORLD_SHADING_TABLE_OFFSET = {int(info['face_count']) * WORLD_SHADING_RECORD_BYTES + DISTANCE_LUT_BYTES}",
        f"BSP_WORLD_SHADING_TABLE_BYTES = {info['shading_table_bytes']}",
        f"BSP_WORLD_SHADING_BYTES = {info['shading_bytes']}",
        f"BSP_WORLD_SHADING_GSU_ROM_BANK = {WORLD_SHADING_GSU_ROM_BANK}",
        f"BSP_WORLD_TEXTURE_COUNT = {info['texture_count']}",
        f"BSP_WORLD_TEXTURE_COORD_RECORD_BYTES = {TEXTURE_COORD_RECORD_BYTES}",
        f"BSP_WORLD_TEXTURE_COORD_BYTES = {info['texture_coordinate_bytes']}",
        f"BSP_WORLD_TEXTURE_COORD_0_BYTES = {info['texture_coordinate_0_bytes']}",
        f"BSP_WORLD_TEXTURE_COORD_1_BYTES = {info['texture_coordinate_1_bytes']}",
        f"BSP_WORLD_TEXTURE_COORD_2_BYTES = {info['texture_coordinate_2_bytes']}",
        f"BSP_WORLD_TEXTURE_COORD_FIRST_GSU_ROM_BANK = {WORLD_TEXCOORD_FIRST_GSU_ROM_BANK}",
        f"BSP_WORLD_FACE_TEXTURE_ID_BYTES = {info['face_texture_id_bytes']}",
        f"BSP_WORLD_FACE_TEXTURE_ID_GSU_ROM_ADDRESS = ${0x8000 + int(info['texture_coordinate_2_bytes']):04X}",
        f"BSP_WORLD_TEXTURE_DIRECTORY_RECORD_BYTES = {TEXTURE_DIRECTORY_RECORD_BYTES}",
        f"BSP_WORLD_TEXTURE_FLAG_POWER_OF_TWO_AXES = {TEXTURE_FLAG_POWER_OF_TWO_AXES}",
        f"BSP_WORLD_TEXTURE_FLAG_SINGLE_BANK = {TEXTURE_FLAG_SINGLE_BANK}",
        f"BSP_WORLD_TEXTURE_DIRECTORY_BYTES = {info['texture_directory_bytes']}",
        f"BSP_WORLD_TEXTURE_DIRECTORY_GSU_ROM_BANK = {WORLD_TEXTURE_DIRECTORY_GSU_ROM_BANK}",
        f"BSP_WORLD_TEXTURE_DIRECTORY_GSU_ROM_ADDRESS = ${0x8000 + int(info['texture_coordinate_2_bytes']) + int(info['face_texture_id_bytes']):04X}",
        f"BSP_WORLD_TEXTURE_PIXEL_BYTES = {info['texture_pixel_bytes']}",
        f"BSP_WORLD_TEXTURE_PIXEL_CHUNK_COUNT = {info['texture_pixel_chunk_count']}",
        f"BSP_WORLD_TEXTURE_FIRST_GSU_ROM_BANK = {WORLD_TEXTURE_FIRST_GSU_ROM_BANK}",
        f"BSP_WORLD_LIGHTMAP_DIRECTORY_RECORD_BYTES = {LIGHTMAP_DIRECTORY_RECORD_BYTES}",
        f"BSP_WORLD_LIGHTMAP_DIRECTORY_BYTES = {info['lightmap_directory_bytes']}",
        f"BSP_WORLD_LIGHTMAP_DIRECTORY_GSU_ROM_BANK = {WORLD_LIGHTMAP_DIRECTORY_GSU_ROM_BANK}",
        "BSP_WORLD_LIGHTMAP_DIRECTORY_GSU_ROM_ADDRESS = $8000",
        f"BSP_WORLD_LIGHTMAP_SAMPLE_BYTES = {info['lightmap_sample_bytes']}",
        f"BSP_WORLD_LIGHTMAP_MAX_FACE_SAMPLE_BYTES = {info['lightmap_max_face_sample_bytes']}",
        f"BSP_WORLD_LIGHTMAP_CHUNK_COUNT = {info['lightmap_chunk_count']}",
        f"BSP_WORLD_LIGHTMAP_FIRST_GSU_ROM_BANK = {WORLD_LIGHTMAP_FIRST_GSU_ROM_BANK}",
        f"BSP_WORLD_LIGHTMAPPED_FACE_COUNT = {info['lightmapped_face_count']}",
        f"BSP_TEXTURE_DEPTH_SHADE_LUT_BYTES = {TEXTURE_DEPTH_SHADE_LUT_BYTES}",
        f"BSP_TEXTURE_DEPTH_COLORMAP_FIRST_LEVEL = {TEXTURE_DEPTH_COLORMAP_FIRST_LEVEL}",
        f"BSP_TEXTURE_DEPTH_COLORMAP_LEVELS = {TEXTURE_DEPTH_COLORMAP_LEVELS}",
        f"BSP_TEXTURE_COLORMAP_LEVELS = {TEXTURE_COLORMAP_LEVELS}",
        f"BSP_TEXTURE_COLORMAP_BYTES = {TEXTURE_COLORMAP_BYTES}",
        f"BSP_LIGHTMAP_COLORMAP_MAP_BYTES = {LIGHTMAP_COLORMAP_MAP_BYTES}",
        f"BSP_LIGHTMAP_MIN_EXACT_COLORMAP_LEVEL = {LIGHTMAP_MIN_EXACT_COLORMAP_LEVEL}",
        f"BSP_TEXTURE_SHADE_NEAR_DISTANCE = {TEXTURE_SHADE_NEAR_DISTANCE}",
        f"BSP_TEXTURE_SHADE_FAR_DISTANCE = {TEXTURE_SHADE_FAR_DISTANCE}",
        f"BSP_WORLD_NODE_RECORD_BYTES = {WORLD_NODE_RECORD_BYTES}",
        f"BSP_WORLD_NODE_PARENT_RECORD_BYTES = {WORLD_NODE_PARENT_RECORD_BYTES}",
        f"BSP_WORLD_FACE_OWNER_RECORD_BYTES = {WORLD_FACE_OWNER_RECORD_BYTES}",
        f"BSP_WORLD_REACHABLE_NODE_COUNT = {info['reachable_node_count']}",
        f"BSP_WORLD_PLANE_RECORD_BYTES = {WORLD_PLANE_RECORD_BYTES}",
        f"BSP_WORLD_LEAF_RECORD_BYTES = {WORLD_LEAF_RECORD_BYTES}",
        f"BSP_WORLD_MARKSURFACE_RECORD_BYTES = {WORLD_MARKSURFACE_RECORD_BYTES}",
        f"BSP_WORLD_INDICES_0_BYTES = {info['indices_0_bytes']}",
        f"BSP_WORLD_INDICES_1_BYTES = {info['indices_1_bytes']}",
        f"BSP_WORLD_VISIBILITY_0_BYTES = {info['visibility_0_bytes']}",
        f"BSP_WORLD_VISIBILITY_1_BYTES = {info['visibility_1_bytes']}",
        f"BSP_WORLD_FACE_BITSET_BYTES = {info['face_bitset_bytes']}",
        f"BSP_WORLD_PVS_DIRECTORY_RECORD_BYTES = {WORLD_PVS_DIRECTORY_RECORD_BYTES}",
        f"BSP_WORLD_PVS_DIRECTORY_BYTES = {info['pvs_directory_bytes']}",
        f"BSP_WORLD_PVS_GUARD_RECORD_BYTES = {WORLD_PVS_GUARD_RECORD_BYTES}",
        f"BSP_WORLD_PVS_GUARD_RECORD_COUNT = {info['pvs_guard_record_count']}",
        f"BSP_WORLD_PVS_GUARD_BYTES = {info['pvs_guard_bytes']}",
        f"BSP_WORLD_PVS_GUARD_ROM_ADDRESS = ${0x8000 + int(info['pvs_directory_bytes']):04X}",
        f"BSP_WORLD_PVS_CHUNK_COUNT = {info['pvs_chunk_count']}",
        f"BSP_WORLD_PVS_COMPRESSED_BYTES = {info['pvs_compressed_bytes']}",
        f"BSP_WORLD_PVS_FIRST_GSU_ROM_BANK = {WORLD_PVS_FIRST_GSU_ROM_BANK}",
        f"BSP_DEMO_TRACK_RECORD_BYTES = {DEMO_TRACK_RECORD_BYTES}",
        f"BSP_DEMO_TRACK_POSE_COUNT = {info['demo_pose_count']}",
        f"BSP_DEMO_TRACK_BYTES = {info['demo_track_bytes']}",
        f"BSP_DEMO_TIMING_RECORD_BYTES = {DEMO_TIMING_RECORD_BYTES}",
        f"BSP_DEMO_TIMING_BYTES = {info['demo_timing_bytes']}",
        f"BSP_DEMO_DURATION_TICKS = {info['demo_duration_ticks']}",
        f"BSP_DEMO_PRECISE_TRACK_RECORD_BYTES = {DEMO_PRECISE_TRACK_RECORD_BYTES}",
        f"BSP_DEMO_PRECISE_TRACK_POSE_COUNT = {info['demo_precise_pose_count']}",
        f"BSP_DEMO_PRECISE_TRACK_BYTES = {info['demo_precise_track_bytes']}",
        f"BSP_DEMO_PRECISE_TIMING_RECORD_BYTES = {DEMO_TIMING_RECORD_BYTES}",
        f"BSP_DEMO_PRECISE_TIMING_BYTES = {info['demo_precise_timing_bytes']}",
        f"BSP_DEMO_PRECISE_DURATION_TICKS = {info['demo_precise_duration_ticks']}",
        f"BSP_DEMO_PRECISE_SAMPLE_RATE_HZ = {DEMO_PRECISE_SAMPLE_RATE_HZ}",
        f"BSP_DEMO_STEP_SAMPLE_RATE_HZ = {DEMO_STEP_SAMPLE_RATE_HZ}",
        f"BSP_DEMO_STEP_STRIDE = {DEMO_STEP_STRIDE}",
        f"BSP_DEMO_STEP_POSE_COUNT = {info['demo_step_pose_count']}",
        f"BSP_DEMO_VERIFY_NEAR_POSE = {info['demo_verify_near_pose']}",
        f"BSP_DEMO_VERIFY_FAR_POSE = {info['demo_verify_far_pose']}",
        f"BSP_WORLD_START_X = {info['start_coordinate'][0]}",
        f"BSP_WORLD_START_Y = {info['start_coordinate'][1]}",
        f"BSP_WORLD_START_Z = {info['start_coordinate'][2]}",
        f"BSP_WORLD_START_X_Q8 = {int(info['start_coordinate'][0]) << 8 & 0xFFFF}",
        f"BSP_WORLD_START_Y_Q8 = {int(info['start_coordinate'][1]) << 8 & 0xFFFF}",
        f"BSP_WORLD_START_Z_Q8 = {int(info['start_coordinate'][2]) << 8 & 0xFFFF}",
        f"BSP_WORLD_COORD_MIN_X_Q8 = {int(coordinate_min[0]) << 8 & 0xFFFF}",
        f"BSP_WORLD_COORD_MIN_Y_Q8 = {int(coordinate_min[1]) << 8 & 0xFFFF}",
        f"BSP_WORLD_COORD_MIN_Z_Q8 = {int(coordinate_min[2]) << 8 & 0xFFFF}",
        f"BSP_WORLD_COORD_MAX_X_Q8 = {int(coordinate_max[0]) << 8 & 0xFFFF}",
        f"BSP_WORLD_COORD_MAX_Y_Q8 = {int(coordinate_max[1]) << 8 & 0xFFFF}",
        f"BSP_WORLD_COORD_MAX_Z_Q8 = {int(coordinate_max[2]) << 8 & 0xFFFF}",
        f"BSP_WORLD_ORIGIN_X = {round(float(origin[0]))}",
        f"BSP_WORLD_ORIGIN_Y = {round(float(origin[1]))}",
        f"BSP_WORLD_ORIGIN_Z = {round(float(origin[2]))}",
        f"BSP_WORLD_COORD_MIN_X = {coordinate_min[0]}",
        f"BSP_WORLD_COORD_MIN_Y = {coordinate_min[1]}",
        f"BSP_WORLD_COORD_MIN_Z = {coordinate_min[2]}",
        f"BSP_WORLD_COORD_MAX_X = {coordinate_max[0]}",
        f"BSP_WORLD_COORD_MAX_Y = {coordinate_max[1]}",
        f"BSP_WORLD_COORD_MAX_Z = {coordinate_max[2]}",
        "",
    ]
    return "\n".join(lines).encode("ascii")
