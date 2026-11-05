"""The steward's garrison backfill: code fills a gap the ruler left, never overrides an order."""

import json

from parley.bridge import TurnDir
from parley.config import GameConfig, SeatConfig
from parley.orchestrator import Orchestrator
from parley.protocol import (
    Army, Disband, MergeArmies, Orders, Recruit, RecruitOption, Settlement, StateReport, Training,
    Unit,
)
from parley.seats import FakeSeat
from parley.steward import (
    STEWARD_RESERVE_TURNS, backfill, garrison_scores, garrison_unit, steward_notes, tax_warning,
)

LEVY = RecruitOption(unit="Levy Spearmen", cost=310, upkeep=125, turns=1)
PEASANTS = RecruitOption(unit="Peasants", cost=110, upkeep=90, turns=1)
COG = RecruitOption(unit="cog", cost=50, upkeep=10, turns=1)
BALLISTA = RecruitOption(unit="NE Ballista", cost=60, upkeep=20, turns=1)


def _settlement(sid, units, can_recruit=(PEASANTS, COG, BALLISTA), **kw):
    kw.setdefault("buildings", [])
    return Settlement(id=sid, name=sid, region=f"{sid}_Province", garrison_strength=units * 100,
                      garrison_units=units, garrison_men=units * 50, population=1000,
                      can_recruit=list(can_recruit), **kw)


def _garrison(sid, units=1):
    return Army(id=f"garrison:{sid}", x=1, y=1, strength=100, units=units, men=units * 50,
                in_settlement=sid, troops=[Unit(type="Spear Militia", soldiers=50)] * units)


def _field(aid="Rufus", units=5):
    return Army(id=aid, leader=aid, x=2, y=2, strength=500, units=units, men=units * 50)


def _report(settlements, armies, treasury=5000, income=500, **kw):
    return StateReport(protocol=1, game_id="g", turn=7, year=1100, faction="england",
                       treasury=treasury, income=income, settlements=settlements, armies=armies,
                       factions=[], visible_enemies=[], last_results=[], **kw)


def _orders(*items, hold_empty=()):
    return Orders(protocol=1, game_id="g", turn=7, faction="england", orders=list(items),
                  hold_empty=list(hold_empty))


AREAS = ("recruit",)


def test_merged_out_garrison_is_backfilled_with_the_cheapest_land_unit():
    rep = _report([_settlement("Nottingham", 2), _settlement("London", 3)],
                  [_garrison("Nottingham", 2), _garrison("London", 3), _field()])
    orders = _orders(MergeArmies(army="garrison:Nottingham", into="Rufus"))
    added, notes = backfill(rep, orders, AREAS, gold_left=5000)
    assert added == [Recruit(settlement="Nottingham", unit="Peasants")]  # not the cog, not the ballista
    assert notes[0]["settlement"] == "Nottingham" and notes[0]["unit"] == "Peasants"


def test_already_empty_settlement_is_backfilled():
    rep = _report([_settlement("Nottingham", 0)], [_field()])
    added, _ = backfill(rep, _orders(), AREAS, gold_left=5000)
    assert [(r.settlement, r.unit) for r in added] == [("Nottingham", "Peasants")]


def test_garrison_with_units_left_is_untouched():
    rep = _report([_settlement("London", 3)], [_garrison("London", 3), _field()])
    orders = _orders(Disband(army="garrison:London", unit="Spear Militia", count=2))
    assert backfill(rep, orders, AREAS, gold_left=5000)[0] == []


def test_disbanding_the_last_unit_empties_it():
    rep = _report([_settlement("London", 1)], [_garrison("London", 1)])
    orders = _orders(Disband(army="garrison:London", unit="Spear Militia", count=1))
    assert [r.settlement for r in backfill(rep, orders, AREAS, gold_left=5000)[0]] == ["London"]


def test_a_recruit_order_from_the_ruler_there_is_enough():
    rep = _report([_settlement("Nottingham", 0)], [_field()])
    orders = _orders(Recruit(settlement="Nottingham", unit="Levy Spearmen"))
    assert backfill(rep, orders, AREAS, gold_left=5000)[0] == []


def test_units_already_in_training_count():
    rep = _report([_settlement("Nottingham", 0, recruit_queue=["Peasants (1 turn left)"])], [_field()])
    assert backfill(rep, _orders(), AREAS, gold_left=5000)[0] == []


