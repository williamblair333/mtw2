"""scripts/trend_new.sh: the campaign watch wakes for a new trend alert, not for an old one whose numbers
moved. Live 11-06: "france: median answer time slowed to 508.0s (earlier 297.3s, 1.7x)" woke the watch again
as "... (earlier 291.4s, 1.7x)", about ten minutes after it was rearmed."""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SLOW = "france: median answer time slowed to 508.0s (earlier 297.3s, 1.7x)"


def new(tmp_path, seen, now):
    a, b = tmp_path / "seen", tmp_path / "now"
    a.write_text(seen)
    b.write_text(now)
    r = subprocess.run(["bash", str(ROOT / "scripts" / "trend_new.sh"), str(a), str(b)],
                       capture_output=True, text=True, check=True)
    return r.stdout.splitlines()


def test_the_same_alert_with_new_numbers_is_not_new(tmp_path):
    moved = "france: median answer time slowed to 508.0s (earlier 291.4s, 1.7x)"
    assert new(tmp_path, SLOW + "\n", moved + "\n") == []


def test_a_different_alert_is_new_and_keeps_its_numbers(tmp_path):
    lost = "england: lost a town on turn 41"
    assert new(tmp_path, SLOW + "\n", SLOW + "\n" + lost + "\n") == [lost]


def test_another_ruler_slowing_is_new(tmp_path):
    other = "england: median answer time slowed to 400.0s (earlier 200.0s, 2.0x)"
    assert new(tmp_path, SLOW + "\n", other + "\n") == [other]


def test_with_nothing_seen_every_alert_is_new(tmp_path):
    # the usual awk idiom (NR==FNR) reads the second file as the first when the first is empty
    assert new(tmp_path, "", SLOW + "\n") == [SLOW]


def test_blank_lines_are_not_alerts(tmp_path):
    assert new(tmp_path, "", "\n\n") == []


def test_the_watch_uses_it():
    text = (ROOT / "scripts" / "campaign_watch.sh").read_text()
    assert "scripts/trend_new.sh" in text
    assert "comm -13" not in text
