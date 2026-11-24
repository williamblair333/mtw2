"""Turn a state report into the text an LLM seat reads."""

import logging
from pathlib import Path

from parley.advice import siege_clock
from parley.audit import refusal_key
from parley.control import AREAS, PRESETS
from parley.protocol import Army, StateReport
from parley.steward import tax_warning
from parley.threats import threats_block
from parley.units import free_slots, free_slots_left, is_free
from parley.units import info as unit_info

log = logging.getLogger("parley.prompt")

PRIMER_PATH = Path(__file__).with_name("primer.md")
STRATEGY_DIR = Path(__file__).with_name("strategy")


def primer() -> str:
    """The strategy primer: how MTW2's systems work. Empty if the file is missing."""
    try:
        return PRIMER_PATH.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""


# an AI-run realm's armies move and their captains change names between the ruler's turns (live
# 11-05, run 10: France lost 2-4 orders a turn to renamed captains and blamed border skirmishes)
AI_RENAMES = ("That AI moves your armies and renames their captains between your turns: use army ids "
              "exactly as this report lists them, never last turn's.")
ROLE = (
    "You are the ruler. Your generals handle routine moves: recruiting, building and "
    "ordinary army movement. Give only diplomatic orders and specific override orders "
    "that matter this turn. " + AI_RENAMES.replace("That AI", "The game's AI")
)

HUMAN_SLOT_ROLE = ("No game AI acts for this realm, and no governor recruits or builds for you: "
                   "what you don't order doesn't happen. Nobody else will raise your armies.")
AI_ASSIST_ROLE = ("The game's own AI also acts for this realm between your orders (recruiting, "
                  "building and moving armies); your orders come first. " + AI_RENAMES)

ORDER_HELP = {
    "diplomacy": '- Diplomacy orders: "send_gold", "cede_settlement", "set_stance".',
    "armies": (
        '- Army orders (name an army by its id): "march_on" (toward a settlement; 20 units with its garrison), "move_army" (toward a tile x,y), '
        '"attack" (a foreign army in sight, outside a settlement), "besiege" (add "assault": true to storm now; '
        'otherwise you wait while it starves; walls need siege equipment, a village has none. Equipment is '
        'built each turn you besiege: assault when ready, or starve the town), "withdraw", '
        '"disband" (an army by its id, a unit type from its troops list, a count, 1 if left out: releases the '
        'weakest first to save upkeep; a bodyguard is never released).\n'
        '- "merge_armies": one of your armies, a garrison too, walks to join another (20 units at most). The joining '
        'happens as it walks, so an attack ordered the same turn fights with the army as it stood before: merge one '
        'turn, attack the next. To move a garrison with no general, merge it into an army that has one, or march '
        'the general into the settlement.\n'
        '- "move_army" also takes a general\'s own name (from YOUR FAMILY): he steps out alone with his bodyguard, '
        'even from a garrison he doesn\'t lead. That is how a field army is made: step a general out onto a tile '
        'beside the settlement, then "merge_armies" the garrison (or other armies) into him next turn. A general '
        'in a garrison is an army waiting to be formed.\n'
        '- A land army moves only onto land; an order onto sea is refused with the nearest land tile. It goes only '
        'as far as its moves allow and continues only if you order it again.\n'
        '- Ships: a fleet sails with "move_army" to a sea tile; "board" puts an army (by its id) or an agent aboard '
        'one of your fleets standing next to it (one army per fleet); "land" puts an army ashore on a land tile '
        'next to its fleet; "blockade" closes a foreign port; "attack" works fleet against fleet. Crossing water: '
        'board, sail, land, over several turns.\n'
        '- "merge_units" (an army by its id) folds that army\'s under-strength units of one type together: soldiers '
        'move into the fullest units, emptied units disband, the bodyguard is untouched. It costs nothing and no '
        'moves, and is refused (nothing to merge) unless the army has two worn units of one type (its troops line '
        'shows them).\n'
        '- Merge worn units of one type when an army has two that can combine; keep units at full strength: a few '
        'full units fight far better than many weak ones.'),
    "build": '- "build": queue a building from a settlement\'s "can build" list. It costs its price when queued; a settlement builds one thing at a time. Never order what is already in its queue.\n'
             '- "repair": queue the repair of a damaged building in a settlement (from its damaged buildings list).',
    "recruit": ('- "recruit": a unit from a settlement\'s "can recruit" list. You pay now; it joins that garrison when '
                'trained (usually next turn). Nobody recruits for you. "retrain" (a settlement) refills its damaged '
                'garrison units whose type its pool still offers, for the missing share of the price; the men arrive '
                'next turn. Bring damaged units into a settlement that can recruit their type first. "hire_mercenary" '
                '(an army with a general, a unit from its "mercenaries for hire" list) pays now, takes one from the pool of the '
                'region the army stands in, and the unit joins that army next turn. "recruit_agent" '
                '(a settlement and an agent from its "can train agents" list) pays now; the agent appears there next '
                'turn. Agents work only if you order them: a merchant earns from a trade resource, a priest converts a '
                'region, a spy scouts and opens gates, an assassin removes generals and agents, a diplomat negotiates '
                'and bribes.'),
    "taxes": '- "set_tax": low, normal, high or extortionate. Higher taxes bring gold and lower public order; a settlement below about 70% public order risks riots and revolt.',
    "agents": ('- Agent orders: "assassinate" (your own assassin, a character in sight), "sabotage" (your own assassin, a '
               'settlement in sight), "spy" (your own spy, a settlement or character in sight; a spy inside a settlement '
               'keeps spying on it, so ordering him to spy on it is refused), "bribe" (your own diplomat, a character or '
               'settlement in sight). In these "agent" is your own agent by its id from your agents list, and '
               '"target" is who or what it acts on, from your sight lists. "move_agent" walks any of your agents (a '
               'princess too) toward a tile x,y; agents cannot cross the sea alone. Merchants: move_agent one onto a '
               'tile from TRADE RESOURCES IN SIGHT and he trades there each turn he stands on it; far resources pay '
               'more, and rival merchants may take his trade. "marry": your princess offers her hand to a foreign '
               'general in sight. Each agent acts once a turn and may fail or die; the next report tells you.'),
}


def adviser_section(adviser: str) -> str:
    return (f"YOUR ADVISER\n{adviser} is your loyal adviser: a human who wants you to win and "
            "has no throne of their own. Weigh their counsel; follow it when it's sound, overrule "
            "it when you know better, and tell them why either way. Ask them for counsel, not for facts: "
            "your report holds everything the game shows you. If it lacks something you need, "
            "write \"Missing: <what>\" in your note and it will be added. Never reveal them to other rulers. "
            "Write to them with {\"to\": \"adviser\"}: every turn at least one short message on what you did "
            "and why (they read it on Discord), at most 3. If you promised something in the thread above, "
            "order it now or tell them plainly why not. " + TECHNICAL_NOTES)


