from __future__ import annotations

import ctypes
import json
import os
import struct
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Iterable


PROTOCOL_VERSION = "CEAI1"
MAX_MESSAGE_BYTES = 1024 * 1024
STATE_GLOB = "cli-anything-cheat-engine-*.json"


class CEBridgeError(RuntimeError):
    """Base error for bridge discovery and transport failures."""


class CEBridgeProtocolError(CEBridgeError):
    """Raised when a bridge frame or response violates the protocol."""


class CEBridgeResponseError(CEBridgeError):
    """Raised when Cheat Engine returns a structured failure."""

    def __init__(self, response: dict[str, Any]):
        self.response = response
        super().__init__(str(response.get("error") or "Cheat Engine bridge request failed"))


@dataclass(frozen=True)
class SessionState:
    path: Path
    protocol: str
    pipe: str
    token: str
    ce_pid: int
    started_at: int

    @property
    def pipe_path(self) -> str:
        return rf"\\.\pipe\{self.pipe}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "state_file": str(self.path),
            "protocol": self.protocol,
            "pipe": self.pipe,
            "ce_pid": self.ce_pid,
            "started_at": self.started_at,
            "alive": is_process_alive(self.ce_pid),
        }


def parse_int(value: str | int) -> int:
    if isinstance(value, int):
        return value
    return int(value, 0)


