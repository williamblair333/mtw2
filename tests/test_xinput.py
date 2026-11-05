"""Phase 1 of the no-click rule (the author, 10-31): `--kind instant` runs only the instant cases, starts
no QA turn loop, and makes the whole run a no-click run (PARLEY_NO_X_INPUT=1) in which every
X-input helper refuses; and the bench save can be made from an existing save with no menu."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tomllib
from pathlib import Path

import pytest

from parley import popups
from parley.qa.__main__ import main as qa_main
from parley.qa.cases import Suite
from parley.qa.runner import (
    SKIPPED_TURN_CASE,
    QARunError,
    _ProcessManager,
    _no_click_guarded,
    _run_instant_case,
    bench_save_record,
    load_bench_save,
    run_suite,
)
from parley.xinput import ENV_VAR, XInputRefused, env_without, no_click_run, refuse_x_input, refuse_xdotool
from test_qa_bench_save import _game
from test_qa_instant_lua import TURN, TickingControl, game  # noqa: F401  (game is a fixture)
from test_qa_runner import FakeHarness, _write_real_game, _write_state

ROOT = Path(__file__).parent.parent


@pytest.fixture(autouse=True)
def _clicks_allowed_by_default(monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)


# --- the guard ----------------------------------------------------------------------------------


def test_the_guard_refuses_only_in_a_no_click_run(monkeypatch):
    refuse_x_input("anything")  # unset: allowed
    monkeypatch.setenv(ENV_VAR, "0")
    refuse_x_input("anything")
    monkeypatch.setenv(ENV_VAR, "1")
    with pytest.raises(XInputRefused, match="X input refused in a no-click run: a click"):
        refuse_x_input("a click")


def test_xdotool_reads_pass_and_input_verbs_refuse(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "1")
    for verb in ("search", "getwindowgeometry", "getmouselocation", "getactivewindow"):
        refuse_xdotool([verb, "x"])
    for verb in ("mousemove", "click", "mousedown", "mouseup", "key", "type", "windowactivate", "windowraise"):
        with pytest.raises(XInputRefused, match=f"xdotool {verb}"):
            refuse_xdotool([verb, "1"])


def test_no_click_run_sets_and_puts_back(monkeypatch):
    with no_click_run():
        assert os.environ[ENV_VAR] == "1"
        assert ENV_VAR not in env_without()
    assert ENV_VAR not in os.environ
    monkeypatch.setenv(ENV_VAR, "keep")
    with no_click_run():
        pass
    assert os.environ[ENV_VAR] == "keep"


def _no_subprocess(monkeypatch) -> list:
    calls: list = []

    def run(argv, *a, **k):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, stdout="X=0\nY=0\nWIDTH=1600\nHEIGHT=900\n", stderr="")

    monkeypatch.setattr(popups.subprocess, "run", run)
    return calls


def test_popup_click_refuses_before_touching_x(monkeypatch):
    calls = _no_subprocess(monkeypatch)
    monkeypatch.setenv(ENV_VAR, "1")
    with pytest.raises(XInputRefused, match="click accept on a popup"):
        popups.click("accept")
    with pytest.raises(XInputRefused, match="pointer move"):
        popups._clear_pointer("22")
    with pytest.raises(XInputRefused, match="pointer move"):
        popups.screenshot(Path("x.png"))  # it moves the pointer first
    with pytest.raises(XInputRefused, match="xdotool mousemove"):
        popups._xdo("mousemove", "1", "2")
    assert all(c[:2] != ["xdotool", "mousemove"] for c in calls)
    assert not any("mousedown" in c or "windowactivate" in c for c in calls)
    popups._xdo("search", "--name", "x")  # a read still goes through
    assert calls[-1] == ["xdotool", "search", "--name", "x"]


def test_popup_click_still_clicks_outside_a_no_click_run(monkeypatch):
    calls = _no_subprocess(monkeypatch)
    monkeypatch.setattr(popups.time, "sleep", lambda s: None)
    popups.click("accept")
    assert ["xdotool", "mousedown", "1"] in calls


def _fake_bin(tmp_path: Path) -> tuple[Path, Path]:
    log = tmp_path / "calls.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("xdotool", "wmctrl", "pgrep", "pkill", "steam", "systemd-run"):
        p = bin_dir / name
        p.write_text(f'#!/usr/bin/env bash\necho "{name} $*" >>"{log}"\n')
        p.chmod(0o755)
    return bin_dir, log


def test_relaunch_script_refuses_clicks_before_killing_anything(tmp_path: Path):
    bin_dir, log = _fake_bin(tmp_path)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", ENV_VAR: "1",
           "PARLEY_TURN_ROOT": str(tmp_path)}
    r = subprocess.run(["bash", str(ROOT / "scripts" / "relaunch_game.sh"), "--clicks"], env=env,
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 3
    assert "X input refused in a no-click run: relaunch_game.sh --clicks" in r.stderr
    assert not log.exists()  # no pgrep, pkill, steam, xdotool or wmctrl


def test_process_manager_relaunches_in_a_no_click_run_but_refuses_the_qa_loop(monkeypatch, tmp_path: Path):
    # the relaunch makes no clicks (hidden launcher, save loaded at start-up): allowed
    ran: list = []
    monkeypatch.setattr("parley.qa.runner.subprocess.run", lambda argv, **k: ran.append(argv))
    monkeypatch.setattr("parley.qa.runner.subprocess.Popen", lambda argv, **k: ran.append(argv))
    monkeypatch.setenv(ENV_VAR, "1")
    pm = _ProcessManager()
    pm.relaunch_game(save="parley_keep_scratch.sav")
    assert ran == [["bash", str(ROOT / "scripts" / "relaunch_game.sh"), "--save", "parley_keep_scratch.sav"]]
    pm.relaunch_game()
    assert ran[-1] == ["bash", str(ROOT / "scripts" / "relaunch_game.sh")]
    ran.clear()
    with pytest.raises(QARunError, match="the QA turn loop"):
        pm.start_qa_loop(tmp_path / "qa-x.toml")
    assert ran == []
    # injected starters are guarded too
    with pytest.raises(QARunError, match="X input refused"):
        _no_click_guarded(lambda: pytest.fail("called"), "the QA loop")()


def test_the_real_campaigns_restarts_never_inherit_the_no_click_variable(monkeypatch):
    seen: list = []
    monkeypatch.setattr("parley.qa.runner.subprocess.run", lambda argv, **k: seen.append((argv, k.get("env"))))
    monkeypatch.setenv(ENV_VAR, "1")
    pm = _ProcessManager(run_fn=lambda argv, **k: seen.append((argv, k.get("env"))))
    pm.start_real(Path("games/local/scratch.toml"))
    pm.start_crash_watch()
    assert len(seen) == 2
    for argv, env in seen:
        assert env is not None and ENV_VAR not in env, argv


# --- `--kind instant` ---------------------------------------------------------------------------


def _suites(tmp_path: Path) -> Path:
    d = tmp_path / "suites"
    d.mkdir()
    instant = ('\n[[cases]]\nname = "{n}"\nkind = "instant"\n'
               'setup = [\'return M.qa.spawn_agent("england", "spy", 1, 2, "S")\']\n'
               'expect = [{{ log = "qa: spawn_agent ok" }}]\n')
    turn = ('\n[[cases]]\nname = "{n}"\n'
            'setup = [\'return M.qa.teleport("x", 1, 2)\']\n'
            'expect = [{{ log = "qa: teleport ok" }}]\n')
    (d / "smoke.toml").write_text('name = "smoke"\nfaction = "england"\n'
                                  + turn.format(n="smoke_turn") + instant.format(n="smoke_instant"))
    (d / "covert.toml").write_text('name = "covert"\nfaction = "england"\n'
                                   + instant.format(n="covert_instant") + turn.format(n="covert_turn"))
    (d / "navy.toml").write_text('name = "navy"\nfaction = "england"\n' + turn.format(n="navy_turn"))
    return d


class _Harness(FakeHarness):
    def __init__(self, turn_root: Path, **kw):
        super().__init__(turn_root, **kw)
        self.env_seen: list[str | None] = []
        self.on_lua = _Harness._lua

    def _lua(self, line: str) -> str:
        self.env_seen.append(os.environ.get(ENV_VAR))
        if "M.qa.current()" in line:
            return "england 10"
        self.on_lua = None
        try:
            return FakeHarness.run_lua(self, line)
        finally:
            self.on_lua = _Harness._lua


def _real(tmp_path: Path):
    real_toml, turn_root, save_dir = _write_real_game(tmp_path)
    (save_dir / "Autosave.sav").write_bytes(b"save-turn-10")
    _write_state(turn_root, "scratch", 10)
    return real_toml, turn_root


def _run(tmp_path, real_toml, h, suite="covert", **kw):
    return run_suite(
        suite, real_toml, bench_save=False, suites_dir=_suites(tmp_path),
        report_dir=tmp_path / "runs" / "qa", qa_games_dir=tmp_path / "qa-games",
        control_factory=h.control_factory, advance_turn=h.advance_turn,
        is_game_running=h.is_game_running, relaunch_game=h.relaunch_game,
        stop_loop=h.stop_loop, stop_crash_watch=h.stop_crash_watch,
        start_qa_loop=h.start_qa_loop, stop_qa_loop=h.stop_qa_loop, start_real=h.start_real,
        start_crash_watch=h.start_crash_watch, crash_dialog_up=lambda: False,
        reload_timeout=2.0, poll_interval=0.01, instant_turn_wait=1.0, **kw,
    )


def test_kind_instant_runs_instant_cases_only_and_starts_no_turn_loop(tmp_path: Path):
    real_toml, turn_root = _real(tmp_path)
    h = _Harness(turn_root)
    results, report = _run(tmp_path, real_toml, h, suite="all", kind="instant")

    assert [(r.name, r.outcome) for r in results] == [
        ("smoke_turn", "skipped"), ("smoke_instant", "pass"),
        ("covert_turn", "skipped"), ("covert_instant", "pass"),
        ("navy_turn", "skipped"),
    ]
    assert not any(e.startswith(("start_qa_loop", "advance")) for e in h.events), h.events
    assert not any("teleport" in c for c in h.lua_calls)  # no turn case's setup ran
    text = report.read_text()
    assert text.count(SKIPPED_TURN_CASE) == 3 and "| smoke_instant | pass |" in text
    # every control line of the run, the restore's load included, ran in the no-click run
    assert h.env_seen and set(h.env_seen) == {"1"}
    assert ENV_VAR not in os.environ  # put back after the run
    assert {"start_real:scratch", "start_crash_watch"} <= set(h.events)
    assert not (turn_root / "qa.lock").exists() and not (turn_root / "paused.txt").exists()
    # smoke's instant cases passed: recorded, as an instant run's (live 10-31 12:36 --no-smoke found none)
    assert json.loads((turn_root / "qa.last_smoke").read_text())["kind"] == "instant"


def test_kind_instant_skips_a_phase2_case_with_its_reason():
    from parley.qa.cases import Case, Expect, Suite
    from parley.qa.runner import SKIPPED_PHASE2, _instant_only

    e = [Expect(log="x")]
    s = Suite(name="d", faction="england", cases=[
        Case(name="now", kind="instant", expect=e),
        Case(name="later", kind="instant", expect=e, phase2="no AI offer in a held turn"),
        Case(name="turn", expect=e),
    ])
    kept, skipped = _instant_only([s])
    assert [c.name for c in kept[0].cases] == ["now"]
    assert skipped["d"] == [("later", SKIPPED_PHASE2 + "no AI offer in a held turn"),
                            ("turn", SKIPPED_TURN_CASE)]
    with pytest.raises(ValueError, match="phase2"):
        Case(name="t", expect=e, phase2="why")  # a turn case is phase 2 already


def test_kind_all_still_runs_turn_cases_with_the_loop(tmp_path: Path):
    real_toml, turn_root = _real(tmp_path)
    h = _Harness(turn_root)
    results, _ = _run(tmp_path, real_toml, h)
    assert [r.outcome for r in results] == ["pass", "pass", "pass", "pass"]
    assert any(e.startswith("start_qa_loop") for e in h.events)
    assert set(h.env_seen) == {None}


def test_a_crash_in_an_instant_run_is_relaunched_without_clicks(tmp_path: Path):
    # relaunch_game.sh makes no clicks since 10-31: the no-click run's restore relaunches the game
    real_toml, turn_root = _real(tmp_path)
    h = _Harness(turn_root, game_running=False)
    results, _ = _run(tmp_path, real_toml, h, kind="instant")
    assert "relaunch_game" in h.events
    assert not (turn_root / "qa.lock").exists()  # restored
    assert results[1].outcome == "fail"  # smoke_instant: game crashed


def test_unknown_kind_is_refused(tmp_path: Path):
    real_toml, turn_root = _real(tmp_path)
    with pytest.raises(QARunError, match="unknown run kind 'turns'"):
        _run(tmp_path, real_toml, _Harness(turn_root), kind="turns")


def test_cli_and_qa_sh_pass_kind(monkeypatch, tmp_path: Path, capsys):
    seen = {}

    def fake_run(suite, real, **kw):
        seen.update(kw, suite=suite)
        report = tmp_path / "r.md"
        report.write_text("# QA Report\n")
        from parley.qa.runner import CaseResult
        return [CaseResult(name="t", outcome="skipped", turns=0, evidence=SKIPPED_TURN_CASE)], report

    monkeypatch.setattr("parley.qa.__main__.run_suite", fake_run)
    assert qa_main(["run", "all", "--real", "g.toml", "--kind", "instant"]) == 0  # skipped is no failure
    assert seen["kind"] == "instant" and seen["suite"] == "all"
    text = (ROOT / "scripts" / "qa.sh").read_text()
    assert 'kind=*)' in text and '--kind "${1#kind=}"' in text


# --- smoke gates an instant run ------------------------------------------------------------------


def test_smokes_helpers_case_is_instant_and_passes_on_the_fake_game(game):  # noqa: F811
    rt, root = game
    text = (ROOT / "games" / "qa" / "smoke.toml").read_text(encoding="utf-8")
    smoke = Suite.model_validate(tomllib.loads(text.replace('"england"', '"venice"')))
    assert smoke.cases[0].name == "helpers" and smoke.cases[0].kind == "instant"
    ctrl = TickingControl(rt, root)
    res, _ = _run_instant_case(smoke.cases[0], "qa-smoke", "g1", "venice", root, ctrl, TURN,
                               poll_interval=0.0, turn_wait=1.0)
    assert res.outcome == "pass", (res.evidence, ctrl.lines)


# --- the bench save with no menu ----------------------------------------------------------------


def _bench_game(on_current: str):
    def lua(h: FakeHarness, line: str) -> str:
        h.env_seen.append(os.environ.get(ENV_VAR))
        if "M.qa.load(" in line:
            h.append_log(f"qa: load ok: {line}")
            h.append_log("bridge loaded campaign at turn 5")
            return "ok"
        if "M.qa.current()" in line:
            return on_current
        return "ok"
    return lua


def _no_menu(tmp_path: Path, current: str = "england 5", restored: list | None = None, **kw):
    real_toml, turn_root, mod_save_dir = _game(tmp_path, bench=False)
    src = tmp_path / "england_turn5.sav"
    src.write_bytes(b"an england save on turn 5")
    h = FakeHarness(turn_root)
    h.env_seen = []
    h.on_lua = _bench_game(current)
    restored = [] if restored is None else restored
    out = bench_save_record(
        real_toml, source=src, control_factory=h.control_factory,
        restore_fn=lambda p: restored.append((p, json.loads((turn_root / "qa.lock").read_text()))) or True,
        stop_loop=h.stop_loop, stop_crash_watch=h.stop_crash_watch, start_real=h.start_real,
        start_crash_watch=h.start_crash_watch, reload_timeout=2.0, turn_wait=0.0, poll_interval=0.01, **kw,
    )
    return out, real_toml, turn_root, mod_save_dir, h, restored


def test_record_from_a_save_needs_no_menu_and_no_start(tmp_path: Path):
    bench, real_toml, turn_root, mod_save_dir, h, restored = _no_menu(tmp_path)
    assert (bench.turn, bench.faction) == (5, "england")
    assert (mod_save_dir / "parley_bench.sav").read_bytes() == b"an england save on turn 5"
    record = json.loads((mod_save_dir / "parley_bench.json").read_text())
    assert record["sha256"] == hashlib.sha256(b"an england save on turn 5").hexdigest()
    assert record["source"] == "england_turn5.sav" and "no-menu" in record["made"]
    assert load_bench_save(__import__("parley.config", fromlist=["x"]).load_config(real_toml)).turn == 5
    # parked like `start`, the bench loaded through EOP and asked whose turn it is, then restored
    assert h.events[:2] == ["stop_loop", "stop_crash_watch"]
    assert h.lua_calls == ['return M.qa.load("mods/parley/saves/parley_bench.sav")', "return M.qa.current()"]
    assert (turn_root / "bridge.txt").read_text() == "game_id=qa-bench-save\n"
    assert (mod_save_dir / "parley_keep_scratch.sav").read_bytes() == b"real-save-turn-40"
    (path, lock), = restored
    assert path == real_toml and lock["purpose"] == "bench-save" and lock["bench_loaded"] is True
    assert set(h.env_seen) == {"1"} and ENV_VAR not in os.environ


@pytest.mark.parametrize("answer, why", [
    ("france 5", "on france's turn, not england's"),
    ("nil", "can't tell the game's turn"),
])
def test_record_from_a_save_of_the_wrong_moment_restores_and_refuses(tmp_path: Path, answer, why):
    restored: list = []
    with pytest.raises(QARunError, match=why):
        _no_menu(tmp_path, current=answer, restored=restored)
    mod_save_dir = tmp_path / "mods" / "parley" / "saves"
    assert not (mod_save_dir / "parley_bench.json").exists()  # never recorded
    # the restore ran on the way out, told the game had changed (the bench save was loaded)
    (_, lock), = restored
    assert lock["bench_loaded"] is True


def test_record_from_a_missing_save_parks_nothing(tmp_path: Path):
    real_toml, turn_root, _ = _game(tmp_path, bench=False)
    with pytest.raises(QARunError, match="no save at"):
        bench_save_record(real_toml, source=tmp_path / "nope.sav",
                          stop_loop=lambda: pytest.fail("parked"), stop_crash_watch=lambda: None,
                          start_real=lambda p: None, start_crash_watch=lambda: None)
    assert not (turn_root / "qa.lock").exists()
