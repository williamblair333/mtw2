"""No code here captures the whole desktop: only the game's own windows. 11-04 a full-desktop
screenshot caught the user's private windows; 11-05 crash_report.py was found still capturing the
root window before every crash-watch relaunch (on the user's own desktop)."""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
# import -window root, xwd -root, scrot/gnome-screenshot full-screen, ImageGrab.grab() with no box
FULL_SCREEN = re.compile(
    r"""-window["',\s]+["']?root\b|\bxwd\b[^\n]*-root|\bscrot\b|gnome-screenshot|spectacle\s|ImageGrab\.grab\(\)"""
)


def test_no_script_or_module_captures_the_whole_screen():
    hits = []
    for base in ("parley", "scripts", "lua", "tools"):
        for p in (REPO / base).rglob("*"):
            if p.is_file() and p.suffix in {".py", ".sh", ".lua", ""}:
                for n, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                    if FULL_SCREEN.search(line):
                        hits.append(f"{p.relative_to(REPO)}:{n}: {line.strip()[:120]}")
    assert not hits, "whole-screen capture (capture a game window id instead):\n" + "\n".join(hits)


def test_the_pattern_catches_the_old_crash_report_capture():
    assert FULL_SCREEN.search('["import", "-window", "root", str(png)]')
    assert FULL_SCREEN.search("import -window root shot.png")
    assert not FULL_SCREEN.search('["import", "-window", wid, str(path)]')
