#!/usr/bin/env python3
"""Generate and build one hash-bound Quake ROM configuration."""

from __future__ import annotations

from snes_tooling import Workspace

import argparse
from contextlib import ExitStack
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from typing import Any, Sequence


TOOLS = Workspace.discover().path('tools', 'snes_tooling', 'quake')
EXAMPLE = Workspace.discover().quake_example
OUTPUT = Workspace.discover().root / "out/snes_quake"
WORKSPACE = Workspace.discover().root
SHARED_TOOLS = WORKSPACE / "tools/commands/shared"


import snes_tooling.quake.generate_snes_example_assets as assets  # noqa: E402
from snes_tooling.shared.snes_example_build import (  # noqa: E402
    build_snes_example,
    project_layout,
    default_libsfx,
)


DEFAULT_LIBSFX = default_libsfx(WORKSPACE)
DEFAULT_RECEIPT = project_layout(EXAMPLE).build_dir / "quake.variant-build.json"


def fingerprint(path: Path) -> dict[str, object]:
    payload = path.read_bytes()
    return {
        "path": str(path.resolve()),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def source_state() -> dict[str, object]:
    manifest = WORKSPACE / "public-source.json"
    if manifest.is_file() and not (WORKSPACE / ".git").exists():
        payload = manifest.read_bytes()
        document = json.loads(payload)
        if document.get("schema") != "quake-playable-source-v1":
            raise ValueError("unrecognized public source manifest")
        changes = []
        for name, expected in document["files"].items():
            path = (WORKSPACE / name).resolve()
            if (not path.is_relative_to(WORKSPACE) or not path.is_file()
                    or hashlib.sha256(path.read_bytes()).hexdigest() != expected):
                changes.append(name)
        return {"commit": hashlib.sha256(payload).hexdigest(), "trackedChanges": changes,
                "clean": not changes}
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=WORKSPACE,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=WORKSPACE,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout.splitlines()
    return {"commit": commit, "trackedChanges": status, "clean": not status}


def atomic_write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def prepare_playable_source_cache(config: Path, libsfx: Path, *, cpu_assembly_only=False) -> dict[str, Any]:
    """Capture a local profile only for a registered, separately staged source."""
    from snes_tooling.quake.quake_playable_maps import MAP_NAMES, config_for
    from snes_tooling.quake.quake_playable_validation import capture_module_manifest
    from snes_tooling.quake.quake_playable_source_budget import prepare_source_budget
    from snes_tooling.quake.quake_playable_walk_hull import (
        COMPACT_POINT_MAPS, INLINE_WALK_MAPS, prepare_compact_point_hull, prepare_inline_walk_hull,
    )
    from snes_tooling.shared.snes_example_build import run_example_source_generator

    names = [name for name in MAP_NAMES if config.resolve() ==
             (WORKSPACE / "config/snes_quake" / config_for(name)).resolve()]
    if len(names) != 1:
        raise ValueError("playable source cache requires a registered map config")
    expected = WORKSPACE / "out/snes_quake/targets" / f"playable-{names[0]}-source/src/snes_quake"
    if EXAMPLE.resolve() != expected.resolve():
        raise ValueError("playable source cache requires its registered staged target")
    manifest = json.loads((EXAMPLE / "snes-project.json").read_bytes())
    if manifest.get("cacheKernelManifest") != "GSUCacheKernels-playable.json":
        raise ValueError("playable source cache requires a target-local manifest binding")
    # Content generation is complete. Refresh assembly sources before the
    # independent disposable assembly/link/geometry preflight captures offsets.
    budget = prepare_source_budget(EXAMPLE)
    if names[0] in INLINE_WALK_MAPS:
        prepare_inline_walk_hull(EXAMPLE)
    elif names[0] in COMPACT_POINT_MAPS:
        prepare_compact_point_hull(EXAMPLE)
    run_example_source_generator(EXAMPLE)
    if cpu_assembly_only:
        return capture_module_manifest(EXAMPLE, libsfx, name="quake", cpu_assembly_only=True)
    return dict(capture_module_manifest(EXAMPLE, libsfx, name="quake"), sourceShaderBudget=budget)


def build_variant(args: argparse.Namespace) -> dict[str, Any]:
    started = time.monotonic()
    config, config_sha256 = assets.validated_config_identity(args.config)
    from snes_tooling.quake.quake_rom_config import configured_target
    if configured_target(config)["mode"] != "fly":
        raise ValueError("variant builds require a map configuration")
    initial_source = source_state()
    if not args.allow_dirty and not initial_source["clean"]:
        raise RuntimeError(
            "variant build requires a clean tracked worktree; use --allow-dirty "
            "only for local iteration"
        )
    from snes_tooling.quake.quake_asset_preflight import require_reference_profile_sources
    require_reference_profile_sources(config)
    if EXAMPLE.resolve() == (WORKSPACE / "src/snes_quake").resolve():
        raise RuntimeError(
            "Map variants require a staged example. Use build_quake_playable.py "
            "to apply the map linker layout and stage generated assets."
        )
    if getattr(args, "reuse_assets", False):
        from snes_tooling.quake.quake_asset_preflight import require_asset_chain_receipt
        require_asset_chain_receipt(config)
        completed = 0
    else:
        completed = assets.run(
            check=False,
            pak=args.pak.resolve() if args.pak is not None else None,
            source_pak=getattr(args, "source_pak", None),
            config=config,
            config_sha256=config_sha256,
        )
    assets.require_config_identity(config, config_sha256)
    asset_receipt_path = assets.DATA / assets.ASSET_CHAIN_RECEIPT
    asset_receipt = json.loads(asset_receipt_path.read_text(encoding="utf-8"))
    if asset_receipt.get("config", {}).get("sha256") != config_sha256:
        raise RuntimeError("asset-chain receipt is not bound to the selected config")

    cache_profile = None
    if getattr(args, "cpu_assembly_only", False):
        preflight = prepare_playable_source_cache(config, args.libsfx.resolve(), cpu_assembly_only=True)
        if source_state() != initial_source:
            raise RuntimeError("source changed during CPU assembly preflight")
        receipt = dict(preflight, schema="quake-playable-module-cpu-assembly-v1",
                       source=initial_source, elapsedSeconds=round(time.monotonic() - started, 3))
        atomic_write_json(args.receipt.resolve(), receipt)
        return receipt
    if getattr(args, "playable_source_cache", False):
        cache_profile = prepare_playable_source_cache(config, args.libsfx.resolve())

    with ExitStack() as lease:
        build = build_snes_example(EXAMPLE, args.libsfx.resolve(), "quake", skip_asset_generation=True)
    assets.require_config_identity(config, config_sha256)
    if (
        fingerprint(asset_receipt_path)["sha256"]
        != hashlib.sha256(assets.asset_chain_receipt(config, config_sha256)).hexdigest()
    ):
        raise RuntimeError("asset outputs changed after receipt publication")

    standard_freshness = Path(str(build["freshnessReceipt"]))
    rom = Path(str(build["rom"]))
    receipt = {
        "schema": "quake-bsp-variant-build-v1",
        "source": initial_source,
        "config": fingerprint(config),
        "selection": asset_receipt["selection"],
        "assetGeneration": {
            "generatorCount": completed,
            "receipt": fingerprint(asset_receipt_path),
            "outputAggregateSha256": asset_receipt["outputs"]["aggregateSha256"],
        },
        "build": {
            "rom": fingerprint(rom),
            "freshnessReceipt": fingerprint(standard_freshness),
            "elapsedSeconds": build["elapsedSeconds"],
        },
        "elapsedSeconds": round(time.monotonic() - started, 3),
    }
    if cache_profile is not None:
        receipt["cacheProfileCapture"] = cache_profile
    atomic_write_json(args.receipt.resolve(), receipt)
    return receipt


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True, help="map configuration to build")
    parser.add_argument("--pak", type=Path)
    parser.add_argument("--source-pak", type=Path, help="original PAK used before configured BSP preparation")
    parser.add_argument("--reuse-assets", action="store_true", help="require matching staged asset receipt")
    parser.add_argument("--playable-source-cache", action="store_true",
                        help="capture a validated local cache profile for a registered playable source")
    parser.add_argument("--cpu-assembly-only", action="store_true",
                        help="assemble a registered playable source without producing a ROM")
    parser.add_argument("--libsfx", type=Path, default=DEFAULT_LIBSFX)
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="permit tracked changes at startup for local iteration",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    started = time.monotonic()
    try:
        args = parse_args(argv)
        receipt = build_variant(args)
    except KeyboardInterrupt:
        print(
            f"Quake variant build interrupted after {time.monotonic() - started:.3f}s",
            file=sys.stderr,
        )
        return 130
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        print(
            f"error: {error}; elapsed={time.monotonic() - started:.3f}s",
            file=sys.stderr,
        )
        return 1
    if args.cpu_assembly_only:
        print(f"Playable CPU assembly passed: receipt={args.receipt.resolve()} "
              f"elapsed={receipt['elapsedSeconds']:.3f}s")
        return 0
    print(
        "Quake variant build passed: "
        f"map={receipt['selection']['mapEntry']} "
        f"romSha256={receipt['build']['rom']['sha256']} "
        f"receipt={args.receipt.resolve()} "
        f"elapsed={receipt['elapsedSeconds']:.3f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
