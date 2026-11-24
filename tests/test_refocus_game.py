"""scripts/refocus_game.sh: the game stops when it isn't the active window; give it focus back.

Live 2026-11-20 07:13-07:21 (the test laptop): a Steam window held focus, the game used no CPU for
8 minutes and the bridge log went quiet; crash-watch saw a live process and no dialog, so nothing
reacted. `xdotool windowactivate` (a window-manager request, no input) resumed it at once.
"""

import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "scripts" / "refocus_game.sh"
GAME, STEAM = "155189249", "77"


def _run(tmp_path, age, *, game=GAME, active=STEAM):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    calls = tmp_path / "calls"
    (bin_dir / "xdotool").write_text(
        "#!/usr/bin/env bash\n"
        f"echo \"$*\" >> '{calls}'\n"
        "case \"$1\" in\n"
        f"  search) [ -n '{game}' ] && echo '{game}';;\n"
        f"  getactivewindow) echo '{active}';;\n"
        "  getwindowname) echo 'Steam';;\n"
        "esac\n")
    (bin_dir / "xdotool").chmod(0o755)
    (bin_dir / "import").write_text(f"#!/usr/bin/env bash\necho import >> '{calls}'\n")
    (bin_dir / "import").chmod(0o755)
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "DISPLAY": ":99"}
    out = subprocess.run(["bash", str(SCRIPT), str(age)], env=env, capture_output=True, text=True,
                         timeout=10)
    said = calls.read_text().splitlines() if calls.exists() else []
    return out, said


def test_an_unfocused_quiet_game_gets_focus_back(tmp_path):
    out, calls = _run(tmp_path, 90)
    assert out.returncode == 0 and out.stdout.strip() == "Steam"  # names what held focus
    assert f"windowactivate --sync {GAME}" in calls


def test_the_active_game_is_left_alone(tmp_path):
    out, calls = _run(tmp_path, 90, active=GAME)
    assert out.returncode == 1
    assert not any(c.startswith("windowactivate") for c in calls)


def test_a_fresh_log_is_left_alone(tmp_path):
    # a quick alt-tab by a person isn't fought: only a log quiet past the threshold counts
    out, calls = _run(tmp_path, 20)
    assert out.returncode == 1 and calls == []


def test_no_game_window_does_nothing_and_never_waits_for_a_click(tmp_path):
    # live 11-20: an empty window id made `import -window ""` wait for a click and hold X
    out, calls = _run(tmp_path, 90, game="")
    assert out.returncode == 1
    assert not any(c.startswith("windowactivate") or c == "import" for c in calls)
