-- Minimal stand-in for the EOP 3.3.1 objects the bridge touches (see docs/eop-api-notes.md).
-- Method calls use ':' exactly where EOP does; stratMap.getRegion is a dot call.

local G = {}

dipRelType = { war = 0, peace = 1, alliance = 2 }
constructionType = { upgrade = 0, construction = 1, repair = 2, demolition = 3, convert = 4, none = 5 }

-- an EOP `unit` (LuaDocs.lua:12664): what armyStruct:getUnit(i) returns and splitArmy takes. Each
-- one is its own object with an ID; the fake's splitArmy only moves units a stack really holds.
local unit_ids = 0
local function U(t)
    unit_ids = unit_ids + 1
    t.__unit, t.ID = true, t.ID or unit_ids
    return t
end
G.unit = U

local function settlement(name, owner, x, y, regionID, buildings)
    buildings = buildings or { "core_building" }
    local units = { U{ eduEntry = { eduType = "Venetian Heavy Infantry" }, soldierCountStratMap = 40,
                      soldierCountStratMapMax = 60, exp = 1 },
                    U{ eduEntry = { eduType = "Mailed Knights" }, soldierCountStratMap = 20,
                      soldierCountStratMapMax = 20, exp = 0 } }
    return {
        name = name, localizedName = name:gsub("^%l", string.upper), ownerFaction = owner,
        xCoord = x, yCoord = y, regionID = regionID, populationSize = 4000,
        army = { totalStrength = 500, numOfUnits = #units, units = units,
                 getUnit = function(self, i) return self.units[i + 1] end },
        buildings = buildings, buildingsNum = #buildings,
        getBuilding = function(self, i)
            local b = self.buildings[i + 1]
            if type(b) == "table" then
                return { getName = function() return b.name end, getType = function() return b.type or b.name end, hp = b.hp }
            elseif b then
                return { getName = function() return b end, getType = function() return b end, hp = 100 }
            end
        end,
        changeOwner = function(self, fac, convert)
            G.calls[#G.calls + 1] = "changeOwner " .. self.name .. " " .. fac.name .. " " .. tostring(convert)
            self.ownerFaction = fac
        end,
        -- player management (EOP: construction/recruitment options, queue, tax, governor flags)
        settlementTaxLevel = 1, settlementStats = { PublicOrder = 85, PublicOrderGarrison = 30, PublicOrderSqualor = -15, PublicOrderUnrest = 0 },
        aiProductionController = { isAutoManagedConstruction = 0, isAutoManagedRecruitment = 0 },
        buildingsQueue = { numBuildingsInQueue = 1,
            getBuildingInQueue = function(self, pos)
                if pos == 1 then return { getQueueBuildingName = function() return "wooden_wall" end } end
            end },
        getConstructionOptions = function(self)
            local s = self
            local opts = self.constructionOpts or { { "market", 1200, 3 }, { "farms", 800, 2 } }
            return { buildingNum = #opts, getConstructionOption = function(_, i)
                local o = opts[i + 1]
                return { buildCost = o[2], buildTurnsRemaining = o[3],
                         constructionType = o[4] or 1,
                         getQueueBuildingName = function() return o[1] end,
                         addBuildingToQueue = function()
                             G.calls[#G.calls + 1] = (o[4] == 2 and "repair " or "build ") .. s.name .. " " .. o[1]
                             return o[5] == nil and true or o[5]
                         end }
            end }
        end,
        -- recruitment pools (EOP: recruitmentPoolCount, getSettlementRecruitmentPool(i) 0-based)
        recruitmentPoolCount = 2,
        getSettlementRecruitmentPool = function(self, i)
            self.pools = self.pools or { { eduIndex = 7, availablePool = 1.5 }, { eduIndex = 9, availablePool = 0.4 } }
            return self.pools[i + 1]
        end,
        getRecruitmentOptions = function(self)
            local s = self
            -- the last entry is a retrain (recruitType 3): EOP reads it out of bounds, so skip it
            local opts = { { "Italian Spear Militia", 350, 1, 0 }, { "Peasants", 100, 1, 0 }, { "junk", 1, 1, 3 } }
            return { unitNum = #opts, getRecruitmentOption = function(_, i)
                local o = opts[i + 1]
                return { eduEntry = { eduType = o[1] }, cost = o[2], recruitTime = o[3], recruitType = o[4],
                         addUnitToQueue = function()
                             G.calls[#G.calls + 1] = "recruit " .. s.name .. " " .. o[1]
                             return true
                         end }
            end }
        end,
    }
end

local function stack(leaderName, x, y, inSett)
    local units = { U{ eduEntry = { eduType = "Venetian Heavy Infantry" }, soldierCountStratMap = 40,
                      soldierCountStratMapMax = 60, exp = 1 },
                    U{ eduEntry = { eduType = "Mailed Knights" }, soldierCountStratMap = 20,
                      soldierCountStratMapMax = 20, exp = 0 } }
    local st = { numOfUnits = 2, totalStrength = 1200, units = units }
    st.getUnit = function(self, i) return self.units[i + 1] end
    if leaderName then
        st.leader = {
            namedCharacter = { fullName = leaderName }, xCoord = x, yCoord = y,
            movePoints = 12.5, movePointsMaxArmy = 20,
            moveToTile = function(self, tx, ty)
                G.calls[#G.calls + 1] = "moveToTile " .. leaderName .. " " .. tx .. " " .. ty
            end,
        }
    end
    st.mergeArmies = function(self, target, force)
        local function id(s) return s.leader and s.leader.namedCharacter.fullName or "garrison:" .. s.findInSettlement().name end
        G.calls[#G.calls + 1] = "merge " .. id(self) .. " " .. id(target) .. " " .. tostring(force)
        if force and not self.mergeFails and not G.mergeFails then
            if self.units and target.units then
                for _, u in ipairs(self.units) do target.units[#target.units + 1] = u end
                self.units = {}
            end
            target.numOfUnits = (target.numOfUnits or 0) + (self.numOfUnits or 0)
            self.numOfUnits = 0
        end
    end
    st.attackArmy = function(self, def)
        G.calls[#G.calls + 1] = "attack " .. (leaderName or "?") .. " " .. def.leader.namedCharacter.fullName
        return 1
    end
    st.findInSettlement = function() return inSett end
    st.createUnitByIDX = function(self, idx, exp, armour, weapon)
        G.calls[#G.calls + 1] = "create " .. tostring(leaderName) .. " " .. G.edu[idx].eduType
        G.created = { exp = exp }
        self.numOfUnits = (self.numOfUnits or 0) + 1
        return G.created
    end
    st.siegeSettlement = function(self, s, isAttack)
        G.calls[#G.calls + 1] = "siege " .. (leaderName or "?") .. " " .. s.name .. " " .. tostring(isAttack)
        -- the game starts the siege (EOP armyStruct.siege) unless a test says it refuses
        if not self.siegeRefused and not self.siege then
            self.siege = { besiegedSettlement = s, siegeTurns = 0, equipmentQueueCount = 0 }
        end
    end
    return st
end

local function faction(name, id, money, cultureID)
    return {
        name = name, localizedName = name, factionID = id, cultureID = cultureID or 0,
        money = money, isPlayerControlled = 0,
        settlements = {}, stacks = {}, characters = {},
        getSettlement = function(self, i) return self.settlements[i + 1] end,
        getStack = function(self, i) return self.stacks[i + 1] end,
        getCharacter = function(self, i) return self.characters[i + 1] end,
        getNamedCharacter = function(self, i) return self.named[i + 1] end,
        -- EOP factionStruct:splitArmy(units, targetX, targetY) (LuaDocs.lua:9455-9459): the units
        -- leave their stack (a settlement too) for the target as a new stack. A general's unit takes
        -- him along: he leads the new stack, standing on the target. Strict to the documented types
        -- and EOP's example (units from armyStruct:getUnit(i)): anything but a `unit` is refused as
        -- sol refuses it, and a unit no stack of the faction holds is ignored, the call returning as
        -- if done (live 10-31 00:01:21: Simon Townsend's split "ran" and he stayed in Nottingham).
        -- G.split_raises makes it raise. A target more than a tile from the stack is ignored the same
        -- way (live run9 turns 22-27: Robert's splits out of Caen to 11 and 18 tiles off did
        -- nothing; one to the next tile worked. Live 3 tiles worked too; the fake is stricter).
        splitArmy = function(self, units, x, y)
            if G.split_raises then error("sol: splitArmy raised") end
            assert(type(units) == "table", "sol: no matching function call takes this number of arguments and the specified types")
            local names, held = {}, {}
            for _, u in ipairs(units) do
                assert(type(u) == "table" and u.__unit, "sol: no matching function call takes this number of arguments and the specified types")
                names[#names + 1] = u.eduEntry.eduType
                for _, from in ipairs(self.stacks) do
                    for i, v in ipairs(from.units or {}) do
                        local at = u.character or from.leader or (from.findInSettlement and from.findInSettlement())
                        local fx, fy = at and at.xCoord, at and at.yCoord
                        local far = fx and fy and math.max(math.abs(fx - x), math.abs(fy - y)) > 1
                        if v == u and not far then
                            table.remove(from.units, i)
                            from.numOfUnits = #from.units
                            held[#held + 1] = u
                            break
                        end
                    end
                end
            end
            G.calls[#G.calls + 1] = "splitArmy " .. self.name .. " " .. table.concat(names, ",") .. " " .. x .. " " .. y
            if #held == 0 then return end
            local st = stack(nil, x, y, nil)
            st.units, st.numOfUnits = held, #held
            for _, u in ipairs(held) do
                for _, c in ipairs(self.characters) do
                    if u.character == c then
                        c.xCoord, c.yCoord, c.armyLeaded = x, y, st
                        st.leader = c
                    end
                end
            end
            self.stacks[#self.stacks + 1] = st
            self.stacksNum = #self.stacks
        end,
        getFactionEconomy = function(self, turnsAgo)
            return { taxesIncome = 1500, tradeIncome = 400, upkeepExpense = 700, wagesExpense = 300,
                     diplomacyExpense = 5000, constructionExpenseBuildings = 1200, diplomacyIncome = 200 }
        end,
        createCharacter = function(self, agent_type, age, cname, name2, subFaction, portrait, x, y)
            assert(portrait ~= nil, "portrait_custom must not be nil")
            G.calls[#G.calls + 1] = "createCharacter " .. self.name .. " " .. agent_type .. " " .. cname .. " " .. x .. " " .. y
            -- live 10-30: the game ignores a name that isn't in the faction's name list
            if G.spawn_ignores_names then cname = "" end
            return G.add_character(self, cname, agent_type, x, y)
        end,
        -- EOP factionStruct:spawnArmy (LuaDocs.lua:9453): a general with one unit; on a settlement's
        -- tile he joins it as its garrison (EOP gives such a stack no leader)
        spawnArmy = function(self, name, name2, ctype, label, portrait, x, y, age, family, subFaction,
                             unitIndex, exp, wpn, armour, soldiers)
            assert(portrait ~= nil, "portrait must not be nil")
            -- live 10-30: sol refuses a nil label ("no matching function call ... types")
            assert(type(label) == "string", "sol: no matching function call takes this number of arguments and the specified types")
            G.labels = G.labels or {}
            assert(not G.labels[label], "spawnArmy: label reused")
            G.labels[label] = true
            G.calls[#G.calls + 1] = "spawnArmy " .. self.name .. " " .. tostring(name) .. " " .. tostring(ctype)
                .. " " .. x .. " " .. y .. " " .. tostring(unitIndex)
            local gname = (name == "random_name") and (G.random_name or "Edwin") or name
            local town
            for _, s in pairs(G.settlements) do
                if s.xCoord == x and s.yCoord == y then town = s end
            end
            local st
            if town then
                -- the town's garrison, when it has one, takes him in (one stack per settlement)
                for _, g in ipairs(self.stacks) do
                    if g.findInSettlement and g.findInSettlement() == town then st = g end
                end
                if st then
                    G.mover(G.general_in_town(self, gname, town, "named character"), 20)
                    return st
                end
                st = stack(nil, x, y, town)
                st.units = {}
                self.stacks[#self.stacks + 1] = st
                self.stacksNum = #self.stacks
                G.mover(G.general_in_town(self, gname, town, "named character"), 20)
                return st
            else
                st = G.add_army(self, gname, x, y)
                st.leader.movePoints = nil
                G.mover(st.leader, 20)
                local c = self.characters[#self.characters]
                G.mover(c, 20)
                -- one record behind the stack's leader and the character, as in the game
                st.leader.namedCharacter, st.leader.characterRecord = c.namedCharacter, c.characterRecord
            end
            st.units = { st.units[1] }
            st.numOfUnits = 1
            return st
        end,
    }
end

-- move points as EOP has them: writing movePoints sets both the character's and the army's
-- (LuaDocs.lua:6496), and reading it gives what the character has left
function G.mover(c, points)
    rawset(c, "movePointsCharacter", points)
    rawset(c, "movePointsArmy", points)
    return setmetatable(c, {
        __index = function(t, k) if k == "movePoints" then return rawget(t, "movePointsCharacter") end end,
        __newindex = function(t, k, v)
            if k == "movePoints" then
                rawset(t, "movePointsCharacter", v)
                rawset(t, "movePointsArmy", v)
            else
                rawset(t, k, v)
            end
        end,
    })
end

-- an on-map character (EOP `character`): generals lead a stack, agents stand alone
local function character(fac, name, typeName, x, y, army)
    local nc = { fullName = name, faction = fac, isAlive = function() return true end,
                 addTrait = function(self, trait, level)
                     G.calls[#G.calls + 1] = "addTrait " .. self.fullName .. " " .. tostring(trait) .. " " .. tostring(level)
                 end,
                 giveRandomName = function(self, nameFactionId)
                     G.calls[#G.calls + 1] = "giveRandomName " .. tostring(nameFactionId)
                     self.fullName = G.random_name or "Edwin"
                 end }
    local c = { xCoord = x, yCoord = y, armyLeaded = army,
                namedCharacter = nc, characterRecord = nc }
    c.getTypeName = function() return typeName end
    local function act(verb)
        return function(self, target)
            local what = target.namedCharacter and target.namedCharacter.fullName or target.name
            if target.tag then what = what .. "@" .. target.tag end  -- tells same-named targets apart
            G.calls[#G.calls + 1] = verb .. " " .. name .. " " .. what
        end
    end
    c.assassinate, c.spyCharacter, c.bribe = act("assassinate"), act("spyCharacter"), act("bribe")
    c.spySettlement, c.bribeSettlement, c.sabotageSettlement =
        act("spySettlement"), act("bribeSettlement"), act("sabotageSettlement")
    c.marry = act("marry")
    -- EOP character:diplomacySettlement / diplomacyCharacter: recorded; G.on_parley(c, target), when a
    -- test sets it, is what the game shows for it (a diplomacy screen, an AI's offer)
    for _, verb in ipairs({ "diplomacySettlement", "diplomacyCharacter" }) do
        local record = act(verb)
        c[verb] = function(self, target)
            record(self, target)
            if G.on_parley then G.on_parley(self, target, fac) end
        end
    end
    -- the move is only recorded: nobody moves on it. Live (run8 turn 18, QA garrison_general_leaves)
    -- a general inside a settlement doesn't move on it at all; tests that need a real move use splitArmy.
    c.moveToTile = function(self, tx, ty) G.calls[#G.calls + 1] = "moveToTile " .. name .. " " .. tx .. " " .. ty end
    if typeName == "general" or typeName == "named character" or typeName == "named_character" then
        -- character.bodyguards (LuaDocs.lua:6459): a `unit` of its own that no stack holds unless a
        -- test puts it there (G.general_in_town): only the stack's own unit object can be split off
        c.bodyguards = U{ eduEntry = { eduType = "NE Bodyguard" }, soldierCountStratMap = 20,
                          soldierCountStratMapMax = 20, exp = 0, owner = name, character = c }
    end
    c.teleport = function(self, tx, ty)
        G.calls[#G.calls + 1] = "teleport " .. name .. " " .. tx .. " " .. ty
        self.xCoord, self.yCoord = tx, ty
        if self.armyLeaded and self.armyLeaded.leader then
            self.armyLeaded.leader.xCoord, self.armyLeaded.leader.yCoord = tx, ty
        end
        return true
    end
    c._fac = fac  -- (not `faction`: the bridge reads that EOP field elsewhere)
    -- EOP character:kill (the game's own death): off the faction's list and out of the college
    c.kill = function(self)
        G.calls[#G.calls + 1] = "kill " .. name
        local list = self._fac.characters
        for i = #list, 1, -1 do if list[i] == self then table.remove(list, i) end end
        self._fac.numOfCharacters = #list
        if G.college then G.college_drop(self) end
    end
    -- EOP character:switchFaction(newFac, keepArmy, keepBg): the game's own switch; the college entry
    -- follows unless G.college_keeps_faction (then the bridge must set it itself)
    c.switchFaction = function(self, newFac, keepArmy, keepBg)
        G.calls[#G.calls + 1] = "switchFaction " .. name .. " " .. newFac.name
        local list = self._fac.characters
        for i = #list, 1, -1 do if list[i] == self then table.remove(list, i) end end
        self._fac.numOfCharacters = #list
        self._fac = newFac
        newFac.characters[#newFac.characters + 1] = self
        newFac.numOfCharacters = #newFac.characters
        if G.college and not G.college_keeps_faction then
            for _, card in ipairs(G.college.entries) do
                if card.character == self then card.factionID = newFac.factionID end
            end
        end
    end
    fac.characters[#fac.characters + 1] = c
    return c
end

-- the college of cardinals (EOP campaignStruct.collegeOfCardinals): a pope (a characterRecord whose
-- .character stands in Rome for the papal states) and cardinals { character, factionID }, as
-- { { "Name", "faction" }, ... }. The Pope's death starts an election (inElection, no pope).
function G.add_college(pope_name, cardinals)
    local papal = faction("papal_states", 30, 1000, 0)
    papal.settlements = {}
    G.factions[#G.factions + 1] = papal
    G.byName.papal_states = papal
    local pope = G.add_character(papal, pope_name, "pope", 60, 60)
    pope.namedCharacter.character = pope
    local college = { entries = {}, cardinalNum = 0, inElection = false, pope = pope.namedCharacter }
    college.getCardinal = function(self, i) return self.entries[i + 1] end
    for _, spec in ipairs(cardinals or {}) do
        local fac = G.byName[spec[2]]
        local c = G.add_character(fac, spec[1], "priest", 62 + #college.entries, 60)
        college.entries[#college.entries + 1] = { character = c, factionID = fac.factionID }
    end
    college.cardinalNum = #college.entries
    G.college = college
    G.campaign.collegeOfCardinals = college
    G.campaign.papalFaction = papal
    return college
end

function G.college_drop(c)
    local college = G.college
    if college.pope and college.pope.character == c then
        college.pope, college.inElection = nil, true
    end
    for i = #college.entries, 1, -1 do
        if college.entries[i].character == c then table.remove(college.entries, i) end
    end
    college.cardinalNum = #college.entries
end

-- a fleet at sea for fac, led by an admiral; carrying = a stack already aboard (or nil)
function G.add_fleet(fac, admiral, x, y)
    local fleet = stack(admiral, x, y, nil)
    fleet.isAdmiral = true
    fleet.numOfUnits = 1
    fleet.xCoord, fleet.yCoord = x, y
    fleet.blockadePort = function(self, port)
        G.calls[#G.calls + 1] = "blockade " .. admiral .. " " .. port.name
        return true
    end
    fac.stacks[#fac.stacks + 1] = fleet
    fac.stacksNum = #fac.stacks
    local c = G.add_character(fac, admiral, "admiral", x, y, fleet)
    c.armyLeaded = fleet
    return fleet
end

function G.add_army(fac, general_name, x, y)
    local s = stack(general_name, x, y, nil)
    fac.stacks[#fac.stacks + 1] = s
    fac.stacksNum = #fac.stacks
    local c = G.add_character(fac, general_name, "general", x, y, s)
    c.armyLeaded = s
    return s
end

-- a named character on the faction's records (EOP getNamedCharacter); fields as EOP names them.
-- A dead one's spouse/parent/character raise on read, as stale pointers might crash live.
function G.add_named(fac, fields)
    local nc = { fullName = fields.name, age = fields.age, isMale = fields.male and 1 or 0,
                 isFamily = fields.family and 1 or 0, status = fields.status or 0, faction = fac }
    local alive = fields.alive ~= false
    nc.isAlive = function() return alive and 1 or 0 end
    nc.isOffMap = function() return false end
    if alive then
        nc.spouse, nc.parent = fields.spouse, fields.parent
        if fields.type then nc.character = { getTypeName = function() return fields.type end } end
    else
        setmetatable(nc, { __index = function(_, k) error("stale pointer read: " .. k) end })
    end
    fac.named = fac.named or {}
    fac.named[#fac.named + 1] = nc
    fac.numOfNamedCharacters = #fac.named
    return nc
end

-- a general inside a town as the game has him: his bodyguard is a unit of the town's stack (the
-- garrison, made when there is none), linked to him by unit.character; character.bodyguards reads as
-- a separate object with the same ID, so only the stack's own (armyStruct:getUnit(i)) can be split.
-- With lead = true he leads that stack (Simon Townsend in Nottingham, live 10-31).
function G.general_in_town(fac, name, town, typeName, lead)
    local st
    for _, g in ipairs(fac.stacks) do
        if g.findInSettlement and g.findInSettlement() == town then st = g end
    end
    if not st then
        st = stack(nil, town.xCoord, town.yCoord, town)
        st.units, st.numOfUnits = {}, 0
        fac.stacks[#fac.stacks + 1] = st
        fac.stacksNum = #fac.stacks
    end
    local c = G.add_character(fac, name, typeName or "general", town.xCoord, town.yCoord)
    local u = U{ eduEntry = { eduType = "NE Bodyguard" }, soldierCountStratMap = 20,
                 soldierCountStratMapMax = 20, exp = 0, character = c }
    c.bodyguards = U{ eduEntry = u.eduEntry, soldierCountStratMap = 20, soldierCountStratMapMax = 20,
                      exp = 0, character = c, ID = u.ID }
    st.units[#st.units + 1] = u
    st.numOfUnits = #st.units
    if lead then st.leader = c end
    return c
end

-- add a character to a faction after reset (keeps numOfCharacters right)
function G.add_character(fac, name, typeName, x, y, army)
    local c = character(fac, name, typeName, x, y, army)
    fac.numOfCharacters = #fac.characters
    return c
end

-- set a character's movement points (EOP character.movePointsCharacter / movePointsArmy) on every
-- table standing for him: the stack's leader and his entry in the faction's characters. A value
-- of "raise" makes reading movePointsCharacter raise, as a field missing from an EOP build might.
function G.set_moves(name, char_points, army_points)
    local function apply(c)
        if not (c and c.namedCharacter and c.namedCharacter.fullName == name) then return end
        if char_points == "raise" then
            setmetatable(c, { __index = function(_, k)
                if k == "movePointsCharacter" then error("no such field: " .. k) end
            end })
        else
            c.movePointsCharacter = char_points
        end
        c.movePointsArmy = army_points
    end
    for _, f in ipairs(G.factions) do
        for _, st in ipairs(f.stacks) do apply(st.leader) end
        for _, c in ipairs(f.characters) do apply(c) end
    end
end

-- open a scroll with these button names; pressing a button records it and closes the scroll
function G.open_scroll(name, buttons)
    local subs = {}
    for i, b in ipairs(buttons) do
        subs[i] = { elementName = b, subElementsNum = 0,
                    execute = function() G.calls[#G.calls + 1] = "press " .. b; G.ui[name] = nil end }
    end
    G.ui[name] = { elementName = name, subElementsNum = #subs,
                   getSubElement = function(self, i) return subs[i + 1] end }
end

function G.reset()
    G.calls = {}
    G.spawn_ignores_names, G.random_name, G.on_parley = nil, nil, nil
    G.college, G.college_keeps_faction = nil, nil
    local venice = faction("venice", 4, 5000, 0)
    local milan = faction("milan", 6, 3000, 0)
    local hre = faction("hre", 2, 6000, 1)
    local slave = faction("slave", 23, 1000, 0)
    G.factions = { hre, venice, milan, slave }
    G.byName = { venice = venice, milan = milan, hre = hre, slave = slave }

    local venezia = settlement("Venice", venice, 120, 88, 10, { "market", "small_church" })
    local ragusa = settlement("Ragusa", venice, 140, 80, 11)
    local milano = settlement("Milan", milan, 100, 90, 12)
    venice.settlements = { venezia, ragusa }
    milan.settlements = { milano }
    venice.stacks = { stack("Doge Enrico", 121, 88, nil), stack(nil, 0, 0, venezia) }
    milan.stacks = { stack("Duke Ottone", 101, 90, nil) }
    local innsbruck = settlement("Innsbruck", hre, 115, 80, 13)
    hre.settlements = { innsbruck }
    local heinrich = stack("Heinrich", 112, 80, nil)
    hre.stacks = { heinrich }

    -- characters: the stacks' generals plus agents. Venice sees within 10 tiles of its own
    -- armies, agents and settlements: Heinrich (9 from the Doge), the HRE spy and Innsbruck
    -- are in sight; Duke Ottone (20 away) and the far HRE assassin are not.
    character(venice, "Doge Enrico", "general", 121, 88, venice.stacks[1])
    character(venice, "Iacopo", "assassin", 120, 88, nil)
    character(venice, "Marco", "spy", 120, 87, nil)
    character(venice, "Pietro", "diplomat", 140, 80, nil)
    character(milan, "Duke Ottone", "general", 101, 90, milan.stacks[1])
    character(hre, "Heinrich", "general", 112, 80, heinrich)
    character(hre, "Ulrich", "spy", 119, 86, nil)
    character(hre, "Konrad", "assassin", 60, 40, nil)
    for _, f in ipairs(G.factions) do
        f.settlementsNum = #f.settlements
        f.stacksNum = #f.stacks
        f.numOfCharacters = #f.characters
    end
    G.settlements = { Venice = venezia, Ragusa = ragusa, Milan = milano, Innsbruck = innsbruck }
    G.regionSettlements = { [10] = venezia, [11] = ragusa, [12] = milano, [13] = innsbruck }

    G.stances = { ["venice|hre"] = dipRelType.war, ["venice|milan"] = dipRelType.peace }
    local function key(a, b)
        if G.stances[a.name .. "|" .. b.name] then return a.name .. "|" .. b.name end
        return b.name .. "|" .. a.name
    end

    G.campaign = {
        turnNumber = 3, currentDate = 1081.5,
        getFaction = function(self, n) return G.byName[n] end,
        checkDipStance = function(self, rel, a, b) return G.stances[key(a, b)] == rel end,
        setDipStance = function(self, rel, a, b)
            G.stances[key(a, b)] = rel
            G.calls[#G.calls + 1] = "setDipStance " .. rel .. " " .. a.name .. " " .. b.name
        end,
    }
    -- ports: Innsbruck's region has a port entrance on the coast (fake geography)
    G.ports = { [13] = { x = 116, y = 91, port = { name = "Innsbruck port" } } }
    G.stratMap = {
        regionsNum = 14, mapWidth = 255, mapHeight = 200,
        getSettlement = function(self, n) return G.settlements[n] end,
        -- a dot call on the map object, as in EOP (live: the global stratmap has no getTile);
        -- isLand is 0 or 1, as live (0 is truthy in Lua). Fake geography: sea where x >= 115, y >= 90
        getTile = function(x, y)
            local port
            for _, p in pairs(G.ports) do
                if p.x == x and p.y == y then port = p.port end
            end
            return { isLand = (x >= 115 and y >= 90) and 0 or 1, port = port, regionID = x >= 130 and 11 or 10 }
        end,
        getRegion = function(id)
            local p = G.ports[id]
            return { regionName = "region" .. id, settlement = G.regionSettlements[id], mercPool = G.mercPools[id],
                     portEntranceXCoord = p and p.x or 0, portEntranceYCoord = p and p.y or 0 }
        end,
    }
    gameDataAll = { get = function() return { campaignStruct = G.campaign, stratMap = G.stratMap } end }
    venice.isPlayerControlled = 1
    -- every faction catholic (0), as the fake's Italian and German factions are in the game
    for _, f in pairs(G.byName) do f.religion = 0 end
    G.campaign.currentFaction = venice
    G.now = 1000  -- the clock the bridge reads (M.clock is pointed here in tests)
    stratmap = { game = {
        getFactionsCount = function() return #G.factions end,
        getFaction = function(i) return G.factions[i + 1] end,
        scriptCommand = function(cmd, arg)
            G.calls[#G.calls + 1] = "script " .. cmd .. " " .. tostring(arg)
            if cmd == "spawn_character" then
                local fac, kind = tostring(arg):match("^(%w+), random_name, (%a+)")
                if fac and G.byName[fac] then G.add_character(G.byName[fac], "New Agent", kind, 120, 88) end
            end
        end,
    }, camera = {
        jump = function(x, y) G.calls[#G.calls + 1] = "camera " .. x .. " " .. y end,
    } }
    -- the game's UI: open scrolls by name, each with buttons (EOP gameSTDUI / uiElementStruct)
    G.ui = {}
    G.lookups = {}  -- every name the bridge asked the game's UI for, in order
    gameSTDUI = { getUiElement = function(name)
        G.lookups[#G.lookups + 1] = name
        return G.ui[name]
    end }
    -- unit definitions (EOP M2TWEOPDU.getEduEntry(index))
    G.edu = { [7] = { index = 7, eduType = "Spear Militia", recruitCost = 350, recruitTime = 1, upkeepCost = 100 },
              [9] = { index = 9, eduType = "Feudal Knights", recruitCost = 900, recruitTime = 2, upkeepCost = 250 } }
    G.edu[20] = { index = 20, eduType = "NE Bodyguard", recruitCost = 1000, recruitTime = 1, upkeepCost = 200 }
    M2TWEOPDU = { getEduEntry = function(i) return G.edu[i] end,
                  getEduIndexByType = function(t)
                      for i, e in pairs(G.edu) do
                          if e.eduType == t then return i end
                      end
                  end }
    for _, s in pairs({ venezia, ragusa, milano, innsbruck }) do
        s.army.createUnitByIDX = function(self, idx, exp, armour, weapon)
            G.calls[#G.calls + 1] = "create " .. s.name .. " " .. G.edu[idx].eduType
            G.created = { exp = exp }  -- the unit the game returns
            return G.created
        end
    end
    G.cultures = { [0] = "southern_european", [1] = "northern_european", [2] = "eastern_european",
                   [3] = "greek", [4] = "middle_eastern" }
    G.options2 = { autoresolveAllBattles = 0 }
    -- the mercenary pool shared by Venice's and Ragusa's regions (EOP region.mercPool). Stock and price
    -- are the game's; who may hire what is descr_mercenaries.txt (tests write it): Albanians for all,
    -- knights below a whole unit, spearmen orthodox only, pilgrims crusading only, arquebusiers need an
    -- event, the old guard ended in 1000
    G.edu[12] = { index = 12, eduType = "Albanian Mercenaries", recruitCost = 400, recruitTime = 1, upkeepCost = 120 }
    G.edu[13] = { index = 13, eduType = "Pilgrims", recruitCost = 40, recruitTime = 1, upkeepCost = 10 }
    G.edu[14] = { index = 14, eduType = "Mercenary Arquebusiers", recruitCost = 800, recruitTime = 1, upkeepCost = 200 }
    G.edu[15] = { index = 15, eduType = "Old Guard", recruitCost = 100, recruitTime = 1, upkeepCost = 20 }
    local merc_units = {
        { eduEntry = G.edu[12], cost = 570, experience = 1, maxUnits = 3, currentPool = 2.4 },
        { eduEntry = G.edu[9], cost = 1100, experience = 0, maxUnits = 2, currentPool = 0.6 },
        { eduEntry = G.edu[7], cost = 400, experience = 0, maxUnits = 2, currentPool = 2 },
        { eduEntry = G.edu[13], cost = 35, experience = 0, maxUnits = 4, currentPool = 3 },
        { eduEntry = G.edu[14], cost = 830, experience = 0, maxUnits = 2, currentPool = 2 },
        { eduEntry = G.edu[15], cost = 100, experience = 0, maxUnits = 2, currentPool = 2 },
    }
    local merc_pool = { name = "pool1", getMercUnitNum = function() return #merc_units end,
                        getMercUnit = function(self, i) return merc_units[i + 1] end }
    G.mercUnits = merc_units
    G.mercPools = { [10] = merc_pool, [11] = merc_pool }
    M2TWEOP = { getOptions2 = function() return G.options2 end,
                getCultureName = function(id) return G.cultures[id] end,
                getReligionName = function(id) return ({ [0] = "catholic", [1] = "orthodox" })[id] end,
                loadGame = function(path) G.calls[#G.calls + 1] = "loadGame " .. tostring(path) end }
end

return G
