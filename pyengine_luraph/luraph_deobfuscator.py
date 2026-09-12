import re
import sys
import subprocess
import os
import glob
import tempfile
import shutil


HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)
DEFAULT_OUTPUT_DIR = os.path.join(PROJECT_ROOT, "output")
RUN_TIMEOUT_SECONDS = 60

sys.pycache_prefix = os.path.join(PROJECT_ROOT, "__pycache__")
os.environ["PYTHONPYCACHEPREFIX"] = sys.pycache_prefix


def get_luau_executable():
    if os.name == "nt":
        candidate = os.path.join(os.path.dirname(HERE), "bin", "luau", "luau.exe")
        if os.path.isfile(candidate):
            return candidate

    env_path = os.environ.get("LUAU_EXECUTABLE")
    if env_path:
        return env_path

    path = shutil.which("luau")
    if path:
        return path

    return "luau"


def _configure_text_streams():
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None or not hasattr(stream, "reconfigure"):
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


_configure_text_streams()

MOCK_ENV_CODE = r"""
local real_type = type
local real_tonumber = tonumber
local real_unpack = unpack
local real_concat = table.concat
local real_tostring = tostring
local real_print = print

local _WAIT_COUNT = 0

local __last_http_url = nil
local __loadstring_n = 0

local function type(v)
    local mt = getmetatable(v)
    if mt and mt.__is_mock_dummy then
        return "userdata"
    end
    return real_type(v)
end

local function typeof(v)
    local mt = getmetatable(v)
    if mt and mt.__is_mock_dummy then
        return "Instance"
    end
    return type(v)
end

local function tonumber(v, base)
    if type(v) == "userdata" or (type(v) == "table" and getmetatable(v) and getmetatable(v).__is_mock_dummy) then
        return 1
    end
    return real_tonumber(v, base)
end

local function unpack(t, i, j)
    if real_type(t) == "table" then
        local looks_like_chunk = true
        for k, v in pairs(t) do
            if real_type(k) ~= "number" then looks_like_chunk = false break end
        end

        if looks_like_chunk and #t > 0 then
            print("UNPACK CALLED WITH TABLE (Potential Chunk): size=" .. #t)
            local success, res = pcall(real_concat, t, ",")
            if success then
                print("CAPTURED CHUNK STRING: " .. res)
                local url = res:match("https?://[%w%.%-%/%?%_%=%&%:]+") or res:match("www%.[%w%.%-%/%?%_%=%&%:]+")
                if url then
                    print("URL DETECTED IN UNPACK --> " .. url)
                end
            end
        end
    end
    return real_unpack(t, i, j)
end

local function table_concat(t, sep, i, j)
    local res = real_concat(t, sep, i, j)
    if real_type(res) == "string" then
        local url = res:match("https?://[%w%.%-%/%?%_%=%&%:]+") or res:match("www%.[%w%.%-%/%?%_%=%&%:]+")
        if url then
            print("URL DETECTED IN CONCAT --> " .. url)
        end
    end
    return res
end

local function escape_lua_string(s)
    local parts = {'"'}
    for i = 1, #s do
        local byte = string.byte(s, i)
        if byte == 92 then
            table.insert(parts, "\\\\")
        elseif byte == 34 then
            table.insert(parts, "\\\"")
        elseif byte == 10 then
            table.insert(parts, "\\n")
        elseif byte == 13 then
            table.insert(parts, "\\r")
        elseif byte == 9 then
            table.insert(parts, "\\t")
        elseif byte >= 32 and byte <= 126 then
            table.insert(parts, string.char(byte))
        else
            table.insert(parts, string.format("\\%03d", byte))
        end
    end
    table.insert(parts, '"')
    return table.concat(parts)
end

local function recursive_tostring(v, depth)
    if depth == nil then depth = 0 end

    if real_type(v) == "string" then
        return escape_lua_string(v)
    elseif real_type(v) == "number" then
        if v == math.floor(v) and v >= -2147483648 and v <= 2147483647 then
            return tostring(math.floor(v))
        end
        return tostring(v)
    elseif real_type(v) == "boolean" then
        return tostring(v)
    elseif v == nil then
        return "nil"
    elseif real_type(v) == "function" then
        return "function(...) end"
    elseif real_type(v) == "buffer" then
        -- Without this, a real buffer argument silently rendered as "nil"
        -- in every trace line and, worse, in the argument-replay this
        -- engine feeds back into a recursively-descended stage -- turning a
        -- script that's actually called with real decompressed data into
        -- one that looks like it's called with nothing. Confirmed via
        -- direct instrumentation against a real sample: the "argument" a
        -- crash seemed to trace back to was never nil at all, only ever
        -- logged that way.
        local ok, s = pcall(buffer.tostring, v)
        if ok and s then
            return "buffer.fromstring(" .. escape_lua_string(s) .. ")"
        end
        return "buffer.create(0)"
    elseif real_type(v) == "table" then
        if getmetatable(v) and getmetatable(v).__is_mock_dummy then
            return tostring(v)
        end
        if depth > 2 then
            return "{}"
        end
        local parts = {}
        local keys = {}
        for k in pairs(v) do table.insert(keys, k) end
        table.sort(keys, function(a,b) return tostring(a) < tostring(b) end)

        for _, k in ipairs(keys) do
            local val = v[k]
            local k_str
            if real_type(k) == "string" then
                k_str = "[" .. escape_lua_string(k) .. "]"
            elseif real_type(k) == "number" then
                k_str = "[" .. tostring(k) .. "]"
            else
                k_str = "[" .. escape_lua_string(tostring(k)) .. "]"
            end
            table.insert(parts, k_str .. " = " .. recursive_tostring(val, depth + 1))
        end
        return "{" .. real_concat(parts, ", ") .. "}"
    else
        return "nil"
    end
end

local function create_dummy(name)
    local d = {}
    local mt = {
        __is_mock_dummy = true,
        __index = function(_, k)
             print("ACCESSED --> " .. name .. "." .. k)
             if k == "HttpGet" or k == "HttpGetAsync" then
                 return function(_, url, ...)
                     print("URL DETECTED --> " .. tostring(url))
                     __last_http_url = tostring(url)
                     return create_dummy("HttpGetResult")
                 end
            end
            return create_dummy(name .. "." .. k)
        end,
        __newindex = function(_, k, v)
            local val_str = recursive_tostring(v, 0)
            print("PROP_SET --> " .. name .. "." .. k .. " = " .. val_str)
        end,
        __call = function(_, ...)
            local args = {...}
            local arg_str = ""
            for i, v in ipairs(args) do
                if i > 1 then arg_str = arg_str .. ", " end
                arg_str = arg_str .. recursive_tostring(v)
            end

            local var_name = name:gsub("%.", "_") .. "_" .. math.random(100, 999)
            print("CALL_RESULT --> local " .. var_name .. " = " .. name .. "(" .. arg_str .. ")")
            if name == "task.wait" or name == "wait" then
                _WAIT_COUNT = _WAIT_COUNT + 1
                if _WAIT_COUNT > 10 then
                     error("Too many waits!")
                end
            end

            for i, v in ipairs(args) do
                if real_type(v) == "function" then
                    print("--- ENTERING CLOSURE FOR " .. name .. " ---")
                    local success, err = pcall(v,
                        create_dummy("arg1"), create_dummy("arg2"),
                        create_dummy("arg3"), create_dummy("arg4"))
                    if not success then
                        print("-- CLOSURE ERROR: " .. tostring(err))
                    end
                    print("--- EXITING CLOSURE FOR " .. name .. " ---")
                end
            end

            if name == "readfile" or name == "loadfile" or name == "dofile" then
                return ""
            end
            if name == "isfile" or name == "isfolder" then
                return false
            end
            if name == "listfiles" then
                return {}
            end
            if name == "writefile" or name == "appendfile" or name == "makefolder" or name == "delfile" or name == "delfolder" then
                return nil
            end

            return create_dummy(var_name)
        end,
        __tostring = function() return name end,
        __concat = function(a, b) return tostring(a) .. tostring(b) end,
        __add = function(a, b) return create_dummy("("..tostring(a).."+"..tostring(b)..")") end,
        __sub = function(a, b) return create_dummy("("..tostring(a).."-"..tostring(b)..")") end,
        __mul = function(a, b) return create_dummy("("..tostring(a).."*"..tostring(b)..")") end,
        __div = function(a, b) return create_dummy("("..tostring(a).."/"..tostring(b)..")") end,
        __mod = function(a, b) return create_dummy("("..tostring(a).."%"..tostring(b)..")") end,
        __pow = function(a, b) return create_dummy("("..tostring(a).."^"..tostring(b)..")") end,
        __unm = function(a) return create_dummy("-"..tostring(a)) end,
        __lt = function(a, b) return false end,
        __le = function(a, b) return false end,
        __eq = function(a, b) return false end,
        __len = function(a) return 2 end,
    }
    setmetatable(d, mt)
    return d
end

local function mock_pairs(t)
    local mt = getmetatable(t)
    if mt and mt.__is_mock_dummy then
        local i = 0
        return function(...)
            i = i + 1
            if i <= 1 then
                return i, create_dummy(tostring(t).."_v"..i)
            end
            return nil
        end
    end
    return pairs(t)
end

local function mock_ipairs(t)
    local mt = getmetatable(t)
    if mt and mt.__is_mock_dummy then
        local i = 0
        return function(...)
            i = i + 1
            if i <= 1 then
                return i, create_dummy(tostring(t).."_v"..i)
            end
            return nil
        end
    end
    return ipairs(t)
end

local safe_string = {}
for k, v in pairs(string) do
    safe_string[k] = v
end
safe_string.char = function(...)
    local args = {...}
    for i = 1, #args do
        local value = tonumber(args[i]) or 0
        args[i] = math.floor(value) % 256
    end
    return string.char(unpack(args))
end

-- Luraph's VM leans on table.create/table.pack/table.unpack/table.find for
-- its own opcode dispatch and constant-pool handling, same as MoonSecV3's.
-- Mirror the full real library (only .concat is wrapped) so none of that
-- silently resolves to nil mid-decode.
local safe_table = {}
for k, v in pairs(table) do
    safe_table[k] = v
end
safe_table.concat = table_concat

-- Luraph-style loaders build one big table like {K=function...,[93]=
-- buffer.fill,[125]=unpack,[62]=loadstring,...} that captures real stdlib
-- functions under numeric/short keys chosen fresh on every compile -- there
-- is no fixed number to hardcode, Luraph re-randomizes it specifically to
-- keep any one discovery from transferring to the next file. But identity
-- doesn't get obfuscated: whatever key holds "the real buffer.readu8" still
-- holds a function value that IS buffer.readu8, byte for byte the same
-- object, on any build. Recording every real function we hand out under its
-- real name, then diffing that against whatever table the target itself
-- calls setmetatable() on, recovers "key 93 is buffer.fill" automatically
-- for ANY sample built this way -- no per-file archaeology required for the
-- part of the puzzle that's a captured library call. It can't do anything
-- for a key that holds a bare number/constant of the obfuscator's own
-- invention (no real object to match against) -- that part stays manual.
local FUNCTION_NAME_MAP = {}
local function register_value(name, v)
    if real_type(v) == "function" then
        if not FUNCTION_NAME_MAP[v] then FUNCTION_NAME_MAP[v] = name end
    elseif real_type(v) == "table" then
        for k2, v2 in pairs(v) do
            if real_type(v2) == "function" and not FUNCTION_NAME_MAP[v2] then
                FUNCTION_NAME_MAP[v2] = name .. "." .. tostring(k2)
            end
        end
    end
end

local real_setmetatable = setmetatable
local fingerprinted = setmetatable({}, { __mode = "k" })
local function hooked_setmetatable(t, mt)
    if real_type(t) == "table" and not fingerprinted[t] then
        local fn_count, total = 0, 0
        for _, v in pairs(t) do
            total = total + 1
            if real_type(v) == "function" then fn_count = fn_count + 1 end
        end
        -- heuristic: a real Lua/game object practically never has 8+
        -- function-valued fields in one flat table; a Luraph-style captured-
        -- stdlib table routinely has dozens
        if fn_count >= 8 and total >= 8 then
            fingerprinted[t] = true
            print("FUNCTABLE: setmetatable() called on a table with " .. fn_count .. "/" .. total ..
                  " function-valued keys -- resolving against known stdlib functions:")
            for k, v in pairs(t) do
                if real_type(v) == "function" then
                    local nm = FUNCTION_NAME_MAP[v]
                    if nm then
                        print("FUNCTABLE KEY[" .. tostring(k) .. "] --> " .. nm)
                    end
                end
            end
        end
    end
    return real_setmetatable(t, mt)
end

local MockEnv = {}
local safe_globals = {
    ["string"] = safe_string,
    ["table"] = safe_table,
    ["math"] = math,
    -- Real, unproxied: Luraph's own decompressor captures these once at
    -- startup to unpack its embedded bytecode blob. A create_dummy() stand-in
    -- here breaks decompression outright rather than producing a trace (see
    -- the module docstring above).
    ["buffer"] = buffer,
    ["pairs"] = mock_pairs,
    ["ipairs"] = mock_ipairs,
    ["select"] = select,
    ["unpack"] = unpack,
    ["tonumber"] = tonumber,
    ["tostring"] = tostring,
    ["type"] = type,
    ["typeof"] = typeof,
    ["pcall"] = pcall,
    ["xpcall"] = xpcall,
    ["getfenv"] = getfenv,
    ["setmetatable"] = hooked_setmetatable,
    ["getmetatable"] = getmetatable,
    ["error"] = error,
    ["assert"] = assert,
    ["next"] = next,
    ["print"] = function(...)
        local args = {...}
        local parts = {}
        for i,v in ipairs(args) do table.insert(parts, tostring(v)) end
        print("TRACE_PRINT --> " .. table.concat(parts, "\t"))
    end,
    ["_VERSION"] = _VERSION,
    ["rawset"] = rawset,
    ["rawget"] = rawget,
    ["os"] = os,
    ["io"] = io or create_dummy("io"),
    ["bit32"] = bit32,
    ["vector"] = vector,
    -- Real, unproxied: coroutine.wrap/create is a pure Luau standard library
    -- with zero dependency on a running Roblox engine (unlike Vector2/
    -- Instance, which really do need one to exist as genuine userdata). The
    -- generic create_dummy() proxy used for other exploit-only globals below
    -- silently drops the real arguments a wrapped/resumed coroutine function
    -- is called with -- confirmed root cause of a real crash during testing
    -- ("invalid argument #1 to 'readu8' (buffer expected, got nil)" a few
    -- statements after a coroutine.wrap call, because the wrapped closure's
    -- varargs came back empty). Exposing the real library instead threads
    -- arguments through correctly since it's genuine Luau coroutine support.
    ["coroutine"] = coroutine,
    ["debug"] = debug,
    ["dofile"] = dofile,
    ["loadfile"] = loadfile,
    ["newproxy"] = newproxy,
    ["loadstring"] = function(s)
        -- Deliberately never executes the captured chunk here -- that would
        -- mean running an unknown-depth nested obfuscated payload during
        -- analysis. Capturing its full literal text via CONTENT START/END
        -- (the engine wrapper below pulls this back out into its own
        -- .stageN.lua file) is enough to hand the *next* run of this same
        -- tool a fresh target one layer deeper, deliberately one manual step
        -- at a time rather than silently auto-recursing.
        __loadstring_n = __loadstring_n + 1
        local n = __loadstring_n
        local bootstrap_expr
        if real_type(s) == "string" then
            print("LOADSTRING DETECTED: size=" .. tostring(#s))
            print("LOADSTRING CONTENT START")
            print(s)
            print("LOADSTRING CONTENT END")
            bootstrap_expr = "loadstring(" .. escape_lua_string(s) .. ")"
        else
            print("LOADSTRING DETECTED: non-string source (fetched remotely)")
            if __last_http_url then
                bootstrap_expr = "loadstring(game:HttpGet(" .. escape_lua_string(__last_http_url) .. "))"
            else
                bootstrap_expr = "(function() end)"
            end
        end
        __last_http_url = nil
        print("LOADSTRING BOOTSTRAP --> local loadstring_result_" .. n .. " = (" .. bootstrap_expr .. " or function() end)()")
        return function(...)
            -- Tagged with this loadstring's own index (n) so the engine
            -- wrapper below can correlate "N arguments, these values" back
            -- to the matching extracted .stageN.lua -- confirmed necessary:
            -- a real sample called its loaded chunk with exactly one
            -- argument, `nil`, and re-running that chunk with *zero*
            -- arguments instead (what auto-descend did before this) is a
            -- different, observably different thing in Lua (table.pack()
            -- vs table.pack(nil) have different .n, which code can and does
            -- branch on).
            local nargs = select("#", ...)
            print("LOADSTRING CALL[" .. n .. "] with " .. nargs .. " arg(s)")
            local ok_nm, nm = pcall(debug.info, 2, "n")
            if ok_nm and nm then print("LOADSTRING CALLED-VIA --> " .. tostring(nm)) end
            if nargs > 0 then
                local args = {...}
                for ai = 1, nargs do
                    print("LOADSTRING ARG[" .. n .. "][" .. ai .. "] --> " .. recursive_tostring(args[ai], 0))
                end
            end
            return create_dummy("loadstring_result_" .. n)
        end
    end
}

setmetatable(MockEnv, {
    __index = function(t, k)
        if safe_globals[k] then
            return safe_globals[k]
        end

        if k == "game" then
            print("ACCESSED --> game")
            return create_dummy("game")
        end
        if k == "getgenv" or k == "getrenv" or k == "getreg" then
            return function() return MockEnv end
        end
        if k == "_ENV" then
            return MockEnv
        end

        -- Auto-adjusting fallback: rather than maintaining a hand-picked
        -- allowlist of "known exploit/Roblox globals" that has to be
        -- extended by hand every time a new script touches something new
        -- (Vector2/Instance/task/... were all originally handled this way,
        -- one name at a time), ANY unrecognized global gets a working dummy
        -- automatically. A script that reads/calls an unknown name almost
        -- always expects *something* usable back -- a bare `nil` there is
        -- what previously turned "this script uses a global we haven't
        -- listed yet" into a hard crash (attempt to index/call a nil value)
        -- that stopped the trace dead, exactly the failure mode this is
        -- meant to reduce. This can't identify a *new bytecode format* --
        -- nothing running inside the sandbox can, since the VM interpreting
        -- that bytecode is the target's own code, opaque to us either way --
        -- it only removes the need to keep hand-tuning which fake globals
        -- the environment offers.
        print("ACCESSED (auto-dummy) --> " .. k)
        return create_dummy(k)
    end,

    __newindex = function(t, k, v)
        local val_str = recursive_tostring(v, 0)
        print("SET GLOBAL --> " .. tostring(k) .. " = " .. val_str)
        rawset(t, k, v)
    end
})

safe_globals["_G"] = MockEnv
safe_globals["shared"] = MockEnv

-- Register every function/library this sandbox actually hands out (real
-- ones like buffer.*/string.*/table.*, and our own wrapped ones like the
-- loadstring mock and TRACE_PRINT-wrapped print) under its real name, so
-- hooked_setmetatable above can recognize exactly what the target actually
-- captured -- not some idealized reference copy.
for gname, gval in pairs(safe_globals) do
    register_value(gname, gval)
end

-- See the identical comment in pyengine_moonsec/moonsec_deobfuscator.py:
-- `local _ENV = MockEnv` does not reliably route bare global reads/writes
-- inside nested closures in this Luau build; `setfenv(1, MockEnv)` is the
-- mechanism that actually works.
setfenv(1, MockEnv);
local function getfenv(...)
    return MockEnv
end;
"""


