"""relaunch_game.sh --clicks (the old clicking fallback) and crash_watch.sh, run against fake
xdotool/wmctrl/pgrep (no game, no X). The default no-click relaunch: tests/test_relaunch.py."""

import os
import re
import subprocess
import time
from pathlib import Path

SCRIPTS = Path(__file__).parent.parent / "scripts"

FAKES = {
    # nothing running, so the kill branch is skipped
    "pgrep": "exit 1",
    "pkill": 'echo "pkill $*" >>"$LOG"; exit 1',
    "steam": "exit 0",
    "sleep": "exit 0",
    "timeout": 'shift; exec "$@"',
    # two "M2TWEOP" windows (a 2x29 stub and the real launcher), one "Medieval 2" window
    "xdotool": r"""
case "$1" in
    search) case "$*" in *M2TWEOP*) printf '11\n22\n' ;; *"Medieval 2"*) echo 33 ;; *) exit 1 ;; esac ;;
    getwindowgeometry)
        case "$3" in
            11) printf 'WINDOW=11\nX=0\nY=0\nWIDTH=2\nHEIGHT=29\nSCREEN=0\n' ;;
            22) printf 'WINDOW=22\nX=691\nY=364\nWIDTH=538\nHEIGHT=351\nSCREEN=0\n' ;;
            33) printf 'WINDOW=33\nX=4\nY=30\nWIDTH=1600\nHEIGHT=900\nSCREEN=0\n' ;;
        esac ;;
    *) echo "xdotool $*" >>"$LOG" ;;
esac
""",
    # Steam over the launcher, a Special Offers popup, and a Steam window clear of both targets
    "wmctrl": r"""
if [ "$1" = -lG ]; then
    echo '0x01  0 600  300  1200 800  host Steam'
    echo '0x02  0 700  400  900  600  host Special Offers'
    echo '0x03  0 1950 50   1200 800  host Steam'
else
    echo "wmctrl $*" >>"$LOG"
fi
""",
}


def test_relaunch_clicks_inside_the_cleared_windows(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in FAKES.items():
        fake = bin_dir / name
        fake.write_text("#!/usr/bin/env bash\n" + body)
        fake.chmod(0o755)
    log = tmp_path / "calls.log"
    log.touch()
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "LOG": str(log), "HOME": str(tmp_path), "DISPLAY": ":99"}
    out = subprocess.run(
        ["bash", str(SCRIPTS / "relaunch_game.sh"), "--clicks"],
        env=env, capture_output=True, text=True, timeout=30,
    )
    assert out.returncode == 0, out.stderr
    calls = log.read_text().splitlines()
    assert "wmctrl -i -c 0x02" in calls  # Special Offers closed
    assert "wmctrl -i -r 0x01 -e 0,1950,300,-1,-1" in calls  # Steam moved off the launcher
    assert not any("0x03" in c for c in calls)  # the Steam window clear of both is left alone
    clicks = [c for c in calls if c.startswith("xdotool mousemove")]
    # Run mod in the real 538x351 launcher, not the stub; Continue Campaign in the game window
    assert clicks == ["xdotool mousemove 956 534 click 1", "xdotool mousemove 376 361 click 1"]
    assert calls.index("xdotool windowraise 22") < calls.index(clicks[0])


def test_scripts_parse_and_match_game_processes_by_name():
    for name in ("relaunch_game.sh", "crash_watch.sh", "crash_dialog.sh"):
        script = SCRIPTS / name
        subprocess.run(["bash", "-n", str(script)], check=True)
        # -f matches command lines: it killed an unrelated shell whose text held "medieval2.exe"
        code = re.sub(r"#.*", "", script.read_text())
        assert not re.search(r"\bp(grep|kill)\s+(-\w*\s+)*-\w*f", code), name


