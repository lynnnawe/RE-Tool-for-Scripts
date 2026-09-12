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
COMPOUND_ASSIGNMENT_OPERATORS = ("+=", "-=", "*=", "/=", "%=", "..=")

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


def _find_compound_lhs_start(content, operator_index):
    idx = operator_index - 1
    while idx >= 0 and content[idx].isspace():
        idx -= 1

    while idx >= 0 and content[idx] == "]":
        bracket_depth = 1
        idx -= 1
        while idx >= 0 and bracket_depth > 0:
            if content[idx] == "]":
                bracket_depth += 1
            elif content[idx] == "[":
                bracket_depth -= 1
            idx -= 1

    while idx >= 0 and (content[idx].isalnum() or content[idx] == "_"):
        idx -= 1

    while idx >= 0 and content[idx] == ".":
        idx -= 1
        while idx >= 0 and content[idx] == "]":
            bracket_depth = 1
            idx -= 1
            while idx >= 0 and bracket_depth > 0:
                if content[idx] == "]":
                    bracket_depth += 1
                elif content[idx] == "[":
                    bracket_depth -= 1
                idx -= 1
        while idx >= 0 and (content[idx].isalnum() or content[idx] == "_"):
            idx -= 1

    return idx + 1


def _find_compound_rhs_end(content, rhs_start):
    idx = rhs_start
    length = len(content)
    bracket_depth = 0
    paren_depth = 0
    brace_depth = 0
    quote = None

    while idx < length and content[idx].isspace():
        idx += 1

    while idx < length:
        char = content[idx]

        if quote:
            if char == "\\":
                idx += 2
                continue
            if char == quote:
                quote = None
            idx += 1
            continue

        if char in ("'", '"'):
            quote = char
            idx += 1
            continue

        if char == "[":
            bracket_depth += 1
        elif char == "]":
            bracket_depth = max(0, bracket_depth - 1)
        elif char == "(":
            paren_depth += 1
        elif char == ")":
            if paren_depth == 0 and bracket_depth == 0 and brace_depth == 0:
                break
            paren_depth = max(0, paren_depth - 1)
        elif char == "{":
            brace_depth += 1
        elif char == "}":
            if brace_depth == 0 and bracket_depth == 0 and paren_depth == 0:
                break
            brace_depth = max(0, brace_depth - 1)
        elif bracket_depth == 0 and paren_depth == 0 and brace_depth == 0:
            if char in ";,\n\r":
                break
            if char.isspace():
                break

        idx += 1

    return idx


def normalize_luau_syntax(content):
    """Rewrite real `+=`-style compound assignments to plain Lua, while
    staying entirely outside of string/comment literals so encoded/encrypted
    constant strings (common in obfuscated payloads) never get corrupted by
    an accidental `*=`/`-=`-shaped byte pair inside their content."""
    replacements = []
    idx = 0
    length = len(content)

    while idx < length:
        char = content[idx]

        if char in ("'", '"'):
            quote = char
            idx += 1
            while idx < length:
                if content[idx] == "\\":
                    idx += 2
                    continue
                if content[idx] == quote:
                    idx += 1
                    break
                idx += 1
            continue

        if content.startswith("--", idx):
            bracket_start = idx + 2
            level = None
            j = bracket_start
            if j < length and content[j] == "[":
                j += 1
                eq = 0
                while j < length and content[j] == "=":
                    eq += 1
                    j += 1
                if j < length and content[j] == "[":
                    level = eq
                    j += 1
            if level is not None:
                close = "]" + "=" * level + "]"
                end = content.find(close, j)
                idx = (end + len(close)) if end != -1 else length
            else:
                nl = content.find("\n", idx)
                idx = nl + 1 if nl != -1 else length
            continue

        if char == "[":
            j = idx + 1
            eq = 0
            while j < length and content[j] == "=":
                eq += 1
                j += 1
            if j < length and content[j] == "[":
                close = "]" + "=" * eq + "]"
                end = content.find(close, j + 1)
                idx = (end + len(close)) if end != -1 else length
                continue

        matched_operator = None
        for operator in COMPOUND_ASSIGNMENT_OPERATORS:
            if content.startswith(operator, idx):
                matched_operator = operator
                break

        if not matched_operator:
            idx += 1
            continue

        lhs_start = _find_compound_lhs_start(content, idx)
        rhs_start = idx + len(matched_operator)
        rhs_end = _find_compound_rhs_end(content, rhs_start)

        lhs = content[lhs_start:idx].strip()
        rhs = content[rhs_start:rhs_end].strip()
        if lhs and rhs:
            replacements.append(
                (lhs_start, rhs_end, f"{lhs} = {lhs} {matched_operator[:-1]} {rhs}")
            )
        idx = rhs_end

    if not replacements:
        return content

    rewritten = content
    for start, end, replacement in reversed(replacements):
        rewritten = rewritten[:start] + replacement + rewritten[end:]

    return rewritten


