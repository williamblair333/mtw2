"""Build parley/data/units.json from the vanilla unit file.

Source (read-only): <M2TW>/mods/bare_geomod/data/export_descr_unit.txt, the unpacked vanilla
export_descr_unit.txt (EDU). Keys are the EDU `type` names, which are exactly the names the game's
recruit lists (`can_recruit[].unit`) and garrison troops (`troops[].type`) use ("Town Militia",
"NE Ballista", "cog"); the `dictionary` name is not used.

Per unit:
  men         soldiers in the unit (EDU `soldier` line; the game scales by unit-size, ratios hold)
  cost        stat_cost field 2; upkeep: stat_cost field 3
  free_upkeep the `free_upkeep_unit` attribute (all militia): free while inside a city's free slots
  category    EDU category: infantry, cavalry, siege, ship
  role        infantry | cavalry | missile (stat_pri fires a missile) | siege | ship
  class       EDU class (light, spearmen, heavy, ...)
  attack      stat_pri attack; defence, armour, shield: stat_pri_armour as "armour, defence skill, shield"

Usage: uv run python scripts/unit_table.py [path/to/export_descr_unit.txt]
"""

import json
import sys
from pathlib import Path

DEFAULT_EDU = Path.home() / (".steam/steam/steamapps/common/Medieval II Total War/mods/bare_geomod/"
                             "data/export_descr_unit.txt")
OUT = Path(__file__).resolve().parent.parent / "parley" / "data" / "units.json"


def _fields(rest: str) -> list[str]:
    return [f.strip() for f in rest.split(",")]


def _int(s: str) -> int:
    return int(float(s))


def parse(text: str) -> dict[str, dict]:
    blocks: list[dict[str, str]] = []
    for raw in text.splitlines():
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        key, _, rest = line.partition(" ")
        rest = rest.strip()
        if key == "type":
            blocks.append({"type": rest})
        elif blocks and key not in blocks[-1]:  # first occurrence (era lines repeat)
            blocks[-1][key] = rest
    units = {}
    for b in blocks:
        try:
            cost = _fields(b["stat_cost"])
            pri = _fields(b["stat_pri"])
            arm = _fields(b["stat_pri_armour"])
            men = _int(_fields(b["soldier"])[1])
        except (KeyError, IndexError, ValueError):
            continue
        category = b.get("category", "")
        role = category if category in ("siege", "ship", "cavalry") else "infantry"
        if role in ("infantry", "cavalry") and pri[2] != "no":
            role = "missile"
        units[b["type"]] = {
            "men": men, "cost": _int(cost[1]), "upkeep": _int(cost[2]),
            "free_upkeep": "free_upkeep_unit" in b.get("attributes", ""),
            "category": category, "role": role, "class": b.get("class", ""),
            "attack": _int(pri[0]), "defence": _int(arm[1]), "armour": _int(arm[0]),
            "shield": _int(arm[2]),
        }
    return units


def main(argv: list[str]) -> int:
    src = Path(argv[1]) if len(argv) > 1 else DEFAULT_EDU
    units = parse(src.read_text(encoding="utf-8", errors="replace"))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"source": "vanilla export_descr_unit.txt", "units": units},
                              indent=0, sort_keys=True) + "\n")
    free = sum(u["free_upkeep"] for u in units.values())
    print(f"{len(units)} units ({free} free upkeep) -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
