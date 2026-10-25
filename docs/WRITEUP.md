# Parley: LLM rulers and Discord diplomacy for Medieval II

Play *Medieval II: Total War* against rulers that think and talk. Large language models (Claude,
Gemini, or a local model) rule some factions. Humans rule others, and the game's own AI runs the
rest. Everyone negotiates in Discord, in public or in private. A deal is only words: whether a
ruler honours it shows up in the game, and the LLMs remember who kept faith and who didn't.

This document covers everything: what it is, how it works, how to install it on Linux, how to
play, how to configure rulers and personalities, what goes wrong and how to fix it. The raw
build log, every attempt and failure included, is `docs/JOURNAL.md`.

---

## 0. Runbook: one command each

This assumes the one-time install (§4) is done. Run these in the repo folder (`mtw2`).

| Command | What it does |
|---|---|
| `just new-game game3 [options]` | creates `games/local/game3.toml` from your template: who plays, which personalities, which brains. `just new-game --help` lists every option with examples (§5a) |
| `just play game3` | stops anything running, starts the turn loop **and** the Discord bot in the background, and waits until the bot is connected |
| `just status` | what's running, and for which game |
| `just logs game3` | the latest output from both |
| `just stop` | stops both |
| `just reload-bridge` | installs the bridge, then the running game reloads it in place through EOP's `restartLua`. No relaunch needed. Orders already applied this turn aren't applied again. The game's per-turn autosave is the fallback: EOP's `saveGame` failed live ("cannot create m2tweop save file") |
| `just restart-loop game3` | restarts only the turn loop (new Python code); the bot keeps running |
| `just follow england game3` | follows one ruler live: everything it says (lobby, private threads, its adviser) and its private note each turn |
| `just report game3` | campaign report: per ruler turns answered, late, seat errors, treasury and settlements over time, messages; per order type issued, done, failed and rejected; every failure reason; which order types were never tried |

**Unattended test game (you just watch):**

```
just new-game soak --play all --personas random --scratch --autoplay --until 30 --wait 600 \
                   --seat venice=@rules-lawyer:script:games/soak-test.json
just play soak
```

