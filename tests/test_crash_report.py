"""scripts/crash_report.py: the report crash-watch writes before a relaunch (fake game folders, fake
`import`; no game, no X)."""

import datetime as dt
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "scripts" / "crash_report.py"
_spec = importlib.util.spec_from_file_location("crash_report", SCRIPT)
cr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cr)


def _ts(now: dt.datetime, ago: float) -> str:
    return (now - dt.timedelta(seconds=ago)).strftime("%Y-%m-%d %H:%M:%S")


def _game(tmp_path: Path, now: dt.datetime, *, import_ok: bool = True) -> dict[str, str]:
    """A turn root, logs dir and save dir as the live game lays them out; returns the env."""
    game = tmp_path / "game"
    turn_root = game / "parley_turns"
    turn_root.mkdir(parents=True)
    bridge = [f"{_ts(now, 400 - i)} autoplay: line {i}" for i in range(290)]
    bridge += [
        f"{_ts(now, 20)} papal-trace: #3 onIncomingMessage: event 202 queued [message:202]",
        f"{_ts(now, 8)} papal vote: looking for the vote scroll from the tick",
        f"{_ts(now, 3)} papal-trace: #4 tick: calling getUiElement [papal_election_scroll]",
        "stack traceback: (unstamped, belongs to the line above)",
    ]
    (turn_root / "parley_bridge.log").write_text("\n".join(bridge) + "\n")
    (turn_root / "heartbeat.txt").write_text("turn=50\n")
    (turn_root / "bridge.txt").write_text("game_id=papal-noA\nfaction=england\nautoplay=1\n")
    (turn_root / "papal_trace.txt").write_text("n=40\nseq=57\nlast=tick: getUiElement returned\n")
    saves = game / "mods" / "parley" / "saves"
    saves.mkdir(parents=True)
    old, new = saves / "Autosave-3.sav", saves / "Autosave-4.sav"
    old.write_bytes(b"turn-49")
    new.write_bytes(b"turn-50")
    os.utime(old, (time.time() - 120, time.time() - 120))
    (saves / "M2TWEOPgameSaveDONTTOUCHTHISFILE.tmp").write_bytes(b"x")
    logs = tmp_path / "logs"
    logs.mkdir()
    turns = [f"{_ts(now, 200 - i)},000 INFO england turn 50: step {i}" for i in range(150)]
    turns.append(f"{_ts(now, 5)},123 INFO popup popup-50-1: acknowledged with its check")
    (logs / "papal-noA-turns.log").write_text("\n".join(turns) + "\n")
    stale = logs / "qa-covert-turns.log"
    stale.write_text(f"{_ts(now, 1300)},000 INFO an old QA run\n")
    os.utime(stale, (time.time() - 1200, time.time() - 1200))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "import"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        + ('echo "$*" >"$(dirname "${@: -1}")/import.args"; printf PNG >"${@: -1}"\n' if import_ok else "exit 1\n")
    )
    fake.chmod(0o755)
    # one visible "Medieval 2" window (id 44); "ERROR" finds none
    xdo = bin_dir / "xdotool"
    xdo.write_text('#!/usr/bin/env bash\ncase "$*" in *"^Medieval 2$"*) echo 44 ;; esac\nexit 0\n')
    xdo.chmod(0o755)
    return {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "PARLEY_TURN_ROOT": str(turn_root),
        "PARLEY_LOGS_DIR": str(logs),
        "PARLEY_CRASH_DIR": str(tmp_path / "crashes"),
    }


@pytest.fixture
def env(monkeypatch):
    def apply(values: dict[str, str]) -> None:
        for k, v in values.items():
            monkeypatch.setenv(k, v)
        monkeypatch.delenv("PARLEY_SAVE_DIR", raising=False)
        monkeypatch.delenv("PARLEY_CRASH_KEEP", raising=False)
    return apply


