"""games/qa/siege.toml's control lines, run by the QA runner through the bridge's control file
against the fake game (LuaJIT via lupa), plus the siege suite's M.qa helpers on their own. Not a
live pass: the fake game behaves here as the suite guesses the real one does (siege equipment
queued on a kept siege, a Catapult may storm at once, a fleet spawns from an admiral, a sally ends
the siege), and is only as true as those guesses."""

import tomllib
from pathlib import Path

import pytest
from lupa.luajit21 import LuaRuntime

from parley.qa.cases import Suite
from parley.qa.runner import _run_instant_case
from tests.test_qa_instant_lua import ROBIN_IN_VENICE, TickingControl

ROOT = Path(__file__).parent.parent
TURN = 3

# the units the suite spawns, and the game as the suite expects it to behave:
#   - a Peasants army can't storm walls yet (canStartAssault false); a Catapult can
#   - siegeSettlement(town, false) on a siege kept queues equipment; an assault the game allows is a
#     battle the attacker loses here (its army is gone)
#   - a rebel siege shows on the town (siegesNum, getSiege(0) with its turns, the holdout)
#   - an admiral spawned at sea is a fleet
#   - the garrison's attack on the besieger ends the siege
GAME = """
FAKE.edu[30] = { index = 30, eduType = 'Peasants' }
FAKE.edu[31] = { index = 31, eduType = 'NE Catapult' }
FAKE.edu[32] = { index = 32, eduType = 'cog' }
local function has_catapult(st)  -- spawned with one, or one merged in (as live)
    return st.catapult == true
end
local function sieging(fac, st, unit)
    local siege = st.siegeSettlement
    st.canStartAssault = function(me) return unit == 'NE Catapult' or has_catapult(me or st) end
    st.siegeSettlement = function(me, s, assault)
        local kept = me.siege ~= nil
        siege(me, s, assault)
        if kept and not assault then me.siege.equipmentQueueCount = 2 end
        if me.siege then
            s.siegesNum = 1
            s.siegeHoldoutTurns = 7
            s.getSiege = function() return { besieger = me, siegeTurns = 0 } end
        end
        if assault and (unit == 'NE Catapult' or has_catapult(me)) then
            -- the army and its general die in the battle
            for i, x in ipairs(fac.stacks) do if x == me then table.remove(fac.stacks, i) end end
            for i = #fac.characters, 1, -1 do
                if fac.characters[i].armyLeaded == me then table.remove(fac.characters, i) end
            end
            fac.stacksNum, fac.numOfCharacters = #fac.stacks, #fac.characters
            s.siegesNum = 0
        end
    end
end
for _, name in ipairs({ 'venice', 'slave' }) do
    local fac = FAKE.byName[name]
    local spawn = fac.spawnArmy
    fac.spawnArmy = function(self, gname, n2, ctype, label, portrait, x, y, ...)
        local unit = FAKE.edu[select(4, ...)].eduType
        if ctype == 3 then
            FAKE.calls[#FAKE.calls + 1] = 'spawn fleet ' .. x .. ' ' .. y .. ' ' .. unit
            return FAKE.add_fleet(self, FAKE.random_name or 'Admiral', x, y)
        end
        local st = spawn(self, gname, n2, ctype, label, portrait, x, y, ...)
        sieging(self, st, unit)
        -- the fake's units are all bodyguards: the catapult rides on the stack, and a merge hands it on
        st.catapult = unit == 'NE Catapult'
        local merge = st.mergeArmies
        st.mergeArmies = function(me, target, force)
            local r = merge(me, target, force)
            if me.catapult then target.catapult = true end
            return r
        end
        -- the stack's leader and the character are one man: a field walk (WALKS) moves both
        local c = self.characters[#self.characters]
        if st.leader and c.armyLeaded == st then
            st.leader.moveToTile = function(me, tx, ty)
                c:moveToTile(tx, ty)
                me.xCoord, me.yCoord = c.xCoord, c.yCoord
            end
        end
        return st
    end
end
for _, st in ipairs(FAKE.byName.venice.stacks) do
    if st.findInSettlement() == FAKE.settlements.Venice then
        local attack = st.attackArmy
        st.attackArmy = function(me, def)
            local r = attack(me, def)
            FAKE.settlements.Venice.siegesNum = 0
            return r
        end
    end
end
"""

