import pytest
from pydantic import ValidationError

from parley.protocol import Orders, StateReport, orders_json_schema


def test_report_roundtrip(venice_report):
    again = StateReport.model_validate_json(venice_report.model_dump_json())
    assert again == venice_report


def test_unknown_order_type_rejected_by_schema():
    with pytest.raises(ValidationError):
        Orders.model_validate(
            {"protocol": 1, "game_id": "g", "turn": 1, "faction": "venice",
             "orders": [{"type": "teleport"}]}
        )


def test_schema_is_json_schema():
    defs = orders_json_schema()["$defs"]
    for name in ("SendGold", "CedeSettlement", "SetStance", "MarchOn", "Besiege", "Withdraw", "Build", "Repair"):
        assert name in defs


def test_repair_order_and_damaged_building_protocol(venice_report):
    from parley.protocol import DamagedBuilding, Repair
    s = venice_report.settlements[0].model_copy(update={
        "damaged_buildings": [DamagedBuilding(name="small_church", hp=40)]
    })
    r = venice_report.model_copy(update={"settlements": [s]})
    r_again = StateReport.model_validate_json(r.model_dump_json())
    assert r_again.settlements[0].damaged_buildings == [DamagedBuilding(name="small_church", hp=40)]

    o = Orders.model_validate({
        "protocol": 1, "game_id": "g", "turn": 1, "faction": "venice",
        "orders": [{"type": "repair", "settlement": "Venice", "building": "small_church"}]
    })
    assert isinstance(o.orders[0], Repair)
    assert (o.orders[0].settlement, o.orders[0].building) == ("Venice", "small_church")


def test_schema_includes_messages():
    from parley.seats.base import strict_schema
    s = strict_schema()
    assert "messages" in s["properties"]
    assert set(s["$defs"]["Say"]["required"]) == {"to", "text"}


def test_orders_messages_default_empty():
    o = Orders.model_validate({"protocol": 1, "game_id": "g", "turn": 1, "faction": "venice", "orders": []})
    assert o.messages == []


def test_orders_carry_a_plan():
    base = {"protocol": 1, "game_id": "g", "turn": 1, "faction": "venice", "orders": []}
    assert Orders.model_validate({**base, "plan": "x"}).plan == "x"
    assert Orders.model_validate(base).plan == ""
    assert "plan" in orders_json_schema()["properties"]


def test_to_orders_keeps_the_plan():
    from parley.seats.base import to_orders
    ids = dict(game_id="g", turn=1, faction="venice")
    assert to_orders({"orders": [], "plan": "Take Milan by turn 12"}, **ids).plan == "Take Milan by turn 12"
    assert to_orders({"orders": [], "plan": ["Take Milan", "Ally Genoa"]}, **ids).plan == "Take Milan\nAlly Genoa"
    assert to_orders({"orders": [], "plan": 5}, **ids).plan == ""
