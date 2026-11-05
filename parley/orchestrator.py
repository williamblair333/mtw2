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
from concurrent.futures import Future, ThreadPoolExecutor, wait as wait_futures
from pathlib import Path

from pydantic import TypeAdapter

from jigsaw import Decision, DecisionLog
from parley.audit import alert_lines, audit_game, new_findings, refusal_key, refusals, ruler_notes
from parley.bridge import TurnDir, atomic_write
from parley.config import GameConfig
from parley.control import PRESETS
from parley.decisions import record_outcomes, record_turn
from parley.events import diff_reports
from parley.popups import Popups, make_reader
from parley.prompt import build_prompt, order_brief
from parley.protocol import OrderResult, Orders, StateReport
from parley.saves import backup_saves
from parley import lessons, pause
from parley.seats import Seat, SeatError, make_seat
from parley.seats.base import SeatLimit
from parley.steward import backfill, steward_notes
from parley.store import Store, adviser_channel, pair_channel
from parley.turn_gate import quiet_turn
from parley.validate import MAX_ORDERS, cost, order_cap, validate_messages, validate_orders
from parley.victory import campaign_dir, read_history, victory_line

log = logging.getLogger("parley")
_results = TypeAdapter(list[OrderResult])
MAX_WORKERS = 8
# The game's Lua can't create folders, so turn folders are made this many turns ahead.
LOOKAHEAD = 5
REFUSAL_LOOKBACK = 8  # earlier turns read for 'refused N turns running'
NOTES_KEPT = 5  # a ruler's own notes carried into its next prompts
REVIEW_EVERY = 20  # turns between a ruler's lessons reviews
REVIEW_TIMEOUT = 300
EMPTY_ORDERS_NOTE = 300  # a note this long with no orders is a plan the ruler forgot to order
EMPTY_ORDERS_RETRY = ("\n\nYOUR LAST ANSWER: your note described a plan, but your \"orders\" list "
                      "was empty, so nothing would happen in the game. Answer again, with every "
                      "order your plan needs in \"orders\". An empty list is right only if you truly "
                      "mean to do nothing this turn.\n")


