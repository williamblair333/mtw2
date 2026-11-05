"""The prompt's top block for last turn's refused orders, and the history behind "N turns running"."""

import json

from parley.audit import refusal_key, refusals
from parley.prompt import build_prompt
from parley.protocol import OrderResult


def _refused(i, kind, reason, brief=""):
    return OrderResult(index=i, type=kind, ok=False, reason=reason, brief=brief)


def _with(report, results):
    return report.model_copy(update={"last_results": results})


def test_no_refusal_block_when_nothing_was_refused(venice_report):
    p = build_prompt(_with(venice_report, [OrderResult(index=0, type="send_gold", ok=True)]), persona="p")
    assert "REFUSED LAST TURN" not in p
    assert "LAST TURN'S ORDER RESULTS" in p
    assert "REFUSED LAST TURN" not in build_prompt(venice_report, persona="p")


def test_refusal_block_is_above_the_results_and_the_refusal_shows_once(venice_report):
    report = _with(venice_report, [
        OrderResult(index=0, type="send_gold", ok=True),
        _refused(1, "move_agent", "York is Scotland's; act on it from outside",
                 "move_agent agent=Spy, target_settlement=York")])
    p = build_prompt(report, persona="p")
    assert "YOUR ORDERS REFUSED LAST TURN: don't give these again as they were" in p
    assert "- move_agent agent=Spy, target_settlement=York: York is Scotland's; act on it from outside." in p
    assert p.count("act on it from outside") == 1  # not repeated in the results section below
    assert p.index("REFUSED LAST TURN") < p.index("LAST TURN'S ORDER RESULTS")
    results = p.split("LAST TURN'S ORDER RESULTS")[1].split("\n\n")[0]
    assert "send_gold" in results and "move_agent" not in results


def test_all_refused_leaves_no_empty_results_section(venice_report):
    p = build_prompt(_with(venice_report, [_refused(0, "disband", "no such army")]), persona="p")
    assert "REFUSED LAST TURN" in p and "LAST TURN'S ORDER RESULTS" not in p


def test_repeats_are_counted_and_numbers_dont_matter(venice_report):
    report = _with(venice_report, [_refused(0, "move_agent", "can't enter York (12, 40)")])
    key = refusal_key("move_agent", "can't enter York (99, 7)")
    history = [{key}, {key}, set(), {key}]  # newest first: the run stops at the gap
    assert "Refused 3 turns running." in build_prompt(report, persona="p", refusal_history=history)
    assert "turns running" not in build_prompt(report, persona="p", refusal_history=[set()])
    assert "turns running" not in build_prompt(report, persona="p")


def test_block_is_capped_and_most_repeated_first(venice_report):
    report = _with(venice_report, [_refused(i, f"kind{i}", f"reason {i}") for i in range(10)])
    k7, k3 = refusal_key("kind7", "reason 7"), refusal_key("kind3", "reason 3")
    p = build_prompt(report, persona="p", refusal_history=[{k7, k3}, {k7, k3}, {k7}])
    lines = p.split("YOUR ORDERS REFUSED LAST TURN")[1].split("\n\n")[0].splitlines()[1:]
    assert len(lines) == 9  # eight refusals and an overflow line
    assert lines[0].startswith("- kind7") and "4 turns running" in lines[0]
    assert lines[1].startswith("- kind3") and "3 turns running" in lines[1]
    assert lines[-1] == "- ...and 2 other refusals."


def test_same_refusal_twice_in_a_turn_is_one_line(venice_report):
    p = build_prompt(_with(venice_report, [_refused(0, "disband", "unknown army 'A1'"),
                                           _refused(1, "disband", "unknown army 'A2'")]), persona="p")
    assert p.count("unknown army") == 1 and "(and 1 like it)" in p


def test_orchestrator_reads_history_from_turn_folders_and_stops_at_a_missing_one(tmp_path, venice_report):
    from parley.bridge import TurnDir
    from parley.orchestrator import Orchestrator
    orch = Orchestrator.__new__(Orchestrator)
    orch.turns = TurnDir(tmp_path)
    game = venice_report.game_id
    for turn in (7, 8):  # report.turn is 10: last turn (9) is in the report; 8 and 7 are history
        d = orch.turns.path_for(game, turn, venice_report.faction)
        d.mkdir(parents=True)
        (d / "rejected.json").write_text(json.dumps([{"index": 0, "type": "disband", "ok": False, "reason": "no army 12"}]))
    hist = orch._refusal_history(venice_report.model_copy(update={"turn": 10}))
    assert hist == [{refusal_key("disband", "no army 99")}] * 2


def test_refusals_reads_game_and_checker_refusals_from_a_turn_folder(tmp_path):
    (tmp_path / "orders.json").write_text(json.dumps({"orders": [{"type": "attack"}, {"type": "disband"}]}))
    (tmp_path / "results.json").write_text(json.dumps([
        {"index": 0, "type": "attack", "ok": True}, {"index": 1, "type": "disband", "ok": False, "reason": "x"}]))
    (tmp_path / "rejected.json").write_text(json.dumps([{"index": 2, "type": "send_gold", "ok": False, "reason": "y"}]))
    assert [(o["type"], r["reason"]) for o, r in refusals(tmp_path)] == [("disband", "x"), ("send_gold", "y")]
