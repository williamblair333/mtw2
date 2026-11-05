"""The game-side bridge (lua/parley_bridge.lua), run in LuaJIT via lupa against a fake game."""

import json
from pathlib import Path

import pytest
from lupa.luajit21 import LuaRuntime

from parley.prompt import build_prompt
from parley.protocol import Crossing, StateReport

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


DOGE_BY_MILAN = "local l = FAKE.byName.venice.stacks[1].leader; l.xCoord, l.yCoord = 101, 91"


def test_army_orders(lua):
    lua.execute(DOGE_BY_MILAN)  # a siege is ordered from the next tile
    write_orders(lua, TURN - 1, "venice", [
        {"type": "march_on", "army": "Doge Enrico", "target_settlement": "Ragusa"},
        {"type": "besiege", "army": "Doge Enrico", "settlement": "Milan"},
        {"type": "withdraw", "army": "Doge Enrico", "to_settlement": "Ragusa"},
    ])
    start_turn(lua, "venice")
    assert calls(lua) == ["moveToTile Doge Enrico 140 80", "siege Doge Enrico Milan false",
                          "moveToTile Doge Enrico 140 80"]


def test_an_army_renamed_by_its_own_move_is_still_found_this_turn(lua):
    # live (2026-10-29, turn 117): France moved three captains, then merge_units on each was "unknown"
    control(lua)
    lua.execute("""
        local leader = FAKE.byName.venice.stacks[1].leader
        local move = leader.moveToTile
        leader.moveToTile = function(self, x, y)
            move(self, x, y)
            self.namedCharacter.fullName = 'Captain Renamed'  -- the game names a new captain
            for _, c in ipairs(FAKE.byName.venice.characters) do
                if c.namedCharacter.fullName == 'Doge Enrico' then c.namedCharacter.fullName = 'Captain Renamed' end
            end
        end
    """)
    write_orders(lua, TURN - 1, "venice", [{"type": "move_army", "army": "Doge Enrico", "x": 100, "y": 60},
                                           {"type": "merge_units", "army": "Doge Enrico"}])
    start_turn(lua, "venice")
    r = results(lua)
    assert r[0]["ok"] and "unknown army" not in (r[1].get("reason") or "")


@pytest.mark.parametrize("order", [
    {"type": "withdraw", "army": "Doge Enrico", "to_settlement": "Venice"},
    {"type": "move_army", "army": "Doge Enrico"},
])
def test_entering_your_own_settlement_past_twenty_units_is_refused(lua, order):
    # live (2026-10-29, the turn audit): Henry (8) onto Edinburgh (15) came back "done", stayed out
    control(lua)
    lua.execute("FAKE.settlements.Venice.army.numOfUnits = 15; FAKE.byName.venice.stacks[1].numOfUnits = 8")
    if order["type"] == "move_army":
        order = {**order, "x": lua.eval("FAKE.settlements.Venice.xCoord"), "y": lua.eval("FAKE.settlements.Venice.yCoord")}
    write_orders(lua, TURN - 1, "venice", [order])
    start_turn(lua, "venice")
    r = results(lua)[0]
    assert not r["ok"] and "garrison has 15 units and this army 8: 23, over the 20" in r["reason"]
    assert not any(c.startswith("moveToTile") for c in calls(lua))


def test_entering_your_own_settlement_within_twenty_units_goes_ahead(lua):
    control(lua)
    lua.execute("FAKE.settlements.Venice.army.numOfUnits = 5; FAKE.byName.venice.stacks[1].numOfUnits = 8")
    write_orders(lua, TURN - 1, "venice", [{"type": "withdraw", "army": "Doge Enrico", "to_settlement": "Venice"}])
    start_turn(lua, "venice")
    assert results(lua)[0]["ok"] and any(c.startswith("moveToTile Doge Enrico") for c in calls(lua))


def test_an_army_whose_captain_was_renamed_is_found_by_its_reported_tile(lua):
    # live (2026-10-29): France's 13 units at (93,129) were Captain Georges in the report and
    # Captain Clement when the orders ran; 25 orders failed as "unknown army"
    control(lua)
    end_turn(lua, "venice")  # writes the report the ruler reads (Doge Enrico's army on its tile)
    lua.execute("FAKE.byName.venice.stacks[1].leader.namedCharacter.fullName = 'Captain Clement'; "
                "for _, c in ipairs(FAKE.byName.venice.characters) do "
                "  if c.namedCharacter.fullName == 'Doge Enrico' then c.namedCharacter.fullName = 'Captain Clement' end end")
    (turn_dir(lua, TURN, "venice") / "orders.json").write_text(json.dumps(
        {"protocol": 1, "game_id": "g1", "turn": TURN, "faction": "venice",
         "orders": [{"type": "move_army", "army": "Doge Enrico", "x": 100, "y": 60}]}))
    lua.execute(f"FAKE.campaign.turnNumber = {TURN + 1}")
    start_turn(lua, "venice")
    r = json.loads((turn_dir(lua, TURN, "venice") / "results.json").read_text())[0]
    # the fake's moveToTile logs the name it was made with; found at all means found by its tile
    assert r["ok"] and "moveToTile Doge Enrico 100 60" in calls(lua)


def test_without_the_report_a_renamed_captain_stays_unknown(lua):
    control(lua)
    lua.execute("FAKE.byName.venice.stacks[1].leader.namedCharacter.fullName = 'Captain Clement'; "
                "for _, c in ipairs(FAKE.byName.venice.characters) do "
                "  if c.namedCharacter.fullName == 'Doge Enrico' then c.namedCharacter.fullName = 'Captain Clement' end end")
    write_orders(lua, TURN - 1, "venice", [{"type": "move_army", "army": "Doge Enrico", "x": 100, "y": 60}])
    start_turn(lua, "venice")  # no report in that folder: nothing to match the tile against
    assert "unknown army 'Doge Enrico'" in results(lua)[0]["reason"]


def test_garrison_cannot_march(lua):
    write_orders(lua, TURN - 1, "venice", [{"type": "march_on", "army": "garrison:Venice", "target_settlement": "Milan"}])
    start_turn(lua, "venice")
    r = json.loads((turn_dir(lua, TURN - 1, "venice") / "results.json").read_text())[0]
    assert not r["ok"] and "no general" in r["reason"]


def test_a_garrison_move_takes_its_general_and_says_the_garrison_stays(lua):
    # live (2026-10-29, York): moveToTile walked the garrison's general out alone; the units stayed
    control(lua)
    lua.execute("FAKE.general_in_town(FAKE.byName.venice, 'Marco Polo', FAKE.settlements.Venice)")
    write_orders(lua, TURN - 1, "venice", [{"type": "move_army", "army": "garrison:Venice", "x": 100, "y": 60}])
    start_turn(lua, "venice")
    r = results(lua)[0]
    assert r["ok"] and "splitArmy venice NE Bodyguard 119 87" in calls(lua), (r, calls(lua))
    assert "moveToTile Marco Polo 100 60" in calls(lua), calls(lua)
    assert "only Marco Polo and his bodyguard march out; the garrison stays in Venice" in r["note"]
    assert "merge_armies garrison:Venice into Marco Polo" in r["note"]


# --- a general inside a town leaves it by EOP's factionStruct:splitArmy (LuaDocs.lua:9455-9459) ----
# Live (run8 turn 18, Robert in Paris; QA field garrison_general_leaves 10-30 22:59/23:18/23:29,
# Rufus in London): moveToTile on a general inside a settlement did nothing and came back "done".

# (order, the tile beside Venice (120,88) he splits onto, the target he walks on to from there)
def _garrison_orders():
    return [
        ({"type": "move_army", "army": "garrison:Venice", "x": 110, "y": 88}, "119 88", "110 88"),
        ({"type": "move_army", "army": "Captain Robin", "x": 110, "y": 88}, "119 88", "110 88"),
        ({"type": "march_on", "army": "garrison:Venice", "target_settlement": "Milan"}, "119 89", "100 90"),
        ({"type": "withdraw", "army": "garrison:Venice", "to_settlement": "Ragusa"}, "121 87", "140 80"),
        ({"type": "besiege", "army": "garrison:Venice", "settlement": "Milan"}, "119 89", "100 90"),
        ({"type": "board", "who": "garrison:Venice", "fleet": "Admiral Polo"}, "119 89", "118 92"),
    ]


@pytest.mark.parametrize("order, step, tile", _garrison_orders())
def test_a_general_in_a_town_leaves_by_a_split_with_his_bodyguard(lua, order, step, tile):
    # live (run9 turns 22-27, Robert in Caen): a split straight to a far target did nothing; he
    # splits onto the tile beside the town and walks on from there
    control(lua)
    done, r = issue(lua, order, f"{ROBIN_IN_VENICE}; {FLEET}")
    assert r["ok"], r
    assert f"splitArmy venice NE Bodyguard {step}" in done, done
    assert done.index(f"splitArmy venice NE Bodyguard {step}") < done.index(f"moveToTile Captain Robin {tile}"), done
    assert "only Captain Robin and his bodyguard march out; the garrison stays in Venice" in r["note"], r
    x, y = (int(v) for v in step.split())
    robin = lua.eval("(function() for _, c in ipairs(FAKE.byName.venice.characters) do "
                     "if c.namedCharacter.fullName == 'Captain Robin' then return c end end end)()")
    assert (robin.xCoord, robin.yCoord) == (x, y)


def test_the_split_hands_over_the_stacks_own_unit_not_character_bodyguards(lua):
    # live QA field 10-31 00:01:21: fac:splitArmy({ leader.bodyguards }, ...) for Simon Townsend in
    # Nottingham returned and he was still inside a turn later. EOP's example builds the table from
    # armyStruct:getUnit(i); the fake (strict to that) ignores a unit no stack holds, as live
    control(lua)
    lua.execute(f"FAKE.reset(); BRIDGE.setup('{lua.root}'); {ROBIN_IN_VENICE}")
    lua.execute("local fac = FAKE.byName.venice; local robin = fac.characters[#fac.characters]; "
                "fac:splitArmy({ robin.bodyguards }, 110, 88)")
    assert lua.eval("FAKE.byName.venice.characters[#FAKE.byName.venice.characters].xCoord") == 120  # the old call: stays
    done, r = issue(lua, {"type": "move_army", "army": "Captain Robin", "x": 110, "y": 88}, ROBIN_IN_VENICE)
    assert r["ok"] and "splitArmy venice NE Bodyguard 119 88" in done, (r, done)
    assert lua.eval("FAKE.byName.venice.characters[#FAKE.byName.venice.characters].xCoord") == 119
    log = bridge_log(lua)
    assert "splits out of Venice with his bodyguard onto (119,88) toward (110,88) (his unit in the town's stack)" in log
    assert "after the split Captain Robin stands at (119,88)" in log and "still in Venice" not in log
    # the garrison's own units stay behind
    assert lua.eval("FAKE.byName.venice.stacks[2].numOfUnits") == 2


def test_a_split_that_leaves_him_in_the_town_is_logged(lua):
    # the evidence for the next live run: where he stands right after the call
    control(lua)
    done, r = issue(lua, {"type": "move_army", "army": "Captain Robin", "x": 110, "y": 88},
                    f"{ROBIN_IN_VENICE}; local fac = FAKE.byName.venice; "
                    "fac.splitArmy = function(self, units, x, y) FAKE.calls[#FAKE.calls + 1] = 'splitArmy noop' end")
    assert "splitArmy noop" in done
    assert "after the split Captain Robin stands at (120,88), still in Venice" in bridge_log(lua)


def test_the_fake_split_to_a_far_tile_does_nothing_as_live(lua):
    # live run9 turns 22-27: Robert's splits out of Caen to 11 and 18 tiles off left him inside
    lua.execute(f"FAKE.reset(); BRIDGE.setup('{lua.root}'); {ROBIN_IN_VENICE}")
    lua.execute("local fac = FAKE.byName.venice; local robin = fac.characters[#fac.characters]; "
                "local mine; for _, st in ipairs(fac.stacks) do for _, u in ipairs(st.units or {}) do "
                "if u.character == robin then mine = u end end end; assert(mine); "
                "fac:splitArmy({ mine }, 110, 88)")
    assert lua.eval("FAKE.byName.venice.characters[#FAKE.byName.venice.characters].xCoord") == 120


def test_the_step_out_skips_a_tile_someone_stands_on(lua):
    control(lua)
    done, r = issue(lua, {"type": "move_army", "army": "Captain Robin", "x": 110, "y": 88},
                    f"{ROBIN_IN_VENICE}; FAKE.byName.venice.characters[1].xCoord = 119; "
                    "FAKE.byName.venice.characters[1].yCoord = 88")
    assert r["ok"] and not any(c.startswith("splitArmy venice NE Bodyguard 119 88") for c in done), done
    assert "splitArmy venice NE Bodyguard 119 87" in done or "splitArmy venice NE Bodyguard 119 89" in done, done


def test_no_free_tile_beside_the_town_refuses_instead_of_a_split_that_does_nothing(lua):
    # live QA 10-31 08:16:37 and 08:18:37: every tile beside London was taken, the split went straight
    # to the far target (the run9 split that does nothing) and the order said ok; Edgar Stanley stayed
    control(lua)
    # someone on every tile beside Venice
    blocked = ("for dx = -1, 1 do for dy = -1, 1 do if dx ~= 0 or dy ~= 0 then "
               "FAKE.add_character(FAKE.byName.milan, 'Spy' .. dx .. dy, 'spy', 120 + dx, 88 + dy) "
               "end end end")
    done, r = issue(lua, {"type": "move_army", "army": "Captain Robin", "x": 110, "y": 88},
                    f"{ROBIN_IN_VENICE}; {blocked}")
    assert not r["ok"] and "Captain Robin can't step out of Venice: no free land tile beside it" in r["reason"], r
    assert not any(c.startswith(("splitArmy", "moveToTile Captain Robin")) for c in done), done


def test_a_target_beside_the_town_is_split_onto_with_no_further_walk(lua):
    control(lua)
    done, r = issue(lua, {"type": "move_army", "army": "Captain Robin", "x": 119, "y": 87}, ROBIN_IN_VENICE)
    assert r["ok"] and "splitArmy venice NE Bodyguard 119 87" in done, done
    assert not any(c.startswith("moveToTile Captain Robin") for c in done), done


BESIEGED = ("local v = FAKE.settlements.Venice; v.siegesNum = 1; "
            "v.getSiege = function(self, i) return { besieger = { leader = { namedCharacter = "
            "{ fullName = 'Captain Garnot', faction = { name = 'france' } } } } } end")


@pytest.mark.parametrize("order", [o for o, _, _ in _garrison_orders()])
def test_nobody_marches_out_of_a_besieged_town(lua, order):
    # live run9 turns 22-35: splits out of Caen under siege (Luquin, then Garnot) did nothing
    control(lua)
    done, r = issue(lua, order, f"{ROBIN_IN_VENICE}; {FLEET}; {BESIEGED}")
    assert not r["ok"] and "Venice is under siege by Captain Garnot (france)" in r["reason"], r
    assert '{"type": "attack", "army": "garrison:Venice", "target": "Captain Garnot", ' \
           '"target_faction": "france"}' in r["reason"], r
    assert not any(c.startswith(("splitArmy", "moveToTile Captain Robin")) for c in done), done


def test_the_fake_split_refuses_what_is_not_a_unit(lua):
    lua.execute(f"FAKE.reset(); BRIDGE.setup('{lua.root}')")
    with pytest.raises(Exception, match="no matching function call"):
        lua.execute("FAKE.byName.venice:splitArmy({ { eduEntry = { eduType = 'x' } } }, 110, 88)")


@pytest.mark.parametrize("order", [o for o, _, _ in _garrison_orders()])
def test_a_general_in_a_town_with_no_moves_left_is_refused_and_not_split(lua, order):
    # live QA field 10-30 23:59:22: the no_moves_left case's general went out by a split. Every move
    # path checks M.no_moves_left before it moves him, M.walk too
    control(lua)
    done, r = issue(lua, order, f"{ROBIN_IN_VENICE}; {FLEET}; FAKE.set_moves('Captain Robin', 0, 0)")
    assert not r["ok"] and "has no moves left this turn" in r["reason"], r
    assert not any(c.startswith(("splitArmy", "moveToTile Captain Robin")) for c in done), done


def test_walk_itself_refuses_a_mover_with_no_moves_left(lua):
    lua.execute(f"FAKE.reset(); BRIDGE.setup('{lua.root}'); {ROBIN_IN_VENICE}; "
                "FAKE.set_moves('Captain Robin', 0, 0)")
    town, why = lua.execute("local fac = FAKE.byName.venice; "
                            "return BRIDGE.walk(fac, fac.characters[#fac.characters], 110, 88)")
    assert town is None and "has no moves left this turn" in why
    assert not any(c.startswith(("splitArmy", "moveToTile")) for c in calls(lua))


def test_a_general_outside_a_town_still_moves_by_move_to_tile(lua):
    control(lua)
    done, r = issue(lua, {"type": "move_army", "army": "Doge Enrico", "x": 110, "y": 88})
    assert r["ok"] and "moveToTile Doge Enrico 110 88" in done and not any(c.startswith("splitArmy") for c in done)
    assert "note" not in r or not r["note"]


def test_a_split_that_raises_falls_back_to_move_to_tile_and_is_logged(lua):
    # never block an order the game may still carry out
    control(lua)
    done, r = issue(lua, {"type": "move_army", "army": "garrison:Venice", "x": 110, "y": 88},
                    f"{ROBIN_IN_VENICE}; FAKE.split_raises = true")
    assert r["ok"] and "moveToTile Captain Robin 110 88" in done, (r, done)
    assert "splitArmy for Captain Robin failed" in bridge_log(lua)


def _next_turn_moves_not_made(lua):
    end_turn(lua, "venice")
    turn_dir(lua, TURN + 1, "venice").mkdir(parents=True, exist_ok=True)
    lua.execute(f"FAKE.campaign.turnNumber = {TURN + 1}")
    start_turn(lua, "venice")
    end_turn(lua, "venice")
    return StateReport.model_validate_json((turn_dir(lua, TURN + 1, "venice") / "state.json").read_text()).moves_not_made


def test_the_general_who_split_out_is_not_reported_as_still_in_the_town(lua):
    # the QA case's expectation: the next report has him on the tile he was sent to, not in the town
    control(lua)
    lua.execute(ROBIN_IN_VENICE)
    write_orders(lua, TURN - 1, "venice", [{"type": "move_army", "army": "garrison:Venice", "x": 110, "y": 88}])
    start_turn(lua, "venice")
    assert results(lua)[0]["ok"]
    assert _next_turn_moves_not_made(lua) == []
    report = StateReport.model_validate_json((turn_dir(lua, TURN + 1, "venice") / "state.json").read_text())
    robin = next(a for a in report.armies if a.id == "Captain Robin")
    assert (robin.x, robin.y) == (119, 88) and not robin.in_settlement  # out; the fake's moveToTile only records


def test_a_march_on_from_a_town_is_checked_by_the_generals_name(lua):
    # the garrison stays behind by design: the check must follow him, not "garrison:Venice"
    control(lua)
    lua.execute(ROBIN_IN_VENICE + "; FAKE.split_raises = true")  # moveToTile: he stays put, as live
    write_orders(lua, TURN - 1, "venice", [{"type": "march_on", "army": "garrison:Venice", "target_settlement": "Milan"}])
    start_turn(lua, "venice")
    unmade = _next_turn_moves_not_made(lua)
    assert [m.id for m in unmade] == ["Captain Robin"], unmade


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


def bridge_log(lua) -> str:
    p = lua.root / "parley_bridge.log"
    return p.read_text() if p.exists() else ""


def test_foreign_army_in_sight_lists_its_units(lua):
    (heinrich,) = report_of(lua).visible_enemies
    assert [(u.type, u.soldiers) for u in heinrich.troops] == [
        ("Venetian Heavy Infantry", 40), ("Mailed Knights", 20)]


def test_foreign_troops_capped_and_each_read_guarded(lua):
    lua.execute("""
        local st = FAKE.byName.hre.stacks[1]
        local units = {}
        for i = 1, 30 do units[i] = { eduEntry = { eduType = 'Peasants' }, soldierCountStratMap = 60 } end
        units[2].eduEntry = nil  -- one broken unit is skipped, not fatal
        st.units, st.numOfUnits = units, 30
    """)
    (heinrich,) = report_of(lua).visible_enemies
    assert len(heinrich.troops) == 19 and heinrich.units == 30  # 20 read, 1 broken


def test_sight_uses_radius_when_no_visibility_call(lua):
    r = report_of(lua)
    assert [a.id for a in r.visible_enemies] == ["Heinrich"]
    assert "sight: radius" in bridge_log(lua)
    assert "sight: getTileVisibility" not in bridge_log(lua)


def test_sight_uses_tile_visibility_when_present(lua):
    lua.execute("""
        tileVisibility = { notVisible = 1, wasVisible = 2, visible = 3 }
        local hre = FAKE.byName.hre
        FAKE.byName.venice.getTileVisibility = function(self, x, y)
            local c = hre.stacks[1].leader
            return (c.xCoord == x and c.yCoord == y) and 3 or 2  -- 2: seen once, not now
        end
    """)
    r = report_of(lua)
    assert [a.id for a in r.visible_enemies] == ["Heinrich"] and r.seen_agents == []
    assert "sight: getTileVisibility" in bridge_log(lua)


def test_tile_visibility_above_visible_counts_as_seen(lua):
    # live 10-31: getTileVisibility returns 3..9 near own towns (more eyes, higher), 1 in fog and
    # 2 seen once; only == 3 counted, so enemies beside London dropped out of England's report
    lua.execute("""
        tileVisibility = { notVisible = 1, wasVisible = 2, visible = 3 }
        FAKE.byName.venice.getTileVisibility = function() return 7 end
    """)
    assert "Heinrich" in [a.id for a in report_of(lua).visible_enemies]


