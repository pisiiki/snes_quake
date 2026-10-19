"""Detect host resources for bounded parallel workspace tools."""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
import struct
import subprocess
import sys


_RELATION_PROCESSOR_CORE = 0
_ERROR_INSUFFICIENT_BUFFER = 122


def _windows_physical_core_count_from_buffer(data: bytes) -> int | None:
    """Count processor-core records in a Windows topology response."""
    offset = 0
    cores = 0
    while offset < len(data):
        if len(data) - offset < 8:
            return None
        relationship, record_size = struct.unpack_from("<II", data, offset)
        if record_size < 8 or offset + record_size > len(data):
            return None
        if relationship == _RELATION_PROCESSOR_CORE:
            cores += 1
        offset += record_size
    return cores or None


def _windows_physical_core_count() -> int | None:
    """Query all Windows processor groups for their physical core records."""
    try:
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        query = kernel32.GetLogicalProcessorInformationEx
    except (AttributeError, OSError):
        return None
    query.argtypes = (
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.DWORD),
    )
    query.restype = wintypes.BOOL
    length = wintypes.DWORD()
    ctypes.set_last_error(0)
    if query(_RELATION_PROCESSOR_CORE, None, ctypes.byref(length)):
        return None
    if ctypes.get_last_error() != _ERROR_INSUFFICIENT_BUFFER or length.value < 8:
        return None
    buffer = ctypes.create_string_buffer(length.value)
    if not query(_RELATION_PROCESSOR_CORE, buffer, ctypes.byref(length)):
        return None
    return _windows_physical_core_count_from_buffer(buffer.raw[: length.value])


def _linux_physical_core_count() -> int | None:
    """Read Linux socket/core identifiers when the kernel exposes them."""
    try:
        text = Path("/proc/cpuinfo").read_text(encoding="utf-8")
    except OSError:
        return None
    identities = set()
    for block in text.split("\n\n"):
        fields = {}
        for line in block.splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                fields[key.strip()] = value.strip()
        if "physical id" in fields and "core id" in fields:
            identities.add((fields["physical id"], fields["core id"]))
    return len(identities) or None


def _macos_physical_core_count() -> int | None:
    """Read the macOS physical-core sysctl when it is available."""
    try:
        result = subprocess.run(
            ("sysctl", "-n", "hw.physicalcpu"),
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    if result.returncode:
        return None
    try:
        count = int(result.stdout.strip())
    except ValueError:
        return None
    return count if count > 0 else None


def _detected_physical_core_count() -> int | None:
    """Return the platform physical-core count, if it can be determined."""
    if sys.platform == "win32":
        return _windows_physical_core_count()
    if sys.platform.startswith("linux"):
        return _linux_physical_core_count()
    if sys.platform == "darwin":
        return _macos_physical_core_count()
    return None


def physical_core_count() -> int:
    """Return physical cores, falling back to the host's logical CPU count."""
    count = _detected_physical_core_count()
    if count is not None:
        return count
    return max(1, os.cpu_count() or 1)


def _windows_memory_status() -> tuple[int, int, int] | None:
    """Return available physical, total physical, and available commit bytes."""
    class MemoryStatus(ctypes.Structure):
        _fields_ = [("length", ctypes.c_uint32), ("load", ctypes.c_uint32)] + [
            (name, ctypes.c_uint64) for name in (
                "totalPhysical", "availablePhysical", "totalCommit", "availableCommit",
                "totalVirtual", "availableVirtual", "extendedVirtual",
            )
        ]

    try:
        query = ctypes.WinDLL("kernel32", use_last_error=True).GlobalMemoryStatusEx
        query.argtypes = (ctypes.POINTER(MemoryStatus),)
        query.restype = ctypes.c_int
        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        if query(ctypes.byref(status)):
            return status.availablePhysical, status.totalPhysical, status.availableCommit
    except (AttributeError, OSError):
        pass
    return None


def _windows_available_memory_bytes() -> int | None:
    """Bound allocations by both resident capacity and remaining commit."""
    status = _windows_memory_status()
    return min(status[0], status[2]) if status is not None else None


def physical_memory_status() -> tuple[int, int] | None:
    """Return fresh whole-host available and total physical RAM bytes."""
    if sys.platform == "win32":
        status = _windows_memory_status()
        return (status[0], status[1]) if status is not None else None
    if sys.platform.startswith("linux"):
        try:
            fields = {}
            for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
                parts = line.split()
                if len(parts) == 3 and parts[0] in ("MemAvailable:", "MemTotal:") and parts[2] == "kB":
                    fields[parts[0]] = int(parts[1]) * 1024
            if "MemAvailable:" in fields and "MemTotal:" in fields:
                return fields["MemAvailable:"], fields["MemTotal:"]
        except (OSError, ValueError):
            pass
    return None


def windows_commit_available_bytes() -> int | None:
    """Return fresh Windows commit headroom, distinct from free physical RAM."""
    if sys.platform != "win32":
        return None
    status = _windows_memory_status()
    return status[2] if status is not None else None


def available_memory_bytes() -> int | None:
    """Return available host memory; unknown capacity remains explicit."""
    if sys.platform == "win32":
        return _windows_available_memory_bytes()
    if sys.platform.startswith("linux"):
        try:
            for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
                fields = line.split()
                if len(fields) == 3 and fields[0] == "MemAvailable:" and fields[2] == "kB":
                    value = int(fields[1])
                    return value * 1024 if value >= 0 else None
        except (OSError, ValueError):
            pass
    return None
