"""Trends across recent turns: rejections rising, rulers slowing, faction shrinking."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import sys
from typing import Any


# refused orders of ONE order type in the newest 3 turns before an applied-share fall is reported: a broken order
# type refuses the same type again and again, a ruler's mistakes are spread out (live 11-22: England's 1-4 orders
# a turn, refusals a merge over 20 units, a move across the sea, two moves onto sea, read "92% to 56%" twice)
MIN_REFUSED = 3
TOWN_LOSS_SMALL = 20  # below this many towns, any town lost in the window is reported
TOWN_LOSS_SHARE = 0.05  # at or above it, only a loss of this share of the towns (5% of 62 is 3)


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _turn_num(path: Path) -> int:
    name = path.name.removeprefix("turn-")
    try:
        return int(name)
    except ValueError:
        return -1


class TurnRow(dict):
    """Per-turn trend metrics with dict and attribute access."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)


class FactionTrends(list):
    """List of TurnRows that also provides dict access to rows and alerts."""

    def __init__(self, rows: list[TurnRow], alerts: list[str]):
        super().__init__(rows)
        self.rows = rows
        self.alerts = alerts

    def __getitem__(self, item: Any) -> Any:
        if item in ("rows", "turns"):
            return self.rows
        if item == "alerts":
            return self.alerts
        return super().__getitem__(item)

    def get(self, key: str, default: Any = None) -> Any:
        if key in ("rows", "turns"):
            return self.rows
        if key == "alerts":
            return self.alerts
        return default

    def __contains__(self, item: Any) -> bool:
        if item in ("rows", "alerts", "turns"):
            return True
        return super().__contains__(item)

    def keys(self) -> list[str]:
        return ["rows", "alerts"]

    def items(self) -> list[tuple[str, Any]]:
        return [("rows", self.rows), ("alerts", self.alerts)]


