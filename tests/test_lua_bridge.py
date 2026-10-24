"""The game-side bridge (lua/parley_bridge.lua), run in LuaJIT via lupa against a fake game."""

import json
from pathlib import Path

import pytest
from lupa.luajit21 import LuaRuntime

from parley.protocol import StateReport

ROOT = Path(__file__).parent.parent
TURN = 3  # the fake campaign's turnNumber


class Game:
    """A LuaJIT runtime with the fake game and bridge loaded, plus the turn root."""

    def __init__(self, rt, root):
        self.rt, self.root = rt, root

    def execute(self, code):
        return self.rt.execute(code)

    def eval(self, code):
        return self.rt.eval(code)


@pytest.fixture
def lua(tmp_path):
    rt = LuaRuntime(unpack_returned_tuples=True)
    rt.execute(f"package.path = '{ROOT}/lua/?.lua;{ROOT}/lua/vendor/?.lua;{ROOT}/tests/lua/?.lua;' .. package.path")
    rt.execute("FAKE = require('fake_game'); FAKE.reset()")
    root = tmp_path / "parley_turns"
    (root / "g1").mkdir(parents=True)
    (root / "bridge.txt").write_text("game_id=g1\nfaction=venice\nfaction=milan\n")
    for turn in (TURN - 1, TURN):
        for f in ("venice", "milan"):
            (root / "g1" / f"turn-{turn:04d}" / f).mkdir(parents=True)
    rt.execute(f"BRIDGE = require('parley_bridge'); BRIDGE.setup('{root}')")
    return Game(rt, root)


def turn_dir(lua, turn, faction):
    return lua.root / "g1" / f"turn-{turn:04d}" / faction


def end_turn(lua, faction):
    lua.execute(f"BRIDGE.on_turn_end(FAKE.byName['{faction}'])")


def start_turn(lua, faction):
    lua.execute(f"BRIDGE.on_turn_start(FAKE.byName['{faction}'])")


def write_orders(lua, turn, faction, orders):
    (turn_dir(lua, turn, faction) / "orders.json").write_text(json.dumps(
        {"protocol": 1, "game_id": "g1", "turn": turn, "faction": faction, "orders": orders}))


def calls(lua):
    return list(lua.eval("FAKE.calls").values())


# --- reports -------------------------------------------------------------------------

def test_turn_end_writes_valid_report(lua):
    end_turn(lua, "venice")
    report = StateReport.model_validate_json((turn_dir(lua, TURN, "venice") / "state.json").read_text())
    assert (report.game_id, report.turn, report.year, report.faction) == ("g1", TURN, 1081, "venice")
    assert report.treasury == 5000
    assert [s.id for s in report.settlements] == ["Venice", "Ragusa"]
    assert report.settlements[0].region == "region10"


def test_report_lists_armies_with_ids(lua):
    end_turn(lua, "venice")
    report = StateReport.model_validate_json((turn_dir(lua, TURN, "venice") / "state.json").read_text())
    assert [(a.id, a.x, a.in_settlement) for a in report.armies] == [
        ("Doge Enrico", 121, None), ("garrison:Venice", 120, "Venice")]


def test_report_stances_and_no_rebels(lua):
    end_turn(lua, "venice")
    report = StateReport.model_validate_json((turn_dir(lua, TURN, "venice") / "state.json").read_text())
    assert {f.id: f.stance for f in report.factions} == {"hre": "war", "milan": "peace"}


def test_non_llm_faction_writes_nothing(lua):
    end_turn(lua, "hre")
    assert not list(lua.root.rglob("hre"))


def test_report_carries_last_results(lua):
    (turn_dir(lua, TURN - 1, "venice") / "results.json").write_text(
        '[{"index": 0, "type": "set_stance", "ok": true, "reason": ""}]')
    end_turn(lua, "venice")
    report = StateReport.model_validate_json((turn_dir(lua, TURN, "venice") / "state.json").read_text())
    assert report.last_results[0].type == "set_stance"


