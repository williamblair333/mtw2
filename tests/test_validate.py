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
