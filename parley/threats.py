"""The THREATS block: what the report already says is dangerous, in a few plain lines.

Facts and the obvious response only; it imposes no rules and never refuses anything."""

from parley import steward, units
from parley.protocol import StateReport

MAX_THREATS = 5
LANDING_TILES = 6     # a loaded enemy fleet this close to a settlement can land next turn
NEAR_TILES = 5       # an enemy army this close to a settlement is a threat to it
QUEUE_MAX = 9         # the game's recruitment queue holds at most this many (lua/parley_bridge.lua K.QUEUE_MAX)
SMALL_GARRISON = 50  # men; below this a garrison is "very small"
RIOT_ORDER = 70       # public order (%) below which settlements riot (the primer's figure)
REBEL_FACTIONS = {"slave", "rebel", "rebels"}


def _is_rebel(faction: str | None) -> bool:
    return (faction or "").lower() in REBEL_FACTIONS


def _men(s) -> int:
    return s.garrison_men


def _garrison_known_empty(s) -> bool:
    return not (s.garrison_units or s.garrison_men or s.garrison_strength)


def _garrison_text(s) -> str:
    return "no garrison" if _garrison_known_empty(s) else f"garrison {s.garrison_units} units, {_men(s)} men"


def _enemy_lines(report: StateReport) -> tuple[list[str], set[str]]:
    war = {f.id for f in report.factions if f.stance == "war"}
    foes = [a for a in report.visible_enemies
            if not a.is_fleet and (a.faction in war or _is_rebel(a.faction))]
    rows = []
    for s in report.settlements:
        if s.x is None:
            continue
        near = sorted(((max(abs(a.x - s.x), abs(a.y - s.y)), a) for a in foes), key=lambda p: p[0])
        near = [(d, a) for d, a in near if d <= NEAR_TILES]
        if near:
            rows.append((near[0][0], s, near))
    rows.sort(key=lambda r: r[0])
    lines = []
    for _, s, near in rows:
        shown = "; ".join(
            f"{a.id} ({'rebels' if _is_rebel(a.faction) else a.faction}, {a.units} units, {a.men} men, {d} tiles away)"
            for d, a in near[:2])
        extra = f" and {len(near) - 2} more" if len(near) > 2 else ""
        lines.append(f"- {s.id} has {_garrison_text(s)}; enemy near it: {shown}{extra}. "
                     f"{_answer(report, s, sum(a.men for _, a in near), near[0][0])}")
    return lines, {s.id for _, s, _ in rows}


