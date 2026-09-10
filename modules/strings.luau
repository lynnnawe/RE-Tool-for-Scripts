local SRC_FILE = SRC_FILE or ""
local TARGET_SOURCE = TARGET_SOURCE or ""
local MINLEN = 4
local RUN_SECS = RUN_SECONDS or 40

local sbyte, sgsub = string.byte, string.gsub
local seen, ordered = {}, {}
local function printable(s)
	local g = 0
	for i = 1, #s do
		local b = sbyte(s, i)
		if (b >= 32 and b <= 126) or b == 9 or b == 10 or b == 13 then g += 1 end
	end
	return g / #s >= 0.72
end
local function record(s)
	if type(s) ~= "string" or #s < MINLEN or seen[s] then return end
	if not printable(s) then return end
	seen[s] = true
	ordered[#ordered + 1] = s
end

local rs, rt, rb = string, table, buffer
local function w1(fn) return function(...) local a = fn(...) record(a) return a end end
local tp, tu = rt.pack, rt.unpack
local function wn(fn) return function(...) local r = tp(fn(...)) for i = 1, r.n do record(r[i]) end return tu(r, 1, r.n) end end

local hs = {} for k, v in pairs(rs) do hs[k] = v end
hs.char, hs.sub, hs.rep, hs.gsub, hs.unpack = w1(rs.char), w1(rs.sub), w1(rs.rep), w1(rs.gsub), wn(rs.unpack)
local ht = {} for k, v in pairs(rt) do ht[k] = v end
ht.concat = w1(rt.concat)
local hb = {} if type(rb) == "table" then for k, v in pairs(rb) do hb[k] = v end if rb.readstring then hb.readstring = w1(rb.readstring) end if rb.tostring then hb.tostring = w1(rb.tostring) end end

EXE.env.string = hs
EXE.env.table = ht
if type(rb) == "table" then EXE.env.buffer = hb end

local realLs = EXE.loadstring
if type(realLs) == "function" then
	EXE.env.loadstring = function(src, name)
		if type(src) == "string" and #src > 0 then SAVE("nested_" .. tostring(#src) .. ".lua", src) end
		return realLs(src, name)
	end
end

local src = TARGET_SOURCE
if (src == "" or src == nil) and SRC_FILE ~= "" and EXE.readfile then
	local ok, c = pcall(EXE.readfile, SRC_FILE)
	if ok then src = c end
end
if type(src) ~= "string" or #src == 0 then
	LOG("[!] no target source available (set a target file / source). Aborting string extractor.")
	error("Lyn Debug Multitool: no target source", 0)
end

LOGF("[*] extracting string constants from target (%d bytes), running for %ds...", #src, RUN_SECS)

local lastCount = 0
local function dump()
	if #ordered == lastCount then return end
	lastCount = #ordered
	local snap = table.clone(ordered)
	table.sort(snap)
	SAVE("constants.txt", table.concat(snap, "\n"))
end

task.spawn(function() for _ = 1, RUN_SECS * 4 do task.wait(0.25) dump() end end)
task.spawn(function() local chunk = realLs(src) if chunk then pcall(chunk) end end)
task.wait(RUN_SECS)
dump()
LOGF("[+] done -- %d unique strings -> %s/constants.txt", #ordered, OUTDIR)
