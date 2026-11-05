# Handoff

## 2026-11-05: phase 1's last case fixed; docs rewritten for outside help; QA runs over ssh

**Most important:** `marry_foreign_general` is fixed (the princess was disgraced, not married; the
bridge now tells the ruler). **Phase 1 is done:** the full no-click bench on the test laptop came back
clean, 74 pass, 23 skipped (played-turn cases), 0 fail (`runs/qa/2026-11-05-0623-all.md` there,
37 min 40 s). The phase gate is open for phase 2: the played-turn cases, on the test laptop.

**Phase 2 (from 06:42, the test laptop):** played-turn runs found five bugs, each fixed with a test that
fails without it. Merged: #367 (frozen AI let go after 3 s: a played turn ~80 s, was ~5 min). Open,
running together now in the chain (test/phase2-integration 78195fd): #375 (End Turn waits up to
20 s for this turn's agent missions, the covert sabotage race; M.qa.load defers during an AI turn,
the envoys crash: a load 2 s after End Turn), #380 (the QA hold applies on the player's turn only:
it had stopped stuck-turn recovery and Denmark's turn stood 9 min), #381 (a faction whose envoy
parleys at its turn start stays awake that turn: a frozen AI makes no offer), #372
(recruit_merchant builds a market on the bench save; one level per town after review).
Diplomacy's ai_offer_accepted/second_offer_asked_again have never passed (no offer on screen).
The chain (`/tmp/phase2_chain.sh` there; picks up /tmp/integ.bundle before each suite; stops if
qa.lock is left or at 22:00) runs field, navy, popups, siege, towns, instant, envoys, covert,
diplomacy, smoke. Logs `logs/phase2-chain.log`, `logs/phase2-<suite>.log`; `just qa-summary`.

**Privacy (11-05):** scripts/crash_report.py captured the **whole desktop** (`import -window root`)
before every crash-watch relaunch. Fixed in #376 (game windows only) with
tests/test_no_desktop_capture.py forbidding any whole-screen capture. **20 old reports in
runs/crashes/ on the main machine hold full-desktop screen.png files** (gitignored, never published; not opened);
deleting them is the author's call. Caveat: X11 `import -window <game>` can still include a window lying
on top of the game window.

**Merged 11-05 later:** #365 `just work-until HH:MM` (a Stop hook holds a standing order; the author
set 23:00), #366/#370 STANDARDS fixes, #368 parallel-seats test by barrier, #369 bridge log cap
(20 MB, rotated before a relaunch). Posted EOP-Labs/M2TWEOP-library#91 (papal vote and family
offers from Lua). agy: only Gemini Argon is out of quota (till 11-06 17:41 UTC); Flash works.
Then #374 `just qa-summary` (written by agy, checked here), #376 privacy fix, #377 a QA crash writes
a crash report before the relaunch. agy is building `just ruler-eval` (STANDARDS ruler-eval-harness)
in <scratch dir> (branch feat/ruler-eval).

**Merged earlier 11-05, stacked:** #361 (marry fix) → #362 (README, CONTRIBUTING, guide;
`EOP_BUILD=master just install-eop`) → #364 (QA over ssh: a held game isn't hung, the run's own
probe passes its lock, the run borrows the desktop's display). Then refresh the public GitHub copy
(`python3 _review/scrub_public.py main <dir>`, gitignored because it lists what it hides; one
snapshot commit on c6e8dca, to GitHub and Gitea mtw2-public).

