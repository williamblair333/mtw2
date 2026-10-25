#!/usr/bin/env bash
# Run Parley games with one command each.
#   game.sh new-game <name> [opts]   make games/local/<name>.toml from your template (--help: examples)
#   game.sh play <name>              stop anything running, start turn loop + Discord bot for <name>
#   game.sh stop                     stop the turn loop and the bot
#   game.sh status                   what's running, and for which game
#   game.sh logs <name>              latest output from both
set -uo pipefail

cd "$(dirname "$0")/.."
GAMES_DIR="${PARLEY_GAMES_DIR:-games/local}"
LOGS=logs

die() { echo "$*" >&2; exit 1; }

valid_name() {
    [[ "$1" =~ ^[A-Za-z0-9_-]+$ ]] || die "game name must be letters, digits, dashes or underscores: '$1'"
}

running() {  # running <run|discord> -> "pid config" lines (any config; only $GAMES_DIR's when set for tests)
    local filter="${PARLEY_GAMES_DIR:+$GAMES_DIR/}"
    # only the Python process itself, not the sh/uv wrappers around it (they exit with it)
    pgrep -af "python3? -m parley $1 " | grep -F -- "${filter:- -m parley $1 }" \
        | awk '$2 ~ /python3?$/ {print $1, $NF}'
}

new_game() {  # all options and examples: just new-game --help
    uv run python -m parley new-game "$@"
}

stop_all() {
    local pids
    pids=$( { running run; running discord; } | awk '{print $1}')
    if [ -z "$pids" ]; then echo "nothing running"; return 0; fi
    kill $pids 2>/dev/null
    for _ in $(seq 20); do
        [ -z "$( { running run; running discord; } )" ] && { echo "stopped"; return 0; }
        sleep 0.25
    done
    die "some processes didn't stop: $( { running run; running discord; } )"
}

status() {
    local r d
    r=$(running run); d=$(running discord)
    if [ -n "$r" ]; then echo "turn loop: running ($(echo "$r" | awk '{print $2}'), pid $(echo "$r" | awk '{print $1}'))"
    else echo "turn loop: not running"; fi
    if [ -n "$d" ]; then echo "bot: running ($(echo "$d" | awk '{print $2}'), pid $(echo "$d" | awk '{print $1}'))"
    else echo "bot: not running"; fi
}

play() {
    local name="${1:-}"
    [ -n "$name" ] || die "usage: just play <name>"
    valid_name "$name"
    local cfg="$GAMES_DIR/$name.toml"
    [ -f "$cfg" ] || die "no such game: $cfg (create it with: just new-game $name)"
    stop_all >/dev/null
    mkdir -p "$LOGS"
    setsid nohup uv run python -m parley run "$cfg" >"$LOGS/$name-turns.log" 2>&1 < /dev/null &
    setsid nohup bash -c 'set -a; [ -f .env ] && . ./.env; set +a; exec uv run python -m parley discord "$1"' \
        _ "$cfg" >"$LOGS/$name-discord.log" 2>&1 < /dev/null &
    echo "starting game '$name'..."
    for _ in $(seq 60); do
        if grep -q "connected to" "$LOGS/$name-discord.log" 2>/dev/null; then
            grep "connected to" "$LOGS/$name-discord.log" | tail -1 | sed 's/^.*INFO //'
            echo "turn loop and bot are running for '$name'."
            echo "next: Steam Play -> Run Mod -> Grand Campaign (NEW to start over, or load your save)"
            if grep -q '^\[autoplay\]' "$cfg"; then
                echo "      autoplay: the game ends its own turns; just watch."
            else
                echo "      untick Show CPU Moves; end turns when #$name says all rulers have decided."
            fi
            return 0
        fi
        if [ -z "$(running discord)" ] && [ -s "$LOGS/$name-discord.log" ]; then
            echo "the bot stopped:" >&2; tail -5 "$LOGS/$name-discord.log" >&2; return 1
        fi
        sleep 0.5
    done
    echo "bot hasn't connected after 30 s; last lines:" >&2
    tail -5 "$LOGS/$name-discord.log" >&2
    return 1
}

restart_loop() {  # restart only the turn loop (picks up new Python code); the bot keeps running
    local name="${1:-}"
    [ -n "$name" ] || die "usage: just restart-loop <name>"
    valid_name "$name"
    local cfg="$GAMES_DIR/$name.toml" pids
    [ -f "$cfg" ] || die "no such game: $cfg"
    pids=$(running run | awk '{print $1}')
    [ -n "$pids" ] && kill $pids 2>/dev/null
    for _ in $(seq 20); do [ -z "$(running run)" ] && break; sleep 0.25; done
    [ -z "$(running run)" ] || die "the turn loop didn't stop: $(running run)"
    mkdir -p "$LOGS"
    setsid nohup uv run python -m parley run "$cfg" >>"$LOGS/$name-turns.log" 2>&1 < /dev/null &
    echo "turn loop restarted for '$name'"
}

GAME="${MTW2_GAME_DIR:-$HOME/.steam/steam/steamapps/common/Medieval II Total War}"

game_command() {  # write a command to the bridge's control file; it runs on the bridge's next tick
    printf '%s\n' "$@" >> "$GAME/parley_turns/control.txt"
}

reload_bridge() {  # install the bridge, then reload it inside the running game
    bash scripts/install_bridge.sh || return 1
    game_command "reload"
    echo "asked the running game to reload the bridge (its per-turn autosave is the fallback)"
}

logs() {
    local name="${1:-}"
    [ -n "$name" ] || die "usage: just logs <name>"
    valid_name "$name"
    for f in "$LOGS/$name-turns.log" "$LOGS/$name-discord.log"; do
        echo "== $f"; tail -15 "$f" 2>/dev/null || echo "(no log)"
    done
}

case "${1:-}" in
    new-game) shift; new_game "$@" ;;
    play) shift; play "$@" ;;
    stop) stop_all ;;
    status) status ;;
    logs) shift; logs "$@" ;;
    restart-loop) shift; restart_loop "$@" ;;
    reload-bridge) reload_bridge ;;
    *) die "usage: game.sh new-game|play|stop|status|logs|restart-loop|reload-bridge" ;;
esac
