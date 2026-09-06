#!/usr/bin/env python3
"""Generate and audit deterministic Quake turbulent-surface assets."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from workspace_paths import shared_tools_root, workspace_root
import struct
import sys
import time
from typing import Any, Mapping, Sequence


TOOLS = Path(__file__).resolve().parent
EXAMPLE = workspace_root(__file__) / "src/snes_quake"
SHARED = shared_tools_root(__file__)
sys.path[:0] = [str(TOOLS), str(SHARED)]

from snes_tooling.shared.generated_outputs import (  # noqa: E402
    GeneratedOutputError,
    sync_generated_outputs,
)
import quake_bsp_turbulence as turbulence  # noqa: E402


DEFAULT_DATA = EXAMPLE / "Data"
PHASE_PATH = Path("QuakeBSPTurbulencePhases.bin")
TABLE_PATH = Path("QuakeBSPTurbulenceTable.bin")
CONSTANTS_PATH = Path("QuakeBSPTurbulenceAssets.i")
ASSEMBLY_PATH = Path("QuakeBSPTurbulenceAssets.s")
METADATA_PATH = Path("QuakeBSPTurbulenceAssets.json")
WORLD_METADATA_PATH = Path("QuakeBSPMetadata.json")
BRUSH_METADATA_PATH = Path("QuakeBSPBrushAssets.json")
FACE_TEXTURE_PATH = Path("QuakeBSPWorldFaceTextureIds.bin")
LIGHTMAP_DIRECTORY_PATH = Path("QuakeBSPWorldLightmapDirectory.bin")
TIMING_PATH = Path("QuakeBSPDemoPreciseTiming.bin")
SKY_PHASE_PATH = Path("QuakeBSPSkyPhases.bin")
PHASE_GSU_ROM_BANK = 0x03
PHASE_CPU_ROM_BANK = 0x83
PHASE_BANK_ADDRESS = 0x8000
PHASE_BANK_BYTES = 0x8000
LIGHTMAP_RECORD = struct.Struct("<BHBBbb")
TEXTURE_RECORD = struct.Struct("<BHHHB")
TEXTURE_FLAG_TURBULENT = 4
MAX_TURBULENT_TEXTURES = 8


class GenerationError(RuntimeError):
    """Raised when generated world assets cannot satisfy the runtime ABI."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise GenerationError(message)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _read(path: Path, inputs: list[dict[str, object]]) -> bytes:
    try:
        payload = path.read_bytes()
    except OSError as error:
        raise GenerationError(f"required turbulence input is missing: {path}") from error
    inputs.append({"path": path.name, "bytes": len(payload), "sha256": _sha256(payload)})
    return payload


def _json(payload: bytes, label: str) -> dict[str, Any]:
    try:
        parsed = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GenerationError(f"{label} is not valid JSON") from error
    _require(type(parsed) is dict, f"{label} root must be an object")
    return parsed


def _require_output(metadata: Mapping[str, Any], name: str, payload: bytes) -> None:
    try:
        record = metadata["outputs"][name]
        expected_bytes = int(record["bytes"])
        expected_sha256 = str(record["sha256"])
    except (KeyError, TypeError, ValueError) as error:
        raise GenerationError(f"world metadata does not bind {name}") from error
    _require(expected_bytes == len(payload), f"{name} byte count changed")
    _require(expected_sha256 == _sha256(payload), f"{name} SHA-256 changed")


def _portable_inputs(records: Sequence[Mapping[str, object]]) -> dict[str, object]:
    ordered = sorted(records, key=lambda record: str(record["path"]))
    aggregate = hashlib.sha256()
    total = 0
    for record in ordered:
        encoded = str(record["path"]).encode("ascii")
        aggregate.update(struct.pack("<I", len(encoded)))
        aggregate.update(encoded)
        aggregate.update(struct.pack("<Q", int(record["bytes"])))
        aggregate.update(bytes.fromhex(str(record["sha256"])))
        total += int(record["bytes"])
    return {
        "fileCount": len(ordered),
        "bytes": total,
        "sha256": aggregate.hexdigest(),
        "files": ordered,
    }


