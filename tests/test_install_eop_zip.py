"""scripts/install_eop.sh EOP_BUILD=zip: install a zip already on the host (our fork's Gitea build,
11-15), checked against the sha256 given."""
import hashlib
import os
import subprocess
import zipfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "install_eop.sh"


def setup(tmp_path):
    game = tmp_path / "game"
    game.mkdir()
    (game / "medieval2.exe").write_text("")
    z = tmp_path / "M2TWEOP.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("M2TWEOPLibrary.dll", "fork build")
    return game, z, hashlib.sha256(z.read_bytes()).hexdigest()


def run(game, **env):
    return subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, timeout=60,
                          env=dict(os.environ, MTW2_GAME_DIR=str(game), EOP_BUILD="zip", **env))


def test_a_zip_with_its_sha_installs(tmp_path):
    game, z, sha = setup(tmp_path)
    r = run(game, EOP_ZIP=str(z), EOP_SHA256=sha)
    assert r.returncode == 0, r.stderr
    assert (game / "mods/parley/M2TWEOPLibrary.dll").read_text() == "fork build"
    assert (game / "mods/parley/parley.cfg").exists()


def test_a_fresh_install_gets_eops_config_and_a_users_is_kept(tmp_path):
    # live 11-24, fresh Debian VM: the fork zip ships no eopData/config, and without gameCfg.json
    # the game exits at start with "encountered an unspecified error"
    import json
    game, z, sha = setup(tmp_path)
    assert run(game, EOP_ZIP=str(z), EOP_SHA256=sha).returncode == 0
    cfg = game / "mods/parley/eopData/config"
    for name in ("gameCfg.json", "battlesCfg.json", "discordRichPresenceCfg.json"):
        json.loads((cfg / name).read_text())
    (cfg / "gameCfg.json").write_text('{"mine": true}')
    assert run(game, EOP_ZIP=str(z), EOP_SHA256=sha).returncode == 0
    assert json.loads((cfg / "gameCfg.json").read_text()) == {"mine": True}


def test_a_wrong_sha_installs_nothing(tmp_path):
    game, z, _ = setup(tmp_path)
    r = run(game, EOP_ZIP=str(z), EOP_SHA256="0" * 64)
    assert r.returncode != 0
    assert not (game / "mods/parley/M2TWEOPLibrary.dll").exists()


def test_no_sha_given_is_refused(tmp_path):
    game, z, _ = setup(tmp_path)
    r = run(game, EOP_ZIP=str(z))
    assert r.returncode != 0 and "EOP_SHA256" in r.stderr
