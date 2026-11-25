"""Recover production QBA1 gameplay bundles from a passing playable build report."""

from __future__ import annotations

import argparse
from fractions import Fraction
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import struct
from time import monotonic

HEADER = struct.Struct("<4s8H4IQ")
ROW = struct.Struct("<BBHBBH")
SPRITE = struct.Struct("<BBHBBBBBBhh")
HALFBANK = 32768


def identity(payload):
    return dict(bytes=len(payload), sha256=sha256(payload).hexdigest())


def verified_actor_roster(gameplay, aliases, coverage):
    """Validate distinct live-grunt and fixed ambient catalogs without fake actors."""
    roster = gameplay.get("stockGrunts", [])
    ambient = gameplay.get("staticAmbientMdls", [])
    if aliases.get("mode") == "static-level-ambient":
        if roster or not ambient:
            raise ValueError("static ambient aliases require a distinct nonempty ambient roster")
        roster = ambient
        frames = [actor.get("frame") for actor in roster]
        if any(type(frame) is not int or not 0 <= frame <= 255 for frame in frames):
            raise ValueError("ambient source frame must be an integer byte")
        if sorted(set(frames)) != sorted(coverage):
            raise ValueError("ambient source frames differ from the complete sprite catalog")
    else:
        if ambient and not gameplay.get("stockKnights"):
            raise ValueError("ambient actors require their explicit static ambient catalog")
        from snes_tooling.quake.quake_grunt_assets import DOG_FRAMES, E1M1_SOLDIER_FRAMES, KNIGHT_FRAMES, SOLDIER_FRAMES
        if gameplay.get("stockKnights"):
            expected = list(KNIGHT_FRAMES)
            if ambient:
                expected = [(0, frame) for frame in expected]
                expected.extend((index, actor["frame"]) for index, actor in enumerate(ambient, 1))
            if weapons := gameplay.get("campaignWeapons"):
                expected.append((aliases["instrumentation"]["modelNames"].index(weapons["spikeModel"]), 0))
            if list(coverage) != expected:
                raise ValueError("production knight billboard rows disagree with the native pose map")
            roster = [*roster, *ambient]
        elif gameplay.get("stockDogs"):
            expected = [(0, frame) for frame in E1M1_SOLDIER_FRAMES] + [(1, frame) for frame in DOG_FRAMES]
            armor = gameplay.get("stockArmor", ())
            expected.extend((2 + i, box["frame"]) for i, box in enumerate(armor))
            models = aliases["instrumentation"]["modelNames"]
            if "progs/backpack.mdl" in models:
                if models.index("progs/backpack.mdl") != 2 + len(armor):
                    raise ValueError("backpack model differs from its native sprite row")
                expected.append((2 + len(armor), 0))
            powerups = gameplay.get("stockPowerups", ())
            for item in powerups:
                if item["spriteRow"] != len(expected):
                    raise ValueError("powerup model differs from its native sprite row")
                expected.append((models.index(item["model"]), item["frame"]))
            if "progs/g_nail.mdl" in models:
                gun = models.index("progs/g_nail.mdl")
                if models[gun:gun + 2] != ["progs/g_nail.mdl", "progs/spike.mdl"]:
                    raise ValueError("nailgun and spike models differ from their native rows")
                expected.extend(((gun, 0), (gun + 1, 0)))
            if "stockSuperShotgun" in gameplay:
                item = gameplay["stockSuperShotgun"]["pickup"]
                if item["spriteRow"] != len(expected):
                    raise ValueError("Super Shotgun pickup differs from its native sprite row")
                expected.append((models.index(item["model"]), item["frame"]))
            if gameplay.get("stockOverkill"):
                from snes_tooling.quake.quakec_gibs import MODELS
                expected.extend((models.index(model), 0) for model in MODELS)
            if box := gameplay.get("stockExplobox"):
                index = models.index(box["explosionModel"])
                expected.extend((index, frame) for frame in box["frames"])
                if "particleModel" in box:
                    index = models.index(box["particleModel"])
                    for first, end in box["particleRows"]:
                        if first != len(expected):
                            raise ValueError("explosion particles disagree with the native sprite rows")
                        expected.extend((index, frame - box["particleRows"][0][0]) for frame in range(first, end))
            from snes_tooling.quake.quake_teleport_particles import FRAMES, MODEL, STRIPS
            if MODEL in models:
                expected.extend((models.index(MODEL), frame) for frame in range(FRAMES * STRIPS))
            from snes_tooling.quake import quake_combat_particles as impacts
            if impacts.MODEL in models:
                expected.extend((models.index(impacts.MODEL), frame)
                                for frame in range(impacts.FRAMES * len(impacts.STYLES)))
            roster = [*roster, *armor, *powerups]
            if list(coverage) != expected:
                raise ValueError("production enemy billboard rows disagree with the native pose map")
        elif coverage and sorted(coverage) != list(SOLDIER_FRAMES):
            raise ValueError("production live grunt sprite frame set is incomplete")
    if bool(roster) != bool(coverage):
        raise ValueError("production gameplay actor roster differs from alias coverage")
    model_names = aliases["instrumentation"]["modelNames"]
    if any(actor["model"] not in model_names for actor in roster):
        raise ValueError("production actor model is absent from alias metadata")
    return roster


