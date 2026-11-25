"""Build the mandatory-MSU playable cartridge independently of demos."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from snes_tooling import Workspace
from snes_tooling.quake.build_quake_project import stage_target
from snes_tooling.quake.generate_quake_snes_weapon_sprites import PREFIX as WEAPON_PREFIX, build_live_outputs
from snes_tooling.quake.quake_bsp_assets import PakArchive, locate_quake_pak
from snes_tooling.quake.quake_bsp_validation import parse_cpu_symbols
from snes_tooling.quake.quake_playable_archive import binding_include, compose
from snes_tooling.quake.quake_playable_layout import LevelLayout, Placement, Span, read_spans, brush_vertex_group, cpu_address, HALFBANK, GSU_ROM_BYTES, ROM_BYTES
from snes_tooling.quake.quake_playable_maps import MAP_NAMES, config_for, id_for, read_tape_boot
from snes_tooling.quake.quake_playable_walk_hull import (
    COMPACT_POINT_MAPS, INLINE_WALK_MAPS, build_explobox_walk_resume,
    prepare_compact_point_hull, prepare_inline_walk_hull,
)
from snes_tooling.quake.quake_playable_materials import plan_materials, replace_pixel_spans
from snes_tooling.quake.quake_playable_alias_budget import compact_empty_alias_spans, split_live_sprite_tail
from snes_tooling.quake.quake_playable_structural_budget import compact_brush_structure_spans
from snes_tooling.quake.quake_playable_link import prepare_module_files, require_segment_declarations
from snes_tooling.quake.quake_playable_relocation import integer_definitions
from snes_tooling.quake.quake_playable_validation import capture_module_manifest
from snes_tooling.quake.quake_status_hud import build_status_hud
from snes_tooling.quake.quake_status_hud_obj import pack_status_hud_overlays, textureless_display_palette
from snes_tooling.quake.quake_pickup_notice import (
    FONT_VRAM as PICKUP_FONT_VRAM, MAP_VRAM as PICKUP_MAP_VRAM, build_pickup_blend, build_pickup_display,
)
from snes_tooling.quake.quake_start_hub import hub_centerprints
from snes_tooling.quake.quake_face_colors import bake_face_colors, brush_material_location
from snes_tooling.quake.quake_weapon_obj import (
    PLACEMENT_BYTES, alias_pixel_ranges, build_weapon_assets, centerprint_rows, encode_centerprints, encode_display_tints,
    encode_obj_assets, permute_alias_pixels,
    permute_colormap, permute_words,
)
from snes_tooling.quake.quake_playable_visibility_stream import build_visibility_stream
from snes_tooling.quake.quake_playable_world_lightmap import (
    build_resident_lightmaps, build_world_lightmap_plan,
)
from snes_tooling.quake.quake_playable_relocation import compact_face_owners, face_owner_format, index_quakec_functions
from snes_tooling.quake.quake_playable_raw_contours import build_raw_contours
from snes_tooling.quake.quake_playable_world_coordinates import build_world_affine_uv
from snes_tooling.quake.quake_playable_texture_budget import (
    prune_unused_world_texture_spans, compact_last_world_texture_span, compact_brush_texture_spans,
)
from snes_tooling.shared.processes import python_child_environment
from snes_tooling.shared.snes_example_build import default_libsfx, project_layout

MAPS = tuple((name, config_for(name)) for name in MAP_NAMES)
E1M1_LATE_CPU_SEGMENTS = (
    ("BSP_CPU_BRR_INSTALL", 176),
    ("BSP_CPU_BRR_BULK", 208),
    ("BSP_CPU_POINT_WIDE_CACHE", 128),
    ("BSP_CPU_POINT_RANKED_SPLIT", 32),
    ("BSP_CPU_POINT_ALIGNED_DIVIDE", 48),
)
WALK_RESUME_SEGMENT = "BSP_CPU_WALK_RESUME"
LIFT_COLLISION_SEGMENT = "BSP_CPU_LIFT_COLLISION"
SHOT_PAIR_SEGMENT = "BSP_CPU_SHOT_PAIR"
PICKUP_PALETTE_SEGMENT = "BSP_CPU_PICKUP_PALETTE"
FOOTING_SEGMENT = "BSP_CPU_FOOTING_LOOKUP"
WORLD_AFFINE_VARIANT_MAPS = {"start", "e1m1", "e1m4"}
RESIDENT_LIGHTMAP_PROFILES = {
    name: Path(f"config/snes_quake/{name}-resident-lightmap-faces.json")
    for name in ("e1m2", "e1m3", "e1m4")
}


def _json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True)+"\n", encoding="utf-8")


def source_asset_records(data):
    """Bind all original packed inputs needed by production C++ consumers."""
    names = {"QuakeBSPAliasAssets.json", "QuakeBSPQuakeCGameplay.json",
             "QuakeBSPMetadata.json", "QuakeBSPBrushAssets.json",
             "QuakeBSPTexturePalette.bin", "QuakeBSPReciprocal.bin",
             "QuakeBSPTurbulenceTable.bin"}
    families = ("QuakeBSPAliasRuntime", "QuakeBSPWorld", "QuakeBSPBrushRuntime",
                "QuakeBSPBrushFragments", "QuakeBSPBrushTexturePixels")
    names.update(path.name for path in data.iterdir()
                 if path.suffix == ".bin" and path.name.startswith(families))
    result = []
    for filename in sorted(names):
        payload = (data / filename).read_bytes()
        result.append(dict(file=filename, bytes=len(payload), sha256=sha256(payload).hexdigest()))
    return result

def _run(command, workspace, example, log):
    env = python_child_environment(workspace.root/"tools", environment=dict(os.environ,
        SNES_WORKSPACE=str(workspace.root), SNES_QUAKE_EXAMPLE=str(example)))
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8") as stream:
        result = subprocess.run(command, cwd=workspace.root, env=env, stdout=stream,
                                stderr=subprocess.STDOUT)
    if result.returncode:
        # JSON tool receipts may occupy one very long line. Keep the diagnostic
        # tail bounded without hiding ordinary assembler/linker failures.
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
        tail = "\n".join(line[:1200] for line in lines[-12:] if not line.startswith("{"))
        raise RuntimeError(f"command failed ({result.returncode}); log={log}\n{tail}")


def _check_baseline(example, config, receipt, libsfx, *, allow_dirty=False):
    """Reuse only the existing variant/native/asset contracts, without rewriting provenance."""
    from snes_tooling.quake import build_quake_variant as variant
    from snes_tooling.quake.quake_asset_preflight import require_asset_chain_receipt
    from snes_tooling.shared import snes_example_build as native

    started = time.monotonic()
    example, config, receipt, libsfx = map(Path, (example, config, receipt, libsfx))
    if not allow_dirty and not variant.source_state()["clean"]:
        raise RuntimeError("baseline reuse requires a clean tracked worktree; use --allow-dirty for local iteration")
    document = json.loads(receipt.read_bytes())
    if document.get("schema") != "quake-bsp-variant-build-v1":
        raise ValueError("unsupported source variant receipt")
    config, config_sha256 = variant.assets.validated_config_identity(config)
    require_asset_chain_receipt(config)
    variant.assets.require_config_identity(config, config_sha256)
    asset_path = example/"Data"/variant.assets.ASSET_CHAIN_RECEIPT
    asset_document = json.loads(asset_path.read_bytes())
    for role, recorded, current in (
        ("config", document.get("config"), config),
        ("asset receipt", document.get("assetGeneration", {}).get("receipt"), asset_path),
    ):
        if recorded != variant.fingerprint(current):
            raise ValueError(f"source variant {role} changed")
    if (document.get("selection") != asset_document["selection"]
            or document["assetGeneration"].get("outputAggregateSha256")
            != asset_document["outputs"]["aggregateSha256"]):
        raise ValueError("source variant asset binding changed")
    # Reject stale native inputs before recomputing the derived hulls.
    fresh = native.require_snes_example_build_fresh(example, "quake")
    fresh_path = Path(fresh["receipt"])
    fresh_document = json.loads(fresh_path.read_bytes())
    recorded_tools = {row["path"] for row in fresh_document["linkInputs"]}
    for name in ("ca65", "ld65"):
        if str(native.require_cc65_tool(libsfx, name).resolve()) not in recorded_tools:
            raise ValueError("source variant libSFX tool path changed")
    layout = native.project_layout(example)
    rom = layout.output_dir/"quake.sfc"
    for role, current in (("rom", rom), ("freshnessReceipt", fresh_path)):
        if document.get("build", {}).get(role) != variant.fingerprint(current):
            raise ValueError(f"source variant {role} changed")
    if config.name in tuple(map(config_for, INLINE_WALK_MAPS)):
        prepare_inline_walk_hull(example, check=True)
    elif config.name in tuple(map(config_for, COMPACT_POINT_MAPS)):
        prepare_compact_point_hull(example, check=True)
    native.run_example_source_generator(example, check=True)
    kernels = native.validate_cache_kernels(Path(fresh["debugInfo"]), segment_name=None, require=True)
    native.validate_cache_manifest(kernels, layout.cache_kernel_manifest, segment_name=None)
    return dict(passed=True, reusedBuild=True, receipt=str(receipt),
        originalSource=document["source"], romSha256=document["build"]["rom"]["sha256"],
        dependencyCount=fresh["dependencyCount"], cacheKernelCount=len(kernels),
        elapsedSeconds=round(time.monotonic()-started, 3))


def _try_reuse_baseline(workspace, output, name, example, config, receipt, libsfx, allow_dirty):
    # Asset modules bind SNES_QUAKE_EXAMPLE during import. Each map therefore
    # checks its existing contracts in the same isolated child environment as a build.
    check = ("import json,sys; from snes_tooling.quake.build_quake_playable import _check_baseline; "
             "print(json.dumps(_check_baseline(*sys.argv[1:5], allow_dirty=sys.argv[5]=='1'))) ")
    command = [sys.executable, "-c", check, str(example), str(config), str(receipt), str(libsfx),
               "1" if allow_dirty else "0"]
    try:
        _run(command, workspace, example, output/f"{name}-source-reuse.log")
    except RuntimeError:
        # A stale or missing contract uses the ordinary build path, retaining
        # --reuse-assets so an invalid asset receipt still fails closed there.
        return False
    print(f"Reusing validated playable {name} source build", flush=True)
    return True


def baseline(workspace, output, module, libsfx, *, reuse_assets=False, allow_dirty=False,
             weapon_obj=True, cpu_assembly_only=False, recorded_tape=False):
    name, config_name = MAPS[module]
    # Stage the same CPU feature for the size probe and relocated link.
    cpu_preamble = b"QC_QUEUED_INPUT = 1\nPLAYABLE_MENU_FONT_PLACEMENT = 1\n"
    if recorded_tape:
        cpu_preamble += b"PLAYABLE_RECORDED_TAPE = 1\n"
    if name in INLINE_WALK_MAPS:
        cpu_preamble += b"PLAYABLE_REGISTER_WALK_TRACE = 1\n"
    elif name in COMPACT_POINT_MAPS:
        cpu_preamble += b"PLAYABLE_REGISTER_POINT_TRACE = 1\n"
    if name == "e1m1":
        cpu_preamble += b"PLAYABLE_LARGE_DISTANCE_CACHE = 1\nPLAYABLE_FX3_PLANE_DISTANCE = 1\n"
        cpu_preamble += b"PLAYABLE_E1M1_PREFETCH_GAMEPLAY_CODE = 1\n"
        cpu_preamble += b"PLAYABLE_E1M1_STATEMENT_BATCH = 1\nPLAYABLE_E1M1_POINT_OBLIQUE = 1\nPLAYABLE_POINT_MOVING_RANK = 1\n"
        cpu_preamble += b"PLAYABLE_E1M1_LOCAL_COPY_END = 1\nPLAYABLE_E1M1_ACTOR_BOUNDS = 1\n"
        cpu_preamble += b"PLAYABLE_E1M1_TRACE_LAYOUT = 1\n"
        cpu_preamble += b"PLAYABLE_E1M1_DUE_REFILL_WAIT = 6144\n"
    if name in ("e1m1", "e1m2", "e1m3", "e1m4"):
        cpu_preamble += b"PLAYABLE_PAIRED_WORLD_CODE = 1\n"
    if name != "start":
        cpu_preamble += b"PLAYABLE_SELECTOR_COOP = 1\n"
    if name != "start":
        cpu_preamble += b"PLAYABLE_COORDINATE_COOP = 1\n"
    gsu_preamble = b"PLAYABLE_WORLD_AFFINE_UV_CODE = 1\n"
    if name != "start":
        brush_fragment = b"PLAYABLE_FLAT_BRUSH_FRAGMENT = 1\nPLAYABLE_FLAT_BRUSH_FRAGMENT_SELECTOR = 1\n"
        cpu_preamble += brush_fragment
        gsu_preamble += brush_fragment
    if name in ("e1m2", "e1m3", "e1m4"):
        gsu_preamble += b"PLAYABLE_Q12_QUOTIENT_PROOF = 1\n"
    if name == "e1m4":
        gsu_preamble += b"PLAYABLE_Q12_COMPACT_RETURN = 1\n"
    if name == "e1m1":
        gsu_preamble += b"PLAYABLE_FX3_PLANE_DISTANCE = 1\nPLAYABLE_E1M1_X3_WORLD_CLIP = 1\n"
        gsu_preamble += b"PLAYABLE_WORLD_AFFINE_UV_DESCRIPTOR_CODE = 1\n"
        gsu_preamble += b"PLAYABLE_E1M1_CULL_STREAMED_ALIAS = 1\n"
        gsu_preamble += b"PLAYABLE_T4_DEFER_EDGE_ADVANCE = 1\n"
    if name in ("e1m1", "e1m2", "e1m3", "e1m4"):
        gsu_preamble += b"PLAYABLE_E1M1_T4_RIGHT_STAGE_CODE = 1\n"
    if name in ("e1m1", "e1m2"):
        gsu_preamble += b"PLAYABLE_ENDPOINT_RANGE_CHECK = 1\n"
    if name in ("e1m1", "e1m2", "e1m3", "e1m4"):
        gsu_preamble += b"PLAYABLE_PAIRED_WORLD_CODE = 1\n"
    if name in ("e1m2", "e1m3", "e1m4") and weapon_obj:
        resident_world = b"PLAYABLE_RESIDENT_WORLD = 1\n"
        cpu_preamble += resident_world
        gsu_preamble += resident_world
        if name in ("e1m2", "e1m4"):
            snapshot = b"PLAYABLE_RESIDENT_WORLD_SNAPSHOT = 1\n"
            cpu_preamble += snapshot
            gsu_preamble += snapshot
    if name in ("e1m1", "e1m2", "e1m3", "e1m4"):
        gsu_preamble += b"PLAYABLE_SELECTOR_FAN_CACHE = 1\n"
    if weapon_obj and name in ("e1m2", "e1m4"):
        cpu_preamble += b"PLAYABLE_POINT_SIGHT_CACHE = 1\nPLAYABLE_KNIGHT_POINT_FRACTIONS = 1\n"
    if name == "e1m2":
        cpu_preamble += b"PLAYABLE_LIGHTMAP_REGIONS = 1\n"
    if name in ("e1m2", "e1m3", "e1m4"):
        cpu_preamble += b"PLAYABLE_FAST_WALK_PPU_MUL = 1\n"
    if name == "e1m3":
        cpu_preamble += b"PLAYABLE_WALK_FOLD_XY = 1\nPLAYABLE_WALK_THREE_AXIS_DELTA = 1\n"
    if name in ("e1m2", "e1m3"):
        min_paired_span = 9 if name == "e1m2" else 17
        gsu_preamble += f"PLAYABLE_PAIRED_MIN_SPAN_WIDTH = {min_paired_span}\n".encode("ascii")
        cpu_preamble += b"PLAYABLE_RESIDENT_NIBBLE_LIGHTMAPS = 1\n"
        gsu_preamble += b"PLAYABLE_RESIDENT_NIBBLE_LIGHTMAPS = 1\n"
    if name == "e1m4":
        gsu_preamble += b"PLAYABLE_PAIRED_MIN_SPAN_WIDTH = 17\n"
    if name in ("e1m2", "e1m3", "e1m4"):
        gsu_preamble += b"PLAYABLE_T4_DEFER_EDGE_ADVANCE = 1\nPLAYABLE_PAIRED_FAST_INTERPOLATION = 1\n"
    if name == "e1m1":
        gsu_preamble += b"PLAYABLE_PAIRED_FAST_INTERPOLATION = 1\nPLAYABLE_PAIRED_NO_PIXEL_REPEAT = 1\n"
    if name in ("e1m2", "e1m3"):
        gsu_preamble += b"PLAYABLE_PAIRED_EXPANDED_GRID = 1\n"
    if name in ("e1m1", "e1m2", "e1m3", "e1m4"):
        gsu_preamble += b"PLAYABLE_PAIRED_TEXEL_REUSE = 1\n"
    if name == "e1m1":
        gsu_preamble += b"PLAYABLE_PAIRED_CACHED_SHORT_SPANS = 1\n"
    if name in WORLD_AFFINE_VARIANT_MAPS:
        gsu_preamble += b"PLAYABLE_WORLD_AFFINE_UV_VARIANTS_CODE = 1\n"
    if name in ("e1m1", "e1m2", "e1m3", "e1m4"):
        gsu_preamble += b"PLAYABLE_BRUSH_PROJECTED_REUSE_CODE = 1\n"
    if name in ("e1m2", "e1m3"):
        brush_affine = b"PLAYABLE_BRUSH_FRAGMENT_AFFINE = 1\n"
        cpu_preamble += brush_affine
        gsu_preamble += brush_affine
    if name in ("e1m2", "e1m4"):
        gsu_preamble += b"PLAYABLE_PACKET_SCREEN_REUSE_CODE = 1\n"
    example = stage_target(workspace, f"playable-{name}-source", config_name=config_name,
                           cache_kernel_manifest="GSUCacheKernels-playable.json",
                           reuse_playable_shader=reuse_assets, cpu_preamble=cpu_preamble,
                           gsu_preamble=gsu_preamble)
    receipt_name = "quake.cpu-assembly.json" if cpu_assembly_only else "quake.variant-build.json"
    receipt = project_layout(example).build_dir / receipt_name
    config = workspace.root/"config/snes_quake"/config_name
    source_stage = "--cpu-assembly-only" if cpu_assembly_only else "--playable-source-cache"
    command = [sys.executable, "-m", "snes_tooling.quake.build_quake_variant",
        "--config", str(config),
        "--libsfx", str(libsfx), "--receipt", str(receipt), source_stage]
    if reuse_assets:
        command.append("--reuse-assets")
    if allow_dirty:
        command.append("--allow-dirty")
    if cpu_assembly_only:
        _run(command, workspace, example, output/f"{name}-cpu-assembly.log")
        return json.loads(receipt.read_bytes())
    reused = reuse_assets and _try_reuse_baseline(
        workspace, output, name, example, config, receipt, libsfx, allow_dirty)
    if not reused:
        print(f"Building playable {name} source assets", flush=True)
        _run(command, workspace, example, output/f"{name}-source.log")
    document = json.loads(receipt.read_bytes())
    rom = Path(document["build"]["rom"]["path"])
    if sha256(rom.read_bytes()).hexdigest() != document["build"]["rom"]["sha256"]:
        raise ValueError(f"source ROM changed after build: {name}")
    return dict(example=example, rom=rom, receipt=receipt, reusedBuild=bool(reused),
                spans=read_spans(module, rom, rom.with_suffix(".dnfo")))


def package_binding(workspace, baselines, hud_payload=b"", weapon_payload=b"", *, tape_boot=None):
    digest = sha256(b"quake-playable-msu-v1\0")
    if tape_boot is not None:
        digest.update(b"tape boot\0" + bytes((id_for(tape_boot.initial_map), tape_boot.skill, tape_boot.always_run)))
    digest.update(sha256(hud_payload).digest())
    digest.update(sha256(weapon_payload).digest())
    for row in baselines:
        digest.update(sha256(row["rom"].read_bytes()).digest())
    source = workspace.root/"src/snes_quake"
    files = sorted(p for p in source.rglob("*") if p.is_file()
        and p.suffix in (".s", ".sgs", ".i")
        and "Data" not in p.relative_to(source).parts
        and "fixtures" not in p.relative_to(source).parts)
    tools = workspace.root/"tools/snes_tooling/quake"
    files += [tools/name for name in (
        "build_quake_playable.py", "quake_playable_archive.py", "quake_playable_layout.py",
        "quake_playable_link.py", "quake_playable_relocation.py", "quake_playable_texture_budget.py",
        "quake_playable_validation.py", "quake_playable_maps.py", "quake_playable_structural_budget.py",
        "quake_playable_materials.py", "quake_playable_sprite_stream.py", "quake_playable_alias_budget.py",
        "quake_playable_visibility_stream.py", "quake_playable_world_lightmap.py", "quake_playable_walk_hull.py",
        "quake_playable_world_coordinates.py", "quake_status_hud.py", "quake_status_hud_obj.py", "quake_face_colors.py",
        "generate_quake_snes_weapon_sprites.py")]
    files.extend(workspace.root / path for path in RESIDENT_LIGHTMAP_PROFILES.values())
    if weapon_payload.startswith(b"OBJ\0"):
        files.extend((tools/"quake_weapon_obj.py", tools/"quake_pickup_notice.py"))
    for path in files:
        digest.update(path.relative_to(workspace.root).as_posix().encode()+b"\0")
        digest.update(sha256(path.read_bytes()).digest())
    return digest.digest()[:16]


def build_module(workspace, output, module, baseline_row, layout, binding, libsfx, weapon, *, tape_boot=None):
    name = MAPS[module][0]
    example = output/"modules"/name/"src/snes_quake"
    if example.exists():
        # This is one bounded generated module directory, never a checkout.
        if not example.resolve().is_relative_to(output.resolve()):
            raise ValueError("playable module path escaped its build root")
        shutil.rmtree(example)
    shutil.copytree(baseline_row["example"], example)
    bins = output/"modules"/name/"segments"
    bins.mkdir(parents=True, exist_ok=True)
    prepared = prepare_module_files(example, layout, module, bins, tape_boot=tape_boot)
    for relative, payload in (prepared.files | {f"Data/{name}": data for name, data in weapon.items()}).items():
        path = example/relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    if hasattr(layout, "weapon_obj"):
        forward = layout.weapon_obj[0]
        data = example/"Data"
        for filename in ("QuakeBSPTexturePalette.bin", "QuakeBSPFlashPalette.bin"):
            path = data/filename
            path.write_bytes(permute_words(path.read_bytes(), forward))
        for filename in ("QuakeBSPLightmapColormap.bin", "QuakeBSPLightmapLevelZeroColormap.bin"):
            path = data/filename
            path.write_bytes(permute_colormap(path.read_bytes(), forward))
        for index, ranges in enumerate(layout.weapon_alias_ranges[module]):
            path = data/f"QuakeBSPAliasRuntime{index}.bin"
            path.write_bytes(permute_alias_pixels(path.read_bytes(), ranges, forward))
    (example/"Data/QuakeBSPPlayableBinding.i").write_bytes(binding_include(binding))
    if name == "e1m1":
        (example/"Data/QuakeIndustrialAmbient.i").write_bytes(layout.industrial_audio.include)
        spc = example/"quake.s700"
        spc.write_bytes(b"PLAYABLE_E1M1_SPC_CARRIER = 1\n" + spc.read_bytes())
    hud, *hud_offsets = layout.status_hud
    (example/"Data/QuakeBSPStatusHud.i").write_bytes(hud.assembly(*map(cpu_address, hud_offsets)))
    if hasattr(layout, "weapon_obj"):
        from snes_tooling.quake.quake_weapon_obj import assembly_include
        offsets = layout.weapon_obj_offsets
        if name == "e1m1":
            offsets = (*offsets[:-1], offsets[-1] + layout.e1m1_message_offset)
        lines = layout.e1m1_message_lines if name == "e1m1" else 4
        constants = assembly_include(offsets, centerprint_lines=lines)
        if name == "e1m1":
            base = layout.weapon_obj_offsets[-1]
            constants += (
                f"PICKUP_ROWS = ${cpu_address(base + layout.pickup_row_offset):06X}\n"
                f"PICKUP_FONT = ${cpu_address(base + layout.pickup_font_offset):06X}\n"
                f"PICKUP_FONT_BYTES = {layout.pickup_font_bytes}\n"
                f"PICKUP_MAP_VRAM = ${PICKUP_MAP_VRAM:04X}\n"
                f"PICKUP_FONT_VRAM = ${PICKUP_FONT_VRAM:04X}\n"
                f"PICKUP_BLEND = ${cpu_address(layout.presentation_offsets['pickup-blend']):06X}\n"
            ).encode("ascii")
            if getattr(layout, "pickup_blend_packed", False):
                constants += b"PICKUP_BLEND_PACKED = 1\n"
        if module:
            first = layout.placements[0, "BSP_WEAPON_TABLES"]
            palette = first.cpu + first.size - 512
            constants += f"PLAYABLE_SHARED_FLASH_PALETTE = ${palette:06X}\n".encode("ascii")
        (example/"Data/QuakeBSPWeaponObj.i").write_bytes(constants)
    manifest = json.loads((example/"snes-project.json").read_bytes())
    # The source view has already passed its normal receipt/source generator.
    # This derived view contains deliberately relocated pointers and must not
    # be overwritten by a generator for the original fixed layout.
    manifest.pop("sourceGenerator", None)
    manifest["assetGenerator"] = Path(os.path.relpath(
        workspace.root/"tools/commands/snes_quake/generate_snes_example_assets.py", example)).as_posix()
    relocated_manifest = "GSUCacheKernels-relocated-playable.json"
    # A failed relocated link cannot leave a source-view profile looking valid.
    (example/relocated_manifest).unlink(missing_ok=True)
    manifest["cacheKernelManifest"] = relocated_manifest
    _json(example/"snes-project.json", manifest)
    cache_profile = capture_module_manifest(example, libsfx, manifest_name=relocated_manifest)
    _json(output/f"{name}-module-cache-profile.json", cache_profile)
    command = [sys.executable, str(workspace.root/"tools/commands/shared/snes_example_build.py"),
        str(example), "--libsfx", str(libsfx), "--name", "quake-playable", "--skip-asset-generation", "--json"]
    print(f"Linking playable {name} module", flush=True)
    _run(command, workspace, example, output/f"{name}-module.log")
    rom = project_layout(example).output_dir/"quake-playable.sfc"
    if not rom.is_file():
        raise ValueError("missing linked playable module: " + str(rom))
    _json(output/f"{name}-module-preparation.json", prepared.report)
    return dict(example=example, rom=rom, symbols=rom.with_suffix(".cpu.sym"),
                segment_files={(module, key): value for key, value in prepared.segment_files.items()})


def discard_empty_composed_directory(spans):
    composed = [span for span in spans if span.name.startswith("BSP_COMPOSED_")]
    if (len(composed) != 1 or composed[0].name != "BSP_COMPOSED_DIRECTORY"
            or len(composed[0].payload) % 2
            or composed[0].payload.count(0xFF) != len(composed[0].payload)):
        raise ValueError("playable requires a composed directory containing only miss entries")
    return [span for span in spans if span.name != "BSP_COMPOSED_DIRECTORY"], len(composed[0].payload)


def compact_q12_reciprocal_spans(spans):
    prefix = "BSP_DIVIDE_Q12_RECIPROCAL_"
    original = sorted((span for span in spans if span.name.startswith(prefix)),
                      key=lambda span: span.name)
    if [len(span.payload) for span in original] != [HALFBANK] * 3 + [HALFBANK - 4]:
        raise ValueError("Unexpected Q12 reciprocal table layout")
    cold = b"".join(span.payload for span in original[1:])
    if any(cold[0::4]) or any(cold[1::4]):
        raise ValueError("Packed Q12 reciprocal tail has a nonzero high limb")
    lows = b"".join(cold[offset:offset + 2] for offset in range(2, len(cold), 4))
    return [span for span in spans if not span.name.startswith(prefix)] + [
        original[0], replace(original[1], payload=lows[:HALFBANK]),
        replace(original[2], payload=lows[HALFBANK:]),
    ]


def weapon_display_palettes(source, forward):
    """Reuse the linked diagnostic palette and the map's two production palettes."""
    rom = source['rom']
    symbols = parse_cpu_symbols(rom.with_suffix('.cpu.sym').read_text(encoding='utf-8'))
    address = symbols['QuakeBSPUntexturedPalette']
    offset = ((address >> 16) & 0x7f)*HALFBANK + (address & 0x7fff)
    diagnostic = rom.read_bytes()[offset:offset + 512]
    data = source['example'] / 'Data'
    normal = (data / 'QuakeBSPTexturePalette.bin').read_bytes()
    flash = (data / 'QuakeBSPFlashPalette.bin').read_bytes()
    if diagnostic[-32:] != normal[-32:]:
        raise ValueError('linked diagnostic palette does not carry the original font colors')
    if forward is not None:
        normal = permute_words(normal, forward)
        flash = permute_words(flash, forward)
    return normal, diagnostic, flash