def test_hold_empty_by_id_or_name_or_case_leaves_it_alone():
    rep = _report([_settlement("Nottingham", 0)], [_field()])
    for spelled in ("Nottingham", "nottingham", " NOTTINGHAM "):
        added, notes = backfill(rep, _orders(hold_empty=[spelled]), AREAS, gold_left=5000)
        assert added == [] and notes == []


def test_treasury_reserve_blocks_it_and_the_ruler_is_told_why():
    rep = _report([_settlement("Nottingham", 0)], [_field()], income=200)
    # Peasants cost 110, upkeep 90 and STEWARD_RESERVE_TURNS turns of it, plus the income margin of 0
    need = 110 + 90 * STEWARD_RESERVE_TURNS
    added, notes = backfill(rep, _orders(), AREAS, gold_left=need - 1)
    assert added == [] and "treasury" in notes[0]["failed"]
    added, _ = backfill(rep, _orders(), AREAS, gold_left=need)
    assert len(added) == 1


def test_negative_income_widens_the_reserve():
    rep = _report([_settlement("Nottingham", 0)], [_field()], income=-300)
    need = 110 + 90 * STEWARD_RESERVE_TURNS + 300
    assert backfill(rep, _orders(), AREAS, gold_left=need - 1)[0] == []
    assert len(backfill(rep, _orders(), AREAS, gold_left=need)[0]) == 1


def test_gold_is_shared_between_settlements():
    rep = _report([_settlement("A", 0), _settlement("B", 0)], [_field()])
    need = 110 + 90 * STEWARD_RESERVE_TURNS
    added, notes = backfill(rep, _orders(), AREAS, gold_left=need + 50)
    assert [r.settlement for r in added] == ["A"]
    assert notes[1]["settlement"] == "B" and "failed" in notes[1]


def test_nothing_recruitable_is_reported_not_invented():
    rep = _report([_settlement("Nottingham", 0, can_recruit=(COG,))], [_field()])
    added, notes = backfill(rep, _orders(), AREAS, gold_left=5000)
    assert added == [] and "garrison unit" in notes[0]["failed"]


def test_a_seat_without_the_recruit_area_gets_no_steward_orders():
    rep = _report([_settlement("Nottingham", 0)], [_field()])
    assert backfill(rep, _orders(), ("diplomacy",), gold_left=5000) == ([], [])


# --- garrison unit choice: free upkeep while a slot is open, else best defence per upkeep ---

TOWN_MILITIA = RecruitOption(unit="Town Militia", cost=290, upkeep=125, turns=1)
SPEAR_MILITIA = RecruitOption(unit="Spear Militia", cost=310, upkeep=125, turns=1)
BILLMEN = RecruitOption(unit="Billmen", cost=230, upkeep=125, turns=1)
KNIGHTS = RecruitOption(unit="Dismounted Feudal Knights", cost=570, upkeep=225, turns=1)
POOL = (TOWN_MILITIA, SPEAR_MILITIA, PEASANTS, LEVY, COG, BALLISTA)


def test_free_unit_first_while_the_city_has_a_slot():
    s = _settlement("London", 1, can_recruit=POOL, buildings=["wooden_wall"])
    assert garrison_unit(s).unit in ("Town Militia", "Spear Militia")


def test_free_unit_is_skipped_once_the_slots_are_full():
    s = _settlement("London", 3, can_recruit=POOL, buildings=["wooden_wall"])
    held = [Unit(type="Town Militia", soldiers=60)] * 3
    assert garrison_unit(s, held).unit in ("Levy Spearmen", "Spear Militia", "Town Militia")
    assert garrison_unit(s, held).unit != "Peasants"  # 60*3/90 = 2 loses to the shield units at 3.4


def test_training_free_units_use_up_slots():
    s = _settlement("London", 0, can_recruit=(PEASANTS, TOWN_MILITIA), buildings=["wooden_pallisade"],
                    training=[Training(unit="Town Militia", ready_turn=9)],
                    recruit_queue=["Spear Militia (1 turn left)"])
    assert garrison_scores(s)[0][1] is False  # both slots taken: nothing counts as free


