"""Tests for parley.decisions recording turn decisions into DecisionLog."""

from jigsaw import DecisionLog
from parley.decisions import record_outcomes, record_turn
from parley.protocol import OrderResult, Orders, SendGold, SetStance


def _orders(*items: object, source_index: list[int] | None = None, malformed: list[OrderResult] | None = None) -> Orders:
    o = Orders(protocol=1, game_id="game1", turn=5, faction="venice", orders=list(items))
    if source_index is not None:
        o.source_index = source_index
    if malformed is not None:
        o.malformed = malformed
    return o


def test_kept_and_rejected_orders_get_right_legality(venice_report):
    log = DecisionLog(":memory:")
    good = SendGold(to="milan", amount=50)
    bad = SendGold(to="milan", amount=999999)
    orders = _orders(good, bad)
    kept = _orders(good)
    rejected = [
        OrderResult(index=1, type="send_gold", ok=False, reason="treasury too small"),
        OrderResult(index=0, type="say", ok=False, reason="ignored say rejection"),
    ]

    count = record_turn(log, venice_report, orders, kept, rejected, "fake_brain")
    assert count == 2

    decisions = sorted(log.query(game=venice_report.game_id), key=lambda d: d.id or 0)
    assert len(decisions) == 2

    # First order survived validation (say rejection was ignored)
    d0 = decisions[0]
    assert d0.kind == "send_gold"
    assert d0.legality == [{"ok": True, "index": 0}]
    assert d0.choice == good.model_dump_json()
    assert d0.primitives == [good.model_dump()]
    assert d0.rung == 7
    assert d0.escalated_because == "LLM seat (fake_brain): asked every turn, no gate yet"
    assert d0.actor == venice_report.faction
    assert d0.turn == venice_report.turn
    assert d0.situation == (
        f"{venice_report.faction} turn {venice_report.turn}: treasury {venice_report.treasury}, "
        f"{len(venice_report.settlements)} settlements, {len(venice_report.armies)} armies"
    )

    # Second order rejected
    d1 = decisions[1]
    assert d1.kind == "send_gold"
    assert d1.legality == [{"ok": False, "reason": "treasury too small", "index": 1}]
    assert d1.choice == bad.model_dump_json()
    assert d1.primitives == [bad.model_dump()]


def test_source_index_mapping_when_parser_dropped_one(venice_report):
    log = DecisionLog(":memory:")
    # Original LLM output had 3 orders: index 0 (kept), 1 (dropped by parser), 2 (kept)
    o0 = SendGold(to="milan", amount=10)
    o2 = SetStance(to="milan", stance="war")
    orders = _orders(o0, o2, source_index=[0, 2])
    kept = _orders(o0)
    # Validation rejected original index 2
    rejected = [OrderResult(index=2, type="set_stance", ok=False, reason="already at war")]

    count = record_turn(log, venice_report, orders, kept, rejected, "fake_brain")
    assert count == 2

    decisions = sorted(log.query(game=venice_report.game_id), key=lambda d: d.id or 0)
    assert decisions[0].kind == "send_gold"
    assert decisions[0].legality == [{"ok": True, "index": 0}]

    assert decisions[1].kind == "set_stance"
    assert decisions[1].legality == [{"ok": False, "reason": "already at war", "index": 2}]


def test_source_index_empty_or_shorter_uses_position(venice_report):
    log = DecisionLog(":memory:")
    o0 = SendGold(to="milan", amount=10)
    o1 = SendGold(to="milan", amount=20)
    orders = _orders(o0, o1)
    orders._source_index = []  # explicitly empty source_index
    rejected = [OrderResult(index=1, type="send_gold", ok=False, reason="rejected")]

    count = record_turn(log, venice_report, orders, _orders(o0), rejected, "brain")
    assert count == 2

    decisions = sorted(log.query(game=venice_report.game_id), key=lambda d: d.id or 0)
    assert decisions[0].legality == [{"ok": True, "index": 0}]
    assert decisions[1].legality == [{"ok": False, "reason": "rejected", "index": 1}]


def test_malformed_entries_recorded(venice_report):
    log = DecisionLog(":memory:")
    o0 = SendGold(to="milan", amount=10)
    mal = [OrderResult(index=1, type="attack", ok=False, reason="syntax error")]
    orders = _orders(o0, malformed=mal)

    count = record_turn(log, venice_report, orders, _orders(o0), [], "brain")
    assert count == 2

    decisions = sorted(log.query(game=venice_report.game_id), key=lambda d: d.id or 0)
    assert decisions[0].kind == "send_gold"
    assert decisions[0].legality == [{"ok": True, "index": 0}]

    d_mal = decisions[1]
    assert d_mal.kind == "attack"
    assert d_mal.choice == "(malformed)"
    assert d_mal.legality == [{"ok": False, "reason": "syntax error", "index": 1}]
    assert d_mal.primitives == []
    assert d_mal.rung == 7


