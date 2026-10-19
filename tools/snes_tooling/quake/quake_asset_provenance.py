"""Hash-bound generation recipes and qualification receipts; never asset payloads."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import struct
from pathlib import Path
from typing import Any, Mapping


SCHEMA = "quake-asset-generation-receipt-v1"
RECEIPT_PATH = Path("src/snes_quake/asset-generation.json")
RECIPE_SCHEMA = "quake-lightmap-generation-recipe-v1"


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("ascii")
    ).hexdigest()


def identity(path: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    return {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}


def content_identity(record: Mapping[str, Any]) -> dict[str, Any]:
    size, sha = record.get("bytes"), record.get("sha256")
    if (
        type(size) is not int
        or size < 0
        or not isinstance(sha, str)
        or not re.fullmatch(r"[0-9a-f]{64}", sha)
    ):
        raise ValueError("generation receipt contains an invalid file identity")
    return {"bytes": size, "sha256": sha}


def write_json(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def compiler_configuration(build_root: Path) -> dict[str, Any]:
    """Retain compiler/math choices while dropping checkout paths and parallelism."""
    cache_paths = sorted(build_root.glob("build-*/CMakeCache.txt"))
    if len(cache_paths) != 1:
        raise ValueError(
            "generation provenance requires exactly one native CMake build"
        )
    build = cache_paths[0].parent
    compilers = sorted(build.glob("CMakeFiles/*/CMakeCXXCompiler.cmake"))
    if len(compilers) != 1:
        raise ValueError(
            "generation provenance requires the actual C++ compiler configuration"
        )
    definitions = dict(
        re.findall(
            r'set\((CMAKE_CXX_COMPILER_(?:ID|VERSION|ARCHITECTURE_ID)) "([^"]*)"\)',
            compilers[0].read_text("utf-8"),
        )
    )
    if not definitions.get("CMAKE_CXX_COMPILER_ID") or not definitions.get(
        "CMAKE_CXX_COMPILER_VERSION"
    ):
        raise ValueError("generation provenance is missing compiler identity/version")
    flags = {}
    for key, value in re.findall(
        r"^(CMAKE_(?:C|CXX)_FLAGS(?:_RELEASE)?):STRING=(.*)$",
        cache_paths[0].read_text("utf-8"),
        re.M,
    ):
        flags[key] = re.sub(r"(?:^|\s)/MP\d*\b", "", value).strip()
    return {
        "host": platform.system(),
        "architecture": platform.machine().lower(),
        "compiler": definitions,
        "flags": flags,
    }


def dependency_identities(vcpkg: Path, tools: Mapping[str, Path]) -> dict[str, Any]:
    """Bind shared libraries and distinct static archives beside the native tools."""
    triplet = "x64-windows" if platform.system() == "Windows" else "x64-linux"
    installed = vcpkg / "installed"
    status = installed / "vcpkg/status"
    packages = {}
    for stanza in status.read_text("utf-8").split("\n\n"):
        fields = dict(
            line.split(": ", 1) for line in stanza.splitlines() if ": " in line
        )
        if (
            fields.get("Package") in {"embree", "tbb"}
            and fields.get("Architecture") == triplet
            and "Version" in fields
        ):
            packages[fields["Package"]] = {
                key: fields[key] for key in ("Version", "Port-Version") if key in fields
            }
    if set(packages) != {"embree", "tbb"}:
        raise ValueError(
            "generation provenance is missing Embree/TBB dependency versions"
        )
    libraries = {}
    static_archives = {}
    directories: dict[Path, list[str]] = {}
    for name, path in sorted(tools.items()):
        directories.setdefault(path.parent, []).append(f"tools/{name}")
    directories.setdefault(installed / triplet / "lib", []).append("vcpkg/lib")
    for directory in sorted(directories):
        if directory.is_dir():
            for path in sorted(directory.iterdir()):
                if path.is_file() and (
                    path.suffix.lower() == ".dll"
                    or path.name.startswith(("libembree", "libtbb"))
                ):
                    record = identity(path)
                    if path.suffix.lower() == ".a":
                        for origin in directories[directory]:
                            static_archives[f"{origin}/{path.name}"] = record
                        continue
                    if path.name in libraries and libraries[path.name] != record:
                        raise ValueError(f"conflicting runtime dependency: {path.name}")
                    libraries[path.name] = record
    if not libraries and not static_archives:
        raise ValueError(
            "generation provenance is missing native dependency identities"
        )
    result = {"packages": packages, "libraries": libraries}
    if static_archives:
        result["staticArchives"] = static_archives
    return result


def lightmap_generation(
    receipt: Mapping[str, Any],
    *,
    bsp: Path,
    build_root: Path,
    vcpkg: Path,
    tools: Mapping[str, Path],
    producer: Path,
    vcpkg_commit: str,
    isa: str,
) -> dict[str, Any]:
    marker = f"SNES Quake Embree ISA: {isa}"
    if marker not in (build_root / "map/light.log").read_text("utf-8"):
        raise ValueError("lighting tool did not confirm the effective Embree ISA")
    inputs = {
        name: content_identity(record) for name, record in receipt["inputs"].items()
    }
    recipe = {
        "schema": RECIPE_SCHEMA,
        "inputs": inputs,
        "configuration": content_identity(receipt["configuration"]),
        "generator": identity(producer),
        "ericwCommit": receipt["ericwCommit"],
        "vcpkgCommit": vcpkg_commit,
        "tools": {name: identity(path) for name, path in sorted(tools.items())},
        "dependencies": dependency_identities(vcpkg, tools),
        "toolchain": compiler_configuration(build_root),
        "embreeIsa": isa,
        "commands": {
            name: command[1:] for name, command in receipt["commands"].items()
        },
        "settings": {
            key: receipt["settings"][key]
            for key in (
                "mapThreads",
                "maxWorldLightmapSamples",
                "maxInlineModelLightmapSamples",
            )
        },
    }
    payload = bsp.read_bytes()
    offset, count = struct.unpack_from("<ii", payload, 4 + 8 * 8)
    if offset < 0 or count < 0 or offset + count > len(payload):
        raise ValueError("invalid BSP lightmap lump")
    return {
        "recipe": recipe,
        "recipeSha256": digest(recipe),
        "outputs": {
            "bsp": identity(bsp),
            "lightmaps": {
                "bytes": count,
                "sha256": hashlib.sha256(payload[offset : offset + count]).hexdigest(),
            },
        },
    }


def source_identities(root: Path) -> dict[str, Any]:
    """Bind every released producer/configuration/patch, excluding generated data."""
    result = {}
    for folder in ("tools", "config", "third_party/patches", "src/reference_renderer"):
        for current, directories, files in os.walk(root / folder):
            directories[:] = sorted(set(directories) - {"vcpkg", "__pycache__", ".git"})
            for name in sorted(files):
                path = Path(current) / name
                if path.suffix in {
                    ".py",
                    ".json",
                    ".patch",
                    ".cpp",
                    ".hpp",
                    ".h",
                    ".txt",
                    ".bin",
                }:
                    result[path.relative_to(root).as_posix()] = identity(path)
    return result


def recipe_differences(expected: Any, current: Any, prefix: str = "") -> list[str]:
    if isinstance(expected, dict) and isinstance(current, dict):
        return [
            difference
            for key in sorted(expected.keys() | current.keys())
            for difference in recipe_differences(
                expected.get(key), current.get(key), f"{prefix}.{key}".strip(".")
            )
        ]
    return [] if expected == current else [prefix or "recipe"]


def begin_generation(root: Path, generation: Mapping[str, Any], reason: str) -> None:
    """Invalidate local reuse before generators or assembly can fail partway."""
    path = root / RECEIPT_PATH
    try:
        previous = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        previous = {}
    if not isinstance(previous, dict):
        previous = {}
    previous_recipe = previous.get(
        "previousRecipe", previous.get("generation", {}).get("recipe", {})
    )
    write_json(path, {
        "schema": SCHEMA,
        "generation": generation,
        "previousRecipe": previous_recipe,
        "qualification": {"status": "requires-requalification", "reason": reason},
    })


def record_generation(
    root: Path,
    contract: Mapping[str, Any],
    generation: Mapping[str, Any],
    *,
    rom: Path | None = None,
) -> dict[str, Any]:
    """Publish renewed qualification only after the caller verifies exact outputs."""
    if generation.get("recipeSha256") != digest(generation.get("recipe")):
        raise ValueError("generation recipe fingerprint is stale")
    path = root / RECEIPT_PATH
    previous = json.loads(path.read_text("utf-8")) if path.is_file() else None
    qualified = contract.get("lightmapGeneration", {})
    if qualified and qualified.get("recipeSha256") != digest(qualified.get("recipe")):
        raise ValueError("qualified generation recipe fingerprint is stale")
    previous_recipe = (
        previous.get("previousRecipe", previous.get("generation", {}).get("recipe", {}))
        if previous else {}
    )
    changes = recipe_differences(previous_recipe or qualified.get("recipe", {}), generation["recipe"])
    document = {
        "schema": SCHEMA,
        "generation": generation,
        "producerInputs": source_identities(root),
        "configuration": content_identity(contract["configuration"]),
        "outputs": {
            "assetSetSha256": contract["assetSetSha256"],
            "files": contract["files"],
        },
        "qualification": {
            "status": "rom-byte-equivalence" if rom else "asset-byte-equivalence",
            "generationRecipeChanged": bool(changes),
            "changedFields": changes,
            "evidence": contract["defaultFeatureCoverage"],
            "qualifiedRecipeSha256": qualified.get("recipeSha256"),
            "rom": identity(rom) if rom else None,
        },
    }
    write_json(path, document)
    return {
        "path": RECEIPT_PATH.as_posix(),
        **identity(path),
        "qualification": document["qualification"]["status"],
        "recipeSha256": generation["recipeSha256"],
        "recipeChanged": bool(changes),
    }


def require_local_generation(root: Path, contract: Mapping[str, Any]) -> dict[str, Any]:
    """Local reuse must retain the same producers, outputs and qualified receipt."""
    path = root / RECEIPT_PATH
    try:
        receipt = json.loads(path.read_text("utf-8"))
        generation = receipt["generation"]
        valid = (
            receipt.get("schema") == SCHEMA
            and generation["recipeSha256"] == digest(generation["recipe"])
            and receipt["producerInputs"] == source_identities(root)
            and receipt["configuration"] == content_identity(contract["configuration"])
            and receipt["outputs"]
            == {
                "assetSetSha256": contract["assetSetSha256"],
                "files": contract["files"],
            }
            and receipt["qualification"]["status"]
            in {"asset-byte-equivalence", "rom-byte-equivalence"}
            and receipt["qualification"]["evidence"] == contract["defaultFeatureCoverage"]
            and receipt["qualification"].get("qualifiedRecipeSha256")
            == contract.get("lightmapGeneration", {}).get("recipeSha256")
        )
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise RuntimeError(
            "local generation receipt is missing or invalid; regenerate and requalify assets"
        ) from error
    if not valid:
        raise RuntimeError("generation inputs changed; regenerate and requalify assets")
    return generation
