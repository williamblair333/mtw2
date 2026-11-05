"""games/qa/popups.toml and its tools: the papal and popup helpers (M.qa) on the fake game, the scene
case in one held turn, and the turn cases' expects against live bridge log excerpts (10-31: a vote
election at 04:50, a results-only one at 05:39, and the 05:29 bench crash). Not a live pass: the fake
is only as true as tests/lua/fake_game.lua, and the log excerpts are elections the game ran itself."""

import re
import tomllib
from pathlib import Path

import pytest
from lupa.luajit21 import LuaRuntime
from pydantic import ValidationError

from parley.qa.cases import Case, Expect, Suite
from parley.qa.checker import alive_after, check
from parley.qa.runner import _probe, _run_instant_case
from tests.test_qa_instant_lua import TickingControl

ROOT = Path(__file__).parent.parent
FIX = ROOT / "tests" / "fixtures" / "qa_popups"
VOTE_LOG = (FIX / "vote-election-2026-10-31-0450.log").read_text(encoding="utf-8")
NO_VOTE_LOG = (FIX / "no-vote-election-2026-10-31-0539.log").read_text(encoding="utf-8")
CRASH_LOG = (FIX / "crash-2026-10-31-0529.log").read_text(encoding="utf-8")
TURN = 3


def _suite(faction: str = "england") -> Suite:
    text = (ROOT / "games" / "qa" / "popups.toml").read_text(encoding="utf-8")
    return Suite.model_validate(tomllib.loads(text.replace('"england"', f'"{faction}"')))


def _case(name: str, faction: str = "england") -> Case:
    return next(c for c in _suite(faction).cases if c.name == name)


# --- the suite ---------------------------------------------------------------------------------


def test_the_popups_suite_loads_with_popup_cases_on_turns_and_the_scene_instant():
    suite = _suite()
    kinds = {c.name: c.kind for c in suite.cases}
    assert kinds == {
        "papal_scene": "instant",
        "event_scroll_closed": "turn",
        "faction_overview_closed": "turn",
        "papal_election_vote": "turn",
        "papal_election_no_vote": "turn",
    }
    # a crash ends the run: the case built to reproduce one goes last
    assert suite.cases[-1].name == "papal_election_no_vote"
    for case in suite.cases:
        assert all(e.independent for e in case.expect), case.name
        for e in case.expect:
            for pattern in (e.log, e.after):
                if pattern:
                    re.compile(pattern)


def test_both_election_cases_check_the_game_lived_on():
    for name in ("papal_election_vote", "papal_election_no_vote"):
        alive = [e for e in _case(name).expect if e.alive is not None]
        assert alive and alive[0].alive >= 30, name


# --- the turn cases' expects on live elections ----------------------------------------------------


def test_the_vote_case_passes_on_the_live_vote_election():
    v = check(_case("papal_election_vote"), VOTE_LOG, state=None, results=None, turns_used=1)
    assert v.outcome == "pass", v.evidence
    assert "alive 30 s after 04:51:12" in v.evidence


def test_the_vote_case_does_not_pass_on_an_election_england_had_no_vote_in():
    v = check(_case("papal_election_vote"), NO_VOTE_LOG, state=None, results=None, turns_used=2)
    assert v.outcome == "fail"
    assert "vote scroll is up" in v.evidence


def test_the_no_vote_case_passes_on_the_live_results_only_election():
    v = check(_case("papal_election_no_vote"), NO_VOTE_LOG, state=None, results=None, turns_used=1)
    assert v.outcome == "pass", v.evidence


def test_the_no_vote_case_fails_on_the_0529_bench_crash():
    # 05:29:44 the check was asked for; the next lines are the relaunched game's (05:30:31)
    v = check(_case("papal_election_no_vote"), CRASH_LOG, state=None, results=None, turns_used=2)
    assert v.outcome == "fail"
    assert "acknowledged with its check" in v.evidence


def test_the_event_case_needs_the_events_own_message_handled_before_the_turn_ends():
    case = _case("event_scroll_closed")
    ok_log = (
        "2026-10-31 10:00:00 qa: event ok: first_wheelbarrow\n"
        "2026-10-31 10:00:01 popup message 31\n"
        "2026-10-31 10:00:09 popup handled: game message 31 (acknowledged with its check)\n"
    )
    assert check(case, ok_log, None, None, 1).outcome == "pass"
    # a message of the turn's end is not the event's
    late = (
        "2026-10-31 10:00:00 qa: event ok: first_wheelbarrow\n"
        "2026-10-31 10:01:00 autoplay: ending turn 3\n"
        "2026-10-31 10:01:01 popup message 31\n"
        "2026-10-31 10:01:09 popup handled: game message 31 (clear_messages)\n"
    )
    assert check(case, late, None, None, 1).outcome == "fail"
    # another message handled is not this one
    other = (
        "2026-10-31 10:00:00 qa: event ok: first_wheelbarrow\n"
        "2026-10-31 10:00:01 popup message 31\n"
        "2026-10-31 10:00:09 popup handled: game message 312 (clear_messages)\n"
    )
    assert check(case, other, None, None, 1).outcome == "fail"


