from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

from parley.qa.__main__ import main as qa_main
from parley.qa.cases import Case, Expect, Suite
from parley.qa.control import ControlTimeout
from parley.qa.runner import (
    REPO_ROOT,
    CaseResult,
    QARunError,
    _ProcessManager,
    _confirm_load,
    build_script_plan,
    ensure_keep_save,
    format_report,
    pick_hostile,
    pick_home,
    pick_targets,
    restore,
    run_suite,
    tile_binds,
    write_qa_config,
)


@pytest.fixture(autouse=True)
def _live_world_by_default(monkeypatch):
    """The tests here prove the park/run/restore machinery on the parked live campaign, as before
    the bench save; the bench save's own tests (test_qa_bench_save.py) pass bench_save=True."""
    monkeypatch.setitem(run_suite.__kwdefaults__, "bench_save", False)


def _write_real_game(tmp_path: Path, game_id: str = "scratch") -> tuple[Path, Path, Path]:
    turn_root = tmp_path / "parley_turns"
    save_dir = tmp_path / "saves"
    mod_save_dir = tmp_path / "mods" / "parley" / "saves"
    games_dir = tmp_path / "games" / "local"
    turn_root.mkdir(parents=True, exist_ok=True)
    save_dir.mkdir(parents=True, exist_ok=True)
    mod_save_dir.mkdir(parents=True, exist_ok=True)
    games_dir.mkdir(parents=True, exist_ok=True)

    real_toml = games_dir / f"{game_id}.toml"
    real_toml.write_text(
        f'game_id = "{game_id}"\n'
        f'turn_root = "{turn_root}"\n'
        f'save_dir = "{save_dir}"\n\n'
        f"[autoplay]\nwait = 60\n\n"
        f"[seats.england]\n"
        f'brain = "fake"\n'
        f'persona = "King William"\n',
        encoding="utf-8",
    )
    return real_toml, turn_root, mod_save_dir


def _write_state(turn_root: Path, game_id: str, turn: int, faction: str = "england", **extra) -> Path:
    d = turn_root / game_id / f"turn-{turn:04d}" / faction
    d.mkdir(parents=True, exist_ok=True)
    if not game_id.startswith("qa-"):
        (turn_root / "heartbeat.txt").write_text(f"turn={turn}\n", encoding="utf-8")
    state = {
        "protocol": 1,
        "game_id": game_id,
        "turn": turn,
        "year": 1080 + turn,
        "faction": faction,
        "treasury": 5000,
        "income": 500,
        "settlements": [{"id": "London", "name": "London", "region": "London_Province", "x": 112, "y": 149}],
        "armies": [],
        "factions": [],
        "visible_enemies": [
            {"id": "Morgunn Erskyn", "leader": "Morgunn Erskyn", "x": 106, "y": 156, "faction": "scotland", "distance": 4},
        ],
        "last_results": [],
        "agents": [],
        "seen_agents": [
            {"id": "Gilles de Laval", "kind": "spy", "x": 114, "y": 140, "faction": "france", "distance": 6},
        ],
        "nearby_settlements": [
            {"id": "York", "name": "York", "faction": "slave", "x": 106, "y": 164, "distance": 3},
            {"id": "Rennes", "name": "Rennes", "faction": "slave", "x": 101, "y": 136, "distance": 7},
        ],
        "agent_results": [],
        **extra,
    }
    state_path = d / "state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    return state_path


class FakeHarness:
    def __init__(self, turn_root: Path, *, game_running: bool = True):
        self.turn_root = turn_root
        self.log_path = turn_root / "parley_bridge.log"
        self.game_running = game_running
        self.events: list[str] = []
        self.lua_calls: list[str] = []
        self.on_lua = None
        self.on_advance = None
        self.turn = 10

    def append_log(self, line: str) -> None:
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(f"2026-10-30 15:45:00 {line}\n")

    def log_offset(self) -> int:
        try:
            return self.log_path.stat().st_size
        except FileNotFoundError:
            return 0

    def run_lua(self, line: str) -> str:
        self.lua_calls.append(line)
        self.events.append(f"lua:{line}")
        if self.on_lua is not None:
            return self.on_lua(self, line)
        if "M.qa.load(" in line:
            self.append_log("qa: load ok: mods/parley/saves/parley_keep.sav")
            self.append_log("bridge reloaded at turn 10")
            return "mods/parley/saves/parley_keep.sav"
        if "M.qa.spawn_agent(" in line:
            self.append_log("qa: spawn_agent ok: QA Agent")
            return "QA Agent"
        if "M.qa.teleport(" in line:
            self.append_log("qa: teleport ok: 110,154")
            return "110,154"
        if "M.qa.where(" in line:
            self.append_log("qa: where ok: 110,154")
            return "110,154"
        if "M.qa.skill(" in line:
            self.append_log("qa: skill ok: QA Spy GoodSpy=5")
            return "QA Spy GoodSpy=5"
        return "ok"

    def control_factory(self, root: Path):
        assert Path(root) == self.turn_root
        return self

    def advance_turn(self, game_id: str, faction: str, current_turn: int) -> int:
        self.turn = current_turn + 1
        self.events.append(f"advance:{game_id}:{self.turn}")
        if self.on_advance is not None:
            self.on_advance(self, game_id, faction, self.turn)
        else:
            self.append_log(f"playtest funds: {faction} topped up 500 -> 50000")
            _write_state(self.turn_root, game_id, self.turn, faction)
        return self.turn

    def is_game_running(self) -> bool:
        self.events.append(f"pgrep:{self.game_running}")
        return self.game_running

    def relaunch_game(self) -> None:
        self.events.append("relaunch_game")
        self.game_running = True
        # relaunch_game.sh continues the newest save; the bridge logs the map load
        self.append_log(f"bridge loaded campaign at turn {self.turn}")

    def stop_loop(self) -> None:
        self.events.append("stop_loop")

    def stop_crash_watch(self) -> None:
        self.events.append("stop_crash_watch")

    def start_qa_loop(self, qa_toml: Path) -> None:
        self.events.append(f"start_qa_loop:{qa_toml.name}")

    def stop_qa_loop(self) -> None:
        self.events.append("stop_qa_loop")

    def start_real(self, real_toml: Path) -> None:
        self.events.append(f"start_real:{real_toml.stem}")

    def start_crash_watch(self) -> None:
        self.events.append("start_crash_watch")


def test_refuses_with_stale_keep_copy(tmp_path: Path):
    real_toml, turn_root, save_dir = _write_real_game(tmp_path)
    keep_file = save_dir / "parley_keep_scratch.sav"
    keep_file.write_bytes(b"old-save-turn-9")
    newest_save = save_dir / "Autosave.sav"
    newest_save.write_bytes(b"new-save-turn-10")
    _write_state(turn_root, "scratch", 10)
    hb_path = turn_root / "heartbeat.txt"
    hb_mtime = hb_path.stat().st_mtime
    os.utime(newest_save, (hb_mtime - 125, hb_mtime - 125))

    harness = FakeHarness(turn_root)
    with pytest.raises(QARunError, match="wait for one real turn, then retry"):
        run_suite(
            "smoke",
            real_toml,
            control_factory=harness.control_factory,
            advance_turn=harness.advance_turn,
            is_game_running=harness.is_game_running,
            relaunch_game=harness.relaunch_game,
            stop_loop=harness.stop_loop,
            stop_crash_watch=harness.stop_crash_watch,
            start_qa_loop=harness.start_qa_loop,
            start_real=harness.start_real,
            start_crash_watch=harness.start_crash_watch,
        )

    assert not (turn_root / "qa.lock").exists()
    assert keep_file.read_bytes() == b"old-save-turn-9"
    assert harness.events == []


def test_refuses_when_lock_exists(tmp_path: Path):
    real_toml, turn_root, save_dir = _write_real_game(tmp_path)
    (save_dir / "Autosave.sav").write_bytes(b"save-turn-10")
    lock_path = turn_root / "qa.lock"
    lock_content = json.dumps({"game_id": "scratch", "kept_save": str(save_dir / "parley_keep_scratch.sav")})
    lock_path.write_text(lock_content, encoding="utf-8")

    harness = FakeHarness(turn_root)
    with pytest.raises(QARunError, match="lock"):
        run_suite(
            "smoke",
            real_toml,
            control_factory=harness.control_factory,
            advance_turn=harness.advance_turn,
            is_game_running=harness.is_game_running,
            relaunch_game=harness.relaunch_game,
            stop_loop=harness.stop_loop,
            stop_crash_watch=harness.stop_crash_watch,
            start_qa_loop=harness.start_qa_loop,
            start_real=harness.start_real,
            start_crash_watch=harness.start_crash_watch,
        )

    assert lock_path.exists()
    assert lock_path.read_text(encoding="utf-8") == lock_content
    assert harness.events == []


def test_failed_smoke_aborts_and_restores(tmp_path: Path):
    real_toml, turn_root, save_dir = _write_real_game(tmp_path)
    (save_dir / "Autosave.sav").write_bytes(b"save-turn-10")
    _write_state(turn_root, "scratch", 10)

    suites_dir = tmp_path / "suites"
    suites_dir.mkdir()
    (suites_dir / "smoke.toml").write_text(
        'name = "smoke"\nfaction = "england"\n\n'
        '[[cases]]\nname = "spawn_agent"\n'
        'setup = [\'M.qa.spawn_agent("england", "spy", 108, 153, "QA Spy")\']\n'
        'expect = [{ log = "qa: spawn_agent ok: QA Spy" }]\n',
        encoding="utf-8",
    )
    (suites_dir / "covert.toml").write_text(
        'name = "covert"\nfaction = "england"\n\n'
        '[[cases]]\nname = "spy_report_closed"\n'
        'setup = [\'M.qa.spawn_agent("england", "spy", $target_x, $target_y, "Covert Spy")\']\n'
        'expect = [{ log = "closed the spy report" }]\n',
        encoding="utf-8",
    )

    harness = FakeHarness(turn_root)

    def fail_spawn(h: FakeHarness, line: str) -> str:
        if "spawn_agent" in line:
            h.append_log("qa: spawn_agent failed: createCharacter returned nil")
            return "nil"
        if "M.qa.load(" in line:
            h.append_log("qa: load ok: mods/parley/saves/parley_keep_scratch.sav")
            h.append_log("bridge reloaded at turn 10")
            return "mods/parley/saves/parley_keep_scratch.sav"
        return "ok"

    harness.on_lua = fail_spawn

    results, report_path = run_suite(
        "covert",
        real_toml,
        suites_dir=suites_dir,
        report_dir=tmp_path / "runs" / "qa",
        control_factory=harness.control_factory,
        advance_turn=harness.advance_turn,
        is_game_running=harness.is_game_running,
        relaunch_game=harness.relaunch_game,
        stop_loop=harness.stop_loop,
        stop_crash_watch=harness.stop_crash_watch,
        start_qa_loop=harness.start_qa_loop,
        start_real=harness.start_real,
        start_crash_watch=harness.start_crash_watch,
    )

    assert len(results) == 1
    assert results[0].name == "spawn_agent"
    assert results[0].outcome == "fail"
    assert "spawn_agent failed" in results[0].evidence
    # Covert suite must not have run after smoke failed
    assert not any("Covert Spy" in c for c in harness.lua_calls)
    # Restore must have run and cleaned up qa.lock
    assert any('M.qa.load("mods/parley/saves/parley_keep_scratch.sav")' in c for c in harness.lua_calls)
    assert "start_real:scratch" in harness.events
    assert "start_crash_watch" in harness.events
    assert not (turn_root / "qa.lock").exists()


def test_exception_mid_run_restores(tmp_path: Path):
    real_toml, turn_root, save_dir = _write_real_game(tmp_path)
    (save_dir / "Autosave.sav").write_bytes(b"save-turn-10")
    _write_state(turn_root, "scratch", 10)

    suites_dir = tmp_path / "suites"
    suites_dir.mkdir()
    (suites_dir / "smoke.toml").write_text(
        'name = "smoke"\nfaction = "england"\n\n'
        '[[cases]]\nname = "teleport"\n'
        'setup = [\'M.qa.teleport("QA Spy", 110, 154)\']\n'
        'expect = [{ log = "qa: teleport ok: 110,154" }]\n',
        encoding="utf-8",
    )

    harness = FakeHarness(turn_root)

    def timeout_on_teleport(h: FakeHarness, line: str) -> str:
        if "teleport" in line:
            # Lock must exist while mid-run
            assert (turn_root / "qa.lock").exists()
            h.game_running = False
            raise ControlTimeout("timed out waiting for bridge")
        if "M.qa.load(" in line:
            h.append_log("qa: load ok: mods/parley/saves/parley_keep_scratch.sav")
            h.append_log("bridge reloaded at turn 10")
            return "mods/parley/saves/parley_keep_scratch.sav"
        return "ok"

    harness.on_lua = timeout_on_teleport

    # the game died mid-case: the case fails with the crash as evidence and the run restores
    results, _ = run_suite(
            "smoke",
            real_toml,
            suites_dir=suites_dir,
            report_dir=tmp_path / "runs" / "qa",
            control_factory=harness.control_factory,
            advance_turn=harness.advance_turn,
            is_game_running=harness.is_game_running,
            relaunch_game=harness.relaunch_game,
            stop_loop=harness.stop_loop,
            stop_crash_watch=harness.stop_crash_watch,
            start_qa_loop=harness.start_qa_loop,
            start_real=harness.start_real,
            start_crash_watch=harness.start_crash_watch,
        )

    assert [(r.name, r.outcome) for r in results] == [("teleport", "fail")]
    assert results[0].evidence.startswith("game crashed at ")
    assert "relaunch_game" in harness.events
    assert any('M.qa.load("mods/parley/saves/parley_keep_scratch.sav")' in c for c in harness.lua_calls)
    assert "start_real:scratch" in harness.events
    assert "start_crash_watch" in harness.events
    assert not (turn_root / "qa.lock").exists()


def test_restore_is_idempotent(tmp_path: Path, capsys):
    real_toml, turn_root, save_dir = _write_real_game(tmp_path)
    keep_path = save_dir / "parley_keep_scratch.sav"
    keep_path.write_bytes(b"kept-save-data")
    lock_path = turn_root / "qa.lock"
    lock_path.write_text(
        json.dumps({"game_id": "scratch", "kept_save": str(keep_path), "turn": 10}),
        encoding="utf-8",
    )

    harness = FakeHarness(turn_root)

    # First restore renames keep to .restored-<timestamp>.sav, removes lock, and restores
    restore(
        real_toml,
        control_factory=harness.control_factory,
        is_game_running=harness.is_game_running,
        relaunch_game=harness.relaunch_game,
        stop_loop=harness.stop_loop,
        start_real=harness.start_real,
        start_crash_watch=harness.start_crash_watch,
    )
    assert not lock_path.exists()
    assert not keep_path.exists()
    restored = list(save_dir.glob("parley_keep_scratch.restored-*.sav"))
    assert len(restored) == 1
    assert restored[0].read_bytes() == b"kept-save-data"

    # Second restore without lock prints "nothing to restore" and touches nothing
    events_before = list(harness.events)
    restore(
        real_toml,
        control_factory=harness.control_factory,
        is_game_running=harness.is_game_running,
        relaunch_game=harness.relaunch_game,
        stop_loop=harness.stop_loop,
        start_real=harness.start_real,
        start_crash_watch=harness.start_crash_watch,
    )
    out = capsys.readouterr().out
    assert "nothing to restore" in out
    assert not lock_path.exists()
    assert harness.events == events_before
    load_calls = [c for c in harness.lua_calls if 'M.qa.load("mods/parley/saves/parley_keep_scratch.sav")' in c]
    assert len(load_calls) == 1


def test_restore_relaunches_when_game_not_running(tmp_path: Path):
    real_toml, turn_root, save_dir = _write_real_game(tmp_path)
    keep_path = save_dir / "parley_keep_scratch.sav"
    keep_path.write_bytes(b"kept-save-data")
    (turn_root / "qa.lock").write_text(json.dumps({"game_id": "scratch", "turn": 10}), encoding="utf-8")

    harness = FakeHarness(turn_root, game_running=False)

    restore(
        real_toml,
        control_factory=harness.control_factory,
        is_game_running=harness.is_game_running,
        relaunch_game=harness.relaunch_game,
        stop_loop=harness.stop_loop,
        start_real=harness.start_real,
        start_crash_watch=harness.start_crash_watch,
    )

    relaunch_idx = harness.events.index("relaunch_game")
    load_idx = next(i for i, e in enumerate(harness.events) if e.startswith("lua:") and "M.qa.load(" in e)
    start_real_idx = harness.events.index("start_real:scratch")
    assert relaunch_idx < load_idx < start_real_idx
    assert not (turn_root / "qa.lock").exists()


def test_restore_puts_the_real_bridge_config_back_before_loading(tmp_path: Path):
    # live 10-30 18:38:30: the kept save loaded with the QA bench's bridge.txt still in place, so the
    # bridge applied qa-field's stale turn-31 orders to the real England and ended its turn 32 at
    # once (nobody pending under the QA config); its report went to the QA folder, and the real
    # ruler's turn-31 orders landed nowhere. The real loop wrote the real bridge.txt half a second late.
    real_toml, turn_root, save_dir = _write_real_game(tmp_path)
    (save_dir / "parley_keep_scratch.sav").write_bytes(b"kept")
    (turn_root / "qa.lock").write_text(json.dumps({"game_id": "scratch", "turn": 10}), encoding="utf-8")
    (turn_root / "bridge.txt").write_text("game_id=qa-field\nfaction=england\nautoplay=1\n", encoding="utf-8")
    harness = FakeHarness(turn_root)
    seen: list[str] = []

    def on_lua(h: FakeHarness, line: str) -> str:
        if "M.qa.load(" in line:
            seen.append((turn_root / "bridge.txt").read_text(encoding="utf-8"))
        return _default_lua(h, line)

    harness.on_lua = on_lua
    assert _restore_with(harness, real_toml) is True
    assert seen and seen[0].startswith("game_id=scratch\n")
    assert "game_id=qa-field" not in seen[0]


def test_restore_failed_load_on_a_changed_game_keeps_the_qa_bridge_config(tmp_path: Path):
    # the real loop stays stopped then: the bridge must not play the real seats on the QA campaign
    real_toml, turn_root, save_dir, keep, lock = _locked_game(tmp_path, ["qa: spawn_agent ok: Edwin"])
    qa_text = "game_id=qa-field\nfaction=england\nautoplay=1\n"
    (turn_root / "bridge.txt").write_text(qa_text, encoding="utf-8")
    harness = FakeHarness(turn_root)
    harness.on_lua = lambda h, line: "boom (error)"
    with pytest.raises(QARunError, match="phase load_failed"):
        _restore_with(harness, real_toml)
    assert (turn_root / "bridge.txt").read_text(encoding="utf-8") == qa_text


def test_report_table_has_every_case(tmp_path: Path):
    real_toml, turn_root, save_dir = _write_real_game(tmp_path)
    save_bytes = b"real-campaign-save-turn-10"
    (save_dir / "Autosave.sav").write_bytes(save_bytes)
    _write_state(turn_root, "scratch", 10)

    suites_dir = tmp_path / "suites"
    suites_dir.mkdir()
    (suites_dir / "smoke.toml").write_text(
        'name = "smoke"\nfaction = "england"\n\n'
        '[[cases]]\nname = "spawn_agent"\ntargets = { x = 108, y = 153 }\n'
        'setup = [\'M.qa.spawn_agent("england", "spy", $x, $y, "QA Spy")\']\n'
        'expect = [\n'
        '  { state = "agents[name=QA Spy].x", equals = "$x" },\n'
        '  { state = "agents[name=QA Spy].y", equals = "$y" },\n'
        ']\n\n'
        '[[cases]]\nname = "teleport"\ntargets = { x = 110, y = 154 }\n'
        'setup = [\'M.qa.teleport("QA Spy", $x, $y)\']\n'
        'expect = [{ log = "qa: teleport ok: $x,$y" }]\n',
        encoding="utf-8",
    )
    (suites_dir / "covert.toml").write_text(
        'name = "covert"\nfaction = "england"\n\n'
        '[[cases]]\nname = "spy_report_closed"\nchance = true\nmax_turns = 2\n'
        'targets = { target_x = 1, target_y = 1, target_settlement = "DefaultTown" }\n'
        'setup = [\'M.qa.spawn_agent("england", "spy", $target_x, $target_y, "QA Spy")\']\n'
        'expect = [\n'
        '  { order_ok = true },\n'
        '  { log = "popup enemy_settlement_info_scroll: closed the spy report after england\'s mission" },\n'
        ']\n'
        '[cases.orders]\n'
        '1 = [{ type = "spy", agent = "QA Spy", target = "$target_settlement" }]\n\n'
        '[[cases]]\nname = "assassinate"\n'
        'targets = { target_x = 1, target_y = 1, target_character = "DefaultChar" }\n'
        'setup = [\'M.qa.spawn_agent("england", "assassin", $target_x, $target_y, "QA Assassin")\']\n'
        'expect = [\n'
        '  { order_ok = true },\n'
        '  { log = "agent mission: england: .*assassination:" },\n'
        '  { state = "agent_results", equals = "assassination:" },\n'
        ']\n'
        '[cases.orders]\n'
        '1 = [{ type = "assassinate", agent = "QA Assassin", target = "$target_character" }]\n',
        encoding="utf-8",
    )

    harness = FakeHarness(turn_root)
    game = _Campaign(harness, _spy_then_assassin,
                     state_extra={"agents": [{"id": "QA Spy", "kind": "spy", "x": 108, "y": 153}]})

    report_dir = tmp_path / "runs" / "qa"
    results, report_path = run_suite(
        "covert",
        real_toml,
        suites_dir=suites_dir,
        report_dir=report_dir,
        control_factory=harness.control_factory,
        advance_turn=harness.advance_turn,
        is_game_running=harness.is_game_running,
        relaunch_game=harness.relaunch_game,
        stop_loop=harness.stop_loop,
        stop_crash_watch=harness.stop_crash_watch,
        start_qa_loop=harness.start_qa_loop,
        start_real=harness.start_real,
        start_crash_watch=harness.start_crash_watch,
    )

    assert [r.name for r in results] == ["spawn_agent", "teleport", "spy_report_closed", "assassinate"]
    assert all(r.outcome == "pass" for r in results)
    assert report_path.exists()
    text = report_path.read_text(encoding="utf-8")
    assert "| case | outcome | turns | evidence |" in text
    for case_name in ("spawn_agent", "teleport", "spy_report_closed", "assassinate"):
        assert f"| {case_name} | pass |" in text

    # Check kept save sha256 matched (renamed to .restored-<timestamp>.sav after restore)
    restored_saves = list(save_dir.glob("parley_keep_scratch.restored-*.sav"))
    assert len(restored_saves) == 1
    assert hashlib.sha256(restored_saves[0].read_bytes()).hexdigest() == hashlib.sha256(save_bytes).hexdigest()

    # Check generated qa-covert.toml and script plan JSON
    qa_toml = real_toml.parent / "qa-covert.toml"
    assert qa_toml.exists()
    qa_toml_text = qa_toml.read_text(encoding="utf-8")
    assert 'game_id = "qa-covert"' in qa_toml_text
    assert "playtest_funds = true" in qa_toml_text
    assert "script:" in qa_toml_text

    # Spy case ran after spawn_agent advanced turn 10 -> 11, so its relative turn 1 = absolute turn 12;
    # it is decided on turn 13's report, so the assassin's turn 1 is 14. Each plan holds one case.
    spy_plan, assassin_plan = game.plans[-2:]
    assert spy_plan == {"12": [{"type": "spy", "agent": "QA Spy", "target": "York"}]}
    assert assassin_plan == {"14": [{"type": "assassinate", "agent": "QA Assassin", "target": "Morgunn Erskyn"}]}
    plan_json = json.loads((real_toml.parent / "qa-covert-plan.json").read_text(encoding="utf-8"))
    assert plan_json == assassin_plan


def test_pick_targets_live_and_missing():
    state = {
        "nearby_settlements": [
            {"id": "Rennes", "name": "Rennes", "x": 101, "y": 136, "distance": 7},
            {"id": "York", "name": "York", "x": 106, "y": 164, "distance": 3},
        ],
        "visible_enemies": [
            {"id": "Prince Louis", "leader": "Prince Louis", "x": 120, "y": 130, "distance": 5},
        ],
        "seen_agents": [
            {"id": "Morgunn Erskyn", "kind": "spy", "x": 107, "y": 160, "distance": 2},
        ],
    }
    targets = pick_targets(state)
    assert targets["target_settlement"] == "York"
    assert (targets["target_x"], targets["target_y"]) != (106, 164)
    assert abs(int(targets["target_x"]) - 106) == 1
    assert abs(int(targets["target_y"]) - 164) == 1
    assert targets["target_character"] == "Morgunn Erskyn"

    assert pick_targets({}) == {}
    assert pick_targets({"nearby_settlements": [], "visible_enemies": [], "seen_agents": []}) == {}


