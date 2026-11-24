#!/usr/bin/env bash
# Run Parley games with one command each.
#   game.sh new-game <name> [opts]   make games/local/<name>.toml from your template (--help: examples)
#   game.sh play <name>              stop anything running, start turn loop + Discord bot for <name>
#   game.sh bot <name>               start only the Discord bot for <name> (its turn loop stays stopped)
#   game.sh stop [--pause]           stop the turn loop and the bot; --pause (just stop) also holds the
#                                    campaign (paused.txt) so autoplay ends no turn unordered
#   game.sh status                   what's running, and for which game
#   game.sh logs <name>              latest output from both
set -uo pipefail

cd "$(dirname "$0")/.."
GAMES_DIR="${PARLEY_GAMES_DIR:-games/local}"
LOGS=logs

# a loop started over ssh has no display: it can't screenshot the game's popups, so every offer runs
# to its 540 s timeout (live 11-05 14:56, the test laptop: "screenshot failed: game window not found").
# Borrow the logged-in desktop's, as qa.sh does
# shellcheck source=desktop_env.sh
. scripts/desktop_env.sh
desktop_env_borrow >/dev/null 2>&1 \
    || echo "warning: nobody is logged in to the desktop; the turn loop can't see the game's popups" >&2

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

# send TERM to each pid's process group, wait up to 5 s, then KILL it (live: a killed loop left
# its agy call running 24 min, ignoring TERM). Only a group that is its own session (started with
# setsid, as play and restart-loop do) is killed whole; anything else, e.g. a bot started from
# the author's terminal, shares the terminal's group, so only the pid itself is killed.
kill_groups() {
    local pgids=() p g s
    for p in "$@"; do
        read -r g s < <(ps -o pgid=,sid= -p "$p" 2>/dev/null)
        if [ -n "$g" ] && [ "$g" = "$s" ]; then pgids+=("-$g"); else pgids+=("$p"); fi
    done
    kill -TERM "${pgids[@]}" 2>/dev/null
    for _ in $(seq 20); do
        kill -0 "${pgids[@]}" 2>/dev/null || return 0
        sleep 0.25
    done
    kill -KILL "${pgids[@]}" 2>/dev/null
    for _ in $(seq 10); do
        kill -0 "${pgids[@]}" 2>/dev/null || return 0
        sleep 0.05
    done
}

stop_all() {
    local pids
    pids=$( { running run; running discord; } | awk '{print $1}')
    if [ -z "$pids" ]; then echo "nothing running"; return 0; fi
    kill_groups $pids
    [ -z "$( { running run; running discord; } )" ] && { echo "stopped"; return 0; }
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
    resume_after_stop
    mkdir -p "$LOGS"
    # monitors off slow the game to a crawl (live 10-31: 66.5 s loads); keep them on while it runs
    bash scripts/screen_awake.sh start || echo "warning: screen-awake didn't start (just screen-awake)" >&2
    # a fresh file, appended to: scripts/rotate_logs.sh cuts it in place while the loop holds it open.
    # The old one is set aside (keep_log.sh), never emptied: it holds the record of the last run
    bash scripts/keep_log.sh "$LOGS/$name-turns.log"
    setsid nohup uv run python -m parley run "$cfg" >>"$LOGS/$name-turns.log" 2>&1 < /dev/null &
    launch_bot "$name" "$cfg"
    echo "starting game '$name'..."
    await_bot "$name" || return 1
    echo "turn loop and bot are running for '$name'."
    echo "next: Steam Play -> Run Mod -> Grand Campaign (NEW to start over, or load your save)"
    if grep -q '^\[autoplay\]' "$cfg"; then
        echo "      autoplay: the game ends its own turns; just watch."
    else
        echo "      untick Show CPU Moves; end turns when #$name says all rulers have decided."
    fi
}

launch_bot() {  # launch_bot <name> <cfg>: start the Discord bot in its own session
    : > "$LOGS/$1-discord.log"  # emptied, then appended to (scripts/rotate_logs.sh cuts it in place)
    setsid nohup bash -c 'set -a; [ -f .env ] && . ./.env; set +a; exec uv run python -m parley discord "$1"' \
        _ "$2" >>"$LOGS/$1-discord.log" 2>&1 < /dev/null &
}

