#!/usr/bin/env bash
# campaign_watch.sh <game_id> [faction] — watch a running campaign; print one line and exit when it
# needs attention. Run it in the background from Claude Code (run_in_background), so Claude is woken
# only then; healthy, it costs nothing. See docs/NOTIFY-CLAUDE.md.
#
# Exits (= wakes) on:
#   STALL   the bridge log quiet for 6 min (a hung or crashed game; crash-watch relaunches at ~8.5)
#   STUCK   a turn stuck 10+ tries (~5 min) behind something the bridge can't close; live (2026-10-30)
#           the "Victory Conditions Failed" screen, where the bridge keeps logging so STALL never fires
#   DOWN    the turn loop, the Discord bot or crash-watch not running
#   LOST    the watched faction holds no settlements, the game shows its campaign-over screen
#           (end_campaign_scroll in the bridge's newest ui_scan, on a stuck turn), or no new report
#           for 15 min
#           (conquered during the AI turns: its last report still showed a town); not while a QA
#           bench run holds qa.lock, and counted from the restore (qa.last_restore) when that is newer
#   OUT     another seat's reports stopped 4+ turns behind the watched faction's (conquered, or its
#           seat dead); one already out when the watch starts is seen
#   SEATS   a ruler seat failing 3+ consecutive turns in logs/<game>-turns.log (any faction)
#   AUDIT   a new [bridge] alert from the turn audit (seat errors excepted); only with WAKE_ON_AUDIT=1
#           (otherwise they wait in #<game>-audit)
#   CRASH   a new crash report in runs/crashes (PARLEY_CRASH_DIR), even one crash-watch recovered
#   CLICK   a new "X input refused" line in the turn log: something asked for a screen click or key,
#           which Parley no longer makes (11-21); it needs an element path in the bridge
#   TREND   a new alert from `just trends` (a falling applied share, slowing rulers, a lost town, a
#           late or failed seat), checked every 10 min; alerts already there at the start are seen
# WATCH_BOT=0: a run without the Discord bot (live 11-05 14:42, the test laptop: the watch exited DOWN in its
# first minute on "bot: not running", and nothing watched the campaign)
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
# a host with no bot token (the test laptop, by design; game.sh's await_bot reads the same line) watches
# without the bot. Live 11-20: the watch there exited DOWN at once until WATCH_BOT=0 was typed by
# hand. Only the log's last lines count, and a later "connected to" wins, so an old error left in
# the file doesn't hide a bot that should be running. An explicit WATCH_BOT always wins. Asked
# each time the bot is found down, not once at the start: live 11-21 20:24 the watch started just
# after a QA restore had rotated the bot's log, before the bot wrote its line, and exited DOWN
no_bot_host() {
    tail -n 20 "$LOGS/$GAME-discord.log" 2>/dev/null \
        | awk '/DISCORD_BOT_TOKEN is not set/ {s=1} /connected to/ {s=0} END {exit !s}'
}
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
trend_alerts() { .venv/bin/python -m parley.trends "$ROOT" "$GAME" --alerts-only 2>/dev/null | sort; }
# the other seats: one whose reports stopped 4+ turns behind the watched faction's is out, conquered
# or its seat dead. Live 11-10: France lost its last town on turn 169, the loop wrote no more France
# reports, and nothing woke for 40 turns: LOST looked at england only. Prints "f (last report turn N)"
seats_out() {
    find "$ROOT/$GAME" -mindepth 3 -maxdepth 3 -path '*/turn-*/*/state.json' 2>/dev/null | awk -F/ -v me="$FACTION" '
        { t = $(NF-2); sub(/^turn-0*/, "", t); f = $(NF-1); if (t + 0 > last[f]) last[f] = t + 0 }
        END { if (me in last) for (f in last) if (f != me && last[f] < last[me] - 3)
                  print f " (last report turn " last[f] ")" }' | sort | paste -sd, - | sed 's/,/, /g'
}
# a watch started where the game doesn't run reads a dead local log. Live 11-13 06:18: started on
# the main machine while the game ran on the test laptop, it woke at once with a STALL on an 11-04 bridge line.
# crash-watch running here means the game lives here (after a boot Steam can take minutes to start it)
log_age=$(( $(date +%s) - $(stat -c %Y "$LOG" 2>/dev/null || echo 0) ))
if [ "$log_age" -gt "${PARLEY_WATCH_HOST_AGE:-21600}" ] && ! pgrep -x medieval2.exe >/dev/null \
        && ! systemctl --user is-active -q parley-crash-watch 2>/dev/null; then
    echo "NOT HERE: no game or crash-watch on $(hostname) and its bridge log is ${log_age}s old; run the watch where the game runs (e.g. ssh the test laptop)"
    exit 1
