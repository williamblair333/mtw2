"""Answer every pending LLM-faction turn: prompt the seat, validate, write orders.

Whatever goes wrong while answering a turn, the turn still ends: the faction gets an
empty order set with the reason in its note. The game must never wait on us, with one
exception: a seat's usage limit pauses the game (parley/pause.py) instead, since playing on
would leave every ruler silent and every decision defaulted.
"""

import fcntl
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pydantic import TypeAdapter

from parley.bridge import TurnDir, atomic_write
from parley.config import GameConfig
from parley.control import PRESETS
from parley.events import diff_reports
from parley.popups import Popups
from parley.prompt import build_prompt
from parley.protocol import OrderResult, Orders, StateReport
from parley.saves import backup_saves
from parley import pause
from parley.seats import Seat, SeatError, make_seat
from parley.seats.base import SeatLimit
from parley.store import Store, adviser_channel, pair_channel
from parley.validate import validate_messages, validate_orders

log = logging.getLogger("parley")
_results = TypeAdapter(list[OrderResult])
MAX_WORKERS = 8
# The game's Lua can't create folders, so turn folders are made this many turns ahead.
LOOKAHEAD = 5
NOTES_KEPT = 5  # a ruler's own notes carried into its next prompts
EMPTY_ORDERS_NOTE = 300  # a note this long with no orders is a plan the ruler forgot to order
EMPTY_ORDERS_RETRY = ("\n\nYOUR LAST ANSWER: your note described a plan, but your \"orders\" list "
                      "was empty, so nothing would happen in the game. Answer again, with every "
                      "order your plan needs in \"orders\". An empty list is right only if you truly "
                      "mean to do nothing this turn.\n")


class Fallback:
    """A seat's popup decider that falls back to the seat's own brain when it fails (live: the
    Opus decider hit a session limit and the decisions were declined unanswered). A usage limit
    on both still raises SeatLimit, so the game pauses as before."""

    def __init__(self, decider, own, faction: str):
        self.decider, self.own, self.faction = decider, own, faction

    def chat(self, prompt: str, *, timeout: float) -> str:
        try:
            return self.decider.chat(prompt, timeout=timeout)
        except SeatError as e:
            log.error("%s: the popup decider failed (%s); asking the seat's own brain", self.faction, e)
            return self.own.chat(prompt, timeout=timeout)


ARMY_ORDERS = {"march_on", "move_army", "attack", "besiege", "withdraw", "merge_armies", "merge_units", "disband",
               "board", "land", "blockade"}


def _armies_now(order, report: StateReport, had: set[str]) -> str:
    """For an army order: each of your armies it named (had: your army ids last turn), as it
    stands now ("done" only means the order was given; seen live: a ruler asking every turn
    whether a merge or a boarding took)."""
    if order.type not in ARMY_ORDERS:
        return ""
    armies = {a.id: a for a in report.armies}
    named = [v for v in order.model_dump().values() if isinstance(v, str) and (v in armies or v in had)]
    out = []
    for name in dict.fromkeys(named):
        a = armies.get(name)
        if a is None:
            out.append(f"{name} is no longer one of your armies (merged, destroyed or renamed)")
            continue
        where = f"in {a.in_settlement}" if a.in_settlement else f"at ({a.x},{a.y})"
        if a.aboard:
            where += f", aboard {a.aboard}"
        if a.is_fleet:
            where += f", carrying {a.carrying} units" if a.carrying else ", empty"
        out.append(f"{name} has {a.units} units, {where}")
    target = getattr(order, "target", None)
    if order.type == "attack" and target:  # did the battle happen? (live: "done", no battle:
        foe = next((e for e in report.visible_enemies if e.id == target), None)  # out of reach)
        out.append(f"{target} has {foe.units} units, at ({foe.x},{foe.y}), {foe.distance} tiles from you; "
                   "unchanged ranks on both sides mean no battle was fought (out of reach)" if foe
                   else f"{target} is no longer in sight")
    return "; ".join(out)


