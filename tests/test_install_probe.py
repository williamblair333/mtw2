"""scripts/install_probe.sh puts the probe where the bridge is, so `just probe` is a no-Parley split."""

import os
import subprocess
from pathlib import Path

SCRIPTS = Path(__file__).parent.parent / "scripts"


def _game(tmp_path: Path) -> Path:
    game = tmp_path / "game"
    master = game / "mods/parley/eopData/eopScripts"
    master.mkdir(parents=True)
    (game / "mods/parley/youneuoy_Data/plugins/lua").mkdir(parents=True)
    (master / "luaPluginScript.lua").write_text("-- EOP entry point for parley\n")
    (master / "luaPluginScript.lua.parley-orig").write_text("-- EOP's own script\n")
    return game


def _probe(game: Path) -> str:
    env = {**os.environ, "MTW2_GAME_DIR": str(game)}
    return subprocess.run(["bash", str(SCRIPTS / "install_probe.sh")], env=env,
                          capture_output=True, text=True, check=True).stdout


def test_the_probe_replaces_the_plugin_the_game_loads(tmp_path):
    # live 11-10: the probe went to youneuoy_Data and the game root; the game loads the mod's
    # eopData/eopScripts (the bridge's), so every "probe" run still ran the bridge
    game = _game(tmp_path)
    out = _probe(game)
    master = game / "mods/parley/eopData/eopScripts"
    assert "parley probe" in (master / "luaPluginScript.lua").read_text()
    assert f"probe installed: {master}/luaPluginScript.lua" in out


def test_the_original_eop_script_is_kept_not_overwritten(tmp_path):
    game = _game(tmp_path)
    _probe(game)
    master = game / "mods/parley/eopData/eopScripts"
    assert (master / "luaPluginScript.lua.parley-orig").read_text() == "-- EOP's own script\n"
