"""The steward: code that fills gaps a ruler left, and never overrides what the ruler ordered.

The author's rule (2026-10-30): work may be offloaded "so long as the LLM's wishes are always carried
out". So the steward only ever APPENDS an order after the ruler's own, never removes or changes
one, never acts where the ruler gave an order of the same kind, and the ruler is told next turn
what it did and how to stop it (`hold_empty`).

Live (run6, run7): a small-model ruler marched garrisons out of its settlements and left them
empty; London rebelled and Nottingham was taken.
"""

import re

from parley import units
from parley.control import ORDER_AREA
from parley.protocol import (
    Attack, Besiege, Board, Disband, Land, MarchOn, MergeArmies, MoveArmy, Orders, Recruit,
    RecruitOption, Settlement, StateReport, Unit, Withdraw,
)
from parley.validate import plain_name

MIN_GARRISON = 1  # units a settlement should keep
# the treasury kept after a steward recruit: the unit's cost, then this many turns of its upkeep
# (plus any deficit the realm runs: negative income is added once)
STEWARD_RESERVE_TURNS = 2
GARRISON_UPKEEP_CAP = 1.5  # a paid steward garrison unit's upkeep: at most this times the cheapest
# units a garrison is no use for: ships and siege engines (names as the game's recruit lists spell them)
_NOT_GARRISON = re.compile(
    r"\b(cog|galley|carrack|longship|dromon|barge|ship|ballista|catapult|trebuchet|mangonel|bombard|"
    r"cannon|ribault|ram|tower)\b", re.IGNORECASE)

# the report has no riot threshold; below this public order, a high tax is worth a warning
TAX_WARN_ORDER = 80
HIGH_TAXES = ("high", "extortionate")


def _candidates(settlement: Settlement, capped: bool = True) -> list[RecruitOption]:
    """Land units fit for a garrison: free-upkeep units, and paid ones whose upkeep is at most
    GARRISON_UPKEEP_CAP times the cheapest paid upkeep. The steward fills a gap cheaply (the author: order
    + cheap upkeep + defence); it doesn't buy elites. Live, run7 Nottingham: without the cap it
    picked Dismounted Feudal Knights at 225 upkeep over Levy Spearmen at 125."""
    fit = [u for u in settlement.can_recruit
           if not _NOT_GARRISON.search(u.unit) and units.is_garrison_kind(u.unit)]
    paid = [u.upkeep for u in fit if u.upkeep and not units.is_free(u.unit)]
    if not paid or not capped:
        return fit
    cap = GARRISON_UPKEEP_CAP * min(paid)
    return [u for u in fit if units.is_free(u.unit) or (u.upkeep or 0) <= cap]


def garrison_unit(settlement: Settlement, garrison: list[Unit] | None = None) -> RecruitOption | None:
    """The land unit the settlement can recruit now that holds it best for the upkeep.

    Never ships or siege engines. While the settlement has a free-upkeep slot left (walls, minus the
    free units already in `garrison`, training or queued), a free-upkeep unit comes first: it costs
    nothing a turn. Otherwise (and among the free ones) the best `units.defence_value`: men * (defence
    + armour + shield) / upkeep, using the report's upkeep. Ties go to the cheaper unit; a unit the
    unit table doesn't know scores 0, so with no data the cheapest wins.
    """
    options = _candidates(settlement)
    free_open = units.free_slots_left(settlement, garrison) > 0

    def rank(u: RecruitOption):
        free = free_open and units.is_free(u.unit)
        value = units.defence_value(u.unit, 1 if free else u.upkeep)
        return (not free, -value, u.cost, u.upkeep or 0)

    return min(options, key=rank, default=None)


def garrison_scores(settlement: Settlement, garrison: list[Unit] | None = None, capped: bool = True
                    ) -> list[tuple[str, bool, float]]:
    """(unit, free here, score) for each candidate, best first: what `garrison_unit` weighed.
    capped=False drops the steward's upkeep cap (THREATS shows what answers an enemy, not what's cheap)."""
    free_open = units.free_slots_left(settlement, garrison) > 0
    rows = []
    for u in _candidates(settlement, capped):
        free = free_open and units.is_free(u.unit)
        rows.append((u.unit, free, units.defence_value(u.unit, 1 if free else u.upkeep), u.cost))
    rows.sort(key=lambda r: (not r[1], -r[2], r[3]))
    return [(n, f, v) for n, f, v, _ in rows]


