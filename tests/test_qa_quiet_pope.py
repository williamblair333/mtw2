"""The QA bench's quiet world keeps the Pope young (games/interrupts.toml papal_election): M.qa.quiet
writes the Pope's age down to 45 and reads it back (the runner calls it after every bench load), and
under freeze=* the bridge calls it again at the player's turn start, as a turn case plays rounds. A
real config (no freeze=*) leaves him alone. Fake game only: that the game's old-age death roll reads
characterRecord.age is a guess the bench run checks."""

from pathlib import Path

import pytest
from lupa.luajit21 import LuaRuntime

ROOT = Path(__file__).parent.parent
TURN = 3
QUIET = "game_id=g1\nfaction=venice\nfreeze=*\n"
REAL = "game_id=g1\nfaction=venice\n"


@pytest.fixture
def game(tmp_path):
    def make(bridge_txt: str, pope_age: int = 78):
        rt = LuaRuntime(unpack_returned_tuples=True)
        rt.execute(f"package.path = '{ROOT}/lua/?.lua;{ROOT}/lua/vendor/?.lua;{ROOT}/tests/lua/?.lua;' .. package.path")
        rt.execute("FAKE = require('fake_game'); FAKE.reset()")
        root = tmp_path / "parley_turns"
        for turn in (TURN - 1, TURN):
            (root / "g1" / f"turn-{turn:04d}" / "venice").mkdir(parents=True, exist_ok=True)
        (root / "bridge.txt").write_text(bridge_txt)
        rt.execute(f"BRIDGE = require('parley_bridge'); BRIDGE.setup('{root}'); "
                   "BRIDGE.clock = function() return FAKE.now end")
        rt.execute("FAKE.add_college('Pope Gregory', { { 'Cardinal Ottone', 'milan' } })")
        rt.execute(f"FAKE.college.pope.age = {pope_age}; FAKE.college.pope.fullName = 'Pope Gregory'")
        return rt, root
    return make


def log_of(root: Path) -> str:
    p = root / "parley_bridge.log"
    return p.read_text() if p.exists() else ""


def test_quiet_makes_an_old_pope_young_and_reports_it(game):
    rt, root = game(QUIET)
    assert rt.eval("BRIDGE.qa.quiet()") == "pope=Pope Gregory age=78->45; venice leader=none heir=none towns=" + str(rt.eval("FAKE.byName.venice.settlementsNum")) + " calmed=0 cured=0"
    assert rt.eval("FAKE.college.pope.age") == 45


def test_quiet_leaves_a_young_pope_alone(game):
    rt, root = game(QUIET, pope_age=33)
    assert rt.eval("BRIDGE.qa.quiet()").startswith("pope=Pope Gregory age=33->33;")


def test_quiet_fails_when_the_age_does_not_stick(game):
    # a read-only field live would leave him old: the runner must refuse the load, so quiet fails
    rt, root = game(QUIET)
    rt.execute("local rec = FAKE.college.pope; FAKE.college.pope = setmetatable({ fullName = rec.fullName }, "
               "{ __index = function(_, k) if k == 'age' then return 78 end end, __newindex = function() end })")
    assert rt.eval("BRIDGE.qa.quiet()") is None
    assert "qa: quiet failed: " in log_of(root)


def test_quiet_mid_election_reports_no_pope(game):
    rt, root = game(QUIET)
    rt.execute("FAKE.college_drop(FAKE.college.pope.character)")
    assert rt.eval("BRIDGE.qa.quiet()").startswith("pope=none (election on);")


def test_the_players_turn_start_keeps_him_young_in_the_quiet_world(game):
    rt, root = game(QUIET)
    rt.execute("FAKE.byName.venice.isPlayerControlled = 1")
    rt.execute("BRIDGE.on_turn_start(FAKE.byName.venice)")
    assert rt.eval("FAKE.college.pope.age") == 45


def test_an_ai_turn_start_writes_nothing(game):
    rt, root = game(QUIET)
    rt.execute("FAKE.byName.milan.isPlayerControlled = 0")
    rt.execute("BRIDGE.on_turn_start(FAKE.byName.milan)")
    assert rt.eval("FAKE.college.pope.age") == 78


