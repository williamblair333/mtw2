#!/usr/bin/env python3
"""Preflight check (STANDARDS regression-per-bug): a commit that changes code carries a test.

Run by the preflight gate before a `git commit` (.claude/preflight.toml), with the command in
PREFLIGHT_COMMAND. The files a commit will hold are those already staged plus those the same
command stages first (`git add a b && git commit ...`). When any is code (lua/, parley/, scripts/:
.lua, .py, .sh) and none is under tests/, the commit is refused, unless its message says why no
test fits: `no-test: <reason>` (a comment-only change, a script only a live run can exercise).
Exit 0 = go; 1 = refused, with the reason on stdout.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys

CODE_DIRS = ("lua/", "parley/", "scripts/")
CODE_EXT = (".lua", ".py", ".sh")


def added_in_command(command: str) -> list[str]:
    """Paths named by `git add` in the command (flags and `.`/`-A` aside)."""
    try:
        tokens = shlex.split(command, comments=False, posix=True)
    except ValueError:
        tokens = command.split()
    paths, i = [], 0
    while i < len(tokens):
        if tokens[i] == "git" and i + 1 < len(tokens) and tokens[i + 1] == "add":
            i += 2
            while i < len(tokens) and tokens[i] not in ("&&", "||", ";", "|"):
                t = tokens[i].rstrip(";")
                if t and not t.startswith("-"):
                    paths.append(t)
                if tokens[i].endswith(";"):
                    break
                i += 1
        i += 1
    return paths


def staged() -> list[str]:
    try:
        out = subprocess.run(["git", "diff", "--cached", "--name-only"], capture_output=True,
                             text=True, timeout=20, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def is_code(path: str) -> bool:
    return path.startswith(CODE_DIRS) and path.endswith(CODE_EXT)


def verdict(command: str, already_staged: list[str]) -> str | None:
    """None to allow; otherwise the reason to refuse."""
    if "no-test:" in command:
        return None
    files = set(already_staged) | set(added_in_command(command))
    code = sorted(f for f in files if is_code(f))
    if not code or any(f.startswith("tests/") for f in files):
        return None
    return ("this commit changes code but carries no test: " + ", ".join(code[:6])
            + ". Add the test that fails without the change (STANDARDS regression-per-bug), "
            "or say why none fits in the message: no-test: <reason>")


def main() -> int:
    command = os.environ.get("PREFLIGHT_COMMAND", "")
    reason = verdict(command, staged())
    if reason:
        print(reason)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
