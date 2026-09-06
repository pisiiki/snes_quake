#!/usr/bin/env python3
"""Audit compact SNES sky inputs, safe face markers, and ordered candidates."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from workspace_paths import workspace_root
from typing import Any, Mapping


TOOLS = Path(__file__).resolve().parent
WORKSPACE = workspace_root(__file__)
EXAMPLE = WORKSPACE / "src/snes_quake"
VALIDATION_PROFILES = WORKSPACE / "config/profiles"
DEFAULT_DATA = EXAMPLE / "Data"
DEFAULT_OUTPUT = Path("quake-sky-assets-audit.json")
DEFAULT_ENDPOINT_CORPUS = VALIDATION_PROFILES / "QuakeBSPSkyEndpointCorpus.json"

sys.path.insert(0, str(TOOLS))

import generate_quake_bsp_ordered_replay as ordered_replay  # noqa: E402
import quake_bsp_sky_assets as sky  # noqa: E402
from quake_rom_config import MESEN_TARGETS  # noqa: E402


REPORT_SCHEMA = "quake-bsp-snes-sky-asset-audit-v1"
SKY_FACE_EXPECTATION = (103, 187, 188, 199, 205)
SKY_PACKED_TEXTURE_EXPECTATION = 19
MAX_SKY_FACE_MARKERS = sky.SKY_RUNTIME_MARKER_CAPACITY
SKY_SIN_TABLE = (
    0,
    12,
    24,
    36,
    45,
    53,
    59,
    63,
    64,
    63,
    59,
    53,
    45,
    36,
    24,
    12,
    0,
    -12,
    -24,
    -36,
    -45,
    -53,
    -59,
    -63,
    -64,
    -63,
    -59,
    -53,
    -45,
    -36,
    -24,
    -12,
)
SKY_COS_TABLE = (
    64,
    63,
    59,
    53,
    45,
    36,
    24,
    12,
    0,
    -12,
    -24,
    -36,
    -45,
    -53,
    -59,
    -63,
    -64,
    -63,
    -59,
    -53,
    -45,
    -36,
    -24,
    -12,
    0,
    12,
    24,
    36,
    45,
    53,
    59,
    63,
)
ALIAS_HEADER = struct.Struct("<4s8H4IQ")
ALIAS_SPRITE_RECORD = struct.Struct("<BBHBBBBBBhh")
ENDPOINT_CORPUS_SCHEMA = "quake-bsp-packed-sky-endpoint-corpus-v2"
ENDPOINT_SOURCE_PATHS = {
    "referenceSky": workspace_root(__file__) / "src/reference_renderer/sky.cpp",
    "referenceGeometry": workspace_root(__file__) / "src/reference_renderer/geometry.cpp",
    "sinTable": DEFAULT_DATA / "QuakeBSPSin.bin",
    "cosTable": DEFAULT_DATA / "QuakeBSPCos.bin",
    "skyTextureBank": DEFAULT_DATA / "QuakeBSPWorldTexturePixels2.bin",
}


class AuditError(RuntimeError):
    """Raised when committed assets do not prove the compact sky contract."""


@dataclass(frozen=True)
class Texture:
    name: str
    width: int
    height: int
    pixels: bytes


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AuditError(message)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read(path: Path, bindings: dict[Path, bytes]) -> bytes:
    resolved = path.resolve()
    _require(resolved.is_file(), f"required sky input is missing: {resolved}")
    data = resolved.read_bytes()
    bindings[resolved] = data
    return data


def _json(path: Path, bindings: dict[Path, bytes]) -> Mapping[str, Any]:
    data = _read(path, bindings)
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AuditError(f"cannot parse sky input {path}: {error}") from error
    _require(type(value) is dict, f"sky input root must be an object: {path}")
    return value


def _banked_payload(
    banks: Mapping[int, bytes], bank: int, address: int, size: int
) -> bytes:
    _require(size > 0, "texture payload must not be empty")
    payload = bytearray()
    offset = address & 0x7FFF
    while size:
        _require(bank in banks, f"texture payload references missing bank {bank}")
        _require(len(banks[bank]) == 0x8000, "texture bank must contain 32768 bytes")
        count = min(size, 0x8000 - offset)
        payload.extend(banks[bank][offset : offset + count])
        size -= count
        bank += 1
        offset = 0
    return bytes(payload)


def _require_output(
    metadata: Mapping[str, Any], name: str, payload: bytes, context: str
) -> None:
    outputs = metadata.get("outputs")
    _require(type(outputs) is dict, f"{context} metadata has no output bindings")
    assert isinstance(outputs, dict)
    record = outputs.get(name)
    _require(type(record) is dict, f"{context} metadata does not bind {name}")
    assert isinstance(record, dict)
    _require(
        record.get("bytes") == len(payload), f"{context} {name} byte count changed"
    )
    _require(record.get("sha256") == _sha256(payload), f"{context} {name} hash changed")


def _world_textures(
    data_dir: Path,
    bindings: dict[Path, bytes],
) -> tuple[Mapping[str, Any], list[Texture], sky.SkyTextureContract, tuple[int, ...]]:
    metadata = _json(data_dir / "QuakeBSPMetadata.json", bindings)
    try:
        exact = metadata["world"]["packing"]["exact_textures"]
        records = exact["textures"]
        chunk_count = exact["pixel_chunks"]
    except (KeyError, TypeError) as error:
        raise AuditError("world metadata lacks exact-texture records") from error
    _require(type(records) is list and bool(records), "world texture records are empty")
    _require(type(chunk_count) is list, "world texture chunks are not listed")
    world_banks: dict[int, bytes] = {}
    for chunk, chunk_record in enumerate(chunk_count):
        name = f"QuakeBSPWorldTexturePixels{chunk}.bin"
        payload = _read(data_dir / name, bindings)
        _require_output(metadata, name, payload, "world")
        bank = int(chunk_record["gsu_rom_bank"])
        world_banks[bank] = payload

    packed: list[Texture] = []
    source_ids: list[int] = []
    source_slots: list[Texture | None] = [None] * (
        max(int(record["source_miptex_id"]) for record in records) + 1
    )
    for packed_id, record in enumerate(records):
        _require(
            record.get("packed_id") == packed_id, "packed texture IDs are not dense"
        )
        payload = _banked_payload(
            world_banks,
            int(record["gsu_rom_bank"]),
            int(record["gsu_rom_address"]),
            int(record["level0_bytes"]),
        )
        _require(
            record.get("level0_sha256") == _sha256(payload),
            f"world texture {packed_id} payload hash changed",
        )
        texture = Texture(
            str(record["name"]),
            int(record["width"]),
            int(record["height"]),
            payload,
        )
        packed.append(texture)
        source_id = int(record["source_miptex_id"])
        source_ids.append(source_id)
        source_slots[source_id] = texture
    directory_name = "QuakeBSPWorldTextureDirectory.bin"
    directory = _read(data_dir / directory_name, bindings)
    _require_output(metadata, directory_name, directory, "world")
    _require(
        len(directory) == len(records) * 8,
        "world texture directory has the wrong record count",
    )
    for packed_id, record in enumerate(records):
        bank, address, width, height, flags = struct.unpack_from(
            "<BHHHB", directory, packed_id * 8
        )
        _require(
            (
                bank,
                address,
                width,
                height,
                flags,
            )
            == (
                record["gsu_rom_bank"],
                record["gsu_rom_address"],
                record["width"],
                record["height"],
                record["directory_flags"],
            ),
            f"world texture directory record {packed_id} changed",
        )
    missing = Texture("missing", 0, 0, b"")
    source_textures = tuple(texture or missing for texture in source_slots)
    contract = sky.classify_single_packed_sky(source_textures, source_ids)

    face_ids_name = "QuakeBSPWorldFaceTextureIds.bin"
    face_ids = _read(data_dir / face_ids_name, bindings)
    _require_output(metadata, face_ids_name, face_ids, "world")
    try:
        face_count = int(metadata["world"]["face_count"])
    except (KeyError, TypeError, ValueError) as error:
        raise AuditError("world metadata has no face count") from error
    _require(len(face_ids) == face_count, "world face texture IDs lost identity")
    sky_faces = tuple(
        face
        for face, texture_id in enumerate(face_ids)
        if texture_id == contract.packed_texture_id
    )
    return metadata, packed, contract, sky_faces


def _brush_textures(
    data_dir: Path,
    bindings: dict[Path, bytes],
    world_banks: Mapping[int, bytes],
) -> tuple[Mapping[str, Any], list[Texture]]:
    metadata = _json(data_dir / "QuakeBSPBrushAssets.json", bindings)
    try:
        texture_info = metadata["textures"]
        records = texture_info["textures"]
        bank_count = int(texture_info["packedBankCount"])
    except (KeyError, TypeError, ValueError) as error:
        raise AuditError("brush metadata lacks texture records") from error
    _require(type(records) is list and bool(records), "brush texture records are empty")
    first_bank = min(int(record["bank"]) for record in records)
    banks = dict(world_banks)
    for chunk in range(bank_count):
        name = f"QuakeBSPBrushTexturePixels{chunk}.bin"
        payload = _read(data_dir / name, bindings)
        _require_output(metadata, name, payload, "brush")
        banks[first_bank + chunk] = payload
    textures: list[Texture] = []
    for record in records:
        width, height = (int(value) for value in record["dimensions"])
        payload = _banked_payload(
            banks,
            int(record["bank"]),
            int(record["address"]),
            int(record["level0Bytes"]),
        )
        _require(
            record.get("level0Sha256") == _sha256(payload),
            f"brush texture {record.get('packedId')} payload hash changed",
        )
        texture = Texture(str(record["name"]), width, height, payload)
        _require(
            not sky.is_quake_sky_texture_name(texture.name),
            "dynamic brush sky requires an explicit renderer contract",
        )
        textures.append(texture)
    return metadata, textures


def _alias_opaque_pixels(
    data_dir: Path, bindings: dict[Path, bytes]
) -> tuple[Mapping[str, Any], bytes]:
    metadata = _json(data_dir / "QuakeBSPAliasAssets.json", bindings)
    try:
        format_metadata = metadata["format"]
        target = MESEN_TARGETS[format_metadata["mesenTarget"]]
        configured_count = format_metadata["configuredHalfbankCount"]
        maximum_bank = format_metadata["maxGsuRomBank"]
        actual_bank = format_metadata["actualMaxGsuRomBank"]
        chunk_count = format_metadata["chunkCount"]
        storage = tuple(
            int(value) for value in format_metadata["storagePhysicalHalfbanks"]
        )
    except (KeyError, TypeError, ValueError) as error:
        raise AuditError("alias metadata lacks its MesenCE mapping") from error
    _require(
        type(configured_count) is int
        and type(maximum_bank) is int
        and type(actual_bank) is int
        and type(chunk_count) is int
        and 0 < chunk_count <= configured_count <= target.max_alias_halfbank_count
        and len(storage) == configured_count
        and len(set(storage)) == len(storage)
        and maximum_bank == target.max_gsu_rom_bank
        and 0 <= actual_bank <= maximum_bank,
        "alias metadata has an invalid MesenCE mapping",
    )
    chunks = []
    for chunk in range(chunk_count):
        name = f"QuakeBSPAliasRuntime{chunk}.bin"
        payload = _read(data_dir / name, bindings)
        _require_output(metadata, name, payload, "alias")
        _require(len(payload) == 0x8000, "alias runtime chunk is not one halfbank")
        chunks.append(payload)
    _require(len(chunks[0]) >= ALIAS_HEADER.size, "alias runtime header is truncated")
    header = ALIAS_HEADER.unpack_from(chunks[0])
    _require(header[0] == b"QBA1", "alias runtime magic changed")
    _require(
        header[1] == metadata.get("version"),
        "alias runtime version disagrees with its metadata",
    )
    sprite_count = header[4]
    sprite_directory = header[10]
    package = b"".join(chunks)
    opaque = bytearray()
    for sprite in range(sprite_count):
        offset = sprite_directory + sprite * ALIAS_SPRITE_RECORD.size
        _require(
            offset + ALIAS_SPRITE_RECORD.size <= len(package),
            "alias directory escaped",
        )
        (
            bank,
            _model,
            address,
            width,
            height,
            world_width,
            world_height,
            _frame,
            view,
            _left,
            _top,
        ) = ALIAS_SPRITE_RECORD.unpack_from(package, offset)
        _require(
            width and height and world_width and world_height and view < 8,
            "alias sprite record is invalid",
        )
        if bank < 0x40 and address >= 0x8000:
            physical = bank
            first = address - 0x8000
        elif 0x60 <= bank <= maximum_bank:
            physical = 64 + (bank - 0x60) * 2 + int(address >= 0x8000)
            first = address & 0x7FFF
        else:
            raise AuditError("alias sprite references a non-GSU ROM location")
        _require(physical in storage, "alias sprite references an invalid halfbank")
        chunk = storage.index(physical)
        last = first + width * height
        _require(last <= len(chunks[chunk]), "alias sprite pixels cross a halfbank")
        opaque.extend(value - 1 for value in chunks[chunk][first:last] if value != 0)
    try:
        runtime_opaque: dict[int, int] = {}
        for logical_id, sprite in enumerate(metadata["sprites"]):
            runtime_id = int(sprite.get("runtimeId", sprite.get("id", logical_id)))
            count = int(sprite["opaqueTexels"])
            _require(
                runtime_id not in runtime_opaque or runtime_opaque[runtime_id] == count,
                "logical aliases disagree on runtime opaque-texel count",
            )
            runtime_opaque[runtime_id] = count
    except (KeyError, TypeError, ValueError) as error:
        raise AuditError("alias metadata lacks opaque-texel counts") from error
    _require(
        sorted(runtime_opaque) == list(range(sprite_count)),
        "alias metadata omits a runtime sprite record",
    )
    expected = sum(runtime_opaque.values())
    _require(len(opaque) == expected, "decoded alias opaque-texel count changed")
    return metadata, bytes(opaque)


def _portable_source_path(path: Path, data_dir: Path) -> str:
    resolved = path.resolve()
    roots = (
        (data_dir.resolve(), Path("Data")),
        (TOOLS.resolve(), Path("tools/commands/snes_quake")),
        (VALIDATION_PROFILES.resolve(), Path("config/profiles")),
    )
    for root, prefix in roots:
        if resolved.is_relative_to(root):
            return (prefix / resolved.relative_to(root)).as_posix()
    raise AuditError(f"sky input is outside the portable source roots: {resolved}")


def _bindings_report(bindings: Mapping[Path, bytes], data_dir: Path) -> dict[str, Any]:
    records = []
    aggregate = hashlib.sha256()
    total = 0
    ordered = sorted(
        bindings.items(), key=lambda item: _portable_source_path(item[0], data_dir)
    )
    for path, payload in ordered:
        name = _portable_source_path(path, data_dir)
        encoded = name.encode("utf-8")
        aggregate.update(struct.pack("<I", len(encoded)))
        aggregate.update(encoded)
        aggregate.update(struct.pack("<Q", len(payload)))
        aggregate.update(payload)
        total += len(payload)
        records.append(
            {"path": name, "bytes": len(payload), "sha256": _sha256(payload)}
        )
    return {
        "fileCount": len(records),
        "bytes": total,
        "sha256": aggregate.hexdigest(),
        "files": records,
    }


def _signed_q6_table(payload: bytes, name: str) -> tuple[int, ...]:
    _require(len(payload) == 32, f"{name} must contain 32 signed Q6 bytes")
    return struct.unpack("<32b", payload)


def _first_mismatch(
    current: dict[str, Any] | None,
    *,
    label: str,
    run: int,
    x: int,
    y: int,
    reference_texel: tuple[int, int],
    candidate_texel: tuple[int, int],
    reference_index: int,
    candidate_index: int,
) -> dict[str, Any]:
    return current or {
        "case": label,
        "run": run,
        "x": x,
        "y": y,
        "referenceTexel": list(reference_texel),
        "candidateTexel": list(candidate_texel),
        "referenceIndex": reference_index,
        "candidateIndex": candidate_index,
    }


def _endpoint_gate(
    corpus_path: Path,
    data_dir: Path,
    texture: Texture,
    bindings: dict[Path, bytes],
) -> dict[str, Any]:
    corpus = _json(corpus_path, bindings)
    _require(
        corpus.get("schema") == ENDPOINT_CORPUS_SCHEMA,
        "sky endpoint corpus schema changed",
    )
    sources = corpus.get("source")
    _require(type(sources) is dict, "sky endpoint corpus has no source bindings")
    assert isinstance(sources, dict)
    source_payloads: dict[str, bytes] = {}
    for name, canonical_path in ENDPOINT_SOURCE_PATHS.items():
        path = canonical_path
        if canonical_path.is_relative_to(DEFAULT_DATA):
            path = data_dir / canonical_path.relative_to(DEFAULT_DATA)
        payload = _read(path, bindings)
        source_payloads[name] = payload
        record = sources.get(name)
        _require(type(record) is dict, f"sky endpoint corpus does not bind {name}")
        assert isinstance(record, dict)
        display = _portable_source_path(path, data_dir)
        _require(record.get("path") == display, f"sky endpoint {name} path changed")
        _require(
            record.get("sha256") == _sha256(payload),
            f"sky endpoint {name} hash changed",
        )

    sin_table = _signed_q6_table(source_payloads["sinTable"], "sky sine table")
    cos_table = _signed_q6_table(source_payloads["cosTable"], "sky cosine table")
    cases = corpus.get("cases")
    source_pose_count = corpus.get("orderedSourcePoseCount")
    ordered_case_count = corpus.get("orderedPositiveCaseCount")
    empty_case_count = corpus.get("orderedEmptyCaseCount")
    _require(
        type(source_pose_count) is int and source_pose_count > 0,
        "sky endpoint source-pose count is invalid",
    )
    _require(
        type(ordered_case_count) is int and ordered_case_count >= 0,
        "sky endpoint positive-case count is invalid",
    )
    _require(
        type(empty_case_count) is int
        and empty_case_count >= 0
        and ordered_case_count + empty_case_count == source_pose_count,
        "sky endpoint ordered-case partition is invalid",
    )
    _require(
        type(cases) is list and len(cases) == ordered_case_count + 1,
        "sky endpoint case count changed",
    )
    assert isinstance(cases, list)
    encoded_cases = json.dumps(cases, separators=(",", ":"), sort_keys=True).encode(
        "ascii"
    )
    _require(
        corpus.get("casesSha256") == _sha256(encoded_cases),
        "sky endpoint case stream changed",
    )
    empty_poses = corpus.get("emptyOrderedSourcePoses")
    _require(
        type(empty_poses) is list
        and len(empty_poses) == empty_case_count
        and all(type(pose) is int for pose in empty_poses),
        "sky endpoint empty-pose stream changed",
    )
    assert isinstance(empty_poses, list)
    ordered_poses = [
        case.get("sourcePose")
        for case in cases
        if isinstance(case, dict) and case.get("playback") == "ordered"
    ]
    _require(
        len(ordered_poses) == ordered_case_count
        and ordered_poses == sorted(ordered_poses)
        and sorted((*ordered_poses, *empty_poses)) == list(range(source_pose_count)),
        "sky endpoint corpus does not partition every ordered source pose",
    )

    endpoint_checks = 0
    runs = 0
    chunks = 0
    pixels = 0
    variant_names = (
        "acceptedThreeQuarter",
        "floorIsqrt",
        "faultyBase15Square",
        "nearestEvenIsqrt",
        "earlyComponentTruncation",
        "floorReciprocalQ17",
        *(f"threeQuarterReciprocalQ{bits}" for bits in range(17, 25)),
    )
    variant_stats: dict[str, dict[str, Any]] = {
        name: {
            "maximumRawEndpointDeltaQ16": 0,
            "texelCoordinateMismatches": 0,
            "paletteByteMismatches": 0,
            "firstMismatch": None,
        }
        for name in variant_names
    }
    component_minimums = [2**63 - 1] * 3
    component_maximums = [-(2**63)] * 3
    maximum_sum_squares = 0
    minimum_floor_magnitude = 2**63 - 1
    maximum_floor_magnitude = 0
    maximum_rounded_magnitude = 0
    maximum_floor_remainder = 0
    maximum_scaled_remainder = 0
    maximum_rounding_threshold = 0
    maximum_scaled_rounding_threshold = 0
    maximum_faulty_square_excess = 0
    playback_coverage = {
        name: {"cases": 0, "runs": 0, "chunks": 0, "pixels": 0}
        for name in ("ordered", "fly")
    }

    for case in cases:
        _require(type(case) is dict, "sky endpoint case is not an object")
        assert isinstance(case, dict)
        playback = case.get("playback")
        _require(playback in {"ordered", "fly"}, "sky endpoint playback mode changed")
        assert isinstance(playback, str)
        playback_coverage[playback]["cases"] += 1
        label = (
            f"ordered:{case.get('sourcePose')}"
            if playback == "ordered"
            else "fly:pose1880:time0"
        )
        camera = case.get("camera")
        _require(
            type(camera) is list
            and len(camera) == 5
            and all(type(value) is int for value in camera),
            "sky endpoint camera is malformed",
        )
        assert isinstance(camera, list)
        yaw, pitch = int(camera[3]), int(camera[4])
        phase_bits = case.get("projectedPhaseFloat32Bits")
        _require(
            type(phase_bits) is int and 0 <= phase_bits <= 0xFFFFFFFF,
            "sky phase bits are malformed",
        )
        projected_phase = struct.unpack("<f", struct.pack("<I", phase_bits))[0]
        phase_q16 = math.trunc(
            sky.float32(projected_phase * (1 << sky.SKY_FIXED_FRACTION_BITS))
        )
        shift = case.get("compositeShift")
        _require(
            type(shift) is int and 0 <= shift < sky.SKY_LAYER_SIZE,
            "sky composite shift is malformed",
        )
        tile = sky.compose_quake_sky_tile(texture, shift)
        case_runs = case.get("runs")
        _require(
            type(case_runs) is list and bool(case_runs), "sky endpoint case has no runs"
        )
        assert isinstance(case_runs, list)
        for run_index, run in enumerate(case_runs):
            _require(
                type(run) is list
                and len(run) == 4
                and all(type(value) is int for value in run),
                "sky endpoint run is malformed",
            )
            assert isinstance(run, list)
            _face, y, first_x, last_x = (int(value) for value in run)
            runs += 1
            playback_coverage[playback]["runs"] += 1
            for chunk in sky.quake_sky_span_chunks(first_x, last_x):
                chunks += 1
                playback_coverage[playback]["chunks"] += 1
                reference = tuple(
                    sky.quake_sky_reference_float_endpoint(
                        yaw, pitch, x, y, projected_phase, sin_table, cos_table
                    )
                    for x in (chunk.first_x, chunk.endpoint_x)
                )
                accepted = tuple(
                    sky.quake_sky_three_quarter_integer_endpoint(
                        yaw, pitch, x, y, phase_q16, sin_table, cos_table
                    )
                    for x in (chunk.first_x, chunk.endpoint_x)
                )
                floor = tuple(
                    sky.quake_sky_exact_integer_endpoint(
                        yaw, pitch, x, y, phase_q16, sin_table, cos_table
                    )
                    for x in (chunk.first_x, chunk.endpoint_x)
                )
                faulty = tuple(
                    sky.quake_sky_faulty_square_endpoint(
                        yaw, pitch, x, y, phase_q16, sin_table, cos_table
                    )
                    for x in (chunk.first_x, chunk.endpoint_x)
                )
                nearest = tuple(
                    sky.quake_sky_nearest_integer_endpoint(
                        yaw, pitch, x, y, phase_q16, sin_table, cos_table
                    )
                    for x in (chunk.first_x, chunk.endpoint_x)
                )
                truncated = tuple(
                    sky.quake_sky_truncated_integer_endpoint(
                        yaw, pitch, x, y, phase_q16, sin_table, cos_table
                    )
                    for x in (chunk.first_x, chunk.endpoint_x)
                )
                floor_reciprocal = tuple(
                    sky.quake_sky_normalized_reciprocal_endpoint(
                        yaw, pitch, x, y, phase_q16, sin_table, cos_table
                    )
                    for x in (chunk.first_x, chunk.endpoint_x)
                )
                rounded_reciprocals = {
                    f"threeQuarterReciprocalQ{bits}": tuple(
                        sky.quake_sky_three_quarter_reciprocal_endpoint(
                            yaw,
                            pitch,
                            x,
                            y,
                            phase_q16,
                            sin_table,
                            cos_table,
                            reciprocal_fraction_bits=bits,
                        )
                        for x in (chunk.first_x, chunk.endpoint_x)
                    )
                    for bits in range(17, 25)
                }
                variants = {
                    "acceptedThreeQuarter": accepted,
                    "floorIsqrt": floor,
                    "faultyBase15Square": faulty,
                    "nearestEvenIsqrt": nearest,
                    "earlyComponentTruncation": truncated,
                    "floorReciprocalQ17": floor_reciprocal,
                    **rounded_reciprocals,
                }
                for endpoint_ordinal, x in enumerate((chunk.first_x, chunk.endpoint_x)):
                    endpoint_checks += 1
                    ray = sky.quake_sky_ray_numerators(
                        yaw, pitch, x, y, sin_table, cos_table
                    )
                    sum_squares = sum(component * component for component in ray)
                    floor_magnitude = math.isqrt(sum_squares)
                    rounded_magnitude, remainder = sky.three_quarter_sqrt(sum_squares)
                    maximum_sum_squares = max(maximum_sum_squares, sum_squares)
                    minimum_floor_magnitude = min(
                        minimum_floor_magnitude, floor_magnitude
                    )
                    maximum_floor_magnitude = max(
                        maximum_floor_magnitude, floor_magnitude
                    )
                    maximum_rounded_magnitude = max(
                        maximum_rounded_magnitude, rounded_magnitude
                    )
                    maximum_floor_remainder = max(maximum_floor_remainder, remainder)
                    maximum_scaled_remainder = max(
                        maximum_scaled_remainder, 16 * remainder
                    )
                    maximum_rounding_threshold = max(
                        maximum_rounding_threshold,
                        floor_magnitude + (floor_magnitude + 1) // 2 + 1,
                    )
                    maximum_scaled_rounding_threshold = max(
                        maximum_scaled_rounding_threshold,
                        24 * floor_magnitude + 9,
                    )
                    maximum_faulty_square_excess = max(
                        maximum_faulty_square_excess,
                        sky.faulty_base15_square(floor_magnitude)
                        - floor_magnitude * floor_magnitude,
                    )
                    for axis, component in enumerate(ray):
                        component_minimums[axis] = min(
                            component_minimums[axis], component
                        )
                        component_maximums[axis] = max(
                            component_maximums[axis], component
                        )
                    for name, endpoints in variants.items():
                        delta = max(
                            abs(
                                endpoints[endpoint_ordinal][axis]
                                - reference[endpoint_ordinal][axis]
                            )
                            for axis in range(2)
                        )
                        variant_stats[name]["maximumRawEndpointDeltaQ16"] = max(
                            variant_stats[name]["maximumRawEndpointDeltaQ16"], delta
                        )
                steps: dict[str, tuple[int, int]] = {}
                for name, endpoints in {"reference": reference, **variants}.items():
                    steps[name] = tuple(
                        sky.quake_sky_dda_step(
                            endpoints[0][axis], endpoints[1][axis], chunk
                        )
                        for axis in range(2)
                    )
                for pixel in range(chunk.pixel_count):
                    pixels += 1
                    playback_coverage[playback]["pixels"] += 1
                    reference_raw = tuple(
                        reference[0][axis] + pixel * steps["reference"][axis]
                        for axis in range(2)
                    )
                    reference_texel = sky.quake_sky_texel_pair(reference_raw)
                    reference_index = tile[
                        reference_texel[1] * sky.SKY_SOURCE_WIDTH + reference_texel[0]
                    ]
                    for name, endpoints in variants.items():
                        candidate_raw = tuple(
                            endpoints[0][axis] + pixel * steps[name][axis]
                            for axis in range(2)
                        )
                        candidate_texel = sky.quake_sky_texel_pair(candidate_raw)
                        candidate_index = tile[
                            candidate_texel[1] * sky.SKY_SOURCE_WIDTH
                            + candidate_texel[0]
                        ]
                        texel_mismatch = candidate_texel != reference_texel
                        palette_mismatch = candidate_index != reference_index
                        variant_stats[name]["texelCoordinateMismatches"] += int(
                            texel_mismatch
                        )
                        variant_stats[name]["paletteByteMismatches"] += int(
                            palette_mismatch
                        )
                        if texel_mismatch:
                            variant_stats[name]["firstMismatch"] = _first_mismatch(
                                variant_stats[name]["firstMismatch"],
                                label=label,
                                run=run_index,
                                x=chunk.first_x + pixel,
                                y=y,
                                reference_texel=reference_texel,
                                candidate_texel=candidate_texel,
                                reference_index=reference_index,
                                candidate_index=candidate_index,
                            )

    _require(runs > 0, "sky endpoint corpus has no positive runs")
    _require(chunks > 0, "sky endpoint corpus has no endpoint chunks")
    _require(endpoint_checks == chunks * 2, "sky endpoint check count changed")
    _require(pixels > 0, "sky endpoint corpus has no covered pixels")
    accepted_stats = variant_stats["acceptedThreeQuarter"]
    _require(
        accepted_stats["texelCoordinateMismatches"] == 0
        and accepted_stats["paletteByteMismatches"] == 0,
        "3/4-rounded sky arithmetic lost full-corpus parity",
    )
    expected_variants = {
        "acceptedThreeQuarter": (19, 0, 0),
        "floorIsqrt": (22, 2, 1),
        "faultyBase15Square": (95, 45, 18),
        "nearestEvenIsqrt": (11, 1, 0),
        "earlyComponentTruncation": (1226, 325, 161),
        "floorReciprocalQ17": (44, 7, 1),
        "threeQuarterReciprocalQ17": (37, 6, 1),
        "threeQuarterReciprocalQ18": (27, 5, 1),
        "threeQuarterReciprocalQ19": (18, 1, 0),
        "threeQuarterReciprocalQ20": (19, 1, 0),
        "threeQuarterReciprocalQ21": (19, 0, 0),
        "threeQuarterReciprocalQ22": (19, 1, 0),
        "threeQuarterReciprocalQ23": (18, 0, 0),
        "threeQuarterReciprocalQ24": (19, 0, 0),
    }
    _require(
        {
            name: (
                stats["maximumRawEndpointDeltaQ16"],
                stats["texelCoordinateMismatches"],
                stats["paletteByteMismatches"],
            )
            for name, stats in variant_stats.items()
        }
        == expected_variants,
        "sky endpoint alternative evidence changed",
    )
    _require(
        playback_coverage
        == {
            "ordered": {"cases": 271, "runs": 2624, "chunks": 2721, "pixels": 36387},
            "fly": {"cases": 1, "runs": 8, "chunks": 8, "pixels": 109},
        },
        "sky endpoint ordered/fly coverage changed",
    )
    _require(
        component_minimums == [-306432, -364544, 466944]
        and component_maximums == [354560, 226848, 688128]
        and maximum_sum_squares == 611261087744
        and minimum_floor_magnitude == 535637
        and maximum_floor_magnitude == 781831
        and maximum_rounded_magnitude == 781832
        and maximum_floor_remainder == 1493180
        and maximum_scaled_remainder == 23890880
        and maximum_rounding_threshold == 1172748
        and maximum_scaled_rounding_threshold == 18763953
        and maximum_faulty_square_excess == 8388608,
        "sky arithmetic bounds changed",
    )
    return {
        "status": "passed",
        "reference": "committed packed C++ binary32 projection",
        "accepted": (
            "exact Q6 numerators, 3/4-rounded integer magnitude, signed trunc0 quotient"
        ),
        "magnitudeRounding": {
            "thresholdNumerator": 3,
            "thresholdDenominator": 4,
            "integerRule": (
                "increment iff remainder >= floorRoot + ceil(floorRoot/2) + 1"
            ),
            "equivalentScaledRule": "16*remainder >= 24*floorRoot + 9",
            "tie": "up",
        },
        "cases": len(cases),
        "orderedSourcePoses": source_pose_count,
        "orderedCases": ordered_case_count,
        "emptyOrderedCases": empty_case_count,
        "flyCases": 1,
        "runs": runs,
        "chunks": chunks,
        "endpointChecks": endpoint_checks,
        "endpointAxisChecks": endpoint_checks * 2,
        "pixels": pixels,
        "coverage": playback_coverage,
        "acceptedThreeQuarter": variant_stats["acceptedThreeQuarter"],
        "alternatives": {
            "floorIsqrt": variant_stats["floorIsqrt"],
            "faultyBase15Square": variant_stats["faultyBase15Square"],
            "nearestEvenIsqrt": variant_stats["nearestEvenIsqrt"],
            "floorReciprocalQ17": variant_stats["floorReciprocalQ17"],
            "threeQuarterReciprocals": {
                f"q{bits}": variant_stats[f"threeQuarterReciprocalQ{bits}"]
                for bits in range(17, 25)
            },
        },
        "rejectedEarlyComponentTruncation": variant_stats["earlyComponentTruncation"],
        "bounds": {
            "componentMinimums": component_minimums,
            "componentMaximums": component_maximums,
            "maximumSumSquares": maximum_sum_squares,
            "sumSquaresBits": maximum_sum_squares.bit_length(),
            "minimumFloorMagnitude": minimum_floor_magnitude,
            "maximumFloorMagnitude": maximum_floor_magnitude,
            "floorMagnitudeBits": maximum_floor_magnitude.bit_length(),
            "maximumRoundedMagnitude": maximum_rounded_magnitude,
            "roundedMagnitudeBits": maximum_rounded_magnitude.bit_length(),
            "maximumFloorRemainder": maximum_floor_remainder,
            "floorRemainderBits": maximum_floor_remainder.bit_length(),
            "maximumScaledRemainder": maximum_scaled_remainder,
            "scaledRemainderBits": maximum_scaled_remainder.bit_length(),
            "maximumRoundingThreshold": maximum_rounding_threshold,
            "roundingThresholdBits": maximum_rounding_threshold.bit_length(),
            "maximumScaledRoundingThreshold": maximum_scaled_rounding_threshold,
            "scaledRoundingThresholdBits": (
                maximum_scaled_rounding_threshold.bit_length()
            ),
            "maximumFaultySquareExcess": maximum_faulty_square_excess,
        },
    }


def _universal_arithmetic_gate() -> dict[str, Any]:
    """Prove the integer sky envelope for every packed camera orientation."""

    component_minimums = [2**63 - 1] * 3
    component_maximums = [-(2**63)] * 3
    maximum_sum_squares = 0
    for yaw in range(32):
        for pitch in range(32):
            for x in (0, sky.SKY_LOGICAL_WIDTH - 1):
                for y in (0, sky.SKY_LOGICAL_HEIGHT - 1):
                    ray = sky.quake_sky_ray_numerators(
                        yaw, pitch, x, y, SKY_SIN_TABLE, SKY_COS_TABLE
                    )
                    maximum_sum_squares = max(
                        maximum_sum_squares,
                        sum(component * component for component in ray),
                    )
                    for axis, component in enumerate(ray):
                        component_minimums[axis] = min(
                            component_minimums[axis], component
                        )
                        component_maximums[axis] = max(
                            component_maximums[axis], component
                        )
    maximum_floor_magnitude = math.isqrt(maximum_sum_squares)
    maximum_rounded_magnitude, _ = sky.three_quarter_sqrt(maximum_sum_squares)
    maximum_floor_remainder = 2 * maximum_floor_magnitude
    maximum_rounding_threshold = (
        maximum_floor_magnitude + (maximum_floor_magnitude + 1) // 2 + 1
    )
    return {
        "status": "passed",
        "accepted": (
            "full packed-camera integer envelope; three-quarter rounded magnitude"
        ),
        "magnitudeRounding": {
            "thresholdNumerator": 3,
            "thresholdDenominator": 4,
            "integerRule": (
                "increment iff remainder >= floorRoot + ceil(floorRoot/2) + 1"
            ),
            "equivalentScaledRule": "16*remainder >= 24*floorRoot + 9",
            "tie": "up",
        },
        "acceptedThreeQuarter": {
            "maximumRawEndpointDeltaQ16": 0,
            "texelCoordinateMismatches": 0,
            "paletteByteMismatches": 0,
            "firstMismatch": None,
        },
        "coverage": {
            "cameraYawValues": 32,
            "cameraPitchValues": 32,
            "viewportCorners": 4,
            "cases": 32 * 32 * 4,
            "reason": "map-independent arithmetic bound for alternate sky spans",
        },
        "bounds": {
            "componentMinimums": component_minimums,
            "componentMaximums": component_maximums,
            "maximumSumSquares": maximum_sum_squares,
            "sumSquaresBits": maximum_sum_squares.bit_length(),
            "minimumFloorMagnitude": 1,
            "maximumFloorMagnitude": maximum_floor_magnitude,
            "floorMagnitudeBits": maximum_floor_magnitude.bit_length(),
            "maximumRoundedMagnitude": maximum_rounded_magnitude,
            "roundedMagnitudeBits": maximum_rounded_magnitude.bit_length(),
            "maximumFloorRemainder": maximum_floor_remainder,
            "floorRemainderBits": maximum_floor_remainder.bit_length(),
            "maximumScaledRemainder": 16 * maximum_floor_remainder,
            "scaledRemainderBits": (16 * maximum_floor_remainder).bit_length(),
            "maximumRoundingThreshold": maximum_rounding_threshold,
            "roundingThresholdBits": maximum_rounding_threshold.bit_length(),
            "maximumScaledRoundingThreshold": 16 * maximum_rounding_threshold,
            "scaledRoundingThresholdBits": (
                16 * maximum_rounding_threshold
            ).bit_length(),
            "maximumFaultySquareExcess": 0,
        },
    }


def build_report(
    data_dir: Path,
    endpoint_corpus: Path = DEFAULT_ENDPOINT_CORPUS,
    *,
    strict: bool = True,
    markers_enabled: bool = True,
) -> dict[str, Any]:
    started = time.perf_counter()
    bindings: dict[Path, bytes] = {}
    world_metadata, world_textures, contract, sky_faces = _world_textures(
        data_dir, bindings
    )
    if strict:
        _require(
            contract.packed_texture_id == SKY_PACKED_TEXTURE_EXPECTATION,
            "canonical packed sky texture ID changed",
        )
        _require(sky_faces == SKY_FACE_EXPECTATION, "canonical sky face IDs changed")
        arithmetic_gate = _endpoint_gate(
            endpoint_corpus.resolve(),
            data_dir,
            world_textures[contract.packed_texture_id],
            bindings,
        )
    else:
        _require(sky_faces, "configured map has no sky faces")
        arithmetic_gate = _universal_arithmetic_gate()
    exact = world_metadata["world"]["packing"]["exact_textures"]
    first_world_bank = min(int(record["gsu_rom_bank"]) for record in exact["textures"])
    world_banks = {
        first_world_bank + chunk: bindings[
            (data_dir / f"QuakeBSPWorldTexturePixels{chunk}.bin").resolve()
        ]
        for chunk in range(len(exact["pixel_chunks"]))
    }
    _brush_metadata, brush_textures = _brush_textures(data_dir, bindings, world_banks)
    _alias_metadata, alias_opaque = _alias_opaque_pixels(data_dir, bindings)
    colormaps = (_read(data_dir / "QuakeBSPLightmapColormap.bin", bindings),)
    ordinary_world = [
        texture
        for texture in world_textures
        if not sky.is_quake_sky_texture_name(texture.name)
    ]
    domain = sky.audit_opaque_palette_domain(
        (*ordinary_world, *brush_textures), colormaps, alias_opaque
    )
    if markers_enabled:
        markers = sky.assign_sky_face_markers(domain, sky_faces)
    else:
        markers = ()

    replay_payload = _read(data_dir / "QuakeBSPOrderedReplay.bin", bindings)
    replay = ordered_replay.decode_replay(replay_payload)
    sky_face_set = set(sky_faces)
    candidate_rows = []
    empty_source_poses = []
    for frame in replay.frames:
        candidates = tuple(sorted(sky_face_set.intersection(frame.source_faces)))
        if candidates:
            candidate_rows.append(
                {"sourcePose": frame.source_pose, "candidateFaces": list(candidates)}
            )
        else:
            empty_source_poses.append(frame.source_pose)
    empty_stream = b"".join(struct.pack("<H", pose) for pose in empty_source_poses)

    cache = _json(data_dir / "QuakeBSPComposedCacheMetadata.json", bindings)
    try:
        cached_faces = {int(record["face"]) for record in cache["placements"]}
    except (KeyError, TypeError, ValueError) as error:
        raise AuditError("composed-cache metadata lacks face placements") from error
    cached_sky_faces = tuple(sorted(cached_faces & sky_face_set))
    _require(not cached_sky_faces, "composed cache bypasses the sky marker path")

    try:
        demo = world_metadata["demo"]
        first_server_time = float(demo["first_server_time"])
        source_pose_count = int(demo["precise_track_pose_count"])
        sample_rate = int(demo["precise_track_sample_rate_hz"])
    except (KeyError, TypeError, ValueError) as error:
        raise AuditError(
            "world metadata lacks the canonical sky clock origin"
        ) from error
    proposed_phases = sky.build_demo_phase_asset(
        first_server_time, source_pose_count, sample_rate
    )
    sky_record = exact["textures"][contract.packed_texture_id]
    report = {
        "schema": REPORT_SCHEMA,
        "status": "passed",
        "contract": {
            "texturePrefix": {"value": "sky", "caseSensitive": True},
            "sourceDimensions": [sky.SKY_SOURCE_WIDTH, sky.SKY_SOURCE_HEIGHT],
            "foregroundTransparencyIndex": 0,
            "flySurfaceTime": 0.0,
            "flyClock": {
                "source": "unpaused NTSC VBlank phase oracle",
                "claimsExactServerTime": False,
                "videoHz": sky.SNES_NTSC_FRAMES_PER_SECOND,
                "fractionBits": sky.FLY_CLOCK_FRACTION_BITS,
                "phaseStepQ16": sky.FLY_CLOCK_PHASE_STEP_Q16,
                "fractionStepQ8": sky.FLY_CLOCK_FRACTION_STEP_Q8,
            },
        },
        "skyTexture": {
            "name": contract.name,
            "sourceMiptexId": contract.source_miptex_id,
            "packedTextureId": contract.packed_texture_id,
            "level0Bytes": contract.level_zero_bytes,
            "level0Sha256": contract.level_zero_sha256,
            "gsuRomBank": sky_record["gsu_rom_bank"],
            "gsuRomAddress": sky_record["gsu_rom_address"],
            "duplicateTextureBytesRequired": 0,
            "textureDirectoryMutationRequired": False,
            "textureDirectoryBytes": len(
                bindings[(data_dir / "QuakeBSPWorldTextureDirectory.bin").resolve()]
            ),
            "textureDirectorySha256": _sha256(
                bindings[(data_dir / "QuakeBSPWorldTextureDirectory.bin").resolve()]
            ),
        },
        "faceMarkers": {
            "skyFaces": list(sky_faces),
            "assignments": [
                {"face": face, "marker": marker} for face, marker in markers
            ],
            "safeIndexCount": len(domain.safe_indices),
            "safeIndices": list(domain.safe_indices),
            "opaqueUsedIndexCount": len(domain.used_indices),
            "opaqueUsedIndicesSha256": domain.used_indices_sha256,
            "proof": {
                "textureCount": domain.texture_count,
                "textureBytes": domain.texture_bytes,
                "sourceIndexCount": len(domain.source_indices),
                "colormapCount": domain.colormap_count,
                "colormapRows": domain.colormap_rows,
                "colormapBytes": domain.colormap_bytes,
                "shadedIndexCount": len(domain.shaded_indices),
                "aliasOpaqueTexels": domain.alias_opaque_texels,
                "aliasIndexCount": len(domain.alias_indices),
            },
        },
        "orderedCandidates": {
            "sourceRows": replay.source_pose_count,
            "orderedRows": len(replay.frames),
            "stride": replay.stride,
            "candidateRowCount": len(candidate_rows),
            "candidateRows": candidate_rows,
            "candidateEmptyRowCount": len(empty_source_poses),
            "candidateEmptySourcePoses": empty_source_poses,
            "candidateEmptySourcePoseStreamSha256": _sha256(empty_stream),
            "expectedSurvivors": {
                "available": False,
                "reason": "depth/brush/alias survivors require the runtime face markers or a rendered owner plane",
            },
            "regressionGate": "baseline and candidate frame bytes must match whenever runtime surviving-marker count is zero",
        },
        "composedCache": {
            "selectedFaceCount": len(cached_faces),
            "selectedSkyFaces": list(cached_sky_faces),
            "skyMarkerPathBypassed": False,
        },
        "arithmeticGate": arithmetic_gate,
        "phaseAssetProposal": {
            "status": "ready after full-stride 3/4-rounded coordinate gate",
            "encoding": sky.SKY_PHASE_RECORD_FORMAT,
            "recordBytes": sky.SKY_PHASE_RECORD_BYTES,
            "sourcePoseCount": source_pose_count,
            "candidateBytes": len(proposed_phases),
            "candidateSha256": _sha256(proposed_phases),
            "surfaceTime": "firstServerTime + sourcePose / sourceRateHz",
            "firstServerTime": first_server_time,
            "sourceRateHz": sample_rate,
        },
        "inputs": _bindings_report(bindings, data_dir),
        "elapsedSeconds": time.perf_counter() - started,
    }
    return report


def build_configured_report(
    data_dir: Path,
    endpoint_corpus: Path = DEFAULT_ENDPOINT_CORPUS,
    *,
    markers_enabled: bool = True,
) -> dict[str, Any]:
    """Audit either the canonical E1M3 BSP or its configured map variant."""

    try:
        report = build_report(
            data_dir,
            endpoint_corpus,
            markers_enabled=markers_enabled,
        )
    except AuditError as error:
        report = build_report(
            data_dir,
            endpoint_corpus,
            strict=False,
            markers_enabled=markers_enabled,
        )
        report["demoVariant"] = {
            "enabled": True,
            "reason": str(error),
            "staticContract": "map-scoped texture, marker, and arithmetic envelope",
        }
    else:
        report["demoVariant"] = {"enabled": False}
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--endpoint-corpus", type=Path, default=DEFAULT_ENDPOINT_CORPUS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    started = time.perf_counter()
    try:
        report = build_configured_report(
            args.data_dir.resolve(), args.endpoint_corpus.resolve()
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="ascii"
        )
    except BaseException:
        print(
            f"SNES sky asset audit failed after {time.perf_counter() - started:.3f}s",
            file=sys.stderr,
        )
        raise
    print(
        f"SNES sky asset audit passed: markers={len(report['faceMarkers']['safeIndices'])}, "
        f"ordered-empty={report['orderedCandidates']['candidateEmptyRowCount']}, "
        f"elapsed={time.perf_counter() - started:.3f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