def test_a_report_holds_the_logs_screenshot_save_and_where_the_game_was(tmp_path, env):
    now = dt.datetime.now().replace(microsecond=0)
    env(_game(tmp_path, now))
    out = cr.write("crash dialog up on 2 polls (44 330x110)", now=now)
    assert out.parent == tmp_path / "crashes" and cr.NAME_RE.match(out.name)

    bridge = (out / "bridge.log").read_text().splitlines()
    assert len(bridge) == 200 and bridge[-1].startswith("stack traceback")
    papal = (out / "papal.log").read_text().splitlines()
    assert len(papal) == 3 and all("papal" in ln for ln in papal)
    # only turn logs written in the last 10 min, 100 lines each
    assert sorted(p.name for p in (out / "turns").iterdir()) == ["papal-noA-turns.log"]
    assert len((out / "turns" / "papal-noA-turns.log").read_text().splitlines()) == 100
    # the game's own window, never the whole screen (11-04: a full-desktop capture caught private windows)
    assert (out / "screen-0.png").read_text() == "PNG"
    assert (out / "import.args").read_text().split()[:2] == ["-window", "44"]
    assert "root" not in (out / "import.args").read_text()
    # the newest save, the one Continue Campaign reloads
    assert (out / "Autosave-4.sav").read_bytes() == b"turn-50"
    assert not (out / "Autosave-3.sav").exists()
    for name in ("heartbeat.txt", "bridge.txt", "papal_trace.txt"):
        assert (out / name).exists()

    meta = json.loads((out / "meta.json").read_text())
    assert meta["game_id"] == "papal-noA" and meta["turn"] == "50"
    assert meta["problems"] == []
    assert meta["last_bridge_line"].startswith("stack traceback")

    md = (out / "report.md").read_text()
    assert "game: papal-noA, turn 50" in md
    assert "crash-watch saw: crash dialog up on 2 polls (44 330x110)" in md
    assert "Autosave-4.sav" in md
    assert "## Guess" in md and "## Repro case" in md
    window = md.split("## Last 10 s: bridge and turn loop")[1].split("```")[1].strip().splitlines()
    # the last 10 s before the newest line (3 s ago): both sources, merged by time
    assert [w.split("|")[0].strip() for w in window] == ["bridge", "papal-noA", "bridge", "bridge"]
    assert "papal vote" in window[0] and "acknowledged" in window[1]
    assert window[-1].endswith("stack traceback: (unstamped, belongs to the line above)")
    assert "Report problems" not in md


def test_a_report_lists_the_orders_applied_at_the_turns_start(tmp_path, env):
    # 11-05 16:44: the orders before the crash (a spy moved into Dijon) were dug out by hand
    now = dt.datetime.now().replace(microsecond=0)
    values = _game(tmp_path, now)
    env(values)
    d = Path(values["PARLEY_TURN_ROOT"]) / "papal-noA" / "turn-0049" / "england"
    d.mkdir(parents=True)
    order = {"type": "move_agent", "agent": "Walter Wolman", "x": 121, "y": 122}
    (d / "orders.json").write_text(json.dumps({"protocol": 1, "orders": [order]}))
    out = cr.write("crash dialog up on 2 polls (44 330x110)", now=now)
    md = (out / "report.md").read_text()
    section = md.split("## Orders applied at this turn's start")[1].split("##")[0]
    assert '- england: {"type":"move_agent","agent":"Walter Wolman","x":121,"y":122}' in section
    assert (out / "orders-england.json").exists()
    assert json.loads((out / "meta.json").read_text())["problems"] == []


