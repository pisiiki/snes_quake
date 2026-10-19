"""Read a file snapshot without blocking atomic replacement on Windows."""
from __future__ import annotations

import os
from pathlib import Path
from typing import BinaryIO


if os.name == 'nt':
    import ctypes
    from ctypes import wintypes
    import msvcrt

    _kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    _kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
        wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
        wintypes.HANDLE]
    _kernel.CreateFileW.restype = wintypes.HANDLE
    _kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel.CloseHandle.restype = wintypes.BOOL
    _kernel.SetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_int,
        wintypes.LPVOID, wintypes.DWORD]
    _kernel.SetFileInformationByHandle.restype = wintypes.BOOL

    class _RenameInfo(ctypes.Structure):
        _fields_ = [('flags', wintypes.DWORD), ('root', wintypes.HANDLE),
            ('length', wintypes.DWORD), ('name', wintypes.WCHAR*1)]


def _native_path(path: Path | str) -> str:
    # Explicit extended paths also work when the caller has not enabled the
    # machine's long-path policy. Preserve already-prefixed drive/UNC paths.
    path = os.path.abspath(path)
    if not path.startswith('\\\\?\\'):
        path = ('\\\\?\\UNC\\'+path[2:]) if path.startswith('\\\\') else '\\\\?\\'+path
    return path


def _snapshot_fd(path: str, _flags: int) -> int:
    path = _native_path(path)
    handle = _kernel.CreateFileW(path, 0x80000000, 0x1 | 0x2 | 0x4,
        None, 3, 0x80, None)  # GENERIC_READ, SHARE_READ|WRITE|DELETE, OPEN_EXISTING.
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        # On success the CRT owns the handle; closing the Python stream closes
        # it exactly once. On conversion failure ownership remains here.
        return msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except BaseException:
        _kernel.CloseHandle(handle)
        raise


def _windows_replace(source: Path | str, destination: Path | str) -> None:
    # MoveFileEx (os.replace) can still reject an open destination even with
    # delete sharing. FileRenameInfoEx POSIX semantics retain the old handles
    # while atomically installing the new name; no unlink/copy gap is needed.
    # https://learn.microsoft.com/windows-hardware/drivers/ddi/ntifs/ns-ntifs-_file_rename_information
    name = _native_path(destination).encode('utf-16-le')
    size = ctypes.sizeof(_RenameInfo)+len(name)
    buffer = ctypes.create_string_buffer(size)
    info = _RenameInfo.from_buffer(buffer)
    info.flags, info.root, info.length = 0x1 | 0x2, None, len(name)
    ctypes.memmove(ctypes.addressof(buffer)+_RenameInfo.name.offset, name, len(name))
    handle = _kernel.CreateFileW(_native_path(source), 0x10000, 0x7, None, 3,
        0x02000000 | 0x00200000, None)  # DELETE; move directories/reparse points as themselves.
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if not _kernel.SetFileInformationByHandle(handle, 22, buffer, size):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        _kernel.CloseHandle(handle)


def replace_snapshot(source: Path | str, destination: Path | str) -> None:
    """Atomically install a file, retaining already-open shared snapshots."""
    if os.name == 'nt':
        try:
            return _windows_replace(source, destination)
        except OSError as error:
            if getattr(error, 'winerror', None) not in (1, 50, 87, 120):
                raise
            # Older Windows/filesystems may not implement FileRenameInfoEx.
            # Keep their atomic rename semantics; caller still bounds retries.
    os.replace(source, destination)


def open_snapshot(path: Path | str) -> BinaryIO:
    """Keep reading the old complete file while its pathname is replaced.

    Writers must publish by atomic replacement, never by truncating this file.
    FILE_SHARE_DELETE permits rename/unlink while the read handle remains open;
    pair this with replace_snapshot for open-destination Windows replacement.
    """
    return open(path, 'rb', opener=_snapshot_fd if os.name == 'nt' else None)


def read_snapshot_text(path: Path | str, *, encoding: str = 'utf-8') -> str:
    with open_snapshot(path) as stream:
        return stream.read().decode(encoding)
