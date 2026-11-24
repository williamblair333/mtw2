import json
import os
from pathlib import Path
import shutil

import pytest

from parley.trends import format_trends, main, trends


def _make_turn(
    root: Path,
    game_id: str,
    turn_num: int,
    faction: str,
    orders_count: int,
    applied_ok: int,
    refused: int,
    answer_seconds: float,
    towns: int,
    armies: int,
    late: bool = False,
    seat_error: bool = False,
) -> None:
    tdir = root / game_id / f"turn-{turn_num:04d}" / faction
    tdir.mkdir(parents=True, exist_ok=True)

    state = {
        "turn": turn_num,
        "settlements": [{"id": f"t_{i}"} for i in range(towns)],
        "armies": [{"id": f"a_{i}"} for i in range(armies)],
    }
    (tdir / "state.json").write_text(json.dumps(state), encoding="utf-8")

    note = "seat error: brain timeout" if seat_error else "plan ok"
    orders_list = [{"type": "move_army", "index": i} for i in range(orders_count)]
    orders = {
        "protocol": 1,
        "game_id": game_id,
        "turn": turn_num,
        "faction": faction,
        "orders": orders_list,
        "note": note,
    }
    (tdir / "orders.json").write_text(json.dumps(orders), encoding="utf-8")

    results = []
    for i in range(applied_ok):
        results.append({"type": "move_army", "ok": True, "index": i, "reason": ""})
    for i in range(applied_ok, applied_ok + refused):
        results.append({"type": "move_army", "ok": False, "index": i, "reason": "failed"})
    (tdir / "results.json").write_text(json.dumps(results), encoding="utf-8")

    if late:
        (tdir / "late.txt").write_text("late answer\n", encoding="utf-8")

    base = 1_700_000_000.0 + turn_num * 1000.0
    os.utime(tdir / "state.json", (base, base))
    os.utime(tdir / "orders.json", (base + answer_seconds, base + answer_seconds))


def test_trends_steady(tmp_path: Path):
    game_id = "test_game"
    for t in range(1, 7):
        _make_turn(
            tmp_path, game_id, t, "england",
            orders_count=5, applied_ok=5, refused=0, answer_seconds=20.0,
            towns=3, armies=3, late=False, seat_error=False,
        )

    res = trends(tmp_path, game_id)
    assert "england" in res
    assert len(res["england"]["rows"]) == 6
    assert res["england"]["alerts"] == []
    text = format_trends(res)
    assert "no alerts" in text


def test_trends_falling_applied_share(tmp_path: Path):
    game_id = "test_game"
    for t in range(1, 4):
        _make_turn(
            tmp_path, game_id, t, "england",
            orders_count=5, applied_ok=5, refused=0, answer_seconds=20.0,
            towns=3, armies=3, late=False, seat_error=False,
        )
    for t in range(4, 7):
        _make_turn(
            tmp_path, game_id, t, "england",
            orders_count=5, applied_ok=2, refused=3, answer_seconds=20.0,
            towns=3, armies=3, late=False, seat_error=False,
        )

    res = trends(tmp_path, game_id)
    alerts = res["england"]["alerts"]
    assert len(alerts) == 1
    assert alerts[0] == "applied share fell 60 points (100% to 40%)"


def test_a_turn_whose_orders_are_not_applied_yet_is_not_a_fall(tmp_path: Path):
    # live 11-11 13:55: "france: applied share fell 42 points (78% to 36%)". The ruler's turn-104 reply was
    # in (orders.json) and its results come at the next turn start, so the newest row read 9 orders, 0 applied
    game_id = "test_game"
    for t in range(1, 8):
        _make_turn(
            tmp_path, game_id, t, "england",
            orders_count=5, applied_ok=5, refused=0, answer_seconds=20.0,
            towns=3, armies=3, late=False, seat_error=False,
        )
    results = list(tmp_path.glob(f"{game_id}/turn-*7/england/results.json"))
    assert len(results) == 1
    results[0].unlink()  # turn 7 answered, not applied yet
    res = trends(tmp_path, game_id)
    assert not any("applied share" in a for a in res["england"]["alerts"]), res["england"]["alerts"]


