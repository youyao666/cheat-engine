-- Cheat Engine AI bridge. Authenticated clients may execute arbitrary CE Lua.

if CEAI_BRIDGE_STARTED then
  return
end
CEAI_BRIDGE_STARTED = true

local PROTOCOL = 'CEAI1'
local BRIDGE_VERSION = '0.4.0'
local MAX_FRAME = 1024 * 1024
local MAX_WRITE = 64 * 1024
local MAX_SCAN_RESULTS = 4096

local function json_escape(value)
  local replacements = {
    ['"'] = '\\"',
    ['\\'] = '\\\\',
    ['\b'] = '\\b',
    ['\f'] = '\\f',
    ['\n'] = '\\n',
    ['\r'] = '\\r',
    ['\t'] = '\\t',
  }
  return '"' .. value:gsub('[%z\1-\31\\"]', function(char)
    return replacements[char] or string.format('\\u%04x', string.byte(char))
  end) .. '"'
end

local function table_is_array(value)
  local count = 0
  local maximum = 0
  for key, _ in pairs(value) do
    if type(key) ~= 'number' or key < 1 or key % 1 ~= 0 then
      return false, 0
    end
    count = count + 1
    if key > maximum then maximum = key end
  end
  return count == maximum, maximum
end

local function json_encode(value, seen)
  local value_type = type(value)
  if value == nil then return 'null' end
  if value_type == 'boolean' then return value and 'true' or 'false' end
  if value_type == 'number' then
    if value ~= value or value == math.huge or value == -math.huge then return 'null' end
    return tostring(value)
  end
  if value_type == 'string' then return json_escape(value) end
  if value_type ~= 'table' then return json_escape(tostring(value)) end

  seen = seen or {}
  if seen[value] then error('JSON cycle detected') end
  seen[value] = true

  local is_array, maximum = table_is_array(value)
  local parts = {}
  if is_array then
    for index = 1, maximum do
      parts[#parts + 1] = json_encode(value[index], seen)
    end
    seen[value] = nil
    return '[' .. table.concat(parts, ',') .. ']'
  end

  local keys = {}
  for key, _ in pairs(value) do keys[#keys + 1] = tostring(key) end
  table.sort(keys)
  for _, key in ipairs(keys) do
    parts[#parts + 1] = json_escape(key) .. ':' .. json_encode(value[key], seen)
  end
  seen[value] = nil
  return '{' .. table.concat(parts, ',') .. '}'
end

local function constant_time_equal(left, right)
  if type(left) ~= 'string' or type(right) ~= 'string' or #left ~= #right then
    return false
  end
  local different = 0
  for index = 1, #left do
    if left:byte(index) ~= right:byte(index) then different = different + 1 end
  end
  return different == 0
end

local function split_nul(payload)
  local fields = {}
  local start = 1
  while true do
    local position = payload:find('\0', start, true)
    if not position then break end
    fields[#fields + 1] = payload:sub(start, position - 1)
    start = position + 1
  end
  return fields
end

local function parse_request(payload)
  local fields = split_nul(payload)
  if fields[1] ~= PROTOCOL then error('Unsupported protocol') end
  if not constant_time_equal(fields[2] or '', CEAI_BRIDGE_TOKEN) then error('Unauthorized client') end
  local method = fields[3]
  if not method or method == '' then error('Missing method') end

  local params = {}
  local index = 4
  while index <= #fields do
    local key = fields[index]
    local value = fields[index + 1]
    if not key or key == '' or value == nil then error('Malformed request parameters') end
    params[key] = value
    index = index + 2
  end
  return method, params
end

local function required(params, name)
  local value = params[name]
  if value == nil or value == '' then error('Missing parameter: ' .. name) end
  return value
end

local function integer_param(params, name, default)
  local value = params[name]
  if value == nil or value == '' then return default end
  local number = tonumber(value)
  if not number then error('Invalid integer parameter: ' .. name) end
  return math.tointeger(number) or number
end

local function boolean_param(params, name, default)
  local value = params[name]
  if value == nil or value == '' then return default end
  return value == '1' or value == 'true'
end

local function hex_address(value)
  return string.format('0x%X', value)
end

local function normalize_address_text(value)
  local text = tostring(value)
  if text:sub(1, 2):lower() == '0x' then return text:lower() end
  return '0x' .. text:lower()
end

local function bytes_to_hex(bytes)
  local parts = {}
  for index = 1, #bytes do parts[index] = string.format('%02x', bytes[index]) end
  return table.concat(parts)
end

local function hex_to_bytes(value)
  local compact = value:gsub('%s+', '')
  if #compact == 0 or #compact % 2 ~= 0 then error('Hex bytes must have even length') end
  if #compact / 2 > MAX_WRITE then error('Memory write exceeds 65536 bytes') end
  local result = {}
  for index = 1, #compact, 2 do
    local byte = tonumber(compact:sub(index, index + 1), 16)
    if not byte then error('Invalid hexadecimal byte string') end
    result[#result + 1] = byte
  end
  return result
end

local function debugger_name(code)
  local names = {[1] = 'windows', [2] = 'veh', [3] = 'kernel', [4] = 'dbvm', [5] = 'gdb'}
  return names[code] or 'none'
end

local function memory_backend_name(code)
  local names = {[1] = 'cr3', [2] = 'fallback'}
  return names[code] or 'none'
end

local function dbvm_memory_diagnostics()
  if type(getDBVMDebugMemoryDiagnostics) ~= 'function' then
    return {supported = false, active = false}
  end

  local raw = getDBVMDebugMemoryDiagnostics() or {}
  return {
    supported = true,
    active = raw.active == true,
    process_handle = hex_address(raw.process_handle or 0),
    cr3 = hex_address(raw.cr3 or 0),
    last_read_backend = memory_backend_name(raw.last_read_backend),
    last_write_backend = memory_backend_name(raw.last_write_backend),
    last_query_backend = memory_backend_name(raw.last_query_backend),
    read_cr3_attempts = raw.read_cr3_attempts or 0,
    read_cr3_success = raw.read_cr3_success or 0,
    read_fallback = raw.read_fallback or 0,
    write_cr3_attempts = raw.write_cr3_attempts or 0,
    write_cr3_success = raw.write_cr3_success or 0,
    write_fallback = raw.write_fallback or 0,
    query_cr3_attempts = raw.query_cr3_attempts or 0,
    query_cr3_success = raw.query_cr3_success or 0,
    query_fallback = raw.query_fallback or 0,
  }
end

local function breakpoint_addresses()
  local values = debug_getBreakpointList() or {}
  local result = {}
  for index = 1, #values do result[index] = hex_address(values[index]) end
  return result
end

local handlers = {}

local SCAN_OPTIONS = {
  unknown = 0,
  exact = 1,
  between = 2,
  bigger = 3,
  smaller = 4,
  increased = 5,
  ['increased-by'] = 6,
  decreased = 7,
  ['decreased-by'] = 8,
  changed = 9,
  unchanged = 10,
  forgot = 11,
}

local VARIABLE_TYPES = {
  byte = 0,
  word = 1,
  dword = 2,
  qword = 3,
  float = 4,
  double = 5,
  string = 6,
  ['unicode-string'] = 7,
  ['byte-array'] = 8,
  binary = 9,
  all = 10,
  ['auto-assembler'] = 11,
  pointer = 12,
  custom = 13,
  grouped = 14,
  ['byte-arrays'] = 15,
  ['code-page-string'] = 16,
}

local ROUNDING_TYPES = {rounded = 0, ['extreme-rounded'] = 1, truncated = 2}
local ALIGNMENT_TYPES = {['not-aligned'] = 0, aligned = 1, ['last-digits'] = 2}

local function scan_enum(map, params, name, default)
  local value = params[name]
  if value == nil or value == '' then return default end
  local numeric = tonumber(value)
  if numeric then
    numeric = math.tointeger(numeric) or numeric
    for _, mapped in pairs(map) do
      if mapped == numeric then return numeric end
    end
    error('Invalid scan ' .. name .. ': ' .. tostring(value))
  end
  local mapped = map[value:lower()]
  if mapped == nil then error('Invalid scan ' .. name .. ': ' .. tostring(value)) end
  return mapped
end

local function scan_string(params, name, default)
  local value = params[name]
  if value == nil then return default or '' end
  return tostring(value)
end

local function scan_state_active()
  return CEAI_SCAN_MEMSCAN ~= nil and CEAI_SCAN_PID ~= nil and CEAI_SCAN_PID ~= 0
end

local function scan_reset_state()
  if CEAI_SCAN_FOUNDLIST ~= nil then
    pcall(function() CEAI_SCAN_FOUNDLIST.deinitialize() end)
    pcall(function() CEAI_SCAN_FOUNDLIST.destroy() end)
    CEAI_SCAN_FOUNDLIST = nil
  end
  if CEAI_SCAN_MEMSCAN ~= nil then
    pcall(function() CEAI_SCAN_MEMSCAN.destroy() end)
    CEAI_SCAN_MEMSCAN = nil
  end
  CEAI_SCAN_PID = nil
  CEAI_SCAN_VARTYPE = nil
  CEAI_SCAN_TYPE_NAME = nil
  CEAI_SCAN_PHASE = nil
end

local function require_scan_state()
  if not scan_state_active() then error('No active scan; run scan new first') end
  local pid = getOpenedProcessID()
  if pid == 0 then error('No process is open in Cheat Engine') end
  if pid ~= CEAI_SCAN_PID then
    error(string.format('Scan belongs to process %d, current process is %d; run scan new', CEAI_SCAN_PID, pid))
  end
end

local function scan_progress()
  if CEAI_SCAN_MEMSCAN == nil then return {TotalAddressesToScan = 0, CurrentlyScanned = 0, ResultsFound = 0} end
  return CEAI_SCAN_MEMSCAN.getProgress() or {}
end

handlers['scan.new'] = function(_params)
  local pid = getOpenedProcessID()
  if pid == 0 then error('No process is open in Cheat Engine') end
  scan_reset_state()
  CEAI_SCAN_MEMSCAN = createMemScan()
  CEAI_SCAN_PID = pid
  CEAI_SCAN_PHASE = 'new'
  return {active = true, pid = pid, phase = CEAI_SCAN_PHASE, progress = scan_progress()}
end

handlers['scan.first'] = function(params)
  require_scan_state()
  if CEAI_SCAN_PHASE ~= 'new' then error('Scan already has results; run scan new before another first scan') end
  local option = scan_enum(SCAN_OPTIONS, params, 'option', SCAN_OPTIONS.exact)
  local vartype = scan_enum(VARIABLE_TYPES, params, 'type', VARIABLE_TYPES.dword)
  local rounding = scan_enum(ROUNDING_TYPES, params, 'rounding', ROUNDING_TYPES.rounded)
  local input1 = scan_string(params, 'value', '')
  local input2 = scan_string(params, 'second_value', '')
  local start_address = params.start or '0'
  local stop_address = params.stop or '0x7fffffffffff'
  local protection = scan_string(params, 'protection', '')
  local alignment = scan_enum(ALIGNMENT_TYPES, params, 'alignment', ALIGNMENT_TYPES['not-aligned'])
  local alignment_param = scan_string(params, 'alignment_param', '')
  local is_hex = boolean_param(params, 'hex', false)
  local is_binary_as_decimal = boolean_param(params, 'binary_as_decimal', false)
  local is_unicode = boolean_param(params, 'unicode', false)
  local is_case_sensitive = boolean_param(params, 'case_sensitive', false)
  if option > SCAN_OPTIONS.smaller then error('scan first option must be unknown, exact, between, bigger, or smaller') end
  if option ~= SCAN_OPTIONS.unknown and option ~= SCAN_OPTIONS.between and input1 == '' then error('scan first option requires value') end
  if option == SCAN_OPTIONS.between and (input1 == '' or input2 == '') then error('scan first between requires value and second_value') end
  CEAI_SCAN_MEMSCAN.firstScan(option, vartype, rounding, input1, input2, start_address, stop_address, protection, alignment, alignment_param, is_hex, is_binary_as_decimal, is_unicode, is_case_sensitive)
  CEAI_SCAN_MEMSCAN.waitTillDone()
  if CEAI_SCAN_FOUNDLIST ~= nil then pcall(function() CEAI_SCAN_FOUNDLIST.destroy() end) end
  CEAI_SCAN_FOUNDLIST = createFoundList(CEAI_SCAN_MEMSCAN)
  CEAI_SCAN_FOUNDLIST.initialize()
  CEAI_SCAN_VARTYPE = vartype
  CEAI_SCAN_TYPE_NAME = scan_string(params, 'type', 'dword')
  CEAI_SCAN_PHASE = 'first'
  return {active = true, pid = CEAI_SCAN_PID, phase = CEAI_SCAN_PHASE, option = scan_string(params, 'option', 'exact'), option_code = option, type = CEAI_SCAN_TYPE_NAME, type_code = vartype, count = CEAI_SCAN_FOUNDLIST.Count, progress = scan_progress()}
end

handlers['scan.next'] = function(params)
  require_scan_state()
  if CEAI_SCAN_FOUNDLIST == nil or CEAI_SCAN_PHASE == 'new' then error('Run scan first before scan next') end
  local option = scan_enum(SCAN_OPTIONS, params, 'option', SCAN_OPTIONS.exact)
  local rounding = scan_enum(ROUNDING_TYPES, params, 'rounding', ROUNDING_TYPES.rounded)
  local input1 = scan_string(params, 'value', '')
  local input2 = scan_string(params, 'second_value', '')
  local is_hex = boolean_param(params, 'hex', false)
  local is_binary_as_decimal = boolean_param(params, 'binary_as_decimal', false)
  local is_unicode = boolean_param(params, 'unicode', false)
  local is_case_sensitive = boolean_param(params, 'case_sensitive', false)
  local is_percentage = boolean_param(params, 'percentage', false)
  local saved_name = scan_string(params, 'saved_name', '')
  if option == SCAN_OPTIONS.unknown then error('scan next does not support unknown; use changed or unchanged') end
  if (option == SCAN_OPTIONS.exact or option == SCAN_OPTIONS.bigger or option == SCAN_OPTIONS.smaller or option == SCAN_OPTIONS['increased-by'] or option == SCAN_OPTIONS['decreased-by']) and input1 == '' then error('scan next option requires value') end
  if option == SCAN_OPTIONS.between and (input1 == '' or input2 == '') then error('scan next between requires value and second_value') end
  CEAI_SCAN_FOUNDLIST.deinitialize()
  CEAI_SCAN_MEMSCAN.nextScan(option, rounding, input1, input2, is_hex, is_binary_as_decimal, is_unicode, is_case_sensitive, is_percentage, saved_name)
  CEAI_SCAN_MEMSCAN.waitTillDone()
  CEAI_SCAN_FOUNDLIST.initialize()
  CEAI_SCAN_PHASE = 'next'
  return {active = true, pid = CEAI_SCAN_PID, phase = CEAI_SCAN_PHASE, option = scan_string(params, 'option', 'exact'), option_code = option, type = CEAI_SCAN_TYPE_NAME, type_code = CEAI_SCAN_VARTYPE, count = CEAI_SCAN_FOUNDLIST.Count, progress = scan_progress()}
end

handlers['scan.status'] = function(_params)
  if not scan_state_active() then return {active = false, pid = getOpenedProcessID(), phase = 'none', count = 0, progress = scan_progress()} end
  local count = 0
  if CEAI_SCAN_FOUNDLIST ~= nil then count = CEAI_SCAN_FOUNDLIST.Count end
  local current_pid = getOpenedProcessID()
  return {active = true, pid = CEAI_SCAN_PID, current_pid = current_pid, process_matches = current_pid == CEAI_SCAN_PID, phase = CEAI_SCAN_PHASE or 'new', type = CEAI_SCAN_TYPE_NAME, type_code = CEAI_SCAN_VARTYPE, count = count, progress = scan_progress()}
end

handlers['scan.results'] = function(params)
  require_scan_state()
  if CEAI_SCAN_FOUNDLIST == nil then error('Scan has no result list; run scan first') end
  local offset = math.max(0, integer_param(params, 'offset', 0))
  local limit = math.min(math.max(1, integer_param(params, 'limit', 256)), MAX_SCAN_RESULTS)
  local total = CEAI_SCAN_FOUNDLIST.Count
  local results = {}
  local stop = math.min(total, offset + limit)
  for index = offset, stop - 1 do
    results[#results + 1] = {index = index, address = normalize_address_text(CEAI_SCAN_FOUNDLIST.getAddress(index)), value = CEAI_SCAN_FOUNDLIST.getValue(index)}
  end
  return {active = true, pid = CEAI_SCAN_PID, offset = offset, limit = limit, count = #results, total = total, results = results, truncated = stop < total}
end

handlers['scan.reset'] = function(_params)
  scan_reset_state()
  return {active = false, pid = getOpenedProcessID(), phase = 'none', count = 0}
end

local function snapshot_lua_value(value, seen, depth)
  local value_type = type(value)
  if value_type == 'nil' then return {type = 'nil'} end
  if value_type == 'boolean' or value_type == 'number' or value_type == 'string' then
    return {type = value_type, value = value}
  end
  if value_type ~= 'table' then
    return {type = value_type, value = tostring(value)}
  end

  seen = seen or {}
  depth = depth or 0
  if seen[value] then return {type = 'table', cycle = true, value = tostring(value)} end
  if depth >= 8 then return {type = 'table', truncated = true, value = tostring(value)} end
  seen[value] = true

  local is_array, maximum = table_is_array(value)
  local snapshot
  if is_array then
    local items = {}
    for index = 1, maximum do
      items[index] = snapshot_lua_value(value[index], seen, depth + 1)
    end
    snapshot = {type = 'table', kind = 'array', value = items}
  else
    local entries = {}
    local truncated = false
    for key, item in pairs(value) do
      if #entries >= 256 then
        truncated = true
        break
      end
      entries[#entries + 1] = {
        key = snapshot_lua_value(key, seen, depth + 1),
        value = snapshot_lua_value(item, seen, depth + 1),
      }
    end
    snapshot = {type = 'table', kind = 'map', entries = entries, truncated = truncated}
  end
  seen[value] = nil
  return snapshot
end

handlers['lua.exec'] = function(params)
  local source = required(params, 'source')
  local chunk_name = params.chunk_name or '=(ce-ai)'
  local chunk, compile_error = load(source, chunk_name, 't', _G)
  if chunk == nil then error(compile_error or 'Lua compilation failed') end

  local packed = table.pack(pcall(chunk))
  if packed[1] ~= true then error(packed[2] or 'Lua execution failed') end
  local results = {}
  for index = 2, packed.n do
    results[#results + 1] = snapshot_lua_value(packed[index])
  end
  return {executed = true, result_count = packed.n - 1, results = results}
end

handlers['session.status'] = function(_params)
  local interface = debug_getCurrentDebuggerInterface()
  return {
    protocol = PROTOCOL,
    bridge_version = BRIDGE_VERSION,
    ce_pid = getCheatEngineProcessID(),
    opened_process_id = getOpenedProcessID(),
    debugger = debugger_name(interface),
    debugging = debug_isDebugging(),
    broken = debug_isBroken(),
    state_file = CEAI_BRIDGE_STATE_FILE,
  }
end

handlers['driver.device-status'] = function(_params)
  if type(ceai_isDBKLoaded) ~= 'function' then
    return {supported = false, loaded = false}
  end
  local loaded = ceai_isDBKLoaded() == true
  local version = 0
  if loaded and type(ceai_getDBKDriverVersion) == 'function' then
    version = ceai_getDBKDriverVersion() or 0
  end
  local device, attempted_version, win32_error, expected_version = '', 0, 0, 0
  if type(ceai_getDBKDeviceDiagnostics) == 'function' then
    device, attempted_version, win32_error, expected_version = ceai_getDBKDeviceDiagnostics()
  end
  return {
    supported = true,
    loaded = loaded,
    version = version,
    device = device or '',
    attempted_version = attempted_version or 0,
    expected_version = expected_version or 0,
    win32_error = win32_error or 0,
  }
end

handlers['driver.connect'] = function(params)
  local device = params.device or ''
  if type(ceai_connectDBKDevice) ~= 'function' then
    error('DBK device connection is not supported by this CE build')
  end
  local connected, version, name, win32_error, expected_version = ceai_connectDBKDevice(device)
  return {
    connected = connected == true,
    version = version or 0,
    expected_version = expected_version or 0,
    device = name or device,
    win32_error = win32_error or 0,
  }
end

local function dbvm_status()
  if type(ceai_getDBVMStatus) ~= 'function' then
    return {supported = false, running = false}
  end
  local status = ceai_getDBVMStatus() or {}
  status.supported = true
  return status
end

handlers['dbvm.status'] = function(_params)
  return dbvm_status()
end

handlers['dbvm.start'] = function(_params)
  if type(ceai_startDBVM) ~= 'function' then
    error('DBVM startup is not supported by this CE build')
  end
  local started, version, error_message = ceai_startDBVM()
  if started ~= true then
    error(error_message or 'DBVM launch failed')
  end
  return {
    started = true,
    version = version or 0,
    status = dbvm_status(),
  }
end

handlers['process.list'] = function(_params)
  local raw = getProcessList()
  local processes = {}
  for pid, name in pairs(raw) do
    processes[#processes + 1] = {pid = pid, name = name}
  end
  table.sort(processes, function(left, right) return left.pid < right.pid end)
  return {processes = processes, count = #processes}
end

handlers['process.open'] = function(params)
  local target = params.pid and integer_param(params, 'pid') or required(params, 'name')
  local opened = openProcess(target) == true
  return {opened = opened, pid = getOpenedProcessID()}
end

handlers['process.info'] = function(_params)
  local pid = getOpenedProcessID()
  local name = nil
  if pid ~= 0 then name = getProcessList()[pid] end
  return {pid = pid, name = name, opened = pid ~= 0}
end

handlers['process.pause'] = function(_params)
  pause()
  return {paused = true, pid = getOpenedProcessID()}
end

handlers['process.resume'] = function(_params)
  unpause()
  return {paused = false, pid = getOpenedProcessID()}
end

handlers['module.list'] = function(_params)
  local raw = enumModules() or {}
  local modules = {}
  for index = 1, #raw do
    local module = raw[index]
    modules[#modules + 1] = {
      name = module.Name,
      address = hex_address(module.Address),
      is_64bit = module.Is64Bit,
      path = module.PathToFile,
    }
  end
  table.sort(modules, function(left, right) return left.address < right.address end)
  return {modules = modules, count = #modules}
end

handlers['symbol.resolve'] = function(params)
  local expression = required(params, 'expression')
  local address = getAddressSafe(expression)
  if address == nil then error('Unable to resolve symbol: ' .. expression) end
  return {expression = expression, address = hex_address(address)}
end

handlers['memory.regions'] = function(params)
  local start_address = integer_param(params, 'start', 0)
  local stop_address = integer_param(params, 'stop', 0x7fffffffffff)
  local limit = math.min(integer_param(params, 'limit', 4096), 65536)
  local readable_only = boolean_param(params, 'readable_only', false)
  if stop_address <= start_address then error('stop must be greater than start') end

  local raw = enumMemoryRegions(stop_address) or {}
  local regions = {}
  for index = 1, #raw do
    local region = raw[index]
    local base = region.BaseAddress
    local committed = region.State == 0x1000
    local blocked = (region.Protect & 0x100) ~= 0 or (region.Protect & 0x1) ~= 0
    if base >= start_address and base < stop_address and (not readable_only or (committed and not blocked)) then
      regions[#regions + 1] = {
        base = hex_address(base),
        size = hex_address(region.RegionSize),
        state = region.State,
        protect = region.Protect,
        type = region.Type,
      }
      if #regions >= limit then break end
    end
  end
  return {regions = regions, count = #regions, truncated = #regions >= limit, dbvm_memory = dbvm_memory_diagnostics()}
end

handlers['memory.read'] = function(params)
  local address = integer_param(params, 'address')
  local size = integer_param(params, 'size')
  if size < 1 or size > MAX_FRAME then error('Memory read size must be between 1 and 1048576') end
  local bytes = readBytes(address, size, true)
  if bytes == nil then error('Unable to read memory at ' .. hex_address(address)) end
  return {address = hex_address(address), requested = size, size = #bytes, hex = bytes_to_hex(bytes), dbvm_memory = dbvm_memory_diagnostics()}
end

handlers['memory.write'] = function(params)
  local address = integer_param(params, 'address')
  local bytes = hex_to_bytes(required(params, 'hex'))
  local written = writeBytes(address, bytes) or 0
  return {address = hex_address(address), requested = #bytes, written = written, dbvm_memory = dbvm_memory_diagnostics()}
end

handlers['memory.disassemble'] = function(params)
  local address = integer_param(params, 'address')
  local count = math.min(integer_param(params, 'count', 16), 256)
  local instructions = {}
  local current = address
  for _ = 1, count do
    local text = disassemble(current)
    if text == nil then break end
    local size = getInstructionSize(current) or 0
    if size <= 0 then size = 1 end
    instructions[#instructions + 1] = {address = hex_address(current), size = size, text = text}
    current = current + size
  end
  return {instructions = instructions, count = #instructions}
end

handlers['scan.aob'] = function(params)
  local pattern = required(params, 'pattern')
  local protection = params.protection or ''
  local limit = math.min(integer_param(params, 'limit', 1024), 65536)
  local list = AOBScan(pattern, protection, 0, '1')
  local addresses = {}
  if list ~= nil then
    local count = math.min(list.Count, limit)
    for index = 0, count - 1 do addresses[#addresses + 1] = normalize_address_text(list[index]) end
    list.destroy()
  end
  return {addresses = addresses, count = #addresses, truncated = #addresses >= limit}
end

handlers['debug.attach'] = function(params)
  local interface = integer_param(params, 'interface', 0)
  if interface < 0 or interface > 4 then error('Invalid debugger interface') end
  debugProcess(interface)
  local current = debug_getCurrentDebuggerInterface()
  return {debugging = debug_isDebugging(), debugger = debugger_name(current), interface = current, dbvm_memory = dbvm_memory_diagnostics()}
end

handlers['debug.status'] = function(_params)
  local interface = debug_getCurrentDebuggerInterface()
  return {
    debugging = debug_isDebugging(),
    broken = debug_isBroken(),
    stepping = debug_isStepping(),
    debugger = debugger_name(interface),
    interface = interface,
    breakpoints = breakpoint_addresses(),
    dbvm_memory = dbvm_memory_diagnostics(),
  }
end

handlers['debug.detach'] = function(_params)
  detachIfPossible()
  return {debugging = debug_isDebugging(), detached = not debug_isDebugging()}
end

handlers['debug.breakpoint.list'] = function(_params)
  local addresses = breakpoint_addresses()
  return {breakpoints = addresses, count = #addresses}
end

handlers['debug.breakpoint.set'] = function(params)
  local address = integer_param(params, 'address')
  local size = integer_param(params, 'size', 1)
  local trigger = integer_param(params, 'trigger', 0)
  if trigger < 0 or trigger > 2 then error('Invalid breakpoint trigger') end
  debug_setBreakpoint(address, size, trigger)
  return {address = hex_address(address), size = size, trigger = trigger, breakpoints = breakpoint_addresses()}
end

handlers['debug.breakpoint.remove'] = function(params)
  local address = integer_param(params, 'address')
  debug_removeBreakpoint(address)
  return {address = hex_address(address), breakpoints = breakpoint_addresses()}
end

handlers['debug.continue'] = function(params)
  local mode = integer_param(params, 'mode', 0)
  if mode < 0 or mode > 2 then error('Invalid continue mode') end
  if not debug_isBroken() then error('Debugger is not stopped at a breakpoint') end
  debug_continueFromBreakpoint(mode)
  return {continued = true, mode = mode}
end

local function dispatch(method, params)
  local handler = handlers[method]
  if not handler then error('Unsupported method: ' .. method) end
  return handler(params)
end

local function response_for(payload)
  local ok, result = pcall(function()
    local method, params = parse_request(payload)
    local dispatch_ok, dispatch_result
    synchronize(function()
      dispatch_ok, dispatch_result = pcall(dispatch, method, params)
    end)
    if dispatch_ok ~= true then error(dispatch_result or 'Synchronized dispatch failed') end
    return dispatch_result
  end)
  if ok then return {ok = true, data = result} end
  return {ok = false, error = tostring(result), type = 'BridgeError'}
end

local function write_response(pipe, response)
  local raw = json_encode(response)
  if #raw > MAX_FRAME then raw = json_encode({ok = false, error = 'Response exceeds frame limit', type = 'BridgeError'}) end
  pipe.writeDword(#raw)
  pipe.writeString(raw)
end

local function state_path()
  local configured = os.getenv('CLI_ANYTHING_CE_STATE_FILE')
  if configured and configured ~= '' then return configured end
  local root = getTempFolder()
  local last = root:sub(-1)
  if last ~= '\\' and last ~= '/' then root = root .. '\\' end
  return root .. 'cli-anything-cheat-engine-' .. tostring(getCheatEngineProcessID()) .. '.json'
end

local function token_part()
  if type(generateGUIDString) == 'function' then
    return generateGUIDString():gsub('[{}%-]', '')
  end

  local seed = os.time() + getTickCount() + getCheatEngineProcessID()
  seed = seed + tonumber(tostring({}):match('0x(%x+)') or '0', 16)
  math.randomseed(seed)
  local parts = {}
  for index = 1, 8 do
    parts[index] = string.format('%08x', math.random(0, 0x7fffffff))
  end
  return table.concat(parts)
end

local guid1 = token_part()
local guid2 = token_part()
CEAI_BRIDGE_TOKEN = guid1 .. guid2
CEAI_BRIDGE_PIPE = 'cli-anything-cheat-engine-' .. tostring(getCheatEngineProcessID()) .. '-' .. guid1
CEAI_BRIDGE_STATE_FILE = state_path()

local state = {
  protocol = PROTOCOL,
  pipe = CEAI_BRIDGE_PIPE,
  token = CEAI_BRIDGE_TOKEN,
  ce_pid = getCheatEngineProcessID(),
  started_at = os.time(),
}
local state_handle, state_error = io.open(CEAI_BRIDGE_STATE_FILE, 'wb')
if not state_handle then
  CEAI_BRIDGE_STARTED = false
  error('Unable to write Cheat Engine AI state file: ' .. tostring(state_error))
end
state_handle:write(json_encode(state))
state_handle:close()

local log_path = CEAI_BRIDGE_STATE_FILE .. '.log'
local function bridge_log(message)
  local handle = io.open(log_path, 'ab')
  if handle then
    handle:write(os.date('!%Y-%m-%dT%H:%M:%SZ') .. ' ' .. tostring(message) .. '\n')
    handle:close()
  end
end

CEAI_BRIDGE_THREAD = createNativeThread(function(thread)
  thread.name = 'Cheat Engine AI Bridge'
  bridge_log('thread started')
  while not thread.Terminated do
    local ok, error_message = pcall(function()
      local pipe = createPipe(CEAI_BRIDGE_PIPE, 65536, 65536)
      if pipe.valid then
        pipe.acceptConnection()
        if pipe.connected then
          bridge_log('client connected')
          local read_ok, length = pcall(function() return pipe.readDword() end)
          if read_ok and length and length > 0 and length <= MAX_FRAME then
            bridge_log('request length=' .. tostring(length))
            bridge_log('payload read starting')
            local payload = pipe.readString(length)
            bridge_log('payload read finished size=' .. tostring(payload and #payload or 0))
            if payload then
              bridge_log('dispatch starting')
              local response = response_for(payload)
              bridge_log('dispatch finished ok=' .. tostring(response.ok))
              bridge_log('response write starting')
              write_response(pipe, response)
              bridge_log('response written')
            end
          elseif pipe.connected then
            write_response(pipe, {ok = false, error = 'Invalid request frame size', type = 'BridgeError'})
          end
        end
      end
      pcall(function() pipe.destroy() end)
    end)
    if not ok then bridge_log('thread error: ' .. tostring(error_message)) end
    sleep(10)
  end
end)

print('Cheat Engine AI bridge ready: ' .. CEAI_BRIDGE_STATE_FILE)
