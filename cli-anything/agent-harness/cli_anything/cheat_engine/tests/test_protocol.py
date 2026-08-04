from __future__ import annotations

import io
import json
import os
import struct

import pytest

from cli_anything.cheat_engine.utils import ce_backend


def _state_file(tmp_path, *, pid=1234, started_at=10):
    path = tmp_path / "session.json"
    path.write_text(
        json.dumps(
            {
                "protocol": ce_backend.PROTOCOL_VERSION,
                "pipe": "ce-test-pipe",
                "token": "a" * 64,
                "ce_pid": pid,
                "started_at": started_at,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_encode_request_uses_length_prefix_and_sorted_fields():
    frame = ce_backend.encode_request("token", "memory.read", {"size": 4, "address": 16})
    size = struct.unpack("<I", frame[:4])[0]

    assert size == len(frame) - 4
    assert frame[4:] == b"\0".join(
        [b"CEAI1", b"token", b"memory.read", b"address", b"16", b"size", b"4", b""]
    )


@pytest.mark.parametrize(
    ("token", "method", "params"),
    [
        ("bad\0token", "session.status", {}),
        ("token", "bad\0method", {}),
        ("token", "session.status", {"bad\0key": "value"}),
        ("token", "session.status", {"key": "bad\0value"}),
    ],
)
def test_encode_request_rejects_nul(token, method, params):
    with pytest.raises(ce_backend.CEBridgeProtocolError, match="NUL"):
        ce_backend.encode_request(token, method, params)


def test_encode_request_rejects_oversized_payload():
    with pytest.raises(ce_backend.CEBridgeProtocolError, match="exceeds"):
        ce_backend.encode_request("token", "memory.write", {"hex": "a" * (1024 * 1024)})


def test_decode_response_returns_json_object():
    payload = json.dumps({"ok": True, "data": {"pid": 7}}).encode()
    response = ce_backend.decode_response(io.BytesIO(struct.pack("<I", len(payload)) + payload))

    assert response == {"ok": True, "data": {"pid": 7}}


@pytest.mark.parametrize(
    "frame",
    [
        b"\x01\x00",
        struct.pack("<I", ce_backend.MAX_MESSAGE_BYTES + 1),
        struct.pack("<I", 4) + b"no",
        struct.pack("<I", 4) + b"nope",
        struct.pack("<I", 2) + b"[]",
    ],
)
def test_decode_response_rejects_invalid_frames(frame):
    with pytest.raises(ce_backend.CEBridgeProtocolError):
        ce_backend.decode_response(io.BytesIO(frame))


def test_explicit_state_file_is_loaded(tmp_path, monkeypatch):
    path = _state_file(tmp_path)
    monkeypatch.setattr(ce_backend, "is_process_alive", lambda pid: pid == 1234)

    state = ce_backend.resolve_session(path)

    assert state.path == path.resolve()
    assert state.pipe_path == r"\\.\pipe\ce-test-pipe"


def test_environment_state_file_precedes_temp_discovery(tmp_path, monkeypatch):
    path = _state_file(tmp_path)
    monkeypatch.setenv("CLI_ANYTHING_CE_STATE_FILE", str(path))

    assert ce_backend.candidate_state_files() == [path.resolve()]


@pytest.mark.skipif(os.name != "nt", reason="Win32 process handle check")
def test_is_process_alive_uses_full_width_windows_handle():
    assert ce_backend.is_process_alive(os.getpid()) is True
    assert ce_backend.is_process_alive(0) is False


def test_resolve_session_rejects_stale_explicit_state(tmp_path, monkeypatch):
    path = _state_file(tmp_path)
    monkeypatch.setattr(ce_backend, "is_process_alive", lambda _pid: False)

    with pytest.raises(ce_backend.CEBridgeError, match="Stale"):
        ce_backend.resolve_session(path)


def test_client_rejects_structured_bridge_error(tmp_path, monkeypatch):
    class FakeDuplexPipe:
        def __init__(self, incoming):
            self.incoming = io.BytesIO(incoming)
            self.written = b""

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def write(self, data):
            self.written += data
            return len(data)

        def read(self, size=-1):
            return self.incoming.read(size)

    state = ce_backend.SessionState(
        path=tmp_path / "state.json",
        protocol=ce_backend.PROTOCOL_VERSION,
        pipe="test",
        token="a" * 64,
        ce_pid=10,
        started_at=1,
    )
    response = json.dumps({"ok": False, "error": "denied", "type": "BridgeError"}).encode()
    stream = FakeDuplexPipe(struct.pack("<I", len(response)) + response)
    monkeypatch.setattr(ce_backend, "resolve_session", lambda _path: state)
    monkeypatch.setattr(ce_backend, "_wait_named_pipe", lambda _path, _timeout: None)
    monkeypatch.setattr("builtins.open", lambda *_args, **_kwargs: stream)

    with pytest.raises(ce_backend.CEBridgeResponseError, match="denied"):
        ce_backend.CheatEngineClient().request("session.status")

    assert b"session.status" in stream.written


def test_client_retries_pipe_open_before_sending(tmp_path, monkeypatch):
    class FakeDuplexPipe:
        def __init__(self, incoming):
            self.incoming = io.BytesIO(incoming)
            self.written = b""

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def write(self, data):
            self.written += data
            return len(data)

        def read(self, size=-1):
            return self.incoming.read(size)

    state = ce_backend.SessionState(tmp_path / "state.json", ce_backend.PROTOCOL_VERSION, "test", "a" * 64, 10, 1)
    response = json.dumps({"ok": True, "data": {"ready": True}}).encode()
    stream = FakeDuplexPipe(struct.pack("<I", len(response)) + response)
    attempts = {"count": 0}

    def fake_open(*_args, **_kwargs):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise OSError(231, "pipe busy")
        return stream

    monkeypatch.setattr(ce_backend, "resolve_session", lambda _path: state)
    monkeypatch.setattr(ce_backend, "_wait_named_pipe", lambda _path, _timeout: None)
    monkeypatch.setattr(ce_backend.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr("builtins.open", fake_open)

    result = ce_backend.CheatEngineClient(timeout=1).request("session.status")

    assert result["data"]["ready"] is True
    assert attempts["count"] == 2
    assert stream.written.count(b"session.status") == 1
