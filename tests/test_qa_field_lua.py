"""games/qa/field.toml: its instant cases run by the QA runner through the bridge's control file
against the fake game (as tests/test_qa_instant_lua.py does for instant.toml), its turn case checked
for shape, and spawn_army's taken-tile and landing checks and M.qa.units on their own. The fake plays
the game as the suite guesses the real one does (a general walks up to 3 tiles toward a move's
target in-turn, splits out of a town onto the next tile, a stack beside a hostile town besieges it,
an island town across the sea): not a live pass."""

import tomllib
from pathlib import Path

import pytest
from lupa.luajit21 import LuaRuntime

from parley.qa.cases import Suite
from parley.qa.runner import _required_placeholders, _run_instant_case
from tests.test_qa_instant_lua import ROBIN_IN_VENICE, TURN, TickingControl
from tests.test_qa_siege_lua import GAME as SIEGE_GAME

ROOT = Path(__file__).parent.parent

# On top of the siege suite's fake (Peasants, a stack that besieges, the leader's walk kept with his
# character's): each spawn named anew (live 10-30), and Corfu, Milan's island town across the sea
# (land 148-152 x 118-122; the fake's sea is x >= 115, y >= 90)
GAME = """
local spawned = 0
for _, name in ipairs({ 'venice', 'slave' }) do
    local fac = FAKE.byName[name]
    local inner = fac.spawnArmy
    fac.spawnArmy = function(...)
        spawned = spawned + 1
        FAKE.random_name = 'Spawn' .. spawned
        return inner(...)
    end
end
local getTile = FAKE.stratMap.getTile
FAKE.stratMap.getTile = function(x, y)
    local t = getTile(x, y)
    if x >= 148 and x <= 152 and y >= 118 and y <= 122 then t.isLand = 1 end
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
    (root / "bridge.txt").write_text("game_id=g1\nfaction=venice\nautoplay=1\nautoplay_wait=60\n"
                                     "control=venice:diplomacy,armies,agents,build,recruit,taxes\n")
    rt.execute(f"BRIDGE = require('parley_bridge'); BRIDGE.setup('{root}'); "
               "BRIDGE.clock = function() return FAKE.now end")
    rt.execute(ROBIN_IN_VENICE)
    rt.execute(SIEGE_GAME)
    rt.execute(GAME)
    rt.execute("FAKE.ui.end_turn = { elementName = 'end_turn', "
               "execute = function() FAKE.calls[#FAKE.calls + 1] = 'press end_turn' end }")
    (root / "g1" / f"turn-{TURN:04d}" / "venice" / "state.json").write_text(
        '{"turn": 3, "faction": "venice", "settlements": [{"id": "Venice", "x": 120, "y": 88}], '
        '"armies": [{"id": "garrison:Venice", "in_settlement": "Venice", "leader": "Captain Robin"}]}'
    )
    return rt, root


def _text() -> str:
    return (ROOT / "games" / "qa" / "field.toml").read_text(encoding="utf-8")


def _suite() -> Suite:
    """field.toml as written, with the fake's faction for England (in its log lines too)."""
    return Suite.model_validate(tomllib.loads(_text().replace("england", "venice")))


def _calls(rt) -> list[str]:
    return list(rt.eval("FAKE.calls").values())


INSTANT = [
    "spawn_army", "move_army", "march_on_besieges", "march_on_across_sea_refused",
    "move_army_across_sea_refused", "no_moves_left_refused", "merge_armies", "garrison_general_leaves",
    "withdraw",
]


def test_the_field_suite_is_instant_but_one_turn_case_last_and_names_its_unforceables():
    suite = Suite.model_validate(tomllib.loads(_text()))
    assert [c.name for c in suite.cases if c.kind == "instant"] == INSTANT
    turn = [c for c in suite.cases if c.kind == "turn"]
    assert [c.name for c in turn] == ["turn_start_orders"] and suite.cases[-1] is turn[0]
    # garrison_general_leaves takes the town's own general out before withdraw brings one in
    names = [c.name for c in suite.cases]
    assert names.index("garrison_general_leaves") < names.index("withdraw")
    live = {"home_x", "home_y", "garrison_town", "garrison_town_x", "garrison_town_y"}
    for case in suite.cases:
        assert _required_placeholders(case) - case.binds <= live, case.name
        assert not case.needs, case.name  # nothing here needs an AI faction to act: all stay frozen
    text = _text()
    assert "What can't be forced" in text and "Unproven live" in text
    # every old case is accounted for in the old -> new map
    for old in ("spawn_army", "move_army", "march_on_besieges", "march_on_across_sea", "move_army_across_sea",
                "no_moves_left", "withdraw", "merge_armies", "garrison_general_leaves"):
        assert f"#   {old} " in text, old


def test_the_turn_case_groups_what_needs_the_turn_start():
    case = next(c for c in Suite.model_validate(tomllib.loads(_text())).cases if c.name == "turn_start_orders")
    assert list(case.orders) == [1] and [o["type"] for o in case.orders[1]] == ["march_on", "move_army"]
    logs = [e.log for e in case.expect if e.log]
    assert any("siege_scroll -> siege_maintain_button" in p for p in logs)  # the popup after march_on
    assert any(p.startswith("qa: tired $tired at turn start") for p in logs)  # tire() at the refill
    assert {e.state for e in case.expect if e.state} >= {"last_results", "armies[id=$tired].x", "armies[id=$tired].y"}
    assert not case.chance  # nothing here is a roll
    # both scenes by the hostile town, away from own towns (spawns absorbed into a garrison, 10-31)
    lines = [s.lua for s in case.setup if not isinstance(s, str)]
    assert sum("spawn_army" in s for s in lines) == 2
    assert 'free_tile($hostile_at_x, $hostile_at_y, 3, 4)' in "\n".join(lines)


