import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from click_coverage import check  # noqa: E402

MAP = """
[[kinds]]
action = "open"
kind = "marriage"
cases = ["family/forced_wife"]

[[kinds]]
action = "open"
kind = "minimized"
cases = []
gap = "no case"
"""


def _setup(tmp_path, log, reports):
    (tmp_path / "t-turns.log").write_text(log)
    rd = tmp_path / "qa"
    rd.mkdir()
    for name, text in reports.items():
        (rd / name).write_text(text)
    (tmp_path / "map.toml").write_text(MAP)
    return [str(tmp_path / "t-turns.log")], rd, tmp_path / "map.toml"


def _report(kind, outcome):
    head = "# QA Report: family\n\n" + (f"Run kind: {kind}\n\n" if kind else "")
    return head + "| case | outcome | turns |\n| --- | --- | --- |\n" + f"| forced_wife | {outcome} | 1 |\n"


OFFER = "2026-11-20 13:22:46 INFO x-input: action=open kind=marriage event=offer id=p1\n"


def test_a_click_kind_with_a_noclick_pass_is_covered(tmp_path):
    report, ok = check(*_setup(tmp_path, OFFER, {"2026-11-21-1200-family.md": _report("noclick", "pass")}))
    assert report[0].startswith("ok") and "kind=marriage" in report[0], report
    assert not ok  # the map's minimized entry is still a gap, logged or not


def test_a_pass_outside_a_noclick_run_does_not_count(tmp_path):
    # the 11-21 miss: a case that passed with clicks allowed proves nothing about no-click play
    report, ok = check(*_setup(tmp_path, OFFER, {"2026-11-21-1200-family.md": _report(None, "pass")}))
    assert not ok and "never run noclick" in report[0]


def test_the_newest_noclick_report_wins(tmp_path):
    report, ok = check(*_setup(tmp_path, OFFER, {"2026-11-21-1200-family.md": _report("noclick", "pass"),
                                                 "2026-11-21-1300-family.md": _report("noclick", "fail")}))
    assert not ok and "forced_wife=fail" in report[0]


def test_a_known_gap_and_an_unmapped_kind_fail(tmp_path):
    log = ("x-input: action=open kind=minimized id=p2\n"
           "x-input: action=press kind=escape id=p3\n")
    report, ok = check(*_setup(tmp_path, log, {}))
    assert not ok
    assert any(r.startswith("GAP") for r in report) and any(r.startswith("UNMAPPED") for r in report)


def test_a_mapped_kind_gone_from_the_logs_is_still_checked(tmp_path):
    # live 11-21: QA restores rotate the turn log and the old ones go; the marriage clicks vanished
    report, ok = check(*_setup(tmp_path, "", {}))
    assert not ok
    assert any("kind=marriage" in r and "never run noclick" in r for r in report), report
    assert any(r.startswith("GAP") and "kind=minimized" in r for r in report), report


def test_the_real_map_parses_and_names_cases_as_suite_slash_case():
    import tomllib
    root = Path(__file__).resolve().parents[1]
    kinds = tomllib.loads((root / "games/click-coverage.toml").read_text())["kinds"]
    for k in kinds:
        assert k.get("cases") or k.get("gap"), k
        for c in k.get("cases", []):
            suite, case = c.split("/")
            assert f'name = "{case}"' in (root / f"games/qa/{suite}.toml").read_text(), c
