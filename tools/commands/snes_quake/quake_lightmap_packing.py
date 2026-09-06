#!/usr/bin/env python3
"""Deterministic six-bit Quake lightmap packing primitives."""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass


ROM_BANK_BYTES = 0x8000
LIGHTMAP_SAMPLE_BITS = 6
LIGHTMAP_SAMPLES_PER_GROUP = 4
LIGHTMAP_BYTES_PER_GROUP = 3
LIGHTMAP_BANK_MASK = 0x3F
LIGHTMAP_PHASE_SHIFT = 6


@dataclass(frozen=True)
class PackedLightmapLocation:
    bank: int
    address: int
    phase: int

    @property
    def encoded_bank(self) -> int:
        return self.bank | self.phase << LIGHTMAP_PHASE_SHIFT


@dataclass(frozen=True)
class PackedLightmapBuild:
    chunks: tuple[bytes, ...]
    locations: tuple[PackedLightmapLocation, ...]
    logical_sample_count: int
    unique_payload_count: int
    carrier_sample_count: int
    alignment_padding_samples: int
    padding_bits: int
    logical_sha256: str
    packed_sha256: str


def pack_six_bit_samples(samples: bytes) -> bytes:
    """Pack four unsigned six-bit samples into three little-endian bytes."""

    if any(sample >= 1 << LIGHTMAP_SAMPLE_BITS for sample in samples):
        raise ValueError("lightmap sample exceeds six bits")
    output = bytearray()
    accumulator = 0
    available = 0
    for sample in samples:
        accumulator |= sample << available
        available += LIGHTMAP_SAMPLE_BITS
        while available >= 8:
            output.append(accumulator & 0xFF)
            accumulator >>= 8
            available -= 8
    if available:
        output.append(accumulator)
    return bytes(output)


def unpack_six_bit_samples(
    packed: bytes, sample_offset: int, sample_count: int
) -> bytes:
    """Decode a bounded sample range from a packed lightmap bank."""

    if sample_offset < 0 or sample_count < 0:
        raise ValueError("lightmap sample range must be non-negative")
    output = bytearray()
    bit_offset = sample_offset * LIGHTMAP_SAMPLE_BITS
    for _ in range(sample_count):
        byte_offset = bit_offset >> 3
        if byte_offset >= len(packed):
            raise ValueError("packed lightmap sample range escapes its bank")
        word = packed[byte_offset]
        if byte_offset + 1 < len(packed):
            word |= packed[byte_offset + 1] << 8
        output.append((word >> (bit_offset & 7)) & 0x3F)
        bit_offset += LIGHTMAP_SAMPLE_BITS
    return bytes(output)


def lightmap_location_sample_offset(address: int, phase: int) -> int:
    """Recover a bank-local sample index from the runtime directory fields."""

    if not 0x8000 <= address <= 0xFFFF or not 0 <= phase < 4:
        raise ValueError("invalid packed lightmap location")
    byte_offset = address - 0x8000
    group_offset = byte_offset - max(0, phase - 1)
    if group_offset < 0 or group_offset % LIGHTMAP_BYTES_PER_GROUP:
        raise ValueError("packed lightmap address and phase disagree")
    return group_offset // LIGHTMAP_BYTES_PER_GROUP * LIGHTMAP_SAMPLES_PER_GROUP + phase


