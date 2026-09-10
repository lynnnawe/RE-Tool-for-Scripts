local MINLEN = 3
local MAXLEN = 500

local seen, out = {}, {}
local function keep(s)
	if type(s) ~= "string" then return end
	local n = #s
	if n < MINLEN or n > MAXLEN or seen[s] then return end
	local g = 0
	for i = 1, n do
		local b = string.byte(s, i)
		if (b >= 32 and b <= 126) or b == 9 or b == 10 or b == 13 then g += 1 end
	end
	if g / n < 0.85 then return end
	seen[s] = true
	out[#out + 1] = s
end

LOG("[*] memory scan starting -- run the target script FIRST and let it fully load, then this.")

local scannedTables, scannedFuncs = 0, 0
if EXE.getgc then
	local ok, objs = pcall(EXE.getgc, true)
	if not ok or type(objs) ~= "table" then ok, objs = pcall(EXE.getgc) end
	if ok and type(objs) == "table" then
		for _, o in pairs(objs) do
			local t = type(o)
			if t == "table" then
				scannedTables += 1
				pcall(function() for k, v in pairs(o) do keep(k) keep(v) end end)
			elseif t == "function" then
				scannedFuncs += 1
				if EXE.getconstants then
					local ok3, consts = pcall(EXE.getconstants, o)
					if ok3 and type(consts) == "table" then for _, c in pairs(consts) do keep(c) end end
				end
				if EXE.getupvalues then
					local ok4, ups = pcall(EXE.getupvalues, o)
					if ok4 and type(ups) == "table" then for _, u in pairs(ups) do keep(u) end end
				end
			end
		end
	end
else
	LOG("[!] no getgc on this executor -- table/function harvest skipped.")
end

if EXE.getreg then
	local ok, reg = pcall(EXE.getreg)
	if ok and type(reg) == "table" then
		pcall(function()
			for k, v in pairs(reg) do
				keep(k) keep(v)
				if type(v) == "table" then for kk, vv in pairs(v) do keep(kk) keep(vv) end end
			end
		end)
	end
end

table.sort(out)
local interesting = {}
local pat = {
	"https?://", "%.net", "%.com", "%.gg", "%.win", "%.xyz", "%.io",
	"discord", "webhook", "api", "remote", "Remote", "hwid", "HWID",
	"whitelist", "key", "Key", "token", "Token", "secret", "auth", "Auth",
	"/v%d", "endpoint", "url", "Url", "URL", "version", "Version",
}
for _, s in ipairs(out) do
	for _, p in ipairs(pat) do
		if string.find(s, p) then interesting[#interesting + 1] = s break end
	end
end

SAVE("strings_all.txt", table.concat(out, "\n"))
SAVE("strings_interest.txt", table.concat(interesting, "\n"))
LOGF("[+] memscan done -- %d tables, %d funcs, %d unique strings (%d interesting) -> %s/", scannedTables, scannedFuncs, #out, #interesting, OUTDIR)
if not EXE.getconstants then LOG("    (no getconstants on this executor -- function constants skipped)") end
