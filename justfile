# List recipes
default:
    @just --list

# Rebuild parley/data/units.json from the vanilla unit file (read-only)
unit-table:
    uv run python scripts/unit_table.py

# Install dependencies
setup:
    uv sync

# Run the test suite
test *args:
    uv run pytest -q {{args}}

# Regenerate docs/EOP-COVERAGE.md: what EOP's Lua API exposes vs what the bridge uses (needs the EOP source)
eop-coverage:
    python3 scripts/eop_coverage.py --md docs/EOP-COVERAGE.md

# Answer LLM-faction turns as the game writes them
run game="games/example.toml":
    uv run python -m parley run {{game}}

# Run the Discord table bot (needs DISCORD_BOT_TOKEN in the untracked env file)
discord game="games/first-game.toml":
    set -a; [ -f .env ] && . ./.env; set +a; uv run python -m parley discord {{game}}

# Restart only the turn loop for <name> (picks up new Python code; the bot keeps running)
restart-loop name:
    bash scripts/game.sh restart-loop {{name}}

# Run one Lua line in the running game and print what it returns (helpers: fac, char, at)
[positional-arguments]
lua line timeout="10":
    bash scripts/probe.sh "$@"

# Install the bridge, then reload it inside the running game (no relaunch needed)
reload-bridge:
    bash scripts/game.sh reload-bridge

# After a crash: stop what's left of the game, relaunch it through Steam on the newest save, no clicks (--save <name>.sav, --clicks)
relaunch-game *args:
    bash scripts/relaunch_game.sh "$@"

# Watch the game and relaunch it after a crash, as the user unit parley-crash-watch (log: logs/crash-watch.log)
crash-watch:
    bash scripts/crash_watch_unit.sh start

# Crash reports crash-watch wrote before relaunching (runs/crashes/), newest first, with their last bridge line
crashes n="10":
    python3 scripts/crash_report.py list -n {{n}}

# Stop crash-watch (the unit, and any watch started the old way)
crash-watch-stop:
    bash scripts/crash_watch_unit.sh stop

# Keep the monitors on while the game runs (screens off slow it to a crawl); `just play` starts it (log: logs/screen-awake.log)
screen-awake:
    bash scripts/screen_awake.sh start

# Stop keeping the monitors on
screen-awake-stop:
    bash scripts/screen_awake.sh stop

# Watch a campaign; exits with one line on a stall, stuck turn, stopped loop or lost faction (docs/NOTIFY-CLAUDE.md)
watch game_id faction="england":
    bash scripts/campaign_watch.sh {{game_id}} {{faction}}

# Post a game note to a ruler in games/local/<name>.toml (its adviser thread and next turn prompt)
tell faction name text:
    uv run python -m parley tell games/local/{{name}}.toml {{faction}} {{quote(text)}}

# Follow one ruler live in games/local/<name>.toml: its messages and turn notes (Ctrl-C stops)
follow faction name:
    uv run python -m parley follow games/local/{{name}}.toml {{faction}}

# Review an LLM ruler's play every N turns and explain mistakes
play-review name faction every="5":
    uv run python -m parley.play_review games/local/{{name}}.toml {{faction}} --every {{every}}

# Campaign report for games/local/<name>.toml: who answered, order coverage, why orders failed
report name:
    uv run python -m parley report games/local/{{name}}.toml

# Turn audit for games/local/<name>.toml: bridge bugs, ruler mistakes, unused options (game_id= for an archived run)
audit name game_id="":
    uv run python -m parley audit games/local/{{name}}.toml {{ if game_id != "" { "--game-id " + game_id } else { "" } }}

# Rulers' lessons from past games (kept beside games/local/<name>.toml's turn folders), with ids
lessons name:
    uv run python -m parley.lessons games/local/{{name}}.toml

# Veto a lesson by id: it leaves every prompt and is never learned again
lessons-veto name id:
    uv run python -m parley.lessons games/local/{{name}}.toml veto {{id}}

# Decision log for games/local/<name>.toml: rungs, kinds, actors and the latest decisions
decisions name last="20":
    uv run python -m parley.decisions_report games/local/{{name}}.toml --last {{last}}

# God view: rulers' private notes, orders and messages (e.g. just notes venice 3)
notes faction="" last="" game="games/first-game.toml":
    uv run python -m parley notes {{game}} {{ if faction != "" { "--faction " + faction } else { "" } }} {{ if last != "" { "--last " + last } else { "" } }}

# Simulated game for the example config (no Medieval II needed)
fake-game turns="3":
    uv run python tools/fake_game.py --root runs/turns --game example --factions venice,milan --turns {{turns}}

# Make a new game from your template; just new-game --help shows every option with examples
new-game *args:
    bash scripts/game.sh new-game {{args}}

# Stop anything running, then start the turn loop and the Discord bot for <name>
play name:
    bash scripts/game.sh play {{name}}

# Stop the turn loop and the Discord bot
stop:
    bash scripts/game.sh stop

# What's running, and for which game
status:
    bash scripts/game.sh status

# Latest output from the turn loop and the bot for <name>
logs name:
    bash scripts/game.sh logs {{name}}

# Install the pinned M2EX release into the game folder (backs up what it replaces)
install-m2ex:
    bash scripts/install_m2ex.sh

# Install M2TWEOP as mods/parley (vanilla game and M2EX untouched)
install-eop:
    bash scripts/install_eop.sh

# Install the Lua probe where EOP and M2EX autoload scripts
probe:
    bash scripts/install_probe.sh

# Install the game-side bridge into mods/parley (replaces the probe)
install-bridge:
    bash scripts/install_bridge.sh

# Ask one real seat for orders on the fixture report (e.g. claude:sonnet)
seat-smoke spec timeout="120":
    uv run python -m parley.smoke {{spec}} {{timeout}}

# Replay a played turn's prompt to seats and compare (e.g. just seat-bench <turn dir> 240 agy:gemini-4-argon-medium claude:sonnet)
seat-bench dir timeout +specs:
    uv run python -m parley.bench {{quote(dir)}} {{timeout}} {{specs}}

# Evaluate seat specs across recorded turn scenarios
ruler-eval *args:
    uv run python -m parley.ruler_eval {{args}}

# Run a QA bench suite (or 'all') on the fixed bench save, real campaign parked and restored (kind=instant: no-click cases only)
[positional-arguments]
qa suite *args:
    bash scripts/qa.sh run "$@"

# Restore the real campaign from its kept save after a QA run
[positional-arguments]
qa-restore *args:
    bash scripts/qa.sh restore "$@"

# Make the bench save: 'start' then 'record' (new campaign, menu), or 'record --from <sav>' alone (no menu, no clicks)
# (arguments keep their quotes: the game's save path has spaces)
[positional-arguments]
qa-bench-save step *args:
    bash scripts/qa.sh bench-save "$@"

# Summarize newest QA bench reports across suites
qa-summary *args:
    uv run python -m parley.qa.summary {{args}}

# Hold a standing order: the Stop hook keeps the session working until HH:MM (`off` drops it, `show` prints it)
work-until arg="show":
    bash scripts/work_until.sh {{ if arg == "show" { "show" } else if arg == "off" { "off" } else { "set " + arg } }}
