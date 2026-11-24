"""Popups the game shows the player: screenshot them, read them, and let the ruler decide."""

import json
import subprocess
import time
from pathlib import Path

import pytest

from parley.popups import Popups, READ_PROMPT, make_reader, parse_decision, read, read_agy


def test_orphan_cutoff_outlasts_the_bridges_decision_wait():
    # a request younger than the bridge's DECIDE_WAIT is still live: deleting it as an orphan would
    # throw away a decision the ruler may still make (the author 10-31: "give Heretic more time")
    import re
    from parley.popups import ORPHAN_AFTER
    lua = (Path(__file__).parent.parent / "lua" / "parley_bridge.lua").read_text(encoding="utf-8")
    decide_wait = int(re.search(r"local READ_WAIT, DECIDE_WAIT = \d+, (\d+)", lua).group(1))
    assert ORPHAN_AFTER > decide_wait


class Recorder:
    def __init__(self, text="A Suitable Prince\nJacob Terrett, Age: 62", choice=None):
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
        if isinstance(self.choice, list):  # one result per look
            return self.choice.pop(0) if self.choice else None
        return self.choice


class Seat:
    def __init__(self, answer):
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


def _answered(root, rid):
    """The turn loop's answer for the bridge to press by element: `.answer` first, then `.done`."""
    assert (root / f"{rid}.done").exists()
    return (root / f"{rid}.answer").read_text()


def test_a_message_is_screenshotted_released_and_read_for_the_ruler(tmp_path):
    p, rec = _popups(tmp_path)
    _req(tmp_path, "popup-22-1", kind="read", event=40)
    p.poll()
    assert (tmp_path / "popup-22-1.done").exists() and len(rec.shots) == 1
    assert p.messages_for("england") == ["A Suitable Prince\nJacob Terrett, Age: 62"]
    assert p.messages_for("england") == []  # delivered once


def test_no_scroll_on_screen_is_not_news(tmp_path):
    # live, turn 73: no scroll open, and the reader transcribed our own Parley overlay as a message
    p, rec = _popups(tmp_path, rec=Recorder(text="NO SCROLL."))
    _req(tmp_path, "popup-73-1", kind="read", event=40)
    p.poll()
    assert p.messages_for("england") == []


def test_offer_prompts_show_the_rulers_own_past_offers():
    # live: every suitor declined from turn 71 to 95, each judged alone, holding a princess for a
    # royal match that never came until she died unmarried
    from parley.popups import marriage_prompt, offer_history
    texts = ["Marriage offer: Howard Peckham (age 47) for your princess. You declined it. Your reason: Too old.",
             "Adoption offer: Garret Harrold (age 23) into your family. You accepted it. Your reason: 3 stars.",
             "Marriage offer: Hugh of_Eynsham (age 43) for your princess. You declined it. Your reason: Mediocre.",
             "Title: Ransom Rejected"]
    history = offer_history(texts)
    assert history.startswith("Marriage offers so far: 2, 0 accepted, 2 declined.")
    assert "- marriage: Howard Peckham (age 47), you declined it: Too old." in history
    assert "- adoption: Garret Harrold (age 23), you accepted it: 3 stars." in history
    p = marriage_prompt("p", "england", {"name": "Davy"}, "reading", history)
    assert "YOUR PAST FAMILY OFFERS" in p and "Hugh of_Eynsham" in p
    assert "YOUR PAST FAMILY OFFERS" not in marriage_prompt("p", "england", {"name": "Davy"}, "reading")
    assert offer_history(["Title: nothing"]) == ""


def test_offer_prompts_say_the_records_are_base_values_and_the_scroll_wins():
    # live: a 4-star Proven Commander's record read "command 0"; Gemini declined him as worthless
    from parley.popups import adoption_prompt, marriage_prompt
    man = {"name": "Howard Peckham", "age": 47, "command": 0, "traits": ["Proven Commander"]}
    for prompt in (marriage_prompt("p", "england", man, "Command ****"),
                   adoption_prompt("p", "england", man, "Command ****")):
        assert "base values, before his traits" in prompt and "trust the scroll" in prompt


def test_the_tick_is_found_with_green_borders_beside_the_scroll(tmp_path):
    # live 11-10 16:31 (turn 126): green province borders at the scroll's edges hid the papal
    # notice's check from find_tick, and End Turn stuck behind the notice
    from PIL import Image, ImageDraw
    from parley.popups import find_tick
    im = Image.new("RGB", (1600, 900), (200, 180, 140))
    d = ImageDraw.Draw(im)
    d.ellipse((785, 384, 815, 414), fill=(40, 200, 40))  # the check
    for x in (410, 1185):  # borders just inside the old 0.25-0.75 band
        d.rectangle((x, 280, x + 4, 660), fill=(40, 200, 40))
    png = tmp_path / "notice.png"
    im.save(png)
    gx, gy = find_tick(png)
    assert abs(gx - 0.5) < 0.01 and abs(gy - 399 / 900) < 0.01


def test_an_accepted_wife_is_answered_for_the_bridge_not_clicked(tmp_path):
    # live 11-10 15:23: England accepted a wife for Arthur Fowler; the accept click crashed the game.
    # The bridge now presses the scroll's accept by element: no click, no Escape
    seat = Seat("ACCEPT. A wife for the young lord.")
    p, rec = _popups(tmp_path, seat=seat, rec=Recorder(choice=CHOICE))
    _req(tmp_path, "popup-79-1", kind="marriage", suitor={"name": "Matilda", "age": 18, "female": True})
    p.poll()
    assert _answered(tmp_path, "popup-79-1") == "accept\n"
    assert rec.clicks == []
    [msg] = p.messages_for("england")
    assert "You accepted" in msg


def test_an_accepted_wife_for_our_own_man_is_answered_for_the_bridge_not_clicked(tmp_path):
    # live 11-10 17:10: the game's offer named our man, Perkin Tyler (no `female`), so #547 missed
    # it, the accept was clicked, and the game crashed
    p, rec = _popups(tmp_path, seat=Seat("ACCEPT. He should marry."), rec=Recorder(choice=CHOICE))
    _req(tmp_path, "popup-147-1", kind="marriage", suitor={"name": "Perkin Tyler", "age": 16, "son": True})
    p.poll()
    assert _answered(tmp_path, "popup-147-1") == "accept\n"
    assert rec.clicks == []
    [msg] = p.messages_for("england")
    assert "a wife for your Perkin Tyler" in msg and "You accepted" in msg


def test_an_accepted_suitor_for_a_princess_is_answered_for_the_bridge_not_clicked(tmp_path):
    p, rec = _popups(tmp_path, seat=Seat("ACCEPT. A good match."), rec=Recorder(choice=CHOICE))
    _req(tmp_path, "popup-79-2", kind="marriage", suitor={"name": "Jacob Terrett", "age": 30})
    p.poll()
    assert _answered(tmp_path, "popup-79-2") == "accept\n"
    assert rec.clicks == []


