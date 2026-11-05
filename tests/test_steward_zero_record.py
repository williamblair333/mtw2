from test_popups import CHOICE, Recorder, Seat, _popups, _req


def test_all_zero_record_goes_to_the_ruler(tmp_path):
    # live, 2026-10-26: the game's record read 0/0 at offer time while the scroll showed
    # command 1, loyalty 7; the steward declined on the zeros
    seat = Seat("ACCEPT")
    p, rec = _popups(tmp_path, seat=seat, rec=Recorder(text="A Suitable Prince\nToby Fitzneale, Age: 31", choice=CHOICE),
                     ladder={"england"})
    _req(tmp_path, "popup-1-1", kind="marriage",
         suitor={"name": "Toby Fitzneale", "age": 31, "command": 0, "loyalty": 0, "piety": 0, "chivalry_or_dread": 0})
    p.poll()
    assert len(seat.prompts) == 1
    assert "Command" in seat.prompts[0] and rec.clicks == ["accept"]
    [msg] = p.messages_for("england")
    assert "your steward decided by rule" not in msg
