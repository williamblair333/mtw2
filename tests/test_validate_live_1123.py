"""Orders the game refused at turn start on 11-23 (turns 4330-4633) that the validator can refuse the
same turn, while the ruler can still fix them."""
from parley.control import AREAS
from parley.protocol import HireMercenary, MercOption, MergeArmies, MoveArmy, Orders, Withdraw
from parley.validate import validate_orders


def _orders(*items):
    return Orders(protocol=1, game_id="test", turn=1, faction="venice", orders=list(items))


def _armies(report, *armies):
    a = report.armies[0]
    return report.model_copy(update={"armies": [a.model_copy(update=kw) for kw in armies]})


def test_hires_in_one_turn_add_up_to_the_20_unit_limit(venice_report):
    # seven hires refused at turn start, "already holds 20 units": each had been checked against
    # the report's count alone
    pool = [MercOption(unit="Spearmen", cost=10, available=5)]
    r = _armies(venice_report, dict(id="Doge Enrico", leader="Doge Enrico", units=18, is_fleet=False,
                                    can_hire=pool))
    r = r.model_copy(update={"treasury": 10_000})
    hires = [HireMercenary(army="Doge Enrico", unit="Spearmen") for _ in range(3)]
    kept, rej = validate_orders(r, _orders(*hires), areas=AREAS)
    assert len(kept.orders) == 2
    assert [x.index for x in rej] == [2]
    assert rej[0].reason == ("'Doge Enrico' holds 18 units and this turn's 2 hires before this one "
                             "fill it to 20 (an army holds at most 20)")


def test_a_garrison_and_the_general_who_leads_it_are_one_army(venice_report):
    # England turn 4451: refused at turn start as a merge into itself
    r = _armies(venice_report, dict(id="garrison:Venice", leader="Doge Enrico", units=5, is_fleet=False),
                dict(id="Doge Enrico", leader="Doge Enrico", units=3, is_fleet=False))
    _, rej = validate_orders(r, _orders(MergeArmies(army="garrison:Venice", into="Doge Enrico")), areas=AREAS)
    assert rej[0].reason == "'garrison:Venice' and 'Doge Enrico' are one army (Doge Enrico leads it)"


def test_moving_into_a_full_own_town_is_refused_before_the_game(venice_report):
    # Bordeaux and Caen: 8 moves and withdrawals refused at turn start
    town = venice_report.settlements[0].model_copy(update={"x": 120, "y": 88})
    venice_report = venice_report.model_copy(update={"settlements": [town, *venice_report.settlements[1:]]})
    r = _armies(venice_report, dict(id=f"garrison:{town.id}", leader=None, units=18, is_fleet=False),
                dict(id="Captain Rufus", leader="Captain Rufus", units=4, is_fleet=False))
    full = (f"{town.id}'s garrison has 18 units and this army 4: 22, over the 20 a settlement holds, "
            f"so it would stay outside")
    for order in (MoveArmy(army="Captain Rufus", x=town.x, y=town.y),
                  Withdraw(army="Captain Rufus", to_settlement=town.id)):
        _, rej = validate_orders(r, _orders(order), areas=AREAS)
        assert rej and rej[0].reason.startswith(full), (order, rej)
    roomy = _armies(venice_report, dict(id=f"garrison:{town.id}", leader=None, units=16, is_fleet=False),
                    dict(id="Captain Rufus", leader="Captain Rufus", units=4, is_fleet=False))
    _, rej = validate_orders(roomy, _orders(MoveArmy(army="Captain Rufus", x=town.x, y=town.y)), areas=AREAS)
    assert rej == []