def test_a_marriage_offer_is_decided_by_the_ruler_then_answered_for_the_bridge(tmp_path):
    seat = Seat("DECLINE. At 62 he will not serve long, and Mixed Loyalties makes him a risk.")
    p, rec = _popups(tmp_path, seat=seat, rec=Recorder(choice=CHOICE))
    _req(tmp_path, "popup-22-2", kind="marriage", suitor={
        "name": "Jacob Terrett", "age": 62, "command": 2, "loyalty": 3, "piety": 4, "chivalry_or_dread": 0,
        "authority": 0, "traits": ["Drillmaster", "MixedLoyalties"]})
    p.poll()
    prompt = seat.prompts[0]
    assert "You are Scratch." in prompt and "Jacob Terrett" in prompt and "age 62" in prompt
    assert "MixedLoyalties" in prompt and "ACCEPT or DECLINE" in prompt
    assert _answered(tmp_path, "popup-22-2") == "decline\n" and rec.clicks == []
    [msg] = p.messages_for("england")
    assert "You declined" in msg and "Mixed Loyalties" in msg


def test_a_message_request_leaves_a_marriage_scroll_to_the_offers_own_request(tmp_path):
    # live 10-30 21:25 (QA field, turn 63): message requests popup-62-943730/1 (events 75, 113) saw the
    # marriage scroll's buttons; 943730 was decided first with a generic prompt and pressed decline at
    # 21:25:21. The marriage request (popup-63-943732) then found no buttons for 25 looks, and the
    # bridge held End Turn "the ruler is deciding a popup" for its full 180 s.
    seat = Seat("ACCEPT. A fine match.")
    # the scroll is up for the first looks, gone once the offer is answered (no last look before
    # the answer any more: the bridge checks the scroll itself)
    rec = Recorder(choice=[CHOICE, CHOICE, CHOICE, None, None, None])
    p, rec = _popups(tmp_path, seat=seat, rec=rec)
    _req(tmp_path, "popup-62-943730", kind="read", event=75)
    _req(tmp_path, "popup-63-943732", kind="marriage", suitor={"name": "Jacob Terrett", "age": 34})
    p.poll()
    assert _answered(tmp_path, "popup-63-943732") == "accept\n"
    assert "ACCEPT or DECLINE" in seat.prompts[0] and "Jacob Terrett" in seat.prompts[0]  # the offer's prompt
    assert len(seat.prompts) == 1  # the message never decides the offer's scroll
    assert (tmp_path / "popup-62-943730.done").exists()  # the message is read once the offer is answered
    assert not (tmp_path / "popup-62-943730.answer").exists() and rec.clicks == []


def test_an_unclear_answer_is_declined_so_autoplay_goes_on(tmp_path):
    # nobody is at the keyboard under autoplay: leaving it open stalls the game (seen live)
    p, rec = _popups(tmp_path, seat=Seat("Hmm, let me think about it."), rec=Recorder(choice=CHOICE))
    _req(tmp_path, "popup-22-3", kind="marriage", suitor={"name": "Jacob", "age": 30})
    p.poll()
    assert _answered(tmp_path, "popup-22-3") == "decline\n" and rec.clicks == []
    [msg] = p.messages_for("england")
    assert "You declined it" in msg and "Nobody answered in time" in msg


def test_a_scroll_gone_while_the_ruler_thought_is_not_clicked(tmp_path):
    # live: Barnaby's adoption was minimized mid-answer, then "accepted" with a click on the map
    p, rec = _popups(tmp_path, rec=Recorder(choice=[CHOICE, CHOICE, None]))
    _req(tmp_path, "popup-37-1", kind="adoption", suitor={"name": "Barnaby", "age": 30})
    p.poll()
    assert rec.clicks == [] and p.messages_for("england") == []


def test_an_offer_minimized_at_once_is_decided_once_the_bridge_reopens_it(tmp_path):
    # live: an offer's icon sat in the minimized stack while the decision waited two minutes
    p, rec = _popups(tmp_path, seat=Seat("ACCEPT a fine match"), rec=Recorder(
        text="A Suitable Prince\nJacob", choice=[None, None, CHOICE, CHOICE]))
    _req(tmp_path, "popup-54-1", kind="marriage", suitor={"name": "Jacob", "age": 30})
    p.poll()
    # the bridge reopens it by its icon's element; the turn loop clicks no icon (deleted 11-21)
    assert rec.clicks == [] and rec.at == []
    assert _answered(tmp_path, "popup-54-1") == "accept\n"


def test_an_offer_with_no_buttons_on_screen_is_never_clicked_blind(tmp_path):
    p, rec = _popups(tmp_path, rec=Recorder(choice=None))
    _req(tmp_path, "popup-22-6", kind="adoption", suitor={"name": "Jacob", "age": 30})
    p.poll()
    assert rec.clicks == [] and not (tmp_path / "popup-22-6.done").exists()


def test_a_usage_limit_pauses_instead_of_declining(tmp_path):
    # live: with the seats out, every offer was declined for the ruler
    from parley.seats.base import SeatLimit

    class Limited(Seat):
        def chat(self, prompt, *, timeout):
            raise SeatLimit("claude usage limit: reached")

    p, rec = _popups(tmp_path, seat=Limited(""), rec=Recorder(choice=CHOICE))
    _req(tmp_path, "popup-33-1", kind="adoption", suitor={"name": "Jacob", "age": 30})
    p.poll()
    assert rec.clicks == [] and (tmp_path / "paused.txt").exists()
    assert not (tmp_path / "popup-33-1.done").exists()
    p.poll()
    assert len(rec.shots) == 2  # nothing more while paused (a first look and a fresh one)
    p.seats["england"] = Seat("ACCEPT a good man")
    from parley import pause
    pause.resume(tmp_path)
    p.poll()  # tried again after the pause
    assert _answered(tmp_path, "popup-33-1") == "accept\n" and rec.clicks == []


def test_a_request_the_bridge_gave_up_on_is_not_acted_on(tmp_path):
    p, rec = _popups(tmp_path, rec=Recorder(choice=CHOICE))
    _req(tmp_path, "popup-22-5", kind="adoption", suitor={"name": "X", "age": 30})
    (tmp_path / "popup-22-5.req").unlink()  # removed by the bridge before the decider got to it
    p._decide({"id": "popup-22-5", "faction": "england", "kind": "adoption"}, tmp_path / "x.png",
              tmp_path / "popup-22-5.req")
    assert rec.clicks == [] and not (tmp_path / "popup-22-5.done").exists()


