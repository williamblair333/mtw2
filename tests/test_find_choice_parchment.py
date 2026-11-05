from PIL import Image, ImageDraw

from parley.popups import find_choice


def _screen(tmp_path, ground):
    # a check and an X 80 px apart, as on every decision scroll (live: 760,628 and 840,628)
    im = Image.new("RGB", (1600, 900), (40, 60, 90))
    d = ImageDraw.Draw(im)
    d.rectangle((600, 560, 1000, 700), fill=ground)
    d.ellipse((745, 613, 775, 643), fill=(30, 200, 40))
    d.ellipse((825, 613, 855, 643), fill=(210, 40, 40))
    png = tmp_path / "screen.png"
    im.save(png)
    return png


def test_buttons_on_parchment_are_a_decision(tmp_path):
    found = find_choice(_screen(tmp_path, (227, 209, 184)))
    assert found and round(found["accept"][0] * 1600) == 760 and round(found["decline"][0] * 1600) == 840


def test_a_label_with_more_green_than_the_button_doesnt_hide_it(tmp_path):
    # live, turn 60: Edinburgh's label icons (72 green px) beside the scroll outnumbered the
    # marriage's check (61), so no blob held 80% and the offer went unanswered for 15 tries
    png = _screen(tmp_path, (227, 209, 184))
    im = Image.open(png)
    ImageDraw.Draw(im).rectangle((1100, 280, 1190, 300), fill=(30, 200, 40))  # on the map
    im.save(png)
    found = find_choice(png)
    assert found and round(found["accept"][0] * 1600) == 760


def test_green_and_red_on_the_snowy_map_are_not(tmp_path):
    # live, turn 27: Edinburgh's label passed for a decision, and the stuck turn never
    # reopened the minimized "Bride Presented" scroll that held it
    assert find_choice(_screen(tmp_path, (186, 195, 204))) is None
