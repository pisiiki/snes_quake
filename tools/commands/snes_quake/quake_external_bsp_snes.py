"""Merge configured external BSP entities into the SNES brush geometry source."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path

from workspace_paths import workspace_root
from typing import Any

import generate_quake_bsp as bsp_tools
from quake_brush_replay import (
    BrushEntityState,
    CanonicalBrushReplay,
)
from quake_external_bsp_replay import CanonicalExternalBspReplay


EXTERNAL_MODEL_CLASS = "external_bsp"
REFERENCE_VISIBILITY_SOURCES = (
    "external_models.cpp",
    "external_models_packed.cpp",
    "packed_brushes.cpp",
    "ordered_replay.cpp",
)
DIRECT_SAFETY_SCHEMA = "quake-brush-direct-safety-v1"


def _reference_visibility_source_sha256() -> str:
    root = workspace_root(__file__) / "src/reference_renderer"
    digest = hashlib.sha256()
    for name in REFERENCE_VISIBILITY_SOURCES:
        payload = (root / name).read_bytes()
        digest.update(name.encode("ascii"))
        digest.update(len(payload).to_bytes(8, "little"))
        digest.update(payload)
    return digest.hexdigest()


def load_external_visibility_profile(
    path: Path,
    *,
    bsp: bytes,
    qer1: bytes,
    qbr2: bytes,
    pak_sha256: str,
    external: CanonicalExternalBspReplay,
) -> tuple[tuple[dict[int, int], ...], dict[str, Any]]:
    """Validate and decode the exact reference-owned entity mask per row."""

    payload = path.read_bytes()
    document = json.loads(payload)
    if document.get("schema") != "quake-external-bsp-visibility-profile-v1":
        raise ValueError("external BSP visibility profile has an invalid schema")
    source = document.get("source", {})
    expected = {
        "pakSha256": pak_sha256,
        "bspSha256": hashlib.sha256(bsp).hexdigest(),
        "qer1Sha256": hashlib.sha256(qer1).hexdigest(),
        "qbr2Sha256": hashlib.sha256(qbr2).hexdigest(),
    }
    mismatches = [name for name, value in expected.items() if source.get(name) != value]
    reference_sha = source.get("referenceSources", {}).get("aggregateSha256")
    if reference_sha != _reference_visibility_source_sha256():
        mismatches.append("referenceSources.aggregateSha256")
    if mismatches:
        raise ValueError(
            "external BSP visibility profile is stale: " + ", ".join(mismatches)
        )
    contract = document.get("contract", {})
    entity_ids = tuple(int(value) for value in contract.get("entityIds", ()))
    expected_entities = tuple(
        sorted({state.entity_number for row in external.rows for state in row.entities})
    )
    if (
        entity_ids != expected_entities
        or int(contract.get("rowCount", -1)) != len(external.rows)
        or int(contract.get("sampleRateHz", -1)) != external.sample_rate_hz
    ):
        raise ValueError("external BSP visibility profile timeline is stale")
    masks = document.get("rows", {}).get("visibleEntityMasks")
    face_masks = document.get("rows", {}).get("visibleFaceMasks")
    face_digits = int(contract.get("faceMaskHexDigitsPerEntity", -1))
    if (
        not isinstance(masks, list)
        or not isinstance(face_masks, list)
        or len(masks) != len(external.rows)
        or len(face_masks) != len(external.rows)
        or face_digits != 2
    ):
        raise ValueError("external BSP visibility profile row masks are incomplete")
    decoded: list[dict[int, int]] = []
    for index, (raw, raw_faces, row) in enumerate(
        zip(masks, face_masks, external.rows, strict=True)
    ):
        try:
            mask = int(raw, 16)
        except (TypeError, ValueError) as error:
            raise ValueError(
                f"external BSP visibility row {index} is not hexadecimal"
            ) from error
        if mask >> len(entity_ids):
            raise ValueError(f"external BSP visibility row {index} exceeds entity bits")
        visible = {entity for bit, entity in enumerate(entity_ids) if mask & (1 << bit)}
        if not isinstance(raw_faces, str) or len(raw_faces) != len(entity_ids) * 2:
            raise ValueError(
                f"external BSP visibility row {index} face masks are malformed"
            )
        try:
            faces = {
                entity: int(raw_faces[bit * 2 : bit * 2 + 2], 16)
                for bit, entity in enumerate(entity_ids)
                if int(raw_faces[bit * 2 : bit * 2 + 2], 16)
            }
        except ValueError as error:
            raise ValueError(
                f"external BSP visibility row {index} face masks are not hexadecimal"
            ) from error
        if set(faces) != visible or any(value & ~0x3F for value in faces.values()):
            raise ValueError(
                f"external BSP visibility row {index} face/entity masks disagree"
            )
        active = {state.entity_number for state in row.entities}
        if not set(faces) <= active:
            raise ValueError(
                f"external BSP visibility row {index} retains an inactive entity"
            )
        decoded.append(faces)
    visible_states = sum(len(row) for row in decoded)
    if visible_states != int(
        document.get("coverage", {}).get("visibleEntityStateCount", -1)
    ):
        raise ValueError("external BSP visibility profile coverage does not reconcile")
    return tuple(decoded), {
        "path": path.as_posix(),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "referenceSourceSha256": reference_sha,
        "visibleEntityStateCount": visible_states,
        "rowsWithVisibleEntities": sum(bool(row) for row in decoded),
        "visiblePixels": int(document["coverage"]["visiblePixels"]),
    }


def load_brush_direct_safety_profile(
    path: Path,
    *,
    row_count: int,
    visibility_sha256: str,
    bound_inputs: Mapping[str, str],
) -> tuple[bytes, dict[str, Any]]:
    """Validate the byte-exact direct-arbiter admission mask."""

    payload = path.read_bytes()
    document = json.loads(payload)
    if document.get("schema") != DIRECT_SAFETY_SCHEMA:
        raise ValueError("brush direct-safety profile has an invalid schema")
    contract = document.get("contract", {})
    source = document.get("source", {})
    if (
        int(contract.get("rowCount", -1)) != row_count
        or int(contract.get("sampleRateHz", -1)) != 20
        or source.get("externalVisibilitySha256") != visibility_sha256
        or source.get("boundInputs") != dict(bound_inputs)
    ):
        raise ValueError("brush direct-safety profile is stale")
    try:
        mask = bytes.fromhex(document["rows"]["safeMaskHex"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("brush direct-safety mask is malformed") from error
    expected_bytes = (row_count + 7) // 8
    if len(mask) != expected_bytes or (row_count & 7 and mask[-1] >> (row_count & 7)):
        raise ValueError("brush direct-safety mask exceeds the row domain")
    safe_rows = sum(value.bit_count() for value in mask)
    coverage = document.get("coverage", {})
    if safe_rows != int(
        coverage.get("safeRowCount", -1)
    ) or row_count - safe_rows != int(coverage.get("exactFallbackRowCount", -1)):
        raise ValueError("brush direct-safety coverage does not reconcile")
    return mask, {
        "path": path.as_posix(),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "maskBytes": len(mask),
        "maskSha256": hashlib.sha256(mask).hexdigest(),
        "safeRowCount": safe_rows,
        "exactFallbackRowCount": row_count - safe_rows,
        "contract": contract["runtime"],
    }


def _empty_model() -> tuple[object, ...]:
    return (*([0.0] * 9), *([0] * 7))


def _remap_surfedge(value: int, edge_base: int) -> int:
    if value < 0:
        return -(abs(value) + edge_base)
    return value + edge_base


def _validate_replay_alignment(
    replay: CanonicalBrushReplay, external: CanonicalExternalBspReplay
) -> None:
    if (
        external.sample_rate_hz != replay.sample_rate_hz
        or external.first_server_time != replay.first_server_time
        or external.camera_track_fnv1a64 != replay.camera_track_fnv1a64
        or external.source_sample_count != replay.source_sample_count
        or len(external.rows) != len(replay.rows)
    ):
        raise ValueError("external BSP replay is not aligned with the brush replay")
    for row, external_row in zip(replay.rows, external.rows, strict=True):
        if external_row.camera != row.camera:
            raise ValueError(
                f"external BSP camera differs at canonical row {row.index}"
            )


def _used_model_slots(
    external: CanonicalExternalBspReplay,
) -> tuple[int, ...]:
    slots = tuple(
        sorted({state.model_slot for row in external.rows for state in row.entities})
    )
    if any(not 0 <= slot < len(external.model_names) for slot in slots):
        raise ValueError("external BSP state names a missing model slot")
    return slots


def encode_external_active_rows(
    external: CanonicalExternalBspReplay,
) -> tuple[bytes, dict[str, Any]]:
    """Pack the exact QER1 active set used when ordered playback enters fly."""

    entities = tuple(
        sorted({state.entity_number for row in external.rows for state in row.entities})
    )
    slot = {entity: index for index, entity in enumerate(entities)}
    row_bytes = (len(entities) + 7) // 8
    payload = bytearray()
    for row in external.rows:
        mask = bytearray(row_bytes)
        for state in row.entities:
            index = slot[state.entity_number]
            mask[index >> 3] |= 1 << (index & 7)
        payload.extend(mask)
    return bytes(payload), {
        "entityIds": list(entities),
        "entityCount": len(entities),
        "rowBytes": row_bytes,
        "rowCount": len(external.rows),
        "activeStateCount": sum(len(row.entities) for row in external.rows),
        "maximumActive": max(len(row.entities) for row in external.rows),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def external_fly_fragment_bounds(
    active_rows: bytes,
    row_bytes: int,
    variant_ids: tuple[int, ...],
    fragment_metadata: Mapping[str, Any],
    variant_leaf_groups: tuple[dict[int, tuple[int, int]], ...],
) -> dict[str, int]:
    """Return exact maxima for the active external fly subset."""

    maxima = {"links": 0, "leafMarkers": 0, "groupFragments": 0, "groupVertices": 0}
    if not variant_ids:
        return maxima
    if row_bytes <= 0 or len(active_rows) % row_bytes:
        raise ValueError("external fly active rows have an invalid stride")
    variants = fragment_metadata["variants"]
    for offset in range(0, len(active_rows), row_bytes):
        mask = int.from_bytes(active_rows[offset : offset + row_bytes], "little")
        active = tuple(
            variant for bit, variant in enumerate(variant_ids) if mask & (1 << bit)
        )
        maxima["links"] = max(
            maxima["links"],
            sum(
                int(variants[v]["fragmentCount"])
                - int(variants[v]["solidFragmentCount"])
                for v in active
            ),
        )
        maxima["leafMarkers"] = max(
            maxima["leafMarkers"],
            sum(int(variants[v]["nonSolidBucketCount"]) for v in active),
        )
        groups: dict[int, tuple[int, int]] = {}
        for variant in active:
            for leaf, (fragments, vertices) in variant_leaf_groups[variant].items():
                old_fragments, old_vertices = groups.get(leaf, (0, 0))
                groups[leaf] = (old_fragments + fragments, old_vertices + vertices)
        if groups:
            maxima["groupFragments"] = max(
                maxima["groupFragments"], max(value[0] for value in groups.values())
            )
            maxima["groupVertices"] = max(
                maxima["groupVertices"],
                max(
                    vertices + 4 * fragments for fragments, vertices in groups.values()
                ),
            )
    return maxima


def extend_external_fly_fragment_bounds(
    base: Mapping[str, int], *args: Any
) -> dict[str, int]:
    result = dict(base)
    extra = external_fly_fragment_bounds(*args)
    for target, source in (
        ("flyCombinedMaximumNonSolidLinks", "links"),
        ("flyCombinedMaximumLeafMarkers", "leafMarkers"),
        ("flyCombinedMaximumLeafGroupFragments", "groupFragments"),
        ("flyCombinedMaximumLeafGroupProjectedVertices", "groupVertices"),
    ):
        result[target] += extra[source]
    return result


def _source_face_range(source: Any) -> range:
    model = source.models[0]
    return range(int(model[14]), int(model[14]) + int(model[15]))


def merge_external_bsp_source(
    world: Any,
    external: CanonicalExternalBspReplay,
    model_payloads: Mapping[str, bytes],
    parse_bsp: Callable[[bytes], Any],
) -> tuple[Any, dict[str, Any]]:
    """Append only replay-used external model-0 draw geometry to one BSP source."""

    used_slots = _used_model_slots(external)
    entities = list(world.entities)
    planes = list(world.planes)
    vertices = list(world.vertices)
    texinfo = list(world.texinfo)
    faces = list(world.faces)
    edges = list(world.edges)
    surfedges = list(world.surfedges)
    models = list(world.models)
    textures = list(world.textures)
    lighting = bytearray(world.lighting)
    records: list[dict[str, Any]] = []
    seen_inline_models: set[int] = set()

    for slot in used_slots:
        name = external.model_names[slot]
        model_index = external.model_precache_indices[slot]
        inline_model = model_index - 1
        if inline_model <= 0 or inline_model > 0xFF:
            raise ValueError(
                f"external BSP model {name!r} cannot use uint8 inline identity"
            )
        if inline_model < len(world.models) or inline_model in seen_inline_models:
            raise ValueError(
                f"external BSP model {name!r} collides with inline model *{inline_model}"
            )
        payload = model_payloads.get(name)
        if payload is None:
            raise ValueError(f"external BSP payload is missing: {name}")
        source = parse_bsp(payload)
        if not source.models:
            raise ValueError(f"external BSP has no model 0: {name}")

        texture_base = len(textures)
        textures.extend(source.textures)
        plane_base = len(planes)
        planes.extend(source.planes)
        vertex_base = len(vertices)
        vertices.extend(source.vertices)
        edge_base = len(edges)
        edges.extend(
            (left + vertex_base, right + vertex_base) for left, right in source.edges
        )
        surfedge_base = len(surfedges)
        surfedges.extend(
            _remap_surfedge(value, edge_base) for value in source.surfedges
        )
        texinfo_base = len(texinfo)
        for record in source.texinfo:
            adjusted = list(record)
            adjusted[8] = int(adjusted[8]) + texture_base
            texinfo.append(tuple(adjusted))
        lighting_base = len(lighting)
        lighting.extend(source.lighting)

        external_faces = tuple(_source_face_range(source))
        first_face = len(faces)
        for source_face in external_faces:
            face = source.faces[source_face]
            faces.append(
                bsp_tools.Face(
                    face.plane + plane_base,
                    face.side,
                    face.first_edge + surfedge_base,
                    face.edge_count,
                    face.texinfo + texinfo_base,
                    face.light_styles,
                    (
                        face.light_offset + lighting_base
                        if face.light_offset >= 0
                        else -1
                    ),
                )
            )

        model = list(source.models[0])
        model[9:14] = [0, 0, 0, 0, 0]
        model[14] = first_face
        model[15] = len(external_faces)
        while len(models) <= inline_model:
            models.append(_empty_model())
        models[inline_model] = tuple(model)
        entities.append(
            {
                "classname": EXTERNAL_MODEL_CLASS,
                "model": f"*{inline_model}",
                "external_model": name,
            }
        )
        seen_inline_models.add(inline_model)
        records.append(
            {
                "slot": slot,
                "name": name,
                "modelPrecacheIndex": model_index,
                "syntheticInlineModel": inline_model,
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "vertices": len(source.vertices),
                "faces": len(external_faces),
                "indices": sum(
                    source.faces[face].edge_count for face in external_faces
                ),
                "textures": len(source.textures),
                "lightingBytes": len(source.lighting),
                "bounds": [float(value) for value in source.models[0][:6]],
            }
        )

    merged = replace(
        world,
        entities=tuple(entities),
        planes=tuple(planes),
        vertices=tuple(vertices),
        texinfo=tuple(texinfo),
        faces=tuple(faces),
        edges=tuple(edges),
        surfedges=tuple(surfedges),
        models=tuple(models),
        textures=tuple(textures),
        lighting=bytes(lighting),
    )
    metadata = {
        "representation": "translated-clipped-bsp-geometry",
        "usedModelCount": len(records),
        "usedModelSlots": list(used_slots),
        "unusedModelSlots": [
            slot for slot in range(len(external.model_names)) if slot not in used_slots
        ],
        "models": records,
        "sourceModelBytes": sum(record["bytes"] for record in records),
        "sourceFaceCount": sum(record["faces"] for record in records),
        "sourceIndexCount": sum(record["indices"] for record in records),
        "contract": (
            "used external model-0 faces retain PAK texture/light inputs and "
            "receive synthetic inline identities equal to precache index minus one"
        ),
    }
    return merged, metadata


def merge_external_bsp_replay(
    replay: CanonicalBrushReplay,
    external: CanonicalExternalBspReplay,
    *,
    visible_faces_by_row: tuple[dict[int, int], ...] | None = None,
) -> tuple[CanonicalBrushReplay, dict[str, Any]]:
    """Append aligned QER1 entities to each canonical translated-brush row."""

    _validate_replay_alignment(replay, external)
    inline_entities = {
        state.entity_number for row in replay.rows for state in row.brushes
    }
    external_states = [state for row in external.rows for state in row.entities]
    external_entity_ids = tuple(
        sorted({state.entity_number for state in external_states})
    )
    if inline_entities.intersection(external_entity_ids):
        raise ValueError("inline and external BSP replays reuse one entity identity")
    if any(state.angles != (0.0, 0.0, 0.0) for state in external_states):
        raise ValueError(
            "SNES external BSP geometry currently requires translation-only states"
        )
    if visible_faces_by_row is not None and len(visible_faces_by_row) != len(
        external.rows
    ):
        raise ValueError("external BSP visibility rows do not match QER1")

    def convert(state: Any) -> BrushEntityState:
        model_index = external.model_precache_indices[state.model_slot]
        return BrushEntityState(
            state.entity_number,
            model_index,
            model_index - 1,
            state.frame,
            state.origin,
            state.angles,
        )

    first_by_entity = {
        state.entity_number: convert(state)
        for row in external.rows
        for state in row.entities
    }
    rows = []
    for index, (row, external_row) in enumerate(
        zip(replay.rows, external.rows, strict=True)
    ):
        visible = (
            visible_faces_by_row[index]
            if visible_faces_by_row is not None
            else {state.entity_number for state in external_row.entities}
        )
        converted = tuple(
            convert(state)
            for state in external_row.entities
            if state.entity_number in visible
        )
        rows.append(replace(row, brushes=(*row.brushes, *converted)))
    if set(first_by_entity) != set(external_entity_ids):
        raise AssertionError("external BSP baseline recovery lost an entity")
    combined = replace(
        replay,
        signon_brushes=(
            *replay.signon_brushes,
            *(first_by_entity[entity] for entity in external_entity_ids),
        ),
        rows=tuple(rows),
    )
    unique_states = {
        (
            state.entity_number,
            state.model_slot,
            state.frame,
            state.origin,
            state.angles,
        )
        for state in external_states
    }
    return combined, {
        "entityCount": len(external_entity_ids),
        "entityIds": list(external_entity_ids),
        "activeStateCount": len(external_states),
        "retainedStateCount": sum(len(row.brushes) for row in rows)
        - sum(len(row.brushes) for row in replay.rows),
        "uniqueStateCount": len(unique_states),
        "maximumActive": max(len(row.entities) for row in external.rows),
        "rowsWithEntities": sum(bool(row.entities) for row in external.rows),
        "firstInlineModel": min(
            external.model_precache_indices[state.model_slot] - 1
            for state in external_states
        ),
        "lastInlineModel": max(
            external.model_precache_indices[state.model_slot] - 1
            for state in external_states
        ),
        "angles": "translation-only protocol-zero",
    }
