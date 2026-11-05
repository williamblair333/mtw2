"""Live 10-31 12:50: `just qa field kind=instant case=move_army` failed at once ("timed out after 30.0s
waiting for bridge response to `lua return M.qa.load(...)`"). With the real loop stopped, the
bridge's autoplay still ended the real campaign's turn 7 on its own timeout, and while the game
played the AI turns the bridge answered control.txt slowly or not at all for a minute or more.

So: the park holds the turn first of all; the first bench load waits for the bridge to answer a
trivial line; the load call itself waits longer while the bridge log keeps growing. And a run whose
smoke suite passed records qa.last_smoke whatever its kind or case filter (live 12:34/12:36)."""

from __future__ import annotations

import datetime as dt
import json
import os
import threading
import time
from pathlib import Path

import pytest

from parley.config import load_config
from parley.qa.control import CONTROL_FILE, LOG_FILE, Control, ControlTimeout
from parley.qa.runner import (
    QA_HOLD_REASON,
    QARunError,
    _await_bridge_answer,
    _park_real,
    _send_and_wait,
    run_suite,
)
from test_qa_bench_save import BenchHarness, _game, _run, _start, _suites
from test_qa_runner import FakeHarness, _write_real_game, _write_state

PAUSE = "paused.txt"


def _held(turn_root: Path) -> bool:
    p = turn_root / PAUSE
    return p.exists() and p.read_text(encoding="utf-8").startswith(QA_HOLD_REASON)


# --- 1. the park holds the turn first -------------------------------------------------------------


def _parkable(tmp_path: Path):
    real_toml, turn_root, save_dir = _write_real_game(tmp_path)
    _write_state(turn_root, "scratch", 10)
    hb_mtime = (turn_root / "heartbeat.txt").stat().st_mtime
    autosave = save_dir / "Autosave.sav"
    autosave.write_bytes(b"real-turn-10")
    os.utime(autosave, (hb_mtime + 5.0, hb_mtime + 5.0))
    return real_toml, turn_root, save_dir


def _park(real_toml: Path, turn_root: Path, events: list[str]):
    return _park_real(
        load_config(real_toml), real_toml, turn_root / "qa.lock",
        stop_loop_fn=lambda: events.append(f"stop_loop held={_held(turn_root)}"),
        stop_cw_fn=lambda: events.append("stop_crash_watch"),
        start_real_fn=lambda p: events.append("start_real"),
        start_cw_fn=lambda: events.append("start_crash_watch"),
        now_fn=dt.datetime.now,
    )


def test_the_park_holds_the_turn_before_it_stops_or_copies_anything(tmp_path: Path):
    real_toml, turn_root, save_dir = _parkable(tmp_path)
    events: list[str] = []
    lock, turn = _park(real_toml, turn_root, events)
    assert events[0] == "stop_loop held=True"
    assert _held(turn_root) and turn == 10
    assert lock["park_held"] is True
    assert json.loads((turn_root / "qa.lock").read_text())["park_held"] is True
    assert (save_dir / "parley_keep_scratch.sav").exists()


def test_a_failed_park_lifts_its_own_hold(tmp_path: Path):
    real_toml, turn_root, _ = _write_real_game(tmp_path)  # no real save: the park fails
    events: list[str] = []
    with pytest.raises(QARunError, match="no real save"):
        _park(real_toml, turn_root, events)
    assert events[0] == "stop_loop held=True"
    assert not (turn_root / PAUSE).exists() and not (turn_root / "qa.lock").exists()


def _park_with_decision(real_toml: Path, turn_root: Path, events: list[str], open_checks, **kw):
    def decision_open() -> bool:
        events.append("check")
        return next(open_checks)
    return _park_real(
        load_config(real_toml), real_toml, turn_root / "qa.lock",
        stop_loop_fn=lambda: events.append("stop_loop"),
        stop_cw_fn=lambda: events.append("stop_crash_watch"),
        start_real_fn=lambda p: events.append("start_real"),
        start_cw_fn=lambda: events.append("start_crash_watch"),
        now_fn=dt.datetime.now, decision_open_fn=decision_open, **kw,
    )


