"""Public Quake archive, MDL, transform, texture, and palette primitives."""

from __future__ import annotations

import io
import os
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, NamedTuple

from PIL import Image


STEAM_APP_ID = "2310"
PALETTE_ENTRY = "gfx/palette.lmp"
MDL_IDENT = b"IDPO"
MDL_VERSION = 6
DEFAULT_MODEL_RADIUS = 88
DEFAULT_TEXTURE_WIDTH = 64
DEFAULT_TEXTURE_HEIGHT = 64
DEFAULT_VISIBLE_COLORS = 15
DEFAULT_BACKGROUND_COLOR = (24, 24, 24)

__all__ = (
    "DEFAULT_BACKGROUND_COLOR",
    "DEFAULT_MODEL_RADIUS",
    "DEFAULT_TEXTURE_HEIGHT",
    "DEFAULT_TEXTURE_WIDTH",
    "DEFAULT_VISIBLE_COLORS",
    "Frame",
    "FormatError",
    "MdlHeader",
    "MdlModel",
    "ModelTransform",
    "PALETTE_ENTRY",
    "PackedVertex",
    "PakArchive",
    "RenderTriangle",
    "RenderMesh",
    "RenderVertex",
    "STEAM_APP_ID",
    "StVertex",
    "Triangle",
    "TextureConversion",
    "build_model_transform",
    "build_render_mesh",
    "convert_texture",
    "decode_positions",
    "locate_quake_pak",
    "orient_positions",
    "parse_mdl",
    "quake_image",
    "snes_bgr555",
    "transform_positions",
)


class FormatError(ValueError):
    """Raised when a Quake archive or asset is malformed."""


class BinaryReader:
    """Bounds-checked little-endian reader for Quake binary formats."""

    def __init__(self, data: bytes) -> None:
        self._stream = io.BytesIO(data)

    @property
    def offset(self) -> int:
        return self._stream.tell()

    def read(self, size: int) -> bytes:
        data = self._stream.read(size)
        if len(data) != size:
            raise FormatError(
                f"unexpected end of input at 0x{self.offset:08x}; "
                f"wanted {size} bytes"
            )
        return data

    def unpack(self, fmt: str) -> tuple[object, ...]:
        size = struct.calcsize(fmt)
        return struct.unpack(fmt, self.read(size))

    def i32(self) -> int:
        return self.unpack("<i")[0]  # type: ignore[return-value]

    def f32(self) -> float:
        return self.unpack("<f")[0]  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class PakEntry:
    offset: int
    size: int


