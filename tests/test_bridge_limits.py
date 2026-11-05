"""Limits the game's Lua puts on the bridge file, checked before it reaches the game."""

import re
from pathlib import Path

BRIDGE = Path(__file__).resolve().parent.parent / "lua" / "parley_bridge.lua"
LUA_LOCALS = 200  # Lua's limit on locals in one function; the file's main chunk is one
HEADROOM = 10


def _top_level_locals(src: str) -> int:
    n = 0
    for line in src.splitlines():
        if re.match(r"^local\s+function\s+\w+", line):
            n += 1
        elif m := re.match(r"^local\s+([\w\s,]+?)(=|$)", line):
            n += len([x for x in m.group(1).split(",") if x.strip()])
    return n


def test_the_bridge_keeps_headroom_under_luas_local_limit():
    # live (2026-10-29): one helper too many took the main chunk past 200 locals; the game's
    # reload then failed to load the bridge at all and the game had to be relaunched
    n = _top_level_locals(BRIDGE.read_text())
    assert n <= LUA_LOCALS - HEADROOM, (
        f"parley_bridge.lua has {n} top-level locals (Lua allows {LUA_LOCALS}); put new constants "
        f"in the K table or helpers on M instead of new top-level locals")
