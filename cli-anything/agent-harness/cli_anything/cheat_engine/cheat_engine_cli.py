from __future__ import annotations

import json
import re
import shlex
from pathlib import Path
from typing import Any

import click

from . import __version__
from .utils.ce_backend import CheatEngineClient, list_sessions, parse_int, session_dicts
from .utils.app_control import app_status, default_agent_state_file, start_cheat_engine
from .utils.driver_build import build_dbk64
from .utils.errors import error_payload
from .utils.output import output_json, output_rows
from .utils.udl_client import (
    DEFAULT_UDL_API_URL,
    UDLClient,
    UDLConnectionError,
    launch_udl_api,
    wait_for_health,
)


DEBUGGER_CODES = {"default": 0, "windows": 1, "veh": 2, "kernel": 3, "dbvm": 4}
BREAKPOINT_TRIGGERS = {"execute": 0, "access": 1, "write": 2}
CONTINUE_MODES = {"run": 0, "step-into": 1, "step-over": 2}


def _client(ctx: click.Context) -> CheatEngineClient:
    return CheatEngineClient(ctx.obj.get("state_file"), ctx.obj.get("timeout", 30.0))


def _udl_client(ctx: click.Context) -> UDLClient:
    return UDLClient(
        base_url=ctx.obj.get("udl_url"),
        token=ctx.obj.get("udl_token"),
        timeout=ctx.obj.get("timeout", 30.0),
    )


def _emit(ctx: click.Context, payload: dict[str, Any], rows: tuple[list[dict], list[str]] | None = None):
    if ctx.obj.get("json_mode") or rows is None:
        output_json(payload)
        return
    output_rows(rows[0], rows[1])


def _fail(ctx: click.Context, exc: Exception):
    payload = error_payload(exc, debug=ctx.obj.get("debug", False))
    if ctx.obj.get("json_mode"):
        output_json(payload)
        ctx.exit(1)
    raise click.ClickException(str(exc)) from exc


def _invoke(ctx: click.Context, method: str, **params: Any) -> dict[str, Any]:
    try:
        return _client(ctx).request(method, **params)
    except Exception as exc:
        return _fail(ctx, exc)