def pack_lightmap_payloads(
    payloads: tuple[bytes, ...], *, first_bank: int, maximum_bank_count: int
) -> PackedLightmapBuild:
    """Deduplicate and bit-pack group-aligned grids without a bank crossing."""

    if not payloads or any(not payload for payload in payloads):
        raise ValueError("packed lightmap payloads must not be empty")
    if maximum_bank_count <= 0 or not 0 <= first_bank <= LIGHTMAP_BANK_MASK:
        raise ValueError("invalid packed lightmap bank range")
    if first_bank + maximum_bank_count - 1 > LIGHTMAP_BANK_MASK:
        raise ValueError("packed lightmap banks exceed the encoded bank mask")
    if any(any(sample >= 64 for sample in payload) for payload in payloads):
        raise ValueError("lightmap payload contains a sample above level 63")

    samples_per_bank = ROM_BANK_BYTES * 8 // LIGHTMAP_SAMPLE_BITS
    carriers: list[bytearray] = []
    carrier_versions: list[int] = []
    suffix_index: dict[bytes, list[tuple[int, int]]] = {}
    payload_locations: dict[bytes, tuple[int, int]] = {}

    def index_carrier(carrier_index: int, maximum_suffix: int) -> None:
        carrier = carriers[carrier_index]
        version = carrier_versions[carrier_index]
        first_offset = max(0, len(carrier) - maximum_suffix)
        first_offset = (
            first_offset + LIGHTMAP_SAMPLES_PER_GROUP - 1
        ) // LIGHTMAP_SAMPLES_PER_GROUP * LIGHTMAP_SAMPLES_PER_GROUP
        for offset in range(
            first_offset, len(carrier), LIGHTMAP_SAMPLES_PER_GROUP
        ):
            suffix_index.setdefault(bytes(carrier[offset:]), []).append(
                (carrier_index, version)
            )

    unique_payloads = sorted(set(payloads), key=lambda item: (-len(item), item))
    maximum_payload = len(unique_payloads[0])
    for payload in unique_payloads:
        for carrier_index, carrier in enumerate(carriers):
            search_offset = 0
            while True:
                offset = carrier.find(payload, search_offset)
                if offset < 0:
                    break
                if offset % LIGHTMAP_SAMPLES_PER_GROUP == 0:
                    payload_locations[payload] = (carrier_index, offset)
                    break
                search_offset = offset + 1
            if payload in payload_locations:
                break
        else:
            carrier_index = -1
            overlap = 0
            for candidate_overlap in range(len(payload), 0, -1):
                candidates = suffix_index.get(payload[:candidate_overlap], ())
                valid_candidates = {
                    candidate_index
                    for candidate_index, version in candidates
                    if carrier_versions[candidate_index] == version
                    and len(carriers[candidate_index])
                    + len(payload)
                    - candidate_overlap
                    <= samples_per_bank
                }
                if valid_candidates:
                    carrier_index = min(valid_candidates)
                    overlap = candidate_overlap
                    break

            if carrier_index < 0:
                carrier_index = next(
                    (
                        candidate_index
                        for candidate_index, carrier in enumerate(carriers)
                        if len(carrier) % LIGHTMAP_SAMPLES_PER_GROUP == 0
                        and len(carrier) + len(payload) <= samples_per_bank
                    ),
                    -1,
                )

            if carrier_index < 0:
                carrier_index = len(carriers)
                carriers.append(bytearray(payload))
                carrier_versions.append(0)
                payload_locations[payload] = (carrier_index, 0)
            else:
                carrier = carriers[carrier_index]
                offset = len(carrier) - overlap
                if offset % LIGHTMAP_SAMPLES_PER_GROUP:
                    raise AssertionError("lightmap overlap lost group alignment")
                carrier.extend(payload[overlap:])
                carrier_versions[carrier_index] += 1
                payload_locations[payload] = (carrier_index, offset)
            index_carrier(carrier_index, maximum_payload)

    bank_samples = [bytearray()]
    carrier_starts: list[tuple[int, int]] = []
    alignment_padding_samples = 0
    for carrier in carriers:
        if len(carrier) > samples_per_bank:
            raise ValueError("one lightmap carrier exceeds a ROM bank")
        aligned_start = (
            len(bank_samples[-1]) + LIGHTMAP_SAMPLES_PER_GROUP - 1
        ) // LIGHTMAP_SAMPLES_PER_GROUP * LIGHTMAP_SAMPLES_PER_GROUP
        if aligned_start + len(carrier) > samples_per_bank:
            bank_samples.append(bytearray())
            aligned_start = 0
        padding = aligned_start - len(bank_samples[-1])
        alignment_padding_samples += padding
        bank_samples[-1].extend(bytes(padding))
        carrier_starts.append((len(bank_samples) - 1, aligned_start))
        bank_samples[-1].extend(carrier)
    if len(bank_samples) > maximum_bank_count:
        raise ValueError(
            "packed lightmaps exceed their ROM bank reservation: "
            f"{len(bank_samples)} > {maximum_bank_count}"
        )

    chunks = tuple(pack_six_bit_samples(bytes(samples)) for samples in bank_samples)
    locations: list[PackedLightmapLocation] = []
    for payload in payloads:
        carrier_index, inner_offset = payload_locations[payload]
        bank_index, carrier_offset = carrier_starts[carrier_index]
        sample_offset = carrier_offset + inner_offset
        if sample_offset % LIGHTMAP_SAMPLES_PER_GROUP:
            raise AssertionError("packed lightmap location lost group alignment")
        phase = 0
        address = 0x8000 + sample_offset * LIGHTMAP_SAMPLE_BITS // 8
        location = PackedLightmapLocation(first_bank + bank_index, address, phase)
        if location.encoded_bank == 0xFF:
            raise ValueError("packed lightmap location collides with missing sentinel")
        decoded_offset = lightmap_location_sample_offset(address, phase)
        decoded = unpack_six_bit_samples(chunks[bank_index], decoded_offset, len(payload))
        if decoded != payload:
            raise AssertionError("packed lightmap payload failed its round trip")
        locations.append(location)

    logical_digest = hashlib.sha256()
    for payload in payloads:
        logical_digest.update(struct.pack("<I", len(payload)))
        logical_digest.update(payload)
    return PackedLightmapBuild(
        chunks,
        tuple(locations),
        sum(len(payload) for payload in payloads),
        len(set(payloads)),
        sum(len(carrier) for carrier in carriers),
        alignment_padding_samples,
        sum(len(chunk) * 8 for chunk in chunks)
        - sum(len(samples) * LIGHTMAP_SAMPLE_BITS for samples in bank_samples),
        logical_digest.hexdigest(),
        hashlib.sha256(b"".join(chunks)).hexdigest(),
    )
