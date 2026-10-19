"""Bound immutable identities for Quake reference-renderer launches."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import struct
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from snes_tooling.quake.quake_demo import discover_demo_map
from snes_tooling.quake.quake_rom_config import CONFIG_SCHEMA, configured_alias_halfbank_count


SCHEMA = "quake-reference-launch-v1"
COMPARISON_SCHEMA = "quake-launch-current-path-comparison-v1"
ALIAS_CHUNK_BYTES = 32 * 1024
MAX_MANIFEST_BYTES = 256 * 1024


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _resolved_file(path: Path) -> tuple[Path, bytes]:
    resolved = path.resolve(strict=True)
    if not resolved.is_file():
        raise ValueError(f"launch input is not a regular file: {resolved}")
    return resolved, resolved.read_bytes()


def _file_record(path: Path, payload: bytes) -> dict[str, Any]:
    return {
        "kind": "file",
        "path": str(path),
        "bytes": len(payload),
        "sha256": _sha256(payload),
    }


def file_identity(path: Path) -> dict[str, Any]:
    """Capture one regular file without retaining its potentially large bytes."""

    resolved, payload = _resolved_file(path)
    return _file_record(resolved, payload)


def _pak_entries(payload: bytes, path: Path) -> dict[str, tuple[int, int]]:
    if len(payload) < 12 or payload[:4] != b"PACK":
        raise ValueError(f"{path} is not a Quake PAK archive")
    directory_offset, directory_bytes = struct.unpack_from("<II", payload, 4)
    if (
        directory_bytes % 64
        or directory_offset > len(payload)
        or directory_bytes > len(payload) - directory_offset
    ):
        raise ValueError(f"{path} has an invalid Quake PAK directory")
    entries: dict[str, tuple[int, int]] = {}
    for offset in range(directory_offset, directory_offset + directory_bytes, 64):
        raw_name, entry_offset, entry_bytes = struct.unpack_from(
            "<56sII", payload, offset
        )
        name = raw_name.split(b"\0", 1)[0].decode("ascii").lower()
        if entry_offset > len(payload) or entry_bytes > len(payload) - entry_offset:
            raise ValueError(f"PAK entry {name!r} escapes {path}")
        entries[name] = (entry_offset, entry_bytes)
    return entries


def _pak_entry(
    payload: bytes,
    entries: Mapping[str, tuple[int, int]],
    entry: str,
    path: Path,
) -> bytes:
    try:
        offset, byte_count = entries[entry.lower()]
    except KeyError as error:
        raise FileNotFoundError(f"{entry!r} is missing from {path}") from error
    return payload[offset : offset + byte_count]


def _pak_entry_record(path: Path, entry: str, payload: bytes) -> dict[str, Any]:
    return {
        "kind": "pakEntry",
        "pakPath": str(path),
        "entry": entry,
        "bytes": len(payload),
        "sha256": _sha256(payload),
    }


def _require_ordered_bsp_binding(data_dir: Path, map_entry: str, bsp_payload: bytes) -> None:
    metadata = data_dir / "QuakeBSPMetadata.json"
    source = json.loads(metadata.read_text(encoding="utf-8"))["source"]
    if (source.get("pak_entry", "").lower() != map_entry.lower() or
            source.get("bsp_sha256") != _sha256(bsp_payload)):
        raise ValueError(
            f"ordered BSP binding mismatch for {map_entry}: the selected PAK map does not match "
            f"{metadata}; use the PAK that generated these packed assets"
        )


def require_ordered_bsp_binding(pak: Path, data_dir: Path, map_entry: str) -> None:
    """Reject a different map revision before launching an ordered playback matrix."""
    path, payload = _resolved_file(pak)
    bsp = _pak_entry(payload, _pak_entries(payload, path), map_entry, path)
    _require_ordered_bsp_binding(data_dir, map_entry, bsp)


def _configured_demo(
    config_path: Path,
    config_payload: bytes,
    pak_path: Path,
    pak_payload: bytes,
    pak_entries: Mapping[str, tuple[int, int]],
) -> tuple[dict[str, Any], bytes, str]:
    try:
        config = json.loads(config_payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"ROM build config is invalid JSON: {config_path}") from error
    if not isinstance(config, dict) or config.get("schema") != CONFIG_SCHEMA:
        raise ValueError(f"ROM build config schema must be {CONFIG_SCHEMA!r}")
    demo = config.get("demo")
    if not isinstance(demo, dict):
        raise ValueError("ROM build config demo must be an object")
    source = demo.get("source")
    locator = demo.get("path")
    if source not in {"file", "pak"}:
        raise ValueError("ROM build demo source must be 'file' or 'pak'")
    if not isinstance(locator, str) or not locator.strip():
        raise ValueError("ROM build demo path must be a non-empty string")
    locator = locator.strip().replace("\\", "/")
    if source == "pak":
        candidate = Path(locator)
        if (
            candidate.is_absolute()
            or locator.startswith("/")
            or (len(locator) >= 2 and locator[1] == ":")
            or ".." in candidate.parts
        ):
            raise ValueError("ROM build PAK demo path must be a safe relative entry")
        demo_payload = _pak_entry(pak_payload, pak_entries, locator, pak_path)
        identity = _pak_entry_record(pak_path, locator, demo_payload)
    else:
        demo_path = Path(locator).expanduser()
        if not demo_path.is_absolute():
            demo_path = config_path.parent / demo_path
        resolved_demo, demo_payload = _resolved_file(demo_path)
        identity = _file_record(resolved_demo, demo_payload)
    map_entry = discover_demo_map(demo_payload)
    identity.update(
        {
            "source": source,
            "locator": locator,
            "mapEntry": map_entry,
        }
    )
    return identity, demo_payload, map_entry


def _alias_asset_bundle(directory: Path, maximum_chunk_count: int) -> dict[str, Any]:
    resolved = directory.resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError(f"alias asset path is not a directory: {resolved}")
    first_path, first = _resolved_file(resolved / "QuakeBSPAliasRuntime0.bin")
    if len(first) != ALIAS_CHUNK_BYTES or first[:4] != b"QBA1" or len(first) < 20:
        raise ValueError("invalid QBA1 alias asset header")
    chunk_count = int.from_bytes(first[18:20], "little")
    if not 1 <= chunk_count <= maximum_chunk_count:
        raise ValueError("QBA1 alias chunk count exceeds the selected MesenCE mapping")
    payloads = [first]
    files = [_file_record(first_path, first)]
    for index in range(1, chunk_count):
        path, payload = _resolved_file(resolved / f"QuakeBSPAliasRuntime{index}.bin")
        if len(payload) != ALIAS_CHUNK_BYTES:
            raise ValueError(f"QBA1 alias chunk has the wrong size: {path}")
        payloads.append(payload)
        files.append(_file_record(path, payload))
    return {
        "directory": str(resolved),
        "chunkCount": chunk_count,
        "bytes": sum(len(payload) for payload in payloads),
        "sha256": _sha256(b"".join(payloads)),
        "files": files,
    }


def capture_reference_launch_inputs(
    *,
    executable: Path,
    rom_config: Path,
    pak: Path,
    camera_track: Path,
    brush_replay: Path,
    alias_assets: Path,
    data_dir: Path,
    ordered_replay: Path | None,
    brushes_enabled: bool,
    external_bsp_replay: Path | None = None,
    sound_replay: Path | None = None,
    particle_replay: Path | None = None,
) -> tuple[dict[str, Any], str]:
    """Capture every bounded reference input before process creation."""

    executable_path, executable_payload = _resolved_file(executable)
    config_path, config_payload = _resolved_file(rom_config)
    pak_path, pak_payload = _resolved_file(pak)
    pak_entries = _pak_entries(pak_payload, pak_path)
    selected_demo, _demo_payload, map_entry = _configured_demo(
        config_path, config_payload, pak_path, pak_payload, pak_entries
    )
    bsp_payload = _pak_entry(pak_payload, pak_entries, map_entry, pak_path)
    if ordered_replay is not None:
        _require_ordered_bsp_binding(data_dir, map_entry, bsp_payload)
    visibility = {
        "selectedBrushesEnabled": brushes_enabled,
        "activeCorpus": "brushesEnabled" if brushes_enabled else "brushesDisabled",
        "metadata": file_identity(data_dir / "QuakeBSPAliasVisibility.json"),
        "corpora": {
            "brushesEnabled": {
                **file_identity(data_dir / "QuakeBSPAliasVisibilityEnabled.bin"),
                "brushesEnabled": True,
            },
            "brushesDisabled": {
                **file_identity(data_dir / "QuakeBSPAliasVisibilityDisabled.bin"),
                "brushesEnabled": False,
            },
        },
    }
    inputs: dict[str, Any] = {
        "executable": _file_record(executable_path, executable_payload),
        "romConfig": _file_record(config_path, config_payload),
        "selectedDemo": selected_demo,
        "pak": _file_record(pak_path, pak_payload),
        "derivedBsp": _pak_entry_record(pak_path, map_entry, bsp_payload),
        "cameraTrack": file_identity(camera_track),
        "brushReplay": file_identity(brush_replay),
        "externalBspReplay": (
            file_identity(external_bsp_replay)
            if external_bsp_replay is not None
            else None
        ),
        "soundReplay": (
            file_identity(sound_replay) if sound_replay is not None else None
        ),
        "particleReplay": file_identity(particle_replay) if particle_replay is not None else None,
        "orderedReplay": (
            file_identity(ordered_replay) if ordered_replay is not None else None
        ),
        "aliasAssets": _alias_asset_bundle(
            alias_assets, configured_alias_halfbank_count(config_path)
        ),
        "aliasVisibility": visibility,
    }
    return inputs, map_entry


def reference_launch_manifest(
    *,
    inputs: Mapping[str, Any],
    pid: int,
    command: list[str],
    configuration: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind a running PID and exact command/config to pre-launch input hashes."""

    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise ValueError("reference launch PID must be a positive integer")
    return {
        "schema": SCHEMA,
        "launchIdentity": {
            "pid": pid,
            "command": list(command),
            "configuration": copy.deepcopy(dict(configuration)),
            "inputs": copy.deepcopy(dict(inputs)),
        },
    }