# the author, 2026-10-26: the ruler answered "on screen message keeps minimizing" as a scribe's trouble;
# it should know it's playing a game and answer the game's own problems plainly
TECHNICAL_NOTES = (
    "You are an AI playing Medieval II: Total War through Parley, a bridge that reads the game into "
    "your report and carries out your orders. Claude (or \"the operator\") is the developer who runs "
    "Parley; notes signed by them mean that developer, not a courtier. Your adviser may also write "
    "technical notes (screen, popups, the bridge, crashes, wrong or missing data). Answer those plainly and "
    "out of character: what your report shows on it (or that it shows nothing), and whether it touched your "
    "orders; if it points at a bug, write \"Bug: <what>\" in your note. Stay in character with other rulers.")


def role(areas: tuple[str, ...], human_slot: bool = False) -> str:
    if areas == PRESETS["ruler"] and not human_slot:
        return ROLE
    rest = [a for a in AREAS if a not in areas]
    text = f"You are the ruler. You command: {', '.join(areas)}."
    if rest and not human_slot:
        text += f" Your governors and generals handle {', '.join(rest)}."
    elif rest:
        text += f" Not yours to order: {', '.join(rest)}."
    text += " " + (HUMAN_SLOT_ROLE if human_slot else AI_ASSIST_ROLE)
    return text


RULES = """OUTPUT RULES
- Answer with JSON matching the given schema, and nothing else.
- Use IDs exactly as written before the parentheses, e.g. "hre", never "Holy Roman Empire".
- Never claim gold, armies or settlements you don't have. Bluff in conversation if you like, never in orders.
- An empty "orders" list is allowed when nothing needs doing.
- To speak, add "messages": {"to": "lobby"} is public; {"to": "<faction id>"} is private to that faction. At most 3 per recipient per turn, 600 characters each. Speak only when you have something new to say; don't repeat what you said before.
- Put private reasoning in "note"; no other faction sees it. Notes come back to you next turn, so record plans, grudges and promises there. A human reads them: plain sentences in short paragraphs, one topic each, no shorthand like "T17" or "+2279".
- An order result of "done" means the order was carried out, not that it succeeded; check your next report.
- Return "plan": your standing plan, 1 to 3 goals, each with its next concrete step and the turn you mean to reach it by. Keep it until a goal is done or you drop it for a reason you state in your note. If a target turn has passed with the step not taken, take it now or say in your note why not.
- Give army and garrison sizes as units and men, never as a strength rating or a bare 4-5 digit number, even where your older notes did."""

DIPLOMACY_HEADER = (
    "DIPLOMACY (most recent last)\n"
    "Public messages are seen by everyone; private ones only by the two sides. "
    "Promises bind nothing in the game: a deal is kept only if someone acts on it.")


def diplomacy_section(lines: list[str]) -> str:
    """The diplomacy block: the latest DIPLOMACY_SHOWN lines, each cut short, and a count of the rest."""
    older = len(lines) - DIPLOMACY_SHOWN
    shown = [x if len(x) <= DIPLOMACY_CHARS else x[:DIPLOMACY_CHARS - 1] + "…" for x in lines[-DIPLOMACY_SHOWN:]]
    return DIPLOMACY_HEADER + "\n" + (f"({older} older messages not shown)\n" if older > 0 else "") + "\n".join(shown)


def one_line(text: str) -> str:
    """Quoted message text on a single line, so nobody can forge a new history line."""
    return " ".join(text.split())


def _sender(sender: str, names: dict[str, str]) -> str:
    if sender == "parley":  # out of character: parley.tell notes and transfer notices
        return "Game note (from the people running this game)"
    if sender.startswith("adviser:"):  # names maps "adviser:<faction>" to the adviser's name
        return f"Your adviser ({names.get(sender, 'unnamed')})"
    faction = sender.removeprefix("human:")
    return f"{names.get(faction, faction)} ({faction})"


def _diplomacy_line(m, me: str, names: dict[str, str]) -> str:
    if m.channel == "lobby":
        where = "public"
    elif m.channel.startswith("adviser:"):
        where = "private with your adviser"
    else:
        a, b = m.channel.removeprefix("pair:").split("|")
        where = f"private with {b if a == me else a}"
    return f"[turn {m.turn}] [{where}] {_sender(m.sender, names)}: {one_line(m.text)}"


def _army(a: Army, hire_seen: dict[str, str] | None = None) -> str:
    if a.in_settlement:
        where = f"in {a.in_settlement}"
    elif a.leader:
        where = f"at ({a.x},{a.y})"
    else:  # the bridge can't place a stack with no general outside a settlement
        where = "position unknown (fleet, fort or no general)"
    leader = f", led by {a.leader}" if a.leader else ""
    if a.is_fleet:
        leader += f" (a fleet{f', carrying an army of {a.carrying} units' if a.carrying else ', empty'})"
    if a.aboard:
        leader += f" (at sea aboard {a.aboard})"
    if a.in_settlement and a.leader:  # seen live: the garrison stays when its general marches
        leader += (" (marching this army moves only the general and his bodyguard; to bring the "
                   "garrison, merge_armies it into a field army)")
    # live: a ruler read "strength 2494" as 2494 men and stormed a city with 54 (a bodyguard
    # rates high); his own troops give the real head count
    men_count = a.men or sum(t.soldiers for t in a.troops)
    men = f", {men_count} men" if men_count else ""
    if a.besieging:
        left = f"; {a.besieging} holds out {a.holdout_turns} more turns" if a.holdout_turns is not None else ""
        built = (f"{a.siege_queue} pieces of siege equipment being built" if a.siege_queue
                 else "no siege equipment queued yet")
        can = "" if a.can_assault is None else f"; can assault now: {'yes' if a.can_assault else 'no'}"
        where += f", besieging {a.besieging} (turn {a.siege_turns or 0}: {built}{left}{can})"
    if a.id == f"garrison:{a.in_settlement}" and not a.besieging:
        where = ""  # the id already names the town (live 11-23: 59 garrisons ended "in <town>")
    line = f"- {a.id}: {a.units} units{men} (strength rating {a.strength}, not men){', ' + where if where else ''}{leader}"
    if a.can_hire:
        offers = "; ".join(
            f"{m.unit} {m.cost}, {m.available}/{m.max or m.available}, exp {m.exp}" for m in a.can_hire)
        # live 11-23: France's 21 armies in one region printed the same offers 21 times (~6 KB); the
        # first army with a list prints it, the rest name that army
        pools = sorted({m.pool for m in a.can_hire if m.pool})
        if hire_seen is not None and offers in hire_seen:
            line += f"\n  mercenaries for hire here: same as {hire_seen[offers]}"
            if pools:  # the first army's line says the pool is shared; the repeat names it
                line += f" (the {', '.join(pools)} pool)"
            return line
        else:
            line += "\n  mercenaries for hire here (florins, available/max, experience): " + offers
            if hire_seen is not None:
                hire_seen[offers] = a.id
        if pools:  # live 11-21: two armies hired the one Galloglaich their region's pool had
            line += f" (the {', '.join(pools)} pool, shared by every army of yours in this region)"
    elif a.leader and not a.is_fleet:
        # live 11-20: with nothing said, rulers ordered hires for generals whose pool offered none
        line += " (no mercenaries here)"
    return line


