"""parley.popups.make_reader says once at start when its command isn't installed: live 11-05 15:05
(the test laptop) the reader was agy, which isn't installed there, and every popup logged "reading failed:
[Errno 2] No such file or directory: 'agy'"; the rulers got no message text."""

import logging
import shutil

from parley import popups


def test_a_reader_whose_command_is_missing_is_reported_at_start(monkeypatch, caplog):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with caplog.at_level(logging.WARNING, logger="parley.popups"):
        popups.make_reader("agy:gemini-3.8-flash-low")
    assert "the agy command isn't installed here" in caplog.text


def test_a_missing_reader_reads_nothing_instead_of_failing_each_popup(monkeypatch):
    # live 11-05 19:54 (the test laptop): an ERROR "reading failed: ... 'agy'" for every popup after the warning
    monkeypatch.setattr(shutil, "which", lambda name: None)
    reader = popups.make_reader("agy:gemini-3.8-flash-low")
    monkeypatch.setattr(popups.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("ran")))
    assert reader("x.png") == ""


def test_an_installed_reader_says_nothing(monkeypatch, caplog):
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    with caplog.at_level(logging.WARNING, logger="parley.popups"):
        popups.make_reader("claude:haiku")
    assert caplog.text == ""
