# Standards: the bar a senior practitioner would hold Parley to

Written from the seat of a senior game-tools engineer and test lead who owns the goal: **LLM rulers
play whole Medieval II campaigns unattended, then a release the community can install and help
with.** The domain is game QA, live-ops and release engineering for a modded PC strategy game, not
this repo's habits. Every session starts from the top open gaps; every status report says which gap
it moved. Rewrite the bar when the phase changes. Ranked by impact, highest first.

```yaml
phase: making it reliable — rulers play run after run unattended; every fix proven on the bench before live
standards:
  - id: fix-what-we-can
    area: QA
    bar: "If we can fix it, we fix it: a bug in code we can change (Parley, Jigsaw, our EOP fork) is fixed at its cause and proven; a workaround or an upstream report is never the finish line"
    why: The author 11-15, "IF YOU CAN FIX IT, FIX IT!!"; the EOP draft listed bugs only worked around in Lua that our fork can fix
    status: partial
    evidence: "docs/WORKAROUNDS.md lists what is still worked around. minorSettlementDb fixed in the fork (on tc since 11-13, fork build a3e678b9); getBuildingInQueue 1-based (fork #4); the rest of _review/eop-upstream-draft-2026-11-14.md open (HANDOFF 11-15 06:00). Upstream gets PRs with proof; only what is not ours (game exe, LuaJIT) goes as an issue"
  - id: standing-orders-hold
    area: process
    bar: A standing order to keep working ("until 23:00") holds mechanically; a milestone is a one-line report, never the end of the turn
    why: 11-05 the author said "work until 2300, don't stop" and the session still ended its turn at 06:31 after a merge; an order kept by memory lapses at the first natural stopping point
    status: done
    evidence: scripts/work_until.sh (`just work-until HH:MM`) and its Stop hook in .claude/settings.json block ending a turn until the time; tests/test_work_until.py
  - id: phase-order
    area: QA
    bar: No turn-playing or click work starts while the newest no-click run has a fail or inconclusive case; no-click is clean first
    why: a test lead clears the fast, deterministic tier before spending slow turn and click runs; 11-01 a session built quiet-world turn work over phase 1's three open cases until the author asked why
    status: done
    evidence: scripts/preflight_interrupts.py phase_open() (run before every `just qa` by .claude/preflight.toml) refuses a turn run while the newest runs/qa/*-all.md lists a fail or inconclusive not explained in games/no-click-explained.toml; tests/test_preflight_interrupts.py test_phase_order_*
  - id: no-clicks-first
    area: QA
    bar: Every game action goes through EOP/Lua first; a screen click (xdotool) is a named last resort, and click-dependent work is batched for when the author is away
    why: clicks fight the author's desktop focus (the 10-30/31 papal crash came from a windowactivate) and need him off the keyboard; moved here from memory no-screen-clicks (11-01) so it is checked, not remembered
    status: partial
    evidence: "just click-coverage (scripts/click_coverage.py, games/click-coverage.toml, tests/test_click_coverage.py): fails until every click kind the census has seen has a bench case passed in a `--kind noclick` run; done means it exits 0. 11-22: the click code is deleted (#689) and every census kind has a noclick bench case but one: the papal results scroll's `escape` (48 seen), closed by activate() on its SCROLL_CLOSE_GADGET (in progress). The history below is superseded where it says a click is needed. Earlier: parley/xinput.py (PARLEY_NO_X_INPUT=1 refuses X input in `just qa all kind=instant`). 11-05: family offers no longer arise on the bench (lua/parley_bridge.lua M.bench_marriages_off marries England's men, #412); a battle under the QA hold resolves by script command (#415, besiege_assault_storms joined phase 1). Still open: the papal vote scroll needs a click (asked upstream, EOP-Labs/M2TWEOP-library#91); decision scrolls (marriage offers) are answered by click, and that crashed the game 3x on 11-05 (HANDOFF; repro games/qa/family.toml)"
  - id: fixed-bench-save
    area: QA
    bar: Every bench suite starts from one fixed, quiet test save, never a copy of a live campaign
    why: a game QA lead never tests on a world whose next event is unknown; failures must repeat
    status: done
    evidence: "parley/qa/runner.py load_bench_save / _load_bench (runs refuse without the save; AI factions frozen via freeze=*) and `just qa-bench-save` (start, record); the save is mods/parley/saves/parley_bench.sav (10-24), and every suite of the 11-05 full pass (runs/qa/2026-11-05-17*.md, 18*.md on the test laptop) loaded it"
  - id: bench-per-system
    area: QA
    bar: Every game system (covert, envoys, diplomacy, field, siege, navy, towns, popups, smoke) has a bench suite
    why: fixes are proven on forced events in minutes, never on live luck
    status: done
    evidence: "games/qa/smoke.toml and the rest of games/qa: a suite for each of the nine (covert, envoys, diplomacy, field, siege, navy, towns, popups, smoke); full pass 11-05 17:26-18:44 on the test laptop: 128 of 134 passed, 3 failed and were fixed (#440-#442, each passed alone after), 3 inconclusive (two instant diplomacy offer cases by design, one chance case)"
  - id: forced-events
    area: QA
    bar: Every game event a ruler meets can be forced on demand (papal election, AI offer, siege, rebellion, mission)
    why: an event that can't be forced can only be tested by waiting, which is how 10-31's bugs got through
    status: partial
    evidence: "games/qa/instant.toml; .claude/preflight.toml gate runs scripts/preflight_interrupts.py before every `just qa`, refusing a turn-playing run until each event in games/interrupts.toml is ruled out or held with code proof plus a passing bench case (`bench = \"suite/case\"`). 11-05: 6 of 13 have a hold: papal_election, succession, rebellion, plague and marriage_offer by M.qa.quiet, with games/qa/quiet.toml as bench proof (passed 19:16 on the test laptop; the case named since 11-01 had never existed); ai_attacks_sieges by freeze=*, no bench case. 7 have none (papal and council missions, crusades, AI offers, general defects, disasters, adoption)"
  - id: instant-cases
    area: QA
    bar: A case ends a turn only when the game must play one; everything else is checked in-turn in seconds
    why: each turn wait costs up to 240 s; the loop's speed bounds every fix
    status: done
    evidence: "games/qa/instant.toml; siege, towns, navy, envoys, covert (1 turn case) and field (1 turn case) are instant but the turns they must play. 11-05: diplomacy and popups reviewed (their turn cases need the AI's turn, the next report or a played turn); games/qa/smoke.toml dropped two turn cases that only re-read held-turn log lines (#443); tests/test_turn_cases_need_turns.py fails any turn case whose every check is such a line"
  - id: regression-per-bug
    area: QA
    bar: Every bug gets a bench case that fails before its fix merges
    why: a fix with no failing case first isn't proven and can come back
    status: partial
    evidence: "tests/test_lua_bridge.py, tests/test_qa_runner.py, tests/test_qa_popups.py: each 11-05 phase-2 fix (#398-#415) has a test there that fails without it, checked by stashing the fix. scripts/preflight_tests_staged.py (gate regression-per-bug, 11-05) refuses a commit with code and no test unless its message says no-test: <reason>. Open: the gate asks for a unit test, not a bench case"
  - id: crash-repro-report
    area: QA
    bar: Every game crash writes its own report (last bridge/turn-loop lines, screenshot, save) and becomes a repro case
    why: crashes are this project's costliest bug class; read-by-hand doesn't scale
    status: partial
    evidence: scripts/crash_report.py, called by crash_watch.sh and by the QA restore (parley/qa/runner.py _ProcessManager.crash_report) before each relaunch, writes runs/crashes/<time>/ (bridge log tail and its papal lines, fresh turn-log tails, the game's windows only (tests/test_no_desktop_capture.py), newest save, game id and turn, report.md with the last 10 s merged and, since 11-05 (#466), the orders applied at the turn's start); just crashes lists them; a new report wakes the campaign watch (CRASH, #463); turning a report into a bench case is still by hand (11-05: the 16:38 crash got covert/spy_into_own_town_with_foreign_spies)
  - id: ruler-eval-harness
    area: rulers
    bar: Fixed scenarios score each ruler model/prompt on legal orders, timeouts and outcomes
    why: ruler changes are guesses without a score; half the goal is rulers good enough to play
    status: partial
    evidence: "parley/ruler_eval.py (`just ruler-eval --scenario <turn dir>... <seat specs>`): every seat on every recorded turn, legal-order rate, answered, time; JSON and markdown in runs/ruler-eval/. games/ruler_eval holds a fixed set of six real run-9 turns (`just ruler-eval-fixed <specs>`, 11-05, #455), and kept orders are counted by control area (#458). Still open: outcome scoring beyond legality and order mix"
  - id: ruler-budget
    area: rulers
    bar: Ruler answers are bounded in tokens and time and never miss a turn by running long
    why: 4 of 46 run9 turns were lost to 6-7.6k-token answers past the 420 s limit
    status: partial
    evidence: 'parley/seats/openai_compat.py streams with RulerBudget (parley/seats/base.py; [ruler_budget] in config) — thinking cut at 6000 tokens or 120 s before the deadline, answer without thinking from the reasoning so far, answer capped at 2500 tokens, a cut answer keeps its finished orders (salvage_json); tests/test_openai_seat.py on a fake server with a simulated clock (run9''s 8k-token turn now plays in 420 s). Run9 measured: 5-8.2k generated tokens at 19-25 tok/s, the orders JSON at most 4.7 KB (~1.5k tokens), so ~85% thinking. Seen live 11-05 18:57 (run 10, the test laptop): France''s thinking cut at 6000 tokens after 225 s, and it answered 5 orders at 247 s of the 720 s wait. agy/claude/ollama seats still have only the timeout (measured 11-05 on games/ruler_eval: Gemini Flash low through agy answered 6/6 real turns in 23-67 s, two runs)'
  - id: prompt-budget
    area: rulers
    bar: A ruler's prompt stays under a size cap (60 KB) however long the campaign runs, with no fact the orders need dropped; rulers draw on their own quota, never the dev session's
    why: France's prompt grew to 328 KB by turn 3454 (157 KB settlements, 129 KB of dead relatives), and on 11-20 rulers on the shared 5-hour quota left 66 turns unruled
    status: open
    evidence: none yet; branch fix/prompt-size compacts family and settlements (tests/fixtures/prompt_size). The separate ruler account is the author's call (HANDOFF 11-22)
  - id: merge-gate-game-smoke
    area: release
    bar: Merges are gated on unit tests and a fast smoke run on the game
    why: unit tests run against a fake; the real game has crashed on code that passed them
    status: partial
    evidence: ".claude/preflight.toml (`just test` the unit gate): gate merge-gate-game-smoke refuses a test run piped through tail/head/grep before && commit/merge/reload (tests/test_preflight_match.py; #443 merged red that way, 11-05). Still open: no game smoke run gates a merge"
  - id: flaky-quarantine
    area: QA
    bar: A flaky case is quarantined with its cause tracked; any case reruns alone in seconds
    why: a red that might be noise teaches everyone to ignore red
    status: partial
    evidence: "parley/qa/__main__.py (case=<name> reruns one); `chance = true` makes a roll inconclusive, never red (covert spy_report_closed); covert.toml and field.toml headers list each old flake's cause and what removed it; games/quarantine.toml (parley/qa/quarantine.py, 11-05) lists flaky cases: they run and are reported, their failure doesn't fail the run, the cause is written beside each. Open: a turn case reruns alone in minutes, not seconds"
  - id: live-config-change
    area: live-ops
    bar: A live seat setting changes through one tested command that keeps a fresh backup, checks the config loads and leaves it unchanged if not; never a hand-typed cp or sed
    why: an ops engineer never edits a running service's config by hand (live 11-23 a wrapped cp broke and its rerun overwrote the only backup)
    status: done
    evidence: "tests/test_seat_set.py pins `just seat-set` (parley/seat_set.py)"
  - id: crash-recovery
    area: live-ops
    bar: A crashed game is relaunched and the campaign resumed without a human
    why: unattended play is the goal
    status: partial
    evidence: 'just crash-watch (scripts/relaunch_game.sh hides EOP''s launcher and loads the save at start-up via bypass_to_strategy_save). Open 11-22: scripts/crash_watch.sh still closes error boxes with wmctrl -c and scripts/refocus_game.sh uses xdotool windowactivate (screen input outside parley/xinput.py); the 11-20 08:36 crash after a bench restore (stale papal results icon) has no fix'
  - id: trend-alerts
    area: live-ops
    bar: Alerts fire on trends (rejections rising, rulers slowing, a faction shrinking), not only on stalls
    why: slow decay loses campaigns without ever tripping a stall alarm
    status: done
    evidence: "parley/trends.py and `just trends scratch` (11-05): per faction over the last 10 turns, applied share, answer time, towns and armies, late answers and seat errors, with alerts on a falling share, slowing answers, a lost town or a late/failed seat; first live run flagged England's lost town (London, turn 82); scripts/campaign_watch.sh wakes on a new one (TREND, every 10 min); parley/orchestrator.py _post_new_trends posts each new one once to the audit channel (tests/test_trends_posted.py)"
  - id: dashboard
    area: live-ops
    bar: One page shows turn, health, crashes, rejected orders, ruler timeouts and open gaps
    why: status shouldn't need a Discord scroll or a person asking
    status: done
    evidence: parley/dashboard.py (`just dashboard scratch`) shows heartbeat and newest report, loop/qa.lock/pause, newest 3 crashes, per-ruler applied/refused/late counts and trend alerts, and STANDARDS gaps; tests/test_dashboard.py; checked live on the test laptop turn 94 (11-05 16:33)
  - id: log-rotation
    area: live-ops
    bar: Every log rotates and has a size cap
    why: parley_bridge.log is 17+ MB and grows every turn (25-26 MB on 11-05)
    status: done
    evidence: "scripts/relaunch_game.sh keeps a log over PARLEY_LOG_CAP_MB (20) as .log.1 before each launch, never under qa.lock (tests/test_relaunch.py test_an_oversized_bridge_log_is_rotated_*); scripts/rotate_logs.sh (`just rotate-logs`, tests/test_rotate_logs.py) caps the bridge log and logs/*.log the same way, run every 10 min by scripts/crash_watch.sh (whenever a campaign runs) and scripts/campaign_watch.sh (11-05)"
  - id: wishes-carried-out
    area: rulers
    bar: Every ruler order is carried out or refused with a reason the ruler can act on
    why: a ruler told "done" for a move that didn't happen plays blind
    status: partial
    evidence: "parley/audit.py; 11-05 #429 #441 #451 #453 (refusals say why; a build is done only if queued). Open: AI-slot rulers share control with their game AI (run 10 France lost 2-4 orders a turn)"
  - id: clean-install-test
    area: release
    bar: A clean-machine install is tested before every release
    why: the community's first contact is the installer
    status: partial
    evidence: "scripts/preflight_vm_headroom.py (gate: a VM on the main machine needs 14 GiB free; one hung the main machine 11-24). PRODUCT.md verify block passes first_run_gate.py on clean python:3.13 (11-05). The game install ran on a fresh Debian 13 VM 11-24 (found #722), not yet end to end"
  - id: versioned-releases
    area: release
    bar: Releases are versioned, tagged and have notes
    why: testers need to say which build they ran
    status: partial
    evidence: CHANGELOG.md
  - id: tester-guide
    area: release
    bar: A community tester can follow a guide to run a campaign and file a useful bug
    why: The author wants the community to help; that needs a path in
    status: partial
    evidence: "CONTRIBUTING.md (how to play and report: what to send, which log lines) and docs/WRITEUP.md §4 (install). Not yet followed by a real outside tester"
```
