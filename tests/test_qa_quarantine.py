"""parley/qa/quarantine.py and games/quarantine.toml (STANDARDS flaky-quarantine)."""

from pathlib import Path

from parley.qa import quarantine
from parley.qa.runner import CaseResult


def _r(name, outcome):
    return CaseResult(name=name, outcome=outcome, turns=0, evidence="")


def test_a_quarantined_failure_is_reported_but_does_not_fail_the_run(tmp_path):
    q = tmp_path / "q.toml"
    q.write_text('[cases]\nflaky_case = "a roll the bench can\'t fix; since 11-05"\n')
    held = quarantine.load(q)
    assert held == {"flaky_case": "a roll the bench can't fix; since 11-05"}
    red, quiet = quarantine.split_failures([_r("flaky_case", "fail"), _r("ok", "pass")], held)
    assert red == [] and [r.name for r in quiet] == ["flaky_case"]
    red, _ = quarantine.split_failures([_r("flaky_case", "fail"), _r("real_bug", "fail")], held)
    assert [r.name for r in red] == ["real_bug"]


def test_just_qa_exits_0_when_only_a_quarantined_case_failed(tmp_path, monkeypatch, capsys):
    import parley.qa.__main__ as qa_main
    report = tmp_path / "report.md"
    report.write_text("| flaky_case | fail |\n")
    results = [_r("flaky_case", "fail"), _r("ok", "pass")]
    monkeypatch.setattr(qa_main, "run_suite", lambda *a, **k: (results, report))
    monkeypatch.setattr(quarantine, "load", lambda path=None: {"flaky_case": "a roll; since 11-05"})
    assert qa_main.main(["run", "smoke", "--real", str(tmp_path / "real.toml")]) == 0
    assert "quarantined (not failing the run): flaky_case: a roll; since 11-05" in capsys.readouterr().out
    results.append(_r("real_bug", "fail"))
    assert qa_main.main(["run", "smoke", "--real", str(tmp_path / "real.toml")]) == 1


def test_a_quarantined_case_that_passes_is_neither_red_nor_listed():
    red, quiet = quarantine.split_failures([_r("flaky_case", "pass")], {"flaky_case": "a roll"})
    assert red == [] and quiet == []


def test_a_missing_or_broken_list_quarantines_nothing(tmp_path):
    assert quarantine.load(tmp_path / "none.toml") == {}
    (tmp_path / "bad.toml").write_text("[cases\n")
    assert quarantine.load(tmp_path / "bad.toml") == {}
    (tmp_path / "empty.toml").write_text("# nothing held\n[cases]\n")
    assert quarantine.load(tmp_path / "empty.toml") == {}
    (tmp_path / "no_table.toml").write_text('note = "no cases table"\n')
    assert quarantine.load(tmp_path / "no_table.toml") == {}


def test_the_committed_list_loads_and_names_only_real_cases():
    from parley.qa.cases import load_suite
    names = {c.name for p in (Path(__file__).parent.parent / "games" / "qa").glob("*.toml")
             for c in load_suite(p).cases}
    held = quarantine.load()
    assert set(held) <= names, set(held) - names
