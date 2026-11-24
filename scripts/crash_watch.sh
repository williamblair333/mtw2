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
menu_polls=0
relaunched_at=0
stuck_tries="${PARLEY_STUCK_RELAUNCH_TRIES:-20}"  # a turn stuck this many tries is relaunched (below)
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
# the logs' size cap (STANDARDS log-rotation): every 20 polls (~10 min) scripts/rotate_logs.sh, quiet
# and never a reason to stop; crash-watch runs whenever a campaign does, the campaign watch only when
# a session watches (11-05: "with no campaign watch and no relaunch, nothing runs it")
polls=0
while true; do
    polls=$((polls + 1))
    if [ $((polls % 20)) -eq 0 ]; then bash scripts/rotate_logs.sh >/dev/null 2>&1 || true; fi
    last_active=$(grep -vE 'stuck\?|still stuck' "$log" 2>/dev/null | tail -1 | cut -c1-19)
    # no stamped line (no log yet, or just rotated) is no age: `date -d ""` is midnight, which read a
    # rotated log as 10 h old and killed a healthy game (live 11-13 10:24); the process and dialog
    # checks below still apply
    if [ -n "$last_active" ]; then
        age=$(( $(date +%s) - $(date -d "$last_active" +%s 2>/dev/null || stat -c %Y "$log" 2>/dev/null || date +%s) ))
    else
        age=0
    fi
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
    # the game stops when it isn't the active window (refocus_game.sh; live 11-20 07:13: a Steam window
    # held focus for 8 minutes and nothing saw it). Once per quiet stretch, so a person at the desktop
    # isn't fought every poll: the next refocus waits for the log to move again
    if [ -z "$why" ] && [ "$last_active" != "${refocused_at_line:-}" ] \
            && held=$(bash scripts/refocus_game.sh "$age"); then
        echo "$(date '+%F %T') the game window wasn't active (held by ${held}) and the bridge log was ${age}s quiet: gave the game focus (WM request, no input)"
        refocused_at_line="$last_active"
    fi
    # the game back at the main menu, no campaign loaded since (left_to_menu.sh): live 11-11 11:13 the
    # "Victory Conditions Failed" scroll's one button left the campaign, and a reload played on. Two polls
    # in a row, as the dialog, and not in the start-up window after this watch's own relaunch
    if [ -z "$why" ] && [ $(( $(date +%s) - relaunched_at )) -ge 120 ] && menu=$(bash scripts/left_to_menu.sh); then
        menu_polls=$((menu_polls + 1))
        [ "$menu_polls" -ge 2 ] && why="the game left its campaign for the main menu ($menu)"
    else
        menu_polls=0
    fi
    # a turn stuck behind something the bridge can't close: it logs "stuck? try N" every ~30 s, so the
    # log is never quiet. Live 11-11 13:58: Denmark's AI turn stood still after a battle, nothing on
    # screen, and only a relaunch moved it on. stuck_tries (~10 min) is past the campaign watch's STUCK
    # wake (10 tries), and the line must be fresh (a turn that moved on stops logging it)
    if [ -z "$why" ]; then
        stuck=$(tail -200 "$log" 2>/dev/null | grep -a 'stuck? try [0-9]' | tail -1)
        stuck_n=$(echo "$stuck" | grep -oE 'stuck\? try [0-9]+' | grep -oE '[0-9]+$')
        stuck_ts=$(date -d "${stuck:0:19}" +%s 2>/dev/null || echo 0)
        if [ "${stuck_n:-0}" -ge "$stuck_tries" ] && [ $(( $(date +%s) - stuck_ts )) -lt 120 ]; then
            why="a turn stuck ${stuck_n} tries ($(echo "${stuck:20}" | cut -c1-80))"
        fi
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
        menu_polls=0
        relaunched_at=$(date +%s)
        sleep 300
    fi
    sleep 30
done