def _material_report(
    texture: Mapping[str, Any], faces: Sequence[int], lightmaps: Sequence[tuple[int, ...]]
) -> dict[str, object]:
    name = str(texture["name"])
    packed_id = int(texture["packed_id"])
    width = int(texture["width"])
    height = int(texture["height"])
    turbulence.require_turbulent_texture(width, height, bytes(width * height))
    baked_ignored = [face for face in faces if lightmaps[face][0] != 0xFF]
    explicit_bypass = [
        face
        for face in faces
        if lightmaps[face][0] == 0xFF and lightmaps[face][1] == 0x00C0
    ]
    invalid_missing = [
        face
        for face in faces
        if lightmaps[face][0] == 0xFF and lightmaps[face][1] != 0x00C0
    ]
    _require(not invalid_missing, f"turbulent texture {name} has a dark missing lightmap")
    return {
        "name": name,
        "material": turbulence.turbulent_material(name),
        "sourceMiptexId": int(texture["source_miptex_id"]),
        "packedTextureId": packed_id,
        "dimensions": [width, height],
        "levelZeroBytes": int(texture["level0_bytes"]),
        "levelZeroSha256": str(texture["level0_sha256"]),
        "directoryFlags": int(texture["directory_flags"]),
        "faces": list(faces),
        "faceCount": len(faces),
        "lightmapPolicy": "fullbright runtime sampler ignores baked samples",
        "bakedSamplesIgnoredFaces": baked_ignored,
        "bakedSamplesIgnoredFaceCount": len(baked_ignored),
        "intentionalMissingBypassFaces": explicit_bypass,
        "intentionalMissingBypassFaceCount": len(explicit_bypass),
    }


