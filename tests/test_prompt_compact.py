"""The prompt drops long-dead relatives and prints each unit price once (France hit 328 KB at turn 3454)."""

import json
import re
from pathlib import Path

from parley.control import AREAS
from parley.prompt import build_prompt
from parley.protocol import Person, RecruitOption, StateReport


def test_family_shrinks_old_dead_relatives(venice_report):
    # 50 old dead, 1 recent dead, 1 dead parent of a living son: the recent one and the parent are
    # listed, the rest counted
    current_turn = venice_report.turn + 50
    living_son = Person(name="Prince John", alive=True, family=True, parent="Old King Philip", role="heir")
    dead_parent = Person(name="Old King Philip", alive=False, family=True, age=65, death_turn=current_turn - 45)
    recent_dead = Person(name="Duke Geoffrey", alive=False, family=True, age=40, death_turn=current_turn - 5)
    old_dead = [
        Person(name=f"Ancestor {i}", alive=False, family=True, age=50 + (i % 20), death_turn=current_turn - 35 - i)
        for i in range(50)
    ]

    family = [living_son, dead_parent, recent_dead] + old_dead
    report = venice_report.model_copy(update={"turn": current_turn, "family": family})
    prompt = build_prompt(report, persona="p")

    assert "YOUR FAMILY (from the game's records; only recent dead are listed;" in prompt
    assert "- Prince John" in prompt
    # live 11-23: France listed 77 dead relatives one per line (2.6 KB); they share one line now
    assert "- dead: Old King Philip (at 65); Duke Geoffrey (at 40)\n" in prompt
    assert "- and 50 more dead relatives (not listed)" in prompt
    for i in range(50):
        assert f"Ancestor {i}" not in prompt


def test_a_spouse_of_your_own_faction_carries_no_faction_tag(venice_report):
    # live 11-23: 82 of France's spouses read "(france)"; only a foreign spouse is named so
    own = Person(name="Dorian", alive=True, family=True, age=44, kind="general",
                 spouse="Alixa", spouse_faction=venice_report.faction)
    foreign = Person(name="Enrico", alive=True, family=True, age=30, kind="general",
                     spouse="Maud", spouse_faction="england")
    p = build_prompt(venice_report.model_copy(update={"family": [own, foreign]}), persona="p")
    assert "married to Alixa," in p or p.count("married to Alixa\n") == 1
    assert f"married to Alixa ({venice_report.faction})" not in p
    assert "married to Maud (england)" in p
    assert "spouses are of your faction unless one is named" in p


def test_settlements_recruit_unit_prices_table_deduplication(venice_report):
    # two towns recruiting one unit at one price print the price once; a town with another price
    # shows its full entry
    s0 = venice_report.settlements[0]
    town_a = s0.model_copy(update={
        "id": "Venice", "name": "Venice",
        "can_recruit": [RecruitOption(unit="Spear Militia", cost=310, turns=1, upkeep=125)]
    })
    town_b = s0.model_copy(update={
        "id": "Ragusa", "name": "Ragusa",
        "can_recruit": [RecruitOption(unit="Spear Militia", cost=310, turns=1, upkeep=125)]
    })
    town_c = s0.model_copy(update={
        "id": "Milan", "name": "Milan",
        "buildings": ["castle"],
        "can_recruit": [RecruitOption(unit="Spear Militia", cost=400, turns=2, upkeep=150)]
    })

    report = venice_report.model_copy(update={"settlements": [town_a, town_b, town_c]})
    prompt = build_prompt(report, persona="p", areas=AREAS)

    assert "UNIT PRICES (florins/turns, upkeep a turn)" in prompt
    assert "- Spear Militia 310/1, upkeep 125" in prompt
    assert prompt.count("310/1, upkeep 125") == 1
    assert "- Venice" in prompt
    assert "- Ragusa" in prompt
    assert "- Milan" in prompt
    assert "Spear Militia 400/2, upkeep 150" in prompt


# a town's own line: its id, then its game name and region only when they differ, then a colon
TOWN_LINE = r"^- (\S+?)(?: \([^)]*\))?(?:, region \S+)?: "


def _resolve_same_as(content: str, full_lists: dict[str, list[str]], sep: str) -> list[str]:
    """A list as printed: in full, or "same as X, plus [..], without [..]" against X's full list."""
    m = re.match(r"^same as (\S+?)(?:, plus \[(.*?)\])?(?:, without \[(.*?)\])?$", content)
    if not m:
        return [e.strip() for e in content.split(sep) if e.strip()]
    without = set(m.group(3).split(sep)) if m.group(3) else set()
    base = [e for e in full_lists[m.group(1)] if e not in without]
    return base + (m.group(2).split(sep) if m.group(2) else [])


