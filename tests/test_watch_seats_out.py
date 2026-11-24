"""campaign_watch.sh's OUT wake: another seat's reports stopped while the watched faction plays on."""

import os
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parent.parent / "scripts"


def _reports(base: Path, faction: str, turns) -> None:
    for t in turns:
        d = base / f"turn-{t:04d}" / faction
        d.mkdir(parents=True, exist_ok=True)
        (d / "state.json").write_text('{"settlements": [{"name": "York"}]}')


@pytest.mark.parametrize("out_at_start", [False, True])
def test_the_watch_wakes_when_another_seat_stops_reporting(tmp_path, out_at_start):
    # live 11-10: France lost its last town on turn 169; the loop wrote no more France reports and
    # the watch, looking at england only, stayed quiet for 40 turns
    game = tmp_path / "scratch"
    _reports(game, "england", range(1, 10 if out_at_start else 6))
    _reports(game, "france", range(1, 6))
    staged = tmp_path / "staged"
    _reports(staged, "england", range(10, 12) if out_at_start else range(6, 10))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # pass 1: england's newer reports land; pass 2: the loop "stops", so the watch exits DOWN
    (bin_dir / "sleep").write_text(
        f"#!/usr/bin/env bash\n[ -f '{tmp_path}/tick1' ] && touch '{tmp_path}/stop' && exit 0\n"
        f"touch '{tmp_path}/tick1'; cp -r '{staged}/.' '{game}/'\n")
    (bin_dir / "sleep").chmod(0o755)
    (bin_dir / "pgrep").write_text(
        f"#!/usr/bin/env bash\n[ -f '{tmp_path}/stop' ] && exit 1\n"
        "printf '101 python3 -m parley run games/local/scratch.toml\\n'\n")
    (bin_dir / "pgrep").chmod(0o755)
    (tmp_path / "parley_bridge.log").write_text("2026-11-10 18:00:00 ok\n")
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path), "DISPLAY": ":99",
           "PARLEY_TURN_ROOT": str(tmp_path), "PARLEY_LOGS_DIR": str(tmp_path), "WATCH_BOT": "0"}
    out = subprocess.run(["bash", str(SCRIPTS / "campaign_watch.sh"), "scratch"],
                         env=env, capture_output=True, text=True, timeout=10)
    said = out.stdout.strip()
    if out_at_start:
        # already out when the watch started: seen, so a re-armed watch doesn't wake on it again
        assert said.startswith("DOWN"), said
    else:
        assert said == "OUT: france (last report turn 5); england plays on", said


def _stale_host(tmp_path: Path, crash_watch_active: bool) -> dict:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, rc in (("pgrep", 1), ("systemctl", 0 if crash_watch_active else 3)):
        (bin_dir / name).write_text(f"#!/usr/bin/env bash\nexit {rc}\n")
        (bin_dir / name).chmod(0o755)
    log = tmp_path / "parley_bridge.log"
    log.write_text("2026-11-04 11:03:02 autoplay: turn 74\n")
    old = log.stat().st_mtime - 9 * 86400
    os.utime(log, (old, old))
    return {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path), "PARLEY_TURN_ROOT": str(tmp_path),
            "PARLEY_LOGS_DIR": str(tmp_path), "WATCH_BOT": "0"}


def test_the_watch_refuses_a_host_without_the_game(tmp_path):
    # live 11-13 06:18: started on the main machine while the game ran on the test laptop, it woke with a STALL on an
    # 11-04 bridge line
    env = _stale_host(tmp_path, crash_watch_active=False)
    r = subprocess.run(["bash", str(SCRIPTS / "campaign_watch.sh"), "scratch"], env=env,
                       capture_output=True, text=True, timeout=20)
    assert r.returncode == 1
    assert r.stdout.startswith("NOT HERE:"), r.stdout


def test_the_watch_stays_where_crash_watch_runs(tmp_path):
    # after tc's boot the log is hours old and Steam can take minutes to start the game
    env = _stale_host(tmp_path, crash_watch_active=True)
    with pytest.raises(subprocess.TimeoutExpired) as exc:
        subprocess.run(["bash", str(SCRIPTS / "campaign_watch.sh"), "scratch"], env=env,
                       capture_output=True, text=True, timeout=3)
    assert b"NOT HERE" not in (exc.value.stdout or b"")


