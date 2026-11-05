from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import preflight_interrupts as pi


def _setup_fake_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    qa_dir = tmp_path / "games" / "qa"
    qa_dir.mkdir(parents=True)
    events = tmp_path / "games" / "interrupts.toml"
    runs = tmp_path / "runs" / "qa"
    runs.mkdir(parents=True)
    monkeypatch.setattr(pi, "ROOT", tmp_path)
    monkeypatch.setattr(pi, "QA_DIR", qa_dir)
    monkeypatch.setattr(pi, "EVENTS", events)
    monkeypatch.setattr(pi, "RUNS", runs)
    monkeypatch.setattr(pi, "EXPLAINED", tmp_path / "games" / "no-click-explained.toml")
    return qa_dir, events


HEADER = "| case | outcome | turns | evidence | time | reload |\n| --- | --- | --- | --- | --- | --- |\n"


def _report(runs: Path, name: str, rows: list[tuple[str, str]], age: int = 0) -> Path:
    """A bench report as parley/qa writes it (runs/qa/<stamp>-<suite>.md); `age` seconds old."""
    import os
    import time

    p = runs / name
    p.write_text("# QA Report: x\n\n" + HEADER + "".join(f"| {c} | {o} | 0 | ev | 1 s |  |\n" for c, o in rows),
                 encoding="utf-8")
    t = time.time() - age
    os.utime(p, (t, t))
    return p


def test_qa_args() -> None:
    assert pi.qa_args("just qa field") == ["field"]
    assert pi.qa_args("PARLEY_NO_X_INPUT=1 just qa all kind=instant") == ["all", "kind=instant"]
    assert pi.qa_args("just qa field && echo done") == ["field"]
    assert pi.qa_args("just qa-restore") is None
    assert pi.qa_args("echo hi") is None


def test_parse_run() -> None:
    r1 = pi.parse_run(["field", "kind=instant", "case=alpha", "no-smoke"])
    assert r1 == {"suite": "field", "cases": ["alpha"], "instant": True, "smoke": False}

    r2 = pi.parse_run(["--real", "games/local/x.toml", "--kind", "instant", "--case", "beta", "--no-smoke", "siege"])
    assert r2 == {"suite": "siege", "cases": ["beta"], "instant": True, "smoke": False}


def test_turn_cases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    qa_dir, _ = _setup_fake_tree(tmp_path, monkeypatch)
    (qa_dir / "smoke.toml").write_text(
        '[[cases]]\nname = "boot"\nkind = "instant"\n'
        '[[cases]]\nname = "end_turn"\n',
        encoding="utf-8",
    )
    (qa_dir / "field.toml").write_text(
        '[[cases]]\nname = "fast"\nkind = "instant"\n'
        '[[cases]]\nname = "march"\n'
        '[[cases]]\nname = "camp"\n',
        encoding="utf-8",
    )

    run_default = pi.parse_run(["field"])
    assert pi.turn_cases(run_default) == ["smoke/end_turn", "field/march", "field/camp"]

    run_no_smoke = pi.parse_run(["field", "no-smoke"])
    assert pi.turn_cases(run_no_smoke) == ["field/march", "field/camp"]

    run_case_filter = pi.parse_run(["field", "case=camp"])
    assert pi.turn_cases(run_case_filter) == ["smoke/end_turn", "field/camp"]

    run_all = pi.parse_run(["all"])
    assert pi.turn_cases(run_all) == ["field/march", "field/camp", "smoke/end_turn"]