def test_lossless_settlements_reconstruction(venice_report):
    # every (town, unit, cost, turns, upkeep) can be read back from the compact text
    s0 = venice_report.settlements[0]
    expected_tuples = []

    town_configs = [
        ("Town1", [("Spear Militia", 310, 1, 125), ("Peasants", 110, 1, 90), ("Ballista", 370, 1, 150)]),
        ("Town2", [("Spear Militia", 310, 1, 125), ("Feudal Knights", 730, 1, 250)]),
        ("Town3", [("Peasants", 110, 1, 90), ("Crossbowmen", 330, 1, 125)]),
        ("Town4", [("Spear Militia", 400, 2, 160), ("Crossbowmen", 330, 1, 125)]),
        ("Town5", [("Feudal Knights", 730, 1, 250), ("Ballista", 370, 1, 150)]),
    ]

    settlements = []
    for town_id, units in town_configs:
        recruits = []
        for uname, cost, turns, upkeep in units:
            recruits.append(RecruitOption(unit=uname, cost=cost, turns=turns, upkeep=upkeep))
            expected_tuples.append((town_id, uname, cost, turns, upkeep))
        settlements.append(s0.model_copy(update={
            "id": town_id, "name": town_id,
            "can_recruit": recruits,
            "buildings": ["huge_stone_wall"],
        }))

    report = venice_report.model_copy(update={"settlements": settlements})
    prompt = build_prompt(report, persona="p", areas=AREAS)

    start = prompt.index("YOUR SETTLEMENTS\n") + len("YOUR SETTLEMENTS\n")
    end = prompt.find("\nYOUR ARMIES", start)
    section = prompt[start:end] if end != -1 else prompt[start:]

    table_prices = {}
    table_m = re.search(r"UNIT PRICES \(florins/turns, upkeep a turn\)[^\n]*\n((?:- .+\n?)+)", section)
    assert table_m is not None, "UNIT PRICES table missing"
    for line in table_m.group(1).splitlines():
        line = line.strip()
        if not line.startswith("- "):
            continue
        m = re.match(r"^- (.+?)\s+(\d+)/(\d+)(?:,\s+upkeep\s+(\d+))?(?:, free-slot)?$", line)
        if m:
            table_prices[m.group(1)] = (int(m.group(2)), int(m.group(3)), int(m.group(4)) if m.group(4) else None)

    recovered_tuples = []
    full_lists: dict[str, list[str]] = {}
    current_town = None
    for line in section.splitlines():
        m_town = re.match(TOWN_LINE, line)
        if m_town:
            current_town = m_town.group(1)
        elif current_town and line.strip().startswith("can recruit:"):
            content = line.strip()[len("can recruit:"):].strip()
            if content and content != "nothing" and not content.startswith("unknown"):
                entries = _resolve_same_as(content, full_lists, "; ")
                if not content.startswith("same as "):
                    full_lists[current_town] = entries
                for entry in entries:
                    entry = entry.strip()
                    if not entry:
                        continue
                    m_diff = re.match(r"^(.+?)\s+(\d+)/(\d+)(?:,\s+upkeep\s+(\d+))?(?:, free-slot)?$", entry)
                    if m_diff:
                        u = m_diff.group(1)
                        recovered_tuples.append((current_town, u, int(m_diff.group(2)), int(m_diff.group(3)),
                                                 int(m_diff.group(4)) if m_diff.group(4) else None))
                    else:
                        m_free = re.match(r"^(.+?),\s+free upkeep \(\d+ left\)$", entry)
                        u = m_free.group(1) if m_free else entry
                        c, t, upk = table_prices[u]
                        recovered_tuples.append((current_town, u, c, t, upk))

    assert sorted(recovered_tuples) == sorted(expected_tuples)


# --- same-as references (live 11-22: France's 64 towns, YOUR SETTLEMENTS 92 KB a turn) -------

FRANCE = Path(__file__).parent / "fixtures" / "prompt_size" / "france_turn3474_state.json"


def _france_section():
    report = StateReport.model_validate(json.loads(FRANCE.read_text()))
    p = build_prompt(report, persona="p", areas=AREAS)
    start = p.index("YOUR SETTLEMENTS\n")
    return report, p[start:p.index("\nYOUR ARMIES", start)]


def test_france_settlements_fit_their_budget():
    # 92 KB before the references; 60.6 KB after (the rest is 54 distinct recruit sets of 64 towns)
    _, section = _france_section()
    assert len(section.encode()) <= 62_000