def _dbk_device_name(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", value):
        raise click.BadParameter(
            "must be a 1-64 character device basename using letters, digits, dot, underscore, or hyphen"
        )
    return value


def _udl_invoke(ctx: click.Context, operation: str, *args: Any) -> dict[str, Any]:
    try:
        return getattr(_udl_client(ctx), operation)(*args)
    except Exception as exc:
        return _fail(ctx, exc)


@click.group(invoke_without_command=True)
@click.option("--json", "json_mode", is_flag=True, help="Output one machine-readable JSON object.")
@click.option("--state-file", type=click.Path(dir_okay=False), default=None)
@click.option("--timeout", type=click.FloatRange(min=0.1), default=30.0, show_default=True)
@click.option("--debug", is_flag=True, help="Include tracebacks in JSON errors.")
@click.option(
    "--udl-url",
    envvar="UDL_API_URL",
    default=DEFAULT_UDL_API_URL,
    show_default=True,
    help="Local UDL HTTP API base URL.",
)
@click.option("--udl-token", envvar="UDL_API_TOKEN", default=None, help="Optional UDL bearer token.")
@click.version_option(version=__version__)
@click.pass_context
def cli(
    ctx: click.Context,
    json_mode: bool,
    state_file: str | None,
    timeout: float,
    debug: bool,
    udl_url: str,
    udl_token: str | None,
):
    """Operate a running Cheat Engine instance through its local agent bridge."""
    ctx.ensure_object(dict)
    ctx.obj.update(
        json_mode=json_mode,
        state_file=state_file,
        timeout=timeout,
        debug=debug,
        udl_url=udl_url,
        udl_token=udl_token,
    )
    if ctx.invoked_subcommand is None:
        ctx.invoke(repl)


@cli.group("session")
def session_group():
    """Discover and inspect Cheat Engine bridge sessions."""


@session_group.command("list")
@click.pass_context
def session_list(ctx: click.Context):
    sessions = session_dicts(list_sessions(ctx.obj.get("state_file")))
    payload = {"ok": True, "data": {"sessions": sessions, "count": len(sessions)}}
    _emit(ctx, payload, (sessions, ["ce_pid", "alive", "protocol", "state_file"]))


@session_group.command("info")
@click.pass_context
def session_info(ctx: click.Context):
    _emit(ctx, _invoke(ctx, "session.status"))


@cli.group("app")
def app_group():
    """Start and inspect the source-built Cheat Engine agent instance."""


@app_group.command("start")
@click.argument("executable", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--wait", "wait_seconds", type=click.FloatRange(min=0.1, max=120.0), default=30.0)
@click.option(
    "--dbk-device",
    callback=lambda _ctx, _param, value: _dbk_device_name(value) if value else None,
    default=None,
    help="Existing DBK device basename to connect during Agent startup.",
)
@click.pass_context
def app_start(ctx: click.Context, executable: Path, wait_seconds: float, dbk_device: str | None):
    try:
        state_file = ctx.obj.get("state_file") or str(default_agent_state_file(executable))
        payload = start_cheat_engine(
            executable,
            state_file=state_file,
            wait_seconds=wait_seconds,
            dbk_device=dbk_device,
        )
        _emit(ctx, {"ok": True, "data": payload})
    except Exception as exc:
        _fail(ctx, exc)


@app_group.command("status")
@click.option("--executable", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=None)
@click.pass_context
def app_show_status(ctx: click.Context, executable: Path | None):
    state_file = ctx.obj.get("state_file")
    if not state_file:
        if executable is None:
            raise click.UsageError("app status requires --state-file or --executable")
        state_file = str(default_agent_state_file(executable))
    _emit(ctx, {"ok": True, "data": app_status(state_file)})


@cli.group("driver")
def driver_group():
    """Inspect UDL and explicitly load or unload local drivers."""


@driver_group.command("health")
@click.pass_context
def driver_health(ctx: click.Context):
    _emit(ctx, _udl_invoke(ctx, "health"))


@driver_group.command("status")
@click.pass_context
def driver_status(ctx: click.Context):
    _emit(ctx, _udl_invoke(ctx, "status"))


@driver_group.command("list")
@click.pass_context
def driver_list(ctx: click.Context):
    payload = _udl_invoke(ctx, "drivers")
    rows = payload.get("drivers", [])
    _emit(ctx, payload, (rows, ["name", "state", "path"]))


@driver_group.command("device-status")
@click.pass_context
def driver_device_status(ctx: click.Context):
    """Inspect the DBK device connection inside the running source CE."""
    _emit(ctx, _invoke(ctx, "driver.device-status"))


@driver_group.command("connect")
@click.argument("device", default="CEDRIVER73", callback=lambda _ctx, _param, value: _dbk_device_name(value))
@click.pass_context
def driver_connect(ctx: click.Context, device: str):
    """Connect source CE to an already loaded DBK device; never load a driver."""
    _emit(ctx, _invoke(ctx, "driver.connect", device=device))


@cli.group("dbvm")
def dbvm_group():
    """Inspect and explicitly start Cheat Engine's DBVM hypervisor."""


@dbvm_group.command("status")
@click.pass_context
def dbvm_status(ctx: click.Context):
    """Inspect DBVM capability, image, driver, and running state."""
    _emit(ctx, _invoke(ctx, "dbvm.status"))


@dbvm_group.command("start")
@click.option("--yes", is_flag=True, help="Confirm entering VMX root operation on this host.")
@click.pass_context
def dbvm_start(ctx: click.Context, yes: bool):
    """Start DBVM on all available CPU cores."""
    if not yes:
        raise click.UsageError("dbvm start requires --yes")
    _emit(ctx, _invoke(ctx, "dbvm.start"))


@driver_group.command("build")
@click.argument("source_root", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option(
    "--wdk-root",
    envvar="CEAI_WDK_ROOT",
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="NuGet WDK content root containing Include and Lib.",
)
@click.option(
    "--vc-tools-root",
    envvar="CEAI_VC_TOOLS_ROOT",
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="MSVC version root containing bin, include, and lib.",
)
@click.option(
    "--windows-sdk-root",
    envvar="CEAI_WINDOWS_SDK_ROOT",
    default=r"C:\Program Files (x86)\Windows Kits\10",
    show_default=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
@click.option(
    "--output",
    "output_directory",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Separate build directory; defaults beside the source checkout under .runtime.",
)
@click.option("--target-platform-version", default="10.0.26100.0", show_default=True)
@click.option(
    "--build-timeout",
    type=click.FloatRange(min=1.0, max=3600.0),
    default=300.0,
    show_default=True,
)
@click.pass_context
def driver_build(
    ctx: click.Context,
    source_root: Path,
    wdk_root: Path,
    vc_tools_root: Path,
    windows_sdk_root: Path,
    output_directory: Path | None,
    target_platform_version: str,
    build_timeout: float,
):
    """Build an unsigned source DBK64 driver without loading it."""
    try:
        payload = build_dbk64(
            source_root,
            wdk_root=wdk_root,
            vc_tools_root=vc_tools_root,
            windows_sdk_root=windows_sdk_root,
            output_directory=output_directory,
            target_platform_version=target_platform_version,
            timeout=build_timeout,
        )
        _emit(ctx, {"ok": True, "data": payload})
    except Exception as exc:
        _fail(ctx, exc)


@driver_group.command("load")
@click.argument("path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--yes", is_flag=True, help="Confirm loading a kernel driver.")
@click.pass_context
def driver_load(ctx: click.Context, path: Path, yes: bool):
    if not yes:
        raise click.UsageError("driver load requires --yes")
    _emit(ctx, _udl_invoke(ctx, "load", str(path.resolve())))


@driver_group.command("unload")
@click.argument("service_name")
@click.option("--yes", is_flag=True, help="Confirm unloading a kernel driver.")
@click.pass_context
def driver_unload(ctx: click.Context, service_name: str, yes: bool):
    if not yes:
        raise click.UsageError("driver unload requires --yes")
    _emit(ctx, _udl_invoke(ctx, "unload", service_name))


@driver_group.command("start-api")
@click.argument("executable", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--yes", is_flag=True, help="Confirm starting UDL and requesting elevation if needed.")
@click.option("--wait", "wait_seconds", type=click.FloatRange(min=0.1, max=120.0), default=15.0)
@click.option("--no-elevate", is_flag=True, help="Start without requesting administrator elevation.")
@click.pass_context
def driver_start_api(
    ctx: click.Context,
    executable: Path,
    yes: bool,
    wait_seconds: float,
    no_elevate: bool,
):
    client = _udl_client(ctx)
    try:
        health = client.health()
        _emit(ctx, {"ok": True, "data": {"already_running": True, "health": health}})
        return
    except UDLConnectionError:
        pass
    except Exception as exc:
        _fail(ctx, exc)
        return

    if not yes:
        raise click.UsageError("driver start-api requires --yes when the API is offline")

    try:
        launch = launch_udl_api(
            executable,
            api_url=client.base_url,
            token=client.token,
            elevate=not no_elevate,
        )
        health = wait_for_health(client, wait_seconds)
    except Exception as exc:
        _fail(ctx, exc)
        return
    _emit(ctx, {"ok": True, "data": {"already_running": False, "launch": launch, "health": health}})


@cli.group("process")
def process_group():
    """List, open, pause, and resume target processes."""


@process_group.command("list")
@click.pass_context
def process_list(ctx: click.Context):
    payload = _invoke(ctx, "process.list")
    rows = payload.get("data", {}).get("processes", [])
    _emit(ctx, payload, (rows, ["pid", "name"]))


@process_group.command("open")
@click.argument("target")
@click.pass_context
def process_open(ctx: click.Context, target: str):
    try:
        params = {"pid": parse_int(target)}
    except ValueError:
        params = {"name": target}
    _emit(ctx, _invoke(ctx, "process.open", **params))


@process_group.command("info")
@click.pass_context
def process_info(ctx: click.Context):
    _emit(ctx, _invoke(ctx, "process.info"))


@process_group.command("pause")
@click.pass_context
def process_pause(ctx: click.Context):
    _emit(ctx, _invoke(ctx, "process.pause"))


@process_group.command("resume")
@click.pass_context
def process_resume(ctx: click.Context):
    _emit(ctx, _invoke(ctx, "process.resume"))


@cli.group("module")
def module_group():
    """Inspect modules in the opened process."""


@module_group.command("list")
@click.pass_context
def module_list(ctx: click.Context):
    payload = _invoke(ctx, "module.list")
    rows = payload.get("data", {}).get("modules", [])
    _emit(ctx, payload, (rows, ["address", "name", "is_64bit", "path"]))


@cli.group("symbol")
def symbol_group():
    """Resolve symbols and CE address expressions."""


@symbol_group.command("resolve")
@click.argument("expression")
@click.pass_context
def symbol_resolve(ctx: click.Context, expression: str):
    _emit(ctx, _invoke(ctx, "symbol.resolve", expression=expression))


@cli.group("lua")
def lua_group():
    """Execute arbitrary source in Cheat Engine's global Lua VM."""


@lua_group.command("exec")
@click.argument("source", required=False)
@click.option(
    "--file",
    "source_file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Read Lua source from a UTF-8 file instead of the inline argument.",
)
@click.option("--chunk-name", default=None, help="Lua chunk name used in errors and debug output.")
@click.pass_context
def lua_exec(ctx: click.Context, source: str | None, source_file: Path | None, chunk_name: str | None):
    """Run unrestricted CE Lua with the privileges of the source CE process."""
    if (source is None) == (source_file is None):
        raise click.UsageError("provide exactly one of SOURCE or --file")
    if source_file is not None:
        try:
            source = source_file.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise click.ClickException(f"Unable to read Lua source file: {exc}") from exc
        chunk_name = chunk_name or f"@{source_file.resolve()}"
    else:
        chunk_name = chunk_name or "=(ce-ai)"
    _emit(ctx, _invoke(ctx, "lua.exec", source=source, chunk_name=chunk_name))


@cli.group("memory")
def memory_group():
    """Enumerate, read, write, and disassemble process memory."""


@memory_group.command("regions")
@click.option("--start", default="0x0", callback=lambda _c, _p, v: parse_int(v))
@click.option("--stop", default="0x7fffffffffff", callback=lambda _c, _p, v: parse_int(v))
@click.option("--limit", type=click.IntRange(min=1, max=65536), default=4096)
@click.option("--readable-only", is_flag=True)
@click.pass_context
def memory_regions(ctx: click.Context, start: int, stop: int, limit: int, readable_only: bool):
    payload = _invoke(
        ctx,
        "memory.regions",
        start=start,
        stop=stop,
        limit=limit,
        readable_only=readable_only,
    )
    rows = payload.get("data", {}).get("regions", [])
    _emit(ctx, payload, (rows, ["base", "size", "state", "protect", "type"]))


@memory_group.command("read")
@click.argument("address", callback=lambda _c, _p, v: parse_int(v))
@click.argument("size", type=click.IntRange(min=1, max=1024 * 1024))
@click.pass_context
def memory_read(ctx: click.Context, address: int, size: int):
    _emit(ctx, _invoke(ctx, "memory.read", address=address, size=size))


@memory_group.command("write")
@click.argument("address", callback=lambda _c, _p, v: parse_int(v))
@click.argument("hex_bytes")
@click.option("--yes", is_flag=True, help="Confirm mutation of target process memory.")
@click.pass_context
def memory_write(ctx: click.Context, address: int, hex_bytes: str, yes: bool):
    normalized = "".join(hex_bytes.split()).lower()
    if not yes:
        raise click.UsageError("memory write requires --yes")
    if not normalized or len(normalized) % 2:
        raise click.UsageError("hex_bytes must contain an even number of hexadecimal digits")
    try:
        bytes.fromhex(normalized)
    except ValueError as exc:
        raise click.UsageError("hex_bytes contains non-hexadecimal characters") from exc
    if len(normalized) // 2 > 65536:
        raise click.UsageError("memory write is limited to 65536 bytes")
    _emit(ctx, _invoke(ctx, "memory.write", address=address, hex=normalized))


@memory_group.command("disassemble")
@click.argument("address", callback=lambda _c, _p, v: parse_int(v))
@click.option("--count", type=click.IntRange(min=1, max=256), default=16)
@click.pass_context
def memory_disassemble(ctx: click.Context, address: int, count: int):
    _emit(ctx, _invoke(ctx, "memory.disassemble", address=address, count=count))


@cli.group("scan")
def scan_group():
    """Run Cheat Engine scanners."""


@scan_group.command("aob")
@click.argument("pattern")
@click.option("--protection", default="", help="CE protection filter, for example +X-W-C.")
@click.option("--limit", type=click.IntRange(min=1, max=65536), default=1024)
@click.pass_context
def scan_aob(ctx: click.Context, pattern: str, protection: str, limit: int):
    _emit(ctx, _invoke(ctx, "scan.aob", pattern=pattern, protection=protection, limit=limit))


SCAN_OPTIONS = [
    "unknown",
    "exact",
    "between",
    "bigger",
    "smaller",
    "increased",
    "increased-by",
    "decreased",
    "decreased-by",
    "changed",
    "unchanged",
    "forgot",
]
FIRST_SCAN_OPTIONS = ["unknown", "exact", "between", "bigger", "smaller"]
NEXT_SCAN_OPTIONS = [option for option in SCAN_OPTIONS if option != "unknown"]
SCAN_TYPES = [
    "byte",
    "word",
    "dword",
    "qword",
    "float",
    "double",
    "string",
    "unicode-string",
    "byte-array",
    "binary",
    "all",
    "auto-assembler",
    "pointer",
    "custom",
    "grouped",
    "byte-arrays",
    "code-page-string",
]
SCAN_ROUNDING = ["rounded", "extreme-rounded", "truncated"]
SCAN_ALIGNMENT = ["not-aligned", "aligned", "last-digits"]


@scan_group.command("new")
@click.pass_context
def scan_new(ctx: click.Context):
    """Create or replace the persistent CE memory-scan session."""
    _emit(ctx, _invoke(ctx, "scan.new"))


@scan_group.command("first")
@click.option("--option", type=click.Choice(FIRST_SCAN_OPTIONS), default="exact", show_default=True)
@click.option("--type", "variable_type", type=click.Choice(SCAN_TYPES), default="dword", show_default=True)
@click.option("--rounding", type=click.Choice(SCAN_ROUNDING), default="rounded", show_default=True)
@click.option("--value", default="", help="Primary value; required for exact/between scans.")
@click.option("--second-value", default="", help="Upper value for between scans.")
@click.option("--start", default="0", help="Start address or CE symbol expression.")
@click.option("--stop", default="0x7fffffffffff", help="Stop address or CE symbol expression.")
@click.option("--protection", default="", help="CE protection filter such as +X-W-C.")
@click.option("--alignment", type=click.Choice(SCAN_ALIGNMENT), default="not-aligned", show_default=True)
@click.option("--alignment-param", default="", help="Alignment parameter when required by the selected mode.")
@click.option("--hex", "hex_input", is_flag=True, help="Interpret scan values as hexadecimal input.")
@click.option("--binary-as-decimal", is_flag=True, help="Display binary scan input/results as decimal.")
@click.option("--unicode", "unicode_input", is_flag=True)
@click.option("--case-sensitive", is_flag=True)
@click.pass_context
def scan_first(
    ctx: click.Context,
    option: str,
    variable_type: str,
    rounding: str,
    value: str,
    second_value: str,
    start: str,
    stop: str,
    protection: str,
    alignment: str,
    alignment_param: str,
    hex_input: bool,
    binary_as_decimal: bool,
    unicode_input: bool,
    case_sensitive: bool,
):
    """Run CE's first value scan in the persistent scan session."""
    _emit(
        ctx,
        _invoke(
            ctx,
            "scan.first",
            option=option,
            type=variable_type,
            rounding=rounding,
            value=value,
            second_value=second_value,
            start=start,
            stop=stop,
            protection=protection,
            alignment=alignment,
            alignment_param=alignment_param,
            hex=hex_input,
            binary_as_decimal=binary_as_decimal,
            unicode=unicode_input,
            case_sensitive=case_sensitive,
        ),
    )


@scan_group.command("next")
@click.option("--option", type=click.Choice(NEXT_SCAN_OPTIONS), default="exact", show_default=True)
@click.option("--rounding", type=click.Choice(SCAN_ROUNDING), default="rounded", show_default=True)
@click.option("--value", default="")
@click.option("--second-value", default="")
@click.option("--hex", "hex_input", is_flag=True)
@click.option("--binary-as-decimal", is_flag=True)
@click.option("--unicode", "unicode_input", is_flag=True)
@click.option("--case-sensitive", is_flag=True)
@click.option("--percentage", is_flag=True)
@click.option("--saved-name", default="", help="Optional CE saved-scan result name.")
@click.pass_context
def scan_next(
    ctx: click.Context,
    option: str,
    rounding: str,
    value: str,
    second_value: str,
    hex_input: bool,
    binary_as_decimal: bool,
    unicode_input: bool,
    case_sensitive: bool,
    percentage: bool,
    saved_name: str,
):
    """Run CE's next/changed-value scan against the previous results."""
    _emit(
        ctx,
        _invoke(
            ctx,
            "scan.next",
            option=option,
            rounding=rounding,
            value=value,
            second_value=second_value,
            hex=hex_input,
            binary_as_decimal=binary_as_decimal,
            unicode=unicode_input,
            case_sensitive=case_sensitive,
            percentage=percentage,
            saved_name=saved_name,
        ),
    )


@scan_group.command("status")
@click.pass_context
def scan_status(ctx: click.Context):
    """Inspect the persistent CE scan session and progress."""
    _emit(ctx, _invoke(ctx, "scan.status"))


@scan_group.command("results")
@click.option("--offset", type=click.IntRange(min=0), default=0, show_default=True)
@click.option("--limit", type=click.IntRange(min=1, max=4096), default=256, show_default=True)
@click.pass_context
def scan_results(ctx: click.Context, offset: int, limit: int):
    """Read a page of addresses and values from the current scan."""
    payload = _invoke(ctx, "scan.results", offset=offset, limit=limit)
    rows = payload.get("data", {}).get("results", [])
    _emit(ctx, payload, (rows, ["index", "address", "value"]))


@scan_group.command("reset")
@click.pass_context
def scan_reset(ctx: click.Context):
    """Destroy the current CE scan and found-list session."""
    _emit(ctx, _invoke(ctx, "scan.reset"))


@cli.group("debug")
def debug_group():
    """Attach debuggers and control breakpoints."""


@debug_group.command("attach")
@click.option("--interface", "interface_name", type=click.Choice(list(DEBUGGER_CODES)), default="default")
@click.pass_context
def debug_attach(ctx: click.Context, interface_name: str):
    _emit(
        ctx,
        _invoke(ctx, "debug.attach", interface=DEBUGGER_CODES[interface_name], name=interface_name),
    )


@debug_group.command("status")
@click.pass_context
def debug_status(ctx: click.Context):
    _emit(ctx, _invoke(ctx, "debug.status"))


@debug_group.command("detach")
@click.pass_context
def debug_detach(ctx: click.Context):
    _emit(ctx, _invoke(ctx, "debug.detach"))


def _continue(ctx: click.Context, mode: str):
    _emit(ctx, _invoke(ctx, "debug.continue", mode=CONTINUE_MODES[mode], name=mode))


@debug_group.command("continue")
@click.pass_context
def debug_continue(ctx: click.Context):
    _continue(ctx, "run")


@debug_group.command("step-into")
@click.pass_context
def debug_step_into(ctx: click.Context):
    _continue(ctx, "step-into")


@debug_group.command("step-over")
@click.pass_context
def debug_step_over(ctx: click.Context):
    _continue(ctx, "step-over")


@debug_group.group("breakpoint")
def breakpoint_group():
    """List, set, and remove breakpoints."""


@breakpoint_group.command("list")
@click.pass_context
def breakpoint_list(ctx: click.Context):
    _emit(ctx, _invoke(ctx, "debug.breakpoint.list"))


@breakpoint_group.command("set")
@click.argument("address", callback=lambda _c, _p, v: parse_int(v))
@click.option("--size", type=click.IntRange(min=1, max=4096), default=1)
@click.option("--trigger", type=click.Choice(list(BREAKPOINT_TRIGGERS)), default="execute")
@click.pass_context
def breakpoint_set(ctx: click.Context, address: int, size: int, trigger: str):
    _emit(
        ctx,
        _invoke(
            ctx,
            "debug.breakpoint.set",
            address=address,
            size=size,
            trigger=BREAKPOINT_TRIGGERS[trigger],
            trigger_name=trigger,
        ),
    )


@breakpoint_group.command("remove")
@click.argument("address", callback=lambda _c, _p, v: parse_int(v))
@click.pass_context
def breakpoint_remove(ctx: click.Context, address: int):
    _emit(ctx, _invoke(ctx, "debug.breakpoint.remove", address=address))


@cli.command("repl")
@click.pass_context
def repl(ctx: click.Context):
    """Start an interactive command session."""
    from .utils.repl_skin import ReplSkin

    skin = ReplSkin("cli-anything-cheat-engine", __version__)
    skin.print_banner()
    prompt = skin.create_prompt_session()
    while True:
        try:
            line = skin.get_input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        if line.lower() in {"exit", "quit"}:
            break
        if line.lower() == "help":
            click.echo(cli.get_help(ctx))
            continue

        args = []
        if ctx.obj.get("json_mode"):
            args.append("--json")
        if ctx.obj.get("state_file"):
            args.extend(["--state-file", ctx.obj["state_file"]])
        args.extend(["--timeout", str(ctx.obj.get("timeout", 30.0))])
        if ctx.obj.get("debug"):
            args.append("--debug")
        if ctx.obj.get("udl_url"):
            args.extend(["--udl-url", ctx.obj["udl_url"]])
        if ctx.obj.get("udl_token"):
            args.extend(["--udl-token", ctx.obj["udl_token"]])
        try:
            cli.main(args=args + shlex.split(line), standalone_mode=False, obj={})
        except click.ClickException as exc:
            exc.show()
        except click.exceptions.Exit:
            pass
    skin.print_goodbye()


def main():
    cli(obj={})


if __name__ == "__main__":
    main()