def _revolt(s) -> str:
    """Compact revolt/money facts for the settlement line, empty when there is nothing to say."""
    bits = []
    if s.rebelling:
        bits.append("FLAGGED TO REVOLT")
    if s.plagued:
        bits.append("plague")
    if s.turmoil:
        bits.append(f"turmoil {s.turmoil}")
    if s.rebel_chance:
        bits.append(f"rebel chance {s.rebel_chance}")
    if s.income is not None:
        tx = f" (taxes {s.taxes_income})" if s.taxes_income is not None else ""
        bits.append(f"income {s.income:+d}/turn{tx}")
    return ", ".join(bits)


def _turns(n: int) -> str:
    return f"{n} turn" if n == 1 else f"{n} turns"


def _garrison(s) -> str:
    if s.garrison_units or s.garrison_men:
        return f"garrison {s.garrison_units} units, {s.garrison_men} men (strength rating {s.garrison_strength}, not men)"
    if s.garrison_strength:
        return f"garrison strength rating {s.garrison_strength} (men unknown; not a head count)"
    return "garrison none"


def _match_advice(s, clock_by_settlement: dict[str, str] | None) -> str | None:
    # siege_clock names a settlement by its name, else its id
    return (clock_by_settlement or {}).get(s.name or s.id)


def _unit_prices_table(settlements) -> tuple[list[str], dict[str, tuple[int, int, int | None]]]:
    from collections import Counter
    unit_prices: dict[str, list[tuple[int, int, int | None]]] = {}
    for s in settlements:
        for u in s.can_recruit:
            unit_prices.setdefault(u.unit, []).append((u.cost, u.turns, u.upkeep))
        for a in s.can_recruit_agents:
            unit_prices.setdefault(a.agent, []).append((a.cost, a.turns, None))
    if not unit_prices:
        return [], {}

    table_prices: dict[str, tuple[int, int, int | None]] = {}
    lines = ["UNIT PRICES (florins/turns, upkeep a turn). free-slot: no upkeep while its town has free-upkeep slots left"]
    for name in sorted(unit_prices.keys()):
        best_price = Counter(unit_prices[name]).most_common(1)[0][0]
        table_prices[name] = best_price
        cost, turns, upkeep = best_price
        upk_str = f", upkeep {upkeep}" if upkeep is not None else ""
        free_str = ", free-slot" if is_free(name) else ""
        lines.append(f"- {name} {cost}/{turns}{upk_str}{free_str}")
    return lines, table_prices


SAME_AS_LEGEND = ('(a list that reads "same as X, plus [...], without [...]" is town X\'s list, printed in '
                  'full above, with those changes)')
# a reference must be this much shorter than the full list, or the list prints in full and
# becomes a base itself (a town of another culture then gives its neighbours a closer base)
SAME_AS_RATIO = 0.5


def _default_region(town_id: str) -> str:
    """The region most towns sit in: their own id plus "_Province" (58 of France's 59, live 11-23)."""
    return town_id.replace(" ", "_") + "_Province"


def town_legend(settlements, areas: tuple[str, ...]) -> str:
    """What a town line leaves out, said once: '' when it leaves nothing out."""
    said = []
    name = any(s.name == s.id for s in settlements)
    region = any(s.region == _default_region(s.id) for s in settlements)
    if name or region:
        said.append("a town's " + " and ".join(
            w for w, on in (("game name", name), ("region (<id>_Province)", region)) if on)
            + " print only when they differ from its id")
    if "build" in areas:
        said.append("no queue line: nothing being built; no can build line: nothing to build now")
    return f"({'; '.join(said)})" if said else ""


def _same_as(own: str, items: list[str], bases: list[tuple[str, list[str]]] | None, sep: str) -> str:
    """`items` in full, or "same as X, plus [..], without [..]" against a town whose list was
    printed in full, whichever is shorter (live 11-22: France's 64 towns repeated the same 20-odd
    recruits and buildings, 48 KB a turn). A list printed in full joins `bases`, so a reference
    never points at another reference."""
    full = sep.join(items)
    if bases is None or not items or len(set(items)) != len(items):
        return full
    cur, best = set(items), full
    for name, ref in bases:
        rs = set(ref)
        plus = [i for i in items if i not in rs]
        minus = [i for i in ref if i not in cur]
        text = (f"same as {name}" + (f", plus [{sep.join(plus)}]" if plus else "")
                + (f", without [{sep.join(minus)}]" if minus else ""))
        if len(text) <= SAME_AS_RATIO * len(full) and len(text) < len(best):
            best = text
    if best is full:
        bases.append((own, items))
    return best


def _settlement(s, areas: tuple[str, ...], garrison: list | None = None,
                clock_by_settlement: dict[str, str] | None = None,
                table_prices: dict[str, tuple[int, int, int | None]] | None = None,
                bases: dict[str, list] | None = None, brief: bool = False) -> str:
    """A town's entry. `brief` (a seat with lookups) leaves out its buildings, a calm town's
    public-order breakdown, recruits, retrain and agents: `town:<id>` returns them (town_details)."""
    # live 11-23: France's 59 town lines repeated "Arhus (Arhus), region Arhus_Province" and
    # "queue: empty" on nearly every town; the name and region print only when they differ, and
    # TOWN_LEGEND says what a missing one means. The id ends at the colon (seats/script.py::_ids).
    where = [f"at ({s.x},{s.y})"] if s.x is not None else []
    if s.port_x is not None:
        where.append(f"port at ({s.port_x},{s.port_y})")
    head = f"- {s.id}" + (f" ({s.name})" if s.name != s.id else "")
    if s.region != _default_region(s.id):
        head += f", region {s.region}"
    head += ": " + ", ".join(where + [_garrison(s)]) + f", population {s.population}"
    if not brief:
        head += (", buildings: "
                 f"{_same_as(s.id, list(s.buildings), None if bases is None else bases.setdefault('buildings', []), ', ') or 'none'}")
    if "recruit" in areas and not s.recruit_blocked and (slots := free_slots(s.buildings)):
        head += f"; free-upkeep slots {free_slots_left(s, garrison)} of {slots} left"
    # tax, order and revolt belong to the town's own line, not to whichever sub-line came last
    if {"build", "recruit", "taxes"} & set(areas) and s.tax_level:
        head += f"; tax {s.tax_level}, public order {s.public_order}%"
        # below 100% unrest grows; much lower and it riots and rebels (brief: only then)
        if s.order_parts and not (brief and s.public_order >= 100):
            head += " (" + _order_parts(s.order_parts) + ")"
    if rl := _revolt(s):
        head += "; " + rl
    line = head
    if s.damaged_buildings:
        line += "\n  damaged buildings: " + "; ".join(f"{d.name} ({d.hp}% health)" for d in s.damaged_buildings)
    if s.siege:
        g = s.siege
        head = ", ".join(f"{n} {w}" for n, w in ((g.units, "units"), (g.men, "men")) if n)
        tail = f"(strength rating {g.strength}, not men)" if g.strength is not None else ""
        size = f"{head} {tail}".strip()
        line += ("\n  UNDER SIEGE by " + (f"{g.by} ({g.faction})" if g.by else "an enemy army")
                 + (f", {size}" if size else "")
                 + (f", for {_turns(g.turns)} so far" if g.turns is not None else "")
                 + (f"; it can hold out {_turns(g.holdout)}" if g.holdout is not None else ""))
        if advice_line := _match_advice(s, clock_by_settlement):
            line += "\n  adviser's siege clock: " + advice_line
    if s.training:
        line += "\n  in training: " + "; ".join(f"{t.unit} (joins the garrison on turn {t.ready_turn})"
                                              for t in s.training)
    if "build" in areas:  # an empty queue and nothing to build print no line (TOWN_LEGEND)
        if s.queue:
            line += f"\n  queue: {', '.join(s.queue)}"
        if s.can_build:
            line += "\n  can build (florins/turns): " + "; ".join(
                f"{b.building} {b.cost}/{b.turns}" for b in s.can_build)
    if "recruit" in areas and s.recruit_queue:
        line += f"\n  recruiting: {', '.join(s.recruit_queue)}"
    if brief:
        return line
    if "recruit" in areas and s.recruit_blocked:
        line += "\n  can recruit: unknown while units are inside (march them out to recruit here)"
    elif "recruit" in areas:
        # free upkeep is the unit type's (free-slot in UNIT PRICES) and the town's slots left (header)
        entries = []
        for u in s.can_recruit:
            tbl = (table_prices or {}).get(u.unit)
            if tbl is not None and (u.cost, u.turns, u.upkeep) == tbl:
                entries.append(u.unit)
            else:
                upk_str = f", upkeep {u.upkeep}" if u.upkeep is not None else ""
                free_str = ", free-slot" if is_free(u.unit) else ""
                entries.append(f"{u.unit} {u.cost}/{u.turns}{upk_str}{free_str}")
        line += "\n  can recruit: " + (_same_as(s.id, entries, None if bases is None else
                                                  bases.setdefault("recruit", []), "; ") or "nothing")
        # what "retrain" would refill here: worn garrison units whose type the pool still offers
        # (live: a ruler ordered it five turns running at Nottingham, refused each time)
        worn = [t for t in (garrison or []) if t.max_soldiers and t.soldiers < t.max_soldiers]
        if worn:
            offered = {u.unit for u in s.can_recruit}
            can = [f"{t.type} ({t.soldiers}/{t.max_soldiers})" for t in worn if t.type in offered]
            line += ("\n  retrain would refill: " + ", ".join(can) if can else
                     "\n  retrain would refill nothing now: the pool offers none of its worn units' types")
    if "recruit" in areas and s.can_recruit_agents:
        agent_entries = []
        for a in s.can_recruit_agents:
            tbl = (table_prices or {}).get(a.agent)
            if tbl is not None and (a.cost, a.turns) == (tbl[0], tbl[1]):
                agent_entries.append(a.agent)
            else:
                agent_entries.append(f"{a.agent} {a.cost}/{a.turns}")
        line += "\n  can train agents: " + "; ".join(agent_entries)
    return line


