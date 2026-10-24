--[[ parley bridge: the game side of the LLM turn loop (EOP 3.3.1 API, docs/eop-api-notes.md).

Never blocks the game. For each LLM faction (listed in <root>/bridge.txt):
  - on its turn END (turn N):  write <root>/<game>/turn-N/<faction>/state.json
  - on its turn START (N+1):   apply <root>/<game>/turn-N/<faction>/orders.json if the
                               orchestrator has answered, then write results.json there.
Orders not ready by then are skipped and logged. Every order is re-checked against the
live game and wrapped in pcall: a bad order is reported, never forced, never fatal.
The orchestrator pre-creates turn folders (Lua can't make directories).
]]

local json = require("json")

local M = {}
local root, gd
local applied = {}  -- turn dirs applied since this campaign map loaded; a reload clears it

-- The game's strings may be Windows-1252, not UTF-8; escape every high byte so the
-- JSON stays valid (bytes read as Latin-1, close enough for names).
local function encode(value)
    return (json.encode(value):gsub("[\128-\255]", function(c)
        return string.format("\\u%04x", c:byte())
    end))
end

local function log(line)
    local f = io.open(root .. "/parley_bridge.log", "a")
    if f then
        f:write(os.date("%Y-%m-%d %H:%M:%S "), line, "\n")
        f:close()
    end
end

local function read_file(path)
    local f = io.open(path, "r")
    if not f then return nil end
    local text = f:read("*a")
    f:close()
    return text
end

local function exists(path)
    local f = io.open(path, "r")
    if f then f:close() return true end
    return false
end

-- Write to .tmp then rename; Windows can't rename over an existing file, so remove it first.
local function atomic_write(path, text)
    local tmp = path .. ".lua.tmp"
    local f, err = io.open(tmp, "w")
    if not f then return false, err end
    f:write(text)
    f:close()
    os.remove(path)
    return os.rename(tmp, path)
end

local function config()
    local text = read_file(root .. "/bridge.txt")
    if not text then return nil end
    local cfg = { factions = {} }
    for line in text:gmatch("[^\r\n]+") do
        local k, v = line:match("^([%w_]+)=(.+)$")
        if k == "game_id" then cfg.game_id = v
        elseif k == "faction" then cfg.factions[v] = true end
    end
    return cfg.game_id and cfg or nil
end

local function turn_dir(cfg, turn, faction)
    return string.format("%s/%s/turn-%04d/%s", root, cfg.game_id, turn, faction)
end

-- --- reading the game ----------------------------------------------------------------

local function stance(campaign, a, b)
    if campaign:checkDipStance(dipRelType.war, a, b) then return "war" end
    if campaign:checkDipStance(dipRelType.alliance, a, b) then return "alliance" end
    if campaign:checkDipStance(dipRelType.peace, a, b) then return "peace" end
    return "neutral"
end

local function base_id(st, index)
    if st.leader then return st.leader.namedCharacter.fullName end
    local s = st:findInSettlement()
    if s then return "garrison:" .. s.name end
    return "stack:" .. index
end

-- IDs for a faction's stacks, in getStack order; repeated names get #2, #3...
local function army_ids(fac)
    local ids, seen = {}, {}
    for i = 0, fac.stacksNum - 1 do
        local id = base_id(fac:getStack(i), i)
        seen[id] = (seen[id] or 0) + 1
        ids[i] = seen[id] > 1 and (id .. "#" .. seen[id]) or id
    end
    return ids
end

local function army_view(st, id)
    local s = st:findInSettlement()
    local x, y = 0, 0
    if st.leader then x, y = st.leader.xCoord, st.leader.yCoord
    elseif s then x, y = s.xCoord, s.yCoord end
    return {  -- nil fields are left out; the orchestrator reads a missing key as "none"
        id = id,
        leader = st.leader and st.leader.namedCharacter.fullName or nil,
        x = x, y = y, strength = st.totalStrength, units = st.numOfUnits,
        in_settlement = s and s.name or nil,
    }
end

function M.report(fac, cfg)
    local campaign, map = gd.campaignStruct, gd.stratMap
    local settlements, armies, factions = {}, {}, {}
    for i = 0, fac.settlementsNum - 1 do
        local s = fac:getSettlement(i)
        local buildings = {}
        for b = 0, s.buildingsNum - 1 do buildings[#buildings + 1] = s:getBuilding(b):getType() end
        settlements[#settlements + 1] = {
            id = s.name, name = s.localizedName, region = map.getRegion(s.regionID).regionName,
            garrison_strength = s.army and s.army.totalStrength or 0,
            population = s.populationSize, buildings = buildings,
        }
    end
    local ids = army_ids(fac)
    for i = 0, fac.stacksNum - 1 do armies[#armies + 1] = army_view(fac:getStack(i), ids[i]) end
    for i = 0, stratmap.game.getFactionsCount() - 1 do
        local other = stratmap.game.getFaction(i)
        if other and other.name ~= fac.name and other.name ~= "slave" then
            factions[#factions + 1] = { id = other.name, name = other.localizedName,
                                        stance = stance(campaign, fac, other) }
        end
    end
    local turn = campaign.turnNumber
    local last = read_file(turn_dir(cfg, turn - 1, fac.name) .. "/results.json")
    return {
        protocol = 1, game_id = cfg.game_id, turn = turn, year = math.floor(campaign.currentDate),
        faction = fac.name, treasury = fac.money, income = 0,
        settlements = settlements, armies = armies, factions = factions,
        visible_enemies = {}, last_results = last and json.decode(last) or {},
    }
end

-- --- applying orders -----------------------------------------------------------------

local function find_army(fac, id)
    local ids = army_ids(fac)
    for i = 0, fac.stacksNum - 1 do
        if ids[i] == id then return fac:getStack(i) end
    end
end

local function owned(fac, s) return s and s.ownerFaction and s.ownerFaction.name == fac.name end

local handlers = {}

function handlers.send_gold(fac, o, target)
    if o.amount <= 0 then return "amount must be positive" end
    if fac.money < o.amount then return "treasury too low (" .. fac.money .. ")" end
    fac.money = fac.money - o.amount
    target.money = target.money + o.amount
end

function handlers.cede_settlement(fac, o, target, map)
    local s = map:getSettlement(o.settlement)
    if not owned(fac, s) then return "settlement '" .. tostring(o.settlement) .. "' not owned" end
    s:changeOwner(target, true)
end

function handlers.set_stance(fac, o, target, map, campaign)
    local rel = dipRelType[o.stance]
    if rel == nil then return "unknown stance '" .. tostring(o.stance) .. "'" end
    campaign:setDipStance(rel, fac, target)
end

local function general(fac, id)
    local st = find_army(fac, id)
    if not st then return nil, "unknown army '" .. tostring(id) .. "'" end
    if not st.leader then return nil, "army '" .. id .. "' has no general to command" end
    return st
end

function handlers.march_on(fac, o, _, map)
    local st, err = general(fac, o.army)
    if not st then return err end
    local s = map:getSettlement(o.target_settlement)
    if not s then return "unknown settlement '" .. tostring(o.target_settlement) .. "'" end
    st.leader:moveToTile(s.xCoord, s.yCoord)
end

function handlers.besiege(fac, o, _, map)
    local st, err = general(fac, o.army)
    if not st then return err end
    local s = map:getSettlement(o.settlement)
    if not s then return "unknown settlement '" .. tostring(o.settlement) .. "'" end
    if owned(fac, s) then return "cannot besiege own settlement" end
    st:siegeSettlement(s, false)
end

function handlers.withdraw(fac, o, _, map)
    local st, err = general(fac, o.army)
    if not st then return err end
    local s = map:getSettlement(o.to_settlement)
    if not owned(fac, s) then return "settlement '" .. tostring(o.to_settlement) .. "' not owned" end
    st.leader:moveToTile(s.xCoord, s.yCoord)
end

local function apply(fac, o)
    local campaign, map = gd.campaignStruct, gd.stratMap
    local handler = handlers[o.type]
    if not handler then return "unknown order type '" .. tostring(o.type) .. "'" end
    local target
    if o.to ~= nil then
        target = campaign:getFaction(o.to)
        if not target or o.to == fac.name then return "unknown faction '" .. tostring(o.to) .. "'" end
    end
    return handler(fac, o, target, map, campaign)
end

-- --- event entry points --------------------------------------------------------------

function M.on_turn_end(fac)
    local cfg = config()
    if not cfg or not cfg.factions[fac.name] then return end
    local ok, err = pcall(function()
        local dir = turn_dir(cfg, gd.campaignStruct.turnNumber, fac.name)
        local done, werr = atomic_write(dir .. "/state.json", encode(M.report(fac, cfg)))
        if not done then log(fac.name .. ": cannot write report in " .. dir .. ": " .. tostring(werr)) end
    end)
    if not ok then log(fac.name .. ": report failed: " .. tostring(err)) end
end

function M.on_turn_start(fac)
    local cfg = config()
    if not cfg or not cfg.factions[fac.name] then return end
    local turn = gd.campaignStruct.turnNumber
    -- the orchestrator makes turn folders from this (Lua can't create directories)
    atomic_write(root .. "/heartbeat.txt", "turn=" .. turn .. "\n")
    local dir = turn_dir(cfg, turn - 1, fac.name)
    if applied[dir] then return end
    applied[dir] = true
    local text = read_file(dir .. "/orders.json")
    if not text then
        -- too late now: mark it, so orders that arrive later are reported back as late
        atomic_write(dir .. "/late.txt", "")
        log(fac.name .. ": no orders for turn " .. (turn - 1) .. " in time; skipped")
        return
    end
    local okd, orders = pcall(json.decode, text)
    if not okd or type(orders) ~= "table" or type(orders.orders) ~= "table" then
        log(fac.name .. ": orders unreadable in " .. dir .. ": " .. tostring(orders))
        return
    end
    local results = {}
    for i, o in ipairs(orders.orders) do
        local ok, reason = pcall(apply, fac, o)
        if not ok then reason = "error: " .. tostring(reason) end
        results[#results + 1] = { index = i - 1, type = tostring(o.type), ok = reason == nil,
                                  reason = reason or "" }
        log(string.format("%s order %d %s: %s", fac.name, i - 1, tostring(o.type), reason or "done"))
    end
    atomic_write(dir .. "/results.json", encode(results))
end

function M.setup(turn_root)
    root = turn_root
    gd = gameDataAll.get()
    applied = {}
end

return M