def _compare_file(record: Mapping[str, Any]) -> dict[str, Any]:
    path = Path(str(record["path"]))
    result: dict[str, Any] = {"kind": "file", "path": str(path)}
    try:
        resolved, payload = _resolved_file(path)
    except (FileNotFoundError, ValueError, OSError) as error:
        result.update({"exists": False, "matchesLaunch": False, "error": str(error)})
        return result
    result.update(
        {
            "path": str(resolved),
            "exists": True,
            "bytes": len(payload),
            "sha256": _sha256(payload),
        }
    )
    result["matchesLaunch"] = result["bytes"] == record.get("bytes") and result[
        "sha256"
    ] == record.get("sha256")
    return result


def _compare_pak_entry(record: Mapping[str, Any]) -> dict[str, Any]:
    pak_path = Path(str(record["pakPath"]))
    entry = str(record["entry"])
    result: dict[str, Any] = {
        "kind": "pakEntry",
        "pakPath": str(pak_path),
        "entry": entry,
    }
    try:
        resolved, pak_payload = _resolved_file(pak_path)
        payload = _pak_entry(
            pak_payload, _pak_entries(pak_payload, resolved), entry, resolved
        )
    except (FileNotFoundError, ValueError, OSError) as error:
        result.update({"exists": False, "matchesLaunch": False, "error": str(error)})
        return result
    result.update(
        {
            "pakPath": str(resolved),
            "exists": True,
            "bytes": len(payload),
            "sha256": _sha256(payload),
        }
    )
    result["matchesLaunch"] = result["bytes"] == record.get("bytes") and result[
        "sha256"
    ] == record.get("sha256")
    return result