def test_a_message_under_an_open_choice_scroll_is_only_read(tmp_path):
    p, rec = _popups(tmp_path, seat=Seat("DECLINE no"), rec=Recorder(text="Diplomacy", choice=CHOICE))
    _req(tmp_path, "popup-25-3", kind="choice", what="an AI's diplomatic offer", options=["decline", "accept"])
    p.seen.add("popup-25-3.req")  # being chosen on (the bridge removes it once pressed)
    _req(tmp_path, "popup-25-4", kind="read", event=9)
    p.poll()
    assert rec.clicks == [] and (tmp_path / "popup-25-4.done").exists()


def test_a_leftover_request_from_before_a_reload_is_removed(tmp_path):
    import os
    p, rec = _popups(tmp_path)
    _req(tmp_path, "popup-27-1", kind="adoption", suitor={"name": "X"})
    (tmp_path / "popup-27-1.done").write_text("")
    old = time.time() - 700
    os.utime(tmp_path / "popup-27-1.req", (old, old))
    p.poll()
    assert rec.shots == [] and list(tmp_path.glob("popup-27-1.*")) == []


def test_each_request_is_handled_once(tmp_path):
    p, rec = _popups(tmp_path)
    _req(tmp_path, "popup-22-4", kind="read", event=1)
    p.poll()
    p.poll()
    assert len(rec.shots) == 1


CHOICE = {"accept": (0.475, 0.698), "decline": (0.524, 0.698)}


def test_an_adoption_offer_is_decided_by_the_ruler_then_answered_for_the_bridge(tmp_path):
    seat = Seat("ACCEPT. A loyal young commander strengthens a thin family.")
    p, rec = _popups(tmp_path, seat=seat, rec=Recorder(text="A Candidate for Adoption", choice=CHOICE))
    _req(tmp_path, "popup-23-1", kind="adoption", suitor={"name": "Charles of Hastings", "age": 21,
                                                          "loyalty": 6, "traits": ["GenerallyLoyal"]})
    p.poll()
    prompt = seat.prompts[0]
    assert "decide an adoption" in prompt and "Charles of Hastings, age 21" in prompt and "loyalty 6 of 10" in prompt
    assert _answered(tmp_path, "popup-23-1") == "accept\n" and rec.clicks == []
    assert (tmp_path / "popup-23-1.hold").exists()
    [msg] = p.messages_for("england")
    assert msg.startswith("Adoption offer: Charles of Hastings (age 21)") and "You accepted" in msg


def test_stacked_offers_each_get_their_own_answer(tmp_path):
    # live: Humphrey's adoption scroll came up over Godwine's; Godwine's answer went to Humphrey
    class Screen(Recorder):
        def __init__(self):
            super().__init__(choice=CHOICE)
            self.top = ["Humphrey of Lydham", "Godwine"]

        def read(self, path):  # the bridge closes each answered scroll; the one beneath shows
            return f"A Candidate for Adoption\n{self.top[len(list(tmp_path.glob('*.answer')))]}, Age: 30"

    class Ruler(Seat):
        def chat(self, prompt, *, timeout):
            self.prompts.append(prompt)
            candidate = prompt.split("THE CANDIDATE")[1].split("YOUR PAST FAMILY OFFERS")[0]
            return "DECLINE too old" if "Humphrey" in candidate else "ACCEPT a victor"

    seat, screen = Ruler(""), Screen()
    p, rec = _popups(tmp_path, seat=seat, rec=screen)
    _req(tmp_path, "popup-26-1", kind="adoption", suitor={"name": "Captain Godwine", "age": 21})
    _req(tmp_path, "popup-26-2", kind="adoption", suitor={"name": "Humphrey of_Lydham", "age": 30})
    p.poll()
    # Humphrey's scroll first, then Godwine's; each request answers its own man
    assert _answered(tmp_path, "popup-26-2") == "decline\n" and _answered(tmp_path, "popup-26-1") == "accept\n"
    assert "Humphrey" in seat.prompts[0].split("THE CANDIDATE")[1] and len(seat.prompts) == 2
    assert rec.clicks == []
    msgs = p.messages_for("england")
    assert any("Humphrey of_Lydham" in m and "You declined" in m for m in msgs)
    assert any("Captain Godwine" in m and "You accepted" in m for m in msgs)


def test_any_popup_with_a_check_and_an_x_is_the_rulers_decision(tmp_path):
    seat = Seat("DECLINE. The guild's price is too high this year.")
    reading = "Guild Offer\nThe Masons' Guild offers to build a guild house in York.\nDecision: accept or decline."
    p, rec = _popups(tmp_path, seat=seat, rec=Recorder(text=reading, choice=CHOICE))
    _req(tmp_path, "popup-23-2", kind="read", event=77)
    p.poll()
    assert "Masons' Guild" in seat.prompts[0] and "green check" in seat.prompts[0]
    assert _answered(tmp_path, "popup-23-2") == "decline\n" and rec.clicks == []
    [msg] = p.messages_for("england")
    assert "A decision the game asked of you" in msg and "You declined" in msg


def test_stacked_requests_decide_the_scroll_once(tmp_path):
    # live: five messages at once, every screenshot showing the same top scroll. Each look
    # after the first click finds no buttons, so the later requests are only read.
    seat = Seat("ACCEPT. A wife for Henry costs nothing.")
    # looks per request: at poll (stale, still the scroll), then the fresh one before deciding
    rec = Recorder(text="Bride Presented", choice=[CHOICE, CHOICE, None, CHOICE, None])
    p, rec = _popups(tmp_path, seat=seat, rec=rec)
    for i in (1, 2, 3):
        _req(tmp_path, f"popup-24-{i}", kind="read", event=i)
    for _ in range(3):  # one plain reading per pass: the bridge clears each scroll in between
        p.poll()
    assert _answered(tmp_path, "popup-24-1") == "accept\n" and len(seat.prompts) == 1
    assert all((tmp_path / f"popup-24-{i}.done").exists() for i in (2, 3))
    assert list(tmp_path.glob("*.answer")) == [tmp_path / "popup-24-1.answer"] and rec.clicks == []


def test_the_ruler_chooses_on_a_named_scroll_and_the_bridge_presses_it(tmp_path):
    seat = Seat("SACK. York's treasury will pay for the next army, and these rebels earned no mercy.")
    p, rec = _popups(tmp_path, seat=seat, rec=Recorder(text="Settlement Captured\nYork"))
    _req(tmp_path, "popup-25-1", kind="choice", what="a captured settlement",
         options=["occupy", "sack", "exterminate"])
    p.poll()
    prompt = seat.prompts[0]
    assert "decide a captured settlement" in prompt and "sack: a large gold haul" in prompt
    assert "(OCCUPY, SACK, EXTERMINATE)" in prompt
    assert (tmp_path / "popup-25-1.answer").read_text() == "sack" and rec.clicks == []
    [msg] = p.messages_for("england")
    assert msg.startswith("A captured settlement: you chose to sack.")


