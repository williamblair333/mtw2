from pathlib import Path

from parley.qa.summary import main, summarize


def _setup_sample_reports(tmp_path: Path) -> None:
    # 1. Older report for smoke suite
    older_smoke = tmp_path / "2026-11-04-1000-smoke.md"
    older_smoke.write_text(
        "# QA Report: smoke\n\n"
        "| case | outcome | turns | evidence | time | reload |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        "| old-case | pass | 1 | ok | 1.0 s | |\n\n"
        "Total: 1.0 s for 1 case(s) (restore not included)\n",
        encoding="utf-8",
    )

    # 2. Newer report for smoke suite (newer report should win)
    newer_smoke = tmp_path / "2026-11-05-1200-smoke.md"
    newer_smoke.write_text(
        "# QA Report: smoke\n\n"
        "| case | outcome | turns | evidence | time | reload |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        "| instant-pass | pass | 0 | passed clean | 0.5 s | |\n"
        "| instant-skip | skipped | 0 | not required | | |\n"
        "| field-fail | fail | 2 | battle ended unexpectedly | 3.2 s | |\n\n"
        "Total: 3.7 s for 3 case(s) (restore not included)\n",
        encoding="utf-8",
    )

    # 3. Report for all suite with multiple outcomes and long evidence
    long_ev = "E" * 200
    all_report = tmp_path / "2026-11-05-1100-all.md"
    all_report.write_text(
        "# QA Report: all\n\n"
        "| case | outcome | turns | evidence | time | reload |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        "| case-pass-1 | pass | 1 | ok | 1.1 s | |\n"
        "| case-pass-2 | pass | 2 | ok | 2.2 s | |\n"
        "| case-fail-1 | fail | 1 | error encountered | 4.0 s | |\n"
        "| case-inconc | inconclusive | 3 | ambiguous state detected | 10.0 s | |\n"
        "| case-skip-1 | skipped | 0 | not applicable | | |\n"
        "| case-skip-2 | skipped | 0 | conditional skip | | |\n"
        f"| case-fail-long | fail | 1 | {long_ev} | 1.0 s | |\n\n"
        "Total: 37 min 40 s for 7 case(s) (restore not included)\n",
        encoding="utf-8",
    )

    # 4. Report with no markdown table
    no_table = tmp_path / "2026-11-05-0900-notable.md"
    no_table.write_text(
        "# QA Report: notable\n\n"
        "Run aborted before execution began.\n\n"
        "Total: 0.0 s for 0 case(s) (restore not included)\n",
        encoding="utf-8",
    )


def test_newest_report_wins(tmp_path: Path):
    _setup_sample_reports(tmp_path)
    out = summarize(tmp_path, suites=["smoke"])
    lines = out.splitlines()

    assert len(lines) == 2
    assert "2026-11-05-1200-smoke.md" in lines[0]
    assert "2026-11-04-1000-smoke.md" not in out
    assert "old-case" not in out
    assert lines[1] == "    field-fail: fail: battle ended unexpectedly"


def test_every_count_is_right_and_skipped_not_listed(tmp_path: Path):
    _setup_sample_reports(tmp_path)
    out = summarize(tmp_path, suites=["all"])
    lines = out.splitlines()

    # Check suite summary line
    expected_header = "all  2026-11-05-1100-all.md  pass=2 fail=2 inconclusive=1 skipped=2  37 min 40 s"
    assert lines[0] == expected_header

    # Skipped rows and pass rows must not be listed
    assert "case-skip-1" not in out
    assert "case-skip-2" not in out
    assert "case-pass-1" not in out
    assert "case-pass-2" not in out


def test_fail_and_inconclusive_rows_listed_with_160_char_evidence(tmp_path: Path):
    _setup_sample_reports(tmp_path)
    out = summarize(tmp_path, suites=["all"])
    lines = out.splitlines()

    # Fail and inconclusive rows must be listed under the suite line with 4-space indent
    assert "    case-fail-1: fail: error encountered" in lines
    assert "    case-inconc: inconclusive: ambiguous state detected" in lines

    # Check evidence truncation at 160 characters
    expected_truncated_line = f"    case-fail-long: fail: {'E' * 160}"
    assert expected_truncated_line in lines
    assert ("E" * 161) not in out


def test_report_with_no_table_does_not_crash(tmp_path: Path):
    _setup_sample_reports(tmp_path)
    out = summarize(tmp_path, suites=["notable"])
    lines = out.splitlines()

    assert len(lines) == 1
    assert lines[0] == "notable  2026-11-05-0900-notable.md  pass=0 fail=0 inconclusive=0 skipped=0  0.0 s"


def test_main_cli_and_all_suites(tmp_path: Path, capsys):
    _setup_sample_reports(tmp_path)

    # CLI with specific suite
    main(["--dir", str(tmp_path), "smoke"])
    captured = capsys.readouterr()
    assert "2026-11-05-1200-smoke.md" in captured.out
    assert "field-fail: fail: battle ended unexpectedly" in captured.out
    assert "all  2026-11-05-1100-all.md" not in captured.out

    # CLI without suites summarizes all discovered suites
    main(["--dir", str(tmp_path)])
    captured_all = capsys.readouterr()
    assert "all  2026-11-05-1100-all.md" in captured_all.out
    assert "smoke  2026-11-05-1200-smoke.md" in captured_all.out
    assert "notable  2026-11-05-0900-notable.md" in captured_all.out
