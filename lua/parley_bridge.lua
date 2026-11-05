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
local K = {}  -- the bridge's constants: one local, not 41 (Lua allows 200 per chunk)
M.K = K  -- (tests shorten waits through it)
M.assault_ordered = 0
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
    -- control: faction -> areas; absent = ruler. freeze: factions whose game AI is frozen ("*":
    -- every AI faction, the QA bench's quiet world), thaw: the exceptions to "*"
    local cfg = { factions = {}, control = {}, freeze = {}, thaw = {}, playtest_funds = {} }
    for line in text:gmatch("[^\r\n]+") do
        local k, v = line:match("^([%w_]+)=(.+)$")
        if k == "game_id" then cfg.game_id = v
        elseif k == "faction" then cfg.factions[v] = true
        elseif k == "freeze" then cfg.freeze[v] = true
        elseif k == "thaw" then cfg.thaw[v] = true
        elseif k == "control" then
            local f, areas = v:match("^([%w_]+):(.*)$")
            if f then
                cfg.control[f] = {}
                for a in areas:gmatch("[%w_]+") do cfg.control[f][a] = true end
            end
        elseif k == "playtest_funds" then
            local f, amount = v:match("^([%w_]+):(.*)$")
            if f and tonumber(amount) then cfg.playtest_funds[f] = tonumber(amount) end
        elseif k == "autoplay" then cfg.autoplay = v == "1"
        elseif k == "autoplay_wait" then cfg.wait = tonumber(v)
        elseif k == "autoplay_hold_decisions" then cfg.hold_decisions = v ~= "0"
        elseif k == "autoplay_until" then cfg.until_turn = tonumber(v)
        elseif k == "papal_hands_off" then cfg.papal_hands_off = v == "1" end
    end
    -- read by luaPluginScript's onScrollOpened as a plain field (no call): see there
    local hands_off = cfg.papal_hands_off == true
    if hands_off ~= (M.papal_hands_off == true) then
        log("papal hands-off: " .. (hands_off and "on (papal scrolls never reach the bridge)" or "off"))
    end
    M.papal_hands_off = hands_off
    return cfg.game_id and cfg or nil
end

-- which control area each order belongs to (parley/control.py ORDER_AREA)
K.ORDER_AREA = {
    send_gold = "diplomacy", cede_settlement = "diplomacy", set_stance = "diplomacy",
    march_on = "armies", besiege = "armies", withdraw = "armies", move_army = "armies", attack = "armies",
    merge_units = "armies", disband = "armies",
    merge_armies = "armies", board = "armies", land = "armies", blockade = "armies",
    assassinate = "agents", spy = "agents", bribe = "agents", sabotage = "agents",
    move_agent = "agents", marry = "agents",
    build = "build", repair = "build", recruit = "recruit", retrain = "recruit", recruit_agent = "recruit", hire_mercenary = "recruit",
    set_tax = "taxes",
}
K.RULER_AREAS = { diplomacy = true, armies = true, agents = true }

local function areas_of(cfg, faction) return cfg.control[faction] or K.RULER_AREAS end

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

local function strip_title(name)
    if name == nil then return nil end
    return (tostring(name):gsub("^Admiral%s+", ""):gsub("^Captain%s+", ""))
end

local function same_army_id(a, b)
    if same(a, b) then return true end
    local ta, tb = strip_title(a), strip_title(b)
    return ta ~= nil and tb ~= nil and same(ta, tb)
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
-- where a leaderless stack is: its settlement, its fort, or the fleet carrying it (EOP gives a
-- stack "inside residence (fleet, settlement, fort)" no leader, LuaDocs.lua:2734; aboard a ship
-- its position is the fleet's)
local function residence(st)
    local s = st:findInSettlement()
    if s then return s.xCoord, s.yCoord, s end
    local okf, fort = pcall(function() return st:findInFort() end)
    if okf and fort then return fort.xCoord, fort.yCoord end
    if st.shipArmy and st.shipArmy.leader then return st.shipArmy.leader.xCoord, st.shipArmy.leader.yCoord end
end

local function leader_of(fac, st)
    if not st then return nil end
    if st.leader then return st.leader end
    if not fac then return nil end
    for i = 0, (fac.numOfCharacters or 0) - 1 do
        -- armyLeaded is unproven live (EOP master renamed types): read it under pcall
        local ok, c = pcall(function()
            local c = fac:getCharacter(i)
            if c and c.armyLeaded == st then return c end
        end)
        if ok and c then return c end
    end
    -- aboard a fleet, or a fleet: the general (admiral) of its own units. Live 10-31 18:12: an army
    -- that boarded had no leader, armyLeaded or position, its fleet no leader either; getUnit(0)'s
    -- character was its general
    if st.shipArmy or st.isAdmiral then
        for i = 0, (st.numOfUnits or 0) - 1 do
            local ok, c = pcall(function()
                local c = st:getUnit(i).character
                local t = c and c:getTypeName()
                if t == "general" or t == "named_character" or t == "named character" or t == "admiral" then
                    return c
                end
            end)
            if ok and c then return c end
        end
    end
    local x, y = residence(st)
    if not x and st.xCoord and st.yCoord then x, y = st.xCoord, st.yCoord end
    if not x then return nil end
    for i = 0, (fac.numOfCharacters or 0) - 1 do
        local ok, c = pcall(function()
            local c = fac:getCharacter(i)
            local t = c and c:getTypeName()
            if (t == "general" or t == "named_character" or t == "named character"
                or (st.isAdmiral and t == "admiral") or t == "admiral")
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
    -- Live: turn 59 (Admiral Humphrey) and turn 35 (Admiral Lewes) fleets whose st.leader is nil
    local leader = leader_of(fac, st)
    if leader then return name_of(leader) end
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

local function army_men(st)
    local men = 0
    if st then
        pcall(function()
            for i = 0, (st.numOfUnits or 0) - 1 do
                local u = st:getUnit(i)
                if u then men = men + (u.soldierCountStratMap or 0) end
            end
        end)
    end
    return men
end

-- fac: the stack's own faction, to find the general of a stack EOP names no leader for (one in a
-- settlement or a fort; foreign stacks in sight are never garrisons)
local function army_view(st, id, fac)
    local s = st:findInSettlement()
    local leader = leader_of(fac, st)
    local x, y = residence(st)
    if not x and leader then x, y = leader.xCoord, leader.yCoord end
    local view = {  -- nil fields are left out; the orchestrator reads a missing key as "none"
        id = id,
        leader = leader and name_of(leader) or nil,
        x = x or 0, y = y or 0, strength = st.totalStrength, men = army_men(st), units = st.numOfUnits,
        in_settlement = s and s.name or nil,
    }
    pcall(function()  -- fleets: what they carry; armies at sea: which fleet
        if st.isAdmiral then
            view.is_fleet = true
            view.carrying = st.boardedArmy and st.boardedArmy.numOfUnits or nil
            view.carrying_men = st.boardedArmy and army_men(st.boardedArmy) or nil
        end
        -- the fleet's admiral by leader_of, not st.shipArmy.leader alone: live QA navy 10-31 08:19 an
        -- army that boarded stood on its fleet's sea tile (110,156 -> 111,157, the fleet's) and read
        -- aboard=- for 15 s, five cases running; EOP gives a stack in a residence (a fleet is one) no
        -- leader, as base_id found for fleets on turns 35 and 59
        local ship = st.shipArmy
        local admiral = ship and (ship.leader or leader_of(fac, ship))
        if admiral then view.aboard = name_of(admiral) end
    end)
    pcall(function()  -- a siege it keeps: the town, how long, what is being built (EOP siegeStruct)
        local sg = st.siege
        local town = sg and sg.besiegedSettlement
        if not town then return end
        view.besieging = town.name
        view.siege_turns = sg.siegeTurns
        view.siege_queue = sg.equipmentQueueCount
        view.holdout_turns = town.siegeHoldoutTurns
    end)
    return view
end

-- --- sight ------------------------------------------------------------------------------
-- EOP has no "visible now" query (getTileVisibility is ever-seen), so sight is a radius
-- around everything the faction has on the map: generals, agents and settlements.

K.SIGHT_RADIUS = 10
K.SIGHT_MAX = 12  -- nearest entries kept per list
K.TROOPS_ARMIES = 4  -- foreign armies (nearest first) whose units are listed
K.TROOPS_UNITS = 20  -- units listed per foreign army
K.AGENT_KINDS = { spy = true, assassin = true, diplomat = true, merchant = true,
                      priest = true, princess = true, admiral = true }
K.AGENT_KIND = { assassinate = "assassin", sabotage = "assassin", spy = "spy", bribe = "diplomat" }

K.GENERAL_TYPES = { general = true, named_character = true, ["named character"] = true }

local function agent_kind(c)
    local t = c:getTypeName()
    if K.GENERAL_TYPES[t] then return nil end  -- they lead armies
    return K.AGENT_KINDS[t] and t or "other"
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
                    return K.GENERAL_TYPES[t] and "general" or t
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
        if st.leader then
            eyes[#eyes + 1] = { st.leader.xCoord, st.leader.yCoord }
        else  -- a stack in a fort, or one EOP names no leader for: its general still looks out
            pcall(function()
                if st:findInSettlement() then return end  -- the settlement is an eye already
                local g = leader_of(fac, st)
                if g then eyes[#eyes + 1] = { g.xCoord, g.yCoord } end
            end)
        end
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
    while #list > K.SIGHT_MAX do table.remove(list) end
    return list
end

-- Land crossings: the green-arrow straits an army walks across (the author: "the game should inform
-- llms of crossings"; Scratch planned ships for Dublin, unaware he could walk). EOP's tile
-- isLandConnection marks them. The map is scanned once, on first use, and the crossings kept
-- as { x, y, from, to } (the regions on either side).
local crossings_cache

-- EOP master or 3.3.1, told apart by a field only master has (stratMap.landConnectionsNum)
local function eop_master()
    local ok, n = pcall(function() return gd.stratMap.landConnectionsNum end)
    return ok and type(n) == "number"
end

local function all_crossings()
    if crossings_cache then return crossings_cache end
    local map, found = gd.stratMap, {}
    -- EOP master drops tile.isLandConnection and isSeaCrossing: the straits are a list,
    -- stratMap.landConnectionsNum and stratMap:getLandConnection(i) -> coordPair {xCoord, yCoord}
    -- (types/strategyMap.cpp:1295, 1337, 1559), and the sea crossings tile.hasSeaCrossing (:1702)
    local master = eop_master()
    local n = master and map.landConnectionsNum or 0
    if master then
        for i = 0, n - 1 do
            pcall(function()
                local c = map:getLandConnection(i)
                if c then found[#found + 1] = { x = c.xCoord, y = c.yCoord } end
            end)
        end
    end
    for y = 0, (map.mapHeight or 0) - 1 do
        for x = 0, (map.mapWidth or 0) - 1 do
            -- green-arrow straits (live: Gibraltar, the Bosphorus) and the "close proximity" sea
            -- crossings (live: seven tiles, one at 94,168 between Ireland and Scotland); hasCrossing
            -- (148 tiles) is river fords and bridges, not straits
            local ok, yes = pcall(function()
                local t = map.getTile(x, y)
                if master then return t.hasSeaCrossing == true or t.hasSeaCrossing == 1 end
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
            -- live turn 59: nearest land tile in each region around the crossing
            local regions, best_land, sx, sy = {}, {}, 0, 0
            for _, c in ipairs(group) do
                sx, sy = sx + c.x, sy + c.y
            end
            local cx = math.floor(sx / #group + 0.5)
            local cy = math.floor(sy / #group + 0.5)
            for _, c in ipairs(group) do
                for dx = -1, 1 do
                    for dy = -1, 1 do
                        pcall(function()
                            local tx, ty = c.x + dx, c.y + dy
                            local tile = map.getTile(tx, ty)
                            if tile.isLand == 1 or tile.isLand == true then
                                local rname = map.getRegion(tile.regionID).regionName
                                regions[rname] = true
                                local d2 = (tx - cx) * (tx - cx) + (ty - cy) * (ty - cy)
                                local cur = best_land[rname]
                                if not cur or d2 < cur.d or (d2 == cur.d and (tx < cur.x or (tx == cur.x and ty < cur.y))) then
                                    best_land[rname] = { x = tx, y = ty, d = d2 }
                                end
                            end
                        end)
                    end
                end
            end
            local names, shores = {}, {}
            for n in pairs(regions) do names[#names + 1] = n end
            table.sort(names)
            for _, n in ipairs(names) do
                local b = best_land[n]
                if b then shores[#shores + 1] = { region = n, x = b.x, y = b.y } end
            end
            list[#list + 1] = { x = cx, y = cy, regions = names, shores = shores }
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
        if d and d <= 3 * K.SIGHT_RADIUS then
            list[#list + 1] = { x = c.x, y = c.y, regions = c.regions, shores = c.shores, distance = d }
        end
    end
    table.sort(list, function(a, b) return a.distance < b.distance end)
    return list
end

-- EOP's resourceType enum, by number
K.RESOURCE_NAMES = { [0] = "gold", "silver", "fish", "furs", "grain", "timber", "iron", "ivory",
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
                if d and d <= K.SIGHT_RADIUS then
                    local view = { kind = K.RESOURCE_NAMES[res:getResourceID()] or "unknown", x = res.xCoord,
                                   y = res.yCoord, distance = d, region = region.regionName }
                    pcall(function() view.value = res:getResourceValue() end)
                    pcall(function() view.owner = region.settlement.ownerFaction.name end)
                    list[#list + 1] = view
                end
            end
        end)
    end
    table.sort(list, function(a, b) return a.distance < b.distance end)
    while #list > K.SIGHT_MAX do table.remove(list) end
    return list
end

-- What fac can see now: { armies, agents, settlements }, each a list of { view, char|sett }.
-- Every foreign entity is read in its own pcall: one odd object is skipped, never fatal.
-- Armies and agents share one id space (an order names either), assigned in game order.
-- Is a tile visible to the faction right now? true/false, or nil when EOP's
-- factionStruct:getTileVisibility is missing or errors (callers then use K.SIGHT_RADIUS).
-- The path taken is logged once: "sight: getTileVisibility" or "sight: radius".
function M.visible_now(fac, x, y)
    if M.sight_mode == "radius" then return nil end
    local ok, v = pcall(function() return fac:getTileVisibility(x, y) end)
    if not ok or type(v) ~= "number" then
        if not M.sight_mode then
            M.sight_mode = "radius"
            log("sight: radius (getTileVisibility " .. (ok and "returned " .. type(v) or "failed: " .. tostring(v)) .. ")")
        end
        return nil
    end
    if not M.sight_mode then
        M.sight_mode = "getTileVisibility"
        log("sight: getTileVisibility")
    end
    -- visible or more: live 10-31 the game returns 3..9 (higher where more eyes see the tile; 7-9
    -- beside London), 1 in fog, 2 seen once. Only == 3 counted, and enemies beside own towns dropped out
    return v >= ((_G.tileVisibility or {}).visible or 3)
end

-- In sight: on a tile the faction sees now, else (no visibility call) within K.SIGHT_RADIUS.
function M.in_sight(fac, d, x, y)
    local v = M.visible_now(fac, x, y)
    if v ~= nil then return v end
    return d ~= nil and d <= K.SIGHT_RADIUS
end

-- A foreign army's units, compact: { type, soldiers }, at most K.TROOPS_UNITS. Each read is guarded.
function M.army_troops(st)
    local list = {}
    for i = 0, math.min(st.numOfUnits or 0, K.TROOPS_UNITS) - 1 do
        pcall(function()
            local u = st:getUnit(i)
            list[#list + 1] = { type = u.eduEntry.eduType, soldiers = u.soldierCountStratMap }
        end)
    end
    return list
end

-- a sight oddity, logged once per bridge load (reports are written often)
local sight_notes = {}
local function sight_note(line)
    if sight_notes[line] then return end
    sight_notes[line] = true
    log(line)
end

function M.sight(fac)
    local eyes = eyes_of(fac)
    local people, setts = {}, {}  -- people: foreign armies and agents in sight, game order
    for i = 0, stratmap.game.getFactionsCount() - 1 do
        local other = stratmap.game.getFaction(i)
        if other and other.name ~= fac.name then
            for j = 0, other.stacksNum - 1 do
                pcall(function()
                    local st = other:getStack(j)
                    if st:findInSettlement() then return end  -- garrisons: see settlements
                    if not st.leader and st.shipArmy then return end  -- aboard: the fleet is seen
                    -- EOP names no leader for a stack in a fort (and, live, for some in the
                    -- field): its general is the character leading it or standing on its tile
                    local leader = leader_of(other, st)
                    local x, y = residence(st)
                    if not leader then
                        x, y = x or st.xCoord, y or st.yCoord
                        local d = x and y and distance(eyes, x, y)
                        if d and d <= K.SIGHT_RADIUS then
                            sight_note(string.format("sight: %s stack at (%d,%d) has no general; left out",
                                                     other.name, x, y))
                        end
                        return
                    end
                    if not x then x, y = leader.xCoord, leader.yCoord end
                    local name = name_of(leader)
                    local d = distance(eyes, x, y)
                    if name and d and M.in_sight(fac, d, x, y) then
                        local view = army_view(st, name, other)
                        view.faction, view.distance = other.name, d
                        people[#people + 1] = { name = name, army = true, view = view, char = leader,
                                                stack = st }
                    elseif name and d and d <= 1 and M.sight_mode == "getTileVisibility" then
                        -- next to the ruler's own yet unseen: say what the tile reports (a probe
                        -- for live: the game may hide what stands there, or the tile may be wrong)
                        local okv, v = pcall(function() return fac:getTileVisibility(x, y) end)
                        sight_note(string.format("sight: %s (%s) at (%d,%d), %d tile%s from %s's own, has tile visibility %s",
                            name, other.name, x, y, d, d == 1 and "" or "s", fac.name, okv and tostring(v) or "?"))
                    end
                end)
            end
            for _, a in ipairs(agents_of(other)) do
                pcall(function()
                    local c = a.char
                    local d = distance(eyes, c.xCoord, c.yCoord)
                    if d and M.in_sight(fac, d, c.xCoord, c.yCoord) then
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
            if d and d <= K.SIGHT_RADIUS then
                setts[#setts + 1] = { sett = s, view = {
                    id = s.name, name = s.localizedName, faction = s.ownerFaction.name, x = s.xCoord, y = s.yCoord,
                    garrison_strength = s.army and s.army.totalStrength or 0,
                    garrison_men = army_men(s.army),
                    garrison_units = s.army and s.army.numOfUnits or 0, distance = d } }
            end
        end)
    end
    armies = nearest(armies)
    for i = 1, math.min(#armies, K.TROOPS_ARMIES) do
        local e = armies[i]
        pcall(function()
            if not e.view.is_fleet then
                local t = M.army_troops(e.stack)
                if #t > 0 then e.view.troops = t end
            end
        end)
    end
    return { armies = armies, agents = nearest(agents), settlements = nearest(setts) }
end

local function views(list)
    local out = {}
    for _, e in ipairs(list) do out[#out + 1] = e.view end
    return out
end

-- Regular income and costs, turn after turn; one-off spending and receipts are kept apart
-- (seen live: bribing Bruges for 19464 showed as "income -19170").
K.ECONOMY_IN = { "farmingIncome", "taxesIncome", "miningIncome", "tradeIncome", "merchantIncome",
                     "otherIncome1", "otherIncome2", "tributesIncome", "adminIncome", "kingsPurseIncome" }
K.ECONOMY_OUT = { "wagesExpense", "upkeepExpense", "corruptionExpense", "tributesExpense",
                      "otherExpense1", "otherExpense2", "devastationExpense" }
K.ONE_OFF_OUT = { "constructionExpenseBuildings", "constructionExpenseField",
                      "recruitmentExpenseBuildings", "recruitmentExpenseMercs", "diplomacyExpense" }
K.ONE_OFF_IN = { "diplomacyIncome", "constructionIncome" }

-- (regular net income, one-off spending, one-off receipts) of the turn just played;
-- zeros if EOP can't say (the prompt reads income 0 as "not reported")
-- the regular items behind the net income, as { item = florins } (costs negative), the
-- nonzero ones: what a ruler needs to see what is bleeding him (asked live, turn after turn)
K.INCOME_NAMES = { farmingIncome = "farming", taxesIncome = "taxes", miningIncome = "mining",
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
                    local name = K.INCOME_NAMES[k] or k
                    parts[name] = (parts[name] or 0) + v
                end
            end
        end
        add(K.ECONOMY_IN, 1)
        add(K.ECONOMY_OUT, -1)
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
        return sum(K.ECONOMY_IN) - sum(K.ECONOMY_OUT), sum(K.ONE_OFF_OUT), sum(K.ONE_OFF_IN)
    end)
    if not ok then return 0, 0, 0 end
    return math.floor(net), math.floor(spent), math.floor(got)
end

-- --- what a player sees of its own realm (only for the areas a seat commands) ----------
-- Tax levels: the game's tax_low..tax_extortionate, assumed 0..3 (unverified in EOP's source).
K.TAX_NAMES = { [0] = "low", [1] = "normal", [2] = "high", [3] = "extortionate" }
K.TAX_LEVELS = { low = 0, normal = 1, high = 2, extortionate = 3 }

-- constructionType enum: upgrade = 0, construction = 1, repair = 2 (settlement.h:176, luaEnums.cpp:659)
K.REPAIR_TYPE = 2

-- { name, cost, turns, opt, type } for each building s can queue now
local function construction_options(s)
    local list, opts = {}, nil
    local oko, res = pcall(function() return s:getConstructionOptions() end)
    opts = oko and res or nil
    for i = 0, (opts and opts.buildingNum or 0) - 1 do  -- 0-based, unchecked in EOP: stay in range
        local okc, o = pcall(function() return opts:getConstructionOption(i) end)
        if okc and o then
            local okn, name = pcall(function() return o:getQueueBuildingName() end)
            local okt, ctype = pcall(function() return o.constructionType end)
            list[#list + 1] = {
                name = okn and name or nil,
                cost = o.buildCost,
                turns = o.buildTurnsRemaining,
                opt = o,
                type = okt and ctype or nil,
            }
        end
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
                                    upkeep = e.upkeepCost, edu = p.eduIndex, pool = p }
            end
        end
    end
    return list
end

-- Recruits in training, kept in a file so a reload or a restart doesn't lose them:
-- { {faction, settlement, edu, unit, ready}, ... }; created at the faction's turn start once ready.
-- One file per game, beside its turn folders (live: a new game found the last game's recruits,
-- due at turn 227, still in a shared file).
local function training_path()
    local cfg = config()
    return root .. (cfg and ("/" .. cfg.game_id) or "") .. "/training.json"
end

local function read_training()
    local text = read_file(training_path())
    local ok, list = pcall(json.decode, text or "[]")
    return (ok and type(list) == "table") and list or {}
end

-- Agents, recruited by direct write like units (EOP has no call that recruits one), by the
-- game's rules in export_descr_buildings.txt. EOP 3.3.1's getAgentCapability and
-- getAgentLimitCapability return garbage (live: London with a cathedral and a great_market
-- returned 0 for every type; Caen, York and Dublin returned -1 for spy and assassin), so the
-- rules come from the EDB instead: a settlement trains an agent only with a building level that
-- grants it for the faction or its culture, the faction's agents of a type stay under the sum of
-- its settlements' agent_limit lines (when the EDB sets one), and each costs its culture's price
-- in descr_cultures.txt. EOP doesn't expose that price to Lua; vanilla gives every culture the
-- same, so it is written here: { EOP agent type, florins }. One turn to train, then the game's
-- own spawn_character.
K.AGENT_RECRUIT = { spy = { 0, 350 }, assassin = { 1, 500 }, diplomat = { 2, 250 },
                        merchant = { 4, 550 }, priest = { 5, 200 } }
K.AGENT_ORDER = { "spy", "assassin", "diplomat", "merchant", "priest" }

local edb_cache

local function parse_edb(text)
    local levels, limited = {}, {}
    local pending, current
    for raw in text:gmatch("[^\r\n]+") do
        local line = raw:gsub(";.*$", ""):match("^%s*(.-)%s*$")
        if line ~= "" then
            if pending then
                if line == "{" then
                    current = pending
                    levels[current] = levels[current] or { agents = {}, limits = {} }
                end
                pending = nil
            end
            local name, kind, rest = line:match("^(%S+)%s+(%S+)%s*(.*)$")
            if name and (kind == "city" or kind == "castle") and (rest == "" or rest == "requires" or rest:match("^requires%s")) then
                pending = name
            elseif current then
                local akind = line:match("^agent%s+([%w_]+)")
                if akind then
                    local allow = levels[current].agents[akind] or {}
                    local flist = line:match("factions%s*{([^}]*)}")
                    if flist then
                        for f in flist:gmatch("[%w_]+") do allow[f] = true end
                    else
                        allow["*"] = true
                    end
                    levels[current].agents[akind] = allow
                end
                local lkind, n = line:match("^agent_limit%s+([%w_]+)%s+(%d+)")
                if lkind then
                    levels[current].limits[lkind] = (levels[current].limits[lkind] or 0) + tonumber(n)
                    limited[lkind] = true
                end
            end
        end
    end
    return { levels = levels, limited = limited }
end

local function edb_rules()
    if edb_cache then return edb_cache end
    local text = read_file(root .. "/../mods/parley/data/export_descr_buildings.txt")
              or read_file(root .. "/../data/export_descr_buildings.txt")
    if not text then
        log("export_descr_buildings.txt not found; no settlement can train agents")
        edb_cache = { levels = {}, limited = {} }
        return edb_cache
    end
    edb_cache = parse_edb(text)
    return edb_cache
end

local function building_levels(s)
    local list = {}
    for b = 0, (s.buildingsNum or 0) - 1 do
        local bld = s:getBuilding(b)
        if bld then
            local ok, name = pcall(function() return bld:getName() end)
            list[#list + 1] = ok and name or bld:getType()
        end
    end
    return list
end

local function culture_of(fac)
    local ok, name = pcall(function() return M2TWEOP.getCultureName(fac.cultureID) end)
    return ok and type(name) == "string" and name or nil
end

local function can_train_agent(s, fac, kind)
    local rules = edb_rules()
    local culture = fac and culture_of(fac)
    for _, name in ipairs(building_levels(s)) do
        local lvl = rules.levels[name]
        local allow = lvl and lvl.agents[kind]
        if allow and (allow["*"] or (fac and allow[fac.name]) or (culture and allow[culture])) then
            return true
        end
    end
    return false
end

-- kind -> { have = on the map or in training, limit = summed over the faction's settlements (nil if unlimited) }
local function agent_counts(fac)
    local rules = edb_rules()
    local counts = {}
    for kind in pairs(K.AGENT_RECRUIT) do
        counts[kind] = { have = 0, limit = rules.limited[kind] and 0 or nil }
    end
    for _, a in ipairs(agents_of(fac)) do
        if counts[a.kind] then counts[a.kind].have = counts[a.kind].have + 1 end
    end
    for _, t in ipairs(read_training()) do
        if t.faction == fac.name and counts[t.agent] then counts[t.agent].have = counts[t.agent].have + 1 end
    end
    for i = 0, (fac.settlementsNum or 0) - 1 do
        local s = fac:getSettlement(i)
        if s then
            for _, name in ipairs(building_levels(s)) do
                local lvl = rules.levels[name]
                if lvl then
                    for kind, n in pairs(lvl.limits) do
                        if counts[kind] and counts[kind].limit then
                            counts[kind].limit = counts[kind].limit + n
                        end
                    end
                end
            end
        end
    end
    return counts
end

-- { agent, cost, turns } for each agent s can train now
local function agent_options(s, counts)
    local list, fac = {}, s.ownerFaction
    for _, kind in ipairs(K.AGENT_ORDER) do
        local a, c = K.AGENT_RECRUIT[kind], counts[kind]
        if can_train_agent(s, fac, kind) and (not c.limit or c.have < c.limit) then
            list[#list + 1] = { agent = kind, cost = a[2], turns = 1 }
        end
    end
    return list
end

local function deliver_training(fac, turn)
    local list, keep = read_training(), {}
    for _, t in ipairs(list) do
        if t.faction == fac.name and t.ready <= turn then
            local lost, at = false, ""
            local ok, err = pcall(function()
                if t.army_leader then  -- a mercenary hired by an army: it joins that army, wherever it stands now
                    local found
                    for i = 0, (fac.stacksNum or 0) - 1 do
                        local st = fac:getStack(i)
                        local l = st and leader_of(fac, st)
                        if l and name_of(l) == t.army_leader then found = st break end
                    end
                    if not found then lost = true error("the army of " .. t.army_leader .. " is gone") end
                    if (found.numOfUnits or 0) >= 20 then error("the army of " .. t.army_leader .. " is full") end
                    local unit = found:createUnitByIDX(t.edu, t.exp or 0, 0, 0)
                    if t.merc and unit then pcall(function() unit.isMercenary = true end) end
                    return
                end
                local s = gd.stratMap:getSettlement(t.settlement)
                if not (s and s.ownerFaction and s.ownerFaction.name == fac.name) then
                    lost = true
                    error("the settlement was lost")
                end
                if t.agent then  -- never retried: a spawn the count missed would make a second agent
                    local args = string.format("%s, random_name, %s, age 20, x %d, y %d",
                                               fac.name, t.agent, s.xCoord, s.yCoord)
                    local before = #agents_of(fac)
                    lost = true  -- from here on, the game may have made him
                    stratmap.game.scriptCommand("spawn_character", args)
                    if #agents_of(fac) <= before then error("UNCONFIRMED: no new " .. t.agent .. " counted after spawn_character") end
                    return
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
                if M.is_ship(t.edu) then  -- to sea as a fleet, not into the land garrison
                    lost = true  -- never retried: a spawn the check missed would make a second fleet
                    local x, y = M.launch_ship(fac, s, t.edu)
                    at = string.format(" (a fleet at (%d,%d))", x, y)
                    return
                end
                local army = s.army or stratmap.game.createArmyInSettlement(s)
                if not army then error("no garrison to join") end
                local unit = army:createUnitByIDX(t.edu, t.exp or 0, 0, 0)
                if t.merc and unit then pcall(function() unit.isMercenary = true end) end  -- upkeep as a hireling
            end)
            log(string.format("%s: %s %s in %s%s%s", fac.name, t.unit, t.retrain and "retrained" or "trained",
                t.settlement or t.army_leader, at,
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
    local n = q and q.numBuildingsInQueue or 0
    if eop_master() then
        -- EOP master's getBuildingInQueue(i) returns the circular buffer's element head+i
        -- (types/settlement.cpp:972, realGameTypes.h:217) though documented 1-based: i = 1..n-1
        -- are items 2..n, item 1 (the one being built) can't be reached, and i = n is an empty
        -- slot whose getQueueBuildingName crashed the game (live, scratch2, England's report)
        if n > 0 then names[1] = "(the building under construction: its name can't be read on this EOP)" end
        for pos = 1, n - 1 do
            local b = q:getBuildingInQueue(pos)
            if b then names[#names + 1] = b:getQueueBuildingName() end
        end
        return names
    end
    for pos = 1, n do  -- 1-based and bounds-checked in EOP 3.3.1
        local b = q:getBuildingInQueue(pos)
        if b then names[#names + 1] = b:getQueueBuildingName() end
    end
    return names
end

-- the game's own recruitment queue, EOP master only: settlement:getUnitInQueue(i) is 0-based
-- with no bounds check in C++ (types/settlement.h:743), so never past unitInQueueCount - 1
local function recruit_queue_of(s)
    local list = {}
    for i = 0, math.min(s.unitInQueueCount or 0, 9) - 1 do
        local u = s:getUnitInQueue(i)
        if u then
            local name = u.recruitType == 2 and "an agent" or (u.eduEntry and u.eduEntry.eduType) or "a unit"
            local left = (u.recruitTime or 0) - (u.turnsTrained or 0)
            list[#list + 1] = string.format("%s (%d turn%s left)", name, left, left == 1 and "" or "s")
        end
    end
    return list
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
K.ORDER_PARTS = {
    garrison = "PublicOrderGarrison", law = "PublicOrderLaw", buildings = "PublicOrderBuildingsEntertainment",
    entertainment = "PublicOrderEntertainment", governor = "PublicOrderGovernorInfluence",
    ["low tax"] = "PublicOrderTaxBonus", ["high tax"] = "PublicOrderTaxPenalty", squalor = "PublicOrderSqualor",
    unrest = "PublicOrderUnrest", ["distance to capital"] = "PublicOrderDistanceToCapital",
    ["cultural unrest"] = "PublicOrderCulturalUnrest", health = "PublicOrderHealth", fear = "PublicOrderFear",
    glory = "PublicOrderGlory", excommunication = "PublicOrderExcommunication",
    ["no governor"] = "PublicOrderNoGovernance", besieged = "PublicOrderBesieged",
    blockaded = "PublicOrderBlockaded", ["population boom"] = "PublicOrderPopulationBoom",
}

-- revolt and money signals (EOP settlementStruct, settlement.cpp:1285,1303,1306,1284 and the
-- settlementStats income members). Each read on its own pcall; M.* because the file is at Lua's local limit.
function M.add_unrest(view, s)
    pcall(function() view.rebelling = (s.isProvokedRebellion or 0) ~= 0 or nil end)
    pcall(function() view.plagued = s.plagued and true or nil end)
    pcall(function()
        local t = s.turmoil
        if type(t) == "number" and t ~= 0 then view.turmoil = math.floor(t) end
    end)
    pcall(function()
        local c = s.rebelFactionChance
        if type(c) == "number" then view.rebel_chance = math.floor(c) end
    end)
    pcall(function() view.income = math.floor(s.settlementStats.TotalIncomeWithoutAdmin) end)
    pcall(function() view.taxes_income = math.floor(s.settlementStats.TaxesIncome) end)
end

-- own besieging army: can it assault now (EOP canStartAssault)
function M.add_can_assault(view, st)
    pcall(function()
        local town = st.siege and st.siege.besiegedSettlement
        if not town then return end
        local can = st:canStartAssault(town)
        if type(can) == "boolean" then view.can_assault = can end
    end)
end

-- an own town under siege: who, how strong, how long, how long it can hold (Scratch, live: "one
-- of my settlements was reported besieged, and the report doesn't say which"). M.report's
-- settlement view and the QA siege suite (M.qa.town_siege) both read it from here
function M.add_siege(view, s)
    pcall(function()
        if (s.siegesNum or 0) > 0 then
            local sg = s:getSiege(0)
            local st = sg.besieger
            local view_s = { turns = sg.siegeTurns, holdout = s.siegeHoldoutTurns }
            pcall(function() view_s.by = name_of(st.leader) end)
            pcall(function() view_s.faction = st.leader.namedCharacter.faction.name end)
            pcall(function() view_s.strength = st.totalStrength end)
            view_s.men = army_men(st)
            pcall(function() view_s.units = st.numOfUnits end)
            view.siege = view_s
        end
    end)
end

-- advice only, never a refusal: what the game says about starting a siege or an assault
-- (EOP armyStruct:canStartSiege / canStartAssault, army.cpp:237,253). nil when it can't be read.
function M.siege_check(st, town, assault)
    local ok, can = pcall(function()
        if assault then return st:canStartAssault(town) end
        return st:canStartSiege(town)
    end)
    if not ok or type(can) ~= "boolean" then return nil end
    if can then return nil end
    if assault then
        return "the game says this army can't assault yet (the walls stand and it has too few siege engines "
            .. "that can breach them); the order still went to the game"
    end
    return "the game says this army can't besiege " .. town.name .. " (it needs infantry to carry equipment or "
        .. "siege engines); the order still went to the game"
end

local function add_management(view, s, areas, counts)
    pcall(function()
        view.tax_level = K.TAX_NAMES[s.settlementTaxLevel]
        view.public_order = math.floor(s.settlementStats.PublicOrder)
    end)
    pcall(function()
        local stats, parts = s.settlementStats, {}
        for name, field in pairs(K.ORDER_PARTS) do
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
                if o.type ~= K.REPAIR_TYPE and o.name then
                    view.can_build[#view.can_build + 1] = { building = o.name, cost = o.cost, turns = o.turns }
                end
            end
        end)
    end
    if areas.recruit then
        pcall(function()
            view.can_recruit = {}
            for _, o in ipairs(recruitment_options(s)) do
                view.can_recruit[#view.can_recruit + 1] = { unit = o.name, cost = o.cost, turns = o.turns,
                                                            upkeep = o.upkeep }
            end
        end)
        if counts then pcall(function() view.can_recruit_agents = agent_options(s, counts) end) end
        if eop_master() then pcall(function() view.recruit_queue = recruit_queue_of(s) end) end
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

local recorded_moves = {}  -- fac.name -> list of move orders given this turn
local unmade_moves = {}    -- fac.name -> list of moves that did not happen
local check_moves_not_made

function M.report(fac, cfg)
    local campaign, map = gd.campaignStruct, gd.stratMap
    local settlements, armies, factions = {}, {}, {}
    local areas = areas_of(cfg, fac.name)
    local manages = areas.build or areas.recruit or areas.taxes
    local training = read_training()
    local okc, counts = false, nil
    if areas.recruit then
        okc, counts = pcall(agent_counts, fac)
        if not okc then
            log(fac.name .. ": agent counts failed: " .. tostring(counts))
            counts = nil
        end
    end
    for i = 0, fac.settlementsNum - 1 do
        local s = fac:getSettlement(i)
        local buildings = {}
        local damaged_buildings = {}
        -- the level (small_church, not temple_catholic): an upgrade must show as a change
        for b = 0, (s.buildingsNum or 0) - 1 do
            local okb, bld = pcall(function() return s:getBuilding(b) end)
            if okb and bld then
                local ok, name = pcall(function() return bld:getName() end)
                local okt, tname = pcall(function() return bld:getType() end)
                name = (ok and name) or (okt and tname) or "building"
                buildings[#buildings + 1] = name
                local okh, hp = pcall(function() return bld.hp end)
                if okh and type(hp) == "number" and hp < 100 then
                    damaged_buildings[#damaged_buildings + 1] = { name = name, hp = math.floor(hp) }
                end
            end
        end
        local view = {
            id = s.name, name = s.localizedName, region = map.getRegion(s.regionID).regionName,
            garrison_strength = s.army and s.army.totalStrength or 0,
            garrison_men = army_men(s.army),
            garrison_units = s.army and s.army.numOfUnits or 0,
            population = s.populationSize, buildings = buildings,
            damaged_buildings = damaged_buildings,
        }
        M.add_unrest(view, s)  -- every ruler loses towns to revolt, not only the managers
        -- where it is, and its port (the tile a fleet docks at): asked for live, again and again
        pcall(function() view.x, view.y = s.xCoord, s.yCoord end)
        pcall(function()
            local r = map.getRegion(s.regionID)
            if (r.portEntranceXCoord or 0) > 0 then view.port_x, view.port_y = r.portEntranceXCoord, r.portEntranceYCoord end
        end)
        M.add_siege(view, s)
        for _, t in ipairs(training) do
            if t.faction == fac.name and t.settlement == s.name then
                view.training = view.training or {}
                view.training[#view.training + 1] = { unit = t.unit, ready_turn = t.ready }
            end
        end
        if manages then add_management(view, s, areas, counts) end
        settlements[#settlements + 1] = view
    end
    local ids = army_ids(fac)
    for i = 0, fac.stacksNum - 1 do
        local st = fac:getStack(i)
        local view = army_view(st, ids[i], fac)
        M.add_can_assault(view, st)
        M.add_can_hire(view, st, fac, campaign)
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
            -- EOP master's treaty record per pair (types/campaign.h:675, ids 0..30, nil outside);
            -- read only: setDipStance stays the one way to change it
            if eop_master() then
                put("treaties", function()
                    local d = campaign:getFactionDiplomacy(fac.factionID, other.factionID)
                    local back = campaign:getFactionDiplomacy(other.factionID, fac.factionID)
                    if not d then return nil end
                    local list = {}
                    if d.hasTradeRights then list[#list + 1] = "trade rights" end
                    if d.hasMilitaryAccess then list[#list + 1] = "military access" end
                    if d.isProtectorate or (back and back.isProtectorate) then list[#list + 1] = "protectorate" end
                    return list
                end)
                put("turns_in_stance", function()
                    local d = campaign:getFactionDiplomacy(fac.factionID, other.factionID)
                    return d and d.numTurnsState
                end)
            end
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
    local nearby = views(seen.settlements)
    local okb, errb = pcall(M.mark_by_land, fac, nearby)
    if not okb then log(fac.name .. ": by_land failed: " .. tostring(errb)) end
    local turn = campaign.turnNumber
    local last = read_file(turn_dir(cfg, turn - 1, fac.name) .. "/results.json")
    local net, spent, received = income(fac)
    return {
        protocol = 1, game_id = cfg.game_id, turn = turn, year = math.floor(campaign.currentDate),
        faction = fac.name, treasury = fac.money, income = net,
        spent_last_turn = spent, received_last_turn = received,
        settlements = settlements, armies = armies, factions = factions, agents = agents,
        agent_limits = counts,
        visible_enemies = views(seen.armies), seen_agents = views(seen.agents),
        nearby_settlements = nearby, last_results = last and json.decode(last) or {},
        human_slot = fac.isPlayerControlled == 1, map_width = map.mapWidth, map_height = map.mapHeight,
        popups = fac.isPlayerControlled == 1 and M.take_popups() or nil,
        agent_results = M.take_agent_news(fac.name),
        family = family, character_events = M.take_character_news(fac.name),
        news = M.take_faction_news(fac.name),
        income_parts = income_parts(fac),
        resources = (function() local ok, r = pcall(M.resources, fac); return ok and r or nil end)(),
        crossings = (function() local ok, r = pcall(M.crossings, fac); return ok and r or nil end)(),
        stance_changes = M.take_stance_news and M.take_stance_news(fac.name) or nil,
        moves_not_made = unmade_moves[fac.name] or {},  -- last turn's, checked at this turn's start
    }
end

-- --- applying orders -----------------------------------------------------------------

local find_army_now

-- the army an id named earlier this turn, if it is still one of the faction's stacks: moving can
-- rename a captain mid-turn (live, 2026-10-29, turn 117: France moved Captains Marcel, Henri and
-- Raoulet, then merge_units on each came back "unknown army")
local function find_army(fac, id)
    local found = M.found_this_turn and M.found_this_turn[fac.name]
    local st = found and found[id]
    if st then
        for i = 0, (fac.stacksNum or 0) - 1 do
            if fac:getStack(i) == st then return st end
        end
    end
    st = find_army_now(fac, id)
    if st and found then found[id] = st end
    return st
end

find_army_now = function(fac, id)
    local ids = army_ids(fac)
    for i = 0, (fac.stacksNum or 0) - 1 do
        if same_army_id(ids[i], id) then return fac:getStack(i) end
    end
    -- Live: turn 59 (Admiral Humphrey) / turn 35 (Admiral Lewes): leader name match if ids shifted
    for i = 0, (fac.stacksNum or 0) - 1 do
        local st = fac:getStack(i)
        if st then
            local leader = leader_of(fac, st)
            if leader and same_army_id(name_of(leader), id) then return st end
        end
    end
    -- Fallback: character whose armyLeaded is set or who stands with the stack
    for i = 0, (fac.numOfCharacters or 0) - 1 do
        local ok, st = pcall(function()
            local c = fac:getCharacter(i)
            if c and same_army_id(name_of(c), id) then
                if c.armyLeaded then return c.armyLeaded end
                for j = 0, (fac.stacksNum or 0) - 1 do
                    local s = fac:getStack(j)
                    if s and leader_of(fac, s) == c then return s end
                end
            end
        end)
        if ok and st then return st end
    end
    -- the army the ruler's report listed under this id, standing on the same tile now: a captain
    -- renamed since (live, 2026-10-29: France's 13 units at (93,129) were Captain Georges in the
    -- report and Captain Clement when the orders ran; 25 orders failed as "unknown army"). One of
    -- the faction's own stacks per tile, and its own armies don't move between report and turn.
    local at = M.reported_at and M.reported_at[fac.name] and M.reported_at[fac.name][id]
    if at then
        for i = 0, (fac.stacksNum or 0) - 1 do
            local st = fac:getStack(i)
            local l = st and leader_of(fac, st)
            if l and l.xCoord == at.x and l.yCoord == at.y then return st end
        end
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

-- march_on, besiege and withdraw: an admiral's stack handed to them is a C++ call pcall can't catch
local function land_general(fac, id)
    local st, leader = general(fac, id)
    if st and st.isAdmiral then return nil, "'" .. tostring(id) .. "' is a fleet; that order is for land armies" end
    return st, leader
end

-- the refusal for a mover with no movement points left this turn, or nil; checked before every
-- moveToTile (and a merge's walk). Live (run8, 2026-10-30): moves were issued with moveToTile and
-- came back "done" while the mover stood still. EOP's character.movePointsCharacter
-- (LuaDocs.lua:6481) is what he has left; movePointsArmy (:6493) his army's. Never blocks on
-- missing data: a read that fails or isn't a number goes ahead as before, and so does a character
-- at 0 whose army still reads above 0 (the game decides), or a move to the tile he stands on.
local TIRED = {
    army = "an army that just took a town, fought or marched its full distance",
    fleet = "a fleet that fought or sailed its full distance",
    agent = "an agent that walked its full distance",
}
function M.no_moves_left(char, kind, x, y)
    if not char then return nil end
    local ok, left = pcall(function() return char.movePointsCharacter end)
    if not ok or type(left) ~= "number" or left > 0 then return nil end
    local oka, army = pcall(function() return char.movePointsArmy end)
    if oka and type(army) == "number" and army > 0 then return nil end
    if x and y then
        local okh, here = pcall(function()
            return math.floor(char.xCoord) == math.floor(x) and math.floor(char.yCoord) == math.floor(y)
        end)
        if okh and here then return nil end
    end
    local okn, who = pcall(name_of, char)
    who = (okn and who and who ~= "") and who or ("this " .. (kind or "army"))
    return string.format("%s has no moves left this turn (%s can't move again until next turn); order it again "
        .. "next turn", who, TIRED[kind] or TIRED.army)
end

local function record_move(fac, id, kind, from_x, from_y, target, order_type)
    if not (fac and id and from_x and from_y) then return end
    -- a move to the tile it stands on can't fail (live: merge_armies sends a captain out of a
    -- garrison and moves the garrison to its own tile; it was reported as a move that didn't happen)
    if tostring(target) == string.format("(%d,%d)", math.floor(from_x), math.floor(from_y)) then return end
    local list = recorded_moves[fac.name] or {}
    list[#list + 1] = {
        id = tostring(id),
        kind = kind or "army",
        from_x = math.floor(from_x),
        from_y = math.floor(from_y),
        target = tostring(target or ""),
        order_type = tostring(order_type or "move"),
    }
    recorded_moves[fac.name] = list
end

-- the faction's own settlement a land general stands in, or nil
function M.town_under(fac, c)
    if not c then return nil end
    local okt, t = pcall(function() return c:getTypeName() end)
    if okt and t == "admiral" then return nil end
    local okx, x, y = pcall(function() return math.floor(c.xCoord), math.floor(c.yCoord) end)
    if not okx then return nil end
    for i = 0, (fac.settlementsNum or 0) - 1 do
        local ok, s = pcall(function() return fac:getSettlement(i) end)
        if ok and s and s.xCoord == x and s.yCoord == y then return s end
    end
end

-- Moves a general to (x, y). Live (run8 turn 18, Robert in Paris; QA field garrison_general_leaves,
-- 2026-10-30 22:59/23:18/23:29, Rufus and Anthony Haynes in London): moveToTile on a general inside
-- a settlement does nothing, and the next turn's check finds him still in the town. EOP's
-- factionStruct:splitArmy(units, x, y) (LuaDocs.lua:9455-9459: "They enter and leave settlements")
-- sends the units named out of their stack to (x, y), so a general in a town goes out with his
-- bodyguard (character.bodyguards, LuaDocs.lua:6459) that way; the garrison stays. Returns the town
-- he left by the split, or nil when he was moved by moveToTile (not in a town, no bodyguard to
-- read, or the split raised: never block an order the game may still carry out).
-- A mover with no moves left is refused here too (M.no_moves_left, #267): the second value is the
-- reason and nothing moves. Live QA field 10-30 23:59: a split ran for a general the bench meant
-- to have 0 moves, so every path that moves a general checks it on the way out.
--
-- The unit handed to splitArmy is the one the stack holds: EOP's own example builds the table from
-- armyStruct:getUnit(i) (LuaDocs index.html, factionStruct:splitArmy usage). Live QA field 10-31
-- 00:01:21 a split of `{ leader.bodyguards }` for Simon Townsend (leading Nottingham's garrison)
-- raised nothing and he was still inside at the next turn; at 23:59:22 the same call took Howard
-- Stafford (in the town, not its leader) out to (104,152). Which difference matters is unproven,
-- so the unit is looked up the documented way, and where he stands right after the call is logged.
local function own_unit(fac, leader, town)
    local okb, bg = pcall(function() return leader.bodyguards end)
    bg = okb and bg or nil
    local okid, bgid = pcall(function() return bg and bg.ID end)
    bgid = okid and bgid or nil
    local stacks = {}
    for _, field in ipairs({ "army", "visitingArmy", "armyLeaded" }) do
        local ok, st = pcall(function() return leader[field] end)
        if ok and st then stacks[#stacks + 1] = st end
    end
    for i = 0, (fac.stacksNum or 0) - 1 do
        local ok, st = pcall(function()
            local st = fac:getStack(i)
            return st and st:findInSettlement() == town and st or nil
        end)
        if ok and st then stacks[#stacks + 1] = st end
    end
    local okt, tarmy = pcall(function() return town.army end)
    if okt and tarmy then stacks[#stacks + 1] = tarmy end
    for _, st in ipairs(stacks) do
        local okn, n = pcall(function() return st.numOfUnits end)
        for i = 0, ((okn and type(n) == "number") and n or 0) - 1 do
            local ok, u = pcall(function()
                local u = st:getUnit(i)
                if not u then return nil end
                if (bg and u == bg) or u.character == leader or (bgid and u.ID == bgid) then return u end
            end)
            if ok and u then return u, st end
        end
    end
    return nil, nil, bg
end

-- the tile next to the town to split onto on the way to (x, y): land, nobody on it, no settlement,
-- the nearest to (x, y); the target itself when it is next to the town. Live (run9 turns 22-27,
-- Robert in Caen): splitArmy to a target 11 or 18 tiles off returned and did nothing, turn after
-- turn; to the next tile it worked, and moveToTile from there walked him on the same turn.
local function step_out(town, x, y)
    local tx, ty = math.floor(town.xCoord), math.floor(town.yCoord)
    x, y = math.floor(x), math.floor(y)
    if math.max(math.abs(x - tx), math.abs(y - ty)) <= 1 then return x, y end
    local taken = {}
    for i = 0, stratmap.game.getFactionsCount() - 1 do
        local f = stratmap.game.getFaction(i)
        for j = 0, (f and f.numOfCharacters or 0) - 1 do
            pcall(function()
                local c = f:getCharacter(j)
                taken[math.floor(c.xCoord) * 1000 + math.floor(c.yCoord)] = true
            end)
        end
    end
    local map = gd.stratMap
    for r = 0, (map.regionsNum or 0) - 1 do
        pcall(function()
            local s = map.getRegion(r).settlement
            if s then taken[math.floor(s.xCoord) * 1000 + math.floor(s.yCoord)] = true end
        end)
    end
    taken[tx * 1000 + ty] = true
    local best, bx, by
    for dx = -1, 1 do
        for dy = -1, 1 do
            local sx, sy = tx + dx, ty + dy
            local ok, land = pcall(function()
                local t = map.getTile(sx, sy)
                return t and (t.isLand == true or t.isLand == 1)
            end)
            if ok and land and not taken[sx * 1000 + sy] then
                local d = (x - sx) ^ 2 + (y - sy) ^ 2
                if not best or d < best then best, bx, by = d, sx, sy end
            end
        end
    end
    return bx, by
end

function M.walk(fac, leader, x, y)
    local tired = M.no_moves_left(leader, "army", x, y)
    if tired then return nil, tired end
    local town = M.town_under(fac, leader)
    -- live (run9 turns 22-35, Robert in Caen): every split out of Caen while Luquin, then
    -- Garnot besieged it did nothing; the one that worked (03:17) came between sieges. Nobody
    -- marches out of a besieged town: the way out is to attack the besieger (a sally)
    local okb, besieger = pcall(function()
        if town and (town.siegesNum or 0) > 0 then return town:getSiege(0).besieger end
    end)
    if okb and besieger then
        local who, whose = "the besieger", nil
        pcall(function() who = name_of(besieger.leader) end)
        pcall(function() whose = besieger.leader.namedCharacter.faction.name end)
        return nil, string.format("%s is under siege by %s%s: nobody can march out of a besieged town. "
            .. "To break the siege, attack the besieger from inside: {\"type\": \"attack\", \"army\": "
            .. "\"garrison:%s\", \"target\": \"%s\"%s}; or hold and wait for relief",
            tostring(town.name), tostring(who), whose and (" (" .. whose .. ")") or "", tostring(town.name),
            tostring(who), whose and (", \"target_faction\": \"" .. whose .. "\"") or "")
    end
    if town then
        local unit, _, bg = own_unit(fac, leader, town)
        local how = "his unit in the town's stack"
        if not unit and bg then
            unit, how = bg, "character.bodyguards (not found among the stack's units)"
        end
        local okst, sx, sy = pcall(step_out, town, x, y)
        if not (okst and sx) then
            -- a split straight to a target past the next tile does nothing (run9, above): refuse
            -- rather than report a move that won't happen. Live QA 10-31 08:16:37 and 08:18:37:
            -- every tile beside London was taken, the split went to (100,143) and (112,144) and
            -- Edgar Stanley stayed in London while the order said "ok"
            local why = string.format("%s can't step out of %s: no free land tile beside it (%s), and a "
                .. "split straight to (%d,%d) doesn't move him. Move whoever stands next to %s first, "
                .. "or order him again next turn", tostring(name_of(leader)), tostring(town.name),
                okst and "all taken or sea" or tostring(sx), math.floor(x), math.floor(y), tostring(town.name))
            log(fac.name .. ": " .. why)
            return nil, why
        end
        if unit then
            local ok, err = pcall(function() fac:splitArmy({ unit }, sx, sy) end)
            if ok then
                log(string.format("%s: %s splits out of %s with his bodyguard onto (%d,%d) toward (%d,%d) (%s)",
                    fac.name, tostring(name_of(leader)), tostring(town.name), math.floor(sx), math.floor(sy),
                    math.floor(x), math.floor(y), how))
                if math.floor(sx) ~= math.floor(x) or math.floor(sy) ~= math.floor(y) then
                    local okm, errm = pcall(function() leader:moveToTile(x, y) end)
                    if not okm then
                        log(string.format("%s: moveToTile after the split failed for %s (%s)", fac.name,
                            tostring(name_of(leader)), tostring(errm)))
                    end
                end
                local okp, px, py = pcall(function() return math.floor(leader.xCoord), math.floor(leader.yCoord) end)
                if okp then
                    log(string.format("%s: after the split %s stands at (%d,%d)%s", fac.name,
                        tostring(name_of(leader)), px, py,
                        (px == math.floor(town.xCoord) and py == math.floor(town.yCoord)) and ", still in "
                            .. tostring(town.name) or ""))
                end
                return town
            end
            log(string.format("%s: splitArmy for %s failed (%s); moveToTile instead", fac.name,
                tostring(name_of(leader)), tostring(err)))
        end
    end
    leader:moveToTile(x, y)
end

-- the id a move is checked by: a general inside a town leaves the garrison's id behind him
local function mover_id(fac, id, leader)
    if M.town_under(fac, leader) then
        local ok, n = pcall(name_of, leader)
        if ok and n and n ~= "" then return n end
    end
    return id
end

local function left_town_note(leader, town, army)
    local who = name_of(leader)
    return string.format("only %s and his bodyguard march out; the garrison stays in %s. To take its troops, "
        .. "order merge_armies %s into %s once he is outside (the garrison marches out to join him)",
        who, tostring(town.localizedName or town.name), "garrison:" .. tostring(town.name), who)
end

function handlers.march_on(fac, o, _, map, campaign)
    local st, leader = land_general(fac, o.army)
    if not st then return leader end  -- on failure the second value is the reason
    local s = map:getSettlement(o.target_settlement)
    if not s then return "unknown settlement '" .. tostring(o.target_settlement) .. "'" end
    -- live (run8, turn 1): Rufus marched on rebel York from the next tile; the move onto a town
    -- it doesn't hold went nowhere and came back "done". From the next tile, a player's click on
    -- an enemy town besieges it; a town at peace or allied can't be walked into at all.
    if not owned(fac, s) then
        local okd, dist = pcall(function()
            return math.max(math.abs(leader.xCoord - s.xCoord), math.abs(leader.yCoord - s.yCoord))
        end)
        if okd and dist <= 1 then
            local owner = s.ownerFaction
            local oks, rel = pcall(stance, campaign, fac, owner)
            local hostile = (owner and owner.name == "slave") or (oks and rel == "war")
            local what = string.format("%s is next to %s, %s's settlement", tostring(o.army),
                tostring(s.localizedName or s.name), tostring(owner and owner.name))
            if not hostile then
                return what .. ", not at war with you: an army can't walk in; besiege it (the besiege "
                    .. "order) to attack it, which breaks the " .. (rel == "alliance" and "alliance" or "peace")
            end
            local res = handlers.besiege(fac, { army = o.army, settlement = o.target_settlement }, nil, map)
            if type(res) == "string" then return what .. ": an army can't walk in; " .. res end
            if type(res) == "table" and res.pending then  -- ordered, not yet shown: no "besieging it"
                return { note = what .. ": an army can't walk in, so it was ordered to besiege it; the game "
                    .. "hasn't shown the siege yet: the next report says whether it holds" }
            end
            local note = what .. ": an army can't walk in, so it is besieging it (a besiege order with "
                .. "\"assault\": true storms it)"
            if type(res) == "table" and res.note then note = note .. "; " .. res.note end
            return { note = note }
        end
    end
    local refused = M.into_full_settlement(fac, st, s.xCoord, s.yCoord)
        or M.no_land_path(fac, o.army, leader.xCoord, leader.yCoord, s.xCoord, s.yCoord)
        or M.no_moves_left(leader, "army", s.xCoord, s.yCoord)
    if refused then return refused end
    record_move(fac, mover_id(fac, o.army, leader), "army", leader.xCoord, leader.yCoord, o.target_settlement, "march_on")
    local town, refused = M.walk(fac, leader, s.xCoord, s.yCoord)
    if refused then return refused end
    if town then return { note = left_town_note(leader, town, o.army) } end
end

function handlers.besiege(fac, o, _, map)
    local st, leader = land_general(fac, o.army)
    if not st then return leader end  -- on failure the second value is the reason
    local s = map:getSettlement(o.settlement)
    if not s then return "unknown settlement '" .. tostring(o.settlement) .. "'" end
    if owned(fac, s) then return "cannot besiege own settlement" end
    -- Live (scratch2, turn 6, three crashes in a row): siegeSettlement from 10 and 16 tiles away
    -- crashed the game; from the next tile it works. Farther off, the army marches there as a
    -- player's click would, and the ruler besieges once beside it.
    local okd, dist = pcall(function()
        return math.max(math.abs(leader.xCoord - s.xCoord), math.abs(leader.yCoord - s.yCoord))
    end)
    if not okd then return "can't tell how far " .. tostring(o.army) .. " is from " .. s.name end
    if dist > 1 then
        -- live (run6): an army "marched" toward a settlement across the sea and sat 36 turns
        local refused = M.no_land_path(fac, o.army, leader.xCoord, leader.yCoord, s.xCoord, s.yCoord)
            or M.no_moves_left(leader, "army")
        if refused then return refused end
        record_move(fac, mover_id(fac, o.army, leader), "army", leader.xCoord, leader.yCoord, o.settlement, "besiege")
        local town, refused = M.walk(fac, leader, s.xCoord, s.yCoord)
        if refused then return refused end
        local note = string.format("%s is %d tiles from %s: marching there instead; besiege it from the next tile",
                             tostring(o.army), dist, s.name)
        if town then note = note .. "; " .. left_town_note(leader, town, o.army) end
        return { note = note }
    end
    local assault = o.assault == true
    -- the human slot's siege scroll asks again: autoplay answers it as the ruler ordered
    if assault then M.assault_ordered = ((type(M.assault_ordered) == "number" and M.assault_ordered) or 0) + 1 end
    local advice = M.siege_check(st, s, assault)
    st:siegeSettlement(s, assault)
    if assault then
        if advice then return { note = advice } end
        return
    end
    -- Live (qa-field, 2026-10-30): march_on said "so it is besieging it" and the next report had
    -- no army (it was lost at the end of the turn). The game saying no is a failure with its
    -- reason; a siege the army's siege struct (the field the report reads) already shows is
    -- "besieging". The siege scroll came up 7 s after the call there, so the struct may be set
    -- late: a missing siege alone is never a failure, only a note.
    if advice then
        return string.format("the siege of %s didn't start: %s", s.name, advice)
    end
    local okr, town = pcall(function()
        local sg = st.siege
        local t = sg and sg.besiegedSettlement
        return t and t.name or false
    end)
    if okr and town == s.name then return nil end  -- besieging it
    return { pending = true, note = string.format("siege of %s ordered; the game hasn't shown it yet: the next "
        .. "report says whether it holds", s.name) }
end

function handlers.withdraw(fac, o, _, map)
    local st, leader = land_general(fac, o.army)
    if not st then return leader end  -- on failure the second value is the reason
    local s = map:getSettlement(o.to_settlement)
    if not owned(fac, s) then return "settlement '" .. tostring(o.to_settlement) .. "' not owned" end
    local full = M.into_full_settlement(fac, st, s.xCoord, s.yCoord)
        or M.no_moves_left(leader, "army", s.xCoord, s.yCoord)
    if full then return full end
    record_move(fac, mover_id(fac, o.army, leader), "army", leader.xCoord, leader.yCoord, o.to_settlement, "withdraw")
    local town, refused = M.walk(fac, leader, s.xCoord, s.yCoord)
    if refused then return refused end
    if town then return { note = left_town_note(leader, town, o.army) } end
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
    local builds = {}
    for _, opt in ipairs(construction_options(s)) do
        if opt.type ~= K.REPAIR_TYPE then builds[#builds + 1] = opt end
    end
    return queue(fac, s, builds, o.building, "build")
end

function handlers.repair(fac, o, _, map)
    local s, err = own_settlement(fac, map, o.settlement)
    if not s then return err end
    local okq, queued = pcall(queue_of, s)
    for _, name in ipairs(okq and queued or {}) do
        if name == o.building then return "'" .. name .. "' is already in " .. s.name .. "'s queue" end
    end
    for _, opt in ipairs(construction_options(s)) do
        if opt.type == K.REPAIR_TYPE and opt.name == o.building then
            if fac.money < opt.cost then return "treasury too low (" .. fac.money .. ", needs " .. opt.cost .. ")" end
            local before = fac.money
            local ok = false
            pcall(function() ok = opt.opt:addBuildingToQueue() end)
            log(string.format("%s repair %s in %s: treasury %d -> %d", fac.name, o.building, s.name, before, fac.money))
            if not ok then return "the game refused to queue '" .. o.building .. "' (queue full?)" end
            return nil
        end
    end
    return s.name .. " can't repair '" .. tostring(o.building) .. "' (not damaged)"
end

-- The game's recruitment queue: at most 9 waiting, and a settlement trains as many at once as
-- its training slots (live, the Retrain tab: Nottingham, a minor city, 2; London, a large city,
-- 3; the rest of the table is inferred). A recruit beyond the slots waits its turn.
K.QUEUE_MAX = 9

local function training_slots(s)
    local okl, level = pcall(function() return s.level end)
    return math.max(1, (okl and type(level) == "number" and level or 3) - 1)
end

-- how many recruits (units, agents, retrains) s already has in training, and the turn a new one
-- taking `turns` would be ready; nil and a reason when the queue is full
local function queue_place(list, fac, s, turns, now)
    local queued = 0
    for _, t in ipairs(list) do
        if t.faction == fac.name and t.settlement == s.name then queued = queued + 1 end
    end
    if queued >= K.QUEUE_MAX then return nil, s.name .. "'s recruitment queue is full (" .. K.QUEUE_MAX .. " waiting)" end
    return now + math.max(1, turns or 1) + math.floor(queued / training_slots(s))
end

-- Recruit like the game does: pay the unit's cost, take one from the settlement's pool, and the
-- unit joins the garrison when its training time is up (at the faction's turn start), later
-- when the settlement's training slots are taken.
function handlers.recruit(fac, o, _, map, campaign)
    local s, err = own_settlement(fac, map, o.settlement)
    if not s then return err end
    local options = recruitment_options(s)
    for _, r in ipairs(options) do
        if r.name == o.unit then
            if fac.money < r.cost then return "treasury too low (" .. fac.money .. ", needs " .. r.cost .. ")" end
            local list = read_training()
            local ready, full = queue_place(list, fac, s, r.turns, campaign.turnNumber)
            if not ready then return full end
            fac.money = fac.money - r.cost
            r.pool.availablePool = r.pool.availablePool - 1
            list[#list + 1] = { faction = fac.name, settlement = s.name, edu = r.edu, unit = r.name, ready = ready }
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

function handlers.recruit_agent(fac, o, _, map, campaign)
    local s, err = own_settlement(fac, map, o.settlement)
    if not s then return err end
    local a = K.AGENT_RECRUIT[o.agent]
    if not a then return "unknown agent '" .. tostring(o.agent) .. "' (spy, assassin, diplomat, merchant, priest)" end
    local counts = agent_counts(fac)
    local c = counts[o.agent]
    if c.limit and c.have >= c.limit then
        return string.format("%s limit reached: %d of %d (buildings that train them raise it)", o.agent, c.have, c.limit)
    end
    if not can_train_agent(s, fac, o.agent) then return s.name .. " has no building that trains a " .. o.agent end
    if fac.money < a[2] then return "treasury too low (" .. fac.money .. ", needs " .. a[2] .. ")" end
    local list = read_training()  -- written before paying: a failure here costs nothing
    local ready, full = queue_place(list, fac, s, 1, campaign.turnNumber)
    if not ready then return full end
    list[#list + 1] = { faction = fac.name, settlement = s.name, agent = o.agent, unit = o.agent, ready = ready }
    atomic_write(training_path(), encode(list))
    fac.money = fac.money - a[2]
    log(string.format("%s recruits a %s in %s for %d; ready turn %d", fac.name, o.agent, s.name, a[2], list[#list].ready))
end

function handlers.set_tax(fac, o, _, map)
    local s, err = own_settlement(fac, map, o.settlement)
    if not s then return err end
    local level = K.TAX_LEVELS[o.level]
    if level == nil then return "unknown tax level '" .. tostring(o.level) .. "'" end
    s.settlementTaxLevel = level
end

-- Work the game's own screens for what EOP can't do (retraining): a queue of jobs, run a step at
-- a time on the human slot's turn while End Turn waits (see run_ui_job)
local ui_jobs = {}
M.ui_jobs = ui_jobs

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

-- Mercenaries, by the game's rules. A general's army hires from the mercenary pool of the region it
-- stands in (EOP region.mercPool; shared by the pool's regions), not at a settlement. The pool
-- entry says what is in stock and its price; whether this faction may hire it is in the game's
-- descr_mercenaries.txt, which EOP can't read from Lua (mercPoolUnit's religion list, events and
-- crusading flag are not exposed): per unit, a religions list, `crusading` (only an army that has
-- joined a crusade or jihad), start_year / end_year, and `events` (needs a game event fired; not
-- readable, so such entries are never offered). No file, nothing is offered.
function M.merc_rules()
    if M.merc_rules_cache and M.merc_rules_root == root then return M.merc_rules_cache end
    local text
    for _, p in ipairs({ "/../mods/parley/data/world/maps/campaign/imperial_campaign/descr_mercenaries.txt",
                         "/../data/world/maps/campaign/imperial_campaign/descr_mercenaries.txt" }) do
        text = text or read_file(root .. p)
    end
    local pools, pool = {}, nil
    if not text then log("descr_mercenaries.txt not found; no mercenary can be hired") end
    for raw in (text or ""):gmatch("[^\r\n]+") do
        local line = (raw:gsub(";.*", ""))
        local name = line:match("^%s*pool%s+(%S+)")
        if name then
            pool = {}
            pools[name] = pool
        elseif pool then
            local u, cost, rest = line:match("^%s*unit%s+(.-)%s+exp%s+%-?%d+%s+cost%s+(%d+)(.*)$")
            if u then
                local r = { cost = tonumber(cost), crusading = rest:find("crusading", 1, true) ~= nil,
                            events = rest:find("events%s*{") ~= nil,
                            first = tonumber(rest:match("start_year%s+(%d+)")) or 0,
                            last = tonumber(rest:match("end_year%s+(%d+)")) or 0 }
                local rel = rest:match("religions%s*{([^}]*)}")
                if rel then
                    r.religions = {}
                    for w in rel:gmatch("%S+") do r.religions[w:lower()] = true end
                end
                pool[u] = pool[u] or {}
                table.insert(pool[u], r)
            end
        end
    end
    M.merc_rules_cache, M.merc_rules_root = pools, root
    return pools
end

-- { name, cost, exp, left, max, edu, entry } for each mercenary the army (a general's, on land) can
-- hire where it stands: in stock (a whole unit), inside its dates, open to the faction's religion,
-- and crusading-only units only for an army that has joined a crusade or jihad
function M.merc_options(st, fac, campaign)
    local list = {}
    local leader = leader_of(fac, st)
    if not leader or st.isAdmiral then return list end
    local tile = tile_at(leader.xCoord, leader.yCoord)
    local region = tile and gd.stratMap.getRegion(tile.regionID)
    local pool = region and region.mercPool
    if not pool then return list end
    local rules = M.merc_rules()[pool.name] or {}
    local okr, religion = pcall(function() return M2TWEOP.getReligionName(fac.religion) end)
    religion = okr and type(religion) == "string" and religion:lower() or nil
    local crusading = false
    pcall(function() crusading = (leader.crusade or leader.jihad) and true or false end)
    local year = campaign.currentDate or 0
    for i = 0, (pool:getMercUnitNum() or 0) - 1 do
        local mu = pool:getMercUnit(i)
        local e = mu and mu.eduEntry
        if mu and e and e.eduType and (mu.currentPool or 0) >= 1 then
            local rule
            for _, r in ipairs(rules[e.eduType] or {}) do
                if r.cost == mu.cost then rule = rule or r end
            end
            local open = rule and not rule.events
                and not (rule.first > 0 and year < rule.first) and not (rule.last > 0 and year > rule.last)
                and not (rule.religions and not (religion and rule.religions[religion]))
                and not (rule.crusading and not crusading)
            if open then
                list[#list + 1] = { name = e.eduType, cost = mu.cost, exp = mu.experience or 0,
                                    left = math.floor(mu.currentPool), max = mu.maxUnits or 0,
                                    edu = e.index, entry = mu }
            end
        end
    end
    return list
end

function M.add_can_hire(view, st, fac, campaign)
    pcall(function()
        local hire = {}
        for _, m in ipairs(M.merc_options(st, fac, campaign)) do
            hire[#hire + 1] = { unit = m.name, cost = m.cost, available = m.left, max = m.max, exp = m.exp }
        end
        if #hire > 0 then view.can_hire = hire end
    end)
end

-- Hire like the game: a general's army standing in the region whose pool it is. Pay the pool entry's
-- price, take one from the pool, and the unit joins the army when its one turn is up. By direct
-- write like recruit; unverified live (the log gives treasury and pool before and after).
function handlers.hire_mercenary(fac, o, _, map, campaign)
    local st = find_army(fac, o.army)
    if not st then return "unknown army '" .. tostring(o.army) .. "'" end
    if st.isAdmiral then return "'" .. o.army .. "' is a fleet; mercenaries are hired by a land army with a general" end
    local leader = leader_of(fac, st)
    if not leader then return "'" .. o.army .. "' has no general; only an army with a general hires mercenaries" end
    local options = M.merc_options(st, fac, campaign)
    for _, m in ipairs(options) do
        if m.name == o.unit then
            if fac.money < m.cost then return "treasury too low (" .. fac.money .. ", needs " .. m.cost .. ")" end
            local who, list = name_of(leader), read_training()
            local queued = 0
            for _, t in ipairs(list) do
                if t.faction == fac.name and t.army_leader == who then queued = queued + 1 end
            end
            if (st.numOfUnits or 0) + queued >= 20 then return "'" .. o.army .. "' already holds 20 units" end
            local before = m.entry.currentPool
            fac.money = fac.money - m.cost
            m.entry.currentPool = before - 1
            list[#list + 1] = { faction = fac.name, army_leader = who, edu = m.edu, unit = m.name, exp = m.exp,
                                merc = true, ready = campaign.turnNumber + 1 }
            atomic_write(training_path(), encode(list))
            log(string.format("%s: %s hires %s for %d (pool %.2f -> %.2f); joins turn %d", fac.name, who, m.name,
                m.cost, before, m.entry.currentPool, list[#list].ready))
            return nil
        end
    end
    local can = {}
    for _, m in ipairs(options) do can[#can + 1] = m.name end
    return "'" .. o.army .. "' can't hire '" .. tostring(o.unit) .. "' where it stands (its region's pool offers: " ..
        (#can > 0 and table.concat(can, ", ") or "nothing") .. ")"
end

-- tile.isLand is 0 or 1 live, and 0 is truthy in Lua
local function is_land(tile) return tile.isLand == true or tile.isLand == 1 end

-- Ships. There is no boarding call: as with a player's right-click, moving onto a fleet's tile
-- boards it and moving from a ship onto a land tile lands. Untested live: the next report shows
-- whether it worked (an army aboard is listed "aboard <fleet>").
local function own_fleet(fac, id)
    local st = find_army(fac, id)
    if not st then return nil, "unknown fleet '" .. tostring(id) .. "'" end
    local leader = leader_of(fac, st)
    if not st.isAdmiral or not (st.leader or leader) then return nil, "'" .. id .. "' is not a fleet" end
    return st
end

function handlers.board(fac, o)
    local fleet, err = own_fleet(fac, o.fleet)
    if not fleet then return err end
    local fleader = leader_of(fac, fleet) or fleet.leader
    local x, y = fleader and fleader.xCoord, fleader and fleader.yCoord
    local agent
    for _, a in ipairs(agents_of(fac)) do
        if same(a.id, o.who) then agent = a end
    end
    if agent then
        local tired = M.no_moves_left(agent.char, "agent", x, y)
        if tired then return tired end
        record_move(fac, o.who, "agent", agent.char.xCoord, agent.char.yCoord, o.fleet, "board")
        agent.char:moveToTile(x, y)
        return nil
    end
    local st, leader = general(fac, o.who)
    if not st then return leader end
    if fleet.boardedArmy then return "'" .. o.fleet .. "' already carries an army (one per fleet)" end
    local tired = M.no_moves_left(leader, "army", x, y)
    if tired then return tired end
    record_move(fac, mover_id(fac, o.who, leader), "army", leader.xCoord, leader.yCoord, o.fleet, "board")
    -- beside the fleet, in the field: the whole army splits onto the fleet's tile, which embarks it
    -- (EOP factionStruct:splitArmy: "They embark/disembark"). Live bench 10-31 15:18
    -- (board_next_fleet): moveToTile onto the sea tile came back "ok" and the army stayed ashore
    if not M.town_under(fac, leader)
        and math.max(math.abs(math.floor(leader.xCoord) - x), math.abs(math.floor(leader.yCoord) - y)) == 1 then
        local units = {}
        for i = 0, (st.numOfUnits or 0) - 1 do
            local oku, u = pcall(function() return st:getUnit(i) end)
            if oku and u then units[#units + 1] = u end
        end
        local ok, err = pcall(function() fac:splitArmy(units, x, y) end)
        if ok then
            log(string.format("%s: %s embarks on %s at (%d,%d) by a split of its %d units", fac.name,
                tostring(o.who), tostring(o.fleet), x, y, #units))
            return nil
        end
        log(string.format("%s: splitArmy to board %s failed (%s); moveToTile instead", fac.name,
            tostring(o.fleet), tostring(err)))
    end
    local town, refused = M.walk(fac, leader, x, y)
    if refused then return refused end
    if town then return { note = left_town_note(leader, town, o.who) } end
end

-- (handlers.land is below onto_foreign_settlement, which it uses)

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

-- every tile a character stands on (fleets' admirals too), as x * 1000 + y
local function occupied_tiles()
    local taken = {}
    for i = 0, stratmap.game.getFactionsCount() - 1 do
        local f = stratmap.game.getFaction(i)
        for j = 0, (f and f.numOfCharacters or 0) - 1 do
            pcall(function()
                local c = f:getCharacter(j)
                taken[math.floor(c.xCoord) * 1000 + math.floor(c.yCoord)] = true
            end)
        end
    end
    return taken
end

-- the first sea tile near..far tiles (Chebyshev) from (x, y), ring by ring, nobody on it: x, y or nil
local function free_sea_near(x, y, near, far, taken)
    taken = taken or occupied_tiles()
    x, y = math.floor(x), math.floor(y)
    for r = near, far do
        for dx = -r, r do
            for dy = -r, r do
                local tx, ty = x + dx, y + dy
                local t = math.max(math.abs(dx), math.abs(dy)) == r and tile_at(tx, ty)
                if t and not is_land(t) and not taken[tx * 1000 + ty] then return tx, ty end
            end
        end
    end
end

-- a settlement's port (the tile at its region's port entrance holds it, as blockade reads it), and
-- the region; nil for a town without one
local function port_of(s)
    local region = s and gd.stratMap.getRegion(s.regionID)
    local tile = region and tile_at(region.portEntranceXCoord, region.portEntranceYCoord)
    return tile and tile.port, region
end

-- the port's tile (EOP portStruct.xCoord/yCoord, LuaDocs.lua:2806), else the region's port entrance
local function port_xy(port, region)
    local ok, x, y = pcall(function() return port.xCoord, port.yCoord end)
    if ok and type(x) == "number" and type(y) == "number" then return x, y end
    return region.portEntranceXCoord, region.portEntranceYCoord
end

-- a unit definition for a ship (EOP eduEntry.category, unitCategory.ship = 4, LuaDocs.lua:7150)
function M.is_ship(edu)
    local ok, e = pcall(function() return M2TWEOPDU.getEduEntry(edu) end)
    return ok and e ~= nil and e.category == ((unitCategory and unitCategory.ship) or 4)
end

-- A ship trained in a port puts to sea as a fleet of its own, an admiral at its head, on the port's
-- dock or the free sea nearest the port, as the game's own recruited ships appear. Until 10-31 a
-- trained ship was created in the town's land garrison like any other unit. The fleet comes from EOP
-- factionStruct:spawnArmy with characterType.admiral (3), as the QA bench's spawn_fleet: unproven
-- live. Returns the tile it put to sea on.
function M.launch_ship(fac, s, edu)
    local port, region = port_of(s)
    local px, py = s.xCoord, s.yCoord
    if port then
        px, py = port_xy(port, region)
        local okd, dx, dy = pcall(function() return port.dock.xCoord, port.dock.yCoord end)
        if okd and type(dx) == "number" and type(dy) == "number" then px, py = dx, dy end
    end
    local x, y = free_sea_near(px, py, 0, 3)
    if not x then error("no free sea within 3 tiles of " .. tostring(s.name) .. "'s port") end
    M.qa_label_n = (M.qa_label_n or 0) + 1
    local label = string.format("parley_ship_%d_%d", os.time(), M.qa_label_n)
    local ctype = (characterType and characterType.admiral) or 3
    local fleet = fac:spawnArmy("random_name", "", ctype, label, "", x, y, 30, false, 31, edu, 0, 0, 0)
    if not fleet then error("spawnArmy returned nil") end
    return x, y
end

-- a general or admiral of this faction by his own name, leading an army or not (live: four generals stood
-- in Dublin's garrison, none leading it, and the ruler could not move one out alone)
local function general_named(fac, name)
    for i = 0, (fac.numOfCharacters or 0) - 1 do
        local ok, c = pcall(function()
            local c = fac:getCharacter(i)
            local t = c and c:getTypeName()
            if (t == "general" or t == "named_character" or t == "named character" or t == "admiral")
                and (same(name_of(c), name) or same_army_id(name_of(c), name)) then return c end
        end)
        if ok and c then return c end
    end
end

local function own_fleet_at(fac, x, y)
    for i = 0, (fac.stacksNum or 0) - 1 do
        local st = fac:getStack(i)
        if st and st.isAdmiral then
            local leader = leader_of(fac, st)
            if leader and leader.xCoord == x and leader.yCoord == y then return true end
        end
    end
end

-- the land (or, with sea = true, the sea) tile nearest (x, y), within a few tiles, or nil
local function nearest_land(x, y, sea)
    for r = 1, 3 do
        for dx = -r, r do
            for dy = -r, r do
                if math.max(math.abs(dx), math.abs(dy)) == r then
                    local t = tile_at(x + dx, y + dy)
                    if t and is_land(t) ~= (sea == true) then return x + dx, y + dy end
                end
            end
        end
    end
end

-- whether (tx, ty) can be walked to from (sx, sy) over land and strait crossings. Live
-- (2026-10-29): a diplomat in England was sent to France; moveToTile did nothing and the order
-- came back "done". A landmass found whole is kept: the next order from it is answered at once.
local landmass = {}  -- x * 1000 + y -> the landmass's id, for landmasses explored to the end
local function land_reach(sx, sy, tx, ty)
    local function key(x, y) return x * 1000 + y end
    local known = landmass[key(sx, sy)]
    if known then return landmass[key(tx, ty)] == known end
    local seen, queue, head = { [key(sx, sy)] = true }, { key(sx, sy) }, 1
    local function add(x, y)
        local k = key(x, y)
        if seen[k] then return false end
        local t = tile_at(x, y)
        if not (t and is_land(t)) then return false end
        seen[k], queue[#queue + 1] = true, k
        return true
    end
    local grew = true
    while grew do
        while head <= #queue do
            local k = queue[head]
            head = head + 1
            local x, y = math.floor(k / 1000), k % 1000
            if x == tx and y == ty then return true end
            for dx = -1, 1 do
                for dy = -1, 1 do add(x + dx, y + dy) end
            end
        end
        -- a strait joins the land on each side: carry on from the far shore of one that touches
        grew = false
        for _, c in ipairs(all_crossings()) do
            local touches = false
            for _, s in ipairs(c.shores or {}) do
                if seen[key(s.x, s.y)] then touches = true end
            end
            if touches then
                for _, s in ipairs(c.shores or {}) do
                    if add(s.x, s.y) then grew = true end
                end
            end
        end
    end
    for k in pairs(seen) do landmass[k] = key(sx, sy) end
    return false
end
M.land_reach = land_reach  -- for checks from control.txt: lua return package.loaded.parley_bridge.land_reach(...)

-- the ruler's fleet nearest (x, y): its admiral's name, where it is and how far, or nil
local function nearest_fleet(fac, x, y)
    local best
    for i = 0, (fac.stacksNum or 0) - 1 do
        pcall(function()
            local st = fac:getStack(i)
            if not (st and st.isAdmiral) then return end
            local l = leader_of(fac, st)
            local name = l and name_of(l)
            if not (name and l.xCoord) then return end
            local d = math.max(math.abs(l.xCoord - x), math.abs(l.yCoord - y))
            if not best or d < best.d then best = { name = name, x = l.xCoord, y = l.yCoord, d = d } end
        end)
    end
    return best
end

-- the refusal for a land move with no way there, or nil. It carries the board order ready to
-- copy (live, 2026-10-29: Heretic was told "board a fleet first" five turns running and never
-- wrote one; a weak model copies an order more readily than it composes one).
local function no_land_path(fac, who, sx, sy, x, y)
    local from, to = tile_at(sx, sy), tile_at(x, y)
    if not (from and is_land(from) and to and is_land(to)) then return nil end  -- aboard, or boarding
    local ok, reach = pcall(land_reach, math.floor(sx), math.floor(sy), x, y)
    if ok and reach == false then
        local text = string.format("(%d,%d) can't be reached over land from (%d,%d): it's across the sea", x, y, sx, sy)
        local f = fac and nearest_fleet(fac, sx, sy)
        if f then
            return text .. string.format("; board a fleet first, then land on the far shore: "
                .. "{\"type\": \"board\", \"who\": \"%s\", \"fleet\": \"%s\"} (%s is at (%d,%d), %d tiles away)",
                tostring(who), f.name, f.name, f.x, f.y, f.d)
        end
        return text .. "; you have no fleet to carry it: recruit a ship (a cog) in a port first"
    end
end
M.no_land_path = no_land_path  -- besiege (defined earlier in the file) and the agent walks use it

-- Marks each view in list (foreign settlements) by_land = true/false: whether any of the
-- faction's land armies can walk there. land_reach keeps every landmass it explores to the end,
-- so the unreachable checks are one flood fill per landmass, and a reachable one stops early.
function M.mark_by_land(fac, list)
    local origins, seen = {}, {}
    for i = 0, (fac.stacksNum or 0) - 1 do
        pcall(function()
            local st = fac:getStack(i)
            if not st or st.isAdmiral then return end
            local l = leader_of(fac, st)
            if not (l and l.xCoord) then return end
            local x, y = math.floor(l.xCoord), math.floor(l.yCoord)
            local t = tile_at(x, y)
            if t and is_land(t) and not seen[x * 1000 + y] then
                seen[x * 1000 + y] = true
                origins[#origins + 1] = { x, y }
            end
        end)
    end
    if #origins == 0 then return end
    for _, v in ipairs(list) do
        pcall(function()
            local to = v.x and tile_at(v.x, v.y)
            if not (to and is_land(to)) then return end
            local reach = false
            for _, o in ipairs(origins) do
                local ok, r = pcall(land_reach, o[1], o[2], v.x, v.y)
                if not ok or r ~= false then reach = true break end
            end
            v.by_land = reach
        end)
    end
end

-- the refusal for a plain move onto another faction's settlement, or nil. Live (2026-10-29, the
-- turn audit): 15 such moves came back "done" while the mover stayed put; the game won't walk
-- anyone into a settlement that isn't theirs.
local function onto_foreign_settlement(fac, x, y, agent)
    local map = gd.stratMap
    for r = 0, (map.regionsNum or 0) - 1 do
        local ok, s = pcall(function() return map.getRegion(r).settlement end)
        if ok and s and s.xCoord == x and s.yCoord == y and s.ownerFaction and s.ownerFaction.name ~= fac.name then
            local what = string.format("(%d,%d) is %s, %s's settlement", x, y,
                tostring(s.localizedName or s.name), tostring(s.ownerFaction.name))
            if agent then
                return what .. ": an agent can't walk in; act on it from outside with the agent's own order "
                    .. "(spy, assassinate, sabotage, bribe), which walks there and acts from the next tile"
            end
            return what .. ": an army can't walk in; besiege it (the besiege order, \"assault\": true to storm it)"
        end
    end
end

-- Landing onto another faction's town is refused like a walk into one (the game won't take an army
-- in; a land order onto a town came back "done" with nobody moving, as the 10-29 turn audit found
-- for 15 moves). The besiege advice holds for a landed army: land beside it first.
function handlers.land(fac, o)
    local st = find_army(fac, o.army)
    if not st then return "unknown army '" .. tostring(o.army) .. "'" end
    if not st.shipArmy then return "'" .. o.army .. "' is not aboard a fleet" end
    local leader = leader_of(fac, st)
    if not leader then return "'" .. o.army .. "' has no general to lead it ashore" end
    local tile = tile_at(o.x, o.y)
    if not tile then return "(" .. tostring(o.x) .. "," .. tostring(o.y) .. ") is off the map" end
    if not is_land(tile) then return "(" .. o.x .. "," .. o.y .. ") is not land; land on a tile next to the fleet" end
    local foreign = onto_foreign_settlement(fac, math.floor(o.x), math.floor(o.y))
    if foreign then return foreign .. ", from a tile beside it once landed" end
    local tired = M.no_moves_left(leader, "army", o.x, o.y)
    if tired then return tired end
    record_move(fac, o.army, "army", leader.xCoord, leader.yCoord, string.format("(%d,%d)", math.floor(o.x), math.floor(o.y)), "land")
    -- the whole army splits ashore (EOP factionStruct:splitArmy disembarks). Live 10-31 18:30:
    -- moveToTile landed the general with his bodyguard only; two of three units stayed aboard
    local units = {}
    for i = 0, (st.numOfUnits or 0) - 1 do
        local oku, u = pcall(function() return st:getUnit(i) end)
        if oku and u then units[#units + 1] = u end
    end
    local ok, err = pcall(function() fac:splitArmy(units, math.floor(o.x), math.floor(o.y)) end)
    if ok then
        log(string.format("%s: %s lands at (%d,%d) by a split of its %d units", fac.name, tostring(o.army),
            math.floor(o.x), math.floor(o.y), #units))
        return nil
    end
    log(string.format("%s: splitArmy to land %s failed (%s); moveToTile instead", fac.name, tostring(o.army), tostring(err)))
    leader:moveToTile(math.floor(o.x), math.floor(o.y))
end

-- the refusal for an army entering the ruler's own settlement at (x, y) when the two together
-- pass 20 units, or nil. Live (2026-10-29, the turn audit): Henry (8 units) moved onto Edinburgh
-- (garrison 15), came back "done" and stayed outside. On M: march_on and withdraw come earlier.
function M.into_full_settlement(fac, st, x, y)
    for i = 0, (fac.settlementsNum or 0) - 1 do
        local ok, s = pcall(function() return fac:getSettlement(i) end)
        if ok and s and s.xCoord == x and s.yCoord == y then
            local inside = (s.army and s.army.numOfUnits) or 0
            local coming = (st and st.numOfUnits) or 0
            if inside + coming > 20 then
                return string.format("%s's garrison has %d units and this army %d: %d, over the 20 a "
                    .. "settlement holds, so it would stay outside. Disband or leave units out first, or "
                    .. "merge_units to fold worn ones", tostring(s.localizedName or s.name), inside, coming,
                    inside + coming)
            end
            return nil
        end
    end
end

function handlers.move_army(fac, o)
    local st, leader = general(fac, o.army)
    if not st then
        local c = general_named(fac, o.army)
        if not c then return leader end  -- on failure the second value is the reason
        local okl, led = pcall(function() return c.armyLeaded end)
        st, leader = (okl and led) or { isAdmiral = (c:getTypeName() == "admiral") }, c
    end
    if type(o.x) ~= "number" or type(o.y) ~= "number" then return "move_army needs x and y" end
    local x, y, map = math.floor(o.x), math.floor(o.y), gd.stratMap
    if not (map.mapWidth and map.mapHeight and x >= 0 and y >= 0 and x < map.mapWidth and y < map.mapHeight) then
        return "(" .. x .. "," .. y .. ") is off the map"
    end
    local tile = tile_at(x, y)
    if st.isAdmiral then
        if tile and is_land(tile) then  -- live, turns 32-34: three guesses at one coast
            local sx, sy = nearest_land(x, y, true)
            return "a fleet can't sail onto land (" .. x .. "," .. y .. ")"
                .. (sx and ("; the nearest sea is (" .. sx .. "," .. sy .. ")") or "")
        end
    elseif tile and not is_land(tile) and not own_fleet_at(fac, x, y) then
        -- live: an order to sea came back "done" and the army never moved
        local lx, ly = nearest_land(x, y)
        return "(" .. x .. "," .. y .. ") is sea" .. (lx and ("; the nearest land is (" .. lx .. "," .. ly .. ")") or "")
    end
    if not st.isAdmiral then
        local refused = onto_foreign_settlement(fac, x, y) or M.into_full_settlement(fac, st, x, y)
            or no_land_path(fac, o.army, leader.xCoord, leader.yCoord, x, y)
        if refused then return refused end
    end
    local tired = M.no_moves_left(leader, st.isAdmiral and "fleet" or "army", x, y)
    if tired then return tired end
    -- a garrison's move is its general's: he is the one the move check must follow
    local gtown = tostring(o.army):match("^garrison:(.+)$")
    local who = (gtown and name_of(leader)) or mover_id(fac, o.army, leader)
    record_move(fac, who, "army", leader.xCoord, leader.yCoord, string.format("(%d,%d)", x, y), "move_army")
    if st.isAdmiral then
        leader:moveToTile(x, y)
        return
    end
    -- a general in a town goes out by a split (M.walk); the garrison stays (live 2026-10-29, York:
    -- the ruler thought the garrison had marched)
    local town, refused = M.walk(fac, leader, x, y)
    if refused then return refused end
    if town then return { note = left_town_note(leader, town, o.army) } end
    if gtown and who then
        return { note = string.format("only %s and his bodyguard march out; the garrison stays in %s. To take "
            .. "its troops, order merge_armies %s into %s once he is outside (the garrison marches out to join him)",
            who, gtown, tostring(o.army), who) }
    end
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
    if moved == 0 then
        -- live: "england merge_units garrison:Edinburgh: 0 soldiers moved, 0 units disbanded"
        -- four turns running, each result "done", and the ruler kept ordering it
        return string.format("nothing to merge in %s: no two worn units of one type that can combine", o.army)
    end
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

local function stack_pos(fac, st)
    local x, y = residence(st)
    if not x then
        local leader = leader_of(fac, st)
        if leader then x, y = leader.xCoord, leader.yCoord end
    end
    return x or st.xCoord, y or st.yCoord
end

-- One of your armies (a garrison too) joins another. EOP's mergeArmies checks nothing in C++, so
-- both stacks are looked up now, at turn start: an army that died since the report is refused,
-- never passed on. Live (turns 179 and 180): garrison:York (18 units) into Augustine Maitland (1
-- unit, on the tile beside York) called mergeArmies(into, false), which opened exchange_scroll
-- instead of moving a man and reported "done" twice. Same or adjacent tiles (Chebyshev <= 1) now
-- merge instantly with force=true and check that into.numOfUnits grew; distant stacks walk with
-- force=false (results have only ok/reason, no note field, so a walk logs and returns nil).
-- Live (scratch2, turn 2): besiege York with Captain Ralph, then merge Rufus into him in the same
-- turn, and the game crashed after the orders: a stack mid-siege or mid-move is never merged.
local ordered = {}  -- armies given a move, march or siege order this turn (reset per orders file)

local function in_siege(st)
    local ok, s = pcall(function() return st.siege end)
    return ok and s ~= nil
end

function handlers.merge_armies(fac, o)
    local st, into = find_army(fac, o.army), find_army(fac, o.into)
    if not st then return "unknown army '" .. tostring(o.army) .. "'" end
    if not into then return "unknown army '" .. tostring(o.into) .. "'" end
    if st == into then return "an army can't merge into itself" end
    if (st.isAdmiral and true or false) ~= (into.isAdmiral and true or false) then
        return "a fleet and a land army can't merge"
    end
    if st.shipArmy or into.shipArmy then return "an army aboard a fleet can't merge; land it first" end
    for _, id in ipairs({ o.army, o.into }) do
        if ordered[id] then return "'" .. id .. "' already moved or besieged this turn; merge next turn" end
    end
    if in_siege(st) or in_siege(into) then
        return "a stack in a siege can't merge; lift the siege first or merge after it ends"
    end
    local moved, before = st.numOfUnits or 0, into.numOfUnits or 0
    local total = moved + before
    if total > 20 then return "together they'd be " .. total .. " units; an army holds at most 20" end
    local ax, ay = stack_pos(fac, st)
    local bx, by = stack_pos(fac, into)
    local dist = (ax and ay and bx and by) and math.max(math.abs(ax - bx), math.abs(ay - by)) or nil
    local instant = dist ~= nil and dist <= 1
    if not instant then
        -- the walk is the moving stack's own: its leader (a garrison has none; a captain leads it out)
        local okl, walker = pcall(function() return st.leader end)
        local tired = okl and M.no_moves_left(walker, "army")
        if tired then return tired end
    end
    local ok = pcall(function() st:mergeArmies(into, instant) end)
    local okn, after = pcall(function() return into.numOfUnits end)
    after = (okn and type(after) == "number") and after or before
    if instant or not ok then
        if not ok or after < total then
            return "the merge didn't take: " .. tostring(o.into) .. " still has " .. after .. " units"
        end
        return nil
    end
    if after < total then
        log(string.format("merge_armies: %s is walking to join %s (%s tiles); it merges when it arrives",
            tostring(o.army), tostring(o.into), tostring(dist and math.floor(dist) or "?")))
        local town = tostring(o.army):match("^garrison:(.+)$")
        if town then  -- live, turn 12: Edinburgh's garrison left under a new captain, the town empty
            return { note = string.format("%s is %s tiles from %s: the garrison marches out of %s under a captain "
                .. "to join it and merges when it arrives; %s is left without a garrison until then",
                tostring(o.army), tostring(dist and math.floor(dist) or "?"), tostring(o.into), town, town) }
        end
    end
    return nil
end

local function own_agent(fac, id)
    for _, a in ipairs(agents_of(fac)) do
        if same(a.id, id) then return a end
    end
end

-- the refusal for an agent order naming no agent of the faction's. One of its own generals is told
-- apart (live 2026-10-29, turn 138: France moved its generals by move_agent and was told "not one
-- of yours"), with the move_army to copy for a move. Starts "unknown agent '<name>'" either way,
-- as parley/audit.py reads it (a ruler's mistake when the name is one of his own).
K.AGENT_FOR = { marry = "princess" }
local function unknown_agent(fac, o)
    local name = tostring(o.agent)
    local okg, g = pcall(general_named, fac, o.agent)
    if not (okg and g) then return "unknown agent '" .. name .. "' (not one of yours)" end
    local text = string.format("unknown agent '%s': %s is one of your generals, not an agent", name, name)
    if o.type == "move_agent" and type(o.x) == "number" and type(o.y) == "number" then
        return text .. string.format("; move his army with {\"type\": \"move_army\", \"army\": \"%s\", \"x\": %d, \"y\": %d}",
            name, math.floor(o.x), math.floor(o.y))
    end
    local need = K.AGENT_KIND[o.type] or K.AGENT_FOR[o.type]
    if need then return text .. string.format("; a %s order is for a %s of yours", tostring(o.type), need) end
    return text
end

function handlers.move_agent(fac, o)
    local a = own_agent(fac, o.agent)
    if not a then return unknown_agent(fac, o) end
    if type(o.x) ~= "number" or type(o.y) ~= "number" then return "move_agent needs x and y" end
    local x, y, map = math.floor(o.x), math.floor(o.y), gd.stratMap
    if not (map.mapWidth and map.mapHeight and x >= 0 and y >= 0 and x < map.mapWidth and y < map.mapHeight) then
        return "(" .. x .. "," .. y .. ") is off the map"
    end
    local tile = tile_at(x, y)
    if tile and not is_land(tile) and not own_fleet_at(fac, x, y) then
        -- live: an agent sent to sea came back "done" and never moved, as armies once did
        local lx, ly = nearest_land(x, y)
        return "(" .. x .. "," .. y .. ") is sea" .. (lx and ("; the nearest land is (" .. lx .. "," .. ly .. ")") or "")
    end
    local refused = onto_foreign_settlement(fac, x, y, true) or no_land_path(fac, o.agent, a.char.xCoord, a.char.yCoord, x, y)
        or M.no_moves_left(a.char, "agent", x, y)
    if refused then return refused end
    record_move(fac, o.agent, "agent", a.char.xCoord, a.char.yCoord, string.format("(%d,%d)", x, y), "move_agent")
    a.char:moveToTile(x, y)
end

-- run at the faction's next turn start: at its turn end a move just ordered hasn't landed yet
-- (live: a diplomat sat on his old tile at England's turn end and stood on his target in France's
-- report a minute later). Moves points are full again by then, so none are reported.
check_moves_not_made = function(fac)
    local unmade = {}
    local recorded = recorded_moves[fac.name] or {}
    for _, m in ipairs(recorded) do
        local cur_x, cur_y
        if m.kind == "agent" then
            local a = own_agent(fac, m.id)
            if a and a.char then cur_x, cur_y = a.char.xCoord, a.char.yCoord end
        else
            local st, leader = general(fac, m.id)
            if not st then
                local c = general_named(fac, m.id)
                if c then
                    local okl, led = pcall(function() return c.armyLeaded end)
                    st, leader = (okl and led) or { isAdmiral = (c:getTypeName() == "admiral") }, c
                end
            end
            if not st then st = find_army(fac, m.id) end
            if st then cur_x, cur_y = stack_pos(fac, st) end
        end
        if cur_x and cur_y and cur_x == m.from_x and cur_y == m.from_y then
            local item = {
                id = m.id,
                from_x = m.from_x,
                from_y = m.from_y,
                target = tostring(m.target),
                order_type = m.order_type,
            }
            unmade[#unmade + 1] = item
            local verb = (m.order_type == "march_on" or m.order_type == "besiege") and "march"
                or (m.order_type == "withdraw" and "withdrawal" or "move")
            log(string.format("%s: %s's %s to %s did not happen: still at (%d,%d)",
                fac.name, m.id, verb, tostring(m.target), m.from_x, m.from_y))
        end
    end
    unmade_moves[fac.name] = unmade
end

-- a princess offers marriage to a foreign general in sight (EOP's marry checks its arguments)
function handlers.marry(fac, o)
    local a = own_agent(fac, o.agent)
    if not a then return unknown_agent(fac, o) end
    if a.kind ~= "princess" then return "'" .. a.id .. "' is a " .. a.kind .. "; only a princess can marry" end
    for _, e in ipairs(M.sight(fac).armies) do
        if same(e.view.id, o.target) then
            a.char:marry(e.char)
            M.note_proposal(fac.name, a.id, e.view.id)
            return nil
        end
    end
    return "target '" .. tostring(o.target) .. "' is not in sight"
end

local busy = {}  -- agents given an order this turn (reset per orders file); one action each

-- Agent orders: your own agent of the right kind, against a target in sight right now.
-- EOP's agent actions return nothing, so "done" means issued; the next report shows the outcome.
local function agent_order(fac, o)
    local need = K.AGENT_KIND[o.type]
    local agent
    for _, a in ipairs(agents_of(fac)) do
        if same(a.id, o.agent) then agent = a end
    end
    if not agent then return nil, unknown_agent(fac, o) end
    if agent.kind ~= need then
        local function a(word) return (tostring(word):match("^[aeiou]") and "an " or "a ") .. tostring(word) end
        return nil, "'" .. agent.id .. "' is " .. a(agent.kind) .. ", not " .. a(need)
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

-- EOP's agent actions check no range, and the engine doesn't either. Live (scratch2, turn 6,
-- two crashes): a spy already inside Caernarvon (on its tile) was ordered to spy on it, and the
-- game died right after the mission. So an agent acts only from the next tile, as the game's own
-- click does; farther off it walks there, and one already inside the target is refused.
local function in_range(fac, o, agent, target)
    local ok, dist = pcall(function()
        return math.max(math.abs(agent.xCoord - target.xCoord), math.abs(agent.yCoord - target.yCoord))
    end)
    if not ok then return false, "can't tell how far '" .. tostring(o.agent) .. "' is from the target" end
    local what = tostring(o.type == "sabotage" and o.settlement or o.target)
    if dist == 0 then return false, "'" .. tostring(o.agent) .. "' is already inside " .. what end
    if dist > 1 then
        local refused = no_land_path(fac, o.agent, agent.xCoord, agent.yCoord, target.xCoord, target.yCoord)
            or M.no_moves_left(agent, "agent")
        if refused then return false, refused end
        record_move(fac, o.agent, "agent", agent.xCoord, agent.yCoord, what, o.type)
        agent:moveToTile(target.xCoord, target.yCoord)
        return false, { note = string.format("'%s' is %d tiles from %s: walking there instead; act from the next tile",
                                    tostring(o.agent), dist, what) }
    end
    return true
end

local function agent_handler(on_char, on_sett)
    return function(fac, o)
        local agent, char, sett = agent_order(fac, o)
        if not agent then return char end  -- char holds the reason
        busy[o.agent] = true
        local near, why = in_range(fac, o, agent, sett or char)
        if not near then return why end
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
    local area = K.ORDER_AREA[o.type]
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
    if M.frozen_turn and M.frozen_turn.fac == fac then M.frozen_turn = nil end
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
    unmade_moves[fac.name] = nil  -- reported once
end

K.MOVES_OR_ATTACKS = {
    march_on = true,
    besiege = true,
    withdraw = true,
    move_army = true,
    attack = true,
    board = true,
    land = true,
    merge_armies = true,
}

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
    -- where the ruler's report put each army: a captain is renamed by the time its orders run, so
    -- an id not found now is matched by its tile (find_army). Read from the report on disk, the one
    -- the ruler read, so it holds across a bridge reload or a relaunch
    pcall(function()
        local seen = json.decode(read_file(dir .. "/state.json") or "")
        local at = {}
        for _, a in ipairs(seen and seen.armies or {}) do
            if a.id and a.x then at[a.id] = { x = a.x, y = a.y } end
        end
        M.reported_at = M.reported_at or {}
        M.reported_at[fac.name] = at
    end)
    M.found_this_turn = M.found_this_turn or {}
    M.found_this_turn[fac.name] = {}  -- armies found by this turn's orders (find_army)
    local results = {}
    busy, ordered = {}, {}
    recorded_moves[fac.name] = {}  -- last turn's were checked at this turn's start
    for i, o in ipairs(orders.orders) do
        local ok, res = pcall(apply, fac, o, cfg)
        local err, note
        if not ok then
            err = "error: " .. tostring(res)
        elseif type(res) == "table" and res.note then
            note = tostring(res.note)
        elseif res ~= nil then
            err = tostring(res)
        end
        local success = (err == nil)
        local aid = o.army or (o.type == "board" and o.who)
        if success and type(aid) == "string" and K.MOVES_OR_ATTACKS[o.type] then
            ordered[aid] = true
        end
        if not success and recorded_moves[fac.name] and #recorded_moves[fac.name] > 0 then
            local last_rec = recorded_moves[fac.name][#recorded_moves[fac.name]]
            if last_rec.id == tostring(aid or o.agent or "") then
                table.remove(recorded_moves[fac.name])
            end
        end
        local r_entry = { index = i - 1, type = tostring(o.type), ok = success,
                          reason = err or "" }
        if note then r_entry.note = note end
        results[#results + 1] = r_entry
        log(string.format("%s order %d %s: %s", fac.name, i - 1, tostring(o.type), err or (note and ("done: " .. note) or "done")))
    end
    atomic_write(dir .. "/results.json", encode(results))
    return true
end

function M.on_turn_start(fac)
    local cfg = config()
    if not cfg then return end
    -- QA bench quiet world (freeze=*): the runner makes the Pope young after each bench load, but a
    -- turn case plays rounds and he ages a year each; keep him young at the player's turn start
    if cfg.freeze["*"] and fac.isPlayerControlled == 1 and M.qa then M.qa.quiet() end
    -- QA bench: movers it keeps without moves, a seatless faction's too (the covert case's rebel
    -- victim, live 10-30 21:38: the rebel army beside the assassin was gone a turn later)
    if M.qa then pcall(M.qa.tire_due, fac) end
    if M.qa then pcall(M.qa.court_due, fac) end  -- the diplomacy suite's AI envoy, on its own turn
    -- an AI faction's game AI frozen or not, as the config says, every turn (a save may not keep
    -- it): a seat's with freeze=<faction>, and every AI faction's with freeze=* (the QA bench's
    -- quiet world) unless thaw=<faction>. Any other is unfrozen, so a world the bench froze
    -- thaws again under the real config. One field read per faction turn start.
    if fac.isPlayerControlled ~= 1 then
        local frozen = cfg.freeze[fac.name] or (cfg.freeze["*"] and not cfg.thaw[fac.name])
        local want = frozen and 1 or 0
        pcall(function()
            if fac.freezeFactionAI ~= want then
                fac.freezeFactionAI = want
                log(fac.name .. ": game AI " .. (want == 1 and "frozen" or "unfrozen"))
            end
        end)
        M.frozen_turn = want == 1 and { fac = fac, since = M.clock() } or nil
    end
    if not cfg.factions[fac.name] then return end
    local turn = gd.campaignStruct.turnNumber
    -- the orchestrator makes turn folders from this (Lua can't create directories)
    atomic_write(root .. "/heartbeat.txt", "turn=" .. turn .. "\n")
    -- playtest funds: top up treasury if below target at turn start (testing switch)
    local target = cfg.playtest_funds and cfg.playtest_funds[fac.name] or 0
    if target > 0 and fac.money < target then
        local old = fac.money
        local ok, err = pcall(function() fac.money = target end)
        if not ok then
            log(string.format("playtest funds: %s top-up failed (%s)", fac.name, tostring(err)))
        elseif fac.money ~= target then
            log(string.format("playtest funds: %s top-up failed (money still %s)", fac.name, tostring(fac.money)))
        else
            log(string.format("playtest funds: %s topped up %d -> %d", fac.name, old, fac.money))
        end
    end
    deliver_training(fac, turn)
    -- last turn's moves have landed by now: the ones that didn't go in this turn's report
    if recorded_moves[fac.name] then
        local ok, err = pcall(check_moves_not_made, fac)
        if not ok then log(fac.name .. ": move check failed: " .. tostring(err)) end
        recorded_moves[fac.name] = nil
    end
    -- under autoplay the human's turn waits for its ruler, if it played last turn
    local waits = cfg.autoplay and fac.isPlayerControlled == 1
        and exists(turn_dir(cfg, turn - 1, fac.name) .. "/state.json")
    if cfg.autoplay and fac.isPlayerControlled == 1 then
        M.autoplay_turn_started(turn)
        M.set_governors(fac, areas_of(cfg, fac.name))
        M.follow(fac)
    end
    ordered = {}
    if apply_orders(fac, cfg, turn, not waits) then pcall(M.keep_sieges, fac) end
end

-- EOP's siegeSettlement(town, false) on the town an army already besieges asks the game AI which
-- siege equipment to build and queues it (character.cpp siegeSettlement, the "maintain" path).
-- An army the ruler left besieging, with no move or assault order this turn, gets that call once.
function M.keep_sieges(fac)
    local ids = army_ids(fac)
    for i = 0, fac.stacksNum - 1 do
        pcall(function()
            local st = fac:getStack(i)
            local sg = st.siege
            local town = sg and sg.besiegedSettlement
            if not town then return end
            local id = ids[i]
            local lname = st.leader and name_of(st.leader)
            if ordered[id] or (lname and ordered[lname]) then return end
            st:siegeSettlement(town, false)
            log(string.format("%s: %s keeps the siege of %s; siege equipment queued", fac.name,
                tostring(id or lname), tostring(town.name)))
        end)
    end
end

-- The human's slot has no AI: whatever its ruler doesn't run, the settlement governors do.
-- (EOP exposes construction and recruitment auto-manage, not taxes.)
function M.set_governors(fac, areas)
    for i = 0, fac.settlementsNum - 1 do
        pcall(function()
            local pc = fac:getSettlement(i).aiProductionController
            if not pc then return end
            -- booleans (EOP LuaDocs aiProductionController): 0/1 were written before and live the
            -- flags still read true under full control (bench 10-31, governors_off_under_full_control)
            pc.isAutoManagedConstruction = not areas.build
            pc.isAutoManagedRecruitment = not areas.recruit
            -- the master switch too (unverified whether the sub-flags alone turn a governor on)
            pc.isAutoManaged = not (areas.build and areas.recruit)
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
K.STUCK_AFTER = 20  -- seconds after End Turn with the human's turn still showing (the author: stuck takes too long)

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

-- press a named button through the game's own button call (EOP uiElementStruct:execute), no mouse
-- (Track A, no clicks); the scripted mouse click only when the element isn't on screen to execute,
-- or when scripted is set. Never both: one press each. (No helper local for the scripted click:
-- the main chunk is at Lua's 200-local limit; live, one more stopped the bridge loading.)
local function click(element, scripted)
    -- the battle panel's auto-resolve stays on the scripted click: live (2026-10-29 21:04, England
    -- defending at Caen, the Battle Deployment panel), execute() on it hung the game for good; the
    -- bridge never logged again and crash-watch had to relaunch. The scripted click had worked for weeks.
    if element == "prebattle_auto_resolve_button" then scripted = true end
    if not scripted then
        local ok, el = pcall(function() return gameSTDUI and gameSTDUI.getUiElement(element) end)
        if ok and el and el.execute and pcall(function() el:execute() end) then return end
    end
    stratmap.game.scriptCommand("select_ui_element", element)
    stratmap.game.scriptCommand("simulate_mouse_click", "lclick_up")
end

-- End Turn by the game's own call too (live, 2026-10-29: execute pressed the auto-resolve button
-- and the battle resolved; #204); the scripted click stays the fallback inside click
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
K.DISMISS = { "prebattle_auto_resolve_button", "close_tick_button", "diplomacy_decline_offer_button",
                  "siege_maintain_button", "siege_assault_button", "siege_end_button",
                  "release_prisoners_button", "close_cross_button",
                  "close_seal_button" }
K.AI_STUCK_AFTER = 30  -- seconds one AI faction's turn may sit unchanged (they take seconds)
K.MAX_TRIES = 15  -- then stop clicking and ask for a human on screen (one try every 20-30 s)
local watch = {}
local pressed = {}  -- buttons already pressed while they linger on screen (never pressed twice)
M.pressed = pressed
local offer_answered = false  -- an AI's offer on the diplomacy screen has been answered

-- the known popup buttons that are open now, if EOP can tell (gameSTDUI.getUiElement looks
-- them up by name); if it can't, or finds none, all of them in turn (pressing a button that
-- isn't on screen does nothing)
local function open_popups()
    if not (gameSTDUI and gameSTDUI.getUiElement) then return K.DISMISS end
    local open = {}
    for _, name in ipairs(K.DISMISS) do
        local ok, e = pcall(gameSTDUI.getUiElement, name)
        if ok and e and not pressed[name] then open[#open + 1] = name end
    end
    return #open > 0 and open or K.DISMISS
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
        -- never the papal election's scrolls (K.PAPAL_SCROLLS: looking one up hung the game)
        local ok, el = false, nil
        if not name:find("papal", 1, true) then ok, el = pcall(gameSTDUI.getUiElement, name) end
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
K.DECISION = {
    prebattle_scroll = "prebattle_auto_resolve_button",
    diplomacy_scroll = "diplomacy_decline_offer_button",  -- an AI's offer to the human slot
    siege_scroll = "siege_maintain_button",
    loot_settlement_scroll = "loot_settlement_occupy_button",
    captor_ransom_scroll = "ransom_prisoners_button",
    captive_ransom_scroll = "accept_ransom_button",
}
-- popups the game raises on its own (not ones a watcher opens to look at things)
K.GAME_POPUPS = {
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
K.MESSAGE_SCROLLS = { "event_scroll", "message_scroll", "faction_events_scroll", "hotseat_message_scroll" }
-- The papal election's scrolls are never looked up, pressed or scanned: the game hung three
-- times (10-30 08:41:52, 18:34:11, 19:04:51) right after the bridge called getUiElement on the
-- results scroll inside its own open event, while the game was still building it (found=false;
-- the event's second firing never came). The game runs the election; the turn loop clicks the
-- ruler's vote from a screenshot; the result closes by itself (every good case, live).
K.PAPAL_SCROLLS = { papal_election_scroll = true, papal_election_results_scroll = true }
for name in pairs(K.GAME_POPUPS) do  -- a message may raise any game popup: look at all of them
    if not K.PAPAL_SCROLLS[name] then K.MESSAGE_SCROLLS[#K.MESSAGE_SCROLLS + 1] = name end
end
table.sort(K.MESSAGE_SCROLLS)
-- (the siege panel too: screenshotted before "maintain" is pressed, so its equipment icons can
-- be measured from the image; reading the game's UI deeper crashed the game live)
K.READ_SCROLLS = { post_battle_scroll = true, ransom_result_scroll = true, siege_scroll = true }
-- decision scrolls the ruler chooses on (see CHOICES): no default pressed when they open
K.CHOICE_SCROLLS = { loot_settlement_scroll = true, captor_ransom_scroll = true,
                         captive_ransom_scroll = true, diplomacy_scroll = true }

-- Scrolls whose close tick has no name: the path of sub-element indexes to it (0-based), from a
-- live probe. post_battle_scroll: part 3 is the button row, its part 0 the tick (part 1 is
-- post_battle_show_stats_button); seen live holding up the HRE's turn after a bridge reload.
K.TICK_PARTS = { post_battle_scroll = { 3, 0 }, ransom_result_scroll = { 0 } }

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
-- (the papal election's was recorded once, live: ui_scan-papal.txt; papal scrolls aren't looked up now)
K.LAYOUT_FILES = { siege_scroll = "ui_scan-siege.txt" }
local recorded = {}

function M.record_layout(scroll, el)
    local file = K.LAYOUT_FILES[scroll]
    if not file or recorded[scroll] then return end
    recorded[scroll] = true
    -- one level only, as the UI scans do safely: a walk four levels down crashed the game live
    -- (the siege panel has a part named "null", likely a bad pointer; pcall can't catch that)
    pcall(function()
        atomic_write(root .. "/" .. file, scroll .. ": " .. describe(el) .. "\n")
        log("popup " .. scroll .. ": layout written to " .. file)
    end)
end

-- Papal election crash trace. The game died 5 times right after the results scroll opened (10-26
-- 14:39, 10-27 09:28, 10-29 14:08, +2), leaving no log line that says which call ran last. Every
-- step around a papal scroll (and around any message popup within 120 s of one) is logged BEFORE
-- the call it names (the log file is closed per line, so it is flushed), and the same step is
-- written to papal_trace.txt: n = papal scrolls opened ever, seq = steps this run, done = 1 once the
-- popup was fully handled. M.trace_load (from setup) reads it back after a relaunch: done=0 means
-- the previous run died inside `last`. Trace only; no behaviour hangs on it.
M.trace_state = { n = 0, seq = 0 }
function M.trace(step, scroll, mode)
    pcall(function()
        local name = tostring(scroll or "")
        local papal = name:find("papal", 1, true) ~= nil
        local now = M.clock()
        if papal and mode == "open" then M.papal_until = now + 120 end
        local st = M.trace_state
        local live = papal or (M.papal_until and now < M.papal_until)
        if not (live or mode == "always" or (mode == "done" and st.open)) then return end
        if mode == "open" and papal then st.n = st.n + 1 end
        st.seq = st.seq + 1
        log("papal-trace: #" .. st.seq .. " " .. step .. (name ~= "" and (" [" .. name .. "]") or ""))
        if not live and not (mode == "done" and st.open) then return end  -- a plain message: log line only
        st.open = mode ~= "done"
        local turn = pcall(function() return gd.campaignStruct.turnNumber end) and gd.campaignStruct.turnNumber or "?"
        atomic_write(root .. "/papal_trace.txt", string.format("n=%d\nseq=%d\ndone=%d\nturn=%s\nlast=%s\nscroll=%s\nat=%s\n",
            st.n, st.seq, mode == "done" and 1 or 0, tostring(turn), step, name, os.date("%Y-%m-%d %H:%M:%S")))
    end)
end

function M.trace_load()
    pcall(function()
        local text = read_file(root .. "/papal_trace.txt")
        if not text then return end
        local n = tonumber(text:match("n=(%d+)")) or 0
        M.trace_state = { n = n, seq = 0 }
        if text:match("done=0") then
            log("papal-trace: PREVIOUS RUN ENDED MID-STEP (papal scrolls so far: " .. n .. "), last="
                .. tostring(text:match("last=([^\n]*)")) .. " scroll=" .. tostring(text:match("scroll=([^\n]*)"))
                .. " at=" .. tostring(text:match("at=([^\n]*)")) .. " turn=" .. tostring(text:match("turn=([^\n]*)")))
        end
    end)
end

-- press the unnamed close of an open result scroll (all of them, or just `only`): the path a
-- live probe found (TICK_PARTS), else one found by shape. Never a decision scroll's.
local function press_tick_part(only)
    for scroll in pairs(K.GAME_POPUPS) do
        -- a vote, and a vote's result, are never pressed by shape: the result closes by itself
        -- (live, every good case) and the game crashed three times right after one opened and
        -- didn't (10-26 14:39, 10-27 09:28, 10-29 14:08), each the bridge's last log line
        if (not only or only == scroll) and not K.DECISION[scroll] and not K.CHOICE_SCROLLS[scroll]
            and not K.PAPAL_SCROLLS[scroll] then
            local ok, done = pcall(function()
                local el = gameSTDUI.getUiElement(scroll)
                if not el then return false end
                local b
                if K.TICK_PARTS[scroll] then
                    b = el
                    for _, i in ipairs(K.TICK_PARTS[scroll]) do b = b:getSubElement(i) end
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

-- the faction overview opens itself at a campaign's start and holds the AI turns behind it
-- (live, a new campaign on 2026-10-29: Scotland's turn sat until it was closed by hand). Only a stuck
-- turn closes it: a watcher may open it to look at things. The spy report too ("Enemy Settlement
-- Details", enemy_settlement_info_scroll): a spy's mission on Nottingham opened it on 2026-10-30
-- and it held France's turn for 7 minutes until closed by hand; the live scan showed the same
-- frame and the same unnamed 58x65 check at the bottom right (#5 @962,528) as the overview.
K.STUCK_ONLY_SCROLLS = { "combined_overview_scroll", "enemy_settlement_info_scroll" }
-- press the close found by shape on `scroll` if it is open; the scroll's name if pressed. One
-- getUiElement call; a scroll that isn't open (nil) presses nothing.
local function close_by_shape(scroll)
    if not (gameSTDUI and gameSTDUI.getUiElement) then return end
    local ok, b = pcall(function()
        local el = gameSTDUI.getUiElement(scroll)
        return el and close_button(el)
    end)
    if ok and b then
        b:execute()
        return scroll
    end
end

local function close_overview()
    for _, scroll in ipairs(K.STUCK_ONLY_SCROLLS) do
        local closed = close_by_shape(scroll)
        if closed then return closed end
    end
end

-- A ruler's spy mission opens the spy report on its result (live 2026-10-30: the mission event
-- came at 11:00:13, the scroll then held France's turn). M.on_agent_mission arms this; the turn
-- loop then looks for the scroll once per tick, after K.POPUP_DELAY (a watcher can read it), for
-- up to K.SPY_REPORT_WAIT seconds. Its content isn't read: the rulers get the same facts from EOP.
K.SPY_REPORT = "enemy_settlement_info_scroll"
K.SPY_REPORT_WAIT = 30
local function close_spy_report(now)
    local s = M.spy_report
    if not s or now < s.from then return end
    if now > s.to then
        M.spy_report = nil
        log("agent mission: no spy report open within " .. K.SPY_REPORT_WAIT .. "s; left to the stuck-turn check")
        return
    end
    if close_by_shape(K.SPY_REPORT) then
        M.spy_report = nil
        log("popup " .. K.SPY_REPORT .. ": closed the spy report after " .. s.who .. "'s mission")
        return true
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
    if state.tries > K.MAX_TRIES then
        if not state.gave_up then log("autoplay: " .. who .. " still stuck after " .. K.MAX_TRIES ..
                                      " tries; needs a human click") end
        state.gave_up = true
        M.status = "Parley: stuck on " .. who .. ", needs a human click"
        -- never give up for good (live: a marriage offer held the game all night): keep asking
        -- the turn loop to look, every second check (about 40 s; the author: two minutes was too slow)
        if (state.tries - K.MAX_TRIES) % 2 ~= 0 then return false end
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
    local ticked = gameSTDUI and (press_tick_part() or close_overview())
    if ticked then
        log("autoplay: " .. who .. " stuck? try " .. state.tries .. ": " .. ticked .. "'s tick")
        return true
    end
    -- only buttons actually on screen: pressing absent ones blind cost a minute a try (the author:
    -- "stuff getting stuck takes too long"); the minimized-message reopening asked for above
    -- covers what no named button can
    local open = {}
    if gameSTDUI and gameSTDUI.getUiElement then
        for _, n in ipairs(K.DISMISS) do
            local ok, e = pcall(gameSTDUI.getUiElement, n)
            if ok and e and (not pressed[n] or (state.tries > 1 and not n:find("^diplomacy_"))) then
                open[#open + 1] = n
            end
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
    if now - watch.since >= K.AI_STUCK_AFTER then
        try_dismiss(watch, tostring(fac.name) .. "'s turn")
        watch.since = now
    end
end

-- --- popups: under autoplay every game popup is acknowledged, logged, and told to the ruler --
-- Scroll names are the game's own (medieval2.exe strings). EOP can't read a scroll's text,
-- only its name and its buttons' names, so the ruler hears what kind of popup it was.

K.POPUP_DELAY = 3  -- seconds a popup stays up, so a watcher can read it
-- an acknowledging button, best first
K.ACK = { "close_tick", "tick", "_ok", "ok_", "accept", "continue", "close" }

local pending, popups = {}, {}  -- popups waiting to be pressed; what the human slot hasn't heard yet
function M.pending() return pending end

-- The papal election's notice (event 202: the Pope is dead, the cardinals convene). Left alone,
-- the game opened the election 3-6 s after it (live 10-30 18:54:16, 19:04:51, 19:47:03); a
-- clear_messages in between and it never opened, End Turn blocked behind it (live 10-29 18:30,
-- 10-30 18:16, 18:33, 19:41). So every popup is left alone until the election opens, and the
-- notice itself is never cleared. With no election by then, the turn loop presses the notice's
-- check (live 18:17:04, 18:34:11: a reopened notice's check opened it).
K.PAPAL_NOTICE = 202
K.PAPAL_NOTICE_WAIT = 15  -- seconds
local papal_notice_at  -- when the notice came; nil once the election opened or the wait ran out

-- The papal window: the game died four times (10-30 18:34:11, 19:04:51, 20:06:30, 20:48:34) with a
-- turn loop click in the same second as a papal scroll opening (a notice's check, a stale
-- request's check, a marriage declined). From the notice (or a scroll, when no notice came: a
-- result England had no vote in) until the result has closed, the bridge asks the turn loop for
-- nothing but the vote and, before the election opens, the notice's check; stuck-turn checks
-- wait. papal_window.txt tells the turn loop (parley/popups.py: papal_phase) to press nothing
-- else, decisions already in hand included. The result closes by itself; it isn't looked up.
-- seconds; vote: the bridge's DECIDE_WAIT; voted (hands off, K.PAPAL_LOOK): from the vote's
-- click, the result's 10 s plus the time it takes to open, as phase "results"
K.PAPAL_WINDOW = { notice = 45, vote = 180, results = 10, voted = 20 }
local papal_window  -- { phase, ends } while the window is open

local function papal_window_write()
    if papal_window then
        atomic_write(root .. "/papal_window.txt",
            string.format("phase=%s\nuntil=%d\n", papal_window.phase, papal_window.ends))
    else
        os.remove(root .. "/papal_window.txt")
    end
end

function M.papal_window_open(phase)
    local now = M.clock()
    if phase == "notice" and papal_window then return end  -- (a reopened notice: the election is on)
    local secs = K.PAPAL_WINDOW[phase]
    if phase == "voted" then phase = "results" end  -- (the turn loop knows notice/vote/results)
    papal_window = { phase = phase, ends = now + secs }
    papal_window_write()
    log("papal window: " .. phase .. "; the turn loop presses nothing else for up to " .. secs .. "s")
end

-- the window's phase while it's open, else nil (and it's closed once over)
function M.papal_phase(now)
    if not papal_window then return nil end
    now = now or M.clock()
    if now < papal_window.ends then return papal_window.phase end
    papal_window = nil
    papal_window_write()
    for _, p in ipairs(pending) do  -- held through the window: each gets its full wait from now
        if p.requested then p.requested = now end
    end
    log("papal window: closed; the turn loop may press again")
    return nil
end

-- after a reload (live 20:20:56, a second before the election opened): the window goes on
function M.papal_window_load()
    papal_window = nil
    local text = read_file(root .. "/papal_window.txt")
    local phase, ends = (text or ""):match("phase=(%w+)"), tonumber((text or ""):match("until=(%d+)"))
    if phase and ends then
        papal_window = { phase = phase, ends = ends }
        log("papal window: " .. phase .. " (kept across the reload)")
    end
    M.papal_phase()
end

local function note_popup(text)
    popups[#popups + 1] = text
    while #popups > 20 do table.remove(popups, 1) end
end

local siege_tried = {}
local siege_active_seq = nil
local last_siege_press = nil

local function siege_count()
    if type(M.assault_ordered) == "number" then return M.assault_ordered end
    if M.assault_ordered == true then return 1 end
    return 0
end

local function siege_sequence()
    if siege_count() > 0 then
        return { "siege_assault_button", "siege_maintain_button", "siege_end_button" }
    else
        return { "siege_maintain_button", "siege_assault_button", "siege_end_button" }
    end
end

local function next_siege_button()
    if not siege_active_seq then
        siege_active_seq = siege_sequence()
    end
    for _, btn in ipairs(siege_active_seq) do
        if not siege_tried[btn] then return btn end
    end
    return siege_active_seq[#siege_active_seq]
end

local function record_siege_press(btn)
    siege_tried[btn] = true
    last_siege_press = btn
    if btn == "siege_assault_button" then
        if type(M.assault_ordered) == "number" then
            M.assault_ordered = math.max(0, M.assault_ordered - 1)
        else
            M.assault_ordered = 0
        end
    end
end

local function check_siege_closed()
    local ok, el = pcall(gameSTDUI.getUiElement, "siege_scroll")
    if (not ok or not el) and last_siege_press then
        local closed_by = last_siege_press
        siege_active_seq = nil
        siege_tried = {}
        last_siege_press = nil
        local text = "a siege (siege_scroll -> " .. closed_by .. ")"
        log("popup handled: " .. text)
        note_popup(text)
        return closed_by
    end
    if not ok or not el then
        siege_active_seq = nil
        siege_tried = {}
        last_siege_press = nil
    end
    return nil
end

local function is_scroll_pending(scroll)
    for _, p in ipairs(pending) do
        if p.scroll == scroll then return true end
    end
    return false
end

local function buttons_for_scroll(scroll, el)
    local list = buttons_of(el)
    if scroll == "siege_scroll" and gameSTDUI and gameSTDUI.getUiElement then
        local names_present = {}
        for _, b in ipairs(list) do
            if b.elementName and b.elementName ~= "" and b.elementName ~= "null" then
                names_present[b.elementName] = true
            end
        end
        for _, n in ipairs({ "siege_assault_button", "siege_maintain_button", "siege_end_button" }) do
            if not names_present[n] then
                local ok, b = pcall(gameSTDUI.getUiElement, n)
                if ok and b then list[#list + 1] = b end
            end
        end
    end
    return list
end

local function choose(scroll, buttons)
    if scroll == "siege_scroll" then
        if not siege_active_seq then
            siege_active_seq = siege_sequence()
        end
        for _, btn in ipairs(siege_active_seq) do
            if not siege_tried[btn] then
                for _, b in ipairs(buttons) do
                    if b.elementName == btn then return b end
                end
            end
        end
        for _, btn in ipairs(siege_active_seq) do
            for _, b in ipairs(buttons) do
                if b.elementName == btn then return b end
            end
        end
    else
        local want = K.DECISION[scroll]
        for _, b in ipairs(buttons) do
            if want and b.elementName == want then return b end
        end
    end
    for _, word in ipairs(K.ACK) do
        for _, b in ipairs(buttons) do
            if b.elementName:find(word, 1, true) then return b end
        end
    end
end

-- a papal scroll is up (its event, or the hands-off look from the tick): the papal window, and
-- for the election one entry asking the ruler's vote; nothing is read from the scroll itself
local function papal_queue(scroll)
    M.papal_window_open(scroll == "papal_election_scroll" and "vote" or "results")
    local p = { scroll = scroll, at = M.clock() }
    -- the papal election: the ruler's cardinals vote; the turn loop finds the Vote buttons
    -- (seen live: the scroll sat unanswered and held the turn)
    if scroll == "papal_election_scroll" then
        p.message, p.kind = "scroll:" .. scroll, "vote"
        if papal_notice_at then log("papal notice: the election opened") end
        papal_notice_at = nil
        for _, n in ipairs(pending) do  -- its check is no longer wanted
            if n.message == K.PAPAL_NOTICE then n.election_opened = true end
        end
    end
    pending[#pending + 1] = p
end

-- papal_hands_off: the bridge never hears of a papal scroll (luaPluginScript's onScrollOpened
-- returns at once: Lua work inside that event preceded every results crash, 20:48, 22:29, 22:43;
-- four QA runs with it off the event went through turns 59-67 clean). The vote scroll is looked
-- for from the per-frame tick instead, between frames, never while the game is inside its open
-- event (the three hangs of 5295dc4 were lookups inside the event, found=false: still being
-- built). One guarded getUiElement("papal_election_scroll") per look, a look every `every`
-- seconds from `after` seconds past the Pope's death notice (202; the game opened the election
-- 3-6 s after it live) for up to `for_` seconds. Nothing on the scroll is read; the turn loop
-- finds the Vote buttons in a screenshot. The results scroll is never looked up.
K.PAPAL_LOOK = { after = 3, every = 2, for_ = 60 }
local papal_look  -- { next, ends } while the vote scroll is being looked for

local function papal_look_start(now)
    if papal_look then return end
    papal_look = { next = now + K.PAPAL_LOOK.after, ends = now + K.PAPAL_LOOK.for_ }
    log("papal vote: looking for the vote scroll from the tick (hands off its event)")
end

local function papal_look_tick(now)
    local look = papal_look
    if not look then return end
    if not M.papal_hands_off or is_scroll_pending("papal_election_scroll") then
        papal_look = nil
        return
    end
    if now >= look.ends then
        papal_look = nil
        log("papal vote: no vote scroll " .. K.PAPAL_LOOK.for_ .. "s after the notice; stopped looking")
        return
    end
    if now < look.next or not (gameSTDUI and gameSTDUI.getUiElement) then return end
    look.next = now + K.PAPAL_LOOK.every
    local scroll = "papal_election_scroll"
    M.trace("tick: calling getUiElement (hands-off vote look)", scroll)
    local ok, el = pcall(gameSTDUI.getUiElement, scroll)
    -- (not found: the step closes, so a later relaunch doesn't read it as a death mid-look)
    M.trace("tick: getUiElement returned, found=" .. tostring(ok and el ~= nil), scroll,
            not (ok and el) and "done" or nil)
    if not (ok and el) then return end
    papal_look = nil
    log("papal vote: the vote scroll is up (seen from the tick)")
    M.trace("tick: the vote scroll is up; asking the ruler's vote", scroll, "open")
    papal_queue(scroll)
end

-- EOP onScrollOpened: eventData may be the scroll's name or carry it as resourceDescription
function M.on_scroll_opened(e)
    local cfg = config()
    if not cfg or not cfg.autoplay then return end
    local scroll = type(e) == "string" and e or (e and e.resourceDescription)
    if not scroll or not K.GAME_POPUPS[scroll] then return end  -- a scroll a watcher opened: leave it
    if K.PAPAL_SCROLLS[scroll] then
        -- no UI call at all (K.PAPAL_SCROLLS); the game fires this event twice per scroll: one
        -- entry (one vote request: live, the second vote click landed after the result was up)
        if is_scroll_pending(scroll) then
            M.trace("onScrollOpened: event again; already queued; ignored", scroll)
            return
        end
        M.trace("onScrollOpened: event received; no UI call (the game is still building it)", scroll, "open")
        log("popup " .. scroll .. ": opened; left to the game (no UI call)")
        papal_queue(scroll)
        return
    end
    M.trace("onScrollOpened: event received", scroll, "open")
    M.trace("calling gameSTDUI.getUiElement", scroll)
    local ok, el = pcall(gameSTDUI.getUiElement, scroll)
    M.trace("getUiElement returned, found=" .. tostring(ok and el ~= nil), scroll)
    if ok and el then M.trace("calling buttons_of/names (reads the element's parts)", scroll) end
    log("popup " .. scroll .. ": " .. ((ok and el) and names(buttons_of(el)) or "(not found)"))
    if ok and el then
        M.trace("buttons_of/names returned; calling record_layout", scroll)
        M.record_layout(scroll, el)
        M.trace("record_layout returned", scroll)
    end
    if K.CHOICE_SCROLLS[scroll] then return end  -- the ruler chooses (watch_buttons), no default here
    local p = { scroll = scroll, at = M.clock() }
    -- results worth reading before they close: the turn loop screenshots them for the ruler
    -- (asked live: "Did Rufus survive, and how many men did we lose?")
    if K.READ_SCROLLS[scroll] then p.message, p.kind = "scroll:" .. scroll, "read" end
    pending[#pending + 1] = p
end

-- A message popup's text can't be read from Lua, so the turn loop screenshots it and has it
-- read (parley/popups.py): the bridge writes popup-<id>.req and holds the popup until
-- popup-<id>.done appears. A marriage or adoption offer is a decision: the ruler decides and the
-- turn loop clicks accept or decline, so it is never cleared out from under the ruler.
-- DECIDE_WAIT: The author 10-31 "give Heretic more time": at 180 the ruler (decide_timeout 120, queued
-- behind both busy Heretic slots) timed out and the default was pressed; the loop now allows 480
local READ_WAIT, DECIDE_WAIT = 30, 540  -- seconds before giving up on the turn loop
K.DECISIONS = { marriage = "a marriage offer", adoption = "an adoption offer",
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
    M.trace("onIncomingMessage: event " .. tostring(id) .. " queued (nothing read from the game)", "message:" .. tostring(id), "always")
    -- (an offer's own scroll raised its request already: the turn loop's fresh look before
    -- deciding turns this one into a plain reading once the offer is answered)
    local phase = M.papal_phase()
    pending[#pending + 1] = { message = id, at = M.clock(), kind = "read",
                              -- a notice reopened once the election is on: its check isn't wanted
                              election_opened = (id == K.PAPAL_NOTICE and (is_scroll_pending("papal_election_scroll")
                                  or (phase and phase ~= "notice"))) or nil }
    if id == K.PAPAL_NOTICE and not is_scroll_pending("papal_election_scroll") then
        papal_notice_at = M.clock()
        log("papal notice: hands off until the election opens (up to " .. K.PAPAL_NOTICE_WAIT .. "s)")
        -- hands off the scroll events: the tick looks for the vote scroll instead (K.PAPAL_LOOK)
        if M.papal_hands_off and (not phase or phase == "notice") then papal_look_start(M.clock()) end
    end
    if id == K.PAPAL_NOTICE then M.papal_window_open("notice") end
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
                      suitor = p.offer and p.offer.suitor or nil,
                      -- pressed even if it looks like the last scroll read (live 19:43: a reopened
                      -- notice, never pressed, cleared again every stuck try)
                      press_check = (p.message == K.PAPAL_NOTICE and not p.election_opened) or nil }
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
    if now - p.requested >= ((K.DECISIONS[p.kind] or p.decision) and DECIDE_WAIT or READ_WAIT) then
        os.remove(p.request .. ".req")
        os.remove(p.request .. ".hold")
        log("popup " .. p.request .. ": the turn loop didn't capture it in time")
        return true, "timeout"
    end
    return false
end

-- press each pending popup's button once it has been up for POPUP_DELAY seconds
local function handle_popups(now)
    if papal_notice_at and now - papal_notice_at >= K.PAPAL_NOTICE_WAIT then
        log("papal notice: no election after " .. K.PAPAL_NOTICE_WAIT .. "s; asking for its check")
        papal_notice_at = nil
    end
    local keep, list = {}, pending
    local phase = M.papal_phase(now)
    if papal_notice_at or phase then
        -- hands off (K.PAPAL_NOTICE, K.PAPAL_WINDOW): only the papal scrolls' own entries, and the
        -- notice's own once its wait is over and the election still hasn't opened (its check)
        list = {}
        for _, p in ipairs(pending) do
            if K.PAPAL_SCROLLS[p.scroll]
                or (p.message == K.PAPAL_NOTICE and not papal_notice_at and phase == "notice") then
                list[#list + 1] = p
            else
                keep[#keep + 1] = p
            end
        end
    end
    for _, p in ipairs(list) do
        local held, how = false, p.how
        if p.message and not p.how and now - p.at >= K.POPUP_DELAY then
            local done
            local tname = p.scroll or ("message:" .. tostring(p.message))
            M.trace("calling captured() (asks the turn loop to screenshot it)", tname)
            done, how = captured(p, now)
            M.trace("captured() returned done=" .. tostring(done) .. " how=" .. tostring(how), tname)
            held = not done
            if done then p.how = how end  -- settled; a deferred one isn't asked again
        end
        if now - p.at < K.POPUP_DELAY or held then
            keep[#keep + 1] = p
        elseif not (K.DECISIONS[p.kind] or p.decision) and p.message and M.deciding() then
            -- clear_messages would minimize the decision being weighed; a minimized decision
            -- blocks End Turn unseen (seen live: Barnaby's adoption, minimized mid-answer)
            keep[#keep + 1] = p
        elseif p.decision and how ~= "captured" then
            -- a decision nobody answered: left on screen for a human, never minimized
            log("popup: a decision left unanswered on screen")
            note_popup("a decision (left unanswered)")
        elseif K.DECISIONS[p.kind] or (p.decision and how == "captured") then
            -- (a generic decision the turn loop never answered falls through and is dismissed)
            -- the turn loop clicked the ruler's answer; if it timed out, a human answers it
            local what = K.DECISIONS[p.kind] or "a decision"
            log("popup: " .. what .. " " .. (how == "captured" and "answered by the ruler" or "left for a human"))
            note_popup(what .. " (" .. (how == "captured" and "you answered it" or "left unanswered") .. ")")
            if p.kind == "vote" and how == "captured" and M.papal_hands_off then
                -- hands off: no results event reaches the bridge, so the result's window opens
                -- from the vote (the result follows the click and closes by itself)
                M.papal_window_open("voted")
            end
        else
            local scrolls = p.scroll and { p.scroll } or K.MESSAGE_SCROLLS
            local done = p.acked and "acknowledged with its check" or nil
            if done or K.PAPAL_SCROLLS[p.scroll] then scrolls = {} end  -- a papal result closes by itself
            for _, scroll in ipairs(scrolls) do
                M.trace("handle: calling getUiElement", scroll)
                local ok, el = pcall(gameSTDUI.getUiElement, scroll)
                if ok and el then
                    M.trace("handle: found; calling record_layout", scroll)
                    M.record_layout(scroll, el)
                    M.trace("handle: calling buttons_for_scroll/choose", scroll)
                    local b = choose(scroll, buttons_for_scroll(scroll, el))
                    M.trace("handle: choose returned " .. (b and ("button " .. tostring(b.elementName)) or "no button"), scroll)
                    if b then
                        M.trace("handle: calling button:execute() on " .. tostring(b.elementName), scroll)
                        b:execute()
                        M.trace("handle: execute() returned", scroll)
                        if scroll == "siege_scroll" then
                            record_siege_press(b.elementName)
                            local ok_still, still_el = pcall(gameSTDUI.getUiElement, "siege_scroll")
                            if not ok_still or not still_el then
                                done = scroll .. " -> " .. b.elementName
                                siege_active_seq = nil
                                siege_tried = {}
                                last_siege_press = nil
                            end
                        else
                            done = scroll .. " -> " .. b.elementName
                        end
                        if done then break end
                    end
                    M.trace("handle: calling press_tick_part", scroll)
                    if press_tick_part(scroll) then
                        done = scroll .. " -> its tick"
                        break
                    end
                    log("popup " .. scroll .. ": no button to press among " .. names(buttons_for_scroll(scroll, el)))
                end
            end
            -- event messages (missions, riots, news, proposals) live in no element we can name;
            -- the campaign script command clear_messages closed one live (a riot in Rennes)
            if not done and p.message == K.PAPAL_NOTICE then
                -- never cleared: clearing it never opened the election (live 19:42:13, 19:43:33)
                done = "left to the game: the papal election's notice"
            elseif not done and p.message and not p.scroll then
                M.trace("handle: calling scriptCommand('clear_messages')", "message:" .. tostring(p.message))
                stratmap.game.scriptCommand("clear_messages", "")
                M.trace("handle: clear_messages returned", "message:" .. tostring(p.message))
                done = "clear_messages"
            end
            local keep_siege = false
            if p.scroll == "siege_scroll" and not done then
                local ok_still, still_el = false, nil
                if gameSTDUI and gameSTDUI.getUiElement then
                    ok_still, still_el = pcall(gameSTDUI.getUiElement, "siege_scroll")
                end
                if ok_still and still_el then
                    p.tries = (p.tries or 0) + 1
                    if p.tries <= 10 then
                        keep_siege = true
                        keep[#keep + 1] = p
                    else
                        log("popup siege_scroll: still open after 10 tries; dropping")
                    end
                end
                if not keep_siege then
                    done = last_siege_press and ("siege_scroll -> " .. last_siege_press) or "closed"
                    siege_active_seq = nil
                    siege_tried = {}
                    last_siege_press = nil
                end
            end
            if not keep_siege then
                local what = p.scroll and K.GAME_POPUPS[p.scroll] or ("game message " .. tostring(p.message))
                local text = p.scroll and (what .. " (" .. (done or p.scroll .. ", closed by itself") .. ")")
                    or ("game message " .. tostring(p.message) .. (done and (" (" .. done .. ")") or ""))
                log("popup handled: " .. text)
                note_popup(text)
                M.trace("popup handled; done", p.scroll or ("message:" .. tostring(p.message)), "done")
            end
        end
    end
    pending = keep
end

-- Decision buttons that exist only while the game waits on the human. The game's own UI
-- lookup finds them by name while they're on screen (seen in a live UI scan, 2026-10-24),
-- which catches popups no event announces, like an AI's offer made during the AI's turn.
K.WATCHED = {
    { "prebattle_auto_resolve_button", "a battle (auto-resolved)" },
    { "diplomacy_decline_offer_button", "an AI's diplomatic offer (declined; the game says not what)" },
    { "siege_maintain_button", "a siege (kept up)" },
    { "loot_settlement_occupy_button", "a captured settlement (occupied)" },
    { "ransom_prisoners_button", "prisoners taken (ransomed)" },
    { "accept_ransom_button", "your men captured (ransom accepted)" },
}
local on_screen = {}  -- watched button -> when it was first seen

-- The ruler's choice on a named decision scroll, keyed by the watched button that shows it is
-- up: { option, button } in the game's own names (its typo included). The turn loop asks the
-- ruler and writes popup-<id>.answer; with no answer in time the first option is pressed.
K.CHOICES = {
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
    local spec, c = K.CHOICES[name], choosing[name]
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
    -- the game is about to open the papal election: a stuck-turn reopen click would disturb it
    if papal_notice_at and M.clock() - papal_notice_at < K.PAPAL_NOTICE_WAIT then return true end
    if M.papal_phase() then return true end  -- the papal window: no reopen click until it's over
    for _, p in ipairs(pending) do
        if p.request and (p.decision or K.DECISIONS[p.kind]) then return true end
    end
    return false
end

-- End Turn waits for the ruler's answer to an offer on the human's screen. Live 10-30 20:48:04,
-- 20:55:59 and 22:28:31 (QA field, turns 59 and 62): a marriage offer came up at England's turn
-- start, the bridge ended the turn 1-2 s later with it unanswered, the AI turns stalled behind it
-- (~30 s, no event), and the decline click released a queued papal results scroll and the
-- deferred End Turn in the same moment; the game died 5 s later twice in three. Answered on the
-- human's own turn, the decline releases no End Turn with it. Bounded: a decision request gives
-- up after DECIDE_WAIT, and the hold itself after K.DECISION_HOLD_MAX.
K.DECISION_HOLD_MAX = DECIDE_WAIT + 30  -- seconds

-- what offer is still with the ruler (nil: none)
function M.decision_waiting()
    if next(choosing) then return "a diplomatic offer" end
    for _, p in ipairs(pending) do
        if K.DECISIONS[p.kind] or p.decision then return K.DECISIONS[p.kind] or "a decision" end
    end
    return nil
end

local function watch_buttons(now)
    if not (gameSTDUI and gameSTDUI.getUiElement) then return end
    check_siege_closed()
    for _, w in ipairs(K.WATCHED) do
        local name, what = w[1], w[2]
        if name == "siege_maintain_button" then
            if is_scroll_pending("siege_scroll") then
                name = nil
            else
                local ok_s, s_el = pcall(gameSTDUI.getUiElement, "siege_scroll")
                if ok_s and s_el then
                    name = next_siege_button()
                    if name == "siege_assault_button" then
                        what = "a siege (assaulted, as ordered)"
                    elseif name == "siege_end_button" then
                        what = "a siege (ended, fallback)"
                    end
                    local siege_seen = on_screen["siege_maintain_button"] or on_screen["siege_scroll"] or now
                    on_screen[name] = on_screen[name] or siege_seen
                elseif siege_count() > 0 then
                    name, what = "siege_assault_button", "a siege (assaulted, as ordered)"
                end
            end
        end
        local ok, el = false, nil
        if name then ok, el = pcall(gameSTDUI.getUiElement, name) end
        if ok and el then
            -- press once, then not again until the button is gone: the game keeps a screen's
            -- buttons after they're used (seen live: decline pressed every 6 s, the AI answering)
            on_screen[name] = on_screen[name] or now
            if not pressed[name] and now - on_screen[name] >= K.POPUP_DELAY then
                local press = name
                if K.CHOICES[name] then
                    local o, answered = choice_for(name, now)
                    press = o and o[2]
                    if o then
                        what = K.CHOICES[name].what .. " (" .. o[1] .. (answered and ", your choice)" or
                                                                          ", nobody chose in time)")
                    end
                end
                if press then
                    pressed[name] = true
                    if press:find("^siege_") then
                        record_siege_press(press)
                    end
                    if name:find("^diplomacy_") then offer_answered = true end
                    log("popup button on screen: pressing " .. press)
                    note_popup(what)
                    -- press the chosen button, never the watched one: an offer is watched by its
                    -- decline button, and the ruler's "accept" must not press decline
                    click(press)  -- executes press's own element (never the watched one), else clicks
                    check_siege_closed()
                end
            end
        else
            if name then
                on_screen[name], pressed[name] = nil, nil
                if choosing[name] then  -- the scroll went (closed by someone else): drop the question
                    os.remove(choosing[name].request .. ".req")
                    choosing[name] = nil
                end
            end
        end
    end
end

-- After an offer is answered the game leaves the diplomacy screen open with no offer buttons;
-- its close seal has no name EOP exposes, so try the likely close buttons one at a time (and
-- scan once, so the log shows what that screen holds if none of them works).
K.CLOSE_DIPLOMACY = { "diplomacy_ok_button", "close_seal_button", "close_tick_button", "close_cross_button" }
K.OFFER_BUTTONS = { "diplomacy_accept_offer_button", "diplomacy_decline_offer_button",
                        "diplomacy_counter_offer_button" }
local leftover = {}
local reasked = 0  -- offers asked again on one open diplomacy screen (reset when it closes)

local function open(name)
    local ok, el = pcall(gameSTDUI.getUiElement, name)
    return ok and el ~= nil
end

local function close_leftover_diplomacy(now)
    if not (gameSTDUI and gameSTDUI.getUiElement) or not open("diplomacy_scroll") then
        leftover, offer_answered, reasked = {}, false, 0
        return
    end
    if not offer_answered then
        for _, b in ipairs(K.OFFER_BUTTONS) do
            if open(b) then leftover = {} return end  -- an offer is still waiting: watch_buttons answers it
        end
    end
    leftover.since = leftover.since or now
    if now - leftover.since < K.POPUP_DELAY or now - (leftover.last or 0) < K.POPUP_DELAY then return end
    -- each try lasts until the screen closes; after one round of the close buttons stop
    -- (seen live: the AI answers each press and the screen keeps reopening)
    if (leftover.tries or 0) >= #K.CLOSE_DIPLOMACY then
        -- live (run9 turn 33, 03:53): Portugal's offer came up on the screen the Moors' answered
        -- offer had left open. Its buttons have the answered offer's names, never pressed twice
        -- while they linger, and no close button closes a screen whose offer waits: ask again
        if reasked < 2 then
            for _, b in ipairs(K.OFFER_BUTTONS) do
                if open(b) then
                    reasked = reasked + 1
                    log("popup: an offer still waits on the diplomacy screen after every close button; "
                        .. "a new offer: asking the ruler again")
                    for _, n in ipairs(K.OFFER_BUTTONS) do
                        on_screen[n], pressed[n] = nil, nil
                        if choosing[n] then
                            os.remove(choosing[n].request .. ".req")
                            choosing[n] = nil
                        end
                    end
                    leftover, offer_answered = {}, false
                    return
                end
            end
        end
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
    local name = K.CLOSE_DIPLOMACY[(leftover.tries - 1) % #K.CLOSE_DIPLOMACY + 1]
    leftover.last = now
    log("popup: diplomacy screen left open; trying " .. name)
    click(name)
end

-- QA bench setup helpers (called one per tick via control.txt `lua ...`).
M.qa = (function()
    local function run(helper, fn)
        local ok, res = pcall(fn)
        if not ok then
            log("qa: " .. helper .. " failed: " .. tostring(res))
            return nil
        end
        log("qa: " .. helper .. " ok: " .. tostring(res))
        return res
    end
    local function in_faction(f, name)
        if not f then return nil end
        for _, a in ipairs(agents_of(f)) do
            if same(a.id, name) or same(a.name, name) then return a.char end
        end
        for i = 0, (f.numOfCharacters or 0) - 1 do
            local ok, c = pcall(function()
                local c = f:getCharacter(i)
                local rec = c and (c.namedCharacter or c.characterRecord or c)
                local cname = rec and clean_name(rec.fullName)
                if c and (same(cname, name) or same_army_id(cname, name)) then return c end
            end)
            if ok and c then return c end
        end
    end
    -- the character and his faction
    local function find_char(name)
        local cur = gd and gd.campaignStruct and gd.campaignStruct.currentFaction
        local c = in_faction(cur, name)
        if c then return c, cur end
        for i = 0, (stratmap and stratmap.game and stratmap.game.getFactionsCount() or 0) - 1 do
            local f = stratmap.game.getFaction(i)
            c = in_faction(f, name)
            if c then return c, f end
        end
        error("unknown character '" .. tostring(name) .. "'")
    end
    -- Marriage (games/qa/envoys.toml marry_foreign_general): the game runs a proposal only between
    -- real family members. Live 11-04: to a spawned general (isFamily false) no mission came, and a
    -- spawned princess vanished at the order; Ysabel (France) to Karl von Heidelberg (HRE) ran one.
    local function truthy(v) return v == true or (type(v) == "number" and v ~= 0) end
    local function free_family(c, kind)
        local ok, yes = pcall(function()
            local rec = c.characterRecord or c.namedCharacter
            local t = c:getTypeName()
            local is_kind = kind == "general" and K.GENERAL_TYPES[t] or t == kind
            return is_kind and truthy(rec.isFamily) and (rec.age or 0) >= 16
                and not rec.spouse
        end)
        return ok and yes
    end
    local function free_princess(f)
        for i = 0, (f.numOfCharacters or 0) - 1 do
            local c = f:getCharacter(i)
            if free_family(c, "princess") then return c end
        end
    end
    -- unmarried family generals of age in factions of `f`'s religion at peace or allied with it
    local function suitors_of(f)
        local list = {}
        for i = 0, stratmap.game.getFactionsCount() - 1 do
            local o = stratmap.game.getFaction(i)
            if o and o.name ~= f.name and o.name ~= "slave" and o.name ~= "papal_states" and o.religion == f.religion then
                local okp, friendly = pcall(function()
                    local s = M.qa.stance(f.name, o.name)
                    return s == "peace" or s == "alliance"
                end)
                if okp and friendly then
                    for j = 0, (o.numOfCharacters or 0) - 1 do
                        local c = o:getCharacter(j)
                        -- leading a field army: a governor moved out of his town led no stack the
                        -- wooer's sight lists (bench 11-04: moved beside Cecilia, "sees nobody")
                        -- not his faction's leader or heir: the bench's Affonso (turn 5) took no
                        -- proposal, the princess didn't even move (11-04)
                        local okf, field = pcall(function()
                            local name = (c.characterRecord or c.namedCharacter).fullName
                            for _, r in ipairs({ o.leader or false, o.heir or false }) do
                                if r and r.fullName == name then return false end
                            end
                            return c.armyLeaded ~= nil and c.armyLeaded:findInSettlement() == nil
                        end)
                        if okf and field and free_family(c, "general") then list[#list + 1] = c end
                    end
                end
            end
        end
        return list
    end
    local function faction_named(faction)
        local fac = gd.campaignStruct:getFaction(faction)
        if not fac then error("unknown faction '" .. tostring(faction) .. "'") end
        return fac
    end
    -- the college of cardinals (EOP campaignStruct.collegeOfCardinals); never a UI call
    local function college_now()
        local college = gd.campaignStruct.collegeOfCardinals
        if not college then error("no college of cardinals") end
        return college
    end
    local function card_name(card)
        local c = card.character
        local rec = c and (c.characterRecord or c.namedCharacter)
        return (rec and clean_name(rec.fullName)) or "?"
    end
    -- the faction's cardinals (college entries with its factionID), and the college
    local function cardinals_of(fac)
        local college, out = college_now(), {}
        for i = 0, (college.cardinalNum or 0) - 1 do
            local card = college:getCardinal(i)
            if card and card.factionID == fac.factionID then out[#out + 1] = card end
        end
        return out, college
    end
    -- every tile someone stands on or a settlement sits on, as x * 1000 + y
    local function taken_tiles()
        local taken = {}
        for i = 0, stratmap.game.getFactionsCount() - 1 do
            local f = stratmap.game.getFaction(i)
            for j = 0, (f and f.numOfCharacters or 0) - 1 do
                pcall(function()
                    local c = f:getCharacter(j)
                    taken[math.floor(c.xCoord) * 1000 + math.floor(c.yCoord)] = true
                end)
            end
        end
        local map = gd.stratMap
        for r = 0, (map.regionsNum or 0) - 1 do
            pcall(function()
                local s = map.getRegion(r).settlement
                if s then taken[math.floor(s.xCoord) * 1000 + math.floor(s.yCoord)] = true end
            end)
        end
        return taken
    end
    -- whether an army can stand on a land tile: not impassable, no river unless it has a crossing,
    -- no fort or watchtower (EOP tileStruct, LuaDocs). Live 10-31 (bench save): William's split onto
    -- the river tile (108,146) by London never moved, and a spawn on it or on impassable (104,162)
    -- landed a tile off, where the game put it
    local function standable(t)
        if t.isImpassible == true then return false end
        if t.hasRiver == true and t.hasCrossing ~= true then return false end
        return t.hasFort ~= true and t.hasWatchtower ~= true
    end

    -- the first land tile near..far tiles (Chebyshev) from (x, y), ring by ring, with nobody and no
    -- settlement on it, an army can stand on it, walkable from (x, y) when that is land, and passing
    -- `ok_tile` when given: "x,y", or nil
    local function free_tile_near(x, y, near, far, ok_tile)
        local taken = taken_tiles()
        local from = tile_at(x, y)
        local anchored = from and is_land(from)
        for r = near, far do
            for dx = -r, r do
                for dy = -r, r do
                    local tx, ty = x + dx, y + dy
                    local t = math.max(math.abs(dx), math.abs(dy)) == r and tile_at(tx, ty)
                    if t and is_land(t) and standable(t) and not taken[tx * 1000 + ty]
                        and (not ok_tile or ok_tile(tx, ty)) then
                        local ok, reach = true, true
                        if anchored then ok, reach = pcall(land_reach, math.floor(x), math.floor(y), tx, ty) end
                        if ok and reach == true then return string.format("%d,%d", tx, ty) end
                    end
                end
            end
        end
    end
    -- the general of an army by its report id, his moves emptied. EOP character.movePoints "sets
    -- both army and character move points" (LuaDocs.lua:6496); movePointsCharacter (:6481) is read
    -- back, so a write that doesn't take fails the setup instead of passing as a tired mover
    -- A general no longer at the head of his own army is still tired by name: live QA field 10-30
    -- 23:58:45, Howard Stafford (spawned two tiles from Nottingham) was inside its garrison by the
    -- next turn start, his army id was gone ("unknown army"), his moves stayed full, and the
    -- no_moves_left case's move went ahead as an ordinary one.
    local function empty_moves(fac, id)
        local st = find_army_now(fac, id)
        local c = st and leader_of(fac, st)
        if not st then
            local okc, ch = pcall(in_faction, fac, id)
            c = okc and ch or nil
            if not c then error("unknown army '" .. tostring(id) .. "'") end
        end
        if not c then error("army '" .. tostring(id) .. "' has no general") end
        c.movePoints = 0
        local left = c.movePointsCharacter
        if type(left) ~= "number" or left > 0 then
            error("moves still " .. tostring(left) .. " after emptying " .. tostring(id))
        end
        return left
    end
    -- armies tire() keeps without moves: the game refills them at turn start, before orders apply
    local tired = {}
    -- what M.qa.order last said, by order type ([1]: the last of any type)
    local last_orders = {}
    local function tile_xy(tile)
        local x, y = tostring(tile):match("^(-?%d+),(-?%d+)$")
        return tonumber(x), tonumber(y)
    end
    -- parleys court() issues at an agent's faction's next turn start (court_due)
    local courts = {}
    -- Towns suite (games/qa/towns.toml): a settlement by name
    local function town_named(town)
        local s = gd.stratMap:getSettlement(town)
        if not s then error("unknown settlement '" .. tostring(town) .. "'") end
        return s
    end
    -- no garrison unit: ships and siege engines (as parley/steward.py's _NOT_GARRISON)
    local not_garrison = { "cog", "galley", "carrack", "longship", "dromon", "barge", "ship", "ballista",
                           "catapult", "trebuchet", "mangonel", "bombard", "cannon", "culverin", "serpentine",
                           "ribault", "basilisk" }
    -- every land unit the town's recruitment pools hold, whatever their stock, cheapest first:
    -- { name, cost, pool, edu } (EOP settlementRecruitmentPool, M2TWEOPDU.getEduEntry)
    local function garrison_pools(s)
        local list = {}
        for i = 0, (s.recruitmentPoolCount or 0) - 1 do
            local p = s:getSettlementRecruitmentPool(i)
            local e = p and M2TWEOPDU.getEduEntry(p.eduIndex)
            local name = e and e.eduType
            local land = name ~= nil
            for _, w in ipairs(not_garrison) do
                if land and name:lower():find(w, 1, true) then land = false end
            end
            if land then list[#list + 1] = { name = name, cost = e.recruitCost or 0, pool = p, edu = p.eduIndex } end
        end
        table.sort(list, function(a, b)
            if a.cost ~= b.cost then return a.cost < b.cost end
            return a.name < b.name
        end)
        return list
    end
    -- a town's governor flags (EOP aiProductionController): "build=<> recruit=<> all=<>"
    local function governor_flags(s)
        local pc = s.aiProductionController
        if not pc then error(tostring(s.name) .. " has no aiProductionController") end
        return string.format("build=%s recruit=%s all=%s", tostring(pc.isAutoManagedConstruction),
            tostring(pc.isAutoManagedRecruitment), tostring(pc.isAutoManaged))
    end
    -- a general with one unit (EOP factionStruct:spawnArmy, LuaDocs.lua:9437-9453; type 7 is
    -- characterType.named_character, :1042; the unit's index from M2TWEOPDU.getEduIndexByType,
    -- :7747). Returns the army's report id; on a settlement's tile that is its garrison's
    -- fleet: an admiral with a ship at sea (characterType.admiral; 3 in the game's type order,
    -- spy 0 .. admiral 3 .. named_character 7). Unproven live (siege suite, 10-31)
    local function spawn(fac, x, y, name, unit, fleet)
        local t = tile_at(x, y)
        if not t then error(string.format("(%s,%s) is off the map", tostring(x), tostring(y))) end
        if fleet and is_land(t) then error(string.format("(%d,%d) is land", x, y)) end
        if not fleet and not is_land(t) then error(string.format("(%d,%d) is sea", x, y)) end
        unit = unit or "NE Bodyguard"
        local idx = M2TWEOPDU.getEduIndexByType(unit)
        if type(idx) ~= "number" or idx < 0 then error("unknown unit type '" .. tostring(unit) .. "'") end
        local ctype = (characterType and characterType.named_character) or 7
        if fleet then ctype = (characterType and characterType.admiral) or 3 end
        -- the label must be a string: LuaDocs says "can be nil", but live (10-30, first field
        -- run) sol refused the call with nil, "no matching function call ... types". Labels
        -- can't be reused, so each spawn gets its own
        M.qa_label_n = (M.qa_label_n or 0) + 1
        local label = string.format("parley_qa_%d_%d", os.time(), M.qa_label_n)
        local army = fac:spawnArmy(name or "random_name", "", ctype, label, "", x, y, 30, false, 31, idx, 0, 0, 0)
        if not army then error("spawnArmy returned nil") end
        local g = leader_of(fac, army) or (fleet and army.leader)
        local rec = g and (g.characterRecord or g.namedCharacter)
        if not rec and not fleet then error("spawned army has no general") end
        -- a name the faction's list lacks is dropped, as with createCharacter
        if rec and (clean_name(rec.fullName) or "") == "" then pcall(function() rec:giveRandomName(fac.factionID) end) end
        -- the loyalty every general gets on coming of age, adoption or marriage (LoyaltyStarter,
        -- Loyalty 5, export_descr_character_traits.txt). Without it a spawned general stands at 0
        -- and goes over to the rebels (live 10-30 19:47-19:49: Edmund Awood and Walter Baker, a turn
        -- after spawning; the rebel left beside the next case's army stopped its move a tile short)
        if not fleet then rec:addTrait("LoyaltyStarter", 1) end
        local ids, id = army_ids(fac), nil
        for i = 0, (fac.stacksNum or 0) - 1 do
            if fac:getStack(i) == army then id = ids[i] end
        end
        if not id then  -- the game may hand back another struct for the same stack
            for i = 0, (fac.stacksNum or 0) - 1 do
                local sx, sy = stack_pos(fac, fac:getStack(i))
                if sx == x and sy == y then id = ids[i] end
            end
        end
        if (id or "") == "" then error("spawned army has no report id") end
        return id
    end
    -- an agent of agent_type (spy, diplomat, merchant, princess...) on (x, y), aged 30
    -- (factionStruct:createCharacter); returns his report id
    local function new_agent(fac, agent_type, x, y, name)
        local c = fac:createCharacter(agent_type, 30, name or "", "", 31, "", x, y)
        if not c then error("createCharacter returned nil") end
        local rec = c.characterRecord or c.namedCharacter or c
        -- live 10-30: the game drops a name that isn't in the faction's name list, and a
        -- nameless agent reports id '' (no order can reach it); give it one from the list
        -- (EOP characterRecord:giveRandomName(nameFactionId))
        if (clean_name(rec.fullName) or "") == "" then rec:giveRandomName(fac.factionID) end
        local cname = clean_name(rec.fullName)
        if (cname or "") == "" then error("spawned agent has no name") end
        -- the report's id: the clean name, numbered when another agent shares it (assign_ids)
        local id = cname
        for _, a in ipairs(agents_of(fac)) do
            if a.name == cname and a.char.xCoord == c.xCoord and a.char.yCoord == c.yCoord then
                id = a.id
            end
        end
        return id
    end
    return {
        -- a field army only: a town's tile puts the general into its garrison (that is garrison()'s
        -- job), and the case would then look for an army id that isn't there
        spawn_army = function(faction, x, y, name, unit)
            return run("spawn_army", function()
                local fac = faction_named(faction)
                if taken_tiles()[math.floor(x) * 1000 + math.floor(y)] then
                    for r = 0, (gd.stratMap.regionsNum or 0) - 1 do
                        local ok, s = pcall(function() return gd.stratMap.getRegion(r).settlement end)
                        if ok and s and s.xCoord == x and s.yCoord == y then
                            error(string.format("(%d,%d) is %s's tile: spawn beside it (free_tile)", x, y, tostring(s.name)))
                        end
                    end
                    -- someone stands there: the game puts the army on a tile beside it (QA field
                    -- 10-30/31: spawns landed a tile off when the tile was taken, and the case read
                    -- the wrong tile). Spawn on a free_tile
                    error(string.format("(%d,%d) is taken: spawn on a free tile (free_tile)", x, y))
                end
                local id = spawn(fac, x, y, name, unit)
                if tostring(id):match("^garrison:") then
                    error(string.format("the army spawned at (%d,%d) is inside a town (%s)", x, y, tostring(id)))
                end
                -- the landing tile is the one asked for, or the scene isn't the case's
                local st = find_army_now(fac, id)
                local ax, ay
                if st then ax, ay = stack_pos(fac, st) end
                if ax and ay and (math.floor(ax) ~= math.floor(x) or math.floor(ay) ~= math.floor(y)) then
                    error(string.format("the army %s landed at (%d,%d), not (%d,%d)", tostring(id), math.floor(ax), math.floor(ay), x, y))
                end
                return id
            end)
        end,
        -- a town's garrison led by a general, by its report id: the general already inside, or one
        -- spawned into it when nobody leads it (live 10-30 19:51: every English town had a general)
        garrison = function(faction, town)
            return run("garrison", function()
                local fac = faction_named(faction)
                local s = gd.stratMap:getSettlement(town)
                if not s then error("unknown settlement '" .. tostring(town) .. "'") end
                if not (s.ownerFaction and s.ownerFaction.name == fac.name) then
                    error(tostring(town) .. " is not " .. fac.name .. "'s")
                end
                local id = "garrison:" .. tostring(town)
                local st = find_army_now(fac, id)
                if st and leader_of(fac, st) then return id end
                return spawn(fac, s.xCoord, s.yCoord)
            end)
        end,
        -- the nearest settlement to (x, y) on the whole map held by the rebels or by a faction at
        -- war with this one: a march_on target that needn't be in sight (live 10-30 19:51: none was)
        hostile_town = function(faction, x, y)
            return run("hostile_town", function()
                local fac = faction_named(faction)
                local map, best, best_d = gd.stratMap, nil, nil
                for r = 0, (map.regionsNum or 0) - 1 do
                    pcall(function()
                        local s = map.getRegion(r).settlement
                        local owner = s and s.ownerFaction
                        if owner and owner.name ~= fac.name
                            and (owner.name == "slave" or stance(gd.campaignStruct, fac, owner) == "war") then
                            local d = math.max(math.abs(s.xCoord - x), math.abs(s.yCoord - y))
                            if not best_d or d < best_d or (d == best_d and tostring(s.name) < tostring(best.name)) then
                                best, best_d = s, d
                            end
                        end
                    end)
                end
                if not best then error(string.format("no rebel or enemy settlement on the map for %s", fac.name)) end
                return best.name
            end)
        end,
        -- the general leading an army (a garrison's: the one in the town), by the army's report id
        leader = function(faction, id)
            return run("leader", function()
                local fac = faction_named(faction)
                local st = find_army_now(fac, id)
                if not st then error("unknown army '" .. tostring(id) .. "'") end
                local c = leader_of(fac, st)
                if not c then error("army '" .. tostring(id) .. "' has no general") end
                return name_of(c)
            end)
        end,
        -- the first land tile near..far tiles (Chebyshev) from (x, y) with nobody and no settlement
        -- on it, walkable from (x, y) when that is land: "x,y"
        free_tile = function(x, y, near, far)
            return run("free_tile", function()
                near = near or 1
                far = far or near
                local tile = free_tile_near(x, y, near, far)
                if not tile then error(string.format("no free land tile %d-%d tiles from (%d,%d)", near, far, x, y)) end
                return tile
            end)
        end,
        -- free_tile, on a tile the faction sees now (M.in_sight): a victim spawned there shows in
        -- its sight lists. Live 10-30 22:03: the rebel victim Esau, on a free tile beside the
        -- assassin, never showed in England's, and the assassinate order went to the next nearest
        -- character, across the sea
        seen_tile = function(faction, x, y, near, far)
            return run("seen_tile", function()
                local fac = faction_named(faction)
                near = near or 1
                far = far or near
                local eyes = eyes_of(fac)
                local tile = free_tile_near(x, y, near, far, function(tx, ty)
                    return M.in_sight(fac, distance(eyes, tx, ty), tx, ty)
                end)
                if not tile then
                    error(string.format("no free land tile %s sees %d-%d tiles from (%d,%d)", fac.name, near, far, x, y))
                end
                return tile
            end)
        end,
        -- the sight id (as the faction's report lists it) of the foreign army or agent on (x, y);
        -- fails when the faction's sight lists hold nobody there
        sees = function(faction, x, y)
            return run("sees", function()
                local fac = faction_named(faction)
                local seen = M.sight(fac)
                for _, list in ipairs({ seen.armies, seen.agents }) do
                    for _, e in ipairs(list) do
                        local ok, here = pcall(function()
                            return math.floor(e.char.xCoord) == x and math.floor(e.char.yCoord) == y
                        end)
                        if ok and here then return e.view.id end
                    end
                end
                error(string.format("%s sees nobody at (%d,%d)", fac.name, x, y))
            end)
        end,
        -- the nearest settlement another faction holds that can't be walked to from (x, y)
        sea_town = function(faction, x, y)
            return run("sea_town", function()
                local fac = faction_named(faction)
                local from = tile_at(x, y)
                if not (from and is_land(from)) then error(string.format("(%d,%d) is not land", x, y)) end
                local map, list = gd.stratMap, {}
                for r = 0, (map.regionsNum or 0) - 1 do
                    pcall(function()
                        local s = map.getRegion(r).settlement
                        if s and s.ownerFaction and s.ownerFaction.name ~= fac.name then
                            list[#list + 1] = { s = s, d = math.max(math.abs(s.xCoord - x), math.abs(s.yCoord - y)) }
                        end
                    end)
                end
                table.sort(list, function(a, b)
                    if a.d ~= b.d then return a.d < b.d end
                    return tostring(a.s.name) < tostring(b.s.name)
                end)
                for _, e in ipairs(list) do
                    local t = tile_at(e.s.xCoord, e.s.yCoord)
                    if t and is_land(t) then
                        local ok, reach = pcall(land_reach, math.floor(x), math.floor(y), e.s.xCoord, e.s.yCoord)
                        if ok and reach == false then return e.s.name end
                    end
                end
                error(string.format("no foreign settlement across the sea from (%d,%d)", x, y))
            end)
        end,
        -- a settlement's tile: "x,y"
        town = function(name)
            return run("town", function()
                local s = gd.stratMap:getSettlement(name)
                if not s then error("unknown settlement '" .. tostring(name) .. "'") end
                return string.format("%d,%d", s.xCoord, s.yCoord)
            end)
        end,
        -- empty an army's moves now, and again at its faction's next `turns` turn starts (default 3)
        tire = function(faction, id, turns)
            return run("tire", function()
                local fac = faction_named(faction)
                local left = empty_moves(fac, id)
                tired[#tired + 1] = { faction = fac.name, id = id, left = turns or 3 }
                return string.format("%s moves=%s", tostring(id), tostring(left))
            end)
        end,
        -- on_turn_start, before the orders: the game has just refilled every mover's moves
        tire_due = function(fac)
            for i = #tired, 1, -1 do
                local e = tired[i]
                if e.faction == fac.name then
                    local ok, res = pcall(empty_moves, fac, e.id)
                    if ok then
                        log(string.format("qa: tired %s at turn start: moves=%s", tostring(e.id), tostring(res)))
                    else
                        log(string.format("qa: tire at turn start didn't take: %s: %s", tostring(e.id), tostring(res)))
                    end
                    e.left = e.left - 1
                    if e.left <= 0 or not ok then table.remove(tired, i) end
                end
            end
        end,
        -- a campaign load (the QA restore's) must never tire a real campaign's general of that name
        -- nor answer M.qa.last with an order given before the load (a bench reload between cases)
        forget = function() tired, courts, last_orders = {}, {}, {} end,
        spawn_agent = function(faction, agent_type, x, y, name)
            return run("spawn_agent", function()
                return new_agent(faction_named(faction), agent_type, x, y, name)
            end)
        end,
        teleport = function(name, x, y)
            return run("teleport", function()
                local c = find_char(name)
                -- refuse a tile EOP can't take: someone or a settlement on it, water, or unstandable.
                -- 11-04 10:12: smoke's teleport to a fixed tile crashed the game (crash dialog) after
                -- spawn_agent's played turn; a check here is a clean failure, never a native crash
                if not (math.floor(c.xCoord) == x and math.floor(c.yCoord) == y) then
                    local t = tile_at(x, y)
                    if not (t and is_land(t) and standable(t)) then
                        error(string.format("tile %d,%d isn't land a character can stand on", x, y))
                    end
                    if taken_tiles()[x * 1000 + y] then
                        error(string.format("tile %d,%d is taken (someone or a settlement is on it)", x, y))
                    end
                end
                c:teleport(x, y)
                return string.format("%d,%d", c.xCoord, c.yCoord)
            end)
        end,
        -- a faction with an unmarried princess of age and a suitor for her (`prefer` if it has both);
        -- ai_only: not the player's faction
        wooer = function(prefer, ai_only)
            return run("wooer", function()
                local first
                for i = 0, stratmap.game.getFactionsCount() - 1 do
                    local f = stratmap.game.getFaction(i)
                    if f and not (ai_only and f.isPlayerControlled == 1) and free_princess(f) and suitors_of(f)[1] then
                        if f.name == prefer then return f.name end
                        first = first or f.name
                    end
                end
                if not first then error("no faction has an unmarried princess of age with a suitor") end
                return first
            end)
        end,
        -- that faction's unmarried princess of age
        princess = function(faction)
            return run("princess", function()
                local c = free_princess(faction_named(faction))
                if not c then error(tostring(faction) .. " has no unmarried princess of age") end
                return clean_name((c.characterRecord or c.namedCharacter).fullName)
            end)
        end,
        -- a suitor for `faction`'s princess moved beside (x, y): the tile he stands on, "x,y"
        bachelor = function(faction, x, y)
            return run("bachelor", function()
                for _, c in ipairs(suitors_of(faction_named(faction))) do
                    local tx, ty = M.qa.free_tile(x, y, 1, 1):match("(%d+),(%d+)")
                    pcall(function() c:teleport(tonumber(tx), tonumber(ty)) end)
                    if math.max(math.abs(c.xCoord - x), math.abs(c.yCoord - y)) <= 1 then
                        return string.format("%d,%d", c.xCoord, c.yCoord)
                    end
                end
                error("no suitor for " .. tostring(faction) .. "'s princess could be moved beside " .. x .. "," .. y)
            end)
        end,
        skill = function(name, trait, level)
            return run("skill", function()
                local c = find_char(name)
                local rec = c.characterRecord or c.namedCharacter
                if not rec then error("no characterRecord for '" .. tostring(name) .. "'") end
                rec:addTrait(trait, level)
                return string.format("%s %s=%d", name_of(c) or tostring(name), tostring(trait), level)
            end)
        end,
        -- EOP's loadGame on a save that isn't there puts up a modal "ERROR: Cannot create M2TWEOP
        -- save file. 2" box that freezes the game until it is closed, and closing it ends the game
        -- (live 10-31: a load of the keep save the QA restore had just renamed). So the path, as the
        -- game sees it (relative to the game folder, the game's working directory), must open
        -- first. A refusal is no `qa: load failed:` line: the bench case load_missing_save_refused
        -- expects it as the result, and the runner's load waits know it (_LOAD_FAILED_RE).
        load = function(path)
            if type(path) == "string" and path ~= "" and not exists(path) then
                local why = "qa: load refused: no save at " .. path
                log(why)
                return why
            end
            return run("load", function()
                if type(path) ~= "string" or path == "" then error("load needs a path") end
                M2TWEOP.loadGame(path)
                return path
            end)
        end,
        -- QA bench: write `faction`'s report (the one on_turn_end writes) for `turn` (default: the
        -- turn before this one, as a real campaign has on its map) in the configured game's turn
        -- folder, which the runner made first. After loading the bench save nothing has reported
        -- yet, and the cases pick their targets from this report. Returns the file's path.
        report = function(faction, turn)
            return run("report", function()
                local cfg = config()
                if not cfg then error("no bridge config") end
                local fac = faction_named(faction)
                local t = tonumber(turn) or (gd.campaignStruct.turnNumber - 1)
                local path = turn_dir(cfg, t, fac.name) .. "/state.json"
                local done, werr = atomic_write(path, encode(M.report(fac, cfg)))
                if not done then error("cannot write " .. path .. ": " .. tostring(werr)) end
                return path
            end)
        end,
        where = function(name)
            return run("where", function()
                local c = find_char(name)
                return string.format("%d,%d", c.xCoord, c.yCoord)
            end)
        end,
        -- Instant cases (games/qa/instant.toml): setup, act and check in one held turn.
        -- whose turn it is: "<faction> <turn>" (the runner waits for its own faction's)
        current = function()
            local c = gd.campaignStruct
            return string.format("%s %d", tostring(c.currentFaction and c.currentFaction.name), c.turnNumber)
        end,
        -- M.walk, as an order's move calls it: "split from <town>", "moved", or "refused: <why>"
        walk = function(name, x, y)
            return run("walk", function()
                local c, fac = find_char(name)
                local town, why = M.walk(fac, c, x, y)
                if why then return "refused: " .. tostring(why) end
                if town then return "split from " .. tostring(town.name) end
                return "moved"
            end)
        end,
        -- Readiness canary (parley/qa/runner.py _await_ready): a general spawned 2-4 tiles from one
        -- of the faction's towns and walked one tile on through M.walk, as a move order walks one:
        -- "<army id>|x,y|tx,ty". Live 10-31 (phase1-run2): a bench load while the AI's turns were
        -- still playing out took 60-75 s, and for minutes after it move orders came back "ok" and
        -- nobody moved; the runner waits until a canary moves. A failure after the spawn removes
        -- the canary again. Unproven live (10-31)
        canary = function(faction)
            return run("canary", function()
                local fac = faction_named(faction)
                local map = gd.stratMap
                for r = 0, (map.regionsNum or 0) - 1 do
                    local ok, s = pcall(function() return map.getRegion(r).settlement end)
                    if ok and s and s.ownerFaction and s.ownerFaction.name == fac.name then
                        local ax, ay = tile_xy(free_tile_near(s.xCoord, s.yCoord, 2, 4) or "")
                        if ax then
                            local id = spawn(fac, ax, ay)
                            local done, res = pcall(function()
                                local st = find_army_now(fac, id)
                                local c = st and leader_of(fac, st)
                                if not c then error("the canary " .. tostring(id) .. " has no general") end
                                local tx, ty = tile_xy(free_tile_near(ax, ay, 1, 1) or "")
                                if not tx then error(string.format("no free tile beside the canary at (%d,%d)", ax, ay)) end
                                local _, why = M.walk(fac, c, tx, ty)
                                if why then error("the canary's walk was refused: " .. tostring(why)) end
                                return string.format("%s|%d,%d|%d,%d", id, ax, ay, tx, ty)
                            end)
                            if done then return res end
                            M.qa.canary_gone(faction, id)
                            error(res)
                        end
                    end
                end
                error("no free land tile 2-4 tiles from any of " .. fac.name .. "'s towns")
            end)
        end,
        -- the canary removed (EOP character:kill, then unit:kill for any unit left): "gone", or
        -- "left" when its army is still on the map. With check_only, only says which, killing nothing:
        -- live 10-31 14:33 the kill landed a moment after the call that made it, which still saw "left"
        canary_gone = function(faction, id, check_only)
            return run("canary_gone", function()
                local fac = faction_named(faction)
                local st = find_army_now(fac, id)
                if not st then return "gone" end
                if check_only then return "left" end
                local function kill(c) if c then pcall(function() c:kill() end) end end
                kill(leader_of(fac, st))
                if find_army_now(fac, id) then  -- by name too, as empty_moves finds a general
                    local okc, ch = pcall(in_faction, fac, id)
                    kill(okc and ch or nil)
                end
                st = find_army_now(fac, id)
                if st then
                    for i = (st.numOfUnits or 0) - 1, 0, -1 do
                        pcall(function() st:getUnit(i):kill() end)
                    end
                end
                return find_army_now(fac, id) and "left" or "gone"
            end)
        end,
        -- "x,y moves=<character's move points> town=<the own town he stands in, or ->"
        status = function(name)
            return run("status", function()
                local c, fac = find_char(name)
                local town = M.town_under(fac, c)
                return string.format("%d,%d moves=%s town=%s", math.floor(c.xCoord), math.floor(c.yCoord),
                    tostring(c.movePointsCharacter), town and tostring(town.name) or "-")
            end)
        end,
        -- tiles (Chebyshev) from a character to (x, y)
        dist = function(name, x, y)
            return run("dist", function()
                local c = find_char(name)
                return math.max(math.abs(math.floor(c.xCoord) - x), math.abs(math.floor(c.yCoord) - y))
            end)
        end,
        -- the tile M.walk would split a general in `town` onto, on his way to (x, y): "x,y"
        step_tile = function(town, x, y)
            return run("step_tile", function()
                local s = gd.stratMap:getSettlement(town)
                if not s then error("unknown settlement '" .. tostring(town) .. "'") end
                local sx, sy = step_out(s, x, y)
                if not sx then error("no free land tile beside " .. tostring(town)) end
                return string.format("%d,%d", sx, sy)
            end)
        end,
        -- an army (by report id) besieges a town from the next tile, as the besiege order does
        -- (armyStruct:siegeSettlement(town, false)); returns the town's siegesNum right after
        besiege = function(faction, id, town)
            return run("besiege", function()
                local fac = faction_named(faction)
                local st = find_army_now(fac, id)
                if not st then error("unknown army '" .. tostring(id) .. "'") end
                local s = gd.stratMap:getSettlement(town)
                if not s then error("unknown settlement '" .. tostring(town) .. "'") end
                st:siegeSettlement(s, false)
                return string.format("%s sieges=%s", tostring(s.name), tostring(s.siegesNum))
            end)
        end,
        -- how many sieges a town is under (settlementStruct.siegesNum)
        sieges = function(town)
            return run("sieges", function()
                local s = gd.stratMap:getSettlement(town)
                if not s then error("unknown settlement '" .. tostring(town) .. "'") end
                return s.siegesNum or 0
            end)
        end,
        -- Popups suite (games/qa/popups.toml). Nothing here looks up, scans or presses a papal
        -- scroll (K.PAPAL_SCROLLS): the papal helpers read and change the college of cardinals
        -- (EOP campaignStruct.collegeOfCardinals: pope, cardinalNum, inElection, getCardinal(i) ->
        -- { character, factionID }), never the screen.
        -- the Pope's name; an error when there is none (an election under way)
        pope = function()
            return run("pope", function()
                local college = college_now()
                local rec = college.pope
                if not rec then error("no pope" .. (college.inElection and " (an election is on)" or "")) end
                return clean_name(rec.fullName) or tostring(rec.fullName)
            end)
        end,
        -- The bench's quiet world, run after every bench load (runner _load_bench_save): the Pope
        -- dies of old age and his election opens scrolls that stall a turn (11-01, turn 50 for
        -- hours), so make him young. EOP collegeOfCardinals.pope is a characterRecord whose `age`
        -- (LuaDocs.lua characterRecord.age; not marked read only, unlike its neighbours) is
        -- written, then read back: an error when it didn't stick, so the runner refuses the load.
        -- Succession likewise: each seated faction's leader and heir (EOP factionStruct.leader /
        -- .heir, characterRecords) are kept young, so neither dies of old age into a succession
        -- scroll mid-case. A missing heir is reported, not made.
        -- "pope=<name> age=<before>-><after>" (or "pope=none" mid-election), then per seated
        -- faction "; <faction> leader=<name> age=a->b heir=<name> age=a->b" (or "heir=none").
        quiet = function(max_age)
            return run("quiet", function()
                local young = tonumber(max_age) or 45
                local function keep_young(rec, who)
                    local before = tonumber(rec.age) or -1
                    if before > young then rec.age = young end
                    local after = tonumber(rec.age) or -1
                    if after > young then
                        error(who .. "'s age stayed " .. tostring(after) .. " after setting " .. young)
                    end
                    return (clean_name(rec.fullName) or "?") .. " age=" .. before .. "->" .. after
                end
                local college = college_now()
                local out
                if college.pope then
                    out = "pope=" .. keep_young(college.pope, "the Pope")
                else
                    out = "pope=none" .. (college.inElection and " (election on)" or "")
                end
                local cfg = config()
                local names = {}
                for name in pairs(cfg and cfg.factions or {}) do names[#names + 1] = name end
                table.sort(names)
                for _, name in ipairs(names) do
                    local fac = faction_named(name)
                    local part = "; " .. name .. " leader="
                    part = part .. (fac.leader and keep_young(fac.leader, name .. "'s leader") or "none")
                    part = part .. " heir=" .. (fac.heir and keep_young(fac.heir, name .. "'s heir") or "none")
                    -- rebellion and plague (games/interrupts.toml): each of its towns' turmoil and
                    -- rebel-faction chance set to 0 and any plague cleared (EOP settlementStruct
                    -- turmoil / rebelFactionChance setters, plagued / plagueDuration fields; all
                    -- kept in the save, so the restore's load puts the real campaign's back)
                    local calmed, cured, towns = 0, 0, fac.settlementsNum or 0
                    for i = 0, towns - 1 do
                        local s = fac:getSettlement(i)
                        if (s.turmoil or 0) ~= 0 or (s.rebelFactionChance or 0) ~= 0 then
                            s.turmoil, s.rebelFactionChance = 0, 0
                            if (s.turmoil or 0) ~= 0 or (s.rebelFactionChance or 0) ~= 0 then
                                error(name .. "'s " .. tostring(s.name) .. " kept turmoil " .. tostring(s.turmoil)
                                    .. " rebel chance " .. tostring(s.rebelFactionChance))
                            end
                            calmed = calmed + 1
                        end
                        if s.plagued then
                            s.plagued, s.plagueDuration = false, 0
                            if s.plagued then error(name .. "'s " .. tostring(s.name) .. " stayed plagued") end
                            cured = cured + 1
                        end
                    end
                    part = part .. " towns=" .. towns .. " calmed=" .. calmed .. " cured=" .. cured
                    out = out .. part
                end
                return out
            end)
        end,
        -- how many cardinals the faction has in the college (its votes in an election)
        cardinals = function(faction)
            return run("cardinals", function()
                return #cardinals_of(faction_named(faction))
            end)
        end,
        -- a vote for the faction: a cardinal of its own (his name), else another faction's (not the
        -- Pope) moved over by EOP character:switchFaction, the game's own switch as a bribe uses;
        -- the college entry is set to the faction too if the switch left it. An error unless the
        -- college then counts one of the faction's.
        give_cardinal = function(faction)
            return run("give_cardinal", function()
                local fac = faction_named(faction)
                local own, college = cardinals_of(fac)
                if #own > 0 then return card_name(own[1]) .. " (already " .. tostring(faction) .. "'s)" end
                local pope = college.pope and clean_name(college.pope.fullName)
                for i = 0, (college.cardinalNum or 0) - 1 do
                    local card = college:getCardinal(i)
                    local c = card and card.character
                    local name = card and card_name(card)
                    if c and card.factionID ~= fac.factionID and name ~= pope then
                        c:switchFaction(fac, false, false)
                        -- looked up again: the switch may have rebuilt the college's entries
                        for j = 0, (college.cardinalNum or 0) - 1 do
                            local again = college:getCardinal(j)
                            if again and card_name(again) == name and again.factionID ~= fac.factionID then
                                again.factionID = fac.factionID
                            end
                        end
                        if #cardinals_of(fac) == 0 then
                            error("moved " .. name .. " to " .. tostring(faction) .. ", but the college counts none of its")
                        end
                        return name
                    end
                end
                error("no cardinal to give " .. tostring(faction) .. " (the college has " .. tostring(college.cardinalNum) .. ")")
            end)
        end,
        -- no vote for the faction: each of its cardinals killed (EOP character:kill, the game's own
        -- death, natural); "<n> killed: <names>; the college counts <m> now"
        drop_cardinals = function(faction)
            return run("drop_cardinals", function()
                local fac = faction_named(faction)
                local own = cardinals_of(fac)
                local chars, names = {}, {}
                for _, card in ipairs(own) do  -- all found before any dies: a death may reorder them
                    local c = card.character
                    if not c then error("a cardinal of " .. tostring(faction) .. " is not on the map") end
                    chars[#chars + 1], names[#names + 1] = c, card_name(card)
                end
                for _, c in ipairs(chars) do c:kill() end
                return string.format("%d killed: %s; the college counts %d now", #chars,
                    #names > 0 and table.concat(names, ", ") or "-", #cardinals_of(fac))
            end)
        end,
        -- the Pope dies (EOP character:kill: the game's own death, as natural): the death notice
        -- (message 202) and the election are the game's from here; his name
        kill_pope = function()
            return run("kill_pope", function()
                local college = college_now()
                if college.inElection then error("an election is already on") end
                local rec = college.pope
                if not rec then error("no pope") end
                local name = clean_name(rec.fullName) or tostring(rec.fullName)
                local c = rec.character
                if not c then error("the Pope " .. name .. " is not on the map") end
                c:kill()
                return name
            end)
        end,
        -- a historic event's message scroll (campaign script command historic_event <name>, as the
        -- campaign script raises america_discovered; names from descr_events.txt)
        event = function(name)
            return run("event", function()
                if type(name) ~= "string" or not name:match("^[%w_]+$") then error("event needs a historic event's name") end
                stratmap.game.scriptCommand("historic_event", name)
                return name
            end)
        end,
        -- press a named UI button as the bridge does (click: execute, else the scripted click), e.g.
        -- faction_button to open the faction overview; never a papal element
        press = function(element)
            return run("press", function()
                if type(element) ~= "string" or element == "" then error("press needs a UI element's name") end
                if element:find("papal", 1, true) then error("papal elements are never pressed") end
                click(element)
                return element
            end)
        end,
        -- Siege suite (games/qa/siege.toml). One order, as a ruler's orders.json gives it, through
        -- the same apply() the turn start runs: "<type> ok", "<type> ok: <note>", "<type> refused:
        -- <reason>" or "<type> error: <Lua error>". A refused move is dropped from the next turn
        -- start's move check, as apply_orders drops it. The army isn't marked ordered (keep_sieges
        -- still keeps a siege it ordered: a case may call keep_sieges after it)
        order = function(faction, o)
            return run("order", function()
                local fac = faction_named(faction)
                if type(o) ~= "table" or type(o.type) ~= "string" then error("order needs a table with a type") end
                local cfg = config()
                if not cfg then error("no bridge config") end
                local moves = recorded_moves[fac.name]
                local before = moves and #moves or 0
                local ok, res = pcall(apply, fac, o, cfg)
                local text
                if not ok then
                    text = o.type .. " error: " .. tostring(res)
                elseif type(res) == "table" and res.note then
                    text = o.type .. " ok: " .. tostring(res.note)
                elseif res ~= nil then
                    text = o.type .. " refused: " .. tostring(res)
                else
                    text = o.type .. " ok"
                end
                local after = recorded_moves[fac.name]
                if after and not text:match("^%S+ ok") then
                    while #after > before do table.remove(after) end
                end
                last_orders[o.type], last_orders[1] = text, text
                return text
            end)
        end,
        -- what the last M.qa.order of this type (any type when nil) said, or "none"
        last = function(otype)
            return last_orders[otype or 1] or "none"
        end,
        -- an army's siege as its report shows it (army_view, can_assault), or "gone" when the
        -- faction has no army by that id now (it died in an assault, or took the town and is its
        -- garrison): "besieging=<town or -> turns=<n> queue=<n> holdout=<n> can_assault=<bool>"
        siege = function(faction, id)
            return run("siege", function()
                local fac = faction_named(faction)
                local st = find_army_now(fac, id)
                if not st then return "gone" end
                local view = army_view(st, id, fac)
                M.add_can_assault(view, st)
                return string.format("besieging=%s turns=%s queue=%s holdout=%s can_assault=%s",
                    tostring(view.besieging or "-"), tostring(view.siege_turns), tostring(view.siege_queue),
                    tostring(view.holdout_turns), tostring(view.can_assault))
            end)
        end,
        -- the turn start's siege keeping (#235: equipment queued) for a faction, now
        keep_sieges = function(faction)
            return run("keep_sieges", function()
                M.keep_sieges(faction_named(faction))
                return "kept"
            end)
        end,
        -- an own town's siege as its report shows it (M.add_siege), or "none":
        -- "by=<general> faction=<f> turns=<n> holdout=<n> units=<n>"
        town_siege = function(town)
            return run("town_siege", function()
                local s = gd.stratMap:getSettlement(town)
                if not s then error("unknown settlement '" .. tostring(town) .. "'") end
                local view = {}
                M.add_siege(view, s)
                local v = view.siege
                if not v then return "none" end
                return string.format("by=%s faction=%s turns=%s holdout=%s units=%s", tostring(v.by),
                    tostring(v.faction), tostring(v.turns), tostring(v.holdout), tostring(v.units))
            end)
        end,
        -- the town besieged by a rebel army: the siege it is under already (its besieger's tile),
        -- else a rebel army of `unit` (Peasants: a siege needs infantry) spawned on a free tile
        -- beside it and set besieging it. Returns the besieger's tile "x,y". The game may show the
        -- siege a little later: a case polls M.qa.sieges after this
        besieged = function(town, unit)
            return run("besieged", function()
                local s = gd.stratMap:getSettlement(town)
                if not s then error("unknown settlement '" .. tostring(town) .. "'") end
                if (s.siegesNum or 0) > 0 then
                    local b = s:getSiege(0).besieger
                    return string.format("%d,%d", math.floor(b.leader.xCoord), math.floor(b.leader.yCoord))
                end
                local slave = faction_named("slave")
                local tile = free_tile_near(s.xCoord, s.yCoord, 1, 1)
                if not tile then error("no free land tile beside " .. tostring(town)) end
                local x, y = tile_xy(tile)
                local id = spawn(slave, x, y, nil, unit or "Peasants")
                local st = find_army_now(slave, id)
                if not st then error("the rebel army '" .. tostring(id) .. "' can't be found") end
                st:siegeSettlement(s, false)
                return tile
            end)
        end,
        -- the nearest other own town a town's garrison could walk to (over land, more than a tile
        -- off, with room for the garrison): a march_on / withdraw target, or "none"
        road_town = function(faction, town)
            return run("road_town", function()
                local fac = faction_named(faction)
                local s = gd.stratMap:getSettlement(town)
                if not s then error("unknown settlement '" .. tostring(town) .. "'") end
                local coming = (s.army and s.army.numOfUnits) or 0
                local best, best_d
                for i = 0, (fac.settlementsNum or 0) - 1 do
                    pcall(function()
                        local t = fac:getSettlement(i)
                        if not t or t.name == s.name then return end
                        local d = math.max(math.abs(t.xCoord - s.xCoord), math.abs(t.yCoord - s.yCoord))
                        if d <= 1 or ((t.army and t.army.numOfUnits) or 0) + coming > 20 then return end
                        local ok, reach = pcall(land_reach, math.floor(s.xCoord), math.floor(s.yCoord), t.xCoord, t.yCoord)
                        if not (ok and reach == true) then return end
                        if not best_d or d < best_d then best, best_d = t, d end
                    end)
                end
                return best and best.name or "none"
            end)
        end,
        -- a sea tile near..far tiles from a town with no one on it, "x,y", or "none" (an inland town)
        coast = function(town, near, far)
            return run("coast", function()
                local s = gd.stratMap:getSettlement(town)
                if not s then error("unknown settlement '" .. tostring(town) .. "'") end
                local taken, x, y = taken_tiles(), math.floor(s.xCoord), math.floor(s.yCoord)
                for r = near or 1, far or 6 do
                    for dx = -r, r do
                        for dy = -r, r do
                            local tx, ty = x + dx, y + dy
                            local t = math.max(math.abs(dx), math.abs(dy)) == r and tile_at(tx, ty)
                            if t and not is_land(t) and not taken[tx * 1000 + ty] then
                                return string.format("%d,%d", tx, ty)
                            end
                        end
                    end
                end
                return "none"
            end)
        end,
        -- an admiral with one ship (`unit`, default "cog": England's first ship) on a sea tile;
        -- returns the fleet's report id
        spawn_fleet = function(faction, x, y, unit)
            return run("spawn_fleet", function()
                return spawn(faction_named(faction), x, y, nil, unit or "cog", true)
            end)
        end,
        -- Diplomacy suite (games/qa/diplomacy.toml). Its orders go through M.qa.order above.
        -- a faction to deal with: alive, not the rebels or the Pope, no seat of its own (a seated
        -- AI's stance change nobody ordered is put back at its turn end, log_stance_changes), not a
        -- player's; those at peace with `faction` first, then by name. n (default 1) picks the n-th.
        -- same_religion: only factions of `faction`'s religion (live 10-31 17:13: England's princess
        -- proposed to the Aztecs' general, religion 3 to England's 0, and the game ran no mission)
        rival = function(faction, n, same_religion)
            return run("rival", function()
                local fac = faction_named(faction)
                local cfg = config()
                local list = {}
                for i = 0, stratmap.game.getFactionsCount() - 1 do
                    local f = stratmap.game.getFaction(i)
                    if f and f.name ~= fac.name and f.name ~= "slave" and f.name ~= "papal_states"
                        and (f.settlementsNum or 0) > 0 and f.isPlayerControlled ~= 1
                        and not (cfg and cfg.factions[f.name])
                        and (not same_religion or f.religion == fac.religion) then
                        list[#list + 1] = { f = f, peace = stance(gd.campaignStruct, fac, f) == "peace" }
                    end
                end
                table.sort(list, function(a, b)
                    if a.peace ~= b.peace then return a.peace end
                    return a.f.name < b.f.name
                end)
                local e = list[n or 1]
                if not e then error(string.format("no rival #%d for %s among %d", n or 1, fac.name, #list)) end
                return e.f.name
            end)
        end,
        -- the stance between two factions ("war", "peace", "alliance"); with `set`, set first, straight
        -- through campaignStruct:setDipStance (a scene, not an order: no stance_orders record)
        stance = function(a, b, set)
            return run("stance", function()
                local fa, fb = faction_named(a), faction_named(b)
                if set ~= nil then
                    local rel = dipRelType[set]
                    if rel == nil then error("unknown stance '" .. tostring(set) .. "'") end
                    gd.campaignStruct:setDipStance(rel, fa, fb)
                end
                return stance(gd.campaignStruct, fa, fb)
            end)
        end,
        -- a faction's treasury (factionStruct.money); with `set`, set first and read back (the towns
        -- suite's "not enough money" cases: 0, then back), so a write that doesn't take fails
        money = function(faction, set)
            return run("money", function()
                local fac = faction_named(faction)
                if set ~= nil then
                    fac.money = set
                    if fac.money ~= set then error("money still " .. tostring(fac.money) .. " after setting " .. tostring(set)) end
                end
                return fac.money
            end)
        end,
        -- who holds a settlement
        owner = function(town)
            return run("owner", function()
                local s = gd.stratMap:getSettlement(town)
                if not s then error("unknown settlement '" .. tostring(town) .. "'") end
                return s.ownerFaction and s.ownerFaction.name or "-"
            end)
        end,
        -- an own settlement to give away: not `keep`, not the capital, the last such in the list;
        -- fails when that would leave the faction with none
        spare_town = function(faction, keep)
            return run("spare_town", function()
                local fac = faction_named(faction)
                local okc, capital = pcall(function() return fac.capital and fac.capital.name end)
                capital = okc and capital or nil
                local pick
                for i = 0, (fac.settlementsNum or 0) - 1 do
                    local s = fac:getSettlement(i)
                    if s and s.name ~= keep and s.name ~= capital then pick = s end
                end
                if not pick or (fac.settlementsNum or 0) < 2 then
                    error(string.format("%s has no settlement to spare (%d, keeping %s and the capital %s)",
                        fac.name, fac.settlementsNum or 0, tostring(keep), tostring(capital)))
                end
                return pick.name
            end)
        end,
        -- the faction's settlement nearest (x, y), by name
        town_of = function(faction, x, y)
            return run("town_of", function()
                local fac = faction_named(faction)
                local best, best_d
                for i = 0, (fac.settlementsNum or 0) - 1 do
                    local s = fac:getSettlement(i)
                    if s then
                        local d = math.max(math.abs(s.xCoord - x), math.abs(s.yCoord - y))
                        if not best_d or d < best_d then best, best_d = s, d end
                    end
                end
                if not best then error(fac.name .. " holds no settlement") end
                return best.name
            end)
        end,
        -- "open" or "closed": a UI element by name (never a papal scroll: looking one up hung the game)
        screen = function(name)
            return run("screen", function()
                if tostring(name):find("papal", 1, true) then error("papal scrolls are never looked up") end
                if not (gameSTDUI and gameSTDUI.getUiElement) then error("no game UI (gameSTDUI)") end
                return open(name) and "open" or "closed"
            end)
        end,
        -- an agent (any faction's, by report id or name) does diplomacy with a settlement (by name)
        -- or a character: EOP character:diplomacySettlement / diplomacyCharacter (LuaDocs 3.3.1
        -- :1233, :1271). An AI faction's envoy parleying the human's town is how the game's AI makes
        -- its offers (JOURNAL: HRE's diplomat made one during HRE's turn); whether the command alone
        -- brings one up is for the live run to show
        parley = function(agent, target)
            return run("parley", function()
                local c, fac = find_char(agent)
                local s = gd.stratMap:getSettlement(target)
                if s then
                    c:diplomacySettlement(s)
                else
                    c:diplomacyCharacter((find_char(target)))
                end
                return string.format("%s of %s parleys with %s", tostring(agent), tostring(fac and fac.name), tostring(target))
            end)
        end,
        -- the same parley, issued at the agent's faction's next turn start (court_due): the AI's offer
        -- made on its own turn, as the game makes them
        court = function(agent, target)
            return run("court", function()
                local _, fac = find_char(agent)
                courts[#courts + 1] = { faction = fac.name, agent = agent, target = target }
                return string.format("%s of %s parleys with %s at %s's next turn start", tostring(agent), fac.name,
                    tostring(target), fac.name)
            end)
        end,
        court_due = function(fac)
            for i = #courts, 1, -1 do
                local e = courts[i]
                if e.faction == fac.name then
                    table.remove(courts, i)
                    local ok, res = pcall(function()
                        local c = find_char(e.agent)
                        local s = gd.stratMap:getSettlement(e.target)
                        if s then c:diplomacySettlement(s) else c:diplomacyCharacter((find_char(e.target))) end
                    end)
                    log(string.format("qa: court: %s parleys with %s at %s's turn start%s", tostring(e.agent),
                        tostring(e.target), fac.name, ok and "" or (" failed: " .. tostring(res))))
                end
            end
        end,
        -- One step of the bridge's own offer handling (watch_buttons, close_leftover_diplomacy), for a
        -- held turn: tick() skips both while paused.txt is up, and resets every popup wait each tick,
        -- so the step is taken as K.POPUP_DELAY after that reset (the close round's own pacing, by
        -- leftover.since/last, still runs on the real clock). With `answer`, an offer the bridge has
        -- put to the ruler and nobody answered gets it, written where parley/popups.py writes the
        -- ruler's (popup-<id>.answer). "screen=<open|closed> offer=<yes|no> asking=<yes|no>
        -- answered=<yes|no>": offer buttons on screen, a question with the ruler, an offer pressed.
        diplomacy_step = function(answer)
            return run("diplomacy_step", function()
                if not (gameSTDUI and gameSTDUI.getUiElement) then error("no game UI (gameSTDUI)") end
                if answer ~= nil then
                    for _, c in pairs(choosing) do
                        local path = c.request .. ".answer"
                        if not read_file(path) then atomic_write(path, tostring(answer) .. " (the QA bench's scripted ruler)\n") end
                    end
                end
                local now = M.clock() + K.POPUP_DELAY
                watch_buttons(now)
                close_leftover_diplomacy(now)
                -- closed by that: forget the screen now, as the next tick would (the next case's
                -- steps must not start from this one's answered offer)
                if not open("diplomacy_scroll") then
                    watch_buttons(now)
                    close_leftover_diplomacy(now)
                end
                local offer = false
                for _, b in ipairs(K.OFFER_BUTTONS) do offer = offer or open(b) end
                return string.format("screen=%s offer=%s asking=%s answered=%s",
                    open("diplomacy_scroll") and "open" or "closed", offer and "yes" or "no",
                    next(choosing) and "yes" or "no", offer_answered and "yes" or "no")
            end)
        end,
        -- Towns suite (games/qa/towns.toml). Its orders go through M.qa.order above.
        -- the buildings a town can queue now, as its report's can_build lists them (no repairs):
        -- "<name>:<cost>:<turns>" "," apart, or "none"
        can_build = function(town)
            return run("can_build", function()
                local out = {}
                for _, o in ipairs(construction_options(town_named(town))) do
                    if o.type ~= K.REPAIR_TYPE and o.name then
                        out[#out + 1] = string.format("%s:%s:%s", o.name, tostring(o.cost), tostring(o.turns))
                    end
                end
                return #out > 0 and table.concat(out, ",") or "none"
            end)
        end,
        -- the quickest building on the town's can_build list (then the cheapest), by name; with
        -- `max_turns`, an error when even the quickest takes longer
        buildable = function(town, max_turns)
            return run("buildable", function()
                local best
                for _, o in ipairs(construction_options(town_named(town))) do
                    if o.type ~= K.REPAIR_TYPE and o.name then
                        local t, bt = o.turns or 99, best and (best.turns or 99)
                        if not best or t < bt or (t == bt and (o.cost or 0) < (best.cost or 0)) then best = o end
                    end
                end
                if not best then error(tostring(town) .. " can build nothing now") end
                if max_turns and (best.turns or 99) > max_turns then
                    error(string.format("%s's quickest building, %s, takes %s turns (more than %d)", tostring(town),
                        best.name, tostring(best.turns), max_turns))
                end
                return best.name
            end)
        end,
        -- what an option costs in the town: kind "build" (default) or "repair" by building level name,
        -- "recruit" by unit (its recruit cost, whatever the pool's stock)
        cost = function(town, name, kind)
            return run("cost", function()
                local s = town_named(town)
                if kind == "recruit" then
                    for i = 0, (s.recruitmentPoolCount or 0) - 1 do
                        local p = s:getSettlementRecruitmentPool(i)
                        local e = p and M2TWEOPDU.getEduEntry(p.eduIndex)
                        if e and e.eduType == name then return e.recruitCost end
                    end
                    error(tostring(town) .. " has no recruitment pool of '" .. tostring(name) .. "'")
                end
                local repair = kind == "repair"
                for _, o in ipairs(construction_options(s)) do
                    if o.name == name and (o.type == K.REPAIR_TYPE) == repair then return o.cost end
                end
                error(string.format("%s has no %s option '%s'", tostring(town), repair and "repair" or "build", tostring(name)))
            end)
        end,
        -- how many items the town's construction queue holds (EOP buildingsQueue.numBuildingsInQueue)
        build_queue = function(town)
            return run("build_queue", function()
                local q = town_named(town).buildingsQueue
                return q and q.numBuildingsInQueue or 0
            end)
        end,
        -- an own town (not `keep`) with an empty construction queue and something on its can_build list
        idle_town = function(faction, keep)
            return run("idle_town", function()
                local fac = faction_named(faction)
                for i = 0, (fac.settlementsNum or 0) - 1 do
                    local s = fac:getSettlement(i)
                    local q = s and s.buildingsQueue
                    if s and s.name ~= keep and (q and q.numBuildingsInQueue or 0) == 0 then
                        for _, o in ipairs(construction_options(s)) do
                            if o.type ~= K.REPAIR_TYPE and o.name then return s.name end
                        end
                    end
                end
                error(fac.name .. " has no town with an empty construction queue and something to build")
            end)
        end,
        -- a building in the town set to `hp` percent (default 50; 100 mends it): the level `name`, else
        -- the first that isn't of the core_building chain (walls). EOP building.hp, read back; the
        -- building's level name
        damage = function(town, name, hp)
            return run("damage", function()
                local s = town_named(town)
                hp = hp or 50
                for b = 0, (s.buildingsNum or 0) - 1 do
                    local bld = s:getBuilding(b)
                    local okn, lvl = pcall(function() return bld:getName() end)
                    local okt, chain = pcall(function() return bld:getType() end)
                    if bld and okn and (lvl == name or (name == nil and not (okt and chain == "core_building"))) then
                        bld.hp = hp
                        if bld.hp ~= hp then error(string.format("%s's hp still %s after setting %d", lvl, tostring(bld.hp), hp)) end
                        -- EOP caches a town's construction options by (buildings + queue hash, turn)
                        -- (settlement.cpp getBuildingOptions); hp is in neither, so the cached list keeps
                        -- or lacks the repair until next turn. Live 11-01: a damaged town offered no repair
                        -- until the turn moved. Rebuild under the next turn's key, then once more as now.
                        local campaign = gd.campaignStruct
                        local t = campaign.turnNumber
                        campaign.turnNumber = t + 1
                        local okc, cerr = pcall(function() return s:getConstructionOptions() end)
                        campaign.turnNumber = t
                        if not okc then error("construction options after damage: " .. tostring(cerr)) end
                        s:getConstructionOptions()
                        return lvl
                    end
                end
                error(string.format("%s has no building %s", tostring(town), name and ("'" .. name .. "'") or "outside the core chain"))
            end)
        end,
        -- the repairs the town can queue now (construction options of the repair type), "," apart, or "none"
        repairable = function(town)
            return run("repairable", function()
                local out = {}
                for _, o in ipairs(construction_options(town_named(town))) do
                    if o.type == K.REPAIR_TYPE and o.name then out[#out + 1] = o.name end
                end
                return #out > 0 and table.concat(out, ",") or "none"
            end)
        end,
        -- the cheapest land unit the town's pools hold, its pool stocked to at least `n` (default 2;
        -- EOP settlementRecruitmentPool.availablePool, as the recruit order itself writes it): its name
        recruitable = function(town, n)
            return run("recruitable", function()
                local e = garrison_pools(town_named(town))[1]
                if not e then error(tostring(town) .. "'s recruitment pools hold no land unit") end
                n = n or 2
                if (e.pool.availablePool or 0) < n then e.pool.availablePool = n end
                if (e.pool.availablePool or 0) < n then error(e.name .. "'s pool still " .. tostring(e.pool.availablePool)) end
                return e.name
            end)
        end,
        -- the town's pool stock of a unit (availablePool)
        pool = function(town, unit)
            return run("pool", function()
                local s = town_named(town)
                for i = 0, (s.recruitmentPoolCount or 0) - 1 do
                    local p = s:getSettlementRecruitmentPool(i)
                    local e = p and M2TWEOPDU.getEduEntry(p.eduIndex)
                    if e and e.eduType == unit then return p.availablePool end
                end
                error(tostring(town) .. " has no recruitment pool of '" .. tostring(unit) .. "'")
            end)
        end,
        -- how many recruits (units, agents, retrains) the bridge holds for the town (training.json)
        training = function(town)
            return run("training", function()
                local n = 0
                for _, t in ipairs(read_training()) do if t.settlement == town then n = n + 1 end end
                return n
            end)
        end,
        -- the turn the town's newest recruit of that unit joins (training.json), or "none"
        ready = function(town, unit)
            return run("ready", function()
                local at = "none"
                for _, t in ipairs(read_training()) do
                    if t.settlement == town and t.unit == unit then at = t.ready end
                end
                return at
            end)
        end,
        -- the town's recruitment queue filled to K.QUEUE_MAX with QA placeholders (due 1000 turns on:
        -- never delivered) or, with `clear`, rid of them again: how many the faction has waiting there
        fill_queue = function(faction, town, clear)
            return run("fill_queue", function()
                local fac, s = faction_named(faction), town_named(town)
                local list, n = read_training(), 0
                if clear then
                    local keep = {}
                    for _, t in ipairs(list) do
                        if not (t.qa_filler and t.settlement == s.name) then keep[#keep + 1] = t end
                    end
                    list = keep
                else
                    for _, t in ipairs(list) do
                        if t.faction == fac.name and t.settlement == s.name then n = n + 1 end
                    end
                    for _ = n + 1, K.QUEUE_MAX do
                        list[#list + 1] = { faction = fac.name, settlement = s.name, unit = "QA placeholder", qa_filler = true,
                                            ready = gd.campaignStruct.turnNumber + 1000 }
                    end
                end
                atomic_write(training_path(), encode(list))
                n = 0
                for _, t in ipairs(read_training()) do
                    if t.faction == fac.name and t.settlement == s.name then n = n + 1 end
                end
                return n
            end)
        end,
        -- a garrison unit of the cheapest land type the town's pools hold (stocked to 2 so a retrain
        -- may take one), worn to a tenth of its men: the most worn in the garrison, first in line for
        -- the retrain. Made in the garrison first when none is there (armyStruct:createUnitByIDX). Its type
        worn = function(faction, town)
            return run("worn", function()
                local fac, s = faction_named(faction), town_named(town)
                if not (s.ownerFaction and s.ownerFaction.name == fac.name) then error(tostring(town) .. " is not " .. fac.name .. "'s") end
                local e = garrison_pools(s)[1]
                if not e then error(tostring(town) .. "'s recruitment pools hold no land unit") end
                if (e.pool.availablePool or 0) < 2 then e.pool.availablePool = 2 end
                local army = s.army or stratmap.game.createArmyInSettlement(s)
                if not army then error(tostring(town) .. " has no garrison") end
                local unit
                for i = 0, (army.numOfUnits or 0) - 1 do
                    local u = army:getUnit(i)
                    if u and u.eduEntry and u.eduEntry.eduType == e.name then unit = u break end
                end
                unit = unit or army:createUnitByIDX(e.edu, 0, 0, 0)
                if not unit then error("createUnitByIDX made no " .. e.name .. " in " .. tostring(town)) end
                local have = math.max(1, math.floor((unit.soldierCountStratMapMax or 10) / 10))
                unit.soldierCountStratMap = have
                if unit.soldierCountStratMap ~= have then error(e.name .. "'s men still " .. tostring(unit.soldierCountStratMap)) end
                return e.name
            end)
        end,
        -- the most worn unit of that type in the town's garrison: "<men>/<max>", or "none"
        men = function(town, unit)
            return run("men", function()
                local army, best = town_named(town).army, nil
                for i = 0, (army and army.numOfUnits or 0) - 1 do
                    local u = army:getUnit(i)
                    if u and u.eduEntry and u.eduEntry.eduType == unit
                        and (not best or u.soldierCountStratMap < best.soldierCountStratMap) then best = u end
                end
                if not best then return "none" end
                return string.format("%d/%d", best.soldierCountStratMap, best.soldierCountStratMapMax)
            end)
        end,
        -- the town's tax level as the report names it (K.TAX_NAMES); with `set`, set first (a scene,
        -- not an order: settlementTaxLevel by K.TAX_LEVELS)
        tax = function(town, set)
            return run("tax", function()
                local s = town_named(town)
                if set ~= nil then
                    local lvl = K.TAX_LEVELS[set]
                    if lvl == nil then error("unknown tax level '" .. tostring(set) .. "'") end
                    s.settlementTaxLevel = lvl
                end
                return K.TAX_NAMES[s.settlementTaxLevel] or tostring(s.settlementTaxLevel)
            end)
        end,
        -- the town's governor flags, "build=<> recruit=<> all=<>"; with `set` (true: governed), all
        -- three set first, as EOP types them (booleans on master; numbers on 3.3.1 when that fails)
        automanage = function(town, set)
            return run("automanage", function()
                local s = town_named(town)
                local pc = s.aiProductionController
                if not pc then error(tostring(town) .. " has no aiProductionController") end
                if set ~= nil then
                    for _, k in ipairs({ "isAutoManagedConstruction", "isAutoManagedRecruitment", "isAutoManaged" }) do
                        if not pcall(function() pc[k] = set end) then pc[k] = set and 1 or 0 end
                    end
                end
                return governor_flags(s)
            end)
        end,
        -- M.set_governors for the faction as the turn start runs it, with its configured control areas
        -- or `areas` ("build,recruit,..."): the town's flags after
        governors = function(faction, town, areas)
            return run("governors", function()
                local fac, a = faction_named(faction), {}
                if areas then
                    for w in tostring(areas):gmatch("[%w_]+") do a[w] = true end
                else
                    local cfg = config()
                    if not cfg then error("no bridge config") end
                    a = areas_of(cfg, fac.name)
                end
                M.set_governors(fac, a)
                return governor_flags(town_named(town))
            end)
        end,
        -- an own town (not `keep`, not the capital, not besieged, no general inside) with its garrison
        -- disbanded (EOP unit:kill, each unit): the town's name. The steward's case: a town left empty
        empty_garrison = function(faction, keep)
            return run("empty_garrison", function()
                local fac = faction_named(faction)
                local okc, capital = pcall(function() return fac.capital and fac.capital.name end)
                capital = okc and capital or nil
                for i = 0, (fac.settlementsNum or 0) - 1 do
                    local s = fac:getSettlement(i)
                    if s and s.name ~= keep and s.name ~= capital and (s.siegesNum or 0) == 0
                        and not (s.army and leader_of(fac, s.army)) then
                        local units = {}
                        for j = 0, (s.army and s.army.numOfUnits or 0) - 1 do units[#units + 1] = s.army:getUnit(j) end
                        for _, u in ipairs(units) do u:kill() end
                        local left = (s.army and s.army.numOfUnits) or 0
                        if left > 0 then error(string.format("%s still has %d units after disbanding", s.name, left)) end
                        return s.name
                    end
                end
                error(fac.name .. " has no town without a general to empty (keeping " .. tostring(keep) .. " and the capital)")
            end)
        end,
        -- Envoys suite (games/qa/envoys.toml). Its orders go through M.qa.order above.
        -- the treasury raised to at least `amount` (a bribe's price is the game's; a scene, not an
        -- order); the treasury after
        funds = function(faction, amount)
            return run("funds", function()
                local fac = faction_named(faction)
                if (fac.money or 0) < amount then fac.money = amount end
                return fac.money
            end)
        end,
        -- "have=<on the map and in training> limit=<n|none>" for one kind of agent, as the report's
        -- agent_limits counts them (the EDB's agent_limit lines)
        agents = function(faction, kind)
            return run("agents", function()
                local c = agent_counts(faction_named(faction))[kind]
                if not c then error("not a recruitable agent: '" .. tostring(kind) .. "'") end
                return string.format("have=%d limit=%s", c.have, tostring(c.limit or "none"))
            end)
        end,
        -- an own town that can train `kind` now (a building of its grants it, and the faction is under
        -- its limit for the kind), by name; "none" when none can
        agent_town = function(faction, kind)
            return run("agent_town", function()
                local fac = faction_named(faction)
                local c = agent_counts(fac)[kind]
                if not c then error("not a recruitable agent: '" .. tostring(kind) .. "'") end
                if c.limit and c.have >= c.limit then return "none" end
                for i = 0, (fac.settlementsNum or 0) - 1 do
                    local s = fac:getSettlement(i)
                    if s and can_train_agent(s, fac, kind) then return s.name end
                end
                return "none"
            end)
        end,
        -- the faction's agents of `kind` brought up to its limit, spawned on free tiles 1-4 from
        -- (x, y): "have=<n> limit=<n>"; "unlimited" when the EDB sets no limit for the kind
        fill_agents = function(faction, kind, x, y)
            return run("fill_agents", function()
                local fac = faction_named(faction)
                for _ = 1, 40 do
                    local c = agent_counts(fac)[kind]
                    if not c then error("not a recruitable agent: '" .. tostring(kind) .. "'") end
                    if not c.limit then return "unlimited" end
                    if c.have >= c.limit then return string.format("have=%d limit=%d", c.have, c.limit) end
                    local tile = free_tile_near(x, y, 1, 4)
                    if not tile then error(string.format("no free land tile 1-4 tiles from (%d,%d)", x, y)) end
                    local tx, ty = tile_xy(tile)
                    new_agent(fac, kind, tx, ty)
                end
                error("still under the " .. tostring(kind) .. " limit after 40 spawns")
            end)
        end,
        -- the nearest trade resource near..far tiles from (x, y) with nobody on its tile, walkable
        -- from (x, y): "x,y" (where a merchant stands to trade; region:getResource(i), as M.resources)
        resource = function(x, y, near, far)
            return run("resource", function()
                near, far = near or 0, far or 10
                local map, taken, best, best_d = gd.stratMap, taken_tiles(), nil, nil
                for r = 0, (map.regionsNum or 0) - 1 do
                    pcall(function()
                        local region = map.getRegion(r)
                        for j = 0, (region.resourcesNum or 0) - 1 do
                            local res = region:getResource(j)
                            local rx, ry = math.floor(res.xCoord), math.floor(res.yCoord)
                            local d = math.max(math.abs(rx - x), math.abs(ry - y))
                            local t = tile_at(rx, ry)
                            if d >= near and d <= far and (not best_d or d < best_d) and t and is_land(t)
                                and not taken[rx * 1000 + ry] then
                                local ok, reach = pcall(land_reach, math.floor(x), math.floor(y), rx, ry)
                                if ok and reach == true then best, best_d = string.format("%d,%d", rx, ry), d end
                            end
                        end
                    end)
                end
                if not best then error(string.format("no free resource tile %d-%d tiles from (%d,%d)", near, far, x, y)) end
                return best
            end)
        end,
        -- the faction's recruits still in training dropped from the game's training file (the
        -- recruits an instant case queued, before a turn case counts its own arriving); how many
        drop_training = function(faction)
            return run("drop_training", function()
                local fac = faction_named(faction)
                local keep, dropped = {}, 0
                for _, t in ipairs(read_training()) do
                    if t.faction == fac.name then dropped = dropped + 1 else keep[#keep + 1] = t end
                end
                if dropped > 0 then atomic_write(training_path(), encode(keep)) end
                return dropped
            end)
        end,
        -- the faction's merchant income as the report reads it (getFactionEconomy(0).merchantIncome)
        merchant_income = function(faction)
            return run("merchant_income", function()
                local e = faction_named(faction):getFactionEconomy(0)
                return math.floor((e and e.merchantIncome) or 0)
            end)
        end,
        -- Navy suite (games/qa/navy.toml). Its orders go through M.qa.order above.
        -- an army or fleet as the report shows it (army_view): "x,y fleet=<yes|no> carrying=<units
        -- aboard|-> men=<men aboard|-> aboard=<the fleet carrying it|->", or "gone"
        army = function(faction, id)
            return run("army", function()
                local fac = faction_named(faction)
                local st = find_army_now(fac, id)
                if not st then return "gone" end
                local v = army_view(st, id, fac)
                return string.format("%d,%d fleet=%s carrying=%s men=%s aboard=%s", math.floor(v.x), math.floor(v.y),
                    v.is_fleet and "yes" or "no", tostring(v.carrying or "-"), tostring(v.carrying_men or "-"),
                    tostring(v.aboard or "-"))
            end)
        end,
        -- a free sea tile near..far tiles from (x, y): "x,y", or "none"
        sea = function(x, y, near, far)
            return run("sea", function()
                local sx, sy = free_sea_near(x, y, near or 1, far or near or 1)
                return sx and string.format("%d,%d", sx, sy) or "none"
            end)
        end,
        -- a free land tile near..far from (x, y), walkable from it, with a free sea tile beside it
        -- (an army spawned there boards a fleet spawned beside it): "x,y", or "none"
        shore = function(x, y, near, far)
            return run("shore", function()
                local occupied = occupied_tiles()
                return free_tile_near(x, y, near or 1, far or near or 1, function(tx, ty)
                    return free_sea_near(tx, ty, 1, 1, occupied) ~= nil
                end) or "none"
            end)
        end,
        -- a free land tile near..far from (x, y) that can't be walked to from it (across the sea),
        -- with a free sea tile beside it: a far shore to land on, "x,y", or "none"
        far_shore = function(x, y, near, far)
            return run("far_shore", function()
                local taken, occupied = taken_tiles(), occupied_tiles()
                x, y = math.floor(x), math.floor(y)
                for r = near or 2, far or 12 do
                    for dx = -r, r do
                        for dy = -r, r do
                            local tx, ty = x + dx, y + dy
                            local t = math.max(math.abs(dx), math.abs(dy)) == r and tile_at(tx, ty)
                            if t and is_land(t) and not taken[tx * 1000 + ty] and free_sea_near(tx, ty, 1, 1, occupied) then
                                local ok, reach = pcall(land_reach, x, y, tx, ty)
                                if ok and reach == false then return string.format("%d,%d", tx, ty) end
                            end
                        end
                    end
                end
                return "none"
            end)
        end,
        -- the settlement nearest (x, y) with a port: whose = "own" for the faction's own, else a rebel
        -- or at-war one's (a blockade target); its name, or "none"
        port_town = function(faction, x, y, whose)
            return run("port_town", function()
                local fac = faction_named(faction)
                local map, best, best_d = gd.stratMap, nil, nil
                for r = 0, (map.regionsNum or 0) - 1 do
                    pcall(function()
                        local s = map.getRegion(r).settlement
                        local owner = s and s.ownerFaction
                        if not owner then return end
                        local fits
                        if whose == "own" then
                            fits = owner.name == fac.name
                        else
                            fits = owner.name ~= fac.name
                                and (owner.name == "slave" or stance(gd.campaignStruct, fac, owner) == "war")
                        end
                        if not (fits and port_of(s)) then return end
                        local d = math.max(math.abs(s.xCoord - x), math.abs(s.yCoord - y))
                        if not best_d or d < best_d or (d == best_d and tostring(s.name) < tostring(best.name)) then
                            best, best_d = s, d
                        end
                    end)
                end
                return best and best.name or "none"
            end)
        end,
        -- a town's port tile "x,y", or "none"
        port = function(town)
            return run("port", function()
                local s = gd.stratMap:getSettlement(town)
                if not s then error("unknown settlement '" .. tostring(town) .. "'") end
                local p, region = port_of(s)
                if not p then return "none" end
                local x, y = port_xy(p, region)
                return string.format("%d,%d", x, y)
            end)
        end,
        -- who blockades a town's port (EOP portStruct.blockadingArmy, its leader's name) and for how
        -- long (numTurnsBlocked): "by=<name|-> turns=<n>", or "no port"
        blockade_of = function(town)
            return run("blockade_of", function()
                local s = gd.stratMap:getSettlement(town)
                if not s then error("unknown settlement '" .. tostring(town) .. "'") end
                local p = port_of(s)
                if not p then return "no port" end
                local by = "-"
                local st = p.blockadingArmy
                if st then
                    by = "?"
                    for i = 0, stratmap.game.getFactionsCount() - 1 do
                        local f = stratmap.game.getFaction(i)
                        for j = 0, (f and f.stacksNum or 0) - 1 do
                            if f:getStack(j) == st then
                                local l = leader_of(f, st)
                                by = l and name_of(l) or by
                            end
                        end
                    end
                end
                return string.format("by=%s turns=%s", by, tostring(p.numTurnsBlocked or 0))
            end)
        end,
        -- an own town whose recruitment pool holds a ship (a port that builds them), or "none"
        ship_yard = function(faction)
            return run("ship_yard", function()
                local fac = faction_named(faction)
                for i = 0, (fac.settlementsNum or 0) - 1 do
                    local s = fac:getSettlement(i)
                    for j = 0, (s and s.recruitmentPoolCount or 0) - 1 do
                        local p = s:getSettlementRecruitmentPool(j)
                        if p and M.is_ship(p.eduIndex) then return s.name end
                    end
                end
                return "none"
            end)
        end,
        -- the ship a town's recruitment pool holds, by unit name, its pool topped up to one when below
        -- (a scene, as money is); "none" when it holds none
        ship_unit = function(town)
            return run("ship_unit", function()
                local s = gd.stratMap:getSettlement(town)
                if not s then error("unknown settlement '" .. tostring(town) .. "'") end
                for i = 0, (s.recruitmentPoolCount or 0) - 1 do
                    local p = s:getSettlementRecruitmentPool(i)
                    if p and M.is_ship(p.eduIndex) then
                        if (p.availablePool or 0) < 1 then p.availablePool = 1 end
                        return M2TWEOPDU.getEduEntry(p.eduIndex).eduType
                    end
                end
                return "none"
            end)
        end,
        -- the faction's recruits in training at `town` made due now and delivered, as its next turn
        -- start would (deliver_training): "delivered=<n>"
        deliver = function(faction, town)
            return run("deliver", function()
                local fac = faction_named(faction)
                local turn = gd.campaignStruct.turnNumber
                local function at_town()
                    local n, list = 0, read_training()
                    for _, t in ipairs(list) do
                        if t.faction == fac.name and t.settlement == town and not t.army_leader then
                            t.ready, n = turn, n + 1
                        end
                    end
                    return n, list
                end
                local due, list = at_town()
                atomic_write(training_path(), encode(list))
                deliver_training(fac, turn)
                return string.format("delivered=%d", due - (at_town()))
            end)
        end,
        -- how many fleets the faction has
        fleets = function(faction)
            return run("fleets", function()
                local fac, n = faction_named(faction), 0
                for i = 0, (fac.stacksNum or 0) - 1 do
                    local st = fac:getStack(i)
                    if st and st.isAdmiral then n = n + 1 end
                end
                return n
            end)
        end,
        -- Field and covert suites (games/qa/field.toml, covert.toml), instant cases.
        -- how many units an army (by report id) has now, or "gone" when the faction has none by that id
        units = function(faction, id)
            return run("units", function()
                local st = find_army_now(faction_named(faction), id)
                if not st then return "gone" end
                return st.numOfUnits or 0
            end)
        end,
        -- the faction's agent mission outcomes kept for its next report (agent_results), without
        -- taking them: "<who>'s <mission>: <outcome> | ...", or "" when none
        news = function(faction)
            return run("news", function()
                return M.peek_agent_news(faction_named(faction).name)
            end)
        end,
        -- the order a refusal hands out ready to copy (the board order in "board a fleet first",
        -- #202/#263), run as given through M.qa.order: the first {...} in what the last order of
        -- `otype` said
        rerun = function(faction, otype)
            local raw = tostring(last_orders[otype or 1] or ""):match("%b{}")
            local o = run("rerun", function()
                if not raw then error("no order to copy in: " .. tostring(last_orders[otype or 1] or "none")) end
                local o = json.decode(raw)
                if type(o) ~= "table" then error("not an order: " .. raw) end
                return o
            end)
            if not o then return nil end
            return M.qa.order(faction, o)
        end,
    }
end)()

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
            -- the plugin script holds the bridge in a local, so a line sees it only as M (live,
            -- 10-30: the first QA run's "M.qa.spawn_agent" found no global M); globals stay visible
            if fn and setfenv then setfenv(fn, setmetatable({ M = M }, { __index = _G })) end
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
            -- the release timer dies with this Lua state (live, 10-30 turn 44: France's frozen
            -- turn never ended); let go now, as release_frozen would; on_turn_start refreezes
            if M.frozen_turn then pcall(M.release_frozen, M.frozen_turn.since + M.FROZEN_TURN_LIMIT) end
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
K.SUCCESS_LEVEL = { earthquake = "not_successful", flood = "slightly_successful",
                        horde = "partly_successful", storm = "highly_successful" }

function M.on_agent_mission(kind, e, has_chance)
    local ok, faction, text = pcall(function()
        -- each read on its own: a princess who married is gone from the map when her event comes,
        -- and one failed read dropped the whole report (bench 11-04: Constance married, no line)
        local okw, who = pcall(function()
            local c = e.character
            return c and (c.fullName or (c.namedCharacter and c.namedCharacter.fullName))
        end)
        who = okw and who or (kind == "marriage proposal" and "a princess" or "an agent")
        local okr, raw = pcall(function() return tostring(e.missionSuccessLevel or "unknown") end)
        raw = okr and raw or "unknown"
        local level = (K.SUCCESS_LEVEL[raw] or raw):gsub("_", " ")
        local text = string.format("%s's %s: %s", who, kind, level)
        if has_chance then
            local okc, chance = pcall(function() return e.missionProbability end)
            if okc and type(chance) == "number" and chance > 0 then text = text .. string.format(" (chance was %d%%)", chance) end
        end
        return e.faction and e.faction.name, text
    end)
    if not ok or not faction then
        log("agent mission: a " .. tostring(kind) .. " event couldn't be read: " .. tostring(ok and "no faction" or faction))
        return
    end
    local list = agent_news[faction] or {}
    list[#list + 1] = text
    while #list > 20 do table.remove(list, 1) end
    agent_news[faction] = list
    log("agent mission: " .. faction .. ": " .. text)
    if kind == "marriage proposal" then M.drop_proposal(faction, text) end
    -- only a player-controlled faction's (a ruler's) mission shows a spy report: the AI's many
    -- spy missions each turn open nothing
    if kind == "spying" then
        local okp, player = pcall(function() return e.faction.isPlayerControlled == 1 end)
        if okp and player then
            local now = M.clock()
            -- a mission that worked holds End Turn until its report is closed or the wait runs out:
            -- live 10-30 (18:54, 20:53, 21:37) End Turn came 0-1 s after the mission and no report
            -- was ever seen; when it came later (17:58, 18:16, 19:41) the report opened within 4 s
            local failed = text:find(": not successful", 1, true) ~= nil
            M.spy_report = { who = faction, from = now + K.POPUP_DELAY, to = now + K.POPUP_DELAY + K.SPY_REPORT_WAIT,
                             hold = not failed }
        end
    end
end

-- Marriage proposals waiting for their outcome. Most come back through onMarriageMission, but one
-- the game turns down hard removes the princess and fires no mission event ("Princess Disgraced!",
-- data/text/english/event_titles.txt {mission_marriage_fail_and_removed}). Bench: she vanished in
-- 4 runs of 4 (11-04, 11-05), and the two 11-05 probes saw her record go dead 10 s after the order,
-- no event, the suitor unmarried and still Polish. Settled when the faction's agent news is read.
local proposals = {}  -- faction -> { [princess] = suitor }

function M.note_proposal(faction, princess, suitor)
    proposals[faction] = proposals[faction] or {}
    proposals[faction][clean_name(princess)] = clean_name(suitor)
end

-- a mission event answered a proposal. Its text starts with the princess's name as the event gave
-- it (raw: "_" or " (null)" in it), or "a princess" when her read failed, as it may once she has
-- married and left the map: then the event still answers one of the faction's proposals, so one is
-- settled rather than left to read as a disgrace later (review 11-05)
function M.drop_proposal(faction, text)
    local list = proposals[faction]
    if not list then return end
    local who = clean_name(text:match("^(.-)'s marriage proposal") or "")
    if list[who] then
        list[who] = nil
    else
        local any = next(list)
        if any then list[any] = nil end
    end
end

-- the faction's record of `name`: true alive, false dead, nil not found or unreadable
local function named_alive(faction, name)
    local f = gd.campaignStruct:getFaction(faction)
    for i = 0, (f and f.numOfNamedCharacters or 0) - 1 do
        local ok, nc = pcall(function() return f:getNamedCharacter(i) end)
        local okn, n = pcall(function() return clean_name(nc.fullName) end)
        if ok and nc and okn and n == name then
            local oka, v = pcall(function() return nc:isAlive() end)
            if not oka then oka, v = pcall(function() return nc.isAlive end) end
            if oka and (v == false or v == 0) then return false end
            if oka and (v == true or v == 1) then return true end
            return nil
        end
    end
end

local function settle_proposals(faction)
    for princess, suitor in pairs(proposals[faction] or {}) do
        local ok, alive = pcall(named_alive, faction, princess)
        if ok and alive == false then
            proposals[faction][princess] = nil
            local text = string.format("%s's marriage proposal: rejected, and she was disgraced and removed (to %s)",
                                       princess, suitor)
            local list = agent_news[faction] or {}
            list[#list + 1] = text
            agent_news[faction] = list
            log("agent mission: " .. faction .. ": " .. text)
        end
    end
end

function M.take_agent_news(faction)
    settle_proposals(faction)
    proposals[faction] = nil  -- the report is the last word on this turn's proposals
    local list = agent_news[faction] or {}
    agent_news[faction] = nil
    return list
end

-- what take_agent_news would hand the next report, left in place (the QA bench's M.qa.news)
function M.peek_agent_news(faction)
    settle_proposals(faction)
    return table.concat(agent_news[faction] or {}, " | ")
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

K.FIELD = {
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
        local ok, v = pcall(K.FIELD[f], e)
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
    local spy_report_closed = close_spy_report(M.clock())
    papal_look_tick(M.clock())  -- hands off: the vote scroll, looked for here, never in its event
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
        if now - auto.clicked >= K.STUCK_AFTER then  -- given up or not: try_dismiss paces itself
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
        -- the screen line never reaches the log; a heartbeat keeps campaign_watch from a false STALL
        if auto.beat_for ~= auto.since then auto.beat_for, auto.beat = auto.since, auto.since end
        if now - auto.beat >= 60 then
            auto.beat = now
            log(string.format("autoplay: turn %d, waiting for %s (%ds of %d)", turn, table.concat(pending, ", "),
                              waited, cfg.wait or 300))
        end
        return
    end
    if spy_report_closed then return end  -- End Turn on a later tick, once the close has landed
    if M.spy_report and M.spy_report.hold and M.spy_report.who == fac.name then
        M.status = string.format("Parley: turn %d, waiting for the spy report to close it", turn)
        if not M.spy_report.held then
            M.spy_report.held = true
            log("autoplay: turn " .. turn .. ": holding End Turn for " .. fac.name .. "'s spy report")
        end
        return
    end
    local offer = cfg.hold_decisions ~= false and M.decision_waiting()
    if offer then
        auto.offer_since = auto.offer_since or now
        local held = now - auto.offer_since
        if held < K.DECISION_HOLD_MAX then
            M.status = string.format("Parley: turn %d, waiting for the ruler's answer to %s (%ds)", turn, offer, held)
            if not auto.offer_logged then
                auto.offer_logged = true
                log("autoplay: turn " .. turn .. ": holding End Turn until the ruler answers " .. offer)
            end
            return
        end
        if not auto.offer_gave_up then
            auto.offer_gave_up = true
            log(string.format("autoplay: turn %d: %s still open after %ds; ending it anyway", turn, offer, held))
        end
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

-- A frozen AI never makes the calls only it can make (live, turn 20: England's own siege), so its
-- turn never ends. Past this many seconds the seat's AI lets go for the rest of the turn;
-- on_turn_start freezes it again next turn. (Unfrozen, that turn closed in five seconds.)
-- 3 s, not 15: a frozen AI's turn never ends by itself, and once let go it ends at once (11-05
-- bench log: 26 releases, median 0 s to the next faction's turn, one over 3 s), so a longer wait
-- buys no quiet and cost ~15 s per AI faction per played turn
M.FROZEN_TURN_LIMIT = 3
function M.release_frozen(now)
    local ft = M.frozen_turn
    if not ft or now - ft.since < M.FROZEN_TURN_LIMIT then return end
    M.frozen_turn = nil
    pcall(function()
        ft.fac.freezeFactionAI = 0
        log(ft.fac.name .. ": turn still running after " .. (now - ft.since)
            .. "s frozen; game AI unfrozen until its next turn")
    end)
end

local next_tick = 0
function M.on_frame()
    local now = M.clock()
    if now < next_tick then return end
    next_tick = now + 2
    pcall(M.release_frozen, now)
    M.tick()
end

function M.setup(turn_root)
    root = turn_root
    gd = gameDataAll.get()
    M.trace_load()
    M.papal_window_load()
    applied = {}
    edb_cache = nil
    -- mission outcomes belong to the campaign they happened in: a load (the QA restore's, a bench
    -- reload) must not hand the bench's to the next report
    agent_news = {}
    proposals = {}
    -- nor this turn's orders: apply_orders resets them per orders file, but M.qa.order bypasses it
    -- and a bench load doesn't rerun the bridge (live 10-31: bribe_agent's spy "already has an order")
    busy, ordered = {}, {}
    if M.qa then M.qa.forget() end
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
            M.sweep_at = M.clock() + K.POPUP_DELAY
        end
    end
    -- every campaign map load (start, Continue, loadGame, reload) says so: the QA runner's restore
    -- waits for this after M.qa.load, and a plain load writes no reload marker
    pcall(function() log("bridge loaded campaign at turn " .. gd.campaignStruct.turnNumber) end)
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