def test_an_unclear_choice_gets_the_bridges_default_at_once(tmp_path):
    p, rec = _popups(tmp_path, seat=Seat("Perhaps mercy, perhaps not."))
    _req(tmp_path, "popup-25-2", kind="choice", what="prisoners taken", options=["ransom", "release", "execute"])
    p.poll()
    assert (tmp_path / "popup-25-2.answer").read_text() == "none" and p.messages_for("england") == []


def test_the_ruler_chooses_the_next_pope(tmp_path):
    # live: the papal election sat unanswered and held the turn
    seat = Seat("2. Domingo leans our way, and Rome owes England for its tithes.")
    p, rec = _popups(tmp_path, seat=seat, rec=Recorder(text="1 Ulaszlo\n2 Domingo\n3 Froderigus"))
    p.find_votes = lambda png: [(0.68, 0.39), (0.68, 0.51), (0.68, 0.63)]
    _req(tmp_path, "popup-44-9", kind="vote")
    p.poll()
    assert "College of Cardinals" in seat.prompts[0] and "1 to 3" in seat.prompts[0]
    assert rec.at == [(0.68, 0.51)] and (tmp_path / "popup-44-9.done").exists()
    [msg] = p.messages_for("england")
    assert "voted for candidate 2 of 3" in msg


def test_the_vote_is_answered_for_the_bridge_when_by_element_not_clicked(tmp_path):
    # (a) When by_element is set, ruler answers candidate 2: written to .answer, no click
    seat = Seat("2. Domingo leans our way, and Rome owes England for its tithes.")
    p, rec = _popups(tmp_path, seat=seat, rec=Recorder(text="1 Ulaszlo\n2 Domingo\n3 Froderigus"))
    p.find_votes = lambda png: [(0.68, 0.39), (0.68, 0.51), (0.68, 0.63)]
    _req(tmp_path, "popup-44-9", kind="vote", by_element=True)
    p.poll()
    assert (tmp_path / "popup-44-9.answer").read_text() == "2\n"
    assert (tmp_path / "popup-44-9.done").exists()
    assert rec.clicks == [] and rec.at == []
    [msg] = p.messages_for("england")
    assert "voted for candidate 2 of 3" in msg


def test_the_vote_falls_back_to_click_when_not_by_element(tmp_path):
    # (c) Fallback: without by_element, the old click path still clicks the Vote button
    seat = Seat("2. Domingo leans our way.")
    p, rec = _popups(tmp_path, seat=seat, rec=Recorder(text="1 Ulaszlo\n2 Domingo\n3 Froderigus"))
    p.find_votes = lambda png: [(0.68, 0.39), (0.68, 0.51), (0.68, 0.63)]
    _req(tmp_path, "popup-44-9", kind="vote")
    p.poll()
    assert rec.clicks == ["vote"] and rec.at == [(0.68, 0.51)]
    assert not (tmp_path / "popup-44-9.answer").exists()
    assert (tmp_path / "popup-44-9.done").exists()


def test_a_message_with_a_lone_check_is_acknowledged_not_cleared(tmp_path):
    # live: the papal election's notice, cleared, was only minimized again, turn after turn
    p, rec = _popups(tmp_path, rec=Recorder(text="With the death of the Pope..."))
    p._find_tick = lambda png: (0.5, 0.45)
    _req(tmp_path, "popup-44-1", kind="read", event=202, press_check=True)  # as the bridge asks for it
    p.poll()
    assert rec.at == [(0.5, 0.45)] and (tmp_path / "popup-44-1.done").read_text() == "acked"
    assert p.messages_for("england") == ["With the death of the Pope..."]


def test_a_check_is_not_clicked_unless_the_bridge_asks(tmp_path):
    # live 11-15 turn 1143: this click acknowledged post_battle_scroll and the bridge pressed its tick too;
    # the game faulted. The bridge closes scrolls itself; the turn loop only reads them
    p, rec = _popups(tmp_path, rec=Recorder(text="Captain Humphrey has won a battle"))
    p._find_tick = lambda png: (0.5, 0.45)
    _req(tmp_path, "popup-1143-1", kind="read", event=40)
    p.poll()
    assert rec.clicks == [] and rec.at == []
    assert (tmp_path / "popup-1143-1.done").read_text() == ""
    assert p.messages_for("england") == ["Captain Humphrey has won a battle"]


def test_the_papal_notice_gets_its_check_though_it_looks_like_the_last_reading(tmp_path):
    # live 10-30 19:43:17 (qa-covert turn 48): the stuck turn reopened the papal notice; it looked
    # like the notice read a minute before, so its check was never pressed and the bridge cleared
    # it again, every try. Its check is what opened the election after a reopen (live 18:34:11).
    p, rec = _popups(tmp_path, rec=Recorder(text="With the death of the Pope..."), same=lambda a, b: True)
    p._find_tick = lambda png: (0.5, 0.45)
    p.last_read = tmp_path / "earlier.png"
    _req(tmp_path, "popup-48-2", kind="read", event=202, press_check=True)
    p.poll()
    assert rec.at == [(0.5, 0.45)] and (tmp_path / "popup-48-2.done").read_text() == "acked"


def test_a_stuck_turn_with_a_decision_on_screen_has_the_ruler_decide_it(tmp_path):
    # live: a marriage offer missed its window; recovery only reopened minimized messages and
    # the offer sat on screen all night
    seat = Seat("DECLINE. Actively disloyal, one star: a rebel in waiting.")
    p, rec = _popups(tmp_path, seat=seat, rec=Recorder(text="Davy Heyway, Age: 31", choice=CHOICE))
    _req(tmp_path, "popup-86-m1", kind="minimized")  # _req names england as the faction
    p.poll()
    assert len(seat.prompts) == 1 and rec.clicks == []  # no click on the message stack, nor the scroll
    assert _answered(tmp_path, "popup-86-m1") == "decline\n"


def test_find_choice_needs_a_check_with_an_x_beside_it(tmp_path):
    from PIL import Image, ImageDraw
    from parley.popups import find_choice
    im = Image.new("RGB", (1600, 900), (200, 180, 140))  # parchment
    d = ImageDraw.Draw(im)
    d.ellipse((750, 618, 770, 638), fill=(40, 200, 40))  # the check, live at 760,628
    tick_only = tmp_path / "tick.png"
    im.save(tick_only)
    assert find_choice(tick_only) is None  # a close tick alone is no decision
    d.ellipse((828, 618, 848, 638), fill=(220, 30, 30))  # the X, 78 px right
    d.ellipse((1000, 690, 1020, 710), fill=(220, 30, 30))  # a red shield elsewhere: ignored
    both = tmp_path / "both.png"
    im.save(both)
    c = find_choice(both)
    assert c and abs(c["accept"][0] * 1600 - 760) <= 1 and abs(c["accept"][1] * 900 - 628) <= 1
    assert abs(c["decline"][0] * 1600 - 838) <= 1 and abs(c["decline"][1] * 900 - 628) <= 1
    # live false alarm: the campaign map, green banner icons spread out with red banners near
    for x in range(450, 1150, 140):
        d.ellipse((x, 300, x + 12, 312), fill=(40, 200, 40))
    assert find_choice(_save(im, tmp_path / "map.png")) is None


