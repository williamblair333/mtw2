#!/usr/bin/env python3
"""Write a crash report before crash-watch relaunches the game; list recent ones.

    crash_report.py write --why TEXT     -> runs/crashes/<YYYY-MM-DD-HHMMSS>/, prints its path
    crash_report.py list [-n N]          -> the newest reports, one line each

A report holds what is gone after a relaunch (STANDARDS.md crash-repro-report): the bridge log's
last 200 lines and the papal-trace lines among them, the last 100 lines of every turn log written in
the last 10 minutes, screenshots of the game's own windows, never the whole screen (the crash dialog is still up: crash_watch.sh calls
this before relaunch_game.sh kills the game), a copy of the newest save (the one Continue Campaign
reloads), heartbeat.txt / bridge.txt / papal_trace.txt, and report.md: the game id and turn, why
crash-watch fired, and the last 10 s of the bridge and the turn loop merged by timestamp.

Standard library only (run with the system python3, no venv needed), and failure-proof: every
part is tried on its own, a failed part is named in report.md, and nothing here raises. Only a
crash folder that can't be created exits non-zero; crash_watch.sh logs that and relaunches anyway.

Paths come from the environment, as in the other scripts: PARLEY_TURN_ROOT (the bridge's folder),
PARLEY_LOGS_DIR (turn logs, default logs), PARLEY_CRASH_DIR (default runs/crashes),
PARLEY_SAVE_DIR (default <turn_root>/../mods/parley/saves), PARLEY_CRASH_KEEP (reports kept,
default 20).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

BRIDGE_LINES = 200
TURN_LINES = 100
TURN_LOG_AGE = 600  # s: a turn log written longer ago belongs to no running loop
WINDOW = 10  # s of bridge and turn-loop activity merged into report.md
SCREENSHOT_TIMEOUT = 5  # s
GAME_WINDOW_TITLES = ("^Medieval 2$", "^ERROR$")  # the only windows a report may capture
DEFAULT_KEEP = 20  # a report is a few MB, most of it the game-window screenshots
NAME_RE = re.compile(r"^\d{4}-\d\d-\d\d-\d{6}(-\d+)?$")
# bridge: "2026-10-31 06:38:16 ..."; turn loop (logging): "2026-10-31 05:31:14,605 INFO ..."
TS_RE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)")


def _env_path(name: str, default: Path) -> Path:
    v = os.environ.get(name)
    return Path(v) if v else default


def turn_root() -> Path:
    return _env_path(
        "PARLEY_TURN_ROOT",
        Path.home() / ".steam/steam/steamapps/common/Medieval II Total War/parley_turns",
    )


def crash_dir() -> Path:
    return _env_path("PARLEY_CRASH_DIR", Path("runs/crashes"))


def tail_lines(path: Path, n: int) -> list[str]:
    """The last n lines of a file, read from its end (the bridge log is 20+ MB)."""
    if n <= 0:
        return []
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        pos = f.tell()
        data = b""
        while pos > 0 and data.count(b"\n") <= n:
            step = min(65536, pos)
            pos -= step
            f.seek(pos)
            data = f.read(step) + data
    lines = data.decode("utf-8", errors="replace").splitlines()
    return lines[-n:]


def read_keys(path: Path) -> dict[str, str]:
    """key=value lines (heartbeat.txt, bridge.txt)."""
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def stamped(lines: list[str], source: str) -> list[tuple[dt.datetime | None, str, str]]:
    """(time, source, line); an unstamped line (a traceback) takes the time of the line above."""
    out = []
    ts: dt.datetime | None = None
    for line in lines:
        m = TS_RE.match(line)
        if m:
            try:
                ts = dt.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
            except ValueError:
                pass
        out.append((ts, source, line))
    return out


def last_seconds(sources: dict[str, list[str]], now: dt.datetime, window: int = WINDOW) -> list[str]:
    """The lines of every source from the `window` s before the newest stamped line (the last thing
    anything logged; never later than now), merged by time. A crash is noticed up to 8 min after it
    happens, so the window ends at the last activity, not at the moment crash-watch fired."""
    rows = [r for name, lines in sources.items() for r in stamped(lines, name) if r[0] is not None]
    if not rows:
        return []
    end = min(max(r[0] for r in rows), now)
    start = end - dt.timedelta(seconds=window)
    keep = [r for r in rows if start <= r[0] <= end]
    keep.sort(key=lambda r: r[0])  # stable: each source keeps its own order within a second
    width = max(len(n) for n in sources)
    return [f"{src:<{width}} | {line}" for _, src, line in keep]


def newest_save(save_dir: Path) -> Path | None:
    """The newest .sav: what the main menu's Continue Campaign loads (relaunch_game.sh)."""
    saves = [p for p in save_dir.glob("*.sav") if p.is_file()]
    return max(saves, key=lambda p: p.stat().st_mtime) if saves else None


