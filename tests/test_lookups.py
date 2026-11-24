"""Ruler lookups (spec docs/superpowers/specs/2026-11-23-ruler-lookups-design.md): a short prompt,
towns in full on request, nothing lost."""
import json
from pathlib import Path

from parley.config import GameConfig, SeatConfig
from parley.control import AREAS
from parley.orchestrator import Orchestrator
from parley.prompt import LOOKUP_LEGEND, build_prompt, town_details
from parley.protocol import Orders, StateReport
from parley.seats import FakeSeat
from parley.seats.base import to_orders

FRANCE = Path(__file__).parent / "fixtures" / "prompt_size" / "france_turn3474_state.json"


def _france():
    return StateReport.model_validate(json.loads(FRANCE.read_text()))


def _section(p, head, end):
    start = p.index(head)
    return p[start:p.index(end, start)]


def _blocks(text):
    """Entries that start "- " with their indented lines, keyed by their first line."""
    out, cur = {}, None
    for line in text.splitlines():
        if line.startswith("- "):
            cur = line
            out[cur] = []
        elif line.startswith("  ") and cur:
            out[cur].append(line)
    return out


def test_a_seat_without_lookups_gets_no_lookup_text():
    p = build_prompt(_france(), persona="p", areas=AREAS)
    assert LOOKUP_LEGEND not in p and "- lookup:" not in p and "UNIT PRICES" in p


def test_the_short_prompt_leaves_out_town_detail_and_keeps_what_a_ruler_acts_on():
    r = _france()
    full = build_prompt(r, persona="p", areas=AREAS)
    short = build_prompt(r, persona="p", areas=AREAS, lookups=True)
    towns = _section(short, "YOUR SETTLEMENTS\n", "\nYOUR ARMIES")
    assert LOOKUP_LEGEND in towns and "- lookup:" in short
    assert "UNIT PRICES" not in towns and ", buildings: " not in towns and "can recruit:" not in towns
    assert len(short) < 0.75 * len(full)
    for s in r.settlements:
        assert f"population {s.population}" in towns
        for b in s.can_build:
            assert f"{b.building} {b.cost}/{b.turns}" in towns
        if s.order_parts and s.public_order < 100:  # unrest: its causes stay in view
            assert f"public order {s.public_order}% (" in towns
    armies = _section(short, "YOUR ARMIES", "\nYOUR AGENTS")
    for head, sub in _blocks(armies).items():
        if head.startswith("- garrison:"):
            assert not any(x.startswith("  troops:") for x in sub), head


def test_town_all_returns_every_town_entry_exactly_as_the_full_prompt_prints_it():
    r = _france()
    full = build_prompt(r, persona="p", areas=AREAS)
    details = town_details(r, ["town:all"], AREAS)
    full_towns = _blocks(_section(full, "YOUR SETTLEMENTS\n", "\nYOUR ARMIES"))
    got = _blocks(details)
    for head, sub in full_towns.items():
        assert got.get(head) == sub, head
    full_armies = _blocks(_section(full, "YOUR ARMIES", "\nYOUR AGENTS"))
    for head, sub in full_armies.items():
        if head.startswith("- garrison:"):
            troops = [x for x in sub if x.startswith("  troops:")]
            assert [x for x in got[head] if x.startswith("  troops:")] == troops, head


def test_one_town_comes_with_its_garrison_and_prices_and_a_wrong_key_says_so():
    r = _france()
    s = next(x for x in r.settlements if x.can_recruit and any(a.id == f"garrison:{x.id}" for a in r.armies))
    d = town_details(r, [f"town:{s.id}", "town:Atlantis"], AREAS)
    assert d.startswith("DETAILS YOU ASKED FOR\nUNIT PRICES")
    assert f"\n- {s.id}" in d and f"\n- garrison:{s.id}: " in d
    assert all(f"- {u.unit} " in d or f"- {u.unit}\n" in d for u in s.can_recruit)
    assert "- town:Atlantis: not a town of yours" in d


def test_a_short_garrison_still_says_what_merge_units_would_combine():
    # Live 11-23 turn 4525: the short garrison had no troop list and no merge line, and France
    # ordered merge_units on three garrisons with nothing to merge; all three were refused.
    from parley.prompt import _own_army
    from parley.protocol import Unit
    r = _france()
    g = next(a for a in r.armies if a.id.startswith("garrison:"))

    def short(*troops):
        units = [Unit(type=t, soldiers=n, max_soldiers=m) for t, n, m in troops]
        return _own_army(g.model_copy(update={"troops": units}), AREAS, brief=True)

    two_worn = short(("Pike Militia", 50, 75), ("Pike Militia", 40, 75))
    assert "\n  merge_units would combine: Pike Militia (50/75, 40/75)" in two_worn
    assert "troops:" not in two_worn
    one_worn = short(("Pike Militia", 50, 75), ("Town Militia", 75, 75))
    assert "merge_units" not in one_worn
    assert "no merge_units line has nothing to merge" in LOOKUP_LEGEND


