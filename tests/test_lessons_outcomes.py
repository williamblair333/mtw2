"""Outcomes for the lessons review: what the turn reports say really happened in the stretch."""

from parley.lessons import OUTCOMES_MAX, outcomes_section, review_prompt
from parley.protocol import Siege, StateReport


def _state(turn, settlements, treasury=1000, income=100, armies=(), nearby=(), news=(), char=(), faction="england"):
    return StateReport.model_validate({
        "protocol": 1, "game_id": "g", "turn": turn, "year": 1400 + turn, "faction": faction,
        "treasury": treasury, "income": income,
        "armies": [{"id": f"a{i}", "x": 1, "y": 1, "strength": 1, "men": m, "units": 1} for i, m in enumerate(armies)],
        "settlements": [{"id": n, "name": n, "region": n, "garrison_strength": 1, "population": 1,
                         "buildings": [], "public_order": o, "tax_level": tax} for n, o, tax in settlements],
        "nearby_settlements": [{"id": n, "name": n, "faction": f, "x": 1, "y": 1} for n, f in nearby],
        "factions": [], "visible_enemies": [], "last_results": [], "news": list(news),
        "character_events": list(char)})


def _revolt_stretch():
    return [(170, _state(170, [("London", 95, "normal"), ("York", 130, "high")], 354, 87, [500, 612])),
            (184, _state(184, [("London", 45, "high"), ("York", 130, "high")], 2190, 145, [500, 612])),
            (186, _state(186, [("York", 120, "high")], -2219, -4263, [500, 500], nearby=[("London", "slave")],
                         news=["scotland broke its alliance with england"],
                         char=["Roger was struck by a disaster: famine (in London_Province)",
                               "Ann was struck by a disaster: famine (in London_Province)"]))]


def test_outcomes_name_a_lost_settlement_its_new_holder_and_its_order_and_tax():
    text = outcomes_section(_revolt_stretch())
    assert "Settlements: 2 at T170, 1 at T186. LOST London (now held by rebels)" in text
    assert "London: T170 95% order, tax normal -> T184 45% order, tax high; tax changed normal->high T184" in text
    assert "last held T184" in text
    assert "York: T170 130% order, tax high -> T186 120% order, tax high" in text


def test_outcomes_carry_money_armies_and_events():
    text = outcomes_section(_revolt_stretch())
    assert "Treasury 354 -> -2219; income/turn 87 -> -4263." in text
    assert "Armies: 2 with 1112 men at T170, 2 with 1000 men at T186." in text
    assert "scotland broke its alliance with england" in text
    assert text.count("famine") == 1 and "famine in London_Province" in text  # folded into one line


def test_outcomes_name_a_gain_and_a_siege_and_stay_small():
    a = _state(1, [("York", 80, "normal")])
    b = _state(9, [("York", 80, "normal"), ("Caen", 60, "low")],
               char=[f"event number {i} {'x' * 100}" for i in range(60)])
    b.settlements[0].siege = Siege(faction="denmark", men=100)
    text = outcomes_section([(9, b), (1, a)])  # any order
    assert "GAINED Caen" in text and "Besieged: York by denmark from T9" in text
    assert len(text.encode()) <= OUTCOMES_MAX
    assert outcomes_section([]) == ""


def test_the_review_prompt_demands_outcome_linked_lessons():
    out = outcomes_section(_revolt_stretch())
    p = review_prompt("King X", "england", [(170, "n", [])], out)
    assert out in p and "link a decision to an outcome" in p and "never contradict" in p
    assert "Prefer no lesson to a weak one" in p and "software around the game" in p
    assert "OUTCOMES" not in review_prompt("King X", "england", [(170, "n", [])])  # no reports: old shape
