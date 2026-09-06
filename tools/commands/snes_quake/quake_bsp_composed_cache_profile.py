#!/usr/bin/env python3
"""Binary profile contract for balanced Quake composed-cache selection."""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


PROFILE_MAGIC = b"QBCP"
PROFILE_VERSION = 1
PROFILE_RECORD = struct.Struct("<II")
PROFILE_HEADER = struct.Struct("<4sHHIIIQQ32s32s32s")


class ProfileError(RuntimeError):
    """Report an invalid or stale composed-cache selection profile."""


@dataclass(frozen=True, slots=True)
class OwnerPixelProfile:
    face_count: int
    demo_artifact_count: int
    fly_artifact_count: int
    demo_total: int
    fly_total: int
    assets_sha256: bytes
    demo_corpus_sha256: bytes
    fly_corpus_sha256: bytes
    demo_counts: tuple[int, ...]
    fly_counts: tuple[int, ...]

    def balanced_weight(self, face: int) -> int:
        """Return the exact common-denominator balanced owner-pixel weight."""

        return (
            self.demo_counts[face] * self.fly_total
            + self.fly_counts[face] * self.demo_total
        )


def _validate_hash(name: str, value: bytes) -> None:
    if len(value) != hashlib.sha256().digest_size:
        raise ProfileError(f"{name} must be one SHA-256 digest")


def validate_profile(profile: OwnerPixelProfile) -> None:
    if profile.face_count <= 0:
        raise ProfileError("profile face count must be positive")
    if len(profile.demo_counts) != profile.face_count:
        raise ProfileError("demo counts lost face identity")
    if len(profile.fly_counts) != profile.face_count:
        raise ProfileError("fly counts lost face identity")
    if profile.demo_artifact_count <= 0 or profile.fly_artifact_count <= 0:
        raise ProfileError("profile corpora must contain artifacts")
    if profile.demo_total <= 0 or profile.fly_total <= 0:
        raise ProfileError("profile corpora must contain world-owner pixels")
    for name, counts, total in (
        ("demo", profile.demo_counts, profile.demo_total),
        ("fly", profile.fly_counts, profile.fly_total),
    ):
        if any(value < 0 or value > 0xFFFF_FFFF for value in counts):
            raise ProfileError(f"{name} face count escapes unsigned 32-bit")
        if sum(counts) != total:
            raise ProfileError(f"{name} total disagrees with per-face counts")
    _validate_hash("asset digest", profile.assets_sha256)
    _validate_hash("demo corpus digest", profile.demo_corpus_sha256)
    _validate_hash("fly corpus digest", profile.fly_corpus_sha256)


def encode_profile(profile: OwnerPixelProfile) -> bytes:
    validate_profile(profile)
    output = bytearray(
        PROFILE_HEADER.pack(
            PROFILE_MAGIC,
            PROFILE_VERSION,
            PROFILE_RECORD.size,
            profile.face_count,
            profile.demo_artifact_count,
            profile.fly_artifact_count,
            profile.demo_total,
            profile.fly_total,
            profile.assets_sha256,
            profile.demo_corpus_sha256,
            profile.fly_corpus_sha256,
        )
    )
    for demo, fly in zip(profile.demo_counts, profile.fly_counts, strict=True):
        output.extend(PROFILE_RECORD.pack(demo, fly))
    return bytes(output)


def decode_profile(payload: bytes) -> OwnerPixelProfile:
    if len(payload) < PROFILE_HEADER.size:
        raise ProfileError("profile is shorter than its header")
    (
        magic,
        version,
        record_bytes,
        face_count,
        demo_artifacts,
        fly_artifacts,
        demo_total,
        fly_total,
        assets_sha256,
        demo_sha256,
        fly_sha256,
    ) = PROFILE_HEADER.unpack_from(payload)
    if magic != PROFILE_MAGIC or version != PROFILE_VERSION:
        raise ProfileError("profile magic or version is unsupported")
    if record_bytes != PROFILE_RECORD.size:
        raise ProfileError("profile record size is unsupported")
    expected = PROFILE_HEADER.size + face_count * PROFILE_RECORD.size
    if len(payload) != expected:
        raise ProfileError("profile length disagrees with its face count")
    records = tuple(PROFILE_RECORD.iter_unpack(payload[PROFILE_HEADER.size :]))
    profile = OwnerPixelProfile(
        face_count,
        demo_artifacts,
        fly_artifacts,
        demo_total,
        fly_total,
        assets_sha256,
        demo_sha256,
        fly_sha256,
        tuple(record[0] for record in records),
        tuple(record[1] for record in records),
    )
    validate_profile(profile)
    return profile


def load_profile(
    path: Path,
    *,
    expected_face_count: int | None = None,
    expected_assets_sha256: str | None = None,
) -> tuple[OwnerPixelProfile, bytes]:
    payload = path.read_bytes()
    profile = decode_profile(payload)
    if expected_face_count is not None and profile.face_count != expected_face_count:
        raise ProfileError("profile face count disagrees with the current map")
    if (
        expected_assets_sha256 is not None
        and profile.assets_sha256.hex() != expected_assets_sha256.lower()
    ):
        raise ProfileError("profile asset digest disagrees with the current map")
    return profile, payload


def digest_artifacts(root: Path, paths: Sequence[Path]) -> bytes:
    """Hash ordered artifact identities and payloads relative to their root."""

    digest = hashlib.sha256()
    for path in paths:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        payload = path.read_bytes()
        digest.update(struct.pack("<I", len(relative)))
        digest.update(relative)
        digest.update(struct.pack("<Q", len(payload)))
        digest.update(payload)
    return digest.digest()
