#!/usr/bin/env bash
# SessionStart(compact) hook: put HANDOFF.md's newest section back into the session.
cd "$(dirname "$0")/.." || exit 0
echo "After compaction: HANDOFF.md's top section follows. If a campaign is running,"
echo "check that \`just watch scratch\` is still running in the background (a new session"
echo "needs one started); restart it with run_in_background if not."
echo
awk '/^## /{n++} n==1' HANDOFF.md
