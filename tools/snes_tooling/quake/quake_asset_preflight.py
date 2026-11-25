"""Cheap binding checks before running the configured Quake asset chain."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


BOUND = {
    "metadata": "QuakeBSPMetadata.json",
    "demoTrack": "QuakeBSPDemoTrack.bin",
    "demoTiming": "QuakeBSPDemoTiming.bin",
    "orderedCameraTrack": "QuakeBSPDemoPrecise.bin",
    "orderedTiming": "QuakeBSPDemoPreciseTiming.bin",
}


def profile_paths(config: Path) -> dict[str, Path]:
    document = json.loads(config.read_text(encoding="utf-8"))
    if document.get("target", {}).get("mode") == "fly":
        return {}
    external = document.get("externalBsp", {})
    paths = {"predecessor": config.parent / "ordered30-predecessor-reuse.json"}
    if external.get("enabled", True):
        paths.update(
            visibility=config.parent / external.get("visibilityProfile", "profiles/external-bsp-visibility.json"),
            direct=config.parent / external.get("directSafetyProfile", "profiles/brush-direct-safety.json"),
        )
    return paths


def _reference_profile_issues(document: dict) -> list[str]:
    from snes_tooling.quake.quake_external_bsp_snes import _reference_visibility_source_sha256

    if document.get("schema") != "quake-external-bsp-visibility-profile-v1":
        return ["visibility: invalid profile schema"]
    if (document.get("source", {}).get("referenceSources", {}).get("aggregateSha256")
            != _reference_visibility_source_sha256()):
        return ["visibility: stale referenceSources.aggregateSha256"]
    return []


def require_reference_profile_sources(config: Path) -> dict:
    """Reject stale reference-owned profiles before any content generation."""
    path = profile_paths(config).get("visibility")
    if path is None:
        return {"status": "disabled"}
    document = json.loads(path.read_bytes())
    if not isinstance(document, dict):
        raise ValueError(f"visibility: {path}: profile must contain an object")
    issues = _reference_profile_issues(document)
    if issues:
        raise ValueError("asset reference-source preflight failed:\n- " + "\n- ".join(issues))
    return {"status": "pass", "visibility": str(path.resolve())}


def _check_fly_bindings(config: Path, data: Path, pak: Path, *, require_generated: bool) -> dict:
    """A level has World identity and derived proofs, without demo profiles."""
    from snes_tooling.quake.quake_rom_config import configured_target

    issues: list[str] = []
    deferred: list[str] = []
    path = data / BOUND["metadata"]
    if not path.is_file():
        (issues if require_generated else deferred).append("generated inputs missing: " + path.name)
    else:
        try:
            target = configured_target(config)
            world = json.loads(path.read_bytes())
            source, demo = world["source"], world["demo"]
            expected = {"pak_entry": target["map"], "pak_sha256": hashlib.sha256(pak.read_bytes()).hexdigest()}
            if "bspSha256" in target:
                expected["bsp_sha256"] = target["bspSha256"]
            if world.get("target") != target:
                issues.append("metadata: stale target; generate the configured Fly level")
            for name, value in expected.items():
                if source.get(name) != value:
                    issues.append(f"metadata: stale source.{name}; generate the configured BSP/PAK")
            if demo.get("enabled") is not False or demo.get("map_entry") != target["map"]:
                issues.append("metadata: Fly demo identity must be disabled and name the configured map")
            require_generated_input_bindings(data)
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            issues.append(f"metadata: {error}")
    return {"status": "fail" if issues else ("deferred" if deferred else "pass"),
            "issues": issues, "deferred": deferred, "profiles": {}}


def check_bindings(config: Path, data: Path, pak: Path, *, require_generated: bool = False) -> dict:
    """Collect independent failures; consumer validators still own full semantics."""
    document = json.loads(config.read_bytes())
    if document.get("target", {}).get("mode") == "fly":
        return _check_fly_bindings(config, data, pak, require_generated=require_generated)
    from snes_tooling.quake.generate_quake_alias_visibility import _load_predecessor_reuse_contract
    from snes_tooling.quake.quake_external_bsp_snes import (
        load_brush_direct_safety_profile,
    )

    issues: list[str] = []
    deferred: list[str] = []
    paths = profile_paths(config)
    documents = {}
    for name, path in paths.items():
        try:
            documents[name] = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(documents[name], dict):
                del documents[name]
                raise ValueError("profile must contain an object")
        except (OSError, ValueError) as error:
            issues.append(f"{name}: {path}: {error}")
    if "visibility" in documents:
        issues.extend(_reference_profile_issues(documents["visibility"]))
    missing = [filename for filename in BOUND.values() if not (data / filename).is_file()]
    if missing:
        message = "generated inputs missing: " + ", ".join(missing)
        (issues if require_generated else deferred).append(message)
    else:
        hashes = {name: hashlib.sha256((data / filename).read_bytes()).hexdigest()
                  for name, filename in BOUND.items()}
        rows = (data / BOUND["orderedCameraTrack"]).stat().st_size // 10
        if "direct" in documents and "visibility" in documents:
            try:
                load_brush_direct_safety_profile(
                    paths["direct"], row_count=rows,
                    visibility_sha256=hashlib.sha256(paths["visibility"].read_bytes()).hexdigest(),
                    bound_inputs=hashes,
                )
            except (OSError, RuntimeError, ValueError, KeyError, TypeError) as error:
                issues.append(f"direct: {error}; inspect boundInputs and visibility; "
                              "capture_quake_brush_direct_safety.py --help documents "
                              "--profile/--previous-data-dir rebind mode; it requires byte-equality proof")
        if "predecessor" in documents:
            try:
                _load_predecessor_reuse_contract(paths["predecessor"], data, expected_rows=rows)
            except (OSError, RuntimeError, ValueError, KeyError, TypeError) as error:
                issues.append(f"predecessor: {error}; inspect ordered30-predecessor-reuse bindings; "
                              "derive_quake_ordered30_predecessor_reuse.py --help documents "
                              "--rebind-contract/--previous-data-dir; changed rendering inputs require qualification")
        if "visibility" in documents:
            source = documents["visibility"].get("source", {})
            metadata = json.loads((data / BOUND["metadata"]).read_text(encoding="utf-8"))
            expected = {
                "pakSha256": hashlib.sha256(pak.read_bytes()).hexdigest(),
                "bspSha256": metadata["source"]["bsp_sha256"],
            }
            for name, filename in (("qer1Sha256", "QuakeBSPExternalModels.bin"),
                                   ("qbr2Sha256", "QuakeBSPBrushReplay.bin")):
                path = data / filename
                if path.is_file():
                    expected[name] = hashlib.sha256(path.read_bytes()).hexdigest()
                else:
                    deferred.append(f"visibility: {filename} not generated yet; consumer validates it")
            for name, value in expected.items():
                if source.get(name) != value:
                    issues.append(f"visibility: stale {name}; all generators must use the qualified configured BSP/PAK")
    return {"status": "fail" if issues else ("deferred" if deferred else "pass"),
            "issues": issues, "deferred": deferred,
            "profiles": {name: str(path.resolve()) for name, path in paths.items()}}


def require_bindings(config: Path, data: Path, pak: Path, *, require_generated: bool = False) -> dict:
    report = check_bindings(config, data, pak, require_generated=require_generated)
    if report["issues"]:
        raise ValueError("asset binding preflight failed:\n- " + "\n- ".join(report["issues"]))
    return report


def require_generated_input_bindings(data: Path) -> None:
    """Validate present derived proofs without regenerating their outputs."""
    from pathlib import PurePosixPath
    from snes_tooling.quake import audit_quake_bsp_sky_assets as sky_audit

    data = Path(data).resolve()

    brush_path = data/'QuakeBSPBrushAssets.json'
    if brush_path.is_file():
        brush = json.loads(brush_path.read_bytes())
        direct = brush.get('source',{}).get('externalBsp',{}).get('directSafety',{})
        if direct.get('safeRowCount',0):
            expected = direct.get('qualifiedAliasAssetsSha256')
            aliases = data/'QuakeBSPAliasAssets.json'
            if not expected or hashlib.sha256(aliases.read_bytes()).hexdigest() != expected:
                raise ValueError('QuakeBSPBrushAssets.json: sprites changed after direct-safety qualification')

    qav_path = data / 'QuakeBSPAliasVisibility.json'
    if qav_path.is_file():
        visibility = json.loads(qav_path.read_bytes())
        world = json.loads((data / 'QuakeBSPMetadata.json').read_bytes())
        fly_only = world.get('target', {}).get('mode') == 'fly'
        if fly_only and visibility.get('enabled') is not False:
            raise ValueError('Fly-only level must not contain a demo visibility archive')
    if qav_path.is_file() and not fly_only:
        from snes_tooling.quake import quake_alias_visibility_projection as projection
        try:
            archive = visibility['archive']
            if (archive.get('schema') != 'quake-shared-alias-visibility-v3'
                    or not isinstance(archive.get('files'), dict) or not archive['files']):
                raise ValueError('invalid QAV3 archive or projection metadata')
            projection.require_bindings(archive, data)
        except (OSError, ValueError, KeyError, IndexError, TypeError, AttributeError) as error:
            raise ValueError(f'{qav_path.name}: {error}') from error

    def resolve(root, name):
        if not isinstance(name, str) or '\\' in name:
            raise ValueError('generated input path is not portable')
        relative = PurePosixPath(name)
        if not relative.parts or relative.is_absolute() or '..' in relative.parts:
            raise ValueError('generated input escapes its source root')
        root = Path(root).resolve()
        path = (root / Path(*relative.parts)).resolve()
        if not path.is_relative_to(root):
            raise ValueError('generated input escapes its source root')
        return path

    sky_path = data / 'QuakeBSPSkyAssets.json'
    if sky_path.is_file():
        sky = json.loads(sky_path.read_bytes())
        if (not isinstance(sky, dict) or sky.get('schema') != 'quake-bsp-snes-sky-assets-v1'
                or sky.get('status') != 'generated'):
            raise ValueError('QuakeBSPSkyAssets.json proof is invalid')
        inputs = sky.get('inputs')
        records = inputs.get('files') if isinstance(inputs, dict) else None
        if not isinstance(records, list) or not records:
            raise ValueError('QuakeBSPSkyAssets.json input bindings are invalid')
        roots = (('Data/', data), ('tools/commands/snes_quake/', sky_audit.TOOLS),
                 ('validation/snes_quake/profiles/', sky_audit.VALIDATION_PROFILES))
        bindings = {}
        for record in records:
            name = record.get('path') if isinstance(record, dict) else None
            matches = [(prefix, root) for prefix, root in roots
                       if isinstance(name, str) and name.startswith(prefix)]
            if len(matches) != 1:
                raise ValueError('QuakeBSPSkyAssets.json input path is invalid')
            prefix, root = matches[0]
            path = resolve(root, name[len(prefix):])
            payload = path.read_bytes()
            if (path in bindings or type(record.get('bytes')) is not int
                    or record['bytes'] != len(payload)
                    or record.get('sha256') != hashlib.sha256(payload).hexdigest()):
                raise ValueError('QuakeBSPSkyAssets.json stale input: ' + name)
            bindings[path] = payload
        if sky_audit._bindings_report(bindings, data) != inputs:
            raise ValueError('QuakeBSPSkyAssets.json input aggregate is stale')


def require_asset_chain_receipt(config: Path) -> dict:
    """Reuse a completed asset chain only while all recorded outputs still match."""
    from snes_tooling.quake import generate_snes_example_assets as assets

    config, digest = assets.validated_config_identity(config)
    path = assets.DATA / assets.ASSET_CHAIN_RECEIPT
    payload = path.read_bytes()
    if payload != assets.asset_chain_receipt(config, digest):
        raise ValueError('QuakeBSPAssetChain.json: asset outputs or configuration changed after receipt publication')
    require_generated_input_bindings(assets.DATA)
    return dict(path=str(path.resolve()), sha256=hashlib.sha256(payload).hexdigest())
