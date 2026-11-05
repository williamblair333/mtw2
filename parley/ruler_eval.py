"""Ruler evaluation harness: replay recorded turn scenarios to seat specs, measure
decision time, and count orders kept, rejected, and malformed by the validator.
"""

from __future__ import annotations

import argparse
import concurrent.futures
from datetime import datetime
import json
from pathlib import Path
import statistics
import sys
import time
from typing import Any, Callable

from parley.control import AREAS
from parley.protocol import StateReport
from parley.seats import make_seat
from parley.validate import validate_orders


def evaluate(
    scenarios: list[Path],
    specs: list[str],
    timeout: float,
    seat_factory: Callable[[str], Any] = make_seat,
) -> dict:
    scenarios = [Path(s) for s in scenarios]
    all_runs: list[dict] = []
    specs_summary: dict[str, dict] = {}

    for spec in specs:
        spec_runs: list[dict] = []
        try:
            seat = seat_factory(spec)
        except Exception as e:
            for sc in scenarios:
                spec_runs.append(
                    {
                        "spec": spec,
                        "scenario": sc.name,
                        "seconds": 0.0,
                        "ok": False,
                        "error": str(e)[:200],
                        "kept": 0,
                        "rejected": 0,
                        "malformed": 0,
                        "has_note": False,
                    }
                )
        else:
            def _eval_one(scenario: Path) -> dict:
                start = time.monotonic()
                try:
                    prompt = (scenario / "prompt.txt").read_text(encoding="utf-8")
                    report = StateReport.model_validate_json(
                        (scenario / "state.json").read_text(encoding="utf-8")
                    )
                    orders, _ = seat.decide(
                        prompt,
                        game_id=report.game_id,
                        turn=report.turn,
                        faction=report.faction,
                        timeout=timeout,
                    )
                    took = time.monotonic() - start
                    kept, rejected = validate_orders(report, orders, AREAS)
                    return {
                        "spec": spec,
                        "scenario": scenario.name,
                        "seconds": round(took, 2),
                        "ok": True,
                        "error": "",
                        "kept": len(kept.orders),
                        "rejected": len(rejected),
                        "malformed": len(orders.malformed),
                        "has_note": bool(orders.note and orders.note.strip()),
                    }
                except Exception as ex:
                    took = time.monotonic() - start
                    return {
                        "spec": spec,
                        "scenario": scenario.name,
                        "seconds": round(took, 2),
                        "ok": False,
                        "error": str(ex)[:200],
                        "kept": 0,
                        "rejected": 0,
                        "malformed": 0,
                        "has_note": False,
                    }

            if len(scenarios) > 1:
                with concurrent.futures.ThreadPoolExecutor(max_workers=min(2, len(scenarios))) as executor:
                    spec_runs = list(executor.map(_eval_one, scenarios))
            elif len(scenarios) == 1:
                spec_runs = [_eval_one(scenarios[0])]
            else:
                spec_runs = []

        n_runs = len(spec_runs)
        answered = sum(1 for r in spec_runs if r["ok"])
        kept = sum(r["kept"] for r in spec_runs)
        rejected = sum(r["rejected"] for r in spec_runs)
        malformed = sum(r["malformed"] for r in spec_runs)
        total_orders = kept + rejected + malformed
        legal_rate = (kept / total_orders) if total_orders > 0 else None
        durations = [r["seconds"] for r in spec_runs]
        median_sec = round(float(statistics.median(durations)), 2) if durations else 0.0
        max_sec = round(float(max(durations)), 2) if durations else 0.0

        specs_summary[spec] = {
            "runs": n_runs,
            "answered": answered,
            "kept": kept,
            "rejected": rejected,
            "malformed": malformed,
            "legal_rate": legal_rate,
            "median_seconds": median_sec,
            "max_seconds": max_sec,
        }
        all_runs.extend(spec_runs)

    return {"runs": all_runs, "specs": specs_summary}


def format_table(result: dict) -> str:
    lines = [
        "| spec | answered | legal_rate | kept | rejected | malformed | median s | max s |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for spec, s in result.get("specs", {}).items():
        rate = s.get("legal_rate")
        rate_str = f"{rate * 100:.1f}%" if rate is not None else "None"
        med_s = f"{s.get('median_seconds', 0.0):.1f}s"
        max_s = f"{s.get('max_seconds', 0.0):.1f}s"
        lines.append(
            f"| {spec} | {s.get('answered', 0)}/{s.get('runs', 0)} | {rate_str} | "
            f"{s.get('kept', 0)} | {s.get('rejected', 0)} | {s.get('malformed', 0)} | "
            f"{med_s} | {max_s} |"
        )

    failed = [r for r in result.get("runs", []) if not r.get("ok")]
    if failed:
        lines.append("")
        for r in failed:
            lines.append(f"FAILED {r['spec']} {r['scenario']}: {r['error']}")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate ruler seats on turn scenarios")
    parser.add_argument("--timeout", type=float, default=300.0, help="Per-turn timeout in seconds (default: 300)")
    parser.add_argument("--out", type=Path, default=Path("runs/ruler-eval"), help="Output directory (default: runs/ruler-eval)")
    parser.add_argument("--scenario", action="append", default=[], dest="scenario", help="Scenario folder (repeatable)")
    parser.add_argument("specs", nargs="*", help="Seat specs to evaluate")
    args = parser.parse_args(argv)

    scenarios = [Path(s) for s in args.scenario]
    result = evaluate(scenarios, args.specs, timeout=args.timeout)
    table = format_table(result)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    (out_dir / f"{stamp}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (out_dir / f"{stamp}.md").write_text(table + "\n", encoding="utf-8")

    print(table)
    return 0


if __name__ == "__main__":
    sys.exit(main())
