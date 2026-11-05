import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

needs_just = pytest.mark.skipif(shutil.which("just") is None, reason="just isn't installed")


@needs_just
def test_the_justfile_parses():
    # 10-31 05:50: #299 added a second `probe` recipe; every `just` command failed, `just qa` too
    r = subprocess.run(["just", "--summary"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@needs_just
@pytest.mark.parametrize("recipe, args, expect", [
    ("qa-bench-save", ["record", "--from", "/x/Medieval II Total War/a b.sav"],
     ["bench-save", "record", "--from", "/x/Medieval II Total War/a b.sav"]),
    ("qa", ["covert", "kind=instant", "case=a b"], ["run", "covert", "kind=instant", "case=a b"]),
    ("qa-restore", ["--real", "games/local/x y.toml"], ["restore", "--real", "games/local/x y.toml"]),
])
def test_qa_recipes_keep_each_argument_whole(tmp_path, recipe, args, expect):
    # 10-31 08:00: `just qa-bench-save record --from <the game's save>` split the path at its spaces
    fake = tmp_path / "bash"
    fake.write_text("#!/bin/sh\nshift\nfor a in \"$@\"; do printf '%s\\n' \"$a\"; done\n")
    fake.chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"}
    r = subprocess.run(["just", recipe, *args], cwd=ROOT, capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == expect
