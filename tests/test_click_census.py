import importlib.util
import logging
from pathlib import Path

from parley import popups

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("click_census", ROOT / "scripts" / "click_census.py")
cc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cc)


def test_every_press_logs_a_census_line(caplog):
    # 11-14: the turn loop's clicks named no message, so nobody could list what still clicks
    caplog.set_level(logging.INFO, logger="parley.popups")
    popups.census("accept", {"id": "popup-6-1", "kind": None, "event": 75})
    popups.census("decline", {"id": "popup-6-2", "kind": "marriage", "event": 15}, wife=True)
    lines = [r.getMessage() for r in caplog.records]
    assert lines == ["x-input: action=accept event=75 id=popup-6-1",
                     "x-input: action=decline kind=marriage event=15 id=popup-6-2 wife=True"]


def test_the_census_tallies_by_decision_and_counts_refusals(tmp_path):
    log = tmp_path / "qa-x-turns.log"
    log.write_text(
        "2026-11-14 INFO popup x-input: action=accept event=75 id=popup-6-1\n"
        "2026-11-14 INFO popup x-input: action=accept event=75 id=popup-7-1\n"
        "2026-11-14 INFO popup x-input: action=decline kind=marriage event=15 id=popup-6-2\n"
        "2026-11-14 ERROR popup popup-6-2: click failed: X input refused in a no-click run: click decline\n")
    seen = cc.parse(log.read_text().splitlines())
    assert seen[("accept", "-", "75", "-", "-")] == 2
    assert seen[("decline", "marriage", "15", "-", "-")] == 1
    assert cc.refused(log.read_text().splitlines()) == 1
    assert cc.table(seen).splitlines()[2] == "| 2 | accept | - | 75 | - | - |"
