"""A load of a save that isn't there never reaches EOP (live 10-31: M.qa.load of the keep save the QA
restore had renamed put up EOP's modal "ERROR: Cannot create M2TWEOP save file. 2" box, froze the
game, and closing it ended the game), and the box, when it does come up, is game trouble."""

import subprocess
import tomllib
from pathlib import Path

import pytest

from parley import relaunch
from parley.qa import runner
from parley.qa.cases import Suite
from parley.qa.runner import BenchSave, QARunError

REPO = Path(__file__).parent.parent


class FakeControl:
    def __init__(self, res: str = "") -> None:
        self.lines: list[str] = []
        self.res = res

    def log_offset(self) -> int:
        return 0

    def run_lua(self, line: str) -> str:
        self.lines.append(line)
        return self.res


# --- prevent: the host checks the file before a load goes out ---


def test_load_line_refuses_a_save_that_is_not_there(tmp_path):
    rel = "mods/parley/saves/parley_keep_scratch.sav"
    with pytest.raises(QARunError, match=r"qa: load refused: no save at mods/parley/saves/parley_keep_scratch\.sav"):
        runner._load_line(tmp_path / "parley_keep_scratch.sav", rel)
    save = tmp_path / "parley_keep_scratch.sav"
    save.write_bytes(b"save")
    assert runner._load_line(save, rel) == f'return M.qa.load("{rel}")'


def test_bench_load_of_a_missing_save_sends_nothing_to_the_game(tmp_path):
    bench = BenchSave(path=tmp_path / "parley_bench.sav", rel="mods/parley/saves/parley_bench.sav",
                      turn=3, faction="england", sha256="0" * 64)
    ctrl = FakeControl()
    called = []
    with pytest.raises(QARunError, match="qa: load refused: no save at mods/parley/saves/parley_bench.sav"):
        runner._load_bench_save(bench, ctrl, tmp_path, reload_timeout=1, poll_interval=0.01,
                                on_called=lambda: called.append(1))
    assert ctrl.lines == [] and called == []


def test_resume_after_relaunch_refuses_a_restored_keep_that_vanished(tmp_path, monkeypatch):
    turn_root = tmp_path / "parley_turns"
    saves = tmp_path / "mods" / "parley" / "saves"
    turn_root.mkdir()
    saves.mkdir(parents=True)
    keep = saves / "parley_keep_g1.restored-20261031-120000.sav"
    keep.write_bytes(b"save")
    (turn_root / runner.LAST_RESTORE_FILE).write_text('{"newest_save_mtime": 9e18}')
    (turn_root / runner.LOG_FILE).write_text("2026-10-31 12:00:00 bridge loaded campaign at turn 7\n")
    real_is_file = Path.is_file
    # the keep is renamed between the choice and the load
    monkeypatch.setattr(Path, "is_file", lambda p: False if p.name == keep.name else real_is_file(p))
    ctrl = FakeControl()
    with pytest.raises(QARunError, match="qa: load refused: no save at mods/parley/saves/parley_keep_g1.restored"):
        runner.resume_real_after_relaunch(turn_root, control_factory=lambda root: ctrl, timeout=1, poll_interval=0.01)
    assert ctrl.lines == []


def test_a_bridge_refusal_fails_the_load_wait_at_once(tmp_path):
    log = tmp_path / "parley_bridge.log"
    log.write_text("2026-10-31 12:00:00 qa: load refused: no save at mods/parley/saves/x.sav\n")
    res = "qa: load refused: no save at mods/parley/saves/x.sav"
    with pytest.raises(QARunError, match="load refused"):
        runner._await_campaign_load(res, log, 0, timeout=5, poll_interval=0.01)
    with pytest.raises(QARunError, match="load refused"):
        runner._confirm_load(res, log, 0, expected_turn=3, timeout=5, poll_interval=0.01)
    # loadGame never ran: the game is still where it was
    assert runner._load_never_reached_game(res, log, 0)


def test_set_bypass_refuses_a_save_that_is_not_there(tmp_path, capsys):
    mod = tmp_path / "mods" / "parley"
    (mod / "saves").mkdir(parents=True)
    cfg = mod / "parley.cfg"
    cfg.write_text("[features]\nx = 1\n")
    assert relaunch.main(["set-bypass", str(cfg), "parley_keep_scratch.sav"]) == 1
    assert "load refused: no save at mods/parley/saves/parley_keep_scratch.sav" in capsys.readouterr().err
    assert cfg.read_text() == "[features]\nx = 1\n"
    (mod / "saves" / "parley_keep_scratch.sav").write_bytes(b"save")
    assert relaunch.main(["set-bypass", str(cfg), "parley_keep_scratch.sav"]) == 0
    assert "bypass_to_strategy_save = mods/parley/saves/parley_keep_scratch.sav" in cfg.read_text()


# --- detect: EOP's box is game trouble ---


def test_game_trouble_reports_the_eop_error_box(tmp_path):
    log = tmp_path / "parley_bridge.log"
    log.write_text("2026-10-31 12:00:00 qa: load ok: x\n")
    why = runner.game_trouble(lambda: True, log, hang_seconds=9999, eop_error_box=lambda: "ERROR")
    assert why is not None and "EOP error box: ERROR" in why and why.startswith("game crashed at")
    assert runner.game_trouble(lambda: True, log, hang_seconds=9999, eop_error_box=lambda: None) is None


def test_process_manager_reads_the_box_title_from_the_script(monkeypatch):
    pm = runner._ProcessManager()

    def fake_run(argv, **kw):
        assert argv[-1].endswith("scripts/eop_error_box.sh")
        return subprocess.CompletedProcess(argv, 0, stdout="55 ERROR\n", stderr="")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    assert pm.eop_error_box() == "ERROR"
    monkeypatch.setattr(runner.subprocess, "run",
                        lambda argv, **kw: subprocess.CompletedProcess(argv, 1, stdout="", stderr=""))
    assert pm.eop_error_box() is None


def test_the_box_check_is_real_only_with_the_real_process_check():
    pm = runner._ProcessManager()
    injected = lambda: "ERROR"  # noqa: E731
    assert runner._error_box_check(injected, lambda: True, pm) is injected
    assert runner._error_box_check(None, lambda: True, pm) is None  # a test double: never read X
    assert runner._error_box_check(None, None, pm) == pm.eop_error_box


# --- bench: the instant suite proves the refusal live ---


def test_instant_suite_has_the_missing_save_case():
    suite = Suite.model_validate(tomllib.loads((REPO / "games" / "qa" / "instant.toml").read_text()))
    case = next(c for c in suite.cases if c.name == "load_missing_save_refused")
    assert case.kind == "instant"
    assert case.act == ['return M.qa.load("mods/parley/saves/qa_no_such.sav")']
    assert not (REPO / "mods" / "parley" / "saves" / "qa_no_such.sav").exists()
