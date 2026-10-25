"""Full control: build, recruit, taxes, moving and attacking with armies, checked and shown."""

from parley.control import AREAS
from parley.prompt import build_prompt
from parley.protocol import (Army, Attack, Build, BuildOption, MoveArmy, Orders, Recruit,
                             RecruitOption, SetTax, Unit)
from parley.validate import validate_orders


def _orders(*o):
    return Orders(protocol=1, game_id="test", turn=3, faction="venice", orders=list(o))


def _full(report):
    s = report.settlements[0].model_copy(update={
        "tax_level": "normal", "public_order": 85, "queue": ["wooden_wall"],
        "can_build": [BuildOption(building="market", cost=1200, turns=3)],
        "can_recruit": [RecruitOption(unit="Italian Spear Militia", cost=350, turns=1)]})
    a = report.armies[0].model_copy(update={
        "troops": [Unit(type="Venetian Heavy Infantry", soldiers=40, max_soldiers=60, exp=1)],
        "moves_left": 12, "moves_max": 20})
    enemy = Army(id="Heinrich", faction="hre", leader="Heinrich", x=110, y=70, strength=900, units=6, distance=4)
    return report.model_copy(update={"settlements": [s, *report.settlements[1:]], "armies": [a, *report.armies[1:]],
                                     "visible_enemies": [enemy]})


def test_valid_player_orders_kept(venice_report):
    r = _full(venice_report)
    venice = r.settlements[0].id
    kept, rej = validate_orders(r, _orders(
        Build(settlement=venice, building="market"),
        Recruit(settlement=venice, unit="Italian Spear Militia"),
        SetTax(settlement=venice, level="high"),
        MoveArmy(army=r.armies[0].id, x=115, y=80),
        Attack(army=r.armies[0].id, target="Heinrich")), areas=AREAS)
    assert rej == [] and len(kept.orders) == 5


def test_build_and_recruit_must_be_on_offer_and_affordable(venice_report):
    r = _full(venice_report).model_copy(update={"treasury": 1300})
    venice = r.settlements[0].id
    _, rej = validate_orders(r, _orders(
        Build(settlement=venice, building="cathedral"),
        Build(settlement="Milan", building="market"),
        Build(settlement=venice, building="market"),
        Recruit(settlement=venice, unit="Italian Spear Militia")), areas=AREAS)
    reasons = [x.reason for x in rej]
    assert "can't build 'cathedral'" in reasons[0]
    assert "not owned" in reasons[1]
    assert "treasury too low" in reasons[2]  # 1200 for the market left 100 for the militia


def test_building_already_in_the_queue_is_refused(venice_report):
    r = _full(venice_report)
    _, rej = validate_orders(r, _orders(Build(settlement=r.settlements[0].id, building="wooden_wall")), areas=AREAS)
    assert "already in" in rej[0].reason and "queue" in rej[0].reason


def test_attack_needs_a_foreign_army_in_sight(venice_report):
    r = _full(venice_report)
    _, rej = validate_orders(r, _orders(Attack(army=r.armies[0].id, target="Duke Ottone")), areas=AREAS)
    assert "not in sight" in rej[0].reason


def test_new_orders_belong_to_their_areas(venice_report):
    r = _full(venice_report)
    _, rej = validate_orders(r, _orders(Build(settlement=r.settlements[0].id, building="market"),
                                        SetTax(settlement=r.settlements[0].id, level="low")))
    assert all("not yours to command" in x.reason for x in rej) and len(rej) == 2


def test_prompt_shows_options_only_for_the_seats_areas(venice_report):
    r = _full(venice_report)
    full = build_prompt(r, persona="p", areas=AREAS)
    assert "can build: market (1200 florins, 3 turns)" in full
    assert "can recruit: Italian Spear Militia (350 florins, 1 turn)" in full
    assert "tax normal, public order 85%" in full and "queue: wooden_wall" in full
    assert "Venetian Heavy Infantry 40/60 exp 1" in full and "moves 12/20" in full
    assert '"build"' in full and '"attack"' in full
    ruler = build_prompt(r, persona="p")
    assert "can build:" not in ruler and "can recruit:" not in ruler


# --- review fixes -----------------------------------------------------------------------------

def test_move_army_must_stay_on_the_map(venice_report):
    r = _full(venice_report).model_copy(update={"map_width": 255, "map_height": 200})
    _, rej = validate_orders(r, _orders(MoveArmy(army=r.armies[0].id, x=-3, y=900)), areas=AREAS)
    assert "off the map" in rej[0].reason


def test_attack_carries_the_target_faction_to_the_bridge(venice_report):
    r = _full(venice_report)
    kept, _ = validate_orders(r, _orders(Attack(army=r.armies[0].id, target="Heinrich")), areas=AREAS)
    assert kept.orders[0].target_faction == "hre"


