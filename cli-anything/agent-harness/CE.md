# Cheat Engine Agent Harness

## Goal

Expose Cheat Engine's real process, memory, scanner, disassembler, symbol, and debugger engines through a stable CLI designed for AI agents. The harness does not automate GUI coordinates and does not reimplement Cheat Engine behavior in Python.

## Architecture

```text
AI / shell
    |
    v
cli-anything-cheat-engine --json ...
    |
    | length-prefixed local named-pipe request
    v
ceai_bridge.lua inside the running Cheat Engine process
    |
    | structured methods plus unrestricted lua.exec
    v
Cheat Engine Lua API -> native CE process/memory/debugger implementation
```

Cheat Engine owns the live session. Each CLI invocation discovers the bridge state file, connects for one request, receives one JSON response, and disconnects. The bridge recreates its named pipe for the next invocation.

## Security Model

- The bridge uses an unguessable pipe name and a 256-bit token made from two native GUIDs.
- The state file is written to the current user's temporary directory.
- Requests are capped at 1 MiB and must use protocol `CEAI1`.
- Structured operations use explicit methods. `lua.exec` is an intentional unrestricted escape hatch that runs source in CE's global Lua VM and can invoke CE APIs, Lua libraries, native extensions, file/process operations, and any capability available to the elevated CE process.
- Memory reads are capped at 1 MiB per request.
- Memory writes are capped at 64 KiB and the CLI requires `--yes`.
- A stale state file is rejected when its CE process is no longer alive or its pipe cannot be reached.

## Initial Command Surface

- `session list|info`
- `process list|open|info|pause|resume`
- `module list`
- `symbol resolve`
- `lua exec SOURCE|--file SCRIPT`
- `memory regions|read|write|disassemble`
- `scan aob`
- `scan new|first|next|status|results|reset`
- `debug attach|status|detach|continue|step-into|step-over`
- `debug breakpoint list|set|remove`

All commands support `--json`. Running the command without a subcommand starts a stateful REPL.

Value scans are backed by CE's native `TMemScan` and `TFoundList` objects. `scan new` binds a session to the currently opened PID; `scan first` starts an exact, unknown, between, bigger, or smaller scan; `scan next` performs exact, changed, unchanged, increased/decreased, delta, and percentage filters; `scan results` pages addresses and values; `scan reset` destroys the session. The scan session lives inside CE, so multiple CLI calls form the same First/Next workflow.

## DBVM Memory Integration

When the DBVM debugger successfully attaches, it records the target process handle and CR3 in `NewKernelHandler`. Calls to `ReadProcessMemory`, `WriteProcessMemory`, and `VirtualQueryEx` use the CR3 implementation only when the incoming handle matches the active DBVM context. Destroying the DBVM debugger clears that context.

This avoids the previous mismatch where DBVM breakpoints operated below Windows while ordinary memory scanning still depended on Windows or DBK virtual-memory enumeration.

## Protocol

Request frame:

```text
uint32_le payload_length
"CEAI1\0TOKEN\0METHOD\0KEY\0VALUE\0..."
```

Response frame:

```text
uint32_le payload_length
UTF-8 JSON object
```

Successful responses use `{"ok": true, "data": ...}`. Failures use `{"ok": false, "error": "...", "type": "..."}`.

## Installation

The Python package is installed from this directory with `pip install -e .`. The bridge installer copies `bridge/ceai_bridge.lua` into the selected Cheat Engine `autorun` directory. Restart Cheat Engine after installing the bridge.

## Scope

This harness is intended for software you own or are authorized to analyze. Possession of the state-file token grants arbitrary code execution inside the running CE process through `lua.exec`; treat the state file and named-pipe endpoint as administrator credentials.
