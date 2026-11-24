"""A town's recruitment pool holds a count of each unit. Live 11-24 (England turn 4863): six Town
Militia were queued at Dijon, its pool held two, and the game refused four at turn start."""
from parley.control import AREAS
from parley.prompt import _settlement
from parley.protocol import Orders, Recruit, RecruitOption
from parley.validate import validate_orders


def _orders(*items):
    return Orders(protocol=1, game_id="test", turn=1, faction="venice", orders=list(items))


def _with_pool(report, available):
    town = report.settlements[0].model_copy(update={"can_recruit": [
        RecruitOption(unit="Town Militia", cost=10, turns=1, upkeep=5, available=available)]})
    return report.model_copy(update={"settlements": [town, *report.settlements[1:]], "treasury": 10_000}), town


def test_recruits_past_the_pool_are_refused_the_same_turn(venice_report):
    r, town = _with_pool(venice_report, 2)
    orders = _orders(*[Recruit(settlement=town.id, unit="Town Militia") for _ in range(6)])
    kept, rej = validate_orders(r, orders, areas=AREAS)
    assert len(kept.orders) == 2
    assert [x.index for x in rej] == [2, 3, 4, 5]
    assert rej[0].reason == (f"{town.id}'s pool holds 2 Town Militia this turn and the 2 recruits "
                             f"before this one take them")


def test_an_unreported_pool_is_not_checked(venice_report):
    r, town = _with_pool(venice_report, None)
    kept, rej = validate_orders(r, _orders(*[Recruit(settlement=town.id, unit="Town Militia")
                                            for _ in range(3)]), areas=AREAS)
    assert len(kept.orders) == 3 and rej == []


def test_the_report_shows_a_pool_smaller_than_the_queue(venice_report):
    _, town = _with_pool(venice_report, 2)
    assert "Town Militia ×2" in _settlement(town, areas=AREAS)
    full = town.model_copy(update={"can_recruit": [town.can_recruit[0].model_copy(update={"available": 9})]})
    text = _settlement(full, areas=AREAS)
    assert "Town Militia" in text and "×" not in text


def test_the_legend_explains_the_count_only_when_one_shows(venice_report):
    from parley.prompt import _unit_prices_table
    _, town = _with_pool(venice_report, 2)
    assert "×N after a unit" in _unit_prices_table([town])[0][0]
    _, roomy = _with_pool(venice_report, 12)
    assert "×N" not in _unit_prices_table([roomy])[0][0]
