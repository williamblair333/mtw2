"""The game must run the bridge in this checkout, never an older one.

Three stamps, each the first 12 hex digits of the bridge file's sha256:
- repo:      lua/parley_bridge.lua in this checkout
- installed: <turn_root>/parley_build.txt, written by scripts/install_bridge.sh
- loaded:    <turn_root>/bridge_loaded_build.txt, written by the bridge when it loads (M.record_build)

Live 11-23: code reached tc by git, which never installs the bridge, so installed and loaded agreed
on the old build, the bench's installed-vs-loaded check passed, and the navy suite tested old Lua.
`ensure_current` compares all three and, on any difference, installs and reloads (game.sh
reload-bridge does both) and waits until the game reports the repo's build.
"""
from __future__ import annotations

import hashlib
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BRIDGE = REPO_ROOT / "lua" / "parley_bridge.lua"


class BridgeStale(RuntimeError):
    """The game still runs another bridge build after a reload."""


def repo_build(bridge: Path = BRIDGE) -> str:
    return hashlib.sha256(bridge.read_bytes()).hexdigest()[:12]


def _stamp(path: Path) -> str | None:
    try:
        return path.read_text().strip() or None
    except FileNotFoundError:
        return None


def stamps(turn_root: Path, bridge: Path = BRIDGE) -> tuple[str, str | None, str | None]:
    return (repo_build(bridge), _stamp(turn_root / "parley_build.txt"),
            _stamp(turn_root / "bridge_loaded_build.txt"))


def _reload() -> None:
    subprocess.run(["bash", str(REPO_ROOT / "scripts" / "game.sh"), "reload-bridge"],
                   cwd=str(REPO_ROOT), check=False)


def ensure_current(turn_root: Path, *, reload: Callable[[], None] = _reload, wait: float = 60.0,
                   poll: float = 2.0, bridge: Path = BRIDGE) -> str:
    """Return the repo's build once the game has it loaded; install and reload first if the
    installed or loaded build differs. Raises BridgeStale if the game hasn't loaded it in `wait` s."""
    repo, installed, loaded = stamps(turn_root, bridge)
    if installed == repo and loaded == repo:
        return repo
    reload()
    deadline = time.monotonic() + wait
    while True:
        repo, installed, loaded = stamps(turn_root, bridge)
        if installed == repo and loaded == repo:
            return repo
        if time.monotonic() >= deadline:
            raise BridgeStale(f"the game runs bridge build {loaded or 'unknown'}, installed is "
                              f"{installed or 'none'}, this checkout's is {repo}; the reload didn't take")
        time.sleep(poll)
