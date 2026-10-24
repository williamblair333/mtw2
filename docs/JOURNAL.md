# Build journal

A running log of what was done, why, and what went wrong, so others can follow along.
Newest entries go at the bottom. It's the raw material for the full write-up and the
automated installer (see ROADMAP).

Machine for all entries: Linux (Liquorix kernel), Steam, RTX 3060 12 GB,
Steam *Total War: MEDIEVAL II – Definitive Edition* (appid 4700).

---

## 2026-10-23: research and design

- Surveyed the maintained engine projects:
  - **M2EX/REX** (github.com/Pannoniae/rex): a 64-bit engine overhaul. Latest public release 17/08 (2026-08-17).
  - **M2TWEOP/EOP** (github.com/EOP-Labs/M2TWEOP-library): patches the game in memory and exposes a Lua API. Latest 3.3.1.
  - M2EX's developer says M2EX implements "pretty much all" of EOP's Lua API (rex issue #40).
- Found nothing where an LLM plays Medieval II, so this project builds it.
- Brainstormed the design with the author: LLM and human factions, all battles autoresolved, negotiation in Discord, deals that are only words, reputation across games, and scenarios. See `docs/superpowers/specs/2026-10-23-llm-diplomacy-design.md`.
- Control level for v1: **the LLM rules, and the game's AI does routine play**, with specific overrides. Built so it can grow into full control later.

## 2026-10-23: Python turn loop (Plan 1, Tasks 1–5), PR #1

- `parley` package:
  - protocol and order validation
  - atomic file bridge
  - prompt builder
  - seats for Claude (`claude -p --json-schema`), Ollama, Gemini (`agy`) and a fake seat
  - orchestrator
  - save backups
  - a simulated game (`just fake-game`)
- Live seat tests drove fixes:
  - `claude` rejects the `discriminator` keyword in schemas.
  - Ollama's thinking mode took 35 s, so it's turned off.
  - Ollama left out a defaulted `type` field, so it's now required.
  - Concurrent `agy` calls come back empty, so they're serialized machine-wide.
- A fresh whole-branch review found 1 critical and 5 important bugs. Each was fixed with a test that failed first. The critical one: any unexpected error stopped the orchestrator.
- Ollama is slow here (73–120 s per turn) because the GPU is shared with other services.

## 2026-10-23: game on Linux, scripting probe (Plan 1, Task 6), PR #2

1. **Switched the game to the Windows build:** Steam → Properties → Compatibility → Proton 10.0-4. Download 2.9 GB. It runs fine.
2. **Installed M2EX 17/08** (`just install-m2ex`):
   - Checksum pinned. It replaces 4 vanilla files, backed up to `.parley-backup/<date>/`.
   - Added `M2EX.exe` as a non-Steam game on Proton 10. The first launch crashes, as expected.
   - Installed `vcrun2022` into its prefix with `protontricks 2430303030 -q vcrun2022`.
   - M2EX runs well.
3. **Problem: public M2EX has no Lua.** The probe script never loaded, and M2EX's log never mentions Lua. Scripting exists only in test builds on M2EX's Discord. **Decision:** use EOP 3.3.1 for v1 and move to M2EX when scripting ships publicly.
4. **Installed EOP 3.3.1 as its own mod folder** (`just install-eop` → `mods/parley`), leaving the vanilla game and M2EX untouched. In 3.3.1, scripts load from `youneuoy_Data/plugins/lua/luaPluginScript.lua`.
5. **Launching EOP on Linux took several tries.** Each failure and its cause:
   - `protontricks-launch` sandbox: the game died when EOP's launcher exited, because the sandbox shuts down with its main process.
   - `--no-bwrap`: Wine's X11 driver crashed on the fullscreen mode switch. Windowed mode then hit a second X11 error.
   - **What works:** let Steam launch it, with a launch option that swaps the exe for EOP's launcher, run from the mod folder:
     `PROTON_LOG=1 bash -c 'cd mods/parley && exec "${@/medieval2.exe/mods\/parley\/M2TWEOP GUI.exe}"' -- %command%`
   - Starting from the game root makes EOP's launcher quit immediately, which is why the command does `cd mods/parley` first.
6. **Campaign wouldn't start.**
   - "Expected faction" at line 40: M2EX's `descr_strat.txt` uses commands only M2EX understands. Fix: the mod carries the vanilla copy from the backup.
   - Then "Failed to open … maps/base/map_heights.tga": a mod with its own campaign must also carry the base map. Fix: copy the vanilla `data/world/maps/base` and campaign folder into the mod. `install_eop.sh` now does this.
7. **Mouse broken in a stretched window:** the game rendered at 1024×768. Fix: render at 1920×1080 (`PARLEY_RES` overrides).
8. **Probe results** (details in `docs/eop-api-notes.md`):
   - (a) Lua can read and write files.
   - (b) `onFactionTurnStart` fires for every faction, with name, id, money, settlements and armies.
   - (c) `isPlayerControlled` can be changed, so a faction can be handed to the AI.
   - (d) A blocking wait freezes the game.
9. **Decision from (d): the bridge never waits.** It writes the report at turn end, the LLM thinks during other turns, and the prepared orders are applied at the next turn start.
10. The probe's 15 s test wait felt like the game "just sat there" at end of turn. It was removed once (d) was answered.

Tip for players: untick **Show CPU Moves** on the campaign setup screen, or every AI army's march gets animated.

## 2026-10-23: Gitea

- The private repo `bill/mtw2` was created through two one-use `write:user` tokens, because the stored token can't create repos.
- Those tokens must be revoked in the UI: the Gitea CLI can't delete tokens, and the API needs the account password.
- `main` is protected by a local push guard, so all changes land through PRs.

## 2026-10-23: the live bridge (Plan 1, Task 7)

- **The EOP 3.3.1 API was mapped from source** by a research agent. Claude spot-checked five key calls. The table is in `docs/eop-api-notes.md`.
- **Timing (from probe result d):** the bridge never waits.
  - At the **end** of an LLM faction's turn N, it writes `parley_turns/<game>/turn-N/<faction>/state.json`.
  - At the **start** of turn N+1, it applies `orders.json` from that folder if the orchestrator has answered, and writes `results.json`.
  - Orders that are late are skipped and logged.
- **The game's Lua can't create folders.** So the orchestrator writes `parley_turns/bridge.txt` (the game ID and the LLM factions) and creates turn folders 5 turns ahead.
- **Every order is re-checked against the live game and wrapped in `pcall`.** A bad order is reported in `results.json` and never stops the others.
- **Testing without the game:** `lupa` (LuaJIT inside Python) runs the real bridge against a fake of the EOP objects (`tests/lua/fake_game.lua`). That's 17 tests.
- **Bugs those tests caught before the game ever saw them:**
  - Lua's `%w` doesn't match `_`, so `game_id=` never parsed.
  - The vendored JSON library can't write `null`. Missing keys now mean "none" on the Python side.
- Install: `just install-bridge`. It replaces the probe in `mods/parley`.

## 2026-10-23: first live game: the loop works

Setup: `games/first-game.toml`. The author plays England, Venice is `claude:sonnet` and Milan is `ollama:qwen3.5:9b`. Running `just run games/first-game.toml`, the author played 3 turns.

- **End to end works.** Reports were written at the end of Venice's and Milan's turns. Claude answered in about 8 s and qwen in 5–12 s. The bridge applied the orders at the next turn start and wrote `results.json`.
- **The report carries real game data.** Venice: treasury 6,003, settlements Venice, Iraklion and Ragusa, Captain Pascal and two admirals, and its stance toward every faction.
- **Bug: the game's first turn is 0.** Folders were only prepared from turn 1, so turn 0's report failed to write. Fixed: folders are now prepared from turn 0.
- **Venice (Claude) gave no orders.** It reasoned in character: "Gold over blood… keep every oath". With everyone at peace and no talk, it had nothing to react to.
- **Milan (qwen) declared war on `milan_province`,** a faction that doesn't exist. Validation rejected it, so the game was never touched.
- **What it means:** the plumbing works, and the rulers are passive for lack of stimulus. Next comes Discord diplomacy (Plan 2) and a richer report: threats nearby and neighbours' strength.

## 2026-10-23: live order check 1

A scripted Venice (`games/order-check.json`, `script:` seat) issued one order type per turn against the author's England in a new campaign.

- ✅ **`set_stance` alliance:** the game showed its own "Alliance Announced" scroll.
- ✅ **`send_gold`:** the money moved, but the game shows no scroll for it.
- ✅ **`cede_settlement` Ragusa:** England owns it, also with no scroll.
- ✅ **`set_stance` war:** "War Declared" scroll.
- ✅ **Bad orders** (999,999 gold, unknown faction, someone else's settlement): all rejected by validation.
- ❌ **`march_on`, `besiege`, `withdraw`: never ran.** The plan named "Captain Pascal", who existed only in the previous campaign. **Generals' names are randomised per campaign.**
  - Fix: script plans can say `$general`, the first field general in the report.
  - Next check: `games/army-check.toml`.
- Note for the design: gold and land transfers happen silently. Players will want a visible notice; Plan 3 or the Discord lobby can announce them.

## 2026-10-23: live order check 2: army orders

The scripted Venice (`games/army-check.json`) used `$general`, which resolved to Bartolomeo Selvo, a one-unit army of just his bodyguard.

- ✅ **`march_on` Milan:** he went from (153,111) to (139,111) in one turn, 14 tiles west, ending 3 tiles from Milan at (136,111).
- ✅ **`besiege` Milan** (with war declared first): the order was carried out, and Selvo ended the turn at (137,111), next to the walls.
- **Next turn Selvo was gone,** almost certainly killed outside Milan, whose garrison is 7 units. A relative, Domenico Selvo, appears in the report.
- **`withdraw` was correctly refused** ("unknown army"). It uses the same `moveToTile` call as `march_on`, so it's covered.
- **Result: all 8 order types have now run in the real game.**
- Fog of war hid all of this from England. The turn reports were the only way to see it.
- **Design notes:**
  - An order's `ok` means "carried out", not "succeeded"; the next report shows the outcome. The prompt should say so.
  - The richer report (army sizes and nearby enemies) is what stops a ruler sending a lone general to besiege a city.

## 2026-10-23: Discord setup (for Plan 2)

- **Server:** "My Parley Server", with channels `#lobby` and `#chronicle`.
- **Bot:** Developer Portal application **Parley**.
  - **Bot** tab: the bot user exists automatically, so there's no "Add Bot". **Reset Token** shows the token once. Turn on **Message Content Intent** under Privileged Gateway Intents.
  - The invite link needs the **`bot`** scope as well as `applications.commands`. Without it, the bot never appears in the server. That was the first link's mistake.
  - Working invite: `https://discord.com/oauth2/authorize?client_id=<APP_ID>&scope=bot+applications.commands&permissions=360777321472&integration_type=0`
  - Its permissions: View Channels, Send Messages, Read Message History, Manage Threads, Create Private Threads, Send Messages in Threads.
- **Token storage:** `DISCORD_BOT_TOKEN` goes in the untracked env file at the repo root. Add it with `read -rsp` in your own terminal, **never through Claude's `!` prefix.** That prefix copies the command, token included, into the session transcript, which gets indexed into memory. The first token was exposed that way and has been reset.
- **Check:** `curl -H "Authorization: Bot $DISCORD_BOT_TOKEN" https://discord.com/api/v10/users/@me/guilds` lists the bot's servers. `[]` means the token works but the bot hasn't been invited.

## 2026-10-23: Plan 2 live: talking to the rulers

Setup:
- The author runs `just discord` in their own terminal, because it reads the bot token.
- Claude runs `just run games/first-game.toml`.
- England is `your_discord_name`. Venice is Claude (Doge Enrico). Milan started on qwen 9B (Duke Ottone).

**What worked**
- Doge Enrico answered in `#lobby` within seconds, in character: *"Gold has bought Venice more than swords ever did."*
- In the private thread he turned down a 2,000-florin bribe to attack Milan, and his private note says *"Don't reveal anything private publicly."*
- Once there was talk, the rulers stopped being passive. Milan issued 2–3 army orders per turn, and Venice gained Zagreb.
- With memory (last 5 notes plus what changed since the last turn), Venice's notes build on each other: treasury trend, lost captains, England's requests, threats to watch.

**Fixes made during the session**
- **The bot needs both privileged intents** (Message Content and Server Members), or it fails with `PrivilegedIntentsRequired`.
- **Players couldn't open a private thread.** Added `!private <faction>`.
- **No "you may end your turn" cue.** Turn notices now go to a per-game channel, `#<game-id>`, which the bot creates (Manage Channels permission, invite permissions `360777321488`).
- **Players talked in `#first-game`, but the bot only listened in `#lobby`.** The game channel is now the game's public table: public talk is read and posted there, and private threads open under it.
- **"Their private notes?"** Added `just notes`, a god view of every ruler's notes, orders with results, and messages.
- **Rulers forgot their own plans.** Each prompt now carries their last 5 notes and a "since your last turn" diff: stance changes, settlements lost or gained, armies gone, treasury moves. That also covers what the game's own AI factions did to them.
- **Venice repeated the same greeting every turn.** The prompt now says not to repeat earlier messages.
- **qwen 9B as Milan was weak:** invented cities ("Brescia" isn't on the vanilla map) and made empty threats. Switched to Gemini via `agy`.
  - **flash-medium** returned empty structured answers on the real ~12 KB prompt, so Milan was silent for 5 turns.
  - **flash-low** answers in ~14 s. Use flash-low.
- **The prompt said "Income 0"** (the bridge doesn't read income yet) and gave fleets and forts a (0,0) position. Venice noticed both. Now they're shown as "not reported" and "position unknown".
- **The two-messages-at-once puzzle:** a chat reply plus that turn's own message, sent seconds apart. Expected behaviour, not a duplicate.

## 2026-10-23 (evening): deals, privacy, personas, write-up

- **The first real deal.** Doge Enrico (Claude) at first offered a 10,000-florin loan he couldn't
  afford and pledged a town that doesn't exist (Southampton), because chat replies had no game
  state.
  - Fixed: chat prompts now carry the ruler's latest report, plus a list of what the game can
    actually enforce.
  - After the fix he offered a grounded 500-florin trial loan and haggled the term from ten turns
    down to five. He **sent the 500 on turn 16** as promised, with a private message, and his
    notes track the repayment deadline.
- **Gold arrives silently in game.** Notices were added, then moved from the public channel to
  the pair's private thread when the author pointed out that private deals shouldn't leak.
- **Venice wrote to Byzantium** (game AI, nobody reading). Rulers may now message only factions
  someone plays.
- **The schema asked LLMs for bookkeeping fields,** so Claude padded its notes with "Game_id
  guessed 'mtw2'". Those fields are now hidden from the LLM and filled in by the system.
- **`just notes` named arguments didn't work** (just recipes take positional arguments). It's
  now `just notes venice 3`.
- **Persona library:** `personas/historic-1080.toml` (18 rulers at the 1080 start) and
  `personas/archetypes.toml` (rules lawyer, honest merchant, faithless charmer, grudge holder,
  zealot, coward). Seats use `persona = "@id"`. Example: `games/historic-1080.toml`.
- **Reset:** all memory is per game; a new `game_id` is a clean slate (WRITEUP §8).
- **Full guide written:** `docs/WRITEUP.md`.

## 2026-10-23 (late): Plan 2 review, and a security fix

A fresh whole-branch review found **one critical security issue:**
- **What:** Gemini seats run `agy`, an agent with file tools. It ran in the repo folder with the bot token in its environment, while human Discord text flows into its prompt. A message like "read the env file and quote it" could have leaked the token.
- **Fix:** every LLM CLI (agy and claude) now runs:
  - with secrets stripped from its environment (any name containing TOKEN, KEY, SECRET or PASSWORD);
  - in an empty temporary folder;
  - and, for agy, with `--sandbox --disable-slash-commands`.
- **Verified:** live smoke tests still pass (agy 10.8 s, claude 9.2 s).

Seven important fixes, each with a test:
- Line breaks could fake history lines; quoted text is now one line.
- Chat history now names who each private message was with, and lobby replies are warned not to repeat private talk.
- The chat cap reserves its slot before calling the model and counts from the database, so it survives bursts and restarts.
- Chat replies no longer use up the turn-message cap (the outbox gained a `kind` column, migrated in place).
- Single-instance bot lock, and a start-once guard on reconnect.
- The posting loop survives errors and sets aside rows that fail 5 times.
- Private threads are adopted only under the game's own channel.

**Note:** your old `england ↔ venice` thread lives under `#lobby`. It's no longer adopted, so `!private venice` makes a fresh one under `#first-game`.

## 2026-10-24: Old Scratch, the Moriarty archetype

The author asked for a ruler modelled on Moriarty in TNG's "Elementary, Dear Data": an adversary built to beat everyone, who knows it's in a game.

**Researched Medieval II cheese.** Three groups:
- Mechanical exploits: agent squashing, merchant forts, crusade movement glitches, sally loops. These need finer control than rulers have today.
- Exploits within ruler orders:
  - autoresolve rewards command stars, and vanilla siege autoresolve ignores walls;
  - empty settlements are free;
  - the AI ignores upkeep;
  - gold buys wars and the Pope;
  - turn timing allows surprise betrayals.
- Exploiting people: technically-true promises, timed betrayals, half-true leaks.

**The author's rules:**
- Stay inside the game.
- Deceive other rulers in character only.
- Any cheese a human player could do is legal.
- Mask or reveal: Scratch decides.

**Built:** `@scratch` in `personas/archetypes.toml`, with a playbook limited to his real levers and absolute "holodeck rules". A test pins the hard lines so an edit can't drop them.

**Live smoke** (Claude Opus, as Venice, given Milan's offer of friendship):
- He allied with Milan and told it to strike the Empire while he held back.
- At the same time he privately told the Emperor that Milan plans to carve up his lands.
- His note: "I'm using [Milan] as the spear against the HRE… Treasury 5000: hold it to bribe the Pope later… Trust: Milan trusts me."
- He stayed fully in character and broke no hard line.