def test_setup_failure_and_missing_targets_fail_case_not_crash(tmp_path: Path):
    real_toml, turn_root, save_dir = _write_real_game(tmp_path)
    (save_dir / "Autosave.sav").write_bytes(b"save-turn-10")
    # State with a settlement but NO visible_enemies or seen_agents
    _write_state(turn_root, "scratch", 10, visible_enemies=[], seen_agents=[])

    suites_dir = tmp_path / "suites"
    suites_dir.mkdir()
    (suites_dir / "smoke.toml").write_text(
        'name = "smoke"\nfaction = "england"\n\n'
        '[[cases]]\nname = "skill"\n'
        'setup = [\'M.qa.skill("QA Spy", "GoodSpy", 5)\']\n'
        'expect = [{ log = "qa: skill ok:" }]\n',
        encoding="utf-8",
    )
    (suites_dir / "covert.toml").write_text(
        'name = "covert"\nfaction = "england"\n\n'
        '[[cases]]\nname = "bad_setup"\n'
        'setup = [\'M.qa.teleport("Nobody", $target_x, $target_y)\']\n'
        'expect = [{ log = "qa: teleport ok:" }]\n\n'
        '[[cases]]\nname = "needs_char"\n'
        'targets = { target_character = "FallbackChar" }\n'
        'setup = [\'M.qa.spawn_agent("england", "assassin", $target_x, $target_y, "QA Assassin")\']\n'
        'expect = [{ log = "agent mission:" }]\n'
        '[cases.orders]\n'
        '1 = [{ type = "assassinate", agent = "QA Assassin", target = "$target_character" }]\n',
        encoding="utf-8",
    )

    harness = FakeHarness(turn_root)

    def custom_lua(h: FakeHarness, line: str) -> str:
        if 'teleport("Nobody"' in line:
            return "unknown character 'Nobody' (error)"
        if "M.qa.skill(" in line:
            h.append_log("qa: skill ok: QA Spy GoodSpy=5")
            return "QA Spy GoodSpy=5"
        if "M.qa.load(" in line:
            h.append_log("qa: load ok: mods/parley/saves/parley_keep_scratch.sav")
            h.append_log("bridge reloaded at turn 10")
            return "mods/parley/saves/parley_keep_scratch.sav"
        return "ok"

    harness.on_lua = custom_lua

    results, _ = run_suite(
        "covert",
        real_toml,
        suites_dir=suites_dir,
        report_dir=tmp_path / "runs" / "qa",
        control_factory=harness.control_factory,
        advance_turn=harness.advance_turn,
        is_game_running=harness.is_game_running,
        relaunch_game=harness.relaunch_game,
        stop_loop=harness.stop_loop,
        stop_crash_watch=harness.stop_crash_watch,
        start_qa_loop=harness.start_qa_loop,
        start_real=harness.start_real,
        start_crash_watch=harness.start_crash_watch,
    )

    by_name = {r.name: r for r in results}
    assert by_name["skill"].outcome == "pass"
    assert by_name["bad_setup"].outcome == "fail"
    assert "(error)" in by_name["bad_setup"].evidence
    assert by_name["needs_char"].outcome == "fail"
    assert "target_character" in by_name["needs_char"].evidence


def test_h1_keep_gate_order_validation_and_restart_on_refusal(tmp_path: Path):
    real_toml, turn_root, save_dir = _write_real_game(tmp_path)
    old_keep = save_dir / "parley_keep_scratch.sav"
    old_keep.write_bytes(b"good-old-keep")
    cand = save_dir / "Autosave.sav"
    cand.write_bytes(b"candidate-save")
    _write_state(turn_root, "scratch", 10)

    # 1. Unknown suite typo is validated before touching anything (no stop_loop, old keep untouched)
    harness = FakeHarness(turn_root)
    with pytest.raises(QARunError, match="unknown QA suite"):
        run_suite(
            "not_a_suite_typo",
            real_toml,
            control_factory=harness.control_factory,
            advance_turn=harness.advance_turn,
            is_game_running=harness.is_game_running,
            relaunch_game=harness.relaunch_game,
            stop_loop=harness.stop_loop,
            stop_crash_watch=harness.stop_crash_watch,
            start_qa_loop=harness.start_qa_loop,
            start_real=harness.start_real,
            start_crash_watch=harness.start_crash_watch,
        )
    assert harness.events == []
    assert old_keep.read_bytes() == b"good-old-keep"
    assert not (turn_root / "qa.lock").exists()

    # 2. Rejects QA-tainted save when any <turn_root>/qa-*/turn-* is newer than candidate save
    qa_turn_dir = turn_root / "qa-covert" / "turn-0011"
    qa_turn_dir.mkdir(parents=True)
    now_ts = cand.stat().st_mtime
    os.utime(cand, (now_ts, now_ts))
    os.utime(qa_turn_dir, (now_ts + 10, now_ts + 10))

    harness = FakeHarness(turn_root)
    with pytest.raises(QARunError, match="wait for one real turn, then retry"):
        run_suite(
            "smoke",
            real_toml,
            control_factory=harness.control_factory,
            advance_turn=harness.advance_turn,
            is_game_running=harness.is_game_running,
            relaunch_game=harness.relaunch_game,
            stop_loop=harness.stop_loop,
            stop_crash_watch=harness.stop_crash_watch,
            start_qa_loop=harness.start_qa_loop,
            start_real=harness.start_real,
            start_crash_watch=harness.start_crash_watch,
        )
    assert old_keep.read_bytes() == b"good-old-keep"
    assert harness.events == []
    assert not (turn_root / "qa.lock").exists()

    # 3. Rejects candidate save older than <turn_root>/heartbeat.txt by > 120s
    shutil.rmtree(turn_root / "qa-covert")
    hb_path = turn_root / "heartbeat.txt"
    os.utime(hb_path, (now_ts + 200, now_ts + 200))
    os.utime(cand, (now_ts + 79, now_ts + 79))  # 121s older than heartbeat.txt -> refuse

    harness = FakeHarness(turn_root)
    with pytest.raises(QARunError, match="wait for one real turn, then retry"):
        run_suite(
            "smoke",
            real_toml,
            control_factory=harness.control_factory,
            advance_turn=harness.advance_turn,
            is_game_running=harness.is_game_running,
            relaunch_game=harness.relaunch_game,
            stop_loop=harness.stop_loop,
            stop_crash_watch=harness.stop_crash_watch,
            start_qa_loop=harness.start_qa_loop,
            start_real=harness.start_real,
            start_crash_watch=harness.start_crash_watch,
        )
    assert old_keep.read_bytes() == b"good-old-keep"
    assert harness.events == []
    assert not (turn_root / "qa.lock").exists()


def test_h2_restore_no_lock_phases_and_rename_keep(tmp_path: Path, capsys):
    real_toml, turn_root, save_dir = _write_real_game(tmp_path)
    harness = FakeHarness(turn_root)

    # 1. No qa.lock -> prints "nothing to restore" and touches nothing
    restore(
        real_toml,
        control_factory=harness.control_factory,
        is_game_running=harness.is_game_running,
        relaunch_game=harness.relaunch_game,
        stop_loop=harness.stop_loop,
        start_real=harness.start_real,
        start_crash_watch=harness.start_crash_watch,
    )
    assert "nothing to restore" in capsys.readouterr().out
    assert harness.events == []
    assert harness.lua_calls == []

    # 2. Phases recorded in lock JSON and skipped on rerun
    keep_path = save_dir / "parley_keep_scratch.sav"
    keep_path.write_bytes(b"kept-save-data")
    lock_path = turn_root / "qa.lock"
    lock_path.write_text(
        json.dumps({"game_id": "scratch", "kept_save": str(keep_path), "turn": 10}),
        encoding="utf-8",
    )

    fail_real = True
    fail_cw = True

    def start_real_flaky(rt: Path) -> None:
        harness.events.append(f"start_real:{rt.stem}")
        if fail_real:
            raise subprocess.CalledProcessError(1, ["game.sh", "play", rt.stem])

    def start_cw_flaky() -> None:
        harness.events.append("start_crash_watch")
        if fail_cw:
            raise subprocess.CalledProcessError(1, ["just", "crash-watch"])

    # Run 1: loaded succeeds, real_started fails
    with pytest.raises(QARunError, match="restore failed at real_started; lock kept; run just qa-restore"):
        restore(
            real_toml,
            control_factory=harness.control_factory,
            is_game_running=harness.is_game_running,
            relaunch_game=harness.relaunch_game,
            stop_loop=harness.stop_loop,
            stop_crash_watch=harness.stop_crash_watch,
            start_real=start_real_flaky,
            start_crash_watch=start_cw_flaky,
        )
    assert lock_path.exists()
    lock_data = json.loads(lock_path.read_text(encoding="utf-8"))
    assert lock_data.get("loaded") is True
    assert not lock_data.get("real_started")
    assert keep_path.exists()

    # Run 2: loaded is skipped, real_started succeeds, cw_started fails
    fail_real = False
    with pytest.raises(QARunError, match="restore failed at cw_started; lock kept; run just qa-restore"):
        restore(
            real_toml,
            control_factory=harness.control_factory,
            is_game_running=harness.is_game_running,
            relaunch_game=harness.relaunch_game,
            stop_loop=harness.stop_loop,
            stop_crash_watch=harness.stop_crash_watch,
            start_real=start_real_flaky,
            start_crash_watch=start_cw_flaky,
        )
    assert len([c for c in harness.lua_calls if "M.qa.load(" in c]) == 1
    lock_data = json.loads(lock_path.read_text(encoding="utf-8"))
    assert lock_data.get("loaded") is True
    assert lock_data.get("real_started") is True
    assert not lock_data.get("cw_started")
    assert keep_path.exists()

    # Run 3: loaded and real_started skipped, cw_started succeeds -> renames keep and removes lock
    fail_cw = False
    restore(
        real_toml,
        control_factory=harness.control_factory,
        is_game_running=harness.is_game_running,
        relaunch_game=harness.relaunch_game,
        stop_loop=harness.stop_loop,
        stop_crash_watch=harness.stop_crash_watch,
        start_real=start_real_flaky,
        start_crash_watch=start_cw_flaky,
    )
    assert len([c for c in harness.lua_calls if "M.qa.load(" in c]) == 1
    assert harness.events.count("start_real:scratch") == 2  # 1 failed + 1 succeeded
    assert not lock_path.exists()
    assert not keep_path.exists()
    restored_files = list(save_dir.glob("parley_keep_scratch.restored-*.sav"))
    assert len(restored_files) == 1
    assert restored_files[0].read_bytes() == b"kept-save-data"


def test_h3_load_confirmation_and_save_dir_relative_to_game_dir(tmp_path: Path):
    # 1. save_dir not under game_dir -> refuse at start before touching anything
    game_dir = tmp_path / "game"
    turn_root = game_dir / "parley_turns"
    outside_saves = tmp_path / "outside_saves"
    games_dir = tmp_path / "games" / "local"
    turn_root.mkdir(parents=True)
    outside_saves.mkdir(parents=True)
    games_dir.mkdir(parents=True)
    (outside_saves / "Autosave.sav").write_bytes(b"save")
    _write_state(turn_root, "scratch", 10)
    bad_toml = games_dir / "scratch.toml"
    bad_toml.write_text(
        f'game_id = "scratch"\n'
        f'turn_root = "{turn_root}"\n'
        f'save_dir = "{outside_saves}"\n\n'
        f"[seats.england]\n"
        f'brain = "fake"\n'
        f'persona = "King"\n',
        encoding="utf-8",
    )
    harness = FakeHarness(turn_root)
    with pytest.raises(QARunError, match="save_dir"):
        run_suite(
            "smoke",
            bad_toml,
            control_factory=harness.control_factory,
            advance_turn=harness.advance_turn,
            is_game_running=harness.is_game_running,
            relaunch_game=harness.relaunch_game,
            stop_loop=harness.stop_loop,
            stop_crash_watch=harness.stop_crash_watch,
            start_qa_loop=harness.start_qa_loop,
            start_real=harness.start_real,
            start_crash_watch=harness.start_crash_watch,
        )
    assert harness.events == []

    # 2. mod_save_dir under game_dir (mods/parley/saves) derives relative loadGame path, and
    #    load confirmation rejects (error), qa: load failed:, heartbeats, reload before load ok, and wrong turn N
    mod_saves = game_dir / "mods" / "parley" / "saves"
    mod_saves.mkdir(parents=True)
    keep_path = mod_saves / "parley_keep_scratch.sav"
    keep_path.write_bytes(b"kept")
    good_toml = games_dir / "scratch.toml"
    good_toml.write_text(
        f'game_id = "scratch"\n'
        f'turn_root = "{turn_root}"\n'
        f'save_dir = "{game_dir / "saves"}"\n\n'
        f"[seats.england]\n"
        f'brain = "fake"\n'
        f'persona = "King"\n',
        encoding="utf-8",
    )
    lock_path = turn_root / "qa.lock"

    # 2a. run_lua returns " (error)" -> fail fast
    lock_path.write_text(json.dumps({"game_id": "scratch", "turn": 10}), encoding="utf-8")
    h1 = FakeHarness(turn_root)
    h1.on_lua = lambda h, line: "load error (error)"
    with pytest.raises(QARunError, match="restore failed at loaded"):
        restore(
            good_toml,
            control_factory=h1.control_factory,
            is_game_running=h1.is_game_running,
            relaunch_game=h1.relaunch_game,
            stop_loop=h1.stop_loop,
            stop_crash_watch=h1.stop_crash_watch,
            start_real=h1.start_real,
            start_crash_watch=h1.start_crash_watch,
            reload_timeout=0.05,
            poll_interval=0.01,
        )
    assert any('M.qa.load("mods/parley/saves/parley_keep_scratch.sav")' in c for c in h1.lua_calls)

    # 2b. qa: load failed: line -> fail fast
    lock_path.write_text(json.dumps({"game_id": "scratch", "turn": 10}), encoding="utf-8")
    h2 = FakeHarness(turn_root)

    def lua_load_failed(h: FakeHarness, line: str) -> str:
        h.append_log("qa: load failed: missing file")
        return "nil"

    h2.on_lua = lua_load_failed
    with pytest.raises(QARunError, match="restore failed at loaded; lock kept"):
        restore(
            good_toml,
            control_factory=h2.control_factory,
            is_game_running=h2.is_game_running,
            relaunch_game=h2.relaunch_game,
            stop_loop=h2.stop_loop,
            stop_crash_watch=h2.stop_crash_watch,
            start_real=h2.start_real,
            start_crash_watch=h2.start_crash_watch,
            reload_timeout=0.05,
            poll_interval=0.01,
        )

    # 2c. Reload BEFORE offset (before run_lua) + heartbeat lines AFTER qa: load ok: -> rejected (times out)
    keep_path.write_bytes(b"kept")
    lock_path.write_text(json.dumps({"game_id": "scratch", "turn": 10}), encoding="utf-8")
    h3 = FakeHarness(turn_root)
    h3.append_log("bridge reloaded at turn 10")

    def lua_heartbeats_only(h: FakeHarness, line: str) -> str:
        h.append_log("qa: load ok: mods/parley/saves/parley_keep_scratch.sav")
        h.append_log("autoplay: turn 10, waiting for england (60s of 300)")
        h.append_log("autoplay: ending turn 10")
        h.append_log("autoplay: auto-resolve all battles on")
        return "mods/parley/saves/parley_keep_scratch.sav"

    h3.on_lua = lua_heartbeats_only
    with pytest.raises(QARunError, match="restore failed at loaded"):
        restore(
            good_toml,
            control_factory=h3.control_factory,
            is_game_running=h3.is_game_running,
            relaunch_game=h3.relaunch_game,
            stop_loop=h3.stop_loop,
            stop_crash_watch=h3.stop_crash_watch,
            start_real=h3.start_real,
            start_crash_watch=h3.start_crash_watch,
            reload_timeout=0.05,
            poll_interval=0.01,
        )

    # 2d. Reload AFTER qa: load ok: but wrong turn N (11 != 10) -> rejected
    lock_path.write_text(json.dumps({"game_id": "scratch", "turn": 10}), encoding="utf-8")
    h4 = FakeHarness(turn_root)

    def lua_wrong_turn(h: FakeHarness, line: str) -> str:
        h.append_log("qa: load ok: mods/parley/saves/parley_keep_scratch.sav")
        h.append_log("bridge reloaded at turn 11")
        return "mods/parley/saves/parley_keep_scratch.sav"

    h4.on_lua = lua_wrong_turn
    with pytest.raises(QARunError, match="restore failed at loaded"):
        restore(
            good_toml,
            control_factory=h4.control_factory,
            is_game_running=h4.is_game_running,
            relaunch_game=h4.relaunch_game,
            stop_loop=h4.stop_loop,
            stop_crash_watch=h4.stop_crash_watch,
            start_real=h4.start_real,
            start_crash_watch=h4.start_crash_watch,
            reload_timeout=0.05,
            poll_interval=0.01,
        )


def test_m1_qa_sh_requires_real_when_loop_stopped_and_prints_resolved_game(tmp_path: Path):
    repo_qa_sh = Path(__file__).resolve().parents[1] / "scripts" / "qa.sh"
    script_text = repo_qa_sh.read_text(encoding="utf-8")
    assert "TURN_ROOT" not in script_text
    assert "SAVE_DIR" not in script_text
    assert "parley_keep_" not in script_text
    assert "scratch.toml" not in script_text

    # Test isolated copy in tmp_path with stubbed game.sh and uv
    fake_repo = tmp_path / "repo"
    (fake_repo / "scripts").mkdir(parents=True)
    (fake_repo / "games" / "local").mkdir(parents=True)
    (fake_repo / "games" / "local" / "scratch.toml").write_text('game_id = "scratch"\n', encoding="utf-8")
    shutil.copy2(repo_qa_sh, fake_repo / "scripts" / "qa.sh")
    shutil.copy2(repo_qa_sh.parent / "desktop_env.sh", fake_repo / "scripts" / "desktop_env.sh")
    (fake_repo / "scripts" / "game.sh").write_text(
        "#!/usr/bin/env bash\necho 'turn loop: not running'\necho 'bot: not running'\n",
        encoding="utf-8",
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv_stub = bin_dir / "uv"
    uv_stub.write_text("#!/usr/bin/env bash\necho \"UV_ARGS:$*\"\n", encoding="utf-8")
    uv_stub.chmod(0o755)

    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}"}
    env.pop("QA_REAL_GAME", None)

    # Without --real or QA_REAL_GAME when loop is not running -> fails (no scratch.toml fallback)
    res_fail = subprocess.run(
        ["bash", str(fake_repo / "scripts" / "qa.sh"), "run", "smoke"],
        cwd=str(fake_repo),
        env=env,
        capture_output=True,
        text=True,
    )
    assert res_fail.returncode != 0

    # With QA_REAL_GAME=scratch -> prints resolved game and runs uv
    env_with_var = {**env, "QA_REAL_GAME": "scratch"}
    res_ok = subprocess.run(
        ["bash", str(fake_repo / "scripts" / "qa.sh"), "run", "smoke"],
        cwd=str(fake_repo),
        env=env_with_var,
        capture_output=True,
        text=True,
    )
    assert res_ok.returncode == 0
    assert "games/local/scratch.toml" in res_ok.stdout
    assert "UV_ARGS:run python -m parley.qa run smoke --real games/local/scratch.toml" in res_ok.stdout


def test_m2_stop_crash_watch_exact_argv_and_verify_gone(tmp_path: Path):
    proc_root = tmp_path / "proc"
    (proc_root / "101").mkdir(parents=True)
    (proc_root / "101" / "cmdline").write_bytes(b"bash\x00scripts/crash_watch.sh\x00")
    (proc_root / "102").mkdir(parents=True)
    (proc_root / "102" / "cmdline").write_bytes(b"bash\x00-c\x00echo scripts/crash_watch.sh\x00")

    killed: list[tuple[int, int]] = []

    def fake_kill_removes(pid: int, sig: int) -> None:
        killed.append((pid, sig))
        shutil.rmtree(proc_root / str(pid), ignore_errors=True)

    runs: list[list[str]] = []

    def fake_run(argv, **kwargs):
        runs.append(list(argv))
        return subprocess.CompletedProcess(argv, 0)

    pm = _ProcessManager(proc_root=proc_root, kill_fn=fake_kill_removes, run_fn=fake_run)
    pm.stop_crash_watch()
    assert killed == [(101, signal.SIGTERM)]
    assert (proc_root / "102").exists()

    # If process refuses to exit, stop_crash_watch raises QARunError when verifying it's gone
    (proc_root / "103").mkdir(parents=True)
    (proc_root / "103" / "cmdline").write_bytes(b"bash\x00scripts/crash_watch.sh\x00")
    pm_stuck = _ProcessManager(
        proc_root=proc_root, kill_fn=lambda pid, sig: None, wait_timeout=0.05, run_fn=fake_run,
    )
    with pytest.raises(QARunError, match="crash-watch"):
        pm_stuck.stop_crash_watch()


def test_crash_watch_stop_and_start_go_through_the_user_unit_recipes(tmp_path: Path):
    # live 10-30 20:20: a crash-watch started from inside a background job died with that job;
    # the recipes run it as the user unit parley-crash-watch, which no process tree owns
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    runs: list[tuple[list[str], dict]] = []

    def fake_run(argv, **kwargs):
        runs.append((list(argv), kwargs))
        return subprocess.CompletedProcess(argv, 0)

    pm = _ProcessManager(proc_root=proc_root, kill_fn=lambda pid, sig: None, run_fn=fake_run)
    pm.stop_crash_watch()
    pm.start_crash_watch()
    assert [argv for argv, _ in runs] == [["just", "crash-watch-stop"], ["just", "crash-watch"]]
    stop_kw, start_kw = runs[0][1], runs[1][1]
    assert stop_kw["cwd"] == str(REPO_ROOT) and start_kw["cwd"] == str(REPO_ROOT)
    assert start_kw["check"] is True
    # a failed unit stop (no user bus, say) still falls through to the legacy argv sweep
    assert stop_kw["check"] is False


def test_tests_never_reach_the_machines_crash_watch():
    # restore()/run_suite() tests that don't inject stop_crash_watch get a default _ProcessManager:
    # it swept the real /proc and killed a live `bash scripts/crash_watch.sh` from any checkout
    pm = _ProcessManager()
    assert pm.proc_root != Path("/proc")
    assert pm.run_fn is not subprocess.run


def test_crash_watch_stop_sweeps_a_legacy_watch_after_the_unit_stop(tmp_path: Path):
    proc_root = tmp_path / "proc"
    (proc_root / "101").mkdir(parents=True)
    (proc_root / "101" / "cmdline").write_bytes(b"bash\x00scripts/crash_watch.sh\x00")
    events: list[str] = []

    def fake_run(argv, **kwargs):
        events.append(" ".join(argv))
        return subprocess.CompletedProcess(argv, 1)  # the unit stop failed

    def fake_kill(pid: int, sig: int) -> None:
        events.append(f"kill {pid}")
        shutil.rmtree(proc_root / str(pid), ignore_errors=True)

    pm = _ProcessManager(proc_root=proc_root, kill_fn=fake_kill, run_fn=fake_run)
    pm.stop_crash_watch()
    assert events == ["just crash-watch-stop", "kill 101"]


def test_m3_restore_stops_crash_watch_and_orphaned_qa_loop(tmp_path: Path):
    real_toml, turn_root, save_dir = _write_real_game(tmp_path)
    keep_path = save_dir / "parley_keep_scratch.sav"
    keep_path.write_bytes(b"kept")
    (turn_root / "qa.lock").write_text(json.dumps({"game_id": "scratch", "turn": 10}), encoding="utf-8")

    proc_root = tmp_path / "proc"
    (proc_root / "201").mkdir(parents=True)
    (proc_root / "201" / "cmdline").write_bytes(
        b"python3\x00-m\x00parley\x00run\x00games/local/qa-covert.toml\x00"
    )
    (proc_root / "202").mkdir(parents=True)
    (proc_root / "202" / "cmdline").write_bytes(
        b"python3\x00-m\x00parley\x00run\x00games/local/scratch.toml\x00"
    )

    killed: list[tuple[int, int]] = []

    def fake_kill(pid: int, sig: int) -> None:
        killed.append((pid, sig))
        shutil.rmtree(proc_root / str(pid), ignore_errors=True)

    harness = FakeHarness(turn_root)
    restore(
        real_toml,
        control_factory=harness.control_factory,
        is_game_running=harness.is_game_running,
        relaunch_game=harness.relaunch_game,
        stop_loop=harness.stop_loop,
        stop_crash_watch=harness.stop_crash_watch,
        start_real=harness.start_real,
        start_crash_watch=harness.start_crash_watch,
        proc_root=proc_root,
        kill_fn=fake_kill,
    )
    assert [pid for pid, _ in killed] == [201]
    assert (proc_root / "202").exists()
    stop_cw_idx = len(harness.events) - 1 - harness.events[::-1].index("stop_crash_watch")
    start_cw_idx = harness.events.index("start_crash_watch")
    assert stop_cw_idx < start_cw_idx


