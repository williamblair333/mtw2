"""A machine that powers off on a schedule (the test laptop: down at 23:59 local, back at 03:00) cuts a QA
run in half: the game dies mid-case and the real campaign stays parked until someone restores it.
`power_off_refusal` says why a run may not start now, from PARLEY_POWER_OFF ("HH:MM", local time).

The variable lives in ~/.config/environment.d/parley.conf on that machine; a shell over ssh doesn't
read that file, so it is read here too when the environment doesn't carry the variable.
"""

from __future__ import annotations

import datetime as _dt
import os
import re
from pathlib import Path

ENV_FILE = Path.home() / ".config" / "environment.d" / "parley.conf"
# the full no-click bench ran its ~75 instant cases in 38 min on the test laptop (11-04): ~30 s a case.
# Estimate high, since a slow case or a relaunch costs minutes, and add the park, bench load and restore.
SECONDS_PER_CASE = 40
FIXED_SECONDS = 8 * 60


def power_off_time(environ: dict[str, str] | None = None, env_file: Path = ENV_FILE) -> _dt.time | None:
    """The daily power-off time, or None when this machine has none set."""
    environ = os.environ if environ is None else environ
    raw = environ.get("PARLEY_POWER_OFF")
    if raw is None and env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            m = re.match(r"\s*PARLEY_POWER_OFF\s*=\s*(.*?)\s*$", line)
            if m:
                raw = m.group(1).strip("\"'")
    if not raw:
        return None
    m = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", raw.strip())
    if not m:
        raise ValueError(f"PARLEY_POWER_OFF={raw!r}: expected HH:MM (local time)")
    return _dt.time(int(m.group(1)), int(m.group(2)))


def estimate_seconds(n_cases: int) -> int:
    return FIXED_SECONDS + SECONDS_PER_CASE * n_cases


def power_off_refusal(now: _dt.datetime, n_cases: int, off: _dt.time | None) -> str | None:
    """Why a run of `n_cases` may not start at `now` (local), or None when it ends before power-off."""
    if off is None:
        return None
    off_at = now.replace(hour=off.hour, minute=off.minute, second=0, microsecond=0)
    if off_at <= now:
        off_at += _dt.timedelta(days=1)
    need = estimate_seconds(n_cases)
    left = (off_at - now).total_seconds()
    if need <= left:
        return None
    return (f"this machine powers off at {off.strftime('%H:%M')} (PARLEY_POWER_OFF), {int(left // 60)} min "
            f"from now, and {n_cases} case(s) need about {need // 60} min; run fewer cases (case=...) "
            f"or start after it powers back on")
