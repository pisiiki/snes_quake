"""Bind exact packed world S/T records to their mandatory MSU carriers."""

from collections import Counter
from dataclasses import dataclass
from struct import Struct, iter_unpack

from snes_tooling.quake.quake_playable_layout import HALFBANK, ROM_BYTES


AXIS_PAIRS = ((0, 1), (0, 2), (1, 2))
WORD_MASK = 0xFFFF
WORLD_FACES_FILE = "QuakeBSPWorldFaces.bin"
WORLD_FACE = Struct("<HBBBB")
AFFINE_MODE_SHIFT = 6
AFFINE_MODE_MASK = 0xC0
AFFINE_VARIANT_BIT = 0x20
AFFINE_VARIANT_MASK = AFFINE_MODE_MASK | AFFINE_VARIANT_BIT
AFFINE_VARIANT_COUNT = 4
AFFINE_DESCRIPTOR_COUNT = 127
AFFINE_DESCRIPTOR_COUNT_MASK = 0xE0
AFFINE_DESCRIPTOR_FLAT_MASK = 0xF0
AFFINE_DESCRIPTOR = Struct("<BHH")
AFFINE_DESCRIPTOR_SEGMENT = "BSP_WORLD_AFFINE_DESCRIPTORS"
WORLD_VERTEX_FILE = "QuakeBSPWorldVertices.bin"
WORLD_INDEX_FILES = tuple(f"QuakeBSPWorldIndices{i}.bin" for i in range(2))
WORLD_COORDINATE_PREFIX = "QuakeBSPWorldTextureCoordinates"


@dataclass(frozen=True)
class AffineWorldCoordinates:
    faces: bytes
    face_count: int
    mode_faces: tuple[int, ...]
    bias_s_x: int
    bias_s_y: int
    bias_t_y: int
    bias_t_z: int
    variants: tuple[tuple[int, int, int], ...] = ()
    descriptor_bytes: bytes = b""

    @property
    def mode_mask(self):
        return AFFINE_VARIANT_MASK if self.variants else AFFINE_MODE_MASK

    @property
    def count_mask(self):
        return 0xFF ^ AFFINE_DESCRIPTOR_COUNT_MASK if self.descriptor_bytes else 0xFF

    def assembly(self):
        values = {
            "WORLD_AFFINE_UV_S_X": self.bias_s_x,
            "WORLD_AFFINE_UV_S_Y": self.bias_s_y,
            "WORLD_AFFINE_UV_T_Y": self.bias_t_y,
            "WORLD_AFFINE_UV_T_Z": self.bias_t_z,
        }
        for number, (mode, bias_s, bias_t) in enumerate(self.variants, 1):
            axis_s, axis_t = AXIS_PAIRS[mode - 1]
            prefix = f"WORLD_AFFINE_UV_VARIANT_{number}"
            values.update({f"{prefix}_S_SHIFT": 2 + 2 * axis_s,
                           f"{prefix}_T_SHIFT": 2 + 2 * axis_t,
                           f"{prefix}_S_BIAS": bias_s,
                           f"{prefix}_T_BIAS": bias_t})
        return (
            "PLAYABLE_WORLD_AFFINE_UV = 1\n"
            + "".join(f"{name} = ${value:X}\n" for name, value in values.items())
            + f'.assert BSP_WORLD_FACE_COUNT = {self.face_count}, lderror, '
              '"Affine UV table length disagrees with face count"\n'
        ).encode("ascii")


def _exact_affine_biases(points, samples, positive_axis, negative_axis, *, swapped=False):
    positive_uv, negative_uv = (1, 0) if swapped else (0, 1)
    positive_bias = (samples[0][positive_uv] - 64 * points[0][positive_axis]) & WORD_MASK
    negative_bias = (samples[0][negative_uv] + 64 * points[0][negative_axis]) & WORD_MASK
    if all(
        ((64 * point[positive_axis] + positive_bias) & WORD_MASK) == sample[positive_uv]
        and ((negative_bias - 64 * point[negative_axis]) & WORD_MASK) == sample[negative_uv]
        for point, sample in zip(points, samples, strict=True)
    ):
        return positive_bias, negative_bias
    return None