_configure_text_streams()

MOCK_ENV_CODE = r"""
local real_type = type
local real_tonumber = tonumber
local real_unpack = unpack
local real_concat = table.concat
local real_tostring = tostring
local real_print = print

local _WAIT_COUNT = 0

-- The obfuscated "hub" pattern `loadstring(game:HttpGet(url))()` is loading a
-- REAL remote UI library, and everything downstream (button/section/element
-- calls) is method-chained off whatever that returns. Tracking the most
-- recently observed HttpGet URL here lets the loadstring mock below turn
-- that into a real, working `loadstring(game:HttpGet(url))()` bootstrap
-- statement in the emitted trace/replay -- instead of an anonymous
-- "loadstring_result" placeholder with no real definition anywhere, which
-- is undefined (nil) the moment the generated .deobf.lua is actually run.
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

-- Every branch here must produce a *syntactically valid* Lua expression,
-- because this string is spliced directly into generated .deobf.lua source.
-- Luau's own tostring() on a table/function/thread/userdata yields
-- "table: 0x...", "function: 0x...", etc. -- none of which are valid Lua
-- literals -- so those cases get real placeholder expressions instead of a
-- bare tostring() fallback.
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
        -- thread / userdata / vector and anything else with no valid literal form
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

-- MoonSecV3's own VM interpreter routinely leans on table.create/table.unpack/
-- table.pack/table.find/table.move for its opcode dispatch and constant-pool
-- handling. Exposing only a hand-picked subset of `table` (as this sandbox
-- used to) left those calls silently resolving to nil with no ACCESSED trace
-- at all (since "table" itself is a *present* key, missing sub-fields never
-- reach MockEnv's __index hook) -- the VM would then die deep inside its own
-- decode loop with a bare "attempt to call a nil value" and no diagnostic.
-- Mirroring the full real library here (like safe_string above) let a real
-- MoonSecV3 payload decode its entire constant pool instead of dying after
-- only a handful of bytes.
local safe_table = {}
for k, v in pairs(table) do
    safe_table[k] = v
end
safe_table.concat = table_concat

local MockEnv = {}
local safe_globals = {
    ["string"] = safe_string,
    ["table"] = safe_table,
    ["math"] = math,
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
    ["setmetatable"] = setmetatable,
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
    ["debug"] = debug,
    ["dofile"] = dofile,
    ["loadfile"] = loadfile,
    ["newproxy"] = newproxy,
    ["loadstring"] = function(s)
        -- We deliberately never fetch/execute the *real* remote content here
        -- inside the sandbox (that would mean running untrusted attacker-
        -- controlled code during analysis). But callers routinely expect
        -- this to return a real module (e.g. a UI library table with
        -- methods like .new(...)), so returning a bare no-op function would
        -- crash the very next statement that touches the "loaded module"
        -- with "attempt to index nil" and stop the trace dead. Returning a
        -- logging dummy instead lets the trace continue, revealing what the
        -- script does with it.
        --
        -- Separately: whatever this dummy stands in for has NO real name in
        -- the replay script we generate, so a naive reconstruction like
        -- `loadstring_result.new(...)` is an undefined global in a real
        -- executor -- guaranteed "attempt to index nil". We already know
        -- exactly how to *really* produce that value (either the literal
        -- source string, or -- the overwhelmingly common "hub script"
        -- pattern -- `loadstring(game:HttpGet(url))()`), so we emit a
        -- distinct trace line handing trace_to_lua.py that real, working
        -- bootstrap expression to splice in verbatim ahead of first use.
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
            print("LOADSTRING FUNCTION CALLED")
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
        -- A bare (undeclared-local) `_ENV` read compiles to an ordinary
        -- global lookup, same as any other identifier -- and obfuscators
        -- commonly stash it into a variable unconditionally (not just behind
        -- a `getfenv() or _ENV` fallback) for later self-checks. Silently
        -- resolving it to nil here fed those checks a value shaped nothing
        -- like a real environment table, which is exactly the kind of
        -- fingerprint an anti-tamper check is built to notice.
        if k == "_ENV" then
            return MockEnv
        end

        local exploit_funcs = {
            "getgc", "getinstances", "getnilinstances",
            "getloadedmodules", "getconnections", "firesignal", "fireclickdetector",
            "firetouchinterest", "isnetworkowner", "gethiddenproperty", "sethiddenproperty",
            "setsimulationradius", "rconsoleprint", "rconsolewarn", "rconsoleerr",
            "rconsoleinfo", "rconsolename", "rconsoleclear", "consoleprint", "consolewarn",
            "consoleerr", "consoleinfo", "consolename", "consoleclear", "warn", "print",
            "error", "debug", "clonefunction", "hookfunction", "newcclosure", "replaceclosure",
            "restoreclosure", "islclosure", "iscclosure", "checkcaller", "getnamecallmethod",
            "setnamecallmethod", "getrawmetatable", "setrawmetatable", "setreadonly",
            "isreadonly", "iswindowactive", "keypress", "keyrelease", "mouse1click",
            "mouse1press", "mouse1release", "mousescroll", "mousemoverel", "mousemoveabs",
            "hookmetamethod", "getcallingscript", "makefolder", "writefile", "readfile",
            "appendfile", "loadfile", "listfiles", "isfile", "isfolder", "delfile",
            "delfolder", "dofile", "bit", "bit32",
            "Vector2", "Vector3", "CFrame", "UDim", "UDim2", "Color3", "Instance", "Ray",
            "Enum", "BrickColor", "NumberRange", "NumberSequence", "ColorSequence",
            "task", "coroutine", "Delay", "delay", "Spawn", "spawn", "Wait", "wait",
            "workspace", "Workspace", "tick", "time", "elapsedTime", "utf8"
        }
        for _, name in ipairs(exploit_funcs) do
            if k == name then
                print("ACCESSED --> " .. k)
                return create_dummy(k)
            end
        end

        print("ACCESSED (NIL) --> " .. k)
        return nil
    end,

    __newindex = function(t, k, v)
        -- recursive_tostring already produces a properly quote/backslash/
        -- newline-escaped Lua string literal for strings (via
        -- escape_lua_string) and a real table constructor for plain tables.
        -- The previous naive '"' .. v .. '"' wrapping here broke (produced
        -- outright invalid Lua) the instant a captured string contained a
        -- '"', a backslash, or a raw newline -- routine for the encoded
        -- string blobs MoonSecV3 stores in globals.
        local val_str = recursive_tostring(v, 0)
        print("SET GLOBAL --> " .. tostring(k) .. " = " .. val_str)
        rawset(t, k, v)
    end
})

safe_globals["_G"] = MockEnv
safe_globals["shared"] = MockEnv

-- IMPORTANT: `local _ENV = MockEnv` (the Lua 5.2+/Luau-manual-documented way to
-- sandbox an environment) does NOT reliably route bare global reads/writes
-- through this table's metamethods in this Luau build -- verified empirically:
-- writes/reads inside nested closures (e.g. a callback passed to string.gsub)
-- silently hit the *real* global table instead, invisibly to every hook above.
-- `setfenv(1, MockEnv)` is Luau's actual working mechanism: it sets the real
-- environment of the running chunk, and every closure defined from here on
-- (including deeply nested ones) inherits it correctly, exactly like classic
-- Lua 5.1 getfenv/setfenv semantics. This is why real MoonSecV3 payloads
-- looked like they stopped early: the obfuscator's own integrity check reads
-- back a value it set via a bare global inside a gsub callback, which was
-- silently going to the real environment and reading back nil here -- causing
-- the script to (correctly, from its own point of view) treat the sandbox as
-- tampered and bail out before running its real logic.
setfenv(1, MockEnv);
local function getfenv(...)
    return MockEnv
end;
"""


