"""Following one ruler live: its messages (every channel it's in) and its turn notes."""

import json

from parley.follow import new_items
from parley.store import Store


def _note(root, turn, faction, note, orders=()):
    d = root / "g" / f"turn-{turn:04d}" / faction
    d.mkdir(parents=True, exist_ok=True)
    (d / "orders.json").write_text(json.dumps({"orders": list(orders), "note": note}))


def test_new_messages_and_notes_since_the_last_look(tmp_path):
    s = Store(tmp_path / "g.db")
    s.record("g", 3, "adviser:england", "adviser:england", "March on Rennes.")
    s.record("g", 3, "adviser:england", "england", "As you wish, my lord.")
    s.record("g", 3, "pair:france|milan", "milan", "not ours")
    _note(tmp_path, 3, "england", "Robin rides.", [{"type": "march_on"}])
    items, state = new_items(s, tmp_path, "g", "england", {})
    assert [i["text"] for i in items] == ["March on Rennes.", "As you wish, my lord.", "Robin rides."]
    assert items[-1]["kind"] == "note" and items[-1]["orders"] == ["march_on"]
    again, _ = new_items(s, tmp_path, "g", "england", state)
    assert again == []
    s.record("g", 4, "lobby", "england", "England stands with Rome.")
    later, _ = new_items(s, tmp_path, "g", "england", state)
    assert [i["text"] for i in later] == ["England stands with Rome."]