class Fallback:
    """A seat or popup decider that falls back to a second brain when the first fails (live: the
    Opus decider hit a session limit; France's Gemini seat hung 4 of 11 turns). A usage limit
    on both still raises SeatLimit, so the game pauses as before."""

    def __init__(self, decider, own, faction: str, reserve: float = 90):
        self.decider, self.own, self.faction, self.reserve = decider, own, faction, reserve
        self.name = getattr(decider, "name", faction)

    def decide(self, prompt: str, *, game_id: str, turn: int, faction: str,
               timeout: float) -> tuple[Orders, str]:
        try:
            return self.decider.decide(prompt, game_id=game_id, turn=turn, faction=faction,
                                       timeout=max(60, timeout - self.reserve))
        except SeatError as e:
            log.warning("%s turn %d: %s failed (%s); asked %s instead",
                        faction, turn, getattr(self.decider, "name", self.faction), e,
                        getattr(self.own, "name", "fallback"))
            return self.own.decide(prompt, game_id=game_id, turn=turn, faction=faction,
                                   timeout=self.reserve)

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
    def __init__(self, config: GameConfig, seats: dict[str, Seat], quiet_seats: dict[str, Seat] | None = None):
        self.config = config
        self.seats = {f: Fallback(seat, make_seat(s.fallback, config.budget_for(f)), f, config.fallback_reserve)
                      if (s := config.seats.get(f)) and s.fallback and s.fallback != s.brain else seat
                      for f, seat in seats.items()}
        self._quiet_streaks: dict[str, int] = {}
        self._quiet_seats: dict[str, Seat] = dict(quiet_seats) if quiet_seats else {}
        self.turns = TurnDir(config.turn_root)
        self._skipped: set[Path] = set()
        self._known: dict[tuple[str, str], dict] = {}  # foreign settlements each ruler has seen
        self._retry_at = 0.0  # while paused for a usage limit: when to try the seats again
        self._audited_turn: int | None = None  # the turn audit runs once a turn (see _audit)
        self._audit_findings: list = []
        self._lock_file = None
        # seats run on one long-lived pool and the scan never waits for them: a report that
        # lands while another seat is still thinking starts at once (live 2026-10-30: France's
        # report came 17 s after England's, and France's turn started only after England's ended)
        self._pool: ThreadPoolExecutor | None = None
        self._inflight: dict[Path, Future] = {}
        config.turn_root.mkdir(parents=True, exist_ok=True)
        self.store = Store(config.turn_root / f"{config.game_id}.db")
        self.lessons_root = config.turn_root / "lessons"  # shared by every game on this turn root
        self._decision_log: DecisionLog | None = None
        self._decision_log_lock = threading.Lock()
        # under autoplay nobody reads the game's popups: screenshot, read and decide them
        deciders = {f: Fallback(make_seat(s.decider, config.budget_for(f)), seats[f], f) if s.decider and s.decider != s.brain and f in seats
                    else seats.get(f) for f, s in config.seats.items()}
        self.popups = (
            Popups(
                config.turn_root,
                config.game_id,
                deciders,
                {f: s.persona for f, s in config.seats.items()},
                read=make_reader(config.reader),
                ladder={f for f, s in config.seats.items() if s.ladder},
                decision_log=self.decision_log,
                decide_timeout=config.decide_timeout,
            )
            if config.autoplay
            else None
        )

    @property
    def decision_log(self) -> DecisionLog:
        """Every ruler decision, for analysis (Jigsaw); one log shared by the seat threads."""
        with self._decision_log_lock:
            if self._decision_log is None:
                self._decision_log = DecisionLog(self.config.turn_root / f"{self.config.game_id}.decisions.db")
            return self._decision_log

    @decision_log.setter
    def decision_log(self, value: DecisionLog) -> None:
        self._decision_log = value
        if self.popups is not None:
            self.popups.decision_log = value

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
        lines += [f"freeze={f}" for f, s in sorted(self.config.seats.items()) if s.freeze]
        if self.config.freeze_others:  # the QA bench's quiet world
            lines += ["freeze=*"] + [f"thaw={f}" for f in sorted(set(self.config.thaw))]
        lines += [f"playtest_funds={f}:{s.playtest_funds_amount}" for f, s in sorted(self.config.seats.items())
                  if s.playtest_funds]
        if auto := self.config.autoplay:
            lines += ["autoplay=1", f"autoplay_wait={auto.wait}"]
            if auto.until_turn is not None:
                lines.append(f"autoplay_until={auto.until_turn}")
            if not auto.hold_decisions:
                lines.append("autoplay_hold_decisions=0")
            if auto.papal_hands_off:
                lines.append("papal_hands_off=1")
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

    def _refusal_history(self, report: StateReport) -> list[set[str]]:
        """Refusal keys of each turn before last turn, newest first, read from the turn folders
        (the same keys audit.py compares); stops at the first turn with no folder."""
        out = []
        for turn in range(report.turn - 2, max(report.turn - 2 - REFUSAL_LOOKBACK, 0), -1):
            folder = self.turns.path_for(report.game_id, turn, report.faction)
            if not folder.is_dir():
                break
            out.append({refusal_key(r.get("type"), r.get("reason")) for _, r in refusals(folder)})
        return out

    def _feedback(self, report: StateReport, dir: Path) -> StateReport:
        """Report last turn's results in the LLM's own numbering, rejections included.

        The game numbers only the orders it received (the kept ones); index_map.json maps
        those back to the LLM's original positions, and rejected.json adds the rest.
        """
        prev = self.turns.path_for(report.game_id, report.turn - 1, report.faction)
        if (prev / "late.txt").exists() and (prev / "orders.json").exists():
            late = Orders.model_validate_json((prev / "orders.json").read_text())
            results = [
                OrderResult(index=i, type=o.type, ok=False, reason="arrived too late; not applied")
                for i, o in enumerate(late.orders)
            ]
            final_report = report.model_copy(update={"last_results": results})
            try:
                # orders.json numbers the kept orders; the log uses the LLM's own numbering
                imap = json.loads((prev / "index_map.json").read_text())
                logged = [r.model_copy(update={"index": imap[r.index]}) for r in results if r.index < len(imap)]
                record_outcomes(self.decision_log, report.game_id, report.faction, report.turn - 1, logged, report.turn)
            except Exception as e:
                log.warning("recording outcomes failed: %s", e)
            return final_report
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
                                       "brief": order_brief(sent[r.index]) if r.index < len(sent) else "",
                                       "now": _armies_now(sent[r.index], report, had) if r.index < len(sent) else ""})
                  for r in report.last_results if r.index < len(index_map)]
        merged += rejected
        results = sorted(merged, key=lambda r: r.index)
        final_report = report.model_copy(update={"last_results": results})
        try:
            record_outcomes(self.decision_log, report.game_id, report.faction, report.turn - 1, results, report.turn)
        except Exception as e:
            log.warning("recording outcomes failed: %s", e)
        return final_report

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
        if report.turn > 0 and report.turn % REVIEW_EVERY == 0 and dir.name in self.seats:
            threading.Thread(target=self.review, args=(dir.name, report.turn), daemon=True).start()
        return True

    # --- lessons across games (per persona; the author vetoes with `just lessons-veto`) ------

    def _lesson_key(self, faction: str) -> str:
        return lessons.key_for(self.config.seats[faction].name or faction)

    def _lessons(self, faction: str) -> list[str]:
        return [x.text for x in lessons.active(self.lessons_root, self._lesson_key(faction))]

    def review(self, faction: str, turn: int) -> list[lessons.Lesson]:
        """Ask the ruler's own brain what the last REVIEW_EVERY turns teach, and keep the lessons."""
        game, history, states = self.config.game_id, [], []
        for t in range(max(0, turn - REVIEW_EVERY + 1), turn + 1):
            d = self.turns.path_for(game, t, faction)
            try:
                note = Orders.model_validate_json((d / "orders.json").read_text()).note.strip()
            except (OSError, ValueError):
                continue
            results = []
            for name in ("results.json", "rejected.json"):
                try:
                    results += [f"order {r.index} ({r.type}): {('done: ' + r.note) if getattr(r, 'note', '') else ('done' if r.ok else 'REJECTED: ' + r.reason)}"
                                for r in _results.validate_json((d / name).read_text())]
                except (OSError, ValueError):
                    pass
            history.append((t, note, results))
            try:
                states.append((t, self.turns.read_state(d)))
            except (ValueError, OSError):
                pass
        if not history:
            return []
        name = self.config.seats[faction].name or faction
        try:
            prompt = lessons.review_prompt(name, faction, history, lessons.outcomes_section(states))
            answer = self.seats[faction].chat(prompt, timeout=REVIEW_TIMEOUT)
            added = lessons.add(self.lessons_root, self._lesson_key(faction), lessons.parse_review(answer),
                                game_id=game, turn=turn, version=lessons.code_version(Path(__file__).parent),
                                today=time.strftime("%Y-%m-%d"))
        except Exception:  # a review never disturbs the game
            log.exception("%s: lessons review at turn %d failed", faction, turn)
            return []
        log.info("%s: lessons review at turn %d kept %d new", faction, turn, len(added))
        return added

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
        seat_cfg = cfg.seats[dir.name]
        areas = seat_cfg.areas
        events = self._events(report) + ruler_notes(self._audit_findings, report.faction, report.turn - 1)
        game_messages = self.popups.messages_for(report.faction) if self.popups else None
        shown = (game_messages or []) + self._steward_notes(report, seat_cfg)
        prompt = build_prompt(report, seat_cfg.persona, cfg.scenario,
                              diplomacy=diplomacy, names=cfg.display_names(),
                              notes=self._recent_notes(report), plan=self._last_plan(report),
                              lessons=self._lessons(dir.name), events=events,
                              areas=areas, adviser=seat_cfg.adviser,
                              refusal_history=self._refusal_history(report),
                              game_messages=shown or None,
                              playtest_funds=seat_cfg.playtest_funds,
                              playtest_funds_amount=seat_cfg.playtest_funds_amount,
                              victory=victory_line(report.faction, report.turn, len(report.settlements),
                                                   campaign_dir(cfg.save_dir.parent), cfg.campaign_length,
                                                   read_history(self.turns.path_for, report),
                                                   factions=report.factions))
        self.turns.write_artifact(dir, "prompt.txt", prompt)
        ids = dict(game_id=report.game_id, turn=report.turn, faction=report.faction)
        start = time.monotonic()

        is_gated = seat_cfg.ladder and bool(seat_cfg.quiet_brain)
        answered_by_quiet = False
        reason = ""
        answered_brain = seat_cfg.brain

        if is_gated:
            streak = self._quiet_streaks.get(report.faction, 0)
            # only what others said since the ruler's last turn: `recent` is the last 30 of any
            # turn, the ruler's own adviser reports included (live: every turn escalated)
            fresh = [m for m in diplomacy if m.sender != report.faction and m.turn >= report.turn - 1]
            reason = quiet_turn(
                report,
                events=events,
                diplomacy=fresh,
                game_messages=game_messages,
                quiet_streak=streak,
            )
            if not reason:
                quiet_seat = self._quiet_seats.get(report.faction)
                if quiet_seat is None:
                    quiet_seat = make_seat(seat_cfg.quiet_brain, cfg.budget_for(report.faction))
                    self._quiet_seats[report.faction] = quiet_seat
                try:
                    orders, raw = quiet_seat.decide(prompt, timeout=cfg.seat_timeout, **ids)
                    if not orders.orders:
                        log.warning(
                            "%s turn %d: quiet brain (%s) returned no orders; falling back to ruler",
                            report.faction, report.turn, seat_cfg.quiet_brain,
                        )
                    else:
                        answered_by_quiet = True
                        answered_brain = seat_cfg.quiet_brain
                        self._quiet_streaks[report.faction] = streak + 1
                except SeatLimit:
                    raise
                except SeatError as e:
                    log.warning(
                        "%s turn %d: quiet brain (%s) seat error (%s); falling back to ruler",
                        report.faction, report.turn, seat_cfg.quiet_brain, e,
                    )

        if not answered_by_quiet:
            if is_gated:
                self._quiet_streaks[report.faction] = 0
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

        if is_gated:
            try:
                self.decision_log.record(Decision(
                    game=report.game_id,
                    turn=report.turn,
                    actor=report.faction,
                    kind="turn_gate",
                    situation="quiet turn" if not reason else reason,
                    rung=4 if answered_by_quiet else 5,
                    escalated_because=reason,
                    choice=answered_brain,
                ))
            except Exception as e:
                log.warning("turn_gate decision log failed: %s", e)

        self.turns.write_artifact(dir, "answer.txt", raw)
        kept, rejected = validate_orders(report, orders, areas,
                                         playtest_funds=seat_cfg.playtest_funds,
                                         playtest_funds_amount=seat_cfg.playtest_funds_amount)
        # back into the LLM's own numbering: to_orders may have dropped malformed orders already
        source = orders.source_index
        rejected = [r.model_copy(update={"index": source[r.index]}) for r in rejected] + orders.malformed
        self.turns.write_artifact(
            dir, "rejected.json", json.dumps([r.model_dump() for r in rejected], indent=2))
        kept = kept.model_copy(update={"messages": self._send(report, orders, dir)})
        dropped = {r.index for r in rejected if r.type != "say"}
        index_map = [source[i] for i in range(len(orders.orders)) if source[i] not in dropped]
        kept, index_map = self._steward(report, orders, kept, index_map, dir, seat_cfg)
        log.info("%s turn %d: %d orders, %d rejected, %.1fs", report.faction, report.turn,
                 len(kept.orders), len(rejected), time.monotonic() - start)
        try:
            record_turn(self.decision_log, report, orders, kept, rejected, answered_brain)
        except Exception as e:
            log.warning("decision log failed: %s", e)
        return kept, index_map

    def _steward(self, report: StateReport, orders: Orders, kept: Orders, index_map: list[int],
                 dir: Path, seat_cfg) -> tuple[Orders, list[int]]:
        """For a seat with `steward`: append recruits for garrisons the ruler's orders leave empty.
        Only ever appends, after the ruler's orders, which pass through untouched; never raises."""
        if not seat_cfg.steward:
            return kept, index_map
        try:
            gold = max(report.treasury, seat_cfg.playtest_funds_amount) if seat_cfg.playtest_funds else report.treasury
            gold -= sum(cost(report, o) for o in kept.orders)
            added, notes = backfill(report, kept, seat_cfg.areas, gold)
            cap = order_cap(report, MAX_ORDERS)
            room = max(0, cap - len(kept.orders))  # the bridge runs every order in one frame
            added = added[:room]
            if not notes:
                return kept, index_map
            # numbered after the ruler's own, so results and audits can tell them apart
            first = max([*orders.source_index, *(r.index for r in orders.malformed if r.type != "say")],
                        default=-1) + 1
            n = 0
            for note in notes:
                if "unit" in note:
                    if n >= len(added):  # cut by the order limit: say so, don't claim a recruit
                        note["failed"] = f"your orders filled the turn's {cap}-order limit"
                        continue
                    note["index"] = first + n
                    n += 1
            self.turns.write_artifact(dir, "steward.json", json.dumps(notes, indent=2))
            if not added:
                return kept, index_map
            log.info("%s turn %d: steward added %d recruit(s)", report.faction, report.turn, len(added))
            return (kept.model_copy(update={"orders": [*kept.orders, *added]}),
                    index_map + [first + i for i in range(len(added))])
        except Exception:  # the steward never costs the ruler its turn
            log.exception("%s turn %d: steward failed; the ruler's orders go as given", report.faction, report.turn)
            return kept, index_map

    def _steward_notes(self, report: StateReport, seat_cfg) -> list[str]:
        """What the steward did last turn, for this turn's prompt."""
        if not seat_cfg.steward:
            return []
        prev = self.turns.path_for(report.game_id, report.turn - 1, report.faction) / "steward.json"
        try:
            return steward_notes(json.loads(prev.read_text()))
        except (OSError, ValueError):
            return []

    def _last_plan(self, report: StateReport) -> str:
        """The ruler's standing plan from its most recent earlier turn that had one."""
        for turn in range(report.turn - 1, -1, -1):
            path = self.turns.path_for(report.game_id, turn, report.faction) / "orders.json"
            try:
                plan = Orders.model_validate_json(path.read_text()).plan.strip()
            except (OSError, ValueError):
                continue
            if plan:
                return plan
        return ""

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

    def _reap(self) -> int:
        """Forget the seats that have finished; how many of them answered their turn."""
        answered = 0
        for d, fut in list(self._inflight.items()):
            if not fut.done():
                continue
            del self._inflight[d]
            try:
                answered += bool(fut.result())
            except Exception:  # _answer catches its own; never lose the poll loop to a stray one
                log.exception("%s: seat thread failed", d)
        return answered

    def run_once(self, wait: bool = True) -> int:
        """One poll: start a seat for every open turn folder not already being answered, and
        count the seats that finished since the last poll. wait=False (run_forever) returns
        at once, leaving the seats running; wait=True also waits for every running seat."""
        self._follow_heartbeat()
        self._announce_transfers()
        answered = self._reap()
        todo = []
        for d in self.turns.pending(self.config.game_id):
            if d in self._inflight:
                continue
            if d.name in self.config.seats and d.name in self.seats:
                todo.append(d)
            elif d not in self._skipped:
                self._skipped.add(d)
                log.info("skipping %s: not an LLM seat", d)
        paused = pause.paused(self.config.turn_root) and time.monotonic() < self._retry_at
        if todo and not paused:  # waiting out a usage limit: the turns stay open
            turn = todo[0].parent.name
            self._audit(int(turn.removeprefix("turn-")))
            try:  # one backup per poll, before any seat starts
                backup_saves(self.config.mod_save_dir, self.config.backup_dir,
                             label=f"{turn}-{'+'.join(d.name for d in todo)}",
                             keep=self.config.keep_backups)
            except OSError as e:
                log.error("save backup failed: %s", e)
            if self._pool is None:
                self._pool = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="seat")
            for d in todo:
                self._inflight[d] = self._pool.submit(self._answer, d)
        if wait and self._inflight:
            wait_futures(list(self._inflight.values()))
            answered += self._reap()
        return answered

    def _audit(self, turn: int) -> None:
        """Once a turn, before the seats start: audit the turns just played, post problems not
        seen before to the humans' audit channel, and keep the findings for the rulers' prompts.
        The author, 2026-10-29: problems sat in the turn folders until he asked."""
        if self._audited_turn == turn:
            return
        self._audited_turn = turn
        game_dir = self.config.turn_root / self.config.game_id
        try:
            self._audit_findings = audit_game(game_dir, since=turn - 2)
            for line in alert_lines(new_findings(game_dir, self._audit_findings), self.config.game_id):
                self.store.queue(self.config.game_id, turn, "audit", "parley", line, kind="notice")
        except Exception:  # never hold up a turn for the audit
            log.exception("turn audit failed")

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
                self.run_once(wait=False)
            except KeyboardInterrupt:
                raise
            except Exception:
                log.exception("poll failed; continuing")
            time.sleep(poll)
