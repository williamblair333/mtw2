import re
from pathlib import Path

from parley.qa.cases import Case, Expect, Suite, load_suite
from parley.qa.checker import Verdict, check
from parley.qa.control import Control

SUITES_DIR = Path(__file__).resolve().parents[1] / "games" / "qa"


def test_order_ok_alone_never_passes():
    only_order_ok = Case(
        name="only_order_ok",
        expect=[Expect(order_ok=True)],
        max_turns=3,
    )
    results = [{"index": 0, "type": "spy", "ok": True, "reason": ""}]

    v1 = check(only_order_ok, log_text="", state={}, results=results, turns_used=1)
    assert isinstance(v1, Verdict)
    assert v1.outcome == "fail"

    v3 = check(only_order_ok, log_text="", state={}, results=results, turns_used=3)
    assert v3.outcome == "fail"

    with_unmet_log = Case(
        name="needs_log_too",
        expect=[Expect(order_ok=True), Expect(log="closed the spy report")],
        max_turns=3,
    )
    assert check(with_unmet_log, "", {}, results, turns_used=1).outcome == "pending"
    assert check(with_unmet_log, "", {}, results, turns_used=3).outcome == "fail"


def test_log_expect_only_reads_after_offset(tmp_path: Path):
    log_file = tmp_path / "parley_bridge.log"
    stale_line = (
        "2026-10-30 14:00:00 popup enemy_settlement_info_scroll: "
        "closed the spy report after england's mission\n"
    )
    log_file.write_text(stale_line, encoding="utf-8")

    ctrl = Control(tmp_path)
    offset = ctrl.log_offset()

    with log_file.open("a", encoding="utf-8") as f:
        f.write("2026-10-30 14:01:00 qa: spawn_agent ok: QA Spy\n")

    case = Case(
        name="spy_report",
        expect=[
            Expect(
                log="popup enemy_settlement_info_scroll: closed the spy report after england's mission"
            )
        ],
        max_turns=2,
    )

    log_since_offset = log_file.read_bytes()[offset:].decode("utf-8")
    verdict = check(case, log_since_offset, state=None, results=[], turns_used=2)
    assert verdict.outcome == "fail"

    with log_file.open("a", encoding="utf-8") as f:
        f.write(stale_line)

    log_since_offset = log_file.read_bytes()[offset:].decode("utf-8")
    verdict_after = check(case, log_since_offset, state=None, results=[], turns_used=2)
    assert verdict_after.outcome == "pass"
    assert "closed the spy report after england's mission" in verdict_after.evidence


def test_state_expect_by_name_selector():
    case = Case(
        name="spawn_agent",
        targets={"x": 115, "y": 81},
        expect=[
            Expect(state="agents[name=QA Spy].x", equals=115),
            Expect(state="agents[name=QA Spy].y", equals=81),
        ],
        max_turns=3,
    )

    wrong_state = {
        "agents": [
            {"id": "Marco", "kind": "spy", "x": 100, "y": 100},
            {"id": "QA Spy", "kind": "spy", "x": 110, "y": 81},
        ]
    }
    assert check(case, "", wrong_state, [], turns_used=1).outcome == "pending"
    assert check(case, "", wrong_state, [], turns_used=3).outcome == "fail"

    matching_state = {
        "agents": [
            {"id": "Marco", "kind": "spy", "x": 100, "y": 100},
            {"id": "QA Spy", "kind": "spy", "x": 115, "y": 81},
        ]
    }
    v = check(case, "", matching_state, [], turns_used=1)
    assert v.outcome == "pass"
    assert "115" in v.evidence and "81" in v.evidence

    named_state = {
        "agents": [
            {"name": "QA Spy", "kind": "spy", "x": 115, "y": 81},
        ]
    }
    assert check(case, "", named_state, [], turns_used=1).outcome == "pass"


