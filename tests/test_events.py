from parley.events import diff_reports
from parley.protocol import Agent, Person


def _r(report, **update):
    return report.model_copy(update=update)


def test_no_previous_report_no_events(venice_report):
    assert diff_reports(None, venice_report) == []


def test_stance_change(venice_report):
    before = venice_report
    after = _r(venice_report, factions=[f.model_copy(update={"stance": "war"}) if f.id == "milan" else f
                                        for f in venice_report.factions])
    assert diff_reports(before, after) == ["Milan (milan): now at war with you (was peace)."]


def test_buildings_finished_and_recruits_joined(venice_report):
    # live, Scratch: "Caernarvon's church: check whether it finished (its queue shows empty)"
    from parley.protocol import ForeignSettlement, Training
    venice = venice_report.settlements[0]
    before = _r(venice_report, settlements=[venice.model_copy(update={
        "buildings": ["town_hall", "wooden_pallisade"],
        "training": [Training(unit="Longbowmen", ready_turn=venice_report.turn),
                     Training(unit="Spearmen", ready_turn=venice_report.turn + 5)]})],
        nearby_settlements=[ForeignSettlement(id="Milan", name="Milan", faction="milan", x=1, y=1)])
    after = _r(venice_report, settlements=[venice.model_copy(update={
        "buildings": ["town_hall", "wooden_wall", "small_church"][:3],
        "training": [Training(unit="Spearmen", ready_turn=venice_report.turn + 5)]})],
        nearby_settlements=[ForeignSettlement(id="Milan", name="Milan", faction="hre", x=1, y=1)])
    events = diff_reports(before, after)
    assert f"{venice.name}: wooden_wall finished." in events and f"{venice.name}: small_church finished." in events
    assert f"{venice.name}: wooden_pallisade no longer stands (destroyed or replaced)." in events
    assert f"{venice.name}: Longbowmen finished training and joined the garrison." in events
    assert not any("Spearmen" in e for e in events)
    assert "Milan changed hands: milan → hre." in events
    upgrade = _r(after, settlements=[venice.model_copy(update={"buildings": ["town_hall", "stone_wall", "small_church"]})])
    assert f"{venice.name}: stone_wall finished, replacing wooden_wall." in diff_reports(after, upgrade)


def test_a_bride_who_takes_her_husbands_name_is_not_a_loss(venice_report):
    # live: Crystina of Lydham married Edward of Cantebury and became Crystina of Cantebury; the
    # report called her gone, French assassins nearby, and the ruler mourned a murder
    before = _r(venice_report, family=[Person(name="Crystina of Lydham", family=True, kind="princess",
                                              parent="Humphrey of Lydham")],
                agents=[Agent(id="Crystina of Lydham", kind="princess", x=1, y=1)])
    after = _r(venice_report, family=[Person(name="Crystina of Cantebury", family=True,
                                             parent="Humphrey of Lydham", spouse="Edward of Cantebury")],
               agents=[])
    events = diff_reports(before, after)
    assert "Crystina of Lydham married Edward of Cantebury and now goes by Crystina of Cantebury." in events
    assert not any("assassin" in e.lower() for e in events)


def test_settlement_lost_and_gained(venice_report):
    ragusa = venice_report.settlements[1]
    zagreb = ragusa.model_copy(update={"id": "Zagreb", "name": "Zagreb"})
    after = _r(venice_report, settlements=[venice_report.settlements[0], zagreb])
    events = diff_reports(venice_report, after)
    assert "You lost Ragusa." in events and "You gained Zagreb." in events


def test_army_gone_and_treasury(venice_report):
    after = _r(venice_report, armies=[], treasury=venice_report.treasury + 2000)
    events = diff_reports(venice_report, after)
    assert "Your army Doge Enrico is gone (destroyed, disbanded or merged)." in events
    assert "Treasury: 5000 → 7000 (+2000)." in events


def test_small_treasury_change_reported_too(venice_report):
    after = _r(venice_report, treasury=venice_report.treasury - 300)
    assert diff_reports(venice_report, after) == ["Treasury: 5000 → 4700 (-300)."]


def test_vanished_princess_gets_ranked_causes(venice_report):
    cecilia = Agent(id="Cecilia", kind="princess", x=120, y=88)
    assassin = Agent(id="Konrad", kind="assassin", x=122, y=88, faction="hre")
    before = _r(venice_report, agents=[cecilia], seen_agents=[assassin],
                family=[Person(name="Cecilia", age=36, family=True, kind="princess")])
    after = _r(venice_report, agents=[], family=[Person(name="Cecilia", age=36, family=True, alive=False)],
               character_events=["Cecilia was the target of an assassination attempt"])
    [loss] = [e for e in diff_reports(before, after) if "is gone" in e]
    assert loss.startswith("Cecilia (princess, aged 36) is gone since your last turn.")
    assert "records list them as dead" in loss
    first = loss.index("1) the game reports that Cecilia was the target")
    second = loss.index("2) assassination: hre's assassin Konrad stood 2 tiles away")
    assert first < second and "unlikely so young" in loss


def test_a_general_alive_elsewhere_has_left_service_not_died(venice_report):
    # live: Captain Godwine, "dead" in England's records, alive among the rebels near Frankfurt
    before = _r(venice_report, family=[Person(name="Captain Godwine", age=21, kind="general")])
    after = _r(venice_report, family=[Person(name="Captain Godwine", age=21, alive=False, now_serves="slave")])
    [loss] = [e for e in diff_reports(before, after) if "Godwine" in e]
    assert "has left your service" in loss and "now serving slave" in loss and "dead" not in loss


def test_a_failed_family_read_is_no_massacre(venice_report):
    before = _r(venice_report, family=[Person(name="Rufus", age=39, family=True), Person(name="Henry", age=25)])
    assert not [e for e in diff_reports(before, _r(venice_report, family=[])) if "is gone" in e]


def test_agent_still_there_is_no_loss(venice_report):
    spy = Agent(id="Marco", kind="spy", x=1, y=1)
    after = _r(venice_report, agents=[spy.model_copy(update={"x": 3})])
    assert not [e for e in diff_reports(_r(venice_report, agents=[spy]), after) if "is gone" in e]