await_bot() {  # await_bot <name>: wait up to 30 s for the bot to connect
    local name="$1"
    for _ in $(seq 60); do
        if grep -q "connected to" "$LOGS/$name-discord.log" 2>/dev/null; then
            grep "connected to" "$LOGS/$name-discord.log" | tail -1 | sed 's/^.*INFO //'
            return 0
        fi
        if [ -z "$(running discord)" ] && [ -s "$LOGS/$name-discord.log" ]; then
            # a machine with no bot token (the test laptop, by design) runs the turn loop alone. Live 11-05
            # 16:45 a QA restore there failed here after the loop had started, and kept qa.lock;
            # the campaign watch (WATCH_BOT=1) still reports a missing bot where one is expected
            if grep -q "DISCORD_BOT_TOKEN is not set" "$LOGS/$name-discord.log"; then
                echo "warning: no Discord bot here (DISCORD_BOT_TOKEN is not set); the turn loop runs without it" >&2
                return 0
            fi
            echo "the bot stopped:" >&2; tail -5 "$LOGS/$name-discord.log" >&2; return 1
        fi
        sleep 0.5
    done
    echo "bot hasn't connected after 30 s; last lines:" >&2
    tail -5 "$LOGS/$name-discord.log" >&2
    return 1
}

bot() {  # start only the Discord bot for <name> (a QA restore of a campaign whose loop was stopped)
    local name="${1:-}"
    [ -n "$name" ] || die "usage: game.sh bot <name>"
    valid_name "$name"
    local cfg="$GAMES_DIR/$name.toml"
    [ -f "$cfg" ] || die "no such game: $cfg"
    if [ -n "$(running discord)" ]; then echo "bot already running"; return 0; fi
    mkdir -p "$LOGS"
    launch_bot "$name" "$cfg"
    await_bot "$name" && echo "bot is running for '$name' (turn loop not started)"
}

restart_loop() {  # restart only the turn loop (picks up new Python code); the bot keeps running
    local name="${1:-}"
    [ -n "$name" ] || die "usage: just restart-loop <name>"
    valid_name "$name"
    local cfg="$GAMES_DIR/$name.toml" pids
    [ -f "$cfg" ] || die "no such game: $cfg"
    pids=$(running run | awk '{print $1}')
    [ -n "$pids" ] && kill_groups $pids
    [ -z "$(running run)" ] || die "the turn loop didn't stop: $(running run)"
    mkdir -p "$LOGS"
    setsid nohup uv run python -m parley run "$cfg" >>"$LOGS/$name-turns.log" 2>&1 < /dev/null &
    echo "turn loop restarted for '$name'"
}

GAME="${MTW2_GAME_DIR:-$HOME/.steam/steam/steamapps/common/Medieval II Total War}"
TURNS="${PARLEY_TURN_ROOT:-$GAME/parley_turns}"
# with the loop stopped, autoplay still ends each turn once its wait for orders runs out, ordered by
# nobody (live 11-05: run 10 went from turn 24 to 29 in an hour). `just stop` (stop --pause) holds the
# campaign with paused.txt; play takes off only a pause with this reason (never a QA hold or a seat's
# usage-limit pause). The QA runner's plain `stop` writes nothing: its bench turns must play
STOP_REASON="stopped by just stop: the turn loop is off"
pause_campaign() {
    [ -d "$TURNS" ] || return 0
    printf '%s; just play (or removing this file) resumes\n' "$STOP_REASON" > "$TURNS/paused.txt"
    echo "campaign paused ($TURNS/paused.txt); just play resumes it"
}
resume_after_stop() {
    if grep -qs "^$STOP_REASON" "$TURNS/paused.txt"; then
        rm -f "$TURNS/paused.txt"
        echo "resumed the campaign 'just stop' had paused"
    fi
}

game_command() {  # write a command to the bridge's control file; it runs on the bridge's next tick
    printf '%s\n' "$@" >> "$GAME/parley_turns/control.txt"
}

reload_bridge() {  # install the bridge, then reload it inside the running game
    bash scripts/install_bridge.sh || return 1
    local log="$GAME/parley_turns/parley_bridge.log" n
    n=$(( $(wc -l < "$log" 2>/dev/null || echo 0) + 1 ))
    game_command "reload"
    echo "asked the running game to reload the bridge (its per-turn autosave is the fallback)"
    pgrep -f medieval2.exe >/dev/null || return 0  # no game: it loads the new bridge on its next start
    # wait for it: a control line written before the reload ran (just lua replaces the file) lost the
    # request and the old bridge kept running (live 10-31 17:16)
    local i
    for i in $(seq 1 30); do
        if tail -n +"$n" "$log" 2>/dev/null | grep -q 'bridge reloaded at turn'; then
            tail -n +"$n" "$log" | grep 'bridge reloaded at turn' | tail -1 | sed 's/^/  /'
            return 0
        fi
        sleep 2
    done
    echo "the bridge didn't confirm the reload within 60 s (game busy, or the request was overwritten): run it again" >&2
    return 1
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
    bot) shift; bot "$@" ;;
    stop) shift; stop_all; if [ "${1:-}" = "--pause" ]; then pause_campaign; fi ;;
    status) status ;;
    logs) shift; logs "$@" ;;
    restart-loop) shift; restart_loop "$@" ;;
    reload-bridge) reload_bridge ;;
    *) die "usage: game.sh new-game|play|bot|stop|status|logs|restart-loop|reload-bridge" ;;
esac
