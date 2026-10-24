--[[ parley probe (Plan 1, Task 6). Answers the open questions in docs/eop-api-notes.md:
  (a) can Lua write and read files, and where do relative paths land
  (b) does onFactionTurnStart fire for every faction, hotseat slots included
  (c) is isPlayerControlled writable (hand a slot's routine play to the AI)
  (d) can Lua wait for a file without freezing the game

Only names verified in EOP source are used (see docs/eop-api-notes.md).
Output: parley_probe.log in the game's working directory, one line per event.
]]

local LOG = "parley_probe.log"

local function log(line)
    local f, err = io.open(LOG, "a")
    if not f then return end
    f:write(os.date("%H:%M:%S "), line, "\n")
    f:close()
end

function onPluginLoad()
    log("plugin loaded; io works (a)")
end

function onFactionTurnStart(eventData)
    local ok, err = pcall(function()
        local fac = eventData.faction
        -- EOP 3.3.1 calls it stacksNum; newer EOP/M2EX call it armiesNum
        local okA, armies = pcall(function() return fac.stacksNum end)
        if not okA or armies == nil then armies = fac.armiesNum end
        log(string.format("(b) turn start: name=%s id=%d player=%d money=%d settlements=%d armies=%s",
            tostring(fac.name), fac.factionID, fac.isPlayerControlled, fac.money,
            fac.settlementsNum, tostring(armies)))

        if fac.isPlayerControlled == 1 then
            -- (c) try to flip control and flip it straight back
            local okSet, setErr = pcall(function()
                fac.isPlayerControlled = 0
                local now = fac.isPlayerControlled
                fac.isPlayerControlled = 1
                log("(c) isPlayerControlled writable; read back " .. tostring(now))
            end)
            if not okSet then log("(c) isPlayerControlled NOT writable: " .. tostring(setErr)) end
            -- (d) answered 2026-10-23: a blocking wait freezes the game (Lua runs on the
            -- main thread), so the probe no longer waits. See docs/eop-api-notes.md.
        end
    end)
    if not ok then log("ERROR in onFactionTurnStart: " .. tostring(err)) end
end
