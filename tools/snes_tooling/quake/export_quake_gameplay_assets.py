"""Build small immutable gameplay inputs directly from the original Quake PAK.

This uses production data compilers and the exact SNES billboard package,
without copying evolving emulator state or rebaking model sprites.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path
import re
import struct
import time

from snes_tooling import Workspace
from snes_tooling.quake.quake_bsp_assets import (
    PakArchive,
    lump_data,
    lump_ranges,
    parse_entities,
    player_start,
    snes_color,
)
from snes_tooling.quake.quake_brush_replay import BrushEntityState, CanonicalBrushRow
from snes_tooling.quake.quakec_gameplay import build_gameplay
from snes_tooling.quake.quake_basic_gameplay import build_basic_gameplay
from snes_tooling.quake.quake_walk_hull import (
    player_hull_outputs,
    shotgun_hull_outputs,
    static_level_hull_outputs,
)
from snes_tooling.quake.generate_quake_snes_weapon_sprites import (
    build_live_outputs,
    PREFIX,
)
from snes_tooling.quake.export_quake_live_weapon_reference import build_reference
from snes_tooling.quake.quake_gameplay_billboard_assets import (
    read_production_bundle,
    alias_payloads_for_map,
)


from snes_tooling.quake.quake_playable_maps import MAP_NAMES

MAPS = MAP_NAMES
SCHEMA = "quake-gameplay-assets-v1"


def equates(payload: bytes) -> dict[str, int]:
    result = {}
    for line in payload.decode("ascii").splitlines():
        line = line.split(";", 1)[0].strip()
        if not line:
            continue
        match = re.fullmatch(r"([A-Z][A-Z_0-9]*)\s*=\s*(-?\d+|\$[0-9A-Fa-f]+)", line)
        if not match:
            raise ValueError(f"unsupported gameplay constant: {line}")
        name, value = match.groups()
        if name in result:
            raise ValueError(f"duplicate gameplay constant: {name}")
        result[name] = int(value[1:], 16) if value.startswith("$") else int(value)
    return result


def assembly_table(text: str, label: str, bits: int) -> list[int]:
    """Read a literal production table, stopping at its next named label."""
    marker = label + ":"
    if text.count(marker) != 1:
        raise ValueError(f"missing or duplicated table: {label}")
    rows = text.split(marker, 1)[1].splitlines()
    values = []
    directive = ".byte" if bits == 8 else ".word"
    for line in rows:
        line = line.split(";", 1)[0].strip()
        if re.match(r"\w+\s*[:=]", line):
            break
        if not line.startswith(directive):
            continue
        for token in line[len(directive) :].split(","):
            token = token.strip()
            value = int(token[1:], 16) if token.startswith("$") else int(token)
            if not 0 <= value < 1 << bits:
                raise ValueError(f"table value outside {bits}-bit domain")
            values.append(value - (1 << bits) if value & (1 << (bits - 1)) else value)
    if not values:
        raise ValueError(f"empty gameplay table: {label}")
    return values


def brush_record(brush: BrushEntityState) -> dict:
    return dict(
        entity=brush.entity_number,
        modelIndex=brush.model_index,
        inlineModel=brush.inline_model,
        frame=brush.frame,
        origin=list(brush.origin),
        angles=list(brush.angles),
    )


def build_map(
    archive: PakArchive, name: str, source: Path
) -> tuple[dict, dict[Path, bytes]]:
    if name not in MAPS:
        raise ValueError(f"unsupported playable map: {name}")
    entry = f"maps/{name}.bsp"
    bsp = archive.read(entry)
    lumps = lump_ranges(bsp)
    entities = parse_entities(lump_data(bsp, lumps, 0))
    models = tuple(struct.iter_unpack("<9f7i", lump_data(bsp, lumps, 14)))
    origin = tuple((models[0][i] + models[0][i + 3]) * 0.5 for i in range(3))
    spawn, angle = player_start(entities)
    brushes = tuple(
        BrushEntityState(
            i,
            int(entity["model"][1:]) + 1,
            int(entity["model"][1:]),
            0,
            tuple(map(float, entity.get("origin", "0 0 0").split())),
            (0.0, 0.0, 0.0),
        )
        for i, entity in enumerate(entities, 1)
        if entity.get("model", "").startswith("*")
        and not entity.get("classname", "").startswith("trigger_")
    )
    row = CanonicalBrushRow(0, 0, 0, 0.0, None, ())
    if name == "start":
        from snes_tooling.quake.quake_start_hub import build_gameplay as builder, hub_static_models
        active = set(hub_static_models(entities))
        brushes = tuple(brush for brush in brushes if brush.inline_model in active)
    else:
        builder = build_gameplay if name == "e1m1" else build_basic_gameplay
    builder_options = {"map_name": name} if builder is build_basic_gameplay else {}
    rows, include, metadata, outputs = builder(
        archive, bsp, entities, models, row, brushes, **builder_options
    )
    if name in ("e1m2", "e1m3"):
        from snes_tooling.quake.quake_e1m2_machinery import e1m2_signon_brushes
        brushes = e1m2_signon_brushes(brushes, metadata["stockExitMachinery"])
    if name == "e1m1":
        from snes_tooling.quake.quakec_health_pickups import health_include, stock_health_boxes
        health = stock_health_boxes(archive, bsp, entities, models)
        metadata["stockHealth"] = {"boxes": health}
        shells = metadata["stockShells"]["boxes"]
        nails = metadata["stockNailgun"]["boxes"]
        boxes = [metadata["stockExplobox"]]
        entity_order = sorted(box["entityNumber"] for box in (*shells, *health, *nails, *boxes))
        include += health_include(shells, health, entity_order, nails=nails, boxes=boxes)
    from snes_tooling.quake.quake_start_hub import HUB_INCLUDE, EPISODE_EXITS, episode_exit_descriptor, hub_outputs
    if name in EPISODE_EXITS:
        metadata = {**metadata, "hub": episode_exit_descriptor(entities, models, name)}
    if HUB_INCLUDE not in outputs:
        outputs.update(hub_outputs(metadata.get("hub")))
    constants = {**equates(include), **equates(outputs[HUB_INCLUDE])}
    from snes_tooling.quake.quake_landing import LANDING_INCLUDE, LANDING_WATER, landing_water_outputs
    landing = landing_water_outputs(bsp, origin)
    constants.update(equates(landing[LANDING_INCLUDE]))
    outputs[LANDING_WATER] = landing[LANDING_WATER]
    if name == "e1m1":
        walk, walk_include = player_hull_outputs(bsp, origin, exit_movers=True, explobox=metadata["stockExplobox"])
        shot, shot_include = shotgun_hull_outputs(bsp, origin, exit_movers=True)
    else:
        selected = hub_static_models(entities) if name == "start" else None
        movers = dict(e1m2=name == "e1m2", e1m3=name == "e1m3")
        walk, walk_include = static_level_hull_outputs(bsp, origin, point=False, static_models=selected, **movers)
        shot, shot_include = static_level_hull_outputs(bsp, origin, point=True, static_models=selected, **movers)
    constants.update(equates(walk_include + shot_include))
    outputs.update(walk)
    outputs.update(shot)
    outputs[Path("QuakeBSPQuakeCGameplay.i")] = include
    outputs[Path("QuakeBSPQuakeCGameplay.json")] = json_bytes(metadata)
    angles_path = source / "src/snes_quake/quake/CameraAngles.s"
    angles = angles_path.read_text(encoding="utf-8")
    sine = assembly_table(angles, "CameraAngleSin", 8)
    move = assembly_table(angles, "CameraMoveSin", 16)
    if len(sine) != 320 or len(move) != 320:
        raise ValueError("production camera table shape changed")
    weapon = build_live_outputs(archive, metadata["stockShotgun"]["viewSequence"],
                                axe_sequence=metadata["stockAxe"]["viewSequence"], playable=True,
                                nailgun="stockNailgun" in metadata or "campaignWeapons" in metadata)
    outputs.update(weapon)
    weapon_source = weapon[Path(PREFIX + ".i")].decode("ascii")
    live = assembly_table(weapon_source, "QuakeBSPWeaponLiveFrames", 8)
    axe_frames = assembly_table(weapon_source, "QuakeBSPWeaponAxeFrames", 8)
    constants.update(
        equates(
            b"\n".join(
                line
                for line in weapon[Path(PREFIX + ".i")].splitlines()
                if re.match(rb"^BSP_WEAPON_(LIVE_TICKS|AXE_TICKS|AXE_IDLE|NAIL_IDLE|SSG_IDLE)\s*=", line)
            )
        )
    )
    if name == "e1m1":
        from snes_tooling.quake.quake_grunt_assets import actor_frame_rows
        outputs[Path("QuakeBSPGruntFrames.bin")] = actor_frame_rows(bool(metadata.get("stockDogs")))
    if name == "e1m1":
        from snes_tooling.quake.quake_intermission import FILE, source_graphics
        outputs[Path(FILE)] = source_graphics(archive)
    palette = archive.read("gfx/palette.lmp")
    outputs[Path("QuakeBSPTexturePalette.bin")] = b"".join(
        struct.pack("<H", snes_color(rgb))
        for rgb in struct.iter_unpack("<BBB", palette)
    )
    constants.update(
        CAMERA_ANGLE_MASK=255,
        CAMERA_ANGLE_QUARTER=64,
        CAMERA_PITCH_MIN=-64,
        CAMERA_PITCH_MAX=64,
    )
    manifest = dict(
        schema=SCHEMA,
        map=name,
        mapEntry=entry,
        worldOrigin=list(origin),
        spawnEyeQ4=[
            round((spawn[i] + (22 if i == 2 else 0) - origin[i]) * 16) for i in range(3)
        ],
        spawnYaw=round(angle / 360 * 256) & 255,
        constants=constants,
        metadata=dict(
            gameplay=metadata,
            walkHull=json.loads(walk[Path("QuakeBSPWalkHull.json")]),
            shotHull=json.loads(shot[Path("QuakeBSPShotHull.json")]),
        ),
        authoredBrushes=[brush_record(brush) for brush in brushes],
        brushRows=[
            dict(
                index=row.index, brushes=[brush_record(brush) for brush in row.brushes]
            )
            for row in rows
        ],
        tables=dict(cameraSinQ6=sine, cameraMoveSinQ4=move, weaponLiveFrames=live,
                    weaponAxeFrames=axe_frames),
        weaponAssets="weapon.qwv4",
        source=dict(
            pakSha256=sha256(archive.path.read_bytes()).hexdigest(),
            bspSha256=sha256(bsp).hexdigest(),
            progsSha256=sha256(archive.read("progs.dat")).hexdigest(),
            cameraTablesSha256=sha256(angles_path.read_bytes()).hexdigest(),
        ),
    )
    return manifest, outputs


def json_bytes(value) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def export_map(
    archive: PakArchive,
    name: str,
    output: Path,
    source: Path,
    production_bundle: dict,
) -> dict:
    manifest, outputs = build_map(archive, name, source)
    aliases, contract = alias_payloads_for_map(production_bundle, manifest)
    for path, payload in aliases.items():
        if path in outputs and outputs[path] != payload:
            raise ValueError(
                "SNES billboard inputs differ from gameplay inputs: " + str(path)
            )
        outputs[path] = payload
    manifest["referenceData"] = "."
    manifest["billboards"] = contract
    destination = output / name
    destination.mkdir(parents=True, exist_ok=True)
    for relative, payload in outputs.items():
        (destination / relative).write_bytes(payload)
    weapon, provenance = build_reference(destination)
    outputs[Path("weapon.qwv4")] = weapon
    outputs[Path("weapon-reference.json")] = json_bytes(provenance)
    for relative in (Path("weapon.qwv4"), Path("weapon-reference.json")):
        (destination / relative).write_bytes(outputs[relative])
    manifest["payloads"] = [
        dict(file=path.as_posix(), bytes=len(blob), sha256=sha256(blob).hexdigest())
        for path, blob in sorted(outputs.items())
    ]
    target = destination / "gameplay.json"
    payload = json_bytes(manifest)
    target.write_bytes(payload)
    return dict(
        map=name,
        manifest=target.relative_to(output).as_posix(),
        bytes=len(payload),
        sha256=sha256(payload).hexdigest(),
    )


def main(argv=None) -> int:
    started = time.monotonic()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pak", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--maps", nargs="+", choices=MAPS, default=list(MAPS))
    parser.add_argument(
        "--production-aliases",
        type=Path,
        required=True,
        help="Hash-bound billboard bundle exported from the playable SNES package",
    )
    args = parser.parse_args(argv)
    try:
        if len(set(args.maps)) != len(args.maps):
            raise ValueError("duplicate map request")
        archive = PakArchive(args.pak)
        source = Workspace.discover().root
        production_bundle = read_production_bundle(args.production_aliases)
        args.output.mkdir(parents=True, exist_ok=True)
        with ThreadPoolExecutor(max_workers=len(args.maps)) as workers:
            futures = [
                workers.submit(
                    export_map, archive, name, args.output, source, production_bundle
                )
                for name in args.maps
            ]
            maps = [future.result() for future in futures]
        index = dict(schema="quake-gameplay-mapset-v1", maps=maps)
        (args.output / "gameplay-maps.json").write_bytes(json_bytes(index))
    except (OSError, ValueError, KeyError) as error:
        print(
            f"FAIL gameplay assets: {error}; elapsed={time.monotonic() - started:.3f}s"
        )
        return 1
    print(
        json.dumps(
            dict(
                passed=True,
                maps=maps,
                output=str(args.output.resolve()),
                elapsedSeconds=round(time.monotonic() - started, 3),
            )
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
