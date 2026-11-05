"""Full control: build, recruit, taxes, moving and attacking with armies, checked and shown."""

from parley.control import AREAS
from parley.prompt import build_prompt
from parley.protocol import (Army, Attack, Build, BuildOption, MoveArmy, Orders, Recruit,
                             RecruitOption, SetTax, Unit)
from parley.validate import validate_orders


def _orders(*o):
    return Orders(protocol=1, game_id="test", turn=3, faction="venice", orders=list(o))


def _named(report, *ids):
    a = report.armies[0]
    return report.model_copy(update={"armies": [a.model_copy(update={"id": i}) for i in ids]})


def test_a_near_miss_name_of_your_own_is_read_as_its_id(venice_report):
    # live (2026-10-29): 'Admiral_Nigel', 'Caen_garrison', 'Princess Constance' refused as unknown
    from parley.protocol import MergeArmies
    r = _named(venice_report, "Admiral Nigel", "garrison:Caen", "Rufus")
    kept, rej = validate_orders(r, _orders(MoveArmy(army="Admiral_Nigel", x=120, y=89),
                                           MergeArmies(army="Caen_garrison", into="rufus")),
                                areas=AREAS)
    assert rej == []
    assert kept.orders[0].army == "Admiral Nigel"
    assert (kept.orders[1].army, kept.orders[1].into) == ("garrison:Caen", "Rufus")


def test_an_army_written_as_its_captains_army_is_read_as_its_id(venice_report):
    # live (run9 turn 45): France ordered merge_units for "Captain Arthur's Army"
    from parley.protocol import MergeUnits
    r = _named(venice_report, "Captain Arthur", "garrison:Caen")
    kept, rej = validate_orders(r, _orders(MergeUnits(army="Captain Arthur's Army")), areas=AREAS)
    assert rej == []
    assert [o.army for o in kept.orders] == ["Captain Arthur"]


def test_an_army_named_by_its_general_is_read_as_the_army(venice_report):
    # live (2026-10-29): France merged "into Philip", who leads garrison:Paris; refused as unknown
    from parley.protocol import MergeArmies
    a = venice_report.armies[0]
    r = venice_report.model_copy(update={"armies": [a.model_copy(update={"id": "garrison:Paris", "leader": "Philip"}),
                                                    a.model_copy(update={"id": "Captain Adam", "leader": "Captain Adam"})]})
    kept, rej = validate_orders(r, _orders(MergeArmies(army="Captain Adam", into="Philip")), areas=AREAS)
    assert rej == [] and kept.orders[0].into == "garrison:Paris"
    # move_army keeps a general's own name: he steps out of the garrison alone
    kept, _ = validate_orders(r, _orders(MoveArmy(army="Philip", x=120, y=89)), areas=AREAS)
    assert [o.army for o in kept.orders] in ([], ["Philip"])


def test_a_near_miss_settlement_name_is_read_as_its_id(venice_report):
    # live (run8, turn 2): march_on "york" and spy on "york" were refused as unknown and not in
    # sight; the report listed York, and the bridge finds a town only by its exact id
    from parley.protocol import Agent, Besiege, ForeignSettlement, MarchOn, Spy
    york = ForeignSettlement(id="York", name="York", faction="slave", x=106, y=164, distance=1)
    richard = Agent(id="Richard", kind="spy", x=107, y=165)
    r = venice_report.model_copy(update={"nearby_settlements": [york], "agents": [richard]})
    kept, rej = validate_orders(r, _orders(MarchOn(army="a1", target_settlement="york"),
                                           Spy(agent="Richard", target="york"),
                                           Besiege(army="a1", settlement="YORK")), areas=AREAS)
    assert rej == []
    assert kept.orders[0].target_settlement == "York"
    assert kept.orders[1].target == "York"
    assert kept.orders[2].settlement == "York"


def test_an_ambiguous_near_miss_stays_unknown(venice_report):
    r = _named(venice_report, "Robert", "Sir Robert")
    _, rej = validate_orders(r, _orders(MoveArmy(army="ROBERT", x=120, y=89)), areas=AREAS)
    assert rej and "unknown army 'ROBERT'" in rej[0].reason


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