Then start a **new** Grand Campaign as any faction (it's an LLM ruler too). Every faction is an LLM ruler.
One of them is secretly Old Scratch. Venice plays `games/soak-test.json`, a fixed plan that tries every
order type, bad ones included. The bridge ends your turn by itself as soon as every ruler has answered,
or after `--wait` seconds, then skips the late ones. A small **Parley** window says who it's waiting
for, and it stops at turn 30. Watch the map and `#soak`, then `just report soak`.

**Every game popup is answered for you.** Each stays up 3 seconds so you can read it, then the
bridge presses one of the scroll's own buttons:

| Popup | Pressed |
|---|---|
| A battle (`prebattle_scroll`) | auto-resolve |
| An AI's offer to your faction (`diplomacy_scroll`) | decline: the game doesn't say what's offered |
| A siege (`siege_scroll`) | keep besieging, or assault if the ruler ordered `besiege` with `"assault": true` |
| A captured settlement | occupy |
| Prisoners taken / your men captured | ransom / accept ransom |
| Anything else the game raises (results, warnings, crusades, elections, messages) | its OK, check mark or close button |

Scrolls you open yourself to look at things (finance, characters, settlements) are left alone.
The bridge logs every popup's buttons in `parley_turns/parley_bridge.log`. Your faction's ruler
gets a *game popups* list in its next report, saying what kind each was and what was pressed;
EOP can't read a scroll's text.

If one still gets stuck, there are fallbacks:
- Battles: autoplay turns on the game's "auto-resolve all battles" and clicks **Auto-resolve** on
  the pre-battle panel.
- A stuck turn: if your turn doesn't end a minute after the click, or an AI's turn sits still for two
  minutes, it tries the known popup buttons one at a time and logs `stuck?` in
  `parley_turns/parley_bridge.log`.
- Anything else: click it yourself.

**Observer game (an LLM plays your faction start to finish, you advise):**

```
just new-game watch --play all --autoplay --control england=full --adviser england \
                    --seat england=@william-the-conqueror:opus
just play watch
```

Start a **new** Grand Campaign **as England**. Your campaign faction has no game AI, so here
everything it does is the LLM's doing. It builds, sets taxes, moves and attacks with every army,
uses its agents and makes its own diplomacy. Its governors recruit (see `recruit` below). Autoplay ends its turns, the camera jumps to its
army, and the Parley window shows its current plan. Type `!adviser` in `#watch` to open your private
thread with it. It treats you as a loyal adviser, may overrule you, and tells you why.

**Control is per ruler** (`--control FACTION=…`, or `control = …` in the game file):

| Control | The LLM commands | The game handles |
|---|---|---|
| `diplomat` | diplomacy | everything else |
| `ruler` (default) | diplomacy, armies, agents | building, recruiting, taxes |
| `full` | everything but recruiting | recruiting |
| a list, e.g. `diplomacy,armies,build` | exactly those areas | the rest |

**Why `full` leaves recruiting out:** EOP 3.3.1 lists a settlement's recruits by reading past an
array in its own C++ code whenever units are inside (the retraining list). Lua can't prevent that,
and it can crash the game. A ruler given `recruit` explicitly sees recruit options only for
settlements with no units inside. Elsewhere it's told to march them out first.

On your campaign faction, "the game handles" means the settlement governors (auto-manage) do the
building and recruiting. EOP can't hand taxes to the governor, so taxes stay as they are. Armies the
LLM doesn't command stand still there. On AI factions, the game's own AI does the rest.

**Start a new game:** `just new-game game3 --rivals 6`, then `just play game3`, then in Steam **Play → Run Mod →**
a **new** Grand Campaign. Untick **Show CPU Moves**. Each turn, end your turn once `#game3` says
*"all rulers have decided"*.

**Continue a game:** `just play game2`, then load its save in the game.

**First time only:** `cp games/template.toml games/local/template.toml`, then set your Discord
username (`[humans]`) and server (`[discord] guild`) in it. `games/local/` is gitignored, so they
never get committed. Edit that template to mod factions: persona, name and brain per faction (§5a).

A new game name is a clean slate: no notes, no grudges, a new channel. Reusing a name continues that
game's memory and conversations.

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

## 5a. Setting up a game: the template and `just new-game`

**The template** (`games/local/template.toml`, your copy of `games/template.toml`) lists **every
playable faction**, each with a persona and an optional brain. Edit any block to mod that faction:

```toml
[factions.france]
persona = "@rules-lawyer"          # a library persona, or your own text in triple quotes
name = "King Philip the Fair"      # how he signs his messages
brain = "claude:opus"              # optional; otherwise [defaults] brain
```

Its top lines set the defaults for new games:

```toml
play = "random 6"                  # or ["france", "hre", "venice"], or "all"
personas = "template"              # or "historic", "archetypes", "random"
secret_scratch = false             # true: one rival is secretly Old Scratch
```

**`just new-game <name> [options]`** turns the template into `games/local/<name>.toml`, with random
picks written out so you can see (and edit) who's in. Options override the template. These are the
same examples `just new-game --help` prints:

| Command | Result |
|---|---|
| `just new-game game3` | the template as it stands: its play line, personas and brains |
| `just new-game game3 --rivals 6` | 6 random rivals, personalities from the template |
| `just new-game game3 --play france hre papal_states` | exactly these three rivals |
| `just new-game game3 --play all` | every faction is an LLM ruler (spectator mode) |
| `just new-game game3 --rivals 5 --personas historic` | 5 random rivals as their 1080 rulers |
| `just new-game game3 --rivals 4 --personas archetypes` | 4 random rivals, each a different archetype (never Scratch) |
| `just new-game game3 --rivals 6 --personas random` | a mix of historic rulers and archetypes |
| `just new-game game3 --rivals 6 --scratch` | one rival is secretly Old Scratch (see below) |
| `just new-game game3 --play france venice --seat france=@rules-lawyer:opus` | France is the Rules Lawyer on Opus |
| `just new-game game3 --rivals 3 --seat sicily=@scratch:opus` | Old Scratch openly as Sicily, plus 3 random rivals |
| `just new-game game3 --rivals 6 --brain flash` | every rival on Gemini Flash |
| `just new-game game3 --play france hre --brain opus --seat hre=@henry-iv-hre:sonnet` | Opus for all but the HRE |
| `just new-game game3 --ask` | answer a few questions instead of typing options |
| `just new-game game3 --from game2` | copy an existing game's seats under a new name |

**Brains:**
- shorthands: `sonnet`, `opus`, `haiku` (Claude), `flash` (Gemini via agy), `local` (Ollama);
- or a full spec: `claude:sonnet`, `agy:gemini-3.8-flash-low`, `ollama:qwen3.5:9b`.

**Personas:** any `@id` in `personas/*.toml` (§7).

**The secret Scratch:** with `--scratch` (or `secret_scratch = true`), one rival is quietly
replaced by Old Scratch on Claude Opus, still signing with his faction's normal ruler's name.
- The game file and the new-game summary look exactly as they would without him.
- Only `games/local/<name>.hidden.toml` says who it is, and `just notes` will show his notes.
  Both are spoilers.

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
- turn and year, treasury, net income (from the game's own ledger)
- settlements, armies, its own agents, factions and stances
- **what it can see**: foreign armies, foreign agents and foreign settlements within 10 tiles
  of any of its generals, agents or settlements, nearest 12 of each, with the distance. Nothing
  farther away is in the prompt, and the prompt says so.
- last turn's results, in the ruler's own numbering, rejections included
- *since your last turn*: wars, settlements lost or gained, armies gone, treasury change
- its last 5 notes
- recent diplomacy, labelled public or private
- output rules

**It answers with:**
- `orders`: gold, cede, stance, march, besiege, withdraw, and agent orders:
  - `assassinate` (its own assassin, a general or agent in sight)
  - `sabotage` (its own assassin, a settlement in sight)
  - `spy` (its own spy, a settlement or character in sight)
  - `bribe` (its own diplomat, a general, agent or settlement in sight)

  Agent orders are checked twice: by the orchestrator against the report, then by the bridge
  against the live game at turn start (the agent is alive, the right kind, and the target is
  still in sight). `done` means issued; whether the agent succeeded shows in the next report.
- with more control (see the control table in §0): `build` and `recruit` (from a settlement's
  "can build" and "can recruit" lists, priced; the checker deducts gold order by order), `set_tax`
  (low, normal, high, extortionate), `move_army` (toward a tile), `attack` (a foreign army in
  sight) and `merge_armies` (one army, or a garrison with no general, walks to join another;
  20 units at most). Agents can also `move_agent` (toward a tile; agents can't cross the sea
  alone) and a princess can `marry` (a foreign general in sight). The report then also lists each settlement's queue, tax and public order, and each
  army's troops and moves left. Orders outside a ruler's control are refused by both the checker
  and the bridge.
- `messages`: to `lobby`, to a faction someone actually plays, or to `adviser` if it has one; at
  most 3 per recipient per turn, 600 characters each;
- a private `note`. The faction you're watching shows its latest note in the Parley window.

**The adviser** (`--adviser FACTION[=USER]`) has a private Discord thread, `adviser ↔ <faction>`.
Type `!adviser` in the game channel to open it. Only the named user can speak for the adviser
there. The ruler's turn prompt says the adviser is loyal and may be overruled, and quotes the
thread with its other diplomacy. Other rulers never see it.

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
| The game minimizes when you switch to Discord | Play windowed: `PARLEY_WINDOWED=1 just install-eop`, or set `windowed = 1` and a resolution smaller than the screen (e.g. `1600 900`) in `mods/parley/parley.cfg` |
| Logo, intro or event movies | `just install-eop` turns them off (`movies`, `splashes`, `event_movies` and the agent movie switches in `mods/parley/parley.cfg`) |
| The game freezes at turn start | An old probe with a blocking wait; reinstall with `just install-bridge` |
| `PrivilegedIntentsRequired` | Turn on **both** privileged intents and **Save Changes** |
| The bot isn't in the server (`[]` from the guilds check) | The invite link lacked `scope=bot` |
| A ruler never replies | Check the bot terminal; Gemini flash-medium returns empty answers, so use flash-low |
| "agy returned an empty answer" | A timeout, or the model failed the JSON schema; agy calls also queue machine-wide |
| An order "done" but nothing happened | `ok` means issued, not succeeded (e.g. a siege when not adjacent); the next report shows the outcome |
| A ruler names armies from another campaign | Generals' names are random per campaign; use `$general` in scripted tests |
| Two messages at once from one ruler | A chat reply plus its turn message; that's expected |

## 11. Known limitations

- Sight is a 10-tile radius, not the game's real fog of war: EOP only exposes "ever seen"
  tiles, not "visible now". Hills, forests and watchtowers don't change it.
- Merchants, priests and princesses are listed but have no orders yet (no acquire, denounce or
  marry).
- Income is the game's figure for the turn just ended; it reads 0 ("not reported") if EOP
  can't say.
- Observer mode is untested in the live game. The new EOP calls are checked against EOP's source
  only. The tax numbers (0–3) are assumed. Auto-resolve and the popup buttons depend on timing.
  The first live run is the probe, so watch `parley_bridge.log`.
- LLM recruiting works only in settlements with no units inside (see above), and can't see units
  already queued (EOP doesn't expose that queue).
- Whether queueing a building or unit takes the gold isn't verified. The bridge logs the treasury
  before and after each queue (`parley_bridge.log`), so the first live run shows it.
- Popup recovery tries six known buttons, only those actually open when EOP can tell. After six
  tries it stops and the Parley window says *needs a human click*.
- Armies move toward a tile and stop when out of moves. A ruler has to re-issue a long march each
  turn. Merging, splitting and disbanding units aren't orders yet.
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
