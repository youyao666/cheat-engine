from __future__ import annotations

import ctypes
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


DEFAULT_UDL_API_URL = "http://127.0.0.1:8765"
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class UDLClientError(RuntimeError):
    pass


class UDLConnectionError(UDLClientError):
    pass


class UDLAPIError(UDLClientError):
    def __init__(self, message: str, status: int | None = None, payload: dict[str, Any] | None = None):
        super().__init__(message)
        self.status = status
        self.payload = payload


def _decode_response(raw: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UDLAPIError("UDL API returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise UDLAPIError("UDL API returned a non-object JSON response")
    return payload


class UDLClient:
    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        timeout: float = 30.0,
    ):
        configured_url = base_url or os.getenv("UDL_API_URL") or DEFAULT_UDL_API_URL
        self.base_url = configured_url.rstrip("/")
        self.token = token if token is not None else os.getenv("UDL_API_TOKEN")
        self.timeout = timeout

        parsed = urlsplit(self.base_url)
        if parsed.scheme != "http" or parsed.hostname not in _LOOPBACK_HOSTS:
            raise ValueError("UDL API URL must use HTTP on the local loopback interface")
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("UDL API URL must not contain a path, query, or fragment")

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        encoded = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Accept": "application/json"}
        if encoded is not None:
            headers["Content-Type"] = "application/json; charset=utf-8"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        request = Request(self.base_url + path, data=encoded, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = _decode_response(response.read())
                status = response.status
        except HTTPError as exc:
            try:
                payload = _decode_response(exc.read())
            except UDLAPIError:
                payload = None
            message = payload.get("error") if payload else str(exc)
            raise UDLAPIError(message, status=exc.code, payload=payload) from exc
        except (URLError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise UDLConnectionError(f"UDL API unavailable at {self.base_url}: {reason}") from exc

        if payload.get("ok") is False:
            raise UDLAPIError(
                str(payload.get("error") or "UDL API request failed"),
                status=status,
                payload=payload,
            )
        return payload

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def status(self) -> dict[str, Any]:
        return self._request("GET", "/api/status")

    def drivers(self) -> dict[str, Any]:
        return self._request("GET", "/api/drivers")

    def load(self, path: str | os.PathLike[str]) -> dict[str, Any]:
        return self._request("POST", "/api/load", {"path": str(path)})

    def unload(self, service_name: str) -> dict[str, Any]:
        return self._request("POST", "/api/unload", {"service_name": service_name})


def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def _launcher_environment(api_url: str, token: str | None) -> dict[str, str]:
    parsed = urlsplit(api_url)
    port = parsed.port or 80
    environment = os.environ.copy()
    environment["UDL_AUTO_HTTP"] = "1"
    environment["UDL_API_PORT"] = str(port)
    if token:
        environment["UDL_API_TOKEN"] = token
    else:
        environment.pop("UDL_API_TOKEN", None)
    return environment


def launch_udl_api(
    executable: str | os.PathLike[str],
    api_url: str,
    token: str | None = None,
    elevate: bool = True,
) -> dict[str, Any]:
    if os.name != "nt":
        raise UDLClientError("UDL can only be started on Windows")

    executable_path = Path(executable).expanduser().resolve()
    if not executable_path.is_file():
        raise FileNotFoundError(f"UDL executable not found: {executable_path}")

    environment = _launcher_environment(api_url, token)
    if _is_admin() or not elevate:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
        process = subprocess.Popen(
            [str(executable_path)],
            cwd=str(executable_path.parent),
            env=environment,
            startupinfo=startupinfo,
        )
        return {
            "started": True,
            "pid": process.pid,
            "elevation_requested": False,
            "executable": str(executable_path),
        }

    shell_execute = ctypes.windll.shell32.ShellExecuteW
    shell_execute.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_int]
    shell_execute.restype = ctypes.c_void_p

    previous = {name: os.environ.get(name) for name in ("UDL_AUTO_HTTP", "UDL_API_PORT", "UDL_API_TOKEN")}
    try:
        for name in previous:
            if name in environment:
                os.environ[name] = environment[name]
            else:
                os.environ.pop(name, None)
        result = shell_execute(None, "runas", str(executable_path), None, str(executable_path.parent), 0)
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    result_code = int(result or 0)
    if result_code <= 32:
        raise UDLClientError(f"Unable to start UDL with elevation (ShellExecute error {result_code})")
    return {
        "started": True,
        "pid": None,
        "elevation_requested": True,
        "executable": str(executable_path),
    }


def wait_for_health(client: UDLClient, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while True:
        try:
            return client.health()
        except UDLClientError as exc:
            last_error = exc
        if time.monotonic() >= deadline:
            raise UDLConnectionError(f"UDL API did not become ready within {timeout:g} seconds") from last_error
        time.sleep(0.2)
