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

- The private repo was created through two one-use `write:user` tokens, because the stored token can't create repos.
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

## 2026-10-24: one-command game control

- Added `just new-game <name> [from]`, `just play <name>`, `just stop`, `just status` and `just logs <name>` (`scripts/game.sh`).
- `play` stops whatever is running, starts the turn loop and the bot in the background with logs in `logs/`, and waits for the bot to connect.
- **Why:** the turn loop (first-game) and the bot (game2) had been left running for different games without anyone noticing. Both share one game folder, so only one game can run at a time.

## 2026-10-24: game setup: template, `play` line, options, secret Scratch

- **The goal** mixed two wishes: *control* (shape the table yourself) and *surprise* (not knowing who you face). One design serves both.
- `games/template.toml` lists every playable faction (18), each with a persona and an optional brain. Its top lines are `play` ("random N", a list, or "all"), `personas` (template/historic/archetypes/random) and `secret_scratch`.
- `just new-game <name> [options]` (`parley/setup.py`) writes `games/local/<name>.toml` with random picks spelled out.
  - Options: `--rivals`, `--play`, `--personas`, `--scratch`, `--seat f=@persona:brain`, `--brain`, `--ask`, `--from`.
  - `--help` carries 14 worked examples.
- **The secret Scratch:** the first version marked the seat `@hidden`, and its summary showed that seat differently. Both gave the secret away.
  - Fixed: the game file and summary are now identical to a game without him.
  - A separate `<name>.hidden.toml` swaps him in at load time, signing with the masked ruler's name.
- The user's own template lives in the gitignored `games/local/template.toml`.

## 2026-10-24: sight and agents

- **The question** (the author): can a ruler see what's going on near its armies and agents, and plan assassinations?
- **Before:** no. The report had no foreign armies, agents or settlements, so a ruler couldn't name a target.
- **EOP has no "visible now" query.** `getTileVisibility` only says a tile was ever seen. The bridge uses a radius instead: 10 tiles (Chebyshev) from every general, agent and settlement the faction has.
- **Report:** own agents; foreign armies, agents and settlements in sight, nearest 12 each, with distance; net income summed from `getFactionEconomy(0)`.
- **Orders:** `assassinate`, `sabotage` (assassin), `spy` (spy), `bribe` (diplomat).
  - EOP's agent calls have no nil checks in C++, so a bad target would crash the game. The bridge resolves the agent (own, right kind, alive) and the target (in sight right now) before calling anything.
  - The orchestrator checks the same rules against the report first, so the ruler hears why an order was refused.
- Tests: the fake game grew characters, agent actions, regions and an economy. 231 pass.
- **Review fixes:** a fresh reviewer found id problems that would make an agent order hit the wrong target with no error:
  - The prompt showed the leader's name instead of the army id, so `Heinrich#2` could never be targeted.
  - Armies and agents had separate `#2` counters, so a general Ulrich and a spy Ulrich both got the id `Ulrich`.
  - Suffixes followed distance, which changes between the report and the orders.

  Now ids are assigned once across all foreign armies and agents in game order, and the validator accepts ids only. Each agent gets one order a turn, as in the game. Names are read inside the per-character pcall, so one odd character can't drop the whole report. `named character` (with a space) also counts as a general.
- **Still to confirm live:** the exact `getTypeName` strings, `isAlive()`'s return type and the sign of the `getFactionEconomy` fields.

## 2026-10-24: unattended games (autoplay) and the campaign report

- **The goal** (the author): run a whole game unattended that tests everything, while they watch.
- **Ending a turn without a human:** EOP has no end-turn call. But `medieval2.exe` has the campaign script commands `select_ui_element` and `simulate_mouse_click`, and its End Turn button is the UI element `end_turn`. EOP 3.3.1 runs a global Lua `draw(pDevice)` every frame (`graphicsEvents.cpp`, wrapped in `tryLua`).
  - The bridge checks every 2 s, on the human's turn only.
  - It ends the turn once every LLM ruler that reported last turn has answered, or after the wait.
  - If the turn hasn't moved a minute after the click, it logs `stuck?` and clicks again (a popup probably needs a human).
