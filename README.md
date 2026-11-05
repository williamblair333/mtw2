# Parley: LLM rulers and Discord diplomacy for Medieval II

Parley lets large language models (LLMs) rule factions in *Medieval II: Total War*. You play one
faction yourself. Claude, Gemini or a local model plays others, and the game's own AI plays the
rest. Everyone talks in a Discord server, in public or in private. A deal is only words. Whether a
ruler keeps it shows up in the game, and the rulers remember who kept faith.

## How it works

Each turn has three steps.

1. **The game reports.** A Lua script inside the game (the *bridge*) writes what each LLM faction
   can see: its towns, armies, agents, money, neighbours and the news of the turn. The script runs
   inside [EOP](https://github.com/EOP-Labs/M2TWEOP-library), a community engine extension that
   lets Lua read and change the game.
2. **The ruler decides.** A Python program sends that report to the faction's LLM. The LLM answers
   with orders (move this army, build that, bribe him) and with messages for Discord.
3. **The game obeys.** The bridge carries out each order through EOP, by the game's own rules:
   cost, movement, buildings, time. An order the game refuses comes back to the ruler with the
   reason.

The bridge knows 27 kinds of order: moving, attacking and besieging; building, repairing,
recruiting and retraining; ships, boarding and landing; tax, gold and diplomacy; and agent
missions (spy, assassinate, sabotage, bribe, marry).

## Status: works, not yet easy

This is a working hobby project, not a finished product. Be ready to read logs.

**What works:**
- Full campaigns with many LLM rulers, on Linux, through Steam's Proton.
- The Discord table: a public channel per game, private threads, replies between turns.
- A test bench of about 100 scripted cases. Each one sets up a situation in the running game,
  gives an order and checks the result. 1591 offline tests also run the real bridge against a
  fake game.

**What doesn't yet:**
- **A few screen clicks are left.** The papal election vote, and family offers (a marriage or
  adoption your faction must accept or decline), still need a mouse click, which our scripts make
  from a screenshot. That only works at one screen size. The rest goes through EOP.
- **Cheap models play poorly.** Strong models play well but cost money. Making a cheap model play
  a competent campaign is open work.
- **Setup takes an afternoon.** There is no one-step installer. The guide below has every step.
- Merchants and priests have no orders yet. Sight is a fixed radius, not the game's fog of war.

## Try it without the game

Two fake rulers play two simulated turns. You need Python 3.13, but no Medieval II, Discord or
LLM:

```sh
pip install uv
uv sync
timeout 30 uv run python -m parley run games/example.toml 2>&1 & sleep 3; uv run python tools/fake_game.py --root runs/turns --game example --factions venice,milan --turns 2; wait
```

The last line shows `milan turn 2: 0 orders, 0 rejected`. That means the whole turn pipeline ran.

## Play it

You need:
- Linux, Steam, and *Total War: MEDIEVAL II – Definitive Edition* (Steam app 4700). The game
  runs as its Windows build under Proton, because the native Linux port can't load mods.
- Python 3.13, [`uv`](https://docs.astral.sh/uv/) and [`just`](https://github.com/casey/just).
- At least one LLM: the `claude` command-line tool, Gemini through `agy`, or a local model through
  Ollama.
- A Discord server you own, if you want the table.

The install steps are in **[the guide, §4](docs/WRITEUP.md#4-installation-on-linux)**. After
that, a game starts like this:

```sh
cp games/template.toml games/local/template.toml   # once; then put your Discord name in it
just new-game game3 --rivals 6     # a game with 6 LLM rivals
just play game3                    # start the turn loop and the Discord bot
just status                        # what's running
just stop                          # stop everything
```

Then start a new Grand Campaign in the game as England. `just --list` shows every command.

## Help wanted

We need people who know EOP, Medieval II's internals, prompt writing for small models, or who
just want to play and report what breaks. See **[CONTRIBUTING.md](CONTRIBUTING.md)**.

## More to read

- [`docs/WRITEUP.md`](docs/WRITEUP.md): the full guide (install, play, configure, troubleshoot).
- [`PRODUCT.md`](PRODUCT.md): what Parley is for and what it won't do.
- [`docs/eop-api-notes.md`](docs/eop-api-notes.md): EOP behaviour we checked against its source.
- [`docs/JOURNAL.md`](docs/JOURNAL.md): the build log, failures included.

## License

GPL-3.0 (see `LICENSE`), the same as [EOP](https://github.com/EOP-Labs/M2TWEOP-library). The
bundled `lua/vendor/json.lua` keeps its MIT license. EOP and M2EX aren't bundled: the installers
download pinned releases from their authors.

*Medieval II: Total War* is a trademark of its owners. This is an unofficial fan project.
