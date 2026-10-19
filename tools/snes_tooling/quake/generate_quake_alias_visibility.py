#!/usr/bin/env python3
"""Generate compact ordered alias-depth visibility assets from the reference."""

from __future__ import annotations

from snes_tooling import Workspace

import argparse
import hashlib
import json
import struct
import subprocess
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from typing import Any


TOOLS = Workspace.discover().path('tools', 'snes_tooling', 'quake')
WORKSPACE = Workspace.discover().root
EXAMPLE = WORKSPACE / "src/snes_quake"
SHARED_TOOLS = Workspace.discover().shared_tools


import snes_tooling.quake.build_quake_bsp_reference as reference_build  # noqa: E402
from snes_tooling.shared.generated_outputs import (  # noqa: E402
    GeneratedOutputError,
    OwnedFileFamily,
    sync_generated_outputs,
)
import snes_tooling.quake.generate_quake_bsp as bsp_tools  # noqa: E402
import snes_tooling.quake.generate_quake_bsp_ordered_replay as ordered_replay  # noqa: E402
from snes_tooling.quake.quake_brush_replay import fnv1a64  # noqa: E402
from snes_tooling.quake.quake_alias_packing import HALFBANK_BYTES, gsu_location  # noqa: E402
from snes_tooling.quake.quake_rom_config import MESEN_TARGETS  # noqa: E402
from snes_tooling.quake.quake_rom_config import configured_warp_source_focal
from snes_tooling.quake import quake_alias_visibility_projection as projection_archive
from snes_tooling.shared.host_resources import physical_core_count


DEFAULT_OUTPUT = EXAMPLE / "Data"
DEFAULT_PREDECESSOR_REUSE_CONTRACT = (
    WORKSPACE / "config/ordered30-predecessor-reuse.json"
)
ENABLED_NAME = Path("QuakeBSPAliasVisibilityEnabled.bin")
DISABLED_NAME = Path("QuakeBSPAliasVisibilityDisabled.bin")
TEMPORAL_ENABLED_NAME = Path("QuakeBSPAliasTemporalEnabled.bin")
TEMPORAL_DISABLED_NAME = Path("QuakeBSPAliasTemporalDisabled.bin")
PREDECESSOR_NAME = Path("QuakeBSPAliasPredecessor.bin")
INCLUDE_NAME = Path("QuakeBSPAliasVisibility.i")
ASSEMBLY_NAME = Path("QuakeBSPAliasVisibility.s")
METADATA_NAME = Path("QuakeBSPAliasVisibility.json")
QAV_HEADER = struct.Struct("<4s12H3I2Q")
QAV_ROW = struct.Struct("<H")
QAV_RECORD = struct.Struct("<BBH")
QAV_MAGIC = b"QAV2"
QAV_VERSION = 2
QAV_HEADER_BYTES = 56
QAV_ROW_BYTES = 2
QAV_HALFBANK_BYTES = 0x8000
QAV_ROW_RECORD_BITS = 4
QAV_ROW_RECORD_MASK = (1 << QAV_ROW_RECORD_BITS) - 1
QAV_DICTIONARY_MAXIMUM = (1 << (16 - QAV_ROW_RECORD_BITS)) - 1
QAV_PARTIAL = 1
QAV_HIDDEN = 2
QAV_BRUSHES_ENABLED_OFFSET = 4 + 8 * 2
QAV_TEMPORAL_IDENTITY_RECORD = struct.Struct("<H")
QAV_PREDECESSOR_REUSE_WORD = struct.Struct("<H")
QAV_PREDECESSOR_REUSE_SCHEMA = "quake-ordered30-predecessor-reuse-v1"
QAV_PREDECESSOR_DISABLED_SCHEMA = "quake-ordered30-predecessor-disabled-v1"
QAV_PREDECESSOR_REUSE_CONTRACT = (
    "circular-previous-pose-logical-indexed8-sha256-v1"
)
QAV_PREDECESSOR_REUSE_SCOPE = {
    "orderedPresentations": 2226,
    "orderedRateHz": 30,
    "orderedPoseStride": 1,
    "technique": 4,
    "dynamicBrushesEnabled": True,
    "mdlEntitiesEnabled": True,
    "aliasVisibilityMode": "qav2",
    "orderedOnly": True,
}
QAV_PREDECESSOR_REUSE_ASSETS = {
    "aliasAssets": "QuakeBSPAliasAssets.json",
    "metadata": "QuakeBSPMetadata.json",
    "orderedCameraTrack": "QuakeBSPDemoPrecise.bin",
    "orderedTiming": "QuakeBSPDemoPreciseTiming.bin",
}
QBA_HEADER = struct.Struct("<4s8H4IQ")
QBA_ROW = struct.Struct("<BBHBBH")
QBA_STATE_BYTES = 8
QBA_GROUP_HEADER = struct.Struct("<HHB")
ENABLED_PHYSICAL_HALFBANK = 94
DISABLED_PHYSICAL_HALFBANK = 95
OWNED_OUTPUTS = (
    OwnedFileFamily(prefix="QuakeBSPAliasVisibility", suffix=".bin"),
    OwnedFileFamily(prefix="QuakeBSPAliasTemporal", suffix=".bin"),
    OwnedFileFamily(prefix="QuakeBSPAliasPredecessor", suffix=".bin"),
    OwnedFileFamily(prefix="QuakeBSPAliasVisibility", suffix=".i"),
    OwnedFileFamily(prefix="QuakeBSPAliasVisibility", suffix=".s"),
    OwnedFileFamily(prefix="QuakeBSPAliasVisibility", suffix=".json"),
)


class AliasVisibilityError(RuntimeError):
    """Report a malformed or stale QAV2 visibility corpus."""


