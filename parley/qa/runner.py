"""QA bench runner: park the real campaign, run smoke + suite cases, write report, and restore."""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import tomllib
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel

from parley.bridge import atomic_write
from parley.config import GameConfig, load_config
from parley.orchestrator import Orchestrator
from parley.pause import path as pause_path
from parley.qa.cases import INSTANT_WITHIN, Case, Expect, SetupStep, Suite, load_suite
from parley.qa.checker import alive_after, check
from parley.qa.control import Control, ControlTimeout, LOG_FILE
from parley.qa.power import power_off_refusal, power_off_time
from parley.seats.script import NEAREST_CHARACTER_TO
from parley.setup import to_toml
from parley.xinput import XInputRefused, env_without, no_click_run, refuse_x_input

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SUITES_DIR = REPO_ROOT / "games" / "qa"
DEFAULT_REPORT_DIR = REPO_ROOT / "runs" / "qa"
LOCK_FILE = "qa.lock"
LAST_RESTORE_FILE = "qa.last_restore"
HEARTBEAT_FILE = "heartbeat.txt"
HEARTBEAT_STALE_SECONDS = 120.0

_PLACEHOLDER_RE = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)")
_QA_FAILED_RE = re.compile(r"qa:\s+\S+\s+failed:\s*([^\r\n]+)")
# a refusal (M.qa.load found no save at the path, so EOP's loadGame never ran) is a failed load too
_LOAD_FAILED_RE = re.compile(r"qa:\s+load\s+(?:failed|refused):\s*([^\r\n]+)")
_LOAD_OK_RE = re.compile(r"qa:\s+load\s+ok:\s*([^\r\n]+)")
# the bridge logs "bridge loaded campaign at turn N" on every map load (loadGame writes no reload
# marker, so "bridge reloaded" alone would never come)
_RELOAD_TURN_RE = re.compile(r"bridge (?:reloaded|loaded campaign) at turn (\d+)")
# The main menu runs a turn-0 campaign behind it, and its map load logs "turn 0" too: only a later
# turn is the campaign (live 10-30 19:09:16, after a relaunch, the restore took the menu's line for the
# campaign; its load, sent from the menu, crashed the game on the loading screen. Continue Campaign
# logged the real turn after it: 19:13:59 turn 0, 19:14:35 turn 43).
CAMPAIGN_LINE = "bridge loaded campaign at turn N (N > 0)"


def _campaign_turn(text: str) -> int | None:
    """The turn of the first campaign map load in `text`, skipping the main menu's turn 0."""
    for m in _RELOAD_TURN_RE.finditer(text):
        if int(m.group(1)) > 0:
            return int(m.group(1))
    return None


# how far back the park looks in the bridge log for the newest campaign load (a turn's logs fit)
_CAMPAIGN_TAIL_BYTES = 8 * 1024 * 1024


_LOG_STAMP_RE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) ")


