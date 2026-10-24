"""Turn a state report into the text an LLM seat reads."""

from parley.protocol import Army, StateReport

ROLE = (
    "You are the ruler. Your generals handle routine moves: recruiting, building and "
    "ordinary army movement. Give only diplomatic orders and specific override orders "
    "that matter this turn."
)

RULES = """OUTPUT RULES
- Answer with JSON matching the given schema, and nothing else.
- Use IDs exactly as written before the parentheses, e.g. "hre", never "Holy Roman Empire".
- Never claim gold, armies or settlements you don't have. Bluff in conversation if you like, never in orders.
- An empty "orders" list is allowed when nothing needs doing.
- To speak, add "messages": {"to": "lobby"} is public to everyone; {"to": "<faction id>"} is private to that faction. At most 3 per recipient per turn, 600 characters each.
- Speak only when you have something new to say; don't repeat what you already said in earlier turns.
- Put your private reasoning in "note"; no other faction sees it. Never put private reasoning in a message. Your notes come back to you next turn, so record plans, grudges and promises there.
- An order result of "done" means the order was carried out, not that it succeeded; check your next report for what actually happened."""

DIPLOMACY_HEADER = (
    "DIPLOMACY (most recent last)\n"
    "Public messages are seen by everyone; private ones only by the two sides. "
    "Promises bind nothing in the game: a deal is kept only if someone acts on it.")


def one_line(text: str) -> str:
    """Quoted message text on a single line, so nobody can forge a new history line."""
    return " ".join(text.split())


def _sender(sender: str, names: dict[str, str]) -> str:
    faction = sender.removeprefix("human:")
    return f"{names.get(faction, faction)} ({faction})"


def _diplomacy_line(m, me: str, names: dict[str, str]) -> str:
    if m.channel == "lobby":
        where = "public"
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
    return f"- {a.id}: {a.units} units, strength {a.strength}, {where}{leader}"


def state_summary(report: StateReport) -> list[str]:
    """The ruler's realm as text sections: treasury, settlements, armies, factions, enemies."""
    parts = [
        f"TURN {report.turn}, YEAR {report.year}. You rule {report.faction}.\n"
        f"Treasury: {report.treasury} florins. "
        + (f"Income: {report.income} per turn." if report.income else
           "Income: not reported (compare treasury between turns).")
    ]
    parts.append("YOUR SETTLEMENTS\n" + "\n".join(
        f"- {s.id} ({s.name}), region {s.region}: garrison {s.garrison_strength}, "
        f"population {s.population}, buildings: {', '.join(s.buildings) or 'none'}"
        for s in report.settlements
    ) if report.settlements else "YOUR SETTLEMENTS\n- none")
    parts.append("YOUR ARMIES\n" + ("\n".join(map(_army, report.armies)) or "- none"))
    parts.append("OTHER FACTIONS\n" + ("\n".join(
        f"- {f.id} ({f.name}): {f.stance}" for f in report.factions) or "- none"))
    parts.append("VISIBLE ENEMY ARMIES\n" + ("\n".join(map(_army, report.visible_enemies)) or "- none"))
    return parts


def build_prompt(report: StateReport, persona: str, scenario: str = "",
                 diplomacy: list | None = None, names: dict[str, str] | None = None,
                 notes: list[tuple[int, str]] | None = None, events: list[str] | None = None) -> str:
    parts = [persona.strip()]
    if scenario:
        parts.append(f"SCENARIO\n{scenario.strip()}")
    parts.append(ROLE)
    parts += state_summary(report)
    if report.last_results:
        parts.append("LAST TURN'S ORDER RESULTS\n" + "\n".join(
            f"- order {r.index} ({r.type}): {'done' if r.ok else 'REJECTED: ' + r.reason}"
            for r in report.last_results))
    if events:
        parts.append("SINCE YOUR LAST TURN\n" + "\n".join(f"- {e}" for e in events))
    if notes:
        parts.append("YOUR RECENT NOTES (your own private plans, oldest first)\n" + "\n".join(
            f"[turn {t}] {n}" for t, n in notes))
    if diplomacy:
        names = names or {}
        parts.append(DIPLOMACY_HEADER + "\n" + "\n".join(
            _diplomacy_line(m, report.faction, names) for m in diplomacy))
    parts.append(RULES)
    return "\n\n".join(parts) + "\n"