def test_missing_turn_dir_does_not_raise(lua):
    lua.execute("FAKE.campaign.turnNumber = 99")
    end_turn(lua, "venice")  # no folder prepared for turn 99: logged, not an error


# --- orders: applied at the next turn start, from the previous turn's folder ------------

def test_orders_applied_at_next_turn_start(lua):
    write_orders(lua, TURN - 1, "venice", [
        {"type": "set_stance", "to": "milan", "stance": "alliance"},
        {"type": "send_gold", "to": "milan", "amount": 1000},
    ])
    start_turn(lua, "venice")
    assert "setDipStance 2 venice milan" in calls(lua)
    assert lua.eval("FAKE.byName.venice.money") == 4000
    assert lua.eval("FAKE.byName.milan.money") == 4000
    results = json.loads((turn_dir(lua, TURN - 1, "venice") / "results.json").read_text())
    assert [r["ok"] for r in results] == [True, True]


def test_orders_applied_once(lua):
    write_orders(lua, TURN - 1, "venice", [{"type": "send_gold", "to": "milan", "amount": 100}])
    start_turn(lua, "venice")
    start_turn(lua, "venice")
    assert lua.eval("FAKE.byName.venice.money") == 4900


def test_gold_rechecked_against_live_treasury(lua):
    lua.execute("FAKE.byName.venice.money = 50")
    write_orders(lua, TURN - 1, "venice", [{"type": "send_gold", "to": "milan", "amount": 100}])
    start_turn(lua, "venice")
    r = json.loads((turn_dir(lua, TURN - 1, "venice") / "results.json").read_text())[0]
    assert not r["ok"] and "treasury" in r["reason"]
    assert lua.eval("FAKE.byName.venice.money") == 50


def test_cede_converts_garrison(lua):
    write_orders(lua, TURN - 1, "venice", [{"type": "cede_settlement", "settlement": "Ragusa", "to": "milan"}])
    start_turn(lua, "venice")
    assert "changeOwner Ragusa milan true" in calls(lua)


def test_cede_unowned_rejected(lua):
    write_orders(lua, TURN - 1, "venice", [{"type": "cede_settlement", "settlement": "Milan", "to": "hre"}])
    start_turn(lua, "venice")
    r = json.loads((turn_dir(lua, TURN - 1, "venice") / "results.json").read_text())[0]
    assert not r["ok"] and "not owned" in r["reason"]


def test_army_orders(lua):
    write_orders(lua, TURN - 1, "venice", [
        {"type": "march_on", "army": "Doge Enrico", "target_settlement": "Milan"},
        {"type": "besiege", "army": "Doge Enrico", "settlement": "Milan"},
        {"type": "withdraw", "army": "Doge Enrico", "to_settlement": "Ragusa"},
    ])
    start_turn(lua, "venice")
    assert calls(lua) == ["moveToTile Doge Enrico 100 90", "siege Doge Enrico Milan false",
                          "moveToTile Doge Enrico 140 80"]


def test_garrison_cannot_march(lua):
    write_orders(lua, TURN - 1, "venice", [{"type": "march_on", "army": "garrison:Venice", "target_settlement": "Milan"}])
    start_turn(lua, "venice")
    r = json.loads((turn_dir(lua, TURN - 1, "venice") / "results.json").read_text())[0]
    assert not r["ok"] and "no general" in r["reason"]


def test_bad_order_does_not_stop_the_rest(lua):
    write_orders(lua, TURN - 1, "venice", [
        {"type": "set_stance", "to": "atlantis", "stance": "war"},
        {"type": "teleport"},
        {"type": "send_gold", "to": "milan", "amount": 10},
    ])
    start_turn(lua, "venice")
    results = json.loads((turn_dir(lua, TURN - 1, "venice") / "results.json").read_text())
    assert [r["ok"] for r in results] == [False, False, True]