# an island town across the sea from Venice (the fake's sea: x >= 115 and y >= 90)
ISLAND = """
local getTile = FAKE.stratMap.getTile
FAKE.stratMap.getTile = function(x, y)
    local t = getTile(x, y)
    if x == 150 and y == 120 then t.isLand = 1 end
    return t
end
local corfu = { name = 'Corfu', localizedName = 'Corfu', ownerFaction = FAKE.byName.milan, xCoord = 150,
                yCoord = 120, regionID = 14, army = { numOfUnits = 1 } }
FAKE.settlements.Corfu = corfu
FAKE.regionSettlements[14] = corfu
FAKE.stratMap.regionsNum = 15
"""


@pytest.fixture
def game(tmp_path):
    rt = LuaRuntime(unpack_returned_tuples=True)
    rt.execute(f"package.path = '{ROOT}/lua/?.lua;{ROOT}/lua/vendor/?.lua;{ROOT}/tests/lua/?.lua;' .. package.path")
    rt.execute("FAKE = require('fake_game'); FAKE.reset()")
    root = tmp_path / "parley_turns"
    for turn in (TURN - 1, TURN):
        (root / "g1" / f"turn-{turn:04d}" / "venice").mkdir(parents=True)
    (root / "bridge.txt").write_text("game_id=g1\nfaction=venice\nautoplay=1\nautoplay_wait=60\n")
    rt.execute(f"BRIDGE = require('parley_bridge'); BRIDGE.setup('{root}'); "
               "BRIDGE.clock = function() return FAKE.now end")
    rt.execute(ROBIN_IN_VENICE)
    rt.execute(GAME)
    rt.execute(ISLAND)
    rt.execute("FAKE.ui.end_turn = { elementName = 'end_turn', "
               "execute = function() FAKE.calls[#FAKE.calls + 1] = 'press end_turn' end }")
    (root / "g1" / f"turn-{TURN:04d}" / "venice" / "state.json").write_text(
        '{"turn": 3, "faction": "venice", "settlements": [{"id": "Venice", "x": 120, "y": 88}], '
        '"armies": [{"id": "garrison:Venice", "in_settlement": "Venice", "leader": "Captain Robin"}]}'
    )
    return rt, root


def _suite_for_venice() -> Suite:
    text = (ROOT / "games" / "qa" / "siege.toml").read_text(encoding="utf-8")
    assert text.count('"england"') >= 10
    return Suite.model_validate(tomllib.loads(text.replace('"england"', '"venice"')))


def test_the_siege_suite_is_all_instant_and_names_its_unforceables():
    suite = _suite_for_venice()
    assert suite.instant
    names = [c.name for c in suite.cases]
    assert names[-1] == "sally_breaks_siege"  # the only case that lifts our town's siege
    assert names.index("siege_equipment_kept") < names.index("besiege_assault_storms")
    text = (ROOT / "games" / "qa" / "siege.toml").read_text(encoding="utf-8")
    assert "What can't be forced" in text and "FIRST LIVE PROOF" in text


