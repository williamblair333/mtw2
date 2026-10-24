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
    for name in ("SendGold", "CedeSettlement", "SetStance", "MarchOn", "Besiege", "Withdraw"):
        assert name in defs


def test_schema_includes_messages():
    from parley.seats.base import strict_schema
    s = strict_schema()
    assert "messages" in s["properties"]
    assert set(s["$defs"]["Say"]["required"]) == {"to", "text"}


def test_orders_messages_default_empty():
    o = Orders.model_validate({"protocol": 1, "game_id": "g", "turn": 1, "faction": "venice", "orders": []})
    assert o.messages == []