def _save(im, path):
    im.save(path)
    return path


def test_parse_decision():
    assert parse_decision("ACCEPT - a fine match") == "accept"
    assert parse_decision("decline: too old") == "decline"
    assert parse_decision("I would say no") is None


def test_one_reading_per_poll_pass(tmp_path):
    rec = Recorder()
    p = Popups(tmp_path, "g", {"england": Seat("ACCEPT")}, personas={"england": "You are Scratch."},
               screenshot=rec.screenshot, read=rec.read, click=rec.click, find=rec.find,
               same=lambda a, b: False, background=False)
    _req(tmp_path, "popup-22-1", kind="read", event=40)
    _req(tmp_path, "popup-22-2", kind="read", event=41)
    _req(tmp_path, "popup-22-3", kind="read", event=42)
    p.poll()
    assert len(rec.shots) == 1
    assert len(p.messages_for("england")) == 1
    p.poll()
    assert len(rec.shots) == 2
    assert len(p.messages_for("england")) == 1
    p.poll()
    assert len(rec.shots) == 3
    assert len(p.messages_for("england")) == 1


def test_the_same_scroll_is_not_read_twice(tmp_path):
    rec = Recorder()
    p = Popups(tmp_path, "g", {"england": Seat("ACCEPT")}, personas={"england": "You are Scratch."},
               screenshot=rec.screenshot, read=rec.read, click=rec.click, find=rec.find,
               same=lambda a, b: True, background=False)
    _req(tmp_path, "popup-22-1", kind="read", event=40)
    _req(tmp_path, "popup-22-2", kind="read", event=41)
    p.poll()
    assert (tmp_path / "popup-22-1.done").exists()
    assert len(p.messages_for("england")) == 1
    for _ in range(4):
        p.poll()
        assert not (tmp_path / "popup-22-2.done").exists()
        assert p.messages_for("england") == []
    p.poll()
    assert (tmp_path / "popup-22-2.done").exists()
    assert p.messages_for("england") == []


def test_a_changed_scroll_is_read(tmp_path):
    rec = Recorder()
    p = Popups(tmp_path, "g", {"england": Seat("ACCEPT")}, personas={"england": "You are Scratch."},
               screenshot=rec.screenshot, read=rec.read, click=rec.click, find=rec.find,
               same=lambda a, b: False, background=False)
    _req(tmp_path, "popup-22-1", kind="read", event=40)
    _req(tmp_path, "popup-22-2", kind="read", event=41)
    p.poll()
    p.poll()
    assert len(p.messages_for("england")) == 2


def test_same_scroll_compares_images(tmp_path):
    from PIL import Image, ImageDraw
    from parley.popups import same_scroll

    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    c = tmp_path / "c.png"
    Image.new("RGB", (200, 100), (255, 255, 255)).save(a)
    im_b = Image.new("RGB", (200, 100), (255, 255, 255))
    ImageDraw.Draw(im_b).rectangle((50, 10, 150, 90), fill=(0, 0, 0))
    im_b.save(b)
    Image.new("RGB", (100, 100), (255, 255, 255)).save(c)

    assert same_scroll(a, a) is True
    assert same_scroll(a, b) is False
    assert same_scroll(a, c) is False


def test_popups_report_helper(tmp_path, venice_report):
    p, _ = _popups(tmp_path)
    assert p._report("england", 5) is None

    # Write report at turn 3
    d3 = tmp_path / "g" / "turn-0003" / "england"
    d3.mkdir(parents=True, exist_ok=True)
    (d3 / "state.json").write_text(venice_report.model_dump_json())

    # Asking for turn 5 finds latest earlier (turn 3)
    r = p._report("england", 5)
    assert r is not None

    # Corrupt turn 3 file returns None
    (d3 / "state.json").write_text("invalid json")
    assert p._report("england", 5) is None


def test_opted_in_adoption_strong_candidate_answered_by_steward(tmp_path):
    from jigsaw import DecisionLog
    dlog = DecisionLog(tmp_path / "decisions.db")
    seat = Seat("DECLINE")
    p, rec = _popups(tmp_path, seat=seat, rec=Recorder(text="A Candidate for Adoption\nCharles, Age: 25", choice=CHOICE),
                     ladder={"england"}, decision_log=dlog)
    _req(tmp_path, "popup-22-1", kind="adoption", suitor={"name": "Charles", "age": 25, "command": 6, "loyalty": 6})
    p.poll()
    assert seat.prompts == []
    assert _answered(tmp_path, "popup-22-1") == "accept\n" and rec.clicks == []
    [msg] = p.messages_for("england")
    assert "your steward decided by rule" in msg
    assert "You accepted it" in msg
    rows = dlog.query(actor="england")
    assert len(rows) == 1
    assert rows[0].rung == 2
    assert rows[0].choice == "accept"


def test_opted_in_adoption_unknown_command_escalates_to_llm(tmp_path):
    seat = Seat("ACCEPT. LLM decides.")
    p, rec = _popups(tmp_path, seat=seat, rec=Recorder(text="A Candidate for Adoption\nUnknown, Age: 25", choice=CHOICE),
                     ladder={"england"})
    _req(tmp_path, "popup-22-2", kind="adoption", suitor={"name": "Unknown", "age": 25, "loyalty": 6})
    p.poll()
    assert len(seat.prompts) == 1
    assert _answered(tmp_path, "popup-22-2") == "accept\n" and rec.clicks == []
    [msg] = p.messages_for("england")
    assert "your steward decided by rule" not in msg
    assert "You accepted it" in msg


def test_opted_in_adoption_close_call_goes_to_the_ruler(tmp_path):
    # command 1, loyalty 2, age 50: 5 points against the 6-point baseline, odds 0.42 vs 0.58
    seat = Seat("ACCEPT. A gamble worth taking.")
    p, rec = _popups(tmp_path, seat=seat, rec=Recorder(text="A Candidate for Adoption\nHugh, Age: 50", choice=CHOICE),
                     ladder={"england"})
    _req(tmp_path, "popup-22-5", kind="adoption", suitor={"name": "Hugh", "age": 50, "command": 1, "loyalty": 2})
    p.poll()
    assert len(seat.prompts) == 1 and _answered(tmp_path, "popup-22-5") == "accept\n" and rec.clicks == []
    assert "your steward decided by rule" not in p.messages_for("england")[0]


