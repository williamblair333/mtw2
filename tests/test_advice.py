import pytest

from parley.advice import TILES_PER_TURN, SiegeAdvice, siege_clock
from parley.protocol import Army, Settlement, Siege


def test_no_sieges_gives_empty_list(venice_report):
    assert siege_clock(venice_report) == []


def test_verdict_sally_when_odds_favorable(venice_report):
    # Garrison outnumbers attacker by >= 1.2, so sally out to break the siege.
    venice = venice_report.settlements[0].model_copy(update={
        "garrison_strength": 1200,
        "x": 100, "y": 100,
        "siege": Siege(by="Captain Anselm", faction="milan", strength=1000, holdout=2),
    })
    r = venice_report.model_copy(update={"settlements": [venice], "armies": []})
    advices = siege_clock(r)
    assert len(advices) == 1
    a = advices[0]
    assert a.verdict == "sally"
    assert a.odds == 1.2
    assert "sally" in a.line


def test_verdict_hold_when_relief_in_time(venice_report):
    # Relieving army arrives in 2 turns, settlement can hold out 4 turns.
    venice = venice_report.settlements[0].model_copy(update={
        "garrison_strength": 800,
        "x": 100, "y": 100,
        "siege": Siege(by="Captain Anselm", faction="milan", strength=1000, holdout=4),
    })
    reliever = Army(id="a2", leader="Prince Edward", x=115, y=100, strength=1100, units=8)
    r = venice_report.model_copy(update={"settlements": [venice], "armies": [reliever]})
    advices = siege_clock(r)
    assert len(advices) == 1
    a = advices[0]
    assert a.verdict == "hold"
    assert a.relief_eta == 2
    assert a.holdout == 4
    assert a.odds == 0.8
    assert "hold" in a.line


def test_verdict_relieve_or_lose_when_too_late_or_no_relief(venice_report):
    # Relief arrives in 4 turns, but settlement only holds 2 turns.
    venice = venice_report.settlements[0].model_copy(update={
        "garrison_strength": 800,
        "x": 100, "y": 100,
        "siege": Siege(by="Captain Anselm", faction="milan", strength=1000, holdout=2),
    })
    reliever = Army(id="a2", leader="Captain Thomas", x=135, y=100, strength=1100, units=8)
    r = venice_report.model_copy(update={"settlements": [venice], "armies": [reliever]})
    advices = siege_clock(r)
    assert len(advices) == 1
    a = advices[0]
    assert a.verdict == "relieve_or_lose"
    assert a.relief_eta == 4
    assert a.holdout == 2
    assert "no relief in time" in a.line

    # Also holds when there is no relief army at all.
    r_empty = venice_report.model_copy(update={"settlements": [venice], "armies": []})
    a_empty = siege_clock(r_empty)[0]
    assert a_empty.verdict == "relieve_or_lose"
    assert a_empty.relief_eta is None
    assert "no relief in time" in a_empty.line


def test_verdict_unknown_when_holdout_unknown(venice_report):
    venice = venice_report.settlements[0].model_copy(update={
        "garrison_strength": 800,
        "x": 100, "y": 100,
        "siege": Siege(by="Captain Anselm", faction="milan", strength=1000, holdout=None),
    })
    r = venice_report.model_copy(update={"settlements": [venice], "armies": []})
    advices = siege_clock(r)
    assert len(advices) == 1
    a = advices[0]
    assert a.verdict == "unknown"
    assert a.holdout is None
    assert "holdout unknown" in a.line


