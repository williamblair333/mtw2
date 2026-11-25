"""A ruler is told what its own game AI recruited (live 11-25: France's AI trained 175 units in French
towns in 43 minutes while its ruler disbanded units to pay upkeep, unaware)."""
from parley.prompt import build_prompt, game_recruits_line
from parley.protocol import GameRecruit, RecruitOption
from tests.test_lua_bridge import lua  # noqa: F401  (the fixture)

EVENT = """
    function trained(faction, unit, town)
        BRIDGE.on_unit_trained({ faction = { name = faction }, eduEntry = { eduType = unit },
                                 settlement = { name = town } })
    end
"""


def test_the_bridge_counts_a_seated_factions_trained_units_and_hands_them_over_once(lua):
    lua.execute(EVENT + """
        BRIDGE.seats = { france = true }
        trained('france', 'Arquebusiers', 'Arhus'); trained('france', 'Arquebusiers', 'Arhus')
        trained('france', 'Pikemen', 'Paris'); trained('spain', 'Jinetes', 'Leon')
    """)
    got = lua.eval("BRIDGE.take_game_recruits('france')")
    rows = [dict(got[i]) for i in range(1, len(got) + 1)]
    assert rows == [{"unit": "Arquebusiers", "settlement": "Arhus", "count": 2},
                    {"unit": "Pikemen", "settlement": "Paris", "count": 1}]
    assert len(lua.eval("BRIDGE.take_game_recruits('france')")) == 0
    assert len(lua.eval("BRIDGE.take_game_recruits('spain')")) == 0  # no ruler: not recorded


def test_a_field_that_fails_to_read_still_counts_the_unit(lua):
    lua.execute("""
        BRIDGE.seats = { france = true }
        BRIDGE.on_unit_trained({ faction = { name = 'france' }, settlement = { name = 'Arhus' } })
        BRIDGE.on_unit_trained({ faction = { name = 'france' } })
    """)
    got = lua.eval("BRIDGE.take_game_recruits('france')")
    rows = sorted((got[i].unit, got[i].settlement) for i in range(1, len(got) + 1))
    assert rows == [("a unit", "Arhus"), ("a unit", "a settlement")]


def test_nothing_is_read_before_the_seats_are_known(lua):
    lua.execute("BRIDGE.seats = nil; BRIDGE.on_unit_trained(nil)")  # no error, nothing recorded


def test_the_prompt_says_what_the_ai_trained_and_its_upkeep(venice_report):
    s = venice_report.settlements[0]
    s = s.model_copy(update={"can_recruit": [RecruitOption(unit="Pikemen", cost=300, turns=1, upkeep=150)]})
    r = venice_report.model_copy(update={
        "settlements": [s] + venice_report.settlements[1:],
        "game_recruits": [GameRecruit(unit="Pikemen", settlement="Venice", count=2)]})
    line = game_recruits_line(r)
    assert line == ("Your game AI trained 2 units in your settlements since your last turn (not your orders); "
                    "they add 300 upkeep a turn: 2x Pikemen in Venice.")
    assert line in build_prompt(r, persona="p")
    assert game_recruits_line(venice_report) == ""
