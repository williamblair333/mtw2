"""The QA bench's load hygiene (live 10-31, phase1-run2): the restore keeps the turn held until the
kept save is loaded, the readiness gate after each bench load (_await_ready: the bench faction's
turn, then a canary that must move), and each case's bench-load seconds in the report."""

from __future__ import annotations

from pathlib import Path

from parley.qa.runner import (
    QA_HOLD_REASON,
    SLOW_LOAD_SECONDS,
    CaseResult,
    _await_ready,
    format_report,
    restore,
)
from test_qa_bench_save import BenchHarness, _game, _run, _suites
from test_qa_runner import _write_real_game


# --- B1: the restore holds the turn until the kept save is loaded ------------------------------


def test_the_restore_keeps_the_turn_held_until_the_kept_save_is_loaded(tmp_path: Path):
    # live 10-31: "qa: load ok: ...parley_keep_scratch.sav", then at the same second "resumed" and
    # "autoplay: ending turn 5": the hold went before the load, and the bridge ended the bench's turn
    real_toml, turn_root, _ = _game(tmp_path)
    h = BenchHarness(turn_root)
    held_at: dict[str, list[bool]] = {"bench": [], "keep": []}

    def watch(self, line):
        if "M.qa.load(" in line:
            held_at["bench" if "parley_bench" in line else "keep"].append((turn_root / "paused.txt").exists())
        return BenchHarness._lua(self, line)

    h.on_lua = watch
    results, _ = _run(tmp_path, real_toml, h)
    assert [r.outcome for r in results] == ["pass", "pass"], results
    assert held_at["keep"] == [True]  # held while the kept save loads
    assert all(held_at["bench"]), held_at  # every bench load held too
    assert not (turn_root / "paused.txt").exists()  # lifted once the real turn loaded
    assert not (turn_root / "qa.lock").exists()


def test_a_restore_whose_load_fails_keeps_the_hold_with_the_lock(tmp_path: Path):
    real_toml, turn_root, mod_save_dir = _game(tmp_path)
    h = BenchHarness(turn_root)

    def keep_load_fails(self, line):
        if "M.qa.load(" in line and "parley_keep" in line:
            self.append_log("qa: load ok: x")
            self.append_log("bridge loaded campaign at turn 3")  # not the real turn 40
            return "ok"
        return BenchHarness._lua(self, line)

    h.on_lua = keep_load_fails
    try:
        _run(tmp_path, real_toml, h)
    except Exception as e:  # QARunError: the restore failed
        assert "restore failed" in str(e)
    else:
        raise AssertionError("the restore should have failed")
    assert (turn_root / "qa.lock").exists()
    # the game is on some other turn: the real campaign's turns stay held until qa-restore loads it
    assert (turn_root / "paused.txt").read_text().startswith(QA_HOLD_REASON)


def test_restore_without_a_lock_still_lifts_a_left_hold(tmp_path: Path):
    real_toml, turn_root, _ = _write_real_game(tmp_path)
    (turn_root / "paused.txt").write_text(QA_HOLD_REASON + " (the game was relaunched ...)\n")
    assert restore(real_toml) is False
    assert not (turn_root / "paused.txt").exists()


# --- C: the readiness gate after each bench load ----------------------------------------------


def _extra_shared() -> str:
    return (
        '\n[[cases]]\nname = "shared_one"\nisolation = "shared"\n'
        'setup = [\'M.qa.spawn_agent("england", "spy", 1, 2, "B")\']\n'
        'expect = [{ log = "qa: spawn_agent ok" }]\n'
    )


def test_a_busy_game_fails_the_case_and_the_next_case_loads_the_bench_again(tmp_path: Path):
    real_toml, turn_root, _ = _game(tmp_path)
    h = BenchHarness(turn_root)
    checks: list[tuple[str, bool]] = []

    def ready(ctrl, faction, log, trouble):
        checks.append((faction, (turn_root / "paused.txt").exists()))
        # the second load (covert's, after smoke's case) leaves the game busy
        return "game busy: canary stayed at 5,5" if len(checks) == 2 else None

    results, report = _run(tmp_path, real_toml, h, suites_dir=_suites(tmp_path, _extra_shared()),
                           ready_check=ready)
    assert [(r.name, r.outcome) for r in results] == [
        ("spawn", "pass"), ("near_town", "fail"), ("shared_one", "pass")], results
    assert results[1].evidence == "game busy: canary stayed at 5,5"
    # the busy case never ran (its spawn never went out); "shared" or not, the next case reloaded
    seq = [("load" if "parley_bench" in c else "keep" if "M.qa.load(" in c else "spawn")
           for c in h.lua_calls if "M.qa.load(" in c or "spawn_agent" in c]
    assert seq == ["load", "spawn", "load", "load", "spawn", "keep"], seq
    # one gate after every bench load, each with the turn held, for the bench faction
    assert checks == [("england", True)] * 3
    assert all(r.reload_seconds is not None for r in results)
    assert "| reload |" in report.read_text()


def test_without_an_injected_gate_a_test_control_runs_none(tmp_path: Path):
    real_toml, turn_root, _ = _game(tmp_path)
    h = BenchHarness(turn_root)
    results, _ = _run(tmp_path, real_toml, h)
    assert [r.outcome for r in results] == ["pass", "pass"]
    assert not any("canary" in c for c in h.lua_calls)


