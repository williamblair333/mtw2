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


def calls(lua, camera=False):
    """Game calls made so far; camera moves are left out unless asked for."""
    return [c for c in lua.eval("FAKE.calls").values() if camera or not c.startswith("camera ")]


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


def test_entry_script_draw_runs_autoplay_and_overlay(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "parley_turns"
    (root / "g1" / f"turn-{TURN - 1:04d}" / "venice").mkdir(parents=True)
    (root / "g1" / f"turn-{TURN - 1:04d}" / "venice" / "orders.json").write_text(
        '{"protocol": 1, "game_id": "g1", "turn": 2, "faction": "venice", "orders": []}')
    (root / "bridge.txt").write_text("game_id=g1\nfaction=venice\nautoplay=1\n")
    rt = LuaRuntime(unpack_returned_tuples=True)
    rt.execute(f"package.path = '{ROOT}/tests/lua/?.lua;{ROOT}/lua/vendor/?.lua;' .. package.path")
    rt.execute("FAKE = require('fake_game'); FAKE.reset(); SHOWN = {}; "
               "ImGui = { Begin = function() return true end, End = function() end, "
               "Text = function(t) SHOWN[#SHOWN + 1] = t end }")
    rt.execute(f"dofile('{ROOT}/lua/luaPluginScript.lua')")
    rt.execute("onCampaignMapLoaded(); draw(nil)")
    assert "script select_ui_element end_turn" in list(rt.eval("FAKE.calls").values())
    assert any("ending turn" in t for t in rt.eval("SHOWN").values())


def test_no_orders_yet_is_logged_as_missed(lua):
    start_turn(lua, "venice")
    assert "no orders" in (lua.root / "parley_bridge.log").read_text()


# --- sight: what the ruler's armies, agents and settlements can see ------------------------

def report_of(lua, faction="venice"):
    end_turn(lua, faction)
    return StateReport.model_validate_json((turn_dir(lua, TURN, faction) / "state.json").read_text())


def test_report_lists_own_agents_not_generals(lua):
    r = report_of(lua)
    assert [(a.id, a.kind, a.x, a.y) for a in r.agents] == [
        ("Iacopo", "assassin", 120, 88), ("Marco", "spy", 120, 87), ("Pietro", "diplomat", 140, 80)]


def test_foreign_armies_in_sight_only(lua):
    r = report_of(lua)
    assert [(a.id, a.faction, a.leader, a.distance) for a in r.visible_enemies] == [("Heinrich", "hre", "Heinrich", 8)]


def test_foreign_agents_in_sight_only(lua):
    r = report_of(lua)
    assert [(a.id, a.faction, a.kind, a.distance) for a in r.seen_agents] == [("Ulrich", "hre", "spy", 1)]


def test_nearby_foreign_settlements(lua):
    r = report_of(lua)
    assert [(s.id, s.faction, s.garrison_strength, s.distance) for s in r.nearby_settlements] == [
        ("Innsbruck", "hre", 500, 7)]


def test_income_is_net_of_expenses(lua):
    # seen live: a 19464 bribe showed as income -19170; one-offs are reported apart
    r = report_of(lua)
    assert r.income == 1500 + 400 - 700 - 300
    assert (r.spent_last_turn, r.received_last_turn) == (5000 + 1200, 200)


def test_broken_foreign_character_is_skipped_not_fatal(lua):
    lua.execute("FAKE.byName.hre.characters[2].getTypeName = function() error('boom') end")
    r = report_of(lua)
    assert r.seen_agents == [] and [a.id for a in r.visible_enemies] == ["Heinrich"]


# --- agent orders -----------------------------------------------------------------------

def results(lua, faction="venice"):
    return json.loads((turn_dir(lua, TURN - 1, faction) / "results.json").read_text())


def issue(lua, order, setup=""):
    """One agent order on a fresh game (an agent acts once per turn); returns (calls, result)."""
    lua.execute(f"FAKE.reset(); BRIDGE.setup('{lua.root}'); {setup}")
    (turn_dir(lua, TURN - 1, "venice") / "results.json").unlink(missing_ok=True)
    write_orders(lua, TURN - 1, "venice", [order])
    start_turn(lua, "venice")
    return calls(lua), results(lua)[0]


@pytest.mark.parametrize("order, call", [
    ({"type": "assassinate", "agent": "Iacopo", "target": "Ulrich"}, "assassinate Iacopo Ulrich"),
    ({"type": "assassinate", "agent": "Iacopo", "target": "Heinrich"}, "assassinate Iacopo Heinrich"),
    ({"type": "sabotage", "agent": "Iacopo", "settlement": "Innsbruck"}, "sabotageSettlement Iacopo Innsbruck"),
    ({"type": "spy", "agent": "Marco", "target": "Innsbruck"}, "spySettlement Marco Innsbruck"),
    ({"type": "spy", "agent": "Marco", "target": "Ulrich"}, "spyCharacter Marco Ulrich"),
    ({"type": "bribe", "agent": "Pietro", "target": "Heinrich"}, "bribe Pietro Heinrich"),
])
def test_agent_orders_issue_the_right_actions(lua, order, call):
    done, r = issue(lua, order)
    assert done == [call] and r["ok"]


def test_one_action_per_agent_per_turn(lua):
    write_orders(lua, TURN - 1, "venice", [
        {"type": "assassinate", "agent": "Iacopo", "target": "Ulrich"},
        {"type": "sabotage", "agent": "Iacopo", "settlement": "Innsbruck"},
    ])
    start_turn(lua, "venice")
    assert calls(lua) == ["assassinate Iacopo Ulrich"]
    assert "already has an order this turn" in results(lua)[1]["reason"]


# a Milan general also called Ulrich, in sight next to the HRE spy Ulrich
MILAN_ULRICH = ("local st = FAKE.byName.milan.stacks[1]; st.leader.namedCharacter.fullName = 'Ulrich'; "
                "st.leader.tag = 'milan'; st.leader.xCoord, st.leader.yCoord = 118, 86; "
                "FAKE.byName.hre.characters[2].tag = 'hre'")


def test_same_name_army_and_agent_get_distinct_ids(lua):
    lua.execute(MILAN_ULRICH)
    r = report_of(lua)
    ids = [a.id for a in r.visible_enemies] + [a.id for a in r.seen_agents]
    assert sorted(ids) == ["Heinrich", "Ulrich", "Ulrich#2"]
    for a in r.visible_enemies + r.seen_agents:
        if a.id.startswith("Ulrich"):
            done, _ = issue(lua, {"type": "assassinate", "agent": "Iacopo", "target": a.id}, MILAN_ULRICH)
            assert done == [f"assassinate Iacopo Ulrich@{a.faction}"]


def test_suffixes_follow_game_order_not_distance(lua):
    # a second HRE spy Ulrich, nearer than the first: he is still Ulrich#2
    second = ("local c = FAKE.byName.hre.characters[2]; FAKE.byName.hre.characters[2].tag = 'first'; "
              "local twin = {}; for k, v in pairs(c) do twin[k] = v end; twin.tag = 'second'; "
              "twin.xCoord, twin.yCoord = 120, 88; table.insert(FAKE.byName.hre.characters, twin); "
              "FAKE.byName.hre.numOfCharacters = #FAKE.byName.hre.characters")
    lua.execute(second)
    assert [(a.id, a.distance) for a in report_of(lua).seen_agents] == [("Ulrich#2", 0), ("Ulrich", 1)]
    done, _ = issue(lua, {"type": "spy", "agent": "Marco", "target": "Ulrich#2"}, second)
    assert done == ["spyCharacter Marco Ulrich@second"]


def test_broken_own_character_does_not_lose_the_report(lua):
    lua.execute("FAKE.byName.venice.characters[2].namedCharacter = nil")
    assert [a.id for a in report_of(lua).agents] == ["Marco", "Pietro"]


def test_orders_outside_the_seats_control_refused(lua):
    (lua.root / "bridge.txt").write_text("game_id=g1\nfaction=venice\nfaction=milan\ncontrol=venice:diplomacy\n")
    write_orders(lua, TURN - 1, "venice", [
        {"type": "march_on", "army": "Doge Enrico", "target_settlement": "Milan"},
        {"type": "send_gold", "to": "milan", "amount": 10},
    ])
    start_turn(lua, "venice")
    r = results(lua)
    assert "not yours to command" in r[0]["reason"] and r[1]["ok"]
    assert calls(lua) == []


# --- full control: the report and orders a player has --------------------------------------

FULL = "control=venice:diplomacy,armies,agents,build,recruit,taxes\n"


def control(lua, line=FULL, extra=""):
    (lua.root / "bridge.txt").write_text(f"game_id=g1\nfaction=venice\nfaction=milan\n{line}{extra}")


def test_full_control_report_has_options_queue_tax_troops_and_moves(lua):
    control(lua)
    r = report_of(lua)
    v = r.settlements[0]
    assert (v.tax_level, v.public_order, v.queue) == ("normal", 85, ["wooden_wall"])
    assert v.order_parts == {"garrison": 30, "squalor": -15}  # what holds order up; zeros left out
    assert [(b.building, b.cost, b.turns) for b in v.can_build] == [("market", 1200, 3), ("farms", 800, 2)]
    # from the recruitment pools: only units with at least one in the pool
    assert [(u.unit, u.cost, u.turns) for u in v.can_recruit] == [("Spear Militia", 350, 1)]
    a = r.armies[0]
    assert [(u.type, u.soldiers, u.max_soldiers, u.exp) for u in a.troops] == [
        ("Venetian Heavy Infantry", 40, 60, 1), ("Mailed Knights", 20, 20, 0)]
    assert (a.moves_left, a.moves_max) == (12, 20)


def test_ruler_report_stays_small(lua):
    r = report_of(lua)
    assert r.settlements[0].can_build == [] and r.settlements[0].tax_level is None
    assert r.armies[0].troops == []


@pytest.mark.parametrize("order, call", [
    ({"type": "build", "settlement": "Venice", "building": "market"}, "build Venice market"),
    ({"type": "move_army", "army": "Doge Enrico", "x": 125, "y": 88}, "moveToTile Doge Enrico 125 88"),
    ({"type": "attack", "army": "Doge Enrico", "target": "Heinrich"}, "attack Doge Enrico Heinrich"),
])
def test_player_orders_issue_the_right_calls(lua, order, call):
    control(lua)
    write_orders(lua, TURN - 1, "venice", [order])
    start_turn(lua, "venice")
    assert call in calls(lua) and results(lua)[0]["ok"]


def test_recruiting_never_asks_for_eops_recruitment_list(lua):
    # EOP 3.3.1 reads past an array when it lists recruits with units inside (C++, before Lua
    # sees anything); recruits come from the recruitment pools instead, units inside or not
    control(lua, "control=venice:recruit\n")
    lua.execute("FAKE.settlements.Venice.army.numOfUnits = 3; "
                "FAKE.settlements.Venice.getRecruitmentOptions = function() error('must not be called') end")
    r = report_of(lua)
    assert [u.unit for u in r.settlements[0].can_recruit] == ["Spear Militia"]
    write_orders(lua, TURN - 1, "venice", [{"type": "recruit", "settlement": "Venice", "unit": "Spear Militia"}])
    start_turn(lua, "venice")
    assert results(lua)[0]["ok"]


def test_recruit_pays_takes_from_the_pool_and_trains_by_next_turn(lua):
    control(lua)
    write_orders(lua, TURN - 1, "venice", [{"type": "recruit", "settlement": "Venice", "unit": "Spear Militia"}])
    start_turn(lua, "venice")
    assert results(lua)[0]["ok"]
    assert lua.eval("FAKE.byName.venice.money") == 5000 - 350
    assert lua.eval("FAKE.settlements.Venice.pools[1].availablePool") == 0.5
    assert not any(c.startswith("create") for c in calls(lua))  # still training
    lua.execute("FAKE.campaign.turnNumber = FAKE.campaign.turnNumber + 1")
    start_turn(lua, "venice")
    assert "create Venice Spear Militia" in calls(lua)


def test_recruit_refused_when_the_pool_is_empty_or_gold_short(lua):
    control(lua)
    lua.execute("FAKE.byName.venice.money = 100")
    write_orders(lua, TURN - 1, "venice", [
        {"type": "recruit", "settlement": "Venice", "unit": "Feudal Knights"},
        {"type": "recruit", "settlement": "Venice", "unit": "Spear Militia"},
    ])
    start_turn(lua, "venice")
    reasons = [r["reason"] for r in results(lua)]
    assert "can't recruit 'Feudal Knights'" in reasons[0] and "treasury" in reasons[1]


def test_training_survives_a_reload(lua):
    control(lua)
    write_orders(lua, TURN - 1, "venice", [{"type": "recruit", "settlement": "Venice", "unit": "Spear Militia"}])
    start_turn(lua, "venice")
    lua.execute(f"package.loaded['parley_bridge'] = nil; BRIDGE = require('parley_bridge'); BRIDGE.setup('{lua.root}')")
    lua.execute("FAKE.campaign.turnNumber = FAKE.campaign.turnNumber + 1")
    start_turn(lua, "venice")
    assert "create Venice Spear Militia" in calls(lua)


def test_report_says_human_slot_and_map_size(lua):
    r = report_of(lua)
    assert r.human_slot and (r.map_width, r.map_height) == (255, 200)
    assert not report_of(lua, "milan").human_slot


def test_move_army_off_the_map_refused(lua):
    control(lua)
    write_orders(lua, TURN - 1, "venice", [{"type": "move_army", "army": "Doge Enrico", "x": -3, "y": 900}])
    start_turn(lua, "venice")
    assert "off the map" in results(lua)[0]["reason"] and calls(lua) == []


def test_move_army_onto_sea_refused_with_the_nearest_land(lua):
    # live: Alfred's order to step out of Dublin onto (92,163), a sea tile, came back "done"
    control(lua)
    write_orders(lua, TURN - 1, "venice", [{"type": "move_army", "army": "Doge Enrico", "x": 116, "y": 91}])
    start_turn(lua, "venice")
    reason = results(lua)[0]["reason"]
    assert "(116,91) is sea" in reason and "nearest land is (" in reason and calls(lua) == []


def test_move_army_moves_a_general_by_his_own_name(lua):
    # live: four generals stood in Dublin's garrison, none leading it; the ruler asked how to move one
    lua.execute("FAKE.add_character(FAKE.byName.venice, 'Rufus', 'general', 121, 88)")
    control(lua)
    write_orders(lua, TURN - 1, "venice", [{"type": "move_army", "army": "Rufus", "x": 110, "y": 88}])
    start_turn(lua, "venice")
    assert results(lua)[0]["ok"] and "moveToTile Rufus 110 88" in calls(lua)


def test_attack_refused_when_the_id_now_belongs_to_another_faction(lua):
    control(lua)
    write_orders(lua, TURN - 1, "venice", [
        {"type": "attack", "army": "Doge Enrico", "target": "Heinrich", "target_faction": "milan"}])
    start_turn(lua, "venice")
    assert "hre" in results(lua)[0]["reason"] and calls(lua) == []


def test_queueing_logs_the_treasury_before_and_after(lua):
    control(lua)
    write_orders(lua, TURN - 1, "venice", [{"type": "build", "settlement": "Venice", "building": "market"}])
    start_turn(lua, "venice")
    assert "treasury 5000 -> 5000" in (lua.root / "parley_bridge.log").read_text()


@pytest.mark.parametrize("order, call", [
    ({"type": "move_agent", "agent": "Pietro", "x": 130, "y": 85}, "moveToTile Pietro 130 85"),
    ({"type": "marry", "agent": "Isabella", "target": "Heinrich"}, "marry Isabella Heinrich"),
    ({"type": "merge_armies", "army": "garrison:Venice", "into": "Doge Enrico"}, "merge garrison:Venice Doge Enrico false"),
])
def test_agent_moves_marriage_and_merging_issue_the_right_calls(lua, order, call):
    control(lua)
    lua.execute("FAKE.add_character(FAKE.byName.venice, 'Isabella', 'princess', 120, 88)")
    write_orders(lua, TURN - 1, "venice", [order])
    start_turn(lua, "venice")
    assert call in calls(lua) and results(lua)[0]["ok"], results(lua)


def test_marry_needs_a_princess_and_a_general_in_sight(lua):
    control(lua)
    write_orders(lua, TURN - 1, "venice", [{"type": "marry", "agent": "Pietro", "target": "Heinrich"}])
    start_turn(lua, "venice")
    assert "princess" in results(lua)[0]["reason"] and calls(lua) == []


def test_merge_refuses_more_than_twenty_units(lua):
    control(lua)
    lua.execute("FAKE.byName.venice.stacks[1].numOfUnits = 15; FAKE.byName.venice.stacks[2].numOfUnits = 8")
    write_orders(lua, TURN - 1, "venice", [{"type": "merge_armies", "army": "garrison:Venice", "into": "Doge Enrico"}])
    start_turn(lua, "venice")
    assert "20" in results(lua)[0]["reason"] and calls(lua) == []


# EOP gives a stack inside a settlement no leader; the general there must still be found
ROBIN_IN_VENICE = "FAKE.add_character(FAKE.byName.venice, 'Captain Robin', 'general', 120, 88)"


def test_general_inside_a_settlement_is_named_on_its_garrison(lua):
    # the garrison keeps its own id: moving the general moves only him and his bodyguard
    # (seen live: Robert marched out of Caen with 22 men and left 8 companies behind)
    lua.execute(ROBIN_IN_VENICE)
    r = report_of(lua)
    a = next(a for a in r.armies if a.in_settlement == "Venice")
    assert (a.id, a.leader) == ("garrison:Venice", "Captain Robin")


def test_general_inside_a_settlement_can_march_out(lua):
    lua.execute(ROBIN_IN_VENICE)
    write_orders(lua, TURN - 1, "venice", [{"type": "march_on", "army": "garrison:Venice", "target_settlement": "Milan"}])
    start_turn(lua, "venice")
    assert results(lua)[0]["ok"] and "moveToTile Captain Robin 100 90" in calls(lua)


def test_governor_flags_are_logged_each_turn(lua):
    control(lua, "control=venice:diplomacy,armies,agents\n", "autoplay=1\n")
    start_turn(lua, "venice")
    assert "governors venice: Venice build=1 recruit=1" in (lua.root / "parley_bridge.log").read_text()


# --- ships: fleets ferry armies and agents, land them, blockade and fight --------------------

FLEET = "FAKE.add_fleet(FAKE.byName.venice, 'Admiral Polo', 118, 92)"


def test_report_marks_fleets_and_who_is_aboard(lua):
    control(lua)
    lua.execute(FLEET + "; local f = FAKE.byName.venice.stacks[3]; local doge = FAKE.byName.venice.stacks[1]; "
                "f.boardedArmy = doge; doge.shipArmy = f; doge.leader = nil; "
                "FAKE.byName.venice.characters[1].xCoord, FAKE.byName.venice.characters[1].yCoord = 118, 92")
    r = report_of(lua)
    fleet = next(a for a in r.armies if a.id == "Admiral Polo")
    assert fleet.is_fleet and fleet.carrying == 2
    doge = next(a for a in r.armies if a.aboard)
    assert (doge.id, doge.aboard, doge.x, doge.y) == ("Doge Enrico", "Admiral Polo", 118, 92)


@pytest.mark.parametrize("order, call", [
    ({"type": "board", "who": "Doge Enrico", "fleet": "Admiral Polo"}, "moveToTile Doge Enrico 118 92"),
    ({"type": "board", "who": "Marco", "fleet": "Admiral Polo"}, "moveToTile Marco 118 92"),
    ({"type": "move_army", "army": "Admiral Polo", "x": 120, "y": 95}, "moveToTile Admiral Polo 120 95"),
    ({"type": "blockade", "fleet": "Admiral Polo", "settlement": "Innsbruck"}, "blockade Admiral Polo Innsbruck port"),
])
def test_naval_orders_issue_the_right_calls(lua, order, call):
    control(lua)
    lua.execute(FLEET)
    write_orders(lua, TURN - 1, "venice", [order])
    start_turn(lua, "venice")
    assert call in calls(lua) and results(lua)[0]["ok"], results(lua)


def test_fleets_sail_on_water_only_and_armies_land_on_land_only(lua):
    control(lua)
    lua.execute(FLEET + "; local f = FAKE.byName.venice.stacks[3]; local doge = FAKE.byName.venice.stacks[1]; "
                "f.boardedArmy = doge; doge.shipArmy = f; doge.leader = nil; "
                "FAKE.byName.venice.characters[1].xCoord, FAKE.byName.venice.characters[1].yCoord = 118, 92")
    write_orders(lua, TURN - 1, "venice", [
        {"type": "move_army", "army": "Admiral Polo", "x": 100, "y": 80},
        {"type": "land", "army": "Doge Enrico", "x": 119, "y": 93},
        {"type": "land", "army": "Doge Enrico", "x": 114, "y": 92},
    ])
    start_turn(lua, "venice")
    r = results(lua)
    assert "onto land" in r[0]["reason"] and "not land" in r[1]["reason"]
    assert r[2]["ok"] and "moveToTile Doge Enrico 114 92" in calls(lua)


def test_land_needs_an_army_aboard(lua):
    control(lua)
    write_orders(lua, TURN - 1, "venice", [{"type": "land", "army": "Doge Enrico", "x": 114, "y": 92}])
    start_turn(lua, "venice")
    assert "not aboard" in results(lua)[0]["reason"]


def test_control_lua_runs_a_line_and_logs_the_result(lua):
    autoplay(lua)
    (lua.root / "control.txt").write_text("lua return gameDataAll.get().stratMap.getTile(118, 92).isLand\n")
    tick(lua)
    assert "control: lua -> 0" in (lua.root / "parley_bridge.log").read_text()


def test_set_tax(lua):
    control(lua)
    write_orders(lua, TURN - 1, "venice", [{"type": "set_tax", "settlement": "Venice", "level": "high"}])
    start_turn(lua, "venice")
    assert lua.eval("FAKE.settlements.Venice.settlementTaxLevel") == 2 and results(lua)[0]["ok"]


def test_build_must_be_on_offer_and_affordable(lua):
    control(lua)
    lua.execute("FAKE.byName.venice.money = 1000")
    write_orders(lua, TURN - 1, "venice", [
        {"type": "build", "settlement": "Venice", "building": "cathedral"},
        {"type": "build", "settlement": "Venice", "building": "market"},
        {"type": "recruit", "settlement": "Milan", "unit": "Peasants"},
    ])
    start_turn(lua, "venice")
    reasons = [r["reason"] for r in results(lua)]
    assert "can't build 'cathedral'" in reasons[0] and "treasury" in reasons[1] and "not owned" in reasons[2]
    assert calls(lua) == []


def test_attack_target_must_be_in_sight(lua):
    control(lua)
    write_orders(lua, TURN - 1, "venice", [{"type": "attack", "army": "Doge Enrico", "target": "Duke Ottone"}])
    start_turn(lua, "venice")
    assert "not in sight" in results(lua)[0]["reason"] and calls(lua) == []


def test_governors_take_what_the_human_slot_leaves(lua):
    control(lua, "control=venice:diplomacy,armies,agents\n", "autoplay=1\n")
    start_turn(lua, "venice")
    assert lua.eval("FAKE.settlements.Venice.aiProductionController.isAutoManagedConstruction") == 1
    assert lua.eval("FAKE.settlements.Venice.aiProductionController.isAutoManagedRecruitment") == 1


def test_full_control_turns_the_governors_off(lua):
    lua.execute("FAKE.settlements.Venice.aiProductionController.isAutoManagedConstruction = 1")
    control(lua, FULL, "autoplay=1\n")
    start_turn(lua, "venice")
    assert lua.eval("FAKE.settlements.Venice.aiProductionController.isAutoManagedConstruction") == 0


def test_autoplay_setup_turns_on_autoresolve_and_prebattle_clicks_it(lua):
    control(lua, "", "autoplay=1\n")
    lua.execute(f"BRIDGE.setup('{lua.root}')")
    assert lua.eval("FAKE.options2.autoresolveAllBattles") == 1
    lua.execute("BRIDGE.on_pre_battle()")
    assert calls(lua) == ["script select_ui_element prebattle_auto_resolve_button",
                          "script simulate_mouse_click lclick_up"]


def test_camera_follows_the_human_slot_under_autoplay(lua):
    control(lua, "", "autoplay=1\n")
    start_turn(lua, "venice")
    assert "camera 121 88" in calls(lua, camera=True)


# --- autoplay: the bridge ends the human's turn once every ruler has answered ---------------

END_TURN = ["script select_ui_element end_turn", "script simulate_mouse_click lclick_up"]
DISMISS = [[f"script select_ui_element {b}", "script simulate_mouse_click lclick_up"]
           for b in ("prebattle_auto_resolve_button", "close_tick_button", "diplomacy_decline_offer_button",
                     "siege_maintain_button", "release_prisoners_button", "close_cross_button",
                     "close_seal_button")]


def autoplay(lua, extra=""):
    (lua.root / "bridge.txt").write_text(
        f"game_id=g1\nfaction=venice\nfaction=milan\nautoplay=1\nautoplay_wait=60\n{extra}")
    lua.execute("BRIDGE.clock = function() return FAKE.now end")


def tick(lua, seconds=5):
    lua.execute(f"FAKE.now = FAKE.now + {seconds}; BRIDGE.tick()")


def reported(lua, turn, faction):
    (turn_dir(lua, turn, faction) / "state.json").write_text("{}")


def test_autoplay_waits_for_every_ruler_then_ends_turn(lua):
    autoplay(lua)
    reported(lua, TURN - 1, "milan")  # milan played turn 2 and hasn't answered yet
    write_orders(lua, TURN - 1, "venice", [])
    start_turn(lua, "venice")
    tick(lua)
    assert calls(lua) == []
    write_orders(lua, TURN - 1, "milan", [])
    tick(lua)
    assert calls(lua) == END_TURN
    tick(lua)
    assert calls(lua) == END_TURN  # once per turn


def test_autoplay_gives_up_waiting_after_the_limit(lua):
    autoplay(lua)
    reported(lua, TURN - 1, "milan")
    write_orders(lua, TURN - 1, "venice", [])
    start_turn(lua, "venice")
    tick(lua, 30)
    assert calls(lua) == []
    tick(lua, 31)
    assert calls(lua) == END_TURN
    assert "milan" in (lua.root / "parley_bridge.log").read_text().split("waited")[-1]


def test_autoplay_applies_the_humans_own_late_orders_before_ending(lua):
    autoplay(lua)
    reported(lua, TURN - 1, "venice")
    start_turn(lua, "venice")  # venice's orders for turn 2 aren't there yet: not marked late
    assert not (turn_dir(lua, TURN - 1, "venice") / "late.txt").exists()
    tick(lua)
    assert calls(lua) == []
    write_orders(lua, TURN - 1, "venice", [{"type": "send_gold", "to": "milan", "amount": 100}])
    tick(lua)
    assert lua.eval("FAKE.byName.venice.money") == 4900
    assert calls(lua) == END_TURN


def test_autoplay_off_does_nothing(lua):
    start_turn(lua, "venice")
    tick(lua, 1000)
    assert calls(lua) == []


def test_autoplay_only_on_the_humans_turn(lua):
    autoplay(lua)
    lua.execute("FAKE.campaign.currentFaction = FAKE.byName.milan")
    tick(lua, 1000)
    assert calls(lua) == []


def test_autoplay_stops_at_the_last_turn(lua):
    autoplay(lua, f"autoplay_until={TURN}\n")
    write_orders(lua, TURN - 1, "venice", [])
    start_turn(lua, "venice")
    tick(lua, 1000)
    assert calls(lua) == []
    assert "last turn" in (lua.root / "parley_bridge.log").read_text()


def test_autoplay_retries_when_the_turn_does_not_end(lua):
    autoplay(lua)
    write_orders(lua, TURN - 1, "venice", [])
    start_turn(lua, "venice")
    tick(lua)
    tick(lua, 21)  # the turn is still TURN 20 s later (the author: stuck took too long at a minute)
    assert calls(lua) == END_TURN  # nothing open: no button pressed blind
    assert list(lua.root.glob("popup-*-m*.req"))  # the turn loop is asked to reopen a minimized message
    tick(lua, 2)  # End Turn again on the next tick
    assert calls(lua) == END_TURN + END_TURN
    assert "stuck" in (lua.root / "parley_bridge.log").read_text()


def test_autoplay_keeps_asking_the_turn_loop_after_giving_up(lua):
    # live: after 15 tries the bridge stopped for good and a marriage offer held the game all night
    autoplay(lua)
    write_orders(lua, TURN - 1, "venice", [])
    start_turn(lua, "venice")
    tick(lua)
    for _ in range(40):  # a stuck check every other tick here
        tick(lua, 21)
    assert "still stuck after 15 tries" in (lua.root / "parley_bridge.log").read_text()
    for r in lua.root.glob("popup-*-m*.req"):
        r.unlink()
    for _ in range(4):  # two stuck checks
        tick(lua, 21)
    reqs = list(lua.root.glob("popup-*-m*.req"))
    assert reqs  # still asking, about every 40 s
    assert json.loads(reqs[0].read_text())["faction"] == "venice"  # so it can decide what it finds


GARRISON = """
    local s = FAKE.settlements['Venice']
    local function unit(kind, n, max) return { eduEntry = { eduType = kind }, soldierCountStratMap = n,
                                                soldierCountStratMapMax = max } end
    s.army.units = { unit('Spear Militia', 30, 60), unit('Feudal Knights', 10, 40), unit('Spear Militia', 60, 60) }
    s.army.numOfUnits = 3
    s.army.getUnit = function(self, i) return self.units[i + 1] end
"""


def test_retrain_refills_by_direct_write_for_any_faction(lua):
    # the author: everything should be direct write if possible. Like the game's Retrain tab: a worn unit
    # is refilled when its type is still in the settlement's pool; Feudal Knights' pool is empty
    control(lua)
    lua.execute(GARRISON + "FAKE.byName.venice.money = 1000")
    write_orders(lua, TURN - 1, "venice", [{"type": "retrain", "settlement": "Venice"}])
    start_turn(lua, "venice")
    assert results(lua)[0]["ok"], results(lua)
    assert lua.eval("FAKE.byName.venice.money") == 1000 - 175  # half of 60 missing: half of 350
    assert lua.eval("FAKE.settlements['Venice'].army.units[1].soldierCountStratMap") == 30  # arrives next turn
    assert lua.eval("FAKE.settlements['Venice'].army.units[2].soldierCountStratMap") == 10  # no knights in the pool
    end_turn(lua, "venice")
    lua.execute("FAKE.campaign.turnNumber = FAKE.campaign.turnNumber + 1")
    start_turn(lua, "venice")
    assert lua.eval("FAKE.settlements['Venice'].army.units[1].soldierCountStratMap") == 60
    assert "Spear Militia retrained in Venice" in (lua.root / "parley_bridge.log").read_text()


def test_retrain_takes_the_most_worn_first_up_to_the_slots(lua):
    # live: nine units refilled at once at Nottingham, several missing one man; the Retrain tab
    # gives a minor city 2 slots, a large city 3
    control(lua)
    lua.execute("""
        local s = FAKE.settlements['Venice']
        s.level = 3
        s.pools = { { eduIndex = 7, availablePool = 5 }, { eduIndex = 9, availablePool = 0.4 } }
        local function unit(n) return { eduEntry = { eduType = 'Spear Militia' }, soldierCountStratMap = n,
                                        soldierCountStratMapMax = 60 } end
        s.army.units = { unit(59), unit(20), unit(40), unit(58) }
        s.army.numOfUnits = 4
        s.army.getUnit = function(self, i) return self.units[i + 1] end
        FAKE.byName.venice.money = 5000
    """)
    write_orders(lua, TURN - 1, "venice", [{"type": "retrain", "settlement": "Venice"}])
    start_turn(lua, "venice")
    log = (lua.root / "parley_bridge.log").read_text()
    assert "Spear Militia 20/60, Spear Militia 40/60" in log and "58/60" not in log


def test_retrain_says_why_when_nothing_can_be_retrained(lua):
    control(lua)
    lua.execute(GARRISON + "FAKE.byName.venice.money = 50")  # too little for any refill
    write_orders(lua, TURN - 1, "venice", [{"type": "retrain", "settlement": "Venice"}])
    start_turn(lua, "venice")
    assert "nothing to retrain" in results(lua)[0]["reason"]


def test_autoplay_clicks_only_popups_that_are_open(lua):
    autoplay(lua)
    lua.execute("gameSTDUI = { getUiElement = function(n) if n == 'siege_maintain_button' then return {} end end }")
    write_orders(lua, TURN - 1, "venice", [])
    start_turn(lua, "venice")
    tick(lua)
    tick(lua, 61)
    # the watcher pressed the open siege button within seconds; recovery doesn't press it again
    sieges = [c for c in calls(lua) if c == "script select_ui_element siege_maintain_button"]
    assert len(sieges) == 1


def test_autoplay_gives_up_and_asks_for_a_human(lua):
    autoplay(lua)
    lua.execute("FAKE.campaign.currentFaction = FAKE.byName.milan")
    tick(lua)
    for _ in range(20):
        tick(lua, 31)
    clicks = [c for c in calls(lua) if c.startswith("script select_ui_element")]
    assert clicks == []  # nothing open, nothing pressed blind
    assert "needs a human" in lua.eval("BRIDGE.status")


# --- popups: every game popup is acknowledged, recorded, and told to the ruler -------------

def capture_all(lua):
    """Stand in for the turn loop: every popup capture request is done."""
    for req in lua.root.glob("popup-*.req"):
        req.with_suffix(".done").write_text("")


def opened(lua, scroll, buttons):
    lua.execute(f"FAKE.open_scroll('{scroll}', {{{', '.join(repr(b) for b in buttons)}}}); "
                f"BRIDGE.on_scroll_opened({{ resourceDescription = '{scroll}' }})")


def presses(lua):
    return [c for c in calls(lua) if c.startswith("press ")]


def test_popup_acknowledged_after_a_moment(lua):
    autoplay(lua)
    opened(lua, "conditions_complete_scroll", ["info_button", "close_tick_button"])
    tick(lua, 1)
    assert presses(lua) == []  # left up a moment so a watcher can read it
    tick(lua, 3)
    assert presses(lua) == ["press close_tick_button"]


@pytest.mark.parametrize("scroll, buttons, pressed", [
    ("prebattle_scroll", ["prebattle_fight_button", "prebattle_auto_resolve_button", "prebattle_withdraw_button"],
     "prebattle_auto_resolve_button"),
    ("siege_scroll", ["siege_assault_button", "siege_maintain_button", "siege_end_button"], "siege_maintain_button"),
])
def test_decision_popups_get_a_sensible_default(lua, scroll, buttons, pressed):
    autoplay(lua)
    opened(lua, scroll, buttons)
    tick(lua, 5)
    capture_all(lua)  # the siege panel is screenshotted first (its equipment icons get measured)
    tick(lua, 1)
    assert presses(lua) == [f"press {pressed}"]


@pytest.mark.parametrize("scroll, buttons", [
    ("diplomacy_scroll", ["diplomacy_accept_offer_button", "diplomacy_decline_offer_button"]),
    ("loot_settlement_scroll", ["loot_settlement_sack_button", "loot_settlement_occupy_button"]),
    ("captor_ransom_scroll", ["execute_prisoners_button", "ransom_prisoners_button"]),
])
def test_choice_scrolls_get_no_default_when_they_open(lua, scroll, buttons):
    autoplay(lua)
    opened(lua, scroll, buttons)
    tick(lua, 5)
    assert presses(lua) == []  # the ruler chooses: see the watched-button tests


def choice_request(lua):
    [req] = list(lua.root.glob("popup-*.req"))
    return req, json.loads(req.read_text())


def test_the_ruler_chooses_what_to_do_with_a_captured_city(lua):
    autoplay(lua)
    lua.execute("FAKE.open_scroll('loot_settlement_occupy_button', {})")
    tick(lua, 1)
    tick(lua, 3)
    req, r = choice_request(lua)
    assert r["kind"] == "choice" and r["faction"] == "venice" and r["what"] == "a captured settlement"
    assert r["options"] == ["occupy", "sack", "exterminate"]
    tick(lua, 30)
    assert calls(lua) == []  # still deciding
    req.with_suffix(".answer").write_text("exterminate")
    tick(lua, 1)
    assert calls(lua) == ["script select_ui_element loot_settlement_extermintate_button",  # the game's typo
                          "script simulate_mouse_click lclick_up"]
    assert not req.exists() and not req.with_suffix(".answer").exists()
    assert any("exterminate, your choice" in p for p in lua.eval("BRIDGE.take_popups()").values())


def test_a_generic_decision_nobody_answered_stays_on_screen(lua):
    # clear_messages minimizes a decision, and a minimized decision blocks End Turn unseen
    autoplay(lua)
    lua.execute("BRIDGE.on_message({ eventID = 77 })")
    tick(lua, 5)
    [req] = list(lua.root.glob("popup-*.req"))
    req.with_suffix(".hold").write_text("")  # the turn loop saw a check and an X
    tick(lua, 60)
    assert "script clear_messages " not in calls(lua) and lua.eval("BRIDGE.deciding()")
    tick(lua, 200)  # no answer at all
    assert "script clear_messages " not in calls(lua) and not req.with_suffix(".hold").exists()
    assert any("left unanswered" in p for p in lua.eval("BRIDGE.take_popups()").values())


def test_a_message_is_not_cleared_while_a_decision_is_weighed(lua):
    # live: a plain message's clear_messages minimized Barnaby's adoption mid-answer
    autoplay(lua)
    lua.execute("""
        local c = { fullName = 'Barnaby', age = 30, getTraits = function() return nil end }
        BRIDGE.on_offered_for_adoption({ character = c, faction = FAKE.byName.venice })
        BRIDGE.on_message({ eventID = 39 })
    """)
    tick(lua, 5)
    reqs = {json.loads(p.read_text())["kind"]: p for p in lua.root.glob("popup-*.req")}
    reqs["read"].with_suffix(".done").write_text("")  # the message is read
    tick(lua, 2)
    assert "script clear_messages " not in calls(lua)  # the adoption is still being weighed
    reqs["adoption"].with_suffix(".done").write_text("")  # answered
    tick(lua, 1)
    tick(lua, 1)
    assert "script clear_messages " in calls(lua)


def test_paused_game_ends_no_turn_and_presses_nothing(lua):
    autoplay(lua)
    (lua.root / "paused.txt").write_text("claude usage limit: reached\n")
    lua.execute("FAKE.open_scroll('loot_settlement_occupy_button', {})")
    for _ in range(10):
        tick(lua, 100)  # long past every wait: the turn's, a decision's, a stuck check's
    assert calls(lua) == [] and list(lua.root.glob("popup-*.req")) == []
    assert "paused" in lua.eval("BRIDGE.status")
    (lua.root / "paused.txt").unlink()
    tick(lua, 1)
    tick(lua, 5)
    assert len(list(lua.root.glob("popup-*.req"))) == 1  # the ruler is asked, as usual


def test_stuck_checks_wait_while_the_ruler_chooses(lua):
    autoplay(lua)
    lua.execute("FAKE.campaign.currentFaction = FAKE.byName.hre; "
                "FAKE.open_scroll('ransom_prisoners_button', {})")
    tick(lua, 1)
    tick(lua, 3)
    for _ in range(3):
        tick(lua, 50)  # an AI turn this long would count as stuck
    assert calls(lua) == [] and lua.eval("BRIDGE.deciding()")


def test_besiege_with_assault_storms_and_its_siege_scroll_assaults(lua):
    autoplay(lua)
    lua.execute("FAKE.stances['venice|milan'] = dipRelType.war")
    write_orders(lua, TURN - 1, "venice", [
        {"type": "besiege", "army": "Doge Enrico", "settlement": "Milan", "assault": True}])
    start_turn(lua, "venice")
    assert "siege Doge Enrico Milan true" in calls(lua)
    opened(lua, "siege_scroll", ["siege_assault_button", "siege_maintain_button"])
    tick(lua, 5)
    capture_all(lua)
    tick(lua, 1)
    assert presses(lua) == ["press siege_assault_button"]


def test_plain_besiege_keeps_maintaining(lua):
    autoplay(lua)
    write_orders(lua, TURN - 1, "venice", [{"type": "besiege", "army": "Doge Enrico", "settlement": "Milan"}])
    start_turn(lua, "venice")
    assert "siege Doge Enrico Milan false" in calls(lua)
    opened(lua, "siege_scroll", ["siege_assault_button", "siege_maintain_button"])
    tick(lua, 5)
    capture_all(lua)
    tick(lua, 1)
    assert presses(lua) == ["press siege_maintain_button"]


def test_decision_buttons_on_screen_are_pressed_without_any_event(lua):
    # an AI's offer during its own turn fires no scroll event: the button itself is found
    autoplay(lua)
    lua.execute("FAKE.campaign.currentFaction = FAKE.byName.hre; "
                "FAKE.open_scroll('diplomacy_decline_offer_button', {})")
    tick(lua, 1)
    assert calls(lua) == []
    tick(lua, 3)
    req, r = choice_request(lua)
    assert r["options"] == ["decline", "accept"] and calls(lua) == []
    req.with_suffix(".answer").write_text("accept\n")
    tick(lua, 1)
    assert calls(lua) == ["script select_ui_element diplomacy_accept_offer_button",
                          "script simulate_mouse_click lclick_up"]
    assert any("accept, your choice" in p for p in lua.eval("BRIDGE.take_popups()").values())


def test_a_watched_button_is_pressed_once_while_it_lingers(lua):
    # seen live: the game keeps the offer buttons after an answer; pressing decline again and
    # again made the AI reply each time ("No matter lord, perhaps something else?"). With no
    # answer from the ruler in time, the default is pressed.
    autoplay(lua)
    lua.execute("FAKE.campaign.currentFaction = FAKE.byName.sicily or FAKE.byName.hre; "
                "FAKE.open_scroll('diplomacy_decline_offer_button', {})")
    tick(lua, 5)  # seen
    tick(lua, 5)  # the ruler is asked
    tick(lua, 200)  # no answer in time
    for _ in range(10):
        tick(lua, 5)
    declines = [c for c in calls(lua) if c.endswith("diplomacy_decline_offer_button")]
    assert len(declines) == 1
    assert any("nobody chose in time" in p for p in lua.eval("BRIDGE.take_popups()").values())


def test_answered_offer_screen_gets_the_leftover_closer(lua):
    autoplay(lua)
    lua.execute("FAKE.campaign.currentFaction = FAKE.byName.hre; FAKE.open_scroll('diplomacy_scroll', {''}); "
                "FAKE.open_scroll('diplomacy_decline_offer_button', {})")
    tick(lua, 1)
    tick(lua, 5)
    req, _ = choice_request(lua)
    req.with_suffix(".answer").write_text("decline")
    for _ in range(4):
        tick(lua, 5)
    assert "script select_ui_element diplomacy_ok_button" in calls(lua)


def test_leftover_diplomacy_screen_closed_by_its_seal(lua):
    # live scan (Sicily): the close seal is the unnamed part at the bottom right, 58x65 at
    # (962,703) on the 1024x768 screen; #0 at the top right is the help button
    autoplay(lua)
    lua.execute("""
        local function part(name, x, y, w, h)
            return { elementName = name, xPos = x, yPos = y, xSize = w, ySize = h,
                     execute = function() FAKE.calls[#FAKE.calls + 1] = 'press ' .. name; FAKE.ui.diplomacy_scroll = nil end }
        end
        local parts = { part('help', 978, 4, 42, 42), part('panel', 319, 110, 386, 614), part('seal', 962, 703, 58, 65) }
        FAKE.ui.diplomacy_scroll = { elementName = 'diplomacy_scroll', xPos = 0, yPos = 0, xSize = 1024, ySize = 768,
            subElementsNum = #parts, getSubElement = function(self, i) return parts[i + 1] end }
    """)
    tick(lua, 1)
    tick(lua, 5)
    assert presses(lua) == ["press seal"]


POST_BATTLE = """
    local function part(name, subs)
        return { elementName = name, subElementsNum = #(subs or {}),
                 getSubElement = function(self, i) return subs[i + 1] end,
                 execute = function() FAKE.calls[#FAKE.calls + 1] = 'press ' .. name; FAKE.ui.post_battle_scroll = nil end }
    end
    -- live probe: four unnamed parts; part 3 is the button row, its part 0 the tick
    local row = part('', { part('tick'), part('post_battle_show_stats_button') })
    local parts = { part('help'), part('title'), part('table'), row }
    FAKE.ui.post_battle_scroll = { elementName = 'post_battle_scroll', subElementsNum = 4,
        getSubElement = function(self, i) return parts[i + 1] end }
"""


def test_post_battle_result_closed_by_its_unnamed_tick(lua):
    autoplay(lua)
    lua.execute(POST_BATTLE + "BRIDGE.on_scroll_opened('post_battle_scroll')")
    tick(lua, 5)
    # read for the ruler first (asked live: "Did Rufus survive, how many men did we lose?")
    [req] = list(lua.root.glob("popup-*.req"))
    assert json.loads(req.read_text())["kind"] == "read" and presses(lua) == []
    req.with_suffix(".done").write_text("")
    tick(lua, 1)
    assert presses(lua) == ["press tick"]


def test_a_reload_sweeps_up_result_scrolls_left_open(lua):
    # live: a battle result opened just before a reload sat a minute until stuck recovery
    autoplay(lua)
    lua.execute(POST_BATTLE)
    (lua.root / "reloaded.txt").write_text(f"turn={TURN}\n")
    lua.execute(f"M2TWEOP.toggleConsole = function() end; BRIDGE.setup('{lua.root}')")
    tick(lua, 1)
    assert presses(lua) == []
    tick(lua, 3)
    assert presses(lua) == ["press tick"]


def test_stuck_turn_presses_a_lingering_post_battle_tick(lua):
    # live: a bridge reload forgot the open scroll, and no named button closes it
    autoplay(lua)
    lua.execute("FAKE.campaign.currentFaction = FAKE.byName.hre; " + POST_BATTLE)
    tick(lua, 1)
    tick(lua, 50)
    assert presses(lua) == ["press tick"]


def test_any_result_scroll_is_closed_by_its_button_found_by_shape(lua):
    # the author: "we can't rely on you to close them" (a ransom result left on screen)
    autoplay(lua)
    lua.execute("""
        local function part(name, x, y, w, h, subs)
            return { elementName = name, xPos = x, yPos = y, xSize = w, ySize = h,
                     subElementsNum = #(subs or {}), getSubElement = function(self, i) return subs[i + 1] end,
                     execute = function() FAKE.calls[#FAKE.calls + 1] = 'press ' .. (name ~= '' and name or ('@' .. x)) end }
        end
        local parts = { part('', 900, 40, 42, 42),            -- help, top right: not it
                        part('', 300, 120, 400, 200),         -- the text panel: not button-sized
                        part('message_zoom_to_button', 400, 420, 40, 40),  -- named: never by shape
                        part('', 520, 430, 42, 42) }          -- the close tick
        local el = part('request_assistance_scroll', 250, 20, 520, 460, parts)
        FAKE.ui.request_assistance_scroll = el
    """)
    lua.execute("BRIDGE.on_scroll_opened('request_assistance_scroll')")
    tick(lua, 5)
    assert presses(lua) == ["press @520"]


def test_scan_records_where_unnamed_parts_sit(lua):
    autoplay(lua)
    (lua.root / "ui_names.txt").write_text("some_scroll\n")
    lua.execute("FAKE.ui.some_scroll = { elementName = 'some_scroll', subElementsNum = 2, "
                "getSubElement = function(self, i) return ({ { elementName = '', xPos = 10, yPos = 20, xSize = 30, ySize = 40 }, "
                "{ elementName = 'ok_button', xPos = 1, yPos = 2, xSize = 3, ySize = 4 } })[i + 1] end }")
    lua.execute("BRIDGE.scan_ui('probe')")
    text = (lua.root / "ui_scan-probe.txt").read_text()
    assert "some_scroll: #0 @10,20 30x40, ok_button @1,2 3x4" in text


def test_leftover_diplomacy_screen_is_closed(lua):
    # after an offer is declined the game leaves the diplomacy screen open, with no offer buttons
    autoplay(lua)
    lua.execute("FAKE.open_scroll('diplomacy_scroll', {'', ''})")
    tick(lua, 1)
    assert calls(lua) == []
    tick(lua, 5)
    assert calls(lua)[-2:] == ["script select_ui_element diplomacy_ok_button", "script simulate_mouse_click lclick_up"]
    tick(lua, 5)
    assert calls(lua)[-2:] == ["script select_ui_element close_seal_button", "script simulate_mouse_click lclick_up"]


def test_diplomacy_screen_with_an_offer_is_left_to_the_offer_buttons(lua):
    autoplay(lua)
    lua.execute("FAKE.open_scroll('diplomacy_scroll', {''}); FAKE.open_scroll('diplomacy_decline_offer_button', {})")
    tick(lua, 1)
    tick(lua, 5)
    assert "script select_ui_element diplomacy_ok_button" not in calls(lua)


# --- control file: Claude (or anyone) can reload the bridge inside the running game ----------

def test_control_reload_restarts_lua_and_marks_the_turn(lua):
    # EOP runs a requested restart only while its console is drawn, so the console opens first
    autoplay(lua)
    lua.execute("EVENTS = {}; M2TWEOP.restartLua = function() table.insert(EVENTS, 'restart') end; "
                "M2TWEOP.toggleConsole = function() table.insert(EVENTS, 'console') end")
    (lua.root / "control.txt").write_text("reload\n")
    tick(lua)
    assert list(lua.eval("EVENTS").values()) == ["console", "restart"]
    assert not (lua.root / "control.txt").exists()
    assert (lua.root / "reloaded.txt").read_text().strip() == f"turn={TURN}"


def test_a_stale_reload_marker_leaves_the_console_alone(lua):
    # seen live: a marker left by a reload that never ran opened the console at game start
    lua.execute("TOGGLES = 0; M2TWEOP.toggleConsole = function() TOGGLES = TOGGLES + 1 end")
    (lua.root / "reloaded.txt").write_text("turn=99\n")
    lua.execute(f"BRIDGE.setup('{lua.root}')")
    assert lua.eval("TOGGLES") == 0 and not (lua.root / "reloaded.txt").exists()


def test_leftover_diplomacy_closer_gives_up(lua):
    # seen live: the AI answers each press and the screen reopens; don't loop forever
    autoplay(lua)
    lua.execute("FAKE.open_scroll('diplomacy_scroll', {''})")
    for _ in range(20):
        tick(lua, 5)
    tries = [c for c in calls(lua) if c.startswith("script select_ui_element") and not c.endswith("end_turn")]
    assert len(tries) == 4


def test_after_a_reload_the_console_is_closed_again(lua):
    lua.execute("TOGGLES = 0; M2TWEOP.toggleConsole = function() TOGGLES = TOGGLES + 1 end")
    (lua.root / "reloaded.txt").write_text(f"turn={TURN}\n")
    lua.execute(f"BRIDGE.setup('{lua.root}')")
    assert lua.eval("TOGGLES") == 1


def test_after_a_reload_orders_already_applied_are_not_applied_again(lua):
    write_orders(lua, TURN - 1, "venice", [{"type": "send_gold", "to": "milan", "amount": 100}])
    start_turn(lua, "venice")
    assert lua.eval("FAKE.byName.venice.money") == 4900
    (lua.root / "reloaded.txt").write_text(f"turn={TURN}\n")  # the bridge reloaded mid-turn
    lua.execute(f"BRIDGE.setup('{lua.root}')")
    autoplay(lua)
    tick(lua)
    assert lua.eval("FAKE.byName.venice.money") == 4900
    assert not (lua.root / "reloaded.txt").exists()


def test_control_scan_writes_what_is_open(lua):
    autoplay(lua)
    (lua.root / "ui_names.txt").write_text("mystery_scroll\n")
    lua.execute("FAKE.open_scroll('mystery_scroll', {'ok_button'})")
    (lua.root / "control.txt").write_text("scan mission\n")
    tick(lua)
    assert "mystery_scroll: ok_button" in (lua.root / "ui_scan-mission.txt").read_text()


def test_control_script_runs_a_game_script_command(lua):
    autoplay(lua)
    (lua.root / "control.txt").write_text("script clear_messages\nscript select_ui_element end_turn\n")
    tick(lua)
    assert calls(lua)[:2] == ["script clear_messages ", "script select_ui_element end_turn"]


def test_control_save_is_not_a_command(lua):
    # M2TWEOP.saveGame failed live ("cannot create m2tweop save file"): not offered
    autoplay(lua)
    lua.execute("SAVED = nil; M2TWEOP.saveGame = function(p) SAVED = p end")
    (lua.root / "control.txt").write_text("save parley_qa\n")
    tick(lua)
    assert lua.eval("SAVED") is None
    assert "unknown command" in (lua.root / "parley_bridge.log").read_text()


def test_scrolls_a_watcher_opens_are_left_alone(lua):
    autoplay(lua)
    opened(lua, "finance_scroll", ["close_tick_button"])
    opened(lua, "own_settlement_info_scroll", ["close_tick_button"])
    tick(lua, 30)
    assert presses(lua) == []


def test_game_messages_are_acknowledged_too(lua):
    autoplay(lua)
    lua.execute("FAKE.open_scroll('event_scroll', {'zoom_to_button', 'close_tick_button'}); "
                "BRIDGE.on_message({ eventID = 42 })")
    tick(lua, 5)
    capture_all(lua)
    tick(lua, 2)
    assert presses(lua) == ["press close_tick_button"]


def test_a_message_presses_whichever_game_popup_is_open(lua):
    autoplay(lua)
    lua.execute("FAKE.open_scroll('papal_election_scroll', {'vote_button', 'close_tick_button'}); "
                "BRIDGE.on_message({ eventID = 9 })")
    tick(lua, 5)
    capture_all(lua)
    tick(lua, 2)
    assert presses(lua) == ["press close_tick_button"]


def test_stuck_turn_writes_a_scan_of_open_ui_once(lua):
    autoplay(lua)
    (lua.root / "ui_names.txt").write_text("end_turn\nsuitable_prince_panel\nnot_open_thing\n")
    lua.execute("FAKE.open_scroll('suitable_prince_panel', {'yes_button', 'no_button'}); "
                "FAKE.open_scroll('end_turn', {})")
    write_orders(lua, TURN - 1, "venice", [])
    start_turn(lua, "venice")
    tick(lua)
    tick(lua, 61)
    tick(lua, 2)
    tick(lua, 61)
    scans = list(lua.root.glob("ui_scan-*.txt"))
    assert len(scans) == 1  # once per stuck turn
    text = scans[0].read_text()
    assert "suitable_prince_panel: yes_button, no_button" in text and "end_turn" in text
    assert "not_open_thing" not in text
    assert "press yes_button" not in presses(lua)  # unknown elements are only logged


def test_game_messages_get_clear_messages(lua):
    # seen live: clear_messages closed a riot popup no element name could reach
    autoplay(lua)
    lua.execute("BRIDGE.on_message({ eventID = 77 })")
    tick(lua, 5)
    tick(lua, 31)  # nobody captured it (no turn loop): cleared after the wait anyway
    assert "script clear_messages " in calls(lua)


def test_a_message_is_held_for_capture_then_cleared(lua):
    autoplay(lua)
    lua.execute("BRIDGE.on_message({ eventID = 77 })")
    tick(lua, 5)
    [req] = list(lua.root.glob("popup-*.req"))
    assert json.loads(req.read_text())["kind"] == "read"
    assert "script clear_messages " not in calls(lua)  # held while the turn loop screenshots it
    req.with_suffix(".done").write_text("")
    tick(lua, 2)
    assert "script clear_messages " in calls(lua)
    assert not req.exists()


def test_a_marriage_offer_asks_for_a_decision_with_the_suitor(lua):
    autoplay(lua)
    lua.execute("""
        local suitor = { fullName = 'Jacob Terrett', age = 62, command = 2, loyalty = 3, piety = 4,
                         chivalryAndDread = 0, authority = 0,
                         getTraits = function() return { name = 'Drillmaster', level = 1,
                             nextTrait = { name = 'MixedLoyalties', level = 1 } } end }
        BRIDGE.on_offered_for_marriage({ character = suitor, faction = FAKE.byName.venice })
        BRIDGE.on_message({ eventID = 5 })
    """)
    tick(lua, 5)
    # the offer raises its own request (no message may follow it, seen live); the message
    # is a reading, which the turn loop's fresh look settles once the offer is answered
    reqs = {json.loads(p.read_text())["kind"]: p for p in lua.root.glob("popup-*.req")}
    assert set(reqs) == {"marriage", "read"}
    reqs["read"].with_suffix(".hold").write_text("")  # the turn loop sees the same check and X
    req = reqs["marriage"]
    r = json.loads(req.read_text())
    assert r["kind"] == "marriage" and r["faction"] == "venice"
    assert r["suitor"]["name"] == "Jacob Terrett" and r["suitor"]["age"] == 62
    assert r["suitor"]["command"] == 2 and r["suitor"]["traits"] == ["Drillmaster", "MixedLoyalties"]
    tick(lua, 60)  # a decision may take a while: no clearing it out from under the ruler
    assert "script clear_messages " not in calls(lua)


def test_an_ai_factions_offer_is_not_the_players_popup(lua):
    # live: onOfferedForAdoption fired for the Moors, and their ruler answered England's scroll
    autoplay(lua)
    lua.execute("""
        local c = { fullName = 'Yusuf', age = 30, getTraits = function() return nil end }
        BRIDGE.on_offered_for_adoption({ character = c, faction = FAKE.byName.milan })
        BRIDGE.on_message({ eventID = 6 })
    """)
    tick(lua, 5)
    [req] = list(lua.root.glob("popup-*.req"))
    assert json.loads(req.read_text())["kind"] == "read"


def test_an_offer_with_no_message_still_asks_the_ruler(lua):
    # live: Captain Godwine offered for adoption after his victory, and no message event came
    autoplay(lua)
    lua.execute("""
        local c = { fullName = 'Godwine', age = 21, getTraits = function() return nil end }
        BRIDGE.on_offered_for_adoption({ character = c, faction = FAKE.byName.venice })
    """)
    tick(lua, 5)
    [req] = list(lua.root.glob("popup-*.req"))
    r = json.loads(req.read_text())
    assert r["kind"] == "adoption" and r["suitor"]["name"] == "Godwine" and r["faction"] == "venice"


def test_agent_mission_outcomes_reach_the_rulers_report(lua):
    lua.execute("BRIDGE.on_agent_mission('bribery', { faction = FAKE.byName.venice, missionSuccessLevel = 'not_successful', "
                "character = { fullName = 'Laurence' } }); "
                "BRIDGE.on_agent_mission('assassination', { faction = FAKE.byName.venice, missionSuccessLevel = 'highly_successful', "
                "missionProbability = 62, character = { fullName = 'Iacopo' } }, true); "
                "BRIDGE.on_agent_mission('spying', { faction = FAKE.byName.hre, missionSuccessLevel = 'slightly_successful', "
                "character = { fullName = 'Ulrich' } })")
    r = report_of(lua)
    assert r.agent_results == ["Laurence's bribery: not successful",
                               "Iacopo's assassination: highly successful (chance was 62%)"]
    assert report_of(lua).agent_results == []  # told once


@pytest.mark.parametrize("eop_says, means", [
    ("earthquake", "not successful"), ("flood", "slightly successful"),
    ("horde", "partly successful"), ("storm", "highly successful")])
def test_eops_mislabelled_success_levels_are_translated(lua, eop_says, means):
    # live: EOP 3.3.1 maps the level number through its disaster table (gameHelpers.cpp:276)
    lua.execute(f"BRIDGE.on_agent_mission('bribery', {{ faction = FAKE.byName.venice, "
                f"missionSuccessLevel = '{eop_says}', character = {{ fullName = 'Laurence' }} }})")
    assert report_of(lua).agent_results == [f"Laurence's bribery: {means}"]


def test_faction_news_reaches_the_right_rulers(lua):
    # a riot reaches its own faction; a war reaches both sides; a crusade reaches everyone
    lua.execute("""
        local v, m = FAKE.byName.venice, FAKE.byName.milan
        BRIDGE.on_faction_event('Riots broke out in {settlement}', { faction = v, settlement = { name = 'Venice' } },
                                { 'faction', 'settlement' }, 'own')
        BRIDGE.on_faction_event('{faction} declared war on {targetFaction}', { faction = m, targetFaction = v },
                                { 'faction', 'targetFaction' }, 'both')
        BRIDGE.on_faction_event('A crusade was called against {targetSettlement} ({targetFaction})',
                                { targetSettlement = { name = 'Jerusalem' }, targetFaction = FAKE.byName.hre },
                                { 'targetSettlement', 'targetFaction' }, 'all')
    """)
    assert report_of(lua).news == ["Riots broke out in Venice", "milan declared war on venice",
                                   "A crusade was called against Jerusalem (hre)"]
    assert report_of(lua, "milan").news == ["milan declared war on venice", "A crusade was called against Jerusalem (hre)"]
    assert report_of(lua).news == []  # handed over once


def test_family_roster_in_report_the_dead_included(lua):
    lua.execute("""
        local v = FAKE.byName.venice
        local doge = FAKE.add_named(v, { name = 'Doge Enrico (null)', age = 52, male = true, family = true,
                                         status = 1, type = 'named character' })
        FAKE.add_named(v, { name = 'Pietro of_Rialto', age = 23, male = true, family = true,
                            status = 2, type = 'named character' })
        FAKE.add_named(v, { name = 'Agnese', age = 19, family = true, type = 'princess', parent = doge })
        FAKE.add_named(v, { name = 'Cecilia', age = 36, family = true, alive = false, status = 164 })
    """)
    family = {p.name: p for p in report_of(lua).family}  # live status values: 1, 2, 164
    assert family["Doge Enrico"].role == "leader" and family["Doge Enrico"].kind == "general"
    assert family["Pietro of Rialto"].role == "heir"
    assert family["Agnese"].kind == "princess" and family["Agnese"].parent == "Doge Enrico"
    assert family["Agnese"].spouse is None and family["Agnese"].alive
    cecilia = family["Cecilia"]  # the dead: no reads through stale pointers
    assert not cecilia.alive and cecilia.age == 36 and cecilia.kind is None


@pytest.mark.parametrize("name", ["Doge Enrico", "Doge_Enrico (null)"])
def test_army_ids_are_clean_and_orders_match_either_way(lua, name):
    # live: Henry's army id read "Henry (null)", and a merge into "Henry" failed
    lua.execute("FAKE.byName.venice.stacks[1].leader.namedCharacter.fullName = 'Doge_Enrico (null)'")
    assert "Doge Enrico" in [a.id for a in report_of(lua).armies]
    write_orders(lua, TURN - 1, "venice", [{"type": "move_army", "army": name, "x": 125, "y": 88}])
    start_turn(lua, "venice")
    assert any(c.startswith("moveToTile") for c in calls(lua))


def test_merge_units_fills_the_fullest_and_disbands_the_emptied(lua):
    # the author: "4 hobilar units and some of them are less than half, they need to be full strength"
    lua.execute("""
        local st = FAKE.byName.venice.stacks[1]
        local units = {}
        local function unit(kind, n, max, exp, char)
            local u = { eduEntry = { eduType = kind }, soldierCountStratMap = n, soldierCountStratMapMax = max,
                        exp = exp, armourLVL = 0, weaponLVL = 0, character = char }
            u.setParams = function(self, count, e, a, w) self.soldierCountStratMap, self.exp = count, e end
            u.kill = function(self)
                for i, x in ipairs(units) do if x == self then table.remove(units, i) end end
                st.numOfUnits = #units
            end
            units[#units + 1] = u
        end
        unit("General's Bodyguard", 10, 30, 2, {})  -- never touched
        unit('Hobilars', 30, 40, 1)
        unit('Hobilars', 15, 40, 3)
        unit('Hobilars', 12, 40, 0)
        unit('Hobilars', 8, 40, 2)
        unit('Peasant Archers', 60, 60, 0)
        st.getUnit = function(self, i) return units[i + 1] end
        st.numOfUnits = #units
        FAKE.units = units
    """)
    write_orders(lua, TURN - 1, "venice", [{"type": "merge_units", "army": "Doge Enrico"}])
    start_turn(lua, "venice")
    left = lua.eval("(function() local t = {} for _, u in ipairs(FAKE.units) do "
                    "t[#t + 1] = u.eduEntry.eduType .. ' ' .. u.soldierCountStratMap .. ' exp ' .. u.exp end "
                    "return table.concat(t, ', ') end)()")
    # 65 Hobilars: one full unit of 40 and one of 25; experience averaged by soldiers
    assert left == "General's Bodyguard 10 exp 2, Hobilars 40 exp 1, Hobilars 25 exp 2, Peasant Archers 60 exp 0"
    assert json.loads((turn_dir(lua, TURN - 1, "venice") / "results.json").read_text())[0]["ok"]


def test_disband_releases_the_weakest_of_a_type_never_a_bodyguard(lua):
    # Scratch, live: "Antwerp's surplus militia is the first thing to cut if a disband order appears"
    lua.execute("""
        local st = FAKE.byName.venice.stacks[1]
        local units = {}
        local function unit(kind, n, char)
            local u = { eduEntry = { eduType = kind }, soldierCountStratMap = n, character = char }
            u.kill = function(self)
                for i, x in ipairs(units) do if x == self then table.remove(units, i) end end
                st.numOfUnits = #units
            end
            units[#units + 1] = u
        end
        unit('Town Militia', 60, {})  -- a bodyguard of that type: never released
        unit('Town Militia', 55)
        unit('Town Militia', 20)
        unit('Peasant Archers', 40)
        st.getUnit = function(self, i) return units[i + 1] end
        st.numOfUnits = #units
        FAKE.units = units
    """)
    write_orders(lua, TURN - 1, "venice", [{"type": "disband", "army": "Doge Enrico", "unit": "Town Militia", "count": 1}])
    start_turn(lua, "venice")
    left = lua.eval("(function() local t = {} for _, u in ipairs(FAKE.units) do "
                    "t[#t + 1] = u.eduEntry.eduType .. ' ' .. u.soldierCountStratMap end return table.concat(t, ', ') end)()")
    assert left == "Town Militia 60, Town Militia 55, Peasant Archers 40"


def test_merge_units_stops_when_the_game_ignores_the_write(lua):
    # live: setParams didn't take on a garrison's units; the old loop spun forever and hung the game
    lua.execute("""
        local st = FAKE.byName.venice.stacks[1]
        local units = {}
        for _, n in ipairs({ 30, 15, 8 }) do
            local u = setmetatable({}, {
                __index = { eduEntry = { eduType = 'Hobilars' }, soldierCountStratMap = n,
                            soldierCountStratMapMax = 40, exp = 0, armourLVL = 0, weaponLVL = 0,
                            kill = function() end },
                __newindex = function() end })  -- every write ignored
            units[#units + 1] = u
        end
        st.getUnit = function(self, i) return units[i + 1] end
        st.numOfUnits = #units
    """)
    write_orders(lua, TURN - 1, "venice", [{"type": "merge_units", "army": "Doge Enrico"}])
    start_turn(lua, "venice")  # returns at all: no hang
    [r] = json.loads((turn_dir(lua, TURN - 1, "venice") / "results.json").read_text())
    assert not r["ok"] and "didn't take the merge" in r["reason"]


def test_stance_changes_are_logged_with_whose_turn_it_was(lua):
    end_turn(lua, "hre")
    lua.execute("FAKE.stances['venice|hre'] = dipRelType.peace")
    end_turn(lua, "hre")  # hre has no LLM ruler: its AI's change stands
    log = (lua.root / "parley_bridge.log").read_text()
    assert "stance: hre|venice war -> peace (seen at the end of hre's turn 3)" in log
    # both sides hear it in their next report, with whose turn it was (the author: rulers must know
    # everything that goes on); venice's report is written at venice's turn end
    end_turn(lua, "venice")
    news = json.loads((turn_dir(lua, TURN, "venice") / "state.json").read_text())["stance_changes"]
    # the actor first (live: the HRE's ruler read its own AI's war as England's breach)
    assert news == ["hre's own game AI, not you and not any ruler, changed hre and you from war to peace on turn 3"]


def test_a_reload_still_catches_the_first_stance_change(lua):
    # live: the first turn after a reload saw no change, and an AI war slipped through
    lua.execute("FAKE.stances['venice|milan'] = dipRelType.war")  # milan's AI declares war
    end_turn(lua, "milan")  # no earlier turn end since setup (a fresh reload)
    assert lua.eval("FAKE.stances['venice|milan']") == lua.eval("dipRelType.peace")


def test_a_reload_mid_turn_starts_from_the_last_turn_ends_stances(lua):
    # live: a reload during the HRE's turn, right after its AI declared war, took the war as
    # the starting point and never undid it
    end_turn(lua, "venice")  # stances saved at a turn end: venice|milan peace
    lua.execute("FAKE.stances['venice|milan'] = dipRelType.war")  # milan's AI declares war...
    lua.execute(f"BRIDGE.setup('{lua.root}')")  # ...and the bridge reloads mid-turn
    end_turn(lua, "milan")
    assert lua.eval("FAKE.stances['venice|milan']") == lua.eval("dipRelType.peace")


def test_the_human_slots_turn_is_never_reverted(lua):
    # live: the human slot's ruler made peace, a reload lost the order's record, and the
    # peace was undone as if England's (nonexistent) game AI had made it
    end_turn(lua, "venice")  # venice is the human slot in the fake game
    lua.execute("FAKE.stances['venice|milan'] = dipRelType.war")
    end_turn(lua, "venice")
    assert lua.eval("FAKE.stances['venice|milan']") == lua.eval("dipRelType.war")


def test_whose_stance_order_it_was_survives_a_reload(lua):
    end_turn(lua, "milan")
    write_orders(lua, TURN - 1, "milan", [{"type": "set_stance", "to": "venice", "stance": "war"}])
    start_turn(lua, "milan")
    lua.execute(f"BRIDGE.setup('{lua.root}')")  # a reload after the order, before the turn end
    end_turn(lua, "milan")
    assert lua.eval("FAKE.stances['venice|milan']") == lua.eval("dipRelType.war")  # the order stands


def test_a_rulers_own_game_ai_cannot_make_war_or_peace(lua):
    # the author: "if the llm is set to declare war or peace then the ai shouldn't be able to"
    # (live: France's and the HRE's AI declared war every turn their rulers made peace)
    end_turn(lua, "milan")  # milan has an LLM ruler
    lua.execute("FAKE.stances['venice|milan'] = dipRelType.war")  # milan's game AI declares war
    end_turn(lua, "milan")
    assert lua.eval("FAKE.stances['venice|milan']") == lua.eval("dipRelType.peace")
    end_turn(lua, "venice")
    [news] = json.loads((turn_dir(lua, TURN, "venice") / "state.json").read_text())["stance_changes"]
    assert news.startswith("milan's own game AI, not you and not any ruler, changed milan and you from peace to war")
    assert news.endswith("it was put back to peace at once, since milan's ruler alone makes war and peace for milan")
    end_turn(lua, "milan")
    lua.execute("FAKE.stances['venice|milan'] = dipRelType.war")
    end_turn(lua, "milan")
    [mine] = json.loads((turn_dir(lua, TURN, "milan") / "state.json").read_text())["stance_changes"][-1:]
    assert mine.startswith("YOUR OWN game AI, not venice and not any ruler, changed venice and you from peace to war")


def test_a_stance_change_by_order_names_whose_order(lua):
    end_turn(lua, "milan")
    write_orders(lua, TURN - 1, "milan", [{"type": "set_stance", "to": "venice", "stance": "war"}])
    start_turn(lua, "milan")
    end_turn(lua, "milan")
    end_turn(lua, "venice")
    news = json.loads((turn_dir(lua, TURN, "venice") / "state.json").read_text())["stance_changes"]
    assert news == ["milan (milan) and you went from peace to war on milan's turn 3, by milan's order"]


def test_report_lists_land_crossings_near_you(lua):
    # the author: "the game should inform llms of crossings" (Scratch planned ships for Dublin, unaware
    # he could walk); EOP tile.isLandConnection marks the green-arrow straits
    lua.execute("""
        local base = FAKE.stratMap.getTile
        FAKE.stratMap.getTile = function(x, y)
            local t = base(x, y)
            t.regionID = x < 125 and 10 or 11
            t.isLandConnection = (y == 95 and (x == 124 or x == 125))
            t.isLand = t.isLandConnection and 0 or 1
            return t
        end
        FAKE.stratMap.mapWidth, FAKE.stratMap.mapHeight = 140, 100
    """)
    r = report_of(lua)
    [c] = r.crossings
    assert (c.x, c.y) in ((124, 95), (125, 95)) and c.regions == ["region10", "region11"]


def test_report_gives_settlement_tiles_ports_training_and_income_items(lua):
    write_orders(lua, TURN - 1, "venice", [])
    (lua.root / "training.json").write_text(json.dumps(
        [{"faction": "venice", "settlement": "Venice", "unit": "Spear Militia", "edu": 7, "ready": 5}]))
    lua.execute("FAKE.ports[10] = { x = 121, y = 90, port = { name = 'Venice port' } }")
    r = report_of(lua)
    venice = next(s for s in r.settlements if s.id == "Venice")
    assert (venice.x, venice.y, venice.port_x, venice.port_y) == (120, 88, 121, 90)
    assert venice.training[0].unit == "Spear Militia" and venice.training[0].ready_turn == 5
    assert r.income_parts["taxes"] == 1500 and r.income_parts["army upkeep"] == -700


def test_someone_dead_to_us_but_alive_elsewhere_is_found(lua):
    lua.execute("""
        FAKE.add_named(FAKE.byName.venice, { name = 'Captain Godwine', age = 21, alive = false })
        FAKE.add_named(FAKE.byName.slave, { name = 'Captain Godwine', age = 21, type = 'named character' })
        FAKE.add_named(FAKE.byName.venice, { name = 'Cecilia', age = 36, family = true, alive = false })
    """)
    family = {p.name: p for p in report_of(lua).family}
    assert family["Captain Godwine"].now_serves == "slave"
    assert family["Cecilia"].now_serves is None


def test_character_events_reach_the_report_once(lua):
    lua.execute("BRIDGE.on_character_event('was the target of an assassination attempt', "
                "{ faction = FAKE.byName.venice, character = { fullName = 'Cecilia' } }); "
                "BRIDGE.on_character_event('was killed in battle', "
                "{ stratCharacter = { namedCharacter = { fullName = 'Heinrich', faction = FAKE.byName.hre } } })")
    assert report_of(lua).character_events == ["Cecilia was the target of an assassination attempt"]
    assert report_of(lua).character_events == []
    lua.execute("BRIDGE.on_character_event('was struck by a disaster', "
                "{ faction = FAKE.byName.venice, character = { fullName = 'Marco' }, disasterType = 'plague' }, true)")
    assert report_of(lua).character_events == ["Marco was struck by a disaster: plague"]


def test_building_already_queued_is_refused(lua):
    control(lua)
    write_orders(lua, TURN - 1, "venice", [{"type": "build", "settlement": "Venice", "building": "wooden_wall"}])
    start_turn(lua, "venice")
    assert "already in Venice's queue" in results(lua)[0]["reason"]


def test_popups_are_logged_with_their_buttons(lua):
    autoplay(lua)
    opened(lua, "conditions_complete_scroll", ["info_button", "close_tick_button"])
    assert "conditions_complete_scroll: info_button, close_tick_button" in (lua.root / "parley_bridge.log").read_text()


def test_the_human_slots_ruler_hears_about_popups(lua):
    autoplay(lua)
    opened(lua, "siege_scroll", ["siege_maintain_button"])
    lua.execute("BRIDGE.on_message({ eventID = 42 })")
    tick(lua, 5)
    capture_all(lua)
    tick(lua, 2)
    r = report_of(lua)
    assert any("siege" in p and "siege_maintain_button" in p for p in r.popups)
    assert any("message 42" in p for p in r.popups)
    assert report_of(lua).popups == []  # told once


def test_no_popup_handling_without_autoplay(lua):
    opened(lua, "conditions_complete_scroll", ["close_tick_button"])
    tick(lua, 30)
    assert presses(lua) == []


def test_autoplay_dismisses_a_popup_that_stalls_an_ai_turn(lua):
    autoplay(lua)
    lua.execute("FAKE.campaign.currentFaction = FAKE.byName.milan")
    lua.execute("FAKE.open_scroll('prebattle_auto_resolve_button', {})")
    tick(lua)
    tick(lua, 29)
    assert presses(lua) == [] and "prebattle_auto_resolve_button" not in " ".join(calls(lua)[1:])
    tick(lua, 2)  # milan's turn hasn't moved for 30 s: an offer to the human, or a battle
    assert "script select_ui_element prebattle_auto_resolve_button" in calls(lua)


def test_the_humans_ruler_plan_shows_on_screen(lua):
    autoplay(lua)
    (turn_dir(lua, TURN - 1, "venice") / "orders.json").write_text(json.dumps(
        {"protocol": 1, "game_id": "g1", "turn": 2, "faction": "venice", "orders": [],
         "note": "Fortify Ragusa, then court Milan."}))
    start_turn(lua, "venice")
    assert lua.eval("BRIDGE.plan") == "venice: Fortify Ragusa, then court Milan."


def test_autoplay_tick_never_raises(lua):
    autoplay(lua)
    lua.execute("FAKE.campaign.currentFaction = nil; gameDataAll.get = function() error('menu') end")
    tick(lua)
    lua.execute("BRIDGE.setup = nil")  # whatever state: still no error


def test_named_character_with_a_space_is_a_general(lua):
    lua.execute("FAKE.byName.hre.characters[1].getTypeName = function() return 'named character' end")
    assert [a.id for a in report_of(lua).seen_agents] == ["Ulrich"]


def test_agent_order_wrong_kind_rejected(lua):
    write_orders(lua, TURN - 1, "venice", [{"type": "assassinate", "agent": "Marco", "target": "Ulrich"}])
    start_turn(lua, "venice")
    r = results(lua)[0]
    assert not r["ok"] and "not an assassin" in r["reason"] and calls(lua) == []


def test_agent_order_target_out_of_sight_rejected(lua):
    write_orders(lua, TURN - 1, "venice", [
        {"type": "assassinate", "agent": "Iacopo", "target": "Duke Ottone"},
        {"type": "sabotage", "agent": "Iacopo", "settlement": "Milan"},
    ])
    start_turn(lua, "venice")
    assert [("not in sight" in r["reason"]) for r in results(lua)] == [True, True]
    assert calls(lua) == []


def test_agent_order_unknown_agent_rejected(lua):
    write_orders(lua, TURN - 1, "venice", [{"type": "spy", "agent": "Ulrich", "target": "Innsbruck"}])
    start_turn(lua, "venice")
    r = results(lua)[0]
    assert not r["ok"] and "unknown agent" in r["reason"]


def test_cannot_sabotage_own_settlement(lua):
    write_orders(lua, TURN - 1, "venice", [{"type": "sabotage", "agent": "Iacopo", "settlement": "Venice"}])
    start_turn(lua, "venice")
    assert not results(lua)[0]["ok"] and calls(lua) == []