def test_not_opted_in_adoption_always_calls_llm(tmp_path):
    seat = Seat("ACCEPT. LLM decides.")
    p, rec = _popups(tmp_path, seat=seat, rec=Recorder(text="A Candidate for Adoption\nStrong, Age: 25", choice=CHOICE),
                     ladder=frozenset())
    _req(tmp_path, "popup-22-3", kind="adoption", suitor={"name": "Strong", "age": 25, "command": 6, "loyalty": 6})
    p.poll()
    assert len(seat.prompts) == 1
    assert _answered(tmp_path, "popup-22-3") == "accept\n" and rec.clicks == []
    [msg] = p.messages_for("england")
    assert "your steward decided by rule" not in msg


def test_opted_in_adoption_high_stakes_no_heir_escalates_to_llm(tmp_path, venice_report):
    from parley.protocol import Person
    report = venice_report.model_copy(
        update={
            "faction": "england",
            "family": [
                Person(name="King Henry", role="leader", kind="general", alive=True, family=True)
            ]
        }
    )
    state_dir = tmp_path / "g" / "turn-0022" / "england"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "state.json").write_text(report.model_dump_json())

    seat = Seat("ACCEPT. LLM decides for heirless kingdom.")
    p, rec = _popups(tmp_path, seat=seat, rec=Recorder(text="A Candidate for Adoption\nNoble, Age: 25", choice=CHOICE),
                     ladder={"england"})
    _req(tmp_path, "popup-22-4", kind="adoption", suitor={"name": "Noble", "age": 25, "command": 6, "loyalty": 6})
    p.poll()
    assert len(seat.prompts) == 1
    assert _answered(tmp_path, "popup-22-4") == "accept\n" and rec.clicks == []
    [msg] = p.messages_for("england")
    assert "your steward decided by rule" not in msg


def test_opted_in_marriage_strong_candidate_answered_by_steward(tmp_path):
    from jigsaw import DecisionLog
    dlog = DecisionLog(tmp_path / "decisions.db")
    seat = Seat("DECLINE")
    p, rec = _popups(tmp_path, seat=seat, rec=Recorder(text="A Suitable Prince\nCharles, Age: 25", choice=CHOICE),
                     ladder={"england"}, decision_log=dlog)
    _req(tmp_path, "popup-22-10", kind="marriage", suitor={"name": "Charles", "age": 25, "command": 6, "loyalty": 6})
    p.poll()
    assert seat.prompts == []
    assert _answered(tmp_path, "popup-22-10") == "accept\n" and rec.clicks == []
    [msg] = p.messages_for("england")
    assert "your steward decided by rule" in msg
    assert "You accepted it" in msg
    rows = dlog.query(actor="england")
    assert len(rows) == 1
    assert rows[0].rung == 2
    assert rows[0].kind == "marriage"
    assert rows[0].choice == "accept"
    assert rows[0].outcome == "accept: pressed by the bridge" and rows[0].outcome_turn == 22


def test_steward_outcome_is_handed_to_the_bridge_without_a_last_look(tmp_path):
    from jigsaw import DecisionLog
    dlog = DecisionLog(tmp_path / "decisions.db")
    # up at poll's look and the second look; a third look (gone) is never taken: whether the scroll
    # is still up when the answer lands is the bridge's check, made on the scroll's element
    p, rec = _popups(tmp_path, seat=Seat("DECLINE"), rec=Recorder(text="A Suitable Prince\nCharles, Age: 25",
                     choice=[CHOICE, CHOICE, None]), ladder={"england"}, decision_log=dlog)
    _req(tmp_path, "popup-22-13", kind="marriage", suitor={"name": "Charles", "age": 25, "command": 6, "loyalty": 6})
    p.poll()
    assert _answered(tmp_path, "popup-22-13") == "accept\n" and rec.clicks == []
    assert rec.choice == [None] and len(rec.shots) == 2
    [row] = dlog.query(actor="england")
    assert row.outcome == "accept: pressed by the bridge"


def test_opted_in_marriage_weak_or_old_candidate_declined_by_steward(tmp_path):
    seat = Seat("ACCEPT")
    p, rec = _popups(tmp_path, seat=seat, rec=Recorder(text="A Suitable Prince\nOld Suitor, Age: 65", choice=CHOICE),
                     ladder={"england"})
    _req(tmp_path, "popup-22-11", kind="marriage", suitor={"name": "Old Suitor", "age": 65, "command": 0, "loyalty": 2})
    p.poll()
    assert seat.prompts == []
    assert _answered(tmp_path, "popup-22-11") == "decline\n" and rec.clicks == []
    [msg] = p.messages_for("england")
    assert "your steward decided by rule" in msg
    assert "You declined it" in msg


def test_opted_in_marriage_close_call_goes_to_the_ruler(tmp_path):
    # command 2, loyalty 2, age 50: 7 points against the 8-point baseline, odds 0.42 vs 0.58
    seat = Seat("ACCEPT. A close match.")
    p, rec = _popups(tmp_path, seat=seat, rec=Recorder(text="A Suitable Prince\nHugh, Age: 50", choice=CHOICE),
                     ladder={"england"})
    _req(tmp_path, "popup-22-12", kind="marriage", suitor={"name": "Hugh", "age": 50, "command": 2, "loyalty": 2})
    p.poll()
    assert len(seat.prompts) == 1 and _answered(tmp_path, "popup-22-12") == "accept\n" and rec.clicks == []
    assert "your steward decided by rule" not in p.messages_for("england")[0]


def test_opted_in_captor_answered_ransom_without_asking_seat(tmp_path):
    from jigsaw import DecisionLog
    dlog = DecisionLog(tmp_path / "decisions.db")
    seat = Seat("EXECUTE. Kill them.")
    reading = "Title: Enemies Captured\nRows: Town Militia | 5 | 19\nTotal Ransom Value: 209\nButtons: Ransom, Release, Execute"
    p, rec = _popups(tmp_path, seat=seat, rec=Recorder(text=reading),
                     ladder={"england"}, decision_log=dlog)
    _req(tmp_path, "popup-22-20", kind="choice", what="prisoners taken",
         options=["ransom", "release", "execute"])
    p.poll()
    assert seat.prompts == []
    assert (tmp_path / "popup-22-20.answer").read_text() == "ransom"
    [msg] = p.messages_for("england")
    assert "your steward decided by rule" in msg
    assert "you chose to ransom" in msg
    rows = dlog.query(actor="england")
    assert len(rows) == 1
    assert rows[0].rung == 2
    assert rows[0].kind == "ransom_captor"
    assert rows[0].choice == "accept"
    assert rows[0].outcome == "answered ransom; the bridge presses it"


