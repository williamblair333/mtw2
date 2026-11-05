"""The no-click guard: X input (xdotool clicks, pointer moves, key presses, window raises; wmctrl
window moves and closes) refused while PARLEY_NO_X_INPUT=1.

The author's rule (10-31): never click the screen when EOP/Lua can do it. A `--kind instant` QA run
(phase 1: every case that needs no clicks) sets the variable for its whole run, so a code path that
would still reach X input fails loudly instead of clicking. Every X-input helper in the repo checks
it: parley/popups.py (click, the pointer move before a screenshot, and _xdo for any xdotool verb
that isn't a read), scripts/relaunch_game.sh's --clicks fallback (before it kills anything), and the
QA runner's QA-loop starter. The default relaunch makes no clicks (hidden EOP launcher, the save
loaded at start-up; 10-31) and runs in a no-click run. Reading the screen (xdotool search/getwindowgeometry,
ImageMagick `import`) is not input and stays allowed: scripts/crash_dialog.sh still looks for Wine's
crash dialog in a no-click run.

The real campaign's loop and crash-watch, restarted by the QA restore, get an environment without
the variable (env_without): the real game still answers its popups by clicking until phase 2."""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager

ENV_VAR = "PARLEY_NO_X_INPUT"
# xdotool verbs that only read the screen or the window list (anything else moves, clicks, types,
# focuses or rearranges something)
XDOTOOL_READS = frozenset({
    "search", "getwindowgeometry", "getmouselocation", "getactivewindow", "getwindowfocus",
    "getwindowname", "getwindowpid", "getdisplaygeometry", "get_desktop", "get_num_desktops",
    "get_desktop_for_window", "version", "help",
})


class XInputRefused(RuntimeError):
    """X input asked for in a no-click run (PARLEY_NO_X_INPUT=1)."""


def no_x_input() -> bool:
    """True in a no-click run: PARLEY_NO_X_INPUT set to anything but empty or 0."""
    return os.environ.get(ENV_VAR, "").strip() not in ("", "0")


def refuse_x_input(what: str) -> None:
    """Raise XInputRefused naming `what` in a no-click run; else return."""
    if no_x_input():
        raise XInputRefused(f"X input refused in a no-click run: {what} ({ENV_VAR}=1)")


def refuse_xdotool(args: tuple[str, ...] | list[str]) -> None:
    """Refuse an xdotool call whose verb isn't a read (XDOTOOL_READS), in a no-click run."""
    verb = str(args[0]) if args else ""
    if verb not in XDOTOOL_READS:
        refuse_x_input("xdotool " + " ".join(str(a) for a in args))


def env_without(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """`env` (default: this process's) without the no-click variable, for the real campaign's
    processes a no-click QA run restarts on its way out."""
    out = dict(os.environ if env is None else env)
    out.pop(ENV_VAR, None)
    return out


@contextmanager
def no_click_run() -> Iterator[None]:
    """Set PARLEY_NO_X_INPUT=1 for the block (and every process started in it), then put back
    whatever was there."""
    before = os.environ.get(ENV_VAR)
    os.environ[ENV_VAR] = "1"
    try:
        yield
    finally:
        if before is None:
            os.environ.pop(ENV_VAR, None)
        else:
            os.environ[ENV_VAR] = before
