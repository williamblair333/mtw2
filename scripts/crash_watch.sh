#!/usr/bin/env bash
# Watch the running game and relaunch it after a crash (the author, 2026-10-26: relaunch it
# unattended when testing). A crash shows as no game process, as Wine's crash dialog
# (crash_dialog.sh, checked every poll: live 10-30 20:11 the dialog kept the process alive and was
# only noticed after 8 minutes), or, as the fallback, a bridge log silent for 8 minutes (live,
# turn 50: the crashed game kept its process behind a crash dialog). Before relaunching it writes a
# crash report (`just crashes` lists them). After a relaunch it waits 5 minutes for the game to load
# before it looks again.
set -uo pipefail
cd "$(dirname "$0")/.."
turn_root="${PARLEY_TURN_ROOT:-$HOME/.steam/steam/steamapps/common/Medieval II Total War/parley_turns}"
log="$turn_root/parley_bridge.log"
relaunch="${PARLEY_RELAUNCH:-scripts/relaunch_game.sh}"
# Before each relaunch, a crash report (runs/crashes/<time>/: log tails, screenshot, save; see
# scripts/crash_report.py). It is bounded by `timeout` and its failure is only logged: the relaunch
# never waits on it for more than report_timeout seconds.
report="${PARLEY_CRASH_REPORT:-scripts/crash_report.py}"
report_timeout="${PARLEY_CRASH_REPORT_TIMEOUT:-15}"
# A false positive kills a healthy game, and crash-watch relaunches right after a relaunch, so the
# dialog must be seen on two polls in a row (~30 s apart), and isn't looked for in the 120 s after
# this watch's own relaunch (start-up windows).
dialog_polls=0
relaunched_at=0
# EOP's modal "ERROR" box (eop_error_box.sh: exact title, the game's own window) freezes the game,
# and pressing OK ends it. It counts on its first poll. It is closed with a window-manager close
# request (`wmctrl -i -c`): that is no X input (no click, key or pointer move; the WM asks the window
# to close, as the title bar's X would), so it is allowed in a no-click run (PARLEY_NO_X_INPUT).
# Then the game gets error_box_exit_s seconds to exit before it is killed.
error_box="${PARLEY_EOP_ERROR_BOX:-scripts/eop_error_box.sh}"
error_box_exit_s="${PARLEY_ERROR_BOX_EXIT_TIMEOUT:-30}"
close_error_box() {  # window id
    echo "$(date '+%F %T') closing EOP's error box $1 (WM close request, no input)"
    wmctrl -i -c "$1" 2>/dev/null || true
    for _ in $(seq 1 "$error_box_exit_s"); do
        pgrep -x medieval2.exe >/dev/null || return 0
        sleep 1
    done
    echo "$(date '+%F %T') the game didn't exit ${error_box_exit_s} s after the box closed; killing it"
    pkill -x medieval2.exe || true
}
while true; do
    last_active=$(grep -vE 'stuck\?|still stuck' "$log" 2>/dev/null | tail -1 | cut -c1-19)
    age=$(( $(date +%s) - $(date -d "$last_active" +%s 2>/dev/null || stat -c %Y "$log") ))
    why=""
    # by process name, not command line: -f also matched shells and Steam's launch chain
    if ! pgrep -x medieval2.exe >/dev/null; then
        why="no medieval2.exe"
    elif box=$(bash "$error_box"); then
        why="EOP error box: ${box#* } (window ${box%% *})"
        close_error_box "${box%% *}"
    elif [ $(( $(date +%s) - relaunched_at )) -lt 120 ]; then
        dialog_polls=0
    elif dialog=$(bash scripts/crash_dialog.sh); then
        dialog_polls=$((dialog_polls + 1))
        [ "$dialog_polls" -ge 2 ] && why="crash dialog up on $dialog_polls polls ($dialog)"
    else
        dialog_polls=0
    fi
    if [ -z "$why" ] && [ "$age" -gt 480 ]; then
        # a quiet log is not a dead game: the bridge says nothing while a ruler decides (up to
        # DECIDE_WAIT 540 s) or the loop is stopped. Live 10-31 19:06 a healthy game was killed
        # and relaunched this way. Ask it first; an answer logs a line and restarts the clock
        if timeout -k 2 45 bash scripts/probe.sh 'return "alive"' 30 2>/dev/null | tr -d '\r' | grep -q '^alive$'; then
            echo "$(date '+%F %T') bridge log ${age}s quiet but the game answers: not a crash"
        else
            why="bridge log ${age}s old and the game didn't answer"
        fi
    fi
    if [ -n "$why" ]; then
        echo "$(date '+%F %T') crash suspected ($why): $(tail -1 "$log" | cut -c1-150)"
        out=$(timeout -k 2 "$report_timeout" python3 "$report" write --why "$why" 2>&1)
        rc=$?
        if [ "$rc" -eq 0 ]; then
            echo "$(date '+%F %T') crash report: $(echo "$out" | tail -1)"
        else  # 124: timed out
            echo "$(date '+%F %T') crash report failed (exit $rc): $(echo "$out" | tail -1)"
        fi
        bash "$relaunch" || echo "$(date '+%F %T') relaunch failed"
        dialog_polls=0
        relaunched_at=$(date +%s)
        sleep 300
    fi
    sleep 30
done
