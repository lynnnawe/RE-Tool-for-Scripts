local realprint, realwarn = print, warn
local realtype, realtostring = type, tostring
local sformat, sgsub, sbyte, ssub, srep = string.format, string.gsub, string.byte, string.sub, string.rep
local PAD = "[dump-pad] " .. srep(".", 4096)

local BUDGET = 30
local deadline = os.clock() + BUDGET
local function guard()
	if os.clock() > deadline then error("[execenv] time budget reached", 0) end
end

local function esc(s)
	s = sgsub(s, "[^\32-\126]", function(c) return sformat("\\x%02X", sbyte(c)) end)
	if #s > 2000 then s = ssub(s, 1, 2000) .. sformat("...<%d bytes>", #s) end
	return s
end
local function out(tag, s)
	realprint("[" .. tag .. "] " .. s)
	realprint(PAD)
end
local function argstr(...)
	local parts, n = {}, select("#", ...)
	for i = 1, n do
		local v = select(i, ...)
		local t = realtype(v)
		if t == "string" then parts[i] = '"' .. esc(v) .. '"'
		elseif t == "number" or t == "boolean" or t == "nil" then parts[i] = realtostring(v)
		else parts[i] = "<" .. t .. ">" end
	end
	return table.concat(parts, ", ", 1, n)
end

local G = getfenv(0)

local stubs = {}
local function makestub(name)
	if stubs[name] then return stubs[name] end
	local s = setmetatable({}, {
		__index = function(_, k) return makestub(name .. "." .. realtostring(k)) end,
		__newindex = function() end,
		__call = function(_, ...) out("api", name .. "(" .. argstr(...) .. ")") return makestub(name .. "()") end,
		__tostring = function() return "<" .. name .. ">" end,
		__concat = function(a, b) return realtostring(a) .. realtostring(b) end,
		__len = function() return 0 end,
	})
	stubs[name] = s
	return s
end

local FS = {}
local function fk(p) return (sgsub(realtostring(p), "\\", "/")) end
G.writefile = function(p, data) FS[fk(p)] = realtostring(data) out("fs", "write " .. realtostring(p) .. " (" .. #realtostring(data) .. " bytes)") end
G.appendfile = function(p, data) local k = fk(p) FS[k] = (FS[k] or "") .. realtostring(data) end
G.readfile = function(p) return FS[fk(p)] or "" end
G.isfile = function(p) return FS[fk(p)] ~= nil end
G.isfolder = function() return false end
G.makefolder = function() end
G.delfile = function(p) FS[fk(p)] = nil end
G.listfiles = function() local t = {} for k in pairs(FS) do t[#t + 1] = k end return t end

local function httpret(body)
	return { StatusCode = 200, StatusMessage = "OK", Success = true, Body = body or "", Headers = { ["content-type"] = "text/plain" } }
end
local function dorequest(opts)
	if realtype(opts) == "table" then
		out("http", realtostring(opts.Method or "GET") .. " " .. realtostring(opts.Url or opts.url or "?"))
		if opts.Body then out("http-body", esc(realtostring(opts.Body))) end
		if realtype(opts.Headers) == "table" then
			for k, v in pairs(opts.Headers) do out("http-header", realtostring(k) .. ": " .. realtostring(v)) end
		end
	end
	return httpret()
end
G.request = dorequest
G.http_request = dorequest
G.syn = { request = dorequest }
G.http = { request = dorequest }
local httpGetFn = function(_, url) out("http", "GET " .. realtostring(url or "?")) return "" end
G.httpget = function(url) out("http", "GET " .. realtostring(url or "?")) return "" end
G.HttpGet = G.httpget

local gameObj = setmetatable({}, {
	__index = function(_, k)
		if k == "HttpGet" or k == "HttpGetAsync" then return httpGetFn end
		if k == "GetService" then return function(_, name) out("service", realtostring(name)) return makestub("service." .. realtostring(name)) end end
		if k == "PlaceId" or k == "GameId" or k == "CreatorId" then return 0 end
		if k == "JobId" then return "" end
		return makestub("game." .. realtostring(k))
	end,
	__newindex = function() end,
	__tostring = function() return "game" end,
})
G.game = gameObj
G.Game = gameObj
G.workspace = makestub("workspace")
G.Workspace = G.workspace
G.Instance = makestub("Instance")
G.Enum = makestub("Enum")
G.Drawing = makestub("Drawing")
G.shared = {}

local genv = {}
G.getgenv = function() return genv end
G.getrenv = function() return G end
G.getreg = function() return {} end
G.getgc = function() return {} end
G.getinstances = function() return {} end
G.getnilinstances = function() return {} end
G.getloadedmodules = function() return {} end
G.getrunningscripts = function() return {} end
G.hookfunction = function(a) return a end
G.hookmetamethod = function() return function() end end
G.newcclosure = function(f) return f end
G.iscclosure = function() return false end
G.islclosure = function() return true end
G.isexecutorclosure = function() return true end
G.checkcaller = function() return true end
G.setreadonly = function() end
G.isreadonly = function() return false end
G.getrawmetatable = function(o) return getmetatable(o) end
G.setrawmetatable = function(o, mt) return setmetatable(o, mt) end
G.getnamecallmethod = function() return "" end
G.identifyexecutor = function() return "LynVM", "1.0" end
G.getexecutorname = function() return "LynVM" end
G.gethwid = function() return "LYNVM-EMULATED-HWID" end
G.setclipboard = function(s) out("clipboard", esc(realtostring(s))) end
G.messagebox = function() return 6 end
G.rconsoleprint = function(s) realprint(realtostring(s)) end
G.crypt = { base64encode = function(s) return s end, base64decode = function(s) return s end,
	base64 = { encode = function(s) return s end, decode = function(s) return s end } }

G.WebSocket = { connect = function(url)
	out("ws", "connect " .. realtostring(url))
	return { Send = function(_, m) out("ws-send", esc(realtostring(m))) end, Close = function() end,
		OnMessage = { Connect = function() return { Disconnect = function() end } end },
		OnClose = { Connect = function() return { Disconnect = function() end } end } }
end }
G.WebSocket.new = G.WebSocket.connect

local function runfn(f, ...) if realtype(f) == "function" then pcall(f, ...) end end
G.task = { wait = function() guard() return 0 end, spawn = function(f, ...) runfn(f, ...) end,
	defer = function(f, ...) runfn(f, ...) end, delay = function(_, f, ...) runfn(f, ...) end, cancel = function() end }
G.wait = function() guard() return 0 end
G.spawn = function(f) runfn(f) end
G.delay = function(_, f) runfn(f) end
G.tick = os.clock
G.time = os.clock
G.typeof = type

local realLoad = loadstring or load
G.loadstring = function(src, name)
	if realtype(src) == "string" then out("loadstring", sformat("%d bytes", #src)) end
	return realLoad(src, name)
end
G.load = G.loadstring

print = function(...) out("print", argstr(...)) end
warn = function(...) out("warn", argstr(...)) end

pcall(function()
	local mt = getmetatable(G)
	if realtype(mt) ~= "table" then mt = {} setmetatable(G, mt) end
	local old = mt.__index
	mt.__index = function(t, k)
		if old ~= nil then
			local v = (realtype(old) == "function") and old(t, k) or old[k]
			if v ~= nil then return v end
		end
		out("global", realtostring(k))
		return makestub(realtostring(k))
	end
end)

realprint("[execenv] mimicking executor environment (LynVM). running target...")
realprint(PAD)
