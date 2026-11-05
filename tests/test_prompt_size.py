"""The prompt stays lean: a size budget on a real turn, and what is trimmed or grouped to get there."""

import json

from conftest import FIXTURES
from parley.control import PRESETS
from parley.prompt import (DIPLOMACY_CHARS, DIPLOMACY_SHOWN, NOTES_SHOWN, RESOURCES_SHOWN, build_prompt,
                           diplomacy_section)
from parley.protocol import Agent, FactionView, StateReport, TradeResource, Unit

ALL_AREAS = ("diplomacy", "armies", "agents", "build", "recruit", "taxes")

# England, turn 39 of run "scratch" (a real 45 KB prompt): code-generated parts only, a fixed persona
# and adviser, no notes or diplomacy. Before the cuts this was 28012 characters.
TURN39_BUDGET = 27538  # 25200 + 2238 (parley/strategy/england.md) + 100 margin (10-30); includes the primer's rules of thumb (1.5 KB); +1000 with the primer cap (playbook);
# +400 (10-30): free-upkeep marks in recruit lists and the siege/reinforcement primer lines


def test_primer_has_rules_of_thumb_and_stays_brief():
    from parley.prompt import primer
    text = primer()
    rules = text.split("### 9. Rules of thumb")[1].strip().splitlines()
    assert 10 <= len(rules) <= 15 and all(r.startswith("- ") for r in rules)
    assert len(text) <= 7000  # it is in every prompt (raised from 6000 for the strategy playbook)


def turn39() -> StateReport:
    return StateReport.model_validate(json.loads((FIXTURES / "state_turn39_england.json").read_text()))


def test_turn39_prompt_stays_within_its_size_budget():
    p = build_prompt(turn39(), persona="p", adviser="lord_ipsi", areas=ALL_AREAS)
    assert len(p) <= TURN39_BUDGET


def test_turn39_prompt_keeps_what_the_ruler_acts_on():
    p = build_prompt(turn39(), persona="p", adviser="lord_ipsi", areas=ALL_AREAS)
    for fact in ("- London (London)", "- Nottingham (Nottingham)", "- Caen (Caen)",
                 "can build (florins/turns): mines 2000/2",
                 "can recruit (florins/turns, upkeep a turn): Town Militia 290/1, free upkeep (3 left)",
                 "free-upkeep slots 3 of 3 left", "cog 500/1, upkeep 150",
                 "Haakon Svendsen (denmark): 14 units, 823 men", "- York (scotland): garrison 6 units, 402 men",
                 "- scotland (Scotland): alliance for 13 turns", "Income items: army upkeep -4563"):
        assert fact in p, fact


def _msg_lines(n):
    return [f"[turn {i}] [public] Somebody (x): {'word ' * 200}end{i}" for i in range(n)]


def test_diplomacy_shows_the_latest_lines_cut_short_and_counts_the_rest():
    text = diplomacy_section(_msg_lines(DIPLOMACY_SHOWN + 5))
    assert "(5 older messages not shown)" in text
    assert "end4" not in text and f"[turn {DIPLOMACY_SHOWN + 4}]" in text
    assert all(len(line) <= DIPLOMACY_CHARS for line in text.split("\n")[3:])


def test_short_diplomacy_is_shown_whole():
    text = diplomacy_section(["[turn 1] [public] A (a): hi"])
    assert "older messages" not in text and "hi" in text


def test_only_the_latest_notes_are_replayed(venice_report):
    notes = [(t, f"note number {t}") for t in range(1, NOTES_SHOWN + 4)]
    p = build_prompt(venice_report, persona="p", notes=notes)
    assert f"note number {NOTES_SHOWN + 3}" in p and "note number 1" not in p


def test_identical_units_are_counted_not_repeated(venice_report):
    army = venice_report.armies[0].model_copy(update={
        "troops": [Unit(type="Knights", soldiers=40, max_soldiers=40)] * 4 + [Unit(type="Spears", soldiers=51, max_soldiers=75)]})
    p = build_prompt(venice_report.model_copy(update={"armies": [army]}), persona="p", areas=ALL_AREAS)
    assert "4x Knights 40/40 exp 0; Spears 51/75 exp 0" in p


def test_agents_standing_together_share_a_line_with_all_their_names(venice_report):
    spies = [Agent(id=n, kind="spy", faction="hre", x=1, y=2, distance=1) for n in ("Ann", "Bob", "Cy")]
    p = build_prompt(venice_report.model_copy(update={"seen_agents": spies}), persona="p")
    assert "- hre spy at (1,2), 1 tile away: Ann, Bob, Cy" in p


def test_quiet_far_factions_are_grouped_but_war_and_rulers_stay_in_full(venice_report):
    fs = [FactionView(id="spain", name="Spain", stance="peace", settlements=2, capital="Leon", leader="Al", armies=7),
          FactionView(id="hre", name="HRE", stance="war", settlements=9, capital="Frankfurt", leader="Heinrich", armies=16),
          FactionView(id="france", name="France", stance="peace", settlements=7, capital="Paris", leader="Philip", armies=11)]
    p = build_prompt(venice_report.model_copy(update={"factions": fs}), persona="p",
                     names={"france": "France"})
    assert "spain (2)" in p and "capital Leon" not in p
    assert "- hre (HRE): war" in p and "capital Frankfurt" in p
    assert "- france (France): peace" in p and "capital Paris" in p and ", has a ruler" in p


def test_far_trade_resources_are_cut_off_with_a_count(venice_report):
    res = [TradeResource(kind="wool", x=i, y=i, distance=i + 1) for i in range(RESOURCES_SHOWN + 4)]
    p = build_prompt(venice_report.model_copy(update={"resources": res}), persona="p")
    assert p.count("- wool at") == RESOURCES_SHOWN and "(and 4 farther ones)" in p


def test_faction_note_is_empty_without_a_file():
    from parley.prompt import faction_note
    assert faction_note("no_such_faction") == "" and faction_note("") == "" and faction_note("../primer") == ""


def test_england_prompt_has_its_note_after_the_primer_and_others_do_not(venice_report):
    from parley.prompt import faction_note, primer
    note = faction_note("england")
    assert note and len(note) <= 2500
    p = build_prompt(turn39(), persona="p", areas=ALL_AREAS)
    head = "HOW ENGLAND WINS (strategy notes for your faction; your report takes precedence)\n"
    assert head + note in p
    assert p.index(primer()) < p.index(head)
    other = build_prompt(venice_report, persona="p", areas=ALL_AREAS)
    assert "WINS (strategy notes" not in other and note not in other
