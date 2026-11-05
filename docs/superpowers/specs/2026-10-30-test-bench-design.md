# Test bench: QA suites for Parley in the real game

Date: 2026-10-30. Status: draft for the author's approval; builder-checked. Command name: `just qa` (see "Settled").

## Why

Parley is software. The live campaign is production. Until now it has also been the only test bed,
so a fix like #255 (the spy report scroll) can't be proven until one of England's spies happens to
succeed (a 25% roll) in a campaign whose rulers may not even be playing. Fixes wait hours, or batch
up unproven, which is what failed on 10-29.

The rule "campaign is the test bed" (memory `live-check-each-fix`) exists because 15 fixes that
passed only fixture tests failed together live. The bench honours that rule: it runs **in the real
game, through the real bridge**, one fix at a time. It only stops relying on chance and on the
calendar.

The author's framing (10-30): treat the game like any other piece of software. We're the dev and QA shop.
Group everything a ruler can do into suites and test them. Cheat freely (money every turn,
invincible factions) to make the tests fast.

## Goals

1. **Prove a fix in minutes.** A suite sets up its scene on turn 1 (spy next to an enemy town, fleet
   beside a port) and runs its cases in a few turns, with no waiting on chance or AI behaviour.
2. **Cover every order type and the popups**, grouped into suites, each case with a pass/fail
   against observable evidence.
3. **Never harm the real campaign.** Run the bench and come back to the real run exactly where it
   was.
4. **Regression runs.** After any bridge change, one command runs every suite (or one), and the
   result is a table.

## Non-goals

- Not a replacement for the live campaign as the **acceptance step**. A fix is done when the bench
  passes and it has been seen in the real campaign (or, if it can't arise there soon, the author accepts
  the bench result). The PR says which.
- Not testing strategy quality (that is the lessons/review work and SAGA).
- No new game mod files: setup goes through EOP calls from the bridge, not edited campaign files.

## Anti-goals (a failure even if it "works")

- **The bench overwrites the real run's resume point** (the shared per-turn `Autosave.sav`).
- **The real run's loop or crash-watch acts on the bench** (writing orders into it, or relaunching
  into it).
- **A fast loop that lies**: bench setup tools that are broken but report pass.

## Suites

Grouped by what the orders touch. Order types are from `parley/protocol.py`.

