"""scripts/preflight_tests_staged.py: a code commit carries a test (STANDARDS regression-per-bug)."""

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "pts", Path(__file__).parent.parent / "scripts" / "preflight_tests_staged.py")
pts = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pts)


def test_code_without_a_test_is_refused():
    r = pts.verdict("git add lua/parley_bridge.lua && git commit -q -m 'fix: x'", [])
    assert r and "lua/parley_bridge.lua" in r and "no-test:" in r


def test_code_with_a_test_staged_in_the_same_command_passes():
    assert pts.verdict("git add parley/orchestrator.py tests/test_orchestrator.py && git commit -m x", []) is None


def test_already_staged_files_count():
    assert pts.verdict("git commit -m x", ["scripts/game.sh"])
    assert pts.verdict("git commit -m x", ["scripts/game.sh", "tests/test_game_scripts.py"]) is None


def test_docs_and_suites_need_no_test():
    assert pts.verdict("git add STANDARDS.md games/qa/towns.toml HANDOFF.md && git commit -m docs", []) is None


def test_a_stated_reason_lets_it_through():
    assert pts.verdict("git add scripts/x.sh && git commit -m 'chore: y\n\nno-test: comment only'", []) is None


def test_git_add_flags_are_not_paths():
    assert pts.added_in_command("git add -A lua/a.lua; git commit -m x") == ["lua/a.lua"]