def test_tile_visibility_drops_things_not_visible_now(lua):
    lua.execute("FAKE.byName.venice.getTileVisibility = function() return 2 end")
    r = report_of(lua)
    assert r.visible_enemies == [] and r.seen_agents == []


def test_sight_sees_a_foreign_army_whose_stack_names_no_leader(lua):
    # live 10-30 22:03 (qa-covert): the rebel army Esau stood a tile from England's assassin for six
    # turns and never reached visible_enemies. EOP's armyStruct.leader is nil for a stack "inside
    # residence (fleet, settlement, fort)" (LuaDocs.lua:2734), and sight skipped every stack
    # without one; its general is still the character leading it
    lua.execute("""
        local st = FAKE.byName.hre.stacks[1]
        st.leader = nil
        st.xCoord, st.yCoord = 112, 80
    """)
    (heinrich,) = report_of(lua).visible_enemies
    assert (heinrich.id, heinrich.leader, heinrich.x, heinrich.y) == ("Heinrich", "Heinrich", 112, 80)
    assert [u.type for u in heinrich.troops] == ["Venetian Heavy Infantry", "Mailed Knights"]


def test_sight_sees_a_foreign_army_in_a_fort(lua):
    lua.execute("""
        local st = FAKE.byName.hre.stacks[1]
        st.leader = nil
        st.findInFort = function() return { xCoord = 112, yCoord = 80 } end
    """)
    (heinrich,) = report_of(lua).visible_enemies
    assert (heinrich.id, heinrich.x, heinrich.y) == ("Heinrich", 112, 80)


def test_sight_logs_a_foreign_stack_it_cannot_name(lua):
    # nobody leads it and no general stands there: not reported, but said once in the log
    lua.execute("""
        local hre = FAKE.byName.hre
        local st = hre.stacks[1]
        st.leader = nil
        st.xCoord, st.yCoord = 112, 80
        for _, c in ipairs(hre.characters) do
            if c.armyLeaded == st then c.armyLeaded, c.xCoord = nil, 50 end
        end
    """)
    assert report_of(lua).visible_enemies == []
    report_of(lua)
    assert bridge_log(lua).count("sight: hre stack at (112,80) has no general; left out") == 1


def test_own_army_in_a_fort_is_an_eye(lua):
    # a stack in a fort has no leader either: it still sees around it (radius sight here)
    lua.execute("""
        local venice = FAKE.byName.venice
        local st = venice.stacks[1]
        st.leader = nil
        st.findInFort = function() return { xCoord = 60, yCoord = 45 } end
        for _, c in ipairs(venice.characters) do
            if c.armyLeaded == st then c.xCoord, c.yCoord = 60, 45 end
        end
    """)
    r = report_of(lua)
    assert "Konrad" in [a.id for a in r.seen_agents]  # the HRE assassin at (60,40), 5 tiles off


def test_sight_logs_an_army_next_to_an_eye_that_the_tile_says_is_unseen(lua):
    # a probe for live: something a tile from the ruler's own that getTileVisibility calls unseen
    lua.execute("""
        tileVisibility = { notVisible = 1, wasVisible = 2, visible = 3 }
        local st = FAKE.byName.hre.stacks[1]
        st.leader.xCoord, st.leader.yCoord = 119, 87
        FAKE.byName.venice.getTileVisibility = function() return 2 end
    """)
    assert report_of(lua).visible_enemies == []
    report_of(lua)
    log = bridge_log(lua)
    assert log.count("sight: Heinrich (hre) at (119,87), 1 tile from venice's own, has tile visibility 2") == 1


def test_sight_falls_back_to_radius_when_visibility_errors(lua):
    lua.execute("FAKE.byName.venice.getTileVisibility = function() error('boom') end")
    r = report_of(lua)
    assert [a.id for a in r.visible_enemies] == ["Heinrich"]
    assert "sight: radius" in bridge_log(lua)


def test_foreign_agents_in_sight_only(lua):
    r = report_of(lua)
    assert [(a.id, a.faction, a.kind, a.distance) for a in r.seen_agents] == [("Ulrich", "hre", "spy", 1)]


def test_nearby_foreign_settlements(lua):
    r = report_of(lua)
    assert [(s.id, s.faction, s.garrison_strength, s.garrison_men, s.garrison_units, s.distance)
            for s in r.nearby_settlements] == [("Innsbruck", "hre", 500, 60, 2, 7)]


def test_report_settlement_garrison_counts_men_and_units(lua):
    lua.execute("FAKE.settlements.Ragusa.army = nil")
    r = report_of(lua)
    venice, ragusa = r.settlements
    assert (venice.garrison_men, venice.garrison_units, venice.garrison_strength) == (60, 2, 500)
    assert (ragusa.garrison_men, ragusa.garrison_units, ragusa.garrison_strength) == (0, 0, 0)


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


def next_to(agent, target):
    """Lua that puts one of Venice's agents on the tile beside a target (agents act from there)."""
    return f"""
        local tx, ty
        for _, f in pairs(FAKE.byName) do
            for _, c in ipairs(f.characters or {{}}) do
                if c.namedCharacter.fullName == '{target}' then tx, ty = c.xCoord, c.yCoord end
            end
            for _, s in ipairs(f.settlements or {{}}) do
                if s.name == '{target}' then tx, ty = s.xCoord, s.yCoord end
            end
        end
        for _, c in ipairs(FAKE.byName.venice.characters) do
            if c.namedCharacter.fullName == '{agent}' then c.xCoord, c.yCoord = tx + 1, ty end
        end
    """


@pytest.mark.parametrize("order, call", [
    ({"type": "assassinate", "agent": "Iacopo", "target": "Ulrich"}, "assassinate Iacopo Ulrich"),
    ({"type": "assassinate", "agent": "Iacopo", "target": "Heinrich"}, "assassinate Iacopo Heinrich"),
    ({"type": "sabotage", "agent": "Iacopo", "settlement": "Innsbruck"}, "sabotageSettlement Iacopo Innsbruck"),
    ({"type": "spy", "agent": "Marco", "target": "Innsbruck"}, "spySettlement Marco Innsbruck"),
    ({"type": "spy", "agent": "Marco", "target": "Ulrich"}, "spyCharacter Marco Ulrich"),
    ({"type": "bribe", "agent": "Pietro", "target": "Heinrich"}, "bribe Pietro Heinrich"),
])
def test_agent_orders_issue_the_right_actions(lua, order, call):
    done, r = issue(lua, order, next_to(order["agent"], order.get("target") or order.get("settlement")))
    assert done == [call] and r["ok"]


def test_agent_already_inside_the_target_is_refused(lua):
    # live, scratch2 turn 6: a spy inside Caernarvon spied on it again, and the game crashed
    inside = ("for _, c in ipairs(FAKE.byName.venice.characters) do "
              "if c.namedCharacter.fullName == 'Marco' then c.xCoord, c.yCoord = 115, 80 end end")
    done, r = issue(lua, {"type": "spy", "agent": "Marco", "target": "Innsbruck"}, inside)
    assert done == [] and "already inside Innsbruck" in r["reason"]


def test_a_campaign_load_forgets_which_agents_had_an_order(lua):
    # live bench 10-31: M.qa.order bypasses apply_orders (its reset), and a bench load doesn't rerun
    # the bridge, so bribe_agent and bribe_settlement found their agent "busy" from an earlier case
    spy = "{ type = 'spy', agent = 'Marco', target = 'Innsbruck' }"
    assert "already has an order" not in lua.eval(f"BRIDGE.qa.order('venice', {spy})")
    assert "already has an order this turn" in lua.eval(f"BRIDGE.qa.order('venice', {spy})")
    lua.execute(f"BRIDGE.setup('{lua.root}')")
    assert "already has an order" not in lua.eval(f"BRIDGE.qa.order('venice', {spy})")


def test_agent_far_from_the_target_walks_there(lua):
    done, r = issue(lua, {"type": "spy", "agent": "Marco", "target": "Innsbruck"})
    assert r["ok"] and "walking there instead" in r["note"]


def test_one_action_per_agent_per_turn(lua):
    lua.execute(next_to("Iacopo", "Ulrich"))
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
            done, _ = issue(lua, {"type": "assassinate", "agent": "Iacopo", "target": a.id},
                            MILAN_ULRICH + "; " + (next_to("Iacopo", "Ulrich") if a.faction == "hre" else
                                                   "local c = FAKE.byName.venice.characters[2]; "
                                                   "c.xCoord, c.yCoord = 119, 86"))
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
    assert [(u.unit, u.cost, u.turns, u.upkeep) for u in v.can_recruit] == [("Spear Militia", 350, 1, 100)]
    a = r.armies[0]
    assert [(u.type, u.soldiers, u.max_soldiers, u.exp) for u in a.troops] == [
        ("Venetian Heavy Infantry", 40, 60, 1), ("Mailed Knights", 20, 20, 0)]
    assert (a.moves_left, a.moves_max) == (12, 20)


def test_ruler_report_stays_small(lua):
    r = report_of(lua)
    assert r.settlements[0].can_build == [] and r.settlements[0].tax_level is None
    assert r.armies[0].troops == []


def test_plain_ruler_and_foreign_armies_and_sieges_carry_men(lua):
    lua.execute("""
        local s = FAKE.settlements.Venice
        s.siegesNum = 1
        s.siegeHoldoutTurns = 6
        s.getSiege = function() return { besieger = FAKE.byName.hre.stacks[1], siegeTurns = 2 } end
    """)
    r = report_of(lua)
    assert r.armies[0].troops == [] and r.armies[0].men == 60
    assert r.visible_enemies[0].men == 60
    assert (r.settlements[0].siege.men, r.settlements[0].siege.units, r.settlements[0].siege.strength) == (60, 2, 1200)


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


MERCS = """
; a comment
pool pool1
\tregions Venice_Province Ragusa_Province
\tunit Albanian Mercenaries\texp 1 cost 570 replenish 0.06 - 0.18 max 3 initial 2
\tunit Feudal Knights\texp 0 cost 1100 replenish 0.02 - 0.07 max 2 initial 0
\tunit Spear Militia\texp 0 cost 400 replenish 0.06 - 0.18 max 2 initial 2 religions { orthodox islam }
\tunit Pilgrims\texp 0 cost 35 replenish 0.18 - 0.5 max 4 initial 3 religions { catholic } crusading
\tunit Mercenary Arquebusiers\texp 0 cost 830 replenish 0.04 - 0.13 max 2 initial 0 start_year 1000 events { gunpowder_discovered }
\tunit Old Guard\texp 0 cost 100 replenish 0.04 - 0.13 max 2 initial 2 end_year 1000
"""


def write_mercs(lua, text=MERCS):
    path = (lua.root.parent / "data" / "world" / "maps" / "campaign" / "imperial_campaign"
            / "descr_mercenaries.txt")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


HIRE = {"type": "hire_mercenary", "army": "Doge Enrico", "unit": "Albanian Mercenaries"}


def test_report_lists_the_mercenaries_an_army_may_hire_where_it_stands(lua):
    control(lua)
    write_mercs(lua)
    r = report_of(lua)
    doge = next(a for a in r.armies if a.id == "Doge Enrico")
    # in stock, in its dates, open to a catholic, not crusading-only, no event needed
    assert [(m.unit, m.cost, m.available, m.max, m.exp) for m in doge.can_hire] == [("Albanian Mercenaries", 570, 2, 3, 1)]
    assert all(a.can_hire == [] for a in r.armies if a.id != "Doge Enrico")  # the garrison has no general
    assert all(s.model_dump().get("can_hire") is None for s in r.settlements)  # not a settlement matter


def test_a_crusading_army_may_hire_crusading_pool_entries_and_religion_limits_hold(lua):
    control(lua)
    write_mercs(lua)
    lua.execute("FAKE.byName.venice.stacks[1].leader.crusade = {}")
    doge = next(a for a in report_of(lua).armies if a.id == "Doge Enrico")
    assert [m.unit for m in doge.can_hire] == ["Albanian Mercenaries", "Pilgrims"]
    lua.execute("FAKE.byName.venice.religion = 1")  # orthodox: spearmen open, pilgrims (catholic) shut
    doge = next(a for a in report_of(lua).armies if a.id == "Doge Enrico")
    assert [m.unit for m in doge.can_hire] == ["Albanian Mercenaries", "Spear Militia"]


def test_no_mercenary_file_means_nothing_to_hire(lua):
    control(lua)
    assert next(a for a in report_of(lua).armies if a.id == "Doge Enrico").can_hire == []


def test_an_army_in_another_region_sees_that_regions_pool(lua):
    control(lua)
    write_mercs(lua)
    lua.execute("FAKE.stratMap.getRegion = (function(old) return function(id) local r = old(id) "
                "if id == 10 then r.mercPool = nil end return r end end)(FAKE.stratMap.getRegion)")
    assert next(a for a in report_of(lua).armies if a.id == "Doge Enrico").can_hire == []


def test_hire_mercenary_pays_shrinks_the_pool_and_joins_the_army_next_turn_as_a_hireling(lua):
    control(lua)
    write_mercs(lua)
    write_orders(lua, TURN - 1, "venice", [HIRE])
    start_turn(lua, "venice")
    assert results(lua)[0]["ok"], results(lua)
    assert lua.eval("FAKE.byName.venice.money") == 5000 - 570
    assert abs(lua.eval("FAKE.mercUnits[1].currentPool") - 1.4) < 1e-9
    assert not any(c.startswith("create") for c in calls(lua))  # still training
    lua.execute("FAKE.campaign.turnNumber = FAKE.campaign.turnNumber + 1")
    start_turn(lua, "venice")
    assert "create Doge Enrico Albanian Mercenaries" in calls(lua)
    assert lua.eval("FAKE.created.exp") == 1 and lua.eval("FAKE.created.isMercenary") is True


def test_hire_mercenary_refused_by_the_games_rules(lua):
    control(lua)
    write_mercs(lua)
    lua.execute("FAKE.byName.venice.money = 600")
    write_orders(lua, TURN - 1, "venice", [
        {**HIRE, "unit": "Feudal Knights"},  # 0.6 in stock
        {**HIRE, "unit": "Spear Militia"},  # orthodox only
        {**HIRE, "unit": "Pilgrims"},  # crusading only
        {**HIRE, "unit": "Mercenary Arquebusiers"},  # needs an event
        {**HIRE, "unit": "Old Guard"},  # ended in 1000
        {**HIRE, "army": "garrison:Venice"},  # no general
        HIRE,
        HIRE,  # gold gone
    ])
    start_turn(lua, "venice")
    r = results(lua)
    assert all("can't hire" in x["reason"] or "no general" in x["reason"] for x in r[:6]), r
    assert "offers: Albanian Mercenaries" in r[0]["reason"]
    assert r[6]["ok"] and "treasury" in r[7]["reason"]
    assert lua.eval("FAKE.byName.venice.money") == 30


def test_hire_mercenary_refused_when_the_pool_has_run_dry_or_the_army_is_in_another_region(lua):
    control(lua)
    write_mercs(lua)
    lua.execute("FAKE.mercUnits[1].currentPool = 0.4")
    write_orders(lua, TURN - 1, "venice", [HIRE])
    start_turn(lua, "venice")
    assert "can't hire 'Albanian Mercenaries'" in results(lua)[0]["reason"]
    assert lua.eval("FAKE.byName.venice.money") == 5000


def test_recruits_beyond_the_training_slots_wait_and_the_queue_holds_nine(lua):
    control(lua)
    # Venice's fake has no level: 2 slots. A 1-turn unit: two ready next turn, then two more a turn later
    lua.execute("FAKE.byName.venice.money = 100000; FAKE.settlements.Venice.pools = "
                "{ { eduIndex = 7, availablePool = 20 }, { eduIndex = 9, availablePool = 0 } }")
    write_orders(lua, TURN - 1, "venice", [{"type": "recruit", "settlement": "Venice", "unit": "Spear Militia"}] * 10)
    start_turn(lua, "venice")
    r = results(lua)
    assert all(x["ok"] for x in r[:9]) and "queue is full (9 waiting)" in r[9]["reason"]
    assert lua.eval("FAKE.byName.venice.money") == 100000 - 9 * 350  # the refused one costs nothing
    ready = sorted(t["ready"] for t in json.loads((turn_dir(lua, TURN, "venice").parent.parent / "training.json").read_text()))
    turn = lua.eval("FAKE.campaign.turnNumber")
    assert ready == [turn + 1] * 2 + [turn + 2] * 2 + [turn + 3] * 2 + [turn + 4] * 2 + [turn + 5]


def test_training_survives_a_reload(lua):
    control(lua)
    write_orders(lua, TURN - 1, "venice", [{"type": "recruit", "settlement": "Venice", "unit": "Spear Militia"}])
    start_turn(lua, "venice")
    lua.execute(f"package.loaded['parley_bridge'] = nil; BRIDGE = require('parley_bridge'); BRIDGE.setup('{lua.root}')")
    lua.execute("FAKE.campaign.turnNumber = FAKE.campaign.turnNumber + 1")
    start_turn(lua, "venice")
    assert "create Venice Spear Militia" in calls(lua)


EDB = """
    levels market great_market
    {
        market city requires factions { southern_european, northern_european, }
        {
            capability
            {
                agent merchant  0  requires factions { venice, milan, }
                agent_limit merchant 1
                agent_limit spy 1
            }
        }
    }
    levels small_church church
    {
        small_church city requires factions { venice, }
        {
            convert_to 0
            capability
            {
                agent priest  0  requires factions { normans, denmark, }
                agent priest  0  requires factions { venice, milan, }
                agent_limit priest 2
            }
        }
        church city
        {
            capability
            {
                agent_limit assassin 1
            }
        }
    }
"""


def write_edb(lua, text=EDB):
    path = lua.root.parent / "data" / "export_descr_buildings.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    lua.execute(f"BRIDGE.setup('{lua.root}')")


def test_report_lists_agents_a_settlement_can_train_and_the_limits(lua):
    control(lua)
    write_edb(lua)
    r = report_of(lua)
    venice, ragusa = r.settlements
    assert [(a.agent, a.cost, a.turns) for a in venice.can_recruit_agents] == [("merchant", 550, 1), ("priest", 200, 1)]
    assert ragusa.can_recruit_agents == []  # Ragusa has only core_building: trains nothing
    assert (r.agent_limits["merchant"].have, r.agent_limits["merchant"].limit) == (0, 1)
    assert (r.agent_limits["spy"].have, r.agent_limits["spy"].limit) == (1, 1)  # Marco
    assert (r.agent_limits["diplomat"].have, r.agent_limits["diplomat"].limit) == (1, None)  # Pietro, no limit in EDB


def test_recruit_agent_pays_and_spawns_him_next_turn(lua):
    control(lua)
    write_edb(lua)
    write_orders(lua, TURN - 1, "venice", [{"type": "recruit_agent", "settlement": "Venice", "agent": "merchant"}])
    start_turn(lua, "venice")
    assert results(lua)[0]["ok"], results(lua)
    assert lua.eval("FAKE.byName.venice.money") == 5000 - 550
    assert not any("spawn_character" in c for c in calls(lua))
    assert report_of(lua).agent_limits["merchant"].have == 1  # in training counts against the limit
    lua.execute("FAKE.campaign.turnNumber = FAKE.campaign.turnNumber + 1")
    start_turn(lua, "venice")
    assert "script spawn_character venice, random_name, merchant, age 20, x 120, y 88" in calls(lua)
    assert "merchant trained in Venice" in (lua.root / "parley_bridge.log").read_text()


def test_recruit_agent_refused_by_the_games_rules(lua):
    control(lua)
    write_edb(lua)
    lua.execute("FAKE.byName.venice.money = 300")
    write_orders(lua, TURN - 1, "venice", [
        {"type": "recruit_agent", "settlement": "Venice", "agent": "spy"},       # limit 1, Marco has it
        {"type": "recruit_agent", "settlement": "Venice", "agent": "assassin"},  # limit 0, Iacopo
        {"type": "recruit_agent", "settlement": "Venice", "agent": "merchant"},  # 550 > 300
        {"type": "recruit_agent", "settlement": "Venice", "agent": "priest"},    # 200: ok
        {"type": "recruit_agent", "settlement": "Venice", "agent": "priest"},    # 100 left
    ])
    start_turn(lua, "venice")
    r = results(lua)
    assert "spy limit reached: 1 of 1" in r[0]["reason"]
    assert "assassin limit reached: 1 of 0" in r[1]["reason"]
    assert "treasury too low" in r[2]["reason"] and r[3]["ok"] and "treasury too low" in r[4]["reason"]


def test_recruit_agent_without_a_building_refused(lua):
    control(lua)
    write_edb(lua)
    write_orders(lua, TURN - 1, "venice", [{"type": "recruit_agent", "settlement": "Venice", "agent": "diplomat"}])
    start_turn(lua, "venice")
    assert "no building that trains a diplomat" in results(lua)[0]["reason"]


def test_agent_without_edb_limit_has_no_limit_and_is_accepted(lua):
    control(lua)
    write_edb(lua, """
        levels market
        {
            market city
            {
                capability
                {
                    agent spy 0
                }
            }
        }
    """)
    r = report_of(lua)
    assert (r.agent_limits["spy"].have, r.agent_limits["spy"].limit) == (1, None)
    assert [a.agent for a in r.settlements[0].can_recruit_agents] == ["spy"]
    write_orders(lua, TURN - 1, "venice", [{"type": "recruit_agent", "settlement": "Venice", "agent": "spy"}])
    start_turn(lua, "venice")
    assert results(lua)[0]["ok"], results(lua)


