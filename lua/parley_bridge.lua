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
    local cfg = { factions = {}, control = {} }  -- control: faction -> areas; absent = ruler
    for line in text:gmatch("[^\r\n]+") do
        local k, v = line:match("^([%w_]+)=(.+)$")
        if k == "game_id" then cfg.game_id = v
        elseif k == "faction" then cfg.factions[v] = true
        elseif k == "control" then
            local f, areas = v:match("^([%w_]+):(.*)$")
            if f then
                cfg.control[f] = {}
                for a in areas:gmatch("[%w_]+") do cfg.control[f][a] = true end
            end
        elseif k == "autoplay" then cfg.autoplay = v == "1"
        elseif k == "autoplay_wait" then cfg.wait = tonumber(v)
        elseif k == "autoplay_until" then cfg.until_turn = tonumber(v) end
    end
    return cfg.game_id and cfg or nil
end

-- which control area each order belongs to (parley/control.py ORDER_AREA)
local ORDER_AREA = {
    send_gold = "diplomacy", cede_settlement = "diplomacy", set_stance = "diplomacy",
    march_on = "armies", besiege = "armies", withdraw = "armies", move_army = "armies", attack = "armies",
    merge_units = "armies", disband = "armies",
    merge_armies = "armies", board = "armies", land = "armies", blockade = "armies",
    assassinate = "agents", spy = "agents", bribe = "agents", sabotage = "agents",
    move_agent = "agents", marry = "agents",
    build = "build", recruit = "recruit", retrain = "recruit", set_tax = "taxes",
}
local RULER_AREAS = { diplomacy = true, armies = true, agents = true }

local function areas_of(cfg, faction) return cfg.control[faction] or RULER_AREAS end

local function turn_dir(cfg, turn, faction)
    return string.format("%s/%s/turn-%04d/%s", root, cfg.game_id, turn, faction)
end

-- --- reading the game ----------------------------------------------------------------

-- live names can carry a " (null)" surname and underscores: "Rufus (null)", "Charles of_Hastings".
-- Ids are written clean; a name in an order matches clean or raw (seen live: a merge into
-- "Henry" failed because the id read "Henry (null)").
local function clean_name(name)
    if name == nil then return nil end  -- a broken character has none: still skipped
    return (tostring(name):gsub(" %(null%)$", ""):gsub("_", " "))
end

local function same(a, b)
    return a == b or (a ~= nil and b ~= nil and clean_name(a) == clean_name(b))
end

local function name_of(c)  -- a character's (or a named character's) clean full name
    local nc = c.namedCharacter or c
    return clean_name(nc.fullName)
end

local function stance(campaign, a, b)
    if campaign:checkDipStance(dipRelType.war, a, b) then return "war" end
    if campaign:checkDipStance(dipRelType.alliance, a, b) then return "alliance" end
    if campaign:checkDipStance(dipRelType.peace, a, b) then return "peace" end
    return "neutral"
end

-- A stack's general. EOP gives a stack inside a settlement no leader, even when a general is
-- in there (a general who marches into a settlement takes command of its garrison), so look for
-- the faction's general standing on the settlement's tile.
-- where a leaderless stack is: its settlement, or the fleet carrying it (EOP gives a stack
-- aboard a ship no leader either; its position is the fleet's)
local function residence(st)
    local s = st:findInSettlement()
    if s then return s.xCoord, s.yCoord, s end
    if st.shipArmy and st.shipArmy.leader then return st.shipArmy.leader.xCoord, st.shipArmy.leader.yCoord end
end

local function leader_of(fac, st)
    if st.leader then return st.leader end
    local x, y = residence(st)
    if not x or not fac then return nil end
    for i = 0, (fac.numOfCharacters or 0) - 1 do
        local ok, c = pcall(function()
            local c = fac:getCharacter(i)
            local t = c and c:getTypeName()
            if (t == "general" or t == "named_character" or t == "named character")
                and c.xCoord == x and c.yCoord == y then return c end
        end)
        if ok and c then return c end
    end
end

-- A stack in a settlement keeps the garrison's id even with a general inside (the report names
-- him as its leader): moving him takes only him and his bodyguard, as seen live. An army aboard
-- a fleet goes by its general's name.
local function base_id(fac, st, index)
    if st.leader then return name_of(st.leader) end
    if st.shipArmy then
        local general = leader_of(fac, st)
        if general then return name_of(general) end
    end
    local s = st:findInSettlement()
    if s then return "garrison:" .. s.name end
    return "stack:" .. index
end

-- IDs for a faction's stacks, in getStack order; repeated names get #2, #3...
local function army_ids(fac)
    local ids, seen = {}, {}
    for i = 0, fac.stacksNum - 1 do
        local id = base_id(fac, fac:getStack(i), i)
        seen[id] = (seen[id] or 0) + 1
        ids[i] = seen[id] > 1 and (id .. "#" .. seen[id]) or id
    end
    return ids
end

-- fac: the stack's own faction, to find a general inside a settlement (nil for foreign stacks
-- in sight, which are only ever field armies)
local function army_view(st, id, fac)
    local s = st:findInSettlement()
    local leader = leader_of(fac, st)
    local x, y = residence(st)
    if not x and leader then x, y = leader.xCoord, leader.yCoord end
    local view = {  -- nil fields are left out; the orchestrator reads a missing key as "none"
        id = id,
        leader = leader and name_of(leader) or nil,
        x = x or 0, y = y or 0, strength = st.totalStrength, units = st.numOfUnits,
        in_settlement = s and s.name or nil,
    }
    pcall(function()  -- fleets: what they carry; armies at sea: which fleet
        if st.isAdmiral then
            view.is_fleet = true
            view.carrying = st.boardedArmy and st.boardedArmy.numOfUnits or nil
        end
        if st.shipArmy and st.shipArmy.leader then view.aboard = name_of(st.shipArmy.leader) end
    end)
    return view
end

-- --- sight ------------------------------------------------------------------------------
-- EOP has no "visible now" query (getTileVisibility is ever-seen), so sight is a radius
-- around everything the faction has on the map: generals, agents and settlements.

local SIGHT_RADIUS = 10
local SIGHT_MAX = 12  -- nearest entries kept per list
local AGENT_KINDS = { spy = true, assassin = true, diplomat = true, merchant = true,
                      priest = true, princess = true, admiral = true }
local AGENT_KIND = { assassinate = "assassin", sabotage = "assassin", spy = "spy", bribe = "diplomat" }

local GENERAL_TYPES = { general = true, named_character = true, ["named character"] = true }

local function agent_kind(c)
    local t = c:getTypeName()
    if GENERAL_TYPES[t] then return nil end  -- they lead armies
    return AGENT_KINDS[t] and t or "other"
end

-- Give each entry an id from its name, unique within the list: the 2nd "Ulrich" is Ulrich#2.
-- Call it on a list in game order (faction, then getCharacter/getStack index), never in
-- distance order, so the same character keeps the same id from report to orders.
local function assign_ids(list)
    local seen = {}
    for _, e in ipairs(list) do
        seen[e.name] = (seen[e.name] or 0) + 1
        e.id = seen[e.name] > 1 and (e.name .. "#" .. seen[e.name]) or e.name
    end
    return list
end

