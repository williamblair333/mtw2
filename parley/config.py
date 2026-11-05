"""Per-game settings, loaded from a TOML file. Relative paths resolve against that file."""

import re
import tomllib
from pathlib import Path

from pydantic import BaseModel, field_validator

from parley.control import resolve
from parley.seats.base import RulerBudget


class SeatConfig(BaseModel):
    brain: str
    persona: str
    name: str = ""  # display name for messages, e.g. "Doge Enrico"; defaults to the faction
    control: str | list[str] = "ruler"  # a preset (diplomat, ruler, full) or a list of areas
    adviser: str = ""  # Discord username of this ruler's loyal adviser, if any
    # the brain for the game's popup decisions (marriages, adoptions, papal votes, sack or occupy,
    # ransoms, offers), when it differs from `brain` (live: a cheap seat declined a 4-star general)
    decider: str = ""
    fallback: str = ""  # backup brain asked once when `brain` fails a turn (live: agy hung 4 of 11 turns)
    # freeze the faction's own game AI (freezeFactionAI) so it can't undo the ruler's orders (live:
    # England's AI walked Captain John away from Caernarvon each turn); give such a seat full control
    freeze: bool = False
    # algorithm deciders first (Jigsaw); the ruler's LLM only when the gate escalates; opt-in per seat
    ladder: bool = False
    # a steward fills gaps the ruler left, never overriding an order: recruits one cheap unit in a
    # settlement the ruler's orders leave without a garrison (needs the "recruit" area), unless the
    # ruler lists it in hold_empty; the ruler is told next turn. Opt-in per seat.
    steward: bool = False
    # cheap brain used on quiet turns when ladder is true (e.g. "agy:gemini-3.8-flash-low")
    quiet_brain: str = ""
    # top up treasury at turn start for live testing; spoils economic judgement
    playtest_funds: bool = False
    playtest_funds_amount: int = 50000
    # this seat's own think/answer budget ([seats.x.ruler_budget]); the game's [ruler_budget] otherwise
    ruler_budget: RulerBudget | None = None

    @field_validator("playtest_funds_amount")
    @classmethod
    def _positive_funds_amount(cls, v: int) -> int:
        if v <= 0:
            raise ValueError(f"playtest_funds_amount must be greater than 0, got {v}")
        return v

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
    # End Turn waits (bounded) for the ruler's answer to an offer on screen (the papal click race)
    hold_decisions: bool = True
    # papal scrolls get no work inside their open event (onScrollOpened returns at once: Lua work
    # there preceded the results crashes); the bridge finds the vote scroll from its per-frame
    # tick after the Pope's death notice, so the ruler still votes. Off: the old in-event handling
    papal_hands_off: bool = True


class GameConfig(BaseModel):
    game_id: str
    turn_root: Path
    save_dir: Path
    mod_save_dir: Path | None = None
    backup_dir: Path | None = None
    scenario: str = ""
    seat_timeout: float = 120
    fallback_reserve: float = 90
    # seconds a ruler has to answer a popup decision (marriage, adoption, an AI's offer). The author 10-31:
    # "give Heretic more time": at 120 s a decision queued behind both busy Heretic slots and timed
    # out ("returned no content before its time ran out"); the bridge waits DECIDE_WAIT (540) for it
    decide_timeout: float = 480
    # how long a streamed ruler (heretic/openai) may think and write inside seat_timeout
    ruler_budget: RulerBudget = RulerBudget()
    keep_backups: int = 20
    campaign_length: str = "long"  # the Campaign Rules chosen at the start: which victory goal applies
    reader: str = "claude:haiku"
    seats: dict[str, SeatConfig]
    humans: dict[str, str] = {}  # faction -> Discord username
    discord: DiscordConfig | None = None
    autoplay: AutoplayConfig | None = None
    # QA bench: freeze the game AI of every AI faction (bridge.txt `freeze=*`), a quiet world where
    # no faction acts unless named in `thaw` (a case that needs an AI siege or offer)
    freeze_others: bool = False
    thaw: list[str] = []

    @field_validator("reader")
    @classmethod
    def _known_reader(cls, v: str) -> str:
        kind, _, model = v.partition(":")
        if kind not in ("claude", "agy") or not model:
            raise ValueError(f"reader must be 'claude:<model>' or 'agy:<model>', got {v!r}")
        return v

    def budget_for(self, faction: str) -> RulerBudget:
        seat = self.seats.get(faction)
        return seat.ruler_budget if seat and seat.ruler_budget else self.ruler_budget

    def display_names(self) -> dict[str, str]:
        names = {f: (s.name or f) for f, s in self.seats.items()}
        names.update({f: f"{u} ({f})" for f, u in self.humans.items()})
        names.update({f"adviser:{f}": s.adviser for f, s in self.seats.items() if s.adviser})
        return names

    def advisers(self) -> dict[str, str]:
        """faction -> its adviser's Discord username"""
        return {f: s.adviser for f, s in self.seats.items() if s.adviser}

    def brains(self) -> dict[str, str]:
        """faction -> its ruler's model spec, shown on its Discord lines"""
        return {f: s.brain for f, s in self.seats.items()}

    def model_post_init(self, _ctx) -> None:
        if self.mod_save_dir is None:
            self.mod_save_dir = self.save_dir.parent / "mods" / "parley" / "saves"
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
    for key in ("turn_root", "save_dir", "mod_save_dir", "backup_dir"):
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
