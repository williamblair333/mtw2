# List recipes
default:
    @just --list

# Install dependencies
setup:
    uv sync

# Run the test suite
test *args:
    uv run pytest -q {{args}}

# Answer LLM-faction turns as the game writes them
run game="games/example.toml":
    uv run python -m parley run {{game}}

# Run the Discord table bot (needs DISCORD_BOT_TOKEN in the untracked env file)
discord game="games/first-game.toml":
    set -a; [ -f .env ] && . ./.env; set +a; uv run python -m parley discord {{game}}

# God view: rulers' private notes, orders and messages (e.g. just notes venice 3)
notes faction="" last="" game="games/first-game.toml":
    uv run python -m parley notes {{game}} {{ if faction != "" { "--faction " + faction } else { "" } }} {{ if last != "" { "--last " + last } else { "" } }}

# Simulated game for the example config (no Medieval II needed)
fake-game turns="3":
    uv run python tools/fake_game.py --root runs/turns --game example --factions venice,milan --turns {{turns}}

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
