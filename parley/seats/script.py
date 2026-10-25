"""A seat that plays a fixed plan: {"<turn>": [order, ...]}. For live checks of the game side.

Names are random per campaign, so a plan names things by placeholder, read from the
prompt: "$general" (first army in the field with a general), "$assassin", "$spy",
"$diplomat"... (first own agent of that kind), "$foreign_character" and
"$foreign_settlement" (nearest in sight), "$last_settlement" (own, last listed).
"""

import json
import re
from pathlib import Path

from parley.protocol import Orders
from parley.seats.base import to_orders

_FIELD_ARMY = re.compile(r"^- (.+?): \d+ units(?:, \d+ men)?, strength(?: rating)? \d+, at \(-?\d+,-?\d+\), led by ",
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


def placeholders(prompt: str) -> dict[str, str]:
    """$names a plan can use, filled from this turn's prompt (sight lists are nearest first)."""
    found = {"$general": _first_general(prompt)}
    for line in _section(prompt, "YOUR AGENTS").splitlines():
        m = re.match(r"^- (.+?): (\w+), ", line)
        if m:
            found.setdefault(f"${m.group(2)}", m.group(1))
    near = _ids(prompt, "FOREIGN ARMIES IN SIGHT") + _ids(prompt, "FOREIGN AGENTS IN SIGHT")
    found["$foreign_character"] = near[0] if near else None
    towns = _ids(prompt, "SETTLEMENTS NEAR YOU")
    found["$foreign_settlement"] = towns[0] if towns else None
    mine = _ids(prompt, "YOUR SETTLEMENTS")
    found["$last_settlement"] = mine[-1] if mine else None
    return {k: v for k, v in found.items() if v}


class ScriptSeat:
    def __init__(self, path: str):
        self.plan = json.loads(Path(path).read_text())
        self.name = f"script:{path}"

    def chat(self, prompt: str, *, timeout: float) -> str:
        return ""  # scripted seats don't talk

    def decide(self, prompt: str, *, game_id: str, turn: int, faction: str,
               timeout: float) -> tuple[Orders, str]:
        # a $name with nothing to fill it stays as written, so the order is rejected with a reason
        found = placeholders(prompt)
        orders = [{k: found.get(v, v) if isinstance(v, str) else v for k, v in o.items()}
                  for o in self.plan.get(str(turn), [])]
        payload = {"orders": orders, "note": f"scripted turn {turn}; placeholders {found}"}
        return to_orders(payload, game_id=game_id, turn=turn, faction=faction), json.dumps(payload)
