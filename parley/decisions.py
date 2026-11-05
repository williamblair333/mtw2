"""Decision log recording for Parley ruler decisions."""

from __future__ import annotations

from jigsaw import Decision, DecisionLog
from parley.protocol import OrderResult, Orders, StateReport


def record_turn(
    log: DecisionLog,
    report: StateReport,
    orders: Orders,
    kept: Orders,
    rejected: list[OrderResult],
    brain: str,
) -> int:
    """Record ruler decisions for a turn into the decision log."""
    situation = (
        f"{report.faction} turn {report.turn}: treasury {report.treasury}, "
        f"{len(report.settlements)} settlements, {len(report.armies)} armies"
    )
    escalated_because = f"LLM seat ({brain}): asked every turn, no gate yet"
    count = 0

    source = orders.source_index
    for i, order in enumerate(orders.orders):
        idx = source[i] if (source and i < len(source)) else i
        rej = next((r for r in rejected if r.type != "say" and r.index == idx), None)
        legality = (
            [{"ok": False, "reason": rej.reason, "index": idx}]
            if rej is not None
            else [{"ok": True, "index": idx}]
        )

        d = Decision(
            game=report.game_id,
            turn=report.turn,
            actor=report.faction,
            kind=order.type,
            situation=situation,
            rung=7,
            escalated_because=escalated_because,
            choice=order.model_dump_json(),
            primitives=[order.model_dump()],
            legality=legality,
        )
        log.record(d)
        count += 1

    for r in orders.malformed:
        d = Decision(
            game=report.game_id,
            turn=report.turn,
            actor=report.faction,
            kind=r.type,
            situation=situation,
            rung=7,
            escalated_because=escalated_because,
            choice="(malformed)",
            primitives=[],
            legality=[{"ok": False, "reason": r.reason, "index": r.index}],
        )
        log.record(d)
        count += 1

    if not orders.orders and not orders.malformed:
        d = Decision(
            game=report.game_id,
            turn=report.turn,
            actor=report.faction,
            kind="turn",
            situation=situation,
            rung=7,
            escalated_because=escalated_because,
            choice="no orders",
        )
        log.record(d)
        count += 1

    return count


def record_outcomes(
    log: DecisionLog,
    game: str,
    faction: str,
    turn: int,
    results: list[OrderResult],
    now_turn: int,
) -> int:
    """Record outcomes for decisions from a previous turn into the decision log."""
    if log is None:
        return 0

    results_by_index: dict[int, OrderResult] = {}
    for r in results:
        idx = getattr(r, "index", None) if not isinstance(r, dict) else r.get("index")
        if idx is not None:
            results_by_index[idx] = r

    count = 0
    decisions = log.query(game=game, actor=faction, since_turn=turn)
    for d in decisions:
        if d.turn != turn:
            continue
        if not d.legality or not isinstance(d.legality[0], dict):
            continue
        idx = d.legality[0].get("index")
        if idx is None or idx not in results_by_index:
            continue

        res = results_by_index[idx]
        ok = getattr(res, "ok", None) if not isinstance(res, dict) else res.get("ok")
        reason = getattr(res, "reason", "") if not isinstance(res, dict) else res.get("reason", "")

        outcome = "done" if ok else f"refused: {reason}"
        if d.id is not None:
            log.set_outcome(d.id, outcome, now_turn)
            count += 1

    return count