def test_unhandled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_fake_tree(tmp_path, monkeypatch)
    src = tmp_path / "src" / "guard.lua"
    src.parent.mkdir(parents=True)
    src.write_text("function suppress_pope()\n  return true\nend\n", encoding="utf-8")

    assert pi.unhandled({"e_ruled": {"what": "Ruled out event", "ruled_out": "never triggers in bench"}}) == []
    _report(pi.RUNS, "2026-11-01-0600-instant.md", [("quiet_world_held", "pass")])
    assert pi.unhandled(
        {"e_held_ok": {"what": "Held event", "held_by": "pope guard", "proof": ["src/guard.lua::suppress_pope"],
                       "bench": "instant/quiet_world_held"}}
    ) == []

    unbuilt = pi.unhandled(
        {"e_unbuilt": {"what": "Unbuilt event", "held_by": "missing guard", "proof": ["src/guard.lua::nonexistent_fn"]}}
    )
    assert len(unbuilt) == 1
    assert "isn't built" in unbuilt[0]

    no_proof = pi.unhandled({"e_noproof": {"what": "No proof event", "held_by": "planned guard"}})
    assert len(no_proof) == 1
    assert "no proof" in no_proof[0]

    neither = pi.unhandled({"e_neither": {"what": "Unhandled event"}})
    assert len(neither) == 1
    assert "nothing holds it off" in neither[0]


def test_main_fake_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    qa_dir, events = _setup_fake_tree(tmp_path, monkeypatch)
    (qa_dir / "smoke.toml").write_text(
        '[[cases]]\nname = "boot"\nkind = "instant"\n',
        encoding="utf-8",
    )
    (qa_dir / "field.toml").write_text(
        '[[cases]]\nname = "march"\n',
        encoding="utf-8",
    )
    events.write_text(
        '[events.papal_election]\nwhat = "Papal election"\n',
        encoding="utf-8",
    )

    assert pi.main(["just qa field kind=instant"]) == 0
    assert pi.main(["echo not a qa command"]) == 0
    assert pi.main(["just qa smoke"]) == 0

    # phase order first: no no-click run on record refuses a turn run before any event is read
    capsys.readouterr()
    assert pi.main(["just qa field"]) == 1
    assert "no no-click run" in capsys.readouterr().out
    clean = _report(pi.RUNS, "2026-11-01-0442-all.md", [("move_army", "pass"), ("siege_storm", "skipped")])

    assert pi.main(["just qa field"]) == 1
    out = capsys.readouterr().out
    assert "papal_election" in out

    events.write_text(
        '[events.papal_election]\nwhat = "Papal election"\nruled_out = "no pope in bench"\n',
        encoding="utf-8",
    )
    assert pi.main(["just qa field"]) == 0
    clean.unlink()  # and with no no-click run on record, even a fully handled list is refused
    assert pi.main(["just qa field"]) == 1


# --- the held event needs a bench pass, not only code (11-01: #342/#344/#345 merged on fake tests) ---

def _held(**extra) -> dict:
    return {"e": {"what": "Held event", "held_by": "guard", "proof": ["src/guard.lua::suppress_pope"], **extra}}


def _guard(tmp_path: Path) -> None:
    src = tmp_path / "src" / "guard.lua"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("function suppress_pope() end\n", encoding="utf-8")


def test_a_hold_proven_only_in_code_is_not_held(tmp_path, monkeypatch) -> None:
    _setup_fake_tree(tmp_path, monkeypatch)
    _guard(tmp_path)
    [p] = pi.unhandled(_held())
    assert "not proven on the bench" in p


def test_a_hold_whose_bench_case_never_passed_is_not_held(tmp_path, monkeypatch) -> None:
    _setup_fake_tree(tmp_path, monkeypatch)
    _guard(tmp_path)
    [p] = pi.unhandled(_held(bench="instant/quiet_world_held"))
    assert "no bench run of instant/quiet_world_held" in p
    _report(pi.RUNS, "2026-11-01-0600-instant.md", [("quiet_world_held", "fail")])
    [p] = pi.unhandled(_held(bench="instant/quiet_world_held"))
    assert "newest bench run of instant/quiet_world_held: fail" in p


