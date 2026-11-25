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
    HireMercenary,
    RecruitAgent,
    Repair,
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
    GameAiRecruiting,
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

MAX_ORDERS = 40  # the floor of the per-turn order budget
HARD_MAX_ORDERS = 150  # never more, however big the realm: a weak model looping out hundreds of orders


def order_cap(report: StateReport, floor: int | None = None) -> int:
    """Orders one turn may carry: grows with the realm (3 per settlement, 1 per army and agent),
    never under the floor (MAX_ORDERS) or over HARD_MAX_ORDERS."""
    floor = MAX_ORDERS if floor is None else floor
    scaled = 3 * len(report.settlements) + len(report.armies) + len(report.agents)
    return min(HARD_MAX_ORDERS, max(floor, scaled))
MAX_PER_RECIPIENT = 3
MAX_CHARS = 600
# "admiral" and "captain": live 11-05 (run 10, turn 11) England wrote board/move_army for "Nigel" and
# "Geiles", its report's "Admiral Nigel" and "Admiral Geiles", and all four were refused as unknown
TITLES = {"princess", "prince", "king", "queen", "lord", "lady", "sir", "duke", "count", "admiral", "captain"}
NAME_FIELDS = ("army", "into", "agent", "who", "fleet")  # the ruler's own armies and agents
SEEN_FIELDS = ("settlement", "target_settlement", "to_settlement", "target")  # towns and characters in sight


def plain_name(name: str) -> str:
    """A name as a ruler might mistype it: case, underscores and a leading title dropped, and a
    garrison written any way ("Caen_garrison", "Nottingham Garrison") as garrison:caen, and an
    army written as "Arthur's Army" as arthur."""
    words = name.replace("_", " ").replace(":", " ").lower().split()
    while len(words) > 1 and words[0] in TITLES:
        words = words[1:]
    if "garrison" in words and len(words) > 1:
        words = ["garrison"] + [w for w in words if w != "garrison"]
    # live (run9 turn 45): France wrote "Captain Arthur's Army" for its army "Captain Arthur"
    if len(words) > 1 and words[-1] in ("army", "stack") and words[0] != "garrison":
        words = words[:-1]
        words[-1] = words[-1].removesuffix("'s").removesuffix("’s")
    return " ".join(words)


def _own_names(report: StateReport) -> set[str]:
    return ({a.id for a in report.armies} | {a.id for a in report.agents}
            | {p.name for p in report.family if p.alive and p.kind == "general"})


def _canonical(order, own: set[str], report: StateReport):
    """The order with a near-miss name of the ruler's own replaced by its exact id, when exactly
    one fits (live, 2026-10-29: 'Admiral_Nigel', 'Caen_garrison' and 'Princess Constance' were
    refused as unknown, seven times for the admiral alone)."""
    if isinstance(order, RecruitAgent):  # its agent is a kind, not a name
        return order
    update = {}
    for field in NAME_FIELDS:
        value = getattr(order, field, None)
        if isinstance(value, str) and value not in own:
            fits = [n for n in own if plain_name(n) == plain_name(value)]
            if len(fits) == 1:
                update[field] = value = fits[0]
        # an army named by the general who leads it (live: merges "into Philip", who leads
        # garrison:Paris); move_army keeps a general's own name: he steps out alone
        if field in ("army", "into") and isinstance(value, str) and not isinstance(order, MoveArmy) \
                and value not in {a.id for a in report.armies}:
            led = [a.id for a in report.armies if a.leader and plain_name(a.leader) == plain_name(value)]
            if len(led) == 1:
                update[field] = led[0]
    # a town or a foreign character in sight, named near enough (live, run8 turn 2: march_on and
    # spy on "york" were refused; the report listed York, and the bridge looks names up exactly)
    seen = ({s.id for s in report.settlements} | {s.id for s in report.nearby_settlements}
            | {e.id for e in report.visible_enemies} | {a.id for a in report.seen_agents})
    for field in SEEN_FIELDS:
        value = getattr(order, field, None)
        if isinstance(value, str) and value not in seen:
            fits = [n for n in seen if plain_name(n) == plain_name(value)]
            if len(fits) == 1:
                update[field] = fits[0]
    return order.model_copy(update=update) if update else order


