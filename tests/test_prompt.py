from parley.prompt import build_prompt
from parley.protocol import Army, OrderResult, Unit


def test_foreign_army_lists_units_grouped_with_roles():
    from parley.prompt import _foreign_army
    a = Army(id="Heinrich", faction="hre", x=5, y=6, strength=900, men=300, units=7, distance=4,
             troops=[Unit(type="Mailed Knights", soldiers=20)] * 4
             + [Unit(type="Peasant Archers", soldiers=60)] * 2 + [Unit(type="Odd Band", soldiers=30)])
    text = _foreign_army(a)
    print(text)
    assert "\n  troops: 4x Mailed Knights (cavalry), 2x Peasant Archers (missile), Odd Band" in text
    assert "300 men" in text and "more" not in text


def test_foreign_army_without_troops_is_one_line_and_truncation_noted():
    from parley.prompt import _foreign_army
    a = Army(id="X", x=1, y=1, strength=10, units=2)
    assert "\n" not in _foreign_army(a)
    a = Army(id="X", x=1, y=1, strength=10, units=25, troops=[Unit(type="Peasants", soldiers=60)] * 20)
    assert _foreign_army(a).endswith("20x Peasants (infantry), and 5 more")


def test_prompt_lists_ids(venice_report):
    p = build_prompt(venice_report, persona="You are Doge Enrico.")
    assert "hre (Holy Roman Empire)" in p
    assert "venice" in p


def test_prompt_includes_rejections(venice_report):
    report = venice_report.model_copy(update={"last_results": [
        OrderResult(index=0, type="send_gold", ok=False, reason="treasury too low")]})
    assert "treasury too low" in build_prompt(report, persona="p")


def test_prompt_includes_scenario_when_given(venice_report):
    assert "SCENARIO" in build_prompt(venice_report, persona="p", scenario="Humans vs LLMs.")
    assert "SCENARIO" not in build_prompt(venice_report, persona="p")


def test_prompt_states_treasury(venice_report):
    assert "5000" in build_prompt(venice_report, persona="p")


def _msg(channel, sender, text, turn=1):
    from parley.store import Message
    return Message(id=1, game_id="test", turn=turn, channel=channel, sender=sender, text=text, ts=0)


def test_prompt_shows_diplomacy_labels(venice_report):
    p = build_prompt(venice_report, persona="p", diplomacy=[
        _msg("lobby", "milan", "Milan fears no one."),
        _msg("pair:england|venice", "human:england", "Join me against the HRE?", turn=2),
    ], names={"milan": "Duke Ottone", "england": "King of England"})
    assert "[turn 1] [public] Duke Ottone (milan): Milan fears no one." in p
    assert "[turn 2] [private with england] King of England (england): Join me against the HRE?" in p


def test_prompt_says_promises_bind_nothing(venice_report):
    p = build_prompt(venice_report, persona="p", diplomacy=[_msg("lobby", "milan", "hi")])
    assert "bind nothing" in p


def test_prompt_no_diplomacy_section_when_empty(venice_report):
    assert "DIPLOMACY" not in build_prompt(venice_report, persona="p")


def test_prompt_includes_recent_notes(venice_report):
    p = build_prompt(venice_report, persona="p", notes=[(1, "Decline the bribe."), (2, "Watch Milan.")])
    assert "YOUR RECENT NOTES" in p and "[turn 1] Decline the bribe." in p and "[turn 2] Watch Milan." in p


def test_prompt_includes_events(venice_report):
    p = build_prompt(venice_report, persona="p", events=["France declared war on you."])
    assert "SINCE YOUR LAST TURN" in p and "- France declared war on you." in p


def test_prompt_says_dont_repeat(venice_report):
    assert "don't repeat" in build_prompt(venice_report, persona="p").lower()


def test_zero_income_shown_as_unknown(venice_report):
    p = build_prompt(venice_report.model_copy(update={"income": 0}), persona="p")
    assert "Income: not reported" in p and "Income: 0" not in p


