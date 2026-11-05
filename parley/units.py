"""Unit facts from the game's own files (parley/data/units.json, built by scripts/unit_table.py) and
the free-upkeep rule: a city keeps some `free_upkeep_unit` units (militia) for nothing, as many as its
walls give; anything beyond that, and any such unit in a castle, pays full upkeep.
"""

import json
import re
from functools import lru_cache
from pathlib import Path

from parley.protocol import Settlement, Unit

_DATA = Path(__file__).parent / "data" / "units.json"

# `free_upkeep bonus N` in export_descr_buildings.txt, by city wall level
WALL_FREE_SLOTS = {"wooden_pallisade": 2, "wooden_palisade": 2, "wooden_wall": 3, "stone_wall": 4,
                   "large_stone_wall": 5, "huge_stone_wall": 6}
# the one castle building with a free_upkeep line (castles otherwise give none)
CASTLE_FREE_SLOTS = {"tourney_fields": 1}


@lru_cache(maxsize=1)
def table() -> dict[str, dict]:
    return json.loads(_DATA.read_text())["units"]


def info(name: str) -> dict | None:
    return table().get(name)


def is_free(name: str) -> bool:
    u = info(name)
    return bool(u and u["free_upkeep"])


def is_garrison_kind(name: str) -> bool:
    """False for ships and siege engines (unknown names count as land units)."""
    u = info(name)
    return not (u and u["role"] in ("ship", "siege"))


def defence_value(name: str, upkeep: int | None = None) -> float:
    """Defensive worth per florin of upkeep: men * (defence skill + armour + shield) / upkeep.

    Stats from the unit file (stat_pri_armour). `upkeep` overrides the file's figure (the report's).
    0 for a unit the table does not know.
    """
    u = info(name)
    if u is None:
        return 0.0
    up = u["upkeep"] if upkeep is None else upkeep
    return u["men"] * (u["defence"] + u["armour"] + u["shield"]) / max(up, 1)


def free_slots(buildings: list[str]) -> int:
    """Free-upkeep slots a settlement's buildings give: its wall level, plus tourney fields."""
    walls = max((WALL_FREE_SLOTS.get(b, 0) for b in buildings), default=0)
    return walls + sum(CASTLE_FREE_SLOTS.get(b, 0) for b in buildings)


def _queued_name(entry: str) -> str:
    return re.sub(r"\s*\(.*\)\s*$", "", entry)  # "Peasants (1 turn left)"


def free_slots_left(s: Settlement, garrison: list[Unit] | None = None) -> int:
    """Free slots not yet used: free units in the garrison, in training or queued fill them."""
    used = sum(1 for t in garrison or [] if is_free(t.type))
    used += sum(1 for t in s.training if is_free(t.unit))
    used += sum(1 for q in s.recruit_queue if is_free(_queued_name(q)))
    return max(0, free_slots(s.buildings) - used)
