local realprint, realtype, realtostring = print, type, tostring
local sformat, sgsub, sbyte, srep, ssub = string.format, string.gsub, string.byte, string.rep, string.sub
local floor, sqrt, min, max, abs = math.floor, math.sqrt, math.min, math.max, math.abs

local VIEWPORT_X, VIEWPORT_Y = 1280, 720
local BEZIER_SAMPLES = 64

local PAD = "[dump-pad] " .. srep(".", 8192)
local seen, lines = {}, 0
local REPEATS, MAX_LINES = 4, 3000

local function esc(s)
    s = sgsub(s, "[^\32-\126]", function(c) return sformat("\\x%02X", sbyte(c)) end)
    if #s > 300 then s = ssub(s, 1, 300) .. "..." end
    return s
end

local function log(msg)
    local c = (seen[msg] or 0) + 1
    seen[msg] = c
    if c > REPEATS or lines >= MAX_LINES then return end
    lines += 1
    realprint(sformat("%5d %s%s", lines, msg, c > 1 and sformat("  (x%d)", c) or ""))
    realprint(PAD)
end

local F = setmetatable({}, { __mode = "k" })   -- proxy -> fields
local T = setmetatable({}, { __mode = "k" })   -- proxy -> Roblox type name

local function object(tname, meta, init)
    local p = newproxy(true)
    local mt = getmetatable(p)
    for k, v in pairs(meta) do mt[k] = v end
    F[p] = init or {}
    T[p] = tname
    return p
end

local function rbxtype(v)
    local t = realtype(v)
    if t == "userdata" then return T[v] or "userdata" end
    if t == "table" then return T[v] or "table" end
    return t
end

local function fmt(v)
    local t = rbxtype(v)
    if t == "string" then return '"' .. esc(v) .. '"' end
    if t == "number" or t == "boolean" or t == "nil" then return realtostring(v) end
    if t == "function" then return "<function>" end
    return t .. "(" .. realtostring(v) .. ")"
end

local function args(...)
    local out, n = {}, select("#", ...)
    for i = 1, n do out[i] = fmt((select(i, ...))) end
    return table.concat(out, ", ", 1, n)
end

local V2, V3

local v2meta = {}
v2meta.__index = function(s, k)
    local f = F[s]
    if k == "X" then return f.x elseif k == "Y" then return f.y end
    if k == "Magnitude" then return sqrt(f.x * f.x + f.y * f.y) end
    if k == "Unit" then
        local m = sqrt(f.x * f.x + f.y * f.y)
        if m == 0 then return V2(0, 0) end
        return V2(f.x / m, f.y / m)
    end
    if k == "Dot" then return function(_, o) return f.x * F[o].x + f.y * F[o].y end end
    if k == "Lerp" then
        return function(_, o, a) return V2(f.x + (F[o].x - f.x) * a, f.y + (F[o].y - f.y) * a) end
    end
    return nil
end
v2meta.__newindex = function() error("Vector2 is read-only", 2) end
v2meta.__add = function(a, b) return V2(F[a].x + F[b].x, F[a].y + F[b].y) end
v2meta.__sub = function(a, b) return V2(F[a].x - F[b].x, F[a].y - F[b].y) end
v2meta.__unm = function(a) return V2(-F[a].x, -F[a].y) end
v2meta.__mul = function(a, b)
    if realtype(a) == "number" then return V2(a * F[b].x, a * F[b].y) end
    if realtype(b) == "number" then return V2(F[a].x * b, F[a].y * b) end
    return V2(F[a].x * F[b].x, F[a].y * F[b].y)
end
v2meta.__div = function(a, b)
    if realtype(b) == "number" then return V2(F[a].x / b, F[a].y / b) end
    return V2(F[a].x / F[b].x, F[a].y / F[b].y)
end
v2meta.__eq = function(a, b) return F[a].x == F[b].x and F[a].y == F[b].y end
v2meta.__tostring = function(a) return sformat("%g, %g", F[a].x, F[a].y) end

V2 = function(x, y) return object("Vector2", v2meta, { x = x or 0, y = y or 0 }) end

