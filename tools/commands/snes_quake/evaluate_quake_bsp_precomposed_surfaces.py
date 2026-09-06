#!/usr/bin/env python3
"""Measure whether E1M3 texture/lightmap surface caches fit in the ROM.

The experiment reproduces technique 4's current packed sampling contract at
one final palette index per reachable integer texture coordinate. It then
measures whole-surface reuse and native 8x8 tile reuse with exact, mirror, and
full dihedral (rotation plus mirror) canonicalization.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

from workspace_paths import workspace_root
from typing import Any, Iterable, Sequence

import numpy as np

import quake_bsp_assets as bsp_assets


WORKSPACE = workspace_root(__file__)
DEFAULT_DATA_DIR = WORKSPACE / "src/snes_quake/Data"
DEFAULT_ROM = WORKSPACE / "out/snes_quake/quake.sfc"
DEFAULT_DEBUG_INFO = WORKSPACE / "out/snes_quake/quake.dnfo"
DEFAULT_OUTPUT = Path("precomposed-surfaces.json")

FACE_RECORD = struct.Struct("<HBBBB")
TEXTURE_RECORD = struct.Struct("<BHHHB")
LIGHTMAP_RECORD = struct.Struct("<BHBBbb")
TEXTURE_COORDINATE_RECORD = struct.Struct("<hh")
ROM_BANK_BYTES = 32 * 1024
TILE_SIZE = 8
SURFACE_DIRECTORY_BYTES = 11
TILE_DIRECTORY_BYTES = 9
PROFILE_IGNORED_TEXTURE_FLAGS = bsp_assets.TEXTURE_FLAG_TURBULENT


class EvaluationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Texture:
    name: str
    width: int
    height: int
    pixels: bytes


@dataclass(frozen=True)
class Lightmap:
    bank: int
    address: int
    width: int
    height: int
    minimum_s: int
    minimum_t: int
    samples: bytes | None


@dataclass(frozen=True)
class Assets:
    faces: tuple[tuple[int, int], ...]
    face_texture_ids: bytes
    face_texture_coordinates: tuple[tuple[int, int], ...]
    textures: tuple[Texture, ...]
    lightmaps: tuple[Lightmap, ...]
    colormap: np.ndarray
    input_sha256: str


@dataclass(frozen=True)
class Surface:
    face: int
    width: int
    height: int
    pixels: bytes


def _read(path: Path, digest: hashlib._Hash | None = None) -> bytes:
    payload = path.read_bytes()
    if digest is not None:
        _update_digest(path, payload, digest)
    return payload


def _update_digest(path: Path, payload: bytes, digest: hashlib._Hash) -> None:
    digest.update(path.name.encode("utf-8"))
    digest.update(struct.pack("<I", len(payload)))
    digest.update(payload)


def surface_profile_texture_directory_payload(payload: bytes) -> bytes:
    """Remove runtime-only texture flags from the composed-cache identity."""

    if len(payload) % TEXTURE_RECORD.size:
        raise EvaluationError("world texture directory is not record aligned")
    normalized = bytearray(payload)
    flags_offset = TEXTURE_RECORD.size - 1
    for offset in range(0, len(normalized), TEXTURE_RECORD.size):
        normalized[offset + flags_offset] &= ~PROFILE_IGNORED_TEXTURE_FLAGS
    return bytes(normalized)


def surface_asset_metadata_payload(metadata: dict[str, Any]) -> bytes:
    """Fingerprint only metadata that defines composed-surface interpretation."""

    source = metadata["source"]
    exact_textures = dict(metadata["world"]["packing"]["exact_textures"])
    # Stream bytes already bind any inserted padding. Keep descriptive packing
    # diagnostics out of the profile identity so metadata-only additions do not
    # invalidate a byte-identical owner-pixel corpus.
    exact_textures.pop("face_boundary_padding_records", None)
    exact_textures.pop("face_boundary_policy", None)
    # These descriptors existed only for the retired visible depth renderers.
    # Composed surfaces use the natural texture and lightmap payloads directly,
    # so deleting the compatibility LUTs must not invalidate owner profiles.
    exact_textures.pop("depth_shading", None)
    if "lightmaps" in exact_textures:
        lightmaps = dict(exact_textures["lightmaps"])
        for key in (
            "colormap_map_file",
            "colormap_map_min_exact_level",
            "colormap_map_role",
            "colormap_min_exact_level",
        ):
            lightmaps.pop(key, None)
        exact_textures["lightmaps"] = lightmaps
    if "directory_flag_bits" in exact_textures:
        flag_bits = dict(exact_textures["directory_flag_bits"])
        flag_bits.pop("turbulent", None)
        exact_textures["directory_flag_bits"] = flag_bits
    if "textures" in exact_textures:
        texture_records = []
        for source_record in exact_textures["textures"]:
            record = dict(source_record)
            if "directory_flags" in record:
                record["directory_flags"] = (
                    int(record["directory_flags"])
                    & ~PROFILE_IGNORED_TEXTURE_FLAGS
                )
            texture_records.append(record)
        exact_textures["textures"] = texture_records
    stable = {
        "schema": "quake-bsp-composed-surface-input-v1",
        "source": {
            key: source[key]
            for key in (
                "bsp_sha256",
                "colormap_sha256",
                "lighting_sha256",
                "pak_entry",
            )
        },
        "exactTextures": exact_textures,
    }
    return json.dumps(stable, sort_keys=True, separators=(",", ":")).encode("ascii")


def _bank_payloads(
    data_dir: Path,
    records: Sequence[dict[str, object]],
    digest: hashlib._Hash,
) -> dict[int, bytes]:
    payloads: dict[int, bytes] = {}
    for record in records:
        bank = int(record["gsu_rom_bank"])
        name = str(record["file"])
        if bank in payloads:
            raise EvaluationError(f"duplicate packed bank {bank}")
        payloads[bank] = _read(data_dir / name, digest)
    return payloads


def _read_banked(
    banks: dict[int, bytes],
    bank: int,
    address: int,
    size: int,
) -> bytes:
    if bank not in banks or address < 0x8000:
        raise EvaluationError(f"invalid packed address {bank:02x}:{address:04x}")
    output = bytearray()
    cursor_bank = bank
    cursor = address - 0x8000
    remaining = size
    while remaining:
        payload = banks.get(cursor_bank)
        if payload is None or cursor > len(payload):
            raise EvaluationError("packed payload escapes its ROM banks")
        take = min(remaining, len(payload) - cursor)
        if take == 0:
            raise EvaluationError("packed payload crosses an unfilled bank tail")
        output.extend(payload[cursor : cursor + take])
        remaining -= take
        cursor_bank += 1
        cursor = 0
    return bytes(output)


def _decode_lightmap_directory(data: bytes) -> tuple[tuple[int, ...], ...]:
    if len(data) % LIGHTMAP_RECORD.size:
        raise EvaluationError("lightmap directory is not record aligned")
    records = tuple(LIGHTMAP_RECORD.iter_unpack(data))
    for bank, address, *_rest in records:
        if bank == 0xFF and address not in (0x00C0, 0x00FF):
            raise EvaluationError(
                "missing-lightmap marker has an invalid encoded level"
            )
    return records


def load_assets(data_dir: Path = DEFAULT_DATA_DIR) -> Assets:
    digest = hashlib.sha256()
    metadata_bytes = _read(data_dir / "QuakeBSPMetadata.json")
    metadata = json.loads(metadata_bytes)
    metadata_payload = surface_asset_metadata_payload(metadata)
    digest.update(struct.pack("<I", len(metadata_payload)))
    digest.update(metadata_payload)
    packing = metadata["world"]["packing"]["exact_textures"]
    lightmap_metadata = packing["lightmaps"]

    face_bytes = _read(data_dir / "QuakeBSPWorldFaces.bin", digest)
    face_texture_ids = _read(data_dir / "QuakeBSPWorldFaceTextureIds.bin", digest)
    coordinate_bytes = b"".join(
        _read(data_dir / f"QuakeBSPWorldTextureCoordinates{index}.bin", digest)
        for index in range(3)
    )
    texture_directory_path = data_dir / "QuakeBSPWorldTextureDirectory.bin"
    texture_directory = _read(texture_directory_path)
    _update_digest(
        texture_directory_path,
        surface_profile_texture_directory_payload(texture_directory),
        digest,
    )
    lightmap_directory = _read(data_dir / "QuakeBSPWorldLightmapDirectory.bin", digest)
    colormap_bytes = _read(data_dir / "QuakeBSPLightmapColormap.bin", digest)

    if len(face_bytes) % FACE_RECORD.size:
        raise EvaluationError("world-face asset is not record aligned")
    if len(texture_directory) % TEXTURE_RECORD.size:
        raise EvaluationError("texture directory is not record aligned")
    if len(coordinate_bytes) % TEXTURE_COORDINATE_RECORD.size:
        raise EvaluationError("texture-coordinate asset is not record aligned")

    face_records = tuple(FACE_RECORD.iter_unpack(face_bytes))
    if len(face_texture_ids) != len(face_records):
        raise EvaluationError("face texture IDs lost face identity")
    faces = tuple((record[0], record[1]) for record in face_records)
    coordinates = tuple(TEXTURE_COORDINATE_RECORD.iter_unpack(coordinate_bytes))
    if any(first + count > len(coordinates) for first, count in faces):
        raise EvaluationError("world face escapes texture coordinates")

    texture_banks = _bank_payloads(data_dir, packing["pixel_chunks"], digest)
    texture_names = {
        int(record["packed_id"]): str(record["name"]) for record in packing["textures"]
    }
    textures: list[Texture] = []
    for packed_id, record in enumerate(TEXTURE_RECORD.iter_unpack(texture_directory)):
        bank, address, width, height, _flags = record
        pixels = _read_banked(texture_banks, bank, address, int(width) * int(height))
        try:
            name = texture_names[packed_id]
        except KeyError as error:
            raise EvaluationError("texture metadata lost packed identity") from error
        textures.append(Texture(name, width, height, pixels))

    lightmap_banks = _bank_payloads(
        data_dir, lightmap_metadata["sample_chunks"], digest
    )
    lightmaps: list[Lightmap] = []
    for (
        encoded_bank,
        address,
        width,
        height,
        minimum_s,
        minimum_t,
    ) in _decode_lightmap_directory(lightmap_directory):
        samples = None
        bank = encoded_bank
        if encoded_bank != 0xFF:
            if width < 2 or height < 2:
                raise EvaluationError("lightmapped face has a degenerate grid")
            phase = encoded_bank >> bsp_assets.LIGHTMAP_PHASE_SHIFT
            bank = encoded_bank & bsp_assets.LIGHTMAP_BANK_MASK
            try:
                sample_offset = bsp_assets.lightmap_location_sample_offset(
                    address, phase
                )
                samples = bsp_assets.unpack_six_bit_samples(
                    lightmap_banks[bank],
                    sample_offset,
                    int(width) * int(height),
                )
            except (KeyError, ValueError) as error:
                raise EvaluationError(
                    f"invalid packed lightmap {bank:02x}:{address:04x}/{phase}"
                ) from error
        lightmaps.append(
            Lightmap(
                bank,
                address,
                width,
                height,
                int(minimum_s) * 16,
                int(minimum_t) * 16,
                samples,
            )
        )
    if len(lightmaps) != len(faces):
        raise EvaluationError("lightmap directory lost face identity")

    if len(colormap_bytes) != 64 * 256:
        raise EvaluationError("natural lightmap colormap must contain 64 rows")
    natural_rows = np.frombuffer(colormap_bytes, dtype=np.uint8).reshape(64, 256)

    return Assets(
        faces,
        face_texture_ids,
        coordinates,
        tuple(textures),
        tuple(lightmaps),
        natural_rows,
        digest.hexdigest(),
    )


def _lightmap_levels(
    lightmap: Lightmap,
    s_coordinates: np.ndarray,
    t_coordinates: np.ndarray,
) -> np.ndarray:
    if lightmap.samples is None:
        raise EvaluationError("cannot compose an unlightmapped face")
    samples = np.frombuffer(lightmap.samples, dtype=np.uint8).reshape(
        lightmap.height, lightmap.width
    )

    def axis(
        coordinates: np.ndarray, minimum: int, extent: int
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        relative = np.floor_divide(coordinates, 16) - minimum // 16
        fraction = np.mod(coordinates, 16).astype(np.uint16)
        below = relative < 0
        above = relative >= extent - 1
        first = np.clip(relative, 0, extent - 1).astype(np.intp)
        fraction[below | above] = 0
        second = first + (fraction != 0)
        return first, second, fraction

    x0, x1, fraction_x = axis(s_coordinates, lightmap.minimum_s, lightmap.width)
    y0, y1, fraction_y = axis(t_coordinates, lightmap.minimum_t, lightmap.height)
    sample_values = samples.astype(np.uint16)
    upper_rows = (
        sample_values[:, x0] * (16 - fraction_x) + sample_values[:, x1] * fraction_x + 8
    ) >> 4
    levels = (
        upper_rows[y0] * (16 - fraction_y[:, None])
        + upper_rows[y1] * fraction_y[:, None]
        + 8
    ) >> 4
    return levels.astype(np.uint8)


def compose_surface(
    texture: Texture,
    lightmap: Lightmap,
    colormap: np.ndarray,
    minimum_s: int,
    maximum_s: int,
    minimum_t: int,
    maximum_t: int,
) -> bytes:
    s_coordinates = np.arange(minimum_s, maximum_s + 1, dtype=np.int32)
    t_coordinates = np.arange(minimum_t, maximum_t + 1, dtype=np.int32)
    levels = _lightmap_levels(lightmap, s_coordinates, t_coordinates)
    texture_pixels = np.frombuffer(texture.pixels, dtype=np.uint8).reshape(
        texture.height, texture.width
    )
    texels = texture_pixels[
        np.mod(t_coordinates, texture.height)[:, None],
        np.mod(s_coordinates, texture.width)[None, :],
    ]
    return np.ascontiguousarray(colormap[levels, texels]).tobytes()


def build_surfaces(assets: Assets) -> tuple[list[Surface], dict[str, object]]:
    surfaces: list[Surface] = []
    composition_digest = hashlib.sha256()
    lightmap_extent_bytes = 0
    categories = {
        "drawableLightmapped": 0,
        "drawableUnlightmapped": 0,
        "nondrawableLightmapped": 0,
        "nondrawableUnlightmapped": 0,
        "animatedTexture": 0,
        "specialTexture": 0,
    }
    special_names: set[str] = set()

    for face, ((first, count), texture_id, lightmap) in enumerate(
        zip(
            assets.faces,
            assets.face_texture_ids,
            assets.lightmaps,
            strict=True,
        )
    ):
        drawable = count != 0 and texture_id != 0xFF
        lightmapped = lightmap.samples is not None
        categories[
            ("drawable" if drawable else "nondrawable")
            + ("Lightmapped" if lightmapped else "Unlightmapped")
        ] += 1
        if not drawable:
            continue
        texture = assets.textures[texture_id]
        if texture.name.startswith("+"):
            categories["animatedTexture"] += 1
        if texture.name.startswith("*") or texture.name.lower().startswith("sky"):
            categories["specialTexture"] += 1
            special_names.add(texture.name)
            # Animated special materials must reach their command-time sampler;
            # a camera-independent precomposed texel cache would freeze them.
            continue
        if not lightmapped:
            continue

        coordinates = assets.face_texture_coordinates[first : first + count]
        minimum_s = min(value[0] >> 4 for value in coordinates)
        maximum_s = max(value[0] >> 4 for value in coordinates)
        minimum_t = min(value[1] >> 4 for value in coordinates)
        maximum_t = max(value[1] >> 4 for value in coordinates)
        width = maximum_s - minimum_s + 1
        height = maximum_t - minimum_t + 1
        pixels = compose_surface(
            texture,
            lightmap,
            assets.colormap,
            minimum_s,
            maximum_s,
            minimum_t,
            maximum_t,
        )
        if len(pixels) != width * height:
            raise AssertionError("composed surface has the wrong dimensions")
        surfaces.append(Surface(face, width, height, pixels))
        lightmap_extent_bytes += (lightmap.width - 1) * 16 * (lightmap.height - 1) * 16
        composition_digest.update(struct.pack("<HHH", face, width, height))
        composition_digest.update(pixels)

    categories["specialTextureNames"] = sorted(special_names)
    return surfaces, {
        "categories": categories,
        "lightmapExtentBytes": lightmap_extent_bytes,
        "reachableCropBytes": sum(len(surface.pixels) for surface in surfaces),
        "compositionSha256": composition_digest.hexdigest(),
    }


def _surface_transforms(surface: Surface, mode: str) -> Iterable[np.ndarray]:
    array = np.frombuffer(surface.pixels, dtype=np.uint8).reshape(
        surface.height, surface.width
    )
    yield array
    if mode == "exact":
        return
    yield array[:, ::-1]
    yield array[::-1, :]
    yield array[::-1, ::-1]
    if mode == "mirrors":
        return
    transposed = array.T
    yield transposed
    yield transposed[:, ::-1]
    yield transposed[::-1, :]
    yield transposed[::-1, ::-1]


def measure_surface_reuse(
    surfaces: Sequence[Surface], world_face_count: int, mode: str
) -> dict[str, int | str]:
    unique: dict[tuple[int, int, bytes], int] = {}
    for surface in surfaces:
        keys = [
            (candidate.shape[1], candidate.shape[0], candidate.tobytes())
            for candidate in _surface_transforms(surface, mode)
        ]
        key = min(keys)
        unique.setdefault(key, len(key[2]))
    payload_bytes = sum(unique.values())
    directory_bytes = world_face_count * SURFACE_DIRECTORY_BYTES
    return {
        "canonicalization": mode,
        "uniqueSurfaces": len(unique),
        "surfaceBytes": payload_bytes,
        "directoryBytes": directory_bytes,
        "totalBytes": payload_bytes + directory_bytes,
    }


def collect_tiles(surfaces: Sequence[Surface]) -> tuple[np.ndarray, int]:
    chunks: list[np.ndarray] = []
    padding_bytes = 0
    for surface in surfaces:
        array = np.frombuffer(surface.pixels, dtype=np.uint8).reshape(
            surface.height, surface.width
        )
        padded_height = math.ceil(surface.height / TILE_SIZE) * TILE_SIZE
        padded_width = math.ceil(surface.width / TILE_SIZE) * TILE_SIZE
        if padded_height != surface.height or padded_width != surface.width:
            padded = np.zeros((padded_height, padded_width), dtype=np.uint8)
            padded[: surface.height, : surface.width] = array
            array = padded
        padding_bytes += array.size - len(surface.pixels)
        chunks.append(
            array.reshape(
                array.shape[0] // TILE_SIZE,
                TILE_SIZE,
                array.shape[1] // TILE_SIZE,
                TILE_SIZE,
            )
            .transpose(0, 2, 1, 3)
            .reshape(-1, TILE_SIZE * TILE_SIZE)
        )
    return np.concatenate(chunks), padding_bytes


def _lexicographic_minimum(best: np.ndarray, candidate: np.ndarray) -> np.ndarray:
    best_words = best.view(">u8").reshape(best.shape[0], -1)
    candidate_words = candidate.view(">u8").reshape(candidate.shape[0], -1)
    undecided = np.ones(best.shape[0], dtype=np.bool_)
    take = np.zeros(best.shape[0], dtype=np.bool_)
    for column in range(best_words.shape[1]):
        less = candidate_words[:, column] < best_words[:, column]
        greater = candidate_words[:, column] > best_words[:, column]
        take |= undecided & less
        undecided &= ~(less | greater)
    best[take] = candidate[take]
    return best


def canonicalize_tiles(tiles: np.ndarray, mode: str) -> np.ndarray:
    shaped = tiles.reshape(-1, TILE_SIZE, TILE_SIZE)
    transforms = [shaped]
    if mode != "exact":
        transforms.extend(
            (shaped[:, :, ::-1], shaped[:, ::-1, :], shaped[:, ::-1, ::-1])
        )
    if mode == "dihedral":
        transposed = shaped.transpose(0, 2, 1)
        transforms.extend(
            (
                transposed,
                transposed[:, :, ::-1],
                transposed[:, ::-1, :],
                transposed[:, ::-1, ::-1],
            )
        )
    best = np.ascontiguousarray(transforms[0].reshape(-1, TILE_SIZE * TILE_SIZE)).copy()
    for transform in transforms[1:]:
        candidate = np.ascontiguousarray(transform.reshape(-1, TILE_SIZE * TILE_SIZE))
        best = _lexicographic_minimum(best, candidate)
    return best


def measure_tile_reuse(
    tiles: np.ndarray,
    world_face_count: int,
    padding_bytes: int,
    mode: str,
) -> dict[str, int | str]:
    transform_bits = {"exact": 0, "mirrors": 2, "dihedral": 3}[mode]
    canonical = canonicalize_tiles(tiles, mode)
    unique_tiles = int(np.unique(canonical, axis=0).shape[0])
    identifier_bits = max(1, (unique_tiles - 1).bit_length())
    reference_bits = identifier_bits + transform_bits
    references = int(tiles.shape[0])
    packed_reference_bytes = math.ceil(references * reference_bits / 8)
    aligned_reference_size = math.ceil(reference_bits / 8)
    aligned_reference_bytes = references * aligned_reference_size
    dictionary_bytes = unique_tiles * TILE_SIZE * TILE_SIZE
    directory_bytes = world_face_count * TILE_DIRECTORY_BYTES
    return {
        "canonicalization": mode,
        "tileSize": TILE_SIZE,
        "tileReferences": references,
        "paddingBytes": padding_bytes,
        "uniqueTiles": unique_tiles,
        "identifierBits": identifier_bits,
        "transformBits": transform_bits,
        "referenceBits": reference_bits,
        "dictionaryBytes": dictionary_bytes,
        "packedReferenceBytes": packed_reference_bytes,
        "byteAlignedReferenceBytes": aligned_reference_bytes,
        "bytesPerAlignedReference": aligned_reference_size,
        "directoryBytes": directory_bytes,
        "packedTotalBytes": (
            dictionary_bytes + packed_reference_bytes + directory_bytes
        ),
        "byteAlignedTotalBytes": (
            dictionary_bytes + aligned_reference_bytes + directory_bytes
        ),
    }


def linked_rom_budget(rom_path: Path, debug_info_path: Path) -> dict[str, int]:
    rom_bytes = rom_path.stat().st_size
    intervals: list[tuple[int, int]] = []
    pattern = re.compile(r"size=0x([0-9A-Fa-f]+).*ooffs=(\d+)")
    for line in debug_info_path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("seg\t") or 'oname="quake.sfc"' not in line:
            continue
        match = pattern.search(line)
        if match is None:
            raise EvaluationError("cannot parse linked ROM segment")
        size = int(match.group(1), 16)
        offset = int(match.group(2))
        if size:
            intervals.append((offset, offset + size))
    if not intervals or max(end for _start, end in intervals) > rom_bytes:
        raise EvaluationError("linked ROM segments escape the image")

    merged: list[list[int]] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    payload_bytes = sum(end - start for start, end in merged)
    occupied_banks = {
        bank
        for start, end in merged
        for bank in range(start // ROM_BANK_BYTES, (end - 1) // ROM_BANK_BYTES + 1)
    }
    bank_count = rom_bytes // ROM_BANK_BYTES
    last_occupied_bank = max(occupied_banks)
    return {
        "romBytes": rom_bytes,
        "bankBytes": ROM_BANK_BYTES,
        "bankCount": bank_count,
        "linkedPayloadBytes": payload_bytes,
        "logicalSlackBytes": rom_bytes - payload_bytes,
        "fullyEmptyBanks": bank_count - len(occupied_banks),
        "fullyEmptyBankBytes": (bank_count - len(occupied_banks)) * ROM_BANK_BYTES,
        "contiguousTailBytes": (bank_count - last_occupied_bank - 1) * ROM_BANK_BYTES,
    }


def scaled_direct_models(
    surfaces: Sequence[Surface],
    world_face_count: int,
    budget: dict[str, int],
) -> list[dict[str, int | bool]]:
    models: list[dict[str, int | bool]] = []
    for mip in range(4):
        scale = 1 << mip
        padded_bytes = 0
        for surface in surfaces:
            width = math.ceil(surface.width / scale)
            height = math.ceil(surface.height / scale)
            padded_bytes += (
                math.ceil(width / TILE_SIZE)
                * math.ceil(height / TILE_SIZE)
                * TILE_SIZE
                * TILE_SIZE
            )
        directory_bytes = world_face_count * SURFACE_DIRECTORY_BYTES
        total_bytes = padded_bytes + directory_bytes
        models.append(
            {
                "mip": mip,
                "linearScale": scale,
                "mip0Parity": mip == 0,
                "surfaceBytes": padded_bytes,
                "directoryBytes": directory_bytes,
                "totalBytes": total_bytes,
                "fitsContiguousTail": total_bytes <= budget["contiguousTailBytes"],
                "fitsFullyEmptyBanks": total_bytes <= budget["fullyEmptyBankBytes"],
                "fitsLogicalSlack": total_bytes <= budget["logicalSlackBytes"],
            }
        )
    return models


def downsample_surfaces(
    surfaces: Sequence[Surface], linear_scale: int
) -> list[Surface]:
    output: list[Surface] = []
    for surface in surfaces:
        pixels = np.frombuffer(surface.pixels, dtype=np.uint8).reshape(
            surface.height, surface.width
        )
        reduced = np.ascontiguousarray(pixels[::linear_scale, ::linear_scale])
        output.append(
            Surface(
                surface.face,
                reduced.shape[1],
                reduced.shape[0],
                reduced.tobytes(),
            )
        )
    return output


def annotate_fit(models: Iterable[dict[str, object]], budget: dict[str, int]) -> None:
    for model in models:
        total = int(
            model["byteAlignedTotalBytes"]
            if "byteAlignedTotalBytes" in model
            else model["totalBytes"]
        )
        model["fitsContiguousTail"] = total <= budget["contiguousTailBytes"]
        model["fitsFullyEmptyBanks"] = total <= budget["fullyEmptyBankBytes"]
        model["fitsLogicalSlack"] = total <= budget["logicalSlackBytes"]


def evaluate(
    data_dir: Path = DEFAULT_DATA_DIR,
    rom_path: Path = DEFAULT_ROM,
    debug_info_path: Path = DEFAULT_DEBUG_INFO,
) -> dict[str, object]:
    assets = load_assets(data_dir)
    surfaces, source = build_surfaces(assets)
    tiles, padding_bytes = collect_tiles(surfaces)
    budget = linked_rom_budget(rom_path, debug_info_path)
    surface_models = [
        measure_surface_reuse(surfaces, len(assets.faces), mode)
        for mode in ("exact", "mirrors", "dihedral")
    ]
    tile_models = [
        measure_tile_reuse(tiles, len(assets.faces), padding_bytes, mode)
        for mode in ("exact", "mirrors", "dihedral")
    ]
    mip3_surfaces = downsample_surfaces(surfaces, 8)
    mip3_tiles, mip3_padding = collect_tiles(mip3_surfaces)
    mip3_tile_models = [
        measure_tile_reuse(mip3_tiles, len(assets.faces), mip3_padding, mode)
        for mode in ("exact", "mirrors", "dihedral")
    ]
    annotate_fit((*surface_models, *tile_models), budget)
    annotate_fit(mip3_tile_models, budget)

    exact_tiles, mirror_tiles, dihedral_tiles = tile_models
    full_resolution_models = [
        (
            f"whole-surface-{model['canonicalization']}",
            int(model["totalBytes"]),
        )
        for model in surface_models
    ] + [
        (
            f"8x8-tile-{model['canonicalization']}",
            int(model["byteAlignedTotalBytes"]),
        )
        for model in tile_models
    ]
    best_name, best_bytes = min(full_resolution_models, key=lambda item: item[1])
    symmetry_saved = int(exact_tiles["dictionaryBytes"]) - int(
        dihedral_tiles["dictionaryBytes"]
    )
    tiled_source_bytes = int(exact_tiles["tileReferences"]) * TILE_SIZE * TILE_SIZE
    exact_reuse_saved = tiled_source_bytes - int(exact_tiles["dictionaryBytes"])
    conclusion = {
        "fullResolutionFitsAlongsideCurrentPaths": best_bytes
        <= budget["logicalSlackBytes"],
        "fullResolutionFitsEvenIfItOwnedTheWholeRom": best_bytes <= budget["romBytes"],
        "bestFullResolutionModel": best_name,
        "bestFullResolutionBytes": best_bytes,
        "bestFullResolutionTimesWholeRom": best_bytes / budget["romBytes"],
        "bestFullResolutionTimesLogicalSlack": best_bytes / budget["logicalSlackBytes"],
        "exactTileDictionaryBytesSavedVsUnsharedTiles": exact_reuse_saved,
        "exactTileDictionaryPercentSavedVsUnsharedTiles": (
            exact_reuse_saved * 100.0 / tiled_source_bytes
        ),
        "dihedralDictionaryBytesSavedVsExactTiles": symmetry_saved,
        "dihedralDictionaryPercentSavedVsExactTiles": (
            symmetry_saved * 100.0 / int(exact_tiles["dictionaryBytes"])
        ),
        "mip3FitsContiguousTailWithExactTiles": bool(
            mip3_tile_models[0]["fitsContiguousTail"]
        ),
        "mip3FitsFullyEmptyBanksWithExactTiles": bool(
            mip3_tile_models[0]["fitsFullyEmptyBanks"]
        ),
        "recommendation": (
            "Do not store every full-resolution composed E1M3 surface. "
            "Rotations and mirrors barely improve exact 8x8 reuse; evaluate "
            "a selective full-resolution cache or the 1/8-linear cache that "
            "fits across the currently empty banks as a lower-mip/far-surface "
            "path instead."
        ),
    }
    return {
        "schema": 1,
        "experiment": "e1m3-technique4-precomposed-surface-storage",
        "exactness": {
            "renderer": "current packed SNES/C++ technique 4",
            "textureFilter": "nearest",
            "lightmapFilter": "Q4 two-stage rounded bilinear",
            "coordinateDomain": (
                "conservative inclusive integer-texel bounds from each "
                "drawable face's packed Q4 vertex-coordinate extrema"
            ),
            "dynamicLights": False,
            "animatedOrSwitchedLightStyles": False,
            "mip": 0,
        },
        "source": {
            "map": "maps/e1m3.bsp",
            "inputSha256": assets.input_sha256,
            **source,
        },
        "romBudget": budget,
        "surfaceModels": surface_models,
        "tileModels": tile_models,
        "tileRuntimeContract": (
            "Tile models add an indirection per 8x8 region; mirrors require "
            "axis reversal and dihedral transforms can also require S/T swap. "
            "The byte-aligned totals charge transform bits in each reference. "
            "The fixed 9-byte directory covers all 4,419 source-face IDs with "
            "a 24-bit reference offset, tile dimensions, and signed origins."
        ),
        "surfaceDirectoryContract": (
            "The fixed 11-byte directory covers all 4,419 source-face IDs "
            "with a 24-bit pointer plus 16-bit dimensions and signed origins."
        ),
        "scaledDirectModels": scaled_direct_models(surfaces, len(assets.faces), budget),
        "mip3TileModels": mip3_tile_models,
        "mip3Contract": (
            "Point-reduced from the exact mip0 composite at one sample per "
            "8x8 source-texel block. This is 1/64 pixel density and does not "
            "preserve full-resolution parity."
        ),
        "conclusion": conclusion,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--debug-info", type=Path, default=DEFAULT_DEBUG_INFO)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = evaluate(
            args.data_dir.resolve(),
            args.rom.resolve(),
            args.debug_info.resolve(),
        )
        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        exact = report["tileModels"][0]
        dihedral = report["tileModels"][2]
        print(
            "result="
            + (
                "FIT"
                if report["conclusion"]["fullResolutionFitsAlongsideCurrentPaths"]
                else "NO_FIT"
            )
            + f" faces={report['source']['categories']['drawableLightmapped']}"
            + f" raw={report['source']['reachableCropBytes']}"
            + f" slack={report['romBudget']['logicalSlackBytes']}"
        )
        print(
            f"8x8 exact={exact['uniqueTiles']} tiles/"
            f"{exact['byteAlignedTotalBytes']} bytes "
            f"d4={dihedral['uniqueTiles']} tiles/"
            f"{dihedral['byteAlignedTotalBytes']} bytes "
            f"symmetrySaved={report['conclusion']['dihedralDictionaryBytesSavedVsExactTiles']}"
        )
        mip3 = report["mip3TileModels"][0]
        print(
            f"mip3 exact={mip3['uniqueTiles']} tiles/"
            f"{mip3['byteAlignedTotalBytes']} bytes "
            f"tailFit={mip3['fitsContiguousTail']}"
        )
        print(f"report={output}")
        return 0
    except (OSError, ValueError, KeyError, EvaluationError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