def test_a_report_keeps_the_games_own_log(tmp_path, env):
    # 11-10: system.log.txt placed the rebels'-turn crash ("Faction turn start: slave" its last line);
    # the relaunch rewrites it, so the 10:21 crash's copy was lost before anyone read it
    now = dt.datetime.now().replace(microsecond=0)
    values = _game(tmp_path, now)
    env(values)
    glog = Path(values["PARLEY_TURN_ROOT"]).parent / "mods" / "parley" / "logs"
    glog.mkdir(parents=True)
    lines = [f"08:57:{i % 60:02d}.000 [M2TWEOP.core] [always] line {i}" for i in range(399)]
    lines.append("08:57:59.217 [M2TWEOP.core] [always] Faction turn start: slave")
    (glog / "system.log.txt").write_text("\r\n".join(lines) + "\r\n")
    out = cr.write("crash dialog up on 2 polls (44 313x82)", now=now)
    kept = (out / "system.log.txt").read_text().splitlines()
    assert len(kept) == 300 and kept[-1].endswith("Faction turn start: slave")
    meta = json.loads((out / "meta.json").read_text())
    assert meta["last_game_line"].endswith("Faction turn start: slave")
    assert meta["problems"] == []


def _proton_lines(n_before: int, n_after: int, av: bool = True) -> list[str]:
    seh = "trace:seh:dispatch_exception"
    lines = [f"13300.{i:03d}:0190:0194:{seh} code=e24c4a02 (unknown) flags=1 addr=7BC3B858" for i in range(n_before)]
    if av:
        lines += [
            "13343.447:0190:0194:warn:seh:dispatch_exception backtrace: --- Exception 0xc0000005.",
            f"13343.447:0190:0194:{seh} code=c0000005 (EXCEPTION_ACCESS_VIOLATION) flags=0 addr=00000000",
            f"13343.447:0190:0194:{seh} eip=00000000 esp=0301b750 ebp=00000000 eflags=00010246",
        ]
    lines += [f"13343.5{i:02d}:0118:011c:trace:unwind:RtlGrowFunctionTable 03D38690, {i}" for i in range(n_after)]
    return lines


def test_a_report_keeps_protons_log_around_the_fault(tmp_path, env):
    # 11-11: PROTON_LOG=1 (in the launch options) writes ~/steam-4700.log with the SEH trace: the only place
    # the crash's own fault shows (eip=0 two seconds into the rebels' turn). Each launch rewrites it.
    now = dt.datetime.now().replace(microsecond=0)
    values = _game(tmp_path, now)
    env(values)
    (tmp_path / "steam-4700.log").write_text("\n".join(_proton_lines(5000, 500)) + "\n")
    out = cr.write("crash dialog up on 2 polls (44 313x82)", now=now)
    kept = (out / "proton.log").read_text().splitlines()
    i = next(n for n, ln in enumerate(kept) if "EXCEPTION_ACCESS_VIOLATION" in ln)
    assert i == cr.PROTON_BEFORE and len(kept) == cr.PROTON_BEFORE + cr.PROTON_AFTER
    meta = json.loads((out / "meta.json").read_text())
    assert "EXCEPTION_ACCESS_VIOLATION" in meta["fault"] and "eip=00000000" in meta["fault"]
    assert meta["problems"] == []
    assert "eip=00000000" in (out / "report.md").read_text()


def test_no_fault_in_protons_log_keeps_its_tail(tmp_path, env):
    now = dt.datetime.now().replace(microsecond=0)
    values = _game(tmp_path, now)
    env(values)
    (tmp_path / "steam-4700.log").write_text("\n".join(_proton_lines(3000, 0, av=False)) + "\n")
    out = cr.write("crash dialog up on 2 polls (44 313x82)", now=now)
    assert len((out / "proton.log").read_text().splitlines()) == cr.PROTON_TAIL
    meta = json.loads((out / "meta.json").read_text())
    assert meta["fault"] is None and meta["problems"] == []


def test_no_proton_log_is_no_problem(tmp_path, env):
    now = dt.datetime.now().replace(microsecond=0)
    env(_game(tmp_path, now))
    out = cr.write("crash dialog up on 2 polls (44 313x82)", now=now)
    assert not (out / "proton.log").exists()
    assert json.loads((out / "meta.json").read_text())["problems"] == []


