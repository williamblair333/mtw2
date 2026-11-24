"""A family offer is answered by the bridge, which presses the scroll's button by its element: the
turn loop writes `.answer` (accept/decline) then `.done`, and neither clicks nor presses Escape. Clicks
on these scrolls crashed the game (11-05 11:57, 12:15, 19:59; 11-06 04:11), though not every time;
Escape closed a declined one (11-06 05:44-05:48, the test laptop) but could never say yes. press_escape
itself is still used for the bridge's stuck-turn "escape" requests, tested below."""
import pytest
from test_popups import CHOICE, Recorder, Seat, _answered, _popups, _req

import parley.popups as popups
from parley.popups import PapalHold, Popups, press_escape
from parley.xinput import XInputRefused

SUITOR = {"name": "Jacob Terrett", "age": 62}


def _answer(tmp_path, answer, kind="marriage"):
    pressed = []
    p, rec = _popups(tmp_path, seat=Seat(answer), rec=Recorder(choice=CHOICE), dismiss=pressed.append)
    _req(tmp_path, "popup-22-2", kind=kind, suitor=SUITOR)
    p.poll()
    return p, rec, pressed


def test_a_declined_marriage_is_answered_for_the_bridge_never_clicked_or_escaped(tmp_path):
    p, rec, pressed = _answer(tmp_path, "DECLINE. Too old.")
    assert _answered(tmp_path, "popup-22-2") == "decline\n"
    assert pressed == [] and rec.clicks == []
    assert "You declined" in p.messages_for("england")[0]


def test_an_unclear_answer_is_answered_decline_with_no_escape(tmp_path):
    _, rec, pressed = _answer(tmp_path, "hmm")
    assert _answered(tmp_path, "popup-22-2") == "decline\n"
    assert pressed == [] and rec.clicks == []


def test_an_accepted_marriage_is_answered_accept_for_the_bridge_not_clicked(tmp_path):
    _, rec, pressed = _answer(tmp_path, "ACCEPT. A good man.")
    assert _answered(tmp_path, "popup-22-2") == "accept\n"
    assert pressed == [] and rec.clicks == []


def test_an_adoption_decline_is_answered_for_the_bridge_not_clicked(tmp_path):
    _, rec, pressed = _answer(tmp_path, "DECLINE. No.", kind="adoption")
    assert _answered(tmp_path, "popup-22-2") == "decline\n"
    assert pressed == [] and rec.clicks == []


@pytest.mark.parametrize("answer", ["DECLINE. No.", "ACCEPT. Yes."])
def test_the_real_turn_loop_answers_a_marriage_with_no_escape_and_no_click(tmp_path, monkeypatch, answer):
    # no click= and no dismiss=: what the turn loop builds; any X input would reach _xdo
    rec, pressed, xdo = Recorder(choice=CHOICE), [], []
    monkeypatch.setattr(popups, "press_escape", lambda guard=None: pressed.append(guard))
    monkeypatch.setattr(popups, "_xdo", lambda *args: xdo.append(args) or "")
    p = Popups(tmp_path, "g", {"england": Seat(answer)}, personas={"england": "You are Scratch."},
               screenshot=rec.screenshot, read=rec.read, find=rec.find, background=False)
    _req(tmp_path, "popup-22-2", kind="marriage", suitor=SUITOR)
    p.poll()
    assert _answered(tmp_path, "popup-22-2") == ("decline\n" if answer.startswith("DECLINE") else "accept\n")
    assert pressed == [] and xdo == []


@pytest.fixture
def xdo(monkeypatch):
    calls = []
    def fake(*args):
        calls.append(args)
        return "99\n" if args[0] == "getactivewindow" else ""
    monkeypatch.setattr(popups, "_xdo", fake)
    monkeypatch.setattr(popups, "_window", lambda: "7")
    monkeypatch.setattr(popups.time, "sleep", lambda _: None)
    return calls


def test_press_escape_is_always_refused_and_touches_no_window(xdo, monkeypatch):
    # the key press was deleted 11-21 (no screen input): refused with or without the variable
    for value in ("1", None):
        if value is None:
            monkeypatch.delenv("PARLEY_NO_X_INPUT", raising=False)
        else:
            monkeypatch.setenv("PARLEY_NO_X_INPUT", value)
        with pytest.raises(XInputRefused):
            press_escape(guard=lambda: False)
    assert xdo == []