def test_empty_turn_records_turn_decision(venice_report):
    log = DecisionLog(":memory:")
    orders = _orders()

    count = record_turn(log, venice_report, orders, orders, [], "brain")
    assert count == 1

    [d] = log.query(game=venice_report.game_id)
    assert d.kind == "turn"
    assert d.choice == "no orders"
    assert d.actor == venice_report.faction
    assert d.turn == venice_report.turn
    assert d.rung == 7
    assert d.escalated_because == "LLM seat (brain): asked every turn, no gate yet"
    assert d.situation == (
        f"{venice_report.faction} turn {venice_report.turn}: treasury {venice_report.treasury}, "
        f"{len(venice_report.settlements)} settlements, {len(venice_report.armies)} armies"
    )


def test_return_count(venice_report, tmp_path):
    log = DecisionLog(tmp_path / "test.db")
    orders = _orders(
        SendGold(to="milan", amount=10),
        SendGold(to="milan", amount=20),
        malformed=[
            OrderResult(index=2, type="attack", ok=False, reason="bad1"),
            OrderResult(index=3, type="march_on", ok=False, reason="bad2"),
        ],
    )
    count = record_turn(log, venice_report, orders, orders, [], "brain")
    assert count == 4
    assert len(log.query()) == 4


def test_record_turn_stores_index(venice_report):
    log = DecisionLog(":memory:")
    orders = _orders(
        SendGold(to="milan", amount=10),
        SetStance(to="milan", stance="war"),
        source_index=[3, 7],
        malformed=[OrderResult(index=9, type="recruit", ok=False, reason="syntax error")],
    )
    rejected = [OrderResult(index=7, type="set_stance", ok=False, reason="already war")]
    record_turn(log, venice_report, orders, _orders(orders.orders[0]), rejected, "brain")

    decisions = {d.kind: d for d in log.query(game=venice_report.game_id)}
    assert decisions["send_gold"].legality == [{"ok": True, "index": 3}]
    assert decisions["set_stance"].legality == [{"ok": False, "reason": "already war", "index": 7}]
    assert decisions["recruit"].legality == [{"ok": False, "reason": "syntax error", "index": 9}]

    # Silent turn gets no index
    log_silent = DecisionLog(":memory:")
    record_turn(log_silent, venice_report, _orders(), _orders(), [], "brain")
    [d_silent] = log_silent.query(game=venice_report.game_id)
    assert d_silent.legality == []


def test_record_outcomes_sets_done_and_refused_skips_unmatched_and_returns_count(venice_report):
    log = DecisionLog(":memory:")
    rep = venice_report.model_copy(update={"turn": 5})
    orders = _orders(
        SendGold(to="milan", amount=10),
        SendGold(to="milan", amount=20),
        SendGold(to="milan", amount=30),
        malformed=[OrderResult(index=3, type="attack", ok=False, reason="bad syntax")],
    )
    record_turn(log, rep, orders, orders, [], "brain")

    # Also log a silent turn from turn 5 and a decision from turn 4 and another faction
    record_turn(log, rep, _orders(), _orders(), [], "brain")
    past_report = rep.model_copy(update={"turn": 4})
    record_turn(log, past_report, _orders(SendGold(to="milan", amount=10)), _orders(), [], "brain")
    other_report = rep.model_copy(update={"faction": "milan"})
    record_turn(log, other_report, _orders(SendGold(to="venice", amount=10)), _orders(), [], "brain")

    # Results for turn 5: index 0 is ok, index 1 refused, index 99 unmatched, index 2 & 3 not in results
    results = [
        OrderResult(index=0, type="send_gold", ok=True),
        OrderResult(index=1, type="send_gold", ok=False, reason="insufficient funds"),
        OrderResult(index=99, type="send_gold", ok=True),
    ]

    set_count = record_outcomes(
        log,
        game=rep.game_id,
        faction=rep.faction,
        turn=rep.turn,
        results=results,
        now_turn=rep.turn + 1,
    )
    assert set_count == 2

    decisions = {
        (d.turn, d.actor, d.choice): d
        for d in log.query(game=rep.game_id)
    }

    d0 = decisions[(5, "venice", orders.orders[0].model_dump_json())]
    assert d0.outcome == "done"
    assert d0.outcome_turn == 6

    d1 = decisions[(5, "venice", orders.orders[1].model_dump_json())]
    assert d1.outcome == "refused: insufficient funds"
    assert d1.outcome_turn == 6

    d2 = decisions[(5, "venice", orders.orders[2].model_dump_json())]
    assert d2.outcome is None
    assert d2.outcome_turn is None

    d3 = decisions[(5, "venice", "(malformed)")]
    assert d3.outcome is None
    assert d3.outcome_turn is None

    # Silent turn had no index
    d_silent = decisions[(5, "venice", "no orders")]
    assert d_silent.outcome is None

    # Other turn and faction untouched
    d_past = decisions[(4, "venice", orders.orders[0].model_dump_json())]
    assert d_past.outcome is None
    d_milan = decisions[(5, "milan", SendGold(to="venice", amount=10).model_dump_json())]
    assert d_milan.outcome is None
