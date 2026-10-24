# LLM Factions & Diplomacy for Medieval II — Design

Date: 2026-10-23 · Status: draft for the author's approval

## Intent

The author wants to play Medieval II: Total War against rivals that *talk*. Some factions are
run by LLMs, some by humans, the rest by the game's own AI. The point is the politics:
deals struck in public or in private, kept or broken, remembered across games. A rival
should feel like a person with a reputation, not a difficulty slider.

Nothing like this exists. No project lets an LLM play Medieval II, and the game has no
free-text diplomacy. The pieces it rests on do exist: M2EX (a 64-bit engine overhaul) and
the EOP Lua scripting API, which M2EX implements.

## The finished picture (long term)

- One campaign runs on the author's Linux machine (Steam, Windows build under Proton, M2EX).
  It's a **hotseat** campaign, and every battle is **autoresolved**.
- Each faction seat is **human**, **Claude** (API key, or your subscription via Claude
  Code headless), a **local model** (Ollama), or **Gemini** (your subscription via `agy`).
  The author chooses per faction at game setup.
- **Discord is the table.** A public lobby channel plus private DMs/threads between
  factions. Humans and LLMs both talk there.
- **Remote human friends** on the LAN join by streaming the one game (Sunshine on the
  server, Moonlight on their PC) and play on their turn. No save-file passing.
- A game can last **one evening or several months**. The game waits at whoever's turn it is.
  A Discord bot pings the next player. Talk never pauses.

## First version (this design's build target)

The author alone, playing one faction, against **two or three LLM factions that negotiate with
him and with each other** in Discord. The rest of the world is the normal game AI.
Everything runs on the author's machine.

Out of scope for v1: remote friends and streaming, turn timers and AFK caretakers, catch-up
chronicles, public sharing or release.

## How it works

### 0. How much an LLM controls (the author decided)

- **v1: the LLM is the ruler, the game's AI is the general.** The game's own campaign AI
  runs the LLM faction's routine play: recruiting, building, moving armies, garrisons. The
  LLM sets goals and does all diplomacy, and it gives **specific orders when they matter**:
  send gold, hand over a region, make peace or war, pull an army back from X, march on Y,
  besiege Z. Those orders override the AI for that turn.
- **Built to grow into full control.** The orders schema and the game-side order handler are
  designed so finer orders can be added one at a time later (recruit this unit, set this tax
  rate, move this agent), up to the LLM playing every piece itself. The control level is a
  per-seat setting.
- Open technical question for step 1: in a hotseat game, can a script hand an LLM seat's
  turn to the game's AI, then apply the LLM's overrides? If not, the fallback is to leave
  LLM factions as normal AI factions (not hotseat slots) and have the bridge run on their
  turn events. Builder picks whichever works and records why.

### 1. The game side (Lua in M2EX)

- On an LLM faction's turn, a script **writes a state report** to a file: treasury and
  income, settlements (garrison, buildings, growth), armies and agents with positions and
  strength, visible enemies, diplomatic stances, and pending transfers (below).
- It then **waits for an orders file**, checks each order, carries out the valid ones,
  records which orders failed and why, and ends the turn.
- **Bad orders never crash the game.** An order the engine wouldn't allow gets rejected and
  reported back to the LLM, never forced through.
- **First build step: prove the file bridge.** Confirm that the M2EX/EOP Lua environment
  can read and write files and wait for one. If it can't, the fallback is a native plugin
  or another channel. That would be a design change, brought back to the author.

### 2. The orchestrator (Python, on the same machine)

- Watches for state reports, turns each one into a prompt for that faction's LLM, validates
  the LLM's answer against a fixed orders schema, and writes the orders file.
- **Report and orders are the same for every brain.** Swapping Claude for a local model
  changes nothing else.
- Keeps every turn's report, orders and results on disk, so a turn can be replayed or debugged.
- **Saves the campaign every turn** and keeps rotating backups. A months-long game must
  never be lost to one bad turn.

### 3. Discord: the table

