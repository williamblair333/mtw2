"""Wire format between the game (Lua) and the orchestrator. IDs are game-internal names."""

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field

PROTOCOL_VERSION = 1

Stance = Literal["war", "peace", "alliance", "neutral"]


class Settlement(BaseModel):
    id: str
    name: str
    region: str
    garrison_strength: int
    population: int
    buildings: list[str]


class Army(BaseModel):
    id: str
    leader: str | None = None  # absent, not null: the game's Lua JSON can't write null
    x: int
    y: int
    strength: int
    units: int
    in_settlement: str | None = None


class FactionView(BaseModel):
    id: str
    name: str
    stance: Stance


class OrderResult(BaseModel):
    index: int
    type: str
    ok: bool
    reason: str = ""


class StateReport(BaseModel):
    protocol: int
    game_id: str
    turn: int
    year: int
    faction: str
    treasury: int
    income: int
    settlements: list[Settlement]
    armies: list[Army]
    factions: list[FactionView]
    visible_enemies: list[Army]
    last_results: list[OrderResult]


class SendGold(BaseModel):
    type: Literal["send_gold"] = "send_gold"
    to: str
    amount: int


class CedeSettlement(BaseModel):
    type: Literal["cede_settlement"] = "cede_settlement"
    settlement: str
    to: str


class SetStance(BaseModel):
    type: Literal["set_stance"] = "set_stance"
    to: str
    stance: Literal["war", "peace", "alliance"]


class MarchOn(BaseModel):
    type: Literal["march_on"] = "march_on"
    army: str
    target_settlement: str


class Besiege(BaseModel):
    type: Literal["besiege"] = "besiege"
    army: str
    settlement: str


class Withdraw(BaseModel):
    type: Literal["withdraw"] = "withdraw"
    army: str
    to_settlement: str


Order = Annotated[
    Union[SendGold, CedeSettlement, SetStance, MarchOn, Besiege, Withdraw],
    Field(discriminator="type"),
]


class Say(BaseModel):
    """A message to post: to "lobby" (public) or to a faction ID (private)."""
    to: str
    text: str


class Orders(BaseModel):
    protocol: int
    game_id: str
    turn: int
    faction: str
    orders: list[Order]
    messages: list[Say] = []
    note: str = ""


def orders_json_schema() -> dict:
    return Orders.model_json_schema()
