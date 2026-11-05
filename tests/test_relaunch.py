"""The no-click relaunch: parley/relaunch.py's edits and save choice, and scripts/relaunch_game.sh run
against a temp game dir with fake steam/pgrep/pkill/xdotool/wmctrl (no game, no X)."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from parley import relaunch
from parley.qa import runner
from parley.xinput import ENV_VAR
from test_qa_runner import FakeHarness, _write_real_game

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "scripts" / "relaunch_game.sh"

CFG = """[features]
mod = mods/parley

[video]
windowed = 1

[log]
level = * error

[multiplayer]
playable = true
"""


# --- cfg edits --------------------------------------------------------------------------------

def test_set_bypass_adds_a_misc_section_and_strip_puts_the_cfg_back():
    out = relaunch.set_bypass(CFG, "mods/parley/saves/a.sav")
    assert out.endswith("\n[misc]\nbypass_to_strategy_save = mods/parley/saves/a.sav\n")
    assert relaunch.strip_bypass(out) == CFG


def test_set_bypass_uses_an_existing_misc_and_replaces_an_old_line():
    text = CFG + "\n[misc]\nunlock_campaign = true\nbypass_to_strategy_save = old.sav\n"
    out = relaunch.set_bypass(text, "mods/parley/saves/new.sav")
    assert out.count("bypass_to_strategy_save") == 1
    assert "[misc]\nbypass_to_strategy_save = mods/parley/saves/new.sav\nunlock_campaign = true\n" in out
    # strip keeps the rest of [misc]
    assert relaunch.strip_bypass(out) == CFG + "\n[misc]\nunlock_campaign = true\n"


def test_strip_bypass_drops_a_misc_section_left_empty_in_the_middle():
    text = "[a]\nx = 1\n\n[misc]\nbypass_to_strategy_save = s.sav\n\n[b]\ny = 2\n"
    assert relaunch.strip_bypass(text) == "[a]\nx = 1\n\n[b]\ny = 2\n"
    assert relaunch.strip_bypass("[a]\nx = 1\n") == "[a]\nx = 1\n"


def test_bypass_value_is_always_the_saves_path_and_never_a_path_given_in():
    assert relaunch.bypass_value("parley_keep_scratch.sav") == "mods/parley/saves/parley_keep_scratch.sav"
    for bad in ("", "../x.sav", "a/b.sav", "a\\b.sav", ".sav", "x.txt"):
        with pytest.raises(ValueError):
            relaunch.bypass_value(bad)


# --- hideLauncher ----------------------------------------------------------------------------

def test_hide_launcher_sets_both_files_and_is_idempotent(tmp_path):
    cfg_dir = tmp_path / "eopData" / "config"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "uiCfg.json").write_text(json.dumps({"hideLauncher": False, "modCfgFile": "parley.cfg"}))
    (tmp_path / "eopData" / "uiCfg.json").write_text(json.dumps({"modCfgFile": "parley.cfg"}))
    paths = relaunch.hide_launcher(tmp_path)
    assert len(paths) == 2
    for p in paths:
        data = json.loads(p.read_text())
        assert data["hideLauncher"] is True and data["modCfgFile"] == "parley.cfg"
    mtimes = [p.stat().st_mtime_ns for p in paths]
    time.sleep(0.01)
    relaunch.hide_launcher(tmp_path)
    assert [p.stat().st_mtime_ns for p in paths] == mtimes  # already set: not rewritten


def test_hide_launcher_without_any_ui_cfg_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="would wait for a click"):
        relaunch.hide_launcher(tmp_path)


# --- the save to load ------------------------------------------------------------------------

def _save(d: Path, name: str, mtime: float) -> Path:
    p = d / name
    p.write_bytes(b"x")
    os.utime(p, (mtime, mtime))
    return p


def test_choose_save_explicit_newest_and_after_a_qa_restore(tmp_path):
    saves, turns = tmp_path / "saves", tmp_path / "turns"
    saves.mkdir()
    turns.mkdir()
    _save(saves, "Autosave-1.sav", 1000)
    _save(saves, "parley_keep_scratch.sav", 3000)  # a keep copy is never "newest"
    _save(saves, "parley_keep_scratch.restored-20261031-080035.sav", 1500)
    assert relaunch.choose_save(saves, turns) == "Autosave-1.sav"
    assert relaunch.choose_save(saves, turns, "parley_keep_scratch.sav") == "parley_keep_scratch.sav"
    with pytest.raises(FileNotFoundError):
        relaunch.choose_save(saves, turns, "missing.sav")
    # after a QA restore with no newer real autosave: the restored keep save
    (turns / "qa.last_restore").write_text(json.dumps({"newest_save_mtime": 1000}))
    assert relaunch.choose_save(saves, turns) == "parley_keep_scratch.restored-20261031-080035.sav"
    # the real game autosaved since: that save
    _save(saves, "Autosave-2.sav", 2000)
    assert relaunch.choose_save(saves, turns) == "Autosave-2.sav"


def test_choose_save_with_no_save_at_all(tmp_path):
    with pytest.raises(FileNotFoundError, match="no save to load"):
        relaunch.choose_save(tmp_path, tmp_path)


# --- relaunch_game.sh, no clicks -------------------------------------------------------------

def _game(tmp_path: Path, steam_body: str, extra: dict | None = None):
    game = tmp_path / "game"
    mod = game / "mods" / "parley"
    (mod / "saves").mkdir(parents=True)
    (mod / "eopData" / "config").mkdir(parents=True)
    (mod / "eopData" / "config" / "uiCfg.json").write_text(json.dumps({"hideLauncher": False}))
    (mod / "eopData" / "uiCfg.json").write_text(json.dumps({"hideLauncher": False}))
    (mod / "parley.cfg").write_text(CFG)
    _save(mod / "saves", "Autosave-1.sav", 1000)
    _save(mod / "saves", "parley_keep_scratch.sav", 2000)
    turns = game / "parley_turns"
    turns.mkdir()
    (turns / "parley_bridge.log").write_text("old line: bridge loaded campaign at turn 7\n")
    calls = tmp_path / "calls.log"
    calls.touch()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fakes = {
        "pgrep": "exit 1",  # nothing running
        "pkill": 'echo "pkill $*" >>"$LOG"; exit 1',
        "sleep": "exec /bin/sleep 0.01",
        # every xdotool call is logged; a search for ^ERROR$ finds the box when $ERROR_UP exists
        "xdotool": r'''echo "xdotool $*" >>"$LOG"
if [ "$1" = search ]; then case "$*" in *ERROR*) [ -e "$ERROR_UP" ] && echo 99 && exit 0 ;; esac; exit 1; fi''',
        "wmctrl": 'echo "wmctrl $*" >>"$LOG"',
        # the game: what parley.cfg said at launch, then the bridge's map loads
        "steam": 'echo "steam $*" >>"$LOG"; cp "$CFG" "$CFG_AT_LAUNCH"\n' + steam_body,
        "systemd-run": 'echo "systemd-run $*" >>"$LOG"; while [ "${1#-}" != "$1" ]; do shift; done; exec "$@"',
        **(extra or {}),
    }
    for name, body in fakes.items():
        p = bin_dir / name
        p.write_text("#!/usr/bin/env bash\n" + body + "\n")
        p.chmod(0o755)
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "DISPLAY": ":99",  # a desktop session (without one the relaunch refuses at once)
        "LOG": str(calls),
        "MTW2_GAME_DIR": str(game),
        "PARLEY_TURN_ROOT": str(turns),
        "PARLEY_PY": sys.executable,
        "PARLEY_RELAUNCH_TIMEOUT": "40",
        "CFG": str(mod / "parley.cfg"),
        "CFG_AT_LAUNCH": str(tmp_path / "cfg_at_launch"),
        "BRIDGE_LOG": str(turns / "parley_bridge.log"),
        "ERROR_UP": str(tmp_path / "error_up"),
        ENV_VAR: "1",  # a no-click run: the default path must not need X input
    }
    return env, mod, calls


LOADS = 'printf "bridge loaded campaign at turn 0\\nbridge loaded campaign at turn 49\\n" >>"$BRIDGE_LOG"'


def _run(env, *args):
    return subprocess.run(["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True, timeout=60)


def _no_x_input(calls: Path) -> None:
    for line in calls.read_text().splitlines():
        assert not line.startswith("wmctrl"), line
        if line.startswith("xdotool"):
            assert line.split()[1] == "search", line  # reads only


def test_relaunch_loads_the_explicit_save_with_no_clicks_and_strips_the_line(tmp_path):
    env, mod, calls = _game(tmp_path, LOADS)
    r = _run(env, "--save", "parley_keep_scratch.sav")
    assert r.returncode == 0, r.stderr
    assert "campaign loaded at turn 49 from parley_keep_scratch.sav" in r.stdout
    at_launch = Path(env["CFG_AT_LAUNCH"]).read_text()
    assert "[misc]\nbypass_to_strategy_save = mods/parley/saves/parley_keep_scratch.sav\n" in at_launch
    assert (mod / "parley.cfg").read_text() == CFG  # stripped afterwards
    for f in ("eopData/config/uiCfg.json", "eopData/uiCfg.json"):
        assert json.loads((mod / f).read_text())["hideLauncher"] is True
    assert "steam steam://rungameid/4700" in calls.read_text().splitlines()
    _no_x_input(calls)


def test_an_oversized_bridge_log_is_rotated_before_the_launch_unless_a_qa_run_reads_it(tmp_path):
    # STANDARDS log-rotation: 11-05 the log was 25-26 MB and growing
    env, mod, calls = _game(tmp_path, LOADS)
    env["PARLEY_LOG_CAP_MB"] = "1"
    log = Path(env["BRIDGE_LOG"])
    log.write_text("old line\n" * 150_000)  # ~1.3 MB
    r = _run(env, "--save", "parley_keep_scratch.sav")
    assert r.returncode == 0, r.stderr
    assert "kept as parley_bridge.log.1" in r.stdout
    assert (log.parent / "parley_bridge.log.1").read_text().startswith("old line")
    assert "old line" not in log.read_text()
    assert "campaign loaded at turn 49" in r.stdout  # the wait read the fresh log

    env2, _, _ = _game(tmp_path / "held", HELD_AT_LAUNCH)
    env2["PARLEY_LOG_CAP_MB"] = "1"
    turns = Path(env2["PARLEY_TURN_ROOT"])
    env2["TURNS"] = str(turns)
    (turns / runner.LOCK_FILE).write_text("{}")
    log2 = Path(env2["BRIDGE_LOG"])
    log2.write_text("old line\n" * 150_000)
    r2 = _run(env2, "--save", "parley_keep_scratch.sav")
    assert r2.returncode == 0, r2.stderr
    assert not (log2.parent / "parley_bridge.log.1").exists()  # a QA run reads it by offset
    assert log2.read_text().startswith("old line")


# --- a relaunch during a QA run comes up held --------------------------------------------------

def test_hold_for_qa_holds_only_with_a_qa_lock_and_leaves_a_pause_as_it_is(tmp_path):
    assert relaunch.hold_for_qa(tmp_path) == "no qa.lock"
    assert not (tmp_path / "paused.txt").exists()
    (tmp_path / runner.LOCK_FILE).write_text("{}")
    assert relaunch.hold_for_qa(tmp_path) == "held"
    text = (tmp_path / "paused.txt").read_text()
    assert text.startswith(runner.QA_HOLD_REASON) and "relaunched" in text
    assert relaunch.hold_for_qa(tmp_path) == "held already"
    # the run's owner lifts it as its own hold
    runner._release_turn(tmp_path)
    assert not (tmp_path / "paused.txt").exists()
    # a seat's usage pause is not the QA run's: left alone
    (tmp_path / "paused.txt").write_text("seat usage limit\n")
    assert relaunch.hold_for_qa(tmp_path) == "held already"
    assert (tmp_path / "paused.txt").read_text() == "seat usage limit\n"


# the game, as launched: was the turn held when Steam started it?
HELD_AT_LAUNCH = 'if [ -e "$TURNS/paused.txt" ]; then echo "held at launch" >>"$LOG"; fi\n' + LOADS


def test_a_relaunch_with_a_qa_lock_comes_up_held(tmp_path):
    # live 10-31: a relaunch during a QA run, unheld, ended the loaded turn after the map load
    env, mod, calls = _game(tmp_path, HELD_AT_LAUNCH)
    turns = Path(env["PARLEY_TURN_ROOT"])
    env["TURNS"] = str(turns)
    (turns / runner.LOCK_FILE).write_text("{}")
    r = _run(env, "--save", "parley_keep_scratch.sav")
    assert r.returncode == 0, r.stderr
    assert "held at launch" in calls.read_text()
    assert "qa.lock present: the turn is held (held)" in r.stdout
    assert (turns / "paused.txt").read_text().startswith(runner.QA_HOLD_REASON)  # the run lifts it


def test_a_relaunch_without_a_qa_lock_is_not_held(tmp_path):
    env, mod, calls = _game(tmp_path, HELD_AT_LAUNCH)
    env["TURNS"] = env["PARLEY_TURN_ROOT"]
    r = _run(env, "--save", "parley_keep_scratch.sav")
    assert r.returncode == 0, r.stderr
    assert "held at launch" not in calls.read_text()
    assert not (Path(env["PARLEY_TURN_ROOT"]) / "paused.txt").exists()


def test_relaunch_without_save_loads_the_newest_real_save(tmp_path):
    env, mod, _ = _game(tmp_path, LOADS)
    r = _run(env)
    assert r.returncode == 0, r.stderr
    assert "bypass_to_strategy_save = mods/parley/saves/Autosave-1.sav" in Path(env["CFG_AT_LAUNCH"]).read_text()
    assert (mod / "parley.cfg").read_text() == CFG


def test_the_menus_turn_0_and_old_log_lines_are_not_the_campaign(tmp_path):
    # only the menu's turn 0 after the launch (the old turn-7 line is before it): a timeout
    env, mod, calls = _game(tmp_path, 'echo "bridge loaded campaign at turn 0" >>"$BRIDGE_LOG"')
    env["PARLEY_RELAUNCH_TIMEOUT"] = "3"
    r = _run(env)
    assert r.returncode == 1
    assert "no 'bridge loaded campaign at turn N' (N > 0)" in r.stderr
    assert (mod / "parley.cfg").read_text() == CFG  # stripped after the failure too
    lines = calls.read_text().splitlines()
    assert "pkill -x medieval2.exe" in lines and "pkill -x M2TWEOP GUI.exe" in lines  # stopped
    _no_x_input(calls)


def test_the_eop_error_box_stops_the_game_and_fails(tmp_path):
    env, mod, calls = _game(tmp_path, 'touch "$ERROR_UP"')
    r = _run(env)
    assert r.returncode == 1
    assert "EOP's ERROR box is up" in r.stderr
    lines = calls.read_text().splitlines()
    assert "pkill -x medieval2.exe" in lines
    assert (mod / "parley.cfg").read_text() == CFG
    _no_x_input(calls)


def test_no_save_or_no_ui_cfg_fails_before_anything_is_stopped_or_launched(tmp_path):
    env, mod, calls = _game(tmp_path, LOADS)
    r = _run(env, "--save", "missing.sav")
    assert r.returncode == 1 and "nothing stopped" in r.stderr
    for f in ("eopData/config/uiCfg.json", "eopData/uiCfg.json"):
        (mod / f).unlink()
    r = _run(env)
    assert r.returncode == 1 and "nothing stopped" in r.stderr
    assert not any(c.startswith(("pkill", "steam")) for c in calls.read_text().splitlines())
    assert (mod / "parley.cfg").read_text() == CFG


def test_a_running_game_is_stopped_before_the_launch(tmp_path):
    env, _, calls = _game(tmp_path, LOADS, extra={
        # medieval2.exe runs until pkill is called
        "pgrep": '[ "$*" = "-x medieval2.exe" ] && ! grep -q "^pkill -x medieval2.exe" "$LOG"',
    })
    r = _run(env)
    assert r.returncode == 0, r.stderr
    lines = calls.read_text().splitlines()
    assert lines.index("pkill -x medieval2.exe") < lines.index("steam steam://rungameid/4700")


def test_under_the_crash_watch_unit_steam_starts_in_its_own_scope(tmp_path):
    env, _, calls = _game(tmp_path, LOADS)
    r = _run({**env, "PARLEY_STEAM_SCOPE": "1"})
    assert r.returncode == 0, r.stderr
    assert "systemd-run --user --scope --collect --quiet steam steam://rungameid/4700" in calls.read_text()


# --- the QA restore relaunches with the kept save ---------------------------------------------

def test_the_restore_relaunches_with_the_keep_save_in_a_no_click_run(tmp_path, monkeypatch):
    real_toml, turn_root, save_dir = _write_real_game(tmp_path)
    (save_dir / "parley_keep_scratch.sav").write_bytes(b"kept")
    (turn_root / "qa.lock").write_text(json.dumps({"game_id": "scratch", "turn": 10}))
    h = FakeHarness(turn_root, game_running=False)
    saves: list = []

    def fake_relaunch(self, save=None):
        saves.append(save)
        h.relaunch_game()

    monkeypatch.setattr(runner._ProcessManager, "relaunch_game", fake_relaunch)
    monkeypatch.setenv(ENV_VAR, "1")
    runner.restore(
        real_toml, control_factory=h.control_factory, is_game_running=h.is_game_running,
        stop_loop=h.stop_loop, start_real=h.start_real, start_crash_watch=h.start_crash_watch,
        stop_crash_watch=lambda: None, crash_dialog_up=lambda: False, proc_root=tmp_path / "proc",
    )
    assert saves == ["parley_keep_scratch.sav"]
    assert not (turn_root / "qa.lock").exists()
