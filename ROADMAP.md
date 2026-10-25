# Roadmap

## v1: the author vs a few talking LLM factions (local)
- [x] Approve the design doc
- [x] Switch the game to the Windows build under Proton and install M2EX (and EOP for Lua)
- [x] Prove the Lua file bridge: Lua file I/O, turn events and AI handover all verified in game
- [x] Orchestrator, LLM seats (Claude, local, Gemini) and the orders schema (Plan 1 Tasks 1–5)
- [x] Discord lobby and DMs, with LLM personas (Plan 2; persona library)
- [ ] Deal ledger, transfer logistics, kept/broken checks
- [ ] Reputation and memory across games (per-game memory done: notes + what changed; cross-game next)
- [ ] Scenarios: teams, co-op goals and win conditions set in the lobby
- [x] Per-turn saves and backups (newest save copied before each poll, last 20 kept)

## Next
- [ ] Every LLM faction can do what the human slot's ruler does (the author: the LLMs they'll play against
      must match Scratch). Rule: the LLM knows everything, decides, and its decisions take effect by
      direct EOP writes wherever possible, each following the game's rules (cost, slots, buildings,
      time); screen clicks only as a last resort for the human slot. Gaps for an AI-run seat today:
      family offers, papal votes and AI offers (the game decides them silently), retraining (screen
      only), game messages and news (human slot only). Measured on France.
- [ ] Freeze each LLM faction's game AI once its decision coverage is complete (docs/decision-inventory.md)
- [ ] Fix Gemini seats (agy), then use Gemini's Sonnet-level model or better, not Flash. Live, scratch
      turns 77, 80, 88: `gemini-3.8-flash-low` timed out at 120 s and 240 s and returned empty answers
      on England's full report, and misread the stats behind a 4-star general. To do: find agy's
      stronger models (`agy --help` / model list), measure one full ruler turn on each (time, valid
      JSON, sensible orders), fix the empty-answer cause (timeout vs schema vs headless tool denial),
      then switch seats back from `claude:sonnet` when a model passes.

## Later
- [ ] Richer report: foreign armies and settlements nearby, real income
- [ ] Human /send and /cede commands (with Plan 3 ledger)
- [ ] Cross-game memory for permanent personas, with a forget command
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
