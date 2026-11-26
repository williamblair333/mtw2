# Changelog

All notable changes to this project are recorded here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### 2026-11-24/26: clean install proven, papal-vote crash fixed, game AI recruiting reported and switchable

#### Added
- Order `game_ai_recruiting` on/off: with it off, the bridge holds the realm's recruitment pools at 0 from the AI's unfreeze to the faction's next turn start (`pool_hold.json`), then gives them back (#734).
- The prompt reports what the faction's own game AI trained since the last turn and the upkeep it adds, from EOP's `onUnitTrained` (#732).
- `docs/upstream.toml` and `scripts/upstream_check.py`: our upstream issues and PRs, checked before every public publish (preflight gate `upstream-current`) (#736).

#### Fixed
- Turn-4877 crash: an offer's "accept" pressed a vote button on the papal results scroll; class guards in `open_choices`, `choice_buttons` and `press_choice` (#728, `tests/test_choice_not_papal.py`).
- `scripts/install_eop.sh` writes EOP's config files when missing; proven on a fresh Debian 13 VM (#722).
- France's prompt under 60 KB: garrisons folded into their town's line, "str N" defined once per section (#730).

#### Changed
- Docs rewritten in plain wording for players; stale screen-click claims removed (#724, #725).
- mtw2's VM memory gate retired; the Refinery's ram-gate covers it (#727).

### 2026-11-22/23: smaller prompts, papal scroll closed by element, three watch wakes fixed at the cause

#### Fixed
- The papal results scroll closes by its `SCROLL_CLOSE_GADGET` (fork level 6 `activate()`), not an Escape request (#693).
- The prompt lists only the dead who matter and prints each unit price once (#692); towns list buildings and recruits as "same as X, plus/without" (#696): France's settlements 92 -> 61 KB, the prompt 168 -> 136 KB, lossless by test (`tests/test_prompt_compact.py`).
- The bench reloads a stale bridge before it runs, and refuses if it can't (`parley_build.txt` vs `bridge_loaded_build.txt`, #694).
- `parley/trends.py`: an applied-share fall needs 3 refusals of one order type in the newest 3 turns (#698); England's varied mistakes woke the watch twice.
- The prompt prints the map's bounds once; `M.to_coast` carries a move_army/move_agent aimed at sea with land 1 tile off to that land, noting it (#699).
- A load under `qa.lock` writes the missing ruler report once the lock goes, instead of skipping it (#700; France waited 720 s at turn 3492).

### 2026-11-21: no screen clicks left; every census click kind benched with clicks refused

#### Added
- Click coverage, completed: `games/click-coverage.toml` + `scripts/click_coverage.py` (`just click-coverage`); every census click kind maps to a passing `--kind noclick` case (#682–#686, #689). New cases: `popups/minimized_message_reopened_by_element` and `popups/stuck_turn_reopens_minimized_message` (`M.qa.stuck_try` drives `try_dismiss`).
- Preflight gate `waits-wake-on-stall` (`scripts/preflight_waits.py`): refuses a `pgrep -f` that matches its own command line and a wait loop with no clock (#683).
- `scripts/campaign_watch.sh` CLICK wake: a new "X input refused" line, matched by timestamp across the log and its rotated copy (#689).

#### Fixed
- A load waiting on the bench no longer waits for popup captures (`captured()`, #682).
- A re-issued `merge_armies` whose walk already arrived reports done (`M.walking_merges`, #687).
- Mercenary pools: each report entry names its pool, the report says it's shared by the region's armies, and `validate_orders` counts hires per pool (#688).
- The watch re-checks for a no-bot host each time it finds the bot down (#690).

#### Removed
- Every screen-input fallback (#689): `parley/xinput.py`'s guard is always on, `popups.click`/`press_escape` refuse, the Lua stuck path writes no "minimized" request, `relaunch_game.sh --clicks` is gone, and the `_decide` icon click and `Popups._reopen` are deleted.

### 2026-11-19: the campaign resumes after tc's nightly power-off

#### Fixed
- `scripts/boot_resume.sh` puts `~/.local/bin` on PATH. The desktop autostart's PATH lacked it, so at 05:44 the resume logged "just: command not found" and the campaign idled from the 11-15 23:59 power-off until a hand restart on 11-19.
- `scripts/relaunch_game.sh` fails at once when the game exits while loading (seen running, then gone 15 s). On tc at 13:30 the game hit "unspecified error and will now exit" after the main menu map, and the relaunch waited out its whole 240 s before crash-watch retried.
- `tests/test_boot_resume.py`: the new case runs with a PATH holding only the tools the script uses. Its red run, on a host with `/usr/bin/just`, had started a real crash-watch there.

### 2026-11-15 (evening): workarounds fixed at their cause, offers answered with no click

#### Fixed
- Open windows come from our EOP fork's `gameSTDUI.getOpenUiElements()`, not an ffi memory walk or a 4,012-name probe. The siege layout names parts at any depth, and the dead retrain click job is gone. Closes W24, W25, W15 and W29 (#642).
- EOP fork #9 (level 2): `getSubElement` and `elementName` check every pointer, so a closed window's stale part is nil, not a crash.
- EOP fork #10: the zip ships no `eopData/config` and names the launcher `M2TWEOP GUI.exe`. `install_eop.sh` writes Parley's `uiCfg.json` keys after every unzip (`python -m parley.relaunch ui-cfg`). Closes W53 (#643).
- The main menu's background map is logged as "main menu map loaded" and never treated as a campaign. Relaunch and the QA runner drop their turn > 0 filter, and the reload's console toggle is gone. Closes W47 (#644).
- EOP fork #11 (level 3): `getOpenUiElements` lists message scrolls, which hang under their message icon, not strat_ui. Offers (marriage, suitor, adoption) are answered with no click and no Escape: the turn loop writes `<req>.answer` and the bridge presses the check or X by element (`M.press_choice`), bound to the request's own scroll (`M.bind_scroll`). Closes W21 and part of W30 (#645).
- No pre-marriage: `M.marry_live`, `M.loaded_fresh` and the `marriage_offers` switch are gone, so the game's own offers reach the ruler. Closes W03 and W05 (#646).

### 2026-11-15: fixing everything we can

#### Added
- `M.open_ui()` reads the game's own list of open UI elements (Steam exe global `0x02c2bc2c`) with ffi; a stuck turn logs what is on screen (#623, #624, #627).
- Our EOP fork: `gameSTDUI.getOpenUiElements()` (fork #6), live-proven on finance_scroll and its buttons.
- `just resume-at-boot <name>`: a login autostart resumes the campaign (#622, #630).
- `just install-eop-zip <zip> <sha256>`: swap the campaign onto another EOP build safely (#628, #631, #633).
- STANDARDS `fix-what-we-can`.

#### Fixed
- Claude seat: the prompt goes on stdin; France's 131 KB prompt broke argv and stopped the loop (#632).
- Bridge: the queue reads every item on the fixed EOP (#620); a reload leaves the console shut on master (#621); the fault catcher reports on after a reload (#625); overlay text isn't doubled on the fixed EOP (#629); the nearest land named for a move is never a foreign town (#618); past the turn limit the report says so (#617).
- Review fixes: open_ui 48-byte read check, desktop Exec without shell syntax, imgui_fixed not cached before a map (#630).
- EOP fork: ImGui text as `%s` (#2), tile.isLandConnection/isSeaCrossing restored (#3), getBuildingInQueue 1-based (#4), splitArmy nil on a no-op (#5), CI publish idempotent and concurrency (#7).

### Fixed (2026-11-14, afternoon)

- A second `merge_units` on the same army in one turn is refused: one merges every group (live, England sent
  four for garrison:York; the bridge refused three and the applied share fell to 73%).
- Bench: navy landings expect `^land ok` (#607); `forced_ai_siege` takes message 39 however it's logged (#608);
  `papal_election_vote` is `needs_click` (#611).

### Added (2026-11-14, no-click play)
- `just qa <suite> kind=noclick`: every bench case, turn cases too, with all screen input refused; `needs_click`
  marks a case whose subject is a click. `just click-census`: every click or Escape the turn loop makes, by
  message event. `docs/no-click-challenges.md`: what still needs a click, with leads and how to prove a fix.

### Fixed (2026-11-14)
- A land order lands one step ashore (a farther tile was ignored by the game yet reported done); a landing not
  shown yet is pending, not refused. The bench turns suitor offers off. `M.qa.force_ai_siege` starts a siege. In a
  full QA run the case that ends the campaign runs last.

### Fixed (2026-11-14, a load with no report)
- A load whose turn has no report from the turn before (a new run's first save, its folders archived) left the ruler nothing to answer; autoplay waited its 720 s and the turn went by with no orders (live 11-14 06:16, run 11 at turn 5). The bridge now writes each seated faction's missing report once the turn loop has made its folder (autoplay only; not under QA).

### Fixed (2026-11-14, merge_units)
- The report's troops carry each unit's armour and weapon level and whether merge_units leaves it alone (`held`: a general's bodyguard or a unit retraining), from the bridge's own grouping key. The merge_units check and the prompt's "merge_units would combine" line now pair units only within one type and armour/weapon level, as the bridge does; the troops line shows upgrades (`Pike Militia (armour 1) 64/75`). Live 11-13/14, France sent merge_units 20 times on two armies whose worn pair the bridge wouldn't combine.

### Changed (2026-11-13, order checks)
- `merge_units` is refused before it reaches the game when the army has no two under-strength units of one type (France repeated it 21 times in half an hour).

### Fixed (2026-11-13, marriages)
- The bridge marries family men only: it had been giving wives to agents and captains, whose records the game frees at their death, so each such wife's own death message read a freed record (the 00eff4db crash).

### Fixed (2026-11-13, stale spouses)
- The 00eff4db crash (turns 272, 640, 1252): a natural death's message copied the dead character's spouse's name from a freed record. At every faction's turn start the bridge now clears a spouse pointer that no faction's records list, and logs who it was.

### Fixed (2026-11-13, army ids)
- An order naming "Captain X" no longer finds a fleet "Admiral X" listed earlier: the bridge tries the exact id before the title-free match (France's march_on was refused as "a fleet" four turns running).

### Fixed (2026-11-13, agent missions)
- One agent mission per target per turn: the order checker and the bridge both refuse a second bribe, assassination, spy or sabotage on a target already ordered this turn. Live at turn 1072 a bribe won a Spanish captain over and the same turn's assassination of him crashed the game.

### Changed (2026-11-13, EOP)
- tc runs the author's EOP fork build (`author/M2TWEOP-library` #1, pre-release `build-553d2c46...`) instead of upstream master b525628: EOP's minor-settlement cache is dropped each faction turn start and after every battle, so it no longer hands EOP's AI freed settlement pointers (crashes at turns 812 and 265). The old files are kept as `*.bak-b525628`.

### Added (2026-11-13, diagnostics)
- `battle sides: ...` in the bridge log before every auto-resolve press (`M.battle_sides`): each side's armies (faction, units, leader, tile), `NIL` for an empty one. For the 00612ea6 auto-resolve crash (turns 808/809), which reads a battle side's missing army.

### Fixed (2026-11-13, 10:24)
- Log rotation killed a healthy game: `rotate_logs.sh` renamed the bridge log during a long AI turn, the silent bridge left none, and crash-watch read the empty timestamp as midnight (37445 s old). The game, busy, missed the probe and was relaunched. Rotation now starts the new log with a stamped line, and crash-watch reads no stamped line as no age.

### Added (2026-11-13, tools)
- `scripts/pdbsym.py`: names DLL offsets (as fault-stack.txt prints them) from a PDB's public symbols, standard library only.

### Fixed (2026-11-13, turn 705)
- Turn 705 crash loop (`c0000417`, 3 of 3 from one autosave): the overlay passed the ruler's note to `ImGui.TextWrapped`, which reads it as a printf format; England's "80%." is an invalid directive and the CRT aborted the game. Text for ImGui now goes through `bridge.imgui_text`, which doubles every `%`. Found from the fault catcher's stack (EOP's `TextWrapped` -> `ImFormatStringToTempBufferV` -> ucrtbase).

### Changed (2026-11-13)
- The fault catcher records every error-class exception (0xC..., with its code), not only access violations; crash reports take Proton's last error-class exception too. Turn 705 died of `c0000417` (msvcrt `_invalid_parameter`) and its report said "none found".

### Added (2026-11-13)
- The bridge's access-violation catcher (`M.fault_catcher`, bytes from `scripts/fault_catcher_stub.py`): a machine-code vectored exception handler records the last AV (address, registers, up to 4 KB of the faulting stack) into `parley_turns/fault.bin`. Crash reports decode it into `fault-stack.txt` and a `stack:` line that names the callers and says whether it matches Proton's eip. Off with `fault_catcher=0` in bridge.txt. For the twice-seen crash at `eip=00eff4db` (turns 272 and 640), a ref-count copy with 1373 callers.

### Fixed (2026-11-13)
- `just watch` started on a host without the game (no medieval2.exe, no crash-watch, bridge log 6+ h old) now exits `NOT HERE` instead of a false STALL on a dead local log.

### Fixed (2026-11-11, unattended live run on the test laptop)
- Turn 246/247/252 crash: an admiral dying of old age crashes the next round. `M.spare_admirals` (`lua/parley_bridge.lua`) holds seated factions' admirals at 50 (#564).
- Turn 124 crash loop: EOP's campaign AI is off at every load unless bridge.txt has `eop_ai=1` (#574).
- `scripts/crash_watch.sh` relaunches after a defeat scroll leaves the game at the menu (`scripts/left_to_menu.sh`, #567) and after a turn stuck 20 tries (`PARLEY_STUCK_RELAUNCH_TRIES`, #572).
- False watch alerts: a stuck line before a reload (#570), a turn not applied yet (#571), and a share fall with fewer than 3 refusals (#577) (`scripts/campaign_watch.sh`, `parley/trends.py`).
- An army with a worn unit says what `merge_units` would combine (`parley/prompt.py`, #578).

### Added (2026-11-11)
- `scripts/crash_report.py` keeps Proton's SEH trace around the fault (`proton.log`, `meta.fault`; `PARLEY_PROTON_LOG`, #561).

### Fixed (2026-11-10, afternoon)
- `handlers.set_tax` reads the level back and fails the order if the game kept the old one (#544).
- A campaign load writes `heartbeat.txt` for the turn it loaded, so an older save gets its turn folder and report (#545; proven live 14:16).

### Fixed (2026-11-10, morning)
- Turn-start crash: `M.marry_live` (`lua/parley_bridge.lua`) marries nobody while a family offer is pending (#538; proven live 07:16).
- `parley/seats/ollama.py` sends `num_ctx` sized to the prompt (#537).
- `scripts/relaunch_game.sh` waits for Steam to start the game (up to `PARLEY_STEAM_START_TIMEOUT`, 900 s) before the 240 s load wait (#539).

### Changed (2026-11-06, midday)
- Forced events (`games/forced_events.toml`, `games/qa/forced.toml`, `tests/test_forced_events.py`): 19 of 34 forced by the game's own reaction (#528-#533). Turn-start breadcrumbs in `lua/parley_bridge.lua` (#535). Live run parked on the author's order; rulers move to the test laptop next (HANDOFF).

### Decided (2026-11-06, early)
- Marriage-offer crash: marry the human slot's single men at turn start instead of answering the scroll (PR #519, `M.marry_live`, `autoplay.marriage_offers`, bench case family/single_men_married_in_advance); not yet merged or proven on the bench.

### Added (2026-11-05, night)
- Edge and characterization tests, test only (#504-#514): dashboard (empty pause file, newest three crashes), rotate_logs before any campaign, trends with an old restore, and `just qa`'s exit code with quarantined cases.
- `scripts/rotate_logs.sh` (`just rotate-logs`): the bridge log and logs/*.log kept under PARLEY_LOG_CAP_MB; the campaign watch runs it every 10 min; game.sh opens the turn and bot logs for append (#438); crash-watch runs it too, so it runs whenever a campaign does (#460).
- The campaign watch wakes on a new crash report (CRASH), even one crash-watch recovered (#463).
- A crash report lists the orders applied at the turn's start and copies each orders.json (#466).
- `games/qa/diplomacy.toml` frozen_rival_offers_nothing: the forced case the AI-offer hold needs; not yet run (#468).
- `games/quarantine.toml` (parley/qa/quarantine.py): a flaky case listed there runs and is reported, but doesn't fail the run (#479).
- `just stop` pauses the campaign (paused.txt) so autoplay ends no turn unordered; `just play` lifts only that pause; the QA runner's stop is unchanged (#473); plain stop exits 0 again (#485).
- `just dashboard` shows why the campaign is paused (#484) and each ruler's "unknown army" refusals (#498).
- `games/qa/family.toml` marriage_offer_answered and `M.qa.marriage_offers_on`: the marriage-click crash's repro, expected to fail until fixed; not yet run (#470); `M.marriages_on` is false before setup (#475, from a cross-model review).
- `tests/test_turn_cases_need_turns.py`: a turn case must check something only a played turn shows (#465).
- `tests/test_standards_evidence.py`: STANDARDS evidence the Refinery checker can read without crashing (#500; cause and fix in HANDOFF, #501).
- Trend alerts posted once each to the audit channel (`Orchestrator._post_new_trends`, #439).
- `games/qa/quiet.toml` quiet_world_held: the quiet world read back from the game after a bench load; the bench proof `games/interrupts.toml` had named since 11-01 but nobody built (#448, #449). Bench: pass.
- `games/ruler_eval`: six real run-9 turns as a fixed ruler-eval set; `ruler_eval --set`, `just ruler-eval-fixed <specs>` (#455); each seat's kept orders counted by control area (#458).
- Preflight gates: tests piped through tail before && commit/merge/reload are refused (#445); a commit with code and no test is refused unless it says `no-test: <reason>` (#450).

### Fixed (2026-11-05, night)
- QA archive moves the QA game's database with its turn folders; stale per-turn message counts failed diplomacy/orders_next_report (#440).
- towns/next_turn_delivers passes on a build still queued behind the town's current one; a build is "done" only if the queue grew (#441).
- popups/papal_election_no_vote gets 3 turns to show 30 s alive (#442).
- smoke: teleport and skill turn cases dropped; the instant helpers case checks them (#443, test fix #444 after #443 merged red).
- Lessons reviews start once every ruler has answered and run one at a time (#446).
- Adoption offers off on the bench (familyTree.maxAdoptionAge 0), back on for a real load (#447).
- The report's unreadable queue head says a done build is in the queue (#451).
- Trends measure an answer from the QA restore when a bench run parked the campaign in between (#452).
- A near-miss army name may drop "admiral" or "captain": "Nigel" finds "Admiral Nigel" (#453).
- An AI-run faction's "unknown army" refusal names its own game AI as the likely cause (#489), and
  its ruler's role text says army ids change between turns (#491).
- A turn's lessons reviews start once even when both rulers answer together (a lock, #454), and are
  staggered one ruler a turn so each runs in the quiet after everyone answered (#457).
- A missing popup reader (no agy/claude installed) reads nothing instead of an ERROR per popup (#456).

### Added (2026-11-05, late)
- `just dashboard <game>` (`parley/dashboard.py`): heartbeat and newest report (who is still deciding), loop/qa.lock/pause, newest 3 crash reports, per-ruler applied/refused/late counts with trend alerts, STANDARDS gaps (#428).
- `games/qa/diplomacy.toml` two_offers_on_their_turns: two AI offers on their own turns, declined then accepted; a case's `choice` may be a list answered in order (#434). Bench: pass.
- `games/qa/covert.toml` spy_into_own_town_with_foreign_spies: a guard for the 16:38 live crash; it did not reproduce it (#432). Bench: pass.

### Fixed (2026-11-05, late)
- `lua/parley_bridge.lua`: an unknown army says why; a garrison id names the town's new owner (#429).
- `games/qa/popups.toml` papal_election_no_vote accepts either path a no-vote faction gets: the 202 notice and its check, or only the result 203 (#430). Bench: pass.
- `scripts/game.sh`: no bot token means no bot, not a failed start or QA restore (#431).
- `scripts/campaign_watch.sh`: DOWN when crash-watch isn't running (#433); no DOWN while a QA run holds qa.lock under an hour (#435); a stuck campaign-over screen is LOST (#436).

### Fixed (2026-11-05, evening: the live campaign on the test laptop)
- `games/qa/towns.toml`: next_turn_delivers builds in the garrison town; the building stands within 3 turns (#418).
- `parley/bridge.py`: the turn loop answers each faction's latest report only (the one the game wrote last); stale reports from a relaunch no longer starve the real turn (#419, #424).
- `tests/test_relaunch.py`: fakes `loginctl`, so the tests no longer fail while the host's screen is locked (#419).
- `scripts/game.sh`, new `scripts/run_loop.sh`: `just run`, `play` and `restart-loop` borrow the desktop's display when started over ssh (#420).
- `parley/popups.py`: says once at start when the popup reader's command isn't installed (#421).
- `lua/parley_bridge.lua`: an agent refused on its target's tile is told to move one tile away first (#422).
- `parley/prompt.py`: an own army with no units left is said to be going (#423).
- From a cross-model review (agy): the restore's wait for the player's turn survives an unanswered call; `M.setup` clears the bridge's popup lists on a load; small `pcall`/`record_alive` fixes (#424).

### Changed (2026-11-05, phase 2: bench speed) — merged as #416
- `parley/qa/runner.py`, `parley/config.py`, `lua/parley_bridge.lua`: bench-only short waits: decision answer 60 s, End Turn hold 90 s, turn timeout 180 s (#391).
- `lua/parley_bridge.lua`: control requests answered within frames, not on the 2 s tick; a frozen AI let go after 1 s (#393).
- `parley/qa/runner.py`: a `case=` run gates on smoke's instant cases only (#396); `parley/qa/control.py` polls every 0.1 s (#401).
- `parley/qa/runner.py`: prints when each turn report was judged and how far the log reached (#406).

### Fixed (2026-11-05, phase 2: played turns) — merged as #416
- `parley/qa/runner.py`: reads the Wine-written bridge log with `\r\n` made `\n`; expects ending in `\n` or `$` never matched (#407).
- `parley/qa/runner.py`: a load clears the old campaign's `popup-*` request files; the turn loop kept answering stale ones, clicking under a pending End Turn (crashes 11:57, 12:15) (#411).
- `parley/qa/runner.py`: the bench holds End Turn for every offer within its 90 s cap (#410, replacing #397's diplomacy-only hold); a restore waits for the player's turn under the QA config (#409).
- `lua/parley_bridge.lua`: the bench marries England's single men and every general it spawns, so no marriage offer arises (`characterRecord:marryWife`); the marriage age limit is set off on the bench and restored on a real load (#412).
- `lua/parley_bridge.lua`: a spawned or launched admiral gets his ship as bodyguard (`setBodyguardUnit`), so the game keeps him; a spawned general draws a name nobody else has (#398).
- `lua/parley_bridge.lua`: `characterRecord.isAlive` read as the property it is (#408); the AI-turn stuck watcher stops deferring to an open decision past its cap (#402).
- `lua/parley_bridge.lua`: a blockade of a rebel port is refused (it crashed the game 3 of 3) (#414); under the QA hold a battle's auto-resolve is pressed again and its results closed (#415).
- `lua/parley_bridge.lua`: End Turn waits for agent missions; a load never runs during an AI turn (#375); the QA hold is for the player's turn only (#380); a faction whose envoy parleys stays awake that turn (#381); End Turn waits for an unread message in the popups suite (#399).
- `games/qa/*.toml`: recruit_merchant builds a market first (#372); sabotage's target gets a building (#403); turn_start_orders' army leads heavy infantry and any siege-maintain path passes (#404); report_fleet_carrying and blockade_port use England's own admirals (#405, #414); faction_overview_closed passes when nothing held (#400); next_turn_delivers may build in the garrison town (#413); besiege_assault_storms joins phase 1 (#415).
- `parley/popups.py`: keeps `<id>-nobuttons.png` when an offer never shows its buttons (#388).
- Closed: #392 (spawning bench generals at 66 made them die of old age).

### Added (2026-11-05, later)
- `just work-until HH:MM`: a Stop hook holds a standing order to keep working until then (#365).
- `just qa-summary`: the newest report per suite with outcome counts and failing cases (#374).
- `just ruler-eval`: every seat on every recorded turn, scored on legal orders, answers and time
  (#379); the first piece of the ruler-eval harness.
- A QA run's crash writes a crash report before its relaunch, as crash-watch does (#377).
- The relaunch keeps the bridge log under 20 MB (the old one as `.log.1`) (#369).

### Fixed (2026-11-05, later)
- Privacy: crash reports capture only the game's windows, never the whole desktop; a test forbids
  any whole-screen capture (#376). Tests no longer use a personal Discord handle or files outside
  the repo (#383).
- A played turn on the bench takes ~80 s, not ~5 min: a frozen AI faction is let go after 3 s
  (#367).
- The parallel-seats test proves concurrency with a barrier instead of a wall-clock bound (#368).

### Added (2026-11-05)
- `PARLEY_POWER_OFF=HH:MM` (parley/qa/power.py): a QA run refuses to start when its estimate
  (8 min + 40 s a case) would cross the machine's scheduled power-off. the test laptop powers off at
  23:59 and back on at 03:00 every night; its `~/.config/environment.d/parley.conf` sets it, and the
  file is read directly so an ssh shell sees it too.

### Added (2026-11-05, docs and install)
- README rewritten in plain words; new CONTRIBUTING.md (where help matters most, ground rules);
  docs/WRITEUP.md fact-checked against the code (control `full` includes recruiting, `just play`,
  all 27 order types, crash recovery, lessons, which EOP, older-graphics launch option).
- `EOP_BUILD=master just install-eop` installs EOP's CI build of master b525628, the build the
  game runs (pinned run id and sha256; the DLL is byte-identical to the one tested). GitHub
  deletes that build on 2027-01-17.

### Fixed (2026-11-05, phase 2)
- `M.qa.teleport` refuses a taken or unstandable tile with a clear error (11-04: a teleport onto
  a fixed tile crashed the game after a played turn); smoke's teleport binds a free tile.
- A frozen AI faction is let go after 3 s, not 15: once released it ends its turn at once (26
  releases, median 0 s), so the wait cost ~15 s per AI faction per played turn.
- `just work-until HH:MM`: a Stop hook holds a standing order to keep working until then.

### Fixed (2026-11-05, QA over ssh)
- A held game (paused.txt) logs nothing, and the QA hang check read 240 s of silence as a hang
  and relaunched a healthy game. It now asks the game first (scripts/probe.sh), as crash-watch
  does; the run's own probe may pass its qa.lock (`PARLEY_QA_OWNER=1`).
- A QA run over ssh borrows the desktop's display (scripts/desktop_env.sh, shared with
  relaunch_game.sh), so its screen checks can see the game's window and dialogs.

### Fixed (2026-11-05)
- A princess disgraced by a refused proposal reaches the ruler's news (lua/parley_bridge.lua
  `settle_proposals`): the game removes her with no mission event ("Princess Disgraced!"; on the
  bench she vanished 4 of 4, and two probes saw her record go dead). `marry_foreign_general` reads the news and passes on any outcome; passed live on
  the test laptop.
- scripts/relaunch_game.sh starts Steam from an ssh shell or a user unit: it borrows DISPLAY and
  the session bus from the running desktop shell, reads PARLEY_STEAM_URL from environment.d when
  unset, and detaches Steam (setsid). With nobody logged in and no Steam, it fails at once
  instead of waiting 240 s.

### Added (2026-11-04: product brief, public Jigsaw, phase-1 cases, #348-#351)
- PRODUCT.md: core job, users, success measures, offline first-run path, non-goals, `verify:`
  block; README "Try it without the game". The first-run gate passes on a clean image (#348).
- `M.qa.wooer / princess / bachelor` (lua/parley_bridge.lua): real family members for the marry
  case; the suitor leads a field army and isn't his faction's leader or heir (#351).
- tests/test_preflight_match.py: the phase gate checked against wrapped and quoted commands (#350).

### Changed (2026-11-04)
- Jigsaw is public (github.com/williamblair333/jigsaw, v0.1.0); pyproject pins its git tag, not
  the local path; tests/test_uv_lock.py checks the committed lock matches that tag (#348, #349).
- .claude/preflight.toml: the forced-events match is a broad prefilter; `qa_args`
  (scripts/preflight_interrupts.py) decides by shell tokens, reading `sh -c` and just's options (#350).
- games/qa/towns.toml `repair_queued`: a repair is paid in full when queued (live London
  13473 -> 13073 with the queue at 1); the fake game agrees (#350).

### Fixed (2026-11-04)
- `timeout 590 just qa ...` and other wrapped runs skipped the phase gate and played turns (#350).
- `_park_real` (parley/qa/runner.py) took a stale heartbeat's turn after a relaunch; a newer
  campaign load in the bridge log wins (#350).
- `M.on_agent_mission` dropped a whole mission report when one field couldn't be read; it reads
  each field on its own and logs an unreadable event (#351).
- STANDARDS.md parses again (a quoted evidence value) (#348).

### Added (2026-11-01 morning: quiet world and the phase-order gate, #342-#346)
- `M.qa.quiet` (lua/parley_bridge.lua): the Pope, each seated faction's leader and heir kept at 45 or
  younger; seated towns' turmoil and rebel chance 0, plague cleared; every write read back. The runner
  runs it after each bench load and refuses the load on failure (`_quiet_world`, parley/qa/runner.py);
  the bridge repeats it at the player's turn start under `freeze=*` (#342, #344, #345).
- Preflight gate (scripts/preflight_interrupts.py): turn-playing `just qa` refused while the newest
  `runs/qa/*-all.md` has an unexplained fail/inconclusive (games/no-click-explained.toml); a held event
  in games/interrupts.toml needs `bench = "suite/case"` with a passing newest row (#346).
- STANDARDS.md: `phase-order` and `no-clicks-first`; forced-events evidence corrected (#346).

### Changed (2026-11-01)
- games/interrupts.toml: rebellion split into town revolts + `general_defects`; plague_disaster into
  `plague` + `disaster` (#345).

### Fixed (2026-11-01)
- uv.lock's jigsaw path, swept into #343 by a `git commit -a` (#344).

### Fixed (2026-11-01 overnight: QA bench and live bridge, #325-#339)
- Free tiles skip impassable/river/fort tiles (#326); tile visibility 3+ is seen (#327); a campaign load
  clears agent/army order records (#328); governors' automanage flags written as booleans (#337).
- Navy: boarding and landing by whole-army split; an army aboard is named by its unit's general (#331, #332).
- QA: park waits for an on-screen decision (#329); canary removal waited for; NE Catapult, build cost on
  start, storming case phase 2 (#336); reload-bridge waits for the reload (#330).
- Watchers: crash-watch and the watch probe the game before acting on a quiet log (#334, #335); STUCK reads
  the newest stuck line and ignores stale ones (#338, #339).

### Added (2026-11-01)
- Heretic decision time: `decide_timeout` config (480 s), bridge DECIDE_WAIT 540 (#329).
- `just screen-awake` / `screen-awake-stop`: keep monitors on while the game runs (#333).

### Added (2026-11-01: interrupting-events preflight gate)
- **`just qa` runs that play turns are refused until every interrupting event is handled.**
  `.claude/preflight.toml` declares the `forced-events` gate; the Refinery's global
  preflight-gate hook runs `scripts/preflight_interrupts.py` before every `just qa` command in
  every Claude session. Each event in `games/interrupts.toml` needs `ruled_out = "why"` or
  `held_by` plus `proof = ["path::regex"]` that matches in the repo. Runs with `kind=instant`
  play no turn and pass. 1 of 10 events held so far (AI attacks, via freeze=*); papal election,
  missions, crusades, diplomacy offers, marriage/adoption, rebellion, succession and disasters
  are open. Why: a minimized papal election stalled turn 50 for hours on 11-01, and the author had to
  ask for a quiet world although STANDARDS already had `forced-events`.

### Changed (2026-10-31: the relaunch makes no clicks)
- **`scripts/relaunch_game.sh` relaunches with no screen input** (spec
  `docs/superpowers/specs/2026-10-31-no-click-relaunch.md`, proven by hand live 10-31 08:37-08:40).
  `"hideLauncher": true` in both EOP `uiCfg.json` files skips the launcher's Run mod.
  `bypass_to_strategy_save = mods/parley/saves/<name>.sav` in parley.cfg's `[misc]` loads the save
  at start-up instead of the menu, so there's no Continue Campaign. The script then waits for
  `bridge loaded campaign at turn N` (N > 0, `PARLEY_RELAUNCH_TIMEOUT`, 240 s). The save it loads
  is `--save <name>.sav`, else the restored keep save after a QA restore with no newer autosave,
  else the newest save the game wrote. The bypass line is always the full saves path: a bare name
  brings up EOP's modal ERROR box. The line is stripped on every exit. EOP's ERROR box
  (read-only `xdotool search`) or the timeout stops the game and fails. A missing save or
  `uiCfg.json` fails before anything is killed. The file edits are in `parley/relaunch.py`.
- **The QA restore relaunches straight onto the kept save** (`--save parley_keep_<id>.sav`). It's
  allowed in a no-click run now, so a crash in `just qa <suite> kind=instant` is relaunched, not
  left for `just qa-restore`. crash-watch uses the same no-click path.
- `relaunch_game.sh --clicks` keeps the old clicking path as a fallback. It's refused under
  `PARLEY_NO_X_INPUT=1`. `just relaunch-game` passes its arguments through.
- `just install-eop` sets `hideLauncher` too.

### Added (2026-10-31: crash reports)
- **crash-watch writes a crash report before each relaunch** (`scripts/crash_report.py`,
  `runs/crashes/<YYYY-MM-DD-HHMMSS>/`): the bridge log's last 200 lines and the papal-trace lines
  among them, the last 100 lines of every `logs/*-turns.log` written in the last 10 min, a
  full-screen screenshot (the crash dialog is still up), a copy of the newest save (what Continue
  Campaign reloads), heartbeat.txt, bridge.txt, papal_trace.txt, and `report.md`: game id and turn,
  what crash-watch saw, the last 10 s of the bridge and turn loop merged by timestamp, and blank
  Guess and Repro case slots. Each part fails on its own and is named in the report; the whole is
  bounded by `timeout` (15 s; ~1.5 s measured, most of it the screenshot) and a failure is only
  logged, so the relaunch always goes ahead. The newest 20 reports are kept (`PARLEY_CRASH_KEEP`).
- **`just crashes`**: recent reports, newest first, with their game, turn, cause and last bridge line.
### Fixed (2026-10-31: a long-thinking ruler no longer loses its turn, STANDARDS ruler-budget)
- **Heretic/OpenAI-compatible seats stream and keep to a budget.** Run9 lost 4 of 46 ruler turns
  ("heretic failed: timed out" at seat_timeout 420): llama-server's log shows 5-8.2k generated
  tokens per answer at 19-25 tok/s (210-360 s), while the saved orders JSON was at most 4.7 KB
  (~1.5k tokens), so ~85% was thinking. Now thinking stops after `think_tokens` (6000) or when
  only `answer_reserve` (120 s) is left; the ruler is asked again with thinking off and the end of
  its reasoning in the prompt. The answer is capped at `answer_tokens` (2500); one cut by the
  deadline, the token cap, a stall or a dropped connection keeps the orders it finished. A call
  with less than 60 s of thinking room (a fallback's reserve) answers without thinking.
- New `[ruler_budget]` table (and `[seats.<f>.ruler_budget]` per seat) in game configs; the
  defaults need no config change.

### Changed (2026-10-31: QA covert and field suites converted to instant cases)
- **`just qa field`**: 9 instant cases and 1 turn case (was 9 turn cases). spawn, move, march_on
  (#261), the across-the-sea refusals (#263), the tired mover (#267), merge, withdraw and the
  garrison's general leaving are read back in the held turn; one turn groups the siege scroll after
  march_on, tire() at turn start and the report's last_results. withdraw goes into
  `$garrison_town` and no longer needs an unled town.
- **`just qa covert`**: 4 instant cases and 1 turn case (was 3 turn cases). assassinate and
  sabotage pass on the order taken and the game's mission line, any outcome; new refusals for an
  agent of the wrong kind and a spy too far off (he walks). The #255 spy report stays a turn case
  (`chance = true`) and now also checks the report's agent_results.
- **M.qa.spawn_army refuses a tile someone stands on and fails when the army lands elsewhere**
  (QA field 10-30/31: spawns landed a tile off). New helpers M.qa.units and M.qa.news.
- **An agent of the wrong kind is refused with the right article** ("is an assassin, not a spy";
  it said "a assassin").

### Added (2026-10-31: QA envoys suite)
- **`just qa envoys`** (`games/qa/envoys.toml`): 12 instant cases and one turn case. recruit_agent
  for a diplomat and a merchant (paid, queued), a princess refused, and the merchant limit refused
  with its count; move_agent walking, refused into a foreign town (the agent orders to use) and
  across the sea (the board order to copy); bribe of an army, an agent and a settlement and a
  princess's proposal to a foreign general, each passing on the order taken and the game's mission
  outcome line; a general named in an agent order. The turn case sees the seat's recruit arrive and
  a merchant on a resource earn trade income. New M.qa helpers: funds, agents, agent_town,
  fill_agents, resource, merchant_income, drop_training. A `log` expect in an instant case may poll
  `within` N s. Not yet run live.

### Changed (2026-10-31)
- **An agent order naming one of the ruler's own generals says so.** The bridge answered "unknown
  agent '<him>' (not one of yours)"; it now says he is one of your generals, not an agent, and for
  a move gives the move_army order to copy (live 10-29, turn 138: France moved its generals by
  move_agent). The text still starts "unknown agent '<name>'", as parley/audit.py reads it.

### Added (2026-10-31: QA diplomacy suite)
- **`just qa diplomacy`** (`games/qa/diplomacy.toml`): set_stance war/peace/alliance, send_gold
  (both treasuries move by the amount), cede_settlement, an AI's offer put to the ruler and his
  accept pressed, a second offer on the open screen asked again (#297), and a diplomacy screen with
  no offer closed, all instant; one turn of every diplomacy order and a `say` read back from the
  next report, and an AI envoy's parley on its own turn (a chance case). New M.qa helpers: rival,
  stance, money, owner, spare_town, town_of, screen, parley, court, diplomacy_step. Scripted seats
  now say their plan's `say` entries and answer the game's choices with a case's `choice`. Not yet
  run live: whether an AI envoy's parley command brings an offer up is unproven (the offer cases
  skip as inconclusive when it doesn't).
### Changed (2026-10-31: the QA bench runs on a fixed, quiet save)
- **Every bench run starts from the bench save, never the live campaign's world.** `just qa` loads
  `mods/parley/saves/parley_bench.sav` (checked against its recorded turn and sha256) after parking
  the real run, and refuses to start without it. The real campaign's keep and restore are unchanged.
  10-31 05:29 a Pope died mid-smoke on the live world and the game crashed.
- **A quiet world.** Every AI faction's game AI is frozen during a run (bridge.txt `freeze=*`); a
  case lists the factions it needs to act in `needs`. The bridge unfreezes them under a real config.
- **`just qa-bench-save start` / `record`** makes the save from a new turn-1 England campaign
  (steps in the test-bench spec). `M.qa.report` writes the bench faction's report after the load.

### Fixed (2026-10-31 05:20: "Captain Arthur's Army")
- **An army written as "<name>'s Army" is read as that army.** Live (run9 turn 45) France's
  merge_units for "Captain Arthur's Army" was refused as unknown. The audit also read that refusal
  as 'Captain Arthur' (its name pattern stopped at the apostrophe) and woke the watch with a false
  bridge bug; it now reads the name to the last quote.

### Fixed (2026-10-31 04:05: a second AI offer; marching out of a besieged town)
- **A second AI offer on an open diplomacy screen goes to the ruler.** Live (run9 turn 33): the
  Moors' offer was declined, then Portugal's offer came up on the same open screen. Its buttons
  have the answered offer's names, which are never pressed twice while they linger, and no close
  button closes a screen whose offer waits: the turn stuck until a hand declined it. Once a round
  of close buttons fails with an offer button still open, the bridge forgets the old answer and
  asks the ruler again (at most twice per open screen).
- **Nobody marches out of a besieged town.** Live (run9 turns 22-35): Robert's splits out of
  Caen while Luquin, then Garnot besieged it did nothing. `M.walk` now refuses with who besieges
  the town and the attack order to copy (a sally on the besieger), for every move order.

### Fixed (2026-10-31 03:20: generals leave towns for far targets)
- **A general inside a town now splits onto the tile beside it, then walks on.** Live (run9
  turns 22-27): Robert's `splitArmy` out of Caen to targets 11 and 18 tiles away came back without
  error and did nothing, turn after turn (London's 3-tile splits worked). Live at 03:17, a split
  to the next tile followed by `moveToTile` to the target in the same call took him from Caen to
  (110,130) at once. `M.walk` picks the free land tile beside the town nearest the target (nobody
  on it, no settlement), splits onto it, then calls `moveToTile`; a target beside the town is split
  onto directly. The fake's `splitArmy` now ignores a target more than a tile off, as live.

### Changed (2026-10-30 night: papal hands-off for real games, with the vote)
- **`papal_hands_off` is on by default** for every game (`[autoplay] papal_hands_off = false`
  turns it off). Four QA field runs with it on played the marriage + results-only elections of
  turns 59-67 with no crash; with it off, 3 of the last 4 runs died ~5 s after the results scroll.
- **The ruler still votes with it on.** After the Pope's death notice (message 202, which still
  reaches the bridge through `onIncomingMessage`), the bridge looks for the vote scroll from its
  per-frame tick, never inside the scroll's open event: one guarded
  `getUiElement("papal_election_scroll")` every 2 s, from 3 s after the notice for up to 60 s
  (`K.PAPAL_LOOK`), only while hands-off is on and no vote is queued. Nothing on the scroll is
  read. Once seen, the existing vote path runs: papal window (vote phase, #283), one vote request,
  the ruler decides, the turn loop clicks the Vote button from a screenshot. Once the vote is
  clicked the window goes to its results phase for 20 s (no results event reaches the bridge).
  `papal_election_results_scroll` is never looked up. Each look is in the papal trace.
  Not yet seen live: QA covert/field from run8's save at turns 43-45 (vote-led elections).

### Added (2026-10-30 late: papal hands-off experiment)
- **`[autoplay] papal_hands_off = true`** (bridge.txt `papal_hands_off=1`; default off; the QA bench's
  generated game turns it on): `luaPluginScript.lua`'s `onScrollOpened` returns at once for any
  scroll named `papal_*`, before the bridge is called. Nothing of ours runs in that callback for
  a papal scroll: no log line, no papal-trace or `papal_window.txt` write, no popup queued, no
  capture request. The check reads the event's `resourceDescription` and a flag the bridge keeps
  from its last bridge.txt read (it logs `papal hands-off: on` when the flag changes). With it on
  the bridge never learns of the election: no papal window (the turn loop isn't held off), and
  **no vote**. A vote-led election leaves the vote scroll to the game and the stuck-turn path;
  QA field turns 59 and 62 are results-only elections, so they test the crash, not the vote.
  Message 202 (the notice) still goes through `onIncomingMessage` as before; no papal scroll has
  been seen to fire a message event (bridge log 22:43:31: none around the results scroll).
  Reading the QA run: a crash ~5 s after a results scroll with no `popup papal_...` line in the
  bridge log means the crash is the game's; no crash at the same spot (turns 59/62, the same
  marriage decline) points at our handler, but only after repeats: 20:56 survived the same
  pattern once with the handler on.

### Fixed (2026-10-30 late: End Turn waits for offers)
- **End Turn waits for the ruler's answer to an offer on screen** (marriage, adoption, a
  diplomatic offer, the papal vote). In all three results-only elections (QA field 20:48:04,
  22:28:31; qa-covert 20:55:59) a marriage offer came up at England's turn start, the bridge ended
  the turn 1-2 s later with it unanswered, the AI turns stalled behind the open scroll (~30 s, no
  event), and the decline click released the queued results scroll and the deferred End Turn in
  the same moment; the game died 5 s later twice. Now the offer is answered on England's own turn
  and End Turn comes after it. The ruler still decides; only the order changes. Bounded: the
  decision request gives up after 180 s and the hold after 210 s (`K.DECISION_HOLD_MAX`).
  `[autoplay] hold_decisions = false` turns it off. Not yet seen live: QA field turns 59 and 62.

### Fixed (2026-10-30 night: the papal window)
- **The turn loop presses nothing while the papal election is on.** #275's hypothesis (the
  bridge's UI lookups) is refuted: with no lookup left, the game still died at 20:06:30 and
  20:48:34 (qa-field), and every crash today (18:34:11, 19:04:51, 20:06:30, 20:48:34) had a turn
  loop click within a second of a papal scroll opening (a notice's check, a stale turn-39
  request's check, a 201 check, a marriage declined). In the three vote crashes the vote and
  result scrolls opened in the same second; in every good election they were 10-41 s apart.
  Not every coincident click kills it: qa-covert replayed turn 59 at 20:56:36, the same decline
  in the same second as the same result, and lived; so did 10-30 06:41:00. The bridge now keeps
  a papal window (`papal_window.txt`, phase and end): from message 202 (45 s), the vote scroll
  (180 s) or the result (10 s after it opened; a result England had no vote in opens it too).
  Meanwhile the bridge asks the turn loop for nothing but the vote and, before the election
  opens, 202's check (#280), holds its own sweep and stuck-turn checks, and gives held requests
  their full wait once it closes; a bridge reload keeps it. `popups.py` takes no screenshot and
  presses nothing else in the window: a ruler's answer that arrives in it is clicked after it
  (not asked again), a stuck-turn reopen is dropped, and the real click asks once more right
  before the press. A result with no warning (20:48) can still open within the last ~0.2 s of a
  click. Not yet seen live.

### Fixed (2026-10-30 night: crash-watch as a user unit)
- **crash-watch runs as the systemd user unit `parley-crash-watch`** (`scripts/crash_watch_unit.sh`,
  `just crash-watch` / `just crash-watch-stop`). Live 20:20: one started by a QA restore inside a
  background job died with that job, and the next crash went unnoticed. Start is a no-op when the
  unit is active; start and stop also end an old-style watch (exact argv). A relaunch under the unit
  starts Steam in its own scope so stopping the unit can't take the game down. The QA runner goes
  through the recipes and keeps its argv sweep as the fallback.
- Tests no longer reach the machine's crash-watch: `restore()` tests without an injected
  `stop_crash_watch` swept the real `/proc` and would kill a live `bash scripts/crash_watch.sh`.

### Added / Fixed (2026-10-30 evening: QA bench, #260-#277)
- **QA bench** (`just qa <suite>`, `just qa-restore`; #260 spec, #262 build, #264-#277 live fixes):
  scripted suites in the real game on a copy of the real save, with a kept-save gate, park/restore,
  hang/crash recovery, a pass/fail/inconclusive table per run. Suites: smoke, covert, field.
- **Bridge fixes found or proven by it:** march_on beside a town besieges (#261); march_on across the
  sea refused (#263); control lines see the bridge as `M` (#265); moves refused when the mover has
  none left (#267); honest siege results (#272); every campaign load logged (#262).
- **QA runner fixes from live runs:** autosaves in `mods/parley/saves` (`mod_save_dir`, also used
  by backups) and the turn from `heartbeat.txt` (#264); named spawns and bound results (#266);
  cases isolated per turn (#269); spawnArmy label (#270); targets picked when the order is written
  (#271); hung-game recovery (#273); real bridge config published before the restore's load (#274);
  the menu's turn-0 map ignored, stale QA answers archived (#276); free-tile spawns (#277).

### Fixed (2026-10-30 night: crash dialog, relaunch after a QA restore)
- **Wine's crash dialog counts as a crash at once.** `scripts/crash_dialog.sh` (a visible
  "Medieval 2" window between 150x60 and 800x400; the game's is 1600x900) is checked on every
  crash-watch poll and every QA `game_trouble` check, instead of waiting out 480 s / 240 s of log
  silence while the dialog keeps medieval2.exe alive (live 20:11). A false positive would kill a
  healthy game, so it must be seen twice: on two crash-watch polls in a row, or two sightings 5 s
  apart in the QA runner; crash-watch skips it for 120 s after its own relaunch.
- **A relaunch right after a QA restore goes back to the real campaign.** When no save is newer than
  `qa.last_restore`, relaunch_game.sh's new `python -m parley.qa after-relaunch` step loads the
  newest `parley_keep_*.restored-*.sav` once the campaign map is up (live 20:12: Continue took the
  QA game's autosave, turn 45 for 41).

### Fixed (2026-10-30 night: the papal election's notice)
- **Hands off while the papal election opens.** Message 202 (the Pope is dead, the cardinals
  convene) opened the election 3-6 s later when nothing touched the screen (18:54, 19:04, 19:47).
  Each time a `clear_messages` for another message landed in that gap, it never opened and End
  Turn stayed blocked (10-29 18:30; 10-30 18:16, 18:33, and qa-covert turn 48 at 19:41:57, two
  seconds after 202). The bridge now leaves every popup alone for up to 15 s after 202, until
  `papal_election_scroll` opens. Stuck-turn checks wait in that time too. It never clears 202
  itself, because clearing it never opened the election (19:42:13, 19:43:33, 19:44:53).
- **The notice's check is pressed even when it looks like the last scroll read.** In the
  recoveries that worked, the notice was reopened and its check pressed (18:17:04, 18:34:11). At
  19:43 the reopened notice matched the image from the last reading, so `popups.py` skipped it
  five times and the bridge cleared it again on every try. Requests for 202 now carry
  `press_check`, which skips the same-scroll check.

### Fixed (2026-10-30 night: QA field round 2, from the 19:39-19:55 runs)
- **Spawned generals keep their loyalty**: `M.qa.spawn_army` gives the general `LoyaltyStarter`
  (Loyalty 5, which the game gives every general on coming of age, adoption or marriage). Two
  spawned generals went over to the rebels a turn after spawning (Edmund Awood, Walter Baker:
  "slave: ... struck by a disaster"); that emptied `march_on_across_sea` and left a rebel beside
  `move_army`'s path, which stopped a tile short with 87 of 104 moves left. Not yet seen live.
- **march_on_besieges picks its town from the map** (`M.qa.hostile_town`: the nearest rebel or
  at-war town) and spawns beside it; no rebel town was in England's sight at 19:51.
- **garrison_general_leaves uses a town's own general** (`M.qa.garrison`), spawning one only into
  an unled garrison; every English town had a general at 19:51 (`pick_garrison_town`).
- **A turn that won't end fails its case** with the bridge's last `autoplay:` line ("turn stuck:
  ...") and ends the run through the restore; it raised and dropped the case from the report
  (covert 19:41-19:44, turn 48 stuck at a papal notice).

### Fixed (2026-10-30 evening: papal election hang)
- **Papal scrolls are never touched by the bridge**: the game hung three times (08:41:52, 18:34:11,
  19:04:51) right after `onScrollOpened(papal_election_results_scroll)` called
  `gameSTDUI.getUiElement` on the scroll while the game was still building it (found=false); the
  event's second firing never came. Now a papal scroll event only queues it (no UI call), the
  message sweep, `press_tick_part` and the stuck-turn UI scan skip papal scrolls, the result is left
  to close by itself, and the double event asks the ruler for one vote, not two (live 18:17: the
  second vote click landed after the result was up). Trace kept. Not yet seen live.

### Fixed (2026-10-30, after the outage: #254-#258)
- **Relaunch clicks inside a cleared window** (#254): closes Steam's "Special Offers", moves Steam
  off the M2TWEOP launcher, clicks relative to the launcher and game windows; processes matched by
  name (`pgrep -x`), not command line (an unrelated shell was killed). Live: the 12:05 crash was
  relaunched without help (turns again at 12:16).
- **Spy report scroll closed** (#255): a ruler's spy mission arms a close of
  `enemy_settlement_info_scroll` through EOP; the stuck-turn check closes it too. It held France's
  turn 7 minutes at 11:00. Not yet seen live.
- **Watch wakes on failed seats** (#258): `SEATS:` when any faction's seat fails 3+ turns running
  (every seat timed out from turn 83 to 96 and nothing fired); failures from before the watch
  started don't fire again.
- **Docs** (#256, #257): `docs/NOTIFY-CLAUDE.md` "Handling a wake": unstick, then fix the cause
  (agy first), merge on green, reload, record.

### Added / Fixed (2026-10-30, afternoon: #240-#250)
- **Per-faction strategy notes** (#240, #241): `parley/strategy/<faction>.md` after the primer;
  England's from the reviewed England guide; the primer gains the game clock.
- **Enemy armies** (#242): the 4 nearest foreign armies list their units with roles; sight uses EOP's
  `getTileVisibility` (confirmed live), else the old radius.
- **Revolt risk and siege checks** (#243): rebellion, plague, turmoil, per-town income; THREATS for a
  town flagged to revolt; `canStartSiege`/`canStartAssault` answers as advice, never blocking.
- **`hire_mercenary`** (#246): a general's army in the pool's region, the pool's price, one unit off
  the pool; religion/crusade/year/event limits from `descr_mercenaries.txt`.
- **THREATS gap** (#247): shortfall in men, recruit answers with cost and arrival, faster answers at
  the gate, a hoarding line (England lost two towns holding 11k florins).
- **Fixed:** relaunch retries Run mod (#248); rulers start as soon as their own report lands, not
  after the other seat's turn (#249); a heartbeat log line while waiting for rulers (#250); uv.lock
  restored and its committed path tested (#245).

### Added (2026-10-30: order cap, papal crash trace)
- **Order cap scales with the realm**: `max(40, 3*settlements + armies + agents)`, ceiling 150
  (`validate.order_cap`); only orders that pass the checks count toward it. The steward's room uses
  the same cap. The bridge has no cap of its own.
- **Papal crash trace (instrumentation only)**: every step around a `papal_*` scroll, and around any
  message popup within 120 s of one, is logged to `parley_bridge.log` as `papal-trace: #seq step
  [scroll]` BEFORE the call it names (the log is closed per line, so flushed), and mirrored to
  `papal_trace.txt` (`n` papal scrolls ever, `seq`, `done`, `turn`, `last`, `scroll`, `at`). After a
  relaunch the bridge logs `papal-trace: PREVIOUS RUN ENDED MID-STEP ... last=...` when `done=0`.
  What the next crash tells us: `last` is the call that never returned, one of getUiElement,
  buttons_of/names, record_layout, `captured()`, `buttons_for_scroll/choose`, `button:execute()`,
  `press_tick_part`, or `scriptCommand('clear_messages')` (suspect: a message popup for the result
  falls through to `clear_messages` while the scroll is open). `n` correlates crashes with scroll count.

### Added / Fixed (2026-10-30, late morning: strategy round)
- **Debt is a tool** (#230): primer, THREATS and the debt block give the fact (gold orders refused
  in debt) and the trade-off instead of "disband"; rigid army-count rules softened.
- **Enemy fleets** (#231): foreign fleets show their cargo ("carrying an army of 3 units (240 men)");
  THREATS lists a loaded enemy fleet within 6 tiles of a settlement.
- **Lessons from outcomes** (#232): the 20-turn review gets OUTCOMES (settlements gained/lost, order
  and tax, sieges, treasury, income, events) and must tie a decision to a result.
- **Economy in the goal block** (#233): income trend, upkeep share, a phase line (building, stalled,
  late) and "your plan has aimed at York since turn 41" matched on the target town.
- **Primer playbook** (#234): free-upkeep slots by wall level, militia as garrison troops, money as
  the engine of conquest, scout ships and one big fleet against troop fleets.
- **Siege equipment** (#235): a besieging army with no other order calls EOP's
  `siegeSettlement(town, false)` each turn, which queues the game AI's equipment choice; the report
  shows siege turns, equipment queued and holdout.
- **Garrison units** (#236, `parley/units.py`, `parley/data/units.json`, `just unit-table`): free
  militia while a city has slots, else best men x (defence+armour+shield) per upkeep, upkeep at most
  1.5x the cheapest; recruit lists mark free units and slots left.
- **Primer: siege engines and several stacks** (#237); turn-39 prompt budget +400.
- **EOP coverage** (#238, `docs/EOP-COVERAGE.md`, `just eop-coverage`): every EOP Lua binding, marked
  used by the bridge or not, with the 30 highest-value gaps for rulers.

### Added / Fixed (2026-10-30, morning: helping the small ruler)
- **Compaction hook** (#218): `.claude/settings.json` runs `scripts/compact_context.sh` after a
  compaction, putting HANDOFF.md's top section back into the session (docs/NOTIFY-CLAUDE.md §6).
- **Discord lines name the model** (#219): `**King Edward (England · heretic:think):** ...`.
- **Refused orders open the prompt** (#221): one line per distinct refusal with its reason and
  "refused N turns running"; the lower results section lists only what was done.
- **Bridge:** besiege and agent walks (spy, sabotage, assassinate, bribe) toward a target across the
  sea are refused with the fleet advice instead of "marching there" forever (#222, run6: 36 turns on
  one tile); reports mark nearby settlements `by_land`, shown as "(across the sea: needs a fleet)".
- **Fixed:** #219 committed a worktree-relative jigsaw path in uv.lock; restored (#220).
- **Steward garrison backfill** (#225, `parley/steward.py`, opt-in `steward = true`): recruits the
  cheapest land unit where the ruler's orders leave a settlement without a garrison; never changes a
  ruler order; `hold_empty` opts a town out; the ruler is told next turn. A TAX AND UNREST warning
  (information only) for high tax under 80% order. The author's rule: offload work so long as the LLM's
  wishes are always carried out.
- **Leaner prompt** (#226): a THREATS block near the top; 25% shorter on England's turn 39 (compact
  lists, grouped quiet factions, capped notes and diplomacy); primer rules of thumb.
- **Bridge:** a reload during a frozen faction's turn releases it first; the release timer died with
  the old Lua state and the turn hung (#224).

### Added / Fixed (2026-10-29 night to 10-30: overnight runs 5-7)
- **`just watch <game_id> [faction]`** (#215, `scripts/campaign_watch.sh`): exits with one line on a
  stall, a turn stuck 10+ tries, a stopped loop or bot, or a lost faction; run in the background it
  wakes Claude. `docs/NOTIFY-CLAUDE.md` explains the pattern. Run6's defeat (turn 189) was missed by
  the old watch: the game sat on Victory Conditions Failed while the bridge kept logging.
- **Every prompt states the victory goal, progress and turns left** (#210, `parley/victory.py`).
- **`heretic:think` seat** (#209): the local model may reason first (benched: 6x slower, not adopted).
- **Bridge:** constants in table `K` under Lua's 200-local limit (#201); buttons and End Turn pressed
  by `execute()` (#204, #205), auto-resolve back on the scripted click after it hung the game (#212);
  renamed captains found by their reported tile, entering a full own settlement refused (#206); an
  army found once is kept for the turn (#211); papal election results never pressed by shape (#208,
  the crash there persists).
- **Checker:** no-land-path refusals carry the board order or say "no fleet" (#202); `move_agent` on a
  general or an admiral refused with the ready `move_army` order (#213, #214).
- **Audit:** an army used after merging it away is a ruler mistake (#203); agent orders for generals too (#213).

### Added / Fixed (2026-10-29, evening: the turn audit and what it found)
- **Turn audit** (#193, #194, #199): plain checks over the turn folders sort problems into bridge bugs,
  ruler mistakes and unused options; `just audit <name> [game_id]`; every turn the loop posts new
  problems once to #<game>-audit and tells each ruler its own in the next prompt.
- **Moves:** no land path refused (#191); moves onto another faction's settlement refused with the
  fitting order (#195); a garrison's move says only its general marches (#198).
- **Names:** near-miss names and a general's name for his army are read as the ruler's own (#196);
  agent-order refusals name the field swap and the right agents (#197).
- **Recruit options show upkeep a turn** (#192).

### Fixed (2026-10-29, later: first live run of #171-#186, each fix checked live before merging)
- **Overview stall** (#187): a stuck turn closes the Faction Overview the game opens at a new campaign's
  start (it held Scotland's AI turn on turn 1). Not yet run on the real stall; the next new campaign is.
- **"Moves that did not happen" was early** (#188): moves are judged at the faction's next turn start
  (at turn end an agent's move hadn't landed yet), moves to the army's own tile aren't recorded
  (merge_armies' garrisons), and the moves-left figure is gone. Checked live on turns 10-13: 4 reports,
  all true.
- **Agents sent to sea** (#189): `move_agent` refuses a sea tile and names the nearest land, as
  `move_army` does.

### Fixed (2026-10-29: stuck armies, prompt rules)
- **Stuck armies** (#184): only orders that move or attack lock an army for the turn (`merge_units` no
  longer blocks a merge); handlers can succeed with a note (walking garrison merge, besiege's march, an
  agent walking into range) instead of reporting REJECTED; every move order records its start tile and a
  mover still there at turn end goes into `moves_not_made`, which the next prompt names ("did not happen").
  136 march_on/withdraw orders across four campaigns were "done" while the army stayed put.
- **Prompt** (#185): a spy inside a settlement isn't ordered to spy on it; `merge_units` needs two worn
  units of one type.
- **Repo** (#182, #183): `review/` and `reviewed/` gitignored; ROADMAP item with Vox Deorum's ideas.

### Added / Fixed (2026-10-26, late: live steward session; play moved off Claude onto agy)
- **Steward** (#159): an all-zero suitor record counts as unknown and goes to the ruler (the game's
  record is empty at offer time). **Stars counted from pixels** (#175): `count_stars` reads the 4x10
  slot grid; its counts feed the steward and the ruler's reading.
- **Rulers know they play a game** (#160, #163): technical notes from the adviser get plain answers and a
  `Bug:` note; Claude is named as the developer who runs Parley.
- **Choice records keep the scroll** (#161); **turn gate** counts only others' new messages (#162).
- **Decision buttons** (#165, #171): `find_choice` needs parchment between and around the buttons and the
  X 80 px right of the check; settlement labels no longer fake or hide a decision (turn 27, 60 stalls).
- **Bridge** (#166, #172, #176): fleets get the nearest sea; a walking garrison says its town is left
  empty; crossings name each shore's land tile; leaderless fleets resolve; empty merges are refused.
- **Prompt** (#176): no every-turn merge rule; the treasury line tells the truth; a DEBT block lists free
  levers when the treasury is negative. **agy seat** survives E2BIG.
- **Unattended running**: `just relaunch-game` (#168), `just crash-watch` (#173); `just play-review`
  (#169, #170) has agy review a ruler's play every N turns into `_review/`.
- **Reader on agy** (#174): `reader = "agy:<model>"` in a game config (default `claude:haiku`).

### Added / Fixed (2026-10-26, afternoon: the steward grows, turn gate, Heretic seat)
- **Steward decides marriage offers** for `ladder = true` seats (#150): `parley/deciders/marriage.py`
  (decline baseline 8, a princess unmarried is an asset; age > 60 costs 3; +2 when short of generals;
  stakes 0.3). `_steward(kind, ...)` serves both adoptions and marriages and logs the real kind.
- **`just decisions <name> [last]`** (#151): a report over `<turn_root>/<game>.decisions.db` by rung
  (with share), kind (with outcome count), actor, and the newest decisions with outcome and escalation
  reason. Read-only; a missing log is reported, never created.
- **Steward answers ransom scrolls by rule** (#152): `parley/deciders/ransom.py`. As captor: ransom by
  custom under 1,500 florins; as captive: pay or refuse by price versus treasury. Execute and release
  always escalate to the ruler.
- **OpenAI-compatible seat and Heretic** (#153): `parley/seats/openai_compat.py` supports `heretic:local`
  and `openai:<model>` (llama-server :8090) with wait-and-retry on 503 or dropped connection. Bench on
  scratch2 England turn 24: 623 s, 16 kept, 4 rejected, 0 malformed.
- **Steward decision outcomes** (#154): every steward choice gets its on-screen outcome recorded in the
  decision log using Jigsaw's `Verdict.decision_id` (jigsaw#9).
- **Turn gate** (#155): `parley/turn_gate.py`. For `ladder = true` seats with `quiet_brain` set, quiet turns
  go to the cheap brain. Escalations (messages, popups, events, enemy within 8 tiles, siege, money, every
  5th turn, 2 quiet turns in a row) go to the ruler; each gated turn logs a `turn_gate` decision.
- **Decision inventory refreshed** (#156): `docs/decision-inventory.md` updated with steward rows,
  retraining (master exposes it; already done by direct write), and repair.
- **Upstream contributions**: EOP-Labs/M2TWEOP-library#89 (feature request for missions list, mercenary
  hiring, diplomatic proposals, games/races, agent recruit cost, siege equipment); #90 (fix PR for #88
  `getBuildingInQueue`, compile-tested on the Gitea Windows runner, run 2255).
- **Repair order** (R3, #157): settlements report damaged buildings (hp below 100); `repair {settlement, building}` queues the game's repair option (cost and time charged). Not yet run in game.

### Added / Fixed (2026-10-26: Jigsaw arrives; any model can play)
- **Decision outcomes** (#148): each logged order is marked "done" or "refused: <reason>" from the
  next turn's results (the LLM's own numbering, late orders mapped through index_map.json).
- **Steward decides adoptions by rule** for seats with `ladder = true` (#146): Jigsaw's ladder
  (rung 2 = `parley/deciders/adoption.py`, #145) answers unless its gate escalates (close call,
  no heir, unknown stars); the ruler reads "(your steward decided by rule) ...". Off by default.
- **Every ruler decision recorded** in Jigsaw's decision log, `<turn_root>/<game>.decisions.db`
  (#143). Parley now depends on Jigsaw (`../jigsaw`, non-editable path dependency).
- **Siege clock** (#142) and its adviser line under each besieged settlement in the prompt (#144).
- **Treaties and stance age** (#138) and **the game's recruitment queue** (#139) on EOP master.
- **Weak models' answers salvaged** (#140): JSON found inside prose or fences, a bare array taken
  as the orders; fleets refused for land orders and mixed merges (Python and bridge); 40-order cap;
  duplicate builds; negative coordinates; CLI output decoded with errors=replace. Retrain refused
  with no gold (#141).
- **Frozen seat watchdog** (#137): a frozen seat's turn running past 15 s unfreezes its AI until
  its next turn (the siege hang). Not yet seen live on a siege.
- Upstream: EOP-Labs/M2TWEOP-library#88 (`getBuildingInQueue` off by one on master).

### Fixed / Added (2026-10-25, night: the game moves to EOP master)
- **EOP master crash** (#135): the bridge read master's building queue past its end
  (`getBuildingInQueue(i)` counts from the buffer head, though documented 1-based); on master it
  reads `1..n-1` and shows the item under construction unnamed. `eop_master()` detects master.
- `seats.<f>.freeze` (#134): sets the faction's own game AI frozen each turn start. Live caveat: a
  frozen faction never ends its turn while it has a siege; England runs unfrozen until the bridge
  unfreezes at turn end.
- The game runs master (upstream CI b525628) as `mods/parley`; 3.3.1 parked as `mods/parley-331`.

### Fixed (2026-10-25, live session: scratch ended at turn 226, scratch2 with the author as HRE)
- Agent recruiting live (#118): EOP 3.3.1's `getAgentCapability`/`getAgentLimitCapability` return
  garbage (London 0, others -1); the rules now come from `export_descr_buildings.txt` (agent and
  agent_limit lines; spy, assassin, diplomat unlimited). Confirmed live: "spy trained in Caernarvon".
- Garrisons and armies report men and units; strength ratings read "(strength rating N, not men)",
  foreign armies and plain ruler seats included (#120, #124).
- `merge_armies`: adjacent stacks merge at once (direct EOP call, no exchange screen) and the merge
  is checked (#122); never a stack that moved or is in a siege that turn (#126, a live crash).
- Live crashes: `besiege` from afar marches instead (#130); agents act only from the next tile,
  and one already inside the target is refused (#131): a spy inside Caernarvon re-spying it
  crashed the game four times.
- agy seats: the answer is taken when it streams in and agy's process group is killed (#125; agy
  deadlocked in CLI teardown after answering); a no-tools line in the prompt (#128).
- `just stop`/`restart-loop` kill the loop's process group, only for setsid groups (#121).
- Recruits in training are kept per game, `<turn_root>/<game_id>/training.json` (#132).
- `install-bridge` installs into EOP master's `eopData/eopScripts` and links `parley_turns` (#129).

### Added (2026-10-25, later)
- `seats.<f>.fallback` and `fallback_reserve`: a backup brain asked once when the brain fails
  (#121). EOP master port: land crossings on both 3.3.1 and master (#127); port plan in
  `_review/2026-10-25-gemini-eop-master-port.md`.

### Added
- `parley/primer.md`: a strategy primer for rulers (Gemini's draft, fact-checked), now in every
  turn prompt after the persona ("HOW THE GAME WORKS"). Fixed before wiring: the riot threshold
  (about 70%, not 100%), same-turn storming with a ram or ladders, failed bribes don't kill
  diplomats, princess marriages.
- **Lessons across games**, per persona (keyed by the seat's display name). Every 20 turns the
  ruler's own brain reviews its last 20 turns (notes and order results) in a background thread and
  keeps up to 3 lessons with turn evidence, tagged with game, turn and code version; lessons about
  our software (rejected orders, seat errors) are excluded by the review prompt. The five newest
  are recalled in every prompt ("LESSONS FROM YOUR PAST GAMES"). `just lessons <game>` lists them,
  `just lessons-veto <game> <id>` removes one for good. Store: `<turn root>/lessons/<persona>.json`.
  Tried on Old Scratch's real turns 141–160 (argon-medium): it found the hoarded 30,000 florins,
  paper peace that never lifted a siege, and assassins left unanswered.
- **Gemini seats fixed:** `agy:gemini-4-argon-medium` plays England's full 45 KB turn in 28–95 s
  with no rejected or malformed orders (measured offline on turns 166–167); the old empty answers
  were timeouts.
- **The recruitment queue** (PR #114): at most 9 recruits waiting per settlement (units, agents
  and retrains alike); beyond its training slots, recruits arrive a turn later per full set.
- `just seat-bench <turn dir> <timeout> <specs…>` (`parley/bench.py`, PR #115): replays a played
  turn's prompt to seats and compares time, kept/rejected/malformed orders, note and plan.
- EOP fork `author/M2TWEOP-library` (Gitea, private) builds EOP master on the Gitea Windows runner
  (`.gitea/workflows/build.yml` there; 13.5 min cold, 7 min with the cached DirectX SDK).
- **Agent recruitment** (`recruit_agent`), by direct write and the game's rules: a settlement
  trains an agent only with a building that grants it (`getAgentCapability`); the faction's agents
  of a kind (on the map or in training) stay under the sum of its settlements' limits
  (`getAgentLimitCapability`); the price is the culture's from `descr_cultures.txt` (spy 350,
  assassin 500, diplomat 250, merchant 550, priest 200). Paid on the order; next turn the game's
  `spawn_character` places him in the settlement. The report shows "can train agents" per
  settlement and the faction's agent limits. Not yet run live: the capability values' meaning
  and the spawn inside a settlement are the first things to watch.
- **Standing plan:** rulers return `"plan"` (1–3 goals, each with its next step and target turn).
  The latest plan is shown in full every turn ("YOUR STANDING PLAN"), so long-range goals stop
  drifting out with old notes. A plan given as a list of goals is joined, not dropped.
- ROADMAP "Later": several humans and LLM rulers in one campaign; EOP upstream contributions, built
  on the Gitea Windows runner.
- **Reading popups:** EOP can't read a popup's text, so under autoplay the turn loop screenshots
  each game message (X11: `xdotool` and `import`) while the bridge holds it.
  - Claude Haiku reads the screenshot: missions with target, reward and deadline, riots, news.
    The text goes into the ruler's next prompt as *game messages*.
  - **Marriage offers are the ruler's decision.** He gets the suitor's real age, stats and traits
    (from `onOfferedForMarriage`) plus the reading. The turn loop clicks his accept or decline in
    the window, then puts the mouse back.
- `just tell <faction> <game> "…"`: a game note to a ruler, in his adviser thread and next prompt.
- **Ships:**
  - The report marks fleets and what they carry, and armies at sea with their fleet.
  - New orders `board` (an army or agent onto a fleet), `land` (ashore onto a land tile) and
    `blockade` (a foreign port).
  - Fleets sail with `move_army`, and only onto water. `attack` works fleet against fleet.
  - All through `moveToTile` and EOP's blockade call; untested live.
- Control file `lua <line>` runs one line of Lua in the game and logs what it returns, for live
  probes, like EOP's console.
- **Agent outcomes:** the game's mission events (bribery, assassination, spying, sabotage, marriage,
  …) report how each mission went, with the odds where the event provides them. They go in the
  ruler's next report. "Done" on an order only ever meant issued.
- **Recruiting from the recruitment pools:** the ruler pays the cost, the unit comes out of the
  town's pool, and it joins the garrison when trained. `full` control includes recruiting again.
- Income is regular earnings; one-off spending (buildings, recruits, bribes) is reported apart.
- Game messages (missions, riots, news, proposals) are cleared with `clear_messages`.
- Rulers are asked to write notes in plain sentences and short paragraphs.

### Fixed
- Orders to build something already in a town's queue are refused, and the prompt says not to.

### Added (earlier today)
- **Hot reload.** The bridge reads `parley_turns/control.txt` each tick (`reload`, `save <name>`).
  `just reload-bridge` installs, saves and reloads the bridge in the running game
  (`M2TWEOP.restartLua`). A `reloaded.txt` marker keeps this turn's settled orders from being applied
  twice. `just restart-loop <game>` restarts only the turn loop.
- The diplomacy screen left open after an answered offer is closed: likely close buttons are tried
  in turn, and the screen is scanned once so the log shows what it holds.
- `just play` prints the right hint for autoplay games.
- `just follow <faction> <game>`: a ruler's messages and turn notes, live (`--once` for watchers).
- Autoplay presses decision buttons it finds on screen (auto-resolve, decline offer, keep siege,
  occupy, ransom), catching popups no event announces. AI-turn stuck detection now waits 45 s,
  down from 120 s.
- Stuck turns write `parley_turns/ui_scan-*.txt`: every UI element that's open, found by trying the
  exe's UI names (`install_bridge.sh` writes `ui_names.txt`).

### Fixed
- A general inside a settlement now leads its garrison in the report and in orders. Before, EOP's
  leaderless settlement stack made him vanish and every order fail.
- The prompt says the treasury is from the end of the last turn, before this turn's income.

### Added (observer play)
- Orders `merge_armies` (a garrison with no general can join an army), `move_agent` and `marry`
  (a princess and a foreign general in sight). Scratch asked for all three in his first game.
- **Popups:** under autoplay every game popup is pressed after 3 s with a set default per kind
  (auto-resolve, decline AI offers, keep sieges, occupy, ransom, else OK or close). Each is
  logged with its button names, and the human slot's ruler gets a *game popups* list.
  Scrolls a watcher opens are left alone.
- `besiege` takes `"assault": true` to storm at once, and the siege scroll then gets assault.

### Fixed
- Tests use a private Gemini lock, so a live game holding the machine's lock can't stall them.

### Added (earlier)
- **Observer mode.** An LLM can play your campaign faction start to finish while you watch.
  - **Per-ruler control:** `diplomat`, `ruler` (default) or `full`, or a list of areas: diplomacy,
    armies, agents, build, recruit, taxes. The prompt, the checker and the bridge all follow it.
  - **New orders:** `build`, `recruit`, `set_tax`, `move_army`, `attack`, with build and recruit
    options, the queue, tax, public order, troops and moves in the report.
  - **Under autoplay on your faction:** governors take the areas the ruler doesn't command, battles
    auto-resolve, stuck popups are tried, the camera follows the faction and the Parley window
    shows its plan.
  - **Adviser:** a private Discord thread, opened with `!adviser`, where you counsel a ruler that
    may overrule you.
  - `new-game --control FACTION=… --adviser FACTION[=USER]`.
- **Unattended games.** `just new-game … --autoplay [--until N] [--wait S]`: the bridge clicks End
  Turn itself (from EOP's per-frame `draw` hook) once every ruler has answered, or after the
  wait. It shows a status window, retries and logs `stuck?` if a popup blocks the turn, and stops
  at turn N. The human's own ruler can now answer during its turn. Autoplay games have no humans.
- `just report <game>`: campaign report (answers, lateness, treasury and settlements over time,
  order coverage, failure reasons, order types never tried).
- `games/soak-test.json`: a scripted plan that tries every order type. Script seats now fill
  `$assassin`, `$spy`, `$diplomat`, `$foreign_character`, `$foreign_settlement` and
  `$last_settlement` from the prompt.
- **Sight and agents.** The report lists the ruler's own agents, plus foreign armies, agents
  and settlements within 10 tiles of anything it has on the map (nearest 12 each, with
  distance), and its net income from the game. New orders: `assassinate`, `sabotage`, `spy`,
  `bribe`, checked against what the ruler can see, then re-checked by the bridge in the live
  game before anything native is called.
- Repo scaffold: README, CHANGELOG, HANDOFF, ROADMAP, CLAUDE.md, justfile, .gitignore
  (`_review/` and `_reviewed/` stay local).
- Design draft: `docs/superpowers/specs/2026-10-23-llm-diplomacy-design.md`.
- Plan 1 (bridge and turn loop), Tasks 1–5: the `parley` package.
  - Protocol models and order validation. Orders that refer to things a faction doesn't
    own, or cost more gold than it has, are rejected with a reason.
  - Atomic file bridge over a shared turn directory.
  - Prompt builder. Last turn's results, rejections included, reach the LLM in its own
    numbering.
  - Seats: Claude (`claude` CLI on the subscription), Ollama, Gemini (`agy`), and a fake
    seat for tests.
  - Orchestrator. A failed seat or any other error ends that faction's turn with empty
    orders, never a hang. One orchestrator runs per turn root. A reloaded save gets
    answered again.
  - Save backups, one per poll, keeping 20.
  - Simulated game (`just fake-game`) and `just run`, `just seat-smoke <brain>`.
- `docs/eop-api-notes.md`: verified facts about EOP's Lua environment (file I/O is available).
- Plan 1 Task 6:
  - `just install-m2ex`, `just install-eop` (EOP 3.3.1 as `mods/parley`, with vanilla campaign files) and `just probe`.
  - Running on Linux through a Steam launch-option swap.
- Plan 1 Task 7: the game-side Lua bridge (`lua/parley_bridge.lua`, `just install-bridge`).
  - It writes the state report at turn end and applies prepared orders at the next turn start, never blocking the game.
  - It re-checks every order against the live game and reports late orders back to the LLM.
  - `heartbeat.txt` keeps turn folders ahead.
  - It's tested in LuaJIT via lupa against a fake of the EOP API.
- `docs/JOURNAL.md`: a build log for the public write-up and the installer.
- Plan 2, the Discord table:
  - message store and outbox (SQLite), and rulers' `messages` (capped, validated);
  - diplomacy in turn prompts, and chat replies between turns;
  - the Discord bot: a per-game channel as the public table, `!private <faction>` threads, and
    turn cues ("all rulers have decided").
- `just notes`: a god view of rulers' notes, orders and messages.
- Memory: each prompt carries the ruler's last 5 notes and what changed since its last turn.
- Chat replies are grounded in the ruler's real report and in what the game can enforce.
- Gold and land reaching a human are announced in the pair's private thread only.
- Rulers may message only factions someone plays. The answer schema no longer asks LLMs for
  bookkeeping fields.
- Persona library (`personas/`): the 1080 historic roster (18 rulers) and 6 permanent
  archetypes. Use one with `persona = "@id"`. Example game: `games/historic-1080.toml`.
- `docs/WRITEUP.md`: the complete guide.
- `@scratch` archetype (Old Scratch): the Moriarty of the table, playing to win inside the game,
  with holodeck rules pinned by a test.
- First live game: Claude's Venice and Ollama's Milan played 3 turns against the author's England, end to end.