def test_opted_in_captor_huge_value_goes_to_seat(tmp_path):
    seat = Seat("RELEASE. Mercy for the captured knights.")
    reading = "Title: Enemies Captured\nTotal Ransom Value: 2,500\nButtons: Ransom, Release, Execute"
    p, rec = _popups(tmp_path, seat=seat, rec=Recorder(text=reading), ladder={"england"})
    _req(tmp_path, "popup-22-21", kind="choice", what="prisoners taken",
         options=["ransom", "release", "execute"])
    p.poll()
    assert len(seat.prompts) == 1
    assert (tmp_path / "popup-22-21.answer").read_text() == "release"
    [msg] = p.messages_for("england")
    assert "your steward decided by rule" not in msg
    assert "you chose to release" in msg


def test_opted_in_captive_cheap_price_is_paid(tmp_path, venice_report):
    # treasury = 5000, ransom = 200 florins -> share = 0.04
    report = venice_report.model_copy(update={"faction": "england", "treasury": 5000})
    state_dir = tmp_path / "g" / "turn-0022" / "england"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "state.json").write_text(report.model_dump_json())

    seat = Seat("REFUSE")
    reading = "The enemy holds your men. Ransom: 200 florins."
    p, rec = _popups(tmp_path, seat=seat, rec=Recorder(text=reading), ladder={"england"})
    _req(tmp_path, "popup-22-22", kind="choice", what="a ransom asked",
         options=["pay", "refuse"])
    p.poll()
    assert seat.prompts == []
    assert (tmp_path / "popup-22-22.answer").read_text() == "pay"
    [msg] = p.messages_for("england")
    assert "your steward decided by rule" in msg
    assert "you chose to pay" in msg


def test_opted_in_captive_above_treasury_is_refused(tmp_path, venice_report):
    # treasury = 500, ransom = 1500 florins -> cannot pay
    report = venice_report.model_copy(update={"faction": "england", "treasury": 500})
    state_dir = tmp_path / "g" / "turn-0022" / "england"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "state.json").write_text(report.model_dump_json())

    seat = Seat("PAY")
    reading = "The enemy holds your men. Ransom: 1,500 florins."
    p, rec = _popups(tmp_path, seat=seat, rec=Recorder(text=reading), ladder={"england"})
    _req(tmp_path, "popup-22-23", kind="choice", what="a ransom asked",
         options=["pay", "refuse"])
    p.poll()
    assert seat.prompts == []
    assert (tmp_path / "popup-22-23.answer").read_text() == "refuse"
    [msg] = p.messages_for("england")
    assert "your steward decided by rule" in msg
    assert "you chose to refuse" in msg


def test_opted_in_captive_middling_share_near_crossover_goes_to_seat(tmp_path, venice_report):
    # treasury = 1000, ransom = 200 gold -> share = 0.20
    # accept = 10 * 0.8 - 3 = 5.0, decline = 3 + 10 * 0.2 = 5.0
    # odds are 50/50, gate escalates as close call
    report = venice_report.model_copy(update={"faction": "england", "treasury": 1000})
    state_dir = tmp_path / "g" / "turn-0022" / "england"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "state.json").write_text(report.model_dump_json())

    seat = Seat("PAY. We need those veteran soldiers.")
    reading = "Demand for release: 200 gold."
    p, rec = _popups(tmp_path, seat=seat, rec=Recorder(text=reading), ladder={"england"})
    _req(tmp_path, "popup-22-24", kind="choice", what="a ransom asked",
         options=["pay", "refuse"])
    p.poll()
    assert len(seat.prompts) == 1
    assert (tmp_path / "popup-22-24.answer").read_text() == "pay"
    [msg] = p.messages_for("england")
    assert "your steward decided by rule" not in msg
    assert "you chose to pay" in msg


def test_seat_not_in_ladder_always_goes_to_seat(tmp_path):
    # captor with low value, but ladder does not include england
    seat = Seat("EXECUTE. Off with their heads.")
    reading = "Title: Enemies Captured\nTotal Ransom Value: 209\nButtons: Ransom, Release, Execute"
    p, rec = _popups(tmp_path, seat=seat, rec=Recorder(text=reading), ladder=frozenset())
    _req(tmp_path, "popup-22-25", kind="choice", what="prisoners taken",
         options=["ransom", "release", "execute"])
    p.poll()
    assert len(seat.prompts) == 1
    assert (tmp_path / "popup-22-25.answer").read_text() == "execute"
    [msg] = p.messages_for("england")
    assert "your steward decided by rule" not in msg


def test_read_agy_command_and_stdout(monkeypatch, tmp_path):
    png = tmp_path / "test.png"
    png.write_bytes(b"dummy png bytes")
    seen = {}

    def fake_run(cmd, capture_output=True, text=True, timeout=120, env=None, cwd=None):
        seen["cmd"] = cmd
        seen["kw"] = {"capture_output": capture_output, "text": text, "timeout": timeout, "env": env, "cwd": cwd}
        assert (Path(cwd) / "popup.png").read_bytes() == b"dummy png bytes"
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="A Suitable Marriage\nLord John\nACCEPT\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = read_agy(png, model="gemini-3.8-flash-low", timeout=60)
    assert result == "A Suitable Marriage\nLord John\nACCEPT"
    assert seen["cmd"] == ["agy", "-p", READ_PROMPT, "--model", "gemini-3.8-flash-low", "--sandbox", "--disable-slash-commands"]
    assert seen["kw"]["timeout"] == 60
    assert not Path(seen["kw"]["cwd"]).exists()