def test_a_crt_invalid_parameter_is_the_fault_too(tmp_path, env):
    # 11-13 turn 705: msvcrt's _invalid_parameter raised c0000417 and the report said "none found"
    now = dt.datetime.now().replace(microsecond=0)
    env(_game(tmp_path, now))
    seh = "trace:seh:dispatch_exception"
    lines = [f"8858.{i:03d}:0190:0194:{seh} code=e24c4a02 (unknown) flags=1 addr=7BC3B858" for i in range(50)]
    lines += ["8858.211:0190:0194:err:msvcrt:_invalid_parameter (null):0 (null): (null) 0",
              f"8858.211:0190:0194:{seh} code=c0000417 (unknown) flags=1 addr=7BC3B858",
              f"8858.211:0190:0194:{seh} eip=7bc3b858 esp=0302a974 ebp=0302a9cc eflags=00000246"]
    (tmp_path / "steam-4700.log").write_text("\n".join(lines) + "\n")
    (tmp_path / "game" / "parley_turns" / "fault.bin").write_bytes(
        _fault_bin(2, 0x7BC3B858, 0x7BC3B858, [0x00A98F1A], code=0xC0000417))
    out = cr.write("crash dialog up on 2 polls (44 313x82)", now=now)
    meta = json.loads((out / "meta.json").read_text())
    assert "code=c0000417" in meta["fault"] and "eip=7bc3b858" in meta["fault"]
    assert meta["stack"]["matches_proton"] is True
    assert "code c0000417 (CRT invalid parameter)" in (out / "fault-stack.txt").read_text()


def _fault_bin(count: int, addr: int, eip: int, stack: list[int], code: int = 0xC0000005) -> bytes:
    import struct
    data = bytearray(0x4000)
    struct.pack_into("<IIII", data, 0, count, addr, len(stack), code)
    ctx = [0] * 51
    ctx[46], ctx[49] = eip, 0x0301B6D4
    struct.pack_into("<51I", data, 0x10, *ctx)
    for i, v in enumerate(stack):
        struct.pack_into("<I", data, 0xDC + 4 * i, v)
    mods = "00400000 00f00000 medieval2.exe\n76640000 00a00000 M2TWEOPLibrary.dll\n"
    data[0x1200:0x1200 + len(mods)] = mods.encode()
    return bytes(data)


def test_a_report_names_the_callers_from_the_bridges_fault_dump(tmp_path, env):
    # 11-11 turn 272 and 11-13 turn 640: eip=00eff4db, a ref-count copy with 1373 callers; Proton's
    # log has no stack, the bridge's catcher (fault.bin) does
    now = dt.datetime.now().replace(microsecond=0)
    values = _game(tmp_path, now)
    env(values)
    root = tmp_path / "game" / "parley_turns"
    (root / "fault.bin").write_bytes(
        _fault_bin(7, 0x00EFF4DB, 0x00EFF4DB, [0x12345678, 0x00A98F1A, 0, 0x766FEF65]))
    out = cr.write("crash dialog up on 2 polls (44 313x82)", now=now)
    meta = json.loads((out / "meta.json").read_text())
    assert meta["problems"] == []
    assert meta["stack"]["address"] == "00eff4db"
    assert meta["stack"]["matches_proton"] is None  # no Proton log here
    assert meta["stack"]["frames"] == ["[esp+004] 00a98f1a medieval2.exe+0x698f1a",
                                       "[esp+00c] 766fef65 M2TWEOPLibrary.dll+0xbef65"]
    text = (out / "fault-stack.txt").read_text()
    assert ("errors caught this process: 7; the last: code c0000005 (access violation) at 00eff4db"
            " (medieval2.exe+0xaff4db)") in text
    assert "eip=00eff4db eflags=00000000 esp=0301b6d4" in text
    assert (out / "fault.bin").exists()
    assert "medieval2.exe+0x698f1a; M2TWEOPLibrary.dll+0xbef65" in (out / "report.md").read_text()


