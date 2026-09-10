local EMULATE_ROBLOX = true
local SHOW_BINARY = false
local DUMP_BUFFERS = true
local MIN_PRINTABLE = 0.75
local MAX_LEN = 8192
local TIME_BUDGET = 90

local real_string, real_table = string, table
local real_print, real_type, real_tostring = print, type, tostring
local real_compile = loadstring or load
local real_getfenv = getfenv
local sbyte, ssub, sformat, sgsub, srep = string.byte, string.sub, string.format, string.gsub, string.rep

local captured, seen, hits = {}, {}, 0
local MIN_LEN = { default = 6, sub = 12, char = 3, concat = 4, unpack = 4, gsub = 8, rep = 8, buffer = 4, arg = 1, api = 1 }

local clock = os.clock
local PAD = "[dump-pad] " .. srep(".", 8192)
local deadline = clock() + TIME_BUDGET
local tick, pending, last_emit, expired = 0, 0, clock(), false

local function flush() if pending > 0 then pending = 0 real_print(PAD) end end
local function budget_check()
	if expired then return end
	tick += 1
	if tick % 4096 ~= 0 then return end
	local now = clock()
	if pending > 0 and now - last_emit > 2 then flush() end
	if now > deadline then
		expired = true
		real_print(sformat("[+] time budget (%ds) reached, %d unique strings captured", TIME_BUDGET, hits))
		pending = 1 flush()
	end
end

local function escape(s) return (sgsub(s, "[^\32-\126]", function(c) return sformat("\\x%02X", sbyte(c)) end)) end
local function is_printable(s)
	local good = 0
	for i = 1, #s do
		local b = sbyte(s, i)
		if (b >= 32 and b <= 126) or b == 9 or b == 10 or b == 13 then good += 1 end
	end
	return good / #s >= MIN_PRINTABLE
end

