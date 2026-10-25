"""Tell a ruler something out of character: a game note in its adviser thread.

For the people running a game (the author, or Claude during a playtest): new orders that now
work, fixes, corrections. The note is posted to Discord like any adviser message and reaches
the ruler's turn prompt, labelled as a game note, not as its adviser speaking.
"""

from pathlib import Path

from parley.store import Store, adviser_channel

NOTE_SENDER = "parley"  # the sender the bot already posts plainly (transfer notices use it too)


def current_turn(turn_root: Path) -> int:
    try:
        text = (Path(turn_root) / "heartbeat.txt").read_text()
        return int(text.strip().removeprefix("turn="))
    except (OSError, ValueError):
        return 0


def tell(store: Store, turn_root: Path, game_id: str, faction: str, text: str) -> int:
    return store.queue(game_id, current_turn(turn_root), adviser_channel(faction), NOTE_SENDER,
                       text.strip(), kind="notice")