local v3meta = {}
v3meta.__index = function(s, k)
    local f = F[s]
    if k == "X" then return f.x elseif k == "Y" then return f.y elseif k == "Z" then return f.z end
    if k == "Magnitude" then return sqrt(f.x ^ 2 + f.y ^ 2 + f.z ^ 2) end
    if k == "Unit" then
        local m = sqrt(f.x ^ 2 + f.y ^ 2 + f.z ^ 2)
        if m == 0 then return V3(0, 0, 0) end
        return V3(f.x / m, f.y / m, f.z / m)
    end
    return nil
end
v3meta.__newindex = function() error("Vector3 is read-only", 2) end
v3meta.__add = function(a, b) return V3(F[a].x + F[b].x, F[a].y + F[b].y, F[a].z + F[b].z) end
v3meta.__sub = function(a, b) return V3(F[a].x - F[b].x, F[a].y - F[b].y, F[a].z - F[b].z) end
v3meta.__unm = function(a) return V3(-F[a].x, -F[a].y, -F[a].z) end
v3meta.__mul = function(a, b)
    if realtype(a) == "number" then return V3(a * F[b].x, a * F[b].y, a * F[b].z) end
    if realtype(b) == "number" then return V3(F[a].x * b, F[a].y * b, F[a].z * b) end
    return V3(F[a].x * F[b].x, F[a].y * F[b].y, F[a].z * F[b].z)
end
v3meta.__div = function(a, b)
    if realtype(b) == "number" then return V3(F[a].x / b, F[a].y / b, F[a].z / b) end
    return V3(F[a].x / F[b].x, F[a].y / F[b].y, F[a].z / F[b].z)
end
v3meta.__eq = function(a, b) return F[a].x == F[b].x and F[a].y == F[b].y and F[a].z == F[b].z end
v3meta.__tostring = function(a) return sformat("%g, %g, %g", F[a].x, F[a].y, F[a].z) end

V3 = function(x, y, z) return object("Vector3", v3meta, { x = x or 0, y = y or 0, z = z or 0 }) end

local UD, UD2

local udmeta = {}
udmeta.__index = function(s, k)
    local f = F[s]
    if k == "Scale" then return f.s elseif k == "Offset" then return f.o end
    return nil
end
udmeta.__newindex = function() error("UDim is read-only", 2) end
udmeta.__add = function(a, b) return UD(F[a].s + F[b].s, F[a].o + F[b].o) end
udmeta.__sub = function(a, b) return UD(F[a].s - F[b].s, F[a].o - F[b].o) end
udmeta.__unm = function(a) return UD(-F[a].s, -F[a].o) end
udmeta.__eq = function(a, b) return F[a].s == F[b].s and F[a].o == F[b].o end
udmeta.__tostring = function(a) return sformat("%g, %g", F[a].s, F[a].o) end

UD = function(s, o) return object("UDim", udmeta, { s = s or 0, o = o or 0 }) end

local ud2meta = {}
ud2meta.__index = function(s, k)
    local f = F[s]
    if k == "X" or k == "Width" then return f.x end
    if k == "Y" or k == "Height" then return f.y end
    if k == "Lerp" then
        return function(_, o, a)
            local g = F[o]
            return UD2(UD(F[f.x].s + (F[F[o].x].s - F[f.x].s) * a, F[f.x].o + (F[F[o].x].o - F[f.x].o) * a),
                       UD(F[f.y].s + (F[F[o].y].s - F[f.y].s) * a, F[f.y].o + (F[F[o].y].o - F[f.y].o) * a))
        end
    end
    return nil
end
ud2meta.__newindex = function() error("UDim2 is read-only", 2) end
ud2meta.__add = function(a, b) return UD2(F[a].x + F[b].x, F[a].y + F[b].y) end
ud2meta.__sub = function(a, b) return UD2(F[a].x - F[b].x, F[a].y - F[b].y) end
ud2meta.__unm = function(a) return UD2(-F[a].x, -F[a].y) end
ud2meta.__mul = function(a, b)
    if realtype(b) == "number" then
        local ax, ay = F[F[a].x], F[F[a].y]
        return UD2(UD(ax.s * b, ax.o * b), UD(ay.s * b, ay.o * b))
    end
    return a
