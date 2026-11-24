"""A pause is lifted only by whoever set it. Live 11-06: Orchestrator._answer lifted any pause once a ruler
answered, so a QA game's scripted ruler took off `just stop`'s pause and the real campaign, restored with no
turn loop, could end turns with nobody ordering. QA relied on that by accident for its bench turns, so the
park now sets a stop pause aside and the restore puts it back."""
import json
import re
from pathlib import Path

import pytest
from test_qa_park_gate import _park, _parkable, _write_real_game

from parley import pause
from parley.qa.runner import QA_HOLD_REASON, QARunError, _put_back_stop_pause, _release_turn

STOP = "stopped by just stop: the turn loop is off; just play (or removing this file) resumes\n"


class _Started(Exception):
    pass


class _Ctrl:
    def log_offset(self):
        return 0


def _turn_case_starts_its_loop(turn_root, tmp_path):
    from parley.qa.cases import Case, Expect
    from parley.qa.runner import _run_case

    seen = []

    def start(_toml):
        seen.append(pause.path(turn_root).read_text() if pause.paused(turn_root) else None)
        raise _Started  # all this test wants: the state when the case's loop starts

    with pytest.raises(_Started):
        _run_case(Case(name="c", expect=[Expect(log="x")]), "qa-x", "real", "england", turn_root,
                  ctrl=_Ctrl(), current_turn=5, plan_path=tmp_path / "plan.json",
                  qa_toml_path=tmp_path / "qa.toml", start_qa_loop_fn=start,
                  advance_turn_fn=lambda g, f, t: t + 1)
    return seen[0]


def test_a_turn_case_lifts_the_runs_own_hold_before_its_turns(tmp_path):
    # live 11-06: with the answer no longer lifting it, "no report after turn 5 within 180 s"
    turn_root = tmp_path / "turns"
    turn_root.mkdir()
    pause.path(turn_root).write_text(QA_HOLD_REASON + "\n")
    assert _turn_case_starts_its_loop(turn_root, tmp_path) is None


def test_a_turn_case_leaves_a_usage_limit_pause(tmp_path):
    turn_root = tmp_path / "turns"
    turn_root.mkdir()
    pause.pause(turn_root, "claude usage limit")
    assert _turn_case_starts_its_loop(turn_root, tmp_path).startswith(pause.LIMIT_PREFIX)


def test_a_ruler_answering_lifts_a_usage_limit_pause(tmp_path):
    pause.pause(tmp_path, "claude usage limit: session limit")
    pause.resume_limit(tmp_path)
    assert not pause.paused(tmp_path)


@pytest.mark.parametrize("text", [STOP, QA_HOLD_REASON + "\n", "by hand\n"])
def test_a_ruler_answering_leaves_anyone_elses_pause(tmp_path, text):
    pause.path(tmp_path).write_text(text)
    pause.resume_limit(tmp_path)
    assert pause.path(tmp_path).read_text() == text


def test_the_stop_reason_matches_what_just_stop_writes():
    script = (Path(__file__).resolve().parent.parent / "scripts" / "game.sh").read_text()
    assert re.search(r'^STOP_REASON="(.*)"$', script, re.M).group(1) == pause.STOP_REASON


def test_the_park_sets_a_stop_pause_aside_and_keeps_it_in_the_lock(tmp_path: Path):
    real_toml, turn_root, _ = _parkable(tmp_path)
    pause.path(turn_root).write_text(STOP)
    lock, _turn = _park(real_toml, turn_root, [])
    # the run's own hold replaces it, so the run can lift that hold for its bench turns
    assert pause.path(turn_root).read_text().startswith(QA_HOLD_REASON)
    assert lock["park_held"] is True and lock["stop_pause"] == STOP
    assert json.loads((turn_root / "qa.lock").read_text())["stop_pause"] == STOP


def test_a_park_with_no_stop_pause_records_none(tmp_path: Path):
    real_toml, turn_root, _ = _parkable(tmp_path)
    lock, _turn = _park(real_toml, turn_root, [])
    assert "stop_pause" not in lock


def test_a_failed_park_puts_the_stop_pause_back(tmp_path: Path):
    real_toml, turn_root, _ = _write_real_game(tmp_path)  # no real save: the park fails
    pause.path(turn_root).write_text(STOP)
    with pytest.raises(QARunError):
        _park(real_toml, turn_root, [])
    assert pause.path(turn_root).read_text() == STOP


def test_putting_it_back_replaces_the_hold_and_survives_the_release(tmp_path):
    pause.path(tmp_path).write_text(QA_HOLD_REASON + "\n")
    _put_back_stop_pause(tmp_path, STOP)
    _release_turn(tmp_path)
    assert pause.path(tmp_path).read_text() == STOP


def test_nothing_to_put_back_leaves_the_hold_for_the_release(tmp_path):
    pause.path(tmp_path).write_text(QA_HOLD_REASON + "\n")
    _put_back_stop_pause(tmp_path, None)
    assert pause.path(tmp_path).read_text().startswith(QA_HOLD_REASON)