def test_m4_main_prints_report_path_even_when_restore_fails(tmp_path: Path, monkeypatch, capsys):
    real_toml, turn_root, save_dir = _write_real_game(tmp_path)
    (save_dir / "Autosave.sav").write_bytes(b"save-turn-10")
    _write_state(turn_root, "scratch", 10)

    suites_dir = tmp_path / "suites"
    suites_dir.mkdir()
    (suites_dir / "smoke.toml").write_text(
        'name = "smoke"\nfaction = "england"\n\n'
        '[[cases]]\nname = "skill"\n'
        'setup = [\'M.qa.skill("QA Spy", "GoodSpy", 5)\']\n'
        'expect = [{ log = "qa: skill ok:" }]\n',
        encoding="utf-8",
    )
    report_dir = tmp_path / "runs" / "qa"
    harness = FakeHarness(turn_root)

    def fail_on_load(h: FakeHarness, line: str) -> str:
        if "M.qa.skill(" in line:
            h.append_log("qa: skill ok: QA Spy GoodSpy=5")
            return "QA Spy GoodSpy=5"
        if "M.qa.load(" in line:
            raise ControlTimeout("load timed out")
        return "ok"

    harness.on_lua = fail_on_load

    orig_run_suite = run_suite

    def patched_run_suite(suite_name: str, real_cfg_path: Path):
        return orig_run_suite(
            suite_name,
            real_cfg_path,
            suites_dir=suites_dir,
            report_dir=report_dir,
            control_factory=harness.control_factory,
            advance_turn=harness.advance_turn,
            is_game_running=harness.is_game_running,
            relaunch_game=harness.relaunch_game,
            stop_loop=harness.stop_loop,
            stop_crash_watch=harness.stop_crash_watch,
            start_qa_loop=harness.start_qa_loop,
            start_real=harness.start_real,
            start_crash_watch=harness.start_crash_watch,
            hang_seconds=0.2,  # the timed-out load is checked for a hang: keep that wait short
        )

    monkeypatch.setattr("parley.qa.__main__.run_suite", patched_run_suite)
    rc = qa_main(["run", "smoke", "--real", str(real_toml)])
    captured = capsys.readouterr()
    assert rc == 1
    assert "wrote " in captured.out
    assert ".md" in captured.out
    assert "restore failed at loaded; lock kept; run just qa-restore" in captured.err
    assert (turn_root / "qa.lock").exists()


def test_m5_setup_control_timeout_fails_case_and_continues_unless_game_gone(tmp_path: Path):
    real_toml, turn_root, save_dir = _write_real_game(tmp_path)
    (save_dir / "Autosave.sav").write_bytes(b"save-turn-10")
    _write_state(turn_root, "scratch", 10)

    suites_dir = tmp_path / "suites"
    suites_dir.mkdir()
    (suites_dir / "smoke.toml").write_text(
        'name = "smoke"\nfaction = "england"\n\n'
        '[[cases]]\nname = "skill"\n'
        'setup = [\'M.qa.skill("QA Spy", "GoodSpy", 5)\']\n'
        'expect = [{ log = "qa: skill ok:" }]\n',
        encoding="utf-8",
    )
    (suites_dir / "covert.toml").write_text(
        'name = "covert"\nfaction = "england"\n\n'
        '[[cases]]\nname = "timeout_case"\n'
        'setup = [\'M.qa.teleport("HungChar", 110, 154)\']\n'
        'expect = [{ log = "qa: teleport ok:" }]\n\n'
        '[[cases]]\nname = "after_timeout"\n'
        'setup = [\'M.qa.where("QA Spy")\']\n'
        'expect = [{ log = "qa: where ok:" }]\n',
        encoding="utf-8",
    )

    harness = FakeHarness(turn_root)

    def lua_timeout_but_alive(h: FakeHarness, line: str) -> str:
        if "HungChar" in line:
            raise ControlTimeout("timed out after 30.0s waiting for HungChar")
        if "M.qa.skill(" in line:
            h.append_log("qa: skill ok: QA Spy GoodSpy=5")
            return "QA Spy GoodSpy=5"
        if "M.qa.where(" in line:
            h.append_log("qa: where ok: 110,154")
            return "110,154"
        if "M.qa.load(" in line:
            h.append_log("qa: load ok: mods/parley/saves/parley_keep_scratch.sav")
            h.append_log("bridge reloaded at turn 10")
            return "mods/parley/saves/parley_keep_scratch.sav"
        return "ok"

    harness.on_lua = lua_timeout_but_alive

    results, _ = run_suite(
        "covert",
        real_toml,
        suites_dir=suites_dir,
        report_dir=tmp_path / "runs" / "qa",
        control_factory=harness.control_factory,
        advance_turn=harness.advance_turn,
        is_game_running=harness.is_game_running,
        relaunch_game=harness.relaunch_game,
        stop_loop=harness.stop_loop,
        stop_crash_watch=harness.stop_crash_watch,
        start_qa_loop=harness.start_qa_loop,
        start_real=harness.start_real,
        start_crash_watch=harness.start_crash_watch,
    )
    by_name = {r.name: r for r in results}
    assert by_name["timeout_case"].outcome == "fail"
    assert "timed out after 30.0s waiting for HungChar" in by_name["timeout_case"].evidence
    assert by_name["after_timeout"].outcome == "pass"

    # When game process is gone on ControlTimeout in setup -> aborts immediately and restores
    shutil.rmtree(turn_root / "qa-covert", ignore_errors=True)
    fresh_save = save_dir / "Autosave.sav"
    fresh_save.write_bytes(b"save-turn-10-fresh")
    fresh_mtime = fresh_save.stat().st_mtime + 1.0
    os.utime(fresh_save, (fresh_mtime, fresh_mtime))
    harness2 = FakeHarness(turn_root)

    def lua_timeout_and_dead(h: FakeHarness, line: str) -> str:
        if "HungChar" in line:
            h.game_running = False
            raise ControlTimeout("timed out after 30.0s; game died")
        if "M.qa.skill(" in line:
            h.append_log("qa: skill ok: QA Spy GoodSpy=5")
            return "QA Spy GoodSpy=5"
        if "M.qa.load(" in line:
            h.append_log("qa: load ok: mods/parley/saves/parley_keep_scratch.sav")
            h.append_log("bridge reloaded at turn 10")
            return "mods/parley/saves/parley_keep_scratch.sav"
        return "ok"

    harness2.on_lua = lua_timeout_and_dead
    # the game is gone: the case fails with the crash as evidence, no later case runs, and the run
    # relaunches and restores
    results2, _ = run_suite(
            "covert",
            real_toml,
            suites_dir=suites_dir,
            report_dir=tmp_path / "runs" / "qa",
            control_factory=harness2.control_factory,
            advance_turn=harness2.advance_turn,
            is_game_running=harness2.is_game_running,
            relaunch_game=harness2.relaunch_game,
            stop_loop=harness2.stop_loop,
            stop_crash_watch=harness2.stop_crash_watch,
            start_qa_loop=harness2.start_qa_loop,
            start_real=harness2.start_real,
            start_crash_watch=harness2.start_crash_watch,
        )
    by_name2 = {r.name: r for r in results2}
    assert by_name2["timeout_case"].outcome == "fail"
    assert by_name2["timeout_case"].evidence.startswith("game crashed at ")
    assert "after_timeout" not in by_name2
    assert not any("M.qa.where(" in c for c in harness2.lua_calls)
    assert "relaunch_game" in harness2.events
    assert not (turn_root / "qa.lock").exists()


def test_r1_last_restore_marker_blocks_until_newer_autosave(tmp_path: Path):
    real_toml, turn_root, save_dir = _write_real_game(tmp_path)
    autosave = save_dir / "Autosave.sav"
    autosave.write_bytes(b"qa-tainted-autosave")
    _write_state(turn_root, "scratch", 10)
    hb_path = turn_root / "heartbeat.txt"
    base_mtime = hb_path.stat().st_mtime
    # Autosave is newer than heartbeat.txt and no qa-* turn dirs exist, so stale/qa-dir checks pass
    os.utime(autosave, (base_mtime + 10.0, base_mtime + 10.0))

    keep_path = save_dir / "parley_keep_scratch.sav"
    keep_path.write_bytes(b"kept-save-turn-10")
    (turn_root / "qa.lock").write_text(
        json.dumps({"game_id": "scratch", "kept_save": str(keep_path), "turn": 10}),
        encoding="utf-8",
    )

    harness = FakeHarness(turn_root)
    restore(
        real_toml,
        control_factory=harness.control_factory,
        is_game_running=harness.is_game_running,
        relaunch_game=harness.relaunch_game,
        stop_loop=harness.stop_loop,
        stop_crash_watch=harness.stop_crash_watch,
        start_real=harness.start_real,
        start_crash_watch=harness.start_crash_watch,
    )

    marker_path = turn_root / "qa.last_restore"
    assert marker_path.exists()
    marker_data = json.loads(marker_path.read_text(encoding="utf-8"))
    assert marker_data["newest_save_mtime"] == pytest.approx(autosave.stat().st_mtime)
    assert isinstance(marker_data["at"], str) and "T" in marker_data["at"]
    restored = save_dir / marker_data["restored_save"]
    assert restored.read_bytes() == b"kept-save-turn-10"

    # Same mtime, nothing played since the restore -> the save the restore loaded is kept as is
    assert ensure_keep_save(save_dir, "scratch", turn_root=turn_root).read_bytes() == b"kept-save-turn-10"

    # Same mtime after a turn started (heartbeat touched since the restore) -> refused
    later = marker_data["at_epoch"] + 60.0
    os.utime(hb_path, (later, later))
    with pytest.raises(QARunError, match="wait for one real turn to autosave, then retry"):
        ensure_keep_save(save_dir, "scratch", turn_root=turn_root)

    # Older mtime -> refused
    os.utime(autosave, (base_mtime + 5.0, base_mtime + 5.0))
    with pytest.raises(QARunError, match="wait for one real turn to autosave, then retry"):
        ensure_keep_save(save_dir, "scratch", turn_root=turn_root)

    # Strictly greater mtime -> accepted
    autosave.write_bytes(b"real-turn-11-autosave")
    os.utime(autosave, (base_mtime + 20.0, base_mtime + 20.0))
    kept = ensure_keep_save(save_dir, "scratch", turn_root=turn_root)
    assert kept.read_bytes() == b"real-turn-11-autosave"


def _paused_after_restore(tmp_path: Path, *, legacy: bool = False) -> tuple[Path, Path, Path, Path]:
    """Live 10-31 08:10: a restore loaded the keep (a copy of Autosave-2, mtime kept), then the
    real campaign was stopped on purpose: Autosave-2 stays the newest save, as old as the record.
    `legacy`: the qa.last_restore written before the loaded save was recorded."""
    import time as _time
    from parley.qa.runner import LAST_RESTORE_FILE
    real_toml, turn_root, save_dir = _write_real_game(tmp_path)
    _write_state(turn_root, "scratch", 50)
    hb = turn_root / "heartbeat.txt"
    t0 = _time.time() - 1000.0
    os.utime(hb, (t0, t0))
    autosave = save_dir / "Autosave-2.sav"
    autosave.write_bytes(b"real-turn-50")
    os.utime(autosave, (t0 + 200.0, t0 + 200.0))
    restored = save_dir / "parley_keep_scratch.restored-20261031-080035.sav"
    shutil.copy2(autosave, restored)
    at = t0 + 900.0
    record = {"newest_save_mtime": autosave.stat().st_mtime,
              "at": _dt.datetime.fromtimestamp(at).isoformat(timespec="seconds")}
    if not legacy:
        record.update({"at_epoch": at, "restored_save": restored.name,
                       "restored_sha256": hashlib.sha256(restored.read_bytes()).hexdigest(),
                       "restored_mtime": restored.stat().st_mtime})
    (turn_root / LAST_RESTORE_FILE).write_text(json.dumps(record), encoding="utf-8")
    return real_toml, turn_root, save_dir, restored


@pytest.mark.parametrize("legacy", [False, True])
def test_paused_campaign_reuses_the_save_the_last_restore_loaded(tmp_path: Path, legacy: bool, capsys):
    from parley.qa.runner import _preflight_keep_save
    _, turn_root, save_dir, restored = _paused_after_restore(tmp_path, legacy=legacy)
    assert _preflight_keep_save(save_dir, "scratch", turn_root=turn_root) == 50
    kept = ensure_keep_save(save_dir, "scratch", turn_root=turn_root)
    assert kept == save_dir / "parley_keep_scratch.sav"
    assert kept.read_bytes() == b"real-turn-50"
    assert kept.stat().st_mtime == restored.stat().st_mtime
    assert "real campaign hasn't moved since the last restore; keeping" in capsys.readouterr().out


def test_a_real_turn_since_the_restore_takes_the_new_autosave(tmp_path: Path):
    import time as _time
    _, turn_root, save_dir, _ = _paused_after_restore(tmp_path)
    now = _time.time()
    os.utime(turn_root / "heartbeat.txt", (now, now))
    fresh = save_dir / "Autosave-3.sav"
    fresh.write_bytes(b"real-turn-51")
    os.utime(fresh, (now + 1.0, now + 1.0))
    assert ensure_keep_save(save_dir, "scratch", turn_root=turn_root).read_bytes() == b"real-turn-51"


@pytest.mark.parametrize("change", ["keep_changed", "heartbeat_moved", "aborted_restore", "qa_dir_since"])
def test_reuse_refused_when_anything_does_not_match(tmp_path: Path, change: str):
    import time as _time
    from parley.qa.runner import LAST_RESTORE_FILE, _preflight_keep_save
    _, turn_root, save_dir, restored = _paused_after_restore(tmp_path)
    if change == "keep_changed":
        restored.write_bytes(b"something else")
    elif change == "heartbeat_moved":
        now = _time.time()
        os.utime(turn_root / "heartbeat.txt", (now, now))
    elif change == "aborted_restore":
        path = turn_root / LAST_RESTORE_FILE
        data = json.loads(path.read_text(encoding="utf-8"))
        data.update(restored_save=None)
        data.pop("restored_sha256")
        path.write_text(json.dumps(data), encoding="utf-8")
    else:
        (turn_root / "qa-smoke" / "turn-0001").mkdir(parents=True)
    with pytest.raises(QARunError, match="refusing QA-tainted save Autosave-2.sav"):
        _preflight_keep_save(save_dir, "scratch", turn_root=turn_root)
    with pytest.raises(QARunError, match="refusing QA-tainted save Autosave-2.sav"):
        ensure_keep_save(save_dir, "scratch", turn_root=turn_root)
    assert not (save_dir / "parley_keep_scratch.sav").exists()


def _park_for_running_test(tmp_path: Path, running: dict | None):
    """Park the real run with fakes; `running` is what the fake reader says runs (None: no reader)."""
    from parley.config import load_config
    from parley.qa.runner import _park_real
    real_toml, turn_root, save_dir = _write_real_game(tmp_path)
    _write_state(turn_root, "scratch", 10)
    hb_mtime = (turn_root / "heartbeat.txt").stat().st_mtime
    autosave = save_dir / "Autosave.sav"
    autosave.write_bytes(b"real-turn-10")
    os.utime(autosave, (hb_mtime + 5.0, hb_mtime + 5.0))
    harness = FakeHarness(turn_root)
    lock_path = turn_root / "qa.lock"
    _park_real(
        load_config(real_toml), real_toml, lock_path,
        stop_loop_fn=harness.stop_loop, stop_cw_fn=harness.stop_crash_watch,
        start_real_fn=harness.start_real, start_cw_fn=harness.start_crash_watch,
        now_fn=_dt.datetime.now,
        running_now_fn=(lambda: dict(running)) if running is not None else None,
        start_bot_fn=lambda p: harness.events.append(f"start_bot:{p.stem}"),
    )
    return real_toml, turn_root, lock_path


def _restore_with_fakes(real_toml: Path, turn_root: Path) -> FakeHarness:
    harness = FakeHarness(turn_root)
    restore(
        real_toml,
        control_factory=harness.control_factory,
        is_game_running=harness.is_game_running,
        relaunch_game=harness.relaunch_game,
        stop_loop=harness.stop_loop,
        stop_crash_watch=harness.stop_crash_watch,
        start_real=harness.start_real,
        start_crash_watch=harness.start_crash_watch,
        start_bot=lambda p: harness.events.append(f"start_bot:{p.stem}"),
    )
    return harness


_STARTS = ("start_real:scratch", "start_bot:scratch", "start_crash_watch")


@pytest.mark.parametrize(
    "running, started",
    [
        # live 10-31 08:05: run9 stopped on purpose; the restore must not start its loop again
        ({"loop": False, "bot": False, "crash_watch": False}, []),
        ({"loop": True, "bot": True, "crash_watch": True}, ["start_real:scratch", "start_crash_watch"]),
        ({"loop": False, "bot": False, "crash_watch": True}, ["start_crash_watch"]),
        ({"loop": True, "bot": True, "crash_watch": False}, ["start_real:scratch"]),
        ({"loop": False, "bot": True, "crash_watch": False}, ["start_bot:scratch"]),
        # nothing recorded (a lock from before the record): everything starts, as before
        (None, ["start_real:scratch", "start_crash_watch"]),
    ],
)
def test_restore_brings_back_what_ran_before_the_park(tmp_path: Path, running, started):
    from parley.qa.runner import RUNNING_BEFORE
    real_toml, turn_root, lock_path = _park_for_running_test(tmp_path, running)
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    assert lock.get(RUNNING_BEFORE) == running
    harness = _restore_with_fakes(real_toml, turn_root)
    assert [e for e in harness.events if e in _STARTS] == started
    assert "stop_crash_watch" in harness.events  # never two watches, whatever ran
    assert not lock_path.exists()


def test_an_old_lock_without_the_record_restores_everything(tmp_path: Path):
    real_toml, turn_root, save_dir = _write_real_game(tmp_path)
    _write_state(turn_root, "scratch", 10)
    (save_dir / "parley_keep_scratch.sav").write_bytes(b"kept-save-turn-10")
    (turn_root / "qa.lock").write_text(json.dumps({"game_id": "scratch", "turn": 10}), encoding="utf-8")
    harness = _restore_with_fakes(real_toml, turn_root)
    assert [e for e in harness.events if e in _STARTS] == ["start_real:scratch", "start_crash_watch"]


def test_a_failed_park_restarts_only_what_ran(tmp_path: Path):
    from parley.config import load_config
    from parley.qa.runner import _park_real
    real_toml, turn_root, save_dir = _write_real_game(tmp_path)  # no real save: the park fails
    harness = FakeHarness(turn_root)
    with pytest.raises(QARunError, match="no real save"):
        _park_real(
            load_config(real_toml), real_toml, turn_root / "qa.lock",
            stop_loop_fn=harness.stop_loop, stop_cw_fn=harness.stop_crash_watch,
            start_real_fn=harness.start_real, start_cw_fn=harness.start_crash_watch,
            now_fn=_dt.datetime.now,
            running_now_fn=lambda: {"loop": False, "bot": False, "crash_watch": True},
        )
    assert [e for e in harness.events if e in _STARTS] == ["start_crash_watch"]
    assert not (turn_root / "qa.lock").exists()


def test_process_manager_reads_what_runs_from_proc(tmp_path: Path):
    proc = tmp_path / "proc"

    def add(pid: int, *argv: str) -> None:
        (proc / str(pid)).mkdir(parents=True)
        (proc / str(pid) / "cmdline").write_bytes(b"\x00".join(a.encode() for a in argv) + b"\x00")

    add(101, "/repo/.venv/bin/python3", "-m", "parley", "run", "games/local/qa-smoke.toml")
    add(102, "uv", "run", "python", "-m", "parley", "discord", "games/local/scratch.toml")

    def no_unit(*a, **k):
        return subprocess.CompletedProcess(a, 3)

    pm = _ProcessManager(proc_root=proc, run_fn=no_unit)
    assert pm.running_now() == {"loop": False, "bot": False, "crash_watch": False}
    add(103, "/repo/.venv/bin/python3", "-m", "parley", "run", "games/local/scratch.toml")
    add(104, "/repo/.venv/bin/python", "-m", "parley", "discord", "games/local/scratch.toml")
    add(105, "bash", "scripts/crash_watch.sh")
    assert pm.running_now() == {"loop": True, "bot": True, "crash_watch": True}
    unit_up = _ProcessManager(proc_root=tmp_path / "none", run_fn=lambda *a, **k: subprocess.CompletedProcess(a, 0))
    assert unit_up.crash_watch_running()


def test_r2_confirm_load_order_and_turn_tolerance(tmp_path: Path):
    real_toml, turn_root, save_dir = _write_real_game(tmp_path)
    keep_path = save_dir / "parley_keep_scratch.sav"
    lock_path = turn_root / "qa.lock"

    # (a) bridge loaded campaign at turn N BEFORE qa: load ok (both after offset) + (b) N == lock_turn - 1 accepted
    keep_path.write_bytes(b"kept-save-turn-9")
    lock_path.write_text(json.dumps({"game_id": "scratch", "turn": 10}), encoding="utf-8")
    h1 = FakeHarness(turn_root)

    def lua_reload_before_ok_and_minus_one(h: FakeHarness, line: str) -> str:
        h.append_log("bridge loaded campaign at turn 9")
        h.append_log("qa: load ok: mods/parley/saves/parley_keep_scratch.sav")
        return "mods/parley/saves/parley_keep_scratch.sav"

    h1.on_lua = lua_reload_before_ok_and_minus_one
    assert restore(
        real_toml,
        control_factory=h1.control_factory,
        is_game_running=h1.is_game_running,
        relaunch_game=h1.relaunch_game,
        stop_loop=h1.stop_loop,
        stop_crash_watch=h1.stop_crash_watch,
        start_real=h1.start_real,
        start_crash_watch=h1.start_crash_watch,
        reload_timeout=0.05,
        poll_interval=0.01,
    )

    # (a) bridge loaded campaign at turn N after offset WITHOUT qa: load ok -> rejected
    log_path = turn_root / "parley_bridge.log"
    offset = log_path.stat().st_size if log_path.exists() else 0
    h1.append_log("bridge loaded campaign at turn 10")
    with pytest.raises(QARunError, match="timed out"):
        _confirm_load(
            "mods/parley/saves/parley_keep_scratch.sav",
            log_path,
            offset,
            expected_turn=10,
            timeout=0.05,
            poll_interval=0.01,
        )

    # (b) N == lock_turn - 2 (8 vs 10) raises QARunError naming both turns
    offset2 = log_path.stat().st_size
    h1.append_log("bridge loaded campaign at turn 8")
    h1.append_log("qa: load ok: mods/parley/saves/parley_keep_scratch.sav")
    with pytest.raises(QARunError) as exc_info:
        _confirm_load(
            "mods/parley/saves/parley_keep_scratch.sav",
            log_path,
            offset2,
            expected_turn=10,
            timeout=0.05,
            poll_interval=0.01,
        )
    assert "8" in str(exc_info.value)
    assert "10" in str(exc_info.value)


def test_r3_preflight_no_stop_and_post_stop_refusal_restart_and_interrupt(tmp_path: Path):
    real_toml, turn_root, save_dir = _write_real_game(tmp_path)
    old_keep = save_dir / "parley_keep_scratch.sav"
    old_keep.write_bytes(b"good-old-keep")
    _write_state(turn_root, "scratch", 10)
    hb_path = turn_root / "heartbeat.txt"
    base_ts = hb_path.stat().st_mtime

    # 1a. Missing save -> preflight refuses with no process touched
    harness = FakeHarness(turn_root)
    with pytest.raises(QARunError, match="no real save found"):
        run_suite(
            "smoke",
            real_toml,
            control_factory=harness.control_factory,
            advance_turn=harness.advance_turn,
            is_game_running=harness.is_game_running,
            relaunch_game=harness.relaunch_game,
            stop_loop=harness.stop_loop,
            stop_crash_watch=harness.stop_crash_watch,
            start_qa_loop=harness.start_qa_loop,
            start_real=harness.start_real,
            start_crash_watch=harness.start_crash_watch,
        )
    assert harness.events == []
    assert old_keep.read_bytes() == b"good-old-keep"

    # 1b. R1 marker qa.last_restore newer/equal to candidate save -> preflight refuses with no process touched
    cand = save_dir / "Autosave.sav"
    cand.write_bytes(b"cand-save")
    os.utime(cand, (base_ts + 10.0, base_ts + 10.0))
    (turn_root / "qa.last_restore").write_text(
        json.dumps({"newest_save_mtime": base_ts + 10.0, "at": "2026-10-30T16:00:00"}),
        encoding="utf-8",
    )
    with pytest.raises(QARunError, match="wait for one real turn to autosave, then retry"):
        run_suite(
            "smoke",
            real_toml,
            control_factory=harness.control_factory,
            advance_turn=harness.advance_turn,
            is_game_running=harness.is_game_running,
            relaunch_game=harness.relaunch_game,
            stop_loop=harness.stop_loop,
            stop_crash_watch=harness.stop_crash_watch,
            start_qa_loop=harness.start_qa_loop,
            start_real=harness.start_real,
            start_crash_watch=harness.start_crash_watch,
        )
    assert harness.events == []
    assert old_keep.read_bytes() == b"good-old-keep"
    (turn_root / "qa.last_restore").unlink()

    # 2. Post-stop refusal where start_real also fails -> error includes original refusal reason
    def stop_loop_taints_save() -> None:
        harness.events.append("stop_loop")
        os.utime(hb_path, (base_ts + 200.0, base_ts + 200.0))

    def start_real_boom(rt: Path) -> None:
        harness.events.append(f"start_real:{rt.stem}")
        raise RuntimeError("boom restarting real loop")

    with pytest.raises(QARunError) as exc_info:
        run_suite(
            "smoke",
            real_toml,
            control_factory=harness.control_factory,
            advance_turn=harness.advance_turn,
            is_game_running=harness.is_game_running,
            relaunch_game=harness.relaunch_game,
            stop_loop=stop_loop_taints_save,
            stop_crash_watch=harness.stop_crash_watch,
            start_qa_loop=harness.start_qa_loop,
            start_real=start_real_boom,
            start_crash_watch=harness.start_crash_watch,
        )
    msg = str(exc_info.value)
    assert "refusing stale save" in msg
    assert "boom restarting real loop" in msg
    assert harness.events[:2] == ["stop_loop", "stop_crash_watch"]
    assert "start_real:scratch" in harness.events
    assert not (turn_root / "qa.lock").exists()

    # 3. KeyboardInterrupt after stop_loop restarts real loop and crash-watch
    os.utime(hb_path, (base_ts, base_ts))
    os.utime(cand, (base_ts + 10.0, base_ts + 10.0))
    harness_ki = FakeHarness(turn_root)

    def stop_cw_interrupted() -> None:
        harness_ki.events.append("stop_crash_watch")
        raise KeyboardInterrupt("user hit ctrl-c")

    with pytest.raises(KeyboardInterrupt):
        run_suite(
            "smoke",
            real_toml,
            control_factory=harness_ki.control_factory,
            advance_turn=harness_ki.advance_turn,
            is_game_running=harness_ki.is_game_running,
            relaunch_game=harness_ki.relaunch_game,
            stop_loop=harness_ki.stop_loop,
            stop_crash_watch=stop_cw_interrupted,
            start_qa_loop=harness_ki.start_qa_loop,
            start_real=harness_ki.start_real,
            start_crash_watch=harness_ki.start_crash_watch,
        )
    assert "start_real:scratch" in harness_ki.events
    assert "start_crash_watch" in harness_ki.events
    assert not (turn_root / "qa.lock").exists()


