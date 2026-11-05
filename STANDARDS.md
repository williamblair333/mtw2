# Standards: the bar a senior practitioner would hold Parley to

Written from the seat of a senior game-tools engineer and test lead who owns the goal: **LLM rulers
play whole Medieval II campaigns unattended, then a release the community can install and help
with.** The domain is game QA, live-ops and release engineering for a modded PC strategy game, not
this repo's habits. Every session starts from the top open gaps; every status report says which gap
it moved. Rewrite the bar when the phase changes. Ranked by impact, highest first.

```yaml
phase: making it reliable — rulers play run after run unattended; every fix proven on the bench before live
standards:
  - id: phase-order
    area: QA
    bar: No turn-playing or click work starts while the newest no-click run has a fail or inconclusive case; no-click is clean first
    why: a test lead clears the fast, deterministic tier before spending slow turn and click runs; 11-01 a session built quiet-world turn work over phase 1's three open cases until the author asked why
    status: met
    evidence: scripts/preflight_interrupts.py phase_open() (run before every `just qa` by .claude/preflight.toml) refuses a turn run while the newest runs/qa/*-all.md lists a fail or inconclusive not explained in games/no-click-explained.toml; tests/test_preflight_interrupts.py test_phase_order_*
  - id: no-clicks-first
    area: QA
    bar: Every game action goes through EOP/Lua first; a screen click (xdotool) is a named last resort, and click-dependent work is batched for when the author is away
    why: clicks fight the author's desktop focus (the 10-30/31 papal crash came from a windowactivate) and need him off the keyboard; moved here from memory no-screen-clicks (11-01) so it is checked, not remembered
    status: partial
    evidence: PARLEY_NO_X_INPUT=1 no-click runs (`just qa all kind=instant`), phase2 = "<why>" marks a click case; papal vote and decision scrolls still need a click (no EOP press yet)
  - id: fixed-bench-save
    area: QA
    bar: Every bench suite starts from one fixed, quiet test save, never a copy of a live campaign
    why: a game QA lead never tests on a world whose next event is unknown; failures must repeat
    status: partial
    evidence: just qa-bench-save (start, record) and parley/qa/runner.py load_bench_save / _load_bench (runs refuse without the save; AI factions frozen via freeze=*); the save itself still has to be created live
  - id: bench-per-system
    area: QA
    bar: Every game system (covert, envoys, diplomacy, field, siege, navy, towns, popups, smoke) has a bench suite
    why: fixes are proven on forced events in minutes, never on live luck
    status: partial
    evidence: games/qa/
  - id: forced-events
    area: QA
    bar: Every game event a ruler meets can be forced on demand (papal election, AI offer, siege, rebellion, mission)
    why: an event that can't be forced can only be tested by waiting, which is how 10-31's bugs got through
    status: partial
    evidence: "games/qa/instant.toml; .claude/preflight.toml gate runs scripts/preflight_interrupts.py before every `just qa`, refusing a turn-playing run until each event in games/interrupts.toml is ruled out or held with code proof plus a passing bench case (`bench = \"suite/case\"`). As of 11-01 none of 12 counts as held: papal_election, succession, rebellion (towns) and plague have code (M.qa.quiet, #342/#344/#345) waiting on instant/quiet_world_held's first bench pass; ai_attacks_sieges (freeze=*) has no bench case; 7 have no hold"
  - id: instant-cases
    area: QA
    bar: A case ends a turn only when the game must play one; everything else is checked in-turn in seconds
    why: each turn wait costs up to 240 s; the loop's speed bounds every fix
    status: partial
    evidence: games/qa/instant.toml; siege, towns, navy, envoys, covert (1 turn case) and field (1 turn case) are instant but the turns they must play; diplomacy, popups and smoke not reviewed
  - id: regression-per-bug
    area: QA
    bar: Every bug gets a bench case that fails before its fix merges
    why: a fix with no failing case first isn't proven and can come back
    status: open
    evidence: 10-31 fixes #295-#298 were proven live first
  - id: crash-repro-report
    area: QA
    bar: Every game crash writes its own report (last bridge/turn-loop lines, screenshot, save) and becomes a repro case
    why: crashes are this project's costliest bug class; read-by-hand doesn't scale
    status: partial
    evidence: scripts/crash_report.py, called by crash_watch.sh before each relaunch, writes runs/crashes/<time>/ (bridge log tail and its papal lines, fresh turn-log tails, screenshot, newest save, game id and turn, report.md with the last 10 s merged); just crashes lists them; turning a report into a bench case is still by hand
  - id: ruler-eval-harness
    area: rulers
    bar: Fixed scenarios score each ruler model/prompt on legal orders, timeouts and outcomes
    why: ruler changes are guesses without a score; half the goal is rulers good enough to play
    status: open
    evidence: ruler quality judged from live runs only
  - id: ruler-budget
    area: rulers
    bar: Ruler answers are bounded in tokens and time and never miss a turn by running long
    why: 4 of 46 run9 turns were lost to 6-7.6k-token answers past the 420 s limit
    status: partial
    evidence: 'parley/seats/openai_compat.py streams with RulerBudget (parley/seats/base.py; [ruler_budget] in config) — thinking cut at 6000 tokens or 120 s before the deadline, answer without thinking from the reasoning so far, answer capped at 2500 tokens, a cut answer keeps its finished orders (salvage_json); tests/test_openai_seat.py on a fake server with a simulated clock (run9''s 8k-token turn now plays in 420 s). Run9 measured: 5-8.2k generated tokens at 19-25 tok/s, the orders JSON at most 4.7 KB (~1.5k tokens), so ~85% thinking. Not yet seen live; agy/claude/ollama seats still have only the timeout'
  - id: merge-gate-game-smoke
    area: release
    bar: Merges are gated on unit tests and a fast smoke run on the game
    why: unit tests run against a fake; the real game has crashed on code that passed them
    status: partial
    evidence: just test
  - id: flaky-quarantine
    area: QA
    bar: A flaky case is quarantined with its cause tracked; any case reruns alone in seconds
    why: a red that might be noise teaches everyone to ignore red
    status: partial
    evidence: parley/qa/__main__.py (case=<name> reruns one); `chance = true` makes a roll inconclusive, never red (covert spy_report_closed); covert.toml and field.toml headers list each old flake's cause and what removed it; no quarantine list yet
  - id: crash-recovery
    area: live-ops
    bar: A crashed game is relaunched and the campaign resumed without a human
    why: unattended play is the goal
    status: done
    evidence: 'just crash-watch (no clicks since 10-31: scripts/relaunch_game.sh hides EOP''s launcher and loads the save at start-up via bypass_to_strategy_save; --clicks is the old fallback)'
  - id: trend-alerts
    area: live-ops
    bar: Alerts fire on trends (rejections rising, rulers slowing, a faction shrinking), not only on stalls
    why: slow decay loses campaigns without ever tripping a stall alarm
    status: open
    evidence: scripts/campaign_watch.sh catches stalls, stuck turns and losses only
  - id: dashboard
    area: live-ops
    bar: One page shows turn, health, crashes, rejected orders, ruler timeouts and open gaps
    why: status shouldn't need a Discord scroll or a person asking
    status: open
    evidence: Discord posts only
  - id: log-rotation
    area: live-ops
    bar: Every log rotates and has a size cap
    why: parley_bridge.log is 17+ MB and grows every turn
    status: open
    evidence: no rotation
  - id: wishes-carried-out
    area: rulers
    bar: Every ruler order is carried out or refused with a reason the ruler can act on
    why: a ruler told "done" for a move that didn't happen plays blind
    status: partial
    evidence: parley/audit.py
  - id: clean-install-test
    area: release
    bar: A clean-machine install is tested before every release
    why: the community's first contact is the installer
    status: open
    evidence: no install test
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
    status: open
    evidence: no guide
```