def test_recruit_agent_checked_shown_and_charged(venice_report):
    from parley.protocol import AgentLimit, AgentOption, RecruitAgent
    r = _full(venice_report)
    s = r.settlements[0].model_copy(update={"can_recruit_agents": [AgentOption(agent="merchant", cost=550, turns=1)]})
    r = r.model_copy(update={"settlements": [s, *r.settlements[1:]], "treasury": 850,
                             "agent_limits": {"merchant": AgentLimit(have=0, limit=1),
                                              "spy": AgentLimit(have=2, limit=2),
                                              "diplomat": AgentLimit(have=1)}})
    kept, rej = validate_orders(r, _orders(
        RecruitAgent(settlement=s.id, agent="merchant"),
        RecruitAgent(settlement=s.id, agent="spy"),
        RecruitAgent(settlement=s.id, agent="priest"),
        Recruit(settlement=s.id, unit="Italian Spear Militia")), areas=AREAS)  # 300 left after the merchant
    assert [o.type for o in kept.orders] == ["recruit_agent"]
    assert "spy limit reached: 2 of 2" in rej[0].reason
    assert "can't train a priest" in rej[1].reason and "treasury too low" in rej[2].reason
    p = build_prompt(r, persona="p", areas=AREAS)
    assert "can train agents (florins/turns): merchant 550/" in p and "diplomat 1/no limit; merchant 0/1; spy 2/2" in p
    assert '"recruit_agent"' in p


def test_recruit_agent_counts_this_turns_orders_against_the_limit(venice_report):
    from parley.protocol import AgentLimit, AgentOption, RecruitAgent
    r = _full(venice_report)
    offer = {"can_recruit_agents": [AgentOption(agent="merchant", cost=550, turns=1)]}
    a, b = (s.model_copy(update=offer) for s in r.settlements[:2])
    r = r.model_copy(update={"settlements": [a, b], "treasury": 5000,
                             "agent_limits": {"merchant": AgentLimit(have=0, limit=2)}})
    kept, rej = validate_orders(r, _orders(*(RecruitAgent(settlement=s.id, agent="merchant") for s in (a, b, a))),
                                areas=AREAS)
    assert len(kept.orders) == 2  # two settlements, two merchants: not "already has an order"
    assert "limit reached: 0 of 2, plus 2 ordered this turn" in rej[0].reason


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


def test_the_same_building_ordered_twice_in_a_turn_is_refused_once(venice_report):
    r = _full(venice_report)
    r = r.model_copy(update={"treasury": 99999})
    kept, rej = validate_orders(r, _orders(*[Build(settlement=r.settlements[0].id, building="market")] * 2),
                                areas=AREAS)
    assert len(kept.orders) == 1 and "already ordered" in rej[0].reason


def test_no_more_than_forty_orders_a_turn(venice_report):
    from parley.validate import MAX_ORDERS
    r = _full(venice_report)
    kept, rej = validate_orders(r, _orders(*[SetTax(settlement=r.settlements[0].id, level="normal")] * 45),
                                areas=AREAS)
    assert len(kept.orders) == MAX_ORDERS and len(rej) == 5 and "more than 40" in rej[0].reason


def test_the_order_cap_scales_with_the_realm_and_has_a_ceiling(venice_report):
    from parley.validate import HARD_MAX_ORDERS, MAX_ORDERS, order_cap
    extra = len(venice_report.armies) + len(venice_report.agents)
    n = len(venice_report.settlements)
    assert order_cap(venice_report) == max(MAX_ORDERS, 3 * n + extra)
    big = venice_report.model_copy(update={"settlements": venice_report.settlements * 20})
    assert order_cap(big) == min(HARD_MAX_ORDERS, max(MAX_ORDERS, 3 * 20 * n + extra))
    huge = venice_report.model_copy(update={"settlements": venice_report.settlements * 500})
    assert order_cap(huge) == HARD_MAX_ORDERS