def allocate_resident_lightmaps(workspace, layout, baselines, name, *, low, high):
    module = MAP_NAMES.index(name)
    selected = json.loads((workspace.root / RESIDENT_LIGHTMAP_PROFILES[name]).read_bytes())
    directory = (baselines[module]["example"] / "Data/QuakeBSPWorldLightmapDirectory.bin").read_bytes()
    plan = build_resident_lightmaps(directory, layout.world_lightmap_plans[module], selected,
                                    nibbles=name in ("e1m2", "e1m3"))
    offset = layout.allocator.allocate(len(plan.payload), (name, "resident lightmaps"),
                                       low=low, high=high, alignment=16)
    layout.resident_world_lightmaps[module] = plan, offset


def require_shared_spc(baselines):
    reference = None
    for module, row in enumerate(baselines):
        name = MAPS[module][0]
        images = [span for span in row["spans"] if span.name == "SMPCODE"]
        if len(images) != 1:
            raise ValueError(f"{name}: expected one staged SMPCODE image, found {len(images)}")
        image = images[0]
        if reference is None:
            reference = image
        elif image.run != reference.run or image.payload != reference.payload:
            def describe(span):
                return (f"run={span.run:#x}, bytes={len(span.payload)}, "
                        f"SHA-256={sha256(span.payload).hexdigest()}")

            raise ValueError(f"{name}: staged SMPCODE differs from {MAPS[0][0]}: "
                             f"{describe(image)} versus {describe(reference)}; "
                             "regenerate the map staging with the same sound driver and samples")