def test_the_newest_bench_run_decides(tmp_path, monkeypatch) -> None:
    # a pass, then a later fail: the hold has regressed
    _setup_fake_tree(tmp_path, monkeypatch)
    _guard(tmp_path)
    _report(pi.RUNS, "2026-11-01-0600-all.md", [("quiet_world_held", "pass")], age=100)
    _report(pi.RUNS, "2026-11-01-0700-instant.md", [("quiet_world_held", "fail")])
    assert pi.unhandled(_held(bench="instant/quiet_world_held"))
    # a report of another suite with a same-named case doesn't count
    _report(pi.RUNS, "2026-11-01-0800-navy.md", [("quiet_world_held", "pass")])
    assert pi.unhandled(_held(bench="instant/quiet_world_held"))
    _report(pi.RUNS, "2026-11-01-0900-all.md", [("quiet_world_held", "pass")])
    assert pi.unhandled(_held(bench="instant/quiet_world_held")) == []


# --- phase order: no turn work while the newest no-click run has fails or inconclusives ---

def test_phase_order_reads_the_newest_all_report(tmp_path, monkeypatch) -> None:
    _setup_fake_tree(tmp_path, monkeypatch)
    _report(pi.RUNS, "2026-11-01-0442-all.md",
            [("marry_foreign_general", "fail"), ("crossing_in_one_turn", "inconclusive"),
             ("repair_queued", "inconclusive"), ("move_army", "pass"), ("siege_storm", "skipped")], age=100)
    problems = pi.phase_open()
    assert [p.split(":")[0] for p in problems] == [
        "- marry_foreign_general", "- crossing_in_one_turn", "- repair_queued"]
    # a newer clean run supersedes it; a newer single-suite run doesn't
    _report(pi.RUNS, "2026-11-01-0500-navy.md", [("crossing_in_one_turn", "pass")], age=50)
    assert len(pi.phase_open()) == 3
    _report(pi.RUNS, "2026-11-01-0600-all.md", [("move_army", "pass")])
    assert pi.phase_open() == []


def test_phase_order_explained_cases_pass(tmp_path, monkeypatch) -> None:
    _setup_fake_tree(tmp_path, monkeypatch)
    _report(pi.RUNS, "2026-11-01-0442-all.md", [("repair_queued", "inconclusive"), ("x", "fail")])
    pi.EXPLAINED.write_text('[cases.repair_queued]\nwhy = "chance: the game offers no repair some loads"\n',
                            encoding="utf-8")
    assert [p.split(":")[0] for p in pi.phase_open()] == ["- x"]


def test_phase_order_refuses_without_a_report_or_rows(tmp_path, monkeypatch) -> None:
    _setup_fake_tree(tmp_path, monkeypatch)
    [p] = pi.phase_open()
    assert "no no-click run" in p
    (pi.RUNS / "2026-11-01-0442-all.md").write_text("# QA Report: all\n\nnothing\n", encoding="utf-8")
    [p] = pi.phase_open()
    assert "no case rows" in p


def test_phase_order_gates_only_turn_runs(tmp_path, monkeypatch, capsys) -> None:
    qa_dir, events = _setup_fake_tree(tmp_path, monkeypatch)
    (qa_dir / "smoke.toml").write_text('[[cases]]\nname = "boot"\nkind = "instant"\n', encoding="utf-8")
    (qa_dir / "field.toml").write_text('[[cases]]\nname = "march"\n', encoding="utf-8")
    events.write_text('[events.e]\nwhat = "E"\nruled_out = "x"\n', encoding="utf-8")
    _report(pi.RUNS, "2026-11-01-0442-all.md", [("marry_foreign_general", "fail")])
    assert pi.main(["just qa field kind=instant"]) == 0  # the no-click work that clears it always runs
    capsys.readouterr()
    assert pi.main(["just qa field"]) == 1
    out = capsys.readouterr().out
    assert "marry_foreign_general" in out and "no-click" in out


def test_main_real_repo() -> None:
    assert pi.main(["just qa all kind=instant"]) == 0
    assert pi.main(["just qa-restore"]) == 0
