"""A seat that plays a fixed plan: {"<turn>": [order, ...]}. For live checks of the game side.

Generals' names are random per campaign, so an army of "$general" means the first army
in the field with a general, read from the prompt's YOUR ARMIES section.
"""

import json
import re
from pathlib import Path

from parley.protocol import Orders
from parley.seats.base import to_orders

_FIELD_ARMY = re.compile(r"^- (.+?): \d+ units, strength \d+, at \(-?\d+,-?\d+\), led by ", re.M)


def _first_general(prompt: str) -> str | None:
    section = prompt.split("YOUR ARMIES", 1)[-1].split("\n\n", 1)[0]
    m = _FIELD_ARMY.search(section)
    return m.group(1) if m else None


class ScriptSeat:
    def __init__(self, path: str):
        self.plan = json.loads(Path(path).read_text())
        self.name = f"script:{path}"

    def chat(self, prompt: str, *, timeout: float) -> str:
        return ""  # scripted seats don't talk

    def decide(self, prompt: str, *, game_id: str, turn: int, faction: str,
               timeout: float) -> tuple[Orders, str]:
        general = _first_general(prompt)
        orders = [{k: (general if v == "$general" else v) for k, v in o.items()}
                  for o in self.plan.get(str(turn), [])]
        payload = {"orders": orders, "note": f"scripted turn {turn}; $general = {general}"}
        return to_orders(payload, game_id=game_id, turn=turn, faction=faction), json.dumps(payload)
