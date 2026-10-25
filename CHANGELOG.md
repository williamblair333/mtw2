# Changelog

All notable changes to this project are recorded here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
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
