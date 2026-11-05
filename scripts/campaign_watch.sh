#!/usr/bin/env bash
# campaign_watch.sh <game_id> [faction] — watch a running campaign; print one line and exit when it
# needs attention. Run it in the background from Claude Code (run_in_background), so Claude is woken
# only then; healthy, it costs nothing. See docs/NOTIFY-CLAUDE.md.
#
# Exits (= wakes) on:
#   STALL   the bridge log quiet for 6 min (a hung or crashed game; crash-watch relaunches at ~8.5)
#   STUCK   a turn stuck 10+ tries (~5 min) behind something the bridge can't close; live (2026-10-30)
#           the "Victory Conditions Failed" screen, where the bridge keeps logging so STALL never fires
#   DOWN    the turn loop or the Discord bot not running
#   LOST    the watched faction holds no settlements, or has had no new report for 15 min
#           (conquered during the AI turns: its last report still showed a town); not while a QA
#           bench run holds qa.lock, and counted from the restore (qa.last_restore) when that is newer
#   SEATS   a ruler seat failing 3+ consecutive turns in logs/<game>-turns.log (any faction)
#   AUDIT   a new [bridge] alert from the turn audit (seat errors excepted); only with WAKE_ON_AUDIT=1
#           (otherwise they wait in #<game>-audit)
# Matches the bridge's "stuck? try N" log line and game.sh status's "turn loop: running"/"bot: running".
set -uo pipefail
GAME="${1:?usage: campaign_watch.sh <game_id> [faction]}"
FACTION="${2:-england}"
cd "$(dirname "$0")/.." || exit 1
ROOT="${PARLEY_TURN_ROOT:-$HOME/.steam/steam/steamapps/common/Medieval II Total War/parley_turns}"
LOG="$ROOT/parley_bridge.log"
DB="$ROOT/$GAME.db"
LOGS="${PARLEY_LOGS_DIR:-logs}"
TURN_LOG="${PARLEY_TURN_LOG:-$LOGS/$GAME-turns.log}"
latest_alert() { sqlite3 "$DB" "select coalesce(max(id),0) from outbox where channel='audit'" 2>/dev/null; }
seat_errors() {
    tail -n 500 "$TURN_LOG" 2>/dev/null | awk '
        match($0, /ERROR ([A-Za-z0-9_]+) turn ([0-9]+): seat error: (.*)/, m) {
            f = m[1]; t = m[2]
            if (!(f in seen)) { order[++nf] = f; seen[f] = 1 }
            n[f]++; turns[f] = (turns[f] ? turns[f] ", " : "") t
            err_t[f] = t; err[f] = m[3]; seq[f] = ++s
        }
        match($0, /INFO ([A-Za-z0-9_]+) turn ([0-9]+): [0-9]+ orders,/, m) {
            f = m[1]; t = m[2]
            if (err_t[f] == t) err_t[f] = ""
            else { n[f] = 0; turns[f] = "" }
        }
        END {
            for (i = 1; i <= nf; i++) {
                f = order[i]
                if (n[f] >= 3) {
                    out = (out ? out ", " : "") f " (turns " turns[f] ")"
                    if (seq[f] > last_s) { last_s = seq[f]; last = err[f] }
                }
            }
            if (out) print "SEATS: " out ": " last
        }'
}
last_alert=$(latest_alert || echo 0)
# failures already in the log when the watch starts were reported by the watch before it;
# fire only when the picture changes (a new failed turn), or a restarted watch would loop
seats_seen=$(seat_errors)
while true; do
    sleep 60
    age=$(( $(date +%s) - $(stat -c %Y "$LOG") ))
    # quiet is not stalled: the bridge says nothing while a ruler decides (DECIDE_WAIT 540 s). Live
    # 10-31 19:21 STALL fired at 391 s while the game answered; ask it first (as crash_watch.sh does)
    if [ "$age" -gt 360 ] && ! timeout -k 2 45 bash scripts/probe.sh 'return "alive"' 30 2>/dev/null \
            | tr -d '\r' | grep -q '^alive$'; then
        echo "STALL: bridge log quiet ${age}s and the game didn't answer; last: $(tail -1 "$LOG" | cut -c1-150)"; exit 0
    fi
    # the newest "stuck? try N" in the tail, unless a turn ended after it: live 11-01 the papal
    # trace logged every 2 s, the last line was never the stuck line, and turn 50 sat stuck
    # (try 1017) with no STUCK
    recent=$(tail -50 "$LOG")
    stuck_line=$(echo "$recent" | grep -E 'stuck\? try [0-9]+' | tail -1)
    tries=$(echo "$stuck_line" | grep -oE 'stuck\? try [0-9]+' | grep -oE '[0-9]+$')
    # stale when old: stuck turns log a try every 20-40 s, so one over 3 min old means the turn moved
    # on (live 11-01 03:53: turn 50 ended by the game after a vote, no "ending turn" line, and the
    # old stuck line fired STUCK)
    stuck_ts=$(date -d "${stuck_line:0:19}" +%s 2>/dev/null || echo 0)
    if [ -n "$stuck_line" ] && [ $(( $(date +%s) - stuck_ts )) -gt 180 ]; then
        tries=0
    fi
    if [ "${tries:-0}" -ge 10 ]; then echo "STUCK: $(echo "$stuck_line" | cut -c1-150)"; exit 0; fi
    st=$(bash scripts/game.sh status 2>&1)
    echo "$st" | grep -q 'turn loop: running' || { echo "DOWN: $st"; exit 0; }
    echo "$st" | grep -q 'bot: running' || { echo "DOWN: $st"; exit 0; }
    s=$(ls -t "$ROOT/$GAME"/turn-*/"$FACTION"/state.json 2>/dev/null | head -1)
    if [ -n "$s" ]; then
        held=$(python3 -I -c "import json,sys; print(len(json.load(open(sys.argv[1]))['settlements']))" "$s" 2>/dev/null)
        if [ "$held" = "0" ]; then echo "LOST: $FACTION holds no settlements ($s)"; exit 0; fi
        # a QA bench run parks the real campaign: no real report comes while qa.lock is up, and the
        # clock restarts at the restore (qa.last_restore); live 10-30 23:33 the watch fired at once on
        # a report from before the run
        if [ ! -e "$ROOT/qa.lock" ]; then
            since=$(stat -c %Y "$s")
            restored=$(stat -c %Y "$ROOT/qa.last_restore" 2>/dev/null || echo 0)
            [ "$restored" -gt "$since" ] && since=$restored
            if [ $(( $(date +%s) - since )) -gt 900 ]; then
                echo "LOST?: no $FACTION report for 15 min ($s)"; exit 0
            fi
        fi
    fi
    seats=$(seat_errors)
    [ -n "$seats" ] && [ "$seats" != "$seats_seen" ] && { echo "$seats" | cut -c1-300; exit 0; }
    if [ -n "${WAKE_ON_AUDIT:-}" ]; then
        new=$(sqlite3 "$DB" "select id, text from outbox where channel='audit' and id > $last_alert \
              and text like '%[bridge]%' and text not like '%seat error%' order by id" 2>/dev/null)
        [ -n "$new" ] && { echo "AUDIT: $new" | cut -c1-600; exit 0; }
    fi
    last_alert=$(latest_alert || echo "$last_alert")
done
