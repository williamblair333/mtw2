#!/usr/bin/env bash
# Keep the monitors from powering off while Medieval II runs: `start`, `stop`, or `run` (the unit's
# own loop). Live 10-31 19:11-19:14: with the screens off (xset dpms force off) a bench load took
# 66.5 s and the game acted on nothing; screens on, 6.5 s. Focus made no difference (A/B 18:5x).
# The long-term fix is a headless display for the game (the author, 10-31: "inhibit now, headless later").
# Runs as the transient user unit parley-screen-awake (as crash_watch_unit.sh does): it outlives the
# shell that started it, and its fixed name allows only one. While medieval2.exe runs it holds a
# KDE inhibit (kde-inhibit --power --screenSaver), released when the game exits.
set -uo pipefail

unit=parley-screen-awake
repo=$(cd "$(dirname "$0")/.." && pwd)
log="$repo/logs/screen-awake.log"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

game_up() { pgrep -f 'medieval2\.exe' >/dev/null; }
stamp() { date '+%F %T'; }

case "${1:-}" in
    run)
        while true; do
            if game_up; then
                echo "$(stamp) game running: holding the screen inhibit"
                kde-inhibit --power --screenSaver bash -c \
                    'while pgrep -f "medieval2\.exe" >/dev/null; do sleep 30; done' \
                    || echo "$(stamp) kde-inhibit failed (exit $?)"
                echo "$(stamp) game gone: inhibit released"
            fi
            sleep 30
        done
        ;;
    start)
        if systemctl --user is-active --quiet "$unit"; then
            echo "screen-awake already running (unit $unit; log $log)"
            exit 0
        fi
        mkdir -p "$repo/logs"
        setenv=()
        # kde-inhibit talks to Plasma over the session bus: the unit needs this session's address
        for name in DISPLAY XAUTHORITY DBUS_SESSION_BUS_ADDRESS; do
            [ -n "${!name:-}" ] && setenv+=("--setenv=$name=${!name}")
        done
        systemd-run --user --unit="$unit" --collect --working-directory="$repo" \
            --property=StandardOutput="append:$log" --property=StandardError="append:$log" \
            "${setenv[@]}" bash "$repo/scripts/screen_awake.sh" run \
            || { echo "screen-awake: systemd-run failed" >&2; exit 1; }
        echo "screen-awake started (unit $unit; log $log; stop: just screen-awake-stop)"
        ;;
    stop)
        systemctl --user stop "$unit" 2>/dev/null || true
        echo "screen-awake stopped"
        ;;
    *)
        echo "usage: $0 start|stop|run" >&2
        exit 2
        ;;
esac
