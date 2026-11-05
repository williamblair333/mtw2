"""Tests for deterministic star counter on Medieval II character scrolls."""

import json
from pathlib import Path
from PIL import Image
import pytest

from parley.popups import Popups, count_stars

FIXTURES_DIR = Path("tests/fixtures/scrolls")
CHOICE = {"accept": (0.475, 0.698), "decline": (0.524, 0.698)}


class Recorder:
    def __init__(self, text="A Suitable Prince\nCharles, Age: 25", choice=None):
        self.shots, self.clicks, self.text, self.choice, self.at = [], [], text, choice, []

    def screenshot(self, path):
        self.shots.append(path)
        path.write_bytes(b"png")

    def read(self, path):
        return self.text

    def click(self, which, at=None):
        self.clicks.append(which)
        self.at.append(at)

    def find(self, path):
        if isinstance(self.choice, list):
            return self.choice.pop(0) if self.choice else None
        return self.choice


class Seat:
    def __init__(self, answer="ACCEPT"):
        self.answer, self.prompts = answer, []

    def chat(self, prompt, *, timeout):
        self.prompts.append(prompt)
        return self.answer


def _req(root, rid, **fields):
    (root / f"{rid}.req").write_text(json.dumps({"id": rid, "turn": 22, "faction": "england", **fields}))


def _popups(tmp_path, seat=None, rec=None, **kwargs):
    rec = rec or Recorder()
    p = Popups(tmp_path, "g", {"england": seat or Seat("ACCEPT")}, personas={"england": "You are Scratch."},
               screenshot=rec.screenshot, read=rec.read, click=rec.click, find=rec.find, background=False,
               **kwargs)
    return p, rec


def test_fixture_counts():
    cases = [
        ("popup-2-1655907-stats.png", {"command": 1, "chivalry_or_dread": 4, "loyalty": 9, "piety": 3}),
        ("popup-1-1655901-stats.png", {"command": 1, "chivalry_or_dread": 1, "loyalty": 7, "piety": 3}),
        ("popup-7-3510304-stats.png", {"command": 1, "chivalry_or_dread": 1, "loyalty": 4, "piety": 4}),
    ]
    for filename, expected in cases:
        path = FIXTURES_DIR / filename
        assert count_stars(path) == expected


def test_blank_parchment_gives_none(tmp_path):
    blank_png = tmp_path / "blank.png"
    Image.new("RGB", (640, 160), (225, 205, 175)).save(blank_png)
    assert count_stars(blank_png) is None


def test_full_window_screenshot_counts(tmp_path):
    # Real crops were taken at offset (480, 100) on 1600x900.
    # Test at various vertical offsets (e.g. 70, 100, 140) to verify finding in full window screenshot.
    crop = Image.open(FIXTURES_DIR / "popup-2-1655907-stats.png")
    expected = {"command": 1, "chivalry_or_dread": 4, "loyalty": 9, "piety": 3}
    for y_offset in (70, 100, 140):
        full = Image.new("RGB", (1600, 900), (180, 160, 130))
        full.paste(crop, (480, y_offset))
        full_png = tmp_path / f"full_{y_offset}.png"
        full.save(full_png)
        assert count_stars(full_png) == expected


def test_steward_uses_counted_stars(tmp_path):
    # When suitor record in the game event is all zeros at offer time,
    # count_stars overrides the zeroes and allows the steward to decide by rule.
    counted = {"command": 4, "chivalry_or_dread": 2, "loyalty": 7, "piety": 3}
    seat = Seat("DECLINE")
    rec = Recorder(text="A Suitable Prince\nCharles, Age: 25", choice=CHOICE)
    p, _ = _popups(tmp_path, seat=seat, rec=rec, ladder={"england"}, count_stars=lambda _: counted)
    _req(tmp_path, "popup-22-1", kind="marriage",
         suitor={"name": "Charles", "age": 25, "command": 0, "loyalty": 0, "piety": 0, "chivalry_or_dread": 0})
    p.poll()

    assert seat.prompts == []
    assert rec.clicks == ["accept"] and rec.at == [CHOICE["accept"]]
    assert (tmp_path / "popup-22-1.done").exists()
    [msg] = p.messages_for("england")
    assert "your steward decided by rule" in msg
    assert "You accepted it" in msg


def test_steward_escalates_when_count_stars_returns_none(tmp_path):
    # When count_stars returns None, the all-zero record escalates to the ruler.
    seat = Seat("ACCEPT")
    rec = Recorder(text="A Suitable Prince\nCharles, Age: 25", choice=CHOICE)
    p, _ = _popups(tmp_path, seat=seat, rec=rec, ladder={"england"}, count_stars=lambda _: None)
    _req(tmp_path, "popup-22-2", kind="marriage",
         suitor={"name": "Charles", "age": 25, "command": 0, "loyalty": 0, "piety": 0, "chivalry_or_dread": 0})
    p.poll()

    assert len(seat.prompts) == 1
    assert rec.clicks == ["accept"]
    assert (tmp_path / "popup-22-2.done").exists()
    [msg] = p.messages_for("england")
    assert "your steward decided by rule" not in msg


def test_counted_stars_line_added_to_ruler_prompt(tmp_path):
    # When count_stars finds stars on a close call that goes to ruler,
    # the reading in the prompt includes "Stars counted from the screen: ..."
    counted = {"command": 1, "chivalry_or_dread": 4, "loyalty": 9, "piety": 3}
    seat = Seat("ACCEPT")
    rec = Recorder(text="A Suitable Prince\nCharles, Age: 50", choice=CHOICE)
    p, _ = _popups(tmp_path, seat=seat, rec=rec, count_stars=lambda _: counted)
    _req(tmp_path, "popup-22-3", kind="marriage",
         suitor={"name": "Charles", "age": 50, "command": 0, "loyalty": 0, "piety": 0, "chivalry_or_dread": 0})
    p.poll()

    assert len(seat.prompts) == 1
    prompt = seat.prompts[0]
    assert "Stars counted from the screen: command 1, chivalry 4, loyalty 9, piety 3" in prompt
