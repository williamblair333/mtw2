"""scripts/game.sh: status (play/stop start and stop real processes and are checked live;
new-game delegates to `parley new-game`, tested in test_setup.py)."""

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "scripts" / "game.sh"


def run(*args, games_dir):
    env = {**os.environ, "PARLEY_GAMES_DIR": str(games_dir)}
    return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, env=env)


def test_status_when_nothing_runs(tmp_path):
    r = run("status", games_dir=tmp_path)
    assert r.returncode == 0 and "turn loop: not running" in r.stdout and "bot: not running" in r.stdout


def test_play_unknown_game_explains(tmp_path):
    r = run("play", "nope", games_dir=tmp_path)
    assert r.returncode != 0 and "just new-game nope" in r.stderr


def test_play_rejects_bad_name(tmp_path):
    r = run("play", "../evil", games_dir=tmp_path)
    assert r.returncode != 0 and "letters, digits" in r.stderr
