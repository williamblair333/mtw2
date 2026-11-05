"""The turn audit: plain checks over turn folders that sort problems into bridge, ruler and option."""

import json

from parley.audit import alert_lines, audit_game, format_audit, new_findings, ruler_notes


def _turn(root, turn, faction, *, state=None, orders=None, results=None, rejected=None):
    d = root / "g1" / f"turn-{turn:04d}" / faction
    d.mkdir(parents=True, exist_ok=True)
    for name, doc in (("state.json", state), ("results.json", results), ("rejected.json", rejected)):
        if doc is not None:
            (d / name).write_text(json.dumps(doc))
    if orders is not None:
        (d / "orders.json").write_text(json.dumps({"orders": orders, "note": ""}))
    return d


def _state(armies=(), agents=(), treasury=1000, income=100):
    return {"armies": list(armies), "agents": list(agents), "settlements": [],
            "treasury": treasury, "income": income}


def _checks(root):
    return {(f.bin, f.check) for f in audit_game(root / "g1")}


def test_done_but_did_not_move_is_a_bridge_bug(tmp_path):
    # live: 136 march_on/withdraw orders came back "done" while the army stayed put
    rufus = {"id": "Rufus", "leader": "Rufus", "x": 105, "y": 156}
    _turn(tmp_path, 1, "england", state=_state([rufus]),
          orders=[{"type": "move_army", "army": "Rufus", "x": 107, "y": 155}],
          results=[{"index": 0, "type": "move_army", "ok": True, "reason": ""}])
    _turn(tmp_path, 2, "england", state=_state([rufus]))
    assert ("bridge", "done but didn't move") not in _checks(tmp_path)  # not judged on the next report
    _turn(tmp_path, 3, "england", state=_state([rufus]))
    assert ("bridge", "done but didn't move") in _checks(tmp_path)


def test_a_march_on_from_the_next_tile_besieges_and_is_not_flagged(tmp_path):
    # live (run8): Rufus marched on York from the next tile; the bridge now besieges it there
    rufus = {"id": "Rufus", "leader": "Rufus", "x": 107, "y": 163}
    york = {"id": "York", "name": "York", "faction": "slave", "x": 106, "y": 164}
    state = dict(_state([rufus]), nearby_settlements=[york])
    _turn(tmp_path, 1, "england", state=state,
          orders=[{"type": "march_on", "army": "Rufus", "target_settlement": "York"}],
          results=[{"index": 0, "type": "march_on", "ok": True, "reason": ""}])
    _turn(tmp_path, 2, "england", state=state)
    _turn(tmp_path, 3, "england", state=state)
    assert ("bridge", "done but didn't move") not in _checks(tmp_path)


def test_a_move_that_lands_after_the_next_report_is_not_flagged(tmp_path):
    # live (2026-10-29): Laurence Bidell still on his old tile in the next report, on his target after
    start, there = {"id": "Laurence", "x": 112, "y": 131}, {"id": "Laurence", "x": 116, "y": 128}
    _turn(tmp_path, 1, "england", state=_state(agents=[start]),
          orders=[{"type": "move_agent", "agent": "Laurence", "x": 116, "y": 128}],
          results=[{"index": 0, "type": "move_agent", "ok": True, "reason": ""}])
    _turn(tmp_path, 2, "england", state=_state(agents=[start]))
    _turn(tmp_path, 3, "england", state=_state(agents=[there]))
    assert ("bridge", "done but didn't move") not in _checks(tmp_path)


def test_a_garrison_that_marched_out_is_followed_by_its_leader(tmp_path):
    g = {"id": "garrison:Rheims", "leader": "Raoulet", "x": 119, "y": 133}
    _turn(tmp_path, 1, "france", state=_state([g]),
          orders=[{"type": "move_army", "army": "garrison:Rheims", "x": 119, "y": 132}],
          results=[{"index": 0, "type": "move_army", "ok": True, "reason": ""}])
    # the town keeps a garrison under a new id; Raoulet is now out on (119,132)
    out = _state([{"id": "garrison:Rheims", "leader": "Militia", "x": 119, "y": 133},
                  {"id": "Raoulet", "leader": "Raoulet", "x": 119, "y": 132}])
    _turn(tmp_path, 2, "france", state=out)
    _turn(tmp_path, 3, "france", state=out)
    assert ("bridge", "done but didn't move") not in _checks(tmp_path)


def test_an_army_used_after_merging_it_away_is_a_ruler_mistake(tmp_path):
    # live (2026-10-29): merge garrison:Edinburgh into Rufus, then five disbands from the garrison
    g = {"id": "garrison:Edinburgh", "leader": "x", "x": 102, "y": 174}
    _turn(tmp_path, 1, "england", state=_state([g, {"id": "Rufus", "x": 101, "y": 173}]),
          orders=[{"type": "merge_armies", "army": "garrison:Edinburgh", "into": "Rufus"},
                  {"type": "disband", "army": "garrison:Edinburgh", "unit": "Peasants"}],
          results=[{"index": 0, "type": "merge_armies", "ok": True, "reason": ""},
                   {"index": 1, "type": "disband", "ok": False, "reason": "unknown army 'garrison:Edinburgh'"}])
    _turn(tmp_path, 2, "england", state=_state([g]))  # the town has a garrison again next turn
    found = audit_game(tmp_path / "g1")
    assert [(f.bin, f.check) for f in found if "Edinburgh" in f.detail] == [("ruler", "used after merging it away")]
    assert "Order for an army before merging it" in ruler_notes(found, "england", 1)[0]


