"""games/qa/diplomacy.toml: its instant cases run by the QA runner through the bridge's control file
against the fake game (as tests/test_qa_instant_lua.py does for instant.toml), its turn cases checked
for shape, and the M.qa diplomacy helpers on their own. The fake's diplomacy screen is a model of what
was seen live (offer buttons that linger after an answer, a close seal that doesn't close a screen
whose offer waits); not a live pass."""

import json
import tomllib
from pathlib import Path

import pytest
from lupa.luajit21 import LuaRuntime

from parley.qa.cases import Case, Suite
from parley.qa.runner import (
    QA_MESSAGES,
    _case_messages,
    _case_results,
    _required_placeholders,
    _run_instant_case,
)
from parley.seats.script import ScriptSeat
from tests.test_qa_instant_lua import ROBIN_IN_VENICE, TURN, TickingControl

ROOT = Path(__file__).parent.parent

# The fake's diplomacy screen. An envoy of the AI parleying a Venetian town or character brings an
# offer (accept/decline buttons on the open screen; a second one on an open screen reuses the
# buttons, as live); Venice's own envoy opens the screen with no offer. Pressing accept or decline
# answers the offer and leaves the buttons lingering (live 10-27). The seal (the screen's unnamed
# bottom-right part, live scan 58x65 at 962,703) closes the screen unless an offer waits on it.
DIPLOMACY_SCREEN = """
local function button(name)
    FAKE.ui[name] = { elementName = name, subElementsNum = 0, execute = function()
        table.insert(FAKE.calls, 'press ' .. name)
        FAKE.offer_waiting = false
    end }
end
local function screen()
    if FAKE.ui.diplomacy_scroll then return end
    local seal = { xPos = 962, yPos = 703, xSize = 58, ySize = 65, execute = function()
        table.insert(FAKE.calls, 'press seal')
        if FAKE.offer_waiting then return end
        for _, n in ipairs({ 'diplomacy_scroll', 'diplomacy_accept_offer_button',
                             'diplomacy_decline_offer_button' }) do FAKE.ui[n] = nil end
    end }
    FAKE.ui.diplomacy_scroll = { elementName = 'diplomacy_scroll', xPos = 0, yPos = 0, xSize = 1024,
        ySize = 768, subElementsNum = 1, getSubElement = function(self, i) return seal end }
end
FAKE.offer_waiting = false
-- every spawn named anew, as the live game names them from its list (live 10-30)
FAKE.spawn_ignores_names = true
local spawned = 0
for _, f in ipairs(FAKE.factions) do
    local create = f.createCharacter
    f.createCharacter = function(...)
        spawned = spawned + 1
        FAKE.random_name = 'Envoy' .. spawned
        return create(...)
    end
end
FAKE.on_parley = function(c, target, fac)
    local theirs = target.ownerFaction or (target.namedCharacter and target.namedCharacter.faction)
    screen()
    if fac.name ~= 'venice' and theirs == FAKE.byName.venice then
        FAKE.offer_waiting = true
        table.insert(FAKE.calls, 'offer from ' .. fac.name)
        button('diplomacy_accept_offer_button')
        button('diplomacy_decline_offer_button')
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
    (root / "bridge.txt").write_text("game_id=g1\nfaction=venice\nautoplay=1\nautoplay_wait=60\n")
    rt.execute(f"BRIDGE = require('parley_bridge'); BRIDGE.setup('{root}'); "
               "BRIDGE.clock = function() return FAKE.now end")
    rt.execute(ROBIN_IN_VENICE)
    rt.execute(DIPLOMACY_SCREEN)
    rt.execute("FAKE.ui.end_turn = { elementName = 'end_turn', "
               "execute = function() FAKE.calls[#FAKE.calls + 1] = 'press end_turn' end }")
    (root / "g1" / f"turn-{TURN:04d}" / "venice" / "state.json").write_text(
        '{"turn": 3, "faction": "venice", "settlements": [{"id": "Venice", "x": 120, "y": 88}], '
        '"armies": [{"id": "garrison:Venice", "in_settlement": "Venice", "leader": "Captain Robin"}]}'
    )
    return rt, root


def _suite() -> Suite:
    """diplomacy.toml as written, with the fake's faction for England."""
    text = (ROOT / "games" / "qa" / "diplomacy.toml").read_text(encoding="utf-8")
    return Suite.model_validate(tomllib.loads(text.replace('"england"', '"venice"')))


def _calls(rt) -> list[str]:
    return list(rt.eval("FAKE.calls").values())


