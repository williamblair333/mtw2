# Decision inventory

Every decision a player makes in an MTW2 grand campaign, what he must see to make it, and whether an
LLM ruler can see it and carry it out today. A faction's game AI is frozen only when every row of
this table reads "yes" for that faction's ruler; until then the game AI keeps every row the ruler
doesn't cover.

**Complete means:** every decision found in any of the three sources below has a row. A decision
found in one source and missing here is a miss.

1. The game's own files (authoritative): `data/text/english/` — `diplomacy.txt` (every proposal),
   `missions.txt` (every mission), `event_titles.txt` (every event message), `strat.txt` (every
   campaign-map panel, button and label), `cursor_action_tooltips.txt` (every right-click action).
2. EOP 3.3.1's Lua API (what can be read and done), extracted from its source: 1787 entries.
3. Player guides, via Gemini, one area at a time (`_review/` drafts), checked against 1 and 2.

**Cross-check (2026-10-24):** all 17 proposal types in `diplomacy.txt` have a row (D2–D15, D18);
every right-click action in `cursor_action_tooltips.txt` maps to a row; every decision button in
`strat.txt` maps to a row; the 46 missions and 225 event messages are information, covered as
classes (C3, C7) with their defects (X1, X2). The six Gemini area reports
(`_review/2026-10-24-gemini-decisions-*.md`) added W17–W22, N5–N6, A9–A12, D18–D20 and R23–R26.

Columns: **See** — the ruler's report shows what he needs; **Do** — an order exists and works;
**Route** — how it could be done (an EOP call, screen clicks) when Do isn't yes.
✅ yes · ◐ partly · ✗ no.

## Realm: settlements and economy

| # | Decision | Must know | See | Do | Route |
|---|---|---|---|---|---|
| R1 | Queue a building | can-build list, cost, turns, effects, treasury | ✅ | ✅ build | — |
| R2 | Cancel or reorder the building queue | queue, refund | ✅ queue | ✗ | buildingsQueue (no remove call found) / clicks |
| R3 | Repair a damaged building | damage (hp), repair cost and time | ✗ | ✗ | building.hp; repair: clicks |
| R4 | Demolish a building | building, refund, what is lost | ◐ levels | ✗ | settlementStruct.destroyBuilding |
| R5 | Convert city ↔ castle | level, cost, what is lost | ✗ | ✗ | construction option (probe) |
| R6 | Recruit a unit | can-recruit list, pool, cost, turns, upkeep | ✅ | ✅ recruit | — |
| R7 | Recruit an agent or ship | agent caps, cost | ◐ | ◐ recruit (if listed) | getAgentCapability, getAgentLimitCapability |
| R8 | Cancel or reorder recruits | queue | ◐ training | ✗ | clicks |
| R9 | Retrain (refill, re-equip) a unit | soldiers vs max, armour/weapon level, cost | ◐ soldiers | ✗ | clicks (SELECT_UNIT_TO_RETRAIN) |
| R10 | Set tax level | tax, public order, growth, income | ◐ no growth | ✅ set_tax | settlementStats |
| R11 | Auto-manage a settlement, and its policy | the policies | ✗ | ✗ | aiProductionController.isAutoManaged / autoManagePolicy |
| R12 | Rally point for new recruits | — | ✗ | ✗ | clicks (minor) |
| R13 | Games and races frequency | public order, cost | ✗ | ✗ | clicks (probe) |
| R14 | Make a settlement the capital | distance-to-capital order penalty | ✗ | ✗ | probe |
| R15 | Guild offer: accept or decline | guild, cost, slot | ◐ popup read | ◐ popup | popup choice |
| R16 | Station or remove a governor | governor traits (chivalry, dread, management…) | ◐ whereabouts | ✅ move_army | namedCharacter stats, getTraits |
| R17 | Move retinue (ancillaries) between characters | ancillary effects | ✗ | ✗ | getAncillary / addAncillary, removeAncillary |
| R18 | Hire mercenaries | pool in region, cost, room | ✗ | ✗ | campaignTable.getMercPool, mercPool.getMercUnit; hire: clicks |
| R19 | Build a fort or watchtower | cost, place | ✗ | ✗ | character.createFort, stackStruct.buildWatchTower |
| R20 | Public order and growth breakdown (information) | order and growth causes, squalor, unrest, religion | ◐ order % | — | settlementStats |
| R21 | Plague: keep people in or out | plagued settlements | ✗ | — | settlementStruct.plagued |
| R22 | Farming, mines, trade income (information) | per-settlement income | ◐ faction totals | — | settlementStats |
| R23 | Trade routes and partners (information) | each settlement's land and sea routes, goods, values | ✗ | — | probe (settlementStats trade fields) |
| R24 | Free upkeep slots (information) | which units in a garrison cost nothing | ✗ | — | probe |
| R25 | Abandon a settlement (walk the garrison out) | order without garrison | ✅ | ✅ move_army | — |
| R26 | Building tree (information) | what each building unlocks next | ✗ | — | EDB (export_descr_buildings) |

