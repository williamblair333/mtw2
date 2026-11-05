"""games/qa/covert.toml: its instant cases run by the QA runner through the bridge's control file
against the fake game (as tests/test_qa_envoys_lua.py does for envoys.toml), the missions' turn cases'
setup and orders on the fake, the turn cases checked for shape, and M.qa.news on its own. The fake
plays the game as the suite guesses the real one does (an assassination or a sabotage is a mission
the game rolls when the agent acts and reports by its own event; an agent walks up to 3 tiles toward
a far target): not a live pass."""

import json
import tomllib
from pathlib import Path

import pytest
from lupa.luajit21 import LuaRuntime

from parley.qa.cases import Suite
from parley.qa.runner import (
    _required_placeholders,
    _run_instant_case,
    _run_steps,
    _substitute_value,
    pick_targets,
)
from tests.test_qa_instant_lua import ROBIN_IN_VENICE, TURN, TickingControl

ROOT = Path(__file__).parent.parent

# every spawn named anew from the faction's list (live 10-30); an assassin's and a spy's missions
# rolled at once and reported by the game's event (onAssassinationMission, onSabotageMission,
# onSpyingMission), with the EOP 3.3.1 success level names (storm = highly successful)
GAME = """
FAKE.spawn_ignores_names = true
local spawned = 0
local function missions(c)
    local fac = c._fac
    for verb, kind in pairs({ assassinate = 'assassination', sabotageSettlement = 'sabotage',
                              spySettlement = 'spying', spyCharacter = 'spying' }) do
        local record = c[verb]
        c[verb] = function(self, target)
            record(self, target)
            BRIDGE.on_agent_mission(kind, { character = self, faction = fac, missionSuccessLevel = 'storm' }, false)
        end
    end
end
for _, f in ipairs(FAKE.factions) do
    local create, army = f.createCharacter, f.spawnArmy
    f.createCharacter = function(...)
        spawned = spawned + 1
        FAKE.random_name = 'Spawn' .. spawned
        local c = create(...)
        missions(c)
        return c
    end
    f.spawnArmy = function(...)
        spawned = spawned + 1
        FAKE.random_name = 'Spawn' .. spawned
        return army(...)
    end
end
"""


@pytest.fixture
def game(tmp_path):
    rt = LuaRuntime(unpack_returned_tuples=True)
    rt.execute(f"package.path = '{ROOT}/lua/?.lua;{ROOT}/lua/vendor/?.lua;{ROOT}/tests/lua/?.lua;' .. package.path")
    rt.execute("FAKE = require('fake_game'); FAKE.reset()")
    root = tmp_path / "parley_turns"
    for turn in (TURN - 1, TURN):
        (root / "g1" / f"turn-{turn:04d}" / "venice").mkdir(parents=True)
    (root / "bridge.txt").write_text("game_id=g1\nfaction=venice\nautoplay=1\nautoplay_wait=60\n"
                                     "control=venice:diplomacy,armies,agents,build,recruit,taxes\n")
    rt.execute(f"BRIDGE = require('parley_bridge'); BRIDGE.setup('{root}'); "
               "BRIDGE.clock = function() return FAKE.now end")
    rt.execute(ROBIN_IN_VENICE)
    rt.execute(GAME)
    rt.execute("FAKE.ui.end_turn = { elementName = 'end_turn', "
               "execute = function() FAKE.calls[#FAKE.calls + 1] = 'press end_turn' end }")
    (root / "g1" / f"turn-{TURN:04d}" / "venice" / "state.json").write_text(
        '{"turn": 3, "faction": "venice", "settlements": [{"id": "Venice", "x": 120, "y": 88}], '
        '"armies": [{"id": "garrison:Venice", "in_settlement": "Venice", "leader": "Captain Robin"}]}'
    )
    return rt, root


def _text() -> str:
    return (ROOT / "games" / "qa" / "covert.toml").read_text(encoding="utf-8")


def _suite() -> Suite:
    """covert.toml as written, with the fake's faction for England (in its log lines too)."""
    return Suite.model_validate(tomllib.loads(_text().replace("england", "venice")))


INSTANT = ["wrong_agent_refused", "spy_far_walks"]
MISSIONS = {"assassinate": "assassination", "sabotage": "sabotage"}


def test_the_covert_suite_is_instant_but_the_missions_and_marks_its_roll():
    suite = Suite.model_validate(tomllib.loads(_text()))
    assert [c.name for c in suite.cases if c.kind == "instant"] == INSTANT
    turn = [c for c in suite.cases if c.kind == "turn"]
    # grouped last; the missions are turn cases (live 10-31: no mission line in a held turn)
    assert [c.name for c in turn] == ["assassinate", "sabotage", "spy_report_closed"]
    assert suite.cases[-3:] == turn
    # #255: the scroll is a popup (no popup is handled in a held turn); the spy's success is a roll
    spy = turn[-1]
    assert spy.chance and spy.max_turns == 3 and list(spy.orders) == [1]
    assert any(e.log and "closed the spy report" in e.log for e in spy.expect)
    assert any(e.state == "agent_results" for e in spy.expect)
    # the assassination and the sabotage pass on any outcome: nothing to retry, no roll to wait on
    for c in turn[:2]:
        assert not c.chance and list(c.orders) == [1] and c.orders[1][0]["type"] == c.name, c.name
        assert any(e.state == "agent_results" for e in c.expect), c.name
    assert not any(c.chance for c in suite.cases if c.kind == "instant")
    live = {"garrison_town", "garrison_town_x", "garrison_town_y"}
    for case in suite.cases:
        assert _required_placeholders(case) - case.binds <= live, case.name
        assert not case.needs, case.name  # the rebel victim stays frozen
    text = _text()
    assert "What can still go red without a bug (chance)" in text and "Unproven live" in text
    for old in ("spy_report_closed", "assassinate", "sabotage"):
        assert f"#   {old} " in text, old


