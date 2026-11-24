"""scripts/keep_log.sh: `just play` sets the old turn log aside instead of emptying it."""

import os
import subprocess
import time
from pathlib import Path

SCRIPTS = Path(__file__).parent.parent / "scripts"


def _keep(log: Path, keep: int = 5) -> None:
    subprocess.run(["bash", str(SCRIPTS / "keep_log.sh"), str(log), str(keep)], check=True)


def test_the_old_log_is_set_aside_and_a_fresh_one_started(tmp_path):
    # live 11-10: `just play` mid-campaign emptied scratch-turns.log, the record of two crashes
    log = tmp_path / "scratch-turns.log"
    log.write_text("england turn 246: 5 orders\n")
    _keep(log)
    assert log.read_text() == ""
    [kept] = tmp_path.glob("scratch-turns.log.2*")
    assert kept.read_text() == "england turn 246: 5 orders\n"


def test_only_the_newest_are_kept(tmp_path):
    log = tmp_path / "scratch-turns.log"
    for i in range(4):
        old = tmp_path / f"scratch-turns.log.2026111{i}-000000"
        old.write_text(str(i))
        t = time.time() - 100 + i
        os.utime(old, (t, t))
    log.write_text("now\n")
    _keep(log, keep=3)
    kept = sorted(p.name for p in tmp_path.glob("scratch-turns.log.2*"))
    assert len(kept) == 3 and "scratch-turns.log.20261110-000000" not in kept
    assert "scratch-turns.log.20261111-000000" not in kept


def test_an_empty_or_missing_log_is_just_started(tmp_path):
    log = tmp_path / "scratch-turns.log"
    _keep(log)
    assert log.exists() and log.read_text() == ""
    assert list(tmp_path.glob("scratch-turns.log.2*")) == []