def build_audit(data_dir: Path) -> tuple[dict[str, Any], bytes, bytes, int]:
    input_records: list[dict[str, object]] = []
    metadata_payload = _read(data_dir / WORLD_METADATA_PATH, input_records)
    metadata = _json(metadata_payload, WORLD_METADATA_PATH.name)
    brush_payload = _read(data_dir / BRUSH_METADATA_PATH, input_records)
    brush_metadata = _json(brush_payload, BRUSH_METADATA_PATH.name)
    face_texture_ids = _read(data_dir / FACE_TEXTURE_PATH, input_records)
    lightmap_payload = _read(data_dir / LIGHTMAP_DIRECTORY_PATH, input_records)
    texture_directory = _read(
        data_dir / "QuakeBSPWorldTextureDirectory.bin", input_records
    )
    timing = _read(data_dir / TIMING_PATH, input_records)
    sky_phases = _read(data_dir / SKY_PHASE_PATH, input_records)
    for name, payload in (
        (FACE_TEXTURE_PATH.name, face_texture_ids),
        (LIGHTMAP_DIRECTORY_PATH.name, lightmap_payload),
        ("QuakeBSPWorldTextureDirectory.bin", texture_directory),
        (TIMING_PATH.name, timing),
    ):
        _require_output(metadata, name, payload)

    _require(len(lightmap_payload) % LIGHTMAP_RECORD.size == 0, "lightmap directory is misaligned")
    lightmaps = tuple(LIGHTMAP_RECORD.iter_unpack(lightmap_payload))
    _require(len(lightmaps) == len(face_texture_ids), "face/lightmap identity changed")
    _require(len(texture_directory) % TEXTURE_RECORD.size == 0, "texture directory is misaligned")
    directory = tuple(TEXTURE_RECORD.iter_unpack(texture_directory))
    try:
        textures = metadata["world"]["packing"]["exact_textures"]["textures"]
        demo = metadata["demo"]
    except (KeyError, TypeError) as error:
        raise GenerationError("world metadata lacks texture/demo provenance") from error
    _require(type(textures) is list and textures, "world texture metadata is empty")
    turbulent_textures = [
        texture for texture in textures if str(texture["name"]).startswith("*")
    ]
    _require(0 < len(turbulent_textures) <= MAX_TURBULENT_TEXTURES, "turbulent texture count exceeds ABI")
    materials: list[dict[str, object]] = []
    turbulent_face_set: set[int] = set()
    for texture in turbulent_textures:
        packed_id = int(texture["packed_id"])
        _require(0 <= packed_id < len(directory), "turbulent packed texture ID escapes directory")
        _require(directory[packed_id][-1] & TEXTURE_FLAG_TURBULENT != 0, "turbulent directory flag is absent")
        faces = tuple(
            face for face, texture_id in enumerate(face_texture_ids) if texture_id == packed_id
        )
        _require(faces, f"configured turbulent texture {texture['name']} has no world faces")
        _require(not turbulent_face_set.intersection(faces), "turbulent face ownership overlaps")
        turbulent_face_set.update(faces)
        materials.append(_material_report(texture, faces, lightmaps))

    ordinary_missing_dark = [
        face
        for face, record in enumerate(lightmaps)
        if record[0] == 0xFF and record[1] == 0x00FF and face not in turbulent_face_set
    ]
    _require(ordinary_missing_dark, "ordinary missing-lightmap dark proof is empty")
    sky_textures = [
        texture
        for texture in textures
        if str(texture["name"]).casefold().startswith("sky")
    ]
    sky_faces = [
        face
        for face, texture_id in enumerate(face_texture_ids)
        if any(texture_id == int(texture["packed_id"]) for texture in sky_textures)
    ]
    brush_special = [
        texture
        for texture in brush_metadata.get("textures", {}).get("textures", [])
        if str(texture.get("name", "")).startswith("*")
        or str(texture.get("name", "")).casefold().startswith("sky")
    ]

    phases = turbulence.build_demo_phase_asset(
        float(demo["first_server_time"]),
        int(demo["precise_track_pose_count"]),
        int(demo["precise_track_sample_rate_hz"]),
    )
    table = turbulence.build_turbulence_table()
    phase_address = PHASE_BANK_ADDRESS + len(timing) + len(sky_phases)
    _require(
        phase_address + len(phases) + len(table) <= PHASE_BANK_ADDRESS + PHASE_BANK_BYTES,
        "turbulence assets cross GSU ROM bank $03",
    )
    report: dict[str, Any] = {
        "schema": "quake-bsp-turbulence-assets-v1",
        "status": "generated",
        "sourceSemantics": {
            "skyPrefix": "sky (case-insensitive)",
            "turbulentPrefix": "*",
            "worldSkyFaces": sky_faces,
            "worldSkyFaceCount": len(sky_faces),
            "worldTurbulentFaces": sorted(turbulent_face_set),
            "worldTurbulentFaceCount": len(turbulent_face_set),
            "configuredBrushSpecialTextures": brush_special,
            "configuredBrushSpecialTextureCount": len(brush_special),
        },
        "materials": materials,
        "lightmapDistinction": {
            "turbulentPolicy": "all turbulent faces are fullbright even when BSP samples exist",
            "ordinaryMissingPolicy": "darkest Quake colormap row",
            "ordinaryMissingDarkFaces": ordinary_missing_dark,
            "ordinaryMissingDarkFaceCount": len(ordinary_missing_dark),
        },
        "contract": {
            "source": "WinQuake D_DrawTurbulent8Span/Turbulent8",
            "cycle": turbulence.TURBULENCE_CYCLE,
            "speedHz": turbulence.TURBULENCE_SPEED,
            "amplitudeTexels": turbulence.TURBULENCE_AMPLITUDE,
            "textureDimensions": [64, 64],
            "coordinateEncoding": "signed Q4; low 10 bits wrap after cross-axis displacement",
            "tableEncoding": "128 unsigned biased Q4 displacements; 256 saturates to 255",
            "maximumTableQuantizationErrorTexels": 1 / 16,
            "palettePolicy": "source level-zero index, fullbright, no lightmap colormap",
            "overflowPolicy": "two's-complement low-word arithmetic followed by 64x64 mask",
            "phase": "floor(surfaceTime*20) mod 128 from command clock",
            "tableBytes": len(table),
            "tableSha256": _sha256(table),
            "contractSha256": _sha256(turbulence.table_contract_bytes()),
        },
        "phase": {
            "encoding": "little-endian unsigned low 23 bits of Q16 table phase",
            "recordBytes": turbulence.TURBULENCE_PHASE_RECORD_BYTES,
            "poseCount": len(phases) // turbulence.TURBULENCE_PHASE_RECORD_BYTES,
            "bytes": len(phases),
            "sha256": _sha256(phases),
            "gsuRomBank": PHASE_GSU_ROM_BANK,
            "gsuRomAddress": phase_address,
            "gsuRomEndAddress": phase_address + len(phases),
            "source": "canonical renderer server-time origin plus pose/sampleRate",
            "flyClock": {
                "source": "unpaused NTSC VBlank, seeded from selected demo command phase",
                "fractionBits": turbulence.FLY_CLOCK_FRACTION_BITS,
                "phaseStepQ16": turbulence.FLY_CLOCK_PHASE_STEP_Q16,
                "fractionStepQ8": turbulence.FLY_CLOCK_FRACTION_STEP_Q8,
                "videoHz": turbulence.SNES_NTSC_FRAMES_PER_SECOND,
            },
        },
        "inputs": _portable_inputs(input_records),
    }
    return report, phases, table, phase_address


