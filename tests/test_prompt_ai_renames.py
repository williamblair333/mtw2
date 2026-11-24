"""An AI-run realm's ruler is told its armies' ids change between turns (live 11-05, run 10)."""

from parley.control import AREAS
from parley.prompt import PRESETS, role


def test_ai_run_rulers_are_told_their_army_ids_change_and_the_human_slot_is_not():
    for areas in (PRESETS["ruler"], AREAS):
        text = role(areas, False)
        assert "renames their captains between your turns" in text, areas
        assert "use army ids exactly as this report lists them" in text, areas
    assert "renames their captains" not in role(AREAS, True)
