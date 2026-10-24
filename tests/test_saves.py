import os

from parley.saves import backup_saves


def test_backup_rotation(tmp_path):
    saves, backups = tmp_path / "saves", tmp_path / "backups"
    saves.mkdir()
    sav = saves / "campaign.sav"
    for i in range(25):
        sav.write_text(f"turn {i}")
        os.utime(sav, (1000 + i, 1000 + i))
        backup_saves(saves, backups, label=f"turn-{i:04d}", keep=20)
    kept = sorted(p.name for p in backups.iterdir())
    assert len(kept) == 20
    assert kept[-1] == "turn-0024-campaign.sav"
    assert "turn-0004-campaign.sav" not in kept


def test_backup_picks_newest_save(tmp_path):
    saves, backups = tmp_path / "saves", tmp_path / "backups"
    saves.mkdir()
    (saves / "old.sav").write_text("old")
    os.utime(saves / "old.sav", (1000, 1000))
    (saves / "new.sav").write_text("new")
    os.utime(saves / "new.sav", (2000, 2000))
    out = backup_saves(saves, backups, label="t1", keep=5)
    assert out.read_text() == "new"


def test_backup_without_saves_returns_none(tmp_path):
    (tmp_path / "saves").mkdir()
    assert backup_saves(tmp_path / "saves", tmp_path / "b", label="t", keep=5) is None
