"""A seat that plays a fixed plan: {"<turn>": [order, ...]}. For live checks of the game side.

Names are random per campaign, so a plan names things by placeholder, read from the
prompt: "$general" (first army in the field with a general), "$assassin", "$spy",
"$diplomat"... (first own agent of that kind), "$foreign_character" and
"$foreign_settlement" (nearest in sight), "$last_settlement" (own, last listed),
"$nearest_character_to:<agent id>" (the character in sight nearest that agent of yours).
"""

import json
import re
from pathlib import Path

from parley.protocol import Orders
from parley.seats.base import to_orders

_FIELD_ARMY = re.compile(r"^- (.+?): \d+ units(?:, \d+ men)?,? \(?strength(?: rating)? \d+(?:, not men\))?, "
                         r"at \(-?\d+,-?\d+\), led by ",
                         re.M)


def _first_general(prompt: str) -> str | None:
    section = prompt.split("YOUR ARMIES", 1)[-1].split("\n\n", 1)[0]
    m = _FIELD_ARMY.search(section)
    return m.group(1) if m else None


def _section(prompt: str, header: str) -> str:
    parts = prompt.split(header + "\n", 1)
    return parts[1].split("\n\n", 1)[0] if len(parts) == 2 else ""


def _ids(prompt: str, header: str) -> list[str]:
    """Ids from a prompt list section: the text between "- " and the first " (" or ":"."""
    return re.findall(r"^- (.+?)(?: \(|:)", _section(prompt, header), re.M)


_AT = re.compile(r"\bat \((-?\d+),(-?\d+)\)")
_FOREIGN_ARMY = re.compile(r"^- (.+?)(?: \(\w+\))?(?:, led by [^:]+)?: (.*)$")
_FOREIGN_AGENTS = re.compile(r"^- \w+ (\w+) at \((-?\d+),(-?\d+)\)[^:]*: (.+)$")

# A plan value "$nearest_character_to:<agent id>" is filled when the order is written, from this
# turn's sight lists: the character nearest that agent of yours. Nothing else knows it in advance.
NEAREST_CHARACTER_TO = "nearest_character_to"


def _sight_characters(prompt: str) -> list[tuple[str, int | None, int | None, bool]]:
    """(id, x, y, can be acted on over land) for every character in this turn's sight lists, in prompt
    order: foreign armies (a fleet can't), then foreign agents (an admiral sails with his fleet). These
    ids are what the validator accepts as a character target."""
    out: list[tuple[str, int | None, int | None, bool]] = []
    for line in _section(prompt, "FOREIGN ARMIES IN SIGHT").splitlines():
        m = _FOREIGN_ARMY.match(line)
        if not m or line == "- none":
            continue
        at = _AT.search(m.group(2))
        out.append((m.group(1), int(at.group(1)) if at else None, int(at.group(2)) if at else None,
                    not m.group(2).startswith("a fleet of")))
    for line in _section(prompt, "FOREIGN AGENTS IN SIGHT").splitlines():
        # "- france diplomat at (103,136), 2 tiles away: Denisot, Jehan": the ids come last
        m = _FOREIGN_AGENTS.match(line)
        if m:
            for aid in m.group(4).split(", "):
                out.append((aid, int(m.group(2)), int(m.group(3)), m.group(1) != "admiral"))
    return out


def _own_agent_tiles(prompt: str) -> dict[str, tuple[int, int]]:
    tiles = {}
    for line in _section(prompt, "YOUR AGENTS").splitlines():
        m = re.match(r"^- (.+?): \w+, at \((-?\d+),(-?\d+)\)$", line)
        if m:
            tiles[m.group(1)] = (int(m.group(2)), int(m.group(3)))
    return tiles


def nearest_character_to(prompt: str, agent: str) -> str | None:
    """The character in sight nearest your agent (tiles, diagonal steps count one), first listed on a
    tie; not a fleet or admiral, nor one on the agent's own tile (an agent acts from the next tile)."""
    at = _own_agent_tiles(prompt).get(agent)
    if at is None:
        return None
    best = None
    for i, (cid, x, y, by_land) in enumerate(_sight_characters(prompt)):
        if not by_land or x is None or y is None:
            continue
        d = max(abs(x - at[0]), abs(y - at[1]))
        if d and (best is None or (d, i) < best[0]):
            best = ((d, i), cid)
    return best[1] if best else None


def placeholders(prompt: str) -> dict[str, str]:
    """$names a plan can use, filled from this turn's prompt (sight lists are nearest first)."""
    found = {"$general": _first_general(prompt)}
    for line in _section(prompt, "YOUR AGENTS").splitlines():
        m = re.match(r"^- (.+?): (\w+), ", line)
        if m:
            found.setdefault(f"${m.group(2)}", m.group(1))
    near = [c[0] for c in _sight_characters(prompt)]
    found["$foreign_character"] = near[0] if near else None
    towns = _ids(prompt, "SETTLEMENTS NEAR YOU")
    found["$foreign_settlement"] = towns[0] if towns else None
    mine = _ids(prompt, "YOUR SETTLEMENTS")
    found["$last_settlement"] = mine[-1] if mine else None
    return {k: v for k, v in found.items() if v}


# the game's choice questions (parley/popups.py choice_prompt): a plan's "choice" answers them
_CHOICE_ASKED = "The game asks you to decide"


class ScriptSeat:
    """A plan entry {"type": "say", "to": ..., "text": ...} is a message, not an order. A plan's
    "choice" (e.g. "accept") is the answer to every choice the game asks the ruler (an AI's offer);
    without one the seat says nothing, and the bridge presses its default."""

    def __init__(self, path: str):
        self.plan = json.loads(Path(path).read_text())
        self.name = f"script:{path}"

    def chat(self, prompt: str, *, timeout: float) -> str:
        choice = self.plan.get("choice")
        if isinstance(choice, str) and choice and _CHOICE_ASKED in prompt:
            return f"{choice.upper()} (scripted QA ruler)"
        return ""  # scripted seats don't talk

    def decide(self, prompt: str, *, game_id: str, turn: int, faction: str,
               timeout: float) -> tuple[Orders, str]:
        # a $name with nothing to fill it stays as written, so the order is rejected with a reason
        found = placeholders(prompt)

        def fill(v):
            if not isinstance(v, str):
                return v
            if v.startswith(f"${NEAREST_CHARACTER_TO}:"):
                return nearest_character_to(prompt, v.split(":", 1)[1]) or v
            return found.get(v, v)

        planned = [{k: fill(v) for k, v in o.items()} for o in self.plan.get(str(turn), [])]
        orders = [o for o in planned if o.get("type") != "say"]
        messages = [{k: v for k, v in o.items() if k != "type"} for o in planned if o.get("type") == "say"]
        payload = {"orders": orders, "messages": messages, "note": f"scripted turn {turn}; placeholders {found}"}
        return to_orders(payload, game_id=game_id, turn=turn, faction=faction), json.dumps(payload)
