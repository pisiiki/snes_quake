"""Host mirror of the bounded X2 world-only capacity retry."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import re
import struct

from snes_tooling.quake.quake_bsp_sky_assets import is_quake_sky_texture_name

X2_VIEWPORT = (128, 112, 64, 56)
CAPACITY_INPUTS = (
    "QuakeBSPWorldFaceTextureIds.bin",
    "QuakeBSPWorldTextureDirectory.bin",
    "QuakeBSPScene.i",
    "QuakeBSPMetadata.json",
)


@dataclass(frozen=True)
class CapacityMaterials:
    face_texture_ids: bytes
    directory: bytes
    sky_texture: int
    max_face_vertices: int
    source_sha256: str

    def ordinary(self, face_id):
        if not 0 <= face_id < len(self.face_texture_ids):
            return False
        texture_id = self.face_texture_ids[face_id]
        entry = self.directory[texture_id*8:(texture_id+1)*8]
        return (texture_id != self.sky_texture and len(entry) == 8
                and entry[7] & 0xFC == 0 and any(entry[3:5]) and any(entry[5:7]))


def load_capacity_materials(data_dir: Path, metadata: dict, face_count: int, *,
                            metadata_bytes: bytes) -> CapacityMaterials | None:
    """Older/incomplete diagnostics keep the strict unmodified admission path."""
    try:
        ids, directory, scene = ((data_dir / name).read_bytes() for name in CAPACITY_INPUTS[:3])
        exact = metadata['world']['packing']['exact_textures']
        enabled = metadata['selection']['sky_enabled']
        sky_ids = [int(record['packed_id']) for record in exact['textures']
                   if is_quake_sky_texture_name(record['name'])]
        texture_count = int(exact['texture_count'])
    except (FileNotFoundError, AttributeError, KeyError, TypeError, ValueError):
        return None
    max_vertices = re.search(rb'(?m)^BSP_WORLD_MAX_FACE_VERTICES\s*=\s*(\d+)\s*$', scene)
    if (len(ids) != face_count or not 0 < texture_count <= 255 or len(directory) != texture_count*8
            or max_vertices is None or type(enabled) is not bool or (enabled and len(sky_ids) != 1)):
        return None
    # Sky assets are generated after ordered QOR1. Use the same early packed
    # texture identities and configuration, not a later Sky include file.
    sky_id = sky_ids[0] if enabled else 255
    if enabled and not 0 <= sky_id < texture_count:
        return None
    digest = hashlib.sha256()
    for name, payload in zip(CAPACITY_INPUTS, (ids, directory, scene, metadata_bytes), strict=True):
        digest.update(name.encode("ascii"))
        digest.update(struct.pack("<I", len(payload)))
        digest.update(payload)
    return CapacityMaterials(ids, directory, sky_id, int(max_vertices[1]), digest.hexdigest())


def vertex_proof_mask(right, up, depth):
    """Return the same six fail-open bit predicates as PacketCapacityClassify."""
    r, u, d = right>>1, up>>1, depth>>1
    mask = sum(1<<bit for bit, distance in enumerate((d+r, d-r, d-u, d+u)) if distance <= -3)
    if 0 < depth < 16384:
        threshold = (depth>>1)+(depth>>4)+(depth>>6)+10
        if up >= threshold:
            mask |= 16
        elif up <= -threshold:
            mask |= 32
    return mask


def prune_x2_candidates(assets, candidates, camera, view_transform, materials):
    """Remove only faces proved empty in every applicable X2 world raster route."""
    cache = {}
    retained = []
    for face_id in candidates:
        if not materials.ordinary(face_id):
            retained.append(face_id)
            continue
        face = assets.faces[face_id]
        if not 3 <= face.vertex_count <= materials.max_face_vertices:
            retained.append(face_id)
            continue
        points = []
        mask = 0x3F
        for ordinal in assets.indices[face.first_index:face.first_index+face.vertex_count]:
            if not 0 <= ordinal < len(assets.vertices):
                mask = 0
                break
            if ordinal not in cache:
                cache[ordinal] = view_transform(assets, assets.vertices[ordinal], camera.position,
                                                camera.yaw, camera.pitch)
            point = cache[ordinal]
            points.append(point)
            mask &= vertex_proof_mask(*point)
            if not mask:
                break
        # Standard packed Q2 + actual Q6 matrix guarantees this bound in ROM.
        # Extra fail-open check supports host callers injecting custom transforms.
        if (not mask or len(points) != face.vertex_count or len(points) < 3
                or any(max(axis)-min(axis) > 32767 for axis in zip(*points, strict=True))
                or any(not -32768 <= value <= 32767 for point in points for value in point)):
            retained.append(face_id)
    return tuple(retained)
