from parley.protocol import (
    CedeSettlement,
    MarchOn,
    Orders,
    SendGold,
    SetStance,
)
from parley.validate import validate_orders


def _orders(*items):
    return Orders(protocol=1, game_id="test", turn=1, faction="venice", orders=list(items))


def test_validate_gold_over_treasury(venice_report):
    kept, results = validate_orders(venice_report, _orders(SendGold(to="milan", amount=6000)))
    assert kept.orders == []
    assert "treasury" in results[0].reason and not results[0].ok


def test_validate_cede_unowned(venice_report):
    kept, results = validate_orders(venice_report, _orders(CedeSettlement(settlement="milan", to="hre")))
    assert kept.orders == []
    assert "not owned" in results[0].reason


def test_move_army_takes_a_generals_own_name(venice_report):
    # live: Symond leads London's garrison; "move_army Symond Maitland" was refused as unknown
    from parley.protocol import MoveArmy, Person
    report = venice_report.model_copy(update={"family": [
        Person(name="Symond Maitland", family=True, kind="general"),
        Person(name="Agnese", family=True, kind="princess")]})
    kept, results = validate_orders(report, _orders(MoveArmy(army="Symond Maitland", x=1, y=1),
                                                    MoveArmy(army="Agnese", x=1, y=1)))
    assert [r.reason for r in results] == ["unknown army 'Agnese'"] and len(kept.orders) == 1


def test_retrain_needs_an_owned_settlement(venice_report):
    from parley.protocol import Retrain
    own = venice_report.settlements[0].id
    _, results = validate_orders(venice_report.model_copy(update={"human_slot": True}),
                                 _orders(Retrain(settlement=own), Retrain(settlement="Milan")), areas=("recruit",))
    assert [r.reason for r in results] == ["settlement 'Milan' not owned"]
    _, results = validate_orders(venice_report.model_copy(update={"human_slot": False}),
                                 _orders(Retrain(settlement=own)), areas=("recruit",))
    assert results == []  # any faction: a direct write, not the human slot's screens


def test_validate_unknown_faction(venice_report):
    kept, results = validate_orders(venice_report, _orders(SetStance(to="atlantis", stance="war")))
    assert kept.orders == []
    assert "unknown faction" in results[0].reason


def test_validate_unknown_army(venice_report):
    kept, _ = validate_orders(venice_report, _orders(MarchOn(army="zz", target_settlement="ragusa")))
    assert kept.orders == []


def test_validate_ids_not_display_names(venice_report):
    kept, results = validate_orders(venice_report, _orders(SetStance(to="Holy Roman Empire", stance="peace")))
    assert kept.orders == [] and "unknown faction" in results[0].reason
    kept, _ = validate_orders(venice_report, _orders(SetStance(to="hre", stance="peace")))
    assert len(kept.orders) == 1


def test_validate_keeps_good_orders_in_order(venice_report):
    good1 = SetStance(to="milan", stance="alliance")
    bad = SendGold(to="milan", amount=0)
    good2 = SendGold(to="milan", amount=100)
    kept, results = validate_orders(venice_report, _orders(good1, bad, good2))
    assert kept.orders == [good1, good2]
    assert [(r.index, r.ok) for r in results] == [(1, False)]


def test_validate_cannot_target_self(venice_report):
    kept, _ = validate_orders(venice_report, _orders(SendGold(to="venice", amount=10)))
    assert kept.orders == []


# --- agent orders ---

def _with_sight(report):
    from parley.protocol import Agent, Army, ForeignSettlement
    return report.model_copy(update={
        "agents": [Agent(id="Iacopo", kind="assassin", x=121, y=88),
                   Agent(id="Marco", kind="spy", x=120, y=88),
                   Agent(id="Pietro", kind="diplomat", x=119, y=88)],
        "visible_enemies": [Army(id="Heinrich", faction="hre", leader="Heinrich", x=110, y=70,
                                 strength=1100, units=7)],
        "seen_agents": [Agent(id="Ulrich", kind="spy", faction="hre", x=119, y=87)],
        "nearby_settlements": [ForeignSettlement(id="Milan", name="Milan", faction="milan", x=100, y=90)],
    })


def test_agent_orders_valid(venice_report):
    from parley.protocol import Assassinate, Bribe, Sabotage, Spy
    r = _with_sight(venice_report)
    kept, rej = validate_orders(r, _orders(
        Assassinate(agent="Iacopo", target="Heinrich"), Spy(agent="Marco", target="Milan"),
        Bribe(agent="Pietro", target="Ulrich")))
    assert len(kept.orders) == 3 and rej == []
    kept, rej = validate_orders(r, _orders(Sabotage(agent="Iacopo", settlement="Milan")))
    assert len(kept.orders) == 1 and rej == []