def test_a_big_realm_gets_more_orders_than_forty(venice_report):
    r = _full(venice_report)
    r = r.model_copy(update={"settlements": r.settlements * 20})
    kept, rej = validate_orders(r, _orders(*[SetTax(settlement=r.settlements[0].id, level="normal")] * 60),
                                areas=AREAS)
    assert len(kept.orders) == min(60, 3 * len(r.settlements) + len(r.armies) + len(r.agents)) and len(kept.orders) > 40


def test_refused_orders_do_not_use_the_order_budget(venice_report):
    from parley.validate import MAX_ORDERS
    r = _full(venice_report)
    bad = [SetTax(settlement="nowhere", level="normal")] * 30
    good = [SetTax(settlement=r.settlements[0].id, level="normal")] * MAX_ORDERS
    kept, rej = validate_orders(r, _orders(*bad, *good), areas=AREAS)
    assert len(kept.orders) == MAX_ORDERS and len(rej) == 30


def test_fleets_get_no_land_army_orders(venice_report):
    from parley.protocol import Besiege, MarchOn, MergeArmies
    r = _full(venice_report)
    fleet = Army(id="Admiral Polo", leader="Admiral Polo", x=118, y=92, strength=100, units=1, is_fleet=True)
    afloat = Army(id="Robert", leader="Robert", x=118, y=92, strength=900, units=6, aboard="Admiral Polo")
    r = r.model_copy(update={"armies": [*r.armies, fleet, afloat]})
    army = r.armies[0].id
    _, rej = validate_orders(r, _orders(Besiege(army="Admiral Polo", settlement="Milan"),
                                        MarchOn(army="Admiral Polo", target_settlement="Milan"),
                                        MergeArmies(army="Admiral Polo", into=army),
                                        MergeArmies(army="Robert", into=army)), areas=AREAS)
    assert [x.index for x in rej] == [0, 1, 2, 3]
    assert "is a fleet" in rej[0].reason and "can't merge" in rej[2].reason and "aboard" in rej[3].reason


def test_negative_coordinates_refused_without_a_map_size(venice_report):
    r = _full(venice_report).model_copy(update={"map_width": None, "map_height": None})
    _, rej = validate_orders(r, _orders(MoveArmy(army=r.armies[0].id, x=-5, y=3)), areas=AREAS)
    assert "off the map" in rej[0].reason


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
    assert "can build (florins/turns): market 1200/3" in full
    assert "can recruit (florins/turns, upkeep a turn): Italian Spear Militia 350/1" in full
    assert "tax normal, public order 85%" in full and "queue: wooden_wall" in full
    assert "Venetian Heavy Infantry 40/60 exp 1" in full and "moves 12/20" in full
    assert '"build"' in full and '"attack"' in full
    ruler = build_prompt(r, persona="p")
    assert "can build:" not in ruler and "can recruit:" not in ruler


def test_recruit_options_show_their_upkeep(venice_report):
    # live (2026-10-29): England bought knights it couldn't keep; the list showed only the price
    r = _full(venice_report)
    r.settlements[0].can_recruit[0].upkeep = 120
    s = r.settlements[0]
    r.settlements[0] = s.model_copy(update={"buildings": ["castle"]})  # no free slots: pays its upkeep
    assert "Italian Spear Militia 350/1, upkeep 120" in build_prompt(r, persona="p", areas=AREAS)
    r.settlements[0] = s.model_copy(update={"buildings": ["stone_wall"], "recruit_queue": []})
    assert "Italian Spear Militia 350/1, free upkeep (4 left)" in build_prompt(r, persona="p", areas=AREAS)


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


