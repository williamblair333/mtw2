"""archive_qa_game: an earlier run's QA game, folders and database, out of the next run's way."""

import datetime as _dt
from pathlib import Path

from parley.qa.runner import archive_qa_game
from parley.store import Store


def test_the_game_database_goes_with_its_turn_folders(tmp_path: Path):
    # full pass 11-05 17:51: diplomacy's orders_next_report had its one `say` refused, "limit 3 per
    # turn to lobby": qa-diplomacy.db still held the lobby messages earlier runs queued at turn 6,
    # and every bench reload goes back to the same turn numbers
    (tmp_path / "qa-diplomacy" / "turn-0006" / "england").mkdir(parents=True)
    store = Store(tmp_path / "qa-diplomacy.db")
    for _ in range(3):
        store.queue("qa-diplomacy", 6, "lobby", "england", "earlier run", kind="say")
    del store
    for side in ("-wal", "-shm"):
        (tmp_path / f"qa-diplomacy.db{side}").write_bytes(b"")
    dest = archive_qa_game(tmp_path, "qa-diplomacy", lambda: _dt.datetime(2026, 11, 5, 17, 51))
    assert dest is not None and (dest / "turn-0006").is_dir()
    assert not list(tmp_path.glob("qa-diplomacy.db*"))
    assert (dest / "qa-diplomacy.db").is_file()
    assert (dest / "qa-diplomacy.db-wal").exists() and (dest / "qa-diplomacy.db-shm").exists()


def test_a_database_without_turn_folders_is_moved_too(tmp_path: Path):
    (tmp_path / "qa-covert.db").write_bytes(b"x")
    dest = archive_qa_game(tmp_path, "qa-covert", lambda: _dt.datetime(2026, 11, 5, 18, 0))
    assert dest is not None and (dest / "qa-covert.db").read_bytes() == b"x"
    assert not (tmp_path / "qa-covert.db").exists()
