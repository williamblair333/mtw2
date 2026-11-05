# EOP scripting coverage

What EOP's Lua interface lets a script see and do, and which of it our bridge
(`lua/parley_bridge.lua`, `lua/luaPluginScript.lua`) already reads or calls for the LLM rulers.

**Generated file.** Everything below the hand-written sections comes from
`scripts/eop_coverage.py`; the intro and the gap list are `scripts/eop_coverage_head.md`.
Regenerate with `just eop-coverage` (needs the EOP source at `../M2TWEOP-library`,
or pass `--eop DIR`). Edit the head file for prose, the script for rules, never this file.

- **EOP source:** `{{VERSION}}` (a master checkout, the build the game runs).
  `docs/eop-api-notes.md` records what was verified live against 3.3.1.
- **Found:** {{TOTAL}} members (fields, properties, functions and events; enum values counted
  apart), {{CAMPAIGN}} of them campaign-relevant.
- **Used by the bridge:** {{USED}} members, plus {{USED_MAYBE}} matched by name only
  (see `?` below). Of the campaign-relevant ones, {{CAMPAIGN_USED}} (+{{CAMPAIGN_USED_MAYBE}} by name).
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

**Events the bridge listens to** ({{EVENTS_USED}} of {{EVENTS}} EOP events): `onPluginLoad`,
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
