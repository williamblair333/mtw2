"""Popups the game shows the player: screenshot them, read them, and let the ruler decide."""

import json
import time

from parley.popups import Popups, parse_decision


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


def _popups(tmp_path, seat=None, rec=None):
    rec = rec or Recorder()
    p = Popups(tmp_path, "g", {"england": seat or Seat("ACCEPT")}, personas={"england": "You are Scratch."},
               screenshot=rec.screenshot, read=rec.read, click=rec.click, find=rec.find, background=False)
    return p, rec


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


def test_a_marriage_offer_is_decided_by_the_ruler_then_clicked(tmp_path):
    seat = Seat("DECLINE. At 62 he will not serve long, and Mixed Loyalties makes him a risk.")
    p, rec = _popups(tmp_path, seat=seat, rec=Recorder(choice=CHOICE))
    _req(tmp_path, "popup-22-2", kind="marriage", suitor={
        "name": "Jacob Terrett", "age": 62, "command": 2, "loyalty": 3, "piety": 4, "chivalry_or_dread": 0,
        "authority": 0, "traits": ["Drillmaster", "MixedLoyalties"]})
    p.poll()
    prompt = seat.prompts[0]
    assert "You are Scratch." in prompt and "Jacob Terrett" in prompt and "age 62" in prompt
    assert "MixedLoyalties" in prompt and "ACCEPT or DECLINE" in prompt
    assert rec.clicks == ["decline"] and (tmp_path / "popup-22-2.done").exists()
    [msg] = p.messages_for("england")
    assert "You declined" in msg and "Mixed Loyalties" in msg


def test_an_unclear_answer_is_declined_so_autoplay_goes_on(tmp_path):
    # nobody is at the keyboard under autoplay: leaving it open stalls the game (seen live)
    p, rec = _popups(tmp_path, seat=Seat("Hmm, let me think about it."), rec=Recorder(choice=CHOICE))
    _req(tmp_path, "popup-22-3", kind="marriage", suitor={"name": "Jacob", "age": 30})
    p.poll()
    assert rec.clicks == ["decline"] and (tmp_path / "popup-22-3.done").exists()
    [msg] = p.messages_for("england")
    assert "You declined it" in msg and "Nobody answered in time" in msg


def test_a_scroll_gone_while_the_ruler_thought_is_not_clicked(tmp_path):
    # live: Barnaby's adoption was minimized mid-answer, then "accepted" with a click on the map
    p, rec = _popups(tmp_path, rec=Recorder(choice=[CHOICE, CHOICE, None]))
    _req(tmp_path, "popup-37-1", kind="adoption", suitor={"name": "Barnaby", "age": 30})
    p.poll()
    assert rec.clicks == [] and p.messages_for("england") == []


def test_an_offer_minimized_at_once_is_reopened_to_be_decided(tmp_path):
    # live: an offer's icon sat in the minimized stack while the decision waited two minutes
    p, rec = _popups(tmp_path, seat=Seat("ACCEPT a fine match"), rec=Recorder(
        text="A Suitable Prince\nJacob", choice=[None, None, CHOICE, CHOICE]))
    p.find_slots = lambda png: [(0.02, 0.74)]
    _req(tmp_path, "popup-54-1", kind="marriage", suitor={"name": "Jacob", "age": 30})
    p.poll()
    assert rec.at[0] == (0.02, 0.74)  # the stack is opened first
    assert rec.clicks[-1] == "accept" and (tmp_path / "popup-54-1.done").exists()


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
    assert rec.clicks == ["accept"]


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


def test_an_adoption_offer_is_decided_by_the_ruler_then_clicked_where_found(tmp_path):
    seat = Seat("ACCEPT. A loyal young commander strengthens a thin family.")
    p, rec = _popups(tmp_path, seat=seat, rec=Recorder(text="A Candidate for Adoption", choice=CHOICE))
    _req(tmp_path, "popup-23-1", kind="adoption", suitor={"name": "Charles of Hastings", "age": 21,
                                                          "loyalty": 6, "traits": ["GenerallyLoyal"]})
    p.poll()
    prompt = seat.prompts[0]
    assert "decide an adoption" in prompt and "Charles of Hastings, age 21" in prompt and "loyalty 6 of 10" in prompt
    assert rec.clicks == ["accept"] and rec.at == [CHOICE["accept"]]
    assert (tmp_path / "popup-23-1.done").exists() and (tmp_path / "popup-23-1.hold").exists()
    [msg] = p.messages_for("england")
    assert msg.startswith("Adoption offer: Charles of Hastings (age 21)") and "You accepted" in msg