def _into_full_town(report: StateReport, army_id: str, town: str) -> str:
    """The refusal for an army entering its own town when the two would pass 20 units, or "".
    The bridge refuses it at turn start (live 11-23: Bordeaux and Caen, 8 times); refused here the
    ruler hears it the same turn."""
    army = next((x for x in report.armies if x.id == army_id), None)
    garrison = next((x for x in report.armies if x.id == f"garrison:{town}"), None)
    if army is None or garrison is None or army is garrison or army.is_fleet:
        return ""
    if army.units + garrison.units <= 20:
        return ""
    return (f"{town}'s garrison has {garrison.units} units and this army {army.units}: "
            f"{army.units + garrison.units}, over the 20 a settlement holds, so it would stay outside. "
            f"Disband or leave units out first, or merge_units to fold worn ones")


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
            # land orders only: the game's C++ gets an admiral's stack otherwise (a crash pcall can't catch)
            if next(x for x in report.armies if x.id == a).is_fleet:
                return f"'{a}' is a fleet; {order.type} is for land armies (fleets: move_army, blockade)"
            if isinstance(order, Besiege) and order.settlement in owned:
                return "cannot besiege own settlement"
            if isinstance(order, Withdraw) and order.to_settlement not in owned:
                return f"settlement '{order.to_settlement}' not owned"
            if isinstance(order, Withdraw) and (full := _into_full_town(report, a, order.to_settlement)):
                return full
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
        case Repair():
            mine = {s.id: s for s in report.settlements}
            s = mine.get(order.settlement)
            if s is None:
                return f"settlement '{order.settlement}' not owned"
            if order.building in s.queue:
                return f"'{order.building}' is already in {s.id}'s queue; it will be repaired without a second order"
            dmg = next((d for d in s.damaged_buildings if d.name == order.building), None)
            if dmg is None:
                damaged_names = ", ".join(d.name for d in s.damaged_buildings) or "none"
                return f"{s.id} has no damaged building '{order.building}' (damaged: {damaged_names})"
        case RecruitAgent():
            s = next((x for x in report.settlements if x.id == order.settlement), None)
            if s is None:
                return f"settlement '{order.settlement}' not owned"
            offer = next((a for a in s.can_recruit_agents if a.agent == order.agent), None)
            if offer is None:
                lim = report.agent_limits.get(order.agent)
                if lim and lim.limit is not None and lim.have >= lim.limit:
                    return f"{order.agent} limit reached: {lim.have} of {lim.limit}"
                return (f"{s.id} can't train a {order.agent} now (can: "
                        f"{', '.join(a.agent for a in s.can_recruit_agents) or 'no agents'})")
            if offer.cost > gold_left:
                return f"treasury too low ({gold_left} left, needs {offer.cost})"
        case HireMercenary(army=a):
            army = next((x for x in report.armies if x.id == a), None)
            if army is None:
                return f"unknown army '{a}'"
            if army.is_fleet:
                return f"'{a}' is a fleet; mercenaries are hired by a land army with a general"
            if not army.leader:
                return f"'{a}' has no general; only an army with a general hires mercenaries"
            offer = next((m for m in army.can_hire if m.unit == order.unit), None)
            if offer is None:
                return (f"'{a}' can't hire '{order.unit}' where it stands (its region's pool offers: "
                        f"{', '.join(m.unit for m in army.can_hire) or 'nothing'})")
            if army.units >= 20:
                return f"'{a}' already holds 20 units"
            if offer.cost > gold_left:
                return f"treasury too low ({gold_left} left, needs {offer.cost})"
        case GameAiRecruiting():
            if report.human_slot:
                return "no game AI acts for your realm: there is nothing to switch"
        case SetTax(settlement=s):
            if s not in owned:
                return f"settlement '{s}' not owned"
        case Retrain(settlement=s):
            if s not in owned:
                return f"settlement '{s}' not owned"
            if gold_left <= 0:
                return f"treasury too low ({gold_left} left) to retrain"
        case MoveAgent(agent=g) | Marry(agent=g):
            agent = next((x for x in report.agents if x.id == g), None)
            if agent is None:
                # live (2026-10-29, turn 138): France sent its generals Godfrey, Milet and Marc Xavier
                # by move_agent; name the order that moves them
                if isinstance(order, MoveAgent) and any(g in (a.id, a.leader) for a in report.armies):
                    return (f"'{g}' leads one of your armies, not an agent: move it with "
                            f"{{\"type\": \"move_army\", \"army\": \"{g}\", \"x\": {order.x}, \"y\": {order.y}}}")
                return f"unknown agent '{g}' (not one of yours)"
            if isinstance(order, MoveAgent) and agent.kind == "admiral":
                # live (2026-10-29, turn 8): Admiral Nigel by move_agent came back "done" and stayed put
                fleet = next((a.id for a in report.armies if a.is_fleet and g in (a.id, a.leader)), g)
                return (f"'{g}' is an admiral: he sails with his fleet, so move it with "
                        f"{{\"type\": \"move_army\", \"army\": \"{fleet}\", \"x\": {order.x}, \"y\": {order.y}}} "
                        f"(fleets move on sea tiles)")
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
            # one stack under two names: a garrison and the general who leads it (live 11-23,
            # England turn 4451, refused by the bridge as a merge into itself)
            if b == mine[a].leader or a == mine[b].leader:
                return f"'{a}' and '{b}' are one army ({mine[a].leader or mine[b].leader} leads it)"
            if mine[a].is_fleet != mine[b].is_fleet:
                return "a fleet and a land army can't merge"
            if mine[a].is_fleet:
                # live 11-14 15:37: Admiral Robin into Admiral John, then two crashes in that round
                return (f"two fleets can't be merged: it removes {a}, and an admiral of yours leaving "
                        f"the game crashes it (11-14); sail them together instead")
            if mine[a].aboard or mine[b].aboard:
                return f"'{a if mine[a].aboard else b}' is aboard a fleet; land it first"
            if mine[a].units + mine[b].units > 20:
                return f"together they'd be {mine[a].units + mine[b].units} units; an army holds at most 20"
        case MergeUnits(army=a):
            mine = {x.id: x for x in report.armies}
            if a not in mine:
                return f"unknown army '{a}'"
            # the bridge pours the weakest unit into the fullest one that isn't full, so it needs two
            # under-strength units of one type (it refuses: "no two worn units of one type"). Live
            # 11-13: France ordered it 21 times in half an hour on two armies that had none. Units
            # pair only within one type AND armour/weapon level, bodyguards and retraining units
            # left out (Unit.merge_group, the bridge's merge_key): live 11-13/14, Captains Foucher
            # and Gerbert each had two worn Pike Militia the bridge wouldn't pair, 20 refusals.
            # Only when every unit's maximum is known
            troops = mine[a].troops
            if troops and all(t.max_soldiers > 0 for t in troops):
                worn: dict[str, int] = {}
                for t in troops:
                    if (g := t.merge_group()) is not None:
                        worn[g] = worn.get(g, 0) + 1
                if not any(n >= 2 for n in worn.values()):
                    return (f"nothing to merge in {a}: no two under-strength units of one type and "
                            f"armour/weapon level (under strength: {', '.join(sorted(worn)) or 'none'})")
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
            if isinstance(order, MoveArmy) and a in armies:
                town = next((s for s in report.settlements if (s.x, s.y) == (order.x, order.y)), None)
                if town is not None and (full := _into_full_town(report, a, town.id)):
                    return full
            if isinstance(order, Attack) and order.target not in {e.id for e in report.visible_enemies}:
                return f"target '{order.target}' is not in sight (use an id from FOREIGN ARMIES IN SIGHT)"
    return ""


