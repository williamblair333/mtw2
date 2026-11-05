# EOP scripting coverage

What EOP's Lua interface lets a script see and do, and which of it our bridge
(`lua/parley_bridge.lua`, `lua/luaPluginScript.lua`) already reads or calls for the LLM rulers.

**Generated file.** Everything below the hand-written sections comes from
`scripts/eop_coverage.py`; the intro and the gap list are `scripts/eop_coverage_head.md`.
Regenerate with `just eop-coverage` (needs the EOP source at `../M2TWEOP-library`,
or pass `--eop DIR`). Edit the head file for prose, the script for rules, never this file.

- **EOP source:** `M2TWEOP-3.3.0-505-gc8746370 (2026-10-25)` (a master checkout, the build the game runs).
  `docs/eop-api-notes.md` records what was verified live against 3.3.1.
- **Found:** 3053 members (fields, properties, functions and events; enum values counted
  apart), 2032 of them campaign-relevant.
- **Used by the bridge:** 265 members, plus 157 matched by name only
  (see `?` below). Of the campaign-relevant ones, 239 (+118 by name).
  Most of the rest are tunables, battle-only or screen-only.

## How to read the tables

| status | meaning |
|---|---|
| `not used` | the bridge never names it |
| `USED report` | read on the path that builds the state report (the StateReport the ruler gets). A key in brackets, such as `(income_parts)`, is the report field the code path feeds. |
| `USED order` | read or called while applying an order (`handlers.*`) |
| `USED event` | read in an event handler (news, popups, missions, marriage offers) |
| `USED other` | read elsewhere: turn driver, popup and UI automation, control file, tick |
| `?` after a status | the member name is declared by several EOP types and the bridge reads that name through a variable the script can't resolve (`x.name`). It is probably used, perhaps through a different type. |

Kinds: `field` (plain C++ member), `property` (getter/setter), `function`, `event`, `enum`.
`rw` is writable, `ro` is read-only, as far as the binding shows; a field the engine ignores on write is
still `rw` here. Test a write live before relying on it.
A tag in italics (*(modding)*, *(ui)*) means the member sits in a campaign domain but is about files,
models, settings or screens, not game state. "Used" means the code path runs, not that the prompt
renders every value: `parley/prompt.py` decides that.

Domains collect EOP's usertypes: faction, character and character record, settlement, army and
unit, map, campaign and diplomacy, religion and papacy, buildings and recruitment, AI, forts and
resources, events, global functions, enums; battle, UI, the campaign rules database
(`campaign_db` tunables) and modding internals are collapsed at the end.

## What the ruler sees and can order today

**Sees** (StateReport, `parley/protocol.py`): treasury and income with its parts, one-off spending
and receipts; its settlements (garrison, population, buildings and damage, siege, public order and its parts,
tax level, what it can build and recruit, queues, port); armies (strength, men, units, position,
moves, troops, fleet cargo); foreign armies, agents and settlements in sight; other factions (stance,
settlement and army counts, leader, capital, treaties, turns in stance); the family and characters
on record; trade resources in sight; land crossings; news, popups, mission and character events,
stance changes. Prompt rendering is in `parley/prompt.py`.

**Can order** (26 orders): send gold, cede settlement, set stance (war, peace, alliance), march on,
besiege (or storm), withdraw, assassinate, spy, bribe, sabotage, build, repair, recruit, recruit
agent, retrain, set tax, move army, attack, move agent, marry, merge armies, merge units, disband,
board, land, blockade.

**Events the bridge listens to** (30 of 243 EOP events): `onPluginLoad`,
`onCampaignMapLoaded`, `onFactionTurnStart`, `onFactionTurnEnd`, `onScrollOpened`,
`onIncomingMessage`, `onMessageOpen`, `onOfferedForMarriage`, `onOfferedForAdoption`,
`onLesserGeneralOfferedForAdoption`, `onPreBattlePanelOpen`; the agent mission results
(`onSpyMission`, `onAssassinationMission`, `onAcquisitionMission`, `onMarriageMission`,
`onDenouncementMission`, `onSabotageMission`, `onBriberyMission`, `onDiplomacyMission`); what befell a
character (`onSufferAssassinationAttempt`, `onBattleGeneralKilled`, `onCharacterDamagedByDisaster`,
`onAcceptBribe`, `onCharacterMarriesPrincess`, `onCharacterMarries`, `onFatherDiesNatural`,
`onCapturedCharacterRansomed`, `onCapturedCharacterReleased`); and two realm news items
(`onFactionExcommunicated`, `onFactionBreakAlliance`). New event hooks are added one at a time, each
watched live (turn 67: a batch of field reads in an event crashed the game).
Many other game events reach the ruler anyway as message popups through `onIncomingMessage`
(the `news` field), so an unlisted event is not always invisible. The campaign events nothing
listens to yet include `onFactionWarDeclared`, `onFactionAllianceDeclared`,
`onFactionTradeAgreementMade`, `onCityRebels`, `onCityRiots`, `onCitySacked`, `onOccupySettlement`,
`onSackSettlement`, `onExterminatePopulation`, `onSettlementConverted`, `onCrusadeCalled`,
`onCrusadeEnds`, `onPopeElected`, `onCharacterDied`, `onFactionDied`, `onBirth`, `onBecomesFactionLeader`,
`onLeaderMissionSuccess`, `onLeaderMissionFailed`, `onUnitTrained`, `onBuildingCompleted`,
`onStartSiege`, `onEndSiege`, `onHordeFormed`, `onInsurrection`, `onDisaster`, `onGiveMoney`.

## Highest-value gaps for rulers

Unused campaign-relevant members that would let an LLM ruler see more or act more. Names are
EOP's; the member tables below say which type each lives on. Ordered by how much a ruler's decisions
would change, roughly.

1. **Enemy army composition.** `armyStruct:getUnit(i)` with `unit.eduEntry`, `soldierCountStratMap`, `exp`
   work on any visible army, not only your own. The report gives foreign armies only strength, men and
   units (`troops` is own armies only). A ruler can't tell cavalry from militia before it attacks, flees or
   sieges. Pairs with `eduEntry` stats below.
2. **Unit stats.** `eduEntry` (attack, defence, hit points, `class`, `category`, `mount`, `morale`,
   `recruitCost`, `upkeepCost`, `primaryStats`, ranges). Recruit options give cost, turns and upkeep only,
   so recruiting is by name. One line of role and strength per unit type would let a ruler build to a plan.
3. **Victory conditions.** `factionStruct.winCondition` (`holdRegionsWinCondition`:
   `regionsToHoldCount`, `getRegionToHoldName`, `getRegionToHoldLength`) and
   `campaignStruct.campaignWinnerID`, `endDate`. Rulers don't know what they are playing toward or how
   close any faction is.
4. **Relative strength of every faction.** `factionStruct:getFactionRanking(turn)` (`factionRanking`: military,
   production, territory, financial, population scores) and `totalRankingScore`. The factions list has counts only;
   rankings say who is winning and who is the threat.
5. **How the AI feels about you.** `factionStruct:getFactionStanding(other)` (a float, the attitude) and
   `factionDiplomacy` (`factionStanding`, `isTrustWorthy`, `numTurnsAllied`, `numTurnsWar`, `numTurnsTrade`,
   `tributeAmount`, `tributeDuration`, `diplomaticBalance`, `lastDiplomaticResult`, `numTurnsCeasefire`,
   `turnsSinceLastMeeting`). Stance (war/peace/alliance) hides whether an AI is about to break a treaty or
   will accept a request. Today rulers learn this by being refused.
6. **Diplomacy beyond stance.** `factionStruct:setMilitaryAccess`, `hasMilitaryAccess` and
   `factionDiplomacy.hasTradeRights`, `isProtectorate`, `protectoratePayment`: grant or revoke
   access, see tribute. Only `set_stance` and `send_gold` exist as orders.
7. **Where the AI neighbours aim.** `factionStruct:getInterFactionLTGD(other)` (`frontLineBalance`,
   `hasAllianceAgainst`, `isStrongestNeighbour`, `isWeakestNeighbour`, `borderTiles`),
   `aiLongTermGoalDirector` (`longTermPolicy`, `longTermTroopStatus`, `consideringNavalInvasion`,
   `navalTargetRegionID`, `getInvasionTargetPriority`), `factionStruct.aiPersonalityType/aiPersonalityName`,
   `getAiFactionValues` (`totalStrength`, `freeStrength`, `immediateEnemyStrength`, `navalStrength`).
   The AI's own view of who it will attack next and how strong it thinks it is.
8. **Who borders you.** `factionStruct.neighbourFactionsBitmap`, `isNeighbourFaction`, `neighbourRegionsNum`,
   `getNeighbourRegionID`, `isNeighbourRegion`. The bridge works out reach from tiles; this is the
   engine's own adjacency, cheap and exact.
9. **Real fog of war and sight.** `factionStruct:getTileVisibility(x, y)`, `canSeeCharacter(c)`,
   `getSpottedCharacter(i)`, `spottedCharactersCount`, `characterRecord.lineOfSight`. Sight is now estimated by
   distance from your own units (`M.sight`); the engine knows exactly what the faction sees, ambushes
   included. It would also give "last seen" locations without our own memory.
10. **Characters: traits, ancillaries, ratings.** `characterRecord:getTraits`, `getTrait`, `getTraitLevel`,
    `ancNum`, `getAncillary`, `hasAncillary`, and the ratings `loyalty`, `command`, `authority`, `influence`,
    `subterfuge`, `piety`, `charm`, `finance`, `management`, `unorthodoxy`, `bribeResistance`, `kills`,
    `numberOfChildren`, `yearOfBirth`, `isHeir`, `isLeader`. The family list has names, ages and
    kinship but nothing about what a general or governor is good at, or who might rebel.
    (`getTraits` is read only for marriage offers.)
11. **A character's real reach.** `character:getMovementExtents()`, `inEnemyTerritory`, `inEnemyZOC`,
    `ambushState`, `isPlagued`, `sedentaryTurns`, `movePointsMaxCharacter`. The tiles an army or agent can reach this
    turn, and whether it is pinned, instead of a ruler guessing from moves left.
12. **Settlement income and growth.** `settlementStats` (`FarmsIncome`, `TaxesIncome`, `MiningIncome`,
    `TradeIncome`, `BuildingsIncome`, `TotalIncomeWithoutAdmin`, the `PopGrowth*` terms,
    `PublicOrder*` is already read), `settlementStruct.turnsOwned`, `harvestSuccess`, `baseFertility`. Faction totals
    are in the report (`income_parts`); which settlement earns or loses, and why population grows, isn't.
13. **Rebellion, plague and unrest risk.** `settlementStruct.isProvokedRebellion`, `rebelFactionChance`,
    `readyToSurrender`, `turmoil`, `plagued`, `plagueDuration`, `publicHealth`, `isTradeBlocked`, `timeSinceLastRebellion`,
    `previousOwner`, `regionStruct.famineThreat`, `loyaltyFactionID`, `rebelType`. A ruler sees public order as a
    number but not that a revolt is about to fire, or that a plague is spreading.
14. **Religion percentages.** `settlementStruct:getReligion(i)`, `ownerConversionRate`, `foundingConversionRate`,
    `settlementStats.majorityReligionID`, `regionStruct:getReligionHistory(turns)`, `character.percentCharacterReligionInRegion`,
    `factionStruct.religion`. Whether a priest is needed, whether a region will flip, whether to build a church.
15. **Papacy and crusades.** `campaignStruct.papalFaction`, `collegeOfCardinals` (`pope`, `popeIsOld`, `inElection`,
    `getCardinal`), `cardinal` (`voteFactionID`, `isPreferati`), `campaignStruct.crusade` and `jihad`
    (`crusadeStruct`: `targetSettlement`, `startTurn`, `endTurn`, `factionJoined`, `length`), `factionStruct.isExcommunicated`.
    The bridge hears excommunication as news. The pope's standing, an open crusade and its target aren't in the report.
16. **Missions.** `factionStruct.missionCount`, `missionDetailsStruct` (`missionName`, `paybackName`). Rulers see mission
    texts only as popups and news; no list of open missions, deadlines or rewards.
17. **Per-opponent war record.** `factionStruct:getBattleVsFactionStats(other)`, `battlesWon`, `battlesLost`,
    `settlementsCaptured`, `settlementsLost`, `unitsLost`, `unitsRecruited`, `lastOpponentId`. Gives the ruler a memory of
    whom it beats and who beats it.
18. **Mercenaries.** `regionStruct.mercPool`, `mercPool:getMercUnit(i)`, `mercPoolUnit` (`cost`, `currentPool`, `maxUnits`,
    `replenishMin/Max`, `experience`), and the `onHireMercenaries` event. The recruit list is read from the building tree (EDB),
    so hireable mercenaries, a common emergency answer, are neither seen nor ordered.
19. **Recruitment pools.** `settlementStruct:getRecruitmentOptions()`, `getSettlementRecruitmentPool(i)` (already used
    for pool counts), `freezeRecruitmentPool`, and the queue counters (`spiesInRecruitmentQueue` and kin). The
    bridge rebuilds options from the EDB; the engine's own list is authoritative (it may also avoid the
    EOP 3.3.1 `recruit_blocked` limit; test live).
20. **Forts and watchtowers.** `factionStruct.fortsNum`, `getFort`, `getWatchtower`, `fortStruct` (`governor`, `siegeNum`,
    `fortFortificationLevel`, `readyToSurrender`, `ownerFaction`), `watchtowerStruct.blockingArmy`; orders `armyStruct:siegeFort`,
    `liftSiege`, `liftBlockade`, `factionStruct:createFortXY`, `createWatchtower`. The report lists no forts or
    watchtowers, own or foreign, and there is no order to besiege a fort.
21. **Siege and army checks and orders not offered.** `armyStruct:canStartSiege`, `canStartAssault`, `canRetreat`,
    `liftSiege`, `isEnemyTo`, `factionStruct:splitArmy`, `settlementStruct:destroyBuilding`, `upgrade`. The engine can
    say whether an army may besiege at all; today a ruler finds out by being refused.
22. **Agent actions not offered.** `character:denounce`, `acquire`, `diplomacyCharacter`, `diplomacySettlement`,
    `switchFaction`, and the fort variants (`spyFort`, `bribeFort`, `diplomacyFort`). Priests and diplomats have no orders
    beyond movement; a diplomat can be moved but not made to negotiate; no way to denounce a rival general.
23. **Terrain for pathing.** `tileStruct` (`groundType`, `climate`, `hasRiver`, `isTradeRoute`, `devastationLevel`, `mpModifier`,
    `factionID` for tile ownership, `hasCrossing`, `roadLevel`, `isImpassible`), `stratMap:findValidTileNearTile`, `isInBounds`.
    The bridge reads `isLand` and crossings; rivers, roads and slow terrain decide a march's arrival turn.
24. **Season and weather.** `campaignStruct.currentSeason`, `startDate`, `endDate`, `weather`, `windSpeed`. Winter starves
    sieges and slows armies; the report has the year only.
25. **Guilds.** `settlementStruct:getGuildStanding(i)`, `guild` (`name`, `id`, `level1-3`). Guild offers and standing are
    invisible to the ruler.
26. **Cities' trade.** `regionStruct.totalTradeValue`, `getResourcesValue`, `hasResourceType`, `resourceTypesBitMap`,
    `tradeResource:getResourceHasMine`, `hasMineBuilt`. Resources in sight are listed (kind, value, owner); what a region's trade is
    worth and whether a mine is built are not.
27. **Army state.** `armyStruct.upkeepModifier`, `isHalfDestroyed`, `moraleBroken`, `tired`, `totalStrengthStart`, `supportingArmiesCampaign`,
    `unit.moraleLevel`, `soldiersFled`. Weakened-army checks without having to compare strength rounds.
28. **Faction automation.** `factionStruct.autoManageAll`, `autoManageBuildings`, `autoManageRecruitment`, `autoManageTaxes`,
    `spendingLimit`, `treasuryTurnStart`. The bridge hands the human slot's unmanaged areas to settlement governors
    (`M.set_governors`); these are the engine's own switches for that, per faction, and the spending cap is new.
29. **Faction record.** `factionRecord` (`canHorde`, `canHavePrincess`, `hasFamilyTree`, `prefersNavalInvasions`, `hordeMinUnits`,
    `shadowedByID`, `spawnsOnRevoltID`). Rules that differ per faction: can it field hordes, does it have princesses.
30. **Rules database.** The `campaignDb*` tunables (ransom, bribery, revolt, recruitment, religion, autoresolve). Static, so
    better summarised once in a rules brief than read each turn.

Not worth reading for rulers: `eduEntry` visuals and animation names, camera, models, textures, ImGui, fonts, shortcuts,
battle internals (see the collapsed sections).

## Parsing limits

- The tables list what is *bound*, not what works. A binding can exist for a member EOP 3.3.1 or the game crashes on.
  Names the bridge touches are exercised live; the rest are not verified.
- Read/write is from the binding shape (`sol::property` with one accessor is read-only; a bare C++ member
  is writable). A field marked `rw` may be ignored by the engine on write.
- A `set` taking a C++ member function pointer is classed as a function by looking for its definition in the
  EOP sources; inline-only methods can be misread as fields.
- Descriptions are EOP's own doc comments. Where there is none, the table shows the documented Lua type.
- Usage is found by name. Names shared by several types are marked `?`; members read through a variable
  holding a key (`e[k]` over a list) are found only when the list is a plain table of names in the bridge.
- The `campaignDb*` tunables, battle, UI and internals are classified by type name, not by reading each member.

## Summary by domain

| domain | members | campaign-relevant | used | campaign-relevant used | campaign-relevant not used |
|---|---:|---:|---:|---:|---:|
| Faction | 201 | 182 | 38 (+3?) | 38 (+3?) | 141 |
| Character and character record | 327 | 323 | 26 (+44?) | 26 (+44?) | 253 |
| Settlement | 196 | 186 | 49 (+8?) | 49 (+8?) | 129 |
| Army and unit | 419 | 406 | 32 (+20?) | 32 (+20?) | 354 |
| Strategy map, tiles and regions | 199 | 185 | 19 (+8?) | 19 (+8?) | 158 |
| Campaign, diplomacy and game state | 153 | 143 | 14 (+3?) | 14 (+3?) | 126 |
| Religion, papacy and crusades | 44 | 44 | 0 (+1?) | 0 (+1?) | 43 |
| Buildings and recruitment | 127 | 127 | 11 (+10?) | 11 (+10?) | 106 |
| Campaign AI | 116 | 116 | 3 (+3?) | 3 (+3?) | 110 |
| Fort, port, watchtower and resources | 68 | 64 | 2 (+17?) | 2 (+17?) | 45 |
| Events | 279 | 193 | 45 (+1?) | 38 (+1?) | 154 |
| Global functions (M2TWEOP, stratmap) | 148 | 63 | 12 | 7 | 56 |
| Enums and constants | 530 | 356 | 3 | 3 | 353 |
| Battle | 296 | 0 | 2 (+28?) | 0 | 0 |
| UI | 164 | 0 | 10 (+5?) | 0 | 0 |
| Campaign rules database (tunables) | 283 | 0 | 2 (+3?) | 0 | 0 |
| Modding and internals | 33 | 0 | 0 (+3?) | 0 | 0 |
| **Total, enums excluded** | **3053** | **2032** | **265 (+157?)** | **239 (+118?)** | **1675** |

## Faction

201 members, 38 used (+3 by name only).

### factionEconomy (20/24 used)

| member | kind | what it is | status |
|---|---|---|---|
| `farmingIncome` | field rw | `int` | USED report (income, income_parts) |
| `taxesIncome` | field rw | `int` | USED report (income, income_parts) |
| `miningIncome` | field rw | `int` | USED report (income, income_parts) |
| `tradeIncome` | field rw | `int` | USED report (income, income_parts) |
| `merchantIncome` | field rw | `int` | USED report (income, income_parts) |
| `constructionIncome` | field rw | `int` | USED report (income) |
| `lootingIncome` | field rw | `int` | not used |
| `missionIncome` | field rw | `int` | not used |
| `diplomacyIncome` | field rw | `int` | USED report (income) |
| `tributesIncome` | field rw | `int` | USED report (income, income_parts) |
| `adminIncome` | field rw | `int` | USED report (income, income_parts) |
| `kingsPurseIncome` | field rw | `int` | USED report (income, income_parts) |
| `wagesExpense` | field rw | `int` | USED report (income, income_parts) |
| `upkeepExpense` | field rw | `int` | USED report (income, income_parts) |
| `constructionExpenseBuildings` | field rw | `int` | USED report (income) |
| `constructionExpenseField` | field rw | `int` | USED report (income) |
| `recruitmentExpenseBuildings` | field rw | `int` | USED report (income) |
| `recruitmentExpenseMercs` | field rw | `int` | USED report (income) |
| `corruptionExpense` | field rw | `int` | USED report (income, income_parts) |
| `diplomacyExpense` | field rw | `int` | USED report (income) |
| `tributesExpense` | field rw | `int` | USED report (income, income_parts) |
| `disasterExpense` | field rw | `int` | not used |
| `entertainmentExpense` | field rw | `int` | not used |
| `devastationExpense` | field rw | `int` | USED report (income, income_parts) |

### factionStruct (18/102 used)

| member | kind | what it is | status |
|---|---|---|---|
| `dipNum` | field rw |  | not used |
| `factionID` | field rw | `int` | USED report |
| `aiFaction` | field rw | `aiFaction` | not used |
| `hasSeaAccess` | field rw | `bool` | not used |
| `spottedCharactersCount` | field rw | `int` | not used |
| `aiPersonalityType` | field rw | `int` | not used |
| `aiPersonalityName` | field rw | `int` | not used |
| `getFactionName` | function |  | not used |
| `cultureID` | field rw | `int` | USED report + order |
| `ai_label` | property rw | `string` | not used |
| `name` | property rw | `string` | USED report (agent_limits, family) + order + event + other |
| `localizedName` | property rw | `string` | USED report + other |
| `regionsOwnedStart` | field rw | `int` | not used |
| `capital` | field rw | `settlementStruct` | USED report |
| `leader` | field rw | `characterRecord` | USED report |
| `heir` | field rw | `characterRecord` | not used |
| `neighbourFactionsBitmap` | field rw | `int` | not used |
| `isPlayerControlled` | field rw | 0=AI, 1=player | USED report + event + other |
| `religion` | field rw | `int` | not used |
| `missionCount` | field rw | `int` | not used |
| `isUndiscovered` | field rw | `int` | not used |
| `neighbourRegionsNum` | field rw | `int` | not used |
| `money` | field rw | `int` | USED report + order + other |
| `deadStatus` | field rw | `int` | not used |
| `kingsPurse` | field rw | `int` | not used |
| `facStrat` | field rw | `factionRecord` | not used |
| `factionRecord` | field rw | `factionRecord` | not used |
| `autoManageAll` | field rw | `bool` | not used |
| `autoManageRecruitment` | field rw | `bool` | not used |
| `autoManageBuildings` | field rw | `bool` | not used |
| `autoManageTaxes` | field rw | `bool` | not used |
| `spendingLimit` | field rw | `float` | not used |
| `isHorde` | field rw | `bool` | not used |
| `isExcommunicated` | field rw | `bool` | not used |
| `revoltReason` | field rw | `int` | not used |
| `freezeFactionAI` | field rw | `int` | USED report + order + event + other |
| `treasuryTurnStart` | field rw | `int` | not used |
| `netIncome` | property ro | Get only! farms + taxes + mining + trade + kingsPurse - upkeep - wages | not used |
| `incomeDoubled` | field rw |  | not used |
| `battlesWon` | field rw | `int` | not used |
| `battlesLost` | field rw | `int` | not used |
| `unitsRecruited` | field rw | `int` | not used |
| `unitsLost` | field rw | `int` | not used |
| `lastOpponentId` | field rw | `int` | not used |
| `settlementsCaptured` | field rw | `int` | not used |
| `settlementsLost` | field rw | `int` | not used |
| `otherFactionCount` | field rw | `int` | not used |
| `numOfNamedCharacters` | field rw |  | USED report (family) |
| `characterRecordNum` | field rw | includes literally all characters without distinction (so also wives, children, dead and those sent off map) | not used |
| `winCondition` | field rw | `holdRegionsWinCondition` | not used |
| `getNamedCharacter` | function |  | USED report (family) |
| `getCharacterRecord` | function | Get a character record using it's index. | not used |
| `numOfCharacters` | field rw | includes all the characters present on the strat map | USED report (agents, armies.leader) + order |
| `getCharacter` | function | Get a character using it's index. | USED report (agents, armies.leader) + order |
| `getSpottedCharacter` | function | Get a spotted character using it's index. | not used |
| `armiesNum` | field rw | `int` | not used |
| `stacksNum` | field rw |  | USED report (distance, nearby_settlements.by_land) + order + other |
| `getArmy` | function | Get an army using it's index. | not used |
| `getStack` | function |  | USED report (distance, nearby_settlements.by_land) + order + other |
| `settlementsNum` | field rw | `int` | USED report (agent_limits, distance) + order + other |
| `getSettlement` | function | Get a settlement using it's index. | USED report (agent_limits, distance) + order + other |
| `fortsNum` | field rw | `int` | not used |
| `getFort` | function | Get a fort using it's index. | not used |
| `portsNum` | field rw | `int` | not used |
| `getPort` | function | Get a port using it's index. | not used |
| `watchtowersNum` | field rw | `int` | not used |
| `getWatchtower` | function | Get a watchtower using it's index. | not used |
| `deleteFort` | function | Delete a specific fort. | not used |
| `createFortXY` | function | Create a fort at the specified coordinates. | not used |
| `createWatchtower` | function | Create a watchtower at the specified coordinates. | not used |
| `deleteWatchtower` | function | Delete a specific watchtower. | not used |
| `hasMilitaryAccess` | function | Check if a faction has military access to another faction. | not used |
| `setMilitaryAccess` | function | Set if a faction has military access to another faction. | not used |
| `getFactionStanding` | function | Get the faction standing between 2 factions (a faction with itself returns global standing). | not used |
| `setFactionStanding` | function | Set the faction standing between 2 factions (a faction with itself sets global standing). | not used |
| `getFactionRanking` | function | Get the faction ranking scores. | not used |
| `getFactionEconomy` | function | Get the faction ecomomy table, specified number of turns ago (max 10). | USED report (income, income_parts) |
| `isNeighbourFaction` | function | Check if 2 factions are neighbours. | not used |
| `getNeighbourRegionID` | function | Get a region ID of a neighbouring region by index. | not used |
| `getBattleVsFactionStats` | function | Get stats versus a specific other faction. | not used |
| `getAiFactionValues` | function | Get various statistics the long term goal director uses. | not used |
| `getInterFactionLTGD` | function | Get various statistics the long term goal director uses versus a target faction. | not used |
| `setCharacterNameFaction` | function | Set the faction characters of a specific type draw their names from. | not used |
| `getTileVisibility` | function | Get faction tile visibility. | not used |
| `setTileVisibility` | function | Set faction tile visibility. | not used |
| `revealTile` | function | Reveal a tile. | not used |
| `hideRevealedTile` | function | Hide revealed tile. | not used |
| `getMapInfo` | function | Get map information. | not used |
| `ancillaryExists` | function | Get the first character it finds holding an ancillary if it exists in the faction. | not used |
| `addSettlement` | function | Add a settlement. | not used |
| `setColor` *(modding)* | function | Set the faction's color. | not used |
| `setSecondaryColor` *(modding)* | function | Set the faction's secondary color. | not used |
| `createCharacter` | function | Create a new character at the specified coordinates. If you are not spawning an agent it is preferred to use ... | not used |
| `spawnArmy` | function | Create a new army at the specified coordinates. Works similarly to the script command spawn_army. You can res... | not used |
| `splitArmy` | function | Split an army. If there is an army at target coords they merge. They embark/disembark. They enter and leave s... | not used |
| `isNeighbourRegion` | function | Check if a region neighbours this faction. | not used |
| `getCharacterCountOfType` | function | Count amount of alive characters of a specified type inside this faction. | not used |
| `canSeeCharacter` | function | Check if the faction can see a certain character (not in ambush stance or has been spotted). | not used |
| `getCharacterByLabel` | function | Get a character by script label. | not used |
| `setFactionBanner` *(modding)* | function | Change faction banner to another faction's. | not used |
| `setLeader` | function | Set a new faction leader. | not used |
| `setCapital` | function | Set new faction capital. | not used |

### eopRebelFaction (1/8 used)

| member | kind | what it is | status |
|---|---|---|---|
| `name` | field rw | `string` | USED report + order + event + other ? |
| `rebelEntry` | field rw | `rebelFaction` | not used |
| `bannerRed` *(modding)* | field rw | `int` | not used |
| `bannerGreen` *(modding)* | field rw | `int` | not used |
| `bannerBlue` *(modding)* | field rw | `int` | not used |
| `bannerSet` *(modding)* | field rw | `bool` | not used |
| `setBannerSymbol` *(modding)* | function | Set the rebel faction's symbol. | not used |
| `addCharacterModel` *(modding)* | function | Add a character model for this rebel faction's captains. | not used |

### factionRecord (1/41 used)

| member | kind | what it is | status |
|---|---|---|---|
| `primaryColorRed` *(modding)* | field rw | Warning: resets on reload. | not used |
| `name` | field rw | `string` | USED report + order + event + other ? |
| `primaryColorGreen` *(modding)* | field rw | Warning: resets on reload. | not used |
| `primaryColorBlue` *(modding)* | field rw | Warning: resets on reload. | not used |
| `canHorde` | field rw | `bool` | not used |
| `secondaryColorRed` *(modding)* | field rw | Warning: resets on reload. | not used |
| `secondaryColorGreen` *(modding)* | field rw | Warning: resets on reload. | not used |
| `secondaryColorBlue` *(modding)* | field rw | Warning: resets on reload. | not used |
| `triumphValue` | field rw | Usage unknown. | not used |
| `cultureID` | property rw | `int` | not used |
| `standardIndex` | field rw | Warning: resets on reload. | not used |
| `logoIndex` *(modding)* | field rw | Warning: resets on reload. | not used |
| `smallLogoIndex` *(modding)* | field rw | Warning: resets on reload. | not used |
| `religionID` | field rw | `int` | not used |
| `customBattleAvailability` | field rw | `int` | not used |
| `periodsUnavailableInCustomBattle` | field rw | `int` | not used |
| `canSap` | field rw | shouldnt do anything in med 2, but could potentially use flag to store some other info about this faction | not used |
| `prefersNavalInvasions` | field rw | `int` | not used |
| `canHavePrincess` | field rw | `bool` | not used |
| `hasFamilyTree` | field rw | `bool` | not used |
| `teutonic` | field rw | `bool` | not used |
| `disbandToPools` | field rw | `bool` | not used |
| `canBuildSiegeTowers` | field rw | `bool` | not used |
| `canTransmitPlague` | field rw | `bool` | not used |
| `shadowedByID` | field rw | `int` | not used |
| `shadowingID` | field rw | `int` | not used |
| `spawnsOnRevoltID` | field rw | `int` | not used |
| `spawnsOnRevoltOwnerID` | field rw | `int` | not used |
| `roman` | field rw | `bool` | not used |
| `barbarian` | field rw | `bool` | not used |
| `eastern` | field rw | `bool` | not used |
| `slave` | field rw | `bool` | not used |
| `hordeMinUnits` | field rw | `int` | not used |
| `hordeMaxUnits` | field rw | `int` | not used |
| `reductionPerHorde` | field rw | `int` | not used |
| `hordeUnitPerSettlementPop` | field rw | `int` | not used |
| `hordeMinNamedCharacters` | field rw | `int` | not used |
| `hordeMaxPercentArmyStack` | field rw | `int` | not used |
| `setFactionStratModel` *(modding)* | function | Set the strat model a character uses for a character type at a specific level. You can only set levels up to ... | not used |
| `setFactionBattleModel` *(modding)* | function | Set a faction's default battle model | not used |
| `getLocalizedName` | function | Get localized name. | not used |

### rebelFaction (1/6 used)

| member | kind | what it is | status |
|---|---|---|---|
| `name` | property rw | `string` | USED report + order + event + other ? |
| `index` | field rw | `int` | not used |
| `category` | field rw | `int` | not used |
| `chance` | field rw | `int` | not used |
| `totalUnitCount` | field rw | `int` | not used |
| `getCategory` | function | Get a rebel unit category. | not used |

### battleFactionCounter (0/3 used)

| member | kind | what it is | status |
|---|---|---|---|
| `battlesWon` | field rw | `int` | not used |
| `battlesLost` | field rw | `int` | not used |
| `lastResult` | field rw | 0 - lose, 1 - draw, 2 - win | not used |

### factionRanking (0/6 used)

| member | kind | what it is | status |
|---|---|---|---|
| `totalRankingScore` | field rw | `float` | not used |
| `militaryRankingScore` | field rw | `float` | not used |
| `productionRankingScore` | field rw | `float` | not used |
| `territoryRankingScore` | field rw | `float` | not used |
| `financialRankingScore` | field rw | `float` | not used |
| `populationRankingScore` | field rw | `float` | not used |

### holdRegionsWinCondition (0/4 used)

| member | kind | what it is | status |
|---|---|---|---|
| `regionsToHoldCount` | field rw | `int` | not used |
| `numberOfRegions` | field rw | `int` | not used |
| `getRegionToHoldName` | function | Get the name of the region that has to be held to win the campaign. | not used |
| `getRegionToHoldLength` | function | Get the number of turns the region has to be held to win the campaign. | not used |

### rebelCategory (0/2 used)

| member | kind | what it is | status |
|---|---|---|---|
| `unitCount` | field rw | `int` | not used |
| `getUnit` | function | Get a rebel unit. | not used |

### rebelUnit (0/5 used)

| member | kind | what it is | status |
|---|---|---|---|
| `unitName` | property rw | `string` | not used |
| `category` | field rw | `int` | not used |
| `soldierCount` | field rw | `int` | not used |
| `armour` | field rw | `int` | not used |
| `weapon` | field rw | `int` | not used |

## Character and character record

327 members, 26 used (+44 by name only).

### characterRecord (26/129 used)