def _troops(troops) -> str:
    """The troops line, identical units counted (3x Knights 40/40 exp 0) rather than repeated."""
    counts: dict[str, int] = {}
    for u in troops:
        key = f"{u.label} {u.soldiers}/{u.max_soldiers or u.soldiers} exp {u.exp}"
        counts[key] = counts.get(key, 0) + 1
    return "; ".join(f"{n}x {k}" if n > 1 else k for k, n in counts.items())


def _own_army(a: Army, areas: tuple[str, ...], settlements=(),
              hire_seen: dict[str, str] | None = None, brief: bool = False) -> str:
    """`brief`: a garrison under lookups: no troop list (town_details prints it)."""
    line, sub_sep, subs = _army(a, hire_seen).partition("\n")  # what follows joins the army's own line
    # a field army with no units left (not even a general's bodyguard) is gone by the next report:
    # live 11-05 (scratch turn 77-78) France's Captain Garnot showed 0 units, vanished, and the ruler
    # guessed at an ambush
    if a.units == 0 and not a.id.startswith("garrison:"):
        line += " — it has no units left, so the game removes it; expect it gone next turn"
    if a.is_fleet:  # which of your ports it lies beside, for boarding and landing
        beside = [s.id for s in settlements if s.port_x is not None
                  and max(abs(s.port_x - a.x), abs(s.port_y - a.y)) <= 1]
        if beside:
            line += f", beside the port of {', '.join(beside)}"
    if "armies" in areas and a.moves_max:
        line += f", moves {a.moves_left}/{a.moves_max}"
    line += sub_sep + subs  # live 11-23: "moves" used to land after the mercenary pool's text
    if "armies" in areas and a.troops and not brief:
        line += "\n  troops: " + _troops(a.troops)
        if merge := _merge_line(a.troops):
            line += "\n  " + merge
    elif "armies" in areas and a.troops and (merge := _merge_line(a.troops)).startswith("merge_units would combine:"):
        # live 11-23 turn 4525: the short garrison lost this line with its troops, and France
        # ordered merge_units blind on three garrisons, all refused (LOOKUP_LEGEND: no line, nothing)
        line += "\n  " + merge
    return line


def _merge_line(troops) -> str:
    """What merge_units would combine: two or more worn units of one type and armour/weapon
    level, bodyguards and retraining units aside (Unit.merge_group, the bridge's merge_key).
    (live 11-11 turn 179: England ordered it on 5 garrisons, each with one worn unit beside full
    ones, all refused "nothing to merge"; its note: "a refusal costs nothing"). Empty when no unit
    is worn, so full armies cost the prompt nothing."""
    worn: dict[str, list[str]] = {}
    for u in troops:
        if (g := u.merge_group()) is not None:
            worn.setdefault(g, []).append(f"{u.soldiers}/{u.max_soldiers}")
    can = [f"{t} ({', '.join(c)})" for t, c in worn.items() if len(c) >= 2]
    if can:
        return "merge_units would combine: " + "; ".join(can)
    return "merge_units would combine nothing (refused)" if worn else ""


def _agent_lines(agents) -> list[str]:
    """One line an agent; agents of one kind on one spot share a line (live 11-23: France's 181
    agents, priests in fives on one tile, 7.5 KB). A lone agent keeps `- <id>: <kind>, <where>`."""
    groups: dict[tuple[str, str], list[str]] = {}
    for a in agents:
        where = f"in {a.in_settlement}" if a.in_settlement else f"at ({a.x},{a.y})"
        groups.setdefault((a.kind, where), []).append(a.id)
    lines = []
    for (kind, where), ids in groups.items():
        if len(ids) > 1 and not any(", " in i for i in ids):  # a comma in a name would split it
            lines.append(f"- {len(ids)} {kind}s {where}: " + ", ".join(ids))
        else:
            lines += [f"- {i}: {kind}, {where}" for i in ids]
    return lines


def _family_brief(p) -> bool:
    """Who a short (lookups) family list keeps: the leader, the heir, generals and princesses."""
    return bool(p.role) or p.kind in ("general", "princess") or bool(p.now_serves)