def test_the_overview_case_needs_the_stuck_close_after_the_press():
    case = _case("faction_overview_closed")
    log = (
        "2026-10-31 10:00:00 qa: press ok: faction_button\n"
        "2026-10-31 10:00:40 autoplay: france's turn stuck? try 1: combined_overview_scroll's tick\n"
    )
    v = check(case, log, None, None, 1)
    assert v.outcome == "pass", v.evidence
    assert "\n" not in v.evidence  # a match over lines is shown as its first and last
    assert check(case, log.split("\n", 1)[1], None, None, 1).outcome == "fail"


# --- the alive check ---------------------------------------------------------------------------------


def test_alive_after_needs_a_line_that_many_seconds_later():
    log = "2026-10-31 10:00:00 papal window: results; x\n2026-10-31 10:00:20 a\n2026-10-31 10:00:31 b\n"
    ok, seen = alive_after(log, "papal window: results", 30)
    assert ok and seen.endswith("10:00:31 b")
    ok, seen = alive_after(log, "papal window: results", 60)
    assert not ok and "+31 s" in seen
    assert alive_after(log, "nothing like it", 1) == (False, "log 'nothing like it' not found")


def test_alive_after_ignores_a_relaunched_games_lines():
    log = ("2026-10-31 05:29:44 papal notice: no election after 15s; asking for its check\n"
           "2026-10-31 05:29:46 tick\n"
           "2026-10-31 05:30:31 papal window: notice (kept across the reload)\n"
           "2026-10-31 05:31:08 bridge loaded campaign at turn 50\n"
           "2026-10-31 05:32:00 later\n")
    ok, seen = alive_after(log, "asking for its check", 30)
    assert not ok and "loaded again" in seen and "+2 s" in seen


def test_an_alive_expect_is_a_check_of_its_own():
    Expect(alive=30, after="x", within=60)
    for bad in ({"alive": 30}, {"after": "x"}, {"alive": 30, "after": "x", "log": "y"},
                {"alive": 0, "after": "x"}, {"alive": 5, "after": "x", "lua": "return 1", "equals": "1"}):
        with pytest.raises(ValidationError):
            Expect(**bad)
    # in either kind of case
    Case(name="t", expect=[{"alive": 5, "after": "x"}])
    Case(name="i", kind="instant", expect=[{"alive": 5, "after": "x"}])


class _Ctrl:
    """Answers every control line and logs it, as the bridge does."""

    def __init__(self, log: Path, lines: list[str]):
        self.log, self.lines, self.asked = log, lines, []

    def log_offset(self) -> int:
        return self.log.stat().st_size

    def run_lua(self, line: str) -> str:
        self.asked.append(line)
        with self.log.open("a", encoding="utf-8") as f:
            f.write(self.lines.pop(0) if self.lines else "")
        return "england 3"


def test_an_instant_alive_check_asks_the_bridge_and_reads_the_log(tmp_path):
    log = tmp_path / "parley_bridge.log"
    log.write_text("2026-10-31 10:00:00 papal window: results; x\n", encoding="utf-8")
    ctrl = _Ctrl(log, ["2026-10-31 10:00:10 control: lua -> england 3\n",
                       "2026-10-31 10:00:31 control: lua -> england 3\n"])
    exp = Expect(alive=30, after="papal window: results")
    assert _probe(exp, {}, ctrl, log, 0, None)[:1] == (False,)
    ok, seen, fatal = _probe(exp, {}, ctrl, log, 0, None)
    assert ok and not fatal and "10:00:31" in seen
    assert ctrl.asked == ["return M.qa.current()"] * 2


# --- the helpers on the fake game ----------------------------------------------------------------


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
    rt.execute("FAKE.add_college('Pope Gregory', { { 'Cardinal Ottone', 'milan' }, { 'Cardinal Hugo', 'hre' } })")
    (root / "g1" / f"turn-{TURN:04d}" / "venice" / "state.json").write_text(
        '{"turn": 3, "faction": "venice", "settlements": [{"id": "Venice", "x": 120, "y": 88}]}'
    )
    return rt, root


def _qa(rt, call: str):
    return rt.eval(f"BRIDGE.qa.{call}")


