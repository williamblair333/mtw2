"""God view: each LLM ruler's private notes, orders and messages, turn by turn.

For testing and spectating. These notes are private to each ruler; reading them as a
player is spying.
"""

import json
from pathlib import Path


def _order_line(o: dict, result: dict | None) -> str:
    target = o.get("to") or o.get("target_settlement") or o.get("settlement") or o.get("to_settlement")
    what = o.get("army") or ""
    extra = o.get("stance") or o.get("amount") or ""
    parts = [o["type"], what, f"→ {target}" if target else "", str(extra) if extra else ""]
    status = ""
    if result is not None:
        status = " [done]" if result.get("ok") else f" [rejected: {result.get('reason')}]"
    return "    " + " ".join(p for p in parts if p) + status


def format_notes(turn_root: Path, game_id: str, faction: str | None = None, last: int | None = None) -> str:
    game_dir = Path(turn_root) / game_id
    turns = sorted(game_dir.glob("turn-*")) if game_dir.is_dir() else []
    turns = [t for t in turns if any((d / "orders.json").exists() for d in t.iterdir() if d.is_dir())]
    if last:
        turns = turns[-last:]
    if not turns:
        return f"{game_id}: no turns answered yet\n"
    out = []
    for t in turns:
        out.append(f"=== Turn {int(t.name.removeprefix('turn-'))} ===")
        for d in sorted(p for p in t.iterdir() if p.is_dir()):
            if faction and d.name != faction or not (d / "orders.json").exists():
                continue
            orders = json.loads((d / "orders.json").read_text())
            results = json.loads((d / "results.json").read_text()) if (d / "results.json").exists() else []
            by_index = {r["index"]: r for r in results}
            out.append(f"{d.name}: {orders.get('note') or '(no note)'}")
            for i, o in enumerate(orders.get("orders", [])):
                out.append(_order_line(o, by_index.get(i)))
            if (d / "messages.json").exists():
                for m in json.loads((d / "messages.json").read_text()).get("kept", []):
                    where = "lobby" if m["to"] == "lobby" else f"{m['to']} (private)"
                    out.append(f"    → {where}: {m['text']}")
        out.append("")
    return "\n".join(out) + "\n"
