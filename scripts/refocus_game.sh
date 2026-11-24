#!/usr/bin/env bash
# refocus_game.sh <bridge log age, s>: give the game window focus back when it isn't the active
# window and the bridge log has been quiet past PARLEY_REFOCUS_AFTER (60 s). Prints the name of the
# window that held focus and exits 0 when it refocused; exits 1 when it did nothing.
# Medieval II stops running when it isn't the active window. Live 2026-11-20 07:13-07:21 (the test laptop):
# a Steam window held focus, the game used no CPU for 8 minutes, and crash-watch saw a live process
# and no dialog, so nothing reacted. `xdotool windowactivate` is a window-manager request, not input
# (no click, key or pointer move), so it is allowed in a no-click run, as eop_error_box's WM close is.
# A fresh log is left alone, so a person's quick alt-tab isn't fought. PARLEY_REFOCUS=0 turns it off.
set -uo pipefail
age="${1:-0}"
[ "${PARLEY_REFOCUS:-1}" = 0 ] && exit 1
[ "$age" -ge "${PARLEY_REFOCUS_AFTER:-60}" ] 2>/dev/null || exit 1
game=$(timeout 5 xdotool search --name '^Medieval 2$' 2>/dev/null | head -1)
# no id: do nothing (live 11-20: an empty id made `import -window ""` wait for a click and hold X)
case "$game" in ''|*[!0-9]*) exit 1 ;; esac
active=$(timeout 5 xdotool getactivewindow 2>/dev/null)
[ "$active" = "$game" ] && exit 1
name=$(timeout 5 xdotool getwindowname "$active" 2>/dev/null)
timeout 5 xdotool windowactivate --sync "$game" >/dev/null 2>&1 || true
echo "${name:-window ${active:-none}}"
