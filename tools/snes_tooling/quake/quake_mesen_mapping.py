"""Build and validate the Quake MesenCE GSU-ROM mapping contract."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from snes_tooling.quake.quake_rom_config import (
    DEFAULT_CONFIG,
    MESENCE_NIGHTLY_TARGET,
    MESEN_TARGETS,
    configured_alias_halfbank_count,
    configured_mesen_target,
)


CONTRACT_SCHEMA = "quake-mesence-mapping-v1"
UPSTREAM_REPOSITORY = "https://github.com/nesdev-org/MesenCE.git"
UPSTREAM_COMMIT = "091ff784182c13712deef068c94dc54020b7caf2"

# The ordinary player is a separately qualified, unmodified upstream binary.
# Keep this pin separate from the ROM mapping contract above.
PLAYER_COMMIT = "4b8a196e299b3de297b204fd1208d2981562c89b"
PLAYER_RUN_ID = 37624076912
PLAYER_ARTIFACT_ID = 11483144254
PLAYER_ZIP_BYTES = 32974185
PLAYER_ZIP_SHA256 = "6296e76cb086c54da97083f17adee2bb33a29695db4ee1135c8ea9c451c753b8"
PLAYER_REPOSITORY = "pisiiki/snes_quake"
PLAYER_RELEASE_TAG = "v0.0.3"
PLAYER_RELEASE_COMMIT = "fafa152d3a08ed0d2bd63a59d0e79b9293a1b9b1"
PLAYER_RELEASE_BUILD_INFO_SHA256 = "d3ad90e3b818c8d60190b3e61b96411aa6666217039716e4a9947c7397397c15"
PLAYER_ASSET_PREFIX = "MesenCE-4b8a196e"
PLAYER_BINARY_NAME = PLAYER_ASSET_PREFIX + "-Windows-x64-AOT.zip"
PLAYER_SOURCE_NAME = PLAYER_ASSET_PREFIX + "-source.zip"
PLAYER_PROVENANCE_NAME = PLAYER_ASSET_PREFIX + "-PROVENANCE.json"


def player_download_url(name: str) -> str:
    return f"https://github.com/{PLAYER_REPOSITORY}/releases/download/{PLAYER_RELEASE_TAG}/{name}"


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
    """Render the pinned player download independently of ROM qualification pins."""

    return f"""On **Windows x64**, [download the tested MesenCE player]({player_download_url(PLAYER_BINARY_NAME)}).
Extract the ZIP, run `Mesen.exe`, and open `quake.sfc`; no emulator build is needed.
This is the unchanged official upstream AOT build at
[`{PLAYER_COMMIT[:8]}`](https://github.com/nesdev-org/MesenCE/commit/{PLAYER_COMMIT}),
without this project's development instrumentation.

ZIP SHA-256: `{PLAYER_ZIP_SHA256}`.
[Exact upstream source and license]({player_download_url(PLAYER_SOURCE_NAME)}) ·
[Download provenance and qualification hashes]({player_download_url(PLAYER_PROVENANCE_NAME)}).

For Linux or macOS, see the upstream
[MesenCE development builds](https://github.com/nesdev-org/MesenCE#development-builds)."""


def player_notices() -> str:
    return f"""## MesenCE player download

The separate Windows emulator download is the unmodified official MesenCE build
at `{PLAYER_COMMIT}`. It is not part of this project's MIT-licensed source or
the Quake ROM. [Corresponding upstream source]({player_download_url(PLAYER_SOURCE_NAME)})
includes the exact upstream `LICENSE` and pinned dependency references;
[provenance]({player_download_url(PLAYER_PROVENANCE_NAME)}) records its binary,
source and qualification hashes. MesenCE retains its upstream GPL-3.0 terms.
"""


def release_rom_config() -> bytes:
    """Return the exact default build contract shipped in releases."""

    payload = DEFAULT_CONFIG.read_bytes()
    document = json.loads(payload)
    if configured_mesen_target(DEFAULT_CONFIG).name != MESENCE_NIGHTLY_TARGET:
        raise ValueError("release config must retain the ordinary MesenCE target")
    if document.get("demo") != {"source": "pak", "path": "demo1.dem"}:
        raise ValueError("release config must retain the shareware demo")
    return payload