def _hex(value: int, width: int) -> str:
    return f"${value:0{width}X}"


def constants_text(report: Mapping[str, Any], phase_address: int) -> bytes:
    materials = report["materials"]
    phase = report["phase"]
    contract = report["contract"]
    lines = [
        "; Generated by generate_quake_bsp_turbulence_assets.py; do not edit.",
        ".ifndef __QUAKE_BSP_TURBULENCE_ASSETS_I__",
        "__QUAKE_BSP_TURBULENCE_ASSETS_I__ = 1",
        "",
        "BSP_TURBULENCE_ENABLED = 1",
        f"BSP_TURBULENCE_TEXTURE_COUNT = {len(materials)}",
    ]
    for index in range(MAX_TURBULENT_TEXTURES):
        value = int(materials[index]["packedTextureId"]) if index < len(materials) else 0xFF
        lines.append(f"BSP_TURBULENCE_TEXTURE_ID_{index} = {value}")
    lines.extend(
        (
            f"BSP_TURBULENCE_CYCLE = {contract['cycle']}",
            f"BSP_TURBULENCE_SPEED = {contract['speedHz']}",
            f"BSP_TURBULENCE_AMPLITUDE = {contract['amplitudeTexels']}",
            f"BSP_TURBULENCE_TEXTURE_SIZE = {contract['textureDimensions'][0]}",
            f"BSP_TURBULENCE_COORD_FRACTION_BITS = {turbulence.TURBULENCE_COORD_FRACTION_BITS}",
            f"BSP_TURBULENCE_COORD_MASK_Q4 = {_hex(turbulence.TURBULENCE_COORD_MASK_Q4, 4)}",
            f"BSP_TURBULENCE_TABLE_BYTES = {contract['tableBytes']}",
            f"BSP_TURBULENCE_PHASE_MASK = {_hex(turbulence.TURBULENCE_PHASE_MASK, 6)}",
            f"BSP_TURBULENCE_PHASE_RECORD_BYTES = {phase['recordBytes']}",
            f"BSP_TURBULENCE_PHASE_POSE_COUNT = {phase['poseCount']}",
            f"BSP_TURBULENCE_PHASE_BYTES = {phase['bytes']}",
            f"BSP_TURBULENCE_PHASE_GSU_ROM_BANK = {_hex(PHASE_GSU_ROM_BANK, 2)}",
            f"BSP_TURBULENCE_PHASE_GSU_ROM_ADDRESS = {_hex(phase_address, 4)}",
            f"BSP_TURBULENCE_PHASE_GSU_ROM_END_ADDRESS = {_hex(phase_address + int(phase['bytes']), 4)}",
            f"BSP_TURBULENCE_FLY_CLOCK_FRACTION_BITS = {turbulence.FLY_CLOCK_FRACTION_BITS}",
            f"BSP_TURBULENCE_FLY_CLOCK_PHASE_STEP_Q16 = {turbulence.FLY_CLOCK_PHASE_STEP_Q16}",
            f"BSP_TURBULENCE_FLY_CLOCK_FRACTION_STEP_Q8 = {turbulence.FLY_CLOCK_FRACTION_STEP_Q8}",
            "",
            ".endif",
            "",
        )
    )
    return "\n".join(lines).encode("ascii")


