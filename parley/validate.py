"""Check an LLM's orders against its own state report before they reach the game."""

from collections.abc import Callable

from parley.control import ORDER_AREA, PRESETS
from parley.protocol import (
    Assassinate,
    Attack,
    Besiege,
    Blockade,
    Board,
    Land,
    Bribe,
    Build,
    Marry,
    MergeArmies,
    MergeUnits,
    Disband,
    MoveAgent,
    MoveArmy,
    Recruit,
    Retrain,
    SetTax,
    Sabotage,
    Spy,
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
        case Assassinate() | Spy() | Bribe() | Sabotage():
            return _check_agent_order(report, order)
        case Build() | Recruit():
            mine = {s.id: s for s in report.settlements}
            s = mine.get(order.settlement)
            if s is None:
                return f"settlement '{order.settlement}' not owned"
            if isinstance(order, Build) and order.building in s.queue:
                return f"'{order.building}' is already in {s.id}'s queue; it will be built without a second order"
            if isinstance(order, Build):
                offer = next((b for b in s.can_build if b.building == order.building), None)
                if offer is None:
                    return (f"{s.id} can't build '{order.building}' now (can: "
                            f"{', '.join(b.building for b in s.can_build) or 'nothing'})")
            else:
                offer = next((u for u in s.can_recruit if u.unit == order.unit), None)
                if offer is None:
                    return (f"{s.id} can't recruit '{order.unit}' now (can: "
                            f"{', '.join(u.unit for u in s.can_recruit) or 'nothing'})")
            if offer.cost > gold_left:
                return f"treasury too low ({gold_left} left, needs {offer.cost})"
        case SetTax(settlement=s):
            if s not in owned:
                return f"settlement '{s}' not owned"
        case Retrain(settlement=s):
            if s not in owned:
                return f"settlement '{s}' not owned"
        case MoveAgent(agent=g) | Marry(agent=g):
            agent = next((x for x in report.agents if x.id == g), None)
            if agent is None:
                return f"unknown agent '{g}' (not one of yours)"
            if isinstance(order, MoveAgent):
                return _off_map(report, order.x, order.y)
            if agent.kind != "princess":
                return f"'{g}' is a {agent.kind}; only a princess can marry"
            if order.target not in {e.id for e in report.visible_enemies}:
                return f"target '{order.target}' is not in sight (marry a general from FOREIGN ARMIES IN SIGHT)"
        case Board(who=w, fleet=f):
            mine = {x.id: x for x in report.armies}
            if f not in mine or not mine[f].is_fleet:
                return f"'{f}' is not one of your fleets"
            if w not in mine and w not in {a.id for a in report.agents}:
                return f"unknown army or agent '{w}'"
            if w in mine and mine[f].carrying:
                return f"'{f}' already carries an army (one per fleet)"
        case Land(army=a):
            mine = {x.id: x for x in report.armies}
            if a not in mine:
                return f"unknown army '{a}'"
            if not mine[a].aboard:
                return f"'{a}' is not aboard a fleet"
            return _off_map(report, order.x, order.y)
        case Blockade(fleet=f, settlement=s):
            mine = {x.id: x for x in report.armies}
            if f not in mine or not mine[f].is_fleet:
                return f"'{f}' is not one of your fleets"
            if s not in {x.id for x in report.nearby_settlements}:
                return f"settlement '{s}' is not in sight"
        case MergeArmies(army=a, into=b):
            mine = {x.id: x for x in report.armies}
            if a not in mine or b not in mine:
                return f"unknown army '{a if a not in mine else b}'"
            if a == b:
                return "an army can't merge into itself"
            if mine[a].units + mine[b].units > 20:
                return f"together they'd be {mine[a].units + mine[b].units} units; an army holds at most 20"
        case MergeUnits(army=a):
            if a not in {x.id for x in report.armies}:
                return f"unknown army '{a}'"
        case Disband(army=a, unit=u, count=n):
            mine = {x.id: x for x in report.armies}
            if a not in mine:
                return f"unknown army '{a}'"
            if n < 1:
                return "count must be at least 1"
            if mine[a].troops and u not in {t.type for t in mine[a].troops}:
                return f"'{a}' has no '{u}' (its troops: {', '.join(sorted({t.type for t in mine[a].troops}))})"
        case MoveArmy(army=a) | Attack(army=a):
            # move_army also takes a general's own name: he steps out alone (live: Symond, who
            # leads London's garrison, was refused here as an unknown army)
            generals = {p.name for p in report.family if p.alive and p.kind == "general"}
            if a not in armies and not (isinstance(order, MoveArmy) and a in generals):
                return f"unknown army '{a}'"
            if isinstance(order, MoveArmy) and (off := _off_map(report, order.x, order.y)):
                return off
            if isinstance(order, Attack) and order.target not in {e.id for e in report.visible_enemies}:
                return f"target '{order.target}' is not in sight (use an id from FOREIGN ARMIES IN SIGHT)"
    return ""


def _off_map(report: StateReport, x: int, y: int) -> str:
    if report.map_width and report.map_height and not (0 <= x < report.map_width and 0 <= y < report.map_height):
        return f"({x},{y}) is off the map (0..{report.map_width - 1}, 0..{report.map_height - 1})"
    return ""


def cost(report: StateReport, order) -> int:
    """Gold an order spends: what the checker deducts before checking the next order."""
    if isinstance(order, SendGold):
        return order.amount
    s = next((s for s in report.settlements if s.id == getattr(order, "settlement", None)), None)
    if s and isinstance(order, Build):
        return next((b.cost for b in s.can_build if b.building == order.building), 0)
    if s and isinstance(order, Recruit):
        return next((u.cost for u in s.can_recruit if u.unit == order.unit), 0)
    return 0


AGENT_KIND = {"assassinate": "assassin", "spy": "spy", "bribe": "diplomat", "sabotage": "assassin"}


def _check_agent_order(report: StateReport, order) -> str:
    """Your own agent, of the right kind, against something you can actually see."""
    mine = {a.id: a for a in report.agents}
    agent = mine.get(order.agent)
    if agent is None:
        return f"unknown agent '{order.agent}' (not one of yours)"
    need = AGENT_KIND[order.type]
    if agent.kind != need:
        return f"'{order.agent}' is a {agent.kind}, not an {need}" if need[0] in "aeiou" else \
            f"'{order.agent}' is a {agent.kind}, not a {need}"
    # ids only: the bridge resolves targets by id, and a leader's name may belong to two armies
    characters = {a.id for a in report.visible_enemies} | {a.id for a in report.seen_agents}
    settlements = {s.id for s in report.nearby_settlements}
    target = order.settlement if isinstance(order, Sabotage) else order.target
    allowed = {"assassinate": characters, "spy": characters | settlements,
               "bribe": characters | settlements, "sabotage": settlements}[order.type]
    if target not in allowed:
        return f"target '{target}' is not in sight (use a name from your sight lists)"
    return ""


def validate_orders(report: StateReport, orders: Orders,
                    areas: tuple[str, ...] = PRESETS["ruler"]) -> tuple[Orders, list[OrderResult]]:
    """areas: the seat's control areas; orders outside them are refused."""
    kept, rejected = [], []
    gold_left = report.treasury
    busy = set()  # agents already given an order: the game lets each act once a turn
    for i, order in enumerate(orders.orders):
        area = ORDER_AREA.get(order.type)
        if area not in areas:
            reason = f"'{order.type}' is {area}, not yours to command (yours: {', '.join(areas)})"
        else:
            reason = _check(report, order, gold_left)
        agent = getattr(order, "agent", None)
        if not reason and agent in busy:
            reason = f"'{agent}' already has an order this turn"
        if reason:
            rejected.append(OrderResult(index=i, type=order.type, ok=False, reason=reason))
            continue
        gold_left -= cost(report, order)
        if agent is not None:
            busy.add(agent)
        if isinstance(order, Attack):
            target = next(e for e in report.visible_enemies if e.id == order.target)
            order = order.model_copy(update={"target_faction": target.faction})
        kept.append(order)
    return orders.model_copy(update={"orders": kept}), rejected


def validate_messages(report: StateReport, messages: list[Say],
                      already_sent: Callable[[str], int],
                      players: set[str] | None = None,
                      adviser: bool = False) -> tuple[list[Say], list[OrderResult]]:
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
        to_faction = m.to not in ("lobby", "adviser")
        if m.to == "adviser" and not adviser:
            reason = "you have no adviser"
        elif to_faction and (m.to == report.faction or m.to not in factions):
            reason = f"unknown faction '{m.to}'"
        elif to_faction and players is not None and m.to not in players:
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
