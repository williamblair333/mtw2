#!/usr/bin/env bash
# Run crash_watch.sh as the transient systemd user unit parley-crash-watch: `start` or `stop`.
# Live 10-30 20:20: crash-watch was started (setsid nohup) by a QA restore inside a Claude Code
# background job; stopping that job killed its whole process tree, crash-watch included, and the
# next crash went unnoticed. A user unit belongs to the user's systemd manager, not to whatever
# shell or job started it, and its fixed name allows only one.
# Stopping the unit kills everything in its cgroup (the loop, its sleep, a relaunch in progress).
# PARLEY_STEAM_SCOPE=1 makes relaunch_game.sh start Steam in a scope of its own, so a Steam (and
# game) that a relaunch had to start survives. KillMode=process was tried instead: the watch's
# leftover `sleep` kept the unit loaded and the next start failed ("already loaded").
# A watch started the old way (`bash scripts/crash_watch.sh`, no unit) is stopped by both actions,
# so there is never one beside the unit. Matched by exact argv, as parley/qa/runner.py does.
set -uo pipefail

unit=parley-crash-watch
repo=$(cd "$(dirname "$0")/.." && pwd)
log="$repo/logs/crash-watch.log"
proc_root="${PARLEY_PROC_ROOT:-/proc}"
# a non-login shell (cron, a job runner) may lack it; systemctl --user finds the bus through it
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

do_kill() {  # signal pid...
    if [ -n "${PARLEY_KILL:-}" ]; then "$PARLEY_KILL" "$@"; else kill "$@"; fi
}

unit_active() { systemctl --user is-active --quiet "$unit"; }

legacy_pids() {  # crash_watch.sh processes that aren't the unit's own
    local main=0 d argv
    if unit_active; then
        main=$(systemctl --user show -p MainPID --value "$unit" 2>/dev/null || echo 0)
    fi
    for d in "$proc_root"/[0-9]*; do
        [ -r "$d/cmdline" ] || continue
        argv=()
        mapfile -d '' -t argv <"$d/cmdline" 2>/dev/null || continue
        [ "${#argv[@]}" -eq 2 ] || continue
        [ "$(basename -- "${argv[0]}")" = bash ] || continue
        case "${argv[1]}" in
            scripts/crash_watch.sh | "$repo/scripts/crash_watch.sh") ;;
            *) continue ;;
        esac
        [ "${d##*/}" = "$main" ] && continue
        echo "${d##*/}"
    done
}

stop_legacy() {
    local pids
    pids=$(legacy_pids)
    [ -n "$pids" ] || return 0
    echo "crash-watch: stopping a watch started outside the unit (pid $(echo $pids))"
    # shellcheck disable=SC2086  # one pid per word
    do_kill -TERM $pids 2>/dev/null || true
    for _ in $(seq 1 25); do
        [ -n "$(legacy_pids)" ] || return 0
        sleep 0.2
    done
    pids=$(legacy_pids)
    # shellcheck disable=SC2086
    [ -n "$pids" ] && { do_kill -KILL $pids 2>/dev/null || true; }
    return 0
}

case "${1:-}" in
    start)
        stop_legacy
        if unit_active; then
            echo "crash-watch already running (unit $unit; log $log)"
            exit 0
        fi
        mkdir -p "$repo/logs"
        setenv=()
        # the user manager's own copies may be stale (XAUTHORITY changes each login)
        for name in DISPLAY XAUTHORITY PARLEY_TURN_ROOT PARLEY_RELAUNCH PARLEY_PY STEAM_PARK_X; do
            [ -n "${!name:-}" ] && setenv+=("--setenv=$name=${!name}")
        done
        systemd-run --user --unit="$unit" --collect --working-directory="$repo" \
            --property=StandardOutput="append:$log" --property=StandardError="append:$log" \
            --setenv=PARLEY_STEAM_SCOPE=1 "${setenv[@]}" \
            bash "$repo/scripts/crash_watch.sh" || { echo "crash-watch: systemd-run failed" >&2; exit 1; }
        echo "crash-watch started (unit $unit; log $log; stop: just crash-watch-stop)"
        ;;
    stop)
        if unit_active; then
            systemctl --user stop "$unit" || echo "crash-watch: systemctl stop failed" >&2
        fi
        stop_legacy
        if unit_active; then
            echo "crash-watch: unit $unit is still active" >&2
            exit 1
        fi
        ;;
    *)
        echo "usage: $0 start|stop" >&2
        exit 2
        ;;
esac