def test_a_bot_log_written_after_the_watch_starts_still_says_no_bot_here(tmp_path):
    # live 11-21 20:24: the watch started just after a QA restore rotated the bot's log, before the
    # bot wrote "DISCORD_BOT_TOKEN is not set", and exited DOWN on "bot: not running"
    _reports(tmp_path / "scratch", "england", range(1, 3))
    bot_log = tmp_path / "scratch-discord.log"
    bot_log.write_text("")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # pass 1: the bot's line lands; pass 2: the turn loop "stops", so the watch exits DOWN for it
    (bin_dir / "sleep").write_text(
        f"#!/usr/bin/env bash\n[ -f '{tmp_path}/tick1' ] && touch '{tmp_path}/stop' && exit 0\n"
        f"touch '{tmp_path}/tick1'; echo 'DISCORD_BOT_TOKEN is not set (put it in the untracked env file)' > '{bot_log}'\n")
    (bin_dir / "sleep").chmod(0o755)
    # only the turn loop runs (no bot process)
    (bin_dir / "pgrep").write_text(
        f"#!/usr/bin/env bash\n[ -f '{tmp_path}/stop' ] && exit 1\n"
        "case \"$*\" in *bot*|*discord*) exit 1 ;; esac\n"
        "printf '101 python3 -m parley run games/local/scratch.toml\\n'\n")
    (bin_dir / "pgrep").chmod(0o755)
    (tmp_path / "parley_bridge.log").write_text("2026-11-21 20:24:00 ok\n")
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path), "DISPLAY": ":99",
           "PARLEY_TURN_ROOT": str(tmp_path), "PARLEY_LOGS_DIR": str(tmp_path)}
    out = subprocess.run(["bash", str(SCRIPTS / "campaign_watch.sh"), "scratch"],
                         env=env, capture_output=True, text=True, timeout=10)
    said = out.stdout.strip()
    assert (tmp_path / "stop").exists(), said  # it got past pass 1: no DOWN for the bot there
    assert said.startswith("DOWN") and "turn loop: running" not in said, said


@pytest.mark.parametrize("new_refusal, rotated",[(True, False), (False, False), (True, True)])
def test_the_watch_wakes_on_a_refused_screen_input(tmp_path, new_refusal, rotated):
    # 11-21: Parley makes no screen input; a path that still asks for one is refused and logged,
    # and the first new refusal wakes the session (CLICK). One already there at the start doesn't
    game = tmp_path / "scratch"
    _reports(game, "england", range(1, 3))
    turn_log = tmp_path / "scratch-turns.log"
    turn_log.write_text("2026-11-21 19:00:00 ERROR popup popup-1-2: pressing its check failed: "
                        "X input refused in a no-click run: click accept on a popup\n")
    new = ("2026-11-21 19:05:00 WARNING popup popup-3-9: Escape failed: X input refused in a no-click "
           "run: press Escape on a stuck scroll (parley/popups.py)\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # pass 1: the new line lands (or nothing does); pass 2: the loop "stops", so the watch exits DOWN
    staged = tmp_path / "new.log"
    staged.write_text(new if new_refusal else "")
    (bin_dir / "sleep").write_text(
        f"#!/usr/bin/env bash\n[ -f '{tmp_path}/tick1' ] && touch '{tmp_path}/stop' && exit 0\n"
        f"touch '{tmp_path}/tick1'; cat '{staged}' >> '{turn_log}'\n"
        # rotate_logs.sh's way: copy to .1, truncate (the refusal is only in .1 when the watch looks)
        + (f"cp -f '{turn_log}' '{turn_log}.1' && : > '{turn_log}'\n" if rotated else ""))
    (bin_dir / "sleep").chmod(0o755)
    (bin_dir / "pgrep").write_text(
        f"#!/usr/bin/env bash\n[ -f '{tmp_path}/stop' ] && exit 1\n"
        "printf '101 python3 -m parley run games/local/scratch.toml\\n'\n")
    (bin_dir / "pgrep").chmod(0o755)
    (tmp_path / "parley_bridge.log").write_text("2026-11-21 19:00:00 ok\n")
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path), "DISPLAY": ":99",
           "PARLEY_TURN_ROOT": str(tmp_path), "PARLEY_LOGS_DIR": str(tmp_path), "WATCH_BOT": "0"}
    out = subprocess.run(["bash", str(SCRIPTS / "campaign_watch.sh"), "scratch"],
                         env=env, capture_output=True, text=True, timeout=10)
    said = out.stdout.strip()
    if new_refusal:
        assert said.startswith("CLICK: a screen input was asked for and refused:"), said
        assert "press Escape on a stuck scroll" in said
    else:
        assert said.startswith("DOWN"), said