def trends(turn_root: Path, game_id: str, last: int = 10) -> dict[str, FactionTrends]:
    game_dir = Path(turn_root).expanduser() / game_id
    if not game_dir.is_dir():
        return {}

    turn_dirs = sorted(
        [p for p in game_dir.glob("turn-*") if p.is_dir() and _turn_num(p) >= 0],
        key=_turn_num,
    )

    factions = sorted({p.name for t in turn_dirs for p in t.iterdir() if p.is_dir()})
    # a QA run parks the campaign between a report and its answer; the ruler starts at the restore
    # (11-05: run 10's turn-5 "answer" took 5638 s, the full bench pass in between)
    try:
        restored = (Path(turn_root).expanduser() / "qa.last_restore").stat().st_mtime
    except OSError:
        restored = None

    result: dict[str, FactionTrends] = {}

    for faction in factions:
        answered_rows: list[TurnRow] = []
        # answered but not applied yet: the results come at the next turn start, so the newest row reads
        # N orders, 0 applied (live 11-11 13:55, "france: applied share fell 42 points (78% to 36%)")
        pending: set[int] = set()
        for t in turn_dirs:
            fdir = t / faction
            orders_path = fdir / "orders.json"
            if not orders_path.is_file():
                continue

            orders_data = _load_json(orders_path) or {}
            state_path = fdir / "state.json"
            state_data = _load_json(state_path) or {}
            results_list = _load_json(fdir / "results.json") or []
            rejected_list = _load_json(fdir / "rejected.json") or []

            applied_ok = sum(1 for r in results_list if r.get("ok"))
            refused = sum(1 for r in results_list if not r.get("ok")) + len(rejected_list)
            refused_types: dict[str, int] = {}
            for r in [x for x in results_list if not x.get("ok")] + rejected_list:
                kind = str(r.get("type") or "?")
                refused_types[kind] = refused_types.get(kind, 0) + 1
            orders_count = max(
                len(orders_data.get("orders", [])) + len(rejected_list),
                applied_ok + refused,
            )

            try:
                s_mtime = state_path.stat().st_mtime
                # the ruler's own time starts at its prompt: live 11-21 England's turns spent 22-28 s
                # reading popups between state.json and prompt.txt, and a 2-order turn's 47 s read as
                # 24 s an order against the ruler's 12 (the turn log's 24 s answer)
                prompt_path = fdir / "prompt.txt"
                if prompt_path.is_file():
                    s_mtime = max(s_mtime, prompt_path.stat().st_mtime)
                o_mtime = orders_path.stat().st_mtime
                if restored is not None and s_mtime < restored < o_mtime:
                    s_mtime = restored
                answer_seconds = round(o_mtime - s_mtime, 1)
            except OSError:
                answer_seconds = 0.0

            towns = len(state_data.get("settlements", []))
            armies = len(state_data.get("armies", []))
            late = (fdir / "late.txt").is_file()
            if not (fdir / "results.json").is_file() and not late:
                pending.add(_turn_num(t))
            note = str(orders_data.get("note") or "")
            seat_error = note.startswith("seat error")

            row = TurnRow({
                "turn": _turn_num(t),
                "orders": orders_count,
                "applied_ok": applied_ok,
                "refused": refused,
                "refused_types": refused_types,
                "answer_seconds": answer_seconds,
                "towns": towns,
                "armies": armies,
                "late": late,
                "seat_error": seat_error,
            })
            answered_rows.append(row)

        if not answered_rows:
            continue

        window = answered_rows[-last:]
        alerts: list[str] = []

        scored = [r for r in window if r["turn"] not in pending]
        if len(scored) >= 4:
            earlier = scored[:-3]
            newest = scored[-3:]

            earlier_orders = sum(r["orders"] for r in earlier)
            earlier_ok = sum(r["applied_ok"] for r in earlier)
            earlier_share = earlier_ok / earlier_orders if earlier_orders else 0.0

            newest_orders = sum(r["orders"] for r in newest)
            newest_ok = sum(r["applied_ok"] for r in newest)
            newest_share = newest_ok / newest_orders if newest_orders else 0.0

            drop = (earlier_share - newest_share) * 100
            # a fall needs refusals to stand on: one refused order among a ruler's 1-2 a turn made a 20-point
            # "fall" (live 11-11 17:04, an attack target out of sight); a broken order type refuses many
            by_type: dict[str, int] = {}
            for r in newest:
                for kind, n in r["refused_types"].items():
                    by_type[kind] = by_type.get(kind, 0) + n
            if drop >= 20.0 - 1e-6 and max(by_type.values(), default=0) >= MIN_REFUSED:
                alerts.append(
                    f"applied share fell {drop:.0f} points ({earlier_share * 100:.0f}% to {newest_share * 100:.0f}%)"
                )

            # per order: a ruler answering a bigger turn isn't slower (live 11-20: France's 27-29 order
            # turns took 74-87 s, 1.8-3.0 s an order against 2.1-5.6 s before, and alerted on raw seconds).
            # The 60 s floor stays on the raw answer time: only a seat near its time limit is worth a wake
            raw_med = statistics.median(r["answer_seconds"] for r in newest)
            earlier_med = statistics.median(r["answer_seconds"] / max(r["orders"], 1) for r in earlier)
            newest_med = statistics.median(r["answer_seconds"] / max(r["orders"], 1) for r in newest)
            if raw_med > 60 and newest_med > 0 and (earlier_med <= 0 or newest_med > 1.5 * earlier_med):
                ratio = (newest_med / earlier_med) if earlier_med > 0 else float("inf")
                alerts.append(
                    f"median answer time per order slowed to {newest_med:.1f}s (earlier {earlier_med:.1f}s, {ratio:.1f}x)"
                )

        # a big faction trades towns in every war: live 11-20 France at 59->58 and 62->60 woke the watch
        # three times in an hour. Any loss counts below TOWN_LOSS_SMALL towns; above, a TOWN_LOSS_SHARE cut
        if len(window) >= 2 and window[-1]["towns"] < window[0]["towns"]:
            first, last = window[0]["towns"], window[-1]["towns"]
            if first < TOWN_LOSS_SMALL or (first - last) >= max(1, round(TOWN_LOSS_SHARE * first)):
                alerts.append(f"towns fell from {first} to {last}")

        newest = window[-3:]
        for r in newest:
            if r["late"]:
                alerts.append(f"late answer on turn {r['turn']}")
            if r["seat_error"]:
                alerts.append(f"seat error on turn {r['turn']}")

        result[faction] = FactionTrends(window, alerts)

    return result


def format_trends(data: dict[str, FactionTrends]) -> str:
    if not data:
        return "no alerts"

    lines: list[str] = []

    for faction, f_data in data.items():
        lines.append(f"=== {faction} ===")
        lines.append("| turn | orders | applied_ok | refused | answer_s | towns | armies | late | seat_error |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for r in f_data.rows:
            ans = f"{r['answer_seconds']:.1f}s"
            lines.append(
                f"| {r['turn']} | {r['orders']} | {r['applied_ok']} | {r['refused']} | {ans} | "
                f"{r['towns']} | {r['armies']} | {r['late']} | {r['seat_error']} |"
            )
        alerts = f_data.alerts
        if alerts:
            lines.append("Alerts:")
            for a in alerts:
                lines.append(f"- {a}")
        else:
            lines.append("no alerts")
        lines.append("")

    return "\n".join(lines).strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Trends across recent turns")
    parser.add_argument("turn_root", type=Path, help="Turn root directory")
    parser.add_argument("game_id", help="Game ID")
    parser.add_argument("--last", type=int, default=10, help="Number of turns (default: 10)")
    parser.add_argument("--alerts-only", action="store_true",
                        help="one line per alert, '<faction>: <alert>' (scripts/campaign_watch.sh's TREND)")
    args = parser.parse_args(argv)

    data = trends(args.turn_root.expanduser(), args.game_id, last=args.last)
    if args.alerts_only:
        for faction, ft in sorted(data.items()):
            for alert in ft.alerts:
                print(f"{faction}: {alert}")
        return 0
    text = format_trends(data)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
