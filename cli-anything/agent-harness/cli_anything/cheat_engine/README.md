# cli-anything-cheat-engine

`cli-anything-cheat-engine` controls a real running Cheat Engine instance through a local, token-authenticated autorun bridge. It also exposes the local UDL HTTP service for explicit driver lifecycle operations. It is designed for AI agents and scripts that need structured process, memory, scanner, symbol, disassembly, debugger, and authorized driver-development operations.

## Install

```powershell
pip install -e .
powershell -File bridge\install_bridge.ps1 -CheatEngineDir "C:\path\to\Cheat Engine"
```

Restart Cheat Engine after installing the bridge.

## Examples

```powershell
cli-anything-cheat-engine --json session info
ce-ai --json --state-file F:\runtime\ce-source.json app start "F:\path\Cheat Engine\bin\cheatengine-x86_64.exe"
cli-anything-cheat-engine --json process list
cli-anything-cheat-engine --json process open 1234
cli-anything-cheat-engine --json module list
ce-ai --json lua exec "return getOpenedProcessID(), getAddressSafe('kernel32.dll')"
ce-ai --json lua exec --file F:\scripts\full-ce-workflow.lua
cli-anything-cheat-engine --json memory read 0x7ff600001000 64
cli-anything-cheat-engine --json scan aob "48 8B ?? ?? 89"
ce-ai --json scan new
ce-ai --json scan first --option exact --type dword --value 100
ce-ai --json scan next --option increased
ce-ai --json scan results --offset 0 --limit 100
ce-ai --json scan reset
cli-anything-cheat-engine --json debug attach --interface dbvm
cli-anything-cheat-engine --json debug breakpoint set 0x7ff600001234
cli-anything-cheat-engine --json driver health
cli-anything-cheat-engine --json driver status
cli-anything-cheat-engine --json driver list
ce-ai --json --state-file F:\runtime\ce-source.json driver device-status
ce-ai --json --state-file F:\runtime\ce-source.json driver connect CEDRIVER73
ce-ai --json --state-file F:\runtime\ce-source.json dbvm status
ce-ai --json --state-file F:\runtime\ce-source.json dbvm start --yes
ce-ai --json driver build "F:\aicoding\ce1\cheat-engine" `
  --wdk-root "F:\tools\wdk-nuget\10.0.26100.6584\extracted\c" `
  --vc-tools-root "D:\VSBuildTools\VC\Tools\MSVC\14.44.35207" `
  --output "F:\aicoding\ce1\.runtime\dbk-ai-x64"
```

Memory writes require explicit confirmation:

```powershell
cli-anything-cheat-engine --json memory write 0x12345678 "90 90" --yes
cli-anything-cheat-engine --json driver load "C:\drivers\dbk64.sys" --yes
cli-anything-cheat-engine --json driver unload DBK64 --yes
```

The UDL client defaults to `http://127.0.0.1:8765`. Override it with `UDL_API_URL`; set `UDL_API_TOKEN` when the service requires Bearer authentication. Remote UDL URLs are rejected.

To let the Agent start the local UDL GUI with its HTTP service enabled:

```powershell
ce-ai --json driver start-api "F:\path\to\udl.exe" --yes
```

This sets `UDL_AUTO_HTTP=1`, passes the configured API port and token, requests administrator elevation when necessary, and waits for `/health`. If the API is already online, the command returns its health without starting another process.

UDL and CE device state are separate. `driver status/list` reports what UDL knows; `driver device-status` reports whether the running source CE has opened a DBK device. After UDL loads the exact DBK artifact, connect it without restarting CE:

```powershell
ce-ai --json --state-file F:\runtime\ce-source.json driver connect CEDRIVER73
```

`driver connect` only opens `\\.\CEDRIVER73`, checks `IOCTL_CE_GETVERSION`, and performs the DBK initialization handshake. It never creates or starts a Windows service. Use `--dbk-device <basename>` with `app start` or `CEAI_DBK_DEVICE` when the UDL-created device uses a different, explicitly reported basename; do not guess a service name.

DBK and DBVM are separate layers. A connected DBK driver provides the kernel transport, but does not mean the CPU is running under DBVM. Check all DBVM prerequisites without changing host state:

```powershell
ce-ai --json --state-file F:\runtime\ce-source.json dbvm status
```

`dbvm start --yes` asks the running source CE to launch its adjacent `vmdisk.img` on all processors through CE's existing `LaunchDBVM(-1)` path. The command checks the connected DBK driver, CPU virtualization capability, EPT, image presence, and current DBVM state again inside CE. This is a host-level transition and can destabilize or crash the machine if the firmware, kernel, or another hypervisor conflicts. Run it only with explicit authorization, never retry a failed launch blindly, and verify `running`, `version`, `free_pages`, and `free_bytes` with `dbvm status` immediately afterward.

`lua exec` runs unrestricted source in CE's global Lua VM. It can call CE's registered APIs for Cheat Tables, address lists, scanners, Auto Assembler, UI, plugins, DBK, DBVM, and auxiliary components, and it can also use Lua file/process/native-code facilities. Inline source and UTF-8 script files are accepted without content filtering or a `--yes` confirmation. Returned values are serialized with their Lua types; tables are recursively snapshotted.

The structured value-scan commands keep a native CE scan session across calls. Use `scan first --option unknown` for an initial unknown-value scan, then `scan next --option changed|unchanged|increased|decreased|increased-by|decreased-by` as the target changes. `scan results` is paginated and capped at 4096 rows per call. Open the target process before `scan new`; changing the CE target invalidates the session until `scan new` is run again.

This means the token-bearing state file is equivalent to administrator-level arbitrary code execution in the source CE process. The structured commands retain their normal validation, but `lua exec` can bypass those command-specific limits by calling CE APIs directly. Auxiliary CE features such as Speedhack, VEH, Mono/.NET, and Java still require their separately built runtime binaries.

Use only on software you own or are authorized to analyze.