def _family_section(report: StateReport, brief: bool = False) -> str | None:
    """`brief` (a seat with lookups): other living relatives are counted, and `family` lists them."""
    family = [p for p in report.family if p.family or p.role or p.kind == "princess"]
    if not family:
        return None
    if brief:
        others = [p for p in family if p.alive and not _family_brief(p)]
        if others:  # the dead kept here are those the kept living still point at
            gone = {id(p) for p in others}
            text = _family_section(report.model_copy(update={"family": [
                p for p in report.family if id(p) not in gone]}))
            return (text or "YOUR FAMILY") + (
                f"\n- and {len(others)} more living relatives (spouses, children; lookup \"family\" lists them)")
    living = [p for p in family if p.alive]
    living_parents = {p.parent for p in living if p.parent}
    living_spouses = {p.spouse for p in living if p.spouse} | {p.name for p in living}

    lines, dead = [], []
    unlisted_dead = 0
    for p in family:
        if p.alive:
            lines.append(_person(p, report))
        else:
            is_parent = p.name in living_parents
            is_spouse = p.name in living_spouses or (p.spouse and p.spouse in {m.name for m in living})
            d_turn = getattr(p, "death_turn", getattr(p, "turn_died", getattr(p, "died_turn", None)))
            is_recent = (d_turn is not None and 0 <= (report.turn - d_turn) <= 30)

            if not (is_parent or is_spouse or is_recent):
                unlisted_dead += 1
            elif p.now_serves:
                lines.append(_person(p, report))
            else:  # live 11-23: France's 77 dead took a line each (2.6 KB); they share one now
                dead.append(p.name + (f" (at {p.age})" if p.age is not None else ""))

    if dead:
        lines.append("- dead: " + "; ".join(dead))
    if unlisted_dead > 0:
        lines.append(f"- and {unlisted_dead} more dead relatives (not listed)")

    return ("YOUR FAMILY (from the game's records; only recent dead are listed; spouses are of your "
            "faction unless one is named)\n" + "\n".join(lines))


LOOKUP_LEGEND = ("(short entries: each town's buildings, full public-order breakdown (printed here only "
                 "below 100%), recruits with prices, retrain and agents, and its garrison's troops, come "
                 "back when you answer with \"lookup\": [\"town:<id>\", ...] and no orders; "
                 "\"town:all\" returns every town and \"family\" every living relative. Look up a town "
                 "before you recruit there. A garrison with no merge_units line has nothing to merge)")


def town_details(report: StateReport, keys: list[str], areas: tuple[str, ...]) -> str:
    """Pass 2 of a lookup turn: each asked-for town's full entry, exactly as the full prompt prints
    it, with its garrison's full army entry and the prices of what it can recruit."""
    def norm(text: str) -> str:
        return "_".join(text.lower().replace("_", " ").split())

    by_key: dict[str, object] = {}
    for s in report.settlements:
        by_key.setdefault(norm(s.name), s)
    for s in report.settlements:
        by_key[norm(s.id)] = s  # an id beats another town's game name
    want, unknown, family = [], [], False
    for k in keys:
        key = k.strip()
        if key.lower() == "family":
            family = True
            continue
        name = key[5:].strip() if key.lower().startswith("town:") else key
        if name.lower() == "all":
            want = list(report.settlements)
            continue
        s = by_key.get(norm(name))
        if s is None:
            unknown.append(key)
        elif s not in want:
            want.append(s)
    try:
        clock = {a.settlement: a.line for a in siege_clock(report)}
    except Exception as exc:
        log.warning("siege_clock failed: %s", exc)
        clock = {}
    lines: list[str] = []
    table_prices: dict = {}
    if want and "recruit" in areas:
        table, table_prices = _unit_prices_table(want)
        lines += table
    bases: dict[str, list] = {}
    towns = []
    hire_seen: dict[str, str] = {}
    for s in want:
        g = next((a for a in report.armies if a.id == f"garrison:{s.id}"), None)
        towns.append(_settlement(s, areas, g.troops if g else None, clock_by_settlement=clock,
                                 table_prices=table_prices, bases=bases))
        if g is not None:
            towns.append(_own_army(g, areas, report.settlements, hire_seen))
    if any("same as " in t for t in towns):
        towns.insert(0, SAME_AS_LEGEND)
    if want and (legend := town_legend(want, areas)):
        towns.insert(0, legend)
    lines += towns
    lines += [f"- {k}: not a town of yours (lookups take town:<id>, town:all or family)" for k in unknown]
    text = "DETAILS YOU ASKED FOR\n" + ("\n".join(lines) or ("" if family else "- nothing"))
    if family:
        text = text.rstrip("\n") + "\n\n" + (_family_section(report) or "YOUR FAMILY\n- none")
    return text