## War: armies and battles

| # | Decision | Must know | See | Do | Route |
|---|---|---|---|---|---|
| W1 | Move an army, march on a settlement | moves left, terrain, land/sea | ✅ | ✅ move_army, march_on | — |
| W2 | Attack an army | foe strength, units, general | ✅ | ✅ attack | — |
| W3 | Besiege; siege length; holdout | walls, garrison, holdout | ✅ | ✅ besiege | — |
| W4 | Build siege equipment (rams, ladders, towers) | build points, wall type | ✗ | ✗ | stackStruct.ladders/rams/towers read; build: clicks |
| W5 | Assault | equipment ready, walls | ◐ | ◐ besiege assault | needs W4 |
| W6 | Sally out / attack from a besieged settlement | besieger strength | ◐ siege | ◐ attack | — |
| W7 | Lift a siege, relieve an ally | — | ✅ | ✅ move_army | — |
| W8 | Battle: fight, auto-resolve, withdraw | odds, both sides | ✗ | ✗ (all auto-resolved) | campaignTable.restrictAutoResolve |
| W9 | Ambush (hidden army) | forest, enemy path | ✗ | ✗ | namedCharacter.ambush (stat); clicks |
| W10 | After capture: occupy, sack, exterminate | loot, population, order | ✅ popup | ✅ popup choice | — |
| W11 | Merge armies; merge units; split | units, strength | ✅ | ✅ merge_armies, merge_units; split ✗ | factionStruct.splitArmy |
| W12 | Disband units | upkeep, free upkeep | ✅ | ✅ disband | — |
| W13 | Spy opens the gates | gates-open chance | ✗ | ✗ | settlementStruct.gatesAreOpened |
| W14 | Crusade or jihad: join, leave, target | crusade target, deadline | ✗ | ✗ | character.crusade, campaignTable.crusade |
| W15 | Captives: ransom, release, execute | captives, price | ✅ popup | ✅ popup choice | — |
| W16 | General's command, traits, loyalty (information) | command, loyalty, traits | ✗ | — | namedCharacter.command, loyalty, getTraits |
| W17 | Garrison, leave or take a fort | fort, its garrison | ✗ forts | ◐ move_army | factionStruct.getFort, fortStruct |
| W18 | Exchange units between two adjacent armies (not whole armies) | both armies' units | ✅ | ✗ | probe (stackStruct.releaseUnits?) |
| W19 | Defend: stand or withdraw when attacked; night attack; AI control of allied reinforcements | odds | ✗ | ✗ | out of scope while every battle is auto-resolved; see Scope |
| W20 | Request a crusade from the Pope; crusade mercenaries | papal standing, target | ✗ | ✗ | probe |
| W21 | Answer an ally's call to arms (war declared on an ally) | the war, the ally | ◐ stance news | ✅ set_stance | — |
| W22 | Respond to a papal "cease hostilities" demand | the demand, excommunication risk | ◐ popup read | ✅ set_stance | — |

## Ships

| # | Decision | Must know | See | Do | Route |
|---|---|---|---|---|---|
| N1 | Sail, carry an army, land | fleet, coast tiles | ✅ | ✅ move_army, board, land | — |
| N2 | Blockade a port | trade lost | ✅ | ✅ blockade | — |
| N3 | Attack a fleet | fleet strength | ✅ | ✅ attack | — |
| N4 | Build ships | port, cost | ◐ | ◐ recruit | — |
| N5 | Split or merge fleets; move passengers between fleets | ships, passengers | ◐ | ◐ merge_armies | factionStruct.splitArmy |
| N6 | Break a blockade of your own port | blockading fleet | ◐ | ✅ attack | — |

## Agents

