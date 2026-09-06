#!/usr/bin/env python3
"""Generate a deterministic selective cache of exact composed Quake surfaces."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
import time
from dataclasses import dataclass
from functools import cmp_to_key
from pathlib import Path

from workspace_paths import shared_tools_root, workspace_root
from quake_release_layout import profile_identity_path
from typing import Any, Sequence


TOOLS = Path(__file__).resolve().parent
WORKSPACE = workspace_root(__file__)
EXAMPLE = WORKSPACE / "src/snes_quake"
SHARED = shared_tools_root(__file__)
sys.path[:0] = [str(TOOLS), str(SHARED)]

from evaluate_quake_bsp_precomposed_surfaces import (  # noqa: E402
    Assets,
    EvaluationError,
    Surface,
    build_surfaces,
    load_assets,
)
from snes_tooling.shared.generated_outputs import (  # noqa: E402
    GeneratedOutputError,
    OwnedFileFamily,
    sync_generated_outputs,
)
from quake_bsp_composed_cache_profile import (  # noqa: E402
    OwnerPixelProfile,
    ProfileError,
    encode_profile,
    load_profile,
)


DEFAULT_OUTPUT = EXAMPLE / "Data"
DEFAULT_DATA_DIR = EXAMPLE / "Data"
DEFAULT_PROFILE = WORKSPACE / "config/profiles/QuakeBSPComposedCacheOwnerProfile.bin"
PROFILE_PATTERN = "QuakeBSPComposedCacheOwnerProfile*.bin"
DEFAULT_PRIORITY_PROFILE = WORKSPACE / "config/profiles/QuakeBSPComposedCachePriorityProfile.json"
PRIORITY_PROFILE_PATTERN = "QuakeBSPComposedCachePriorityProfile*.json"
GSU_DIRECT_FIRST_PHYSICAL_BANK = 64
DIRECTORY_PHYSICAL_BANK = 2
DIRECTORY_CPU_LOAD = 0x82D000
DIRECTORY_GSU_ROM_BANK = 0x02
DIRECTORY_GSU_ROM_ADDRESS = 0xD000
DIRECTORY_REGION_BYTES = 0x3000
DEFAULT_FIRST_BANK = 64
# Payload physical halfbanks 64..86 leave 87..95 for GSU-direct alias assets.
DEFAULT_BANK_COUNT = 23
LAST_GSU_DIRECT_PHYSICAL_BANK = 95
BANK_BYTES = 32 * 1024
MISS_INDEX = 0xFFFF
DEMO_SELECTION_WEIGHT = 3
FLY_SELECTION_WEIGHT = 1
DESCRIPTOR = struct.Struct("<BHH3x")

FACE_DIRECTORY_PATH = Path("QuakeBSPComposedCacheFaceDirectory.bin")
DESCRIPTOR_PATH = Path("QuakeBSPComposedCacheDescriptors.bin")
DIRECTORY_PAYLOAD_PATH = Path("QuakeBSPComposedCacheDirectoryPayload.bin")
METADATA_PATH = Path("QuakeBSPComposedCacheMetadata.json")
CONSTANTS_PATH = Path("QuakeBSPComposedCache.i")
ASSETS_ASSEMBLY_PATH = Path("QuakeBSPComposedCacheAssets.s")
CHUNK_PREFIX = "QuakeBSPComposedCacheChunk"
CHUNK_FAMILY = OwnedFileFamily(
    prefix=CHUNK_PREFIX,
    suffix=".bin",
    numbered=True,
)


class CacheGenerationError(RuntimeError):
    """Report an invalid cache source or packing request."""


@dataclass(frozen=True, slots=True)
class PriorityProfile:
    """Owner pixels for the exact frame that currently limits playback."""

    face_count: int
    assets_sha256: str
    ordered_rate_hz: int
    pose: int
    dynamic_brushes_enabled: bool
    mdl_entities_enabled: bool
    owner_plane_sha256: str
    owner_pixel_total: int
    owner_counts: tuple[int, ...]
    payload_sha256: str


@dataclass(frozen=True, slots=True)
class CacheSurface:
    face: int
    width: int
    height: int
    minimum_s: int
    minimum_t: int
    pixels: bytes

    @property
    def size(self) -> int:
        return len(self.pixels)


@dataclass(frozen=True, slots=True)
class Placement:
    descriptor: int
    face: int
    physical_bank: int
    bank: int
    address: int
    minimum_s: int
    minimum_t: int
    width: int
    height: int
    size: int

    @property
    def address_bias(self) -> int:
        """Return the wrapped base for addressBias + s + width*t."""

        return (self.address - self.minimum_s - self.width * self.minimum_t) & 0xFFFF


@dataclass(frozen=True, slots=True)
class PackedCache:
    face_directory: bytes
    descriptors: bytes
    directory_payload: bytes
    chunks: tuple[bytes, ...]
    placements: tuple[Placement, ...]
    main_placement_count: int
    source_surface_faces: int
    eligible_faces: int
    zero_sized_faces: int
    oversized_faces: int
    width_over_255_faces: int
    height_over_256_faces: int
    budget_omitted_faces: int
    first_bank: int
    bank_count: int
    bank_bytes: int
    directory_bank_bytes: int
    profile: OwnerPixelProfile
    priority_profile: PriorityProfile | None

    @property
    def payload_bytes(self) -> int:
        return sum(placement.size for placement in self.placements)

    @property
    def main_payload_bytes(self) -> int:
        return sum(
            placement.size for placement in self.placements[: self.main_placement_count]
        )

    @property
    def directory_used_bytes(self) -> int:
        return (
            len(self.face_directory)
            + len(self.descriptors)
            + len(self.directory_payload)
        )


def derive_cache_surfaces(
    assets: Assets,
    surfaces: Sequence[Surface],
) -> tuple[CacheSurface, ...]:
    """Attach exact integer texture origins to evaluator-composed surfaces."""

    output: list[CacheSurface] = []
    seen: set[int] = set()
    for surface in surfaces:
        if surface.face in seen:
            raise CacheGenerationError(f"duplicate composed face {surface.face}")
        if not 0 <= surface.face < len(assets.faces):
            raise CacheGenerationError(f"composed face {surface.face} is out of range")
        seen.add(surface.face)

        first, count = assets.faces[surface.face]
        coordinates = assets.face_texture_coordinates[first : first + count]
        if count <= 0 or len(coordinates) != count:
            raise CacheGenerationError(
                f"composed face {surface.face} has invalid texture coordinates"
            )
        minimum_s = min(value[0] >> 4 for value in coordinates)
        maximum_s = max(value[0] >> 4 for value in coordinates)
        minimum_t = min(value[1] >> 4 for value in coordinates)
        maximum_t = max(value[1] >> 4 for value in coordinates)
        width = maximum_s - minimum_s + 1
        height = maximum_t - minimum_t + 1
        if (surface.width, surface.height) != (width, height):
            raise CacheGenerationError(
                f"composed face {surface.face} extent disagrees with its coordinates"
            )
        if len(surface.pixels) != width * height:
            raise CacheGenerationError(
                f"composed face {surface.face} payload has the wrong size"
            )
        output.append(
            CacheSurface(
                surface.face,
                width,
                height,
                minimum_s,
                minimum_t,
                surface.pixels,
            )
        )
    return tuple(output)


def load_priority_profile(
    path: Path,
    *,
    expected_face_count: int,
    expected_assets_sha256: str,
) -> PriorityProfile:
    """Load and strictly validate the checked-in limiting-frame profile."""

    payload = path.read_bytes()
    document = json.loads(payload)
    if document.get("schema") != "quake-bsp-composed-cache-priority-profile-v1":
        raise CacheGenerationError("priority profile schema is unsupported")
    if document.get("faceCount") != expected_face_count:
        raise CacheGenerationError("priority profile lost exact face identity")
    if document.get("assetsSha256") != expected_assets_sha256:
        raise CacheGenerationError("priority profile belongs to different assets")

    source = document.get("source")
    if not isinstance(source, dict):
        raise CacheGenerationError("priority profile source is missing")
    owner_pixels = document.get("ownerPixels")
    if not isinstance(owner_pixels, list):
        raise CacheGenerationError("priority profile owner pixels are missing")
    counts = [0] * expected_face_count
    for record in owner_pixels:
        if (
            not isinstance(record, list)
            or len(record) != 2
            or not all(isinstance(value, int) for value in record)
        ):
            raise CacheGenerationError("priority profile owner record is invalid")
        face, count = record
        if not 0 <= face < expected_face_count or count <= 0:
            raise CacheGenerationError("priority profile owner record is out of range")
        if counts[face]:
            raise CacheGenerationError("priority profile repeats a source face")
        counts[face] = count
    owner_total = sum(counts)
    if document.get("ownerPixelTotal") != owner_total:
        raise CacheGenerationError("priority profile owner total disagrees")

    def required_source(name: str, kind: type) -> Any:
        value = source.get(name)
        if not isinstance(value, kind):
            raise CacheGenerationError(
                f"priority profile source field {name} is invalid"
            )
        return value

    owner_sha256 = required_source("ownerPlaneSha256", str)
    if len(owner_sha256) != 64:
        raise CacheGenerationError("priority owner-plane SHA-256 is invalid")
    return PriorityProfile(
        face_count=expected_face_count,
        assets_sha256=expected_assets_sha256,
        ordered_rate_hz=required_source("orderedRateHz", int),
        pose=required_source("pose", int),
        dynamic_brushes_enabled=required_source("dynamicBrushesEnabled", bool),
        mdl_entities_enabled=required_source("mdlEntitiesEnabled", bool),
        owner_plane_sha256=owner_sha256,
        owner_pixel_total=owner_total,
        owner_counts=tuple(counts),
        payload_sha256=_sha256(payload),
    )


def select_owner_profile(
    paths: Sequence[Path], assets: Assets
) -> tuple[OwnerPixelProfile | None, Path | None, tuple[str, ...]]:
    """Select the unique profile bound to the generated world assets."""

    matches: list[tuple[OwnerPixelProfile, Path]] = []
    available_assets = []
    for path in paths:
        profile, _payload = load_profile(path)
        available_assets.append(profile.assets_sha256.hex())
        if (
            profile.face_count == len(assets.faces)
            and profile.assets_sha256.hex() == assets.input_sha256
        ):
            matches.append((profile, path))
    if len(matches) > 1:
        raise CacheGenerationError(
            "multiple owner profiles match the generated BSP assets"
        )
    if not matches:
        return None, None, tuple(available_assets)
    profile, path = matches[0]
    return profile, path, tuple(available_assets)


def select_priority_profile(
    paths: Sequence[Path], assets: Assets
) -> tuple[PriorityProfile | None, Path | None]:
    """Select the unique limiting-frame profile for the generated assets."""

    matches: list[Path] = []
    for path in paths:
        document = json.loads(path.read_bytes())
        if (
            document.get("faceCount") == len(assets.faces)
            and document.get("assetsSha256") == assets.input_sha256
        ):
            matches.append(path)
    if len(matches) > 1:
        raise CacheGenerationError(
            "multiple priority profiles match the generated BSP assets"
        )
    if not matches:
        return None, None
    path = matches[0]
    return (
        load_priority_profile(
            path,
            expected_face_count=len(assets.faces),
            expected_assets_sha256=assets.input_sha256,
        ),
        path,
    )


def _validate_pack_request(
    surfaces: Sequence[CacheSurface],
    face_count: int,
    profile: OwnerPixelProfile,
    first_bank: int,
    bank_count: int,
    bank_bytes: int,
) -> None:
    if not 0 < bank_bytes <= BANK_BYTES:
        raise CacheGenerationError("bank size must be in 1..32768")
    if face_count < 0 or face_count >= MISS_INDEX:
        raise CacheGenerationError("face count escapes the 16-bit directory")
    if profile.face_count != face_count:
        raise CacheGenerationError("selection profile lost exact face identity")
    if bank_count <= 0:
        raise CacheGenerationError("bank count must be positive")
    if first_bank < GSU_DIRECT_FIRST_PHYSICAL_BANK:
        raise CacheGenerationError("payload starts before the GSU-direct window")
    if first_bank + bank_count - 1 > LAST_GSU_DIRECT_PHYSICAL_BANK:
        raise CacheGenerationError(
            "payload physical bank range escapes FX3 GSU-direct halfbanks 64..95"
        )
    faces = [surface.face for surface in surfaces]
    if len(faces) != len(set(faces)):
        raise CacheGenerationError("cache surfaces lost exact face identity")
    if any(face < 0 or face >= face_count for face in faces):
        raise CacheGenerationError("cache surface face is outside the directory")


def _descriptor_bytes(placement: Placement) -> bytes:
    if not 0 <= placement.bank <= 0xFF:
        raise CacheGenerationError("surface bank escapes unsigned 8-bit")
    if not 0 <= placement.address <= 0xFFFF:
        raise CacheGenerationError("surface address escapes unsigned 16-bit")
    if not 0 < placement.width <= 0xFFFF:
        raise CacheGenerationError("surface width escapes unsigned 16-bit")
    return DESCRIPTOR.pack(
        placement.bank,
        placement.address_bias,
        placement.width,
    )


def gsu_location_for_physical_halfbank(
    physical_bank: int,
    offset: int = 0,
) -> tuple[int, int]:
    """Map an FX3 physical 32-KiB halfbank to its GSU ROMB/address pair."""

    if (
        not GSU_DIRECT_FIRST_PHYSICAL_BANK
        <= physical_bank
        <= LAST_GSU_DIRECT_PHYSICAL_BANK
    ):
        raise CacheGenerationError("physical halfbank is not GSU-direct")
    if not 0 <= offset < BANK_BYTES:
        raise CacheGenerationError("physical halfbank offset escapes 32 KiB")
    relative = physical_bank - GSU_DIRECT_FIRST_PHYSICAL_BANK
    bank = 0x60 + (relative >> 1)
    address = (0x8000 if relative & 1 else 0) + offset
    return bank, address


def cpu_load_address_for_physical_halfbank(physical_bank: int) -> int:
    """Return the linker address for an FX3 physical 32-KiB ROM halfbank."""

    if (
        not GSU_DIRECT_FIRST_PHYSICAL_BANK
        <= physical_bank
        <= LAST_GSU_DIRECT_PHYSICAL_BANK
    ):
        raise CacheGenerationError("physical halfbank escapes the GSU-direct window")
    return 0x600000 + (physical_bank - GSU_DIRECT_FIRST_PHYSICAL_BANK) * BANK_BYTES


def compare_profile_scores(
    left: CacheSurface,
    right: CacheSurface,
    profile: OwnerPixelProfile,
) -> int:
    """Compare exact normalized 3:1 demo/fly benefit per composed byte."""

    left_weight = normalized_selection_weight(profile, left.face)
    right_weight = normalized_selection_weight(profile, right.face)
    cross = left_weight * right.size - right_weight * left.size
    if cross:
        return -1 if cross > 0 else 1
    return (left.face > right.face) - (left.face < right.face)


def normalized_selection_weight(profile: OwnerPixelProfile, face: int) -> int:
    """Return the exact common-denominator 3:1 normalized corpus weight."""

    return (
        DEMO_SELECTION_WEIGHT * profile.demo_counts[face] * profile.fly_total
        + FLY_SELECTION_WEIGHT * profile.fly_counts[face] * profile.demo_total
    )


def compare_priority_scores(
    left: CacheSurface,
    right: CacheSurface,
    profile: PriorityProfile,
) -> int:
    """Compare limiting-frame owner pixels per directory byte exactly."""

    left_cost = left.size + DESCRIPTOR.size
    right_cost = right.size + DESCRIPTOR.size
    cross = (
        profile.owner_counts[left.face] * right_cost
        - profile.owner_counts[right.face] * left_cost
    )
    if cross:
        return -1 if cross > 0 else 1
    return (left.face > right.face) - (left.face < right.face)


def pack_cache(
    surfaces: Sequence[CacheSurface],
    face_count: int,
    profile: OwnerPixelProfile,
    *,
    first_bank: int = DEFAULT_FIRST_BANK,
    bank_count: int = DEFAULT_BANK_COUNT,
    bank_bytes: int = BANK_BYTES,
    directory_bank_bytes: int = DIRECTORY_REGION_BYTES,
    priority_profile: PriorityProfile | None = None,
) -> PackedCache:
    """Pack the balanced banks, then use directory slack for the limiter."""

    _validate_pack_request(
        surfaces, face_count, profile, first_bank, bank_count, bank_bytes
    )
    if not 0 < directory_bank_bytes <= BANK_BYTES:
        raise CacheGenerationError("directory bank size must be in 1..32768")
    if priority_profile is not None:
        if priority_profile.face_count != face_count:
            raise CacheGenerationError("priority profile lost exact face identity")
        if len(priority_profile.owner_counts) != face_count:
            raise CacheGenerationError("priority profile owner counts are incomplete")
    zero_sized = sum(surface.size == 0 for surface in surfaces)
    spanning_candidates = [
        surface
        for surface in surfaces
        if bank_bytes < surface.size <= 2 * bank_bytes
        and priority_profile is not None
        and priority_profile.owner_counts[surface.face] > 0
    ]
    if spanning_candidates and bank_bytes != BANK_BYTES:
        raise CacheGenerationError(
            "a spanning surface requires physical 32-KiB halfbanks"
        )
    if spanning_candidates and (first_bank & 1 or bank_count < 2):
        raise CacheGenerationError(
            "a limiting-frame spanning surface needs an even low halfbank pair"
        )
    spanning_faces = {surface.face for surface in spanning_candidates}
    oversized = sum(
        surface.size > bank_bytes and surface.face not in spanning_faces
        for surface in surfaces
    )
    width_over_255 = sum(surface.width > 255 for surface in surfaces)
    height_over_256 = sum(surface.height > 256 for surface in surfaces)
    eligible = [surface for surface in surfaces if 0 < surface.size <= bank_bytes]

    spanning_candidates.sort(
        key=cmp_to_key(
            lambda left, right: compare_priority_scores(left, right, priority_profile)
        )
    )

    eligible.sort(
        key=cmp_to_key(lambda left, right: compare_profile_scores(left, right, profile))
    )
    chunks: list[bytearray] = []
    chunk_used: list[int] = []
    placements: list[Placement] = []

    if spanning_candidates:
        surface = spanning_candidates[0]
        chunks.extend((bytearray(bank_bytes), bytearray(bank_bytes)))
        chunks[0][:bank_bytes] = surface.pixels[:bank_bytes]
        tail_bytes = surface.size - bank_bytes
        chunks[1][:tail_bytes] = surface.pixels[bank_bytes:]
        chunk_used.extend((bank_bytes, tail_bytes))
        bank, address = gsu_location_for_physical_halfbank(first_bank)
        placements.append(
            Placement(
                descriptor=0,
                face=surface.face,
                physical_bank=first_bank,
                bank=bank,
                address=address,
                minimum_s=surface.minimum_s,
                minimum_t=surface.minimum_t,
                width=surface.width,
                height=surface.height,
                size=surface.size,
            )
        )

    for surface in eligible:
        chunk_index = next(
            (
                index
                for index, used in enumerate(chunk_used)
                if surface.size <= bank_bytes - used
            ),
            None,
        )
        if chunk_index is None:
            if len(chunks) == bank_count:
                continue
            chunks.append(bytearray(bank_bytes))
            chunk_used.append(0)
            chunk_index = len(chunks) - 1
        offset = chunk_used[chunk_index]
        end = offset + surface.size
        chunks[chunk_index][offset:end] = surface.pixels
        chunk_used[chunk_index] = end
        physical_bank = first_bank + chunk_index
        bank, address = gsu_location_for_physical_halfbank(physical_bank, offset)
        placement = Placement(
            descriptor=len(placements),
            face=surface.face,
            physical_bank=physical_bank,
            bank=bank,
            address=address,
            minimum_s=surface.minimum_s,
            minimum_t=surface.minimum_t,
            width=surface.width,
            height=surface.height,
            size=surface.size,
        )
        placements.append(placement)

    main_placement_count = len(placements)
    directory_payload = bytearray()
    if priority_profile is not None:
        selected_faces = {placement.face for placement in placements}
        priority_candidates = [
            surface
            for surface in (*eligible, *spanning_candidates)
            if surface.face not in selected_faces
            and priority_profile.owner_counts[surface.face] > 0
        ]
        priority_candidates.sort(
            key=cmp_to_key(
                lambda left, right: compare_priority_scores(
                    left, right, priority_profile
                )
            )
        )
        fixed_bytes = face_count * 2 + main_placement_count * DESCRIPTOR.size
        remaining_bytes = directory_bank_bytes - fixed_bytes
        selected_tail: list[CacheSurface] = []
        for surface in priority_candidates:
            cost = surface.size + DESCRIPTOR.size
            if cost <= remaining_bytes:
                selected_tail.append(surface)
                remaining_bytes -= cost

        payload_offset = (
            face_count * 2
            + (main_placement_count + len(selected_tail)) * DESCRIPTOR.size
        )
        for surface in selected_tail:
            offset = payload_offset + len(directory_payload)
            bank = DIRECTORY_GSU_ROM_BANK
            address = DIRECTORY_GSU_ROM_ADDRESS + offset
            if address + surface.size > 0x10000:
                raise CacheGenerationError(
                    "directory-tail surface escapes its fixed ROM2 region"
                )
            placements.append(
                Placement(
                    descriptor=len(placements),
                    face=surface.face,
                    physical_bank=DIRECTORY_PHYSICAL_BANK,
                    bank=bank,
                    address=address,
                    minimum_s=surface.minimum_s,
                    minimum_t=surface.minimum_t,
                    width=surface.width,
                    height=surface.height,
                    size=surface.size,
                )
            )
            directory_payload.extend(surface.pixels)

    if len(placements) >= MISS_INDEX:
        raise CacheGenerationError("descriptor indices collide with the miss marker")
    directory = [MISS_INDEX] * face_count
    descriptors = bytearray()
    for placement in placements:
        directory[placement.face] = placement.descriptor
        descriptors.extend(_descriptor_bytes(placement))
    directory_bytes = b"".join(struct.pack("<H", value) for value in directory)
    directory_used_bytes = (
        len(directory_bytes) + len(descriptors) + len(directory_payload)
    )
    if directory_used_bytes > directory_bank_bytes:
        raise CacheGenerationError("directory payload escapes its fixed ROM2 region")
    return PackedCache(
        directory_bytes,
        bytes(descriptors),
        bytes(directory_payload),
        tuple(bytes(chunk) for chunk in chunks),
        tuple(placements),
        main_placement_count,
        len(surfaces),
        len(eligible) + len(spanning_candidates),
        zero_sized,
        oversized,
        width_over_255,
        height_over_256,
        len(eligible) + len(spanning_candidates) - len(placements),
        first_bank,
        bank_count,
        bank_bytes,
        directory_bank_bytes,
        profile,
        priority_profile,
    )


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def chunk_path(index: int) -> Path:
    return Path(f"{CHUNK_PREFIX}{index:02d}.bin")


def metadata_for(
    assets: Assets,
    source: dict[str, object],
    packed: PackedCache,
    *,
    profile_path: Path | None = DEFAULT_PROFILE,
    priority_profile_path: Path | None = DEFAULT_PRIORITY_PROFILE,
) -> dict[str, Any]:
    profile = packed.profile
    priority = packed.priority_profile
    profile_payload = encode_profile(profile)
    chunks = [
        {
            "index": index,
            "physicalBank": packed.first_bank + index,
            "gsuBank": gsu_location_for_physical_halfbank(packed.first_bank + index)[0],
            "gsuAddress": gsu_location_for_physical_halfbank(packed.first_bank + index)[
                1
            ],
            "file": chunk_path(index).as_posix(),
            "bytes": len(payload),
            "sha256": _sha256(payload),
        }
        for index, payload in enumerate(packed.chunks)
    ]
    placements = [
        {
            "descriptor": item.descriptor,
            "face": item.face,
            "surfaceBytes": item.size,
            "physicalBank": item.physical_bank,
            "gsuBank": item.bank,
            "gsuAddress": item.address,
            "addressBias": item.address_bias,
            "minimumS": item.minimum_s,
            "minimumT": item.minimum_t,
            "width": item.width,
            "height": item.height,
            "demoOwnerPixels": profile.demo_counts[item.face],
            "flyOwnerPixels": profile.fly_counts[item.face],
            "priorityOwnerPixels": (
                priority.owner_counts[item.face] if priority is not None else 0
            ),
            "storageTier": (
                "mainBanks"
                if item.descriptor < packed.main_placement_count
                else "directoryTail"
            ),
        }
        for item in packed.placements
    ]
    selected_faces = [item.face for item in packed.placements]
    selected_demo = sum(profile.demo_counts[face] for face in selected_faces)
    selected_fly = sum(profile.fly_counts[face] for face in selected_faces)
    selected_priority = (
        sum(priority.owner_counts[face] for face in selected_faces)
        if priority is not None
        else 0
    )
    weighted_coverage_numerator = (
        DEMO_SELECTION_WEIGHT * selected_demo * profile.fly_total
        + FLY_SELECTION_WEIGHT * selected_fly * profile.demo_total
    )
    weighted_coverage_denominator = (
        (DEMO_SELECTION_WEIGHT + FLY_SELECTION_WEIGHT)
        * profile.demo_total
        * profile.fly_total
    )
    used_last_bank = (
        packed.first_bank + len(packed.chunks) - 1 if packed.chunks else None
    )
    return {
        "schema": "quake-bsp-composed-cache-v1",
        "source": {
            "inputSha256": assets.input_sha256,
            **source,
        },
        "contract": {
            "composition": "exact technique-4 albedo plus static lightmap",
            "selectionOrder": (
                "descending exact (3*demo/demoTotal + fly/flyTotal)/surfaceBytes; "
                "source face ID ascending breaks ties; comparisons use integer "
                "cross-products"
            ),
            "directoryTailSelectionOrder": (
                "descending limiting-frame ownerPixels/(surfaceBytes+descriptorBytes); "
                "source face ID ascending breaks ties; main-bank selections remain "
                "unchanged"
            ),
            "spanningSelectionOrder": (
                "highest limiting-frame ownerPixels/(surfaceBytes+descriptorBytes) "
                "surface in 32769..65536 bytes occupies the first paired low/high "
                "GSU ROM bank before balanced first-fit selection"
            ),
            "selectionWeights": {
                "demo": DEMO_SELECTION_WEIGHT,
                "fly": FLY_SELECTION_WEIGHT,
            },
            "selectionNormalization": "each corpus is divided by its owner-pixel total",
            "packing": "deterministic first-fit in ranking order",
            "faceIdentity": "2-byte descriptor index per source face; FFFF is miss",
            "cameraOrDemoDependent": False,
            "bankCrossingAllowed": True,
            "bankCrossingContract": (
                "one priority surface may span the paired low/high physical "
                "halfbanks of one GSU ROM bank"
            ),
            "descriptor": "bank:u8,addressBias:u16,width:u16,reserved:u8[3]",
            "descriptorAddressing": "FX3 GSU ROMB/address, not CPU linker address",
            "descriptorAddressFormula": (
                "addressBias=(gsuAddress-minimumS-width*minimumT)&0xFFFF; "
                "pixelAddress=(addressBias+s+width*t)&0xFFFF"
            ),
            "surfaceEligibility": (
                "non-empty complete surface no larger than one physical 32-KiB "
                "halfbank, plus one limiting-frame surface no larger than one "
                "paired 64-KiB GSU ROM bank; width is unsigned 16-bit; height "
                "is not encoded"
            ),
        },
        "profile": {
            "schema": "quake-bsp-composed-cache-owner-profile-v1",
            "file": profile_metadata_path(profile_path),
            "bytes": len(profile_payload),
            "sha256": _sha256(profile_payload),
            "assetsSha256": profile.assets_sha256.hex(),
            "demo": {
                "artifactCount": profile.demo_artifact_count,
                "corpusSha256": profile.demo_corpus_sha256.hex(),
                "ownerPixels": profile.demo_total,
                "selectedOwnerPixels": selected_demo,
                "selectedCoveragePercent": 100.0 * selected_demo / profile.demo_total,
            },
            "fly": {
                "artifactCount": profile.fly_artifact_count,
                "corpusSha256": profile.fly_corpus_sha256.hex(),
                "ownerPixels": profile.fly_total,
                "selectedOwnerPixels": selected_fly,
                "selectedCoveragePercent": 100.0 * selected_fly / profile.fly_total,
            },
            "weightedNormalizedCoverage": {
                "numerator": weighted_coverage_numerator,
                "denominator": weighted_coverage_denominator,
                "percent": (
                    100.0 * weighted_coverage_numerator / weighted_coverage_denominator
                ),
            },
        },
        "priorityProfile": (
            {
                "schema": "quake-bsp-composed-cache-priority-profile-v1",
                "file": profile_metadata_path(priority_profile_path),
                "sha256": priority.payload_sha256,
                "assetsSha256": priority.assets_sha256,
                "orderedRateHz": priority.ordered_rate_hz,
                "pose": priority.pose,
                "dynamicBrushesEnabled": priority.dynamic_brushes_enabled,
                "mdlEntitiesEnabled": priority.mdl_entities_enabled,
                "ownerPlaneSha256": priority.owner_plane_sha256,
                "ownerPixels": priority.owner_pixel_total,
                "selectedOwnerPixels": selected_priority,
                "selectedCoveragePercent": (
                    100.0 * selected_priority / priority.owner_pixel_total
                ),
            }
            if priority is not None
            else None
        ),
        "budget": {
            "directoryPhysicalBank": DIRECTORY_PHYSICAL_BANK,
            "directoryCpuLoad": DIRECTORY_CPU_LOAD,
            "directoryGsuRomBank": DIRECTORY_GSU_ROM_BANK,
            "directoryGsuRomAddress": DIRECTORY_GSU_ROM_ADDRESS,
            "directoryBankBytes": packed.directory_bank_bytes,
            "firstBank": packed.first_bank,
            "lastBank": packed.first_bank + packed.bank_count - 1,
            "bankCount": packed.bank_count,
            "bankBytes": packed.bank_bytes,
            "budgetBytes": packed.bank_count * packed.bank_bytes,
        },
        "selection": {
            "sourceFaceCount": len(assets.faces),
            "eligibleFaceCount": packed.eligible_faces,
            "selectedFaceCount": len(packed.placements),
            "mainSelectedFaceCount": packed.main_placement_count,
            "directoryTailSelectedFaceCount": (
                len(packed.placements) - packed.main_placement_count
            ),
            "ineligibleComposedFaceCount": (
                packed.source_surface_faces - packed.eligible_faces
            ),
            "notComposedSurfaceFaceCount": (
                len(assets.faces) - packed.source_surface_faces
            ),
            "ineligibleReasonCounts": {
                "zeroSurfaceBytes": packed.zero_sized_faces,
                "largerThanSupportedCacheSpan": packed.oversized_faces,
            },
            "dimensionDiagnostics": {
                "widthOver255": packed.width_over_255_faces,
                "heightOver256": packed.height_over_256_faces,
            },
            "oversizedFaceCount": packed.oversized_faces,
            "budgetOmittedFaceCount": packed.budget_omitted_faces,
            "selectedMaxWidth": max(
                (item.width for item in packed.placements), default=0
            ),
            "selectedMaxHeight": max(
                (item.height for item in packed.placements), default=0
            ),
        },
        "packing": {
            "usedBankCount": len(packed.chunks),
            "usedFirstBank": packed.first_bank if packed.chunks else None,
            "usedLastBank": used_last_bank,
            "payloadBytes": packed.payload_bytes,
            "mainPayloadBytes": packed.main_payload_bytes,
            "mainAllocatedBytes": len(packed.chunks) * packed.bank_bytes,
            "mainPaddingBytes": (
                len(packed.chunks) * packed.bank_bytes - packed.main_payload_bytes
            ),
            "directoryPayloadBytes": len(packed.directory_payload),
            "directoryUsedBytes": packed.directory_used_bytes,
            "directoryPaddingBytes": (
                packed.directory_bank_bytes - packed.directory_used_bytes
            ),
        },
        "outputs": {
            "faceDirectory": {
                "file": FACE_DIRECTORY_PATH.as_posix(),
                "bytes": len(packed.face_directory),
                "sha256": _sha256(packed.face_directory),
            },
            "descriptors": {
                "file": DESCRIPTOR_PATH.as_posix(),
                "recordBytes": DESCRIPTOR.size,
                "bytes": len(packed.descriptors),
                "sha256": _sha256(packed.descriptors),
            },
            "directoryPayload": {
                "file": DIRECTORY_PAYLOAD_PATH.as_posix(),
                "bytes": len(packed.directory_payload),
                "sha256": _sha256(packed.directory_payload),
            },
            "chunks": chunks,
        },
        "placements": placements,
    }


def constants_for(packed: PackedCache, face_count: int) -> bytes:
    used_last = (
        packed.first_bank + len(packed.chunks) - 1
        if packed.chunks
        else packed.first_bank
    )
    first_gsu_bank, first_gsu_address = gsu_location_for_physical_halfbank(
        packed.first_bank
    )
    lines = [
        "; Generated by generate_quake_bsp_composed_cache.py.",
        ".ifndef __QUAKE_BSP_COMPOSED_CACHE_I__",
        "__QUAKE_BSP_COMPOSED_CACHE_I__ = 1",
        "",
        "BSP_COMPOSED_CACHE_SCHEMA = 1",
        f"BSP_COMPOSED_DIRECTORY_PHYSICAL_BANK = {DIRECTORY_PHYSICAL_BANK}",
        f"BSP_COMPOSED_CACHE_FIRST_PHYSICAL_BANK = {packed.first_bank}",
        f"BSP_COMPOSED_CACHE_FIRST_BANK = ${packed.first_bank:02X}",
        f"BSP_COMPOSED_CACHE_LAST_BANK = ${packed.first_bank + packed.bank_count - 1:02X}",
        f"BSP_COMPOSED_CACHE_BANK_COUNT = {packed.bank_count}",
        f"BSP_COMPOSED_CACHE_USED_BANK_COUNT = {len(packed.chunks)}",
        f"BSP_COMPOSED_CACHE_USED_LAST_BANK = ${used_last:02X}",
        f"BSP_COMPOSED_CACHE_BANK_BYTES = ${packed.bank_bytes:04X}",
        f"BSP_COMPOSED_CACHE_FIRST_GSU_ROM_BANK = ${first_gsu_bank:02X}",
        f"BSP_COMPOSED_CACHE_FIRST_GSU_ROM_ADDRESS = ${first_gsu_address:04X}",
        f"BSP_COMPOSED_CACHE_FACE_COUNT = {face_count}",
        f"BSP_COMPOSED_CACHE_SELECTED_FACE_COUNT = {len(packed.placements)}",
        f"BSP_COMPOSED_CACHE_MAIN_SELECTED_FACE_COUNT = {packed.main_placement_count}",
        f"BSP_COMPOSED_CACHE_DIRECTORY_SELECTED_FACE_COUNT = {len(packed.placements) - packed.main_placement_count}",
        f"BSP_COMPOSED_CACHE_FACE_DIRECTORY_BYTES = {len(packed.face_directory)}",
        f"BSP_COMPOSED_CACHE_DESCRIPTOR_BYTES = {DESCRIPTOR.size}",
        f"BSP_COMPOSED_CACHE_DESCRIPTORS_BYTES = {len(packed.descriptors)}",
        f"BSP_COMPOSED_CACHE_DIRECTORY_PAYLOAD_BYTES = {len(packed.directory_payload)}",
        "BSP_COMPOSED_CACHE_DIRECTORY_BYTES = BSP_COMPOSED_CACHE_FACE_DIRECTORY_BYTES+BSP_COMPOSED_CACHE_DESCRIPTORS_BYTES+BSP_COMPOSED_CACHE_DIRECTORY_PAYLOAD_BYTES",
        f"BSP_COMPOSED_DIRECTORY_GSU_ROM_BANK = ${DIRECTORY_GSU_ROM_BANK:02X}",
        f"BSP_COMPOSED_DIRECTORY_GSU_ROM_ADDRESS = ${DIRECTORY_GSU_ROM_ADDRESS:04X}",
        f"BSP_COMPOSED_DESCRIPTOR_GSU_ROM_ADDRESS = ${DIRECTORY_GSU_ROM_ADDRESS:04X}+BSP_COMPOSED_CACHE_FACE_DIRECTORY_BYTES",
        f"BSP_COMPOSED_CACHE_MISS = ${MISS_INDEX:04X}",
        "",
        ".endif",
        "",
    ]
    return "\n".join(lines).encode("ascii")


def assembly_assets_for(packed: PackedCache) -> bytes:
    """Emit the linker segments for the directory and packed payload banks."""

    directory_load = DIRECTORY_CPU_LOAD
    output_chunk_count = (
        packed.bank_count
        if packed.bank_count == DEFAULT_BANK_COUNT
        else len(packed.chunks)
    )
    lines = [
        "; Generated by generate_quake_bsp_composed_cache.py.",
        '.segment "BSP_COMPOSED_DIRECTORY"',
        "QuakeBSPComposedCacheFaceDirectory:",
        f'        .incbin "Data/{FACE_DIRECTORY_PATH.as_posix()}"',
        "QuakeBSPComposedCacheFaceDirectoryEnd:",
        "QuakeBSPComposedCacheDescriptors:",
        f'        .incbin "Data/{DESCRIPTOR_PATH.as_posix()}"',
        "QuakeBSPComposedCacheDescriptorsEnd:",
        "QuakeBSPComposedCacheDirectoryPayload:",
        f'        .incbin "Data/{DIRECTORY_PAYLOAD_PATH.as_posix()}"',
        "QuakeBSPComposedCacheDirectoryPayloadEnd:",
        '.assert QuakeBSPComposedCacheFaceDirectoryEnd - QuakeBSPComposedCacheFaceDirectory = BSP_COMPOSED_CACHE_FACE_DIRECTORY_BYTES, error, "Composed-cache face directory size disagrees"',
        '.assert QuakeBSPComposedCacheDescriptorsEnd - QuakeBSPComposedCacheDescriptors = BSP_COMPOSED_CACHE_DESCRIPTORS_BYTES, error, "Composed-cache descriptor size disagrees"',
        '.assert QuakeBSPComposedCacheDirectoryPayloadEnd - QuakeBSPComposedCacheDirectoryPayload = BSP_COMPOSED_CACHE_DIRECTORY_PAYLOAD_BYTES, error, "Composed-cache directory payload size disagrees"',
        '.assert __BSP_COMPOSED_DIRECTORY_SIZE__ = BSP_COMPOSED_CACHE_DIRECTORY_BYTES, lderror, "Composed-cache directory segment size disagrees"',
        f'.assert __BSP_COMPOSED_DIRECTORY_SIZE__ <= ${DIRECTORY_REGION_BYTES:04X}, lderror, "Composed-cache directory escapes its fixed ROM2 region"',
        f'.assert __BSP_COMPOSED_DIRECTORY_LOAD__ = ${directory_load:06X}, lderror, "Composed-cache directory physical halfbank moved"',
        '.assert __BSP_COMPOSED_DIRECTORY_LOAD__ >= __GSU_SKY_ROM_CODE_LOAD__ + __GSU_SKY_ROM_CODE_SIZE__, lderror, "Composed-cache directory overlaps GSU sky ROM code"',
    ]
    for index in range(output_chunk_count):
        segment = f"BSP_COMPOSED_{index}"
        label = f"QuakeBSPComposedCacheChunk{index:02d}"
        load = cpu_load_address_for_physical_halfbank(packed.first_bank + index)
        lines.extend(
            (
                f'.segment "{segment}"',
                f"{label}:",
                f'        .incbin "Data/{chunk_path(index).as_posix()}"',
                f"{label}End:",
                f'.assert {label}End - {label} = BSP_COMPOSED_CACHE_BANK_BYTES, error, "Composed-cache chunk {index:02d} size disagrees"',
                f'.assert __{segment}_SIZE__ = BSP_COMPOSED_CACHE_BANK_BYTES, lderror, "Composed-cache segment {index} size disagrees"',
                f'.assert __{segment}_LOAD__ = ${load:06X}, lderror, "Composed-cache physical halfbank {packed.first_bank + index} moved"',
            )
        )
    lines.append("")
    return "\n".join(lines).encode("ascii")


def outputs_for(
    assets: Assets,
    source: dict[str, object],
    packed: PackedCache,
    *,
    profile_path: Path | None = DEFAULT_PROFILE,
    priority_profile_path: Path | None = DEFAULT_PRIORITY_PROFILE,
) -> dict[Path, bytes]:
    report = metadata_for(
        assets,
        source,
        packed,
        profile_path=profile_path,
        priority_profile_path=priority_profile_path,
    )
    outputs = {
        FACE_DIRECTORY_PATH: packed.face_directory,
        DESCRIPTOR_PATH: packed.descriptors,
        DIRECTORY_PAYLOAD_PATH: packed.directory_payload,
        METADATA_PATH: (json.dumps(report, indent=2, sort_keys=True) + "\n").encode(
            "ascii"
        ),
        CONSTANTS_PATH: constants_for(packed, len(assets.faces)),
        ASSETS_ASSEMBLY_PATH: assembly_assets_for(packed),
    }
    output_chunk_count = (
        packed.bank_count
        if packed.bank_count == DEFAULT_BANK_COUNT
        else len(packed.chunks)
    )
    reserved_chunks = (
        *packed.chunks,
        *(
            bytes([0xFF]) * packed.bank_bytes
            for _ in range(output_chunk_count - len(packed.chunks))
        ),
    )
    outputs.update(
        (chunk_path(index), payload) for index, payload in enumerate(reserved_chunks)
    )
    return outputs


def _configured_map_entry(data_dir: Path) -> str:
    try:
        metadata = json.loads(
            (data_dir / "QuakeBSPMetadata.json").read_text(encoding="ascii")
        )
        map_entry = str(metadata["demo"]["map_entry"])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise CacheGenerationError(
            "configured world metadata has no BSP map"
        ) from error
    if not map_entry.startswith("maps/") or not map_entry.endswith(".bsp"):
        raise CacheGenerationError("configured world metadata has an invalid BSP map")
    return map_entry


def profile_metadata_path(path: Path | None) -> str | None:
    if path is None:
        return None
    resolved = path.resolve()
    for root in (EXAMPLE, WORKSPACE):
        try:
            return profile_identity_path(resolved.relative_to(root.resolve())).as_posix()
        except ValueError:
            pass
    return resolved.as_posix()


def configured_profile_paths(
    explicit: Path | None, profile_dir: Path, pattern: str
) -> tuple[Path, ...]:
    if explicit is not None:
        return (explicit.resolve(),)
    return tuple(
        sorted(profile_dir.resolve().glob(pattern), key=lambda path: path.name)
    )


def _empty_profile(assets: Assets) -> OwnerPixelProfile:
    """Return a valid zero-selection profile for an unsupported map variant."""

    if not assets.faces:
        raise CacheGenerationError("configured world has no faces")
    digest = hashlib.sha256(b"map-variant-composed-cache-disabled").digest()
    counts = (1, *(0 for _ in range(len(assets.faces) - 1)))
    return OwnerPixelProfile(
        face_count=len(assets.faces),
        demo_artifact_count=1,
        fly_artifact_count=1,
        demo_total=1,
        fly_total=1,
        assets_sha256=bytes.fromhex(assets.input_sha256),
        demo_corpus_sha256=digest,
        fly_corpus_sha256=digest,
        demo_counts=counts,
        fly_counts=counts,
    )


def _parse_integer(value: str) -> int:
    return int(value, 0)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--priority-profile", type=Path)
    parser.add_argument("--profile-dir", type=Path, default=DEFAULT_PROFILE.parent)
    parser.add_argument("--first-bank", type=_parse_integer, default=DEFAULT_FIRST_BANK)
    parser.add_argument("--bank-count", type=_parse_integer, default=DEFAULT_BANK_COUNT)
    parser.add_argument("--check", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    started = time.perf_counter()
    args = parse_args(argv)
    try:
        assets = load_assets(args.data_dir.resolve())
        map_entry = _configured_map_entry(args.data_dir.resolve())
        profile_dir = args.profile_dir.resolve()
        owner_paths = configured_profile_paths(
            args.profile, profile_dir, PROFILE_PATTERN
        )
        if not owner_paths:
            raise CacheGenerationError("no composed-cache owner profiles were found")
        configured_profile, selected_profile_path, available_profile_assets = (
            select_owner_profile(owner_paths, assets)
        )
        priority_paths = configured_profile_paths(
            args.priority_profile, profile_dir, PRIORITY_PROFILE_PATTERN
        )
        if map_entry == "maps/e1m3.bsp" and configured_profile is not None:
            profile = configured_profile
            priority_profile, selected_priority_profile_path = select_priority_profile(
                priority_paths, assets
            )
            surfaces, source = build_surfaces(assets)
            cache_surfaces = derive_cache_surfaces(assets, surfaces)
        else:
            profile = _empty_profile(assets)
            priority_profile = None
            selected_profile_path = None
            selected_priority_profile_path = None
            cache_surfaces = ()
            source = {
                "mapVariant": map_entry,
                "selection": (
                    "disabled; checked-in E1M3 owner profiles do not apply"
                    if map_entry != "maps/e1m3.bsp"
                    else "disabled; checked-in owner profiles belong to a different BSP asset identity"
                ),
                "availableProfileAssetsSha256": list(available_profile_assets),
            }
        packed = pack_cache(
            cache_surfaces,
            len(assets.faces),
            profile,
            first_bank=args.first_bank,
            bank_count=args.bank_count,
            priority_profile=priority_profile,
        )
        sync_generated_outputs(
            outputs_for(
                assets,
                source,
                packed,
                profile_path=selected_profile_path,
                priority_profile_path=selected_priority_profile_path,
            ),
            args.output.resolve(),
            check=args.check,
            owned_families=(CHUNK_FAMILY,),
        )
    except (
        OSError,
        ValueError,
        KeyError,
        EvaluationError,
        ProfileError,
        CacheGenerationError,
        GeneratedOutputError,
    ) as error:
        elapsed = time.perf_counter() - started
        print(f"error: {error}; elapsed={elapsed:.3f}s", file=sys.stderr)
        return 1
    action = "verified" if args.check else "generated"
    elapsed = time.perf_counter() - started
    print(
        f"{action} composed cache: faces={len(packed.placements)} "
        f"banks={len(packed.chunks)}/{packed.bank_count} "
        f"payload={packed.payload_bytes} bytes "
        f"directoryPayload={len(packed.directory_payload)} bytes "
        f"elapsed={elapsed:.3f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
