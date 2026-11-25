"""Allocation proof for independently selected inline-brush local variants."""
import struct


def extend_independent_inline_fragment_bounds(
    base, compact, visual_sections, compact_to_fragments, static_fragments,
    fragment_metadata, variant_leaf_groups, entity_ids,
):
    """Cover mixed live poses without materializing their Cartesian product.

    Each entity contributes its maximum demand independently. Per-leaf maxima
    are kept separate for fragment records and frustum-clipped vertices, so
    neither metric assumes that its maximum occurs in a stored atomic row.
    The existing external-Fly extension must run after this inline proof.
    """
    result = dict(base)
    if not entity_ids:
        return result
    if len(set(entity_ids)) != len(entity_ids):
        raise ValueError("independent inline entities must be distinct")
    entities = {int(item["entity"]): item for item in compact.metadata["entities"]}
    slots = {int(item["slot"]): item for item in entities.values()}
    fragment_ids = tuple(value[0] for value in struct.iter_unpack("<H", compact_to_fragments))
    variants = fragment_metadata["variants"]

    def demand(variant_ids):
        links = markers = 0
        groups = {}
        for variant in variant_ids:
            record = variants[variant]
            links += int(record["fragmentCount"]) - int(record["solidFragmentCount"])
            markers += int(record["nonSolidBucketCount"])
            for leaf, (fragments, vertices) in variant_leaf_groups[variant].items():
                old_fragments, old_vertices = groups.get(leaf, (0, 0))
                groups[leaf] = (old_fragments + fragments,
                                old_vertices + vertices + 4 * fragments)
        return links, markers, groups

    controlled_slots = set()
    envelope_links = envelope_markers = 0
    envelope_groups = {}
    for entity in entity_ids:
        if entity not in entities:
            raise ValueError("independent inline entity is absent from the compact directory")
        record = entities[entity]
        first, count = int(record["firstVariant"]), int(record["variantCount"])
        if count <= 0 or first < 0 or first + count > len(fragment_ids):
            raise ValueError("independent inline variants escape the compact directory")
        controlled_slots.add(int(record["slot"]))
        choices = [demand((variant,)) for variant in fragment_ids[first:first + count]]
        envelope_links += max(value[0] for value in choices)
        envelope_markers += max(value[1] for value in choices)
        leaves = set().union(*(value[2] for value in choices))
        for leaf in leaves:
            fragments = max(value[2].get(leaf, (0, 0))[0] for value in choices)
            vertices = max(value[2].get(leaf, (0, 0))[1] for value in choices)
            old_fragments, old_vertices = envelope_groups.get(leaf, (0, 0))
            envelope_groups[leaf] = (old_fragments + fragments, old_vertices + vertices)

    static_ids = tuple(value[1] for value in struct.iter_unpack("<HH", static_fragments))
    static_links, static_markers, static_groups = demand(static_ids)
    demo_state_count = max(value[0] for value in struct.iter_unpack("<H", visual_sections["ROWSTATE"]))

    def group_maxima(*sources):
        groups = {}
        for source in sources:
            for leaf, (fragments, vertices) in source.items():
                old_fragments, old_vertices = groups.get(leaf, (0, 0))
                groups[leaf] = old_fragments + fragments, old_vertices + vertices
        return (max((value[0] for value in groups.values()), default=0),
                max((value[1] for value in groups.values()), default=0))

    def increase(prefix, links, markers, groups):
        for suffix, value in (("NonSolidLinks", links), ("LeafMarkers", markers),
                              ("LeafGroupFragments", groups[0]),
                              ("LeafGroupProjectedVertices", groups[1])):
            key = prefix + suffix
            result[key] = max(result[key], value)

    for state_index, state in enumerate(struct.iter_unpack("<HHHBB", visual_sections["VSTATES"])):
        first_transform, _texture, _reserved, count, _texture_count = state
        fixed_ids = []
        seen_controlled = set()
        for index in range(first_transform, first_transform + count):
            slot, local = struct.unpack_from("<BH", visual_sections["VTRANS"], index * 3)
            if slot in controlled_slots:
                if slot in seen_controlled:
                    raise ValueError("independent inline entity repeats within a visual state")
                seen_controlled.add(slot)
                continue
            record = slots[slot]
            fixed_ids.append(fragment_ids[int(record["firstVariant"]) + local])
        if seen_controlled != controlled_slots:
            raise ValueError("independent inline entity is missing from a visual state")
        fixed_links, fixed_markers, fixed_groups = demand(fixed_ids)
        links, markers = fixed_links + envelope_links, fixed_markers + envelope_markers
        if state_index < demo_state_count:
            increase("replayMaximum", links, markers, group_maxima(fixed_groups, envelope_groups))
        increase("flyCombinedMaximum", links + static_links, markers + static_markers,
                 group_maxima(fixed_groups, envelope_groups, static_groups))
    return result