def test_castle_has_no_free_slot_but_tourney_fields_gives_one():
    s = _settlement("Nottingham", 0, can_recruit=(TOWN_MILITIA, PEASANTS), buildings=["fortress"])
    assert garrison_scores(s)[0][:2] == ("Town Militia", False)  # 60*7/125 = 3.4 beats Peasants 2.0
    s = _settlement("Nottingham", 0, can_recruit=(PEASANTS, TOWN_MILITIA), buildings=["fortress", "tourney_fields"])
    assert garrison_scores(s)[0][:2] == ("Town Militia", True)


def test_never_ships_or_siege_even_when_they_score_well():
    s = _settlement("London", 0, can_recruit=(COG, BALLISTA), buildings=["wooden_wall"])
    assert garrison_unit(s) is None


def test_best_defence_per_upkeep_beats_cheapest():
    s = _settlement("Nottingham", 0, can_recruit=(PEASANTS, LEVY, BILLMEN), buildings=["fortress"])
    assert garrison_unit(s).unit == "Levy Spearmen"  # 3.36 beats Peasants 2.0; Billmen 1.2
    assert [r[0] for r in garrison_scores(s)] == ["Levy Spearmen", "Peasants", "Billmen"]


def test_elites_are_too_dear_for_a_steward_garrison():
    # live, run7 Nottingham: uncapped it bought Dismounted Feudal Knights (upkeep 225); cap 1.5 x 90
    s = _settlement("Nottingham", 0, can_recruit=(PEASANTS, LEVY, KNIGHTS), buildings=["fortress"])
    assert garrison_unit(s).unit == "Levy Spearmen"
    assert "Dismounted Feudal Knights" not in [r[0] for r in garrison_scores(s)]


def test_unknown_units_fall_back_to_the_cheapest():
    a = RecruitOption(unit="Mystery A", cost=300, upkeep=100, turns=1)
    b = RecruitOption(unit="Mystery B", cost=200, upkeep=100, turns=1)
    assert garrison_unit(_settlement("X", 0, can_recruit=(a, b))).unit == "Mystery B"


def test_backfill_counts_the_free_units_already_in_the_garrison():
    s = _settlement("London", 0, can_recruit=(PEASANTS, TOWN_MILITIA), buildings=["wooden_pallisade"])
    g = Army(id="garrison:London", x=1, y=1, strength=1, units=0, in_settlement="London",
             troops=[Unit(type="Town Militia", soldiers=60)] * 2)  # both free slots used
    added, _ = backfill(_report([s], [g]), _orders(), AREAS, gold_left=5000)
    assert added[0].unit == "Town Militia"  # still the best value, but no longer free: it costs 125


def test_notes_text():
    text = steward_notes([{"settlement": "Nottingham", "name": "Nottingham", "unit": "Levy Spearmen"}])
    assert text == ["Your steward recruited Levy Spearmen in Nottingham (it was left without a garrison). "
                    "To stop this, list the settlement in hold_empty."]
    failed = steward_notes([{"settlement": "London", "name": "London", "failed": "the treasury is too low"}])
    assert "London" in failed[0] and "too low" in failed[0]


def test_tax_warning_flags_high_tax_with_low_order_only():
    low = _settlement("London", 3, tax_level="high", public_order=70, order_parts={"high tax": 4})
    calm = _settlement("Caen", 3, tax_level="high", public_order=175)
    normal = _settlement("Nottingham", 3, tax_level="normal", public_order=40)
    text = tax_warning(_report([low, calm, normal], []))
    assert "London" in text and "70%" in text and "high" in text
    assert "Caen" not in text and "Nottingham" not in text
    assert tax_warning(_report([calm, normal], [])) == ""


# --- the whole turn, through the orchestrator ------------------------------------------------

def _cfg(tmp_path, steward):
    (tmp_path / "saves").mkdir(exist_ok=True)
    return GameConfig(game_id="g", turn_root=tmp_path / "turns", save_dir=tmp_path / "saves",
                      backup_dir=tmp_path / "backups",
                      seats={"england": SeatConfig(brain="fake", persona="p", control="full", steward=steward)})


def _write_turn(cfg, rep, turn):
    d = TurnDir(cfg.turn_root).path_for(cfg.game_id, turn, "england")
    d.mkdir(parents=True, exist_ok=True)
    (d / "state.json").write_text(rep.model_copy(update={"turn": turn, "game_id": "g"}).model_dump_json())
    return d


def _rep():
    return _report([_settlement("Nottingham", 2), _settlement("London", 3)],
                   [_garrison("Nottingham", 2), _garrison("London", 3), _field()])


