import json

import pytest

from parley.bridge import TurnDir
from parley.protocol import Orders


def _state(td: TurnDir, faction: str, venice_state_dict, turn: int = 1):
    d = td.path_for("test", turn, faction)
    d.mkdir(parents=True)
    (d / "state.json").write_text(json.dumps({**venice_state_dict, "faction": faction}))
    return d


def _orders(faction="venice"):
    return Orders(protocol=1, game_id="test", turn=1, faction=faction, orders=[])


def test_path_layout(tmp_path):
    assert TurnDir(tmp_path).path_for("g1", 7, "venice") == tmp_path / "g1" / "turn-0007" / "venice"


def test_pending_lists_unanswered_only(tmp_path, venice_state_dict):
    td = TurnDir(tmp_path)
    answered = _state(td, "venice", venice_state_dict)
    waiting = _state(td, "milan", venice_state_dict)
    td.write_orders(answered, _orders())
    assert td.pending() == [waiting]


def test_tmp_files_ignored(tmp_path):
    td = TurnDir(tmp_path)
    d = td.path_for("test", 1, "venice")
    d.mkdir(parents=True)
    (d / "state.json.tmp").write_text("{}")
    assert td.pending() == []


def test_write_orders_atomic(tmp_path, venice_state_dict):
    td = TurnDir(tmp_path)
    d = _state(td, "venice", venice_state_dict)
    td.write_orders(d, _orders())
    assert not list(d.glob("*.tmp"))
    assert Orders.model_validate_json((d / "orders.json").read_text()) == _orders()


def test_read_state_truncated_raises(tmp_path, venice_state_dict):
    td = TurnDir(tmp_path)
    d = _state(td, "venice", venice_state_dict)
    text = (d / "state.json").read_text()
    (d / "state.json").write_text(text[: len(text) // 2])
    with pytest.raises(ValueError):
        td.read_state(d)


def test_read_results_absent_then_present(tmp_path, venice_state_dict):
    td = TurnDir(tmp_path)
    d = _state(td, "venice", venice_state_dict)
    assert td.read_results(d) is None
    (d / "results.json").write_text('[{"index": 0, "type": "send_gold", "ok": true}]')
    assert td.read_results(d)[0].ok


def test_atomic_write_tmp_names_unique(tmp_path, monkeypatch):
    import os
    from parley import bridge
    seen = []
    real = os.replace
    monkeypatch.setattr(bridge.os, "replace", lambda a, b: (seen.append(str(a)), real(a, b)))
    bridge.atomic_write(tmp_path / "x.json", "1")
    bridge.atomic_write(tmp_path / "x.json", "2")
    assert len(set(seen)) == 2
