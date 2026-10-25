"""Messages and the outbox, in one SQLite file shared by the orchestrator and the Discord bot.

Channels: "lobby" (public) or "pair:<a>|<b>" (private, faction IDs in alphabetical order).
Senders: a faction ID for an LLM seat, "human:<faction>" for a human seat.
"""

import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY, game_id TEXT, turn INTEGER, channel TEXT, sender TEXT,
    text TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS outbox (
    id INTEGER PRIMARY KEY, game_id TEXT, turn INTEGER, channel TEXT, sender TEXT,
    text TEXT, ts REAL, posted INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS messages_game ON messages (game_id, channel);
CREATE INDEX IF NOT EXISTS outbox_game ON outbox (game_id, posted);
"""


@dataclass(frozen=True)
class Message:
    id: int
    game_id: str
    turn: int
    channel: str
    sender: str
    text: str
    ts: float


def pair_channel(a: str, b: str) -> str:
    x, y = sorted((a, b))
    return f"pair:{x}|{y}"


def adviser_channel(faction: str) -> str:
    """A ruler's private thread with its adviser (a human who isn't a player)."""
    return f"adviser:{faction}"


def _row(r) -> Message:
    return Message(*r[:7])


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        with closing(self._connect()) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(SCHEMA)
            cols = {r[1] for r in db.execute("PRAGMA table_info(outbox)")}
            if "kind" not in cols:  # older databases: every row was a turn message
                db.execute("ALTER TABLE outbox ADD COLUMN kind TEXT DEFAULT 'turn'")
                db.commit()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)

    def record(self, game_id: str, turn: int, channel: str, sender: str, text: str) -> int:
        with closing(self._connect()) as db, db:
            return db.execute(
                "INSERT INTO messages (game_id, turn, channel, sender, text, ts) VALUES (?,?,?,?,?,?)",
                (game_id, turn, channel, sender, text, time.time())).lastrowid

    def recent(self, game_id: str, faction: str, limit: int = 30) -> list[Message]:
        with closing(self._connect()) as db:
            rows = db.execute(
                "SELECT id, game_id, turn, channel, sender, text, ts FROM messages "
                # exact prefix/suffix compares: LIKE would treat '_' in faction ids as a wildcard
                "WHERE game_id = ? AND (channel = 'lobby' OR channel = ? "
                "OR substr(channel, 1, length(?)) = ? OR substr(channel, -length(?)) = ?) "
                "ORDER BY id DESC LIMIT ?",
                (game_id, adviser_channel(faction), f"pair:{faction}|", f"pair:{faction}|",
                 f"|{faction}", f"|{faction}", limit)).fetchall()
        return [_row(r) for r in reversed(rows)]

    def queue(self, game_id: str, turn: int, channel: str, sender: str, text: str,
              kind: str = "turn") -> int:
        """kind: "turn" (a ruler's turn message), "chat" (a reply between turns), "notice"."""
        with closing(self._connect()) as db, db:
            return db.execute(
                "INSERT INTO outbox (game_id, turn, channel, sender, text, ts, kind) "
                "VALUES (?,?,?,?,?,?,?)",
                (game_id, turn, channel, sender, text, time.time(), kind)).lastrowid

    def chat_count(self, game_id: str, turn: int, sender: str) -> int:
        with closing(self._connect()) as db:
            return db.execute(
                "SELECT COUNT(*) FROM outbox WHERE game_id = ? AND turn = ? AND sender = ? "
                "AND kind = 'chat'", (game_id, turn, sender)).fetchone()[0]

    def mark_failed(self, outbox_id: int) -> None:
        """Set aside a row that can't be posted, so it stops blocking the rows after it."""
        with closing(self._connect()) as db, db:
            db.execute("UPDATE outbox SET posted = -1 WHERE id = ? AND posted = 0", (outbox_id,))

    def unposted(self, game_id: str) -> list[Message]:
        with closing(self._connect()) as db:
            rows = db.execute(
                "SELECT id, game_id, turn, channel, sender, text, ts FROM outbox "
                "WHERE game_id = ? AND posted = 0 ORDER BY id", (game_id,)).fetchall()
        return [_row(r) for r in rows]

    def mark_posted(self, outbox_id: int) -> None:
        """Mark an outbox row posted and record it as a message, atomically."""
        with closing(self._connect()) as db, db:
            r = db.execute("SELECT game_id, turn, channel, sender, text FROM outbox "
                           "WHERE id = ? AND posted = 0", (outbox_id,)).fetchone()
            if r is None:
                return
            db.execute("UPDATE outbox SET posted = 1 WHERE id = ?", (outbox_id,))
            db.execute("INSERT INTO messages (game_id, turn, channel, sender, text, ts) "
                       "VALUES (?,?,?,?,?,?)", (*r, time.time()))

    def sent_count(self, game_id: str, turn: int, sender: str, channel: str) -> int:
        with closing(self._connect()) as db:
            return db.execute(
                "SELECT COUNT(*) FROM outbox WHERE game_id = ? AND turn = ? AND sender = ? "
                "AND channel = ? AND kind = 'turn'", (game_id, turn, sender, channel)).fetchone()[0]
