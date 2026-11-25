# Parley: LLM rulers and Discord diplomacy for Medieval II

Parley hands factions in *Medieval II: Total War* to large language models (LLMs): Claude, Gemini
or a model running on your own machine. You play one faction. The LLMs play some others, and the
game's own AI plays the rest. Everyone can talk in a Discord server, in public or in private
threads. A ruler can promise anything there, but only its orders change the game, so you find out
whether it kept its word by watching the campaign map. The rulers remember who kept their
promises to them.

## How a turn works

1. **The game reports.** A Lua script inside the game (we call it the *bridge*) writes what each
   LLM faction knows: its settlements, armies, agents, treasury, neighbours and what happened since
   last turn. It runs inside [EOP](https://github.com/EOP-Labs/M2TWEOP-library), a community
   engine extension that lets Lua read and change the game.
2. **The ruler decides.** A Python program sends that report to the faction's LLM. The LLM
   answers with orders (move this army, build that, bribe that general) and with messages for
   Discord.
3. **The game carries out the orders.** The bridge gives each order to the game through EOP. The
   game's normal rules apply: cost, movement points, building requirements, build time. When an
   order is refused, the ruler gets the reason.

The bridge handles 27 kinds of order: moving, attacking and besieging; building, repairing,
recruiting and retraining; ships, boarding and landing; tax, gold and diplomacy; and agent
missions (spy, assassinate, sabotage, bribe, marry).

## Status: it works, but setup is hard

This is a hobby project, not a finished product. Expect to read log files.

**What works:**
- Full campaigns with several LLM rulers, on Linux, through Steam's Proton. Our test campaign
  passed turn 5,000 and once ran 217 turns in a row with nobody touching it.
- The Discord table: one public channel per game, private threads, replies between turns.
- Game pop-ups (marriage and adoption offers, the papal vote, notices) are answered through EOP,
  with no mouse click. A click from a screenshot is kept only as a fallback.
- Tests: a bench of about 100 scripted cases, each of which sets up a situation in the running
  game, gives an order and checks the result; and 2,123 offline tests, which run the real bridge
  against a fake game.

**What doesn't work yet:**
- **Cheap models play poorly.** Strong models play well but cost money. Making a cheap model run
  a competent campaign is open work.
- **Setup takes an afternoon.** There is no one-step installer. The guide below lists every step;
  we tested it on a fresh Debian 13 machine on 2026-11-25.
- Merchants and priests have no orders yet. What a ruler can see is a fixed radius, not the
  game's fog of war.

## Try it without the game

Two fake rulers play two simulated turns. You need Python 3.13. You don't need Medieval II,
Discord or an LLM:

```sh
pip install uv
uv sync
timeout 30 uv run python -m parley run games/example.toml 2>&1 & sleep 3; uv run python tools/fake_game.py --root runs/turns --game example --factions venice,milan --turns 2; wait
```

On Debian and Ubuntu, `pip install` is blocked outside a virtual environment; install uv with
`curl -LsSf https://astral.sh/uv/install.sh | sh` (or `pipx install uv`) instead.

If the last line reads `milan turn 2: 0 orders, 0 rejected`, every step of a turn ran.

## Play it

You need:
- Linux, Steam, and *Total War: MEDIEVAL II – Definitive Edition* (Steam app 4700). The game
  runs as its Windows version under Proton, because the native Linux version can't load mods.
- Python 3.13, [`uv`](https://docs.astral.sh/uv/) (installed as above) and
  [`just`](https://github.com/casey/just) (`sudo apt install just` on Debian 13 and Ubuntu 24.04+).
- At least one LLM: the `claude` command-line tool, Gemini through `agy`, or a local model through
  Ollama.
- A Discord server you own, if you want the table.

The install steps are in **[the guide, §4](docs/WRITEUP.md#4-installation-on-linux)**. After
that, a game starts like this:

```sh
mkdir -p games/local && cp games/template.toml games/local/template.toml   # once; then put your Discord name in it
just new-game game3 --rivals 6     # a game with 6 LLM rivals
just play game3                    # start the turn loop and the Discord bot
just status                        # what's running
just dashboard game3               # one page: turn, health, crashes, how each ruler is doing
just stop                          # stop everything and pause the campaign (just play resumes)
just resume-at-boot scratch        # resume that campaign at every desktop login (off: just resume-at-boot-off)
```

Then start a new Grand Campaign in the game as England. `just --list` shows every command.

## Help wanted

We need people who know EOP or Medieval II's internals, people who write prompts for small
models, and players who will try it and report what breaks. See
**[CONTRIBUTING.md](CONTRIBUTING.md)**.

## More to read

- [`docs/WRITEUP.md`](docs/WRITEUP.md): the full guide (install, play, settings, troubleshooting).
- [`PRODUCT.md`](PRODUCT.md): what Parley is for and what it won't do.
- [`docs/eop-api-notes.md`](docs/eop-api-notes.md): EOP behaviour we checked against its source.
- [`docs/JOURNAL.md`](docs/JOURNAL.md): the build log, failures included.

## License

GPL-3.0 (see `LICENSE`), the same as [EOP](https://github.com/EOP-Labs/M2TWEOP-library). The
bundled `lua/vendor/json.lua` keeps its MIT license. EOP and M2EX aren't bundled: the installers
download pinned releases from their authors.

*Medieval II: Total War* is a trademark of its owners. This is an unofficial fan project.