fi
out_seen=$(seats_out)
last_alert=$(latest_alert || echo 0)
# failures already in the log when the watch starts were reported by the watch before it;
# fire only when the picture changes (a new failed turn), or a restarted watch would loop
seats_seen=$(seat_errors)
trends_seen=$(trend_alerts)
# a crash crash-watch recovered still wakes the session, so its cause gets looked at: live 11-05 the
# 20:00 crash (a marriage-offer click) was relaunched in a minute and noticed an hour later
newest_crash() { ls -1d "${PARLEY_CRASH_DIR:-runs/crashes}"/2*/ 2>/dev/null | sort | tail -1; }
crash_seen=$(newest_crash)
# Parley makes no screen input (11-21, parley/xinput.py): a code path that still asks for one is
# refused and logged "X input refused". The first new one wakes the session (CLICK): the newest
# such line, by its timestamp, in the log and its rotated copy (rotate_logs.sh copies to .1 and
# truncates; a count would reset there and miss one)
latest_refused() { cat "$TURN_LOG.1" "$TURN_LOG" 2>/dev/null | grep -a 'X input refused' | tail -1; }
refused_seen=$(latest_refused)
minute=0
while true; do
    sleep 60
    minute=$((minute + 1))
    crash=$(newest_crash)
    if [ -n "$crash" ] && [ "$crash" != "$crash_seen" ]; then
        echo "CRASH: $(basename "$crash"): $(grep -m1 -E '^- (crash-watch saw|game):' "$crash/report.md" 2>/dev/null | cut -c1-200)"
        exit 0
    fi
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
    # and stale when a campaign was loaded after it: live 11-11 12:07 the lost campaign's "try 12", 40 s
    # before a restart at turn 5, said LOST about the new campaign (healthy, waiting for its ruler)
    if [ -n "$stuck_line" ] && echo "$recent" | awk -v s="$stuck_line" 'f && /bridge loaded campaign/ {hit=1} $0 == s {f=1} END {exit !hit}'; then
        tries=0
    fi
    if [ "${tries:-0}" -ge 10 ]; then
        # the bridge lists what's open in ui_scan-*.txt; the campaign-over screen means a defeat.
        # Live 11-05 17:10 (run 9): Scotland took York, England's last town, and this said only STUCK
        scan=$(ls -t "$ROOT"/ui_scan-*.txt 2>/dev/null | head -1)
        if [ -n "$scan" ] && grep -q '^end_campaign_scroll' "$scan"; then
            echo "LOST: the game shows its campaign-over screen (end_campaign_scroll in $(basename "$scan")); $(echo "$stuck_line" | cut -c1-100)"
            exit 0
        fi
        echo "STUCK: $(echo "$stuck_line" | cut -c1-150)"; exit 0
    fi
    # a QA bench run parks the loop, the bot and crash-watch while it holds qa.lock, and restores
    # them (live 11-05 17:05: the watch said DOWN during a one-case run). A lock over an hour old was
    # left behind: the checks run again, and DOWN says so
    lock_note=""
    parked=0
    # stat fails when the restore removes the lock between the test and the read: not parked
    lock_mtime=$(stat -c %Y "$ROOT/qa.lock" 2>/dev/null)
    if [ -n "$lock_mtime" ]; then
        lock_age=$(( $(date +%s) - lock_mtime ))
        if [ "$lock_age" -lt 3600 ]; then parked=1
        else lock_note=" (qa.lock is ${lock_age}s old: just qa-restore)"; fi
    fi
    if [ "$parked" = 0 ]; then
        st=$(bash scripts/game.sh status 2>&1)
        echo "$st" | grep -q 'turn loop: running' || { echo "DOWN: $st$lock_note"; exit 0; }
        if [ "${WATCH_BOT:-}" != 0 ] && ! echo "$st" | grep -q 'bot: running' \
                && { [ -n "${WATCH_BOT:-}" ] || ! no_bot_host; }; then
            echo "DOWN: $st$lock_note"; exit 0
        fi
        # crash-watch relaunches a crashed game; without it a crash waits for STALL and a person. Live
        # 11-05 (the test laptop): the campaign ran 14:41-16:50 with no crash-watch, and the 16:38 crash sat
        # until a QA run found the dialog at 16:44. WATCH_CRASH=0 for a run that means to go without it
        if [ "${WATCH_CRASH:-1}" != 0 ] && ! systemctl --user is-active --quiet parley-crash-watch 2>/dev/null \
                && ! pgrep -f "[c]rash_watch.sh" >/dev/null; then
            echo "DOWN: crash-watch is not running (just crash-watch)$lock_note"; exit 0
        fi
    fi
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
    out=$(seats_out)
    [ -n "$out" ] && [ "$out" != "$out_seen" ] && { echo "OUT: $out; $FACTION plays on" | cut -c1-300; exit 0; }
    seats=$(seat_errors)
    [ -n "$seats" ] && [ "$seats" != "$seats_seen" ] && { echo "$seats" | cut -c1-300; exit 0; }
    refused=$(latest_refused)
    # newer only (the lines start "YYYY-MM-DD HH:MM:SS"): a log moved aside by a restart shows an
    # older line, never a wake
    if [ -n "$refused" ] && [[ "${refused:0:19}" > "${refused_seen:0:19}" ]]; then
        echo "CLICK: a screen input was asked for and refused: $(echo "$refused" | cut -c1-220)"
        exit 0
    fi
    if [ $((minute % 10)) -eq 0 ]; then
        # the logs' size cap (STANDARDS log-rotation): a game that never relaunches grew its bridge
        # log past 25 MB (11-05); quiet unless it rotated something, and never a reason to exit
        bash scripts/rotate_logs.sh >/dev/null 2>&1 || true
        new_trends=$(bash scripts/trend_new.sh <(echo "$trends_seen") <(trend_alerts))
        [ -n "$new_trends" ] && { echo "TREND: $(echo "$new_trends" | head -3 | tr '\n' ';')" | cut -c1-300; exit 0; }
    fi
    if [ -n "${WAKE_ON_AUDIT:-}" ]; then
        new=$(sqlite3 "$DB" "select id, text from outbox where channel='audit' and id > $last_alert \
              and text like '%[bridge]%' and text not like '%seat error%' order by id" 2>/dev/null)
        [ -n "$new" ] && { echo "AUDIT: $new" | cut -c1-600; exit 0; }
    fi
    last_alert=$(latest_alert || echo "$last_alert")
done
