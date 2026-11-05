#!/usr/bin/env python3
"""Preflight gate for `just qa`: a run that plays turns needs every interrupting event handled.

Why: 2026-11-01 a minimized papal election stalled turn 50 for hours. Papal elections were
already the known crash source and STANDARDS had `forced-events`, yet no test setup held them
off. The author had to ask. This check makes the list mechanical: the Refinery's preflight-gate hook
runs it before any `just qa` command (.claude/preflight.toml), in every session.

Rules:
  * a run with `kind=instant` (or `--kind instant`) plays no turn: pass.
  * otherwise every case the run would play that has kind "turn" (the default) needs each
    event in games/interrupts.toml handled: `ruled_out = "<why it can't happen>"`, or
    `held_by = "<what holds it off>"` plus `proof = ["<path>::<regex>", ...]`, each of which
    must match in the repo, so a neutraliser that was planned but never built doesn't count.
  * a `held_by` also needs `bench = "<suite>/<case>"`, and the newest bench report row for that
    case (runs/qa/<stamp>-<suite>.md or -all.md) must say pass: a hold proven only by unit tests
    isn't held (11-01: #342/#344/#345 merged on fake-game tests and hand-typed Lua).
  * phase order (STANDARDS: phase-order): no turn-playing run while the newest no-click run
    (runs/qa/*-all.md) has a fail or inconclusive case, unless games/no-click-explained.toml
    lists it with a `why` (11-01: a session did quiet-world turn work over phase 1's open fails).
  * the smoke suite runs before the others unless `no-smoke`/`--no-smoke` is given.

runs/qa is gitignored, so a worktree has no reports and turn runs there are refused; set
PARLEY_QA_RUNS to the main checkout's runs/qa to read its reports.

Reads PREFLIGHT_COMMAND (set by the gate); or pass the command as arguments when testing.
Exit 0 = go, 1 = refused (the output says what's missing), 2 = the command or files can't be read.
"""
from __future__ import annotations

import os
import re
import shlex
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QA_DIR = ROOT / "games" / "qa"
EVENTS = ROOT / "games" / "interrupts.toml"  # not in games/qa/: every toml there is a suite
EXPLAINED = ROOT / "games" / "no-click-explained.toml"
RUNS = Path(os.environ.get("PARLEY_QA_RUNS") or ROOT / "runs" / "qa")
ROW = re.compile(r"^\| (\S+) \| (pass|fail|inconclusive|skipped|error|crashed)\b", re.M)
OPEN = {"fail", "inconclusive", "error", "crashed"}


def _reports(suite: str | None = None) -> list[Path]:
    """Bench reports, newest first; with `suite`, only that suite's and the all-suite runs."""
    try:
        found = [p for p in RUNS.glob("*.md")
                 if suite is None or p.stem.endswith(f"-{suite}") or p.stem.endswith("-all")]
    except OSError:
        return []
    return sorted(found, key=lambda p: p.stat().st_mtime, reverse=True)


def bench_outcome(ref: str) -> tuple[str | None, Path | None]:
    """The newest report row's outcome for `suite/case`, and its report."""
    suite, _, case = ref.partition("/")
    for p in _reports(suite):
        for name, outcome in ROW.findall(p.read_text(encoding="utf-8", errors="replace")):
            if name == case:
                return outcome, p
    return None, None


def phase_open() -> list[str]:
    """The newest no-click run's fail/inconclusive cases not explained in games/no-click-explained.toml."""
    alls = [p for p in _reports() if p.stem.endswith("-all")]
    if not alls:
        return [f"- no no-click run on record in {RUNS} (run `just qa all kind=instant` first)"]
    newest = alls[0]
    rows = ROW.findall(newest.read_text(encoding="utf-8", errors="replace"))
    if not rows:
        return [f"- {newest.name} has no case rows; can't tell whether phase 1 is clean"]
    try:
        explained = tomllib.loads(EXPLAINED.read_text(encoding="utf-8")).get("cases", {})
    except FileNotFoundError:
        explained = {}
    return [f"- {name}: {outcome} in {newest.name}" for name, outcome in rows
            if outcome in OPEN and not str(explained.get(name, {}).get("why", "")).strip()]