def test_faction_line_shows_treaties_and_how_long_the_stance_held(venice_report):
    f = venice_report.factions[0].model_copy(update={"treaties": ["trade rights"], "turns_in_stance": 4})
    p = build_prompt(venice_report.model_copy(update={"factions": [f]}), persona="p")
    assert f"- {f.id} ({f.name}): {f.stance} for 4 turns (trade rights)" in p


def test_recruitment_queue_shown_to_seats_that_recruit(venice_report):
    s = venice_report.settlements[0].model_copy(update={"recruit_queue": ["Peasants (1 turn left)"]})
    r = venice_report.model_copy(update={"settlements": [s]})
    assert "recruiting: Peasants (1 turn left)" in build_prompt(r, persona="p", areas=["recruit"])
    assert "recruiting:" not in build_prompt(r, persona="p")


def test_leaderless_field_stack_has_no_fake_position(venice_report):
    from parley.protocol import Army
    stray = Army(id="stack:8", x=0, y=0, strength=300, units=2)
    p = build_prompt(venice_report.model_copy(update={"armies": [stray]}), persona="p")
    assert "stack:8: 2 units (strength rating 300, not men), position unknown (fleet, fort or no general)" in p
    assert "(0,0)" not in p


def _sighted(report):
    from parley.protocol import Agent, Army, ForeignSettlement
    return report.model_copy(update={
        "agents": [Agent(id="Iacopo", kind="assassin", x=121, y=88, in_settlement="Venice")],
        "visible_enemies": [Army(id="Heinrich", faction="hre", leader="Heinrich", x=110, y=70,
                                 strength=1100, men=280, units=7, distance=4)],
        "seen_agents": [Agent(id="Ulrich", kind="spy", faction="hre", x=119, y=87, distance=2)],
        "nearby_settlements": [ForeignSettlement(id="Milan", name="Milan", faction="milan", x=100, y=90,
                                                 garrison_strength=900, garrison_men=120, garrison_units=3, distance=20)],
    })


def test_prompt_shows_own_agents(venice_report):
    p = build_prompt(_sighted(venice_report), persona="p")
    assert "YOUR AGENTS" in p and "Iacopo: assassin, in Venice" in p


def test_prompt_shows_what_is_in_sight(venice_report):
    p = build_prompt(_sighted(venice_report), persona="p")
    assert ("FOREIGN ARMIES IN SIGHT" in p
            and "Heinrich (hre): 7 units, 280 men (strength rating 1100, not men), at (110,70), 4 tiles away" in p)
    assert "FOREIGN AGENTS IN SIGHT" in p and "- hre spy at (119,87), 2 tiles away: Ulrich" in p
    assert ("SETTLEMENTS NEAR YOU" in p
            and "Milan (milan): garrison 3 units, 120 men (strength rating 900, not men), at (100,90), 20 tiles away" in p)


def test_prompt_marks_a_settlement_across_the_sea(venice_report):
    r = _sighted(venice_report)
    r.nearby_settlements[0].by_land = False
    assert "20 tiles away (across the sea: needs a fleet)" in build_prompt(r, persona="p")
    r.nearby_settlements[0].by_land = True
    assert "across the sea" not in build_prompt(r, persona="p")


def test_foreign_army_shown_by_its_id(venice_report):
    from parley.protocol import Army
    r = _sighted(venice_report)
    r.visible_enemies.append(Army(id="Heinrich#2", faction="milan", leader="Heinrich", x=1, y=1,
                                  strength=5, units=1, distance=9))
    p = build_prompt(r, persona="p")
    assert "- Heinrich#2 (milan), led by Heinrich: 1 units" in p


def test_prompt_explains_agent_orders(venice_report):
    p = build_prompt(venice_report, persona="p")
    assert "assassinate" in p and "your own assassin" in p and "from your sight lists" in p


def test_prompt_explains_sight_is_limited(venice_report):
    assert "only what your armies, agents and settlements can see" in build_prompt(venice_report, persona="p")


def test_old_reports_without_sight_fields_still_parse(venice_state_dict):
    from parley.protocol import StateReport
    r = StateReport.model_validate(venice_state_dict)  # the fixture has none of the new fields
    assert r.agents == [] and r.seen_agents == [] and r.nearby_settlements == []