def test_one_refused_order_among_few_is_not_a_fall(tmp_path: Path):
    # live 11-11 17:04: "england: applied share fell 20 points (100% to 80%)" was one refused attack (target not
    # in sight) among a ruler's 1-2 orders a turn
    game_id = "test_game"
    for t in range(1, 7):
        _make_turn(
            tmp_path, game_id, t, "england",
            orders_count=1, applied_ok=1, refused=0, answer_seconds=20.0,
            towns=3, armies=3, late=False, seat_error=False,
        )
    _make_turn(
        tmp_path, game_id, 7, "england",
        orders_count=1, applied_ok=0, refused=1, answer_seconds=20.0,
        towns=3, armies=3, late=False, seat_error=False,
    )
    res = trends(tmp_path, game_id)
    assert not any("applied share" in a for a in res["england"]["alerts"]), res["england"]["alerts"]


def _share_alerts(tmp_path: Path, turns: list[tuple[int, list[str]]]) -> list[str]:
    # each turn: (orders, the types of its refused orders); the rest are applied
    for t, (orders, refused) in enumerate(turns, start=1):
        _make_turn(
            tmp_path, "test_game", t, "england",
            orders_count=orders, applied_ok=orders - len(refused), refused=len(refused), answer_seconds=20.0,
            towns=3, armies=3, late=False, seat_error=False,
        )
        path = tmp_path / "test_game" / f"turn-{t:04d}" / "england" / "results.json"
        results = json.loads(path.read_text())
        for r, kind in zip([r for r in results if not r["ok"]], refused):
            r["type"] = kind
        path.write_text(json.dumps(results))
    return [a for a in trends(tmp_path, "test_game")["england"]["alerts"] if "applied share" in a]


def test_mistakes_spread_over_order_types_are_not_a_fall(tmp_path: Path):
    # live 11-22: "england: applied share fell 37 points (92% to 56%)": a merge over 20 units, a move across
    # the sea, a move and an agent's walk onto sea, each a different ruler mistake the game refused
    newest = [(3, ["merge_armies", "move_army"]), (3, []), (3, ["move_agent", "move_army"])]
    assert _share_alerts(tmp_path, [(3, [])] * 7 + newest) == []


def test_one_order_type_refused_again_and_again_still_alerts(tmp_path: Path):
    newest = [(3, ["recruit", "recruit"]), (3, ["recruit"]), (3, ["recruit"])]
    assert _share_alerts(tmp_path, [(3, [])] * 7 + newest)


def test_trends_slowing_answers(tmp_path: Path):
    game_id = "test_game"
    for t in range(1, 4):
        _make_turn(
            tmp_path, game_id, t, "england",
            orders_count=5, applied_ok=5, refused=0, answer_seconds=30.0,
            towns=3, armies=3, late=False, seat_error=False,
        )
    for t in range(4, 7):
        _make_turn(
            tmp_path, game_id, t, "england",
            orders_count=5, applied_ok=5, refused=0, answer_seconds=75.0,
            towns=3, armies=3, late=False, seat_error=False,
        )

    res = trends(tmp_path, game_id)
    alerts = res["england"]["alerts"]
    assert len(alerts) == 1
    assert alerts[0] == "median answer time per order slowed to 15.0s (earlier 6.0s, 2.5x)"


def test_more_orders_is_not_slower_answer_time(tmp_path: Path):
    # Live data 2026-11-20: turns were bigger, seconds per order didn't slow
    game_id = "scratch"
    live_rows = [
        (2056, 19, 46.6),
        (2057, 8, 40.6),
        (2058, 15, 41.6),
        (2059, 13, 40.8),
        (2060, 15, 35.4),
        (2061, 15, 44.6),
        (2062, 6, 33.7),
        (2063, 27, 73.8),
        (2064, 29, 86.5),
        (2065, 27, 48.8),
    ]
    for turn, orders, ans in live_rows:
        _make_turn(
            tmp_path, game_id, turn, "france",
            orders_count=orders, applied_ok=orders, refused=0, answer_seconds=ans,
            towns=5, armies=5, late=False, seat_error=False,
        )
    res = trends(tmp_path, game_id)
    assert not any("answer time" in a for a in res["france"]["alerts"]), res["france"]["alerts"]


def test_doubled_answer_time_with_same_orders_alerts(tmp_path: Path):
    game_id = "test_game"
    for t in range(1, 4):
        _make_turn(
            tmp_path, game_id, t, "england",
            orders_count=5, applied_ok=5, refused=0, answer_seconds=35.0,
            towns=3, armies=3, late=False, seat_error=False,
        )
    for t in range(4, 7):
        _make_turn(
            tmp_path, game_id, t, "england",
            orders_count=5, applied_ok=5, refused=0, answer_seconds=70.0,
            towns=3, armies=3, late=False, seat_error=False,
        )

    res = trends(tmp_path, game_id)
    alerts = res["england"]["alerts"]
    assert len(alerts) == 1
    assert alerts[0] == "median answer time per order slowed to 14.0s (earlier 7.0s, 2.0x)"