def test_the_diplomacy_suite_s_instant_cases_run_on_the_fake_game_in_one_held_turn(game):
    rt, root = game
    ctrl = TickingControl(rt, root)
    results = {}
    for case in (c for c in _suite().cases if c.kind == "instant"):
        res, _ = _run_instant_case(case, "qa-diplomacy", "g1", "venice", root, ctrl, TURN,
                                   poll_interval=0.0, turn_wait=1.0)
        results[case.name] = res
        assert not (root / "paused.txt").exists()

    assert set(results) == {"set_stance_war", "set_stance_peace", "set_stance_alliance", "send_gold",
                            "screen_left_open_closed", "ai_offer_accepted", "second_offer_asked_again",
                            "cede_settlement"}
    failed = {name: (res.outcome, res.evidence) for name, res in results.items() if res.outcome != "pass"}
    assert not failed, failed
    calls = _calls(rt)
    assert "press end_turn" not in calls
    # the ruler's answers were pressed, each its own button: the first offer declined, then accepted
    presses = [c for c in calls if c.startswith("press ")]
    assert presses.count("press diplomacy_accept_offer_button") == 2, presses
    assert presses.count("press diplomacy_decline_offer_button") == 1, presses
    log = (root / "parley_bridge.log").read_text()
    assert log.count("a new offer: asking the ruler again") == 1
    assert "changeOwner Ragusa" in " ".join(calls)


def test_a_game_that_shows_no_offer_skips_the_offer_case_never_passes_it(game):
    # live, an AI envoy's parley on England's turn may bring nothing up: inconclusive, with the reason
    rt, root = game
    rt.execute("FAKE.on_parley = nil")
    ctrl = TickingControl(rt, root)
    case = next(c for c in _suite().cases if c.name == "ai_offer_accepted")
    res, _ = _run_instant_case(case, "qa-diplomacy", "g1", "venice", root, ctrl, TURN,
                               poll_interval=0.0, turn_wait=1.0)
    assert res.outcome == "inconclusive", res.evidence
    assert "offer=no" in res.evidence


def test_a_screen_the_bridge_cannot_close_fails_the_case(game):
    # a seal that doesn't close it and no close button that works: the step reports the screen open
    rt, root = game
    rt.execute("local on = FAKE.on_parley; FAKE.on_parley = function(...) on(...); FAKE.offer_waiting = true end")
    ctrl = TickingControl(rt, root)
    case = next(c for c in _suite().cases if c.name == "screen_left_open_closed")
    case = case.model_copy(update={"expect": [case.expect[0].model_copy(update={"within": 0.5})]})
    res, _ = _run_instant_case(case, "qa-diplomacy", "g1", "venice", root, ctrl, TURN,
                               poll_interval=0.0, turn_wait=1.0)
    assert res.outcome == "fail", res.evidence
    assert "screen=open" in res.evidence


def test_the_turn_cases_name_only_what_setup_binds_or_the_runner_finds():
    suite = Suite.model_validate(tomllib.loads((ROOT / "games/qa/diplomacy.toml").read_text(encoding="utf-8")))
    live = {"garrison_town", "garrison_town_x", "garrison_town_y"}
    for case in suite.cases:
        assert _required_placeholders(case) - case.binds <= live, case.name
    turn = {c.name: c for c in suite.cases if c.kind == "turn"}
    assert set(turn) == {"orders_next_report", "ai_offer_on_its_turn"}
    assert turn["ai_offer_on_its_turn"].choice == "accept" and turn["ai_offer_on_its_turn"].chance
    types = [o["type"] for o in turn["orders_next_report"].orders[1]]
    assert types == ["set_stance", "set_stance", "set_stance", "send_gold", "cede_settlement", "say"]


def test_an_instant_case_takes_no_choice():
    with pytest.raises(ValueError, match="no choice"):
        Case(name="x", kind="instant", choice="accept", expect=[{"log": "x"}])


def test_the_script_seat_says_its_messages_and_answers_choices(tmp_path):
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"5": [{"type": "set_stance", "to": "france", "stance": "war"},
                                      {"type": "say", "to": "lobby", "text": "hello"}],
                                "choice": "accept"}))
    seat = ScriptSeat(str(plan))
    orders, _ = seat.decide("", game_id="g", turn=5, faction="england", timeout=1)
    assert [o.type for o in orders.orders] == ["set_stance"]
    assert [(m.to, m.text) for m in orders.messages] == [("lobby", "hello")]
    assert seat.chat("You rule england. The game asks you to decide an AI's offer NOW", timeout=1).startswith("ACCEPT")
    assert seat.chat("what do you think of France?", timeout=1) == ""
    plan.write_text(json.dumps({"5": []}))
    assert ScriptSeat(str(plan)).chat("The game asks you to decide x", timeout=1) == ""


