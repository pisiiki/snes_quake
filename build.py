"""Build the five-map SNES Quake cartridge and its matching MSU-1 files."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import tomllib


def publish_named_cartridge(report):
    rom = Path(report["rom"])
    sidecar = Path(report["sidecar"])
    if sidecar != rom.with_suffix(".msu"):
        raise ValueError("ROM and MSU-1 sidecar must share a filename stem")
    output = rom.parent
    named_rom = rom.with_name("snes_quake.sfc")
    named_sidecar = named_rom.with_suffix(".msu")
    moves = [(rom, named_rom), (sidecar, named_sidecar)]
    tracks = []
    for track in report["audioTracks"]:
        number = track["track"]
        if track["file"] != f"{rom.stem}-{number}.pcm":
            raise ValueError(f"PCM track {number} does not match the ROM filename stem")
        filename = f"{named_rom.stem}-{number}.pcm"
        moves.append((output / track["file"], output / filename))
        tracks.append(dict(track, file=filename))
    for suffix in (".cpu.sym", ".dnfo", ".dmap"):
        companion = rom.with_suffix(suffix)
        if companion.is_file():
            moves.append((companion, named_rom.with_suffix(suffix)))

    raw_report = output / f"{rom.stem}-build.json"
    named_report = output / f"{named_rom.stem}-build.json"
    for source in (raw_report, *(path for path, _ in moves)):
        if not source.is_file():
            raise FileNotFoundError(source)
    result = dict(report, rom=str(named_rom), sidecar=str(named_sidecar), audioTracks=tracks)
    with TemporaryDirectory(prefix=".naming-", dir=output) as directory:
        stage = Path(directory)
        new_report = stage / "build.json"
        new_report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        # Put the report in place last. Restore both sets if any move fails.
        completed = []
        try:
            for source, target in (*moves, (raw_report, stage / "old-report.json"),
                                   (new_report, named_report)):
                if target.exists():
                    backup = stage / target.name
                    target.replace(backup)
                    completed.append((target, backup))
                source.replace(target)
                completed.append((source, target))
        except OSError:
            for source, target in reversed(completed):
                target.replace(source)
            raise
    return named_report


def main(argv=None):
    started = time.monotonic()
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument("--pak", type=Path, help="original shareware PAK0.PAK")
    inputs.add_argument("--shareware", type=Path, help="untouched Quake 1.06 shareware ZIP")
    parser.add_argument("--libsfx", type=Path, help="reuse an existing pinned libSFX checkout")
    parser.add_argument("--allow-dirty", action="store_true", help="build locally edited release sources")
    options = parser.parse_args(argv)
    sys.path.insert(0, str(root / "tools"))
    os.environ["SNES_WORKSPACE"] = str(root)
    from snes_tooling import Workspace
    from snes_tooling.quake.build_quake_playable import build
    from snes_tooling.quake.quake_release_dependencies import LIBSFX
    from snes_tooling.quake.quake_release_layout import SHAREWARE_ARCHIVE
    from snes_tooling.quake.quake_shareware import LHA_MEMBERS, SharewareArchive
    from snes_tooling.shared.workspace_bootstrap import ToolchainSpec, ensure_libsfx, host_platform

    try:
        if options.pak:
            pak = options.pak.resolve()
        else:
            archive = SharewareArchive(options.shareware or root / SHAREWARE_ARCHIVE)
            pak = root / "out/shareware/PAK0.PAK"
            with archive.open_resource() as resource:
                pak.parent.mkdir(parents=True, exist_ok=True)
                resource.extract_member("ID1/PAK0.PAK", pak)
        LHA_MEMBERS["ID1/PAK0.PAK"].verify(pak, "PAK0.PAK")
        os.environ["QUAKE_PAK"] = str(pak)

        libsfx = (options.libsfx or root / LIBSFX.path).resolve()
        if not options.libsfx and not libsfx.exists():
            libsfx.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "clone", "--no-checkout", LIBSFX.repository, libsfx], check=True)
            subprocess.run(["git", "-C", libsfx, "checkout", "--detach", LIBSFX.commit], check=True)
        actual = subprocess.check_output(["git", "-C", libsfx, "rev-parse", "HEAD"], text=True).strip()
        if actual != LIBSFX.commit:
            raise ValueError(f"libSFX revision {actual} differs from required {LIBSFX.commit}")
        if options.libsfx:
            status = subprocess.check_output(["git", "-C", libsfx, "submodule", "status", "--", "tools/cc65"],
                                             text=True)
            if not status.startswith(" "):
                raise ValueError("--libsfx requires its pinned tools/cc65 submodule to be initialized")
        tracked = subprocess.check_output(["git", "-C", libsfx, "status", "--porcelain", "-uno"], text=True)
        if tracked:
            raise ValueError("libSFX and its cc65 submodule must have clean tracked sources")
        with (root / "pyproject.toml").open("rb") as stream:
            spec = ToolchainSpec(root / "pyproject.toml", tomllib.load(stream)["tool"]["snes"])
        ensure_libsfx(Workspace(root), spec, Path("git"), platform_name=host_platform(),
                      provision=True, override=libsfx)
        report = publish_named_cartridge(build(libsfx=libsfx, allow_dirty=options.allow_dirty))
        print(f"Public build passed; report={report}; elapsed={time.monotonic() - started:.3f}s")
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Playable build failed: {error}; elapsed={time.monotonic() - started:.3f}s", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
