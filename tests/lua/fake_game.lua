-- Minimal stand-in for the EOP 3.3.1 objects the bridge touches (see docs/eop-api-notes.md).
-- Method calls use ':' exactly where EOP does; stratMap.getRegion is a dot call.

local G = {}

dipRelType = { war = 0, peace = 1, alliance = 2 }

local function settlement(name, owner, x, y, regionID)
    return {
        name = name, localizedName = name:gsub("^%l", string.upper), ownerFaction = owner,
        xCoord = x, yCoord = y, regionID = regionID, populationSize = 4000,
        army = { totalStrength = 500, numOfUnits = 0 }, buildingsNum = 1,
        getBuilding = function(self, i) return { getType = function() return "core_building" end } end,
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
            local opts = { { "market", 1200, 3 }, { "farms", 800, 2 } }
            return { buildingNum = #opts, getConstructionOption = function(_, i)
                local o = opts[i + 1]
                return { buildCost = o[2], buildTurnsRemaining = o[3],
                         getQueueBuildingName = function() return o[1] end,
                         addBuildingToQueue = function()
                             G.calls[#G.calls + 1] = "build " .. s.name .. " " .. o[1]
                             return true
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
    local st = { numOfUnits = 2, totalStrength = 1200 }
    local units = { { eduEntry = { eduType = "Venetian Heavy Infantry" }, soldierCountStratMap = 40,
                      soldierCountStratMapMax = 60, exp = 1 },
                    { eduEntry = { eduType = "Mailed Knights" }, soldierCountStratMap = 20,
                      soldierCountStratMapMax = 20, exp = 0 } }
    st.getUnit = function(self, i) return units[i + 1] end
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
    end
    st.attackArmy = function(self, def)
        G.calls[#G.calls + 1] = "attack " .. (leaderName or "?") .. " " .. def.leader.namedCharacter.fullName
        return 1
    end
    st.findInSettlement = function() return inSett end
    st.siegeSettlement = function(self, s, isAttack)
        G.calls[#G.calls + 1] = "siege " .. (leaderName or "?") .. " " .. s.name .. " " .. tostring(isAttack)
    end
    return st
end

local function faction(name, id, money)
    return {
        name = name, localizedName = name, factionID = id, money = money, isPlayerControlled = 0,
        settlements = {}, stacks = {}, characters = {},
        getSettlement = function(self, i) return self.settlements[i + 1] end,
        getStack = function(self, i) return self.stacks[i + 1] end,
        getCharacter = function(self, i) return self.characters[i + 1] end,
        getNamedCharacter = function(self, i) return self.named[i + 1] end,
        getFactionEconomy = function(self, turnsAgo)
            return { taxesIncome = 1500, tradeIncome = 400, upkeepExpense = 700, wagesExpense = 300,
                     diplomacyExpense = 5000, constructionExpenseBuildings = 1200, diplomacyIncome = 200 }
        end,
    }
end

-- an on-map character (EOP `character`): generals lead a stack, agents stand alone
local function character(fac, name, typeName, x, y, army)
    local c = { xCoord = x, yCoord = y, armyLeaded = army,
                namedCharacter = { fullName = name, faction = fac, isAlive = function() return true end } }
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
    c.moveToTile = function(self, tx, ty) G.calls[#G.calls + 1] = "moveToTile " .. name .. " " .. tx .. " " .. ty end
    fac.characters[#fac.characters + 1] = c
    return c
end

-- a fleet at sea for fac, led by an admiral; carrying = a stack already aboard (or nil)
function G.add_fleet(fac, admiral, x, y)
    local fleet = stack(admiral, x, y, nil)
    fleet.isAdmiral = true
    fleet.numOfUnits = 1
    fleet.blockadePort = function(self, port)
        G.calls[#G.calls + 1] = "blockade " .. admiral .. " " .. port.name
        return true
    end
    fac.stacks[#fac.stacks + 1] = fleet
    fac.stacksNum = #fac.stacks
    G.add_character(fac, admiral, "admiral", x, y)
    return fleet
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

-- add a character to a faction after reset (keeps numOfCharacters right)
function G.add_character(fac, name, typeName, x, y)
    local c = character(fac, name, typeName, x, y, nil)
    fac.numOfCharacters = #fac.characters
    return c
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
    local venice = faction("venice", 4, 5000)
    local milan = faction("milan", 6, 3000)
    local hre = faction("hre", 2, 6000)
    local slave = faction("slave", 23, 1000)
    G.factions = { hre, venice, milan, slave }
    G.byName = { venice = venice, milan = milan, hre = hre, slave = slave }

    local venezia = settlement("Venice", venice, 120, 88, 10)
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
            return { isLand = (x >= 115 and y >= 90) and 0 or 1, port = port }
        end,
        getRegion = function(id)
            local p = G.ports[id]
            return { regionName = "region" .. id, settlement = G.regionSettlements[id],
                     portEntranceXCoord = p and p.x or 0, portEntranceYCoord = p and p.y or 0 }
        end,
    }
    gameDataAll = { get = function() return { campaignStruct = G.campaign, stratMap = G.stratMap } end }
    venice.isPlayerControlled = 1
    G.campaign.currentFaction = venice
    G.now = 1000  -- the clock the bridge reads (M.clock is pointed here in tests)
    stratmap = { game = {
        getFactionsCount = function() return #G.factions end,
        getFaction = function(i) return G.factions[i + 1] end,
        scriptCommand = function(cmd, arg)
            G.calls[#G.calls + 1] = "script " .. cmd .. " " .. tostring(arg)
        end,
    }, camera = {
        jump = function(x, y) G.calls[#G.calls + 1] = "camera " .. x .. " " .. y end,
    } }
    -- the game's UI: open scrolls by name, each with buttons (EOP gameSTDUI / uiElementStruct)
    G.ui = {}
    gameSTDUI = { getUiElement = function(name) return G.ui[name] end }
    -- unit definitions (EOP M2TWEOPDU.getEduEntry(index))
    G.edu = { [7] = { index = 7, eduType = "Spear Militia", recruitCost = 350, recruitTime = 1 },
              [9] = { index = 9, eduType = "Feudal Knights", recruitCost = 900, recruitTime = 2 } }
    M2TWEOPDU = { getEduEntry = function(i) return G.edu[i] end }
    for _, s in pairs({ venezia, ragusa, milano, innsbruck }) do
        s.army.createUnitByIDX = function(self, idx, exp, armour, weapon)
            G.calls[#G.calls + 1] = "create " .. s.name .. " " .. G.edu[idx].eduType
            return {}
        end
    end
    G.options2 = { autoresolveAllBattles = 0 }
    M2TWEOP = { getOptions2 = function() return G.options2 end }
end

return G
