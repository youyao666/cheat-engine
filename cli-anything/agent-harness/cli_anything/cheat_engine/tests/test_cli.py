from __future__ import annotations

import json

from click.testing import CliRunner

from cli_anything.cheat_engine import cheat_engine_cli
from cli_anything.cheat_engine.utils.udl_client import UDLConnectionError


class FakeClient:
    def __init__(self):
        self.calls = []

    def request(self, method, **params):
        self.calls.append((method, params))
        return {"ok": True, "data": {"method": method, **params}}


def invoke_with_client(monkeypatch, args):
    client = FakeClient()
    monkeypatch.setattr(cheat_engine_cli, "_client", lambda _ctx: client)
    result = CliRunner().invoke(cheat_engine_cli.cli, args)
    return result, client


def test_root_and_group_help():
    runner = CliRunner()
    assert runner.invoke(cheat_engine_cli.cli, ["--help"]).exit_code == 0
    for group in (
        "session",
        "app",
        "driver",
        "dbvm",
        "process",
        "module",
        "symbol",
        "lua",
        "memory",
        "scan",
        "debug",
    ):
        result = runner.invoke(cheat_engine_cli.cli, [group, "--help"])
        assert result.exit_code == 0, result.output


def test_process_open_parses_hex_pid(monkeypatch):
    result, client = invoke_with_client(monkeypatch, ["--json", "process", "open", "0x2a"])

    assert result.exit_code == 0
    assert client.calls == [("process.open", {"pid": 42})]


def test_process_open_preserves_name(monkeypatch):
    result, client = invoke_with_client(monkeypatch, ["--json", "process", "open", "target.exe"])

    assert result.exit_code == 0
    assert client.calls == [("process.open", {"name": "target.exe"})]


def test_memory_read_forwards_decimal_address(monkeypatch):
    result, client = invoke_with_client(monkeypatch, ["--json", "memory", "read", "0x1000", "32"])

    assert result.exit_code == 0
    assert client.calls == [("memory.read", {"address": 0x1000, "size": 32})]


def test_lua_exec_forwards_unrestricted_inline_source(monkeypatch):
    source = "return getOpenedProcessID(), getAddressSafe('kernel32.dll')"
    result, client = invoke_with_client(monkeypatch, ["--json", "lua", "exec", source])

    assert result.exit_code == 0
    assert client.calls == [("lua.exec", {"source": source, "chunk_name": "=(ce-ai)"})]


def test_lua_exec_reads_utf8_file(monkeypatch, tmp_path):
    script = tmp_path / "agent.lua"
    script.write_text("return {pid=getOpenedProcessID()}", encoding="utf-8")
    result, client = invoke_with_client(monkeypatch, ["--json", "lua", "exec", "--file", str(script)])

    assert result.exit_code == 0
    assert client.calls == [
        ("lua.exec", {"source": "return {pid=getOpenedProcessID()}", "chunk_name": f"@{script.resolve()}"})
    ]


def test_lua_exec_requires_exactly_one_source(monkeypatch, tmp_path):
    script = tmp_path / "agent.lua"
    script.write_text("return true", encoding="utf-8")
    runner = CliRunner()

    missing = runner.invoke(cheat_engine_cli.cli, ["lua", "exec"])
    duplicate = runner.invoke(
        cheat_engine_cli.cli, ["lua", "exec", "return true", "--file", str(script)]
    )

    assert missing.exit_code == 2
    assert duplicate.exit_code == 2


def test_memory_regions_forwards_filters(monkeypatch):
    result, client = invoke_with_client(
        monkeypatch,
        [
            "--json",
            "memory",
            "regions",
            "--start",
            "0x1000",
            "--stop",
            "0x9000",
            "--limit",
            "12",
            "--readable-only",
        ],
    )

    assert result.exit_code == 0
    assert client.calls == [
        (
            "memory.regions",
            {"start": 0x1000, "stop": 0x9000, "limit": 12, "readable_only": True},
        )
    ]


def test_memory_write_requires_confirmation():
    result = CliRunner().invoke(cheat_engine_cli.cli, ["memory", "write", "0x1000", "90"])

    assert result.exit_code == 2
    assert "requires --yes" in result.output


