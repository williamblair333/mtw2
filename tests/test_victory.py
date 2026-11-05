"""Victory conditions and the turn limit, read from the game's own campaign files."""

from parley.victory import turn_limit, victory_line, win_conditions

WIN = ("france\r\nhold_regions Jerusalem_Province\r\ntake_regions 45\r\nshort_campaign hold_regions ;Jerusalem_Province\r\n"
       "take_regions 20\r\noutlive england\r\n\r\n"
       "england\r\nhold_regions Jerusalem_Province\r\ntake_regions 45\r\nshort_campaign hold_regions ;Jerusalem_Province\r\n"
       "take_regions 15\r\noutlive france scotland\r\n")
STRAT = "campaign\t\timperial_campaign\nstart_date\t1080 summer\nend_date\t1530 winter\ntimescale\t2.00\n"


def test_win_conditions_split_long_and_short():
    goals = win_conditions(WIN)
    assert goals["england"]["long"] == {"hold": ["Jerusalem_Province"], "take": 45}
    assert goals["england"]["short"] == {"hold": [], "take": 15, "outlive": ["france", "scotland"]}


def test_victory_line_shows_the_settlements_of_the_factions_to_outlive(tmp_path):
    from parley.protocol import FactionView
    (tmp_path / "descr_win_conditions.txt").write_text(WIN)
    (tmp_path / "descr_strat.txt").write_text(STRAT)
    fv = lambda i, n: FactionView(id=i, name=i.title(), stance="neutral", settlements=n)  # noqa: E731
    facs = [fv("england", 5), fv("france", 7), fv("scotland", 2), fv("hre", 9)]
    short = victory_line("england", 0, 5, tmp_path, "short", factions=facs)
    assert ("outlive france and scotland. France holds 7 settlements, Scotland holds 2 settlements. "
            "The campaign ends") in short
    one = victory_line("england", 0, 5, tmp_path, "short", factions=[fv("france", 1), fv("scotland", 0)])
    assert "France holds 1 settlement, Scotland is destroyed (0 settlements)." in one
    assert "Scotland" not in victory_line("england", 0, 5, tmp_path, "short", factions=[fv("france", 3)]).split("outlive")[1].split(".")[1]
    # the long campaign has nothing to outlive, and no factions list changes nothing
    assert "holds" not in victory_line("england", 71, 5, tmp_path, factions=facs)
    assert victory_line("england", 0, 5, tmp_path, "short") == victory_line("england", 0, 5, tmp_path, "short", factions=[])


def test_turn_limit_is_years_over_years_a_turn():
    assert turn_limit(STRAT) == 225  # the game showed "Turns remaining: 225" on turn 1


def test_victory_line_states_the_goal_progress_and_turns_left(tmp_path):
    (tmp_path / "descr_win_conditions.txt").write_text(WIN)
    (tmp_path / "descr_strat.txt").write_text(STRAT)
    line = victory_line("england", 71, 5, tmp_path)
    assert line == ("To win the campaign: hold Jerusalem, rule 45 regions in all (you hold 5). "
                    "The campaign ends after turn 225: 154 turns left. If it ends first, you have lost.")
    short = victory_line("england", 0, 3, tmp_path, "short")
    assert "rule 15 regions in all (you hold 3), outlive france and scotland" in short
    assert victory_line("venice", 0, 3, tmp_path) is None  # not in the file: no line
    assert victory_line("england", 0, 3, tmp_path / "missing") is None


# --- the economy block ---
import json
from types import SimpleNamespace

from parley.victory import Snapshot, economy_lines, first_goal, read_history


def snaps(now_turn, n, income, treasury=1000, settlements=3, plan="", upkeep=None, armies=0):
    """Current snapshot first, then n earlier turns newest first; `income`/`settlements` are functions of turn."""
    return [Snapshot(t, income(t), treasury, settlements(t) if callable(settlements) else settlements, armies,
                     upkeep, upkeep and upkeep * 2, plan if t < now_turn else "")
            for t in range(now_turn, now_turn - n - 1, -1)]


def test_first_goal_drops_numbers_and_turns():
    assert first_goal("1. Storm and capture York (Turn 43). 2. Pursue the army (Turn 46).") == "storm and capture york"
    assert first_goal("Storm and capture York (Turn 46): Attack Edmund.") == "storm and capture york"
    assert first_goal("") == ""


def test_building_phase_early_with_growing_income():
    text = "\n".join(economy_lines(snaps(30, 12, lambda t: 500 + 20 * t), 195))
    assert "Economy: income 1100 a turn (was 900 10 turns ago; +22%); treasury 1000" in text
    assert "20 turns ago" not in text  # only 12 turns of history
    assert "Building phase" in text and "pace" not in text


def test_stalled_when_neither_income_nor_land_grew():
    text = "\n".join(economy_lines(snaps(120, 20, lambda t: 1000, settlements=4), 105))
    assert "Neither income nor land has grown in 15 turns (4 settlements then, 4 now)" in text
    assert "Building phase" not in text


