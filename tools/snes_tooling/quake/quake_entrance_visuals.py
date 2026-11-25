"""Bind independent entrance-leaf poses to the canonical QBSE local variants."""
from hashlib import sha256
from pathlib import Path

from snes_tooling.quake.quake_brush_compact_replay import build_compact_replay, quantize_q3


def entrance_visual_outputs(replay, gameplay, brush_metadata, *, external_entity_ids=()):
    leaves = gameplay.get("stockEntranceDoors", [])
    movers = gameplay.get("stockExitMachinery", {}).get("movers", [])
    filename = Path("QuakeBSPEntranceVisuals.i")
    if not leaves and not movers:
        return {filename: b"; This map has no independently controlled entrance leaves.\n"}, dict(
            schema="quake-entrance-visuals-v1", enabled=False, leaves=[])
    if leaves and (len(leaves) != 2 or len({leaf["renderEntity"] for leaf in leaves}) != 2):
        raise ValueError("entrance visuals require two distinct authored leaves")
    active = {state.entity_number for row in replay.rows for state in row.brushes}
    external = active & set(external_entity_ids)
    inline = active - external
    compact = build_compact_replay(replay, entity_order=(*sorted(inline), *sorted(external)),
        fly_baselines=tuple(state for state in replay.signon_brushes if state.entity_number in inline))
    if compact.metadata["entities"] != brush_metadata["replay"]["entities"]:
        raise ValueError("entrance local variants differ from the packed entity directory")
    lines = ["; Generated from the same canonical QBSE directory as the native brush assets."]
    records = []
    for index, leaf in enumerate(leaves):
        entity = leaf["renderEntity"]
        pose_rows = leaf["poseRows"]
        if len(pose_rows) != 17 or pose_rows[0] != 0 or len(set(pose_rows)) != 17:
            raise ValueError("entrance visuals require seventeen distinct pose rows")
        variants, positions = [], []
        for pose, row_index in enumerate(pose_rows):
            if not isinstance(row_index, int) or isinstance(row_index, bool) or not 0 <= row_index < len(replay.rows):
                raise ValueError("entrance pose row escapes the canonical replay")
            states = [state for state in replay.rows[row_index].brushes if state.entity_number == entity]
            if len(states) != 1:
                raise ValueError("entrance pose row omits or repeats its authored leaf")
            state = states[0]
            expected = tuple(round((a + b * pose / 16) * 8) / 8
                             for a, b in zip(leaf["origin"], leaf["travel"], strict=True))
            if (state.inline_model != leaf["inlineModel"] or state.origin != expected
                    or state.frame != 0 or state.angles != (0., 0., 0.)):
                raise ValueError("entrance pose changes its translation-only authored identity")
            variants.append(compact.local_variant_by_state[state])
            positions.append([quantize_q3(v, label="entrance visual origin") for v in state.origin])
        lines += [f"QuakeCEntrance{index}LocalVariants:",
                  "        .word " + ", ".join(str(value) for value in variants),
                  f'.assert *-QuakeCEntrance{index}LocalVariants = (QC_ENTRANCE_STEPS+1)*2, error, "Entrance local-variant table size changed"']
        records.append(dict(renderEntity=entity, inlineModel=leaf["inlineModel"],
                            poseRows=pose_rows, localVariants=variants, originsQ3=positions))
    if movers:
        lines.append("QCExitLocalVariants:")
        offsets = []
        for mover in movers:
            entity = mover["renderEntity"]
            model = mover["inlineModel"]
            offsets.append(model)
            variants = []
            for row in mover["poseRows"]:
                state, = [s for s in replay.rows[row].brushes if s.entity_number == entity]
                variants.append(compact.local_variant_by_state[state] + 1)
            if any(value > 255 for value in variants):
                raise ValueError("exit mover variant exceeds the byte command")
            lines.append("        .word " + ", ".join(map(str, variants)))
        lines += ["QCExitVariantOffsets:", "        .word " + ", ".join(map(str, offsets))]
        for mover in movers:
            if "visualRows" not in mover:
                continue
            entity = mover["renderEntity"]
            variants = []
            for row in mover["visualRows"]:
                state, = [s for s in replay.rows[row].brushes if s.entity_number == entity]
                variants.append(compact.local_variant_by_state[state] + 1)
            if any(value > 255 for value in variants):
                raise ValueError("platform variant exceeds the byte command")
            lines.append(f"QCPlatform{mover['inlineModel']}LocalVariants:")
            for start in range(0, len(variants), 16):
                lines.append("        .byte " + ", ".join(map(str, variants[start:start + 16])))
        machinery = gameplay.get("stockExitMachinery", {})
        doors = [*machinery.get("secretDoors", []), *machinery.get("ordinaryDoors", [])]
        if doors:
            lines.append("QCSecretDoorVariantBases:")
            lines.append("        .word " + ", ".join(
                f"QCSecretDoor{door['inlineModel']}Variants-QCSecretDoorVariants" for door in doors))
            lines.append("QCSecretDoorVariants:")
            for door in doors:
                variants = []
                for index in door["visualRows"]:
                    state, = (s for s in replay.rows[index].brushes if s.entity_number == door["renderEntity"])
                    variants.append(compact.local_variant_by_state[state] + 1)
                if max(variants) > 255:
                    raise ValueError("secret door variant exceeds the byte command")
                lines.append(f"QCSecretDoor{door['inlineModel']}Variants:")
                for start in range(0, len(variants), 16):
                    lines.append("        .byte " + ", ".join(map(str, variants[start:start + 16])))
        if any(value >= 255 for leaf in records for value in leaf["localVariants"]):
            raise ValueError("entrance mover variant exceeds the byte command")
    payload = ("\n".join(lines) + "\n").encode('ascii')
    return {filename: payload}, dict(schema="quake-entrance-visuals-v1", enabled=True,
        leaves=records, includeSha256=sha256(payload).hexdigest(),
        contract="Each leaf selects its own local variant; later lift/button keep the base visual state")
