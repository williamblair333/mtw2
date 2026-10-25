"""Follow one ruler live: what it says (lobby, private threads, its adviser) and its turn notes.

For spectating and for analysing a ruler while a game runs: `just follow england scratch`
prints as things happen; `--once` waits for the next new item, prints it and exits (so a
background watcher can be re-armed after each one).
"""

import json
import time
from pathlib import Path

from parley.store import Store


def new_items(store: Store, turn_root: Path, game_id: str, faction: str, state: dict) -> tuple[list, dict]:
    """Messages and notes newer than `state` ({"msg": last id, "note_turn": last turn})."""
    items = []
    last_msg = state.get("msg", 0)
    for m in store.recent(game_id, faction, limit=500):
        if m.id > last_msg:
            items.append({"kind": "message", "turn": m.turn, "channel": m.channel,
                          "sender": m.sender, "text": m.text})
            last_msg = max(last_msg, m.id)
    last_turn = state.get("note_turn", -1)
    game_dir = Path(turn_root) / game_id
    for d in sorted(game_dir.glob(f"turn-*/{faction}/orders.json")):
        turn = int(d.parent.parent.name.removeprefix("turn-"))
        if turn > last_turn:
            try:
                o = json.loads(d.read_text())
            except (OSError, ValueError):
                continue  # mid-write: the next look gets it
            items.append({"kind": "note", "turn": turn, "text": o.get("note") or "",
                          "orders": [x.get("type") for x in o.get("orders", [])]})
            last_turn = turn
    return items, {"msg": last_msg, "note_turn": last_turn}


def format_item(i: dict) -> str:
    if i["kind"] == "note":
        return f"[turn {i['turn']}] NOTE ({', '.join(i['orders']) or 'no orders'}): {i['text']}"
    return f"[turn {i['turn']}] {i['channel']} | {i['sender']}: {i['text']}"


def follow(store: Store, turn_root: Path, game_id: str, faction: str, state_file: Path | None,
           once: bool, poll: float = 3.0) -> None:
    state = json.loads(state_file.read_text()) if state_file and state_file.exists() else {}
    while True:
        items, state = new_items(store, turn_root, game_id, faction, state)
        for i in items:
            print(format_item(i), flush=True)
        if state_file:
            state_file.write_text(json.dumps(state))
        if items and once:
            return
        time.sleep(poll)
