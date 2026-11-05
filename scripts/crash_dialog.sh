#!/usr/bin/env bash
# Exit 0, printing "<window id> <W>x<H>", when the game's crash dialog is up; else exit 1.
# Under Proton a crash shows a Wine message box titled "Medieval 2" ("Medieval 2: Total War
# encountered an unspecified error and will now exit.", OK button), about 330x110, and
# medieval2.exe stays alive until OK is pressed (live 10-30 20:11: crash-watch saw it only after 8
# minutes of bridge-log silence). The game's own window has the same title but is 1600x900, so the
# rule is size: a visible "Medieval 2" window between 150x60 and 800x400 is the dialog. The upper
# bound keeps the game window (and an 800x600/640x480 start-up size) out; the lower bound keeps
# stub windows out (the launcher has a 2x29 one).
set -uo pipefail

for w in $(xdotool search --onlyvisible --name '^Medieval 2$' 2>/dev/null); do
    WIDTH=0 HEIGHT=0
    eval "$(xdotool getwindowgeometry --shell "$w" 2>/dev/null | grep -E '^(WIDTH|HEIGHT)=[0-9]+$')"
    if [ "$WIDTH" -ge 150 ] && [ "$WIDTH" -le 800 ] && [ "$HEIGHT" -ge 60 ] && [ "$HEIGHT" -lt 400 ]; then
        echo "$w ${WIDTH}x${HEIGHT}"
        exit 0
    fi
done
exit 1
