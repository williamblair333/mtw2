"""The QA bench's fixed start: the bench save every suite loads, its quiet world, and the recipe
that makes it (just qa-bench-save). The park/restore machinery itself is test_qa_runner.py's."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import time
from pathlib import Path

import pytest

from parley.config import load_config
from parley.orchestrator import Orchestrator
from parley.qa.__main__ import main as qa_main
from parley.qa.cases import Suite
from parley.qa.runner import (
    BENCH_RECIPE,
    QARunError,
    _run_changed_game,
    bench_save_record,
    bench_save_start,
    load_bench_save,
    newest_real_save,
    run_suite,
    write_qa_config,
)
from test_qa_runner import FakeHarness, _write_real_game, _write_state

BENCH_TURN = 10  # FakeHarness's default load logs "bridge reloaded at turn 10"


def _write_bench(mod_save_dir: Path, *, turn: int = BENCH_TURN, faction: str = "england",
                 data: bytes = b"bench-save-bytes", digest: str | None = None) -> Path:
    save = mod_save_dir / "parley_bench.sav"
    save.write_bytes(data)
    (mod_save_dir / "parley_bench.json").write_text(json.dumps({
        "save": save.name, "turn": turn, "faction": faction,
        "sha256": digest or hashlib.sha256(data).hexdigest(),
    }), encoding="utf-8")
    return save


def _game(tmp_path: Path, *, bench: bool = True):
    real_toml, turn_root, mod_save_dir = _write_real_game(tmp_path)
    (mod_save_dir / "Autosave.sav").write_bytes(b"real-save-turn-40")
    # the live campaign's report: far away from anything the bench save holds
    _write_state(turn_root, "scratch", 40, nearby_settlements=[
        {"id": "Antioch", "name": "Antioch", "faction": "slave", "x": 300, "y": 20, "distance": 2}])
    if bench:
        _write_bench(mod_save_dir)
    return real_toml, turn_root, mod_save_dir


def _suites(tmp_path: Path, extra: str = "") -> Path:
    d = tmp_path / "suites"
    d.mkdir()
    (d / "smoke.toml").write_text(
        'name = "smoke"\nfaction = "england"\n\n'
        '[[cases]]\nname = "spawn"\n'
        'setup = [\'M.qa.spawn_agent("england", "spy", 108, 153, "QA Spy")\']\n'
        'expect = [{ log = "qa: spawn_agent ok" }]\n',
        encoding="utf-8",
    )
    (d / "covert.toml").write_text(
        'name = "covert"\nfaction = "england"\n\n'
        '[[cases]]\nname = "near_town"\n'
        'setup = [\'M.qa.spawn_agent("england", "spy", $target_settlement_x, $target_settlement_y, "$target_settlement")\']\n'
        'expect = [{ log = "qa: spawn_agent ok" }]\n'
        + extra,
        encoding="utf-8",
    )
    return d


class BenchHarness(FakeHarness):
    """FakeHarness whose bridge writes the bench report (M.qa.report) into the published game's
    turn folder, and which notes bridge.txt whenever a case spawns."""

    def __init__(self, turn_root: Path):
        super().__init__(turn_root)
        self.bridge_at_spawn: list[str] = []
        self.bridge_at_load: list[str] = []
        self.on_lua = BenchHarness._lua

    def _lua(self, line: str) -> str:
        bridge = (self.turn_root / "bridge.txt").read_text(encoding="utf-8")
        if "M.qa.load(" in line:
            self.bridge_at_load.append(bridge)
            self.append_log(f"qa: load ok: {line}")
            turn = BENCH_TURN if "parley_bench" in line else 40  # the real campaign's turn
            self.append_log(f"bridge loaded campaign at turn {turn}")
            return "ok"
        if "M.qa.quiet(" in line:  # the quiet world: the Pope made young after every bench load
            self.append_log("qa: quiet ok: pope=Pope Gregory age=78->45")
            return "pope=Pope Gregory age=78->45"
        if "M.qa.report(" in line:
            game_id = next(ln.split("=", 1)[1] for ln in bridge.splitlines() if ln.startswith("game_id="))
            p = _write_state(self.turn_root, game_id, BENCH_TURN - 1, nearby_settlements=[
                {"id": "York", "name": "York", "faction": "slave", "x": 106, "y": 164, "distance": 3}])
            self.append_log(f"qa: report ok: {p}")
            return str(p)
        if "M.qa.spawn_agent(" in line:
            self.bridge_at_spawn.append(bridge)
            self.append_log("qa: spawn_agent ok: QA Agent")
            return "QA Agent"
        return "ok"


def _run(tmp_path: Path, real_toml: Path, h: FakeHarness, suite: str = "covert", **kw):
    return run_suite(
        suite, real_toml, bench_save=True,
        suites_dir=kw.pop("suites_dir", None) or _suites(tmp_path),
        report_dir=tmp_path / "runs" / "qa",
        control_factory=h.control_factory, advance_turn=h.advance_turn,
        is_game_running=h.is_game_running, relaunch_game=h.relaunch_game,
        stop_loop=h.stop_loop, stop_crash_watch=h.stop_crash_watch,
        start_qa_loop=h.start_qa_loop, stop_qa_loop=h.stop_qa_loop, start_real=h.start_real,
        start_crash_watch=h.start_crash_watch, crash_dialog_up=lambda: False,
        reload_timeout=2.0, poll_interval=0.01, **kw,
    )


# --- the bench save is the run's world ----------------------------------------------------------


def test_the_run_loads_the_bench_save_and_targets_come_from_its_report(tmp_path: Path):
    real_toml, turn_root, _ = _game(tmp_path)
    h = BenchHarness(turn_root)
    results, _ = _run(tmp_path, real_toml, h)

    assert [r.outcome for r in results] == ["pass", "pass"], results
    loads = [c for c in h.lua_calls if "M.qa.load(" in c]
    # the bench save first, again for covert (a new suite starts fresh: smoke's case changed the
    # world), the real campaign's kept save last (the restore, unchanged)
    assert loads == ['return M.qa.load("mods/parley/saves/parley_bench.sav")',
                     'return M.qa.load("mods/parley/saves/parley_bench.sav")',
                     'return M.qa.load("mods/parley/saves/parley_keep_scratch.sav")']
    assert h.lua_calls.index(loads[0]) < h.lua_calls.index(f'return M.qa.report("england", {BENCH_TURN - 1})')
    # York (the bench report's), never Antioch (the live campaign's)
    spawn = next(c for c in h.lua_calls if "York" in c or "Antioch" in c)
    assert '"York"' in spawn and "106, 164" in spawn
    assert {"start_real:scratch", "start_crash_watch"} <= set(h.events)
    assert not (turn_root / "qa.lock").exists()
    assert not (turn_root / "paused.txt").exists()


def test_cases_start_fresh_on_the_bench_save_unless_shared(tmp_path: Path):
    # live 10-31 phase 1: 30 cases' spawns piled up around London (no free tile beside it) and a
    # general one case withdrew into London led the next cases' garrison. A new suite and every
    # "fresh" case (the default) reload the bench save once a case ran; "shared" ones don't
    real_toml, turn_root, _ = _game(tmp_path)
    extra = (
        '\n[[cases]]\nname = "shared_one"\nisolation = "shared"\n'
        'setup = [\'M.qa.spawn_agent("england", "spy", 1, 2, "B")\']\n'
        'expect = [{ log = "qa: spawn_agent ok" }]\n'
        '\n[[cases]]\nname = "fresh_one"\n'
        'setup = [\'M.qa.spawn_agent("england", "spy", 1, 2, "C")\']\n'
        'expect = [{ log = "qa: spawn_agent ok" }]\n'
    )
    h = BenchHarness(turn_root)
    results, report = _run(tmp_path, real_toml, h, suites_dir=_suites(tmp_path, extra))
    assert [r.name for r in results] == ["spawn", "near_town", "shared_one", "fresh_one"]
    seq = [("load" if "parley_bench" in c else "keep" if "M.qa.load(" in c else "spawn")
           for c in h.lua_calls if "M.qa.load(" in c or "spawn_agent" in c]
    assert seq == ["load", "spawn", "load", "spawn", "spawn", "load", "spawn", "keep"]
    # no turn was played (each case passed on its setup): the bench report from the first load stands
    assert len([c for c in h.lua_calls if "M.qa.report(" in c]) == 1
    assert "Bench reloads (case isolation): 2" in report.read_text()
    assert not (turn_root / "paused.txt").exists()


def test_a_reload_after_played_turns_archives_their_folders_and_writes_the_bench_report_again(tmp_path: Path):
    # a turn case played turn 11; the next case's reload goes back to turn 10, whose folders must not
    # hold the undone turns' reports and orders, and whose targets come from the bench report again
    real_toml, turn_root, _ = _game(tmp_path)
    extra = (
        '\n[[cases]]\nname = "plays_a_turn"\nmax_turns = 1\n'
        'expect = [{ log = "playtest funds" }]\n'
        '[cases.orders]\n1 = [{ type = "set_tax", settlement = "York", level = "low" }]\n'
        '\n[[cases]]\nname = "after_it"\n'
        'setup = [\'M.qa.spawn_agent("england", "spy", $target_settlement_x, $target_settlement_y, "X")\']\n'
        'expect = [{ log = "qa: spawn_agent ok" }]\n'
    )
    h = BenchHarness(turn_root)
    results, _ = _run(tmp_path, real_toml, h, suites_dir=_suites(tmp_path, extra))
    assert [r.name for r in results][-2:] == ["plays_a_turn", "after_it"], results
    assert any(e.startswith("advance:qa-covert:") for e in h.events), h.events
    assert len([c for c in h.lua_calls if "M.qa.report(" in c]) == 2  # the first load's, the reload's
    archived = [p.name for p in (turn_root / "qa-archive").iterdir()]
    assert any(n.startswith("qa-covert-") for n in archived), archived
    assert not list((turn_root / "qa-covert").glob(f"turn-{BENCH_TURN + 1:04d}/*/state.json"))
    spawn = [c for c in h.lua_calls if '"X"' in c][-1]
    assert "106, 164" in spawn  # York, from the bench report written again


def test_a_failed_bench_reload_ends_the_run_and_restores(tmp_path: Path):
    real_toml, turn_root, _ = _game(tmp_path)
    h = BenchHarness(turn_root)
    loads = []

    def second_load_fails(self, line):
        if "parley_bench" in line:
            loads.append(line)
            if len(loads) == 2:
                return "loadGame failed (error)"
        return BenchHarness._lua(self, line)

    h.on_lua = second_load_fails
    results, _ = _run(tmp_path, real_toml, h)
    assert [(r.name, r.outcome) for r in results] == [("spawn", "pass"), ("near_town", "fail")]
    assert "the bench reload before the case failed" in results[-1].evidence
    assert h.lua_calls[-1] == 'return M.qa.load("mods/parley/saves/parley_keep_scratch.sav")'


def test_the_bench_loads_under_the_quiet_world(tmp_path: Path):
    real_toml, turn_root, _ = _game(tmp_path)
    h = BenchHarness(turn_root)
    _run(tmp_path, real_toml, h)
    bench_cfg = h.bridge_at_load[0].splitlines()
    assert "game_id=qa-covert" in bench_cfg and "freeze=*" in bench_cfg
    assert not any(ln.startswith("thaw=") for ln in bench_cfg)


def test_a_case_that_needs_a_faction_thaws_it_and_the_next_case_freezes_it_again(tmp_path: Path):
    real_toml, turn_root, _ = _game(tmp_path)
    extra = (
        '\n[[cases]]\nname = "france_acts"\nneeds = ["france"]\n'
        'setup = [\'M.qa.spawn_agent("england", "spy", 1, 2, "B")\']\n'
        'expect = [{ log = "qa: spawn_agent ok" }]\n'
        '\n[[cases]]\nname = "quiet_again"\n'
        'setup = [\'M.qa.spawn_agent("england", "spy", 1, 2, "C")\']\n'
        'expect = [{ log = "qa: spawn_agent ok" }]\n'
    )
    h = BenchHarness(turn_root)
    results, _ = _run(tmp_path, real_toml, h, suites_dir=_suites(tmp_path, extra))
    assert [r.name for r in results] == ["spawn", "near_town", "france_acts", "quiet_again"]
    thaws = [[ln for ln in b.splitlines() if ln.startswith(("freeze=", "thaw="))] for b in h.bridge_at_spawn]
    assert thaws == [["freeze=*"], ["freeze=*"], ["freeze=*", "thaw=france"], ["freeze=*"]]
    # the QA loop restarts on the case's toml, so it says the same as bridge.txt
    toml = load_config(tmp_path / "games" / "local" / "qa-covert.toml")
    assert toml.freeze_others and toml.thaw == []


def test_a_bench_load_whose_pope_stays_old_aborts_the_run_and_restores(tmp_path: Path):
    # games/interrupts.toml papal_election: no case runs on a world that may elect a Pope
    real_toml, turn_root, _ = _game(tmp_path)
    h = BenchHarness(turn_root)

    def old_pope(self, line):
        if "M.qa.quiet(" in line:
            return "the Pope's age stayed 78 after setting 45 (error)"
        return BenchHarness._lua(self, line)

    h.on_lua = old_pope
    with pytest.raises(QARunError, match="quiet-world step failed"):
        _run(tmp_path, real_toml, h)
    assert not any("spawn_agent" in c for c in h.lua_calls)
    assert h.lua_calls[-1] == 'return M.qa.load("mods/parley/saves/parley_keep_scratch.sav")'
    assert not (turn_root / "qa.lock").exists()


def test_every_bench_load_is_followed_by_the_quiet_step(tmp_path: Path):
    real_toml, turn_root, _ = _game(tmp_path)
    h = BenchHarness(turn_root)
    _run(tmp_path, real_toml, h)
    calls = h.lua_calls
    bench_loads = [i for i, c in enumerate(calls) if "M.qa.load(" in c and "parley_bench" in c]
    assert bench_loads
    for i in bench_loads:
        assert calls[i + 1] == "return M.qa.quiet()"


def test_a_bridge_without_the_report_helper_aborts_the_run_and_restores(tmp_path: Path):
    real_toml, turn_root, _ = _game(tmp_path)
    h = BenchHarness(turn_root)

    def no_report(self, line):
        if "M.qa.report(" in line:
            return "attempt to call field 'report' (a nil value) (error)"
        return BenchHarness._lua(self, line)

    h.on_lua = no_report
    with pytest.raises(QARunError, match="wrote no england report"):
        _run(tmp_path, real_toml, h)
    assert not any("spawn_agent" in c for c in h.lua_calls)  # no case ran on the live world
    assert h.lua_calls[-1] == 'return M.qa.load("mods/parley/saves/parley_keep_scratch.sav")'
    assert not (turn_root / "qa.lock").exists()


def test_the_lock_names_the_bench_save_and_a_failed_restore_knows_the_game_changed(tmp_path: Path):
    real_toml, turn_root, _ = _game(tmp_path)
    h = BenchHarness(turn_root)
    seen = {}

    def peek(self, line):
        if "M.qa.spawn_agent(" in line and "lock" not in seen:
            seen["lock"] = json.loads((turn_root / "qa.lock").read_text(encoding="utf-8"))
        return BenchHarness._lua(self, line)

    h.on_lua = peek
    _run(tmp_path, real_toml, h)
    lock = seen["lock"]
    assert lock["bench_save"] == "mods/parley/saves/parley_bench.sav" and lock["bench_loaded"] is True
    assert lock["kept_save"].endswith("parley_keep_scratch.sav")
    # a lock with no helper line after its offset still counts as changed: the bench save loaded
    assert "bench save" in _run_changed_game({**lock, "log_offset": 10**9}, turn_root / "parley_bridge.log")


# --- refusals -----------------------------------------------------------------------------------


def test_refuses_without_a_bench_save_and_names_the_recipe(tmp_path: Path):
    real_toml, turn_root, _ = _game(tmp_path, bench=False)
    h = BenchHarness(turn_root)
    with pytest.raises(QARunError, match=f"no bench save at .*parley_bench.sav; make it with `{BENCH_RECIPE} start`"):
        _run(tmp_path, real_toml, h)
    assert h.events == []  # nothing parked
    assert not (turn_root / "qa.lock").exists()


@pytest.mark.parametrize("bad, why", [
    ({"digest": "0" * 64}, "changed since it was recorded"),
    ({"turn": 0}, "turn 1 or later"),
])
def test_refuses_a_bench_save_that_changed_or_is_on_turn_0(tmp_path: Path, bad, why):
    real_toml, turn_root, mod_save_dir = _game(tmp_path, bench=False)
    _write_bench(mod_save_dir, **bad)
    h = BenchHarness(turn_root)
    with pytest.raises(QARunError, match=why):
        _run(tmp_path, real_toml, h)
    assert h.events == []


def test_refuses_a_bench_save_with_no_record(tmp_path: Path):
    real_toml, turn_root, mod_save_dir = _game(tmp_path, bench=False)
    (mod_save_dir / "parley_bench.sav").write_bytes(b"x")
    with pytest.raises(QARunError, match="no valid record"):
        load_bench_save(load_config(real_toml))


def test_refuses_suites_of_another_faction(tmp_path: Path):
    real_toml, turn_root, mod_save_dir = _game(tmp_path, bench=False)
    _write_bench(mod_save_dir, faction="france")
    h = BenchHarness(turn_root)
    with pytest.raises(QARunError, match="bench save plays france, but suite"):
        _run(tmp_path, real_toml, h)
    assert h.events == []


def test_the_bench_save_is_never_taken_for_the_real_campaigns_newest_save(tmp_path: Path):
    _, _, mod_save_dir = _game(tmp_path)
    real = mod_save_dir / "Autosave.sav"
    os.utime(real, (time.time() - 60, time.time() - 60))
    assert newest_real_save(mod_save_dir) == real


# --- the quiet world in the configs -------------------------------------------------------------


def test_write_qa_config_quiet_publishes_freeze_star_and_thaws(tmp_path: Path):
    real_toml, turn_root, _ = _game(tmp_path)
    suite = Suite(name="covert", faction="england", cases=[])
    out = write_qa_config(real_toml, suite, tmp_path / "plan.json", out_path=tmp_path / "qa.toml",
                          quiet=True, thaw=["france", "england", "france"])
    cfg = load_config(out)
    assert cfg.freeze_others and cfg.thaw == ["france"]  # the bench faction is the player anyway
    Orchestrator(cfg, {}).publish_bridge_config()
    lines = (turn_root / "bridge.txt").read_text().splitlines()
    assert {"freeze=*", "thaw=france"} <= set(lines) and "thaw=england" not in lines
    # a real game's config publishes no freeze=*
    Orchestrator(load_config(real_toml), {}).publish_bridge_config()
    assert "freeze=*" not in (turn_root / "bridge.txt").read_text()


# --- making the bench save (just qa-bench-save) -------------------------------------------------


class _Ctrl:
    def __init__(self, answer: str):
        self.answer, self.lines = answer, []

    def run_lua(self, line: str) -> str:
        self.lines.append(line)
        return self.answer


def _start(tmp_path: Path):
    real_toml, turn_root, mod_save_dir = _game(tmp_path, bench=False)
    events: list[str] = []
    msg = bench_save_start(
        real_toml,
        stop_loop=lambda: events.append("stop_loop"),
        stop_crash_watch=lambda: events.append("stop_crash_watch"),
        start_real=lambda p: events.append("start_real"),
        start_crash_watch=lambda: events.append("start_crash_watch"),
        now_fn=lambda: dt.datetime.fromtimestamp(time.time() - 30),
    )
    return real_toml, turn_root, mod_save_dir, events, msg


def test_bench_save_start_parks_the_real_run_and_leaves_the_new_campaign_alone(tmp_path: Path):
    real_toml, turn_root, mod_save_dir, events, msg = _start(tmp_path)
    assert events == ["stop_loop", "stop_crash_watch"]
    assert (mod_save_dir / "parley_keep_scratch.sav").read_bytes() == b"real-save-turn-40"
    lock = json.loads((turn_root / "qa.lock").read_text())
    assert lock["purpose"] == "bench-save" and lock["turn"] == 40
    # no seats, no autoplay: the bridge neither ends the new campaign's turns nor applies old orders
    assert (turn_root / "bridge.txt").read_text() == "game_id=qa-bench-save\n"
    assert f"{BENCH_RECIPE} record" in msg and "England" in msg


def test_bench_save_start_refuses_under_a_qa_lock(tmp_path: Path):
    real_toml, turn_root, _ = _game(tmp_path, bench=False)
    (turn_root / "qa.lock").write_text("{}")
    with pytest.raises(QARunError, match="lock file already exists"):
        bench_save_start(real_toml, stop_loop=lambda: None, stop_crash_watch=lambda: None,
                         start_real=lambda p: None, start_crash_watch=lambda: None)


def test_bench_save_record_keeps_the_new_campaigns_autosave_and_restores(tmp_path: Path):
    real_toml, turn_root, mod_save_dir, _, _ = _start(tmp_path)
    (mod_save_dir / "Autosave.sav").write_bytes(b"new-england-campaign-turn-1")  # written after start
    ctrl, restored = _Ctrl("england 1"), []
    bench = bench_save_record(real_toml, control_factory=lambda root: ctrl,
                              restore_fn=lambda p: restored.append(p) or True)
    assert ctrl.lines == ["return M.qa.current()"]
    assert (mod_save_dir / "parley_bench.sav").read_bytes() == b"new-england-campaign-turn-1"
    record = json.loads((mod_save_dir / "parley_bench.json").read_text())
    assert record["turn"] == 1 and record["faction"] == "england" and record["source"] == "Autosave.sav"
    assert record["sha256"] == hashlib.sha256(b"new-england-campaign-turn-1").hexdigest()
    assert (bench.turn, bench.rel) == (1, "mods/parley/saves/parley_bench.sav")
    assert restored == [real_toml]
    # the keep save is still the real campaign's, for the restore
    assert (mod_save_dir / "parley_keep_scratch.sav").read_bytes() == b"real-save-turn-40"


@pytest.mark.parametrize("answer, why", [
    ("france 1", "france's turn, not england's"),
    ("england 0", "end the first turn"),
    ("nil", "can't tell the game's turn"),
])
def test_bench_save_record_refuses_the_wrong_moment(tmp_path: Path, answer, why):
    real_toml, turn_root, mod_save_dir, _, _ = _start(tmp_path)
    (mod_save_dir / "Autosave.sav").write_bytes(b"new")
    with pytest.raises(QARunError, match=why):
        bench_save_record(real_toml, control_factory=lambda root: _Ctrl(answer),
                          restore_fn=lambda p: pytest.fail("no restore on a refusal"))
    assert not (mod_save_dir / "parley_bench.sav").exists()


def test_bench_save_record_refuses_when_the_game_saved_nothing_since_start(tmp_path: Path):
    real_toml, turn_root, mod_save_dir, _, _ = _start(tmp_path)
    old = time.time() - 3600
    os.utime(mod_save_dir / "Autosave.sav", (old, old))
    with pytest.raises(QARunError, match="wrote no save on the new campaign"):
        bench_save_record(real_toml, control_factory=lambda root: _Ctrl("england 2"),
                          restore_fn=lambda p: True)


def test_bench_save_record_needs_start_first(tmp_path: Path):
    real_toml, turn_root, _ = _game(tmp_path, bench=False)
    with pytest.raises(QARunError, match=f"run `{BENCH_RECIPE} start` first"):
        bench_save_record(real_toml, control_factory=lambda root: _Ctrl("england 1"))
    (turn_root / "qa.lock").write_text(json.dumps({"game_id": "scratch"}))
    with pytest.raises(QARunError, match="a QA run's lock"):
        bench_save_record(real_toml, control_factory=lambda root: _Ctrl("england 1"))


def test_cli_bench_save_steps(monkeypatch, tmp_path: Path, capsys):
    calls = []
    monkeypatch.setattr("parley.qa.__main__.bench_save_start", lambda real: calls.append(("start", real)) or "next")
    assert qa_main(["bench-save", "start", "--real", "g.toml"]) == 0
    monkeypatch.setattr("parley.qa.__main__.bench_save_record", lambda real, source, faction: (_ for _ in ()).throw(
        QARunError("no bench-save lock")))
    assert qa_main(["bench-save", "record", "--real", "g.toml", "--from", "x.sav"]) == 1
    assert calls == [("start", Path("g.toml"))]
    assert "no bench-save lock" in capsys.readouterr().err