def test_one_action_per_agent_per_turn(venice_report):
    from parley.protocol import Assassinate, Sabotage
    r = _with_sight(venice_report)
    kept, rej = validate_orders(r, _orders(Assassinate(agent="Iacopo", target="Nobody"),
                                           Assassinate(agent="Iacopo", target="Heinrich"),
                                           Sabotage(agent="Iacopo", settlement="Milan")))
    assert [o.type for o in kept.orders] == ["assassinate"]
    assert "already has an order this turn" in rej[-1].reason


def test_foreign_army_targeted_by_its_id_not_leader_name(venice_report):
    from parley.protocol import Army, Assassinate
    r = _with_sight(venice_report)
    r.visible_enemies.append(Army(id="Heinrich#2", faction="milan", leader="Heinrich", x=1, y=1,
                                  strength=1, units=1))
    r.visible_enemies[0] = r.visible_enemies[0].model_copy(update={"id": "Heinrich", "leader": "Heinrich of Swabia"})
    _, rej = validate_orders(r, _orders(Assassinate(agent="Iacopo", target="Heinrich of Swabia")))
    assert "not in sight" in rej[0].reason
    kept, rej = validate_orders(r, _orders(Assassinate(agent="Iacopo", target="Heinrich#2")))
    assert rej == []


def test_agent_must_be_yours_and_right_kind(venice_report):
    from parley.protocol import Assassinate
    r = _with_sight(venice_report)
    _, rej = validate_orders(r, _orders(Assassinate(agent="Marco", target="Heinrich"),
                                        Assassinate(agent="Nobody", target="Heinrich")))
    assert "is a spy, not an assassin" in rej[0].reason and "unknown agent" in rej[1].reason


def test_agent_target_must_be_in_sight(venice_report):
    from parley.protocol import Assassinate, Sabotage
    r = _with_sight(venice_report)
    _, rej = validate_orders(r, _orders(Assassinate(agent="Iacopo", target="The Pope"),
                                        Sabotage(agent="Iacopo", settlement="Rome")))
    assert all("not in sight" in x.reason for x in rej) and len(rej) == 2


def test_cannot_target_own_settlement_or_agent(venice_report):
    from parley.protocol import Sabotage, Spy
    r = _with_sight(venice_report)
    _, rej = validate_orders(r, _orders(Sabotage(agent="Iacopo", settlement="Venice"),
                                        Spy(agent="Marco", target="Iacopo")))
    assert len(rej) == 2


# --- messages (Plan 2) ---

from parley.protocol import Say  # noqa: E402
from parley.validate import validate_messages  # noqa: E402


def _none_sent(_to):
    return 0


def test_say_to_unknown_faction_rejected(venice_report):
    kept, rejected = validate_messages(venice_report, [Say(to="atlantis", text="hi")], _none_sent)
    assert kept == [] and "unknown faction" in rejected[0].reason and rejected[0].type == "say"


def test_say_to_self_rejected(venice_report):
    kept, rejected = validate_messages(venice_report, [Say(to="venice", text="hi")], _none_sent)
    assert kept == [] and rejected


def test_say_to_lobby_ok(venice_report):
    kept, rejected = validate_messages(venice_report, [Say(to="lobby", text="hear me")], _none_sent)
    assert kept == [Say(to="lobby", text="hear me")] and rejected == []


def test_say_trimmed_to_600(venice_report):
    kept, _ = validate_messages(venice_report, [Say(to="milan", text="x" * 900)], _none_sent)
    assert len(kept[0].text) == 600


def test_say_cap_per_recipient(venice_report):
    msgs = [Say(to="milan", text="one"), Say(to="milan", text="two")]
    kept, rejected = validate_messages(venice_report, msgs, lambda to: 2)
    assert [m.text for m in kept] == ["one"]
    assert rejected[0].index == 1 and "limit 3 per turn" in rejected[0].reason


def test_say_only_to_players(venice_report):
    """hre is in the game but run by the game's own AI: nobody would read a message to it."""
    kept, rejected = validate_messages(venice_report, [Say(to="hre", text="hi"), Say(to="milan", text="hi")],
                                       _none_sent, players={"milan", "england"})
    assert [m.to for m in kept] == ["milan"]
    assert "not a player" in rejected[0].reason


def test_empty_say_rejected(venice_report):
    kept, rejected = validate_messages(venice_report, [Say(to="milan", text="   ")], _none_sent)
    assert kept == [] and "empty" in rejected[0].reason
