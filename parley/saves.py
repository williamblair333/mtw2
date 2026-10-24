"""Copy the newest campaign save aside before each LLM turn, keeping the last N."""

import shutil
from pathlib import Path


def backup_saves(save_dir: Path, backup_root: Path, label: str, keep: int) -> Path | None:
    saves = sorted(Path(save_dir).glob("*.sav"), key=lambda p: p.stat().st_mtime)
    if not saves:
        return None
    backup_root = Path(backup_root)
    backup_root.mkdir(parents=True, exist_ok=True)
    newest = saves[-1]
    dest = backup_root / f"{label}-{newest.name}"
    shutil.copy2(newest, dest)
    backups = sorted(backup_root.glob("*.sav"), key=lambda p: (p.stat().st_mtime, p.name))
    for old in backups[: max(0, len(backups) - keep)]:
        old.unlink(missing_ok=True)
    return dest
