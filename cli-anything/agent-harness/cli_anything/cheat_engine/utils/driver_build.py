from __future__ import annotations

import json
import locale
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


class DriverBuildError(RuntimeError):
    pass


def _last_json_object(output: str) -> dict[str, Any]:
    starts = [index for index, character in enumerate(output) if character == "{"]
    for start in reversed(starts):
        try:
            payload = json.loads(output[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    raise DriverBuildError("DBK build did not return a JSON result")


def build_dbk64(
    source_root: Path,
    *,
    wdk_root: Path,
    vc_tools_root: Path,
    windows_sdk_root: Path,
    output_directory: Path | None = None,
    target_platform_version: str = "10.0.26100.0",
    timeout: float = 300.0,
) -> dict[str, Any]:
    if os.name != "nt":
        raise DriverBuildError("DBK64 can only be built on Windows")

    source_root = source_root.resolve()
    wdk_root = wdk_root.resolve()
    vc_tools_root = vc_tools_root.resolve()
    windows_sdk_root = windows_sdk_root.resolve()
    output_directory = (
        output_directory.resolve()
        if output_directory is not None
        else source_root.parent / ".runtime" / "dbk-ai-x64"
    )
    script = source_root / "DBKKernel" / "build-ai-wdm-x64.ps1"

    required = {
        "source root": source_root,
        "AI WDM build script": script,
        "WDK root": wdk_root,
        "MSVC tools root": vc_tools_root,
        "Windows SDK root": windows_sdk_root,
    }
    for description, path in required.items():
        if not path.exists():
            raise FileNotFoundError(f"{description} not found: {path}")

    powershell = shutil.which("pwsh.exe") or shutil.which("powershell.exe")
    if not powershell:
        raise DriverBuildError("PowerShell was not found")

    command = [
        powershell,
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        "-WdkRoot",
        str(wdk_root),
        "-VcToolsRoot",
        str(vc_tools_root),
        "-WindowsSdkRoot",
        str(windows_sdk_root),
        "-OutputDirectory",
        str(output_directory),
        "-TargetPlatformVersion",
        target_platform_version,
    ]

    try:
        completed = subprocess.run(
            command,
            cwd=source_root,
            capture_output=True,
            text=True,
            encoding=locale.getpreferredencoding(False),
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise DriverBuildError(f"DBK64 build timed out after {timeout:g} seconds") from exc

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        if len(detail) > 4000:
            detail = detail[-4000:]
        raise DriverBuildError(
            f"DBK64 build failed with exit code {completed.returncode}"
            + (f": {detail}" if detail else "")
        )

    result = _last_json_object(completed.stdout)
    artifact = Path(str(result.get("Path", ""))).resolve()
    if not artifact.is_file():
        raise DriverBuildError(f"DBK64 build reported a missing artifact: {artifact}")

    return {
        "path": str(artifact),
        "size": int(result["Size"]),
        "sha256": str(result["Sha256"]),
        "signed": bool(result["Signed"]),
        "signature_status": str(result.get("SignatureStatus", "NotSigned")),
        "machine": str(result.get("Machine", "x64")),
        "pe_magic": str(result.get("PeMagic", "PE32+")),
        "subsystem": str(result.get("Subsystem", "Native")),
        "entry_point_rva": str(result.get("EntryPointRva", "")),
        "dll_characteristics": str(result.get("DllCharacteristics", "")),
        "force_integrity": bool(result.get("ForceIntegrity", False)),
        "target": str(result["Target"]),
        "target_platform_version": str(result["TargetPlatformVersion"]),
        "loaded": False,
    }
