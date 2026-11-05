#!/usr/bin/env bash
# Hold a standing order like "work until 23:00": while .claude/work-until.local holds a time still
# ahead, a Claude Code Stop hook refuses to end the turn. Live 11-05: The author said "work until 2300 on
# the test laptop, don't stop", and the session still stopped at 06:31 after a milestone.
#   work_until.sh set HH:MM   today's HH:MM (local); tomorrow's if it has passed
#   work_until.sh off         drop the order
#   work_until.sh show        print it
#   work_until.sh hook        the Stop hook (reads the hook JSON on stdin; prints a block decision)
# A missing, unreadable or past order never blocks (fails open).
set -uo pipefail
root="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
file="$root/.claude/work-until.local"
now_epoch() { date +%s; }  # tests override with WORK_UNTIL_NOW

case "${1:-show}" in
    set)
        hm="${2:?usage: work_until.sh set HH:MM}"
        [[ "$hm" =~ ^([01]?[0-9]|2[0-3]):[0-5][0-9]$ ]] || { echo "expected HH:MM, not '$hm'" >&2; exit 2; }
        t=$(date -d "today $hm" +%s)
        [ "$t" -le "$(now_epoch)" ] && t=$(date -d "tomorrow $hm" +%s)
        date -d "@$t" --iso-8601=minutes > "$file"
        echo "work until $(cat "$file") (stop: just work-until off)"
        ;;
    off) rm -f "$file"; echo "no standing order" ;;
    show) if [ -f "$file" ]; then echo "work until $(cat "$file")"; else echo "no standing order"; fi ;;
    hook)
        cat >/dev/null  # the hook's JSON; not needed
        [ -f "$file" ] || exit 0
        until_s=$(date -d "$(head -1 "$file")" +%s 2>/dev/null) || { echo "work-until: unreadable $file; not holding" >&2; exit 0; }
        now=${WORK_UNTIL_NOW:-$(now_epoch)}
        if [ "$now" -ge "$until_s" ]; then
            echo "work-until: $(head -1 "$file") has passed; the turn may end" >&2
            exit 0
        fi
        left=$(( (until_s - now) / 60 ))
        printf '{"decision":"block","reason":"Standing order from the author: keep working until %s (%d min left). Do not stop at a milestone: report in one line and take the next item (HANDOFF top section, then the phase order in STANDARDS.md). Only the author ends it early (just work-until off)."}\n' "$(head -1 "$file")" "$left"
        ;;
    *) echo "usage: work_until.sh set HH:MM | off | show | hook" >&2; exit 2 ;;
esac