def test_prompt_lists_popups_answered_for_the_ruler(venice_report):
    p = build_prompt(venice_report.model_copy(update={"popups": ["a siege (siege_scroll -> siege_maintain_button)"]}),
                     persona="p")
    assert "GAME POPUPS SINCE YOUR LAST TURN" in p and "- a siege (siege_scroll -> siege_maintain_button)" in p
    assert "GAME POPUPS" not in build_prompt(venice_report, persona="p")


def test_one_off_spending_is_shown_apart_from_income(venice_report):
    p = build_prompt(venice_report.model_copy(update={"income": 900, "spent_last_turn": 19464,
                                                      "received_last_turn": 200}), persona="p")
    assert "Income: 900 per turn after upkeep and wages" in p
    assert "Last turn you also spent 19464 on buildings, recruits and diplomacy (bribes, gifts)" in p
    assert "and received 200 in gifts" in p


def test_prompt_asks_for_a_readable_note(venice_report):
    p = build_prompt(venice_report, persona="p")
    assert "plain sentences" in p and "short paragraphs" in p


def test_prompt_lists_agent_outcomes(venice_report):
    p = build_prompt(venice_report.model_copy(update={"agent_results": ["Laurence's bribery: not successful"]}),
                     persona="p")
    assert "YOUR AGENTS' MISSIONS SINCE YOUR LAST TURN" in p and "- Laurence's bribery: not successful" in p


def test_prompt_answers_what_the_ruler_kept_asking(venice_report):
    # live, Scratch asked the adviser: what tile is London on, is a cog next to it, did the
    # recruits arrive, what is bleeding us, did the merge take, are they moving toward us
    from parley.protocol import Army, OrderResult, Training
    venice = venice_report.settlements[0].model_copy(update={
        "x": 109, "y": 147, "port_x": 110, "port_y": 147,
        "training": [Training(unit="Longbowmen", ready_turn=27)]})
    fleet = Army(id="Admiral Nigel", leader="Admiral Nigel", x=110, y=146, strength=149, units=1, is_fleet=True)
    foe = Army(id="Manfred", leader="Manfred", faction="hre", x=121, y=141, strength=590, units=6,
               from_x=125, from_y=139)
    r = venice_report.model_copy(update={
        "settlements": [venice] + venice_report.settlements[1:], "armies": venice_report.armies + [fleet],
        "visible_enemies": [foe], "income_parts": {"taxes": 3000, "army upkeep": -2100, "trade": 900},
        "last_results": [OrderResult(index=0, type="merge_armies", ok=True,
                                     now="garrison:Caen has 15 units, in Caen; Paul has 1 units, at (100,130)")]})
    p = build_prompt(r, persona="p")
    assert f"- {venice.id} ({venice.name}), region {venice.region} at (109,147), port at (110,147)" in p
    assert "in training: Longbowmen (joins the garrison on turn 27)" in p
    assert "Admiral Nigel" in p and "beside the port of " + venice.id in p
    assert "Income items: taxes +3000, army upkeep -2100, trade +900." in p
    assert "order 0 (merge_armies): done. Now: garrison:Caen has 15 units" in p
    assert "at (121,141) (last turn at (125,139))" in p


def test_prompt_names_a_besieged_settlement_and_its_besieger(venice_report):
    # Scratch, live: "one of my settlements was reported besieged, and the report doesn't say which"
    from parley.protocol import Siege
    s = venice_report.settlements[0].model_copy(update={
        "siege": Siege(by="Captain Anselm", faction="slave", units=4, men=180, strength=792, turns=1, holdout=6)})
    p = build_prompt(venice_report.model_copy(update={"settlements": [s]}), persona="p")
    assert ("UNDER SIEGE by Captain Anselm (slave), 4 units, 180 men (strength rating 792, not men), "
            "for 1 turn so far; it can hold out 6 turns") in p
    s_men_only = venice_report.settlements[0].model_copy(update={
        "siege": Siege(by="Captain Anselm", faction="slave", men=180, strength=792, turns=1, holdout=6)})
    assert ("UNDER SIEGE by Captain Anselm (slave), 180 men (strength rating 792, not men), "
            "for 1 turn so far; it can hold out 6 turns") in build_prompt(
                venice_report.model_copy(update={"settlements": [s_men_only]}), persona="p")


