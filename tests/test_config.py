from parley.config import SeatConfig, load_config


def test_seat_config_ladder_default():
    seat = SeatConfig(brain="fake", persona="p")
    assert seat.ladder is False


def test_seat_config_ladder_parses_true(tmp_path):
    p = tmp_path / "game.toml"
    p.write_text("""
game_id = "test"
turn_root = "/tmp/turns"
save_dir = "/tmp/saves"
backup_dir = "/tmp/backups"

[seats.venice]
brain = "fake"
persona = "p"
ladder = true
""")
    cfg = load_config(p)
    assert cfg.seats["venice"].ladder is True


def test_game_config_reader_default(tmp_path):
    p = tmp_path / "game.toml"
    p.write_text("""
game_id = "test"
turn_root = "/tmp/turns"
save_dir = "/tmp/saves"
backup_dir = "/tmp/backups"

[seats.venice]
brain = "fake"
persona = "p"
""")
    cfg = load_config(p)
    assert cfg.reader == "claude:haiku"


def test_game_config_reader_agy(tmp_path):
    p = tmp_path / "game.toml"
    p.write_text("""
game_id = "test"
turn_root = "/tmp/turns"
save_dir = "/tmp/saves"
backup_dir = "/tmp/backups"
reader = "agy:gemini-3.8-flash-low"

[seats.venice]
brain = "fake"
persona = "p"
""")
    cfg = load_config(p)
    assert cfg.reader == "agy:gemini-3.8-flash-low"


def test_game_config_reader_invalid(tmp_path):
    import pytest
    p = tmp_path / "game.toml"
    p.write_text("""
game_id = "test"
turn_root = "/tmp/turns"
save_dir = "/tmp/saves"
backup_dir = "/tmp/backups"
reader = "bogus"

[seats.venice]
brain = "fake"
persona = "p"
""")
    with pytest.raises(ValueError):
        load_config(p)


def test_seat_config_playtest_funds_default():
    seat = SeatConfig(brain="fake", persona="p")
    assert seat.playtest_funds is False
    assert seat.playtest_funds_amount == 50000


def test_seat_config_playtest_funds_read(tmp_path):
    p = tmp_path / "game.toml"
    p.write_text("""
game_id = "test"
turn_root = "/tmp/turns"
save_dir = "/tmp/saves"
backup_dir = "/tmp/backups"

[seats.england]
brain = "fake"
persona = "p"
playtest_funds = true
playtest_funds_amount = 75000
""")
    cfg = load_config(p)
    assert cfg.seats["england"].playtest_funds is True
    assert cfg.seats["england"].playtest_funds_amount == 75000


def test_seat_config_playtest_funds_default_amount_when_not_specified(tmp_path):
    p = tmp_path / "game.toml"
    p.write_text("""
game_id = "test"
turn_root = "/tmp/turns"
save_dir = "/tmp/saves"
backup_dir = "/tmp/backups"

[seats.england]
brain = "fake"
persona = "p"
playtest_funds = true
""")
    cfg = load_config(p)
    assert cfg.seats["england"].playtest_funds is True
    assert cfg.seats["england"].playtest_funds_amount == 50000


def test_seat_config_playtest_funds_amount_rejected_if_zero_or_negative(tmp_path):
    import pytest
    p = tmp_path / "game.toml"
    p.write_text("""
game_id = "test"
turn_root = "/tmp/turns"
save_dir = "/tmp/saves"
backup_dir = "/tmp/backups"

[seats.england]
brain = "fake"
persona = "p"
playtest_funds = true
playtest_funds_amount = 0
""")
    with pytest.raises(ValueError, match="greater than 0"):
        load_config(p)

    p.write_text("""
game_id = "test"
turn_root = "/tmp/turns"
save_dir = "/tmp/saves"
backup_dir = "/tmp/backups"

[seats.england]
brain = "fake"
persona = "p"
playtest_funds = true
playtest_funds_amount = -5000
""")
    with pytest.raises(ValueError, match="greater than 0"):
        load_config(p)


def test_game_config_mod_save_dir_default(tmp_path, monkeypatch):
    from parley.config import GameConfig

    direct = GameConfig(
        game_id="test",
        turn_root=tmp_path / "game" / "parley_turns",
        save_dir=tmp_path / "game" / "saves",
        seats={"england": SeatConfig(brain="fake", persona="p")},
    )
    assert direct.save_dir == tmp_path / "game" / "saves"
    assert direct.mod_save_dir == tmp_path / "game" / "mods" / "parley" / "saves"

    monkeypatch.setenv("HOME", str(tmp_path))
    p = tmp_path / "game.toml"
    p.write_text("""
game_id = "test"
turn_root = "~/game/parley_turns"
save_dir = "~/game/saves"

[seats.england]
brain = "fake"
persona = "p"
""")
    cfg = load_config(p)
    assert cfg.save_dir == (tmp_path / "game" / "saves").resolve()
    assert cfg.mod_save_dir == (tmp_path / "game" / "mods" / "parley" / "saves").resolve()


def test_game_config_mod_save_dir_override_and_expansion(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    p = tmp_path / "cfg" / "game.toml"
    p.parent.mkdir(parents=True)
    p.write_text("""
game_id = "test"
turn_root = "~/game/parley_turns"
save_dir = "~/game/saves"
mod_save_dir = "~/custom_mod_saves"

[seats.england]
brain = "fake"
persona = "p"
""")
    cfg = load_config(p)
    assert cfg.save_dir == (tmp_path / "game" / "saves").resolve()
    assert cfg.mod_save_dir == (tmp_path / "custom_mod_saves").resolve()

    p.write_text("""
game_id = "test"
turn_root = "../game/parley_turns"
save_dir = "../game/saves"
mod_save_dir = "../game/mods/other/saves"

[seats.england]
brain = "fake"
persona = "p"
""")
    cfg_rel = load_config(p)
    assert cfg_rel.mod_save_dir == (tmp_path / "game" / "mods" / "other" / "saves").resolve()