def test_memory_write_validates_hex():
    runner = CliRunner()
    odd = runner.invoke(cheat_engine_cli.cli, ["memory", "write", "0x1000", "9", "--yes"])
    invalid = runner.invoke(cheat_engine_cli.cli, ["memory", "write", "0x1000", "zz", "--yes"])

    assert odd.exit_code == 2
    assert invalid.exit_code == 2


def test_memory_write_normalizes_and_forwards(monkeypatch):
    result, client = invoke_with_client(
        monkeypatch, ["--json", "memory", "write", "0x1000", "AA bb 01", "--yes"]
    )

    assert result.exit_code == 0
    assert client.calls == [("memory.write", {"address": 0x1000, "hex": "aabb01"})]


def test_dbvm_debugger_maps_to_interface_four(monkeypatch):
    result, client = invoke_with_client(monkeypatch, ["--json", "debug", "attach", "--interface", "dbvm"])

    assert result.exit_code == 0
    assert client.calls == [("debug.attach", {"interface": 4, "name": "dbvm"})]


def test_app_start_uses_explicit_state_file(monkeypatch, tmp_path):
    executable = tmp_path / "cheatengine-x86_64.exe"
    executable.write_bytes(b"placeholder")
    state = tmp_path / "ce-state.json"
    captured = {}

    def fake_start(path, state_file, wait_seconds, dbk_device):
        captured.update(path=path, state_file=state_file, wait_seconds=wait_seconds, dbk_device=dbk_device)
        return {"pid": 123, "state_file": state_file}

    monkeypatch.setattr(cheat_engine_cli, "start_cheat_engine", fake_start)
    result = CliRunner().invoke(
        cheat_engine_cli.cli,
        ["--json", "--state-file", str(state), "app", "start", str(executable), "--wait", "2"],
    )

    assert result.exit_code == 0
    assert captured == {"path": executable, "state_file": str(state), "wait_seconds": 2.0, "dbk_device": None}


def test_driver_device_commands_use_ce_bridge(monkeypatch):
    result, client = invoke_with_client(monkeypatch, ["--json", "driver", "device-status"])
    assert result.exit_code == 0
    assert client.calls == [("driver.device-status", {})]

    result, client = invoke_with_client(monkeypatch, ["--json", "driver", "connect", "CEDRIVER73"])
    assert result.exit_code == 0
    assert client.calls == [("driver.connect", {"device": "CEDRIVER73"})]


def test_driver_connect_rejects_path_like_name():
    result = CliRunner().invoke(cheat_engine_cli.cli, ["driver", "connect", r"\\.\CEDRIVER73"])
    assert result.exit_code == 2
    assert "device basename" in result.output


def test_dbvm_status_and_start_require_confirmation(monkeypatch):
    status, client = invoke_with_client(monkeypatch, ["--json", "dbvm", "status"])
    refused = CliRunner().invoke(cheat_engine_cli.cli, ["dbvm", "start"])
    started, client2 = invoke_with_client(monkeypatch, ["--json", "dbvm", "start", "--yes"])

    assert status.exit_code == 0
    assert client.calls == [("dbvm.status", {})]
    assert refused.exit_code == 2
    assert "requires --yes" in refused.output
    assert started.exit_code == 0
    assert client2.calls == [("dbvm.start", {})]


def test_breakpoint_set_maps_write_trigger(monkeypatch):
    result, client = invoke_with_client(
        monkeypatch,
        ["--json", "debug", "breakpoint", "set", "0x401000", "--size", "4", "--trigger", "write"],
    )

    assert result.exit_code == 0
    assert client.calls == [
        (
            "debug.breakpoint.set",
            {"address": 0x401000, "size": 4, "trigger": 2, "trigger_name": "write"},
        )
    ]


def test_scan_new_and_status_use_persistent_session_methods(monkeypatch):
    created, client = invoke_with_client(monkeypatch, ["--json", "scan", "new"])
    status, client2 = invoke_with_client(monkeypatch, ["--json", "scan", "status"])

    assert created.exit_code == 0
    assert client.calls == [("scan.new", {})]
    assert status.exit_code == 0
    assert client2.calls == [("scan.status", {})]


