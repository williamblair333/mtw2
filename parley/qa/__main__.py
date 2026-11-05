"""CLI entry point: python -m parley.qa run <suite|all> --real <game.toml> | restore --real <game.toml>
| bench-save start|record --real <game.toml> [--from <save>] | after-relaunch --turn-root <dir> --log-offset <bytes>."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from parley.qa.runner import (
    QARunError,
    bench_save_record,
    bench_save_start,
    format_report,
    restore,
    resume_real_after_relaunch,
    run_suite,
)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="parley.qa")
    sub = ap.add_subparsers(dest="cmd", required=True)

    run_p = sub.add_parser("run", help="run a QA bench suite (or 'all') and restore the real campaign")
    run_p.add_argument("suite", help="suite name (e.g. smoke, covert, all)")
    run_p.add_argument("--real", required=True, type=Path, help="path to the real game TOML (e.g. games/local/<name>.toml)")
    run_p.add_argument("--case", action="append", dest="cases", metavar="NAME",
                       help="run only this case of the suite (repeatable); smoke still runs first")
    run_p.add_argument("--no-smoke", action="store_true",
                       help="skip smoke for instant cases alone, if a run's smoke suite passed in the last 30 min")
    run_p.add_argument("--kind", choices=["all", "instant"], default="all",
                       help="instant: only the instant cases, turn cases reported as skipped; no QA turn "
                            "loop, and X input (clicks) refused for the whole run; a relaunch makes no clicks")

    rest_p = sub.add_parser("restore", help="restore the real campaign from its kept save")
    rest_p.add_argument("--real", required=True, type=Path, help="path to the real game TOML (e.g. games/local/<name>.toml)")

    bench_p = sub.add_parser(
        "bench-save",
        help="make the bench save: 'start' parks the real run, 'record' keeps the new campaign's save and restores",
    )
    bench_p.add_argument("step", choices=["start", "record"])
    bench_p.add_argument("--real", required=True, type=Path, help="path to the real game TOML (e.g. games/local/<name>.toml)")
    bench_p.add_argument("--from", dest="source", type=Path, default=None,
                         help="record: the save to keep (default: the game's newest own save, the turn-start "
                              "autosave). With no `start` before it: the no-menu path, which parks the real "
                              "run, loads this save through EOP, reads its turn and faction, records and "
                              "restores, with no clicks")
    bench_p.add_argument("--faction", default="england", help="record: the bench faction (default england)")

    after_p = sub.add_parser(
        "after-relaunch",
        help="after relaunch_game.sh --clicks: load the restored keep save if Continue took the QA game's",
    )
    after_p.add_argument("--turn-root", required=True, type=Path, help="the game's parley_turns dir")
    after_p.add_argument("--log-offset", type=int, default=0, help="bridge log size before the relaunch")

    args = ap.parse_args(argv)
    try:
        if args.cmd == "after-relaunch":
            print(f"relaunch: {resume_real_after_relaunch(args.turn_root, log_offset=args.log_offset)}")
            return 0
        if args.cmd == "run":
            extra: dict = {}
            if args.cases:
                extra["cases"] = args.cases
            if args.no_smoke:
                extra["no_smoke"] = True
            if args.kind != "all":
                extra["kind"] = args.kind
            results, report_path = run_suite(args.suite, args.real, **extra)
            print(report_path.read_text(encoding="utf-8"), end="")
            print(f"wrote {report_path}")
            return 1 if any(r.outcome == "fail" for r in results) else 0
        if args.cmd == "bench-save":
            if args.step == "start":
                print(bench_save_start(args.real))
            else:
                b = bench_save_record(args.real, source=args.source, faction=args.faction)
                print(f"bench save {b.path} recorded: {b.faction}, turn {b.turn}, sha256 {b.sha256}; "
                      f"the real campaign is restored")
            return 0
        if args.cmd == "restore":
            if restore(args.real):
                print(f"restored {args.real}")
            return 0
    except QARunError as e:
        if args.cmd == "run":
            if getattr(e, "results", None) is not None:
                print(format_report(args.suite, e.results), end="")
            if getattr(e, "report_path", None) is not None:
                print(f"wrote {e.report_path}")
        print(f"qa error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
