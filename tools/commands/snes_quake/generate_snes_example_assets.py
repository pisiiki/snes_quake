#!/usr/bin/env python3
"""Generate or verify the complete configured Quake SNES asset chain."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

from workspace_paths import shared_tools_root, workspace_root
from typing import Sequence


TOOLS = Path(__file__).resolve().parent
SHARED_TOOLS = shared_tools_root(__file__)
if str(SHARED_TOOLS) not in sys.path:
    sys.path.insert(0, str(SHARED_TOOLS))

from snes_tooling.shared.generated_outputs import sync_generated_outputs  # noqa: E402
import quake_mesen_mapping  # noqa: E402
from quake_rom_config import (  # noqa: E402
    BSP_SOURCE_ERICW_MAP,
    DEFAULT_CONFIG,
    configured_alias_sprites,
    configured_bsp_build,
    configured_demo_source,
    configured_mesen_target,
    configured_playback_sample_rate,
    configured_sky,
    configured_soundtrack,
)

EXAMPLE = workspace_root(__file__) / "src/snes_quake"
WORKSPACE = workspace_root(__file__)
DATA = EXAMPLE / "Data"
ASSET_CHAIN_RECEIPT = Path("QuakeBSPAssetChain.json")
COMPOSED_CACHE_GENERATOR = "generate_quake_bsp_composed_cache.py"
ORDERED_REPLAY_GENERATOR = "generate_quake_bsp_ordered_replay.py"
PACKET_ORACLE_GENERATOR = "quake_bsp_packet_oracle.py"
SKY_ASSET_GENERATOR = "generate_quake_bsp_sky_assets.py"
TURBULENCE_ASSET_GENERATOR = "generate_quake_bsp_turbulence_assets.py"
CONFIG_GENERATORS = {
    "generate_quake_bsp.py",
    "generate_quake_brush_replay.py",
    "generate_quake_alias_billboards.py",
    "generate_quake_reference_external_bsp_replay.py",
    "generate_quake_reference_sound_replay.py",
    "generate_quake_snes_soundtrack.py",
    SKY_ASSET_GENERATOR,
}
GENERATORS = (
    "generate_quake_bsp.py",
    PACKET_ORACLE_GENERATOR,
    ORDERED_REPLAY_GENERATOR,
    "generate_quake_brush_replay.py",
    "generate_quake_alias_billboards.py",
    "generate_quake_reference_external_bsp_replay.py",
    "generate_quake_reference_sound_replay.py",
    "generate_quake_snes_soundtrack.py",
    "generate_quake_alias_visibility.py",
    "generate_quake_monster_cameras.py",
    COMPOSED_CACHE_GENERATOR,
    SKY_ASSET_GENERATOR,
    TURBULENCE_ASSET_GENERATOR,
)


class AssetGenerationInterrupted(KeyboardInterrupt):
    """Carry deterministic progress when the user interrupts the asset chain."""

    def __init__(self, generator: str, completed: int) -> None:
        super().__init__(generator)
        self.generator = generator
        self.completed = completed


def _fingerprint(path: Path) -> dict[str, object]:
    payload = path.read_bytes()
    return {
        "path": path.relative_to(DATA).as_posix(),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def asset_chain_receipt(config: Path, config_sha256: str) -> bytes:
    """Bind the selected config to every published Quake asset output."""

    config_payload = config.read_bytes()
    if hashlib.sha256(config_payload).hexdigest() != config_sha256:
        raise RuntimeError("ROM build config changed before receipt publication")
    try:
        config_locator = config.relative_to(EXAMPLE).as_posix()
        config_external = False
    except ValueError:
        try:
            config_locator = config.relative_to(WORKSPACE).as_posix()
            config_external = False
        except ValueError:
            config_locator = config.name
            config_external = True

    source = configured_demo_source(config)
    alias_sprites = configured_alias_sprites(config)
    soundtrack = configured_soundtrack(config)
    sky = configured_sky(config)
    world_metadata = json.loads(
        (DATA / "QuakeBSPMetadata.json").read_text(encoding="utf-8")
    )
    mesen_mapping = quake_mesen_mapping.build_contract(
        config, DATA / "QuakeBSPAliasAssets.json"
    )
    try:
        map_entry = str(world_metadata["demo"]["map_entry"])
        generated_demo = str(world_metadata["demo"]["locator"])
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError("generated world metadata has no demo identity") from error
    if generated_demo != source.locator:
        raise RuntimeError(
            "generated world metadata belongs to a different configured demo"
        )

    files = tuple(
        _fingerprint(path)
        for path in sorted(DATA.glob("QuakeBSP*"), key=lambda item: item.name)
        if path.is_file() and path.name != ASSET_CHAIN_RECEIPT.name
    )
    if not files:
        raise RuntimeError("Quake asset chain produced no outputs")
    aggregate = hashlib.sha256()
    for record in files:
        aggregate.update(str(record["path"]).encode("utf-8"))
        aggregate.update(int(record["bytes"]).to_bytes(8, "little"))
        aggregate.update(bytes.fromhex(str(record["sha256"])))

    receipt = {
        "schema": "quake-bsp-asset-chain-v1",
        "config": {
            "path": config_locator,
            "external": config_external,
            "bytes": len(config_payload),
            "sha256": config_sha256,
        },
        "selection": {
            "bspBuild": {
                "source": configured_bsp_build(config).source,
            },
            "demoSource": source.kind,
            "demoLocator": source.locator,
            "mapEntry": map_entry,
            "playbackSampleRateHz": configured_playback_sample_rate(config),
            "mesenTarget": configured_mesen_target(config).name,
            "aliasHalfbankCount": alias_sprites.halfbank_count,
            "aliasMdlWorldUnitsPerTexel": (
                alias_sprites.mdl_world_units_per_texel
            ),
            "sound": {
                "enabled": soundtrack.enabled,
                "sampleRateHz": soundtrack.sample_rate_hz,
                "volume": soundtrack.volume,
            },
            "sky": {"enabled": sky.enabled},
        },
        "mesenMapping": mesen_mapping,
        "outputs": {
            "fileCount": len(files),
            "aggregateSha256": aggregate.hexdigest(),
            "files": files,
        },
    }
    return (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8")


def validated_config_identity(config: Path | None = None) -> tuple[Path, str]:
    """Validate and fingerprint the one config consumed by the whole chain."""

    path = (config or DEFAULT_CONFIG).resolve()
    payload = path.read_bytes()
    configured_demo_source(path)
    configured_playback_sample_rate(path)
    configured_soundtrack(path)
    configured_sky(path)
    configured_mesen_target(path)
    configured_alias_sprites(path)
    configured_bsp_build(path)
    digest = hashlib.sha256(payload).hexdigest()
    require_config_identity(path, digest)
    return path, digest


def receipt_bound_config() -> Path | None:
    """Resolve the config that owns existing outputs for a no-argument check."""

    receipt_path = DATA / ASSET_CHAIN_RECEIPT
    if not receipt_path.is_file():
        return None
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        config = receipt["config"]
        locator = str(config["path"])
        external = bool(config["external"])
        expected_sha256 = str(config["sha256"])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError(
            "asset-chain receipt has an invalid config binding"
        ) from error
    if receipt.get("schema") != "quake-bsp-asset-chain-v1":
        raise RuntimeError("asset-chain receipt schema is unsupported")
    if external:
        raise RuntimeError(
            "asset-chain receipt uses an external config; pass --config explicitly"
        )
    example_candidate = (EXAMPLE / locator).resolve()
    workspace_candidate = (WORKSPACE / locator).resolve()
    candidate = (
        example_candidate if example_candidate.is_file() else workspace_candidate
    )
    workspace = WORKSPACE.resolve()
    example = EXAMPLE.resolve()
    if workspace not in candidate.parents and example not in candidate.parents:
        raise RuntimeError("asset-chain receipt config escapes the workspace")
    if not candidate.is_file():
        raise RuntimeError(f"asset-chain receipt config is missing: {candidate}")
    if hashlib.sha256(candidate.read_bytes()).hexdigest() != expected_sha256:
        raise RuntimeError("asset-chain receipt config hash is stale")
    return candidate


def require_config_identity(config: Path, expected_sha256: str) -> None:
    try:
        current_sha256 = hashlib.sha256(config.read_bytes()).hexdigest()
    except OSError as error:
        raise RuntimeError(
            f"ROM build config became unreadable during asset generation: {config}"
        ) from error
    if current_sha256 != expected_sha256:
        raise RuntimeError(
            "ROM build config changed during asset generation; rerun the command "
            f"with a stable config: {config}"
        )


def command_for(
    generator: str,
    *,
    check: bool,
    pak: Path | None = None,
    config: Path | None = None,
) -> list[str]:
    command = [sys.executable, str(TOOLS / generator)]
    if generator == PACKET_ORACLE_GENERATOR:
        command.append("--check" if check else "--write")
        return command
    if pak is not None and generator not in {
        COMPOSED_CACHE_GENERATOR,
        ORDERED_REPLAY_GENERATOR,
        SKY_ASSET_GENERATOR,
        TURBULENCE_ASSET_GENERATOR,
    }:
        command.extend(("--pak", str(pak)))
    if config is not None and generator in CONFIG_GENERATORS:
        command.extend(("--config", str(config)))
    if generator == ORDERED_REPLAY_GENERATOR:
        command.append("--include-full-rate")
    if check:
        command.append("--check")
    return command


def run(
    *,
    check: bool,
    pak: Path | None = None,
    config: Path,
    config_sha256: str,
) -> int:
    if pak is None and configured_bsp_build(config).source == BSP_SOURCE_ERICW_MAP:
        # Every generator must consume the same configured map, including the
        # visibility-profile consumers that reject the original shipping BSP.
        import build_quake_modern_bsp
        from quake_bsp_assets import locate_quake_pak

        arguments = build_quake_modern_bsp.parse_args(
            ["--pak", str(locate_quake_pak(None)), "--config", str(config)]
        )
        print("Preparing configured modern BSP", flush=True)
        build_quake_modern_bsp.build(arguments)
        pak = arguments.output_pak.resolve()
    completed = 0
    for index, generator in enumerate(GENERATORS, start=1):
        require_config_identity(config, config_sha256)
        command = command_for(generator, check=check, pak=pak, config=config)
        print(f"[{index}/{len(GENERATORS)}] {generator}", flush=True)
        try:
            result = subprocess.run(
                command,
                cwd=workspace_root(__file__) / "src/snes_quake",
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
        except KeyboardInterrupt:
            raise AssetGenerationInterrupted(generator, completed) from None
        if result.returncode:
            raise RuntimeError(
                f"{generator} failed with exit {result.returncode}:\n{result.stdout}"
            )
        completed += 1
        if result.stdout:
            print(result.stdout.rstrip(), flush=True)
        require_config_identity(config, config_sha256)
    sync_generated_outputs(
        {ASSET_CHAIN_RECEIPT: asset_chain_receipt(config, config_sha256)},
        DATA,
        check=check,
    )
    return completed


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pak", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--check", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    started = time.monotonic()
    args = parse_args(argv)
    try:
        requested_config = args.config
        if args.check and requested_config is None:
            requested_config = receipt_bound_config()
        config, config_sha256 = validated_config_identity(requested_config)
        completed = run(
            check=args.check,
            pak=args.pak.resolve() if args.pak is not None else None,
            config=config,
            config_sha256=config_sha256,
        )
    except KeyboardInterrupt as error:
        completed = getattr(error, "completed", 0)
        active = getattr(error, "generator", "preflight")
        print(
            f"Quake SNES asset chain interrupted: completed={completed}/"
            f"{len(GENERATORS)} active={active} "
            f"elapsed={time.monotonic() - started:.3f}s",
            file=sys.stderr,
        )
        return 130
    except (OSError, RuntimeError, ValueError) as error:
        print(
            f"error: {error}; elapsed={time.monotonic() - started:.3f}s",
            file=sys.stderr,
        )
        return 1
    action = "verified" if args.check else "generated"
    print(
        f"Quake SNES asset chain {action}: generators={completed} "
        f"config={config} configSha256={config_sha256} "
        f"elapsed={time.monotonic() - started:.3f}s",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
