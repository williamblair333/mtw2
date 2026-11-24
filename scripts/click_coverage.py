#!/usr/bin/env python3
"""Does every kind of screen input the census has seen have a bench case that passed with every
click refused? Reads the census kinds from the turn-loop logs (scripts/click_census.py), the map in
games/click-coverage.toml, and the newest `Run kind: noclick` report of each suite in runs/qa.
Prints one line per kind and exits 1 while any kind is unmapped, a known gap, or not yet passed.
Usage: click_coverage.py [--logs GLOB] [--reports DIR] [--map FILE]."""
from __future__ import annotations

import argparse
import glob
import re
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from click_census import parse  # noqa: E402

FIELDS = ("action", "kind", "event", "scroll", "wife")
REPORT = re.compile(r"^\d{4}-\d{2}-\d{2}-\d{4}-(.+)\.md$")
ROW = re.compile(r"^\| ([^|]+?) \| ([^|]+?) \|")


def matches(entry: dict, seen: dict) -> bool:
    return all(entry.get(f, "*") in ("*", seen[f]) for f in FIELDS)


def noclick_outcomes(report_dir: Path) -> dict[str, str]:
    """suite/case -> outcome, from the newest noclick report that ran that case."""
    out: dict[str, str] = {}
    for p in sorted(report_dir.glob("*.md"), key=lambda p: p.name):  # oldest first: newest wins
        m = REPORT.match(p.name)
        if not m:
            continue
        text = p.read_text(errors="replace")
        if "\nRun kind: noclick\n" not in text:
            continue
        for line in text.splitlines():
            r = ROW.match(line)
            if r and r.group(1) not in ("case", "---"):
                out[f"{m.group(1)}/{r.group(1)}"] = r.group(2)
    return out


def check(log_files: list[str], report_dir: Path, map_file: Path) -> tuple[list[str], bool]:
    lines: list[str] = []
    for f in log_files:
        try:
            lines.extend(Path(f).read_text(errors="replace").splitlines())
        except OSError:
            pass
    kinds = tomllib.loads(map_file.read_text())["kinds"]
    outcomes = noclick_outcomes(report_dir)
    report, ok = [], True
    seen_rows = [(dict(zip(FIELDS, key)), n) for key, n in parse(lines).most_common()]
    # the map is the durable list: a QA restore rotates the turn log and old ones are deleted (live
    # 11-21: the 26 marriage-offer clicks were gone from the logs by noon), so an entry no log shows
    # any more is still checked
    hit = {id(e) for s, _ in seen_rows for e in [next((e for e in kinds if matches(e, s)), None)] if e}
    for e in kinds:
        if id(e) not in hit:
            seen_rows.append(({f: e.get(f, "*") for f in FIELDS}, 0))
    for seen, n in seen_rows:
        label = " ".join(f"{f}={seen[f]}" for f in FIELDS if seen[f] not in ("-", "?", "*"))
        entry = next((e for e in kinds if matches(e, seen)), None)
        if entry is None and n == 0:
            continue
        if entry is None:
            report.append(f"UNMAPPED  {label} ({n}x): add it to {map_file}")
            ok = False
        elif not entry.get("cases"):
            report.append(f"GAP       {label} ({n}x): {entry.get('gap', 'no case')}")
            ok = False
        else:
            bad = [c for c in entry["cases"] if outcomes.get(c) != "pass"]
            if bad:
                report.append(f"NOT PASSED {label} ({n}x): " + ", ".join(f"{c}={outcomes.get(c, 'never run noclick')}"
                                                                     for c in bad))
                ok = False
            else:
                report.append(f"ok        {label} ({n}x): {', '.join(entry['cases'])}")
    return report, ok


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--logs", default="logs/*-turns.log*")
    ap.add_argument("--reports", type=Path, default=Path("runs/qa"))
    ap.add_argument("--map", type=Path, default=Path("games/click-coverage.toml"))
    a = ap.parse_args(argv)
    report, ok = check(sorted(glob.glob(a.logs)), a.reports, a.map)
    print("\n".join(report) if report else "no x-input lines in the logs")
    print("click coverage: " + ("every click kind has a passing no-click case" if ok else "INCOMPLETE"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