def test_no_success_within_cap_is_inconclusive():
    case = Case(
        name="spy_report_closed",
        chance=True,
        max_turns=4,
        expect=[
            Expect(order_ok=True),
            Expect(
                log="popup enemy_settlement_info_scroll: closed the spy report after england's mission"
            ),
        ],
    )
    results = [{"index": 0, "type": "spy", "ok": True, "reason": ""}]
    unlucky_log = (
        "agent mission: england: QA Spy's spying: not successful (chance was 95%)\n"
    )

    for turn in (1, 2, 3):
        v = check(case, unlucky_log, state={}, results=results, turns_used=turn)
        assert v.outcome == "pending"

    v_cap = check(case, unlucky_log, state={}, results=results, turns_used=4)
    assert v_cap.outcome == "inconclusive"

    deterministic = case.model_copy(update={"chance": False})
    assert check(deterministic, unlucky_log, state={}, results=results, turns_used=4).outcome == "fail"


def test_field_suite_loads_and_every_placeholder_is_filled():
    from parley.qa.runner import _required_placeholders, pick_targets

    field = load_suite(SUITES_DIR / "field.toml")
    assert (field.name, field.faction) == ("field", "england")
    by_name = {c.name: c for c in field.cases}
    assert {"spawn_army", "move_army", "march_on_besieges", "march_on_across_sea_refused",
            "move_army_across_sea_refused", "no_moves_left_refused", "withdraw", "merge_armies",
            "garrison_general_leaves", "turn_start_orders"} == set(by_name)
    state = {
        "settlements": [{"id": "London", "x": 112, "y": 149, "garrison_units": 3}],
        "factions": [{"id": "france", "stance": "war"}],
        "nearby_settlements": [{"id": "York", "faction": "slave", "x": 106, "y": 164, "distance": 3}],
    }
    live = set(pick_targets(state))
    for c in field.cases:
        assert any(e.independent for e in c.expect), c.name
        assert not (_required_placeholders(c) - c.binds - live), c.name
        if c.orders:  # every order names the army setup spawned, never a fixed one
            assert all("$" in str(o) for orders in c.orders.values() for o in orders), c.name

    # across the sea (#263): refused with the reason, and the general still where he was spawned
    import re

    from parley.qa.runner import _substitute_str

    for name, otype in (("march_on_across_sea_refused", "march_on"), ("move_army_across_sea_refused", "move_army")):
        c = by_name[name]
        targets = {"at": "110,147", "at_x": 110, "at_y": 147, "far_x": 100, "far_y": 141, "gen": "Edwin"}
        refusal = next(e for e in c.expect if e.lua == f'return M.qa.last("{otype}")')
        to = "(100,141)" if otype == "move_army" else "(100,140)"
        said = f"{otype} refused: {to} can't be reached over land from (110,147): it's across the sea; ..."
        assert re.search(_substitute_str(refusal.match, targets), said), name
        assert not re.search(_substitute_str(refusal.match, targets), f"{otype} ok"), name
        where = next(e for e in c.expect if e.lua == 'return M.qa.where("$gen")')
        assert where.equals == "$at", name


def test_field_cases_need_no_town_in_sight_and_no_unled_town():
    """Live 10-30 19:51: no rebel or at-war town in sight and every own town with a general.
    march_on_besieges and garrison_general_leaves found no target and never ran; they now pick
    theirs in setup (M.qa.hostile_town, M.qa.garrison)."""
    from parley.qa.runner import _required_placeholders, pick_targets

    field = load_suite(SUITES_DIR / "field.toml")
    state = {
        "settlements": [{"id": "London", "x": 109, "y": 147, "garrison_units": 6},
                        {"id": "Nottingham", "x": 107, "y": 155, "garrison_units": 5}],
        "armies": [{"id": "garrison:London", "leader": "Henry", "in_settlement": "London"},
                   {"id": "garrison:Nottingham", "leader": "John", "in_settlement": "Nottingham"}],
        "factions": [{"id": "france", "stance": "peace"}],
        "nearby_settlements": [{"id": "Caen", "faction": "france", "x": 100, "y": 140, "distance": 9}],
    }
    live = set(pick_targets(state))
    by_name = {c.name: c for c in field.cases}
    for name in ("march_on_besieges", "garrison_general_leaves"):
        c = by_name[name]
        assert not (_required_placeholders(c) - c.binds - live), name
    assert any("M.qa.hostile_town(" in s.lua for s in by_name["march_on_besieges"].setup if hasattr(s, "lua"))
    assert any("M.qa.garrison(" in s.lua for s in by_name["garrison_general_leaves"].setup if hasattr(s, "lua"))


