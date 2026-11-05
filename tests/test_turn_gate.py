import pytest
from parley.protocol import Army, FactionView, Settlement, Siege, StateReport
from parley.turn_gate import quiet_turn


def test_quiet_turn_returns_empty_when_quiet(venice_report):
    reason = quiet_turn(
        venice_report,
        events=[],
        diplomacy=[],
        game_messages=None,
        quiet_streak=0,
    )
    assert reason == ""


def test_reason_messages_diplomacy(venice_report):
    reason = quiet_turn(
        venice_report,
        events=[],
        diplomacy=["some message"],
        game_messages=None,
        quiet_streak=0,
    )
    assert reason == "messages"


def test_reason_messages_game_messages(venice_report):
    reason = quiet_turn(
        venice_report,
        events=[],
        diplomacy=[],
        game_messages=["pope demands gold"],
        quiet_streak=0,
    )
    assert reason == "messages"


def test_reason_popups(venice_report):
    rep = venice_report.model_copy(update={"popups": ["marriage proposal accepted"]})
    assert quiet_turn(rep, events=[], diplomacy=[], game_messages=None, quiet_streak=0) == "popups"


def test_reason_character_events(venice_report):
    rep = venice_report.model_copy(update={"character_events": ["general died"]})
    assert quiet_turn(rep, events=[], diplomacy=[], game_messages=None, quiet_streak=0) == "character events"


def test_reason_news(venice_report):
    rep = venice_report.model_copy(update={"news": ["crusade called"]})
    assert quiet_turn(rep, events=[], diplomacy=[], game_messages=None, quiet_streak=0) == "news"


def test_reason_stance_changes(venice_report):
    rep = venice_report.model_copy(update={"stance_changes": ["milan declared war"]})
    assert quiet_turn(rep, events=[], diplomacy=[], game_messages=None, quiet_streak=0) == "stance changes"


def test_reason_agent_results(venice_report):
    rep = venice_report.model_copy(update={"agent_results": ["spy executed"]})
    assert quiet_turn(rep, events=[], diplomacy=[], game_messages=None, quiet_streak=0) == "agent results"


def test_reason_events(venice_report):
    assert quiet_turn(venice_report, events=["lost 100 gold"], diplomacy=[], game_messages=None, quiet_streak=0) == "events"


def test_reason_enemy_near_settlement(venice_report):
    # settlement at (10, 10), enemy at war (hre) at (18, 10) -> chebyshev distance = 8 (within 8)
    settlement = Settlement(id="s1", name="S1", region="R", garrison_strength=10, population=1000, buildings=[], x=10, y=10)
    enemy = Army(id="e_hre", faction="hre", x=18, y=10, strength=20, units=2)
    rep = venice_report.model_copy(update={
        "settlements": [settlement],
        "armies": [],
        "visible_enemies": [enemy],
    })
    assert quiet_turn(rep, events=[], diplomacy=[], game_messages=None, quiet_streak=0) == "enemy near"


def test_reason_enemy_near_army(venice_report):
    # army at (20, 20), enemy at war (hre) at (20, 28) -> chebyshev distance = 8 (within 8)
    army = Army(id="own_a", x=20, y=20, strength=10, units=1)
    enemy = Army(id="e_hre", faction="hre", x=20, y=28, strength=20, units=2)
    rep = venice_report.model_copy(update={
        "settlements": [],
        "armies": [army],
        "visible_enemies": [enemy],
    })
    assert quiet_turn(rep, events=[], diplomacy=[], game_messages=None, quiet_streak=0) == "enemy near"


def test_distance_boundary_8_vs_9(venice_report):
    # enemy at distance 9 should not trigger
    army = Army(id="own_a", x=20, y=20, strength=10, units=1)
    enemy = Army(id="e_hre", faction="hre", x=20, y=29, strength=20, units=2)
    rep = venice_report.model_copy(update={
        "settlements": [],
        "armies": [army],
        "visible_enemies": [enemy],
    })
    assert quiet_turn(rep, events=[], diplomacy=[], game_messages=None, quiet_streak=0) == ""


def test_enemy_stance_peace_or_unknown_ignored(venice_report):
    # enemy within 1 tile, but faction 'milan' is at peace
    army = Army(id="own_a", x=20, y=20, strength=10, units=1)
    enemy_milan = Army(id="e_milan", faction="milan", x=20, y=21, strength=20, units=2)
    enemy_unknown = Army(id="e_unknown", faction="unknown_faction", x=20, y=21, strength=20, units=2)
    enemy_none = Army(id="e_none", faction=None, x=20, y=21, strength=20, units=2)

    for foe in [enemy_milan, enemy_unknown, enemy_none]:
        rep = venice_report.model_copy(update={
            "settlements": [],
            "armies": [army],
            "visible_enemies": [foe],
        })
        assert quiet_turn(rep, events=[], diplomacy=[], game_messages=None, quiet_streak=0) == ""


def test_reason_siege(venice_report):
    settlement = Settlement(
        id="s1", name="S1", region="R", garrison_strength=10, population=1000, buildings=[],
        x=10, y=10, siege=Siege(by="enemy_gen", faction="hre"),
    )
    rep = venice_report.model_copy(update={"settlements": [settlement]})
    assert quiet_turn(rep, events=[], diplomacy=[], game_messages=None, quiet_streak=0) == "siege"