def test_recruit_blocked_settlement_says_why(venice_report):
    r = _full(venice_report)
    s = r.settlements[0].model_copy(update={"can_recruit": [], "recruit_blocked": True})
    p = build_prompt(r.model_copy(update={"settlements": [s]}), persona="p", areas=AREAS)
    assert "can recruit: unknown while units are inside" in p


def test_full_role_is_honest_about_who_else_acts(venice_report):
    human = build_prompt(venice_report.model_copy(update={"human_slot": True}), persona="p", areas=AREAS)
    ai = build_prompt(venice_report, persona="p", areas=AREAS)
    assert "what you don't order doesn't happen" in human and "no governor recruits" in human
    assert "what you don't order doesn't happen" not in ai and "game's own AI also acts" in ai


def test_besiege_can_assault(venice_report):
    from parley.protocol import Besiege
    r = _full(venice_report)
    kept, rej = validate_orders(r, _orders(Besiege(army=r.armies[0].id, settlement="Milan", assault=True)),
                                areas=AREAS)
    assert rej == [] and kept.orders[0].assault
    assert '"assault": true' in build_prompt(r, persona="p", areas=AREAS)


def test_agent_moves_marriage_and_merging(venice_report):
    from parley.protocol import Agent, MergeArmies, MoveAgent, Marry
    r = _full(venice_report)
    a = r.armies[0].model_copy(update={"id": "Robin", "units": 8})
    b = r.armies[0].model_copy(update={"id": "garrison:Caen", "leader": None, "units": 9, "in_settlement": "Caen"})
    r = r.model_copy(update={"armies": [a, b], "map_width": 255, "map_height": 200,
                             "agents": [Agent(id="Cecilia", kind="princess", x=1, y=1),
                                        Agent(id="Laurence", kind="diplomat", x=1, y=1)]})
    kept, rej = validate_orders(r, _orders(
        MoveAgent(agent="Laurence", x=96, y=130),
        Marry(agent="Cecilia", target="Heinrich"),
        MergeArmies(army="garrison:Caen", into="Robin")), areas=AREAS)
    assert rej == [] and len(kept.orders) == 3
    _, rej = validate_orders(r, _orders(
        Marry(agent="Laurence", target="Heinrich"),       # not a princess
        MoveAgent(agent="Cecilia", x=999, y=1),            # off the map
        MergeArmies(army="Robin", into="Robin")), areas=AREAS)
    assert "princess" in rej[0].reason and "off the map" in rej[1].reason and "itself" in rej[2].reason


def test_merge_respects_the_twenty_unit_stack(venice_report):
    from parley.protocol import MergeArmies
    r = _full(venice_report)
    a = r.armies[0].model_copy(update={"id": "A", "units": 15})
    b = r.armies[0].model_copy(update={"id": "B", "units": 8})
    _, rej = validate_orders(r.model_copy(update={"armies": [a, b]}),
                             _orders(MergeArmies(army="A", into="B")), areas=AREAS)
    assert "20" in rej[0].reason


def test_prompt_explains_the_new_orders(venice_report):
    p = build_prompt(_full(venice_report), persona="p", areas=AREAS)
    assert '"move_agent"' in p and '"marry"' in p and '"merge_armies"' in p


def test_naval_orders_checked(venice_report):
    from parley.protocol import Army, Blockade, Board, ForeignSettlement, Land
    r = _full(venice_report)
    fleet = Army(id="Admiral Polo", leader="Admiral Polo", x=118, y=92, strength=100, units=1, is_fleet=True)
    full = Army(id="Admiral Nigel", leader="Admiral Nigel", x=118, y=93, strength=100, units=1, is_fleet=True, carrying=5)
    afloat = Army(id="Robert", leader="Robert", x=118, y=92, strength=900, units=6, aboard="Admiral Polo")
    r = r.model_copy(update={"armies": [*r.armies, fleet, full, afloat], "map_width": 255, "map_height": 200,
                             "nearby_settlements": [ForeignSettlement(id="Bruges", name="Bruges", faction="slave", x=1, y=1)]})
    army = r.armies[0].id
    kept, rej = validate_orders(r, _orders(Board(who=army, fleet="Admiral Polo"), Land(army="Robert", x=114, y=92),
                                           Blockade(fleet="Admiral Polo", settlement="Bruges")), areas=AREAS)
    assert rej == [] and len(kept.orders) == 3
    _, rej = validate_orders(r, _orders(Board(who=army, fleet=army), Board(who=army, fleet="Admiral Nigel"),
                                        Land(army=army, x=1, y=1), Blockade(fleet="Admiral Polo", settlement="Rome")),
                             areas=AREAS)
    reasons = [x.reason for x in rej]
    assert "not one of your fleets" in reasons[0] and "already carries" in reasons[1]
    assert "not aboard" in reasons[2] and "not in sight" in reasons[3]


def test_full_preset_includes_recruiting():
    from parley.control import resolve
    assert "recruit" in resolve("full") and "build" in resolve("full")