def state_summary(report: StateReport, areas: tuple[str, ...] = PRESETS["ruler"],
                  ruled: set[str] | None = None, lookups: bool = False) -> list[str]:
    """The ruler's realm as text sections: treasury, settlements, armies, factions, enemies.
    Build and recruit options, taxes and troops show only for areas the ruler commands.
    `lookups`: short town entries and no garrison troops; town_details has the rest."""
    parts = [
        f"TURN {report.turn}, YEAR {report.year}. You rule {report.faction}.\n"
        f"Treasury: {report.treasury} florins at the end of your last turn (orders are paid from this "
        "balance; this turn's income has not arrived yet). "
        + (f"Income: {report.income} per turn after upkeep and wages." if report.income else
           "Income: not reported (compare treasury between turns).")
    ]
    if report.map_width and report.map_height:  # live 11-22: England ordered moves to (100,200) on a 295x189 map
        parts[0] += (f"\nMap: {report.map_width} x {report.map_height} tiles (x 0-{report.map_width - 1}, "
                     f"y 0-{report.map_height - 1}).")
    if report.income_parts:  # what makes up that income, largest first (costs negative)
        parts[0] += "\nIncome items: " + ", ".join(
            f"{k} {v:+d}" for k, v in sorted(report.income_parts.items(), key=lambda kv: -abs(kv[1]))) + "."
    if report.spent_last_turn or report.received_last_turn:
        parts[0] += (f" Last turn you also spent {report.spent_last_turn} on buildings, recruits and diplomacy (bribes, gifts)"
                     + (f" and received {report.received_last_turn} in gifts" if report.received_last_turn else "")
                     + ".")
    clock_by_settlement: dict[str, str] = {}
    try:
        clock_by_settlement = {a.settlement: a.line for a in siege_clock(report)}
    except Exception as exc:
        log.warning("siege_clock failed: %s", exc)
    if report.settlements:
        table_lines = []
        table_prices = {}
        if "recruit" in areas and not lookups:
            table_lines, table_prices = _unit_prices_table(report.settlements)
        bases: dict[str, list] = {}
        settlement_lines = [
            _settlement(s, areas, next((a.troops for a in report.armies if a.id == f"garrison:{s.id}"), None),
                        clock_by_settlement=clock_by_settlement, table_prices=table_prices, bases=bases,
                        brief=lookups)
            for s in report.settlements
        ]
        if any("same as " in x for x in settlement_lines):
            settlement_lines.insert(0, SAME_AS_LEGEND)
        if legend := town_legend(report.settlements, areas):
            settlement_lines.insert(0, legend)
        if lookups:
            settlement_lines.insert(0, LOOKUP_LEGEND)
        all_lines = (table_lines + settlement_lines) if table_lines else settlement_lines
        parts.append("YOUR SETTLEMENTS\n" + "\n".join(all_lines))
    else:
        parts.append("YOUR SETTLEMENTS\n- none")
    hire_seen: dict[str, str] = {}  # offers text -> the first army that printed it
    parts.append("YOUR ARMIES (a strength rating is not a head count: a general's bodyguard of a few dozen "
                 "men rates in the thousands. Count men; walls need siege equipment before you storm)\n" + ("\n".join(_own_army(a, areas, report.settlements, hire_seen,
                                                        brief=lookups and a.id.startswith("garrison:"))
                                              for a in report.armies) or "- none"))
    if report.agent_results:
        parts.append("YOUR AGENTS' MISSIONS SINCE YOUR LAST TURN (from the game itself)\n"
                     + "\n".join(f"- {a}" for a in report.agent_results))
    if report.popups:
        parts.append("GAME POPUPS SINCE YOUR LAST TURN (answered for you; the game shows no text "
                     "here, only what kind they were)\n" + "\n".join(f"- {p}" for p in report.popups))
    if report.agents:
        parts.append("YOUR AGENTS\n" + "\n".join(_agent_lines(report.agents)))
    if report.agent_limits:  # the game's limits: buildings that train a kind raise its limit
        parts.append("AGENT LIMITS (yours, counting those in training / most you may have)\n" + "; ".join(
            f"{k} {v.have}/{'no limit' if v.limit is None else v.limit}"
            for k, v in sorted(report.agent_limits.items())))
    if family_text := _family_section(report, brief=lookups):
        parts.append(family_text)
    if report.character_events:
        parts.append("WHAT BEFELL YOUR PEOPLE SINCE YOUR LAST TURN (from the game itself)\n"
                     + "\n".join(f"- {e}" for e in report.character_events))
    if report.news:
        parts.append("NEWS SINCE YOUR LAST TURN (from the game itself: missions, riots, treaties, crusades)\n"
                     + "\n".join(f"- {e}" for e in report.news))
    if report.stance_changes:
        parts.append("WAR AND PEACE SINCE YOUR LAST TURN (from the game itself: who changed what)\n"
                     + "\n".join(f"- {c}" for c in report.stance_changes)
                     + "\nAny ruler may set war or peace alone, and it binds both sides at once. For a "
                     "faction with a ruler (one you can message), its game AI may not: what it changes "
                     "without the ruler's order is undone, so such a change was nobody's choice. A "
                     "faction with no ruler is played by the game's AI alone: its wars are real, and "
                     "setting peace with it does not stop its armies, which may go on besieging and "
                     "attacking you (live: Spain took Rennes under a peace set by England). Judge such "
                     "a faction by what its armies do, not by the stance. "
                     "Attacking a faction you are at peace with breaks a treaty and harms your "
                     "reputation with every court; declare war first if you mean to fight.")
    # live: England set peace with Spain, an AI-run faction, turn after turn, and lost Rennes to it
    parts.append("OTHER FACTIONS (stance with you). A faction with a ruler answers messages, and its game "
                 "AI's wars are undone. One run by the game's AI alone makes real wars, and setting peace with it does "
                 "not stop its armies: judge it by what its armies do\n"
                 + (_factions(report, ruled) or "- none"))
    parts.append(SIGHT_NOTE)
    parts.append("FOREIGN ARMIES IN SIGHT\n" + ("\n".join(map(_foreign_army, report.visible_enemies)) or "- none"))
    parts.append("FOREIGN AGENTS IN SIGHT\n" + (_foreign_agents(report.seen_agents) or "- none"))
    if report.crossings:
        parts.append("LAND CROSSINGS NEAR YOU (an army walks across the water here, no ships needed: "
                     "move_army onto the land tile on the far side)\n" + "\n".join(
                         f"- at ({c.x},{c.y}), joining {_crossing_shores(c)}{_away(c.distance)}"
                         for c in report.crossings))
    if report.resources:
        shown = report.resources[:RESOURCES_SHOWN]
        parts.append("TRADE RESOURCES IN SIGHT (a merchant standing on one trades there every turn)\n"
                     + "\n".join(f"- {r.kind} at ({r.x},{r.y}), {r.region}"
                                 + (f", value {r.value}" if r.value is not None else "")
                                 + (f", held by {r.owner}" if r.owner else "") + _away(r.distance)
                                 for r in shown)
                     + (f"\n(and {len(report.resources) - len(shown)} farther ones)"
                        if len(report.resources) > len(shown) else ""))
    parts.append("SETTLEMENTS NEAR YOU\n" + ("\n".join(
        f"- {s.id} ({s.faction}): {_garrison(s)}, at ({s.x},{s.y}){_away(s.distance)}{_by_sea(s)}"
        for s in report.nearby_settlements) or "- none"))
    if report.remembered:
        parts.append("SETTLEMENTS SEEN BEFORE (out of sight now, as last seen; the rest of the map is "
                     "unexplored)\n" + "\n".join(
            f"- {s.id} ({s.faction}): {_garrison(s)}, at ({s.x},{s.y}), seen turn {s.seen_turn}"
            for s in report.remembered))
    return parts


def _by_sea(s) -> str:
    """Marks a settlement none of the faction's armies can walk to (the bridge's land check)."""
    return " (across the sea: needs a fleet)" if s.by_land is False else ""


def _crossing_shores(c) -> str:
    """Each side's region with the land tile to step onto (older reports name regions only)."""
    if c.shores:
        return " and ".join(f"{s.region} ({s.x},{s.y})" for s in c.shores)
    return " and ".join(c.regions) or "two shores"


def _whereabouts(p, report) -> str:
    """Where a living family member stands: the army he leads, the settlement he's in, or a tile
    (Scratch, live: "Missing: where Garret Harrold is standing, and which army he leads")."""
    if p.x is None:
        return ""
    if report is not None:
        led = next((a for a in report.armies if a.leader == p.name), None)
        if led:
            return f", leads {led.id}" + (f" in {led.in_settlement}" if led.in_settlement else f" at ({led.x},{led.y})")
        town = next((s for s in report.settlements if (s.x, s.y) == (p.x, p.y)), None)
        if town:
            return f", in {town.id}"
    return f", at ({p.x},{p.y})"


def _person(p, report=None) -> str:
    age = f", {p.age}" if p.age is not None else ""
    if not p.alive and p.now_serves:
        return f"- {p.name}: left your service, alive and now with {p.now_serves}"
    if not p.alive:
        return f"- {p.name}: dead" + (f" (at {p.age})" if p.age is not None else "")
    what = [w for w in (p.role, p.kind) if w]
    line = f"- {p.name}{age}" + (f", {', '.join(what)}" if what else "")
    if p.spouse:
        own = report is not None and p.spouse_faction == report.faction  # the header says "unless named"
        line += f", married to {p.spouse}" + (f" ({p.spouse_faction})" if p.spouse_faction and not own else "")
    elif p.kind == "princess":
        line += ", unmarried: her hand can be offered to a foreign general in sight (\"marry\")"
    if p.parent:
        line += f", child of {p.parent}"
    if p.off_map:
        line += ", off the map"
    else:
        line += _whereabouts(p, report)
    return line


SIGHT_NOTE = ("You see only what your armies, agents and settlements can see. Use only names, "
              "settlements and positions listed here.")


def _away(distance: int | None) -> str:
    return f", {distance} {'tile' if distance == 1 else 'tiles'} away" if distance is not None else ""