def _run_campaign_watch(tmp_path: Path, turns_log: str, before: str = "") -> str:
    """`before` is in the turn log when the watch starts; `turns_log` lands during its first sleep."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    # Pass 1: sleep appends the new turn lines and pgrep reports loop + bot running;
    # pass 2: sleep marks stop so DOWN exits.
    (tmp_path / "pending.log").write_text(turns_log)
    (bin_dir / "sleep").write_text(
        f"#!/usr/bin/env bash\n[ -f '{tmp_path}/tick1' ] && touch '{tmp_path}/stop' && exit 0\n"
        f"touch '{tmp_path}/tick1'; cat '{tmp_path}/pending.log' >> '{tmp_path}/scratch-turns.log'\n"
    )
    (bin_dir / "sleep").chmod(0o755)
    (bin_dir / "pgrep").write_text(
        f"#!/usr/bin/env bash\n[ -f '{tmp_path}/stop' ] && exit 1\n"
        "printf '101 python3 -m parley run games/local/scratch.toml\\n"
        "102 python3 -m parley discord games/local/scratch.toml\\n'\n"
    )
    (bin_dir / "pgrep").chmod(0o755)
    for f in (tmp_path / "tick1", tmp_path / "stop"):
        f.unlink(missing_ok=True)
    (tmp_path / "parley_bridge.log").write_text("2026-10-30 14:00:00 ok\n")
    (tmp_path / "scratch-turns.log").write_text(before)
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(tmp_path), "DISPLAY": ":99",
        "PARLEY_TURN_ROOT": str(tmp_path),
        "PARLEY_LOGS_DIR": str(tmp_path),
    }
    out = subprocess.run(
        ["bash", str(SCRIPTS / "campaign_watch.sh"), "scratch"],
        env=env, capture_output=True, text=True, timeout=10,
    )
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def test_campaign_watch_exits_on_three_consecutive_seat_errors(tmp_path):
    subprocess.run(["bash", "-n", str(SCRIPTS / "campaign_watch.sh")], check=True)
    both_failing = "\n".join([
        "2026-10-30 12:36:57,019 ERROR england turn 83: seat error: heretic failed: timed out",
        "2026-10-30 12:36:57,031 INFO england turn 83: 0 orders, 0 rejected, 421.1s",
        "2026-10-30 12:37:14,239 ERROR france turn 83: seat error: heretic failed: timed out",
        "2026-10-30 12:37:14,251 INFO france turn 83: 0 orders, 0 rejected, 421.1s",
        "2026-10-30 12:44:16,899 ERROR england turn 84: seat error: heretic failed: timed out",
        "2026-10-30 12:44:16,911 INFO england turn 84: 0 orders, 0 rejected, 421.1s",
        "2026-10-30 12:44:33,634 ERROR france turn 84: seat error: heretic failed: timed out",
        "2026-10-30 12:44:33,646 INFO france turn 84: 0 orders, 0 rejected, 421.1s",
        "2026-10-30 12:51:36,556 ERROR england turn 85: seat error: heretic failed: timed out",
        "2026-10-30 12:51:36,572 INFO england turn 85: 0 orders, 0 rejected, 421.1s",
        "2026-10-30 12:51:53,272 ERROR france turn 85: seat error: heretic failed: 503 Service Unavailable",
        "2026-10-30 12:51:53,283 INFO france turn 85: 0 orders, 0 rejected, 421.1s",
    ]) + "\n"
    line = _run_campaign_watch(tmp_path, both_failing)
    assert "\n" not in line
    assert line == (
        "SEATS: england (turns 83, 84, 85), france (turns 83, 84, 85): "
        "heretic failed: 503 Service Unavailable"
    )

    # Non-watched faction failing 3 turns while England succeeds still wakes with that faction.
    rival_only = "\n".join([
        "2026-10-30 12:00:00,000 INFO england turn 10: 4 orders, 0 rejected, 15.0s",
        "2026-10-30 12:01:00,000 ERROR france turn 10: seat error: heretic failed: timed out",
        "2026-10-30 12:01:00,010 INFO france turn 10: 0 orders, 0 rejected, 421.1s",
        "2026-10-30 12:05:00,000 INFO england turn 11: 3 orders, 0 rejected, 14.0s",
        "2026-10-30 12:06:00,000 ERROR france turn 11: seat error: heretic failed: timed out",
        "2026-10-30 12:06:00,010 INFO france turn 11: 0 orders, 0 rejected, 421.1s",
        "2026-10-30 12:10:00,000 INFO england turn 12: 5 orders, 1 rejected, 16.0s",
        "2026-10-30 12:11:00,000 ERROR france turn 12: seat error: heretic failed: timed out",
        "2026-10-30 12:11:00,010 INFO france turn 12: 0 orders, 0 rejected, 421.1s",
    ]) + "\n"
    assert _run_campaign_watch(tmp_path, rival_only) == (
        "SEATS: france (turns 10, 11, 12): heretic failed: timed out"
    )


def test_campaign_watch_seat_success_resets_error_count(tmp_path):
    # 4 errors total for england (turns 83, 84 and 86, 87), but turn 85 succeeded so streak is 2.
    reset_by_success = "\n".join([
        "2026-10-30 12:36:57,019 ERROR england turn 83: seat error: heretic failed: timed out",
        "2026-10-30 12:36:57,031 INFO england turn 83: 0 orders, 0 rejected, 421.1s",
        "2026-10-30 12:44:16,899 ERROR england turn 84: seat error: heretic failed: timed out",
        "2026-10-30 12:44:16,911 INFO england turn 84: 0 orders, 0 rejected, 421.1s",
        "2026-10-30 12:51:36,572 INFO england turn 85: 6 orders, 0 rejected, 38.2s",
        "2026-10-30 12:58:56,686 ERROR england turn 86: seat error: heretic failed: timed out",
        "2026-10-30 12:58:56,698 INFO england turn 86: 0 orders, 0 rejected, 421.1s",
        "2026-10-30 13:06:16,665 ERROR england turn 87: seat error: heretic failed: timed out",
        "2026-10-30 13:06:16,678 INFO england turn 87: 0 orders, 0 rejected, 421.1s",
    ]) + "\n"
    line = _run_campaign_watch(tmp_path, reset_by_success)
    assert not line.startswith("SEATS:")
    assert line.startswith("DOWN:")


def test_campaign_watch_ignores_seat_errors_from_before_it_started(tmp_path):
    # a restarted watch must not fire again on the failures that woke Claude last time
    old = "\n".join(
        f"2026-10-30 12:{m:02d}:00,000 ERROR england turn {t}: seat error: heretic failed: timed out"
        for m, t in ((36, 83), (44, 84), (51, 85))
    ) + "\n"
    assert _run_campaign_watch(tmp_path, "", before=old).startswith("DOWN:")
    # ...but a further failed turn after the start does fire
    new = "2026-10-30 12:58:56,686 ERROR england turn 86: seat error: heretic failed: timed out\n"
    assert _run_campaign_watch(tmp_path, new, before=old) == (
        "SEATS: england (turns 83, 84, 85, 86): heretic failed: timed out"
    )


def test_campaign_watch_lost_counts_from_the_qa_restore_and_skips_a_qa_run(tmp_path):
    # live 10-30 23:33: restored at 23:30:36, the newest real report (turn 57) was ~20 min old from
    # before the QA run, and the watch fired "LOST?" at once
    import os
    import time

    state = tmp_path / "scratch" / "turn-0057" / "england" / "state.json"
    state.parent.mkdir(parents=True)
    state.write_text('{"settlements": [{"id": "London"}]}')
    old = time.time() - 20 * 60
    os.utime(state, (old, old))
    # no QA run: a 20-minute-old report is a lost faction
    assert _run_campaign_watch(tmp_path, "").startswith("LOST?: no england report for 15 min")
    # just restored: the clock starts at the restore
    (tmp_path / "qa.last_restore").write_text("restored\n")
    assert _run_campaign_watch(tmp_path, "").startswith("DOWN:")
    # an old restore doesn't hide a real loss
    os.utime(tmp_path / "qa.last_restore", (old, old))
    assert _run_campaign_watch(tmp_path, "").startswith("LOST?:")
    # a QA run in progress parks the campaign: no check at all
    (tmp_path / "qa.lock").write_text("123\n")
    assert _run_campaign_watch(tmp_path, "").startswith("DOWN:")


# --- the crash dialog (live 10-30 20:11: a Wine message box "Medieval 2", ~330x110, with the text
# "Medieval 2: Total War encountered an unspecified error and will now exit." and an OK button;
# medieval2.exe stays alive until OK is pressed) ---

_WINDOWS_XDOTOOL = r"""
# WINDOWS="id:WxH ..." lists the visible "Medieval 2" windows (or the file $WINFILE holds them);
# a token "E<id>:<pid>" is an "ERROR" window (EOP's modal box) whose _NET_WM_PID is <pid> (or none)
[ -n "${WINFILE:-}" ] && WINDOWS=$(cat "$WINFILE")
case "$1" in
    search)
        case "$*" in
            *ERROR*) for w in $WINDOWS; do case "$w" in E*) w=${w#E}; echo "${w%%:*}" ;; esac; done ;;
            *) for w in $WINDOWS; do case "$w" in E*) ;; *) echo "${w%%:*}" ;; esac; done ;;
        esac ;;
    getwindowpid)
        for w in $WINDOWS; do
            case "$w" in E"$2":*) [ -n "${w#*:}" ] && { echo "${w#*:}"; exit 0; }; exit 1 ;; esac
        done
        exit 1 ;;
    getwindowgeometry)
        for w in $WINDOWS; do
            [ "${w%%:*}" = "$3" ] || continue
            size=${w#*:}
            printf 'WINDOW=%s\nX=4\nY=30\nWIDTH=%s\nHEIGHT=%s\nSCREEN=0\n' "$3" "${size%x*}" "${size#*x}"
        done ;;
esac
"""


def _fake_bin(tmp_path: Path, fakes: dict[str, str]) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name, body in fakes.items():
        fake = bin_dir / name
        fake.write_text("#!/usr/bin/env bash\n" + body)
        fake.chmod(0o755)
    return bin_dir


def _crash_dialog(tmp_path: Path, windows: str) -> subprocess.CompletedProcess:
    bin_dir = _fake_bin(tmp_path, {"xdotool": _WINDOWS_XDOTOOL})
    return subprocess.run(
        ["bash", str(SCRIPTS / "crash_dialog.sh")],
        env={"PATH": f"{bin_dir}:/usr/bin:/bin", "WINDOWS": windows},
        capture_output=True, text=True, timeout=10,
    )


def test_crash_dialog_is_a_small_medieval_2_window_never_the_game(tmp_path):
    # the game window alone (1600x900 at 4,30) is never the dialog
    assert _crash_dialog(tmp_path, "33:1600x900").returncode == 1
    # nor a 2x29 stub like the launcher's, nor nothing at all
    assert _crash_dialog(tmp_path, "33:1600x900 34:2x29").returncode == 1
    assert _crash_dialog(tmp_path, "").returncode == 1
    # the dialog beside the game, or alone
    up = _crash_dialog(tmp_path, "33:1600x900 44:330x110")
    assert up.returncode == 0
    assert "44 330x110" in up.stdout
    assert _crash_dialog(tmp_path, "44:330x110").returncode == 0


def _run_crash_watch(
    tmp_path: Path, polls: list[str], sleeps: int, report_body: str = "", extra_env: dict | None = None,
    extra_fakes: dict[str, str] | None = None,
) -> tuple[str, list[str]]:
    """`polls[i]` is what poll i+1 sees on screen (the last one repeats); the watch ends at its
    `sleeps`-th sleep (sleep's parent is the watch's shell)."""
    import datetime as dt

    calls = tmp_path / "calls.log"
    calls.write_text("")
    winfile = tmp_path / "windows"
    winfile.write_text(polls[0])
    for i, w in enumerate(polls[1:], start=1):
        (tmp_path / f"windows.{i}").write_text(w)
    count = tmp_path / "sleeps"
    count.write_text("0")
    bin_dir = _fake_bin(tmp_path, {
        "xdotool": _WINDOWS_XDOTOOL,
        "pgrep": "exit 0",  # medieval2.exe alive
        "sleep": (
            f'echo "sleep $*" >>"{calls}"; n=$(( $(cat "{count}") + 1 )); echo $n >"{count}"\n'
            f'[ -f "{tmp_path}/windows.$n" ] && cp "{tmp_path}/windows.$n" "{winfile}"\n'
            f'[ $n -ge {sleeps} ] && kill -TERM $PPID\nexit 0\n'
        ),
        **(extra_fakes or {}),
    })
    relaunch = tmp_path / "relaunch.sh"
    relaunch.write_text(f'echo relaunch >>"{calls}"\n')
    report = tmp_path / "crash_report.py"
    report.write_text(
        "import sys\n"
        f"open({str(calls)!r}, 'a').write('report ' + ' '.join(sys.argv[1:]) + '\\n')\n"
        + (report_body or "print('runs/crashes/x')\n")
    )
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    (tmp_path / "parley_bridge.log").write_text(f"{now} autoplay: turn 41, waiting for england\n")
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(tmp_path), "DISPLAY": ":99",
        "WINFILE": str(winfile),
        "PARLEY_TURN_ROOT": str(tmp_path),
        "PARLEY_RELAUNCH": str(relaunch),
        "PARLEY_CRASH_REPORT": str(report),
        **(extra_env or {}),
    }
    out = subprocess.run(
        ["bash", str(SCRIPTS / "crash_watch.sh")],
        env=env, capture_output=True, text=True, timeout=15,
    )
    return out.stdout, calls.read_text().splitlines()


DIALOG = "33:1600x900 44:330x110"
GAME = "33:1600x900"


def test_crash_watch_relaunches_on_the_crash_dialog_seen_on_two_polls(tmp_path):
    # process alive and the bridge log fresh: only the dialog says the game is gone
    out, calls = _run_crash_watch(tmp_path, [DIALOG], sleeps=2)
    assert "crash dialog" in out
    # the report is written while the dialog is still up, before the relaunch kills it
    assert calls == [
        "sleep 30", "report write --why crash dialog up on 2 polls (44 330x110)", "relaunch", "sleep 300",
    ]
    assert "crash report: runs/crashes/x" in out


# --- EOP's modal "ERROR" box (live 10-31: "Cannot create M2TWEOP save file. 2" on a load of a save
# that wasn't there; the game froze until it was closed, and closing it ended the game) ---


def _eop_error_box(tmp_path: Path, windows: str, game_running: bool = True) -> subprocess.CompletedProcess:
    bin_dir = _fake_bin(tmp_path, {"xdotool": _WINDOWS_XDOTOOL, "pgrep": "exit 0" if game_running else "exit 1"})
    proc = tmp_path / "proc"
    for pid, comm in (("700", "medieval2.exe"), ("701", "firefox"), ("702", "M2TWEOP GUI.exe")):
        (proc / pid).mkdir(parents=True, exist_ok=True)
        (proc / pid / "comm").write_text(comm + "\n")
    return subprocess.run(
        ["bash", str(SCRIPTS / "eop_error_box.sh")],
        env={"PATH": f"{bin_dir}:/usr/bin:/bin", "WINDOWS": windows, "PARLEY_PROC_ROOT": str(proc)},
        capture_output=True, text=True, timeout=10,
    )


def test_eop_error_box_is_an_error_window_of_the_game_only(tmp_path):
    # nothing, the game window, Wine's crash dialog: none is EOP's box
    assert _eop_error_box(tmp_path, "").returncode == 1
    assert _eop_error_box(tmp_path, GAME).returncode == 1
    assert _eop_error_box(tmp_path, DIALOG).returncode == 1
    # an ERROR window of medieval2.exe (or EOP's launcher)
    up = _eop_error_box(tmp_path, "33:1600x900 E55:700")
    assert up.returncode == 0 and up.stdout.strip() == "55 ERROR"
    assert _eop_error_box(tmp_path, "E56:702").returncode == 0
    # another program's ERROR window never counts
    assert _eop_error_box(tmp_path, "E57:701").returncode == 1
    # a window with no pid counts only while the game runs
    assert _eop_error_box(tmp_path, "E58:").returncode == 0
    assert _eop_error_box(tmp_path, "E58:", game_running=False).returncode == 1


def test_eop_error_box_script_makes_no_x_input():
    text = (SCRIPTS / "eop_error_box.sh").read_text()
    verbs = set(re.findall(r"xdotool\s+(\w+)", text))
    assert verbs <= {"search", "getwindowpid"}


def _closes_on_wmctrl(tmp_path: Path, game_exits: bool) -> dict[str, str]:
    calls = tmp_path / "calls.log"
    closed = tmp_path / "closed"
    return {
        "wmctrl": f'echo "wmctrl $*" >>"{calls}"; touch "{closed}"\n',
        "pkill": f'echo "pkill $*" >>"{calls}"\n',
        "pgrep": f'[ -f "{closed}" ] && exit 1; exit 0\n' if game_exits else "exit 0",
    }


def test_crash_watch_closes_the_eop_error_box_and_relaunches_on_the_first_poll(tmp_path):
    from_box = _closes_on_wmctrl(tmp_path, game_exits=True)
    out, calls = _run_crash_watch(tmp_path, [GAME + " E55:"], sleeps=1, extra_fakes=from_box)
    assert "EOP error box" in out
    # a WM close request (no click), then the report naming the box, then the relaunch
    assert calls == [
        "wmctrl -i -c 55", "report write --why EOP error box: ERROR (window 55)", "relaunch", "sleep 300",
    ]


def test_crash_watch_kills_a_game_that_outlives_its_closed_error_box(tmp_path):
    from_box = _closes_on_wmctrl(tmp_path, game_exits=False)
    out, calls = _run_crash_watch(
        tmp_path, [GAME + " E55:"], sleeps=3, extra_fakes=from_box,
        extra_env={"PARLEY_ERROR_BOX_EXIT_TIMEOUT": "2"},
    )
    assert calls == [
        "wmctrl -i -c 55", "sleep 1", "sleep 1", "pkill -x medieval2.exe",
        "report write --why EOP error box: ERROR (window 55)", "relaunch", "sleep 300",
    ]
    assert "killing it" in out


def test_crash_watch_relaunches_when_the_report_fails(tmp_path):
    out, calls = _run_crash_watch(
        tmp_path, [DIALOG], sleeps=2, report_body="import sys\nprint('disk full', file=sys.stderr)\nsys.exit(1)\n"
    )
    assert calls[0] == "sleep 30" and calls[1].startswith("report write")
    assert calls[2:] == ["relaunch", "sleep 300"]
    assert "crash report failed (exit 1): disk full" in out


def test_crash_watch_relaunches_when_the_report_hangs(tmp_path):
    t0 = time.monotonic()
    out, calls = _run_crash_watch(
        tmp_path, [DIALOG], sleeps=2, report_body="import time\ntime.sleep(60)\n",
        extra_env={"PARLEY_CRASH_REPORT_TIMEOUT": "1"},
    )
    assert "relaunch" in calls
    assert "crash report failed (exit 124)" in out
    assert time.monotonic() - t0 < 10


def test_crash_watch_ignores_a_dialog_seen_once(tmp_path):
    out, calls = _run_crash_watch(tmp_path, [DIALOG, GAME], sleeps=4)
    assert out == ""
    assert "relaunch" not in calls


def test_crash_watch_skips_the_dialog_check_right_after_its_relaunch(tmp_path):
    # start-up windows must not set off a second relaunch: the polls after it come within 120 s
    out, calls = _run_crash_watch(tmp_path, [DIALOG], sleeps=6)
    assert calls.count("relaunch") == 1
    assert [c for c in calls if not c.startswith("report ")] == (
        ["sleep 30", "relaunch", "sleep 300"] + ["sleep 30"] * 4
    )


def test_crash_watch_leaves_a_working_game_alone(tmp_path):
    out, calls = _run_crash_watch(tmp_path, [GAME], sleeps=1)
    assert out == ""
    assert calls == ["sleep 30"]


# --- after a QA restore, Continue Campaign loads the QA game's autosave (live 10-30 20:12: the real
# loop came back on turn 45 instead of 41); relaunch_game.sh --clicks hands that case to Python ---

def _relaunch_env(tmp_path: Path) -> tuple[dict, Path, Path]:
    bin_dir = _fake_bin(tmp_path, FAKES)
    calls = tmp_path / "calls.log"
    calls.touch()
    turn_root = tmp_path / "parley_turns"
    turn_root.mkdir()
    py = tmp_path / "fake-python"
    py.write_text(f'#!/usr/bin/env bash\necho "python $*" >>"{calls}"\n')
    py.chmod(0o755)
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "LOG": str(calls),
        "HOME": str(tmp_path), "DISPLAY": ":99",
        "PARLEY_TURN_ROOT": str(turn_root),
        "PARLEY_PY": str(py),
    }
    return env, turn_root, calls


def test_relaunch_after_a_qa_restore_hands_over_to_the_reload_check(tmp_path):
    env, turn_root, calls = _relaunch_env(tmp_path)
    (turn_root / "parley_bridge.log").write_text("0123456789")  # 10 bytes before the relaunch
    (turn_root / "qa.last_restore").write_text('{"newest_save_mtime": 1.0}\n')
    out = subprocess.run(
        ["bash", str(SCRIPTS / "relaunch_game.sh"), "--clicks"],
        env=env, capture_output=True, text=True, timeout=30,
    )
    assert out.returncode == 0, out.stderr
    lines = calls.read_text().splitlines()
    assert lines[-1] == f"python -m parley.qa after-relaunch --turn-root {turn_root} --log-offset 10"
    # after the Continue Campaign click
    assert lines.index("xdotool mousemove 376 361 click 1") < len(lines) - 1


def test_relaunch_without_a_qa_restore_only_continues(tmp_path):
    env, _, calls = _relaunch_env(tmp_path)
    out = subprocess.run(
        ["bash", str(SCRIPTS / "relaunch_game.sh"), "--clicks"],
        env=env, capture_output=True, text=True, timeout=30,
    )
    assert out.returncode == 0, out.stderr
    assert not any(c.startswith("python") for c in calls.read_text().splitlines())


def test_relaunch_fails_when_the_reload_check_fails(tmp_path):
    env, turn_root, _ = _relaunch_env(tmp_path)
    (turn_root / "qa.last_restore").write_text('{"newest_save_mtime": 1.0}\n')
    Path(env["PARLEY_PY"]).write_text("#!/usr/bin/env bash\nexit 1\n")
    out = subprocess.run(
        ["bash", str(SCRIPTS / "relaunch_game.sh"), "--clicks"],
        env=env, capture_output=True, text=True, timeout=30,
    )
    assert out.returncode != 0


# --- crash-watch runs as the transient user unit parley-crash-watch (live 10-30 20:20: started from a
# background job, it died with that job's process tree and the next crash went unnoticed) ---

UNIT_SCRIPT = SCRIPTS / "crash_watch_unit.sh"
REPO = SCRIPTS.parent


def _unit_env(tmp_path: Path, *, active: bool, main_pid: int = 0) -> tuple[dict, Path, Path]:
    """Fake systemctl/systemd-run/kill and a fake /proc. Returns env, the calls log and the proc root."""
    calls = tmp_path / "calls.log"
    calls.write_text("")
    state = tmp_path / "state"
    state.mkdir()
    if active:
        (state / "active").touch()
    (state / "mainpid").write_text(f"{main_pid}\n")
    proc = tmp_path / "proc"
    proc.mkdir()
    bin_dir = _fake_bin(tmp_path, {
        "systemctl": (
            f'echo "systemctl $*" >>"{calls}"\n'
            'case "$*" in\n'
            f'    *is-active*) [ -f "{state}/active" ] ;;\n'
            f'    *MainPID*) cat "{state}/mainpid" ;;\n'
            f'    *" stop "*) rm -f "{state}/active" ;;\n'
            'esac\n'
        ),
        "systemd-run": f'echo "systemd-run $* XDG=$XDG_RUNTIME_DIR" >>"{calls}"; touch "{state}/active"\n',
        "fakekill": (
            f'echo "kill $*" >>"{calls}"\n'
            f'for p in "$@"; do case "$p" in -*) ;; *) rm -rf "{proc}/$p" ;; esac; done\n'
        ),
    })
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(tmp_path), "DISPLAY": ":99",
        "PARLEY_PROC_ROOT": str(proc),
        "PARLEY_KILL": str(bin_dir / "fakekill"),
    }
    return env, calls, proc


def _proc(proc: Path, pid: int, *argv: str) -> None:
    (proc / str(pid)).mkdir()
    (proc / str(pid) / "cmdline").write_bytes(b"".join(a.encode() + b"\x00" for a in argv))


def _unit(env: dict, action: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(UNIT_SCRIPT), action], env=env, capture_output=True, text=True, timeout=30,
    )


def test_crash_watch_starts_as_a_user_unit_no_job_owns(tmp_path):
    env, calls, _ = _unit_env(tmp_path, active=False)
    out = _unit(env, "start")
    assert out.returncode == 0, out.stderr
    runs = [c for c in calls.read_text().splitlines() if c.startswith("systemd-run")]
    assert len(runs) == 1
    log = REPO / "logs" / "crash-watch.log"
    for part in (
        "--user", "--unit=parley-crash-watch", "--collect", f"--working-directory={REPO}",
        f"--property=StandardOutput=append:{log}", f"--property=StandardError=append:{log}",
        # stopping the unit kills its whole cgroup, so Steam must be started outside it
        "--setenv=PARLEY_STEAM_SCOPE=1",
        f"bash {REPO}/scripts/crash_watch.sh",
    ):
        assert part in runs[0], part
    # KillMode=process left the watch's `sleep` behind, which kept the unit loaded: the next start
    # failed with "already loaded" (probed on this host 10-30)
    assert "KillMode" not in runs[0]
    # a non-login shell has no XDG_RUNTIME_DIR; systemctl --user needs it to find the bus
    assert runs[0].endswith(f"XDG=/run/user/{os.getuid()}")
    assert "parley-crash-watch" in out.stdout


def test_crash_watch_start_is_a_no_op_when_the_unit_is_active(tmp_path):
    env, calls, _ = _unit_env(tmp_path, active=True, main_pid=200)
    out = _unit(env, "start")
    assert out.returncode == 0, out.stderr
    assert "already running" in out.stdout
    assert not any(c.startswith("systemd-run") for c in calls.read_text().splitlines())


def test_crash_watch_start_stops_a_legacy_watch_first(tmp_path):
    # one started the old way (setsid nohup, no unit) would run beside the unit: two relaunchers
    env, calls, proc = _unit_env(tmp_path, active=False)
    _proc(proc, 101, "bash", "scripts/crash_watch.sh")
    _proc(proc, 102, "bash", "-c", "echo scripts/crash_watch.sh")
    _proc(proc, 103, "bash", "scripts/crash_watch.sh", "extra")
    out = _unit(env, "start")
    assert out.returncode == 0, out.stderr
    lines = calls.read_text().splitlines()
    kills = [c for c in lines if c.startswith("kill")]
    assert kills == ["kill -TERM 101"]
    assert lines.index("kill -TERM 101") < next(i for i, c in enumerate(lines) if c.startswith("systemd-run"))
    assert (proc / "102").exists() and (proc / "103").exists()


def test_crash_watch_start_on_an_active_unit_stops_a_legacy_one_but_not_the_unit(tmp_path):
    env, calls, proc = _unit_env(tmp_path, active=True, main_pid=200)
    _proc(proc, 200, "/usr/bin/bash", f"{REPO}/scripts/crash_watch.sh")  # the unit's own
    _proc(proc, 101, "bash", "scripts/crash_watch.sh")  # legacy
    out = _unit(env, "start")
    assert out.returncode == 0, out.stderr
    kills = [c for c in calls.read_text().splitlines() if c.startswith("kill")]
    assert kills == ["kill -TERM 101"]
    assert (proc / "200").exists()


def test_crash_watch_stop_stops_the_unit_and_any_legacy_watch(tmp_path):
    env, calls, proc = _unit_env(tmp_path, active=True, main_pid=200)
    _proc(proc, 101, "bash", f"{REPO}/scripts/crash_watch.sh")
    out = _unit(env, "stop")
    assert out.returncode == 0, out.stderr
    lines = calls.read_text().splitlines()
    assert "systemctl --user stop parley-crash-watch" in lines
    assert "kill -TERM 101" in lines


def test_crash_watch_stop_is_quiet_when_nothing_runs(tmp_path):
    env, calls, _ = _unit_env(tmp_path, active=False)
    out = _unit(env, "stop")
    assert out.returncode == 0, out.stderr
    assert "systemctl --user stop parley-crash-watch" not in calls.read_text().splitlines()


def test_relaunch_under_the_unit_starts_steam_in_its_own_scope(tmp_path):
    # Steam started by a relaunch inside parley-crash-watch would die with the unit
    bin_dir = _fake_bin(tmp_path, {
        **FAKES,
        "steam": 'echo "steam $*" >>"$LOG"',
        "systemd-run": 'echo "systemd-run $*" >>"$LOG"; while [ "${1#-}" != "$1" ]; do shift; done; exec "$@"',
    })
    log = tmp_path / "calls.log"
    log.touch()
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "LOG": str(log), "HOME": str(tmp_path), "DISPLAY": ":99"}
    for scoped in (False, True):
        log.write_text("")
        run_env = {**env, **({"PARLEY_STEAM_SCOPE": "1"} if scoped else {})}
        out = subprocess.run(
            ["bash", str(SCRIPTS / "relaunch_game.sh"), "--clicks"],
            env=run_env, capture_output=True, text=True, timeout=30,
        )
        assert out.returncode == 0, out.stderr
        for _ in range(50):  # steam is started in the background
            if "steam steam://rungameid/4700" in log.read_text():
                break
            time.sleep(0.05)
        calls = log.read_text().splitlines()
        assert "steam steam://rungameid/4700" in calls
        runs = [c for c in calls if c.startswith("systemd-run")]
        if scoped:
            assert runs == ["systemd-run --user --scope --collect --quiet steam steam://rungameid/4700"]
        else:
            assert runs == []


def _no_display_env(tmp_path, procs: dict[str, str]):
    """A relaunch run over ssh: no DISPLAY; `procs` maps a process name to its pid for a fake pgrep."""
    pgrep = ('name=""; for a in "$@"; do name="$a"; done; case "$name" in '
             + " ".join(f'{n}) echo {p}; exit 0 ;;' for n, p in procs.items())
             + ' esac; exit 1')
    bin_dir = _fake_bin(tmp_path, {**FAKES, "steam": 'echo "steam $*" >>"$LOG"', "pgrep": pgrep})
    log = tmp_path / "calls.log"
    log.touch()
    return {"PATH": f"{bin_dir}:/usr/bin:/bin", "LOG": str(log), "HOME": str(tmp_path)}, log


def test_relaunch_with_nobody_logged_in_fails_at_once(tmp_path):
    # the test laptop 11-05: after its nightly power-off it sat at the login screen and each restore
    # waited the full 240 s for a Steam that could never start
    env, log = _no_display_env(tmp_path, {})
    out = subprocess.run(["bash", str(SCRIPTS / "relaunch_game.sh"), "--clicks"],
                         env=env, capture_output=True, text=True, timeout=30)
    assert out.returncode == 1
    assert "nobody is logged in to the desktop" in out.stderr
    assert "steam " not in log.read_text()


def test_relaunch_over_ssh_reads_the_steam_url_from_environment_d(tmp_path):
    env, log = _no_display_env(tmp_path, {"steam": "4242"})  # Steam already up: it takes the URL
    conf = tmp_path / ".config" / "environment.d"
    conf.mkdir(parents=True)
    (conf / "parley.conf").write_text("PARLEY_STEAM_URL=steam://launch/4700/option0\n")
    out = subprocess.run(["bash", str(SCRIPTS / "relaunch_game.sh"), "--clicks"],
                         env=env, capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    for _ in range(50):
        if "steam steam://launch/4700/option0" in log.read_text():
            break
        time.sleep(0.05)
    assert "steam steam://launch/4700/option0" in log.read_text().splitlines()


def test_crash_watch_recipes_are_one_line_calls_to_the_unit_script():
    text = (REPO / "justfile").read_text()
    for recipe, action in (("crash-watch", "start"), ("crash-watch-stop", "stop")):
        m = re.search(rf"^{re.escape(recipe)}:\n((?:    .*\n)+)", text, re.M)
        assert m, recipe
        assert m.group(1).strip() == f"bash scripts/crash_watch_unit.sh {action}", recipe
