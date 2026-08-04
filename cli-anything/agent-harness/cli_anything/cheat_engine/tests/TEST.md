# TEST.md - Cheat Engine CLI Test Plan

## Test Inventory Plan

- `test_protocol.py`: request framing, response framing, state discovery, limits, and stale-session behavior, about 18 tests.
- `test_cli.py`: Click command shape, JSON output, argument validation, and backend invocation, about 20 tests.
- `test_bridge_contract.py`: bridge method names, required security checks, and Pascal/Lua integration markers, about 10 tests.
- `test_full_e2e.py`: optional real Cheat Engine bridge workflow on Windows, about 8 tests.

## Unit Test Plan

### `utils/ce_backend.py`

- Encode the `CEAI1` NUL-field request without accepting NULs in keys or values.
- Reject payloads larger than 1 MiB.
- Decode complete JSON responses and reject truncated, oversized, or non-object responses.
- Resolve an explicit state file before environment and auto-discovery paths.
- Ignore malformed and stale state files during auto-discovery.
- Select the newest reachable CE session.
- Produce clear errors when no bridge is available.

### `cheat_engine_cli.py`

- Root, group, and command `--help` output.
- `--json` success and structured error behavior.
- Integer parsing for decimal and hexadecimal addresses.
- Memory read and AOB scan parameter validation.
- Persistent native value-scan session commands: `scan new`, `scan first`, `scan next`, `scan status`, `scan results`, and `scan reset`.
- Memory write requires `--yes` and valid even-length hexadecimal bytes.
- Arbitrary inline and file-based Lua source is forwarded unchanged to `lua.exec`.
- Debugger name and breakpoint trigger mappings.
- Subcommands forward only documented backend method names.

### Bridge Contract

- Lua bridge contains protocol version, maximum frame size, token comparison, and literal structured methods.
- `lua.exec` compiles source against `_G`, executes it with protected error propagation, and snapshots multiple return values.
- Pascal exposes native GUID generation to Lua.
- Plugin debugger selection recognizes DBVM as interface 4.
- `NewKernelHandler` exposes activate/deactivate DBVM process-memory context functions.
- DBVM attach and destroy paths call the matching context lifecycle functions.

## E2E Test Plan

### Prerequisites

- Windows 10/11.
- A built Cheat Engine binary from this source tree.
- The bridge installed in that binary's `autorun` directory.
- Administrator privileges for DBK/DBVM-specific tests.
- Hardware and firmware configuration capable of running DBVM for DBVM tests.

### Workflows

#### `live_process_probe`

1. Start Cheat Engine with the bridge installed.
2. Run `session info`.
3. List processes and open a test helper process.
4. List modules, resolve a symbol, and read known memory.
5. Disassemble a known executable address.

Verify every response is valid JSON and contains stable documented keys.

#### `aob_scan_probe`

1. Start a controlled helper process containing a known byte pattern.
2. Open it through the CLI.
3. Run `scan aob` with a result limit.

Verify the known address appears and the result limit is enforced.

#### `value_scan_probe`

1. Open a controlled test process and place a known integer in a private page.
2. Run `scan new` and `scan first --option exact`.
3. Change selected values and run `scan next --option increased`, `increased-by`, and `unchanged`.
4. Read pages with `scan results`, then run `scan reset`.

Verify counts and addresses follow native CE First/Next Scan semantics and the session is bound to the opened PID.

#### `debugger_probe`

1. Open a controlled helper process.
2. Attach with the Windows or VEH debugger.
3. Set an execute breakpoint.
4. Inspect status, remove the breakpoint, and detach.

Verify debugger type, breakpoint list, and cleanup state.

#### `dbvm_memory_probe`

1. Start DBVM on supported hardware.
2. Open a controlled helper process.
3. Attach with `debug attach --interface dbvm`.
4. Enumerate regions and read a known user-mode address.
5. Compare returned bytes with the helper's expected value.
6. Detach and confirm the DBVM memory context is no longer active.

Verify region enumeration is non-empty and read operations report the DBVM CR3 backend.

## Output Validation

- JSON mode writes only one JSON object to stdout.
- Errors use non-zero exit codes and include `ok=false`, `error`, and `type`.
- Memory bytes are lowercase hexadecimal with an even length.
- Addresses are `0x`-prefixed strings to avoid JSON integer precision loss.
- Process and module lists are deterministic arrays, not maps with unstable ordering.

## Test Results

Automated verification on 2026-08-04:

- `python -m pytest -q`: 63 passed.
- `python -m compileall -q cli_anything\cheat_engine`: passed.
- `git -c core.whitespace=cr-at-eol diff --check`: passed.
- Canonical/runtime bridge SHA-256 hashes: identical.
- Canonical/packaged `SKILL.md` SHA-256 hashes: identical.
- Source CE bridge `0.4.0` live session, DBK connection, and DBVM status: passed.
- Native value scan E2E: exact 3 results → increased 2 → increased-by 25 gives 1 → unchanged keeps 1 → paginated results → reset.
- Scan test page was allocated only inside source CE, then released successfully; no external target process was modified.