def test_edb_parser_matches_culture_name_and_strips_comments(lua):
    control(lua)
    write_edb(lua, """
        levels market ; comment on levels
        {
            market city requires factions { northern_european, } ; comment on header
            {
                ; comment before capability
                capability
                {
                    agent spy 0 requires factions { northern_european, } ; culture name
                    agent diplomat 0 ; no faction list: applies to everyone
                    agent_limit spy 2 ; inline comment after limit
                }
            }
        }
    """)
    r = report_of(lua)
    assert [a.agent for a in r.settlements[0].can_recruit_agents] == ["diplomat"]
    assert r.agent_limits["spy"].limit == 2
    lua.execute("FAKE.byName.venice.cultureID = 1")  # northern_european
    assert [a.agent for a in report_of(lua).settlements[0].can_recruit_agents] == ["spy", "diplomat"]


def test_missing_edb_logs_once_and_trains_no_agents(lua):
    control(lua)
    r = report_of(lua)
    assert r.settlements[0].can_recruit_agents == []
    report_of(lua)
    write_orders(lua, TURN - 1, "venice", [{"type": "recruit_agent", "settlement": "Venice", "agent": "merchant"}])
    start_turn(lua, "venice")
    assert "no building that trains a merchant" in results(lua)[0]["reason"]
    assert (lua.root / "parley_bridge.log").read_text().count("export_descr_buildings.txt") == 1


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


def test_move_agent_onto_sea_refused_with_the_nearest_land(lua):
    # live (2026-10-29): Gregory Budinge's move to (105,138), a sea tile, came back "done"
    control(lua)
    write_orders(lua, TURN - 1, "venice", [{"type": "move_agent", "agent": "Pietro", "x": 116, "y": 91}])
    start_turn(lua, "venice")
    reason = results(lua)[0]["reason"]
    assert "(116,91) is sea" in reason and "nearest land is (" in reason and calls(lua) == []


ISLAND = """
    local mainland = FAKE.stratMap.getTile
    FAKE.stratMap.getTile = function(x, y)  -- Pietro (140,80) on an island: land 135-145 x 75-85
        if x >= 130 and x <= 150 and y >= 70 and y <= 89 then
            return { isLand = (x >= 135 and x <= 145 and y >= 75 and y <= 85) and 1 or 0 }
        end
        return mainland(x, y)
    end
"""


@pytest.mark.parametrize("kind, order", [
    ("agent", {"type": "move_agent", "agent": "Pietro", "x": 100, "y": 60}),
    ("army", {"type": "move_army", "army": "Doge Enrico", "x": 140, "y": 80}),
])
def test_move_with_no_land_path_refused(lua, kind, order):
    # live (2026-10-29): a diplomat in England was sent to France; it came back "done" and he stayed
    control(lua)
    lua.execute(ISLAND)
    write_orders(lua, TURN - 1, "venice", [order])
    start_turn(lua, "venice")
    reason = results(lua)[0]["reason"]
    assert "can't be reached over land" in reason and "you have no fleet" in reason and calls(lua) == []


def test_an_army_beside_its_fleet_boards_by_a_split_of_all_its_units(lua):
    # live bench 10-31 15:18 (board_next_fleet): moveToTile onto the fleet's sea tile came back "ok"
    # and the army stayed on the shore. EOP's factionStruct:splitArmy: "They embark/disembark"
    control(lua)
    beside = ("local st = FAKE.byName.venice.stacks[1]; st.leader.xCoord, st.leader.yCoord = 121, 89; "
              "if st.xCoord then st.xCoord, st.yCoord = 121, 89 end; "
              "FAKE.add_fleet(FAKE.byName.venice, 'Admiral Lewes', 121, 90)")
    done, r = issue(lua, {"type": "board", "who": "Doge Enrico", "fleet": "Admiral Lewes"}, beside)
    assert r["ok"], r
    assert any(c.startswith("splitArmy venice ") and c.endswith(" 121 90") for c in done), done
    assert not any(c.startswith("moveToTile Doge Enrico") for c in done), done


def test_no_land_path_refusal_carries_the_board_order_ready_to_copy(lua):
    # live (2026-10-29): told "board a fleet first" five turns running, the ruler never wrote one
    control(lua)
    lua.execute(ISLAND)
    lua.execute("FAKE.add_fleet(FAKE.byName.venice, 'Admiral Lewes', 120, 95)")
    write_orders(lua, TURN - 1, "venice", [{"type": "move_army", "army": "Doge Enrico", "x": 140, "y": 80}])
    start_turn(lua, "venice")
    reason = results(lua)[0]["reason"]
    assert '{"type": "board", "who": "Doge Enrico", "fleet": "Admiral Lewes"}' in reason
    assert "Admiral Lewes is at (120,95)" in reason and calls(lua) == []


def test_move_on_the_same_island_goes_ahead(lua):
    control(lua)
    lua.execute(ISLAND)
    write_orders(lua, TURN - 1, "venice", [{"type": "move_agent", "agent": "Pietro", "x": 143, "y": 83}])
    start_turn(lua, "venice")
    assert results(lua)[0]["ok"] and "moveToTile Pietro 143 83" in calls(lua)


@pytest.mark.parametrize("kind, order, says", [
    ("army", {"type": "move_army", "army": "Doge Enrico"}, "besiege it"),
    ("agent", {"type": "move_agent", "agent": "Pietro"}, "agent's own order (spy, assassinate"),
])
def test_move_onto_a_foreign_settlement_refused_with_the_order_that_fits(lua, kind, order, says):
    # live (2026-10-29, the turn audit): 15 moves onto others' settlements came back "done", nobody moved
    control(lua)
    x, y = lua.eval("FAKE.settlements.Milan.xCoord"), lua.eval("FAKE.settlements.Milan.yCoord")
    write_orders(lua, TURN - 1, "venice", [{**order, "x": x, "y": y}])
    start_turn(lua, "venice")
    reason = results(lua)[0]["reason"]
    assert f"({x},{y}) is " in reason and "milan's settlement" in reason and says in reason
    assert not any(c.startswith("moveToTile") for c in calls(lua))


# an army or agent sent at a settlement across the sea walked nowhere and came back "done"
# (live, run6: an army sat on one tile for 36 turns after "marching there instead")
ISLAND_MILAN = "FAKE.settlements.Milan.xCoord, FAKE.settlements.Milan.yCoord = 140, 82"


def test_besiege_across_the_sea_refused_instead_of_marching(lua):
    control(lua)
    lua.execute(ISLAND)
    lua.execute(ISLAND_MILAN)
    write_orders(lua, TURN - 1, "venice", [{"type": "besiege", "army": "Doge Enrico", "settlement": "Milan"}])
    start_turn(lua, "venice")
    r = results(lua)[0]
    assert not r["ok"] and "can't be reached over land" in r["reason"] and "you have no fleet" in r["reason"]
    assert calls(lua) == []


def test_besiege_across_the_sea_carries_the_board_order(lua):
    control(lua)
    lua.execute(ISLAND)
    lua.execute(ISLAND_MILAN)
    lua.execute("FAKE.add_fleet(FAKE.byName.venice, 'Admiral Lewes', 120, 95)")
    write_orders(lua, TURN - 1, "venice", [{"type": "besiege", "army": "Doge Enrico", "settlement": "Milan"}])
    start_turn(lua, "venice")
    assert '{"type": "board", "who": "Doge Enrico", "fleet": "Admiral Lewes"}' in results(lua)[0]["reason"]
    assert calls(lua) == []


def test_march_on_across_the_sea_refused(lua):
    # live (run8, turn 16): garrison:London marched on Paris across the Channel; "done", stayed at (109,147)
    control(lua)
    lua.execute(ISLAND)
    lua.execute(ISLAND_MILAN)
    lua.execute(ROBIN_IN_VENICE)
    write_orders(lua, TURN - 1, "venice", [
        {"type": "march_on", "army": "garrison:Venice", "target_settlement": "Ragusa"},
        {"type": "march_on", "army": "Doge Enrico", "target_settlement": "Milan"},
    ])
    start_turn(lua, "venice")
    for r in results(lua):
        assert not r["ok"] and "can't be reached over land" in r["reason"] and "you have no fleet" in r["reason"]
    assert calls(lua) == []


def test_march_on_across_the_sea_carries_the_board_order(lua):
    control(lua)
    lua.execute(ISLAND)
    lua.execute(ROBIN_IN_VENICE)
    lua.execute("FAKE.add_fleet(FAKE.byName.venice, 'Admiral Lewes', 120, 95)")
    write_orders(lua, TURN - 1, "venice", [
        {"type": "march_on", "army": "garrison:Venice", "target_settlement": "Ragusa"},
    ])
    start_turn(lua, "venice")
    assert '{"type": "board", "who": "garrison:Venice", "fleet": "Admiral Lewes"}' in results(lua)[0]["reason"]
    assert calls(lua) == []


@pytest.mark.parametrize("order", [
    {"type": "spy", "agent": "Marco", "target": "Innsbruck"},
    {"type": "sabotage", "agent": "Iacopo", "settlement": "Innsbruck"},
    {"type": "assassinate", "agent": "Iacopo", "target": "Heinrich"},
])
def test_agent_walk_across_the_sea_refused(lua, order):
    # the agent stands on the island, the target on the mainland
    on_island = ISLAND + f"""
        for _, c in ipairs(FAKE.byName.venice.characters) do
            if c.namedCharacter.fullName == '{order["agent"]}' then c.xCoord, c.yCoord = 140, 80 end
        end
    """
    done, r = issue(lua, order, on_island)
    assert not r["ok"] and "can't be reached over land" in r["reason"], r
    assert not any(c.startswith("moveToTile") for c in done), done


def test_report_marks_settlements_the_armies_cannot_reach_by_land(lua):
    assert report_of(lua).nearby_settlements[0].by_land is True
    lua.execute(ISLAND)
    lua.execute("FAKE.settlements.Innsbruck.xCoord, FAKE.settlements.Innsbruck.yCoord = 140, 82")
    assert report_of(lua).nearby_settlements[0].by_land is False


def test_move_onto_an_own_settlement_goes_ahead(lua):
    control(lua)
    x, y = lua.eval("FAKE.settlements.Venice.xCoord"), lua.eval("FAKE.settlements.Venice.yCoord")
    write_orders(lua, TURN - 1, "venice", [{"type": "move_agent", "agent": "Pietro", "x": x, "y": y}])
    start_turn(lua, "venice")
    assert results(lua)[0]["ok"] and f"moveToTile Pietro {x} {y}" in calls(lua)


def test_fleet_onto_land_refused_with_the_nearest_sea(lua):
    # live, turns 32-34: a fleet ordered onto one coast three turns running, one tile off each time
    lua.execute("FAKE.add_fleet(FAKE.byName.venice, 'Admiral Lewes', 116, 92)")
    control(lua)
    write_orders(lua, TURN - 1, "venice", [{"type": "move_army", "army": "Admiral Lewes", "x": 120, "y": 88}])
    start_turn(lua, "venice")
    reason = results(lua)[0]["reason"]
    assert "a fleet can't sail onto land (120,88)" in reason and "the nearest sea is (" in reason
    assert calls(lua) == []


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
    ({"type": "merge_armies", "army": "garrison:Venice", "into": "Doge Enrico"}, "merge garrison:Venice Doge Enrico true"),
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


def test_merge_refused_into_an_army_that_moved_this_turn(lua):
    # live, scratch2 turn 2: besiege, then merge into the besieger, crashed the game
    control(lua)
    write_orders(lua, TURN - 1, "venice", [
        {"type": "move_army", "army": "Doge Enrico", "x": 125, "y": 88},
        {"type": "merge_armies", "army": "garrison:Venice", "into": "Doge Enrico"}])
    start_turn(lua, "venice")
    r = results(lua)
    assert r[0]["ok"] and "already moved or besieged" in r[1]["reason"]
    assert not any(c.startswith("merge") for c in calls(lua))


def test_merge_refused_for_a_stack_in_a_siege(lua):
    control(lua)
    lua.execute("for _, s in ipairs(FAKE.byName.venice.stacks) do s.siege = {} end")
    write_orders(lua, TURN - 1, "venice", [{"type": "merge_armies", "army": "garrison:Venice", "into": "Doge Enrico"}])
    start_turn(lua, "venice")
    assert "siege" in results(lua)[0]["reason"] and not any(c.startswith("merge") for c in calls(lua))


def test_merge_adjacent_garrison_merges_instantly(lua):
    control(lua)
    write_orders(lua, TURN - 1, "venice", [{"type": "merge_armies", "army": "garrison:Venice", "into": "Doge Enrico"}])
    start_turn(lua, "venice")
    assert results(lua)[0]["ok"] and calls(lua) == ["merge garrison:Venice Doge Enrico true"]
    assert lua.eval("FAKE.byName.venice.stacks[1].numOfUnits") == 4
    assert lua.eval("FAKE.byName.venice.stacks[2].numOfUnits") == 0


def test_merge_adjacent_refused_when_it_does_not_take(lua):
    # live (turns 179 and 180): garrison:York into Augustine Maitland beside York moved nothing
    control(lua)
    lua.execute("FAKE.byName.venice.stacks[2].mergeFails = true")
    write_orders(lua, TURN - 1, "venice", [{"type": "merge_armies", "army": "garrison:Venice", "into": "Doge Enrico"}])
    start_turn(lua, "venice")
    r = results(lua)[0]
    assert not r["ok"] and r["reason"] == "the merge didn't take: Doge Enrico still has 2 units"
    assert calls(lua) == ["merge garrison:Venice Doge Enrico true"]


def test_merge_far_apart_walks(lua):
    control(lua)
    lua.execute("FAKE.byName.venice.stacks[1].leader.xCoord = 130")
    write_orders(lua, TURN - 1, "venice", [{"type": "merge_armies", "army": "garrison:Venice", "into": "Doge Enrico"}])
    start_turn(lua, "venice")
    assert calls(lua) == ["merge garrison:Venice Doge Enrico false"]
    assert "merge_armies: garrison:Venice is walking to join Doge Enrico (10 tiles); it merges when it arrives" in (
        lua.root / "parley_bridge.log").read_text()
    # live, turn 12: the ruler must know its town is left empty while the garrison walks
    r = results(lua)[0]
    assert r["ok"] and r["reason"] == ""
    assert "marches out of Venice under a captain" in r["note"] and "Venice is left without a garrison" in r["note"]


# EOP gives a stack inside a settlement no leader; the general there must still be found
ROBIN_IN_VENICE = "FAKE.general_in_town(FAKE.byName.venice, 'Captain Robin', FAKE.settlements.Venice)"


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
    assert results(lua)[0]["ok"] and "splitArmy venice NE Bodyguard 119 89" in calls(lua)
    assert "moveToTile Captain Robin 100 90" in calls(lua)


def test_governor_flags_are_logged_each_turn(lua):
    control(lua, "control=venice:diplomacy,armies,agents\n", "autoplay=1\n")
    start_turn(lua, "venice")
    assert "governors venice: Venice build=true recruit=true" in (lua.root / "parley_bridge.log").read_text()


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


def test_report_gives_the_men_aboard_a_fleet(lua):
    control(lua)
    lua.execute(FLEET + "; local f = FAKE.byName.venice.stacks[3]; f.boardedArmy = FAKE.byName.venice.stacks[1]")
    fleet = next(a for a in report_of(lua).armies if a.id == "Admiral Polo")
    assert fleet.carrying == 2 and fleet.carrying_men and fleet.carrying_men > 0


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
    # the whole army splits ashore (live 10-31 18:30: moveToTile landed the general alone)
    assert r[2]["ok"] and "splitArmy venice Venetian Heavy Infantry,Mailed Knights 114 92" in calls(lua)


# --- movement points: a mover with none left is refused, not reported "done" ------------------
# EOP character.movePointsCharacter (LuaDocs.lua:6481). Live (run8, 2026-10-30): moves issued with
# moveToTile came back "done" while the mover stood still; one with no moves left can't go anywhere.

NO_MOVES = "has no moves left this turn"
FLEET_DOGE_ABOARD = (FLEET + "; local f = FAKE.byName.venice.stacks[3]; local doge = FAKE.byName.venice.stacks[1]; "
                     "f.boardedArmy = doge; doge.shipArmy = f; doge.leader = nil; "
                     "FAKE.byName.venice.characters[1].xCoord, FAKE.byName.venice.characters[1].yCoord = 118, 92")


@pytest.mark.parametrize("who, order, setup", [
    ("Doge Enrico", {"type": "move_army", "army": "Doge Enrico", "x": 110, "y": 88}, ""),
    ("Captain Robin", {"type": "move_army", "army": "garrison:Venice", "x": 110, "y": 88}, ROBIN_IN_VENICE),
    ("Doge Enrico", {"type": "march_on", "army": "Doge Enrico", "target_settlement": "Ragusa"}, ""),
    ("Doge Enrico", {"type": "besiege", "army": "Doge Enrico", "settlement": "Milan"}, ""),
    ("Doge Enrico", {"type": "withdraw", "army": "Doge Enrico", "to_settlement": "Ragusa"}, ""),
    ("Doge Enrico", {"type": "merge_armies", "army": "Doge Enrico", "into": "garrison:Venice"},
     "FAKE.byName.venice.stacks[1].leader.xCoord = 130"),
    ("Pietro", {"type": "move_agent", "agent": "Pietro", "x": 138, "y": 80}, ""),
    ("Marco", {"type": "spy", "agent": "Marco", "target": "Innsbruck"}, ""),
    ("Doge Enrico", {"type": "board", "who": "Doge Enrico", "fleet": "Admiral Polo"}, FLEET),
    ("Marco", {"type": "board", "who": "Marco", "fleet": "Admiral Polo"}, FLEET),
    ("Doge Enrico", {"type": "land", "army": "Doge Enrico", "x": 114, "y": 92}, FLEET_DOGE_ABOARD),
])
def test_a_mover_with_no_moves_left_is_refused_and_nothing_is_issued(lua, who, order, setup):
    # live (run8, 2026-10-30): Robert's move out of Paris came back "done"; he never left
    control(lua)
    done, r = issue(lua, order, f"{setup}\nFAKE.set_moves('{who}', 0, 0)")
    assert not r["ok"] and r["reason"].startswith(f"{who} {NO_MOVES}"), r
    assert "order it again next turn" in r["reason"]
    assert not any(c.startswith(("moveToTile", "merge ", "siege ")) for c in done), done


def test_the_army_refusal_says_why_an_army_runs_out_of_moves(lua):
    control(lua)
    _, r = issue(lua, {"type": "move_army", "army": "Doge Enrico", "x": 110, "y": 88},
                 "FAKE.set_moves('Doge Enrico', 0, 0)")
    assert r["reason"] == ("Doge Enrico has no moves left this turn (an army that just took a town, fought "
                           "or marched its full distance can't move again until next turn); order it again next turn")


@pytest.mark.parametrize("points", [
    "30, 30",        # moves left
    "nil, nil",      # the field reads nil: never block on missing data
    "'raise', nil",  # reading it raises: never block on missing data
    "0, 40",         # the character reads 0 but his army still has moves: let the game decide
])
def test_a_mover_with_moves_or_unreadable_moves_goes_ahead(lua, points):
    control(lua)
    done, r = issue(lua, {"type": "move_army", "army": "Doge Enrico", "x": 110, "y": 88},
                    f"FAKE.set_moves('Doge Enrico', {points})")
    assert r["ok"] and "moveToTile Doge Enrico 110 88" in done, r


def test_an_agent_with_moves_left_still_walks_to_its_target(lua):
    control(lua)
    done, r = issue(lua, {"type": "spy", "agent": "Marco", "target": "Innsbruck"}, "FAKE.set_moves('Marco', 12)")
    assert r["ok"] and any(c.startswith("moveToTile Marco") for c in done), (r, done)


def test_an_exhausted_army_merging_beside_its_target_is_not_refused(lua):
    # an instant merge is no walk: mergeArmies(into, true) joins the stacks where they stand
    control(lua)
    done, r = issue(lua, {"type": "merge_armies", "army": "garrison:Venice", "into": "Doge Enrico"},
                    "FAKE.set_moves('Doge Enrico', 0, 0)")
    assert r["ok"] and done == ["merge garrison:Venice Doge Enrico true"], (r, done)


def test_land_needs_an_army_aboard(lua):
    control(lua)
    write_orders(lua, TURN - 1, "venice", [{"type": "land", "army": "Doge Enrico", "x": 114, "y": 92}])
    start_turn(lua, "venice")
    assert "not aboard" in results(lua)[0]["reason"]


def test_fleet_with_nil_leader_resolves_and_moves(lua):
    # live: turn 59 (Admiral Humphrey) and turn 35 (Admiral Lewes) reported fleet with st.leader nil
    # was refused as unknown army / unknown fleet
    control(lua)
    lua.execute("local f = FAKE.add_fleet(FAKE.byName.venice, 'Admiral Humphrey', 114, 166); f.leader = nil")
    r = report_of(lua)
    fleet = next(a for a in r.armies if a.id == "Admiral Humphrey")
    assert fleet.is_fleet and fleet.leader == "Admiral Humphrey" and (fleet.x, fleet.y) == (114, 166)

    write_orders(lua, TURN - 1, "venice", [
        {"type": "move_army", "army": "Admiral Humphrey", "x": 115, "y": 164},
        {"type": "board", "who": "Marco", "fleet": "Admiral Humphrey"},
    ])
    start_turn(lua, "venice")
    res = results(lua)
    assert res[0]["ok"] and "moveToTile Admiral Humphrey 115 164" in calls(lua)
    assert res[1]["ok"] and "moveToTile Marco 114 166" in calls(lua)


def test_fleet_order_without_admiral_prefix_resolves(lua):
    control(lua)
    lua.execute("FAKE.add_fleet(FAKE.byName.venice, 'Admiral Humphrey', 114, 166)")
    write_orders(lua, TURN - 1, "venice", [
        {"type": "move_army", "army": "Humphrey", "x": 115, "y": 164},
    ])
    start_turn(lua, "venice")
    res = results(lua)
    assert res[0]["ok"] and "moveToTile Admiral Humphrey 115 164" in calls(lua)