def test_r4_restore_prunes_older_restored_saves(tmp_path: Path):
    import datetime as dt

    real_toml, turn_root, save_dir = _write_real_game(tmp_path)
    old1 = save_dir / "parley_keep_scratch.restored-20261029-100000.sav"
    old2 = save_dir / "parley_keep_scratch.restored-20261030-100000.sav"
    other = save_dir / "parley_keep_other.restored-20261029-100000.sav"
    old1.write_bytes(b"old-1")
    old2.write_bytes(b"old-2")
    other.write_bytes(b"other-game")

    keep_path = save_dir / "parley_keep_scratch.sav"
    keep_path.write_bytes(b"newest-kept-save")
    (turn_root / "qa.lock").write_text(
        json.dumps({"game_id": "scratch", "kept_save": str(keep_path), "turn": 10}),
        encoding="utf-8",
    )

    harness = FakeHarness(turn_root)
    restore(
        real_toml,
        control_factory=harness.control_factory,
        is_game_running=harness.is_game_running,
        relaunch_game=harness.relaunch_game,
        stop_loop=harness.stop_loop,
        stop_crash_watch=harness.stop_crash_watch,
        start_real=harness.start_real,
        start_crash_watch=harness.start_crash_watch,
        now_fn=lambda: dt.datetime(2026, 10, 30, 16, 30, 0),
    )

    remaining = list(save_dir.glob("parley_keep_scratch.restored-*.sav"))
    assert len(remaining) == 1
    assert remaining[0].name == "parley_keep_scratch.restored-20261030-163000.sav"
    assert remaining[0].read_bytes() == b"newest-kept-save"
    assert not old1.exists()
    assert not old2.exists()
    assert other.exists()


def test_mod_save_dir_ignores_manual_save_dir_and_picks_newest_rotating_autosave(tmp_path: Path):
    from parley.qa.runner import newest_real_save

    real_toml, turn_root, mod_save_dir = _write_real_game(tmp_path)
    manual_save_dir = tmp_path / "saves"
    (manual_save_dir / "eng.sav").write_bytes(b"stale-manual-save")
    os.utime(manual_save_dir / "eng.sav", (100.0, 100.0))

    a1 = mod_save_dir / "Autosave-1.sav"
    a2 = mod_save_dir / "Autosave-2.sav"
    a3 = mod_save_dir / "Autosave-3.sav"
    old_keep = mod_save_dir / "parley_keep_scratch.sav"
    a1.write_bytes(b"autosave-1")
    a2.write_bytes(b"autosave-2")
    a3.write_bytes(b"autosave-3-newest")
    old_keep.write_bytes(b"old-keep")

    _write_state(turn_root, "scratch", 16)
    hb_mtime = (turn_root / "heartbeat.txt").stat().st_mtime
    os.utime(a1, (hb_mtime - 300.0, hb_mtime - 300.0))
    os.utime(a2, (hb_mtime - 60.0, hb_mtime - 60.0))
    os.utime(a3, (hb_mtime - 30.0, hb_mtime - 30.0))
    os.utime(old_keep, (hb_mtime + 100.0, hb_mtime + 100.0))

    assert newest_real_save(mod_save_dir) == a3
    kept = ensure_keep_save(mod_save_dir, "scratch", turn_root=turn_root)
    assert kept == mod_save_dir / "parley_keep_scratch.sav"
    assert kept.read_bytes() == b"autosave-3-newest"
    assert list(manual_save_dir.glob("parley_keep_*")) == []


def test_heartbeat_turn_and_stale_window_ignores_precreated_and_stray_turn_folders(tmp_path: Path):
    real_toml, turn_root, mod_save_dir = _write_real_game(tmp_path)
    # Previous turn state exists (turn 15), turn 16..21 pre-created with no state.json,
    # and stray turn-0107..0112 folders left from previous campaign.
    _write_state(turn_root, "scratch", 15)
    for t in (*range(16, 22), *range(107, 113)):
        d = turn_root / "scratch" / f"turn-{t:04d}" / "england"
        d.mkdir(parents=True, exist_ok=True)

    hb_path = turn_root / "heartbeat.txt"
    hb_path.write_text("turn=16\r\n", encoding="utf-8")
    hb_mtime = hb_path.stat().st_mtime

    for t in range(107, 113):
        stray_dir = turn_root / "scratch" / f"turn-{t:04d}"
        os.utime(stray_dir, (hb_mtime + 50.0, hb_mtime + 50.0))

    autosave = mod_save_dir / "Autosave-3.sav"
    autosave.write_bytes(b"autosave-turn-16")
    # 60s older than heartbeat.txt (within 120s window, even though >5s older than turn-0112)
    os.utime(autosave, (hb_mtime - 60.0, hb_mtime - 60.0))

    suites_dir = tmp_path / "suites"
    suites_dir.mkdir()
    (suites_dir / "smoke.toml").write_text(
        'name = "smoke"\nfaction = "england"\n\n'
        '[[cases]]\nname = "skill"\n'
        'setup = [\'M.qa.skill("QA Spy", "GoodSpy", 5)\']\n'
        'expect = [{ log = "qa: skill ok:" }]\n',
        encoding="utf-8",
    )

    seen_lock_turn: list[int] = []
    harness = FakeHarness(turn_root)
    harness.turn = 16

    def on_lua(h: FakeHarness, line: str) -> str:
        if "M.qa.skill(" in line:
            lock_data = json.loads((turn_root / "qa.lock").read_text(encoding="utf-8"))
            seen_lock_turn.append(lock_data["turn"])
            h.append_log("qa: skill ok: QA Spy GoodSpy=5")
            return "QA Spy GoodSpy=5"
        if "M.qa.load(" in line:
            h.append_log("qa: load ok: mods/parley/saves/parley_keep_scratch.sav")
            h.append_log("bridge loaded campaign at turn 16")
            return "mods/parley/saves/parley_keep_scratch.sav"
        return "ok"

    harness.on_lua = on_lua

    results, _ = run_suite(
        "smoke",
        real_toml,
        suites_dir=suites_dir,
        report_dir=tmp_path / "runs" / "qa",
        control_factory=harness.control_factory,
        advance_turn=harness.advance_turn,
        is_game_running=harness.is_game_running,
        relaunch_game=harness.relaunch_game,
        stop_loop=harness.stop_loop,
        stop_crash_watch=harness.stop_crash_watch,
        start_qa_loop=harness.start_qa_loop,
        start_real=harness.start_real,
        start_crash_watch=harness.start_crash_watch,
    )
    assert len(results) == 1 and results[0].outcome == "pass"
    assert seen_lock_turn == [16]
    assert any('M.qa.load("mods/parley/saves/parley_keep_scratch.sav")' in c for c in harness.lua_calls)

    # Save older than heartbeat mtime - 120s is refused
    shutil.rmtree(turn_root / "qa-smoke", ignore_errors=True)
    (turn_root / "qa.last_restore").unlink(missing_ok=True)
    os.utime(autosave, (hb_mtime - 121.0, hb_mtime - 121.0))
    with pytest.raises(QARunError, match="refusing stale save Autosave-3.sav"):
        run_suite(
            "smoke",
            real_toml,
            suites_dir=suites_dir,
            report_dir=tmp_path / "runs" / "qa",
            control_factory=harness.control_factory,
            advance_turn=harness.advance_turn,
            is_game_running=harness.is_game_running,
            relaunch_game=harness.relaunch_game,
            stop_loop=harness.stop_loop,
            stop_crash_watch=harness.stop_crash_watch,
            start_qa_loop=harness.start_qa_loop,
            start_real=harness.start_real,
            start_crash_watch=harness.start_crash_watch,
        )


# --- setup binds (live 10-30: a spawned agent's name is the game's, not the case's) -------------

def _default_lua(h: FakeHarness, line: str) -> str:
    saved, h.on_lua = h.on_lua, None
    try:
        return h.run_lua(line)
    finally:
        h.on_lua = saved


def _run_with(harness: FakeHarness, suite: str, real_toml: Path, suites_dir: Path, report_dir: Path):
    return run_suite(
        suite, real_toml, suites_dir=suites_dir, report_dir=report_dir,
        control_factory=harness.control_factory, advance_turn=harness.advance_turn,
        is_game_running=harness.is_game_running, relaunch_game=harness.relaunch_game,
        stop_loop=harness.stop_loop, stop_crash_watch=harness.stop_crash_watch,
        start_qa_loop=harness.start_qa_loop, start_real=harness.start_real,
        start_crash_watch=harness.start_crash_watch, stop_qa_loop=harness.stop_qa_loop,
    )


def test_case_setup_accepts_plain_lines_and_bind_tables():
    case = Case.model_validate({
        "name": "c",
        "setup": ['M.qa.where("x")',
                  {"lua": 'return M.qa.spawn_agent("england", "spy", 1, 2, "QA Spy")', "bind": "spy"}],
        "expect": [{"log": "x"}],
    })
    assert case.setup[0] == 'M.qa.where("x")'
    assert case.setup[1].lua.startswith("return M.qa.spawn_agent(")
    assert case.setup[1].bind == "spy"


def _bind_suite(suites_dir: Path) -> None:
    suites_dir.mkdir()
    (suites_dir / "smoke.toml").write_text(
        'name = "smoke"\nfaction = "england"\n\n'
        '[[cases]]\nname = "spawn_agent"\ntargets = { x = 108, y = 153 }\n'
        'setup = [\n'
        '  { lua = \'return M.qa.spawn_agent("england", "spy", $x, $y, "QA Spy")\', bind = "spy" },\n'
        '  \'return M.qa.skill("$spy", "GoodSpy", 5)\',\n'
        ']\n'
        'expect = [\n'
        '  { state = "agents[id=$spy].x", equals = "$x" },\n'
        '  { state = "agents[id=$spy].y", equals = "$y" },\n'
        ']\n'
        '[cases.orders]\n'
        '1 = [{ type = "spy", agent = "$spy", target = "York" }]\n',
        encoding="utf-8",
    )


def test_setup_bind_feeds_later_setup_orders_and_expects(tmp_path: Path):
    real_toml, turn_root, save_dir = _write_real_game(tmp_path)
    (save_dir / "Autosave.sav").write_bytes(b"save-turn-10")
    _write_state(turn_root, "scratch", 10)
    suites_dir = tmp_path / "suites"
    _bind_suite(suites_dir)
    harness = FakeHarness(turn_root)

    def on_lua(h: FakeHarness, line: str) -> str:
        if "M.qa.spawn_agent(" in line:
            h.append_log("qa: spawn_agent ok: Edwin#2")
            return "Edwin#2"
        return _default_lua(h, line)

    def on_advance(h: FakeHarness, game_id: str, faction: str, turn: int) -> None:
        _write_state(h.turn_root, game_id, turn, faction,
                     agents=[{"id": "Edwin#2", "kind": "spy", "x": 108, "y": 153}])

    harness.on_lua = on_lua
    harness.on_advance = on_advance
    results, _ = _run_with(harness, "smoke", real_toml, suites_dir, tmp_path / "runs" / "qa")
    assert [(r.name, r.outcome) for r in results] == [("spawn_agent", "pass")], results
    assert 'return M.qa.skill("Edwin#2", "GoodSpy", 5)' in harness.lua_calls
    plan = json.loads((real_toml.parent / "qa-smoke-plan.json").read_text(encoding="utf-8"))
    assert plan == {"11": [{"type": "spy", "agent": "Edwin#2", "target": "York"}]}
    assert "agents[id=Edwin#2].x=108" in results[0].evidence


def test_setup_bind_to_nothing_fails_the_case(tmp_path: Path):
    real_toml, turn_root, save_dir = _write_real_game(tmp_path)
    (save_dir / "Autosave.sav").write_bytes(b"save-turn-10")
    _write_state(turn_root, "scratch", 10)
    suites_dir = tmp_path / "suites"
    _bind_suite(suites_dir)
    harness = FakeHarness(turn_root)

    def on_lua(h: FakeHarness, line: str) -> str:
        if "M.qa.spawn_agent(" in line:
            h.append_log("qa: spawn_agent ok: ")
            return ""
        return _default_lua(h, line)

    harness.on_lua = on_lua
    results, _ = _run_with(harness, "smoke", real_toml, suites_dir, tmp_path / "runs" / "qa")
    assert results[0].outcome == "fail"
    assert "$spy" in results[0].evidence
    assert not any("M.qa.skill(" in c for c in harness.lua_calls)
    assert not any(e.startswith("advance:") for e in harness.events)


def test_build_script_plan_leaves_bound_orders_to_the_case_run():
    bound = Case.model_validate({
        "name": "c",
        "setup": [{"lua": "return M.qa.spawn_agent('england', 'spy', 1, 2, 'x')", "bind": "spy"}],
        "orders": {1: [{"type": "spy", "agent": "$spy", "target": "York"}]},
        "expect": [{"log": "x"}],
    })
    plain = Case.model_validate({
        "name": "d",
        "orders": {1: [{"type": "spy", "agent": "Marco", "target": "York"}]},
        "expect": [{"log": "x"}],
    })
    assert build_script_plan([bound, plain], 10) == {"12": [{"type": "spy", "agent": "Marco", "target": "York"}]}


# --- restore abort: the load never reached the game (live 10-30 17:12) --------------------------

def _restore_with(harness: FakeHarness, real_toml: Path, **kw):
    return restore(
        real_toml,
        control_factory=harness.control_factory,
        is_game_running=harness.is_game_running,
        relaunch_game=harness.relaunch_game,
        stop_loop=harness.stop_loop,
        stop_crash_watch=harness.stop_crash_watch,
        start_real=harness.start_real,
        start_crash_watch=harness.start_crash_watch,
        reload_timeout=0.05,
        poll_interval=0.01,
        **kw,
    )


def _locked_game(tmp_path: Path, run_log: list[str] | None = None, with_offset: bool = True):
    """A parked game whose QA run logged run_log after it started (log_offset in the lock)."""
    real_toml, turn_root, save_dir = _write_real_game(tmp_path)
    keep = save_dir / "parley_keep_scratch.sav"
    keep.write_bytes(b"kept")
    log = turn_root / "parley_bridge.log"
    log.write_text("2026-10-30 17:00:00 autoplay: ending turn 9\n", encoding="utf-8")  # before the run
    lock_data: dict = {"game_id": "scratch", "turn": 10}
    if with_offset:
        lock_data["log_offset"] = log.stat().st_size
    with log.open("a", encoding="utf-8") as f:
        for line in run_log or []:
            f.write(f"2026-10-30 17:11:00 {line}\n")
    lock = turn_root / "qa.lock"
    lock.write_text(json.dumps(lock_data), encoding="utf-8")
    return real_toml, turn_root, save_dir, keep, lock


@pytest.mark.parametrize("failure", ["error_result", "load_failed_line"])
def test_restore_load_that_never_reached_the_game_restarts_real_and_retires_lock(tmp_path: Path, failure: str):
    import datetime as dt

    # live 17:12: step one failed, so the run changed nothing before the failed load
    real_toml, turn_root, save_dir, keep, lock = _locked_game(
        tmp_path, run_log=["qa: spawn_agent failed: boom", "control: lua -> nil"])
    harness = FakeHarness(turn_root)

    def on_lua(h: FakeHarness, line: str) -> str:
        if failure == "error_result":
            return "[string \"...\"]:1: attempt to index nil (error)"
        h.append_log("qa: load failed: cannot open save")
        return "nil"

    harness.on_lua = on_lua
    with pytest.raises(QARunError) as ei:
        _restore_with(harness, real_toml, now_fn=lambda: dt.datetime(2026, 10, 30, 17, 12, 5))
    msg = str(ei.value)
    assert "restore failed at loaded" in msg
    assert "aborted" in msg and "never reached the game" in msg
    assert "start_real:scratch" in harness.events
    assert "start_crash_watch" in harness.events
    assert harness.events.index("stop_crash_watch") < harness.events.index("start_crash_watch")
    assert not lock.exists()
    assert (turn_root / "qa.lock.aborted-20261030-171205").exists()
    assert not keep.exists()
    aborted_keep = save_dir / "parley_keep_scratch.restored-20261030-171205-aborted.sav"
    assert aborted_keep.read_bytes() == b"kept"
    assert "qa.lock.aborted-20261030-171205" in msg and aborted_keep.name in msg


def test_restore_keeps_the_lock_when_the_load_may_have_reached_the_game(tmp_path: Path):
    real_toml, turn_root, save_dir, keep, lock = _locked_game(tmp_path)
    harness = FakeHarness(turn_root)

    def on_lua(h: FakeHarness, line: str) -> str:  # load ok logged, but no reload marker
        h.append_log("qa: load ok: mods/parley/saves/parley_keep_scratch.sav")
        return "mods/parley/saves/parley_keep_scratch.sav"

    harness.on_lua = on_lua
    with pytest.raises(QARunError, match="restore failed at loaded; lock kept"):
        _restore_with(harness, real_toml)
    assert lock.exists() and keep.exists()
    assert "start_real:scratch" not in harness.events


def test_restore_keeps_the_lock_when_restarting_after_an_aborted_load_fails(tmp_path: Path):
    real_toml, turn_root, save_dir, keep, lock = _locked_game(tmp_path)
    harness = FakeHarness(turn_root)
    harness.on_lua = lambda h, line: "boom (error)"

    def start_real_boom(rt: Path) -> None:
        raise subprocess.CalledProcessError(1, ["game.sh", "play", rt.stem])

    harness.start_real = start_real_boom
    with pytest.raises(QARunError, match="lock kept"):
        _restore_with(harness, real_toml)
    assert lock.exists() and keep.exists()


def test_aborted_keep_survives_the_next_restore_prune(tmp_path: Path):
    import datetime as dt

    real_toml, turn_root, save_dir, keep, lock = _locked_game(tmp_path)
    harness = FakeHarness(turn_root)
    harness.on_lua = lambda h, line: "boom (error)"
    with pytest.raises(QARunError):
        _restore_with(harness, real_toml, now_fn=lambda: dt.datetime(2026, 10, 30, 17, 12, 5))
    keep.write_bytes(b"kept-2")
    lock.write_text(json.dumps({"game_id": "scratch", "turn": 10}), encoding="utf-8")
    ok = FakeHarness(turn_root)
    assert _restore_with(ok, real_toml, now_fn=lambda: dt.datetime(2026, 10, 30, 18, 0, 0)) is True
    assert (save_dir / "parley_keep_scratch.restored-20261030-171205-aborted.sav").exists()
    assert (save_dir / "parley_keep_scratch.restored-20261030-180000.sav").exists()









@pytest.mark.parametrize("run_log, with_offset, why", [
    (["qa: spawn_agent ok: Edwin"], True, "qa: spawn_agent ok: Edwin"),
    (["qa: spawn_agent failed: x", "autoplay: ending turn 10"], True, "autoplay: ending turn 10"),
    ([], False, "no run start offset"),
])
def test_restore_failed_load_on_a_changed_game_leaves_the_real_loop_stopped(
    tmp_path: Path, run_log: list[str], with_offset: bool, why: str
):
    real_toml, turn_root, save_dir, keep, lock = _locked_game(tmp_path, run_log, with_offset)
    harness = FakeHarness(turn_root)
    harness.on_lua = lambda h, line: "boom (error)"
    with pytest.raises(QARunError) as ei:
        _restore_with(harness, real_toml)
    msg = str(ei.value)
    assert "lock kept (phase load_failed)" in msg
    assert "QA-altered campaign" in msg and why in msg
    assert "deliberately left stopped" in msg
    assert str(keep) in msg and "just qa-restore" in msg
    assert "start_real:scratch" not in harness.events
    assert "start_crash_watch" not in harness.events
    assert keep.exists() and not list(save_dir.glob("*aborted*"))
    assert lock.exists() and not list(turn_root.glob("qa.lock.aborted-*"))
    data = json.loads(lock.read_text(encoding="utf-8"))
    assert data["load_failed"] is True
    assert not data.get("loaded")

    # fixed load: just qa-restore finishes the job from the same lock
    ok = FakeHarness(turn_root)
    assert _restore_with(ok, real_toml) is True
    assert "start_real:scratch" in ok.events and not lock.exists()


def _failing_load_run(tmp_path: Path, spawn_ok: bool):
    real_toml, turn_root, save_dir = _write_real_game(tmp_path)
    (save_dir / "Autosave.sav").write_bytes(b"save-turn-10")
    _write_state(turn_root, "scratch", 10)
    (turn_root / "parley_bridge.log").write_text("2026-10-30 17:00:00 autoplay: ending turn 9\n", encoding="utf-8")
    suites_dir = tmp_path / "suites"
    _bind_suite(suites_dir)
    harness = FakeHarness(turn_root)

    def on_lua(h: FakeHarness, line: str) -> str:
        if "M.qa.spawn_agent(" in line:
            if spawn_ok:
                h.append_log("qa: spawn_agent ok: Edwin")
                return "Edwin"
            h.append_log("qa: spawn_agent failed: boom")
            return "nil"
        if "M.qa.load(" in line:
            return "attempt to index a nil value (error)"
        return _default_lua(h, line)

    harness.on_lua = on_lua
    with pytest.raises(QARunError) as ei:
        _run_with(harness, "smoke", real_toml, suites_dir, tmp_path / "runs" / "qa")
    return str(ei.value), harness, turn_root


def test_run_whose_first_step_failed_restarts_real_after_a_failed_load(tmp_path: Path):
    msg, harness, turn_root = _failing_load_run(tmp_path, spawn_ok=False)
    assert "aborted" in msg and "never reached the game" in msg
    assert "start_real:scratch" in harness.events
    assert not (turn_root / "qa.lock").exists()


def test_run_that_changed_the_game_keeps_real_stopped_after_a_failed_load(tmp_path: Path):
    msg, harness, turn_root = _failing_load_run(tmp_path, spawn_ok=True)
    assert "QA-altered campaign" in msg and "qa: spawn_agent ok: Edwin" in msg
    assert "start_real:scratch" not in harness.events
    assert json.loads((turn_root / "qa.lock").read_text(encoding="utf-8"))["load_failed"] is True


# --- field suite: tile binds, a home town, a hostile town ----------------------------------

def test_tile_binds_split_a_tile_into_x_and_y():
    assert tile_binds("dest", "110,154") == {"dest_x": 110, "dest_y": 154}
    assert tile_binds("dest", " 7,-2 ") == {"dest_x": 7, "dest_y": -2}
    assert tile_binds("army", "Edwin") == {}
    assert tile_binds("army", "garrison:London") == {}
    assert tile_binds("army", "1,2,3") == {}


def test_case_binds_cover_a_bound_tiles_x_and_y():
    case = Case.model_validate({
        "name": "c",
        "setup": [{"lua": "return M.qa.free_tile(1, 2, 1, 1)", "bind": "dest"}],
        "expect": [{"state": "armies[id=x].x", "equals": "$dest_x"}],
    })
    assert case.binds == {"dest", "dest_x", "dest_y"}


def _own(name, x, y, units=4, **extra):
    return {"id": name, "name": name, "x": x, "y": y, "garrison_units": units, **extra}


def test_pick_home_takes_an_own_town_with_room_and_no_general():
    state = {
        "settlements": [
            _own("London", 112, 149),               # Henry is inside: a spawned general wouldn't lead it
            _own("Nottingham", 110, 157, units=19),  # full: one more and nobody can walk in
            _own("Caen", 100, 140, siege={"turns": 1}),
            {"id": "Nowhere", "garrison_units": 0},  # no tile
            _own("York", 106, 164),
        ],
        "armies": [
            {"id": "garrison:London", "leader": "Henry", "in_settlement": "London", "x": 112, "y": 149},
            {"id": "garrison:York", "in_settlement": "York", "x": 106, "y": 164},
        ],
    }
    assert pick_home(state) == {"home_settlement": "York", "home_x": 106, "home_y": 164}
    # a full town is still an anchor to spawn beside, but nothing to withdraw into
    assert pick_home({"settlements": [_own("London", 112, 149, units=19)]}) == {"home_x": 112, "home_y": 149}
    assert pick_home({}) == {}


