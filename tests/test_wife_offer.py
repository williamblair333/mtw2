"""The game's marriage offer comes in two kinds under one event: a man as a suitor for a princess, and a
woman as a wife for one of the ruler's men. The prompt, the record and the steward's score all treated
every offer as a suitor (HANDOFF 11-06: "for your princess" for a man's marriage offer)."""
from test_popups import CHOICE, Recorder, Seat, _popups, _req

from parley.popups import OFFER, marriage_prompt

WIFE = {"name": "Udeline of_Painswick", "age": 24, "female": True}
SUITOR = {"name": "Francis of_Berwick", "age": 20, "command": 3}


def test_a_wife_offer_is_put_to_the_ruler_as_a_wife():
    prompt = marriage_prompt("You are Scratch.", "england", WIFE, "")
    assert "wife for one of your men" in prompt and "Udeline of_Painswick" in prompt
    assert "princess" not in prompt and "THE SUITOR" not in prompt and "adopts him" not in prompt


def test_the_scripted_ruler_can_answer_both_kinds():
    # 11-06: "forced_wife_accepted_by_click" passed 3 times without a click: the wife prompt lacked the
    # words ScriptSeat answers on, so it said nothing and the offer was declined
    from parley.seats.script import _CHOICE_ASKED
    assert _CHOICE_ASKED in marriage_prompt("P", "england", WIFE, "")
    assert _CHOICE_ASKED in marriage_prompt("P", "england", SUITOR, "")


def test_a_suitor_offer_keeps_its_wording():
    prompt = marriage_prompt("You are Scratch.", "england", SUITOR, "")
    assert "THE SUITOR" in prompt and "Your princess stops being a diplomat" in prompt
    assert "wife for one of your men" not in prompt


def _decide(tmp_path, suitor):
    seat = Seat("DECLINE. No.")
    p, _rec = _popups(tmp_path, seat=seat, rec=Recorder(choice=CHOICE), dismiss=lambda r: None)
    _req(tmp_path, "popup-22-2", kind="marriage", suitor=suitor)
    p.poll()
    return p, seat


def test_the_rulers_record_of_a_wife_offer_says_so_and_still_counts_as_an_offer(tmp_path):
    p, seat = _decide(tmp_path, WIFE)
    assert seat.prompts, "the ruler decides a wife offer"
    [msg] = p.messages_for("england")
    assert "as a wife for one of your men" in msg and "for your princess" not in msg
    assert OFFER.match(msg)


def test_a_suitors_record_keeps_its_wording(tmp_path):
    p, _seat = _decide(tmp_path, SUITOR)
    [msg] = p.messages_for("england")
    assert "for your princess" in msg and OFFER.match(msg)


def _retries(tmp_path, suitor):
    """How many times the offer was put back because the screen didn't name this person."""
    rec = Recorder(text="A young woman of fitting breeding", choice=CHOICE)
    p, _ = _popups(tmp_path, seat=Seat("DECLINE. No."), rec=rec, dismiss=lambda r: None)
    put_back, requeue = [], p._requeue
    p._requeue = lambda *a: (put_back.append(a), requeue(*a))[1]
    _req(tmp_path, "popup-22-2", kind="marriage", suitor=suitor)
    p.poll()
    return len(put_back)


def test_a_wife_offer_never_waits_for_her_name_on_screen(tmp_path):
    # bench 11-06 07:08: "the screen shows someone else's offer" until the bridge's wait ran out
    assert _retries(tmp_path, WIFE) == 0


def test_a_suitor_whose_name_isnt_on_screen_still_waits_for_his_own_scroll(tmp_path):
    assert _retries(tmp_path, SUITOR) == 3


def test_the_steward_does_not_score_a_wife_as_a_suitor(tmp_path):
    p, _rec = _popups(tmp_path, seat=Seat("DECLINE. No."), rec=Recorder(choice=CHOICE), dismiss=lambda r: None)
    called = []
    p._steward = lambda *a: called.append(a) or (None, None)
    _req(tmp_path, "popup-22-2", kind="marriage", suitor=WIFE)
    p.poll()
    assert called == []
    _req(tmp_path, "popup-22-3", kind="marriage", suitor=SUITOR)
    p.poll()
    assert len(called) == 1
