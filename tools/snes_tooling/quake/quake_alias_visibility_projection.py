"""Projection corpus production and stale-input bindings for QAV3."""

from __future__ import annotations

import hashlib
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

from snes_tooling import Workspace
from snes_tooling.quake import generate_quake_bsp_ordered_replay as replay
from snes_tooling.quake import quake_alias_visibility_archive as archive
from snes_tooling.shared.host_resources import physical_core_count


def projection_replay(arguments: tuple[Path, int, int]) -> tuple[int, bytes]:
    data, focal, workers = arguments
    ordered = replay.build_replay(data, stride=1, render_scale=3, source_focal=focal, workers=workers)
    return focal, replay.encode_replay(ordered)


def input_bindings(data: Path, focal: int) -> dict:
    root = Workspace.discover().root
    patterns = ("QuakeBSPWorld*.bin", "QuakeBSPWorld*.i", "QuakeBSPScene.i",
                "QuakeBSPBrush*.bin", "QuakeBSPBrush*.json", "QuakeBSPBrush*.i",
                "QuakeBSPAliasRuntime*.bin", "QuakeBSPAliasAssets.json",
                "QuakeBSPMetadata.json", "QuakeBSPDemoPrecise.bin", "QuakeBSPPalette*.bin")
    paths = {path for pattern in patterns for path in data.glob(pattern)}
    inputs = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(paths)}
    sources = sorted((root / "src/reference_renderer").glob("*.cpp"))
    sources += sorted((root / "src/reference_renderer").glob("*.hpp"))
    sources.append(root / "src/snes_quake/quake/Viewport.i")
    sources += [root / "tools/snes_tooling/quake" / name for name in (
        "generate_quake_alias_visibility.py", "quake_alias_visibility_archive.py",
        "quake_alias_visibility_projection.py", "generate_quake_bsp_ordered_replay.py",
        "quake_bsp_packet_oracle.py", "analyze_quake_bsp_packets.py")]
    producers = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                 for path in sources}
    return dict(inputs=inputs, producers=producers, projections=[
        dict(scale=2, focal=96, width=128, height=112, center=[64,56]),
        dict(scale=3, focal=64, width=85, height=74, center=[43,37]),
        dict(scale=3, focal=focal, width=85, height=74, center=[43,37])])


def require_bindings(metadata: dict, data: Path, focal: int) -> None:
    if metadata.get("bindings") != input_bindings(data, focal):
        raise ValueError("QAV3 camera, geometry, sprite, producer or projection binding is stale")
    for name, expected in metadata["files"].items():
        path = data / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"QAV3 archive artifact is stale: {name}")