def test_a_listed_name_refused_after_it_moved_is_a_bridge_bug(tmp_path):
    # live: France moved garrison:Rheims out, then merged it by its old id
    g = {"id": "garrison:Rheims", "leader": "Raoulet", "x": 119, "y": 133}
    _turn(tmp_path, 1, "france", state=_state([g]),
          orders=[{"type": "move_army", "army": "garrison:Rheims", "x": 119, "y": 132},
                  {"type": "merge_armies", "army": "garrison:Rheims", "into": "Charles"}],
          results=[{"index": 0, "type": "move_army", "ok": True, "reason": ""},
                   {"index": 1, "type": "merge_armies", "ok": False, "reason": "unknown army 'garrison:Rheims'"}])
    found = [f for f in audit_game(tmp_path / "g1") if f.check == "listed name refused"]
    assert found and "earlier order this turn moved it" in found[0].detail


def test_a_refused_earlier_move_is_not_a_move_that_lost_the_name(tmp_path):
    # live run9 turn 32: Captain Luquin died besieging Caen before France's orders ran; both his
    # move_army and his merge_units came back unknown
    luquin = {"id": "Captain Luquin", "leader": "Captain Luquin", "x": 103, "y": 134}
    _turn(tmp_path, 1, "france", state=_state([luquin]),
          orders=[{"type": "move_army", "army": "Captain Luquin", "x": 103, "y": 115},
                  {"type": "merge_units", "army": "Captain Luquin"}],
          results=[{"index": 0, "type": "move_army", "ok": False, "reason": "unknown army 'Captain Luquin'"},
                   {"index": 1, "type": "merge_units", "ok": False, "reason": "unknown army 'Captain Luquin'"}])
    _turn(tmp_path, 2, "france", state=_state([]))
    assert not any(f.check == "listed name refused" for f in audit_game(tmp_path / "g1"))


def test_a_name_gone_before_its_order_ran_is_not_flagged(tmp_path):
    robert = {"id": "Captain Robert", "leader": "Captain Robert", "x": 112, "y": 130}
    _turn(tmp_path, 1, "france", state=_state([robert]),
          orders=[{"type": "merge_armies", "army": "Captain Robert", "into": "Philip"}],
          results=[{"index": 0, "type": "merge_armies", "ok": False, "reason": "unknown army 'Captain Robert'"}])
    _turn(tmp_path, 2, "france", state=_state([]))  # died in a battle before France's turn
    assert not any(f.check == "listed name refused" for f in audit_game(tmp_path / "g1"))


def test_near_miss_names_are_told_apart_from_made_up_ones(tmp_path):
    _turn(tmp_path, 1, "england", state=_state([{"id": "Admiral Nigel", "x": 1, "y": 1},
                                                {"id": "garrison:Caen", "leader": "x", "x": 2, "y": 2}]),
          orders=[], rejected=[{"type": "move_army", "reason": "unknown army 'Admiral_Nigel'"},
                               {"type": "merge_armies", "reason": "unknown army 'Caen_garrison'"},
                               {"type": "bribe", "reason": "unknown agent 'Laurence Bidell' (not one of yours)"}])
    checks = [(f.check, f.detail) for f in audit_game(tmp_path / "g1")]
    assert sum(c == "near-miss name" for c, _ in checks) == 2
    assert any(c == "name not in report" and "Laurence Bidell" in d for c, d in checks)


def test_a_refused_name_with_an_apostrophe_is_read_whole(tmp_path):
    # live (run9 turn 45): "unknown army 'Captain Arthur's Army'" was read as 'Captain Arthur', a
    # listed army, and reported as a bridge bug
    arthur = {"id": "Captain Arthur", "leader": "Captain Arthur", "x": 119, "y": 100}
    _turn(tmp_path, 1, "france", state=_state([arthur]), orders=[],
          rejected=[{"type": "merge_units", "reason": "unknown army 'Captain Arthur's Army'"}])
    _turn(tmp_path, 2, "france", state=_state([arthur]))
    checks = [(f.check, f.detail) for f in audit_game(tmp_path / "g1")]
    assert not any(c == "listed name refused" for c, _ in checks), checks
    assert any("Captain Arthur's Army" in d for _, d in checks), checks


