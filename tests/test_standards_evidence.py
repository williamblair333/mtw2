"""STANDARDS.md evidence the Refinery's standards_check.py can read without crashing.

The checker first tries the whole evidence string as a path (`(project / ev).exists()`). The file
system walks it one "/"-separated segment at a time and stops at the first segment that doesn't
exist; if that segment is longer than a file name may be (255 bytes), it raises "File name too long"
and the checker crashes (11-05: four times in one night, e.g. "games/qa/ has a suite for each...").
Until the checker is fixed, no evidence may reach such a segment.
"""

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
NAME_MAX = 255


def _first_missing_segment(ev: str) -> str | None:
    path = ROOT
    for part in ev.split("/"):
        if len(part.encode("utf-8")) > NAME_MAX:
            return part
        path = path / part
        try:
            if not path.exists():
                return None  # the walk stops here, at a segment short enough to be a name
        except OSError:
            return part
    return None


def test_the_checker_never_meets_an_evidence_segment_too_long_for_a_file_name():
    text = (ROOT / "STANDARDS.md").read_text(encoding="utf-8")
    bad = []
    for m in re.finditer(r"^\s+evidence:\s*(.+)$", text, re.M):
        ev = m.group(1).strip().strip("\"'")
        seg = _first_missing_segment(ev)
        if seg is not None:
            bad.append(seg[:70] + "...")
    assert bad == [], bad


def test_the_check_catches_the_shape_that_crashed():
    assert _first_missing_segment("games/qa/ has a suite for each " + "x" * 300) is not None
    # a shorter missing segment first: the walk stops there (the 326-byte stretch that passed on 11-05)
    assert _first_missing_segment("scripts/crash_report.py, see (tests/x.py), then " + "x" * 300) is None
