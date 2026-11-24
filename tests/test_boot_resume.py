"""scripts/boot_resume.sh: at login, resume the campaign that was playing (live 11-15: tc booted at
03:00 and nothing came back; the campaign idled until 05:48)."""
import os
import shutil
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "boot_resume.sh"


def run(tmp_path: Path, resume: str | None, paused: bool = False):
    calls = tmp_path / "calls"
    just = tmp_path / "just"
    just.write_text(f'#!/usr/bin/env bash\necho "$*" >> "{calls}"\n')
    just.chmod(0o755)
    turn_root = tmp_path / "turns"
    turn_root.mkdir()
    if paused:
        (turn_root / "paused.txt").write_text("")
    cfg = tmp_path / "resume"
    if resume is not None:
        cfg.write_text(resume + "\n")
    env = dict(os.environ, PARLEY_JUST=str(just), PARLEY_RESUME_FILE=str(cfg),
               PARLEY_TURN_ROOT=str(turn_root), PARLEY_BOOT_WAIT="0")
    r = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=30)
    return r, (calls.read_text().splitlines() if calls.exists() else [])


def test_it_starts_the_named_campaigns_loop_and_crash_watch(tmp_path):
    r, calls = run(tmp_path, "scratch")
    assert r.returncode == 0, r.stderr
    # crash-watch relaunches the game itself (no medieval2.exe); the loop waits for it
    assert calls == ["play scratch", "crash-watch"]


def test_a_paused_campaign_stays_paused(tmp_path):
    r, calls = run(tmp_path, "scratch", paused=True)
    assert r.returncode == 0 and calls == []
    assert "paused" in r.stdout


def test_just_is_found_in_local_bin_without_it_on_path(tmp_path):
    # live 11-19: the autostart's PATH lacked ~/.local/bin, so "just: command not found" and
    # nothing resumed after the 03:00 power-on
    home = tmp_path / "home"
    (home / ".local" / "bin").mkdir(parents=True)
    calls = tmp_path / "calls"
    just = home / ".local" / "bin" / "just"
    just.write_text(f'#!/usr/bin/env bash\necho "$*" >> "{calls}"\n')
    just.chmod(0o755)
    cfg = tmp_path / "resume"
    cfg.write_text("scratch\n")
    turns = tmp_path / "turns"
    turns.mkdir()
    # PATH holds only the tools the script uses, never a real just (/usr/bin/just on the main machine: the
    # red run of this test started a real crash-watch there, 11-19)
    sysbin = tmp_path / "sysbin"
    sysbin.mkdir()
    for tool in ("bash", "dirname", "head", "tr", "date", "sleep", "mkdir", "env"):
        (sysbin / tool).symlink_to(shutil.which(tool))
    env = {"HOME": str(home), "PATH": str(sysbin), "PARLEY_RESUME_FILE": str(cfg),
           "PARLEY_TURN_ROOT": str(turns), "PARLEY_BOOT_WAIT": "0"}
    r = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert "failed" not in r.stdout, r.stdout
    assert calls.read_text().splitlines() == ["play scratch", "crash-watch"]


def test_nothing_named_nothing_started(tmp_path):
    r, calls = run(tmp_path, None)
    assert r.returncode == 0 and calls == []


def test_log_flag_writes_the_boot_log(tmp_path):
    import shutil
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, repo / "scripts" / "boot_resume.sh")
    env = dict(os.environ, PARLEY_RESUME_FILE=str(tmp_path / "none"), PARLEY_BOOT_WAIT="0")
    r = subprocess.run(["bash", str(repo / "scripts" / "boot_resume.sh"), "--log"], env=env,
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0 and r.stdout == ""
    assert "nothing to start" in (repo / "logs" / "boot-resume.log").read_text()


INSTALL = SCRIPT.with_name("boot_resume_install.sh")


def test_install_on_and_off(tmp_path):
    env = dict(os.environ, PARLEY_RESUME_FILE=str(tmp_path / "resume"),
               PARLEY_AUTOSTART_DIR=str(tmp_path / "autostart"))
    subprocess.run(["bash", str(INSTALL), "on", "scratch"], env=env, check=True, capture_output=True)
    desktop = (tmp_path / "autostart" / "parley-resume.desktop").read_text()
    exec_line = next(ln for ln in desktop.splitlines() if ln.startswith("Exec="))
    # a desktop entry's Exec is no shell: no single quotes, redirects or bash -c (review 11-15)
    assert "scripts/boot_resume.sh\" --log" in exec_line
    assert not any(c in exec_line for c in "'>&|;")
    assert (tmp_path / "resume").read_text().strip() == "scratch"
    subprocess.run(["bash", str(INSTALL), "off"], env=env, check=True, capture_output=True)
    assert not (tmp_path / "autostart" / "parley-resume.desktop").exists()
    assert not (tmp_path / "resume").exists()