end
ud2meta.__eq = function(a, b) return F[a].x == F[b].x and F[a].y == F[b].y end
ud2meta.__tostring = function(a)
    local x, y = F[F[a].x], F[F[a].y]
    return sformat("{%g, %g}, {%g, %g}", x.s, x.o, y.s, y.o)
end

UD2 = function(x, y) return object("UDim2", ud2meta, { x = x, y = y }) end

local function ud2new(a, b, c, d)
    if rbxtype(a) == "UDim" then return UD2(a, b) end
    return UD2(UD(a or 0, b or 0), UD(c or 0, d or 0))
end

local ZERO2 = ud2new(0, 0, 0, 0)

local function u2parts(u)
    local f = F[u]
    local x, y = F[f.x], F[f.y]
    return x.s, x.o, y.s, y.o
end

local enumTypes = {}
local Enum

local itemmeta = {}
itemmeta.__index = function(s, k)
    local f = F[s]
    if k == "Name" then return f.name end
    if k == "Value" then return f.value end
    if k == "EnumType" then return f.etype end
    return nil
end
itemmeta.__tostring = function(s) return "Enum." .. F[F[s].etype].name .. "." .. F[s].name end
itemmeta.__eq = function(a, b) return F[a].name == F[b].name and F[a].etype == F[b].etype end

