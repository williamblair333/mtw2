"""Replay one real turn's prompt to seats and compare their answers: time, orders kept, rejected,
malformed, and whether a note and plan came back. Nothing reaches the game.

Usage: python -m parley.bench <turn dir> <timeout> <seat spec>...
  <turn dir> is a faction's folder of a played turn (it holds prompt.txt and state.json).
Live, 2026-10-25: England's 45 KB turns showed gemini-4-argon-medium answering in 28-95 s with
nothing rejected, and -high running past 300 s (the empty answers once blamed on Gemini)."""

import sys
import time
from pathlib import Path

from parley.control import AREAS
from parley.protocol import StateReport
from parley.seats import make_seat
from parley.validate import validate_orders


def bench(turn_dir: Path, spec: str, timeout: float) -> str:
    prompt = (turn_dir / "prompt.txt").read_text()
    report = StateReport.model_validate_json((turn_dir / "state.json").read_text())
    start = time.monotonic()
    try:
        orders, _ = make_seat(spec).decide(prompt, game_id=report.game_id, turn=report.turn,
                                           faction=report.faction, timeout=timeout)
    except Exception as e:  # a seat failing is a result here, not a crash
        return f"{spec}: {time.monotonic() - start:.0f}s FAILED {type(e).__name__}: {str(e)[:300]}"
    took = time.monotonic() - start
    kept, rejected = validate_orders(report, orders, AREAS)  # every area: the prompt already set the seat's
    lines = [f"{spec}: {took:.0f}s, {len(kept.orders)} kept, {len(rejected)} rejected, "
             f"{len(orders.malformed)} malformed, note {len(orders.note)} chars, plan {len(orders.plan)} chars"]
    lines += [f"    {o.type}: {o.model_dump_json(exclude_defaults=True)[:150]}" for o in kept.orders]
    lines += [f"    REJECTED {r.index} {r.type}: {r.reason[:150]}" for r in rejected]
    lines.append("    NOTE: " + orders.note[:400].replace("\n", " "))
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    turn_dir, timeout = Path(argv[0]).expanduser(), float(argv[1])
    for spec in argv[2:]:
        print(bench(turn_dir, spec, timeout), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
