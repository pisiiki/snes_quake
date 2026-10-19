"""Deterministic runtime-use accounting for Quake alias sprites."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from typing import Any, Protocol


class ResidencyPayload(Protocol):
    """Hashable payload with a measurable packed size."""

    def __len__(self) -> int: ...

    def __hash__(self) -> int: ...


def compact_alias_rows(
    static_states: tuple[Any, ...],
    rows: tuple[Any, ...],
    sprite_ids: dict[int, int],
) -> tuple[tuple[Any, ...], tuple[Any, ...]]:
    """Remap IDs without repeating visibility against unused sprite placeholders.

    Missing IDs belong to inactive models. Remove their unreferenced states and
    remap both static and dynamic token indices, preserving groups and draw order.
    """

    def states(source: tuple[Any, ...]) -> tuple[tuple[Any, ...], dict[int, int]]:
        indices = {old: new for new, old in enumerate(
            index for index, state in enumerate(source) if state.sprite_id in sprite_ids
        )}
        return tuple(
            replace(
                source[index],
                sprite=sprite_ids[source[index].sprite_id],
                directional_base_sprite=(
                    None if source[index].directional_base_sprite is None
                    else sprite_ids[source[index].directional_base_sprite]
                ),
            )
            for index in indices
        ), indices

    compact_static, static_indices = states(static_states)
    compact_rows = []
    for row in rows:
        dynamic, dynamic_indices = states(row.dynamic_states)
        try:
            groups = tuple(replace(group, tokens=tuple(
                0x80 | static_indices[token & 0x7F] if token & 0x80
                else dynamic_indices[token]
                for token in group.tokens
            )) for group in row.groups)
        except KeyError as error:
            raise ValueError("alias compaction removed a drawn state") from error
        compact_rows.append(replace(row, dynamic_states=dynamic, groups=groups))
    return compact_static, tuple(compact_rows)


def verify_alias_compaction(
    before: tuple[tuple[Any, ...], tuple[Any, ...]],
    after: tuple[tuple[Any, ...], tuple[Any, ...]],
    exact_sprite_ids: dict[int, int],
    *,
    view_count: int,
) -> dict[str, int | bool]:
    """Reject changed draw membership, ordering, state identity or fly views."""

    def members(static: tuple[Any, ...], row: Any) -> tuple[Any, ...]:
        return tuple((group.leaf, group.parent, tuple(
            (bool(token & 0x80), static[token & 0x7F] if token & 0x80
             else row.dynamic_states[token]) for token in group.tokens
        )) for group in row.groups)

    def exact(state: Any) -> Any:
        base = state.directional_base_sprite
        if base is not None:
            mapped = tuple(exact_sprite_ids[base + view] for view in range(view_count))
            if mapped != tuple(range(mapped[0], mapped[0] + view_count)):
                raise ValueError("alias compaction broke contiguous directional views")
            base = mapped[0]
        return replace(state, sprite=exact_sprite_ids[state.sprite_id],
                       directional_base_sprite=base)

    if len(before[1]) != len(after[1]):
        raise ValueError("alias compaction changed row count")
    tokens = 0
    for index, (original, compact) in enumerate(zip(before[1], after[1], strict=True)):
        try:
            expected = tuple((leaf, parent, tuple((static, exact(state))
                for static, state in states))
                for leaf, parent, states in members(before[0], original))
            actual = members(after[0], compact)
        except (KeyError, IndexError) as error:
            raise ValueError(f"alias compaction lost an exact drawn state in row {index}") from error
        if expected != actual or original.culled_tokens != compact.culled_tokens:
            raise ValueError(f"alias compaction changed draw membership in row {index}")
        tokens += sum(len(states) for _leaf, _parent, states in actual)
    return {"visibilityPreserved": True, "rowsChecked": len(after[1]), "tokensChecked": tokens}


def usage_metadata(
    usage: tuple[int, ...],
    *,
    variants: set[int] | None = None,
    payloads: tuple[ResidencyPayload, ...] | None = None,
) -> dict[str, int]:
    """Summarize exact variants requested by one runtime path."""

    candidates = set(range(len(usage))) if variants is None else variants
    requested = {index for index in candidates if usage[index]}
    result = {
        "requestedVariantCount": len(requested),
        "tokenOccurrences": sum(usage[index] for index in requested),
        "residentRequestedVariantCount": len(requested),
        "residentRequestedOccurrences": sum(usage[index] for index in requested),
    }
    if payloads is not None:
        resident_payloads = {payloads[index] for index in requested}
        result.update(
            residentPayloadCount=len(resident_payloads),
            residentPayloadBytes=sum(map(len, resident_payloads)),
        )
    return result


def runtime_sprite_usage(
    static_states: tuple[Any, ...],
    rows: tuple[Any, ...],
    demo_row_count: int,
    sprite_count: int,
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Count exact sprite requests in demo and fly survivor rows."""

    demo: Counter[int] = Counter()
    fly: Counter[int] = Counter()
    for row_index, row in enumerate(rows):
        counts = demo if row_index < demo_row_count else fly
        for group in row.groups:
            for token in group.tokens:
                state = (
                    static_states[token & 0x7F]
                    if token & 0x80
                    else row.dynamic_states[token]
                )
                if not 0 <= state.sprite_id < sprite_count:
                    raise ValueError("alias usage names an invalid sprite")
                counts[state.sprite_id] += 1
    return (
        tuple(demo[index] for index in range(sprite_count)),
        tuple(fly[index] for index in range(sprite_count)),
    )