def test_prompt_includes_adviser_siege_clock_for_besieged_settlement(venice_report):
    from parley.protocol import Siege
    s = venice_report.settlements[0].model_copy(update={
        "siege": Siege(by="Captain Anselm", faction="slave", units=4, men=180, strength=792, turns=1, holdout=6)})
    p = build_prompt(venice_report.model_copy(update={"settlements": [s]}), persona="p")
    assert "adviser's siege clock:" in p
    assert "holds 6 more turns" in p


def test_prompt_has_no_siege_clock_without_siege(venice_report):
    p = build_prompt(venice_report, persona="p")
    assert "adviser's siege clock:" not in p


def test_prompt_builds_when_siege_clock_raises(venice_report, monkeypatch, caplog):
    import parley.prompt
    from parley.protocol import Siege

    def boom(_report):
        raise RuntimeError("siege clock exploded")

    monkeypatch.setattr(parley.prompt, "siege_clock", boom)
    s = venice_report.settlements[0].model_copy(update={
        "siege": Siege(by="Captain Anselm", faction="slave", units=4, men=180, strength=792, turns=1, holdout=6)})
    p = build_prompt(venice_report.model_copy(update={"settlements": [s]}), persona="p")
    assert "adviser's siege clock:" not in p
    assert "UNDER SIEGE by Captain Anselm" in p
    assert "siege_clock failed: siege clock exploded" in caplog.text


def test_prompt_says_where_each_family_member_stands(venice_report):
    # Scratch, live: "Missing: where Garret Harrold is standing, and which army he leads"
    from parley.protocol import Army, Person
    army = Army(id="Garret Harrold", leader="Garret Harrold", x=99, y=127, strength=5640, units=15)
    town = venice_report.settlements[0].model_copy(update={"x": 120, "y": 88})
    family = [Person(name="Garret Harrold", age=30, family=True, kind="general", x=99, y=127),
              Person(name="Rufus", age=52, family=True, role="leader", kind="general", x=120, y=88),
              Person(name="Agnese", age=19, family=True, kind="princess", x=50, y=60)]
    p = build_prompt(venice_report.model_copy(update={"family": family, "armies": [army],
                                                      "settlements": [town]}), persona="p")
    assert "- Garret Harrold, 30, general, leads Garret Harrold at (99,127)" in p
    assert f"- Rufus, 52, leader, general, in {town.id}" in p
    assert "at (50,60)" in p


def test_prompt_lists_family_the_dead_included(venice_report):
    from parley.protocol import Person
    family = [Person(name="Rufus", age=37, family=True, role="leader", kind="general"),
              Person(name="Matilda", age=60, family=True, spouse="William"),
              Person(name="Agnese", age=19, family=True, kind="princess", parent="Rufus"),
              Person(name="Cecilia", age=36, family=True, alive=False),
              Person(name="Laurence", age=40, kind="diplomat")]
    p = build_prompt(venice_report.model_copy(update={"family": family}), persona="p")
    assert "YOUR FAMILY" in p and "- Rufus, 37, leader, general" in p
    assert "- Matilda, 60, married to William" in p and "- Cecilia: dead (at 36)" in p
    assert "- Agnese, 19, princess, unmarried" in p and "child of Rufus" in p
    assert "- Laurence" not in p  # agents outside the family stay in YOUR AGENTS


def test_prompt_includes_game_messages_read_from_the_screen(venice_report):
    p = build_prompt(venice_report, persona="p", game_messages=["New Mission: Take Settlement\nTarget: Antwerp"])
    assert "GAME MESSAGES SINCE YOUR LAST TURN" in p and "Target: Antwerp" in p
    assert "GAME MESSAGES" not in build_prompt(venice_report, persona="p")


