# Changelog

All notable changes to this project are recorded here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
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