# The game keeps each part of public order as a count of 5% steps, every one positive; these
# take away. Live, London: 100 + 5 x (bonuses 21 - penalties 25) = 80%, as its panel shows.
ORDER_PENALTIES = {"high tax", "squalor", "unrest", "cultural unrest", "distance to capital",
                   "excommunication", "no governor", "besieged", "blockaded"}


def _order_parts(parts: dict[str, int]) -> str:
    pct = {k: (-5 if k in ORDER_PENALTIES else 5) * abs(v) for k, v in parts.items()}
    return ", ".join(f"{k} {v:+d}%" for k, v in sorted(pct.items(), key=lambda kv: -abs(kv[1])))


def _faction(f, ruled: set[str] | None = None) -> str:
    line = f"- {f.id} ({f.name}): {f.stance}"
    if f.turns_in_stance:
        line += f" for {f.turns_in_stance} turns"
    if f.treaties:
        line += f" ({', '.join(f.treaties)})"
    if ruled is not None:
        line += ", has a ruler" if f.id in ruled else ", run by the game's AI"
    if f.settlements == 0:
        return line + "; destroyed (no settlements left)" if not f.armies else \
            line + f"; holds no settlement, {f.armies} armies still in the field"
    facts = [f"{f.settlements} settlements"] if f.settlements is not None else []
    if f.capital:
        facts.append(f"capital {f.capital}")
    if f.leader:
        facts.append(f"led by {f.leader}")
    if f.armies is not None:
        facts.append(f"{f.armies} armies")
    return line + (f"; {', '.join(facts)}" if facts else "")


def _factions(report: StateReport, ruled: set[str] | None) -> str:
    """One line each for the factions that matter now (war, alliance, treaties, a ruler, anything of
    theirs in sight); the quiet far-off ones at peace are grouped to a name and a size."""
    near = ({a.faction for a in report.visible_enemies} | {a.faction for a in report.seen_agents}
            | {s.faction for s in report.nearby_settlements})
    lines, quiet, dead = [], [], []
    for f in report.factions:
        if f.settlements == 0 and not f.armies:
            dead.append(f.id)
        elif (f.stance == "peace" and not f.treaties and f.id not in near
              and (ruled is None or f.id not in ruled) and f.settlements is not None):
            quiet.append(f"{f.id} ({f.settlements})")
        else:
            lines.append(_faction(f, ruled))
    if quiet:
        lines.append("- At peace with no treaties, nothing of theirs in sight, run by the game's AI "
                     "(settlements): " + ", ".join(quiet))
    if dead:
        lines.append("- Destroyed: " + ", ".join(dead))
    return "\n".join(lines)


def _foreign_agents(agents) -> str:
    """One line per faction, kind and tile: agents standing together are named on one line."""
    groups: dict[tuple, list] = {}
    for a in agents:
        groups.setdefault((a.faction, a.kind, a.x, a.y, a.distance), []).append(a.id)
    return "\n".join(
        f"- {faction} {kind} at ({x},{y}){_away(d)}: " + ", ".join(ids)
        for (faction, kind, x, y, d), ids in groups.items())


def _foreign_troops(troops) -> str:
    """A foreign army's makeup: "4x Mailed Knights (cavalry), 2x Peasant Archers (missile)"."""
    counts: dict[str, int] = {}
    for u in troops:
        counts[u.type] = counts.get(u.type, 0) + 1
    parts = []
    for name, n in counts.items():
        role = (unit_info(name) or {}).get("role")
        parts.append((f"{n}x {name}" if n > 1 else name) + (f" ({role})" if role else ""))
    return ", ".join(parts)


def _foreign_army(a: Army) -> str:
    # the id is what orders must name; the leader only when it says something more
    who = f"{a.id} ({a.faction})" if a.faction else a.id
    if a.leader and a.leader != a.id:
        who += f", led by {a.leader}"
    where = f"in {a.in_settlement}" if a.in_settlement else f"at ({a.x},{a.y})"
    if a.from_x is not None:  # seen last turn elsewhere: the way it is heading
        where += f" (last turn at ({a.from_x},{a.from_y}))"
    if a.is_fleet:  # its units are ships; the army it carries is the invasion
        ships = f"a fleet of {a.units} ship{'s' if a.units != 1 else ''}"
        if a.carrying:
            cargo = f" ({a.carrying_men} men)" if a.carrying_men else ""
            ships += f", carrying an army of {a.carrying} units{cargo}"
        else:
            ships += ", empty"
        return f"- {who}: {ships}, {where}{_away(a.distance)}"
    if a.aboard:
        where = f"at sea aboard {a.aboard}, {where}"
    men = f", {a.men} men" if a.men else ""
    line = f"- {who}: {a.units} units{men} (strength rating {a.strength}, not men), {where}{_away(a.distance)}"
    if a.troops:
        line += "\n  troops: " + _foreign_troops(a.troops)
        if a.units > len(a.troops):
            line += f", and {a.units - len(a.troops)} more"
    return line


def _debt_block(report: StateReport) -> str:
    # live: an LLM ruler in debt entered a passive loop issuing build/recruit orders that
    # the validator refused, unaware that orders costing gold are blocked while in debt
    lines = [
        f"IN DEBT (Treasury: {report.treasury} florins)\n"
        "Orders costing gold are refused while the treasury is negative; everything else works. "
        "Debt is fine while it buys a gain: taking a town brings its income and the gold from "
        "capturing it. If the debt buys nothing, these free levers clear it:"
    ]

    armies_lines = []
    for a in report.armies:
        upkeep = f", upkeep {a.upkeep}" if getattr(a, "upkeep", None) is not None else ""
        armies_lines.append(f"- {a.id}: {a.units} units{upkeep}")
    lines.append("Armies (\"disband\" cuts upkeep, but only for units that serve no goal):\n" + ("\n".join(armies_lines) if armies_lines else "- none"))

    settlement_lines = []
    for s in report.settlements:
        tax_str = f"tax level {s.tax_level}" if s.tax_level else "tax level not set"
        if s.public_order is not None:
            tax_str += f", public order {s.public_order}%"
        settlement_lines.append(f"- {s.id}: {tax_str}")
    lines.append("Settlements (for \"set_tax\" to raise revenue):\n" + ("\n".join(settlement_lines) if settlement_lines else "- none"))

    war_factions = {f.id for f in report.factions if f.stance == "war"}
    hostile = [s for s in report.nearby_settlements
               if s.faction in war_factions or s.faction.lower() in ("rebels", "slave", "rebel")]
    hostile_lines = [
        f"- {s.id} ({s.faction}): garrison {s.garrison_units} units, {s.garrison_men} men"
        for s in hostile
    ]
    lines.append("Enemy and rebel settlements in sight (for \"march_on\" or \"besiege\"):\n" +
                 ("\n".join(hostile_lines) if hostile_lines else "- none in sight"))

    lines.append("In your note, write one line per army: an order, or why none.")
    return "\n\n".join(lines)


RESOURCES_SHOWN = 8  # nearest trade resources listed
NOTES_SHOWN = 2     # most recent notes replayed to the ruler
DIPLOMACY_SHOWN = 10 # most recent diplomacy lines
DIPLOMACY_CHARS = 380  # longest line shown, cut short beyond this
REFUSAL_LINES = 8  # most lines the refusal block shows
BRIEF_CHARS = 110