def test_prompt_shows_each_factions_size_and_fate(venice_report):
    # the adviser, live: "Is Scotland no more?"
    fs = [venice_report.factions[0].model_copy(update={"settlements": 3, "capital": "Edinburgh",
                                                       "leader": "Sibylla", "armies": 4}),
          venice_report.factions[1].model_copy(update={"settlements": 0, "armies": 0})]
    p = build_prompt(venice_report.model_copy(update={"factions": fs}), persona="p")
    # a quiet faction at peace is grouped with its size; a destroyed one is named as such
    assert f"At peace with no treaties" in p and f"{fs[0].id} (3)" in p
    assert f"- Destroyed: {fs[1].id}" in p


def test_prompt_lists_settlements_seen_before(venice_report):
    from parley.protocol import ForeignSettlement
    cork = ForeignSettlement(id="Cork", name="Cork", faction="slave", x=80, y=160,
                             garrison_strength=400, garrison_men=75, garrison_units=2, seen_turn=12)
    p = build_prompt(venice_report.model_copy(update={"remembered": [cork]}), persona="p")
    assert "SETTLEMENTS SEEN BEFORE" in p
    assert "- Cork (slave): garrison 2 units, 75 men (strength rating 400, not men), at (80,160), seen turn 12" in p


def test_settlement_garrison_shows_units_men_and_strength_rating(venice_report):
    # live: York's totalStrength 13953 read as 13953 men; the garrison was 19 units, 961 men
    york = venice_report.settlements[0].model_copy(update={
        "id": "York", "name": "York", "garrison_units": 19, "garrison_men": 961, "garrison_strength": 13953})
    empty = venice_report.settlements[1].model_copy(update={
        "garrison_units": 0, "garrison_men": 0, "garrison_strength": 0})
    p = build_prompt(venice_report.model_copy(update={"settlements": [york, empty]}), persona="p")
    assert "garrison 19 units, 961 men (strength rating 13953, not men)" in p
    assert f"- {empty.id} ({empty.name}), region {empty.region}: garrison none," in p


def test_remembered_settlement_from_older_report_labels_strength_rating(venice_report):
    from parley.protocol import ForeignSettlement
    old = ForeignSettlement(id="Cork", name="Cork", faction="slave", x=80, y=160, garrison_strength=400, seen_turn=12)
    p = build_prompt(venice_report.model_copy(update={"remembered": [old]}), persona="p")
    assert "- Cork (slave): garrison strength rating 400 (men unknown; not a head count), at (80,160), seen turn 12" in p


def test_own_armies_count_men_and_call_strength_a_rating(venice_report):
    # live: "strength 2494" read as 2494 men; the assault went in with 54 and lost 37
    from parley.protocol import Army, Unit
    henry = Army(id="King Henry", leader="King Henry", x=101, y=174, strength=2494, units=2,
                 troops=[Unit(type="NE Bodyguard", soldiers=32, max_soldiers=20),
                         Unit(type="NE Bodyguard", soldiers=20, max_soldiers=20)])
    plain = Army(id="Prince Robert", leader="Prince Robert", x=100, y=170, strength=1800, men=84, units=3)
    p = build_prompt(venice_report.model_copy(update={"armies": [henry, plain]}), persona="p")
    assert "- King Henry: 2 units, 52 men (strength rating 2494, not men), at (101,174), led by King Henry" in p
    assert "- Prince Robert: 3 units, 84 men (strength rating 1800, not men), at (100,170), led by Prince Robert" in p
    assert "not a head count" in p


def test_output_rules_forbid_quoting_strength_ratings_as_sizes(venice_report):
    p = build_prompt(venice_report, persona="p")
    assert ("- Give army and garrison sizes as units and men, never as a strength rating or a bare "
            "4-5 digit number, even where your older notes did.") in p


