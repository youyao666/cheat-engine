---
name: cli-anything-cheat-engine
description: Operate a running Cheat Engine instance through a structured local CLI for process inspection, memory analysis, scanning, and debugging
version: 0.4.0
command: cli-anything-cheat-engine
install: pip install -e cli-anything/agent-harness
requires:
  - Cheat Engine built from this source tree
  - click>=8.0
  - prompt-toolkit>=3.0
categories:
  - debugging
  - reverse-engineering
  - windows
---

# Cheat Engine CLI Skill

Use this CLI for authorized, structured reverse-engineering workflows against a running Cheat Engine instance.

## Setup

```powershell
cd cli-anything\agent-harness
python -m pip install -e .
powershell -File bridge\install_bridge.ps1 -CheatEngineDir "C:\path\to\Cheat Engine"
```

Restart Cheat Engine after installing the autorun bridge. The bridge creates a per-process named pipe and a token-bearing state file in the user's temporary directory.

## Quick Commands

```powershell
ce-ai --json session info
ce-ai --json --state-file F:\runtime\ce-source.json app start "F:\path\Cheat Engine\bin\cheatengine-x86_64.exe"
ce-ai --json process list
ce-ai --json process open 1234
ce-ai --json module list
ce-ai --json symbol resolve "target.exe+1000"
ce-ai --json lua exec "return getOpenedProcessID(), getAddressSafe('target.exe')"
ce-ai --json lua exec --file F:\scripts\full-ce-workflow.lua
ce-ai --json memory regions --readable-only
ce-ai --json memory read 0x7ff600001000 64
ce-ai --json memory disassemble 0x7ff600001000 --count 20
ce-ai --json scan aob "48 8B ?? ?? 89"
ce-ai --json scan new
ce-ai --json scan first --option exact --type dword --value 100
ce-ai --json scan next --option increased
ce-ai --json scan results --offset 0 --limit 100
ce-ai --json scan reset
ce-ai --json debug attach --interface dbvm
ce-ai --json debug breakpoint set 0x7ff600001000 --trigger execute
ce-ai --json debug status
ce-ai --json debug continue
ce-ai --json debug detach
ce-ai --json driver health
ce-ai --json driver status
ce-ai --json driver list
ce-ai --json --state-file F:\runtime\ce-source.json driver device-status
ce-ai --json --state-file F:\runtime\ce-source.json driver connect CEDRIVER73
ce-ai --json --state-file F:\runtime\ce-source.json dbvm status
ce-ai --json --state-file F:\runtime\ce-source.json dbvm start --yes
ce-ai --json driver build "F:\aicoding\ce1\cheat-engine" --wdk-root "F:\tools\wdk-nuget\10.0.26100.6584\extracted\c" --vc-tools-root "D:\VSBuildTools\VC\Tools\MSVC\14.44.35207"
```

## Agent Usage Notes

- Use `--json` for automated calls.
- `app start` launches the exact executable path in `CEAI_AGENT_MODE`, validates the adjacent autorun bridge, waits for the named-pipe session, and reuses an already-running matching state file.
- Open a process before module, symbol, memory, scan, or debugger commands.
- Prefer `memory read`, `memory disassemble`, and `scan aob` before mutating state.
- Value scans use the native CE session: `scan new`, `scan first`, `scan next`, `scan status`, `scan results`, and `scan reset`. The session is bound to the opened PID; changing target requires a new scan.
- `memory write` requires `--yes` and accepts at most 64 KiB of hexadecimal bytes.
- UDL status commands do not require a CE bridge session. The API defaults to `http://127.0.0.1:8765`; use `UDL_API_URL` and optional `UDL_API_TOKEN` to override it.
- `driver load` and `driver unload` require `--yes`. Pass the exact `.sys` path or service name returned by UDL; do not guess either value.
- `driver build` runs the source-tree AI WDM build in a separate output directory and returns PE/signature metadata; it never loads or installs the resulting unsigned driver.
- `driver start-api <udl.exe> --yes` starts UDL with `UDL_AUTO_HTTP=1`, requests elevation if needed, and waits for `/health`. It does nothing if the API is already online.
- `driver status/list` describe UDL; `driver device-status` describes the DBK handle inside source CE. A successful UDL load does not imply CE is connected.
- `driver connect <device-basename>` only opens an already exposed DBK device, verifies version, and performs initialization. It never creates/starts a service or unloads a driver.
- `app start --dbk-device <device-basename>` passes an explicit device basename to Agent CE through `CEAI_DBK_DEVICE`; the default is `CEDRIVER73`.
- `lua exec` runs unrestricted source in CE's global Lua VM. It has no content filter or `--yes` gate and can call all registered CE/Lua/native APIs available in that process.
- Treat the state-file token as administrator credentials. `lua exec` can perform file/process operations, load native code, call DBK/DBVM APIs, and bypass structured-command limits.
- DBK and DBVM are separate layers. Use `dbvm status` to check DBK, CPU virtualization, EPT, `vmdisk.img`, and the current DBVM version without changing host state.
- `dbvm start --yes` is a host-level transition that launches CE's adjacent `vmdisk.img` on all processors. It requires explicit authorization; never retry a failed start blindly, and run `dbvm status` immediately afterward.
- Auxiliary CE features exposed through Lua still require their separate runtime binaries, such as Speedhack, VEH, Mono/.NET, Java, and TCC components.
- `--interface dbvm` requires a supported 64-bit Windows host with DBVM running.
- During a successful DBVM debugger session, matching process memory reads, writes, and region queries use the debugger's captured CR3 and fall back to CE's configured backend on failure.
- Run `debug detach` when the debugging workflow is complete.