**the test laptop:** powers off 23:59, back 03:00, then waits at the LightDM login screen (nobody logged
in: no game). `PARLEY_POWER_OFF=23:59` in its parley.conf (#359). The author said it's ours until 23:00
today. It can't fetch from Gitea (no credentials): ship branches as git bundles. A stray
`parley_turns/qa.lock.test-probe` is there (harmless; the guard wouldn't let me move it).

**Drafts for the author, not posted:** `_review/2026-11-05-eop-discord-question-draft.md` (ask EOP's
Discord how to press the papal vote and family offers from Lua) and
`_review/2026-11-05-eop-issue-89-comment-draft.md` (issue #89: mercenaries now by direct write,
agent costs from a fixed table).

## 2026-11-04 night: the test laptop runs the bench; phase 1 down to marry_foreign_general

**Most important (then):** phase 1 had one open case, `marry_foreign_general` (fixed 11-05).

**the test laptop (<test-laptop-ip>) is the test machine now.** The game runs there with no clicks (Proton 10,
`PROTON_USE_WINED3D=1 WINEDLLOVERRIDES=d3d9=n,b` so EOP's d3d9 hook loads first), and the full
no-click bench ran in 38 min (71 pass, the same as the main machine). Every step is in
`_review/2026-11-04-the test laptop-setup-log.md`. Quirks:
- One Steam account runs the game on one machine at a time: launching on the main machine while the test laptop
  plays does nothing (Steam takes the URL and starts no game).
- A locked desktop stalls the game behind the lock screen; `relaunch-game` now refuses at once on
  a locked session (#355). the test laptop was **left unlocked with auto-lock off for the night**.
- It powers off at 23:59 local and back on at 03:00 every night (seen 11-03 to 11-05; set
  outside the user crontab). `PARLEY_POWER_OFF=23:59` in its parley.conf makes a QA run that
  would cross it refuse to start. After 03:00 it waits at the LightDM login screen: nobody is
  logged in, so no game can start until someone logs in (or LightDM autologin is set: The author's call).
  `relaunch-game` now says so at once; it also starts Steam from ssh (borrows the desktop's DISPLAY,
  reads PARLEY_STEAM_URL from environment.d). A cut-off test left a qa.lock there (11-05 03:47,
  real campaign not running before): `just qa-restore --real games/local/scratch.toml` after login.
- Its Steam asks which launch option to use; `~/.config/environment.d/parley.conf` sets
  `PARLEY_STEAM_URL=steam://launch/4700/option0` (#353).
- Its game is held (`parley_turns/paused.txt`): the copied bridge.txt has autoplay on and no rulers
  run there. Its checkout is on main (d69668b, 11-05). **Open:** it has no Gitea credentials, so
  `git fetch` fails ("could not read Username") and code goes over as git bundles. Fix: a read-only
  Gitea token (or deploy key) for it; the author's call, since it's a new credential on that machine.

**`marry_foreign_general` fixed (11-05):** the princess wasn't married, she was disgraced. A probe
listing every copy of both characters showed Cecilia's record going `alive=false, spouse=nil` 10 s
after the order (with popup message 160), the suitor still Polish and unmarried, in both 11-05
probes; she vanished in all 4 runs since 11-04 (the bench save replays the same roll). Poland's AI
wasn't frozen in England's turn (freeze=0), so a frozen suitor faction isn't the cause. The game has that outcome: event_titles.txt
`{mission_marriage_fail_and_removed}Princess Disgraced!`, and it fires no mission event. The
bridge now remembers each marry order and reports a princess found dead with no mission line when
the news is read; the case reads `M.qa.news`. Passed live on the test laptop. EOP's `character:marry`
(EOP-Labs/M2TWEOP-library `actionsStrat.cpp:204-219`) only issues the game's own action (type 34).

**Merged tonight:** #353 (PARLEY_STEAM_URL), #354 (the gate ignores heredoc text), #355 (locked
desktop), #356 (`repair_queued`: a repair is paid at once with at most one item ahead of it; queue 2
pays nothing at queue time; proven on the test laptop's towns suite), #357 (`crossing_in_one_turn`: the
fleet must end beside the far shore; it stopped at 118,146 with 27 of 80 moves left because
`M.qa.sea` picked an unreachable tile; proven on the test laptop's navy suite).

**`marry_foreign_general`:** with England's own princess and a valid suitor on the bench, the order
is taken, the princess leaves the map within seconds, no mission event comes, and 25 s later the
suitor (Boleslaw Herman, Poland) is still Polish and unmarried. A rejected proposal looks
different: the event fires and the princess stays (Ysabel, France, live). Next: one played turn
after the proposal (phase 2), or EOP 3.3.1's own marry code.

**Needs the author:** re-lock the test laptop; the main machine's Steam showed an on-screen notice on a launch tonight
(likely Steam Cloud, after the game ran under the same account on the test laptop); start the Discord
bot if the queued updates should post.

## 2026-11-04: repair_queued passes; the phase gate had a hole; Jigsaw is public

**Most important:** phase 1 still has two open cases (`marry_foreign_general` half found,
`crossing_in_one_turn` untouched), and the gate stays shut until a clean
`just qa all kind=instant`. Answer "now what?" with the next step; start only on the author's go.

**State at session end:** the game is running on scratch at turn 74 with the loop stopped
(`just play scratch` to resume). Live probes changed that campaign: Michault and Karl were
moved, Lorin de Calais spawned, and a spawned princess vanished. Saves are expendable. The main
checkout is on `fix/qa-open-cases` (merged); switch to main before new work. The old
`.claude/worktrees/session-end` (11-01, merged #347) is still there.

**Done:** `repair_queued` passes on the bench (no-click, instant). The 11-01 cache fix made the
repair show, and the case's charge rule was wrong: a repair is paid in full when queued, even
behind others (London 13473 -> 13073 with the queue at 1). The fake game in
`tests/test_qa_towns_lua.py` now charges a repair the same way.

**Fixed:**
- The forced-events gate (`.claude/preflight.toml`) missed `timeout 590 just qa ...`, so a run
  played smoke's turn cases while phase 1 was open (`tests/test_preflight_match.py`).
- The park took the turn from a stale heartbeat after a relaunch (bench turn 6, real 74), and
  the restore then refused. It now uses the bridge log's newest campaign load when that's newer.

**Found, open (phase 2, click/turn):** smoke `teleport` crashed the game right after
`spawn_agent`'s played turn (11-04 10:12:58, `runs/qa/2026-11-04-1012-towns.md`).

**Elsewhere:** PRODUCT.md (#348); Jigsaw public v0.1.0, pinned by tag (CLAUDE.md); the Gitea
container's DNS had died, so every GitHub mirror failed (gitea-infra #18).

**`marry_foreign_general` (still fails, cause half found):**
- 11 fails had one setup cause: spawned characters can't marry. A spawned general has
  `isFamily` false, and the game ran no proposal to him; a spawned princess vanished at the
  order. Live on the real campaign, a real princess (Ysabel, France) and a real bachelor (Karl,
  HRE) gave `marriage proposal: not successful (chance was 20%)` 5 s after the order.
- The case now uses real family members (`M.qa.wooer/princess/bachelor`). The suitor is
  unmarried, of age, of the wooer's religion, at peace, leading a field army, and not his
  faction's leader or heir. On the bench a heir (Affonso) took no proposal, and a governor
  moved out of town wasn't in sight.
- `M.on_agent_mission` no longer drops a report when one field can't be read, and logs if
  it can't read one at all.
- **Open:** on the bench, a valid proposal (Constance of France to Boleslaw Herman, Poland)
  makes the princess leave the map with no mission event, no message, and the suitor still
  unmarried 20 s on. Every marriage event logged so far is a failure. Next: check the suitor
  and the princess after one played turn (phase 2), and read EOP 3.3.1's own `marry` (the
  indexed EOP source is master, and its index is partial).

**Next:** `crossing_in_one_turn`; then `just qa all kind=instant`; then the marriage outcome
above.

## 2026-11-01 (06:00): order fixed by a gate; quiet world built, not bench-proven; phase-1 rerun running

**Most important:** no-click first. `just qa` now refuses turn runs while the newest
`runs/qa/*-all.md` has a fail or inconclusive (#346). This session started on the quiet world
(turn work) over phase 1's open cases until the author asked why; Uncle J's audit traced it to the
04:45 handoff's order and to no-clicks-first living only in memory. Both are now in STANDARDS.md
(`phase-order`, `no-clicks-first`) and checked by the gate.

**Running:** a full no-click baseline, `PARLEY_NO_X_INPUT=1 just qa all kind=instant --real
games/local/scratch.toml`, started 05:27 on main as of #345 (log in this session's scratchpad,
report lands in `runs/qa/2026-11-01-*-all.md`). It parks and restores scratch.

**Merged:** #342 (young Pope, with the Uncle J session's agy job), #343 (journal), #344 (leader/heir;
uv.lock fix), #345 (towns: turmoil, rebel chance, plague; event splits), #346 (the gate, bench proof
for holds, STANDARDS). Live writes checked by hand on scratch only (Pope 55->30, leaders 54/49->45,
11 towns calmed). **No hold counts until `instant/quiet_world_held` passes on the bench.**

**Unmerged:** `.claude/worktrees/quiet-case` (branch `feat/quiet-bench-case`): the
`quiet_world_held` instant case appended to games/qa/instant.toml; 2 tests fail there (one is
`test_the_instant_suite_loads_and_needs_only_the_garrison_town`, likely a case-list assertion;
the other not read). `feat/far-board` still needs its navy bench proof.

**Next (in order):**
1. Read the new phase-1 report. Fix each fail/inconclusive with a bench case that fails first:
   `marry_foreign_general` (order ok, no mission), `crossing_in_one_turn` (fleet a tile short,
   118,146 vs 118,145), `repair_queued` (nothing repairable after 50% damage).
2. Finish and merge `quiet_world_held`, then rerun it so the four holds count.
3. Prove `feat/far-board` on the navy suite (run from that branch's bridge).
4. Only then: a no-mouse decision press through EOP (marriage/AI offers/papal vote, item 4), then
   the remaining interrupt events.

**Quirks:** agy quota out ~127 h from 04:52 (resets ~11-06). `just install-bridge` copies; the game
needs `just reload-bridge`. Never `git commit -a` in the main checkout: uv.lock drifts there.
The Uncle J session and its agy job edited this checkout at 04:48: agy edit jobs go in worktrees.

## 2026-11-01 (04:45): phase 1 at 71/1/2; screens-off root cause; far board unmerged

**Running:** scratch campaign turn ~51 (loop, bot, crash-watch, screen-awake). Watch restarted at wrap-up.

**Phase 1 (no-click) bench, 04:42:** 71 pass, 1 fail (`marry_foreign_general`), 2 inconclusive
(`crossing_in_one_turn` setup expects the fleet a tile off; `repair_queued` found nothing damaged),
23 skipped (click phase). Was 59/11/5/22 at 10-31 15:18. Report: `runs/qa/2026-11-01-0442-all.md`.

**Merged this session (#325-#339):** tiles armies can't stand on skipped (#326); tile visibility >= 3
counts as seen (#327; rulers' sight lists were dropping enemies beside own towns); a load clears agent
order records (#328); park waits for an on-screen decision + Heretic decision time 480 s / bridge
DECIDE_WAIT 540 (#329); reload-bridge waits for the reload (#330); board by whole-army split, armies
aboard named by their unit's general (#331); land by whole-army split (#332, the author's question: the
landed army was the general alone); screen-awake inhibit (#333); crash-watch and the watch probe the
game before calling silence a crash/stall (#334/#335); NE Catapult, build cost on start, storming to
phase 2 (#336); **governors were never switched off** (0/1 written to EOP booleans; #337); watch
STUCK reads the newest stuck line, stale after 3 min (#338/#339). scratch.toml (local): seat_timeout
600, autoplay wait 720.

**Screens off = game crawls** (bench load 66.5 s vs 6.5 s, A/B 19:11/19:14; focus is NOT the cause,
A/B 18:5x). agy's research (`_review/headless-display.md`): DXVK vsync waits on vblanks the NVIDIA
driver stops with DPMS off. The game does use DXVK's d3d9 (checked). **Untested fix:** `dxvk.conf`
with `d3d9.presentInterval = 0` and `d3d9.maxFrameRate = 60` (game dir and mods/parley), relaunch,
`xset dpms force off`, one-case bench. The author: test it when he steps away. screen-awake stays until then.

**Papal election stalled turn 50 for hours** (minimized; bridge hands-off). The tick vote found the
vote scroll live (03:47) and voted, but the xdotool click didn't land (the author had the mouse); the author voted
by hand; results ran clean. No-click papal vote = its own session (forced-election bench case, then a
gameSTDUI press). My blocking AskUserQuestion also stopped the 20-min cron for hours: while the author is
away, never block on a question; post it to Discord instead.

**Unmerged, needs a bench proof:** `feat/far-board` (78ea8ee, pushed): a board order to a far fleet
walks to a land tile beside it and a pending board embarks it by split when adjacent (the author's choice).
Written by agy, reviewed; garrison-key bug fixed in review; 1520 tests pass. Prove with the navy suite
plus the captain round trip (`$scratchpad/captain.sh`, a captain-led army: does its name hold across
board/land? The author asked).

**Next (in order):** 1. the quiet world for turn cases (young Pope via EOP character age after each
bench load first, then the rest of `games/interrupts.toml`; the #340 gate blocks turn runs until then);
2. prove and merge far-board; 3. DXVK screens-off test; 4. no-click papal vote; 5. marry_foreign_general
(game runs no mission; religion and age ruled out); 6. phase 2 (click) run.

## 2026-11-01: turn-playing QA runs are gated on interrupting events

A new preflight gate (`.claude/preflight.toml`, enforced by the Refinery's global hook) refuses any
`just qa` run with a turn case until every event in `games/interrupts.toml` is held (with code proof)
or ruled out. **Only AI attacks are held today, so turn-playing runs are blocked.** `kind=instant` runs
still go. Next: build the quiet world the 11-01 session planned (young Pope after each bench load,
then the rest of the list), record each in `games/interrupts.toml`, and the gate opens by itself.
Never delete an event to get a run through.

## 2026-10-31 (late): QA bench hardened (#320-#324); phase-1 rerun is next

**Running:** the scratch campaign, turn ~7. It advances unattended because run9's loop is paused. No
watchers or QA runs are left behind.

**Merged #320-#324:**
- #320: the restore reads the real turn from the log.
- #321: EOP "Cannot create M2TWEOP save file" box. Missing-save loads are refused, `scripts/eop_error_box.sh`
  detects the box, and crash-watch closes it and relaunches. The bench case `load_missing_save_refused` passes.
- #322: the hold is kept until the real campaign reloads; the relaunch holds under a qa.lock; there's a
  canary ready gate after each bench load; the report has a reload column and flags slow loads.
- #323: the park holds first; the bridge must answer before the first load (180 s); any smoke pass
  records qa.last_smoke.
- #324: STANDARDS.md parses.

**Root cause of "moves don't happen":** a busy game. While AI turns play, loads take 60-75 s and
`moveToTile` gets ignored. On an idle game every move case passes.

**Next:**
1. Gate test, never run live: `PARLEY_NO_X_INPUT=1 just qa field kind=instant case=move_army case=spawn_army --real games/local/scratch.toml`.
   Then the full phase 1: `just stop; PARLEY_NO_X_INPUT=1 just qa all kind=instant --real games/local/scratch.toml`.
2. Fix `garrison_general_leaves` (William won't leave London) and `withdraw` (spawn lands a tile off).
3. The author's call: rank ruler-budget (#8) and wishes-carried-out (#15) higher in STANDARDS.
4. Phase 2 click work overnight.

## 2026-10-31 (00:40): papal crash cause found; generals leave towns by split; fix rounds paused

**Running:** run8 turn ~62. England is down to London + Nottingham (lost Paris, Caen before T40, York
T55-60), treasury ~0, income +1.4k: ruler quality is a question for the author, separate from tonight's
bugs. Loop, bot, crash-watch unit, `WAKE_ON_AUDIT=1 just watch scratch`, a papal-election watcher.
New fix rounds paused at 00:40 to save Claude usage (agy is out until ~11-06); wakes still get fixed.

**Papal crash: cause found.** With our Lua doing nothing in `onScrollOpened` for papal scrolls
(#289 `papal_hands_off`), 4/4 QA field runs played the crash turns 59-67 clean (3 of 4 crashed with it
off). #290 makes hands-off the default (run8 too, live 23:41) and finds the ruler's vote from the
tick (one guarded `getUiElement("papal_election_scroll")` every 2 s after the death notice), never in
the callback. **Unproven:** a live vote found from the tick (watcher running). #275/#280/#283/#288
stay (harmless guards).

**Merged since 22:40 (#288-#293):** End Turn waits for offers (#288); papal hands-off switch (#289)
and default + tick vote (#290); QA home pick, turn wait 240 s > hold, no false LOST? after QA (#291);
generals inside a town leave by `factionStruct:splitArmy` (#292), with the unit from the stack's
`getUnit(i)` (#293). **Live:** the split works but takes effect a moment later (the immediate
"still in London" log line is misleading; next-turn check is right; QA move_army from London passed).

**Open:** 1. prove the tick vote on a live election; 2. QA field flakiness: spawns off by a tile when
occupied, spawned armies absorbed into Nottingham's garrison during AI turns (governors? retreats?
unknown), a stuck QA turn 80 popup; 3. `garrison_general_leaves` not yet reached on the bench with
#293; 4. France ~60% order rejections; 5. 17 MB bridge log rotation; 6. older items below.

## 2026-10-30 (22:40): papal crash narrowed to a click race; crash-watch is a unit; QA mostly green

**Running:** run8 turn ~55. Loop, bot, campaign watch; crash-watch is now the systemd user unit
`parley-crash-watch` (`just crash-watch`, `just crash-watch-stop`; #282). Never start it from a
background job. QA: `just qa covert` 6/7, `just qa field` 6+ of 13 (last run crashed mid-way).

**Merged since 20:10 (#279-#286):** loyal spawned generals + scene setup (#279); papal notice left
alone 15 s (#280); crash dialog caught at once, post-QA relaunch reloads run8's kept save (#281);
crash-watch unit (#282); papal window: loop presses nothing during an election (#283); marriage
offers no longer answered by other prompts, End Turn waits for the spy report (#284); QA funds and
assassin placement (#285); **sight: foreign armies with no `leader` (forts, some field stacks) are
now seen** (#286; run8's Captain Nicholas vanished from England's reports after T49 because of this).

**Papal crash, current understanding (NOT fixed):** #275 (no bridge UI calls) refuted 20:48; #283's
papal window helps notice-led elections but a **results-only** election (no notice) still crashes
when the turn loop clicks a decision in the same second: 20:48:34 (marriage decline) and 22:28:59.2
(marriage decline) → crash 5 s later; 20:56:36 same pattern survived once. Next: answer AI offers
during AI turns without screen clicks (EOP diplomacy/decision API? script command?), or hold decision
clicks after "ending turn" until the player's turn starts if the game tolerates waiting offers. The
QA field run reaches turn 59/62 (a marriage + results-only election) to reproduce it.

**Open:** 1. the papal click race above; 2. confirm #286 live (bridge log probes `sight: ... no
general` / `tile visibility`); 3. QA field cases after the papal crash point; 4. France's ~60% order
rejections; 5. 17 MB bridge log rotation; 6. older Next list below.

## 2026-10-30 (20:10): QA bench (`just qa`) built and proven live; run8; agy out for the week

**Running:** run8 (started 15:27 after run7's England was conquered at T108), turn ~37, England 5
towns (took York + Paris). Loop, bot, crash-watch, `WAKE_ON_AUDIT=1 just watch scratch`.
The author is away; he gets `# 🛠️ MTW2 UPDATE` posts in the Discord chronicle at milestones and hourly
(memory periodic-updates).

**The QA bench** (spec `docs/superpowers/specs/2026-10-30-test-bench-design.md`, plan
`docs/superpowers/plans/2026-10-30-qa-bench.md`): `just qa <smoke|covert|field>` keeps the real
save, stops the real loop/bot/crash-watch, plays scripted cases in the real game on a copy under
`game_id qa-<suite>`, writes `runs/qa/<stamp>-<suite>.md`, then loads the kept save back and restarts
everything. Stop `just watch` before a run, restart it after. Gate: one real autosave between runs
(use the scratchpad-style wait: newest `mods/parley/saves/Autosave*.sav` newer than
`parley_turns/qa.last_restore`). `just qa-restore` finishes a restore by hand (lock-gated).
**Live (the author agreed 10-30):** the live campaign is the acceptance step; fixes are first proven by QA.

**Proven live by QA today:** #255 spy report closed; sabotage; #263 across-the-sea refusals; #267
no-moves guard; withdraw; merge_armies; spawn/teleport/skill/money helpers; park/restore (many
times); #273 hang recovery; #275 papal election ran clean once (19:47) with no UI call.

**Open (next):** 1. PR from the field round-2 agent (move_army stopped a tile short; march_on siege
case needs a hostile target; march_on_across_sea army vanished; garrison case needs a home town;
covert aborted waiting for its turn) — review, merge, rerun `just qa covert` and `just qa field`;
2. a few more clean papal elections before calling #275 proven; 3. France's ~60% order rejections
(disband count 0, unaffordable orders, agents a town can't train); 4. bridge log is 17 MB and never
rotates; 5. the unexplained run8 T18 Paris move (field case `garrison_general_leaves` is meant to
reproduce it); 6. then the older Next list below (SAGA live A/B, Heretic slots).

**Delegation:** agy's weekly quota ran out at 17:25 (resets ~11-06); Claude agents do code work.
agy can now read the game install (Uncle J). Close the Chrome tab that slowed Heretic (still frozen).

## 2026-10-30 (14:50): back from the outage; seats were dead 83-96; Heretic slow from a Chrome tab

**Running:** run7, loop + bot, crash-watch, `WAKE_ON_AUDIT=1 just watch scratch` (now with SEATS).
England is down to London (lost York at report turn 87; treasury -18.8k, -1.9k/turn); France 8 towns,
+4.7k/turn. England played most of 83-96 without a ruler (see below). Restart only when England is lost.

**What went wrong:** from 12:36 every England and France seat timed out (420 s, 0 orders), 50 in a
row; the watch couldn't see it (#258 adds SEATS). Cause: Heretic decoded at ~6 tok/s per slot instead
of ~25. Not the GPU fit, not thread count (4/5/6 threads tested, no change; compose left as it was),
not CPU priority or pinning. **A Chrome renderer (pid 79828, a background tab spinning at 100% since
boot) was the cause**: SIGSTOP on it → 25 tok/s at once, SIGCONT → 6-8 again. Likely GPU work (WebGL/
video) competing with Heretic. **It's left frozen (SIGSTOP)**; `kill -CONT 79828` thaws it; closing
that tab is the real fix (the author: which tab?). Check for such a tab after every reboot: a session restore
reopens it.

**Merged today after the outage:** #254 relaunch (live-proven at 12:14), #255 spy report scroll (not
yet seen live; a one-shot grep waits), #256/#257 wake procedure (agy first), #258 SEATS watch check.
The author, 10-30: fix as you go, also while he's away; restart Heretic freely during testing.

**Next:** 1. confirm seats return orders now; 2. close the Chrome tab for good (the author); 3. the 12:05
crash: cause unknown (after AI agent missions; #255's field read is a suspect only if it repeats);
4. SAGA live A/B (below).

## 2026-10-30 (10:20): stopped for a planned power outage; how to resume

**Stopped cleanly before the outage** (the author, 10:15): run7 at game turn ~71; the newest save is the
game's per-turn `Autosave.sav`. England holds London and York (lost Caen T58 to Portugal, Nottingham
T60 to Scotland while holding 11k florins: #247 is the answer); France 8 towns (took Bruges T70).

**To resume after power returns** (Claude does all of this when the author says "continue"):
1. GPU: Heretic must be up: `curl -s 127.0.0.1:8090/health` returns ok. If not, the GPU came back
   in shared mode: `just gpu mtw2` in the author's tooling repo, wait for health ok.
2. `just play scratch` (loop + Discord bot) **before** the game, then `just relaunch-game`: it starts
   the game through Steam, presses the M2EX launcher's **Run mod** (retries, #248) and the menu's
   **Continue Campaign** (the newest save). If it fails, do it by hand: launcher window "M2TWEOP",
   Run mod at screen (956,534); game window "Medieval 2" at (4,30) 1600x900, Continue Campaign at
   (376,361). Confirm with "bridge reloaded"/orders lines in parley_turns/parley_bridge.log.
3. `just crash-watch` (relaunches after a crash; since 10-30 it starts the user unit
   `parley-crash-watch` and returns at once, so it needs no background job), and
   `just watch scratch` with run_in_background in Claude; restart the watch after every wake.
4. Ping the author only for screen-only help: Discord chronicle via the outbox (memory: ping-author-on-discord).

**SAGA verdict (both rounds, `_review/2026-10-30-saga-experiment.md`):** no tool variant beats the
full prompt (tools on a slim prompt: passive; hybrid: no model used a tool, Haiku ties; planner + 4
controllers: more orders, loses 6-7 of 8 on quality, ~2x cost). Don't wire into live play. Untested:
a planner whose goals persist over several live turns; Heretic in saga mode.
Config is local: `games/local/scratch.toml` (both `heretic:think`, `steward = true`,
`seat_timeout` 420, autoplay `wait` 540).

**Merged since the section below (#240-#250):** per-faction strategy notes + England's (#240-241);
enemy army composition, sight by EOP `getTileVisibility` (confirmed live, #242); revolt risk per town
+ siege/assault checks as advice (#243); order cap scales with the realm, papal crash trace,
outlive status (#244); uv.lock restored + `tests/test_uv_lock.py` (#245); `hire_mercenary` by the
game's rules (#246, not yet seen live); THREATS gives the gap in men, costs, arrival (#247);
relaunch retries Run mod (#248); rulers start as soon as their own report lands (#249: France's
orders were late behind England's); a heartbeat line while waiting for rulers (#250).

**Live results:** siege equipment call ran without a crash (France kept the siege of Bruges T70 and
took it; queued count not seen). Papal results crash #6 at 08:41 (T61): the trace shows the bridge
finished its calls (`getUiElement returned, found=false`) and the game died after: a game-side crash
while that scroll is up; the same turn passed on reload.

**SAGA experiment** (`feat/saga-tools`, not merged; `_review/2026-10-30-saga-experiment.md`):
round 1, tools on a slim prompt, lost for every model (models don't pull; passive play). Round 2
(hybrid prompt; SAGA's planner + per-domain controllers) cut short by the outage: see the review
file for what finished.

**Next:** 1. SAGA fair test (the author: give it a real chance; memory saga-fair-chance): a LIVE A/B over 20-40 turns, one seat in saga mode with a persistent plan carried across turns (replan every ~6 turns or on an emergency), Sonnet as brain (Heretic too when a slot is free), the other seat single-shot; compare towns, income, refusals; also try native tool calling; 2. popup decider
and chat share Heretic's 2 slots with two thinking rulers (timeouts): a 3rd slot or another brain;
3. watch #246 hire_mercenary and the revolt flags live; 4. the 30 EOP gaps and legal actions
(`_review/2026-10-30-legal-actions.md`: split_army, denounce/acquire, crusade join, demolish);
5. papal crash: game-side, consider pressing nothing and waiting longer on that scroll.

## 2026-10-30 (08:10): strategy round: economy, fleets, sieges, militia, lessons, EOP map

**Running:** run7 at turn ~55, both rulers `heretic:think` + `steward = true`, `seat_timeout` 420.
England: 3 towns, income 3,488/turn (was 806 at T47), every garrison filled, at war with Scotland,
plan "besiege and assault York by T55". France: 7 towns, 14 armies, income 2,618, at peace.

**The author's strategy rulings (10-30):** no rigid region pace (behind early, then a financial
powerhouse steamrolls); debt to take a town is fine, don't shed troops when negative; scout ships +
one big fleet sinks troop fleets; militia = garrison duty (order cheaply, defend sieges); garrison
units by order + cheap upkeep + defence; both rulers think (rulers on many machines later).

**Merged #230-#238:** debt is a tool (#230); enemy fleets and their cargo + THREATS line (#231);
lessons review sees OUTCOMES (#232); goal block: economy, phase, stuck-plan by target town (#233);
primer playbook from game files (free slots by wall level, militia; #234); besieging armies queue
siege equipment via EOP's siegeSettlement(town,false) "maintain" path (#235, **not yet seen live**:
a background check waits for "keeps the siege"); steward garrison units from `parley/data/units.json`
(free militia first, else best defence per upkeep, upkeep <= 1.5x cheapest; #236); primer on
siege engines and multi-stack attacks (#237); `docs/EOP-COVERAGE.md` + `just eop-coverage` (#238:
3,053 EOP members, ~239 campaign-relevant used; 30 highest-value gaps listed up top).

**Lessons to veto (the author's call, `just lessons-veto <id>`):** 41a7d878, da4def8d, 19d0035a,
9a6a978c, 05462f8d, 4ef256cb, c6c96c95, d2673dc3, e3b1e16b (contradicted by run5/run6 outcomes).

**In review:** the author's `~/Downloads/england-m2tw-guide.md` (agent ->
`_review/2026-10-30-england-guide-review.md`); proposes a per-faction strategy note.

**Next:** 1. live-check siege equipment (siege_queue > 0) and the T60 lessons review; 2. EOP gaps
worth building first: enemy army composition, which own armies can reinforce a fight, reachable
tiles (`getMovementExtents`); 3. the 40-order cap; 4. after 18:10 UTC: Gemini rechecks the
strategy/naval research; 5. diplomacy screen left open; papal results crash; slow seat blocks.

## 2026-10-30 (07:00): helping the small ruler; Heretic thinks now

**Running:** `scratch` run7 (turn ~46), loop, bot, crash-watch, `just watch scratch` (background).
England and France now on **`heretic:think`** with **`steward = true`** (the author, 10-30: thinking on for every Heretic ruler;
benched 170-214 s alone vs ~37 s; live with both thinking, France 208-233 s and England timed out
at 300 on turn 45, so `seat_timeout` 420 and autoplay `wait` 480 since 07:05; seat errors now read
"heretic failed", not "openai failed" (#228: Heretic runs through the OpenAI-compatible seat)).
The game file is local: `games/local/scratch.toml`. Restart rules as in the section below.

**The author's rule, widened 10-30:** work may be offloaded (steward, checker) **so long as the LLM's
wishes are always carried out**: fill gaps, warn, catch orders that can't work; never override or
block an order the game would accept; tell the ruler what was done.

**Reviews (local, `_review/`):** `2026-10-30-run6-england-loss.md` (57% of Heretic's orders refused
vs 4% for Sonnet; ~90 turns marching at towns across the sea with no fleet; garrisons stripped;
London rebelled at T186 after a tax rise) and `2026-10-30-mtw2-strategy.md` (draft, thin sources:
have Gemini check it against TWC after 18:10 UTC).

**Merged this morning:** #218 compaction hook (`scripts/compact_context.sh`, NOTIFY-CLAUDE §6;
fired correctly on its first compaction), #219 Discord lines name the ruler's model, #220 uv.lock
restored, #221 refused orders at the top of the prompt, #222 besiege/agent walks across the sea
refused (bridge reloaded live at T44; check `by_land` in England's next state.json).

**Then merged and live:** #224 (reload releases a frozen turn; bridge reloaded at T46), #225
steward garrison backfill, #226 leaner prompt + THREATS + primer rules of thumb. Loop restarted on
them at ~06:55. Reload the bridge only during England's turn (no frozen faction) until #224 has been
in a reload once.

**Bugs seen, not fixed:** the diplomacy screen stays open after accepting an AI offer (05:15, run7;
cleared by focusing the game and pressing Escape); England strips garrisons (the steward is the fix).

**Next:** 1. watch the next ~10 turns: refusal rate (was 23% run7, 57% run6), steward notes,
thinking-turn times vs the 300 s cut-off, THREATS lines vs the game; 1b. the 40-order cap
(`validate.py` MAX_ORDERS) counts refused orders and will cut a big realm's turn (and the steward's
recruits first): scale it with settlements + armies before any realm passes ~15 settlements; 2. after 18:10 UTC: Gemini checks the strategy draft, England on Gemini to
compare; 3. diplomacy screen left open; 4. papal election results crash; 5. one slow seat blocks
the other in the loop; 6. draft the narrow M2TWEOP ask (the author to approve before posting).

## 2026-10-30 (05:20): new campaign (run7) running; the watch is in the repo

**Running, unattended:** `scratch` run7 (started 10-30 ~05:00, turn ~1), loop, bot, crash-watch.
England and France on `heretic:local`. **No watch runs once this session ends**: the next session
starts it with `just watch scratch` in the background (run_in_background) and handles what it prints.
Restart the campaign whenever England is lost (the author: keep going): stop loop/bot/game, move
`parley_turns/scratch` and `scratch.db` to `.runN`, `just play scratch` **before** launching the game,
then the M2EX launcher Run mod -> Single Player -> Grand Campaign -> START.

**Runs overnight:** run5 England on Sonnet grew to 5 settlements, then lost under Heretic by turn 166;
run6 (Heretic) conquered on turn 189 and not restarted, because the old watch missed it (fixed, #215).
Archives: `parley_turns/scratch.run5*`, `scratch.run6*`. run7 has stray empty `turn-0191..0193`
folders (no state.json; harmless to the watch, which uses the newest England report).

**Merged since the last section:** #208-#215 (see CHANGELOG). Guide for wake-on-event:
`docs/NOTIFY-CLAUDE.md`. The author asked for a fresh session instead of compaction: not possible from
inside; a SessionStart(compact) hook that injects HANDOFF.md instead (the author: yes, 10-30; next item 2).

**GPU still in mtw2 mode**: `just gpu shared` in the author's tooling repo when the campaign stops.
Claude usage cap for the day was 12% (the author).

**Next, in order:** 1. start `just watch scratch`; 2. add a Claude Code `SessionStart` hook,
matcher `compact`, for this project that puts HANDOFF.md's top section into the session after a
compaction (and a reminder to restart `just watch scratch`, which a compaction doesn't kill but a new
session needs); use the update-config skill, project `.claude/settings.json`; the author approved 10-30;
then update docs/NOTIFY-CLAUDE.md section 6; 3. papal election results crash (5 so far; cause
unknown, not the shape press); 4. one slow seat blocks the other in the loop; 5. #scratch-audit
alerts (garrison:Nottingham done but didn't move); 6. after the Gemini reset (~10-30 18:10 UTC):
England on Gemini, compare refusals; 7. Heretic help: affordability hints, ready orders, shorter
history, Sonnet examples.

## 2026-10-29 (end of day, Claude usage at 7%): campaign left running on free models

**Running, unattended:** the `scratch` campaign (turn ~52), loop, bot, crash-watch; England and France
both on `heretic:local` (England was on Sonnet for turns 44-51: 15-25 s a turn, 0 checker refusals,
~33% game-side refusals from far fewer orders). The play reviewer is **stopped** (it queued on Heretic).
Reader: `agy:gemini-3.8-flash-low`, out of quota until ~10-30 18:10 UTC (popups fall back to defaults).

**GPU is in mtw2 mode** (Uncle J, PR #239 there): llama-heretic `-c 65536 -np 2 --fit-target 1024`
(2 x 32k, 8.8 GB on the GPU), Ollama and Klarheit's timers paused. France's turns 188-228 s -> 73 s.
**When the campaign stops: `just gpu shared` in the author's tooling repo.** ~1 GB VRAM headroom:
on a CUDA OOM, `HERETIC_FIT=2048 just heretic up -d --force-recreate` there.

**Merged since the evening section:** #200 docs, #201 the bridge's 41 constants in one table `K`
(the main chunk hit Lua's 200-local limit; a reload then failed and needed `just relaunch-game`, which
now has run end to end twice), #202 no-land-path refusal carries the board order or "no fleet", #203
audit: used after merging it away = ruler, #204 buttons pressed by `execute()` (Track A), #205 End
Turn too, #206 renamed captains found by their reported tile (~25 France refusals) and entering a full
own settlement refused (not yet met live).

**Refusals, all 332 this campaign:** treasury too low 26% (ruler), captain renames (bridge, fixed),
merges after moving / over 20 (ruler), sea and foreign-town moves (told the fitting order). Model
matters most: England 7% refused on Gemini (turns 0-4), 34-60% on Heretic, Sonnet 0 checker refusals.

**A crash at turn 47 (14:08):** "unspecified error"; not my probe (control.txt was still unread after
the relaunch). Last bridge line: a papal election results scroll; Proton log shows LuaJIT exception
code 0xe24c4a02 nearby (also thrown for caught errors, so not proof). Look at the papal scroll
handling next.

**Next, in order:** 1. after the Gemini reset: England on `agy:gemini-3.8-flash-medium`, reader on
flash-low, play reviewer back on Gemini; compare refusals with Heretic/Sonnet; 2. the papal-scroll
crash; 3. Track A: decision scrolls (marriage/adoption) by `execute()` on their sub-elements (needs a
live offer to see the parts); `on_pre_battle` still uses a scripted click; 4. "merge Henry into
garrison:York" came back unknown after Henry entered York (explain it in the refusal); 5. The author's
calls: prompt chat-history trim, whether Sonnet is worth its cost for the release.
Gate every reload: `pytest -q > out; s=$?` and a lupa `loadfile` compile check, never `| tail`.

## 2026-10-29 (evening): the turn audit runs every turn; eight more fixes from what it found

**State:** main after this docs PR. **Running:** the `scratch` campaign (turn ~33), the loop and the
bot (both from main), crash-watch, the play reviewer on Heretic. France is now `freeze = true`,
`control = "full"` (its game AI overrode its ruler's moves; bridge logged "france: game AI frozen").

**The turn audit** (the author, 10-29: "why do I have to ask you"): `just audit <name> [game_id]` replays any
run; every turn the loop audits the turns just played, posts each new problem once to
**#scratch-audit** (humans only), and tells each ruler its own ruler/option findings in the next
prompt. Bridge-bug findings per 10 turns are the convergence measure (this run: 12, 5, 19, then turns
30+ after the fixes; run3: 3, 2, 10, 8). Seen keys: `parley_turns/scratch/audit-seen.json`.

**Merged since the last section:** #190 docs, #191 no-land-path refused, #192 recruit upkeep shown,
#193/#194 the audit, #195 moves onto foreign settlements refused with the fitting order, #196 near-miss
names read as the ruler's own (28 past refusals resolved on replay), #197 agent-order refusals name
the field swap, #198 a garrison's move takes only its general (said in a note; move checked by his
name), #199 the audit judges moves two reports on. Each loaded into the running game before merging,
except #194 (the bot needs the main checkout's env file) and #199 (offline).

**Probed live through `control.txt`** (a one-line `lua ...` the bridge runs and logs): long land moves
work; `faction:splitArmy` from a garrison **copies** the unit (York 8 -> 9; the copy was removed again):
never use it for a march-out.

**Ruler quality (Track B) is now the main gap.** Heretic lost London, Nottingham and Caen by turn 31
and repeats refused orders after being told why (sea moves 5 turns running, merges over 20 units).
Open on branch `feat/refusals-carry-the-order` (loaded into the game, not merged): a no-land-path
refusal carries the board order ready to copy; merge once a live refusal shows it and see whether
Heretic copies it.

**Next, in order:** 1. merge the board-order branch after its live check; 2. watch #scratch-audit and
the bridge-bug count for turns 30+; 3. after the Gemini reset (~10-30 18:10 UTC): reader back on
Gemini, Track A (no clicks) Phase 1; 4. decide with the author whether ruler quality needs a stronger model.

## 2026-10-29 (later): fresh campaign running; three fixes checked live and merged

**State:** main after this docs PR. **Running:** the `scratch` campaign (a new England campaign started
today, turn ~16), the turn loop, the Discord bot, crash-watch, and the play reviewer on Heretic
(`uv run python -m parley.play_review games/local/scratch.toml england --every 5 --model heretic:local`).
The previous run is in `parley_turns/scratch.run3*`, the failed first start in `scratch.false-start*`,
and its play reviews in `_review/scratch.run3-reviews/`.

**Seats (`games/local/scratch.toml`):** England brain and decider and France on `heretic:local`; the
reader is `agy:gemini-3.8-flash-low`. **Every Gemini Flash tier is out until ~10-30 18:10 UTC**, so popup
reads fail and fall back to the bridge's defaults until then.

**Process (the author, 2026-10-29: "most efficient course"):** one fix at a time in its own worktree, loaded
with `just reload-bridge`, checked live against the turn folders, then merged. Start the turn loop
before starting a new campaign.

**Merged today:** #187 overview stall (not yet on the real case: a new campaign's turn 1), #188 move
check at the next turn start (live-checked, turns 10-13), #189 `move_agent` refuses sea.

**Next, in order:**
1. Watch the campaign: verify each play review (`_review/*-play-review-scratch-england-t*.md`) against
   the turn folders; fix bridge bugs one at a time as above. The ruler repeats refused orders (a fleet
   onto land twice); that's Track B (ruler quality).
2. Open: Rufus didn't move on the turn a garrison was sent to merge into him (one case). France has no
   `freeze`, so its game AI can override its ruler's moves: The author's call whether to freeze it.
3. After the Gemini reset: reader back on Gemini; Track A (no clicks) Phase 1 from
   `_review/2026-10-27-no-clicks-inventory.md`.
4. Outreach bar (the author, 10-29): 50+ untouched turns, no false reports in prompts, a cheap ruler that
   holds and grows England, the draft in `review/` corrected; roughly 1 of 4 met today.

## 2026-10-29: stuck-army fixes and prompt rules merged; nothing run live yet

**State:** main after the docs PR for this session, 733 tests pass. **Nothing running.** Merged: #182
(`review/` ignored), #183 (ROADMAP: Vox Deorum ideas, ideas only since its code is CC BY-NC-SA), #184
(stuck armies, `_review/stuck-army-2026-10-27/REPORT.md`), #185 (spy and merge_units prompt rules).
**None of #171-#185 has run live**, and `mods/parley` doesn't have #184: run `just install-bridge` first.

**Seats:** `games/local/scratch.toml` is on `heretic:local` (England brain and decider, France) since Flash
quota ran out on 10-27; the reader is still `agy:gemini-3.8-flash-low`. Flash was available again on
10-29. Argon is out until 10-30 17:41 UTC; agy's Claude and gpt-oss models until 11-02.

**Next, in order:**
1. Fresh campaign `scratch.run3`: move `parley_turns/scratch*` (the current run) aside, pick the seats,
   `just install-bridge`, `just play scratch`, `just crash-watch`, `just play-review scratch england`.
   Watch for `MOVES THAT DID NOT HAPPEN` in prompts and the bridge log's "did not happen" lines: they
   will tell whether moves onto own settlements fail for a reason we can fix.
2. Track A (no clicks): agy's inventory `_review/2026-10-27-no-clicks-inventory.md`, Phase 1. Verify
   each claim first (e.g. `run_ui_job` dead, `getUiElement():execute()` for every button).
3. Community outreach waits for a clean campaign (the author, 10-29). agy's draft is in `review/`; several
   claims in it are wrong or unverified.

Play review notes: the turn-40 review's "agent loss reported a turn late" was wrong (Geoffrey Grey died
after the turn-37 report was written); verify review claims against the turn folders before acting.

## 2026-10-26 (evening): play moved off Claude; agy watches, diagnoses and fixes

**State:** main after this docs PR, 711 tests pass. **Nothing running** (loop, bot, crash-watch and play
reviewer stopped for the night). The `scratch` campaign ended: victory conditions failed (~turn 106,
England down to 2 settlements, -16,000 florins); the game sits on that screen. Seats in
`games/local/scratch.toml` stay on agy: England brain `agy:gemini-3.8-flash-medium`, decider and France
`agy:gemini-3.8-flash-low`, `reader = "agy:gemini-3.8-flash-low"`. To resume: new England campaign (move
`parley_turns/scratch*` aside first, as `scratch.run2`), `just play scratch`, `just crash-watch`,
`just play-review scratch england`.

**The author, 2026-10-26:** save Claude usage, put play on agy; relaunch the game yourself after a crash; if a
ruler plays stupid, have agy find out why; an agy watcher should watch the play.

**Done (merged):** #168/#173 `just relaunch-game` and `just crash-watch`; #169/#170 play reviewer; #171
decision buttons hidden or faked by settlement labels (turn-60 stall; also the likely trigger of the turn-50
crash: an undetected guild offer, then a minimized scroll forced open over it); #172 crossings name each
shore's land tile, leaderless fleets resolve; #174 reader on agy; #175 stars counted from pixels (Gemini
undercounts by one; the record is all zeros); #176 the Gemini loop (below).

**Gemini as ruler (turns 51-106):** flash-low (no thinking) took England from 7 settlements, +6,000 (turn
60) to 2, -12,000, one order a turn. agy's diagnosis, verified: an every-turn merge rule plus merges that
moved nothing reported "done", debt refusing every gold order with no free lever named, and notes copied
forward turn after turn. flash-medium thinks (~4,700 tokens) but still gave one order until #176. After
#176: refused empty merges, set_tax used; still thin.

**Next, in order:**
1. Judge Gemini fairly: a fresh campaign with #171-#176 in from turn 1 (this one is past saving). If it
   still plays thin, feed back only the last note (agy's fix: YOUR RECENT NOTES feeds 5 near-copies).
2. Read the play reviews in `_review/` (t0069...); verify each claim before acting.
3. `just relaunch-game` has not yet run end to end (Steam -> Run mod); the next crash tests it.
4. The older items below (ransom captive wording, Argon after ~10-30, upstream #89/#90, X1 duplicates).

## 2026-10-26 (late afternoon): live steward test, scratch restarted as a new England campaign

**State:** main after #163, 682 tests pass. `scratch` is a NEW England campaign (started 13:05; the old
scratch turn folders and db are moved to `parley_turns/scratch.run1*`, nothing deleted). The game,
loop and bot keep running under autoplay; England has `quiet_brain = "agy:gemini-3.8-flash-low"` in
`games/local/scratch.toml` (a test line; remove it when done).

**Verified live:** the steward escalates; repair works (turn 21, Edinburgh small_church, 5441 -> 5313
florins, no longer damaged); the ruler answers technical notes plainly (Mantle correction, turn 11).

**Fixed live (merged):**
- #159: the game's suitor record is all-zero at offer time; the steward declined two good suitors on
  "command 0, loyalty 0". An all-zero record now counts as unknown and goes to the ruler.
- #160, #163: rulers know they're an AI playing through Parley, answer technical notes out of character
  ("Bug: <what>" in the note), and know Claude is the developer who runs it.
- #161: the ruler's record of a named choice keeps what the scroll showed (turn 8: it forgot its own
  ceasefire with Scotland, blamed the game's AI, and re-declared war).
- #162: the turn gate counted the ruler's own and old messages (`Store.recent` = last 30 of any turn),
  so every turn escalated. Now only others' messages since its last turn count. France writes to England
  almost every turn, so the cheap brain still rarely plays: expected, not a bug.

- #165: `find_choice` took settlement labels (green faces, red beside them) for a decision's check
  and X, so stuck recovery sent phantom decisions to the ruler and never reopened the minimized
  "Bride Presented" scroll (turn 27, 10 min, a hand click). Buttons must now sit on parchment
  (checked on ~1700 live captures: all 123 real decisions kept). Stuck turns now clear in 1-2 tries.
- #166 (bridge, reloaded live at turn 37): a fleet ordered onto land is told the nearest sea (turns
  32-34: three guesses at one coast); a garrison merging into a distant army is told it marches out
  under a captain and leaves its town empty (turn 12, Edinburgh).

**Next, in order:**
1. **`just install-bridge` doesn't reach a running game**: it loads at launch; use `just
   reload-bridge`, only with no popup on screen (a reload at turn 7 dropped an open marriage scroll).
   When scripting the check, strip the `\r` from `system.log.txt` lines.
2. Duplicate readings (defect X1) still live: one mission or sack choice is read up to 5 times.
3. The cheap brain hasn't played a turn: France writes to England nearly every turn, a real reason.
   Remove `quiet_brain` from `games/local/scratch.toml` when done testing.
4. Items 2-5 of the list below (ransom wording, Argon after ~10-30, upstream #89/#90, traits/event ids).

## 2026-10-26 (afternoon): the steward grows, a turn gate, Heretic can play

**State:** main after this docs PR, 668 tests pass. Nothing running. The game's installed bridge
predates the repair order (#157): run `just install-bridge` before live tests. The author, 2026-10-26: Claude usage runs out before Wednesday: offload everything possible to
agy (Gemini writes code, tests, docs; Claude specs, gates on tests, reads diffs, merges). Saved games
don't matter for now: live tests may use and overwrite any save, scratch2 included.

**Next session, in order:**
0. **Live steward test, Claude driving the game alone** (the author is away; saves don't matter): run
   `scratch` (England = player slot, ladder on) for several turns; after each turn read
   `just decisions scratch` and the ruler's game messages; check each steward answer against the
   scroll. Also set `quiet_brain = "agy:gemini-3.8-flash-low"` on England for a few turns to see the
   gate live.
1. **Test the repair order live** (#157, merged; damaged buildings in the report, `repair` order) on
   a damaged building, after `just install-bridge`.
2. **Live-check the ransom captive scroll's wording** (never captured; its parse is unverified).
3. **Argon seat test after ~10-30** (`just seat-bench` on a fresh turn).
4. **Watch upstream #89/#90**; when llama.cpp#30528 merges, the Refinery bumps Heretic's image.
5. **Remaining items from previous list:**
   - Score traits next (unscored today); calibrate `ADOPTION_SCALE` and the 0.2 margin from real offers.
   - Event ids: log mining is not viable (`_review/2026-10-26-gemini-event-ids.md`); try
     `M2TWEOP.condition("Event <name>", e)` live, one probe at a time on a save copy, or log the
     eventID with each reading going forward.
   - Click debt and next deciders from `docs/decision-inventory.md`.

**The steward and popups:**
- Marriage offers (`parley/deciders/marriage.py`, #150) and ransom scrolls (`parley/deciders/ransom.py`,
  #152) join adoption under `_steward(kind, ...)`. Ransoms: captor ransoms by custom under 1,500
  florins; captive pays or refuses by price versus treasury; execute and release always escalate to the
  ruler.
- In `games/local/scratch.toml`, England (the player slot under autoplay) has `ladder = true`. In
  `scratch2` England is AI-run, so popups never reach it; the steward only matters for the player slot.
  Neither scratch game has a decision log yet (logging began after their last turns).
- Every steward decision records its on-screen outcome in the decision log (#154), using Jigsaw's
  `Verdict.decision_id` (jigsaw#9).
- `just decisions <name> [last]` (#151) reports decision history from `<turn_root>/<game>.decisions.db`
  by rung, kind, actor, and newest decisions with outcome and escalation reason.

**The turn gate (#155):**
- For `ladder = true` seats with `quiet_brain` set, quiet turns go to the cheap brain (`parley/turn_gate.py`).
- Reasons escalating to the ruler: messages, popups, events, enemy within 8 tiles, siege, money, every
  5th turn, and 2 quiet turns in a row. Each gated turn logs a `turn_gate` decision.
- Not yet run live; no seat sets `quiet_brain` yet.

**Seats and benching (scratch2 England turn 24, 53 KB prompt):**
- `heretic:local` / `openai:<model>` (#153): OpenAI-compatible seat talking to llama-server on :8090,
  with wait-and-retry on 503 or dropped connection. Bench: 623 s, 16 kept, 4 rejected, 0 malformed:
  best non-Claude order quality, but far past the 240 s seat timeout while the game shares the GPU.
  Heretic's wake from sleep can abort on CUDA OOM (llama.cpp re-uses its boot-time fit; upstream
  ggml-org/llama.cpp#30528 open); Refinery #216 added a retry in ask_heretic.
- Seats through agy: `flash-low` 47 s, 7 kept, 0 rejected, 0 malformed; `flash-medium` 201 s, 6/0/0
  (shared slots); `flash-high` 302 s, 2 kept, 6 malformed; `gpt-oss-120b-medium` alone 293 s, 1 kept,
  2 malformed; argon low/medium/high all "agy status ERROR" (weekly quota, resets ~2026-10-30).

**Upstream and gaps:**
- EOP-Labs/M2TWEOP-library#89 feature request (missions list, hiring mercenaries, diplomatic proposals,
  games/races, agent recruit cost, siege equipment); #90 the fix PR for #88 (`getBuildingInQueue`),
  compile-tested on the Gitea Windows runner (run 2255), not run in game.
- Gap audit found master already exposes retraining (we already do it by direct write) and repair
  (construction options + `addBuildingToQueue`). Decision inventory refreshed (#156).
- Repair order (R3, #157): damaged buildings (hp below 100) in the report; `repair` queues the game's repair option. Not yet run in game.
- Refinery #215: agy may run `which`, `realpath`, `git grep`, etc. (a marriage job had died on `which`).

## 2026-10-26: Jigsaw (algorithms first, LLM when needed); Gemini fully unblocked

**State:** main after PR #149 (docs), 596 tests pass. Nothing running. `scratch2` untouched (a live
test this morning ran on a copy; turn folders and saves restored byte-identical). Bridge installed
with today's changes (watchdog, treaties, recruit queue, fleet guards).

**New project: Jigsaw**, `../jigsaw` (private Gitea `author/jigsaw`, GPL-3.0). Design:
`docs/specs/2026-10-26-jigsaw-design.md` (draft 2). Built: decision log (thread-safe), ladder and
gate. Parley imports it (non-editable path dependency: after Jigsaw changes run
`uv sync --reinstall-package jigsaw`; it must become a git/PyPI dependency before going public).

**Gemini now:** writes and tests code in a worktree (`sandbox-run`, offline bubblewrap), reads the
web (agy-only `fetch` MCP, `raw: true`), and habitual commands (python3, find, sed, jq...) are
sandboxed shims on its PATH (Refinery #208, #209, #210, #213). **Restart the session** so the
delegate MCP server loads the new `ask_agy.py`; until then run agy through
`the author's tooling repo/.venv/bin/python scripts/ask_agy.py --cwd <worktree> --edits
--model gemini-3.8-flash-medium --prompt-file <file>`. Argon's weekly cap resets ~10-30 14:00.
In mtw2 worktrees: `uv sync` on the host first, Gemini tests with `sandbox-run .venv/bin/pytest -q`.

**Next session, in order:**
0. **Marriage steward** (same shape as adoption; a Gemini job died on its first command,
   `which sandbox-run`): allow `command(which)` in the Refinery's agy permissions, then rerun the
   Gemini spec in `_review/2026-10-26-marriage-steward-spec.md` (score_marriage: decline baseline
   8, age > 60 costs 3, stakes 0.3; `_steward_adoption` generalised into `_steward(kind, ...)`).
1. **Try the steward live:** `ladder = true` under a seat (e.g. England) in `games/local/scratch2.toml`
   (the author's call), then read `scratch2.decisions.db` (`rung_counts`) and the ruler's messages. Score
   traits next (unscored today); calibrate `ADOPTION_SCALE` and the 0.2 margin from real offers.
2. **Next deciders, each with its adapter row** (`docs/decision-inventory.md`): ransoms, then the
   click debt. Event ids: log mining is not viable
   (`_review/2026-10-26-gemini-event-ids.md`); try `M2TWEOP.condition("Event <name>", e)` live, one
   probe at a time on a save copy, or log the eventID with each reading going forward.
3. **Decision outcomes** are recorded (#148); next, outcomes for steward decisions (the click's
   result) and a `just decisions <game>` recipe over the log.
4. **Gate in front of the ruler's turn** (Jigsaw build step 3, cost cutting): quiet turns get a
   cheap note instead of a full Opus call.
5. Upstream contributions (each needs the author's OK, public): a PR for #88's fix; the event-id table
   once named; the decision-inventory gaps as feature requests.
6. Gemini seat test after Argon resets (seats must survive bad decisions: PR #140 covers parsing).

## 2026-10-25 (night): the game runs EOP master; its crash found and fixed

**State:** main after PR #136 (this docs PR), 536 tests pass. The game is on **EOP master**
(upstream CI build b525628) as `mods/parley`; 3.3.1 is parked as `mods/parley-331`. The author's campaign
`scratch2` (the author plays HRE; England = Scratch on `claude:opus`, full control, not frozen; France =
Philip on `claude:sonnet`) is saved as `author-hre-turn27` in master's saves, loaded with the bridge
running, at HRE's turn 27. The loop and bot are stopped for the night: `just play scratch2`, then
load `author-hre-turn27`.

**The master crash (PR #135):** bisected live by driving the game (launch through Steam, "Run mod" in
the EOP launcher, load, End Turn, read logs). A Lua line trace (`debug.sethook`) over England's
turn end stopped at `queue_of`: master's `getBuildingInQueue(i)` returns `buildingQueue[i]` of a
circular buffer indexed from its head (`types/settlement.cpp:972`) though documented 1-based, so
`i = n` is an empty slot and its name read kills the game. The bridge reads `1..n-1` on master.
Verified: two full rounds with rulers answering and orders applied (merge, move_agent, recruit).

**Next session, in order:**
1. **Upstream issue for `getBuildingInQueue`** (needs the author's OK: public, his account): cause,
   file:line, one-line fix (`position - 1`), the repro (any faction with a queued building).
2. **Freeze done right:** a frozen faction's turn never ends (live, turn 20: its frozen AI never
   answered its own siege). The bridge must unfreeze the seat as its turn ends (or after orders),
   then refreeze at its next start; test on a save copy with a siege running. England is not frozen.
3. **Master's new calls for our gaps** (`_review/2026-10-25-gemini-eop-master-port.md` §3):
   treaties (`campaign:getFactionDiplomacy`), heir/leader, capital, recruitment queue
   (`getUnitInQueue`), agent recruit cost. Behaviour change to watch: master's `setDipStance` runs a
   console command (`diplomatic_stance ...`), not a direct write.
4. Gemini seat test after Argon's quota resets (~2026-10-30 13:40). Webhook command (the author).

**Driving the game yourself** (the author asked for it): window `Medieval 2` at (4,30) 1600x900; Steam
`steam://rungameid/4700` opens the EOP launcher (window `M2TWEOP`, "Run mod" at screen 956,534);
main menu Load Game 376,488 → Load Campaign Game 376,298 → list rows ~20 px apart from y 274 (in-game
menu) or 330 (main menu) → Load; End Turn 1550,760; crash dialog OK 960,551. Screenshots:
`import -window root -crop 1610x935+0+0`. Never `rm -rf` (denied); never EOP `saveGame`.

## 2026-10-25 (afternoon): scratch2 live (the author plays HRE); crash guards in; EOP master parked

**State:** main after PR #132, 534 tests pass. The game runs **EOP 3.3.1** (`mods/parley`) with
`games/local/scratch2.toml`: The author plays HRE himself (no autoplay), England is Old Scratch on
`claude:opus` (full control, a non-player faction now), France is Philip on `claude:sonnet`. At
turn 10, no crash since the rollback. scratch ended at turn 226 (victory conditions failed).

**Next session, in order:**
1. **EOP master crash, on a save copy, never in the author's game.** The official CI build b525628 is
   parked as `mods/parley-master` (bridge installed in its `eopData/eopScripts`, `parley_turns`
   linked). It crashed six times at England's turn start right after its own "Try attack army
   order" log lines, with no bridge orders. Swap = two renames with the game closed. Check
   whether master's campaign-AI changes (the attack-order log) crash on their own (a vanilla save,
   no bridge), then report upstream if so. The port plan: `_review/2026-10-25-gemini-eop-master-port.md`
   (Gemini's; its rename map checked: only land crossings differ by name, PR #127 done).
2. **Gemini seat test** when Argon's weekly quota resets (~2026-10-30 13:40): `just seat-bench`
   on hung turns, then argon-medium on France with `fallback = "claude:sonnet"` for 30+ turns.
   Flash is not a ruler (0 orders) and not an autonomous coder (give it exact single edits).
3. **Webhook (the author):** `workflow_job` hook on `author/M2TWEOP-library`; the command is in this
   session's transcript (prompts for foc's secret, URL `http://<gitea-host>:8712/`).
4. The ROADMAP's decision-tracking design (discuss with the author) and the decision inventory refresh.

**Live crash classes, all guarded now:** an instant merge into a besieging or moving stack (#126);
`siegeSettlement` from more than one tile (#130); an agent action from inside or far from its
target (#131). EOP's calls check no range: any new order that calls an EOP action must check
range and state first.

**Quirks:** `training.json` is per game now (#132). France's Gemini runs left `fallback` docs in
WRITEUP. The shared bot and loop: `just play scratch2`. Rulers keep re-issuing refused orders
(Richard's spy); the refusal reasons reach them each turn.

## 2026-10-25 (later): primer, plan, agents, lessons, queue merged; EOP builds on the runner

**State:** main after PR #117, 513 tests pass. The game is stopped. Nothing below has run live yet.
**Start fresh:** the author took mtw2 off the Refinery's delegate local-only list (Refinery PR #204).
A new session gets the `delegate` MCP (`ask_agy`, pass `model="gemini-4-argon-high"`); only the
env file stays blocked. agy's own read_file deny on mtw2 is still on (the author's call), so paste code
into Gemini prompts.

**Merged this session:**
- #110: the strategy primer in every prompt, fact-fixed before wiring; the standing plan
  (`"plan"`, shown every turn).
- #111 and #113: `recruit_agent`, by the game's rules. A building must grant the agent
  (`getAgentCapability`), the faction limit is the sum of `getAgentLimitCapability`, and the
  price comes from `descr_cultures.txt`. Next turn `spawn_character` places him.
- #112: the lessons store, per persona (keyed by the seat's display name), reviewed every 20
  turns in a background thread. `just lessons <game>` lists them, `just lessons-veto <game> <id>`
  removes one. Gemini seats measured: `agy:gemini-4-argon-medium` is clean on England's full turn.
- #114: the recruitment queue. 9 waiting at most; beyond the training slots, recruits wait.
- #115: `just seat-bench <turn dir> <timeout> <specs…>` replays a played turn to seats.

**First live session, watch in this order (one change at a time):**
1. The report's "can train agents" and "AGENT LIMITS". Check that `getAgentCapability(t).value
   > 0` matches what the game's recruitment panel offers. Then one `recruit_agent`; the next turn
   the log should say "<agent> trained in <settlement>", or "UNCONFIRMED".
2. The standing plan appears and carries over. The primer shows up in `prompt.txt`.
3. At turn 180 (the next multiple of 20), the log line "lessons review at turn 180 kept N".
   Then `just lessons scratch`.
4. Optional: a seat on `agy:gemini-4-argon-medium` (the author's call which seat), to save Claude usage.

**EOP builds (fork `author/M2TWEOP-library`, private):**
- Branch `gitea-ci` holds `.gitea/workflows/build.yml`. It mirrors upstream's build (msbuild
  library, GUI and d3d9, Release x86) and unpacks the DirectX June 2010 SDK in the job, checked
  by Authenticode, with portable 7-Zip pinned by SHA256.
- **Green:** run 573 built EOP master in 13.5 min and produced `M2TWEOP.zip` (96 MB) as an
  artifact, in the run's UI. Run 574 built branch `lua-culture-agent-cost` green too. Run 571
  had failed on a dead 7-Zip URL, since fixed. The SDK is now cached at
  `C:\Users\runner\eop-cache\dxsdk-jun10`, trusted only with its marker (gitea's conditions).
  Thread: `_review/2026-10-25-gitea-*eop*`.
- **needs-author:** the VM auto-starts only for `author/foc`. A `workflow_job` webhook on
  `author/M2TWEOP-library`, with foc's URL and secret, needs the author (the secret is credential-guarded).
  Until then, ask the gitea session to start the VM.
- Branch `lua-culture-agent-cost`: `M2TWEOP.getAgentRecruitCost/Time` from the culture DB, the
  first upstream candidate. It can't be verified until we run an EOP master build in the game,
  and that upgrade is the author's call.

**Still open from the ROADMAP:** parity for AI-run seats. The game decides family offers, votes
and AI offers silently for them. EOP master has only notifications plus `characterRecord:marryWife`,
so a live probe must first show whether `onOfferedForMarriage` fires before the AI decides. Then
the EOP master port, then the freeze.

## 2026-10-25 (end): game stopped; primer, plan and EOP builds queued

**State:** main after PR #108, all merged, 486 tests passed at the last full run. The author stopped the
scratch game (England Opus, France Sonnet). Claude's weekly usage was at 74%, so hand work to Gemini
(`agy --model gemini-4-argon-high`, code pasted in, tests as the gate).

**Pick up here, in order:**
1. **Primer + standing plan.** `parley/primer.md` is committed but not yet wired in. Gemini's answers
   (spec + code, unreviewed) are in `_review/2026-10-25-gemini-wire-answer.md` (primer into
   `build_prompt`) and `_review/2026-10-25-gemini-plan-answer.md` (`Orders.plan`,
   `Orchestrator._last_plan`, a plan section in the prompt). Review them, apply, `just test`, one PR.
2. **EOP builds on the Gitea Windows runner.** The thread is in `the Gitea admin folder/review/` and
   `_review/` (`2026-10-25-*windows-runner-msvc.md`). The runner already has MSVC v143 and SDK 22621.
   Next: create the Gitea repo `author/M2TWEOP-library` (fork of EOP-Labs), add a minimal
   `runs-on: windows` msbuild workflow (job-scoped env only, VS stays 2022), run it, and post the
   log to gitea's review folder. Doorbell: SendMessage `gitea-dc`.
3. Then the agreed list in ROADMAP "Next": agent recruitment via `spawn_character` with the game's
   rules, parity for AI-run seats, fixing Gemini seats (try gemini-4-argon), and a cross-game lessons
   store.

## 2026-10-24: observer mode live: Old Scratch plays England, the author advises

**State (end of session):** `games/local/scratch.toml` is running, at turn 23. It has 18 LLM rulers;
the Gemini seats were moved to Claude Haiku mid-game. Old Scratch (Opus, `control = "full"`,
adviser `your_discord_name`) plays England, the human slot, under autoplay. He holds York, Rennes and
Bruges, the last two bought by bribe. PRs #13–#39 are merged, 398 tests pass, `main` is clean.
The day's story is in `docs/JOURNAL.md`; the guide is `docs/WRITEUP.md` §0 and §9.

**The QA loop (Claude can run it without the author):**
- `just follow england scratch` streams the ruler's messages and notes. Claude re-arms it as a
  background `--once` watcher.
- `just reload-bridge` hot-reloads the bridge into the running game through EOP's `restartLua`,
  which needs `enableConsole = 1`. Orders already applied aren't applied again.
- `just restart-loop scratch` restarts only the turn loop; the bot and its token are untouched.
- `parley_turns/control.txt` takes four commands:
  - `reload`
  - `scan <label>`: every open UI element, with positions
  - `script <campaign command>`
  - `lua <one line>`: a live probe, whose result is logged in `parley_bridge.log`
- `just tell england scratch "…"` sends the ruler an out-of-character game note.
- A full relaunch is needed only after a crash. Don't use EOP's `saveGame`: it hung the game.

**Built today (beyond the observer-mode list):**
- recruiting from the recruitment pools
- the income figure split from one-off spending
- agent mission outcomes, with EOP's disaster-name bug translated
- popups read from screenshots by Haiku, with the turn loop's own thread
- marriage offers decided by the ruler and clicked (window focus needed)
- ships: `board`, `land`, `blockade` (only the tile and port lookups are verified live)
- the duplicate-build refusal
- readable notes
- `just tell`
- game notes

**Next (suggested order)**
1. **Family, and why agents and family die** (the author's request). The report has no family, so
   Cecilia's death went unnoticed until Scratch asked.
   - List the family from `fac:getNamedCharacter(i)` (the dead and off-map ones included):
     name, age, role, alive, married to whom, and princesses with their marriage prospects.
   - When an agent or family member disappears, give the ruler the full list of plausible causes
     for that kind of character, ordered by evidence, and ask him to theorize. Causes overlap:
     - old age (compare against the age at last report)
     - assassination (enemy assassins seen nearby; any `onAssassinationMission` event naming the
       victim)
     - battle death (a battle that turn)
     - plague, or failing a mission (spies and assassins can die in a failed attempt)
     - for a princess: married off (spouse field, or no longer in the list as ours)
     - bribed away (now listed under another faction)
   - The author suspects Cecilia, dead at 36, was murdered.
2. **AI diplomatic offers decided by the ruler**, like marriages. The screen reading can now show
   the terms. Click accept or decline as with the marriage scroll (measure the buttons from a
   screenshot).
3. **Ships live:** watch Scratch's first board, sail and land. Fix whatever the move-based boarding
   does in practice.
4. **Garrison marching:** confirm that `merge_armies` brings a garrison to a field army.
5. **Parley window width** (its lines are cut off). Make the seal finder's size limit relative to
   the window.
6. **Unit queue slot limit** for recruiting (not modelled).

## 2026-10-23 (end of day): Plans 1–2 done and playable; persona library; full write-up

**State:** playable end to end on the author's Linux machine.
- **Game side:** EOP 3.3.1 in `mods/parley`, launched through a Steam launch-option swap. The
  Lua bridge reports at turn end and applies orders at turn start, and never blocks. All 8 order
  types are verified in game.
- **LLM side:** Claude (CLI), Gemini (`agy`, flash-**low**) and Ollama seats.
- **Memory:** each ruler's last 5 notes plus what changed since its last turn, and the
  diplomacy so far.
- **Discord table:**
  - a public channel per game (`#<game-id>`), private threads via `!private <faction>`;
  - replies between turns, grounded in the ruler's real report;
  - turn cues, and transfer notices in private threads only.
- **Persona library:** the 1080 historic roster plus 6 archetypes, used with `persona = "@id"`.
- Tests: 168 passing. Guide: `docs/WRITEUP.md`. Build log: `docs/JOURNAL.md`.

**How to play:** `docs/WRITEUP.md` §5.
1. `just run games/historic-1080.toml`
2. `just discord games/historic-1080.toml`, in the author's own terminal, since it reads the token.
3. Steam Play → Run Mod → new campaign as England.

**Live game in progress:** `games/first-game.toml`.
- England (the author) owes Venice 600 florins by turn 20 or 21. Venice sent 500 on turn 16.
- Milan was switched to Gemini flash-low.

**Next (suggested order)**
1. **A richer report:** foreign armies near the ruler's lands, neighbours' settlements, real
   income. That cures invented place names and blind threats.
2. **Plan 3, the deal ledger:**
   - human `/send` and `/cede` with travel time;
   - deals recorded from chat;
   - kept or broken checked against the game, with a public record.
3. **Plan 4, cross-game memory for permanent personas,** with `forget`.
4. **A bigger game** with `games/historic-1080.toml`, then scenarios (Plan 5).
5. **An automated installer** from `docs/WRITEUP.md` §4.

**Known issues**
- Public M2EX has no Lua; v1 runs on EOP.
- Gemini flash-medium returns empty structured answers; use flash-low. agy calls queue
  machine-wide.
- Rulers sometimes repeat lobby messages.
- `income` and `visible_enemies` aren't populated by the bridge yet.
- The deferred review minors are in `.superpowers/sdd/*/progress.md` and the PR descriptions.

## Checkpoint 11-01 ~08:40 (stopped early: machine out of memory)

Branch `fix/qa-open-cases` (not merged, not live-checked with `just qa`):
- The 06:05 baseline exit code 1 comes from `marry_foreign_general`, the only `fail`
  (`parley/qa/__main__.py:75` exits 1 only on a `fail`).
- `repair_queued` cause found and proven live: EOP caches a town's construction options by
  (buildings + queue hash, turn) (`M2TWEOP library/types/settlement.cpp:1008`). Setting `hp`
  changes neither, so no repair shows up until next turn. In Dijon a bump of `turnNumber` by
  one, then a query, then the restore, then a second query listed both repairs. `M.qa.damage`
  now does that. Next: `just qa towns case=repair_queued`. Also make the fake game in
  `tests/test_qa_towns_lua.py` cache like EOP. A first try keyed on `FAKE.gd` broke 5 tests
  and was reverted.
- `marry_foreign_general` and `crossing_in_one_turn` still need a diagnosis. Both agy calls
  failed: argon-high quota is gone for ~5 days, and Flash timed out and was denied `git log`.
- The scratch turn loop and bot are stopped (`just stop`). Restart with `just play scratch`.
