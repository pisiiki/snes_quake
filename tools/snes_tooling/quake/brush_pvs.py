"""Conservative source-leaf visibility for the camera-independent QBSF pool."""
from __future__ import annotations

import hashlib
from pathlib import Path
import struct

BANK_BYTES = 32768
DIRECTORY = struct.Struct("<H")


def leaf_halfspaces(source):
    """World hull leaves are convex intersections of their ancestor halfspaces."""
    result = {}
    stack = [(int(source.models[0][9]), ())]
    while stack:
        node, path = stack.pop()
        if node < 0:
            if ~node:
                if ~node in result:
                    raise ValueError("non-solid world leaf has multiple owners")
                result[~node] = path
            continue
        record = source.nodes[node]
        plane = tuple(float(x) for x in source.planes[record.plane][:4])
        stack.extend((child, path + ((plane, side),))
                     for side, child in enumerate(record.children))
    return result


def escapes_leaf(vertices, halfspaces):
    """Keep boundary vertices; reject only points strictly across a source plane.

    A convex polygon stays in a convex leaf if every vertex stays in it. No
    center/radius approximation or integer truncation participates in this proof.
    """
    return any((sum(point[i] * plane[i] for i in range(3)) - plane[3])
               * (1 if side == 0 else -1) < -1e-7
               for point in vertices for plane, side in halfspaces)


def quantization_guard(source, fragments):
    """Globally admit leaves containing any Q2 fragment that escapes its leaf.

    Read the actual QBSF v4 vertices after signed-Q3 translation and Q2 packing.
    A guard therefore covers every generated transform, including signon-only
    and external brushes, and both translation and clipping quantization.
    """
    m = fragments.metadata
    if m["version"] != 4:
        raise ValueError("brush leaf PVS requires QBSF v4")
    roles = m["bankRoles"]
    origin = tuple((float(source.models[0][i]) + float(source.models[0][i+3])) / 2
                   for i in range(3))

    def bank(index):
        return fragments.outputs[Path(f"QuakeBSPBrushFragments{index}.bin")]

    def pool(role):
        first = roles[role]["firstBank"] - m["firstBank"]
        return b"".join(bank(i) for i in range(first, first + roles[role]["bankCount"]))

    directory = roles["control"]["buckets"]
    control = bank(directory["bankIndex"])
    descriptors, vertices = pool("descriptors"), pool("vertices")
    paths = leaf_halfspaces(source)
    guarded, escaped, bucket_leaves = set(), [], set()
    for bucket in range(m["bucketCount"]):
        leaf, first, count, solid, _ = struct.unpack_from(
            "<HHBBH", control, directory["offset"] + bucket * 8)
        if solid:
            continue
        bucket_leaves.add(leaf)
        for fragment in range(first, first + count):
            _, start, length, _ = struct.unpack_from("<HIBB", descriptors, fragment * 8)
            decoded = []
            for index in range(start, start + length):
                x, y, z, residual = struct.unpack_from("<bbbB", vertices, index * 4)
                decoded.append(tuple((v * 4 + ((residual >> (axis * 2)) & 3)) * 4
                                     + origin[axis] for axis, v in enumerate((x, y, z))))
            if escapes_leaf(decoded, paths[leaf]):
                guarded.add(leaf)
                escaped.append(fragment)
    return guarded, {"policy": "globally admit source leaves containing any decoded QBSF v4 polygon outside its owning convex leaf",
                     "guardLeaves": sorted(guarded), "escapedFragments": escaped,
                     "bucketLeaves": sorted(bucket_leaves),
                     "checkedFragments": m["fragmentCount"], "checkedVariants": m["variantCount"]}


def encode_zero_runs(row):
    result = bytearray()
    index = 0
    while index < len(row):
        value = row[index]
        if value:
            result.append(value)
            index += 1
        else:
            end = index + 1
            while end < len(row) and row[end] == 0 and end - index < 255:
                end += 1
            result.extend((0, end - index))
            index = end
    return bytes(result)