def test_public_order_shows_what_holds_it_up(venice_report):
    # live: Nottingham rioted to the rebels after its garrison was disbanded to cut upkeep
    s = venice_report.settlements[0].model_copy(update={
        "tax_level": "high", "public_order": 75,
        # as the game keeps them, live (London): 5% steps, every part positive
        "order_parts": {"law": 11, "buildings": 5, "garrison": 2, "squalor": 10, "high tax": 8}})
    p = build_prompt(venice_report.model_copy(update={"settlements": [s]}), persona="p", areas=["taxes"])
    assert "public order 75% (law +55%, squalor -50%, high tax -40%, buildings +25%, garrison +10%)" in p


def test_factions_say_who_has_a_ruler_and_who_is_ai_run(venice_report):
    # live: England kept setting peace with AI-run Spain and lost Rennes to it under that peace
    f0, f1 = venice_report.factions[0], venice_report.factions[1]
    p = build_prompt(venice_report, persona="p", names={f0.id: "Philip", "adviser:venice": "lord"})
    assert f"- {f0.id} ({f0.name}): {f0.stance}, has a ruler" in p
    assert f"- {f1.id} ({f1.name}): {f1.stance}, run by the game's AI" in p
    assert "setting peace with it does not stop its armies" in p


def test_settlements_say_what_retrain_would_refill(venice_report):
    # live: retrain ordered at Nottingham five turns running, refused each time (pool empty)
    from parley.protocol import Army, RecruitOption, Unit
    s = venice_report.settlements[0].model_copy(update={
        "can_recruit": [RecruitOption(unit="Spear Militia", cost=350, turns=1)]})
    g = Army(id=f"garrison:{s.id}", x=1, y=1, strength=1, units=2, in_settlement=s.id,
             troops=[Unit(type="Spear Militia", soldiers=30, max_soldiers=60),
                     Unit(type="Feudal Knights", soldiers=10, max_soldiers=40)])
    p = build_prompt(venice_report.model_copy(update={"settlements": [s], "armies": [g]}),
                     persona="p", areas=["recruit"])
    assert "retrain would refill: Spear Militia (30/60)" in p
    s2 = s.model_copy(update={"can_recruit": []})
    p = build_prompt(venice_report.model_copy(update={"settlements": [s2], "armies": [g]}),
                     persona="p", areas=["recruit"])
    assert "retrain would refill nothing now" in p


def test_prompt_lists_the_realms_news(venice_report):
    p = build_prompt(venice_report.model_copy(update={"news": ["Riots broke out in Rennes"]}), persona="p")
    assert "NEWS SINCE YOUR LAST TURN" in p and "- Riots broke out in Rennes" in p
    assert "NEWS SINCE" not in build_prompt(venice_report, persona="p")


def test_prompt_starts_with_persona(venice_report):
    assert build_prompt(venice_report, persona="You are Doge Enrico.").startswith("You are Doge Enrico.")


def test_prompt_includes_the_primer(venice_report):
    p = build_prompt(venice_report, persona="I am the Doge.")
    assert "HOW THE GAME WORKS" in p and "merchant" in p.lower()
    assert p.index("I am the Doge.") < p.index("HOW THE GAME WORKS") < p.index("OUTPUT RULES")


def test_primer_missing_file_is_empty(venice_report, monkeypatch, tmp_path):
    import parley.prompt
    monkeypatch.setattr(parley.prompt, "PRIMER_PATH", tmp_path / "missing.md")
    assert parley.prompt.primer() == ""
    assert "HOW THE GAME WORKS" not in build_prompt(venice_report, persona="p")


def test_prompt_shows_the_standing_plan(venice_report):
    p = build_prompt(venice_report, persona="p", plan="1. Take Milan: march Doge Enrico there by turn 12")
    assert "YOUR STANDING PLAN" in p and "Take Milan" in p
    assert "(none yet: write one)" in build_prompt(venice_report, persona="p")
    assert 'Return "plan"' in p


def test_prompt_shows_damaged_buildings_under_settlement(venice_report):
    from parley.protocol import DamagedBuilding
    s = venice_report.settlements[0].model_copy(update={
        "damaged_buildings": [DamagedBuilding(name="small_church", hp=45)]
    })
    r = venice_report.model_copy(update={"settlements": [s, *venice_report.settlements[1:]]})
    p = build_prompt(r, persona="p")
    assert "damaged buildings: small_church (45% health)" in p

    # When no buildings are damaged, "damaged buildings:" is not present
    p_clean = build_prompt(venice_report, persona="p")
    assert "damaged buildings:" not in p_clean


