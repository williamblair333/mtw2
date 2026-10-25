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

| Characters | `fac.numOfCharacters`, `fac:getCharacter(i)` (0-based, **no bounds check**); `c:getTypeName()` → `spy`, `assassin`, `diplomat`, `admiral`, `merchant`, `priest`, `general`, `named_character`, `princess`, `heretic`, `witch`, `inquisitor`, `pope`; `c.namedCharacter:isAlive()`; `c.armyLeaded` | luaP.cpp (character usertype) |
| Agent actions | `c:assassinate(char)`, `c:spyCharacter(char)`, `c:spySettlement(s)`, `c:bribe(char)`, `c:bribeSettlement(s)`, `c:sabotageSettlement(s)`; return nothing; **no nil checks in C++**, so the bridge resolves every target first | luaP.cpp (character usertype) |
| All settlements | `for i = 0, stratMap.regionsNum - 1 do local s = stratMap.getRegion(i).settlement end` | luaP2.cpp |
| Visibility | only `M2TWEOP.getTileVisibility(fac, x, y)`, which is *ever seen*, not *visible now*; the bridge uses a 10-tile radius instead | luaP2.cpp |
| Income | `fac:getFactionEconomy(turnsAgo)`: `farmingIncome`, `taxesIncome`, `miningIncome`, `tradeIncome`, `merchantIncome`, `constructionIncome`, `otherIncome1/2`, `diplomacyIncome`, `tributesIncome`, `adminIncome`, `kingsPurseIncome`; expenses `wagesExpense`, `upkeepExpense`, `constructionExpenseBuildings/Field`, `recruitmentExpenseBuildings/Mercs`, `corruptionExpense`, `diplomacyExpense`, `tributesExpense`, `otherExpense1/2`, `devastationExpense` | luaP.cpp |

### Playing a whole faction (observer mode)

Mapped from the source on 2026-10-24 (`LP` = `M2TWEOP-luaPlugin/luaPlugin/`). None of these has
been run in the game yet.