def test_the_park_waits_for_an_open_decision_before_it_stops_the_loop(tmp_path: Path):
    # live 10-31 16:19: a marriage offer was open when the bench parked; with the loop stopped and
    # the bench's clicks off it stayed on screen over every bench load, and the game took commands
    # and ran none of them ("game busy" on every case)
    real_toml, turn_root, _ = _parkable(tmp_path)
    events: list[str] = []
    _park_with_decision(real_toml, turn_root, events, iter([True, True, False]),
                        decision_wait=5, decision_poll=0)
    assert events[:4] == ["check", "check", "check", "stop_loop"]


def test_a_decision_left_open_refuses_the_park_and_stops_nothing(tmp_path: Path):
    real_toml, turn_root, _ = _parkable(tmp_path)
    events: list[str] = []
    with pytest.raises(QARunError, match="a decision is open on screen"):
        _park_with_decision(real_toml, turn_root, events, iter(lambda: True, None),
                            decision_wait=0.05, decision_poll=0.01)
    assert "stop_loop" not in events and not (turn_root / "qa.lock").exists()
    assert not (turn_root / PAUSE).exists()


def test_the_park_never_lifts_a_usage_limit_pause(tmp_path: Path):
    real_toml, turn_root, _ = _write_real_game(tmp_path)
    (turn_root / PAUSE).write_text("claude usage limit: reached\n")
    with pytest.raises(QARunError):
        _park(real_toml, turn_root, [])
    assert (turn_root / PAUSE).read_text() == "claude usage limit: reached\n"


class _Watcher(BenchHarness):
    """Notes whether the turn is held at each bench load and whenever the QA turn loop starts."""

    def __init__(self, turn_root: Path):
        super().__init__(turn_root)
        self.held_at: list[str] = []

    def run_lua(self, line: str) -> str:
        if "M.qa.load(" in line:
            self.held_at.append(f"load held={_held(self.turn_root)}")
        return super().run_lua(line)

    def start_qa_loop(self, qa_toml: Path) -> None:  # from here the QA loop's turns may end
        self.held_at.append(f"loop held={_held(self.turn_root)}")
        super().start_qa_loop(qa_toml)


def test_a_bench_run_with_turn_cases_holds_each_load_and_lifts_the_hold_for_its_turns(tmp_path: Path):
    real_toml, turn_root, _ = _game(tmp_path)
    h = _Watcher(turn_root)
    extra = ('\n[[cases]]\nname = "turny"\nturns = 1\n'
             'setup = [\'M.qa.spawn_agent("england", "spy", 1, 2, "X")\']\n'
             'expect = [{ log = "qa: spawn_agent ok" }]\n')
    results, _ = _run(tmp_path, real_toml, h, suites_dir=_suites(tmp_path, extra))
    assert all(r.outcome == "pass" for r in results), results
    loads = [e for e in h.held_at if e.startswith("load")]
    assert loads and all(e == "load held=True" for e in loads), h.held_at
    loops = [e for e in h.held_at if e.startswith("loop")]
    assert loops and all(e == "loop held=False" for e in loops), h.held_at
    assert not (turn_root / PAUSE).exists() and not (turn_root / "qa.lock").exists()


def test_a_live_campaign_run_lifts_the_park_hold_before_its_turns(tmp_path: Path):
    real_toml, turn_root, save_dir = _parkable(tmp_path)
    d = tmp_path / "suites"
    d.mkdir()
    (d / "smoke.toml").write_text(
        'name = "smoke"\nfaction = "england"\n\n[[cases]]\nname = "spawn"\n'
        'setup = [\'M.qa.spawn_agent("england", "spy", 108, 153, "QA Spy")\']\n'
        'expect = [{ log = "qa: spawn_agent ok" }]\n', encoding="utf-8")
    h = _Watcher(turn_root)
    h.on_lua = None  # FakeHarness's own bridge: the live campaign, no bench
    results, _ = run_suite(
        "smoke", real_toml, bench_save=False, suites_dir=d, report_dir=tmp_path / "runs",
        qa_games_dir=tmp_path / "qa-games", control_factory=h.control_factory,
        advance_turn=h.advance_turn, is_game_running=h.is_game_running,
        relaunch_game=h.relaunch_game, stop_loop=h.stop_loop, stop_crash_watch=h.stop_crash_watch,
        start_qa_loop=h.start_qa_loop, stop_qa_loop=h.stop_qa_loop, start_real=h.start_real,
        start_crash_watch=h.start_crash_watch, crash_dialog_up=lambda: False,
        reload_timeout=2.0, poll_interval=0.01,
    )
    assert results[0].outcome == "pass", results
    loops = [e for e in h.held_at if e.startswith("loop")]
    assert loops and all(e == "loop held=False" for e in loops), h.held_at
    assert not (turn_root / PAUSE).exists()