def make_dir(root: Path, now: dt.datetime) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    base = now.strftime("%Y-%m-%d-%H%M%S")
    for i in range(1, 100):
        d = root / (base if i == 1 else f"{base}-{i}")
        try:
            d.mkdir()
            return d
        except FileExistsError:
            continue
    raise OSError(f"no free report folder for {base} in {root}")


def prune(root: Path, keep: int) -> list[str]:
    """Remove all but the newest `keep` reports (only folders named like one)."""
    reports = sorted(p.name for p in root.iterdir() if p.is_dir() and NAME_RE.match(p.name))
    gone = reports[:-keep] if keep > 0 else reports
    for name in gone:
        shutil.rmtree(root / name, ignore_errors=True)
    return gone


def write(why: str, now: dt.datetime | None = None) -> Path:
    t0 = time.monotonic()
    now = now or dt.datetime.now().replace(microsecond=0)
    root = crash_dir()
    out = make_dir(root, now)
    tr = turn_root()
    logs = _env_path("PARLEY_LOGS_DIR", Path("logs"))
    save_dir = _env_path("PARLEY_SAVE_DIR", tr.parent / "mods" / "parley" / "saves")
    problems: list[str] = []
    meta: dict[str, object] = {"at": now.isoformat(sep=" "), "why": why}

    def part(name: str, fn) -> object:
        try:
            return fn()
        except Exception as e:  # a report part never stops the others, nor the relaunch
            problems.append(f"{name}: {type(e).__name__}: {e}")
            return None

    # the screenshot first: the dialog is what's most likely to change while the rest is read.
    # The game's own windows only, never the whole screen: a full-desktop capture caught the user's
    # private windows (11-04). The game window and Wine's crash dialog are both titled "Medieval 2"
    # (crash_dialog.sh), EOP's modal box "ERROR". No such window: no picture, never the desktop.
    def screenshot() -> str:
        ids: list[str] = []
        for title in GAME_WINDOW_TITLES:
            found = subprocess.run(
                ["xdotool", "search", "--onlyvisible", "--name", title],
                capture_output=True, text=True, timeout=SCREENSHOT_TIMEOUT,
            )
            ids += [w for w in found.stdout.split() if w.isdigit() and w not in ids]
        if not ids:
            raise RuntimeError("no game window to capture (the whole screen is never captured)")
        names = []
        for i, w in enumerate(ids):
            png = out / f"screen-{i}.png"
            subprocess.run(
                ["import", "-window", w, str(png)],
                check=True, capture_output=True, timeout=SCREENSHOT_TIMEOUT,
            )
            names.append(png.name)
        return ", ".join(names)

    meta["screenshot"] = part("screenshot", screenshot)

    bridge: list[str] = part("bridge log", lambda: tail_lines(tr / "parley_bridge.log", BRIDGE_LINES)) or []
    if bridge:
        (out / "bridge.log").write_text("\n".join(bridge) + "\n", encoding="utf-8")
        papal = [ln for ln in bridge if "papal" in ln.lower()]
        if papal:
            (out / "papal.log").write_text("\n".join(papal) + "\n", encoding="utf-8")
        meta["last_bridge_line"] = bridge[-1]

    turn_logs: dict[str, list[str]] = {}

    def read_turn_logs() -> None:
        tdir = out / "turns"
        for p in sorted(logs.glob("*-turns.log")):
            if now.timestamp() - p.stat().st_mtime > TURN_LOG_AGE:
                continue
            lines = tail_lines(p, TURN_LINES)
            tdir.mkdir(exist_ok=True)
            (tdir / p.name).write_text("\n".join(lines) + "\n", encoding="utf-8")
            turn_logs[p.name.removesuffix("-turns.log")] = lines

    part("turn logs", read_turn_logs)
    meta["turn_logs"] = sorted(turn_logs)

    for name in ("heartbeat.txt", "bridge.txt", "papal_trace.txt"):
        src = tr / name
        if src.exists():
            part(name, lambda src=src: shutil.copy2(src, out / src.name))
    hb = part("heartbeat", lambda: read_keys(tr / "heartbeat.txt")) or {}
    cfg = part("bridge.txt", lambda: read_keys(tr / "bridge.txt")) or {}
    meta["game_id"] = cfg.get("game_id")
    meta["turn"] = hb.get("turn")

    def copy_save() -> dict | None:
        sav = newest_save(save_dir)
        if sav is None:
            raise FileNotFoundError(f"no .sav in {save_dir}")
        shutil.copy2(sav, out / sav.name)
        return {
            "name": sav.name,
            "written": dt.datetime.fromtimestamp(sav.stat().st_mtime).isoformat(sep=" ", timespec="seconds"),
        }

    meta["save"] = part("save", copy_save)
    meta["qa_restore_pending"] = (tr / "qa.last_restore").exists()

    merged = part("merge", lambda: last_seconds({"bridge": bridge, **turn_logs}, now)) or []
    meta["problems"] = problems
    meta["seconds"] = round(time.monotonic() - t0, 2)
    part("meta.json", lambda: (out / "meta.json").write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8"))
    (out / "report.md").write_text(render(meta, merged), encoding="utf-8")

    def cap() -> None:
        keep = int(os.environ.get("PARLEY_CRASH_KEEP") or DEFAULT_KEEP)
        prune(root, max(keep, 1))  # never this report itself

    cap_err = len(problems)
    part("cap", cap)
    if len(problems) > cap_err:  # report.md is written: say so in the log line instead
        print(f"crash report: {problems[-1]}", file=sys.stderr)
    return out


def render(meta: dict, merged: list[str]) -> str:
    save = meta.get("save")
    lines = [
        f"# Crash {meta['at']}",
        "",
        f"- game: {meta.get('game_id') or '?'}, turn {meta.get('turn') or '?'} (heartbeat)",
        f"- crash-watch saw: {meta['why']}",
        f"- screenshot: {meta.get('screenshot') or 'none'}",
        "- save: "
        + (f"{save['name']} (written {save['written']}; Continue Campaign reloads it)" if save else "none"),
    ]
    if meta.get("qa_restore_pending"):
        lines.append("- qa.last_restore was present: the relaunch may load the QA keep save instead")
    lines += [
        f"- turn logs: {', '.join(meta.get('turn_logs') or []) or 'none written in the last 10 min'}",
        f"- report took {meta['seconds']} s",
        "",
        "## Guess",
        "",
        "_(fill in: what the game was doing, and the bench case that repeats it)_",
        "",
        "## Repro case",
        "",
        "_(none yet: games/qa/<suite>.toml case name)_",
        "",
        f"## Last {WINDOW} s: bridge and turn loop",
        "",
        "```",
        *(merged or ["(no timestamped lines)"]),
        "```",
        "",
        "Files: bridge.log (last 200 lines), papal.log, turns/, screen-N.png (the game's windows only), the save, heartbeat.txt,"
        " bridge.txt, papal_trace.txt, meta.json.",
    ]
    if meta.get("problems"):
        lines += ["", "## Report problems", "", *(f"- {p}" for p in meta["problems"])]
    return "\n".join(lines) + "\n"


def list_reports(n: int) -> list[str]:
    root = crash_dir()
    if not root.is_dir():
        return []
    names = sorted((p.name for p in root.iterdir() if p.is_dir() and NAME_RE.match(p.name)), reverse=True)
    out = []
    for name in names[:n]:
        d = root / name
        try:
            meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            meta = {}
        last = meta.get("last_bridge_line")
        if last is None:
            try:
                last = (tail_lines(d / "bridge.log", 1) or [""])[0]
            except OSError:
                last = ""
        where = f"{meta.get('game_id') or '?'} t{meta.get('turn') or '?'}"
        out.append(f"{name}  {where}  {meta.get('why', '?')}\n    {str(last)[:160]}")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("write", help="write a crash report now")
    w.add_argument("--why", default="?", help="what crash-watch saw")
    ls = sub.add_parser("list", help="the newest reports and their last bridge line")
    ls.add_argument("-n", type=int, default=10)
    a = ap.parse_args(argv)
    if a.cmd == "write":
        try:
            print(write(a.why))
        except Exception as e:
            print(f"crash report: {type(e).__name__}: {e}", file=sys.stderr)
            return 1
        return 0
    rows = list_reports(a.n)
    print("\n".join(rows) if rows else f"no crash reports in {crash_dir()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