class PakArchive:
    """Read named entries from a bounds-checked Quake PACK archive."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._entries: dict[str, PakEntry] = {}
        file_size = path.stat().st_size
        with path.open("rb") as stream:
            magic, directory_offset, directory_size = _unpack_stream(stream, "<4sii")
            if magic != b"PACK":
                raise FormatError(f"not a Quake PAK archive: {path}")
            if (
                directory_offset < 12
                or directory_size < 0
                or directory_size % 64
                or directory_offset + directory_size > file_size
            ):
                raise FormatError(f"invalid PAK directory in {path}")
            stream.seek(directory_offset)
            for _ in range(directory_size // 64):
                raw_name, offset, size = _unpack_stream(stream, "<56sii")
                name = raw_name.split(b"\0", 1)[0].decode("ascii").replace("\\", "/")
                if offset < 0 or size < 0 or offset + size > file_size:
                    raise FormatError(f"invalid PAK entry {name!r}")
                self._entries[name.lower()] = PakEntry(offset, size)

    def read(self, name: str) -> bytes:
        try:
            entry = self._entries[name.lower()]
        except KeyError as error:
            raise FormatError(f"{name!r} is missing from {self.path}") from error
        with self.path.open("rb") as stream:
            stream.seek(entry.offset)
            data = stream.read(entry.size)
        if len(data) != entry.size:
            raise FormatError(f"truncated PAK entry {name!r}")
        return data


@dataclass(frozen=True, slots=True)
class MdlHeader:
    scale: tuple[float, float, float]
    origin: tuple[float, float, float]
    skin_count: int
    skin_width: int
    skin_height: int
    vertex_count: int
    triangle_count: int
    frame_count: int
    flags: int = 0


@dataclass(frozen=True, slots=True)
class StVertex:
    on_seam: bool
    s: int
    t: int


@dataclass(frozen=True, slots=True)
class Triangle:
    faces_front: bool
    vertices: tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class PackedVertex:
    position: tuple[int, int, int]
    normal_index: int


@dataclass(frozen=True, slots=True)
class Frame:
    name: str
    vertices: tuple[PackedVertex, ...]


@dataclass(frozen=True, slots=True)
class MdlModel:
    header: MdlHeader
    skins: tuple[bytes, ...]
    st_vertices: tuple[StVertex, ...]
    triangles: tuple[Triangle, ...]
    frames: tuple[Frame, ...]


@dataclass(frozen=True, slots=True)
class RenderVertex:
    position: tuple[int, int, int]
    uv: tuple[int, int]
    source_vertex: int
    on_seam: bool


@dataclass(frozen=True, slots=True)
class RenderTriangle:
    vertices: tuple[int, int, int]
    faces_front: bool


class RenderMesh(NamedTuple):
    vertices: tuple[RenderVertex, ...]
    triangles: tuple[RenderTriangle, ...]


class TextureConversion(NamedTuple):
    indices: bytes
    colors: tuple[tuple[int, int, int], ...]
    preview: Image.Image


@dataclass(frozen=True, slots=True)
class ModelTransform:
    center: tuple[float, float, float]
    scale: float


def _unpack_stream(stream: BinaryIO, fmt: str) -> tuple[object, ...]:
    size = struct.calcsize(fmt)
    data = stream.read(size)
    if len(data) != size:
        raise FormatError("unexpected end of file")
    return struct.unpack(fmt, data)


def _parse_keyvalues(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8-sig", errors="strict")
    tokens: list[str] = []
    index = 0
    while index < len(text):
        if text[index].isspace():
            index += 1
            continue
        if text.startswith("//", index):
            newline = text.find("\n", index)
            index = len(text) if newline < 0 else newline + 1
            continue
        if text[index] in "{}":
            tokens.append(text[index])
            index += 1
            continue
        if text[index] != '"':
            raise FormatError(
                f"invalid KeyValues token in {path} at character {index}"
            )
        index += 1
        value: list[str] = []
        while index < len(text) and text[index] != '"':
            if text[index] == "\\" and index + 1 < len(text):
                escaped = text[index + 1]
                if escaped in ('"', "\\"):
                    value.append(escaped)
                    index += 2
                    continue
            value.append(text[index])
            index += 1
        if index >= len(text):
            raise FormatError(f"unterminated KeyValues string in {path}")
        tokens.append("".join(value))
        index += 1

    def parse_object(position: int, nested: bool) -> tuple[dict[str, object], int]:
        result: dict[str, object] = {}
        while position < len(tokens):
            if tokens[position] == "}":
                if not nested:
                    raise FormatError(f"unexpected closing brace in {path}")
                return result, position + 1
            key = tokens[position]
            position += 1
            if position >= len(tokens):
                raise FormatError(f"missing value for {key!r} in {path}")
            if tokens[position] == "{":
                value, position = parse_object(position + 1, True)
            elif tokens[position] == "}":
                raise FormatError(f"missing value for {key!r} in {path}")
            else:
                value = tokens[position]
                position += 1
            result[key] = value
        if nested:
            raise FormatError(f"unterminated object in {path}")
        return result, position

    parsed, final_position = parse_object(0, False)
    if final_position != len(tokens):
        raise FormatError(f"trailing KeyValues data in {path}")
    return parsed


def _steam_root() -> Path | None:
    if os.name != "nt":
        return None
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            return Path(winreg.QueryValueEx(key, "SteamPath")[0])
    except OSError:
        return None


def locate_quake_pak() -> Path:
    """Locate Quake's installed PAK0.PAK in configured Steam libraries."""

    steam = _steam_root()
    if steam is None:
        raise FileNotFoundError("Steam was not found; pass --pak explicitly")
    library_file = steam / "steamapps" / "libraryfolders.vdf"
    libraries = [steam]
    if library_file.is_file():
        root = _parse_keyvalues(library_file).get("libraryfolders")
        if isinstance(root, dict):
            for value in root.values():
                if isinstance(value, dict) and isinstance(value.get("path"), str):
                    candidate = Path(value["path"])
                    if candidate not in libraries:
                        libraries.append(candidate)

    for library in libraries:
        manifest = library / "steamapps" / f"appmanifest_{STEAM_APP_ID}.acf"
        if not manifest.is_file():
            continue
        state = _parse_keyvalues(manifest).get("AppState")
        if not isinstance(state, dict) or not isinstance(
            state.get("installdir"), str
        ):
            continue
        install = library / "steamapps" / "common" / state["installdir"]
        for candidate in (
            install / "id1" / "PAK0.PAK",
            install / "id1" / "pak0.pak",
        ):
            if candidate.is_file():
                return candidate
    raise FileNotFoundError(
        "Quake PAK0.PAK was not found in the configured Steam libraries"
    )


def _read_packed_vertex(reader: BinaryReader) -> PackedVertex:
    x, y, z, normal = reader.unpack("<4B")
    return PackedVertex((x, y, z), normal)


