"""Wire format between the game (Lua) and the orchestrator. IDs are game-internal names."""

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, PrivateAttr, field_validator

PROTOCOL_VERSION = 1

Stance = Literal["war", "peace", "alliance", "neutral"]


TaxLevel = Literal["low", "normal", "high", "extortionate"]


class BuildOption(BaseModel):
    building: str  # the level's name, e.g. "market"; what a build order names
    cost: int
    turns: int


class RecruitOption(BaseModel):
    unit: str  # the unit type, e.g. "Italian Spear Militia"; what a recruit order names
    cost: int
    turns: int


class Unit(BaseModel):
    type: str
    soldiers: int
    max_soldiers: int = 0
    exp: int = 0


class Training(BaseModel):
    unit: str
    ready_turn: int


class Siege(BaseModel):
    by: str | None = None  # the besieging general
    faction: str | None = None
    strength: int | None = None
    turns: int | None = None  # how long it has lasted
    holdout: int | None = None  # how many turns the settlement can hold out


class Settlement(BaseModel):
    id: str
    name: str
    region: str
    garrison_strength: int
    population: int
    buildings: list[str]
    # filled for seats that run their own building, recruiting or taxes
    tax_level: TaxLevel | None = None
    public_order: int | None = None  # percent
    order_parts: dict[str, int] = {}  # what makes up public order (garrison, squalor, unrest...), +/- percent

    @field_validator("order_parts", mode="before")
    @classmethod
    def _empty_parts(cls, v):  # the game's Lua JSON writes an empty table as []
        return {} if v == [] else v
    queue: list[str] = []  # buildings under construction, first first
    can_build: list[BuildOption] = []
    can_recruit: list[RecruitOption] = []
    recruit_blocked: bool = False  # units inside: EOP 3.3.1 can't list recruits safely then
    x: int | None = None
    y: int | None = None
    port_x: int | None = None  # the port entrance, where a fleet docks; none inland
    port_y: int | None = None
    training: list[Training] = []  # recruits paid for, joining the garrison when ready
    siege: Siege | None = None  # besieged now: by whom, and how long it can hold


class Army(BaseModel):
    id: str
    leader: str | None = None  # absent, not null: the game's Lua JSON can't write null
    x: int
    y: int
    strength: int
    units: int
    in_settlement: str | None = None
    faction: str | None = None  # set for foreign armies in sight
    distance: int | None = None  # tiles from the nearest of your armies, agents or settlements
    troops: list[Unit] = []  # your own armies' units, for seats that command armies
    from_x: int | None = None  # a foreign army seen last turn elsewhere: where it was
    from_y: int | None = None
    is_fleet: bool = False  # a fleet (led by an admiral)
    carrying: int | None = None  # a fleet: units of the army aboard
    aboard: str | None = None  # an army at sea: the fleet carrying it
    moves_left: int | None = None
    moves_max: int | None = None


AgentKind = Literal["spy", "assassin", "diplomat", "merchant", "priest", "princess", "admiral",
                    "general", "other"]


class Agent(BaseModel):
    id: str
    kind: AgentKind
    x: int
    y: int
    in_settlement: str | None = None
    faction: str | None = None  # set for foreign agents in sight
    distance: int | None = None


class Person(BaseModel):
    """A named character the faction keeps a record of, the dead included."""
    name: str
    age: int | None = None
    alive: bool = True
    male: bool | None = None
    family: bool = False
    off_map: bool = False
    role: str | None = None  # "leader" or "heir"
    kind: str | None = None  # general, princess, spy, ...; not read for the dead
    spouse: str | None = None
    spouse_faction: str | None = None
    parent: str | None = None
    now_serves: str | None = None  # listed dead here, but alive in this faction's records
    x: int | None = None  # where they stand, if on the map
    y: int | None = None


class ForeignSettlement(BaseModel):
    id: str
    name: str
    faction: str
    x: int
    y: int
    garrison_strength: int = 0
    distance: int | None = None
    seen_turn: int | None = None  # remembered, out of sight now: the turn it was last seen


class TradeResource(BaseModel):
    """A trade resource in sight: a merchant standing on its tile trades there."""
    kind: str
    x: int
    y: int
    distance: int | None = None
    region: str | None = None
    value: int | None = None
    owner: str | None = None  # the faction holding its region


class Crossing(BaseModel):
    """A land crossing: a strait an army walks across without ships."""
    x: int
    y: int
    regions: list[str] = []  # the land regions on either side
    distance: int | None = None


class FactionView(BaseModel):
    id: str
    name: str
    stance: Stance
    settlements: int | None = None  # 0: destroyed
    armies: int | None = None  # stacks, fleets and garrisons included
    leader: str | None = None
    capital: str | None = None


class OrderResult(BaseModel):
    index: int
    type: str
    ok: bool
    reason: str = ""
    now: str = ""  # what the armies the order named look like now (did the merge take?)


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
    visible_enemies: list[Army]  # foreign armies in sight (any faction, not only enemies)
    last_results: list[OrderResult]
    agents: list[Agent] = []  # your own agents
    seen_agents: list[Agent] = []  # foreign agents in sight
    nearby_settlements: list[ForeignSettlement] = []  # foreign settlements in sight
    remembered: list[ForeignSettlement] = []  # seen on earlier turns, out of sight now (filled by the orchestrator)
    human_slot: bool = False  # the campaign's player faction: no game AI acts for it
    popups: list[str] = []  # game popups since the last report, and the button pressed for you
    agent_results: list[str] = []  # how your agents' missions turned out since the last report
    family: list[Person] = []  # every named character on record, the dead included
    character_events: list[str] = []  # what befell your characters since the last report
    news: list[str] = []  # what the game told the realm by message: missions, riots, treaties, crusades
    income_parts: dict[str, int] = {}  # the regular items behind income, costs negative
    stance_changes: list[str] = []  # stance changes since the last report, and whose turn made them
    resources: list[TradeResource] = []  # trade resources in sight, nearest first
    crossings: list[Crossing] = []  # land crossings within reach: walk across, no ships

    @field_validator("income_parts", mode="before")
    @classmethod
    def _empty_table(cls, v):  # the game's Lua JSON writes an empty table as []
        return {} if v == [] else v
    spent_last_turn: int = 0  # one-offs: buildings, recruits, diplomacy (bribes, gifts)
    received_last_turn: int = 0  # one-offs: gifts and the like
    map_width: int | None = None
    map_height: int | None = None


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
    assault: bool = False  # storm it now instead of starving it out


