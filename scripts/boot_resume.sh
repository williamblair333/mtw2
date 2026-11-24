#!/usr/bin/env bash
# At login, resume the campaign that was playing. Live 11-15: tc powers off at 23:59 and on at
# 03:00 (autologin), and nothing came back; the campaign idled until a hand relaunched it at 05:48.
# Run from the desktop's autostart (scripts/boot_resume_install.sh), so it has the session's
# DISPLAY. The campaign to resume is named in PARLEY_RESUME_FILE (`just resume-at-boot <name>`);
# a campaign paused by `just stop` (paused.txt) stays paused. `just play` starts the turn loop and
# the bot; crash-watch sees no medieval2.exe and relaunches the game on the newest save, no clicks.
set -uo pipefail
cd "$(dirname "$0")/.."
# --log (the autostart's): append to logs/boot-resume.log here, since a desktop entry's Exec has no
# shell redirection (single quotes aren't quoting there; review 11-15)
if [ "${1:-}" = "--log" ]; then mkdir -p logs; exec >> logs/boot-resume.log 2>&1; fi
# uv and just live in ~/.local/bin, which the desktop autostart's PATH lacks (live 11-19: "just:
# command not found" at 05:44, and nothing resumed)
export PATH="$HOME/.local/bin:$PATH"
just="${PARLEY_JUST:-just}"
resume_file="${PARLEY_RESUME_FILE:-$HOME/.config/parley/resume}"
turn_root="${PARLEY_TURN_ROOT:-$HOME/.steam/steam/steamapps/common/Medieval II Total War/parley_turns}"
name=$(head -1 "$resume_file" 2>/dev/null | tr -d '[:space:]')
stamp() { date '+%F %T'; }
if [ -z "$name" ]; then
    echo "$(stamp) boot-resume: no campaign named in $resume_file; nothing to start"
    exit 0
fi
if [ -e "$turn_root/paused.txt" ]; then
    echo "$(stamp) boot-resume: '$name' is paused ($turn_root/paused.txt); leaving it"
    exit 0
fi
# the desktop and Steam's own start-up first (Steam may self-update after a boot)
sleep "${PARLEY_BOOT_WAIT:-60}"
echo "$(stamp) boot-resume: resuming '$name'"
"$just" play "$name" || echo "$(stamp) boot-resume: just play $name failed"
"$just" crash-watch || echo "$(stamp) boot-resume: just crash-watch failed"