local etmeta = {}
etmeta.__index = function(s, k)
    local f = F[s]
    if k == "GetEnumItems" then
        return function() local l = {} for _, v in pairs(f.items) do l[#l + 1] = v end return l end
    end
    if k == "FromName" then return function(_, n) return f.items[n] end end
    if k == "FromValue" then
        return function(_, val)
            for _, v in pairs(f.items) do if F[v].value == val then return v end end
            return nil
        end
    end
    local it = f.items[k]
    if not it then
        it = object("EnumItem", itemmeta, { name = k, value = f.order, etype = s })
        f.order += 1
        f.items[k] = it
    end
    return it
end
etmeta.__tostring = function(s) return "Enum." .. F[s].name end

local function enumType(name)
    local et = enumTypes[name]
    if et then return et end
    et = object("Enum", etmeta, { name = name, items = {}, order = 0 })
    enumTypes[name] = et
    return et
end

local enumsmeta = {}
enumsmeta.__index = function(_, k)
    if k == "GetEnums" then
        return function() local l = {} for _, v in pairs(enumTypes) do l[#l + 1] = v end return l end
    end
    return enumType(k)
end
enumsmeta.__tostring = function() return "Enums" end
Enum = object("Enums", enumsmeta, {})

local connmeta = {}
connmeta.__index = function(s, k)
    local f = F[s]
    if k == "Connected" then return f.connected end
    if k == "Disconnect" or k == "disconnect" then
        return function() f.connected = false end
    end
    return nil
end
connmeta.__tostring = function() return "Connection" end

local sigmeta = {}
sigmeta.__index = function(s, k)
    local f = F[s]
    if k == "Connect" or k == "connect" or k == "ConnectParallel" or k == "Once" then
        return function(_, fn)
            local c = object("RBXScriptConnection", connmeta, { connected = true, fn = fn })
            f.handlers[#f.handlers + 1] = c
            return c
        end
    end
    if k == "Wait" then return function() return nil end end
    return nil
end
sigmeta.__tostring = function(s) return "Signal " .. F[s].name end

local function newSignal(name)
    return object("RBXScriptSignal", sigmeta, { name = name, handlers = {} })
end

local function bez(p0, p1, p2, p3, t)
    local m = 1 - t
    local a, b, c, d = m * m * m, 3 * m * m * t, 3 * m * t * t, t * t * t
    local x0s, x0o, y0s, y0o = u2parts(p0)
    local x1s, x1o, y1s, y1o = u2parts(p1)
    local x2s, x2o, y2s, y2o = u2parts(p2)
    local x3s, x3o, y3s, y3o = u2parts(p3)
    return UD2(UD(a * x0s + b * x1s + c * x2s + d * x3s, a * x0o + b * x1o + c * x2o + d * x3o),
               UD(a * y0s + b * y1s + c * y2s + d * y3s, a * y0o + b * y1o + c * y2o + d * y3o))
end

local function bezd(p0, p1, p2, p3, t)
    local m = 1 - t
    local a, b, c = 3 * m * m, 6 * m * t, 3 * t * t
    local x0s, x0o, y0s, y0o = u2parts(p0)
    local x1s, x1o, y1s, y1o = u2parts(p1)
    local x2s, x2o, y2s, y2o = u2parts(p2)
    local x3s, x3o, y3s, y3o = u2parts(p3)
    return UD2(UD(a * (x1s - x0s) + b * (x2s - x1s) + c * (x3s - x2s),
                  a * (x1o - x0o) + b * (x2o - x1o) + c * (x3o - x2o)),
               UD(a * (y1s - y0s) + b * (y2s - y1s) + c * (y3s - y2s),
                  a * (y1o - y0o) + b * (y2o - y1o) + c * (y3o - y2o)))
end

local function u2vec(u, psx, psy)
    local xs, xo, ys, yo = u2parts(u)
    return V2(psx * xs + xo, psy * ys + yo)
end

local instmeta = {}
local makeInstance

local function absoluteSize(inst)
    local f = F[inst]
    local psx, psy
    if f.parent then
        local p = absoluteSize(f.parent)
        psx, psy = F[p].x, F[p].y
    else
        psx, psy = VIEWPORT_X, VIEWPORT_Y
    end
    local size = f.props.Size
    if not size or rbxtype(size) ~= "UDim2" then return V2(psx, psy) end
    local xs, xo, ys, yo = u2parts(size)
    local w, h = psx * xs + xo, psy * ys + yo
    for _, c in ipairs(f.children) do
        local cf = F[c]
        if cf.class == "UIScale" then
            local s = cf.props.Scale or 1
            w, h = w * s, h * s
        elseif cf.class == "UISizeConstraint" then
            local mn, mx = cf.props.MinSize, cf.props.MaxSize
            if mn then w, h = max(w, F[mn].x), max(h, F[mn].y) end
            if mx then w, h = min(w, F[mx].x), min(h, F[mx].y) end
        end
    end
    return V2(w, h)
end

local function pathSegments(inst)
    local cps = F[inst].cps or {}
    local segs = {}
    for i = 1, #cps - 1 do
        local a, b = F[cps[i]], F[cps[i + 1]]
        segs[i] = { a.pos, a.pos + a.right, b.pos + b.left, b.pos }
    end
    return segs
end

local function pathArc(inst)
    local f = F[inst]
    if f.arc then return f.arc end
    local segs = pathSegments(inst)
    local ps = absoluteSize(f.parent or inst)
    local psx, psy = F[ps].x, F[ps].y
    local arc = { total = 0, segs = {} }
    for i, s in ipairs(segs) do
        local prev = u2vec(bez(s[1], s[2], s[3], s[4], 0), psx, psy)
        local acc, samples = 0, { [0] = 0 }
        for k = 1, BEZIER_SAMPLES do
            local cur = u2vec(bez(s[1], s[2], s[3], s[4], k / BEZIER_SAMPLES), psx, psy)
            acc += (cur - prev).Magnitude
            samples[k] = acc
            prev = cur
        end
        arc.segs[i] = { len = acc, samples = samples }
        arc.total += acc
    end
    f.arc = arc
    return arc
end

local function pathAt(inst, t, byArc, tangent)
    local segs = pathSegments(inst)
    local n = #segs
    if n == 0 then return tangent and V2(0, 0) or ZERO2 end
    t = max(0, min(1, t or 0))
    local si, lt
    if byArc then
        local arc = pathArc(inst)
        local target, run = t * arc.total, 0
        si, lt = n, 1
        for i, s in ipairs(arc.segs) do
            if run + s.len >= target or i == n then
                local want, prev = target - run, 0
                lt = 1
                for k = 1, BEZIER_SAMPLES do
                    local cur = s.samples[k]
                    if cur >= want then
                        local span = cur - prev
                        lt = (k - 1 + (span > 0 and (want - prev) / span or 0)) / BEZIER_SAMPLES
                        break
                    end
                    prev = cur
                end
                si = i
                break
            end
            run += s.len
        end
    else
        local u = t * n
        si = min(n, floor(u) + 1)
        lt = u - (si - 1)
    end
    local s = segs[si]
    if tangent then
        local ps = absoluteSize(F[inst].parent or inst)
        return u2vec(bezd(s[1], s[2], s[3], s[4], lt), F[ps].x, F[ps].y).Unit
    end
    return bez(s[1], s[2], s[3], s[4], lt)
end

local classMethods = {}
classMethods.Path2D = {
    SetControlPoints = function(self, cps)
        F[self].cps = cps
        F[self].arc = nil
        log(sformat("CALL   Path2D:SetControlPoints(%d points)", #cps))
    end,
    GetControlPoints = function(self) return F[self].cps or {} end,
    GetLength = function(self) return pathArc(self).total end,
    GetMaxIndex = function(self) return max(0, #(F[self].cps or {}) - 1) end,
    GetPositionOnCurve = function(self, t) return pathAt(self, t, false, false) end,
    GetTangentOnCurve = function(self, t) return pathAt(self, t, false, true) end,
    GetPositionOnCurveArcLength = function(self, t) return pathAt(self, t, true, false) end,
    GetTangentOnCurveArcLength = function(self, t) return pathAt(self, t, true, true) end,
}

instmeta.__index = function(self, k)
    local f = F[self]
    local v = f.props[k]
    if v ~= nil then return v end

    if k == "Parent" then return f.parent end
    if k == "Name" then return f.name end
    if k == "ClassName" then return f.class end
    if k == "AbsoluteSize" then return absoluteSize(self) end
    if k == "AbsolutePosition" then return V2(0, 0) end

    local cm = classMethods[f.class]
    if cm and cm[k] then return cm[k] end

    if k == "AncestryChanged" or k == "Changed" or k == "ChildAdded"
        or k == "ChildRemoved" or k == "Destroying" then
        f.signals[k] = f.signals[k] or newSignal(k)
        return f.signals[k]
    end

    if k == "IsA" then return function(_, w) return w == f.class end end
    if k == "GetChildren" then
        return function() local o = {} for i, c in ipairs(f.children) do o[i] = c end return o end
    end
    if k == "GetDescendants" then
        return function()
            local o = {}
            local function walk(n)
                for _, c in ipairs(F[n].children) do o[#o + 1] = c walk(c) end
            end
            walk(self)
            return o
        end
    end
    if k == "FindFirstChild" or k == "FindFirstChildOfClass" or k == "FindFirstChildWhichIsA" then
        return function(_, name)
            for _, c in ipairs(f.children) do
                if F[c].name == name or F[c].class == name then return c end
            end
            return nil
        end
    end
    if k == "WaitForChild" then
        return function(_, name)
            for _, c in ipairs(f.children) do
                if F[c].name == name then return c end
            end
            return makeInstance(name, self)   -- must not return nil or the VM stalls
        end
    end
    if k == "Clone" then
        return function()
            local c = makeInstance(f.class)
            for pk, pv in pairs(f.props) do F[c].props[pk] = pv end
            return c
        end
    end
    if k == "Destroy" or k == "Remove" then return function() F[self].parent = nil end end
    if k == "GetPropertyChangedSignal" then
        return function(_, name)
            local key = "prop:" .. name
            f.signals[key] = f.signals[key] or newSignal(name)
            return f.signals[key]
        end
    end
    if k == "GetService" then return function(_, n) return self:WaitForChild(n) end end

    for _, c in ipairs(f.children) do
        if F[c].name == k then return c end
    end

    log(sformat("MISS   %s.%s", f.class, realtostring(k)))
    return nil
end

instmeta.__newindex = function(self, k, v)
    local f = F[self]
    if k == "Parent" then
        if f.parent then
            local sib = F[f.parent].children
            for i, c in ipairs(sib) do if c == self then table.remove(sib, i) break end end
        end
        f.parent = v
        if v and F[v] and F[v].children then
            local ch = F[v].children
            ch[#ch + 1] = self
        end
        return
    end
    if k == "Name" then f.name = v return end
    f.props[k] = v
end

instmeta.__tostring = function(self) return F[self].name end

makeInstance = function(class, parent)
    local inst = object("Instance", instmeta, {
        class = class, name = class, props = {}, children = {}, parent = nil, signals = {},
    })
    if parent then inst.Parent = parent end
    return inst
end

local cpmeta = {}
cpmeta.__index = function(s, k)
    local f = F[s]
    if k == "Position" then return f.pos end
    if k == "LeftTangent" then return f.left end
    if k == "RightTangent" then return f.right end
    return nil
end
cpmeta.__tostring = function(s) return "Path2DControlPoint(" .. realtostring(F[s].pos) .. ")" end
cpmeta.__eq = function(a, b) return F[a].pos == F[b].pos end

local game = makeInstance("DataModel")
F[game].name = "Ugc"

local services = {}
local function service(name, props)
    local s = services[name]
    if s then return s end
    s = makeInstance(name, game)
    F[s].name = name
    for k, v in pairs(props or {}) do F[s].props[k] = v end
    services[name] = s
    return s
end

service("Workspace")
service("Players")
service("StarterPlayer")
service("StarterGui")
service("ReplicatedStorage")
service("CoreGui")
service("Lighting")
service("RunService", {
    IsClient = function() return true end,
    IsServer = function() return false end,
    IsStudio = function() return false end,
    IsRunning = function() return true end,
})
service("HttpService", {
    GetAsync = function(_, url) log("HTTP   GetAsync(" .. fmt(url) .. ")") return "" end,
    PostAsync = function(_, url, b) log("HTTP   PostAsync(" .. fmt(url) .. ", " .. fmt(b) .. ")") return "" end,
    RequestAsync = function(_, o) log("HTTP   RequestAsync(" .. fmt(o) .. ")") return { Success = true, StatusCode = 200, Body = "" } end,
    JSONDecode = function() return {} end,
    JSONEncode = function() return "{}" end,
    GenerateGUID = function() return "{00000000-0000-0000-0000-000000000000}" end,
})

F[game].props.GetService = function(_, n)
    log('CALL   game:GetService("' .. realtostring(n) .. '")')
    return service(n)
end
F[game].props.IsLoaded = function() return true end
F[game].props.HttpGet = function(_, url) log("HTTP   game:HttpGet(" .. fmt(url) .. ")") return "" end
F[game].props.HttpGetAsync = F[game].props.HttpGet
F[game].props.Workspace = services.Workspace
F[game].props.PlaceId = 0
F[game].props.JobId = ""

local rndmeta = {}
rndmeta.__index = function(s, k)
    if k == "NextInteger" then return function(_, a, b) return floor((a + b) / 2) end end
    if k == "NextNumber" then return function(_, a, b) if a then return (a + b) / 2 end return 0.5 end end
    if k == "Shuffle" then return function(_, t) return t end end
    if k == "Clone" then return function(self) return self end end
    return nil
end
rndmeta.__tostring = function() return "Random" end

local task = {
    wait = function(t) return t or 0 end,
    cancel = function() end,
    synchronize = function() end,
    desynchronize = function() end,
}
local SPAWN_INVOKES = (SPAWN_INVOKES ~= false)
task.spawn = function(f, ...)
    if realtype(f) == "function" then
        local a = table.pack(...)
        local ok, n_, d_ = pcall(function() return __PCSTATS() end)
        if ok and realtype(n_) == "number" then
            log(sformat("CALL   task.spawn(<function>)  [VM %d dispatched, %d distinct so far]", n_, d_))
        else
            log("CALL   task.spawn(<function>)")
        end
        if not SPAWN_INVOKES then log("SKIP   not invoking the spawned function") return f end
        local ok, err = pcall(function() return f(table.unpack(a, 1, a.n)) end)
        if not ok then log("ERROR  task.spawn callback: " .. esc(realtostring(err))) end
    end
    return f
end
task.defer = function(f, ...) return task.spawn(f, ...) end
task.delay = function(_, f, ...) return task.spawn(f, ...) end

local cfmeta = {}
cfmeta.__index = function(s, k)
    local f = F[s]
    if k == "X" then return f.x elseif k == "Y" then return f.y elseif k == "Z" then return f.z end
    return nil
end
cfmeta.__tostring = function(s) return sformat("%g, %g, %g", F[s].x, F[s].y, F[s].z) end

local c3meta = {}
c3meta.__index = function(s, k)
    local f = F[s]
    if k == "R" then return f.r elseif k == "G" then return f.g elseif k == "B" then return f.b end
    return nil
end
c3meta.__tostring = function(s) return sformat("%g, %g, %g", F[s].r, F[s].g, F[s].b) end

local G = getfenv(0)
local REALG = getmetatable(G).__index
local dbginfo = debug.info

local EMU = {
    Instance = { new = function(c, p) log('CALL   Instance.new("' .. realtostring(c) .. '")') return makeInstance(c, p) end },
    Path2DControlPoint = {
        new = function(pos, l, r)
            return object("Path2DControlPoint", cpmeta,
                { pos = pos or ZERO2, left = l or ZERO2, right = r or ZERO2 })
        end,
    },
    Vector2 = { new = V2, zero = V2(0, 0), one = V2(1, 1), xAxis = V2(1, 0), yAxis = V2(0, 1) },
    Vector3 = { new = V3, zero = V3(0, 0, 0), one = V3(1, 1, 1) },
    UDim = { new = UD },
    UDim2 = {
        new = ud2new,
        fromScale = function(x, y) return UD2(UD(x, 0), UD(y, 0)) end,
        fromOffset = function(x, y) return UD2(UD(0, x), UD(0, y)) end,
    },
    CFrame = { new = function(x, y, z) return object("CFrame", cfmeta, { x = x or 0, y = y or 0, z = z or 0 }) end },
    Color3 = {
        new = function(r, g, b) return object("Color3", c3meta, { r = r or 0, g = g or 0, b = b or 0 }) end,
        fromRGB = function(r, g, b) return object("Color3", c3meta, { r = (r or 0) / 255, g = (g or 0) / 255, b = (b or 0) / 255 }) end,
    },
    Random = { new = function() return object("Random", rndmeta, {}) end },
    Enum = Enum,
    task = task,
    game = game,
    Game = game,
    workspace = services.Workspace,
    Workspace = services.Workspace,
    typeof = rbxtype,
    tick = function() return os.clock() end,
    time = function() return os.time() end,
    wait = task.wait,
    spawn = task.spawn,
    delay = function(_, f, ...) return task.spawn(f, ...) end,
    iscclosure = function(f) return dbginfo(f, "s") == "[C]" end,
    islclosure = function(f) return dbginfo(f, "s") ~= "[C]" end,
    isexecutorclosure = function() return false end,
    identifyexecutor = function() return "Synapse X", "2.0.0" end,
    getexecutorname = function() return "Synapse X" end,
    checkcaller = function() return true end,
    setreadonly = function() end,
    isreadonly = function() return false end,
}
EMU.getgenv = function() return G end
EMU.getrenv = function() return G end

local stubs = {}
local function makestub(name)
    if stubs[name] then return stubs[name] end
    local s = setmetatable({}, {
        __index = function(_, k)
            log("INDEX  " .. name .. "." .. realtostring(k))
            return makestub(name .. "." .. realtostring(k))
        end,
        __newindex = function() end,
        __call = function(_, ...)
            log(sformat("CALL   %s(%s)", name, args(...)))
            return makestub(name .. "()")
        end,
        __tostring = function() return "<" .. name .. ">" end,
        __concat = function(a, b) return realtostring(a) .. realtostring(b) end,
        __len = function() return 0 end,
    })
    stubs[name] = s
    return s
end

for k, v in pairs(EMU) do G[k] = v end

setmetatable(G, {
    __index = function(_, k)
        local v = REALG[k]
        if v ~= nil then return v end
        log("GLOBAL " .. realtostring(k) .. "  (unimplemented)")
        return makestub(realtostring(k))
    end,
})

local function hook_loader(fn, nm)
    if realtype(fn) ~= "function" then return fn end
    return function(chunk, ...)
        if realtype(chunk) == "string" then
            realprint(srep("=", 70))
            realprint(sformat("[%s] %d bytes:", nm, #chunk))
            realprint(chunk)
            realprint(srep("=", 70))
            realprint(PAD)
        end
        return fn(chunk, ...)
    end
end
G.loadstring = hook_loader(REALG.loadstring, "loadstring")
