"""Shared scene-palette transforms; sprite indices never change for a flash."""

import struct

# Warm light, blended at one eighth in the native five-bit channel domain.
FLASH_TINT = (31, 24, 12)
FLASH_DENOMINATOR = 8


def quantize_rgb555_channels(rgb):
    """Round an array of RGB888 channels to the native five-bit domain."""
    import numpy as np

    return ((np.asarray(rgb, dtype=np.uint16) * 31 + 127) // 255).astype(np.uint8)


def flash_palette(palette: bytes) -> bytes:
    if len(palette) != 512:
        raise ValueError("scene palette must contain 256 RGB555 words")
    words = []
    for (word,) in struct.iter_unpack("<H", palette):
        if word & 0x8000:
            raise ValueError("scene palette contains an invalid RGB555 word")
        words.append(sum(
            ((((word >> shift) & 31) * (FLASH_DENOMINATOR - 1) + tint
              + FLASH_DENOMINATOR // 2) // FLASH_DENOMINATOR) << shift
            for shift, tint in zip((0, 5, 10), FLASH_TINT, strict=True)
        ))
    return struct.pack("<256H", *words)
