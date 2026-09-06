"""Original Quake pickup yaw and the bounded NTSC fly animation clock."""

import math
import struct

from quake_bsp_sky_assets import SNES_NTSC_FRAMES_PER_SECOND

EF_ROTATE = 8
FLY_ROTATE_SENTINEL = -128  # Outside the signed Q6 sine/cosine range [-64, 64].
ROTATION_SPEED = 100
FLY_ROTATION_STEP_Q32 = round((1 << 32) * ROTATION_SPEED / (360 * SNES_NTSC_FRAMES_PER_SECOND))
ROTATION_BASES = tuple((round(math.sin(i * math.tau / 256) * 64),
                        round(math.cos(i * math.tau / 256) * 64)) for i in range(256))
ROTATION_BASES_BYTES = b"".join(struct.pack("<bb", *basis) for basis in ROTATION_BASES)


def rotation_phase_q16(server_time: float) -> int:
    """WinQuake anglemod(100 * cl.time), expressed as one unsigned turn."""
    if not math.isfinite(server_time) or server_time < 0:
        raise ValueError("alias rotation time must be finite and nonnegative")
    return int(server_time * ROTATION_SPEED * (65536 / 360)) & 0xFFFF


def mdl_yaw(model, network_yaw: float, server_time: float) -> float:
    if model.header.flags & EF_ROTATE:
        return rotation_phase_q16(server_time) * (360 / 65536)
    return network_yaw


def rotation_yaw_q8(phase_q32: int) -> int:
    return ((phase_q32 + 0x800000) >> 24) & 0xFF