| Need | Call | Source |
|---|---|---|
| What can be built | `s:getConstructionOptions()` → `.buildingNum`; `opts:getConstructionOption(i)` (0-based, **unchecked**) → `:getQueueBuildingName()`, `.buildCost`, `.buildTurnsRemaining`, `:addBuildingToQueue()` → bool | LP/luaP.cpp:4184-4220, 4568-4608 |
| Construction queue | `s.buildingsQueue.numBuildingsInQueue`; `q:getBuildingInQueue(pos)` (**1-based**, checked) | LP/luaP.cpp:4100, 4524-4543 |
| What can be recruited | `s:getRecruitmentOptions()` → `.unitNum`; `r:getRecruitmentOption(i)` (0-based, **unchecked**) → `.eduEntry.eduType`, `.cost`, `.recruitTime`, `.recruitType` (0 unit, 1 ship, 2 agent, 3/4 retrain), `:addUnitToQueue()` → bool. **Bug:** retrain entries are read out of bounds (settlementHelpers.cpp:330-337). The bridge stops at the first `recruitType >= 3` | LP/luaP.cpp:4192-4295 |
| Recruitment queue | not exposed | |
| Units in a stack | `st:getUnit(i)` (0-based, **unchecked**) → `.eduEntry.eduType`, `.soldierCountStratMap`, `.soldierCountStratMapMax`, `.exp` | LP/luaP.cpp:1244-1254, 4838 |
| Moves | `char.movePoints`, `char.movePointsMaxArmy` (read only: writing them is a cheat) | LP/luaP.cpp:1976-1981 |
| Attack | `st:attackArmy(defenderStack)` → 1 issued, 0 refused (refuses a defender in a settlement) | LP/luaP.cpp:4984; stackStructHelpers.cpp:78-94 |
| Tax | `s.settlementTaxLevel` read/write; **assumed** 0 low, 1 normal, 2 high, 3 extortionate (unverified) | LP/luaP.cpp:4007 |
| Public order | `s.settlementStats.PublicOrder` | LP/luaP.cpp:4358-4409 |
| Governors | `s.aiProductionController` (may be nil) `.isAutoManagedConstruction`, `.isAutoManagedRecruitment` (writable); tax auto-manage isn't exposed | LP/luaP.cpp:3483-3495 |
| Battles | `M2TWEOP.getOptions2().autoresolveAllBattles = 1` (a hotseat option; may not apply to a normal campaign); event `onPreBattlePanelOpen`; UI element `prebattle_auto_resolve_button` | LP/luaP.cpp:662-667; luaEvents.cpp:2453 |
| Popups | UI elements `close_tick_button`, `diplomacy_decline_offer_button` (in `medieval2.exe` strings) | exe |
| Camera | `stratmap.camera.jump(x, y)` (dot call) | LP/luaP.cpp:949 |
| Merge | `st:mergeArmies(target, false)`: walks to `target` (uses moves); **no nil check in C++**, and does nothing past 20 units. The bridge looks both stacks up at turn start and checks the count first | LP/luaP.cpp:4936-4939; stackStructHelpers.cpp:217-249 |
| Marriage | `princess:marry(general)`: a princess only, the target a named character; nil-checked | LP/luaP.cpp:2039; actionsStrat.cpp:204-216 |
| Move an agent | `char:moveToTile(x, y)` works for agents as for generals | LP/luaP.cpp:2015 |
| Fleets | `stack.isAdmiral`; `fleet.boardedArmy` (one army); `army.shipArmy` (its fleet). A boarded army has no `leader`: its general stands on the fleet's tile | LP/luaP.cpp:4725-4734, 4851-4852 |
| Board, land, sail | No calls: `moveToTile` onto the fleet's tile boards it, from a ship onto land lands, and an admiral to a sea tile sails. **Untested live** | LIB/actionsStrat.cpp:163-188 |
| Blockade | `fleet:blockadePort(port)` → bool; the port is `stratmap.getTile(region.portEntranceXCoord, …).port` | LP/luaP.cpp:4961-4969; luaP2.cpp:1319 |
| Tiles | `stratmap.getTile(x, y)` (**no bounds check**) → `isLand`, `isCoastalWater`, `hasShip`, `port` | LP/luaP2.cpp:1000-1008, 1215-1228 |
| Mission outcomes | `onBriberyMission`, `onAssassinationMission`, … carry `missionSuccessLevel`. **EOP 3.3.1 bug:** it maps the level number through its disaster table, so 0–3 arrive as earthquake, flood, horde, storm (seen live). The bridge translates them back to not / slightly / partly / highly successful. `missionProbability` exists only on the events that export it | LP/gameHelpers.cpp:276-310 |
| Family | `fac.numOfNamedCharacters`, `fac:getNamedCharacter(i)`: every named character, including the dead and those off the map (`isAlive()` is a bool, `age`). The on-map list (`getCharacter`) misses them, which is how Cecilia's death went unnoticed. Also `isFamily`, `isMale`, `spouse`, `parent`, `childs`. **`status` is bit flags, not "5 leader, 2 heir" as documented:** live values are 1 (leader), 2 (heir), 164 (the dead old king), 144, 48, 240 (agents); bit 1 is leader and bit 2 heir, as EOP's own onlineThings.cpp tests them. Names can end in a literal " (null)" and carry underscores ("Charles of_Hastings"). A pending adoption candidate is listed as **not alive** until accepted. The bridge reads only name, age and status for the dead: their pointers may be stale | LP/luaP.cpp:2209-2391; LIB/onlineThings.cpp:224-228 |
| What befell a character | `onSufferAssassinationAttempt` (the victim's side), `onBattleGeneralKilled` (`stratCharacter`), `onCharacterDamagedByDisaster`, `onAcceptBribe`, `onCharacterMarries`, `onFatherDiesNatural`, `onCapturedCharacterRansomed`/`Released`: all export `character`, `faction`, `regionID` | LP/luaEvents.cpp |
| Offers to the player | `onOfferedForMarriage`, `onOfferedForAdoption`, `onLesserGeneralOfferedForAdoption` export the man offered as `character`. The scroll that follows is an event message with a green check and a red X; `clear_messages` does **not** close it (an adoption hung autoplay live). The turn loop finds the two buttons in a screenshot and clicks the ruler's answer | LP/luaEvents.cpp |
| Cheats we don't use | `s:createBuilding`, `stack:createUnit`, `char:teleport`, writing `movePoints`, instant `mergeArmies` | |

Gotchas: there's no x/y on a stack (use the leader or `findInSettlement()`); there's no getter for
"the stance"; the faction count includes the rebels (`slave`); don't copy the doc's
`#CAMPAIGN.numberOfFactions` loops; and `stratmap.game.scriptCommand` warns that
inc/set/declare_counter crash.
