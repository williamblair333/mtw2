"""The committed uv.lock pins Jigsaw by the git tag pyproject.toml names.

Jigsaw used to be a path dependency, and a worktree's `uv sync` rewrote that path (#219, #244).
Since #348 it's a public git tag: a lock committed from a stale sync would point at a path or
another tag, and a clean machine would install something else. This checks the committed lock
(HEAD), not the working copy.
"""

import re
import subprocess
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _committed(path: str) -> str | None:
    try:
        return subprocess.run(["git", "show", f"HEAD:{path}"], cwd=REPO, capture_output=True,
                              text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None  # not a git checkout (an sdist): nothing committed to check


def test_committed_uv_lock_pins_jigsaw_at_the_pyproject_tag():
    lock, project = _committed("uv.lock"), _committed("pyproject.toml")
    if lock is None or project is None:
        return
    source = tomllib.loads(project)["tool"]["uv"]["sources"]["jigsaw"]
    want = f'source = {{ git = "{source["git"]}?tag={source["tag"]}#'
    block = re.search(r'\[\[package\]\]\nname = "jigsaw"\n.*?(?=\n\[\[package\]\]|\Z)', lock, re.S)
    assert block, "uv.lock has no jigsaw package"
    assert want in block.group(0), (
        f"uv.lock's jigsaw isn't {source['git']} at {source['tag']}; run `uv lock` and commit it")