def test_popup_reading_before_the_prompt_is_not_the_rulers_time(tmp_path: Path):
    # live 11-21: England's turns spent 22-28 s reading popups between state.json and prompt.txt;
    # the 2-6 order turns read as 61-91 s answers and woke the watch twice
    import os
    game_id = "test_game"
    for t in range(1, 7):
        orders = 10 if t < 4 else 3
        _make_turn(
            tmp_path, game_id, t, "england",
            orders_count=orders, applied_ok=orders, refused=0, answer_seconds=65.0,
            towns=3, armies=3, late=False, seat_error=False,
        )
        tdir = tmp_path / game_id / f"turn-{t:04d}" / "england"
        base = 1_700_000_000.0 + t * 1000.0
        (tdir / "prompt.txt").write_text("prompt")
        os.utime(tdir / "prompt.txt", (base + 30.0, base + 30.0))  # the ruler answered in 35 s

    res = trends(tmp_path, game_id)
    assert res["england"]["alerts"] == []
    assert all(r["answer_seconds"] == 35.0 for r in res["england"]["rows"])


def test_a_doubling_under_the_60s_floor_does_not_alert(tmp_path: Path):
    # the raw 60 s floor stays: a fast seat drifting from 20 s to 40 s is no reason to wake anyone
    game_id = "test_game"
    for t, ans in [(1, 20.0), (2, 20.0), (3, 20.0), (4, 40.0), (5, 40.0), (6, 40.0)]:
        _make_turn(
            tmp_path, game_id, t, "england",
            orders_count=5, applied_ok=5, refused=0, answer_seconds=ans,
            towns=3, armies=3, late=False, seat_error=False,
        )
    assert not any("answer time" in a for a in trends(tmp_path, game_id)["england"]["alerts"])


def test_zero_orders_does_not_divide_by_zero(tmp_path: Path):
    game_id = "test_game"
    for t in range(1, 4):
        _make_turn(
            tmp_path, game_id, t, "england",
            orders_count=0, applied_ok=0, refused=0, answer_seconds=30.0,
            towns=3, armies=3, late=False, seat_error=False,
        )
    for t in range(4, 7):
        _make_turn(
            tmp_path, game_id, t, "england",
            orders_count=0, applied_ok=0, refused=0, answer_seconds=75.0,
            towns=3, armies=3, late=False, seat_error=False,
        )

    res = trends(tmp_path, game_id)
    alerts = res["england"]["alerts"]
    assert len(alerts) == 1  # 0 orders count as 1
    assert alerts[0] == "median answer time per order slowed to 75.0s (earlier 30.0s, 2.5x)"


def test_a_qa_park_between_report_and_answer_is_not_thinking(tmp_path: Path):
    # 11-05 run 10: a full bench pass parked the campaign after the turn-5 report; its answer
    # "took" 5638 s. The ruler starts at the restore (qa.last_restore)
    for t in range(1, 5):
        _make_turn(tmp_path, "g", t, "england", orders_count=5, applied_ok=5, refused=0,
                   answer_seconds=3000.0 if t == 4 else 30.0, towns=3, armies=3)
    base = 1_700_000_000.0 + 4 * 1000.0
    restore = tmp_path / "qa.last_restore"
    restore.write_text("restored\n")
    os.utime(restore, (base + 2970.0, base + 2970.0))  # 30 s before the answer
    rows = trends(tmp_path, "g")["england"].rows
    assert [r["answer_seconds"] for r in rows] == [30.0, 30.0, 30.0, 30.0]


def test_a_restore_from_before_the_report_changes_nothing(tmp_path: Path):
    # an old qa.last_restore (an earlier bench run) falls before every report: answers are untouched
    for t in range(1, 5):
        _make_turn(tmp_path, "g", t, "england", orders_count=5, applied_ok=5, refused=0,
                   answer_seconds=40.0, towns=3, armies=3)
    restore = tmp_path / "qa.last_restore"
    restore.write_text("restored\n")
    os.utime(restore, (1_000_000.0, 1_000_000.0))
    assert [r["answer_seconds"] for r in trends(tmp_path, "g")["england"].rows] == [40.0] * 4