def _log(root: Path) -> str:
    return (root / "parley_bridge.log").read_text(encoding="utf-8")


def _calls(rt) -> list[str]:
    return list(rt.eval("FAKE.calls").values())


def test_pope_and_cardinals_read_the_college(game):
    rt, root = game
    assert _qa(rt, "pope()") == "Pope Gregory"
    assert _qa(rt, "cardinals('venice')") == 0
    assert _qa(rt, "cardinals('milan')") == 1


def test_give_cardinal_moves_a_foreign_one_by_the_games_own_switch(game):
    rt, root = game
    assert _qa(rt, "give_cardinal('venice')") == "Cardinal Ottone"
    assert "switchFaction Cardinal Ottone venice" in _calls(rt)
    assert _qa(rt, "cardinals('venice')") == 1
    assert _qa(rt, "give_cardinal('venice')") == "Cardinal Ottone (already venice's)"
    assert _calls(rt).count("switchFaction Cardinal Ottone venice") == 1


def test_give_cardinal_sets_the_college_entry_when_the_switch_left_it(game):
    rt, root = game
    rt.execute("FAKE.college_keeps_faction = true")
    assert _qa(rt, "give_cardinal('venice')") == "Cardinal Ottone"
    assert _qa(rt, "cardinals('venice')") == 1


def test_give_cardinal_fails_with_nobody_to_give(game):
    rt, root = game
    rt.execute("FAKE.college.entries = {}; FAKE.college.cardinalNum = 0")
    assert _qa(rt, "give_cardinal('venice')") is None
    assert re.search(r"qa: give_cardinal failed: .*no cardinal to give venice \(the college has 0\)", _log(root))


def test_drop_cardinals_kills_the_factions_own(game):
    rt, root = game
    assert _qa(rt, "drop_cardinals('milan')") == "1 killed: Cardinal Ottone; the college counts 0 now"
    assert "kill Cardinal Ottone" in _calls(rt)
    assert _qa(rt, "drop_cardinals('venice')") == "0 killed: -; the college counts 0 now"


def test_kill_pope_kills_him_once(game):
    rt, root = game
    assert _qa(rt, "kill_pope()") == "Pope Gregory"
    assert "kill Pope Gregory" in _calls(rt)
    assert rt.eval("FAKE.college.inElection") is True
    assert _qa(rt, "kill_pope()") is None
    assert "qa: kill_pope failed: " in _log(root) and "an election is already on" in _log(root)
    assert _qa(rt, "pope()") is None


def test_no_papal_helper_touches_the_screen(game):
    rt, root = game
    for call in ("pope()", "cardinals('venice')", "give_cardinal('venice')", "drop_cardinals('venice')",
                 "kill_pope()"):
        _qa(rt, call)
    assert list(rt.eval("FAKE.lookups").values()) == []


def test_event_raises_a_historic_event_by_script_command(game):
    rt, root = game
    assert _qa(rt, "event('first_wheelbarrow')") == "first_wheelbarrow"
    assert "script historic_event first_wheelbarrow" in _calls(rt)
    assert _qa(rt, "event('two words')") is None


def test_press_clicks_a_named_button_but_never_a_papal_one(game):
    rt, root = game
    assert _qa(rt, "press('faction_button')") == "faction_button"
    calls = _calls(rt)
    assert "script select_ui_element faction_button" in calls
    assert "script simulate_mouse_click lclick_up" in calls
    assert _qa(rt, "press('papal_election_scroll')") is None
    assert list(rt.eval("FAKE.lookups").values()) == ["faction_button"]


def test_the_scene_case_runs_on_the_fake_game_in_one_held_turn(game):
    rt, root = game
    ctrl = TickingControl(rt, root)
    res, _ = _run_instant_case(_case("papal_scene", "venice"), "qa-popups", "g1", "venice", root, ctrl, TURN,
                               poll_interval=0.0, turn_wait=1.0)
    assert res.outcome == "pass", (res.evidence, ctrl.lines)
    assert not (root / "paused.txt").exists()
    assert "kill " not in " ".join(_calls(rt))  # the scene kills nobody


@pytest.mark.parametrize("name", ["event_scroll_closed", "faction_overview_closed",
                                  "papal_election_vote", "papal_election_no_vote"])
def test_each_turn_cases_setup_runs_on_the_fake_game(game, name):
    rt, root = game
    ctrl = TickingControl(rt, root)
    case = _case(name, "venice")
    for step in case.setup:
        line = step if isinstance(step, str) else step.lua
        res = ctrl.run_lua(line)
        assert res not in ("", "nil") and not res.endswith("(error)"), (line, res)
    assert " failed: " not in _log(root)