def _off_map(report: StateReport, x: int, y: int) -> str:
    if x < 0 or y < 0:
        return f"({x},{y}) is off the map (coordinates start at 0)"
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
    if s and isinstance(order, RecruitAgent):
        return next((a.cost for a in s.can_recruit_agents if a.agent == order.agent), 0)
    if isinstance(order, HireMercenary):
        army = next((x for x in report.armies if x.id == order.army), None)
        return next((m.cost for m in army.can_hire if m.unit == order.unit), 0) if army else 0
    return 0


AGENT_KIND = {"assassinate": "assassin", "spy": "spy", "bribe": "diplomat", "sabotage": "assassin"}


def _check_agent_order(report: StateReport, order) -> str:
    """Your own agent, of the right kind, against something you can actually see."""
    mine = {a.id: a for a in report.agents}
    agent = mine.get(order.agent)
    need = AGENT_KIND[order.type]
    yours = sorted(a.id for a in report.agents if a.kind == need)
    yours_text = (f"your {need}s: {', '.join(yours)}" if yours else f"you have no {need}")
    if agent is None:
        # live (2026-10-29): France put the enemy diplomat it meant to bribe in "agent", five times
        seen = next((a for a in report.seen_agents if a.id == order.agent), None)
        if seen is not None:
            return (f"'{order.agent}' is {seen.faction}'s {seen.kind}, not yours: \"agent\" is your own "
                    f"{need} ({yours_text}) and \"target\" is who you act on")
        return f"unknown agent '{order.agent}' (not one of yours; {yours_text})"
    if agent.kind != need:
        article = "an" if need[0] in "aeiou" else "a"
        return f"'{order.agent}' is a {agent.kind}, not {article} {need} ({yours_text})"
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
                    areas: tuple[str, ...] = PRESETS["ruler"],
                    playtest_funds: bool = False,
                    playtest_funds_amount: int = 50000) -> tuple[Orders, list[OrderResult]]:
    """areas: the seat's control areas; orders outside them are refused."""
    kept, rejected = [], []
    gold_left = max(report.treasury, playtest_funds_amount) if playtest_funds else report.treasury
    busy = set()  # agents already given an order: the game lets each act once a turn
    # one agent mission per target a turn: live 11-13 a bribe won a captain over and the same
    # turn's assassination of him then crashed the game (the bridge refuses it too)
    targeted: dict[str, str] = {}
    training: dict[str, int] = {}  # agents of each kind ordered trained this turn
    queued = {s.id: set(s.queue) for s in report.settlements}  # buildings queued, this turn's included
    merged: set[str] = set()  # armies given merge_units this turn
    # mercenaries hired this turn, by (pool, unit): a region's pool is shared by every army in it.
    # Live 11-21 (scratch, turn 3130): one Galloglaich listed under three of England's armies;
    # Alfred Gryffin's hire took it and Aston Morgan's was refused by the bridge as "offers: nothing"
    hired: dict[tuple[str, str], list[str]] = {}
    hires_into: dict[str, int] = {}  # units hired into each army this turn
    recruited: dict[tuple[str, str], int] = {}  # (settlement, unit) recruits ordered this turn
    own = _own_names(report)
    cap = order_cap(report)
    for i, order in enumerate(orders.orders):
        order = _canonical(order, own, report)
        area = ORDER_AREA.get(order.type)
        if len(kept) >= cap:  # the bridge runs every order in one game frame; refused orders don't count
            reason = f"more than {cap} orders in one turn; the rest are dropped"
        elif area not in areas:
            reason = f"'{order.type}' is {area}, not yours to command (yours: {', '.join(areas)})"
        else:
            reason = _check(report, order, gold_left)
        agent = None if isinstance(order, RecruitAgent) else getattr(order, "agent", None)  # a kind, not an agent
        if not reason and agent in busy:
            reason = f"'{agent}' already has an order this turn"
        mission_target = None
        if isinstance(order, (Assassinate, Spy, Bribe, Sabotage)):
            mission_target = order.settlement if isinstance(order, Sabotage) else order.target
        if not reason and mission_target is not None and mission_target.lower() in targeted:
            reason = (f"'{mission_target}' is already the target of {targeted[mission_target.lower()]}'s "
                      f"mission this turn: one mission per target a turn")
        # one merge_units folds every group in the army: live 11-14 England sent four for
        # garrison:York in one turn and the bridge refused three, "nothing to merge"
        if not reason and isinstance(order, MergeUnits):
            if order.army in merged:
                reason = (f"merge_units is already ordered for {order.army} this turn: one merges "
                          f"every group of worn units in it")
            else:
                merged.add(order.army)
        if not reason and isinstance(order, (Build, Repair)):
            if order.building in queued[order.settlement]:
                reason = f"'{order.building}' is already ordered for {order.settlement} this turn"
            else:
                queued[order.settlement].add(order.building)
        if not reason and isinstance(order, RecruitAgent) and (lim := report.agent_limits.get(order.agent)) and lim.limit is not None:
            if lim.have + training.get(order.agent, 0) >= lim.limit:
                reason = f"{order.agent} limit reached: {lim.have} of {lim.limit}, plus {training[order.agent]} ordered this turn"
            else:
                training[order.agent] = training.get(order.agent, 0) + 1
        # live 11-24 (England turn 4863): six Town Militia queued at Dijon, its pool held two, the
        # game refused four at turn start
        if not reason and isinstance(order, Recruit):
            s = next(x for x in report.settlements if x.id == order.settlement)
            offer = next(u for u in s.can_recruit if u.unit == order.unit)
            before = recruited.get((s.id, order.unit), 0)
            if offer.available is not None and before >= offer.available:
                reason = (f"{s.id}'s pool holds {offer.available} {order.unit} this turn and the "
                          f"{before} recruit{'s' if before != 1 else ''} before this one take "
                          f"{'them' if offer.available != 1 else 'it'}")
            else:
                recruited[(s.id, order.unit)] = before + 1
        if not reason and isinstance(order, HireMercenary):
            army = next(x for x in report.armies if x.id == order.army)
            offer = next(m for m in army.can_hire if m.unit == order.unit)
            key = (offer.pool or f"army:{army.id}", order.unit)
            took = hired.setdefault(key, [])
            # live 11-23: seven hires refused by the bridge, "already holds 20 units": each was
            # checked against the report's count, not the hires before it this turn
            before = hires_into.get(army.id, 0)
            if army.units + before >= 20:
                reason = (f"'{army.id}' holds {army.units} units and this turn's {before} hires "
                          f"before this one fill it to 20 (an army holds at most 20)")
            elif len(took) >= offer.available:
                where = f"the {offer.pool} pool" if offer.pool else "the pool"
                reason = (f"{where} has {offer.available} {order.unit} and this turn's hires for "
                          f"{', '.join(took)} take them: a region's pool is shared by every army in it")
            else:
                took.append(order.army)
                hires_into[army.id] = before + 1
        if reason:
            rejected.append(OrderResult(index=i, type=order.type, ok=False, reason=reason))
            continue
        gold_left -= cost(report, order)
        if agent is not None:
            busy.add(agent)
        if mission_target is not None:
            targeted[mission_target.lower()] = agent
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