def test_france_buildings_and_recruits_read_back_exactly():
    report, section = _france_section()
    builds: dict[str, list[str]] = {}
    recruits: dict[str, list[str]] = {}
    got_b, got_r, town = {}, {}, None
    for line in section.splitlines():
        if m := re.match(TOWN_LINE + r".*?, buildings: (.*?)(?:; free-upkeep slots|; tax |; rebel|$)", line):
            town, text = m.group(1), m.group(2)
            got_b[town] = set(_resolve_same_as(text, builds, ", "))
            if not text.startswith("same as "):
                builds[town] = text.split(", ")
        elif town and line.startswith("  can recruit: "):
            text = line[len("  can recruit: "):]
            if text == "nothing":
                got_r[town] = set()
                continue
            got_r[town] = set(_resolve_same_as(text, recruits, "; "))
            if not text.startswith("same as "):
                recruits[town] = text.split("; ")
    for s in report.settlements:
        assert got_b[s.id] == set(s.buildings), s.id
        names = {re.sub(r" \d+/\d+.*$", "", e) for e in got_r[s.id]}
        assert names == {u.unit for u in s.can_recruit}, s.id
    lines = section.splitlines()
    legend = lines.index(next(x for x in lines if x.startswith('(a list that reads "same as')))
    assert legend < min(i for i, x in enumerate(lines) if "same as " in x and not x.startswith("(a list"))


def test_a_reference_names_a_town_printed_in_full():
    _, section = _france_section()
    full, town = set(), None
    for line in section.splitlines():
        if m := re.match(TOWN_LINE, line):
            town = m.group(1)
        for kind in ("buildings: ", "can recruit: "):
            if kind in line:
                text = line.split(kind, 1)[1]
                if text.startswith("same as "):
                    assert (kind, text.split()[2].rstrip(",;")) in full, line
                else:
                    full.add((kind, town))


def test_free_slot_units_are_marked_once_in_the_price_table(venice_report):
    s = venice_report.settlements[0].model_copy(update={
        "buildings": ["stone_wall"], "recruit_queue": [],
        "can_recruit": [RecruitOption(unit="Italian Spear Militia", cost=350, turns=1)]})
    p = build_prompt(venice_report.model_copy(update={"settlements": [s]}), persona="p", areas=AREAS)
    assert "free-upkeep slots" in p and ", free-slot\n" in p and "free upkeep (" not in p


def test_a_town_line_names_its_game_name_and_region_only_when_they_differ(venice_report):
    # live 11-23: 57 of France's 59 towns printed "Arhus (Arhus), region Arhus_Province"
    from parley.seats.script import _ids
    s0 = venice_report.settlements[0]
    plain = s0.model_copy(update={"id": "Arhus", "name": "Arhus", "region": "Arhus_Province",
                                  "queue": [], "can_build": []})
    odd = s0.model_copy(update={"id": "Las Navas", "name": "Navas", "region": "Andalusia"})
    p = build_prompt(venice_report.model_copy(update={"settlements": [plain, odd]}), persona="p", areas=AREAS)
    assert "\n- Arhus: " in p and "Arhus_Province" not in p
    assert "\n- Las Navas (Navas), region Andalusia: " in p
    assert "region (<id>_Province)" in p and "no queue line: nothing being built" in p
    town_block = p.split("\n- Arhus: ", 1)[1].split("\n- ", 1)[0]
    assert "queue:" not in town_block and "can build" not in town_block
    assert _ids(p, "YOUR SETTLEMENTS")[-2:] == ["Arhus", "Las Navas"]


def test_town_legend_is_left_out_when_nothing_is_left_out(venice_report):
    s = venice_report.settlements[0].model_copy(update={"id": "Venice", "name": "La Serenissima",
                                                        "region": "Veneto"})
    p = build_prompt(venice_report.model_copy(update={"settlements": [s]}), persona="p", areas=("armies",))
    assert "print only when they differ" not in p and "no queue line" not in p


def test_a_garrison_drops_its_town_and_moves_stay_on_the_army_line(venice_report):
    # live 11-23: "moves 0/119" printed after the mercenary pool's text, on the hire line
    from parley.protocol import Army, MercOption
    g = Army(id="garrison:Caen", in_settlement="Caen", x=1, y=1, strength=900, units=3, men=180)
    f = Army(id="Paul", leader="Paul", x=100, y=130, strength=900, units=1, moves_left=5, moves_max=80,
             can_hire=[MercOption(unit="Pikemen", cost=500, available=1, max=2, exp=0, pool="Normandy")])
    p = build_prompt(venice_report.model_copy(update={"armies": [g, f]}), persona="p", areas=AREAS)
    caen = p.split("\n- garrison:Caen: ", 1)[1].split("\n", 1)[0]
    assert caen == "3 units, 180 men, str 900"
    paul, hire = p.split("\n- Paul: ", 1)[1].split("\n", 2)[:2]
    assert paul.endswith("moves 5/80") and hire.startswith("  mercenaries for hire here")
    assert "moves" not in hire