def test_no_stall_if_land_grew_and_no_phase_when_mid_game_steady():
    h = snaps(120, 20, lambda t: 1000, settlements=lambda t: 4 if t < 110 else 6)
    text = "\n".join(economy_lines(h, 105))
    assert "Neither" not in text and "Building" not in text
    assert "Settlements: 6 now (6 10 turns ago, 4 20 turns ago)" in text


def test_late_phase_uses_upkeep_only_when_reported():
    with_up = "\n".join(economy_lines(snaps(200, 20, lambda t: 2000 + t, upkeep=3000, armies=5), 25))
    assert "25 turns left" in with_up and "cost about 600 each" in with_up and "roughly 9 of them" in with_up
    assert "Army upkeep is 50% of your regular costs (3000 of 6000 a turn)" in with_up
    without = "\n".join(economy_lines(snaps(200, 20, lambda t: 2000 + t), 25))
    assert "25 turns left" in without and "cost about" not in without and "Army upkeep" not in without


def test_slipped_plan_is_reported_after_four_turns():
    plan = "1. Storm and capture York (Turn 43). 2. Raid."
    h = snaps(50, 10, lambda t: 800, plan=plan)
    h[3] = h[3]._replace(plan="1. Storm and capture York (Turn 47).")
    assert "Your plan has said 'storm and capture york' since turn 40 (10 turns)." in economy_lines(h, 175)
    short = economy_lines(snaps(50, 3, lambda t: 800, plan=plan), 175)
    assert not [x for x in short if x.startswith("Your plan")]
    h3 = snaps(50, 10, lambda t: 800, plan=plan)
    h3[2] = h3[2]._replace(plan="1. Take Nottingham.")  # a different goal breaks the run
    assert not [x for x in economy_lines(h3, 175) if x.startswith("Your plan")]


def test_empty_history_adds_nothing(tmp_path):
    assert economy_lines([], 100) == []
    (tmp_path / "descr_win_conditions.txt").write_text(WIN)
    (tmp_path / "descr_strat.txt").write_text(STRAT)
    assert "\n" not in victory_line("england", 71, 5, tmp_path)


def test_read_history_reads_turn_folders_and_skips_missing(tmp_path):
    def path_for(game, turn, faction):
        return tmp_path / f"t{turn}"
    for t in (8, 6):
        d = tmp_path / f"t{t}"
        d.mkdir()
        (d / "state.json").write_text(json.dumps({"income": 100 * t, "treasury": 5, "settlements": [{}] * 2,
                                                  "armies": [{}], "income_parts": {"army upkeep": -300, "taxes": 900}}))
        (d / "orders.json").write_text(json.dumps({"plan": f"plan {t}"}))
    report = SimpleNamespace(game_id="g", faction="england", turn=10, income=1, treasury=2,
                             settlements=[SimpleNamespace(name=n) for n in "abc"], armies=[], income_parts={})
    h = read_history(path_for, report)
    assert [x.turn for x in h] == [10, 8, 6]
    assert h[0].settlements == 3 and h[1] == Snapshot(8, 800, 5, 2, 1, 300, 300, "plan 8")


def towns_now(**owners):
    return {"towns": {k.lower(): v for k, v in owners.items()}, "faction": "england"}


def test_stuck_plan_matches_the_target_settlement_across_rewordings():
    goals = ["Storm York and capture the city", "Capture York (Turn 44)", "Take York by assault", "Assault York"]
    h = snaps(50, 4, lambda t: 800)
    h = [h[0]._replace(**towns_now(York="scotland", London="england"))] + \
        [x._replace(plan=f"1. {g}. 2. Raid") for x, g in zip(h[1:], goals)]
    line = [x for x in economy_lines(h, 175) if x.startswith("Your plan")]
    assert line == ["Your plan has aimed at York since turn 46 (4 turns); it is still Scotland's."]


def test_stuck_plan_target_silent_when_owned_or_run_too_short_or_broken():
    base = snaps(50, 5, lambda t: 800, plan="1. Take York.")
    owned = [base[0]._replace(**towns_now(York="england"))] + base[1:]
    assert not [x for x in economy_lines(owned, 175) if x.startswith("Your plan")]
    short = [base[0]._replace(**towns_now(York="scotland"))] + base[1:3]
    assert not [x for x in economy_lines(short, 175) if x.startswith("Your plan")]
    broken = [base[0]._replace(**towns_now(York="scotland", Nottingham="england"))] + list(base[1:])
    broken[2] = broken[2]._replace(plan="1. Hold Nottingham.")
    assert not [x for x in economy_lines(broken, 175) if x.startswith("Your plan")]


def test_stuck_plan_falls_back_to_exact_wording_without_a_known_name():
    h = snaps(50, 5, lambda t: 800, plan="1. Build a financial powerhouse (Turn 60).")
    h[0] = h[0]._replace(**towns_now(York="scotland"))
    assert "Your plan has said 'build a financial powerhouse' since turn 45 (5 turns)." in economy_lines(h, 175)