def test_the_covert_suite_s_instant_cases_run_on_the_fake_game_in_one_held_turn(game):
    rt, root = game
    ctrl = TickingControl(rt, root)
    results = {}
    for case in (c for c in _suite().cases if c.kind == "instant"):
        res, _ = _run_instant_case(case, "qa-covert", "g1", "venice", root, ctrl, TURN,
                                   poll_interval=0.0, turn_wait=1.0)
        results[case.name] = res
        assert not (root / "paused.txt").exists()

    assert list(results) == INSTANT
    failed = {name: (res.outcome, res.evidence) for name, res in results.items() if res.outcome != "pass"}
    assert not failed, (failed, ctrl.lines[-12:])
    calls = list(rt.eval("FAKE.calls").values())
    assert "press end_turn" not in calls
    assert not any(c.startswith("spySettlement ") for c in calls)  # the far spy walked instead


def _lua_table(d: dict) -> str:
    return "{ " + ", ".join(f'{k} = {v}' if isinstance(v, int) else f'{k} = "{v}"' for k, v in d.items()) + " }"


def test_the_mission_turn_cases_set_up_and_their_orders_reach_the_game(game):
    # the setup lines the runner runs before the case's turn, then the case's turn-1 order through
    # the bridge's apply() (M.qa.order, as orders.json's at turn start): the mission line comes and is
    # kept for the report's agent_results
    rt, root = game
    ctrl = TickingControl(rt, root)
    state = json.loads((root / "g1" / f"turn-{TURN:04d}" / "venice" / "state.json").read_text())
    for case in (c for c in _suite().cases if c.name in MISSIONS):
        targets, failed, _ = _run_steps(case, case.setup, pick_targets(state), ctrl,
                                        root / "parley_bridge.log", None, poll_interval=0.0)
        assert failed is None, (case.name, failed.evidence if failed else None)
        order = _substitute_value(case.orders[1][0], targets)
        assert rt.eval(f'BRIDGE.qa.order("venice", {_lua_table(order)})') == f"{case.name} ok", case.name
    calls = list(rt.eval("FAKE.calls").values())
    assert any(c.startswith("spawnArmy slave random_name ") for c in calls)  # the rebel victim
    assert any(c.startswith("assassinate ") for c in calls), calls
    assert any(c.startswith("sabotageSettlement ") and c.endswith(" Innsbruck") for c in calls)
    news = rt.eval("BRIDGE.take_agent_news('venice')")
    assert [n.split("'s ")[1] for n in news.values()] == ["assassination: highly successful",
                                                          "sabotage: highly successful"]


@pytest.fixture
def lua(game):
    rt, _ = game

    def run(line: str):
        return rt.eval(f"(function() {line} end)()")

    rt.execute("M = BRIDGE")
    return run


def test_news_reads_the_outcomes_kept_for_the_next_report_without_taking_them(lua):
    assert lua('return M.qa.news("venice")') == ""
    lua("M.on_agent_mission('assassination', { faction = FAKE.byName.venice, character = { fullName = 'Iacopo' }, "
        "missionSuccessLevel = 'earthquake' }, false)")
    assert lua('return M.qa.news("venice")') == "Iacopo's assassination: not successful"
    assert lua('return M.qa.news("venice")') == "Iacopo's assassination: not successful"  # still there
    assert list(lua("return M.take_agent_news('venice')").values()) == ["Iacopo's assassination: not successful"]
    assert lua('return M.qa.news("venice")') == ""
    assert lua('return M.qa.news("nobody")') is None  # an unknown faction fails the helper


def test_a_campaign_load_forgets_the_missions_and_the_last_orders(lua, game):
    # a bench reload between cases, or the restore's load of the real campaign: the bench's mission
    # outcomes must not reach the next report, nor M.qa.last answer with an order from before
    _, root = game
    lua("M.on_agent_mission('sabotage', { faction = FAKE.byName.venice, character = { fullName = 'Iacopo' }, "
        "missionSuccessLevel = 'storm' }, false)")
    lua('return M.qa.order("venice", { type = "set_tax", settlement = "Venice", level = "nope" })')
    assert lua('return M.qa.last("set_tax")') is not None
    lua(f"BRIDGE.setup('{root}')")
    assert lua('return M.qa.news("venice")') == ""
    assert lua('return M.qa.last("set_tax")') in (None, "", "none")
