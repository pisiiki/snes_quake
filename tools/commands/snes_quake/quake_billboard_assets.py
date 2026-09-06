"""Source MDL/IDSP codecs and rasters for the shared Quake billboard path."""

from __future__ import annotations

import hashlib
import math
import struct
from collections import defaultdict
from dataclasses import dataclass
from enum import IntEnum
from fractions import Fraction
from typing import Callable, Iterable

import quake_assets
from quake_demo import CameraEntitySample, EntityState


VIEW_COUNT = 8
# Freeze the qualified eight-way projection basis instead of asking the host C
# math library to approximate multiples of pi/4.  A one-ULP sin(pi/4)
# difference between Windows and Linux is enough to move an interpolated MDL
# texture coordinate across an integer boundary.  These exact binary values
# preserve the already-qualified sprite package while making every view
# independent of libm.
MDL_VIEW_BASES = (
    (1.0, 0.0),
    (
        float.fromhex("0x1.6a09e667f3bcdp-1"),
        float.fromhex("0x1.6a09e667f3bcdp-1"),
    ),
    (float.fromhex("0x1.1a62633145c07p-54"), 1.0),
    (
        float.fromhex("-0x1.6a09e667f3bccp-1"),
        float.fromhex("0x1.6a09e667f3bcdp-1"),
    ),
    (-1.0, float.fromhex("0x1.1a62633145c07p-53")),
    (
        float.fromhex("-0x1.6a09e667f3bcep-1"),
        float.fromhex("-0x1.6a09e667f3bccp-1"),
    ),
    (float.fromhex("-0x1.a79394c9e8a0ap-53"), -1.0),
    (
        float.fromhex("0x1.6a09e667f3bcbp-1"),
        float.fromhex("-0x1.6a09e667f3bcep-1"),
    ),
)
SPR_MAGIC = b"IDSP"
SPR_VERSION = 1
SPR_HEADER = struct.Struct("<4siifiiifi")
SPR_FRAME_HEADER = struct.Struct("<4i")
SPR_MAX_FILE_BYTES = 16 * 1024 * 1024
SPR_MAX_FRAMES = 4096
SPR_MAX_DIMENSION = 4096
SPR_MAX_PIXELS = 16 * 1024 * 1024


@dataclass(frozen=True, order=True, slots=True)
class SpriteRaster:
    """Canonical encoded sprite identity, independent of placement metadata."""

    width: int
    height: int
    pixels: bytes

    def __post_init__(self) -> None:
        if not 0 < self.width <= 0xFF or not 0 < self.height <= 0xFF:
            raise ValueError("canonical sprite dimensions escape u8 storage")
        if len(self.pixels) != self.width * self.height:
            raise ValueError("canonical sprite raster size disagrees with dimensions")

    def __len__(self) -> int:
        return len(self.pixels)


class SpriteOrientation(IntEnum):
    VIEW_PARALLEL_UPRIGHT = 0
    FACING_UPRIGHT = 1
    VIEW_PARALLEL = 2
    ORIENTED = 3
    VIEW_PARALLEL_ORIENTED = 4


ORIENTATION_NAMES = {
    SpriteOrientation.VIEW_PARALLEL_UPRIGHT: "view-plane-parallel-upright",
    SpriteOrientation.FACING_UPRIGHT: "facing-upright",
    SpriteOrientation.VIEW_PARALLEL: "view-plane-parallel",
    SpriteOrientation.ORIENTED: "oriented",
    SpriteOrientation.VIEW_PARALLEL_ORIENTED: "view-plane-parallel-oriented",
}