| # | Decision | Must know | See | Do | Route |
|---|---|---|---|---|---|
| A1 | Spy on a settlement or character; infiltrate | target, chance | ✅ | ✅ spy | — |
| A2 | Assassinate | target, chance | ✅ | ✅ assassinate | — |
| A3 | Sabotage a building | target building | ✅ | ✅ sabotage (building choice ✗) | character.sabotage |
| A4 | Diplomat: negotiate, bribe | target | ✅ | ✅ bribe; negotiate ✗ (see D) | character.diplomacy* |
| A5 | Merchant: trade a resource; acquire a rival merchant | resource value, rival merchants | ✅ resources | ◐ move_agent; acquire ✗ | character.acquire |
| A6 | Priest: convert, denounce | religion % in region | ✗ religion | ◐ move_agent; denounce ✗ | character.denounce, settlementStruct.getReligion |
| A7 | Princess: marriage, diplomacy | target | ✅ | ✅ marry | — |
| A8 | Agent skills and traits (information) | subterfuge, charm, … | ✗ | — | namedCharacter stats |
| A9 | Agent rides with an army or fleet; leaves it | — | ✅ | ◐ move_agent, board | — |
| A10 | Station an agent at home (counter-spy, protect a governor) | foreign agents near | ✅ seen agents | ✅ move_agent | — |
| A11 | Disband an agent | upkeep | ✅ | ✗ | probe (character.kill is not disbanding) |
| A12 | Pick the target inside a stack or settlement (assassinate, sabotage) | the characters or buildings there | ◐ | ◐ | character.assassinate / sabotage take a target |

## Diplomacy (the proposal panel, from diplomacy.txt)

| # | Decision | Must know | See | Do | Route |
|---|---|---|---|---|---|
| D1 | War and peace | stances | ✅ | ✅ set_stance | — |
| D2 | Ceasefire | — | ✅ | ✅ set_stance peace | — |
| D3 | Alliance; cancel alliance | — | ✅ | ✅ set_stance | — |
| D4 | Trade rights | which ports and roads trade | ◐ | ✗ | probe (a script command?) |
| D5 | Military access | — | ✗ | ✗ | factionStruct.hasMilitaryAccess / setMilitaryAccess |
| D6 | Map information | — | ✗ | ✗ | probe |
| D7 | Gift, one-off money, yearly tribute | treasury | ✅ | ◐ send_gold (no yearly) | probe |
| D8 | Region (give, demand) | — | ✅ | ◐ cede_settlement | settlementStruct.changeOwner |
| D9 | Protectorate | — | ✗ | ✗ | probe |
| D10 | Demand, threaten | — | — | ✗ | none in EOP (LLM messages instead) |
| D11 | Bribe a settlement or army | cost | ✅ | ✅ bribe | — |
| D12 | Join an attack on a third faction | — | — | ✗ | messages instead |
| D13 | Marriage alliance | — | ◐ | ◐ popup | — |
| D14 | Buy or sell a papal vote | cardinals | ✗ | ✗ | collegeOfCardinals |
| D15 | Ask to lift excommunication | papal standing | ✗ | ✗ | probe |
| D16 | Answer a proposal from another faction | the offer, its balance | ✅ popup | ✅ popup choice | — |
| D17 | Relations, reputation, power, wealth, priorities (information) | per faction | ◐ size | — | getFactionStanding, getFactionRanking |
| D18 | Each proposal both ways: offer or demand (D4–D9, D12) | — | — | ✗ | as each row |
| D19 | Cancel trade rights, military access, a protectorate, tribute | current treaties | ✗ treaties | ✗ | probe |
| D20 | Treaties in force (information): trade rights, access, tribute paid and received, protector | per faction | ✗ | — | hasMilitaryAccess; others probe |

## Church, family, missions, events

| # | Decision | Must know | See | Do | Route |
|---|---|---|---|---|---|
| C1 | Papal standing (information) | standing, excommunication risk | ✗ | — | factionStruct.getFactionStanding |
| C2 | Papal election vote | cardinals | ✅ popup | ✅ popup | — |
| C3 | Missions: know them, their deadline and reward | every active mission | ◐ popup when issued | — | factionStruct.missions (not exposed: route 2) |
| C4 | Marriage offers; adoption offers | suitor stats | ✅ popup | ✅ popup | — |
| C5 | Heir | candidates | ◐ family | ✗ | namedCharacter.setAsHeir |
| C6 | Family stats and traits (information) | command, loyalty, piety, traits, vices | ✗ | — | namedCharacter stats, getTraits |
| C7 | Rebellion, riots, disasters, plague (information) | which settlement | ◐ | — | 225 event messages: onIncomingMessage eventID |
| C8 | Rankings and victory conditions (information) | provinces held, factions to outlast | ✗ | — | factionStruct.getFactionRanking; holdRegionsWinCondition |

## EOP master against 3.3.1 (checked 2026-10-24)

3.3.1 (2024-08-23) is still EOP's latest release. EOP-Labs' `master` has moved on (head `b525628`,
2026-10-19), and its CI publishes a build of every commit as an Actions artifact
(`M2TWEOP-latest-build-<sha>`, about 120 MB; artifacts expire, so pin and keep a copy). Master's Lua
API has 2509 entries against 3.3.1's 1787 (1075 new).

