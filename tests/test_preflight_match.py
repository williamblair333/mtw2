"""The forced-events gate catches every way a session runs `just qa`, and nothing else.

The hook's `match` (.claude/preflight.toml) is only a prefilter; scripts/preflight_interrupts.py
qa_args decides, with shell tokenizing, whether `just qa` actually runs. Live 11-04:
`timeout 590 just qa towns ...` slipped past the old match (VAR=value only before `just`) and the
run played smoke's turn cases while phase 1 was open; one of them crashed the game. The review
of that fix found more bypasses (quoted VAR values, `timeout -s KILL`, sudo, `bash -c`, a second
line, `just -f`), and quoted commit messages wrongly caught.
"""

import importlib.util
import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GATES = tomllib.loads((ROOT / ".claude" / "preflight.toml").read_text(encoding="utf-8"))["gate"]
MATCH = re.compile(next(g for g in GATES if g["id"] == "forced-events")["match"])
_spec = importlib.util.spec_from_file_location("preflight_interrupts", ROOT / "scripts" / "preflight_interrupts.py")
pi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pi)


def gated(command: str) -> list[str] | None:
    """The suite arguments the gate checks, or None when it lets the command through unchecked."""
    return pi.qa_args(command) if MATCH.search(command) else None


@pytest.mark.parametrize(("command", "args"), [
    ("just qa towns case=repair_queued", ["towns", "case=repair_queued"]),
    ("PARLEY_NO_X_INPUT=1 just qa all kind=instant", ["all", "kind=instant"]),
    ("timeout 590 just qa towns case=x --real games/local/scratch.toml 2>&1 | tail -15",
     ["towns", "case=x", "--real", "games/local/scratch.toml", "2>&1"]),
    ("PARLEY_NO_X_INPUT=1 timeout 590 just qa towns kind=instant", ["towns", "kind=instant"]),
    ("timeout -k 5 590 just qa smoke", ["smoke"]),
    ("timeout -s KILL 590 just qa towns", ["towns"]),
    ("env PARLEY_NO_X_INPUT=1 just qa all", ["all"]),
    ("env -i just qa towns", ["towns"]),
    ("time -p just qa towns", ["towns"]),
    ("nice -n 10 just qa navy", ["navy"]),
    ("nohup just qa all &", ["all"]),
    ("sudo just qa towns", ["towns"]),
    ('FOO="a b" just qa towns', ["towns"]),
    ("cd . && timeout 300 just qa towns", ["towns"]),
    ("cd d\njust qa towns", ["towns"]),
    ("just install-bridge && just qa towns", ["towns"]),
    ("just -f justfile qa towns", ["towns"]),
    ("just --justfile j qa towns", ["towns"]),
    ("bash -c 'just qa towns'", ["towns"]),
    ("timeout 5 sh -c 'cd x && just qa towns kind=instant'", ["towns", "kind=instant"]),
])
def test_the_gate_checks_a_qa_run(command, args):
    assert gated(command) == args


@pytest.mark.parametrize("command", [
    "just qa-restore --real games/local/scratch.toml",
    "just qa-bench-save start",
    "git commit -m 'run just qa towns next'",
    'git commit -m "fix: run; just qa foo"',
    'git log --grep="x | just qa x"',
    "echo hi | grep 'a; just qa'",
    "grep -n 'just qa' HANDOFF.md",
    # live 11-04: a log note written by heredoc mentioned `PARLEY_NO_X_INPUT=1 just qa all kind=instant`
    # in backticks, and the closing backtick made it read as a turn-playing run
    "cat >> notes.md <<'EOF'\nthen run `PARLEY_NO_X_INPUT=1 just qa all kind=instant` there\nEOF\necho ok",
    "cat > x.md <<EOF\njust qa towns\nEOF",
    "python3 - <<-PY\n\tprint('just qa towns')\n\tPY",
])
def test_the_gate_lets_through_what_runs_no_suite(command):
    assert gated(command) is None


def test_a_qa_run_after_a_heredoc_is_still_checked():
    assert gated("cat > x.md <<'EOF'\nnotes\nEOF\njust qa towns") == ["towns"]


def test_a_heredoc_fed_to_a_shell_is_checked_as_commands():
    assert gated("bash <<'EOF'\ncd .\njust qa towns\nEOF") == ["towns"]
