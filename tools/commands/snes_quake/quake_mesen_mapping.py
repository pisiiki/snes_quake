"""Build and validate the Quake MesenCE GSU-ROM mapping contract."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from quake_rom_config import (
    DEFAULT_CONFIG,
    MESENCE_NIGHTLY_TARGET,
    MESEN_TARGETS,
    configured_alias_halfbank_count,
    configured_mesen_target,
)


CONTRACT_SCHEMA = "quake-mesence-mapping-v1"
UPSTREAM_REPOSITORY = "https://github.com/nesdev-org/MesenCE.git"
UPSTREAM_COMMIT = "091ff784182c13712deef068c94dc54020b7caf2"


def target_capabilities() -> dict[str, dict[str, Any]]:
    """Return the upstream emulator capability used by the hardware-safe build."""

    nightly = MESEN_TARGETS[MESENCE_NIGHTLY_TARGET]
    return {
        nightly.name: {
            "ordinary": True,
            "maxAliasHalfbankCount": nightly.max_alias_halfbank_count,
            "maxGsuRomBank": nightly.max_gsu_rom_bank,
            "emulator": {
                "repository": UPSTREAM_REPOSITORY,
                "commit": UPSTREAM_COMMIT,
            },
        },
    }


def build_contract(
    config_path: Path,
    alias_metadata_path: Path,
) -> dict[str, Any]:
    """Bind one generated QBA1 package to its selected MesenCE capability."""

    target = configured_mesen_target(config_path)
    halfbanks = configured_alias_halfbank_count(config_path)
    try:
        metadata = json.loads(alias_metadata_path.read_text(encoding="utf-8"))
        mapping = metadata["format"]
        actual_bank = mapping["actualMaxGsuRomBank"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("alias metadata has no MesenCE mapping contract") from error
    expected = {
        "mesenTarget": target.name,
        "configuredHalfbankCount": halfbanks,
        "maxGsuRomBank": target.max_gsu_rom_bank,
    }
    if not isinstance(mapping, dict) or any(
        mapping.get(name) != value for name, value in expected.items()
    ):
        raise ValueError("alias metadata disagrees with the selected MesenCE target")
    if (
        type(actual_bank) is not int
        or actual_bank < 0
        or actual_bank > target.max_gsu_rom_bank
    ):
        raise ValueError("alias metadata exceeds the selected MesenCE target")
    return {
        "schema": CONTRACT_SCHEMA,
        "selectedTarget": target.name,
        "configuredAliasHalfbankCount": halfbanks,
        "maximumGsuRomBank": target.max_gsu_rom_bank,
        "actualMaximumGsuRomBank": actual_bank,
        "targets": target_capabilities(),
    }


def validate_contract(
    contract: object,
    config_path: Path,
) -> dict[str, Any]:
    """Validate mapping metadata before a standalone release build publishes it."""

    target = configured_mesen_target(config_path)
    halfbanks = configured_alias_halfbank_count(config_path)
    if not isinstance(contract, dict):
        raise ValueError("MesenCE mapping contract must be an object")
    expected = {
        "schema": CONTRACT_SCHEMA,
        "selectedTarget": target.name,
        "configuredAliasHalfbankCount": halfbanks,
        "maximumGsuRomBank": target.max_gsu_rom_bank,
        "targets": target_capabilities(),
    }
    if any(contract.get(name) != value for name, value in expected.items()):
        raise ValueError("MesenCE mapping contract is stale")
    actual = contract.get("actualMaximumGsuRomBank")
    if type(actual) is not int or not 0 <= actual <= target.max_gsu_rom_bank:
        raise ValueError("MesenCE mapping contract has an invalid actual ROM bank")
    return contract


def validate_alias_metadata(
    contract: Mapping[str, Any], config_path: Path, alias_metadata_path: Path
) -> None:
    """Require generated alias metadata to reproduce the release contract."""

    if build_contract(config_path, alias_metadata_path) != contract:
        raise ValueError("generated alias metadata differs from the release mapping")


def release_readme() -> str:
    """Describe the upstream emulator target without project-specific patches."""

    return """Requires the current **MesenCE development build**. Download it for
[Windows, Linux or macOS](https://github.com/nesdev-org/MesenCE#development-builds),
then open `quake.sfc` in the emulator."""


def release_rom_config() -> bytes:
    """Return the exact default build contract shipped in releases."""

    payload = DEFAULT_CONFIG.read_bytes()
    document = json.loads(payload)
    if configured_mesen_target(DEFAULT_CONFIG).name != MESENCE_NIGHTLY_TARGET:
        raise ValueError("release config must retain the ordinary MesenCE target")
    if document.get("demo") != {"source": "pak", "path": "demo1.dem"}:
        raise ValueError("release config must retain the shareware demo")
    return payload