def reflow_semicolons(content):
    """Insert a real newline after every statement-terminating ';' that
    isn't inside a string/comment/long-bracket literal. Luraph output (and
    especially a decompressed nested stage like da0.lua's) is typically
    emitted as one single physical line thousands of characters long --
    every runtime error and every debug.traceback() frame in it then reports
    the exact same line number no matter which statement actually failed,
    which makes diagnosing a crash here otherwise impossible. This is purely
    a whitespace change (Lua statement boundaries don't care about newlines)
    so it can't alter behavior."""
    out = []
    i, n = 0, len(content)
    while i < n:
        c = content[i]
        if c in ("'", '"'):
            quote = c
            out.append(c)
            i += 1
            while i < n:
                out.append(content[i])
                if content[i] == "\\" and i + 1 < n:
                    i += 1
                    out.append(content[i])
                    i += 1
                    continue
                if content[i] == quote:
                    i += 1
                    break
                i += 1
            continue

        if content.startswith("--", i):
            j = i + 2
            level = None
            k = j
            if k < n and content[k] == "[":
                k += 1
                eq = 0
                while k < n and content[k] == "=":
                    eq += 1
                    k += 1
                if k < n and content[k] == "[":
                    level = eq
                    k += 1
            if level is not None:
                close = "]" + "=" * level + "]"
                end = content.find(close, k)
                end = (end + len(close)) if end != -1 else n
            else:
                nl = content.find("\n", i)
                end = nl if nl != -1 else n
            out.append(content[i:end])
            i = end
            continue

        if c == "[":
            j = i + 1
            eq = 0
            while j < n and content[j] == "=":
                eq += 1
                j += 1
            if j < n and content[j] == "[":
                close = "]" + "=" * eq + "]"
                end = content.find(close, j + 1)
                end = (end + len(close)) if end != -1 else n
                out.append(content[i:end])
                i = end
                continue

        out.append(c)
        if c == ";":
            out.append("\n")
        i += 1
    return "".join(out)


