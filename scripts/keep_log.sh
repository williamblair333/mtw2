#!/usr/bin/env bash
# keep_log.sh <log> [keep] — set a log aside before a fresh start: <log>.<stamp>, the newest [keep]
# (default 5) of those kept, then <log> left empty. Live 11-10: `just play` mid-campaign emptied
# scratch-turns.log, and with it the turn loop's record of that hour's two crashes.
set -uo pipefail
log="${1:?usage: keep_log.sh <log> [keep]}"
keep="${2:-5}"
if [ -s "$log" ]; then
    mv "$log" "$log.$(date +%Y%m%d-%H%M%S)"
    ls -1t "$log".2* 2>/dev/null | tail -n +"$((keep + 1))" | xargs -r rm -f
fi
: > "$log"