def _read_simple_frame(reader: BinaryReader, vertex_count: int) -> Frame:
    _read_packed_vertex(reader)
    _read_packed_vertex(reader)
    raw_name = reader.read(16)
    name = raw_name.split(b"\0", 1)[0].decode("ascii", errors="replace")
    vertices = tuple(_read_packed_vertex(reader) for _ in range(vertex_count))
    return Frame(name, vertices)


def parse_mdl(data: bytes) -> MdlModel:
    """Parse a Quake alias-model (MDL version 6) byte stream."""

    reader = BinaryReader(data)
    ident, version = reader.unpack("<4si")
    if ident != MDL_IDENT or version != MDL_VERSION:
        raise FormatError(f"unsupported MDL signature/version: {ident!r}/{version}")
    scale = reader.unpack("<3f")
    origin = reader.unpack("<3f")
    reader.f32()
    reader.unpack("<3f")
    counts = reader.unpack("<8i")
    reader.f32()
    skin_count, skin_width, skin_height, vertex_count, triangle_count, frame_count = (
        counts[:6]
    )
    if min(
        skin_count,
        skin_width,
        skin_height,
        vertex_count,
        triangle_count,
        frame_count,
    ) <= 0:
        raise FormatError("MDL header contains an invalid non-positive count")
    if skin_width * skin_height > 16 * 1024 * 1024:
        raise FormatError("MDL skin is unreasonably large")
    header = MdlHeader(
        scale=scale,  # type: ignore[arg-type]
        origin=origin,  # type: ignore[arg-type]
        skin_count=skin_count,
        skin_width=skin_width,
        skin_height=skin_height,
        vertex_count=vertex_count,
        triangle_count=triangle_count,
        frame_count=frame_count,
        flags=counts[7],
    )

    skin_bytes = skin_width * skin_height
    skins: list[bytes] = []
    for _ in range(skin_count):
        group = reader.i32()
        if group == 0:
            skins.append(reader.read(skin_bytes))
        elif group == 1:
            group_count = reader.i32()
            if group_count <= 0:
                raise FormatError("MDL skin group is empty")
            for _ in range(group_count):
                reader.f32()
            skins.extend(reader.read(skin_bytes) for _ in range(group_count))
        else:
            raise FormatError(f"unsupported MDL skin group type {group}")

    st_vertices = tuple(
        StVertex(bool(on_seam), s, t)
        for on_seam, s, t in (reader.unpack("<3i") for _ in range(vertex_count))
    )
    triangles = tuple(
        Triangle(bool(front), (v0, v1, v2))
        for front, v0, v1, v2 in (
            reader.unpack("<4i") for _ in range(triangle_count)
        )
    )
    for triangle in triangles:
        if any(index < 0 or index >= vertex_count for index in triangle.vertices):
            raise FormatError(f"MDL triangle has an invalid vertex index: {triangle}")

    frames: list[Frame] = []
    for _ in range(frame_count):
        group = reader.i32()
        if group == 0:
            frames.append(_read_simple_frame(reader, vertex_count))
        elif group == 1:
            group_count = reader.i32()
            if group_count <= 0:
                raise FormatError("MDL frame group is empty")
            _read_packed_vertex(reader)
            _read_packed_vertex(reader)
            for _ in range(group_count):
                reader.f32()
            frames.extend(
                _read_simple_frame(reader, vertex_count)
                for _ in range(group_count)
            )
        else:
            raise FormatError(f"unsupported MDL frame group type {group}")

    return MdlModel(header, tuple(skins), st_vertices, triangles, tuple(frames))


def decode_positions(
    model: MdlModel, frame: Frame
) -> tuple[tuple[float, float, float], ...]:
    """Decode packed MDL vertices into Quake world-space positions."""

    return tuple(
        tuple(
            packed.position[axis] * model.header.scale[axis]
            + model.header.origin[axis]
            for axis in range(3)
        )
        for packed in frame.vertices
    )  # type: ignore[return-value]


def orient_positions(
    model: MdlModel, frame: Frame
) -> tuple[tuple[float, float, float], ...]:
    """Convert Quake Z-up positions to the samples' X-right/Y-down/Z-depth axes."""

    return tuple((y, -z, x) for x, y, z in decode_positions(model, frame))


def build_model_transform(
    model: MdlModel, target_radius: int = DEFAULT_MODEL_RADIUS
) -> ModelTransform:
    """Build one centered scale shared by every animation frame."""

    if target_radius <= 0:
        raise ValueError("target radius must be positive")
    oriented_frames = tuple(orient_positions(model, frame) for frame in model.frames)
    bounds = tuple(
        (
            min(vertex[axis] for frame in oriented_frames for vertex in frame),
            max(vertex[axis] for frame in oriented_frames for vertex in frame),
        )
        for axis in range(3)
    )
    center = tuple((low + high) / 2.0 for low, high in bounds)
    maximum = max(
        abs(vertex[axis] - center[axis])
        for frame in oriented_frames
        for vertex in frame
        for axis in range(3)
    )
    if maximum == 0:
        raise FormatError("MDL animation has no spatial extent")
    return ModelTransform(center, target_radius / maximum)


