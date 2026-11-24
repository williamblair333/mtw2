"""The game runs this checkout's bridge, never an older one (parley.bridge_build). Live 11-22 x3 and
11-23 navy: the bench tested old Lua; on 11-23 code reached tc by git, which never installs the
bridge, so installed and loaded agreed on the old build and the old check passed."""
from types import SimpleNamespace

import pytest

from parley.bridge_build import BridgeStale, ensure_current, repo_build


def _root(tmp_path, installed, loaded):
    bridge = tmp_path / "parley_bridge.lua"
    bridge.write_text("-- new\n")
    root = tmp_path / "turns"
    root.mkdir()
    for name, v in (("parley_build.txt", installed), ("bridge_loaded_build.txt", loaded)):
        if v is not None:
            (root / name).write_text(v + "\n")
    return bridge, root


def _clock(monkeypatch):
    import parley.bridge_build as bb
    now = [0.0]
    monkeypatch.setattr(bb, "time", SimpleNamespace(monotonic=lambda: now[0],
                                                    sleep=lambda s: now.__setitem__(0, now[0] + s)))


def test_all_three_builds_agree_no_reload(tmp_path):
    bridge, root = _root(tmp_path, None, None)
    new = repo_build(bridge)
    for name in ("parley_build.txt", "bridge_loaded_build.txt"):
        (root / name).write_text(new + "\n")
    calls = []
    assert ensure_current(root, reload=lambda: calls.append(1), bridge=bridge) == new
    assert calls == []


@pytest.mark.parametrize("installed, loaded", [("old", "old"), ("new", "old"), (None, None), ("old", "new")])
def test_any_difference_installs_reloads_and_waits_for_the_new_build(tmp_path, monkeypatch, installed, loaded):
    bridge, root = _root(tmp_path, None, None)
    new = repo_build(bridge)
    _root_vals = {"old": "aaaaaaaaaaaa", "new": new, None: None}
    for name, v in (("parley_build.txt", _root_vals[installed]), ("bridge_loaded_build.txt", _root_vals[loaded])):
        if v is not None:
            (root / name).write_text(v + "\n")
    _clock(monkeypatch)

    def reload():  # game.sh reload-bridge: install writes the stamp, the game loads and records it
        (root / "parley_build.txt").write_text(new + "\n")
        (root / "bridge_loaded_build.txt").write_text(new + "\n")

    assert ensure_current(root, reload=reload, bridge=bridge) == new


def test_a_reload_that_does_not_take_is_an_error_naming_all_three(tmp_path, monkeypatch):
    bridge, root = _root(tmp_path, "aaaaaaaaaaaa", "aaaaaaaaaaaa")
    _clock(monkeypatch)
    with pytest.raises(BridgeStale, match=r"runs bridge build aaaaaaaaaaaa, installed is aaaaaaaaaaaa, "
                                          r"this checkout's is " + repo_build(bridge)):
        ensure_current(root, reload=lambda: None, bridge=bridge)
