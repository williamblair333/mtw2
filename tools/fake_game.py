"""Stand-in for the game: writes a state report per LLM faction per turn, waits for
orders, writes results, moves on. Exits 0 after the last turn, 1 on timeout.

Usage: python tools/fake_game.py --root runs/turns --game example --factions venice,milan --turns 3
"""

import argparse
import json
import sys
import time
from pathlib import Path

from parley.bridge import TurnDir, atomic_write
from parley.protocol import OrderResult, Orders

FIXTURE = Path(__file__).parent.parent / "tests" / "fixtures" / "state_turn1_venice.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--game", required=True)
    ap.add_argument("--factions", required=True)
    ap.add_argument("--turns", type=int, default=3)
    ap.add_argument("--wait", type=float, default=300)
    args = ap.parse_args()

    turns = TurnDir(args.root)
    base = json.loads(FIXTURE.read_text())
    others = [{"id": "hre", "name": "Holy Roman Empire", "stance": "war"}]
    factions = args.factions.split(",")
    last: dict[str, list] = {f: [] for f in factions}
    for turn in range(1, args.turns + 1):
        for faction in factions:
            d = turns.path_for(args.game, turn, faction)
            d.mkdir(parents=True, exist_ok=True)
            report = {**base, "game_id": args.game, "turn": turn, "year": 1079 + turn,
                      "faction": faction, "last_results": last[faction],
                      "factions": [{"id": f, "name": f.title(), "stance": "peace"}
                                   for f in factions if f != faction] + others}
            atomic_write(d / "state.json", json.dumps(report, indent=2))
            print(f"turn {turn}: {faction} waiting for orders", flush=True)
            deadline = time.monotonic() + args.wait
            while not (d / "orders.json").exists():
                if time.monotonic() > deadline:
                    print(f"turn {turn}: {faction} timed out", file=sys.stderr)
                    return 1
                time.sleep(0.2)
            orders = Orders.model_validate_json((d / "orders.json").read_text())
            results = [OrderResult(index=i, type=o.type, ok=True) for i, o in enumerate(orders.orders)]
            atomic_write(d / "results.json", json.dumps([r.model_dump() for r in results], indent=2))
            last[faction] = [r.model_dump() for r in results]
            print(f"turn {turn}: {faction} applied {len(results)} orders", flush=True)
    print("done", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