local function emit(tag, s)
	if expired then return end
	if real_type(s) ~= "string" then return end
	if #s < (MIN_LEN[tag] or MIN_LEN.default) then return end
	if seen[s] then return end
	if not SHOW_BINARY and not is_printable(s) then return end
	seen[s] = true
	hits += 1
	local shown = s
	if #s > MAX_LEN then shown = ssub(s, 1, MAX_LEN) .. sformat("...<truncated, %d bytes total>", #s) end
	local line = sformat("[%s] %s", tag, escape(shown))
	captured[#captured + 1] = line
	real_print(line)
	pending += 1
	last_emit = clock()
end

local function wrap1(fn, tag)
	if real_type(fn) ~= "function" then return fn end
	return function(...) budget_check() local a = fn(...) emit(tag, a) return a end
end
local function wrap2(fn, tag)
	if real_type(fn) ~= "function" then return fn end
	return function(...) budget_check() local a, b = fn(...) emit(tag, a) return a, b end
end
local tpack, tunpack = real_table.pack, real_table.unpack
local function wrapn(fn, tag)
	if real_type(fn) ~= "function" then return fn end
	return function(...) budget_check() local res = tpack(fn(...)) for i = 1, res.n do emit(tag, res[i]) end return tunpack(res, 1, res.n) end
end

local hooked_string = {}
for k, v in pairs(real_string) do hooked_string[k] = v end
hooked_string.char = wrap1(real_string.char, "char")
hooked_string.sub = wrap1(real_string.sub, "sub")
hooked_string.rep = wrap1(real_string.rep, "rep")
hooked_string.gsub = wrap2(real_string.gsub, "gsub")
hooked_string.unpack = wrapn(real_string.unpack, "unpack")

local hooked_table = {}
for k, v in pairs(real_table) do hooked_table[k] = v end
hooked_table.concat = wrap1(real_table.concat, "concat")

local dumped_buf, nbufs = {}, 0
local function hexdump(b)
	if not DUMP_BUFFERS or dumped_buf[b] then return end
	dumped_buf[b] = true
	nbufs += 1
	local ok, s = pcall(buffer.tostring, b)
	if not ok then return end
	real_print(sformat("[BUF %d] length=%d", nbufs, #s))
	for i = 1, #s, 64 do
		local chunk = ssub(s, i, i + 63)
		real_print(sformat("[HEX %d %08d] %s", nbufs, i - 1, (sgsub(chunk, ".", function(c) return sformat("%02x", sbyte(c)) end))))
	end
	real_print(sformat("[BUF %d END]", nbufs))
	real_print(PAD)
end

local hooked_buffer = nil
if real_type(buffer) == "table" then
	hooked_buffer = {}
	for k, v in pairs(buffer) do hooked_buffer[k] = v end
	hooked_buffer.tostring = wrap1(buffer.tostring, "buffer")
	hooked_buffer.readstring = wrap1(buffer.readstring, "buffer")
	for _, name in ipairs({ "readu8", "readu16", "readu32", "readf32", "readf64", "readstring" }) do
		local fn = buffer[name]
		if type(fn) == "function" then hooked_buffer[name] = function(b, ...) hexdump(b) budget_check() local r = fn(b, ...) if name == "readstring" then emit("buffer", r) end return r end end
	end
	if type(buffer.fromstring) == "function" then hooked_buffer.fromstring = function(s) local b = buffer.fromstring(s) hexdump(b) return b end end
end

local function hook_loader(fn, name)
	if real_type(fn) ~= "function" then return fn end
	return function(chunk, ...)
		if real_type(chunk) == "string" then
			real_print(srep("=", 70))
			real_print(sformat("[%s] payload, %d bytes:", name, #chunk))
			real_print(chunk)
			real_print(srep("=", 70))
			captured[#captured + 1] = sformat("[%s] payload, %d bytes:\n%s", name, #chunk, chunk)
		end
		return fn(chunk, ...)
	end
end

string = hooked_string
table = hooked_table
if hooked_buffer then buffer = hooked_buffer end
loadstring = hook_loader(loadstring, "loadstring")
load = hook_loader(load, "load")
print = function() end
warn = function() end

if EMULATE_ROBLOX then
	local G = real_getfenv(0)
	local stubs = {}
	local function makestub(name)
		if stubs[name] then return stubs[name] end
		local s = setmetatable({}, {
			__index = function(_, k) budget_check() local key = name .. "." .. real_tostring(k) emit("api", key) return makestub(key) end,
			__newindex = function() end,
			__call = function(_, ...)
				budget_check() emit("api", name .. "()")
				for i = 1, select("#", ...) do local a = select(i, ...) if real_type(a) == "string" then emit("arg", a) end end
				return makestub(name .. "()")
			end,
			__tostring = function() return "<stub " .. name .. ">" end,
			__concat = function(a, b) return real_tostring(a) .. real_tostring(b) end,
			__len = function() return 0 end,
		})
		stubs[name] = s
		return s
	end
	local fakeenv = setmetatable({}, {
		__index = function(_, k) local v = G[k] if v ~= nil then return v end return makestub(real_tostring(k)) end,
		__newindex = function(t, k, v) rawset(t, k, v) end,
	})
	getfenv = function() return fakeenv end

	for _, gname in ipairs({ "game", "workspace", "Instance", "Enum", "shared", "script", "Players", "ReplicatedStorage", "Vector3", "Vector2", "CFrame", "Color3", "UDim2", "Ray", "Region3" }) do
		if G[gname] == nil then G[gname] = makestub(gname) end
	end
	local function runfn(f, ...) if real_type(f) == "function" then pcall(f, ...) end end
	G.task = G.task or { wait = function() return 0 end, spawn = function(f, ...) runfn(f, ...) end, defer = function(f, ...) runfn(f, ...) end, delay = function(_, f, ...) runfn(f, ...) end, cancel = function() end }
	G.wait = G.wait or function() return 0 end
	G.spawn = G.spawn or function(f) runfn(f) end
	G.delay = G.delay or function(_, f) runfn(f) end
	G.tick = G.tick or os.clock
	G.time = G.time or os.clock
	G.typeof = G.typeof or type
end

function __PC() end
function __T() end
