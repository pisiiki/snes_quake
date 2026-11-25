"""Build the playable SNES Quake cartridge."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

from snes_tooling import Workspace
from snes_tooling.quake.quake_rom_config import configured_target
from snes_tooling.quake.quake_target_layout import asset_layout
from snes_tooling.shared.processes import python_child_environment


def _write_staged_text(path: Path, text: str) -> None:
    if not path.is_file() or path.read_text(encoding="utf-8") != text:
        path.write_text(text, encoding="utf-8")


def stage_target(workspace: Workspace, name: str, *, config_name: str,
                 cache_kernel_manifest: str, reuse_playable_shader: bool = False,
                 cpu_preamble: bytes = b"", gsu_preamble: bytes = b"") -> Path:
    config = workspace.root / "config/snes_quake" / config_name
    target = configured_target(config)
    if target["mode"] != "fly":
        raise ValueError("project staging requires a map configuration")
    example = workspace.root / "out/snes_quake/targets" / name / "src/snes_quake"
    if example.resolve() != example:
        raise ValueError(f"target staging path must not redirect outside its assigned path: {example}")
    example.mkdir(parents=True, exist_ok=True)
    preambles = {example / "quake.s": cpu_preamble, example / "quake.sgs": gsu_preamble,
                 example / "Makefile": b"SNES_QUAKE_STAGED_MAP := 1\n"}

    def copy_source(source, destination):
        destination_path = Path(destination)
        if (reuse_playable_shader and destination_path == example / "quake.sgs"
                and (example / "Data/QuakeBSPAliasRuntime0.bin").is_file()):
            from snes_tooling.quake.quake_playable_source_budget import prepare_source_budget

            # Stage the final derived bytes directly. Copying the unprefixed
            # source first invalidates ld65's timestamp for identical output.
            prepare_source_budget(example, source_shader=Path(source), shader_preamble=gsu_preamble)
            return destination
        preamble = preambles.get(destination_path)
        if preamble:
            payload = preamble + Path(source).read_bytes()
            if not destination_path.is_file() or destination_path.read_bytes() != payload:
                destination_path.write_bytes(payload)
            return destination
        return shutil.copy2(source, destination)

    shutil.copytree(workspace.root / "src/snes_quake", example, dirs_exist_ok=True,
                    copy_function=copy_source,
                    ignore=shutil.ignore_patterns("Data", "fixtures", "snes-project.json", "Map.cfg"))
    manifest = json.loads((workspace.root / "src/snes_quake/snes-project.json").read_bytes())
    for key, relative in (
        ("assetGenerator", "tools/commands/snes_quake/generate_snes_example_assets.py"),
        ("sourceGenerator", "tools/commands/snes_quake/quake_runtime_codegen.py"),
    ):
        manifest[key] = Path(os.path.relpath(workspace.root / relative, example)).as_posix()
    manifest["cacheKernelManifest"] = cache_kernel_manifest
    manifest.update(buildDirectory="../../build", libsfxBuildDirectory="../../build_libsfx",
                    outputDirectory="../..")
    _write_staged_text(example / "snes-project.json", json.dumps(manifest, indent=2) + "\n")
    map_path = example / "Map.cfg"
    layout = (workspace.root / "src/snes_quake/Map.cfg").read_text()
    # Merge the two unused soundtrack halfbanks without changing the
    # physical offsets of any later linker areas.
    for pattern, replacement in (
        (r"(\bROM100:\s+start = \$c20000, size = )\$8000", r"\g<1>$10000"),
        (r"(?m)^\s*ROM101:\s+start = \$c28000,[^\n]*\n", ""),
        (r"(\bBSP_SOUND_03:\s+load = )ROM101", r"\g<1>ROM100"),
    ):
        layout, count = re.subn(pattern, replacement, layout)
        if count != 1:
            raise ValueError("map staging requires the two stock $C2 soundtrack halves")
    for segment, bank in asset_layout(False, target.get("map")).linker_remaps().items():
        layout, count = re.subn(r"(\b" + segment + r":\s+load\s*=\s*)ROM\d+",
                               lambda match: match[1] + f"ROM{bank}", layout)
        if count != 1:
            raise ValueError(f"expected one linker segment {segment}, got {count}")
    _write_staged_text(map_path, layout)
    return example


def main(argv=None):
    started = time.monotonic()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=("playable",), default="playable")
    parser.add_argument("--libsfx", type=Path)
    parser.add_argument("--pak", type=Path, help="original shareware PAK")
    parser.add_argument("--reuse-assets", nargs="?", const="all", choices=("all", "playable"),
                        help="verify and reuse staged assets")
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    workspace = Workspace.discover()
    try:
        command = [sys.executable, "-m", "snes_tooling.quake.build_quake_playable"]
        if args.libsfx:
            command.extend(("--libsfx", str(args.libsfx.resolve())))
        for enabled, flag in ((args.reuse_assets, "--reuse-assets"), (args.allow_dirty, "--allow-dirty"),
                              (args.json, "--json")):
            if enabled:
                command.append(flag)
        environment = python_child_environment(workspace.root / "tools", environment=dict(
            os.environ, SNES_WORKSPACE=str(workspace.root)))
        if args.pak:
            environment["QUAKE_PAK"] = str(args.pak.resolve())
        return subprocess.run(command, cwd=workspace.root, env=environment).returncode
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Quake project build failed: {error}; elapsed={time.monotonic()-started:.3f}s", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