def verified_mdl_density(metadata, sprites):
    """Verify declared density against exact QBA extents; retain legacy unknowns."""
    if "rasterDensity" not in metadata:
        # Historical packages are recoverable without inventing a density.
        return None
    record = metadata["rasterDensity"]
    density = record.get("mdlWorldUnitsPerTexel") if isinstance(record, dict) else None
    if (
        isinstance(density, bool)
        or not isinstance(density, (int, float))
        or not math.isfinite(density)
        or density < 1
    ):
        raise ValueError("production MDL density must be finite and at least one")
    fraction = Fraction(str(density))
    for sprite in sprites:
        models = metadata.get("instrumentation", {}).get("modelNames", ())
        if models and models[sprite[1]].endswith(".spr"):
            continue  # IDSP pixels and pivots retain their original world-unit scale.
        width, height, world_width, world_height = sprite[3:7]
        world_width = world_width or width
        world_height = world_height or height
        expected = tuple(
            (value * fraction.denominator + fraction.numerator - 1)
            // fraction.numerator
            for value in (world_width, world_height)
        )
        if width <= 0 or height <= 0 or (width, height) != expected:
            raise ValueError(
                "production MDL density disagrees with QBA stored/world extents"
            )
    return float(density)


def require_identity(payload, expected, label):
    actual = identity(payload)
    if any(actual[key] != expected[key] for key in actual):
        raise ValueError(f"size/SHA-256 mismatch for {label}")
    return actual


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def original_location(physical):
    if physical < 64:
        return physical, 0x8000
    return 0x60 + (physical - 64) // 2, 0x8000 if physical & 1 else 0


