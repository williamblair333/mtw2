import json

from parley.notes import format_notes


def _turn(root, turn, faction, note, orders=(), said=(), results=None):
    d = root / "g" / f"turn-{turn:04d}" / faction
    d.mkdir(parents=True)
    (d / "orders.json").write_text(json.dumps(
        {"protocol": 1, "game_id": "g", "turn": turn, "faction": faction,
         "orders": list(orders), "note": note}))
    (d / "messages.json").write_text(json.dumps({"kept": list(said), "rejected": []}))
    if results is not None:
        (d / "results.json").write_text(json.dumps(results))


def test_notes_by_turn_and_faction(tmp_path):
    _turn(tmp_path, 0, "venice", "Decline the bribe.", said=[{"to": "england", "text": "No."}])
    _turn(tmp_path, 0, "milan", "Seize Brescia.",
          orders=[{"type": "march_on", "army": "Rossi", "target_settlement": "Brescia"}],
          results=[{"index": 0, "type": "march_on", "ok": True, "reason": ""}])
    _turn(tmp_path, 1, "venice", "Still at peace.")
    out = format_notes(tmp_path, "g")
    assert out.index("Turn 0") < out.index("Turn 1")
    assert "milan: Seize Brescia." in out
    assert "march_on Rossi → Brescia [done]" in out
    assert "→ england (private): No." in out


def test_notes_filter_by_faction_and_last(tmp_path):
    for t in range(4):
        _turn(tmp_path, t, "venice", f"note {t}")
        _turn(tmp_path, t, "milan", f"milan {t}")
    out = format_notes(tmp_path, "g", faction="venice", last=2)
    assert "note 2" in out and "note 3" in out and "note 1" not in out and "milan" not in out


def test_notes_empty_game(tmp_path):
    assert "no turns" in format_notes(tmp_path, "nothing")
