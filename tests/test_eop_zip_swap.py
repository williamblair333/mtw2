"""scripts/eop_zip_swap.sh: swap the campaign onto another EOP build in a safe order (11-15)."""
import hashlib
import os
import subprocess
import zipfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "eop_zip_swap.sh"


def setup(tmp_path):
    game = tmp_path / "game"
    mod = game / "mods" / "parley"
    (mod / "eopData" / "config").mkdir(parents=True)
    (mod / "eopData" / "eopScripts").mkdir(parents=True)
    (game / "medieval2.exe").write_text("")
    (mod / "M2TWEOPLibrary.dll").write_text("old build")
    (mod / "eopData" / "config" / "a.json").write_text("{}")
    (mod / "eopData" / "eopScripts" / "luaPluginScript.lua").write_text("bridge loader")
    z = tmp_path / "M2TWEOP.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("M2TWEOPLibrary.dll", "fork build")
        f.writestr("eopData/config/a.json", '{"changed": 1}')
    calls = tmp_path / "calls"
    just = tmp_path / "just"
    just.write_text(f'#!/usr/bin/env bash\necho "$*" >> "{calls}"\n')
    just.chmod(0o755)
    return game, mod, z, hashlib.sha256(z.read_bytes()).hexdigest(), just, calls


def run(game, just, *args):
    return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, timeout=120,
                          env=dict(os.environ, MTW2_GAME_DIR=str(game), PARLEY_JUST=str(just)))


def test_the_swap_backs_up_stops_first_installs_and_resumes(tmp_path):
    game, mod, z, sha, just, calls = setup(tmp_path)
    r = run(game, just, str(z), sha, "scratch")
    assert r.returncode == 0, r.stderr + r.stdout
    backup = game / ".parley-backup" / f"eop-before-{sha[:8]}"
    assert (backup / "M2TWEOPLibrary.dll").read_text() == "old build"
    assert (backup / "eopScripts" / "luaPluginScript.lua").read_text() == "bridge loader"
    assert (mod / "M2TWEOPLibrary.dll").read_text() == "fork build"
    # crash-watch stops before anything else, the bridge goes back after the zip, then resume
    assert calls.read_text().splitlines() == [
        "crash-watch-stop", "stop", "install-bridge", "relaunch-game", "play scratch", "crash-watch"]
    assert "a.json" in r.stdout  # the config change against the backup is shown


def test_a_wrong_sha_touches_nothing(tmp_path):
    game, mod, z, _, just, calls = setup(tmp_path)
    r = run(game, just, str(z), "0" * 64)
    assert r.returncode != 0
    assert (mod / "M2TWEOPLibrary.dll").read_text() == "old build"
    assert not calls.exists()