def visibility_row(pvs, leaf, leaf_count, guards):
    if not 0 <= leaf < leaf_count:
        raise ValueError("camera leaf escapes the world VIS domain")
    row = bytearray((leaf_count + 7) // 8)
    visible = set(range(leaf_count)) if leaf == 0 else {
        bit + 1 for bit in range(leaf_count - 1) if pvs[bit >> 3] & (1 << (bit & 7))}
    visible.update((leaf, *guards))
    for bit in visible:
        if not 0 <= bit < leaf_count:
            raise ValueError("guard leaf escapes the world VIS domain")
        row[bit >> 3] |= 1 << (bit & 7)
    return bytes(row)


def texture_bank_used_bytes(textures, bank):
    """Find a bank's occupied prefix from exact texture spans, including crossings."""
    return max((min(BANK_BYTES, (row["bank"] - bank) * BANK_BYTES
                    + row["address"] - 0x8000 + row["level0Bytes"])
                for row in textures
                if row["bank"] <= bank < row["bank"] + row["bankSpan"]), default=0)


def build_leaf_pvs(source, fragments, decompress, *, bank, start_offset):
    guards, proof = quantization_guard(source, fragments)
    leaf_count = int(source.models[0][13]) + 1
    directory_bytes = leaf_count * DIRECTORY.size
    if start_offset + directory_bytes > BANK_BYTES:
        raise ValueError(f"brush PVS directory needs {directory_bytes} bytes; tail has {BANK_BYTES-start_offset}")
    offset = start_offset + directory_bytes
    payload = bytearray(directory_bytes)
    shared, directory = {}, bytearray()
    relevant = set(proof["bucketLeaves"]) | guards
    for leaf in range(leaf_count):
        source_row = decompress(source.visibility, source.leaves[leaf].vis_offset, leaf_count - 1)
        # Only leaves used by QBSF can be queried. Keeping the camera bit out
        # of the stored row lets equivalent brush PVS rows share one payload;
        # the runtime explicitly adds that bit after decoding.
        row = bytearray(visibility_row(source_row, leaf, leaf_count, guards))
        if leaf:
            for bit in range(leaf_count):
                if bit not in relevant:
                    row[bit >> 3] &= ~(1 << (bit & 7))
            if leaf not in guards and not source_row[(leaf-1) >> 3] & (1 << ((leaf-1) & 7)):
                row[leaf >> 3] &= ~(1 << (leaf & 7))
        row = encode_zero_runs(row)
        if row not in shared:
            if offset + len(row) > BANK_BYTES:
                raise ValueError(f"brush PVS row ends at {offset+len(row)}; bank capacity is {BANK_BYTES}")
            shared[row] = 0x8000 + offset
            payload.extend(row)
            offset += len(row)
        directory.extend(DIRECTORY.pack(shared[row]))
    payload[:len(directory)] = directory
    return bytes(payload), {"bank": bank, "leafCount": leaf_count,
                     "directoryBank": bank, "directoryBytes": directory_bytes,
                     "rowBytes": (leaf_count + 7) // 8, "directoryRecordBytes": DIRECTORY.size,
                     "directoryAddress": 0x8000 + start_offset, "uniqueRows": len(shared),
                     "logicalBytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(),
                     "storage": "unused tail of final QBSA bank; camera bit added after decode",
                     "guard": proof}


BANKED_DIRECTORY = struct.Struct("<HB")


def banked_rows(payload, metadata, regions, *, directory_bank, directory_offset):
    """Relocate complete, unchanged RLE streams using 24-bit row pointers."""
    count = metadata["leafCount"]
    directory_bytes = count * BANKED_DIRECTORY.size
    if directory_offset + directory_bytes > BANK_BYTES:
        raise ValueError(f"brush PVS directory needs {directory_bytes} bytes; tail has {BANK_BYTES-directory_offset}")
    pointers = [DIRECTORY.unpack_from(payload, leaf * DIRECTORY.size)[0] - 0x8000 for leaf in range(count)]
    starts = sorted(set(pointers))
    ends = starts[1:] + [len(payload)]
    storage = [{"bank": bank, "offset": offset, "payload": bytearray()} for bank, offset in regions]
    relocated = {}
    for first, last in zip(starts, ends, strict=True):
        row = payload[first:last]
        for region in storage:
            offset = region["offset"] + len(region["payload"])
            if offset + len(row) <= BANK_BYTES:
                relocated[first] = BANKED_DIRECTORY.pack(0x8000 + offset, region["bank"])
                region["payload"].extend(row)
                break
        else:
            needed = len(payload) - count * DIRECTORY.size
            available = sum(BANK_BYTES - offset for _, offset in regions)
            raise ValueError(f"brush PVS rows need {needed} bytes across tails with {available} bytes; next row={len(row)}")
    directory = b"".join(relocated[pointer] for pointer in pointers)
    storage = [region for region in storage if region["payload"]]
    result = {**metadata, "bank": directory_bank, "directoryBank": directory_bank,
              "directoryAddress": 0x8000 + directory_offset, "directoryBytes": directory_bytes,
              "directoryRecordBytes": BANKED_DIRECTORY.size,
              "logicalBytes": len(directory) + sum(len(row["payload"]) for row in storage),
              "sha256": hashlib.sha256(directory + b"".join(row["payload"] for row in storage)).hexdigest(),
              "rowStorage": [{"bank": row["bank"], "offset": row["offset"], "bytes": len(row["payload"]),
                              "sha256": hashlib.sha256(row["payload"]).hexdigest()} for row in storage],
              "storage": "24-bit directory in brush texture tail; unchanged RLE rows in checked brush bank tails"}
    return directory, storage, result


def install_leaf_pvs(source, fragments, decompress, *, texture_chunks, texture_metadata,
                     runtime_chunks, runtime_metadata):
    """Use declared unoccupied bank tails without moving any existing records."""
    payload, metadata = build_leaf_pvs(source, fragments, decompress, bank=0, start_offset=0)
    first = runtime_metadata["firstBank"]
    directory_bank = first - 1
    directory_offset = (texture_bank_used_bytes(texture_metadata["textures"], directory_bank) + 1) & ~1
    regions = [(first + index, used) for index, used in enumerate(runtime_metadata["usedBytesByBank"])]
    for role in fragments.metadata["bankRoles"].values():
        count = role["bankCount"]
        used = role.get("logicalBytes", role.get("bytes")) - (count - 1) * BANK_BYTES
        regions.append((role["firstBank"] + count - 1, used))
    regions.sort(key=lambda item: (item[1], item[0]))
    directory, rows, metadata = banked_rows(payload, metadata, regions,
        directory_bank=directory_bank, directory_offset=directory_offset)
    textures, runtime = list(texture_chunks), list(runtime_chunks)

    def write_tail(previous, offset, added):
        if offset + len(added) > len(previous) or any(v != 0xFF for v in previous[offset:offset + len(added)]):
            raise ValueError("brush PVS overlaps an occupied bank range")
        result = bytearray(previous)
        result[offset:offset + len(added)] = added
        return bytes(result)

    textures[-1] = write_tail(textures[-1], directory_offset, directory)
    for row in rows:
        bank, offset, added = row["bank"], row["offset"], row["payload"]
        if first <= bank < first + len(runtime):
            index = bank - first
            runtime[index] = write_tail(runtime[index], offset, added)
            runtime_metadata["usedBytesByBank"][index] += len(added)
            runtime_metadata["freeBytesByBank"][index] -= len(added)
        else:
            path = Path(f"QuakeBSPBrushFragments{bank-fragments.metadata['firstBank']}.bin")
            fragments.outputs[path] = write_tail(fragments.outputs[path], offset, added)
            fragments.metadata["outputs"][path.as_posix()]["sha256"] = hashlib.sha256(fragments.outputs[path]).hexdigest()
    return tuple(textures), tuple(runtime), metadata
