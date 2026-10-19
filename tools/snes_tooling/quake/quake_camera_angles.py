"""Explicit camera angle units for legacy and fine-angle ROM inspection."""

from __future__ import annotations


def rom_angle_steps(symbols: dict[str, int]) -> int:
    steps = symbols.get("CAMERA_ANGLE_STEPS", 32)
    if steps not in (32, 256):
        raise ValueError(f"unsupported ROM camera angle scale: {steps}")
    return steps


def convert_angle(value: int, source_steps: int, target_steps: int) -> int:
    """Convert an angle exactly; never silently round a fine camera fixture."""
    if source_steps not in (32, 256) or target_steps not in (32, 256):
        raise ValueError("camera angle steps must be 32 or 256")
    if type(value) is not int:
        raise ValueError("camera angles must be integers")
    converted, remainder = divmod(value * target_steps, source_steps)
    if remainder:
        raise ValueError("camera angle is not representable by the target ROM")
    return converted


def validate_orientation(yaw: int, pitch: int, steps: int) -> None:
    if steps not in (32, 256):
        raise ValueError("camera angle steps must be 32 or 256")
    if type(yaw) is not int or type(pitch) is not int:
        raise ValueError("camera angles must be integers")
    if not 0 <= yaw < steps:
        raise ValueError(f"manual-camera yaw must be in 0..{steps-1}")
    if not -steps // 4 <= pitch <= steps // 4:
        raise ValueError(f"manual-camera pitch must be in {-steps//4}..{steps//4}")