def test_repair_order_checked_and_kept(venice_report):
    from parley.protocol import DamagedBuilding, Repair
    r = _full(venice_report)
    venice = r.settlements[0].id
    s = r.settlements[0].model_copy(update={
        "damaged_buildings": [DamagedBuilding(name="small_church", hp=50)]
    })
    r = r.model_copy(update={"settlements": [s, *r.settlements[1:]]})

    kept, rej = validate_orders(r, _orders(Repair(settlement=venice, building="small_church")), areas=AREAS)
    assert rej == [] and len(kept.orders) == 1

    # refused when building is not damaged
    _, rej = validate_orders(r, _orders(Repair(settlement=venice, building="cathedral")), areas=AREAS)
    assert len(rej) == 1 and "has no damaged building 'cathedral'" in rej[0].reason

    # refused when settlement is unowned
    _, rej = validate_orders(r, _orders(Repair(settlement="Milan", building="small_church")), areas=AREAS)
    assert len(rej) == 1 and "settlement 'Milan' not owned" in rej[0].reason

    # refused when seat lacks build area
    _, rej = validate_orders(r, _orders(Repair(settlement=venice, building="small_church")), areas=("diplomacy", "armies"))
    assert len(rej) == 1 and "'repair' is build, not yours to command" in rej[0].reason


def test_repair_order_refused_when_already_in_queue_or_duplicate(venice_report):
    from parley.protocol import DamagedBuilding, Repair
    r = _full(venice_report)
    venice = r.settlements[0].id
    s = r.settlements[0].model_copy(update={
        "queue": ["small_church"],
        "damaged_buildings": [DamagedBuilding(name="small_church", hp=50)]
    })
    r = r.model_copy(update={"settlements": [s, *r.settlements[1:]]})

    _, rej = validate_orders(r, _orders(Repair(settlement=venice, building="small_church")), areas=AREAS)
    assert len(rej) == 1 and "already in" in rej[0].reason and "queue" in rej[0].reason

    # duplicate in same turn
    s2 = r.settlements[0].model_copy(update={"queue": []})
    r2 = r.model_copy(update={"settlements": [s2, *r.settlements[1:]]})
    kept, rej = validate_orders(r2, _orders(
        Repair(settlement=venice, building="small_church"),
        Repair(settlement=venice, building="small_church"),
    ), areas=AREAS)
    assert len(kept.orders) == 1 and len(rej) == 1 and "already ordered for" in rej[0].reason


def test_hire_mercenary_checked_shown_and_charged(venice_report):
    from parley.protocol import HireMercenary, MercOption
    r = _full(venice_report)
    a = r.armies[0].model_copy(update={"leader": "Doge Enrico", "units": 4, "can_hire": [
        MercOption(unit="Albanian Mercenaries", cost=570, available=2, max=3, exp=1)]})
    nolead = a.model_copy(update={"id": "garrison:X", "leader": None})
    fleet = a.model_copy(update={"id": "Fleet", "is_fleet": True})
    r = r.model_copy(update={"armies": [a, nolead, fleet], "treasury": 1000})
    kept, rej = validate_orders(r, _orders(
        HireMercenary(army=a.id, unit="Albanian Mercenaries"),
        HireMercenary(army=a.id, unit="Albanian Mercenaries"),  # 430 left
        HireMercenary(army=a.id, unit="Swiss Pikemen"),
        HireMercenary(army="garrison:X", unit="Albanian Mercenaries"),
        HireMercenary(army="Fleet", unit="Albanian Mercenaries"),
        HireMercenary(army="Nowhere", unit="Albanian Mercenaries")), areas=AREAS)
    assert [o.type for o in kept.orders] == ["hire_mercenary"]
    assert "treasury too low (430 left, needs 570)" in rej[0].reason
    assert "can't hire 'Swiss Pikemen' where it stands" in rej[1].reason and "no general" in rej[2].reason
    assert "is a fleet" in rej[3].reason and "unknown army" in rej[4].reason
    p = build_prompt(r, persona="p", areas=AREAS)
    assert "mercenaries for hire here" in p and "Albanian Mercenaries 570, 2/3, exp 1" in p and '"hire_mercenary"' in p
    # only a seat that controls recruiting may hire
    _, rej = validate_orders(r, _orders(HireMercenary(army=a.id, unit="Albanian Mercenaries")))
    assert rej and "recruit" in rej[0].reason