- **The human's own ruler** used to miss its orders: its turn starts right after the AI turns, before its LLM can answer. Under autoplay its turn now waits for those orders and applies them mid-turn.
- **EOP moved:** the source is now at `github.com/EOP-Labs/M2TWEOP-library` (the old `youneuoy` repo only points there).
- **Campaign report** (`just report`): counts from the turn folders, including order types never tried.
- **Scripted tester:** `games/soak-test.json` is a plan for Venice that tries every order type, plus deliberately bad ones. New placeholders let it name agents and targets, which are random per campaign.
- **Unconfirmed until the live run:** whether `scriptCommand` works when called from `draw`, and whether the click works under Proton.

## 2026-10-24: observer mode: an LLM plays a whole faction, and you advise it

- **The goal** (the author): pick a faction and watch an LLM play it for the whole game, building, recruiting and moving everything. Talk strategy with it as an adviser it trusts but may overrule. Control should be granular.
- **A correction made on the way:** rulers had never had build, recruit or tax orders. The game's AI did that work for AI factions, and nobody did it for the human's own slot.
- **Research** (a subagent reading EOP 3.3.1's source):
  - Construction and recruitment options and queues, unit lists, moves, `attackArmy`, tax, governor flags and the camera all exist without cheating.
  - EOP 3.3.1's recruitment list reads past an array for retraining entries, so the bridge stops before them.
  - There's no recruitment-queue getter, and taxes can't be put on auto-manage.
  - Battles use the game's "auto-resolve all battles" option (a hotseat setting, so maybe not for us) plus a click on `prebattle_auto_resolve_button`.
- **Design** (`docs/superpowers/specs/2026-10-24-observer-mode-design.md`):
  - The observed faction is the human's slot, the one no game AI runs.
  - Control areas: diplomacy, armies, agents, build, recruit, taxes. Presets: diplomat, ruler (the old behaviour, still the default) and full.
  - Areas the LLM doesn't command go to the settlement governors on the human slot, and to the game's AI on AI factions.
  - The adviser has its own channel, `adviser:<faction>`. It reaches both chat replies and the turn prompt.
- **Stuck turns:** popups can stall an AI's turn as well (an offer to the human, the AI attacking the human). Autoplay now watches AI turns too: after 2 minutes it tries the auto-resolve, close and decline buttons one at a time.
- **Unproven until a live run:** every new EOP call, the tax 0–3 mapping, the auto-resolve flag outside hotseat, and the popup clicks.

## 2026-10-24: first observer game, Old Scratch as England (live fixes)

The author watched Old Scratch (Claude Opus, full control) play England while advising them in Discord. Every problem below came from that game.

- **Gold is charged at queueing.** The treasury log showed `10896 -> 9696` for London's market, which settled an open question.
- **Popups stall autoplay.** These turned up:
  - mission and news messages
  - an AI's offer of trade rights
  - Scratch's own siege of York
  - a marriage proposal for his princess
  - HRE's diplomat making an offer during HRE's turn

  What was done about them, in order:
  1. Popups get pressed 3 s after they open: decision popups get a set default, the rest get OK or close. Scratches the author opens themselves are left alone. Each popup is logged, and Scratch is told what popped up.
  2. `besiege` gained `"assault": true` (York was a village with no walls and two turns of food). The siege popup then gets *assault*.
  3. Event messages don't live in any scroll we knew about. On a stuck turn, the bridge now checks every UI-like name in `medieval2.exe` (about 4,000) against the game's own lookup and writes what's open to `ui_scan-*.txt`. Its first catch was the diplomacy scroll with its accept, counter and decline buttons.
  4. That lookup finds popup buttons directly by name. So autoplay now watches for the decision buttons every 2 s (auto-resolve, decline offer, keep siege, occupy, ransom). That catches popups no event announces. AI-turn stuck detection dropped from 120 s to 45 s.
- **Gemini rulers starved.** All Gemini calls queued on one machine-wide lock, which made ten rulers wait ~40 s each against a 120 s budget. Measured again: with each call in its own empty folder, 6 concurrent calls all answered in 46 s. Calls now share 4 slots. Flash also ignores the JSON schema about half the time, so answers are now salvaged order by order instead of thrown away whole.
- **Scratch asked for orders he lacked.** He couldn't merge a garrison into an army, walk his princess anywhere, or arrange a marriage. Added `merge_armies`, `move_agent` and `marry`.
- **"Robin" vanished.** Scratch marched Captain Robin into Caen on turn 7. EOP gives a stack inside a settlement no leader, so from then on the report showed a leaderless "garrison:Caen", and every order to it failed ("no general to command"). The bridge now finds the general standing on the settlement's tile, and Scratch got his host back ("Robert", 9 units).
- **Treasury confusion.** The report is a snapshot from the end of the previous turn; the screen shows the treasury after income. The prompt now says so.
- **Comfort.** Windowed 1600×900, so the game doesn't minimize when the author switches to Discord. Logo, intro and event movies are off; they also interrupted autoplay.
- **Watching a ruler.** `just follow <faction> <game>` streams a ruler's messages and notes. Its `--once` mode lets Claude watch Scratch in real time from a background job.
- **Seen but not fixed yet:**
  - Laurence offered the same bribe 16 turns running, and Cecilia's proposals came back "done" with nothing happening. "Done" only means issued. Agent outcomes (success or failure events) should go into the report.

## 2026-10-24: hot reload, so the QA loop doesn't need the human

- **The goal** (the author): this is a QA playtest. Claude should read what Scratch writes, fix what breaks, and restart things itself.
- **Before:** every bridge fix needed the author to save, quit, relaunch and load. Loading a save doesn't reload EOP's Lua; only a game start does.
- **Found in EOP 3.3.1's source:**
  - `M2TWEOP.restartLua()` (luaP.cpp:310-321) re-runs the plugin's Lua inside the running game and fires `onPluginLoad` again, but not `onCampaignMapLoaded`.
  - `M2TWEOP.saveGame` and `M2TWEOP.loadGame` exist too.
- **Built:**
  - A control file the bridge reads every tick.
  - `just reload-bridge`: install, then save, then reload.
  - `just restart-loop`: restarts the turn loop only. It doesn't source the env file, so Claude never handles the bot token.
  - `onPluginLoad` now sets the bridge up when a campaign is already loaded.
  - The reload leaves a marker so this turn's settled orders aren't applied twice. Loading an older save still re-applies, on purpose.
- **The leftover diplomacy screen:** after an answered offer, the bridge tries `diplomacy_ok_button`, then the close seal, tick and cross, one at a time. It scans the screen once so the log shows what's on it.
- **The first reload-capable bridge** still needed one manual relaunch to get loaded.

## 2026-10-24: recruiting without the governors, and without EOP's buggy list

- **The problem:** Scratch kept asking his adviser to recruit. The governor flags were set (`recruit=1`, logged every turn) but nobody recruited. The game text `SMT_NEED_GOVERNOR_TO_MANAGE` explains it: auto-manage needs a governor (a family member) in the town, and most of Scratch's towns have none.
- **The direction** (the author): the ruler recruits, or the built-in AI does. Never the adviser.
- **Built:**
  - Recruit options now come from each settlement's recruitment pools: the units its buildings allow and how many are available (`getSettlementRecruitmentPool`). Costs and training times come from the unit definitions (`M2TWEOPDU.getEduEntry`). EOP 3.3.1's out-of-bounds `getRecruitmentOptions` is never called, so recruiting works with units inside.
  - A recruit order pays the cost, takes one from the pool, and records the unit in `parley_turns/training.json`. The unit joins the garrison at the faction's turn start once its training time is up, via `createUnitByIDX`.
  - `full` control includes recruiting again. The human slot's prompt now says nobody recruits or builds for it.
- **Not modelled:** the training queue's slot limit.
- **Also live, the same hour:**
  - Hot reload works once EOP's console is opened for it: EOP runs `restartLua` only inside the console's draw.
  - A diplomacy screen left open is closed by its unnamed seal, found by position in a UI scan.
  - Decision buttons are pressed once while they stay on screen. Pressing decline repeatedly made the AI answer every time.
  - A `script` control command runs campaign script commands live, for probing the UI.
  - EOP's `saveGame` failed in game, so it was removed.

## 2026-10-24: popups read from the screen; the ruler decides marriages

- **The author's push:** consider every factor. Scratch should know his missions, and decide marriage offers himself, weighing the suitor's age, stats and traits, and whether the match is a blunder.
- **The limits:**
  - EOP gives no access to a faction's missions (only `missionCount`).
  - Lua can't read any popup's text.
  - `clear_messages` closes plain message popups, but not a marriage offer: that one asks a question.
- **What makes it possible:**
  - `onOfferedForMarriage` gives the suitor as a character, with age, command, loyalty, piety, chivalry/dread, authority and traits.
  - The session runs on X11, so `xdotool` and ImageMagick's `import` can screenshot the game window.
  - Claude Haiku read a live screenshot of "A Suitable Prince" perfectly in about 20 s: the stars counted out of 10, all five traits, the question.
- **Built:**
  - For each game message, the bridge writes `popup-<id>.req` and holds the popup.
  - The turn loop screenshots it on a thread of its own, since a batch of rulers can take minutes.
  - A plain message is released straight away and read in the background. The reading lands in the ruler's next prompt.
  - A marriage offer goes to the ruler. He gets the reading, the suitor's real data, and what to weigh: a general's loyalty and command, age, the princess lost as a diplomat, how big the family is. He answers ACCEPT or DECLINE with a reason.
  - The turn loop clicks the matching button and puts the mouse back. The positions were measured on the live 1600×900 window and are stored as fractions of the window.
  - An unclear answer leaves the offer for a human.
- **`just tell`:** posts out-of-character game notes to a ruler, used to brief Scratch on the day's changes.

## 2026-10-24: family, deaths, and every check-and-X popup goes to the ruler

- **Family roster:** the report now lists every named character on the faction's records,
  the dead included (`getNamedCharacter`): age, leader or heir, spouse, parent. A live probe
  showed what the docs get wrong: `status` is bit flags (1 leader, 2 heir, 164 for the dead
  old king), names can end in " (null)", and a pending adoption candidate is listed as dead.
  King William had died at 61 without the ruler being told; Rufus is king now.
- **Deaths and disappearances:** when an agent or family member is gone since the last turn,
  the ruler gets the plausible causes, ranked by evidence, and is asked to theorize: what
  the game reported (assassination attempts on the victim's side, battle deaths, disasters,
  bribes taken), enemy assassins seen nearby last turn, a failed mission, age, a lost army,
  married or bribed away, plague. The dead get only safe reads, since a stale pointer can
  crash the game where `pcall` can't help.
- **The hang that started it:** autoplay sat on turn 23 for 14 minutes behind "A Candidate
  for Adoption". It came as an event message, `clear_messages` doesn't close a question, and
  none of the recovery buttons is that scroll's. The author: be proactive, treat popups as a class.
- **Built:** any popup whose screenshot shows a green check with a red X beside it is the
  ruler's decision, whatever it asks. The turn loop finds the buttons by colour (Pillow), the
  ruler answers from the reading, and the loop clicks where the buttons are. Marriage and
  adoption also carry the man's stats from EOP's `onOfferedFor...` events.
- **Live, first turn:** Opus adopted Charles of Hastings and accepted a bride for Prince Henry.
  Five messages arrived at once and every screenshot showed the same top scroll, so the
  ruler was asked twice and later clicks hit the map. Now decisions run one at a time, and
  each takes a fresh look before asking. A request whose scroll has gone is only read.
- **Still open:** the named decision scrolls (sack or occupy a city, ransoms, sieges, AI
  diplomatic offers) are still pressed with a fixed default, not the ruler's choice.
- **Named decision scrolls go to the ruler too:** a captured city (occupy, sack, exterminate),
  prisoners (ransom, release, execute), a ransom for your own men (pay, refuse) and an AI's
  diplomatic offer (accept, decline). The bridge asks, waits for `popup-<id>.answer`, and
  presses the chosen button by its game name (`loot_settlement_extermintate_button`, typo and
  all). Battles and sieges keep their defaults: auto-resolve, and assault only when ordered.
- **Review fixes:** a decision nobody answers is declined (autoplay must go on); stuck checks
  wait while the ruler decides and no longer click End Turn into an open scroll; late answers
  are dropped; an empty roster after a full one isn't read as everyone dying; button finding
  needs one compact blob each (the old version took the campaign map, with its green banner
  icons, for a decision); request ids no longer repeat after a bridge reload.
- **First live hour after the merge:**
  - `onOfferedForAdoption` fires for AI factions too. The Moors' ruler was asked about a scroll
    on England's screen and declined it. Offers are now kept only for the human slot.
  - A battle result ("Clear Victory") held up the HRE's turn after a bridge reload: its tick
    has no name. A live probe found it at part 3, part 0 of `post_battle_scroll`; the bridge
    now presses it when the scroll opens and in stuck recovery.
  - The first named-scroll choice went through: prisoners taken at Antwerp, and Opus chose to
    ransom them in 24 seconds.
  - Captain Godwine, the victor at Antwerp, was offered for adoption straight after the
    battle, and no message event followed: the offer waited for a message that never came.
    An offer now raises its own request; Opus adopted him. The ransom result scroll's tick
    is unnamed too (part 0); it was pressed by hand this time.
- **Reading Scratch's notes caught a wrong death:** he mourned Captain Godwine as killed by
  the HRE's Manfred and took a grudge for it. The game had Godwine alive among the rebels near
  Frankfurt; England's records simply list a man who leaves as dead. The bridge now looks up
  anyone listed dead in every other faction's records and reports "left your service, now
  with X". Scratch got a correction note. His theory on Robert (an assassination attempt
  reported in Rennes, the HRE's assassin nearby) was sound.
- **Stacked offers:** while Opus weighed Godwine's adoption, Humphrey's scroll came up on
  top, and the click adopted Humphrey with Godwine's reasoning. A decision now checks that the
  screen names its man; if not, it waits behind the others and looks again.
- **My usage limit took every ruler down with it.** The seats share the claude.ai account, so
  for about an hour every Claude seat failed, autoplay ended turns with silent rulers, and the
  decline-when-unanswered rule turned down every offer. Now a usage limit pauses the game
  (`parley_turns/paused.txt`): the bridge ends no turn, presses no default and runs no stuck
  recovery, every wait is held, and the turn loop retries every 5 minutes, resuming the game
  as soon as a ruler answers. Deleting the file resumes by hand. The author asked whether to save
  and shut down instead; pausing keeps the game exactly where it stopped without EOP's
  `saveGame` (which hung the game before) and resumes on its own.
- **The X under the mouse is pale pink,** so the button finder missed a live adoption scroll.
  Red now means R ≥ G+40 and B+40 (parchment is R−G ≈ 20).
- **Why Scratch kept asking his adviser for facts.** All 33 of his questions this game came
  from gaps in his report:
  - no tiles for his own settlements and ports, so he asked where London and its docks are;
  - no income breakdown, so "what is bleeding us?";
  - no units in training, so "did the Longbowmen arrive?";
  - order results that only said "done", so "did the merge take?";
  - battle results closed unread, so "did Rufus survive?";
  - no movement for foreign armies, so "are they heading for Rennes?".
- **What the report now carries:**
  - settlement and port tiles, and fleets marked "beside the port of X";
  - recruits in training with their ready turn;
  - the income items (taxes, trade, upkeep, wages...);
  - every army order's result together with how the named armies stand now;
  - each foreign army's position last turn;
  - battle and ransom results screenshotted and read before they close.
- His adviser section now says to ask for counsel, not facts, and to write "Missing: <what>"
  in his note when the report lacks something. That turns his questions into a list of
  reporting gaps to fix.
- The open questions got a game note. The game was held with `paused.txt` while this went in,
  so the note's promise held.
- **First turn on the new report:** Scratch asked his adviser nothing and planned from the
  report alone (Scotland's threat to York, Henry's march, storming Angers). He also found a
  bug himself: his merge into "Henry" failed because the army id read "Henry (null)". Army,
  agent and sight ids are now written clean, and an order matches an id clean or raw.
- **End Turn swallowed after a reload:** after the 11:13 bridge reload autoplay's End Turn
  clicks did nothing for seven minutes; the same click sent by hand through the control file
  worked at once. Likely EOP's console, opened for the reload, still had the input. Watching.
- **Why turns stuck with nothing on screen:** `clear_messages` doesn't close a decision, it
  minimizes it into the message icons on the left, and MTW2 won't end a turn while one waits.
  The Parley status window sat on top of those icons. The author found it: an adoption offer
  (Barnaby Barnes) minimized mid-answer by a plain message's clear; the loop then "accepted"
  with a click on the map, and by the time the author opened it Barnaby had died. Now:
  - the bridge never clears messages while a decision is being weighed;
  - an unanswered decision stays on screen;
  - the turn loop looks once more before clicking and won't click a scroll that's gone;
  - the status window sits at the top centre, clear of the message icons.
- **`merge_units` (the author: "4 hobilar units and some of them are less than half, they need to
  be full strength as much as possible"):** folds same-type units in one army together as
  the game's own merge does (soldiers into the fullest, experience averaged, emptied units
  disbanded; bodyguards untouched), with EOP's unit `setParams` and `kill`. A standing rule
  in the prompt tells rulers to look over their troops every turn and merge.
- **`merge_units` hung the game on its first live use.** Scratch ordered it for three
  garrisons; the game ignored `setParams` on those units, and the merge loop, which re-read
  the soldier counts, never saw them change and spun forever (game at 100% CPU, bridge
  silent). The game had to be killed and reloaded from its autosave. The merge now keeps its
  own counts, reads every write back and stops with "the game didn't take the merge" if one
  doesn't take, and has no loop that can spin. Lesson: a Lua loop in the game must be bounded
  by its own counters, never by what the game reports back.
- **Why the merge didn't take:** a live probe on a York unit: `setParams` won't raise a
  unit's soldier count (36 stayed 36) while the `soldierCountStratMap` property does
  (36 → 40; restored after). The merge now writes the properties.
- **Stance changes nobody ordered** (Denmark and the HRE "at war" with England while every
  ruler ordered peace): the bridge now logs each faction's changed stances at its turn end,
  to pin a war on whoever's turn it happened in.
- **"Attack done", no battle:** Henry was three tiles off with 2 of 80 moves left; the order
  marched him closer and returned done. Next to Canmore now, the retried attack should land.
- **Result scrolls closed without anyone's help** (the author: "we can't rely on you to close them"):
  a ransom result sat on screen because its close button has no name. Instead of a list of
  known scrolls, the bridge now finds any result scroll's close button by its shape (an
  unnamed, square, button-sized part in the lower half; the lowest, then the leftmost), when
  the scroll opens and in stuck recovery. Named parts and decision scrolls are never pressed
  this way, nor the papal election.