-- a faction's agents (not generals) as { id, name, kind, char }, in getCharacter order
local function agents_of(f)
    local list = {}
    for i = 0, (f.numOfCharacters or 0) - 1 do
        local ok, c, kind, name = pcall(function()
            local c = f:getCharacter(i)
            if not c then return nil end
            local kind = agent_kind(c)
            return c, kind, kind and name_of(c)
        end)
        if ok and kind and name then list[#list + 1] = { name = name, kind = kind, char = c } end
    end
    return assign_ids(list)
end

-- namedCharacter.status is bit flags (EOP's docs say "5 leader, 2 heir"; live: 1, 2, 164...):
-- bit 1 the leader, bit 2 the heir, as EOP's own onlineThings.cpp tests them
local function role_of(status)
    if status % 2 == 1 then return "leader" end
    if math.floor(status / 2) % 2 == 1 then return "heir" end
end


-- Every named character the faction has kept a record of, the dead and the off-map included
-- (a dead one has no on-map character, so its kind is unknown): name, age, kind, alive, family,
-- spouse and parent. Each field is read on its own, so one bad read doesn't lose the person.
local function family_of(f)
    local list = {}
    for i = 0, (f.numOfNamedCharacters or 0) - 1 do
        local ok, nc = pcall(function() return f:getNamedCharacter(i) end)
        local okn, name = pcall(function() return nc.fullName end)
        if ok and nc and okn and name and name ~= "" then
            local p = { name = clean_name(name) }
            local function read(key, fn) local okr, v = pcall(fn); if okr and v ~= nil then p[key] = v end end
            read("age", function() return nc.age end)
            read("alive", function() return nc:isAlive() end)
            read("male", function() return nc.isMale end)
            read("family", function() return nc.isFamily end)
            if type(p.alive) == "number" then p.alive = p.alive ~= 0 end
            -- the dead keep stale pointers (character, spouse, parent): a native read through
            -- one can crash the game, which pcall can't catch, so they get name, age and status
            if p.alive ~= false then
                read("off_map", function() return nc:isOffMap() end)
                read("role", function() return role_of(nc.status) end)
                read("kind", function()
                    local t = nc.character:getTypeName()
                    return GENERAL_TYPES[t] and "general" or t
                end)
                -- where they stand (Scratch, live: "Missing: where Garret Harrold is standing,
                -- and which army he leads"); the prompt names the army or settlement there
                read("x", function() return nc.character.xCoord end)
                read("y", function() return nc.character.yCoord end)
                read("spouse", function() return nc.spouse and clean_name(nc.spouse.fullName) end)
                read("spouse_faction", function() return nc.spouse and nc.spouse.faction.name end)
                read("parent", function() return nc.parent and clean_name(nc.parent.fullName) end)
            end
            for _, k in ipairs({ "male", "family", "off_map" }) do
                if type(p[k]) == "number" then p[k] = p[k] ~= 0 end  -- some EOP flags are 0/1
            end
            list[#list + 1] = p
        end
    end
    return list
end

-- Someone the faction's records list as dead may be alive elsewhere: a general who went over to
-- the rebels, an agent bribed away (seen live: Captain Godwine, "dead" to England, alive among
-- the rebels near Frankfurt). Sets now_serves on such entries, from every other faction's records.
local function whereabouts(fac, family)
    local lost = {}
    for _, p in ipairs(family) do
        if p.alive == false then lost[p.name] = p end
    end
    if not next(lost) then return end
    for i = 0, stratmap.game.getFactionsCount() - 1 do
        local other = stratmap.game.getFaction(i)
        if other and other.name ~= fac.name then
            for j = 0, (other.numOfNamedCharacters or 0) - 1 do
                pcall(function()
                    local nc = other:getNamedCharacter(j)
                    local p = lost[clean_name(nc.fullName)]
                    local alive = p and nc:isAlive()
                    if p and (alive == true or alive == 1) then p.now_serves = other.name end
                end)
            end
        end
    end
end

local function eyes_of(fac)
    local eyes = {}
    for i = 0, fac.settlementsNum - 1 do
        local s = fac:getSettlement(i)
        eyes[#eyes + 1] = { s.xCoord, s.yCoord }
    end
    for i = 0, fac.stacksNum - 1 do
        local st = fac:getStack(i)
        if st.leader then eyes[#eyes + 1] = { st.leader.xCoord, st.leader.yCoord } end
    end
    for _, a in ipairs(agents_of(fac)) do eyes[#eyes + 1] = { a.char.xCoord, a.char.yCoord } end
    return eyes
end

local function distance(eyes, x, y)
    local best
    for _, e in ipairs(eyes) do
        local d = math.max(math.abs(e[1] - x), math.abs(e[2] - y))
        if not best or d < best then best = d end
    end
    return best
end

-- nearest first (ties keep game order: LuaJIT's sort isn't stable), at most SIGHT_MAX
local function nearest(list)
    for i, e in ipairs(list) do e.seq = i end
    table.sort(list, function(a, b)
        if a.view.distance ~= b.view.distance then return a.view.distance < b.view.distance end
        return a.seq < b.seq
    end)
    while #list > SIGHT_MAX do table.remove(list) end
    return list
end

-- Land crossings: the green-arrow straits an army walks across (the author: "the game should inform
-- llms of crossings"; Scratch planned ships for Dublin, unaware he could walk). EOP's tile
-- isLandConnection marks them. The map is scanned once, on first use, and the crossings kept
-- as { x, y, from, to } (the regions on either side).
local crossings_cache

local function all_crossings()
    if crossings_cache then return crossings_cache end
    local map, found = gd.stratMap, {}
    for y = 0, (map.mapHeight or 0) - 1 do
        for x = 0, (map.mapWidth or 0) - 1 do
            -- green-arrow straits (live: Gibraltar, the Bosphorus) and the "close proximity" sea
            -- crossings (live: seven tiles, one at 94,168 between Ireland and Scotland); hasCrossing
            -- (148 tiles) is river fords and bridges, not straits
            local ok, yes = pcall(function()
                local t = map.getTile(x, y)
                local a, b = t.isLandConnection, t.isSeaCrossing
                return a == true or a == 1 or b == true or b == 1
            end)
            if ok and yes then found[#found + 1] = { x = x, y = y } end
        end
    end
    -- one crossing per group of neighbouring tiles; its ends are the land regions around it
    local seen, list = {}, {}
    for _, t in ipairs(found) do
        local key = t.x .. "," .. t.y
        if not seen[key] then
            local group, stack = {}, { t }
            seen[key] = true
            while #stack > 0 do
                local c = table.remove(stack)
                group[#group + 1] = c
                for _, o in ipairs(found) do
                    local k = o.x .. "," .. o.y
                    if not seen[k] and math.abs(o.x - c.x) <= 1 and math.abs(o.y - c.y) <= 1 then
                        seen[k] = true
                        stack[#stack + 1] = o
                    end
                end
            end
            local regions, sx, sy = {}, 0, 0
            for _, c in ipairs(group) do
                sx, sy = sx + c.x, sy + c.y
                for dx = -1, 1 do
                    for dy = -1, 1 do
                        pcall(function()
                            local tile = map.getTile(c.x + dx, c.y + dy)
                            if tile.isLand == 1 or tile.isLand == true then
                                regions[map.getRegion(tile.regionID).regionName] = true
                            end
                        end)
                    end
                end
            end
            local names = {}
            for n in pairs(regions) do names[#names + 1] = n end
            table.sort(names)
            list[#list + 1] = { x = math.floor(sx / #group + 0.5), y = math.floor(sy / #group + 0.5),
                                regions = names }
        end
    end
    crossings_cache = list
    return list
end

-- the crossings within reach of fac (twice its sight), nearest first
function M.crossings(fac)
    local eyes, list = eyes_of(fac), {}
    for _, c in ipairs(all_crossings()) do
        local d = distance(eyes, c.x, c.y)
        if d and d <= 3 * SIGHT_RADIUS then
            list[#list + 1] = { x = c.x, y = c.y, regions = c.regions, distance = d }
        end
    end
    table.sort(list, function(a, b) return a.distance < b.distance end)
    return list
end

-- EOP's resourceType enum, by number
local RESOURCE_NAMES = { [0] = "gold", "silver", "fish", "furs", "grain", "timber", "iron", "ivory",
    "wine", "slaves", "chocolate", "marble", "textiles", "dyes", "tobacco", "silk", "sugar",
    "sulfur", "tin", "spices", "cotton", "amber", "coal", "wool", "elephants", "camels", "dogs",
    "generic" }

-- Trade resources in sight, nearest first: where a merchant can stand to trade (the author: "why
-- aren't you using merchants... I see resources everywhere"). EOP: region:getResource(i) has
-- xCoord, yCoord, getResourceID(), getResourceValue().
function M.resources(fac)
    local map, eyes, list = gd.stratMap, eyes_of(fac), {}
    for r = 0, (map.regionsNum or 0) - 1 do
        pcall(function()
            local region = map.getRegion(r)
            for j = 0, (region.resourcesNum or 0) - 1 do
                local res = region:getResource(j)
                local d = distance(eyes, res.xCoord, res.yCoord)
                if d and d <= SIGHT_RADIUS then
                    local view = { kind = RESOURCE_NAMES[res:getResourceID()] or "unknown", x = res.xCoord,
                                   y = res.yCoord, distance = d, region = region.regionName }
                    pcall(function() view.value = res:getResourceValue() end)
                    pcall(function() view.owner = region.settlement.ownerFaction.name end)
                    list[#list + 1] = view
                end
            end
        end)
    end
    table.sort(list, function(a, b) return a.distance < b.distance end)
    while #list > SIGHT_MAX do table.remove(list) end
    return list
end

-- What fac can see now: { armies, agents, settlements }, each a list of { view, char|sett }.
-- Every foreign entity is read in its own pcall: one odd object is skipped, never fatal.
-- Armies and agents share one id space (an order names either), assigned in game order.
function M.sight(fac)
    local eyes = eyes_of(fac)
    local people, setts = {}, {}  -- people: foreign armies and agents in sight, game order
    for i = 0, stratmap.game.getFactionsCount() - 1 do
        local other = stratmap.game.getFaction(i)
        if other and other.name ~= fac.name then
            for j = 0, other.stacksNum - 1 do
                pcall(function()
                    local st = other:getStack(j)
                    if not st.leader or st:findInSettlement() then return end  -- garrisons: see settlements
                    local name = name_of(st.leader)
                    local d = distance(eyes, st.leader.xCoord, st.leader.yCoord)
                    if name and d and d <= SIGHT_RADIUS then
                        local view = army_view(st, name)
                        view.faction, view.distance = other.name, d
                        people[#people + 1] = { name = name, army = true, view = view, char = st.leader,
                                                stack = st }
                    end
                end)
            end
            for _, a in ipairs(agents_of(other)) do
                pcall(function()
                    local c = a.char
                    local d = distance(eyes, c.xCoord, c.yCoord)
                    if d and d <= SIGHT_RADIUS then
                        people[#people + 1] = { name = a.name, char = c, view = {
                            kind = a.kind, x = c.xCoord, y = c.yCoord, faction = other.name, distance = d } }
                    end
                end)
            end
        end
    end
    local armies, agents = {}, {}
    for _, e in ipairs(assign_ids(people)) do
        e.view.id = e.id
        table.insert(e.army and armies or agents, e)
    end
    local map = gd.stratMap
    for r = 0, (map.regionsNum or 0) - 1 do
        pcall(function()
            local s = map.getRegion(r).settlement
            if not s or not s.ownerFaction or s.ownerFaction.name == fac.name then return end
            local d = distance(eyes, s.xCoord, s.yCoord)
            if d and d <= SIGHT_RADIUS then
                setts[#setts + 1] = { sett = s, view = {
                    id = s.name, name = s.localizedName, faction = s.ownerFaction.name, x = s.xCoord, y = s.yCoord,
                    garrison_strength = s.army and s.army.totalStrength or 0, distance = d } }
            end
        end)
    end
    return { armies = nearest(armies), agents = nearest(agents), settlements = nearest(setts) }
end

local function views(list)
    local out = {}
    for _, e in ipairs(list) do out[#out + 1] = e.view end
    return out
end

-- Regular income and costs, turn after turn; one-off spending and receipts are kept apart
-- (seen live: bribing Bruges for 19464 showed as "income -19170").
local ECONOMY_IN = { "farmingIncome", "taxesIncome", "miningIncome", "tradeIncome", "merchantIncome",
                     "otherIncome1", "otherIncome2", "tributesIncome", "adminIncome", "kingsPurseIncome" }
local ECONOMY_OUT = { "wagesExpense", "upkeepExpense", "corruptionExpense", "tributesExpense",
                      "otherExpense1", "otherExpense2", "devastationExpense" }
local ONE_OFF_OUT = { "constructionExpenseBuildings", "constructionExpenseField",
                      "recruitmentExpenseBuildings", "recruitmentExpenseMercs", "diplomacyExpense" }
local ONE_OFF_IN = { "diplomacyIncome", "constructionIncome" }

-- (regular net income, one-off spending, one-off receipts) of the turn just played;
-- zeros if EOP can't say (the prompt reads income 0 as "not reported")
-- the regular items behind the net income, as { item = florins } (costs negative), the
-- nonzero ones: what a ruler needs to see what is bleeding him (asked live, turn after turn)
local INCOME_NAMES = { farmingIncome = "farming", taxesIncome = "taxes", miningIncome = "mining",
    tradeIncome = "trade", merchantIncome = "merchants", otherIncome1 = "other income",
    otherIncome2 = "other income", tributesIncome = "tribute received", adminIncome = "administration",
    kingsPurseIncome = "king's purse", wagesExpense = "wages (generals and agents)",
    upkeepExpense = "army upkeep", corruptionExpense = "corruption", tributesExpense = "tribute paid",
    otherExpense1 = "other costs", otherExpense2 = "other costs", devastationExpense = "devastation" }

local function income_parts(fac)
    local ok, parts = pcall(function()
        local e, parts = fac:getFactionEconomy(0), {}
        local function add(keys, sign)
            for _, k in ipairs(keys) do
                local v = math.floor((e[k] or 0) * sign)
                if v ~= 0 then
                    local name = INCOME_NAMES[k] or k
                    parts[name] = (parts[name] or 0) + v
                end
            end
        end
        add(ECONOMY_IN, 1)
        add(ECONOMY_OUT, -1)
        return parts
    end)
    return ok and parts or {}
end

local function income(fac)
    local ok, net, spent, got = pcall(function()
        local e = fac:getFactionEconomy(0)
        local function sum(keys)
            local n = 0
            for _, k in ipairs(keys) do n = n + (e[k] or 0) end
            return n
        end
        return sum(ECONOMY_IN) - sum(ECONOMY_OUT), sum(ONE_OFF_OUT), sum(ONE_OFF_IN)
    end)
    if not ok then return 0, 0, 0 end
    return math.floor(net), math.floor(spent), math.floor(got)
end

-- --- what a player sees of its own realm (only for the areas a seat commands) ----------
-- Tax levels: the game's tax_low..tax_extortionate, assumed 0..3 (unverified in EOP's source).
local TAX_NAMES = { [0] = "low", [1] = "normal", [2] = "high", [3] = "extortionate" }
local TAX_LEVELS = { low = 0, normal = 1, high = 2, extortionate = 3 }

-- { name, cost, turns, opt } for each building s can queue now
local function construction_options(s)
    local list, opts = {}, s:getConstructionOptions()
    for i = 0, (opts and opts.buildingNum or 0) - 1 do  -- 0-based, unchecked in EOP: stay in range
        local o = opts:getConstructionOption(i)
        if o then list[#list + 1] = { name = o:getQueueBuildingName(), cost = o.buildCost,
                                      turns = o.buildTurnsRemaining, opt = o } end
    end
    return list
end

-- EOP 3.3.1's getRecruitmentOptions copies its retraining entries from the wrong index
-- (settlementHelpers.cpp getRecruitOptions: available->units[i] from i = trainCount), reading
-- past an array in C++ before Lua sees the result. Retraining exists only for units inside the
-- settlement, so the list is only ever asked for when none are inside. Unknown counts as inside.
local function units_inside(s)
    return s.army ~= nil and (s.army.numOfUnits or 1) > 0
end

-- { name, cost, turns, edu, pool } for each unit s can recruit now, read from its recruitment
-- pools (the units its buildings allow, and how many are available) and the unit definitions.
-- EOP's own getRecruitmentOptions is never used: it reads past an array with units inside.
local function recruitment_options(s)
    local list = {}
    for i = 0, (s.recruitmentPoolCount or 0) - 1 do  -- 0-based; stay inside the count
        local p = s:getSettlementRecruitmentPool(i)
        if p and (p.availablePool or 0) >= 1 then
            local e = M2TWEOPDU.getEduEntry(p.eduIndex)
            if e and e.eduType then
                list[#list + 1] = { name = e.eduType, cost = e.recruitCost, turns = e.recruitTime,
                                    edu = p.eduIndex, pool = p }
            end
        end
    end
    return list
end

-- Recruits in training, kept in a file so a reload or a restart doesn't lose them:
-- { {faction, settlement, edu, unit, ready}, ... }; created at the faction's turn start once ready.
local function training_path() return root .. "/training.json" end

local function read_training()
    local text = read_file(training_path())
    local ok, list = pcall(json.decode, text or "[]")
    return (ok and type(list) == "table") and list or {}
end

local function deliver_training(fac, turn)
    local list, keep = read_training(), {}
    for _, t in ipairs(list) do
        if t.faction == fac.name and t.ready <= turn then
            local lost = false
            local ok, err = pcall(function()
                local s = gd.stratMap:getSettlement(t.settlement)
                if not (s and s.ownerFaction and s.ownerFaction.name == fac.name) then
                    lost = true
                    error("the settlement was lost")
                end
                if t.retrain then  -- refill the most worn unit of that type still in the garrison
                    local army, best = s.army, nil
                    for i = 0, (army and army.numOfUnits or 0) - 1 do
                        local u = army:getUnit(i)
                        if u and u.eduEntry.eduType == t.unit and u.soldierCountStratMap < u.soldierCountStratMapMax
                            and (not best or u.soldierCountStratMap < best.soldierCountStratMap) then best = u end
                    end
                    if not best then lost = true error("no worn " .. t.unit .. " left in the garrison") end
                    best.soldierCountStratMap = best.soldierCountStratMapMax
                    if best.soldierCountStratMap ~= best.soldierCountStratMapMax then error("the refill didn't take") end
                    return
                end
                local army = s.army or stratmap.game.createArmyInSettlement(s)
                if not army then error("no garrison to join") end
                army:createUnitByIDX(t.edu, 0, 0, 0)
            end)
            log(string.format("%s: %s %s in %s%s", fac.name, t.unit, t.retrain and "retrained" or "trained", t.settlement,
                ok and "" or (" FAILED: " .. tostring(err) .. (lost and "" or "; retrying next turn"))))
            if not ok and not lost then keep[#keep + 1] = t end
        else
            keep[#keep + 1] = t
        end
    end
    if #keep ~= #list then atomic_write(training_path(), encode(keep)) end
end

local function queue_of(s)
    local names, q = {}, s.buildingsQueue
    for pos = 1, (q and q.numBuildingsInQueue or 0) do  -- 1-based and bounds-checked in EOP
        local b = q:getBuildingInQueue(pos)
        if b then names[#names + 1] = b:getQueueBuildingName() end
    end
    return names
end

local function options_view(list)
    local out = {}
    for _, o in ipairs(list) do out[#out + 1] = { name = o.name, cost = o.cost, turns = o.turns } end
    return out
end

-- adds the management fields to a settlement view; each read on its own, so one missing
-- field costs only itself
-- what makes up a settlement's public order, as its details panel shows (live: Nottingham
-- rioted to the rebels after its garrison was disbanded to cut upkeep, the ruler unaware it held
-- order). Plain members of settlementStats, like PublicOrder itself.
local ORDER_PARTS = {
    garrison = "PublicOrderGarrison", law = "PublicOrderLaw", buildings = "PublicOrderBuildingsEntertainment",
    entertainment = "PublicOrderEntertainment", governor = "PublicOrderGovernorInfluence",
    ["low tax"] = "PublicOrderTaxBonus", ["high tax"] = "PublicOrderTaxPenalty", squalor = "PublicOrderSqualor",
    unrest = "PublicOrderUnrest", ["distance to capital"] = "PublicOrderDistanceToCapital",
    ["cultural unrest"] = "PublicOrderCulturalUnrest", health = "PublicOrderHealth", fear = "PublicOrderFear",
    glory = "PublicOrderGlory", excommunication = "PublicOrderExcommunication",
    ["no governor"] = "PublicOrderNoGovernance", besieged = "PublicOrderBesieged",
    blockaded = "PublicOrderBlockaded", ["population boom"] = "PublicOrderPopulationBoom",
}

local function add_management(view, s, areas)
    pcall(function()
        view.tax_level = TAX_NAMES[s.settlementTaxLevel]
        view.public_order = math.floor(s.settlementStats.PublicOrder)
    end)
    pcall(function()
        local stats, parts = s.settlementStats, {}
        for name, field in pairs(ORDER_PARTS) do
            local v = stats[field]
            if type(v) == "number" and v ~= 0 then parts[name] = math.floor(v) end
        end
        view.order_parts = parts
    end)
    if areas.build then
        pcall(function() view.queue = queue_of(s) end)
        pcall(function()
            view.can_build = {}
            for _, o in ipairs(construction_options(s)) do
                view.can_build[#view.can_build + 1] = { building = o.name, cost = o.cost, turns = o.turns }
            end
        end)
    end
    if areas.recruit then
        pcall(function()
            view.can_recruit = {}
            for _, o in ipairs(recruitment_options(s)) do
                view.can_recruit[#view.can_recruit + 1] = { unit = o.name, cost = o.cost, turns = o.turns }
            end
        end)
    end
end

local function add_troops(view, st)
    pcall(function()
        local troops = {}
        for i = 0, st.numOfUnits - 1 do
            local u = st:getUnit(i)
            if u then troops[#troops + 1] = { type = u.eduEntry.eduType, soldiers = u.soldierCountStratMap,
                                              max_soldiers = u.soldierCountStratMapMax, exp = u.exp } end
        end
        view.troops = troops
    end)
    if st.leader then
        pcall(function()
            view.moves_left = math.floor(st.leader.movePoints)
            view.moves_max = math.floor(st.leader.movePointsMaxArmy)
        end)
    end
end

function M.report(fac, cfg)
    local campaign, map = gd.campaignStruct, gd.stratMap
    local settlements, armies, factions = {}, {}, {}
    local areas = areas_of(cfg, fac.name)
    local manages = areas.build or areas.recruit or areas.taxes
    local training = read_training()
    for i = 0, fac.settlementsNum - 1 do
        local s = fac:getSettlement(i)
        local buildings = {}
        -- the level (small_church, not temple_catholic): an upgrade must show as a change
        for b = 0, s.buildingsNum - 1 do
            local bld = s:getBuilding(b)
            local ok, name = pcall(function() return bld:getName() end)
            buildings[#buildings + 1] = ok and name or bld:getType()
        end
        local view = {
            id = s.name, name = s.localizedName, region = map.getRegion(s.regionID).regionName,
            garrison_strength = s.army and s.army.totalStrength or 0,
            population = s.populationSize, buildings = buildings,
        }
        -- where it is, and its port (the tile a fleet docks at): asked for live, again and again
        pcall(function() view.x, view.y = s.xCoord, s.yCoord end)
        pcall(function()
            local r = map.getRegion(s.regionID)
            if (r.portEntranceXCoord or 0) > 0 then view.port_x, view.port_y = r.portEntranceXCoord, r.portEntranceYCoord end
        end)
        -- under siege: who, how strong, how long, how long it can hold (Scratch, live: "one of
        -- my settlements was reported besieged, and the report doesn't say which")
        pcall(function()
            if (s.siegesNum or 0) > 0 then
                local sg = s:getSiege(0)
                local st = sg.besieger
                local view_s = { turns = sg.siegeTurns, holdout = s.siegeHoldoutTurns }
                pcall(function() view_s.by = name_of(st.leader) end)
                pcall(function() view_s.faction = st.leader.namedCharacter.faction.name end)
                pcall(function() view_s.strength = st.totalStrength end)
                view.siege = view_s
            end
        end)
        for _, t in ipairs(training) do
            if t.faction == fac.name and t.settlement == s.name then
                view.training = view.training or {}
                view.training[#view.training + 1] = { unit = t.unit, ready_turn = t.ready }
            end
        end
        if manages then add_management(view, s, areas) end
        settlements[#settlements + 1] = view
    end
    local ids = army_ids(fac)
    for i = 0, fac.stacksNum - 1 do
        local st = fac:getStack(i)
        local view = army_view(st, ids[i], fac)
        if areas.armies and cfg.control[fac.name] then add_troops(view, st) end  -- not for plain rulers
        armies[#armies + 1] = view
    end
    for i = 0, stratmap.game.getFactionsCount() - 1 do
        local other = stratmap.game.getFaction(i)
        if other and other.name ~= fac.name and other.name ~= "slave" then
            local view = { id = other.name, name = other.localizedName, stance = stance(campaign, fac, other) }
            -- what a player's faction screen shows (live, the adviser: "Is Scotland no more?")
            local function put(k, f)
                local ok, v = pcall(f)
                if ok and v ~= nil then view[k] = v end
            end
            put("settlements", function() return other.settlementsNum end)
            put("armies", function() return other.stacksNum end)
            put("leader", function() return other.leader and clean_name(other.leader.fullName) end)
            put("capital", function() return other.capital and (other.capital.localizedName or other.capital.name) end)
            factions[#factions + 1] = view
        end
    end
    local agents = {}
    for _, a in ipairs(agents_of(fac)) do
        agents[#agents + 1] = { id = a.id, kind = a.kind, x = a.char.xCoord, y = a.char.yCoord }
    end
    local okf, family = pcall(family_of, fac)
    if not okf then
        log(fac.name .. ": family failed: " .. tostring(family))
        family = {}
    end
    pcall(whereabouts, fac, family)
    local ok, seen = pcall(M.sight, fac)
    if not ok then
        log(fac.name .. ": sight failed: " .. tostring(seen))
        seen = { armies = {}, agents = {}, settlements = {} }
    end
    local turn = campaign.turnNumber
    local last = read_file(turn_dir(cfg, turn - 1, fac.name) .. "/results.json")
    local net, spent, received = income(fac)
    return {
        protocol = 1, game_id = cfg.game_id, turn = turn, year = math.floor(campaign.currentDate),
        faction = fac.name, treasury = fac.money, income = net,
        spent_last_turn = spent, received_last_turn = received,
        settlements = settlements, armies = armies, factions = factions, agents = agents,
        visible_enemies = views(seen.armies), seen_agents = views(seen.agents),
        nearby_settlements = views(seen.settlements), last_results = last and json.decode(last) or {},
        human_slot = fac.isPlayerControlled == 1, map_width = map.mapWidth, map_height = map.mapHeight,
        popups = fac.isPlayerControlled == 1 and M.take_popups() or nil,
        agent_results = M.take_agent_news(fac.name),
        family = family, character_events = M.take_character_news(fac.name),
        news = M.take_faction_news(fac.name),
        income_parts = income_parts(fac),
        resources = (function() local ok, r = pcall(M.resources, fac); return ok and r or nil end)(),
        crossings = (function() local ok, r = pcall(M.crossings, fac); return ok and r or nil end)(),
        stance_changes = M.take_stance_news and M.take_stance_news(fac.name) or nil,
    }
end

-- --- applying orders -----------------------------------------------------------------

local function find_army(fac, id)
    local ids = army_ids(fac)
    for i = 0, fac.stacksNum - 1 do
        if same(ids[i], id) then return fac:getStack(i) end
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

-- stance orders applied this game, by pair: whose order and on which turn, so a change can be
-- told apart from one the game's own AI made (seen live: HRE's AI declared war on England
-- while HRE's ruler, ordering nothing, blamed England for every breach)
local stance_orders = {}

local function pair_key(a, b)
    return a < b and (a .. "|" .. b) or (b .. "|" .. a)
end

function handlers.set_stance(fac, o, target, map, campaign)
    local rel = dipRelType[o.stance]
    if rel == nil then return "unknown stance '" .. tostring(o.stance) .. "'" end
    campaign:setDipStance(rel, fac, target)
    stance_orders[pair_key(fac.name, target.name)] = { by = fac.name, turn = campaign.turnNumber, stance = o.stance }
    -- kept on disk: a reload must not forget whose order it was (live: it did, and a ruler's own
    -- peace was undone as if the game's AI had made it)
    pcall(function() atomic_write(root .. "/stance_orders.json", encode(stance_orders)) end)
end

function M.load_stance_orders()
    local ok, t = pcall(json.decode, read_file(root .. "/stance_orders.json") or "")
    if ok and type(t) == "table" then
        for k, v in pairs(t) do stance_orders[k] = v end
    end
end

local function general(fac, id)
    local st = find_army(fac, id)
    if not st then return nil, "unknown army '" .. tostring(id) .. "'" end
    local leader = leader_of(fac, st)
    if not leader then return nil, "army '" .. id .. "' has no general to command (merge it into one that has)" end
    return st, leader
end

function handlers.march_on(fac, o, _, map)
    local st, leader = general(fac, o.army)
    if not st then return leader end  -- on failure the second value is the reason
    local s = map:getSettlement(o.target_settlement)
    if not s then return "unknown settlement '" .. tostring(o.target_settlement) .. "'" end
    leader:moveToTile(s.xCoord, s.yCoord)
end

function handlers.besiege(fac, o, _, map)
    local st, leader = general(fac, o.army)
    if not st then return leader end  -- on failure the second value is the reason
    local s = map:getSettlement(o.settlement)
    if not s then return "unknown settlement '" .. tostring(o.settlement) .. "'" end
    if owned(fac, s) then return "cannot besiege own settlement" end
    local assault = o.assault == true
    -- the human slot's siege scroll asks again: autoplay answers it as the ruler ordered
    if assault then M.assault_ordered = true end
    st:siegeSettlement(s, assault)
end

function handlers.withdraw(fac, o, _, map)
    local st, leader = general(fac, o.army)
    if not st then return leader end  -- on failure the second value is the reason
    local s = map:getSettlement(o.to_settlement)
    if not owned(fac, s) then return "settlement '" .. tostring(o.to_settlement) .. "' not owned" end
    leader:moveToTile(s.xCoord, s.yCoord)
end

-- --- player orders: build, recruit, taxes, move, attack -------------------------------------

local function own_settlement(fac, map, name)
    local s = map:getSettlement(name)
    if not owned(fac, s) then return nil, "settlement '" .. tostring(name) .. "' not owned" end
    return s
end

-- queue an option found by name in list(s); EOP's queue calls don't say whether they check gold
local function queue(fac, s, list, name, what)
    for _, o in ipairs(list) do
        if o.name == name then
            if fac.money < o.cost then return "treasury too low (" .. fac.money .. ", needs " .. o.cost .. ")" end
            local before = fac.money
            local ok = what == "build" and o.opt:addBuildingToQueue() or what == "recruit" and o.opt:addUnitToQueue()
            -- unverified whether the game charges when queueing: the log is the evidence
            log(string.format("%s %s %s in %s: treasury %d -> %d", fac.name, what, name, s.name, before, fac.money))
            if not ok then return "the game refused to queue '" .. name .. "' (queue full?)" end
            return nil
        end
    end
    local can = {}
    for _, o in ipairs(list) do can[#can + 1] = o.name end
    return s.name .. " can't " .. what .. " '" .. tostring(name) .. "' now (can: " ..
        (#can > 0 and table.concat(can, ", ") or "nothing") .. ")"
end

function handlers.build(fac, o, _, map)
    local s, err = own_settlement(fac, map, o.settlement)
    if not s then return err end
    local okq, queued = pcall(queue_of, s)
    for _, name in ipairs(okq and queued or {}) do
        if name == o.building then return "'" .. name .. "' is already in " .. s.name .. "'s queue" end
    end
    return queue(fac, s, construction_options(s), o.building, "build")
end

-- Recruit like the game does: pay the unit's cost, take one from the settlement's pool, and the
-- unit joins the garrison when its training time is up (at the faction's turn start). Not
-- modelled: the queue's slot limit.
function handlers.recruit(fac, o, _, map, campaign)
    local s, err = own_settlement(fac, map, o.settlement)
    if not s then return err end
    local options = recruitment_options(s)
    for _, r in ipairs(options) do
        if r.name == o.unit then
            if fac.money < r.cost then return "treasury too low (" .. fac.money .. ", needs " .. r.cost .. ")" end
            fac.money = fac.money - r.cost
            r.pool.availablePool = r.pool.availablePool - 1
            local list = read_training()
            list[#list + 1] = { faction = fac.name, settlement = s.name, edu = r.edu, unit = r.name,
                                ready = campaign.turnNumber + math.max(1, r.turns or 1) }
            atomic_write(training_path(), encode(list))
            log(string.format("%s recruits %s in %s for %d; ready turn %d", fac.name, r.name, s.name,
                r.cost, list[#list].ready))
            return nil
        end
    end
    local can = {}
    for _, r in ipairs(options) do can[#can + 1] = r.name end
    return s.name .. " can't recruit '" .. tostring(o.unit) .. "' now (can: " ..
        (#can > 0 and table.concat(can, ", ") or "nothing") .. ")"
end

function handlers.set_tax(fac, o, _, map)
    local s, err = own_settlement(fac, map, o.settlement)
    if not s then return err end
    local level = TAX_LEVELS[o.level]
    if level == nil then return "unknown tax level '" .. tostring(o.level) .. "'" end
    s.settlementTaxLevel = level
end

-- Work the game's own screens for what EOP can't do (retraining): a queue of jobs, run a step at
-- a time on the human slot's turn while End Turn waits (see run_ui_job)
local ui_jobs = {}

-- Retrain like the game's Retrain tab, by direct write, for any faction (the author: direct write
-- wherever possible). A damaged unit in the garrison is refilled when its type has one in the
-- settlement's recruitment pool: the tab greys it out otherwise ("No more units of this type
-- available for retraining", live). It pays the missing share of the recruit cost, takes one from
-- the pool, and the men arrive at the faction's next turn start (deliver_training). Not modelled:
-- armour and weapon upgrades, the queue's slot limit. (The screen route clicked cards the game
-- refused, and every refusal rang the game's error bell.)
function handlers.retrain(fac, o, _, map, campaign)
    local s, err = own_settlement(fac, map, o.settlement)
    if not s then return err end
    local army = s.army
    if not army then return s.name .. " has no garrison to retrain" end
    local options, list, done, spent = recruitment_options(s), read_training(), {}, 0
    -- the most worn first, as many as the settlement's training slots (live, the Retrain tab:
    -- Nottingham, a minor city, 2; London, a large city, 3; the rest of the table is inferred)
    local worn = {}
    for i = 0, army.numOfUnits - 1 do
        local u = army:getUnit(i)
        local have, max = u and u.soldierCountStratMap, u and u.soldierCountStratMapMax
        if have and max and have < max then worn[#worn + 1] = { u = u, have = have, max = max } end
    end
    table.sort(worn, function(a, b) return a.have / a.max < b.have / b.max end)
    local okl, level = pcall(function() return s.level end)
    local slots = math.max(1, (okl and type(level) == "number" and level or 3) - 1)
    for _, w in ipairs(worn) do
        if #done >= slots then break end
        local u, have, max = w.u, w.have, w.max
        do
            for _, r in ipairs(options) do
                if r.name == u.eduEntry.eduType and r.pool.availablePool >= 1 then
                    local price = math.ceil((r.cost or 0) * (max - have) / max)
                    if fac.money >= price then
                        fac.money = fac.money - price
                        r.pool.availablePool = r.pool.availablePool - 1
                        spent = spent + price
                        list[#list + 1] = { faction = fac.name, settlement = s.name, retrain = true, unit = r.name,
                                            from = have, ready = campaign.turnNumber + 1 }
                        done[#done + 1] = string.format("%s %d/%d", r.name, have, max)
                    end
                    break
                end
            end
        end
    end
    if #done == 0 then return s.name .. ": nothing to retrain (no damaged unit whose type its pool still offers, or too little gold)" end
    atomic_write(training_path(), encode(list))
    log(string.format("%s retrains in %s for %d: %s", fac.name, s.name, spent, table.concat(done, ", ")))
end

-- a map tile, or nil off the map (getTile doesn't check bounds). Live: getTile is a dot call
-- on the map object, not on the global stratmap table.
local function tile_at(x, y)
    local map = gd.stratMap
    if type(x) ~= "number" or type(y) ~= "number" or not (map.mapWidth and map.mapHeight) then return nil end
    x, y = math.floor(x), math.floor(y)
    if x < 0 or y < 0 or x >= map.mapWidth or y >= map.mapHeight then return nil end
    return map.getTile(x, y)
end

-- tile.isLand is 0 or 1 live, and 0 is truthy in Lua
local function is_land(tile) return tile.isLand == true or tile.isLand == 1 end

-- Ships. There is no boarding call: as with a player's right-click, moving onto a fleet's tile
-- boards it and moving from a ship onto a land tile lands. Untested live: the next report shows
-- whether it worked (an army aboard is listed "aboard <fleet>").
local function own_fleet(fac, id)
    local st = find_army(fac, id)
    if not st then return nil, "unknown fleet '" .. tostring(id) .. "'" end
    if not st.isAdmiral or not st.leader then return nil, "'" .. id .. "' is not a fleet" end
    return st
end

function handlers.board(fac, o)
    local fleet, err = own_fleet(fac, o.fleet)
    if not fleet then return err end
    local x, y = fleet.leader.xCoord, fleet.leader.yCoord
    local agent
    for _, a in ipairs(agents_of(fac)) do
        if same(a.id, o.who) then agent = a end
    end
    if agent then
        agent.char:moveToTile(x, y)
        return nil
    end
    local st, leader = general(fac, o.who)
    if not st then return leader end
    if fleet.boardedArmy then return "'" .. o.fleet .. "' already carries an army (one per fleet)" end
    leader:moveToTile(x, y)
end

function handlers.land(fac, o)
    local st = find_army(fac, o.army)
    if not st then return "unknown army '" .. tostring(o.army) .. "'" end
    if not st.shipArmy then return "'" .. o.army .. "' is not aboard a fleet" end
    local leader = leader_of(fac, st)
    if not leader then return "'" .. o.army .. "' has no general to lead it ashore" end
    local tile = tile_at(o.x, o.y)
    if not tile then return "(" .. tostring(o.x) .. "," .. tostring(o.y) .. ") is off the map" end
    if not is_land(tile) then return "(" .. o.x .. "," .. o.y .. ") is not land; land on a tile next to the fleet" end
    leader:moveToTile(math.floor(o.x), math.floor(o.y))
end

function handlers.blockade(fac, o, _, map)
    local fleet, err = own_fleet(fac, o.fleet)
    if not fleet then return err end
    local s = map:getSettlement(o.settlement)
    if not s then return "unknown settlement '" .. tostring(o.settlement) .. "'" end
    if owned(fac, s) then return "cannot blockade your own port" end
    local region = map.getRegion(s.regionID)
    local tile = region and tile_at(region.portEntranceXCoord, region.portEntranceYCoord)
    local port = tile and tile.port
    if not port then return s.name .. " has no port to blockade" end
    if not fleet:blockadePort(port) then return "the game refused the blockade (out of reach?)" end
end

-- a general of this faction by his own name, leading an army or not (live: four generals stood
-- in Dublin's garrison, none leading it, and the ruler could not move one out alone)
local function general_named(fac, name)
    for i = 0, (fac.numOfCharacters or 0) - 1 do
        local ok, c = pcall(function()
            local c = fac:getCharacter(i)
            local t = c and c:getTypeName()
            if (t == "general" or t == "named_character" or t == "named character")
                and same(name_of(c), name) then return c end
        end)
        if ok and c then return c end
    end
end

local function own_fleet_at(fac, x, y)
    for i = 0, fac.stacksNum - 1 do
        local st = fac:getStack(i)
        if st and st.isAdmiral and st.leader and st.leader.xCoord == x and st.leader.yCoord == y then return true end
    end
end

-- the land tile nearest (x, y), within a few tiles, or nil
local function nearest_land(x, y)
    for r = 1, 3 do
        for dx = -r, r do
            for dy = -r, r do
                if math.max(math.abs(dx), math.abs(dy)) == r then
                    local t = tile_at(x + dx, y + dy)
                    if t and is_land(t) then return x + dx, y + dy end
                end
            end
        end
    end
end

function handlers.move_army(fac, o)
    local st, leader = general(fac, o.army)
    if not st then
        local c = general_named(fac, o.army)
        if not c then return leader end  -- on failure the second value is the reason
        st, leader = { isAdmiral = false }, c
    end
    if type(o.x) ~= "number" or type(o.y) ~= "number" then return "move_army needs x and y" end
    local x, y, map = math.floor(o.x), math.floor(o.y), gd.stratMap
    if not (map.mapWidth and map.mapHeight and x >= 0 and y >= 0 and x < map.mapWidth and y < map.mapHeight) then
        return "(" .. x .. "," .. y .. ") is off the map"
    end
    local tile = tile_at(x, y)
    if st.isAdmiral then
        if tile and is_land(tile) then return "a fleet can't sail onto land (" .. x .. "," .. y .. ")" end
    elseif tile and not is_land(tile) and not own_fleet_at(fac, x, y) then
        -- live: an order to sea came back "done" and the army never moved
        local lx, ly = nearest_land(x, y)
        return "(" .. x .. "," .. y .. ") is sea" .. (lx and ("; the nearest land is (" .. lx .. "," .. ly .. ")") or "")
    end
    leader:moveToTile(x, y)
end

function handlers.attack(fac, o)
    local st, leader = general(fac, o.army)
    if not st then return leader end  -- on failure the second value is the reason
    for _, e in ipairs(M.sight(fac).armies) do
        if same(e.view.id, o.target) then
            -- ids follow names and sight, which shift between the report and now: attack only the
            -- faction the ruler meant
            if o.target_faction and e.view.faction ~= o.target_faction then
                return "'" .. o.target .. "' is now " .. tostring(e.view.faction) .. "'s army, not " ..
                    o.target_faction .. "'s; not attacking"
            end
            if st:attackArmy(e.stack) ~= 1 then
                return "the game refused the attack (out of reach or no moves left)"
            end
            return nil
        end
    end
    return "target '" .. tostring(o.target) .. "' is not in sight"
end

-- Within one army, fold under-strength units of the same type (and armour and weapon level)
-- together, as the game's own merge does: soldiers pour from the weakest into the fullest unit,
-- never past its maximum, experience averaged by soldiers; emptied units disband. EOP has no
-- merge call, so it is done with the unit's own setParams and kill. A general's bodyguard (a
-- unit with a character) and a unit retraining are left alone. (the author: "4 hobilar units and some
-- of them are less than half, they need to be full strength as much as possible".)
function handlers.merge_units(fac, o)
    local st = find_army(fac, o.army)
    if not st then return "unknown army '" .. tostring(o.army) .. "'" end
    local groups = {}
    for i = 0, st.numOfUnits - 1 do
        local u = st:getUnit(i)
        local ok, key = pcall(function()
            if u.character or u.retrainingSettlement then return nil end
            return u.eduEntry.eduType .. "|" .. (u.armourLVL or 0) .. "|" .. (u.weaponLVL or 0)
        end)
        if ok and key then
            groups[key] = groups[key] or {}
            table.insert(groups[key], u)
        end
    end
    -- Counts are kept here, never re-read in a loop, and every write is read back: live, the
    -- game ignored setParams on a garrison's units and the old loop spun forever, hanging the
    -- game. A write that doesn't take stops the merge at once.
    local emptied, moved = {}, 0
    -- the properties, not setParams: live, setParams would not raise a unit's count (36 stayed
    -- 36), while setting soldierCountStratMap did (36 became 40)
    local function set(u, count, exp)
        u.soldierCountStratMap = count
        pcall(function() u.exp = exp end)
        return u.soldierCountStratMap == count
    end
    for _, units in pairs(groups) do
        local n_of, max_of, exp_of = {}, {}, {}
        for i, u in ipairs(units) do
            n_of[i], max_of[i], exp_of[i] = u.soldierCountStratMap, u.soldierCountStratMapMax, u.exp
        end
        local order = {}
        for i = 1, #units do order[i] = i end
        table.sort(order, function(a, b) return n_of[a] > n_of[b] end)
        local take = #order  -- the weakest still holding soldiers
        for give = 1, #order do  -- fill each unit, fullest first, from the weakest
            local t = order[give]
            for _ = 1, #order do  -- at most one pour per donor: no loop can spin
                if take <= give or n_of[t] >= max_of[t] then break end
                local d = order[take]
                local n = math.min(n_of[d], max_of[t] - n_of[t])
                local total = n_of[t] + n
                local exp = math.floor((exp_of[t] * n_of[t] + exp_of[d] * n) / total + 0.5)
                if not set(units[t], total, exp) then
                    return string.format("the game didn't take the merge in %s (%d soldiers moved before it stopped)", o.army, moved)
                end
                n_of[t], exp_of[t] = total, exp
                n_of[d] = n_of[d] - n
                if n_of[d] > 0 then
                    if not set(units[d], n_of[d], exp_of[d]) then
                        return string.format("the game didn't take the merge in %s", o.army)
                    end
                else
                    emptied[#emptied + 1] = units[d]
                    take = take - 1
                end
                moved = moved + n
            end
        end
    end
    for _, u in ipairs(emptied) do u:kill() end
    log(string.format("%s merge_units %s: %d soldiers moved, %d units disbanded", fac.name, o.army, moved, #emptied))
    return nil
end

-- Release units of one type from an army to save upkeep (Scratch, live: "Antwerp's surplus
-- militia is the first thing to cut if a disband order appears"): the weakest first, never a
-- unit with a character (a general's bodyguard). unit:kill() as merge_units uses it.
function handlers.disband(fac, o)
    local st = find_army(fac, o.army)
    if not st then return "unknown army '" .. tostring(o.army) .. "'" end
    local found = {}
    for i = 0, st.numOfUnits - 1 do
        local u = st:getUnit(i)
        local ok, match = pcall(function() return not u.character and u.eduEntry.eduType == o.unit end)
        if ok and match then found[#found + 1] = u end
    end
    if #found == 0 then return "'" .. tostring(o.army) .. "' has no '" .. tostring(o.unit) .. "' to release" end
    table.sort(found, function(a, b) return a.soldierCountStratMap < b.soldierCountStratMap end)
    local n = math.min(tonumber(o.count) or 1, #found)
    for k = 1, n do found[k]:kill() end
    log(string.format("%s disband %s: %d %s released", fac.name, o.army, n, o.unit))
    return nil
end

-- One of your armies (a garrison too) walks to join another. EOP's mergeArmies checks nothing
-- in C++, so both stacks are looked up now, at turn start: an army that died since the report is
-- refused, never passed on. force=false walks (uses moves) instead of merging instantly.
function handlers.merge_armies(fac, o)
    local st, into = find_army(fac, o.army), find_army(fac, o.into)
    if not st then return "unknown army '" .. tostring(o.army) .. "'" end
    if not into then return "unknown army '" .. tostring(o.into) .. "'" end
    if st == into then return "an army can't merge into itself" end
    local total = (st.numOfUnits or 0) + (into.numOfUnits or 0)
    if total > 20 then return "together they'd be " .. total .. " units; an army holds at most 20" end
    st:mergeArmies(into, false)
end

local function own_agent(fac, id)
    for _, a in ipairs(agents_of(fac)) do
        if same(a.id, id) then return a end
    end
end

function handlers.move_agent(fac, o)
    local a = own_agent(fac, o.agent)
    if not a then return "unknown agent '" .. tostring(o.agent) .. "' (not one of yours)" end
    if type(o.x) ~= "number" or type(o.y) ~= "number" then return "move_agent needs x and y" end
    local x, y, map = math.floor(o.x), math.floor(o.y), gd.stratMap
    if not (map.mapWidth and map.mapHeight and x >= 0 and y >= 0 and x < map.mapWidth and y < map.mapHeight) then
        return "(" .. x .. "," .. y .. ") is off the map"
    end
    a.char:moveToTile(x, y)
end

-- a princess offers marriage to a foreign general in sight (EOP's marry checks its arguments)
function handlers.marry(fac, o)
    local a = own_agent(fac, o.agent)
    if not a then return "unknown agent '" .. tostring(o.agent) .. "' (not one of yours)" end
    if a.kind ~= "princess" then return "'" .. a.id .. "' is a " .. a.kind .. "; only a princess can marry" end
    for _, e in ipairs(M.sight(fac).armies) do
        if same(e.view.id, o.target) then
            a.char:marry(e.char)
            return nil
        end
    end
    return "target '" .. tostring(o.target) .. "' is not in sight"
end

local busy = {}  -- agents given an order this turn (reset per orders file); one action each

-- Agent orders: your own agent of the right kind, against a target in sight right now.
-- EOP's agent actions return nothing, so "done" means issued; the next report shows the outcome.
local function agent_order(fac, o)
    local need = AGENT_KIND[o.type]
    local agent
    for _, a in ipairs(agents_of(fac)) do
        if same(a.id, o.agent) then agent = a end
    end
    if not agent then return nil, "unknown agent '" .. tostring(o.agent) .. "' (not one of yours)" end
    if agent.kind ~= need then
        local an = need:match("^[aeiou]") and "an " or "a "
        return nil, "'" .. agent.id .. "' is a " .. agent.kind .. ", not " .. an .. need
    end
    if busy[agent.id] then return nil, "'" .. agent.id .. "' already has an order this turn" end
    local okl, alive = pcall(function() return agent.char.namedCharacter:isAlive() end)
    if okl and (alive == false or alive == 0) then return nil, "'" .. agent.id .. "' is dead" end
    local seen = M.sight(fac)
    local name = o.type == "sabotage" and o.settlement or o.target
    for _, e in ipairs(seen.settlements) do
        if same(e.view.id, name) then return agent.char, nil, e.sett end
    end
    if o.type ~= "sabotage" then
        for _, list in ipairs({ seen.armies, seen.agents }) do
            for _, e in ipairs(list) do
                if same(e.view.id, name) then return agent.char, e.char end
            end
        end
    end
    return nil, "target '" .. tostring(name) .. "' is not in sight"
end

local function agent_handler(on_char, on_sett)
    return function(fac, o)
        local agent, char, sett = agent_order(fac, o)
        if not agent then return char end  -- char holds the reason
        busy[o.agent] = true
        if sett then
            if not on_sett then return "target '" .. o.target .. "' is a settlement" end
            agent[on_sett](agent, sett)
        else
            if not on_char then return "target is not a settlement" end
            agent[on_char](agent, char)
        end
    end
end

handlers.assassinate = agent_handler("assassinate", nil)
handlers.sabotage = agent_handler(nil, "sabotageSettlement")
handlers.spy = agent_handler("spyCharacter", "spySettlement")
handlers.bribe = agent_handler("bribe", "bribeSettlement")

local function apply(fac, o, cfg)
    local campaign, map = gd.campaignStruct, gd.stratMap
    local handler = handlers[o.type]
    if not handler then return "unknown order type '" .. tostring(o.type) .. "'" end
    local areas = areas_of(cfg, fac.name)
    local area = ORDER_AREA[o.type]
    if not areas[area] then return "'" .. o.type .. "' is " .. tostring(area) .. ", not yours to command" end
    local target
    if o.to ~= nil then
        target = campaign:getFaction(o.to)
        if not target or o.to == fac.name then return "unknown faction '" .. tostring(o.to) .. "'" end
    end
    return handler(fac, o, target, map, campaign)
end

-- --- event entry points --------------------------------------------------------------

-- Who changes stances: at each faction's turn end, its stances that changed since its last
-- turn end are logged, so a war nobody ordered can be pinned on the turn it happened in
-- (seen live: Denmark and the HRE "at war" with England while every ruler ordered peace).
local stances_seen = {}
local stance_news = {}  -- faction -> what changed in its stances, and who did it, since its report

function M.take_stance_news(faction)
    local list = stance_news[faction] or {}
    stance_news[faction] = nil
    return list
end

local function log_stance_changes(fac)
    local campaign = gd.campaignStruct
    for i = 0, stratmap.game.getFactionsCount() - 1 do
        local other = stratmap.game.getFaction(i)
        if other and other.name ~= fac.name and other.name ~= "slave" then
            local key = fac.name < other.name and (fac.name .. "|" .. other.name) or (other.name .. "|" .. fac.name)
            local now = stance(campaign, fac, other)
            local was = stances_seen[key]
            if was and was ~= now then
                log(string.format("stance: %s %s -> %s (seen at the end of %s's turn %d)",
                                  key, was, now, fac.name, campaign.turnNumber))
                -- both sides hear who did it: a stance changes for both at once, by either's order
                -- or the game's own AI (the author: rulers must know everything that goes on, then decide)
                local by = fac.localizedName or fac.name
                -- an order applied since this pair was last seen, for this stance, is a ruler's;
                -- otherwise the game's own AI made the change
                local o = stance_orders[key]
                local ordered = o and o.turn >= campaign.turnNumber - 1 and o.stance == now and o.by
                -- a faction with an LLM ruler: war and peace are the ruler's alone (the author: "if the
                -- llm is set to declare war or peace then the ai shouldn't be able to"). A change
                -- its own game AI made on its turn, with no ruler's order, is put back at once.
                local cfg = config()
                local reverted = false
                -- (never on the human slot's turn: it has no game AI, only its ruler's orders;
                -- live, its ruler's own peace was undone when a reload lost the order's record)
                if not ordered and cfg and cfg.factions[fac.name] and fac.isPlayerControlled ~= 1
                    and dipRelType[was] then
                    campaign:setDipStance(dipRelType[was], fac, other)
                    reverted = stance(campaign, fac, other) == was
                    log(string.format("stance: %s %s -> %s by %s's game AI %s", key, was, now, fac.name,
                                      reverted and ("reverted to " .. was) or "could not be reverted"))
                end
                for _, side in ipairs({ { fac, other }, { other, fac } }) do
                    local me, them = side[1], side[2]
                    local list = stance_news[me.name] or {}
                    local who
                    if ordered then
                        who = ordered == me.name and "by your own order"
                            or ("by " .. (them.localizedName or them.name) .. "'s order")
                    else
                        who = "by the game's own AI acting for " .. (me == fac and "you" or by)
                            .. ", not by any ruler's order"
                    end
                    local line = string.format("%s (%s) and you went from %s to %s on %s's turn %d, %s",
                        them.localizedName or them.name, them.name, was, now, by, campaign.turnNumber, who)
                    if not ordered then  -- the actor first: misread live as the other side's breach
                        local actor = me == fac and "YOUR OWN game AI" or (by .. "'s own game AI")
                        line = string.format("%s, not %s and not any ruler, changed %s and you from %s to %s "
                            .. "on turn %d", actor, me == fac and (them.localizedName or them.name) or "you",
                            them.localizedName or them.name, was, now, campaign.turnNumber)
                    end
                    if reverted then
                        line = line .. string.format("; it was put back to %s at once, since %s's ruler alone "
                            .. "makes war and peace for %s", was, by, by)
                    end
                    list[#list + 1] = line
                    while #list > 20 do table.remove(list, 1) end
                    stance_news[me.name] = list
                end
            end
            stances_seen[key] = stance(campaign, fac, other)
        end
    end
end

-- every pair's stance as it stands now: a reload starts from this, not from nothing (live: the
-- first turn after each reload saw no stance change at all, and an AI war slipped through)
function M.snapshot_stances()
    -- the stances as of the last turn end, saved there: a reload mid-turn would otherwise take
    -- an AI's war as the starting point (live: a reload during the HRE's turn, right after its
    -- AI declared war, and the war was never undone)
    local saved = read_file(root .. "/stances.json")
    local ok, t = pcall(json.decode, saved or "")
    if ok and type(t) == "table" and next(t) then
        for k, v in pairs(t) do stances_seen[k] = v end
        return
    end
    local campaign, n = gd.campaignStruct, stratmap.game.getFactionsCount()
    for i = 0, n - 1 do
        local a = stratmap.game.getFaction(i)
        for j = i + 1, n - 1 do
            local b = stratmap.game.getFaction(j)
            if a and b and a.name ~= "slave" and b.name ~= "slave" then
                local key = a.name < b.name and (a.name .. "|" .. b.name) or (b.name .. "|" .. a.name)
                stances_seen[key] = stance(campaign, a, b)
            end
        end
    end
end

function M.on_turn_end(fac)
    pcall(log_stance_changes, fac)
    pcall(function() atomic_write(root .. "/stances.json", encode(stances_seen)) end)
    local cfg = config()
    if not cfg or not cfg.factions[fac.name] then return end
    local ok, err = pcall(function()
        local dir = turn_dir(cfg, gd.campaignStruct.turnNumber, fac.name)
        local done, werr = atomic_write(dir .. "/state.json", encode(M.report(fac, cfg)))
        if not done then log(fac.name .. ": cannot write report in " .. dir .. ": " .. tostring(werr)) end
    end)
    if not ok then log(fac.name .. ": report failed: " .. tostring(err)) end
end

-- Apply fac's orders from turn-1. With final false and no orders yet, leave them for a
-- later try (autoplay: the human's own ruler may answer during its turn). Returns true
-- once the turn's orders are settled (applied, or marked late).
local function apply_orders(fac, cfg, turn, final)
    local dir = turn_dir(cfg, turn - 1, fac.name)
    if applied[dir] then return true end
    local text = read_file(dir .. "/orders.json")
    if not text and not final then return false end
    applied[dir] = true
    if not text then
        -- too late now: mark it, so orders that arrive later are reported back as late
        atomic_write(dir .. "/late.txt", "")
        log(fac.name .. ": no orders for turn " .. (turn - 1) .. " in time; skipped")
        return true
    end
    local okd, orders = pcall(json.decode, text)
    if not okd or type(orders) ~= "table" or type(orders.orders) ~= "table" then
        log(fac.name .. ": orders unreadable in " .. dir .. ": " .. tostring(orders))
        return true
    end
    if fac.isPlayerControlled == 1 and type(orders.note) == "string" and orders.note ~= "" then
        M.plan = fac.name .. ": " .. orders.note:sub(1, 300)  -- the on-screen window shows it
    end
    local results = {}
    busy = {}
    for i, o in ipairs(orders.orders) do
        local ok, reason = pcall(apply, fac, o, cfg)
        if not ok then reason = "error: " .. tostring(reason) end
        results[#results + 1] = { index = i - 1, type = tostring(o.type), ok = reason == nil,
                                  reason = reason or "" }
        log(string.format("%s order %d %s: %s", fac.name, i - 1, tostring(o.type), reason or "done"))
    end
    atomic_write(dir .. "/results.json", encode(results))
    return true
end

function M.on_turn_start(fac)
    local cfg = config()
    if not cfg or not cfg.factions[fac.name] then return end
    local turn = gd.campaignStruct.turnNumber
    -- the orchestrator makes turn folders from this (Lua can't create directories)
    atomic_write(root .. "/heartbeat.txt", "turn=" .. turn .. "\n")
    deliver_training(fac, turn)
    -- under autoplay the human's turn waits for its ruler, if it played last turn
    local waits = cfg.autoplay and fac.isPlayerControlled == 1
        and exists(turn_dir(cfg, turn - 1, fac.name) .. "/state.json")
    if cfg.autoplay and fac.isPlayerControlled == 1 then
        M.autoplay_turn_started(turn)
        M.set_governors(fac, areas_of(cfg, fac.name))
        M.follow(fac)
    end
    apply_orders(fac, cfg, turn, not waits)
end

-- The human's slot has no AI: whatever its ruler doesn't run, the settlement governors do.
-- (EOP exposes construction and recruitment auto-manage, not taxes.)
function M.set_governors(fac, areas)
    for i = 0, fac.settlementsNum - 1 do
        pcall(function()
            local pc = fac:getSettlement(i).aiProductionController
            if not pc then return end
            pc.isAutoManagedConstruction = areas.build and 0 or 1
            pc.isAutoManagedRecruitment = areas.recruit and 0 or 1
            -- the master switch too (unverified whether the sub-flags alone turn a governor on)
            pc.isAutoManaged = (areas.build and areas.recruit) and 0 or 1
        end)
    end
    -- read the flags back: whether governors really build and recruit is still being checked live
    local seen = {}
    for i = 0, fac.settlementsNum - 1 do
        pcall(function()
            local s = fac:getSettlement(i)
            local pc = s.aiProductionController
            if pc then
                seen[#seen + 1] = string.format("%s build=%s recruit=%s", s.name,
                    tostring(pc.isAutoManagedConstruction), tostring(pc.isAutoManagedRecruitment))
            end
        end)
    end
    log("governors " .. fac.name .. ": " .. table.concat(seen, "; "))
end

-- point the camera at the ruler's first general, else its first settlement
function M.follow(fac)
    pcall(function()
        for i = 0, fac.stacksNum - 1 do
            local st = fac:getStack(i)
            if st.leader and not st:findInSettlement() then
                return stratmap.camera.jump(st.leader.xCoord, st.leader.yCoord)
            end
        end
        if fac.settlementsNum > 0 then
            local s = fac:getSettlement(0)
            stratmap.camera.jump(s.xCoord, s.yCoord)
        end
    end)
end

-- EOP's onPreBattlePanelOpen: under autoplay nobody is there to choose, so auto-resolve
function M.on_pre_battle()
    local cfg = config()
    if not cfg or not cfg.autoplay then return end
    log("autoplay: battle panel open; auto-resolving")
    stratmap.game.scriptCommand("select_ui_element", "prebattle_auto_resolve_button")
    stratmap.game.scriptCommand("simulate_mouse_click", "lclick_up")
end

-- --- autoplay: end the human's turn once every ruler has answered ----------------------
-- Called every frame (EOP's draw hook) through M.on_frame, which throttles it. Ends the
-- turn by clicking the game's own End Turn button through its script commands.

M.clock = os.time
M.status = nil  -- one line for the on-screen overlay
local auto = {}
local STUCK_AFTER = 20  -- seconds after End Turn with the human's turn still showing (the author: stuck takes too long)

-- the wait for late rulers counts from the human's turn start
function M.autoplay_turn_started(turn) auto = { turn = turn, since = M.clock() } end

local function pending_rulers(cfg, turn, fac)
    local pending = {}
    for name in pairs(cfg.factions) do
        local dir = turn_dir(cfg, turn - 1, name)
        if name == fac.name then
            if not applied[dir] then pending[#pending + 1] = name end
        elseif exists(dir .. "/state.json") and not exists(dir .. "/orders.json") then
            pending[#pending + 1] = name
        end
    end
    table.sort(pending)
    return pending
end

local function click(element)
    stratmap.game.scriptCommand("select_ui_element", element)
    stratmap.game.scriptCommand("simulate_mouse_click", "lclick_up")
end

local function click_end_turn() click("end_turn") end

-- One step of the first screen job, at most every UI_STEP seconds (each step opens a scroll the
-- next needs drawn). Retraining, as a player does it (live, London): select the settlement, its
-- recruitment scroll, the Retrain tab; then the turn loop clicks each card (EOP's execute() on a
-- card does nothing) and closes the scroll. Card positions are in the UI's 1024x768 space.
local UI_STEP, UI_GIVE_UP = 1.5, 120

local function run_ui_job(now)
    local j = ui_jobs[1]
    j.started = j.started or now
    if now - j.started > UI_GIVE_UP then  -- the turn loop never answered: End Turn mustn't wait forever
        log("screen job " .. j.kind .. " " .. j.settlement .. ": gave up after " .. UI_GIVE_UP .. "s")
        table.remove(ui_jobs, 1)
        return
    end
    if j.at and now - j.at < UI_STEP then return end
    j.at = now
    if j.step == 1 then
        stratmap.game.scriptCommand("select_settlement", j.settlement)
    elseif j.step == 2 then
        click("recruitment_button")
    elseif j.step == 3 then
        click("settlement_info_retrain_tab")
    elseif j.step == 4 then
        local cards = {}
        local e = gameSTDUI and gameSTDUI.getUiElement("available_training_options")
        for i = 0, (e and e.subElementsNum or 0) - 1 do  -- getSubElement is unchecked: stay in range
            local c = e:getSubElement(i)
            cards[#cards + 1] = { (c.xPos + c.xSize / 2) / 1024, (c.yPos + c.ySize / 2) / 768 }
        end
        local id = "popup-" .. gd.campaignStruct.turnNumber .. "-r" .. os.time()
        j.request = root .. "/" .. id
        atomic_write(j.request .. ".req", encode({ id = id, kind = "clicks", what = "retrain " .. j.settlement,
                                                  cards = cards, faction = j.faction,
                                                  turn = gd.campaignStruct.turnNumber }))
        log("retrain " .. j.settlement .. ": " .. #cards .. " units can be retrained; the turn loop clicks them")
    else  -- step 5: wait for the turn loop's clicks
        if not exists(j.request .. ".done") then return end
        os.remove(j.request .. ".req")
        os.remove(j.request .. ".done")
        log("retrain " .. j.settlement .. ": done")
        table.remove(ui_jobs, 1)
        return
    end
    j.step = j.step + 1
end

-- an open UI element's buttons (sub-elements), and their names as one line
local function buttons_of(el)
    local list = {}
    for i = 0, (el.subElementsNum or 0) - 1 do  -- stay inside subElementsNum: getSubElement is unchecked
        local b = el:getSubElement(i)
        if b and b.elementName then list[#list + 1] = b end
    end
    return list
end

local function names(buttons)
    local out = {}
    for _, b in ipairs(buttons) do out[#out + 1] = b.elementName end
    return table.concat(out, ", ")
end

-- every part of an element, unnamed ones by index, with position and size: an unnamed button
-- (the diplomacy screen's close seal) can only be told apart by where it sits
local function describe(el)
    local out = {}
    for i = 0, (el.subElementsNum or 0) - 1 do
        local b = el:getSubElement(i)
        if b then
            local name = b.elementName
            local label = (name and name ~= "" and name ~= "null") and name or ("#" .. i)
            if b.xPos then label = string.format("%s @%d,%d %dx%d", label, b.xPos, b.yPos, b.xSize, b.ySize) end
            out[#out + 1] = label
        end
    end
    return table.concat(out, ", ")
end

-- Popups that wait for a human, tried one per stuck check: a battle against the human's slot,
-- a result scroll, an AI's diplomatic offer to the human. Names from medieval2.exe's strings.
local DISMISS = { "prebattle_auto_resolve_button", "close_tick_button", "diplomacy_decline_offer_button",
                  "siege_maintain_button", "release_prisoners_button", "close_cross_button",
                  "close_seal_button" }
local AI_STUCK_AFTER = 30  -- seconds one AI faction's turn may sit unchanged (they take seconds)
local MAX_TRIES = 15  -- then stop clicking and ask for a human on screen (one try every 20-30 s)
local watch = {}
local pressed = {}  -- buttons already pressed while they linger on screen (never pressed twice)

-- the known popup buttons that are open now, if EOP can tell (gameSTDUI.getUiElement looks
-- them up by name); if it can't, or finds none, all of them in turn (pressing a button that
-- isn't on screen does nothing)
local function open_popups()
    if not (gameSTDUI and gameSTDUI.getUiElement) then return DISMISS end
    local open = {}
    for _, name in ipairs(DISMISS) do
        local ok, e = pcall(gameSTDUI.getUiElement, name)
        if ok and e and not pressed[name] then open[#open + 1] = name end
    end
    return #open > 0 and open or DISMISS
end

-- Which UI elements are open right now, by trying every UI-like name in the game's exe
-- (ui_names.txt, written by install_bridge.sh) against the game's own lookup. EOP can't list
-- open elements, so this is how an unknown dialog's real name and buttons get found: written to
-- ui_scan-<who>.txt for a human (or Claude) to read. Nothing found this way is pressed.
function M.scan_ui(who)
    local text = read_file(root .. "/ui_names.txt")
    if not text or not (gameSTDUI and gameSTDUI.getUiElement) then return end
    local lines = {}
    for name in text:gmatch("[^\r\n]+") do
        local ok, el = pcall(gameSTDUI.getUiElement, name)
        if ok and el then
            local okd, parts = pcall(describe, el)
            lines[#lines + 1] = name .. ": " .. (okd and parts or "?")
        end
    end
    local file = root .. "/ui_scan-" .. who:gsub("[^%w]+", "-") .. ".txt"
    atomic_write(file, table.concat(lines, "\n") .. "\n")
    log("autoplay: " .. #lines .. " UI elements open; list in " .. file)
end

-- one recovery attempt for a stuck `who`; false once it has given up
-- popups that ask for a decision: the button pressed for nobody-at-the-keyboard
local DECISION = {
    prebattle_scroll = "prebattle_auto_resolve_button",
    diplomacy_scroll = "diplomacy_decline_offer_button",  -- an AI's offer to the human slot
    siege_scroll = "siege_maintain_button",
    loot_settlement_scroll = "loot_settlement_occupy_button",
    captor_ransom_scroll = "ransom_prisoners_button",
    captive_ransom_scroll = "accept_ransom_button",
}
-- popups the game raises on its own (not ones a watcher opens to look at things)
local GAME_POPUPS = {
    post_battle_scroll = "a battle's result", post_battle_stats_scroll = "battle statistics",
    ransom_result_scroll = "a ransom's outcome", request_assistance_scroll = "an ally asks for help",
    ally_attack_warning_scroll = "a warning about attacking an ally",
    neutral_attack_warning_scroll = "a warning about attacking a neutral faction",
    excommunication_attack_warning_scroll = "a warning that an attack risks excommunication",
    join_crusade_against_ally_scroll = "a crusade against an ally",
    join_crusade_against_neutral_scroll = "a crusade against a neutral faction",
    join_jihad_against_ally_scroll = "a jihad against an ally",
    join_jihad_against_neutral_scroll = "a jihad against a neutral faction",
    papal_election_scroll = "a papal election", papal_election_results_scroll = "a papal election's result",
    conditions_complete_scroll = "victory conditions complete", convert_settlement_warning_scroll = "a settlement conversion warning",
    break_siege_confirmation_scroll = "a siege about to break", battle_delay_scroll = "a delayed battle",
    end_deployment_scroll = "a battle deployment", mission_target_scroll = "a mission's target",
    hotseat_message_scroll = "a message", exchange_scroll = "an exchange",
    prebattle_scroll = "a battle", diplomacy_scroll = "a diplomatic offer", siege_scroll = "a siege",
    loot_settlement_scroll = "a captured settlement", captor_ransom_scroll = "prisoners taken",
    captive_ransom_scroll = "your men captured",
}
-- where an event message (a mission, a disaster, news) may show; unconfirmed, so the log says
-- which one was open
local MESSAGE_SCROLLS = { "event_scroll", "message_scroll", "faction_events_scroll", "hotseat_message_scroll" }
for name in pairs(GAME_POPUPS) do  -- a message may raise any game popup: look at all of them
    MESSAGE_SCROLLS[#MESSAGE_SCROLLS + 1] = name
end
table.sort(MESSAGE_SCROLLS)
-- (the siege panel too: screenshotted before "maintain" is pressed, so its equipment icons can
-- be measured from the image; reading the game's UI deeper crashed the game live)
local READ_SCROLLS = { post_battle_scroll = true, ransom_result_scroll = true, siege_scroll = true }
-- decision scrolls the ruler chooses on (see CHOICES): no default pressed when they open
local CHOICE_SCROLLS = { loot_settlement_scroll = true, captor_ransom_scroll = true,
                         captive_ransom_scroll = true, diplomacy_scroll = true }

-- Scrolls whose close tick has no name: the path of sub-element indexes to it (0-based), from a
-- live probe. post_battle_scroll: part 3 is the button row, its part 0 the tick (part 1 is
-- post_battle_show_stats_button); seen live holding up the HRE's turn after a bridge reload.
local TICK_PARTS = { post_battle_scroll = { 3, 0 }, ransom_result_scroll = { 0 } }

-- press the unnamed tick of an open scroll in TICK_PARTS; the scroll's name if pressed
local function unnamed(b)
    local n = b.elementName
    return n == nil or n == "" or n == "null"
end

-- Any result scroll's close button, found by its shape (the author: "we can't rely on you to close
-- them"): an unnamed, roughly square, button-sized part in the scroll's lower half; the lowest,
-- then the leftmost (the tick sits left of the stats button on a battle result). Named parts
-- (zoom, stats, decisions) are never pressed this way.
local function close_button(el)
    local best
    local bottom = (el.yPos or 0) + (el.ySize or 0) / 2
    local function visit(e, depth)
        for i = 0, (e.subElementsNum or 0) - 1 do
            local b = e:getSubElement(i)
            if b then
                local w, h = b.xSize or 0, b.ySize or 0
                if unnamed(b) and w >= 24 and w <= 70 and h >= 24 and h <= 70 and math.abs(w - h) <= 20
                    and (b.yPos or 0) >= bottom then
                    if not best or b.yPos > best.yPos or (b.yPos == best.yPos and b.xPos < best.xPos) then best = b end
                end
                if depth < 3 then visit(b, depth + 1) end
            end
        end
    end
    visit(el, 1)
    return best
end

-- The siege panel's and the papal election's whole layout, four levels deep, once each: the
-- equipment choice (rams, ladders, towers) has no API in EOP, so its buttons must be found
-- (the author: "is he buying siege equipment when he sieges?" He wasn't). Called when the scroll is
-- actually found: live, it was "not found" at the moment it opened and found seconds later.
local LAYOUT_FILES = { siege_scroll = "ui_scan-siege.txt", papal_election_scroll = "ui_scan-papal.txt" }
local recorded = {}

function M.record_layout(scroll, el)
    local file = LAYOUT_FILES[scroll]
    if not file or recorded[scroll] then return end
    recorded[scroll] = true
    -- one level only, as the UI scans do safely: a walk four levels down crashed the game live
    -- (the siege panel has a part named "null", likely a bad pointer; pcall can't catch that)
    pcall(function()
        atomic_write(root .. "/" .. file, scroll .. ": " .. describe(el) .. "\n")
        log("popup " .. scroll .. ": layout written to " .. file)
    end)
end

-- press the unnamed close of an open result scroll (all of them, or just `only`): the path a
-- live probe found (TICK_PARTS), else one found by shape. Never a decision scroll's.
local function press_tick_part(only)
    for scroll in pairs(GAME_POPUPS) do
        if (not only or only == scroll) and not DECISION[scroll] and not CHOICE_SCROLLS[scroll]
            and scroll ~= "papal_election_scroll" then  -- a vote: never pressed by shape
            local ok, done = pcall(function()
                local el = gameSTDUI.getUiElement(scroll)
                if not el then return false end
                local b
                if TICK_PARTS[scroll] then
                    b = el
                    for _, i in ipairs(TICK_PARTS[scroll]) do b = b:getSubElement(i) end
                else
                    b = close_button(el)
                end
                if not b then
                    log("popup " .. scroll .. ": no close button found among " .. describe(el))
                    return false
                end
                b:execute()
                return true
            end)
            if ok and done then return scroll end
        end
    end
end

local function try_dismiss(state, who)
    if M.deciding and M.deciding() then  -- the ruler is deciding a popup: it's not stuck
        M.status = "Parley: " .. who .. ", the ruler is deciding a popup"
        return false  -- nothing dismissed: no End Turn into the open scroll
    end
    if not state.scanned then
        state.scanned = true
        pcall(M.scan_ui, who)
    end
    state.tries = (state.tries or 0) + 1
    if state.tries > MAX_TRIES then
        if not state.gave_up then log("autoplay: " .. who .. " still stuck after " .. MAX_TRIES ..
                                      " tries; needs a human click") end
        state.gave_up = true
        M.status = "Parley: stuck on " .. who .. ", needs a human click"
        -- never give up for good (live: a marriage offer held the game all night): keep asking
        -- the turn loop to look, every second check (about 40 s; the author: two minutes was too slow)
        if (state.tries - MAX_TRIES) % 2 ~= 0 then return false end
    end
    -- a minimized decision blocks End Turn unseen (its icon names no UI element): ask the turn
    -- loop to reopen one from the stack on the left, the next slot each time. It also decides a
    -- decision it finds open on screen, so the request names the human slot's faction.
    pcall(function()
        local id = "popup-" .. gd.campaignStruct.turnNumber .. "-m" .. os.time()
        local cfg, faction = config(), nil
        for name in pairs(cfg and cfg.factions or {}) do
            local f = gd.campaignStruct:getFaction(name)
            if f and f.isPlayerControlled == 1 then faction = name end
        end
        atomic_write(root .. "/" .. id .. ".req", encode({ id = id, kind = "minimized", faction = faction,
                                                          turn = gd.campaignStruct.turnNumber }))
    end)
    local ticked = gameSTDUI and press_tick_part()
    if ticked then
        log("autoplay: " .. who .. " stuck? try " .. state.tries .. ": " .. ticked .. "'s tick")
        return true
    end
    -- only buttons actually on screen: pressing absent ones blind cost a minute a try (the author:
    -- "stuff getting stuck takes too long"); the minimized-message reopening asked for above
    -- covers what no named button can
    local open = {}
    if gameSTDUI and gameSTDUI.getUiElement then
        for _, n in ipairs(DISMISS) do
            local ok, e = pcall(gameSTDUI.getUiElement, n)
            if ok and e and not pressed[n] then open[#open + 1] = n end
        end
    end
    local name = open[(state.tries - 1) % math.max(#open, 1) + 1]
    log("autoplay: " .. who .. " stuck? try " .. state.tries .. ": "
        .. (name or "no known popup open; reopening a minimized message"))
    M.status = "Parley: " .. who .. " stuck? " .. (name and ("pressing " .. name) or "reopening a minimized message")
    if name then click(name) end
    return true
end

-- an AI faction's turn that doesn't move is almost always a popup waiting for the human
local function watch_ai_turn(campaign, fac, now)
    local key = campaign.turnNumber .. ":" .. tostring(fac.name)
    if watch.key ~= key then watch = { key = key, since = now } return end
    if now - watch.since >= AI_STUCK_AFTER then
        try_dismiss(watch, tostring(fac.name) .. "'s turn")
        watch.since = now
    end
end

-- --- popups: under autoplay every game popup is acknowledged, logged, and told to the ruler --
-- Scroll names are the game's own (medieval2.exe strings). EOP can't read a scroll's text,
-- only its name and its buttons' names, so the ruler hears what kind of popup it was.

local POPUP_DELAY = 3  -- seconds a popup stays up, so a watcher can read it
-- an acknowledging button, best first
local ACK = { "close_tick", "tick", "_ok", "ok_", "accept", "continue", "close" }

local pending, popups = {}, {}  -- popups waiting to be pressed; what the human slot hasn't heard yet

local function choose(scroll, buttons)
    local want = DECISION[scroll]
    if scroll == "siege_scroll" and M.assault_ordered then
        want, M.assault_ordered = "siege_assault_button", nil  -- one assault per order
    end
    for _, b in ipairs(buttons) do
        if want and b.elementName == want then return b end
    end
    for _, word in ipairs(ACK) do
        for _, b in ipairs(buttons) do
            if b.elementName:find(word, 1, true) then return b end
        end
    end
end

local function note_popup(text)
    popups[#popups + 1] = text
    while #popups > 20 do table.remove(popups, 1) end
end

-- EOP onScrollOpened: eventData may be the scroll's name or carry it as resourceDescription
function M.on_scroll_opened(e)
    local cfg = config()
    if not cfg or not cfg.autoplay then return end
    local scroll = type(e) == "string" and e or (e and e.resourceDescription)
    if not scroll or not GAME_POPUPS[scroll] then return end  -- a scroll a watcher opened: leave it
    local ok, el = pcall(gameSTDUI.getUiElement, scroll)
    log("popup " .. scroll .. ": " .. ((ok and el) and names(buttons_of(el)) or "(not found)"))
    if ok and el then M.record_layout(scroll, el) end
    if CHOICE_SCROLLS[scroll] then return end  -- the ruler chooses (watch_buttons), no default here
    local p = { scroll = scroll, at = M.clock() }
    -- results worth reading before they close: the turn loop screenshots them for the ruler
    -- (asked live: "Did Rufus survive, and how many men did we lose?")
    if READ_SCROLLS[scroll] then p.message, p.kind = "scroll:" .. scroll, "read" end
    -- the papal election: the ruler's cardinals vote; the turn loop finds the Vote buttons
    -- (seen live: the scroll sat unanswered and held the turn)
    if scroll == "papal_election_scroll" then p.message, p.kind = "scroll:" .. scroll, "vote" end
    pending[#pending + 1] = p
end

-- A message popup's text can't be read from Lua, so the turn loop screenshots it and has it
-- read (parley/popups.py): the bridge writes popup-<id>.req and holds the popup until
-- popup-<id>.done appears. A marriage or adoption offer is a decision: the ruler decides and the
-- turn loop clicks accept or decline, so it is never cleared out from under the ruler.
local READ_WAIT, DECIDE_WAIT = 30, 180  -- seconds before giving up on the turn loop
local DECISIONS = { marriage = "a marriage offer", adoption = "an adoption offer",
                    vote = "a papal election vote" }
-- seeded from the clock so ids stay unique across bridge reloads (seen live: popup-23-1 twice)
local next_request = (os.time() % 100000) * 100

local function traits_of(c)
    local names, t = {}, c:getTraits()
    while t and #names < 30 do
        names[#names + 1] = t.name
        t = t.nextTrait
    end
    return names
end

-- EOP onOfferedForMarriage / onOfferedForAdoption: the man offered to the human slot (a suitor
-- for one of its princesses, or a candidate for adoption), kept in `suitor` either way
local function human_faction(cfg)
    for name in pairs(cfg.factions) do
        local f = gd.campaignStruct:getFaction(name)
        if f and f.isPlayerControlled == 1 then return name end
    end
end

local function offered(kind, e)
    local ok, o = pcall(function()
        local c = e.character
        local suitor = { name = c.fullName, age = c.age, command = c.command, loyalty = c.loyalty,
                         piety = c.piety, chivalry_or_dread = c.chivalryAndDread, authority = c.authority }
        pcall(function() suitor.traits = traits_of(c) end)
        return { kind = kind, faction = e.faction and e.faction.name, suitor = suitor }
    end)
    if not ok then return end
    -- the events fire for AI factions too (seen live: the Moors' adoption, answered on England's
    -- screen); only the human slot's offers come up as popups
    local cfg = config()
    if not cfg or not cfg.autoplay or o.faction ~= human_faction(cfg) then return end
    -- a request of its own: no message event may follow (seen live: a captain offered for
    -- adoption after his victory, with no message at all)
    pending[#pending + 1] = { message = "offer", kind = kind, offer = o, at = M.clock() }
    log(kind .. " offer: " .. tostring(o.suitor.name) .. " for " .. tostring(o.faction))
end

function M.on_offered_for_marriage(e) offered("marriage", e) end
function M.on_offered_for_adoption(e) offered("adoption", e) end

-- EOP onIncomingMessage / onMessageOpen: a game event message (missions, news, disasters)
function M.on_message(e)
    local cfg = config()
    if not cfg or not cfg.autoplay then return end
    local id = e and e.eventID
    for _, p in ipairs(pending) do
        if p.message == id then return end
    end
    log("popup message " .. tostring(id))
    -- (an offer's own scroll raised its request already: the turn loop's fresh look before
    -- deciding turns this one into a plain reading once the offer is answered)
    pending[#pending + 1] = { message = id, at = M.clock(), kind = "read" }
end

-- for a message popup: ask the turn loop to capture it (once); true when it's done or given up
local function captured(p, now)
    if not p.request then
        next_request = next_request + 1
        p.request = root .. "/popup-" .. gd.campaignStruct.turnNumber .. "-" .. next_request
        p.requested = now
        local cfg = config()
        local req = { id = p.request:match("popup%-[%d%-]+$"), turn = gd.campaignStruct.turnNumber, kind = p.kind,
                      event = p.message, faction = (p.offer and p.offer.faction) or (cfg and human_faction(cfg)),
                      suitor = p.offer and p.offer.suitor or nil }
        atomic_write(p.request .. ".req", encode(req))
        return false
    end
    -- the turn loop found a check and an X on screen: a decision for the ruler, whatever kind
    if not p.decision and exists(p.request .. ".hold") then p.decision = true end
    if exists(p.request .. ".done") then
        -- "acked": the turn loop pressed the scroll's own check; clearing would minimize the next
        if (read_file(p.request .. ".done") or ""):find("acked", 1, true) then p.acked = true end
        os.remove(p.request .. ".req")
        os.remove(p.request .. ".done")
        os.remove(p.request .. ".hold")
        return true, "captured"
    end
    if now - p.requested >= ((DECISIONS[p.kind] or p.decision) and DECIDE_WAIT or READ_WAIT) then
        os.remove(p.request .. ".req")
        os.remove(p.request .. ".hold")
        log("popup " .. p.request .. ": the turn loop didn't capture it in time")
        return true, "timeout"
    end
    return false
end

-- press each pending popup's button once it has been up for POPUP_DELAY seconds
local function handle_popups(now)
    local keep = {}
    for _, p in ipairs(pending) do
        local held, how = false, p.how
        if p.message and not p.how and now - p.at >= POPUP_DELAY then
            local done
            done, how = captured(p, now)
            held = not done
            if done then p.how = how end  -- settled; a deferred one isn't asked again
        end
        if now - p.at < POPUP_DELAY or held then
            keep[#keep + 1] = p
        elseif not (DECISIONS[p.kind] or p.decision) and p.message and M.deciding() then
            -- clear_messages would minimize the decision being weighed; a minimized decision
            -- blocks End Turn unseen (seen live: Barnaby's adoption, minimized mid-answer)
            keep[#keep + 1] = p
        elseif p.decision and how ~= "captured" then
            -- a decision nobody answered: left on screen for a human, never minimized
            log("popup: a decision left unanswered on screen")
            note_popup("a decision (left unanswered)")
        elseif DECISIONS[p.kind] or (p.decision and how == "captured") then
            -- (a generic decision the turn loop never answered falls through and is dismissed)
            -- the turn loop clicked the ruler's answer; if it timed out, a human answers it
            local what = DECISIONS[p.kind] or "a decision"
            log("popup: " .. what .. " " .. (how == "captured" and "answered by the ruler" or "left for a human"))
            note_popup(what .. " (" .. (how == "captured" and "you answered it" or "left unanswered") .. ")")
        else
            local scrolls = p.scroll and { p.scroll } or MESSAGE_SCROLLS
            local done = p.acked and "acknowledged with its check" or nil
            if done then scrolls = {} end
            for _, scroll in ipairs(scrolls) do
                local ok, el = pcall(gameSTDUI.getUiElement, scroll)
                if ok and el then
                    M.record_layout(scroll, el)
                    local b = choose(scroll, buttons_of(el))
                    if b then
                        b:execute()
                        done = scroll .. " -> " .. b.elementName
                        break
                    end
                    if press_tick_part(scroll) then
                        done = scroll .. " -> its tick"
                        break
                    end
                    log("popup " .. scroll .. ": no button to press among " .. names(buttons_of(el)))
                end
            end
            -- event messages (missions, riots, news, proposals) live in no element we can name;
            -- the campaign script command clear_messages closed one live (a riot in Rennes)
            if not done and p.message then
                stratmap.game.scriptCommand("clear_messages", "")
                done = "clear_messages"
            end
            local what = p.scroll and GAME_POPUPS[p.scroll] or ("game message " .. tostring(p.message))
            local text = p.scroll and (what .. " (" .. (done or p.scroll .. ", closed by itself") .. ")")
                or ("game message " .. tostring(p.message) .. (done and (" (" .. done .. ")") or ""))
            log("popup handled: " .. text)
            note_popup(text)
        end
    end
    pending = keep
end

-- Decision buttons that exist only while the game waits on the human. The game's own UI
-- lookup finds them by name while they're on screen (seen in a live UI scan, 2026-10-24),
-- which catches popups no event announces, like an AI's offer made during the AI's turn.
local WATCHED = {
    { "prebattle_auto_resolve_button", "a battle (auto-resolved)" },
    { "diplomacy_decline_offer_button", "an AI's diplomatic offer (declined; the game says not what)" },
    { "siege_maintain_button", "a siege (kept up)" },
    { "loot_settlement_occupy_button", "a captured settlement (occupied)" },
    { "ransom_prisoners_button", "prisoners taken (ransomed)" },
    { "accept_ransom_button", "your men captured (ransom accepted)" },
}
local on_screen = {}  -- watched button -> when it was first seen
local offer_answered = false  -- an AI's offer on the diplomacy screen has been answered

-- The ruler's choice on a named decision scroll, keyed by the watched button that shows it is
-- up: { option, button } in the game's own names (its typo included). The turn loop asks the
-- ruler and writes popup-<id>.answer; with no answer in time the first option is pressed.
local CHOICES = {
    loot_settlement_occupy_button = { what = "a captured settlement", options = {
        { "occupy", "loot_settlement_occupy_button" }, { "sack", "loot_settlement_sack_button" },
        { "exterminate", "loot_settlement_extermintate_button" } } },
    ransom_prisoners_button = { what = "prisoners taken in battle", options = {
        { "ransom", "ransom_prisoners_button" }, { "release", "release_prisoners_button" },
        { "execute", "execute_prisoners_button" } } },
    accept_ransom_button = { what = "your men captured, their ransom asked of you", options = {
        { "pay", "accept_ransom_button" }, { "refuse", "reject_ransom_button" } } },
    diplomacy_decline_offer_button = { what = "an AI's diplomatic offer", options = {
        { "decline", "diplomacy_decline_offer_button" }, { "accept", "diplomacy_accept_offer_button" } } },
}
local choosing = {}  -- watched button -> { request, since } while the ruler decides

-- the option to press for a choice scroll now, or nil while the ruler is still deciding
local function choice_for(name, now)
    local spec, c = CHOICES[name], choosing[name]
    if not c then
        next_request = next_request + 1
        local turn = gd.campaignStruct.turnNumber
        local id = "popup-" .. turn .. "-" .. next_request
        local cfg = config()
        local options = {}
        for _, o in ipairs(spec.options) do options[#options + 1] = o[1] end
        atomic_write(root .. "/" .. id .. ".req", encode({ id = id, turn = turn, kind = "choice",
            what = spec.what, options = options, faction = cfg and human_faction(cfg) }))
        choosing[name] = { request = root .. "/" .. id, since = now }
        log("popup " .. id .. ": " .. spec.what .. ", the ruler chooses: " .. table.concat(options, ", "))
        return nil
    end
    local answer = read_file(c.request .. ".answer")
    if not answer and now - c.since < DECIDE_WAIT then return nil end
    os.remove(c.request .. ".req")
    os.remove(c.request .. ".answer")
    choosing[name] = nil
    local pick = answer and answer:match("^%s*(%S+)")
    for _, o in ipairs(spec.options) do
        if o[1] == pick then return o, true end
    end
    log("popup " .. c.request:match("popup%-[%d%-]+$") .. ": no answer from the ruler; pressing " .. spec.options[1][1])
    return spec.options[1], false
end

-- a decision is with the ruler right now (stuck checks wait for it)
function M.deciding()
    if next(choosing) then return true end
    for _, p in ipairs(pending) do
        if p.request and (p.decision or DECISIONS[p.kind]) then return true end
    end
    return false
end

local function watch_buttons(now)
    if not (gameSTDUI and gameSTDUI.getUiElement) then return end
    for _, w in ipairs(WATCHED) do
        local name, what = w[1], w[2]
        if name == "siege_maintain_button" and M.assault_ordered then
            name, what = "siege_assault_button", "a siege (assaulted, as ordered)"
        end
        local ok, el = pcall(gameSTDUI.getUiElement, name)
        if ok and el then
            -- press once, then not again until the button is gone: the game keeps a screen's
            -- buttons after they're used (seen live: decline pressed every 6 s, the AI answering)
            on_screen[name] = on_screen[name] or now
            if not pressed[name] and now - on_screen[name] >= POPUP_DELAY then
                local press = name
                if CHOICES[name] then
                    local o, answered = choice_for(name, now)
                    press = o and o[2]
                    if o then
                        what = CHOICES[name].what .. " (" .. o[1] .. (answered and ", your choice)" or
                                                                          ", nobody chose in time)")
                    end
                end
                if press then
                    pressed[name] = true
                    if name == "siege_assault_button" then M.assault_ordered = nil end
                    if name:find("^diplomacy_") then offer_answered = true end
                    log("popup button on screen: pressing " .. press)
                    note_popup(what)
                    click(press)
                end
            end
        else
            on_screen[name], pressed[name] = nil, nil
            if choosing[name] then  -- the scroll went (closed by someone else): drop the question
                os.remove(choosing[name].request .. ".req")
                choosing[name] = nil
            end
        end
    end
end

-- After an offer is answered the game leaves the diplomacy screen open with no offer buttons;
-- its close seal has no name EOP exposes, so try the likely close buttons one at a time (and
-- scan once, so the log shows what that screen holds if none of them works).
local CLOSE_DIPLOMACY = { "diplomacy_ok_button", "close_seal_button", "close_tick_button", "close_cross_button" }
local OFFER_BUTTONS = { "diplomacy_accept_offer_button", "diplomacy_decline_offer_button",
                        "diplomacy_counter_offer_button" }
local leftover = {}

local function open(name)
    local ok, el = pcall(gameSTDUI.getUiElement, name)
    return ok and el ~= nil
end

local function close_leftover_diplomacy(now)
    if not (gameSTDUI and gameSTDUI.getUiElement) or not open("diplomacy_scroll") then
        leftover, offer_answered = {}, false
        return
    end
    if not offer_answered then
        for _, b in ipairs(OFFER_BUTTONS) do
            if open(b) then leftover = {} return end  -- an offer is still waiting: watch_buttons answers it
        end
    end
    leftover.since = leftover.since or now
    if now - leftover.since < POPUP_DELAY or now - (leftover.last or 0) < POPUP_DELAY then return end
    -- each try lasts until the screen closes; after one round of the close buttons stop
    -- (seen live: the AI answers each press and the screen keeps reopening)
    if (leftover.tries or 0) >= #CLOSE_DIPLOMACY then
        if not leftover.gave_up then log("popup: diplomacy screen still open after every close button; leaving it") end
        leftover.gave_up = true
        return
    end
    if not leftover.scanned then
        leftover.scanned = true
        pcall(M.scan_ui, "diplomacy-left-open")
    end
    -- the close seal has no name: it's the small part in the screen's bottom-right corner
    -- (live scan: 58x65 at 962,703 of 1024x768; the top-right part is the help button)
    if not leftover.sealed then
        leftover.sealed = true
        local ok, seal = pcall(function()
            local el = gameSTDUI.getUiElement("diplomacy_scroll")
            local right = (el.xPos or 0) + (el.xSize or 1024) * 0.85
            local bottom = (el.yPos or 0) + (el.ySize or 768) * 0.85
            for i = 0, (el.subElementsNum or 0) - 1 do
                local b = el:getSubElement(i)
                if b and b.xPos and b.xSize <= 100 and b.ySize <= 100 and b.xPos >= right and b.yPos >= bottom then
                    return b
                end
            end
        end)
        if ok and seal then
            leftover.last = now
            log(string.format("popup: diplomacy screen left open; pressing its seal (@%d,%d)", seal.xPos, seal.yPos))
            seal:execute()
            return
        end
    end
    leftover.tries = (leftover.tries or 0) + 1
    local name = CLOSE_DIPLOMACY[(leftover.tries - 1) % #CLOSE_DIPLOMACY + 1]
    leftover.last = now
    log("popup: diplomacy screen left open; trying " .. name)
    click(name)
end

-- The control file: one command per line, read and removed on the next tick.
--   reload        restart the bridge's Lua inside the running game (after just install-bridge)
--   scan <label>  write every open UI element (with parts and positions) to ui_scan-<label>.txt
--   script <cmd> [args]  run a campaign script command in the game (for probing the UI live)
-- (No "save": M2TWEOP.saveGame failed live with "cannot create m2tweop save file"; the game's
-- own per-turn autosave is the safety net before a reload.)
local function control()
    local text = read_file(root .. "/control.txt")
    if not text then return end
    os.remove(root .. "/control.txt")
    for line in text:gmatch("[^\r\n]+") do
        local cmd, arg = line:match("^%s*(%S+)%s*(%S*)")
        local rest = line:match("^%s*script%s+(.+)$")
        local code = line:match("^%s*lua%s+(.+)$")
        if code then  -- lua <one line>: run it in the game (like EOP's console), log what it returns
            local fn, cerr = (loadstring or load)(code)
            local ok, res = false, cerr
            if fn then ok, res = pcall(fn) end
            log("control: lua -> " .. tostring(res) .. (ok and "" or " (error)"))
        elseif cmd == "scan" then  -- scan <label>: what UI is open right now, to ui_scan-<label>.txt
            pcall(M.scan_ui, arg ~= "" and arg or "now")
        elseif cmd == "script" and rest then  -- script <command> [args]: a campaign script command
            local name, args = rest:match("^(%S+)%s*(.*)$")
            local ok, err = pcall(stratmap.game.scriptCommand, name, args)
            log("control: script " .. rest .. (ok and "" or (" failed: " .. tostring(err))))
        elseif cmd == "reload" then
            -- after the restart, setup() reads this so this turn's orders aren't applied twice
            atomic_write(root .. "/reloaded.txt", "turn=" .. gd.campaignStruct.turnNumber .. "\n")
            log("control: reloading the bridge")
            -- EOP carries out a requested restart only while its console is drawn
            -- (console.cpp draw() returns early when hidden), so show it; setup() hides it again
            M2TWEOP.toggleConsole()
            M2TWEOP.restartLua()
            return
        elseif cmd then
            log("control: unknown command '" .. line .. "'")
        end
    end
end

-- How agents' missions turned out (EOP's onBriberyMission, onAssassinationMission, ...), kept
-- per faction until its next report: "done" on an order only means it was issued. has_chance:
-- only events that export missionProbability may be asked for it (it's a raw vfunc call).
local agent_news = {}
-- EOP 3.3.1 bug: missionSuccessLevel looks the level number up in its disaster table
-- (gameHelpers.cpp:276-310), so level 0..3 arrives as earthquake..storm; seen live
local SUCCESS_LEVEL = { earthquake = "not_successful", flood = "slightly_successful",
                        horde = "partly_successful", storm = "highly_successful" }

function M.on_agent_mission(kind, e, has_chance)
    local ok, faction, text = pcall(function()
        local c = e.character
        local who = c and (c.fullName or (c.namedCharacter and c.namedCharacter.fullName)) or "an agent"
        local raw = tostring(e.missionSuccessLevel or "unknown")
        local level = (SUCCESS_LEVEL[raw] or raw):gsub("_", " ")
        local text = string.format("%s's %s: %s", who, kind, level)
        if has_chance then
            local chance = e.missionProbability
            if type(chance) == "number" and chance > 0 then text = text .. string.format(" (chance was %d%%)", chance) end
        end
        return e.faction and e.faction.name, text
    end)
    if not ok or not faction then return end
    local list = agent_news[faction] or {}
    list[#list + 1] = text
    while #list > 20 do table.remove(list, 1) end
    agent_news[faction] = list
    log("agent mission: " .. faction .. ": " .. text)
end

function M.take_agent_news(faction)
    local list = agent_news[faction] or {}
    agent_news[faction] = nil
    return list
end

-- What happened to a faction's characters (EOP's onSufferAssassinationAttempt,
-- onBattleGeneralKilled, ...), kept until its next report: evidence when one of them vanishes.
-- what: the sentence after the name, e.g. "survived or suffered an assassination attempt".
local character_news = {}

function M.on_character_event(what, e, has_disaster)
    local ok, faction, text = pcall(function()
        local c = e.character or e.stratCharacter
        local nc = c and (c.namedCharacter or c)
        local who = nc and nc.fullName and clean_name(nc.fullName) or "a character"
        local fac = e.faction or (nc and nc.faction)
        local text = string.format("%s %s", who, what)
        if has_disaster then
            local okd, kind = pcall(function() return e.disasterType end)
            if okd and kind then text = text .. ": " .. tostring(kind) end
        end
        local okr, region = pcall(function() return gd.stratMap.getRegion(e.regionID).regionName end)
        if okr and region then text = text .. " (in " .. region .. ")" end
        return fac and fac.name, text
    end)
    if not ok or not faction then return end
    local list = character_news[faction] or {}
    list[#list + 1] = text
    while #list > 20 do table.remove(list, 1) end
    character_news[faction] = list
    log("character event: " .. faction .. ": " .. text)
end

function M.take_character_news(faction)
    local list = character_news[faction] or {}
    character_news[faction] = nil
    return list
end

-- What happened in a realm and the world that the game tells a player by message: missions
-- done or failed, riots, rebellions, treaties, crusades, excommunications, disasters. Kept per
-- faction until its next report. fields: the exports this event has (only those may be read:
-- each is a raw vfunc call). to: "own" (the event's faction), "both" (and targetFaction), "all".
local faction_news = {}

local function place_name(s)
    return s and (s.localizedName or s.name) or nil
end

local FIELD = {
    settlement = function(e) return place_name(e.settlement) end,
    targetSettlement = function(e) return place_name(e.targetSettlement) end,
    faction = function(e) return e.faction and e.faction.name end,
    targetFaction = function(e) return e.targetFaction and e.targetFaction.name end,
    missionDetails = function(e) return e.missionDetails end,
    resourceDescription = function(e) return e.resourceDescription end,
    guild = function(e) return e.guild and e.guild.name end,
}

local function add_news(faction, text)
    if not faction then return end
    local list = faction_news[faction] or {}
    list[#list + 1] = text
    while #list > 30 do table.remove(list, 1) end
    faction_news[faction] = list
end

function M.on_faction_event(template, e, fields, to)
    local vals, raw = {}, {}
    for _, f in ipairs(fields) do
        local ok, v = pcall(FIELD[f], e)
        if ok and v ~= nil then raw[f], vals[f] = tostring(v), clean_name(tostring(v)) end
    end
    local text = template:gsub("{(%w+)}", function(k) return raw[k] and (k:find("[Ff]action") and raw[k] or vals[k]) or "?" end)
    if to == "all" then
        for i = 0, stratmap.game.getFactionsCount() - 1 do
            local f = stratmap.game.getFaction(i)
            if f and f.name ~= "slave" then add_news(f.name, text) end
        end
    else
        add_news(raw.faction, text)
        if to == "both" and raw.targetFaction ~= raw.faction then add_news(raw.targetFaction, text) end
    end
    log("faction event: " .. text)
end

function M.take_faction_news(faction)
    local list = faction_news[faction] or {}
    faction_news[faction] = nil
    return list
end

-- what popped up since the human slot's last report (then forgotten)
function M.take_popups()
    local out = popups
    popups = {}
    return out
end

local paused_logged = false

local function tick()
    if not root or not gd then return end
    control()
    local cfg = config()
    if not cfg or not cfg.autoplay then M.status = nil return end
    -- paused (parley/pause.py: a seat's usage limit): end no turn, press nothing, and keep every
    -- wait from running out, so the game resumes where it stopped with nothing decided for anyone
    local reason = read_file(root .. "/paused.txt")
    if reason then
        local now = M.clock()
        for _, p in ipairs(pending) do
            if p.requested then p.requested = now end
            p.at = now
        end
        for _, c in pairs(choosing) do c.since = now end
        for name in pairs(on_screen) do on_screen[name] = now end
        auto.since, watch.since = now, now
        if auto.clicked then auto.clicked = now end
        if not paused_logged then log("paused: " .. reason:gsub("%s+$", "")) end
        paused_logged = true
        M.status = "Parley: paused, the rulers can't answer (" .. reason:gsub("%s+$", "") .. ")"
        return
    end
    if paused_logged then log("resumed") end
    paused_logged = false
    if M.sweep_at and M.clock() >= M.sweep_at then
        M.sweep_at = nil
        local swept = press_tick_part()
        if swept then log("after the reload: closed a leftover " .. swept) end
    end
    handle_popups(M.clock())
    watch_buttons(M.clock())
    close_leftover_diplomacy(M.clock())
    local campaign = gd.campaignStruct
    local fac = campaign.currentFaction
    if not fac then return end
    if fac.isPlayerControlled ~= 1 then return watch_ai_turn(campaign, fac, M.clock()) end
    local turn, now = campaign.turnNumber, M.clock()
    if auto.turn ~= turn then auto = { turn = turn, since = now } end
    if cfg.until_turn and turn >= cfg.until_turn then
        M.status = "Parley autoplay: stopped at turn " .. turn
        if not auto.stopped then log("autoplay: last turn " .. turn .. " reached; not ending it") end
        auto.stopped = true
        return
    end
    if auto.end_next then  -- a popup was dismissed last tick: now End Turn again
        auto.end_next = nil
        click_end_turn()
        return
    end
    if auto.clicked then
        if now - auto.clicked >= STUCK_AFTER then  -- given up or not: try_dismiss paces itself
            auto.clicked = now
            auto.end_next = try_dismiss(auto, "turn " .. turn)
        end
        return
    end
    if cfg.factions[fac.name] then apply_orders(fac, cfg, turn, false) end
    if #ui_jobs > 0 then  -- screen jobs (retraining) first, while no popup holds the screen
        if #pending == 0 and not (M.deciding and M.deciding()) then run_ui_job(now) end
        M.status = string.format("Parley: turn %d, working the screens (%s %s)", turn, ui_jobs[1] and ui_jobs[1].kind or "",
                                 ui_jobs[1] and ui_jobs[1].settlement or "")
        return
    end
    local pending = pending_rulers(cfg, turn, fac)
    local waited = now - auto.since
    if #pending > 0 and waited < (cfg.wait or 300) then
        M.status = string.format("Parley: turn %d, waiting for %s (%ds)", turn, table.concat(pending, ", "), waited)
        return
    end
    if #pending > 0 then
        log(string.format("autoplay: turn %d waited %ds; ending without %s", turn, waited, table.concat(pending, ", ")))
        if cfg.factions[fac.name] then apply_orders(fac, cfg, turn, true) end
    end
    log("autoplay: ending turn " .. turn)
    M.status = "Parley: ending turn " .. turn
    auto.clicked = now
    click_end_turn()
end

local last_error
function M.tick()
    local ok, err = pcall(tick)
    if not ok and tostring(err) ~= last_error then
        last_error = tostring(err)
        pcall(log, "autoplay tick failed: " .. last_error)
    end
end

local next_tick = 0
function M.on_frame()
    local now = M.clock()
    if now < next_tick then return end
    next_tick = now + 2
    M.tick()
end

function M.setup(turn_root)
    root = turn_root
    gd = gameDataAll.get()
    applied = {}
    local cfg = config()
    -- Reloaded mid-turn by the control file: orders already settled this turn stay settled.
    -- (Loading an older save has no marker, and its orders are applied again, on purpose.)
    local marker = read_file(root .. "/reloaded.txt")
    if marker then
        os.remove(root .. "/reloaded.txt")
        local turn = tonumber(marker:match("turn=(%d+)"))
        if cfg and turn and turn == gd.campaignStruct.turnNumber then
            -- a real reload opened EOP's console to run; close it (a stale marker from a reload
            -- that never ran must not: toggling would open it)
            pcall(M2TWEOP.toggleConsole)
            for f in pairs(cfg.factions) do
                local dir = turn_dir(cfg, turn - 1, f)
                if exists(dir .. "/results.json") or exists(dir .. "/late.txt") then applied[dir] = true end
            end
            log("bridge reloaded at turn " .. turn)
            -- a reload forgets the popups already open: close leftover result scrolls soon
            -- (live: a battle result sat a minute until stuck recovery found it)
            M.sweep_at = M.clock() + POPUP_DELAY
        end
    end
    if cfg and cfg.autoplay then
        -- the game's own "auto-resolve all battles" (a hotseat option; may not apply otherwise,
        -- so on_pre_battle clicks the button too)
        local ok = pcall(function() M2TWEOP.getOptions2().autoresolveAllBattles = 1 end)
        log("autoplay: auto-resolve all battles " .. (ok and "on" or "unavailable"))
    end
    pcall(M.snapshot_stances)
    pcall(M.load_stance_orders)
end

return M