| Suite | Cases (order types and behaviours) |
|---|---|
| `covert` | recruit_agent (spy, assassin), move_agent, spy (settlement, character), assassinate, sabotage, **spy report scroll closed (#255)** |
| `envoys` | recruit_agent (diplomat, princess, merchant), move_agent, bribe (army, agent, settlement), marry, merchant on a resource |
| `diplomacy` | set_stance war/peace/alliance, send_gold, cede_settlement, messages (`say`), AI offers and the diplomacy screen left open |
| `field` | move_army, march_on, attack, withdraw, merge_armies, merge_units, disband, hire_mercenary |
| `siege` | besiege, besiege + assault, siege equipment kept (#235), siege refused across sea (#222) |
| `navy` | board, land, blockade, fleets carrying armies |
| `towns` | build, repair, recruit, retrain, set_tax, steward garrison backfill |
| `popups` | papal election and results scrolls, faction overview, mission results, event scrolls, "Victory Conditions Failed" |
| `smoke` | the bench's own tools: createCharacter, spawnArmy, teleport, money top-up, loadGame. **Runs first in every bench run; a failed smoke case aborts the run.** |

Each case states:
- **setup** (EOP calls that place what it needs). An entry `{ lua = '...', bind = "spy" }` keeps
  the line's control result as `$spy` for later setup lines, orders and expects. The game names a
  spawned agent from the faction's name list and ignores the case's name (live 10-30), so
  `spawn_agent` returns the agent's report id and cases refer to it only through the bind.
- **orders** (scripted, per turn),
- **expect**: one or more of: the order's `OrderResult.ok`, a field in the next `state.json`
  (`equals` a value, or `at_least` a number), a bridge log line (regex), a popup gone within N
  seconds; `any_of` passes on any one of its expects. `order_ok` alone never passes a case, nor
  does an `any_of` with an `order_ok` alternative,
- **timeout** in turns.

## How a bench run goes

1. `just qa <suite|all>`.
2. **Park the real run.** Stop the real game's loop, bot and crash-watch. Copy the real run's newest
   save to a kept name (`parley_keep_<game_id>.sav`). **The bench refuses to start until that copy
   exists and matches**: structure, not convention. Write a bench lock file naming the real game.
3. **Start the bench game**: its own `game_id` (`bench-<suite>`), its own turn folders and `.db`,
   `playtest_funds` for the bench faction (money every turn), its seats on `script:` brains. A new
   grand campaign, or a bench start save once one exists (left to the builder).
4. **Smoke cases** first, then the suite's cases: EOP places agents and armies next to their targets
   (`createCharacter`, `spawnArmy`, `teleport`), scripted orders go in, autoplay ends turns, and the
   checker matches each expectation.
5. **Report**: a table (case, pass/fail, evidence line, turns taken) in the terminal and in
   `runs/bench/<date>-<suite>.md`. A failed case keeps its turn folder for diagnosis.
6. **Restore.** `loadGame` the kept save, restart the real loop, bot and crash-watch, remove the lock.
   `just qa-restore` does just this step and is safe to run twice (after a crash mid-bench).
   If the load call fails before any load reaches the game (the call errors or logs
   `qa: load failed`, with no `qa: load ok`), what happens depends on whether the run changed the
   game. The lock records the bridge log offset at the run's start.
   - **Provably unchanged** (no `qa: <helper> ok:` and no `autoplay: ending turn` since that
     offset, as when step one failed live at 17:12): the restore aborts. It restarts the real
     loop, bot and crash-watch, moves the lock to `qa.lock.aborted-<stamp>` and the keep to
     `parley_keep_<id>.restored-<stamp>-aborted.sav` (never pruned).
   - **Anything changed, or no offset to prove otherwise**: the real loop and crash-watch stay
     stopped (the game is on the QA-altered campaign). The lock is kept with `load_failed`, the
     keep is not renamed, and the error says to load the keep by hand or fix the load and run
     `just qa-restore`.

## Rulers (phase 2)

Phase 1 proves the game machinery with scripted orders. Phase 2 adds one ruler case per suite: an
LLM seat with a directive ("only train spies and spy on Nottingham; build and defend") must
produce accepted orders of the suite's types within N turns. That checks the prompt and the
validator, not just the bridge. The directive goes through the existing `just tell` / game-note path
or a per-seat persona; left to the builder.

## Constraints

- Real game: Steam Windows build under Proton with M2EX/EOP (project CLAUDE.md). One game instance at
  a time.
- Bridge changes are Lua in `lua/parley_bridge.lua`, tested with `tests/test_lua_bridge.py` against
  `tests/lua/fake_game.lua`. Bench code needs the same fixture tests as the rest.
- EOP batch reads in one event have crashed the game (memory `eop-events-one-at-a-time`): setup
  calls go one per tick, as the popup code already does.
- Logic in scripts and Python, one-line recipes in the justfile.
- The four EOP calls (createCharacter, spawnArmy, teleport, loadGame) are unused so far
  (docs/EOP-COVERAGE.md). Their exact signatures must be read from the EOP docs before use.

## Decided

- Suites as listed above; scripted seats in phase 1; the real campaign remains the acceptance step
  (the author and Uncle J, 10-30).
- Cheats allowed: money every turn (`playtest_funds` exists), spawned and teleported units (the author).
- The two HIGH pre-mortem findings are requirements: the kept save gate, and parking the real
  loop and crash-watch during a bench.

## Settled after the builder check (Claude's calls, flagged for the author)

1. **Name:** `parley/bench.py` is already the seat benchmark. The new tool is **`qa`**: `just qa
   <suite|all>`, `just qa-restore`, module `parley/qa/`, results in `runs/qa/`.
2. **Autosave.sav:** it doesn't have to stay byte-for-byte untouched. Restoring from the kept copy is
   the guarantee (memory `saves-expendable`: saves may be overwritten in tests). After `loadGame` of the
   kept save, the real run's next turn autosaves and becomes the newest save again.
3. **Crashes:** a crash during a QA run **aborts the run and restores**; no relaunch into the bench.
   `relaunch_game.sh` gains a "load this named save" mode (Load Game menu, or Continue then
   `loadGame`), which `qa-restore` uses when the game isn't running. That is the most fragile part
   and gets its own smoke case.
   **A hang counts as a crash** (live 10-30 18:34: the papal election results scroll froze the game
   with its process alive). The game is hung when medieval2.exe is alive but the bridge log hasn't
   grown for `HANG_SECONDS` (240 s; crash-watch uses 480 s). Checked before each case and while a
   case waits for its turns: the case fails with `game hung/crashed at <time>: <last log line>` and
   the run goes to the restore. The restore relaunches a dead or hung game (`relaunch_game.sh`),
   waits for `bridge loaded campaign at turn N`, then loads the kept save; a load that times out is
   checked for a hang, and after a relaunch retried once.
   **Wine's crash dialog is a crash at once** (live 10-30 20:11: the "Medieval 2" message box kept
   medieval2.exe alive). `scripts/crash_dialog.sh` (a visible "Medieval 2" window between 150x60 and
   800x400) is checked on every `game_trouble` check and every crash-watch poll. It counts only when
   seen twice (two sightings 5 s apart; two crash-watch polls in a row), and crash-watch skips it
   for 120 s after its own relaunch.
   **A relaunch after a restore** continues the newest save, which is the QA game's autosave until
   the real game autosaves again. With `qa.last_restore` present, no `qa.lock`, and no save newer
   than its `newest_save_mtime`, `python -m parley.qa after-relaunch` (run by relaunch_game.sh)
   loads the newest `parley_keep_*.restored-*.sav` once the campaign map is up.
4. **Resuming the real run:** the in-flight turn is thrown away; the rulers are asked again from the
   kept save. No replaying of half-done turns.
5. **Dice rolls:** force them. Spawn agents with maximum skill (EOP character attributes/traits) so
   missions succeed almost always, and give each case a retry cap in turns. A case tests the
   behaviour under it: the #255 case passes when the spy report appears **and** is closed; a run
   where no mission succeeded inside the cap is "inconclusive", never "pass".
6. **Evidence:** `OrderResult.ok` alone never passes a case. Every case needs at least one
   independent check: a changed field in the next `state.json`, a game-side log line, or a popup gone.
   Smoke cases check the effect (`teleport`: the character's x,y in the next report).
7. **What gets parked:** the real turn loop, Discord bot, crash-watch, and Claude's campaign watch.
   The QA run uses its own loop and **no bot**; `say` is checked through the orders path and the
   outbox rows in the QA game's own `.db`. Nothing posts to Discord from QA.
8. **Bridge config:** the builder must find out whether the bridge re-reads its published config
   mid-campaign. If it doesn't, each switch includes a `reload-bridge`, and a check that the bridge
   reports the expected `game_id` before any order is written.
9. **"Invincible":** money every turn plus scripted seats that never start fights plus spawned
   garrisons. No further invincibility work unless a suite needs it.
10. **Phase 2 (ruler cases)** is a later spec. The case format reserves a `seat` field (`script` now,
    an LLM spec later) and a `directive` text, so phase 2 needs no format change.
11. **All suites in one run:** one park and one restore around the whole sequence. A failed smoke
    case aborts everything; a failed suite doesn't stop the next one.

## Left to the builder

- Case file format (TOML or JSON, next to `games/order-check.json`) and the checker's module layout.
- New campaign per run vs a prepared bench start save.
- Which faction the bench plays and where the scenes are placed.
- How loadGame is triggered (bridge command file, like reload-bridge) and how the menus are handled
  if loadGame needs the campaign map.

## The bench save: a fixed, quiet world (added 10-31)

Until 10-31 the bench parked the real run and ran its cases on the live campaign's world, so
whatever that world was about to do happened mid-suite (05:29: a Pope died during smoke and the game
crashed). Now every run starts from one fixed save, never a copy of a live campaign.

**The save.** `mods/parley/saves/parley_bench.sav` (in the real config's `mod_save_dir`, beside the
keep saves), recorded in `parley_bench.json` next to it: turn, faction, sha256, source file. The
runner (`parley/qa/runner.py`: `load_bench_save`, `_load_bench`) refuses to start, naming the recipe,
when the save is missing, has no record, differs from its sha256, is on turn 0, or plays another
faction than a suite. `newest_real_save` never takes it (nor a keep save) for the real campaign's.

**A run** parks the real campaign exactly as before (kept save, lock, loop and crash-watch stopped)
and restores it exactly as before. In between: the QA config is published, the turn held, the bench
save loaded (`M.qa.load`, confirmed by `qa: load ok` and `bridge loaded campaign at turn <recorded>`),
and the bridge writes the bench faction's report for the turn before the loaded one
(`M.qa.report(faction, turn)`, as a campaign on its map has). Cases take their targets from that
report and their own suite's, never from the live campaign. The lock gains `bench_save` and
`bench_loaded`; a restore whose load fails after the bench loaded treats the game as changed.

**The quiet world.** The QA config sets `freeze_others = true`: bridge.txt says `freeze=*`, and the
bridge freezes the game AI (`freezeFactionAI`) of every AI faction at its turn start ("<faction>:
game AI frozen" in the log). A case lists the AI factions it needs to act in `needs = ["france"]`
(an AI siege, an offer); the runner republishes bridge.txt with `thaw=<faction>` for that case and
without it for the next. A freeze or thaw takes effect at that faction's next turn start. Under any
config without `freeze=*` the bridge unfreezes an AI faction that isn't a frozen seat, so the real
campaign thaws whatever the bench froze.

**Making the save** (`just qa-bench-save`; the bridge can't write saves, `M2TWEOP.saveGame` fails
live, so it is the game's own save, as the keep save is):

1. With the real campaign running, `just qa-bench-save start`: parks the real run like a QA run
   (keep save, lock with `purpose = bench-save`) and gives the bridge a config with no seats and no
   autoplay, so it leaves the new campaign alone.
2. In the game: quit to the main menu, **New Campaign → Grand Campaign → England**, default
   settings (the long campaign). End turn 0 without doing anything.
3. On England's **turn 1**, before moving anything, `just qa-bench-save record --real
   games/local/<name>.toml` (the real loop is stopped, so name its config). It asks the bridge whose
   turn it is (`M.qa.current()` must say `england 1` or later), copies the game's newest own save
   (the turn-start autosave, which must be newer than step 1) to `parley_bench.sav`, writes the
   record, then restores the real campaign as `just qa-restore` does. With autosave off, save in the
   game and pass `--from <that .sav>`.

A turn-1 England start: few armies in the field, no Pope near death in a known campaign, and every
scene the suites build is spawned by setup anyway. Remake it (steps 1-3) after an EOP or M2EX
upgrade, or when a suite needs a different start.

**What can still vary between runs** (the save fixes the world, not the dice):

| Varies | Why | What a case does |
|---|---|---|
| Mission and battle rolls (spy, assassin, bribe, auto-resolve) | the game's RNG is not reseeded by a load | max-skill agents (`M.qa.skill`), a turn cap, `chance = true`: no success inside the cap is inconclusive, never pass |
| Natural deaths, births, coming of age, the Pope's death and the papal election | game rules, not faction AI: freezing doesn't stop them | turn cases stay few turns from turn 1; a case that must not meet a papal scroll is an instant case; the popup suite forces the scroll it tests |
| Random events (plague, rebellions, riots, disasters) | game rules | check the case's own scene only; never assert on a world-wide count |
| A frozen faction whose turn won't end | a frozen AI can't make the calls only it can (#release_frozen) | after 15 s the bridge unfreezes it for that turn ("turn still running after ... game AI unfrozen"); a case that sees that line in its window should treat AI moves as possible |
| Thawed factions (`needs`) | their AI acts as it likes | expect the effect with `any_of` or a turn cap and `chance` |
| Rebels | `slave` is an AI faction: frozen too | thaw `slave` in `needs` if a case wants rebels to move |
| The load's turn | the record is the bridge's turn when recorded | the load must log the recorded turn (or one less, as the keep load allows) or the run stops |

## Instant cases (added 10-31)

A turn case orders, ends the turn and reads the next report: up to 240 s a turn. Most bridge fixes
don't need a turn. Run9's three findings (a split to a far target does nothing; nobody marches out
of a besieged town; a character's tile lags the split that moved him) were each proven by hand
with control lines in seconds. `kind = "instant"` makes that a case (`games/qa/instant.toml`):

- **setup** and **act**: control lines, run in order, with `bind` as before. A setup line's
  `require` regex (polled for `within` s) skips the case as inconclusive when the scene didn't
  come about (a siege that didn't start), with the result as the reason.
- **expect**: `{ lua = '<query>', match / no_match / equals / below / at_least }` polled every
  half second for `within` s (10 by default), or `{ log = '<regex>' }` over the log since the case
  began. A failed case reports what the query last returned. A query that errors fails at once.
- **No turn ends.** The runner stops the QA loop, holds the turn with `paused.txt` (the bridge
  ends no turn and presses nothing, but still runs control lines), waits for the faction's own
  turn (`M.qa.current()`), runs the case and lifts the hold. A suite of instant cases starts no QA
  loop. If `autoplay: ending turn` appears during a case anyway, the case is inconclusive. The
  restore and the run's end lift a hold a crash left (only one that says it is the bench's).
- Cases share the game only when they say so (**isolation**, added 10-31 after phase 1's first live
  run: 30 cases' spawns filled every tile beside London, and a general one case withdrew into London
  led the next cases' garrison; 9 fails and 5 inconclusives came from that). A suite's `isolation`
  (default `"fresh"`) applies to each case unless the case sets its own. A fresh case starts on the
  bench save as recorded: the runner reloads it (`M.qa.load`, confirmed as the first load is) when any
  case ran since the last load, with the QA loop stopped and the turn held; when turns were played
  since, the QA games' turn folders go to the archive and the bench report is written again. A
  `"shared"` case starts on what the case before left (towns and diplomacy suites, refusals that move
  nobody). The first case of every suite starts fresh whatever it says. A failed reload ends the run
  (the restore follows). Cost: the live bench load takes ~4 s (08:00:21 -> 08:00:25, 08:06:21 ->
  08:06:25), ~6-8 s with the control round trips, about 45 reloads in an `all` run (~5-6 min on a
  16-min run); the report gives the count and time. A load also clears the bridge's kept mission
  outcomes and `M.qa.last`.
- `phase2 = "<why>"` on an instant case: the no-click run (`kind=instant`) reports it
  `skipped: phase 2: <why>`; a full run still runs it (an AI offer that won't come in a held turn, a
  merchant no town trains on the bench save).

Use an instant case when the behaviour shows inside the turn it's ordered in: moves, splits,
refusals, spawns, setup helpers. Use a turn case when it needs the turn to end: an order applied
at turn start, a mission roll, a report field, a popup after End Turn, the AI's answer.

Popups can't be instant: the hold stops the bridge's popup handling and the turn loop's alike, so
`games/qa/popups.toml` forces each popup in a turn case's setup (the Pope killed with
`character:kill`, a historic event, the faction overview's button) and lets the QA loop handle it.
`{ alive = N, after = '<regex>' }` (either kind) passes when the same game's bridge log has a line
N s after the first matching line, with no bridge load between: the papal crash check.

`just qa <suite> case=<name>` runs only the named cases (repeatable; smoke still runs first).
`no-smoke` skips smoke for instant cases alone, and only within 30 min of a whole smoke pass
(`<turn_root>/qa.last_smoke`). The report gives each case's wall time and the run's total.

## No clicks: `kind=instant` (phase 1, 10-31)

The author's rule: never click the screen when EOP/Lua can do it. Phase 1 runs every case that needs no
clicks on the real game; the click-dependent cases come later, overnight.

`just qa <suite|all> kind=instant` (`python -m parley.qa run ... --kind instant`) runs only the
instant cases. Each turn case gets a report row `skipped: needs a played turn (click phase)` (a
skip is no failure). No QA turn loop starts: the loop's popup thread is what clicks, and only it
answers turns. The turn is held (paused.txt) from before the bench load to the end of the run.
Smoke's instant case `helpers` (free_tile, spawn, teleport, where, skill in one held turn) gates
the run; its turn cases are skipped like any other, so an instant run writes no `qa.last_smoke`.

The whole run, restore included, is a no-click run: the runner sets `PARLEY_NO_X_INPUT=1`
(parley/xinput.py), which every X-input path checks and refuses with
`X input refused in a no-click run: <what>`:

- parley/popups.py: `click`, `_clear_pointer` (so `screenshot`), and `_xdo` for any xdotool verb
  that isn't a read;
- scripts/relaunch_game.sh, at its top, before it kills anything (exit 3);
- the runner's relaunch and QA-loop starters, real or injected (a QARunError).

A crash or hang during an instant run fails the case and goes to the restore, which can't relaunch
(that clicks): it stops with `restore failed at loaded; lock kept`. Run `just qa-restore` (no
variable) to relaunch and restore. The real campaign's loop and crash-watch, restarted by the
restore, get an environment without the variable. Reading the screen is not input:
scripts/crash_dialog.sh (xdotool search/getwindowgeometry) still runs.

The bench save without the menu: `just qa-bench-save record --from <save>` with no `start` before
it parks the real run, copies the save to the bench save, loads it through EOP (`M.qa.load`,
loadGame), reads its faction and turn from the loaded game (`M.qa.current()`: must be England, on
turn 1 or later), records turn, faction and sha256, and restores. It is a no-click run too. Use a
copy of an England campaign's save made on England's own turn (an autosave is). `start` then
`record` (a new campaign through the menu) still works as before.