def test_march_on_besieges_passes_on_the_siege_scroll_even_when_the_army_is_gone():
    # live (qa-field 10-30 18:31): the siege started (scroll maintained) and the one-unit army was
    # gone by the next report; the case tests the siege, not the army's survival
    # the siege scroll is a popup, handled only in a played turn: turn_start_orders checks it (and
    # only its march_on and siege-scroll expects are taken here; march_on_besieges checks the rest
    # in-turn)
    field = load_suite(SUITES_DIR / "field.toml")
    case = next(c for c in field.cases if c.name == "turn_start_orders")
    keep = [e for e in case.expect if (e.log and "siege_scroll" in e.log)
            or (e.state == "last_results" and "besieg" in str(e.equals))]
    assert len(keep) == 2
    case = case.model_copy(update={"expect": keep, "targets": {
        "army": "Ralph Gryffin", "hostile": "Dublin", "next": "89,161", "next_x": 89, "next_y": 161}})
    note = ("Ralph Gryffin is next to Dublin, slave's settlement: an army can't walk in, so it is "
            "besieging it (a besiege order with \"assault\": true storms it)")
    log = ("2026-10-30 18:31:39 england order 0 march_on: done: " + note + "\n"
           "2026-10-30 18:31:39 popup siege_scroll: (not found)\n"
           "2026-10-30 18:31:40 autoplay: ending turn 40\n"
           "2026-10-30 18:31:46 popup handled: a siege (siege_scroll -> siege_maintain_button)\n")
    ok = [{"index": 0, "type": "march_on", "ok": True, "note": note}]
    gone = {"armies": [], "last_results": ok}
    assert check(case, log, gone, ok, turns_used=2).outcome == "pass"
    # no siege scroll after the order: not proven
    no_scroll = "".join(log.splitlines(keepends=True)[:3])
    assert check(case, no_scroll, gone, ok, turns_used=2).outcome != "pass"
    # a scroll before the order (another army's siege) doesn't count
    before = log.splitlines(keepends=True)[3] + no_scroll
    assert check(case, before, gone, ok, turns_used=2).outcome != "pass"
    # a siege the game hadn't shown when the order ran still passes once its scroll is maintained
    pending = ("Ralph Gryffin is next to Dublin, slave's settlement: an army can't walk in, so it was "
               "ordered to besiege it; the game hasn't shown the siege yet: the next report says whether it holds")
    ok_p = [{"index": 0, "type": "march_on", "ok": True, "note": pending}]
    log_p = log.replace(note, pending)
    assert check(case, log_p, {"armies": [], "last_results": ok_p}, ok_p, turns_used=2).outcome == "pass"


