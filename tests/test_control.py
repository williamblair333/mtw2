"""Control areas: which parts of play are the LLM's and which the game's, per seat."""

import pytest

from parley.control import AREAS, ORDER_AREA, resolve
from parley.prompt import build_prompt
from parley.protocol import MarchOn, Orders, SetStance
from parley.validate import validate_orders


def test_presets():
    assert resolve("diplomat") == ("diplomacy",)
    assert resolve("ruler") == ("diplomacy", "armies", "agents")
    assert resolve("full") == AREAS


def test_cherry_picked_areas_keep_canonical_order():
    assert resolve(["build", "diplomacy"]) == ("diplomacy", "build")


def test_unknown_area_or_preset_refused():
    with pytest.raises(ValueError, match="unknown control area 'navy'"):
        resolve(["diplomacy", "navy"])
    with pytest.raises(ValueError, match="control must be"):
        resolve("emperor")


def test_every_order_type_has_an_area():
    from typing import get_args

    from parley.protocol import Order
    types = {m.model_fields["type"].default for m in get_args(get_args(Order)[0])}
    assert types <= set(ORDER_AREA) and set(ORDER_AREA.values()) <= set(AREAS)


def test_seat_control_defaults_to_ruler():
    from parley.config import SeatConfig
    assert SeatConfig(brain="fake", persona="p").areas == ("diplomacy", "armies", "agents")
    assert SeatConfig(brain="fake", persona="p", control=list(AREAS)).areas == AREAS


def _orders(*o):
    return Orders(protocol=1, game_id="test", turn=3, faction="venice", orders=list(o))


def test_orders_outside_the_seats_areas_refused(venice_report):
    kept, rej = validate_orders(venice_report, _orders(
        SetStance(to="milan", stance="peace"), MarchOn(army="Doge Enrico", target_settlement="Milan")),
        areas=("diplomacy",))
    assert [o.type for o in kept.orders] == ["set_stance"]
    assert "'march_on' is armies, not yours to command" in rej[0].reason


def test_prompt_lists_only_the_seats_areas(venice_report):
    p = build_prompt(venice_report, persona="p", areas=("diplomacy",))
    assert "assassinate" not in p and "march_on" not in p
    assert "Your governors and generals handle armies, agents, build, recruit, taxes" in p


def test_full_control_prompt_says_nobody_else_acts(venice_report):
    p = build_prompt(venice_report.model_copy(update={"human_slot": True}), persona="p", areas=AREAS)
    assert "No game AI acts for this realm" in p