# just's own options that take a value, skipped between `just` and its recipe (`just -f j qa x`)
_JUST_VALUED = {"-f", "--justfile", "-d", "--working-directory", "--dotenv-filename", "--dotenv-path",
                "--shell", "--shell-arg", "--chooser", "--command", "--color", "--list-heading",
                "--list-prefix"}


_HEREDOC = re.compile(r"<<(-?)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")
# a heredoc fed to one of these is a script, so its body is checked as commands
_SHELLS = {"sh", "bash", "dash", "zsh", "ssh"}


def _drop_heredoc_bodies(command: str) -> str:
    """The command with each heredoc's body removed, unless the heredoc feeds a shell.

    A body is text handed to a program (a file, a commit message): live 11-04 a log note in a
    heredoc that mentioned the no-click qa command read as a turn-playing run."""
    out, pending = [], []
    for line in command.split("\n"):
        if pending:
            strip_tabs, delim, keep = pending[0]
            if (line.lstrip("\t") if strip_tabs else line) == delim:
                pending.pop(0)
                if keep:
                    out.append(line)
            elif keep:
                out.append(line)
            continue
        out.append(line)
        for m in _HEREDOC.finditer(line):
            before = line[:m.start()].split()
            program = before[-1] if before else ""
            pending.append((m.group(1) == "-", m.group(3), program in _SHELLS))
    return "\n".join(out)


def qa_args(command: str) -> list[str] | None:
    """The arguments after the first `just qa` in a shell command, or None if there is none.

    Tokenized like the shell, so `just qa` inside a quoted string (a commit message, a grep
    pattern) or a heredoc's body doesn't count, while one inside a `sh -c '...'` script or a
    heredoc fed to a shell does."""
    # a line break ends a command, as `;` does (shlex alone reads it as plain whitespace)
    command = _drop_heredoc_bodies(command).replace("\n", " ;\n")
    try:
        words = shlex.split(command, comments=True)
    except ValueError:
        words = command.split()
    for i, w in enumerate(words):
        if w == "-c" and i + 1 < len(words):
            inner = qa_args(words[i + 1])
            if inner is not None:
                return inner
        if w != "just":
            continue
        j = i + 1
        while j < len(words) and words[j].startswith("-"):
            if words[j] == "--set":
                j += 3
            elif words[j] in _JUST_VALUED:
                j += 2
            else:
                j += 1
        if j < len(words) and words[j] == "qa":
            rest = []
            for w in words[j + 1:]:
                if w in {";", "&&", "||", "|", "&"} or w.endswith(";"):
                    if w.endswith(";") and w != ";":
                        rest.append(w[:-1])
                    break
                rest.append(w)
            return rest
    return None


def parse_run(args: list[str]) -> dict:
    run = {"suite": None, "cases": [], "instant": False, "smoke": True}
    it = iter(args)
    for a in it:
        if a in ("kind=instant",) or a == "--kind=instant":
            run["instant"] = True
        elif a == "--kind":
            run["instant"] = next(it, "") == "instant"
        elif a.startswith("case="):
            run["cases"].append(a[5:])
        elif a == "--case":
            run["cases"].append(next(it, ""))
        elif a in ("no-smoke", "--no-smoke"):
            run["smoke"] = False
        elif a == "--real":
            next(it, None)
        elif not a.startswith("-") and "=" not in a and run["suite"] is None:
            run["suite"] = a
    return run


def load_suite(name: str) -> dict:
    return tomllib.loads((QA_DIR / f"{name}.toml").read_text(encoding="utf-8"))


