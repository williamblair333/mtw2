"""Telling a ruler something out of character: a game note in its adviser thread."""

from parley.prompt import build_prompt
from parley.store import Message, Store
from parley.tell import NOTE_SENDER, tell


def test_tell_queues_a_note_in_the_rulers_adviser_thread(tmp_path):
    s = Store(tmp_path / "g.db")
    (tmp_path / "heartbeat.txt").write_text("turn=22\n")
    tell(s, tmp_path, "g", "england", "You can now recruit for yourself.")
    [m] = s.unposted("g")
    assert (m.channel, m.sender, m.turn, m.text) == ("adviser:england", NOTE_SENDER, 22,
                                                      "You can now recruit for yourself.")


def test_a_game_note_is_labelled_plainly_in_the_turn_prompt(venice_report):
    note = Message(id=1, game_id="g", turn=3, channel="adviser:venice", sender=NOTE_SENDER,
                   text="Ships work now.", ts=0)
    p = build_prompt(venice_report, persona="p", adviser="ann", diplomacy=[note])
    assert "Game note (from the people running this game): Ships work now." in p