def test_seat_flag_defaults_off():
    assert SeatConfig(brain="fake", persona="p").steward is False


def test_orchestrator_appends_after_the_rulers_orders_and_tells_the_ruler_next_turn(tmp_path):
    cfg = _cfg(tmp_path, steward=True)
    d1 = _write_turn(cfg, _rep(), 1)
    ruler = FakeSeat([Orders(protocol=1, game_id="g", turn=1, faction="england",
                             orders=[MergeArmies(army="garrison:Nottingham", into="Rufus")])])
    orch = Orchestrator(cfg, {"england": ruler})
    assert orch.run_once() == 1
    sent = Orders.model_validate_json((d1 / "orders.json").read_text())
    assert [o.type for o in sent.orders] == ["merge_armies", "recruit"]  # the ruler's order is first and intact
    assert sent.orders[0] == MergeArmies(army="garrison:Nottingham", into="Rufus")
    assert (sent.orders[1].settlement, sent.orders[1].unit) == ("Nottingham", "Peasants")
    assert json.loads((d1 / "index_map.json").read_text()) == [0, 1]  # the steward's order has its own index
    assert json.loads((d1 / "steward.json").read_text())[0]["settlement"] == "Nottingham"

    # next turn: the ruler reads what the steward did
    d2 = _write_turn(cfg, _rep(), 2)
    orch.run_once()
    prompt = (d2 / "prompt.txt").read_text()
    assert ("Your steward recruited Peasants in Nottingham (it was left without a garrison). "
            "To stop this, list the settlement in hold_empty.") in prompt


def test_orchestrator_honours_hold_empty(tmp_path):
    cfg = _cfg(tmp_path, steward=True)
    d1 = _write_turn(cfg, _rep(), 1)
    ruler = FakeSeat([Orders(protocol=1, game_id="g", turn=1, faction="england",
                             orders=[MergeArmies(army="garrison:Nottingham", into="Rufus")],
                             hold_empty=["Nottingham"])])
    Orchestrator(cfg, {"england": ruler}).run_once()
    sent = Orders.model_validate_json((d1 / "orders.json").read_text())
    assert [o.type for o in sent.orders] == ["merge_armies"]


def test_a_recruit_cut_by_the_order_limit_is_not_claimed(tmp_path, monkeypatch):
    import parley.orchestrator as o
    monkeypatch.setattr(o, "order_cap", lambda report, floor=None: 1)  # the ruler's one order fills the turn
    cfg = _cfg(tmp_path, steward=True)
    d1 = _write_turn(cfg, _rep(), 1)
    ruler = FakeSeat([Orders(protocol=1, game_id="g", turn=1, faction="england",
                             orders=[MergeArmies(army="garrison:Nottingham", into="Rufus")])])
    orch = Orchestrator(cfg, {"england": ruler})
    orch.run_once()
    sent = Orders.model_validate_json((d1 / "orders.json").read_text())
    assert [o.type for o in sent.orders] == ["merge_armies"]
    d2 = _write_turn(cfg, _rep(), 2)
    orch.run_once()
    prompt = (d2 / "prompt.txt").read_text()
    assert "Your steward recruited" not in prompt and "1-order limit" in prompt


def test_seat_without_steward_is_untouched(tmp_path):
    cfg = _cfg(tmp_path, steward=False)
    d1 = _write_turn(cfg, _rep(), 1)
    ruler = FakeSeat([Orders(protocol=1, game_id="g", turn=1, faction="england",
                             orders=[MergeArmies(army="garrison:Nottingham", into="Rufus")])])
    Orchestrator(cfg, {"england": ruler}).run_once()
    sent = Orders.model_validate_json((d1 / "orders.json").read_text())
    assert [o.type for o in sent.orders] == ["merge_armies"]
    assert not (d1 / "steward.json").exists()


def test_hold_empty_survives_parsing_the_rulers_answer():
    from parley.seats.base import to_orders
    o = to_orders({"orders": [], "hold_empty": ["Nottingham", 7]}, game_id="g", turn=1, faction="england")
    assert o.hold_empty == ["Nottingham"]
    assert to_orders({"orders": [], "hold_empty": "London"}, game_id="g", turn=1, faction="england").hold_empty == ["London"]
    assert to_orders({"orders": []}, game_id="g", turn=1, faction="england").hold_empty == []