# qa-field turn 65 England, live 10-30 23:19 (trimmed): both towns led by a general
_LIVE_ENGLAND_T65 = {
    "settlements": [
        {"id": "London", "x": 109, "y": 147, "siege": None, "garrison_units": 10},
        {"id": "Nottingham", "x": 107, "y": 155, "siege": None, "garrison_units": 18},
    ],
    "armies": [
        {"id": "garrison:London", "leader": "Rufus", "x": 109, "y": 147, "in_settlement": "London", "units": 10},
        {"id": "garrison:Nottingham", "leader": "Henry", "x": 107, "y": 155, "in_settlement": "Nottingham", "units": 18},
        {"id": "James of Evesham", "leader": "James of Evesham", "x": 121, "y": 143, "in_settlement": None, "units": 1},
    ],
}


def test_pick_home_anchors_beside_a_led_town_when_none_is_free():
    # live 10-30 23:10-23:30: eight field cases failed at setup on "no live target for home_x,
    # home_y" though they only spawn beside the town
    out = pick_home(_LIVE_ENGLAND_T65)
    assert out == {"home_x": 109, "home_y": 147}
    # a town under siege is the last choice for an anchor
    sieged = json.loads(json.dumps(_LIVE_ENGLAND_T65))
    sieged["settlements"][0]["siege"] = {"faction": "portugal", "turns": 1}
    assert pick_home(sieged) == {"home_x": 107, "home_y": 155}
    for s in sieged["settlements"]:
        s["siege"] = {"turns": 1}
    assert pick_home(sieged) == {"home_x": 109, "home_y": 147}


def test_home_refusals_say_why_each_town_was_passed_over():
    from parley.qa.runner import home_refusals

    assert home_refusals(_LIVE_ENGLAND_T65) == (
        "London: Rufus leads its garrison; Nottingham: Henry leads its garrison"
    )
    state = {"settlements": [_own("Caen", 1, 2, siege={"turns": 1}), _own("York", 3, 4, units=19), {"id": "X"}]}
    assert home_refusals(state) == "Caen: under siege; York: garrison full (19 units); X: no tile"
    assert home_refusals({}) == "no own towns"


def test_withdraw_without_a_home_town_fails_at_setup_with_the_reasons(tmp_path):
    from parley.qa.cases import Case, Expect, load_suite
    from parley.qa.runner import _effective_targets, _run_case, pick_targets

    # live 10-30 23:10-23:30 every English town had a general, so no $home_settlement: field's
    # withdraw (instant since 10-31) goes into $garrison_town, which a led town fills, and runs
    suite = load_suite(Path(__file__).resolve().parents[1] / "games" / "qa" / "field.toml")
    targets = pick_targets(_LIVE_ENGLAND_T65)
    for c in suite.cases:
        assert _effective_targets(c, targets)[1] == [], c.name
    # a case that still names $home_settlement fails at setup, saying why town by town
    withdraw = Case(name="withdraw", expect=[Expect(log="x")],
                    orders={1: [{"type": "withdraw", "army": "Edwin", "to_settlement": "$home_settlement"}]})
    assert _effective_targets(withdraw, targets)[1] == ["home_settlement"]
    turn_root = tmp_path / "parley_turns"
    sdir = turn_root / "qa-field" / "turn-0065" / "england"
    sdir.mkdir(parents=True)
    (sdir / "state.json").write_text(json.dumps(_LIVE_ENGLAND_T65))
    result, _ = _run_case(
        withdraw, "qa-field", "real", "england", turn_root, ctrl=None, current_turn=65,  # type: ignore[arg-type]
        plan_path=tmp_path / "plan.json", qa_toml_path=tmp_path / "qa.toml",
        start_qa_loop_fn=lambda p: None, advance_turn_fn=lambda g, f, t: t + 1,
    )
    assert result.outcome == "fail" and result.turns == 0
    assert result.evidence == (
        "no live target found in state.json for: home_settlement (no own town to withdraw into: "
        "London: Rufus leads its garrison; Nottingham: Henry leads its garrison)"
    )


def test_garrison_general_leaves_says_he_never_left():
    # live 10-30 23:29 (turn 67): the move came back "done", Rufus still led garrison:London, and the
    # case's evidence was "state 'armies[id=Rufus].x' not found". Instant since 10-31: the general is
    # read by name (M.qa.status), so a failure shows his tile and the town he still stands in
    import re

    from parley.qa.cases import load_suite
    from parley.qa.runner import _substitute_str

    suite = load_suite(Path(__file__).resolve().parents[1] / "games" / "qa" / "field.toml")
    case = next(c for c in suite.cases if c.name == "garrison_general_leaves")
    targets = {"gen": "Rufus", "out_x": 108, "out_y": 146}
    status = next(e for e in case.expect if e.lua and "M.qa.status(" in e.lua)
    assert _substitute_str(status.lua, targets) == 'return M.qa.status("Rufus")'
    pattern = _substitute_str(status.match, targets)
    assert not re.search(pattern, "109,147 moves=20 town=London")  # he never left
    assert not re.search(pattern, "108,146 moves=12 town=London")  # a split that left him inside
    assert re.search(pattern, "108,146 moves=12 town=-")  # outside, on the tile he was sent to


def test_turn_wait_outlasts_the_bridges_end_turn_hold():
    # #288: the bridge holds End Turn up to K.DECISION_HOLD_MAX while an offer waits; a 180 s turn
    # wait failed a held turn as "turn stuck" (live 10-30 23:06)
    import inspect
    import re

    from parley.qa import runner

    lua = (Path(__file__).resolve().parents[1] / "lua" / "parley_bridge.lua").read_text()
    decide_wait = int(re.search(r"local READ_WAIT, DECIDE_WAIT = \d+, (\d+)", lua).group(1))
    extra = int(re.search(r"K\.DECISION_HOLD_MAX = DECIDE_WAIT \+ (\d+)", lua).group(1))
    assert runner.BRIDGE_DECISION_HOLD_MAX == decide_wait + extra
    assert runner.TURN_TIMEOUT > runner.BRIDGE_DECISION_HOLD_MAX
    assert inspect.signature(runner._default_advance_turn).parameters["timeout"].default == runner.TURN_TIMEOUT
    assert inspect.signature(runner.run_suite).parameters["turn_timeout"].default == runner.TURN_TIMEOUT


def test_pick_garrison_town_prefers_a_town_its_general_leads():
    # live 10-30 19:51: every English town had a general, so pick_home found none and the garrison
    # case never ran. A town its general already leads is the live case (Robert in Paris)
    from parley.qa.runner import pick_garrison_town

    state = {
        "settlements": [
            _own("Caen", 100, 140, siege={"turns": 1}),
            _own("Nottingham", 107, 155),
            _own("London", 109, 147),
        ],
        "armies": [
            {"id": "garrison:Caen", "leader": "Robert", "in_settlement": "Caen", "x": 100, "y": 140},
            {"id": "garrison:London", "leader": "Henry", "in_settlement": "London", "x": 109, "y": 147},
            {"id": "garrison:Nottingham", "in_settlement": "Nottingham", "x": 107, "y": 155},
        ],
    }
    assert pick_garrison_town(state) == {"garrison_town": "London", "garrison_town_x": 109, "garrison_town_y": 147}
    # nobody leads a garrison: a town with room, where the case spawns one
    state["armies"].pop(1)
    assert pick_garrison_town(state)["garrison_town"] == "Nottingham"
    assert pick_garrison_town({"settlements": [_own("York", 106, 164, units=19)]}) == {}
    assert pick_garrison_town({}) == {}


def test_default_advance_timeout_on_a_live_bridge_is_a_stuck_turn(tmp_path: Path):
    """Live 10-30 19:41-19:44: the turn after a papal notice never ended; the bridge kept logging
    'stuck?' and the 180 s wait raised a QARunError that dropped the case from the report. A turn
    that doesn't end on a live bridge fails the case with the bridge's last turn line and ends the
    run, as a hang does (the restore loads the kept save on a stuck game too)."""
    from parley.qa.runner import _GameDown, _default_advance_turn

    turn_root = tmp_path / "parley_turns"
    turn_root.mkdir()
    log = turn_root / "parley_bridge.log"
    log.write_text(
        "2026-10-30 19:41:55 autoplay: ending turn 48\n"
        "2026-10-30 19:44:35 autoplay: turn 48 stuck? try 8: no known popup open; reopening a minimized message\n"
    )

    def alive() -> None:  # the bridge keeps logging
        with log.open("a", encoding="utf-8") as f:
            f.write("2026-10-30 19:44:38 character event: england: Henry was struck by a disaster\n")

    advance = _default_advance_turn(
        turn_root, lambda: alive(), timeout=0.05, poll_interval=0.01, hang_seconds=0.3,
    )
    with pytest.raises(_GameDown) as exc:
        advance("qa-covert", "england", 47)
    assert exc.value.evidence.startswith("turn stuck: no qa-covert/england report after turn 47 within ")
    assert exc.value.evidence.endswith("autoplay: turn 48 stuck? try 8: no known popup open; reopening a minimized message")


def test_a_stuck_turn_fails_its_case_in_the_report_and_restores(tmp_path: Path):
    real_toml, turn_root, save_dir = _write_real_game(tmp_path)
    (save_dir / "Autosave.sav").write_bytes(b"save-turn-10")
    _write_state(turn_root, "scratch", 10)
    suites_dir = _hang_suites(
        tmp_path,
        '[[cases]]\nname = "marches"\nmax_turns = 4\n'
        'expect = [{ log = "never logged" }]\n'
        '[cases.orders]\n1 = [{ type = "move_army", army = "x", x = 1, y = 1 }]\n\n'
        '[[cases]]\nname = "after"\nsetup = [\'M.qa.where("QA Spy")\']\nexpect = [{ log = "qa: where ok:" }]\n',
    )
    harness = FakeHarness(turn_root)
    harness.append_log("autoplay: turn 11 stuck? try 1: no known popup open; reopening a minimized message")

    def alive() -> bool:  # no new report ever comes, but the bridge keeps logging
        harness.append_log("character event: england: Henry was struck by a disaster")
        return True

    results, report = run_suite(
        "covert",
        real_toml,
        suites_dir=suites_dir,
        report_dir=tmp_path / "runs" / "qa",
        control_factory=harness.control_factory,
        is_game_running=alive,
        relaunch_game=harness.relaunch_game,
        stop_loop=harness.stop_loop,
        stop_crash_watch=harness.stop_crash_watch,
        start_qa_loop=harness.start_qa_loop,
        start_real=harness.start_real,
        start_crash_watch=harness.start_crash_watch,
        reload_timeout=0.05,
        turn_timeout=0.05,
        poll_interval=0.01,
        hang_seconds=0.3,
    )
    assert [(r.name, r.outcome) for r in results] == [("skill", "pass"), ("marches", "fail")]
    assert results[1].evidence.startswith("turn stuck: ")
    assert "turn 11 stuck? try 1" in results[1].evidence
    assert "turn stuck: " in report.read_text(encoding="utf-8")
    assert "relaunch_game" not in harness.events  # stuck, not dead or hung: the load is enough
    assert any("M.qa.load(" in e for e in harness.events)
    assert not (turn_root / "qa.lock").exists()


def test_pick_hostile_takes_the_nearest_rebel_or_enemy_town_reachable_by_land():
    state = {
        "factions": [{"id": "france", "stance": "war"}, {"id": "scotland", "stance": "peace"}],
        "nearby_settlements": [
            {"id": "Edinburgh", "faction": "scotland", "x": 100, "y": 170, "distance": 2},  # at peace
            {"id": "Caen", "faction": "france", "x": 100, "y": 140, "distance": 3, "by_land": False},
            {"id": "Rennes", "faction": "france", "x": 101, "y": 136, "distance": 7},
            {"id": "York", "faction": "slave", "x": 106, "y": 164, "distance": 5, "by_land": True},
        ],
    }
    assert pick_hostile(state) == {"hostile_settlement": "York", "hostile_x": 106, "hostile_y": 164}
    state["nearby_settlements"].pop()
    assert pick_hostile(state)["hostile_settlement"] == "Rennes"
    assert pick_hostile({"nearby_settlements": [{"id": "Paris", "faction": "france", "x": 1, "y": 2}]}) == {}
    assert pick_hostile({}) == {}


def test_pick_targets_adds_home_and_hostile():
    state = {
        "settlements": [_own("London", 112, 149)],
        "armies": [],
        "nearby_settlements": [{"id": "York", "name": "York", "faction": "slave", "x": 106, "y": 164, "distance": 3}],
    }
    targets = pick_targets(state)
    assert (targets["home_settlement"], targets["home_x"], targets["home_y"]) == ("London", 112, 149)
    assert (targets["hostile_settlement"], targets["hostile_x"], targets["hostile_y"]) == ("York", 106, 164)
    assert targets["target_settlement"] == "York"


def test_bound_tile_feeds_setup_orders_and_expects_as_numbers(tmp_path: Path):
    real_toml, turn_root, save_dir = _write_real_game(tmp_path)
    (save_dir / "Autosave.sav").write_bytes(b"save-turn-10")
    _write_state(turn_root, "scratch", 10)
    suites_dir = tmp_path / "suites"
    suites_dir.mkdir()
    (suites_dir / "smoke.toml").write_text(
        'name = "smoke"\nfaction = "england"\n\n'
        '[[cases]]\nname = "move_army"\n'
        'setup = [\n'
        '  { lua = \'return M.qa.free_tile($home_x, $home_y, 2, 3)\', bind = "at" },\n'
        '  { lua = \'return M.qa.spawn_army("england", $at_x, $at_y)\', bind = "army" },\n'
        '  { lua = \'return M.qa.free_tile($at_x, $at_y, 2, 2)\', bind = "dest" },\n'
        ']\n'
        'expect = [\n'
        '  { state = "armies[id=$army].x", equals = "$dest_x" },\n'
        '  { state = "armies[id=$army].y", equals = "$dest_y" },\n'
        ']\n'
        '[cases.orders]\n'
        '1 = [{ type = "move_army", army = "$army", x = "$dest_x", y = "$dest_y" }]\n',
        encoding="utf-8",
    )
    harness = FakeHarness(turn_root)
    answers = {
        "return M.qa.free_tile(112, 149, 2, 3)": "110,147",
        'return M.qa.spawn_army("england", 110, 147)': "Edwin",
        "return M.qa.free_tile(110, 147, 2, 2)": "108,145",
    }

    def on_lua(h: FakeHarness, line: str) -> str:
        return answers[line] if line in answers else _default_lua(h, line)

    def on_advance(h: FakeHarness, game_id: str, faction: str, turn: int) -> None:
        _write_state(h.turn_root, game_id, turn, faction, armies=[{"id": "Edwin", "x": 108, "y": 145}])

    harness.on_lua = on_lua
    harness.on_advance = on_advance
    results, _ = _run_with(harness, "smoke", real_toml, suites_dir, tmp_path / "runs" / "qa")
    assert [(r.name, r.outcome) for r in results] == [("move_army", "pass")], results
    assert all(line in harness.lua_calls for line in answers)
    plan = json.loads((real_toml.parent / "qa-smoke-plan.json").read_text(encoding="utf-8"))
    assert plan == {"11": [{"type": "move_army", "army": "Edwin", "x": 108, "y": 145}]}


def test_a_tile_bind_that_isnt_a_tile_fails_the_case(tmp_path: Path):
    real_toml, turn_root, save_dir = _write_real_game(tmp_path)
    (save_dir / "Autosave.sav").write_bytes(b"save-turn-10")
    _write_state(turn_root, "scratch", 10)
    suites_dir = tmp_path / "suites"
    suites_dir.mkdir()
    (suites_dir / "smoke.toml").write_text(
        'name = "smoke"\nfaction = "england"\n\n'
        '[[cases]]\nname = "c"\n'
        'setup = [{ lua = \'return M.qa.town("York")\', bind = "york" }]\n'
        'expect = [{ log = "x" }]\n'
        '[cases.orders]\n'
        '1 = [{ type = "move_army", army = "Edwin", x = "$york_x", y = "$york_y" }]\n',
        encoding="utf-8",
    )
    harness = FakeHarness(turn_root)
    harness.on_lua = lambda h, line: "York" if "M.qa.town(" in line else _default_lua(h, line)
    results, _ = _run_with(harness, "smoke", real_toml, suites_dir, tmp_path / "runs" / "qa")
    assert results[0].outcome == "fail"
    assert "$york_x" in results[0].evidence and "$york_y" in results[0].evidence
    assert not any(e.startswith("advance:") for e in harness.events)


# --- each case on its own turns (live 10-30 18:00: covert's cases overlapped in one plan) --------

class _Campaign:
    """A fake campaign behind the QA loop: the loop answers each turn from the plan it loaded when it
    (re)started; the game applies a turn's orders, writes that turn's results.json, logs what came of
    them, then writes the next turn's report."""

    def __init__(self, h: FakeHarness, outcome, state_extra: dict | None = None):
        self.h = h
        self.outcome = outcome  # (order, turn, campaign) -> (result fields, log line or None, agent result or None)
        self.state_extra = state_extra or {}
        self.loaded: dict[str, list[dict]] = {}
        self.plans: list[dict[str, list[dict]]] = []
        self.inside: set[str] = set()
        start = h.start_qa_loop

        def start_qa_loop(qa_toml: Path) -> None:
            start(qa_toml)
            self.loaded = json.loads((qa_toml.parent / f"{qa_toml.stem}-plan.json").read_text(encoding="utf-8"))
            self.plans.append(self.loaded)

        h.start_qa_loop = start_qa_loop
        h.on_advance = self.advance

    def advance(self, h: FakeHarness, game_id: str, faction: str, turn: int) -> None:
        applied = turn - 1
        orders = self.loaded.get(str(applied), [])
        results, missions = [], []
        for i, order in enumerate(orders):
            res, line, mission = self.outcome(order, applied, self)
            results.append({"index": i, "type": order["type"], "reason": "", **res})
            if line:
                h.append_log(line)
            if mission:
                missions.append(mission)
        d = h.turn_root / game_id / f"turn-{applied:04d}" / faction
        d.mkdir(parents=True, exist_ok=True)
        (d / "results.json").write_text(json.dumps(results), encoding="utf-8")
        _write_state(h.turn_root, game_id, turn, faction, last_results=results, agent_results=missions,
                     **self.state_extra)


def _spy_then_assassin(order: dict, turn: int, game: _Campaign):
    if order["type"] == "spy":
        if order["agent"] in game.inside:
            return {"ok": False, "reason": f"'{order['agent']}' is already inside {order['target']}"}, None, None
        game.inside.add(order["agent"])
        return ({"ok": True}, "popup enemy_settlement_info_scroll: closed the spy report after england's mission",
                f"{order['agent']}'s spying: partly successful (chance was 95%)")
    if order["type"] in ("assassinate", "sabotage"):
        mission = "assassination" if order["type"] == "assassinate" else "sabotage"
        text = f"{order['agent']}'s {mission}: slightly successful (chance was 80%)"
        return {"ok": True}, f"agent mission: england: {text}", text
    raise AssertionError(order)


_SPY_CASE = (
    '[[cases]]\nname = "spy"\nchance = true\nmax_turns = 4\n'
    'setup = [{ lua = \'return M.qa.spawn_agent("england", "spy", 101, 173, "QA Spy")\', bind = "spy" }]\n'
    'expect = [\n'
    '  { order_ok = true },\n'
    '  { log = "popup enemy_settlement_info_scroll: closed the spy report after england\'s mission" },\n'
    ']\n'
    '[cases.orders]\n'
    '1 = [{ type = "spy", agent = "$spy", target = "York" }]\n'
    '2 = [{ type = "spy", agent = "$spy", target = "York" }]\n'
    '3 = [{ type = "spy", agent = "$spy", target = "York" }]\n'
    '4 = [{ type = "spy", agent = "$spy", target = "York" }]\n\n'
)
_ASSASSIN_CASE = (
    '[[cases]]\nname = "assassinate"\n'
    'setup = [{ lua = \'return M.qa.spawn_agent("england", "assassin", 105, 155, "QA Assassin")\', '
    'bind = "assassin" }]\n'
    'expect = [\n'
    '  { order_ok = true },\n'
    '  { log = "agent mission: england: .*assassination:" },\n'
    '  { state = "agent_results", equals = "assassination:" },\n'
    ']\n'
    '[cases.orders]\n'
    '1 = [{ type = "assassinate", agent = "$assassin", target = "Morgunn Erskyn" }]\n'
)
_COVERT_HEAD = 'name = "covert"\nfaction = "england"\n\n'


def _covert_game(tmp_path: Path, suite_text: str, outcome) -> tuple[FakeHarness, _Campaign, Path, Path]:
    real_toml, turn_root, save_dir = _write_real_game(tmp_path)
    (save_dir / "Autosave.sav").write_bytes(b"save-turn-10")
    _write_state(turn_root, "scratch", 10)
    suites_dir = tmp_path / "suites"
    suites_dir.mkdir()
    (suites_dir / "smoke.toml").write_text('name = "smoke"\nfaction = "england"\ncases = []\n', encoding="utf-8")
    (suites_dir / "covert.toml").write_text(suite_text, encoding="utf-8")
    harness = FakeHarness(turn_root)
    names = {"spy": "Davy Talbot", "assassin": "Ralph of Whitby"}

    def on_lua(h: FakeHarness, line: str) -> str:
        for kind, name in names.items():
            if "M.qa.spawn_agent(" in line and f'"{kind}"' in line:
                h.append_log(f"qa: spawn_agent ok: {name}")
                return name
        return _default_lua(h, line)

    harness.on_lua = on_lua
    return harness, _Campaign(harness, outcome), real_toml, suites_dir


def _loop_state_before(events: list[str], index: int) -> str | None:
    """The QA loop's last stop/start before events[index]."""
    for e in reversed(events[:index]):
        if e == "stop_qa_loop" or e.startswith("start_qa_loop"):
            return e
    return None


def test_cases_run_one_after_another_each_with_only_its_own_orders_in_the_plan(tmp_path: Path):
    harness, game, real_toml, suites_dir = _covert_game(
        tmp_path, _COVERT_HEAD + _SPY_CASE + _ASSASSIN_CASE, _spy_then_assassin)
    results, _ = _run_with(harness, "covert", real_toml, suites_dir, tmp_path / "runs" / "qa")
    assert [(r.name, r.outcome) for r in results] == [("spy", "pass"), ("assassinate", "pass")], results

    spy = [{"type": "spy", "agent": "Davy Talbot", "target": "York"}]
    # the spy case is decided at turn 12 (the report after its turn-11 order); the assassin's setup runs
    # then, so its turn 1 is 13, and the loop restarts on a plan with the assassin's order and nothing else
    assert game.plans[-2:] == [
        {"11": spy, "12": spy, "13": spy, "14": spy},
        {"13": [{"type": "assassinate", "agent": "Ralph of Whitby", "target": "Morgunn Erskyn"}]},
    ], game.plans
    assert "already inside" not in results[1].evidence

    # the loop is stopped (the game waits for the seat) while each case's setup runs
    spawns = [i for i, e in enumerate(harness.events) if e.startswith("lua:") and "spawn_agent" in e]
    assert len(spawns) == 2
    assert all(_loop_state_before(harness.events, i) == "stop_qa_loop" for i in spawns), harness.events


def test_a_case_reads_only_its_own_turns_results(tmp_path: Path):
    # live 10-30 18:00: the assassin's order_ok showed the spy's turn ("'Davy Talbot' is already inside
    # Edinburgh"). Here the assassin's order is never applied, while the turn before it holds a spy
    # failure, every report's last_results repeats it, and a stale results.json from an earlier run
    # sits in the case's own turn
    stale_spy = [{"index": 0, "type": "spy", "ok": False, "reason": "'Davy Talbot' is already inside Edinburgh"}]

    def never_applied(order: dict, turn: int, game: _Campaign):
        raise AssertionError("no order is applied in this test")

    harness, game, real_toml, suites_dir = _covert_game(tmp_path, _COVERT_HEAD + _ASSASSIN_CASE, never_applied)
    qa_dir = harness.turn_root / "qa-covert"
    d10 = qa_dir / "turn-0010" / "england"
    d10.mkdir(parents=True)
    (d10 / "results.json").write_text(json.dumps(stale_spy), encoding="utf-8")
    d11 = qa_dir / "turn-0011" / "england"
    d11.mkdir(parents=True)
    old = d11 / "results.json"
    old.write_text(json.dumps([{"index": 0, "type": "assassinate", "ok": True, "reason": ""}]), encoding="utf-8")
    for p in (old, d10 / "results.json", d10.parent, d11.parent):  # an earlier run's, older than the save
        os.utime(p, (1_000_000_000, 1_000_000_000))

    def advance(h: FakeHarness, game_id: str, faction: str, turn: int) -> None:  # orders never land
        h.append_log("agent mission: england: Ralph of Whitby's assassination: slightly successful")
        _write_state(h.turn_root, game_id, turn, faction, last_results=stale_spy,
                     agent_results=["Ralph of Whitby's assassination: slightly successful"])

    harness.on_advance = advance
    results, _ = _run_with(harness, "covert", real_toml, suites_dir, tmp_path / "runs" / "qa")
    assert results[0].name == "assassinate" and results[0].outcome == "fail", results
    assert "already inside" not in results[0].evidence
    assert "order_ok=True not met ([])" in results[0].evidence


