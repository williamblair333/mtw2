"""Turn directory shared with the game: root/<game_id>/turn-<0000>/<faction>/.

Every write goes to <name>.tmp, is fsynced, then renamed into place, so a reader never
sees a half-written file. Readers ignore *.tmp.
"""

import os
import threading
import time
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from parley.protocol import OrderResult, Orders, StateReport

_results = TypeAdapter(list[OrderResult])


def atomic_write(path: Path, text: str) -> None:
    # Unique per writer, so two writers never trample each other's temp file.
    tmp = path.with_name(f"{path.name}.{os.getpid()}-{threading.get_ident()}-{os.urandom(3).hex()}.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


class TurnDir:
    def __init__(self, root: Path):
        self.root = Path(root)

    def path_for(self, game_id: str, turn: int, faction: str) -> Path:
        return self.root / game_id / f"turn-{turn:04d}" / faction

    def pending(self, game_id: str = "*") -> list[Path]:
        """Faction dirs whose state.json has no answer yet, or is newer than its answer
        (the game rewrote the report after a save was reloaded)."""
        found = []
        for state in self.root.glob(f"{game_id}/turn-*/*/state.json"):
            orders = state.parent / "orders.json"
            try:
                if not orders.exists() or state.stat().st_mtime > orders.stat().st_mtime:
                    found.append(state.parent)
            except FileNotFoundError:
                continue
        return sorted(found, key=lambda d: (d.parent.name, d.name))

    def is_superseded(self, dir: Path) -> bool:
        return (dir / "orders.json").exists()

    def archive_answer(self, dir: Path) -> Path:
        """Move a previous answer aside before answering a rewritten report."""
        dest = dir / f"superseded-{time.strftime('%Y%m%d-%H%M%S')}-{os.urandom(2).hex()}"
        dest.mkdir()
        for name in ("orders.json", "results.json", "prompt.txt", "answer.txt",
                     "rejected.json", "index_map.json"):
            if (dir / name).exists():
                os.replace(dir / name, dest / name)
        return dest

    def read_state(self, dir: Path) -> StateReport:
        # The game's strings may not be UTF-8; a bad byte must not stall the faction forever.
        text = (dir / "state.json").read_bytes().decode("utf-8", errors="replace")
        try:
            return StateReport.model_validate_json(text)
        except ValidationError as e:
            raise ValueError(f"bad state report in {dir}: {e}") from e

    def write_orders(self, dir: Path, orders: Orders) -> None:
        atomic_write(dir / "orders.json", orders.model_dump_json(indent=2))

    def write_artifact(self, dir: Path, name: str, text: str) -> None:
        atomic_write(dir / name, text)

    def read_results(self, dir: Path) -> list[OrderResult] | None:
        path = dir / "results.json"
        if not path.exists():
            return None
        return _results.validate_json(path.read_text(encoding="utf-8"))