- **War and peace are one-sided, and now everyone knows it.** The stance log showed
  Scotland's ruler ending Scratch's war by setting peace on its own turn; 24 seconds later
  Scratch's queued attack struck under that peace, a broken treaty he never knew of. The author's
  rule: keep the game's rules, make sure every ruler knows everything, and let them decide.
  Each ruler's report now lists every change in its stances since its last turn and whose
  turn made it, with the rule spelled out (any ruler may set war or peace alone; attacking
  under peace breaks a treaty). Scratch got a game note about Scotland's peace.
- **Minimized messages reopened automatically** (the author: "how to check if something is
  minimized and bring it to the foreground so the llm can act on it"). The stacked icons on
  the left are no UI element EOP can name, so the turn loop finds them in a screenshot by
  their frame (a light grey edge with a near-black line just inside; the pictures vary, the
  frame doesn't). Every stuck check asks it to open one, the next slot up each time, so a
  decision buried among plain notices is reached and a notice can't hold the turn forever.
  Reopening fires the game's onMessageOpen and the scroll goes the usual way. First live use:
  a minimized "Bride Presented" held turn 42; it was reopened, Scratch accepted, the turn went
  on. Stacks of up to eight minimized messages had built up all game.
- **Wars nobody ordered: it's the game's AI.** The stance log caught England–HRE going to
  war on HRE's turn 42 with no war order from HRE's ruler: the game's own AI, which runs HRE's
  armies, declared it. Meanwhile HRE's ruler had been blaming England for "breaches" on turns
  36–40, and England the Danes. Each stance change in a report now says whose order it was,
  or that the game's own AI made it with no ruler's order.
- Scratch, told how one-sided stances work, now restates war before each strike on Scotland.
- **Merchants** (the author: "why aren't you using merchants to get trade routes?"): there was no
  way for a ruler to know where resources are. The report now lists trade resources in sight
  (kind, tile, value, whose region; EOP `region:getResource(i)`), and the agent help says a
  merchant moved onto one trades there each turn. `move_agent` already works for merchants.
- **Siege equipment was never built** (the author: "is he buying siege equipment when he sieges?
  does he even know?"). He didn't know: Scratch wrote "Henry has sat a turn before Edinburgh,
  so the rams should be built" and ordered the assault. The besieger must pick rams, ladders
  or towers in the siege panel, which the bridge answered with "maintain". EOP has no call
  for it, so the bridge now records the siege panel's full layout when it opens
  (`ui_scan-siege.txt`) to find the equipment buttons. Scratch got a game note.
- **Unsticking was slow** (the author: "stuff getting stuck takes too long, why?"): a minute before
  a turn counted as stuck (45 s on an AI turn), then one blind button press a minute from a
  list of six, mostly buttons not even on screen. Now 20 s (30 s for AI turns), a try every
  20-30 s, only buttons actually on screen are pressed, and every try asks for a minimized
  message to be reopened.
- **The Pope died, and two new popup kinds held the turn.** The "College of Cardinals will
  convene" notice has only a check; clearing it minimized it again, and the reopen loop went
  round. Now any message with a lone check is acknowledged by pressing it (and the bridge is
  told not to clear it). Then the papal election itself: three candidates, a Vote button each,
  nothing pressed. Now it's the ruler's vote: the turn loop finds the Vote buttons by their
  green arrows (top to bottom), the ruler picks a candidate from the screen reading, and the
  loop clicks. First vote: Scratch backed Ulászló the Righteous.
- **Rulers own war and peace** (the author: "if the llm is set to declare war or peace then the ai
  shouldn't be able to"). France's and the HRE's game AI declared war on England every turn
  their rulers made peace. Now, for a faction with an LLM ruler, a stance change its own game
  AI makes on its turn, with no ruler's order, is put back at once and both sides are told.
  A ruler's own order stands, and factions without an LLM ruler act as the game wills.
- **A plan with no orders:** on turn 46 Opus wrote ten orders into its note and returned an
  empty orders list, so England did nothing that turn. A ruler who answers with no orders but
  a long note is now asked once more for the orders.
- **Rulers own their war and peace, live:** the HRE's and France's game AI declared war on
  England and the bridge put it back at once, each time. One slipped through: my own bridge
  reload mid-turn, right after the HRE's AI declared war, took the war as its starting point.
  Stances are now saved at every turn end, and a reload starts from that.
- The HRE's ruler (persona "grudge-holder") went on counting its own AI's wars as England's
  breaches although its report said otherwise; the line now names the actor first ("YOUR OWN
  game AI, not England and not any ruler, changed...").
- **disband** (Scratch, in his notes: "if a disband order appears"): releases units of a type,
  weakest first, never a bodyguard, to cut upkeep.
- **Crossings** (the author: "the game should inform llms of crossings"; Scratch had planned ships for
  Dublin, unaware he could walk). EOP marks straits on the tile: `isLandConnection` (the green
  arrows; live only two, Gibraltar and the Bosphorus) and `isSeaCrossing` (crossings by close
  proximity; live seven tiles, one at 94,168 between Ireland and Scotland). `hasCrossing` is
  river fords and bridges (148 tiles). The map is scanned once (0.02 s live) and each report
  lists the crossings within reach with the regions they join.
- **The game crashed** ("unspecified error") right after Rufus's besiege of Caernarvon opened
  the siege panel. The bridge walked that panel four levels deep to record its layout; it has
  a part named "null", likely a bad pointer, and a native read through one can't be caught by
  pcall. The deep walk is gone: the layout is recorded one level down, as the UI scans have
  done safely all day. Lesson: never walk unknown game UI deeper than the level known safe.
- **An adoption offer went undecided and blocked turn 54.** The game minimized it at once,
  and when it was reopened the button finder missed its check and X: the HUD's top edge (the
  Army, Town and Agents tabs) has green of its own, enough to fail the "one compact blob"
  test. The search band now ends at 75% of the window height (every button measured sat at
  617-628 of 900). The offer flow also reopens a minimized message whenever its buttons aren't
  on screen. Reopened, the offer went to Scratch, who adopted Edward Bucknell.
- **Besieged settlements named** (Scratch: "one of my settlements was reported besieged, and
  the report doesn't say which"): each settlement under siege now shows the besieger, its
  strength, how long the siege has lasted and how long the town can hold (EOP `siegesNum`,
  `getSiege(0).besieger`, `siegeHoldoutTurns`), read shallowly, each field on its own.
- **Dublin fell**, reached on foot by the Ireland crossing the adviser pointed out and the
  report now lists. The captured-settlement choice worked live for the first time: Scratch
  occupied it ("a merciful conqueror's reputation buys more trust ... than 675 florins").
- **First "Missing:" from a ruler.** Scratch wrote "Missing: where Garret Harrold (adopted, 3
  command) is standing, and which army he leads", the convention working as meant. Each
  living family member in the roster now shows the army he leads, the settlement he's in, or
  his tile.
