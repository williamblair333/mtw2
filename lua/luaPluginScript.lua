--[[ EOP entry point for parley. Installed by `just install-bridge` into
mods/parley/youneuoy_Data/plugins/lua/ next to parley_bridge.lua and json.lua.
The game's working directory is the game root, so turn files live in <game>/parley_turns. ]]

local here = debug.getinfo(1, "S").source:match("^@(.*[/\\])") or "./"
package.path = here .. "?.lua;" .. package.path

local bridge = require("parley_bridge")

function onPluginLoad()
    M2TWEOP.unlockGameConsoleCommands()
end

function onCampaignMapLoaded()
    bridge.setup("parley_turns")
end

function onFactionTurnStart(eventData)
    local ok, err = pcall(bridge.on_turn_start, eventData.faction)
    if not ok then print("parley: on_turn_start failed: " .. tostring(err)) end
end

function onFactionTurnEnd(eventData)
    local ok, err = pcall(bridge.on_turn_end, eventData.faction)
    if not ok then print("parley: on_turn_end failed: " .. tostring(err)) end
end