def test_corrupt_orders_file_logged_not_raised(lua):
    (turn_dir(lua, TURN - 1, "venice") / "orders.json").write_text('{"orders": [')
    start_turn(lua, "venice")
    assert not (turn_dir(lua, TURN - 1, "venice") / "results.json").exists()
    assert "orders unreadable" in (lua.root / "parley_bridge.log").read_text()


# --- final review fixes ------------------------------------------------------------------

def test_non_utf8_names_still_give_valid_json(lua):
    lua.execute(r"FAKE.byName.venice.stacks[1].leader.namedCharacter.fullName = 'Ladis\179aw'")
    end_turn(lua, "venice")
    report = StateReport.model_validate_json((turn_dir(lua, TURN, "venice") / "state.json").read_bytes())
    assert report.armies[0].id.startswith("Ladis")


def test_turn_start_writes_heartbeat(lua):
    start_turn(lua, "venice")
    assert (lua.root / "heartbeat.txt").read_text().strip() == f"turn={TURN}"


def test_reload_reapplies_orders(lua):
    write_orders(lua, TURN - 1, "venice", [{"type": "send_gold", "to": "milan", "amount": 100}])
    start_turn(lua, "venice")
    lua.execute(f"FAKE.reset(); BRIDGE.setup('{lua.root}')")  # a save from before the orders was loaded
    start_turn(lua, "venice")
    assert lua.eval("FAKE.byName.venice.money") == 4900


def test_no_orders_marks_turn_late(lua):
    start_turn(lua, "venice")
    assert (turn_dir(lua, TURN - 1, "venice") / "late.txt").exists()


def test_duplicate_general_names_get_unique_ids(lua):
    lua.execute("FAKE.byName.venice.stacks[2].leader = { namedCharacter = { fullName = 'Doge Enrico' }, "
                "xCoord = 130, yCoord = 85, moveToTile = function(self, x, y) "
                "FAKE.calls[#FAKE.calls + 1] = 'second moves ' .. x end }")
    end_turn(lua, "venice")
    report = StateReport.model_validate_json((turn_dir(lua, TURN, "venice") / "state.json").read_text())
    assert [a.id for a in report.armies] == ["Doge Enrico", "Doge Enrico#2"]
    write_orders(lua, TURN - 1, "venice", [{"type": "march_on", "army": "Doge Enrico#2", "target_settlement": "Milan"}])
    start_turn(lua, "venice")
    assert calls(lua) == ["second moves 100"]


def test_entry_script_wires_eop_events(tmp_path, monkeypatch):
    """luaPluginScript.lua, as EOP loads it: events reach the bridge with turn files
    under parley_turns in the working directory (the game root)."""
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "parley_turns"
    (root / "g1" / f"turn-{TURN:04d}" / "venice").mkdir(parents=True)
    (root / "bridge.txt").write_text("game_id=g1\nfaction=venice\n")
    rt = LuaRuntime(unpack_returned_tuples=True)
    rt.execute(f"package.path = '{ROOT}/tests/lua/?.lua;{ROOT}/lua/vendor/?.lua;' .. package.path")
    rt.execute("FAKE = require('fake_game'); FAKE.reset(); "
               "M2TWEOP = { unlockGameConsoleCommands = function() UNLOCKED = true end }")
    rt.execute(f"dofile('{ROOT}/lua/luaPluginScript.lua')")
    rt.execute("onPluginLoad(); onCampaignMapLoaded(); onFactionTurnEnd({ faction = FAKE.byName.venice })")
    assert rt.eval("UNLOCKED")
    assert (root / "g1" / f"turn-{TURN:04d}" / "venice" / "state.json").exists()


def test_no_orders_yet_is_logged_as_missed(lua):
    start_turn(lua, "venice")
    assert "no orders" in (lua.root / "parley_bridge.log").read_text()
