from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from .ce_backend import (
    CEBridgeError,
    CheatEngineClient,
    get_process_image_path,
    is_process_alive,
    list_sessions,
)


def default_agent_state_file(executable: Path) -> Path:
    resolved = str(executable.resolve()).casefold().encode("utf-8")
    suffix = hashlib.sha256(resolved).hexdigest()[:12]
    return Path(tempfile.gettempdir()) / f"cli-anything-cheat-engine-agent-{suffix}.json"


def _same_path(left: str | Path, right: str | Path) -> bool:
    return os.path.normcase(os.path.abspath(str(left))) == os.path.normcase(os.path.abspath(str(right)))


def app_status(state_file: str | Path) -> dict[str, Any]:
    sessions = list_sessions(str(state_file))
    if not sessions:
        return {"running": False, "state_file": str(Path(state_file).resolve())}
    state = sessions[0]
    alive = is_process_alive(state.ce_pid)
    return {
        "running": alive,
        "state_file": str(state.path),
        "ce_pid": state.ce_pid,
        "executable": get_process_image_path(state.ce_pid) if alive else None,
        "protocol": state.protocol,
        "started_at": state.started_at,
    }


def start_cheat_engine(
    executable: str | Path,
    *,
    state_file: str | Path | None = None,
    wait_seconds: float = 30.0,
    dbk_device: str | None = None,
) -> dict[str, Any]:
    if os.name != "nt":
        raise CEBridgeError("Cheat Engine app control is only supported on Windows")

    exe = Path(executable).expanduser().resolve()
    if not exe.is_file():
        raise CEBridgeError(f"Cheat Engine executable does not exist: {exe}")
    bridge = exe.parent / "autorun" / "ceai_bridge.lua"
    if not bridge.is_file():
        raise CEBridgeError(f"Cheat Engine AI bridge is not installed: {bridge}")

    state_path = Path(state_file).expanduser().resolve() if state_file else default_agent_state_file(exe)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    current = app_status(state_path)
    if current.get("running"):
        if not current.get("executable") or not _same_path(current["executable"], exe):
            raise CEBridgeError(
                f"State file belongs to a different running executable: {current.get('executable')}"
            )
        health = CheatEngineClient(str(state_path), timeout=wait_seconds).request("session.status")
        return {
            "already_running": True,
            "state_file": str(state_path),
            "bridge": str(bridge),
            "session": health.get("data", {}),
        }

    environment = os.environ.copy()
    environment["CEAI_AGENT_MODE"] = "1"
    environment["CLI_ANYTHING_CE_STATE_FILE"] = str(state_path)
    if dbk_device:
        environment["CEAI_DBK_DEVICE"] = dbk_device
    process = subprocess.Popen(
        [str(exe), "CEAI_AGENT_MODE"],
        cwd=str(exe.parent),
        env=environment,
        close_fds=True,
    )

    deadline = time.monotonic() + wait_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise CEBridgeError(f"Cheat Engine exited before bridge startup (exit code {process.returncode})")
        try:
            sessions = list_sessions(str(state_path))
            if sessions and sessions[0].ce_pid == process.pid and is_process_alive(process.pid):
                image = get_process_image_path(process.pid)
                if image and not _same_path(image, exe):
                    raise CEBridgeError(f"Started PID image path mismatch: {image}")
                health = CheatEngineClient(str(state_path), timeout=max(0.1, deadline - time.monotonic())).request(
                    "session.status"
                )
                return {
                    "already_running": False,
                    "pid": process.pid,
                    "executable": image or str(exe),
                    "state_file": str(state_path),
                    "bridge": str(bridge),
                    "session": health.get("data", {}),
                }
        except Exception as exc:
            last_error = exc
        time.sleep(0.1)

    detail = f": {last_error}" if last_error else ""
    raise CEBridgeError(f"Timed out waiting for Cheat Engine AI bridge{detail}")
