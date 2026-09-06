#!/usr/bin/env python3
"""Generate planar MDL and IDSP billboards for the configured Quake demo."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from workspace_paths import shared_tools_root, workspace_root


TOOLS = Path(__file__).resolve().parent
SHARED_TOOLS = shared_tools_root(__file__)
for dependency in (TOOLS, SHARED_TOOLS):
    if str(dependency) not in sys.path:
        sys.path.insert(0, str(dependency))

from snes_tooling.shared.generated_outputs import (  # noqa: E402
    GeneratedOutputError,
    OwnedFileFamily,
    sync_generated_outputs,
)
import generate_quake_bsp as bsp_tools  # noqa: E402
from quake_alias_billboards import build_alias_assets  # noqa: E402
from quake_rom_config import DEFAULT_CONFIG  # noqa: E402


DEFAULT_OUTPUT = workspace_root(__file__) / "src/snes_quake/Data"
METADATA_NAME = Path("QuakeBSPAliasAssets.json")
INCLUDE_NAME = Path("QuakeBSPAliasAssets.i")
ASSEMBLY_NAME = Path("QuakeBSPAliasAssets.s")
OWNED_OUTPUTS = (
    OwnedFileFamily(prefix="QuakeBSPAliasRuntime", suffix=".bin", numbered=True),
    OwnedFileFamily(prefix="QuakeBSPAliasAssets", suffix=".json"),
    OwnedFileFamily(prefix="QuakeBSPAliasAssets", suffix=".i"),
    OwnedFileFamily(prefix="QuakeBSPAliasAssets", suffix=".s"),
)


def build_outputs(
    pak: Path, config: Path = DEFAULT_CONFIG
) -> tuple[dict[Path, bytes], dict[str, object]]:
    assets = build_alias_assets(pak, config_path=config)
    outputs = {
        Path(f"QuakeBSPAliasRuntime{index}.bin"): payload
        for index, payload in enumerate(assets.chunks)
    }
    outputs[INCLUDE_NAME] = assets.include
    outputs[ASSEMBLY_NAME] = assets.assembly
    outputs[METADATA_NAME] = (
        json.dumps(assets.metadata, indent=2, sort_keys=True) + "\n"
    ).encode("ascii")
    return outputs, assets.metadata


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pak", type=Path)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    started = time.monotonic()
    args = parse_args(argv)
    outputs, metadata = build_outputs(
        bsp_tools.locate_quake_pak(args.pak), args.config.resolve()
    )
    try:
        sync_generated_outputs(
            outputs,
            args.output,
            check=args.check,
            owned_families=OWNED_OUTPUTS,
        )
    except GeneratedOutputError as error:
        raise SystemExit(f"generated Quake alias assets are stale:\n{error}") from None
    action = "verified" if args.check else "generated"
    mdl_count = sum(model.get("kind") == "mdl" for model in metadata["models"])
    effect_count = sum(model.get("kind") == "spr" for model in metadata["models"])
    print(
        f"{action} {metadata['timeline']['assetRowCount']} alias rows "
        f"({metadata['timeline']['rowCount']} demo + "
        f"{metadata['timeline']['flyRowCount']} fly), "
        f"{mdl_count} MDLs + {effect_count} IDSP effects / "
        f"{metadata['residency']['generatedVariantCount']} projected -> "
        f"{metadata['coverage']['variantCount']} cartridge frame-view sprites, "
        f"{metadata['staticStateCount']} static states in "
        f"{metadata['format']['chunkCount']} halfbanks; "
        f"elapsed={time.monotonic() - started:.3f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
