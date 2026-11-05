"""The THREATS block: plain facts computed from the report, near the top of the prompt."""

from parley.prompt import build_prompt
from parley.protocol import Army, FactionView, Settlement
from parley.threats import MAX_THREATS, threat_lines


def _town(i, x, y, men=200, units=5, order=100, tax="normal"):
    return Settlement(id=i, name=i, region=i, garrison_strength=1000 if men else 0, garrison_men=men,
                      garrison_units=units, population=1000, buildings=[], x=x, y=y,
                      public_order=order, tax_level=tax)


def _foe(i, faction, x, y, men=300, fleet=False):
    return Army(id=i, x=x, y=y, strength=3000, men=men, units=6, faction=faction, is_fleet=fleet)


def _calm(report, **update):
    """The fixture realm stripped to one healthy town, so each test adds exactly one problem."""
    base = dict(settlements=[_town("London", 10, 10)], visible_enemies=[], treasury=1000, income=600,
                factions=[FactionView(id="scotland", name="Scotland", stance="war"),
                          FactionView(id="france", name="France", stance="peace")])
    return report.model_copy(update={**base, **update})


def test_nothing_qualifies_so_no_block(venice_report):
    report = _calm(venice_report)
    assert threat_lines(report) == []
    assert "THREATS" not in build_prompt(report, persona="p")


def test_enemy_army_near_a_settlement_names_the_garrison(venice_report):
    report = _calm(venice_report, visible_enemies=[_foe("Brian", "scotland", 13, 12, men=1279)])
    (line,) = threat_lines(report)
    assert "Brian" in line and "scotland" in line and "1279 men" in line
    assert "London" in line and "3 tiles" in line and "200 men" in line


def test_peaceful_and_far_and_fleet_armies_are_not_threats(venice_report):
    report = _calm(venice_report, visible_enemies=[
        _foe("Pal", "france", 11, 11),            # at peace
        _foe("Far", "scotland", 30, 30),          # at war but far
        _foe("Ship", "scotland", 11, 11, fleet=True)])  # a fleet can't storm a town
    assert threat_lines(report) == []


def test_rebels_count_as_enemies(venice_report):
    report = _calm(venice_report, visible_enemies=[_foe("Gawain", "slave", 12, 10, men=152)])
    (line,) = threat_lines(report)
    assert "Gawain" in line and "rebels" in line


def test_empty_and_small_garrisons_are_named(venice_report):
    report = _calm(venice_report, settlements=[
        _town("London", 10, 10, men=0, units=0), _town("Caen", 50, 50, men=20, units=1), _town("York", 70, 70)])
    lines = threat_lines(report)
    assert len(lines) == 2
    assert "London" in lines[0] and "no garrison" in lines[0]
    assert "Caen" in lines[1] and "20 men" in lines[1]


def test_unknown_garrison_men_is_not_called_empty(venice_report):
    town = _town("London", 10, 10, men=0, units=0).model_copy(update={"garrison_strength": 900})
    assert threat_lines(_calm(venice_report, settlements=[town])) == []


def test_treasury_going_negative_next_turn(venice_report):
    (line,) = threat_lines(_calm(venice_report, treasury=300, income=-500))
    assert "300" in line and "-500" in line and "negative" in line


def test_unreported_income_is_not_a_threat(venice_report):
    assert threat_lines(_calm(venice_report, treasury=300, income=0)) == []


def test_low_public_order_warns_of_riots(venice_report):
    report = _calm(venice_report, settlements=[_town("London", 10, 10, order=45, tax="high")])
    (line,) = threat_lines(report)
    assert "London" in line and "45%" in line and "high" in line and "riot" in line


def test_enemy_line_absorbs_that_settlements_garrison_line(venice_report):
    report = _calm(venice_report, settlements=[_town("London", 10, 10, men=0, units=0)],
                   visible_enemies=[_foe("Brian", "scotland", 12, 10)])
    assert len(threat_lines(report)) == 1


def test_block_is_capped_and_sits_between_refusals_and_the_report(venice_report):
    towns = [_town(f"T{i}", i * 20, 0, men=0, units=0) for i in range(8)]
    report = _calm(venice_report, settlements=towns)
    assert len(threat_lines(report)) == MAX_THREATS == 5
    p = build_prompt(report, persona="p")
    assert p.count("\n- ") and p.index("THREATS") < p.index("YOUR SETTLEMENTS")
    assert p.index("YOUR ADVISER" if "YOUR ADVISER" in p else "HOW THE GAME WORKS") < p.index("THREATS")


def test_loaded_enemy_fleet_near_a_settlement_is_a_landing_threat(venice_report):
    fleet = Army(id="Admiral Eoin", x=14, y=10, strength=100, units=2, faction="scotland", is_fleet=True,
                 carrying=5, carrying_men=410, distance=4)
    (line,) = threat_lines(_calm(venice_report, visible_enemies=[fleet]))
    assert "Admiral Eoin (scotland) carries an army of 5 units (410 men), 4 tiles from London" in line
    assert "garrison 5 units, 200 men" in line and "land next turn" in line and "stops the landing" in line


def test_empty_far_or_peaceful_fleets_are_not_landing_threats(venice_report):
    def f(i, faction, x, carrying):
        return Army(id=i, x=x, y=10, strength=100, units=1, faction=faction, is_fleet=True, carrying=carrying)
    report = _calm(venice_report, visible_enemies=[
        f("Empty", "scotland", 12, None), f("Far", "scotland", 30, 4), f("Friend", "france", 12, 4)])
    assert threat_lines(report) == []


def test_foreign_fleet_shows_ships_and_cargo_not_a_one_unit_army():
    from parley.prompt import _foreign_army
    fleet = Army(id="Admiral Eoin", leader="Admiral Eoin", faction="scotland", x=14, y=10, strength=100,
                 units=1, is_fleet=True, carrying=3, carrying_men=240, distance=4)
    empty = fleet.model_copy(update={"carrying": None, "carrying_men": None})
    assert "a fleet of 1 ship, carrying an army of 3 units (240 men), at (14,10)" in _foreign_army(fleet)
    assert "1 units" not in _foreign_army(fleet) and "a fleet of 1 ship, empty" in _foreign_army(empty)
    a = Army(id="Duke", faction="scotland", x=14, y=10, strength=9, units=3, aboard="Admiral Eoin")
    assert "at sea aboard Admiral Eoin" in _foreign_army(a)


def test_provoked_rebellion_is_flagged_with_the_obvious_response(venice_report):
    town = _town("London", 10, 10, order=40, tax="high").model_copy(update={"rebelling": True})
    report = _calm(venice_report, settlements=[town])
    first = threat_lines(report)[0]
    assert "London" in first and "flagged by the game to revolt" in first and "Lower its tax" in first


def test_plague_is_a_threat_line(venice_report):
    town = _town("London", 10, 10).model_copy(update={"plagued": True})
    (line,) = threat_lines(_calm(venice_report, settlements=[town]))
    assert "London has plague" in line


def test_revolt_facts_show_on_the_settlement_line_and_calm_town_has_none(venice_report):
    from parley.prompt import _revolt
    town = _town("London", 10, 10).model_copy(update={
        "rebelling": True, "plagued": True, "turmoil": 2, "rebel_chance": 30, "income": -120, "taxes_income": 800})
    assert _revolt(town) == "FLAGGED TO REVOLT, plague, turmoil 2, rebel chance 30, income -120/turn (taxes 800)"
    assert _revolt(_town("Calm", 1, 1)) == ""