def _batch(option, gap: int) -> tuple[int, int, int]:
    """(units, men, florins) of `option` that cover `gap` men."""
    men = units.info(option.unit)["men"]
    n = min(-(-gap // men), QUEUE_MAX)
    return n, n * men, n * option.cost


def _answer(report: StateReport, s, foe_men: int, enemy_tiles: int = 99) -> str:
    """The gap in men, and what answers it this turn: recruits (cost, men), field armies that can join."""
    gap = foe_men - _men(s)
    text = (f"{foe_men} enemy men vs your {_men(s)}: short by {gap}." if gap > 0
            else f"{foe_men} enemy men vs your {_men(s)}: you are not short on men.")
    if gap > 0:
        held = next((a.troops for a in report.armies if a.id == f"garrison:{s.id}"), None)
        known = {o.unit: o for o in steward._candidates(s, capped=False) if units.info(o.unit)}
        picks = []
        scores = steward.garrison_scores(s, held, capped=False)
        if scores:
            picks.append(known.get(scores[0][0]))
        if known:
            picks.append(min(known.values(), key=lambda o: o.cost / units.info(o.unit)["men"]))
        picks = [p for i, p in enumerate(picks) if p and p not in picks[:i]]
        if picks:
            batches = [(o, *_batch(o, gap)) for o in picks]
            opts = " or ".join(f"{n} x {o.unit} ({m} men, {c:,} florins{'' if m >= gap else ', the queue limit'})"
                               for o, n, m, c in batches)
            # the report doesn't expose a settlement's level, so not the exact turn: units train a few at a time
            text += (f" Queue {'to close it' if all(m >= gap for _, _, m, _ in batches) else 'toward it'}"
                     f": {opts}, against the {report.treasury:,} florins you hold (a settlement queues up to "
                     f"{QUEUE_MAX} units, as many as its pool allows). Units train a few at a time (2 in a small "
                     "city, 3 in a large one): the first batch is ready next turn, the rest a turn later per batch.")
        elif s.recruit_blocked or not s.can_recruit:
            text += " It can't recruit now."
    mine = sorted(((max(abs(a.x - s.x), abs(a.y - s.y)), a) for a in report.armies
                   if not a.id.startswith("garrison:") and not a.is_fleet and a.men), key=lambda p: p[0])
    mine = [(d, a) for d, a in mine if d <= NEAR_TILES][:2]
    if mine:
        text += " Your armies near: " + "; ".join(f"{a.id}, {d} tiles away, {a.men} men" for d, a in mine) + "."
    if gap > 0 and enemy_tiles <= 2:
        hire = [f"{a.id} can hire {o.available} x {o.unit} ({o.cost:,} florins each)"
                for a in report.armies if not a.is_fleet and max(abs(a.x - s.x), abs(a.y - s.y)) <= NEAR_TILES
                for o in a.can_hire[:1]]
        text += (" The enemy is at the gate and queued units may come too late; faster: merge an army in"
                 + (f"; mercenaries join next turn ({'; '.join(hire[:2])})" if hire else "") + ".")
    return text


def _hoard_line(report: StateReport, threatened: list[str]) -> list[str]:
    if not threatened or report.income <= 0 or report.treasury <= 2 * report.income:
        return []
    names = " and ".join(threatened[:3])
    return [f"- Treasury {report.treasury:,} = {report.treasury / report.income:.1f} turns of income, unspent, "
            f"while {names} {'is' if len(threatened) == 1 else 'are'} threatened."]


def _fleet_lines(report: StateReport) -> list[str]:
    """Foreign fleets carrying an army (at war, or rebels) near one of our settlements."""
    war = {f.id for f in report.factions if f.stance == "war"}
    lines = []
    for a in report.visible_enemies:
        if not (a.is_fleet and a.carrying and (a.faction in war or _is_rebel(a.faction))):
            continue
        near = sorted(((max(abs(a.x - s.x), abs(a.y - s.y)), s) for s in report.settlements if s.x is not None),
                      key=lambda p: p[0])
        if near and near[0][0] <= LANDING_TILES:
            d, s = near[0]
            who = "rebels" if _is_rebel(a.faction) else a.faction
            men = f" ({a.carrying_men} men)" if a.carrying_men else ""
            lines.append(f"- {a.id} ({who}) carries an army of {a.carrying} units{men}, {d} tiles from {s.id} "
                         f"({_garrison_text(s)}): it can land next turn. A fleet that beats it at sea stops "
                         "the landing (attack works fleet against fleet).")
    return lines


def threat_lines(report: StateReport) -> list[str]:
    """Up to MAX_THREATS lines, most urgent first: enemies at the gate, riot risk, debt, thin garrisons."""
    enemy, covered = _enemy_lines(report)
    riots = [f"- {s.id} has public order {s.public_order}% (tax {s.tax_level or 'not set'}): below "
             f"{RIOT_ORDER}% it riots and can go over to the rebels. Lower its tax or add men to its garrison."
             for s in report.settlements if s.public_order is not None and s.public_order < RIOT_ORDER]
    revolt = []
    for s in report.settlements:
        if s.rebelling:
            revolt.append(f"- {s.id} is flagged by the game to revolt (it can go over to the rebels as soon as next "
                          f"turn; public order {s.public_order}%, tax {s.tax_level or 'not set'}). "
                          "Lower its tax or add men to its garrison now.")
        elif s.plagued:
            revolt.append(f"- {s.id} has plague: its people die and its order slips. Lower its tax, and "
                          "build or keep a hospital or sewer there if you can.")
    debt = []
    if report.income and 0 <= report.treasury and report.treasury + report.income < 0:
        debt = [f"- Treasury {report.treasury} florins with income {report.income} a turn: it goes negative "
                "next turn, and orders that cost gold are refused in debt: recruit or build now if you need to. "
                "Debt is fine while it buys a gain (a siege, a town to take); if it buys nothing, cut what serves no goal."]
    thin = []
    for s in report.settlements:
        if s.id in covered:
            continue
        if _garrison_known_empty(s):
            thin.append(f"- {s.id} has no garrison: anyone who reaches it takes it. Recruit there or merge an army in.")
        elif s.garrison_men and s.garrison_men < SMALL_GARRISON:
            thin.append(f"- {s.id} has a garrison of only {s.garrison_men} men. Recruit there or merge an army in.")
    lines = (enemy + _fleet_lines(report) + revolt + riots + debt + thin)[:MAX_THREATS]
    hoard = _hoard_line(report, [s.id for s in report.settlements if s.id in covered])
    return lines[:MAX_THREATS - len(hoard)] + hoard


def threats_block(report: StateReport) -> str:
    lines = threat_lines(report)
    return "THREATS (worked out from your report below)\n" + "\n".join(lines) if lines else ""
