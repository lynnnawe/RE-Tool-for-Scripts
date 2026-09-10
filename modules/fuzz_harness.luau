local BASE = FUZZ_BASE or "http://127.0.0.1:8790"
local WS_BASE = FUZZ_WS or "ws://127.0.0.1:8790"

local request = EXE.request
local httpget = EXE.httpget_fn
local WebSocket = EXE.WebSocket

LOG("========================================================================")
LOG("  LYN DEBUG MULTITOOL -- PARSER FUZZ  " .. os.date("%H:%M:%S"))
LOG("  If the client crashes, the LAST 'RUNNING' line is the culprit.")
LOG("========================================================================")

local function mark(stage)
	if EXE.writefile then pcall(EXE.writefile, OUTDIR .. "/fuzz_last_stage.txt", stage .. "  @" .. os.date("%H:%M:%S")) end
end

LOG("")
LOG("[ preflight ] checking the fuzz server is reachable...")
if not request then LOG("  request() unavailable -- cannot run.") error("Lyn Debug Multitool: no request()", 0) end
do
	local ok, res = pcall(request, { Url = BASE .. "/ok", Method = "GET" })
	local sc = (ok and type(res) == "table") and res.StatusCode or 0
	local body = (ok and type(res) == "table" and type(res.Body) == "string") and res.Body or ""
	if sc ~= 200 or body ~= "hello" then
		LOG("  !! SERVER NOT REACHABLE (status=" .. tostring(sc) .. ", body=" .. #body .. " bytes)")
		LOG("     Start it first from the multitool: 'Start fuzz server'.")
		error("Lyn Debug Multitool: fuzz server not reachable", 0)
	end
	LOG("  server is up. Proceeding.")
end

local http_cases = { "/ok", "/huge-header", "/many-headers", "/negative-length", "/overflow-length", "/lying-length", "/bad-chunk", "/no-status", "/nulls", "/deep-json", "/bad-utf8", "/split-forever" }
LOG("")
LOG("[ request() parser ]")
for _, path in ipairs(http_cases) do
	LOG("  -> RUNNING: request " .. path)
	mark("request " .. path)
	local t0 = tick()
	local ok, res = pcall(request, { Url = BASE .. path, Method = "GET" })
	local dt = tick() - t0
	if ok then
		local sc = (type(res) == "table" and res.StatusCode) or "?"
		local bl = (type(res) == "table" and type(res.Body) == "string") and #res.Body or 0
		LOG(string.format("     survived  status=%s bodylen=%d  (%.1fs)", tostring(sc), bl, dt))
	else
		LOG("     rejected  " .. tostring(res):sub(1, 70) .. string.format("  (%.1fs)", dt))
	end
	if path == "/split-forever" and dt > 60 then LOG("     !! took over 60s -- possible hang/DoS on unterminated headers") end
end

LOG("")
LOG("[ httpget() parser ]")
if httpget then
	for _, path in ipairs({ "/ok", "/lying-length", "/nulls", "/bad-utf8" }) do
		LOG("  -> RUNNING: httpget " .. path)
		mark("httpget " .. path)
		local ok, res = pcall(httpget, BASE .. path)
		if ok then LOG("     survived  len=" .. (type(res) == "string" and #res or 0))
		else LOG("     rejected  " .. tostring(res):sub(1, 70)) end
	end
else LOG("  httpget() unavailable") end

LOG("")
LOG("[ WebSocket parser ] -- one hostile frame per fresh connection")
if WebSocket then
	local ws_cases = { "normal", "len126lie", "len127huge", "len64overflow", "big2mb", "badutf8", "empty", "reservedop", "nulls" }
	local connect = WebSocket.connect or WebSocket.new
	for _, case in ipairs(ws_cases) do
		LOG("  -> RUNNING: ws /" .. case)
		mark("ws " .. case)
		local ok, ws = pcall(connect, WS_BASE .. "/" .. case)
		if not ok then LOG("     connect rejected: " .. tostring(ws):sub(1, 70))
		else
			local got, lastlen = 0, -1
			if ws.OnMessage and ws.OnMessage.Connect then
				pcall(function() ws.OnMessage:Connect(function(msg) got += 1 lastlen = type(msg) == "string" and #msg or -1 end) end)
			end
			local t0 = tick()
			while tick() - t0 < 2 do task.wait(0.05) end
			if got > 0 then LOG(string.format("     survived  frame delivered, len=%d", lastlen))
			else LOG("     survived  no frame surfaced (rejected without crashing)") end
			pcall(function() ws:Close() end)
			task.wait(0.1)
		end
	end
else LOG("  WebSocket unavailable") end

mark("COMPLETE")
LOG("")
LOG("========================================================================")
LOG("  NO CRASH -- request()/httpget()/WebSocket withstood this corpus.")
LOG("========================================================================")
SAVELOG("fuzz_result.txt")