def place_explobox_walk_resume(layout, module, data):
    # Keep the shared Mode 1 sizing reservation so the playable asset
    # allocation order is identical. Playable modes use other tilemaps.
    keys = [(index, "BSP_CPU_MAP_TILEMAP") for index in layout.modules]
    placement = layout.placements[keys[0]]
    if (placement.storage != "cpu" or placement.size != 2048
            or any(layout.placements[key] != placement for key in keys)):
        raise ValueError("playable Mode 1 tilemaps must share one 2 KiB CPU ROM reservation")
    payload = build_explobox_walk_resume(data)
    for key in keys:
        del layout.placements[key]
        del layout.spans[key]
    span = Span(module, WALK_RESUME_SEGMENT, 0, 0, payload)
    layout.spans[span.key] = span
    layout.placements[span.key] = placement


def build(*, libsfx=None, reuse_assets=False, allow_dirty=False, sources_only=False,
          layout_only=None, cpu_assembly_only=None, weapon_obj=True, tape_boot=None):
    started = time.monotonic()
    tape_boot = read_tape_boot(tape_boot) if tape_boot is not None else None
    workspace = Workspace.discover()
    if not sources_only and cpu_assembly_only is None:
        template = (workspace.root / "src/snes_quake/Map.cfg").read_text(encoding="utf-8")
        require_segment_declarations(template, (WALK_RESUME_SEGMENT, PICKUP_PALETTE_SEGMENT, FOOTING_SEGMENT,
                                                *(name for name, _ in E1M1_LATE_CPU_SEGMENTS)))
    output = workspace.root/"out/snes_quake/playable"
    output.mkdir(parents=True, exist_ok=True)
    libsfx = (libsfx or default_libsfx(workspace.root)).resolve()
    with ThreadPoolExecutor(max_workers=len(MAPS)) as executor:
        tasks = [executor.submit(baseline, workspace, output, module, libsfx,
                 reuse_assets=reuse_assets, allow_dirty=allow_dirty, weapon_obj=weapon_obj,
                 cpu_assembly_only=cpu_assembly_only is not None, recorded_tape=tape_boot is not None)
                 for module in range(len(MAPS))]
        baselines = [task.result() for task in tasks]
    if cpu_assembly_only is not None:
        result = dict(schema="quake-playable-cpu-assembly-v1", passed=True,
            maps={name: row for (name, _), row in zip(MAPS, baselines, strict=True)},
            elapsedSeconds=round(time.monotonic()-started, 3))
        _json(cpu_assembly_only, result)
        return result
    require_shared_spc(baselines)
    if sources_only:
        result = dict(schema="quake-playable-source-build-v1", passed=True,
            maps=[dict(map=MAPS[i][0], rom=str(row["rom"]), receipt=str(row["receipt"]),
                       reusedBuild=row["reusedBuild"])
                  for i, row in enumerate(baselines)], elapsedSeconds=round(time.monotonic()-started, 3))
        _json(output/"source-build.json", result)
        return result
    pak = locate_quake_pak(None)
    pak_digest = sha256(pak.read_bytes()).hexdigest()
    gameplay = [json.loads((row["example"] / "Data/QuakeBSPQuakeCGameplay.json").read_bytes())
                for row in baselines]
    def weapon_source(metadata):
        return metadata["pakSha256"], metadata["stockShotgun"]["viewSequence"], metadata["stockAxe"]["viewSequence"]

    source = weapon_source(gameplay[0])
    if source[0] != pak_digest or any(weapon_source(row) != source for row in gameplay):
        raise ValueError("playable modules must share the selected PAK and weapon animations")
    weapon = build_live_outputs(PakArchive(pak), source[1], axe_sequence=source[2], playable=True, nailgun="stockNailgun" in gameplay[0])
    weapon_payload = weapon[Path(WEAPON_PREFIX + "Data0.bin")]
    obj = None
    if weapon_obj:
        import re
        fixed = set()
        palettes = set()
        for row in baselines:
            data = row["example"]/"Data"
            palettes.add((data/"QuakeBSPTexturePalette.bin").read_bytes())
            sky = (data/"QuakeBSPSkyAssets.i").read_text(encoding="ascii")
            fixed.update(int(i) for i in re.findall(
                r"^BSP_SKY_TOKEN_(?:START|BODY|END|SINGLE) = (\d+)$", sky, re.M))
        if len(palettes) != 1:
            raise ValueError("playable OBJ modules require a shared scene palette")
        forward, poses, core = build_weapon_assets(weapon, palettes.pop(), fixed=fixed)
        weapon_payload = weapon[Path(WEAPON_PREFIX + "Data0.bin")]
        if core != (58, 88, 69, 100):
            raise ValueError("generated weapon no longer covers the assembly occlusion rectangle")
        obj = (forward, core, *encode_obj_assets(poses))
    spans, material_plans, visibility_plans, lightmap_plans = [], {}, {}, {}
    sprite_tails = {}
    face_owner_formats = {}
    if obj:
        tilemap = b"".join((0x4000 if y >= 28 else (
            y // 2 * 16 + 15 - x // 2 | (x & 1) << 14 | (y & 1) << 15
        )).to_bytes(2, "little") for y in range(32) for x in range(32))
        flash_palette = (baselines[0]["example"]/"Data/QuakeBSPFlashPalette.bin").read_bytes()
        # The sizing links encode map-local addresses in the descriptor words.
        # Final modules all assemble the same generated include against DATA0.
        shared_weapon_table = next(s.payload for s in baselines[0]["spans"]
                                   if s.name == "BSP_WEAPON_TABLES")[:-512]
    e1m1 = MAP_NAMES.index("e1m1")
    shot_pair = next((span for span in baselines[e1m1]["spans"]
                      if span.name == SHOT_PAIR_SEGMENT), None)
    lift_collision = next(span for span in baselines[e1m1]["spans"]
                          if span.name == LIFT_COLLISION_SEGMENT)
    indexed_quakec = {}
    for module, row in enumerate(baselines):
        kept, budget = prune_unused_world_texture_spans(row["example"]/"Data", row["spans"], module=module)
        kept, world_tail = compact_last_world_texture_span(row["example"]/"Data", kept, module=module)
        # The playable viewport regenerates every weapon pose into DATA0. The
        # standalone full-height viewport can need a second bank for the same poses.
        kept = [span for span in kept
                if span.name not in ("BSP_WEAPON_DATA1", SHOT_PAIR_SEGMENT, LIFT_COLLISION_SEGMENT)]
        kept, brush_tails = compact_brush_texture_spans(row["example"]/"Data", kept, module=module)
        kept, structure = compact_brush_structure_spans(row["example"]/"Data", kept, module=module)
        kept, empty_alias = compact_empty_alias_spans(row["example"]/"Data", kept, module=module)
        if MAPS[module][0] == "e1m1" or gameplay[module].get("stockKnights"):
            kept, sprite_tails[module] = split_live_sprite_tail(row["example"]/"Data", kept, module)
        material_plans[module] = plan_materials(row["example"]/"Data", module,
                                                palette_map=obj[0] if obj else None)
        kept = replace_pixel_spans(kept, material_plans[module])
        kept, empty_composed_bytes = discard_empty_composed_directory(kept)
        kept = compact_q12_reciprocal_spans(kept)
        dense = (row["example"] / "Data/QuakeBSPQuakeCFunctions.bin").read_bytes()
        indexed = index_quakec_functions(dense)
        if indexed is not None:
            # START and E1M3 keep the descriptors inside the CPU overlay.
            # Its remaining code is relinked at the reduced offsets normally.
            carriers = [span for span in kept if span.name in ("BSP_QUAKEC_FUNCTIONS", "BSP_QUAKEC")
                        and dense in span.payload]
            if len(carriers) != 1 or carriers[0].payload.count(dense) != 1:
                raise ValueError("cannot uniquely locate the original QuakeC function table")
            carrier = carriers[0]
            kept[kept.index(carrier)] = replace(carrier, payload=carrier.payload.replace(dense, indexed))
            indexed_quakec[module] = indexed
        owners = next(span for span in kept if span.name == "BSP_WORLD_FACE_OWNERS")
        packed_owners = compact_face_owners(owners.payload)
        if packed_owners is not None:
            kept[kept.index(owners)] = replace(owners, payload=packed_owners)
            face_owner_formats[module] = face_owner_format(packed_owners)
        visibility_plans[module] = build_visibility_stream(row["example"]/"Data")
        # E1M1's long combat steps overlap the renderer best with resident grids.
        if MAPS[module][0] != "e1m1":
            lightmap_plans[module] = build_world_lightmap_plan(row["example"]/"Data")
        # The final playable link adds the X2 alias HUD clip and the boot-only
        # VBlank arm. The standalone sizing link has neither path.
        link_growth = {"GSU_ALIAS_FLY_CODE": 16, "BSP_QUAKEC": 26}
        # Warm-switch, archived sound initialization and campaign mailbox code
        # only exist in a relocated playable module, after the sizing link.
        link_growth["BSP_CPU_WALK_RUN"] = (1408, 114, 114, 190, 67)[module]
        if MAPS[module][0] == "e1m1":
            # The relocated walk and point loaders both shorten mover adds.
            link_growth["BSP_QUAKEC"] += 32
            # Lazy QuakeC handlers grow beyond the standalone sizing bank.
            link_growth["BSP_QUAKEC"] += 176
            # The linked comparison and IFNOT handlers share one result tail.
            link_growth["BSP_QUAKEC"] += 144
            # The X2 lighting link stores its three Flat brush patch templates in ROM.
            link_growth["GSU_PAIRED_WORLD_ROM_CODE"] = 21
            for prefix in ("", "F3_"):
                link_growth[prefix + "GSU_LIGHTMAP_UNPACK_ROM_CODE"] = 32
                link_growth[prefix + "GSU_FACE_COLOR_CODE"] = 16
        if obj:
            link_growth["GSU_T4_REPLAY_BOUNDS_CODE"] = 54
            link_growth["BSP_QUAKEC"] += 72
            table = next(span for span in kept if span.name == "BSP_WEAPON_TABLES")
            world = next(span for span in kept if span.name == "BSP_WORLD_TEXTURE_AUX")
            data = row["example"]/"Data"
            if (len(flash_palette) != 512 or not table.payload.endswith(flash_palette)
                    or (data/"QuakeBSPFlashPalette.bin").read_bytes() != flash_palette
                    or (data/"QuakeBSPTextureDisplayTilemap.bin").read_bytes() != tilemap
                    or world.payload.count(tilemap) != 1):
                raise ValueError("playable palette or X2 tilemap differs from its native boot contract")
            kept[kept.index(world)] = replace(world, payload=world.payload.replace(tilemap, b""))
            # A source map only carries models available there. All relocated
            # modules point at the final shared descriptor and bob-row table.
            source_frames = len(json.loads((data/(WEAPON_PREFIX + ".json")).read_bytes())["frames"])
            shared_frames = len(json.loads(weapon[Path(WEAPON_PREFIX + ".json")])["frames"])
            if len(table.payload) + 24 * (shared_frames - source_frames) != len(shared_weapon_table) + 512:
                raise ValueError("playable weapon table extent differs between maps")
            if module:
                kept[kept.index(table)] = replace(table, payload=shared_weapon_table)
        if MAPS[module][0] in ("e1m2", "e1m3", "e1m4"):
            # The final link installs and restores both Flat world GSU entry points.
            link_growth["BSP_QUAKEC"] += 38
        if MAPS[module][0] in ("e1m2", "e1m3"):
            # The relocated module validates mover-aware mixed tokens and copies
            # the cached exit-variant table through WRAM.
            link_growth["BSP_QUAKEC"] += 85
        if obj and MAPS[module][0] == "e1m2":
            # Bracket simulation for deferred uploads and invalidate the
            # resident framebuffer when a collision mover changes pose.
            link_growth["BSP_QUAKEC"] += 8 + 377  # Carried weapon OBJ staging and HUD.
        if obj and MAPS[module][0] in ("e1m2", "e1m4"):
            # The final streamed link services opaque-frame snapshot DMA.
            link_growth["BSP_QUAKEC"] += 128
        if MAPS[module][0] == "e1m1" and obj:
            # Keep the existing packing size class when the point trace shrinks.
            # Its order leaves bank-local tails for the late CPU audio code.
            qc_size = next(len(span.payload) for span in kept if span.name == "BSP_QUAKEC")
            link_growth["BSP_QUAKEC"] = max(link_growth["BSP_QUAKEC"], 0x80E9 - qc_size)
        spans.extend(replace(span, payload=span.payload + b"\xff" * link_growth[span.name])
                     if span.name in link_growth else
                     replace(span, payload=weapon_payload) if span.name == "BSP_WEAPON_DATA0" else span
                     for span in kept)
        if obj:
            # The source link has no hardware HUD. Reserve its relocated CPU code.
            spans.append(Span(module, "BSP_CPU_STATUS_HUD_OBJ", 0, 0, bytes(0x100)))
        for prefix in ('', 'F3_'):
            spans.append(Span(module, prefix + 'GSU_FACE_COLOR_CODE', 0, 0x703400, bytes(0x200)))
        if MAPS[module][0] in ("e1m1", "e1m2", "e1m3", "e1m4"):
            # The final playable link supplies the X2 Flat resident row code.
            spans.append(Span(module, "GSU_FLAT_MONOTONE_CODE", 0, 0x703600, bytes(0x200)))
        budget.update(materialPool=material_plans[module].report(),
                      emptyAliasCompaction=empty_alias, emptyComposedDirectoryBytes=empty_composed_bytes,
                      worldTailCompaction=world_tail, brushTextureCompaction=brush_tails,
                      structuralCompaction=structure)
        _json(output/f"{MAPS[module][0]}-texture-budget.json", budget)
    vertex_groups = [brush_vertex_group(row['example']/'Data', module)
                     for module, row in enumerate(baselines)]
    # ld65 bounds every module's code to this reserved prefix and compose
    # independently checks the reclaimed window before writing cartridge data.
    # The stock START, E1M3, and E1M4 prefixes leave room for more shared data.
    # Allow the linked recorded-input code and six bytes for the walk initializer.
    # The tape layout needs the remaining unrounded space for cartridge assets.
    cpu_code_limits = ((0x6971, 0x619E, 0x5C65, 0x64D1, 0x6275) if tape_boot is not None
                       else (0x68E0, 0x6100, 0x5BD0, 0x6450, 0x6270))
    layout = LevelLayout(spans, classic_groups=vertex_groups, reclaim_module_tails=True,
                         cpu_code_limits=cpu_code_limits,
                         hardware_weapon_obj=obj is not None)
    layout.face_owner_formats = face_owner_formats
    layout.material_plans = material_plans
    layout.world_lightmap_plans = lightmap_plans
    layout.world_coordinate_modules = tuple(range(len(MAPS)))
    layout.empty_composed = True
    layout.compact_q12_reciprocals = True
    layout.world_affine_uv = {
        module: build_world_affine_uv(
            row["example"]/"Data",
            extra_modes=MAP_NAMES[module] in WORLD_AFFINE_VARIANT_MAPS,
            descriptor_modes=MAP_NAMES[module] == "e1m1",
        )
        for module, row in enumerate(baselines)
    }
    # Preserve the measured E1M2 placement before unrestricted allocations.
    layout.resident_world_lightmaps = {}
    allocate_resident_lightmaps(workspace, layout, baselines, "e1m2",
                               low=layout.cpu_module_count * HALFBANK, high=0x200000)
    # Tape builds use the existing E1M4 MSU lightmap stream to leave room
    # for recorded input code in all five CPU modules.
    last_bank_residents = ("e1m3", "e1m4") if tape_boot is None else ("e1m3",)
    for name in last_bank_residents:
        allocate_resident_lightmaps(workspace, layout, baselines, name,
                                   low=GSU_ROM_BYTES - HALFBANK, high=GSU_ROM_BYTES)
    forward = obj[0] if obj else None
    hud = build_status_hud(palette_map=forward)
    display_palettes = []
    layout.textureless_palettes = []
    for row in baselines:
        natural, diagnostic, flash = weapon_display_palettes(row, forward)
        textureless, lightmap_rows = textureless_display_palette(
            hud, natural, diagnostic, weapon_obj=obj is not None)
        display_palettes.append((natural, textureless, flash))
        layout.textureless_palettes.append((textureless, lightmap_rows))
    if obj:
        hud = pack_status_hud_overlays(hud, tuple(dict.fromkeys(
            palette for scene in display_palettes for palette in scene)), poses)
    hud_parts = {"hud-graphics": hud.graphics, "hud-maps": hud.maps, "hud-glyphs": hud.glyphs}
    layout.presentation_parts = dict(hud_parts)
    if obj:
        layout.weapon_obj = obj
        start = MAP_NAMES.index('start')
        _, start_messages = hub_centerprints(gameplay[start]['hub'])
        _, messages = hub_centerprints(gameplay[MAP_NAMES.index("e1m1")]["hub"])
        start_centerprints = encode_centerprints(start_messages)
        layout.e1m1_message_offset = len(start_centerprints)
        layout.e1m1_message_lines = max(len(centerprint_rows(message)) for message in messages)
        centerprints = start_centerprints + encode_centerprints(
            messages, line_capacity=layout.e1m1_message_lines, pickup_rows=True)
        pickup_rows, pickup_font = build_pickup_display(pak)
        layout.pickup_row_offset = len(centerprints)
        layout.pickup_font_offset = len(centerprints) + len(pickup_rows)
        layout.pickup_font_bytes = len(pickup_font)
        layout.pickup_blend = build_pickup_blend()
        layout.presentation_parts["pickup-blend"] = layout.pickup_blend
        display = (encode_display_tints(display_palettes[start]), centerprints + pickup_rows + pickup_font)
        # Each page has its own descriptors and OAM DMA source, all within one CPU bank.
        placements = (obj[3][i:i+PLACEMENT_BYTES] for i in range(0, len(obj[3]), PLACEMENT_BYTES))
        payloads = (obj[0], obj[2], *placements, *display)
        layout.weapon_obj_payloads = payloads
        weapon_parts = {f"weapon-{i}": data for i, data in enumerate(payloads)}
        layout.presentation_parts.update(weapon_parts)
        layout.weapon_alias_ranges = {}
        for module, row in enumerate(baselines):
            data = row["example"]/"Data"
            alias = json.loads((data/"QuakeBSPAliasAssets.json").read_bytes())["format"]
            chunks = [(data/f"QuakeBSPAliasRuntime{i}.bin").read_bytes() for i in range(alias["chunkCount"])]
            layout.weapon_alias_ranges[module] = alias_pixel_ranges(chunks, alias["storagePhysicalHalfbanks"])
    layout.indexed_quakec = indexed_quakec
    # This deterministic texture-preserving order leaves room for the late
    # CPU segments after the tape modules consume the extra lower ROM space.
    layout.allocate(preferred_seed=2 if tape_boot is not None else None)
    place_explobox_walk_resume(layout, e1m1, baselines[e1m1]["example"] / "Data")
    layout.status_hud = (hud, *(layout.presentation_offsets[name] for name in hud_parts))
    if obj:
        offsets = tuple(layout.presentation_offsets[name] for name in weapon_parts)
        # All modules read the same far pointers. Keep one table in upper CPU ROM.
        pointers = b"".join(cpu_address(offset).to_bytes(3, "little") for offset in offsets[2:-2])
        directory = layout.allocator.allocate(len(pointers), ("shared", "weapon page pointers"),
            low=GSU_ROM_BYTES, high=ROM_BYTES, alignment=2, bank_bytes=65536)
        layout.weapon_obj_offsets = (*offsets[:-2], directory, *offsets[-2:])
        layout.weapon_obj_payloads = (*payloads[:-2], pointers, *payloads[-2:])
    with ThreadPoolExecutor(max_workers=len(MAPS)) as executor:
        data = [row['example'] / 'Data' for row in baselines]
        layout.face_colors = dict(enumerate(executor.map(bake_face_colors, data)))
    if obj:
        layout.face_colors = {module: tuple(colors.translate(obj[0]) for colors in pair)
                              for module, pair in layout.face_colors.items()}
    layout.brush_color_locations = dict(enumerate(
        brush_material_location(json.loads((path / 'QuakeBSPBrushAssets.json').read_bytes()))[0]
        for path in data))
    layout.raw_world_contours = {e1m1: build_raw_contours(
        layout.allocator, layout.world_affine_uv[e1m1], baselines[e1m1]["example"]/"Data",
        visibility_plans[e1m1])}
    # E1M1's BRR and point-trace helpers fit in bank-local CPU tails.
    # Allocate after presentation and contours so this cannot move GSU data.
    late_cpu_segments = E1M1_LATE_CPU_SEGMENTS
    if getattr(layout, "pickup_blend_packed", False):
        late_cpu_segments += ((PICKUP_PALETTE_SEGMENT, 320),)
    for name, size in late_cpu_segments:
        span = Span(e1m1, name, 0, 0, bytes(size))
        offset = layout.allocator.allocate(size, span.key,
            low=GSU_ROM_BYTES, high=ROM_BYTES, alignment=16, bank_bytes=0x10000)
        layout.spans[span.key] = span
        layout.placements[span.key] = Placement(offset, size, "cpu")
    from snes_tooling.quake.quake_switchable_lights import DIRECTORY_SEGMENT, build_switchable_lights
    lights = build_switchable_lights(data[e1m1], PakArchive(pak), palette_map=obj[0] if obj else None)
    directory_offset = layout.allocator.allocate(lights.directory_bytes, (e1m1, DIRECTORY_SEGMENT),
        low=GSU_ROM_BYTES, high=ROM_BYTES, alignment=2, bank_bytes=0x10000)
    layout.switched_grid_directory = {e1m1: directory_offset}
    software_weapon_modules = []
    if obj:
        for module, row in enumerate(baselines):
            fields = integer_definitions((row["example"] / "Data/QuakeBSPBrushAssets.i").read_text(encoding="utf-8"))
            if not {"QC_NAIL_COUNT", "QC_CAMPAIGN_ITEMS"}.intersection(fields):
                continue
            software_weapon_modules.append(module)
            span = Span(module, "BSP_CPU_X3_WEAPON_VIEW", 0, 0, bytes(448))
            offset = layout.allocator.allocate(len(span.payload), span.key,
                low=GSU_ROM_BYTES, high=ROM_BYTES, alignment=2, bank_bytes=0x10000)
            layout.spans[span.key] = span
            layout.placements[span.key] = Placement(offset, len(span.payload), "cpu")
    # Far loads let the support directory travel with its lookup routine,
    # leaving the rectangle records in the existing interpreter bank.
    hull = integer_definitions((data[e1m1] / "PlayableWalkHull.i").read_text(encoding="ascii"))
    footing_bytes = 176 + hull["PLAYABLE_SHOT_SUPPORT_DIRECTORY_BYTES"]
    late_spans = [(shot_pair, 16)] if shot_pair is not None else []
    late_spans.append((Span(e1m1, FOOTING_SEGMENT, 0, 0, bytes(footing_bytes)), 2))
    late_spans.append((lift_collision, 16))
    for span, alignment in late_spans:
        size = len(span.payload)
        offset = layout.allocator.allocate(size, span.key, low=GSU_ROM_BYTES, high=ROM_BYTES,
                                           alignment=alignment, bank_bytes=0x10000)
        layout.spans[span.key] = span
        layout.placements[span.key] = Placement(offset, size, "cpu")
    cpu_capacity = layout.allocator.capacity_diagnostic(
        low=GSU_ROM_BYTES, high=ROM_BYTES, alignment=16, bank_bytes=0x10000)
    if layout_only is not None:
        report = dict(passed=True, schema="quake-playable-rom-layout-v1",
            placements=layout.summary(), cpuCapacity=cpu_capacity,
            reservations=[dict(offset=start, end=end, bytes=end - start, owner=owner)
                          for start, end, owner in layout.allocator.intervals],
            elapsedSeconds=round(time.monotonic() - started, 3))
        _json(layout_only, report)
        return report
    stream_cursor = max((p.offset + p.size for p in layout.placements.values()
                         if p.storage == "msu"), default=ROM_BYTES)
    layout.sprite_tails = {}
    for module, tail in sprite_tails.items():
        layout.sprite_tails[module] = (stream_cursor, tail)
        stream_cursor += len(tail)
    layout.visibility_streams = {}
    for module, plan in visibility_plans.items():
        layout.visibility_streams[module] = (plan, stream_cursor)
        stream_cursor += len(plan.payload)
    from snes_tooling.quake.quake_intermission import planar_stream
    intermission = planar_stream(PakArchive(pak), obj[0] if obj else bytes(range(256)))
    layout.intermission = {e1m1: (intermission, stream_cursor)}
    stream_cursor += len(intermission)
    if software_weapon_modules:
        from snes_tooling.quake.quake_x3_software_weapon import build
        prefix = WEAPON_PREFIX
        x3_weapon, first_pose, phase_sizes = build(
            json.loads(weapon[Path(prefix+".json")]),
            weapon[Path(prefix+".i")].decode("ascii"),
            weapon[Path(prefix+"Data0.bin")])
        layout.x3_software_weapon = (x3_weapon, stream_cursor, first_pose, len(phase_sizes)//3)
        stream_cursor += len(x3_weapon)
    layout.face_colors[e1m1], colors = lights.color_tables(layout.face_colors[e1m1])
    layout.switchable_lights = {e1m1: (lights, colors, stream_cursor)}
    _json(output/"layout.json", layout.summary())
    asset_deduplication = layout.deduplication_summary()
    asset_deduplication["gsuCapacity"] = layout.allocator.capacity_diagnostic(
        low=layout.cpu_module_count*HALFBANK, high=GSU_ROM_BYTES, alignment=16)
    asset_deduplication["cpuCapacity"] = cpu_capacity
    _json(output/"asset-deduplication.json", asset_deduplication)
    from snes_tooling.quake.quake_e1m1_ambient import build_ambient_bank
    layout.industrial_audio = build_ambient_bank(PakArchive(pak))
    binding = package_binding(workspace, baselines, hud.payload + layout.industrial_audio.payload,
        b"OBJ\0"+weapon_payload+b"".join(layout.weapon_obj_payloads)+layout.pickup_blend+x3_weapon
        if obj else weapon_payload, tape_boot=tape_boot)
    with ThreadPoolExecutor(max_workers=len(MAPS)) as executor:
        tasks = [executor.submit(build_module, workspace, output, module, baselines[module],
                                 layout, binding, libsfx, weapon, tape_boot=tape_boot) for module in range(len(MAPS))]
        modules = [task.result() for task in tasks]
    segment_files = {key: value for row in modules for key, value in row["segment_files"].items()}
    rom, sidecar, result = compose(layout, [row["rom"] for row in modules],
        [row["symbols"] for row in modules], segment_files, binding, tape_boot=tape_boot)
    rom_path = output/"quake-playable.sfc"
    rom_path.write_bytes(rom)
    rom_path.with_suffix(".msu").write_bytes(sidecar)
    from snes_tooling.quake.quakec_powerups import write_artifact_tracks
    result["audioTracks"] = write_artifact_tracks(PakArchive(pak), rom_path)
    for i, row in enumerate(modules):
        for suffix in (".cpu.sym", ".dnfo", ".dmap"):
            source = row["rom"].with_suffix(suffix)
            if source.is_file():
                shutil.copyfile(source, output/f"quake-playable.{MAPS[i][0]}{suffix}")
                if MAPS[i][0] == result["defaultMap"]:
                    shutil.copyfile(source, rom_path.with_suffix(suffix))
    result.update(passed=True, rom=str(rom_path), sidecar=str(rom_path.with_suffix(".msu")),
        assetDeduplication=asset_deduplication,
        maps=[dict(map=MAPS[i][0], data=str(row["example"]/"Data"),
                   sourceData=str(baselines[i]["example"]/"Data"),
                   sourceAssets=source_asset_records(baselines[i]["example"]/"Data"),
                   symbols=str(row["symbols"]),
                   debug=str(row["rom"].with_suffix(".dnfo"))) for i, row in enumerate(modules)],
        elapsedSeconds=round(time.monotonic()-started, 3))
    _json(output/"quake-playable-build.json", result)
    return result


def main(argv=None):
    started = time.monotonic()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print the playable package report")
    parser.add_argument("--libsfx", type=Path)
    parser.add_argument("--reuse-assets", action="store_true")
    parser.add_argument("--tape-boot", type=Path, metavar="TAPE",
                        help="cold boot a recorded video tape's map, difficulty and Always Run settings")
    parser.add_argument("--weapon-obj", action=argparse.BooleanOptionalAction, default=True,
                        help="use native hardware sprites for playable X2 weapons (default: enabled)")
    parser.add_argument("--allow-dirty", action="store_true")
    stage = parser.add_mutually_exclusive_group()
    stage.add_argument("--sources-only", action="store_true", help="qualify the registered source modules before packaging")
    stage.add_argument("--layout-only", type=Path, metavar="REPORT",
                       help="write ROM placements and reservations without linking playable modules")
    stage.add_argument("--cpu-assembly-only", type=Path, metavar="REPORT",
                       help="assemble the five playable CPU sources before linking")
    args = parser.parse_args(argv)
    try:
        from contextlib import redirect_stdout
        options = vars(args).copy()
        as_json = options.pop("json")
        with redirect_stdout(sys.stderr if as_json else sys.stdout):
            result = build(**options)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Playable build failed: {error}; elapsed={time.monotonic()-started:.3f}s", file=sys.stderr)
        return 1
    report = args.cpu_assembly_only or args.layout_only or Workspace.discover().root / 'out/snes_quake/playable'
    print(json.dumps(result, indent=2) if as_json else f"Playable build passed; report={report}; elapsed={result['elapsedSeconds']:.3f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
