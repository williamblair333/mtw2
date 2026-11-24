"""STANDARDS instant-cases: a turn case must check something only a played turn can show.

A turn case whose every check is a `qa: ...` log line reads back what its own setup wrote in the
held turn, and plays turns for nothing (smoke's teleport and skill until 11-05, #443). Such a case
belongs in an instant case. Checks that need a turn: a state value or order result from the next
report, a log line the game or bridge writes as the turn plays, or the game alive after one.
"""

from pathlib import Path

import pytest

from parley.qa.cases import load_suite

SUITES = sorted((Path(__file__).parent.parent / "games" / "qa").glob("*.toml"))


def _flat(expects):
    out = []
    for e in expects:
        out.append(e)
        out.extend(_flat(e.any_of or []))
    return out


def _needs_a_turn(e) -> bool:
    if e.state is not None or e.order_ok is not None or e.alive is not None:
        return True
    if e.log is None:
        return False
    # a pattern that runs past its first line (popups/event_scroll_closed: from "qa: event ok" on to
    # the popup handled as the turn plays) reads more than the setup's own line
    spans = "[\\s\\S]" in e.log or "\\n" in e.log
    return spans or not e.log.startswith("qa: ")


@pytest.mark.parametrize("path", SUITES, ids=lambda p: p.stem)
def test_every_turn_case_checks_something_a_turn_shows(path):
    for case in load_suite(path).cases:
        if case.kind != "turn":
            continue
        assert any(_needs_a_turn(e) for e in _flat(case.expect)), (
            f"{path.stem}/{case.name}: every check is a held-turn 'qa:' log line; make it an instant case")


def test_the_check_catches_the_old_smoke_cases():
    from parley.qa.cases import Case
    old = Case.model_validate({"name": "skill", "expect": [{"log": "qa: skill ok:"}]})
    assert not any(_needs_a_turn(e) for e in _flat(old.expect))
