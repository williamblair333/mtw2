# Handoff

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
