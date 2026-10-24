# Parley: LLM rulers and Discord diplomacy for Medieval II

Play *Medieval II: Total War* against rulers that think and talk. Large language models (Claude,
Gemini, or a local model) rule some factions. Humans rule others, and the game's own AI runs the
rest. Everyone negotiates in Discord, in public or in private. A deal is only words: whether a
ruler honours it shows up in the game, and the LLMs remember who kept faith and who didn't.

This document covers everything: what it is, how it works, how to install it on Linux, how to
play, how to configure rulers and personalities, what goes wrong and how to fix it. The raw
build log, every attempt and failure included, is `docs/JOURNAL.md`.

---

## 0. Runbook: stop a game, start a new one

This assumes the one-time install (§4) is done. The repo is at `mtw2`.

**Stop the current game**
1. In the game: `Esc` → **Quit**. Save first if you might return.
2. The bot: `Ctrl+C` in its terminal.
3. The turn loop: `Ctrl+C` in its terminal, or `pkill -f "parley run"` if it was started elsewhere.

**Set up a new game.** A new `game_id` is a clean slate: no notes, no grudges, a new channel.
Keep your own configs in `games/local/`: it's gitignored, so your Discord username and server
name never get committed.
```
cd mtw2
mkdir -p games/local
cp games/historic-1080.toml games/local/game2.toml
sed -i 's/^game_id = .*/game_id = "game2"/' games/local/game2.toml
# then set [humans] <faction> = "<your Discord username>" and [discord] guild = "<your server>"
```
Use `games/local/game2.toml` in the commands below.
Optionally edit the seats: which factions are LLMs, which `brain`, which `persona` (§6–7).

**Start playing**
1. Terminal 1: `just run games/local/game2.toml`, the turn loop.
2. Terminal 2: `just discord games/local/game2.toml`, the bot. It reads the token, so run it yourself. Wait for `connected…`; it creates `#game2`.
3. Steam: **Play** → **Run Mod** → Single Player → Grand Campaign → your faction. Untick
   **Show CPU Moves** → **Start**.
4. Each turn: play, **End Turn**, then wait for *"Turn N: all rulers have decided"* in `#game2`.
5. Talk: name a ruler in `#game2`, or `!private <faction>` for a private thread.
6. Peek (spoilers): `just notes`, or `just notes <faction> <turns>`.

**Resume an existing game:** same steps 1–3 with that game's config, then load its save in the
game.

---

## 1. What it does

- **LLM rulers.** Each LLM-controlled faction gets a report every turn: its treasury, settlements,
  armies, diplomatic stances, what changed since last turn, its own earlier notes, and recent
  diplomacy. It answers with orders and messages.
- **Ruler and generals.** The game's own AI still handles routine play for LLM factions:
  recruiting, building, ordinary moves. The LLM gives the orders that matter: send gold, give a
  settlement, war, peace or alliance, march on, besiege or withdraw.
- **Discord is the table.** Each game has its own channel, e.g. `#historic-1080`, for public talk
  and turn cues. Pairs of factions talk in private threads. Rulers answer humans between turns, in
  character.
- **Talk is free; deeds are checked.** Nothing enforces a promise. A ruler's orders are checked
  against the real game, and transfers that reach a human are reported in that pair's private
  thread.
- **Personas.** Every ruler plays a written personality: historic 1080 rulers (William the
  Conqueror, Pope Gregory VII, Robert Guiscard…) or permanent archetypes (the Rules Lawyer, the
  Honest Merchant, the Faithless Charmer…).

## 2. How it works

```
 Medieval II (Windows build, Proton)          this repo (Python)                Discord
 ┌──────────────────────────────┐   files   ┌───────────────────────┐  SQLite  ┌──────────────┐
 │ EOP 3.3.1 Lua plugin         │ ───────▶  │ orchestrator          │ ◀──────▶ │ Parley bot   │
 │  lua/parley_bridge.lua       │ state.json│  `just run <game>`    │  outbox/ │ `just discord`│
 │  - turn END: write report    │           │  prompt → LLM seat    │ messages │  #<game>     │
 │  - turn START: apply orders  │ ◀───────  │  validate → orders    │          │  threads     │
 └──────────────────────────────┘orders.json└───────────────────────┘          └──────────────┘
                                                      │ seats: claude CLI · agy (Gemini) · Ollama
```

