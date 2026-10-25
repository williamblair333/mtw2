"""Turn a state report into the text an LLM seat reads."""

from parley.control import AREAS, PRESETS
from parley.protocol import Army, StateReport

ROLE = (
    "You are the ruler. Your generals handle routine moves: recruiting, building and "
    "ordinary army movement. Give only diplomatic orders and specific override orders "
    "that matter this turn."
)

HUMAN_SLOT_ROLE = ("No game AI acts for this realm, and no governor recruits or builds for you: "
                   "what you don't order doesn't happen. Nobody else will raise your armies.")
AI_ASSIST_ROLE = ("The game's own AI also acts for this realm between your orders (recruiting, "
                  "building and moving armies); your orders come first.")

ORDER_HELP = {
    "diplomacy": '- Diplomacy orders: "send_gold", "cede_settlement", "set_stance".',
    "armies": '- Army orders: "march_on" (toward a settlement), "move_army" (toward a tile x,y), "attack" (a foreign army in sight, outside a settlement), "besiege" (add "assault": true to storm it now; otherwise you wait while it starves; walls need siege equipment, a village has none), "withdraw", "merge_armies" (one of your armies, a garrison too, walks to join another; 20 units at most; the joining happens as it walks, so an attack ordered in the same turn fights with the army as it stood before: merge one turn, attack the next; to move a garrison that has no general, merge it into an army that has a general, or march the general into the settlement). Name an army by its id. "move_army" also takes a general\'s own name (from YOUR FAMILY) as the army: he steps out alone with his bodyguard, even from a garrison he doesn\'t lead. That is how a field army is made: step a general out of a settlement by name onto a tile beside it, then "merge_armies" the garrison (or other armies) into him the next turn; a general sitting in a garrison is an army waiting to be formed, not a missing one. A land army moves only onto land; an order onto sea is refused with the nearest land tile. An army goes only as far as its moves allow; it continues next turn only if you order it again. Ships: a fleet sails with "move_army" to a sea tile; "board" puts an army (by its id) or an agent aboard one of your fleets standing next to it (one army per fleet); "land" puts an army aboard ashore on a land tile next to its fleet; "blockade" closes a foreign port with a fleet; "attack" works fleet against fleet. Crossing water: board, sail, land, over several turns. "merge_units" (an army by its id) folds that army\'s under-strength units of the same type together, as the game\'s own merge does: soldiers move into the fullest units, and emptied units disband (a general\'s bodyguard is never touched). It costs nothing and no moves. \"disband\" (an army by its id, a unit type from its troops list, and a count, 1 if left out) releases that many units of that type, the weakest first, to save their upkeep; a general\'s bodyguard is never released.\n'
               "- STANDING RULE, every turn: look over each army's troops. Only where an army holds two or more units of the same type that are both below full strength (for example four Hobilars, some under half), order \"merge_units\" for that army; an army whose units are full, or all of different types, needs no merge. Keep your units at full strength as much as possible: a few full units fight far better than many weak ones.",
    "build": '- "build": queue a building from a settlement\'s "can build" list. It costs its price when queued; a settlement builds one thing at a time. Never order what is already in its queue: it is coming.',
    "recruit": '- "recruit": a unit from a settlement\'s "can recruit" list. You pay its price now; it joins that settlement\'s garrison when trained (usually next turn). Nobody recruits for you: if you want an army, recruit it. "retrain" (a settlement) refills its damaged garrison units whose type that settlement can still recruit (one from its recruitment pool each, as the game does), for the missing share of the unit\'s price; the men arrive next turn. Bring damaged units into a settlement that can recruit their type first.',
    "taxes": '- "set_tax": low, normal, high or extortionate. Higher taxes bring gold and lower public order; a settlement below about 70% public order risks riots and revolt.',
    "agents": '- Agent orders: "assassinate" (your own assassin, a character in sight), "sabotage" (your own assassin, a settlement in sight), "spy" (your own spy, a settlement or character in sight), "bribe" (your own diplomat, a character or settlement in sight). Targets must come from your sight lists. "move_agent" walks any of your agents (a princess too) toward a tile x,y; agents cannot cross the sea on their own. Merchants: move_agent one onto a tile from TRADE RESOURCES IN SIGHT and he trades there each turn he stands on it; valuable resources far from your own lands pay more, and rival merchants may try to take his trade. "marry": your princess offers her hand to a foreign general in sight. Each agent acts once a turn. Agents may fail or die; the next report tells you.',
}