def test_a_turn_that_ends_during_setup_is_not_the_cases_first_turn(tmp_path: Path):
    # live 10-30 17:59: sabotage's setup spawned at turn 36, the game ended turn 36 two seconds later,
    # and the plan put the order at 36; it was never given
    sabotage = _COVERT_HEAD + (
        '[[cases]]\nname = "sabotage"\n'
        'setup = [\n'
        '  { lua = \'return M.qa.spawn_agent("england", "assassin", 105, 163, "QA Saboteur")\', bind = "saboteur" },\n'
        '  \'return M.qa.skill("$saboteur", "GoodAssassin", 5)\',\n'
        ']\n'
        'expect = [\n'
        '  { order_ok = true },\n'
        '  { log = "agent mission: england: .*sabotage:" },\n'
        '  { state = "agent_results", equals = "sabotage:" },\n'
        ']\n'
        '[cases.orders]\n'
        '1 = [{ type = "sabotage", agent = "$saboteur", settlement = "York" }]\n'
    )
    harness, game, real_toml, suites_dir = _covert_game(tmp_path, sabotage, _spy_then_assassin)
    spawn = harness.on_lua

    def on_lua(h: FakeHarness, line: str) -> str:
        res = spawn(h, line)
        if "M.qa.spawn_agent(" in line:  # the game ends turn 10 while setup is still running
            _write_state(h.turn_root, "qa-covert", 11)
        return res

    harness.on_lua = on_lua
    results, _ = _run_with(harness, "covert", real_toml, suites_dir, tmp_path / "runs" / "qa")
    assert game.plans[-1] == {"12": [{"type": "sabotage", "agent": "Ralph of Whitby", "settlement": "York"}]}
    assert [(r.name, r.outcome) for r in results] == [("sabotage", "pass")], results


def test_a_case_with_orders_is_not_judged_before_its_orders_apply(tmp_path: Path):
    # the report of the case's own first turn predates its orders: a state expect it happens to meet
    # (a previous case's refusal in last_results) must not pass the case
    text = _COVERT_HEAD + (
        '[[cases]]\nname = "refused"\nmax_turns = 1\n'
        'setup = [{ lua = \'return M.qa.spawn_agent("england", "spy", 101, 173, "QA Spy")\', bind = "spy" }]\n'
        'expect = [{ state = "last_results", equals = "already inside" }]\n'
        '[cases.orders]\n'
        '1 = [{ type = "spy", agent = "$spy", target = "York" }]\n'
    )
    harness, game, real_toml, suites_dir = _covert_game(tmp_path, text, _spy_then_assassin)

    def advance(h: FakeHarness, game_id: str, faction: str, turn: int) -> None:
        _write_state(h.turn_root, game_id, turn, faction, last_results=[
            {"index": 0, "type": "spy", "ok": False, "reason": "'Davy Talbot' is already inside York"}])

    harness.on_advance = advance
    results, _ = _run_with(harness, "covert", real_toml, suites_dir, tmp_path / "runs" / "qa")
    assert results[0].outcome == "fail", results


def test_pick_targets_gives_the_character_and_settlement_tiles_and_skips_fleets():
    state = {
        "nearby_settlements": [{"id": "Edinburgh", "faction": "scotland", "x": 102, "y": 174, "distance": 0}],
        "visible_enemies": [
            {"id": "Admiral Enguerran", "leader": "Admiral Enguerran", "is_fleet": True, "x": 102, "y": 141,
             "distance": 1},
            {"id": "Edmund Canmore#2", "leader": "Edmund Canmore", "x": 98, "y": 180, "distance": 6},
        ],
        "seen_agents": [{"id": "Admiral Enguerran#2", "kind": "admiral", "x": 102, "y": 141, "distance": 1}],
    }
    t = pick_targets(state)
    assert t["target_character"] == "Edmund Canmore#2"  # the report id, which orders resolve
    assert (t["target_character_x"], t["target_character_y"]) == (98, 180)
    assert (t["target_settlement_x"], t["target_settlement_y"]) == (102, 174)


def test_covert_spawns_each_agent_beside_its_target_and_orders_it_by_its_bound_name():
    import re

    from parley.qa.cases import SetupStep, load_suite
    from parley.qa.runner import DEFAULT_SUITES_DIR, _required_placeholders

    covert = {c.name: c for c in load_suite(DEFAULT_SUITES_DIR / "covert.toml").cases}
    live = set(pick_targets({
        "nearby_settlements": [{"id": "Edinburgh", "faction": "scotland", "x": 102, "y": 174, "distance": 0}],
        "visible_enemies": [{"id": "Edmund Canmore", "leader": "Edmund Canmore", "x": 98, "y": 180,
                             "distance": 6}],
        "settlements": [{"id": "York", "x": 106, "y": 164, "garrison_units": 3}],
    }))
    for c in covert.values():
        assert not (_required_placeholders(c) - c.binds - live), c.name
        spawns = [s.bind for s in c.setup if isinstance(s, SetupStep) and "spawn_agent" in s.lua]
        # the instant cases' orders are act lines; the turn case's are the seat's plan
        named = [o["agent"] for orders in c.orders.values() for o in orders]
        named += [m for a in c.act for m in re.findall(r'agent = "(\$\w+)"', a if isinstance(a, str) else a.lua)]
        assert named and all(a[1:] in spawns for a in named), c.name
    # live 10-30 18:00, 18:52 and 21:38: a victim picked from the sight lists walked off; the case now
    # spawns its own (a rebel army on a tile England sees) and the assassin on the next tile
    assert 'seen_tile("england", $garrison_town_x, $garrison_town_y' in covert["assassinate"].setup[0].lua
    assert "free_tile($victim_at_x, $victim_at_y, 1, 1)" in covert["assassinate"].setup[3].lua
    # an agent acts on a town from the next tile only: farther off he walks (spy_far_walks tests that)
    assert "free_tile($hostile_at_x, $hostile_at_y, 1, 1)" in covert["sabotage"].setup[2].lua
    assert "free_tile($hostile_at_x, $hostile_at_y, 1, 1)" in covert["spy_report_closed"].setup[2].lua


def test_assassinate_names_the_bench_victim_by_its_sight_id_not_the_nearest_character(tmp_path, venice_report):
    """Live 10-30 18:19: a victim picked from one report was gone from the next (Edmund Canmore went
    into Inverness). Live 10-30 22:03: the bench's own victim was never in England's sight lists and
    `$nearest_character_to:` sent the order to whoever was next nearest, across the sea. The order
    now names the victim's sight id, bound at setup by M.qa.sees, so no other character stands in."""
    import json as _json

    from parley.prompt import build_prompt
    from parley.protocol import Agent, Army
    from parley.qa.cases import load_suite
    from parley.qa.runner import DEFAULT_SUITES_DIR, build_script_plan
    from parley.seats.script import ScriptSeat
    from parley.validate import validate_orders

    # covert.toml's assassinate (a turn case again since 10-31): its order, as the scripted ruler's
    # plan names it, has to pass the validator
    from parley.qa.cases import Case, Expect

    suite_case = {c.name: c for c in load_suite(DEFAULT_SUITES_DIR / "covert.toml").cases}["assassinate"]
    assert suite_case.orders[1] == [{"type": "assassinate", "agent": "$assassin", "target": "$victim_id"}]
    case = Case(name="assassinate", expect=[Expect(log="agent mission")], orders=suite_case.orders)
    turn45 = {
        "nearby_settlements": [{"id": "Edinburgh", "faction": "scotland", "x": 102, "y": 174, "distance": 0},
                               {"id": "Inverness", "faction": "scotland", "x": 99, "y": 181, "distance": 7}],
        "visible_enemies": [{"id": "Edmund Canmore", "leader": "Edmund Canmore", "faction": "scotland",
                             "x": 98, "y": 180, "distance": 6}],
    }
    targets = {**pick_targets(turn45), "at": "97,179", "at_x": 97, "at_y": 179, "assassin": "Harry Baker",
               "victim": "Esau", "victim_at": "98,180", "victim_at_x": 98, "victim_at_y": 180,
               "victim_id": "Esau"}
    bound = case.model_copy(update={"targets": targets, "setup": []})
    plan = build_script_plan([bound], 45, targets)
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(_json.dumps(plan))

    # turn 46: a Scots diplomat walked up beside the assassin and is listed before the victim, a
    # French fleet with its admiral and a diplomat lie off Caen, far south
    report = venice_report.model_copy(update={
        "agents": [Agent(id="Harry Baker", kind="assassin", x=97, y=179)],
        "visible_enemies": [Army(id="Admiral Milet", leader="Admiral Milet", faction="france", is_fleet=True,
                                 x=103, y=136, strength=300, units=3, distance=2),
                            Army(id="Esau", leader="Esau", faction="slave", x=98, y=180, strength=50,
                                 units=1, distance=1)],
        "seen_agents": [
            Agent(id="Patrick Macdougall", kind="diplomat", faction="scotland", x=98, y=178, distance=1),
            Agent(id="Denisot de Mauchaut", kind="diplomat", faction="france", x=103, y=136, distance=2),
            Agent(id="Admiral Milet#2", kind="admiral", faction="france", x=103, y=136, distance=2),
        ],
    })
    orders, _ = ScriptSeat(str(plan_path)).decide(build_prompt(report, "p"), game_id="qa-covert", turn=46,
                                                 faction=report.faction, timeout=5)
    assert [(o.type, o.agent, o.target) for o in orders.orders] == [("assassinate", "Harry Baker", "Esau")]
    _, rejected = validate_orders(report, orders)
    assert rejected == []


def test_pick_targets_uses_report_ids_and_prefers_a_character_standing_in_a_town():
    """Only ids are in the validator's lists; an agent standing in a foreign town stays put more often
    than an army in the field, so it is the better target for an assassin acting next turn."""
    state = {
        "nearby_settlements": [{"id": "Inverness", "faction": "scotland", "x": 99, "y": 181, "distance": 7}],
        "visible_enemies": [
            {"leader": "No Id", "x": 100, "y": 170, "distance": 1},  # no report id: not orderable
            {"id": "Edmund Canmore", "leader": "Edmund Canmore", "x": 98, "y": 180, "distance": 6},
        ],
        "seen_agents": [{"id": "Fergus", "kind": "priest", "faction": "scotland", "x": 99, "y": 181,
                         "in_settlement": "Inverness", "distance": 7}],
    }
    t = pick_targets(state)
    assert t["target_character"] == "Fergus"
    assert (t["target_character_x"], t["target_character_y"]) == (99, 181)
    del state["seen_agents"]
    assert pick_targets(state)["target_character"] == "Edmund Canmore"

# --- hang detection (live 10-30 18:34: the papal election results scroll froze the game; the
# bridge log went silent with medieval2.exe alive, and nothing relaunched it) ---


def _age_log(log_path: Path, seconds: float) -> None:
    t = time.time() - seconds
    os.utime(log_path, (t, t))


def test_game_trouble_reports_dead_hung_or_nothing(tmp_path: Path):
    from parley.qa.runner import HANG_SECONDS, game_trouble

    assert HANG_SECONDS == 240.0
    log = tmp_path / "parley_bridge.log"
    # no log yet: nothing proves a hang
    assert game_trouble(lambda: True, log) is None
    log.write_text("2026-10-30 18:34:10 autoplay: turn 12\n2026-10-30 18:34:11 popup papal_election_results\n")
    assert game_trouble(lambda: True, log) is None  # fresh log: working
    dead = game_trouble(lambda: False, log)
    assert dead is not None and dead.startswith("game crashed at ")
    assert dead.endswith("2026-10-30 18:34:11 popup papal_election_results")
    _age_log(log, 300)
    hung = game_trouble(lambda: True, log)
    assert hung is not None and hung.startswith("game hung at ")
    assert hung.endswith("2026-10-30 18:34:11 popup papal_election_results")
    # the threshold is overridable
    _age_log(log, 5)
    assert game_trouble(lambda: True, log) is None
    assert game_trouble(lambda: True, log, hang_seconds=1.0).startswith("game hung at ")


def test_process_manager_writes_a_crash_report_and_never_raises(tmp_path, monkeypatch):
    # 11-05 07:18 a QA crash left no report; the restore's relaunch now writes one first
    from parley.qa import runner as r

    (tmp_path / "scripts").mkdir()
    script = tmp_path / "scripts" / "crash_report.py"
    script.write_text("print('writing')\nprint('runs/crashes/2026-11-05-071830')\n")
    monkeypatch.setattr(r, "REPO_ROOT", tmp_path)
    assert r._ProcessManager().crash_report("QA run: game crashed") == "runs/crashes/2026-11-05-071830"
    script.write_text("import sys\nsys.exit(3)\n")
    assert r._ProcessManager().crash_report("x") is None
    script.unlink()
    assert r._ProcessManager().crash_report("x") is None


def test_a_quiet_game_that_answers_is_not_hung(tmp_path: Path):
    # live 11-05 05:28: a held turn (paused.txt) logs nothing; the healthy game was read as hung
    from parley.qa.runner import game_trouble

    log = tmp_path / "parley_bridge.log"
    log.write_text("2026-11-05 05:21:17 paused: held on the test laptop\n")
    _age_log(log, 300)
    asked = []
    assert game_trouble(lambda: True, log, answers=lambda: asked.append(1) or True) is None
    assert asked == [1]
    hung = game_trouble(lambda: True, log, answers=lambda: False)
    assert hung is not None and hung.startswith("game hung at ")
    # a fresh log never asks
    log.write_text("2026-11-05 05:30:00 autoplay: turn 75\n")
    assert game_trouble(lambda: True, log, answers=lambda: asked.append(2) or False) is None
    assert asked == [1]


def test_game_trouble_takes_the_crash_dialog_as_a_crash_at_once(tmp_path: Path):
    # live 10-30 20:11: the Wine crash box kept medieval2.exe alive; the log was only seconds old
    from parley.qa.runner import game_trouble

    log = tmp_path / "parley_bridge.log"
    log.write_text("2026-10-30 20:11:48 bridge loaded campaign at turn 41\n")
    crashed = game_trouble(lambda: True, log, crash_dialog=lambda: True)
    assert crashed is not None and crashed.startswith("game crashed at ")
    assert "crash dialog" in crashed
    assert crashed.endswith("bridge loaded campaign at turn 41")
    assert game_trouble(lambda: True, log, crash_dialog=lambda: False) is None


def test_restore_relaunches_on_the_crash_dialog_before_the_load(tmp_path: Path):
    real_toml, turn_root, save_dir = _write_real_game(tmp_path)
    lock_path = _lock(turn_root, save_dir)
    harness = FakeHarness(turn_root)  # alive, log fresh
    harness.append_log("autoplay: turn 10, waiting for england")

    def dialog_up() -> bool:
        return "relaunch_game" not in harness.events  # the relaunch kills it

    assert _restore_hang(
        harness, real_toml, crash_dialog_up=dialog_up, dialog_confirm_seconds=0.01
    ) is True
    relaunch_idx = harness.events.index("relaunch_game")
    load_idx = next(i for i, e in enumerate(harness.events) if "M.qa.load(" in e)
    assert relaunch_idx < load_idx
    assert not lock_path.exists()


def test_restore_ignores_a_crash_dialog_seen_once(tmp_path: Path):
    # a false positive would kill a healthy game: one sighting, then gone, is no crash
    real_toml, turn_root, save_dir = _write_real_game(tmp_path)
    _lock(turn_root, save_dir)
    harness = FakeHarness(turn_root)
    harness.append_log("autoplay: turn 10, waiting for england")
    sightings = [True]

    def dialog_up() -> bool:
        return sightings.pop(0) if sightings else False

    assert _restore_hang(
        harness, real_toml, crash_dialog_up=dialog_up, dialog_confirm_seconds=0.01
    ) is True
    assert "relaunch_game" not in harness.events
    assert sightings == []  # it did look


def test_confirmed_dialog_needs_two_sightings_apart():
    from parley.qa.runner import DIALOG_CONFIRM_SECONDS, _confirmed_dialog

    assert DIALOG_CONFIRM_SECONDS >= 5.0
    slept: list[float] = []
    seen = iter([True, True])
    assert _confirmed_dialog(lambda: next(seen), apart=5.0, sleep=slept.append)() is True
    assert slept == [5.0]
    seen = iter([True, False])
    assert _confirmed_dialog(lambda: next(seen), apart=5.0, sleep=slept.append)() is False
    slept.clear()
    assert _confirmed_dialog(lambda: False, apart=5.0, sleep=slept.append)() is False
    assert slept == []  # no sighting, no wait


def test_run_suite_fails_a_case_on_the_crash_dialog(tmp_path: Path):
    real_toml, turn_root, save_dir = _write_real_game(tmp_path)
    (save_dir / "Autosave.sav").write_bytes(b"save-turn-10")
    _write_state(turn_root, "scratch", 10)
    suites_dir = _hang_suites(
        tmp_path,
        '[[cases]]\nname = "first"\nsetup = [\'M.qa.where("QA Spy")\']\nexpect = [{ log = "qa: where ok:" }]\n',
    )
    harness = FakeHarness(turn_root)
    state = {"dialog": False}

    def crash_after_skill(h: FakeHarness, line: str) -> str:
        if "M.qa.skill(" in line:
            h.append_log("qa: skill ok: QA Spy GoodSpy=5")
            state["dialog"] = True
            return "QA Spy GoodSpy=5"
        if "M.qa.load(" in line:
            h.append_log("qa: load ok: mods/parley/saves/parley_keep_scratch.sav")
            h.append_log("bridge loaded campaign at turn 10")
            return "mods/parley/saves/parley_keep_scratch.sav"
        return "ok"

    def dialog_up() -> bool:
        if "relaunch_game" in harness.events:
            return False
        return state["dialog"]

    harness.on_lua = crash_after_skill
    results, _ = _run_hang_suite(
        harness, real_toml, suites_dir, tmp_path, crash_dialog_up=dialog_up, dialog_confirm_seconds=0.01
    )
    assert [(r.name, r.outcome) for r in results] == [("skill", "pass"), ("first", "fail")]
    assert "crash dialog" in results[1].evidence
    assert "relaunch_game" in harness.events


def test_process_manager_default_dialog_check_is_off_for_injected_doubles(tmp_path: Path):
    # tests that inject is_game_running must never look at the real X display
    real_toml, turn_root, save_dir = _write_real_game(tmp_path)
    _lock(turn_root, save_dir)
    harness = FakeHarness(turn_root)
    harness.append_log("autoplay: turn 10, waiting for england")
    called = []
    orig = _ProcessManager.crash_dialog_up
    _ProcessManager.crash_dialog_up = lambda self: called.append(1) or True  # type: ignore[method-assign]
    try:
        assert _restore_hang(harness, real_toml) is True
    finally:
        _ProcessManager.crash_dialog_up = orig  # type: ignore[method-assign]
    assert called == []
    assert "relaunch_game" not in harness.events


# --- after a relaunch, put the real campaign back when Continue Campaign took the QA game's save ---

def _after_relaunch_setup(tmp_path: Path, *, autosave_newer: bool = False):
    from parley.qa.runner import LAST_RESTORE_FILE

    _, turn_root, save_dir = _write_real_game(tmp_path)
    qa_autosave = save_dir / "Autosave.sav"  # the QA game's, from before the restore
    qa_autosave.write_bytes(b"qa-turn-45")
    os.utime(qa_autosave, (1000.0, 1000.0))
    old = save_dir / "parley_keep_scratch.restored-20261030-180000.sav"
    old.write_bytes(b"real-turn-30")
    os.utime(old, (500.0, 500.0))
    keep = save_dir / "parley_keep_scratch.restored-20261030-201000.sav"
    keep.write_bytes(b"real-turn-41")
    os.utime(keep, (900.0, 900.0))
    (turn_root / LAST_RESTORE_FILE).write_text(json.dumps({"newest_save_mtime": 1000.0}), encoding="utf-8")
    if autosave_newer:
        os.utime(qa_autosave, (1100.0, 1100.0))  # the real game has autosaved since
    harness = FakeHarness(turn_root)
    harness.append_log("bridge loaded campaign at turn 41")  # before the crash: not this launch
    return turn_root, harness


def _after_relaunch(turn_root: Path, harness: FakeHarness, offset: int, **kw) -> str:
    from parley.qa.runner import resume_real_after_relaunch

    return resume_real_after_relaunch(
        turn_root,
        log_offset=offset,
        control_factory=harness.control_factory,
        timeout=kw.pop("timeout", 2.0),
        poll_interval=0.01,
        **kw,
    )


def test_after_relaunch_loads_the_restored_keep_once_the_campaign_is_up(tmp_path: Path):
    turn_root, harness = _after_relaunch_setup(tmp_path)
    offset = harness.log_offset()
    harness.append_log("bridge loaded campaign at turn 0")  # the main menu
    harness.append_log("bridge loaded campaign at turn 45")  # Continue Campaign: the QA game
    msg = _after_relaunch(turn_root, harness, offset)
    assert harness.lua_calls == [
        'return M.qa.load("mods/parley/saves/parley_keep_scratch.restored-20261030-201000.sav")'
    ]
    assert "parley_keep_scratch.restored-20261030-201000.sav" in msg
    assert "turn 45" in msg


def test_after_relaunch_waits_past_the_main_menu_and_the_old_log(tmp_path: Path):
    from parley.qa.runner import QARunError

    turn_root, harness = _after_relaunch_setup(tmp_path)
    offset = harness.log_offset()
    harness.append_log("bridge loaded campaign at turn 0")
    with pytest.raises(QARunError, match="bridge loaded campaign at turn N"):
        _after_relaunch(turn_root, harness, offset, timeout=0.1)
    assert harness.lua_calls == []


def test_after_relaunch_leaves_a_real_autosave_alone(tmp_path: Path):
    turn_root, harness = _after_relaunch_setup(tmp_path, autosave_newer=True)
    offset = harness.log_offset()
    harness.append_log("bridge loaded campaign at turn 42")
    msg = _after_relaunch(turn_root, harness, offset)
    assert harness.lua_calls == []
    assert "Autosave.sav" in msg


def test_after_relaunch_does_nothing_without_a_restore_or_during_a_qa_run(tmp_path: Path):
    from parley.qa.runner import LAST_RESTORE_FILE, LOCK_FILE

    turn_root, harness = _after_relaunch_setup(tmp_path)
    offset = harness.log_offset()
    harness.append_log("bridge loaded campaign at turn 45")
    (turn_root / LOCK_FILE).write_text("{}", encoding="utf-8")  # the bench or its restore owns the game
    assert "qa.lock" in _after_relaunch(turn_root, harness, offset)
    (turn_root / LOCK_FILE).unlink()
    (turn_root / LAST_RESTORE_FILE).unlink()
    _after_relaunch(turn_root, harness, offset)
    assert harness.lua_calls == []


def test_after_relaunch_reports_a_failed_load(tmp_path: Path):
    from parley.qa.runner import QARunError

    turn_root, harness = _after_relaunch_setup(tmp_path)
    offset = harness.log_offset()
    harness.append_log("bridge loaded campaign at turn 45")

    def fail(h: FakeHarness, line: str) -> str:
        h.append_log("qa: load failed: no such file")
        return "nil (error)"

    harness.on_lua = fail
    with pytest.raises(QARunError, match="load"):
        _after_relaunch(turn_root, harness, offset)


def test_cli_after_relaunch_without_a_restore_is_a_no_op(tmp_path: Path, capsys):
    turn_root = tmp_path / "parley_turns"
    turn_root.mkdir()
    assert qa_main(["after-relaunch", "--turn-root", str(turn_root), "--log-offset", "0"]) == 0
    assert "no QA restore" in capsys.readouterr().out


def _hang_suites(tmp_path: Path, covert_cases: str) -> Path:
    suites_dir = tmp_path / "suites"
    suites_dir.mkdir()
    (suites_dir / "smoke.toml").write_text(
        'name = "smoke"\nfaction = "england"\n\n'
        '[[cases]]\nname = "skill"\n'
        'setup = [\'M.qa.skill("QA Spy", "GoodSpy", 5)\']\n'
        'expect = [{ log = "qa: skill ok:" }]\n',
        encoding="utf-8",
    )
    (suites_dir / "covert.toml").write_text(
        'name = "covert"\nfaction = "england"\n\n' + covert_cases, encoding="utf-8"
    )
    return suites_dir


def _run_hang_suite(harness: FakeHarness, real_toml: Path, suites_dir: Path, tmp_path: Path, **kw):
    return run_suite(
        "covert",
        real_toml,
        suites_dir=suites_dir,
        report_dir=tmp_path / "runs" / "qa",
        control_factory=harness.control_factory,
        advance_turn=harness.advance_turn,
        is_game_running=harness.is_game_running,
        relaunch_game=harness.relaunch_game,
        stop_loop=harness.stop_loop,
        stop_crash_watch=harness.stop_crash_watch,
        start_qa_loop=harness.start_qa_loop,
        start_real=harness.start_real,
        start_crash_watch=harness.start_crash_watch,
        poll_interval=0.01,
        **kw,
    )