@dataclass(frozen=True, slots=True)
class BillboardSprite:
    # width/height name the stored source raster. world_width/world_height
    # retain the exact source extent projected by the runtime.
    width: int
    height: int
    left: int
    top: int
    pixels: tuple[int, ...]
    world_width: int = 0
    world_height: int = 0
    model: int = 0
    frame: int = 0
    view: int = 0
    visibility_width: int = 0
    visibility_height: int = 0
    visibility_pixels: tuple[int, ...] = ()

    @property
    def projected_width(self) -> int:
        return self.world_width or self.width

    @property
    def projected_height(self) -> int:
        return self.world_height or self.height

    @property
    def visibility_raster(self) -> tuple[int, int, tuple[int, ...]]:
        if self.visibility_pixels:
            return self.visibility_width, self.visibility_height, self.visibility_pixels
        return self.width, self.height, self.pixels

    @property
    def encoded_pixels(self) -> bytes:
        payload = bytearray()
        for pixel in self.pixels:
            if not pixel & 0x0100:
                payload.append(0)
                continue
            color = pixel & 0xFF
            if color == 0xFF:
                raise ValueError("opaque alias texel escapes biased-byte storage")
            payload.append(color + 1)
        return bytes(payload)

    @property
    def storage_raster(self) -> SpriteRaster:
        return SpriteRaster(self.width, self.height, self.encoded_pixels)


def canonicalize_sprite_rasters(
    sprites: tuple[BillboardSprite, ...],
) -> tuple[SpriteRaster, ...]:
    """Intern complete sprite rasters before visibility or residency decisions."""

    canonical: dict[SpriteRaster, SpriteRaster] = {}
    result: list[SpriteRaster] = []
    for sprite in sprites:
        raster = sprite.storage_raster
        result.append(canonical.setdefault(raster, raster))
    return tuple(result)


def _density_fraction(world_units_per_texel: float) -> Fraction:
    if isinstance(world_units_per_texel, bool) or not isinstance(
        world_units_per_texel, (int, float)
    ):
        raise ValueError("MDL world units per texel must be numeric")
    if not math.isfinite(world_units_per_texel) or world_units_per_texel < 1:
        raise ValueError("MDL world units per texel must be at least one")
    return Fraction(str(world_units_per_texel))


def _density_output_extent(extent: int, density: Fraction) -> int:
    return (extent * density.denominator + density.numerator - 1) // density.numerator