def test_an_agent_order_naming_a_general_is_a_ruler_mistake(tmp_path):
    # live (2026-10-29, turn 138): the audit called France's move_agent on its generals a bridge bug
    g = {"id": "Godfrey", "leader": "Godfrey", "x": 140, "y": 156}
    _turn(tmp_path, 1, "france", state=_state([g]), orders=[],
          rejected=[{"type": "move_agent", "reason": "unknown agent 'Godfrey' (not one of yours)"}])
    _turn(tmp_path, 2, "france", state=_state([g]))
    assert [(f.bin, f.check) for f in audit_game(tmp_path / "g1")] == [("ruler", "agent order for a general")]


def test_the_same_refusal_two_turns_running_is_a_ruler_mistake(tmp_path):
    for t, xy in ((1, "93,168"), (2, "92,165")):
        _turn(tmp_path, t, "england", state=_state(), orders=[{"type": "move_army", "army": "Admiral Nigel"}],
              results=[{"index": 0, "type": "move_army", "ok": False,
                        "reason": f"a fleet can't sail onto land ({xy}); the nearest sea is (94,167)"}])
    found = [f for f in audit_game(tmp_path / "g1") if f.check == "same refusal again"]
    assert len(found) == 1 and found[0].turn == 2 and found[0].bin == "ruler"


def test_debt_flags_the_runway_and_a_missing_disband(tmp_path):
    _turn(tmp_path, 1, "england", state=_state(treasury=300, income=-96), orders=[])
    checks = _checks(tmp_path)
    assert ("ruler", "money running out") in checks and ("option", "in debt, no disband") in checks
    _turn(tmp_path, 2, "france", state=_state(treasury=300, income=-96), orders=[{"type": "disband"}])
    assert not any(f.faction == "france" and f.check == "in debt, no disband" for f in audit_game(tmp_path / "g1"))


def test_seat_errors_and_unanswered_turns_are_bridge_side(tmp_path):
    d = _turn(tmp_path, 1, "milan", state=_state(), orders=[])
    (d / "orders.json").write_text(json.dumps({"orders": [], "note": "seat error: agy status ERROR"}))
    _turn(tmp_path, 2, "milan", state=_state())  # no orders.json
    _turn(tmp_path, 3, "milan", state=_state(), orders=[])
    assert {("bridge", "seat error"), ("bridge", "unanswered")} <= _checks(tmp_path)


def test_format_groups_repeats_and_keys_ignore_numbers(tmp_path):
    for t in (1, 2, 3):
        _turn(tmp_path, t, "england", state=_state(treasury=10 * t, income=-50), orders=[])
    found = audit_game(tmp_path / "g1")
    runway = [f for f in found if f.check == "money running out"]
    assert len({f.key for f in runway}) == 1  # one problem, three turns
    text = format_audit(found, "g1")
    assert "**money running out** (england, 3x, turns 1, 2, 3)" in text
    assert format_audit([], "g1").endswith("Nothing found.\n")


def test_new_findings_alert_each_problem_once(tmp_path):
    for t in (1, 2):
        _turn(tmp_path, t, "england", state=_state(treasury=10, income=-50), orders=[])
    game = tmp_path / "g1"
    first = new_findings(game, audit_game(game))
    assert {f.check for f in first} == {"money running out", "in debt, no disband"} and len(first) == 2
    _turn(tmp_path, 3, "england", state=_state(treasury=5, income=-60), orders=[])
    assert new_findings(game, audit_game(game)) == []  # same problems, another turn: no new alert


def test_alert_lines_put_bridge_bugs_first_and_cap_the_rest(tmp_path):
    from parley.audit import ALERTS_PER_TURN, Finding
    many = [Finding("ruler", f"check {i}", "england", 3, "x") for i in range(ALERTS_PER_TURN + 2)]
    many.append(Finding("bridge", "seat error", "milan", 4, "agy status ERROR"))
    lines = alert_lines(many, "g1")
    assert lines[0].startswith("Audit, turn 4 [bridge] seat error (milan)")
    assert len(lines) == ALERTS_PER_TURN + 1 and lines[-1].endswith("more new problems: just audit g1")


def test_since_limits_the_turns_and_keeps_the_repeat_check(tmp_path):
    for t in (1, 2, 3):
        _turn(tmp_path, t, "england", state=_state(), orders=[{"type": "move_army", "army": "A"}],
              results=[{"index": 0, "type": "move_army", "ok": False, "reason": "(9,9) is sea"}])
    found = audit_game(tmp_path / "g1", since=3)
    assert {f.turn for f in found} == {3} and any(f.check == "same refusal again" for f in found)


def test_ruler_notes_tell_a_ruler_only_its_own_turn_as_facts(tmp_path):
    _turn(tmp_path, 1, "england", state=_state(treasury=10, income=-50), orders=[])
    _turn(tmp_path, 1, "france", state=_state(treasury=10, income=-50), orders=[])
    found = audit_game(tmp_path / "g1")
    notes = ruler_notes(found, "england", 1)
    assert any("Your money is running out" in n for n in notes)
    assert any("The disband order releases units" in n for n in notes)
    assert ruler_notes(found, "england", 2) == [] and len(ruler_notes(found, "france", 1)) == 2
    assert not any("bridge" in n for n in notes)
