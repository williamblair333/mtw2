"""The campaign report: what each ruler did over a whole game, from the turn folders."""

import json

from parley.report import campaign_report


def _turn(root, turn, faction, *, state=None, orders=None, results=None, rejected=None,
          messages=None, late=False):
    d = root / "g1" / f"turn-{turn:04d}" / faction
    d.mkdir(parents=True, exist_ok=True)
    if state is not None:
        (d / "state.json").write_text(json.dumps(state))
    if orders is not None:
        (d / "orders.json").write_text(json.dumps({"orders": orders[0], "note": orders[1]}))
    if results is not None:
        (d / "results.json").write_text(json.dumps(results))
    if rejected is not None:
        (d / "rejected.json").write_text(json.dumps(rejected))
    if messages is not None:
        (d / "messages.json").write_text(json.dumps({"kept": messages, "rejected": []}))
    if late:
        (d / "late.txt").write_text("")


def _state(treasury, settlements):
    return {"treasury": treasury, "settlements": [{"id": s} for s in settlements]}


def _game(tmp_path):
    root = tmp_path / "turns"
    gold = {"type": "send_gold", "to": "milan", "amount": 100}
    hit = {"type": "assassinate", "agent": "Iacopo", "target": "Ulrich"}
    _turn(root, 0, "venice", state=_state(5000, ["Venice", "Ragusa"]), orders=([gold, hit], "pay Milan"),
          results=[{"index": 0, "type": "send_gold", "ok": True, "reason": ""},
                   {"index": 1, "type": "assassinate", "ok": False, "reason": "target 'Ulrich' is not in sight"}],
          rejected=[{"index": 2, "type": "besiege", "ok": False, "reason": "unknown army 'Bob'"}],
          messages=[{"to": "lobby", "text": "Peace!"}, {"to": "milan", "text": "Gold is coming."}])
    _turn(root, 1, "venice", state=_state(4200, ["Venice"]), late=True)
    _turn(root, 0, "milan", state=_state(3000, ["Milan"]), orders=([], "seat error: timeout"))
    return root


def test_report_rows_per_ruler(tmp_path):
    text = campaign_report(_game(tmp_path), "g1")
    assert "| venice | 2 | 1 | 1 | 0 | 5000 → 4200 | 2 → 1 | 1 public, 1 private |" in text
    assert "| milan | 1 | 1 | 0 | 1 | 3000 → 3000 | 1 → 1 | none |" in text


def test_report_order_coverage(tmp_path):
    text = campaign_report(_game(tmp_path), "g1")
    assert "| send_gold | 1 | 1 | 0 | 0 |" in text
    assert "| assassinate | 1 | 0 | 1 | 0 |" in text
    assert "| besiege | 1 | 0 | 0 | 1 |" in text
    assert "Never tried: " in text and "bribe" in text.split("Never tried: ")[1].splitlines()[0]


def test_report_lists_reasons(tmp_path):
    text = campaign_report(_game(tmp_path), "g1")
    assert "venice turn 0 assassinate (game): target 'Ulrich' is not in sight" in text
    assert "venice turn 0 besiege (checker): unknown army 'Bob'" in text


def test_report_on_an_empty_game(tmp_path):
    assert "no turns" in campaign_report(tmp_path, "nothing")