MAX_STAGE_DEPTH = 6


def deobfuscate_file(filepath, output_dir=None, depth=0, call_args_lua=""):
    print(f"Processing {filepath}...")

    if ".deobf." in filepath or ".report." in filepath:
        return None

    output_dir = output_dir or DEFAULT_OUTPUT_DIR
    os.makedirs(output_dir, exist_ok=True)

    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
        return None

    content = reflow_semicolons(content)

    looks_luraph = bool(re.search(r"luraph", content, re.IGNORECASE))
    looks_vm_wrapper = "setmetatable(" in content and "buffer." in content
    if not looks_luraph and not looks_vm_wrapper:
        print(
            "NOTE: no 'luraph' signature or buffer-based VM-wrapper shape found in this "
            "file. Running the sandbox anyway -- the same technique still works on any "
            "obfuscator whose VM bottoms out into real game/API calls -- but if this isn't "
            "actually Luraph-style output, expect a thinner trace."
        )

    if call_args_lua:
        print(f"Replaying the real call arguments this chunk was invoked with: {call_args_lua}")
    wrapped_target = (
        "local __ok, __err = xpcall(function(...)\n"
        + content
        + "\nend, function(__e)\n"
        "    real_print(\"RUNTIME_ERROR --> \" .. tostring(__e))\n"
        "    local __tb = debug.traceback()\n"
        "    if __tb and __tb ~= \"\" then\n"
        "        real_print(\"TRACEBACK --> \" .. __tb)\n"
        "    end\n"
        "    return __e\n"
        "end" + (", " + call_args_lua if call_args_lua else "") + ")\n"
    )

    new_content = MOCK_ENV_CODE + wrapped_target

    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", suffix=".lua", delete=False
    ) as temp_handle:
        temp_file = temp_handle.name
        temp_handle.write(new_content)

    print(f"Executing Luraph sandbox for {filepath} (timeout {RUN_TIMEOUT_SECONDS}s)...")

    cmd = [get_luau_executable(), temp_file, "-a", "1"]
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    RELEVANT_PREFIXES = (
        "ACCESSED", "CALL_RESULT", "URL DETECTED", "SET GLOBAL",
        "UNPACK CALLED", "CAPTURED CHUNK", "CLOSURE", "TRACE_PRINT",
        "PROP_SET", "LOADSTRING", "RUNTIME_ERROR", "TRACEBACK",
        "LOADSTRING BOOTSTRAP", "FUNCTABLE",
    )

    stdout_lines = []
    stdout_data = b""
    err = b""
    try:
        stdout_data, err = process.communicate(timeout=RUN_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        print(f"Timeout ({RUN_TIMEOUT_SECONDS}s) reached -- this is expected for a VM that "
              f"never terminates on its own (see below); using whatever trace was captured "
              f"up to this point.")
        process.kill()
        stdout_data, err = process.communicate()
        if exc.output:
            stdout_data = exc.output + stdout_data
        if exc.stderr:
            err = exc.stderr + err
    except Exception as e:
        print(f"Error: {e}")
        process.kill()

    if stdout_data:
        for line in stdout_data.decode("utf-8", errors="replace").splitlines():
            stdout_lines.append(line.rstrip("\n"))
            if any(prefix in line for prefix in RELEVANT_PREFIXES):
                print(line.strip())

    if err:
        stderr_text = err.decode("utf-8", errors="replace")
        if stderr_text.strip():
            print("STDERR:", stderr_text)
            if any(marker in stderr_text for marker in (
                "Expected identifier", "MalformedString", "Malformed",
                "expected", "unexpected symbol",
            )):
                print(
                    "HINT: this looks like a Lua/Luau *syntax* error, meaning the input "
                    "wasn't valid Lua to begin with -- the sandbox never even started "
                    "running your script. Paste the ORIGINAL, unmodified obfuscated script."
                )

    trace_lines = [
        line.strip() for line in stdout_lines
        if any(prefix in line for prefix in RELEVANT_PREFIXES)
    ]

    if not trace_lines and not err:
        print(
            "NOTE: the sandbox ran with no errors but captured no trace activity at all. "
            "Double check the target is actually the obfuscated wrapper (not something "
            "already processed)."
        )

    key_map = dict(re.findall(r"FUNCTABLE KEY\[(.+?)\] --> (\S+)", "\n".join(stdout_lines)))
    if key_map:
        keymap_file = os.path.join(output_dir, os.path.basename(filepath) + ".keymap.txt")
        with open(keymap_file, "w", encoding="utf-8") as f:
            f.write(f"# auto-discovered key -> real stdlib function map for {filepath}\n")
            f.write("# found by identity match against known functions when the target "
                    "called setmetatable() on its own table -- not by any number specific "
                    "to this file, so this technique works on any similarly-built VM\n\n")
            for k, v in sorted(key_map.items(), key=lambda kv: (len(kv[0]), kv[0])):
                f.write(f"[{k}] = {v}\n")
        print(f"Auto-discovered {len(key_map)} key -> real-function mappings, saved to {keymap_file}")

        def _annotate(mo):
            key = mo.group(1)
            name = key_map.get(key)
            return f"[{key}--[[{name}]]]" if name else mo.group(0)

        readable = re.sub(r"\[(\d+)\]", _annotate, content)
        readable_file = os.path.join(output_dir, os.path.basename(filepath) + ".readable.lua")
        with open(readable_file, "w", encoding="utf-8", newline="") as f:
            f.write(readable)
        print(f"Reflowed + key-annotated source (readable even with a thin runtime trace) saved to {readable_file}")

    stage_files = []
    full_stdout = "\n".join(stdout_lines)
    content_matches = re.findall(r"LOADSTRING CONTENT START\n(.*?)\nLOADSTRING CONTENT END", full_stdout, re.DOTALL)
    bootstrap_ns = re.findall(r"LOADSTRING BOOTSTRAP --> local loadstring_result_(\d+)", full_stdout)

    call_args_by_n = {}
    for call_n, nargs_str in re.findall(r"LOADSTRING CALL\[(\d+)\] with (\d+) arg\(s\)", full_stdout):
        if call_n in call_args_by_n:
            continue
        nargs = int(nargs_str)
        arg_values = []
        for ai in range(1, nargs + 1):
            m = re.search(
                re.escape(f"LOADSTRING ARG[{call_n}][{ai}] --> ") + r"(.*)",
                full_stdout,
            )
            arg_values.append(m.group(1) if m else "nil")
        call_args_by_n[call_n] = ", ".join(arg_values)

    for idx, match_text in enumerate(content_matches):
        if len(match_text.strip()) < 20:
            continue
        stage_n = bootstrap_ns[idx] if idx < len(bootstrap_ns) else str(idx + 1)
        stage_args = call_args_by_n.get(stage_n, "")
        if stage_args:
            match_text = f"return (function(...)\n{match_text}\nend)({stage_args})\n"
        stage_path = os.path.join(output_dir, os.path.basename(filepath) + f".stage{stage_n}.lua")
        with open(stage_path, "w", encoding="utf-8", newline="") as f:
            f.write(match_text)
        stage_files.append((stage_path, stage_args))

    def _patch_bootstrap(line):
        if not line.startswith("LOADSTRING BOOTSTRAP -->"):
            return line
        m = re.match(r"(LOADSTRING BOOTSTRAP --> local loadstring_result_(\d+) = \(.*\))\(\)$", line)
        if not m:
            return line
        n = m.group(2)
        args = call_args_by_n.get(n)
        return f"{m.group(1)}({args})" if args else line

    trace_lines = [_patch_bootstrap(line) for line in trace_lines]

    report_file = os.path.join(output_dir, os.path.basename(filepath) + ".report.txt")
    with open(report_file, "w", encoding="utf-8") as f:
        f.write("--- LURAPH DEOBFUSCATION REPORT ---\n")
        f.write(f"File: {filepath}\n\n")
        f.write("--- TRACE ---\n")
        for line in trace_lines:
            f.write(line + "\n")

    print(f"Report saved to {report_file}")

    deobf_path = report_file.replace(".report.txt", ".deobf.lua")
    try:
        import trace_to_lua
        import importlib
        importlib.reload(trace_to_lua)
        trace_to_lua.parse_trace(report_file)
    except Exception as e:
        print(f"Failed to convert trace: {e}")
        import traceback
        traceback.print_exc()

    if os.path.exists(temp_file) and not os.environ.get("KEEP_TEMP"):
        os.remove(temp_file)

    deepest_path = deobf_path if os.path.isfile(deobf_path) else None

    for stage_path, stage_call_args in stage_files:
        if depth >= MAX_STAGE_DEPTH:
            print(f"Nested loadstring payload extracted to {stage_path} -- stopped auto-descending "
                  f"at depth {MAX_STAGE_DEPTH} (probably a real loop, not more wrapper layers); "
                  f"run this same tool again targeting that file to keep going by hand.")
            continue
        print(f"Nested loadstring payload extracted to {stage_path} -- descending into it automatically...")
        nested_result = deobfuscate_file(stage_path, output_dir, depth=depth + 1)
        if nested_result:
            deepest_path = nested_result

    if depth == 0 and deepest_path:
        print(f"FINAL_DEOBF_PATH --> {deepest_path}")

    return deepest_path


def main():
    target = "obfuscated_scripts"
    if len(sys.argv) > 1:
        target = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else None

    if os.path.isfile(target):
        deobfuscate_file(target, output_dir)
    elif os.path.isdir(target):
        files = glob.glob(os.path.join(target, "*.lua"))
        for file in sorted(files):
            if "temp_deob" in file or ".report.txt" in file or ".deobf." in file or ".stage" in file:
                continue
            deobfuscate_file(file, output_dir)
            print("-" * 40)
    else:
        print("Invalid path")


if __name__ == "__main__":
    main()
