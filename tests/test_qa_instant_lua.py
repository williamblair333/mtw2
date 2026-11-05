"""games/qa/instant.toml's own control lines, run by the QA runner through the bridge's control file
against the fake game (LuaJIT via lupa): every line parses, every helper exists, and the checks pass
on the fake's behaviour. Not a live pass: the fake is only as true as tests/lua/fake_game.lua."""

import tomllib
from pathlib import Path

import pytest
from lupa.luajit21 import LuaRuntime

from parley.qa.cases import Suite
from parley.qa.control import Control, ControlTimeout
from parley.qa.runner import QA_HOLD_REASON, _run_instant_case

ROOT = Path(__file__).parent.parent
TURN = 3
ROBIN_IN_VENICE = "FAKE.general_in_town(FAKE.byName.venice, 'Captain Robin', FAKE.settlements.Venice)"
# the game starts a siege and the town shows it (settlementStruct.siegesNum, getSiege(0).besieger)
REBELS_BESIEGE = (
    "local fac = FAKE.byName.slave; local spawn = fac.spawnArmy; "
    "fac.spawnArmy = function(self, ...) local st = spawn(self, ...); local siege = st.siegeSettlement; "
    "st.siegeSettlement = function(me, s, a) siege(me, s, a); s.siegesNum = 1; "
    "s.getSiege = function() return { besieger = me } end end; return st end"
)
# live run9: moveToTile from a field tile walks him on at once (Caen to (110,130)); the fake only
# records it. Here a general outside a town walks up to 3 tiles toward the target.
WALKS = (
    "for _, c in ipairs(FAKE.byName.venice.characters) do if not c.walks then c.walks = true; "
    "local rec = c.moveToTile; c.moveToTile = function(self, tx, ty) rec(self, tx, ty); "
    "for _, s in pairs(FAKE.settlements) do if s.xCoord == self.xCoord and s.yCoord == self.yCoord then return end end; "
    "for _ = 1, 3 do "
    "self.xCoord = self.xCoord + (tx > self.xCoord and 1 or (tx < self.xCoord and -1 or 0)); "
    "self.yCoord = self.yCoord + (ty > self.yCoord and 1 or (ty < self.yCoord and -1 or 0)) end end end end"
)


class TickingControl(Control):
    """The runner's Control, with the game's tick run after each line is written: the bridge reads
    control.txt, runs the line and logs `control: lua -> <result>`, as in the game."""

    def __init__(self, rt, root: Path):
        super().__init__(root, timeout=1.0)
        self.rt = rt
        self.lines: list[str] = []

    def run_lua(self, line: str) -> str:
        self.lines.append(line)
        self.rt.execute(WALKS)
        offset = self.log_offset()
        with self._control_path.open("a", encoding="utf-8") as f:
            f.write(f"lua {line}\n")
        self.rt.execute("FAKE.now = FAKE.now + 1; BRIDGE.tick()")
        res = self._read_result_after(offset)
        if res is None:
            raise ControlTimeout(f"no result for {line}")
        return res


@pytest.fixture
def game(tmp_path):
    rt = LuaRuntime(unpack_returned_tuples=True)
    rt.execute(f"package.path = '{ROOT}/lua/?.lua;{ROOT}/lua/vendor/?.lua;{ROOT}/tests/lua/?.lua;' .. package.path")
    rt.execute("FAKE = require('fake_game'); FAKE.reset()")
    root = tmp_path / "parley_turns"
    for turn in (TURN - 1, TURN):
        (root / "g1" / f"turn-{turn:04d}" / "venice").mkdir(parents=True)
    # autoplay on, waiting 60 s: without the hold the bridge would end the turn under the case
    (root / "bridge.txt").write_text("game_id=g1\nfaction=venice\nautoplay=1\nautoplay_wait=60\n")
    rt.execute(f"BRIDGE = require('parley_bridge'); BRIDGE.setup('{root}'); "
               "BRIDGE.clock = function() return FAKE.now end")
    rt.execute(f"{ROBIN_IN_VENICE}; {REBELS_BESIEGE}")
    rt.execute("FAKE.ui.end_turn = { elementName = 'end_turn', "
               "execute = function() FAKE.calls[#FAKE.calls + 1] = 'press end_turn' end }")
    (root / "g1" / f"turn-{TURN:04d}" / "venice" / "state.json").write_text(
        '{"turn": 3, "faction": "venice", "settlements": [{"id": "Venice", "x": 120, "y": 88}], '
        '"armies": [{"id": "garrison:Venice", "in_settlement": "Venice", "leader": "Captain Robin"}]}'
    )
    return rt, root


def _suite_for_venice() -> Suite:
    """instant.toml as written, with the fake's faction for England."""
    text = (ROOT / "games" / "qa" / "instant.toml").read_text(encoding="utf-8")
    assert text.count('"england"') >= 5
    return Suite.model_validate(tomllib.loads(text.replace('"england"', '"venice"')))


def test_the_instant_suite_runs_on_the_fake_game_in_one_held_turn(game):
    rt, root = game
    ctrl = TickingControl(rt, root)
    results = {}
    for i, case in enumerate(_suite_for_venice().cases):
        rt.execute(f"FAKE.random_name = 'Spawned{i}'")  # the live game names each spawn anew
        res, _ = _run_instant_case(case, "qa-instant", "g1", "venice", root, ctrl, TURN,
                                   poll_interval=0.0, turn_wait=1.0)
        results[case.name] = res
        assert not (root / "paused.txt").exists()  # the hold ends with the case

    for name, res in results.items():
        assert res.outcome == "pass", (name, res.evidence, ctrl.lines)
    assert "refused: Venice is under siege by" in results["besieged_town_refuses"].evidence
    calls = list(rt.eval("FAKE.calls").values())
    assert "press end_turn" not in calls
    siege_at = next(i for i, c in enumerate(calls) if c.startswith("siege "))
    assert not any(c.startswith(("splitArmy", "moveToTile")) for c in calls[siege_at:]), calls
    assert "paused: " + QA_HOLD_REASON in (root / "parley_bridge.log").read_text()
