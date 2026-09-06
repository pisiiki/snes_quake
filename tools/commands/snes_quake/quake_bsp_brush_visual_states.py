"""Atomic demo and complete fly brush-state packaging."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import generate_quake_bsp as bsp_tools
    from quake_bsp_brush_assets import _ParsedBsp
    from quake_brush_compact_replay import CompactReplayBuild
    from quake_brush_replay import CanonicalBrushReplay

def _resolve_animated_texture(
    source_texture: int,
    entity_frame: int,
    tenths: int,
    animations: dict[str, dict[str, list[int]]],
    textures: tuple[bsp_tools.MipTexture, ...],
) -> int:
    name = textures[source_texture].name
    if not name.startswith("+"):
        return source_texture
    group = animations[name[2:].lower()]
    sequence = (
        group["alternate"] if entity_frame and group["alternate"] else group["regular"]
    )
    return sequence[(tenths // 2) % len(sequence)]


def _visual_states(
    source: _ParsedBsp,
    replay: CanonicalBrushReplay,
    compact: CompactReplayBuild,
    model_face_textures: dict[int, tuple[int, ...]],
    source_to_packed: dict[int, int],
    external_first_slot: int,
) -> tuple[dict[str, bytes], dict[str, Any]]:
    from quake_bsp_brush_assets import (
        _animation_groups, ROW_STATE_RECORD, VISUAL_STATE_RECORD,
        VISUAL_TRANSFORM_RECORD, VISUAL_TEXTURE_RECORD,
    )

    directly_referenced = {
        texture for textures in model_face_textures.values() for texture in textures
    }
    animations, _closure = _animation_groups(source.textures, directly_referenced)
    keys: dict[
        tuple[
            tuple[tuple[int, int], ...],
            tuple[tuple[int, int, int], ...],
            tuple[tuple[int, int, int], ...],
        ],
        int,
    ] = {}
    row_ids = bytearray()
    state_records: list[
        tuple[
            tuple[tuple[int, int], ...],
            tuple[tuple[int, int, int], ...],
            tuple[tuple[int, int, int], ...],
        ]
    ] = []
    for row, transforms in zip(replay.rows, compact.row_transforms, strict=True):
        clock = compact.metadata["textureAnimationClock"]
        tenths = (row.index + clock["textureClockBias"]) // clock["textureTickStride"]
        inline_textures: list[tuple[int, int, int]] = []
        external_textures: list[tuple[int, int, int]] = []
        for state in row.brushes:
            slot = compact.slot_by_entity[state.entity_number]
            for local_face, source_texture in enumerate(
                model_face_textures[state.inline_model]
            ):
                if not source.textures[source_texture].name.startswith("+"):
                    continue
                resolved_source = _resolve_animated_texture(
                    source_texture,
                    state.frame,
                    tenths,
                    animations,
                    source.textures,
                )
                record = (slot, local_face, source_to_packed[resolved_source])
                if slot < external_first_slot:
                    inline_textures.append(record)
                else:
                    external_textures.append(record)
        key = (transforms, tuple(inline_textures), tuple(external_textures))
        state_id = keys.get(key)
        if state_id is None:
            state_id = len(state_records) + 1
            if state_id > 0xFFFF:
                raise ValueError(
                    "resolved brush visual states exceed uint16 bound "
                    f"(needed at canonical row {row.index})"
                )
            keys[key] = state_id
            state_records.append(key)
        row_ids.extend(ROW_STATE_RECORD.pack(state_id))

    # Fill camera-admission omissions; signon-only brushes remain in VSTATIC.
    # Pickup membership continues to come from the frozen QER1 row.
    baseline_states = {
        compact.slot_by_entity[state.entity_number]: state
        for state in replay.signon_brushes
        if state.entity_number in compact.slot_by_entity
        and compact.slot_by_entity[state.entity_number] < external_first_slot
    }
    demo_state_count = len(state_records)
    fly_ids = []
    for transforms, inline_textures, external_textures in tuple(state_records):
        missing = sorted(set(baseline_states) - {slot for slot, _variant in transforms})
        complete = tuple(sorted((*transforms, *((slot, compact.local_variant_by_state[baseline_states[slot]])
                                               for slot in missing))))
        baseline_textures = []
        for slot in missing:
            state = baseline_states[slot]
            for face, texture in enumerate(model_face_textures[state.inline_model]):
                if source.textures[texture].name.startswith("+"):
                    resolved = _resolve_animated_texture(texture, state.frame, 0, animations, source.textures)
                    baseline_textures.append((slot, face, source_to_packed[resolved]))
        key = (complete, tuple(sorted((*inline_textures, *baseline_textures))), external_textures)
        state_id = keys.get(key)
        if state_id is None:
            state_id = len(state_records) + 1
            if state_id > 0xFFFF:
                raise ValueError("complete fly brush states exceed uint16 addressing")
            keys[key] = state_id
            state_records.append(key)
        fly_ids.append(state_id)
    # Publication retains its fly ID: repeated conversion must be idempotent.
    fly_ids.extend(range(demo_state_count + 1, len(state_records) + 1))
    fly_map = b"".join(ROW_STATE_RECORD.pack(state) for state in fly_ids)

    directories = bytearray()
    transform_entries = bytearray()
    texture_entries = bytearray()
    max_transforms = 0
    max_textures = 0
    max_inline_textures = 0
    max_external_textures = 0
    for transforms, inline_textures, external_textures in state_records:
        textures = (*inline_textures, *external_textures)
        first_transform = len(transform_entries) // VISUAL_TRANSFORM_RECORD.size
        first_texture = len(texture_entries) // VISUAL_TEXTURE_RECORD.size
        if len(transforms) > 0xFF or len(textures) > 0xFF:
            raise ValueError("one resolved brush visual state exceeds uint8 counts")
        directories.extend(
            VISUAL_STATE_RECORD.pack(
                first_transform,
                first_texture,
                0,
                len(transforms),
                len(textures),
            )
        )
        for slot, local_variant in reversed(transforms):
            transform_entries.extend(VISUAL_TRANSFORM_RECORD.pack(slot, local_variant))
        for slot, local_face, packed_texture in textures:
            texture_entries.extend(
                VISUAL_TEXTURE_RECORD.pack(slot, local_face, packed_texture)
            )
        max_transforms = max(max_transforms, len(transforms))
        max_textures = max(max_textures, len(textures))
        max_inline_textures = max(max_inline_textures, len(inline_textures))
        max_external_textures = max(max_external_textures, len(external_textures))
    sections = {
        "ROWSTATE": bytes(row_ids),
        "FLYSTATE": fly_map,
        "VSTATES": bytes(directories),
        "VTRANS": bytes(transform_entries),
        "VTEX": bytes(texture_entries),
    }
    metadata = {
        "disabledStateId": 0,
        "firstEnabledStateId": 1,
        "visualStateCount": len(state_records),
        "demoVisualStateCount": demo_state_count,
        "flyStateMapBytes": len(fly_map),
        "flyStateMapSha256": hashlib.sha256(fly_map).hexdigest(),
        "flyFallbackEntityIds": sorted(state.entity_number for state in baseline_states.values()),
        "flyStateContract": (
            "idempotent accepted demo-to-fly state mapping; retain present inline poses "
            "and resolved textures, fill absent replay slots with signon poses/textures; "
            "VSTATIC and QER1 pickup membership remain independent"
        ),
        "rowStateRecordBytes": ROW_STATE_RECORD.size,
        "rowStateBytes": len(row_ids),
        "rowStateSha256": hashlib.sha256(row_ids).hexdigest(),
        "stateRecordBytes": VISUAL_STATE_RECORD.size,
        "transformRecordBytes": VISUAL_TRANSFORM_RECORD.size,
        "resolvedTextureRecordBytes": VISUAL_TEXTURE_RECORD.size,
        "transformRecordCount": len(transform_entries) // VISUAL_TRANSFORM_RECORD.size,
        "resolvedTextureRecordCount": len(texture_entries)
        // VISUAL_TEXTURE_RECORD.size,
        "maximumTransformsPerState": max_transforms,
        "maximumResolvedTexturesPerState": max_textures,
        "maximumInlineResolvedTexturesPerState": max_inline_textures,
        "maximumExternalResolvedTexturesPerState": max_external_textures,
        "textureOverrideOrdering": "inline slots then external BSP slots",
        "contract": (
            "row ID is indexed by the canonical camera row; state 0 disables "
            "brushes, IDs 1..N atomically select transforms and exact resolved "
            "animated-face texture identities"
        ),
        "timingStorage": "none",
    }
    return sections, metadata