def test_bench_save_start_leaves_no_hold_for_the_new_campaign(tmp_path: Path):
    _, turn_root, _, _, _ = _start(tmp_path)
    assert (turn_root / "bridge.txt").read_text() == "game_id=qa-bench-save\n"
    assert not (turn_root / PAUSE).exists()


# --- 2. the bridge answers before the first bench load; the load waits on a live bridge -----------


def _answer_later(turn_root: Path, delay: float, *, chatter: float | None = None, result: str = "1"):
    """A bridge that logs (every `chatter` s, when given) and answers the control line after `delay`."""
    log = turn_root / LOG_FILE

    def run():
        end = time.monotonic() + delay
        while time.monotonic() < end:
            if chatter is not None:
                with log.open("a", encoding="utf-8") as f:
                    f.write("autoplay: AI turns playing\n")
            time.sleep(chatter or 0.01)
        with log.open("a", encoding="utf-8") as f:
            f.write(f"control: lua -> {result}\n")

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


def test_the_gate_waits_past_controls_timeout_for_a_slow_bridge_sending_the_line_once(tmp_path: Path):
    ctrl = Control(tmp_path, timeout=0.05)
    t = _answer_later(tmp_path, 0.4)
    assert _await_bridge_answer(ctrl, tmp_path / LOG_FILE, None, timeout=5.0, poll_interval=0.01) is None
    t.join()
    # one line: a retry that wrote it again would leave a stale answer for the load to read
    assert (tmp_path / CONTROL_FILE).read_text() == "lua return 1\n"


def test_the_gate_reports_a_busy_game_when_the_bridge_never_answers(tmp_path: Path):
    ctrl = Control(tmp_path, timeout=0.05)
    t0 = time.monotonic()
    busy = _await_bridge_answer(ctrl, tmp_path / LOG_FILE, None, timeout=0.3, poll_interval=0.01)
    assert busy == "game busy: the bridge didn't answer for 0s"
    assert 0.3 <= time.monotonic() - t0 < 2.0


def test_the_gate_stops_on_a_crashed_game(tmp_path: Path):
    from parley.qa.runner import _GameDown
    ctrl = Control(tmp_path, timeout=0.05)
    with pytest.raises(_GameDown, match="game crashed"):
        _await_bridge_answer(ctrl, tmp_path / LOG_FILE, lambda: "game crashed at 12:50: x",
                             timeout=5.0, poll_interval=0.01)


def test_a_load_call_waits_on_a_bridge_whose_log_still_grows(tmp_path: Path):
    ctrl = Control(tmp_path, timeout=0.15)
    t = _answer_later(tmp_path, 0.6, chatter=0.03, result="ok")
    res = _send_and_wait(ctrl, 'return M.qa.load("x")', max_wait=5.0, quiet_limit=0.15,
                         log_path=tmp_path / LOG_FILE, trouble_fn=None, poll_interval=0.01)
    t.join()
    assert res == "ok"
    assert (tmp_path / CONTROL_FILE).read_text() == 'lua return M.qa.load("x")\n'


def test_a_load_call_on_a_silent_bridge_times_out_after_the_quiet_limit(tmp_path: Path):
    ctrl = Control(tmp_path, timeout=0.15)
    t0 = time.monotonic()
    with pytest.raises(ControlTimeout, match="waiting for bridge response"):
        _send_and_wait(ctrl, 'return M.qa.load("x")', max_wait=5.0, quiet_limit=0.15,
                       log_path=tmp_path / LOG_FILE, trouble_fn=None, poll_interval=0.01)
    assert time.monotonic() - t0 < 1.0


