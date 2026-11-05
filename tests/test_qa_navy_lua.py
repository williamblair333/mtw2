"""games/qa/navy.toml's control lines, run by the QA runner through the bridge's control file against
the fake game (LuaJIT via lupa), plus the navy suite's M.qa helpers and bridge changes on their own.
Not a live pass: the fake game behaves here as the suite guesses the real one does (moving onto an
own fleet's tile boards it, moving from aboard onto land lands, a fleet sails to the tile it is sent
to, blockadePort sets the port's blockadingArmy, a ship's eduEntry.category is 4, spawnArmy with an
admiral makes a fleet), and is only as true as those guesses."""

import tomllib
from pathlib import Path

import pytest
from lupa.luajit21 import LuaRuntime

from parley.qa.cases import Suite
from parley.qa.runner import _run_instant_case
from tests.test_qa_instant_lua import ROBIN_IN_VENICE, TickingControl

ROOT = Path(__file__).parent.parent
TURN = 3

# The fake's sea is x >= 115 and y >= 90. Added here: an island across it (x 128-130, y 96-98) with
# Milan's Corfu on it, a port for Venice (region 10) beside Innsbruck's, and a ship in Venice's pool.
GAME = """
FAKE.edu[32] = { index = 32, eduType = 'cog', category = 4, recruitCost = 500, recruitTime = 1, upkeepCost = 100 }
local getTile = FAKE.stratMap.getTile
FAKE.stratMap.getTile = function(x, y)
    local t = getTile(x, y)
    if x >= 128 and x <= 130 and y >= 96 and y <= 98 then t.isLand = 1 end
    return t
end
local corfu = { name = 'Corfu', localizedName = 'Corfu', ownerFaction = FAKE.byName.milan, xCoord = 129,
                yCoord = 97, regionID = 14, army = { numOfUnits = 1 } }
FAKE.settlements.Corfu = corfu
FAKE.regionSettlements[14] = corfu
FAKE.stratMap.regionsNum = 15
FAKE.ports[10] = { x = 121, y = 90, port = { name = 'Venice port' } }
local venice = FAKE.settlements.Venice
venice.recruitmentPoolCount = 3
venice.pools = { { eduIndex = 7, availablePool = 1.5 }, { eduIndex = 9, availablePool = 0.4 },
                 { eduIndex = 32, availablePool = 0.5 } }

local function land(x, y) return FAKE.stratMap.getTile(x, y).isLand == 1 end
local function fleet_at(fac, x, y)
    for _, f in ipairs(fac.stacks) do
        if f.isAdmiral and f.leader and f.leader.xCoord == x and f.leader.yCoord == y then return f end
    end
end
-- a general c leading stack st: his whole army split onto an own fleet's tile boards it (EOP then
-- gives the stack no leader, shipArmy/boardedArmy link the two); moveToTile onto the fleet does
-- nothing (live bench 10-31 15:18: board_next_fleet "ok", the army stayed ashore); from aboard
-- onto land he lands
local function sailor(fac, st, c)
    st.leader.moveToTile = function(me, tx, ty)
        c:moveToTile(tx, ty)
        me.xCoord, me.yCoord = c.xCoord, c.yCoord
    end
    local split = fac.splitArmy
    fac.splitArmy = function(self, units, tx, ty)
        local fleet = fleet_at(fac, tx, ty)
        local mine = units[1] ~= nil
        for _, u in ipairs(units) do
            local found = false
            for _, su in ipairs(st.units or {}) do if su == u then found = true end end
            mine = mine and found
        end
        if fleet and mine and not st.shipArmy and not fleet.boardedArmy then
            FAKE.calls[#FAKE.calls + 1] = 'splitArmy board ' .. c.namedCharacter.fullName .. ' ' .. tx .. ' ' .. ty
            c.xCoord, c.yCoord = tx, ty
            st.shipArmy, fleet.boardedArmy, st.aboard_leader, st.leader = fleet, st, st.leader, nil
            return
        end
        -- the whole army split from aboard onto land lands it (live 10-31 18:30: moveToTile landed
        -- the general with his bodyguard only and left two of three units aboard)
        if mine and st.shipArmy and land(tx, ty) then
            FAKE.calls[#FAKE.calls + 1] = 'splitArmy land ' .. c.namedCharacter.fullName .. ' ' .. tx .. ' ' .. ty
            st.shipArmy.boardedArmy, st.shipArmy = nil, nil
            st.leader, st.aboard_leader = st.aboard_leader, nil
            c.xCoord, c.yCoord = tx, ty
            st.leader.xCoord, st.leader.yCoord = tx, ty
            return
        end
        return split(self, units, tx, ty)
    end
    -- from aboard, moveToTile takes the general alone: the fake keeps the army aboard (stricter)
    c.moveToTile = function(self, tx, ty)
        FAKE.calls[#FAKE.calls + 1] = 'moveToTile ' .. self.namedCharacter.fullName .. ' ' .. tx .. ' ' .. ty
    end
end
-- a fleet sails straight to a sea tile, the army aboard with it; blockadePort takes the port
local function sails(fac, fleet, c)
    fleet.leader.moveToTile = function(me, tx, ty)
        FAKE.calls[#FAKE.calls + 1] = 'sail ' .. c.namedCharacter.fullName .. ' ' .. tx .. ' ' .. ty
        if land(tx, ty) then return end
        me.xCoord, me.yCoord, c.xCoord, c.yCoord, fleet.xCoord, fleet.yCoord = tx, ty, tx, ty, tx, ty
        local aboard = fleet.boardedArmy
        if aboard then
            for _, g in ipairs(fac.characters) do
                if g.armyLeaded == aboard then g.xCoord, g.yCoord = tx, ty end
            end
            if aboard.aboard_leader then aboard.aboard_leader.xCoord, aboard.aboard_leader.yCoord = tx, ty end
        end
    end
    fleet.blockadePort = function(self, port)
        FAKE.calls[#FAKE.calls + 1] = 'blockade ' .. c.namedCharacter.fullName .. ' ' .. port.name
        port.blockadingArmy = self
        return true
    end
end
local fac = FAKE.byName.venice
local spawn = fac.spawnArmy
local n = 0
fac.spawnArmy = function(self, gname, n2, ctype, label, portrait, x, y, ...)
    n = n + 1
    local unit = FAKE.edu[select(4, ...)].eduType
    if ctype == 3 then
        FAKE.calls[#FAKE.calls + 1] = 'spawn fleet ' .. x .. ' ' .. y .. ' ' .. unit
        local fleet = FAKE.add_fleet(self, 'Admiral' .. n, x, y)
        sails(self, fleet, self.characters[#self.characters])
        return fleet
    end
    FAKE.random_name = 'General' .. n
    local st = spawn(self, gname, n2, ctype, label, portrait, x, y, ...)
    if st.leader then sailor(self, st, self.characters[#self.characters]) end
    return st
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
    # full control, as the QA seat has (write_qa_config): recruit is an area of its own
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


def _navy_text() -> str:
    return (ROOT / "games" / "qa" / "navy.toml").read_text(encoding="utf-8")


def _suite_for_venice() -> Suite:
    return Suite.model_validate(tomllib.loads(_navy_text().replace("england", "venice")))


def test_the_navy_suite_is_instant_but_three_grouped_turn_cases_and_names_its_unforceables():
    suite = _suite_for_venice()
    kinds = [c.kind for c in suite.cases]
    assert kinds.count("turn") == 3
    assert kinds[-3:] == ["turn", "turn", "turn"]  # grouped, last
    # live 10-31: the instant blockade crashed the game in a held turn; never instant again, and the
    # turn case checks the game lived past the order
    blockade = next(c for c in suite.cases if c.name == "blockade_port")
    assert blockade.kind == "turn" and any(e.alive for e in blockade.expect)
    assert suite.cases[0].name == "across_sea_board_first"  # while its fleet is the nearest
    names = {c.name for c in suite.cases}
    assert {"board_next_fleet", "board_far_fleet_walks", "land_on_coast", "land_onto_sea_refused",
            "land_onto_foreign_town_refused", "blockade_port", "fleet_sails", "fleet_onto_land_refused",
            "crossing_in_one_turn", "crossing_over_turns", "report_fleet_carrying", "recruit_ship"} <= names
    text = _navy_text()
    assert "What can't be forced" in text and "Unproven live" in text


def test_the_navy_suites_instant_cases_pass_on_the_fake_game_in_one_held_turn(game):
    rt, root = game
    ctrl = TickingControl(rt, root)
    results = {}
    for case in _suite_for_venice().cases:
        if case.kind != "instant":
            continue
        res, _ = _run_instant_case(case, "qa-navy", "g1", "venice", root, ctrl, TURN,
                                   poll_interval=0.0, turn_wait=1.0)
        results[case.name] = res
        assert not (root / "paused.txt").exists()

    for name, res in results.items():
        assert res.outcome == "pass", (name, res.evidence, ctrl.lines[-12:])
    assert len(results) == 12
    calls = list(rt.eval("FAKE.calls").values())
    assert "press end_turn" not in calls
    assert not any(c.startswith("blockade ") for c in calls)  # no instant case calls blockadePort
    assert any(c.startswith("spawn fleet ") and c.endswith(" cog") for c in calls)
    assert "create Venice cog" not in calls  # the ship went to sea, not into the garrison
    log = (root / "parley_bridge.log").read_text()
    assert "qa: rerun ok: " in log


@pytest.fixture
def lua(game):
    rt, _ = game
    rt.execute("M = BRIDGE")
    return lambda line: rt.eval(f"(function() {line} end)()")


def _aboard(lua) -> tuple[str, str]:
    """An army aboard a fleet on the sea beside Venice's shore: (army id, fleet id)."""
    fleet = lua('return M.qa.spawn_fleet("venice", 118, 90)')
    army = lua('return M.qa.spawn_army("venice", 119, 89)')
    assert lua(f'return M.qa.order("venice", {{ type = "board", who = "{army}", fleet = "{fleet}" }})') == "board ok"
    assert lua(f'return M.qa.army("venice", "{army}")') == f"118,90 fleet=no carrying=- men=- aboard={fleet}"
    return army, fleet


