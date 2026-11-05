from __future__ import annotations

import math

from parley.deciders.adoption import AdoptionScore
from parley.protocol import StateReport

MARRIAGE_DECLINE_BASELINE = 8.0


def score_marriage(suitor: dict, report: StateReport | None) -> AdoptionScore:
    cmd = suitor.get("command")
    loy = suitor.get("loyalty")
    piety = suitor.get("piety")
    cd = suitor.get("chivalry_or_dread")
    age = suitor.get("age")

    cmd_val = float(cmd or 0)
    loy_val = float(loy or 0)
    piety_val = float(piety or 0)
    cd_val = float(abs(cd or 0))

    accept = 2.0 * cmd_val + 1.5 * loy_val + 0.5 * piety_val + 0.5 * cd_val

    if age is not None:
        if age <= 30:
            accept += 2.0
        elif 31 <= age <= 45:
            accept += 1.0
        elif age > 60:
            accept -= 3.0

    if loy is not None and loy <= 1:
        accept -= 4.0

    if report is not None:
        # report.family lists every named character on record; count the family itself
        living = [p for p in report.family if p.alive and p.family]
        generals = [p for p in living if p.kind == "general"]
        generals_count = len(generals)
        settlements_count = len(report.settlements)

        if generals_count < math.ceil(settlements_count / 2):
            accept += 2.0

        reason = (
            f"Command {cmd if cmd is not None else 'unknown'}, "
            f"loyalty {loy if loy is not None else 'unknown'}, "
            f"age {age if age is not None else 'unknown'}; "
            f"the family has {generals_count} generals for {settlements_count} settlements."
        )
    else:
        reason = (
            f"Command {cmd if cmd is not None else 'unknown'}, "
            f"loyalty {loy if loy is not None else 'unknown'}, "
            f"age {age if age is not None else 'unknown'}."
        )

    decline = MARRIAGE_DECLINE_BASELINE
    known = cmd is not None and loy is not None
    stakes = 0.3

    return AdoptionScore(
        accept=accept,
        decline=decline,
        stakes=stakes,
        known=known,
        reason=reason,
    )
