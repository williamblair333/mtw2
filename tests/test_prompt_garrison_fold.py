"""Garrisons that only repeat their town's line fold into one line; "str N" is defined once per section.

Live 11-25 (France, turn 4923, lookups on): 52 of 57 garrison lines in YOUR ARMIES repeated the town's
own "garrison N units, M men (strength rating S, not men)" word for word (~3.1 KB), and the strength
phrase appeared 113 times (3.5 KB). The prompt went from 59.4 KB to 53.9 KB with nothing lost.
"""
import json
from pathlib import Path

from parley.control import AREAS
from parley.prompt import STR_NOTE, build_prompt
from parley.protocol import StateReport

FRANCE = Path(__file__).parent / "fixtures" / "prompt_size" / "france_turn3474_state.json"


def _report():
    return StateReport.model_validate(json.loads(FRANCE.read_text()))


def _armies(p):
    start = p.index("YOUR ARMIES")
    return p[start:p.index("\n\n", start)]


def test_every_garrison_id_is_still_named_and_folded_ones_match_their_town():
    r = _report()
    p = build_prompt(r, persona="p", areas=AREAS, lookups=True)
    armies = _armies(p)
    fold = next((ln for ln in armies.splitlines() if ln.startswith("- garrison:<town> for ")), "")
    folded = fold.removeprefix("- garrison:<town> for ").split(": each one's")[0].split(", ") if fold else []
    assert folded, "some garrisons fold on France's report"
    towns = {s.id: s for s in r.settlements}
    for a in r.armies:
        if not a.id.startswith("garrison:"):
            continue
        town = a.in_settlement
        if town in folded:
            s = towns[town]
            assert f"\n- {a.id}:" not in armies
            assert (s.garrison_units, s.garrison_strength) == (a.units, a.strength) and not a.leader
        else:
            assert f"\n- {a.id}:" in armies, a.id


def test_a_garrison_with_a_general_keeps_its_own_line():
    r = _report()
    g = next(a for a in r.armies if a.id.startswith("garrison:") and not a.leader)
    led = g.model_copy(update={"leader": "Captain Test"})
    r = r.model_copy(update={"armies": [led if a is g else a for a in r.armies]})
    armies = _armies(build_prompt(r, persona="p", areas=AREAS, lookups=True))
    assert f"\n- {g.id}:" in armies and "Captain Test" in armies


def test_nothing_folds_without_lookups():
    # the full prompt prints each garrison's troops, which its town's line doesn't
    assert "- garrison:<town> for " not in build_prompt(_report(), persona="p", areas=AREAS)


def test_str_is_defined_where_it_is_first_used_and_the_long_phrase_is_gone():
    p = build_prompt(_report(), persona="p", areas=AREAS, lookups=True)
    assert p.index(f"({STR_NOTE})") < p.index(", str ")
    assert "not men)" not in p
