"""scripts/rotate_logs.sh: the logs' size cap (STANDARDS log-rotation)."""

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "scripts" / "rotate_logs.sh"


def _run(tmp_path: Path, cap_mb: str = "1") -> subprocess.CompletedProcess:
    env = {**os.environ, "PARLEY_TURN_ROOT": str(tmp_path / "turns"), "PARLEY_LOGS_DIR": str(tmp_path / "logs"),
           "PARLEY_LOG_CAP_MB": cap_mb}
    return subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=10)


def _setup(tmp_path: Path) -> tuple[Path, Path, Path]:
    (tmp_path / "turns").mkdir()
    (tmp_path / "logs").mkdir()
    big = b"x" * (1024 * 1024 + 10)
    bridge = tmp_path / "turns" / "parley_bridge.log"
    bridge.write_bytes(big)
    turns = tmp_path / "logs" / "scratch-turns.log"
    turns.write_bytes(big)
    small = tmp_path / "logs" / "crash-watch.log"
    small.write_bytes(b"short\n")
    return bridge, turns, small


def test_logs_over_the_cap_are_kept_once_and_start_again(tmp_path):
    bridge, turns, small = _setup(tmp_path)
    # a writer holding the turn log open in append mode, as game.sh play's >> does
    with open(turns, "ab") as held:
        r = _run(tmp_path)
        assert r.returncode == 0, r.stderr
        held.write(b"next line\n")
        held.flush()
    assert (bridge.parent / "parley_bridge.log.1").stat().st_size > 1024 * 1024
    # the new bridge log starts with one stamped line: live 11-13 10:24 no log during a long AI turn read
    # as 10 h old to crash-watch, which killed a healthy game
    seeded = bridge.read_text().splitlines()
    assert len(seeded) == 1 and seeded[0][4] == "-" and seeded[0].endswith("rotated: older lines in parley_bridge.log.1")
    assert (turns.parent / "scratch-turns.log.1").stat().st_size > 1024 * 1024
    # cut in place: the held writer's next line lands at the start, not after a hole
    assert turns.read_bytes() == b"next line\n"
    assert small.read_bytes() == b"short\n" and not (small.parent / "crash-watch.log.1").exists()
    assert "rotated" in r.stdout


def test_nothing_is_rotated_while_a_qa_run_holds_the_lock(tmp_path):
    bridge, turns, _ = _setup(tmp_path)
    (tmp_path / "turns" / "qa.lock").write_text("{}")
    assert _run(tmp_path).stdout == ""
    assert bridge.stat().st_size > 1024 * 1024 and turns.stat().st_size > 1024 * 1024


def test_a_machine_with_no_turn_root_or_logs_yet_is_quiet(tmp_path):
    # crash-watch calls it every 10 min (#460), before any campaign has made a log
    r = _run(tmp_path)  # neither turns/ nor logs/ exists under tmp_path
    assert r.returncode == 0 and r.stdout == "" and r.stderr == ""


def test_logs_under_the_cap_are_left_alone(tmp_path):
    bridge, turns, _ = _setup(tmp_path)
    assert _run(tmp_path, cap_mb="20").stdout == ""
    assert bridge.exists() and turns.stat().st_size > 1024 * 1024