def order_brief(order) -> str:
    """An order in a few words: its type and fields, cut short."""
    fields = {k: v for k, v in order.model_dump().items() if k != "type" and v not in (None, "", [], {})}
    text = f"{order.type} " + ", ".join(f"{k}={v}" for k, v in fields.items())
    text = text.strip()
    return text if len(text) <= BRIEF_CHARS else text[:BRIEF_CHARS - 1] + "…"


def refusal_block(results, history: list[set[str]]) -> str:
    """The top-of-prompt block for last turn's refused orders: one line per distinct refusal
    (same type and shaped reason, as audit.py compares them), most-repeated first, with how many
    turns running it has come back (history: refusal keys of each earlier turn, newest first)."""
    groups: dict[str, list] = {}
    for r in results:
        if not r.ok:
            groups.setdefault(refusal_key(r.type, r.reason), []).append(r)
    if not groups:
        return ""
    rows = []
    for key, rs in groups.items():
        run = 1
        for earlier in history:
            if key not in earlier:
                break
            run += 1
        rows.append((run, key, rs))
    rows.sort(key=lambda row: -row[0])  # stable: ties keep the order given
    lines = []
    for run, _, rs in rows[:REFUSAL_LINES]:
        first = rs[0]
        what = first.brief or first.type
        more = f" (and {len(rs) - 1} like it)" if len(rs) > 1 else ""
        again = f" Refused {run} turns running." if run > 1 else ""
        lines.append(f"- {what}{more}: {first.reason}.{again}".replace("..", "."))
    if len(rows) > REFUSAL_LINES:
        lines.append(f"- ...and {len(rows) - REFUSAL_LINES} other refusals.")
    return "YOUR ORDERS REFUSED LAST TURN: don't give these again as they were\n" + "\n".join(lines)


def faction_note(faction: str) -> str:
    """Strategy notes for one faction (parley/strategy/<faction>.md). Empty if there is no file."""
    if not faction or not faction.replace("_", "").isalnum():
        return ""
    try:
        return (STRATEGY_DIR / f"{faction}.md").read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""


def build_prompt(report: StateReport, persona: str, scenario: str = "",
                 diplomacy: list | None = None, names: dict[str, str] | None = None,
                 notes: list[tuple[int, str]] | None = None, events: list[str] | None = None,
                 areas: tuple[str, ...] = PRESETS["ruler"], adviser: str = "",
                 game_messages: list[str] | None = None, plan: str = "",
                 lessons: list[str] | None = None,
                 playtest_funds: bool = False,
                 playtest_funds_amount: int = 50000, victory: str | None = None,
                 refusal_history: list[set[str]] | None = None, lookups: bool = False) -> str:
    """`lookups` (spec 2026-11-23-ruler-lookups-design): short town entries; the ruler may answer
    with "lookup" first and gets town_details back in a second pass."""
    parts = [persona.strip()]
    if scenario:
        parts.append(f"SCENARIO\n{scenario.strip()}")
    if victory:
        parts.append(f"YOUR GOAL\n{victory}")
    if text := primer():
        parts.append("HOW THE GAME WORKS (a primer; your report and order rules below take precedence)\n" + text)
    if text := faction_note(report.faction):
        parts.append(f"HOW {report.faction.upper()} WINS (strategy notes for your faction; your report takes precedence)\n" + text)
    parts.append(role(areas, report.human_slot))
    if playtest_funds:
        parts.append(f"PLAYTEST: your treasury is topped up to {playtest_funds_amount} florins at the start of each turn; money is not a constraint in this test.")
    if adviser:
        parts.append(adviser_section(adviser))
        names = {**(names or {}), f"adviser:{report.faction}": adviser}
    if block := refusal_block(report.last_results, refusal_history or []):
        parts.append(block)
    if block := threats_block(report):
        parts.append(block)
    ruled = {k for k in names if not k.startswith("adviser:")} if names else None  # seats and humans
    parts += state_summary(report, areas, ruled, lookups=lookups)
    if report.treasury < 0 and not playtest_funds:
        parts.append(_debt_block(report))
    if warn := tax_warning(report):
        parts.append(warn)
    if shown := [r for r in report.last_results if r.ok]:  # refusals are up top, in their own block
        parts.append("LAST TURN'S ORDER RESULTS\n" + "\n".join(
            f"- order {r.index} ({r.type}): {('done: ' + r.note) if (r.ok and r.note) else ('done' if r.ok else 'REJECTED: ' + r.reason)}"
            + (f". Now: {r.now}" if r.now else "")
            for r in shown))
    if report.moves_not_made:
        def _move_line(m) -> str:
            if m.order_type == "attack":
                at = f" to ({m.target_x},{m.target_y})" if m.target_x is not None else ""
                return f"{m.id}'s attack on {m.target} came to no battle: {m.target} stepped away{at}, no men lost."
            verb = "march" if m.order_type in ("march_on", "besiege", "march") else ("withdrawal" if m.order_type == "withdraw" else "move")
            moves = f" with {m.moves_left} moves left." if m.moves_left is not None else "."
            return f"{m.id}'s {verb} to {m.target} did not happen: still at ({m.from_x},{m.from_y}){moves}"

        parts.append("MOVES THAT DID NOT HAPPEN\n" + "\n".join(
            _move_line(m) for m in report.moves_not_made))
    if events:
        parts.append("SINCE YOUR LAST TURN\n" + "\n".join(f"- {e}" for e in events))
    if game_messages:
        parts.append("GAME MESSAGES SINCE YOUR LAST TURN (read from the screen: missions, news, offers)\n"
                     + "\n\n".join(m.strip() for m in game_messages))
    parts.append("YOUR STANDING PLAN (from your last turn: 1-3 goals, each with its next step and target turn)\n"
                 + plan if plan else "YOUR STANDING PLAN\n(none yet: write one)")
    if lessons:
        parts.append("LESSONS FROM YOUR PAST GAMES (reviews of your own earlier play; weigh them, they can be "
                     "wrong, and this game's report comes first)\n" + "\n".join(f"- {x}" for x in lessons))
    if notes:
        parts.append("YOUR RECENT NOTES (your own private plans, oldest first)\n" + "\n".join(
            f"[turn {t}] {n}" for t, n in notes[-NOTES_SHOWN:]))
    if diplomacy:
        names = names or {}
        parts.append(diplomacy_section([_diplomacy_line(m, report.faction, names) for m in diplomacy]))
    parts.append(RULES + "\n" + "\n".join(ORDER_HELP[a] for a in areas if a in ORDER_HELP)
                 + ("\n" + LOOKUP_RULE if lookups else ""))
    return "\n\n".join(parts) + "\n"


LOOKUP_RULE = ("- lookup: to see towns' full entries (or \"family\") first, answer only {\"lookup\": [\"town:<id>\", ...]} "
               "with no orders; they come back and you then give this turn's orders. One lookup a turn.")
LOOKUP_ANSWERED = ("\n{details}\n\nThose are the details you asked for. Give this turn's orders now "
                   "(no more lookups this turn).\n")