def test_control_lua_runs_a_line_and_logs_the_result(lua):
    autoplay(lua)
    (lua.root / "control.txt").write_text("lua return gameDataAll.get().stratMap.getTile(118, 92).isLand\n")
    tick(lua)
    assert "control: lua -> 0" in (lua.root / "parley_bridge.log").read_text()


def test_control_lua_line_sees_the_bridge_as_M(lua):
    # live 10-30: the first QA run's "M.qa.spawn_agent" failed, "attempt to index global 'M'":
    # the plugin script keeps the bridge in a local, so no global names it
    lua.execute("M = nil")
    autoplay(lua)
    (lua.root / "control.txt").write_text("lua return type(M.qa) .. ' ' .. type(gameDataAll)\n")
    tick(lua)
    assert "control: lua -> table table" in (lua.root / "parley_bridge.log").read_text()
    assert lua.eval("M") is None  # nothing leaks into the globals


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
    # EOP's flags are booleans (LuaDocs aiProductionController): live 10-31 bench, 0/1 were written
    # and the flags still read true under full control
    assert lua.eval("FAKE.settlements.Venice.aiProductionController.isAutoManagedConstruction") is True
    assert lua.eval("FAKE.settlements.Venice.aiProductionController.isAutoManagedRecruitment") is True


def test_full_control_turns_the_governors_off(lua):
    lua.execute("FAKE.settlements.Venice.aiProductionController.isAutoManagedConstruction = true")
    control(lua, FULL, "autoplay=1\n")
    start_turn(lua, "venice")
    pc = "FAKE.settlements.Venice.aiProductionController"
    assert lua.eval(f"{pc}.isAutoManagedConstruction") is False
    assert lua.eval(f"{pc}.isAutoManagedRecruitment") is False
    assert lua.eval(f"{pc}.isAutoManaged") is False


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
                     "siege_maintain_button", "siege_assault_button", "siege_end_button",
                     "release_prisoners_button", "close_cross_button",
                     "close_seal_button")]


def test_end_turn_is_pressed_by_its_own_call_when_on_screen(lua):
    # Track A (no clicks): live, execute pressed the auto-resolve button (#204); End Turn follows
    autoplay(lua)
    lua.execute("FAKE.ui.end_turn = { elementName = 'end_turn', "
                "execute = function() FAKE.calls[#FAKE.calls + 1] = 'press end_turn' end }")
    write_orders(lua, TURN - 1, "venice", [])
    start_turn(lua, "venice")
    tick(lua)
    assert calls(lua) == ["press end_turn"]  # no scripted click, pressed once


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


def test_autoplay_logs_a_heartbeat_about_every_minute_while_waiting(lua):
    autoplay(lua, "autoplay_wait=540\n")
    reported(lua, TURN - 1, "milan")
    write_orders(lua, TURN - 1, "venice", [])
    start_turn(lua, "venice")
    log = lua.root / "parley_bridge.log"

    def beats():
        return [l for l in log.read_text().splitlines() if "autoplay: turn" in l and "waiting for" in l]

    tick(lua, 30)
    assert beats() == []
    tick(lua, 35)  # 65 s in
    assert len(beats()) == 1
    assert "waiting for milan (65s of 540)" in beats()[0]
    tick(lua, 20)
    assert len(beats()) == 1
    tick(lua, 45)  # 130 s in, 65 s after the last beat
    assert len(beats()) == 2


def test_autoplay_logs_no_heartbeat_when_nothing_is_awaited(lua):
    autoplay(lua)
    write_orders(lua, TURN - 1, "venice", [])
    write_orders(lua, TURN - 1, "milan", [])
    start_turn(lua, "venice")
    tick(lua, 100)
    text = (lua.root / "parley_bridge.log").read_text() if (lua.root / "parley_bridge.log").exists() else ""
    assert "waiting for" not in text


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
    tick(lua, 560)  # no answer at all (DECIDE_WAIT 540)
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
    lua.execute(DOGE_BY_MILAN)
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


def test_two_assault_orders_in_one_turn_each_answered_with_siege_assault_button(lua):
    autoplay(lua)
    lua.execute(DOGE_BY_MILAN)
    lua.execute("FAKE.add_army(FAKE.byName.venice, 'Captain Robin', 115, 81)")
    lua.execute("FAKE.stances['venice|milan'] = dipRelType.war")
    write_orders(lua, TURN - 1, "venice", [
        {"type": "besiege", "army": "Doge Enrico", "settlement": "Milan", "assault": True},
        {"type": "besiege", "army": "Captain Robin", "settlement": "Innsbruck", "assault": True},
    ])
    start_turn(lua, "venice")
    assert "siege Doge Enrico Milan true" in calls(lua)
    assert "siege Captain Robin Innsbruck true" in calls(lua)
    assert lua.eval("BRIDGE.assault_ordered") == 2
    # First siege scroll
    opened(lua, "siege_scroll", ["siege_assault_button", "siege_maintain_button"])
    tick(lua, 5)
    capture_all(lua)
    tick(lua, 1)
    assert presses(lua) == ["press siege_assault_button"]
    assert lua.eval("BRIDGE.assault_ordered") == 1
    # Second siege scroll
    opened(lua, "siege_scroll", ["siege_assault_button", "siege_maintain_button"])
    tick(lua, 5)
    capture_all(lua)
    tick(lua, 1)
    assert presses(lua) == ["press siege_assault_button", "press siege_assault_button"]
    assert lua.eval("BRIDGE.assault_ordered") == 0


def test_siege_scroll_unnamed_children_maintain_disabled_falls_through_and_closes(lua):
    autoplay(lua)
    lua.execute("""
        FAKE.ui['siege_scroll'] = {
            elementName = 'siege_scroll', subElementsNum = 4,
            getSubElement = function(self, i) return { elementName = '', subElementsNum = 0 } end
        }
        FAKE.ui['siege_maintain_button'] = {
            elementName = 'siege_maintain_button', subElementsNum = 0,
            execute = function() table.insert(FAKE.calls, 'press siege_maintain_button') end
        }
        FAKE.ui['siege_assault_button'] = {
            elementName = 'siege_assault_button', subElementsNum = 0,
            execute = function() table.insert(FAKE.calls, 'press siege_assault_button'); FAKE.ui['siege_scroll'] = nil end
        }
        FAKE.ui['siege_end_button'] = {
            elementName = 'siege_end_button', subElementsNum = 0,
            execute = function() table.insert(FAKE.calls, 'press siege_end_button'); FAKE.ui['siege_scroll'] = nil end
        }
        BRIDGE.on_scroll_opened({ resourceDescription = 'siege_scroll' })
    """)
    tick(lua, 5)
    capture_all(lua)
    tick(lua, 1)
    assert presses(lua) == ["press siege_maintain_button"]
    assert lua.eval("FAKE.ui['siege_scroll']") is not None
    tick(lua, 1)
    assert presses(lua) == ["press siege_maintain_button", "press siege_assault_button"]
    assert lua.eval("FAKE.ui['siege_scroll']") is None


def test_siege_scroll_closed_before_press_clears_pending_and_runs_ui_job(lua):
    autoplay(lua)
    lua.execute("table.insert(BRIDGE.ui_jobs, { kind = 'retrain', settlement = 'Venice', step = 1 })")
    opened(lua, "siege_scroll", ["siege_maintain_button"])
    assert lua.eval("#BRIDGE.pending()") == 1

    # Closes before handle_popups presses anything
    lua.execute("FAKE.ui['siege_scroll'] = nil")

    tick(lua, 5)
    capture_all(lua)
    tick(lua, 1)

    assert lua.eval("#BRIDGE.pending()") == 0
    assert "script select_settlement Venice" in calls(lua)
    log = (lua.root / "parley_bridge.log").read_text()
    assert "popup handled: a siege (closed)" in log


def test_siege_scroll_drops_after_ten_tries_if_stuck(lua):
    autoplay(lua)
    opened(lua, "siege_scroll", ["unrecognized_button"])
    tick(lua, 5)
    capture_all(lua)
    for _ in range(10):
        tick(lua, 1)
        assert lua.eval("#BRIDGE.pending()") == 1
    tick(lua, 1)
    assert lua.eval("#BRIDGE.pending()") == 0
    log = (lua.root / "parley_bridge.log").read_text()
    assert "still open after 10 tries; dropping" in log


def test_besiege_from_afar_marches_instead(lua):
    # live, scratch2 turn 6: siegeSettlement from 10 and 16 tiles crashed the game, three times
    write_orders(lua, TURN - 1, "venice", [
        {"type": "besiege", "army": "Doge Enrico", "settlement": "Milan", "assault": True}])
    start_turn(lua, "venice")
    r = results(lua)[0]
    assert r["ok"] and "21 tiles from Milan: marching there instead" in r["note"]
    assert calls(lua) == ["moveToTile Doge Enrico 100 90"]


def test_march_on_an_enemy_town_from_the_next_tile_besieges_it(lua):
    # live (run8, turn 1): march_on Rufus to York (rebel) from (107,163), the next tile; the move
    # onto a town it doesn't hold went nowhere, came back "done", and Rufus sat still two turns
    lua.execute(DOGE_BY_MILAN)
    lua.execute("FAKE.stances['venice|milan'] = dipRelType.war")
    write_orders(lua, TURN - 1, "venice", [
        {"type": "march_on", "army": "Doge Enrico", "target_settlement": "Milan"}])
    start_turn(lua, "venice")
    assert calls(lua) == ["siege Doge Enrico Milan false"]
    r = results(lua)[0]
    assert r["ok"] and "next to Milan" in r["note"] and "besieging it" in r["note"]


def test_march_on_a_rebel_town_from_the_next_tile_besieges_it(lua):
    lua.execute(DOGE_BY_MILAN)
    lua.execute("FAKE.settlements.Milan.ownerFaction = FAKE.byName.slave")
    write_orders(lua, TURN - 1, "venice", [
        {"type": "march_on", "army": "Doge Enrico", "target_settlement": "Milan"}])
    start_turn(lua, "venice")
    assert calls(lua) == ["siege Doge Enrico Milan false"]
    assert results(lua)[0]["ok"]


def test_march_on_a_siege_the_game_has_not_shown_yet_is_ok_with_a_note(lua):
    # live (qa-field, 2026-10-30): the siege scroll came up 7 s after siegeSettlement, so the
    # army's siege may be set late: a siege not yet shown is never a failure, and never "besieging"
    lua.execute(DOGE_BY_MILAN)
    lua.execute("FAKE.settlements.Milan.ownerFaction = FAKE.byName.slave")
    lua.execute("FAKE.byName.venice.stacks[1].siegeRefused = true")
    write_orders(lua, TURN - 1, "venice", [
        {"type": "march_on", "army": "Doge Enrico", "target_settlement": "Milan"}])
    start_turn(lua, "venice")
    assert calls(lua) == ["siege Doge Enrico Milan false"]  # still carried out
    r = results(lua)[0]
    assert r["ok"] and "next to Milan" in r["note"] and "besieging it" not in r["note"]
    assert "the game hasn't shown the siege yet: the next report says whether it holds" in r["note"]


def test_besiege_not_yet_shown_is_ok_with_a_note(lua):
    lua.execute(DOGE_BY_MILAN)
    lua.execute("FAKE.byName.venice.stacks[1].siegeRefused = true")
    write_orders(lua, TURN - 1, "venice", [{"type": "besiege", "army": "Doge Enrico", "settlement": "Milan"}])
    start_turn(lua, "venice")
    r = results(lua)[0]
    assert r["ok"] and "siege of Milan ordered; the game hasn't shown it yet" in r["note"]


def test_besiege_the_game_refuses_fails_with_its_reason_and_still_goes_out(lua):
    lua.execute(DOGE_BY_MILAN)
    lua.execute("FAKE.byName.venice.stacks[1].canStartSiege = function() return false end")
    write_orders(lua, TURN - 1, "venice", [{"type": "besiege", "army": "Doge Enrico", "settlement": "Milan"}])
    start_turn(lua, "venice")
    assert "siege Doge Enrico Milan false" in calls(lua)
    r = results(lua)[0]
    assert not r["ok"] and "the siege of Milan didn't start" in r["reason"]
    assert "can't besiege Milan" in r["reason"]


def test_march_on_the_game_refuses_fails_without_saying_besieging(lua):
    lua.execute(DOGE_BY_MILAN)
    lua.execute("FAKE.settlements.Milan.ownerFaction = FAKE.byName.slave")
    lua.execute("FAKE.byName.venice.stacks[1].canStartSiege = function() return false end")
    write_orders(lua, TURN - 1, "venice", [
        {"type": "march_on", "army": "Doge Enrico", "target_settlement": "Milan"}])
    start_turn(lua, "venice")
    r = results(lua)[0]
    assert not r["ok"] and "next to Milan" in r["reason"] and "besieging it" not in r["reason"]
    assert "can't besiege Milan" in r["reason"]


def test_besiege_that_starts_reports_ok(lua):
    lua.execute(DOGE_BY_MILAN)
    write_orders(lua, TURN - 1, "venice", [{"type": "besiege", "army": "Doge Enrico", "settlement": "Milan"}])
    start_turn(lua, "venice")
    r = results(lua)[0]
    assert r["ok"] and "note" not in r
    assert report_of(lua).armies[0].besieging == "Milan"


def test_march_on_a_town_at_peace_from_the_next_tile_says_it_can_not_walk_in(lua):
    lua.execute(DOGE_BY_MILAN)  # venice and milan are at peace
    write_orders(lua, TURN - 1, "venice", [
        {"type": "march_on", "army": "Doge Enrico", "target_settlement": "Milan"}])
    start_turn(lua, "venice")
    assert calls(lua) == []
    r = results(lua)[0]
    assert not r["ok"] and "can't walk in" in r["reason"] and "besiege" in r["reason"]


def test_plain_besiege_keeps_maintaining(lua):
    autoplay(lua)
    lua.execute(DOGE_BY_MILAN)
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


def test_an_accepted_offer_presses_accept_never_decline(lua):
    # live 2026-10-27: the watched decline button's element was executed for an "accept"
    autoplay(lua)
    lua.execute("FAKE.campaign.currentFaction = FAKE.byName.hre; "
                "FAKE.open_scroll('diplomacy_decline_offer_button', {}); "
                "FAKE.open_scroll('diplomacy_accept_offer_button', {}); "
                "for _, n in ipairs({'diplomacy_decline_offer_button', 'diplomacy_accept_offer_button'}) do "
                "  FAKE.ui[n].execute = function() table.insert(FAKE.calls, 'press ' .. n) end "
                "end")
    tick(lua, 1)
    tick(lua, 3)
    req, _ = choice_request(lua)
    req.with_suffix(".answer").write_text("accept\n")
    tick(lua, 1)
    assert presses(lua) == ["press diplomacy_accept_offer_button"]


def test_a_watched_button_is_pressed_once_while_it_lingers(lua):
    # seen live: the game keeps the offer buttons after an answer; pressing decline again and
    # again made the AI reply each time ("No matter lord, perhaps something else?"). With no
    # answer from the ruler in time, the default is pressed.
    autoplay(lua)
    lua.execute("FAKE.campaign.currentFaction = FAKE.byName.sicily or FAKE.byName.hre; "
                "FAKE.open_scroll('diplomacy_decline_offer_button', {})")
    tick(lua, 5)  # seen
    tick(lua, 5)  # the ruler is asked
    tick(lua, 560)  # no answer in time (DECIDE_WAIT 540)
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


def test_the_battle_panels_auto_resolve_is_clicked_never_executed(lua):
    # live (2026-10-29 21:04): execute() on it hung the game (England defending, Battle Deployment)
    autoplay(lua)
    lua.execute("FAKE.campaign.currentFaction = FAKE.byName.hre; "
                "FAKE.ui.prebattle_auto_resolve_button = { elementName = 'prebattle_auto_resolve_button', "
                "execute = function() FAKE.calls[#FAKE.calls + 1] = 'press prebattle_auto_resolve_button' end }")
    tick(lua, 1)
    tick(lua, 50)  # a stuck-turn check presses the named buttons on screen
    assert "press prebattle_auto_resolve_button" not in presses(lua)
    assert "script select_ui_element prebattle_auto_resolve_button" in calls(lua)


def test_stuck_turn_presses_a_lingering_post_battle_tick(lua):
    # live: a bridge reload forgot the open scroll, and no named button closes it
    autoplay(lua)
    lua.execute("FAKE.campaign.currentFaction = FAKE.byName.hre; " + POST_BATTLE)
    tick(lua, 1)
    tick(lua, 50)
    assert presses(lua) == ["press tick"]


OVERVIEW = """
    local function part(name, x, y, w, h)
        return { elementName = name, xPos = x, yPos = y, xSize = w, ySize = h, subElementsNum = 0,
                 execute = function() FAKE.calls[#FAKE.calls + 1] = 'press ' .. (name ~= '' and name or ('@' .. x)) end }
    end
    local parts = { part('', 962, 528, 58, 65), part('', 978, 4, 42, 42), part('', 512, 0, 104, 63),
                    part('', 547, 63, 442, 465), part('family_tree_button', 558, 536, 42, 42) }
    FAKE.ui.combined_overview_scroll = { elementName = 'combined_overview_scroll', xPos = 512, yPos = 0,
        xSize = 512, ySize = 593, subElementsNum = #parts, getSubElement = function(self, i) return parts[i + 1] end }
"""


def test_stuck_turn_closes_the_faction_overview(lua):
    # live scan (a new campaign, 2026-10-29): the overview opened at the start held Scotland's
    # AI turn; its check is the unnamed 58x65 part at the bottom right, #1 is the help button
    autoplay(lua)
    lua.execute("FAKE.campaign.currentFaction = FAKE.byName.hre; " + OVERVIEW)
    tick(lua, 1)
    tick(lua, 50)
    assert presses(lua) == ["press @962"]
    assert "combined_overview_scroll's tick" in (lua.root / "parley_bridge.log").read_text()


def test_overview_a_watcher_opened_is_left_alone(lua):
    autoplay(lua)
    lua.execute("FAKE.campaign.currentFaction = FAKE.byName.hre; " + OVERVIEW)
    tick(lua, 1)
    assert presses(lua) == []


# the live scan (ui_scan-france-s-turn.txt, 2026-10-30 11:00:45) of the spy report a successful
# spy mission opened: "enemy_settlement_info_scroll: #0 @978,4 42x42, garrison_info_zoom_to_button
# @516,543 42x42, #2 @512,0 442x85, #3 @547,85 442x474, #4 @566,98 404x452, #5 @962,528 58x65",
# frame @512,0 512x593. The agent and garrison portraits (unnamed, button-sized) sit inside #4.
SPY_REPORT = """
    local function part(name, x, y, w, h, kids)
        kids = kids or {}
        return { elementName = name, xPos = x, yPos = y, xSize = w, ySize = h, subElementsNum = #kids,
                 getSubElement = function(self, i) return kids[i + 1] end,
                 execute = function() FAKE.calls[#FAKE.calls + 1] = 'press ' .. (name ~= '' and name or ('@' .. x)) end }
    end
    local inner = { part('enemy_garrison_display', 567, 236, 42, 56, { part('', 567, 236, 42, 56) }),
                    part('enemy_agents_display', 567, 367, 42, 56, { part('', 567, 367, 42, 56) }) }
    local parts = { part('', 978, 4, 42, 42), part('garrison_info_zoom_to_button', 516, 543, 42, 42),
                    part('', 512, 0, 442, 85), part('', 547, 85, 442, 474),
                    part('', 566, 98, 404, 452, inner), part('', 962, 528, 58, 65) }
    FAKE.ui.enemy_settlement_info_scroll = { elementName = 'enemy_settlement_info_scroll', xPos = 512,
        yPos = 0, xSize = 512, ySize = 593, subElementsNum = #parts,
        getSubElement = function(self, i) return parts[i + 1] end }
"""


def test_stuck_turn_closes_the_spy_report(lua):
    # live 2026-10-30: England's spy report held France's turn; 12 tries said "no known popup open"
    autoplay(lua)
    lua.execute("FAKE.campaign.currentFaction = FAKE.byName.hre; " + SPY_REPORT)
    tick(lua, 1)
    tick(lua, 50)
    assert presses(lua) == ["press @962"]  # the check, not the zoom button or a portrait
    assert "enemy_settlement_info_scroll's tick" in (lua.root / "parley_bridge.log").read_text()


def test_spy_report_a_watcher_opened_is_left_alone(lua):
    autoplay(lua)
    lua.execute("FAKE.campaign.currentFaction = FAKE.byName.hre; " + SPY_REPORT)
    tick(lua, 1)
    assert presses(lua) == []


SPY_MISSION = ("BRIDGE.on_agent_mission('spying', {{ faction = FAKE.byName.{who}, missionSuccessLevel = "
               "'storm', missionProbability = 25, character = {{ fullName = 'Ambrose Churborne' }} }}, true)")


def test_a_rulers_spy_mission_closes_its_report_at_once(lua):
    # live 2026-10-30 11:00:13: the mission event came 16 s before the stuck-turn check began
    autoplay(lua)
    lua.execute("FAKE.campaign.currentFaction = FAKE.byName.hre; " + SPY_MISSION.format(who="venice"))
    lua.execute(SPY_REPORT)
    tick(lua, 1)
    assert presses(lua) == []  # left up a moment, for a watcher
    tick(lua, 3)
    assert presses(lua) == ["press @962"]
    assert "closed the spy report after venice's mission" in (lua.root / "parley_bridge.log").read_text()
    lua.execute("FAKE.ui.enemy_settlement_info_scroll = nil")  # the press closed it
    tick(lua, 50)
    assert presses(lua) == ["press @962"]  # once
    assert lua.eval("BRIDGE.spy_report") is None


