#!/usr/bin/env python3
"""Preflight gate (.claude/preflight.toml, id waits-wake-on-stall): refuse two shell mistakes that
left a queue on tc hung for 3 hours on 11-21 without anyone being told.

1. pgrep/pkill -f whose pattern matches the command line it runs in. The harness runs every
   command through `bash -c`, and ssh runs it the same way remotely, so the whole command is some
   process's argv: `while pgrep -f "[p]ython3 x.py"` matched "python3 x.py" further on in the same
   string and never ended. The [b]racket trick only keeps the pattern itself from matching.
2. A wait loop (until/while ... do ... sleep) with no clock in it (SECONDS, date +%s, timeout N):
   it ends only when the thing it waits for happens, so a hang is silent.

Reads the command from PREFLIGHT_COMMAND; exit 0 = go, else the reason is printed."""
from __future__ import annotations

import os
import re
import shlex
import sys

# only where a command starts (line start, after ; & | ( or a loop/if keyword): not prose that
# names pgrep, such as a commit message about this very gate
PGREP = re.compile(r"(?:^|[;&|(`'\"]|\b(?:while|until|if|then|do|!))\s*p(?:grep|kill)\b((?:\s+-\w+)*\s+-\w*f\w*(?:\s+-\w+)*)\s+(\"[^\"]*\"|'[^']*'|\S+)")
LOOP = re.compile(r"(?s)\b(?:until|while)\b.*?;\s*do\b.*?\bsleep\b")
CLOCK = re.compile(r"\bSECONDS\b|date\s+\+%s|\btimeout\s+\d")


def problems(cmd: str) -> list[str]:
    out = []
    for m in PGREP.finditer(cmd):
        raw = m.group(2)
        try:
            pat = shlex.split(raw)[0]
        except ValueError:
            pat = raw.strip("\"'")
        try:
            rx = re.compile(pat)
        except re.error:
            continue
        # the command with this pgrep's own pattern cut out: what else in the argv could it match
        rest = cmd[:m.start(2)] + cmd[m.end(2):]
        if rx.search(rest):
            out.append(f"pgrep/pkill -f {raw} matches text elsewhere in this same command, which is "
                       "itself a running process's command line (bash -c / ssh): it will find itself. "
                       "Use a PID, pgrep -x, or a pattern that appears nowhere else in the command.")
    if LOOP.search(cmd) and not CLOCK.search(cmd):
        out.append("a wait loop with no deadline or stall check: it ends only on success, so a hang "
                   "is silent. Track time (SECONDS / date +%s / timeout N) and break with a "
                   "STALLED or DEADLINE line.")
    return out


def main() -> int:
    found = problems(os.environ.get("PREFLIGHT_COMMAND", ""))
    for p in found:
        print(p)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