def _density_block_bounds(
    index: int, extent: int, density: Fraction
) -> tuple[int, int]:
    start = index * density.numerator // density.denominator
    stop = min(extent, (index + 1) * density.numerator // density.denominator)
    if stop <= start:
        raise AssertionError("MDL density produced an empty reduction block")
    return start, stop


def summarize_mdl_raster_fidelity(
    sprites: Iterable[BillboardSprite], world_units_per_texel: float
) -> dict[str, object]:
    """Measure storage reduction against each retained density-one projection."""

    if world_units_per_texel <= 0:
        raise ValueError("MDL world units per texel must be positive")
    density = _density_fraction(world_units_per_texel)
    materialized = tuple(sprites)
    if not materialized:
        raise ValueError("MDL fidelity summary requires at least one sprite")
    totals = defaultdict(int)
    minimum_silhouette: Fraction | None = None
    minimum_palette: Fraction | None = None
    for sprite in materialized:
        visibility_width, visibility_height, visibility = sprite.visibility_raster
        expected_width = _density_output_extent(visibility_width, density)
        expected_height = _density_output_extent(visibility_height, density)
        if (visibility_width, visibility_height) != (
            sprite.projected_width,
            sprite.projected_height,
        ):
            raise ValueError("MDL visibility raster lost its density-one extent")
        if (sprite.width, sprite.height) != (expected_width, expected_height):
            raise ValueError("MDL storage raster silently changed configured density")
        totals["visibilityTexelCount"] += len(visibility)
        totals["storageTexelCount"] += len(sprite.pixels)
        visibility_opaque = sum(bool(pixel & 0xFF00) for pixel in visibility)
        if not visibility_opaque:
            raise ValueError("MDL visibility raster has no opaque texels")
        storage_opaque = sum(bool(pixel & 0xFF00) for pixel in sprite.pixels)
        totals["visibilityOpaqueTexelCount"] += visibility_opaque
        totals["storageOpaqueTexelCount"] += storage_opaque
        if not storage_opaque:
            totals["emptyStorageRasterCount"] += 1
        intersection = 0
        union = 0
        palette_matches = 0
        for output_y in range(sprite.height):
            top, bottom = _density_block_bounds(output_y, visibility_height, density)
            for output_x in range(sprite.width):
                left, right = _density_block_bounds(output_x, visibility_width, density)
                opaque = tuple(
                    visibility[y * visibility_width + x]
                    for y in range(top, bottom)
                    for x in range(left, right)
                    if visibility[y * visibility_width + x] & 0xFF00
                )
                stored = sprite.pixels[output_y * sprite.width + output_x]
                stored_opaque = bool(stored & 0xFF00)
                if stored_opaque != bool(opaque):
                    totals["opacityBlockMismatchCount"] += 1
                block_area = (right - left) * (bottom - top)
                intersection += len(opaque) if stored_opaque else 0
                union += block_area if stored_opaque else len(opaque)
                if stored_opaque:
                    palette_matches += opaque.count(stored)
                    if stored not in opaque:
                        totals["representativeSourceMissCount"] += 1
        silhouette = Fraction(intersection, union)
        palette = Fraction(palette_matches, visibility_opaque)
        minimum_silhouette = (
            silhouette
            if minimum_silhouette is None
            else min(silhouette, minimum_silhouette)
        )
        minimum_palette = (
            palette if minimum_palette is None else min(palette, minimum_palette)
        )
        totals["silhouetteIntersectionTexelCount"] += intersection
        totals["silhouetteUnionTexelCount"] += union
        totals["paletteRepresentativeMatchTexelCount"] += palette_matches
    if any(
        totals[field]
        for field in (
            "emptyStorageRasterCount",
            "opacityBlockMismatchCount",
            "representativeSourceMissCount",
        )
    ):
        raise AssertionError("MDL storage reduction violated its fidelity contract")
    assert minimum_silhouette is not None and minimum_palette is not None
    return {
        "variantCount": len(materialized),
        **dict(totals),
        "minimumVariantSilhouetteIou": {
            "numerator": minimum_silhouette.numerator,
            "denominator": minimum_silhouette.denominator,
        },
        "minimumVariantPaletteAgreement": {
            "numerator": minimum_palette.numerator,
            "denominator": minimum_palette.denominator,
        },
    }


@dataclass(frozen=True, slots=True)
class SprFrame:
    origin: tuple[int, int]
    width: int
    height: int
    pixels: bytes

    @property
    def transparency_bounds(self) -> tuple[int, int, int, int] | None:
        opaque = tuple(index for index, color in enumerate(self.pixels) if color != 255)
        if not opaque:
            return None
        xs = tuple(index % self.width for index in opaque)
        ys = tuple(index // self.width for index in opaque)
        return min(xs), min(ys), max(xs), max(ys)


@dataclass(frozen=True, slots=True)
class SprGroup:
    intervals: tuple[float, ...]
    frames: tuple[SprFrame, ...]


SprTopFrame = SprFrame | SprGroup


@dataclass(frozen=True, slots=True)
class SprModel:
    orientation: SpriteOrientation
    bounding_radius: float
    width: int
    height: int
    frames: tuple[SprTopFrame, ...]
    beam_length: float
    sync_type: int


BillboardModel = quake_assets.MdlModel | SprModel


def billboard_model_kind(model: BillboardModel) -> str:
    return "spr" if isinstance(model, SprModel) else "mdl"


def billboard_frame_count(model: BillboardModel) -> int:
    return len(model.frames)


def billboard_frame_name(model: BillboardModel, frame: int) -> str:
    return f"frame{frame}" if isinstance(model, SprModel) else model.frames[frame].name


class SprFormatError(ValueError):
    """A source IDSP payload violates the bounded Quake v1 contract."""


class _SprReader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.offset = 0

    def read(self, size: int, label: str) -> bytes:
        if size < 0 or self.offset + size > len(self.data):
            raise SprFormatError(f"truncated IDSP {label}")
        result = self.data[self.offset : self.offset + size]
        self.offset += size
        return result

    def unpack(self, record: struct.Struct, label: str) -> tuple[object, ...]:
        return record.unpack(self.read(record.size, label))

    def i32(self, label: str) -> int:
        return int(struct.unpack("<i", self.read(4, label))[0])

    def f32(self, label: str) -> float:
        return float(struct.unpack("<f", self.read(4, label))[0])


def _bounded_count(value: int, label: str) -> int:
    if not 0 < value <= SPR_MAX_FRAMES:
        raise SprFormatError(
            f"IDSP {label} count {value} is outside 1..{SPR_MAX_FRAMES}"
        )
    return value


def _read_spr_frame(
    reader: _SprReader, model_width: int, model_height: int
) -> SprFrame:
    origin_x, origin_y, width, height = (
        int(value) for value in reader.unpack(SPR_FRAME_HEADER, "frame header")
    )
    if not 0 < width <= min(model_width, SPR_MAX_DIMENSION):
        raise SprFormatError("IDSP frame width is empty or exceeds its header bound")
    if not 0 < height <= min(model_height, SPR_MAX_DIMENSION):
        raise SprFormatError("IDSP frame height is empty or exceeds its header bound")
    pixels = width * height
    if pixels > SPR_MAX_PIXELS:
        raise SprFormatError("IDSP frame pixel count exceeds the codec bound")
    return SprFrame((origin_x, origin_y), width, height, reader.read(pixels, "pixels"))


def parse_spr(data: bytes) -> SprModel:
    """Parse one complete, bounded Quake IDSP v1 payload."""

    if len(data) > SPR_MAX_FILE_BYTES:
        raise SprFormatError("IDSP payload exceeds the codec byte bound")
    reader = _SprReader(data)
    (
        magic,
        version,
        orientation,
        bounding_radius,
        width,
        height,
        frame_count,
        beam_length,
        sync_type,
    ) = reader.unpack(SPR_HEADER, "header")
    if magic != SPR_MAGIC:
        raise SprFormatError("invalid IDSP magic")
    if version != SPR_VERSION:
        raise SprFormatError(f"unsupported IDSP version {version}")
    try:
        parsed_orientation = SpriteOrientation(int(orientation))
    except ValueError as error:
        raise SprFormatError(f"invalid IDSP orientation {orientation}") from error
    if not math.isfinite(float(bounding_radius)) or float(bounding_radius) < 0.0:
        raise SprFormatError("IDSP bounding radius must be finite and nonnegative")
    if not 0 < int(width) <= SPR_MAX_DIMENSION:
        raise SprFormatError("IDSP maximum width is outside the codec bound")
    if not 0 < int(height) <= SPR_MAX_DIMENSION:
        raise SprFormatError("IDSP maximum height is outside the codec bound")
    _bounded_count(int(frame_count), "top-level frame")
    if not math.isfinite(float(beam_length)):
        raise SprFormatError("IDSP beam length must be finite")
    if sync_type not in (0, 1):
        raise SprFormatError(f"invalid IDSP sync type {sync_type}")

    frames: list[SprTopFrame] = []
    total_pixels = 0
    for frame_index in range(int(frame_count)):
        frame_type = reader.i32(f"frame {frame_index} type")
        if frame_type == 0:
            frame = _read_spr_frame(reader, int(width), int(height))
            total_pixels += len(frame.pixels)
            frames.append(frame)
            continue
        if frame_type != 1:
            raise SprFormatError(f"invalid IDSP frame type {frame_type}")
        group_count = _bounded_count(
            reader.i32(f"frame {frame_index} group count"), "group frame"
        )
        intervals = tuple(
            reader.f32(f"frame {frame_index} group interval")
            for _ in range(group_count)
        )
        if any(
            not math.isfinite(interval) or interval <= 0.0 for interval in intervals
        ):
            raise SprFormatError("IDSP group intervals must be finite and positive")
        if any(second <= first for first, second in zip(intervals, intervals[1:])):
            raise SprFormatError("IDSP group intervals must be strictly increasing")
        group_frames = tuple(
            _read_spr_frame(reader, int(width), int(height)) for _ in range(group_count)
        )
        total_pixels += sum(len(frame.pixels) for frame in group_frames)
        frames.append(SprGroup(intervals, group_frames))
    if total_pixels > SPR_MAX_PIXELS:
        raise SprFormatError("IDSP aggregate pixel count exceeds the codec bound")
    if reader.offset != len(data):
        raise SprFormatError("IDSP payload has trailing bytes")
    return SprModel(
        parsed_orientation,
        float(bounding_radius),
        int(width),
        int(height),
        tuple(frames),
        float(beam_length),
        int(sync_type),
    )


def encode_spr(model: SprModel) -> bytes:
    """Encode a parsed IDSP model deterministically for exact codec fixtures."""

    output = bytearray(
        SPR_HEADER.pack(
            SPR_MAGIC,
            SPR_VERSION,
            int(model.orientation),
            model.bounding_radius,
            model.width,
            model.height,
            len(model.frames),
            model.beam_length,
            model.sync_type,
        )
    )
    for top_frame in model.frames:
        if isinstance(top_frame, SprGroup):
            output.extend(struct.pack("<ii", 1, len(top_frame.frames)))
            output.extend(
                struct.pack(f"<{len(top_frame.intervals)}f", *top_frame.intervals)
            )
            frames = top_frame.frames
        else:
            output.extend(struct.pack("<i", 0))
            frames = (top_frame,)
        for frame in frames:
            output.extend(
                SPR_FRAME_HEADER.pack(
                    frame.origin[0], frame.origin[1], frame.width, frame.height
                )
            )
            output.extend(frame.pixels)
    encoded = bytes(output)
    # Reuse the parser as the encoder's complete bounds and consistency check.
    parse_spr(encoded)
    return encoded


def resolved_spr_frame(model: SprModel, frame: int) -> int:
    return frame if 0 <= frame < len(model.frames) else 0


def spr_subframe(model: SprModel, frame: int, server_time: float) -> int:
    """Apply Quake's cumulative group-interval selection at one server time."""

    top_frame = model.frames[resolved_spr_frame(model, frame)]
    if isinstance(top_frame, SprFrame):
        return 0
    if not math.isfinite(server_time):
        raise ValueError("sprite server time must be finite")
    cycle = top_frame.intervals[-1]
    target = server_time - math.floor(server_time / cycle) * cycle
    for index, interval in enumerate(top_frame.intervals[:-1]):
        if interval > target:
            return index
    return len(top_frame.frames) - 1


def spr_source_frame(model: SprModel, frame: int, subframe: int = 0) -> SprFrame:
    top_frame = model.frames[resolved_spr_frame(model, frame)]
    if isinstance(top_frame, SprFrame):
        if subframe != 0:
            raise ValueError("single IDSP frame has no nonzero subframe")
        return top_frame
    if not 0 <= subframe < len(top_frame.frames):
        raise ValueError("IDSP group subframe is out of range")
    return top_frame.frames[subframe]


def rasterize_spr_billboard(
    model: SprModel,
    *,
    frame_index: int = 0,
    subframe: int = 0,
    model_id: int = 0,
) -> BillboardSprite:
    """Crop transparent IDSP borders while preserving exact source placement."""

    if model.orientation != SpriteOrientation.VIEW_PARALLEL:
        raise ValueError(
            "the shared camera-facing billboard path requires view-plane-parallel IDSP"
        )
    frame_index = resolved_spr_frame(model, frame_index)
    frame = spr_source_frame(model, frame_index, subframe)
    bounds = frame.transparency_bounds
    if bounds is None:
        return BillboardSprite(
            1,
            1,
            frame.origin[0],
            frame.origin[1],
            (0,),
            1,
            1,
            model_id,
            frame_index,
            subframe,
        )
    minimum_x, minimum_y, maximum_x, maximum_y = bounds
    width = maximum_x - minimum_x + 1
    height = maximum_y - minimum_y + 1
    if width > 0xFF or height > 0xFF:
        raise ValueError("cropped IDSP raster escapes u8 sprite dimensions")
    pixels = tuple(
        0 if color == 255 else 0x100 | color
        for y in range(minimum_y, maximum_y + 1)
        for color in frame.pixels[
            y * frame.width + minimum_x : y * frame.width + maximum_x + 1
        ]
    )
    return BillboardSprite(
        width,
        height,
        frame.origin[0] + minimum_x,
        frame.origin[1] - minimum_y,
        pixels,
        width,
        height,
        model_id,
        frame_index,
        subframe,
    )


def _precache_kind(name: str) -> str:
    if name.startswith("*"):
        return "inline-bsp"
    if name.endswith(".bsp"):
        return "external-bsp"
    if name.endswith(".mdl"):
        return "mdl"
    if name.endswith(".spr"):
        return "spr"
    return "other"


def _spr_frame_metadata(frame: SprFrame) -> dict[str, object]:
    bounds = frame.transparency_bounds
    opaque_colors = sorted({color for color in frame.pixels if color != 255})
    return {
        "origin": list(frame.origin),
        "width": frame.width,
        "height": frame.height,
        "pixelBytes": len(frame.pixels),
        "pixelSha256": hashlib.sha256(frame.pixels).hexdigest(),
        "transparentIndex": 255,
        "hasTransparency": 255 in frame.pixels,
        "transparencyBounds": list(bounds) if bounds is not None else None,
        "croppedWidth": 0 if bounds is None else bounds[2] - bounds[0] + 1,
        "croppedHeight": 0 if bounds is None else bounds[3] - bounds[1] + 1,
        "croppedPixelBytes": 0
        if bounds is None
        else (bounds[2] - bounds[0] + 1) * (bounds[3] - bounds[1] + 1),
        "opaqueTexels": sum(color != 255 for color in frame.pixels),
        "opaquePaletteIndices": opaque_colors,
    }


def build_model_precache_inventory(
    read: Callable[[str], bytes],
    model_precache: tuple[str, ...],
    samples: Iterable[CameraEntitySample],
) -> tuple[dict[str, object], set[str]]:
    """Audit all precached model classes and every used/unused IDSP frame."""

    normalized = tuple(name.replace("\\", "/").lower() for name in model_precache)
    sprite_occurrences: dict[str, int] = defaultdict(int)
    sprite_entities: dict[str, set[int]] = defaultdict(set)
    sprite_frames: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for sample in samples:
        for state in sample.entities:
            if not 0 < state.model_index < len(sample.model_precache):
                continue
            name = sample.model_precache[state.model_index].replace("\\", "/").lower()
            if not name.endswith(".spr"):
                continue
            sprite_occurrences[name] += 1
            sprite_entities[name].add(state.entity_number)
            sprite_frames[name][state.frame] += 1

    sprite_entries: list[dict[str, object]] = []
    for precache_index, name in enumerate(normalized):
        if not name.endswith(".spr"):
            continue
        payload = read(name)
        model = parse_spr(payload)
        frames: list[dict[str, object]] = []
        for frame_index, top_frame in enumerate(model.frames):
            occurrence_count = sprite_frames[name].get(frame_index, 0)
            if isinstance(top_frame, SprGroup):
                frames.append(
                    {
                        "index": frame_index,
                        "type": "group",
                        "occurrenceCount": occurrence_count,
                        "intervals": list(top_frame.intervals),
                        "subframes": [
                            {"index": index, **_spr_frame_metadata(frame)}
                            for index, frame in enumerate(top_frame.frames)
                        ],
                    }
                )
            else:
                frames.append(
                    {
                        "index": frame_index,
                        "type": "single",
                        "occurrenceCount": occurrence_count,
                        **_spr_frame_metadata(top_frame),
                    }
                )
        occurrence_count = sprite_occurrences[name]
        sprite_entries.append(
            {
                "precacheIndex": precache_index,
                "pakEntry": name,
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "used": occurrence_count > 0,
                "shippingPayload": occurrence_count > 0,
                "occurrenceCount": occurrence_count,
                "entityIds": sorted(sprite_entities[name]),
                "frameRange": sorted(sprite_frames[name]),
                "orientationType": int(model.orientation),
                "orientation": ORIENTATION_NAMES[model.orientation],
                "maximumDimensions": [model.width, model.height],
                "boundingRadius": model.bounding_radius,
                "beamLength": model.beam_length,
                "syncType": model.sync_type,
                "frames": frames,
            }
        )
    used_names = {entry["pakEntry"] for entry in sprite_entries if entry["used"]}
    return (
        {
            "entries": [
                {"index": index, "name": name, "kind": _precache_kind(name)}
                for index, name in enumerate(normalized)
            ],
            "countsByKind": {
                kind: sum(_precache_kind(name) == kind for name in normalized)
                for kind in ("mdl", "spr", "external-bsp", "inline-bsp", "other")
            },
            "sprites": sprite_entries,
            "usedSpriteModels": sorted(used_names),
            "unusedSpriteModels": sorted(
                entry["pakEntry"] for entry in sprite_entries if not entry["used"]
            ),
            "usedSpriteOccurrences": sum(sprite_occurrences.values()),
        },
        set(used_names),
    )


def _edge(
    first: tuple[float, float],
    second: tuple[float, float],
    point: tuple[float, float],
) -> float:
    return (point[0] - first[0]) * (second[1] - first[1]) - (point[1] - first[1]) * (
        second[0] - first[0]
    )


def nearest_view(camera_origin: tuple[float, float, float], state: EntityState) -> int:
    """Quantize the camera bearing relative to an entity's yaw to 45 degrees."""

    bearing = math.degrees(
        math.atan2(
            camera_origin[1] - state.origin[1],
            camera_origin[0] - state.origin[0],
        )
    )
    relative = (bearing - state.angles[1]) % 360.0
    return int(math.floor(relative / 45.0 + 0.5)) & (VIEW_COUNT - 1)


def resolved_frame(model: quake_assets.MdlModel, frame: int) -> int:
    """Match Quake's invalid alias-frame fallback while retaining valid animation."""

    return frame if 0 <= frame < len(model.frames) else 0


def reduce_coverage_aware_raster(
    width: int,
    height: int,
    pixels: tuple[int, ...],
    world_units_per_texel: float,
) -> tuple[int, int, tuple[int, ...]]:
    """Reduce fixed world-unit blocks without dropping any opaque block."""

    if world_units_per_texel <= 0:
        raise ValueError("MDL world units per texel must be positive")
    if len(pixels) != width * height:
        raise ValueError("MDL raster dimensions disagree with its pixels")
    if world_units_per_texel == 1:
        return width, height, pixels
    density = _density_fraction(world_units_per_texel)
    output_width = _density_output_extent(width, density)
    output_height = _density_output_extent(height, density)
    reduced: list[int] = []
    for output_y in range(output_height):
        top, bottom = _density_block_bounds(output_y, height, density)
        for output_x in range(output_width):
            left, right = _density_block_bounds(output_x, width, density)
            counts: dict[int, int] = {}
            nearest: dict[int, int] = {}
            center_x2 = left + right
            center_y2 = top + bottom
            for source_y in range(top, bottom):
                for source_x in range(left, right):
                    pixel = pixels[source_y * width + source_x]
                    if not pixel & 0xFF00:
                        continue
                    counts[pixel] = counts.get(pixel, 0) + 1
                    distance = (2 * source_x + 1 - center_x2) ** 2 + (
                        2 * source_y + 1 - center_y2
                    ) ** 2
                    nearest[pixel] = min(distance, nearest.get(pixel, distance))
            reduced.append(
                0
                if not counts
                else min(counts, key=lambda pixel: (-counts[pixel], nearest[pixel], pixel))
            )
    return output_width, output_height, tuple(reduced)


def rasterize_billboard(
    model: quake_assets.MdlModel,
    *,
    frame_index: int = 0,
    view: int = 0,
    mdl_world_units_per_texel: float = 1,
    model_id: int = 0,
) -> BillboardSprite:
    """Rasterize one MDL pose once, then derive its configured storage raster."""

    if mdl_world_units_per_texel <= 0:
        raise ValueError("MDL world units per texel must be positive")
    frame_index = resolved_frame(model, frame_index)
    view &= VIEW_COUNT - 1
    frame = model.frames[frame_index]
    skin = model.skins[0]
    positions = quake_assets.decode_positions(model, frame)
    cosine, sine = MDL_VIEW_BASES[view]
    projected = tuple(
        (sine * position[0] - cosine * position[1], position[2])
        for position in positions
    )
    vertex_depths = tuple(
        cosine * position[0] + sine * position[1] for position in positions
    )
    minimum_x = math.floor(min(point[0] for point in projected))
    maximum_x = math.ceil(max(point[0] for point in projected))
    minimum_y = math.floor(min(point[1] for point in projected))
    maximum_y = math.ceil(max(point[1] for point in projected))
    world_width = maximum_x - minimum_x
    world_height = maximum_y - minimum_y
    if not 0 < world_width <= 0xFF or not 0 < world_height <= 0xFF:
        raise ValueError(
            f"MDL projected extent {world_width}x{world_height} escapes u8 dimensions"
        )
    if not -0x8000 <= minimum_x <= 0x7FFF or not -0x8000 <= maximum_y <= 0x7FFF:
        raise ValueError("MDL projected pivot escapes signed-word storage")

    depths = [-math.inf] * (world_width * world_height)
    pixels = [0] * (world_width * world_height)
    skin_width = model.header.skin_width
    skin_height = model.header.skin_height
    for triangle in model.triangles:
        indices = triangle.vertices
        points = tuple(projected[index] for index in indices)
        area = _edge(points[0], points[1], points[2])
        if abs(area) <= 1e-9:
            continue
        texture_coordinates: list[tuple[float, float]] = []
        for index in indices:
            st = model.st_vertices[index]
            s = st.s
            if not triangle.faces_front and st.on_seam:
                s += skin_width // 2
            texture_coordinates.append((float(s), float(st.t)))
        triangle_min_x = max(
            0,
            math.floor(min(p[0] for p in points) - minimum_x),
        )
        triangle_max_x = min(
            world_width - 1,
            math.ceil(max(p[0] for p in points) - minimum_x) - 1,
        )
        triangle_min_y = max(
            0,
            math.floor(min(p[1] for p in points) - minimum_y),
        )
        triangle_max_y = min(
            world_height - 1,
            math.ceil(max(p[1] for p in points) - minimum_y) - 1,
        )
        for source_y in range(triangle_min_y, triangle_max_y + 1):
            sample_y = minimum_y + source_y + 0.5
            output_y = world_height - 1 - source_y
            for source_x in range(triangle_min_x, triangle_max_x + 1):
                sample = (
                    minimum_x + source_x + 0.5,
                    sample_y,
                )
                weights = (
                    _edge(points[1], points[2], sample) / area,
                    _edge(points[2], points[0], sample) / area,
                    _edge(points[0], points[1], sample) / area,
                )
                if min(weights) < -1e-8:
                    continue
                depth = sum(
                    weights[vertex] * vertex_depths[indices[vertex]]
                    for vertex in range(3)
                )
                pixel = output_y * world_width + source_x
                if depth <= depths[pixel]:
                    continue
                s = sum(weights[i] * texture_coordinates[i][0] for i in range(3))
                t = sum(weights[i] * texture_coordinates[i][1] for i in range(3))
                texture_x = min(skin_width - 1, max(0, math.floor(s)))
                texture_y = min(skin_height - 1, max(0, math.floor(t)))
                depths[pixel] = depth
                pixels[pixel] = 0x0100 | skin[texture_y * skin_width + texture_x]
    if not any(pixel & 0xFF00 for pixel in pixels):
        raise ValueError("MDL front projection produced no covered texels")
    full_density_pixels = tuple(pixels)
    width, height, storage_pixels = reduce_coverage_aware_raster(
        world_width,
        world_height,
        full_density_pixels,
        mdl_world_units_per_texel,
    )
    return BillboardSprite(
        width,
        height,
        minimum_x,
        maximum_y,
        storage_pixels,
        world_width,
        world_height,
        model_id,
        frame_index,
        view,
        0 if mdl_world_units_per_texel == 1 else world_width,
        0 if mdl_world_units_per_texel == 1 else world_height,
        () if mdl_world_units_per_texel == 1 else full_density_pixels,
    )


def rasterize_front_billboard(model: quake_assets.MdlModel) -> BillboardSprite:
    """Compatibility helper for the original full-resolution front view."""

    return rasterize_billboard(model)


def rasterize_model_variants(
    task: tuple[quake_assets.MdlModel, int, float, tuple[tuple[int, int], ...]],
) -> tuple[BillboardSprite, ...]:
    """Rasterize one MDL's retained frame/view set in a worker process."""

    model, model_id, world_units_per_texel, variants = task
    return tuple(
        rasterize_billboard(
            model,
            frame_index=frame,
            view=view,
            mdl_world_units_per_texel=world_units_per_texel,
            model_id=model_id,
        )
        for frame, view in variants
    )