def test_a_spy_report_slow_to_open_is_still_closed(lua):
    # a scroll can be "not found" the moment it opens and found seconds later (the siege panel)
    autoplay(lua)
    lua.execute("FAKE.campaign.currentFaction = FAKE.byName.hre; " + SPY_MISSION.format(who="venice"))
    tick(lua, 4)
    tick(lua, 4)
    assert presses(lua) == []  # nothing open: nothing pressed, nothing broken
    lua.execute(SPY_REPORT)
    tick(lua, 4)
    assert presses(lua) == ["press @962"]


def _ended(lua):
    return "autoplay: ending turn" in (lua.root / "parley_bridge.log").read_text()


def test_end_turn_waits_for_the_spy_report_of_a_successful_mission(lua):
    # live 2026-10-30 (18:54, 20:53, 21:37): the ruler's spy mission succeeded and autoplay ended the
    # turn 0-1 s later; no spy report was ever seen. When the turn didn't end at once (17:58, 18:16,
    # 19:41) the report opened within 4 s and was closed. End Turn now waits for it.
    autoplay(lua)
    write_orders(lua, TURN - 1, "venice", [])
    start_turn(lua, "venice")
    lua.execute(SPY_MISSION.format(who="venice"))
    tick(lua, 1)
    assert not _ended(lua)
    lua.execute(SPY_REPORT)
    tick(lua, 3)
    assert presses(lua) == ["press @962"]
    assert not _ended(lua)  # the close is pressed this tick; End Turn comes on a later one
    lua.execute("FAKE.ui.enemy_settlement_info_scroll = nil")
    tick(lua, 1)
    assert _ended(lua)


def test_end_turn_waits_no_longer_than_the_spy_report_wait(lua):
    autoplay(lua)
    write_orders(lua, TURN - 1, "venice", [])
    start_turn(lua, "venice")
    lua.execute(SPY_MISSION.format(who="venice"))
    for _ in range(6):
        tick(lua, 5)
    assert not _ended(lua)
    tick(lua, 5)
    tick(lua, 1)
    assert "no spy report open within 30s" in (lua.root / "parley_bridge.log").read_text()
    assert _ended(lua)


def test_a_failed_spy_mission_holds_no_end_turn(lua):
    autoplay(lua)
    write_orders(lua, TURN - 1, "venice", [])
    start_turn(lua, "venice")
    lua.execute(SPY_MISSION.format(who="venice").replace("'storm'", "'earthquake'"))
    tick(lua, 1)
    assert _ended(lua)


def test_no_spy_report_gives_up_quietly(lua):
    autoplay(lua)
    lua.execute("FAKE.campaign.currentFaction = FAKE.byName.hre; " + SPY_MISSION.format(who="venice"))
    for _ in range(10):
        tick(lua, 5)
    assert "no spy report open within 30s" in (lua.root / "parley_bridge.log").read_text()
    lua.execute(SPY_REPORT)  # one opened later (a watcher) is not the mission's
    tick(lua, 1)
    assert presses(lua) == []


def test_an_ai_factions_spy_mission_looks_for_no_report(lua):
    # the AI's spy missions (many a turn) open no scroll
    autoplay(lua)
    lua.execute("FAKE.campaign.currentFaction = FAKE.byName.hre; " + SPY_MISSION.format(who="milan"))
    lua.execute(SPY_REPORT)
    tick(lua, 4)
    assert presses(lua) == []


def test_other_missions_look_for_no_spy_report(lua):
    autoplay(lua)
    lua.execute("FAKE.campaign.currentFaction = FAKE.byName.hre; "
                + SPY_MISSION.format(who="venice").replace("'spying'", "'assassination'"))
    lua.execute(SPY_REPORT)
    tick(lua, 4)
    assert presses(lua) == []


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


def test_reload_during_a_frozen_turn_lets_the_game_ai_go(lua):
    # live, 10-30 turn 44: a reload 4 s into France's frozen turn lost the 15 s release timer
    # with the old Lua state, and the turn never ended
    frozen_milan(lua)
    assert lua.eval("FAKE.byName.milan.freezeFactionAI") == 1
    lua.execute("M2TWEOP.restartLua = function() end; M2TWEOP.toggleConsole = function() end")
    (lua.root / "control.txt").write_text("reload\n")
    tick(lua)
    assert lua.eval("FAKE.byName.milan.freezeFactionAI") == 0


def test_a_stale_reload_marker_leaves_the_console_alone(lua):
    # seen live: a marker left by a reload that never ran opened the console at game start
    lua.execute("TOGGLES = 0; M2TWEOP.toggleConsole = function() TOGGLES = TOGGLES + 1 end")
    (lua.root / "reloaded.txt").write_text("turn=99\n")
    lua.execute(f"BRIDGE.setup('{lua.root}')")
    assert lua.eval("TOGGLES") == 0 and not (lua.root / "reloaded.txt").exists()


def test_a_second_offer_on_the_open_diplomacy_screen_goes_to_the_ruler(lua):
    # live run9 turn 33 (03:53): the Moors' offer declined, then Portugal's offer on the same open
    # screen; its buttons were never pressed and the turn stuck until a hand declined it
    autoplay(lua)
    lua.execute("FAKE.campaign.currentFaction = FAKE.byName.hre; FAKE.open_scroll('diplomacy_scroll', {''}); "
                "FAKE.open_scroll('diplomacy_decline_offer_button', {})")
    tick(lua, 1)
    tick(lua, 5)
    req, _ = choice_request(lua)
    req.with_suffix(".answer").write_text("decline")
    for _ in range(8):
        tick(lua, 5)
    assert "a new offer: asking the ruler again" in bridge_log(lua)
    # (a popup-*-m*.req is the stuck-turn minimized-message question, not the offer)
    [req2] = [p for p in lua.root.glob("popup-*.req") if "-m" not in p.name]
    assert req2 != req
    req2.with_suffix(".answer").write_text("accept")
    for _ in range(3):
        tick(lua, 5)
    assert "script select_ui_element diplomacy_accept_offer_button" in calls(lua), calls(lua)


def test_a_lingering_offer_is_asked_again_at_most_twice(lua):
    autoplay(lua)
    lua.execute("FAKE.campaign.currentFaction = FAKE.byName.hre; FAKE.open_scroll('diplomacy_scroll', {''}); "
                "FAKE.open_scroll('diplomacy_decline_offer_button', {})")
    for _ in range(300):
        tick(lua, 5)
    assert bridge_log(lua).count("a new offer: asking the ruler again") == 2


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


def test_a_papal_election_result_is_never_pressed_by_shape(lua):
    # live: the game crashed three times right after a result scroll that didn't close by itself
    autoplay(lua)
    lua.execute("""
        local function part(name, x, y, w, h)
            return { elementName = name, xPos = x, yPos = y, xSize = w, ySize = h, subElementsNum = 0,
                     execute = function() FAKE.calls[#FAKE.calls + 1] = 'press ' .. (name ~= '' and name or ('@' .. x)) end }
        end
        local parts = { part('', 900, 40, 42, 42), part('', 520, 430, 42, 42) }
        FAKE.ui.papal_election_results_scroll = { elementName = 'papal_election_results_scroll', xPos = 250,
            yPos = 20, xSize = 520, ySize = 460, subElementsNum = #parts, getSubElement = function(self, i) return parts[i + 1] end }
    """)
    lua.execute("BRIDGE.on_scroll_opened('papal_election_results_scroll')")
    tick(lua, 5)
    tick(lua, 50)  # long enough for a stuck-turn check too
    assert not any(p.startswith("press @") for p in presses(lua))


PAPAL = ("papal_election_scroll", "papal_election_results_scroll")


def papal_lookups(lua):
    return [n for n in (lua.eval("table.concat(FAKE.lookups, ',')") or "").split(",") if "papal" in n]


def open_papal(lua, scroll, times=2):
    for _ in range(times):  # live, the game fires onScrollOpened twice for each papal scroll
        lua.execute(f"BRIDGE.on_scroll_opened({{ resourceDescription = '{scroll}' }})")


def test_a_papal_result_leaves_a_step_trace_and_a_counter(lua):
    autoplay(lua)
    lua.execute("FAKE.open_scroll('papal_election_results_scroll', {''})")
    open_papal(lua, "papal_election_results_scroll")
    log = (lua.root / "parley_bridge.log").read_text()
    assert "papal-trace:" in log and "onScrollOpened: event received; no UI call" in log
    assert "already queued; ignored" in log  # the event's second firing
    state = (lua.root / "papal_trace.txt").read_text()
    assert "n=1" in state and "done=0" in state and "scroll=papal_election_results_scroll" in state
    tick(lua, 50)  # the popup is handled; the trace closes
    assert "done=1" in (lua.root / "papal_trace.txt").read_text()


def test_a_papal_scroll_event_makes_no_ui_call(lua):
    # live 10-30 08:41:52, 18:34:11 and 19:04:51: the game hung each time right after the bridge
    # looked up papal_election_results_scroll inside its open event (found=false: still being
    # built); the event's second firing never came. The bridge now only queues it.
    autoplay(lua)
    lua.execute("FAKE.open_scroll('papal_election_scroll', {'vote_button'}); "
                "FAKE.open_scroll('papal_election_results_scroll', {''})")
    for scroll in PAPAL:
        open_papal(lua, scroll)
    assert lua.eval("#FAKE.lookups") == 0
    log = (lua.root / "parley_bridge.log").read_text()
    for scroll in PAPAL:
        assert f"popup {scroll}: opened; left to the game (no UI call)" in log


def test_papal_scrolls_are_never_looked_up_while_they_are_up(lua):
    # not by the message sweep, the stuck-turn check, its UI scan, or the result's own handling
    autoplay(lua)
    (lua.root / "ui_names.txt").write_text("papal_election_scroll\npapal_election_results_scroll\nend_turn\n")
    lua.execute("FAKE.open_scroll('papal_election_scroll', {'vote_button', 'close_tick_button'}); "
                "FAKE.open_scroll('papal_election_results_scroll', {'close_tick_button'}); "
                "FAKE.open_scroll('end_turn', {})")
    write_orders(lua, TURN - 1, "venice", [])
    start_turn(lua, "venice")
    tick(lua)
    open_papal(lua, "papal_election_scroll")
    lua.execute("BRIDGE.on_message({ eventID = 202 })")  # the election's notice
    tick(lua, 5)
    capture_all(lua)
    open_papal(lua, "papal_election_results_scroll")
    for _ in range(8):  # stuck-turn checks (and their UI scan) come round
        tick(lua, 21)
        capture_all(lua)
    assert papal_lookups(lua) == []
    assert not any(p in ("press vote_button", "press close_tick_button") for p in presses(lua))
    scans = list(lua.root.glob("ui_scan-*.txt"))
    assert scans and "papal" not in scans[0].read_text()  # the scan ran, without them


def reqs_of(lua):
    return [json.loads(p.read_text()) for p in lua.root.glob("popup-*.req")]


def test_nothing_is_touched_while_the_papal_notice_waits_for_its_election(lua):
    # live 10-30 19:41:55 (qa-covert turn 48): message 202 (the Pope is dead, the cardinals
    # convene) came with End Turn; the sweep cleared message 40 two seconds later and the
    # election never opened (live 18:16, 18:33 and 10-29 18:30 too). Left alone, it opened 3-6 s
    # after 202 (18:54:16, 19:04:51, 19:47:03).
    autoplay(lua)
    lua.execute("BRIDGE.on_message({ eventID = 40 })")
    tick(lua, 2)
    lua.execute("BRIDGE.on_message({ eventID = 201 }); BRIDGE.on_message({ eventID = 202 })")
    for _ in range(4):
        tick(lua, 2)
        capture_all(lua)
    assert "script clear_messages " not in calls(lua)
    assert reqs_of(lua) == []  # nothing asked of the turn loop: no check pressed either
    assert lua.eval("BRIDGE.deciding()")  # stuck-turn checks wait too
    open_papal(lua, "papal_election_scroll")
    for _ in range(3):
        tick(lua, 2)
        capture_all(lua)
    assert "script clear_messages " not in calls(lua)  # still hands off: the papal window
    open_papal(lua, "papal_election_results_scroll")
    for _ in range(6):
        tick(lua, 2)
        capture_all(lua)
    assert "script clear_messages " in calls(lua)  # message 40, once the result has closed
    log = (lua.root / "parley_bridge.log").read_text()
    assert "papal notice: hands off until the election opens" in log


def test_the_papal_notice_is_never_cleared(lua):
    # live 19:42:13, 19:43:33, 19:44:53: clearing 202 never opened the election
    autoplay(lua)
    open_papal(lua, "papal_election_scroll")  # (election already up: no wait)
    lua.execute("BRIDGE.on_message({ eventID = 202 })")
    for _ in range(4):
        tick(lua, 2)
        capture_all(lua)
    open_papal(lua, "papal_election_results_scroll")
    asked = []
    for _ in range(8):  # the papal window closes 10 s after the result
        tick(lua, 4)
        asked.extend(reqs_of(lua))
        capture_all(lua)
    tick(lua, 31)
    assert "script clear_messages " not in calls(lua)
    # read for the ruler, its check not pressed: the election it opens is over
    assert [r.get("press_check") for r in asked if r.get("event") == 202] == [None]
    log = (lua.root / "parley_bridge.log").read_text()
    assert "game message 202 (left to the game: the papal election's notice)" in log


def test_with_no_election_the_papal_notice_is_sent_to_have_its_check_pressed(lua):
    # live 18:34:05-11 and 18:17:01-04: the notice reopened and its check pressed opened the election
    autoplay(lua)
    lua.execute("BRIDGE.on_message({ eventID = 202 })")
    tick(lua, 10)
    assert reqs_of(lua) == []
    tick(lua, 6)  # past the wait: the game didn't open it
    tick(lua, 1)
    [r] = reqs_of(lua)
    assert r["event"] == 202 and r["press_check"] is True
    assert lua.eval("BRIDGE.deciding()")  # the papal window: no stuck-turn reopen yet
    tick(lua, 30)  # 47 s: the election never came; the stuck-turn check may reopen it again
    assert not lua.eval("BRIDGE.deciding()")
    log = (lua.root / "parley_bridge.log").read_text()
    assert "papal notice: no election after 15s; asking for its check" in log


# --- the papal window: from the Pope's death notice until the result has closed ------------
# live 10-30: the game died at 18:34:11, 19:04:51, 20:06:30 and 20:48:34, each time with a turn
# loop click in the same second as a papal scroll opening. The bridge tells the turn loop
# (papal_window.txt) and holds its own requests and stuck-turn checks meanwhile.

def papal_window(lua):
    path = lua.root / "papal_window.txt"
    return path.read_text() if path.exists() else None


def test_the_papal_window_runs_from_the_notice_until_the_result_has_closed(lua):
    autoplay(lua)
    lua.execute("BRIDGE.on_message({ eventID = 202 })")
    assert "phase=notice" in papal_window(lua)
    tick(lua, 4)
    open_papal(lua, "papal_election_scroll")
    assert "phase=vote" in papal_window(lua)
    lua.execute("BRIDGE.on_message({ eventID = 202 })")  # a reopened notice doesn't undo the vote
    assert "phase=vote" in papal_window(lua)
    tick(lua, 20)
    capture_all(lua)  # the ruler voted
    tick(lua, 1)
    assert lua.eval("BRIDGE.deciding()")
    open_papal(lua, "papal_election_results_scroll")
    assert "phase=results" in papal_window(lua)
    tick(lua, 5)
    assert papal_window(lua) is not None and lua.eval("BRIDGE.deciding()")
    tick(lua, 6)
    assert papal_window(lua) is None and not lua.eval("BRIDGE.deciding()")
    log = (lua.root / "parley_bridge.log").read_text()
    assert "papal window: results" in log and "papal window: closed" in log


def test_a_result_with_no_notice_opens_the_papal_window(lua):
    # live 20:48:34 and 20:56:36 (turn 59): a result with no election shown to England first
    autoplay(lua)
    open_papal(lua, "papal_election_results_scroll")
    assert "phase=results" in papal_window(lua)
    assert lua.eval("BRIDGE.deciding()")


def test_popups_wait_for_the_papal_window_to_close(lua):
    # live 20:06:27-30: a clear_messages and a check pressed while the election opened
    autoplay(lua)
    open_papal(lua, "papal_election_scroll")
    lua.execute("BRIDGE.on_message({ eventID = 40 })")
    asked = []

    def run(n, step):
        for _ in range(n):
            tick(lua, step)
            asked.extend(reqs_of(lua))
            capture_all(lua)
    run(10, 3)
    assert [r["kind"] for r in asked] == ["vote"]  # the vote, and nothing else
    assert "script clear_messages " not in calls(lua)
    open_papal(lua, "papal_election_results_scroll")
    run(3, 2)
    assert [r.get("event") for r in asked if r["kind"] != "vote"] == []
    run(4, 3)  # the result closed 10 s ago: back to normal
    assert 40 in [r.get("event") for r in asked]


def test_a_request_out_when_the_papal_window_opens_gets_its_full_wait_after_it(lua):
    # the turn loop holds it through the window; it mustn't time out the moment the window closes
    autoplay(lua)
    lua.execute("BRIDGE.on_message({ eventID = 40 })")
    tick(lua, 5)
    [r] = reqs_of(lua)
    open_papal(lua, "papal_election_scroll")
    tick(lua, 60)
    capture_all(lua)  # the vote (only the vote: the reading waits)
    (lua.root / f"{r['id']}.done").unlink()
    open_papal(lua, "papal_election_results_scroll")
    tick(lua, 11)
    assert (lua.root / f"{r['id']}.req").exists()  # still asked for, after the window
    log = (lua.root / "parley_bridge.log").read_text()
    assert "the turn loop didn't capture it in time" not in log


def test_the_papal_window_survives_a_bridge_reload(lua):
    # live 20:20:56: the bridge reloaded a second before the election opened
    autoplay(lua)
    now = lua.eval("FAKE.now")
    (lua.root / "papal_window.txt").write_text(f"phase=vote\nuntil={now + 30}\n")
    lua.execute(f"BRIDGE.setup('{lua.root.as_posix()}')")
    assert lua.eval("BRIDGE.deciding()")
    (lua.root / "papal_window.txt").write_text(f"phase=vote\nuntil={now - 1}\n")  # over
    lua.execute(f"BRIDGE.setup('{lua.root.as_posix()}')")
    tick(lua, 1)
    assert not lua.eval("BRIDGE.deciding()") and papal_window(lua) is None


def test_the_vote_is_asked_once_though_the_event_fires_twice(lua):
    # live 18:17:42 and 18:17:57: two vote requests, the second clicked after the result was up
    autoplay(lua)
    open_papal(lua, "papal_election_scroll")
    tick(lua, 5)
    reqs = [json.loads(p.read_text()) for p in lua.root.glob("popup-*.req")]
    assert [r["kind"] for r in reqs] == ["vote"]


def test_a_papal_result_is_left_to_close_by_itself(lua):
    autoplay(lua)
    lua.execute("FAKE.open_scroll('papal_election_results_scroll', {'close_tick_button'})")
    open_papal(lua, "papal_election_results_scroll")
    tick(lua, 5)
    log = (lua.root / "parley_bridge.log").read_text()
    assert "a papal election's result (papal_election_results_scroll, closed by itself)" in log
    assert presses(lua) == [] and papal_lookups(lua) == []


def test_a_trace_left_open_is_reported_after_a_relaunch(lua):
    (lua.root / "papal_trace.txt").write_text(
        "n=4\nseq=9\ndone=0\nturn=57\nlast=handle: calling scriptCommand('clear_messages')\n"
        "scroll=message:7\nat=2026-10-30 10:00:00\n")
    lua.execute(f"BRIDGE.setup('{lua.root.as_posix()}')")
    log = (lua.root / "parley_bridge.log").read_text()
    assert "PREVIOUS RUN ENDED MID-STEP" in log and "papal scrolls so far: 4" in log and "clear_messages" in log


