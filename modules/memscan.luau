local MINLEN = 3
local MAXLEN = 800
local BIGCAP = 4000000

local seen, out = {}, {}
local urls, urlseen = {}, {}
local https, httpseen = {}, {}
local interest, intseen = {}, {}

local sbyte, sfind, sgmatch, ssub = string.byte, string.find, string.gmatch, string.sub

local function ratio(s)
	local g = 0
	for i = 1, #s do
		local b = sbyte(s, i)
		if (b >= 32 and b <= 126) or b == 9 or b == 10 or b == 13 then g += 1 end
	end
	return g / #s
end

local urlpat = "[%a][%w%+%.%-]*://[%w%._~%-:/%?#%[%]@!%$&'%(%)%*%+,;=%%]+"
local hostpat = "[%w%-]+%.[%w%-]+%.[%w%._%-~:/%?#@=&%%]*"

local function addurl(u)
	u = (u:gsub("[%.,%)%]'\"]+$", ""))
	if #u >= 8 and not urlseen[u] then urlseen[u] = true urls[#urls + 1] = u end
end

local httpkw = {
	"HttpGet", "HttpGetAsync", "HttpPost", "HttpPostAsync", "PostAsync", "GetAsync",
	"RequestAsync", "http_request", "syn.request", "request(", "webhook", "discord.com/api",
	"discordapp.com/api", "Authorization", "Bearer ", "api_key", "apikey", "\"POST\"", "\"GET\"",
}
local intkw = {
	"discord", "webhook", "hwid", "HWID", "whitelist", "key", "Key", "token", "Token",
	"secret", "auth", "Auth", "endpoint", "/v%d", "/api/", "version", "Version", "loadstring",
	"pastebin", "gist", "raw.github", "supabase", "firebase", "hastebin", "%.gg", "%.lua", "%.php",
}

local function scan(s)
	if type(s) ~= "string" then return end
	local n = #s
	if n < MINLEN or n > BIGCAP then return end

	for u in sgmatch(s, urlpat) do addurl(u) end
	for h in sgmatch(s, hostpat) do
		if sfind(h, "%.", 1) and not sfind(h, "%s") and #h <= 200 then
			if sfind(h, "%.%a%a") then addurl(h) end
		end
	end

	for _, kw in ipairs(httpkw) do
		if sfind(s, kw, 1, true) then
			if not httpseen[s] and n <= 6000 then httpseen[s] = true https[#https + 1] = s end
			break
		end
	end

	if n <= MAXLEN and ratio(s) >= 0.85 then
		if not seen[s] then seen[s] = true out[#out + 1] = s end
		if not intseen[s] then
			for _, p in ipairs(intkw) do
				if sfind(s, p) then intseen[s] = true interest[#interest + 1] = s break end
			end
		end
	end
end

local visited = {}
local scanfunc

local function walk(t, depth)
	if type(t) ~= "table" or visited[t] or depth > 6 then return end
	visited[t] = true
	pcall(function()
		for k, v in pairs(t) do
			scan(k)
			local tv = type(v)
			if tv == "string" then scan(v)
			elseif tv == "table" then walk(v, depth + 1)
			elseif tv == "function" then scanfunc(v) end
		end
	end)
end

scanfunc = function(f)
	if EXE.getconstants then
		local ok, c = pcall(EXE.getconstants, f)
		if ok and type(c) == "table" then
			for _, x in pairs(c) do
				if type(x) == "string" then scan(x) elseif type(x) == "table" then walk(x, 4) end
			end
		end
	end
	if EXE.getupvalues then
		local ok, u = pcall(EXE.getupvalues, f)
		if ok and type(u) == "table" then
			for _, x in pairs(u) do
				if type(x) == "string" then scan(x) elseif type(x) == "table" then walk(x, 4) end
			end
		end
	end
end

LOG("[*] memory scan -- run the target script FIRST and let it fully load, then this.")

local nt, nf = 0, 0
if EXE.getgc then
	local ok, objs = pcall(EXE.getgc, true)
	if not ok or type(objs) ~= "table" then ok, objs = pcall(EXE.getgc) end
	if ok and type(objs) == "table" then
		for _, o in pairs(objs) do
			local t = type(o)
			if t == "table" then nt += 1 walk(o, 4)
			elseif t == "function" then nf += 1 scanfunc(o) end
		end
	end
else
	LOG("[!] no getgc on this executor -- heap harvest limited to globals + registry.")
end

if EXE.getreg then local ok, reg = pcall(EXE.getreg) if ok then walk(reg, 0) end end
if type(EXE.env) == "table" then walk(EXE.env, 0) end

table.sort(out)
table.sort(urls)
table.sort(interest)

SAVE("strings_all.txt", table.concat(out, "\n"))
SAVE("urls.txt", table.concat(urls, "\n"))
SAVE("http.txt", table.concat(https, "\n"))
SAVE("strings_interest.txt", table.concat(interest, "\n"))

LOG("")
LOGF("[+] tables %d  funcs %d", nt, nf)
LOGF("[+] urls          : %d  -> %s/urls.txt", #urls, OUTDIR)
LOGF("[+] http strings  : %d  -> %s/http.txt", #https, OUTDIR)
LOGF("[+] interesting   : %d  -> %s/strings_interest.txt", #interest, OUTDIR)
LOGF("[+] all strings   : %d  -> %s/strings_all.txt", #out, OUTDIR)
if not EXE.getconstants then LOG("    (no getconstants here -- function constants skipped)") end
for i = 1, math.min(#urls, 25) do LOG("    " .. urls[i]) end
