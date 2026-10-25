# Handoff

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
