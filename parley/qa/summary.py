"""Summarize QA bench reports: newest report per suite, outcome counts, and failed cases."""

from __future__ import annotations

import argparse
from pathlib import Path
import re


def _parse_report(path: Path) -> tuple[dict[str, int], list[tuple[str, str, str]], str]:
    counts = {"pass": 0, "fail": 0, "inconclusive": 0, "skipped": 0}
    issues: list[tuple[str, str, str]] = []
    duration = ""

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return counts, issues, duration

    lines = content.splitlines()
    in_table = False
    col_idx: dict[str, int] = {}

    for line in lines:
        line_s = line.strip()
        if line_s.startswith("Total:"):
            after_total = line_s[6:].strip()
            if " for " in after_total:
                duration = after_total.split(" for ")[0].strip()
            else:
                duration = after_total

        if not in_table:
            if "|" in line_s:
                parts = [c.strip().lower() for c in re.split(r"(?<!\\)\|", line_s)]
                if parts and parts[0] == "":
                    parts = parts[1:]
                if parts and parts[-1] == "":
                    parts = parts[:-1]
                if "case" in parts and "outcome" in parts:
                    col_idx = {name: idx for idx, name in enumerate(parts)}
                    in_table = True
            continue

        if not line_s.startswith("|"):
            in_table = False
            continue

        parts = [c.strip() for c in re.split(r"(?<!\\)\|", line_s)]
        if parts and parts[0] == "":
            parts = parts[1:]
        if parts and parts[-1] == "":
            parts = parts[:-1]

        if all(re.match(r"^:?-+:?$", c) for c in parts if c):
            continue

        if "case" in col_idx and "outcome" in col_idx:
            case_idx = col_idx["case"]
            outcome_idx = col_idx["outcome"]
            ev_idx = col_idx.get("evidence")

            if max(case_idx, outcome_idx) < len(parts):
                case_name = parts[case_idx]
                outcome = parts[outcome_idx].lower()
                ev_text = parts[ev_idx] if (ev_idx is not None and ev_idx < len(parts)) else ""
                ev_text = ev_text.replace(r"\|", "|")

                if outcome in counts:
                    counts[outcome] += 1
                if outcome in ("fail", "inconclusive"):
                    issues.append((case_name, outcome, ev_text))

    return counts, issues, duration


def summarize(report_dir: Path, suites: list[str] | None = None) -> str:
    report_dir = Path(report_dir)
    if not report_dir.is_dir():
        return ""

    suite_reports: dict[str, list[Path]] = {}
    for entry in report_dir.iterdir():
        if not entry.is_file():
            continue
        m = re.match(r"^\d{4}-\d{2}-\d{2}-\d{4}-(.+)\.md$", entry.name)
        if not m:
            continue
        suite_reports.setdefault(m.group(1), []).append(entry)

    if not suite_reports:
        return ""

    if suites is not None:
        target_suites = [s for s in dict.fromkeys(suites) if s in suite_reports]
    else:
        target_suites = sorted(suite_reports.keys())

    out_lines: list[str] = []
    for suite in target_suites:
        newest = max(suite_reports[suite], key=lambda p: p.name)
        counts, issues, duration = _parse_report(newest)

        dur_part = f"  {duration}" if duration else ""
        header = (
            f"{suite}  {newest.name}  "
            f"pass={counts['pass']} fail={counts['fail']} "
            f"inconclusive={counts['inconclusive']} skipped={counts['skipped']}"
            f"{dur_part}"
        )
        out_lines.append(header)
        for case, outcome, evidence in issues:
            out_lines.append(f"    {case}: {outcome}: {evidence[:160]}")

    return "\n".join(out_lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Summarize QA bench reports")
    parser.add_argument("--dir", default=Path("runs/qa"), type=Path, help="QA reports directory (default: runs/qa)")
    parser.add_argument("suites", nargs="*", help="Optional suite names to summarize")
    args = parser.parse_args(argv)

    out = summarize(args.dir, suites=args.suites or None)
    if out:
        print(out)


if __name__ == "__main__":
    main()
