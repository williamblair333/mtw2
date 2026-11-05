from test_popups import Recorder, Seat, _popups, _req


def test_the_ruler_remembers_what_the_offer_was(tmp_path):
    # live, turn 8: the ruler's own ceasefire with Scotland read back only as "an ai's
    # diplomatic offer", so its next turn blamed the game's AI for the peace
    seat = Seat("ACCEPT. A ceasefire costs me nothing.")
    p, rec = _popups(tmp_path, seat=seat, rec=Recorder(text="Their offers\nScotland: Ceasefire"))
    _req(tmp_path, "popup-7-1", kind="choice", what="an ai's diplomatic offer", options=["decline", "accept"])
    p.poll()
    [msg] = p.messages_for("england")
    assert msg.startswith("An ai's diplomatic offer: you chose to accept.")
    assert "The scroll showed: Their offers Scotland: Ceasefire." in msg
    assert msg.endswith("Your reason: A ceasefire costs me nothing.")
