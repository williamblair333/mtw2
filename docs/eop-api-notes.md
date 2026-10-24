# EOP / M2EX Lua API: verified notes

Only facts checked against source go here. Each one cites where it was checked.
Tasks 6–7 of Plan 1 may use only names listed as verified.

## Verified

| Fact | Source |
|---|---|
| EOP opens the Lua libraries `base, package, coroutine, string, os, math, table, bit32, io, ffi, jit, debug`. **File I/O through `io` is available** to scripts. | `EOP-Labs/M2TWEOP-library`, `M2TWEOP Code/M2TWEOP library/luaPlugin.cpp:176` (checked 2026-10-23) |
| `package.path` includes `eopData\eopScripts\redist\?.lua` and `package.cpath` includes `eopData\eopScripts\redist\?.dll`, so native Lua modules (e.g. LuaSocket) can be loaded from there. | same file, lines 178–188 |
| Event hooks `onPluginLoad()` and `onPreFactionTurnStart(eventData)` exist. | same file, doc comments at lines 753, 1023 |
| M2EX's developer says M2EX implements "pretty much all" EOP Lua functions and loads scripts from the same place EOP does. | `Pannoniae/rex` issue #40, comment by Pannoniae |

## Probe results on the author's machine (2026-10-23, EOP 3.3.1, Steam DE under Proton 10.0-4)

| Question | Answer |
|---|---|
| (a) Lua file I/O in game | **Yes.** `io.open` writes `parley_probe.log` in the game root (the working directory). |
| (b) `onFactionTurnStart(eventData)` | **Fires for every faction**: all 20 AI factions, the rebels (`slave`, id 23) and the player, each with `name`, `factionID`, `isPlayerControlled`, `money`, `settlementsNum` and army count. |
| (c) `faction.isPlayerControlled` writable | **Yes.** Set to 0 and read back 0. LLM seats can be hotseat slots handed to the AI for routine play. |
| (d) Blocking wait in the event | **Freezes the game.** Lua runs on the main thread, so a 15 s wait is a 15 s freeze. |

**Decision from (d):** the bridge never blocks. The state report is written at `onFactionTurnEnd`. The orchestrator decides while the other factions and humans play. Orders already waiting are applied at that faction's next `onFactionTurnStart`. Orders that arrive after it are not applied: the bridge marks the turn `late.txt`, and the orchestrator reports those orders back to the LLM as "arrived too late; not applied". Each turn start also writes `heartbeat.txt` (turn=N), from which the orchestrator keeps turn folders ahead, even after loading a later save. LLMs act on a report one round old, which is acceptable for ruler-level orders and keeps the game from freezing.

**Version differences:** EOP 3.3.1 calls the army count `stacksNum`; newer EOP and M2EX call it `armiesNum`. 3.3.1 loads scripts from `youneuoy_Data/plugins/lua/luaPluginScript.lua`; newer versions from `eopData/eopScripts/`.

**Public M2EX 17/08 has no Lua.** Its `system.log.txt` never mentions Lua, and the probe never loaded under `M2EX.exe`. Scripting is in Discord-only test builds, so v1 runs on EOP 3.3.1 until M2EX ships scripting publicly.

## How it runs on Linux (what worked)

- EOP lives in `mods/parley` (`just install-eop`). The game root stays vanilla apart from M2EX's files.
- Steam launch options for Medieval II swap the exe for EOP's launcher, run from the mod folder:
  `PROTON_LOG=1 bash -c 'cd mods/parley && exec "${@/medieval2.exe/mods\/parley\/M2TWEOP GUI.exe}"' -- %command%`
- What failed, and why:
  - `protontricks-launch`: its sandbox kills the game when the launcher exits. With `--no-bwrap`, Wine's X11 driver crashes on the fullscreen mode switch, then on `X_SetClipRectangles`.
  - Starting from the game root: EOP's launcher quits immediately.
  - Running EOP on the M2EX-modified game files: M2EX's `descr_strat.txt` uses M2EX-only commands ("Expected faction" at line 40). Fix: the mod carries the vanilla `descr_strat.txt` and `radar_map2.tga` from `.parley-backup/`, plus the whole vanilla `data/world/maps/base` and campaign folder (a mod with its own campaign must also carry the base map).
- A window stretched beyond the render resolution breaks mouse mapping, so the mod renders at 1920×1080 (`PARLEY_RES` overrides).

## Still open

- Exact function names for: listing a faction's armies, settlements and treasury; diplomatic stances; giving money; transferring a settlement; moving or besieging with an army.

Two attempts to have Gemini research these via `agy` (2026-10-23) produced no report:
the first had its shell `curl` calls denied, and the second hit repeated 503 errors from
web search. Retry later, or read `luaPlugin.cpp` and the EOP docs directly.

## EOP 3.3.1 calls used by the bridge (source-verified)

Mapped from tag `M2TWEOP-3.3.1` (`M2TWEOP-luaPlugin/luaPlugin/`), 2026-10-23. Claude spot-checked
`setDipStance`, `changeOwner`, `siegeSettlement`, `gameDataAll` and `dipRelType` against the source.

| Need | Call | Source |
|---|---|---|
| Campaign / map | `local gd = gameDataAll.get()`; `gd.campaignStruct`; `gd.stratMap` | luaP2.cpp:1862-1873 |
| Turn number | `campaign.turnNumber` | luaP2.cpp:725 |
| Turn events | `onFactionTurnStart(e)`, `onFactionTurnEnd(e)`; `e.faction` | luaEvents.cpp:2274-2322 |
| Faction by name | `campaign:getFaction("venice")` (nil if unknown) | luaP2.cpp:835-843 |
| Treasury | `fac.money` (read/write) | luaP.cpp:2894 |
| Settlements | `fac.settlementsNum`, `fac:getSettlement(i)` (0-based); `s.name`, `s.localizedName`, `s.ownerFaction`, `s.xCoord`, `s.yCoord`, `s.populationSize`, `s.regionID`, `s.buildingsNum`, `s:getBuilding(i)`, `b:getType()` | luaP.cpp:2973-4082 |
| Settlement by name | `stratMap:getSettlement("London")` | luaP2.cpp:1043-1052 |
| Region name | `stratMap.getRegion(id).regionName` (dot call) | luaP2.cpp:987-996 |
| Armies | `fac.stacksNum`, `fac:getStack(j)` (0-based); `st.numOfUnits`, `st.totalStrength`, `st.leader` (nil inside a settlement), `st:findInSettlement()` | luaP.cpp:2931-4885 |
| Leader | `char.namedCharacter.fullName`, `char.xCoord`, `char.yCoord` | luaP.cpp:1951-2319 |
| Diplomacy | `campaign:checkDipStance(dipRelType.war, f1, f2)` → bool; `campaign:setDipStance(dipRelType.peace, f1, f2)`; `dipRelType.war/peace/alliance` | luaP2.cpp:759-784, 2960-2986 |
| Cede | `s:changeOwner(newFac, true)` (convert garrison) | luaP.cpp:3987-4001 |
| Move | `char:moveToTile(x, y)` (needs movement points) | luaP.cpp:2007-2015 |
| Siege | `st:siegeSettlement(s, false)`; always pass the bool; a silent no-op without a leader | luaP.cpp:4941-4949 |

Gotchas: there's no x/y on a stack (use the leader or `findInSettlement()`); there's no getter for
"the stance"; the faction count includes the rebels (`slave`); don't copy the doc's
`#CAMPAIGN.numberOfFactions` loops; and `stratmap.game.scriptCommand` warns that
inc/set/declare_counter crash.