def test_suites_load():
    smoke = load_suite(SUITES_DIR / "smoke.toml")
    assert isinstance(smoke, Suite)
    assert smoke.name == "smoke"
    assert smoke.faction == "england"
    smoke_names = [c.name for c in smoke.cases]
    assert {"spawn_agent", "teleport", "playtest_funds", "skill"} <= set(smoke_names)
    for c in smoke.cases:
        assert any(e.independent for e in c.expect)

    covert = load_suite(SUITES_DIR / "covert.toml")
    assert isinstance(covert, Suite)
    assert covert.name == "covert"
    assert covert.faction == "england"
    covert_by_name = {c.name: c for c in covert.cases}
    assert {"spy_report_closed", "assassinate", "sabotage"} <= set(covert_by_name)

    spy_case = covert_by_name["spy_report_closed"]
    assert spy_case.chance is True
    assert spy_case.max_turns == 3  # one spy order (live 10-30 18:52: repeats were "already inside")
    for c in covert.cases:
        assert any(e.independent for e in c.expect)

    smoke_by_name = {c.name: c for c in smoke.cases}
    spawn_c = smoke_by_name["spawn_agent"]
    # live 10-30: the game named the spawned spy itself; the case finds it by the bound id
    # a bound tile also binds its x and y; live 10-30 19:26 the fixed tile was taken, so the spawn
    # goes on a free tile ($at) and the check compares against that
    assert spawn_c.binds == {"at", "at_x", "at_y", "spy", "spy_x", "spy_y"}
    x, y = 107, 154
    bound = spawn_c.model_copy(update={"targets": {**spawn_c.targets, "spy": "Edwin#2",
                                                   "at": f"{x},{y}", "at_x": x, "at_y": y}})
    assert check(bound, "", {"agents": [{"id": "Edwin#2", "kind": "spy", "x": x, "y": y}]},
                 [], turns_used=1).outcome == "pass"
    assert check(bound, "", {"agents": [{"id": "QA Spy", "kind": "spy", "x": x, "y": y}]},
                 [], turns_used=3).outcome == "fail"
    # only the spawn call itself may mention a "QA ..." name; everything else uses the bound id
    for s in (smoke, covert):
        for c in s.cases:
            later = [st for st in c.setup if isinstance(st, str)]
            later += [str(o) for orders in c.orders.values() for o in orders]
            later += [str(e.state) for e in c.expect]
            assert not any("QA " in t for t in later), (c.name, later)
    tp_c = smoke_by_name["teleport"]
    # the destination is a free tile bound at setup ($to), not a fixed one (11-04: a taken tile crashed it)
    assert {"to", "to_x", "to_y"} <= tp_c.binds
    tp_bound = tp_c.model_copy(update={"targets": {**tp_c.targets, "to": "111,155", "to_x": 111, "to_y": 155}})
    assert check(tp_bound, "qa: teleport ok: 111,155\n", {}, [], turns_used=1).outcome == "pass"
    assert check(tp_bound, "qa: teleport ok: 110,154\n", {}, [], turns_used=tp_c.max_turns).outcome == "fail"
    assert (
        check(
            smoke_by_name["playtest_funds"],
            "playtest funds: england topped up 500 -> 50000\n",
            {},
            [],
            turns_used=1,
        ).outcome
        == "pass"
    )
    assert (
        check(
            smoke_by_name["skill"],
            "qa: skill ok: QA Spy GoodSpy=5\n",
            {},
            [],
            turns_used=1,
        ).outcome
        == "pass"
    )

    assert (
        check(
            spy_case,
            "popup enemy_settlement_info_scroll: closed the spy report after england's mission\n",
            {"agent_results": ["Simon Awood's spying: partly successful"]},
            [{"index": 0, "type": "spy", "ok": True}],
            turns_used=1,
        ).outcome
        == "pass"
    )
    # a mission that failed: no report to close, the outcome in agent_results; a roll, so not a fail
    unlucky = check(spy_case, "", {"agent_results": ["Simon Awood's spying: not successful"]},
                    [{"index": 0, "type": "spy", "ok": True}], turns_used=spy_case.max_turns)
    assert unlucky.outcome == "inconclusive"
    # assassinate and sabotage are turn cases again (live 10-31: no mission line in a held turn); any
    # outcome passes on the mission line and the report's agent_results, so no roll to wait on
    for name, mission in (("assassinate", "assassination"), ("sabotage", "sabotage")):
        c = covert_by_name[name]
        assert c.kind == "turn" and not c.chance and c.max_turns == 2, name
        line = f"agent mission: england: Harry Baker's {mission}: not successful\n"
        logs = [e.log for e in c.expect if e.log]
        assert logs and all(re.search(p, line) for p in logs), name
        bound = c.model_copy(update={"setup": []})
        state = {"agent_results": [f"Harry Baker's {mission}: not successful"]}
        ok = [{"index": 0, "type": c.orders[1][0]["type"], "ok": True}]
        assert check(bound, line, state, ok, turns_used=1).outcome == "pass", name
        assert check(bound, "", {"agent_results": []}, ok, turns_used=c.max_turns).outcome == "fail", name


# --- at_least and any_of (live 10-30 21:56: the treasury stood at 50723, over the 50000 target, so
# the bridge topped nothing up and logged nothing; the playtest_funds case failed on a missing line)


