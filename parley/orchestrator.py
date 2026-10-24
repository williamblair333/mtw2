"""Answer every pending LLM-faction turn: prompt the seat, validate, write orders.

Whatever goes wrong while answering a turn, the turn still ends: the faction gets an
empty order set with the reason in its note. The game must never wait on us.
"""

import fcntl
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pydantic import TypeAdapter

from parley.bridge import TurnDir, atomic_write
from parley.config import GameConfig
from parley.events import diff_reports
from parley.prompt import build_prompt
from parley.protocol import OrderResult, Orders, StateReport
from parley.saves import backup_saves
from parley.seats import Seat, SeatError
from parley.store import Store, pair_channel
from parley.validate import validate_messages, validate_orders

log = logging.getLogger("parley")
_results = TypeAdapter(list[OrderResult])
MAX_WORKERS = 8
# The game's Lua can't create folders, so turn folders are made this many turns ahead.
LOOKAHEAD = 5
NOTES_KEPT = 5  # a ruler's own notes carried into its next prompts


class Orchestrator:
    def __init__(self, config: GameConfig, seats: dict[str, Seat]):
        self.config = config
        self.seats = seats
        self.turns = TurnDir(config.turn_root)
        self._skipped: set[Path] = set()
        self._lock_file = None
        config.turn_root.mkdir(parents=True, exist_ok=True)
        self.store = Store(config.turn_root / f"{config.game_id}.db")

    # --- one process per turn root -------------------------------------------------

    def acquire(self) -> None:
        self.config.turn_root.mkdir(parents=True, exist_ok=True)
        f = open(self.config.turn_root / ".orchestrator.lock", "a")
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            f.close()
            raise RuntimeError(f"an orchestrator is already running on {self.config.turn_root}")
        self._lock_file = f

    def release(self) -> None:
        if self._lock_file:
            fcntl.flock(self._lock_file, fcntl.LOCK_UN)
            self._lock_file.close()
            self._lock_file = None

    # --- what the game's Lua needs from us --------------------------------------------

    def publish_bridge_config(self) -> None:
        """turn_root/bridge.txt: the game ID and which factions are LLM seats."""
        lines = [f"game_id={self.config.game_id}"]
        lines += [f"faction={f}" for f in sorted(self.config.seats)]
        self.config.turn_root.mkdir(parents=True, exist_ok=True)
        atomic_write(self.config.turn_root / "bridge.txt", "\n".join(lines) + "\n")

    def prepare_turn_dirs(self, from_turn: int = 0) -> None:  # the game's first turn is 0
        for turn in range(from_turn, from_turn + LOOKAHEAD + 1):
            for faction in self.config.seats:
                self.turns.path_for(self.config.game_id, turn, faction).mkdir(
                    parents=True, exist_ok=True)

    # --- answering a turn ------------------------------------------------------------

    def _empty(self, dir: Path, report: StateReport | None, note: str) -> Orders:
        turn = report.turn if report else int(dir.parent.name.removeprefix("turn-"))
        return Orders(protocol=1, game_id=self.config.game_id, turn=turn,
                      faction=dir.name, orders=[], note=note)

    def _feedback(self, report: StateReport, dir: Path) -> StateReport:
        """Report last turn's results in the LLM's own numbering, rejections included.

        The game numbers only the orders it received (the kept ones); index_map.json maps
        those back to the LLM's original positions, and rejected.json adds the rest.
        """
        prev = self.turns.path_for(report.game_id, report.turn - 1, report.faction)
        if (prev / "late.txt").exists() and (prev / "orders.json").exists():
            late = Orders.model_validate_json((prev / "orders.json").read_text())
            return report.model_copy(update={"last_results": [
                OrderResult(index=i, type=o.type, ok=False, reason="arrived too late; not applied")
                for i, o in enumerate(late.orders)]})
        try:
            index_map = json.loads((prev / "index_map.json").read_text())
            rejected = _results.validate_json((prev / "rejected.json").read_text())
        except (OSError, ValueError):
            return report
        merged = [r.model_copy(update={"index": index_map[r.index]})
                  for r in report.last_results if r.index < len(index_map)]
        merged += rejected
        return report.model_copy(update={"last_results": sorted(merged, key=lambda r: r.index)})

    def _answer(self, dir: Path) -> bool:
        try:
            report = self.turns.read_state(dir)
        except (ValueError, OSError) as e:
            log.warning("state not readable yet in %s: %s", dir, e)
            return False
        if self.turns.is_superseded(dir):
            log.info("%s: report rewritten (save reloaded?); archived old answer to %s",
                     dir, self.turns.archive_answer(dir).name)
        try:
            orders, index_map = self._decide(dir, report)
        except Exception as e:  # never leave the game waiting
            log.exception("%s: failed to answer", dir)
            orders, index_map = self._empty(dir, report, f"orchestrator error: {e}"), []
        self.turns.write_artifact(dir, "index_map.json", json.dumps(index_map))
        self.turns.write_orders(dir, orders)
        self.prepare_turn_dirs(report.turn)
        self._announce_if_all_decided(report.turn)
        return True

    def _announce_if_all_decided(self, turn: int) -> None:
        """Tell the humans (#chronicle) once every LLM ruler has answered this turn."""
        game = self.config.game_id
        if not all((self.turns.path_for(game, turn, f) / "orders.json").exists()
                   for f in self.config.seats):
            return
        if self.store.sent_count(game, turn, "parley", "chronicle"):
            return
        self.store.queue(game, turn, "chronicle", "parley",
                         f"Turn {turn}: all rulers have decided. You may end your turn.")

    def _decide(self, dir: Path, report: StateReport) -> tuple[Orders, list[int]]:
        cfg = self.config
        if report.faction != dir.name or report.game_id != cfg.game_id:
            return self._empty(dir, report, (
                f"report mismatch: report says {report.game_id}/{report.faction}, "
                f"directory is {cfg.game_id}/{dir.name}")), []
        report = self._feedback(report, dir)
        diplomacy = self.store.recent(report.game_id, report.faction)
        prompt = build_prompt(report, cfg.seats[dir.name].persona, cfg.scenario,
                              diplomacy=diplomacy, names=cfg.display_names(),
                              notes=self._recent_notes(report), events=self._events(report))
        self.turns.write_artifact(dir, "prompt.txt", prompt)
        ids = dict(game_id=report.game_id, turn=report.turn, faction=report.faction)
        start = time.monotonic()
        try:
            orders, raw = self.seats[dir.name].decide(prompt, timeout=cfg.seat_timeout, **ids)
        except SeatError as e:
            log.error("%s turn %d: seat error: %s", report.faction, report.turn, e)
            orders, raw = Orders(protocol=1, orders=[], note=f"seat error: {e}", **ids), ""
        self.turns.write_artifact(dir, "answer.txt", raw)
        kept, rejected = validate_orders(report, orders)
        self.turns.write_artifact(
            dir, "rejected.json", json.dumps([r.model_dump() for r in rejected], indent=2))
        kept = kept.model_copy(update={"messages": self._send(report, orders, dir)})
        dropped = {r.index for r in rejected}
        index_map = [i for i in range(len(orders.orders)) if i not in dropped]
        log.info("%s turn %d: %d orders, %d rejected, %.1fs", report.faction, report.turn,
                 len(kept.orders), len(rejected), time.monotonic() - start)
        return kept, index_map

    def _recent_notes(self, report: StateReport, keep: int = NOTES_KEPT) -> list[tuple[int, str]]:
        """The ruler's own notes from its last few answered turns, oldest first."""
        notes = []
        for turn in range(report.turn - 1, -1, -1):
            path = self.turns.path_for(report.game_id, turn, report.faction) / "orders.json"
            try:
                note = Orders.model_validate_json(path.read_text()).note.strip()
            except (OSError, ValueError):
                continue
            if note and not note.startswith(("seat error", "orchestrator error", "report mismatch")):
                notes.append((turn, note))
            if len(notes) == keep:
                break
        return notes[::-1]

    def _events(self, report: StateReport) -> list[str]:
        prev = self.turns.path_for(report.game_id, report.turn - 1, report.faction)
        try:
            before = self.turns.read_state(prev)
        except (ValueError, OSError):
            return []
        return diff_reports(before, report)

    def _send(self, report: StateReport, orders: Orders, dir: Path) -> list:
        """Validate the faction's messages and queue the kept ones for the Discord bot."""
        def channel(to: str) -> str:
            return "lobby" if to == "lobby" else pair_channel(report.faction, to)

        kept, rejected = validate_messages(
            report, orders.messages,
            lambda to: self.store.sent_count(report.game_id, report.turn, report.faction, channel(to)),
            players=set(self.config.seats) | set(self.config.humans))
        for m in kept:
            self.store.queue(report.game_id, report.turn, channel(m.to), report.faction, m.text)
        self.turns.write_artifact(dir, "messages.json", json.dumps(
            {"kept": [m.model_dump() for m in kept], "rejected": [r.model_dump() for r in rejected]},
            indent=2))
        return kept

    # --- polling -----------------------------------------------------------------------

    def _follow_heartbeat(self) -> None:
        """The game writes heartbeat.txt (turn=N) at each turn start; keep folders ahead of it
        even after a reload to a later save or a gap while we were down."""
        try:
            text = (self.config.turn_root / "heartbeat.txt").read_text()
            turn = int(text.strip().removeprefix("turn="))
        except (OSError, ValueError):
            return
        if turn != getattr(self, "_heartbeat", None):
            self._heartbeat = turn
            self.prepare_turn_dirs(turn)

    def _announce_transfers(self) -> None:
        """Gold and land reaching a human arrive silently in the game. Tell the two sides, in
        their private thread only: a private deal's results must not leak to the table."""
        if not self.config.humans:
            return
        game = self.config.game_id
        for results in (self.config.turn_root / game).glob("turn-*/*/results.json"):
            d = results.parent
            if d.name not in self.config.seats or (d / "announced.txt").exists():
                continue
            try:
                orders = Orders.model_validate_json((d / "orders.json").read_text())
                done = {r.index for r in _results.validate_json(results.read_text()) if r.ok}
            except (OSError, ValueError):
                continue
            sender = d.name.replace("_", " ").title()
            for i, o in enumerate(orders.orders):
                if i not in done or getattr(o, "to", None) not in self.config.humans:
                    continue
                to = o.to.replace("_", " ").title()
                if o.type == "send_gold":
                    text = f"📜 {sender} sent {to} {o.amount} florins."
                elif o.type == "cede_settlement":
                    text = f"📜 {sender} gave {to} {o.settlement}."
                else:
                    continue
                self.store.queue(game, orders.turn, pair_channel(d.name, o.to), "parley", text)
            self.turns.write_artifact(d, "announced.txt", "")

    def run_once(self) -> int:
        self._follow_heartbeat()
        self._announce_transfers()
        todo = []
        for d in self.turns.pending(self.config.game_id):
            if d.name in self.config.seats and d.name in self.seats:
                todo.append(d)
            elif d not in self._skipped:
                self._skipped.add(d)
                log.info("skipping %s: not an LLM seat", d)
        if not todo:
            return 0
        turn = todo[0].parent.name
        try:  # one backup per poll, before any seat starts
            backup_saves(self.config.save_dir, self.config.backup_dir,
                         label=f"{turn}-{'+'.join(d.name for d in todo)}",
                         keep=self.config.keep_backups)
        except OSError as e:
            log.error("save backup failed: %s", e)
        with ThreadPoolExecutor(max_workers=min(len(todo), MAX_WORKERS)) as pool:
            return sum(pool.map(self._answer, todo))

    def run_forever(self, poll: float = 0.5) -> None:
        self.publish_bridge_config()
        self.prepare_turn_dirs()
        log.info("watching %s", self.turns.root)
        while True:
            try:
                self.run_once()
            except KeyboardInterrupt:
                raise
            except Exception:
                log.exception("poll failed; continuing")
            time.sleep(poll)