def transform_positions(
    model: MdlModel, frame: Frame, transform: ModelTransform
) -> tuple[tuple[int, int, int], ...]:
    """Apply a model transform and return immutable signed-byte positions."""

    positions = tuple(
        tuple(
            round((vertex[axis] - transform.center[axis]) * transform.scale)
            for axis in range(3)
        )
        for vertex in orient_positions(model, frame)
    )
    if any(
        component < -127 or component > 127
        for vertex in positions
        for component in vertex
    ):
        raise FormatError(f"frame {frame.name!r} escapes signed-byte model coordinates")
    return positions  # type: ignore[return-value]


def build_render_mesh(
    model: MdlModel,
    frame: Frame,
    transform: ModelTransform,
    texture_width: int = DEFAULT_TEXTURE_WIDTH,
    texture_height: int = DEFAULT_TEXTURE_HEIGHT,
) -> RenderMesh:
    """Build immutable seam-aware render vertices and oriented triangles."""

    if texture_width <= 0 or texture_height <= 0:
        raise ValueError("texture dimensions must be positive")
    positions = transform_positions(model, frame, transform)
    vertices = tuple(
        RenderVertex(
            position,
            (
                max(
                    0,
                    min(
                        texture_width - 1,
                        round(
                            st.s
                            * (texture_width - 1)
                            / (model.header.skin_width - 1)
                        ),
                    ),
                ),
                max(
                    0,
                    min(
                        texture_height - 1,
                        round(
                            st.t
                            * (texture_height - 1)
                            / (model.header.skin_height - 1)
                        ),
                    ),
                ),
            ),
            source_index,
            st.on_seam,
        )
        for source_index, (position, st) in enumerate(
            zip(positions, model.st_vertices, strict=True)
        )
    )
    if len(vertices) > 256:
        raise FormatError(f"model has {len(vertices)} vertices; byte indices support 256")
    triangles = tuple(
        RenderTriangle(
            (triangle.vertices[0], triangle.vertices[2], triangle.vertices[1]),
            triangle.faces_front,
        )
        for triangle in model.triangles
    )
    if any(len(set(triangle.vertices)) != 3 for triangle in triangles):
        raise FormatError("MDL contains a degenerate triangle")
    return RenderMesh(vertices, triangles)


def quake_image(
    indices: bytes, width: int, height: int, palette: bytes
) -> Image.Image:
    """Convert Quake indexed pixels and its 256-color palette to RGB."""

    if len(palette) != 256 * 3:
        raise FormatError(f"Quake palette must contain 768 bytes, got {len(palette)}")
    if len(indices) != width * height:
        raise FormatError(
            f"indexed image has {len(indices)} pixels; expected {width * height}"
        )
    colors = tuple(
        tuple(palette[index : index + 3]) for index in range(0, len(palette), 3)
    )
    image = Image.new("RGB", (width, height))
    image.putdata([colors[index] for index in indices])
    return image


def convert_texture(
    source: Image.Image,
    width: int = DEFAULT_TEXTURE_WIDTH,
    height: int = DEFAULT_TEXTURE_HEIGHT,
    visible_colors: int = DEFAULT_VISIBLE_COLORS,
    background: tuple[int, int, int] = DEFAULT_BACKGROUND_COLOR,
) -> TextureConversion:
    """Resize and quantize an RGB source into an indexed SNES texture."""

    if width <= 0 or height <= 0 or not 1 <= visible_colors < 256:
        raise ValueError("invalid texture dimensions or visible-color count")
    resized = source.resize((width, height), Image.Resampling.LANCZOS)
    quantized = resized.quantize(
        colors=visible_colors,
        method=Image.Quantize.MEDIANCUT,
        dither=Image.Dither.NONE,
    )
    raw_palette = quantized.getpalette()
    if raw_palette is None:
        raise FormatError("Pillow did not return an indexed texture palette")
    colors = (background,) + tuple(
        tuple(raw_palette[index : index + 3])
        for index in range(0, visible_colors * 3, 3)
    )
    indices = bytes(index + 1 for index in quantized.getdata())
    preview = Image.new("P", (width, height))
    preview_palette = [component for color in colors for component in color]
    preview.putpalette(preview_palette + [0] * (768 - len(preview_palette)))
    preview.putdata(indices)
    return TextureConversion(indices, colors, preview)


def snes_bgr555(color: tuple[int, int, int]) -> int:
    """Convert one 8-bit RGB color to the SNES BGR555 word layout."""

    red, green, blue = color
    return (red >> 3) | ((green >> 3) << 5) | ((blue >> 3) << 10)