def _identity_records(
    value: Any, prefix: str = "inputs"
) -> list[tuple[str, Mapping[str, Any]]]:
    if isinstance(value, Mapping):
        kind = value.get("kind")
        if kind in {"file", "pakEntry"}:
            return [(prefix, value)]
        records: list[tuple[str, Mapping[str, Any]]] = []
        for name, child in value.items():
            records.extend(_identity_records(child, f"{prefix}.{name}"))
        return records
    if isinstance(value, list):
        records = []
        for index, child in enumerate(value):
            records.extend(_identity_records(child, f"{prefix}[{index}]"))
        return records
    return []


def compare_current_paths(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Recheck paths while leaving the recorded launch identity untouched."""

    if manifest.get("schema") != SCHEMA:
        raise ValueError(f"launch manifest schema must be {SCHEMA!r}")
    launch = manifest.get("launchIdentity")
    if not isinstance(launch, Mapping) or not isinstance(launch.get("inputs"), Mapping):
        raise ValueError("launch manifest has no immutable input identity")
    comparisons = {
        name: (
            _compare_file(record)
            if record["kind"] == "file"
            else _compare_pak_entry(record)
        )
        for name, record in _identity_records(launch["inputs"])
    }
    return {
        "schema": COMPARISON_SCHEMA,
        "launchPid": launch.get("pid"),
        "allMatch": bool(comparisons)
        and all(item["matchesLaunch"] for item in comparisons.values()),
        "identities": comparisons,
    }


def manifest_with_current_comparison(
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a status view without changing or relabeling launch identity."""

    result = copy.deepcopy(dict(manifest))
    result["currentPathComparison"] = compare_current_paths(manifest)
    return result


def atomic_write_manifest(path: Path, manifest: Mapping[str, Any]) -> None:
    """Durably replace a JSON manifest without exposing a partial document."""

    destination = path.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    encoded = payload.encode("utf-8")
    if len(encoded) > MAX_MANIFEST_BYTES:
        raise ValueError(
            f"launch manifest is {len(encoded)} bytes; maximum is {MAX_MANIFEST_BYTES}"
        )
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
            delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary_path.replace(destination)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
