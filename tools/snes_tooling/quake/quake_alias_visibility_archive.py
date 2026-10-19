"""Shared QAV3 rows: direct pose addresses, compact tokens and optional RLE.

The six CPU directories select an address in one GSU 64 KiB ROM bank. Rows
never cross that bank, but may cross its physical 32 KiB halfbank boundary.
Token order and partial-mask candidate order are unchanged from the reference.
Hidden candidate counts have no runtime meaning and are deliberately omitted.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from typing import Sequence


CAPACITY = 65536
FALLBACK = 65535
MAX_TOKENS = 128
MAX_RECORDS = 15
HEADER = struct.Struct("<BBH")


@dataclass(frozen=True)
class Token:
    ordinal: int
    hidden: bool
    candidates: int = 0
    mask: bytes = b""


def qav2_tokens(payload: bytes) -> tuple[Token, ...]:
    cursor = 0
    result = []
    while cursor < len(payload):
        if cursor + HEADER.size > len(payload):
            raise ValueError("truncated QAV2 token")
        token, kind, candidates = HEADER.unpack_from(payload, cursor)
        cursor += HEADER.size
        if token >= MAX_TOKENS or not candidates or kind not in (1, 2):
            raise ValueError("invalid QAV2 token")
        size = (candidates + 7) // 8 if kind == 1 else 0
        mask = payload[cursor:cursor + size]
        if len(mask) != size:
            raise ValueError("truncated QAV2 mask")
        cursor += size
        result.append(Token(token, kind == 2, candidates if size else 0, mask))
    validate_tokens(result)
    return tuple(result)


def validate_tokens(tokens: Sequence[Token]) -> None:
    if len(tokens) > MAX_RECORDS or len({t.ordinal for t in tokens}) != len(tokens):
        raise ValueError("invalid archive token count or duplicate ordinal")
    for token in tokens:
        if not 0 <= token.ordinal < MAX_TOKENS:
            raise ValueError("archive token ordinal escapes pointer RAM")
        if token.hidden:
            if token.candidates or token.mask:
                raise ValueError("hidden archive token retains a mask")
        elif (not 0 < token.candidates <= 65535 or
              len(token.mask) != (token.candidates + 7) // 8 or
              not 0 < sum(v.bit_count() for v in token.mask) < token.candidates or
              (token.candidates & 7 and token.mask[-1] >> (token.candidates & 7))):
            raise ValueError("invalid archive partial mask")


def raw_row(tokens: Sequence[Token]) -> bytes:
    validate_tokens(tokens)
    result = bytearray([len(tokens)])
    for token in tokens:
        result.append(token.ordinal | (128 if token.hidden else 0))
        if not token.hidden:
            result.extend(struct.pack("<H", token.candidates))
            result.extend(token.mask)
    return bytes(result)


def rle_encode(payload: bytes) -> bytes:
    result = bytearray()
    cursor = 0
    while cursor < len(payload):
        run = 1
        while cursor + run < len(payload) and payload[cursor + run] == payload[cursor] and run < 128:
            run += 1
        if run >= 3:
            result.extend((127 + run, payload[cursor]))
            cursor += run
            continue
        start = cursor
        cursor += run
        while cursor < len(payload) and cursor - start < 128:
            run = 1
            while cursor + run < len(payload) and payload[cursor + run] == payload[cursor] and run < 3:
                run += 1
            if run == 3:
                break
            cursor += min(run, 128 - (cursor - start))
        result.append(cursor - start - 1)
        result.extend(payload[start:cursor])
    return bytes(result)


def encode_row(tokens: Sequence[Token], *, codec: str = "auto") -> bytes:
    raw = raw_row(tokens)
    if codec not in ("auto", "raw"):
        raise ValueError("archive codec must be auto or raw")
    if codec == "raw" or not tokens:
        return raw
    compressed = bytes([raw[0] | 128]) + struct.pack("<H", len(raw) - 1) + rle_encode(raw[1:])
    return compressed if len(compressed) < len(raw) else raw


def decode_row(payload: bytes, address: int, *, maximum_decoded: int) -> tuple[tuple[Token, ...], int]:
    if not 0 <= address < min(len(payload), FALLBACK):
        raise ValueError("archive address escapes GSU ROM bank")
    cursor = address

    def byte() -> int:
        nonlocal cursor
        if cursor >= min(len(payload), CAPACITY):
            raise ValueError("archive row crosses GSU ROM bank")
        value = payload[cursor]
        cursor += 1
        return value

    header = byte()
    count = header & 127
    if count > MAX_RECORDS:
        raise ValueError("archive row count is invalid")
    expanded = bytearray()
    compressed = bool(header & 128)
    if compressed:
        length = byte() | byte() << 8
        if not count or not 0 < length <= maximum_decoded:
            raise ValueError("archive expanded length escapes mask RAM")
        while len(expanded) < length:
            control = byte()
            run = (control & 127) + 1
            if len(expanded) + run > length:
                raise ValueError("archive RLE run exceeds expanded length")
            if control & 128:
                expanded.extend(bytes([byte()]) * run)
            else:
                expanded.extend(byte() for _ in range(run))
        data, offset = bytes(expanded), 0
    else:
        data, offset = payload, cursor
    start = offset
    tokens = []
    for _ in range(count):
        if offset >= len(data):
            raise ValueError("truncated archive token")
        descriptor = data[offset]
        offset += 1
        hidden = bool(descriptor & 128)
        candidates, mask = 0, b""
        if not hidden:
            if offset + 2 > len(data):
                raise ValueError("truncated archive candidate count")
            candidates = struct.unpack_from("<H", data, offset)[0]
            offset += 2
            size = (candidates + 7) // 8
            mask = data[offset:offset + size]
            offset += size
        tokens.append(Token(descriptor & 127, hidden, candidates, mask))
    if offset - start > maximum_decoded or offset > len(data):
        raise ValueError("archive row escapes mask RAM or ROM")
    if compressed and offset != len(data):
        raise ValueError("archive RLE retains trailing data")
    validate_tokens(tokens)
    return tuple(tokens), cursor if compressed else offset


def pack(corpora: Sequence[Sequence[bytes]], *, codec: str = "auto") -> tuple[bytes, bytes, dict]:
    if len(corpora) != 6 or not corpora[0] or len({len(rows) for rows in corpora}) != 1:
        raise ValueError("archive requires six matching full-rate corpora")
    payload = bytearray(b"\x00")  # Shared empty/fully-visible row.
    addresses = {b"\x00": 0}
    directory = bytearray()
    unique_raw = set()
    compressed_rows = 0
    maximum_decoded = 0
    maximum_masks = 0
    expected_rows = []
    for rows in corpora:
        for row in rows:
            tokens = qav2_tokens(row)
            raw = raw_row(tokens)
            encoded = encode_row(tokens, codec=codec)
            unique_raw.add(raw)
            maximum_decoded = max(maximum_decoded, len(raw) - 1)
            maximum_masks = max(maximum_masks, sum(len(t.mask) for t in tokens))
            if encoded not in addresses:
                address = len(payload)
                if address >= FALLBACK or address + len(encoded) > CAPACITY:
                    raise ValueError("shared archive exceeds its GSU ROM bank")
                addresses[encoded] = address
                payload.extend(encoded)
                compressed_rows += bool(encoded[0] & 128)
            directory.extend(struct.pack("<H", addresses[encoded]))
            expected_rows.append(tokens)
    boundaries = set(addresses.values())
    crossing = 0
    for address in boundaries:
        _, end = decode_row(payload, address, maximum_decoded=maximum_decoded)
        crossing += address < 32768 < end
        if end not in boundaries and end != len(payload):
            raise ValueError("archive row does not end at a payload boundary")
    for (address,), expected in zip(struct.iter_unpack("<H", directory), expected_rows, strict=True):
        if decode_row(payload, address, maximum_decoded=maximum_decoded)[0] != expected:
            raise ValueError("archive reconstruction differs from reference tokens")
    metadata = dict(codec=codec, sourceRows=len(corpora[0]), projectionBrushStreams=6,
        uniqueRows=len(addresses), compressedRows=compressed_rows, directoryBytes=len(directory),
        payloadBytes=len(payload), paddingBytes=CAPACITY-len(payload), allocatedPayloadBytes=CAPACITY,
        uncompressedSharedBytes=sum(map(len, unique_raw)), maximumDecodedBytes=maximum_decoded,
        maximumMaskBytes=maximum_masks, reconstructedRows=len(expected_rows),
        halfbankCrossingRows=crossing, directorySha256=hashlib.sha256(directory).hexdigest(),
        payloadSha256=hashlib.sha256(payload).hexdigest())
    return bytes(payload).ljust(CAPACITY, b"\xff"), bytes(directory), metadata
