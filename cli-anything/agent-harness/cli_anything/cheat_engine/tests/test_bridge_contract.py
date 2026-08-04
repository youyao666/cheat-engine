from __future__ import annotations

import re
from pathlib import Path


HARNESS_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = Path(__file__).resolve().parents[5]
BRIDGE = HARNESS_ROOT / "bridge" / "ceai_bridge.lua"
NEW_KERNEL_HANDLER = REPO_ROOT / "Cheat Engine" / "NewKernelHandler.pas"
DBVM_DEBUGGER = REPO_ROOT / "Cheat Engine" / "dbvmdebuggerinterface.pas"
LUA_HANDLER = REPO_ROOT / "Cheat Engine" / "LuaHandler.pas"
PLUGIN_EXPORTS = REPO_ROOT / "Cheat Engine" / "pluginexports.pas"
CE_FUNC_PROC = REPO_ROOT / "Cheat Engine" / "CEFuncProc.pas"


EXPECTED_METHODS = {
    "session.status",
    "driver.device-status",
    "driver.connect",
    "dbvm.status",
    "dbvm.start",
    "process.list",
    "process.open",
    "process.info",
    "process.pause",
    "process.resume",
    "module.list",
    "symbol.resolve",
    "lua.exec",
    "memory.regions",
    "memory.read",
    "memory.write",
    "memory.disassemble",
    "scan.aob",
    "scan.new",
    "scan.first",
    "scan.next",
    "scan.status",
    "scan.results",
    "scan.reset",
    "debug.attach",
    "debug.status",
    "debug.detach",
    "debug.breakpoint.list",
    "debug.breakpoint.set",
    "debug.breakpoint.remove",
    "debug.continue",
}


def test_bridge_has_literal_method_allowlist_and_security_limits():
    source = BRIDGE.read_text(encoding="utf-8")
    methods = set(re.findall(r"handlers\['([^']+)'\]", source))

    assert methods == EXPECTED_METHODS
    assert "local MAX_FRAME = 1024 * 1024" in source
    assert "local MAX_WRITE = 64 * 1024" in source
    assert "constant_time_equal" in source
    assert "CEAI_BRIDGE_TOKEN" in source
    assert "local function token_part()" in source
    assert "type(generateGUIDString) == 'function'" in source
    assert "math.randomseed(seed)" in source


def test_bridge_exposes_authenticated_arbitrary_lua_execution():
    source = BRIDGE.read_text(encoding="utf-8")

    assert "handlers['lua.exec']" in source
    assert "load(source, chunk_name, 't', _G)" in source
    assert "table.pack(pcall(chunk))" in source
    assert "snapshot_lua_value" in source
    assert "dispatch_ok, dispatch_result = pcall(dispatch, method, params)" in source
    assert "if dispatch_ok ~= true then error(dispatch_result or 'Synchronized dispatch failed') end" in source


def test_bridge_owns_a_persistent_paginated_value_scan_session():
    source = BRIDGE.read_text(encoding="utf-8")

    assert "CEAI_SCAN_MEMSCAN = createMemScan()" in source
    assert "CEAI_SCAN_MEMSCAN.firstScan" in source
    assert "CEAI_SCAN_MEMSCAN.nextScan" in source
    assert "CEAI_SCAN_MEMSCAN.waitTillDone()" in source
    assert "CEAI_SCAN_FOUNDLIST = createFoundList(CEAI_SCAN_MEMSCAN)" in source
    assert "local MAX_SCAN_RESULTS = 4096" in source
    assert "Scan belongs to process %d, current process is %d" in source


def test_pascal_exposes_guid_generation_and_dbvm_interface_four():
    lua_source = LUA_HANDLER.read_text(encoding="utf-8")
    plugin_source = PLUGIN_EXPORTS.read_text(encoding="utf-8")

    assert "lua_generateGUIDString" in lua_source
    assert "generateGUIDString" in lua_source
    assert "CurrentDebuggerInterface is TDBVMDebugInterface" in lua_source
    assert "4: formSettings.cbUseDBVMDebugger.checked:=true" in plugin_source
    assert "lua_ceai_getDBVMStatus" in lua_source
    assert "lua_ceai_startDBVM" in lua_source
    assert "LaunchDBVM(-1)" in lua_source


def test_new_kernel_handler_routes_matching_dbvm_context():
    source = NEW_KERNEL_HANDLER.read_text(encoding="utf-8")

    for marker in (
        "ActivateDBVMDebugMemoryContext",
        "DeactivateDBVMDebugMemoryContext",
        "ClearDBVMDebugMemoryContext",
        "GetDBVMDebugMemoryContext",
        "dbvmDebugMemoryContextCS",
        "ReadProcessMemoryCR3(cr3",
        "WriteProcessMemoryCR3(cr3",
        "VirtualQueryExCR3(cr3",
        "GetDBVMDebugMemoryDiagnostics",
        "dbvmDebugMemoryReadCR3Success",
        "dbvmDebugMemoryQueryFallback",
    ):
        assert marker in source
    assert "dbvmDebugMemoryProcessHandle=hProcess" in source


def test_dbvm_debugger_owns_context_lifecycle_and_restores_force_flag():
    source = DBVM_DEBUGGER.read_text(encoding="utf-8")

    assert "ActivateDBVMDebugMemoryContext(attachedProcessHandle, processCR3)" in source
    assert "DeactivateDBVMDebugMemoryContext(attachedProcessHandle, processCR3)" in source
    assert "finally\n    forceCR3VirtualQueryEx:=oldforce;" in source.replace("\r\n", "\n")
    assert "ClearDBVMDebugMemoryContext;" in CE_FUNC_PROC.read_text(encoding="utf-8")


def test_bridge_reports_observed_dbvm_memory_backend():
    bridge_source = BRIDGE.read_text(encoding="utf-8")
    lua_source = LUA_HANDLER.read_text(encoding="utf-8")

    assert "getDBVMDebugMemoryDiagnostics" in lua_source
    assert "memory_backend_name" in bridge_source
    assert "last_read_backend = memory_backend_name" in bridge_source
    assert "query_cr3_success = raw.query_cr3_success or 0" in bridge_source
    assert bridge_source.count("dbvm_memory = dbvm_memory_diagnostics()") >= 5
