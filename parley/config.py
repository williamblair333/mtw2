"""Per-game settings, loaded from a TOML file. Relative paths resolve against that file."""

import re
import tomllib
from pathlib import Path

from pydantic import BaseModel, field_validator

from parley.control import resolve


class SeatConfig(BaseModel):
    brain: str
    persona: str
    name: str = ""  # display name for messages, e.g. "Doge Enrico"; defaults to the faction
    control: str | list[str] = "ruler"  # a preset (diplomat, ruler, full) or a list of areas
    adviser: str = ""  # Discord username of this ruler's loyal adviser, if any
    # the brain for the game's popup decisions (marriages, adoptions, papal votes, sack or occupy,
    # ransoms, offers), when it differs from `brain` (live: a cheap seat declined a 4-star general)
    decider: str = ""

    @field_validator("control")
    @classmethod
    def _known_control(cls, v):
        resolve(v)
        return v

    @property
    def areas(self) -> tuple[str, ...]:
        return resolve(self.control)


def channel_slug(name: str) -> str:
    """Discord text-channel name: lowercase, letters/digits/dashes."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


class DiscordConfig(BaseModel):
    guild: str
    lobby: str = "lobby"
    game_channel: str = ""  # this game's turn announcements; defaults to the game id


class AutoplayConfig(BaseModel):
    """The bridge ends the human's turn itself, once every ruler has answered."""
    wait: int = 300  # seconds to wait for late rulers before ending the turn anyway
    until_turn: int | None = None  # stop ending turns at this game turn


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
    autoplay: AutoplayConfig | None = None

    def display_names(self) -> dict[str, str]:
        names = {f: (s.name or f) for f, s in self.seats.items()}
        names.update({f: f"{u} ({f})" for f, u in self.humans.items()})
        names.update({f"adviser:{f}": s.adviser for f, s in self.seats.items() if s.adviser})
        return names

    def advisers(self) -> dict[str, str]:
        """faction -> its adviser's Discord username"""
        return {f: s.adviser for f, s in self.seats.items() if s.adviser}

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
    # <name>.hidden.toml, if present, secretly overrides seats (e.g. Old Scratch behind a mask);
    # the game file itself shows nothing.
    hidden_path = path.with_name(f"{path.stem}.hidden.toml")
    if hidden_path.exists():
        secret = tomllib.loads(hidden_path.read_text(encoding="utf-8")).get("seats", {})
        for f, override in secret.items():
            if f not in data.get("seats", {}):
                raise ValueError(f"{hidden_path.name} hides seat {f}, which isn't in {path.name}")
            data["seats"][f].update({k: v for k, v in override.items() if k in ("persona", "brain", "name")})
    # the persona library: the nearest personas/ folder above the config (games/ or games/local/)
    personas_dir = next((d / "personas" for d in path.resolve().parents if (d / "personas").is_dir()),
                        path.parent.parent / "personas")
    _resolve_personas(data.get("seats", {}), personas_dir)
    return GameConfig.model_validate(data)