def test_hung_game_before_a_case_fails_it_and_restore_relaunches(tmp_path: Path):
    real_toml, turn_root, save_dir = _write_real_game(tmp_path)
    (save_dir / "Autosave.sav").write_bytes(b"save-turn-10")
    _write_state(turn_root, "scratch", 10)
    suites_dir = _hang_suites(
        tmp_path,
        '[[cases]]\nname = "first"\nsetup = [\'M.qa.where("QA Spy")\']\nexpect = [{ log = "qa: where ok:" }]\n\n'
        '[[cases]]\nname = "second"\nsetup = [\'M.qa.where("QA Spy")\']\nexpect = [{ log = "qa: where ok:" }]\n',
    )
    harness = FakeHarness(turn_root)

    def hang_after_skill(h: FakeHarness, line: str) -> str:
        if "M.qa.skill(" in line:
            h.append_log("qa: skill ok: QA Spy GoodSpy=5")
            h.append_log("popup papal_election_results")
            _age_log(h.log_path, 300)  # silent since: the game froze on the scroll
            return "QA Spy GoodSpy=5"
        if "M.qa.load(" in line:
            h.append_log("qa: load ok: mods/parley/saves/parley_keep_scratch.sav")
            h.append_log("bridge loaded campaign at turn 10")
            return "mods/parley/saves/parley_keep_scratch.sav"
        if "M.qa.where(" in line:
            h.append_log("qa: where ok: 110,154")
            return "110,154"
        return "ok"

    harness.on_lua = hang_after_skill
    results, report = _run_hang_suite(harness, real_toml, suites_dir, tmp_path)

    assert [(r.name, r.outcome) for r in results] == [("skill", "pass"), ("first", "fail")]
    assert results[1].evidence.startswith("game hung at ")
    assert results[1].evidence.endswith("popup papal_election_results")
    assert not any("M.qa.where(" in c for c in harness.lua_calls)  # no case ran on the hung game
    relaunch_idx = harness.events.index("relaunch_game")
    load_idx = next(i for i, e in enumerate(harness.events) if "M.qa.load(" in e)
    assert relaunch_idx < load_idx < harness.events.index("start_real:scratch")
    assert "start_crash_watch" in harness.events
    assert not (turn_root / "qa.lock").exists()
    assert "game hung at" in report.read_text(encoding="utf-8")


def test_hang_while_waiting_for_a_cases_turns_fails_it(tmp_path: Path):
    real_toml, turn_root, save_dir = _write_real_game(tmp_path)
    (save_dir / "Autosave.sav").write_bytes(b"save-turn-10")
    _write_state(turn_root, "scratch", 10)
    suites_dir = _hang_suites(
        tmp_path,
        '[[cases]]\nname = "marches"\nmax_turns = 4\n'
        'expect = [{ log = "never logged" }]\n'
        '[cases.orders]\n1 = [{ type = "move_army", army = "x", x = 1, y = 1 }]\n',
    )
    harness = FakeHarness(turn_root)

    def freeze(h: FakeHarness, game_id: str, faction: str, turn: int) -> None:
        _write_state(h.turn_root, game_id, turn, faction)
        if turn >= 12:
            h.append_log("popup papal_election_results")
            _age_log(h.log_path, 300)

    harness.on_advance = freeze
    results, _ = _run_hang_suite(harness, real_toml, suites_dir, tmp_path)

    by_name = {r.name: r for r in results}
    assert by_name["marches"].outcome == "fail"
    assert by_name["marches"].evidence.startswith("game hung at ")
    advances = [e for e in harness.events if e.startswith("advance:qa-covert")]
    assert len(advances) == 2  # stopped waiting once the game hung, not after max_turns
    assert "relaunch_game" in harness.events
    assert not (turn_root / "qa.lock").exists()


def test_default_advance_stops_on_a_hung_game(tmp_path: Path):
    from parley.qa.runner import _default_advance_turn

    turn_root = tmp_path / "parley_turns"
    turn_root.mkdir()
    advance = _default_advance_turn(
        turn_root, lambda: "game hung at 18:34:11: popup", timeout=5.0, poll_interval=0.01
    )
    with pytest.raises(QARunError, match="game hung at 18:34:11"):
        advance("qa-covert", "england", 10)


def test_default_advance_timeout_waits_for_a_hang_verdict(tmp_path: Path):
    """The turn wait (180 s) is shorter than the hang threshold: a timeout on a silent bridge waits
    until the detector can say whether the game hung."""
    from parley.qa.runner import _default_advance_turn, game_trouble

    turn_root = tmp_path / "parley_turns"
    turn_root.mkdir()
    log = turn_root / "parley_bridge.log"
    log.write_text("2026-10-30 18:34:11 popup papal_election_results\n")
    advance = _default_advance_turn(
        turn_root,
        lambda: game_trouble(lambda: True, log, hang_seconds=0.3),
        timeout=0.05,
        poll_interval=0.01,
        hang_seconds=0.3,
    )
    with pytest.raises(QARunError, match="game hung at"):
        advance("qa-covert", "england", 10)


def _lock(turn_root: Path, save_dir: Path) -> Path:
    keep_path = save_dir / "parley_keep_scratch.sav"
    keep_path.write_bytes(b"kept-save-data")
    lock_path = turn_root / "qa.lock"
    lock_path.write_text(json.dumps({"game_id": "scratch", "turn": 10, "log_offset": 0}), encoding="utf-8")
    return lock_path


def _restore_hang(harness: FakeHarness, real_toml: Path, **kw):
    return restore(
        real_toml,
        control_factory=harness.control_factory,
        is_game_running=harness.is_game_running,
        relaunch_game=harness.relaunch_game,
        stop_loop=harness.stop_loop,
        stop_crash_watch=harness.stop_crash_watch,
        start_real=harness.start_real,
        start_crash_watch=harness.start_crash_watch,
        poll_interval=0.01,
        **kw,
    )


def test_restore_relaunches_a_hung_game_before_the_load(tmp_path: Path):
    real_toml, turn_root, save_dir = _write_real_game(tmp_path)
    lock_path = _lock(turn_root, save_dir)
    harness = FakeHarness(turn_root)  # the process is alive
    harness.append_log("popup papal_election_results")
    _age_log(harness.log_path, 300)

    assert _restore_hang(harness, real_toml) is True

    relaunch_idx = harness.events.index("relaunch_game")
    load_idx = next(i for i, e in enumerate(harness.events) if "M.qa.load(" in e)
    assert relaunch_idx < load_idx < harness.events.index("start_real:scratch")
    assert not lock_path.exists()


def test_restore_relaunch_without_a_campaign_load_keeps_the_lock(tmp_path: Path):
    real_toml, turn_root, save_dir = _write_real_game(tmp_path)
    lock_path = _lock(turn_root, save_dir)
    harness = FakeHarness(turn_root, game_running=False)

    def relaunch_no_campaign() -> None:
        harness.events.append("relaunch_game")
        harness.game_running = True  # the game started but never reached the campaign map

    with pytest.raises(QARunError, match="restore failed at loaded; lock kept") as ei:
        restore(
            real_toml,
            control_factory=harness.control_factory,
            is_game_running=harness.is_game_running,
            relaunch_game=relaunch_no_campaign,
            stop_loop=harness.stop_loop,
            start_real=harness.start_real,
            start_crash_watch=harness.start_crash_watch,
            poll_interval=0.01,
            relaunch_timeout=0.1,
        )
    assert "bridge loaded campaign" in str(ei.value)
    assert not any("M.qa.load(" in c for c in harness.lua_calls)
    assert lock_path.exists()
    assert "start_real:scratch" not in harness.events


def test_restore_load_timeout_on_a_hung_game_relaunches_and_retries_once(tmp_path: Path):
    real_toml, turn_root, save_dir = _write_real_game(tmp_path)
    lock_path = _lock(turn_root, save_dir)
    harness = FakeHarness(turn_root)
    harness.append_log("autoplay: turn 10")  # fresh: not hung yet when the restore starts
    loads = []

    def hang_on_first_load(h: FakeHarness, line: str) -> str:
        if "M.qa.load(" in line:
            loads.append(line)
            if len(loads) == 1:
                raise ControlTimeout("timed out after 30.0s waiting for bridge response")
            h.append_log("qa: load ok: mods/parley/saves/parley_keep_scratch.sav")
            h.append_log("bridge loaded campaign at turn 10")
            return "mods/parley/saves/parley_keep_scratch.sav"
        return "ok"

    harness.on_lua = hang_on_first_load
    assert _restore_hang(harness, real_toml, hang_seconds=0.2) is True

    assert len(loads) == 2
    first_load = next(i for i, e in enumerate(harness.events) if "M.qa.load(" in e)
    relaunch_idx = harness.events.index("relaunch_game")
    assert first_load < relaunch_idx
    assert not lock_path.exists()


def test_restore_load_timeout_on_a_live_bridge_does_not_relaunch(tmp_path: Path):
    real_toml, turn_root, save_dir = _write_real_game(tmp_path)
    lock_path = _lock(turn_root, save_dir)
    harness = FakeHarness(turn_root)
    harness.append_log("autoplay: turn 10")

    def timeout_but_logging(h: FakeHarness, line: str) -> str:
        if "M.qa.load(" in line:
            h.append_log("autoplay: turn 10, waiting for england (60s of 60)")  # the bridge lives
            raise ControlTimeout("timed out after 30.0s waiting for bridge response")
        return "ok"

    harness.on_lua = timeout_but_logging
    with pytest.raises(QARunError, match="restore failed at loaded; lock kept"):
        _restore_hang(harness, real_toml, hang_seconds=5.0)
    assert "relaunch_game" not in harness.events
    assert sum("M.qa.load(" in c for c in harness.lua_calls) == 1
    assert lock_path.exists()


def test_restore_retry_that_times_out_again_keeps_the_lock(tmp_path: Path):
    real_toml, turn_root, save_dir = _write_real_game(tmp_path)
    lock_path = _lock(turn_root, save_dir)
    harness = FakeHarness(turn_root)
    harness.append_log("autoplay: turn 10")

    def dead_on_load(h: FakeHarness, line: str) -> str:
        if "M.qa.load(" in line:
            h.game_running = False
            raise ControlTimeout("timed out after 30.0s waiting for bridge response")
        return "ok"

    harness.on_lua = dead_on_load
    with pytest.raises(QARunError, match="restore failed at loaded; lock kept"):
        _restore_hang(harness, real_toml)
    assert harness.events.count("relaunch_game") == 1
    assert sum("M.qa.load(" in c for c in harness.lua_calls) == 2
    assert lock_path.exists()
    assert "start_real:scratch" not in harness.events


# --- live 10-30 19:09: the main menu's turn-0 campaign is not the campaign ----------------------------


def test_restore_relaunch_waits_past_the_main_menus_turn_0_campaign(tmp_path: Path):
    """Live 10-30 19:09: after the hang-recovery relaunch the main menu's background map logged
    "bridge loaded campaign at turn 0"; the restore took it for the campaign, sent M.qa.load from the
    menu and the game crashed on the loading screen. Continue Campaign logs the real turn after it
    (19:13:59 turn 0, 19:14:35 turn 43)."""
    import threading

    real_toml, turn_root, save_dir = _write_real_game(tmp_path)
    lock_path = _lock(turn_root, save_dir)
    harness = FakeHarness(turn_root, game_running=False)
    loaded_at: list[str] = []

    def relaunch_menu_then_campaign() -> None:
        harness.events.append("relaunch_game")
        harness.game_running = True
        harness.append_log("bridge loaded campaign at turn 0")  # the main menu's map
        threading.Timer(0.2, lambda: harness.append_log("bridge loaded campaign at turn 43")).start()

    def on_lua(h: FakeHarness, line: str) -> str:
        if "M.qa.load(" in line:
            loaded_at.append(h.log_path.read_text(encoding="utf-8"))
            h.append_log("qa: load ok: mods/parley/saves/parley_keep_scratch.sav")
            h.append_log("bridge loaded campaign at turn 10")
            return "mods/parley/saves/parley_keep_scratch.sav"
        return "ok"

    harness.on_lua = on_lua
    assert restore(
        real_toml,
        control_factory=harness.control_factory,
        is_game_running=harness.is_game_running,
        relaunch_game=relaunch_menu_then_campaign,
        stop_loop=harness.stop_loop,
        stop_crash_watch=harness.stop_crash_watch,
        start_real=harness.start_real,
        start_crash_watch=harness.start_crash_watch,
        poll_interval=0.01,
        relaunch_timeout=5.0,
    )
    assert len(loaded_at) == 1
    assert "bridge loaded campaign at turn 43" in loaded_at[0]  # not sent from the menu
    assert not lock_path.exists()


def test_restore_relaunch_that_only_reaches_the_main_menu_never_loads(tmp_path: Path):
    real_toml, turn_root, save_dir = _write_real_game(tmp_path)
    lock_path = _lock(turn_root, save_dir)
    harness = FakeHarness(turn_root, game_running=False)

    def relaunch_menu_only() -> None:
        harness.events.append("relaunch_game")
        harness.game_running = True
        harness.append_log("bridge loaded campaign at turn 0")

    with pytest.raises(QARunError, match="restore failed at loaded; lock kept") as ei:
        restore(
            real_toml,
            control_factory=harness.control_factory,
            is_game_running=harness.is_game_running,
            relaunch_game=relaunch_menu_only,
            stop_loop=harness.stop_loop,
            start_real=harness.start_real,
            start_crash_watch=harness.start_crash_watch,
            poll_interval=0.01,
            relaunch_timeout=0.2,
        )
    assert "bridge loaded campaign at turn N" in str(ei.value) and "N > 0" in str(ei.value)
    assert not any("M.qa.load(" in c for c in harness.lua_calls)
    assert lock_path.exists()


def test_confirm_load_skips_a_turn_0_menu_map_and_names_the_line_it_waits_for(tmp_path: Path):
    log_path = tmp_path / "parley_bridge.log"
    log_path.write_text(
        "2026-10-30 18:37:43 bridge loaded campaign at turn 0\n"
        "2026-10-30 18:37:45 qa: load ok: mods/parley/saves/parley_keep_scratch.sav\n"
        "2026-10-30 18:38:30 bridge loaded campaign at turn 32\n",
        encoding="utf-8",
    )
    _confirm_load("ok", log_path, 0, expected_turn=32, timeout=0.05, poll_interval=0.01)

    log_path.write_text(
        "2026-10-30 19:09:16 bridge loaded campaign at turn 0\n"
        "2026-10-30 19:09:48 qa: load ok: mods/parley/saves/parley_keep_scratch.sav\n",
        encoding="utf-8",
    )
    with pytest.raises(QARunError) as ei:
        _confirm_load("ok", log_path, 0, expected_turn=32, timeout=0.05, poll_interval=0.01)
    msg = str(ei.value)
    assert "bridge loaded campaign at turn N" in msg and "N > 0" in msg
    assert "bridge reloaded" not in msg


# --- live 10-30 18:52 covert run ---------------------------------------------------------------------

# qa-covert/turn-0044/england/state.json of the 18:52 run, trimmed to what targeting reads
_LIVE_TURN44 = {
    "turn": 44,
    "visible_enemies": [{"id": "Edmund Canmore", "faction": "scotland", "x": 98, "y": 180, "distance": 6}],
    "seen_agents": [
        {"id": "Patrick Macdougall", "kind": "diplomat", "faction": "scotland", "x": 105, "y": 165, "distance": 1},
        {"id": "Vico de Bronzo", "kind": "diplomat", "faction": "milan", "x": 114, "y": 143, "distance": 5},
        {"id": "Iacobus Bandini", "kind": "other", "faction": "papal_states", "x": 106, "y": 104, "distance": 30},
    ],
    "agents": [{"id": "Simon Awood", "kind": "spy", "x": 102, "y": 174}],
    "nearby_settlements": [
        {"id": "Edinburgh", "name": "Edinburgh", "faction": "scotland", "x": 102, "y": 174, "distance": 0},
        {"id": "Caen", "name": "Caen", "faction": "france", "x": 104, "y": 134, "distance": 2},
        {"id": "Inverness", "name": "Inverness", "faction": "scotland", "x": 99, "y": 181, "distance": 7},
    ],
}


def _covert_case(name: str):
    from parley.qa.cases import load_suite
    from parley.qa.runner import DEFAULT_SUITES_DIR

    return {c.name: c for c in load_suite(DEFAULT_SUITES_DIR / "covert.toml").cases}[name]


def _rendered_setup(case, targets: dict) -> list[str]:
    from parley.qa.runner import _setup_lua, _substitute_str

    return [_substitute_str(_setup_lua(s), targets) for s in case.setup]


def test_covert_spy_spawns_on_a_free_tile_beside_the_town_and_spies_once():
    """Live 10-30 18:52: the spy spawned on the unchecked tile diagonal to Edinburgh, spied it on its
    first order turn (turn 41: "Simon Awood's spying: partly successful") and so stood inside the
    town; the case's repeat orders on turns 42-44 were refused "'Simon Awood' is already inside
    Edinburgh", and order_ok read the last one."""
    spy = _covert_case("spy_report_closed")
    # the town is picked on the whole map now (M.qa.hostile_town), its tile bound by M.qa.town
    targets = {**pick_targets(_LIVE_TURN44), "hostile": "Edinburgh", "hostile_at": "102,174",
               "hostile_at_x": 102, "hostile_at_y": 174}
    setup = _rendered_setup(spy, targets)
    assert setup[2] == "return M.qa.free_tile(102, 174, 1, 1)"  # a free land tile next to the town
    assert spy.setup[2].bind == "at"
    assert spy.setup[3].lua.startswith("return M.qa.spawn_agent(") and "$at_x, $at_y" in spy.setup[3].lua
    assert list(spy.orders) == [1]  # one mission: a spy that got in can't spy the same town again
    assert spy.orders[1] == [{"type": "spy", "agent": "$spy", "target": "$hostile"}]
    assert spy.max_turns >= 2  # the order's turn and the report after it
    assert spy.chance  # a roll: no success inside max_turns is inconclusive


def test_field_march_on_army_has_infantry_to_besiege():
    """Live 10-30 21:23: the one-unit army (a general's bodyguard, cavalry) beside Bruges was refused by
    the game's canStartSiege; a siege needs infantry to build equipment (live 18:31 the same kind of army
    besieged Dublin). The case's army is a general leading infantry."""
    from parley.qa.cases import load_suite
    from parley.qa.runner import DEFAULT_SUITES_DIR

    case = next(c for c in load_suite(DEFAULT_SUITES_DIR / "field.toml").cases if c.name == "march_on_besieges")
    spawn = next(s for s in case.setup if not isinstance(s, str) and "spawn_army" in s.lua)
    assert spawn.lua == 'return M.qa.spawn_army("england", $next_x, $next_y, nil, "Peasants")'


def _setup_lua_of(step):
    return step if isinstance(step, str) else step.lua


def test_covert_assassin_has_a_victim_that_stays_put():
    """Live 10-30 18:52 and 21:38: a victim picked from the sight lists walked off before the order
    ran (21:38: the rebel army Captain Lopo at (107,131) was out of sight a turn later, and the turn
    after nobody but fleets was in sight, so `$nearest_character_to:Walter Canton` stayed unfilled).
    The case spawns its own victim (tired, with every AI frozen) and the assassin beside it, and
    orders the assassination once, at the next turn start."""
    case = _covert_case("assassinate")
    # a turn case again since 10-31's phase 1 (no mission line in a held turn): one order, at the
    # next turn start; the victim is frozen with every AI and tired besides
    assert case.kind == "turn" and list(case.orders) == [1] and not case.act
    assert case.setup[0].bind == "victim_at"
    assert case.setup[1].lua == 'return M.qa.spawn_army("slave", $victim_at_x, $victim_at_y)'
    assert case.setup[1].bind == "victim"
    assert case.setup[2] == 'return M.qa.tire("slave", "$victim")'
    assert case.setup[3].lua == "return M.qa.free_tile($victim_at_x, $victim_at_y, 1, 1)"
    assert "$at_x, $at_y" in case.setup[4].lua and case.setup[4].bind == "assassin"
    assert not case.needs  # the rebels stay frozen


def test_covert_assassin_targets_the_victim_england_sees_by_its_sight_id():
    """Live 10-30 22:03: the rebel victim Esau stood at (106,144), the assassin beside it at (105,143),
    but England's sight lists never held Esau, so `$nearest_character_to:` picked the next nearest
    (an HRE agent at (108,128), across the Channel) and the order was refused as across the sea.
    The victim now goes on a tile England sees (M.qa.seen_tile, walkable from the town), the assassin
    beside it on the same landmass, and setup fails loudly unless England's sight holds the victim
    (M.qa.sees binds its sight id, which the orders name)."""
    case = _covert_case("assassinate")
    assert case.setup[0].lua == 'return M.qa.seen_tile("england", $garrison_town_x, $garrison_town_y, 3, 4)'
    sees = [s for s in case.setup if "M.qa.sees(" in _setup_lua_of(s)]
    assert len(sees) == 1 and sees[0].bind == "victim_id"
    assert sees[0].lua == 'return M.qa.sees("england", $victim_at_x, $victim_at_y)'
    assert case.setup.index(sees[0]) > 4  # after the assassin, whose eyes count too
    assert case.orders[1] == [{"type": "assassinate", "agent": "$assassin", "target": "$victim_id"}]


def test_a_run_moves_an_earlier_runs_answers_out_of_the_qa_game_before_the_bridge_sees_them(tmp_path: Path):
    """Live 10-30 18:55:50: with the QA loop stopped for the assassin's setup, the bridge started
    turn 45 and found qa-covert/turn-0044/england/orders.json from the 18:15 run ("england order 0
    spy: unknown agent 'Toby of Eynsham'"), applied it, and ended turn 45 at once ("autoplay: ending
    turn 45") while setup was still spawning: the target walked off. The QA game's turn folders are
    reused run to run; an earlier run's answers must be gone before the bridge plays the QA game."""
    harness, game, real_toml, suites_dir = _covert_game(
        tmp_path, _COVERT_HEAD + _ASSASSIN_CASE, _spy_then_assassin)
    old = harness.turn_root / "qa-covert" / "turn-0011" / "england"
    old.mkdir(parents=True)
    (old / "state.json").write_text("{}", encoding="utf-8")
    (old / "orders.json").write_text(json.dumps({"orders": [{"type": "spy", "agent": "Toby of Eynsham"}]}),
                                     encoding="utf-8")
    for p in (old / "state.json", old / "orders.json", old, old.parent):  # an earlier run's, before the save
        os.utime(p, (1_000_000_000, 1_000_000_000))
    published: list[bool] = []
    real_start = harness.start_qa_loop

    def start_qa_loop(qa_toml: Path) -> None:
        # the bridge plays the QA game from the moment its config is published, before this
        published.append((old / "orders.json").exists())
        real_start(qa_toml)

    harness.start_qa_loop = start_qa_loop
    results, _ = _run_with(harness, "covert", real_toml, suites_dir, tmp_path / "runs" / "qa")
    assert published and not any(published)
    kept = list((harness.turn_root / "qa-archive").glob("qa-covert-*/turn-0011/england/orders.json"))
    assert len(kept) == 1  # kept for diagnosis, out of the bridge's way
    assert [(r.name, r.outcome) for r in results] == [("assassinate", "pass")], results


def test_qa_config_turns_the_papal_hands_off_switch_on(tmp_path: Path):
    # the bench runs the papal crash experiment (turns 59/62 of the field suite); the real game
    # keeps its own config (restore publishes it back)
    from types import SimpleNamespace
    from parley.config import load_config
    real_toml, _, _ = _write_real_game(tmp_path)
    plan = tmp_path / "plan.json"
    plan.write_text("{}\n", encoding="utf-8")
    out = write_qa_config(real_toml, SimpleNamespace(name="field", faction="england"), plan, tmp_path / "qa.toml")
    assert load_config(out).autoplay.papal_hands_off is True
    assert load_config(real_toml).autoplay.papal_hands_off is True  # the default for every game now


def test_field_spawns_go_beside_a_town_never_on_it():
    """QA field 10-30 23:49-00:03: home_x/home_y is a town's own tile (#291), and an army spawned on a
    town's tile is its garrison, not the field army the case looks for ("armies[id=Simon Townsend]
    not found"). Every spawned army stands on a tile a free_tile (or seen_tile) step found, at least
    one tile out (free_tile skips towns and occupied tiles); only M.qa.garrison puts one in a town,
    and M.qa.spawn_army refuses a town's tile (test_lua_bridge)."""
    import re

    from parley.qa.cases import load_suite
    from parley.qa.runner import DEFAULT_SUITES_DIR

    # the faction named, or bound by setup ("$rival": envoys.toml's suitor)
    spawn_re = re.compile(r"M\.qa\.spawn_army\(\s*\"\$?[a-z_]+\"\s*,\s*\$([a-z_]+)_x\s*,\s*\$([a-z_]+)_y")
    # M.qa.shore (navy) is a free_tile with a free sea tile beside it
    tile_re = re.compile(r"M\.qa\.(?:free_tile|seen_tile|shore)\((?:\"[a-z_]+\",\s*)?[^,]+,[^,]+,\s*(\d+)")
    seen = 0
    for path in sorted(DEFAULT_SUITES_DIR.glob("*.toml")):
        for case in load_suite(path).cases:
            free: set[str] = set()
            for step in case.setup:
                code = _setup_lua_of(step)
                bind = None if isinstance(step, str) else step.bind
                if "spawn_army" in code:
                    m = spawn_re.search(code)
                    assert m and m.group(1) == m.group(2), (path.name, case.name, code)
                    assert m.group(1) in free, (path.name, case.name, f"spawn on ${m.group(1)}: not a free tile")
                    seen += 1
                t = tile_re.search(code)
                if t and bind:
                    assert int(t.group(1)) >= 1, (path.name, case.name, code)
                    free.add(bind)
    assert seen >= 6


