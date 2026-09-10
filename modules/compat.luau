local OWNER = OWNER or "Lyn"
local OUTDIR = OUTDIR or "lyn_debug"

local function _scopes()
	local s = {}
	if getgenv then local ok, v = pcall(getgenv) if ok and type(v) == "table" then s[#s + 1] = v end end
	if getrenv then local ok, v = pcall(getrenv) if ok and type(v) == "table" then s[#s + 1] = v end end
	local fe = (getfenv and getfenv(0)) or nil
	if type(fe) == "table" then s[#s + 1] = fe end
	if type(_G) == "table" then s[#s + 1] = _G end
	return s
end

local function _pick(names)
	local scopes = _scopes()
	for _, nm in ipairs(names) do
		local dot = string.find(nm, ".", 1, true)
		for _, sc in ipairs(scopes) do
			if dot then
				local a, b = string.sub(nm, 1, dot - 1), string.sub(nm, dot + 1)
				local ok, t = pcall(function() return sc[a] end)
				if ok and type(t) == "table" then
					local ok2, f = pcall(function() return t[b] end)
					if ok2 and f ~= nil then return f end
				end
			else
				local ok, v = pcall(function() return sc[nm] end)
				if ok and v ~= nil then return v end
			end
		end
	end
	return nil
end

local EXE = {}
EXE.env = (getgenv and getgenv()) or (getfenv and getfenv(0)) or _G
EXE.request = _pick({ "request", "http_request", "syn.request", "http.request", "fluxus.request", "krnl.request", "getobjects" })
EXE.httpget_fn = _pick({ "httpget", "HttpGet" })
EXE.readfile = _pick({ "readfile" })
EXE.writefile = _pick({ "writefile" })
EXE.appendfile = _pick({ "appendfile" })
EXE.isfile = _pick({ "isfile" })
EXE.isfolder = _pick({ "isfolder" })
EXE.makefolder = _pick({ "makefolder" })
EXE.delfile = _pick({ "delfile" })
EXE.listfiles = _pick({ "listfiles" })
EXE.loadstring = _pick({ "loadstring", "load" })
EXE.hookfunction = _pick({ "hookfunction", "replaceclosure", "detour", "hookfunc" })
EXE.newcclosure = _pick({ "newcclosure" })
EXE.getrawmetatable = _pick({ "getrawmetatable", "debug.getrawmetatable" })
EXE.setreadonly = _pick({ "setreadonly", "make_writeable", "makewriteable" })
EXE.getnamecallmethod = _pick({ "getnamecallmethod" })
EXE.setnamecallmethod = _pick({ "setnamecallmethod" })
EXE.checkcaller = _pick({ "checkcaller" })
EXE.getgc = _pick({ "getgc", "get_gc_objects", "getgarbage" })
EXE.getconstants = _pick({ "getconstants", "debug.getconstants" })
EXE.getupvalues = _pick({ "getupvalues", "debug.getupvalues" })
EXE.getreg = _pick({ "getreg", "debug.getregistry", "getregistry" })
EXE.gethwid = _pick({ "gethwid", "get_hwid" })
EXE.identify = _pick({ "identifyexecutor", "getexecutorname" })
EXE.WebSocket = _pick({ "WebSocket", "syn.websocket", "websocket" })
EXE.crypt = _pick({ "crypt" })
EXE.rconsoleprint = _pick({ "rconsoleprint", "printconsole", "consoleprint" })
EXE.messagebox = _pick({ "messagebox" })

EXE.HttpGet = function(url)
	if EXE.httpget_fn then
		local ok, r = pcall(EXE.httpget_fn, url)
		if ok and type(r) == "string" then return r end
	end
	local ok, r = pcall(function() return game:HttpGet(url) end)
	if ok then return r end
	return nil
end

local LOGLINES = {}
local function LOG(s)
	s = tostring(s)
	print(s)
	if EXE.rconsoleprint then pcall(EXE.rconsoleprint, s .. "\n") end
	LOGLINES[#LOGLINES + 1] = s
end
local function LOGF(...) LOG(string.format(...)) end

local function ENSURE()
	if EXE.isfolder and EXE.makefolder then
		pcall(function() if not EXE.isfolder(OUTDIR) then EXE.makefolder(OUTDIR) end end)
	end
end
local function SAVE(name, body)
	ENSURE()
	if EXE.writefile then pcall(EXE.writefile, OUTDIR .. "/" .. name, body) end
end
local function APPEND(name, body)
	ENSURE()
	if EXE.appendfile then
		pcall(EXE.appendfile, OUTDIR .. "/" .. name, body)
	elseif EXE.writefile and EXE.readfile and EXE.isfile then
		pcall(function()
			local p = OUTDIR .. "/" .. name
			local cur = EXE.isfile(p) and EXE.readfile(p) or ""
			EXE.writefile(p, cur .. body)
		end)
	elseif EXE.writefile then
		pcall(EXE.writefile, OUTDIR .. "/" .. name, body)
	end
end
local function SAVELOG(name) SAVE(name, table.concat(LOGLINES, "\n")) end

local function CONFIRM_OWNER()
	if EXE.messagebox then
		local prompt = "Lyn Debug Multitool\n\nThis will analyze a Roblox script for debugging / security review.\nAre you the owner of, or authorized to analyze, this script?"
		local ok, r = pcall(EXE.messagebox, prompt, "Authorization - owner: " .. OWNER, 4)
		if ok then
			if r == 6 or r == true or r == "Yes" or r == 1 then return true end
			return false
		end
	end
	LOG("[auth] no message window available on this executor; proceeding under asserted authorization (owner: " .. OWNER .. ").")
	return true
end

if not CONFIRM_OWNER() then
	LOG("[auth] authorization declined -- aborting.")
	error("Lyn Debug Multitool: authorization declined", 0)
end