def test_scan_first_forwards_ce_value_scan_parameters(monkeypatch):
    result, client = invoke_with_client(
        monkeypatch,
        [
            "--json",
            "scan",
            "first",
            "--option",
            "between",
            "--type",
            "qword",
            "--rounding",
            "truncated",
            "--value",
            "100",
            "--second-value",
            "200",
            "--start",
            "target.exe",
            "--stop",
            "target.exe+10000",
            "--protection",
            "+W-X-C",
            "--alignment",
            "aligned",
            "--alignment-param",
            "8",
            "--hex",
            "--binary-as-decimal",
            "--unicode",
            "--case-sensitive",
        ],
    )

    assert result.exit_code == 0
    assert client.calls == [
        (
            "scan.first",
            {
                "option": "between",
                "type": "qword",
                "rounding": "truncated",
                "value": "100",
                "second_value": "200",
                "start": "target.exe",
                "stop": "target.exe+10000",
                "protection": "+W-X-C",
                "alignment": "aligned",
                "alignment_param": "8",
                "hex": True,
                "binary_as_decimal": True,
                "unicode": True,
                "case_sensitive": True,
            },
        )
    ]


def test_scan_next_forwards_changed_value_parameters(monkeypatch):
    result, client = invoke_with_client(
        monkeypatch,
        [
            "--json",
            "scan",
            "next",
            "--option",
            "increased-by",
            "--value",
            "25",
            "--percentage",
            "--saved-name",
            "baseline",
        ],
    )

    assert result.exit_code == 0
    assert client.calls == [
        (
            "scan.next",
            {
                "option": "increased-by",
                "rounding": "rounded",
                "value": "25",
                "second_value": "",
                "hex": False,
                "binary_as_decimal": False,
                "unicode": False,
                "case_sensitive": False,
                "percentage": True,
                "saved_name": "baseline",
            },
        )
    ]


def test_scan_results_and_reset_forward_pagination(monkeypatch):
    results, client = invoke_with_client(
        monkeypatch, ["--json", "scan", "results", "--offset", "20", "--limit", "50"]
    )
    reset, client2 = invoke_with_client(monkeypatch, ["--json", "scan", "reset"])

    assert results.exit_code == 0
    assert client.calls == [("scan.results", {"offset": 20, "limit": 50})]
    assert reset.exit_code == 0
    assert client2.calls == [("scan.reset", {})]