def test_a_fault_dump_from_an_earlier_av_says_so(tmp_path, env):
    now = dt.datetime.now().replace(microsecond=0)
    env(_game(tmp_path, now))
    (tmp_path / "steam-4700.log").write_text("\n".join(_proton_lines(5000, 500)) + "\n")  # eip=00000000
    (tmp_path / "game" / "parley_turns" / "fault.bin").write_bytes(_fault_bin(1, 0x764F269D, 0x764F269D, []))
    out = cr.write("crash dialog up on 2 polls (44 313x82)", now=now)
    meta = json.loads((out / "meta.json").read_text())
    assert meta["stack"]["matches_proton"] is False
    assert "NOT Proton's eip" in (out / "report.md").read_text()


def test_an_empty_fault_dump_caught_nothing(tmp_path, env):
    now = dt.datetime.now().replace(microsecond=0)
    env(_game(tmp_path, now))
    (tmp_path / "game" / "parley_turns" / "fault.bin").write_bytes(bytes(0x4000))
    out = cr.write("crash dialog up on 2 polls (44 313x82)", now=now)
    meta = json.loads((out / "meta.json").read_text())
    assert meta["stack"] == {"address": None, "frames": []} and meta["problems"] == []
    assert "no error exception caught" in (out / "report.md").read_text()


def test_the_bridges_fault_stub_is_the_generators():
    import re
    gen_spec = importlib.util.spec_from_file_location("stub", SCRIPT.parent / "fault_catcher_stub.py")
    gen = importlib.util.module_from_spec(gen_spec)
    gen_spec.loader.exec_module(gen)
    lua = (SCRIPT.parent.parent / "lua" / "parley_bridge.lua").read_text()
    table = re.search(r"M\.FAULT_STUB = \{([^}]*)\}", lua).group(1)
    assert [int(x) for x in re.findall(r"\d+", table)] == list(gen.stub())
    assert gen.stub().count(bytes.fromhex("44332211")) == 1


def test_no_game_window_means_no_picture_never_the_desktop(tmp_path, env):
    now = dt.datetime.now().replace(microsecond=0)
    e = _game(tmp_path, now)
    (tmp_path / "bin" / "xdotool").write_text("#!/usr/bin/env bash\nexit 0\n")  # no game window up
    env(e)
    out = cr.write("game hung", now=now)
    assert not list(out.glob("screen*.png"))
    assert not (out / "import.args").exists()  # import was never called
    meta = json.loads((out / "meta.json").read_text())
    assert any("no game window to capture" in p for p in meta["problems"])


def test_a_report_never_fails_on_a_missing_part(tmp_path, env):
    now = dt.datetime.now().replace(microsecond=0)
    values = _game(tmp_path, now, import_ok=False)
    values["PARLEY_TURN_ROOT"] = str(tmp_path / "nowhere")  # no bridge log, no heartbeat, no saves
    env(values)
    out = cr.write("no medieval2.exe", now=now)
    md = (out / "report.md").read_text()
    assert "game: ?, turn ?" in md and "screenshot: none" in md and "save: none" in md
    problems = md.split("## Report problems")[1]
    for part in ("screenshot", "bridge log", "heartbeat", "save"):
        assert f"- {part}:" in problems
    # the turn logs still made it
    assert (out / "turns" / "papal-noA-turns.log").exists()


def test_only_the_newest_reports_are_kept(tmp_path, env):
    now = dt.datetime(2026, 10, 31, 7, 0, 0)
    env(_game(tmp_path, now))
    crashes = tmp_path / "crashes"
    for name in ("2026-10-30-010000", "2026-10-30-020000", "2026-10-30-030000", "2026-10-30-030000-2"):
        (crashes / name).mkdir(parents=True)
    (crashes / "notes").mkdir()  # not a report: left alone
    os.environ["PARLEY_CRASH_KEEP"] = "3"
    try:
        out = cr.write("bridge log 483s old", now=now)
    finally:
        del os.environ["PARLEY_CRASH_KEEP"]
    assert out.name == "2026-10-31-070000"
    assert sorted(p.name for p in crashes.iterdir()) == [
        "2026-10-30-030000", "2026-10-30-030000-2", "2026-10-31-070000", "notes",
    ]
    # a second crash in the same second gets its own folder
    assert cr.write("again", now=now).name == "2026-10-31-070000-2"