def _mapping(value: object, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AliasVisibilityError(f"{context} must be an object")
    return value


def _sha256(value: object, context: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise AliasVisibilityError(f"{context} must be a lowercase SHA-256")
    return value


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _load_predecessor_reuse_contract(
    contract_path: Path, data_dir: Path, *, expected_rows: int
) -> tuple[bytes, dict[str, Any]]:
    raw = contract_path.read_bytes()
    try:
        document = _mapping(json.loads(raw), "predecessor reuse contract")
    except (UnicodeError, json.JSONDecodeError) as error:
        raise AliasVisibilityError(
            "predecessor reuse contract is not valid JSON"
        ) from error
    disabled = document.get("schema") == QAV_PREDECESSOR_DISABLED_SCHEMA
    if not disabled and document.get("schema") != QAV_PREDECESSOR_REUSE_SCHEMA:
        raise AliasVisibilityError("predecessor reuse contract schema is unsupported")
    scope = _mapping(document.get("scope"), "predecessor reuse scope")
    if any(scope.get(key) != value for key, value in QAV_PREDECESSOR_REUSE_SCOPE.items()):
        raise AliasVisibilityError("predecessor reuse scope is not canonical ORDER 30HZ")

    equality = _mapping(
        document.get("predecessorEquality"), "predecessor equality"
    )
    contract = "disabled-until-requalified" if disabled else QAV_PREDECESSOR_REUSE_CONTRACT
    if equality.get("contract") != contract:
        raise AliasVisibilityError("predecessor equality contract is unsupported")
    pose_count = equality.get("poseCount")
    poses = equality.get("reusablePoses")
    if type(pose_count) is not int or pose_count != expected_rows:
        raise AliasVisibilityError("predecessor reuse pose count disagrees with QAV2")
    if (
        not isinstance(poses, list)
        or any(type(pose) is not int for pose in poses)
        or poses != sorted(set(poses))
        or any(not 0 <= pose < pose_count for pose in poses)
        or equality.get("reusablePoseCount") != len(poses)
    ):
        raise AliasVisibilityError("predecessor reusable poses are invalid")
    if disabled and poses:
        raise AliasVisibilityError("disabled predecessor reuse cannot claim reusable poses")

    oracle = _mapping(document.get("oracle"), "predecessor reuse oracle")
    report_sha256 = None if disabled else _sha256(oracle.get("reportSha256"), "oracle report")
    logical_sha256 = None if disabled else _sha256(
        oracle.get("logicalSequenceSha256"), "oracle logical sequence"
    )
    bindings = _mapping(oracle.get("bindings"), "oracle bindings")
    for key, filename in QAV_PREDECESSOR_REUSE_ASSETS.items():
        binding = _mapping(bindings.get(key), f"oracle binding {key}")
        expected_bytes = binding.get("bytes")
        expected_sha256 = _sha256(binding.get("sha256"), f"oracle binding {key}")
        asset_path = data_dir / filename
        if (
            type(expected_bytes) is not int
            or asset_path.stat().st_size != expected_bytes
            or _file_sha256(asset_path) != expected_sha256
        ):
            raise AliasVisibilityError(
                f"predecessor reuse contract is stale for {filename}"
            )

    word_count = (pose_count + 15) // 16
    words = [0] * word_count
    for pose in poses:
        words[pose >> 4] |= 1 << (pose & 15)
    payload = b"".join(QAV_PREDECESSOR_REUSE_WORD.pack(word) for word in words)
    metadata = {
        "contract": contract,
        "contractSha256": hashlib.sha256(raw).hexdigest(),
        "oracleReportSha256": report_sha256,
        "logicalSequenceSha256": logical_sha256,
        "poseCount": pose_count,
        "reusablePoseCount": len(poses),
        "wordCount": word_count,
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    if disabled:
        metadata["qualificationRequired"] = True
    return payload, metadata


@dataclass(frozen=True, slots=True)
class VisibilityCorpus:
    payload: bytes
    brushes_enabled: bool
    source_rows: int
    ordered_rows: int
    stride: int
    source_rate: int
    step_rate: int
    maximum_records: int
    maximum_mask_bytes: int
    dictionary_count: int
    dictionary_offset: int
    payload_offset: int
    payload_bytes: int
    camera_fingerprint: int
    alias_fingerprint: int
    partial_tokens: int
    hidden_tokens: int
    candidate_pixels: int
    visible_pixels: int
    mask_bytes: int
    row_payloads: tuple[bytes, ...]


def _read_alias_package(data_dir: Path) -> tuple[tuple[Path, ...], bytes, int]:
    metadata_path = data_dir / "QuakeBSPAliasAssets.json"
    metadata = json.loads(metadata_path.read_text(encoding="ascii"))
    try:
        format_metadata = metadata["format"]
        target = MESEN_TARGETS[format_metadata["mesenTarget"]]
        configured_count = format_metadata["configuredHalfbankCount"]
        maximum_bank = format_metadata["maxGsuRomBank"]
        actual_bank = format_metadata["actualMaxGsuRomBank"]
        chunk_count = format_metadata["chunkCount"]
    except (KeyError, TypeError) as error:
        raise AliasVisibilityError("QBA1 has no valid MesenCE mapping") from error
    if (
        type(configured_count) is not int
        or type(maximum_bank) is not int
        or type(actual_bank) is not int
        or type(chunk_count) is not int
        or not 0 < chunk_count <= configured_count <= target.max_alias_halfbank_count
        or maximum_bank != target.max_gsu_rom_bank
        or not 0 <= actual_bank <= maximum_bank
    ):
        raise AliasVisibilityError(
            "QBA1 storage regions exceed or disagree with the selected MesenCE mapping"
        )
    paths = tuple(
        data_dir / f"QuakeBSPAliasRuntime{index}.bin" for index in range(chunk_count)
    )
    payloads = tuple(path.read_bytes() for path in paths)
    if any(len(payload) != QAV_HALFBANK_BYTES for payload in payloads):
        raise AliasVisibilityError("QBA1 runtime chunk has the wrong size")
    package = b"".join(payloads)
    if package[:4] != b"QBA1" or len(package) < 44:
        raise AliasVisibilityError("QBA1 runtime package has an invalid header")
    camera_fingerprint = struct.unpack_from("<Q", package, 36)[0]
    return paths, package, camera_fingerprint


def _configured_map_entry(data_dir: Path) -> str:
    try:
        metadata = json.loads((data_dir / "QuakeBSPMetadata.json").read_text("ascii"))
        map_entry = str(metadata["demo"]["map_entry"])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise AliasVisibilityError(
            "configured world metadata has no BSP map"
        ) from error
    if not map_entry.startswith("maps/") or not map_entry.endswith(".bsp"):
        raise AliasVisibilityError("configured world metadata has an invalid BSP map")
    return map_entry


def _dynamic_brush_replay_supported(data_dir: Path) -> bool:
    try:
        metadata = json.loads(
            (data_dir / "QuakeBSPBrushAssets.json").read_text("ascii")
        )
        return bool(metadata["runtimeReplay"]["supported"])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise AliasVisibilityError(
            "brush asset metadata has no runtime replay capability"
        ) from error


def _world_only_enabled_payload(disabled_payload: bytes) -> bytes:
    """Mirror a brush-disabled QAV2 corpus while retaining its world visibility."""

    if len(disabled_payload) != QAV_HALFBANK_BYTES:
        raise AliasVisibilityError("QAV2 output is not one 32 KiB halfbank")
    if struct.unpack_from("<H", disabled_payload, QAV_BRUSHES_ENABLED_OFFSET) != (0,):
        raise AliasVisibilityError("world-only QAV2 source still enables brushes")
    enabled_payload = bytearray(disabled_payload)
    struct.pack_into("<H", enabled_payload, QAV_BRUSHES_ENABLED_OFFSET, 1)
    return bytes(enabled_payload)


def parse_visibility(
    payload: bytes,
    *,
    expected_brushes: bool,
    expected_camera_fingerprint: int,
    expected_alias_fingerprint: int,
) -> VisibilityCorpus:
    if len(payload) != QAV_HALFBANK_BYTES:
        raise AliasVisibilityError("QAV2 output is not one 32 KiB halfbank")
    (
        magic,
        version,
        header_bytes,
        source_rows,
        ordered_rows,
        stride,
        source_rate,
        step_rate,
        row_bytes,
        brushes_enabled,
        maximum_records,
        maximum_mask_bytes,
        dictionary_count,
        directory_offset,
        payload_offset,
        payload_bytes,
        camera_fingerprint,
        alias_fingerprint,
    ) = QAV_HEADER.unpack_from(payload)
    if (
        magic != QAV_MAGIC
        or version != QAV_VERSION
        or header_bytes != QAV_HEADER_BYTES
        or row_bytes != QAV_ROW_BYTES
        or source_rows == 0
        or ordered_rows != source_rows
        or stride != 1
        or source_rate == 0
        or step_rate != source_rate
        or maximum_records > QAV_ROW_RECORD_MASK
        or dictionary_count > QAV_DICTIONARY_MAXIMUM
        or directory_offset != QAV_HEADER_BYTES
        or payload_offset
        != directory_offset + source_rows * QAV_ROW_BYTES + dictionary_count * 2
        or payload_offset + payload_bytes > len(payload)
    ):
        raise AliasVisibilityError("QAV2 header contract is invalid")
    if bool(brushes_enabled) != expected_brushes:
        raise AliasVisibilityError("QAV2 brush mode disagrees with its output name")
    if camera_fingerprint != expected_camera_fingerprint:
        raise AliasVisibilityError("QAV2 camera identity disagrees with QBA1")
    if alias_fingerprint != expected_alias_fingerprint:
        raise AliasVisibilityError("QAV2 package identity disagrees with QBA1")

    dictionary_offset = directory_offset + source_rows * QAV_ROW_BYTES
    descriptors: list[tuple[int, int]] = []
    dictionary_records: dict[int, int] = {}
    seen_ids: set[int] = set()
    next_id = 1
    for pose in range(source_rows):
        (descriptor,) = QAV_ROW.unpack_from(
            payload, directory_offset + pose * QAV_ROW_BYTES
        )
        record_count = descriptor & QAV_ROW_RECORD_MASK
        dictionary_id = descriptor >> QAV_ROW_RECORD_BITS
        if (record_count == 0) != (dictionary_id == 0):
            raise AliasVisibilityError("QAV2 row descriptor is inconsistent")
        if dictionary_id > dictionary_count:
            raise AliasVisibilityError("QAV2 row escapes its dictionary")
        descriptors.append((dictionary_id, record_count))
        if dictionary_id == 0:
            continue
        prior = dictionary_records.setdefault(dictionary_id, record_count)
        if prior != record_count:
            raise AliasVisibilityError("QAV2 dictionary record count is ambiguous")
        if dictionary_id not in seen_ids:
            if dictionary_id != next_id:
                raise AliasVisibilityError(
                    "QAV2 dictionary IDs do not follow first occurrence order"
                )
            seen_ids.add(dictionary_id)
            next_id += 1
    if next_id != dictionary_count + 1:
        raise AliasVisibilityError("QAV2 dictionary contains an unreferenced row")

    cursor = payload_offset
    payload_end = payload_offset + payload_bytes
    dictionary_stats: dict[int, tuple[int, int, int, int, int]] = {}
    dictionary_payloads: dict[int, bytes] = {}
    unique_payloads: set[bytes] = set()
    for dictionary_id in range(1, dictionary_count + 1):
        (offset,) = struct.unpack_from(
            "<H", payload, dictionary_offset + (dictionary_id - 1) * 2
        )
        if offset != cursor:
            raise AliasVisibilityError(
                "QAV2 dictionary payloads are not tightly ordered"
            )
        row_start = cursor
        record_count = dictionary_records[dictionary_id]
        row_partial_tokens = 0
        row_hidden_tokens = 0
        row_candidate_pixels = 0
        row_visible_pixels = 0
        row_mask_bytes = 0
        tokens: set[int] = set()
        for _ in range(record_count):
            if cursor + QAV_RECORD.size > payload_end:
                raise AliasVisibilityError("QAV2 token record exceeds its payload")
            token, kind, candidates = QAV_RECORD.unpack_from(payload, cursor)
            cursor += QAV_RECORD.size
            if token in tokens or candidates == 0:
                raise AliasVisibilityError("QAV2 token record has invalid counts")
            tokens.add(token)
            row_candidate_pixels += candidates
            if kind == QAV_HIDDEN:
                row_hidden_tokens += 1
                continue
            if kind != QAV_PARTIAL:
                raise AliasVisibilityError("QAV2 token kind is invalid")
            size = (candidates + 7) // 8
            if cursor + size > payload_end:
                raise AliasVisibilityError("QAV2 visibility mask exceeds its payload")
            mask = payload[cursor : cursor + size]
            cursor += size
            visible = sum(byte.bit_count() for byte in mask)
            if visible == 0 or visible == candidates:
                raise AliasVisibilityError("QAV2 partial-token contract is invalid")
            if candidates & 7 and mask[-1] >> (candidates & 7):
                raise AliasVisibilityError("QAV2 visibility mask has nonzero tail bits")
            row_partial_tokens += 1
            row_visible_pixels += visible
            row_mask_bytes += size
        row_payload = payload[row_start:cursor]
        if row_payload in unique_payloads:
            raise AliasVisibilityError("QAV2 dictionary retains duplicate payloads")
        unique_payloads.add(row_payload)
        dictionary_payloads[dictionary_id] = row_payload
        dictionary_stats[dictionary_id] = (
            row_partial_tokens,
            row_hidden_tokens,
            row_candidate_pixels,
            row_visible_pixels,
            row_mask_bytes,
        )
    if cursor != payload_end:
        raise AliasVisibilityError("QAV2 payload has trailing or unreferenced bytes")
    if any(byte != 0xFF for byte in payload[payload_end:]):
        raise AliasVisibilityError("QAV2 halfbank padding is not canonical")

    partial_tokens = 0
    hidden_tokens = 0
    candidate_pixels = 0
    visible_pixels = 0
    mask_bytes = 0
    observed_maximum_records = 0
    observed_maximum_mask_bytes = 0
    for dictionary_id, record_count in descriptors:
        observed_maximum_records = max(observed_maximum_records, record_count)
        if dictionary_id == 0:
            continue
        partial, hidden, candidates, visible, masks = dictionary_stats[dictionary_id]
        partial_tokens += partial
        hidden_tokens += hidden
        candidate_pixels += candidates
        visible_pixels += visible
        mask_bytes += masks
        observed_maximum_mask_bytes = max(observed_maximum_mask_bytes, masks)
    if (
        observed_maximum_records != maximum_records
        or observed_maximum_mask_bytes != maximum_mask_bytes
    ):
        raise AliasVisibilityError("QAV2 declared maxima disagree with its rows")
    return VisibilityCorpus(
        payload,
        expected_brushes,
        source_rows,
        ordered_rows,
        stride,
        source_rate,
        step_rate,
        maximum_records,
        maximum_mask_bytes,
        dictionary_count,
        dictionary_offset,
        payload_offset,
        payload_bytes,
        camera_fingerprint,
        alias_fingerprint,
        partial_tokens,
        hidden_tokens,
        candidate_pixels,
        visible_pixels,
        mask_bytes,
        tuple(
            b"" if dictionary_id == 0 else dictionary_payloads[dictionary_id]
            for dictionary_id, _record_count in descriptors
        ),
    )


def _alias_location_offset(
    package: bytes, bank: int, address: int, size: int
) -> int:
    if size < 0 or len(package) % HALFBANK_BYTES:
        raise AliasVisibilityError("QBA1 package storage is malformed")
    for chunk in range(len(package) // HALFBANK_BYTES):
        chunk_bank, chunk_address = gsu_location(chunk)
        offset = address - chunk_address
        if bank == chunk_bank and 0 <= offset <= HALFBANK_BYTES - size:
            return chunk * HALFBANK_BYTES + offset
    raise AliasVisibilityError("QBA1 row pointer escapes the runtime package")


def _temporal_alias_identity_ids(
    alias_package: bytes, corpus: VisibilityCorpus
) -> tuple[int, ...]:
    """Intern exact raster-reachable QBA1/QAV2 inputs for every source row."""

    if len(alias_package) < QBA_HEADER.size:
        raise AliasVisibilityError("QBA1 runtime package is shorter than its header")
    header = QBA_HEADER.unpack_from(alias_package)
    row_count = header[3]
    row_directory_offset = header[9]
    if (
        header[0] != b"QBA1"
        or header[2] != QBA_HEADER.size
        or row_count < corpus.source_rows
        or row_directory_offset < QBA_HEADER.size
        or row_directory_offset + row_count * QBA_ROW.size > HALFBANK_BYTES
    ):
        raise AliasVisibilityError("QBA1 row-directory contract is invalid")

    identities: dict[bytes, int] = {}
    row_ids: list[int] = []
    for pose, visibility_payload in enumerate(corpus.row_payloads):
        row_offset = row_directory_offset + pose * QBA_ROW.size
        (
            dynamic_bank,
            dynamic_count,
            dynamic_address,
            group_bank,
            group_count,
            group_address,
        ) = QBA_ROW.unpack_from(alias_package, row_offset)
        dynamic_bytes = dynamic_count * QBA_STATE_BYTES
        if dynamic_bytes:
            dynamic_offset = _alias_location_offset(
                alias_package,
                dynamic_bank,
                dynamic_address,
                dynamic_bytes,
            )
            dynamic_states = alias_package[
                dynamic_offset : dynamic_offset + dynamic_bytes
            ]
        else:
            dynamic_states = b""

        identity = bytearray(struct.pack("<H", group_count))
        if group_count:
            group_offset = _alias_location_offset(
                alias_package,
                group_bank,
                group_address,
                QBA_GROUP_HEADER.size,
            )
            chunk_end = (
                group_offset // HALFBANK_BYTES + 1
            ) * HALFBANK_BYTES
            for _group in range(group_count):
                if group_offset + QBA_GROUP_HEADER.size > chunk_end:
                    raise AliasVisibilityError("QBA1 group header crosses a halfbank")
                leaf, parent, token_count = QBA_GROUP_HEADER.unpack_from(
                    alias_package, group_offset
                )
                group_offset += QBA_GROUP_HEADER.size
                token_end = group_offset + token_count
                if token_end > chunk_end:
                    raise AliasVisibilityError("QBA1 group tokens cross a halfbank")
                tokens = alias_package[group_offset:token_end]
                group_offset = token_end
                identity.extend(QBA_GROUP_HEADER.pack(leaf, parent, token_count))
                for token in tokens:
                    if token & 0x80:
                        identity.extend((0x80, token & 0x7F))
                        continue
                    state_offset = token * QBA_STATE_BYTES
                    state_end = state_offset + QBA_STATE_BYTES
                    if state_end > len(dynamic_states):
                        raise AliasVisibilityError(
                            "QBA1 group references a missing dynamic state"
                        )
                    identity.append(0)
                    identity.extend(dynamic_states[state_offset:state_end])

        identity.extend(struct.pack("<H", len(visibility_payload)))
        identity.extend(visibility_payload)
        key = bytes(identity)
        identity_id = identities.get(key)
        if identity_id is None:
            identity_id = len(identities) + 1
            if identity_id > 0xFFFF:
                raise AliasVisibilityError("temporal alias identity escapes uint16")
            identities[key] = identity_id
        row_ids.append(identity_id)
    return tuple(row_ids)


def _encode_temporal_alias_identities(
    corpus: VisibilityCorpus, row_ids: tuple[int, ...]
) -> bytes:
    if len(row_ids) != corpus.source_rows or any(
        not 0 < identity <= 0xFFFF for identity in row_ids
    ):
        raise AliasVisibilityError("temporal alias identity rows are invalid")
    return b"".join(QAV_TEMPORAL_IDENTITY_RECORD.pack(identity) for identity in row_ids)


def _export(
    executable: Path,
    pak: Path,
    data_dir: Path,
    replay_path: Path,
    output: Path,
    *,
    map_entry: str,
    brushes_enabled: bool,
    render_scale: int = 2,
    source_focal: int = 64,
) -> str:
    command = [
        str(executable),
        "--pak",
        str(pak),
        "--map",
        map_entry,
        "--data-dir",
        str(data_dir),
        "--ordered-replay",
        str(replay_path),
        "--realtime-demo",
        str(data_dir / "QuakeBSPDemoPrecise.bin"),
        "--brush-replay",
        str(data_dir / "QuakeBSPBrushReplay.bin"),
        "--alias-assets",
        str(data_dir),
        "--ordered-alias-visibility",
        str(output),
    ]
    if not brushes_enabled:
        command.append("--no-brushes")
    if render_scale == 3:
        command.extend(("--render-scale", "x3", "--visibility-source-focal", str(source_focal)))
    completed = subprocess.run(
        command,
        cwd=EXAMPLE,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=300,
    )
    expected = (
        "aliasVisibilityContract=QAV2",
        f"brushes={'enabled' if brushes_enabled else 'disabled'}",
        f"renderScale=x{render_scale}",
        f"sourceFocal={96 if render_scale == 2 else source_focal}",
    )
    if completed.returncode or any(value not in completed.stdout for value in expected):
        raise AliasVisibilityError(
            "reference alias-visibility export failed:\n" + completed.stdout
        )
    return completed.stdout.strip()


def _render_include(
    enabled: VisibilityCorpus, disabled: VisibilityCorpus, *, reuse_bytes: int
) -> bytes:
    lines = [
        "; Generated by generate_quake_alias_visibility.py; do not edit.",
        f"BSP_ALIAS_VISIBILITY_VERSION = {QAV_VERSION}",
        f"BSP_ALIAS_VISIBILITY_SOURCE_ROW_COUNT = {enabled.source_rows}",
        f"BSP_ALIAS_VISIBILITY_ORDERED_ROW_COUNT = {enabled.ordered_rows}",
        f"BSP_ALIAS_VISIBILITY_POSE_STRIDE = {enabled.stride}",
        f"BSP_ALIAS_VISIBILITY_HEADER_BYTES = {QAV_HEADER_BYTES}",
        f"BSP_ALIAS_VISIBILITY_ROW_RECORD_BYTES = {QAV_ROW_BYTES}",
        f"BSP_ALIAS_VISIBILITY_TOKEN_RECORD_BYTES = {QAV_RECORD.size}",
        f"BSP_ALIAS_VISIBILITY_ROW_RECORD_BITS = {QAV_ROW_RECORD_BITS}",
        f"BSP_ALIAS_VISIBILITY_ROW_RECORD_MASK = ${QAV_ROW_RECORD_MASK:04X}",
        f"BSP_ALIAS_VISIBILITY_PARTIAL = {QAV_PARTIAL}",
        f"BSP_ALIAS_VISIBILITY_HIDDEN = {QAV_HIDDEN}",
        "BSP_ALIAS_VISIBILITY_ENABLED_BANK = $6F",
        "BSP_ALIAS_VISIBILITY_ENABLED_ADDRESS = $0000",
        "BSP_ALIAS_VISIBILITY_DISABLED_BANK = $6F",
        "BSP_ALIAS_VISIBILITY_DISABLED_ADDRESS = $8000",
        f"BSP_ALIAS_VISIBILITY_DIRECTORY_OFFSET = ${QAV_HEADER_BYTES:04X}",
        "BSP_ALIAS_VISIBILITY_DICTIONARY_OFFSET = "
        "BSP_ALIAS_VISIBILITY_DIRECTORY_OFFSET + "
        "BSP_ALIAS_VISIBILITY_SOURCE_ROW_COUNT * "
        "BSP_ALIAS_VISIBILITY_ROW_RECORD_BYTES",
        "BSP_ALIAS_TEMPORAL_IDENTITY_RECORD_BYTES = "
        f"{QAV_TEMPORAL_IDENTITY_RECORD.size}",
        "BSP_ALIAS_PREDECESSOR_REUSE_WORD_BYTES = "
        f"{QAV_PREDECESSOR_REUSE_WORD.size}",
        f"BSP_ALIAS_PREDECESSOR_REUSE_BYTES = {reuse_bytes}",
        "BSP_ALIAS_PREDECESSOR_REUSE_POSE_COUNT = "
        f"{enabled.source_rows}",
        "BSP_ALIAS_VISIBILITY_MAX_DICTIONARY_ROWS = "
        f"{max(enabled.dictionary_count, disabled.dictionary_count)}",
        "BSP_ALIAS_VISIBILITY_MAX_RECORDS = "
        f"{max(enabled.maximum_records, disabled.maximum_records)}",
        "BSP_ALIAS_VISIBILITY_MAX_MASK_BYTES = "
        f"{max(enabled.maximum_mask_bytes, disabled.maximum_mask_bytes)}",
        "",
    ]
    return "\n".join(lines).encode("ascii")


def _render_assembly() -> bytes:
    return (
        "; Generated by generate_quake_alias_visibility.py; do not edit.\n"
        '.segment "BSP_ALIAS_VISIBILITY_ENABLED"\n'
        "QuakeBSPAliasVisibilityEnabled:\n"
        f'        .incbin "Data/{ENABLED_NAME.name}"\n'
        "QuakeBSPAliasVisibilityEnabledEnd:\n"
        ".assert QuakeBSPAliasVisibilityEnabledEnd - "
        "QuakeBSPAliasVisibilityEnabled = $8000, error, "
        '"Enabled alias visibility must fill one halfbank"\n'
        ".assert __BSP_ALIAS_VISIBILITY_ENABLED_LOAD__ = $6F0000, lderror, "
        '"Enabled alias visibility moved"\n\n'
        '.segment "BSP_ALIAS_VISIBILITY_DISABLED"\n'
        "QuakeBSPAliasVisibilityDisabled:\n"
        f'        .incbin "Data/{DISABLED_NAME.name}"\n'
        "QuakeBSPAliasVisibilityDisabledEnd:\n"
        ".assert QuakeBSPAliasVisibilityDisabledEnd - "
        "QuakeBSPAliasVisibilityDisabled = $8000, error, "
        '"Disabled alias visibility must fill one halfbank"\n'
        ".assert __BSP_ALIAS_VISIBILITY_DISABLED_LOAD__ = $6F8000, lderror, "
        '"Disabled alias visibility moved"\n'
        '\n.segment "BSP_ALIAS_TEMPORAL"\n'
        "QuakeBSPAliasTemporalEnabled:\n"
        f'        .incbin "Data/{TEMPORAL_ENABLED_NAME.name}"\n'
        "QuakeBSPAliasTemporalDisabled:\n"
        f'        .incbin "Data/{TEMPORAL_DISABLED_NAME.name}"\n'
        "QuakeBSPAliasPredecessor:\n"
        f'        .incbin "Data/{PREDECESSOR_NAME.name}"\n'
        ".assert __BSP_ALIAS_TEMPORAL_LOAD__ + __BSP_ALIAS_TEMPORAL_SIZE__ <= $F88000, "
        'lderror, "CPU alias reuse tables exceed demo-clock halfbank"\n'
    ).encode("ascii")


def build_outputs(
    pak: Path,
    data_dir: Path = DEFAULT_OUTPUT,
    predecessor_contract: Path = DEFAULT_PREDECESSOR_REUSE_CONTRACT,
    *, config: Path | None = None, codec: str = "auto",
    workers: int | None = None, reference: Path | None = None,
) -> tuple[dict[Path, bytes], dict[str, Any]]:
    workers = physical_core_count() if workers is None else workers
    if workers < 1:
        raise ValueError("visibility workers must be positive")
    alias_paths, alias_package, camera_fingerprint = _read_alias_package(data_dir)
    alias_fingerprint = fnv1a64(alias_package)
    map_entry = _configured_map_entry(data_dir)
    dynamic_brush_supported = _dynamic_brush_replay_supported(data_dir)
    executable = reference.resolve() if reference is not None else Path(str(reference_build.build()["executable"]))
    if not executable.is_file():
        raise ValueError("missing visibility reference executable: " + str(executable))
    with tempfile.TemporaryDirectory(prefix="quake-alias-visibility-") as temporary:
        root = Path(temporary)
        full_rate_replay = ordered_replay.build_replay(data_dir, stride=1, workers=workers)
        full_rate_payload = ordered_replay.encode_replay(full_rate_replay)
        full_rate_path = root / "QuakeBSPFullRateReplay.bin"
        full_rate_path.write_bytes(full_rate_payload)
        enabled_path = root / ENABLED_NAME
        disabled_path = root / DISABLED_NAME
        if dynamic_brush_supported:
            _export(
                executable,
                pak,
                data_dir,
                full_rate_path,
                enabled_path,
                map_entry=map_entry,
                brushes_enabled=True,
            )
        _export(
            executable,
            pak,
            data_dir,
            full_rate_path,
            disabled_path,
            map_entry=map_entry,
            brushes_enabled=False,
        )
        disabled_payload = disabled_path.read_bytes()
        if dynamic_brush_supported:
            enabled_payload = enabled_path.read_bytes()
        else:
            enabled_payload = _world_only_enabled_payload(disabled_payload)
        enabled = parse_visibility(
            enabled_payload,
            expected_brushes=True,
            expected_camera_fingerprint=camera_fingerprint,
            expected_alias_fingerprint=alias_fingerprint,
        )
        disabled = parse_visibility(
            disabled_payload,
            expected_brushes=False,
            expected_camera_fingerprint=camera_fingerprint,
            expected_alias_fingerprint=alias_fingerprint,
        )
        archive_outputs, archive_metadata, projection_corpora = projection_archive.build_projection_archive(
            executable=executable, pak=pak, data=data_dir, temporary=root,
            focal=configured_warp_source_focal(config), codec=codec, enabled=enabled, disabled=disabled,
            workers=workers)
    if (
        enabled.source_rows,
        enabled.ordered_rows,
        enabled.stride,
        enabled.source_rate,
        enabled.step_rate,
    ) != (
        disabled.source_rows,
        disabled.ordered_rows,
        disabled.stride,
        disabled.source_rate,
        disabled.step_rate,
    ):
        raise AliasVisibilityError("enabled/disabled QAV2 schedules disagree")

    predecessor_reuse, predecessor_reuse_metadata = (
        _load_predecessor_reuse_contract(
            predecessor_contract,
            data_dir,
            expected_rows=enabled.source_rows,
        )
    )

    enabled_identity_ids = projection_archive.joint_temporal_ids(alias_package, projection_corpora, brushes=True)
    disabled_identity_ids = projection_archive.joint_temporal_ids(alias_package, projection_corpora, brushes=False)
    enabled_temporal = _encode_temporal_alias_identities(
        enabled, enabled_identity_ids
    )
    disabled_temporal = _encode_temporal_alias_identities(
        disabled, disabled_identity_ids
    )
    enabled_output = enabled.payload
    disabled_output = disabled.payload

    def describe(
        corpus: VisibilityCorpus, payload: bytes, identity_ids: tuple[int, ...]
    ) -> dict[str, Any]:
        identity_bytes = b"".join(
            QAV_TEMPORAL_IDENTITY_RECORD.pack(identity)
            for identity in identity_ids
        )
        return {
            "brushesEnabled": corpus.brushes_enabled,
            "partialTokens": corpus.partial_tokens,
            "hiddenTokens": corpus.hidden_tokens,
            "candidatePixelsInNonvisibleTokens": corpus.candidate_pixels,
            "visiblePixelsInNonvisibleTokens": corpus.visible_pixels,
            "maskBytes": corpus.mask_bytes,
            "dictionaryRows": corpus.dictionary_count,
            "dictionaryBytes": corpus.dictionary_count * 2,
            "payloadBytes": corpus.payload_bytes,
            "usedBytes": corpus.payload_offset + corpus.payload_bytes,
            "maximumRecordsPerRow": corpus.maximum_records,
            "maximumMaskBytesPerRow": corpus.maximum_mask_bytes,
            "temporalIdentity": {
                "file": (TEMPORAL_ENABLED_NAME if corpus.brushes_enabled else TEMPORAL_DISABLED_NAME).name,
                "recordBytes": QAV_TEMPORAL_IDENTITY_RECORD.size,
                "rowCount": len(identity_ids),
                "uniqueCount": len(set(identity_ids)),
                "sha256": hashlib.sha256(identity_bytes).hexdigest(),
            },
            "sha256": hashlib.sha256(payload).hexdigest(),
        }

    metadata: dict[str, Any] = {
        "schema": "quake-bsp-alias-visibility-v2",
        "version": QAV_VERSION,
        "archive": archive_metadata,
        "contract": {
            "depth": "alias origin Q6 depth is strictly nearer than final packed opaque Q6 depth; opaque wins ties",
            "ordering": "QBA1 far-to-near token order; masks retain that token's opaque destination-texel order",
            "fastPath": "fully visible tokens have no record; fully hidden tokens skip projection; only partial tokens consume bitmasks",
            "deduplication": "exact row payloads use first-occurrence dictionary IDs; source-row lookup remains direct",
            "temporalIdentity": "joint first-occurrence IDs bind exact painter groups, raster-reachable QBA1 states and all three projection row payloads; camera/focal and brush guards remain mandatory",
            "predecessorReuse": "a hash-bound canonical ORDER 30HZ bitset proves exact equality with the circular preceding presentation",
        },
        "schedule": {
            "sourceRows": enabled.source_rows,
            "orderedRows": enabled.ordered_rows,
            "poseStride": enabled.stride,
            "sourceRateHz": enabled.source_rate,
            "stepRateHz": enabled.step_rate,
        },
        "identity": {
            "mapEntry": map_entry,
            "cameraFnv1a64": f"{camera_fingerprint:016x}",
            "aliasPackageFnv1a64": f"{alias_fingerprint:016x}",
            "aliasPackageSha256": hashlib.sha256(alias_package).hexdigest(),
            "aliasChunks": [path.name for path in alias_paths],
            "orderedReplaySha256": hashlib.sha256(
                (data_dir / "QuakeBSPOrderedReplay.bin").read_bytes()
            ).hexdigest(),
            "fullRateReplaySha256": hashlib.sha256(full_rate_payload).hexdigest(),
            "brushReplaySha256": hashlib.sha256(
                (data_dir / "QuakeBSPBrushReplay.bin").read_bytes()
            ).hexdigest(),
        },
        "predecessorReuse": {
            "file": PREDECESSOR_NAME.name,
            "wordBytes": QAV_PREDECESSOR_REUSE_WORD.size,
            **predecessor_reuse_metadata,
        },
        "variant": {
            "dynamicBrushReplaySupported": dynamic_brush_supported,
            "enabledCorpus": (
                "reference-brush-aware"
                if dynamic_brush_supported
                else "world-only mirror; alternate-map brushes are disabled"
            ),
        },
        "format": {
            "halfbankBytes": QAV_HALFBANK_BYTES,
            "headerBytes": QAV_HEADER_BYTES,
            "rowRecordBytes": QAV_ROW_BYTES,
            "rowRecordBits": QAV_ROW_RECORD_BITS,
            "tokenRecordBytes": QAV_RECORD.size,
            "partialKind": QAV_PARTIAL,
            "hiddenKind": QAV_HIDDEN,
            "temporalStorage": "CPU demo-clock halfbank, separate from QAV2",
            "temporalIdentityRecordBytes": QAV_TEMPORAL_IDENTITY_RECORD.size,
            "predecessorReuseWordBytes": QAV_PREDECESSOR_REUSE_WORD.size,
            "enabledPhysicalHalfbank": ENABLED_PHYSICAL_HALFBANK,
            "disabledPhysicalHalfbank": DISABLED_PHYSICAL_HALFBANK,
        },
        "enabled": describe(enabled, enabled_output, enabled_identity_ids),
        "disabled": describe(disabled, disabled_output, disabled_identity_ids),
    }
    outputs = {
        ENABLED_NAME: enabled_output,
        DISABLED_NAME: disabled_output,
        TEMPORAL_ENABLED_NAME: enabled_temporal,
        TEMPORAL_DISABLED_NAME: disabled_temporal,
        PREDECESSOR_NAME: predecessor_reuse,
        INCLUDE_NAME: _render_include(
            enabled, disabled, reuse_bytes=len(predecessor_reuse)
        ) + (f"BSP_ALIAS_ARCHIVE_VERSION = 3\n"
             f"BSP_ALIAS_ARCHIVE_WARP_FOCAL = {configured_warp_source_focal(config)}\n"
             f"BSP_ALIAS_ARCHIVE_MAX_DECODED_BYTES = {archive_metadata['maximumDecodedBytes']}\n"
             f"BSP_ALIAS_ARCHIVE_PAYLOAD_BYTES = {archive_metadata['payloadBytes']}\n").encode("ascii"),
        ASSEMBLY_NAME: projection_archive.assembly(),
        METADATA_NAME: (json.dumps(metadata, indent=2, sort_keys=True) + "\n").encode(
            "ascii"
        ),
    }
    outputs.update(archive_outputs)
    return outputs, metadata


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pak", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--codec", choices=("auto", "raw"), default="auto")
    parser.add_argument("--workers", type=int, default=physical_core_count())
    parser.add_argument("--reference", type=Path, help="prebuilt reference; avoids shared build output in parallel focal preparation")
    parser.add_argument(
        "--predecessor-reuse-contract",
        type=Path,
        default=DEFAULT_PREDECESSOR_REUSE_CONTRACT,
    )
    parser.add_argument("--check", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    started = time.monotonic()
    args = parse_args(argv)
    try:
        outputs, metadata = build_outputs(
            bsp_tools.locate_quake_pak(args.pak).resolve(),
            args.output.resolve(),
            args.predecessor_reuse_contract.resolve(),
            config=args.config, codec=args.codec, workers=args.workers, reference=args.reference,
        )
        sync_generated_outputs(
            outputs,
            args.output,
            check=args.check,
            owned_families=OWNED_OUTPUTS,
        )
    except (AliasVisibilityError, GeneratedOutputError, OSError, RuntimeError, ValueError) as error:
        raise SystemExit(
            f"Quake alias visibility generation failed:\n{error}\nelapsed={time.monotonic() - started:.3f}s"
        ) from None
    action = "verified" if args.check else "generated"
    print(
        f"{action} {metadata['schedule']['orderedRows']} ordered alias visibility "
        f"rows: enabled={metadata['enabled']['payloadBytes']} payload bytes, "
        f"disabled={metadata['disabled']['payloadBytes']} payload bytes; "
        f"sharedArchive={metadata['archive']['payloadBytes']} bytes ({metadata['archive']['codec']}); "
        f"predecessorReuse={metadata['predecessorReuse']['reusablePoseCount']} poses; "
        f"elapsed={time.monotonic() - started:.3f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
