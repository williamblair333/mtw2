from __future__ import annotations

import re

from parley.deciders.adoption import AdoptionScore

RANSOM_PATTERNS = [
    re.compile(r"total\s+ransom\s+value\s*:\s*([0-9]+(?:,[0-9]+)*)", re.IGNORECASE),
    re.compile(r"ransom\s*:\s*([0-9]+(?:,[0-9]+)*)", re.IGNORECASE),
    re.compile(r"([0-9]+(?:,[0-9]+)*)\s*florins\b", re.IGNORECASE),
    re.compile(r"([0-9]+(?:,[0-9]+)*)\s*gold\b", re.IGNORECASE),
]


def parse_ransom_value(reading: str) -> int | None:
    """Parse ransom amount from scroll text reading.

    Parses the first of:
    1. "Total Ransom Value: N"
    2. "Ransom: N"
    3. "N florins"
    4. "N gold"
    (case-insensitive, handling commas in numbers like "1,250").
    Returns None if no match.
    """
    if not isinstance(reading, str):
        return None
    for pat in RANSOM_PATTERNS:
        m = pat.search(reading)
        if m:
            try:
                return int(m.group(1).replace(",", ""))
            except ValueError:
                continue
    return None


def score_captor(value: int | None) -> AdoptionScore:
    """Score a captor scroll (prisoners taken in battle).

    Accept means "ransom". The steward never picks execute or release by rule
    (they are reputation choices the ruler owns). Known is True when value is
    not None and value < 1500; a value >= 1500 escalates to the ruler.
    """
    known = value is not None and value < 1500
    accept = 10.0
    decline = 0.0
    stakes = 0.2
    reason = (
        f"prisoners worth {value} gold: ransomed by custom"
        if value is not None
        else "prisoners worth unknown gold: ransomed by custom"
    )
    return AdoptionScore(
        accept=accept,
        decline=decline,
        stakes=stakes,
        known=known,
        reason=reason,
    )


def score_captive(value: int | None, treasury: int | None) -> AdoptionScore:
    """Score a captive scroll (your men captured, ransom demanded).

    Accept means "pay". Known is True when both value and treasury are not None.
    If value > treasury: accept = 0, decline = 10 (can't pay).
    Else: share = value / max(treasury, 1)
          accept = 10 * (1 - share) - 3 when share <= 0.5 else 0
          decline = 3 + 10 * share
    Stakes: 0.3. Reason names the price and the treasury.
    """
    stakes = 0.3
    if value is None or treasury is None:
        return AdoptionScore(
            accept=0.0,
            decline=10.0,
            stakes=stakes,
            known=False,
            reason=f"ransom {value if value is not None else 'unknown'}, treasury {treasury if treasury is not None else 'unknown'}",
        )

    known = True
    if value > treasury:
        accept = 0.0
        decline = 10.0
        reason = f"ransom {value} exceeds treasury {treasury}: cannot pay"
    else:
        share = value / max(treasury, 1)
        accept = 10.0 * (1.0 - share) - 3.0 if share <= 0.5 else 0.0
        decline = 3.0 + 10.0 * share
        reason = f"ransom {value}, treasury {treasury}"

    return AdoptionScore(
        accept=accept,
        decline=decline,
        stakes=stakes,
        known=known,
        reason=reason,
    )
