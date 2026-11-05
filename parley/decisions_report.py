"""Read-only report over a game's decision log."""

from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from jigsaw import DecisionLog
from parley.config import load_config


def summarize(log: Any, game: str, last: int = 20) -> str:
    """Summarize decisions recorded for a game in the decision log."""
    decisions = log.query(game=game)
    if not decisions:
        return f"{game}: no decisions recorded\n"

    total = len(decisions)
    min_turn = min(d.turn for d in decisions)
    max_turn = max(d.turn for d in decisions)

    out = [f"{game}: {total} decisions, turns {min_turn}..{max_turn}", ""]

    out.append("By rung:")
    by_rung = Counter(d.rung for d in decisions)
    for rung in sorted(by_rung):
        count = by_rung[rung]
        pct = count * 100 / total
        pct_str = f"{pct:.0f}%" if pct == int(pct) else f"{pct:.1f}%"
        out.append(f"  rung {rung}: {count} ({pct_str})")
    out.append("")

    out.append("By kind:")
    by_kind: dict[str, list[Any]] = defaultdict(list)
    for d in decisions:
        by_kind[d.kind].append(d)
    for kind in sorted(by_kind):
        items = by_kind[kind]
        count = len(items)
        outcomes = sum(1 for d in items if d.outcome is not None and d.outcome != "")
        out.append(f"  {kind}: {count} ({outcomes} with outcome)")
    out.append("")

    out.append("By actor:")
    by_actor = Counter(d.actor for d in decisions)
    for actor in sorted(by_actor):
        out.append(f"  {actor}: {by_actor[actor]}")
    out.append("")

    latest = decisions[:max(0, last)]
    out.append(f"Latest {len(latest)}:")
    for d in latest:
        choice = (d.choice or "").replace("\n", " ").strip()
        line = f"  t{d.turn} {d.actor} {d.kind} rung {d.rung}: {choice}"
        if d.outcome:
            line += f" -> {d.outcome.replace(chr(10), ' ').strip()}"
        if d.escalated_because:
            line += f" (escalated: {d.escalated_because.replace(chr(10), ' ').strip()})"
        out.append(line[:160])

    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m parley.decisions_report", description=__doc__)
    ap.add_argument("game", type=Path, help="the game's .toml")
    ap.add_argument("--last", type=int, default=20, help="how many of the newest decisions to list")
    args = ap.parse_args(argv)

    config = load_config(args.game.expanduser())
    db_path = config.turn_root / f"{config.game_id}.decisions.db"
    if not db_path.exists():  # DecisionLog would create it
        print(f"no decision log at {db_path}")
        return 0

    with DecisionLog(db_path) as log:
        print(summarize(log, config.game_id, last=args.last), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
