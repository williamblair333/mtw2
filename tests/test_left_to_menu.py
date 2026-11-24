"""scripts/left_to_menu.sh: has the game left its campaign for the main menu (and not loaded another)?"""

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "scripts" / "left_to_menu.sh"

LOADED = "11:29:14.080 [M2TWEOP.core] [always] Hashmaps filled"
EXIT = ("11:13:10.523 [M2TWEOP.core] [always] GAME EXIT TO MENU - CLEAR DATA",
        "11:13:10.523 [M2TWEOP.core] [always] DATA CLEARED",
        "11:13:10.524 [M2TWEOP.core] [always] EXIT TO MENU EVENTS PROCESSED")


def run(tmp_path: Path, lines: list[str] | None) -> subprocess.CompletedProcess:
    log = tmp_path / "system.log.txt"
    if lines is not None:
        log.write_text("\r\n".join(lines) + "\r\n")  # the game writes CRLF
    env = {**os.environ, "PARLEY_GAME_LOG": str(log)}
    return subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, env=env, timeout=10)


def test_a_campaign_left_for_the_menu_is_reported(tmp_path):
    # 11-11 11:13: the "Victory Conditions Failed" scroll's only button returned to the main menu; nothing
    # noticed for 15 min (crash-watch looks for a crash dialog, the campaign watch for a stale report)
    r = run(tmp_path, ["11:12:00.000 [M2TWEOP.core] [always] Faction turn start: england", LOADED, *EXIT])
    assert r.returncode == 0
    assert "GAME EXIT TO MENU" in r.stdout


def test_a_campaign_loaded_after_the_exit_is_not(tmp_path):
    # a QA bench load (M2TWEOP.loadGame) passes through the menu and loads a campaign again
    r = run(tmp_path, [LOADED, *EXIT, "11:13:20.000 [M2TWEOP.core] [always] Strat character models loaded", LOADED])
    assert r.returncode == 1 and r.stdout == ""


def test_a_running_campaign_is_not(tmp_path):
    assert run(tmp_path, [LOADED, "11:30:00.000 [M2TWEOP.core] [always] Faction turn start: france"]).returncode == 1


def test_no_game_log_is_not(tmp_path):
    assert run(tmp_path, None).returncode == 1
