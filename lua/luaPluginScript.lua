--[[ EOP entry point for parley. Installed by `just install-bridge` into
mods/parley/youneuoy_Data/plugins/lua/ next to parley_bridge.lua and json.lua.
The game's working directory is the game root, so turn files live in <game>/parley_turns. ]]

local here = debug.getinfo(1, "S").source:match("^@(.*[/\\])") or "./"
package.path = here .. "?.lua;" .. package.path

local bridge = require("parley_bridge")

-- EOP's console opens only when this is 1; the bridge's hot reload needs it (see control())
enableConsole = 1

function onPluginLoad()
    M2TWEOP.unlockGameConsoleCommands()
    -- M2TWEOP.restartLua() (the control file's "reload") fires onPluginLoad mid-campaign and
    -- never onCampaignMapLoaded, so set up here too; at game start this is harmless and
    -- onCampaignMapLoaded sets up again when a campaign loads
    local ok, err = pcall(bridge.setup, "parley_turns")
    if not ok then print("parley: setup on plugin load failed: " .. tostring(err)) end
end

function onCampaignMapLoaded()
    bridge.setup("parley_turns")
end

function onFactionTurnStart(eventData)
    local ok, err = pcall(bridge.on_turn_start, eventData.faction)
    if not ok then print("parley: on_turn_start failed: " .. tostring(err)) end
end

-- every frame: autoplay (throttled inside) and a one-line status window while it runs
local overlay = true
function draw(pDevice)
    bridge.on_frame()
    if overlay and bridge.status and ImGui then
        overlay = pcall(function()
            -- top centre, small: on the left it covered the minimized-message icons, and a
            -- minimized decision there blocks End Turn unseen (seen live: an adoption offer)
            pcall(function()
                ImGui.SetNextWindowPos(560, 8, ImGuiCond.Always)
                ImGui.SetNextWindowSize(480, 110, ImGuiCond.Always)
            end)
            if ImGui.Begin("Parley") then
                ImGui.Text(bridge.status)
                if bridge.plan then (ImGui.TextWrapped or ImGui.Text)(bridge.plan) end
            end
            ImGui.End()
        end)  -- the first failure turns the window off for good
    end
end

-- game popups: acknowledged under autoplay a few seconds later (bridge.on_frame), and told to
-- the human slot's ruler
function onScrollOpened(eventData)
    local ok, err = pcall(bridge.on_scroll_opened, eventData)
    if not ok then print("parley: on_scroll_opened failed: " .. tostring(err)) end
end

function onIncomingMessage(eventData)
    local ok, err = pcall(bridge.on_message, eventData)
    if not ok then print("parley: on_message failed: " .. tostring(err)) end
end

onMessageOpen = onIncomingMessage

-- a suitor for the player's princess: the ruler decides (with his age, stats and traits)
function onOfferedForMarriage(eventData)
    local ok, err = pcall(bridge.on_offered_for_marriage, eventData)
    if not ok then print("parley: on_offered_for_marriage failed: " .. tostring(err)) end
end

-- a candidate for adoption into the player's family: the ruler decides, as with marriages
function onOfferedForAdoption(eventData)
    local ok, err = pcall(bridge.on_offered_for_adoption, eventData)
    if not ok then print("parley: on_offered_for_adoption failed: " .. tostring(err)) end
end

onLesserGeneralOfferedForAdoption = onOfferedForAdoption

-- how agents' missions turned out, for the ruler's next report; true = the event exports
-- missionProbability (only those may be asked for it)
local function mission(kind, has_chance)
    return function(eventData)
        local ok, err = pcall(bridge.on_agent_mission, kind, eventData, has_chance)
        if not ok then print("parley: on_agent_mission failed: " .. tostring(err)) end
    end
end
onSpyMission = mission("spying", true)
onAssassinationMission = mission("assassination", true)
onAcquisitionMission = mission("acquisition", true)
onMarriageMission = mission("marriage proposal", true)
onDenouncementMission = mission("denouncement", true)
onSabotageMission = mission("sabotage", true)
onBriberyMission = mission("bribery", false)
onDiplomacyMission = mission("diplomacy", false)

-- what befell a faction's characters: the evidence a ruler weighs when one of them vanishes
-- (has_disaster: only events that export disasterType may be asked for it; a raw vfunc call)
local function befell(what, has_disaster)
    return function(eventData)
        local ok, err = pcall(bridge.on_character_event, what, eventData, has_disaster)
        if not ok then print("parley: on_character_event failed: " .. tostring(err)) end
    end
end
onSufferAssassinationAttempt = befell("was the target of an assassination attempt")
onBattleGeneralKilled = befell("was killed in battle")
onCharacterDamagedByDisaster = befell("was struck by a disaster", true)
onAcceptBribe = befell("accepted a bribe and went over to another faction")
onCharacterMarriesPrincess = befell("married a princess")
onCharacterMarries = befell("married")
onFatherDiesNatural = befell("lost his father to a natural death")

-- what the game tells a player by message, for the ruler's next report (fields: the exports
-- the event has, the only ones that may be read; to: "own", "both" or "all")
local function news(template, fields, to)
    return function(eventData)
        local ok, err = pcall(bridge.on_faction_event, template, eventData, fields, to or "own")
        if not ok then print("parley: on_faction_event failed: " .. tostring(err)) end
    end
end
-- Only events proven safe live. A field read that EOP's docs list as exported can still crash
-- the game outright (pcall can't catch it): live, turn 67, the game died on the event right
-- after these two fired (likely a crusade or a war declaration). Add others one at a time,
-- each watched live, never in a batch.
onFactionExcommunicated = news("{faction} was excommunicated by the Pope", { "faction" }, "all")
onFactionBreakAlliance = news("{faction} broke its alliance with {targetFaction}", { "faction", "targetFaction" }, "both")
onCapturedCharacterRansomed = befell("was captured and ransomed")
onCapturedCharacterReleased = befell("was captured and released")

function onPreBattlePanelOpen(eventData)
    local ok, err = pcall(bridge.on_pre_battle)
    if not ok then print("parley: on_pre_battle failed: " .. tostring(err)) end
end

function onFactionTurnEnd(eventData)
    local ok, err = pcall(bridge.on_turn_end, eventData.faction)
    if not ok then print("parley: on_turn_end failed: " .. tostring(err)) end
end