def test_the_report_view_shows_the_fleet_carrying_and_the_army_aboard(lua):
    army, fleet = _aboard(lua)
    assert lua(f'return M.qa.army("venice", "{fleet}")').startswith("118,90 fleet=yes carrying=1 men=")
    assert lua('return M.qa.army("venice", "Nobody")') == "gone"


def test_an_army_aboard_a_fleet_whose_stack_has_no_leader_still_reads_aboard_it(lua):
    # live QA navy 10-31 08:19: every boarded army stood on its fleet's sea tile and read aboard=- for
    # 15 s (five cases): EOP gives a stack in a residence (a fleet is one) no leader, and the view
    # took the admiral from shipArmy.leader alone. Its admiral is found as leader_of finds it
    army, fleet = _aboard(lua)
    lua("for _, f in ipairs(FAKE.byName.venice.stacks) do if f.isAdmiral then f.leader = nil end end")
    assert lua(f'return M.qa.army("venice", "{army}")') == f"118,90 fleet=no carrying=- men=- aboard={fleet}"
    assert lua(f'return M.qa.army("venice", "{fleet}")').startswith("118,90 fleet=yes carrying=1 men=")


def test_an_army_aboard_is_named_by_its_units_general_when_nothing_else_says(lua):
    # live 10-31 18:12 (probe): Humphrey of Painswick boarded Admiral Godwine; the fleet's boardedArmy
    # held his unit, but the army's stack had no leader, no armyLeaded and no position of its own, and
    # the fleet no leader: M.qa.army said "gone" for him and carrying=- for the fleet. getUnit(0).character
    # was him
    army, fleet = _aboard(lua)
    # as live: a leader's own unit (his bodyguard, a fleet's flagship) names him as its character
    lua("for _, c in ipairs(FAKE.byName.venice.characters) do if c.armyLeaded then "
        "c.armyLeaded:getUnit(0).character = c end end")
    lua("for _, f in ipairs(FAKE.byName.venice.stacks) do if f.isAdmiral then f.leader = nil end; "
        "if f.shipArmy then f.xCoord, f.yCoord = nil, nil end end; "
        "for _, c in ipairs(FAKE.byName.venice.characters) do c.armyLeaded = nil end")
    assert lua(f'return M.qa.army("venice", "{army}")') == f"118,90 fleet=no carrying=- men=- aboard={fleet}"
    assert lua(f'return M.qa.army("venice", "{fleet}")').startswith("118,90 fleet=yes carrying=1 men=")