def test_stacked_offers_each_get_their_own_answer(tmp_path):
    # live: Humphrey's adoption scroll came up over Godwine's; Godwine's answer went to Humphrey
    class Screen(Recorder):
        def __init__(self):
            super().__init__(choice=CHOICE)
            self.top = ["Humphrey of Lydham", "Godwine"]

        def read(self, path):
            return f"A Candidate for Adoption\n{self.top[0]}, Age: 30"

        def click(self, which, at=None):
            super().click(which, at)
            self.top.pop(0)  # the answered scroll closes; the one beneath shows

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
    assert rec.clicks == ["decline", "accept"]  # Humphrey's scroll first, then Godwine's
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
    assert rec.clicks == ["decline"] and rec.at == [CHOICE["decline"]]
    [msg] = p.messages_for("england")
    assert "A decision the game asked of you" in msg and "You declined" in msg


def test_stacked_requests_decide_the_scroll_once(tmp_path):
    # live: five messages at once, every screenshot showing the same top scroll. Each look
    # after the first click finds no buttons, so the later requests are only read.
    seat = Seat("ACCEPT. A wife for Henry costs nothing.")
    # looks per request: at poll (stale, still the scroll), then the fresh one before deciding
    rec = Recorder(text="Bride Presented", choice=[CHOICE, CHOICE, CHOICE, None, CHOICE, None])
    p, rec = _popups(tmp_path, seat=seat, rec=rec)
    for i in (1, 2, 3):
        _req(tmp_path, f"popup-24-{i}", kind="read", event=i)
    for _ in range(3):  # one plain reading per pass: the bridge clears each scroll in between
        p.poll()
    assert rec.clicks == ["accept"] and len(seat.prompts) == 1
    assert all((tmp_path / f"popup-24-{i}.done").exists() for i in (1, 2, 3))


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


def test_a_message_with_a_lone_check_is_acknowledged_not_cleared(tmp_path):
    # live: the papal election's notice, cleared, was only minimized again, turn after turn
    p, rec = _popups(tmp_path, rec=Recorder(text="With the death of the Pope..."))
    p._find_tick = lambda png: (0.5, 0.45)
    _req(tmp_path, "popup-44-1", kind="read", event=202)
    p.poll()
    assert rec.at == [(0.5, 0.45)] and (tmp_path / "popup-44-1.done").read_text() == "acked"
    assert p.messages_for("england") == ["With the death of the Pope..."]


def test_a_stuck_turn_reopens_minimized_messages_one_slot_at_a_time(tmp_path):
    # a minimized decision blocks End Turn unseen; plain notices reopened get minimized again,
    # so each stuck look opens the next slot up
    slots = [(0.02, 0.74), (0.02, 0.68), (0.02, 0.62)]
    p, rec = _popups(tmp_path)
    p.find_slots = lambda png: slots
    for i in range(4):
        _req(tmp_path, f"popup-42-m{i}", kind="minimized")
        p.poll()
    assert rec.at == [slots[0], slots[1], slots[2], slots[0]]
    assert list(tmp_path.glob("popup-42-m*")) == []  # nobody waits on these


def test_a_stuck_turn_with_a_decision_on_screen_has_the_ruler_decide_it(tmp_path):
    # live: a marriage offer missed its window; recovery only reopened minimized messages and
    # the offer sat on screen all night
    seat = Seat("DECLINE. Actively disloyal, one star: a rebel in waiting.")
    p, rec = _popups(tmp_path, seat=seat, rec=Recorder(text="Davy Heyway, Age: 31", choice=CHOICE))
    p.find_slots = lambda png: [(0.02, 0.74)]
    _req(tmp_path, "popup-86-m1", kind="minimized")  # _req names england as the faction
    p.poll()
    assert len(seat.prompts) == 1 and rec.clicks == ["decline"]
    assert rec.at == [CHOICE["decline"]]  # no click on the message stack


def test_a_screen_job_clicks_each_card_then_closes_the_scroll(tmp_path):
    # retraining: the bridge opens the Retrain tab and lists the cards; the loop clicks them
    p, rec = _popups(tmp_path)
    cards = [[596 / 1024, 363 / 768], [639 / 1024, 363 / 768]]
    _req(tmp_path, "popup-128-r1", kind="clicks", what="retrain London", cards=cards)
    p.poll()
    assert rec.at == [tuple(cards[1]), tuple(cards[0]), Popups.SEAL]  # last first: clicked cards shift the rest
    assert (tmp_path / "popup-128-r1.done").exists()


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