def _load_state(path: Path) -> SessionState:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CEBridgeError(f"Invalid Cheat Engine state file {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise CEBridgeError(f"Cheat Engine state file must contain an object: {path}")

    protocol = raw.get("protocol")
    pipe = raw.get("pipe")
    token = raw.get("token")
    ce_pid = raw.get("ce_pid")
    started_at = raw.get("started_at", 0)
    if protocol != PROTOCOL_VERSION:
        raise CEBridgeError(f"Unsupported bridge protocol in {path}: {protocol!r}")
    if not isinstance(pipe, str) or not pipe:
        raise CEBridgeError(f"State file has no valid pipe name: {path}")
    if not isinstance(token, str) or len(token) < 32:
        raise CEBridgeError(f"State file has no valid token: {path}")
    if not isinstance(ce_pid, int) or ce_pid <= 0:
        raise CEBridgeError(f"State file has no valid CE process ID: {path}")
    if not isinstance(started_at, int):
        started_at = 0

    return SessionState(path.resolve(), protocol, pipe, token, ce_pid, started_at)


def is_process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    from ctypes import wintypes

    process_query_limited_information = 0x1000
    still_active = 259
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return False
    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


def get_process_image_path(pid: int) -> str | None:
    if os.name != "nt" or pid <= 0:
        return None
    from ctypes import wintypes

    process_query_limited_information = 0x1000
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return None
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return None
        return buffer.value
    finally:
        kernel32.CloseHandle(handle)


def candidate_state_files(explicit: str | os.PathLike[str] | None = None) -> list[Path]:
    if explicit:
        return [Path(explicit).expanduser().resolve()]

    env_path = os.environ.get("CLI_ANYTHING_CE_STATE_FILE")
    if env_path:
        return [Path(env_path).expanduser().resolve()]

    temp_root = Path(tempfile.gettempdir())
    return sorted(
        temp_root.glob(STATE_GLOB),
        key=lambda path: path.stat().st_mtime if path.exists() else 0,
        reverse=True,
    )


def list_sessions(explicit: str | os.PathLike[str] | None = None) -> list[SessionState]:
    sessions: list[SessionState] = []
    for path in candidate_state_files(explicit):
        try:
            sessions.append(_load_state(path))
        except CEBridgeError:
            continue
    return sessions


def resolve_session(explicit: str | os.PathLike[str] | None = None) -> SessionState:
    failures: list[str] = []
    for path in candidate_state_files(explicit):
        try:
            state = _load_state(path)
        except CEBridgeError as exc:
            failures.append(str(exc))
            continue
        if not is_process_alive(state.ce_pid):
            failures.append(f"Stale Cheat Engine state file: {path}")
            continue
        return state

    detail = f" ({'; '.join(failures[:3])})" if failures else ""
    raise CEBridgeError(
        "No running Cheat Engine AI bridge found. Install ceai_bridge.lua in CE's autorun "
        f"directory and restart Cheat Engine.{detail}"
    )


def encode_request(token: str, method: str, params: dict[str, Any] | None = None) -> bytes:
    if not method or "\0" in method:
        raise CEBridgeProtocolError("Method must be a non-empty string without NUL bytes")
    if "\0" in token:
        raise CEBridgeProtocolError("Token must not contain NUL bytes")

    fields = [PROTOCOL_VERSION, token, method]
    for key in sorted((params or {}).keys()):
        value = (params or {})[key]
        key_text = str(key)
        if isinstance(value, bool):
            value_text = "1" if value else "0"
        elif value is None:
            value_text = ""
        else:
            value_text = str(value)
        if "\0" in key_text or "\0" in value_text:
            raise CEBridgeProtocolError("Request keys and values must not contain NUL bytes")
        fields.extend([key_text, value_text])

    payload = "\0".join(fields).encode("utf-8") + b"\0"
    if len(payload) > MAX_MESSAGE_BYTES:
        raise CEBridgeProtocolError(f"Request exceeds {MAX_MESSAGE_BYTES} bytes")
    return struct.pack("<I", len(payload)) + payload


def _read_exact(stream: BinaryIO, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = stream.read(size - len(chunks))
        if not chunk:
            raise CEBridgeProtocolError("Unexpected EOF from Cheat Engine bridge")
        chunks.extend(chunk)
    return bytes(chunks)


def decode_response(stream: BinaryIO) -> dict[str, Any]:
    size = struct.unpack("<I", _read_exact(stream, 4))[0]
    if size <= 0 or size > MAX_MESSAGE_BYTES:
        raise CEBridgeProtocolError(f"Invalid response size: {size}")
    payload = _read_exact(stream, size)
    try:
        response = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CEBridgeProtocolError(f"Invalid JSON response from Cheat Engine: {exc}") from exc
    if not isinstance(response, dict):
        raise CEBridgeProtocolError("Cheat Engine response must be a JSON object")
    return response


def _wait_named_pipe(path: str, timeout: float) -> None:
    if os.name != "nt":
        raise CEBridgeError("The Cheat Engine named-pipe bridge is only supported on Windows")
    from ctypes import wintypes

    timeout_ms = max(1, min(int(timeout * 1000), 0xFFFFFFFF))
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.WaitNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
    kernel32.WaitNamedPipeW.restype = wintypes.BOOL
    if not kernel32.WaitNamedPipeW(path, timeout_ms):
        error = ctypes.get_last_error()
        raise CEBridgeError(f"Timed out waiting for Cheat Engine pipe {path} (WinError {error})")


class CheatEngineClient:
    def __init__(self, state_file: str | None = None, timeout: float = 30.0):
        self.state_file = state_file
        self.timeout = timeout

    def request(self, method: str, **params: Any) -> dict[str, Any]:
        state = resolve_session(self.state_file)
        frame = encode_request(state.token, method, params)
        deadline = time.monotonic() + self.timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CEBridgeError(f"Timed out opening Cheat Engine pipe {state.pipe_path}")
            _wait_named_pipe(state.pipe_path, remaining)
            try:
                pipe = open(state.pipe_path, "r+b", buffering=0)
                break
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise CEBridgeError(f"Failed to open Cheat Engine pipe: {exc}") from exc
                time.sleep(min(0.02, max(0.001, deadline - time.monotonic())))

        try:
            with pipe:
                pipe.write(frame)
                response = decode_response(pipe)
        except OSError as exc:
            raise CEBridgeError(f"Failed to communicate with Cheat Engine pipe: {exc}") from exc

        if response.get("ok") is not True:
            raise CEBridgeResponseError(response)
        return response


def session_dicts(states: Iterable[SessionState]) -> list[dict[str, Any]]:
    return [state.as_dict() for state in states]
