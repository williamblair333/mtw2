#!/usr/bin/env bash
# Has the game left its campaign for the main menu? Prints the game log's exit line and exits 0 when its
# last "GAME EXIT TO MENU" comes after its last campaign load ("Hashmaps filled"); exits 1 otherwise, and
# when there is no game log. Live 11-11 11:13: the "Victory Conditions Failed" scroll's one button
# ("Return to Main Menu") left the campaign; a reload played on, but nothing noticed for 15 min.
# A QA bench load (M2TWEOP.loadGame) passes through the menu too, then loads: that one isn't counted.
set -uo pipefail
cd "$(dirname "$0")/.."
turn_root="${PARLEY_TURN_ROOT:-$HOME/.steam/steam/steamapps/common/Medieval II Total War/parley_turns}"
game_log="${PARLEY_GAME_LOG:-$turn_root/../mods/parley/logs/system.log.txt}"
EXIT_LINE="GAME EXIT TO MENU"   # EOP core, on leaving a campaign
LOAD_LINE="Hashmaps filled"     # EOP core, at the end of a campaign load
[ -f "$game_log" ] || exit 1
exit_n=$(grep -an "$EXIT_LINE" "$game_log" | tail -1 | cut -d: -f1)
[ -n "$exit_n" ] || exit 1
load_n=$(grep -an "$LOAD_LINE" "$game_log" | tail -1 | cut -d: -f1)
if [ -z "$load_n" ] || [ "$exit_n" -gt "$load_n" ]; then
    sed -n "${exit_n}p" "$game_log" | tr -d '\r'
    exit 0
fi
exit 1