def test_a_message_presses_whichever_game_popup_is_open(lua):
    autoplay(lua)
    lua.execute("FAKE.open_scroll('mission_target_scroll', {'zoom_to_button', 'close_tick_button'}); "
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


# --- End Turn waits for the ruler's answer to an offer --------------------------------------
# Live 10-30 20:48:04, 20:55:59, 22:28:31 (QA field, turns 59 and 62): a marriage offer came up at
# England's turn start, the bridge ended the turn 1-2 s later with it unanswered, the AI turns
# stalled behind the open scroll (no event for ~30 s), and the decline click released a papal
# results scroll and the deferred End Turn together; the game died 5 s later twice out of three.


def offer_marriage(lua):
    lua.execute("""
        local c = { fullName = 'Jacob', age = 30, getTraits = function() return nil end }
        BRIDGE.on_offered_for_marriage({ character = c, faction = FAKE.byName.venice })
    """)


def test_end_turn_waits_until_the_ruler_has_answered_an_offer(lua):
    autoplay(lua)
    write_orders(lua, TURN - 1, "venice", [])
    start_turn(lua, "venice")
    offer_marriage(lua)
    tick(lua, 5)
    tick(lua, 5)
    assert calls(lua) == []  # the offer is with the ruler: no End Turn under it
    [req] = list(lua.root.glob("popup-*.req"))
    req.with_suffix(".done").write_text("")  # the turn loop clicked the ruler's answer
    tick(lua, 2)
    assert calls(lua) == END_TURN
    log = (lua.root / "parley_bridge.log").read_text()
    assert "holding End Turn until the ruler answers a marriage offer" in log


def test_end_turn_hold_for_an_offer_is_bounded(lua):
    autoplay(lua)
    write_orders(lua, TURN - 1, "venice", [])
    start_turn(lua, "venice")
    offer_marriage(lua)
    start = lua.eval("FAKE.now")
    tick(lua, 5)
    [req] = list(lua.root.glob("popup-*.req"))
    req.with_suffix(".hold").write_text("")  # the turn loop has it, and never answers
    for _ in range(130):
        tick(lua, 5)
        if calls(lua):
            break
    assert calls(lua) == END_TURN
    assert lua.eval("FAKE.now") - start <= 560  # DECIDE_WAIT (540) plus a little, never forever


def test_end_turn_hold_has_its_own_cap(lua):
    # a decision entry that never settles (whatever the cause) still can't hold the turn forever
    autoplay(lua)
    write_orders(lua, TURN - 1, "venice", [])
    start_turn(lua, "venice")
    offer_marriage(lua)
    lua.execute("BRIDGE.K.DECISION_HOLD_MAX = 20")
    for _ in range(3):
        tick(lua, 5)
    assert calls(lua) == []
    tick(lua, 10)
    assert calls(lua) == END_TURN
    assert "ending it anyway" in (lua.root / "parley_bridge.log").read_text()


def test_end_turn_hold_for_offers_can_be_switched_off(lua):
    autoplay(lua, "autoplay_hold_decisions=0\n")
    write_orders(lua, TURN - 1, "venice", [])
    start_turn(lua, "venice")
    offer_marriage(lua)
    tick(lua, 5)
    assert calls(lua) == END_TURN


def test_an_ai_factions_offer_doesnt_hold_end_turn(lua):
    autoplay(lua)
    write_orders(lua, TURN - 1, "venice", [])
    start_turn(lua, "venice")
    lua.execute("""
        local c = { fullName = 'Yusuf', age = 30, getTraits = function() return nil end }
        BRIDGE.on_offered_for_marriage({ character = c, faction = FAKE.byName.milan })
    """)
    tick(lua, 5)
    assert calls(lua) == END_TURN


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


def test_merge_units_reports_refusal_when_nothing_can_combine(lua):
    # live: "england merge_units garrison:Edinburgh: 0 soldiers moved, 0 units disbanded"
    # four turns running, each result "done", and the ruler kept ordering it
    lua.execute("""
        local st = FAKE.byName.venice.stacks[1]
        local units = {}
        local function unit(kind, n, max)
            units[#units + 1] = { eduEntry = { eduType = kind }, soldierCountStratMap = n,
                                 soldierCountStratMapMax = max, exp = 0, armourLVL = 0, weaponLVL = 0 }
        end
        unit('Hobilars', 40, 40)
        unit('Peasant Archers', 30, 60)
        st.getUnit = function(self, i) return units[i + 1] end
        st.numOfUnits = #units
        FAKE.units = units
    """)
    write_orders(lua, TURN - 1, "venice", [{"type": "merge_units", "army": "Doge Enrico"}])
    start_turn(lua, "venice")
    [r] = json.loads((turn_dir(lua, TURN - 1, "venice") / "results.json").read_text())
    assert not r["ok"]
    assert "nothing to merge in Doge Enrico: no two worn units of one type that can combine" in r["reason"]


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
    assert [(s.region, s.x, s.y) for s in c.shores] == [("region10", 124, 94), ("region11", 125, 94)]
    p = build_prompt(r, persona="p")
    assert "LAND CROSSINGS NEAR YOU (an army walks across the water here, no ships needed: move_army onto the land tile on the far side)" in p
    assert "joining region10 (124,94) and region11 (125,94)" in p
    # old reports without shores continue to work
    r_old = r.model_copy(update={"crossings": [Crossing(x=125, y=95, regions=["region10", "region11"], distance=10)]})
    assert "joining region10 and region11" in build_prompt(r_old, persona="p")


def test_land_crossings_on_eop_master_come_from_the_connection_list(lua):
    # EOP master has no tile.isLandConnection: stratMap.landConnectionsNum + getLandConnection(i)
    lua.execute("""
        local base = FAKE.stratMap.getTile
        FAKE.stratMap.getTile = function(x, y)
            local t = base(x, y)
            t.regionID = x < 125 and 10 or 11
            t.isLand = (y == 95 and (x == 124 or x == 125)) and 0 or 1
            return t
        end
        FAKE.stratMap.mapWidth, FAKE.stratMap.mapHeight = 140, 100
        FAKE.stratMap.landConnectionsNum = 2
        FAKE.stratMap.getLandConnection = function(self, i)
            return ({ [0] = { xCoord = 124, yCoord = 95 }, [1] = { xCoord = 125, yCoord = 95 } })[i]
        end
    """)
    r = report_of(lua)
    [c] = r.crossings
    assert (c.x, c.y) in ((124, 95), (125, 95)) and c.regions == ["region10", "region11"]
    assert [(s.region, s.x, s.y) for s in c.shores] == [("region10", 124, 94), ("region11", 125, 94)]
    p = build_prompt(r, persona="p")
    assert "LAND CROSSINGS NEAR YOU (an army walks across the water here, no ships needed: move_army onto the land tile on the far side)" in p
    assert "joining region10 (124,94) and region11 (125,94)" in p
    # old reports without shores continue to work
    r_old = r.model_copy(update={"crossings": [Crossing(x=125, y=95, regions=["region10", "region11"], distance=10)]})
    assert "joining region10 and region11" in build_prompt(r_old, persona="p")


def test_report_gives_settlement_tiles_ports_training_and_income_items(lua):
    write_orders(lua, TURN - 1, "venice", [])
    (turn_dir(lua, TURN, "venice").parent.parent / "training.json").write_text(json.dumps(
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


def test_stuck_retry_represses_button_in_pressed_that_is_still_on_screen(lua):
    autoplay(lua)
    lua.execute("FAKE.campaign.currentFaction = FAKE.byName.milan")
    lua.execute("FAKE.open_scroll('siege_maintain_button', {})")
    lua.execute("BRIDGE.pressed['siege_maintain_button'] = true")
    tick(lua)
    tick(lua, 31)
    assert "script select_ui_element siege_maintain_button" not in calls(lua)
    tick(lua, 31)
    assert "script select_ui_element siege_maintain_button" in calls(lua)


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


def test_freeze_sets_the_seats_game_ai_frozen_each_turn(lua):
    (lua.root / "bridge.txt").write_text("game_id=g1\nfaction=venice\nfaction=milan\nfreeze=milan\n")
    lua.execute("FAKE.byName.milan.isPlayerControlled = 0; FAKE.byName.venice.isPlayerControlled = 0; "
                "FAKE.byName.venice.freezeFactionAI = 1")
    start_turn(lua, "milan")
    start_turn(lua, "venice")
    assert lua.eval("FAKE.byName.milan.freezeFactionAI") == 1
    assert lua.eval("FAKE.byName.venice.freezeFactionAI") == 0  # not listed: unfrozen
    assert "milan: game AI frozen" in (lua.root / "parley_bridge.log").read_text()


def frozen_milan(lua):
    (lua.root / "bridge.txt").write_text("game_id=g1\nfaction=venice\nfaction=milan\nfreeze=milan\n")
    lua.execute("BRIDGE.clock = function() return FAKE.now end; FAKE.byName.milan.isPlayerControlled = 0")
    start_turn(lua, "milan")


def frame(lua, seconds):
    lua.execute(f"FAKE.now = FAKE.now + {seconds}; BRIDGE.on_frame()")


def test_a_frozen_seats_turn_that_runs_too_long_unfreezes_its_ai(lua):
    # live, turn 20: a frozen AI never answered its own siege and the turn never ended
    frozen_milan(lua)
    frame(lua, 2)  # M.FROZEN_TURN_LIMIT is 3 s (11-05: a released AI ends its turn at once)
    assert lua.eval("FAKE.byName.milan.freezeFactionAI") == 1
    frame(lua, 5)
    assert lua.eval("FAKE.byName.milan.freezeFactionAI") == 0
    assert "milan: turn still running" in (lua.root / "parley_bridge.log").read_text()
    start_turn(lua, "milan")  # its next turn: frozen again
    assert lua.eval("FAKE.byName.milan.freezeFactionAI") == 1


def test_a_frozen_seats_turn_that_ends_in_time_stays_frozen(lua):
    frozen_milan(lua)
    lua.execute("BRIDGE.on_turn_end(FAKE.byName.milan)")
    frame(lua, 60)
    assert lua.eval("FAKE.byName.milan.freezeFactionAI") == 1


def test_freeze_star_freezes_every_ai_faction_but_the_thawed_and_the_player(lua):
    # the QA bench's quiet world: no seat needed, a thawed faction (a case's `needs`) acts
    (lua.root / "bridge.txt").write_text("game_id=g1\nfaction=venice\nfreeze=*\nthaw=milan\n")
    lua.execute("FAKE.byName.venice.isPlayerControlled = 1; FAKE.byName.milan.isPlayerControlled = 0; "
                "FAKE.byName.hre.isPlayerControlled = 0; FAKE.byName.milan.freezeFactionAI = 1")
    for f in ("venice", "milan", "hre"):
        start_turn(lua, f)
    assert lua.eval("FAKE.byName.hre.freezeFactionAI") == 1  # no seat, still frozen
    assert lua.eval("FAKE.byName.milan.freezeFactionAI") == 0  # thawed
    assert not lua.eval("FAKE.byName.venice.freezeFactionAI")  # the player is never touched
    assert "hre: game AI frozen" in bridge_log(lua)


def test_a_plain_config_thaws_an_ai_faction_the_bench_left_frozen(lua):
    lua.execute("FAKE.byName.hre.isPlayerControlled = 0; FAKE.byName.hre.freezeFactionAI = 1")
    start_turn(lua, "hre")
    assert lua.eval("FAKE.byName.hre.freezeFactionAI") == 0
    assert "hre: game AI unfrozen" in bridge_log(lua)


def test_a_bench_frozen_factions_turn_that_runs_too_long_lets_go(lua):
    (lua.root / "bridge.txt").write_text("game_id=g1\nfaction=venice\nfreeze=*\n")
    lua.execute("BRIDGE.clock = function() return FAKE.now end; FAKE.byName.hre.isPlayerControlled = 0")
    start_turn(lua, "hre")
    frame(lua, 20)
    assert lua.eval("FAKE.byName.hre.freezeFactionAI") == 0
    assert "hre: turn still running" in bridge_log(lua)


def test_qa_report_writes_the_factions_report_for_the_turn_before(lua):
    # after the bench save loads nothing has reported; the cases' targets come from this report
    path = lua.eval("BRIDGE.qa.report('venice')")
    assert path.endswith(f"g1/turn-{TURN - 1:04d}/venice/state.json")
    r = StateReport.model_validate_json((turn_dir(lua, TURN - 1, "venice") / "state.json").read_text())
    assert r.faction == "venice"
    assert "qa: report ok:" in bridge_log(lua)
    assert lua.eval("BRIDGE.qa.report('venice', 3)").endswith("turn-0003/venice/state.json")
    assert lua.eval("BRIDGE.qa.report('nobody')") is None
    assert "qa: report failed: " in bridge_log(lua)


def test_building_queue_on_eop_master_never_reads_past_its_end(lua):
    # master's getBuildingInQueue(i) is head+i: i = n was an empty slot whose name read crashed
    # the game (live, scratch2); item 1 can't be reached, items 2..n are i = 1..n-1
    control(lua)
    lua.execute("""
        FAKE.stratMap.landConnectionsNum = 0
        local q = FAKE.settlements.Venice.buildingsQueue
        q.numBuildingsInQueue = 3
        local items = { [1] = "market", [2] = "farms" }   -- head+1, head+2
        q.getBuildingInQueue = function(self, pos)
            if pos >= 3 then error("read past the queue's end") end
            if pos <= 0 then return nil end
            return { getQueueBuildingName = function() return items[pos] end }
        end
    """)
    venice = report_of(lua).settlements[0]
    assert venice.queue[0].startswith("(the building under construction")
    assert venice.queue[1:] == ["market", "farms"]


def test_eop_master_reports_treaties_and_turns_in_stance(lua):
    # campaign:getFactionDiplomacy(a, b) is master only (types/campaign.h:675): nil outside 0..30
    lua.execute("""
        FAKE.stratMap.landConnectionsNum = 0
        local v, m = FAKE.byName.venice.factionID, FAKE.byName.milan.factionID
        local d = { [v] = { [m] = { hasTradeRights = true, hasMilitaryAccess = false,
                                    isProtectorate = false, numTurnsState = 7 } },
                    [m] = { [v] = { isProtectorate = true } } }
        FAKE.campaign.getFactionDiplomacy = function(self, a, b) return d[a] and d[a][b] end
    """)
    milan = next(f for f in report_of(lua).factions if f.id == "milan")
    assert milan.treaties == ["trade rights", "protectorate"] and milan.turns_in_stance == 7


def test_eop_master_reports_the_recruitment_queue_inside_its_count(lua):
    # getUnitInQueue(i) is 0-based with no bounds check (types/settlement.h:743)
    control(lua)
    lua.execute("""
        FAKE.stratMap.landConnectionsNum = 0
        local s = FAKE.settlements.Venice
        s.unitInQueueCount = 2
        local q = { [0] = { recruitType = 0, eduEntry = { eduType = "Peasants" }, recruitTime = 2, turnsTrained = 1 },
                    [1] = { recruitType = 2, recruitTime = 1, turnsTrained = 0 } }
        s.getUnitInQueue = function(self, i)
            if i < 0 or i >= 2 then error("read past the queue's end") end
            return q[i]
        end
    """)
    assert report_of(lua).settlements[0].recruit_queue == ["Peasants (1 turn left)", "an agent (1 turn left)"]


@pytest.mark.parametrize("order", [
    {"type": "besiege", "army": "Admiral Polo", "settlement": "Milan"},
    {"type": "march_on", "army": "Admiral Polo", "target_settlement": "Milan"},
    {"type": "merge_armies", "army": "Admiral Polo", "into": "Doge Enrico"},
])
def test_a_fleet_never_reaches_the_games_land_army_calls(lua, order):
    # a weak model's slip; the game's C++ handed an admiral's stack is a crash pcall can't catch
    control(lua)
    lua.execute(FLEET)
    write_orders(lua, TURN - 1, "venice", [order])
    start_turn(lua, "venice")
    r = results(lua)[0]
    assert not r["ok"] and "fleet" in r["reason"] and calls(lua) == []


def test_eop_331_reports_no_treaties(lua):
    milan = next(f for f in report_of(lua).factions if f.id == "milan")
    assert milan.treaties == [] and milan.turns_in_stance is None


def test_damaged_buildings_reported_and_pcall_safe(lua):
    # damaged buildings (hp < 100) listed in report; hp == 100 or missing hp safe
    lua.execute("""
        local s = FAKE.settlements.Venice
        s.buildings = {
            "core_building",
            { name = "small_church", hp = 45 },
            { name = "port", hp = 100 },
        }
        s.buildingsNum = #s.buildings
    """)
    r = report_of(lua)
    v = r.settlements[0]
    assert [(d.name, d.hp) for d in v.damaged_buildings] == [("small_church", 45)]

    # 3.3.1 fallback / broken hp read never breaks the report
    lua.execute("""
        local s = FAKE.settlements.Venice
        s.buildings = { { name = "broken", hp = "invalid" } }
        s.buildingsNum = 1
        s.getBuilding = function()
            return { getName = function() return "broken" end, getType = function() return "broken" end }
        end
    """)
    r2 = report_of(lua)
    assert r2.settlements[0].damaged_buildings == []


def test_repair_order_finds_repair_option_and_queues(lua):
    control(lua)
    lua.execute("""
        local s = FAKE.settlements.Venice
        -- market is normal construction (type 1); small_church is repair (type 2)
        s.constructionOpts = {
            { "market", 1200, 3, 1 },
            { "small_church", 400, 1, 2 },
        }
    """)
    r = report_of(lua)
    # repair option must NOT appear in can_build
    assert [b.building for b in r.settlements[0].can_build] == ["market"]

    # Queue repair order
    write_orders(lua, TURN - 1, "venice", [{"type": "repair", "settlement": "Venice", "building": "small_church"}])
    start_turn(lua, "venice")

    res = results(lua)[0]
    assert res["ok"]
    assert "repair Venice small_church" in calls(lua)


def test_repair_order_refusals(lua):
    def check_refusal(order, setup="", control_line=FULL):
        control(lua, line=control_line)
        lua.execute(f"FAKE.reset(); BRIDGE.setup('{lua.root}'); "
                    "FAKE.settlements.Venice.constructionOpts = { "
                    "{ 'market', 1200, 3, 1 }, { 'small_church', 400, 1, 2 } }; " + setup)
        (turn_dir(lua, TURN - 1, "venice") / "results.json").unlink(missing_ok=True)
        write_orders(lua, TURN - 1, "venice", [order])
        start_turn(lua, "venice")
        return results(lua)[0]

    # 1. Not damaged / no repair option
    res = check_refusal({"type": "repair", "settlement": "Venice", "building": "market"})
    assert not res["ok"] and "not damaged" in res["reason"]

    # 2. No money
    res = check_refusal({"type": "repair", "settlement": "Venice", "building": "small_church"},
                        setup="FAKE.byName.venice.money = 100")
    assert not res["ok"] and "treasury too low" in res["reason"]

    # 3. Queue full (addBuildingToQueue returns false)
    res = check_refusal({"type": "repair", "settlement": "Venice", "building": "small_church"},
                        setup="FAKE.settlements.Venice.constructionOpts = { { 'small_church', 400, 1, 2, false } }")
    assert not res["ok"] and "queue full" in res["reason"]

    # 4. Already in queue
    res = check_refusal({"type": "repair", "settlement": "Venice", "building": "small_church"},
                        setup="FAKE.settlements.Venice.buildingsQueue = { numBuildingsInQueue = 1, "
                              "getBuildingInQueue = function(self, pos) if pos == 1 then return { getQueueBuildingName = function() return 'small_church' end } end end }")
    assert not res["ok"] and "already in Venice's queue" in res["reason"]

    # 5. Settlement not owned
    res = check_refusal({"type": "repair", "settlement": "Milan", "building": "small_church"})
    assert not res["ok"] and "not owned" in res["reason"]

    # 6. Seat lacks build area
    res = check_refusal({"type": "repair", "settlement": "Venice", "building": "small_church"},
                        control_line="control=venice:diplomacy,armies,agents\n")
    assert not res["ok"] and "not yours to command" in res["reason"]
    start_turn(lua, "venice")
    res = results(lua)[0]
    assert not res["ok"] and "not yours to command" in res["reason"]


def test_playtest_funds_below_target_topped_up_and_logged(lua):
    (lua.root / "bridge.txt").write_text("game_id=g1\nfaction=venice\nfaction=milan\nplaytest_funds=venice:50000\n")
    lua.execute("FAKE.byName.venice.money = 3000")
    start_turn(lua, "venice")
    assert lua.eval("FAKE.byName.venice.money") == 50000
    log = (lua.root / "parley_bridge.log").read_text()
    assert "playtest funds: venice topped up 3000 -> 50000" in log


def test_playtest_funds_at_or_above_target_untouched(lua):
    (lua.root / "bridge.txt").write_text("game_id=g1\nfaction=venice\nfaction=milan\nplaytest_funds=venice:50000\n")
    lua.execute("FAKE.byName.venice.money = 50000")
    start_turn(lua, "venice")
    assert lua.eval("FAKE.byName.venice.money") == 50000
    log = (lua.root / "parley_bridge.log").read_text() if (lua.root / "parley_bridge.log").exists() else ""
    assert "playtest funds: venice topped up" not in log

    lua.execute("FAKE.byName.venice.money = 60000")
    start_turn(lua, "venice")
    assert lua.eval("FAKE.byName.venice.money") == 60000
    log = (lua.root / "parley_bridge.log").read_text() if (lua.root / "parley_bridge.log").exists() else ""
    assert "playtest funds: venice topped up" not in log


def test_playtest_funds_off_untouched(lua):
    (lua.root / "bridge.txt").write_text("game_id=g1\nfaction=venice\nfaction=milan\n")
    lua.execute("FAKE.byName.venice.money = 3000")
    start_turn(lua, "venice")
    assert lua.eval("FAKE.byName.venice.money") == 3000
    log = (lua.root / "parley_bridge.log").read_text() if (lua.root / "parley_bridge.log").exists() else ""
    assert "playtest funds" not in log

    (lua.root / "bridge.txt").write_text("game_id=g1\nfaction=venice\nfaction=milan\nplaytest_funds=venice:0\n")
    lua.execute("FAKE.byName.venice.money = 3000")
    start_turn(lua, "venice")
    assert lua.eval("FAKE.byName.venice.money") == 3000
    log = (lua.root / "parley_bridge.log").read_text() if (lua.root / "parley_bridge.log").exists() else ""
    assert "playtest funds" not in log


def test_playtest_funds_failed_logged_when_money_read_only_error(lua):
    (lua.root / "bridge.txt").write_text("game_id=g1\nfaction=venice\nfaction=milan\nplaytest_funds=venice:50000\n")
    lua.execute("""
        local fac = FAKE.byName.venice
        fac.money = nil
        setmetatable(fac, {
            __index = function(t, k) if k == "money" then return 3000 end end,
            __newindex = function(t, k, v)
                if k == "money" then error("money is read-only") end
                rawset(t, k, v)
            end,
        })
    """)
    start_turn(lua, "venice")
    log = (lua.root / "parley_bridge.log").read_text()
    assert "playtest funds: venice top-up failed" in log
    assert "money is read-only" in log


def test_playtest_funds_failed_logged_when_money_read_only_unchanged(lua):
    (lua.root / "bridge.txt").write_text("game_id=g1\nfaction=venice\nfaction=milan\nplaytest_funds=venice:50000\n")
    lua.execute("""
        local fac = FAKE.byName.venice
        fac.money = nil
        setmetatable(fac, {
            __index = function(t, k) if k == "money" then return 3000 end end,
            __newindex = function(t, k, v)
                if k == "money" then return end
                rawset(t, k, v)
            end,
        })
    """)
    start_turn(lua, "venice")
    log = (lua.root / "parley_bridge.log").read_text()
    assert "playtest funds: venice top-up failed (money still 3000)" in log


def test_merge_units_does_not_block_same_turn_merge_armies(lua):
    control(lua)
    lua.execute("""
        local fac = FAKE.byName.venice
        local st = fac.stacks[1]
        st.leader.namedCharacter.fullName = 'Rufus'
        for _, c in ipairs(fac.characters) do
            if c.namedCharacter.fullName == 'Doge Enrico' then
                c.namedCharacter.fullName = 'Rufus'
            end
        end
        local units = {}
        local function unit(kind, n, max, exp)
            local u = { eduEntry = { eduType = kind }, soldierCountStratMap = n,
                        soldierCountStratMapMax = max, exp = exp, armourLVL = 0, weaponLVL = 0 }
            u.kill = function(self)
                for i, x in ipairs(units) do if x == self then table.remove(units, i) end end
            end
            units[#units + 1] = u
        end
        unit('Hobilars', 20, 40, 1)
        unit('Hobilars', 10, 40, 2)
        st.units = units
        st.numOfUnits = #units
        FAKE.units = units
    """)
    write_orders(lua, TURN - 1, "venice", [
        {"type": "merge_units", "army": "Rufus"},
        {"type": "merge_armies", "army": "garrison:Venice", "into": "Rufus"},
    ])
    start_turn(lua, "venice")
    r = results(lua)
    assert r[0]["ok"] is True
    assert r[1]["ok"] is True


def test_walking_garrison_merge_succeeds_with_note_in_prompt(lua):
    control(lua)
    lua.execute("FAKE.byName.venice.stacks[1].leader.xCoord = 130")
    write_orders(lua, TURN - 1, "venice", [
        {"type": "merge_armies", "army": "garrison:Venice", "into": "Doge Enrico"}
    ])
    start_turn(lua, "venice")
    r = results(lua)[0]
    assert r["ok"] is True
    assert r["reason"] == ""
    assert "marches out of Venice under a captain" in r["note"] and "Venice is left without a garrison" in r["note"]
    end_turn(lua, "venice")
    report = StateReport.model_validate_json((turn_dir(lua, TURN, "venice") / "state.json").read_text())
    assert report.last_results[0].ok is True
    assert "Venice is left without a garrison" in report.last_results[0].note
    prompt = build_prompt(report, persona="You are Doge Enrico.")
    assert "Venice is left without a garrison" in prompt


def test_march_on_stationary_army_lists_moves_not_made(lua):
    lua.execute("""
        local fac = FAKE.byName.venice
        fac.stacks[1].leader.namedCharacter.fullName = 'Rufus'
        fac.stacks[1].leader.xCoord, fac.stacks[1].leader.yCoord = 105, 156
        fac.stacks[1].leader.movePoints = 72.0
        for _, c in ipairs(fac.characters) do
            if c.namedCharacter.fullName == 'Doge Enrico' then
                c.namedCharacter.fullName = 'Rufus'
                c.xCoord, c.yCoord = 105, 156
                c.movePoints = 72.0
            end
        end
        FAKE.settlements['Nottingham'] = {
            name = 'Nottingham', localizedName = 'Nottingham',
            xCoord = 107, yCoord = 155, regionID = 1,
            ownerFaction = fac, army = nil, populationSize = 1000,
        }
    """)
    write_orders(lua, TURN - 1, "venice", [
        {"type": "march_on", "army": "Rufus", "target_settlement": "Nottingham"}
    ])
    start_turn(lua, "venice")
    assert results(lua)[0]["ok"] is True
    end_turn(lua, "venice")
    # live: at the turn's end a move just ordered hasn't landed yet, so it isn't judged there
    report = StateReport.model_validate_json((turn_dir(lua, TURN, "venice") / "state.json").read_text())
    assert report.moves_not_made == []

    # the next turn starts with Rufus where he was: that turn's report says so
    turn_dir(lua, TURN + 1, "venice").mkdir(parents=True, exist_ok=True)
    write_orders(lua, TURN, "venice", [
        {"type": "march_on", "army": "Rufus", "target_settlement": "Nottingham"}
    ])
    lua.execute(f"FAKE.campaign.turnNumber = {TURN + 1}")
    start_turn(lua, "venice")
    end_turn(lua, "venice")
    report = StateReport.model_validate_json((turn_dir(lua, TURN + 1, "venice") / "state.json").read_text())
    assert len(report.moves_not_made) == 1
    m = report.moves_not_made[0]
    assert m.id == "Rufus" and m.from_x == 105 and m.from_y == 156 and m.target == "Nottingham"
    prompt = build_prompt(report, persona="You are Rufus.")
    assert "Rufus's march to Nottingham did not happen: still at (105,156)." in prompt

    # this time he marches: the turn after, nothing is listed
    lua.execute("""
        local fac = FAKE.byName.venice
        fac.stacks[1].leader.xCoord, fac.stacks[1].leader.yCoord = 107, 155
        for _, c in ipairs(fac.characters) do
            if c.namedCharacter.fullName == 'Rufus' then
                c.xCoord, c.yCoord = 107, 155
            end
        end
    """)
    turn_dir(lua, TURN + 2, "venice").mkdir(parents=True, exist_ok=True)
    lua.execute(f"FAKE.campaign.turnNumber = {TURN + 2}")
    start_turn(lua, "venice")
    end_turn(lua, "venice")
    report2 = StateReport.model_validate_json((turn_dir(lua, TURN + 2, "venice") / "state.json").read_text())
    assert report2.moves_not_made == []
    prompt2 = build_prompt(report2, persona="You are Rufus.")
    assert "did not happen" not in prompt2


def test_move_to_the_tile_it_stands_on_is_never_reported(lua):
    # live: merge_armies moved a garrison to its own tile; the next report said it didn't happen
    lua.execute("""
        local fac = FAKE.byName.venice
        fac.stacks[1].leader.namedCharacter.fullName = 'Rufus'
        fac.stacks[1].leader.xCoord, fac.stacks[1].leader.yCoord = 105, 156
    """)
    write_orders(lua, TURN - 1, "venice", [{"type": "move_army", "army": "Rufus", "x": 105, "y": 156}])
    start_turn(lua, "venice")
    end_turn(lua, "venice")
    turn_dir(lua, TURN + 1, "venice").mkdir(parents=True, exist_ok=True)
    lua.execute(f"FAKE.campaign.turnNumber = {TURN + 1}")
    start_turn(lua, "venice")
    end_turn(lua, "venice")
    report = StateReport.model_validate_json((turn_dir(lua, TURN + 1, "venice") / "state.json").read_text())
    assert report.moves_not_made == []


SIEGE_BY_DOGE = """
    local st = FAKE.byName.venice.stacks[1]
    local town = { name = 'Milan', siegeHoldoutTurns = 5 }
    st.siege = { besiegedSettlement = town, siegeTurns = 2, equipmentQueueCount = 1 }
"""


def test_besieging_army_left_alone_gets_its_siege_equipment_queued(lua):
    lua.execute(SIEGE_BY_DOGE)
    write_orders(lua, TURN - 1, "venice", [])
    start_turn(lua, "venice")
    assert calls(lua) == ["siege Doge Enrico Milan false"]
    assert "Doge Enrico keeps the siege of Milan; siege equipment queued" in (
        lua.root / "parley_bridge.log").read_text()


def test_besieger_ordered_to_withdraw_is_not_given_the_maintain_call(lua):
    lua.execute(SIEGE_BY_DOGE)
    write_orders(lua, TURN - 1, "venice", [
        {"type": "withdraw", "army": "Doge Enrico", "to_settlement": "Ragusa"}])
    start_turn(lua, "venice")
    assert not any(c.startswith("siege ") for c in calls(lua))


def test_besieger_ordered_to_move_is_not_given_the_maintain_call(lua):
    lua.execute(SIEGE_BY_DOGE)
    write_orders(lua, TURN - 1, "venice", [
        {"type": "move_army", "army": "Doge Enrico", "x": 90, "y": 90}])
    start_turn(lua, "venice")
    assert not any(c.startswith("siege ") for c in calls(lua))


def test_army_not_besieging_gets_no_siege_call(lua):
    write_orders(lua, TURN - 1, "venice", [])
    start_turn(lua, "venice")
    assert not any(c.startswith("siege ") for c in calls(lua))


def test_besieging_army_reports_town_equipment_and_holdout(lua):
    from parley.prompt import _army
    lua.execute(SIEGE_BY_DOGE)
    a = report_of(lua).armies[0]
    assert (a.besieging, a.siege_turns, a.siege_queue, a.holdout_turns) == ("Milan", 2, 1, 5)
    line = _army(a)
    assert "besieging Milan" in line and "1 pieces of siege equipment being built" in line
    assert "Milan holds out 5 more turns" in line


def test_settlement_report_carries_revolt_plague_and_income(lua):
    lua.execute("""
        local s = FAKE.byName.venice.settlements[1]
        s.isProvokedRebellion = 1; s.plagued = true; s.turmoil = 2; s.rebelFactionChance = 35
        s.settlementStats.TotalIncomeWithoutAdmin = -120.5; s.settlementStats.TaxesIncome = 800
    """)
    s = report_of(lua).settlements[0]
    assert (s.rebelling, s.plagued, s.turmoil, s.rebel_chance, s.income, s.taxes_income) == (
        True, True, 2, 35, -121, 800)


def test_settlement_report_without_unrest_fields_is_calm(lua):
    s = report_of(lua).settlements[0]
    assert (s.rebelling, s.plagued, s.turmoil, s.rebel_chance, s.income) == (False, False, None, None, None)


def test_assault_the_game_says_no_still_goes_out_with_a_note(lua):
    lua.execute(DOGE_BY_MILAN)
    lua.execute("FAKE.byName.venice.stacks[1].canStartAssault = function() return false end")
    write_orders(lua, TURN - 1, "venice", [
        {"type": "besiege", "army": "Doge Enrico", "settlement": "Milan", "assault": True}])
    start_turn(lua, "venice")
    assert "siege Doge Enrico Milan true" in calls(lua)  # never blocked
    r = results(lua)[0]
    assert r["ok"] and "the game says this army can't assault yet" in r["note"]


def test_assault_the_game_allows_has_no_note(lua):
    lua.execute(DOGE_BY_MILAN)
    lua.execute("FAKE.byName.venice.stacks[1].canStartAssault = function() return true end")
    write_orders(lua, TURN - 1, "venice", [
        {"type": "besiege", "army": "Doge Enrico", "settlement": "Milan", "assault": True}])
    start_turn(lua, "venice")
    assert "siege Doge Enrico Milan true" in calls(lua)
    assert "note" not in results(lua)[0]


def test_besieging_army_reports_can_assault_now(lua):
    from parley.prompt import _army
    lua.execute(SIEGE_BY_DOGE)
    lua.execute("FAKE.byName.venice.stacks[1].canStartAssault = function() return false end")
    a = report_of(lua).armies[0]
    assert a.can_assault is False
    assert "can assault now: no" in _army(a)
    lua.execute("FAKE.byName.venice.stacks[1].canStartAssault = function() return true end")
    assert "can assault now: yes" in _army(report_of(lua).armies[0])


# --- QA bench setup helpers (M.qa) --------------------------------------------------------

def test_qa_spawn_agent_logs_and_returns_name(lua):
    name = lua.eval("BRIDGE.qa.spawn_agent('venice', 'spy', 115, 81, 'QA Spy')")
    assert name == "QA Spy"
    assert "createCharacter venice spy QA Spy 115 81" in calls(lua)
    assert "qa: spawn_agent ok: QA Spy" in bridge_log(lua)
    assert lua.eval("BRIDGE.qa.skill('QA Spy', 'GoodSpy', 5)") == "QA Spy GoodSpy=5"
    assert "addTrait QA Spy GoodSpy 5" in calls(lua)
    assert "qa: skill ok: QA Spy GoodSpy=5" in bridge_log(lua)
    assert [(a.id, a.kind, a.x, a.y) for a in report_of(lua).agents if a.id == "QA Spy"] == [
        ("QA Spy", "spy", 115, 81)]


def test_qa_spawn_agent_names_a_nameless_spawn_and_returns_its_report_id(lua):
    # live 10-30 smoke run: createCharacter ignored "QA Spy" (not in England's name list); the
    # spy stood at the tile with id '' and no order could reach it
    lua.execute("FAKE.spawn_ignores_names = true")
    name = lua.eval("BRIDGE.qa.spawn_agent('venice', 'spy', 115, 81, 'QA Spy')")
    assert name == "Edwin"
    assert "giveRandomName 4" in calls(lua)  # venice's factionID
    assert "qa: spawn_agent ok: Edwin" in bridge_log(lua)
    assert [(a.id, a.kind, a.x, a.y) for a in report_of(lua).agents if a.x == 115 and a.y == 81] == [
        ("Edwin", "spy", 115, 81)]
    assert lua.eval("BRIDGE.qa.skill('Edwin', 'GoodSpy', 5)") == "Edwin GoodSpy=5"


def test_qa_spawn_agent_returns_the_numbered_id_when_the_name_is_taken(lua):
    lua.execute("FAKE.spawn_ignores_names = true; FAKE.random_name = 'Marco'")
    name = lua.eval("BRIDGE.qa.spawn_agent('venice', 'spy', 115, 81, 'QA Spy')")
    assert name == "Marco#2"
    assert "qa: spawn_agent ok: Marco#2" in bridge_log(lua)
    assert [(a.id, a.x, a.y) for a in report_of(lua).agents if a.id.startswith("Marco")] == [
        ("Marco", 120, 87), ("Marco#2", 115, 81)]
    assert lua.eval("BRIDGE.qa.where('Marco#2')") == "115,81"


def test_qa_spawn_agent_fails_when_the_agent_stays_nameless(lua):
    lua.execute("FAKE.spawn_ignores_names = true; FAKE.random_name = ''")
    assert lua.eval("BRIDGE.qa.spawn_agent('venice', 'spy', 115, 81, 'QA Spy')") is None
    assert "qa: spawn_agent failed:" in bridge_log(lua)
    assert "no name" in bridge_log(lua)


def test_qa_teleport_reports_reached_tile(lua):
    assert lua.eval("BRIDGE.qa.teleport('Marco', 115, 81)") == "115,81"
    assert "teleport Marco 115 81" in calls(lua)
    assert "qa: teleport ok: 115,81" in bridge_log(lua)
    assert lua.eval("BRIDGE.qa.where('Marco')") == "115,81"
    lua.execute("for _, c in ipairs(FAKE.byName.venice.characters) do "
                "if c.namedCharacter.fullName == 'Marco' then "
                "c.teleport = function(self, tx, ty) self.xCoord, self.yCoord = tx - 1, ty return true end end end")
    assert lua.eval("BRIDGE.qa.teleport('Marco', 115, 81)") == "114,81"
    assert lua.eval("BRIDGE.qa.where('Marco')") == "114,81"


def test_qa_teleport_refuses_a_taken_tile_instead_of_crashing(lua):
    # 11-04 10:12: a teleport onto a fixed tile crashed the game after a played turn
    tx, ty = lua.eval("BRIDGE.qa.where('Doge Enrico')").split(",")
    before = len(calls(lua))
    assert lua.eval(f"BRIDGE.qa.teleport('Marco', {tx}, {ty})") is None
    assert not any(c.startswith("teleport Marco") for c in calls(lua)[before:])
    assert f"tile {tx},{ty} is taken" in bridge_log(lua)


def test_qa_helper_failure_is_logged_not_raised(lua):
    lua.execute("FAKE.byName.venice.createCharacter = function() error('boom') end")
    res = lua.eval("BRIDGE.qa.spawn_agent('venice', 'spy', 115, 81, 'QA Spy')")
    assert res is None
    assert "qa: spawn_agent failed:" in bridge_log(lua)
    assert "boom" in bridge_log(lua)


def _game_dir_with_save(tmp_path, monkeypatch, rel):
    """The game's working directory (the game folder) with a save at `rel`, as the game sees it."""
    game = tmp_path / "game"
    (game / rel).parent.mkdir(parents=True)
    (game / rel).write_bytes(b"save")
    monkeypatch.chdir(game)


def test_qa_load_calls_eop_loadgame_with_path(lua, tmp_path, monkeypatch):
    _game_dir_with_save(tmp_path, monkeypatch, "mods/parley/saves/parley_keep_g1.sav")
    res = lua.eval("BRIDGE.qa.load('mods/parley/saves/parley_keep_g1.sav')")
    assert res == "mods/parley/saves/parley_keep_g1.sav"
    assert "loadGame mods/parley/saves/parley_keep_g1.sav" in calls(lua)
    assert "qa: load ok: mods/parley/saves/parley_keep_g1.sav" in bridge_log(lua)


def test_qa_load_refuses_a_missing_save_and_never_calls_eop(lua, tmp_path, monkeypatch):
    # live 10-31: EOP's loadGame on a missing save froze the game behind a modal ERROR box
    _game_dir_with_save(tmp_path, monkeypatch, "mods/parley/saves/parley_keep_scratch.restored-1.sav")
    res = lua.eval("BRIDGE.qa.load('mods/parley/saves/parley_keep_scratch.sav')")
    assert res == "qa: load refused: no save at mods/parley/saves/parley_keep_scratch.sav"
    assert not any(c.startswith("loadGame") for c in calls(lua))
    log = bridge_log(lua)
    assert "qa: load refused: no save at mods/parley/saves/parley_keep_scratch.sav" in log
    # not a load that went out, nor a helper failure the bench's act step would fail on
    assert "qa: load ok" not in log and "qa: load failed" not in log
    # the bridge still answers afterwards
    assert lua.eval("BRIDGE.qa.load('mods/parley/saves/parley_keep_scratch.restored-1.sav')") \
        == "mods/parley/saves/parley_keep_scratch.restored-1.sav"


def test_every_campaign_load_is_logged_for_the_qa_restore(lua):
    # M2TWEOP.loadGame writes no reload marker; the QA restore waits for this line instead
    lua.execute(f"BRIDGE.setup('{lua.root}')")
    assert f"bridge loaded campaign at turn {TURN}" in bridge_log(lua)


# --- QA field suite helpers: spawn_army, leader, free_tile, sea_town, town, tire ------------

def test_qa_spawn_army_returns_the_armys_report_id(lua):
    # EOP factionStruct:spawnArmy (LuaDocs.lua:9437-9453): type 7 is characterType.named_character
    # (:1042), the unit's index from M2TWEOPDU.getEduIndexByType (:7747)
    army = lua.eval("BRIDGE.qa.spawn_army('venice', 110, 70)")
    assert army == "Edwin"
    assert "spawnArmy venice random_name 7 110 70 20" in calls(lua)
    assert "qa: spawn_army ok: Edwin" in bridge_log(lua)
    assert [(a.id, a.x, a.y, a.units) for a in report_of(lua).armies if a.id == "Edwin"] == [("Edwin", 110, 70, 1)]


def test_qa_spawn_army_returns_the_numbered_id_when_the_name_is_taken(lua):
    lua.execute("FAKE.random_name = 'Doge Enrico'")
    assert lua.eval("BRIDGE.qa.spawn_army('venice', 110, 70)") == "Doge Enrico#2"
    assert [(a.id, a.x) for a in report_of(lua).armies if a.id.startswith("Doge")] == [
        ("Doge Enrico", 121), ("Doge Enrico#2", 110)]


def test_qa_garrison_in_an_unled_town_is_its_garrison_and_leader_names_the_general(lua):
    # Ragusa (140,80) has no stack: the spawned general's is its garrison, which the report ids by town
    assert lua.eval("BRIDGE.qa.garrison('venice', 'Ragusa')") == "garrison:Ragusa"
    assert lua.eval("BRIDGE.qa.leader('venice', 'garrison:Ragusa')") == "Edwin"
    assert "qa: leader ok: Edwin" in bridge_log(lua)
    assert lua.eval("BRIDGE.qa.leader('venice', 'Doge Enrico')") == "Doge Enrico"


def test_qa_spawn_army_refuses_sea_and_unknown_units(lua):
    assert lua.eval("BRIDGE.qa.spawn_army('venice', 116, 91)") is None
    assert "qa: spawn_army failed:" in bridge_log(lua) and "(116,91) is sea" in bridge_log(lua)
    assert lua.eval("BRIDGE.qa.spawn_army('venice', 110, 70, 'random_name', 'Nonesuch')") is None
    assert "unknown unit type 'Nonesuch'" in bridge_log(lua)
    assert not any(c.startswith("spawnArmy") for c in calls(lua))
    assert lua.eval("BRIDGE.qa.leader('venice', 'Nobody')") is None
    assert "qa: leader failed:" in bridge_log(lua)


def test_qa_free_tile_skips_people_towns_and_sea(lua):
    # around the Doge (121,88): Marco stands on (120,87), Venice is (120,88)
    assert lua.eval("BRIDGE.qa.free_tile(121, 88, 1, 1)") == "120,89"
    assert "qa: free_tile ok: 120,89" in bridge_log(lua)
    # (118,92) is sea (x >= 115, y >= 90), and so are the first rings round it
    assert lua.eval("BRIDGE.qa.free_tile(118, 92, 1, 3)") == "115,89"


def test_qa_free_tile_stays_on_the_anchors_landmass(lua):
    lua.execute(ISLAND)
    # six tiles west of the island's edge is the mainland: land, but not walkable from (135,80)
    assert lua.eval("BRIDGE.qa.free_tile(135, 80, 6, 6)") == "141,75"
    assert lua.eval("BRIDGE.qa.free_tile(140, 80, 7, 7)") is None
    assert "qa: free_tile failed:" in bridge_log(lua)
    assert "no free land tile 7-7 tiles from (140,80)" in bridge_log(lua)


# live 10-30 22:03: the covert victim Esau stood beside the assassin, out of England's sight lists,
# so the assassinate order went to the next nearest character, across the sea

def test_qa_seen_tile_is_a_free_tile_the_faction_sees(lua):
    lua.execute("""
        tileVisibility = { notVisible = 1, wasVisible = 2, visible = 3 }
        FAKE.byName.venice.getTileVisibility = function(self, x, y)
            return (x == 113 and y == 81) and 3 or 2
        end
    """)
    assert lua.eval("BRIDGE.qa.free_tile(112, 80, 1, 1)") == "111,79"
    assert lua.eval("BRIDGE.qa.seen_tile('venice', 112, 80, 1, 1)") == "113,81"
    assert "qa: seen_tile ok: 113,81" in bridge_log(lua)


def test_qa_free_tile_skips_tiles_no_army_can_stand_on(lua):
    # live 10-31 (bench save): (108,146) by London has a river: William's split out never moved and
    # withdraw's spawn there landed on (107,146); the readiness canary spawned on impassable
    # (104,162) landed on (103,161) and could never reach its impassable target (103,162)
    lua.execute("""
        local base = FAKE.stratMap.getTile
        FAKE.stratMap.getTile = function(x, y)
            local t = base(x, y)
            if x == 111 and y == 79 then t.isImpassible = true end
            if x == 111 and y == 80 then t.hasRiver = true end
            if x == 111 and y == 81 then t.hasRiver, t.hasCrossing = true, true end
            return t
        end
    """)
    assert lua.eval("BRIDGE.qa.free_tile(112, 80, 1, 1)") == "111,81"


def test_qa_seen_tile_fails_loudly_when_the_faction_sees_no_free_tile(lua):
    lua.execute("FAKE.byName.venice.getTileVisibility = function() return 2 end")
    assert lua.eval("BRIDGE.qa.seen_tile('venice', 112, 80, 1, 1)") is None
    assert "qa: seen_tile failed:" in bridge_log(lua)
    assert "no free land tile venice sees 1-1 tiles from (112,80)" in bridge_log(lua)
    assert lua.eval("BRIDGE.qa.seen_tile('nowhere', 112, 80, 1, 1)") is None
    assert "unknown faction 'nowhere'" in bridge_log(lua)


def test_qa_seen_tile_uses_the_sight_radius_and_stays_on_the_anchors_landmass(lua):
    # no visibility call: within the sight radius of the Doge (121,88)
    assert lua.eval("BRIDGE.qa.seen_tile('venice', 112, 80, 1, 1)") == "111,79"
    lua.execute(ISLAND)
    # Pietro (140,80) sees the mainland six tiles west of (135,80) too, but it can't be walked to
    assert lua.eval("BRIDGE.qa.seen_tile('venice', 135, 80, 6, 6)") == "141,75"
    assert lua.eval("BRIDGE.qa.seen_tile('venice', 140, 80, 7, 7)") is None


def test_qa_sees_gives_the_sight_id_of_who_stands_on_a_tile(lua):
    assert lua.eval("BRIDGE.qa.sees('venice', 112, 80)") == "Heinrich"
    assert "qa: sees ok: Heinrich" in bridge_log(lua)
    assert lua.eval("BRIDGE.qa.sees('venice', 119, 86)") == "Ulrich"
    # the far HRE assassin stands out of sight; nobody at all on an empty tile
    assert lua.eval("BRIDGE.qa.sees('venice', 60, 40)") is None
    assert "venice sees nobody at (60,40)" in bridge_log(lua)
    assert lua.eval("BRIDGE.qa.sees('venice', 111, 79)") is None
    # a rebel army spawned in sight is seen by its sight id
    army = lua.eval("BRIDGE.qa.spawn_army('slave', 111, 79)")
    assert army and lua.eval("BRIDGE.qa.sees('venice', 111, 79)") == army


def test_qa_sea_town_is_the_nearest_foreign_town_across_the_sea(lua):
    assert lua.eval("BRIDGE.qa.sea_town('venice', 121, 88)") is None  # one landmass: none
    assert "qa: sea_town failed:" in bridge_log(lua)
    assert "no foreign settlement across the sea from (121,88)" in bridge_log(lua)
    lua.execute(ISLAND)
    lua.execute(ISLAND_MILAN)
    # Innsbruck (8 tiles) is walkable; Ragusa is on the island but Venice's own
    assert lua.eval("BRIDGE.qa.sea_town('venice', 121, 88)") == "Milan"
    assert "qa: sea_town ok: Milan" in bridge_log(lua)


def test_qa_town_gives_a_settlements_tile(lua):
    assert lua.eval("BRIDGE.qa.town('Milan')") == "100,90"
    assert lua.eval("BRIDGE.qa.town('Atlantis')") is None
    assert "qa: town failed:" in bridge_log(lua) and "unknown settlement 'Atlantis'" in bridge_log(lua)


def test_qa_tire_empties_moves_now_and_again_at_turn_start(lua):
    # EOP character.movePoints "sets both army and character move points" (LuaDocs.lua:6496); the
    # game refills them at turn start, before orders apply, so the bench empties them again there
    army = lua.eval("BRIDGE.qa.spawn_army('venice', 110, 70)")
    assert lua.eval(f"BRIDGE.qa.tire('venice', '{army}')") == "Edwin moves=0"
    assert "qa: tire ok: Edwin moves=0" in bridge_log(lua)
    lua.execute("FAKE.byName.venice.stacks[3].leader.movePoints = 20")  # the game's refill
    write_orders(lua, TURN - 1, "venice", [{"type": "move_army", "army": "Edwin", "x": 111, "y": 70}])
    start_turn(lua, "venice")
    assert "qa: tired Edwin at turn start: moves=0" in bridge_log(lua)
    assert "no moves left" in results(lua)[0]["reason"]
    assert not any(c.startswith("moveToTile Edwin") for c in calls(lua))


def test_qa_spawn_army_refuses_a_towns_tile(lua):
    # QA field 10-30 23:49-00:03: field armies that ended up inside Nottingham's garrison were lost to
    # their cases ("armies[id=Simon Townsend] not found"); a field spawn goes beside a town, never on it
    assert lua.eval("BRIDGE.qa.spawn_army('venice', 140, 80)") is None
    assert "(140,80) is Ragusa's tile: spawn beside it (free_tile)" in bridge_log(lua)
    assert not any(c.startswith("spawnArmy") for c in calls(lua))


def test_qa_tire_finds_a_general_who_went_into_a_town(lua):
    # live 10-30 23:58:45: Howard Stafford was inside Nottingham by the next turn start, "unknown
    # army 'Howard Stafford'", his moves full, and the no_moves_left case's move went ahead. The town's
    # garrison has its own general (Godwine there, Captain Robin here), so no army is Edwin's any more
    lua.execute(ROBIN_IN_VENICE)
    army = lua.eval("BRIDGE.qa.spawn_army('venice', 110, 70)")
    assert lua.eval(f"BRIDGE.qa.tire('venice', '{army}')") == "Edwin moves=0"
    lua.execute("""
        local fac = FAKE.byName.venice
        local st = fac.stacks[3]
        table.remove(fac.stacks, 3); fac.stacksNum = #fac.stacks   -- his army is gone into the town
        for _, c in ipairs(fac.characters) do
            if c.namedCharacter.fullName == 'Edwin' then
                c.xCoord, c.yCoord, c.armyLeaded = 120, 88, nil
                c.movePoints = 20                                   -- the game's refill
            end
        end""")
    write_orders(lua, TURN - 1, "venice", [{"type": "move_army", "army": "Edwin", "x": 111, "y": 88}])
    start_turn(lua, "venice")
    assert "qa: tired Edwin at turn start: moves=0" in bridge_log(lua)
    assert "no moves left" in results(lua)[0]["reason"]
    assert not any(c.startswith(("splitArmy", "moveToTile Edwin")) for c in calls(lua))


def test_qa_tire_keeps_a_rebel_army_put_at_its_own_turn_start(lua):
    # the covert assassinate case's victim (live 10-30 21:38: the rebel army it was spawned beside,
    # Captain Lopo, was out of sight a turn later): the rebels have no seat, so their turn start
    # must still tire it
    army = lua.eval("BRIDGE.qa.spawn_army('slave', 110, 70)")
    assert army
    assert lua.eval(f"BRIDGE.qa.tire('slave', '{army}')") == f"{army} moves=0"
    start_turn(lua, "slave")
    assert f"qa: tired {army} at turn start: moves=0" in bridge_log(lua)


def test_qa_tire_stops_after_its_turns_and_on_a_campaign_load(lua):
    lua.eval("BRIDGE.qa.spawn_army('venice', 110, 70)")
    lua.eval("BRIDGE.qa.tire('venice', 'Edwin', 1)")
    start_turn(lua, "venice")
    lua.execute("FAKE.campaign.turnNumber = 4")
    start_turn(lua, "venice")
    assert bridge_log(lua).count("qa: tired Edwin at turn start") == 1
    lua.eval("BRIDGE.qa.tire('venice', 'Edwin')")
    lua.execute(f"BRIDGE.setup('{lua.root}')")  # a load (the QA restore's loadGame) forgets them
    lua.execute("FAKE.campaign.turnNumber = 5")
    start_turn(lua, "venice")
    assert bridge_log(lua).count("qa: tired Edwin at turn start") == 1


def test_qa_spawn_army_gives_the_general_the_games_starting_loyalty(lua):
    # live 10-30 19:47-19:49: two spawned generals (Edmund Awood, Walter Baker) left England for
    # the rebels a turn after spawning ("slave: Walter Baker was struck by a disaster"). The game
    # gives every general LoyaltyStarter (Loyalty 5) on coming of age, adoption or marriage
    # (export_descr_character_traits.txt); a spawned one never gets it and stands at loyalty 0
    assert lua.eval("BRIDGE.qa.spawn_army('venice', 110, 70)") == "Edwin"
    assert "addTrait Edwin LoyaltyStarter 1" in calls(lua)
    lua.execute("FAKE.random_name = 'Bruno'")
    assert lua.eval("BRIDGE.qa.garrison('venice', 'Ragusa')") == "garrison:Ragusa"
    assert "addTrait Bruno LoyaltyStarter 1" in calls(lua)


def test_qa_garrison_keeps_the_general_inside_or_spawns_one(lua):
    # live 10-30 19:51: every English town had a general, so the garrison case found no town to
    # spawn one into. A town already led is the live case itself (Robert in Paris): use him
    assert lua.eval("BRIDGE.qa.garrison('venice', 'Ragusa')") == "garrison:Ragusa"
    spawns = sum(c.startswith("spawnArmy") for c in calls(lua))
    assert lua.eval("BRIDGE.qa.garrison('venice', 'Ragusa')") == "garrison:Ragusa"
    assert sum(c.startswith("spawnArmy") for c in calls(lua)) == spawns  # led already: no second general
    assert "qa: garrison ok: garrison:Ragusa" in bridge_log(lua)
    # Venice's garrison has nobody leading it: a general is spawned into it
    lua.execute("FAKE.random_name = 'Bruno'")
    assert lua.eval("BRIDGE.qa.garrison('venice', 'Venice')") == "garrison:Venice"
    assert "spawnArmy venice random_name 7 120 88 20" in calls(lua)
    assert lua.eval("BRIDGE.qa.leader('venice', 'garrison:Venice')") == "Bruno"
    # not one of the faction's towns
    assert lua.eval("BRIDGE.qa.garrison('venice', 'Milan')") is None
    assert "qa: garrison failed:" in bridge_log(lua) and "Milan is not venice's" in bridge_log(lua)


def test_qa_hostile_town_is_the_nearest_rebel_or_enemy_town_on_the_map(lua):
    # live 10-30 19:51: no rebel or at-war town was in England's sight, so march_on_besieges had
    # no target; the case spawns its army beside a town picked from the whole map instead
    assert lua.eval("BRIDGE.qa.hostile_town('venice', 121, 88)") == "Innsbruck"  # hre: at war
    assert "qa: hostile_town ok: Innsbruck" in bridge_log(lua)
    lua.execute("FAKE.stances['venice|hre'] = dipRelType.peace")
    assert lua.eval("BRIDGE.qa.hostile_town('venice', 121, 88)") is None  # Milan: at peace
    assert "no rebel or enemy settlement" in bridge_log(lua)
    lua.execute("FAKE.settlements.Milan.ownerFaction = FAKE.byName.slave")
    assert lua.eval("BRIDGE.qa.hostile_town('venice', 121, 88)") == "Milan"


def test_qa_tire_fails_when_the_moves_dont_empty(lua):
    # the Doge's moves can't be written in the fake (no movePoints setter): a tire that doesn't
    # take must fail the setup, never pass as a mover with no moves
    assert lua.eval("BRIDGE.qa.tire('venice', 'Doge Enrico')") is None
    assert "qa: tire failed:" in bridge_log(lua) and "moves still" in bridge_log(lua)



# --- papal hands-off experiment (bridge.txt papal_hands_off=1) --------------------------
# The game dies ~5 s after a papal results scroll opens right after a click (20:48, 22:29,
# 22:43). With the switch on, luaPluginScript's onScrollOpened returns before any work for a
# papal_* scroll: if the game still dies, the crash is game-side, not our handler.

def _entry_script(tmp_path, monkeypatch, extra=""):
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "parley_turns"
    (root / "g1" / f"turn-{TURN:04d}" / "venice").mkdir(parents=True)
    (root / "bridge.txt").write_text(f"game_id=g1\nfaction=venice\nautoplay=1\n{extra}")
    rt = LuaRuntime(unpack_returned_tuples=True)
    rt.execute(f"package.path = '{ROOT}/tests/lua/?.lua;{ROOT}/lua/vendor/?.lua;' .. package.path")
    rt.execute("FAKE = require('fake_game'); FAKE.reset(); "
               "M2TWEOP = { unlockGameConsoleCommands = function() end }")
    rt.execute(f"dofile('{ROOT}/lua/luaPluginScript.lua')")
    rt.execute("onCampaignMapLoaded()")
    # the bridge as the entry script holds it: count what reaches it
    rt.execute("BRIDGE_CALLS = {}; local b = package.loaded.parley_bridge; "
               "local real = b.on_scroll_opened; "
               "b.on_scroll_opened = function(e) BRIDGE_CALLS[#BRIDGE_CALLS + 1] = e; return real(e) end; "
               "READS = {}; function event(name) return setmetatable({}, { __index = function(_, k) "
               "READS[#READS + 1] = k; if k == 'resourceDescription' then return name end end }) end")
    return rt, root


def _log_size(root):
    log = root / "parley_bridge.log"
    return log.stat().st_size if log.exists() else 0


@pytest.mark.parametrize("scroll", ["papal_election_results_scroll", "papal_election_scroll"])
def test_papal_hands_off_entry_script_returns_before_the_bridge(tmp_path, monkeypatch, scroll):
    rt, root = _entry_script(tmp_path, monkeypatch, "papal_hands_off=1\n")
    before = _log_size(root)
    rt.execute(f"onScrollOpened(event('{scroll}'))")
    rt.execute(f"onScrollOpened('{scroll}')")  # eventData may be the bare name
    assert rt.eval("#BRIDGE_CALLS") == 0
    assert list(rt.eval("READS").values()) == ["resourceDescription"]  # nothing else read
    assert _log_size(root) == before  # no log line
    assert not (root / "papal_window.txt").exists()
    trace = root / "papal_trace.txt"
    assert not trace.exists() or "papal_election" not in trace.read_text()
    # nothing queued for the turn loop either, later frames included
    rt.execute("draw(nil)")
    assert not list(root.glob("popup-*.req"))


def test_papal_hands_off_leaves_other_scrolls_to_the_bridge(tmp_path, monkeypatch):
    rt, _ = _entry_script(tmp_path, monkeypatch, "papal_hands_off=1\n")
    rt.execute("onScrollOpened(event('battle_results_scroll'))")
    assert rt.eval("#BRIDGE_CALLS") == 1


def test_papal_scrolls_reach_the_bridge_without_the_switch(tmp_path, monkeypatch):
    rt, root = _entry_script(tmp_path, monkeypatch)
    rt.execute("onScrollOpened(event('papal_election_results_scroll'))")
    assert rt.eval("#BRIDGE_CALLS") == 1
    assert (root / "papal_window.txt").exists()


def test_papal_hands_off_off_by_default_and_follows_bridge_txt(lua):
    autoplay(lua)
    tick(lua)
    assert not lua.eval("BRIDGE.papal_hands_off")
    autoplay(lua, "papal_hands_off=1\n")
    tick(lua)
    assert lua.eval("BRIDGE.papal_hands_off") is True
    autoplay(lua)  # switched off again: the next config read sees it
    tick(lua)
    assert not lua.eval("BRIDGE.papal_hands_off")


# --- hands-off, the vote: found from the per-frame tick, never from inside the scroll's event --
# With papal_hands_off on the bridge never hears of a papal scroll, so the vote scroll (opened
# 3-6 s after the Pope's death notice, message 202) is looked for from the tick: one guarded
# getUiElement("papal_election_scroll") every 2 s, from 3 s after the notice for up to 60 s.
# The results scroll is never looked up (it closes by itself).

HANDS_OFF = "papal_hands_off=1\n"


def test_hands_off_finds_the_vote_scroll_from_the_tick_after_the_notice(lua):
    autoplay(lua, HANDS_OFF)
    lua.execute("BRIDGE.on_message({ eventID = 202 })")
    tick(lua, 1)
    assert papal_lookups(lua) == []  # not before the game has had time to open it
    lua.execute("FAKE.open_scroll('papal_election_scroll', {'vote_button'})")  # no event reaches us
    tick(lua, 3)
    assert papal_lookups(lua) == ["papal_election_scroll"]
    assert "phase=vote" in papal_window(lua)
    tick(lua, 3)  # (K.POPUP_DELAY)
    assert [r["kind"] for r in reqs_of(lua)] == ["vote"]  # the ruler is asked for the vote
    for _ in range(5):
        tick(lua, 2)
    assert papal_lookups(lua) == ["papal_election_scroll"]  # found once: no more looks
    assert "press vote_button" not in presses(lua)  # the turn loop clicks the vote, not Lua
    log = (lua.root / "parley_bridge.log").read_text()
    assert "papal vote: the vote scroll is up (seen from the tick)" in log
    assert "papal notice: the election opened" in log


def test_hands_off_looks_every_2s_for_up_to_60s_and_never_at_the_result(lua):
    autoplay(lua, HANDS_OFF)
    lua.execute("BRIDGE.on_message({ eventID = 202 }); "
                "FAKE.open_scroll('papal_election_results_scroll', {'close_tick_button'})")
    for _ in range(70):
        tick(lua, 1)
    looks = papal_lookups(lua)
    assert set(looks) == {"papal_election_scroll"}  # the results scroll: never
    assert 25 <= len(looks) <= 30  # every 2 s, 3-60 s after the notice
    for _ in range(30):
        tick(lua, 1)
    assert len(papal_lookups(lua)) == len(looks)  # given up
    assert "papal vote: no vote scroll 60s after the notice" in (lua.root / "parley_bridge.log").read_text()


def test_without_hands_off_the_tick_never_looks_for_the_vote(lua):
    autoplay(lua)
    lua.execute("BRIDGE.on_message({ eventID = 202 }); FAKE.open_scroll('papal_election_scroll', {'vote_button'})")
    for _ in range(20):
        tick(lua, 1)
    assert papal_lookups(lua) == []


def test_hands_off_after_the_vote_the_result_gets_its_window(lua):
    # the vote clicked, the result opens: the turn loop presses nothing else until it has closed
    autoplay(lua, HANDS_OFF)
    lua.execute("BRIDGE.on_message({ eventID = 202 }); BRIDGE.on_message({ eventID = 40 })")
    tick(lua, 4)
    lua.execute("FAKE.open_scroll('papal_election_scroll', {'vote_button'})")
    tick(lua, 2)  # seen
    tick(lua, 3)  # asked
    tick(lua, 60)  # the ruler takes a while
    capture_all(lua)  # the loop clicked the ruler's vote
    tick(lua, 1)
    assert "phase=results" in papal_window(lua)
    lua.execute("FAKE.open_scroll('papal_election_results_scroll', {'close_tick_button'})")
    tick(lua, 10)
    assert papal_window(lua) is not None and lua.eval("BRIDGE.deciding()")
    tick(lua, 11)
    assert papal_window(lua) is None and not lua.eval("BRIDGE.deciding()")
    assert papal_lookups(lua) == ["papal_election_scroll"] * 2  # not up yet at 4 s; up at 6 s; never the result
    log = (lua.root / "parley_bridge.log").read_text()
    assert "popup: a papal election vote answered by the ruler" in log


def test_hands_off_entry_script_votes_from_the_frame(tmp_path, monkeypatch):
    # the whole path: the scroll's event returns at once; a later frame finds the vote scroll
    rt, root = _entry_script(tmp_path, monkeypatch, HANDS_OFF)
    rt.execute("package.loaded.parley_bridge.clock = function() return FAKE.now end")
    rt.execute("onIncomingMessage({ eventID = 202 })")
    rt.execute("FAKE.open_scroll('papal_election_scroll', {'vote_button'})")
    rt.execute("onScrollOpened(event('papal_election_scroll'))")
    assert rt.eval("#BRIDGE_CALLS") == 0 and rt.eval("#FAKE.lookups") == 0
    rt.execute("FAKE.now = FAKE.now + 4; draw(nil)")
    rt.execute("FAKE.now = FAKE.now + 4; draw(nil)")  # (K.POPUP_DELAY)
    assert [json.loads(p.read_text())["kind"] for p in root.glob("popup-*.req")] == ["vote"]
    assert "phase=vote" in (root / "papal_window.txt").read_text()
