import hashlib
import os
import subprocess
from pathlib import Path

SCRIPTS = Path(__file__).parent.parent / "scripts"


def test_install_bridge_writes_parley_build_stamp(tmp_path):
    game = tmp_path / "game"
    master = game / "mods/parley/eopData/eopScripts"
    master.mkdir(parents=True)
    env = {**os.environ, "MTW2_GAME_DIR": str(game)}
    subprocess.run(["bash", str(SCRIPTS / "install_bridge.sh")], env=env,
                   capture_output=True, text=True, check=True)
    stamp_file = game / "parley_turns" / "parley_build.txt"
    assert stamp_file.exists()
    installed_bridge = master / "parley_bridge.lua"
    expected = hashlib.sha256(installed_bridge.read_bytes()).hexdigest()[:12]
    assert stamp_file.read_text().strip() == expected


def test_python_one_liner_stamp_matches_hashlib(tmp_path):
    dummy = tmp_path / "bridge.lua"
    dummy.write_text("return { version = '1.0' }\n")
    cmd = ["python3", "-c",
           "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest()[:12])",
           str(dummy)]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.strip()
    expected = hashlib.sha256(dummy.read_bytes()).hexdigest()[:12]
    assert out == expected
