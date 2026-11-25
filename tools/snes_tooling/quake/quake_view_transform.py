"""Packed camera components: exact integer coefficients, one final rounding."""


def _signed16(value):
    return ((int(value) + 0x8000) & 0xFFFF) - 0x8000


def packed_view_transform(vertex, camera, coefficients, *, vertex_fraction_bits=2):
    """Map packed coordinates to signed-word Q6 using Q6 camera coefficients."""
    scale = 1 << vertex_fraction_bits
    dx, dy, dz = (_signed16(int(vertex[i]) - int(camera[i]) * scale) for i in range(3))
    cy, sy, cp, sp = map(int, coefficients)
    forward = dx * cy + dy * sy

    def nearest(value, shift):
        return _signed16((value + (1 << (shift - 1))) >> shift) if shift else _signed16(value)

    return (nearest(dy * cy - dx * sy, vertex_fraction_bits),
            nearest(dz * cp * 64 - forward * sp, vertex_fraction_bits + 6),
            nearest(forward * cp + dz * sp * 64, vertex_fraction_bits + 6))