def test_land_onto_a_foreign_town_is_refused_and_nobody_moves(lua):
    army, _ = _aboard(lua)
    res = lua(f'return M.qa.order("venice", {{ type = "land", army = "{army}", x = 115, y = 80 }})')
    assert res.startswith("land refused: (115,80) is Innsbruck, hre's settlement: an army can't walk in; besiege it")
    assert not any(c.startswith("moveToTile General") and c.endswith(" 115 80") for c in lua("return FAKE.calls").values())


def test_land_onto_an_own_coast_tile_goes_ashore(lua):
    army, _ = _aboard(lua)
    assert lua(f'return M.qa.order("venice", {{ type = "land", army = "{army}", x = 119, y = 89 }})') == "land ok"
    assert lua(f'return M.qa.army("venice", "{army}")') == "119,89 fleet=no carrying=- men=- aboard=-"


def test_a_trained_ship_puts_to_sea_as_a_fleet_beside_the_port(lua, game):
    _, root = game
    assert lua('return M.qa.ship_yard("venice")') == "Venice"
    assert lua('return M.qa.ship_unit("Venice")') == "cog"  # its pool (0.5) topped up to one
    before = lua('return M.qa.fleets("venice")')
    assert lua('return M.qa.order("venice", { type = "recruit", settlement = "Venice", unit = "cog" })') == "recruit ok"
    assert lua('return M.qa.deliver("venice", "Venice")') == "delivered=1"
    assert lua('return M.qa.fleets("venice")') == before + 1
    calls = list(lua("return FAKE.calls").values())
    assert "spawn fleet 121 90 cog" in calls  # on the port's own sea tile, the nearest free one
    assert "create Venice cog" not in calls
    assert "venice: cog trained in Venice (a fleet at (121,90))" in (root / "parley_bridge.log").read_text()


