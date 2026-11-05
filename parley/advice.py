"""MTW2 decision algorithm: siege advice for rulers under siege."""

import math
from typing import Literal

from pydantic import BaseModel

from parley.protocol import Army, StateReport

# Rough estimate of how far a land army moves per turn, to be calibrated from live games.
TILES_PER_TURN = 10

VERDICT_TEXT = {  # the prompt's words for each verdict
    "sally": "strong enough to sally",
    "hold": "hold for relief",
    "relieve_or_lose": "no relief in time: break the siege or lose it",
    "unknown": "holdout unknown",
}


def _turns(n: int) -> str:
    return f"{n} turn" if n == 1 else f"{n} turns"


class SiegeAdvice(BaseModel):
    settlement: str
    holdout: int | None = None
    attacker: str | None = None
    attacker_strength: int | None = None
    garrison_strength: int
    odds: float | None = None
    relief: list[str] = []
    relief_eta: int | None = None
    verdict: Literal["sally", "hold", "relieve_or_lose", "unknown"]
    line: str


def siege_clock(report: StateReport) -> list[SiegeAdvice]:
    advices: list[SiegeAdvice] = []
    for s in report.settlements:
        if s.siege is None:
            continue
        g = s.siege
        holdout = g.holdout
        attacker = g.by or g.faction
        attacker_strength = g.strength
        garrison_strength = s.garrison_strength

        odds: float | None = None
        if attacker_strength is not None and attacker_strength > 0:
            odds = round(garrison_strength / attacker_strength, 2)

        relief_candidates: list[tuple[int, int, Army]] = []
        if s.x is not None and s.y is not None:
            for a in report.armies:
                if a.in_settlement or a.is_fleet or a.aboard:
                    continue
                if a.x is None or a.y is None:
                    continue
                dist = max(abs(a.x - s.x), abs(a.y - s.y))
                eta = max(1, math.ceil(dist / TILES_PER_TURN))
                relief_candidates.append((eta, dist, a))

        relief_candidates.sort(key=lambda item: (item[0], item[1], -item[2].strength, item[2].id))
        relief = [f"Army {a.id}: {_turns(eta)} away, strength {a.strength}" for eta, _, a in relief_candidates]
        relief_eta = relief_candidates[0][0] if relief_candidates else None
        nearest = relief_candidates[0][2] if relief_candidates else None

        if odds is not None and odds >= 1.2:
            verdict = "sally"
        elif relief_eta is not None and holdout is not None and relief_eta <= holdout:
            verdict = "hold"
        elif holdout is not None:
            verdict = "relieve_or_lose"
        else:
            verdict = "unknown"

        settlement_name = s.name or s.id
        holds_str = (f"holds {holdout} more {'turn' if holdout == 1 else 'turns'}"
                     if holdout is not None else "holdout unknown")
        odds_str = f" ({odds})" if odds is not None else ""
        vs_str = (f"garrison {garrison_strength} vs attacker {attacker_strength}{odds_str}"
                  if attacker_strength is not None else f"garrison {garrison_strength} vs attacker unknown")

        if nearest is not None and relief_eta is not None:
            who = nearest.leader or f"Army {nearest.id}"
            t_str = f"{relief_eta} {'turn' if relief_eta == 1 else 'turns'} away"
            relief_str = f"{who} {t_str} (strength {nearest.strength})"
        else:
            relief_str = "no relief"

        verdict_str = VERDICT_TEXT[verdict]
        line = f"Siege of {settlement_name}: {holds_str}; {vs_str}; {relief_str}: {verdict_str}."

        advices.append(
            SiegeAdvice(
                settlement=settlement_name,
                holdout=holdout,
                attacker=attacker,
                attacker_strength=attacker_strength,
                garrison_strength=garrison_strength,
                odds=odds,
                relief=relief,
                relief_eta=relief_eta,
                verdict=verdict,
                line=line,
            )
        )
    return advices