def test_reason_money_negative_treasury(venice_report):
    rep = venice_report.model_copy(update={"treasury": -50, "income": 500})
    assert quiet_turn(rep, events=[], diplomacy=[], game_messages=None, quiet_streak=0) == "money"


def test_reason_money_negative_income(venice_report):
    rep = venice_report.model_copy(update={"treasury": 1000, "income": -1})
    assert quiet_turn(rep, events=[], diplomacy=[], game_messages=None, quiet_streak=0) == "money"


def test_money_zero_treasury_and_income_is_quiet(venice_report):
    rep = venice_report.model_copy(update={"treasury": 0, "income": 0})
    assert quiet_turn(rep, events=[], diplomacy=[], game_messages=None, quiet_streak=0) == ""


def test_reason_cadence(venice_report):
    rep = venice_report.model_copy(update={"turn": 5})
    assert quiet_turn(rep, events=[], diplomacy=[], game_messages=None, quiet_streak=0, cadence=5) == "cadence"
    rep0 = venice_report.model_copy(update={"turn": 0})
    assert quiet_turn(rep0, events=[], diplomacy=[], game_messages=None, quiet_streak=0, cadence=5) == "cadence"
    rep4 = venice_report.model_copy(update={"turn": 4})
    assert quiet_turn(rep4, events=[], diplomacy=[], game_messages=None, quiet_streak=0, cadence=5) == ""


def test_reason_streak(venice_report):
    assert quiet_turn(venice_report, events=[], diplomacy=[], game_messages=None, quiet_streak=2, max_streak=2) == "streak"
    assert quiet_turn(venice_report, events=[], diplomacy=[], game_messages=None, quiet_streak=3, max_streak=2) == "streak"
    assert quiet_turn(venice_report, events=[], diplomacy=[], game_messages=None, quiet_streak=1, max_streak=2) == ""


def test_priority_order_of_reasons(venice_report):
    # Test ordering between consecutive reason levels
    # 1. messages before popups
    rep = venice_report.model_copy(update={"popups": ["p"]})
    assert quiet_turn(rep, events=[], diplomacy=["d"], game_messages=None, quiet_streak=0) == "messages"

    # 2. popups before character events
    rep = venice_report.model_copy(update={"popups": ["p"], "character_events": ["c"]})
    assert quiet_turn(rep, events=[], diplomacy=[], game_messages=None, quiet_streak=0) == "popups"

    # 3. character events before news
    rep = venice_report.model_copy(update={"character_events": ["c"], "news": ["n"]})
    assert quiet_turn(rep, events=[], diplomacy=[], game_messages=None, quiet_streak=0) == "character events"

    # 4. news before stance changes
    rep = venice_report.model_copy(update={"news": ["n"], "stance_changes": ["s"]})
    assert quiet_turn(rep, events=[], diplomacy=[], game_messages=None, quiet_streak=0) == "news"

    # 5. stance changes before agent results
    rep = venice_report.model_copy(update={"stance_changes": ["s"], "agent_results": ["a"]})
    assert quiet_turn(rep, events=[], diplomacy=[], game_messages=None, quiet_streak=0) == "stance changes"

    # 6. agent results before events
    rep = venice_report.model_copy(update={"agent_results": ["a"]})
    assert quiet_turn(rep, events=["ev"], diplomacy=[], game_messages=None, quiet_streak=0) == "agent results"

    # 7. events before enemy near
    army = Army(id="own_a", x=20, y=20, strength=10, units=1)
    enemy = Army(id="e_hre", faction="hre", x=20, y=20, strength=20, units=2)
    rep = venice_report.model_copy(update={"settlements": [], "armies": [army], "visible_enemies": [enemy]})
    assert quiet_turn(rep, events=["ev"], diplomacy=[], game_messages=None, quiet_streak=0) == "events"

    # 8. enemy near before siege
    settlement = Settlement(
        id="s1", name="S1", region="R", garrison_strength=10, population=1000, buildings=[],
        x=20, y=20, siege=Siege(by="b", faction="hre"),
    )
    rep = venice_report.model_copy(update={"settlements": [settlement], "armies": [], "visible_enemies": [enemy]})
    assert quiet_turn(rep, events=[], diplomacy=[], game_messages=None, quiet_streak=0) == "enemy near"

    # 9. siege before money
    rep = venice_report.model_copy(update={"settlements": [settlement], "armies": [], "visible_enemies": [], "treasury": -100})
    assert quiet_turn(rep, events=[], diplomacy=[], game_messages=None, quiet_streak=0) == "siege"

    # 10. money before cadence
    rep = venice_report.model_copy(update={"settlements": [], "armies": [], "visible_enemies": [], "treasury": -100, "turn": 5})
    assert quiet_turn(rep, events=[], diplomacy=[], game_messages=None, quiet_streak=0, cadence=5) == "money"

    # 11. cadence before streak
    rep = venice_report.model_copy(update={"settlements": [], "armies": [], "visible_enemies": [], "turn": 5})
    assert quiet_turn(rep, events=[], diplomacy=[], game_messages=None, quiet_streak=5, cadence=5, max_streak=2) == "cadence"