def test_a_trained_land_unit_still_joins_the_garrison(lua):
    assert lua('return M.qa.order("venice", { type = "recruit", settlement = "Venice", unit = "Spear Militia" })') == "recruit ok"
    assert lua('return M.qa.deliver("venice", "Venice")') == "delivered=1"
    assert "create Venice Spear Militia" in lua("return FAKE.calls").values()


def test_ports_blockades_and_shores(lua):
    assert lua('return M.qa.port_town("venice", 120, 88)') == "Innsbruck"  # at war; Milan has no port
    assert lua('return M.qa.port_town("venice", 120, 88, "own")') == "Venice"
    assert lua('return M.qa.port("Innsbruck")') == "116,91"
    assert lua('return M.qa.port("Milan")') == "none"
    assert lua('return M.qa.blockade_of("Innsbruck")') == "by=- turns=0"
    assert lua('return M.qa.blockade_of("Milan")') == "no port"
    fleet = lua('return M.qa.spawn_fleet("venice", 115, 90)')
    assert lua(f'return M.qa.order("venice", {{ type = "blockade", fleet = "{fleet}", settlement = "Innsbruck" }})') == "blockade ok"
    assert lua('return M.qa.blockade_of("Innsbruck")') == f"by={fleet} turns=0"
    assert lua('return M.qa.shore(120, 88, 1, 3)') == "119,89"  # land, sea at (118,90) beside it
    assert lua('return M.qa.far_shore(119, 89, 2, 15)') == "128,96"  # the island
    assert lua('return M.qa.far_shore(119, 89, 2, 4)') == "none"
    assert lua('return M.qa.sea(120, 88, 1, 1)') == "none"


def test_rerun_runs_the_order_a_refusal_hands_out_or_fails(lua, game):
    _, root = game
    assert lua('return M.qa.rerun("venice", "move_army")') is None  # no order said anything yet
    log = (root / "parley_bridge.log").read_text()
    assert "qa: rerun failed: " in log and "no order to copy in: none" in log
    fleet = lua('return M.qa.spawn_fleet("venice", 118, 90)')
    army = lua('return M.qa.spawn_army("venice", 119, 89)')
    res = lua(f'return M.qa.order("venice", {{ type = "move_army", army = "{army}", x = 128, y = 96 }})')
    assert f'{{"type": "board", "who": "{army}", "fleet": "{fleet}"}}' in res
    assert lua('return M.qa.rerun("venice", "move_army")') == "board ok"
    assert lua(f'return M.qa.army("venice", "{army}")').endswith(f"aboard={fleet}")
