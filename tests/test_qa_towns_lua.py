"""games/qa/towns.toml: its instant cases run by the QA runner through the bridge's control file
against the fake game (LuaJIT via lupa), its turn case's setup lines and expects checked on their
own, the towns helpers (M.qa) on their own, and the steward switch the suite turns on. Not a live
pass: the fake game behaves as the suite guesses the real one does (queueing a building charges at
once, a damaged building is offered for repair, pool and men writes stick, unit:kill disbands), and
is only as true as those guesses."""

import re
import tomllib
from pathlib import Path

import pytest
from lupa.luajit21 import LuaRuntime

from parley.config import load_config
from parley.qa.cases import Suite
from parley.qa.checker import check
from parley.qa.runner import _required_placeholders, _run_instant_case, _substitute_str, write_qa_config
from tests.test_qa_instant_lua import ROBIN_IN_VENICE, TickingControl

ROOT = Path(__file__).parent.parent
TURN = 3

# the game as the suite expects it: buildings are objects whose hp sticks (the walls are the core
# chain), the construction options are two builds plus a repair for each damaged building, queueing
# one charges its cost and fills a queue slot, garrison units can be disbanded (unit:kill) and made
# (createUnitByIDX adds a full unit)
GAME = """
local U = FAKE.unit
FAKE.settlements.Venice.buildings = { 'wooden_pallisade', 'market', 'small_church' }
for _, s in pairs(FAKE.settlements) do
    local objs = {}
    for i, b in ipairs(s.buildings) do
        local name = type(b) == 'table' and b.name or b
        local chain = name == 'wooden_pallisade' and 'core_building' or name
        objs[i] = { hp = 100, getName = function() return name end, getType = function() return chain end }
    end
    s.buildings, s.buildingsNum = objs, #objs
    s.getBuilding = function(self, i) return self.buildings[i + 1] end
    s.buildingsQueue.numBuildingsInQueue = s.name == 'Venice' and 1 or 0
    s.getConstructionOptions = function(self)
        local opts = { { 'farms', 800, 2, 1 }, { 'town_watch', 400, 1, 1 } }
        for _, b in ipairs(self.buildings) do
            if b.hp < 100 then opts[#opts + 1] = { b.getName(), 300, 1, 2 } end
        end
        local me = self
        return { buildingNum = #opts, getConstructionOption = function(_, i)
            local o = opts[i + 1]
            return { buildCost = o[2], buildTurnsRemaining = o[3], constructionType = o[4],
                     getQueueBuildingName = function() return o[1] end,
                     addBuildingToQueue = function()
                         FAKE.calls[#FAKE.calls + 1] = (o[4] == 2 and 'repair ' or 'build ') .. me.name .. ' ' .. o[1]
                         -- as live: a build is paid at once into an empty queue, on starting behind
                         -- others (10-31 19:3x); a repair at once with at most one item ahead of it,
                         -- not behind two (11-04: queue 1 paid, queue 2 not)
                         local ahead = me.buildingsQueue.numBuildingsInQueue
                         if (o[4] == 2 and ahead <= 1) or ahead == 0 then
                             me.ownerFaction.money = me.ownerFaction.money - o[2]
                         end
                         me.buildingsQueue.numBuildingsInQueue = me.buildingsQueue.numBuildingsInQueue + 1
                         return true
                     end }
        end }
    end
    local function killable(army, u)
        u.kill = function(me)
            for j, x in ipairs(army.units) do if x == me then table.remove(army.units, j) end end
            army.numOfUnits = #army.units
            FAKE.calls[#FAKE.calls + 1] = 'kill ' .. me.eduEntry.eduType
        end
        return u
    end
    for _, u in ipairs(s.army.units) do killable(s.army, u) end
    -- a garrison stack knows its town, as EOP's armyStruct:findInSettlement does
    s.army.findInSettlement = s.army.findInSettlement or function() return s end
    s.army.createUnitByIDX = function(self, idx)
        local u = killable(self, U{ eduEntry = FAKE.edu[idx], soldierCountStratMap = 60, soldierCountStratMapMax = 60, exp = 0 })
        self.units[#self.units + 1] = u
        self.numOfUnits = #self.units
        FAKE.calls[#FAKE.calls + 1] = 'create ' .. s.name .. ' ' .. FAKE.edu[idx].eduType
        return u
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
    # the QA seat's control is "full": every area, build, recruit and taxes among them
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


def _suite_text() -> str:
    return (ROOT / "games" / "qa" / "towns.toml").read_text(encoding="utf-8")


def _suite_for_venice() -> Suite:
    text = _suite_text()
    assert text.count('"england"') >= 20
    return Suite.model_validate(tomllib.loads(text.replace('"england"', '"venice"')))


def test_the_towns_suite_is_instant_but_one_turn_case_last_and_seats_the_steward():
    suite = Suite.model_validate(tomllib.loads(_suite_text()))
    assert (suite.name, suite.faction, suite.steward) == ("towns", "england", True)
    kinds = [c.kind for c in suite.cases]
    assert kinds[:-1] == ["instant"] * (len(kinds) - 1) and kinds[-1] == "turn"
    names = [c.name for c in suite.cases]
    assert names.index("repair_not_damaged_refused") < names.index("repair_queued")
    for level in ("low", "normal", "high", "extortionate"):
        assert f"set_tax_{level}" in names
    # every case names only what setup binds, or the garrison town the runner finds
    live = {"garrison_town", "garrison_town_x", "garrison_town_y"}
    for case in suite.cases:
        assert _required_placeholders(case) - case.binds <= live, case.name
    assert "What can't be forced" in _suite_text() and "Unproven live" in _suite_text()


def test_the_steward_is_seated_only_for_a_suite_that_asks(tmp_path):
    real = tmp_path / "real.toml"
    real.write_text('game_id = "real"\nturn_root = "/tmp/t"\nsave_dir = "/tmp/s"\n'
                    '[seats.england]\nbrain = "fake"\npersona = "p"\n', encoding="utf-8")
    towns = Suite.model_validate(tomllib.loads(_suite_text()))
    plain = towns.model_copy(update={"steward": False, "name": "plain"})
    cfg = load_config(write_qa_config(real, towns, tmp_path / "plan.json", tmp_path / "qa-towns.toml"))
    assert cfg.seats["england"].steward and "recruit" in cfg.seats["england"].areas
    cfg = load_config(write_qa_config(real, plain, tmp_path / "plan.json", tmp_path / "qa-plain.toml"))
    assert not cfg.seats["england"].steward


def test_the_towns_suite_runs_on_the_fake_game_in_one_held_turn(game):
    rt, root = game
    ctrl = TickingControl(rt, root)
    results = {}
    for case in _suite_for_venice().cases:
        if case.kind != "instant":
            continue
        res, _ = _run_instant_case(case, "qa-towns", "g1", "venice", root, ctrl, TURN,
                                   poll_interval=0.0, turn_wait=1.0)
        results[case.name] = res
        assert not (root / "paused.txt").exists()

    for name, res in results.items():
        assert res.outcome == "pass", (name, res.evidence, ctrl.lines[-12:])
    calls = list(rt.eval("FAKE.calls").values())
    assert "press end_turn" not in calls
    assert "build Venice town_watch" in calls  # the build order reached the game
    assert "repair Venice market" in calls
    assert "create Venice Spear Militia" in calls  # retrain_queued's worn unit
    # the refusals queued nothing: one build and one repair in all
    assert sum(c.startswith(("build ", "repair ")) for c in calls) == 2
    assert rt.eval("FAKE.byName.venice.money") > 0  # the "no money" cases put the treasury back


@pytest.fixture
def lua(game):
    rt, root = game

    def run(line: str):
        return rt.eval(f"(function() {line} end)()")

    rt.execute("M = BRIDGE")
    return run


def test_money_sets_and_reads_back(lua):
    start = lua('return M.qa.money("venice")')
    assert lua('return M.qa.money("venice", 0)') == 0
    assert lua(f'return M.qa.money("venice", {start})') == start


def test_can_build_and_buildable_read_the_reports_list(lua):
    assert lua('return M.qa.can_build("Venice")') == "farms:800:2,town_watch:400:1"
    assert lua('return M.qa.buildable("Venice")') == "town_watch"  # the quickest
    assert lua('return M.qa.buildable("Venice", 0)') is None  # nothing that quick: the helper fails
    assert lua('return M.qa.cost("Venice", "farms")') == 800
    assert lua('return M.qa.cost("Venice", "market", "repair")') is None  # not damaged: no repair option


def test_damage_skips_the_walls_offers_a_repair_and_mends(lua):
    assert lua('return M.qa.repairable("Venice")') == "none"
    assert lua('return M.qa.damage("Venice")') == "market"
    assert lua('return M.qa.repairable("Venice")') == "market"
    assert lua('return M.qa.cost("Venice", "market", "repair")') == 300
    assert lua('return M.qa.damage("Venice", "market", 100)') == "market"
    assert lua('return M.qa.repairable("Venice")') == "none"


def test_recruitable_stocks_the_cheapest_land_pool(lua):
    assert lua('return M.qa.pool("Venice", "Spear Militia")') == 1.5
    assert lua('return M.qa.recruitable("Venice")') == "Spear Militia"
    assert lua('return M.qa.pool("Venice", "Spear Militia")') == 2
    assert lua('return M.qa.cost("Venice", "Spear Militia", "recruit")') == 350


def test_fill_queue_fills_to_nine_and_clears_only_its_own(lua):
    assert lua('return M.qa.order("venice", { type = "recruit", settlement = "Venice", unit = "Spear Militia" })') == "recruit ok"
    assert lua('return M.qa.training("Venice")') == 1
    assert lua('return M.qa.ready("Venice", "Spear Militia")') == TURN + 1
    assert lua('return M.qa.fill_queue("venice", "Venice")') == 9
    assert lua('return M.qa.fill_queue("venice", "Venice", true)') == 1


def test_worn_makes_the_most_worn_unit_and_men_reads_it(lua):
    assert lua('return M.qa.men("Venice", "Spear Militia")') == "none"
    assert lua('return M.qa.worn("venice", "Venice")') == "Spear Militia"
    assert lua('return M.qa.men("Venice", "Spear Militia")') == "6/60"
    assert lua('return M.qa.worn("venice", "Milan")') is None  # not Venice's


def test_tax_and_governor_flags(lua):
    assert lua('return M.qa.tax("Venice")') == "normal"
    assert lua('return M.qa.tax("Venice", "extortionate")') == "extortionate"
    assert lua('return M.qa.tax("Venice", "none")') is None
    assert lua('return M.qa.automanage("Venice", true)') == "build=true recruit=true all=true"
    assert lua('return M.qa.governors("venice", "Venice")') == "build=false recruit=false all=false"
    assert lua('return M.qa.governors("venice", "Venice", "diplomacy,armies")') == "build=true recruit=true all=true"


def test_empty_garrison_spares_the_town_with_a_general(lua):
    # Venice has Captain Robin: Ragusa is emptied
    assert lua('return M.qa.empty_garrison("venice", nil)') == "Ragusa"
    assert lua("return FAKE.settlements.Ragusa.army.numOfUnits") == 0
    assert lua("return FAKE.settlements.Venice.army.numOfUnits") > 0
    assert lua('return M.qa.idle_town("venice", "Venice")') == "Ragusa"


def test_the_turn_case_setup_runs_on_the_fake_game(lua, game):
    _, root = game
    case = next(c for c in _suite_for_venice().cases if c.name == "next_turn_delivers")
    targets: dict = {"garrison_town": "Venice", "garrison_town_x": 120, "garrison_town_y": 88}
    for step in case.setup:
        code = step if isinstance(step, str) else step.lua
        res = lua(_substitute_str(code, targets))
        assert res is not None, code
        if not isinstance(step, str) and step.bind:
            targets[step.bind] = res
    assert (targets["u"], targets["w"], targets["idle"], targets["b"], targets["empty"]) == (
        "Spear Militia", "Spear Militia", "Ragusa", "town_watch", "Ragusa")
    log = (root / "parley_bridge.log").read_text()
    for line in ("qa: order ok: recruit ok", "qa: order ok: retrain ok", "qa: order ok: build ok",
                 "qa: order ok: set_tax ok"):
        assert line in log


def test_the_turn_case_passes_on_the_next_turns_log_and_report_and_names_what_is_missing():
    case = next(c for c in Suite.model_validate(tomllib.loads(_suite_text())).cases if c.name == "next_turn_delivers")
    case = case.model_copy(update={"targets": {"garrison_town": "London", "u": "Peasants", "w": "Peasants",
                                               "idle": "York", "b": "town_watch", "empty": "Nottingham"}})
    log = ("qa: order ok: recruit ok\nqa: order ok: retrain ok\nqa: order ok: build ok\n"
           "england: Peasants trained in London\nengland: Peasants retrained in London\n"
           "england order 0 recruit: done\nengland recruits Peasants in Nottingham for 110; ready turn 5\n")
    state = {"settlements": [
        {"id": "London", "tax_level": "low", "order_parts": {"low tax": 10}, "buildings": ["market"]},
        {"id": "York", "buildings": ["wooden_pallisade", "town_watch"]}]}
    assert check(case, log, state, [], turns_used=1).outcome == "pass"
    # a failed delivery, or a building still to come, isn't a pass
    bad = log.replace("Peasants trained in London", "Peasants trained in London FAILED: the settlement was lost")
    assert check(case, bad, state, [], turns_used=3).outcome == "fail"
    state["settlements"][1]["buildings"] = ["wooden_pallisade", "town_watch_2"]
    verdict = check(case, log, state, [], turns_used=1)
    assert verdict.outcome == "pending" and re.search("buildings", verdict.evidence)
