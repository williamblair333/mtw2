"""`just seat-set`: change one live seat setting safely (live 11-23: a hand-typed cp broke on a
line wrap, and its rerun overwrote the only backup of the old config)."""
import pytest

from parley.config import load_config
from parley.seat_set import SeatSetError, set_seat_option

CONFIG = """\
game_id = "g"
turn_root = "{root}/turns"
save_dir = "{root}/saves"

[seats.england]
brain = "fake"
persona = "p"

[seats.france]
brain = "fake"  # a comment that must survive
persona = "p"
control = "full"
"""


@pytest.fixture
def cfg(tmp_path):
    (tmp_path / "saves").mkdir()
    p = tmp_path / "scratch.toml"
    p.write_text(CONFIG.format(root=tmp_path))
    return p


def test_it_adds_a_setting_to_one_seat_and_keeps_the_rest(cfg):
    set_seat_option(cfg, "france", "lookups", "true")
    c = load_config(cfg)
    assert c.seats["france"].lookups is True and c.seats["england"].lookups is False
    assert '# a comment that must survive' in cfg.read_text()


def test_it_replaces_a_setting_already_there(cfg):
    set_seat_option(cfg, "france", "control", '"ruler"')
    text = cfg.read_text()
    assert text.count("control =") == 1 and load_config(cfg).seats["france"].control == "ruler"


def test_every_run_keeps_its_own_backup(cfg):
    original = cfg.read_text()
    b1 = set_seat_option(cfg, "france", "lookups", "true")
    b2 = set_seat_option(cfg, "france", "lookups", "true")  # a rerun must not overwrite b1
    assert b1 != b2 and b1.read_text() == original and b2.exists()


def test_an_unknown_key_or_seat_is_refused_and_nothing_changes(cfg):
    original = cfg.read_text()
    with pytest.raises(SeatSetError):
        set_seat_option(cfg, "france", "lookupz", "true")
    with pytest.raises(SeatSetError):
        set_seat_option(cfg, "spain", "lookups", "true")
    assert cfg.read_text() == original


def test_a_value_the_config_rejects_puts_the_old_file_back(cfg):
    original = cfg.read_text()
    with pytest.raises(SeatSetError):
        set_seat_option(cfg, "france", "control", '"emperor"')  # not a control preset
    with pytest.raises(SeatSetError):
        set_seat_option(cfg, "france", "lookups", "tru e")  # not a TOML value
    assert cfg.read_text() == original