def build_world_affine_uv(data, *, extra_modes=False, descriptor_modes=False):
    records = {
        filename: (data/filename).read_bytes()
        for filename in (WORLD_VERTEX_FILE, WORLD_FACES_FILE, *WORLD_INDEX_FILES)
    }
    records.update((path.name, path.read_bytes())
                   for path in data.glob(f"{WORLD_COORDINATE_PREFIX}*.bin"))
    return build_world_affine_uv_records(
        records, extra_modes=extra_modes, descriptor_modes=descriptor_modes)


def build_world_affine_uv_records(records, *, extra_modes=False, descriptor_modes=False):
    if descriptor_modes and not extra_modes:
        raise ValueError("affine descriptor modes require the flag variants")
    # Three common axis-aligned texture mappings share four per-map biases.
    # Admit each mode only after proving both packed coordinates at every vertex.
    vertices = [
        (4*x + (low & 3), 4*y + ((low >> 2) & 3), 4*z + ((low >> 4) & 3))
        for x, y, z, low in iter_unpack("<bbbB", records[WORLD_VERTEX_FILE])
    ]
    index_bytes = b"".join(records[name] for name in WORLD_INDEX_FILES)
    coordinate_bytes = b"".join(
        records[name] for name in sorted(records)
        if name.startswith(WORLD_COORDINATE_PREFIX) and name.endswith(".bin")
    )
    indices = [index for (index,) in iter_unpack("<H", index_bytes)]
    coordinates = list(iter_unpack("<HH", coordinate_bytes))
    if len(indices) != len(coordinates):
        raise ValueError("world coordinate and index streams disagree")
    faces = bytearray(records[WORLD_FACES_FILE])
    matches = []
    descriptor_matches = []
    histograms = [Counter() for _ in AXIS_PAIRS]
    for first, count, flat, _, flags in WORLD_FACE.iter_unpack(faces):
        if flags not in (0, 1, 2):
            raise ValueError("source world flags collide with the linked affine mode")
        modes = {}
        candidates = set()
        if descriptor_modes and (count & AFFINE_DESCRIPTOR_COUNT_MASK
                                 or flat & AFFINE_DESCRIPTOR_FLAT_MASK):
            raise ValueError("source world face count or color overlaps its affine descriptor")
        if count:
            end = first + count
            if end > len(indices) or any(index >= len(vertices) for index in indices[first:end]):
                raise ValueError("affine UV face escapes its source streams")
            points = [vertices[index] for index in indices[first:end]]
            samples = coordinates[first:end]
            for mode, (axis_s, axis_t) in enumerate(AXIS_PAIRS, 1):
                pair = _exact_affine_biases(points, samples, axis_s, axis_t)
                if pair is not None:
                    modes[mode] = pair
                    histograms[mode-1][pair] += 1
                    if descriptor_modes:
                        candidates.add((False, mode, *pair))
                if descriptor_modes:
                    swapped = _exact_affine_biases(points, samples, axis_s, axis_t, swapped=True)
                    if swapped is not None:
                        candidates.add((True, mode, *swapped))
        matches.append(modes)
        if descriptor_modes:
            descriptor_matches.append(candidates)
    if not all(histograms):
        raise ValueError("affine UV modes have no exact source matches")
    selected = tuple(
        min(histogram, key=lambda pair: (-histogram[pair], pair))
        for histogram in histograms
    )
    (s_x, t_y), (other_s_x, t_z), (s_y, other_t_z) = selected
    if s_x != other_s_x or t_z != other_t_z:
        raise ValueError("dominant affine UV modes do not share their common biases")
    variants = []
    if extra_modes:
        remaining = [index for index, modes in enumerate(matches)
                     if not any(pair == selected[mode - 1] for mode, pair in modes.items())]
        # Prefer the bias pair that covers the most remaining source faces.
        for _ in range(AFFINE_VARIANT_COUNT):
            scores = Counter((mode, *pair) for index in remaining
                             for mode, pair in matches[index].items())
            if not scores:
                raise ValueError("affine UV variant has no exact source matches")
            variant = min(scores, key=lambda entry: (-scores[entry], entry))
            variants.append(variant)
            mode, bias_s, bias_t = variant
            remaining = [index for index in remaining
                         if matches[index].get(mode) != (bias_s, bias_t)]
    descriptor_indices = {}
    descriptor_bytes = bytearray()
    if descriptor_modes:
        for descriptor in range(1, AFFINE_DESCRIPTOR_COUNT + 1):
            scores = Counter(recipe for index in remaining for recipe in descriptor_matches[index])
            if not scores:
                break
            recipe = min(scores, key=lambda entry: (-scores[entry], entry))
            covered = [index for index in remaining if recipe in descriptor_matches[index]]
            descriptor_indices.update((index, descriptor) for index in covered)
            remaining = [index for index in remaining if index not in descriptor_indices]
            swapped, mode, positive_bias, negative_bias = recipe
            descriptor_bytes.extend(AFFINE_DESCRIPTOR.pack(
                7 + mode + 3 * swapped, positive_bias, negative_bias))
    flag_mode_count = len(AXIS_PAIRS) + len(variants) + 1
    counts = [0] * (flag_mode_count + len(descriptor_bytes) // AFFINE_DESCRIPTOR.size)
    for face, modes in enumerate(matches):
        mode = next((mode for mode, pair in modes.items() if pair == selected[mode-1]), 0)
        flags = mode << AFFINE_MODE_SHIFT
        if not mode:
            for index, (axis_mode, bias_s, bias_t) in enumerate(variants):
                if modes.get(axis_mode) == (bias_s, bias_t):
                    mode = index + len(AXIS_PAIRS) + 1
                    flags = (index << AFFINE_MODE_SHIFT) | AFFINE_VARIANT_BIT
                    break
        faces[(face + 1) * WORLD_FACE.size - 1] |= flags
        if not mode and (descriptor := descriptor_indices.get(face)):
            mode = flag_mode_count + descriptor - 1
            offset = face * WORLD_FACE.size
            faces[offset + 2] |= (descriptor & 7) << 5
            faces[offset + 3] |= (descriptor >> 3) << 4
        counts[mode] += 1
    if not all(counts[1:]):
        raise ValueError("selected affine UV mode has no encoded faces")
    return AffineWorldCoordinates(bytes(faces), len(matches), tuple(counts), s_x, s_y, t_y, t_z,
                                  tuple(variants), bytes(descriptor_bytes))


def restore_world_face_modes(faces, *, mode_mask=AFFINE_MODE_MASK, descriptors=False):
    restored = bytearray(faces)
    for offset in range(WORLD_FACE.size - 1, len(restored), WORLD_FACE.size):
        restored[offset] &= ~mode_mask
        if descriptors:
            restored[offset - 3] &= ~AFFINE_DESCRIPTOR_COUNT_MASK
            restored[offset - 2] &= ~AFFINE_DESCRIPTOR_FLAT_MASK
    return bytes(restored)


def coordinate_include(layout, module):
    chunks = [layout.placements.get((module, f"BSP_WORLD_TEXCOORD_{index}"))
              for index in range(4)]
    count = sum(chunk is not None for chunk in chunks)
    if not count or any(chunk is None for chunk in chunks[:count]):
        raise ValueError("world coordinate stream has a missing carrier")
    sizes, seeks = [], []
    for index, chunk in enumerate(chunks[:count]):
        seek = 64 + 2 * chunk.offset
        if (chunk.storage != "msu" or chunk.offset < ROM_BYTES or seek + 2 * chunk.size > 1 << 32
                or not 0 < chunk.size <= HALFBANK or chunk.size % 4
                or (index + 1 != count and chunk.size != HALFBANK)):
            raise ValueError("invalid world coordinate MSU carrier")
        sizes.append(f"${chunk.size:04X}")
        seeks.append(f"${seek:08X}")
    return ("PLAYABLE_WORLD_COORDINATE_STREAM = 1\n"
            "WORLD_COORDINATE_REQUEST_TAG = $0040\n"
            f"WORLD_COORDINATE_CHUNK_COUNT = {count}\n"
            ".macro WORLD_COORDINATE_CHUNKS\n"
            f"        .word {', '.join(sizes)}\n"
            ".endmacro\n.macro WORLD_COORDINATE_SEEKS\n"
            f"        .dword {', '.join(seeks)}\n"
            ".endmacro\n").encode("ascii")