def assembly_text(phase_address: int, phase_bytes: int, table_bytes: int) -> bytes:
    phase_end = phase_address + phase_bytes
    table_end = phase_end + table_bytes
    return (
        "; Generated by generate_quake_bsp_turbulence_assets.py; do not edit.\n"
        '.segment "BSP_DEMO_TIMING"\n'
        "QuakeBSPTurbulencePhases:\n"
        '        .incbin "Data/QuakeBSPTurbulencePhases.bin"\n'
        "QuakeBSPTurbulencePhasesEnd:\n"
        "QuakeBSPTurbulenceTable:\n"
        '        .incbin "Data/QuakeBSPTurbulenceTable.bin"\n'
        "QuakeBSPTurbulenceTableEnd:\n"
        '.assert QuakeBSPTurbulencePhases = QuakeBSPSkyPhasesEnd, error, "Turbulence phases must follow sky phases"\n'
        '.assert QuakeBSPTurbulencePhasesEnd - QuakeBSPTurbulencePhases = BSP_TURBULENCE_PHASE_BYTES, error, "Turbulence phase size disagrees"\n'
        '.assert QuakeBSPTurbulenceTableEnd - QuakeBSPTurbulenceTable = BSP_TURBULENCE_TABLE_BYTES, error, "Turbulence table size disagrees"\n'
        f'.assert QuakeBSPTurbulencePhases = {_hex((PHASE_CPU_ROM_BANK << 16) | phase_address, 6)}, lderror, "Turbulence phases moved"\n'
        f'.assert QuakeBSPTurbulenceTableEnd = {_hex((PHASE_CPU_ROM_BANK << 16) | table_end, 6)}, lderror, "Turbulence assets moved"\n'
        '.assert __BSP_DEMO_TIMING_SIZE__ = BSP_DEMO_PRECISE_TIMING_BYTES+BSP_SKY_PHASE_BYTES+BSP_TURBULENCE_PHASE_BYTES+BSP_TURBULENCE_TABLE_BYTES, lderror, "Timing/special-phase segment size disagrees"\n'
    ).encode("ascii")


def outputs_for(data_dir: Path) -> dict[Path, bytes]:
    report, phases, table, phase_address = build_audit(data_dir)
    constants = constants_text(report, phase_address)
    assembly = assembly_text(phase_address, len(phases), len(table))
    outputs: dict[Path, bytes] = {
        PHASE_PATH: phases,
        TABLE_PATH: table,
        CONSTANTS_PATH: constants,
        ASSEMBLY_PATH: assembly,
    }
    report["outputs"] = {
        path.name: {"bytes": len(payload), "sha256": _sha256(payload)}
        for path, payload in outputs.items()
    }
    outputs[METADATA_PATH] = (
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    ).encode("ascii")
    return outputs


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--output", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--check", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    started = time.perf_counter()
    args = parse_args(argv)
    try:
        outputs = outputs_for(args.data_dir.resolve())
        sync_generated_outputs(outputs, args.output.resolve(), check=args.check)
    except (GenerationError, GeneratedOutputError, OSError, ValueError) as error:
        print(f"error: {error}; elapsed={time.perf_counter() - started:.3f}s", file=sys.stderr)
        return 1
    action = "verified" if args.check else "generated"
    print(
        f"Quake turbulence assets {action}: phases={len(outputs[PHASE_PATH])} "
        f"table={len(outputs[TABLE_PATH])} outputs={len(outputs)} "
        f"elapsed={time.perf_counter() - started:.3f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