def _leaving(report: StateReport, order) -> tuple[str, int] | None:
    """(settlement id, units) an order takes out of a garrison, or None. A garrison named as the
    army leaves whole; a general named alone steps out with his one bodyguard unit."""
    garrisons = {a.id: a for a in report.armies if a.id.startswith("garrison:") and a.in_settlement}
    if isinstance(order, Disband):
        g = garrisons.get(order.army)
        if g is None:
            return None
        have = sum(1 for t in g.troops if t.type == order.unit) if g.troops else order.count
        return g.in_settlement, min(order.count, have)
    if isinstance(order, (MergeArmies, MarchOn, Besiege, Withdraw, Attack, MoveArmy, Land)):
        g = garrisons.get(order.army)
        if g is not None:
            return g.in_settlement, g.units
        if isinstance(order, MoveArmy):  # by the general who leads a garrison
            led = [a for a in garrisons.values() if a.leader and a.leader == order.army]
            if len(led) == 1:
                return led[0].in_settlement, 1
    if isinstance(order, Board):
        g = garrisons.get(order.who)
        if g is not None:
            return g.in_settlement, g.units
    return None


def units_after(report: StateReport, orders: Orders) -> dict[str, int]:
    """Garrison units each own settlement is left with once the ruler's orders are carried out."""
    left = {s.id: s.garrison_units for s in report.settlements}
    for order in orders.orders:
        gone = _leaving(report, order)
        if gone and gone[0] in left:
            left[gone[0]] = max(0, left[gone[0]] - gone[1])
    return left


def _held(settlement: Settlement, hold_empty: list[str]) -> bool:
    names = {plain_name(settlement.id), plain_name(settlement.name)}
    return any(plain_name(h) in names for h in hold_empty)


def backfill(report: StateReport, orders: Orders, areas: tuple[str, ...], gold_left: int
             ) -> tuple[list[Recruit], list[dict]]:
    """Recruit orders for settlements the ruler's orders leave under MIN_GARRISON.

    gold_left: the treasury after the ruler's own kept orders. Returns (orders to append, notes
    for the ruler: {settlement, name, unit} for each recruit, {settlement, name, failed} for each
    settlement that needed one and could not have one).

    Skipped: a settlement the ruler listed in hold_empty; one where the ruler ordered any recruit;
    one with recruits already queued or in training that would fill it; a seat with no say over
    recruiting. Units of a field army standing in the settlement are not counted as a garrison.
    """
    if ORDER_AREA["recruit"] not in areas:
        return [], []
    recruiting = {o.settlement for o in orders.orders if isinstance(o, Recruit)}
    left = units_after(report, orders)
    added, notes = [], []
    for s in report.settlements:
        incoming = len(s.training) + len(s.recruit_queue)
        if left[s.id] + incoming >= MIN_GARRISON or s.id in recruiting or _held(s, orders.hold_empty):
            continue
        held = next((a.troops for a in report.armies if a.id == f"garrison:{s.id}"), None)
        unit = garrison_unit(s, held)
        if unit is None:
            why = ("it can't recruit a garrison unit now" if not s.recruit_blocked
                   else "units inside it keep the game from listing what it can recruit")
            notes.append({"settlement": s.id, "name": s.name, "failed": why})
            continue
        reserve = unit.cost + (unit.upkeep or 0) * STEWARD_RESERVE_TURNS + max(0, -report.income)
        if gold_left < reserve:
            notes.append({"settlement": s.id, "name": s.name,
                          "failed": f"the treasury is too low ({gold_left} florins; it keeps {reserve} "
                                    f"in hand for a {unit.unit})"})
            continue
        gold_left -= unit.cost
        added.append(Recruit(settlement=s.id, unit=unit.unit))
        notes.append({"settlement": s.id, "name": s.name, "unit": unit.unit,
                      "ordered_by_you": left[s.id] < s.garrison_units})
    return added, notes


def steward_notes(notes: list[dict]) -> list[str]:
    """What the ruler reads next turn about the steward's garrison work."""
    out = []
    for n in notes:
        if n.get("failed"):
            out.append(f"Your steward found {n['name']} without a garrison but could not recruit one: "
                       f"{n['failed']}. To stop these notes, list the settlement in hold_empty.")
        else:
            out.append(f"Your steward recruited {n['unit']} in {n['name']} (it was left without a "
                       f"garrison). To stop this, list the settlement in hold_empty.")
    return out


def tax_warning(report: StateReport) -> str:
    """Settlements whose tax is high while public order is low. Information only; nothing changes."""
    rows = []
    for s in report.settlements:
        if s.tax_level in HIGH_TAXES and s.public_order is not None and s.public_order < TAX_WARN_ORDER:
            parts = ", ".join(f"{k} {v}" for k, v in s.order_parts.items() if "tax" in k)
            rows.append(f"- {s.name}: public order {s.public_order}%, tax {s.tax_level}"
                        + (f" ({parts} in its order breakdown)" if parts else "")
                        + ". Low order risks riots; set_tax lower or add garrison.")
    return "TAX AND UNREST\n" + "\n".join(rows) if rows else ""
