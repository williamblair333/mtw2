"""scripts/work_until.sh: a standing order ("work until 23:00") holds the Stop hook until then."""
import json
import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "work_until.sh"


def run(tmp_path, *args, now=None):
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path)}
    if now is not None:
        env["WORK_UNTIL_NOW"] = str(now)
    (tmp_path / ".claude").mkdir(exist_ok=True)
    return subprocess.run(["bash", str(SCRIPT), *args], input="{}", capture_output=True, text=True, env=env)


def test_no_order_never_blocks(tmp_path):
    out = run(tmp_path, "hook")
    assert out.returncode == 0 and out.stdout == ""


def test_an_order_ahead_blocks_the_stop_with_the_reason(tmp_path):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "work-until.local").write_text("2026-11-05T23:00-05:00\n")
    now = int(subprocess.run(["date", "-d", "2026-11-05T06:31-05:00", "+%s"], capture_output=True, text=True).stdout)
    out = run(tmp_path, "hook", now=now)
    d = json.loads(out.stdout)
    assert d["decision"] == "block"
    assert "2026-11-05T23:00" in d["reason"] and "989 min left" in d["reason"]


def test_a_passed_or_broken_order_lets_the_turn_end(tmp_path):
    (tmp_path / ".claude").mkdir()
    f = tmp_path / ".claude" / "work-until.local"
    f.write_text("2026-11-05T23:00-05:00\n")
    after = int(subprocess.run(["date", "-d", "2026-11-05T23:01-05:00", "+%s"], capture_output=True, text=True).stdout)
    out = run(tmp_path, "hook", now=after)
    assert out.returncode == 0 and out.stdout == "" and "has passed" in out.stderr
    f.write_text("not a date\n")
    out = run(tmp_path, "hook")
    assert out.returncode == 0 and out.stdout == "" and "unreadable" in out.stderr


def test_set_show_off(tmp_path):
    assert "work until" in run(tmp_path, "set", "23:00").stdout
    assert (tmp_path / ".claude" / "work-until.local").exists()
    assert "work until" in run(tmp_path, "show").stdout
    assert run(tmp_path, "set", "25:00").returncode == 2
    run(tmp_path, "off")
    assert "no standing order" in run(tmp_path, "show").stdout