- A bot account per LLM persona (or one bot that speaks as several personas: builder's call).
- **Public lobby channel:** open talk. Deals sworn there are **public deals**.
- **Private DMs/threads:** back-room talk. Only the two parties see it.
- LLMs answer when spoken to, even off-turn. They also talk unprompted on their turn when
  they have reason to: proposals, threats, demands.
- **LLMs negotiate with each other too** (the author decided), in public and in private threads.
  Discord bots can't DM each other, so bot-to-bot back-rooms are private threads the author can't
  see in normal play (a hidden admin view is fine for debugging). Limits are needed so bots
  don't talk forever: a cap on messages per pair per turn, and conversations close when the
  turn ends. (Exact numbers are the builder's call.)

### 4. Deals: talk is free, honoring is an action

- A deal is just words. **Nothing enforces it.** Each side chooses whether to honor it.
- Honoring means doing it in the game: send gold, hand over a region, sign peace or an
  alliance, pull an army back.
- **Transfers between seats go through the bot** (Claude's call), e.g. `/send 2000 to
  Venice` or `/cede Milan to France`. That's what applies the delivery delay. LLMs issue
  the same transfers in their orders. The game's own diplomacy screen isn't locked, but the
  deal checker reads real treasury and region changes, so a deal kept by any route counts.
- **Logistics take time.** Gold and land transfers start when sent and arrive later, with
  the delay based on distance between the factions' capitals or the regions involved. The
  sender pays at once and the receiver gets it on arrival. (Builder sets the formula. The author
  suggested "how long it'll take to get the gold / transfer the land." Interception risk on
  the way is a later idea, not v1.)
- The system **logs deals** from the conversation as structured records (who, what, by
  when), then **checks the game state** to mark each one kept, late, partly kept, or broken.
  The LLM that's party to the deal confirms the record. The author confirms theirs.
- **Disputed deals** (Claude's call): if the parties don't agree on what was said, the deal
  is recorded as *disputed*, with both versions and a link to the chat. Disputing is itself
  part of a player's record.

### 4b. Scenarios: custom goals set in the lobby (the author decided)

- Before or during a game, players can set **goals the base game doesn't have**:
  - teams, e.g. all humans vs all LLMs, with the first side to do X winning
  - full co-op, e.g. everyone works together to get gunpowder units by the earliest year
  - anything else that can be judged from the game state
- A scenario defines: teams (or none), one or more win/lose conditions, and an optional
  deadline year. The system checks conditions every turn against the state reports and
  announces progress and the result in the lobby.
- LLM seats get the scenario in every prompt, so they play to it: cooperate with their team,
  or betray it if the scenario allows.
- v1 condition types (Claude's call): hold N regions or named settlements, have a building
  or unit type, reach a treasury amount, eliminate a faction, all by a given year. Conditions
  written in plain language and judged by an LLM referee are a later step.
- Scenarios and their results go into the cross-game record, e.g. who betrayed their team in
  the humans-vs-LLMs game.

### 5. Reputation and memory

- **Profiles belong to players, not factions,** and last across games. "the author" or the Claude
  persona "Doge Enrico" keeps its history whichever faction it plays next.
- **Public record:** every public deal, sworn in the lobby, with its outcome. Anyone can
  look it up.
- **Private memory:** each LLM keeps what was said to *it* in private and what happened
  after. Nobody else sees it. A player can leak it in the lobby, truthfully or not.
- Patterns emerge from this. One rival keeps every public oath and backstabs in private.
  Another forgives nothing. LLMs build these profiles of each other, and of the author, over many
  games.
- **Personas:** each LLM seat gets a persona with a name, temperament, and negotiating
  style, so they don't all play the same polite diplomat. Memory belongs to the persona.

### 6. Seats and brains

- v1 order of support (Claude's call): **Claude Code headless on your subscription**
  and **local Ollama** first, then **Gemini via `agy`**. The **Claude API** is optional,
  with a spending cap per game.
- CLI-based brains (Claude Code, `agy`) start slowly and have rate limits. The builder must
  keep LLM turns quick (anti-goal 4), e.g. by having LLM factions think in parallel.
- Local via Ollama. Expect it to be weaker, which gives natural difficulty and rivals that
  are easier to fool. Its output must be validated hard against the orders schema.

## Anti-goals: if any of these happen, v1 has failed even if it runs

1. **Pushover LLMs.** They agree to everything and never betray. They need real interests and
   the willingness to say no or backstab.
2. **Dumb on the map.** They talk well but play badly: empty cities, wandering armies. What
   they say and what they do must line up.
3. **Lying from confusion.** Claiming gold or armies they don't have because they misread the
   report. Deliberate bluffs are fine. Confusion isn't.
4. **Slow turns.** The author ends their turn and waits ten minutes. LLM turns must be quick.
5. **Lost or corrupted campaigns** from crashes or bad orders.
6. **Memory that doesn't stick:** forgetting a betrayal or mixing up who said what.
7. **Fiddly setup:** starting a game should be one `just` command plus picking seats.

## Constraints

- Linux host. Steam Definitive Edition (appid 4700), switched from the Feral Linux port to
  the Windows build under Proton 10+. That costs a ~18 GB redownload.
- M2EX stable 17/08 or newer. No 4 GB patch needed.
- Autoresolve all battles. LLMs never fight tactical battles.
- Private Git repo for now, on the author's Gitea. Written so it can go public later: no secrets in
  the repo, and API keys and Discord tokens in an untracked `.env`.
- `justfile` recipes for setup, start and stop, per the author's convention.
- Offload research and grunt work to Gemini via `agy` where it fits. Claude verifies what
  Gemini returns before anything gets acted on.

## Decided by Claude (the author can overrule)

- Transfers go through bot commands, disputed deals get recorded as disputed, the v1
  brain order and the v1 scenario condition types (all above).
- Engine: M2EX on the vanilla grand campaign, using the EOP-style Lua API.
- Orchestrator, Discord bot and LLM adapters in Python. SQLite for deals, public records,
  private memory and personas.
- Game↔orchestrator over files on disk, if the Lua environment allows it.
- Turn order is the game's own hotseat order.

## Left to the builder

- The exact state-report and orders schemas.
- How big the report gets: summary vs full detail, fog of war.
- The transfer-delay formula.
- How deals are pulled out of chat: LLM extraction, a `/deal` slash command, or both.
- One bot per persona vs one bot for all.
- The memory design: summaries, retrieval, what goes in each prompt.
- How quick turns get: parallel LLM thinking, time limits per turn.

## Research in progress

Gemini is checking the EOP Lua API for file I/O, turn events, state queries, order
functions, diplomacy and money/settlement transfers, hotseat setup, and crash risks. The
report lands in `_review/`. Claude verifies it before the plan relies on it.
