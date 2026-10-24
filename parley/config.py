"""Per-game settings, loaded from a TOML file. Relative paths resolve against that file."""

import re
import tomllib
from pathlib import Path

from pydantic import BaseModel


class SeatConfig(BaseModel):
    brain: str
    persona: str
    name: str = ""  # display name for messages, e.g. "Doge Enrico"; defaults to the faction


def channel_slug(name: str) -> str:
    """Discord text-channel name: lowercase, letters/digits/dashes."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


class DiscordConfig(BaseModel):
    guild: str
    lobby: str = "lobby"
    game_channel: str = ""  # this game's turn announcements; defaults to the game id


class GameConfig(BaseModel):
    game_id: str
    turn_root: Path
    save_dir: Path
    backup_dir: Path | None = None
    scenario: str = ""
    seat_timeout: float = 120
    keep_backups: int = 20
    seats: dict[str, SeatConfig]
    humans: dict[str, str] = {}  # faction -> Discord username
    discord: DiscordConfig | None = None

    def display_names(self) -> dict[str, str]:
        names = {f: (s.name or f) for f, s in self.seats.items()}
        names.update({f: f"{u} ({f})" for f, u in self.humans.items()})
        return names

    def model_post_init(self, _ctx) -> None:
        if self.backup_dir is None:
            self.backup_dir = self.turn_root.parent / "backups"
        if self.discord and not self.discord.game_channel:
            self.discord.game_channel = channel_slug(self.game_id)


def _resolve_personas(seats: dict, personas_dir: Path) -> None:
    """persona = "@id" pulls text (and a default name) from the persona library."""
    library = None
    for faction, seat in seats.items():
        ref = seat.get("persona", "")
        if not ref.startswith("@"):
            continue
        if library is None:
            from parley.personas import load_personas
            library = load_personas(personas_dir)
        p = library.get(ref[1:])
        if p is None:
            raise ValueError(f"unknown persona '{ref}' for seat {faction} (looked in {personas_dir})")
        seat["persona"] = p.persona
        seat.setdefault("name", p.name)


def load_config(path: Path) -> GameConfig:
    path = Path(path)
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    for key in ("turn_root", "save_dir", "backup_dir"):
        if key in data:
            data[key] = (path.parent / Path(data[key]).expanduser()).resolve()
    # the persona library: the nearest personas/ folder above the config (games/ or games/local/)
    personas_dir = next((d / "personas" for d in path.resolve().parents if (d / "personas").is_dir()),
                        path.parent.parent / "personas")
    _resolve_personas(data.get("seats", {}), personas_dir)
    return GameConfig.model_validate(data)
