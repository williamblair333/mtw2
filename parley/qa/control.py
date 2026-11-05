"""Drive the running M2TWEOP Lua bridge through <turn_root>/control.txt."""

from __future__ import annotations

import time
from pathlib import Path

LOG_FILE = "parley_bridge.log"
CONTROL_FILE = "control.txt"
LUA_RESULT_PREFIX = "control: lua -> "
POLL_INTERVAL = 0.5


class ControlTimeout(TimeoutError):
    """Raised when the bridge does not log a result for a control.txt Lua line in time."""


class Control:
    def __init__(self, turn_root: Path, timeout: float = 30.0) -> None:
        self.turn_root = Path(turn_root)
        self.timeout = timeout

    @property
    def _log_path(self) -> Path:
        return self.turn_root / LOG_FILE

    @property
    def _control_path(self) -> Path:
        return self.turn_root / CONTROL_FILE

    def log_offset(self) -> int:
        try:
            return self._log_path.stat().st_size
        except FileNotFoundError:
            return 0

    def send_lua(self, line: str) -> int:
        """Write one control line; returns the log offset its answer comes after (result_after)."""
        offset = self.log_offset()
        with self._control_path.open("a", encoding="utf-8") as f:
            f.write(f"lua {line}\n")
        return offset

    def result_after(self, offset: int) -> str | None:
        """The first control answer logged after `offset`, or None when there is none yet."""
        return self._read_result_after(offset)

    def run_lua(self, line: str) -> str:
        offset = self.send_lua(line)

        deadline = time.monotonic() + self.timeout
        while True:
            result = self._read_result_after(offset)
            if result is not None:
                return result
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ControlTimeout(
                    f"timed out after {self.timeout}s waiting for bridge response to "
                    f"`lua {line}` in {self.turn_root}"
                )
            time.sleep(min(POLL_INTERVAL, remaining))

    def _read_result_after(self, offset: int) -> str | None:
        try:
            with self._log_path.open("rb") as f:
                f.seek(offset)
                data = f.read()
        except FileNotFoundError:
            return None

        text = data.decode("utf-8", errors="replace")
        for raw_line in text.splitlines():
            if LUA_RESULT_PREFIX in raw_line:
                _, _, result = raw_line.partition(LUA_RESULT_PREFIX)
                return result
        return None
