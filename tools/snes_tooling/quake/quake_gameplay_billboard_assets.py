"""Verify portable production QBA1 assets for the SNES gameplay renderer."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path, PurePosixPath

from snes_tooling.quake.quake_gameplay_production_aliases import (
    HEADER,
    SPRITE,
    verified_mdl_density,
)


def identity(payload):
    return dict(bytes=len(payload), sha256=sha256(payload).hexdigest())


def read_production_bundle(index_path):
    """Read and verify the complete portable closure before exporting any map."""
    index_path = Path(index_path).resolve()
    index_payload = index_path.read_bytes()
    index = json.loads(index_payload)
    if index.get("schema") != "quake-production-gameplay-aliases-v1":
        raise ValueError("an explicit production gameplay alias bundle is required")
    maps = index.get("maps", [])
    if len({row["map"] for row in maps}) != len(maps) or not maps:
        raise ValueError("production alias bundle contains duplicate or missing maps")
    payloads = {}
    for row in index["payloads"]:
        name = row["file"]
        relative = PurePosixPath(name)
        if (
            relative.is_absolute()
            or any(part in ("", ".", "..") for part in relative.parts)
            or "\\" in name
            or ":" in name
            or name in payloads
        ):
            raise ValueError("production alias payload path is invalid or duplicated")
        path = (index_path.parent / name).resolve()
        if not path.is_relative_to(index_path.parent):
            raise ValueError("production alias payload escapes its bundle")
        blob = path.read_bytes()
        if identity(blob) != {key: row[key] for key in ("bytes", "sha256")}:
            raise ValueError("production alias payload size/SHA-256 mismatch: " + name)
        payloads[name] = blob
    return dict(index=index, identity=identity(index_payload), payloads=payloads)


def alias_payloads_for_map(bundle, manifest):
    """Return flat map files and a render contract for export_map's existing closure."""
    name = manifest["map"]
    row = next((item for item in bundle["index"]["maps"] if item["map"] == name), None)
    if row is None:
        raise ValueError("production alias bundle omits gameplay map " + name)
    source = manifest["source"]
    if (
        row["pakSha256"] != source["pakSha256"]
        or row["bspSha256"] != source["bspSha256"]
    ):
        raise ValueError("production alias bundle belongs to another PAK/BSP")
    prefix = name + "/"
    outputs = {
        Path(key[len(prefix) :]): blob
        for key, blob in bundle["payloads"].items()
        if key.startswith(prefix)
    }
    if any(path.parent != Path(".") for path in outputs):
        raise ValueError(
            "production aliases must be flat within the gameplay map directory"
        )
    aliases = json.loads(outputs[Path("QuakeBSPAliasAssets.json")])
    gameplay = json.loads(outputs[Path("QuakeBSPQuakeCGameplay.json")])
    # Compiler metadata has integer callback keys; JSON manifests encode them
    # as strings. Compare the serialized input domain, not Python key types.
    if gameplay != json.loads(json.dumps(manifest["metadata"]["gameplay"])):
        raise ValueError(
            "production alias roster/gameplay metadata differs from the live map"
        )
    packed = row.get("packedWorld", {})
    if packed.get("schema") != "quake-gameplay-production-world-v1" or not packed.get(
        "files"
    ):
        raise ValueError(
            "default gameplay requires the complete production packed world and brushes"
        )
    for filename in packed["files"]:
        if Path(filename) not in outputs:
            raise ValueError("production packed-world payload is missing: " + filename)
    for filename, field in (
        ("QuakeBSPMetadata.json", "worldMetadata"),
        ("QuakeBSPBrushAssets.json", "brushMetadata"),
    ):
        if identity(outputs[Path(filename)]) != packed[field]:
            raise ValueError("production packed-world metadata identity differs")
    if aliases["schema"] != "quake-level-alias-assets-v1":
        raise ValueError("gameplay requires the standalone production alias schema")
    expected_chunks = aliases["format"]["chunkCount"]
    chunks = {
        path.name: blob
        for path, blob in outputs.items()
        if path.name.startswith("QuakeBSPAliasRuntime") and path.suffix == ".bin"
    }
    if len(chunks) != expected_chunks:
        raise ValueError("production alias bundle has a wrong chunk count")
    for filename, expected in aliases["outputs"].items():
        if identity(chunks[filename]) != expected:
            raise ValueError(
                "production alias chunk differs from its original metadata"
            )
    sprites = []
    if row["spriteCount"]:
        data = b"".join(
            chunks[f"QuakeBSPAliasRuntime{i}.bin"] for i in range(expected_chunks)
        )
        header = HEADER.unpack_from(data)
        if header[4] != row["spriteCount"]:
            raise ValueError("production alias sprite count disagrees with its bundle")
        sprites = [
            SPRITE.unpack_from(data, header[10] + i * SPRITE.size)
            for i in range(header[4])
        ]
    density = verified_mdl_density(aliases, sprites)
    if row.get("mdlWorldUnitsPerTexel") != density:
        raise ValueError("production MDL density differs from its bound metadata")
    contract = dict(
        schema="quake-gameplay-production-billboards-v1",
        referenceData=".",
        sourceBundle=bundle["identity"],
        sourcePackage=bundle["index"]["source"],
        mode=row["mode"],
        spriteCount=row["spriteCount"],
        rows=row["rows"],
        actors=row["actors"],
        frames=row["frames"],
        viewsPerFrame=row["viewsPerFrame"],
        **({"singleViewModels": row["singleViewModels"]} if "singleViewModels" in row else {}),
        mdlWorldUnitsPerTexel=density,
        packedWorld=packed,
        cameraPositionUnits=row.get("cameraPositionUnits", 16),
        aliasMetadata=identity(outputs[Path("QuakeBSPAliasAssets.json")]),
        palette=identity(outputs[Path("QuakeBSPTexturePalette.bin")]),
    )
    return outputs, contract
