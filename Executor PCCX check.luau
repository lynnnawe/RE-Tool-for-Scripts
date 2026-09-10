--!nonstrict
local ECHO_TEST = false
local ECHO_URL  = "http://127.0.0.1:8787/audit"

local scopes = {}
do
	local function add(getter)
		if type(getter) == "function" then
			local ok, v = pcall(getter)
			if ok and type(v) == "table" then scopes[#scopes + 1] = v end
		end
	end
	add(getgenv)
	add(getrenv)
	if getfenv then local ok, v = pcall(getfenv, 0) if ok and type(v) == "table" then scopes[#scopes + 1] = v end end
	if type(_G) == "table" then scopes[#scopes + 1] = _G end
end
local env = scopes[1] or _G or getfenv(0)

local function G(n)
	for _, sc in ipairs(scopes) do
		local ok, v = pcall(function() return sc[n] end)
		if ok and v ~= nil then return v end
	end
	return nil
end

local function resolve(names)
	for _, nm in ipairs(names) do
		local dot = string.find(nm, ".", 1, true)
		if dot then
			local t = G(string.sub(nm, 1, dot - 1))
			if type(t) == "table" then
				local ok, f = pcall(function() return t[string.sub(nm, dot + 1)] end)
				if ok and f ~= nil then return f end
			end
		else
			local v = G(nm)
			if v ~= nil then return v end
		end
	end
	return nil
end

local function try(f, ...)
	if type(f) ~= "function" then return false, "<not available>" end
	local ok, r = pcall(f, ...)
	return ok, r
end

local F = {
	request      = resolve({ "request", "http_request", "syn.request", "http.request", "fluxus.request", "krnl.request" }),
	httpget      = resolve({ "httpget", "HttpGet", "syn.http_get" }),
	gethwid      = resolve({ "gethwid", "get_hwid" }),
	identify     = resolve({ "identifyexecutor", "getexecutorname" }),
	websocket    = resolve({ "WebSocket", "syn.websocket", "websocket" }),
	rconsole     = resolve({ "rconsoleprint", "printconsole", "consoleprint" }),
	listfiles    = resolve({ "listfiles" }),
	isfolder     = resolve({ "isfolder" }),
	isfile       = resolve({ "isfile" }),
	readfile     = resolve({ "readfile" }),
	writefile    = resolve({ "writefile" }),
	delfile      = resolve({ "delfile", "delfile" }),
}

local lines = {}
local function log(s)
	s = tostring(s)
	print(s)
	if F.rconsole then pcall(F.rconsole, s .. "\n") end
	lines[#lines + 1] = s
end
local function logf(...) log(string.format(...)) end
local function kv(k, v) logf("  %-24s %s", k, tostring(v)) end
local function rule(t)
	log("")
	log(string.rep("=", 72))
	if t then log("  " .. t) log(string.rep("=", 72)) end
end

local exeName, exeVer = "Executor", ""
if F.identify then
	local ok, a, b = pcall(F.identify)
	if ok then
		if type(a) == "string" and a ~= "" then exeName = a end
		if type(b) == "string" then exeVer = b end
	end
end

rule(exeName:upper() .. " SELF-AUDIT  " .. os.date("%Y-%m-%d %H:%M:%S"))
log("  Read-only except two write probes inside the workspace, cleaned up after.")

rule("1. EXECUTOR IDENTITY")
do
	kv("identifyexecutor()", exeName .. "  " .. exeVer)
	local ok, n = try(resolve({ "getexecutorname" })) kv("getexecutorname()", n)
	kv("_VERSION", _VERSION)
end

rule("2. MACHINE IDENTITY -- what can leave your PC")
do
	local ok, hwid = try(F.gethwid)
	kv("gethwid()", hwid)
	if ok and type(hwid) == "string" then logf("  %-24s %d chars", "length", #hwid) end
	log("")
	log("  A hardware id typically hashes stable machine facts (CPU id, volume")
	log("  serials, computer name, BIOS/motherboard strings). It survives an OS")
	log("  reinstall and uniquely identifies this PC.")
	log("")
	local _, uid = try(resolve({ "get_user_identity" })) kv("get_user_identity()", uid)
	local _, tid = try(resolve({ "getthreadidentity", "getidentity" })) kv("getthreadidentity()", tid)
end

rule("3. ROBLOX IDENTITY -- same as any LocalScript sees")
do
	local ok, Players = pcall(game.GetService, game, "Players")
	local lp = ok and Players.LocalPlayer or nil
	if lp then
		kv("UserId", lp.UserId)
		kv("Name", lp.Name)
		kv("DisplayName", lp.DisplayName)
		kv("AccountAge (days)", lp.AccountAge)
		pcall(function() kv("MembershipType", lp.MembershipType) end)
		pcall(function() kv("LocaleId", lp.LocaleId) end)
	else kv("LocalPlayer", "<none>") end
	kv("game.PlaceId", game.PlaceId)
	kv("game.GameId", game.GameId)
	kv("game.JobId", game.JobId ~= "" and game.JobId or "<studio/none>")
	pcall(function()
		local c = workspace.CurrentCamera
		kv("Viewport (px)", string.format("%d x %d", c.ViewportSize.X, c.ViewportSize.Y))
	end)
end

rule("4. HEADERS ADDED TO EVERY request() CALL")
log("  Many executors attach identifying headers to every request() automatically,")
log("  such as a machine fingerprint, an account/user id, and a User-Agent naming")
log("  the executor. The only reliable way to see what THIS one adds is to echo them.")
log("")
if ECHO_TEST then
	local ok, res = try(F.request, { Url = ECHO_URL, Method = "GET" })
	if ok and type(res) == "table" then
		kv("StatusCode", res.StatusCode)
		log("  --- headers the server actually received ---")
		for l in tostring(res.Body or ""):gmatch("[^\r\n]+") do log("    " .. l) end
	else
		log("  request failed: " .. tostring(res) .. "  (is your listener up?)")
	end
else
	log("  ECHO_TEST is off. To prove it: run a local HTTP listener that echoes request")
	log("  headers on 127.0.0.1:8787, set ECHO_TEST = true, re-run. Keep it LOCAL.")
end

rule("5. FILESYSTEM ACCESS")
log("  Sandbox root: the executor's own workspace folder (readfile/writefile scope).")
log("")
local files, folders = {}, {}
if F.listfiles then
	local function walk(p, d)
		if d > 4 then return end
		local ok, ents = pcall(F.listfiles, p)
		if not ok or type(ents) ~= "table" then return end
		for _, e in ipairs(ents) do
			local isdir = false
			if F.isfolder then local o, r = pcall(F.isfolder, e) isdir = o and r or false end
			if isdir then folders[#folders + 1] = e walk(e, d + 1)
			else files[#files + 1] = e end
		end
	end
	for _, r in ipairs({ "", ".", "/" }) do
		local ok, ents = pcall(F.listfiles, r)
		if ok and type(ents) == "table" and #ents > 0 then walk(r, 1) break end
	end
	kv("folders visible", #folders)
	kv("files readable", #files)
	log("")
	log("  All readable, writable and deletable by any script:")
	for i, f in ipairs(files) do
		if i > 40 then logf("    ... and %d more", #files - 40) break end
		log("    " .. f)
	end
	if F.readfile then
		for _, f in ipairs(files) do
			if f:match("%.json$") or f:match("%.txt$") then
				local ok, data = pcall(F.readfile, f)
				if ok and type(data) == "string" and #data < 20000 then
					log("")
					logf("  Read proof: %s  (%d bytes)", f, #data)
					log("    " .. data:sub(1, 120):gsub("[\r\n]", " "))
					break
				end
			end
		end
	end
else log("  listfiles unavailable") end

rule("6. SANDBOX ESCAPE TESTS -- these SHOULD all fail")
do
	local rf = F.readfile
	local function probe(p)
		local ok, r = pcall(rf, p)
		local kind = ok and type(r) or "error"
		local n = (ok and type(r) == "string") and #r or 0
		logf("  %-50s type=%-7s bytes=%d", p:sub(1, 50), kind, n)
		return n > 0
	end
	if not rf then
		log("  readfile unavailable -- cannot test.")
	else
		log("  CONTROLS")
		local posBytes = 0
		if files[1] then
			local ok, r = pcall(rf, files[1])
			posBytes = (ok and type(r) == "string") and #r or 0
			logf("  %-50s type=%-7s bytes=%d  <- inside sandbox, must be > 0",
				("POSITIVE: " .. files[1]):sub(1, 50), ok and type(r) or "error", posBytes)
		end
		probe("_no_such_file_xyz.txt")
		log("               ^ nonexistent, inside sandbox. This is what failure looks like.")
		log("")
		log("  ESCAPE ATTEMPTS (each targets a file that really exists)")
		local escaped = false
		for _, p in ipairs({
			"../settings.json",
			"../../Google/Chrome/User Data/Default/Login Data",
			"../../../../../../Windows/win.ini",
			"..\\..\\..\\..\\..\\..\\Windows\\win.ini",
			"C:/Windows/win.ini",
			"C:\\Windows\\win.ini",
			"....//....//Windows/win.ini",
		}) do
			if probe(p) then escaped = true end
		end
		log("")
		if posBytes == 0 then
			log("  VERDICT: INCONCLUSIVE -- even the in-sandbox read returned nothing.")
		elseif escaped then
			log("  VERDICT: SANDBOX BROKEN -- an escape returned real file contents.")
		else
			log("  VERDICT: SANDBOX HOLDS -- in-sandbox read returned bytes, every")
			log("           escape returned nothing, same as the nonexistent-file control.")
		end
	end
end

rule("7. WRITE PROBES -- extension blocklist, cleans up after itself")
do
	local wf, df, isf = F.writefile, F.delfile, F.isfile
	if not wf then
		log("  writefile unavailable -- cannot test.")
	else
		local ok, err = try(wf, "_audit_probe.txt", "ok")
		if ok then
			log("  allowed      _audit_probe.txt written")
			if isf then local _, e = try(isf, "_audit_probe.txt") kv("isfile()", e) end
			local d = try(df, "_audit_probe.txt")
			log("  cleanup      " .. (d and "deleted" or "delete FAILED"))
		else log("  write failed: " .. tostring(err)) end
		log("")
		log("  Blocked extensions (all should fail):")
		for _, ext in ipairs({ "exe", "bat", "cmd", "ps1", "vbs", "msi", "scr", "hta", "com", "wsf" }) do
			local n = "_audit_probe." .. ext
			local w, e = try(wf, n, "x")
			local created = false
			if isf then local _, c = try(isf, n) created = c == true end
			if created then
				logf("  !! ALLOWED   .%-4s file was actually created -- REPORT THIS", ext)
				pcall(df, n)
			else
				logf("  blocked      .%-4s -> %s", ext, w and "no error, but no file created" or tostring(e):sub(1, 45))
			end
		end
	end
end

rule("8. CAPABILITY PROBE")
local groups = {
	{ "FILESYSTEM", { "readfile","writefile","appendfile","loadfile","dofile","listfiles",
		"isfile","isfolder","makefolder","delfile","delfolder","saveinstance","getcustomasset" } },
	{ "NETWORK", { "httpget","HttpGet","request","http_request","syn.request","WebSocket","getobjects" } },
	{ "MACHINE ID", { "gethwid","get_hwid","get_user_identity","identifyexecutor","getexecutorname" } },
	{ "INPUT INJECTION", { "keypress","keyrelease","keytap","keyclick","mouse1click","mouse1press",
		"mouse1release","mouse2click","mouse2press","mouse2release","mousemoveabs","mousemoverel",
		"mousescroll","isrbxactive","iswindowactive","isgameactive" } },
	{ "CLIPBOARD", { "setclipboard","toclipboard","setrbxclipboard","getclipboard","get_clipboard" } },
	{ "VM INTERNALS", { "getgenv","getrenv","getreg","getgc","gettenv","getsenv","filtergc",
		"hookfunction","hookmetamethod","restorefunction","getrawmetatable","setrawmetatable",
		"setreadonly","isreadonly","newcclosure","iscclosure","islclosure","isexecutorclosure",
		"getnamecallmethod","setnamecallmethod","loadstring" } },
	{ "SCRIPT / BYTECODE", { "decompile","dumpbytecode","getscriptbytecode","getscriptclosure",
		"getscripthash","getscripts","getrunningscripts","getloadedmodules","getcallingscript",
		"getthreadidentity","setthreadidentity" } },
	{ "OBJECT MODEL", { "getinstances","getnilinstances","gethui","cloneref","cache","getproperties",
		"gethiddenproperty","sethiddenproperty","isscriptable","setscriptable","getconnections",
		"firesignal","replicatesignal","fireclickdetector","fireproximityprompt","firetouchinterest",
		"getsimulationradius","setsimulationradius","isnetworkowner" } },
	{ "DRAWING / RAKNET / MISC", { "Drawing","DrawingImmediate","raknet","crypt","Regex",
		"rconsoleprint","rconsoleinput","messagebox","setfflag","getfflag","setfpscap",
		"queueonteleport","Signal","getactors","run_on_actor","is_parallel" } },
	{ "PROCESS / SYSTEM (often absent)", { "getenv","getprocesses","listprocesses","shellexecute","execute",
		"createprocess","screenshot","capturescreen","getcookies","getauthcookie","readregistry",
		"writeregistry","getclipboard" } },
}
local present, absent = 0, 0
for _, grp in ipairs(groups) do
	log("")
	log("  [" .. grp[1] .. "]")
	local row = {}
	for _, n in ipairs(grp[2]) do
		local ok = resolve({ n }) ~= nil
		if ok then present = present + 1 else absent = absent + 1 end
		row[#row + 1] = string.format("%s%-24s", ok and "+" or "-", n)
		if #row == 2 then log("    " .. table.concat(row, " ")) row = {} end
	end
	if #row > 0 then log("    " .. table.concat(row, " ")) end
end
log("")
logf("  + present, - absent      (%d present, %d absent)", present, absent)

rule("9. SUMMARY")
logf("  Executor: %s %s", exeName, exeVer)
log("")
log("  Capabilities depend on what the probe above found present. In general an")
log("  executor of this kind CAN, at minimum:")
log("    - fingerprint this machine if gethwid is present")
log("    - read/rewrite/delete everything in its workspace folder")
log("    - read your full Roblox identity and current game session")
log("    - attach identifying headers to outbound request() calls")
log("  and CANNOT read outside the sandbox unless section 6 says the sandbox broke.")

rule()
logf("  Audit complete -- %d lines.", #lines)
if F.writefile then
	pcall(function()
		F.writefile("audit_output.txt", table.concat(lines, "\n"))
		log("  Saved to workspace/audit_output.txt")
	end)
end
