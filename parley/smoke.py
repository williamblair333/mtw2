"""Send the fixture report to one real seat and print its validated orders.

Usage: python -m parley.smoke <seat-spec> [timeout]
"""

import sys
import time
from pathlib import Path

from parley.prompt import build_prompt
from parley.protocol import StateReport
from parley.seats import make_seat
from parley.validate import validate_orders

FIXTURE = Path(__file__).parent.parent / "tests" / "fixtures" / "state_turn1_venice.json"
PERSONA = ("You are Doge Enrico Dandolo of Venice: old, shrewd and patient. You prefer gold "
           "to blood, and you never forgive a broken oath.")


def main(argv: list[str]) -> int:
    spec, timeout = argv[0], float(argv[1]) if len(argv) > 1 else 120
    report = StateReport.model_validate_json(FIXTURE.read_text())
    seat = make_seat(spec)
    start = time.monotonic()
    orders, _ = seat.decide(build_prompt(report, PERSONA), game_id=report.game_id,
                            turn=report.turn, faction=report.faction, timeout=timeout)
    kept, rejected = validate_orders(report, orders)
    print(f"{seat.name}: {time.monotonic() - start:.1f}s")
    print(kept.model_dump_json(indent=2))
    for r in rejected:
        print(f"REJECTED order {r.index} ({r.type}): {r.reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
