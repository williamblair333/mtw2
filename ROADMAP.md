# Roadmap

## v1: the author vs a few talking LLM factions (local)
- [x] Approve the design doc
- [x] Switch the game to the Windows build under Proton and install M2EX (and EOP for Lua)
- [x] Prove the Lua file bridge: Lua file I/O, turn events and AI handover all verified in game
- [x] Orchestrator, LLM seats (Claude, local, Gemini) and the orders schema (Plan 1 Tasks 1–5)
- [x] Discord lobby and DMs, with LLM personas (Plan 2; persona library)
- [ ] Deal ledger, transfer logistics, kept/broken checks
- [ ] Reputation and memory across games (per-game memory done: notes, what changed, a standing
      plan; cross-game lessons per persona done, with veto; reputation across games next)
- [ ] Scenarios: teams, co-op goals and win conditions set in the lobby
- [x] Per-turn saves and backups (newest save copied before each poll, last 20 kept)

## Next
- [ ] **Jigsaw** (the author, 2026-10-26): algorithms first, the LLM only when a gate says so, every
      decision logged; one engine (`../jigsaw`), MTW2 its first game pack. Done: decision
      log, ladder and gate, every ruler decision recorded (#143), decision outcomes (#148, #154),
      the steward answering adoptions (#146), marriages (#150) and ransoms (#152) by rule for
      `ladder = true` seats, `just decisions` report (#151), and the turn gate for quiet turns
      (#155). Next: live steward and turn gate test on `scratch` (player slot), repair order
      (#157, merged), and the remaining decision-inventory rows. Public since 2026-11-04
      (github.com/williamblair333/jigsaw, v0.1.0); Parley pins its tag (#348).
- [ ] Ideas from Vox Deorum (Civ V LLM AI, github.com/vox-deorum/vox-deorum, arXiv 2512.18564;
      reviewed 2026-10-29). Its code is CC BY-NC-SA, so take ideas only, never code. For Jigsaw's
      steward: (1) the ruler picks strategy controls (a posture such as expand or wage war) that
      turn into steward weights, instead of one order a turn; (2) an explicit "keep the plan"
      answer, so a ruler isn't pushed into busywork; (3) a full ruler turn every N turns or on an
      event, quiet turns to the steward; (4) a pruned briefing (victory progress, diplomacy, local
      fronts): their input grew roughly with the square of the turn number; (5) a fixed-start
      benchmark that rates seats by Elo against the game's AI (their CivBench), to judge Gemini and
      Heretic fairly. Failure modes to watch for: no sense of the map (chokepoints, blockades),
      "phony wars" across the sea, and sticking with a losing plan.
- [ ] Every LLM faction can do what the human slot's ruler does (the author: the LLMs he'll play against
      must match Scratch). Rule: the LLM knows everything, decides, and its decisions take effect by
      direct EOP writes wherever possible, each following the game's rules (cost, slots, buildings,
      time); screen clicks only as a last resort for the human slot. Gaps for an AI-run seat today:
      family offers, papal votes and AI offers (the game decides them silently), game messages and
      news (human slot only). Measured on France. Done since: retraining and agent recruitment by
      direct write for any faction (PRs #107, #111; agents live since #118, rules from the EDB).
- [ ] Freeze each LLM faction's game AI once its decision coverage is complete (docs/decision-inventory.md)
- [x] Refresh docs/decision-inventory.md against the code and the live game (#156). Done 2026-10-26:
      updated with steward rows, retraining confirmed in master (done by direct write), repair route
      mapped (construction options + `addBuildingToQueue`), and upstream #89/#90 noted. Next: work
      down remaining ✗ rows.
- [x] Track every decision in one system for later analysis (the author, 2026-10-25). Designed with the author
      2026-10-26 as Jigsaw's decision log: every ruler order and steward choice, with rung, reason
      and legality, in `<turn_root>/<game>.decisions.db` (#143). Outcomes recorded for ruler orders
      (#148) and steward choices (#154, jigsaw#9). Reporting via `just decisions <game>` (#151).
- [x] Repair order (R3): merged (#157); proven on the bench 2026-11-04 (`towns/repair_queued`,
      #350): a repair is paid in full when queued.
- [x] OpenAI-compatible seat and Heretic (PR #153): `parley/seats/openai_compat.py` supports
      `heretic:local` and `openai:<model>` (llama-server :8090) with wait-and-retry. Benchmarked on
      scratch2 turn 24: 623 s, 16 kept, 4 rejected, 0 malformed (best non-Claude order quality, but
      GPU-shared latency exceeds 240 s timeout).
- [ ] Delegate by default (the author, 2026-10-25): research, first drafts, bounded code slices, reviews
      and second opinions go to agy (`gemini-4-argon-high`) or other models via the delegate MCP,
      with the check written first and `just test` as the gate. Claude keeps diagnosis, specs,
      reviews and merges. agy runs concurrent calls fine, each in its own workdir, so a Gemini
      seat in play is no reason to hold back.
- [ ] Gemini as ruler, in progress (2026-10-26: The author moved play to agy to save usage). flash-low
      collapsed England (no thinking; an every-turn merge loop; debt with no free lever); #176 fixed
      the prompt causes. Next: a fresh campaign with the fixes from turn 1, `just play-review` watching.
- [ ] (older) Fix Gemini as a ruler before any seat uses it again (the author, 2026-10-25). Live on France,
      turns 168-192: `agy:gemini-4-argon-medium` answered in 26-62 s when it worked but hung to the
      limit on 6 of 18 turns (agy's own --print-timeout never fired), and a killed loop left an agy
      call running as an orphan. Every seat moved to Claude. Hang found and fixed (PR #125: agy
      deadlocked in CLI teardown after answering; the seat now takes the streamed answer and kills
      the group). Left: soak argon-medium for 30+ live turns once its weekly quota resets
      (~2026-10-30). Flash failed as a ruler (0 orders, PR #128 notes). The fallback brain (PR #121)
      stays as the safety net.
- [x] EOP master crash at England's turn start: the bridge read master's building queue past its
      end (`getBuildingInQueue` counts from the buffer head; PR #135). The game runs master since
      2026-10-25. Reported upstream 2026-10-26 (EOP-Labs/M2TWEOP-library#88); master's treaties
      and recruitment queue are in the report (#138, #139).
- [x] Freeze a seat's game AI without stalling (#137): a frozen seat whose turn runs past 15 s gets
      its AI unfrozen until its next turn. Not yet seen live on a siege; England's freeze is still
      off in scratch2 (the author's call).
- [x] Fix Gemini seats (agy). Measured 2026-10-25 offline on England's real turns 166-167 (45 KB
      prompts, every area): `agy:gemini-4-argon-medium` answered in 28 s and 95 s, valid, no rejected
      or malformed orders, and it reasoned well (AI-run factions' peace doesn't lift sieges);
      `-low` 47-57 s, also clean; `-high` ran past 300 s, the same empty answer as Flash's: the
      empty answers are timeouts. Next: a live turn on argon-medium (the author's call which seat).
      The history: Live, scratch
      turns 77, 80, 88: `gemini-3.8-flash-low` timed out at 120 s and 240 s and returned empty answers
      on England's full report, and misread the stats behind a 4-star general. To do: find agy's
      stronger models (`agy --help` / model list), measure one full ruler turn on each (time, valid
      JSON, sensible orders), fix the empty-answer cause (timeout vs schema vs headless tool denial),
      then switch seats back from `claude:sonnet` when a model passes.

## Later
- [ ] Several humans and several LLM rulers in one campaign (the author, 2026-10-25). MTW2's hotseat mode
      gives each human a faction slot; every LLM faction is then an AI-run seat, so this needs the
      parity stage above (offers, votes and news for AI-run seats, direct-write actions), turn
      hand-off between humans, and a per-human view so nobody sees another's screen or report.
      Base already there: MTW2 hotseat campaigns, and EOP's online hotseat battles with results
      carried back to the campaign map (EOP README).
- [ ] Contribute to EOP upstream (EOP-Labs/M2TWEOP-library, a Windows C++ build; the author's account,
      public): what we had to work around or found missing. PR #90 submitted for #88 (`getBuildingInQueue`
      off-by-one fix), compile-tested on Gitea Windows runner. Feature request #89 filed (missions
      list, mercenaries, diplomacy, games/races, agent recruit cost, siege equipment). Remaining: test
      in game, event fields crash check.
- [x] Richer report: foreign armies and settlements nearby, real income
- [ ] Human /send and /cede commands (with Plan 3 ledger)
- [x] Cross-game memory for permanent personas, with a forget command (lessons store, `just lessons-veto`)
- [ ] A shared "general wisdom" pool every ruler draws on, once per-persona lessons look good
- [ ] `/claim <faction>` Discord command so humans can pick or switch factions per game
- [x] Full public write-up: docs/WRITEUP.md (kept current)
- [ ] Automated installer: one command from a fresh Steam install to a playable game
- [ ] Move from EOP to M2EX once M2EX ships Lua scripting publicly
- [ ] Remote friends on the LAN via Sunshine/Moonlight
- [ ] Turn timers and an AFK caretaker
- [ ] Catch-up chronicles in Discord
- [ ] Interception of transfers in transit
- [ ] Full granular LLM control (per-seat setting)
- [ ] Plain-language scenario goals judged by an LLM referee
- [ ] Choose a license and make the repo public
