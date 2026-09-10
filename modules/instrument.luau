local MODE = MODE or "full"
local SCRIPT_KEY = SCRIPT_KEY or ""
local LIVE_URL = LIVE_URL or ""
local RUN_SECONDS = RUN_SECONDS or 90
local TARGET_SOURCE = TARGET_SOURCE or ""
local MAX_LINES = 40000
local MAX_REPEATS = 6
local MAX_ARG_LEN = 4000
local MAX_BYTES = 8 * 1024 * 1024

local counts = { calls = 0, instances = 0, globals = 0, payloads = 0, args = 0 }
local repeats = {}
local seenPayload = {}
local inHook = false

local function ours()
	if not EXE.checkcaller then return true end
	local ok, v = pcall(EXE.checkcaller)
	return (not ok) or v
end

local function shorten(s)
	if #s > MAX_ARG_LEN then return s:sub(1, MAX_ARG_LEN) .. ("...<%d bytes>"):format(#s) end
	return s
end

local function fmt(v)
	local ok, t = pcall(typeof, v)
	if not ok then t = type(v) end
	if t == "string" then
		return '"' .. shorten((v:gsub("[^\32-\126]", function(c) return ("\\x%02X"):format(c:byte()) end))) .. '"'
	elseif t == "number" or t == "boolean" or t == "nil" then
		return tostring(v)
	elseif t == "Instance" then
		local okc, class = pcall(function() return v.ClassName end)
		local okn, name = pcall(function() return v.Name end)
		return ("Instance<%s %q>"):format(okc and class or "?", okn and tostring(name) or "?")
	elseif t == "table" then
		local parts, n = {}, 0
		for k, val in pairs(v) do
			n += 1
			if n > 8 then parts[#parts + 1] = "..." break end
			local okk, kv = pcall(tostring, k)
			local okv, vv = pcall(tostring, val)
			parts[#parts + 1] = (okk and kv or "?") .. "=" .. (okv and vv or "?")
		end
		return "{" .. table.concat(parts, ", ") .. "}"
	elseif t == "function" then
		return "<function>"
	end
	local ok3, s = pcall(tostring, v)
	return t .. "(" .. (ok3 and s or "?") .. ")"
end

local function fmtArgs(...)
	local out, n = {}, select("#", ...)
	for i = 1, n do out[i] = fmt((select(i, ...))) end
	return table.concat(out, ", ", 1, n)
end

local function fmtArgsFull(...)
	local out, n = {}, select("#", ...)
	for i = 1, n do
		local v = select(i, ...)
		out[i] = (type(v) == "string") and v or (select(2, pcall(tostring, v)) or "?")
	end
	return table.concat(out, "\n---\n", 1, n)
end

local buffers = { calls = {}, instances = {}, globals = {}, args = {} }
local function put(name, line)
	counts[name] = (counts[name] or 0) + 1
	if counts[name] > MAX_LINES then return end
	local r = (repeats[line] or 0) + 1
	repeats[line] = r
	if r > MAX_REPEATS then return end
	local t = buffers[name]
	t[#t + 1] = (r > 1) and (line .. ("   (x%d)"):format(r)) or line
	if #t >= 200 then APPEND(name .. ".log", table.concat(t, "\n") .. "\n") table.clear(t) end
end
local function flushall()
	for name, t in pairs(buffers) do
		if #t > 0 then APPEND(name .. ".log", table.concat(t, "\n") .. "\n") table.clear(t) end
	end
end

local function savePayload(src, origin)
	if type(src) ~= "string" or #src == 0 or #src > MAX_BYTES or seenPayload[src] then return end
	seenPayload[src] = true
	counts.payloads += 1
	local n = counts.payloads
	SAVE(("payload_%d.lua"):format(n), src)
	APPEND("index.log", ("payload_%d  %d bytes via %s  | %s\n"):format(n, #src, origin, (src:sub(1, 80):gsub("[^\32-\126]", "."))))
	LOGF("[+] captured payload %d (%d bytes) via %s", n, #src, origin)
end

local function cclosure(fn)
	if EXE.newcclosure then
		local ok, w = pcall(EXE.newcclosure, fn)
		if ok then return w end
	end
	return fn
end

local function wrapChunk(chunk, n)
	if type(chunk) ~= "function" then return chunk end
	return function(...)
		local a = table.pack(...)
		local ok, line = pcall(function() return ("payload_%d called with (%s)"):format(n, fmtArgs(table.unpack(a, 1, a.n))) end)
		if ok then put("args", line) LOG("[+] " .. line) end
		local okf, full = pcall(function() return ("=== payload_%d arguments (%d) ===\n%s"):format(n, a.n, fmtArgsFull(table.unpack(a, 1, a.n))) end)
		if okf then put("args", full) end
		return chunk(table.unpack(a, 1, a.n))
	end
end

local real_loadstring = EXE.loadstring
local function install_loadstring_hook()
	if type(real_loadstring) ~= "function" then return end
	local replacement = function(src, chunkname)
		savePayload(src, "loadstring")
		local chunk, err = real_loadstring(src, chunkname)
		if chunk == nil then return chunk, err end
		return wrapChunk(chunk, counts.payloads)
	end
	if MODE == "stealth" and EXE.hookfunction then
		local ok, orig = pcall(EXE.hookfunction, real_loadstring, cclosure(replacement))
		if ok and type(orig) == "function" then real_loadstring = orig end
		LOG("[*] stealth: loadstring hooked in place (closure identity preserved).")
	else
		EXE.env.loadstring = cclosure(replacement)
	end
end

local restore = {}
local function install_meta_hooks()
	if MODE == "stealth" then return end
	if not (EXE.getrawmetatable and EXE.setreadonly) then
		LOG("[!] metatable hooks unavailable on this executor; capturing payloads only.")
		return
	end
	local real_new = Instance.new
	local ok = pcall(function()
		local hooked_new = cclosure(function(class, parent)
			put("instances", ("Instance.new(%s%s)"):format(fmt(class), parent and (", " .. fmt(parent)) or ""))
			return real_new(class, parent)
		end)
		local realInstance = Instance
		EXE.env.Instance = setmetatable({}, {
			__index = function(_, k) if k == "new" then return hooked_new end return realInstance[k] end,
			__newindex = function() end,
		})
	end)
	if not ok then LOG("[!] could not hook Instance.new") end

	pcall(function()
		local mt = EXE.getrawmetatable(game)
		EXE.setreadonly(mt, false)
		local old = mt.__namecall
		restore.namecall = function() pcall(function() EXE.setreadonly(mt, false) mt.__namecall = old EXE.setreadonly(mt, true) end) end
		mt.__namecall = cclosure(function(self, ...)
			if inHook or not ours() then return old(self, ...) end
			inHook = true
			local a = table.pack(...)
			local okm, method = pcall(function() return EXE.getnamecallmethod and EXE.getnamecallmethod() or "?" end)
			local okl, line = pcall(function() return ("%s:%s(%s)"):format(fmt(self), tostring(okm and method or "?"), fmtArgs(table.unpack(a, 1, a.n))) end)
			if okl then put("calls", line) end
			inHook = false
			return old(self, ...)
		end)
		EXE.setreadonly(mt, true)
	end)

	pcall(function()
		local mt = EXE.getrawmetatable(game)
		EXE.setreadonly(mt, false)
		local old = mt.__newindex
		restore.newindex = function() pcall(function() EXE.setreadonly(mt, false) mt.__newindex = old EXE.setreadonly(mt, true) end) end
		mt.__newindex = cclosure(function(self, k, v)
			if not inHook and ours() and (type(v) == "string" or type(v) == "number" or type(v) == "boolean") then
				inHook = true
				local okl, line = pcall(function() return ("SET %s.%s = %s"):format(fmt(self), tostring(k), fmt(v)) end)
				if okl then put("calls", line) end
				inHook = false
			end
			return old(self, k, v)
		end)
		EXE.setreadonly(mt, true)
	end)

	pcall(function()
		local mt = getmetatable(EXE.env)
		if type(mt) ~= "table" or rawget(mt, "__index") == nil then
			setmetatable(EXE.env, { __index = function(_, k) put("globals", tostring(k)) return nil end })
		end
	end)
end

LOG("========================================================================")
LOGF("  LYN DEBUG MULTITOOL -- INSTRUMENT (%s)  %s", MODE, os.date("%H:%M:%S"))
LOG("========================================================================")

install_loadstring_hook()
install_meta_hooks()

if SCRIPT_KEY ~= "" then EXE.env.script_key = SCRIPT_KEY end

local function run_source(label, src)
	if type(src) ~= "string" or #src == 0 then return end
	savePayload(src, label)
	local chunk, err = real_loadstring(src, label)
	if not chunk then LOG("[!] compile failed for " .. label .. ": " .. tostring(err)) return end
	task.spawn(function()
		local ok, e = pcall(wrapChunk(chunk, counts.payloads))
		if not ok then LOG("[!] runtime error in " .. label .. ": " .. tostring(e)) end
	end)
end

if LIVE_URL ~= "" then
	LOG("[*] fetching live loader: " .. LIVE_URL)
	local body = EXE.HttpGet(LIVE_URL)
	if type(body) == "string" and #body > 0 then
		run_source(LIVE_URL, body)
	else
		LOG("[!] HttpGet failed for " .. LIVE_URL)
	end
elseif TARGET_SOURCE ~= "" then
	LOG("[*] running embedded target source under hooks.")
	run_source("target", TARGET_SOURCE)
else
	LOG("[*] hooks installed. Now execute the target script normally -- its payloads and calls will be captured.")
end

task.spawn(function()
	local t0 = tick()
	while tick() - t0 < RUN_SECONDS do
		task.wait(2)
		flushall()
	end
	flushall()
	SAVELOG("instrument.log")
	LOGF("[+] done -- %d payloads, %d calls, %d instances captured -> %s/", counts.payloads, counts.calls, counts.instances, OUTDIR)
	for _, r in pairs(restore) do pcall(r) end
end)
