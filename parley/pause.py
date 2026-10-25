"""Pausing the game while the rulers can't answer (a seat's usage limit).

`<turn_root>/paused.txt` holds the reason. While it exists the bridge ends no turn, presses no
default on any decision and runs no stuck recovery, so nothing is decided for the rulers; the
turn loop retries every RETRY seconds and removes it once a ruler answers. Deleting the file
by hand resumes too.
"""

import os
import time
from pathlib import Path

from parley.bridge import atomic_write

RETRY = 300  # seconds between tries while paused


def path(turn_root: Path) -> Path:
    return Path(turn_root) / "paused.txt"


def pause(turn_root: Path, reason: str) -> None:
    atomic_write(path(turn_root), reason.strip().splitlines()[0][:200] + "\n")


def paused(turn_root: Path) -> bool:
    return path(turn_root).exists()


def resume(turn_root: Path) -> None:
    """Lift the pause; popup requests held through it count as fresh again (the turn loop
    treats an old request as a leftover from a bridge reload)."""
    if not paused(turn_root):
        return
    path(turn_root).unlink(missing_ok=True)
    now = time.time()
    for req in Path(turn_root).glob("popup-*.req"):
        try:
            os.utime(req, (now, now))
        except OSError:
            pass
