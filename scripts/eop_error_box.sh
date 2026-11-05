#!/usr/bin/env bash
# Exit 0, printing "<window id> <title>", when M2TWEOP's modal error box is up; else exit 1.
# EOP shows a Win32 message box titled exactly "ERROR" ("Cannot create M2TWEOP save file. 2" for a
# load of a save that isn't there, live 10-31). While it is up the game is frozen (the bridge answers
# no control line), and closing it ends the game. Read-only X queries (xdotool search /
# getwindowpid): no input, so it runs in a no-click run (PARLEY_NO_X_INPUT).
# The box must belong to the game: a window pid (Wine sets _NET_WM_PID to the Windows process's own
# pid) must be medieval2.exe or EOP's launcher; a window with no pid counts only while medieval2.exe
# runs. Another program's "ERROR" window never kills a healthy game.
set -uo pipefail

for w in $(xdotool search --name '^ERROR$' 2>/dev/null); do
    pid=$(xdotool getwindowpid "$w" 2>/dev/null || true)
    if [ -n "$pid" ]; then
        comm=$(cat "${PARLEY_PROC_ROOT:-/proc}/$pid/comm" 2>/dev/null || true)
        case "$comm" in
            medieval2.exe | "M2TWEOP GUI.exe") ;;
            *) continue ;;
        esac
    elif ! pgrep -x medieval2.exe >/dev/null 2>&1; then
        continue
    fi
    echo "$w ERROR"
    exit 0
done
exit 1