| member | kind | what it is | status |
|---|---|---|---|
| `index` | field rw | `int` | not used |
| `character` | field rw | `character` | USED report (family) |
| `traitCount` | property ro | `int` | not used |
| `shortName` | property rw | Internal name. | not used |
| `lastName` | property rw | Internal name. | not used |
| `fullName` | property rw | Internal name including surname. | USED report (family) + order + event |
| `localizedDisplayName` | property rw | Display name, resets upon reloading a save. | not used |
| `savedDisplayName` | property rw | `string` | not used |
| `savedDisplayLastName` | property rw | `string` | not used |
| `savedDisplayEpithet` | property rw | Use removeEpithet() if you need to clear this | not used |
| `label` | property rw | `string` | not used |
| `portrait` | property rw | Wives (who have never been princesses) and children do not have anything for this field. Path to 'young' port... | not used |
| `portrait2` | property rw | Wives (who have never been princesses) and children do not have anything for this field. Path to 'old' portra... | not used |
| `portrait_custom` | property rw | Wives (who have never been princesses) and children do not have anything for this field. Folder name in ui/cu... | not used |
| `modelName` *(modding)* | property rw | Battle model (needs battle_models.modeldb entry). | not used |
| `status` | field ro | 5-leader,2 - heir, 0 - ordinary character, read only, do not set value | USED report (family) + event + other |
| `setAsHeir` | function | Sets the named character as the faction heir. | not used |
| `isOffMap` | function | Checks if character is off map, read only, do not set this value. | USED report (family) |
| `isMale` | property rw | `bool` | USED report (family) |
| `isAlive` | property rw | `bool` | USED report (family) + other |
| `isChild` | property rw | `bool` | not used |
| `isFamily` | property rw | `bool` | USED report (family) |
| `age` | property rw | `int` | USED report (family) + event |
| `yearOfBirth` | field rw | For example with 4 turns per year, the yearOfBirth could be 1840.25 | not used |
| `seasonOfBirth` | field rw | `int` | not used |
| `seasonOfDeath` | field rw | `int` | not used |
| `nameFaction` | field rw | `int` | not used |
| `yearOfDeath` | field rw | `float` | not used |
| `numberOfChildren` | field rw | `int` | not used |
| `faction` | field rw | `factionStruct` | USED report + event |
| `isFamilyHead` | property rw | `bool` | not used |
| `kills` | property rw | `int` | not used |
| `wasLeader` | property rw | `bool` | not used |
| `wasMarriageAlliance` | field rw | `bool` | not used |
| `deathType` | field rw | `int` | not used |
| `originalFaction` | field rw | `int` | not used |
| `parent` | field rw | `characterRecord` | USED report (family) |
| `portraitIndex` | field rw | `int` | not used |
| `spouse` | field rw | `characterRecord` | USED report (family) |
| `childs` | property ro |  | not used |
| `children` | property ro | Maximum 4. | not used |
| `combatVsReligion` | property ro | Maximum 10. EVEN IF YOU SET RELIGION LIMIT. | not used |
| `combatVsFaction` | property ro | Maximum 31. | not used |
| `getTraits` | function | Get the pointer to the character's traits container. | USED event |
| `addTrait` | function | Add a trait to the character. Case sensitive. | not used |
| `removeTrait` | function | Remove a trait from the character. Case sensitive. | not used |
| `ancNum` | field rw | `int` | not used |
| `getAncillary` | function | Get the pointer to the ancillary using it's index. You can iterate over a character's ancillaries for example... | not used |
| `addAncillary` | function | Add an ancillary to the named character using the name per export\_descr\_ancillaries.txt. | not used |
| `removeAncillary` | function | Remove an ancillary from the named character using it's pointer. Use getAncillary function to get the specifi... | not used |
| `getEopSetModel` *(modding)* | function | Get the model set with eop. | not used |
| `giveValidLabel` | function | Give an unused label based on shortName + _eop_number. | not used |
| `isLeader` | function | Check if character is a faction leader. | not used |
| `isHeir` | function | Check if character is a faction heir. | not used |
| `hasAncillary` | function | Check if the character has a certain ancillary. | not used |
| `hasAncType` | function | Check if the character has a certain ancillary type. | not used |
| `getTrait` | function | Get a character trait. | not used |
| `getTraitLevel` | function | Get the level of a trait the character has (or 0 if the character does not have the trait). Case sensitive. | not used |
| `addTraitPoints` | function | Add trait points to a trait, will upgrade/downgrade the level if it passes the thresholds. Case sensitive. | not used |
| `acquireAncillary` | function | Give character an ancillary, checks excluded cultures. | not used |
| `giveRandomName` | function | Give a random name. | not used |
| `setPortrait` | function | Set a characters portrait. Use a relative path from the mod folder! This is persistent and the recommended me... | not used |
| `giveRandomPortrait` | function | Select a random portrait from a culture for a character. | not used |
| `removeEpithet` | function | Remove a characters epithet | not used |
| `birthChild` | function | Create a new child for the character. You need to select the father for this. | not used |
| `marryWife` | function | Create and marry a wife. | not used |
| `createMessageMarriageProposal` | function | Create a message with a marriage proposal. For a daughter - a husband, for a son - a wife. | not used |
| `level` | field rw | `int` | USED order ? |
| `authority` | field rw | `int` | USED event ? |
| `command` | field rw | `int` | USED event ? |
| `chivalryAndDread` | field rw | positive = Chivalry, negative = Dread | USED event |
| `loyalty` | field rw | `int` | USED event ? |
| `piety` | field rw | `int` | USED event ? |
| `influence` | field rw | `int` | not used |
| `subterfuge` | field rw | `int` | not used |
| `charm` | field rw | `int` | not used |
| `finance` | field rw | `int` | not used |
| `magic` | field rw | `int` | not used |
| `unorthodoxy` | field rw | `int` | not used |
| `heresyImmunity` | field rw | `int` | not used |
| `assassination` | field rw | `int` | not used |
| `sabotage` | field rw | `int` | USED report + order + event + other ? |
| `eligibility` | field rw | `int` | not used |
| `purity` | field rw | `int` | not used |
| `violence` | field rw | `int` | not used |
| `disposition` | field rw | `int` | not used |
| `boldness` | field rw | `int` | not used |
| `generosity` | field rw | `int` | not used |
| `management` | field rw | `int` | not used |
| `bodyguardSize` | field rw | `int` | not used |
| `troopMorale` | field rw | `int` | not used |
| `movementPointsBonus` | field rw | `int` | not used |
| `attack` | field rw | `int` | USED report + order + event ? |
| `defence` | field rw | `int` | not used |
| `siegeAttack` | field rw | `int` | not used |
| `siegeDefense` | field rw | `int` | not used |
| `ambush` | field rw | `int` | not used |
| `navalCommand` | field rw | `int` | not used |
| `siegeEngineering` | field rw | `int` | not used |
| `nightBattle` | field rw | `int` | not used |
| `personalSecurity` | field rw | `int` | not used |
| `publicSecurity` | field rw | `int` | not used |
| `bribery` | field rw | `int` | not used |
| `bribeResistance` | field rw | `int` | not used |
| `electability` | field rw | `int` | not used |
| `lineOfSight` | field rw | `int` | not used |
| `trainingUnits` | field rw | `int` | not used |
| `trainingAgents` | field rw | `int` | not used |
| `construction` | field rw | `int` | not used |
| `trading` | field rw | `int` | not used |
| `localPopularity` | field rw | `int` | not used |
| `footInTheDoor` | field rw | `int` | not used |
| `farming` | field rw | `int` | USED report ? |
| `mining` | field rw | `int` | USED report ? |
| `taxCollection` | field rw | `int` | not used |
| `fertility` | field rw | `int` | not used |
| `cavalryCommand` | field rw | `int` | not used |
| `infantryCommand` | field rw | `int` | not used |
| `gunpowderCommand` | field rw | `int` | not used |
| `artilleryCommand` | field rw | `int` | not used |
| `health` | field rw | `int` | USED report + other ? |
| `squalor` | field rw | `int` | USED report + other ? |
| `unrest` | field rw | `int` | USED report + other ? |
| `law` | field rw | `int` | USED report + other ? |
| `looting` | field rw | `int` | not used |
| `bodyguardValour` | field rw | `int` | not used |
| `hitpoints` | field rw | Note: Generals have base 5 hitpoints and can gain up to 5 more from traits/ancillaries. Hitpoint values can e... | not used |
| `trainingAnimalUnits` | field rw | `int` | not used |
| `battleSurgery` | field rw | `int` | not used |

### character (16/81 used)