def restore_pointers(chunks, regions, physical, *, tail_bytes=0):
    """Invert only the same QBA1 pointer fields relocated by the ROM linker."""
    source = b"".join(chunks)
    out = bytearray(source)
    header = HEADER.unpack_from(source)
    if header[:3] != (b"QBA1", 6, HEADER.size) or header[8] != len(chunks):
        raise ValueError("invalid production QBA1 header")

    def restore(bank, address, *, pixels=0):
        if bank >= 0x80:
            index = bank - 0x80
            if tail_bytes and index == len(regions) and pixels and address + pixels <= tail_bytes:
                old_bank, old_base = original_location(physical[0])
                return old_bank, old_base + regions[0]["bytes"] + address
            if (not pixels or not 0 < index < len(regions) or regions[index]["storage"] != "msu"
                    or not 0 <= address < HALFBANK or address + pixels > HALFBANK
                    or regions[index]["bytes"] != HALFBANK):
                raise ValueError("invalid tagged MSU sprite pointer")
            old_bank, old_base = original_location(physical[index])
            return old_bank, old_base + address
        for index, region in enumerate(regions):
            if region.get("storage") == "msu":
                continue
            if (
                bank == region["gsuBank"]
                and region["gsuAddress"] <= address
                and address + max(1, pixels) <= region["gsuAddress"] + region["bytes"]
            ):
                old_bank, old_base = original_location(physical[index])
                return old_bank, old_base + address - region["gsuAddress"]
        raise ValueError(
            f"QBA1 pointer ${bank:02X}:${address:04X} escapes alias regions"
        )

    for index in range(header[3]):
        offset = header[9] + index * ROW.size
        row = list(ROW.unpack_from(source, offset))
        if row[1]:
            row[0], row[2] = restore(row[0], row[2])
        if row[4]:
            row[3], row[5] = restore(row[3], row[5])
        ROW.pack_into(out, offset, *row)
    for index in range(header[4]):
        offset = header[10] + index * SPRITE.size
        sprite = list(SPRITE.unpack_from(source, offset))
        sprite[0], sprite[2] = restore(sprite[0], sprite[2], pixels=sprite[3] * sprite[4])
        SPRITE.pack_into(out, offset, *sprite)
    return [
        bytes(out[index : index + HALFBANK]) for index in range(0, len(out), HALFBANK)
    ]


def locate(root, value, *fallbacks):
    """Honor fresh report paths, then the retained package's adjacent copies."""
    if value:
        declared = Path(value)
        declared = declared if declared.is_absolute() else root / declared
        if declared.is_file():
            return declared
    for candidate in fallbacks:
        if candidate.is_file():
            return candidate
    raise ValueError(
        "playable package input is unavailable: " + str(value or fallbacks)
    )


def package_segment(segment, rom, msu):
    offset, size = segment["offset"], segment["bytes"]
    if offset < 0 or size <= 0:
        raise ValueError("invalid playable segment range")
    if segment["storage"] == "msu":
        paired = msu[64 + offset * 2 : 64 + (offset + size) * 2]
        if len(paired) != size * 2 or any(
            a ^ b != 255 for a, b in zip(paired[::2], paired[1::2])
        ):
            raise ValueError("playable MSU segment is truncated or corrupt")
        payload = paired[::2]
    elif segment["storage"] in ("gsu", "cpu"):
        payload = rom[offset : offset + size]
    else:
        raise ValueError("unsupported playable segment storage")
    require_identity(payload, segment, "stored " + segment["segment"])
    return payload


def weapon_palette_inverse(rom, entry):
    offset = entry["offset"]
    mapping = rom[offset : offset + entry["bytes"]]
    require_identity(mapping, entry, "weapon OBJ palette")
    if (len(mapping) != 256 or len(set(mapping)) != 256 or mapping[0] != 0
            or mapping[240:] != bytes(range(240, 256))):
        raise ValueError("invalid weapon OBJ palette permutation")
    return bytes(mapping.index(index) for index in range(256))


def source_records(map_entry):
    records = map_entry.get("sourceAssets", [])
    if isinstance(records, dict):
        return records
    return {row["file"]: row for row in records}


def closure_records(closure, path):
    if closure is None:
        return {}
    tree = next(
        (tree for tree in closure["trees"] if tree["record"]["path"] == path), None
    )
    if tree is None:
        raise ValueError(
            "the supplied input closure omits this module's declared data tree"
        )
    return {row["relative"]: row for row in tree["manifest"]}