class Withdraw(BaseModel):
    type: Literal["withdraw"] = "withdraw"
    army: str
    to_settlement: str


class Assassinate(BaseModel):
    """Your assassin tries to kill a character in sight (a foreign general or agent)."""
    type: Literal["assassinate"] = "assassinate"
    agent: str
    target: str


class Spy(BaseModel):
    """Your spy infiltrates a settlement or shadows a character in sight."""
    type: Literal["spy"] = "spy"
    agent: str
    target: str


class Bribe(BaseModel):
    """Your diplomat tries to buy a foreign army's general, an agent or a settlement in sight."""
    type: Literal["bribe"] = "bribe"
    agent: str
    target: str


class Sabotage(BaseModel):
    """Your assassin sabotages a foreign settlement in sight."""
    type: Literal["sabotage"] = "sabotage"
    agent: str
    settlement: str


class Build(BaseModel):
    """Queue a building your settlement can build now (from its "can build" list)."""
    type: Literal["build"] = "build"
    settlement: str
    building: str


class Recruit(BaseModel):
    """Queue a unit your settlement can recruit now (from its "can recruit" list)."""
    type: Literal["recruit"] = "recruit"
    settlement: str
    unit: str


class Retrain(BaseModel):
    """Refill the settlement's damaged garrison units whose type its recruitment pool still offers, as
    the game's Retrain tab does: the missing share of the recruit cost, one from the pool each, the
    men arriving next turn. Armour and weapon upgrades aren't included."""
    type: Literal["retrain"] = "retrain"
    settlement: str


class SetTax(BaseModel):
    type: Literal["set_tax"] = "set_tax"
    settlement: str
    level: TaxLevel


class MoveArmy(BaseModel):
    """Move an army toward a map tile (it goes as far as its moves allow this turn)."""
    type: Literal["move_army"] = "move_army"
    army: str
    x: int
    y: int


class Attack(BaseModel):
    """Attack a foreign army in sight (one outside a settlement; besiege settlements instead)."""
    type: Literal["attack"] = "attack"
    army: str
    target: str
    # filled in by the checker from the report, so the bridge attacks only that faction's army
    # even if ids shuffle between the report and the order
    target_faction: str | None = None


class MoveAgent(BaseModel):
    """Walk one of your agents (a princess, diplomat, spy...) toward a map tile."""
    type: Literal["move_agent"] = "move_agent"
    agent: str
    x: int
    y: int


class Marry(BaseModel):
    """Your princess offers marriage to a foreign general in sight."""
    type: Literal["marry"] = "marry"
    agent: str
    target: str


class MergeArmies(BaseModel):
    """Bring one of your armies (a garrison too) to join another; at most 20 units together."""
    type: Literal["merge_armies"] = "merge_armies"
    army: str
    into: str


class MergeUnits(BaseModel):
    """Within one army, fold under-strength units of the same type together, as the game's own
    merge does: soldiers move into the fullest units, and emptied units disband."""
    type: Literal["merge_units"] = "merge_units"
    army: str


class Disband(BaseModel):
    """Release units of one type from an army (a garrison too) to save their upkeep: the
    weakest first, never a general's bodyguard."""
    type: Literal["disband"] = "disband"
    army: str
    unit: str  # the unit type as the army's troops list names it
    count: int = 1


class Board(BaseModel):
    """An army (by its general) or an agent goes aboard one of your fleets (on its tile)."""
    type: Literal["board"] = "board"
    who: str
    fleet: str


class Land(BaseModel):
    """An army aboard a fleet goes ashore on a land tile next to the fleet."""
    type: Literal["land"] = "land"
    army: str
    x: int
    y: int


class Blockade(BaseModel):
    """One of your fleets blockades a foreign settlement's port."""
    type: Literal["blockade"] = "blockade"
    fleet: str
    settlement: str


Order = Annotated[
    Union[SendGold, CedeSettlement, SetStance, MarchOn, Besiege, Withdraw,
          Assassinate, Spy, Bribe, Sabotage, Build, Recruit, Retrain, SetTax, MoveArmy, Attack,
          MoveAgent, Marry, MergeArmies, MergeUnits, Disband, Board, Land, Blockade],
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
    # set by seats.base.to_orders, never part of the schema: where each kept order sat in the
    # LLM's own list, and the orders/messages dropped as malformed (in that numbering)
    _source_index: list[int] | None = PrivateAttr(default=None)
    _malformed: list[OrderResult] = PrivateAttr(default_factory=list)

    @property
    def source_index(self) -> list[int]:
        return self._source_index if self._source_index is not None else list(range(len(self.orders)))

    @source_index.setter
    def source_index(self, value: list[int]) -> None:
        self._source_index = value

    @property
    def malformed(self) -> list[OrderResult]:
        return self._malformed

    @malformed.setter
    def malformed(self, value: list[OrderResult]) -> None:
        self._malformed = value


def orders_json_schema() -> dict:
    return Orders.model_json_schema()
