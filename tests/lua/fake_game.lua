-- Minimal stand-in for the EOP 3.3.1 objects the bridge touches (see docs/eop-api-notes.md).
-- Method calls use ':' exactly where EOP does; stratMap.getRegion is a dot call.

local G = {}

dipRelType = { war = 0, peace = 1, alliance = 2 }

local function settlement(name, owner, x, y, regionID)
    return {
        name = name, localizedName = name:gsub("^%l", string.upper), ownerFaction = owner,
        xCoord = x, yCoord = y, regionID = regionID, populationSize = 4000,
        army = { totalStrength = 500 }, buildingsNum = 1,
        getBuilding = function(self, i) return { getType = function() return "core_building" end } end,
        changeOwner = function(self, fac, convert)
            G.calls[#G.calls + 1] = "changeOwner " .. self.name .. " " .. fac.name .. " " .. tostring(convert)
            self.ownerFaction = fac
        end,
    }
end

local function stack(leaderName, x, y, inSett)
    local st = { numOfUnits = 8, totalStrength = 1200 }
    if leaderName then
        st.leader = {
            namedCharacter = { fullName = leaderName }, xCoord = x, yCoord = y,
            moveToTile = function(self, tx, ty)
                G.calls[#G.calls + 1] = "moveToTile " .. leaderName .. " " .. tx .. " " .. ty
            end,
        }
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
        settlements = {}, stacks = {},
        getSettlement = function(self, i) return self.settlements[i + 1] end,
        getStack = function(self, i) return self.stacks[i + 1] end,
    }
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
    for _, f in ipairs(G.factions) do
        f.settlementsNum = #f.settlements
        f.stacksNum = #f.stacks
    end
    G.settlements = { Venice = venezia, Ragusa = ragusa, Milan = milano }

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
    G.stratMap = {
        getSettlement = function(self, n) return G.settlements[n] end,
        getRegion = function(id) return { regionName = "region" .. id } end,
    }
    gameDataAll = { get = function() return { campaignStruct = G.campaign, stratMap = G.stratMap } end }
    stratmap = { game = {
        getFactionsCount = function() return #G.factions end,
        getFaction = function(i) return G.factions[i + 1] end,
    } }
end

return G