def recover(package, output, input_closure=None):
    started = monotonic()
    package = Path(package).resolve()
    root = package.parent
    build_payload = package.read_bytes()
    build = json.loads(build_payload)
    if build.get("schema") != "quake-playable-package-v1" or not build.get("passed"):
        raise ValueError(
            "--snes-package requires a passing quake-playable-build.json report"
        )
    if not build.get("maps") or len({row["map"] for row in build["maps"]}) != len(
        build["maps"]
    ):
        raise ValueError("playable build report contains duplicate or missing maps")
    rom_name = Path(build["rom"].replace("\\", "/")).name
    msu_name = Path(build["sidecar"].replace("\\", "/")).name
    stem = Path(rom_name).stem
    rom = locate(root, build["rom"], root / rom_name).read_bytes()
    msu = locate(root, build["sidecar"], root / msu_name).read_bytes()
    require_identity(
        rom, dict(bytes=build["romBytes"], sha256=build["romSha256"]), "ROM"
    )
    require_identity(
        msu, dict(bytes=build["archiveBytes"], sha256=build["archiveSha256"]), "MSU"
    )
    if msu[:20] != b"QPL1" + bytes.fromhex(build["binding"]):
        raise ValueError("playable MSU binding differs from its build report")
    closure_payload = Path(input_closure).read_bytes() if input_closure else None
    closure = json.loads(closure_payload) if closure_payload else None
    if closure is not None and not closure.get("passed"):
        raise ValueError("a passing input closure is required")
    layout_payload = (
        (root / "layout.json").read_bytes()
        if (root / "layout.json").is_file()
        else None
    )
    layout = json.loads(layout_payload) if layout_payload else None
    weapon_obj = build.get("weaponObj")
    palette_inverse = None
    if weapon_obj is not None:
        palette_inverse = weapon_palette_inverse(rom, weapon_obj[0])
    outputs, maps, evidence = {}, [], []
    recovered_chunks = 0
    for module, map_entry in enumerate(build["maps"]):
        name = map_entry["map"]
        if not re.fullmatch(r"[a-z0-9_-]+", name):
            raise ValueError("invalid playable map name")
        source_data = Path(map_entry["sourceData"])
        source_data = source_data if source_data.is_absolute() else root / source_data
        if not source_data.is_dir():
            source_data = root / "metadata" / f"playable-{name}-source"
        if not source_data.is_dir():
            raise ValueError(
                "production source metadata is missing for "
                + name
                + "; preserve sourceData or place its metadata next to the build report"
            )
        source_bound = source_records(map_entry)
        if not source_bound and closure is None:
            raise ValueError(
                "this legacy playable report has no sourceAssets binding; supply --input-closure"
                + " or rebuild the playable package with current tooling"
            )
        original = closure_records(closure, map_entry["sourceData"])
        relocated = closure_records(closure, map_entry["data"])
        metadata = {}
        for filename in ("QuakeBSPAliasAssets.json", "QuakeBSPQuakeCGameplay.json"):
            payload = (source_data / filename).read_bytes()
            for records in (source_bound, original):
                if records:
                    require_identity(payload, records[filename], name + " " + filename)
            metadata[filename] = json.loads(payload)
            outputs[f"{name}/{filename}"] = payload
        aliases = metadata["QuakeBSPAliasAssets.json"]
        gameplay = metadata["QuakeBSPQuakeCGameplay.json"]
        if aliases.get("schema") != "quake-level-alias-assets-v1":
            raise ValueError("production gameplay requires standalone level aliases")
        if not all(
            re.fullmatch(r"[0-9a-f]{64}", gameplay[key])
            for key in ("pakSha256", "bspSha256", "progsSha256")
        ):
            raise ValueError("production gameplay metadata lacks source bindings")
        segments = {
            row["segment"]: row for row in build["segments"] if row["module"] == module
        }
        count = aliases["format"]["chunkCount"]
        recovered_chunks += count
        regions = [segments[f"BSP_ALIAS_{index}"] for index in range(count)]
        if layout is not None:
            for index, region in enumerate(regions):
                if any(
                    layout[f"{module}:BSP_ALIAS_{index}"][key] != region[key]
                    for key in (("offset", "bytes", "storage") if region["storage"] == "msu"
                                else ("offset", "bytes", "storage", "gsuBank", "gsuAddress"))
                ):
                    raise ValueError(
                        "playable alias layout differs from package segment"
                    )
        chunks = [package_segment(region, rom, msu) for region in regions]
        if relocated:
            for index, payload in enumerate(chunks):
                require_identity(
                    payload,
                    relocated[f"QuakeBSPAliasRuntime{index}.bin"],
                    "relocated alias",
                )
        from snes_tooling.quake.quake_playable_alias_budget import restore_empty_alias_extent
        tails = [row for row in build.get("spriteTails", ()) if row["module"] == module]
        tail = b""
        if tails:
            if len(tails) != 1 or not gameplay.get("stockGrunts") or tails[0]["storage"] != "msu":
                raise ValueError("invalid playable alias sprite tail")
            tail = package_segment(tails[0], rom, msu)
            if len(chunks[0]) + len(tail) != HALFBANK:
                raise ValueError("alias sprite tail does not reconstruct bank zero")
            chunks[0] += tail
        else:
            chunks = restore_empty_alias_extent(source_data, chunks)
        restored = restore_pointers(
            chunks, regions, aliases["format"]["storagePhysicalHalfbanks"], tail_bytes=len(tail)
        )
        if palette_inverse is not None:
            from snes_tooling.quake.quake_weapon_obj import alias_pixel_ranges, permute_alias_pixels
            ranges = alias_pixel_ranges(restored, aliases["format"]["storagePhysicalHalfbanks"])
            restored = [permute_alias_pixels(payload, extent, palette_inverse)
                        for payload, extent in zip(restored, ranges, strict=True)]
        for index, payload in enumerate(restored):
            filename = f"QuakeBSPAliasRuntime{index}.bin"
            require_identity(
                payload,
                aliases["outputs"][filename],
                name + " original alias " + str(index),
            )
            if original:
                require_identity(
                    payload,
                    original[filename],
                    name + " closure original alias " + str(index),
                )
            outputs[f"{name}/{filename}"] = payload
        symbol_path = locate(
            root,
            map_entry.get("symbols"),
            root / f"{stem}.{name}.cpu.sym",
            root / f"{stem}.cpu.sym"
            if module == 0
            else root / "missing-module-symbols",
        )
        symbol_payload = symbol_path.read_bytes()
        labels = {
            label: int(address, 16)
            for address, label in re.findall(
                rb"^al ([0-9A-Fa-f]+) \.([^\r\n ]+)\r?$", symbol_payload, re.MULTILINE
            )
        }
        if (
            b"QuakeBSPTexturePalette" not in labels
            or b"QuakeBSPTexturePaletteEnd" not in labels
        ):
            raise ValueError("module CPU symbols omit the production texture palette")
        address = labels[b"QuakeBSPTexturePalette"]
        if labels[b"QuakeBSPTexturePaletteEnd"] - address != 512:
            raise ValueError("production palette symbol extent is not 512 bytes")
        containers = [
            row
            for row in segments.values()
            if row["linkerAddress"] <= address
            and address + 512 <= row["linkerAddress"] + row["bytes"]
        ]
        if len(containers) != 1:
            raise ValueError(
                "production palette symbols do not name one complete declared segment"
            )
        container = containers[0]
        relative = address - container["linkerAddress"]
        palette = package_segment(container, rom, msu)[relative : relative + 512]
        if palette_inverse is not None:
            from snes_tooling.quake.quake_weapon_obj import permute_words
            palette = permute_words(palette, palette_inverse)
        for records in (source_bound, original):
            if records:
                require_identity(
                    palette, records["QuakeBSPTexturePalette.bin"], name + " palette"
                )
        source_palette = source_data / "QuakeBSPTexturePalette.bin"
        if source_palette.is_file() and source_palette.read_bytes() != palette:
            raise ValueError(
                "production palette differs from canonical sourceData palette"
            )
        outputs[f"{name}/QuakeBSPTexturePalette.bin"] = palette
        from snes_tooling.quake.quake_gameplay_production_world import (
            recover_packed_files,
        )

        packed_outputs, packed_contract = recover_packed_files(
            source_data,
            segments,
            labels,
            lambda segment: package_segment(segment, rom, msu),
            dict(original, **source_bound),
            palette_inverse=palette_inverse,
        )
        for filename, payload in packed_outputs.items():
            outputs[f"{name}/{filename}"] = payload
        world_metadata = json.loads(packed_outputs["QuakeBSPMetadata.json"])
        if (
            world_metadata["source"]["pak_sha256"] != gameplay["pakSha256"]
            or world_metadata["source"]["bsp_sha256"] != gameplay["bspSha256"]
        ):
            raise ValueError(
                "production packed world and gameplay PAK/BSP identities differ"
            )
        header = HEADER.unpack_from(restored[0])
        data = b"".join(restored)
        coverage = {}
        sprites = []
        model_names = aliases["instrumentation"]["modelNames"]
        for index in range(header[4]):
            row = SPRITE.unpack_from(data, header[10] + index * SPRITE.size)
            sprites.append(row)
            key = (row[1], row[7]) if len(model_names) > 1 else row[7]
            coverage.setdefault(key, []).append(row[8])
        mdl_density = verified_mdl_density(aliases, sprites)
        from snes_tooling.quake.quake_combat_particles import MODEL as impact_model
        from snes_tooling.quake.quake_teleport_particles import MODEL as teleport_model
        single_view = [model for model in model_names if model in (teleport_model, impact_model)]
        for key, views in coverage.items():
            direct = len(model_names) > 1 and model_names[key[0]] in single_view
            if sorted(views) != ([0] if direct else list(range(8))):
                raise ValueError("production alias frame lacks its declared sprite views")
        roster = verified_actor_roster(gameplay, aliases, coverage)
        if any(actor["model"] not in model_names for actor in roster):
            raise ValueError("production actor model is absent from alias metadata")
        maps.append(
            dict(
                map=name,
                referenceData=name,
                mode=aliases["mode"],
                rows=header[3],
                spriteCount=header[4],
                frames=[frame for _, frame in coverage] if len(model_names) > 1 else sorted(coverage),
                cameraPositionUnits=labels.get(b"BSP_PLAYABLE_CAMERA_POSITION_UNITS", 16),
                packedWorld=packed_contract,
                viewsPerFrame=8 if coverage else 0,
                **({"singleViewModels": single_view} if single_view else {}),
                mdlWorldUnitsPerTexel=mdl_density,
                actors=[
                    dict(entityNumber=actor["entityNumber"], model=actor["model"])
                    for actor in roster
                ],
                pakSha256=gameplay["pakSha256"],
                bspSha256=gameplay["bspSha256"],
            )
        )
        evidence.append(
            dict(
                map=name,
                symbols=identity(symbol_payload),
                paletteSegment=container["segment"],
                paletteSegmentOffset=relative,
                metadataBoundByBuildReport=bool(source_bound),
                originalInputClosureVerified=closure is not None,
            )
        )
    source = dict(
        package=identity(build_payload),
        rom=identity(rom),
        msu=identity(msu),
        maps=evidence,
    )
    if layout_payload:
        source["layout"] = identity(layout_payload)
    if closure_payload:
        source["inputClosure"] = identity(closure_payload)
    index = dict(
        schema="quake-production-gameplay-aliases-v1",
        maps=maps,
        payloads=[
            dict(file=path, **identity(blob)) for path, blob in sorted(outputs.items())
        ],
        source=source,
    )
    outputs["production-aliases.json"] = json_bytes(index)
    for relative, payload in outputs.items():
        path = Path(output) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    return dict(
        passed=True,
        recoveredOriginalAliasChunks=recovered_chunks,
        maps=[
            dict(map=row["map"], sprites=row["spriteCount"], actors=len(row["actors"]))
            for row in maps
        ],
        elapsedSeconds=round(monotonic() - started, 3),
    )


def main(argv=None):
    started = monotonic()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snes-package", required=True, type=Path, metavar="BUILD_REPORT",
                        help="path to quake-playable-build.json inside the playable package")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--input-closure", type=Path)
    arguments = parser.parse_args(argv)
    try:
        report = recover(
            arguments.snes_package, arguments.output, arguments.input_closure
        )
    except (OSError, ValueError, KeyError, struct.error) as error:
        print(
            json.dumps(
                dict(
                    passed=False,
                    error=str(error),
                    elapsedSeconds=round(monotonic() - started, 3),
                )
            )
        )
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
