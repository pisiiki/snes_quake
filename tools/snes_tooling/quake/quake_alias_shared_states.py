"""Lossless paired snapshot storage without changing the eight-byte state ABI."""

from collections import Counter, defaultdict
from dataclasses import replace


def pair_alias_snapshots(rows, fly_rows):
    """Reindex demo states so two snapshots share their common contiguous bytes.

    Group tokens are remapped without changing their draw order. Fly rows keep
    their original state order because the separate facing table indexes it.
    Each returned blob is immutable, and each snapshot remains one contiguous
    read. No decompression, extra indirection or runtime work is introduced.
    """
    if not 0 <= fly_rows <= len(rows):
        raise ValueError("fly suffix length is outside the alias row sequence")
    demo_end = len(rows) - fly_rows
    sequences = list(
        dict.fromkeys(
            tuple(s.packed() for s in row.dynamic_states) for row in rows[:demo_end]
        )
    )
    counts = [Counter(sequence) for sequence in sequences]
    groups_by_sequence = defaultdict(set)
    seen_groups = set()
    for row in rows:
        groups_by_sequence[tuple(state.packed() for state in row.dynamic_states)].add(
            row.groups
        )
        seen_groups.add(row.groups)

    def remapped_groups(sequence, order):
        reverse = {old: new for new, old in enumerate(order)}
        return {
            tuple(
                replace(
                    group,
                    tokens=tuple(
                        token if token & 128 else reverse[token]
                        for token in group.tokens
                    ),
                )
                for group in groups
            )
            for groups in groups_by_sequence[sequence]
        }

    remaining = set(range(len(sequences)))
    orders, locations = {}, {}
    while remaining:
        i = min(remaining)
        remaining.remove(i)
        overlap, partner = max(
            ((sum((counts[i] & counts[j]).values()), -j) for j in remaining),
            default=(0, 0),
        )
        if not overlap:
            orders[sequences[i]] = tuple(range(len(sequences[i])))
            payload = b"".join(sequences[i])
            locations[payload] = (payload, 0)
            continue
        j = -partner
        remaining.remove(j)
        common = counts[i] & counts[j]
        shared, outside = [], []
        for index, value in enumerate(sequences[i]):
            if common[value]:
                shared.append(index)
                common[value] -= 1
            else:
                outside.append(index)
        right = defaultdict(list)
        for index, value in enumerate(sequences[j]):
            right[value].append(index)
        prefix = [right[sequences[i][index]].pop(0) for index in shared]
        rest = sorted(index for indices in right.values() for index in indices)
        first_order, second_order = tuple(outside + shared), tuple(prefix + rest)
        forward_groups = remapped_groups(sequences[i], first_order) | remapped_groups(
            sequences[j], second_order
        )
        alternate_i, alternate_j = tuple(shared + outside), tuple(rest + prefix)
        reverse_groups = remapped_groups(sequences[i], alternate_i) | remapped_groups(
            sequences[j], alternate_j
        )

        def cost(groups):
            return sum(
                sum(5 + len(group.tokens) for group in stream)
                for stream in groups - seen_groups
            )

        reversed_pair = cost(reverse_groups) < cost(forward_groups)
        if reversed_pair:
            first_order, second_order = alternate_i, alternate_j
        seen_groups.update(reverse_groups if reversed_pair else forward_groups)
        orders[sequences[i]], orders[sequences[j]] = first_order, second_order
        first = b"".join(sequences[i][index] for index in first_order)
        second = b"".join(sequences[j][index] for index in second_order)
        common_bytes = sum(len(sequences[i][index]) for index in shared)
        if reversed_pair:
            first, second = second, first
        if first[-common_bytes:] != second[:common_bytes]:
            raise AssertionError("paired alias states do not share identical bytes")
        blob = first + second[common_bytes:]
        locations[first] = (blob, 0)
        locations[second] = (blob, len(first) - common_bytes)
    result = []
    for row in rows[:demo_end]:
        sequence = tuple(state.packed() for state in row.dynamic_states)
        order = orders[sequence]
        reverse = {old: new for new, old in enumerate(order)}
        groups = tuple(
            replace(
                group,
                tokens=tuple(
                    token if token & 128 else reverse[token] for token in group.tokens
                ),
            )
            for group in row.groups
        )
        reordered = replace(
            row,
            dynamic_states=tuple(row.dynamic_states[i] for i in order),
            groups=groups,
        )
        # Verify identities as well as bytes: equal payloads may name two actors.
        for before, after in zip(row.groups, reordered.groups, strict=True):
            for old, new in zip(before.tokens, after.tokens, strict=True):
                if old & 128:
                    if old != new:
                        raise AssertionError("static alias token changed")
                elif row.dynamic_states[old] != reordered.dynamic_states[new]:
                    raise AssertionError(
                        "paired alias snapshot changed draw order or entity identity"
                    )
        result.append(reordered)
    for row in rows[demo_end:]:
        payload = b"".join(state.packed() for state in row.dynamic_states)
        locations.setdefault(payload, (payload, 0))
        result.append(row)
    for snapshot, (blob, offset) in locations.items():
        if blob[offset : offset + len(snapshot)] != snapshot:
            raise AssertionError("paired alias snapshot cannot be reproduced")
    return tuple(result), locations
