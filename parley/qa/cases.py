"""QA bench case and suite models, loaded from TOML files."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, model_validator

# how long an instant case's check polls its query before it fails (live run9: a character's tile
# after a split lagged the call that made it; read a few seconds later it was right)
INSTANT_WITHIN = 10.0

# How a case starts (a bench run only). "fresh": on the bench save as recorded; the runner reloads
# it (M.qa.load, ~4 s live) when any case ran since the last load. "shared": on whatever the case
# before it left. A suite sets the default, a case may override it, and the first case of every
# suite starts fresh whatever it says (live 10-31 phase 1: spawns piled up around London over 30
# cases until no free tile was left beside it; a general one case withdrew into London was the next
# cases' garrison leader).
Isolation = Literal["fresh", "shared"]


class Expect(BaseModel):
    """One thing a case must show. `at_least` compares the `state` value as a number (a `$name`
    placeholder is filled first); `any_of` passes when any one of its expects does (live 10-30
    21:56: a treasury already at the playtest target logs no top-up, so the funds case accepts
    either the top-up line or a full treasury)."""

    log: str | None = None
    state: str | None = None
    equals: str | int | None = None
    at_least: str | int | float | None = None
    order_ok: bool | None = None
    any_of: list[Expect] | None = None
    # instant cases only: a control line polled until its result passes (`equals` the text,
    # `match`es a regex, has no `no_match`, is a number `below`/`at_least` a value) or `within` s pass.
    # `within` on a `log` expect polls the log that long (an agent's mission line comes after his walk)
    lua: str | None = None
    match: str | None = None
    no_match: str | None = None
    below: str | int | float | None = None
    within: float | None = None
    # the game still running `alive` seconds after the first log line matching `after` (the papal
    # crash check): a later line of the same game's bridge log, timed at least that long after it,
    # with no bridge (re)load between (a relaunched game's lines prove nothing about the old one).
    # Instant cases also ask the bridge a control line on each look, so its log advances while held.
    alive: float | None = None
    after: str | None = None

    @model_validator(mode="after")
    def _at_least_reads_a_state(self) -> Expect:
        if (self.alive is None) != (self.after is None):
            raise ValueError("alive and after go together: seconds alive after a log line")
        if self.alive is not None:
            others = (self.log, self.state, self.equals, self.at_least, self.order_ok, self.lua,
                      self.match, self.no_match, self.below)
            if any(v is not None for v in others) or self.any_of:
                raise ValueError("an alive expect is a check of its own: only alive, after and within")
            if self.alive <= 0:
                raise ValueError("alive needs a number of seconds above 0")
            return self
        if self.at_least is not None and self.state is None and self.lua is None:
            raise ValueError("at_least needs a state path or a lua query")
        if self.at_least is not None and self.equals is not None:
            raise ValueError("at_least and equals can't both be set")
        if self.lua is not None:
            if self.state is not None or self.log is not None or self.order_ok is not None or self.any_of:
                raise ValueError("a lua expect is a query of its own: no state, log, order_ok or any_of")
            if all(v is None for v in (self.equals, self.match, self.no_match, self.below, self.at_least)):
                raise ValueError("a lua expect needs equals, match, no_match, below or at_least")
        elif any(v is not None for v in (self.match, self.no_match, self.below)):
            raise ValueError("match, no_match and below go with a lua query")
        elif self.within is not None and self.log is None:
            raise ValueError("within goes with a lua query or a log line")
        return self

    @property
    def independent(self) -> bool:
        """Evidence of its own (a log line or a state value), not just orders accepted: an `any_of`
        counts only when every alternative is, so an order_ok alternative can't pass it alone."""
        if self.log is not None or self.state is not None or self.lua is not None or self.alive is not None:
            return True
        return bool(self.any_of) and all(e.independent for e in self.any_of)


