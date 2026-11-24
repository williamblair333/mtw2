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


def test_pending_skips_a_factions_older_reports(tmp_path, venice_state_dict):
    # live 11-05 14:42: stale reports for turns 6-8 were answered before the real turn 75, and both
    # rulers ran out of time; only each faction's newest report can still be acted on
    td = TurnDir(tmp_path)
    for turn in (6, 7, 75):
        _state(td, "france", venice_state_dict, turn=turn)
    old_england = _state(td, "england", venice_state_dict, turn=74)
    td.write_orders(old_england, _orders("england"))
    england = _state(td, "england", venice_state_dict, turn=75)
    assert td.pending() == [td.path_for("test", 75, "france"), england] or \
        sorted(td.pending()) == sorted([td.path_for("test", 75, "france"), england])


def test_pending_follows_a_reload_to_an_earlier_turn(tmp_path, venice_state_dict):
    # review 11-05 (agy): turn 75 answered, then an earlier save loaded and its turn-74 report rewritten;
    # by highest turn the loop would wait on 75 forever. The report written last is the live one
    import os
    import time
    td = TurnDir(tmp_path)
    t74 = _state(td, "england", venice_state_dict, turn=74)
    td.write_orders(t74, _orders("england"))
    t75 = _state(td, "england", venice_state_dict, turn=75)
    td.write_orders(t75, _orders("england"))
    later = time.time() + 5
    os.utime(t74 / "state.json", (later, later))  # the game rewrote turn 74's report after the load
    assert td.pending() == [t74]


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
