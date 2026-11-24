"""diplomacy/frozen_rival_offers_nothing passed in vain on 11-06: its rival took no turn in the one
AI round it saw. Its log expect has to refuse that log, and an offer anywhere in the case's log."""
import re
from pathlib import Path

from parley.qa.cases import load_suite

SUITE = Path(__file__).resolve().parent.parent / "games" / "qa" / "diplomacy.toml"
OFFER = "popup popup-6-1: an AI's diplomatic offer, the ruler chooses: decline, accept"
END5, END6, END7 = (f"autoplay: ending turn {t}" for t in (5, 6, 7))
FROZEN = "denmark: game AI frozen"
OTHER = "france: game AI frozen"


def the_case():
    return next(c for c in load_suite(SUITE).cases if c.name == "frozen_rival_offers_nothing")


def passes(*lines: str) -> bool:
    pattern = the_case().expect[0].log.replace("$rival", "denmark")
    # as parley/qa/checker.py _check_expect searches it
    return re.search(pattern, "\n".join(lines), re.MULTILINE) is not None


def test_two_rounds_with_the_rivals_turn_and_no_offer_pass():
    assert passes("qa: rival ok: denmark", END5, FROZEN, END6, FROZEN, END7)


def test_the_11_06_log_does_not_pass_the_rival_took_no_turn():
    assert not passes("qa: rival ok: aztecs", END5, OTHER, END6, OTHER, END7)


def test_one_round_does_not_pass():
    assert not passes(END5, FROZEN, END6)


def test_an_offer_in_either_round_fails_even_with_a_clean_stretch_after_it():
    assert not passes(END5, OFFER, FROZEN, END6, FROZEN, END7, FROZEN, END7, FROZEN, END7)
    assert not passes(END5, FROZEN, END6, OFFER, FROZEN, END7, FROZEN, END7)


def test_the_case_asks_for_a_rival_that_takes_its_turns_and_time_for_two_rounds():
    case = the_case()
    assert case.max_turns >= 3
    assert 'M.qa.rival("england", 1, true)' in str(case.setup[0])
