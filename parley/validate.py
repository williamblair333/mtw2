"""Check an LLM's orders against its own state report before they reach the game."""

from collections.abc import Callable

from parley.protocol import (
    Besiege,
    CedeSettlement,
    MarchOn,
    OrderResult,
    Orders,
    Say,
    SendGold,
    SetStance,
    StateReport,
    Withdraw,
)

MAX_PER_RECIPIENT = 3
MAX_CHARS = 600


def _check(report: StateReport, order, gold_left: int) -> str:
    factions = {f.id for f in report.factions}
    owned = {s.id for s in report.settlements}
    armies = {a.id for a in report.armies}

    target = getattr(order, "to", None)
    if target is not None:
        if target == report.faction:
            return "cannot target own faction"
        if target not in factions:
            return f"unknown faction '{target}'"

    match order:
        case SendGold(amount=amount):
            if amount <= 0:
                return "amount must be positive"
            if amount > gold_left:
                return f"treasury too low ({gold_left} left)"
        case CedeSettlement(settlement=s):
            if s not in owned:
                return f"settlement '{s}' not owned"
        case MarchOn(army=a) | Besiege(army=a) | Withdraw(army=a):
            if a not in armies:
                return f"unknown army '{a}'"
            if isinstance(order, Besiege) and order.settlement in owned:
                return "cannot besiege own settlement"
            if isinstance(order, Withdraw) and order.to_settlement not in owned:
                return f"settlement '{order.to_settlement}' not owned"
        case SetStance():
            pass
    return ""


def validate_orders(report: StateReport, orders: Orders) -> tuple[Orders, list[OrderResult]]:
    kept, rejected = [], []
    gold_left = report.treasury
    for i, order in enumerate(orders.orders):
        reason = _check(report, order, gold_left)
        if reason:
            rejected.append(OrderResult(index=i, type=order.type, ok=False, reason=reason))
            continue
        if isinstance(order, SendGold):
            gold_left -= order.amount
        kept.append(order)
    return orders.model_copy(update={"orders": kept}), rejected


def validate_messages(report: StateReport, messages: list[Say],
                      already_sent: Callable[[str], int],
                      players: set[str] | None = None) -> tuple[list[Say], list[OrderResult]]:
    """Keep messages to the lobby or a known faction, capped per recipient per turn.

    already_sent(to) is how many messages this faction already queued to `to` this turn.
    players, when given, are the factions someone actually plays (LLM seats and humans);
    private messages to anyone else (the game's own AI) would go unread, so they're refused.
    """
    factions = {f.id for f in report.factions}
    kept, rejected, counts = [], [], {}
    for i, m in enumerate(messages):
        text = m.text.strip()
        reason = ""
        if m.to != "lobby" and (m.to == report.faction or m.to not in factions):
            reason = f"unknown faction '{m.to}'"
        elif m.to != "lobby" and players is not None and m.to not in players:
            reason = (f"'{m.to}' is not a player (the game's own AI runs it; nobody reads "
                      f"private messages to it). Players: {', '.join(sorted(players))}")
        elif not text:
            reason = "empty message"
        elif already_sent(m.to) + counts.get(m.to, 0) >= MAX_PER_RECIPIENT:
            reason = f"limit {MAX_PER_RECIPIENT} per turn to {m.to}"
        if reason:
            rejected.append(OrderResult(index=i, type="say", ok=False, reason=reason))
            continue
        counts[m.to] = counts.get(m.to, 0) + 1
        kept.append(Say(to=m.to, text=text[:MAX_CHARS]))
    return kept, rejected