What master adds for the rows above:

| Rows | Master adds |
|---|---|
| D17, D19, D20 | `campaignTable.getFactionDiplomacy` → `factionDiplomacy`: state, hasTradeRights, hasMilitaryAccess, isProtectorate, protectoratePayment, tributeAmount, tributeDuration, factionStanding, numTurnsWar/Allied/Ceasefire/Trade/Access, numEmptyThreats, isTrustWorthy |
| R11 | `factionStruct.autoManageAll/Buildings/Recruitment/Taxes`; `aiProductionController.isAutoManagedTaxes`, `setExtraBias` |
| R14 | `factionStruct.setCapital` |
| W5, W7, N2 | `armyStruct.canStartAssault`, `liftSiege`, `liftBlockade`, `canRetreat` |
| W14, W20 | `character.joinCrusade/leaveCrusade/joinJihad/leaveJihad`; `crusadeStruct` targets, joined factions, rewards |
| C5 | `characterRecord.setAsHeir`, `isHeir` |
| C6, W16, A8 | traits and retinue with their text: `traitLevel.description/effectsDescription`, `ancillary.description/effectsDescription`; `characterRecord.deathType` |
| R20, R21, W3 | `settlementStruct.publicHealth`, `plagueDuration`, `maxHoldoutTurns`, `readyToSurrender`, `canConstructBuilding` |
| D6 | `factionStruct.revealTile`, `setTileVisibility` |

Still missing in master: an active-mission list (C3; only `missionDetailsStruct` on events), retrain
(R9), repair (R3), hiring mercenaries (R18), diplomatic proposals (D4–D10, D18), siege-equipment
building (W4), games and races (R13). Those stay screen clicks or route 2 (direct memory reads).

Cost of moving to master: core types are renamed (`stackStruct` → `armyStruct`, `namedCharacter` →
`characterRecord`, and more), so the bridge needs a port, and an unreleased build is less proven.

## Scope: decisions left out on purpose

| What | Why | the author decides |
|---|---|---|
| The battle map: deployment, formations, stakes, weather, unit orders, pursuit | every battle is auto-resolved under autoplay; nobody fights on the battle map | keep out, or let rulers choose "fight" vs "auto-resolve" and take a human-like battle AI |
| Camera, lists, mini-map, show-AI-moves, speed | interface only, no effect on the campaign | — |
| End turn | the turn loop ends each turn once every ruler has answered | — |

## Defects found in what the ruler sees today

| # | Defect | Evidence | Fix |
|---|---|---|---|
| X1 | The screen reader often reads one scroll many times and misses the other messages that turn | scratch turn 67: 9 messages arrived (log: ids 51, 1, 40, 92, 104, 27, 15, 68, 211); all 9 readings are "Obtain Trade Agreement". Turn 66: the Pope's death read 8 times. 59+ repeats in 333 readings | each message must be read once, from its own scroll: find why the same scroll stays on screen |
| X2 | Event message ids don't index `event_titles.txt` in file order | id 40 came 50 times; file order makes it "city_sacked" | find EOP's / the game's event enum (probe), then name every message by id with no screen read |
| X3 | Sixteen news events were cut after a crash | turn 67 crash on the third event fired | add one event at a time, watched live |

## Freeze probe (scratch, France, turns 93–105, 2026-10-25)

`factionStruct.freezeFactionAI = 1` set live through the bridge's control file (`stratmap.game`;
`gd` isn't visible there), then back to 0.

| What | Frozen |
|---|---|
| Turns end | yes, normally |
| Stance changes by the faction's AI | none (one every turn before) |
| Building, recruiting | none: queues stayed empty, treasury rose 447 → 17,642 |
| Army movement | none after paths set before the freeze ran out (three armies finished paths, turns 94–96) |
| Economy | nobody managed it: income fell to −4,500 a turn (famine, lower taxes and trade, upkeep unchanged) |
| Unexplained | a new two-unit army, Captain Rene, appeared on turn 103 |

Verdict: the freeze does stop the faction's AI. Everything the ruler doesn't order stops with it, so
a frozen faction whose ruler can't build, recruit, tax and manage upkeep slides into bankruptcy.
Freeze only at full coverage, as planned.

## The game's AI controls (for the freeze)

| Control | What it does | Note |
|---|---|---|
| factionStruct.freezeFactionAI | stops the faction's AI | probe: what still happens |
| aiProductionController.isAutoManaged* / autoManagePolicy | the governor AI for one settlement | possible fallback for rows the ruler doesn't own |
| campaignTable.restrictAutoResolve | battles | for W8 |