class SetupStep(BaseModel):
    """A setup line whose control result is kept: `bind = "spy"` makes it `$spy` in later
    setup lines, orders and expects (live 10-30: the game names a spawned agent itself)."""

    lua: str
    bind: str | None = None
    # instant cases: the result must match this regex, or the case is skipped (inconclusive) with
    # the result as the reason; polled for `within` seconds (0: read once), so only on a query
    require: str | None = None
    within: float = 0.0


class Case(BaseModel):
    name: str
    # "turn": orders, end turns, check the next report. "instant": setup, act and check by control
    # lines inside one turn, which the runner holds (no End Turn) while the case runs
    kind: Literal["turn", "instant"] = "turn"
    setup: list[str | SetupStep] = []
    act: list[str | SetupStep] = []
    orders: dict[int, list[dict]] = {}
    expect: list[Expect]
    targets: dict[str, str | int] = {}
    max_turns: int = 3
    # AI factions this case needs to act (an AI siege, an offer): their game AI is thawed for the
    # case, from each one's next turn start; every other AI faction stays frozen (the quiet world)
    needs: list[str] = []
    chance: bool = False
    # turn cases: the scripted ruler's answer to every choice the game asks during the case's turns
    # (an AI's offer: "accept" or "decline"); unset, the seat says nothing and the bridge's default goes
    choice: str | None = None
    seat: str = "script"
    directive: str = ""
    # unset: the suite's isolation (Suite.isolation)
    isolation: Isolation | None = None
    # an instant case that can't pass in phase 1 (the no-click `kind=instant` run), and why: that run
    # reports it skipped with this reason; a full run (phase 2) still runs it
    phase2: str | None = None

    @model_validator(mode="after")
    def _kind_fits(self) -> Case:
        if self.phase2 is not None and (self.kind != "instant" or not self.phase2.strip()):
            raise ValueError(f"case {self.name}: phase2 is the reason an instant case waits for phase 2 "
                             "(a turn case is phase 2 already)")
        exps, todo = [], list(self.expect)
        while todo:
            e = todo.pop()
            exps.append(e)
            todo.extend(e.any_of or [])
        if self.kind == "instant":
            if self.orders:
                raise ValueError(f"instant case {self.name}: no orders (it never ends a turn)")
            if any(e.state is not None or e.order_ok is not None for e in exps):
                raise ValueError(f"instant case {self.name}: expects are lua queries or log lines, not state/order_ok")
            if self.choice is not None:
                raise ValueError(f"instant case {self.name}: no choice (no seat answers in a held turn; "
                                 "M.qa.diplomacy_step(answer) does)")
        else:
            if self.act or any(e.lua is not None or e.within is not None for e in exps):
                raise ValueError(f'case {self.name}: act, lua expects and within are for kind = "instant"')
            if any(isinstance(s, SetupStep) and s.require is not None for s in self.setup):
                raise ValueError(f'case {self.name}: require is for kind = "instant"')
        return self

    @property
    def binds(self) -> set[str]:
        """Names the case's setup (and act) binds. A bound tile ("x,y", as M.qa.free_tile returns)
        also binds `<name>_x` and `<name>_y` (the runner fails the case if a bind comes back empty)."""
        names = {s.bind for s in [*self.setup, *self.act] if isinstance(s, SetupStep) and s.bind}
        return names | {f"{n}_{axis}" for n in names for axis in ("x", "y")}


class Suite(BaseModel):
    name: str
    faction: str
    cases: list[Case]
    # the QA seat gets the steward (parley/steward.py), which backfills an emptied garrison: the towns
    # suite's #225 case. Off by default: a steward recruit in another suite's turn would be noise
    steward: bool = False
    # each case's isolation unless it sets its own (see Isolation)
    isolation: Isolation = "fresh"

    @property
    def instant(self) -> bool:
        return bool(self.cases) and all(c.kind == "instant" for c in self.cases)

    def isolation_of(self, case: Case) -> Isolation:
        return case.isolation or self.isolation


def load_suite(path: Path | str) -> Suite:
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    return Suite.model_validate(data)