def test_a_real_campaign_leaves_the_pope_to_age(game):
    rt, root = game(REAL)
    rt.execute("FAKE.byName.venice.isPlayerControlled = 1")
    rt.execute("BRIDGE.on_turn_start(FAKE.byName.venice)")
    assert rt.eval("FAKE.college.pope.age") == 78


def _family(rt, leader_age=67, heir_age=48):
    rt.execute(f"FAKE.byName.venice.leader = {{ fullName = 'Doge Pietro', age = {leader_age} }}; "
               f"FAKE.byName.venice.heir = {{ fullName = 'Marco', age = {heir_age} }}")


def test_quiet_keeps_the_seated_factions_leader_and_heir_young(game):
    # succession (games/interrupts.toml): neither dies of old age into a succession scroll
    rt, root = game(QUIET)
    _family(rt)
    assert rt.eval("BRIDGE.qa.quiet()") == (
        "pope=Pope Gregory age=78->45; venice leader=Doge Pietro age=67->45 heir=Marco age=48->45 towns="
        + str(rt.eval("FAKE.byName.venice.settlementsNum")) + " calmed=0 cured=0")
    assert rt.eval("FAKE.byName.venice.leader.age") == 45
    assert rt.eval("FAKE.byName.venice.heir.age") == 45


def test_quiet_reports_a_missing_heir_and_leaves_unseated_factions_alone(game):
    rt, root = game(QUIET)
    _family(rt)
    rt.execute("FAKE.byName.venice.heir = nil; FAKE.byName.milan.leader = { fullName = 'Duke', age = 70 }")
    assert "venice leader=Doge Pietro age=67->45 heir=none towns=" in rt.eval("BRIDGE.qa.quiet()")
    assert rt.eval("FAKE.byName.milan.leader.age") == 70


def test_quiet_fails_when_the_leaders_age_does_not_stick(game):
    rt, root = game(QUIET)
    _family(rt)
    rt.execute("FAKE.byName.venice.leader = setmetatable({ fullName = 'Doge Pietro' }, "
               "{ __index = function(_, k) if k == 'age' then return 67 end end, __newindex = function() end })")
    assert rt.eval("BRIDGE.qa.quiet()") is None
    assert "venice's leader's age stayed 67" in log_of(root)


def test_the_players_turn_start_keeps_the_leader_young_too(game):
    rt, root = game(QUIET)
    _family(rt)
    rt.execute("FAKE.byName.venice.isPlayerControlled = 1")
    rt.execute("BRIDGE.on_turn_start(FAKE.byName.venice)")
    assert rt.eval("FAKE.byName.venice.leader.age") == 45


def test_quiet_calms_and_cures_the_seated_factions_towns(game):
    # rebellion and plague (games/interrupts.toml): turmoil, rebel chance and plague cleared
    rt, root = game(QUIET)
    rt.execute("local s = FAKE.byName.venice:getSettlement(0); s.turmoil = 4; s.rebelFactionChance = 30; "
               "s.plagued = true; s.plagueDuration = 3")
    out = rt.eval("BRIDGE.qa.quiet()")
    assert " calmed=1 cured=1" in out
    assert rt.eval("FAKE.byName.venice:getSettlement(0).turmoil") == 0
    assert rt.eval("FAKE.byName.venice:getSettlement(0).rebelFactionChance") == 0
    assert rt.eval("FAKE.byName.venice:getSettlement(0).plagued") is False
    assert rt.eval("FAKE.byName.venice:getSettlement(0).plagueDuration") == 0


def test_quiet_fails_when_a_towns_turmoil_does_not_clear(game):
    rt, root = game(QUIET)
    # a read-only field live: writes are dropped, the read still says 4
    rt.execute("local real = FAKE.byName.venice:getSettlement(0); "
               "local stuck = setmetatable({}, { __index = function(_, k) if k == 'turmoil' then return 4 end "
               "return real[k] end, __newindex = function() end }); "
               "FAKE.byName.venice.getSettlement = function() return stuck end")
    assert rt.eval("BRIDGE.qa.quiet()") is None
    assert "kept turmoil 4" in log_of(root)