def test_the_field_suite_s_instant_cases_run_on_the_fake_game_in_one_held_turn(game):
    rt, root = game
    ctrl = TickingControl(rt, root)
    results = {}
    for case in (c for c in _suite().cases if c.kind == "instant"):
        res, _ = _run_instant_case(case, "qa-field", "g1", "venice", root, ctrl, TURN,
                                   poll_interval=0.0, turn_wait=1.0)
        results[case.name] = res
        assert not (root / "paused.txt").exists()

    assert list(results) == INSTANT
    failed = {name: (res.outcome, res.evidence) for name, res in results.items() if res.outcome != "pass"}
    assert not failed, (failed, ctrl.lines[-12:])
    calls = _calls(rt)
    assert "press end_turn" not in calls
    assert any(c.startswith("siege ") and c.endswith(" Innsbruck false") for c in calls)  # march_on's siege
    assert any(c.startswith("merge ") and c.endswith(" true") for c in calls)  # next tile: merged at once
    assert any(c.startswith("splitArmy venice NE Bodyguard ") for c in calls)  # Robin out of Venice
    # the refusals moved nobody toward Corfu's island
    walks = [c.split() for c in calls if c.startswith("moveToTile ")]
    assert not any(int(w[-2]) >= 148 for w in walks), walks


def test_a_general_who_never_leaves_the_town_fails_the_case(game):
    # live 10-30 22:59-23:29 (London): the order "done", the general still inside. A split the game
    # refuses (and the moveToTile after it, which the fake only records) is that bug
    rt, root = game
    rt.execute("FAKE.split_raises = true")
    case = next(c for c in _suite().cases if c.name == "garrison_general_leaves")
    case = case.model_copy(update={"expect": [e.model_copy(update={"within": 0.2}) if e.lua else e
                                              for e in case.expect]})
    res, _ = _run_instant_case(case, "qa-field", "g1", "venice", root, TickingControl(rt, root), TURN,
                               poll_interval=0.0, turn_wait=1.0)
    assert res.outcome == "fail", res.evidence
    assert "town=Venice" in res.evidence


@pytest.fixture
def lua(game):
    rt, root = game

    def run(line: str):
        return rt.eval(f"(function() {line} end)()")

    rt.execute("M = BRIDGE")
    run.root = root
    return run


def _log(lua) -> str:
    return (lua.root / "parley_bridge.log").read_text()


def test_spawn_army_refuses_a_tile_someone_stands_on(lua):
    # QA field 10-30/31: a spawn on a taken tile landed a tile off and the case read the wrong tile
    assert lua('return M.qa.spawn_army("venice", 120, 87)') is None  # Marco the spy stands there
    assert "(120,87) is taken: spawn on a free tile (free_tile)" in _log(lua)
    assert not any(c.startswith("spawnArmy ") for c in lua("return FAKE.calls").values())


def test_spawn_army_fails_when_the_army_lands_off_its_tile(lua):
    lua("local fac = FAKE.byName.venice; local inner = fac.spawnArmy; "
        "fac.spawnArmy = function(self, a, b, c, d, e, x, y, ...) return inner(self, a, b, c, d, e, x + 1, y, ...) end")
    assert lua('return M.qa.spawn_army("venice", 110, 70)') is None
    assert "landed at (111,70), not (110,70)" in _log(lua)


def test_the_readiness_canary_spawns_near_an_own_town_walks_one_tile_and_is_removed(lua):
    # parley/qa/runner.py _await_ready: live 10-31 moves came back "ok" and nobody moved after a load
    # during the AI's turns; the canary is that move, made on purpose and watched
    res = lua('return M.qa.canary("venice")')
    army, start, target = res.split("|")
    sx, sy = map(int, start.split(","))
    tx, ty = map(int, target.split(","))
    assert 2 <= max(abs(sx - 120), abs(sy - 88)) <= 4  # beside Venice, never on it
    assert max(abs(tx - sx), abs(ty - sy)) == 1
    calls = list(lua("return FAKE.calls").values())
    assert any(c.startswith(f"spawnArmy venice random_name ") and c.endswith(f" {sx} {sy} " + c.split()[-1])
               for c in calls), calls
    assert any(c.startswith("moveToTile ") and c.endswith(f" {tx} {ty}") for c in calls), calls
    assert lua(f'return M.qa.army("venice", "{army}")').startswith(f"{sx},{sy} ")
    # check-only looks and kills nothing (the runner polls it while the real kill lands)
    assert lua(f'return M.qa.canary_gone("venice", "{army}", true)') == "left"
    assert not any(str(c).startswith("kill ") for c in lua("return FAKE.calls").values())
    gone = lua(f'return M.qa.canary_gone("venice", "{army}")')
    assert gone in ("gone", "left")
    assert f"kill {army}" in list(lua("return FAKE.calls").values())
    assert lua('return M.qa.canary_gone("venice", "Nobody")') == "gone"


def test_a_canary_with_nowhere_to_stand_fails_and_spawns_nothing(lua):
    lua("FAKE.stratMap.regionsNum = 0")
    assert lua('return M.qa.canary("venice")') is None
    log = _log(lua)
    assert "qa: canary failed: " in log and "no free land tile 2-4 tiles from any of venice's towns" in log
    assert not any(c.startswith("spawnArmy ") for c in lua("return FAKE.calls").values())


def test_units_counts_an_army_s_units_or_says_gone(lua):
    army = lua('return M.qa.spawn_army("venice", 110, 70)')
    assert lua(f'return M.qa.units("venice", "{army}")') == 1
    assert lua('return M.qa.units("venice", "Doge Enrico")') == 2
    assert lua('return M.qa.units("venice", "Nobody")') == "gone"
