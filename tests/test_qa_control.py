import threading
import time
from pathlib import Path

import pytest

from parley.qa.control import Control, ControlTimeout


def test_run_lua_appends_line_and_returns_logged_result(tmp_path: Path):
    control_file = tmp_path / "control.txt"
    log_file = tmp_path / "parley_bridge.log"
    control_file.write_text("scan before\n", encoding="utf-8")

    def fake_bridge():
        time.sleep(0.05)
        with log_file.open("a", encoding="utf-8") as f:
            f.write("2026-10-30 15:29:51 qa: where ok: 115,81\n")
            f.write("2026-10-30 15:29:52 control: lua -> 115,81\n")

    t = threading.Thread(target=fake_bridge)
    t.start()
    try:
        ctrl = Control(tmp_path, timeout=1.0)
        result = ctrl.run_lua("return M.qa.where('Marco')")
    finally:
        t.join()

    assert result == "115,81"
    assert control_file.read_text(encoding="utf-8") == (
        "scan before\nlua return M.qa.where('Marco')\n"
    )


def test_run_lua_times_out_with_clear_error(tmp_path: Path):
    ctrl = Control(tmp_path, timeout=0.1)
    assert ctrl.log_offset() == 0
    line = "return M.qa.load('missing.sav')"
    with pytest.raises(ControlTimeout) as exc_info:
        ctrl.run_lua(line)
    msg = str(exc_info.value)
    assert line in msg
    assert str(tmp_path) in msg


def test_run_lua_ignores_older_log_lines(tmp_path: Path):
    log_file = tmp_path / "parley_bridge.log"
    log_file.write_text(
        "2026-10-30 15:29:00 control: lua -> stale_result\n",
        encoding="utf-8",
    )
    ctrl = Control(tmp_path, timeout=1.0)
    assert ctrl.log_offset() == log_file.stat().st_size

    def fake_bridge():
        time.sleep(0.05)
        with log_file.open("a", encoding="utf-8") as f:
            f.write("2026-10-30 15:29:52 control: lua -> fresh_result\n")

    t = threading.Thread(target=fake_bridge)
    t.start()
    try:
        result = ctrl.run_lua("return 'fresh_result'")
    finally:
        t.join()

    assert result == "fresh_result"