def _treasury_case(at_least="$playtest_funds"):
    return Case(
        name="funds",
        targets={"playtest_funds": 50000},
        expect=[Expect(any_of=[
            Expect(log="playtest funds: england topped up"),
            Expect(state="treasury", at_least=at_least),
        ])],
        max_turns=3,
    )


def test_at_least_compares_numbers():
    case = Case(name="n", expect=[Expect(state="treasury", at_least=50000)])
    assert check(case, "", {"treasury": 50723}, None, turns_used=1).outcome == "pass"
    assert check(case, "", {"treasury": 50000}, None, turns_used=1).outcome == "pass"
    below = check(case, "", {"treasury": 47817}, None, turns_used=3)
    assert below.outcome == "fail" and "47817" in below.evidence and "50000" in below.evidence
    # not a number: never passes
    assert check(case, "", {"treasury": "lots"}, None, turns_used=3).outcome == "fail"
    assert check(case, "", {"treasury": None}, None, turns_used=3).outcome == "fail"
    assert check(case, "", {"treasury": True}, None, turns_used=3).outcome == "fail"
    unfilled = Case(name="u", expect=[Expect(state="treasury", at_least="$nobody")])
    assert check(unfilled, "", {"treasury": 1}, None, turns_used=3).outcome == "fail"


def test_at_least_fills_placeholders():
    case = Case(name="n", targets={"floor": 100}, expect=[Expect(state="treasury", at_least="$floor")])
    assert check(case, "", {"treasury": 100}, None, turns_used=1).outcome == "pass"
    assert check(case, "", {"treasury": 99}, None, turns_used=3).outcome == "fail"


def test_at_least_needs_a_state_path():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Expect(at_least=5)
    with pytest.raises(ValidationError):
        Expect(state="treasury", equals=5, at_least=5)


def test_any_of_passes_on_the_top_up_line_or_a_full_treasury():
    case = _treasury_case()
    topped = check(case, "2026-10-30 22:02:07 playtest funds: england topped up 2608 -> 50000\n",
                   {"treasury": 2608}, None, turns_used=1)
    assert topped.outcome == "pass" and "topped up" in topped.evidence
    full = check(case, "", {"treasury": 50723}, None, turns_used=1)
    assert full.outcome == "pass" and "treasury=50723" in full.evidence
    neither = check(case, "", {"treasury": 47817}, None, turns_used=1)
    assert neither.outcome == "pending"
    failed = check(case, "", {"treasury": 47817}, None, turns_used=3)
    assert failed.outcome == "fail" and "topped up" in failed.evidence and "47817" in failed.evidence
    # before the case's first turn (no report yet): the line alone can pass it
    assert check(case, "", None, [], turns_used=0).outcome == "pending"


def test_any_of_with_an_order_ok_alternative_is_no_independent_evidence():
    results = [{"index": 0, "type": "spy", "ok": True, "reason": ""}]
    case = Case(name="sneaky", expect=[Expect(any_of=[Expect(order_ok=True), Expect(log="never")])])
    v = check(case, "", {}, results, turns_used=1)
    assert v.outcome == "fail" and "order_ok alone" in v.evidence
    assert check(Case(name="empty", expect=[Expect(any_of=[])]), "", {}, results, turns_used=3).outcome == "fail"


def test_smoke_playtest_funds_passes_on_a_full_treasury_without_a_top_up():
    from parley.qa.runner import QA_PLAYTEST_FUNDS, _required_placeholders

    smoke = load_suite(SUITES_DIR / "smoke.toml")
    case = next(c for c in smoke.cases if c.name == "playtest_funds")
    assert "playtest_funds" in _required_placeholders(case)
    bound = case.model_copy(update={"targets": {"playtest_funds": QA_PLAYTEST_FUNDS}})
    assert check(bound, "", {"treasury": QA_PLAYTEST_FUNDS + 723}, [], turns_used=1).outcome == "pass"
    assert check(bound, "playtest funds: england topped up 3876 -> 50000\n", {"treasury": 3876}, [],
                 turns_used=1).outcome == "pass"
    assert check(bound, "", {"treasury": QA_PLAYTEST_FUNDS - 1}, [], turns_used=case.max_turns).outcome == "fail"