def test_the_siege_suite_runs_on_the_fake_game_in_one_held_turn(game):
    rt, root = game
    ctrl = TickingControl(rt, root)
    results = {}
    for i, case in enumerate(_suite_for_venice().cases):
        rt.execute(f"FAKE.random_name = 'Spawned{i}'")
        res, _ = _run_instant_case(case, "qa-siege", "g1", "venice", root, ctrl, TURN,
                                   poll_interval=0.0, turn_wait=1.0)
        results[case.name] = res
        assert not (root / "paused.txt").exists()

    for name, res in results.items():
        assert res.outcome == "pass", (name, res.evidence, ctrl.lines[-12:])
    calls = list(rt.eval("FAKE.calls").values())
    assert "press end_turn" not in calls
    assert "siege Spawned0 Innsbruck false" in calls  # the besiege order reached the game
    assert any(c.startswith("spawn fleet ") and c.endswith(" cog") for c in calls)
    assert "attack ? Spawned6" in calls  # the sally: the garrison on the rebels spawned in case 7
    log = (root / "parley_bridge.log").read_text()
    assert "venice: Spawned2 keeps the siege of Innsbruck; siege equipment queued" in log
    # nobody walked out of besieged Venice
    besieged_at = next(i for i, c in enumerate(calls) if c.startswith("spawnArmy slave"))
    assert not any(c.startswith(("splitArmy", "moveToTile Captain Robin")) for c in calls[besieged_at:]), calls


@pytest.fixture
def lua(game):
    rt, root = game

    def run(line: str):
        return rt.eval(f"(function() {line} end)()")

    rt.execute("M = BRIDGE")
    return run


def test_order_runs_the_real_handler_and_last_keeps_its_answer(lua):
    assert lua('return M.qa.last("besiege")') == "none"
    res = lua('return M.qa.order("venice", { type = "besiege", army = "garrison:Venice", settlement = "Venice" })')
    assert res == "besiege refused: cannot besiege own settlement"
    assert lua('return M.qa.last("besiege")') == res
    assert lua("return M.qa.last()") == res
    assert lua('return M.qa.order("venice", { type = "fly" })') == "fly refused: unknown order type 'fly'"
    assert lua('return M.qa.last("besiege")') == res  # by type


def test_order_without_a_type_fails_the_helper(lua, game):
    _, root = game
    assert lua('return M.qa.order("venice", { army = "x" })') is None
    assert "qa: order failed: " in (root / "parley_bridge.log").read_text()


def test_road_town_finds_the_nearest_own_town_by_land_or_none(lua):
    assert lua('return M.qa.road_town("venice", "Venice")') == "Ragusa"
    # Ragusa full: no room for Venice's garrison
    lua("FAKE.settlements.Ragusa.army.numOfUnits = 19")
    assert lua('return M.qa.road_town("venice", "Venice")') == "none"


def test_coast_finds_a_free_sea_tile_or_none(lua):
    tile = lua('return M.qa.coast("Venice", 1, 6)')
    x, y = (int(v) for v in tile.split(","))
    assert x >= 115 and y >= 90  # the fake's sea
    assert lua('return M.qa.coast("Milan", 1, 3)') == "none"  # Milan (100,90) is inland


def test_besieged_spawns_one_rebel_siege_and_reuses_it(lua):
    first = lua('return M.qa.besieged("Venice")')
    assert lua('return M.qa.sieges("Venice")') == 1
    assert lua('return M.qa.besieged("Venice")') == first  # no second besieger
    spawns = [c for c in lua("return FAKE.calls").values() if c.startswith("spawnArmy slave")]
    assert len(spawns) == 1 and spawns[0].endswith(" 30")  # Peasants


def test_town_siege_reads_the_reports_siege_view(lua):
    assert lua('return M.qa.town_siege("Venice")') == "none"
    lua('M.qa.besieged("Venice")')
    assert lua('return M.qa.town_siege("Venice")') == "by=Edwin faction=slave turns=0 holdout=7 units=1"


def test_siege_says_gone_for_an_army_that_isnt_there(lua):
    assert lua('return M.qa.siege("venice", "Nobody")') == "gone"
    assert lua('return M.qa.siege("venice", "Doge Enrico")').startswith("besieging=- ")


def test_spawn_fleet_refuses_land(lua):
    assert lua('return M.qa.spawn_fleet("venice", 100, 80)') is None