def _newest_campaign_load(log_path: Path, tail_bytes: int = _CAMPAIGN_TAIL_BYTES) -> tuple[int, float | None] | None:
    """(turn, epoch) of the newest campaign map load in the tail of the bridge log, skipping turn 0.
    The epoch is the line's local-time stamp, None if the line has none."""
    try:
        with Path(log_path).open("rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - tail_bytes))
            text = f.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    for line in reversed(text.splitlines()):
        m = _RELOAD_TURN_RE.search(line)
        if m and int(m.group(1)) > 0:
            stamp = _LOG_STAMP_RE.match(line)
            when = None
            if stamp:
                try:
                    when = _dt.datetime.strptime(stamp.group(1), "%Y-%m-%d %H:%M:%S").timestamp()
                except ValueError:
                    pass
            return int(m.group(1)), when
    return None


def _newest_campaign_turn(log_path: Path, tail_bytes: int = _CAMPAIGN_TAIL_BYTES) -> int | None:
    """The turn of the newest campaign map load in the tail of the bridge log, skipping turn 0."""
    load = _newest_campaign_load(log_path, tail_bytes)
    return load[0] if load else None
# what changes the game during a run: a setup helper that worked, or a turn that ended
_QA_HELPER_OK_RE = re.compile(r"qa:\s+(?!load\s)\S+\s+ok:")
_TURN_ENDED_RE = re.compile(r"autoplay: ending turn")

# A live bridge logs at least a heartbeat a minute while it waits on seats ("autoplay: turn N,
# waiting for ..."). A game whose process is alive but whose bridge log hasn't grown for this long is
# hung (live 10-30 18:34: the papal election results scroll froze the game with medieval2.exe alive;
# "process alive" read as "game working", and nothing relaunched it). crash_watch.sh uses the same
# idea with 480 s for the real campaign; the QA bench waits on its own game, so it gives up sooner.
HANG_SECONDS = 240.0
# The bridge holds End Turn while an offer waits on the ruler, up to K.DECISION_HOLD_MAX seconds
# (lua/parley_bridge.lua: DECIDE_WAIT 540 + 30; #288). The QA turn wait must outlast that hold, or a
# held turn fails its case as "turn stuck" (live 10-30 23:06). A test keeps this in step with the Lua.
BRIDGE_DECISION_HOLD_MAX = 570.0
TURN_TIMEOUT = BRIDGE_DECISION_HOLD_MAX + 30.0
# relaunch_game.sh returns once the bridge logged the campaign's map load (its --clicks fallback
# returns after the Continue Campaign click, and the map loads after that)
RELAUNCH_TIMEOUT = 300.0
_LOG_TAIL_BYTES = 4096


class QARunError(RuntimeError):
    """Raised when a QA bench run refuses to start or aborts."""

    def __init__(
        self,
        message: str,
        *,
        report_path: Path | None = None,
        results: list[CaseResult] | None = None,
    ) -> None:
        super().__init__(message)
        self.report_path = report_path
        self.results = results


class CaseResult(BaseModel):
    name: str
    # "skipped": not run at all (a turn case in a `--kind instant` run); never a failure
    outcome: Literal["pass", "fail", "inconclusive", "skipped"]
    turns: int
    evidence: str
    seconds: float | None = None  # the case's wall time, set by run_suite
    # the bench load before the case (load call to "bridge loaded campaign"; not in `seconds`), and
    # the wait after it until the game was idle (_await_ready); None when no load came before it
    reload_seconds: float | None = None
    ready_seconds: float | None = None


class _GameDown(QARunError):
    """The game crashed or hung during a case: the case fails with this as its evidence and the run
    goes straight to the restore."""

    def __init__(self, evidence: str, *, turns: int = 0) -> None:
        super().__init__(evidence)
        self.evidence = evidence
        self.turns = turns


def _clock(ts: float) -> str:
    return _dt.datetime.fromtimestamp(ts).strftime("%H:%M:%S")


def _last_log_line(log_path: Path) -> str:
    try:
        with Path(log_path).open("rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - _LOG_TAIL_BYTES))
            data = f.read()
    except OSError:
        return ""
    lines = [ln.strip() for ln in data.decode("utf-8", errors="replace").splitlines() if ln.strip()]
    return lines[-1][:150] if lines else ""


_TURN_TAIL_BYTES = 256 * 1024


def _last_turn_line(log_path: Path) -> str:
    """The bridge's newest `autoplay:` line (what it says about the turn: waiting, ending, stuck),
    else its last line. Character events can flood the tail, so this reads further back."""
    try:
        with Path(log_path).open("rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - _TURN_TAIL_BYTES))
            data = f.read()
    except OSError:
        return ""
    lines = [ln.strip() for ln in data.decode("utf-8", errors="replace").splitlines() if ln.strip()]
    turn_lines = [ln for ln in lines if " autoplay: " in ln]
    return (turn_lines or lines or [""])[-1][:200]


def game_trouble(
    is_game_running: Callable[[], bool],
    log_path: Path,
    *,
    hang_seconds: float | None = None,
    now: Callable[[], float] = time.time,
    crash_dialog: Callable[[], bool] | None = None,
    eop_error_box: Callable[[], str | None] | None = None,
    answers: Callable[[], bool] | None = None,
) -> str | None:
    """'game crashed at <time>: <last log line>' when medieval2.exe is gone, EOP's modal ERROR box
    is up (`eop_error_box`, scripts/eop_error_box.sh: its title, or None) or Wine's crash dialog is
    up (`crash_dialog`, scripts/crash_dialog.sh), 'game hung at <time> ...' when it is alive but
    the bridge log hasn't grown for `hang_seconds` (HANG_SECONDS by default) and it doesn't
    `answers` a question (a held turn logs nothing), else None. No log at all proves nothing, so it
    is never read as a hang."""
    limit = HANG_SECONDS if hang_seconds is None else float(hang_seconds)
    log_path = Path(log_path)
    if not is_game_running():
        return f"game crashed at {_clock(now())} (medieval2.exe not running): {_last_log_line(log_path) or 'no bridge log'}"
    # live 10-31: "Cannot create M2TWEOP save file. 2" froze the game; the bridge answered nothing
    box = eop_error_box() if eop_error_box is not None else None
    if box:
        return f"game crashed at {_clock(now())} (EOP error box: {box}): {_last_log_line(log_path) or 'no bridge log'}"
    # live 10-30 20:11: the dialog keeps medieval2.exe alive, and the log was seconds old
    if crash_dialog is not None and crash_dialog():
        return f"game crashed at {_clock(now())} (crash dialog up): {_last_log_line(log_path) or 'no bridge log'}"
    try:
        mtime = log_path.stat().st_mtime
    except OSError:
        return None
    silent = now() - mtime
    if silent < limit:
        return None
    if answers is not None and answers():
        return None
    return (
        f"game hung at {_clock(mtime)} (medieval2.exe alive, bridge log silent {int(silent)} s): "
        f"{_last_log_line(log_path)}"
    )


def _await_trouble(
    trouble_fn: Callable[[], str | None],
    log_path: Path,
    since_size: int,
    *,
    hang_seconds: float | None = None,
    poll_interval: float = 0.5,
) -> str | None:
    """After the bridge failed to answer: wait until the detector says crashed/hung, or the log grows
    (the bridge is alive). A wait no longer than the hang threshold (a 30 s control call, the
    TURN_TIMEOUT turn wait) can't tell on its own; the silence only grows, so this ends within `hang_seconds`."""
    limit = HANG_SECONDS if hang_seconds is None else float(hang_seconds)
    deadline = time.monotonic() + limit + 5.0
    while True:
        trouble = trouble_fn()
        if trouble is not None:
            return trouble
        if _log_size(Path(log_path)) != since_size:
            return None
        if time.monotonic() >= deadline:
            return None
        time.sleep(poll_interval)


def _relaunch_and_wait(
    relaunch_fn: Callable[[], None],
    log_path: Path,
    *,
    timeout: float,
    poll_interval: float,
) -> None:
    """Relaunch the game (relaunch_game.sh kills a hung one and loads the kept save) and wait
    for the bridge to log the campaign map load, so the kept save's load goes to a working bridge.
    The main menu's turn-0 map is not the campaign: a load sent from the menu crashes the game."""
    start = _log_size(log_path)
    relaunch_fn()
    deadline = time.monotonic() + timeout
    while True:
        if _log_size(log_path) < start:  # the log started over: read all of it
            start = 0
        if _campaign_turn(_read_log_since(log_path, start)) is not None:
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise QARunError(
                f"relaunched the game, but no '{CAMPAIGN_LINE}' in {log_path} within {timeout}s"
            )
        time.sleep(min(poll_interval, remaining))


def _adjacent_tile(x: int, y: int) -> tuple[int, int]:
    tx = x - 1 if x > 0 else x + 1
    ty = y - 1 if y > 0 else y + 1
    return tx, ty


def pick_targets(state: dict) -> dict[str, str | int]:
    """Pick live targets from a faction's newest state.json dict."""
    if not isinstance(state, dict):
        return {}
    out: dict[str, str | int] = {}

    settlements = [
        s
        for s in (state.get("nearby_settlements") or [])
        if isinstance(s, dict)
        and (s.get("name") or s.get("id"))
        and s.get("x") is not None
        and s.get("y") is not None
    ]
    if settlements:
        nearest_sett = min(
            enumerate(settlements),
            key=lambda iv: (
                iv[1].get("distance") is None,
                float(iv[1]["distance"]) if iv[1].get("distance") is not None else 0.0,
                iv[0],
            ),
        )[1]
        sx, sy = int(nearest_sett["x"]), int(nearest_sett["y"])
        tx, ty = _adjacent_tile(sx, sy)
        out["target_settlement"] = str(nearest_sett.get("name") or nearest_sett.get("id"))
        out["target_settlement_x"] = sx
        out["target_settlement_y"] = sy
        out["target_x"] = tx
        out["target_y"] = ty

    # Characters exactly as the validator lists them: the report ids of foreign armies and agents in
    # sight (orders resolve characters by id, and a leader's name may lead two armies). A fleet stands
    # at sea and an admiral sails with it: nobody can be spawned beside them to reach them over land.
    # An agent standing in a foreign town is preferred: it stays put more often than an army in the
    # field, and the assassin acts the turn after it spawns (live 10-30 18:19: Edmund Canmore's army
    # went into Inverness and out of the sight lists before the order ran). A general in a town is a
    # garrison, never in the sight lists, so no army is preferred that way.
    town_tiles = {(s.get("x"), s.get("y")) for s in settlements}
    char_candidates: list[tuple[bool, bool, float, int, str, int | None, int | None]] = []
    people = [(e, False) for e in state.get("visible_enemies") or [] if isinstance(e, dict) and not e.get("is_fleet")]
    people += [(a, True) for a in state.get("seen_agents") or [] if isinstance(a, dict) and a.get("kind") != "admiral"]
    for idx, (who, is_agent) in enumerate(people):
        cid = who.get("id")
        if not (isinstance(cid, str) and cid.strip()):
            continue
        in_town = is_agent and (bool(who.get("in_settlement")) or (who.get("x"), who.get("y")) in town_tiles)
        dist = who.get("distance")
        char_candidates.append(
            (
                not in_town,
                dist is None,
                float(dist) if dist is not None else 0.0,
                idx,
                cid.strip(),
                who.get("x"),
                who.get("y"),
            )
        )

    if char_candidates:
        best = min(char_candidates, key=lambda c: c[:4])
        out["target_character"] = best[4]
        if best[5] is not None and best[6] is not None:
            # the character's own tile, so a case can spawn its agent beside him (M.qa.free_tile)
            out["target_character_x"] = int(best[5])
            out["target_character_y"] = int(best[6])
            if "target_x" not in out:
                tx, ty = _adjacent_tile(int(best[5]), int(best[6]))
                out["target_x"] = tx
                out["target_y"] = ty

    out.update(pick_home(state))
    out.update(pick_garrison_town(state))
    out.update(pick_hostile(state))
    return out


# a garrison takes 20 units; the field cases walk or spawn one more in
_HOME_MAX_UNITS = 18
_TILE_RE = re.compile(r"\s*(-?\d+),(-?\d+)\s*")


def tile_binds(name: str, value: str) -> dict[str, int]:
    """A bound tile ("x,y") also binds `<name>_x` and `<name>_y`, as numbers (orders need them)."""
    m = _TILE_RE.fullmatch(value)
    if not m:
        return {}
    return {f"{name}_x": int(m.group(1)), f"{name}_y": int(m.group(2))}


def pick_home(state: dict) -> dict[str, str | int]:
    """An own town for the field cases, in two strengths.

    `home_settlement` (with its tile): a town an army can withdraw into and be told apart in, first
    in the report with a tile, room in its garrison, no siege, and no general inside (the garrison's
    general is the one found on the town's tile, so a second one would make the case's general
    ambiguous).

    `home_x`/`home_y` alone: the anchor the other cases spawn beside (M.qa.free_tile finds a free land
    tile near it), so any own town with a tile will do; one not under siege is preferred. Live 10-30
    23:10-23:30: Rufus led London's garrison (garrison_general_leaves never got him out) and Henry
    Nottingham's 18-19 units, so the strict pick found nothing and eight cases failed at setup."""
    if not isinstance(state, dict):
        return {}
    led = {
        a.get("in_settlement")
        for a in state.get("armies") or []
        if isinstance(a, dict) and a.get("in_settlement") and a.get("leader")
    }
    towns = [
        s
        for s in state.get("settlements") or []
        if isinstance(s, dict) and s.get("id") and s.get("x") is not None and s.get("y") is not None
    ]
    for s in towns:
        if s.get("siege") or s["id"] in led or int(s.get("garrison_units") or 0) > _HOME_MAX_UNITS:
            continue
        return {"home_settlement": str(s["id"]), "home_x": int(s["x"]), "home_y": int(s["y"])}
    anchor = next((s for s in towns if not s.get("siege")), None) or next(iter(towns), None)
    if anchor is None:
        return {}
    return {"home_x": int(anchor["x"]), "home_y": int(anchor["y"])}


def home_refusals(state: dict) -> str:
    """Why no own town qualified as `home_settlement`, town by town (for a case's setup evidence)."""
    if not isinstance(state, dict):
        return "no report"
    leaders = {
        a.get("in_settlement"): a.get("leader")
        for a in state.get("armies") or []
        if isinstance(a, dict) and a.get("in_settlement") and a.get("leader")
    }
    why: list[str] = []
    for s in state.get("settlements") or []:
        if not isinstance(s, dict) or not s.get("id"):
            continue
        sid = s["id"]
        if s.get("x") is None or s.get("y") is None:
            why.append(f"{sid}: no tile")
        elif s.get("siege"):
            why.append(f"{sid}: under siege")
        elif sid in leaders:
            why.append(f"{sid}: {leaders[sid]} leads its garrison")
        elif int(s.get("garrison_units") or 0) > _HOME_MAX_UNITS:
            why.append(f"{sid}: garrison full ({int(s['garrison_units'])} units)")
    return "; ".join(why) or "no own towns"


def pick_garrison_town(state: dict) -> dict[str, str | int]:
    """An own town for the garrison case, not under siege: first one whose garrison a general
    already leads (the live case: Robert in Paris), else one with room where the case spawns one
    (M.qa.garrison). Live 10-30 19:51: every English town had a general and pick_home found none."""
    if not isinstance(state, dict):
        return {}
    led = {
        a.get("in_settlement")
        for a in state.get("armies") or []
        if isinstance(a, dict) and a.get("in_settlement") and a.get("leader")
    }
    towns = [
        s
        for s in state.get("settlements") or []
        if isinstance(s, dict) and s.get("id") and s.get("x") is not None and s.get("y") is not None
        and not s.get("siege")
    ]
    pick = next((s for s in towns if s["id"] in led), None) or next(
        (s for s in towns if int(s.get("garrison_units") or 0) <= _HOME_MAX_UNITS), None
    )
    if pick is None:
        return {}
    return {"garrison_town": str(pick["id"]), "garrison_town_x": int(pick["x"]), "garrison_town_y": int(pick["y"])}


def pick_hostile(state: dict) -> dict[str, str | int]:
    """The nearest foreign town in sight that an army may besiege and can walk to: a rebel one, or
    one of a faction at war (march_on refuses a town at peace), not marked across the sea."""
    if not isinstance(state, dict):
        return {}
    at_war = {
        f.get("id")
        for f in state.get("factions") or []
        if isinstance(f, dict) and f.get("stance") == "war"
    }
    best: tuple[float, int, dict] | None = None
    for i, s in enumerate(state.get("nearby_settlements") or []):
        if not isinstance(s, dict) or not s.get("id") or s.get("x") is None or s.get("y") is None:
            continue
        if s.get("by_land") is False or not (s.get("faction") == "slave" or s.get("faction") in at_war):
            continue
        dist = float(s["distance"]) if s.get("distance") is not None else float("inf")
        if best is None or (dist, i) < (best[0], best[1]):
            best = (dist, i, s)
    if best is None:
        return {}
    s = best[2]
    return {"hostile_settlement": str(s["id"]), "hostile_x": int(s["x"]), "hostile_y": int(s["y"])}


def _substitute_str(value: str, targets: dict[str, str | int]) -> str:
    if not targets:
        return value
    if value.startswith("$") and value[1:] in targets:
        return str(targets[value[1:]])
    out = value
    for key in sorted(targets, key=len, reverse=True):
        out = out.replace(f"${key}", str(targets[key]))
    return out


def _substitute_value(value: object, targets: dict[str, str | int]) -> object:
    if isinstance(value, str):
        if value.startswith("$") and value[1:] in targets:
            return targets[value[1:]]
        return _substitute_str(value, targets)
    if isinstance(value, dict):
        return {k: _substitute_value(v, targets) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute_value(x, targets) for x in value]
    return value


def _required_placeholders(case: Case) -> set[str]:
    needed: set[str] = {k for k in case.targets if k.startswith("target_")}
    for step in [*case.setup, *case.act]:
        needed.update(_PLACEHOLDER_RE.findall(_setup_lua(step)))
        if isinstance(step, SetupStep) and step.require:
            needed.update(_PLACEHOLDER_RE.findall(step.require))
    for order_list in case.orders.values():
        for order in order_list:
            for val in order.values():
                if isinstance(val, str):
                    needed.update(_PLACEHOLDER_RE.findall(val))
    expects = list(case.expect)
    while expects:
        exp = expects.pop()
        expects.extend(exp.any_of or [])
        for val in (exp.log, exp.state, exp.equals, exp.at_least, exp.lua, exp.match, exp.no_match, exp.below,
                    exp.after):
            if isinstance(val, str):
                needed.update(_PLACEHOLDER_RE.findall(val))
    # filled by the script seat when the order is written, from that turn's report
    needed.discard(NEAREST_CHARACTER_TO)
    return needed


def _setup_lua(step: str | SetupStep) -> str:
    return step.lua if isinstance(step, SetupStep) else step


def _effective_targets(case: Case, live_targets: dict[str, str | int]) -> tuple[dict[str, str | int], list[str]]:
    base = {k: v for k, v in case.targets.items() if not k.startswith("target_")}
    merged = {**base, **live_targets}
    needed = _required_placeholders(case) - case.binds  # bound by the case's own setup
    missing = sorted(k for k in needed if k not in merged)
    return merged, missing


def build_script_plan(
    cases: list[Case],
    current_turn: int,
    targets: dict[str, str | int] | None = None,
) -> dict[str, list[dict]]:
    """Build a ScriptSeat plan JSON dict mapping absolute turns to order lists."""
    plan: dict[str, list[dict]] = {}
    offset = current_turn
    live = targets or {}
    for case in cases:
        if not case.orders:
            continue
        if case.binds:
            # orders naming a setup result are planned by _run_case once setup has bound it
            offset += max(int(k) for k in case.orders)
            continue
        merged, _ = _effective_targets(case, live)
        for rel_turn, orders in sorted(case.orders.items()):
            abs_turn = offset + int(rel_turn)
            rendered = [_substitute_value(o, merged) for o in orders]
            plan[str(abs_turn)] = rendered  # type: ignore[assignment]
        offset += max(int(k) for k in case.orders)
    return plan


# the QA seat's treasury target: the bridge tops up to it at turn start (a case reads it as $playtest_funds)
QA_PLAYTEST_FUNDS = 50000


def write_qa_config(
    real_config_path: Path,
    suite: Suite,
    plan_path: Path,
    out_path: Path | None = None,
    *,
    quiet: bool = False,
    thaw: list[str] | tuple[str, ...] = (),
) -> Path:
    """Write games/local/qa-<suite>.toml for the QA run. `quiet` freezes every AI faction's game AI
    (the bench's quiet world) but those in `thaw` (the running case's `needs`)."""
    real_cfg = load_config(Path(real_config_path))
    dest = Path(out_path) if out_path is not None else Path(real_config_path).parent / f"qa-{suite.name}.toml"
    dest.parent.mkdir(parents=True, exist_ok=True)
    game_data = {
        "game_id": f"qa-{suite.name}",
        "turn_root": str(real_cfg.turn_root),
        "save_dir": str(real_cfg.save_dir),
        "mod_save_dir": str(real_cfg.mod_save_dir),
        "seat_timeout": real_cfg.seat_timeout,
        # the papal crash experiment (field suite turns 59/62): our handler stays out of papal scrolls
        "autoplay": {"wait": 60, "papal_hands_off": True},
        "seats": {
            suite.faction: {
                "brain": f"script:{Path(plan_path).resolve()}",
                "persona": "QA bench scripted ruler.",
                "control": "full",
                "playtest_funds": True,
                "playtest_funds_amount": QA_PLAYTEST_FUNDS,
                **({"steward": True} if getattr(suite, "steward", False) else {}),
            }
        },
    }
    if quiet:
        game_data["freeze_others"] = True
        game_data["thaw"] = sorted(set(thaw) - {suite.faction})
    text = to_toml(game_data, f"# QA bench game for suite '{suite.name}'.")
    dest.write_text(text, encoding="utf-8")
    tomllib.loads(text)
    return dest


def _secs(s: float) -> str:
    return f"{s:.1f} s" if s < 120 else f"{int(s // 60)} min {int(s % 60)} s"


def _reload_cell(r: CaseResult) -> str:
    """The bench load before the case: "4.1 s", "75.0 s slow load", "+ ready 12.0 s" when the game
    took that long after it to go idle; empty when no load came before the case."""
    if r.reload_seconds is None:
        return ""
    cell = _secs(r.reload_seconds)
    if r.reload_seconds > SLOW_LOAD_SECONDS:
        cell += " slow load"
    if r.ready_seconds is not None and r.ready_seconds >= 1.0:
        cell += f" + ready {_secs(r.ready_seconds)}"
    return cell


def format_report(
    suite_name: str,
    results: list[CaseResult],
    total_seconds: float | None = None,
    reloads: list[float] | None = None,
) -> str:
    """Render a markdown report table for a QA run: each case's wall time, and the run's total
    (park, smoke and cases; the restore after it is not in it) when given. `reloads`: the seconds
    each bench reload for a case's isolation took (not in the cases' times)."""
    lines = [
        f"# QA Report: {suite_name}",
        "",
        "| case | outcome | turns | evidence | time | reload |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    slow: list[str] = []
    for r in results:
        ev = r.evidence.replace("\n", " ").replace("|", "\\|")
        t = _secs(r.seconds) if r.seconds is not None else ""
        lines.append(f"| {r.name} | {r.outcome} | {r.turns} | {ev} | {t} | {_reload_cell(r)} |")
        if r.reload_seconds is not None and r.reload_seconds > SLOW_LOAD_SECONDS:
            slow.append(f"{r.name} ({_secs(r.reload_seconds)})")
    if slow:
        # the case run before a slow load is the likely one that left the game busy (AI turns playing out)
        lines += ["", f"Slow loads (over {SLOW_LOAD_SECONDS:g} s; the case before each likely left the game "
                      f"busy): {', '.join(slow)}"]
    if total_seconds is not None:
        lines += ["", f"Total: {_secs(total_seconds)} for {len(results)} case(s) (restore not included)"]
    if reloads:
        lines += ["", f"Bench reloads (case isolation): {len(reloads)}, {_secs(sum(reloads))} in all "
                      f"({sum(reloads) / len(reloads):.1f} s each)"]
    return "\n".join(lines) + "\n"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def newest_real_save(save_dir: Path) -> Path | None:
    """The newest save the game wrote itself: never a keep copy, never the bench save."""
    saves = sorted(
        (
            p
            for p in Path(save_dir).glob("*.sav")
            if not p.name.startswith("parley_keep_") and not p.name.startswith(BENCH_SAVE_STEM)
        ),
        key=lambda p: p.stat().st_mtime,
    )
    return saves[-1] if saves else None


# The bench's fixed start: one quiet early-turn save every suite loads before its cases, never the
# live campaign (10-31 05:29 a Pope died mid-smoke on the live world and the game crashed). It sits
# in the mod's save folder beside the keep saves; its record (turn, faction, sha256) beside it.
BENCH_SAVE_STEM = "parley_bench"
BENCH_SAVE_NAME = f"{BENCH_SAVE_STEM}.sav"
BENCH_RECORD_NAME = f"{BENCH_SAVE_STEM}.json"
BENCH_RECIPE = "just qa-bench-save"
BENCH_SAVE_GAME_ID = "qa-bench-save"  # the bridge's game while the bench save is being made


class BenchSave(BaseModel):
    path: Path
    rel: str  # as M.qa.load takes it: relative to the game folder
    turn: int
    faction: str
    sha256: str


def bench_save_paths(real_cfg: GameConfig) -> tuple[Path, Path]:
    d = Path(real_cfg.mod_save_dir)
    return d / BENCH_SAVE_NAME, d / BENCH_RECORD_NAME


def load_bench_save(real_cfg: GameConfig) -> BenchSave:
    """The recorded bench save, checked against its record; QARunError (naming the recipe that
    makes it) when it is missing, unrecorded, changed since it was recorded, or on turn 0 (the
    main menu's campaign logs turn 0 too, so a turn-0 load can't be told from it)."""
    save, record = bench_save_paths(real_cfg)
    how = f"make it with `{BENCH_RECIPE} start`, then `{BENCH_RECIPE} record` (docs/superpowers/specs/2026-10-30-test-bench-design.md)"
    if not save.exists():
        raise QARunError(f"no bench save at {save}; {how}")
    try:
        data = json.loads(record.read_text(encoding="utf-8"))
        turn, faction, digest = int(data["turn"]), str(data["faction"]), str(data["sha256"])
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise QARunError(f"bench save {save.name} has no valid record at {record} ({e}); {how}") from e
    if turn < 1:
        raise QARunError(f"bench save {save.name} is on turn {turn}; it must be turn 1 or later; {how}")
    if _sha256(save) != digest:
        raise QARunError(f"bench save {save.name} changed since it was recorded (sha256 differs); {how}")
    return BenchSave(path=save, rel=_rel_save_path(real_cfg, BENCH_SAVE_NAME), turn=turn,
                     faction=faction, sha256=digest)


def keep_save_path(save_dir: Path, game_id: str) -> Path:
    return Path(save_dir) / f"parley_keep_{game_id}.sav"


def _read_heartbeat(turn_root: Path) -> tuple[int, float] | None:
    hb_path = Path(turn_root) / HEARTBEAT_FILE
    try:
        st = hb_path.stat()
        raw = hb_path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    if not raw.startswith("turn="):
        return None
    turn_str = raw.removeprefix("turn=").strip()
    if not turn_str.isdigit():
        return None
    return int(turn_str), st.st_mtime


def _rel_keep_save_path(real_cfg: GameConfig) -> str:
    return _rel_save_path(real_cfg, f"parley_keep_{real_cfg.game_id}.sav")


def _rel_save_path(real_cfg: GameConfig, name: str) -> str:
    """A save in mod_save_dir, as M.qa.load takes it: relative to the game folder."""
    game_dir = Path(real_cfg.turn_root).resolve().parent
    mod_save_dir = Path(real_cfg.mod_save_dir).resolve()
    try:
        rel_dir = mod_save_dir.relative_to(game_dir)
    except ValueError as e:
        raise QARunError(
            f"mod_save_dir {real_cfg.mod_save_dir} is not under game dir {game_dir}"
        ) from e
    if rel_dir == Path("."):
        raise QARunError(
            f"mod_save_dir {real_cfg.mod_save_dir} is not under game dir {game_dir}"
        )
    return (rel_dir / name).as_posix()


def _load_line(save: Path, rel: str) -> str:
    """The control line that loads `rel` (M.qa.load: relative to the game folder), whose file on this
    host is `save`. QARunError when there is no such file: EOP's loadGame on a missing save puts up a
    modal "ERROR: Cannot create M2TWEOP save file. 2" box that freezes the game until it is closed,
    and closing it ends the game (live 10-31: a load of the keep save the restore had renamed).
    Called right before each load goes out, so a save renamed meanwhile is caught."""
    if not Path(save).is_file():
        raise QARunError(f"qa: load refused: no save at {rel} ({save})")
    return f'return M.qa.load("{rel}")'


def _validate_keep_candidate(
    newest: Path,
    cand_mtime: float,
    game_id: str,
    turn_root: Path | None,
) -> int | None:
    if turn_root is None:
        return None
    last_restore_path = Path(turn_root) / LAST_RESTORE_FILE
    if last_restore_path.exists():
        try:
            last_restore_data = json.loads(last_restore_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise QARunError(
                f"invalid {last_restore_path}; wait for one real turn to autosave, then retry"
            ) from e
        rec_mtime = (
            last_restore_data.get("newest_save_mtime")
            if isinstance(last_restore_data, dict)
            else None
        )
        if not isinstance(rec_mtime, (int, float)) or not (cand_mtime > float(rec_mtime)):
            raise QARunError(
                f"refusing QA-tainted save {newest.name} (mtime {cand_mtime} <= {LAST_RESTORE_FILE} {rec_mtime}); "
                f"wait for one real turn to autosave, then retry"
            )
    for qa_dir in sorted(Path(turn_root).glob("qa-*/turn-*")):
        if not qa_dir.is_dir():
            continue
        if qa_dir.stat().st_mtime > cand_mtime:
            raise QARunError(
                f"refusing QA-tainted save {newest.name} ({qa_dir} is newer); "
                f"wait for one real turn, then retry"
            )
    hb = _read_heartbeat(Path(turn_root))
    if hb is None:
        raise QARunError(
            f"no valid {HEARTBEAT_FILE} found in {turn_root}; "
            f"wait for one real turn, then retry"
        )
    real_turn, hb_mtime = hb
    # An autosave is written at the start of the player's turn, while heartbeat.txt
    # is updated at every seat's on_turn_start; allow up to 120s of turn progression.
    if cand_mtime < hb_mtime - HEARTBEAT_STALE_SECONDS:
        raise QARunError(
            f"refusing stale save {newest.name} (older than {HEARTBEAT_FILE} by more than 120s); "
            f"wait for one real turn, then retry"
        )
    return real_turn


def _restored_keep_if_unmoved(save_dir: Path, game_id: str, turn_root: Path | None) -> Path | None:
    """The save the last restore loaded, when the real campaign provably hasn't moved since (live
    10-31 08:10: with the real campaign deliberately paused no real turn autosaves, so every park
    refused the newest save as QA-tainted). All of these must hold, else None:
      - qa.last_restore names the save it loaded (an aborted restore names none), and that file is
        unchanged (its recorded sha256; a record from before the name was kept: the newest
        non-aborted parley_keep_<game>.restored-*.sav whose mtime is the record's newest_save_mtime,
        i.e. the keep was the newest real save, copied with its mtime);
      - no real save is newer than the record (a newer one is a real turn: it is used as before);
      - heartbeat.txt, written at every turn start, is valid and not touched since the restore;
      - no QA game's turn folder is newer than the restore."""
    if turn_root is None:
        return None
    turn_root = Path(turn_root)
    try:
        data = json.loads((turn_root / LAST_RESTORE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    rec_mtime = data.get("newest_save_mtime")
    if not isinstance(rec_mtime, (int, float)) or isinstance(rec_mtime, bool):
        return None
    at_epoch = data.get("at_epoch")
    if not isinstance(at_epoch, (int, float)) or isinstance(at_epoch, bool):
        try:
            at_epoch = _dt.datetime.fromisoformat(str(data.get("at"))).timestamp()
        except ValueError:
            return None
    newest = newest_real_save(save_dir)
    if newest is not None and newest.stat().st_mtime > float(rec_mtime):
        return None
    if "restored_save" in data:
        name = data.get("restored_save")
        digest = data.get("restored_sha256")
        if not isinstance(name, str) or not isinstance(digest, str) or Path(name).name != name:
            return None
        restored = Path(save_dir) / name
        if not restored.is_file() or _sha256(restored) != digest:
            return None
    else:
        candidates = sorted(
            (
                p
                for p in Path(save_dir).glob(f"parley_keep_{game_id}.restored-*.sav")
                if not p.name.endswith("-aborted.sav")
            ),
            key=lambda p: (p.stat().st_mtime, p.name),
        )
        if not candidates or candidates[-1].stat().st_mtime != float(rec_mtime):
            return None
        restored = candidates[-1]
    hb = _read_heartbeat(turn_root)
    if hb is None or hb[1] > float(at_epoch):
        return None
    for qa_dir in turn_root.glob("qa-*/turn-*"):
        if qa_dir.is_dir() and qa_dir.stat().st_mtime > float(at_epoch):
            return None
    return restored


def _preflight_keep_save(save_dir: Path, game_id: str, turn_root: Path | None = None) -> int | None:
    newest = newest_real_save(save_dir)
    try:
        if newest is None:
            raise QARunError(f"no real save found in {save_dir}; wait for one real turn, then retry")
        cand_mtime = newest.stat().st_mtime
        return _validate_keep_candidate(newest, cand_mtime, game_id, turn_root)
    except QARunError:
        if _restored_keep_if_unmoved(save_dir, game_id, turn_root) is None:
            raise
        hb = _read_heartbeat(Path(turn_root)) if turn_root is not None else None
        return hb[0] if hb is not None else None


def _reuse_restored_keep(save_dir: Path, game_id: str, restored: Path) -> Path:
    """Copy the save the last restore loaded to the keep save, checked byte for byte."""
    keep = keep_save_path(save_dir, game_id)
    tmp_keep = Path(save_dir) / f".parley_keep_{game_id}.sav.tmp"
    try:
        shutil.copy2(restored, tmp_keep)
        if _sha256(tmp_keep) != _sha256(restored):
            raise QARunError(f"keep copy of {restored.name} does not match it; retry")
        os.replace(tmp_keep, keep)
    except BaseException:
        tmp_keep.unlink(missing_ok=True)
        raise
    print(f"real campaign hasn't moved since the last restore; keeping {restored.name} as is (as {keep.name})")
    return keep


def ensure_keep_save(save_dir: Path, game_id: str, turn_root: Path | None = None) -> Path:
    newest = newest_real_save(save_dir)
    if newest is None:
        restored = _restored_keep_if_unmoved(save_dir, game_id, turn_root)
        if restored is not None:
            return _reuse_restored_keep(save_dir, game_id, restored)
        raise QARunError(f"no real save found in {save_dir}; wait for one real turn, then retry")
    try:
        _validate_keep_candidate(newest, newest.stat().st_mtime, game_id, turn_root)
    except QARunError:
        restored = _restored_keep_if_unmoved(save_dir, game_id, turn_root)
        if restored is None:
            raise
        return _reuse_restored_keep(save_dir, game_id, restored)
    keep = keep_save_path(save_dir, game_id)
    tmp_keep = Path(save_dir) / f".parley_keep_{game_id}.sav.tmp"
    shutil.copy2(newest, tmp_keep)
    try:
        cand_mtime = newest.stat().st_mtime
        _validate_keep_candidate(newest, cand_mtime, game_id, turn_root)

        latest = newest_real_save(save_dir)
        if latest is None or not tmp_keep.exists():
            raise QARunError(f"keep save {keep} missing after copy")
        if tmp_keep.stat().st_size != latest.stat().st_size or _sha256(tmp_keep) != _sha256(latest):
            raise QARunError(
                f"stale keep copy: {keep.name} does not match newest save {latest.name} in {save_dir}; "
                f"wait for one real turn, then retry"
            )
        os.replace(tmp_keep, keep)
    except BaseException:
        tmp_keep.unlink(missing_ok=True)
        raise
    return keep


# an earlier run's QA game folders go here (outside the `qa-*` games), the newest few kept for diagnosis
QA_ARCHIVE_DIR = "qa-archive"
QA_ARCHIVE_KEEP = 3


def archive_qa_game(turn_root: Path, game_id: str, now_fn: Callable[[], _dt.datetime]) -> Path | None:
    """Move an earlier run's folders of the QA game out of the bridge's way, before it plays that game.

    The QA game's turn folders are reused run to run, and the bridge applies whatever orders.json it
    finds at a turn start, then ends the turn when nobody is pending (live 10-30 18:55:50: with the QA
    loop stopped for the assassin's setup, the bridge applied the 18:15 run's turn-44 orders, "unknown
    agent 'Toby of Eynsham'", and ended turn 45 while setup was still spawning)."""
    src = Path(turn_root) / game_id
    if not src.is_dir():
        return None
    archive = Path(turn_root) / QA_ARCHIVE_DIR
    archive.mkdir(parents=True, exist_ok=True)
    stamp = now_fn().strftime("%Y%m%d-%H%M%S")
    dest = archive / f"{game_id}-{stamp}"
    n = 1
    while dest.exists():
        dest = archive / f"{game_id}-{stamp}-{n}"
        n += 1
    os.replace(src, dest)
    kept = sorted(p for p in archive.glob(f"{game_id}-*") if p.is_dir())
    for old in kept[:-QA_ARCHIVE_KEEP]:
        shutil.rmtree(old, ignore_errors=True)
    return dest


def _read_log_since(log_path: Path, offset: int) -> str:
    try:
        with log_path.open("rb") as f:
            f.seek(offset)
            return f.read().decode("utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def _latest_state_for_faction(
    turn_root: Path,
    game_ids: list[str],
    faction: str,
) -> tuple[int, dict, Path] | None:
    candidates: list[tuple[float, int, Path]] = []
    for gid in game_ids:
        game_dir = Path(turn_root) / gid
        if not game_dir.is_dir():
            continue
        for state_file in game_dir.glob(f"turn-*/{faction}/state.json"):
            turn_str = state_file.parent.parent.name.removeprefix("turn-")
            if not turn_str.isdigit():
                continue
            try:
                mtime = state_file.stat().st_mtime
            except FileNotFoundError:
                continue
            candidates.append((mtime, int(turn_str), state_file))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]))
    _, turn_num, best_path = candidates[-1]
    data = json.loads(best_path.read_bytes().decode("utf-8", errors="replace"))
    return int(data.get("turn", turn_num)), data, best_path


def _state_for_turn(turn_root: Path, game_id: str, turn: int, faction: str) -> dict | None:
    """The faction's report for exactly this turn of this game, or None."""
    path = Path(turn_root) / game_id / f"turn-{turn:04d}" / faction / "state.json"
    try:
        data = json.loads(path.read_bytes().decode("utf-8", errors="replace"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _read_json_list(path: Path) -> list | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, list) else None


# a results.json older than the case's plan (by more than the filesystem's clock granularity) is an
# earlier run's: the QA game's turn folders are reused whenever the bench reloads the same save
_RESULTS_CLOCK_SLACK = 1.0


def _case_results(
    turn_root: Path,
    game_id: str,
    faction: str,
    case_plan: dict[str, list[dict]],
    report_turn: int,
    since: float,
) -> tuple[int | None, list[dict]]:
    """The results of the case's own orders at its latest order turn before `report_turn`, written
    after the case's plan was: results.json entries (their index mapped back through index_map.json)
    plus rejected.json entries, each matched to the case's order at that index by type. Never another
    turn's, so never another case's (live 10-30 18:00: the assassin read the spy's refusal)."""
    turns = sorted((int(k) for k in case_plan if int(k) < report_turn), reverse=True)
    if not turns:
        return None, []
    turn = turns[0]
    # a plan's "say" entries are messages (ScriptSeat): the results number the orders without them
    orders = [o for o in case_plan[str(turn)] if o.get("type") != "say"]
    d = Path(turn_root) / game_id / f"turn-{turn:04d}" / faction
    res_path = d / "results.json"
    try:
        if res_path.stat().st_mtime < since - _RESULTS_CLOCK_SLACK:
            return turn, []
    except OSError:
        return turn, []
    index_map = _read_json_list(d / "index_map.json") or []
    entries: list[tuple[int, dict]] = []
    for r in _read_json_list(res_path) or []:
        if isinstance(r, dict) and isinstance(r.get("index"), int):
            i = r["index"]
            orig = index_map[i] if 0 <= i < len(index_map) and isinstance(index_map[i], int) else i
            entries.append((orig, r))
    for r in _read_json_list(d / "rejected.json") or []:
        if isinstance(r, dict) and isinstance(r.get("index"), int):
            entries.append((r["index"], r))
    own = [
        r for orig, r in sorted(entries, key=lambda e: e[0])
        if 0 <= orig < len(orders) and r.get("type") == orders[orig].get("type")
    ]
    return turn, own


QA_MESSAGES = "qa_messages"


def _case_messages(
    turn_root: Path,
    game_id: str,
    faction: str,
    case_plan: dict[str, list[dict]],
    report_turn: int,
    since: float,
) -> list[dict]:
    """The messages the orchestrator kept and queued (its messages.json, `kept`) for the case's own
    latest order turn before `report_turn`, written after the case's plan was. A turn case reads
    them as the state path `qa_messages`: a `say` delivered to the outbox."""
    turns = sorted((int(k) for k in case_plan if int(k) < report_turn), reverse=True)
    if not turns:
        return []
    path = Path(turn_root) / game_id / f"turn-{turns[0]:04d}" / faction / "messages.json"
    try:
        if path.stat().st_mtime < since - _RESULTS_CLOCK_SLACK:
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    kept = data.get("kept") if isinstance(data, dict) else None
    return [m for m in kept if isinstance(m, dict)] if isinstance(kept, list) else []


def _is_crash_watch_argv(argv: list[str]) -> bool:
    return (
        len(argv) == 2
        and Path(argv[0]).name == "bash"
        and argv[1] in ("scripts/crash_watch.sh", str(REPO_ROOT / "scripts" / "crash_watch.sh"))
    )


def _is_qa_loop_argv(argv: list[str]) -> bool:
    if len(argv) != 5:
        return False
    if not Path(argv[0]).name.startswith("python"):
        return False
    if argv[1:4] != ["-m", "parley", "run"]:
        return False
    cfg_name = Path(argv[4]).name
    return cfg_name.startswith("qa-") and cfg_name.endswith(".toml")


def _is_parley_argv(argv: list[str], command: str) -> bool:
    """`python -m parley <command> <config>`, the Python process itself (not its sh/uv wrappers)."""
    return (
        len(argv) == 5
        and Path(argv[0]).name.startswith("python")
        and argv[1:4] == ["-m", "parley", command]
    )


def _is_real_loop_argv(argv: list[str]) -> bool:
    """A turn loop that isn't a QA bench's (game.sh's `running run`, less the qa-*.toml loops)."""
    return _is_parley_argv(argv, "run") and not _is_qa_loop_argv(argv)


def _is_bot_argv(argv: list[str]) -> bool:
    return _is_parley_argv(argv, "discord")


CRASH_WATCH_UNIT = "parley-crash-watch"  # scripts/crash_watch_unit.sh

# The lock's record of what ran before the park (live 10-31 08:05: run9 was stopped on purpose for
# a no-click sprint, and the restore after `just qa-bench-save record` started its loop again,
# which then clicked popups). The restore brings back exactly this; a lock without it, all three.
RUNNING_BEFORE = "running_before"
RUNNING_KEYS = ("loop", "bot", "crash_watch")


class _ProcessManager:
    def __init__(
        self,
        *,
        proc_root: Path | None = None,
        kill_fn: Callable[[int, int], None] | None = None,
        wait_timeout: float = 5.0,
        run_fn: Callable[..., subprocess.CompletedProcess] | None = None,
    ) -> None:
        self.qa_proc: subprocess.Popen | None = None
        self.proc_root: Path = Path(proc_root) if proc_root is not None else Path("/proc")
        self.kill_fn: Callable[[int, int], None] = kill_fn or os.kill
        self.wait_timeout: float = wait_timeout
        self.run_fn: Callable[..., subprocess.CompletedProcess] = run_fn or subprocess.run

    def _find_pids(self, match_argv: Callable[[list[str]], bool]) -> list[int]:
        if not self.proc_root.is_dir():
            return []
        my_pid = os.getpid()
        pids: list[int] = []
        for entry in sorted(self.proc_root.iterdir(), key=lambda p: p.name):
            if not entry.name.isdigit():
                continue
            pid = int(entry.name)
            if pid == my_pid:
                continue
            try:
                raw = (entry / "cmdline").read_bytes()
            except OSError:
                continue
            if not raw:
                continue
            argv = [part.decode("utf-8", errors="replace") for part in raw.rstrip(b"\x00").split(b"\x00")]
            if match_argv(argv):
                pids.append(pid)
        return pids

    def _stop_by_argv(self, label: str, match_argv: Callable[[list[str]], bool]) -> None:
        pids = self._find_pids(match_argv)
        if not pids:
            return
        for pid in pids:
            try:
                self.kill_fn(pid, signal.SIGTERM)
            except OSError:
                pass
        deadline = time.monotonic() + self.wait_timeout
        while time.monotonic() < deadline:
            if not self._find_pids(match_argv):
                return
            time.sleep(0.02)
        for pid in self._find_pids(match_argv):
            try:
                self.kill_fn(pid, signal.SIGKILL)
            except OSError:
                pass
        kill_deadline = time.monotonic() + min(1.0, self.wait_timeout)
        while time.monotonic() < kill_deadline:
            if not self._find_pids(match_argv):
                return
            time.sleep(0.02)
        remaining = self._find_pids(match_argv)
        if remaining:
            raise QARunError(f"{label} did not stop (pids: {remaining})")

    def stop_orphaned_qa_loops(self) -> None:
        self._stop_by_argv("orphaned QA loop", _is_qa_loop_argv)

    def stop_qa_proc(self) -> None:
        proc = self.qa_proc
        self.qa_proc = None
        if proc is not None and proc.poll() is None:
            try:
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, signal.SIGTERM)
            except OSError:
                proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    pgid = os.getpgid(proc.pid)
                    os.killpg(pgid, signal.SIGKILL)
                except OSError:
                    proc.kill()
        self.stop_orphaned_qa_loops()

    def stop_loop(self) -> None:
        self.stop_qa_proc()
        subprocess.run(
            ["bash", str(REPO_ROOT / "scripts" / "game.sh"), "stop"],
            cwd=str(REPO_ROOT),
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def stop_crash_watch(self) -> None:
        # crash-watch runs as the user unit parley-crash-watch (scripts/crash_watch_unit.sh; live
        # 10-30 20:20 one started from a background job died with that job). The argv sweep after
        # it catches a watch started the old way, and verifies none is left even if the stop failed.
        self.run_fn(["just", "crash-watch-stop"], cwd=str(REPO_ROOT), check=False)
        self._stop_by_argv("crash-watch", _is_crash_watch_argv)

    def start_qa_loop(self, qa_toml: Path) -> None:
        # the QA loop's popup thread clicks (parley/popups.py): never started in a no-click run
        _refuse_in_no_click_run(f"the QA turn loop for {Path(qa_toml).name} (its popup thread clicks)")
        self.stop_qa_proc()
        logs_dir = REPO_ROOT / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        log_file = logs_dir / f"{qa_toml.stem}-turns.log"
        f = log_file.open("a", encoding="utf-8")
        self.qa_proc = subprocess.Popen(
            [sys.executable, "-m", "parley", "run", str(qa_toml)],
            cwd=str(REPO_ROOT),
            stdout=f,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )

    def is_game_running(self) -> bool:
        res = subprocess.run(
            ["pgrep", "-x", "medieval2.exe"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return res.returncode == 0

    def crash_dialog_up(self) -> bool:
        """Wine's "Medieval 2" crash dialog is on screen (scripts/crash_dialog.sh)."""
        try:
            res = subprocess.run(
                ["bash", str(REPO_ROOT / "scripts" / "crash_dialog.sh")],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
            )
        except subprocess.TimeoutExpired:
            return False
        return res.returncode == 0

    def eop_error_box(self) -> str | None:
        """The title of EOP's modal error box ("ERROR") when it is up, else None
        (scripts/eop_error_box.sh: read-only X queries, no input)."""
        try:
            res = subprocess.run(
                ["bash", str(REPO_ROOT / "scripts" / "eop_error_box.sh")],
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            )
        except subprocess.TimeoutExpired:
            return None
        if res.returncode != 0:
            return None
        # "<window id> <title>"
        return res.stdout.strip().partition(" ")[2] or "ERROR"

    def game_answers(self) -> bool:
        """True when the running game answers a question through the bridge (scripts/probe.sh), as
        crash_watch.sh asks before it calls a quiet game dead. A held turn (paused.txt) logs nothing:
        live 11-05 05:28 a held, healthy game was read as hung and relaunched. The run holds
        qa.lock, which probe.sh refuses unless PARLEY_QA_OWNER=1 (live 05:43: refused, read as hung)."""
        try:
            res = subprocess.run(
                ["bash", str(REPO_ROOT / "scripts" / "probe.sh"), 'return "alive"', "30"],
                check=False,
                capture_output=True,
                text=True,
                timeout=45,
                env={**os.environ, "PARLEY_QA_OWNER": "1"},
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return any(line.strip() == "alive" for line in res.stdout.splitlines())

    def relaunch_game(self, save: str | None = None) -> None:
        """relaunch_game.sh: no clicks (hidden EOP launcher, the save loaded at start-up), so it runs
        in a no-click run too. `save`: a file name in mods/parley/saves to load, else the script's
        own choice. Returns once the bridge logged the campaign's map load; fails otherwise."""
        argv = ["bash", str(REPO_ROOT / "scripts" / "relaunch_game.sh")]
        if save:
            argv += ["--save", save]
        subprocess.run(argv, cwd=str(REPO_ROOT), check=True)

    def start_real(self, real_toml: Path) -> None:
        # the real campaign's loop answers its popups by clicking: a no-click QA run's variable
        # must not follow it there (it would refuse every click for the rest of the campaign)
        subprocess.run(
            ["bash", str(REPO_ROOT / "scripts" / "game.sh"), "play", Path(real_toml).stem],
            cwd=str(REPO_ROOT),
            check=True,
            env=env_without(),
        )

    def start_crash_watch(self) -> None:
        # a no-op when the unit is already active, so at most one watch runs; never in no-click mode
        self.run_fn(["just", "crash-watch"], cwd=str(REPO_ROOT), check=True, env=env_without())

    def crash_watch_running(self) -> bool:
        """The crash-watch unit is active, or a watch started the old way (bash scripts/crash_watch.sh) runs."""
        try:
            res = self.run_fn(
                ["systemctl", "--user", "is-active", "--quiet", CRASH_WATCH_UNIT],
                check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            if res.returncode == 0:
                return True
        except OSError:
            pass
        return bool(self._find_pids(_is_crash_watch_argv))

    def running_now(self) -> dict[str, bool]:
        """What runs now, as the lock records it (RUNNING_BEFORE): the real turn loop, the Discord
        bot, crash-watch."""
        return {
            "loop": bool(self._find_pids(_is_real_loop_argv)),
            "bot": bool(self._find_pids(_is_bot_argv)),
            "crash_watch": self.crash_watch_running(),
        }

    def start_bot(self, real_toml: Path) -> None:
        """Only the real game's Discord bot (game.sh bot): its turn loop stays stopped."""
        subprocess.run(
            ["bash", str(REPO_ROOT / "scripts" / "game.sh"), "bot", Path(real_toml).stem],
            cwd=str(REPO_ROOT),
            check=True,
            env=env_without(),
        )


def _refuse_in_no_click_run(what: str) -> None:
    """QARunError (the runner's restore and report handle it) in a no-click run."""
    try:
        refuse_x_input(what)
    except XInputRefused as e:
        raise QARunError(str(e)) from e


def _no_click_guarded(fn: Callable, what: str) -> Callable:
    """`fn`, refused in a no-click run before it is called: the guard holds for an injected
    starter or relauncher as much as for the real one."""

    def guarded(*args, **kwargs):
        _refuse_in_no_click_run(what)
        return fn(*args, **kwargs)

    return guarded


def _dialog_check(
    crash_dialog_up: Callable[[], bool] | None,
    is_game_running: Callable[[], bool] | None,
    pm: _ProcessManager,
) -> Callable[[], bool]:
    """The raw crash-dialog check to use: the injected one, else the real screen only when the
    process check is real too (an injected is_game_running is a test double that must not read X)."""
    if crash_dialog_up is not None:
        return crash_dialog_up
    return pm.crash_dialog_up if is_game_running is None else (lambda: False)


def _error_box_check(
    eop_error_box: Callable[[], str | None] | None,
    is_game_running: Callable[[], bool] | None,
    pm: _ProcessManager,
) -> Callable[[], str | None] | None:
    """The EOP error box check to use, as _dialog_check: the injected one, else the real screen only
    when the process check is real too. Seen once is enough: its title is exact (no size rule)."""
    if eop_error_box is not None:
        return eop_error_box
    return pm.eop_error_box if is_game_running is None else None


def _answers_check(is_game_running: Callable[[], bool] | None, pm: _ProcessManager) -> Callable[[], bool] | None:
    """The 'does the game answer' check, as _error_box_check: the real probe only when the process
    check is real too (tests inject theirs and never reach the game)."""
    return pm.game_answers if is_game_running is None else None


# A false positive would kill a healthy game, so the dialog must be seen twice this far apart
DIALOG_CONFIRM_SECONDS = 5.0


def _confirmed_dialog(
    check: Callable[[], bool],
    *,
    apart: float = DIALOG_CONFIRM_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> Callable[[], bool]:
    """`check`, true only when it sees the dialog, waits `apart` seconds, and sees it again."""

    def confirmed() -> bool:
        if not check():
            return False
        sleep(apart)
        return check()

    return confirmed


def _await_campaign_load(
    lua_res: str,
    log_path: Path,
    offset: int,
    *,
    timeout: float = 180.0,
    poll_interval: float = 0.5,
) -> int:
    """After an M.qa.load: wait for 'qa: load ok' and the campaign's map load; its turn."""
    if lua_res.endswith(" (error)"):
        raise QARunError(f"M.qa.load failed: {lua_res}")
    deadline = time.monotonic() + timeout
    while True:
        text = _read_log_since(log_path, offset)
        m_fail = _LOAD_FAILED_RE.search(text)
        if m_fail:
            raise QARunError(f"M.qa.load failed: {m_fail.group(0)}")
        loaded_turn = _campaign_turn(text)
        if _LOAD_OK_RE.search(text) and loaded_turn is not None:
            return loaded_turn
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise QARunError(
                f"timed out after {timeout}s waiting for 'qa: load ok:' and '{CAMPAIGN_LINE}' in {log_path}"
            )
        time.sleep(min(poll_interval, remaining))


def _confirm_load(
    lua_res: str,
    log_path: Path,
    offset: int,
    *,
    expected_turn: int | None,
    timeout: float = 180.0,
    poll_interval: float = 0.5,
) -> None:
    if lua_res.endswith(" (error)"):
        raise QARunError(f"M.qa.load failed: {lua_res}")
    deadline = time.monotonic() + timeout
    while True:
        text = _read_log_since(log_path, offset)
        m_fail = _LOAD_FAILED_RE.search(text)
        if m_fail:
            raise QARunError(f"M.qa.load failed: {m_fail.group(0)}")
        m_ok = _LOAD_OK_RE.search(text)
        loaded_turn = _campaign_turn(text)
        if m_ok and loaded_turn is not None:
            if expected_turn is None:
                raise QARunError("missing expected turn in qa.lock")
            exp_turn = int(expected_turn)
            if exp_turn < 1:
                # a lock parked right after a relaunch carried the heartbeat's turn 0 (live 10-31): any
                # campaign turn is the load we asked for
                print(
                    f"qa-restore: warning: qa.lock has turn {exp_turn}; accepting the loaded campaign "
                    f"at turn {loaded_turn}",
                    file=sys.stderr,
                )
                return
            if loaded_turn not in (exp_turn, exp_turn - 1):
                raise QARunError(
                    f"bridge loaded campaign at turn {loaded_turn}, expected turn {exp_turn} (or {exp_turn - 1})"
                )
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise QARunError(
                f"timed out after {timeout}s waiting for 'qa: load ok:' and '{CAMPAIGN_LINE}' in {log_path}"
            )
        time.sleep(min(poll_interval, remaining))


def _phase_done(lock_data: dict, phase: str) -> bool:
    if bool(lock_data.get(phase)):
        return True
    phases = lock_data.get("phases")
    if isinstance(phases, dict) and bool(phases.get(phase)):
        return True
    return False


def _mark_phase(lock_path: Path, lock_data: dict, phase: str) -> None:
    lock_data[phase] = True
    phases = lock_data.get("phases")
    if isinstance(phases, dict):
        phases[phase] = True
    else:
        lock_data["phases"] = {
            "loaded": bool(lock_data.get("loaded", False)),
            "real_started": bool(lock_data.get("real_started", False)),
            "cw_started": bool(lock_data.get("cw_started", False)),
        }
    lock_path.write_text(json.dumps(lock_data, indent=2) + "\n", encoding="utf-8")


def _log_size(log_path: Path) -> int:
    try:
        return log_path.stat().st_size
    except FileNotFoundError:
        return 0


def _run_changed_game(lock_data: dict, log_path: Path) -> str | None:
    """Why the QA run may have changed the game, or None when it provably didn't: no setup helper
    logged `qa: <helper> ok:` and no turn ended since the run started (live 10-30 17:12: step one
    failed). A lock without the run's log offset proves nothing."""
    if lock_data.get("bench_loaded"):
        return f"the run loaded the bench save {lock_data.get('bench_save')}"
    start = lock_data.get("log_offset")
    if not isinstance(start, int) or isinstance(start, bool) or start < 0:
        return "the lock has no run start offset"
    text = _read_log_since(log_path, start)
    m = _QA_HELPER_OK_RE.search(text) or _TURN_ENDED_RE.search(text)
    if m:
        line = next((ln for ln in text.splitlines() if m.group(0) in ln), m.group(0))
        return f"the run logged {line.strip()!r}"
    return None


def _load_never_reached_game(lua_res: str, log_path: Path, offset: int) -> bool:
    """The load call itself errored (or the helper logged `qa: load failed`) and no `qa: load ok`
    followed: loadGame never ran, so the game is still on the bench's campaign."""
    text = _read_log_since(log_path, offset)
    if _LOAD_OK_RE.search(text):
        return False
    return lua_res.endswith(" (error)") or bool(_LOAD_FAILED_RE.search(text))


def _running_before(lock_data: dict) -> dict[str, bool] | None:
    """The lock's record of what ran before the park, or None (a lock written before it was kept,
    or a park that couldn't tell: the restore starts all three, as it always did)."""
    rec = lock_data.get(RUNNING_BEFORE)
    if not isinstance(rec, dict) or not all(isinstance(rec.get(k), bool) for k in RUNNING_KEYS):
        return None
    return {k: rec[k] for k in RUNNING_KEYS}


def _start_real_as_before(
    running: dict[str, bool] | None,
    real_config_path: Path,
    start_real_fn: Callable[[Path], None],
    start_bot_fn: Callable[[Path], None] | None,
) -> None:
    """Start the real loop and bot (game.sh play) when the loop ran before the park or nothing was
    recorded; only the bot when the bot alone ran; nothing when neither did."""
    if running is None or running["loop"]:
        start_real_fn(real_config_path)
    elif running["bot"]:
        if start_bot_fn is None:
            raise QARunError("the real bot ran before the park, but no bot starter was given")
        start_bot_fn(real_config_path)


def _restarted_words(running: dict[str, bool] | None) -> str:
    if running is None:
        return "the real loop, bot and crash-watch were restarted"
    started = [w for w, on in (("the real loop", running["loop"]),
                               ("bot", running["loop"] or running["bot"]),
                               ("crash-watch", running["crash_watch"])) if on]
    if not started:
        return "nothing was restarted (nothing ran before the park)"
    return f"{', '.join(started)} restarted as before the park"


def _write_last_restore(
    real_cfg: GameConfig,
    now_fn: Callable[[], _dt.datetime],
    restored: Path | None = None,
) -> None:
    """qa.last_restore: the newest real save's mtime (a save no newer is QA-tainted), and the save
    the restore loaded (`restored`; None when it never loaded, as in an aborted restore), so a park
    with nothing played since can reuse it (_restored_keep_if_unmoved)."""
    newest_after = newest_real_save(real_cfg.mod_save_dir)
    payload = {
        "newest_save_mtime": newest_after.stat().st_mtime if newest_after is not None else 0.0,
        "at": now_fn().isoformat(timespec="seconds"),
        "at_epoch": time.time(),  # wall clock, as file mtimes are (now_fn may be a test's)
        "restored_save": restored.name if restored is not None else None,
    }
    if restored is not None:
        payload["restored_sha256"] = _sha256(restored)
        payload["restored_mtime"] = restored.stat().st_mtime
    (real_cfg.turn_root / LAST_RESTORE_FILE).write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )


def _abort_restore(
    real_config_path: Path,
    real_cfg: GameConfig,
    lock_path: Path,
    keep_path: Path,
    cause: BaseException,
    *,
    stop_crash_watch: Callable[[], None],
    start_real: Callable[[Path], None],
    start_crash_watch: Callable[[], None],
    now_fn: Callable[[], _dt.datetime],
    running: dict[str, bool] | None = None,
    start_bot: Callable[[Path], None] | None = None,
) -> None:
    """The kept save never loaded (live 10-30 17:12: a failed load left the real loop stopped until
    restarted by hand). Restart what ran before the park (`running`; None: loop+bot and crash-watch)
    anyway, retire the lock and the keep under -aborted names, and raise. If a restart fails, the
    lock stays for `just qa-restore`."""
    _release_turn(real_cfg.turn_root)  # the real loop plays on from here, as it did before the hold
    try:
        _start_real_as_before(running, real_config_path, start_real, start_bot)
        stop_crash_watch()
        if running is None or running["crash_watch"]:
            start_crash_watch()
    except (subprocess.CalledProcessError, ControlTimeout, QARunError) as e:
        raise QARunError(
            f"restore failed at loaded; lock kept; run just qa-restore "
            f"(load never reached the game: {cause}; restarting the real loop failed: {e})"
        ) from e
    stamp = now_fn().strftime("%Y%m%d-%H%M%S")
    aborted_lock = lock_path.with_name(f"{LOCK_FILE}.aborted-{stamp}")
    os.replace(lock_path, aborted_lock)
    aborted_keep = keep_path.with_name(f"parley_keep_{real_cfg.game_id}.restored-{stamp}-aborted.sav")
    if keep_path.exists():
        os.replace(keep_path, aborted_keep)
    _write_last_restore(real_cfg, now_fn)
    raise QARunError(
        f"restore failed at loaded, aborted: the kept save never reached the game ({cause}). "
        f"The game is still on the QA bench's campaign; {_restarted_words(running)} on it. Lock moved to {aborted_lock}; the real campaign's save is {aborted_keep} "
        f"(load it by hand to get the real campaign back)."
    ) from cause


def restore(
    real_config_path: Path | str,
    *,
    control_factory: Callable[[Path], Control] | None = None,
    is_game_running: Callable[[], bool] | None = None,
    relaunch_game: Callable[[], None] | None = None,
    stop_loop: Callable[[], None] | None = None,
    stop_crash_watch: Callable[[], None] | None = None,
    start_real: Callable[[Path], None] | None = None,
    start_crash_watch: Callable[[], None] | None = None,
    reload_timeout: float = 180.0,
    poll_interval: float = 0.5,
    proc_root: Path | None = None,
    kill_fn: Callable[[int, int], None] | None = None,
    now_fn: Callable[[], _dt.datetime] = _dt.datetime.now,
    hang_seconds: float | None = None,
    relaunch_timeout: float = RELAUNCH_TIMEOUT,
    crash_dialog_up: Callable[[], bool] | None = None,
    dialog_confirm_seconds: float = DIALOG_CONFIRM_SECONDS,
    eop_error_box: Callable[[], str | None] | None = None,
    start_bot: Callable[[Path], None] | None = None,
) -> bool:
    """Restore the real campaign from its kept save, bring back what ran before the park, and clear
    qa.lock. The lock's `running_before` (loop, bot, crash-watch) says what that was: a loop that
    was stopped stays stopped, and only what ran is started. A lock without it (or `just
    qa-restore` of an older lock): real loop+bot and crash-watch are all started, as before.

    A crashed or hung game (game_trouble) is relaunched before the load; a load that times out is
    checked for a hang once, and after a relaunch tried once more."""
    real_config_path = Path(real_config_path)
    real_cfg: GameConfig = load_config(real_config_path)
    lock_path = real_cfg.turn_root / LOCK_FILE
    if not lock_path.exists():
        # a crashed bench may leave an instant case's hold: the real run's turns must end again
        _release_turn(real_cfg.turn_root)
        print("nothing to restore")
        return False

    try:
        lock_data = json.loads(lock_path.read_text(encoding="utf-8"))
        if not isinstance(lock_data, dict):
            lock_data = {}
    except (OSError, ValueError):
        lock_data = {}

    rel_save = _rel_keep_save_path(real_cfg)
    expected_turn = lock_data.get("turn")
    if expected_turn is None:
        hb = _read_heartbeat(real_cfg.turn_root)
        if hb is not None:
            expected_turn = hb[0]

    pm = _ProcessManager(proc_root=proc_root, kill_fn=kill_fn)
    stop_loop_fn = stop_loop or pm.stop_loop
    stop_cw_fn = stop_crash_watch or pm.stop_crash_watch
    is_running_fn = is_game_running or pm.is_game_running
    dialog_fn = _confirmed_dialog(
        _dialog_check(crash_dialog_up, is_game_running, pm), apart=dialog_confirm_seconds
    )
    box_fn = _error_box_check(eop_error_box, is_game_running, pm)
    keep_path = keep_save_path(real_cfg.mod_save_dir, real_cfg.game_id)
    # the relaunch makes no clicks (relaunch_game.sh), so a no-click run's restore relaunches too; it
    # starts the game straight on the kept save, never on the QA game's newer autosave
    relaunch_fn = relaunch_game or (lambda: pm.relaunch_game(save=keep_path.name))
    start_real_fn = start_real or pm.start_real
    start_cw_fn = start_crash_watch or pm.start_crash_watch
    # an injected real starter is a test double: never start the real bot for it
    start_bot_fn = start_bot or (pm.start_bot if start_real is None else None)
    running = _running_before(lock_data)
    ctrl_factory = control_factory or (lambda root: Control(root))
    stop_orphaned_fn = (
        pm.stop_orphaned_qa_loops
        if (stop_loop is None or proc_root is not None)
        else (lambda: None)
    )

    if _phase_done(lock_data, "loaded"):
        _release_turn(real_cfg.turn_root)  # the kept save is on the map already
    else:
        # Held from here until the bridge says it loaded the kept save at the real turn (live 10-31:
        # a hold lifted first let the bridge end the still-loaded bench's turn 5, at the second of
        # "qa: load ok", and the AI turns that started left later bench loads slow and moves dead).
        # A hold that is up already (an instant case's, a QA relaunch's) is kept the same way.
        _hold_turn(real_cfg.turn_root)
        lua_res: str | None = None
        log_path = real_cfg.turn_root / LOG_FILE
        offset = 0
        bridge_path = real_cfg.turn_root / "bridge.txt"
        qa_bridge_text: str | None = None
        try:
            if not keep_path.exists():
                raise QARunError(f"kept save not found at {keep_path}")
            stop_orphaned_fn()
            stop_loop_fn()

            def trouble_fn() -> str | None:
                return game_trouble(
                    is_running_fn, log_path, hang_seconds=hang_seconds, crash_dialog=dialog_fn,
                    eop_error_box=box_fn, answers=_answers_check(is_game_running, pm),
                )

            def relaunch(why: str) -> None:
                print(f"qa-restore: {why}; relaunching the game", file=sys.stderr)
                _relaunch_and_wait(relaunch_fn, log_path, timeout=relaunch_timeout, poll_interval=poll_interval)

            trouble = trouble_fn()
            if trouble is not None:
                relaunch(trouble)
            ctrl = ctrl_factory(real_cfg.turn_root)
            load_line = _load_line(keep_path, rel_save)
            offset = ctrl.log_offset()
            # the real seats' bridge config before the load, not after: the bridge acts on the
            # loaded turn at once (live 10-30 18:38:30: under the QA config still in place it
            # applied qa-field's stale orders to the real England and ended its turn 32 unasked)
            if bridge_path.exists():
                qa_bridge_text = bridge_path.read_text(encoding="utf-8")
            Orchestrator(real_cfg, {}).publish_bridge_config()
            try:
                lua_res = ctrl.run_lua(load_line)
            except ControlTimeout:
                # live 10-30 18:37: the load timed out on a game frozen for three minutes, under
                # the hang threshold; wait for the detector's verdict instead of failing outright
                trouble = _await_trouble(
                    trouble_fn, log_path, offset, hang_seconds=hang_seconds, poll_interval=poll_interval
                )
                if trouble is None:
                    raise
                relaunch(trouble)
                offset = ctrl.log_offset()
                lua_res = ctrl.run_lua(_load_line(keep_path, rel_save))
            _confirm_load(
                lua_res,
                log_path,
                offset,
                expected_turn=int(expected_turn) if expected_turn is not None else None,
                timeout=reload_timeout,
                poll_interval=poll_interval,
            )
            # "bridge loaded campaign at turn <real turn>" seen: the real campaign's turns may end again
            _release_turn(real_cfg.turn_root)
            _mark_phase(lock_path, lock_data, "loaded")
        except (subprocess.CalledProcessError, ControlTimeout, QARunError) as e:
            if lua_res is not None and _load_never_reached_game(lua_res, log_path, offset):
                changed = _run_changed_game(lock_data, log_path)
                if changed is not None:
                    # the game is on the bench's altered campaign: playing the real seats on it
                    # would be worse than a stopped loop, so the bridge keeps the QA config too
                    if qa_bridge_text is not None:
                        bridge_path.write_text(qa_bridge_text, encoding="utf-8")
                    lock_data["load_failed"] = True
                    lock_data["load_failed_reason"] = str(e)
                    lock_path.write_text(json.dumps(lock_data, indent=2) + "\n", encoding="utf-8")
                    raise QARunError(
                        f"restore failed at loaded; lock kept (phase load_failed): the kept save "
                        f"never reached the game ({e}), and the game is on the QA-altered campaign "
                        f"({changed}). The real loop and crash-watch are deliberately left stopped. "
                        f"Load {keep_path} by hand, or fix the load and run just qa-restore."
                    ) from e
                _abort_restore(
                    real_config_path, real_cfg, lock_path, keep_path, e,
                    stop_crash_watch=stop_cw_fn, start_real=start_real_fn,
                    start_crash_watch=start_cw_fn, now_fn=now_fn,
                    running=running, start_bot=start_bot_fn,
                )
            raise QARunError(
                f"restore failed at loaded; lock kept; run just qa-restore ({e})"
            ) from e

    if not _phase_done(lock_data, "real_started"):
        try:
            stop_orphaned_fn()
            _start_real_as_before(running, real_config_path, start_real_fn, start_bot_fn)
            if running is not None and not (running["loop"] or running["bot"]):
                print("qa-restore: the real loop and bot weren't running before the park; left stopped")
            _mark_phase(lock_path, lock_data, "real_started")
        except (subprocess.CalledProcessError, ControlTimeout, QARunError) as e:
            raise QARunError(
                f"restore failed at real_started; lock kept; run just qa-restore ({e})"
            ) from e

    if not _phase_done(lock_data, "cw_started"):
        try:
            stop_orphaned_fn()
            stop_cw_fn()
            if running is None or running["crash_watch"]:
                start_cw_fn()
            else:
                print("qa-restore: crash-watch wasn't running before the park; left stopped")
            _mark_phase(lock_path, lock_data, "cw_started")
        except (subprocess.CalledProcessError, ControlTimeout, QARunError) as e:
            raise QARunError(
                f"restore failed at cw_started; lock kept; run just qa-restore ({e})"
            ) from e

    keep_path = keep_save_path(real_cfg.mod_save_dir, real_cfg.game_id)
    restored_path: Path | None = None
    if keep_path.exists():
        stamp = now_fn().strftime("%Y%m%d-%H%M%S")
        restored_path = keep_path.with_name(f"parley_keep_{real_cfg.game_id}.restored-{stamp}.sav")
        os.replace(keep_path, restored_path)

    restored_files = sorted(
        (
            p
            for p in Path(real_cfg.mod_save_dir).glob(f"parley_keep_{real_cfg.game_id}.restored-*.sav")
            if not p.name.endswith("-aborted.sav")  # never loaded: the real campaign's only save
        ),
        key=lambda p: (p == restored_path, p.stat().st_mtime, p.name),
    )
    for old_restored in restored_files[:-1]:
        old_restored.unlink(missing_ok=True)

    _write_last_restore(real_cfg, now_fn, restored_path)

    lock_path.unlink(missing_ok=True)
    return True


def resume_real_after_relaunch(
    turn_root: Path | str,
    *,
    mod_save_dir: Path | str | None = None,
    log_offset: int = 0,
    control_factory: Callable[[Path], Control] | None = None,
    timeout: float = RELAUNCH_TIMEOUT,
    poll_interval: float = 0.5,
) -> str:
    """After relaunch_game.sh's Continue Campaign: put the real campaign back when Continue loaded
    the QA game's autosave (live 10-30 20:12: the real loop came back on turn 45 instead of 41).

    That is the case when <turn_root>/qa.last_restore exists and no save in `mod_save_dir`
    (default <game>/mods/parley/saves) other than the keep saves is newer than its
    newest_save_mtime: the real game hasn't autosaved since the restore. Then, once the bridge logs
    `bridge loaded campaign at turn N` (N > 0) after `log_offset`, the newest
    parley_keep_*.restored-*.sav is loaded through control.txt. A qa.lock means a bench run or
    its restore owns the game, so nothing is done. Returns what it did; raises QARunError when the
    load could not be made."""
    turn_root = Path(turn_root)
    game_dir = turn_root.parent
    save_dir = Path(mod_save_dir) if mod_save_dir is not None else game_dir / "mods" / "parley" / "saves"
    if (turn_root / LOCK_FILE).exists():
        return f"{LOCK_FILE} present: a QA run or restore owns the game; left to it"
    last_restore_path = turn_root / LAST_RESTORE_FILE
    if not last_restore_path.exists():
        return "no QA restore on record; continuing the newest save"
    try:
        data = json.loads(last_restore_path.read_text(encoding="utf-8"))
        rec = float(data["newest_save_mtime"])
    except (OSError, ValueError, TypeError, KeyError) as e:
        raise QARunError(f"invalid {last_restore_path}: {e}") from e
    newest = newest_real_save(save_dir)
    if newest is not None and newest.stat().st_mtime > rec:
        return f"{newest.name} is newer than the last QA restore; continuing it"
    restored = sorted(
        save_dir.glob("parley_keep_*.restored-*.sav"),
        key=lambda p: (p.stat().st_mtime, p.name),
    )
    if not restored:
        raise QARunError(
            f"no save newer than the last QA restore and no parley_keep_*.restored-*.sav in {save_dir}: "
            "the game may be on the QA campaign"
        )
    keep = restored[-1]
    log_path = turn_root / LOG_FILE
    deadline = time.monotonic() + timeout
    start = log_offset
    while True:
        if _log_size(log_path) < start:  # the log started over: read all of it
            start = 0
        turn = _campaign_turn(_read_log_since(log_path, start))
        if turn is not None:
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise QARunError(
                f"no '{CAMPAIGN_LINE}' in {log_path} within {timeout}s; {keep.name} not loaded"
            )
        time.sleep(min(poll_interval, remaining))
    try:
        rel = keep.resolve().relative_to(game_dir.resolve()).as_posix()
    except ValueError as e:
        raise QARunError(f"{keep} is not under the game dir {game_dir}") from e
    ctrl = (control_factory or (lambda root: Control(root)))(turn_root)
    offset = ctrl.log_offset()
    line = _load_line(keep, rel)
    try:
        lua_res = ctrl.run_lua(line)
    except ControlTimeout as e:
        raise QARunError(f"loading {keep.name}: {e}") from e
    if lua_res.endswith(" (error)"):
        raise QARunError(f"M.qa.load({rel}) failed: {lua_res}")
    deadline = time.monotonic() + timeout
    while True:
        text = _read_log_since(log_path, offset)
        m_fail = _LOAD_FAILED_RE.search(text)
        if m_fail:
            raise QARunError(f"M.qa.load({rel}) failed: {m_fail.group(0)}")
        if _LOAD_OK_RE.search(text):
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise QARunError(f"M.qa.load({rel}) sent, but no 'qa: load ok' in {log_path}")
        time.sleep(min(poll_interval, remaining))
    return (
        f"the campaign came up at turn {turn} with no real autosave since the last QA restore; "
        f"loaded {keep.name}"
    )


def _default_advance_turn(
    turn_root: Path,
    trouble_fn: Callable[[], str | None],
    timeout: float = TURN_TIMEOUT,
    poll_interval: float = 0.5,
    hang_seconds: float | None = None,
) -> Callable[[str, str, int], int]:
    log_path = Path(turn_root) / LOG_FILE

    def _advance(game_id: str, faction: str, current_turn: int) -> int:
        deadline = time.monotonic() + timeout
        while True:
            trouble = trouble_fn()
            if trouble is not None:
                raise _GameDown(trouble)
            found = _latest_state_for_faction(turn_root, [game_id], faction)
            if found is not None and found[0] > current_turn:
                return found[0]
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                # the turn wait is shorter than the hang threshold: a silent bridge gets a verdict
                trouble = _await_trouble(
                    trouble_fn, log_path, _log_size(log_path),
                    hang_seconds=hang_seconds, poll_interval=poll_interval,
                )
                if trouble is not None:
                    raise _GameDown(trouble)
                # the bridge is alive but the turn won't end (live 10-30 19:41-19:44: a papal notice,
                # "stuck? try 1..9"): no later case can run either. The case fails with the bridge's
                # own word on the turn, the report keeps it, and the restore loads the kept save
                raise _GameDown(
                    f"turn stuck: no {game_id}/{faction} report after turn {current_turn} within "
                    f"{timeout:g} s (game alive, bridge logging): {_last_turn_line(log_path)}"
                )
            time.sleep(min(poll_interval, remaining))

    return _advance


def _call_lua(
    ctrl: Control,
    line: str,
    log_path: Path,
    trouble_fn: Callable[[], str | None] | None,
) -> tuple[str | None, str]:
    """Run one control line: (result, "") or (None, why it failed: a timeout, a Lua error, or the
    helper's own `qa: <helper> failed:` line). A timeout on a crashed or hung game raises _GameDown."""
    call_offset = ctrl.log_offset()
    try:
        res = ctrl.run_lua(line)
    except ControlTimeout as exc:
        trouble = trouble_fn() if trouble_fn is not None else None
        if trouble is not None:
            raise _GameDown(trouble) from exc
        return None, str(exc)
    m_fail = _QA_FAILED_RE.search(_read_log_since(log_path, call_offset))
    if res.endswith(" (error)") or m_fail:
        return None, m_fail.group(0) if m_fail else res
    return res, ""


def _run_steps(
    case: Case,
    steps: list[str | SetupStep],
    targets: dict[str, str | int],
    ctrl: Control,
    log_path: Path,
    trouble_fn: Callable[[], str | None] | None,
    *,
    poll_interval: float = 0.5,
) -> tuple[dict[str, str | int], CaseResult | None, list[str]]:
    """Run setup (or act) lines in order, binding results: (targets with the binds, None, each line's
    "line -> result"), or (targets, the case's failed or skipped result, ...) at the first that fails.
    A step's `require` regex (instant cases) is polled for `within` s; a result it never matches skips
    the case as inconclusive, with the result as the reason."""
    done: list[str] = []
    for step in steps:
        line = _substitute_str(_setup_lua(step), targets)
        require = step.require if isinstance(step, SetupStep) else None
        deadline = time.monotonic() + (step.within if isinstance(step, SetupStep) else 0.0)
        while True:
            res, why = _call_lua(ctrl, line, log_path, trouble_fn)
            if res is None:
                return targets, CaseResult(name=case.name, outcome="fail", turns=0, evidence=why), done
            if require is None or re.search(_substitute_str(require, targets), res.strip()):
                break
            if time.monotonic() >= deadline:
                return targets, CaseResult(
                    name=case.name,
                    outcome="inconclusive",
                    turns=0,
                    evidence=f"skipped: setup `{line}` returned {res.strip()!r}, not /{_substitute_str(require, targets)}/",
                ), done
            time.sleep(poll_interval)
        done.append(f"`{line}` -> {res.strip()}")
        if isinstance(step, SetupStep) and step.bind:
            value = res.strip()
            if value in ("", "nil"):
                return targets, CaseResult(
                    name=case.name,
                    outcome="fail",
                    turns=0,
                    evidence=f"setup `{line}` bound ${step.bind} to nothing ({res!r})",
                ), done
            targets = {**targets, step.bind: value, **tile_binds(step.bind, value)}
    return targets, None, done


# paused.txt (parley/pause.py) makes the bridge end no turn and press nothing, while it still runs
# control lines (tick() reads control.txt first). An instant case holds its turn with it: the QA game's
# autoplay `wait` (60 s) would otherwise end the turn under the case. Removed only when it says this.
QA_HOLD_REASON = "qa instant case: holding the turn"


def _hold_turn(turn_root: Path) -> bool:
    """Hold the turn for an instant case. False when a pause (a seat's usage limit) is already on:
    that holds the turn too, and it is not the bench's to lift."""
    p = pause_path(turn_root)
    if p.exists():
        return False
    p.write_text(QA_HOLD_REASON + "\n", encoding="utf-8")
    return True


def _release_turn(turn_root: Path) -> None:
    """Lift the instant cases' hold (never another pause). Safe to call when there is none."""
    p = pause_path(turn_root)
    try:
        if p.read_text(encoding="utf-8").startswith(QA_HOLD_REASON):
            p.unlink()
    except OSError:
        pass


def _num(value: object) -> float | None:
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def _describe(exp: Expect, targets: dict[str, str | int]) -> str:
    sub = lambda v: _substitute_str(str(v), targets)  # noqa: E731
    if exp.alive is not None:
        return f"alive {exp.alive:g} s after /{sub(exp.after)}/"
    if exp.lua is None:
        if exp.any_of:
            return "any of (" + " | ".join(_describe(e, targets) for e in exp.any_of) + ")"
        return f"log /{sub(exp.log)}/"
    want = []
    if exp.equals is not None:
        want.append(f"== {sub(exp.equals)!r}")
    if exp.match is not None:
        want.append(f"/{sub(exp.match)}/")
    if exp.no_match is not None:
        want.append(f"not /{sub(exp.no_match)}/")
    if exp.below is not None:
        want.append(f"< {sub(exp.below)}")
    if exp.at_least is not None:
        want.append(f">= {sub(exp.at_least)}")
    return f"`{sub(exp.lua)}` " + " and ".join(want)


def _probe(
    exp: Expect,
    targets: dict[str, str | int],
    ctrl: Control,
    log_path: Path,
    case_offset: int,
    trouble_fn: Callable[[], str | None] | None,
) -> tuple[bool, str, bool]:
    """One look at an instant expect: (passed, what was seen, fatal). A query that errors is fatal:
    polling it again won't help (a helper the installed bridge lacks, a bad line)."""
    sub = lambda v: _substitute_str(str(v), targets)  # noqa: E731
    if exp.lua is None and exp.any_of:
        seen = []
        for alt in exp.any_of:
            ok, observed, _ = _probe(alt, targets, ctrl, log_path, case_offset, trouble_fn)
            if ok:
                return True, observed, False
            seen.append(observed)
        return False, " | ".join(seen), False
    if exp.alive is not None:
        # the bridge answers a control line (its tick runs, so the game isn't hung) and logs it,
        # which also keeps a held turn's log advancing; then the log since the case began says
        # whether the game lived `alive` s past the line (no relaunch between)
        res, why = _call_lua(ctrl, "return M.qa.current()", log_path, trouble_fn)
        if res is None:
            return False, f"the bridge didn't answer: {why}", False
        ok, observed = alive_after(_read_log_since(log_path, case_offset), sub(exp.after), exp.alive)
        return ok, observed, False
    if exp.lua is None:
        m = re.search(sub(exp.log), _read_log_since(log_path, case_offset))
        return (True, m.group(0), False) if m else (False, "no such log line", False)
    res, why = _call_lua(ctrl, sub(exp.lua), log_path, trouble_fn)
    if res is None:
        return False, why, True
    v = res.strip()
    ok = True
    if exp.equals is not None and v != sub(exp.equals):
        ok = False
    if exp.match is not None and not re.search(sub(exp.match), v):
        ok = False
    if exp.no_match is not None and re.search(sub(exp.no_match), v):
        ok = False
    for bound, passes in ((exp.below, lambda a, b: a < b), (exp.at_least, lambda a, b: a >= b)):
        if bound is not None:
            a, b = _num(v), _num(sub(bound))
            if a is None or b is None or not passes(a, b):
                ok = False
    return ok, v, False


def _await_own_turn(
    ctrl: Control,
    faction: str,
    log_path: Path,
    trouble_fn: Callable[[], str | None] | None,
    *,
    timeout: float,
    poll_interval: float,
) -> str | None:
    """Wait until the game is on `faction`'s turn (M.qa.current: "<faction> <turn>"): None, or why not."""
    deadline = time.monotonic() + timeout
    while True:
        res, why = _call_lua(ctrl, "return M.qa.current()", log_path, trouble_fn)
        if res is None:
            return f"can't tell whose turn it is: {why}"
        if res.strip().split(" ")[0] == faction:
            return None
        if time.monotonic() >= deadline:
            return f"not {faction}'s turn within {timeout:g} s (M.qa.current() -> {res.strip()!r})"
        if trouble_fn is not None:
            trouble = trouble_fn()
            if trouble is not None:
                raise _GameDown(trouble)
        time.sleep(poll_interval)


READY_TIMEOUT = 180.0  # how long a bench load may leave the game busy before the case fails
CANARY_WINDOW = 15.0  # how long the readiness canary has to step one tile
DECISION_WAIT = 600.0  # how long a park waits for the real loop to answer a decision on screen
CANARY_GONE_WINDOW = 10.0  # how long the canary's removal may take to land (EOP kill is not instant)
SLOW_LOAD_SECONDS = 20.0  # a bench load slower than this is flagged in the report (idle: ~4 s)
_CANARY_RE = re.compile(r"^(.+)\|(-?\d+),(-?\d+)\|(-?\d+),(-?\d+)$")
# (ctrl, bench faction, bridge log, trouble_fn) -> None when the game is idle, else "game busy: <why>"
ReadyCheck = Callable[[Control, str, Path, Callable[[], str | None] | None], str | None]


def _await_ready(
    ctrl: Control,
    faction: str,
    log_path: Path,
    trouble_fn: Callable[[], str | None] | None,
    *,
    timeout: float = READY_TIMEOUT,
    canary_window: float = CANARY_WINDOW,
    canary_gone_window: float = CANARY_GONE_WINDOW,
    poll_interval: float = 0.5,
) -> str | None:
    """After a bench load: wait until the game is idle on `faction`'s turn. None when it is, else
    "game busy: <evidence>" (the case fails with it instead of running on a busy game).

    Live 10-31 (phase1-run2): a load asked for while the AI's turns still played out took 60-75 s,
    and for minutes afterwards move orders came back "move_army ok" and nobody moved, while
    M.qa.current() already named the bench faction. EOP exposes no field known to tell that state
    apart (campaignStruct.isLoaded/isPaused are undocumented and unproven), so the signal is the
    symptom itself: the bench faction's turn (M.qa.current), then a canary (M.qa.canary: a general
    spawned near an own town and walked one tile, as a move order walks) that must reach its tile
    within `canary_window` s. It is removed again (M.qa.canary_gone) whatever it did; a canary that
    doesn't move is tried again until `timeout`."""
    deadline = time.monotonic() + timeout
    not_ours = _await_own_turn(ctrl, faction, log_path, trouble_fn, timeout=timeout, poll_interval=poll_interval)
    if not_ours is not None:
        return f"game busy: {not_ours}"
    tries: list[str] = []
    while True:
        res, why = _call_lua(ctrl, f'return M.qa.canary("{faction}")', log_path, trouble_fn)
        m = _CANARY_RE.match(res.strip()) if res is not None else None
        if m is None:
            return f"game busy: the readiness canary didn't start: {why or repr(res)}"
        army, start, target = m.group(1), f"{m.group(2)},{m.group(3)}", f"{m.group(4)},{m.group(5)}"
        seen = start
        stop = min(deadline, time.monotonic() + canary_window)
        moved = False
        try:
            while True:
                pos, _ = _call_lua(ctrl, f'return M.qa.army("{faction}", "{army}")', log_path, trouble_fn)
                seen = (pos or "?").split(" ")[0]
                if seen == target:
                    moved = True
                    break
                if time.monotonic() >= stop:
                    break
                time.sleep(poll_interval)
        finally:
            gone, gwhy = _call_lua(ctrl, f'return M.qa.canary_gone("{faction}", "{army}")', log_path, trouble_fn)
            # live 10-31 14:33: the kill lands a moment after the call, so the same call still saw
            # the army ("left"); watch it go without killing again
            gone_by = time.monotonic() + canary_gone_window
            while gone == "left" and time.monotonic() < gone_by:
                time.sleep(poll_interval)
                gone, gwhy = _call_lua(ctrl, f'return M.qa.canary_gone("{faction}", "{army}", true)',
                                       log_path, trouble_fn)
        if gone != "gone":
            return f"game busy: the readiness canary {army} wasn't removed ({gwhy or gone})"
        if moved:
            return None
        tries.append(f"{army} {start}->{target} stayed at {seen}")
        if time.monotonic() >= deadline:
            cur, _ = _call_lua(ctrl, "return M.qa.current()", log_path, trouble_fn)
            return (f"game busy: no readiness canary moved within {timeout:g} s ({len(tries)} tried, "
                    f"{canary_window:g} s each; last: {tries[-1]}; M.qa.current() -> {cur!r})")
        if trouble_fn is not None:
            trouble = trouble_fn()
            if trouble is not None:
                raise _GameDown(trouble)
        time.sleep(poll_interval)


def _run_instant_case(
    case: Case,
    qa_game_id: str,
    real_game_id: str,
    faction: str,
    turn_root: Path,
    ctrl: Control,
    current_turn: int,
    trouble_fn: Callable[[], str | None] | None = None,
    stop_qa_loop_fn: Callable[[], None] = lambda: None,
    *,
    poll_interval: float = 0.5,
    turn_wait: float = TURN_TIMEOUT,
) -> tuple[CaseResult, int]:
    """Run an instant case inside one turn: hold the turn (paused.txt), wait for the faction's own
    turn, run setup and act, then poll each expect's query until it passes or its `within` runs out.
    Nothing here ends a turn: the QA loop is stopped and stays stopped, and no plan is written. A turn
    that ended anyway (a hold that didn't take) makes the case inconclusive, whatever it saw.

    Raises _GameDown when the game crashed or hung (trouble_fn)."""
    stop_qa_loop_fn()
    held = _hold_turn(turn_root)
    try:
        latest = _latest_state_for_faction(turn_root, [qa_game_id, real_game_id], faction)
        state_dict = latest[1] if latest is not None else {}
        if latest is not None and latest[0] > current_turn:
            current_turn = latest[0]
        live_targets = {"playtest_funds": QA_PLAYTEST_FUNDS, **pick_targets(state_dict)}
        targets, missing = _effective_targets(case, live_targets)
        if missing:
            return CaseResult(
                name=case.name, outcome="fail", turns=0,
                evidence=f"no live target found in state.json for: {', '.join(missing)}",
            ), current_turn

        log_path = Path(turn_root) / LOG_FILE
        not_ours = _await_own_turn(
            ctrl, faction, log_path, trouble_fn, timeout=turn_wait, poll_interval=poll_interval
        )
        if not_ours is not None:
            return CaseResult(name=case.name, outcome="fail", turns=0, evidence=not_ours), current_turn

        case_offset = ctrl.log_offset()
        targets, failed, _ = _run_steps(
            case, case.setup, targets, ctrl, log_path, trouble_fn, poll_interval=poll_interval
        )
        if failed is not None:
            return failed, current_turn
        targets, failed, acted = _run_steps(
            case, case.act, targets, ctrl, log_path, trouble_fn, poll_interval=poll_interval
        )
        if failed is not None:
            return failed, current_turn
        unbound = sorted(_required_placeholders(case) - set(targets))
        if unbound:
            return CaseResult(
                name=case.name, outcome="fail", turns=0,
                evidence=f"setup bound nothing for: {', '.join('$' + k for k in unbound)}",
            ), current_turn

        seen: list[str] = []
        verdict: tuple[str, str] | None = None
        for exp in case.expect:
            within = exp.within if exp.within is not None else INSTANT_WITHIN
            if exp.alive is not None:  # the game must have the time to prove it lived that long
                within = max(within, exp.alive + INSTANT_WITHIN)
            deadline = time.monotonic() + within
            while True:
                ok, observed, fatal = _probe(exp, targets, ctrl, log_path, case_offset, trouble_fn)
                if ok or fatal or time.monotonic() >= deadline:
                    break
                time.sleep(poll_interval)
            if not ok:
                how = "failed" if fatal else f"not seen within {within:g} s"
                verdict = ("fail", f"{_describe(exp, targets)} {how}; observed: {observed}")
                break
            seen.append(f"{_describe(exp, targets)} -> {observed}")

        acts = "; ".join(acted)
        if _TURN_ENDED_RE.search(_read_log_since(log_path, case_offset)):
            what = verdict[1] if verdict else "; ".join(seen)
            return CaseResult(
                name=case.name, outcome="inconclusive", turns=0,
                evidence=f"the turn ended during the instant case (the hold didn't take): {what}",
            ), current_turn
        if verdict is not None:
            return CaseResult(
                name=case.name, outcome="fail", turns=0, evidence=f"act: {acts}; {verdict[1]}"
            ), current_turn
        return CaseResult(
            name=case.name, outcome="pass", turns=0, evidence=f"act: {acts}; " + "; ".join(seen)
        ), current_turn
    finally:
        if held:
            _release_turn(turn_root)


def _run_case(
    case: Case,
    qa_game_id: str,
    real_game_id: str,
    faction: str,
    turn_root: Path,
    ctrl: Control,
    current_turn: int,
    plan_path: Path,
    qa_toml_path: Path,
    start_qa_loop_fn: Callable[[Path], None],
    advance_turn_fn: Callable[[str, str, int], int],
    trouble_fn: Callable[[], str | None] | None = None,
    stop_qa_loop_fn: Callable[[], None] = lambda: None,
) -> tuple[CaseResult, int]:
    """Run one case on turns of its own. The QA loop is stopped first, so the game waits for the
    seat's answer instead of ending turns under the setup (live 10-30 17:59: sabotage's turn ended
    mid-setup and its order was planned for a turn already gone); after setup the plan is replaced by
    this case's orders alone, from the turn after the newest report, and the loop restarted on it.

    Raises _GameDown when the game crashed or hung (trouble_fn) during setup or the case's turns."""
    stop_qa_loop_fn()
    latest = _latest_state_for_faction(turn_root, [qa_game_id, real_game_id], faction)
    state_dict = latest[1] if latest is not None else {}
    if latest is not None and latest[0] > current_turn:
        current_turn = latest[0]

    live_targets = {"playtest_funds": QA_PLAYTEST_FUNDS, **pick_targets(state_dict)}
    effective_targets, missing = _effective_targets(case, live_targets)
    if missing:
        evidence = f"no live target found in state.json for: {', '.join(missing)}"
        if "home_settlement" in missing:
            evidence += f" (no own town to withdraw into: {home_refusals(state_dict)})"
        return (
            CaseResult(
                name=case.name,
                outcome="fail",
                turns=0,
                evidence=evidence,
            ),
            current_turn,
        )

    log_path = Path(turn_root) / LOG_FILE
    case_offset = ctrl.log_offset()

    effective_targets, failed, _ = _run_steps(case, case.setup, effective_targets, ctrl, log_path, trouble_fn)
    if failed is not None:
        return failed, current_turn

    unbound = sorted(_required_placeholders(case) - set(effective_targets))
    if unbound:  # a `<name>_x` whose bind came back as something other than a tile
        return (
            CaseResult(
                name=case.name,
                outcome="fail",
                turns=0,
                evidence=f"setup bound nothing for: {', '.join('$' + k for k in unbound)}",
            ),
            current_turn,
        )

    # The case's turn 1 is the turn after the newest report once setup is done: with the loop
    # stopped nobody has answered a later turn, so that turn's report comes after the setup.
    after = _latest_state_for_faction(turn_root, [qa_game_id, real_game_id], faction)
    if after is not None and after[0] > current_turn:
        current_turn = after[0]

    # orders go in after setup, so they can name what setup bound (a spawned agent's id); the plan
    # holds this case's orders and no other's
    bound_case = case.model_copy(update={"targets": effective_targets, "setup": []})
    case_plan = build_script_plan([bound_case], current_turn, effective_targets) if bound_case.orders else {}
    plan_written_at = time.time()
    # the scripted ruler's answer to the game's choices (ScriptSeat.chat), beside the turns' orders
    plan_file = {**case_plan, "choice": case.choice} if case.choice else case_plan
    plan_path.write_text(json.dumps(plan_file, indent=2) + "\n", encoding="utf-8")
    start_qa_loop_fn(qa_toml_path)
    first_order_turn = min((int(k) for k in case_plan), default=None)

    log_since = _read_log_since(log_path, case_offset)
    initial_verdict = check(bound_case, log_since, state=None, results=[], turns_used=0)
    if initial_verdict.outcome == "pass" and first_order_turn is None:
        return (
            CaseResult(
                name=case.name,
                outcome="pass",
                turns=0,
                evidence=initial_verdict.evidence,
            ),
            current_turn,
        )

    pending = "max_turns reached"
    for turns_used in range(1, bound_case.max_turns + 1):
        trouble = trouble_fn() if trouble_fn is not None else None
        if trouble is not None:
            raise _GameDown(trouble, turns=turns_used - 1)
        try:
            current_turn = advance_turn_fn(qa_game_id, faction, current_turn)
        except _GameDown as down:
            down.turns = turns_used - 1
            raise
        if first_order_turn is not None and current_turn <= first_order_turn:
            # this report comes before the case's first orders were applied: nothing of the case's in it
            pending = f"max_turns reached before the case's first orders (turn {first_order_turn}) were applied"
            continue
        log_since = _read_log_since(log_path, case_offset)
        turn_state = _state_for_turn(turn_root, qa_game_id, current_turn, faction)
        _, results = _case_results(turn_root, qa_game_id, faction, case_plan, current_turn, plan_written_at)
        if turn_state is not None:
            turn_state = {**turn_state, QA_MESSAGES: _case_messages(
                turn_root, qa_game_id, faction, case_plan, current_turn, plan_written_at)}
        verdict = check(bound_case, log_since, state=turn_state, results=results, turns_used=turns_used)
        if verdict.outcome != "pending":
            return (
                CaseResult(
                    name=case.name,
                    outcome=verdict.outcome,
                    turns=turns_used,
                    evidence=verdict.evidence,
                ),
                current_turn,
            )

    return (
        CaseResult(
            name=case.name,
            outcome="inconclusive" if bound_case.chance else "fail",
            turns=bound_case.max_turns,
            evidence=pending,
        ),
        current_turn,
    )


def _resolve_suites(suite_name: str, suites_dir: Path, cases: list[str] | None = None) -> list[Suite]:
    """smoke, then the named suite (or every suite for "all"). `cases` keeps only those cases of
    the named suite(s); smoke stays whole unless it is the suite named. An unknown case name is an
    error listing the cases there are."""
    smoke_path = Path(suites_dir) / "smoke.toml"
    smoke = load_suite(smoke_path)
    if suite_name == "smoke":
        suites = [smoke]
    elif suite_name == "all":
        others = [
            load_suite(p)
            for p in sorted(Path(suites_dir).glob("*.toml"))
            if p.stem != "smoke"
        ]
        suites = [smoke, *others]
    else:
        target_path = Path(suites_dir) / f"{suite_name}.toml"
        if not target_path.exists():
            raise QARunError(f"unknown QA suite '{suite_name}' (no {target_path})")
        suites = [smoke, load_suite(target_path)]
    if not cases:
        return suites
    filtered = suites if suite_name == "smoke" else suites[1:]
    known = [c.name for s in filtered for c in s.cases]
    unknown = [n for n in cases if n not in known]
    if unknown:
        raise QARunError(
            f"no case {', '.join(repr(n) for n in unknown)} in suite '{suite_name}'; "
            f"its cases: {', '.join(known) or 'none'}"
        )
    keep = set(cases)
    picked = [s.model_copy(update={"cases": [c for c in s.cases if c.name in keep]}) for s in filtered]
    picked = [s for s in picked if s.cases]
    return picked if suite_name == "smoke" else [smoke, *picked]


# `--kind instant` (phase 1 of the author's no-click rule, 10-31): only the cases that need no played turn
RUN_KINDS = ("all", "instant")
SKIPPED_TURN_CASE = "skipped: needs a played turn (click phase)"
SKIPPED_PHASE2 = "skipped: phase 2: "


def _instant_only(suites: list[Suite]) -> tuple[list[Suite], dict[str, list[tuple[str, str]]]]:
    """Each suite with its phase-1 instant cases alone (a suite left with none stays, empty, so its
    skipped cases are still reported), and each suite's skipped cases as (name, evidence): its turn
    cases (a turn case ends a turn, and only the QA turn loop answers turns; its popup thread clicks)
    and the instant cases whose `phase2` says why they wait for phase 2."""
    kept: list[Suite] = []
    skipped: dict[str, list[tuple[str, str]]] = {}
    for s in suites:
        skipped[s.name] = [
            (c.name, SKIPPED_TURN_CASE if c.kind != "instant" else SKIPPED_PHASE2 + str(c.phase2))
            for c in s.cases if c.kind != "instant" or c.phase2
        ]
        kept.append(s.model_copy(update={"cases": [c for c in s.cases if c.kind == "instant" and not c.phase2]}))
    return kept, skipped


def _real_process_record(
    pm: _ProcessManager,
    running_now: Callable[[], dict[str, bool]] | None,
    start_bot: Callable[[Path], None] | None,
    stop_loop: Callable[[], None] | None,
    start_real: Callable[[Path], None] | None,
) -> tuple[Callable[[], dict[str, bool]] | None, Callable[[Path], None] | None]:
    """(what-runs reader, bot starter) for a park: the injected ones, else the real ones, except
    beside an injected stopper/starter (a test double), where the real processes are never read
    (nothing is recorded: the restore starts everything, as before) or started."""
    running_fn = running_now or (pm.running_now if stop_loop is None else None)
    start_bot_fn = start_bot or (pm.start_bot if start_real is None else None)
    return running_fn, start_bot_fn


def _decision_on_screen(turn_root: Path) -> bool:
    """Whether a decision scroll (a check and an X) is on the game's screen, as the real loop finds
    one (parley.popups.find_choice). A screenshot that fails says no: a game that is down fails the
    bridge gate after the park anyway."""
    from parley.popups import _window, find_choice
    png = turn_root / "qa_park_check.png"
    try:
        # the window alone, no pointer move: popups.screenshot moves the pointer off the scroll first,
        # refused in a no-click run (live 10-31 17:00: "couldn't look ... parking anyway"); a button
        # under the pointer may go unseen, the rare case the loop's own looks cover
        subprocess.run(["import", "-window", _window(), str(png)], check=True, capture_output=True, timeout=20)
        return find_choice(png) is not None
    except Exception as e:  # noqa: BLE001 - no window, no xdotool: the park goes on
        print(f"qa: couldn't look for a decision on screen ({e}); parking anyway", flush=True)
        return False


def _park_real(
    real_cfg: GameConfig,
    real_config_path: Path,
    lock_path: Path,
    *,
    stop_loop_fn: Callable[[], None],
    stop_cw_fn: Callable[[], None],
    start_real_fn: Callable[[Path], None],
    start_cw_fn: Callable[[], None],
    now_fn: Callable[[], _dt.datetime],
    extra: dict | None = None,
    running_now_fn: Callable[[], dict[str, bool]] | None = None,
    start_bot_fn: Callable[[Path], None] | None = None,
    decision_open_fn: Callable[[], bool] | None = None,
    decision_wait: float = DECISION_WAIT,
    decision_poll: float = 10.0,
) -> tuple[dict, int]:
    """Park the real run: record what runs (`running_now_fn`: loop, bot, crash-watch; None records
    nothing, and the restore then starts all three), stop its loop, bot and crash-watch, keep a
    copy of its newest save, and write the lock (with `extra`). Returns (the lock's payload, the
    real turn). On any failure the lock goes, what ran before is restarted, and the error is raised.

    The first thing it does to the game is hold the turn (_hold_turn; the lock's `park_held` says it
    did): with the real loop stopped the bridge's autoplay would still end the real campaign's turn
    on its own timeout, mid-park (live 10-31 12:50 "autoplay: ending turn 7", then the bridge
    answered nothing while the AI turns played). The restore lifts it once the kept save is loaded;
    a run lifts it earlier only where it lets turns end (_run_suite); a failed park lifts it here."""
    turn_root = real_cfg.turn_root
    running: dict[str, bool] | None = None
    if running_now_fn is not None:  # before anything is stopped: a failure here changes nothing
        now_running = running_now_fn()
        running = {k: bool(now_running.get(k)) for k in RUNNING_KEYS}
    # a decision on screen (marriage, adoption, an AI's offer) is the real loop's to answer: wait for
    # it before stopping anything. Live 10-31 16:19 a marriage offer open at the park stayed over
    # every bench load (no clicks on the bench), and the game took commands and ran none of them
    if decision_open_fn is not None and decision_open_fn():
        print(f"qa: a decision is open on screen; waiting up to {decision_wait:g} s for the real loop "
              "to answer it before parking", flush=True)
        give_up = time.monotonic() + decision_wait
        while decision_open_fn():
            if time.monotonic() >= give_up:
                raise QARunError(
                    f"a decision is open on screen and stayed for {decision_wait:g} s; the real loop "
                    "didn't answer it (its ruler may be slow or down): answer it, then retry")
            time.sleep(decision_poll)
    park_held = False
    try:
        park_held = _hold_turn(turn_root)
        stop_loop_fn()
        stop_cw_fn()
        keep_path = ensure_keep_save(real_cfg.mod_save_dir, real_cfg.game_id, turn_root=turn_root)
        hb = _read_heartbeat(turn_root)
        if hb is None:
            raise QARunError(
                f"no valid {HEARTBEAT_FILE} found in {turn_root}; "
                f"wait for one real turn, then retry"
            )
        real_turn = hb[0]
        load = _newest_campaign_load(turn_root / LOG_FILE)
        if real_turn >= 1 and load is not None and load[1] is not None and load[1] > hb[1]:
            # a campaign load newer than the heartbeat: a relaunch that loaded at start-up writes no
            # heartbeat until a turn starts, so the heartbeat is the game before it (live 11-04: a
            # crashed bench run left turn 6, the relaunch loaded turn 74, the restore then refused it)
            real_turn = load[0]
        if real_turn < 1:
            # right after a click-free relaunch the heartbeat says turn 0 (the menu's map): the
            # campaign's own load line has the real turn (live 10-31: lock turn 0, restore refused 49)
            log_turn = _newest_campaign_turn(turn_root / LOG_FILE)
            if log_turn is None:
                raise QARunError(
                    f"{HEARTBEAT_FILE} in {turn_root} says turn {real_turn} and the bridge log has no "
                    f"campaign turn ('{CAMPAIGN_LINE}'); load the campaign, then retry"
                )
            real_turn = log_turn
        now = now_fn()
        lock_payload = {
            "game_id": real_cfg.game_id,
            "real_game_id": real_cfg.game_id,
            "real_config": str(real_config_path.resolve()),
            "kept_save": str(keep_path.resolve()),
            "turn": real_turn,
            "started_at": now.isoformat(timespec="seconds"),
            "started_epoch": now.timestamp(),
            # the restore reads the bridge log from here to tell whether the run changed the game
            "log_offset": _log_size(turn_root / LOG_FILE),
            "loaded": False,
            "real_started": False,
            "cw_started": False,
            "park_held": park_held,
            "phases": {
                "loaded": False,
                "real_started": False,
                "cw_started": False,
            },
            **(extra or {}),
        }
        if running is not None:
            lock_payload[RUNNING_BEFORE] = running
        lock_path.write_text(json.dumps(lock_payload, indent=2) + "\n", encoding="utf-8")
    except BaseException as exc:
        lock_path.unlink(missing_ok=True)
        if park_held:
            _release_turn(turn_root)  # the real campaign plays on as before the park
        restart_errors: list[Exception] = []
        try:
            _start_real_as_before(running, real_config_path, start_real_fn, start_bot_fn)
        except Exception as re_exc:
            restart_errors.append(re_exc)
        try:
            if running is None or running["crash_watch"]:
                start_cw_fn()
        except Exception as cw_exc:
            restart_errors.append(cw_exc)
        if restart_errors:
            restart_msg = "; ".join(str(e) for e in restart_errors)
            raise QARunError(
                f"{exc} (also failed to restart real loop/crash-watch: {restart_msg})"
            ) from exc
        raise
    return lock_payload, real_turn


# Live 10-31 12:50: with the real loop stopped, the bridge's autoplay ended the real campaign's turn
# on its own timeout, and while the game played the AI turns the bridge answered control.txt slowly
# or not at all for a minute or more; the first bench load timed out after Control's 30 s.
BRIDGE_ANSWER_WAIT = 180.0  # before the first bench load: how long the bridge may take to answer
LOAD_CALL_WAIT = 180.0  # M.qa.load's own answer, while the bridge log keeps growing


def _send_and_wait(
    ctrl: Control,
    line: str,
    *,
    max_wait: float,
    quiet_limit: float | None,
    log_path: Path,
    trouble_fn: Callable[[], str | None] | None,
    poll_interval: float,
    resend_ok: bool = False,
) -> str:
    """Send `line` once and wait for its answer up to `max_wait` s, giving up sooner once the bridge
    log has been silent `quiet_limit` s (None: no such limit; a bridge that is alive keeps logging).
    Never sent twice: a timed-out line stays in control.txt, and its late answer would be read as
    the next line's. Raises ControlTimeout; _GameDown when `trouble_fn` says crashed or hung.
    A control with no send_lua (a test double) gets run_lua, retried on ControlTimeout only when
    `resend_ok` (a harmless line)."""
    start = time.monotonic()
    send = getattr(ctrl, "send_lua", None)
    if send is None:
        while True:
            try:
                return ctrl.run_lua(line)
            except ControlTimeout:
                trouble = trouble_fn() if trouble_fn is not None else None
                if trouble is not None:
                    raise _GameDown(trouble) from None
                if not resend_ok or time.monotonic() - start >= max_wait:
                    raise
    offset = send(line)
    size = _log_size(log_path)
    last_growth = time.monotonic()
    while True:
        res = ctrl.result_after(offset)
        if res is not None:
            return res
        now = time.monotonic()
        cur = _log_size(log_path)
        if cur != size:
            size, last_growth = cur, now
        waited = now - start
        if waited >= max_wait or (quiet_limit is not None and now - last_growth >= quiet_limit):
            raise ControlTimeout(
                f"timed out after {waited:.1f}s waiting for bridge response to `lua {line}` in "
                f"{getattr(ctrl, 'turn_root', log_path.parent)}"
            )
        trouble = trouble_fn() if trouble_fn is not None else None
        if trouble is not None:
            raise _GameDown(trouble)
        time.sleep(poll_interval)


def _await_bridge_answer(
    ctrl: Control,
    log_path: Path,
    trouble_fn: Callable[[], str | None] | None,
    *,
    timeout: float = BRIDGE_ANSWER_WAIT,
    poll_interval: float = 0.5,
) -> str | None:
    """Before the first bench load: wait until the bridge answers `return 1` (it answers nothing while
    the game plays AI turns). None once it answered, else "game busy: the bridge didn't answer for
    Ns". A crashed or hung game (trouble_fn) raises _GameDown."""
    t0 = time.monotonic()
    try:
        _send_and_wait(ctrl, "return 1", max_wait=timeout, quiet_limit=None, log_path=Path(log_path),
                       trouble_fn=trouble_fn, poll_interval=poll_interval, resend_ok=True)
    except ControlTimeout:
        return f"game busy: the bridge didn't answer for {time.monotonic() - t0:.0f}s"
    return None


def _load_bench_save(
    bench: BenchSave,
    ctrl: Control,
    turn_root: Path,
    *,
    reload_timeout: float,
    poll_interval: float,
    on_called: Callable[[], None] = lambda: None,
    load_wait: float = LOAD_CALL_WAIT,
) -> float:
    """Load the bench save (M.qa.load) and wait for the game to say it loaded it at its recorded turn.
    `on_called` runs once the load call went out (the game may be on the bench's campaign from then).
    The call's own answer: as long as `load_wait` while the bridge log keeps growing (the game is
    alive, just busy), Control's timeout once the log is silent that long (as before).
    Returns the load's seconds (idle game: ~4 s; live 10-31 60-75 s while AI turns still played out)."""
    start = time.monotonic()
    log_path = Path(turn_root) / LOG_FILE
    offset = ctrl.log_offset()
    line = _load_line(bench.path, bench.rel)
    try:
        lua_res = _send_and_wait(
            ctrl, line, max_wait=max(load_wait, getattr(ctrl, "timeout", 30.0)),
            quiet_limit=getattr(ctrl, "timeout", 30.0), log_path=log_path, trouble_fn=None,
            poll_interval=min(poll_interval, 0.5),
        )
    except ControlTimeout as e:
        raise QARunError(f"loading the bench save {bench.rel}: {e}") from e
    on_called()
    try:
        _confirm_load(lua_res, log_path, offset, expected_turn=bench.turn,
                      timeout=reload_timeout, poll_interval=poll_interval)
    except QARunError as e:
        raise QARunError(f"bench save {bench.rel}: {e}") from e
    _quiet_world(ctrl, log_path, bench.rel)
    return time.monotonic() - start


_QUIET_RE = re.compile(r"^pope=")


def _quiet_world(ctrl: Control, log_path: Path, rel: str) -> str:
    """After every bench load, before any turn: the quiet world (M.qa.quiet makes the Pope young, so
    no old-age papal election opens scrolls mid-case; 11-01 one stalled turn 50 for hours). The
    bridge logs its "qa: quiet ok: pope=<name> age=<before>-><after>" line. A load whose quiet step
    fails is refused, never run on a world that may elect a Pope (games/interrupts.toml)."""
    res, why = _call_lua(ctrl, "return M.qa.quiet()", log_path, None)
    if res is None or not _QUIET_RE.match(res.strip()):
        raise QARunError(f"bench save {rel}: the quiet-world step failed: {why or repr(res)}"
                         " (is the installed bridge current? just install-bridge)")
    return res.strip()


def _load_bench(
    bench: BenchSave,
    ctrl: Control,
    turn_root: Path,
    orch: Orchestrator,
    lock_path: Path,
    lock_payload: dict,
    trouble_fn: Callable[[], str | None],
    *,
    reload_timeout: float,
    poll_interval: float,
    load_wait: float = LOAD_CALL_WAIT,
) -> float:
    """Load the bench save under the QA config already published (its quiet world in force), then
    have the bridge write the bench faction's report for the turn before the loaded one, as a real
    campaign has on its map: the cases pick their targets from it, never from the live campaign."""
    log_path = Path(turn_root) / LOG_FILE

    def mark_loaded() -> None:
        lock_payload["bench_loaded"] = True  # from here the game may be on the bench's campaign
        lock_path.write_text(json.dumps(lock_payload, indent=2) + "\n", encoding="utf-8")

    load_seconds = _load_bench_save(bench, ctrl, turn_root, reload_timeout=reload_timeout,
                                    poll_interval=poll_interval, on_called=mark_loaded,
                                    load_wait=load_wait)
    report_turn = bench.turn - 1
    orch.prepare_turn_dirs(report_turn)
    res, why = _call_lua(ctrl, f'return M.qa.report("{bench.faction}", {report_turn})', log_path, trouble_fn)
    state = (Path(turn_root) / orch.config.game_id / f"turn-{report_turn:04d}" / bench.faction / "state.json")
    if res is None or not state.exists():
        raise QARunError(
            f"the bench save loaded, but the bridge wrote no {bench.faction} report "
            f"({why or 'no ' + str(state)}); is the installed bridge current (just install-bridge)?"
        )
    return load_seconds


# `--no-smoke` (instant-only reruns) skips smoke only when a whole smoke suite passed this recently
SMOKE_FRESH_SECONDS = 30 * 60
LAST_SMOKE_FILE = "qa.last_smoke"


def _last_smoke_age(turn_root: Path, now: _dt.datetime) -> float | None:
    """Seconds since a whole smoke suite last passed (qa.last_smoke), or None when none is recorded."""
    try:
        data = json.loads((Path(turn_root) / LAST_SMOKE_FILE).read_text(encoding="utf-8"))
        return now.timestamp() - float(data["passed_epoch"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _no_smoke_refusal(suites: list[Suite], suite_name: str, turn_root: Path, now: _dt.datetime) -> str | None:
    """Why `--no-smoke` may not skip smoke for this run, or None when it may."""
    if suite_name in ("smoke", "all"):
        return f"--no-smoke can't run with suite '{suite_name}'"
    rest = suites[1:]
    turn_cases = [c.name for s in rest for c in s.cases if c.kind != "instant"]
    if turn_cases:
        return f"--no-smoke is for instant cases only; these end turns: {', '.join(turn_cases)}"
    age = _last_smoke_age(turn_root, now)
    if age is None:
        return f"--no-smoke needs a smoke pass in the last {SMOKE_FRESH_SECONDS // 60} min; none recorded ({LAST_SMOKE_FILE})"
    if age > SMOKE_FRESH_SECONDS or age < 0:
        return (f"--no-smoke needs a smoke pass in the last {SMOKE_FRESH_SECONDS // 60} min; "
                f"the last was {int(age // 60)} min ago")
    return None


def run_suite(
    suite_name: str,
    real_config_path: Path | str,
    *,
    suites_dir: Path = DEFAULT_SUITES_DIR,
    report_dir: Path = DEFAULT_REPORT_DIR,
    qa_games_dir: Path | None = None,
    control_factory: Callable[[Path], Control] | None = None,
    advance_turn: Callable[[str, str, int], int] | None = None,
    is_game_running: Callable[[], bool] | None = None,
    relaunch_game: Callable[[], None] | None = None,
    stop_loop: Callable[[], None] | None = None,
    stop_crash_watch: Callable[[], None] | None = None,
    start_qa_loop: Callable[[Path], None] | None = None,
    start_real: Callable[[Path], None] | None = None,
    start_crash_watch: Callable[[], None] | None = None,
    reload_timeout: float = 180.0,
    turn_timeout: float = TURN_TIMEOUT,
    poll_interval: float = 0.5,
    now_fn: Callable[[], _dt.datetime] = _dt.datetime.now,
    stop_qa_loop: Callable[[], None] | None = None,
    hang_seconds: float | None = None,
    relaunch_timeout: float = RELAUNCH_TIMEOUT,
    crash_dialog_up: Callable[[], bool] | None = None,
    dialog_confirm_seconds: float = DIALOG_CONFIRM_SECONDS,
    eop_error_box: Callable[[], str | None] | None = None,
    cases: list[str] | None = None,
    no_smoke: bool = False,
    instant_turn_wait: float = TURN_TIMEOUT,
    bench_save: bool = True,
    kind: str = "all",
    running_now: Callable[[], dict[str, bool]] | None = None,
    start_bot: Callable[[Path], None] | None = None,
    ready_check: ReadyCheck | None = None,
    bridge_wait: float = BRIDGE_ANSWER_WAIT,
    load_wait: float = LOAD_CALL_WAIT,
    power_off: Callable[[], _dt.time | None] = power_off_time,
) -> tuple[list[CaseResult], Path]:
    """Run smoke + the requested QA suite(s), write the report, and always restore the real campaign
    to what ran before (`running_now` at the park: loop, bot, crash-watch; read from /proc and
    systemd unless the process helpers are injected).

    `kind="instant"` (phase 1 of the no-click rule): only instant cases run; each turn case is
    reported as "skipped: needs a played turn (click phase)". No QA turn loop is started (its popup
    thread is what clicks), and the whole run, restore included, is a no-click run
    (PARLEY_NO_X_INPUT=1, parley/xinput.py): anything that would still reach X input (the QA loop)
    is refused with a QARunError naming it. The restore's relaunch after a crash makes no clicks
    (relaunch_game.sh loads the kept save at start-up) and goes ahead. Smoke's instant case
    (`helpers`) gates the run; its turn cases are skipped like any other."""
    args = dict(locals())
    if kind not in RUN_KINDS:
        raise QARunError(f"unknown run kind {kind!r}; one of {', '.join(RUN_KINDS)}")
    if kind == "instant":
        with no_click_run():
            return _run_suite(**args)
    return _run_suite(**args)


def _run_suite(
    suite_name: str,
    real_config_path: Path | str,
    *,
    suites_dir: Path,
    report_dir: Path,
    qa_games_dir: Path | None,
    control_factory: Callable[[Path], Control] | None,
    advance_turn: Callable[[str, str, int], int] | None,
    is_game_running: Callable[[], bool] | None,
    relaunch_game: Callable[[], None] | None,
    stop_loop: Callable[[], None] | None,
    stop_crash_watch: Callable[[], None] | None,
    start_qa_loop: Callable[[Path], None] | None,
    start_real: Callable[[Path], None] | None,
    start_crash_watch: Callable[[], None] | None,
    reload_timeout: float,
    turn_timeout: float,
    poll_interval: float,
    now_fn: Callable[[], _dt.datetime],
    stop_qa_loop: Callable[[], None] | None,
    hang_seconds: float | None,
    relaunch_timeout: float,
    crash_dialog_up: Callable[[], bool] | None,
    dialog_confirm_seconds: float,
    eop_error_box: Callable[[], str | None] | None,
    cases: list[str] | None,
    no_smoke: bool,
    instant_turn_wait: float,
    bench_save: bool,
    kind: str,
    running_now: Callable[[], dict[str, bool]] | None,
    start_bot: Callable[[Path], None] | None,
    ready_check: ReadyCheck | None,
    bridge_wait: float = BRIDGE_ANSWER_WAIT,
    load_wait: float = LOAD_CALL_WAIT,
    power_off: Callable[[], _dt.time | None] = power_off_time,
) -> tuple[list[CaseResult], Path]:
    """run_suite's body (run_suite sets up the no-click run around it).

    The cases run on the bench save (load_bench_save; refused when it is missing), in a quiet world:
    every AI faction's game AI frozen but the running case's `needs`. `bench_save=False` runs them on
    the parked live campaign instead, as before; only the park/restore machinery's tests use it.

    `cases` runs only those cases of the suite; `no_smoke` skips smoke for a run of instant cases
    alone when a whole smoke suite passed in the last SMOKE_FRESH_SECONDS (qa.last_smoke).
    Before each case and while a case waits for its turns, a crashed or hung game (game_trouble)
    fails the case with that as evidence and ends the run; the restore relaunches the game."""
    run_start = time.monotonic()
    suites = _resolve_suites(suite_name, Path(suites_dir), cases)
    instant_run = kind == "instant"
    skipped_turn: dict[str, list[str]] = {}
    if instant_run:
        suites, skipped_turn = _instant_only(suites)
    real_config_path = Path(real_config_path)
    real_cfg = load_config(real_config_path)
    _rel_keep_save_path(real_cfg)

    turn_root = real_cfg.turn_root
    turn_root.mkdir(parents=True, exist_ok=True)

    lock_path = turn_root / LOCK_FILE
    if lock_path.exists():
        raise QARunError(
            f"refusing to start QA run: lock file already exists at {lock_path} "
            f"(run `just qa-restore` first)"
        )
    if no_smoke:
        why = _no_smoke_refusal(suites, suite_name, turn_root, now_fn())
        if why is not None:
            raise QARunError(f"refusing to start QA run: {why}")
        suites = suites[1:]
    # a machine that powers off on a schedule kills a run mid-case (the test laptop: 23:59 to 03:00 nightly)
    try:
        off = power_off()
    except ValueError as e:
        raise QARunError(f"refusing to start QA run: {e}") from None
    why = power_off_refusal(now_fn(), sum(len(s.cases) for s in suites), off)
    if why is not None:
        raise QARunError(f"refusing to start QA run: {why}")
    # any run whose smoke suite passed records it for --no-smoke (live 10-31 12:34: a `kind=instant
    # case=X` run passed smoke, and at 12:36 --no-smoke found none). An instant run's smoke is smoke's
    # instant cases, all a --no-smoke run (instant cases only) would run of it; the record says which
    # kind passed. Only a case filter on smoke itself runs part of the suite: no record.
    whole_smoke = not (suite_name == "smoke" and cases)

    bench: BenchSave | None = None
    if bench_save:
        bench = load_bench_save(real_cfg)
        other = sorted({s.faction for s in suites} - {bench.faction})
        if other:
            raise QARunError(
                f"refusing to start QA run: the bench save plays {bench.faction}, "
                f"but suite(s) play {', '.join(other)}"
            )

    _preflight_keep_save(real_cfg.mod_save_dir, real_cfg.game_id, turn_root=turn_root)

    pm = _ProcessManager()
    stop_loop_fn = stop_loop or pm.stop_loop
    stop_cw_fn = stop_crash_watch or pm.stop_crash_watch
    # both refused in a no-click run, injected or not (the QA loop's popup thread clicks)
    start_qa_fn = _no_click_guarded(start_qa_loop or pm.start_qa_loop,
                                    "the QA turn loop (its popup thread clicks)")
    # an injected loop starter without a stopper is a test double: never kill real QA loops for it
    stop_qa_fn = stop_qa_loop or (pm.stop_qa_proc if start_qa_loop is None else (lambda: None))
    is_running_fn = is_game_running or pm.is_game_running
    raw_dialog_fn = _dialog_check(crash_dialog_up, is_game_running, pm)
    dialog_fn = _confirmed_dialog(raw_dialog_fn, apart=dialog_confirm_seconds)
    box_fn = _error_box_check(eop_error_box, is_game_running, pm)
    # None: the restore relaunches with the kept save (no clicks, allowed in a no-click run)
    relaunch_fn = relaunch_game
    start_real_fn = start_real or pm.start_real
    start_cw_fn = start_crash_watch or pm.start_crash_watch
    ctrl_factory = control_factory or (lambda root: Control(root))
    # the readiness gate after each bench load: the canary on the real game; an injected control is a
    # test double that answers no canary, so it gets one only when the test passes it
    ready_fn: ReadyCheck | None = ready_check
    if ready_fn is None and control_factory is None:
        ready_fn = lambda c, fac, log, trouble: _await_ready(c, fac, log, trouble, poll_interval=poll_interval)  # noqa: E731

    def trouble_fn() -> str | None:
        return game_trouble(
            is_running_fn, turn_root / LOG_FILE, hang_seconds=hang_seconds, crash_dialog=dialog_fn,
            eop_error_box=box_fn, answers=_answers_check(is_game_running, pm),
        )

    def await_ready() -> tuple[float, str | None]:
        """(seconds the gate took, None or "game busy: <why>") after a bench load."""
        assert bench is not None
        if ready_fn is None:
            return 0.0, None
        t0 = time.monotonic()
        busy = ready_fn(ctrl, bench.faction, turn_root / LOG_FILE, trouble_fn)
        return time.monotonic() - t0, busy

    advance_fn = advance_turn or _default_advance_turn(
        turn_root, trouble_fn, timeout=turn_timeout, poll_interval=poll_interval,
        hang_seconds=hang_seconds,
    )

    all_results: list[CaseResult] = []
    reloads: list[float] = []  # each bench reload's seconds (case isolation)
    out_games_dir = Path(qa_games_dir) if qa_games_dir is not None else real_config_path.parent
    report_path: Path | None = None

    running_fn, start_bot_fn = _real_process_record(pm, running_now, start_bot, stop_loop, start_real)
    lock_payload, real_turn = _park_real(
        real_cfg, real_config_path, lock_path,
        stop_loop_fn=stop_loop_fn, stop_cw_fn=stop_cw_fn, start_real_fn=start_real_fn,
        start_cw_fn=start_cw_fn, now_fn=now_fn,
        extra={"bench_save": bench.rel} if bench is not None else None,
        running_now_fn=running_fn, start_bot_fn=start_bot_fn,
        # the real game only: a test double's stopper means there is no screen to look at
        decision_open_fn=(lambda: _decision_on_screen(turn_root)) if stop_loop is None else None,
    )

    try:
        ctrl = ctrl_factory(turn_root)
        active_suite = suites[-1] if suite_name != "all" else suites[0]
        qa_game_id = f"qa-{active_suite.name}"

        current_turn = real_turn
        # no case's orders yet: each case writes the plan once the case before it is decided, with
        # its own orders alone (_run_case; live 10-30 18:00 the cases overlapped in one plan)
        plan_path = out_games_dir / f"qa-{active_suite.name}-plan.json"
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text("{}\n", encoding="utf-8")

        quiet = bench is not None
        qa_toml_path = write_qa_config(
            real_config_path,
            active_suite,
            plan_path,
            out_path=out_games_dir / f"qa-{active_suite.name}.toml",
            quiet=quiet,
        )
        qa_cfg = load_config(qa_toml_path)
        orch = Orchestrator(qa_cfg, {})
        # the game the cases' reports come from when their own suite's has none yet: the bench
        # report's (written below), or the live campaign's when no bench save is used
        context_game_id = qa_game_id if bench is not None else real_cfg.game_id
        thawed: list[str] = []
        held_for_load = False
        park_held = bool(lock_payload.get("park_held"))  # the park's hold (_park_real) is the run's
        if instant_run or suites[0].instant:
            # instant cases first (--no-smoke, or a --kind instant run): hold the turn before the QA
            # config reaches the bridge, whose 60 s wait has likely run out on this turn already;
            # held until the run ends (an instant run never ends a turn)
            _hold_turn(turn_root)
        elif bench is not None:
            # the loaded turn must not end before its report is written
            held_for_load = _hold_turn(turn_root) or park_held
        elif park_held:
            # the parked live campaign itself is the world, and its turn cases end turns
            _release_turn(turn_root)
        archive_qa_game(turn_root, qa_game_id, now_fn)  # before the bridge plays the QA game
        orch.publish_bridge_config()
        # the last bench load not yet charged to a case: (load s, ready s, None or "game busy: ...")
        pending_load: tuple[float, float, str | None] | None = None
        if bench is not None:
            # live 10-31 12:50: the bridge answered nothing for a minute or more while the AI turns of
            # a turn ended before the park played out; the load timed out after Control's 30 s
            busy = _await_bridge_answer(ctrl, turn_root / LOG_FILE, trouble_fn, timeout=bridge_wait,
                                        poll_interval=poll_interval)
            if busy is not None:
                raise QARunError(busy)
            load_s = _load_bench(
                bench, ctrl, turn_root, orch, lock_path, lock_payload, trouble_fn,
                reload_timeout=reload_timeout, poll_interval=poll_interval, load_wait=load_wait,
            )
            current_turn = bench.turn
            try:
                ready_s, busy = await_ready()  # still held: nothing ends the turn meanwhile
            finally:
                if held_for_load:
                    _release_turn(turn_root)
            pending_load = (load_s, ready_s, busy)
        orch.prepare_turn_dirs(current_turn)

        def publish_world(suite: Suite, needs: list[str]) -> None:
            """The case's quiet world: every AI faction frozen but the ones it needs (bench only)."""
            nonlocal thawed, qa_cfg, orch
            want = sorted(set(needs))
            if bench is None or want == thawed:
                return
            write_qa_config(real_config_path, suite, plan_path, out_path=qa_toml_path,
                            quiet=True, thaw=want)
            qa_cfg = load_config(qa_toml_path)
            orch = Orchestrator(qa_cfg, {})
            orch.publish_bridge_config()
            thawed = want

        def needs_loop(suite: Suite) -> bool:
            """An instant suite holds its turns: nobody may answer them; an instant run starts none."""
            return not instant_run and not suite.instant

        # case isolation (cases.Isolation): the world is the bench save as recorded until a case runs
        world_fresh = bench is not None
        force_reload = False  # a case failed on a busy game: the next one loads the bench again
        load_info: tuple[float, float, str | None] | None = None

        def reload_bench() -> tuple[float, float, str | None]:
            """The bench save again, for a case that starts fresh: the QA loop stopped and the turn
            held meanwhile. When turns were played since the last load, the QA games' turn folders
            go to the archive first (a reloaded turn must not meet the orders and reports of turns
            the reload undid) and the bench report is written again, into the active game. Then,
            still held, the readiness gate (await_ready). Returns (load s, ready s, busy)."""
            nonlocal context_game_id, current_turn
            assert bench is not None
            stop_qa_fn()
            held = _hold_turn(turn_root)
            try:
                if current_turn > bench.turn:
                    for gid in dict.fromkeys((qa_game_id, context_game_id)):
                        archive_qa_game(turn_root, gid, now_fn)
                    load_s = _load_bench(
                        bench, ctrl, turn_root, orch, lock_path, lock_payload, trouble_fn,
                        reload_timeout=reload_timeout, poll_interval=poll_interval, load_wait=load_wait,
                    )
                    context_game_id = qa_game_id
                else:
                    load_s = _load_bench_save(bench, ctrl, turn_root, reload_timeout=reload_timeout,
                                              poll_interval=poll_interval, load_wait=load_wait)
                current_turn = bench.turn
                orch.prepare_turn_dirs(current_turn)
                ready_s, busy = await_ready()
                return load_s, ready_s, busy
            finally:
                if held:
                    _release_turn(turn_root)

        if needs_loop(active_suite):
            start_qa_fn(qa_toml_path)

        smoke_failed = False
        game_down = False
        for s in suites:
            if smoke_failed or game_down:
                break
            all_results.extend(
                CaseResult(name=n, outcome="skipped", turns=0, evidence=why)
                for n, why in skipped_turn.get(s.name, [])
            )
            if not s.cases:  # an instant run's suite with turn cases only: nothing to load or run
                continue
            if s.name != active_suite.name and s.name != "smoke":
                active_suite = s
                qa_game_id = f"qa-{s.name}"
                plan_path = out_games_dir / f"qa-{s.name}-plan.json"
                plan_path.write_text("{}\n", encoding="utf-8")
                qa_toml_path = write_qa_config(
                    real_config_path,
                    s,
                    plan_path,
                    out_path=out_games_dir / f"qa-{s.name}.toml",
                    quiet=quiet,
                )
                thawed = []
                qa_cfg = load_config(qa_toml_path)
                orch = Orchestrator(qa_cfg, {})
                archive_qa_game(turn_root, qa_game_id, now_fn)
                orch.publish_bridge_config()
                orch.prepare_turn_dirs(current_turn)
                if needs_loop(s):
                    start_qa_fn(qa_toml_path)

            for i, case in enumerate(s.cases):
                case_start = time.monotonic()
                try:
                    trouble = trouble_fn()
                    if trouble is not None:
                        raise _GameDown(trouble)
                    if bench is not None and (
                        force_reload or (not world_fresh and (i == 0 or s.isolation_of(case) == "fresh"))
                    ):
                        try:
                            pending_load = reload_bench()
                        except QARunError as e:
                            down = trouble_fn()
                            raise _GameDown(down or f"the bench reload before the case failed: {e}") from e
                        reloads.append(time.monotonic() - case_start)
                        case_start = time.monotonic()
                        world_fresh = True
                    force_reload = False
                    world_fresh = False  # from here the case may change the world
                    load_info, pending_load = pending_load, None
                    busy = load_info[2] if load_info is not None else None
                    if busy is None:
                        publish_world(s, case.needs)
                    if busy is not None:
                        # never run on a busy game (live 10-31: moves "ok", nobody moved); the next
                        # case loads the bench again, whatever its isolation
                        res = CaseResult(name=case.name, outcome="fail", turns=0, evidence=busy)
                        force_reload = True
                    elif case.kind == "instant":
                        res, current_turn = _run_instant_case(
                            case=case,
                            qa_game_id=qa_game_id,
                            real_game_id=context_game_id,
                            faction=s.faction,
                            turn_root=turn_root,
                            ctrl=ctrl,
                            current_turn=current_turn,
                            trouble_fn=trouble_fn,
                            stop_qa_loop_fn=stop_qa_fn,
                            poll_interval=poll_interval,
                            turn_wait=instant_turn_wait,
                        )
                    else:
                        res, current_turn = _run_case(
                            case=case,
                            qa_game_id=qa_game_id,
                            real_game_id=context_game_id,
                            faction=s.faction,
                            turn_root=turn_root,
                            ctrl=ctrl,
                            current_turn=current_turn,
                            plan_path=plan_path,
                            qa_toml_path=qa_toml_path,
                            start_qa_loop_fn=start_qa_fn,
                            advance_turn_fn=advance_fn,
                            trouble_fn=trouble_fn,
                            stop_qa_loop_fn=stop_qa_fn,
                        )
                except _GameDown as down:
                    # live 10-30 18:34: no case can run on a crashed or hung game; restore relaunches
                    all_results.append(
                        CaseResult(name=case.name, outcome="fail", turns=down.turns, evidence=down.evidence,
                                   seconds=time.monotonic() - case_start)
                    )
                    game_down = True
                    break
                all_results.append(res.model_copy(update={
                    "seconds": time.monotonic() - case_start,
                    "reload_seconds": load_info[0] if load_info is not None else None,
                    "ready_seconds": load_info[1] if load_info is not None else None,
                }))
                if s.name == "smoke" and res.outcome != "pass":
                    smoke_failed = True
                    break
            else:
                if s.name == "smoke" and whole_smoke:
                    # every smoke case passed: a later instant-only rerun may skip smoke (--no-smoke)
                    now = now_fn()
                    (turn_root / LAST_SMOKE_FILE).write_text(json.dumps(
                        {"passed_at": now.isoformat(timespec="seconds"), "passed_epoch": now.timestamp(),
                         "kind": kind, "cases": [c.name for c in s.cases]}
                    ) + "\n", encoding="utf-8")

        report_dir_p = Path(report_dir)
        report_dir_p.mkdir(parents=True, exist_ok=True)
        stamp = now_fn().strftime("%Y-%m-%d-%H%M")
        report_path = report_dir_p / f"{stamp}-{suite_name}.md"
        report_path.write_text(
            format_report(suite_name, all_results, time.monotonic() - run_start, reloads), encoding="utf-8"
        )
        return all_results, report_path
    finally:
        # an instant case's hold, should one outlive its case, stays up into the restore: the restore
        # lifts it only once the kept save is loaded (live 10-31: lifted here, the bridge ended the
        # still-loaded bench's turn 5 with stale orders and every AI turn played out)
        if report_path is None:
            try:
                report_dir_p = Path(report_dir)
                report_dir_p.mkdir(parents=True, exist_ok=True)
                stamp = now_fn().strftime("%Y-%m-%d-%H%M")
                report_path = report_dir_p / f"{stamp}-{suite_name}.md"
                report_path.write_text(
                    format_report(suite_name, all_results, time.monotonic() - run_start, reloads),
                    encoding="utf-8",
                )
            except OSError:
                pass
        try:
            restore(
                real_config_path,
                control_factory=ctrl_factory,
                is_game_running=is_running_fn,
                relaunch_game=relaunch_fn,
                stop_loop=stop_loop_fn,
                stop_crash_watch=stop_cw_fn,
                start_real=start_real_fn,
                start_crash_watch=start_cw_fn,
                reload_timeout=reload_timeout,
                poll_interval=poll_interval,
                now_fn=now_fn,
                hang_seconds=hang_seconds,
                relaunch_timeout=relaunch_timeout,
                crash_dialog_up=raw_dialog_fn,  # restore confirms it itself
                eop_error_box=box_fn,
                dialog_confirm_seconds=dialog_confirm_seconds,
                start_bot=start_bot_fn,
            )
        except QARunError as e:
            e.report_path = report_path
            e.results = all_results
            raise


BENCH_PURPOSE = "bench-save"


def bench_save_start(
    real_config_path: Path | str,
    *,
    stop_loop: Callable[[], None] | None = None,
    stop_crash_watch: Callable[[], None] | None = None,
    start_real: Callable[[Path], None] | None = None,
    start_crash_watch: Callable[[], None] | None = None,
    now_fn: Callable[[], _dt.datetime] = _dt.datetime.now,
    running_now: Callable[[], dict[str, bool]] | None = None,
    start_bot: Callable[[Path], None] | None = None,
) -> str:
    """Step one of making the bench save: park the real run exactly as a QA run does (its loop, bot
    and crash-watch stopped, its newest save kept, the lock written), and give the bridge a config
    with no seats and no autoplay, so the new campaign a human starts next is left alone (the real
    config would end its turns and apply the real game's old orders to it). Returns what to do next."""
    real_config_path = Path(real_config_path)
    real_cfg = load_config(real_config_path)
    _rel_keep_save_path(real_cfg)
    turn_root = real_cfg.turn_root
    lock_path = turn_root / LOCK_FILE
    if lock_path.exists():
        raise QARunError(f"refusing to start: lock file already exists at {lock_path} (run `just qa-restore` first)")
    _preflight_keep_save(real_cfg.mod_save_dir, real_cfg.game_id, turn_root=turn_root)
    pm = _ProcessManager()
    running_fn, start_bot_fn = _real_process_record(pm, running_now, start_bot, stop_loop, start_real)
    _park_real(
        real_cfg, real_config_path, lock_path,
        stop_loop_fn=stop_loop or pm.stop_loop,
        stop_cw_fn=stop_crash_watch or pm.stop_crash_watch,
        start_real_fn=start_real or pm.start_real,
        start_cw_fn=start_crash_watch or pm.start_crash_watch,
        now_fn=now_fn,
        extra={"purpose": BENCH_PURPOSE},
        running_now_fn=running_fn, start_bot_fn=start_bot_fn,
    )
    atomic_write(turn_root / "bridge.txt", f"game_id={BENCH_SAVE_GAME_ID}\n")
    # the park's hold: no autoplay ends a turn under this config, and a human plays the new campaign
    _release_turn(turn_root)
    return (
        "the real run is parked and the bridge has no seats. In the game: quit to the main menu, "
        "start a new Grand Campaign as England, end the first turn, and on England's turn 1 (before "
        f"moving anything) run `{BENCH_RECIPE} record --real {real_config_path}`."
    )


def bench_save_record(
    real_config_path: Path | str,
    *,
    source: Path | str | None = None,
    faction: str = "england",
    control_factory: Callable[[Path], Control] | None = None,
    restore_fn: Callable[[Path], bool] | None = None,
    now_fn: Callable[[], _dt.datetime] = _dt.datetime.now,
    stop_loop: Callable[[], None] | None = None,
    stop_crash_watch: Callable[[], None] | None = None,
    start_real: Callable[[Path], None] | None = None,
    start_crash_watch: Callable[[], None] | None = None,
    reload_timeout: float = 180.0,
    turn_wait: float = 30.0,
    poll_interval: float = 0.5,
    running_now: Callable[[], dict[str, bool]] | None = None,
    start_bot: Callable[[Path], None] | None = None,
) -> BenchSave:
    """Step two: with the game on the new campaign's map, on `faction`'s own turn (1 or later), copy
    the save the game wrote this session (`source`, else its newest own save: the turn-start
    autosave) to the bench save, record its turn (asked of the bridge) and sha256, then restore the
    real campaign as `just qa-restore` does. The bridge can't write a save itself (M2TWEOP.saveGame
    fails live), so the bench save is the game's own, like the keep save.

    With `source` and no `start` before it (no qa.lock): the no-menu path
    (bench_save_record_no_menu), which needs no clicks."""
    real_config_path = Path(real_config_path)
    real_cfg = load_config(real_config_path)
    turn_root = real_cfg.turn_root
    lock_path = turn_root / LOCK_FILE
    if source is not None and not lock_path.exists():
        return bench_save_record_no_menu(
            real_config_path, Path(source), faction=faction, control_factory=control_factory,
            restore_fn=restore_fn, now_fn=now_fn, stop_loop=stop_loop,
            stop_crash_watch=stop_crash_watch, start_real=start_real,
            start_crash_watch=start_crash_watch, reload_timeout=reload_timeout,
            turn_wait=turn_wait, poll_interval=poll_interval,
            running_now=running_now, start_bot=start_bot,
        )
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise QARunError(
            f"no bench-save lock at {lock_path}; run `{BENCH_RECIPE} start` first, "
            f"or `{BENCH_RECIPE} record --from <save>` (no menu, no clicks)"
        ) from e
    if not isinstance(lock, dict) or lock.get("purpose") != BENCH_PURPOSE:
        raise QARunError(f"{lock_path} is a QA run's lock, not `{BENCH_RECIPE} start`'s; run `just qa-restore`")
    ctrl = (control_factory or (lambda root: Control(root)))(turn_root)
    try:
        where = ctrl.run_lua("return M.qa.current()").strip()
    except ControlTimeout as e:
        raise QARunError(f"the bridge didn't answer ({e}); is the game on the campaign map?") from e
    parts = where.split(" ")
    if len(parts) != 2 or not parts[1].isdigit():
        raise QARunError(f"can't tell the game's turn: M.qa.current() -> {where!r}")
    if parts[0] != faction:
        raise QARunError(f"it is {parts[0]}'s turn, not {faction}'s; record on {faction}'s own turn")
    turn = int(parts[1])
    if turn < 1:
        raise QARunError(f"the campaign is on turn {turn}; end the first turn and record on turn 1 or later")
    started = float(lock.get("started_epoch") or 0.0)
    src = Path(source) if source is not None else newest_real_save(real_cfg.mod_save_dir)
    if src is None or not src.exists():
        raise QARunError(f"no save to record in {real_cfg.mod_save_dir}; save the game in the game, then pass --from")
    if source is None and src.stat().st_mtime <= started:
        raise QARunError(
            f"{src.name} is older than `{BENCH_RECIPE} start`: the game wrote no save on the new "
            "campaign yet; save it in the game (Save Game) and pass --from <that file>"
        )
    save, record = bench_save_paths(real_cfg)
    tmp = save.with_name(f".{save.name}.tmp")
    shutil.copy2(src, tmp)
    os.replace(tmp, save)
    digest = _sha256(save)
    atomic_write(record, json.dumps({
        "save": save.name,
        "turn": turn,
        "faction": faction,
        "sha256": digest,
        "source": src.name,
        "recorded_at": now_fn().isoformat(timespec="seconds"),
    }, indent=2) + "\n")
    bench = load_bench_save(real_cfg)
    (restore_fn or restore)(real_config_path)
    return bench


def _await_turn_of(
    ctrl: Control,
    faction: str,
    *,
    timeout: float,
    poll_interval: float,
) -> int:
    """The turn, once M.qa.current() says it is `faction`'s ("<faction> <turn>"); QARunError
    when it doesn't within `timeout` s (the save is another faction's, or not on its own turn)."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            where = ctrl.run_lua("return M.qa.current()").strip()
        except ControlTimeout as e:
            raise QARunError(f"the bridge didn't answer ({e}); is the game on the campaign map?") from e
        parts = where.split(" ")
        if len(parts) == 2 and parts[1].isdigit() and parts[0] == faction:
            return int(parts[1])
        if time.monotonic() >= deadline:
            if len(parts) != 2 or not parts[1].isdigit():
                raise QARunError(f"can't tell the game's turn: M.qa.current() -> {where!r}")
            raise QARunError(
                f"the loaded save is on {parts[0]}'s turn, not {faction}'s, after {timeout:g} s; "
                f"record a save made on {faction}'s own turn"
            )
        time.sleep(poll_interval)


def bench_save_record_no_menu(
    real_config_path: Path | str,
    source: Path | str,
    *,
    faction: str = "england",
    control_factory: Callable[[Path], Control] | None = None,
    restore_fn: Callable[[Path], bool] | None = None,
    now_fn: Callable[[], _dt.datetime] = _dt.datetime.now,
    stop_loop: Callable[[], None] | None = None,
    stop_crash_watch: Callable[[], None] | None = None,
    start_real: Callable[[Path], None] | None = None,
    start_crash_watch: Callable[[], None] | None = None,
    reload_timeout: float = 180.0,
    turn_wait: float = 30.0,
    poll_interval: float = 0.5,
    running_now: Callable[[], dict[str, bool]] | None = None,
    start_bot: Callable[[Path], None] | None = None,
) -> BenchSave:
    """Make the bench save from an existing save, with no menu and no clicks (`just qa-bench-save
    record --from <save>` with no `start` before it): park the real run as `start` does (loop, bot
    and crash-watch stopped, its newest save kept, the lock written), give the bridge the seatless
    bench config, copy `source` to the bench save, load it through EOP (M.qa.load: loadGame), read
    its turn and faction from the loaded game (M.qa.current, which must say `faction` and a turn of
    1 or later), record turn, faction and sha256, and restore the real campaign. Any failure after
    the park restores too, then raises. The whole of it is a no-click run (PARLEY_NO_X_INPUT=1);
    the restore's relaunch of a crashed game makes no clicks, so it is allowed.

    The save to use: a copy of an existing England campaign's save on England's own turn 1 or later
    (an autosave is written at the start of the player's turn). If the record fails after the copy,
    the bench save no longer matches its old record and runs refuse it until a record succeeds."""
    with no_click_run():
        real_config_path = Path(real_config_path)
        real_cfg = load_config(real_config_path)
        rel = _rel_save_path(real_cfg, BENCH_SAVE_NAME)
        _rel_keep_save_path(real_cfg)
        turn_root = real_cfg.turn_root
        lock_path = turn_root / LOCK_FILE
        src = Path(source)
        if not src.is_file():
            raise QARunError(f"no save at {src}")
        if src.suffix.lower() != ".sav":
            raise QARunError(f"{src} is not a .sav")
        if lock_path.exists():
            raise QARunError(f"refusing to start: lock file already exists at {lock_path} (run `just qa-restore` first)")
        _preflight_keep_save(real_cfg.mod_save_dir, real_cfg.game_id, turn_root=turn_root)
        pm = _ProcessManager()
        running_fn, start_bot_fn = _real_process_record(pm, running_now, start_bot, stop_loop, start_real)
        lock_payload, _ = _park_real(
            real_cfg, real_config_path, lock_path,
            stop_loop_fn=stop_loop or pm.stop_loop,
            stop_cw_fn=stop_crash_watch or pm.stop_crash_watch,
            start_real_fn=start_real or pm.start_real,
            start_cw_fn=start_crash_watch or pm.start_crash_watch,
            now_fn=now_fn,
            extra={"purpose": BENCH_PURPOSE, "no_menu": True, "bench_save": rel},
            running_now_fn=running_fn, start_bot_fn=start_bot_fn,
        )
        restore_call = restore_fn or restore
        save, record = bench_save_paths(real_cfg)
        try:
            # the loaded campaign is left alone: no seats, no autoplay, no old orders applied
            atomic_write(turn_root / "bridge.txt", f"game_id={BENCH_SAVE_GAME_ID}\n")
            if src.resolve() != save.resolve():
                tmp = save.with_name(f".{save.name}.tmp")
                shutil.copy2(src, tmp)
                os.replace(tmp, save)
            ctrl = (control_factory or (lambda root: Control(root)))(turn_root)
            log_path = turn_root / LOG_FILE
            offset = _log_size(log_path)
            line = _load_line(save, rel)
            try:
                lua_res = ctrl.run_lua(line)
            except ControlTimeout as e:
                raise QARunError(f"loading {rel}: {e}") from e
            lock_payload["bench_loaded"] = True  # from here the game may be on the bench's campaign
            lock_path.write_text(json.dumps(lock_payload, indent=2) + "\n", encoding="utf-8")
            _await_campaign_load(lua_res, log_path, offset, timeout=reload_timeout, poll_interval=poll_interval)
            turn = _await_turn_of(ctrl, faction, timeout=turn_wait, poll_interval=poll_interval)
            if turn < 1:
                raise QARunError(f"the save is on turn {turn}; record a save on turn 1 or later")
            atomic_write(record, json.dumps({
                "save": save.name,
                "turn": turn,
                "faction": faction,
                "sha256": _sha256(save),
                "source": src.name,
                "made": "no-menu (loaded through EOP, no clicks)",
                "recorded_at": now_fn().isoformat(timespec="seconds"),
            }, indent=2) + "\n")
            bench = load_bench_save(real_cfg)
        except BaseException as e:
            try:
                restore_call(real_config_path)
            except QARunError as restore_err:
                raise QARunError(f"{e}; the restore after it failed too: {restore_err}") from e
            raise
        restore_call(real_config_path)
        return bench
