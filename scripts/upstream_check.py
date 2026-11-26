#!/usr/bin/env python3
"""Do our upstream issues and PRs say where we stand? (preflight gate upstream-current)

Reads docs/upstream.toml and asks GitHub (gh) for each item's state, and for every open issue or PR the
account opened on the repos listed. Fails when an item we marked "solved" is still open upstream, or
when an open upstream item of ours is missing from the register. Live 11-25: an EOP developer answered
our issue #91, which we had solved by 11-20 and never closed.
Exit 0 = fine (or GitHub unreachable: the check can't decide, so it doesn't block); 1 = act first.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

REGISTER = Path(__file__).resolve().parents[1] / "docs" / "upstream.toml"
AUTHOR = "williamblair333"


def problems(items: list[dict], states: dict[tuple[str, int], str], open_ours: set[tuple[str, int]]) -> list[str]:
    out = []
    listed = {(i["repo"], i["number"]) for i in items}
    for i in items:
        key = (i["repo"], i["number"])
        if i.get("state") == "solved" and states.get(key) == "OPEN":
            out.append(f"{i['repo']}#{i['number']} ({i['ask']}) is solved on our side but still open upstream: "
                       f"comment where we got to ({i.get('note', '')}) and close it. Posting is William's call: "
                       f"draft it for him")
    for repo, n in sorted(open_ours - listed):
        out.append(f"{repo}#{n} is ours and open upstream but not in docs/upstream.toml: add it with its state")
    return out


def _gh(args: list[str]) -> str:
    return subprocess.run(["gh", *args], capture_output=True, text=True, timeout=30, check=True).stdout


def main() -> int:
    items = tomllib.loads(REGISTER.read_text())["item"]
    try:
        states, open_ours = {}, set()
        for repo in sorted({i["repo"] for i in items}):
            for kind in ("issues", "prs"):
                for r in json.loads(_gh(["search", kind, "--repo", repo, "--author", AUTHOR, "--state", "open",
                                         "--json", "number", "--limit", "100"])):
                    open_ours.add((repo, r["number"]))
            for i in (i for i in items if i["repo"] == repo):
                states[(repo, i["number"])] = "OPEN" if (repo, i["number"]) in open_ours else "CLOSED"
    except (subprocess.SubprocessError, OSError, json.JSONDecodeError) as e:
        print(f"upstream check skipped: GitHub not reachable ({e})")
        return 0
    found = problems(items, states, open_ours)
    for p in found:
        print(p)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