def test_a_town_key_matches_whatever_its_case_or_spacing():
    # Live 11-23: France asked for town:helsinki and town:smyrna on 12 turns and got
    # "not a town of yours" each time, because ids are Helsinki and Smyrna.
    r = _france()
    s = next(x for x in r.settlements if any(a.id == f"garrison:{x.id}" for a in r.armies))
    exact = town_details(r, [f"town:{s.id}"], AREAS)
    for key in (f"town:{s.id.lower()}", f"town:{s.id.upper()}", f"town: {s.id.replace('_', ' ')} ",
                f"TOWN:{s.id}"):
        assert town_details(r, [key], AREAS) == exact, key
    spaced = next((x for x in r.settlements if "_" in x.id), None)
    if spaced is not None:
        d = town_details(r, [f"town:{spaced.id.replace('_', ' ').lower()}"], AREAS)
        assert "not a town of yours" not in d


def test_the_short_family_and_the_family_lookup_hold_every_line_of_the_full_list():
    r = _france()
    full = build_prompt(r, persona="p", areas=AREAS)
    short = build_prompt(r, persona="p", areas=AREAS, lookups=True)
    whole = _section(full, "YOUR FAMILY", "\n\n").splitlines()[1:]
    brief = _section(short, "YOUR FAMILY", "\n\n").splitlines()[1:]
    looked = town_details(r, ["family"], AREAS).split("YOUR FAMILY", 1)[1].splitlines()[1:]
    assert looked == whole
    assert len("\n".join(brief)) < 0.7 * len("\n".join(whole))
    assert brief[-1].startswith("- and ") and 'lookup "family"' in brief[-1]
    for line in whole:  # every general, leader, heir and princess stays in the short list
        if any(w in line for w in (", general", ", leader", ", heir", "princess")):
            assert line in brief, line


def test_agents_of_one_kind_on_one_spot_share_a_line():
    from parley.prompt import _agent_lines
    from parley.protocol import Agent
    a = [Agent(id="Hugh", kind="priest", x=1, y=2), Agent(id="Ives", kind="priest", x=1, y=2),
         Agent(id="Jean", kind="spy", x=1, y=2), Agent(id="Odo, the Elder", kind="priest", x=5, y=5),
         Agent(id="Paul, the Younger", kind="priest", x=5, y=5)]
    assert _agent_lines(a) == ["- 2 priests at (1,2): Hugh, Ives", "- Jean: spy, at (1,2)",
                               "- Odo, the Elder: priest, at (5,5)", "- Paul, the Younger: priest, at (5,5)"]


def test_to_orders_reads_a_lookup_list_or_one_key():
    ids = dict(game_id="g", turn=1, faction="france")
    assert to_orders({"orders": [], "lookup": ["town:Paris", 3]}, **ids).lookup == ["town:Paris"]
    assert to_orders({"orders": [], "lookup": "town:all"}, **ids).lookup == ["town:all"]
    assert to_orders({"orders": []}, **ids).lookup == []


class _Recorder:
    """Answers with the given payloads in turn and keeps every prompt it was asked."""

    name = "rec"

    def __init__(self, *payloads):
        self.payloads, self.prompts, self.timeouts = list(payloads), [], []

    def decide(self, prompt, *, game_id, turn, faction, timeout):
        self.prompts.append(prompt)
        self.timeouts.append(timeout)
        p = self.payloads.pop(0)
        return to_orders(p, game_id=game_id, turn=turn, faction=faction), json.dumps(p)


def _orch(tmp_path, lookups):
    (tmp_path / "saves").mkdir(exist_ok=True)
    (tmp_path / "mods" / "parley" / "saves").mkdir(parents=True, exist_ok=True)
    cfg = GameConfig(game_id="test", turn_root=tmp_path / "turns", save_dir=tmp_path / "saves",
                     backup_dir=tmp_path / "backups",
                     seats={"france": SeatConfig(brain="fake", persona="p", control="full", lookups=lookups)})
    return Orchestrator(cfg, {"france": FakeSeat()}), cfg.seats["france"]


def test_a_lookup_answer_gets_the_details_and_a_second_ask(tmp_path):
    orch, seat_cfg = _orch(tmp_path, lookups=True)
    r = _france()
    town = r.settlements[0].id
    seat = _Recorder({"orders": [], "lookup": [f"town:{town}"]}, {"orders": [], "note": "done"})
    d = tmp_path / "turn-1" / "france"
    d.mkdir(parents=True)
    orders, raw, asked = orch._ask(seat, "PROMPT", d, r, seat_cfg, dict(game_id="test", turn=1, faction="france"))
    assert orders.note == "done" and len(seat.prompts) == 2
    assert seat.prompts[1].startswith("PROMPT\nDETAILS YOU ASKED FOR") and asked == seat.prompts[1]
    assert "no more lookups this turn" in seat.prompts[1]
    assert (d / "lookup.txt").read_text().startswith("DETAILS YOU ASKED FOR")
    assert json.loads((d / "answer1.txt").read_text())["lookup"] == [f"town:{town}"]
    assert seat.timeouts[1] <= seat.timeouts[0]


def test_a_seat_without_lookups_ignores_a_lookup_answer(tmp_path):
    orch, seat_cfg = _orch(tmp_path, lookups=False)
    seat = _Recorder({"orders": [], "lookup": ["town:all"], "note": "x"})
    d = tmp_path / "turn-1" / "france"
    d.mkdir(parents=True)
    orders, _, asked = orch._ask(seat, "PROMPT", d, _france(), seat_cfg,
                                 dict(game_id="test", turn=1, faction="france"))
    assert len(seat.prompts) == 1 and asked == "PROMPT" and not (d / "lookup.txt").exists()
    assert isinstance(orders, Orders)