def test_a_load_call_gives_up_at_max_wait_even_on_a_chatty_bridge(tmp_path: Path):
    ctrl = Control(tmp_path, timeout=0.1)
    _answer_later(tmp_path, 3.0, chatter=0.02)
    t0 = time.monotonic()
    with pytest.raises(ControlTimeout):
        _send_and_wait(ctrl, 'return M.qa.load("x")', max_wait=0.4, quiet_limit=0.1,
                       log_path=tmp_path / LOG_FILE, trouble_fn=None, poll_interval=0.01)
    assert time.monotonic() - t0 < 1.5


class _Busy(BenchHarness):
    """The bridge answers no `return 1` (ControlTimeout) for its first `silent` ones."""

    def __init__(self, turn_root: Path, silent: int):
        super().__init__(turn_root)
        self.silent = silent

    def run_lua(self, line: str) -> str:
        if line == "return 1" and self.silent > 0:
            self.silent -= 1
            self.lua_calls.append(line)
            raise ControlTimeout(f"timed out after 30.0s waiting for bridge response to `lua {line}`")
        return super().run_lua(line)


def test_the_run_waits_for_the_bridge_before_its_first_bench_load(tmp_path: Path):
    real_toml, turn_root, _ = _game(tmp_path)
    h = _Busy(turn_root, silent=3)
    results, _ = _run(tmp_path, real_toml, h)
    assert [r.outcome for r in results] == ["pass", "pass"], results
    first_load = next(i for i, c in enumerate(h.lua_calls) if "M.qa.load(" in c)
    assert h.lua_calls[:first_load] == ["return 1"] * 4


def test_a_bridge_that_never_answers_ends_the_run_as_game_busy_and_restores(tmp_path: Path):
    real_toml, turn_root, _ = _game(tmp_path)
    h = _Busy(turn_root, silent=10**6)
    with pytest.raises(QARunError, match="game busy: the bridge didn't answer for"):
        _run(tmp_path, real_toml, h, bridge_wait=0.2)
    assert not any("parley_bench" in c for c in h.lua_calls)  # never loaded the bench save
    # the restore ran: the kept save loaded, the hold lifted, the lock gone
    assert any("parley_keep_scratch" in c for c in h.lua_calls)
    assert not (turn_root / "qa.lock").exists() and not (turn_root / PAUSE).exists()


# --- 3. any run whose smoke suite passed records qa.last_smoke ------------------------------------


def test_an_instant_run_with_a_case_filter_records_its_smoke_pass(tmp_path: Path):
    # live 12:34: `just qa field kind=instant case=X` passed smoke; at 12:36 --no-smoke found none
    from test_xinput import _Harness, _real
    from test_xinput import _run as _xrun
    real_toml, turn_root = _real(tmp_path)
    results, _ = _xrun(tmp_path, real_toml, _Harness(turn_root), suite="covert", kind="instant",
                       cases=["covert_instant"])
    assert [(r.name, r.outcome) for r in results] == [
        ("smoke_turn", "skipped"), ("smoke_instant", "pass"), ("covert_instant", "pass")], results
    rec = json.loads((turn_root / "qa.last_smoke").read_text())
    assert rec["passed_epoch"] > 0 and rec["kind"] == "instant"


def test_a_failed_instant_smoke_records_nothing(tmp_path: Path):
    from test_xinput import _Harness, _real
    from test_xinput import _run as _xrun
    real_toml, turn_root = _real(tmp_path)
    h = _Harness(turn_root)
    real_lua = h.on_lua

    def broken(self, line):  # the spawn logs nothing: smoke_instant fails
        return "ok" if "M.qa.spawn_agent(" in line else real_lua(self, line)

    h.on_lua = broken
    results, _ = _xrun(tmp_path, real_toml, h, suite="covert", kind="instant", cases=["covert_instant"])
    assert ("smoke_instant", "fail") in [(r.name, r.outcome) for r in results], results
    assert not (turn_root / "qa.last_smoke").exists()