class Orchestrator:
    def __init__(self, config: GameConfig, seats: dict[str, Seat]):
        self.config = config
        self.seats = seats
        self.turns = TurnDir(config.turn_root)
        self._skipped: set[Path] = set()
        self._known: dict[tuple[str, str], dict] = {}  # foreign settlements each ruler has seen
        self._retry_at = 0.0  # while paused for a usage limit: when to try the seats again
        self._lock_file = None
        config.turn_root.mkdir(parents=True, exist_ok=True)
        self.store = Store(config.turn_root / f"{config.game_id}.db")
        # under autoplay nobody reads the game's popups: screenshot, read and decide them
        deciders = {f: Fallback(make_seat(s.decider), seats[f], f) if s.decider and s.decider != s.brain and f in seats
                    else seats.get(f) for f, s in config.seats.items()}
        self.popups = Popups(config.turn_root, config.game_id, deciders,
                             {f: s.persona for f, s in config.seats.items()}) if config.autoplay else None

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
        # the bridge refuses orders outside a seat's areas too; no line means the default, ruler
        lines += [f"control={f}:{','.join(s.areas)}" for f, s in sorted(self.config.seats.items())
                  if s.areas != PRESETS["ruler"]]
        if auto := self.config.autoplay:
            lines += ["autoplay=1", f"autoplay_wait={auto.wait}"]
            if auto.until_turn is not None:
                lines.append(f"autoplay_until={auto.until_turn}")
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
        try:
            sent = Orders.model_validate_json((prev / "orders.json").read_text()).orders
            had = {a.id for a in self.turns.read_state(prev).armies}
        except (OSError, ValueError):
            sent, had = [], set()
        merged = [r.model_copy(update={"index": index_map[r.index],
                                       "now": _armies_now(sent[r.index], report, had) if r.index < len(sent) else ""})
                  for r in report.last_results if r.index < len(index_map)]
        merged += rejected
        return report.model_copy(update={"last_results": sorted(merged, key=lambda r: r.index)})

    def _since_last(self, report: StateReport) -> StateReport:
        """Foreign armies seen last turn elsewhere get where they were (the way they head), and
        foreign settlements seen before but out of sight now are remembered as last seen."""
        report = report.model_copy(update={"remembered": self._remembered(report)})
        prev = self.turns.path_for(report.game_id, report.turn - 1, report.faction)
        try:
            before = self.turns.read_state(prev)
        except (ValueError, OSError):
            return report
        was = {a.id: a for a in before.visible_enemies}
        seen = [a.model_copy(update={"from_x": was[a.id].x, "from_y": was[a.id].y})
                if a.id in was and (was[a.id].x, was[a.id].y) != (a.x, a.y) else a
                for a in report.visible_enemies]
        return report.model_copy(update={"visible_enemies": seen})

    def _remembered(self, report: StateReport) -> list:
        """The map a player keeps: every foreign settlement this ruler's reports ever showed (live,
        the adviser: "have you fully explored Ireland and England?"). Read once from past turns."""
        key = (report.game_id, report.faction)
        known = self._known.get(key)
        if known is None:
            known = {}
            for turn in range(max(0, report.turn - 400), report.turn):
                try:
                    past = self.turns.read_state(self.turns.path_for(report.game_id, turn, report.faction))
                except (ValueError, OSError):
                    continue
                for s in past.nearby_settlements:
                    known[s.id] = s.model_copy(update={"seen_turn": past.turn})
            self._known[key] = known
        for s in report.nearby_settlements:
            known[s.id] = s.model_copy(update={"seen_turn": report.turn})
        in_sight = {s.id for s in report.nearby_settlements} | {s.id for s in report.settlements}
        return sorted((s for s in known.values() if s.id not in in_sight), key=lambda s: s.name)

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
        except SeatLimit as e:  # nobody can answer until it resets: pause, keep the turn open
            log.error("%s: %s; pausing the game, retrying in %ds", dir, e, pause.RETRY)
            pause.pause(self.config.turn_root, str(e))
            self._retry_at = time.monotonic() + pause.RETRY
            return False
        except Exception as e:  # never leave the game waiting
            log.exception("%s: failed to answer", dir)
            orders, index_map = self._empty(dir, report, f"orchestrator error: {e}"), []
        self.turns.write_artifact(dir, "index_map.json", json.dumps(index_map))
        self.turns.write_orders(dir, orders)
        if pause.paused(self.config.turn_root) and not orders.note.startswith(("seat error", "orchestrator error")):
            log.info("a ruler answered again; resuming the game")
            pause.resume(self.config.turn_root)
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
        report = self._since_last(self._feedback(report, dir))
        diplomacy = self.store.recent(report.game_id, report.faction)
        areas = cfg.seats[dir.name].areas
        prompt = build_prompt(report, cfg.seats[dir.name].persona, cfg.scenario,
                              diplomacy=diplomacy, names=cfg.display_names(),
                              notes=self._recent_notes(report), events=self._events(report),
                              areas=areas, adviser=cfg.seats[dir.name].adviser,
                              game_messages=self.popups.messages_for(report.faction) if self.popups else None)
        self.turns.write_artifact(dir, "prompt.txt", prompt)
        ids = dict(game_id=report.game_id, turn=report.turn, faction=report.faction)
        start = time.monotonic()
        try:
            orders, raw = self.seats[dir.name].decide(prompt, timeout=cfg.seat_timeout, **ids)
            if not orders.orders and len(orders.note or "") > EMPTY_ORDERS_NOTE:
                # live: Opus wrote ten orders into its note and returned an empty list, a turn lost
                log.warning("%s turn %d: no orders but a %d-character plan; asking again",
                            report.faction, report.turn, len(orders.note))
                orders, raw = self.seats[dir.name].decide(prompt + EMPTY_ORDERS_RETRY, timeout=cfg.seat_timeout, **ids)
        except SeatLimit:
            raise
        except SeatError as e:
            log.error("%s turn %d: seat error: %s", report.faction, report.turn, e)
            orders, raw = Orders(protocol=1, orders=[], note=f"seat error: {e}", **ids), ""
        self.turns.write_artifact(dir, "answer.txt", raw)
        kept, rejected = validate_orders(report, orders, areas)
        # back into the LLM's own numbering: to_orders may have dropped malformed orders already
        source = orders.source_index
        rejected = [r.model_copy(update={"index": source[r.index]}) for r in rejected] + orders.malformed
        self.turns.write_artifact(
            dir, "rejected.json", json.dumps([r.model_dump() for r in rejected], indent=2))
        kept = kept.model_copy(update={"messages": self._send(report, orders, dir)})
        dropped = {r.index for r in rejected if r.type != "say"}
        index_map = [source[i] for i in range(len(orders.orders)) if source[i] not in dropped]
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
            if to == "adviser":
                return adviser_channel(report.faction)
            return "lobby" if to == "lobby" else pair_channel(report.faction, to)

        kept, rejected = validate_messages(
            report, orders.messages,
            lambda to: self.store.sent_count(report.game_id, report.turn, report.faction, channel(to)),
            players=set(self.config.seats) | set(self.config.humans),
            adviser=bool(self.config.seats[report.faction].adviser))
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
        if pause.paused(self.config.turn_root) and time.monotonic() < self._retry_at:
            return 0  # waiting out a usage limit; the turns stay open
        turn = todo[0].parent.name
        try:  # one backup per poll, before any seat starts
            backup_saves(self.config.save_dir, self.config.backup_dir,
                         label=f"{turn}-{'+'.join(d.name for d in todo)}",
                         keep=self.config.keep_backups)
        except OSError as e:
            log.error("save backup failed: %s", e)
        with ThreadPoolExecutor(max_workers=min(len(todo), MAX_WORKERS)) as pool:
            return sum(pool.map(self._answer, todo))

    def _popup_loop(self) -> None:
        while True:
            try:
                self.popups.poll()
            except Exception:
                log.exception("popup poll failed; continuing")
            time.sleep(0.5)

    def run_forever(self, poll: float = 0.5) -> None:
        self.publish_bridge_config()
        self.prepare_turn_dirs()
        log.info("watching %s", self.turns.root)
        if self.popups:  # its own thread: the bridge holds a popup only ~30 s for its screenshot
            threading.Thread(target=self._popup_loop, daemon=True).start()
        while True:
            try:
                self.run_once()
            except KeyboardInterrupt:
                raise
            except Exception:
                log.exception("poll failed; continuing")
            time.sleep(poll)