def test_json_backend_error_is_structured(monkeypatch):
    class FailingClient:
        def request(self, _method, **_params):
            raise RuntimeError("bridge unavailable")

    monkeypatch.setattr(cheat_engine_cli, "_client", lambda _ctx: FailingClient())
    result = CliRunner().invoke(cheat_engine_cli.cli, ["--json", "process", "info"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["type"] == "RuntimeError"
    assert payload["error"] == "bridge unavailable"


class FakeUDLClient:
    base_url = "http://127.0.0.1:8765"
    token = None

    def __init__(self):
        self.calls = []

    def health(self):
        self.calls.append(("health", ()))
        return {"ok": True, "service": "udl-api"}

    def status(self):
        self.calls.append(("status", ()))
        return {"ok": True, "kudl_ready": True}

    def drivers(self):
        self.calls.append(("drivers", ()))
        return {"ok": True, "drivers": [{"name": "test", "state": "Running", "path": "x.sys"}]}

    def load(self, path):
        self.calls.append(("load", (path,)))
        return {"ok": True, "service_name": "test"}

    def unload(self, service_name):
        self.calls.append(("unload", (service_name,)))
        return {"ok": True, "service_name": service_name}


def invoke_with_udl(monkeypatch, args, client=None):
    client = client or FakeUDLClient()
    monkeypatch.setattr(cheat_engine_cli, "_udl_client", lambda _ctx: client)
    result = CliRunner().invoke(cheat_engine_cli.cli, args)
    return result, client


def test_driver_health_and_list_do_not_require_ce_session(monkeypatch):
    health, client = invoke_with_udl(monkeypatch, ["--json", "driver", "health"])
    listed, _ = invoke_with_udl(monkeypatch, ["--json", "driver", "list"], client)

    assert health.exit_code == 0
    assert listed.exit_code == 0
    assert client.calls == [("health", ()), ("drivers", ())]


def test_driver_build_forwards_tool_roots_without_loading(monkeypatch, tmp_path):
    source_root = tmp_path / "cheat-engine"
    wdk_root = tmp_path / "wdk"
    vc_tools_root = tmp_path / "msvc"
    sdk_root = tmp_path / "sdk"
    output = tmp_path / "out"
    for directory in (source_root, wdk_root, vc_tools_root, sdk_root):
        directory.mkdir()
    captured = {}

    def fake_build(source, **kwargs):
        captured.update(source=source, **kwargs)
        return {
            "path": str(output / "DBK64.sys"),
            "sha256": "00" * 32,
            "signed": False,
            "loaded": False,
        }

    monkeypatch.setattr(cheat_engine_cli, "build_dbk64", fake_build)
    result = CliRunner().invoke(
        cheat_engine_cli.cli,
        [
            "--json",
            "driver",
            "build",
            str(source_root),
            "--wdk-root",
            str(wdk_root),
            "--vc-tools-root",
            str(vc_tools_root),
            "--windows-sdk-root",
            str(sdk_root),
            "--output",
            str(output),
            "--build-timeout",
            "12",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured == {
        "source": source_root,
        "wdk_root": wdk_root,
        "vc_tools_root": vc_tools_root,
        "windows_sdk_root": sdk_root,
        "output_directory": output,
        "target_platform_version": "10.0.26100.0",
        "timeout": 12.0,
    }
    assert json.loads(result.output)["data"]["loaded"] is False


def test_driver_load_requires_confirmation_and_forwards_absolute_path(monkeypatch, tmp_path):
    driver = tmp_path / "sample.sys"
    driver.write_bytes(b"not a real driver")

    refused, _ = invoke_with_udl(monkeypatch, ["driver", "load", str(driver)])
    accepted, client = invoke_with_udl(
        monkeypatch, ["--json", "driver", "load", str(driver), "--yes"]
    )

    assert refused.exit_code == 2
    assert "requires --yes" in refused.output
    assert accepted.exit_code == 0
    assert client.calls == [("load", (str(driver.resolve()),))]


def test_driver_unload_requires_confirmation(monkeypatch):
    refused, _ = invoke_with_udl(monkeypatch, ["driver", "unload", "SampleService"])
    accepted, client = invoke_with_udl(
        monkeypatch, ["--json", "driver", "unload", "SampleService", "--yes"]
    )

    assert refused.exit_code == 2
    assert accepted.exit_code == 0
    assert client.calls == [("unload", ("SampleService",))]


def test_driver_start_api_reuses_online_service_without_confirmation(monkeypatch, tmp_path):
    executable = tmp_path / "udl.exe"
    executable.write_bytes(b"placeholder")
    client = FakeUDLClient()
    monkeypatch.setattr(
        cheat_engine_cli,
        "launch_udl_api",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not launch")),
    )

    result, _ = invoke_with_udl(
        monkeypatch, ["--json", "driver", "start-api", str(executable)], client
    )

    assert result.exit_code == 0
    assert json.loads(result.output)["data"]["already_running"] is True


def test_driver_start_api_sets_auto_http_and_waits(monkeypatch, tmp_path):
    executable = tmp_path / "udl.exe"
    executable.write_bytes(b"placeholder")

    class OfflineClient(FakeUDLClient):
        token = "secret"

        def health(self):
            raise UDLConnectionError("offline")

    client = OfflineClient()
    captured = {}

    def fake_launch(path, api_url, token, elevate):
        captured.update(path=path, api_url=api_url, token=token, elevate=elevate)
        return {"started": True, "pid": 123}

    monkeypatch.setattr(cheat_engine_cli, "launch_udl_api", fake_launch)
    monkeypatch.setattr(
        cheat_engine_cli,
        "wait_for_health",
        lambda current, timeout: {"ok": True, "timeout": timeout, "same_client": current is client},
    )

    result, _ = invoke_with_udl(
        monkeypatch,
        ["--json", "driver", "start-api", str(executable), "--yes", "--wait", "2"],
        client,
    )

    assert result.exit_code == 0
    assert captured == {
        "path": executable,
        "api_url": "http://127.0.0.1:8765",
        "token": "secret",
        "elevate": True,
    }
    assert json.loads(result.output)["data"]["health"]["same_client"] is True