# --- instant cases: setup, act and check by control lines inside one held turn -------------------

def _instant_game(tmp_path: Path, cases_toml: str, *, smoke_cases: str | None = None):
    real_toml, turn_root, save_dir = _write_real_game(tmp_path)
    (save_dir / "Autosave.sav").write_bytes(b"save-turn-10")
    _write_state(turn_root, "scratch", 10)
    suites_dir = tmp_path / "suites"
    suites_dir.mkdir()
    (suites_dir / "smoke.toml").write_text(
        'name = "smoke"\nfaction = "england"\n\n' + (smoke_cases if smoke_cases is not None else
        '[[cases]]\nname = "skill"\nsetup = [\'M.qa.skill("QA Spy", "GoodSpy", 5)\']\n'
        'expect = [{ log = "qa: skill ok:" }]\n'),
        encoding="utf-8",
    )
    (suites_dir / "instant.toml").write_text('name = "instant"\nfaction = "england"\n\n' + cases_toml,
                                             encoding="utf-8")
    return real_toml, turn_root, suites_dir


def _run_instant(tmp_path: Path, harness: FakeHarness, real_toml: Path, suites_dir: Path, suite="instant", **kw):
    return run_suite(
        suite,
        real_toml,
        suites_dir=suites_dir,
        report_dir=tmp_path / "runs" / "qa",
        control_factory=harness.control_factory,
        advance_turn=harness.advance_turn,
        is_game_running=harness.is_game_running,
        relaunch_game=harness.relaunch_game,
        stop_loop=harness.stop_loop,
        stop_crash_watch=harness.stop_crash_watch,
        start_qa_loop=harness.start_qa_loop,
        stop_qa_loop=harness.stop_qa_loop,
        start_real=harness.start_real,
        start_crash_watch=harness.start_crash_watch,
        poll_interval=0.01,
        instant_turn_wait=0.3,
        **kw,
    )


WALK_CASE = (
    '[[cases]]\nname = "walk_out"\nkind = "instant"\n'
    'setup = [{ lua = \'return M.qa.free_tile(5, 5, 1, 1)\', bind = "next" }]\n'
    'act = [\'return M.qa.walk("Robert", $next_x, $next_y)\']\n'
    'expect = [{ lua = \'return M.qa.status("Robert")\', match = "^$next_x,$next_y .*town=-$", within = 0.3 }]\n'
)


class _Walker:
    """The game side of WALK_CASE: Robert shows on his new tile `lag` status reads after the walk;
    `own_turn_after` M.qa.current() reads say it's France's turn first."""

    def __init__(self, lag: int = 0, tile: str = "6,6", own_turn_after: int = 0):
        self.lag, self.tile, self.own_turn_after = lag, tile, own_turn_after
        self.walked = False
        self.held: list[tuple[str, bool]] = []  # each line, and whether the turn was held as it ran

    def __call__(self, h: FakeHarness, line: str) -> str:
        self.held.append((line, (h.turn_root / "paused.txt").exists()))
        if "M.qa.current()" in line:
            if self.own_turn_after > 0:
                self.own_turn_after -= 1
                return "france 10"
            return "england 10"
        if "M.qa.free_tile(" in line:
            h.append_log("qa: free_tile ok: 6,6")
            return "6,6"
        if "M.qa.walk(" in line:
            self.walked = True
            h.append_log("qa: walk ok: split from Caen")
            return "split from Caen"
        if "M.qa.status(" in line:
            if self.walked and self.lag <= 0:
                out = f"{self.tile} moves=10 town=-"
            else:
                self.lag -= int(self.walked)
                out = "5,5 moves=12 town=Caen"
            h.append_log(f"qa: status ok: {out}")
            return out
        return _default_lua(h, line)


def _default_lua(h: FakeHarness, line: str) -> str:
    """What the harness answers with no on_lua (smoke's skill, the restore's load), recorded once."""
    saved, h.on_lua = h.on_lua, None
    try:
        return h.run_lua(line)
    finally:
        h.on_lua = saved
        h.lua_calls.pop()
        h.events.pop()


def test_instant_case_passes_when_its_query_comes_right_and_never_ends_a_turn(tmp_path: Path):
    real_toml, turn_root, suites_dir = _instant_game(tmp_path, WALK_CASE)
    harness = FakeHarness(turn_root)
    game = _Walker(lag=2, own_turn_after=1)  # the tile lags the walk (live run9); France's turn first
    harness.on_lua = game
    results, report = _run_instant(tmp_path, harness, real_toml, suites_dir, cases=["walk_out"])

    assert [(r.name, r.outcome) for r in results] == [("skill", "pass"), ("walk_out", "pass")], results
    walk = results[1]
    assert walk.turns == 0 and "6,6 moves=10 town=-" in walk.evidence and "split from Caen" in walk.evidence
    # nothing advanced a turn after smoke, and the QA loop wasn't restarted; it was stopped first
    i = harness.events.index("lua:return M.qa.current()")
    assert not any(e.startswith(("advance:", "start_qa_loop")) for e in harness.events[i:]), harness.events
    assert "stop_qa_loop" in harness.events[:i]
    # every line of the case ran with the turn held; the hold is gone afterwards
    first = next(i for i, (line, _) in enumerate(game.held) if "M.qa.current()" in line)
    case_lines = [(line, held) for line, held in game.held[first:] if "M.qa.load(" not in line]
    assert len(case_lines) >= 6 and all(held for _, held in case_lines), case_lines
    assert not (turn_root / "paused.txt").exists()
    assert walk.seconds is not None and "| walk_out | pass | 0 |" in report.read_text()
    assert "Total: " in report.read_text()


def test_instant_case_fails_with_the_value_it_saw(tmp_path: Path):
    real_toml, turn_root, suites_dir = _instant_game(tmp_path, WALK_CASE)
    harness = FakeHarness(turn_root)
    harness.on_lua = _Walker(tile="7,7")  # he went somewhere else
    results, _ = _run_instant(tmp_path, harness, real_toml, suites_dir)
    r = results[-1]
    assert r.outcome == "fail", r
    assert "not seen within 0.3 s" in r.evidence and "observed: 7,7 moves=10 town=-" in r.evidence, r.evidence
    assert '`return M.qa.status("Robert")` /^6,6 .*town=-$/' in r.evidence, r.evidence


def test_instant_case_times_out_cleanly_on_a_query_that_never_comes_right(tmp_path: Path):
    real_toml, turn_root, suites_dir = _instant_game(tmp_path, WALK_CASE)
    harness = FakeHarness(turn_root)
    harness.on_lua = _Walker(lag=10**6)  # still inside, however often he's asked
    t0 = time.monotonic()
    results, _ = _run_instant(tmp_path, harness, real_toml, suites_dir)
    assert time.monotonic() - t0 < 10
    r = results[-1]
    assert r.outcome == "fail" and "observed: 5,5 moves=12 town=Caen" in r.evidence, r
    assert not (turn_root / "paused.txt").exists()
    i = harness.events.index("lua:return M.qa.current()")
    assert not any(e.startswith("advance:") for e in harness.events[i:])


def test_instant_case_fails_at_once_on_a_query_that_errors(tmp_path: Path):
    case = ('[[cases]]\nname = "q"\nkind = "instant"\n'
            'expect = [{ lua = \'return M.qa.status("Nobody")\', match = "x", within = 30 }]\n')
    real_toml, turn_root, suites_dir = _instant_game(tmp_path, case)
    harness = FakeHarness(turn_root)

    def game(h: FakeHarness, line: str) -> str:
        if "M.qa.current()" in line:
            return "england 10"
        if "M.qa.status(" in line:
            h.append_log("qa: status failed: unknown character 'Nobody'")
            return "nil"
        return _default_lua(h, line)

    harness.on_lua = game
    t0 = time.monotonic()
    results, _ = _run_instant(tmp_path, harness, real_toml, suites_dir, cases=["q"])
    assert time.monotonic() - t0 < 10  # not the 30 s within
    assert results[-1].outcome == "fail" and "unknown character 'Nobody'" in results[-1].evidence


def test_instant_case_not_on_its_own_turn_fails_with_whose_turn_it_is(tmp_path: Path):
    real_toml, turn_root, suites_dir = _instant_game(tmp_path, WALK_CASE)
    harness = FakeHarness(turn_root)
    harness.on_lua = _Walker(own_turn_after=10**6)
    results, _ = _run_instant(tmp_path, harness, real_toml, suites_dir)
    r = results[-1]
    assert r.outcome == "fail" and "not england's turn" in r.evidence and "france 10" in r.evidence, r
    assert not any("M.qa.walk(" in c for c in harness.lua_calls)


def test_instant_case_skips_when_a_required_setup_result_never_comes(tmp_path: Path):
    case = ('[[cases]]\nname = "siege"\nkind = "instant"\n'
            'setup = [{ lua = \'return M.qa.sieges("Caen")\', require = "^[1-9]", within = 0.1 }]\n'
            'act = [\'return M.qa.walk("Robert", 1, 1)\']\n'
            'expect = [{ log = "under siege" }]\n')
    real_toml, turn_root, suites_dir = _instant_game(tmp_path, case)
    harness = FakeHarness(turn_root)
    walker = _Walker()
    harness.on_lua = lambda h, line: "0" if "sieges(" in line else walker(h, line)
    results, _ = _run_instant(tmp_path, harness, real_toml, suites_dir)
    r = results[-1]
    assert r.outcome == "inconclusive" and r.evidence.startswith("skipped:") and "'0'" in r.evidence, r
    assert not any("M.qa.walk(" in c for c in harness.lua_calls)


def test_instant_case_whose_turn_ended_anyway_is_inconclusive(tmp_path: Path):
    real_toml, turn_root, suites_dir = _instant_game(tmp_path, WALK_CASE)
    harness = FakeHarness(turn_root)
    walker = _Walker()

    def game(h: FakeHarness, line: str) -> str:
        if "M.qa.walk(" in line:
            h.append_log("autoplay: ending turn 10")
        return walker(h, line)

    harness.on_lua = game
    results, _ = _run_instant(tmp_path, harness, real_toml, suites_dir)
    assert results[-1].outcome == "inconclusive" and "the turn ended" in results[-1].evidence


def test_instant_hold_leaves_a_pause_it_did_not_make(tmp_path: Path):
    real_toml, turn_root, suites_dir = _instant_game(tmp_path, WALK_CASE)
    harness = FakeHarness(turn_root)
    harness.on_lua = _Walker()
    harness.stop_qa_loop = lambda: (turn_root / "paused.txt").write_text("claude usage limit: reached\n")
    results, _ = _run_instant(tmp_path, harness, real_toml, suites_dir)
    assert results[-1].outcome == "pass"
    assert (turn_root / "paused.txt").read_text() == "claude usage limit: reached\n"


def test_restore_lifts_a_hold_a_crashed_run_left(tmp_path: Path):
    from parley.qa.runner import QA_HOLD_REASON

    real_toml, turn_root, _ = _write_real_game(tmp_path)
    (turn_root / "paused.txt").write_text(QA_HOLD_REASON + "\n")
    assert restore(real_toml) is False  # no lock: nothing else to restore
    assert not (turn_root / "paused.txt").exists()


# --- picking cases, skipping smoke, timing -------------------------------------------------------

TWO_CASES = WALK_CASE + (
    '\n[[cases]]\nname = "other"\nkind = "instant"\n'
    'expect = [{ lua = \'return M.qa.status("Robert")\', match = "town=", within = 0.1 }]\n'
)


def test_case_filter_runs_only_the_named_cases_after_smoke(tmp_path: Path):
    real_toml, turn_root, suites_dir = _instant_game(tmp_path, TWO_CASES)
    harness = FakeHarness(turn_root)
    harness.on_lua = _Walker()
    results, _ = _run_instant(tmp_path, harness, real_toml, suites_dir, cases=["other"])
    assert [r.name for r in results] == ["skill", "other"]


def test_case_filter_on_smoke_itself(tmp_path: Path):
    smoke = ('[[cases]]\nname = "skill"\nsetup = [\'M.qa.skill("QA Spy", "GoodSpy", 5)\']\n'
             'expect = [{ log = "qa: skill ok:" }]\n\n'
             '[[cases]]\nname = "skill2"\nsetup = [\'M.qa.skill("QA Spy", "GoodSpy", 5)\']\n'
             'expect = [{ log = "qa: skill ok:" }]\n')
    real_toml, turn_root, suites_dir = _instant_game(tmp_path, WALK_CASE, smoke_cases=smoke)
    harness = FakeHarness(turn_root)
    results, _ = _run_instant(tmp_path, harness, real_toml, suites_dir, suite="smoke", cases=["skill2"])
    assert [r.name for r in results] == ["skill2"]
    assert not (turn_root / "qa.last_smoke").exists()  # part of smoke is not a smoke pass


def test_unknown_case_name_lists_the_suites_cases(tmp_path: Path):
    real_toml, turn_root, suites_dir = _instant_game(tmp_path, TWO_CASES)
    harness = FakeHarness(turn_root)
    with pytest.raises(QARunError, match=r"no case 'nope' in suite 'instant'; its cases: walk_out, other"):
        _run_instant(tmp_path, harness, real_toml, suites_dir, cases=["nope"])
    assert harness.events == [] and not (turn_root / "qa.lock").exists()


def test_a_whole_smoke_pass_is_recorded_and_lets_no_smoke_skip_it(tmp_path: Path):
    real_toml, turn_root, suites_dir = _instant_game(tmp_path, WALK_CASE)
    harness = FakeHarness(turn_root)
    harness.on_lua = _Walker()
    _run_instant(tmp_path, harness, real_toml, suites_dir)
    assert json.loads((turn_root / "qa.last_smoke").read_text())["passed_epoch"] > 0

    # one real turn later: a fresh autosave and heartbeat, as the bench requires between runs
    save = tmp_path / "mods" / "parley" / "saves" / "Autosave.sav"
    save.write_bytes(b"save-turn-11")
    _write_state(turn_root, "scratch", 11)
    later = time.time() + 5
    os.utime(save, (later, later))
    harness2 = FakeHarness(turn_root)
    harness2.on_lua = _Walker()
    results, _ = _run_instant(tmp_path, harness2, real_toml, suites_dir, no_smoke=True)
    assert [r.name for r in results] == ["walk_out"] and results[0].outcome == "pass"
    assert not any("M.qa.skill(" in c for c in harness2.lua_calls)
    assert not any(e.startswith("start_qa_loop") for e in harness2.events)


def test_a_failed_smoke_records_no_pass(tmp_path: Path):
    real_toml, turn_root, suites_dir = _instant_game(tmp_path, WALK_CASE)
    harness = FakeHarness(turn_root)
    # skill logs nothing: smoke fails
    harness.on_lua = lambda h, line: "ok" if "M.qa.skill(" in line else _default_lua(h, line)
    _run_instant(tmp_path, harness, real_toml, suites_dir)
    assert not (turn_root / "qa.last_smoke").exists()


def test_no_smoke_refused_without_a_recent_smoke_pass(tmp_path: Path):
    import datetime as dt

    real_toml, turn_root, suites_dir = _instant_game(tmp_path, WALK_CASE)
    harness = FakeHarness(turn_root)
    with pytest.raises(QARunError, match="none recorded"):
        _run_instant(tmp_path, harness, real_toml, suites_dir, no_smoke=True)
    old = dt.datetime.now() - dt.timedelta(minutes=31)
    (turn_root / "qa.last_smoke").write_text(json.dumps({"passed_epoch": old.timestamp()}))
    with pytest.raises(QARunError, match="the last was 31 min ago"):
        _run_instant(tmp_path, harness, real_toml, suites_dir, no_smoke=True)
    assert harness.events == [] and not (turn_root / "qa.lock").exists()


def test_no_smoke_refused_for_turn_cases_and_for_smoke_or_all(tmp_path: Path):
    real_toml, turn_root, suites_dir = _instant_game(tmp_path, WALK_CASE)
    (turn_root / "qa.last_smoke").write_text(json.dumps({"passed_epoch": time.time()}))
    (suites_dir / "field.toml").write_text(
        'name = "field"\nfaction = "england"\n\n[[cases]]\nname = "turny"\n'
        'expect = [{ log = "x" }]\n', encoding="utf-8")
    harness = FakeHarness(turn_root)
    with pytest.raises(QARunError, match="instant cases only; these end turns: turny"):
        _run_instant(tmp_path, harness, real_toml, suites_dir, suite="field", no_smoke=True)
    for suite in ("smoke", "all"):
        with pytest.raises(QARunError, match=f"can't run with suite '{suite}'"):
            _run_instant(tmp_path, harness, real_toml, suites_dir, suite=suite, no_smoke=True)
    assert harness.events == []


def test_report_shows_each_cases_time_and_the_total():
    rs = [CaseResult(name="a", outcome="pass", turns=0, evidence="e", seconds=3.21),
          CaseResult(name="b", outcome="fail", turns=2, evidence="f", seconds=250.0)]
    text = format_report("instant", rs, total_seconds=260.0)
    assert "| case | outcome | turns | evidence | time |" in text
    assert "| a | pass | 0 | e | 3.2 s |" in text and "| b | fail | 2 | f | 4 min 10 s |" in text
    assert "Total: 4 min 20 s for 2 case(s)" in text


def test_cli_passes_case_and_no_smoke(monkeypatch, tmp_path: Path, capsys):
    seen = {}
    report = tmp_path / "r.md"
    report.write_text("# QA Report: instant\n\nTotal: 1.0 s for 0 case(s)\n")

    def fake_run_suite(suite, real, **kw):
        seen.update(kw, suite=suite)
        return [], report

    monkeypatch.setattr("parley.qa.__main__.run_suite", fake_run_suite)
    assert qa_main(["run", "instant", "--real", "x.toml", "--case", "a", "--case", "b", "--no-smoke"]) == 0
    assert seen == {"suite": "instant", "cases": ["a", "b"], "no_smoke": True}
    assert "Total: 1.0 s" in capsys.readouterr().out


def test_qa_sh_passes_case_and_no_smoke_through(tmp_path: Path):
    # just qa <suite> case=NAME no-smoke -> python -m parley.qa run <suite> --case NAME --no-smoke
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "uv").write_text('#!/usr/bin/env bash\necho "uv $*"\n')
    (fake_bin / "uv").chmod(0o755)
    real = tmp_path / "real.toml"
    real.write_text("")
    out = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "qa.sh"), "run", "instant", "case=split_far_target",
         "--case", "besieged_town_refuses", "no-smoke", "--real", str(real)],
        capture_output=True, text=True, env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )
    assert out.returncode == 0, out.stderr
    assert (f"uv run python -m parley.qa run instant --real {real} --case split_far_target "
            f"--case besieged_town_refuses --no-smoke") in out.stdout


def test_instant_case_model_rules():
    with pytest.raises(ValueError, match="no orders"):
        Case(name="x", kind="instant", orders={1: [{"type": "move_army"}]}, expect=[Expect(log="y")])
    with pytest.raises(ValueError, match="not state/order_ok"):
        Case(name="x", kind="instant", expect=[Expect(state="treasury", equals=1)])
    with pytest.raises(ValueError, match='for kind = "instant"'):
        Case(name="x", expect=[Expect(lua="return 1", equals="1")])
    with pytest.raises(ValueError, match="needs equals, match"):
        Expect(lua="return 1")
    with pytest.raises(ValueError, match="go with a lua query"):
        Expect(log="x", match="y")


def test_the_instant_suite_loads_and_needs_only_the_garrison_town():
    from parley.qa.cases import load_suite
    from parley.qa.runner import _effective_targets

    suite = load_suite(REPO_ROOT / "games" / "qa" / "instant.toml")
    assert suite.instant and [c.name for c in suite.cases] == [
        "split_adjacent_target", "split_far_target", "occupied_step_tile_skipped", "besieged_town_refuses",
        "load_missing_save_refused"]
    for c in suite.cases[:-1]:
        assert _effective_targets(c, {})[1] == ["garrison_town", "garrison_town_x", "garrison_town_y"]
    # the missing-save refusal needs no target at all
    assert _effective_targets(suite.cases[-1], {})[1] == []


def _park_after_relaunch(tmp_path: Path, log_text: str | None, hb_turn: int = 0, hb_age: float = 0.0):
    """Park with the heartbeat at `hb_turn` (0, as right after a click-free relaunch), written
    `hb_age` seconds before now; `log_text` is the bridge log."""
    from parley.config import load_config
    from parley.qa.runner import _park_real
    real_toml, turn_root, save_dir = _write_real_game(tmp_path)
    _write_state(turn_root, "scratch", 49)
    hb = turn_root / "heartbeat.txt"
    hb_mtime = hb.stat().st_mtime - hb_age
    hb.write_text(f"turn={hb_turn}\n", encoding="utf-8")
    os.utime(hb, (hb_mtime, hb_mtime))
    autosave = save_dir / "Autosave.sav"
    autosave.write_bytes(b"real-turn-49")
    os.utime(autosave, (hb_mtime + 5.0, hb_mtime + 5.0))
    if log_text is not None:
        (turn_root / "parley_bridge.log").write_text(log_text, encoding="utf-8")
    harness = FakeHarness(turn_root)
    lock_path = turn_root / "qa.lock"

    def park():
        return _park_real(
            load_config(real_toml), real_toml, lock_path,
            stop_loop_fn=harness.stop_loop, stop_cw_fn=harness.stop_crash_watch,
            start_real_fn=harness.start_real, start_cw_fn=harness.start_crash_watch,
            now_fn=_dt.datetime.now,
            running_now_fn=lambda: {"loop": True, "bot": False, "crash_watch": True},
        )

    return park, harness, lock_path


def test_park_after_a_relaunch_takes_the_turn_from_the_bridge_log(tmp_path: Path):
    # live 10-31: after a click-free relaunch the heartbeat said turn 0 and the lock got "turn": 0
    park, _, lock_path = _park_after_relaunch(
        tmp_path,
        "2026-10-31 10:00:00 bridge loaded campaign at turn 0\n"
        "2026-10-31 10:00:40 bridge loaded campaign at turn 48\n"
        "2026-10-31 10:05:00 bridge loaded campaign at turn 0\n"
        "2026-10-31 10:05:40 bridge loaded campaign at turn 49\n"
        "2026-10-31 10:06:00 autoplay: something else\n",
    )
    _, real_turn = park()
    assert real_turn == 49
    assert json.loads(lock_path.read_text(encoding="utf-8"))["turn"] == 49


def _log_at(seconds_ago: float, turn: int) -> str:
    stamp = _dt.datetime.fromtimestamp(time.time() - seconds_ago).strftime("%Y-%m-%d %H:%M:%S")
    return f"{stamp} bridge loaded campaign at turn {turn}\n"


def test_park_prefers_a_campaign_load_newer_than_the_heartbeat(tmp_path: Path):
    # live 11-04: a bench run crashed with the heartbeat at the bench's turn 6; the relaunch loaded
    # the real campaign at turn 74 and wrote no heartbeat, so the lock got "turn": 6 and the
    # restore refused the real campaign's turn 74
    park, _, lock_path = _park_after_relaunch(
        tmp_path, _log_at(600, 5) + _log_at(60, 74), hb_turn=6, hb_age=300)
    _, real_turn = park()
    assert real_turn == 74
    assert json.loads(lock_path.read_text(encoding="utf-8"))["turn"] == 74


def test_park_keeps_a_heartbeat_newer_than_the_last_campaign_load(tmp_path: Path):
    # loaded at turn 48, then played on: the heartbeat's turn 52 is the real one
    park, _, _ = _park_after_relaunch(tmp_path, _log_at(900, 48), hb_turn=52, hb_age=60)
    _, real_turn = park()
    assert real_turn == 52


@pytest.mark.parametrize(
    "log_text",
    [None, "2026-10-31 10:00:00 bridge loaded campaign at turn 0\n"],
)
def test_park_refuses_when_neither_heartbeat_nor_log_gives_a_turn(tmp_path: Path, log_text):
    park, harness, lock_path = _park_after_relaunch(tmp_path, log_text)
    with pytest.raises(QARunError, match="no campaign turn"):
        park()
    assert not lock_path.exists()
    assert [e for e in harness.events if e in _STARTS] == ["start_real:scratch", "start_crash_watch"]


def test_confirm_load_accepts_any_campaign_turn_for_a_turn_0_lock(tmp_path: Path, capsys):
    # live 10-31: the restore loaded turn 49 but a lock written with turn 0 failed it, and the lock stayed
    log_path = tmp_path / "parley_bridge.log"
    log_path.write_text(
        "2026-10-31 11:00:00 bridge loaded campaign at turn 0\n"
        "2026-10-31 11:00:30 qa: load ok: mods/parley/saves/parley_keep_scratch.sav\n"
        "2026-10-31 11:01:00 bridge loaded campaign at turn 49\n",
        encoding="utf-8",
    )
    _confirm_load("ok", log_path, 0, expected_turn=0, timeout=0.05, poll_interval=0.01)
    assert "turn 0" in capsys.readouterr().err
    # a real lock turn still checks the loaded turn
    with pytest.raises(QARunError, match="expected turn 32"):
        _confirm_load("ok", log_path, 0, expected_turn=32, timeout=0.05, poll_interval=0.01)
