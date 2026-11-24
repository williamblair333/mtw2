#!/usr/bin/env bash
# rotate_logs.sh: keep the campaign's logs under PARLEY_LOG_CAP_MB (default 20, as relaunch_game.sh).
# A log over the cap is kept as <log>.1 (one older copy, replaced each time) and starts again empty:
#   - parley_bridge.log is renamed: the bridge opens it for each line (lua/parley_bridge.lua log),
#     so its next line starts a new file;
#   - logs/*.log are copied, then cut to zero in place: the turn loop and the bot hold them open,
#     appending (game.sh play and restart-loop open them with >>), so they write on at the new end.
# Never while a QA run holds qa.lock: its runner reads the bridge log by byte offset.
# Called by scripts/campaign_watch.sh every 10 minutes; `just rotate-logs` by hand. Prints one line
# per log it rotated.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
ROOT="${PARLEY_TURN_ROOT:-$HOME/.steam/steam/steamapps/common/Medieval II Total War/parley_turns}"
LOGS="${PARLEY_LOGS_DIR:-logs}"
cap=$(( ${PARLEY_LOG_CAP_MB:-20} * 1024 * 1024 ))
[ -e "$ROOT/qa.lock" ] && exit 0
size() { stat -c %s "$1" 2>/dev/null || echo 0; }
bridge="$ROOT/parley_bridge.log"
if [ "$(size "$bridge")" -gt "$cap" ]; then
    # the new log starts with a stamped line: with none, a long AI turn (the bridge silent) left no
    # log, crash-watch read its age as since midnight and killed a healthy game (live 11-13 10:24).
    # >> appends: a bridge line written after the mv is kept
    mv -f "$bridge" "$bridge.1" && echo "rotated $bridge" \
        && printf '%s rotated: older lines in parley_bridge.log.1\n' "$(date '+%F %T')" >> "$bridge"
fi
for f in "$LOGS"/*.log; do
    [ -f "$f" ] || continue
    if [ "$(size "$f")" -gt "$cap" ]; then
        cp -f "$f" "$f.1" && : > "$f" && echo "rotated $f"
    fi
done
exit 0
