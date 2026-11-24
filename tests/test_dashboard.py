import json
import os
from pathlib import Path

from parley.dashboard import _standards, dashboard, main


def _setup(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "turns"
    repo = tmp_path / "repo"
    root.mkdir()
    repo.mkdir()
    (root / "heartbeat.txt").write_text("turn=93\n", encoding="utf-8")
    # the bridge log is Wine-written CRLF
    (root / "parley_bridge.log").write_bytes(b"2026-11-05 16:29:49 autoplay: ending turn 93\r\n")
    for t, towns in ((92, 4), (93, 3)):
        f = root / "g" / f"turn-{t:04d}" / "england"
        f.mkdir(parents=True)
        (f / "state.json").write_text(json.dumps({"settlements": [{}] * towns, "armies": [{}]}))
        (f / "orders.json").write_text(json.dumps({"orders": [{}, {}]}))
        (f / "results.json").write_text(json.dumps([{"ok": True}, {"ok": False}]))
        os.utime(f / "orders.json", (os.stat(f / "state.json").st_mtime + 40,) * 2)
    crash = repo / "runs" / "crashes" / "2026-11-05-120000"
    crash.mkdir(parents=True)
    (crash / "report.md").write_text("# Crash\n\n- game: qa-covert, turn 7 (heartbeat)\n- crash-watch saw: game window gone\n", encoding="utf-8")
    (repo / "STANDARDS.md").write_text(
        "head\n```yaml\nphase: x\nstandards:\n  - id: a\n    status: done\n  - id: b\n    status: open\n"
        "  - id: c\n    status: partial\nideas:\n  - id: z\n    status: untested\n```\n", encoding="utf-8")
    return root, repo


def test_dashboard_shows_each_section(tmp_path):
    root, repo = _setup(tmp_path)
    page = dashboard(root, "g", repo)
    assert "heartbeat: turn=93" in page
    assert "newest report: turn-0093" in page and "answered: england; waiting: none" in page
    assert "autoplay: ending turn 93" in page and "\r" not in page
    assert "qa.lock: free" in page and "paused: no" in page
    assert "2026-11-05-120000" in page and "qa-covert, turn 7 (heartbeat); game window gone" in page
    assert "england: turns 92-93, 2/4 orders applied, 2 refused, 0 late or failed answers" in page
    assert "ALERT towns fell from 4 to 3" in page
    assert "1 done, 1 partial, 1 open of 3" in page
    assert "- open: b" in page and "- partial: c" in page


def test_unknown_army_refusals_are_counted_per_ruler(tmp_path):
    # live 11-05 (run 10): France's game AI renamed its captains; 2-4 orders a turn came back unknown
    root, repo = _setup(tmp_path)
    (root / "g" / "turn-0093" / "england" / "results.json").write_text(json.dumps([
        {"ok": False, "reason": "unknown army 'Captain Henri': not one of your armies by that name now"},
        {"ok": True}]))
    page = dashboard(root, "g", repo)
    assert "    1 refused for an army id no longer there (renamed or gone)" in page


def test_a_pause_shows_its_reason(tmp_path):
    root, repo = _setup(tmp_path)
    (root / "paused.txt").write_text("stopped by just stop: the turn loop is off; just play resumes\n")
    page = dashboard(root, "g", repo)
    assert "paused: yes (" in page and "): stopped by just stop: the turn loop is off" in page


def test_an_empty_pause_file_still_shows_as_paused(tmp_path):
    root, repo = _setup(tmp_path)
    (root / "paused.txt").write_text("")
    assert "paused: yes (" in dashboard(root, "g", repo) and "): ?" in dashboard(root, "g", repo)


def test_only_the_newest_three_crashes_show_newest_first(tmp_path):
    root, repo = _setup(tmp_path)
    crashes = repo / "runs" / "crashes"
    for name in ("2026-11-04-090000", "2026-11-05-130000", "2026-11-05-140000", "2026-11-05-150000"):
        (crashes / name).mkdir()  # no report.md: shown by name alone
    page = dashboard(root, "g", repo)
    assert "2026-11-04-090000" not in page and "2026-11-05-120000" not in page
    assert page.index("2026-11-05-150000") < page.index("2026-11-05-140000") < page.index("2026-11-05-130000")


def test_standards_ignores_ideas(tmp_path):
    _, repo = _setup(tmp_path)
    assert _standards(repo) == [("a", "done"), ("b", "open"), ("c", "partial")]


def test_dashboard_empty_root(tmp_path, capsys):
    assert main([str(tmp_path / "nowhere"), "g", "--repo", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "heartbeat: none" in out and "no answered turns" in out and "no STANDARDS.md" in out


def test_dashboard_on_this_repo_standards():
    items = _standards(Path("."))
    assert len(items) >= 15 and all(s in {"done", "partial", "open", "n/a"} for _, s in items)
