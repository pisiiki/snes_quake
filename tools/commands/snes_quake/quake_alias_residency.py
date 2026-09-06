"""Deterministic runtime-use accounting for Quake alias sprites."""

from __future__ import annotations

from collections import Counter
from typing import Any, Protocol


class ResidencyPayload(Protocol):
    """Hashable payload with a measurable packed size."""

    def __len__(self) -> int: ...

    def __hash__(self) -> int: ...


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
