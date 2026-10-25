"""Campaign report: what every ruler did over a whole game, read from the turn folders.

For test runs: who answered, who was late, which order types were tried and how they
fared, and why orders failed. Mechanical counts only; it doesn't judge whether a ruler
kept its word.
"""

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import get_args

from parley.protocol import Order

ORDER_TYPES = [m.model_fields["type"].default for m in get_args(get_args(Order)[0])]


def _load(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def campaign_report(turn_root: Path, game_id: str) -> str:
    game_dir = Path(turn_root) / game_id
    turns = sorted(game_dir.glob("turn-*")) if game_dir.is_dir() else []
    rulers = defaultdict(lambda: {"reported": 0, "answered": 0, "late": 0, "errors": 0,
                                  "treasury": [], "settlements": [], "public": 0, "private": 0})
    issued, done, failed, refused = Counter(), Counter(), Counter(), Counter()
    reasons = []
    for t in turns:
        turn = int(t.name.removeprefix("turn-"))
        for d in sorted(p for p in t.iterdir() if p.is_dir()):
            r = rulers[d.name]
            if (state := _load(d / "state.json")) is not None:
                r["reported"] += 1
                r["treasury"].append(state.get("treasury", 0))
                r["settlements"].append(len(state.get("settlements", [])))
            r["late"] += (d / "late.txt").exists()
            if (orders := _load(d / "orders.json")) is not None:
                r["answered"] += 1
                r["errors"] += (orders.get("note") or "").startswith("seat error")
                for o in orders.get("orders", []):
                    issued[o.get("type")] += 1
            for res in _load(d / "results.json") or []:
                (done if res.get("ok") else failed)[res.get("type")] += 1
                if not res.get("ok"):
                    reasons.append(f"{d.name} turn {turn} {res.get('type')} (game): {res.get('reason')}")
            for res in _load(d / "rejected.json") or []:
                issued[res.get("type")] += 1
                refused[res.get("type")] += 1
                reasons.append(f"{d.name} turn {turn} {res.get('type')} (checker): {res.get('reason')}")
            for m in (_load(d / "messages.json") or {}).get("kept", []):
                r["public" if m.get("to") == "lobby" else "private"] += 1
    if not rulers:
        return f"{game_id}: no turns played yet\n"

    def span(xs):
        return f"{xs[0]} → {xs[-1]}" if xs else "?"

    out = [f"# Campaign report: {game_id}", "",
           f"Turns {int(turns[0].name[5:])}–{int(turns[-1].name[5:])}.", "",
           "| ruler | reported | answered | late | seat errors | treasury | settlements | messages |",
           "|---|---|---|---|---|---|---|---|"]
    for name, r in sorted(rulers.items()):
        talk = (f"{r['public']} public, {r['private']} private"
                if r["public"] or r["private"] else "none")
        out.append(f"| {name} | {r['reported']} | {r['answered']} | {r['late']} | {r['errors']} | "
                   f"{span(r['treasury'])} | {span(r['settlements'])} | {talk} |")
    out += ["", "## Orders", "",
            "| order | issued | done | failed in game | rejected by checker |", "|---|---|---|---|---|"]
    for kind in [k for k in ORDER_TYPES if issued[k]] + sorted(k for k in issued if k not in ORDER_TYPES):
        out.append(f"| {kind} | {issued[kind]} | {done[kind]} | {failed[kind]} | {refused[kind]} |")
    never = [k for k in ORDER_TYPES if not issued[k]]
    out += ["", "Never tried: " + (", ".join(never) if never else "none"), ""]
    out += ["## Why orders failed", ""] + ([f"- {x}" for x in reasons] or ["- nothing failed"])
    return "\n".join(out) + "\n"