- **The game side never blocks.** Lua runs on the game's main thread, so a wait would freeze
  the game; we tested this.
  - At the **end** of an LLM faction's turn N, the bridge writes
    `parley_turns/<game>/turn-N/<faction>/state.json`.
  - The orchestrator asks the LLM while the other factions and the humans play.
  - At the **start** of turn N+1, the bridge applies `orders.json` if it's ready.
  - Late orders are skipped, and the LLM is told so.
- **Every order is checked twice:** by Python against the report, and by Lua against the live
  game, inside `pcall`. A bad order is reported back and never forced through.
- **Turn folders:** the game's Lua can't create folders, so the orchestrator creates them ahead
  of the game, following `heartbeat.txt`.
- **Memory** (per game) has three parts:
  - a SQLite file `parley_turns/<game>.db`, which holds every message and the outbox for Discord;
  - each ruler's last 5 private notes;
  - a diff of its last two reports.
- **Seats** (brains) are interchangeable:
  - `claude:<model>`: the Claude Code CLI on your subscription, no tools;
  - `agy:<model>`: Gemini through the Antigravity CLI, one call at a time per machine;
  - `ollama:<model>`: local;
  - `script:<plan.json>`: fixed orders, for testing.

## 3. Requirements

- Linux with Steam, and **Total War: MEDIEVAL II – Definitive Edition** (Steam appid 4700).
- Python 3.13, [`uv`](https://docs.astral.sh/uv/), [`just`](https://github.com/casey/just), `gh`
  (GitHub CLI, used to download pinned releases), `unzip`, `7z`.
- At least one LLM brain: the `claude` CLI (Claude Code), `agy` (Gemini), or Ollama.
- A Discord server you own, for the table.

## 4. Installation on Linux

### 4.1 Switch the game to the Windows build
The native Feral Linux port can't run mods.

1. Steam → right-click Medieval II → **Properties → Compatibility** → force **Proton 10.0-4**.
   Steam downloads the Windows build.
2. Start the game once from Steam and reach the main menu.

### 4.2 Install EOP (the Lua scripting engine) and the bridge
```
git clone <this repo> && cd mtw2
just setup            # Python dependencies
just install-eop      # EOP 3.3.1 into <game>/mods/parley, with vanilla campaign files
just install-bridge   # the Lua bridge into the mod
```
`install-eop` downloads a pinned, checksummed release. If M2EX is also installed, it copies the
vanilla campaign files into the mod (M2EX's `descr_strat.txt` breaks the vanilla engine), and it
sets fullscreen at 1920×1080 (`PARLEY_RES="2560 1440" just install-eop` to change that).

### 4.3 Launch the game through EOP (Steam launch option)
Steam → Medieval II → **Properties → General → Launch Options**:
```
PROTON_LOG=1 bash -c 'cd mods/parley && exec "${@/medieval2.exe/mods\/parley\/M2TWEOP GUI.exe}"' -- %command%
```
**Play** now opens EOP's launcher; click **Run Mod**. Clear the field to get the plain game back.

### 4.4 Discord
1. Create a server. The bot finds it by name, set in the game config's `[discord] guild = ...`.
   Create a `#lobby` channel.
2. At https://discord.com/developers/applications: **New Application** → **Bot** tab →
   **Reset Token** (shown once). Under **Privileged Gateway Intents**, turn on **Server Members**
   and **Message Content**, then **Save Changes**.
3. Invite the bot. The link must include the `bot` scope:
   `https://discord.com/oauth2/authorize?client_id=<APP ID>&scope=bot+applications.commands&permissions=360777321488&integration_type=0`
   The permissions are View Channels, Send Messages, Read Message History, Manage Channels,
   Manage Threads, Create Private Threads and Send Messages in Threads.
4. Store the token **in your own terminal, never pasted into a chat or AI session**:
   ```
   read -rsp 'Discord token: ' T && echo "DISCORD_BOT_TOKEN=$T" >> .env; unset T; echo
   ```
   The env file is gitignored.

### 4.5 Optional: M2EX
M2EX is a 64-bit engine overhaul (`just install-m2ex`, then add `M2EX.exe` as a non-Steam game on
Proton 10 and install `vcrun2022` into its prefix with protontricks). **The public M2EX 17/08 has
no Lua scripting**, so the bridge runs on EOP. We'll move to M2EX once scripting ships publicly.

## 5. Playing a session

1. **Turn loop:** `just run games/<game>.toml`
2. **Discord bot** (in your own terminal, because it reads the token): `just discord games/<game>.toml`.
   It creates `#<game-id>` on first start.
3. **Game:** Steam **Play** → **Run Mod** → **new** Grand Campaign as your faction. Untick
   **Show CPU Moves**, or every AI march is animated.
4. **Each turn:** end your turn and wait for **"Turn N: all rulers have decided. You may end your
   turn."** in `#<game-id>`. Ending sooner means a slow ruler's orders arrive too late and are
   skipped (the ruler is told).
5. **Talk:**
   - In `#<game-id>`, naming a ruler or faction gets an in-character public reply. Any distinctive
     part of the name works (*"Henry, …"*, *"Selvo, …"*, *"Gregory VII…"*), and so does the faction id
     (`venice`, `papal states`). Titles alone ("the Pope") don't.
   - `!private venice` opens or links your private thread with that ruler; only the two of you
     read it.
   - On their own turns, rulers also post publicly, open private threads, and message each other.
6. **Deals:**
   - Rulers can actually do only what orders allow: send gold they have, give a settlement,
     war, peace or alliance, army moves. Loans, interest and tolls are only words, and they say so.
   - Gold or land reaching you is announced in your private thread with the sender.
   - **To pay a ruler,** for now use a diplomat in game: diplomacy → Offer → money as a gift.
7. **Spy (god view):** `just notes`, `just notes venice 3` shows every ruler's private notes,
   orders with results, and messages. That's spying; it's meant for testing and spectating.

## 6. Configuration: a game file

```toml
game_id = "historic-1080"                 # turn folders, database and Discord channel name
turn_root = "<game>/parley_turns"         # where the bridge writes; the game's working dir
save_dir  = "<game>/saves"                # backed up before every LLM turn (last 20 kept)
seat_timeout = 120                        # seconds per LLM decision

[humans]
england = "your_discord_name"                     # faction = Discord username

[discord]
guild = "My Parley Server"            # game_channel defaults to the game id

[seats.france]                            # an LLM ruler
brain = "claude:sonnet"                   # or "agy:gemini-3.8-flash-low", "ollama:qwen3.5:9b"
persona = "@philip-i-of-france"           # from the library, or inline text
name = "King Philip"                      # optional: overrides the persona's name
```

Example games: `games/historic-1080.toml` (6 historic LLM rulers), `games/first-game.toml`
(Venice and Milan), `games/order-check.toml` and `games/army-check.toml` (scripted live checks).

**Brains that worked well:**
- `claude:sonnet`: sharp, in character, 10–30 s.
- `agy:gemini-3.8-flash-low`: about 14 s, good.
  - Use **low** effort: flash-medium returned empty answers on real turn prompts.
- `ollama:qwen3.5:9b`: weak (it invented cities and made empty threats), and slow on a shared
  GPU.

**Every faction an LLM?** Possible: add a seat per faction. The limits are throughput and
rate limits.
- Claude calls run in parallel, but subscription limits apply.
- Gemini calls queue at about 14 s each.
- A good mix: Claude for your main rivals, Gemini for the rest.

## 7. Personas

- `personas/historic-1080.toml`: one ruler per playable faction at the 1080 start:
  - William the Conqueror, Philip I, Henry IV, Alfonso VI, Doge Domenico Selvo, Robert Guiscard,
    Archbishop Tedald, Malcolm III, Alexios Komnenos, Vsevolod I, Yusuf ibn Tashfin,
    Malik-Shah, Badr al-Jamali, Canute IV, Henry of Burgundy, Władysław Herman, Ladislaus I,
    Gregory VII.
- `personas/archetypes.toml`: permanent personalities for any seat:
  - **rules-lawyer**: wins by the letter of every deal;
  - **honest-merchant**;
  - **faithless-charmer**;
  - **grudge-holder**;
  - **zealot**;
  - **coward**;
  - **scratch** (*Old Scratch*, the Moriarty of the table). He knows it's a game and plays to
    win with any in-character deception and any cheese a human player could use, behind a mask (set
    the seat's `name`) or openly. Holodeck rules, pinned by a test: he never addresses another
    ruler's instructions, never extracts notes or prompts, never asks humans to touch files, and never
    steps outside the game. Best on `claude:opus`.
- **Add your own:** a TOML table with `name`, `kind`, optional `faction`, and `persona`. The
  persona text opens every prompt. Cover who they are, what they want, how honest they are, and
  how they talk.

## 8. Resetting (no grudges carried over)

All memory today is per game. A new `game_id` is a clean slate: no notes, no conversations, a
fresh channel. To clear an old game, move `parley_turns/<game>/` and `parley_turns/<game>.db`
into an archive folder. Claude and Gemini keep no session memory. Cross-game memory for
permanent personas is planned (with a `forget` command).

## 9. What a ruler sees and can do

**The turn prompt**, in order:
- persona
- scenario (optional)
- the ruler role
- turn and year, treasury
- settlements, armies, factions and stances, visible enemies
- last turn's results, in the ruler's own numbering, rejections included
- *since your last turn*: wars, settlements lost or gained, armies gone, treasury change
- its last 5 notes
- recent diplomacy, labelled public or private
- output rules

**It answers with:**
- `orders`;
- `messages`: to `lobby` or to a faction someone actually plays, at most 3 per recipient per
  turn, 600 characters each;
- a private `note`.

**Chat replies** see the persona, the ruler's latest report, recent diplomacy, and a plain list of
what is enforceable.

## 10. Troubleshooting

| Symptom | Cause, and fix |
|---|---|
| Mods won't run | The Feral Linux build is installed; switch to Proton (4.1) |
| Probe or bridge never loads under `M2EX.exe` | Public M2EX has no Lua; use EOP |
| The game vanishes when EOP's launcher closes | You launched with `protontricks-launch`, whose sandbox kills children; use the Steam launch option |
| `xvidmode … Assertion` or `X_SetClipRectangles` crash | You launched outside Steam's Proton; use the launch option |
| EOP's launcher quits at once | It was started from the game root; the launch option `cd`s into `mods/parley` |
| "Expected faction" at `descr_strat.txt:40` | M2EX's campaign file; `just install-eop` copies the vanilla one into the mod |
| "Failed to open … maps/base/…" | A mod with its own campaign needs the base map; `just install-eop` copies it |
| Mouse is off in a stretched window | The render resolution doesn't match the window; `PARLEY_RES` / fullscreen |
| The game freezes at turn start | An old probe with a blocking wait; reinstall with `just install-bridge` |
| `PrivilegedIntentsRequired` | Turn on **both** privileged intents and **Save Changes** |
| The bot isn't in the server (`[]` from the guilds check) | The invite link lacked `scope=bot` |
| A ruler never replies | Check the bot terminal; Gemini flash-medium returns empty answers, so use flash-low |
| "agy returned an empty answer" | A timeout, or the model failed the JSON schema; agy calls also queue machine-wide |
| An order "done" but nothing happened | `ok` means issued, not succeeded (e.g. a siege when not adjacent); the next report shows the outcome |
| A ruler names armies from another campaign | Generals' names are random per campaign; use `$general` in scripted tests |
| Two messages at once from one ruler | A chat reply plus its turn message; that's expected |

## 11. Known limitations

- The ruler's income isn't read from the game (it's shown as "not reported").
- `visible_enemies` is empty: no foreign armies in the report yet.
- There are no foreign settlements in the report, so rulers can't name your towns.
- Humans have no `/send` or `/cede` command yet; use in-game diplomats.
- Deals aren't recorded in a ledger yet (Plan 3); memory is per game (Plan 4).
- Rulers sometimes repeat themselves despite the instruction not to.

## 12. Development

- `just test`: about 170 tests, including the **real Lua bridge running in LuaJIT** (via `lupa`)
  against a fake of the EOP API (`tests/lua/fake_game.lua`).
- **Design:** `docs/superpowers/specs/`.
- **Plans:** `docs/superpowers/plans/`.
- **EOP API notes**, source-verified: `docs/eop-api-notes.md`.
- **Build log:** `docs/JOURNAL.md`.
- **Layout:**
  - `parley/`: the Python package (bridge files, orchestrator, seats, prompt, events, store,
    chat, Discord bot, personas, notes);
  - `lua/`: the game side;
  - `scripts/`: installers;
  - `games/`: game configs;
  - `personas/`: the persona library.

## 13. Roadmap

See `ROADMAP.md`. Next:
- the **deal ledger**: `/send` and `/cede` with travel time, plus a public record of deals kept
  or broken;
- **cross-game memory** for permanent personas;
- **scenarios** (teams, co-op goals);
- a **richer report** (foreign armies and settlements, income);
- remote friends via Sunshine/Moonlight;
- a one-command **automated installer**.