| member | kind | what it is | status |
|---|---|---|---|
| `characterType` | property rw | use characterType enum | not used |
| `xCoord` | field rw | `int` | USED report (armies, armies.leader) + order + other |
| `yCoord` | field rw | `int` | USED report (armies, armies.leader) + order + other |
| `namedCharacter` | field rw |  | USED report + order + event + other |
| `characterRecord` | field rw | `characterRecord` | not used |
| `faction` | property ro | `factionStruct` | USED report + order + event + other ? |
| `markedForDeath` | field rw | can check if the character died before the game updates he is dead like post battle event | not used |
| `inEnemyZOC` | field rw | `bool` | not used |
| `inEnemyTerritory` | field rw | `bool` | not used |
| `sedentaryTurns` | field rw | `int` | not used |
| `isPlagued` | field rw | `bool` | not used |
| `plaguedDuration` | field rw | `int` | not used |
| `ambushState` | field rw |  | not used |
| `actionType` | field rw | `int` | not used |
| `unusedMovePoints` | field rw | `bool` | not used |
| `infiniteMovePoints` | field rw | `bool` | not used |
| `movePointsCharacter` | field rw | `float` | not used |
| `numTurnsIdle` | field rw | `int` | not used |
| `regionID` | field rw | `int` | not used |
| `hasEopOrders` | field rw | `bool` | not used |
| `percentCharacterReligionInRegion` | field rw | 0 to 1 | not used |
| `popConvertedThisTurn` | field rw | `float` | not used |
| `timeInRegion` | field rw | `int` | not used |
| `timeWithArmy` | field rw | for auxiliary generals, not leading general | not used |
| `settlement` | property ro | `settlementStruct` | USED report + order + event + other ? |
| `fort` | property ro | `fortStruct` | not used |
| `dockedPort` | field rw | `portStruct` | not used |
| `blockedPort` | field rw | `portStruct` | not used |
| `army` | field rw | `armyStruct` | USED order + event ? |
| `jihad` | property ro | `jihadStruct` | not used |
| `armyLeaded` | field rw |  | USED report (armies.leader) + order |
| `bodyguards` | field rw | `unit` | not used |
| `armyNotLeaded` | field rw |  | not used |
| `visitingArmy` | field rw | in the army but not leading it | not used |
| `movePointsModifier` | field rw | `float` | not used |
| `movePointsMaxArmy` | field rw | `float` | USED report (armies.troops) |
| `movePointsMaxCharacter` | field rw | `float` | not used |
| `movePointsArmy` | field rw | `float` | not used |
| `movePoints` | property rw | sets both army and character move points. | USED report (armies.troops) |
| `crusade` | field rw | `crusadeStruct` | not used |
| `turnJoinedCrusade` | field rw | `int` | not used |
| `currentTurn` | field rw | `int` | not used |
| `distanceToCrusadeTarget` | field rw | `float` | not used |
| `crusadeNoProgressTurns` | field rw |  | not used |
| `noCrusadeProgressThisTurn` | field rw |  | not used |
| `ability` | property rw | see descr\_hero\_abilities.xml | not used |
| `getTypeID` | function | Get the character type. Use characterType enum. | not used |
| `getTypeName` | function | Get the character type. Use characterType enum. | USED report (armies.leader, family) + order |
| `setTypeID` | function | Set the character type. Use characterType enum. | not used |
| `moveToTile` | function | Issue regular move command, character must have movement points. | USED order + other |
| `diplomacyCharacter` | function | Issue diplomacy command. | not used |
| `assassinate` | function | Issue assassination command. | USED report (armies) + order + event + other |
| `marry` | function | Issue marry command. | USED report + order + event |
| `spyCharacter` | function | Issue spyCharacter command. | not used |
| `denounce` | function | Issue denounce command. | not used |
| `bribe` | function | Issue bribe command. | USED report (armies) + order + event + other |
| `acquire` | function | Issue acquire command. | not used |
| `sabotage` | function | Issue sabotage command. | USED report + order + event + other ? |
| `switchFaction` | function | Switch character faction. | not used |
| `diplomacySettlement` | function | Issue diplomacy command. | not used |
| `bribeSettlement` | function | Issue bribe command. | not used |
| `spySettlement` | function | Issue spy command. | not used |
| `sabotageSettlement` | function | Issue sabotage command. | not used |
| `diplomacyFort` | function | Issue diplomacy command. | not used |
| `bribeFort` | function | Issue bribe command. | not used |
| `spyFort` | function | Issue spy command. | not used |
| `reposition` | function | Instantly teleport character to the coordinates, if occupied a random place in the same region is chosen. | not used |
| `teleport` | function | Instantly teleport character to the coordinates, if occupied the closest valid place to the coordinates is ch... | not used |
| `kill` | function | Delete this character | USED order ? |
| `createFort` | function | Create a fort at the character's coordinates | not used |
| `setBodyguardUnit` | function | Set bodyguard. Do this only for characters without it, such as immediately after creating a character. | not used |
| `setCharacterModel` *(modding)* | function | Set a character's model to a new one. | not used |
| `sendOffMap` | function | Send a character off map (command will not fire if the general does not have a label, as you wouldn't be able... | not used |
| `getMovementExtents` | function | Get the movement extents for the character. | not used |
| `createMoveData` | function | Get pathfinding information for this character (try to create and then assign to a variable and use it, not c... | not used |
| `joinCrusade` | function | Join an ongoing crusade. | not used |
| `leaveCrusade` | function | Abandon a joined crusade. | not used |
| `joinJihad` | function | Join an ongoing jihad. | not used |
| `leaveJihad` | function | Abandon a joined jihad. | not used |
| `hasFreeTilesToMove` | function | Check if character can move out of his position. | not used |
| `isGeneral` | function | Checks if character is either named_character or general. | not used |

### characterMoveData (4/24 used)

| member | kind | what it is | status |
|---|---|---|---|
| `character` | field rw | `character` | not used |
| `xCoord` | field rw | `int` | USED report + order + other ? |
| `yCoord` | field rw | `int` | USED report + order + other ? |
| `searchType` | field rw | `int` | not used |
| `turns` | field rw | `int` | USED report + order + other ? |
| `moveExtents` | field rw | `characterMovementExtents` | not used |
| `settlementCount` | property ro | `int` | not used |
| `fortCount` | property ro | `int` | not used |
| `tileCount` | property ro | `int` | not used |
| `armyCount` | property ro | `int` | not used |
| `resourceCount` | property ro | `int` | not used |
| `characterCount` | property ro | `int` | not used |
| `getSettlement` | function | Get a settlement. | USED other ? |
| `getCharacter` | function | Get a character. | not used |
| `getArmy` | function | Get an army. | not used |
| `getResource` | function | Get a resource. | not used |
| `getFort` | function | Get a fort. | not used |
| `getTile` | function | Get a tile. | not used |
| `sortSettlementsDistance` | function | Sort settlements by distance (already sorted by default). | not used |
| `sortSettlementsStrength` | function | Sort settlements by strength. | not used |
| `sortArmiesDistance` | function | Sort armies by distance (already sorted by default). | not used |
| `sortArmiesStrength` | function | Sort armies by strength. | not used |
| `sortFortsDistance` | function | Sort forts by distance (already sorted by default). | not used |
| `sortFortsStrength` | function | Sort forts by strength. | not used |

### ancillary (3/12 used)

| member | kind | what it is | status |
|---|---|---|---|
| `index` | field rw | `int` | not used |
| `isUnique` | field rw | `bool` | not used |
| `effectsNum` | field rw | `int` | not used |
| `transferable` | field rw | `bool` | not used |
| `name` | property rw | (internal) | USED report + order + event + other ? |
| `type` | property rw | `string` | USED report + order + event + other ? |
| `imagePath` *(modding)* | property rw | `string` | not used |
| `localizedName` | property rw | `string` | USED report + other ? |
| `description` | property rw | `string` | not used |
| `effectsDescription` | property rw | `string` | not used |
| `getEffect` | function | Get an ancillary effect. | not used |
| `isCultureExcluded` | function | Is culture exluded? | not used |

### moveDataTile (3/5 used)

| member | kind | what it is | status |
|---|---|---|---|
| `tile` | field rw | `tileStruct` | not used |
| `moveCost` | field rw | `float` | not used |
| `turns` | field rw | `int` | USED report + order + other ? |
| `xCoord` | field rw | `int` | USED report + order + other ? |
| `yCoord` | field rw | `int` | USED report + order + other ? |

### traitContainer (3/5 used)

| member | kind | what it is | status |
|---|---|---|---|
| `level` | property ro | `int` | USED order ? |
| `name` | property ro | `string` | USED report + order + event + other ? |
| `nextTrait` | property ro | `traitContainer` | USED event |
| `prevTrait` | property ro | `traitContainer` | not used |
| `traitInfo` | field rw | `traitStruct` | not used |

### moveDataArmy (2/4 used)

| member | kind | what it is | status |
|---|---|---|---|
| `army` | field rw | `armyStruct` | USED order + event ? |
| `moveCost` | field rw | `float` | not used |
| `turns` | field rw | `int` | USED report + order + other ? |
| `ownFaction` | field rw | `bool` | not used |

### moveDataSettlement (2/4 used)

| member | kind | what it is | status |
|---|---|---|---|
| `settlement` | field rw | `settlementStruct` | USED report + order + event + other ? |
| `moveCost` | field rw | `float` | not used |
| `turns` | field rw | `int` | USED report + order + other ? |
| `ownFaction` | field rw | `bool` | not used |

### traitEffect (2/2 used)

| member | kind | what it is | status |
|---|---|---|---|
| `id` | field rw | `int` | USED report + order + event + other ? |
| `value` | field rw | `int` | USED report ? |

### traitEntry (2/11 used)

| member | kind | what it is | status |
|---|---|---|---|
| `index` | field rw | `int` | not used |
| `name` | field rw | `string` | USED report + order + event + other ? |
| `levels` | property ro | Maximum: 10, first real level seems to be at index 1 (so 2 in lua), use function instead | USED report (agent_limits) + order |
| `antiTraits` | property ro | Maximum: 20 | not used |
| `levelCount` | field rw | will be one over the actual count | not used |
| `antiTraitCount` | field rw | `int` | not used |
| `noGoingBackLevel` | field rw | `int` | not used |
| `hidden` | field rw | `bool` | not used |
| `getLevel` | function | Get trait level, dont need to account for the first level being at index 1. | not used |
| `isCharacterTypeValid` | function | Is character type valid? | not used |
| `isCultureExcluded` | function | Is culture excluded? | not used |

### traitLevel (2/10 used)

| member | kind | what it is | status |
|---|---|---|---|
| `level` | field rw | `int` | USED order ? |
| `threshold` | field rw | `int` | not used |
| `effectsCount` | field rw | `int` | not used |
| `name` | property rw | `string` | USED report + order + event + other ? |
| `description` | property rw | `string` | not used |
| `effectsDescription` | property rw | `string` | not used |
| `epithetDescription` | property rw | `string` | not used |
| `gainDescription` | property rw | `string` | not used |
| `loseDescription` | property rw | `string` | not used |
| `getTraitEffect` | function | Get trait effect. | not used |

### characterMovementExtents (1/9 used)

| member | kind | what it is | status |
|---|---|---|---|
| `searchType` | field rw | (only get) | not used |
| `totalTiles` | field rw | `int` | not used |
| `xCoordMin` | field rw | `int` | not used |
| `yCoordMin` | field rw | `int` | not used |
| `xCoordMax` | field rw | `int` | not used |
| `yCoordMax` | field rw | `int` | not used |
| `turns` | field rw | `int` | USED report + order + other ? |
| `character` | field rw | `character` | not used |
| `getTile` | function | Get a movement extent tile. | not used |

### moveDataCharacter (1/4 used)

| member | kind | what it is | status |
|---|---|---|---|
| `character` | field rw | `character` | not used |
| `moveCost` | field rw | `float` | not used |
| `turns` | field rw | `int` | USED report + order + other ? |
| `ownFaction` | field rw | `bool` | not used |

### moveDataFort (1/4 used)

| member | kind | what it is | status |
|---|---|---|---|
| `fort` | field rw | `fortStruct` | not used |
| `moveCost` | field rw | `float` | not used |
| `turns` | field rw | `int` | USED report + order + other ? |
| `ownFaction` | field rw | `bool` | not used |

### moveDataResource (1/4 used)

| member | kind | what it is | status |
|---|---|---|---|
| `resource` | field rw | `tradeResource` | not used |
| `moveCost` | field rw | `float` | not used |
| `turns` | field rw | `int` | USED report + order + other ? |
| `ownFaction` | field rw | `bool` | not used |

### movementExtentTile (1/3 used)

| member | kind | what it is | status |
|---|---|---|---|
| `tile` | property ro | `tileStruct` | not used |
| `moveCost` | field rw | `float` | not used |
| `turns` | field rw | `int` | USED report + order + other ? |

### capturedCharacter (0/2 used)

| member | kind | what it is | status |
|---|---|---|---|
| `namedChar` | field rw | `characterRecord` | not used |
| `capturedValue` | field rw | `int` | not used |

### capturedFactionInfo (0/11 used)

| member | kind | what it is | status |
|---|---|---|---|
| `targetFactionID` | field rw | `int` | not used |
| `factionID` | field rw | `int` | not used |
| `namedChar` | field rw | `characterRecord` | not used |
| `targetCharacter` | field rw | `characterRecord` | not used |
| `capturedCharactersNum` | property ro | `int` | not used |
| `capturedUnitsNum` | property ro | `int` | not used |
| `ransomValue` | field rw | `int` | not used |
| `heirCaptured` | field rw | `bool` | not used |
| `leaderCaptured` | field rw | `bool` | not used |
| `getCapturedUnit` | function | Get a captured unit by it's index. | not used |
| `getCapturedCharacter` | function | Get a captured character by it's index. | not used |

### traitStruct (0/3 used)

| member | kind | what it is | status |
|---|---|---|---|
| `traitEntry` | field rw | `traitEntry` | not used |
| `levelEntry` | field rw | `traitLevel` | not used |
| `traitPoints` | field rw | `int` | not used |

## Settlement

196 members, 49 used (+8 by name only).

### settlementStruct (25/102 used)

| member | kind | what it is | status |
|---|---|---|---|
| `xCoord` | field rw | `int` | USED report (distance, visible_enemies/seen_agents/nearby_settlements) + order + other |
| `yCoord` | field rw | `int` | USED report (distance, visible_enemies/seen_agents/nearby_settlements) + order + other |
| `governor` | field rw | `character` | USED report + other ? |
| `army` | field rw | `armyStruct` | USED report (visible_enemies/seen_agents/nearby_settlements) + order + other |
| `rebelEntry` | field rw | `rebelFaction` | not used |
| `port` | field rw | `portStruct` | not used |
| `name` | property rw | internal name of settlement | USED report (armies, visible_enemies/seen_agents/nearby_settlements) + order + other |
| `localizedName` | property rw | `string` | USED report (visible_enemies/seen_agents/nearby_settlements) + order + other |
| `ownerFaction` | field rw | `factionStruct` | USED report (resources, settlements.can_recruit_agents) + order + other |
| `changeOwner` | function | Change owner faction of settlement. All agents, armies etc. leave the settlement. | USED order |
| `creatorFactionID` | field rw | `int` | not used |
| `savedData` | property rw | `table` | not used |
| `regionID` | field rw | `int` | USED report + order |
| `level` | field rw | `int` | USED order |
| `isCastle` | field rw | `int` | not used |
| `publicHealth` | field rw | `int` | not used |
| `scriptRebel` *(modding)* | field rw | `bool` | not used |
| `governorDuration` | field rw | `int` | not used |
| `portAdmiral` | field rw | `character` | not used |
| `lastGovernor` | field rw | `character` | not used |
| `timeSinceLastRebellion` | field rw | `int` | not used |
| `isTradeBlocked` | field rw | `bool` | not used |
| `plagueDuration` | field rw | `int` | not used |
| `gatesAreOpened` | field rw | `bool` | not used |
| `previousOwner` | field rw | `int` | not used |
| `foundingConversionRate` | field rw | `int` | not used |
| `ownerConversionRate` | field rw | `int` | not used |
| `moneySpentConstruction` | field rw | `int` | not used |
| `moneySpentTraining` | field rw | `int` | not used |
| `moneySpentRecruitment` | field rw | `int` | not used |
| `lastHordeFaction` | field rw | `int` | not used |
| `loyaltyLastTurn` | field rw | `int` | not used |
| `settlementTaxLevel` | field rw | `int` | USED report (settlements.(tax,order,queue,can_*)) + order |
| `salliedOut` | field rw | `bool` | not used |
| `readyToSurrender` | field rw | `bool` | not used |
| `siegeHoldoutTurns` | field rw |  | USED report (armies) + order |
| `takenByCrusade` | field rw | `crusadeStruct` | not used |
| `siegeCasualties` | field rw | `int` | not used |
| `unitInQueueCount` | property ro | `int` | USED report (settlements.recruit_queue) |
| `maxHoldoutTurns` | field rw | `int` | not used |
| `siegeDuration` | field rw | `int` | not used |
| `turnsSieged` | field rw |  | not used |
| `factionTradedFrom` | field rw | `int` | not used |
| `turnsOwned` | field rw | start at 10 for settlements owned at game start without specification in descr_strat | not used |
| `subFactionID` | field rw | `int` | not used |
| `yearFounded` | field rw | `int` | not used |
| `isCapital` | field rw | `bool` | not used |
| `isMinorSettlement` | field rw | `bool` | not used |
| `aiProductionController` | field rw | `aiProductionController` | USED other |
| `harvestSuccess` | field rw | `int` | not used |
| `baseFertility` | property rw | `int` | not used |
| `rebelFactionChance` | property rw | `int` | not used |
| `plagued` | field rw | `bool` | not used |
| `plagueDeaths` | field rw | `int` | not used |
| `populationSiegeStart` | field rw | `int` | not used |
| `isProvokedRebellion` | field rw | `int` | not used |
| `populationSize` | property rw | `int` | USED report |
| `recruitmentPoolCount` | field rw | `int` | USED report (settlements.can_recruit) + order |
| `freezeRecruitmentPool` | field rw | `int` | not used |
| `spiesInRecruitmentQueue` | field rw | `int` | not used |
| `assassinsInRecruitmentQueue` | field rw | `int` | not used |
| `diplomatsInRecruitmentQueue` | field rw | `int` | not used |
| `admiralsInRecruitmentQueue` | field rw | `int` | not used |
| `merchantsInRecruitmentQueue` | field rw | `int` | not used |
| `priestsInRecruitmentQueue` | field rw | `int` | not used |
| `settlementStats` | property ro | `settlementStats` | USED report (settlements.(tax,order,queue,can_*)) |
| `characterCount` | property ro | `int` | not used |
| `settlementStatsLastTurn` | property ro | `settlementStats` | not used |
| `turmoil` | property rw | `int` | not used |
| `bannerPosX` *(modding)* | field rw | `float` | not used |
| `bannerPosZ` *(modding)* | field rw | `float` | not used |
| `bannerPosY` *(modding)* | field rw | `float` | not used |
| `getReligion` | function | Get the settlement's specific regligion's value | not used |
| `setReligion` | function | Set the settlement's specific religion's value, make sure the sum of all religion values does not exceed 1.0! | not used |
| `getGuildStanding` | function | Get a settlement's standing points with a specific guild by ID | not used |
| `setGuildStanding` | function | Set the settlement's standing points with specific guild. | not used |
| `buildingsNum` | field rw | `int` | USED report (settlements.buildings) + order |
| `getBuilding` | function | Get a specific building by it's index. | USED report (settlements.buildings) + order |
| `createBuilding` | function | Create a building in the settlement. | not used |
| `destroyBuilding` | function | Destroy a building of a specified type in the settlement. | not used |
| `buildingsQueue` | field rw | `buildingsQueue` | USED report (settlements.queue) + order |
| `resourcesNum` | field rw | `int` | not used |
| `getResource` | function | Get a specific resource by it's index. | not used |
| `siegesNum` | field rw | `int` | USED report |
| `getSiege` | function | Get a specific siege by it's index | USED report |
| `getCharacter` | function | Get a specific character by index. | not used |
| `getSettlementCapability` | function | Get a capability by capability type. | not used |
| `getAgentCapability` | function | Get an agent capability by agent type (only recruitable agents) 0 = spy, 1 = assassin, 2 = diplomat, 3 = prin... | not used |
| `getAgentLimitCapability` | function | Get an agent limit capability by agent type (only recruitable agents) 0 = spy, 1 = assassin, 2 = diplomat, 3 ... | not used |
| `getRecruitmentCapability` | function | Get a recruitment capability by index (max 64!). | not used |
| `recruitmentCapabilityNum` | property ro | `int` | not used |
| `getSettlementRecruitmentPool` | function | Get a recruitment pool by index. | USED report (settlements.can_recruit) + order |
| `upgrade` | function | Upgrade a settlement to the next level. | not used |
| `buildingPresent` | function | Check if settlement has a building line. | not used |
| `buildingPresentMinLevel` | function | Check if settlement has a minimum building level. | not used |
| `getConstructionOptions` | function | Get available construction items. | USED report (settlements.can_build) + order |
| `getRecruitmentOptions` | function | Get available recruitment items. | not used |
| `getUnitInQueue` | function | Get unit in queue. | USED report (settlements.recruit_queue) |
| `createArmyInSettlement` | function | Create an army in a settlement (don't need a character). Used to add units to an empty settlement. | not used |
| `canConstructBuilding` | function | Check if the settlement can construct a building level. | not used |
| `getFortificationLevel` | function | Get fortitication level of the settlement. | not used |
| `createPort` | function | Add a port to a settlement. The port and settlement must be located in the same region. Keep in mind that min... | not used |

### settlementStats (20/51 used)

| member | kind | what it is | status |
|---|---|---|---|
| `population` | field rw | `int` | not used |
| `PopGrowthBaseFarm` | field ro | Get only | not used |
| `PopGrowthFarms` | field ro | Get only | not used |
| `PopGrowthHealth` | field ro | Get only | not used |
| `PopGrowthBuildings` | field ro | Get only | not used |
| `PopGrowthTaxBonus` | field ro | Get only | not used |
| `PopGrowthEntertainment` | field ro | Get only | not used |
| `PopGrowthTrade` | field ro | Get only | not used |
| `PopGrowthGovernorInfluence` | field ro | Get only | not used |
| `PopGrowthSqualor` | field ro | Get only | not used |
| `PopGrowthPlague` | field ro | Get only | not used |
| `PopGrowthTaxPenalty` | field ro | Get only | not used |
| `PublicOrderGarrison` | field ro | Get only | USED report (settlements.(tax,order,queue,can_*)) + other |
| `PublicOrderLaw` | field ro | Get only | USED report (settlements.(tax,order,queue,can_*)) + other |
| `PublicOrderBuildingsEntertainment` | field ro | Get only | USED report (settlements.(tax,order,queue,can_*)) + other |
| `PublicOrderGovernorInfluence` | field ro | Get only | USED report (settlements.(tax,order,queue,can_*)) + other |
| `PublicOrderTaxBonus` | field ro | Get only | USED report (settlements.(tax,order,queue,can_*)) + other |
| `PublicOrderTriumph` | field ro | Get only | not used |
| `PublicOrderPopulationBoom` | field ro | Get only | USED report (settlements.(tax,order,queue,can_*)) + other |
| `PublicOrderEntertainment` | field ro | Get only | USED report (settlements.(tax,order,queue,can_*)) + other |
| `PublicOrderHealth` | field ro | Get only | USED report (settlements.(tax,order,queue,can_*)) + other |
| `PublicOrderReligiousOrder` | field ro | Get only | not used |
| `PublicOrderFear` | field ro | Get only | USED report (settlements.(tax,order,queue,can_*)) + other |
| `PublicOrderGlory` | field ro | Get only | USED report (settlements.(tax,order,queue,can_*)) + other |
| `PublicOrderSqualor` | field ro | Get only | USED report (settlements.(tax,order,queue,can_*)) + other |
| `PublicOrderDistanceToCapital` | field ro | Get only | USED report (settlements.(tax,order,queue,can_*)) + other |
| `PublicOrderNoGovernance` | field ro | Get only | USED report (settlements.(tax,order,queue,can_*)) + other |
| `PublicOrderTaxPenalty` | field ro | Get only | USED report (settlements.(tax,order,queue,can_*)) + other |
| `PublicOrderUnrest` | field ro | Get only | USED report (settlements.(tax,order,queue,can_*)) + other |
| `PublicOrderBesieged` | field ro | Get only | USED report (settlements.(tax,order,queue,can_*)) + other |
| `PublicOrderBlockaded` | field ro | Get only | USED report (settlements.(tax,order,queue,can_*)) + other |
| `PublicOrderCulturalUnrest` | field ro | Get only | USED report (settlements.(tax,order,queue,can_*)) + other |
| `PublicOrderExcommunication` | field ro | Get only | USED report (settlements.(tax,order,queue,can_*)) + other |
| `PublicOrder` | field ro | Get only | USED report (settlements.(tax,order,queue,can_*)) |
| `FarmsIncome` | field ro | Get only | not used |
| `TaxesIncome` | field ro | Get only | not used |
| `MiningIncome` | field ro | Get only | not used |
| `TradeIncome` | field ro | Get only | not used |
| `DiplomaticIncome` | field ro | Get only | not used |
| `DemolitionIncome` | field ro | Get only | not used |
| `LootingIncome` | field ro | Get only | not used |
| `BuildingsIncome` | field ro | Get only | not used |
| `AdminIncome` | field ro | Get only | not used |
| `ConstructionExpense` | field ro | Get only | not used |
| `RecruitmentExpense` | field ro | Get only | not used |
| `DiplomaticExpense` | field ro | Get only | not used |
| `CorruptionExpense` | field ro | Get only | not used |
| `EntertainmentExpense` | field ro | Get only | not used |
| `DevastationExpense` | field ro | Get only | not used |
| `TotalIncomeWithoutAdmin` | field ro | Get only | not used |
| `majorityReligionID` | field rw | `int` | not used |

### siegeStruct (4/10 used)

| member | kind | what it is | status |
|---|---|---|---|
| `besieger` | field rw | `armyStruct` | USED report |
| `siegeTurns` | field rw | `int` | USED report (armies) + order |
| `siegeCasualties` | field rw | `int` | not used |
| `siegeAssaults` | field rw | Amount of times the besieger has assaulted the settlement. | not used |
| `finished` | field rw | `bool` | not used |
| `equipmentQueueCount` | field rw | `int` | USED report (armies) + order |
| `soldierCountStart` | field rw | `int` | not used |
| `besiegedSettlement` | property ro | `settlementStruct` | USED report (armies) + order + other |
| `besiegedFort` | property ro | `fortStruct` | not used |
| `getQueueItem` | function | Get an item in the siege equipment queue by index. | not used |

### siegeEngineStruct (3/13 used)

| member | kind | what it is | status |
|---|---|---|---|
| `xCoord` | field rw | `float` | USED report + order + other ? |
| `zCoord` | field rw | `float` | not used |
| `yCoord` | field rw | `float` | USED report + order + other ? |
| `mass` | field rw | `float` | not used |
| `health` | field rw | `int` | USED report + other ? |
| `angle` | property rw | `int` | not used |
| `currentUnit` | field rw | `unit` | not used |
| `lastUnit` | field rw | `unit` | not used |
| `engineID` | field rw | Unique ID not class! | not used |
| `fireLevel` | field rw | `int` | not used |
| `isBurning` | field rw | `int` | not used |
| `stats` | field rw | `unitStats` | not used |
| `getType` | function | Get the type of the engine (use the enum). | not used |

### settlementRecruitmentPool (2/2 used)

| member | kind | what it is | status |
|---|---|---|---|
| `eduIndex` | field rw | `int` | USED report + order ? |
| `availablePool` | field rw | `float` | USED report (settlements.can_recruit) + order |

### siegeEquipmentQueueItem (2/6 used)

| member | kind | what it is | status |
|---|---|---|---|
| `type` | field rw | `int` | USED report + order + event + other ? |
| `frozen` | field rw | `bool` | not used |
| `valid` | field rw | `bool` | not used |
| `cost` | field rw | `int` | USED report + order + other ? |
| `remainingCost` | field rw | `int` | not used |
| `percentComplete` | field rw | `int` | not used |

### settlementCapability (1/2 used)

| member | kind | what it is | status |
|---|---|---|---|
| `value` | field rw | `int` | USED report ? |
| `bonus` | field rw | `int` | not used |

### minorSettlementBalance (0/10 used)

| member | kind | what it is | status |
|---|---|---|---|
| `incomeModifierBase` | field rw | Default: 0.0 | not used |
| `growthModifierBase` | field rw | Default: 0.25 | not used |
| `incomeModifierAllianceOffset` *(modding)* | field rw | Default: 0.30 | not used |
| `growthModifierAllianceOffset` *(modding)* | field rw | Default: 0.40 | not used |
| `incomeModifierNeutralOffset` *(modding)* | field rw | Default: 0.15 | not used |
| `growthModifierNeutralOffset` *(modding)* | field rw | Default: 0.20 | not used |
| `incomeModifierTradeRightsOffset` *(modding)* | field rw | Default: 0.30 | not used |
| `growthModifierTradeRightsOffset` *(modding)* | field rw | Default: 0.15 | not used |
| `incomeModifierOwnFaction` | field rw | Default: 0.75 | not used |
| `growthModifierOwnFaction` | field rw | Default: 0.75 | not used |

## Army and unit

419 members, 32 used (+20 by name only).

### armyStruct (18/83 used)

| member | kind | what it is | status |
|---|---|---|---|
| `faction` | field rw | `factionStruct` | USED report + order + event + other ? |
| `isAdmiral` | field rw | `bool` | USED report (armies, armies.leader) + order |
| `supportingArmiesCampaign` | field rw | `int` | not used |
| `canRetreat` | field rw | `bool` | not used |
| `upkeepModifier` | field rw | `int` | not used |
| `battleLadders` | field rw | How many left in battle. | not used |
| `battleRams` | field rw | How many left in battle. | not used |
| `battleOutcome` | field rw | `int` | not used |
| `battleTowers` | field rw | How many left in battle. | not used |
| `deadUnitsNum` | field rw | `int` | not used |
| `xCoord` | property ro | `int` | USED report (armies.leader) + order |
| `yCoord` | property ro | `int` | USED report (armies.leader) + order |
| `ladders` | field rw | `int` | not used |
| `rams` | field rw | `int` | not used |
| `bannerRed` *(modding)* | field rw | `int` | not used |
| `bannerBlue` *(modding)* | field rw | `int` | not used |
| `rebelEntry` | field rw | `rebelFaction` | not used |
| `bannerGreen` *(modding)* | field rw | `int` | not used |
| `bannerSet` *(modding)* | field rw | `bool` | not used |
| `hiddenUnitCount` | field rw | `int` | not used |
| `maxGroups` | field rw | `int` | not used |
| `towers` | field rw | `int` | not used |
| `siege` | field rw | Current siege. | USED report (armies) + order + other |
| `reformPointX` | field rw | `int` | not used |
| `reformPointY` | field rw | `int` | not used |
| `isReinforcing` | field rw | Actively reinforcing (moving units into the battlefield). | not used |
| `inBattle` | field rw | `bool` | not used |
| `routedBattle` | field rw | `bool` | not used |
| `moraleBroken` | field rw | `bool` | not used |
| `finishedBattle` | field rw | Just fought a battle. | not used |
| `isReinforcement` | field rw | `bool` | not used |
| `generalDeathTimer` | field rw | `int` | not used |
| `generalRoutTimer` | field rw | `int` | not used |
| `regionID` | field rw | `int` | not used |
| `subFactionID` | field rw | `int` | not used |
| `totalStrengthStart` | field rw | `int` | not used |
| `generalCommandRadius` | field rw | `number` | not used |
| `generalBattleCommand` | field rw | `int` | not used |
| `alliance` | field rw | `int` | USED report + order ? |
| `isHalfDestroyed` | field rw | `bool` | not used |
| `tired` | field rw | `bool` | not used |
| `commandingArmy` | field rw | if not leading army but reinforcement | not used |
| `commandingArmyThatGivesCommands` | field rw | reinforcement and listening to player commands | not used |
| `sortStack` | function | Sort units in a stack. Use the sortType enum to specify the sorting mode. | not used |
| `getUnit` | function | Get a unit by it's index. | USED report (armies, armies.troops) + order + other |
| `numOfUnits` | field rw | `int` | USED report (armies, armies.troops) + order + other |
| `getCharacter` | function | Get a character (agent or non-leading named character) by it's index. | not used |
| `numOfCharacters` | field rw | Includes Auxiliary generals and agents (i.e all characters excluding the leading general) | not used |
| `boardedArmy` | field rw | army embarked on this fleet stack | USED report (armies) + order |
| `shipArmy` | field rw | fleet that this army stack is embarked on | USED report (armies) + order |
| `blockedPort` | field rw | `dockStruct` | not used |
| `leader` | field rw | Returns nil if stack is inside residence (fleet, settlement, fort). | USED report (armies.leader, armies.troops) + order + other |
| `findInSettlement` | function | Find the settlement in which the army is located. Returns nil if the army is not in a settlement. Returns nil... | USED report (armies, visible_enemies/seen_agents/nearby_settlements) + order + other |
| `findInFort` | function | Find the fort in which the army is located. Returns nil if the army is not in a fort. Returns nil if the army... | not used |
| `totalStrength` | field rw | `int` | USED report (armies, visible_enemies/seen_agents/nearby_settlements) + order |
| `reform_point_x` | field rw | X coordinate to which the retreating units will go. | not used |
| `reform_point_y` | field rw | Y coordinate to which the retreating units will go. | not used |
| `createEOPUnit` | function |  | not used |
| `createUnit` | function | Create a unit in the army by type from export\_descr\_unit.txt | not used |
| `createUnitByIDX` | function | Create a unit in the army by index from export\_descr\_unit.txt | USED other |
| `mergeArmies` | function | Merge 2 armies on the strat map. Does nothing if the total size of the new army exceeds 20 units. | USED order |
| `siegeSettlement` | function | Besiege the specified settlement, or attack it if already besieging it. Requires movement points. | USED order + other |
| `siegeFort` | function | Besiege the specified fort, or attack it if already besieging it. Requires movement points. | not used |
| `blockadePort` | function | Blockade a port. | USED order |
| `liftSiege` | function | Lift an active siege. | not used |
| `liftBlockade` | function | Lift an active blockade. | not used |
| `attackArmy` | function | Attack another army. Requires movement points. | USED order |
| `getDeadUnit` | function | Get dead unit at index. | not used |
| `getGroup` | function | Get unit group at index. | not used |
| `defineUnitGroup` | function | Define a new unit group with a label. | not used |
| `setAiActiveSet` | function | Set ai active set to a value for the whole army (0 = inacitve, 1 = active, 2 = script controlled) | not used |
| `releaseUnits` | function | Set ai active set to on or off depending if army is player controlled | not used |
| `buildWatchTower` | function | Build a watchtower (payment applies) | not used |
| `canStartSiege` | function | Does army have the capability to start a siege? (infantry units to carry equipment or siege engines) | not used |
| `canStartSiegeFort` | function | Does army have the capability to start a siege? (infantry units to carry equipment or siege engines) | not used |
| `canStartAssault` | function | Does army have the capability to start an assault? | not used |
| `canStartAssaultFort` | function | Does army have the capability to start an assault? | not used |
| `isEnemyTo` | function | Is another army at war with this army? | not used |
| `isAllyTo` | function | Is another army allied to this army? | not used |
| `isEnemyToFaction` | function | Is this army at war with this faction? | not used |
| `isAllyToFaction` | function | Is this army allied to this faction? | not used |
| `moveTactical` | function | Move to specified position, merge with other armies if they occupy the same tile, find close tile if the targ... | not used |
| `getNumberOfCategory` | function | Get number of units in this army of a specific category | not used |

### unit (11/93 used)

| member | kind | what it is | status |
|---|---|---|---|
| `eduEntry` | field rw | `eduEntry` | USED report (armies.troops, settlements.recruit_queue) + order + other |
| `aiActiveSet` | field rw | 0 means inactive, 1 means active, 2 means labelled unit (for Battle) | not used |
| `movePoints` | property rw | `float` | not used |
| `soldierCountStratMap` | property rw | soldiers count. You can change it on stratmap and soldiers updated. Use @{setParams} if you need change sever... | USED report (armies, armies.troops) + order + other |
| `exp` | property rw | soldiers expierence. You can change it on stratmap and soldiers updated. Use @{setParams} if you need change ... | USED report (armies.troops) + order |
| `armourLVL` | property rw | soldiers armour. You can change it on stratmap and soldiers updated. Use @{setParams} if you need change seve... | USED order |
| `weaponLVL` | property rw | soldiers weapon. You can change it on stratmap and soldiers updated. Use @{setParams} if you need change seve... | USED order |
| `soldierCountStratMapMax` | property ro | Read only | USED report (armies.troops) + order + other |
| `soldierCountBattleMap` | field ro | Read only | not used |
| `unitPositionData` | field rw | `unitPositionData` | not used |
| `character` | field rw | `character` | USED order |
| `flankRightState` | field rw | `int` | not used |
| `flankLeftState` | field rw | `int` | not used |
| `flankRearState` | field rw | `int` | not used |
| `flankRightThreat` | field rw | `unit` | not used |
| `flankLeftThreat` | field rw | `unit` | not used |
| `flankRearThreat` | field rw | `unit` | not used |
| `crusadeState` | field rw | >0 means crusading, <0 means disbaning, 0 means no crusade | not used |
| `crusade` | field rw | `crusadeStruct` | not used |
| `soldiersFled` | field rw | `int` | not used |
| `aiGroupData` | field rw | `unitAiGroupData` | not used |
| `isInfighting` | field rw | `bool` | not used |
| `unitStats` | field rw | `unitStats` | not used |
| `isCloseFormation` | field rw | `int` | not used |
| `moraleLevel` | property rw | use moraleStatus enum | not used |
| `inPlayableArea` | property rw | `bool` | not used |
| `isHidden` | property rw | `bool` | not used |
| `canBeSeen` | property rw | `bool` | not used |
| `hasBeenSeen` | property rw | `bool` | not used |
| `inFormation` | property rw | `bool` | not used |
| `isMercenary` | property rw | `bool` | not used |
| `stakesUsed` | property rw | `bool` | not used |
| `specialAbilityActive` | property rw | `bool` | not used |
| `holyInspired` | property rw | `bool` | not used |
| `dead` | property rw | `bool` | not used |
| `unableToFire` | property rw | `bool` | not used |
| `battlePosX` | field rw | (battle) | not used |
| `battlePosZ` | field rw | (battle) | not used |
| `battlePosY` | field rw | (battle) | not used |
| `officer1` | field rw | `generalBattleStruct` | not used |
| `officer2` | field rw | `generalBattleStruct` | not used |
| `officer3` | field rw | `generalBattleStruct` | not used |
| `generalInfo` | field rw | `generalBattleStruct` | not used |
| `generalArmy` | field rw | `generalBattleStruct` | not used |
| `angle` | property rw | (battle) | not used |
| `unitGroup` | field rw | `unitGroup` | not used |
| `fatigue` | field rw | (battle) | not used |
| `maxAmmo` | field rw | (battle) | not used |
| `ID` | field rw | `int` | not used |
| `currentAmmo` | field rw | (battle) | not used |
| `siegeEngineNum` | property ro | (only infantry and artillery units!) | not used |
| `army` | field rw | `armyStruct` | USED order + event ? |
| `retrainingSettlement` | field rw | `settlementStruct` | USED order |
| `supplies` | field rw | `int` | not used |
| `nearbyFriendlyUnitsNum` | field rw | `int` | not used |
| `nearbyEnemyUnitsNum` | field rw | `int` | not used |
| `kill` | function | Kill this unit. It disbands the unit, including returning to recruitment pool if disband_to_pools is true for... | USED order |
| `destroy` | function | It destroys the unit without returning it to the recruitment pool. It destroys a fleet on the high seas, even... | not used |
| `setParams` | function | Set unit basic parameters | not used |
| `alias` | property rw | `string` | not used |
| `hasAttribute` | function | Check if unit has edu attribute. | not used |
| `hasBattleProperty` | function | Check if unit has guard mode, skirmish or fire at will on. | not used |
| `setBattleProperty` | function | Set a unit battle property (guard mode, skirmish or fire at will). | not used |
| `getActionStatus` | function | Get unit action status in battle ( idling, hiding, ready, reforming, moving, withdrawing, missiles\_firing, m... | not used |
| `getActionStatusInt` | function | Get unit action status in battle (use enum, faster than string). | not used |
| `isMovingFastSet` | function | Is unit set to run? | not used |
| `setMovingFastSet` | function | Toggle unit running. | not used |
| `isOnWalls` | function | Is unit on walls? | not used |
| `isEngaged` | function | Is unit engaged in melee? | not used |
| `isUnderFire` | function | Is unit under fire? | not used |
| `getMountClass` | function | Get unit mount class. | not used |
| `getFormation` | function | Get unit formation type. | not used |
| `moveToPosition` | function | Orders the unit to move to the specified position. | not used |
| `immediatePlace` | function | Immediately positions the unit at the given location. | not used |
| `attackClosestUnit` | function | Searches an arc in front of the unit, and attacks the closest enemy found. | not used |
| `attackUnit` | function | Orders the unit to attack another unit. | not used |
| `deployStakes` | function | Deploys stakes. | not used |
| `changeFormation` | function | Changes the unit's formation. | not used |
| `halt` | function | Orders the unit to stop it's orders. | not used |
| `moveToOrientation` | function | Orders the unit to move to the specified position with a specified rotation and orientation. | not used |
| `moveRelative` | function | Orders the unit to move to the specified position. | not used |
| `moveToMissileRange` | function | Orders the attacker to move into missile range of the target. | not used |
| `turn` | function | Turn to an absolute angle or by an angle relative to it's current rotation. | USED event + other ? |
| `taunt` | function | Makes the unit taunt. | not used |
| `useSpecialAbility` | function | Makes the unit perform their special ability. | not used |
| `getSiegeEngine` | function | Get Siege engine. | not used |
| `attackBuilding` | function | Order a unit with appropriate siege equipment to attack an appropriate building (including docking towers/lad... | not used |
| `collectEngine` | function | Order an infantry unit to collect an engine (ram/ladder/tower). | not used |
| `getNearbyFriendlyUnit` | function | Get Nearby friendly unit. | not used |
| `getNearbyEnemyUnit` | function | Get Nearby Enemy unit. | not used |
| `releaseUnit` | function | Set ai active set to on or off depending on if the unit is player controlled. | not used |
| `isFiring` | function | Check if action status is firing or reloading. | not used |
| `isIdle` | function | Check if action status is idle or hiding or taunting or celebrating or ready. | not used |

### eduEntry (7/102 used)

| member | kind | what it is | status |
|---|---|---|---|
| `eduType` | property rw | Get only | USED report + order + other ? |
| `soldier` | property rw | Get only | not used |
| `unitCardTga` *(modding)* | property rw | Get only | not used |
| `infoCardTga` *(modding)* | property rw | Get only | not used |
| `infoPicDir` | property rw | `string` | not used |
| `cardPicDir` | property rw | `string` | not used |
| `localizedName` | property rw | `string` | USED report + other ? |
| `localizedDescription` | property rw | `string` | not used |
| `localizedDescriptionShort` | property rw | `string` | not used |
| `index` | field ro | Get only | not used |
| `unitCreatedCounter` | field ro | Get only | not used |
| `soldierCount` | field rw | `int` | not used |
| `mass` | field rw | `float` | not used |
| `width` | field rw | `float` | not used |
| `primaryStats` | field rw | `attackStats` | not used |
| `secondaryStats` | field rw | `attackStats` | not used |
| `tertiaryStats` | field rw | `attackStats` | not used |
| `engineStats` | field rw | `attackStats` | not used |
| `mountStats` | field rw | `attackStats` | not used |
| `animalStats` | field rw | `attackStats` | not used |
| `primaryDefenseStats` | field rw | `defenseStats` | not used |
| `secondaryDefenseStats` | field rw | `defenseStats` | not used |
| `mountDefenseStats` | field rw | `defenseStats` | not used |
| `animalDefenseStats` | field rw | `defenseStats` | not used |
| `height` | field rw | `float` | not used |
| `training` | field rw | `int` | USED report |
| `discipline` | field rw | `int` | not used |
| `mount` | field rw | `mountStruct` | not used |
| `canPhalanx` | field rw | `int` | not used |
| `moveSpeedMod` | field rw | `float` | not used |
| `unitSpacingFrontToBackClose` | field rw | `float` | not used |
| `unitSpacingSideToSideClose` | field rw | `float` | not used |
| `unitSpacingFrontToBackLoose` | field rw | `float` | not used |
| `unitSpacingSideToSideLoose` | field rw | `float` | not used |
| `statHealth` | field rw | `int` | not used |
| `statHealthAnimal` | field rw | `int` | not used |
| `statHeat` | field rw | `int` | not used |
| `statScrub` | field rw | `int` | not used |
| `statSand` | field rw | `int` | not used |
| `statForest` | field rw | `int` | not used |
| `statSnow` | field rw | `int` | not used |
| `recruitTime` | field rw | `int` | USED report + order ? |
| `recruitCost` | field rw | `int` | USED report (settlements.can_recruit) + order |
| `upkeepCost` | field rw | `int` | USED report (settlements.can_recruit) + order |
| `weaponCost` | field rw | `int` | not used |
| `armourCost` | field rw | `int` | not used |
| `customBattleCost` | field rw | `int` | not used |
| `customBattleIncrease` | field rw | `int` | not used |
| `customBattleLimit` | field rw | `int` | not used |
| `morale` | field rw | `int` | not used |
| `moraleLocked` | field rw | `int` | not used |
| `statFood1` | field rw | `int` | not used |
| `statFood2` | field rw | `int` | not used |
| `category` | field ro | Get only | not used |
| `primaryAnim` | property ro | `string` | not used |
| `secondaryAnim` | property ro | `string` | not used |
| `class` | field ro | Get only | not used |
| `categoryClassCombo` | field ro | Get only | not used |
| `recruitPriorityOffset` *(modding)* | field rw | times 4 | not used |
| `crusadingUpkeepModifier` | field rw | `float` | not used |
| `aiUnitValuePerSoldier` | field rw | `float` | not used |
| `aiUnitValue` | field rw | `float` | not used |
| `haveAttributeLegio` | property rw |  | not used |
| `legio` | property rw | `bool` | not used |
| `hideForest` | property rw | `bool` | not used |
| `hideImprovedForest` | property rw | `bool` | not used |
| `hideLongGrass` | property rw | `bool` | not used |
| `hideAnywhere` | property rw | `bool` | not used |
| `powerCharge` | property rw | `bool` | not used |
| `seaFaring` | property rw | `bool` | not used |
| `command` | property rw | `bool` | USED event ? |
| `heavyUnit` | property rw | `bool` | not used |
| `hardy` | property rw | `bool` | not used |
| `veryHardy` | property rw | `bool` | not used |
| `slave` | property rw | `bool` | not used |
| `frightenFoot` | property rw | `bool` | not used |
| `frightenMounted` | property rw | `bool` | not used |
| `freeUpkeepUnit` | property rw | `bool` | not used |
| `gunpowderUnit` | property rw | `bool` | not used |
| `gunpowderArtillery` | property rw | `bool` | not used |
| `fireByRank` | property rw | `bool` | not used |
| `startNotSkirmishing` | property rw | `bool` | not used |
| `mercenaryUnit` | property rw | `bool` | not used |
| `noCustom` | property rw | `bool` | not used |
| `isPeasant` | property rw | `bool` | not used |
| `generalUnit` | property rw | `bool` | not used |
| `generalUnitUpgrade` | property rw | `bool` | not used |
| `cantabrianCircle` | property rw | `bool` | not used |
| `druid` | property rw | `bool` | not used |
| `screechingWomen` | property rw | `bool` | not used |
| `warCry` | property rw | `bool` | not used |
| `stakes` | property rw | `bool` | not used |
| `canSkirmish` | property rw | `bool` | not used |
| `hasOwnership` | function | Check if a faction has ownership of this entry. | not used |
| `setOwnership` | function | Set if a faction has ownership of this entry. | not used |
| `hasAttribute` | function | Check if the entry has an attribute. | not used |
| `getArmourLevelNum` | function | Get number of armour levels. | not used |
| `getArmourModelNum` *(modding)* | function | Get number of armour models. | not used |
| `getArmourLevel` | function | Get armour level at index. | not used |
| `getArmourModel` *(modding)* | function | Get armour model at index. | not used |
| `setArmourLevel` | function | Set armour level at index. | not used |
| `setArmourModel` *(modding)* | function | Set armour model at index. | not used |

### unitInQueue (7/15 used)

| member | kind | what it is | status |
|---|---|---|---|
| `recruitType` | field rw | 0 = normal, 1 = ship, 2 = agent, 3 = retraining 4 = retraining ship | USED report (settlements.recruit_queue) |
| `experience` | field rw | `int` | not used |
| `armourUpg` | field rw | `int` | not used |
| `weaponUpg` | field rw | `int` | not used |
| `eduEntry` | property rw | `eduEntry` | not used |
| `agentType` | property rw | `int` | not used |
| `retrainingUnit` | property rw | `unit` | not used |
| `soldierCount` | field rw | `int` | not used |
| `cost` | field rw | `int` | USED report + order + other ? |
| `recruitTime` | field rw | `int` | USED report + order ? |
| `turnsTrained` | field rw | `int` | USED report (settlements.recruit_queue) |
| `settlement` | field rw | `settlementStruct` | USED report + order + event + other ? |
| `turnNumber` | field rw | `int` | USED report + order + event + other ? |
| `isMercenary` | field rw | `int` | not used |
| `addUnitToQueue` | function | Add a unit to the recruitment queue. | USED report + order |

### unitGroup (3/35 used)

| member | kind | what it is | status |
|---|---|---|---|
| `unitsInFormationNum` | field rw | `int` | not used |
| `unitsNotInFormationNum` | field rw | `int` | not used |
| `unitNumTotal` | field rw | `int` | not used |
| `xCoord` | field rw | `float` | USED report + order + other ? |
| `yCoord` | field rw | `float` | USED report + order + other ? |
| `angle` | field rw | `int` | not used |
| `automationType` | field rw | 1 = defend, 2 = attack | not used |
| `defendXCoord` | field rw | if automated defend (1) | not used |
| `defendYCoord` | field rw | if automated defend (1) | not used |
| `defendRadius` | field rw | if automated defend (1) | not used |
| `targetUnit` | field rw | if automated attack (2) | not used |
| `newAutomationType` | field rw | 1 = defend, 2 = attack (setting this passes info from new fields to active fields) | not used |
| `newDefendXCoord` | field rw | if automated defend (1) | not used |
| `newDefendYCoord` | field rw | if automated defend (1) | not used |
| `newDefendRadius` | field rw | if automated defend (1) | not used |
| `newTargetUnit` | field rw | if automated attack (2) | not used |
| `addUnit` | function | Add a unit to the group (won't add if unit already in group). | not used |
| `removeUnit` | function | Remove a unit from a group. | not used |
| `undefine` | function | Undefine a unit group. | not used |
| `automate` | function | Toggle group automation. | not used |
| `automateAttack` | function | Automate group attack. | not used |
| `automateDefense` | function | Automate group defense. | not used |
| `getUnitInFormation` | function | Get a unit in the group's formation (not given individual commands). Once you give a unit a command once it s... | not used |
| `getUnitNotInFormation` | function | Get a unit not in the group's formation (not given individual commands). Once you give a unit a command once ... | not used |
| `place` | function | Place a group at a location. | not used |
| `changeUnitFormation` | function | Change the group's units formations. | not used |
| `moveToMissileRangeOfGroup` | function | Move to put an enemy group inside your missile range. | not used |
| `moveToMissileRangeOfUnit` | function | Move to put an enemy unit inside your missile range. | not used |
| `attackGroup` | function | Attack another group. | not used |
| `halt` | function | Halt the group's orders. | not used |
| `moveFormed` | function | Move to the specified location in formation. | not used |
| `moveUnformed` | function | Move to the specified location not in formation. | not used |
| `moveRelativeFormed` | function | Move to the specified location in formation. | not used |
| `moveRelativeUnformed` | function | Move to the specified location not in formation. | not used |
| `turn` | function | Turn the group either relative or absolute. | USED event + other ? |

### M2TWEOPDU (1/12 used)

| member | kind | what it is | status |
|---|---|---|---|
| `addEopEduEntryFromFile` *(modding)* | function | Create new M2TWEOPDU entry from a file describing it. | not used |
| `addEopEduEntryFromEDUID` | function | Create new M2TWEOPDU entry. | not used |
| `getEopEduEntryByID` | function | Get eduEntry of a M2TWEOPDU entry. Needed to change many parameters of the entry. | not used |
| `getEduEntry` | function | Get eduEntry by index. Needed to change many parameters of the entry. | USED report (settlements.can_recruit) + order |
| `getEduEntryNum` | function | Get number of units in vanilla EDU. | not used |
| `getEopEntryNum` | function | Get number of units in EOP EDU. | not used |
| `getEduEntryByType` | function | Get eduEntry by EDU type name. Needed to change many parameters of the entry. Works for EOP units too. | not used |
| `getEduIndexByType` | function | Get EDU index by EDU type name. Needed to change many parameters of the entry. Works for EOP units too. | not used |
| `setEntrySoldierModel` *(modding)* | function | Set unit info card for a M2TWEOPDU entry. Requirements for the location and parameters of the image are uncha... | not used |
| `getEopEduEntryIterating` | function | Get an eop entry by using its index in the EOP database, not edu index! | not used |
| `findGeneralUnit` | function | Get the faction's standard bodyguard unit. | not used |
| `findGeneralUpgradeUnit` | function | Get the faction's standard bodyguard upgrade unit. | not used |

### attackStats (1/31 used)

| member | kind | what it is | status |
|---|---|---|---|
| `isValid` | property rw | `bool` | not used |
| `isMissile` | property rw | `bool` | not used |
| `isSpear` | property rw | `bool` | not used |
| `isLightSpear` | property rw | `bool` | not used |
| `isPrec` | property rw | `bool` | not used |
| `isAP` | property rw | `bool` | not used |
| `isBP` | property rw | `bool` | not used |
| `isArea` | property rw | `bool` | not used |
| `isFire` | property rw | `bool` | not used |
| `isBodyLaunching` | property rw | `bool` | not used |
| `isThrown` | property rw | `bool` | not used |
| `isShortPike` | property rw | `bool` | not used |
| `isLongPike` | property rw | `bool` | not used |
| `isSpearBonus12` | property rw | `bool` | not used |
| `isSpearBonus10` | property rw | `bool` | not used |
| `isSpearBonus8` | property rw | `bool` | not used |
| `isSpearBonus6` | property rw | `bool` | not used |
| `isSpearBonus4` | property rw | `bool` | not used |
| `attack` | property rw | `int` | USED report + order + event ? |
| `charge` | property rw | `int` | not used |
| `ammo` | property rw | `int` | not used |
| `range` | field rw | `int` | not used |
| `rangeSquared` | field rw | `float` | not used |
| `projectile` | field rw | `projectileStruct` | not used |
| `weaponType` | field rw | `int` | not used |
| `techType` | field rw | `int` | not used |
| `damageType` | field rw | `int` | not used |
| `soundType` *(modding)* | field rw | `int` | not used |
| `minAttackDelayPri` | field rw | `int` | not used |
| `weaponFX` | field rw | `string` | not used |
| `isShieldPiercing` | property rw | `bool` | not used |

### capturedUnit (1/3 used)

| member | kind | what it is | status |
|---|---|---|---|
| `unit` | field rw | `unit` | USED report + order + other ? |
| `capturedSoldiers` | field rw | `int` | not used |
| `capturedValue` | field rw | `int` | not used |

### mercPool (1/4 used)

| member | kind | what it is | status |
|---|---|---|---|
| `name` | field rw | `string` | USED report + order + event + other ? |
| `getMercUnitNum` | function | Get amount of mercenary units a region has. | not used |
| `addMercUnit` | function | Add a new mercenary unit to a pool. | not used |
| `getMercUnit` | function | Get a mercenary unit from a pool by index. | not used |

### mercPoolUnit (1/14 used)

| member | kind | what it is | status |
|---|---|---|---|
| `eduEntry` | field rw | `eduEntry` | not used |
| `experience` | field rw | `int` | not used |
| `cost` | field rw | `int` | USED report + order + other ? |
| `replenishMin` | field rw | `float` | not used |
| `replenishMax` | field rw | `float` | not used |
| `maxUnits` | field rw | `int` | not used |
| `currentPool` | field rw | `float` | not used |
| `startYear` | field rw | `int` | not used |
| `endYear` | field rw | `int` | not used |
| `crusading` | field rw | `int` | not used |
| `poolIndex` | field rw | `int` | not used |
| `mercPoolUnitIndex` | field rw | `int` | not used |
| `mercPool` | field rw | `mercPool` | not used |
| `setMercReligion` | function | Set or remove a religion requirement for a mercenary unit. | not used |

### unitPositionData (1/16 used)

| member | kind | what it is | status |
|---|---|---|---|
| `engagedUnitsNum` | field rw | `int` | not used |
| `unit` | field rw | `unit` | USED report + order + other ? |
| `isOnWallsCount` | field rw | (amount of walls | not used |
| `isInTowerCount` | field rw | (amount of towers) | not used |
| `isInGateHouseCount` | field rw | (amount of gatehouses) | not used |
| `hasTargets` | field rw | `bool` | not used |
| `combatStatus` | field rw | use enum: combatStatus | not used |
| `isHalted` | field rw | `bool` | not used |
| `lastTargetCoordX` | field rw | dont set | not used |
| `lastTargetCoordY` | field rw | dont set | not used |
| `towersUnderFireFromCount` | field rw | `int` | not used |
| `unitsUnderFireFromCount` | field rw | `int` | not used |
| `getUnitUnderFireFrom` | function | Get unit that is firing at this unit. | not used |
| `getEngagedUnit` | function | Get unit that is fighting this unit in melee. | not used |
| `getTargetUnit` | function | Get the unit this unit is currently targeting. | not used |
| `getActionType` | function | Get unit's current action type (use enum). | not used |

### unitAiGroupData (0/4 used)

| member | kind | what it is | status |
|---|---|---|---|
| `group` | field rw | `unitGroup` | not used |
| `battleObjective` | field rw | `battleObjective` | not used |
| `inMelee` | field rw | `bool` | not used |
| `isAvailable` | field rw | `bool` | not used |

### unitStats (0/7 used)

| member | kind | what it is | status |
|---|---|---|---|
| `chargeBonus` | property rw | `int` | not used |
| `chargeDecay` | property rw | `int` | not used |
| `attackInBattle` | field rw | `int` | not used |
| `armourInBattle` | field rw | `int` | not used |
| `formationDefBonus` | field rw | `int` | not used |
| `formationAttBonus` | field rw | `int` | not used |
| `generalsBonus` | field rw | `int` | not used |

## Strategy map, tiles and regions

199 members, 19 used (+8 by name only).

### regionStruct (9/74 used)

| member | kind | what it is | status |
|---|---|---|---|
| `regionName` | field rw | `string` | USED report (crossings, resources) + order + event |
| `settlementName` | field rw | `string` | not used |
| `localizedName` | property rw | `string` | USED report + other ? |
| `legioName` | field rw | `string` | not used |
| `colorRed` *(modding)* | field rw | `int` | not used |
| `colorGreen` *(modding)* | field rw | `int` | not used |
| `colorBlue` *(modding)* | field rw | `int` | not used |
| `regionID` | field rw | `int` | not used |
| `landingPointsCount` | field rw | `int` | not used |
| `loyaltyFactionID` | field rw | `int` | not used |
| `roadLevel` | field rw | as set in descr_strat | not used |
| `farmingLevel` | field rw | as set in descr_strat | not used |
| `famineThreat` | field rw | `int` | not used |
| `harvestSuccess` | field rw | `int` | not used |
| `totalTradeValue` | field rw | `int` | not used |
| `seaConnectedRegionsCount` | field rw | `int` | not used |
| `seaImportRegionsCount` | field rw | `int` | not used |
| `landMass` | field rw | `landMass` | not used |
| `roadToPort` | field rw | `roadStruct` | not used |
| `patrolPointsCount` | field rw | `int` | not used |
| `devastatedTilesCount` | field rw | `int` | not used |
| `tilesBorderingEdgeOfMapCount` | field rw | `int` | not used |
| `fertileTilesCount` | field rw | `int` | not used |
| `resourceTypesBitMap` | field rw | `int` | not used |
| `stacksNum` | field rw |  | not used |
| `armyCount` | field rw | `int` | not used |
| `fortsNum` | field rw |  | not used |
| `fortCount` | field rw | `int` | not used |
| `watchtowersNum` | field rw |  | not used |
| `watchtowerCount` | field rw | `int` | not used |
| `settlementCount` | property ro | `int` | not used |
| `isSea` | field rw | `bool` | not used |
| `peninsular` | field rw | `bool` | not used |
| `mercPool` | field rw | `mercPool` | not used |
| `settlement` | field rw |  | USED report (resources) |
| `regionCapital` | field rw | `settlementStruct` | not used |
| `tileCount` | field rw | `int` | not used |
| `neighbourRegionsNum` | field rw | `int` | not used |
| `resourcesNum` | field rw |  | USED report (resources) |
| `resourceCount` | field rw | `int` | not used |
| `settlementXCoord` | field rw |  | not used |
| `settlementYCoord` | field rw |  | not used |
| `regionCapitalX` | field rw | `int` | not used |
| `regionCapitalY` | field rw | `int` | not used |
| `portEntranceXCoord` | field rw | `int` | USED report + order |
| `portEntranceYCoord` | field rw | `int` | USED report + order |
| `faction` | field rw | `factionStruct` | USED report + order + event + other ? |
| `rebelType` | field rw | `string` | not used |
| `localizedRebelsName` | property rw | `string` | not used |
| `triumphValue` | field rw | `int` | not used |
| `getArmy` | function | Get an army by it's index. | not used |
| `getStack` | function |  | not used |
| `getFort` | function | Get a fort by it's index. | not used |
| `getSettlement` | function | Get a settlement by it's index (iterating). | USED other ? |
| `getWatchtower` | function | Get a watchtower by it's index. | not used |
| `getResource` | function | Get a resource by it's index. | USED report (resources) |
| `getNeighbour` | function | Get a neighbour region by it's index. | not used |
| `getHiddenResource` | function | Check if a region has a hidden resource. | not used |
| `setHiddenResource` | function | Set a region's hidden resource | not used |
| `getSeaConnectedRegion` | function | Get a region that is reachable from this region. | not used |
| `getSeaImportRegion` | function | Get a region this region is importing trade goods from. | not used |
| `getRegionSeaEdge` | function | Get a region sea edge (point where it borders both sea and another land region). | not used |
| `getDevastatedTile` | function | Get a devastated tile. | not used |
| `getTileBorderingEdgeOfMap` | function | Get a tile that borders the edge of the map. | not used |
| `getTile` | function | Get a tile by index. | not used |
| `getLandingPoint` | function | Get a landing point by index. | not used |
| `getFertileTile` | function | Get a fertile tile by index. | not used |
| `getReligionHistory` | function | Get religion amount from a set number of turns ago. | not used |
| `hasResourceType` | function | Check if region has a resource type. | not used |
| `getResourcesValue` | function | Get total value of all resources in the region. | not used |
| `hasFaction` | function | Check if the region contains a settlement owned by the specified faction. | not used |
| `getEnemySettsToFaction` | function | Get number of settlements in the region that are hostile to specified faction. | not used |
| `getNeutralSettsToFaction` | function | Get number of settlements in the region that are neutral to specified faction. | not used |
| `getHostileArmiesStrength` | function | Get the strength total of all armies in this region that are hostile to a specific faction. | not used |

### stratMap (8/27 used)

| member | kind | what it is | status |
|---|---|---|---|
| `mapWidth` | field rw | `int` | USED report (crossings) + order |
| `isLoaded` | field rw | `bool` | not used |
| `mapHeight` | field rw | `int` | USED report (crossings) + order |
| `regionsNum` | field rw | `int` | USED report (resources, visible_enemies/seen_agents/nearby_settlements) + order |
| `volcanoesNum` | field rw | `int` | not used |
| `landConnectionsNum` | field rw | `int` | USED report (crossings) + order |
| `landMassNum` | field rw | `int` | not used |
| `getRegion` | function | Get a specific region by index. | USED report (crossings, resources) + order + event |
| `getTile` | function | Get a specific tile by it's coordinates. | USED report (crossings) + order |
| `getVolcanoCoords` | function | Get a volcano's coordinates. | not used |
| `getLandConnection` | function | Get a land connection's coordinates (the green arrows on the map that allow you to cross bodies of water). | USED report (crossings) + order |
| `getLandMass` | function | Get a landmass (collection of regions reachable by land, like a continent or island). | not used |
| `getSettlement` | function | Get a settlement by its internal name. This is the intended way to get a settlement quickly by it's name. | USED order |
| `getRegionByName` | function | Get a region by its internal name. | not used |
| `moveCamera` *(ui)* | function | Slowly move the camera to the specified tile. | not used |
| `jumpCamera` *(ui)* | function | Quickly move the camera to the specified tile. | not used |
| `zoomCamera` *(ui)* | function | Set the zoom level of the camera. | not used |
| `startDrawModelAt` *(modding)* | function | Start drawing .cas campaign strategy model with a unique ID in some coords. Can be used at any time. | not used |
| `stopDrawModel` *(modding)* | function | Stop drawing .cas campaign strategy model with a unique ID. Can be used at any time. | not used |
| `replaceTile` | function | Replace a custom tile. Change the custom battlefield on the specified coordinates. Note: You must have at lea... | not used |
| `setOwnExtentsColor` *(modding)* | function | Set movement extents color. | not used |
| `setEnemyExtentsColor` *(modding)* | function | Set enemy movement extents color. | not used |
| `setZocColor` *(modding)* | function | Set Zone of Control color. | not used |
| `findValidTileNearTile` | function | Find a valid tile near a location (or on location if its valid). | not used |
| `isInBounds` | function | Check if the position is contained within the strat map. | not used |
| `getMovePath` *(modding)* | function | Get the shortest between 2 positions. | not used |
| `rebuildFrontiers` | function | Regenerate frontier tiles. | not used |

### tileStruct (7/50 used)

| member | kind | what it is | status |
|---|---|---|---|
| `road` | field rw | `roadStruct` | not used |
| `isLand` | field rw | (1 = land, 0 = sea) | USED report (crossings) + order |
| `groundType` | property rw | `int` | not used |
| `regionID` | field rw | `int` | USED report (crossings) + order |
| `choke` | field rw | `int` | not used |
| `xCoord` | property ro | `int` | USED report + order + other ? |
| `yCoord` | property ro | `int` | USED report + order + other ? |
| `factionID` | property ro | `int` | not used |
| `heatValue` | property ro | `int` | not used |
| `height` | property rw | `int` | not used |
| `climate` | property rw | `int` | not used |
| `hasRiver` | property ro | `bool` | not used |
| `hasRiverSource` | property ro | `bool` | not used |
| `hasCliff` | property ro | `bool` | not used |
| `resource` | property ro | `tradeResource\|nil` | not used |
| `character` | property ro | `character\|nil` | not used |
| `settlement` | property ro | `settlementStruct\|nil` | USED report + order + other |
| `fort` | property ro | `fortStruct\|nil` | not used |
| `port` | property ro | `portStruct\|nil` | USED order |
| `watchtower` | property ro | `watchtowerStruct\|nil` | not used |
| `hasCrossing` | property ro | `bool` | not used |
| `hasVolcano` | property ro | `bool` | not used |
| `hasSeaCrossing` | property ro | `bool` | USED report (crossings) + order |
| `hasRoad` | property ro | `bool` | not used |
| `roadLevel` | property ro | `int` | not used |
| `earthquakeLevel` | property ro | `int` | not used |
| `floodLevel` | property ro | `int` | not used |
| `stormLevel` | property ro | `int` | not used |
| `volcanoLevel` | property ro | `int` | not used |
| `isScorched` | property ro | `bool` | not used |
| `isTradeRoute` | property ro | `bool` | not used |
| `devastationLevel` | property rw | `int` | not used |
| `isDeforested` | property rw | `bool` | not used |
| `isBorder` | property ro | `bool` | not used |
| `isLandCoast` | property ro | `bool` | not used |
| `isSeaCoast` | property ro | `bool` | not used |
| `hasSettlement` | property ro | `bool` | not used |
| `hasFort` | property ro | `bool` | not used |
| `hasDock` | property ro | `bool` | not used |
| `hasPort` | property ro | `bool` | not used |
| `hasWatchtower` | property ro | `bool` | not used |
| `hasNavy` | property ro | `bool` | not used |
| `hasArmy` | property ro | `bool` | not used |
| `isImpassible` | property ro | `bool` | not used |
| `isDevastated` | property ro | `bool` | not used |
| `mpModifier` | field rw | `float` | not used |
| `factionHasArmyNearTile` | function | Check if a faction has an army near a tile. | not used |
| `factionHasCharacterOnTile` | function | Check if a faction has a character on a tile. | not used |
| `getTileCharacterCount` | function | Get amount of characters on a tile. | not used |
| `getTileCharacterAtIndex` | function | Get a character on a tile. | not used |

### coordPair (2/2 used)

| member | kind | what it is | status |
|---|---|---|---|
| `xCoord` | field rw | `int` | USED report + order + other ? |
| `yCoord` | field rw | `int` | USED report + order + other ? |

### roadStruct (1/7 used)

| member | kind | what it is | status |
|---|---|---|---|
| `coordsNum` | field rw | `int` | not used |
| `regionIdStart` | field rw | `int` | not used |
| `regionIdEnd` | field rw | `int` | not used |
| `tradeValue` | field rw | only counts from 1 side (importer) | not used |
| `id` | field rw | `int` | USED report + order + event + other ? |
| `onlyHalf` | field rw | `bool` | not used |
| `getCoord` | function | Get a road coord by index. | not used |

### landMass (0/3 used)

| member | kind | what it is | status |
|---|---|---|---|
| `index` | field rw | `int` | not used |
| `regionsNum` | field rw | `int` | not used |
| `getRegionID` | function | Get a region ID by index. | not used |

### landingPoint (0/3 used)

| member | kind | what it is | status |
|---|---|---|---|
| `landTile` | property ro | `tileStruct` | not used |
| `moveCost` | field rw | From water to land | not used |
| `seaTile` | property ro | `tileStruct` | not used |

### landingTile (0/2 used)

| member | kind | what it is | status |
|---|---|---|---|
| `tile` | property ro | `tileStruct` | not used |
| `moveCost` | field rw | Move points required to reach this tile | not used |

### neighbourRegion (0/16 used)

| member | kind | what it is | status |
|---|---|---|---|
| `regionID` | field rw | `int` | not used |
| `tradeValue` | field rw | `int` | not used |
| `region` | field rw | `regionStruct` | not used |
| `borderTilesCount` | field rw | `int` | not used |
| `frontierTilesCount` | field rw | `int` | not used |
| `ambushTilesCount` | field rw | `int` | not used |
| `deepFrontierTilesCount` | field rw | `int` | not used |
| `borderCrossingCount` | field rw | `int` | not used |
| `connectingRoad` | field rw | `roadStruct` | not used |
| `isBlocked` | field rw | `bool` | not used |
| `moveCost` | field rw | from settlement to settlement | not used |
| `getBorderTile` | function | Get a border tile by index. | not used |
| `getFrontierTile` | function | Get a frontier tile by index. | not used |
| `getAmbushTile` | function | Get an ambush tile by index. | not used |
| `getDeepFrontierTile` | function | Get a deep frontier tile by index. | not used |
| `getBorderCrossing` | function | Get a border tile that is passable to other region. | not used |

### seaConnectedRegion (0/7 used)

| member | kind | what it is | status |
|---|---|---|---|
| `regionID` | field rw | `int` | not used |
| `seaExportValue` | field rw | `int` | not used |
| `seaImportValue` | field rw | `int` | not used |
| `tilesReachableCount` | field rw | `int` | not used |
| `seaTradeLanePathCount` *(modding)* | field rw | `int` | not used |
| `getReachableTile` | function | Get a reachable tile by index. | not used |
| `getTradeLaneCoord` | function | Get trade lane coords by index. | not used |

### stratMovePath (0/3 used)

| member | kind | what it is | status |
|---|---|---|---|
| `totalTiles` | property ro | `int` | not used |
| `totalCost` | field rw | `float` | not used |
| `getPathCoords` *(modding)* | function | Get move path coords by index. | not used |

### weatherData (0/5 used)

| member | kind | what it is | status |
|---|---|---|---|
| `fogMin` | field ro | get only | not used |
| `fogMax` | field ro | get only | not used |
| `windStrength` | field ro | get only | not used |
| `rainType` | field ro | get only | not used |
| `rainLevel` | field ro | get only | not used |

## Campaign, diplomacy and game state

153 members, 14 used (+3 by name only).

### campaignStruct (8/84 used)

| member | kind | what it is | status |
|---|---|---|---|
| `campaignDifficultyFaction` | property ro | Indexing starts at 1, so add 1 to faction ID. Maximum 31. | not used |
| `battleDifficultyFaction` | property ro | Indexing starts at 1, so add 1 to faction ID. Maximum 31. | not used |
| `factionsSortedByDescrStrat` | property ro | Table of factionStruct[31], indexing starts at 1. Maximum 31. Slightly misleading name, sorted by the turn or... | not used |
| `factionsSortedByID` | property ro | Table of factionStruct[31], indexing starts at 1, so add 1 to faction ID. Maximum 31. | not used |
| `numberOfFactions` | field rw | `int` | not used |
| `mercPoolNum` | property ro | `int` | not used |
| `settlementNum` | property ro | `int` | not used |
| `papalFaction` | field rw | `factionStruct` | not used |
| `numberOfHumanFactions` | field rw | Number of player-controlled factions. | not used |
| `collegeOfCardinals` | field rw | `collegeOfCardinals` | not used |
| `currentFaction` | field rw | Faction whose turn it is at the moment, can be set. | USED event |
| `windSpeed` | field rw | `float` | not used |
| `parsingType` | field rw | 1 = load, 2 = campaign, 3 = custom battle | not used |
| `isLoaded` | field rw | `bool` | not used |
| `timeOfDay` | field rw | `float` | not used |
| `weather` | field rw | `weatherData` | not used |
| `factionTurnID` | field rw | `int` | not used |
| `marianReformsActive` | field rw | `bool` | not used |
| `marianReformsDisabled` | field rw | `bool` | not used |
| `tickCount` | field rw | `int` | not used |
| `millisecondCount` | field rw | `int` | not used |
| `slaveFaction` | property ro | `factionStruct` | not used |
| `secondCount` | field rw | `float` | not used |
| `fogOfWar` | field rw | `bool` | not used |
| `isPaused` | field rw | `bool` | not used |
| `speedUp` | field rw | `bool` | not used |
| `ignoreSpeedUp` | field rw | `bool` | not used |
| `followMovement` | field rw | `bool` | not used |
| `passedTurnsNum` | field rw |  | not used |
| `turnNumber` | field rw | `int` | USED report + order + event + other |
| `crusade` | field rw | `crusadeStruct` | not used |
| `campaignWinnerID` | field rw | `int` | not used |
| `jihad` | field rw | `jihadStruct` | not used |
| `timescale` | field rw | Factor for number of turns per year, see descr\_strat.txt | not used |
| `slaveFactionID` | field rw | `int` | not used |
| `romeSettlement` | field rw | `settlementStruct` | not used |
| `constantinopleSettlement` | field rw | `settlementStruct` | not used |
| `brigandSpawnValue` | field rw | Lower values increase spawn rate. | not used |
| `pirateSpawnValue` | field rw | Lower values increase spawn rate. | not used |
| `restrictAutoResolve` | field rw | `int` | not used |
| `saveEnabled` | field rw | `int` | not used |
| `freeUpkeepForts` | field rw | Number of units who get free upkeep in forts. | not used |
| `rebellingCharactersActive` | field rw | `bool` | not used |
| `nightBattlesEnabled` | field rw | `bool` | not used |
| `currentDate` | field rw | `float` | USED report |
| `currentSeason` | field rw | season (0=summer, 1=winter) | not used |
| `startDate` | field rw | `float` | not used |
| `startSeason` | field rw | season (0=summer, 1=winter) | not used |
| `endDate` | field rw | `float` | not used |
| `endSeason` | field rw | season (0=summer, 1=winter) | not used |
| `daysInBattle` | field rw | `int` | not used |
| `currentTimeInBattle` | field rw | 24 max, so calculate as daysInBattle*24+currentTimeInBattle. | not used |
| `fortsNum` | field rw | `int` | not used |
| `roadsNum` | field rw | `int` | not used |
| `portsBuildingsNum` | field rw | `int` | not used |
| `watchTowerNum` | field rw | `int` | not used |
| `checkDipStance` | function | Check if a diplomatic relation between two factions. | USED report + order |
| `setDipStance` | function | Set a diplomatic relation between two factions. | USED order + other |
| `getUnitSize` | function | Get size of unit(i.e. small or medium, etc). Numbers from 0 to 3 | not used |
| `getFort` | function | Get fort by index. | not used |
| `getPort` | function | Get port by index. | not used |
| `getWatchTower` | function | Get watchtower by index. | not used |
| `getSettlementByName` | function | Get settlement by internal name. | not used |
| `getFaction` | function | Get a faction by it's internal name. | USED event |
| `getCampaignPath` *(modding)* | function | Get path to the current descr\_strat file used. | not used |
| `getMercPool` | function | Get a mercenary pool by index. | not used |
| `getMercPoolByName` | function | Get a mercenary pool by name. | not used |
| `getRoad` | function | Get a road by index. | not used |
| `getPlayerFaction` | function | Get a human faction by index. | not used |
| `getFactionByID` | function | Get a faction by faction ID. | not used |
| `getFactionByOrder` | function | Get a faction by turn order (best way to iterate over factions on the campaign map). | not used |
| `isPlayableFaction` | function | Check if a faction is playable. | not used |
| `setPlayableFaction` | function | Set if a faction is playable. | not used |
| `isPlayerFaction` | function | Check if a faction is player controlled. | not used |
| `isExistingFaction` | function | Check if a faction is currently active in the campaign. | not used |
| `getNumberOfMarriages` | function | Check how many interfaction marriages have been done between the 2 factions. | not used |
| `getFactionDiplomacy` | function | Get faction diplomacy data. | USED report |
| `getSettlement` | function | Get settlement by index. | USED other ? |
| `switchFactionOrder` | function | Switch turn order for 2 factions. Useful to avoid bugs with control command. | not used |
| `addCharacterCas` *(modding)* | function | Add a new .cas character strategy model to the game with a unique name. Only add it after loading to campaign... | not used |
| `historicEvent` | function | Fire a game event message. Picture needs to be provided in the ui folders as default. | not used |
| `getCharacterByLabel` | function | Get a character by script label. | not used |
| `worldwideAncillaryExists` | function | Get the first character it finds holding an ancillary, or nil if it doesn't exist in the campaign. | not used |
| `execScriptEvent` *(modding)* | function | Fire an event such as a disaster. You need vision of the event or the event must be in your lands to get a no... | not used |

### factionDiplomacy (4/30 used)

| member | kind | what it is | status |
|---|---|---|---|
| `previousState` | field rw | `int` | not used |
| `state` | field rw | (don't set, use setDipStance so all proper functionality fires) | not used |
| `hasTradeRights` | property ro | (don't set, use setDipStance so all proper functionality fires) | USED report |
| `hasMilitaryAccess` | property rw | `bool` | USED report |
| `isTrustWorthy` | property rw | `bool` | not used |
| `isProtectorate` | property ro | (don't set, use setDipStance so all proper functionality fires) | USED report |
| `isKnown` | property rw | `bool` | not used |
| `lastDiplomaticResult` | property rw | `bool` | not used |
| `factionStanding` | field rw | `float` | not used |
| `protectoratePayment` | field rw | `int` | not used |
| `numTurnsAllied` | field rw | `int` | not used |
| `numTurnsWar` | field rw | `int` | not used |
| `numTurnsState` | field rw | `int` | USED report |
| `numTurnsTrade` | field rw | `int` | not used |
| `numTurnsAccess` | field rw | `int` | not used |
| `numTurnsProtectorate` | field rw | `int` | not used |
| `numTreaties` | field rw | `int` | not used |
| `numAssists` | field rw | `int` | not used |
| `numAssistFailures` | field rw | `int` | not used |
| `numEmptyThreats` | field rw | `int` | not used |
| `numValidThreats` | field rw | `int` | not used |
| `leaveTerritoryTimer` | field rw | `int` | not used |
| `winsInBattle` | field rw | `int` | not used |
| `tributeAmount` | field rw | `int` | not used |
| `tributeDuration` | field rw | `int` | not used |
| `turnsSinceLastMeeting` | field rw | `int` | not used |
| `diplomaticSuccess` | field rw | `int` | not used |
| `diplomaticBalance` | field rw | `int` | not used |
| `lastMapInfoTrade` | field rw | `int` | not used |
| `numTurnsCeasefire` | field rw | `int` | not used |

### gameDataAll (3/6 used)

| member | kind | what it is | status |
|---|---|---|---|
| `get` | function |  | USED other |
| `battleStruct` | field rw |  | not used |
| `campaignStruct` | field rw |  | USED report + order + event + other |
| `uiCardManager` *(ui)* | field rw |  | not used |
| `stratMap` | field rw |  | USED report (crossings, resources) + order + event + other |
| `selectionInfo` | field rw |  | not used |

### guild (2/6 used)

| member | kind | what it is | status |
|---|---|---|---|
| `name` | property rw | `string` | USED report + order + event + other ? |
| `id` | field rw | `int` | USED report + order + event + other ? |
| `level1` | field rw | `int` | not used |
| `level2` | field rw | `int` | not used |
| `level3` | field rw | `int` | not used |
| `entry` | field rw | `edbEntry` | not used |

### campaignDifficulty1 (0/9 used)

| member | kind | what it is | status |
|---|---|---|---|
| `orderFromGrowth` | field rw | `int` | not used |
| `aiHireMercenaries` | field rw | `bool` | not used |
| `brigandChanceAi` | field rw | `float` | not used |
| `brigandChancePlayer` | field rw | `float` | not used |
| `maxPlayerPeaceTurns` | field rw | `int` | not used |
| `taxIncomeModifierPlayer` | field rw | `float` | not used |
| `farmingIncomeModifierPlayer` | field rw | `float` | not used |
| `incomeModifierAi` | field rw | `float` | not used |
| `playerRegionValueModifier` | field rw | `float` | not used |

### campaignDifficulty2 (0/7 used)

| member | kind | what it is | status |
|---|---|---|---|
| `popGrowthBonusAi` | field rw | `int` | not used |
| `publicOrderBonusAi` | field rw | `int` | not used |
| `experienceBonusAi` | field rw | `int` | not used |
| `incomeBonusAi` | field rw | `int` | not used |
| `dontAttackAiDefenders` | field rw | `bool` | not used |
| `forceNavalInvasions` | field rw | `bool` | not used |
| `brigandControllerTargetSettlements` | field rw | `bool` | not used |

### missionDetailsStruct (0/2 used)

| member | kind | what it is | status |
|---|---|---|---|
| `missionName` | property ro | `string` | not used |
| `paybackName` | property ro | `string` | not used |

### selectionInfo (0/9 used)

| member | kind | what it is | status |
|---|---|---|---|
| `selectedCharacter` *(ui)* | property ro | (Get only) | not used |
| `hoveredCharacter` | property ro | (Get only) | not used |
| `selectedEnemyCharacter` *(ui)* | property ro | You can only select non-player characters with zoom to location button (Get only) | not used |
| `selectedSettlement` *(ui)* | property ro | (Get only) | not used |
| `hoveredSettlement` | property ro | (Get only) | not used |
| `selectedEnemySettlement` *(ui)* | property ro | You can only select non-player settlements with zoom to location button (Get only) | not used |
| `selectedFort` *(ui)* | property ro | (Get only) | not used |
| `hoveredFort` | property ro | (Get only) | not used |
| `selectedEnemyFort` *(ui)* | property ro | You can only select non-player forts with zoom to location button (Get only) | not used |

## Religion, papacy and crusades

44 members, 0 used (+1 by name only).

### crusadeReward (1/2 used)

| member | kind | what it is | status |
|---|---|---|---|
| `money` | field rw | `int` | USED order ? |
| `experience` | field rw | `int` | not used |

### cardinal (0/4 used)

| member | kind | what it is | status |
|---|---|---|---|
| `character` | property ro | `character` | not used |
| `factionID` | field rw | `int` | not used |
| `voteFactionID` | field rw | `int` | not used |
| `isPreferati` | field rw | `bool` | not used |

### collegeOfCardinals (0/10 used)

| member | kind | what it is | status |
|---|---|---|---|
| `pope` | field rw | `characterRecord` | not used |
| `cardinalNum` | field rw | `int` | not used |
| `electionResultsCount` | field rw | `int` | not used |
| `popeIsOld` | field rw | `bool` | not used |
| `inElection` | field rw | `bool` | not used |
| `maxCardinals` | field rw | `int` | not used |
| `maxPreferati` | field rw | `int` | not used |
| `popePreviousFactionID` | field rw | `int` | not used |
| `getCardinal` | function | Get a specific cardinal by index. | not used |
| `getElectionResult` | function | Get a election result by index. | not used |

### crusadeStruct (0/15 used)

| member | kind | what it is | status |
|---|---|---|---|
| `startTurn` | field rw | `int` | not used |
| `endTurn` | field rw | `int` | not used |
| `targetSettlement` | field rw | `settlementStruct` | not used |
| `length` | field rw | `int` | not used |
| `outcome` | field rw | `int` | not used |
| `orthodoxID` | field rw | `int` | not used |
| `catholicID` | field rw | `int` | not used |
| `hereticID` | field rw | `int` | not used |
| `factionJoined` | function | Check if a faction has joined this crusade. | not used |
| `factionJoinedLastTurn` | function | Check if a faction has joined this crusade last turn. | not used |
| `factionFought` | function | Check if a faction has fought in this crusade. | not used |
| `factionInTarget` | function | Check if a faction is in the crusade target region. | not used |
| `getReward` | function | Get reward a faction will get for winning this crusade. | not used |
| `start` | function | Start a new crusade. | not used |
| `stop` | function | Stop an ongoing crusade. | not used |

### jihadStruct (0/13 used)

| member | kind | what it is | status |
|---|---|---|---|
| `startTurn` | field rw | `int` | not used |
| `endTurn` | field rw | `int` | not used |
| `targetSettlement` | field rw | `settlementStruct` | not used |
| `length` | field rw | `int` | not used |
| `outcome` | field rw | `int` | not used |
| `muslimID` | field rw | `int` | not used |
| `factionJoined` | function | Check if a faction has joined this jihad. | not used |
| `factionJoinedLastTurn` | function | Check if a faction has joined this jihad last turn. | not used |
| `factionFought` | function | Check if a faction has fought in this jihad. | not used |
| `factionInTarget` | function | Check if a faction is in the jihad target region. | not used |
| `getReward` | function | Get reward a faction will get for winning this jihad. | not used |
| `start` | function | Start a new jihad. | not used |
| `stop` | function | Stop an ongoing jihad. | not used |

## Buildings and recruitment

127 members, 11 used (+10 by name only).

### buildingInQueue (7/13 used)

| member | kind | what it is | status |
|---|---|---|---|
| `building` | field rw | Is nil if building doesn't exist yet. | USED order ? |
| `edbEntry` | field rw | `edbEntry` | not used |
| `constructionType` | field rw | 0 = upgrade, 1 = normal, 4 = convert settlement | USED report (settlements.can_build) + order |
| `settlement` | field rw | `settlementStruct` | USED report + order + event + other ? |
| `currentLevel` | field rw | `int` | not used |
| `previousLevel` | field rw | `int` | not used |
| `buildCost` | field rw | `int` | USED report + order ? |
| `buildTurnsPassed` | field rw | `int` | not used |
| `buildTurnsRemaining` | field rw | `int` | USED report (settlements.can_build) + order |
| `percentBuilt` | field rw | `int` | not used |
| `getQueueBuildingType` | function | Get name of building in queue type (chain) | not used |
| `getQueueBuildingName` | function | Get name of building in queue level | USED report (settlements.can_build, settlements.queue) + order |
| `addBuildingToQueue` | function | Add a building to the construction queue. | USED report + order |

### building (5/8 used)

| member | kind | what it is | status |
|---|---|---|---|
| `level` | field rw | `int` | USED order ? |
| `hp` | property rw | `int` | USED report |
| `settlement` | field rw | `settlementStruct` | USED report + order + event + other ? |
| `edbEntry` | field rw | `edbEntry` | not used |
| `factionID` | field rw | `int` | not used |
| `getType` | function | Get the name of the building type (the building chain in export\_descr\_buildings.txt). | USED report (settlements.buildings) + order |
| `getName` | function | Get name of building level (as per export\_descr\_buildings.txt). | USED report (settlements.buildings) + order |
| `addCapability` | function |  | not used |

### buildingLevel (2/33 used)

| member | kind | what it is | status |
|---|---|---|---|
| `name` | property rw | `string` | USED report + order + event + other ? |
| `genericBuildingPic` | property rw | `string` | not used |
| `genericBuildingPicConstructed` | property rw | `string` | not used |
| `genericBuildingPicConstruction` | property rw | `string` | not used |
| `buildCost` | field rw | `int` | USED report + order ? |
| `buildTime` | field rw | `int` | not used |
| `settlementMinLvl` | field rw | `int` | not used |
| `availableCastle` | property ro | `bool` | not used |
| `availableCity` | property ro | `bool` | not used |
| `capabilityNum` | property ro | `int` | not used |
| `recruitPoolNum` | property ro | `int` | not used |
| `factionCapabilityNum` | property ro | `int` | not used |
| `setBuildingPic` | function | Set picture of building. | not used |
| `getBuildingPic` | function | Get picture of building. | not used |
| `setBuildingPicConstructed` | function | Set constructed picture of building. | not used |
| `getBuildingPicConstructed` | function | Get constructed picture of building. | not used |
| `setBuildingPicConstruction` | function | Set construction picture of building. | not used |
| `getBuildingPicConstruction` | function | Get construction picture of building. | not used |
| `setLocalizedName` | function | Set the name of the building level. | not used |
| `getLocalizedName` | function | Get the name of the building level. | not used |
| `setLocalizedDescr` | function | Set the description of the building level. | not used |
| `getLocalizedDescr` | function | Get the description of the building level. | not used |
| `setLocalizedDescrShort` | function | Set the description of the building level. | not used |
| `getLocalizedDescrShort` | function | Get the description of the building level. | not used |
| `getCapability` | function | Get a capability. | not used |
| `getFactionCapability` | function | Get a faction capability. | not used |
| `getRecruitPool` | function | Get a recruit pool. | not used |
| `addCapability` | function | Add a capability. | not used |
| `addFactionCapability` | function | Add a faction capability. | not used |
| `addRecruitPool` | function | Add a recruit pool. | not used |
| `removeCapability` | function | Remove a capability. | not used |
| `removeFactionCapability` | function | Remove a faction capability. | not used |
| `removeRecruitPool` | function | Remove a recruit pool. | not used |

### buildingsQueue (2/2 used)

| member | kind | what it is | status |
|---|---|---|---|
| `numBuildingsInQueue` | property ro | maximum is 6 | USED report (settlements.queue) + order |
| `getBuildingInQueue` | function | Get building in queue by position | USED report (settlements.queue) + order |

### constructionOptions (2/4 used)

| member | kind | what it is | status |
|---|---|---|---|
| `buildingNum` | field rw | `int` | USED report (settlements.can_build) + order |
| `totalCost` | field rw | `int` | not used |
| `totalTime` | field rw | `int` | not used |
| `getConstructionOption` | function | Get an available construction item. | USED report (settlements.can_build) + order |

### edbEntry (2/13 used)

| member | kind | what it is | status |
|---|---|---|---|
| `buildingID` | field rw | `int` | not used |
| `classification` | field rw | `int` | not used |
| `isCoreBuilding` | field rw | `int` | not used |
| `isPort` | field rw | `int` | not used |
| `isWallBuilding` | field rw | `int` | not used |
| `isTemple` | field rw | `int` | not used |
| `religionID` | field rw | `int` | not used |
| `isHinterland` | field rw | `int` | not used |
| `isFarm` | field rw | `int` | not used |
| `name` | property rw | `string` | USED report + order + event + other ? |
| `localizedName` | property rw | `string` | USED report + other ? |
| `buildingLevelCount` | field rw | `int` | not used |
| `getBuildingLevel` | function | Get a building level. | not used |

### recruitmentCapability (1/5 used)

| member | kind | what it is | status |
|---|---|---|---|
| `eduIndex` | field rw | `int` | USED report + order ? |
| `xp` | field rw | `int` | not used |
| `initialSize` | field rw | `float` | not used |
| `replenishRate` | field rw | `float` | not used |
| `maxSize` | field rw | `float` | not used |

### EDB (0/27 used)

| member | kind | what it is | status |
|---|---|---|---|
| `hiddenResourceCount` | property ro | `int` | not used |
| `port` | property ro | `edbEntry` | not used |
| `castlePort` | property ro | `edbEntry` | not used |
| `coreCityBuilding` | property ro | `edbEntry` | not used |
| `coreCastleBuilding` | property ro | `edbEntry` | not used |
| `addEopBuildEntry` | function | Create new EOP Building entry | not used |
| `getBuildingByName` | function | Get a building edb entry by name. | not used |
| `getBuildingByID` | function | Get a building edb entry by index (EOP buildings too). | not used |
| `getBuildingNum` | function | Get number of vanilla buildings. | not used |
| `getGuild` | function | Get a guild by index. | not used |
| `getGuildNum` | function | Get number of guilds. | not used |
| `getGuildByName` | function | Get a guild by name. | not used |
| `getEopBuildEntry` | function |  | not used |
| `setBuildingPic` | function |  | not used |
| `setBuildingPicConstructed` | function |  | not used |
| `setBuildingPicConstruction` | function |  | not used |
| `setBuildingLocalizedName` | function |  | not used |
| `setBuildingLocalizedDescr` | function |  | not used |
| `setBuildingLocalizedDescrShort` | function |  | not used |
| `addBuildingCapability` | function |  | not used |
| `removeBuildingCapability` | function |  | not used |
| `getBuildingCapability` | function |  | not used |
| `getBuildingCapabilityNum` | function |  | not used |
| `addBuildingPool` | function |  | not used |
| `removeBuildingPool` | function |  | not used |
| `getBuildingPool` | function |  | not used |
| `getBuildingPoolNum` | function |  | not used |

### capability (0/4 used)

| member | kind | what it is | status |
|---|---|---|---|
| `capabilityType` | field rw | `int` | not used |
| `capabilityLvl` | field rw | `int` | not used |
| `bonus` | field rw | `int` | not used |
| `capabilityID` | field rw | `int` | not used |

### eopProductionHelper (0/5 used)

| member | kind | what it is | status |
|---|---|---|---|
| `upkeepTurns` | field rw | How many turns of the units upkeep the faction must have in treasury for the unit to be considered. Default: 8 | not used |
| `minMoney` | field rw | Minimum treasury for script to activate. Default: 1000 | not used |
| `costMultiplier` | field rw | Unit cost is multiplied by this value when considering if the faction should buy this unit (actual treasury s... | not used |
| `enabled` | field rw | Enable the script. Default: true | not used |
| `logProduction` | field rw | Log produced units. Default: true | not used |

### recruitPool (0/9 used)

| member | kind | what it is | status |
|---|---|---|---|
| `capabilityType` | field rw | `int` | not used |
| `experience` | property rw | `int` | not used |
| `unitID` | property rw | `int` | not used |
| `agentAmount` | property rw | `int` | not used |
| `agentLimit` | property rw | `int` | not used |
| `agentType` | property rw | `int` | not used |
| `initialSize` | field rw | `float` | not used |
| `gainPerTurn` | field rw | `float` | not used |
| `maxSize` | field rw | `float` | not used |

### recruitmentOptions (0/4 used)

| member | kind | what it is | status |
|---|---|---|---|
| `unitNum` | field rw | `int` | not used |
| `totalCost` | field rw | `int` | not used |
| `totalTime` | field rw | `int` | not used |
| `getRecruitmentOption` | function | Get an available recruitment item. | not used |

## Campaign AI

116 members, 3 used (+3 by name only).

### aiProductionController (4/20 used)

| member | kind | what it is | status |
|---|---|---|---|
| `aiFaction` | field rw | `aiFaction` | not used |
| `regionID` | field rw | `int` | not used |
| `settlement` | field rw | `settlementStruct` | USED report + order + event + other ? |
| `autoManagePolicy` | field rw | `int` | not used |
| `isAutoManaged` | field rw | `bool` | USED other |
| `isAutoManagedRecruitment` | field rw | `bool` | USED other |
| `isAutoManagedConstruction` | field rw | `bool` | USED other |
| `isAutoManagedTaxes` | field rw | `bool` | not used |
| `spyBias` | field rw | `int` | not used |
| `assassinBias` | field rw | `int` | not used |
| `diplomatBias` | field rw | `int` | not used |
| `admiralBias` | field rw | `int` | not used |
| `priestBias` | field rw | `int` | not used |
| `merchantBias` | field rw | `int` | not used |
| `setConstructionValue` | function | Set bias value of the ai personality for a capability. | not used |
| `setRecruitmentValue` | function | Set bias value of the ai personality for a recruitment class. | not used |
| `setExtraBias` | function | Set bias value of the ai personality. | not used |
| `getExtraBias` | function | Get bias value of the ai personality. | not used |
| `getConstructionValue` | function | Get bias value of the ai personality for a capability. | not used |
| `getRecruitmentValue` | function | Get bias value of the ai personality for a recruitment class. | not used |

### aiFaction (1/4 used)

| member | kind | what it is | status |
|---|---|---|---|
| `faction` | field rw | `factionStruct` | USED report + order + event + other ? |
| `factionID` | field rw | `int` | not used |
| `LTGD` | field rw | `aiLongTermGoalDirector` | not used |
| `aiPersonality` | field rw | `aiPersonality` | not used |

### aiLongTermGoalDirector (1/17 used)

| member | kind | what it is | status |
|---|---|---|---|
| `faction` | field rw | `factionStruct` | USED report + order + event + other ? |
| `aiFaction` | field rw | `aiFaction` | not used |
| `trustedAllyEnemiesBitfield` | field rw | `int` | not used |
| `freeStrengthEnemy` | field rw | `int` | not used |
| `freeStrengthEnemyBalance` | field rw | `int` | not used |
| `consideringNavalInvasion` | field rw | `int` | not used |
| `navalTargetRegionID` | field rw | `int` | not used |
| `stagingRegionID` | field rw | `int` | not used |
| `longTermPolicy` | field rw | `int` | not used |
| `longTermTroopStatus` | field rw | `int` | not used |
| `getLongTermGoalValues` | function | Get long term goal director values versus a specific other faction. | not used |
| `isTrustedAllyEnemy` | function | Check if another faction is an enemy of one the faction's trusted allies. | not used |
| `isTrustedAlly` | function | Check if another faction is a trusted ally. | not used |
| `regionsBordersOnlyTrusted` | function | Check if a regions borders only trusted territory. | not used |
| `getInvasionTargetNum` | function | Count of settlements inside and bordering the region we currently have an invasion type for. | not used |
| `getInvasionTargetPriority` | function | Sum of settlements inside and bordering the region's invasion priorities. | not used |
| `reset` | function | Reset decision values. | not used |

### aiFactionData (0/5 used)

| member | kind | what it is | status |
|---|---|---|---|
| `setTargetFactionFactor` | function | Set factor for targetting a faction. | not used |
| `setAidFactionFactor` | function | Set factor for aiding a faction. | not used |
| `setSettlementFactor` | function | Set factor for a specific settlement (defense or attack). | not used |
| `setTargetReligionFactor` | function | Set factor for targetting a religion. | not used |
| `setAidReligionFactor` | function | Set factor for aiding a religion. | not used |

### aiFactionValues (0/16 used)

| member | kind | what it is | status |
|---|---|---|---|
| `totalPopulation` | field rw | `int` | not used |
| `tileCount` | field rw | `int` | not used |
| `averagePopulation` | field rw | `int` | not used |
| `productionValue` | field rw | `int` | not used |
| `nonAlliedBorderLength` | field rw | `int` | not used |
| `alliedBorderLength` | field rw | `int` | not used |
| `fleetCount` | field rw | `int` | not used |
| `navalPowerPerFleet` | field rw | `int` | not used |
| `navalStrength` | field rw | `int` | not used |
| `armyCount` | field rw | `int` | not used |
| `strengthPerArmy` | field rw | `int` | not used |
| `totalStrength` | field rw | `int` | not used |
| `freeStrength` | field rw | `int` | not used |
| `enemyNum` | field rw | `int` | not used |
| `immediateEnemyStrength` | field rw | `int` | not used |
| `protectorateOf` | field rw | `int` | not used |

### aiPersonality (0/20 used)

| member | kind | what it is | status |
|---|---|---|---|
| `aiFaction` | field rw | `aiFaction` | not used |
| `aiProductionControllersNum` | field rw | `int` | not used |
| `aiPersonalityType` | field rw | `int` | not used |
| `aiPersonalityName` | field rw | `int` | not used |
| `balancedPolicyNum` | field rw | `int` | not used |
| `financialPolicyNum` | field rw | `int` | not used |
| `militaryPolicyNum` | field rw | `int` | not used |
| `growthPolicyNum` | field rw | `int` | not used |
| `culturalPolicyNum` | field rw | `int` | not used |
| `setConstructionValue` | function | Set bias value of the ai personality for a capability. | not used |
| `setConstructionAgentValue` | function | Set bias value of the ai personality for a capability. | not used |
| `setConstructionUnitValue` | function | Set bias value of the ai personality for a capability. | not used |
| `setRecruitmentValue` | function | Set bias value of the ai personality for a recruitment class. | not used |
| `setAgentValue` | function | Set bias value of the ai personality for an agent type. | not used |
| `getConstructionValue` | function | Get bias value of the ai personality for a capability. | not used |
| `getConstructionAgentValue` | function | Get bias value of the ai personality for a capability. | not used |
| `getConstructionUnitValue` | function | Get bias value of the ai personality for a capability. | not used |
| `getRecruitmentValue` | function | Get bias value of the ai personality for a recruitment class. | not used |
| `getAgentValue` | function | Get bias value of the ai personality for an agent type. | not used |
| `getProductionController` | function | Get a production controller by index. | not used |

### decisionValuesLTGD (0/16 used)

| member | kind | what it is | status |
|---|---|---|---|
| `defendType` | field rw | `int` | not used |
| `defendPriority` | field rw | `int` | not used |
| `invasionType` | field rw | `int` | not used |
| `invadePriority` | field rw | `int` | not used |
| `atWar` | field rw | `bool` | not used |
| `wantPeace` | field rw | `bool` | not used |
| `wantAlly` | field rw | `bool` | not used |
| `wantBeProtect` | field rw | `bool` | not used |
| `wantOfferProtect` | field rw | `bool` | not used |
| `allianceAgainst` | field rw | `int` | not used |
| `ptsDesire` | field rw | `int` | not used |
| `ptsAlliance` | field rw | `int` | not used |
| `canForceInvade` | field rw | `bool` | not used |
| `forceInvade` | field rw | `bool` | not used |
| `pointsInvasion` | field rw | `int` | not used |
| `pointsDefense` | field rw | `int` | not used |

### eopAiConfig (0/13 used)

| member | kind | what it is | status |
|---|---|---|---|
| `enabled` | property rw | `bool` | not used |
| `enableLogging` | property rw | `bool` | not used |
| `aggressionFactor` | property rw | `float` | not used |
| `defenseFactor` | property rw | `float` | not used |
| `residenceFactor` | property rw | `float` | not used |
| `aidFactor` | property rw | `float` | not used |
| `moveCostFactor` | property rw | `float` | not used |
| `powerFactor` | property rw | `float` | not used |
| `nonBorderFactor` | property rw | `float` | not used |
| `invadePriorityFactor` | property rw | `float` | not used |
| `maxTurnSearchCount` | property rw | `int` | not used |
| `getFactionData` | function | Get faction specific data. | not used |
| `getProductionHelper` | function | Get EOP production helper | not used |

### interFactionLTGD (0/5 used)

| member | kind | what it is | status |
|---|---|---|---|
| `borderTiles` | field rw | `int` | not used |
| `frontLineBalance` | field rw | `int` | not used |
| `hasAllianceAgainst` | field rw | `int` | not used |
| `isStrongestNeighbour` | field rw | `int` | not used |
| `isWeakestNeighbour` | field rw | `int` | not used |

## Fort, port, watchtower and resources

68 members, 2 used (+17 by name only).

### tradeResource (5/11 used)

| member | kind | what it is | status |
|---|---|---|---|
| `xCoord` | field rw | `int` | USED report + order + other ? |
| `yCoord` | field rw | `int` | USED report + order + other ? |
| `regionID` | field rw | `int` | not used |
| `resourceID` | field rw | `int` | not used |
| `settlement` | field rw | `settlementStruct` | USED report + order + event + other ? |
| `setStratModel` *(modding)* | function | Set the resource's strat model. | not used |
| `getResourceID` | function | Get the resource's ID. | USED report (resources) |
| `getResourceValue` | function | Get the resource's trade value. | USED report (resources) |
| `getResourceHasMine` | function | Check if the resource can have a mine. | not used |
| `hasMineBuilt` | function | Check if the resource has a mine built. | not used |
| `getResourceImage` | function | Get the resource's image (icon) relative path. | not used |

### fortStruct (4/32 used)

| member | kind | what it is | status |
|---|---|---|---|
| `xCoord` | field rw | `int` | USED report + order + other ? |
| `yCoord` | field rw | `int` | USED report + order + other ? |
| `governor` | property ro | `character` | USED report + other ? |
| `characterCount` | property ro | `int` | not used |
| `army` | field rw | `armyStruct` | USED order + event ? |
| `gatesAreOpened` | field rw | `int` | not used |
| `ownerFaction` | field rw | `factionStruct` | not used |
| `siegeNum` | field rw | `int` | not used |
| `maxHoldoutTurns` | field rw | `int` | not used |
| `siegeDuration` | field rw | `int` | not used |
| `preSiegePopulation` | field rw | `int` | not used |
| `factionTradedFrom` | field rw | `int` | not used |
| `plagueDuration` | field rw | `int` | not used |
| `salliedOut` | field rw | `int` | not used |
| `readyToSurrender` | field rw | `int` | not used |
| `takenByCrusade` | field rw | `crusadeStruct` | not used |
| `plagued` | field rw | `int` | not used |
| `subFactionID` | field rw | `int` | not used |
| `regionID` | field rw | `int` | not used |
| `creatorFactionID` | field rw | `int` | not used |
| `creatorCultureID` | field rw | `int` | not used |
| `rebelEntry` | field rw | `rebelFaction` | not used |
| `fortFortificationLevel` | field rw | `int` | not used |
| `bannerPosX` *(modding)* | field rw | `float` | not used |
| `bannerPosZ` *(modding)* | field rw | `float` | not used |
| `bannerPosY` *(modding)* | field rw | `float` | not used |
| `getSiege` | function | Get a specific siege by it's index | not used |
| `getCharacter` | function | Get a specific character by index. | not used |
| `changeOwner` | function | Change fort ownership. | not used |
| `isAllyToFaction` | function | Check if fort is allied to faction. | not used |
| `isEnemyToFaction` | function | Check if fort is at war with faction. | not used |
| `createArmyInFort` | function | Create an army in a fort (don't need a character). Used to add units to an empty fort. | not used |

### watchtowerStruct (4/7 used)

| member | kind | what it is | status |
|---|---|---|---|
| `xCoord` | field rw | `int` | USED report + order + other ? |
| `yCoord` | field rw | `int` | USED report + order + other ? |
| `factionID` | field rw | `int` | not used |
| `regionID` | field rw | `int` | not used |
| `faction` | field rw | `factionStruct` | USED report + order + event + other ? |
| `settlement` | field rw | `settlementStruct` | USED report + order + event + other ? |
| `blockingArmy` | field rw | `armyStruct` | not used |

### dockStruct (3/9 used)

| member | kind | what it is | status |
|---|---|---|---|
| `xCoord` | field rw | water tile, Note: setting only moves dock strat model | USED report + order + other ? |
| `yCoord` | field rw | water tile, Note: setting only moves dock strat model | USED report + order + other ? |
| `regionID` | field rw | `int` | not used |
| `ownerFaction` | field rw | Note: port's ownership changes to blockading faction (army on port) | not used |
| `settlement` | field rw | `settlementStruct` | USED report + order + event + other ? |
| `cultureID` | field rw | `int` | not used |
| `numTurnsBlocked` | field rw | `int` | not used |
| `port` | field rw | `portStruct` | not used |
| `dockedArmy` | field rw | `armyStruct` | not used |

### portStruct (3/9 used)

| member | kind | what it is | status |
|---|---|---|---|
| `xCoord` | field rw | land tile, Note: setting this only moves port's strat model. | USED report + order + other ? |
| `yCoord` | field rw | land tile, Note: setting this only moves port's strat model. | USED report + order + other ? |
| `ownerFaction` | field rw | Note: port's ownership changes to blockading faction (army on port) | not used |
| `settlement` | field rw | `settlementStruct` | USED report + order + event + other ? |
| `blockadingArmy` | field rw | Enemy army blockading the port, by standing on it's tile, check for nil. | not used |
| `dock` | field rw | water tile, only upgraded ports have this, check for nil. | not used |
| `regionID` | field rw | `int` | not used |
| `numTurnsBlocked` | field rw | `int` | not used |
| `cultureID` | field rw | `int` | not used |

## Events

279 members, 45 used (+1 by name only).

### events (30/243 used)

| member | kind | what it is | status |
|---|---|---|---|
| `onCharacterTurnStart` | event | Called at a character's turn start. [Exports: character (characterRecord), faction, regionID, characterType, religion] | not used |
| `onCapturedCharacterRansomed` | event | A captured character has been successfully ransomed back from the enemy. [Exports: character (characterRecord), faction, regionID, characterType, religion] | USED event |
| `onCapturedCharacterReleased` | event | A captured character has been released by the enemy. [Exports: character (characterRecord), faction, regionID, characterType, religion] | USED event |
| `onFatherDiesNatural` | event | A character father died of natural causes. [Exports: character (characterRecord), faction, regionID, characterType, religion] | USED event |
| `onPreBattleWithdrawal` | event | When a battle is about to start but one of the armies withdraws. [Exports: character (characterRecord), faction, regionID, characterType, religion] | not used |
| `onPostBattle` | event | When a battle has finished. [Exports: character (characterRecord), faction, regionID, characterType, religion] | not used |
| `onHireMercenaries` | event | A General has hired some mercenaries. [Exports: character (characterRecord), faction, regionID, characterType, religion] | not used |
| `onGeneralCaptureResidence` | event | A General has captured a residence such as a fort or watchtower. [Exports: character (characterRecord), faction, regionID, characterType, religion] | not used |
| `onLeaderDestroyedFaction` | event | A faction has been destroyed. [Exports: character (characterRecord), faction, regionID, characterType, religion] | not used |
| `onOfferedForAdoption` | event | An adoption has been proposed. [Exports: character (characterRecord), faction, regionID, characterType, religion] | USED event |
| `onLesserGeneralOfferedForAdoption` | event | A lesser general adoption has been proposed (man of the hour event). [Exports: character (characterRecord), faction, regionID, characterType, religion] | USED event |
| `onOfferedForMarriage` | event | A marriage offer has been proposed. [Exports: character (characterRecord), faction, regionID, characterType, religion] | USED event |
| `onBrotherAdopted` | event | A brother has been adopted. [Exports: character (characterRecord), faction, regionID, characterType, religion] | not used |
| `onBirth` | event | A child is born to the faction leader. [Exports: character (characterRecord), faction, regionID, characterType, religion] | not used |
| `onCharacterComesOfAge` | event | A character has come of age. [Exports: character (characterRecord), faction, regionID, characterType, religion] | not used |
| `onCharacterMarries` | event | A character has married. [Exports: character (characterRecord), faction, regionID, characterType, religion] | USED event |
| `onCharacterMarriesPrincess` | event | A character has married a princess. [Exports: character (characterRecord), faction, regionID, characterType, religion] | USED event |
| `onMarriageAlliancePossible` | event | A marriage alliance is possible. [Exports: character (characterRecord), faction, regionID, characterType, religion] | not used |
| `onMarriageAllianceOffered` | event | A marriage alliance has been offered. [Exports: character (characterRecord), faction, regionID, characterType, religion] | not used |
| `onPriestBecomesHeretic` | event | A priest has gone mad. [Exports: character (characterRecord), faction, regionID, characterType, religion] | not used |
| `onCharacterNearHeretic` | event | A character is adjacent to a heretic. [Exports: character (characterRecord), faction, regionID, characterType, religion] | not used |
| `onCharacterNearWitch` | event | A character is adjacent to a witch. [Exports: character (characterRecord), faction, regionID, characterType, religion] | not used |
| `onCardinalPromoted` | event | A character has been promoted to a cardinal. [Exports: character (characterRecord), faction, regionID, characterType, religion] | not used |
| `onCharacterBecomesAFather` | event | A character has become a father. [Exports: character (characterRecord), faction, regionID, characterType, religion] | not used |
| `onGeneralDevastatesTile` | event | A General and his army has devastated an enemy's fertile land. [Exports: character (characterRecord), faction, regionID, characterType, religion] | not used |
| `onExecutesASpyOnAMission` | event | A spying mission has failed and the spy is executed by the target. [Exports: character (characterRecord), faction, regionID, characterType, religion] | not used |
| `onExecutesAnAssassinOnAMission` | event | An assassination mission has failed and the assassin is executed by the target. [Exports: character (characterRecord), faction, regionID, characterType, religion] | not used |
| `onSufferAssassinationAttempt` | event | Someone has had an attempt on their life. [Exports: character (characterRecord), faction, regionID, characterType, religion] | USED event |
| `onSufferAcquisitionAttempt` | event | Someone has had an attempt on their assets. [Exports: character (characterRecord), faction, regionID, characterType, religion] | not used |
| `onSufferMarriageAttempt` | event | Someone has had an attempt on their bachelorhood. [Exports: character (characterRecord), faction, regionID, characterType, religion] | not used |
| `onSufferDenouncementAttempt` | event | Someone has had a denouncement attempt. [Exports: character (characterRecord), faction, regionID, characterType, religion] | not used |
| `onLeaderOrderedSabotage` | event | A Faction leader has ordered a sabotage mission. [Exports: character (characterRecord), faction, regionID, characterType, religion] | not used |
| `onAcceptBribe` | event | Someone has been bribed. [Exports: character (characterRecord), faction, regionID, characterType, religion] | USED event |
| `onRefuseBribe` | event | Someone has refused a bribe. [Exports: character (characterRecord), faction, regionID, characterType, religion] | not used |
| `onInsurrection` | event | Insurgence has been provoked. [Exports: character (characterRecord), faction, regionID, characterType, religion] | not used |
| `onLeaderOrderedDiplomacy` | event | A Faction leader has ordered a diplomacy mission. [Exports: character (characterRecord), faction, regionID, characterType, religion] | not used |
| `onNewAdmiralCreated` | event | A new admiral has been created for a new ship. [Exports: stratCharacter (character), character (characterRecord), faction, regionID, characterType, religion] | not used |
| `onGovernorBuildingDestroyed` | event | A building has been destroyed. [Exports: character (characterRecord), faction, regionID, characterType, religion, settlement] | not used |
| `onGovernorThrowGames` | event | Games have been thrown. [Exports: character (characterRecord), faction, regionID, characterType, religion] | not used |
| `onGovernorThrowRaces` | event | Races have been thrown. [Exports: character (characterRecord), faction, regionID, characterType, religion] | not used |
| `onCharacterSelected` | event | The player has selected a character. [Exports: character (characterRecord), targetSettlement, faction, regionID, characterType, religion] | not used |
| `onEnemyCharacterSelected` | event | The player has selected an enemy character. [Exports: character (characterRecord), faction, regionID, characterType, religion] | not used |
| `onMultiTurnMove` | event | The player has selected a position beyond the character's extents. [Exports: character (characterRecord), faction, regionID, characterType, religion] | not used |
| `onCharacterPanelOpen` | event | The player has opened the panel for the selected character. [Exports: character (characterRecord), faction, regionID, characterType, religion] | not used |
| `onLeaderMissionSuccess` | event | A mission has been completed. [Exports: character (characterRecord), faction, regionID, characterType, missionDetails, religion] | not used |
| `onLeaderMissionFailed` | event | A mission has failed. [Exports: character (characterRecord), faction, regionID, characterType, missionDetails, religion] | not used |
| `onGeneralJoinCrusade` | event | A General has been sent on Crusade/Jihad. [Exports: character (characterRecord), targetSettlement, faction, targetFaction, regionID, targetRegionID, characterType, religion, targetReligion, crusade] | not used |
| `onGeneralAbandonCrusade` | event | A General has left a Crusade/Jihad. [Exports: character (characterRecord), targetSettlement, faction, targetFaction, regionID, targetRegionID, characterType, religion, targetReligion, crusade] | not used |
| `onGeneralArrivesCrusadeTargetRegion` | event | A General has arrived in the Crusade/Jihad target region. [Exports: character (characterRecord), targetSettlement, faction, targetFaction, army, regionID, targetRegionID, characterType, religion, targetReligion, crusade] | not used |
| `onGeneralTakesCrusadeTarget` | event | A General has taken the Crusade/Jihad target settlement. [Exports: character (characterRecord), targetSettlement, faction, targetFaction, regionID, targetRegionID, characterType, religion, targetReligion, crusade] | not used |
| `onCharacterTurnEnd` | event | A Character has finished its turn. [Exports: character (characterRecord), settlement, faction, regionID, characterType, religion] | not used |
| `onCharacterTurnEndInSettlement` | event | A Character has finished its turn in a settlement. [Exports: character (characterRecord), settlement, faction, regionID, characterType, religion] | not used |
| `onBecomesFactionLeader` | event | The character has been made the faction leader. [Exports: character (characterRecord), faction, regionID, characterType, religion] | not used |
| `onCeasedFactionLeader` | event | The character is no longer faction leader. [Exports: character (characterRecord), faction, regionID, characterType, religion] | not used |
| `onBecomesFactionHeir` | event | The character has been made a faction heir. [Exports: character (characterRecord), faction, regionID, characterType, religion] | not used |
| `onCeasedFactionHeir` | event | The character is no longer faction heir. [Exports: character (characterRecord), faction, regionID, characterType, religion] | not used |
| `onCharacterDamagedByDisaster` | event | A character has been injured by a disaster. disasterTypes: earthquake, flood, horde, storm, volcano, dustbowl, locusts, famine, plague, riot, fire [Exports: character (characterRecord), faction, regionID, disasterType, characterT... | USED event |
| `onGeneralCaptureSettlement` | event | A General has captured a settlement. [Exports: character (characterRecord), settlement, targetSettlement, faction, targetFaction, regionID, characterType, religion] | not used |
| `onGeneralAssaultsResidence` | event | An assault has taken place. NOTE: settlement and fort are not in eventData! They are separate arguments!. [Exports: character (characterRecord), faction, targetFaction, regionID, targetRegionID, characterType, religion, targetRel... | not used |
| `onGeneralAssaultsGeneral` | event | An assault has taken place. [Exports: character (characterRecord), targetCharacter, faction, targetFaction, regionID, characterType, targetCharacterType, religion, targetReligion] | not used |
| `onCharacterAttacksCrusadingGeneral` | event | A general on crusade/jihad has been attacked by other character (it includes crusading generals attacked in a residence or on navy and generals attacked by spotted and killed assassin). [Exports: character (characterRecord), targ... | not used |
| `onGeneralPrisonersRansomedCaptor` | event | A General of a captor faction has made a ransom decision. ransomType: ransom, execute, release, cannot_pay_ransom [Exports: character (characterRecord), faction, targetFaction, regionID, characterType, religion, targetReligion, c... | not used |
| `onGeneralPrisonersRansomedCaptive` | event | A General of a captive faction has made a ransom decision. [Exports: character (characterRecord), faction, targetFaction, regionID, characterType, religion, targetReligion, captureInfo, ransomType] | not used |
| `onFactionLeaderPrisonersRansomedCaptor` | event | A captor faction has made a ransom decision. [Exports: character (characterRecord), faction, targetFaction, regionID, characterType, religion, targetReligion, captureInfo, ransomType] | not used |
| `onFactionLeaderPrisonersRansomedCaptive` | event | A captive faction has made a ransom decision. [Exports: character (characterRecord), faction, targetFaction, regionID, characterType, religion, targetReligion, captureInfo, ransomType] | not used |
| `onSpyMission` | event | A spy mission has completed. May also export fort or settlement if target was a garrison residence. missionSuccessLevel: not_successful, slightly_successful, partly_successful, highly_successful [Exports: character (characterReco... | USED event |
| `onAssassinationMission` | event | An assassination mission has completed. missionSuccessLevel: not_successful, slightly_successful, partly_successful, highly_successful [Exports: character (characterRecord), faction, regionID, characterType, missionSuccessLevel, ... | USED event |
| `onAcquisitionMission` | event | An acquisition mission has completed. missionSuccessLevel: not_successful, slightly_successful, partly_successful, highly_successful [Exports: character (characterRecord), faction, regionID, characterType, missionSuccessLevel, mi... | USED event |
| `onMarriageMission` | event | A marriage mission has completed. missionSuccessLevel: not_successful, slightly_successful, partly_successful, highly_successful [Exports: character (characterRecord), faction, regionID, characterType, missionSuccessLevel, missio... | USED event |
| `onDenouncementMission` | event | A denouncement mission has completed. missionSuccessLevel: not_successful, slightly_successful, partly_successful, highly_successful [Exports: character (characterRecord), faction, regionID, characterType, missionSuccessLevel, mi... | USED event |
| `onSabotageMission` | event | A sabotage mission has completed. missionSuccessLevel: not_successful, slightly_successful, partly_successful, highly_successful [Exports: character (characterRecord), faction, regionID, characterType, missionSuccessLevel, missio... | USED event |
| `onBriberyMission` | event | A bribery mission has completed. missionSuccessLevel: not_successful, slightly_successful, partly_successful, highly_successful [Exports: character (characterRecord), faction, targetFaction, regionID, characterType, missionSucces... | USED event |
| `onDiplomacyMission` | event | A diplomacy mission has completed. missionSuccessLevel: not_successful, slightly_successful, partly_successful, highly_successful [Exports: character (characterRecord), faction, targetFaction, regionID, characterType, missionSucc... | USED event |
| `onLeaderOrderedSpyingMission` | event | A Faction leader has ordered a spying mission. missionSuccessLevel: not_successful, slightly_successful, partly_successful, highly_successful [Exports: character (characterRecord), settlement, fort, faction, targetFaction, region... | not used |
| `onLeaderOrderedAssassination` | event | A Faction leader has ordered an assassination mission. missionSuccessLevel: not_successful, slightly_successful, partly_successful, highly_successful [Exports: character (characterRecord), targetCharacter, faction, regionID, char... | not used |
| `onLeaderOrderedBribery` | event | A Faction leader has ordered a bribery mission. [Exports: character (characterRecord), faction, regionID, characterType, religion] | not used |
| `onSettlementTurnStart` | event | A settlement is being processed for the start of its faction's turn. [Exports: settlement, faction, regionID, religion] | not used |
| `onUngarrisonedSettlement` | event | A settlement is no longer garrisoned. [Exports: settlement, faction, regionID, religion] | not used |
| `onSettlementUpgraded` | event | A settlement has been upgraded. [Exports: settlement, faction, regionID, religion] | not used |
| `onSettlementConverted` | event | A settlement has been converted. [Exports: settlement, faction, regionID, religion] | not used |
| `onSiegeEquipmentCompleted` | event | Siege equipment has been completed by one of the besieging armies. [Exports: settlement, faction, regionID, religion] | not used |
| `onSettlementTurnEnd` | event | A Settlement is being processed for the end of its faction's turn. [Exports: settlement, faction, regionID, religion] | not used |
| `onSettlementSelected` | event | The player has selected a settlement. [Exports: settlement, faction, regionID, religion] | not used |
| `onSettlementPanelOpen` | event | The player has opened the panel for the selected settlement. [Exports: settlement, faction, regionID, religion] | not used |
| `onRecruitmentPanelOpen` | event | The player has opened a recruitment panel. [Exports: settlement, faction, regionID, religion] | not used |
| `onConstructionPanelOpen` | event | The player has opened a construction panel. [Exports: settlement, faction, regionID, religion] | not used |
| `onTradePanelOpen` | event | The player has opened a trade panel. [Exports: settlement, faction, regionID, religion] | not used |
| `onSettlementScrollAdviceRequested` | event | The player has requested advice on the settlement scroll. [Exports: settlement, faction, regionID, resourceDescription, religion] | not used |
| `onGuildUpgraded` | event | A guild has been created/upgraded. [Exports: settlement, faction, regionID, resourceDescription, guildId, religion] | not used |
| `onGuildDestroyed` | event | A guild has been destroyed. [Exports: settlement, faction, regionID, guildId, religion] | not used |
| `onOccupySettlement` | event | A settlement has been captured and occupied. [Exports: character (characterRecord), faction, targetFaction, regionID, characterType, religion, targetReligion] | not used |
| `onSackSettlement` | event | A settlement has been captured and sacked. [Exports: character (characterRecord), faction, targetFaction, regionID, characterType, religion, targetReligion] | not used |
| `onExterminatePopulation` | event | A settlement has been captured and some of its population has been decimated. [Exports: character (characterRecord), faction, targetFaction, regionID, characterType, religion, targetReligion] | not used |
| `onCityRiots` | event | A settlement has rioted. [Exports: settlement, faction, targetFaction, regionID, religion, targetReligion] | not used |
| `onGiveSettlement` | event | A settlement has been given to another faction. [Exports: settlement, faction, targetFaction, regionID, religion, targetReligion] | not used |
| `onCityRebels` | event | A settlement has rebelled. [Exports: settlement, faction, targetFaction, regionID, religion, targetReligion] | not used |
| `onCitySacked` | event | A settlement has been razed. [Exports: settlement, faction, targetFaction, regionID, religion, targetReligion] | not used |
| `onGovernorCityRiots` | event | A settlement has rioted. [Exports: character (characterRecord), settlement, faction, targetFaction, regionID, characterType, religion, targetReligion] | not used |
| `onGovernorCityRebels` | event | A settlement has rebelled. [Exports: character (characterRecord), settlement, faction, targetFaction, regionID, characterType, religion, targetReligion] | not used |
| `onAbandonShowMe` | event | The player has abandoned a show me scipt. | not used |
| `onGameReloaded` | event | A strat map game has been reloaded. | not used |
| `onBattleWinningPlaza` | event | The plaza is being captured. | not used |
| `onBattleStopsWinningPlaza` | event | The plaza capture has been stopped. | not used |
| `onBattleDominatingPlaza` | event | The enemy will have captured the plaza in 30s. | not used |
| `onBattleEngineUnmanned` | event | A siege engine is now unmanned. | not used |
| `onBattlePlayerArmyHalfDestroyed` | event | Half of the player's army has been destroyed. | not used |
| `onBattleEnemyArmyHalfDestroyed` | event | Half of the enemy's army has been destroyed. | not used |
| `onBattleFinished` | event | The battle has finished. | not used |
| `onBattleArmyHalfDestroyed` | event | Half of an army has been destroyed. | not used |
| `onEscPressed` | event | The escape key has been pressed. This trigger will only fire if the command StealEscKey has been used. | not used |
| `onScriptedAdvice` | event | The player has been issued with advice by a script. | not used |
| `onNavalPreBattleScrollAdviceRequested` | event | The player has requested advice on the naval prebattle scroll. | not used |
| `onPreBattleScrollAdviceRequested` | event | The player has requested advice on the prebattle scroll. | not used |
| `onCollegeOfCardinalsPanelOpen` | event | The player has opened the college of cardinals panel. | not used |
| `onDiplomaticStandingPanelOpen` | event | The player has opened the diplomatic standing panel. | not used |
| `onBattlePlayerUnderAttackIdle` | event | An idle unit is under missile fire. | not used |
| `onBattleWinningCombat` | event | A team has gained the advantage in combat. | not used |
| `onBattleArmyTired` | event | The whole army is tired. | not used |
| `onBattleSpySuccess` | event | A spy has successfully opened the gates. | not used |
| `onBattleTideofBattle` | event | A different team is now the strongest. | not used |
| `onBattleUnitGoesBerserk` | event | A unit has gone berserk. [Exports: unit] | not used |
| `onBattleSiegeEngineDestroyed` | event | A siege engine has been destroyed. [Exports: unit] | not used |
| `onBattleSiegeEngineDocksWall` | event | A siege engine has docked with a wall. [Exports: unit] | not used |
| `onBattleGatesAttackedByEngine` | event | An engine has started attacking a gate. [Exports: unit] | not used |
| `onBattleGatesDestroyedByEngine` | event | An engine has destroyed a gate. [Exports: unit] | not used |
| `onBattleWallsBreachedByEngine` | event | A siege engine has knocked down a wall. [Exports: unit] | not used |
| `onBattleWallsCaptured` | event | A wall has been captured. [Exports: unit] | not used |
| `onBattleUnitRouts` | event | A unit has routed. [Exports: unit] | not used |
| `onUnitDisbanded` | event | A unit has been disbanded. [Exports: faction, playerUnit, eduEntry, religion] | not used |
| `onUnitTrained` | event | A unit has been trained. [Exports: settlement, faction, playerUnit, eduEntry, religion] | not used |
| `onGovernorUnitTrained` | event | A unit has been trained. [Exports: character (characterRecord), settlement, faction, regionID, playerUnit, eduEntry, characterType, religion] | not used |
| `onGovernorBuildingCompleted` | event | A building has been completed. [Exports: character (characterRecord), settlement, faction, regionID, priorBuild, characterType, religion] | not used |
| `onAgentCreated` | event | An agent has been trained. [Exports: character (characterRecord), settlement, faction, regionID, characterType, religion] | not used |
| `onGovernorAgentCreated` | event | An agent has been trained. [Exports: character (characterRecord), settlement, faction, regionID, characterType, religion] | not used |
| `onBuildingDestroyed` | event | A building has been destroyed. [Exports: settlement, faction, regionID, resourceDescription, religion] | not used |
| `onAddedToBuildingQueue` | event | A building has been added to the construction queue. [Exports: settlement, faction, regionID, resourceDescription, religion] | not used |
| `onBuildingCompleted` | event | A building has been completed. [Exports: settlement, faction, priorBuild, religion] | not used |
| `onRequestBuildingAdvice` | event | The player has requested building advice. [Exports: settlement, faction, regionID, religion] | not used |
| `onRequestTrainingAdvice` | event | The player has requested training advice. [Exports: settlement, faction, regionID, religion] | not used |
| `onAddedToTrainingQueue` | event | A unit has been added to the training queue. [Exports: settlement, faction, regionID, resourceDescription, religion] | not used |
| `onBattleArmyRouted` | event | An army has been entirely routed. [Exports: army] | not used |
| `onBattleReinforcementsArrive` | event | A reinforcing army has arrived on the battlefield. [Exports: army] | not used |
| `onRequestMercenariesAdvice` | event | The player has requested mercenaries advice. [Exports: army] | not used |
| `onButtonPressed` | event | The player has clicked on a button. [Exports: resourceDescription] | not used |
| `onShortcutTriggered` | event | The player triggered a keyboard shortcut. [Exports: resourceDescription] | not used |
| `onUIElementVisible` | event | A special UI Element is visible. [Exports: resourceDescription] | not used |
| `onScrollOpened` | event | The player opened a scroll. [Exports: resourceDescription] | USED event |
| `onScrollClosed` | event | The player closed a scroll. [Exports: resourceDescription] | not used |
| `onScrollAdviceRequested` | event | The player has requested advice on a scroll. [Exports: resourceDescription] | not used |
| `onAdviceSupressed` | event | The player has suppressed a piece of advice. [Exports: resourceDescription] | not used |
| `onBattleGeneralRouted` | event | A general has been routed. [Exports: stratCharacter (character), character (characterRecord)] | not used |
| `onBattleGeneralKilled` | event | A general has been killed. [Exports: stratCharacter (character)] | USED event |
| `onCrusadeCalled` | event | A Crusade/Jihad has been called. [Exports: targetSettlement, targetFaction, targetRegionID, targetReligion, crusade] | not used |
| `onPopeAcceptsCrusadeTarget` | event | The Pope has accepted the player's crusade target. [Exports: targetSettlement, targetFaction, targetRegionID, targetReligion, crusade] | not used |
| `onPopeRejectsCrusadeTarget` | event | The Pope has rejected the player's crusade target. [Exports: targetSettlement, targetFaction, targetRegionID, targetReligion, crusade] | not used |
| `onCrusadeEnds` | event | A Crusade/Jihad has ended. [Exports: targetSettlement, targetRegionID, crusade] | not used |
| `onPreFactionTurnStart` | event | Called before the faction's turn starts. [Exports: faction, religion] | not used |
| `onFactionTurnStart` | event | Called at a faction's turn start. [Exports: faction, religion] | USED event |
| `onFactionNewCapital` | event | Called after faction changes to a new capital. [Exports: faction, religion] | not used |
| `onFactionTurnEnd` | event | Called at a faction's turn end. [Exports: faction, religion] | USED event |
| `onVotedForPope` | event | A Faction has voted for the new pope. [Exports: faction, religion] | not used |
| `onFactionExcommunicated` | event | A Faction has been excommunicated. [Exports: faction, religion] | USED event |
| `onHordeFormed` | event | A Faction has formed a horde. [Exports: faction, religion] | not used |
| `onCardinalRemoved` | event | A cardinal has been removed from the game. [Exports: faction, religion] | not used |
| `onInquisitorAppointed` | event | An inquisitor has been dispatched to a region. [Exports: faction, religion] | not used |
| `onAssassinCaughtAttackingPope` | event | An assassination mission against the pope has failed and the assassin is executed. [Exports: faction, religion] | not used |
| `onFinancesPanelOpen` | event | The player has opened his finances panel. [Exports: faction, religion] | not used |
| `onFactionSummaryPanelOpen` | event | The player has opened the faction summary panel. [Exports: faction, religion] | not used |
| `onFamilyTreePanelOpen` | event | The player has opened the family tree panel. [Exports: faction, religion] | not used |
| `onDiplomacyPanelOpen` | event | The player has opened the diplomatic standing panel. [Exports: faction, religion] | not used |
| `onPreBattlePanelOpen` | event | The player has attacked an army or settlement. The decision panel is now open. [Exports: faction, religion] | USED event |
| `onIncomingMessage` | event | A message has arrived for the player. [Exports: faction, eventID, religion] | USED event |
| `onMessageOpen` | event | The player has opened a message. [Exports: faction, eventID, religion] | USED event |
| `onMessageClosed` | event | The player has closed a message. [Exports: eventID] | not used |
| `onDeclineAutomatedSettlementManagement` | event | The player has declined automated settlement management. [Exports: faction, religion] | not used |
| `onBattleAiCommenced` | event | The battle AI has begun processing. [Exports: faction, religion] | not used |
| `onBattleDelayPhaseCommenced` | event | The delay phase has begun. [Exports: faction, religion] | not used |
| `onBattleDeploymentPhaseCommenced` | event | The deployment phase has begun. [Exports: faction, religion] | not used |
| `onBattleConflictPhaseCommenced` | event | The conflict phase has begun. [Exports: faction, religion] | not used |
| `onFactionWarDeclared` | event | Called after a faction declares a war. [Exports: faction, targetFaction, religion, targetReligion] | not used |
| `onFactionAllianceDeclared` | event | Called after a faction declares an alliance. [Exports: faction, targetFaction, religion, targetReligion] | not used |
| `onInterFactionMarriage` | event | A marriage has occured between two factions. gets fired for both factions involved. [Exports: faction, targetFaction, religion, targetReligion] | not used |
| `onFactionTradeAgreementMade` | event | Called after a faction makes a trade agreement. [Exports: faction, targetFaction, religion, targetReligion] | not used |
| `onPopeElected` | event | A new pope has been elected. [Exports: faction, targetFaction, religion, targetReligion] | not used |
| `onFactionBreakAlliance` | event | Called after a faction breaks an alliance. [Exports: faction, targetFaction, religion, targetReligion] | USED event |
| `onUpdateAttitude` | event | A faction to faction attitude update has occurred (once every round). [Exports: faction, targetFaction, religion] | not used |
| `onDemeanour` | event | A demeanour response has occured in diplomacy talks. [Exports: faction, targetFaction, religion, targetReligion, amount] | not used |
| `onGiveMoney` | event | Called after a faction gives money to another faction. [Exports: faction, targetFaction, religion, targetReligion, amount] | not used |
| `onBattlePlayerUnitAttacksEnemyUnit` | event | A player unit has attacked one of the enemies units. [Exports: attackingUnit, defendingUnit, playerUnit, enemyUnit] | not used |
| `onBattleEnemyUnitAttacksPlayerUnit` | event | An enemy unit has attacked one of the players units. [Exports: attackingUnit, defendingUnit, playerUnit, enemyUnit] | not used |
| `onBattlePlayerUnitGoesBerserk` | event | One of the player's units has gone berserk. [Exports: playerUnit] | not used |
| `onBattlePlayerUnitRouts` | event | One of the player's units has routed. [Exports: playerUnit] | not used |
| `onBattlePlayerSiegeEngineDestroyed` | event | A siege engine belonging to the player has been destroyed. [Exports: playerUnit] | not used |
| `onBattleGatesAttackedByPlayerEngine` | event | A player's engine has started attacking a gate. [Exports: playerUnit] | not used |
| `onBattleEnemyUnitGoesBerserk` | event | One of the enemy's units has gone berserk. [Exports: enemyUnit] | not used |
| `onBattleEnemyUnitRouts` | event | One of the enemy's units has routed. [Exports: enemyUnit] | not used |
| `onBattleEnemySiegeEngineDestroyed` | event | A siege engine belonging to the enemy has been destroyed. [Exports: enemyUnit] | not used |
| `onBattleGatesAttackedByEnemyEngine` | event | An enemy's engine has started attacking a gate. [Exports: enemyUnit] | not used |
| `onDisaster` | event | When a particular disaster has just happened. [Exports: resourceDescription] | not used |
| `onEventCounter` | event | An event counter has changed it's value. [Exports: eventCounter] | not used |
| `onUngarrisonedFort` | event | The last unit has been removed from a fort, agents do not count. [Exports: fort, faction, regionID, religion] | not used |
| `onObjSeen` | event | An object of the target faction has been seen by the faction. [Exports: faction, targetFaction, regionID, coords, religion] | not used |
| `onTileSeen` | event | The tile has been seen by the faction. [Exports: faction, regionID, coords, religion] | not used |
| `onTransgression` | event | A faction to faction transgression has occurred. transgressions: TC_THREATEN_WAR, TC_DECLARED_WAR, TC_MINOR_ASSASSINATION_ATTEMPT, TC_BROKE_TREATY_TERMS, TC_BROKE_ALLIANCE, TC_INVASION [Exports: faction, targetFaction, resourceDe... | not used |
| `onForgiveness` | event | A faction to faction forgiveness has occurred. forgiveness: FC_MILITARY_ASSISTANCE, FC_OBVIOUS_BRIBE [Exports: faction, targetFaction, resourceDescription, religion] | not used |
| `onArmyTakesCrusadeTarget` | event | An army has taken a crusade or jihad target settlement. [Exports: targetSettlement, faction, targetFaction, army, regionID, targetRegionID, coords, religion, targetReligion, crusade] | not used |
| `onUnitsDesertCrusade` | event | Units have deserted a crusade or jihad. [Exports: targetSettlement, faction, targetFaction, targetRegionID, religion, targetReligion, crusade] | not used |
| `onLoadingFonts` | event | Called when ImGui backend reload fonts | not used |
| `onNewGameStart` | event | Called when a new campaign is started from the menu (when you click the start campaign button, nothing loaded yet). | not used |
| `onEduParsed` | event | Called after the game reads the EDU at startup (add units here). Previously called onReadGameDbsAtStart. | not used |
| `onGameInit` | event | Called after the game has loaded to the main menu. | not used |
| `onExitToMenu` | event | Called after campaign has exited to the main menu. | not used |
| `onNewGameLoaded` | event | Called after a new campaign's data has been loaded first time. (M2TW.stratMap and M2TW.campaign) | not used |
| `onUnloadCampaign` | event | Called after the campaignStruct gets unloaded (exit to menu, load save etc). | not used |
| `onAiTurn` | event | Called on ai initialized on turn start. | not used |
| `onBattleCompleted` | event | Called when an auto-resolved or manual battle ends. Keep in mind characters that will die due to being in a defensive garrison that lost or have no flee tile will not be marked as death yet but will be destroyed with the army. | not used |
| `onCalculateLTGD` | event | Called just after LTGD reads xml every turn. | not used |
| `onSetProductionControllers` | event | Called just before the personality production values are propogated to the production controllers. | not used |
| `onSpawnArmy` | event | Called when an army has been spawned via campaign_script or lua spawnArmy | not used |
| `onClickAtTile` | event | Called on clicking the stratmap. | not used |
| `onCharacterClicked` | event | Called when clicking on a character. | not used |
| `onCampaignTick` | event | Called on campaign tick. | not used |
| `onBattleTick` | event | Called on battle tick. | not used |
| `onCampaignMapLoaded` | event | Called after loading the campaign map, including cas models and textures. Best used for model related stuff. This fires every time including post-battle and save loading. | USED event |
| `onRemoveFromUnitQueue` | event | Called when a unit is removed from the unit queue. | not used |
| `onPluginLoad` | event | Called on plugin load (at game start). | USED event |
| `onCreateSaveFile` | event | Called on creating a new save file. | not used |
| `onLoadSaveFile` | event | Called on loading a save file. | not used |
| `onChangeTurnNum` | event | Called at the start of a new turn. | not used |
| `onSelectWorldpkgdesc` | event | Called on select worldpkgdesc for battlemap. See https://wiki.twcenter.net/index.php?title=.worldpkgdesc_-_M2TW. M2TWEOP will ignore the return value if its group does not match the required group! | not used |
| `onFortificationLevelS` | event | Called on specified fortificationlevel in a siege of a settlement. | not used |
| `onCalculateUnitValue` | event | Called when the game calculates the value of a unit. For example, in battle, when it says 'Victory seems certain' when units are engaging each other it uses this, it uses this to decide which units to recruit, to evaluate army st... | not used |
| `onEndSiege` | event | Called on the completion of the siege (in any way, with any outcome). | not used |
| `onStartSiege` | event | Called on the starting of the siege (in any way, with any outcome). | not used |
| `onFactionSymbolSelect` | event | Called when clicking on a faction symbol in the faction selection menu. | not used |
| `onCharacterDied` | event | Called when a character dies. | not used |
| `onFactionDied` | event | Called when a faction dies. | not used |
| `onCharacterSwitchFaction` | event | Called when a character switch faction. | not used |
| `onCalculationRatioForBirth` | event | Called when a calculation ratio for birth or adoption. Note: The default value is how many regions the faction owns | not used |
| `onCreateTooltip` | event | Called when the in-game tooltip is created(strat map objects, buttons, etc). Works only for "yellow" tooltips. Works only for existing tooltips. | not used |
| `onCreateTooltipByCoords` | event | Called when checking the conditions for creating a tooltip based on the coordinates of the campaign map. Works only for "yellow" tooltips. Use this to create a new tooltip at specific coordinates. | not used |
| `onBlockadePort` | event | Called when the port is blocked. | not used |
| `onUnitDestroy` | event | Called when the unit has been destroyed. | not used |

### eventTrigger (16/36 used)

| member | kind | what it is | status |
|---|---|---|---|
| `attackingUnit` | property ro | `unit` | not used |
| `defendingUnit` | property ro | `unit` | not used |
| `stratCharacter` | property ro | `character` | USED event |
| `character` | property ro | Note it is characterRecord, not character | USED event |
| `targetCharacter` | property ro | Note it is characterRecord, not character | not used |
| `settlement` | property ro | `settlementStruct` | USED other |
| `targetSettlement` | property ro | `settlementStruct` | USED other |
| `fort` | property ro | `fortStruct` | not used |
| `faction` | property ro | `factionStruct` | USED event + other |
| `targetFaction` | property ro | `factionStruct` | USED event + other |
| `army` | property ro | `armyStruct` | USED report (visible_enemies/seen_agents/nearby_settlements) + order |
| `regionID` | property ro | `int` | USED event |
| `targetRegionID` | property ro | `int` | not used |
| `playerUnit` | property ro | `unit` | not used |
| `enemyUnit` | property ro | `unit` | not used |
| `battleBuilding` | property ro | `buildingBattle` | not used |
| `priorBuild` | property ro | `buildingInQueue` | not used |
| `resourceDescription` | property ro | `string` | USED event + other |
| `eduEntry` | property ro | `eduEntry` | not used |
| `characterType` | property ro | `int` | not used |
| `targetCharacterType` | property ro | `int` | not used |
| `disasterType` | property ro | `string` | USED event |
| `missionSuccessLevel` | property ro | `string` | USED event |
| `missionProbability` | property ro | `int` | USED event |
| `missionDetails` | property ro | `missionDetailsStruct` | USED other |
| `eventID` | property ro | `int` | USED event |
| `guildID` | property ro | `int` | not used |
| `eventCounter` | property ro | `string` | not used |
| `coords` | property ro | `coordPair` | not used |
| `religion` | property ro | `int` | not used |
| `targetReligion` | property ro | `int` | not used |
| `amount` | property ro | `float` | USED order |
| `crusade` | property ro | `crusadeStruct` | not used |
| `captureInfo` | property ro | `capturedFactionInfo` | not used |
| `ransomType` | property ro | `string` | not used |
| `unit` | property ro | `unit` | USED report + order + other ? |

## Global functions (M2TWEOP, stratmap)

148 members, 12 used.

### M2TWEOP (5/121 used)

| member | kind | what it is | status |
|---|---|---|---|
| `getModPath` *(modding)* | function | Function to return the path to the mod folder, starts from the drive not the game folder. | not used |
| `getModFolderName` *(modding)* | function | Get the name of the mod folder. | not used |
| `toggleConsole` *(modding)* | function | Open/close the lua console. | USED report + order + event + other |
| `toggleDeveloperMode` *(modding)* | function | Toggle developer mode. | not used |
| `reloadScript` *(modding)* | function | Reload the lua script (without restarting the plugin itself, onPluginLoad doesn't fire). | not used |
| `restartLua` *(modding)* | function | Restart the lua plugin (onPluginLoad fires). | USED report + order + event |
| `saveGame` | function | Save the game. | not used |
| `getAncillary` | function | Get an ancillary by name. | not used |
| `getAncillaryByIndex` | function | Get an ancillary by index. | not used |
| `getAncillaryCount` | function | Get ancillary count. | not used |
| `getTrait` | function | Get a trait by name. | not used |
| `getTraitByIndex` | function | Get a trait by index. | not used |
| `getTraitCount` | function | Get trait count. | not used |
| `copyFile` *(modding)* | function | Copy a file. | not used |
| `setExpandedString` *(modding)* | function | Set a string in the expanded string table. | not used |
| `getExpandedString` | function | Get a string from the expanded string table. | not used |
| `setStratString` *(modding)* | function | Set a string in the strat string table. | not used |
| `getStratString` | function | Get a string from the strat string table. | not used |
| `getGameVersion` | function | Function to get the game version. | not used |
| `setPerfectSpy` *(modding)* | function | Set perfect spy. | not used |
| `getLocalFactionID` | function | Get local faction ID. | not used |
| `getPluginPath` *(modding)* | function | Function to return the path to the plugin (location of your LUA files). | not used |
| `logGame` | function | Log something to the game log. | not used |
| `loadGame` | function | Load a savegame. | not used |
| `loadTexture` *(modding)* | function | Load d3d texture | not used |
| `unloadTexture` *(modding)* | function | Unload d3d texture | not used |
| `setAncillariesLimit` *(modding)* | function | Sets the limit of ancillaries per character on the stratmap. | not used |
| `unlockGameConsoleCommands` *(modding)* | function | Unlocks all console commands, also allows the use of the 'control' command to change factions in singleplayer... | USED event |
| `setMaxBgSize` *(modding)* | function | Sets the maximum amount of soldiers a general's bodyguard unit can replenish to. The value is multiplied by t... | not used |
| `setMinBgSize` *(modding)* | function | Sets the minimum amount of soldiers a general's bodyguard unit can replenish to. The value is multiplied by t... | not used |
| `setExtraLeaderSoldiers` *(modding)* | function | Sets the extra amount of soldiers faction leaders get. The value is multiplied by the unit size modifiers (e.... | not used |
| `setExtraHeirSoldiers` *(modding)* | function | Sets the extra amount of soldiers faction heirs get. The value is multiplied by the unit size modifiers (e.g ... | not used |
| `setEDUUnitsSize` *(modding)* | function | Sets the new maximum soldier count. | not used |
| `setTextureCacheSize` *(modding)* | function | Set a size limit for UI texture cache. The new maximum size is 2048 x 2048. This also changes the maximum siz... | not used |
| `unlockWeaponLimit` *(modding)* | function | Set the weapon limit for units to 3. | not used |
| `openGateOnStratMap` | function | Opens or closes settlement and fort gates for the current siege on both the strategic and tactical maps, rega... | not used |
| `playGameSound` *(modding)* | function | Enables the specified game sound event (see SOUND_EVENTS in soundEvents.lua). | not used |
| `resetTooltipText` *(ui)* | function | Reset current game tooltip text. | not used |
| `getTooltipActive` *(ui)* | function | Get game tooltip activity. | not used |
| `getLastCursorState` | function | Get game last cursor state. | not used |
| `setAdvancedSettlementInfoScrollFrameSize` *(modding)* | function | Change the frame size in the "advanced_settlement_info_scroll" scroll. By default: 442 x 358. | not used |
| `setMercsScrollNumOfLines` *(modding)* | function | //Set the number of lines in the mercenaries menu. By default: 3. | not used |
| `setMercsScrollParameters` *(modding)* | function | Set parameters for the mercenary scroll. By default: 18, 6, 9, 3, 92. | not used |
| `setEnemyArmyUnitsScrollParameters` *(modding)* | function | Set parameters for the enemy army units scroll. By default: 18, 9, 42, 56. | not used |
| `getSettlementInfoScroll` *(ui)* | function | Gets a struct containing color information about the settlement info scroll. | not used |
| `setBuildingChainLimit` *(modding)* | function | `setBuildingChainLimit` | not used |
| `setConversionLvlFromCastle` *(modding)* | function | `setConversionLvlFromCastle` | not used |
| `setConversionLvlFromCity` *(modding)* | function | `setConversionLvlFromCity` | not used |
| `setGuildCooldown` *(modding)* | function | `setGuildCooldown` | not used |
| `toggleUnitsBMapHighlight` *(modding)* | function | Toggle the highlighting of units on the tactical map. | not used |
| `getBattleCamCoords` | function | Get the current x, y and z coords of the battlemap camera | not used |
| `setReligionsLimit` *(modding)* | function | Set the maximum number of religions in the mod (per descr\_religions.txt). Do not use religions > 10 in Comba... | not used |
| `setEquipmentCosts` *(modding)* | function | Set the siege points required to make different siege equipment. | not used |
| `isTileFree` | function | Checks if a tile is free. | not used |
| `getStratHoveredCoords` | function | Get the hovered tile coordinates on the strategy map. | not used |
| `getBattleHoveredCoords` | function | Get the hovered position coordinates on the battle map. | not used |
| `getGameTileCoordsWithCursor` | function |  | not used |
| `getTileRegionID` | function |  | not used |
| `getTileVisibility` | function | Get a specific tile's visibility according to faction (i.e can a faction see a tile) Note: Once the tile has ... | not used |
| `getRegionOwner` | function |  | not used |
| `getReligionName` | function | Get religion name by index. | not used |
| `getReligionCount` | function | Get the amount of religions. | not used |
| `getCultureName` | function | Get culture name by index. | USED report + order |
| `getClimateName` | function | Get climate name by index. | not used |
| `getReligion` | function | Get religion ID by name. | not used |
| `getCultureID` | function | Get culture ID by name. | not used |
| `getClimateID` | function | Get climate ID by name. | not used |
| `getOptions1` | function | Get some game options. | not used |
| `getOptions2` | function | Get some game options. | USED other |
| `getCampaignDifficulty1` | function | Get the campaign difficulty modifiers. Note: If making changes, make sure to re-apply in onPreFactionTurnStart | not used |
| `getCampaignDifficulty2` | function | Get the campaign difficulty modifiers. Note: If making changes, make sure to re-apply in onPreFactionTurnStart | not used |
| `getCampaignDb` | function | Get the campaign options. | not used |
| `getCampaignDbExtra` | function | Get the campaign options. | not used |
| `addModelToGame` *(modding)* | function | Add a new .cas campaign strategy model to the game with a unique ID. This should be called during onPluginLoa... | not used |
| `condition` | function | Check game condition. | not used |
| `getTileMoveCost` | function | Calculate movement point cost between two adjacent tiles. | not used |
| `setModel` *(modding)* | function | Set the strategy model for object at specified coordinates, works only for supported object types | not used |
| `callConsole` *(modding)* | function | Execute a Medieval II console command. | not used |
| `setScriptCounter` *(modding)* | function | Set an event\_counter value, does not work for counters, only event\_counters. | not used |
| `getScriptCounter` *(modding)* | function | Get a script counter value, works for counters and for event\_counters | not used |
| `getEopAiConfig` *(modding)* | function | Get AI config. | not used |
| `getRebelFaction` | function | Get a rebel faction. | not used |
| `getFactionRecord` | function | Get a faction record. | not used |
| `getFactionRecordNum` | function | Get amount of factions in descr_sm_factions. | not used |
| `hideUnknownUnitTooltips` *(modding)* | function | Hides tooltips for unknown units, only use if you use empty card instead of question mark as the UI. Disabled... | not used |
| `useEopFrontiers` *(modding)* | function | Recalculates frontier tiles for the AI using EOP algorithms. | not used |
| `ignoreOwnershipRecruitment` *(modding)* | function | Don't require edu ownership for recruitment. Disabled by default. | not used |
| `changeGeneralPosition` | function | Place the general in inside the unit instead of the left edge to make him less vulnerable to cavalry charges.... | not used |
| `modelExists` *(modding)* | function | Check if a model is a valid entry in the bmdb. | not used |
| `setApIsShieldPiercing` *(modding)* | function | Set if armour piercing missile attacks also halve shield stat. Default: true | not used |
| `handleUnitCards` *(modding)* | function | Faction specific unit cards are always chosen if found. Enabled by default. | not used |
| `setWeaponBonusModifier` *(modding)* | function | Set attack added for each level of weapon bonus. Default: 3. | not used |
| `setArmourUpgradeModifier` *(modding)* | function | Set armour added for each level of armour upgrade. Default: 2. | not used |
| `setPhalanxMissileDefense` *(modding)* | function | Set amount of extra defense against missiles phalanx formation gives. Default: 4. | not used |
| `setSchiltromMissileDefense` *(modding)* | function | Set amount of extra defense against missiles schiltrom formation gives. Default: 1. | not used |
| `setShieldWallMissileDefense` *(modding)* | function | Set amount of extra defense against missiles shieldwall formation gives. Default: 0. | not used |
| `setElephantHitpointDamage` *(modding)* | function | Set amount of hitpoint damage javelins do to elephants. Default: 4. | not used |
| `setElephantJavBonus` *(modding)* | function | Set amount of bonus attack thrown attribute gives against elephants. Default: 10. | not used |
| `enableRangedWeaponUpg` *(modding)* | function | Enable ranged attack bonus from weapon upgrades. Enabled by default in EOP. | not used |
| `drawUnitCardOutline` *(modding)* | function | Draw white outline around soldier numbers on the unit card. Enabled by default in EOP. | not used |
| `noMovementResetOnFlee` *(modding)* | function | Disable movement being set to 0 after a character withdraws from battle. This favours the player, because the... | not used |
| `noAiMissileLooseFormation` *(modding)* | function | Disable AI units going into loose formation while being shot at. Enabled by default in EOP. | not used |
| `alwaysAbortLua` *(modding)* | function | Always abort on LUA errors. Prevents savegame corruption. | not used |
| `displayEnemyStats` *(modding)* | function | Display enemy stats such as kills post battle, instead of only player. Enabled by default in EOP. | not used |
| `enableAiBattles` *(modding)* | function | Enable watching AI battles for AI campaigns instead of autoresolve. Disabled by default. | not used |
| `randomizeHealing` *(modding)* | function | Instead of first soldiers that died, random soldiers will be healed. Enabled by default. | not used |
| `aiBattleFrequency` | function | If AI battles are enabled, how often should they occur (for example 2 means every other battle). 1 by default. | not used |
| `setWatchTowerRange` *(modding)* | function | Set watchtower range. Default: 10. | not used |
| `enableFamilyEventsWithoutTree` *(modding)* | function | Factions without a family tree or a teutonic one still get marriage offers and produce children. Enabled by d... | not used |
| `setKhakiTextColor` *(modding)* | function | Change color of default khaki text. | not used |
| `setRgbaTextColor` *(modding)* | function | Change one RGBA color to another. | not used |
| `enableDebugInfo` *(modding)* | function | Enable display of debug information. | not used |
| `enableEopCamera` *(modding)* | function | Enable EOP stratmap camera. Control: Keypad7 - left rotate, Keypad9 - right rotate, Keypad8 - reset rotate. M... | not used |
| `viewTacticalMap` | function | View tactical map at the specified coordinates. | not used |
| `getMinorSettlementBalance` | function | Get modifiers for minor settlements for income and growth. | not used |
| `generateSprite` *(modding)* | function | Generate sprites for a battle model entry in the bmdb. There needs to be a export/unit_sprites folder in your... | not used |
| `getPhalanxOptions` | function | Get EOP Phalanx Options | not used |
| `getGroundTypeMoveCost` | function | Get the move cost of a ground type. | not used |
| `setGroundTypeMoveCost` *(modding)* | function | Set the move cost of a ground type. | not used |
| `addBanner` *(modding)* | function | Add a banner symbol. Add them onCampaignMapLoaded or later! | not used |
| `scriptCommand` *(modding)* | function | Fire any script command available from the game. It is always just 2 parameters in the function, the command ... | not used |

### stratmap.game (4/11 used)

| member | kind | what it is | status |
|---|---|---|---|
| `getFactionsCount` | function |  | USED report (family, visible_enemies/seen_agents/nearby_settlements) + order + event + other |
| `getFaction` | function |  | USED report (family, visible_enemies/seen_agents/nearby_settlements) + order + event + other |
| `callConsole` *(modding)* | function |  | not used |
| `createCharacterByString` | function |  | not used |
| `spawnArmy` | function |  | not used |
| `createArmy` | function |  | not used |
| `createArmyInSettlement` | function |  | USED other |
| `historicEvent` | function |  | not used |
| `setScriptCounter` *(modding)* | function |  | not used |
| `getScriptCounter` *(modding)* | function |  | not used |
| `scriptCommand` *(modding)* | function |  | USED report + order + event + other |

### stratmap (2/3 used)

| member | kind | what it is | status |
|---|---|---|---|
| `objects` | field |  | not used |
| `camera` *(ui)* | field |  | USED other |
| `game` | field |  | USED report (family, visible_enemies/seen_agents/nearby_settlements) + order + event + other |

### stratmap.camera (1/3 used)

| member | kind | what it is | status |
|---|---|---|---|
| `move` | function |  | not used |
| `jump` | function |  | USED other |
| `zoom` *(ui)* | function |  | not used |

### M2TW (0/5 used)

| member | kind | what it is | status |
|---|---|---|---|
| `battle` | property ro | `battleStruct` | not used |
| `campaign` | property ro | `campaignStruct` | not used |
| `stratMap` | property ro | `stratMap` | not used |
| `uiCardManager` *(ui)* | property ro | `uiCardManager` | not used |
| `selectionInfo` | property ro | `selectionInfo` | not used |

### stratmap.objects (0/5 used)

| member | kind | what it is | status |
|---|---|---|---|
| `startDrawModelAt` *(modding)* | function |  | not used |
| `stopDrawModel` *(modding)* | function |  | not used |
| `addCharacterCas` *(modding)* | function |  | not used |
| `setModel` *(modding)* | function |  | not used |
| `replaceTile` | function |  | not used |

## Enums and constants

530 members, 3 used.

### dipRelType (3/5 used)

| member | kind | what it is | status |
|---|---|---|---|
| `war` | enum ro | `int` | USED report + order |
| `peace` | enum ro | `int` | USED report + order |
| `alliance` | enum ro | `int` | USED report + order |
| `suzerain` | enum ro | `int` | not used |
| `trade` | enum ro | (Doesn't work with trade rights agreements set at game start) | not used |

### aiObjective (0/19 used)

| member | kind | what it is | status |
|---|---|---|---|
| `invalid` | enum ro | `int` | not used |
| `moveToPoint` | enum ro | `int` | not used |
| `attackEnemyBattleGroup` | enum ro | `int` | not used |
| `defendTerrainHill` | enum ro | `int` | not used |
| `defendTerrainForest` | enum ro | `int` | not used |
| `defendTerrainArea` | enum ro | `int` | not used |
| `defendCrossing` | enum ro | `int` | not used |
| `assaultCrossing` | enum ro | `int` | not used |
| `defendLine` | enum ro | `int` | not used |
| `scout` | enum ro | `int` | not used |
| `withdraw` | enum ro | `int` | not used |
| `defendSettlement` | enum ro | `int` | not used |
| `supportDefendSettlement` | enum ro | `int` | not used |
| `attackSettlement` | enum ro | `int` | not used |
| `skirmish` | enum ro | `int` | not used |
| `bombard` | enum ro | `int` | not used |
| `attackModel` | enum ro | `int` | not used |
| `sallyOut` | enum ro | `int` | not used |
| `ambush` | enum ro | `int` | not used |

### aiPlan (0/11 used)

| member | kind | what it is | status |
|---|---|---|---|
| `doNothing` | enum ro | `int` | not used |
| `attackAll` | enum ro | `int` | not used |
| `defend` | enum ro | `int` | not used |
| `defendFeature` | enum ro | `int` | not used |
| `hide` | enum ro | `int` | not used |
| `ambush` | enum ro | `int` | not used |
| `scout` | enum ro | `int` | not used |
| `withdraw` | enum ro | `int` | not used |
| `attackSettlement` | enum ro | `int` | not used |
| `defendSettlement` | enum ro | `int` | not used |
| `sallyOut` | enum ro | `int` | not used |

### battleBuildingType (0/4 used)

| member | kind | what it is | status |
|---|---|---|---|
| `ambient` *(battle)* | enum ro | `int` | not used |
| `gate` *(battle)* | enum ro | `int` | not used |
| `tower` *(battle)* | enum ro | `int` | not used |
| `wall` *(battle)* | enum ro | `int` | not used |

### battleState (0/8 used)

| member | kind | what it is | status |
|---|---|---|---|
| `notInBattle` *(battle)* | enum ro | `int` | not used |
| `preBattle` *(battle)* | enum ro | `int` | not used |
| `delay` *(battle)* | enum ro | `int` | not used |
| `deployment` *(battle)* | enum ro | `int` | not used |
| `deploymentPlayer2` *(battle)* | enum ro | `int` | not used |
| `conflict` *(battle)* | enum ro | `int` | not used |
| `victoryScroll` *(battle)* | enum ro | `int` | not used |
| `pursuit` *(battle)* | enum ro | `int` | not used |

### battleSuccess (0/4 used)

| member | kind | what it is | status |
|---|---|---|---|
| `close` *(battle)* | enum ro | `int` | not used |
| `average` *(battle)* | enum ro | `int` | not used |
| `clear` *(battle)* | enum ro | `int` | not used |
| `crushing` *(battle)* | enum ro | `int` | not used |

### battleType (0/8 used)

| member | kind | what it is | status |
|---|---|---|---|
| `ambushSuccess` *(battle)* | enum ro | `int` | not used |
| `ambushFail` *(battle)* | enum ro | `int` | not used |
| `open` *(battle)* | enum ro | `int` | not used |
| `siege` *(battle)* | enum ro | `int` | not used |
| `sally` *(battle)* | enum ro | `int` | not used |
| `naval` *(battle)* | enum ro | `int` | not used |
| `withdrawal` *(battle)* | enum ro | `int` | not used |
| `meetEnemy` *(battle)* | enum ro | `int` | not used |

### buildingCapability (0/57 used)

| member | kind | what it is | status |
|---|---|---|---|
| `population_growth_bonus` | enum ro | `int` | not used |
| `population_loyalty_bonus` | enum ro | `int` | not used |
| `population_health_bonus` | enum ro | `int` | not used |
| `trade_base_income_bonus` | enum ro | `int` | not used |
| `trade_level_bonus` | enum ro | `int` | not used |
| `trade_fleet` | enum ro | `int` | not used |
| `taxable_income_bonus` | enum ro | `int` | not used |
| `mine_resource` | enum ro | `int` | not used |
| `farming_level` | enum ro | `int` | not used |
| `road_level` | enum ro | `int` | not used |
| `gate_strength` | enum ro | `int` | not used |
| `gate_defences` | enum ro | `int` | not used |
| `wall_level` | enum ro | `int` | not used |
| `tower_level` | enum ro | `int` | not used |
| `armour` | enum ro | `int` | not used |
| `stage_games` | enum ro | `int` | not used |
| `stage_races` | enum ro | `int` | not used |
| `fire_risk` | enum ro | `int` | not used |
| `weapon_melee_simple` | enum ro | `int` | not used |
| `weapon_melee_blade` | enum ro | `int` | not used |
| `weapon_missile_mechanical` | enum ro | `int` | not used |
| `weapon_missile_gunpowder` | enum ro | `int` | not used |
| `weapon_artillery_mechanical` | enum ro | `int` | not used |
| `weapon_artillery_gunpowder` | enum ro | `int` | not used |
| `weapon_naval_gunpowder` | enum ro | `int` | not used |
| `upgrade_bodyguard` | enum ro | `int` | not used |
| `recruits_morale_bonus` | enum ro | `int` | not used |
| `recruits_exp_bonus` | enum ro | `int` | not used |
| `happiness_bonus` | enum ro | `int` | not used |
| `law_bonus` | enum ro | `int` | not used |
| `construction_cost_bonus_military` | enum ro | `int` | not used |
| `construction_cost_bonus_religious` | enum ro | `int` | not used |
| `construction_cost_bonus_defensive` | enum ro | `int` | not used |
| `construction_cost_bonus_other` | enum ro | `int` | not used |
| `construction_time_bonus_military` | enum ro | `int` | not used |
| `construction_time_bonus_religious` | enum ro | `int` | not used |
| `construction_time_bonus_defensive` | enum ro | `int` | not used |
| `construction_time_bonus_other` | enum ro | `int` | not used |
| `construction_cost_bonus_wooden` | enum ro | `int` | not used |
| `construction_cost_bonus_stone` | enum ro | `int` | not used |
| `construction_time_bonus_wooden` | enum ro | `int` | not used |
| `construction_time_bonus_stone` | enum ro | `int` | not used |
| `free_upkeep` | enum ro | `int` | not used |
| `pope_approval` | enum ro | `int` | not used |
| `pope_disapproval` | enum ro | `int` | not used |
| `religion_level` | enum ro | `int` | not used |
| `amplify_religion_level` | enum ro | `int` | not used |
| `archer_bonus` | enum ro | `int` | not used |
| `cavalry_bonus` | enum ro | `int` | not used |
| `heavy_cavalry_bonus` | enum ro | `int` | not used |
| `gun_bonus` | enum ro | `int` | not used |
| `navy_bonus` | enum ro | `int` | not used |
| `recruitment_cost_bonus_naval` | enum ro | `int` | not used |
| `retrain_cost_bonus` | enum ro | `int` | not used |
| `weapon_projectile` | enum ro | `int` | not used |
| `income_bonus` | enum ro | `int` | not used |
| `recruitment_slots` | enum ro | `int` | not used |

### characterAttr (0/109 used)

| member | kind | what it is | status |
|---|---|---|---|
| `command` | enum ro | `int` | not used |
| `influence` | enum ro | increases command radius | not used |
| `subterfuge` | enum ro | `int` | not used |
| `loyalty` | enum ro | `int` | not used |
| `charm` | enum ro | princess only | not used |
| `finance` | enum ro | merchant only | not used |
| `piety` | enum ro | `int` | not used |
| `magic` | enum ro | witch only, doesnt really do anything | not used |
| `chivalry` | enum ro | `int` | not used |
| `authority` | enum ro | `int` | not used |
| `level` | enum ro | `int` | not used |
| `unorthodoxy` | enum ro | influences chance for priest to become heretic | not used |
| `heresyImmunity` | enum ro | value over 1 makes it impossible for priest to become heretic | not used |
| `assassination` | enum ro | `int` | not used |
| `sabotage` | enum ro | `int` | not used |
| `eligibility` | enum ro | increases college of cardinals eligibility | not used |
| `purity` | enum ro | used for catholic mission scoring | not used |
| `violence` | enum ro | used for cease fire / break alliance mission scoring | not used |
| `disposition` | enum ro | useless | not used |
| `boldness` | enum ro | useless | not used |
| `generosity` | enum ro | useless | not used |
| `management` | enum ro | useless | not used |
| `bodyguardSize` | enum ro | `int` | not used |
| `troopMorale` | enum ro | `int` | not used |
| `movementPoints` | enum ro | 5% per point | not used |
| `attack` | enum ro | `int` | not used |
| `defence` | enum ro | `int` | not used |
| `siegeAttack` | enum ro | `int` | not used |
| `siegeDefence` | enum ro | `int` | not used |
| `ambush` | enum ro | `int` | not used |
| `navalCommand` | enum ro | `int` | not used |
| `siegeEngineering` | enum ro | `int` | not used |
| `nightBattle` | enum ro | `int` | not used |
| `personalSecurity` | enum ro | increases bodyguard size | not used |
| `publicSecurity` | enum ro | increases counterspy ability as governor | not used |
| `bribery` | enum ro | divided by campaign db briber attr divisor | not used |
| `briberyResistance` | enum ro | divided by campaign db bribee attr divisor | not used |
| `electability` | enum ro | useless | not used |
| `lineOfSight` | enum ro | `int` | not used |
| `trainingUnits` | enum ro | 5% cost per point | not used |
| `trainingAgents` | enum ro | 5% cost per point | not used |
| `construction` | enum ro | 5% cost per point | not used |
| `trading` | enum ro | 1% per point | not used |
| `localPopularity` | enum ro | `int` | not used |
| `footInTheDoor` | enum ro | useless | not used |
| `farming` | enum ro | `int` | not used |
| `mining` | enum ro | `int` | not used |
| `taxCollection` | enum ro | `int` | not used |
| `fertility` | enum ro | `int` | not used |
| `cavalryCommand` | enum ro | `int` | not used |
| `infantryCommand` | enum ro | `int` | not used |
| `gunpowderCommand` | enum ro | `int` | not used |
| `artilleryCommand` | enum ro | `int` | not used |
| `startReligionCombat` | enum ro | `int` | not used |
| `combatVReligion0` | enum ro | `int` | not used |
| `combatVReligion1` | enum ro | `int` | not used |
| `combatVReligion2` | enum ro | `int` | not used |
| `combatVReligion3` | enum ro | `int` | not used |
| `combatVReligion4` | enum ro | `int` | not used |
| `combatVReligion5` | enum ro | `int` | not used |
| `combatVReligion6` | enum ro | `int` | not used |
| `combatVReligion7` | enum ro | `int` | not used |
| `combatVReligion8` | enum ro | `int` | not used |
| `combatVReligion9` | enum ro | `int` | not used |
| `endReligionCombat` | enum ro | `int` | not used |
| `startFactionCombat` | enum ro | `int` | not used |
| `combatVFaction0` | enum ro | `int` | not used |
| `combatVFaction1` | enum ro | `int` | not used |
| `combatVFaction2` | enum ro | `int` | not used |
| `combatVFaction3` | enum ro | `int` | not used |
| `combatVFaction4` | enum ro | `int` | not used |
| `combatVFaction5` | enum ro | `int` | not used |
| `combatVFaction6` | enum ro | `int` | not used |
| `combatVFaction7` | enum ro | `int` | not used |
| `combatVFaction8` | enum ro | `int` | not used |
| `combatVFaction9` | enum ro | `int` | not used |
| `combatVFaction10` | enum ro | `int` | not used |
| `combatVFaction11` | enum ro | `int` | not used |
| `combatVFaction12` | enum ro | `int` | not used |
| `combatVFaction13` | enum ro | `int` | not used |
| `combatVFaction14` | enum ro | `int` | not used |
| `combatVFaction15` | enum ro | `int` | not used |
| `combatVFaction16` | enum ro | `int` | not used |
| `combatVFaction17` | enum ro | `int` | not used |
| `combatVFaction18` | enum ro | `int` | not used |
| `combatVFaction19` | enum ro | `int` | not used |
| `combatVFaction20` | enum ro | `int` | not used |
| `combatVFaction21` | enum ro | `int` | not used |
| `combatVFaction22` | enum ro | `int` | not used |
| `combatVFaction23` | enum ro | `int` | not used |
| `combatVFaction24` | enum ro | `int` | not used |
| `combatVFaction25` | enum ro | `int` | not used |
| `combatVFaction26` | enum ro | `int` | not used |
| `combatVFaction27` | enum ro | `int` | not used |
| `combatVFaction28` | enum ro | `int` | not used |
| `combatVFaction29` | enum ro | `int` | not used |
| `combatVFaction30` | enum ro | `int` | not used |
| `combatVFaction31` | enum ro | `int` | not used |
| `endFactionCombat` | enum ro | `int` | not used |
| `health` | enum ro | `int` | not used |
| `squalor` | enum ro | `int` | not used |
| `unrest` | enum ro | `int` | not used |
| `law` | enum ro | `int` | not used |
| `looting` | enum ro | `int` | not used |
| `bodyguardValour` | enum ro | `int` | not used |
| `hitPoints` | enum ro | `int` | not used |
| `trainingAnimalUnits` | enum ro | `int` | not used |
| `battleSurgery` | enum ro | `int` | not used |
| `attributeNum` | enum ro | `int` | not used |

### characterType (0/13 used)

| member | kind | what it is | status |
|---|---|---|---|
| `spy` | enum ro | `int` | not used |
| `assassin` | enum ro | `int` | not used |
| `diplomat` | enum ro | `int` | not used |
| `admiral` | enum ro | `int` | not used |
| `merchant` | enum ro | `int` | not used |
| `priest` | enum ro | `int` | not used |
| `general` | enum ro | `int` | not used |
| `named_character` | enum ro | `int` | not used |
| `princess` | enum ro | `int` | not used |
| `heretic` | enum ro | `int` | not used |
| `witch` | enum ro | `int` | not used |
| `inquisitor` | enum ro | `int` | not used |
| `pope` | enum ro | `int` | not used |

### combatStatus (0/8 used)

| member | kind | what it is | status |
|---|---|---|---|
| `notInCombat` *(battle)* | enum ro | `int` | not used |
| `victoryCertain` *(battle)* | enum ro | `int` | not used |
| `victoryAlmostCertain` *(battle)* | enum ro | `int` | not used |
| `victoryDistinct` *(battle)* | enum ro | `int` | not used |
| `balanced` *(battle)* | enum ro | `int` | not used |
| `defeatDistinct` *(battle)* | enum ro | `int` | not used |
| `defeatAlmostCertain` *(battle)* | enum ro | `int` | not used |
| `defeatCertain` *(battle)* | enum ro | `int` | not used |

### constructionType (0/6 used)

| member | kind | what it is | status |
|---|---|---|---|
| `upgrade` | enum ro | `int` | not used |
| `construction` | enum ro | `int` | not used |
| `repair` | enum ro | `int` | not used |
| `demolition` | enum ro | `int` | not used |
| `convert` | enum ro | `int` | not used |
| `none` | enum ro | `int` | not used |

### cursorState (0/4 used)

| member | kind | what it is | status |
|---|---|---|---|
| `onStratMap` *(ui)* | enum ro | `int` | not used |
| `onScroll` *(ui)* | enum ro | `int` | not used |
| `onElement` *(ui)* | enum ro | button(except zoom in missions),slider,checkbox,etc | not used |
| `onMinMap` *(ui)* | enum ro | `int` | not used |

### deathType (0/21 used)

| member | kind | what it is | status |
|---|---|---|---|
| `alive` | enum ro | `int` | not used |
| `diedNatural` | enum ro | `int` | not used |
| `diedInDisaster` | enum ro | `int` | not used |
| `diedInBattle` | enum ro | `int` | not used |
| `assassinated` | enum ro | `int` | not used |
| `executed` | enum ro | `int` | not used |
| `executedPrisoner` | enum ro | `int` | not used |
| `poisoned` | enum ro | `int` | not used |
| `plague` | enum ro | `int` | not used |
| `starvation` | enum ro | `int` | not used |
| `captainRemoval` | enum ro | `int` | not used |
| `removedForRetraining` | enum ro | `int` | not used |
| `incompatibleFaction` | enum ro | `int` | not used |
| `bribed` | enum ro | `int` | not used |
| `disbanded` | enum ro | `int` | not used |
| `sunk` | enum ro | `int` | not used |
| `married` | enum ro | `int` | not used |
| `acquired` | enum ro | `int` | not used |
| `retired` | enum ro | `int` | not used |
| `disgraced` | enum ro | `int` | not used |
| `denounced` | enum ro | `int` | not used |

### defendType (0/6 used)

| member | kind | what it is | status |
|---|---|---|---|
| `minimal` *(battle)* | enum ro | `int` | not used |
| `normal` *(battle)* | enum ro | `int` | not used |
| `raid` *(battle)* | enum ro | `int` | not used |
| `frontline` *(battle)* | enum ro | `int` | not used |
| `fortified` *(battle)* | enum ro | `int` | not used |
| `deep` *(battle)* | enum ro | `int` | not used |

### engineType (0/20 used)

| member | kind | what it is | status |
|---|---|---|---|
| `catapult` *(battle)* | enum ro | `int` | not used |
| `trebuchet` *(battle)* | enum ro | `int` | not used |
| `ballista` *(battle)* | enum ro | `int` | not used |
| `bombard` *(battle)* | enum ro | `int` | not used |
| `grandBombard` *(battle)* | enum ro | `int` | not used |
| `hugeBombard` *(battle)* | enum ro | `int` | not used |
| `culverin` *(battle)* | enum ro | `int` | not used |
| `basilisk` *(battle)* | enum ro | `int` | not used |
| `cannon` *(battle)* | enum ro | `int` | not used |
| `mortar` *(battle)* | enum ro | `int` | not used |
| `scorpion` *(battle)* | enum ro | `int` | not used |
| `serpentine` *(battle)* | enum ro | `int` | not used |
| `rocketLauncher` *(battle)* | enum ro | `int` | not used |
| `ribault` *(battle)* | enum ro | `int` | not used |
| `monsterRibault` *(battle)* | enum ro | `int` | not used |
| `mangonel` *(battle)* | enum ro | `int` | not used |
| `tower` *(battle)* | enum ro | `int` | not used |
| `ram` *(battle)* | enum ro | `int` | not used |
| `ladder` *(battle)* | enum ro | `int` | not used |
| `holy_cart` *(battle)* | enum ro | `int` | not used |

### formationType (0/10 used)

| member | kind | what it is | status |
|---|---|---|---|
| `horde` *(battle)* | enum ro | `int` | not used |
| `column` *(battle)* | enum ro | `int` | not used |
| `square` *(battle)* | enum ro | `int` | not used |
| `wedge` *(battle)* | enum ro | `int` | not used |
| `squareHollow` *(battle)* | enum ro | `int` | not used |
| `phalanx` *(battle)* | enum ro | `int` | not used |
| `schiltrom` *(battle)* | enum ro | `int` | not used |
| `shieldWall` *(battle)* | enum ro | `int` | not used |
| `wall` *(battle)* | enum ro | `int` | not used |
| `movingThrough` *(battle)* | enum ro | `int` | not used |

### invadeType (0/6 used)

| member | kind | what it is | status |
|---|---|---|---|
| `buildup` *(battle)* | enum ro | `int` | not used |
| `immediate` *(battle)* | enum ro | `int` | not used |
| `raids` *(battle)* | enum ro | `int` | not used |
| `opportunistic` *(battle)* | enum ro | `int` | not used |
| `start` *(battle)* | enum ro | `int` | not used |
| `none` *(battle)* | enum ro | `int` | not used |

### managePolicy (0/6 used)

| member | kind | what it is | status |
|---|---|---|---|
| `balanced` | enum ro | `int` | not used |
| `financial` | enum ro | `int` | not used |
| `military` | enum ro | `int` | not used |
| `growth` | enum ro | `int` | not used |
| `cultural` | enum ro | `int` | not used |
| `noPolicy` | enum ro | `int` | not used |

### moraleStatus (0/7 used)

| member | kind | what it is | status |
|---|---|---|---|
| `berserk` *(battle)* | enum ro | `int` | not used |
| `impetuous` *(battle)* | enum ro | `int` | not used |
| `high` *(battle)* | enum ro | `int` | not used |
| `firm` *(battle)* | enum ro | `int` | not used |
| `shaken` *(battle)* | enum ro | `int` | not used |
| `wavering` *(battle)* | enum ro | `int` | not used |
| `routing` *(battle)* | enum ro | `int` | not used |

### mountClass (0/4 used)

| member | kind | what it is | status |
|---|---|---|---|
| `horse` *(battle)* | enum ro | `int` | not used |
| `camel` *(battle)* | enum ro | `int` | not used |
| `elephant` *(battle)* | enum ro | `int` | not used |
| `infantry` *(battle)* | enum ro | `int` | not used |

### physicalGroundType (0/16 used)

| member | kind | what it is | status |
|---|---|---|---|
| `grassShort` *(battle)* | enum ro | `int` | not used |
| `grassLong` *(battle)* | enum ro | `int` | not used |
| `sand` *(battle)* | enum ro | `int` | not used |
| `rock` *(battle)* | enum ro | `int` | not used |
| `forestDense` *(battle)* | enum ro | `int` | not used |
| `scrubDense` *(battle)* | enum ro | `int` | not used |
| `swamp` *(battle)* | enum ro | `int` | not used |
| `mud` *(battle)* | enum ro | `int` | not used |
| `mudRoad` *(battle)* | enum ro | `int` | not used |
| `stoneRoad` *(battle)* | enum ro | `int` | not used |
| `water` *(battle)* | enum ro | `int` | not used |
| `ice` *(battle)* | enum ro | `int` | not used |
| `snow` *(battle)* | enum ro | `int` | not used |
| `wood` *(battle)* | enum ro | `int` | not used |
| `dirt` *(battle)* | enum ro | `int` | not used |
| `unknown` *(battle)* | enum ro | `int` | not used |

### productionBias (0/15 used)

| member | kind | what it is | status |
|---|---|---|---|
| `frontier` | enum ro | `int` | not used |
| `conflict` | enum ro | `int` | not used |
| `frontline` | enum ro | `int` | not used |
| `abandon` | enum ro | `int` | not used |
| `increaseGarrison` | enum ro | `int` | not used |
| `trade` | enum ro | `int` | not used |
| `tax` | enum ro | `int` | not used |
| `spies` | enum ro | `int` | not used |
| `assassins` | enum ro | `int` | not used |
| `merchants` | enum ro | `int` | not used |
| `priests` | enum ro | `int` | not used |
| `diplomats` | enum ro | `int` | not used |
| `ships` | enum ro | `int` | not used |
| `qualityUnits` | enum ro | `int` | not used |
| `buildStrengthLimit` | enum ro | `int` | not used |

### rainLevel (0/6 used)

| member | kind | what it is | status |
|---|---|---|---|
| `dry` *(battle)* | enum ro | `int` | not used |
| `drizzle` *(battle)* | enum ro | `int` | not used |
| `light` *(battle)* | enum ro | `int` | not used |
| `heavy` *(battle)* | enum ro | `int` | not used |
| `torrential` *(battle)* | enum ro | `int` | not used |
| `invalid` *(battle)* | enum ro | `int` | not used |

### rainType (0/6 used)

| member | kind | what it is | status |
|---|---|---|---|
| `none` *(battle)* | enum ro | `int` | not used |
| `rain` *(battle)* | enum ro | `int` | not used |
| `hail` *(battle)* | enum ro | `int` | not used |
| `snow` *(battle)* | enum ro | `int` | not used |
| `dust` *(battle)* | enum ro | `int` | not used |
| `invalid` *(battle)* | enum ro | `int` | not used |

### resourceType (0/28 used)

| member | kind | what it is | status |
|---|---|---|---|
| `gold` | enum ro | `int` | not used |
| `silver` | enum ro | `int` | not used |
| `fish` | enum ro | `int` | not used |
| `furs` | enum ro | `int` | not used |
| `grain` | enum ro | `int` | not used |
| `timber` | enum ro | `int` | not used |
| `iron` | enum ro | `int` | not used |
| `ivory` | enum ro | `int` | not used |
| `wine` | enum ro | `int` | not used |
| `slaves` | enum ro | `int` | not used |
| `chocolate` | enum ro | `int` | not used |
| `marble` | enum ro | `int` | not used |
| `textiles` | enum ro | `int` | not used |
| `dyes` | enum ro | `int` | not used |
| `tobacco` | enum ro | `int` | not used |
| `silk` | enum ro | `int` | not used |
| `sugar` | enum ro | `int` | not used |
| `sulfur` | enum ro | `int` | not used |
| `tin` | enum ro | `int` | not used |
| `spices` | enum ro | `int` | not used |
| `cotton` | enum ro | `int` | not used |
| `amber` | enum ro | `int` | not used |
| `coal` | enum ro | `int` | not used |
| `wool` | enum ro | `int` | not used |
| `elephants` | enum ro | `int` | not used |
| `camels` | enum ro | `int` | not used |
| `dogs` | enum ro | `int` | not used |
| `generic` | enum ro | `int` | not used |

### searchType (0/7 used)

| member | kind | what it is | status |
|---|---|---|---|
| `avoidZoc` *(ui)* | enum ro | `int` | not used |
| `ignoreZoc` *(ui)* | enum ro | `int` | not used |
| `direct` *(ui)* | enum ro | `int` | not used |
| `militaryAccess` *(ui)* | enum ro | `int` | not used |
| `landingPoints` *(ui)* | enum ro | `int` | not used |
| `region` *(ui)* | enum ro | `int` | not used |
| `strategic` *(ui)* | enum ro | `int` | not used |

### sortType (0/7 used)

| member | kind | what it is | status |
|---|---|---|---|
| `eduType` *(ui)* | enum ro | `int` | not used |
| `category` *(ui)* | enum ro | `int` | not used |
| `class` *(ui)* | enum ro | `int` | not used |
| `soldierCount` *(ui)* | enum ro | `int` | not used |
| `experience` *(ui)* | enum ro | `int` | not used |
| `categoryClass` *(ui)* | enum ro | `int` | not used |
| `aiUnitValue` *(ui)* | enum ro | `int` | not used |

### strategyGroundType (0/16 used)

| member | kind | what it is | status |
|---|---|---|---|
| `lowFertility` | enum ro | `int` | not used |
| `mediumFertility` | enum ro | `int` | not used |
| `highFertility` | enum ro | `int` | not used |
| `wilderness` | enum ro | `int` | not used |
| `highMountains` | enum ro | `int` | not used |
| `lowMountains` | enum ro | `int` | not used |
| `hills` | enum ro | `int` | not used |
| `denseForest` | enum ro | `int` | not used |
| `woodland` | enum ro | `int` | not used |
| `swamp` | enum ro | `int` | not used |
| `ocean` | enum ro | `int` | not used |
| `deepSea` | enum ro | `int` | not used |
| `shallowSea` | enum ro | `int` | not used |
| `coast` | enum ro | `int` | not used |
| `impassableLand` | enum ro | `int` | not used |
| `impassableSea` | enum ro | `int` | not used |

### tileVisibility (0/4 used)

| member | kind | what it is | status |
|---|---|---|---|
| `notVisibleInitial` | enum ro | `int` | not used |
| `notVisible` | enum ro | `int` | not used |
| `wasVisible` | enum ro | `int` | not used |
| `visible` | enum ro | `int` | not used |

### unitAction (0/20 used)

| member | kind | what it is | status |
|---|---|---|---|
| `changeFormation` *(battle)* | enum ro | `int` | not used |
| `changeFormationClose` *(battle)* | enum ro | `int` | not used |
| `changeFormationWidth` *(battle)* | enum ro | `int` | not used |
| `changeSpeed` *(battle)* | enum ro | `int` | not used |
| `changeMeleeState` *(battle)* | enum ro | `int` | not used |
| `setupEngine` *(battle)* | enum ro | `int` | not used |
| `collectEngine` *(battle)* | enum ro | `int` | not used |
| `dropEngine` *(battle)* | enum ro | `int` | not used |
| `hide` *(battle)* | enum ro | `int` | not used |
| `move` *(battle)* | enum ro | `int` | not used |
| `moveIntoPlayableArea` *(battle)* | enum ro | `int` | not used |
| `turn` *(battle)* | enum ro | `int` | not used |
| `attackUnit` *(battle)* | enum ro | `int` | not used |
| `attackBuilding` *(battle)* | enum ro | `int` | not used |
| `attackEngine` *(battle)* | enum ro | `int` | not used |
| `withdraw` *(battle)* | enum ro | `int` | not used |
| `feignRout` *(battle)* | enum ro | `int` | not used |
| `useAbility` *(battle)* | enum ro | `int` | not used |
| `halt` *(battle)* | enum ro | `int` | not used |
| `idle` *(battle)* | enum ro | `int` | not used |

### unitBattleProperties (0/3 used)

| member | kind | what it is | status |
|---|---|---|---|
| `guardMode` *(battle)* | enum ro | `int` | not used |
| `fireAtWill` *(battle)* | enum ro | `int` | not used |
| `skirmish` *(battle)* | enum ro | `int` | not used |

### unitCategory (0/6 used)

| member | kind | what it is | status |
|---|---|---|---|
| `infantry` | enum ro | `int` | not used |
| `cavalry` | enum ro | `int` | not used |
| `siege` | enum ro | `int` | not used |
| `non_combatant` | enum ro | `int` | not used |
| `ship` | enum ro | `int` | not used |
| `handler` | enum ro | `int` | not used |

### unitCategoryClass (0/11 used)

| member | kind | what it is | status |
|---|---|---|---|
| `nonCombatant` | enum ro | `int` | not used |
| `lightInfantry` | enum ro | `int` | not used |
| `heavyInfantry` | enum ro | `int` | not used |
| `spearmenInfantry` | enum ro | `int` | not used |
| `missileInfantry` | enum ro | `int` | not used |
| `lightCavalry` | enum ro | `int` | not used |
| `heavyCavalry` | enum ro | `int` | not used |
| `missileCavalry` | enum ro | `int` | not used |
| `siegeWeapon` | enum ro | `int` | not used |
| `animalHandler` | enum ro | `int` | not used |
| `battleShip` | enum ro | `int` | not used |

### unitClass (0/5 used)

| member | kind | what it is | status |
|---|---|---|---|
| `heavy` | enum ro | `int` | not used |
| `light` | enum ro | `int` | not used |
| `skirmish` | enum ro | `int` | not used |
| `spearmen` | enum ro | `int` | not used |
| `missile` | enum ro | `int` | not used |

### unitDiscipline (0/5 used)

| member | kind | what it is | status |
|---|---|---|---|
| `berserker` *(battle)* | enum ro | `int` | not used |
| `impetuous` *(battle)* | enum ro | `int` | not used |
| `low` *(battle)* | enum ro | `int` | not used |
| `normal` *(battle)* | enum ro | `int` | not used |
| `disciplined` *(battle)* | enum ro | `int` | not used |

### unitStatus (0/24 used)

| member | kind | what it is | status |
|---|---|---|---|
| `idle` | enum ro | `int` | not used |
| `hiding` | enum ro | `int` | not used |
| `taunting` | enum ro | `int` | not used |
| `celebrating` | enum ro | `int` | not used |
| `ready` | enum ro | `int` | not used |
| `reforming` | enum ro | `int` | not used |
| `moving` | enum ro | `int` | not used |
| `withdrawing` | enum ro | `int` | not used |
| `missilesFiring` | enum ro | `int` | not used |
| `missilesReloading` | enum ro | `int` | not used |
| `charging` | enum ro | `int` | not used |
| `fighting` | enum ro | `int` | not used |
| `pursuing` | enum ro | `int` | not used |
| `routing` | enum ro | `int` | not used |
| `fightingBacksToTheWalls` | enum ro | `int` | not used |
| `runningAmok` | enum ro | `int` | not used |
| `berserk` | enum ro | `int` | not used |
| `rallying` | enum ro | `int` | not used |
| `dead` | enum ro | `int` | not used |
| `leavingBattle` | enum ro | `int` | not used |
| `enteringBattle` | enum ro | `int` | not used |
| `leftBattle` | enum ro | `int` | not used |
| `bracing` | enum ro | `int` | not used |
| `infighting` | enum ro | `int` | not used |

### unitTraining (0/3 used)

| member | kind | what it is | status |
|---|---|---|---|
| `untrained` *(battle)* | enum ro | `int` | not used |
| `trained` *(battle)* | enum ro | `int` | not used |
| `highly_trained` *(battle)* | enum ro | `int` | not used |

### weaponTechType (0/7 used)

| member | kind | what it is | status |
|---|---|---|---|
| `melee_simple` *(battle)* | enum ro | `int` | not used |
| `melee_blade` *(battle)* | enum ro | `int` | not used |
| `missile_mechanical` *(battle)* | enum ro | `int` | not used |
| `missile_gunpowder` *(battle)* | enum ro | `int` | not used |
| `artillery_mechanical` *(battle)* | enum ro | `int` | not used |
| `artillery_gunpowder` *(battle)* | enum ro | `int` | not used |
| `naval_gunpowder` *(battle)* | enum ro | `int` | not used |

### weaponType (0/5 used)

| member | kind | what it is | status |
|---|---|---|---|
| `melee` *(battle)* | enum ro | `int` | not used |
| `siegeMelee` *(battle)* | enum ro | `int` | not used |
| `thrown` *(battle)* | enum ro | `int` | not used |
| `missile` *(battle)* | enum ro | `int` | not used |
| `siegeMissile` *(battle)* | enum ro | `int` | not used |

## Battle

296 members, 2 used (+28 by name only).

<details><summary>Show members</summary>

### battleSide (3/23 used)

| member | kind | what it is | status |
|---|---|---|---|
| `isDefender` *(battle)* | field rw | `bool` | not used |
| `canDeploy` *(battle)* | field rw | `bool` | not used |
| `canWithdraw` *(battle)* | field rw | `bool` | not used |
| `isCanDeploy` *(battle)* | field rw |  | not used |
| `wonBattle` *(battle)* | field rw | 0 = lose, 1 = draw, 2 = win | not used |
| `battleSuccess` *(battle)* | field rw | 0 = close, 1 = average, 2 = clear, 3 = crushing | not used |
| `battleArmyNum` *(battle)* | field rw | `int` | not used |
| `reinforceArmyCount` *(battle)* | field rw | `int` | not used |
| `alliance` *(battle)* | field rw | `int` | USED report + order ? |
| `soldierCountStart` *(battle)* | field rw | `int` | not used |
| `totalStrength` *(battle)* | field rw | `int` | not used |
| `activeArmyStrength` *(battle)* | field rw | `int` | not used |
| `battleOdds` *(battle)* | field rw | `float` | not used |
| `factionCount` *(battle)* | field rw | `int` | not used |
| `battleAIPlan` *(battle)* | field rw | `battleAI` | not used |
| `winConditions` *(battle)* | property ro | Returns an int index of a wincondition. Maximum 4. | not used |
| `getWinConditionString` *(battle)* | function | Get win condition string, for example: destroy\_or\_rout_enemy | not used |
| `armiesNum` *(battle)* | field rw | `int` | not used |
| `armies` *(battle)* | property ro | Returns a table of battleSideArmy. Maximum: 64. | USED report + order + event + other |
| `getBattleArmy` *(battle)* | function | Get a battle army by it's index. | not used |
| `getFaction` *(battle)* | function | Get a faction in this side by it's index. | USED event ? |
| `getReinforcementArmy` *(battle)* | function | Get a reinforcement army in this side by it's index. | not used |
| `hasFaction` *(battle)* | function | Check if a side contains a faction. | not used |

### buildingBattle (3/19 used)

| member | kind | what it is | status |
|---|---|---|---|
| `type` *(battle)* | field rw | `int` | USED report + order + event + other ? |
| `factionId` *(battle)* | field rw | `int` | not used |
| `posX` *(battle)* | field rw | `float` | not used |
| `posZ` *(battle)* | field rw | `float` | not used |
| `posY` *(battle)* | field rw | `float` | not used |
| `breached` *(battle)* | field rw | `bool` | not used |
| `dockable` *(battle)* | field rw | `bool` | not used |
| `perimeter` *(battle)* | field rw | `int` | not used |
| `controllingUnit` *(battle)* | field rw | `unit` | not used |
| `faction` *(battle)* | field rw | `factionStruct` | USED report + order + event + other ? |
| `currentHealth` *(battle)* | field rw | `int` | not used |
| `startHealth` *(battle)* | field rw | `int` | not used |
| `battleResidence` *(battle)* | field rw | `battleResidence` | not used |
| `alliance` *(battle)* | field rw | `int` | USED report + order ? |
| `index` *(battle)* | field rw | `int` | not used |
| `isBurning` *(battle)* | field rw | `bool` | not used |
| `fireDamage` *(battle)* | field rw | `float` | not used |
| `fireLevel` *(battle)* | field rw | `float` | not used |
| `battleBuildingStats` *(battle)* | field rw | `battleBuildingStats` | not used |

### plazaData (3/11 used)

| member | kind | what it is | status |
|---|---|---|---|
| `xCoord` *(battle)* | field rw | `float` | USED report + order + other ? |
| `yCoord` *(battle)* | field rw | `float` | USED report + order + other ? |
| `capturing` *(battle)* | field rw | `bool` | not used |
| `isCaptured` *(battle)* | field rw | `bool` | not used |
| `sizeX` *(battle)* | field rw | `float` | not used |
| `sizeY` *(battle)* | field rw | `float` | not used |
| `alliance` *(battle)* | field rw | `int` | USED report + order ? |
| `plazaMaxTime` *(battle)* | field rw | `float` | not used |
| `plazaControlPerSecond` *(battle)* | field rw | `float` | not used |
| `plazaControl` *(battle)* | field rw | `float` | not used |
| `getSoldierCount` *(battle)* | function | Get amount of soldiers on plazaz for an alliance. | not used |

### battleBuildingStats (2/10 used)

| member | kind | what it is | status |
|---|---|---|---|
| `name` *(battle)* | field rw | `string` | USED report + order + event + other ? |
| `flammability` *(battle)* | field rw | `int` | not used |
| `impactDamage` *(battle)* | field rw | `int` | not used |
| `health` *(battle)* | field rw | (descr_walls, not currently battle) | USED report + other ? |
| `controlAreaRadius` *(battle)* | field rw | `float` | not used |
| `manned` *(battle)* | field rw | `int` | not used |
| `healthExcluded` *(battle)* | field rw | `int` | not used |
| `isSelectable` *(battle)* | field rw | `int` | not used |
| `towerStatsCount` *(battle)* | property ro | `int` | not used |
| `getTowerStats` *(battle)* | function | Get tower stats by index. | not used |

### battleCameraStruct (2/3 used)

| member | kind | what it is | status |
|---|---|---|---|
| `xCoord` *(battle)* | field rw | `float` | USED report + order + other ? |
| `yCoord` *(battle)* | field rw | `float` | USED report + order + other ? |
| `zCoord` *(battle)* | field rw | `float` | not used |

### battlePos (2/2 used)

| member | kind | what it is | status |
|---|---|---|---|
| `xCoord` *(battle)* | field rw | `float` | USED report + order + other ? |
| `yCoord` *(battle)* | field rw | `float` | USED report + order + other ? |

### battleResidence (2/10 used)

| member | kind | what it is | status |
|---|---|---|---|
| `settlement` *(battle)* | field rw | `settlementStruct` | USED report + order + event + other ? |
| `faction` *(battle)* | field rw | `factionStruct` | USED report + order + event + other ? |
| `settlementWallsBreached` *(battle)* | field rw | `int` | not used |
| `settlementGateDestroyed` *(battle)* | field rw | `int` | not used |
| `battleBuildings` *(battle)* | field rw | `battleBuildings` | not used |
| `fortInfo` *(battle)* | field rw | `fortBattleInfo` | not used |
| `plazaData` *(battle)* | field rw | `plazaData` | not used |
| `isUsed` *(battle)* | field rw | `bool` | not used |
| `streetPositionCount` *(battle)* | property ro | `int` | not used |
| `getStreetPosition` *(battle)* | function | Get a street position in a settlement. | not used |

### battleStruct (2/48 used)

| member | kind | what it is | status |
|---|---|---|---|
| `battleState` *(battle)* | field rw | `int` | not used |
| `battleType` *(battle)* | field rw | `int` | not used |
| `isNightBattle` *(battle)* | field rw | `bool` | not used |
| `attackingSide` *(battle)* | field rw | `int` | not used |
| `isAutoResolve` *(battle)* | field rw | `bool` | not used |
| `defendingSide` *(battle)* | field rw | `int` | not used |
| `timeWinningAlliance` *(battle)* | field rw | `int` | not used |
| `residenceOwnerFacId` *(battle)* | field rw | `int` | not used |
| `defenderWithdrawn` *(battle)* | field rw | `bool` | not used |
| `battleAiEnabled` *(battle)* | field rw | `bool` | not used |
| `isFortBattle` *(battle)* | field rw | `bool` | not used |
| `xCoord` *(battle)* | field rw | `int` | USED report + order + other ? |
| `finishTimer` *(battle)* | field rw | `int` | not used |
| `fortInfo` *(battle)* | field rw | `fortBattleInfo` | not used |
| `yCoord` *(battle)* | field rw | `int` | USED report + order + other ? |
| `playerArmyNum` *(battle)* | field rw | `int` | not used |
| `attackerXCoord` *(battle)* | field rw | `int` | not used |
| `attackerYCoord` *(battle)* | field rw | `int` | not used |
| `defenderXCoord` *(battle)* | field rw | `int` | not used |
| `defenderYCoord` *(battle)* | field rw | `int` | not used |
| `paused` *(battle)* | field rw | `bool` | not used |
| `unitSize` *(battle)* | field rw | `int` | not used |
| `tideOfBattle` *(battle)* | field rw | `int` | not used |
| `inBattle` *(battle)* | field rw | `bool` | not used |
| `battleSpeed` *(battle)* | field rw | `float` | not used |
| `secondsPassed` *(battle)* | field rw | `float` | not used |
| `tickCount` *(battle)* | field rw | `int` | not used |
| `ticksSinceBattleStart` *(battle)* | field rw | `int` | not used |
| `hidingEnabledSet` *(battle)* | field rw | `int` | not used |
| `mapWidthDoubled` *(battle)* | field rw |  | not used |
| `mapHeightDoubled` *(battle)* | field rw |  | not used |
| `mapWidth` *(battle)* | field rw | `float` | not used |
| `mapHeight` *(battle)* | field rw | `float` | not used |
| `sidesNum` *(battle)* | field rw | `int` | not used |
| `terrainFeatures` *(battle)* | field rw | `terrainFeatures` | not used |
| `sides` *(battle)* | property ro | Returns a battleSide[8]. Maximum: 8. | not used |
| `factionSide` *(battle)* | property ro | faction alliance array, -1 if not in battle, start at 1 so faction ID + 1 Maximum 31. | not used |
| `getPlayerArmy` *(battle)* | function | Get a players army. | not used |
| `getBattleResidence` *(battle)* | function | Get table with certain info about the battle residence. | not used |
| `getUnitByLabel` *(battle)* | function | Get a unit by it's label. | not used |
| `getGroupByLabel` *(battle)* | function | Get a group by it's label. | not used |
| `getBattleMapHeight` *(battle)* | function | Get battlemap height at position. | not used |
| `getBattlefieldEngines` *(battle)* | function | Get battlefield engines. | not used |
| `getBattleTile` *(battle)* | function | Get battlefield tile. | not used |
| `getZoneID` *(battle)* | function | Get zone ID. | not used |
| `getPosPerimeter` *(battle)* | function | Get position perimeter. | not used |
| `isZoneValid` *(battle)* | function | Is zone valid. | not used |
| `isRiverBattle` *(battle)* | function | Is battle a river battle. | not used |

### fortBattleInfo (2/6 used)

| member | kind | what it is | status |
|---|---|---|---|
| `fort` *(battle)* | field rw | `fortStruct` | not used |
| `garrison` *(battle)* | field rw | `armyStruct` | USED report (settlements.(tax,order,queue,can_*)) + other |
| `faction` *(battle)* | field rw | `factionStruct` | USED report + order + event + other ? |
| `ownerFactionID` *(battle)* | field rw | `int` | not used |
| `creatorFactionID` *(battle)* | field rw | `int` | not used |
| `fortFortificationLevel` *(battle)* | field rw | `int` | not used |

### streetPosition (2/4 used)

| member | kind | what it is | status |
|---|---|---|---|
| `xCoord` *(battle)* | field rw | `float` | USED report + order + other ? |
| `yCoord` *(battle)* | field rw | `float` | USED report + order + other ? |
| `perimeter` *(battle)* | field rw | `int` | not used |
| `available` *(battle)* | field rw | `bool` | not used |

### terrainFeatureHill (2/6 used)

| member | kind | what it is | status |
|---|---|---|---|
| `xCoord` *(battle)* | field rw | `float` | USED report + order + other ? |
| `zCoord` *(battle)* | field rw | `float` | not used |
| `yCoord` *(battle)* | field rw | `float` | USED report + order + other ? |
| `radius` *(battle)* | field rw | `float` | not used |
| `terrainLinesStart` *(battle)* | field rw | `terrainLine` | not used |
| `area` *(battle)* | field rw | `float` | not used |

### battleArmy (1/9 used)

| member | kind | what it is | status |
|---|---|---|---|
| `army` *(battle)* | field rw | `armyStruct` | USED order + event ? |
| `character` *(battle)* | field rw | `character` | not used |
| `generalNumKillsBattle` *(battle)* | field rw | `int` | not used |
| `generalHPRatioLost` *(battle)* | field rw | `float` | not used |
| `numKilledGenerals` *(battle)* | field rw | (manual battle only) | not used |
| `initialStrength` *(battle)* | field rw | `float` | not used |
| `battleOdds` *(battle)* | field rw | `float` | not used |
| `unitCount` *(battle)* | field rw | `int` | not used |
| `getBattleUnit` *(battle)* | function | Get a battle unit by it's index. | not used |

### battleSideArmy (1/6 used)

| member | kind | what it is | status |
|---|---|---|---|
| `army` *(battle)* | field rw | `armyStruct` | USED order + event ? |
| `canWithdraw` *(battle)* | field rw | `bool` | not used |
| `isReinforcement` *(battle)* | field rw | `bool` | not used |
| `deployAreaCount` *(battle)* | property ro | `int` | not used |
| `deploymentArea` *(battle)* | property ro |  | not used |
| `getDeployArea` *(battle)* | function | Get a deployment area. | not used |

### battleUnit (1/19 used)

| member | kind | what it is | status |
|---|---|---|---|
| `unit` *(battle)* | field rw | `unit` | USED report + order + other ? |
| `valuePerSoldier` *(battle)* | field rw | `float` | not used |
| `soldiersLost` *(battle)* | field rw | `int` | not used |
| `soldiersStart` *(battle)* | field rw | `int` | not used |
| `unitsRouted` *(battle)* | field rw |  | not used |
| `soldiersRouted` *(battle)* | field rw | `int` | not used |
| `soldiersKilled` *(battle)* | field rw | `int` | not used |
| `takenPrisoner` *(battle)* | field rw | `int` | not used |
| `prisonersCaught` *(battle)* | field rw | `int` | not used |
| `soldiersHealed` *(battle)* | field rw | `int` | not used |
| `soldiersRallied` *(battle)* | field rw | `int` | not used |
| `soldiersEnd` *(battle)* | field rw | `int` | not used |
| `friendlyFireCasualties` *(battle)* | field rw | `int` | not used |
| `expStart` *(battle)* | field rw | `int` | not used |
| `expGained` *(battle)* | field rw | `int` | not used |
| `isGeneral` *(battle)* | field rw | `int` | not used |
| `hasWithdrawn` *(battle)* | field rw | `int` | not used |
| `shipsSunk` *(battle)* | field rw | `int` | not used |
| `shipDamage` *(battle)* | field rw | `int` | not used |

### generalBattleStruct (1/5 used)

| member | kind | what it is | status |
|---|---|---|---|
| `unit` *(battle)* | field rw | `unit` | USED report + order + other ? |
| `record` *(battle)* | field rw | `characterRecord` | not used |
| `stats` *(battle)* | field rw | `unitStats` | not used |
| `isGeneral` *(battle)* | field rw | `bool` | not used |
| `isAlive` *(battle)* | field rw | `bool` | not used |

### projectileStruct (1/9 used)

| member | kind | what it is | status |
|---|---|---|---|
| `name` *(battle)* | field rw | `string` | USED report + order + event + other ? |
| `accuracy` *(battle)* | field rw | `float` | not used |
| `accuracyVsBuildings` *(battle)* | field rw | `float` | not used |
| `accuracyVsTowers` *(battle)* | field rw | `float` | not used |
| `damage` *(battle)* | field rw | `int` | not used |
| `damageToTroops` *(battle)* | field rw | `int` | not used |
| `affectedByRain` *(battle)* | field rw | `int` | not used |
| `isBodyPiercing` *(battle)* | field rw | `int` | not used |
| `fiery` *(battle)* | field rw | `int` | not used |

### battleAI (0/31 used)

| member | kind | what it is | status |
|---|---|---|---|
| `gtaPlan` *(battle)* | property rw | `int` | not used |
| `previousAiPlan` *(battle)* | field rw | `int` | not used |
| `aiAnalyzerPlan` *(battle)* | field rw | `int` | not used |
| `unitCount` *(battle)* | field rw | `int` | not used |
| `isDefender` *(battle)* | field rw | `bool` | not used |
| `isAmbush` *(battle)* | field rw | `bool` | not used |
| `isDeploying` *(battle)* | field rw | `bool` | not used |
| `hasDeployed` *(battle)* | field rw | `bool` | not used |
| `scriptPlan` *(battle)* | field rw | `bool` | not used |
| `wantsToSally` *(battle)* | field rw | `bool` | not used |
| `battleDifficulty` *(battle)* | field rw | `int` | not used |
| `battleSide` *(battle)* | field rw | `battleSide` | not used |
| `defendAreaSet` *(battle)* | field rw | `bool` | not used |
| `objectiveTimer` *(battle)* | field rw | `int` | not used |
| `defendAreaX` *(battle)* | field rw | `float` | not used |
| `defendAreaZ` *(battle)* | field rw | `float` | not used |
| `defendAreaY` *(battle)* | field rw | `float` | not used |
| `defendRadius` *(battle)* | field rw | `float` | not used |
| `defendHill` *(battle)* | field rw | `terrainFeatureHill` | not used |
| `visibleEnemyUnitCount` *(battle)* | field rw | `int` | not used |
| `alliedInitialStrength` *(battle)* | field rw | `battleStrengthStruct` | not used |
| `alliedStrength` *(battle)* | field rw | `battleStrengthStruct` | not used |
| `enemyInitialStrength` *(battle)* | field rw | `battleStrengthStruct` | not used |
| `enemyStrength` *(battle)* | field rw | `battleStrengthStruct` | not used |
| `enemyVisibleInitialStrength` *(battle)* | field rw | `battleStrengthStruct` | not used |
| `enemyVisibleStrength` *(battle)* | field rw | `battleStrengthStruct` | not used |
| `addedObjectivesCount` *(battle)* | field rw | `int` | not used |
| `objectiveCount` *(battle)* | property ro | `int` | not used |
| `getObjective` *(battle)* | function | Get a battle objective by it's index. | not used |
| `getVisibleEnemy` *(battle)* | function | Get a visible enemy unit by index. | not used |
| `getUnit` *(battle)* | function | Get a unit by index. | not used |

### battleBuildings (0/4 used)

| member | kind | what it is | status |
|---|---|---|---|
| `buildingCount` *(battle)* | field rw | `int` | not used |
| `perimeterCount` *(battle)* | field rw | `int` | not used |
| `getBuilding` *(battle)* | function | Get a battle building by it's index. | not used |
| `getPerimeter` *(battle)* | function | Get a perimeter by it's index. | not used |

### battleObjective (0/8 used)

| member | kind | what it is | status |
|---|---|---|---|
| `priority` *(battle)* | field rw | `int` | not used |
| `battleAi` *(battle)* | field rw | `battleAI` | not used |
| `ticks` *(battle)* | field rw | `int` | not used |
| `isRequired` *(battle)* | field rw | `bool` | not used |
| `isPlayer` *(battle)* | field rw | `bool` | not used |
| `unitCount` *(battle)* | field rw | `int` | not used |
| `getUnit` *(battle)* | function | Get a unit by it's index. | not used |
| `getType` *(battle)* | function | Get the type of objective. | not used |

### battleStrengthStruct (0/7 used)

| member | kind | what it is | status |
|---|---|---|---|
| `soldierCount` *(battle)* | field rw | `int` | not used |
| `meleeStrength` *(battle)* | field rw | `int` | not used |
| `missileStrength` *(battle)* | field rw | `int` | not used |
| `siegeStrength` *(battle)* | field rw | `int` | not used |
| `infantryMissilePlusMelee` *(battle)* | field rw | `int` | not used |
| `cavalryMeleeStrength` *(battle)* | field rw | `int` | not used |
| `total` *(battle)* | field rw | `int` | not used |

### battleTile (0/3 used)

| member | kind | what it is | status |
|---|---|---|---|
| `physicalGroundType` *(battle)* | property ro | `int` | not used |
| `height` *(battle)* | property ro | `float` | not used |
| `waterHeight` *(battle)* | property ro | `float` | not used |

### battlefieldEngines (0/2 used)

| member | kind | what it is | status |
|---|---|---|---|
| `engineNum` *(battle)* | field rw | `int` | not used |
| `getEngine` *(battle)* | function | Get an engine from the battlefield. | not used |

### defenseStats (0/5 used)

| member | kind | what it is | status |
|---|---|---|---|
| `isValid` *(battle)* | property rw | `bool` | not used |
| `armour` *(battle)* | property rw | `int` | not used |
| `defense` *(battle)* | property rw | `int` | not used |
| `shield` *(battle)* | property rw | `int` | not used |
| `armourMaterial` *(battle)* | field rw | `int` | not used |

### deploymentAreaS (0/6 used)

| member | kind | what it is | status |
|---|---|---|---|
| `coordsNum` *(battle)* | field rw | `int` | not used |
| `width` *(battle)* | field rw | `int` | not used |
| `height` *(battle)* | field rw | `int` | not used |
| `centreX` *(battle)* | field rw | `float` | not used |
| `centreY` *(battle)* | field rw | `float` | not used |
| `getCoordPair` *(battle)* | function | Get pair of coords with index. | not used |

### lineData (0/7 used)

| member | kind | what it is | status |
|---|---|---|---|
| `xCoordStart` *(battle)* | field rw | `float` | not used |
| `yCoordStart` *(battle)* | field rw | `float` | not used |
| `xCoordEnd` *(battle)* | field rw | `float` | not used |
| `yCoordEnd` *(battle)* | field rw | `float` | not used |
| `xMidPoint` *(battle)* | field rw | `float` | not used |
| `yMidPoint` *(battle)* | field rw | `float` | not used |
| `length` *(battle)* | field rw | `float` | not used |

### perimeterBuildings (0/2 used)

| member | kind | what it is | status |
|---|---|---|---|
| `buildingCount` *(battle)* | field rw | `int` | not used |
| `getBuilding` *(battle)* | function | Get a battle building in a perimiter by it's index. | not used |

### phalanxOptions (0/5 used)

| member | kind | what it is | status |
|---|---|---|---|
| `braceRanks` *(battle)* | field rw | How many ranks will brace. Default: 3 | not used |
| `maxSoldiersSecondary` *(battle)* | field rw | How many soldiers a pikeman can engage at once before drawing secondary. Default: 2 | not used |
| `readyDist` *(battle)* | field rw | Distance in meters to be considered ready for enemy. Default: 60 | not used |
| `drawDebugInfo` *(battle)* | field rw | Draw sphere's where the spear points are on the battlemap. Default: false | not used |
| `enableEnhancedTargeting` *(battle)* | field rw | Pikeman soldiers attack more. Default: true | not used |

### terrainFeatures (0/10 used)

| member | kind | what it is | status |
|---|---|---|---|
| `width` *(battle)* | field rw | `float` | not used |
| `widthHalf` *(battle)* | field rw | `float` | not used |
| `length` *(battle)* | field rw | `float` | not used |
| `lengthHalf` *(battle)* | field rw | `float` | not used |
| `widthOnePercent` *(battle)* | field rw | `float` | not used |
| `lengthOnePercent` *(battle)* | field rw | `float` | not used |
| `terrainLineCount` *(battle)* | property ro | `int` | not used |
| `hillCount` *(battle)* | property ro | `int` | not used |
| `getLine` *(battle)* | function | Get a terrain line by index. | not used |
| `getHill` *(battle)* | function | Get a terrain hill by index. | not used |

### terrainLine (0/8 used)

| member | kind | what it is | status |
|---|---|---|---|
| `startX` *(battle)* | field rw | `float` | not used |
| `startZ` *(battle)* | field rw | `float` | not used |
| `startY` *(battle)* | field rw | `float` | not used |
| `endX` *(battle)* | field rw | `float` | not used |
| `endZ` *(battle)* | field rw | `float` | not used |
| `endY` *(battle)* | field rw | `float` | not used |
| `previousSegment` *(battle)* | field rw | `terrainLine` | not used |
| `nextSegment` *(battle)* | field rw | `terrainLine` | not used |

### towerStats (0/8 used)

| member | kind | what it is | status |
|---|---|---|---|
| `stats` *(battle)* | field rw | `attackStats` | not used |
| `fireAngle` *(battle)* | field rw | `float` | not used |
| `slotYawX` *(battle)* | field rw | `float` | not used |
| `slotYawY` *(battle)* | field rw | `float` | not used |
| `slotPitchX` *(battle)* | field rw | `float` | not used |
| `slotPitchY` *(battle)* | field rw | `float` | not used |
| `fireRate` *(battle)* | property rw | (don't set) | not used |
| `fireRateFlaming` *(battle)* | property rw | (don't set) | not used |

</details>

## UI

164 members, 10 used (+5 by name only).

<details><summary>Show members</summary>

### uiElementStruct (8/8 used)

| member | kind | what it is | status |
|---|---|---|---|
| `elementName` *(ui)* | property ro | `string` | USED report + order + event |
| `xSize` *(ui)* | field rw | `int` | USED report + order + event |
| `ySize` *(ui)* | field rw | `int` | USED report + order + event |
| `xPos` *(ui)* | field rw | `int` | USED report + order + event |
| `yPos` *(ui)* | field rw | `int` | USED report + order + event |
| `subElementsNum` *(ui)* | field rw | `int` | USED report + order + event |
| `getSubElement` *(ui)* | function | Get a subelement of an UI element using the index. | USED report + order + event |
| `execute` *(ui)* | function | execute standard game UI element, use only for buttons | USED event |

### buildingInfoScroll (3/4 used)

| member | kind | what it is | status |
|---|---|---|---|
| `settlement` *(ui)* | field rw | `settlementStruct` | USED report + order + event + other ? |
| `building` *(ui)* | field rw | `building` | USED order ? |
| `edbEntry` *(ui)* | property ro | `edbEntry` | not used |
| `level` *(ui)* | property ro | `buildingLevel` | USED order ? |

### gameSTDUI (1/1 used)

| member | kind | what it is | status |
|---|---|---|---|
| `getUiElement` *(ui)* | function | Get a game UI element, element must be opened. | USED report + order + event + other |

### options2 (1/67 used)

| member | kind | what it is | status |
|---|---|---|---|
| `campaignResolutionX` *(ui)* | field rw | `int` | not used |
| `campaignResolutionY` *(ui)* | field rw | `int` | not used |
| `battleResolutionX` *(ui)* | field rw | `int` | not used |
| `battleResolutionY` *(ui)* | field rw | `int` | not used |
| `vSync` *(ui)* | field rw | `int` | not used |
| `uiIconBarCheck` *(ui)* | field rw | `int` | not used |
| `uiRadarCheck` *(ui)* | field rw | `int` | not used |
| `useMorale` *(ui)* | field rw | `int` | not used |
| `uiAmmoCheck` *(ui)* | field rw | `int` | not used |
| `useFatigue` *(ui)* | field rw | `int` | not used |
| `uiSupplyCheck` *(ui)* | field rw | `int` | not used |
| `toggleFowState` *(ui)* | field rw | this does not toggle fow just remembers if it was on or off | not used |
| `cameraRestrict` *(ui)* | field rw | `int` | not used |
| `eventCutscenes` *(ui)* | field rw | `int` | not used |
| `defaultCameraInBattle` *(ui)* | field rw | `int` | not used |
| `splashes` *(ui)* | field rw | `int` | not used |
| `stencilShadows` *(ui)* | field rw | `int` | not used |
| `audioEnable` *(ui)* | field rw | `int` | not used |
| `speechEnable` *(ui)* | field rw | `int` | not used |
| `firstTimePlay` *(ui)* | field rw | `int` | not used |
| `toggleAutoSave` *(ui)* | field rw | `int` | not used |
| `showBanners` *(ui)* | field rw | `int` | not used |
| `passwords` *(ui)* | field rw | `int` | not used |
| `hotseatTurns` *(ui)* | field rw | `int` | not used |
| `hotseatScroll` *(ui)* | field rw | `int` | not used |
| `allowValidationFeatures` *(ui)* | field rw | `int` | not used |
| `campaignSpeed` *(ui)* | field rw | `int` | not used |
| `labelSettlements` *(ui)* | field rw | `int` | not used |
| `disablePapalElections` *(ui)* | field rw | `int` | not used |
| `autoresolveAllBattles` *(ui)* | field rw | `int` | USED other |
| `savePrefs` *(ui)* | field rw | `int` | not used |
| `disableConsole` *(ui)* | field rw | `int` | not used |
| `validateDiplomacy` *(ui)* | field rw | `int` | not used |
| `unitDetail` *(ui)* | field rw | `int` | not used |
| `buildingDetail` *(ui)* | field rw | `int` | not used |
| `maxSoldiersOnBattlefield` *(ui)* | field rw | if limited | not used |
| `unitSize` *(ui)* | field rw | `int` | not used |
| `cameraRotateSpeed` *(ui)* | field rw | `int` | not used |
| `cameraMoveSpeed` *(ui)* | field rw | `int` | not used |
| `cameraSmoothing` *(ui)* | field rw | `float` | not used |
| `masterVolume` *(ui)* | field rw | `int` | not used |
| `musicVolume` *(ui)* | field rw | `int` | not used |
| `speechVolume` *(ui)* | field rw | `int` | not used |
| `sfxVolume` *(ui)* | field rw | `int` | not used |
| `subFactionAccents` *(ui)* | field rw | `int` | not used |
| `playerFactionID` *(ui)* | field rw | `int` | not used |
| `campaignDifficulty` *(ui)* | field rw | `int` | not used |
| `battleDifficulty` *(ui)* | field rw | `int` | not used |
| `tgaWidth` *(ui)* | field rw | `int` | not used |
| `tgaAspect` *(ui)* | field rw | `float` | not used |
| `tgaInputScale` *(ui)* | field rw | `int` | not used |
| `scrollMinZoom` *(ui)* | field rw | `int` | not used |
| `scrollMaxZoom` *(ui)* | field rw | `int` | not used |
| `advisorVerbosity` *(ui)* | field rw | `int` | not used |
| `effectQuality` *(ui)* | field rw | `int` | not used |
| `EnableCameraCampaignSmoothing` *(ui)* | field rw | `int` | not used |
| `chatMsgDuration` *(ui)* | field rw | `int` | not used |
| `saveGameSpyPassword` *(ui)* | field rw | `int` | not used |
| `addDateToLogs` *(ui)* | field rw | `int` | not used |
| `showToolTips` *(ui)* | field rw | `int` | not used |
| `isNormalHud` *(ui)* | field rw | `int` | not used |
| `showPackageLitter` *(ui)* | field rw | `int` | not used |
| `unitSizeMultiplierLow` *(ui)* | field rw | `float` | not used |
| `unitSizeMultiplierMedium` *(ui)* | field rw | `float` | not used |
| `unitSizeMultiplierLarge` *(ui)* | field rw | `float` | not used |
| `isHotseatPlayer` *(ui)* | function | Check if a faction was selected on faction select screen. | not used |
| `setHotseatPlayer` *(ui)* | function | Select a faction on faction select screen. | not used |

### settlementInfoScroll (1/2 used)

| member | kind | what it is | status |
|---|---|---|---|
| `settlement` *(ui)* | field rw | `settlementStruct` | USED report + order + event + other ? |
| `getUIStrings` *(ui)* | function | Get settlement text color info. | not used |

### unitInfoScroll (1/4 used)

| member | kind | what it is | status |
|---|---|---|---|
| `unit` *(ui)* | field rw | If the scroll is about existing unit | USED report + order + other ? |
| `eduEntry` *(ui)* | property ro | `eduEntry` | not used |
| `recruitmentItem` *(ui)* | field rw | `unitInQueue` | not used |
| `mercenary` *(ui)* | field rw | `mercPoolUnit` | not used |

### options1 (0/45 used)

| member | kind | what it is | status |
|---|---|---|---|
| `widescreen` *(ui)* | field rw | `int` | not used |
| `antiAliasMode` *(ui)* | field rw | `int` | not used |
| `subtitles` *(ui)* | field rw | `int` | not used |
| `english` *(ui)* | field rw | `int` | not used |
| `noBattleTimeLimit` *(ui)* | field rw | `int` | not used |
| `useNewCursorActions` *(ui)* | field rw | `int` | not used |
| `campaignNumTimesPlay` *(ui)* | field rw | `int` | not used |
| `uiWinConditions` *(ui)* | field rw | `int` | not used |
| `isScenario` *(ui)* | field rw | `int` | not used |
| `isHotseatEnabled` *(ui)* | field rw | `int` | not used |
| `hotseatAutosave` *(ui)* | field rw | `int` | not used |
| `email` *(ui)* | field rw | `int` | not used |
| `isPlayingDlc` *(ui)* | property rw | `bool` | not used |
| `saveConfig` *(ui)* | field rw | `int` | not used |
| `closeAfterSave` *(ui)* | field rw | `int` | not used |
| `validateData` *(ui)* | field rw | `int` | not used |
| `campaignMapSpeedUp` *(ui)* | field rw | `int` | not used |
| `skipAiFactions` *(ui)* | field rw | `int` | not used |
| `labelCharacters` *(ui)* | field rw | `int` | not used |
| `noBackGroundFmv` *(ui)* | field rw | `int` | not used |
| `disableArrowMarkers` *(ui)* | field rw | `int` | not used |
| `arcadeBattles` *(ui)* | field rw | `int` | not used |
| `disableEvents` *(ui)* | field rw | `int` | not used |
| `isPrologue` *(ui)* | field rw | `int` | not used |
| `updateAiCamera` *(ui)* | field rw | `int` | not used |
| `hideCampaign` *(ui)* | field rw | `int` | not used |
| `unlimitedMenOnBattlefield` *(ui)* | field rw | `int` | not used |
| `tgaReserveSpace` *(ui)* | field rw | `int` | not used |
| `keysetUsed` *(ui)* | field rw | `int` | not used |
| `muteAdvisor` *(ui)* | field rw | `int` | not used |
| `advancedStatsAlways` *(ui)* | field rw | `int` | not used |
| `microManageAllSettlements` *(ui)* | field rw | `int` | not used |
| `blindAdvisor` *(ui)* | field rw | `int` | not used |
| `terrainQuality` *(ui)* | field rw | `int` | not used |
| `vegetationQuality` *(ui)* | field rw | `int` | not used |
| `useQuickChat` *(ui)* | field rw | `int` | not used |
| `graphicsAdaptor` *(ui)* | field rw | `int` | not used |
| `showDemeanour` *(ui)* | field rw | `int` | not used |
| `radar` *(ui)* | field rw | `int` | not used |
| `unitCards` *(ui)* | field rw | `int` | not used |
| `sa_cards` *(ui)* | field rw | `int` | not used |
| `buttons` *(ui)* | field rw | `int` | not used |
| `tutorialBattlePlayed` *(ui)* | field rw | `int` | not used |
| `disableVnVs` *(ui)* | field rw | `int` | not used |
| `allUsers` *(ui)* | field rw | `int` | not used |

### settlementTextStrings (0/8 used)

| member | kind | what it is | status |
|---|---|---|---|
| `incomeString` *(ui)* | field rw | `uiString` | not used |
| `incomeValue` *(ui)* | field rw | `uiString` | not used |
| `publicOrderString` *(ui)* | field rw | `uiString` | not used |
| `publicOrderValue` *(ui)* | field rw | `uiString` | not used |
| `populationString` *(ui)* | field rw | `uiString` | not used |
| `populationValue` *(ui)* | field rw | `uiString` | not used |
| `populationGrowthString` *(ui)* | field rw | `uiString` | not used |
| `populationGrowthValue` *(ui)* | field rw | `uiString` | not used |

### uiCardManager (0/10 used)

| member | kind | what it is | status |
|---|---|---|---|
| `selectedUnitCardsCount` *(ui)* | field rw | `int` | not used |
| `unitCardsCount` *(ui)* | field rw | `int` | not used |
| `selectedSettlement` *(ui)* | field rw | `settlementStruct` | not used |
| `selectedCharacter` *(ui)* | field rw | `character` | not used |
| `selectedFort` *(ui)* | field rw | `fortStruct` | not used |
| `getSelectedUnitCard` *(ui)* | function | Get selected unit card by index. | not used |
| `getUnitCard` *(ui)* | function | Get unit card by index (battle or strat). | not used |
| `getBuildingInfoScroll` *(ui)* | function | Get building info scroll. | not used |
| `getUnitInfoScroll` *(ui)* | function | Get unit info scroll. | not used |
| `getFamilyTree` *(ui)* | function | Get family tree from scroll. Make sure scroll is open! | not used |

### uiFamilyLeaf (0/6 used)

| member | kind | what it is | status |
|---|---|---|---|
| `record` *(ui)* | field rw | `characterRecord` | not used |
| `generation` *(ui)* | field rw | `int` | not used |
| `parent` *(ui)* | field rw | `uiFamilyLeaf` | not used |
| `spouse` *(ui)* | field rw | `uiFamilyLeaf` | not used |
| `numChildren` *(ui)* | field rw | `int` | not used |
| `getChild` *(ui)* | function | Get a child. | not used |

### uiFamilyTree (0/5 used)

| member | kind | what it is | status |
|---|---|---|---|
| `familyRoot` *(ui)* | field rw | `uiFamilyLeaf` | not used |
| `generations` *(ui)* | field rw | `int` | not used |
| `hoveredLeaf` *(ui)* | field rw | `uiFamilyLeaf` | not used |
| `selectedLeaf` *(ui)* | field rw | `uiFamilyLeaf` | not used |
| `canSelectAll` *(ui)* | field rw | `bool` | not used |

### uiString (0/4 used)

| member | kind | what it is | status |
|---|---|---|---|
| `thickness` *(ui)* | field rw | (0-255) | not used |
| `blue` *(ui)* | field rw | (0-255) | not used |
| `green` *(ui)* | field rw | (0-255) | not used |
| `red` *(ui)* | field rw | (0-255) | not used |

</details>

## Campaign rules database (tunables)

283 members, 2 used (+3 by name only).

<details><summary>Show members</summary>

### campaignDb (5/16 used)

| member | kind | what it is | status |
|---|---|---|---|
| `recruitment` *(modding)* | field rw | `campaignDbRecruitment` | not used |
| `religion` *(modding)* | field rw | `campaignDbReligion` | not used |
| `bribery` *(modding)* | field rw | `campaignDbBribery` | not used |
| `familyTree` *(modding)* | field rw | `campaignDbFamilyTree` | not used |
| `diplomacy` *(modding)* | field rw | `campaignDbDiplomacy` | USED report + order + event |
| `display` *(modding)* | field rw | `campaignDbDisplay` | not used |
| `ransom` *(modding)* | field rw | `campaignDbRansom` | not used |
| `autoResolve` *(modding)* | field rw | `campaignDbAutoresolve` | not used |
| `settlement` *(modding)* | field rw | `campaignDbSettlement` | USED report + order + event + other ? |
| `revolt` *(modding)* | field rw | `campaignDbRevolt` | not used |
| `horde` *(modding)* | field rw | `campaignDbHorde` | USED report + order + event ? |
| `merchants` *(modding)* | field rw | `campaignDbMerchants` | USED report ? |
| `agents` *(modding)* | field rw | `campaignDbAgents` | USED report + order + event + other |
| `crusades` *(modding)* | field rw | `campaignDbCrusades` | not used |
| `ai` *(modding)* | field rw | `campaignDbAi` | not used |
| `misc` *(modding)* | field rw | `campaignDbMisc` | not used |

### campaignDbAgents (0/44 used)

| member | kind | what it is | status |
|---|---|---|---|
| `denounceInquisitorBaseChance` *(modding)* | field rw | `float` | not used |
| `DenouncePriestBaseChance` *(modding)* | field rw | `float` | not used |
| `denounceAttackModifier` *(modding)* | field rw | `float` | not used |
| `denounceDefenceModifier` *(modding)* | field rw | `float` | not used |
| `denounceChanceMax` *(modding)* | field rw | `int` | not used |
| `assassinateBaseChance` *(modding)* | field rw | `float` | not used |
| `assassinateAttackModifier` *(modding)* | field rw | `float` | not used |
| `assassinateDefenceModifier` *(modding)* | field rw | `float` | not used |
| `assassinatePublicModifier` *(modding)* | field rw | `float` | not used |
| `assassinatePersonalModifier` *(modding)* | field rw | `float` | not used |
| `assassinateCounterSpyModifier` *(modding)* | field rw | `float` | not used |
| `assassinateAgentModifier` *(modding)* | field rw | `float` | not used |
| `assassinateOwnRegionModifier` *(modding)* | field rw | `float` | not used |
| `assassinateAssassinateAttrModifier` *(modding)* | field rw | `float` | not used |
| `assassinateChanceMin` *(modding)* | field rw | `int` | not used |
| `assassinateChanceMax` *(modding)* | field rw | `int` | not used |
| `denounceHereticAttemptModifier` *(modding)* | field rw | `float` | not used |
| `denounceCharacterAttemptModifier` *(modding)* | field rw | `float` | not used |
| `acquisitionBaseChance` *(modding)* | field rw | `float` | not used |
| `acquisitionLevelModifier` *(modding)* | field rw | `float` | not used |
| `acquisitionAttackTradeRightsModifier` *(modding)* | field rw | `float` | not used |
| `acquisitionDefenceTradeRightsModifier` *(modding)* | field rw | `float` | not used |
| `acquisitionChanceMin` *(modding)* | field rw | `int` | not used |
| `acquisitionChanceMax` *(modding)* | field rw | `int` | not used |
| `inquisitorCrtHeresyDivisor` *(modding)* | field rw | `float` | not used |
| `inquisitorCrtPfpModifier` *(modding)* | field rw | `float` | not used |
| `inquisitorCrtPfpModifierMin` *(modding)* | field rw | `float` | not used |
| `inquisitorCrtPfpModifierMax` *(modding)* | field rw | `float` | not used |
| `inquisitorCrtChanceMax` *(modding)* | field rw | `float` | not used |
| `spyBaseChance` *(modding)* | field rw | `float` | not used |
| `spyLevelModifier` *(modding)* | field rw | `float` | not used |
| `notSpyLevelModifier` *(modding)* | field rw | `float` | not used |
| `spyPublicModifier` *(modding)* | field rw | `float` | not used |
| `spyCounterSpyModifier` *(modding)* | field rw | `float` | not used |
| `spyDistanceModifier` *(modding)* | field rw | `float` | not used |
| `spySecretAgentTargetModifier` *(modding)* | field rw | `float` | not used |
| `spySedentaryTurnsModifier` *(modding)* | field rw | `float` | not used |
| `spyAllianceModifier` *(modding)* | field rw | `float` | not used |
| `spyTargetEngagedModifier` *(modding)* | field rw | `float` | not used |
| `spyInSettlementModifier` *(modding)* | field rw | `float` | not used |
| `spyWatchtowerModifier` *(modding)* | field rw | `float` | not used |
| `spyInOwnRegionModifier` *(modding)* | field rw | `float` | not used |
| `spyChanceMin` *(modding)* | field rw | `int` | not used |
| `spyChanceMax` *(modding)* | field rw | `int` | not used |

### campaignDbAi (0/14 used)

| member | kind | what it is | status |
|---|---|---|---|
| `priestReligionMin` *(modding)* | field rw | `float` | not used |
| `priestReligionMax` *(modding)* | field rw | `float` | not used |
| `priestHeresyMin` *(modding)* | field rw | `float` | not used |
| `priestHeresyMax` *(modding)* | field rw | `float` | not used |
| `priestReligionExport` *(modding)* | field rw | `float` | not used |
| `priestMaxProdTurns` *(modding)* | field rw | `float` | not used |
| `merchantMinSurvivalAcquire` *(modding)* | field rw | `int` | not used |
| `attStrModifier` *(modding)* | field rw | `float` | not used |
| `siegeAttStrModifier` *(modding)* | field rw | `float` | not used |
| `crusadeAttStrModifier` *(modding)* | field rw | `float` | not used |
| `sallyAttStrModifier` *(modding)* | field rw | `float` | not used |
| `ambushAttStrModifier` *(modding)* | field rw | `float` | not used |
| `strLimitWeak` *(modding)* | field rw | `float` | not used |
| `strLimitStrong` *(modding)* | field rw | `float` | not used |

### campaignDbAutoresolve (0/26 used)

| member | kind | what it is | status |
|---|---|---|---|
| `minCapturePercent` *(modding)* | field rw | `float` | not used |
| `maxCapturePercent` *(modding)* | field rw | `float` | not used |
| `lopsidedThresh` *(modding)* | field rw | `float` | not used |
| `lopsidedHnMod` *(modding)* | field rw | `float` | not used |
| `separationMissileAdd` *(modding)* | field rw | `int` | not used |
| `navalSinkModifier` *(modding)* | field rw | `float` | not used |
| `navalSinkOffset` *(modding)* | field rw | `float` | not used |
| `navalSinkMax` *(modding)* | field rw | `float` | not used |
| `sallyAtDefDrawDivisor` *(modding)* | field rw | `float` | not used |
| `useNewSettAutoResolve` *(modding)* | field rw | `bool` | not used |
| `gateDefenceNumOilAttacks` *(modding)* | field rw | `int` | not used |
| `gateDefenceStrengthOilBase` *(modding)* | field rw | `float` | not used |
| `gateDefenceNumArrowAttacks` *(modding)* | field rw | `int` | not used |
| `gateDefenceStrengthArrowBase` *(modding)* | field rw | `float` | not used |
| `gateDefenceStrengthArrowLevelModifier` *(modding)* | field rw | `float` | not used |
| `gateDefenceNumDefaultAttacks` *(modding)* | field rw | `int` | not used |
| `gateDefenceStrengthDefaultBase` *(modding)* | field rw | `float` | not used |
| `gateDefenceStrengthDefaultLevelModifier` *(modding)* | field rw | `float` | not used |
| `settDefenceNumArrowAttacks` *(modding)* | field rw | `int` | not used |
| `settDefenceStrengthArrowBase` *(modding)* | field rw | `float` | not used |
| `settDefenceStrengthArrowModifier` *(modding)* | field rw | `float` | not used |
| `settDefenceStrengthDefaultBase` *(modding)* | field rw | `float` | not used |
| `settDefenceStrengthDefaultModifier` *(modding)* | field rw | `float` | not used |
| `displayStrengthOil` *(modding)* | field rw | `float` | not used |
| `displayStrengthArrow` *(modding)* | field rw | `float` | not used |
| `displayStrengthDefault` *(modding)* | field rw | `float` | not used |

### campaignDbBribery (0/13 used)

| member | kind | what it is | status |
|---|---|---|---|
| `baseCharacterChance` *(modding)* | field rw | `float` | not used |
| `religionModifier` *(modding)* | field rw | `float` | not used |
| `combinedAttributeModifier` *(modding)* | field rw | `float` | not used |
| `briberAttributeDivisor` *(modding)* | field rw | `float` | not used |
| `bribeeAttributeDivisor` *(modding)* | field rw | `float` | not used |
| `armySizeModifier` *(modding)* | field rw | `float` | not used |
| `baseSettlementChance` *(modding)* | field rw | `float` | not used |
| `settlementLoyaltyModifier` *(modding)* | field rw | `float` | not used |
| `settlementPopulationModifier` *(modding)* | field rw | `float` | not used |
| `factionStandingDivisor` *(modding)* | field rw | `float` | not used |
| `maxBribeChance` *(modding)* | field rw | `float` | not used |
| `minBribeChance` *(modding)* | field rw | `float` | not used |
| `bribeChanceModifier` *(modding)* | field rw | `float` | not used |

### campaignDbCrusades (0/7 used)

| member | kind | what it is | status |
|---|---|---|---|
| `requiredJihadPiety` *(modding)* | field rw | `int` | not used |
| `maxDisbandProgress` *(modding)* | field rw | `float` | not used |
| `nearTargetNoDisbandDistance` *(modding)* | field rw | `float` | not used |
| `disbandProgressWindow` *(modding)* | field rw | `int` | not used |
| `crusadeCalledStartTurn` *(modding)* | field rw | `int` | not used |
| `jihadCalledStartTurn` *(modding)* | field rw | `int` | not used |
| `movementPointsModifier` *(modding)* | field rw | `float` | not used |

### campaignDbDiplomacy (0/2 used)

| member | kind | what it is | status |
|---|---|---|---|
| `maxDiplomacyItems` *(modding)* | field rw | `int` | not used |
| `nullMissionScore` *(modding)* | field rw | `int` | not used |

### campaignDbDisplay (0/12 used)

| member | kind | what it is | status |
|---|---|---|---|
| `characterSelectionRadius` *(modding)* | field rw | `float` | not used |
| `characterSelectionHeight` *(modding)* | field rw | `float` | not used |
| `characterSelectionHeightCrouching` *(modding)* | field rw | `float` | not used |
| `diplomacyScrollHeight` *(modding)* | field rw | `float` | not used |
| `factionStandingMin` *(modding)* | field rw | `float` | not used |
| `factionStandingMax` *(modding)* | field rw | `float` | not used |
| `UseOrigRebelFactionModels` *(modding)* | field rw | `bool` | not used |
| `hudTabTextOffset` *(modding)* | field rw | `int` | not used |
| `useFactionCreatorSettModels` *(modding)* | field rw | `bool` | not used |
| `standardSoldierLimit` *(modding)* | field rw | `int` | not used |
| `standardSoldierLevelScale` *(modding)* | field rw | `int` | not used |
| `clearBattleModelsOnNewFaction` *(modding)* | field rw | `bool` | not used |

### campaignDbExtra (0/41 used)

| member | kind | what it is | status |
|---|---|---|---|
| `clearPoolsWithCaps` *(modding)* | field rw | `bool` | not used |
| `addInitialWithCaps` *(modding)* | field rw | `bool` | not used |
| `forceClampToMax` *(modding)* | field rw | `bool` | not used |
| `witchConversionRateModifier` *(modding)* | field rw | `float` | not used |
| `inquisitorTargetCrusades` *(modding)* | field rw | `bool` | not used |
| `foundingConversionDefaultRate` *(modding)* | field rw | `float` | not used |
| `ownerConversionDefaultRate` *(modding)* | field rw | `float` | not used |
| `neighbourNormaliseWeight` *(modding)* | field rw | `float` | not used |
| `governorConversionRateOffset` *(modding)* | field rw | `float` | not used |
| `governorConversionRateModifier` *(modding)* | field rw | `float` | not used |
| `spyConversionRateOffset` *(modding)* | field rw | `float` | not used |
| `spyConversionRateModifier` *(modding)* | field rw | `float` | not used |
| `spyConversionRateForeignModifier` *(modding)* | field rw | `float` | not used |
| `bribeToFamilyTree` *(modding)* | field rw | `bool` | not used |
| `enemiesRejectGifts` *(modding)* | field rw | `bool` | not used |
| `useBalanceOwed` *(modding)* | field rw | `bool` | not used |
| `recruitmentSortSimple` *(modding)* | field rw | `bool` | not used |
| `keepOriginalHereticPortraits` *(modding)* | field rw | `bool` | not used |
| `altSettOrderColors` *(modding)* | field rw | `bool` | not used |
| `separateGamesRaces` *(modding)* | field rw | `bool` | not used |
| `chivalryDisplayThreshold` *(modding)* | field rw | `int` | not used |
| `captiveRansomForSlave` *(modding)* | field rw | `bool` | not used |
| `switchableDefenceExposed` *(modding)* | field rw | `bool` | not used |
| `gateDefenceStrengthOilLevelModifier` *(modding)* | field rw | `float` | not used |
| `settDefenceStrengthNumDefaultAttacks` *(modding)* | field rw | `int` | not used |
| `siegeGearRequiredForCastleLevel` *(modding)* | field rw | `int` | not used |
| `noTowersOnlyForCastleLevel` *(modding)* | field rw | `int` | not used |
| `fortFortificationLevel` *(modding)* | field rw | `int` | not used |
| `alternativeReligiousUnrest` *(modding)* | field rw | `bool` | not used |
| `revoltAdditionalArmies` *(modding)* | field rw | `bool` | not used |
| `revoltCrusadingArmies` *(modding)* | field rw | `bool` | not used |
| `agentsCanHide` *(modding)* | field rw | `bool` | not used |
| `denounceChanceMin` *(modding)* | field rw | `int` | not used |
| `inquisitorCrtChanceMin` *(modding)* | field rw | `float` | not used |
| `inquisitorTargetLeaders` *(modding)* | field rw | `bool` | not used |
| `inquisitorTargetHeirs` *(modding)* | field rw | `bool` | not used |
| `spyRescaleChance` *(modding)* | field rw | `bool` | not used |
| `allowResourceForts` *(modding)* | field rw | `bool` | not used |
| `enableHotseatMessages` *(modding)* | field rw | `bool` | not used |
| `enableBananaRepublicCheat` *(modding)* | field rw | `bool` | not used |
| `enableUnitAccentOverrides` *(modding)* | field rw | `bool` | not used |

### campaignDbFamilyTree (0/17 used)

| member | kind | what it is | status |
|---|---|---|---|
| `maxAge` *(modding)* | field rw | `int` | not used |
| `maxAgeForMarriageMale` *(modding)* | field rw | `int` | not used |
| `maxAgeForMarriageForFemale` *(modding)* | field rw | `int` | not used |
| `maxAgeBeforeDeath` *(modding)* | field rw | `int` | not used |
| `maxAgeOfChild` *(modding)* | field rw | `int` | not used |
| `oldAge` *(modding)* | field rw | `int` | not used |
| `ageOfManhood` *(modding)* | field rw | `int` | not used |
| `daughtersAgeOfConsent` *(modding)* | field rw | `int` | not used |
| `daughtersRetirementAge` *(modding)* | field rw | `int` | not used |
| `ageDifferenceMin` *(modding)* | field rw | `int` | not used |
| `ageDifferenceMax` *(modding)* | field rw | `int` | not used |
| `parentToChildMinAgeDiff` *(modding)* | field rw | `int` | not used |
| `minAdoptionAge` *(modding)* | field rw | `int` | not used |
| `maxAdoptionAge` *(modding)* | field rw | `int` | not used |
| `maxAgeForConception` *(modding)* | field rw | `int` | not used |
| `ageOfManhoodClose` *(modding)* | field rw | `int` | not used |
| `maxNumberOfChildren` *(modding)* | field rw | `int` | not used |

### campaignDbHorde (0/7 used)

| member | kind | what it is | status |
|---|---|---|---|
| `endTargetFactionBonus` *(modding)* | field rw | `int` | not used |
| `startTargetFactionBonus` *(modding)* | field rw | `int` | not used |
| `farmingLevelBonus` *(modding)* | field rw | `int` | not used |
| `sharedTargetBonus` *(modding)* | field rw | `int` | not used |
| `disbandingHordeBonus` *(modding)* | field rw | `int` | not used |
| `hordeStartingRegionBonus` *(modding)* | field rw | `int` | not used |
| `hordeTargetResourceBonus` *(modding)* | field rw | `int` | not used |

### campaignDbMerchants (0/2 used)

| member | kind | what it is | status |
|---|---|---|---|
| `baseIncomeModifier` *(modding)* | field rw | `float` | not used |
| `tradeBonusOffset` *(modding)* | field rw | `float` | not used |

### campaignDbMisc (0/7 used)

| member | kind | what it is | status |
|---|---|---|---|
| `fortDevastationDistance` *(modding)* | field rw | `int` | not used |
| `armyDevastationDistance` *(modding)* | field rw | `int` | not used |
| `fortDevastationModifier` *(modding)* | field rw | `int` | not used |
| `armyDevastationModifier` *(modding)* | field rw | `int` | not used |
| `allowEnemyForts` *(modding)* | field rw | `bool` | not used |
| `siegeMovementPointsModifier` *(modding)* | field rw | `int` | not used |
| `cavalryMovementPointsModifier` *(modding)* | field rw | `int` | not used |

### campaignDbRansom (0/9 used)

| member | kind | what it is | status |
|---|---|---|---|
| `captorReleaseChanceBase` *(modding)* | field rw | `float` | not used |
| `captorReleaseChanceChivMod` *(modding)* | field rw | `float` | not used |
| `captorRansomChanceBase` *(modding)* | field rw | `float` | not used |
| `captorRansomChanceChivMod` *(modding)* | field rw | `float` | not used |
| `captorRansomChanceTmMod` *(modding)* | field rw | `float` | not used |
| `captiveRansomChanceBase` *(modding)* | field rw | `float` | not used |
| `captiveRansomChanceChivMod` *(modding)* | field rw | `float` | not used |
| `captiveRansomChanceTmMod` *(modding)* | field rw | `float` | not used |
| `captiveRansomChanceMsmMod` *(modding)* | field rw | `float` | not used |

### campaignDbRecruitment (0/11 used)

| member | kind | what it is | status |
|---|---|---|---|
| `recruitmentSlots` *(modding)* | field rw | `int` | not used |
| `retrainingSlots` *(modding)* | field rw | `int` | not used |
| `deplenishPoolsWithCaps` *(modding)* | field rw | `bool` | not used |
| `deplenishMultiplier` *(modding)* | field rw | `float` | not used |
| `deplenishOffset` *(modding)* | field rw | `float` | not used |
| `addDisbandNoCaps` *(modding)* | field rw | `bool` | not used |
| `percentagePoolReductionLost` *(modding)* | field rw | `int` | not used |
| `percentagePoolReductionOccupy` *(modding)* | field rw | `int` | not used |
| `percentagePoolReductionSack` *(modding)* | field rw | `int` | not used |
| `percentagePoolReductionExterminate` *(modding)* | field rw | `int` | not used |
| `maxAgentsPerTurn` *(modding)* | field rw | `int` | not used |

### campaignDbReligion (0/21 used)

| member | kind | what it is | status |
|---|---|---|---|
| `maxWitchesPerRegion` *(modding)* | field rw | `int` | not used |
| `maxWitches` *(modding)* | field rw | `int` | not used |
| `maxHereticsPerRegion` *(modding)* | field rw | `int` | not used |
| `maxHeretics` *(modding)* | field rw | `int` | not used |
| `maxInquisitorsPerRegion` *(modding)* | field rw | `int` | not used |
| `maxInquisitors` *(modding)* | field rw | `int` | not used |
| `maxHereticsConversionModifier` *(modding)* | field rw | `float` | not used |
| `hereticConversionRateModifier` *(modding)* | field rw | `float` | not used |
| `hereticConversionRateOffset` *(modding)* | field rw | `float` | not used |
| `witchConversionRateOffset` *(modding)* | field rw | `float` | not used |
| `inquisitorConversionRateModifier` *(modding)* | field rw | `float` | not used |
| `inquisitorConversionRateOffset` *(modding)* | field rw | `float` | not used |
| `priestConversionRateModifier` *(modding)* | field rw | `float` | not used |
| `priestConversionRateOffset` *(modding)* | field rw | `float` | not used |
| `witchChanceModifier` *(modding)* | field rw | `float` | not used |
| `hereticChanceModifier` *(modding)* | field rw | `float` | not used |
| `inquisitorChanceModifier` *(modding)* | field rw | `float` | not used |
| `minCardinalPiety` *(modding)* | field rw | `int` | not used |
| `convertToHereticBaseModifier` *(modding)* | field rw | `float` | not used |
| `convertToHereticUnorthodoxModifier` *(modding)* | field rw | `float` | not used |
| `inquisitorTurnStart` *(modding)* | field rw | `int` | not used |

### campaignDbRevolt (0/15 used)

| member | kind | what it is | status |
|---|---|---|---|
| `endTurnModifier` *(modding)* | field rw | `float` | not used |
| `excommunicatedModifier` *(modding)* | field rw | `float` | not used |
| `newLeaderModifier` *(modding)* | field rw | `float` | not used |
| `maxEffectiveLoyalty` *(modding)* | field rw | `float` | not used |
| `rebelRegionModifier` *(modding)* | field rw | `float` | not used |
| `shadowRegionModifier` *(modding)* | field rw | `float` | not used |
| `rebelBorderModifier` *(modding)* | field rw | `float` | not used |
| `shadowBorderModifier` *(modding)* | field rw | `float` | not used |
| `numUnitsModifier` *(modding)* | field rw | `float` | not used |
| `captainModifier` *(modding)* | field rw | `float` | not used |
| `minRevoltChance` *(modding)* | field rw | `float` | not used |
| `maxRevoltChance` *(modding)* | field rw | `float` | not used |
| `aiRevoltModifier` *(modding)* | field rw | `float` | not used |
| `shadowAuthorityModifier` *(modding)* | field rw | `float` | not used |
| `shadowAuthorityModifierSett` *(modding)* | field rw | `float` | not used |

### campaignDbSettlement (0/19 used)

| member | kind | what it is | status |
|---|---|---|---|
| `sackMoneyModifier` *(modding)* | field rw | `float` | not used |
| `exterminateMoneyModifier` *(modding)* | field rw | `float` | not used |
| `chivSpfModifier` *(modding)* | field rw | `float` | not used |
| `chivSofModifier` *(modding)* | field rw | `float` | not used |
| `dreadSofModifier` *(modding)* | field rw | `float` | not used |
| `pietyCorruptionModifier` *(modding)* | field rw | `float` | not used |
| `pietyAdminSifModifier` *(modding)* | field rw | `float` | not used |
| `portToPortMpMin` *(modding)* | field rw | `float` | not used |
| `heresyUnrestNodifier` *(modding)* | field rw | `float` | not used |
| `religionUnrestModifier` *(modding)* | field rw | `float` | not used |
| `siegeGearRequiredForCityLevel` *(modding)* | field rw | `int` | not used |
| `noTowersOnlyForCityLevel` *(modding)* | field rw | `int` | not used |
| `minTurnKeepRebelGarrison` *(modding)* | field rw | `int` | not used |
| `destroyEmptyForts` *(modding)* | field rw | `bool` | not used |
| `canBuildForts` *(modding)* | field rw | `bool` | not used |
| `raceGameCostsModifier` *(modding)* | field rw | `float` | not used |
| `altRelAlliedModifier` *(modding)* | field rw | `float` | not used |
| `altRelGovModifierBase` *(modding)* | field rw | `float` | not used |
| `altRelGovCoefficient` *(modding)* | field rw | `float` | not used |

</details>

## Modding and internals

33 members, 0 used (+3 by name only).

<details><summary>Show members</summary>

### vector3 (2/3 used)

| member | kind | what it is | status |
|---|---|---|---|
| `xCoord` *(modding)* | field rw | `float` | USED report + order + other ? |
| `yCoord` *(modding)* | field rw | `float` | USED report + order + other ? |
| `zCoord` *(modding)* | field rw | `float` | not used |

### mountStruct (1/19 used)

| member | kind | what it is | status |
|---|---|---|---|
| `name` *(modding)* | field rw | `string` | USED report + order + event + other ? |
| `modelName` *(modding)* | field rw | `string` | not used |
| `mountClass` *(modding)* | field rw | `int` | not used |
| `radius` *(modding)* | field rw | `float` | not used |
| `xRadius` *(modding)* | field rw | `float` | not used |
| `yRadius` *(modding)* | field rw | `float` | not used |
| `yOffset` *(modding)* | field rw | `float` | not used |
| `height` *(modding)* | field rw | `float` | not used |
| `mass` *(modding)* | field rw | `float` | not used |
| `elephantDeadRadius` *(modding)* | field rw | `float` | not used |
| `elephantTuskRadius` *(modding)* | field rw | `float` | not used |
| `elephantTuskZ` *(modding)* | field rw | `float` | not used |
| `elephantRootNodeHeight` *(modding)* | field rw | `float` | not used |
| `elephantNumberOfRiders` *(modding)* | field rw | `int` | not used |
| `riderOffSetX` *(modding)* | field rw | `float` | not used |
| `riderOffSetY` *(modding)* | field rw | `float` | not used |
| `riderOffsetZ` *(modding)* | field rw | `float` | not used |
| `rootNodeHeight` *(modding)* | field rw | `float` | not used |
| `getElephantRiderOffset` *(modding)* | function | Get elephant rider offset. | not used |

### mapImageStruct (0/11 used)

| member | kind | what it is | status |
|---|---|---|---|
| `useBlur` *(modding)* | field rw | `bool` | not used |
| `adaptiveBlur` *(modding)* | field rw | Can be slow on large or frequently updated images! needs use blur also true. | not used |
| `blurStrength` *(modding)* | field rw | `float` | not used |
| `makeMapImage` *(modding)* | function | Create a new image you want to determine region colors. | not used |
| `exportImage` *(modding)* | function | Export image with current tiles set and black background. | not used |
| `clearMapImage` *(modding)* | function | Reset image state. | not used |
| `loadMapTexture` *(modding)* | function | Create a new map texture. Use an uncompressed(!) dds image that is some multiple of your map_regions size. Th... | not used |
| `fillRegionColor` *(modding)* | function | Fill a region with a color. | not used |
| `addRegionColor` *(modding)* | function | Add a color to already filled region. | not used |
| `fillTileColor` *(modding)* | function | Fill a tile with a color. | not used |
| `addTileColor` *(modding)* | function | Add a color to an already set tile. | not used |

</details>