def test_fleet_and_aboard_never_counted_as_relief(venice_report):
    venice = venice_report.settlements[0].model_copy(update={
        "garrison_strength": 800,
        "x": 100, "y": 100,
        "siege": Siege(by="Captain Anselm", faction="milan", strength=1000, holdout=5),
    })
    fleet = Army(id="f1", leader="Admiral Nigel", x=105, y=100, strength=200, units=2, is_fleet=True)
    aboard = Army(id="a2", leader="Lord Luke", x=105, y=100, strength=600, units=4, aboard="f1")
    in_town = venice_report.armies[0]  # in_settlement = "venice"
    r = venice_report.model_copy(update={"settlements": [venice], "armies": [fleet, aboard, in_town]})
    advices = siege_clock(r)
    assert len(advices) == 1
    a = advices[0]
    assert a.relief == []
    assert a.relief_eta is None
    assert a.verdict == "relieve_or_lose"


def test_nearest_of_two_relief_armies_is_chosen(venice_report):
    venice = venice_report.settlements[0].model_copy(update={
        "garrison_strength": 800,
        "x": 100, "y": 100,
        "siege": Siege(by="Captain Anselm", faction="milan", strength=1000, holdout=5),
    })
    # Far army at dx=35 (ETA 4), near army at dx=15 (ETA 2).
    far = Army(id="far", leader="Captain Thomas", x=135, y=100, strength=1500, units=10)
    near = Army(id="near", leader="Prince Edward", x=115, y=100, strength=1100, units=8)
    r = venice_report.model_copy(update={"settlements": [venice], "armies": [far, near]})
    advices = siege_clock(r)
    assert len(advices) == 1
    a = advices[0]
    assert a.relief_eta == 2
    assert len(a.relief) == 2
    assert a.relief[0] == "Army near: 2 turns away, strength 1100"
    assert a.relief[1] == "Army far: 4 turns away, strength 1500"
    assert "Prince Edward" in a.line


def test_line_contains_holdout_strengths_and_verdict(venice_report):
    venice = venice_report.settlements[0].model_copy(update={
        "name": "Venice",
        "garrison_strength": 900,
        "x": 100, "y": 100,
        "siege": Siege(by="Captain Anselm", faction="milan", strength=1400, holdout=4),
    })
    reliever = Army(id="a2", leader="Prince Edward", x=115, y=100, strength=1100, units=8)
    r = venice_report.model_copy(update={"settlements": [venice], "armies": [reliever]})
    advices = siege_clock(r)
    assert len(advices) == 1
    a = advices[0]
    assert a.holdout == 4
    assert a.garrison_strength == 900
    assert a.attacker_strength == 1400
    assert a.verdict == "hold"
    # Verify the line contains holdout, garrison strength, attacker strength, and verdict
    assert "4" in a.line
    assert "900" in a.line
    assert "1400" in a.line
    assert a.verdict in a.line
    assert a.line == "Siege of Venice: holds 4 more turns; garrison 900 vs attacker 1400 (0.64); Prince Edward 2 turns away (strength 1100): hold for relief."


def test_no_coordinates_skipped_from_relief(venice_report):
    # Settlement with no coordinates cannot compute relief distance.
    venice = venice_report.settlements[0].model_copy(update={
        "x": None, "y": None,
        "garrison_strength": 800,
        "siege": Siege(by="Captain Anselm", faction="milan", strength=1000, holdout=4),
    })
    reliever = Army(id="a2", leader="Prince Edward", x=115, y=100, strength=1100, units=8)
    r = venice_report.model_copy(update={"settlements": [venice], "armies": [reliever]})
    advices = siege_clock(r)
    assert len(advices) == 1
    assert advices[0].relief == []
    assert advices[0].relief_eta is None
    assert advices[0].verdict == "relieve_or_lose"

    # Reliever with no coordinates (bypassing validation via model_construct) is skipped.
    venice_coords = venice.model_copy(update={"x": 100, "y": 100})
    unplaced = Army.model_construct(id="a3", leader="No Coords", x=None, y=None, strength=1100, units=8)
    r2 = venice_report.model_copy(update={"settlements": [venice_coords], "armies": [unplaced]})
    advices2 = siege_clock(r2)
    assert advices2[0].relief == []
    assert advices2[0].relief_eta is None