def build_projection_archive(*, executable: Path, pak: Path, data: Path, temporary: Path,
                             focal: int, codec: str, enabled, disabled,
                             workers: int | None = None) -> tuple[dict, dict, tuple]:
    from snes_tooling.quake import generate_quake_alias_visibility as visibility
    corpora = [enabled, disabled]
    outputs = {}
    focals = tuple(dict.fromkeys((64, focal)))
    workers = physical_core_count() if workers is None else workers
    if workers < 1:
        raise ValueError("visibility workers must be positive")
    parallel = min(len(focals), workers)
    jobs = [(data, f, max(1, workers//parallel)) for f in focals]
    if parallel == 1:
        replays = dict(map(projection_replay, jobs))
    else:
        with ProcessPoolExecutor(parallel) as pool:
            replays = dict(pool.map(projection_replay, jobs))
    paths = {}
    for f, payload in replays.items():
        path = temporary / f"x3-{f}.qor"
        path.write_bytes(payload)
        paths[f] = path

    def export(job):
        f, brushes = job
        target = temporary / f"x3-{f}-{int(brushes)}.qav"
        visibility._export(executable, pak, data, paths[f], target,
            map_entry=visibility._configured_map_entry(data), brushes_enabled=brushes,
            render_scale=3, source_focal=f)
        return (f, brushes), target.read_bytes()

    supported = visibility._dynamic_brush_replay_supported(data)
    jobs = [(f, brushes) for f in focals for brushes in ((True, False) if supported else (False,))]
    with ThreadPoolExecutor(min(workers, len(jobs))) as pool:
        exported = dict(pool.map(export, jobs))
    variants = []
    for label, f in (("Unity", 64), ("Warp", focal)):
        for brushes in (True, False):
            raw = exported[f, brushes] if supported or not brushes else visibility._world_only_enabled_payload(exported[f, False])
            corpus = visibility.parse_visibility(raw, expected_brushes=brushes,
                expected_camera_fingerprint=enabled.camera_fingerprint,
                expected_alias_fingerprint=enabled.alias_fingerprint)
            corpora.append(corpus)
            name = Path(f"QuakeBSPAliasVisibilityX3{label}{'Enabled' if brushes else 'Disabled'}.bin")
            outputs[name] = raw
            variants.append(dict(name=label, focal=f, brushesEnabled=brushes, file=name.name,
                sha256=hashlib.sha256(raw).hexdigest(),
                fullRateReplaySha256=hashlib.sha256(replays[f]).hexdigest(),
                maximumRecords=corpus.maximum_records, maximumMasks=corpus.maximum_mask_bytes))
    payload, directory, metadata = archive.pack([c.row_payloads for c in corpora], codec=codec)
    for index in range(2):
        outputs[Path(f"QuakeBSPAliasVisibilityArchive{index}.bin")] = payload[index*32768:(index+1)*32768]
    outputs[Path("QuakeBSPAliasVisibilityDirectory.bin")] = directory
    metadata.update(schema="quake-shared-alias-visibility-v3", variants=variants,
        bindings=input_bindings(data, focal),
        directoryOrder=["x2-enabled", "x2-disabled", "x3-unity-enabled", "x3-unity-disabled", "x3-warp-enabled", "x3-warp-disabled"],
        directoryContract="CPU direct source-pose uint16 addresses into GSU bank $6f; $ffff means live fallback",
        rowContract="count byte, high bit RLE; token high bit hidden, otherwise candidate count uint16 and ordered opaque-texel bits",
        candidateOrder="QBA1 canonical token ordinal, clipped destination scan rows then columns, transparent sprite samples omitted",
        files={name.name:hashlib.sha256(value).hexdigest() for name,value in outputs.items()})
    return outputs, metadata, tuple(corpora)


def joint_temporal_ids(alias_package: bytes, corpora: tuple, *, brushes: bool) -> tuple[int, ...]:
    """Conservatively bind every projection without enlarging the temporal tables."""
    from snes_tooling.quake import generate_quake_alias_visibility as visibility
    index = 0 if brushes else 1
    ids = [visibility._temporal_alias_identity_ids(alias_package, corpora[index + 2*p]) for p in range(3)]
    identities = {}
    result = []
    for key in zip(*ids, strict=True):
        if key not in identities:
            identities[key] = len(identities) + 1
        result.append(identities[key])
    return tuple(result)


def assembly() -> bytes:
    names = ("X2Enabled", "X2Disabled", "X3UnityEnabled", "X3UnityDisabled", "X3WarpEnabled", "X3WarpDisabled")
    lines = ['; Generated shared QAV3 archive.', '.segment "BSP_ALIAS_VISIBILITY_ENABLED"',
        '.assert * = $6F0000, lderror, "QAV3 first halfbank moved"',
        '.incbin "Data/QuakeBSPAliasVisibilityArchive0.bin"', '.segment "BSP_ALIAS_VISIBILITY_DISABLED"',
        '.assert * = $6F8000, lderror, "QAV3 second halfbank moved"',
        '.incbin "Data/QuakeBSPAliasVisibilityArchive1.bin"', '.segment "BSP_ALIAS_VISIBILITY_DIRECTORY"']
    for index, name in enumerate(names):
        symbol = f"QuakeBSPAliasVisibility{name}"
        lines.extend([f".export {symbol}", f"{symbol}:",
            f'.incbin "Data/QuakeBSPAliasVisibilityDirectory.bin", {index}*BSP_ALIAS_VISIBILITY_SOURCE_ROW_COUNT*2, BSP_ALIAS_VISIBILITY_SOURCE_ROW_COUNT*2'])
    lines.append('.segment "BSP_ALIAS_TEMPORAL"')
    for name in ("TemporalEnabled", "TemporalDisabled", "Predecessor"):
        symbol = f"QuakeBSPAlias{name}"
        lines.extend([f".export {symbol}", f"{symbol}:", f'.incbin "Data/{symbol}.bin"'])
    lines.append('.assert * <= $F88000, lderror, "Alias temporal identities overflow their CPU halfbank"')
    return ("\n".join(lines)+"\n").encode("ascii")
