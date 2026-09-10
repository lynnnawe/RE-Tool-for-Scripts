local function try(f, ...)
	if type(f) ~= "function" then return false, "<not available>" end
	local ok, r = pcall(f, ...)
	return ok, r
end
local function G(n)
	local ok, v = pcall(function() return EXE.env[n] end)
	return ok and v or nil
end
local function logf(...) LOG(string.format(...)) end
local function kv(k, v) logf("  %-24s %s", k, tostring(v)) end
local function rule(t)
	LOG("")
	LOG(string.rep("=", 72))
	if t then LOG("  " .. t) LOG(string.rep("=", 72)) end
end

rule("LYN DEBUG MULTITOOL -- EXECUTOR SELF-AUDIT  " .. os.date("%Y-%m-%d %H:%M:%S"))

rule("1. EXECUTOR IDENTITY")
do
	if EXE.identify then
		local ok, a, b = pcall(EXE.identify)
		kv("identifyexecutor()", ok and (tostring(a) .. "  " .. tostring(b or "")) or "error")
	else kv("identifyexecutor()", "<missing>") end
	kv("_VERSION", _VERSION)
end

rule("2. MACHINE IDENTITY -- what can leave this PC")
do
	local ok, hwid = try(EXE.gethwid)
	kv("gethwid()", hwid)
	if ok and type(hwid) == "string" then logf("  %-24s %d chars", "length", #hwid) end
	local _, uid = try(G("get_user_identity")) kv("get_user_identity()", uid)
	local _, tid = try(G("getthreadidentity")) kv("getthreadidentity()", tid)
end

rule("3. ROBLOX IDENTITY")
do
	local ok, Players = pcall(game.GetService, game, "Players")
	local lp = ok and Players.LocalPlayer or nil
	if lp then
		kv("UserId", lp.UserId) kv("Name", lp.Name) kv("DisplayName", lp.DisplayName)
		kv("AccountAge (days)", lp.AccountAge)
		pcall(function() kv("MembershipType", lp.MembershipType) end)
		pcall(function() kv("LocaleId", lp.LocaleId) end)
	else kv("LocalPlayer", "<none>") end
	kv("game.PlaceId", game.PlaceId)
	kv("game.GameId", game.GameId)
	kv("game.JobId", game.JobId ~= "" and game.JobId or "<studio/none>")
end

rule("4. FILESYSTEM ACCESS")
local files, folders = {}, {}
if EXE.listfiles then
	local function walk(p, d)
		if d > 4 then return end
		local ok, ents = pcall(EXE.listfiles, p)
		if not ok or type(ents) ~= "table" then return end
		for _, e in ipairs(ents) do
			local isdir = false
			if EXE.isfolder then local o, r = pcall(EXE.isfolder, e) isdir = o and r or false end
			if isdir then folders[#folders + 1] = e walk(e, d + 1) else files[#files + 1] = e end
		end
	end
	for _, r in ipairs({ "", ".", "/" }) do
		local ok, ents = pcall(EXE.listfiles, r)
		if ok and type(ents) == "table" and #ents > 0 then walk(r, 1) break end
	end
	kv("folders visible", #folders)
	kv("files readable", #files)
	for i, f in ipairs(files) do
		if i > 40 then logf("    ... and %d more", #files - 40) break end
		LOG("    " .. f)
	end
else LOG("  listfiles unavailable") end

rule("5. SANDBOX ESCAPE TESTS -- these SHOULD all fail")
do
	local rf = EXE.readfile
	local function probe(p)
		local ok, r = pcall(rf, p)
		local kind = ok and type(r) or "error"
		local n = (ok and type(r) == "string") and #r or 0
		logf("  %-50s type=%-7s bytes=%d", p:sub(1, 50), kind, n)
		return n > 0
	end
	local posBytes = 0
	if files[1] and rf then
		local ok, r = pcall(rf, files[1])
		posBytes = (ok and type(r) == "string") and #r or 0
		logf("  POSITIVE control %-33s bytes=%d (must be > 0)", files[1]:sub(1, 33), posBytes)
	end
	if rf then probe("_no_such_file_xyz.txt") end
	local escaped = false
	if rf then
		for _, p in ipairs({
			"../settings.json",
			"../../Google/Chrome/User Data/Default/Login Data",
			"../../../../../../Windows/win.ini",
			"..\\..\\..\\..\\..\\..\\Windows\\win.ini",
			"C:/Windows/win.ini", "C:\\Windows\\win.ini", "....//....//Windows/win.ini",
		}) do if probe(p) then escaped = true end end
	end
	if posBytes == 0 then LOG("  VERDICT: INCONCLUSIVE")
	elseif escaped then LOG("  VERDICT: SANDBOX BROKEN -- an escape returned real file contents.")
	else LOG("  VERDICT: SANDBOX HOLDS") end
end

rule("6. WRITE PROBES -- extension blocklist, self-cleaning")
do
	local wf, df, isf = EXE.writefile, EXE.delfile, EXE.isfile
	local ok, err = try(wf, "_audit_probe.txt", "ok")
	if ok then
		LOG("  allowed      _audit_probe.txt written")
		try(df, "_audit_probe.txt")
		LOG("  cleanup      deleted")
	else LOG("  write failed: " .. tostring(err)) end
	for _, ext in ipairs({ "exe", "bat", "cmd", "ps1", "vbs", "msi", "scr", "hta", "com", "wsf" }) do
		local n = "_audit_probe." .. ext
		try(wf, n, "x")
		local _, created = try(isf, n)
		if created == true then logf("  !! ALLOWED   .%-4s file created -- REPORT THIS", ext) pcall(df, n)
		else logf("  blocked      .%s", ext) end
	end
end

rule("7. CAPABILITY PROBE")
local groups = {
	{ "FILESYSTEM", { "readfile", "writefile", "appendfile", "loadfile", "dofile", "listfiles", "isfile", "isfolder", "makefolder", "delfile", "delfolder", "saveinstance", "getcustomasset" } },
	{ "NETWORK", { "httpget", "HttpGet", "request", "http_request", "WebSocket", "getobjects" } },
	{ "MACHINE ID", { "gethwid", "get_hwid", "get_user_identity", "identifyexecutor", "getexecutorname" } },
	{ "INPUT INJECTION", { "keypress", "keyrelease", "keytap", "mouse1click", "mouse1press", "mouse2click", "mousemoveabs", "mousemoverel", "mousescroll", "isrbxactive" } },
	{ "CLIPBOARD", { "setclipboard", "toclipboard", "getclipboard", "get_clipboard" } },
	{ "VM INTERNALS", { "getgenv", "getrenv", "getreg", "getgc", "gettenv", "getsenv", "filtergc", "hookfunction", "hookmetamethod", "getrawmetatable", "setrawmetatable", "setreadonly", "newcclosure", "iscclosure", "isexecutorclosure", "getnamecallmethod", "loadstring" } },
	{ "SCRIPT / BYTECODE", { "decompile", "dumpbytecode", "getscriptbytecode", "getscriptclosure", "getscripthash", "getscripts", "getrunningscripts", "getloadedmodules", "getcallingscript", "getthreadidentity", "setthreadidentity" } },
	{ "OBJECT MODEL", { "getinstances", "getnilinstances", "gethui", "cloneref", "getproperties", "gethiddenproperty", "sethiddenproperty", "isscriptable", "setscriptable", "getconnections", "firesignal", "fireclickdetector", "fireproximityprompt", "firetouchinterest", "setsimulationradius", "isnetworkowner" } },
	{ "DRAWING / MISC", { "Drawing", "raknet", "crypt", "Regex", "rconsoleprint", "messagebox", "setfflag", "getfflag", "setfpscap", "queueonteleport", "getactors", "run_on_actor" } },
	{ "SHOULD BE ABSENT", { "getenv", "getprocesses", "shellexecute", "execute", "createprocess", "screenshot", "capturescreen", "getcookies", "getauthcookie", "readregistry", "writeregistry" } },
}
local present, absent = 0, 0
for _, grp in ipairs(groups) do
	LOG("")
	LOG("  [" .. grp[1] .. "]")
	local row = {}
	for _, n in ipairs(grp[2]) do
		local ok = G(n) ~= nil
		if ok then present += 1 else absent += 1 end
		row[#row + 1] = string.format("%s%-24s", ok and "+" or "-", n)
		if #row == 2 then LOG("    " .. table.concat(row, " ")) row = {} end
	end
	if #row > 0 then LOG("    " .. table.concat(row, " ")) end
end
LOG("")
logf("  + present, - absent      (%d present, %d absent)", present, absent)

rule("SUMMARY")
LOGF("  Audit complete.")
SAVELOG("audit_output.txt")
LOGF("  Saved to %s/audit_output.txt", OUTDIR)