def deobfuscate_file(filepath, output_dir=None):
    print(f"Processing {filepath}...")

    if ".deobf." in filepath or ".report." in filepath:
        return

    output_dir = output_dir or DEFAULT_OUTPUT_DIR
    os.makedirs(output_dir, exist_ok=True)

    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
        return

    content = normalize_luau_syntax(content)

    idx_args = content.rfind("(getfenv")
    if idx_args == -1:
        idx_args = content.rfind("( getfenv")
    if idx_args == -1:
        idx_args = len(content)

    idx_ret = content.rfind("return(function", 0, idx_args)
    if idx_ret == -1:
        idx_ret = content.rfind("return (function", 0, idx_args)
    if idx_ret == -1:
        print(f"Could not find a return(function ...) injection point in {filepath}; "
              f"this doesn't look like a MoonSecV3-wrapped script.")
        return

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
        "end)\n"
    )

    new_content = MOCK_ENV_CODE + wrapped_target

    if "getfenv and getfenv()or _ENV" in new_content:
        new_content = new_content.replace("getfenv and getfenv()or _ENV", "MockEnv")
    else:
        new_content = re.sub(r"getfenv\s+and\s+getfenv\(\)or\s+_ENV", "MockEnv", new_content)

    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", suffix=".lua", delete=False
    ) as temp_handle:
        temp_file = temp_handle.name
        temp_handle.write(new_content)

    print(f"Executing MoonSecV3 sandbox for {filepath}...")

    cmd = [get_luau_executable(), temp_file, "-a", "1"]
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    RELEVANT_PREFIXES = (
        "ACCESSED", "CALL_RESULT", "URL DETECTED", "SET GLOBAL",
        "UNPACK CALLED", "CAPTURED CHUNK", "CLOSURE", "TRACE_PRINT",
        "PROP_SET", "LOADSTRING", "RUNTIME_ERROR", "TRACEBACK",
        "LOADSTRING BOOTSTRAP",
    )

    stdout_lines = []
    stdout_data = b""
    err = b""
    try:
        stdout_data, err = process.communicate(timeout=30)
    except subprocess.TimeoutExpired as exc:
        print("Timeout reached.")
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
            stdout_lines.append(line.strip())
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
                    "running your script. This usually means the pasted/target text has "
                    "already been run through another 'deobfuscator' (e.g. a regex-based "
                    "tool like pol.py) that mangled variable names into invalid syntax. "
                    "Paste the ORIGINAL, unmodified obfuscated script instead."
                )

    trace_lines = [
        line for line in stdout_lines
        if any(prefix in line for prefix in RELEVANT_PREFIXES)
    ]

    if not trace_lines and not err:
        print(
            "NOTE: the sandbox ran with no errors but captured no trace activity at all. "
            "That's unusual for a real MoonSecV3 payload -- double check the target box "
            "actually contains the obfuscated script (not something already processed)."
        )

    report_file = os.path.join(output_dir, os.path.basename(filepath) + ".report.txt")
    with open(report_file, "w", encoding="utf-8") as f:
        f.write("--- MOONSECV3 DEOBFUSCATION REPORT ---\n")
        f.write(f"File: {filepath}\n\n")
        f.write("--- TRACE ---\n")
        for line in trace_lines:
            f.write(line + "\n")

    print(f"Report saved to {report_file}")

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
            if "temp_deob" in file or ".report.txt" in file or ".deobf." in file:
                continue
            deobfuscate_file(file, output_dir)
            print("-" * 40)
    else:
        print("Invalid path")


if __name__ == "__main__":
    main()
