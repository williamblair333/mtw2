"""games/forced_events.toml: every event the game can raise has a way to force it, or says why not.
A row only counts as forced when a real, non-chance bench case proves it (STANDARDS forced-events)."""
import re
import tomllib
from pathlib import Path

import pytest

from parley.qa.cases import load_suite

ROOT = Path(__file__).resolve().parent.parent
EVENTS = tomllib.loads((ROOT / "games" / "forced_events.toml").read_text())["events"]
# The work list can only shrink: lower this as cases land, never raise it without adding an event.
MAX_ROUTE_ONLY = 12


def _bridge_game_popups() -> set[str]:
    text = (ROOT / "lua" / "parley_bridge.lua").read_text()
    block = re.search(r"K\.GAME_POPUPS = \{(.*?)\n\}", text, re.S).group(1)
    return set(re.findall(r"(\w+_scroll) =", block))


def test_each_row_has_a_status_it_can_back():
    for name, row in EVENTS.items():
        assert row.get("what"), name
        status = row.get("status")
        assert status in ("forced", "route", "no_route"), name
        if status == "route":
            assert row.get("route"), f"{name}: a route row says what to try"
        if status == "no_route":
            assert row.get("why"), f"{name}: no_route says what was tried"


@pytest.mark.parametrize("name", [n for n, r in EVENTS.items() if r["status"] == "forced"])
def test_a_forced_row_names_a_real_case_that_is_not_left_to_chance(name):
    suite, _, case_name = EVENTS[name]["case"].partition("/")
    cases = {c.name: c for c in load_suite(ROOT / "games" / "qa" / f"{suite}.toml").cases}
    assert case_name in cases, f"{name}: no case {EVENTS[name]['case']}"
    assert not cases[case_name].chance, f"{name}: {case_name} is left to the game's roll"


def test_every_interrupt_event_is_covered():
    interrupts = tomllib.loads((ROOT / "games" / "interrupts.toml").read_text())["events"]
    covered = {r.get("interrupt") for r in EVENTS.values()}
    assert set(interrupts) - covered == set()


def test_every_scroll_the_bridge_knows_is_covered():
    covered = {s for r in EVENTS.values() for s in r.get("scrolls", [])}
    assert _bridge_game_popups() - covered == set()


def test_inventory_rows_named_exist():
    text = (ROOT / "docs" / "decision-inventory.md").read_text()
    rows = set(re.findall(r"^\| *([A-Z]{1,2}\d+) *\|", text, re.M))
    for name, row in EVENTS.items():
        assert set(row.get("inventory", [])) <= rows, name


def test_the_work_list_only_shrinks():
    left = [n for n, r in EVENTS.items() if r["status"] == "route"]
    assert len(left) <= MAX_ROUTE_ONLY, f"{len(left)} events have no proving case: {left}"