def test_prompt_explains_repair_when_build_in_areas(venice_report):
    p_full = build_prompt(venice_report, persona="p", areas=("build", "diplomacy"))
    assert '"repair": queue the repair of a damaged building in a settlement' in p_full

    p_ruler = build_prompt(venice_report, persona="p", areas=("diplomacy", "armies"))
    assert '"repair": queue the repair' not in p_ruler


def test_prompt_merge_rule_has_no_standing_rule_imperative(venice_report):
    p = build_prompt(venice_report, persona="p")
    assert "STANDING RULE" not in p
    assert "every turn: look over each army's troops" not in p
    assert "Merge worn units of one type when an army has two that can combine" in p


def test_prompt_income_timing_states_balance_honestly(venice_report):
    p = build_prompt(venice_report, persona="p")
    assert "this turn's income arrives before your orders" not in p
    assert "(orders are paid from this balance; this turn's income has not arrived yet)" in p


def test_prompt_debt_block_when_treasury_negative(venice_report):
    from parley.protocol import ForeignSettlement
    rebel = ForeignSettlement(id="Inverness", name="Inverness", faction="rebels", x=100, y=90,
                              garrison_strength=200, garrison_men=80, garrison_units=2, distance=5)
    s = venice_report.settlements[0].model_copy(update={"tax_level": "normal"})
    r = venice_report.model_copy(update={
        "treasury": -450,
        "settlements": [s],
        "nearby_settlements": [rebel],
    })
    p = build_prompt(r, persona="p")
    assert "IN DEBT (Treasury: -450 florins)" in p
    assert "Orders costing gold are refused while the treasury is negative" in p
    assert "Debt is fine while it buys a gain" in p  # the author, 10-30: debt to take a town is fine
    assert "- a1: 9 units" in p
    assert f"- {s.id}: tax level normal" in p
    assert "- Inverness (rebels): garrison 2 units, 80 men" in p
    assert "In your note, write one line per army: an order, or why none." in p


def test_prompt_no_debt_block_when_treasury_positive_or_zero(venice_report):
    p_pos = build_prompt(venice_report, persona="p")
    assert "IN DEBT (Treasury" not in p_pos
    assert "Orders costing gold are refused while the treasury is negative" not in p_pos

    p_zero = build_prompt(venice_report.model_copy(update={"treasury": 0}), persona="p")
    assert "IN DEBT (Treasury" not in p_zero


def test_prompt_playtest_funds_line_present_only_when_on(venice_report):
    p_off = build_prompt(venice_report, persona="p")
    assert "PLAYTEST: your treasury is topped up" not in p_off

    p_false = build_prompt(venice_report, persona="p", playtest_funds=False)
    assert "PLAYTEST: your treasury is topped up" not in p_false

    p_default = build_prompt(venice_report, persona="p", playtest_funds=True)
    expected_default = "PLAYTEST: your treasury is topped up to 50000 florins at the start of each turn; money is not a constraint in this test."
    assert expected_default in p_default

    p_custom = build_prompt(venice_report, persona="p", playtest_funds=True, playtest_funds_amount=75000)
    expected_custom = "PLAYTEST: your treasury is topped up to 75000 florins at the start of each turn; money is not a constraint in this test."
    assert expected_custom in p_custom


def test_prompt_debt_block_suppressed_when_playtest_funds_on(venice_report):
    r = venice_report.model_copy(update={"treasury": -450})
    p_off = build_prompt(r, persona="p", playtest_funds=False)
    assert "IN DEBT (Treasury" in p_off

    p = build_prompt(r, persona="p", playtest_funds=True, playtest_funds_amount=50000)
    assert "IN DEBT (Treasury" not in p
    assert "PLAYTEST: your treasury is topped up to 50000 florins at the start of each turn; money is not a constraint in this test." in p