def test_make_reader_parsing(monkeypatch):
    from parley import popups
    calls = []
    monkeypatch.setattr(popups.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(popups, "read", lambda path, *, model: calls.append(("claude", path, model)) or "from claude")
    monkeypatch.setattr(popups, "read_agy", lambda path, *, model: calls.append(("agy", path, model)) or "from agy")

    r_claude = make_reader("claude:haiku")
    assert r_claude(Path("c.png")) == "from claude"
    assert calls == [("claude", Path("c.png"), "haiku")]

    calls.clear()
    r_agy = make_reader("agy:gemini-3.8-flash-low")
    assert r_agy(Path("a.png")) == "from agy"
    assert calls == [("agy", Path("a.png"), "gemini-3.8-flash-low")]

    with pytest.raises(ValueError):
        make_reader("agy:")

    with pytest.raises(ValueError):
        make_reader("other:model")


# --- the papal window: the turn loop keeps its hands off the papal election ----------------
# live 10-30: the game died at 18:34:11, 19:04:51, 20:06:30 and 20:48:34 with a turn loop click
# landing in the same second as a papal scroll opening (a notice's check, a stale request's
# check, a marriage declined). The bridge writes papal_window.txt from the Pope's death notice
# (202) until the result has closed; meanwhile the loop presses nothing but the vote (and, before
# the election opens, the notice's check that #280 asks for).

def _papal(root, phase, secs=60):
    (root / "papal_window.txt").write_text(f"phase={phase}\nuntil={time.time() + secs:.0f}\n")


def test_papal_phase_reads_the_bridges_window_and_ignores_an_old_one(tmp_path):
    from parley.popups import papal_phase
    assert papal_phase(tmp_path) is None
    _papal(tmp_path, "results")
    assert papal_phase(tmp_path) == "results"
    _papal(tmp_path, "vote", secs=-5)  # left behind by a crash: over
    assert papal_phase(tmp_path) is None
    (tmp_path / "papal_window.txt").write_text("garbage")
    assert papal_phase(tmp_path) is None


def test_nothing_is_screenshotted_or_pressed_while_the_papal_window_is_open(tmp_path):
    p, rec = _popups(tmp_path)
    p._find_tick = lambda png: (0.5, 0.45)
    _papal(tmp_path, "results")
    _req(tmp_path, "popup-59-1", kind="read", event=40)
    p.poll()
    p.poll()
    assert rec.shots == [] and rec.clicks == [] and not (tmp_path / "popup-59-1.done").exists()
    (tmp_path / "papal_window.txt").unlink()  # the result has closed
    p.poll()
    # read, not clicked: the bridge closes it (one closer per scroll, 11-15 turn 1143)
    assert rec.clicks == [] and (tmp_path / "popup-59-1.done").read_text() == ""


def test_a_decision_answered_as_the_papal_window_opens_is_handed_over_after_it_without_asking_again(tmp_path):
    # live 20:48:31-34 (qa-field turn 59): a marriage declined; the click landed as the papal
    # result opened, and the game died
    class Late(Seat):
        def chat(self, prompt, *, timeout):
            _papal(tmp_path, "results")  # the result opens while the ruler thinks
            return super().chat(prompt, timeout=timeout)

    seat = Late("DECLINE too old")
    p, rec = _popups(tmp_path, seat=seat, rec=Recorder(text="A Suitable Prince\nJacob", choice=CHOICE))
    _req(tmp_path, "popup-59-2", kind="marriage", suitor={"name": "Jacob", "age": 62})
    p.poll()
    assert rec.clicks == [] and len(seat.prompts) == 1
    assert not (tmp_path / "popup-59-2.answer").exists() and not (tmp_path / "popup-59-2.done").exists()
    p.poll()  # still open: still nothing
    assert not (tmp_path / "popup-59-2.answer").exists()
    (tmp_path / "papal_window.txt").unlink()
    p.poll()
    assert _answered(tmp_path, "popup-59-2") == "decline\n" and len(seat.prompts) == 1  # the ruler's answer, kept
    assert rec.clicks == []
    assert any("You declined it" in m for m in p.messages_for("england"))


def test_the_vote_is_still_clicked_in_the_papal_window(tmp_path):
    p, rec = _popups(tmp_path, seat=Seat("2 the better man"), rec=Recorder(text="1 A\n2 B"))
    p.find_votes = lambda png: [(0.68, 0.39), (0.68, 0.51)]
    _papal(tmp_path, "vote")
    _req(tmp_path, "popup-44-3", kind="vote")
    p.poll()
    assert rec.clicks == ["vote"] and rec.at == [(0.68, 0.51)]


def test_a_vote_is_not_clicked_once_the_result_is_up(tmp_path):
    # live 18:17:57: a second vote click landed after the result was up
    p, rec = _popups(tmp_path, seat=Seat("1"), rec=Recorder(text="1 A\n2 B"))
    p.find_votes = lambda png: [(0.68, 0.39), (0.68, 0.51)]
    _papal(tmp_path, "results")
    _req(tmp_path, "popup-44-4", kind="vote")
    p.poll()
    assert rec.clicks == []


def test_the_notice_check_is_pressed_only_before_the_election_opens(tmp_path):
    p, rec = _popups(tmp_path, rec=Recorder(text="With the death of the Pope..."))
    p._find_tick = lambda png: (0.5, 0.45)
    _papal(tmp_path, "notice")
    _req(tmp_path, "popup-48-5", kind="read", event=202, press_check=True)
    p.poll()
    assert rec.clicks == ["accept"]  # #280: the check opens the election
    _papal(tmp_path, "vote")  # the vote scroll is up: its own check-like marks are not the notice's
    _req(tmp_path, "popup-48-6", kind="read", event=202, press_check=True)
    p.poll()
    assert rec.clicks == ["accept"] and not (tmp_path / "popup-48-6.done").exists()


def test_an_offer_waiting_for_its_buttons_reopens_nothing_in_the_papal_window(tmp_path):
    # live 20:48:11 and 20:56:13: "reopened a minimized message to find it" before a papal result
    p, rec = _popups(tmp_path, rec=Recorder(text="A Suitable Prince\nJacob", choice=None))
    _req(tmp_path, "popup-59-7", kind="marriage", suitor={"name": "Jacob", "age": 30})
    p.poll()
    assert rec.at == [] and rec.clicks == []  # nothing pressed (no icon click since 11-21)
    assert (tmp_path / "popup-59-7.req").exists()


def test_the_real_click_is_refused_before_it_looks_up_a_window(monkeypatch):
    # the click was deleted 11-21 (no screen input): refused whatever the papal guard says
    from parley import popups
    from parley.xinput import XInputRefused
    done = []
    monkeypatch.setattr(popups, "_window", lambda: done.append("window") or "7")
    monkeypatch.setattr(popups, "_xdo", lambda *args: done.append(args) or "")
    for guard in (lambda: True, lambda: False):
        with pytest.raises(XInputRefused):
            popups.click("decline", (0.5, 0.5), guard=guard)
    assert done == []


def test_a_stuck_turn_escape_dismisses_the_scroll_without_a_screenshot(tmp_path):
    # live 11-10 09:41: papal_election_results_scroll stayed open after End Turn; one Escape closed it
    dismissed = []
    p, rec = _popups(tmp_path, dismiss=dismissed.append)
    _req(tmp_path, "popup-42-e1", kind="escape", scroll="papal_election_results_scroll")
    p.poll()
    assert len(dismissed) == 1 and dismissed[0]["scroll"] == "papal_election_results_scroll"
    assert rec.shots == [] and rec.clicks == [] and list(tmp_path.glob("popup-42-e1*")) == []


def test_a_stuck_turn_escape_is_dropped_in_the_papal_window(tmp_path):
    dismissed = []
    p, rec = _popups(tmp_path, dismiss=dismissed.append)
    _papal(tmp_path, "notice")
    _req(tmp_path, "popup-46-e1", kind="escape", scroll="papal_election_results_scroll")
    p.poll()
    assert dismissed == [] and rec.clicks == [] and rec.shots == []
    assert list(tmp_path.glob("popup-46-e1*")) == []



