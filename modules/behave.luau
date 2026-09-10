local realprint = print
local realtype, realtostring = type, tostring
local sformat, sgsub, sbyte, srep, ssub = string.format, string.gsub, string.byte, string.rep, string.sub

local seen, lines = {}, 0

local function esc(s)
    s = sgsub(s, "[^\32-\126]", function(c) return sformat("\\x%02X", sbyte(c)) end)
    if #s > 400 then s = ssub(s, 1, 400) .. "..." end
    return s
end

local PAD = "[dump-pad] " .. srep(".", 8192)
local REPEATS, MAX_LINES = 3, 4000
local function log(msg)
    local c = (seen[msg] or 0) + 1
    seen[msg] = c
    if c > REPEATS or lines >= MAX_LINES then return end
    lines += 1
    realprint(sformat("%5d %s%s", lines, msg, c > 1 and sformat("   (x%d)", c) or ""))
    realprint(PAD)
    if lines == MAX_LINES then realprint("[LOG FULL]") realprint(PAD) end
end

local function argstr(...)
    local out, n = {}, select("#", ...)
    for i = 1, n do
        local a = select(i, ...)
        local t = realtype(a)
        if t == "string" then
            out[i] = '"' .. esc(a) .. '"'
        elseif t == "number" or t == "boolean" or t == "nil" then
            out[i] = realtostring(a)
        elseif t == "table" then
            local mt = getmetatable(a)
            out[i] = (mt and mt.__tostring) and realtostring(a) or "<table>"
        elseif t == "function" then
            out[i] = "<function>"
        else
            out[i] = "<" .. t .. ">"
        end
    end
    return table.concat(out, ", ", 1, n)
end

local sfind = string.find
local depth = 0
local RUNS_CALLBACKS = {
    ["task.spawn"] = true, ["task.defer"] = true, ["task.delay"] = true,
    ["task.wait"] = false, ["spawn"] = true, ["delay"] = true,
}

local G = getfenv(0)
local stubs = {}

local function makestub(name)
    if stubs[name] then return stubs[name] end
    local s = setmetatable({}, {
        __index = function(_, k)
            local key = name .. "." .. realtostring(k)
            log("INDEX  " .. key)
            return makestub(key)
        end,
        __newindex = function(_, k, v)
            log(sformat("SET    %s.%s = %s", name, realtostring(k), argstr(v)))
        end,
        __call = function(_, ...)
            log(sformat("CALL   %s(%s)", name, argstr(...)))
            if RUNS_CALLBACKS[name] or sfind(name, "Connect") or sfind(name, "Once") then
                for i = 1, select("#", ...) do
                    local a = select(i, ...)
                    if realtype(a) == "function" and depth < 8 then
                        depth += 1
                        local ok, err = pcall(a)
                        depth -= 1
                        if not ok then log("ERROR  in " .. name .. " callback: " .. esc(realtostring(err))) end
                    end
                end
            end
            return makestub(name .. "()")
        end,
        __tostring = function() return "<" .. name .. ">" end,
        __concat = function(a, b) return realtostring(a) .. realtostring(b) end,
        __len = function() return 0 end,
        __eq = function() return false end,
    })
    stubs[name] = s
    return s
end

local fakeenv = setmetatable({}, {
    __index = function(_, k)
        local v = G[k]
        if v ~= nil then return v end
        log("GLOBAL " .. realtostring(k))
        return makestub(realtostring(k))
    end,
    __newindex = function(t, k, v) rawset(t, k, v) end,
})

getfenv = function() return fakeenv end

for _, gname in ipairs({ "game", "workspace", "Instance", "Enum", "shared", "script", "Players", "ReplicatedStorage", "Vector3", "Vector2", "CFrame", "Color3", "UDim2" }) do
    if G[gname] == nil then G[gname] = makestub(gname) end
end
local function runfn(f, ...) if realtype(f) == "function" then pcall(f, ...) end end
G.task = G.task or { wait = function() return 0 end, spawn = function(f, ...) runfn(f, ...) end, defer = function(f, ...) runfn(f, ...) end, delay = function(_, f, ...) runfn(f, ...) end, cancel = function() end }
G.wait = G.wait or function() return 0 end
G.spawn = G.spawn or function(f) runfn(f) end
G.delay = G.delay or function(_, f) runfn(f) end
G.tick = G.tick or os.clock
G.typeof = G.typeof or realtype

print = function(...) log("PRINT  " .. argstr(...)) end
warn  = function(...) log("WARN   " .. argstr(...)) end

local function hook_loader(fn, nm)
    if realtype(fn) ~= "function" then return fn end
    return function(chunk, ...)
        if realtype(chunk) == "string" then
            realprint(srep("=", 70))
            realprint(sformat("[%s] %d bytes:", nm, #chunk))
            realprint(chunk)
            realprint(srep("=", 70))
            realprint("[dump-pad] " .. srep(".", 8192))
        end
        return fn(chunk, ...)
    end
end
loadstring = hook_loader(loadstring, "loadstring")
load = hook_loader(load, "load")
