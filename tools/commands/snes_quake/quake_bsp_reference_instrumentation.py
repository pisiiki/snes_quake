#!/usr/bin/env python3
"""Control and inspect the live Quake reference renderer over its named pipe."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import struct
import tempfile
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any, Sequence


PROTOCOL = "quake-reference-instrumentation-v1"
MAX_MESSAGE_BYTES = 1 << 20
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class ReferenceInstrumentationError(RuntimeError):
    """A structured error returned by the reference renderer."""


class ReferenceInstrumentationClient:
    def __init__(self, pipe_name: str, *, timeout: float = 10.0) -> None:
        if os.name != "nt":
            raise OSError("reference instrumentation currently requires Windows")
        if not pipe_name or len(pipe_name) > 64:
            raise ValueError("pipe_name must contain 1-64 characters")
        if not 0.0 < timeout <= 600.0:
            raise ValueError("timeout must be between 0 and 600 seconds")
        self.pipe_name = pipe_name
        self.timeout = timeout
        self._handle: int | None = None
        self._request_id = 0
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._configure_api()

    def _configure_api(self) -> None:
        self._kernel32.WaitNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
        self._kernel32.WaitNamedPipeW.restype = wintypes.BOOL
        self._kernel32.CreateFileW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        self._kernel32.CreateFileW.restype = wintypes.HANDLE
        self._kernel32.ReadFile.argtypes = [
            wintypes.HANDLE,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            wintypes.LPVOID,
        ]
        self._kernel32.ReadFile.restype = wintypes.BOOL
        self._kernel32.WriteFile.argtypes = [
            wintypes.HANDLE,
            wintypes.LPCVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            wintypes.LPVOID,
        ]
        self._kernel32.WriteFile.restype = wintypes.BOOL
        self._kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._kernel32.CloseHandle.restype = wintypes.BOOL

    @property
    def connected(self) -> bool:
        return self._handle is not None

    def connect(self) -> None:
        if self.connected:
            raise RuntimeError("reference instrumentation client is already connected")
        path = rf"\\.\pipe\{self.pipe_name}"
        deadline = time.monotonic() + self.timeout
        while True:
            remaining_ms = max(1, int((deadline - time.monotonic()) * 1000.0))
            if self._kernel32.WaitNamedPipeW(path, min(remaining_ms, 100)):
                handle = self._kernel32.CreateFileW(
                    path,
                    GENERIC_READ | GENERIC_WRITE,
                    0,
                    None,
                    OPEN_EXISTING,
                    0,
                    None,
                )
                if handle != INVALID_HANDLE_VALUE:
                    self._handle = int(handle)
                    return
            if time.monotonic() >= deadline:
                self._raise_windows(
                    "reference instrumentation pipe did not become ready"
                )
            time.sleep(0.01)

    def close(self) -> None:
        handle = self._handle
        self._handle = None
        if handle is not None:
            self._kernel32.CloseHandle(handle)

    def request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        if self._handle is None:
            raise RuntimeError("reference instrumentation client is not connected")
        self._request_id += 1
        request: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
        }
        if params is not None:
            request["params"] = params
        payload = json.dumps(request, separators=(",", ":")).encode("utf-8")
        if len(payload) > MAX_MESSAGE_BYTES:
            raise ValueError("reference instrumentation request is too large")
        self._write_all(struct.pack("<I", len(payload)) + payload)
        response_size = struct.unpack("<I", self._read_exact(4))[0]
        if response_size == 0 or response_size > MAX_MESSAGE_BYTES:
            raise RuntimeError("reference instrumentation response size is invalid")
        response = json.loads(self._read_exact(response_size))
        if response.get("jsonrpc") != "2.0" or response.get("id") != self._request_id:
            raise RuntimeError("reference instrumentation response identity mismatch")
        if "error" in response:
            error = response["error"]
            raise ReferenceInstrumentationError(
                f"reference RPC {method} failed ({error.get('code')}): "
                f"{error.get('message')}"
            )
        if "result" not in response:
            raise RuntimeError("reference instrumentation response has no result")
        return response["result"]

    def wait_until_ready(self) -> dict[str, Any]:
        deadline = time.monotonic() + self.timeout
        while True:
            status = self.request("status")
            if status.get("protocol") != PROTOCOL:
                raise RuntimeError("reference instrumentation protocol mismatch")
            if status.get("ready"):
                return status
            if status.get("serverError"):
                raise RuntimeError(str(status["serverError"]))
            if time.monotonic() >= deadline:
                raise TimeoutError("reference renderer did not publish live state")
            time.sleep(0.01)

    def capture_frame(
        self, output: Path, *, rgb_output: Path | None = None
    ) -> dict[str, Any]:
        result = self.request("captureFrame")
        if result.get("protocol") != PROTOCOL or result.get("format") != "indexed8":
            raise RuntimeError("reference renderer returned an incompatible frame")
        indices = bytes.fromhex(result.pop("indicesHex"))
        expected = int(result["width"]) * int(result["height"])
        if len(indices) != expected:
            raise RuntimeError("reference renderer returned a truncated frame")
        output = output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(f".{output.name}.tmp")
        temporary.write_bytes(indices)
        temporary.replace(output)
        result["artifact"] = str(output)
        result["bytes"] = len(indices)
        result["sha256"] = hashlib.sha256(indices).hexdigest()
        rgb_hex = result.pop("rgb888Hex", None)
        if result.get("rgbFormat") != "rgb888" or not isinstance(rgb_hex, str):
            raise RuntimeError("reference renderer returned no direct RGB frame")
        rgb = bytes.fromhex(rgb_hex)
        if len(rgb) != expected * 3:
            raise RuntimeError("reference renderer returned a truncated RGB frame")
        result["rgbBytes"] = len(rgb)
        result["rgbSha256"] = hashlib.sha256(rgb).hexdigest()
        if rgb_output is not None:
            rgb_output = rgb_output.resolve()
            rgb_output.parent.mkdir(parents=True, exist_ok=True)
            rgb_temporary = rgb_output.with_name(f".{rgb_output.name}.tmp")
            rgb_temporary.write_bytes(
                f"P6\n{result['width']} {result['height']}\n255\n".encode("ascii") + rgb
            )
            rgb_temporary.replace(rgb_output)
            result["rgbArtifact"] = str(rgb_output)
        return result

    def capture_window(self, output: Path) -> dict[str, Any]:
        """Capture the application's scene and controls, never the desktop."""
        from PIL import Image

        started = time.monotonic()
        output = output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="quake-reference-ui-") as temporary:
            native = Path(temporary) / "client.bmp"
            accepted = self.request("captureWindow", {"path": str(native)})
            if accepted.get("accepted") is not True:
                raise RuntimeError("reference renderer rejected window capture")
            deadline = time.monotonic() + self.timeout
            while True:
                status = self.request("status")
                result = status.get("windowCapture")
                if result and result.get("path") == str(native):
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError("reference window capture did not finish")
                time.sleep(0.01)
            if result.get("status") != "pass":
                raise RuntimeError(f"reference window capture failed: {result.get('error')}")
            with Image.open(native) as frame:
                if frame.size != (result["width"], result["height"]):
                    raise RuntimeError("reference window capture dimensions disagree")
                frame = frame.convert("RGB")
                rgb_hash = hashlib.sha256(frame.tobytes()).hexdigest()
                frame.save(output, format="PNG")
        payload = output.read_bytes()
        return {
            **{key: value for key, value in result.items() if key != "path"},
            "artifact": str(output), "includesUi": True,
            "rgbSha256": rgb_hash, "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "elapsedSeconds": round(time.monotonic() - started, 3),
        }

    def inspect_aliases(self) -> dict[str, Any]:
        result = self.request("inspectAliases")
        if (
            result.get("protocol") != PROTOCOL
            or result.get("schema") != "quake-reference-alias-inspection-v1"
            or not isinstance(result.get("available"), bool)
        ):
            raise RuntimeError("reference renderer returned invalid alias diagnostics")
        if result["available"]:
            aliases = result.get("aliases")
            overwrites = result.get("overwrites")
            if not isinstance(aliases, list) or not isinstance(overwrites, list):
                raise RuntimeError("reference alias diagnostics are incomplete")
        return result

    def set_external_bsp_models(self, enabled: bool) -> dict[str, Any]:
        if not isinstance(enabled, bool):
            raise TypeError("external BSP enabled state must be boolean")
        result = self.request("setExternalBspModels", {"enabled": enabled})
        if result.get("accepted") is not True or result.get("enabled") is not enabled:
            raise RuntimeError("reference renderer rejected external BSP state")
        return result

    def set_sound(self, enabled: bool) -> dict[str, Any]:
        if not isinstance(enabled, bool):
            raise TypeError("sound enabled state must be boolean")
        result = self.request("setSound", {"enabled": enabled})
        if result.get("accepted") is not True or result.get("enabled") is not enabled:
            raise RuntimeError("reference renderer rejected sound state")
        return result

    def set_volume(self, volume: float) -> dict[str, Any]:
        if (
            isinstance(volume, bool)
            or not isinstance(volume, (float, int))
            or not 0.0 <= float(volume) <= 1.0
        ):
            raise ValueError("volume must be from 0.0 to 1.0")
        result = self.request("setVolume", {"volume": float(volume)})
        if result.get("accepted") is not True or abs(
            float(result.get("volume", -1.0)) - float(volume)
        ) > 1e-6:
            raise RuntimeError("reference renderer rejected sound volume")
        return result

    def _write_all(self, data: bytes) -> None:
        assert self._handle is not None
        offset = 0
        while offset < len(data):
            chunk = data[offset : offset + 0xFFFFFFFF]
            buffer = ctypes.create_string_buffer(chunk)
            transferred = wintypes.DWORD()
            if not self._kernel32.WriteFile(
                self._handle,
                buffer,
                len(chunk),
                ctypes.byref(transferred),
                None,
            ):
                self._raise_windows("reference instrumentation write failed")
            if transferred.value == 0:
                raise OSError("reference instrumentation write made no progress")
            offset += transferred.value

    def _read_exact(self, size: int) -> bytes:
        assert self._handle is not None
        chunks: list[bytes] = []
        remaining = size
        while remaining:
            buffer = ctypes.create_string_buffer(remaining)
            transferred = wintypes.DWORD()
            if not self._kernel32.ReadFile(
                self._handle,
                buffer,
                remaining,
                ctypes.byref(transferred),
                None,
            ):
                self._raise_windows("reference instrumentation read failed")
            if transferred.value == 0:
                raise EOFError("reference instrumentation pipe closed")
            chunks.append(buffer.raw[: transferred.value])
            remaining -= transferred.value
        return b"".join(chunks)

    @staticmethod
    def _raise_windows(context: str) -> None:
        error = ctypes.get_last_error()
        raise OSError(error, f"{context}: {ctypes.FormatError(error).strip()}")

    def __enter__(self) -> ReferenceInstrumentationClient:
        self.connect()
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pipe", required=True)
    parser.add_argument("--timeout", type=float, default=10.0)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    subparsers.add_parser("status")
    capture = subparsers.add_parser("capture")
    capture.add_argument("--out", type=Path, required=True)
    capture.add_argument("--rgb-out", type=Path)
    window = subparsers.add_parser("capture-window")
    window.add_argument("--out", type=Path, required=True)
    inspect_aliases = subparsers.add_parser("inspect-aliases")
    inspect_aliases.add_argument("--out", type=Path)
    subparsers.add_parser("pause")
    subparsers.add_parser("resume")
    seek = subparsers.add_parser("seek")
    seek.add_argument("pose", type=int)
    pace = subparsers.add_parser("set-pace")
    pace.add_argument("pace", choices=("timed", "fast"))
    rate = subparsers.add_parser("set-rate")
    rate.add_argument("rate_hz", type=int, choices=(2, 20))
    external = subparsers.add_parser("set-external-bsp-models")
    external.add_argument("state", choices=("on", "off"))
    sound = subparsers.add_parser("set-sound")
    sound.add_argument("state", choices=("on", "off"))
    volume = subparsers.add_parser("set-volume")
    volume.add_argument("volume", type=float)
    subparsers.add_parser("shutdown")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    started = time.monotonic()
    args = parse_args(argv)
    with ReferenceInstrumentationClient(args.pipe, timeout=args.timeout) as client:
        if args.operation == "status":
            result = client.wait_until_ready()
        elif args.operation == "capture":
            client.wait_until_ready()
            result = client.capture_frame(args.out, rgb_output=args.rgb_out)
        elif args.operation == "capture-window":
            client.wait_until_ready()
            result = client.capture_window(args.out)
        elif args.operation == "inspect-aliases":
            client.wait_until_ready()
            result = client.inspect_aliases()
            if args.out is not None:
                output = args.out.resolve()
                output.parent.mkdir(parents=True, exist_ok=True)
                temporary = output.with_name(f".{output.name}.tmp")
                temporary.write_text(
                    json.dumps(result, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                temporary.replace(output)
                result["artifact"] = str(output)
        elif args.operation in ("pause", "resume", "shutdown"):
            result = client.request(args.operation)
        elif args.operation == "seek":
            result = client.request("seek", {"pose": args.pose})
        elif args.operation == "set-pace":
            result = client.request("setPace", {"pace": args.pace})
        elif args.operation == "set-rate":
            result = client.request("setRate", {"rateHz": args.rate_hz})
        elif args.operation == "set-external-bsp-models":
            result = client.set_external_bsp_models(args.state == "on")
        elif args.operation == "set-sound":
            result = client.set_sound(args.state == "on")
        elif args.operation == "set-volume":
            result = client.set_volume(args.volume)
        else:
            raise AssertionError(f"unhandled operation: {args.operation}")
    result["elapsedSeconds"] = time.monotonic() - started
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