def test_just_crashes_lists_newest_first_with_the_last_bridge_line(tmp_path, env):
    values = _game(tmp_path, dt.datetime.now().replace(microsecond=0))
    env(values)
    cr.write("no medieval2.exe", now=dt.datetime(2026, 10, 31, 6, 0, 0))
    cr.write("crash dialog up on 2 polls", now=dt.datetime(2026, 10, 31, 6, 30, 0))
    out = subprocess.run(
        [sys.executable, str(SCRIPT), "list"], env=values, capture_output=True, text=True, timeout=10
    )
    assert out.returncode == 0, out.stderr
    lines = out.stdout.splitlines()
    assert lines[0].startswith("2026-10-31-063000  papal-noA t50  crash dialog up on 2 polls")
    assert lines[1].strip().startswith("stack traceback")
    assert lines[2].startswith("2026-10-31-060000")


def test_the_cli_prints_the_report_and_fails_only_without_a_folder(tmp_path):
    values = _game(tmp_path, dt.datetime.now().replace(microsecond=0))
    ok = subprocess.run(
        [sys.executable, str(SCRIPT), "write", "--why", "no medieval2.exe"],
        env=values, capture_output=True, text=True, timeout=10,
    )
    assert ok.returncode == 0, ok.stderr
    assert (Path(ok.stdout.strip()) / "report.md").exists()
    (tmp_path / "blocked").write_text("a file where the crash folder should be")
    values["PARLEY_CRASH_DIR"] = str(tmp_path / "blocked")
    bad = subprocess.run(
        [sys.executable, str(SCRIPT), "write", "--why", "x"], env=values, capture_output=True, text=True, timeout=10
    )
    assert bad.returncode == 1 and "crash report:" in bad.stderr
    empty = subprocess.run(
        [sys.executable, str(SCRIPT), "list"],
        env={**values, "PARLEY_CRASH_DIR": str(tmp_path / "none")}, capture_output=True, text=True, timeout=10,
    )
    assert empty.returncode == 0 and "no crash reports" in empty.stdout


def test_the_window_ends_at_the_last_activity_never_after_now():
    now = dt.datetime(2026, 10, 31, 6, 40, 0)
    sources = {
        "bridge": ["2026-10-31 06:30:00 a", "2026-10-31 06:30:09 b", "2026-10-31 06:30:20 c"],
        "scratch": ["2026-10-31 06:30:15,001 INFO d", "Traceback (most recent call last):"],
        "late": ["2026-10-31 07:00:00 clock skew"],  # past now: the window still ends at now
    }
    rows = cr.last_seconds(sources, now)
    assert rows == []  # 06:39:50-06:40:00 holds nothing
    del sources["late"]
    rows = cr.last_seconds(sources, now)
    assert [r.split("|", 1)[1].strip() for r in rows] == [
        "2026-10-31 06:30:15,001 INFO d", "Traceback (most recent call last):", "2026-10-31 06:30:20 c",
    ]


def test_tail_reads_from_the_end(tmp_path):
    p = tmp_path / "big.log"
    p.write_text("".join(f"line {i}\n" for i in range(100_000)))
    assert cr.tail_lines(p, 3) == ["line 99997", "line 99998", "line 99999"]
    assert cr.tail_lines(p, 0) == []
    short = tmp_path / "short.log"
    short.write_text("a\nb")
    assert cr.tail_lines(short, 5) == ["a", "b"]
