#!/usr/bin/env python3
"""Tally the screen inputs the turn loop made (or tried to make) from its logs: what still needs a
click. Each `x-input:` line comes from parley/popups.py census(), one per click or Escape, made, or
refused in a no-click run. Usage: click_census.py [log files...] (default: logs/*-turns.log*).
Prints a markdown table, most frequent first: the list of challenges for no-click play."""
from __future__ import annotations

import collections
import glob
import re
import sys
from pathlib import Path

TAG = "x-input:"
FIELD = re.compile(r"(\w+)=(\S+)")
REFUSED = "X input refused in a no-click run"


def parse(lines) -> collections.Counter:
    seen: collections.Counter = collections.Counter()
    for line in lines:
        if TAG not in line:
            continue
        f = dict(FIELD.findall(line.split(TAG, 1)[1]))
        seen[(f.get("action", "?"), f.get("kind", "-"), f.get("event", "-"), f.get("scroll", "-"),
              f.get("wife", "-"))] += 1
    return seen


def refused(lines) -> int:
    return sum(REFUSED in line for line in lines)


def table(seen: collections.Counter) -> str:
    rows = ["| count | action | request kind | message event | scroll | wife |", "| ---: | --- | --- | --- | --- | --- |"]
    for (action, kind, event, scroll, wife), n in seen.most_common():
        rows.append(f"| {n} | {action} | {kind} | {event} | {scroll} | {wife} |")
    return "\n".join(rows)


def main(argv: list[str]) -> int:
    files = argv or sorted(glob.glob("logs/*-turns.log*"))
    lines: list[str] = []
    for f in files:
        try:
            lines.extend(Path(f).read_text(errors="replace").splitlines())
        except OSError as e:
            print(f"skipped {f}: {e}", file=sys.stderr)
    seen = parse(lines)
    print(f"# Click census: {sum(seen.values())} screen inputs in {len(files)} log file(s); "
          f"{refused(lines)} refused by the no-click guard\n")
    print(table(seen) if seen else "No x-input lines (logs from before 11-14 have none).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