def turn_cases(run: dict) -> list[str]:
    """`suite/case` for every turn case the run would play."""
    suite = run["suite"]
    if suite == "all":
        names = sorted(p.stem for p in QA_DIR.glob("*.toml"))
    else:
        names = [suite]
        if run["smoke"] and suite != "smoke":
            names.insert(0, "smoke")
    found = []
    for name in names:
        for case in load_suite(name).get("cases", []):
            if run["cases"] and name != "smoke" and case.get("name") not in run["cases"]:
                continue
            if case.get("kind", "turn") != "instant":
                found.append(f"{name}/{case.get('name')}")
    return found


def unhandled(events: dict) -> list[str]:
    problems = []
    for eid, ev in events.items():
        what = ev.get("what", eid)
        if str(ev.get("ruled_out", "")).strip():
            continue
        held = str(ev.get("held_by", "")).strip()
        if not held:
            problems.append(f"- {eid}: {what}\n    nothing holds it off yet{_note(ev)}")
            continue
        proofs = ev.get("proof") or []
        if not proofs:
            problems.append(f"- {eid}: held_by '{held}' has no proof (path::regex)")
            continue
        built = True
        for p in proofs:
            path, _, rx = p.partition("::")
            f = ROOT / path
            try:
                ok = bool(rx) and re.search(rx, f.read_text(encoding="utf-8", errors="replace"), re.M)
            except (OSError, re.error) as exc:
                problems.append(f"- {eid}: proof {p!r} unreadable ({exc})")
                built = False
                continue
            if not ok:
                problems.append(f"- {eid}: proof {p!r} not found, so '{held}' isn't built")
                built = False
        if not built:
            continue  # no bench question until the code is there
        bench = str(ev.get("bench", "")).strip()
        if not bench:
            problems.append(f"- {eid}: held in code, not proven on the bench (add bench = \"suite/case\""
                            " and a passing run of it)")
            continue
        outcome, report = bench_outcome(bench)
        if outcome is None:
            problems.append(f"- {eid}: no bench run of {bench} on record in {RUNS}")
        elif outcome != "pass":
            problems.append(f"- {eid}: newest bench run of {bench}: {outcome} ({report.name})")
    return problems


def _note(ev: dict) -> str:
    return f"\n    note: {ev['note']}" if ev.get("note") else ""


def main(argv: list[str]) -> int:
    command = " ".join(argv) if argv else os.environ.get("PREFLIGHT_COMMAND", "")
    args = qa_args(command)
    if args is None:
        return 0
    run = parse_run(args)
    if run["instant"]:
        print("instant-only run: no turn plays, so nothing can interrupt it")
        return 0
    if not run["suite"]:
        return 0  # qa.sh prints its own usage
    try:
        cases = turn_cases(run)
        events = tomllib.loads(EVENTS.read_text(encoding="utf-8")).get("events", {})
    except (OSError, tomllib.TOMLDecodeError) as exc:
        print(f"can't read the QA files: {exc}")
        return 2
    if not cases:
        print("no turn case in this run")
        return 0
    shown = ", ".join(cases[:6]) + (f" and {len(cases) - 6} more" if len(cases) > 6 else "")
    try:
        early = phase_open()
    except (OSError, tomllib.TOMLDecodeError) as exc:
        print(f"can't read the no-click run or {EXPLAINED.name}: {exc}")
        return 2
    if early:
        print(f"This run plays turns ({shown}), but the newest no-click run isn't clean:\n"
              + "\n".join(early)
              + "\n\nNo-click work comes first (STANDARDS: phase-order). Fix each, rerun "
                "`just qa all kind=instant`, or list one in games/no-click-explained.toml with its why.")
        return 1
    if not events:
        print(f"{EVENTS.relative_to(ROOT)} lists no events; a turn-playing run can't be cleared")
        return 1
    problems = unhandled(events)
    if not problems:
        return 0
    print(f"This run plays turns ({shown}), and these game events can interrupt it:\n"
          + "\n".join(problems)
          + "\n\nFor each one, build what holds it off in the bench setup and record it in "
            "games/interrupts.toml (held_by + proof = [\"path::regex\"]), or write ruled_out "
            "with the reason it can't happen. (STANDARDS: forced-events, fixed-bench-save.)\n"
            "Runs with kind=instant play no turn and pass this gate.")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
