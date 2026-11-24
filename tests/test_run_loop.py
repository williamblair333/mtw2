"""scripts/run_loop.sh (just run) and scripts/game.sh borrow the logged-in desktop's display when
started without one: live 11-05 14:56 (the test laptop) a loop started over ssh logged "screenshot failed:
game window not found" and every offer ran to its 540 s timeout."""

import os
import subprocess
from pathlib import Path

SCRIPTS = Path(__file__).parent.parent / "scripts"


def _fake_bin(tmp_path: Path, desktop_pid: int | None) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # the desktop shell: pgrep finds it (plasmashell), or nothing is running
    pgrep = f'[ "$*" != "${{*%plasmashell}}" ] && echo {desktop_pid} && exit 0; exit 1' if desktop_pid else "exit 1"
    for name, body in {"pgrep": pgrep, "uv": 'echo "UV:$* DISPLAY=${DISPLAY:-none}"'}.items():
        p = bin_dir / name
        p.write_text("#!/usr/bin/env bash\n" + body + "\n")
        p.chmod(0o755)
    return bin_dir


def _run(tmp_path: Path, desktop_pid: int | None) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY")}
    env["PATH"] = f"{_fake_bin(tmp_path, desktop_pid)}:/usr/bin:/bin"
    return subprocess.run(["bash", str(SCRIPTS / "run_loop.sh"), "games/local/scratch.toml"],
                          env=env, capture_output=True, text=True, timeout=20)


def test_run_loop_borrows_the_desktops_display(tmp_path):
    desktop = subprocess.Popen(["sleep", "30"], env={"DISPLAY": ":77", "PATH": "/usr/bin:/bin"})
    try:
        res = _run(tmp_path, desktop.pid)
    finally:
        desktop.kill()
    assert res.returncode == 0, res.stderr
    assert "UV:run python -m parley run games/local/scratch.toml DISPLAY=:77" in res.stdout
    assert "using the desktop's (DISPLAY=:77" in res.stdout


def test_run_loop_still_starts_and_warns_when_nobody_is_logged_in(tmp_path):
    res = _run(tmp_path, None)
    assert res.returncode == 0
    assert "DISPLAY=none" in res.stdout
    assert "nobody is logged in" in res.stderr


def test_game_sh_borrows_the_display_too():
    # play and restart-loop start the loop from game.sh
    text = (SCRIPTS / "game.sh").read_text(encoding="utf-8")
    assert ". scripts/desktop_env.sh" in text and "desktop_env_borrow" in text