class _Canary:
    """M.qa.current / canary / army / canary_gone of a game whose canaries start to move after
    `stuck` of them stayed put."""

    def __init__(self, stuck: int = 0, current: str = "england 10", removed: str = "gone"):
        self.stuck, self.current, self.removed = stuck, current, removed
        self.lines: list[str] = []
        self.spawned = 0
        self.gone: list[str] = []

    def log_offset(self) -> int:
        return 0

    def run_lua(self, line: str) -> str:
        self.lines.append(line)
        if "M.qa.current()" in line:
            return self.current
        if "M.qa.canary(" in line:
            self.spawned += 1
            return f"Canary {self.spawned}|5,5|6,5"
        if "M.qa.army(" in line:
            moved = self.spawned > self.stuck
            return ("6,5" if moved else "5,5") + " fleet=no carrying=- men=- aboard=-"
        if "M.qa.canary_gone(" in line:
            self.gone.append(line)
            return self.removed
        return "ok"


def test_await_ready_passes_once_a_canary_moves_and_removes_it(tmp_path: Path):
    g = _Canary()
    assert _await_ready(g, "england", tmp_path / "log", None, timeout=5, canary_window=1, poll_interval=0) is None
    assert g.spawned == 1 and g.gone == ['return M.qa.canary_gone("england", "Canary 1")']


def test_await_ready_tries_new_canaries_until_one_moves(tmp_path: Path):
    g = _Canary(stuck=2)
    assert _await_ready(g, "england", tmp_path / "log", None, timeout=5, canary_window=0.05,
                        poll_interval=0.01) is None
    assert g.spawned == 3 and len(g.gone) == 3  # every canary removed, moved or not


def test_await_ready_gives_up_as_game_busy_with_the_evidence(tmp_path: Path):
    g = _Canary(stuck=10 ** 6)
    why = _await_ready(g, "england", tmp_path / "log", None, timeout=0.2, canary_window=0.05, poll_interval=0.01)
    assert why is not None and why.startswith("game busy: no readiness canary moved within 0.2 s")
    assert "stayed at 5,5" in why and "england 10" in why
    assert len(g.gone) == g.spawned


def test_await_ready_waits_for_the_bench_factions_turn_first(tmp_path: Path):
    g = _Canary(current="france 10")
    why = _await_ready(g, "england", tmp_path / "log", None, timeout=0.05, poll_interval=0.01)
    assert why is not None and why.startswith("game busy: not england's turn") and g.spawned == 0


def test_a_canary_left_on_the_map_is_game_busy_not_ready(tmp_path: Path):
    g = _Canary(removed="left")
    why = _await_ready(g, "england", tmp_path / "log", None, timeout=5, canary_window=1,
                       canary_gone_window=0.05, poll_interval=0.01)
    assert why is not None and "wasn't removed" in why
    # the first call kills; every later one only looks
    assert g.gone[0].endswith('"Canary 1")') and all(c.endswith('"Canary 1", true)') for c in g.gone[1:])


def test_a_canary_whose_kill_lands_late_is_ready(tmp_path: Path):
    # live 10-31 14:33: canary_gone said "left" in the call that killed it; the kill lands a moment later
    g = _Canary()
    g.run_lua_base = g.run_lua  # type: ignore[attr-defined]

    def late(line: str) -> str:
        if "M.qa.canary_gone(" in line:
            g.gone.append(line)
            return "gone" if len(g.gone) >= 3 else "left"
        return g.run_lua_base(line)  # type: ignore[attr-defined]

    g.run_lua = late  # type: ignore[method-assign]
    assert _await_ready(g, "england", tmp_path / "log", None, timeout=5, canary_window=1,
                        canary_gone_window=2, poll_interval=0.01) is None
    assert g.spawned == 1 and g.gone == ['return M.qa.canary_gone("england", "Canary 1")',
                                         'return M.qa.canary_gone("england", "Canary 1", true)',
                                         'return M.qa.canary_gone("england", "Canary 1", true)']


def test_a_canary_that_cannot_start_is_game_busy(tmp_path: Path):
    g = _Canary()
    g.run_lua = lambda line: "england 10" if "current" in line else "nil"  # type: ignore[method-assign]
    why = _await_ready(g, "england", tmp_path / "log", None, timeout=1, poll_interval=0)
    assert why is not None and why.startswith("game busy: the readiness canary didn't start")


# --- D: each case's bench-load seconds in the report ------------------------------------------


def test_the_report_shows_each_cases_reload_and_flags_slow_loads():
    rs = [
        CaseResult(name="a", outcome="pass", turns=0, evidence="e", seconds=3.0, reload_seconds=4.1, ready_seconds=0.4),
        CaseResult(name="b", outcome="pass", turns=0, evidence="e", seconds=3.0),
        CaseResult(name="c", outcome="fail", turns=0, evidence="game busy: x", seconds=1.0,
                   reload_seconds=SLOW_LOAD_SECONDS + 55, ready_seconds=180.0),
    ]
    text = format_report("field", rs)
    assert "| case | outcome | turns | evidence | time | reload |" in text
    assert "| a | pass | 0 | e | 3.0 s | 4.1 s |" in text
    assert "| b | pass | 0 | e | 3.0 s |  |" in text
    assert "| c | fail | 0 | game busy: x | 1.0 s | 75.0 s slow load + ready 3 min 0 s |" in text
    assert "Slow loads (over 20 s; the case before each likely left the game busy): c (75.0 s)" in text