def adviser_section(adviser: str) -> str:
    return (f"YOUR ADVISER\n{adviser} is your loyal adviser: a human who wants you to win and "
            "has no throne of their own. Weigh their counsel. Follow it when it's sound, overrule "
            "it when you know better, and tell them why either way. Ask them for counsel, not for facts: "
            "your report holds everything the game shows you. If it lacks something you need to know, "
            "write \"Missing: <what>\" in your note and it will be added. Never reveal them to other rulers. Write to them with {\"to\": \"adviser\"}: every "
            "turn at least one short message on what you did and why (they read it on Discord; a silent "
            "turn leaves them guessing), at most 3. "
            "What you told them between turns is in the thread above: if you promised something there, "
            "order it now or tell them plainly why not.")


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
- To speak, add "messages": {"to": "lobby"} is public to everyone; {"to": "<faction id>"} is private to that faction. At most 3 per recipient per turn, 600 characters each.
- Speak only when you have something new to say; don't repeat what you already said in earlier turns.
- Put your private reasoning in "note"; no other faction sees it. Never put private reasoning in a message. Your notes come back to you next turn, so record plans, grudges and promises there. A human reads your notes too: write plain sentences in short paragraphs, one topic each, separated by blank lines, and no shorthand like "T17" or "+2279".
- An order result of "done" means the order was carried out, not that it succeeded; check your next report for what actually happened."""

DIPLOMACY_HEADER = (
    "DIPLOMACY (most recent last)\n"
    "Public messages are seen by everyone; private ones only by the two sides. "
    "Promises bind nothing in the game: a deal is kept only if someone acts on it.")


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


def _army(a: Army) -> str:
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
    men = f", {sum(t.soldiers for t in a.troops)} men" if a.troops else ""
    return f"- {a.id}: {a.units} units{men}, strength rating {a.strength}, {where}{leader}"


def _turns(n: int) -> str:
    return f"{n} turn" if n == 1 else f"{n} turns"


def _settlement(s, areas: tuple[str, ...], garrison: list | None = None) -> str:
    where = f" at ({s.x},{s.y})" if s.x is not None else ""
    if s.port_x is not None:
        where += f", port at ({s.port_x},{s.port_y})"
    line = (f"- {s.id} ({s.name}), region {s.region}{where}: garrison {s.garrison_strength}, "
            f"population {s.population}, buildings: {', '.join(s.buildings) or 'none'}")
    if s.siege:
        g = s.siege
        line += ("\n  UNDER SIEGE by " + (f"{g.by} ({g.faction})" if g.by else "an enemy army")
                 + (f", strength {g.strength}" if g.strength is not None else "")
                 + (f", for {_turns(g.turns)} so far" if g.turns is not None else "")
                 + (f"; it can hold out {_turns(g.holdout)}" if g.holdout is not None else ""))
    if s.training:
        line += "\n  in training: " + "; ".join(f"{t.unit} (joins the garrison on turn {t.ready_turn})"
                                              for t in s.training)
    if {"build", "recruit", "taxes"} & set(areas) and s.tax_level:
        line += f"; tax {s.tax_level}, public order {s.public_order}%"
        if s.order_parts:  # below 100% unrest grows; much lower and it riots and rebels
            line += " (" + _order_parts(s.order_parts) + ")"
    if "build" in areas:
        line += f"\n  queue: {', '.join(s.queue) or 'empty'}"
        line += "\n  can build: " + ("; ".join(
            f"{b.building} ({b.cost} florins, {_turns(b.turns)})" for b in s.can_build) or "nothing")
    if "recruit" in areas and s.recruit_blocked:
        line += "\n  can recruit: unknown while units are inside (march them out to recruit here)"
    elif "recruit" in areas:
        line += "\n  can recruit: " + ("; ".join(
            f"{u.unit} ({u.cost} florins, {_turns(u.turns)})" for u in s.can_recruit) or "nothing")
        # what "retrain" would refill here: worn garrison units whose type the pool still offers
        # (live: a ruler ordered it five turns running at Nottingham, refused each time)
        worn = [t for t in (garrison or []) if t.max_soldiers and t.soldiers < t.max_soldiers]
        if worn:
            offered = {u.unit for u in s.can_recruit}
            can = [f"{t.type} ({t.soldiers}/{t.max_soldiers})" for t in worn if t.type in offered]
            line += ("\n  retrain would refill: " + ", ".join(can) if can else
                     "\n  retrain would refill nothing now: the pool offers none of its worn units' types")
    return line


def _own_army(a: Army, areas: tuple[str, ...], settlements=()) -> str:
    line = _army(a)
    if a.is_fleet:  # which of your ports it lies beside, for boarding and landing
        beside = [s.id for s in settlements if s.port_x is not None
                  and max(abs(s.port_x - a.x), abs(s.port_y - a.y)) <= 1]
        if beside:
            line += f", beside the port of {', '.join(beside)}"
    if "armies" in areas and a.moves_max:
        line += f", moves {a.moves_left}/{a.moves_max}"
    if "armies" in areas and a.troops:
        line += "\n  troops: " + "; ".join(
            f"{u.type} {u.soldiers}/{u.max_soldiers or u.soldiers} exp {u.exp}" for u in a.troops)
    return line


def state_summary(report: StateReport, areas: tuple[str, ...] = PRESETS["ruler"],
                  ruled: set[str] | None = None) -> list[str]:
    """The ruler's realm as text sections: treasury, settlements, armies, factions, enemies.
    Build and recruit options, taxes and troops show only for areas the ruler commands."""
    parts = [
        f"TURN {report.turn}, YEAR {report.year}. You rule {report.faction}.\n"
        f"Treasury: {report.treasury} florins at the end of your last turn "
        "(this turn's income arrives before your orders are carried out). "
        + (f"Income: {report.income} per turn after upkeep and wages." if report.income else
           "Income: not reported (compare treasury between turns).")
    ]
    if report.income_parts:  # what makes up that income, largest first (costs negative)
        parts[0] += "\nIncome items: " + ", ".join(
            f"{k} {v:+d}" for k, v in sorted(report.income_parts.items(), key=lambda kv: -abs(kv[1]))) + "."
    if report.spent_last_turn or report.received_last_turn:
        parts[0] += (f" Last turn you also spent {report.spent_last_turn} on buildings, recruits and "
                     "diplomacy (bribes, gifts)"
                     + (f" and received {report.received_last_turn} in gifts" if report.received_last_turn else "")
                     + ".")
    parts.append("YOUR SETTLEMENTS\n" + "\n".join(
        _settlement(s, areas, next((a.troops for a in report.armies if a.id == f"garrison:{s.id}"), None))
        for s in report.settlements
    ) if report.settlements else "YOUR SETTLEMENTS\n- none")
    parts.append("YOUR ARMIES (a strength rating is the game's estimate of fighting power, not a head "
                 "count: a general's bodyguard of a few dozen men rates in the thousands. Count men, "
                 "and walls need siege equipment, before you storm a city)\n" + ("\n".join(_own_army(a, areas, report.settlements)
                                              for a in report.armies) or "- none"))
    if report.agent_results:
        parts.append("YOUR AGENTS' MISSIONS SINCE YOUR LAST TURN (from the game itself)\n"
                     + "\n".join(f"- {a}" for a in report.agent_results))
    if report.popups:
        parts.append("GAME POPUPS SINCE YOUR LAST TURN (answered for you; the game shows no text "
                     "here, only what kind they were)\n" + "\n".join(f"- {p}" for p in report.popups))
    if report.agents:
        parts.append("YOUR AGENTS\n" + "\n".join(
            f"- {a.id}: {a.kind}, " + (f"in {a.in_settlement}" if a.in_settlement else f"at ({a.x},{a.y})")
            for a in report.agents))
    family = [p for p in report.family if p.family or p.role or p.kind == "princess"]
    if family:
        parts.append("YOUR FAMILY (from the game's records; the dead stay listed)\n"
                     + "\n".join(_person(p, report) for p in family))
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
    parts.append("OTHER FACTIONS (stance with you; what the faction screen shows). A faction with a "
                 "ruler answers messages, and its game AI's wars are undone. A faction run by the game's "
                 "AI alone makes real wars, and setting peace with it does not stop its armies: judge it "
                 "by what its armies do\n" + ("\n".join(
        _faction(f, ruled) for f in report.factions) or "- none"))
    parts.append(SIGHT_NOTE)
    parts.append("FOREIGN ARMIES IN SIGHT\n" + ("\n".join(map(_foreign_army, report.visible_enemies)) or "- none"))
    parts.append("FOREIGN AGENTS IN SIGHT\n" + ("\n".join(
        f"- {a.id} ({a.faction}): {a.kind} at ({a.x},{a.y}){_away(a.distance)}"
        for a in report.seen_agents) or "- none"))
    if report.crossings:
        parts.append("LAND CROSSINGS NEAR YOU (an army walks across the water here, no ships needed: "
                     "march or move_army onto the far side)\n" + "\n".join(
                         f"- at ({c.x},{c.y}), joining {' and '.join(c.regions) or 'two shores'}{_away(c.distance)}"
                         for c in report.crossings))
    if report.resources:
        parts.append("TRADE RESOURCES IN SIGHT (a merchant standing on one trades there every turn)\n"
                     + "\n".join(f"- {r.kind} at ({r.x},{r.y}), region {r.region}"
                                 + (f", value {r.value}" if r.value is not None else "")
                                 + (f", held by {r.owner}" if r.owner else "") + _away(r.distance)
                                 for r in report.resources))
    parts.append("SETTLEMENTS NEAR YOU\n" + ("\n".join(
        f"- {s.id} ({s.faction}): garrison {s.garrison_strength}, at ({s.x},{s.y}){_away(s.distance)}"
        for s in report.nearby_settlements) or "- none"))
    if report.remembered:
        parts.append("SETTLEMENTS SEEN BEFORE (out of sight now, as last seen; the rest of the map is "
                     "unexplored: send a general, agent or ship to look)\n" + "\n".join(
            f"- {s.id} ({s.faction}): garrison {s.garrison_strength}, at ({s.x},{s.y}), seen turn {s.seen_turn}"
            for s in report.remembered))
    return parts


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
        line += f", married to {p.spouse}" + (f" ({p.spouse_faction})" if p.spouse_faction else "")
    elif p.kind == "princess":
        line += ", unmarried: her hand can be offered to a foreign general in sight (\"marry\")"
    if p.parent:
        line += f", child of {p.parent}"
    if p.off_map:
        line += ", off the map"
    else:
        line += _whereabouts(p, report)
    return line


SIGHT_NOTE = ("You see only what your armies, agents and settlements can see; anything farther away "
              "is unknown to you. Use only names, settlements and positions listed here.")


def _away(distance: int | None) -> str:
    return f", {distance} tiles away" if distance is not None else ""


# The game keeps each part of public order as a count of 5% steps, every one positive; these
# take away. Live, London: 100 + 5 x (bonuses 21 - penalties 25) = 80%, as its panel shows.
ORDER_PENALTIES = {"high tax", "squalor", "unrest", "cultural unrest", "distance to capital",
                   "excommunication", "no governor", "besieged", "blockaded"}


def _order_parts(parts: dict[str, int]) -> str:
    pct = {k: (-5 if k in ORDER_PENALTIES else 5) * abs(v) for k, v in parts.items()}
    return ", ".join(f"{k} {v:+d}%" for k, v in sorted(pct.items(), key=lambda kv: -abs(kv[1])))


def _faction(f, ruled: set[str] | None = None) -> str:
    line = f"- {f.id} ({f.name}): {f.stance}"
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


def _foreign_army(a: Army) -> str:
    # the id is what orders must name; the leader only when it says something more
    who = f"{a.id} ({a.faction})" if a.faction else a.id
    if a.leader and a.leader != a.id:
        who += f", led by {a.leader}"
    where = f"in {a.in_settlement}" if a.in_settlement else f"at ({a.x},{a.y})"
    if a.from_x is not None:  # seen last turn elsewhere: the way it is heading
        where += f" (last turn at ({a.from_x},{a.from_y}))"
    return f"- {who}: {a.units} units, strength rating {a.strength}, {where}{_away(a.distance)}"


def build_prompt(report: StateReport, persona: str, scenario: str = "",
                 diplomacy: list | None = None, names: dict[str, str] | None = None,
                 notes: list[tuple[int, str]] | None = None, events: list[str] | None = None,
                 areas: tuple[str, ...] = PRESETS["ruler"], adviser: str = "",
                 game_messages: list[str] | None = None) -> str:
    parts = [persona.strip()]
    if scenario:
        parts.append(f"SCENARIO\n{scenario.strip()}")
    parts.append(role(areas, report.human_slot))
    if adviser:
        parts.append(adviser_section(adviser))
        names = {**(names or {}), f"adviser:{report.faction}": adviser}
    ruled = {k for k in names if not k.startswith("adviser:")} if names else None  # seats and humans
    parts += state_summary(report, areas, ruled)
    if report.last_results:
        parts.append("LAST TURN'S ORDER RESULTS\n" + "\n".join(
            f"- order {r.index} ({r.type}): {'done' if r.ok else 'REJECTED: ' + r.reason}"
            + (f". Now: {r.now}" if r.now else "")
            for r in report.last_results))
    if events:
        parts.append("SINCE YOUR LAST TURN\n" + "\n".join(f"- {e}" for e in events))
    if game_messages:
        parts.append("GAME MESSAGES SINCE YOUR LAST TURN (read from the screen: missions, news, offers)\n"
                     + "\n\n".join(m.strip() for m in game_messages))
    if notes:
        parts.append("YOUR RECENT NOTES (your own private plans, oldest first)\n" + "\n".join(
            f"[turn {t}] {n}" for t, n in notes))
    if diplomacy:
        names = names or {}
        parts.append(DIPLOMACY_HEADER + "\n" + "\n".join(
            _diplomacy_line(m, report.faction, names) for m in diplomacy))
    parts.append(RULES + "\n" + "\n".join(ORDER_HELP[a] for a in areas if a in ORDER_HELP))
    return "\n\n".join(parts) + "\n"