def test_trends_lost_town(tmp_path: Path):
    game_id = "test_game"
    for t in range(1, 4):
        _make_turn(
            tmp_path, game_id, t, "england",
            orders_count=5, applied_ok=5, refused=0, answer_seconds=20.0,
            towns=3, armies=3, late=False, seat_error=False,
        )
    for t in range(4, 7):
        _make_turn(
            tmp_path, game_id, t, "england",
            orders_count=5, applied_ok=5, refused=0, answer_seconds=20.0,
            towns=2, armies=3, late=False, seat_error=False,
        )

    res = trends(tmp_path, game_id)
    alerts = res["england"]["alerts"]
    assert len(alerts) == 1
    assert alerts[0] == "towns fell from 3 to 2"


@pytest.mark.parametrize("first,last,alerts", [
    (59, 58, False),  # live 11-20: France trading one town in a war woke the watch
    (62, 60, False),
    (62, 59, True),   # 3 of 62 is 5%: reported
    (11, 9, True),    # a small faction: any loss is reported (England's Antwerp, 11-20)
])
def test_a_big_faction_reports_only_a_real_cut_in_towns(tmp_path: Path, first, last, alerts):
    for t in range(1, 7):
        _make_turn(tmp_path, "g", t, "france", orders_count=5, applied_ok=5, refused=0,
                   answer_seconds=20.0, towns=first if t < 6 else last, armies=3)
    got = [a for a in trends(tmp_path, "g")["france"]["alerts"] if "towns fell" in a]
    assert bool(got) == alerts, got


def test_alerts_only_prints_one_line_per_alert_for_the_watch(tmp_path: Path, capsys):
    # scripts/campaign_watch.sh compares these lines with those at its start (TREND)
    from parley.trends import main
    for t, towns in ((1, 3), (2, 3), (3, 3), (4, 2), (5, 2), (6, 2)):
        _make_turn(tmp_path, "g", t, "england", orders_count=5, applied_ok=5, refused=0,
                   answer_seconds=20.0, towns=towns, armies=3)
        _make_turn(tmp_path, "g", t, "france", orders_count=5, applied_ok=5, refused=0,
                   answer_seconds=20.0, towns=4, armies=3)
    assert main([str(tmp_path), "g", "--alerts-only"]) == 0
    assert capsys.readouterr().out.strip().splitlines() == ["england: towns fell from 3 to 2"]


def test_trends_late_answer(tmp_path: Path):
    game_id = "test_game"
    for t in range(1, 6):
        _make_turn(
            tmp_path, game_id, t, "england",
            orders_count=5, applied_ok=5, refused=0, answer_seconds=20.0,
            towns=3, armies=3, late=False, seat_error=False,
        )
    _make_turn(
        tmp_path, game_id, 6, "england",
        orders_count=5, applied_ok=5, refused=0, answer_seconds=20.0,
        towns=3, armies=3, late=True, seat_error=False,
    )

    res = trends(tmp_path, game_id)
    alerts = res["england"]["alerts"]
    assert len(alerts) == 1
    assert alerts[0] == "late answer on turn 6"


def test_trends_seat_error(tmp_path: Path):
    game_id = "test_game"
    for t in range(1, 6):
        _make_turn(
            tmp_path, game_id, t, "england",
            orders_count=5, applied_ok=5, refused=0, answer_seconds=20.0,
            towns=3, armies=3, late=False, seat_error=False,
        )
    _make_turn(
        tmp_path, game_id, 6, "england",
        orders_count=5, applied_ok=5, refused=0, answer_seconds=20.0,
        towns=3, armies=3, late=False, seat_error=True,
    )

    res = trends(tmp_path, game_id)
    alerts = res["england"]["alerts"]
    assert len(alerts) == 1
    assert alerts[0] == "seat error on turn 6"


def test_trends_sample_scratch(tmp_path: Path):
    sample_dir = Path("_sample/scratch")
    if not sample_dir.is_dir():
        pytest.skip("_sample absent")

    dest = tmp_path / "scratch"
    shutil.copytree(sample_dir, dest)

    res = trends(tmp_path, "scratch", last=10)
    assert "england" in res
    assert "france" in res
    assert len(res["england"]["rows"]) == 10
    assert len(res["france"]["rows"]) == 10
    assert len(res["england"]) == 10
    assert len(res["france"]) == 10


def test_trends_main_cli(tmp_path: Path, capsys):
    game_id = "test_game"
    for t in range(1, 5):
        _make_turn(
            tmp_path, game_id, t, "england",
            orders_count=3, applied_ok=3, refused=0, answer_seconds=15.0,
            towns=2, armies=2, late=False, seat_error=False,
        )

    code = main([str(tmp_path), game_id, "--last", "4"])
    assert code == 0
    captured = capsys.readouterr().out
    assert "england" in captured
    assert "no alerts" in captured