def test_case_results_number_the_orders_without_the_say_entries(tmp_path):
    d = tmp_path / "g" / "turn-0005" / "england"
    d.mkdir(parents=True)
    (d / "results.json").write_text(json.dumps([{"index": 0, "type": "set_stance", "ok": True},
                                                {"index": 1, "type": "send_gold", "ok": True}]))
    plan = {"5": [{"type": "say", "to": "lobby", "text": "hi"}, {"type": "set_stance"}, {"type": "send_gold"}]}
    _, own = _case_results(tmp_path, "g", "england", plan, 6, since=0.0)
    assert [r["type"] for r in own] == ["set_stance", "send_gold"]


def test_case_messages_are_the_kept_ones_of_the_case_s_order_turn(tmp_path):
    d = tmp_path / "g" / "turn-0005" / "england"
    d.mkdir(parents=True)
    (d / "messages.json").write_text(json.dumps({"kept": [{"to": "lobby", "text": "hi"}],
                                                 "rejected": [{"index": 1, "type": "say"}]}))
    plan = {"5": [{"type": "say", "to": "lobby", "text": "hi"}]}
    assert _case_messages(tmp_path, "g", "england", plan, 6, since=0.0) == [{"to": "lobby", "text": "hi"}]
    # an earlier run's file (older than the case's plan) is not the case's
    assert _case_messages(tmp_path, "g", "england", plan, 6, since=(d / "messages.json").stat().st_mtime + 60) == []
    assert QA_MESSAGES == "qa_messages"


def _helper(rt, root, line: str) -> str:
    ctrl = TickingControl(rt, root)
    return ctrl.run_lua(line)


def test_rival_skips_seats_rebels_and_players_and_puts_peace_first(game):
    rt, root = game
    # milan at peace, hre at war; venice is the player and the seat, slave the rebels
    assert _helper(rt, root, 'return M.qa.rival("venice")') == "milan"
    assert _helper(rt, root, 'return M.qa.rival("venice", 2)') == "hre"
    assert _helper(rt, root, 'return M.qa.rival("venice", 3)') == "nil"
    assert "no rival #3 for venice among 2" in (root / "parley_bridge.log").read_text()


def test_rival_of_the_same_religion_skips_the_others(game):
    # live 10-31 17:13: the marriage case's rival was the Aztecs (religion 3, England 0), and the
    # game ran no marriage mission for England's princess
    rt, root = game
    rt.execute("FAKE.byName.venice.religion = 0; FAKE.byName.milan.religion = 3; FAKE.byName.hre.religion = 0")
    assert _helper(rt, root, 'return M.qa.rival("venice")') == "milan"
    assert _helper(rt, root, 'return M.qa.rival("venice", 1, true)') == "hre"


def test_diplomacy_orders_go_through_the_bridge_s_apply_and_a_refusal_is_reported(game):
    rt, root = game
    assert _helper(rt, root, 'return M.qa.order("venice", { type = "send_gold", to = "milan", amount = 99999 })') \
        == "send_gold refused: treasury too low (5000)"
    assert _helper(rt, root, 'return M.qa.order("venice", { type = "set_stance", to = "milan", stance = "war" })') \
        == "set_stance ok"
    assert "setDipStance 0 venice milan" in _calls(rt)
    assert _helper(rt, root, 'return M.qa.stance("venice", "milan")') == "war"


def test_court_parleys_at_the_envoy_s_faction_s_turn_start_only(game):
    rt, root = game
    rt.execute("FAKE.add_character(FAKE.byName.milan, 'Envoy Gian', 'diplomat', 121, 89)")
    assert "parleys with Venice at milan's next turn start" in _helper(rt, root, 'return M.qa.court("Envoy Gian", "Venice")')
    rt.execute("BRIDGE.on_turn_start(FAKE.byName.hre)")
    assert not any(c.startswith("diplomacySettlement") for c in _calls(rt))
    rt.execute("BRIDGE.on_turn_start(FAKE.byName.milan)")
    assert "diplomacySettlement Envoy Gian Venice" in _calls(rt)
    rt.execute("BRIDGE.on_turn_start(FAKE.byName.milan)")  # once only
    assert _calls(rt).count("diplomacySettlement Envoy Gian Venice") == 1
    assert "qa: court: Envoy Gian parleys with Venice at milan's turn start\n" in (root / "parley_bridge.log").read_text()


def test_screen_never_looks_up_a_papal_scroll(game):
    rt, root = game
    assert _helper(rt, root, 'return M.qa.screen("papal_election_scroll")') == "nil"
    assert "papal_election_scroll" not in list(rt.eval("FAKE.lookups").values())
