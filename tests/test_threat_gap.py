"""THREATS states the gap in men and what answers it, from real run7 turns 57 and 59 (england).

Live: England saw 'garrison 1 units, 75 men; enemy 252 men 1 tile away', recruited one unit a turn
with 4,000-11,000 florins in the treasury, and lost Caen and Nottingham."""

import json
from pathlib import Path

from parley.protocol import Army, FactionView, Settlement, StateReport
from parley.threats import MAX_THREATS, threat_lines


def _real(turn):
    path = Path(__file__).parent / "fixtures" / f"state_turn{turn}_england.json"
    return StateReport.model_validate(json.loads(path.read_text()))


def _town(i, x, y, men=200, units=5):
    return Settlement(id=i, name=i, region=i, garrison_strength=1000, garrison_men=men, garrison_units=units,
                      population=1000, buildings=[], x=x, y=y, public_order=100, tax_level="normal")


def _foe(i, x, y, men=300):
    return Army(id=i, x=x, y=y, strength=3000, men=men, units=6, faction="scotland")


def _calm(report, **update):
    base = dict(settlements=[_town("London", 10, 10)], visible_enemies=[], armies=[], treasury=1000,
                income=600, factions=[FactionView(id="scotland", name="Scotland", stance="war")])
    return report.model_copy(update={**base, **update})


def _line(lines, start):
    return next(x for x in lines if x.startswith(f"- {start}"))


def test_t57_states_the_gap_and_what_closes_it():
    lines = threat_lines(_real(57))
    nott = _line(lines, "Nottingham")
    assert "252 enemy men vs your 75: short by 177" in nott
    assert "4 x Dismounted Feudal Knights (192 men, 2,280 florins)" in nott   # the steward's ranking, no upkeep cap
    assert "3 x Peasants (180 men, 330 florins)" in nott                      # the cheapest men per florin
    assert "against the 4,023 florins you hold" in nott
    assert "queues up to 9" in nott and "pool" in nott
    assert "first batch is ready next turn, the rest a turn later per batch" in nott   # not all arrive at once
    assert "enemy is at the gate" in nott and "merge an army in" in nott
    caen = _line(lines, "Caen")
    assert "969 enemy men vs your 227: short by 742" in caen
    # 13 units would close it, but the game's queue holds 9: say so rather than promise
    assert "9 x Peasants (540 men, 990 florins, the queue limit)" in caen and "toward it" in caen


def test_t59_gap_and_hoarding_fact():
    lines = threat_lines(_real(59))
    nott = _line(lines, "Nottingham")
    assert "432 enemy men vs your 72: short by 360" in nott
    assert "8 x Dismounted Feudal Knights (384 men, 4,560 florins)" in nott
    assert "6 x Peasants (360 men, 660 florins)" in nott
    assert "against the 8,212 florins you hold" in nott
    (hoard,) = [x for x in lines if "of income" in x]
    assert "Treasury 8,212 = 2.3 turns of income" in hoard and "unspent" in hoard and "Nottingham" in hoard


def test_no_hoarding_fact_under_two_turns_of_income_or_without_a_threat():
    assert not [x for x in threat_lines(_real(57)) if "of income" in x]     # 4,023 < 2 x 3,830
    assert threat_lines(_calm(_real(57), treasury=90000, income=100)) == []


def test_a_field_army_near_is_offered_as_a_joiner():
    report = _calm(_real(57), settlements=[_town("London", 10, 10, men=50, units=1)],
                   visible_enemies=[_foe("Brian", 11, 10)],
                   armies=[Army(id="Henry", x=13, y=10, strength=900, men=600, units=8)])
    (line,) = threat_lines(report)
    assert "Henry, 3 tiles away, 600 men" in line


def test_adjacent_enemy_names_mercenaries_the_armies_can_hire():
    from parley.protocol import MercOption
    hire = [MercOption(unit="Mercenary Spearmen", cost=400, available=3)]
    report = _calm(_real(57), settlements=[_town("London", 10, 10, men=50, units=1)],
                   visible_enemies=[_foe("Brian", 11, 10)],
                   armies=[Army(id="Henry", x=13, y=10, strength=900, men=600, units=8, can_hire=hire)])
    (line,) = threat_lines(report)
    assert "mercenaries join next turn (Henry can hire 3 x Mercenary Spearmen (400 florins each))" in line


def test_distant_enemy_gets_no_at_the_gate_advice():
    report = _calm(_real(57), settlements=[_town("London", 10, 10, men=50, units=1)],
                   visible_enemies=[_foe("Brian", 14, 10)])
    (line,) = threat_lines(report)
    assert "at the gate" not in line


def test_not_short_says_so():
    report = _calm(_real(57), visible_enemies=[_foe("Brian", 11, 10, men=100)])
    (line,) = threat_lines(report)
    assert "100 enemy men vs your 200" in line and "short by" not in line


def test_hoarding_fact_survives_the_line_cap():
    towns = [_town(f"T{i}", 10 + i * 20, 10, men=10, units=1) for i in range(6)]
    foes = [_foe(f"F{i}", 11 + i * 20, 10) for i in range(6)]
    lines = threat_lines(_calm(_real(57), settlements=towns, visible_enemies=foes, treasury=9000, income=1000))
    assert len(lines) == MAX_THREATS and any("turns of income" in x for x in lines)
