from test_adviser import _msg

from parley.chat import chat_prompt
from parley.prompt import TECHNICAL_NOTES, adviser_section


def test_the_ruler_knows_it_plays_a_game_with_its_adviser():
    # the author, 2026-10-26: "on screen message keeps minimizing" got a scribe's-trouble answer
    incoming = _msg("adviser:england", "adviser:england", "On screen message keeps minimizing")
    assert TECHNICAL_NOTES in chat_prompt("p", "england", [], incoming, {})
    assert TECHNICAL_NOTES in adviser_section("lord_ipsi")
    # live, turn 23: "let Claude check if the repair went through" came back as "the clerk who asked"
    assert "Claude" in TECHNICAL_NOTES and "the developer who runs Parley" in TECHNICAL_NOTES


def test_other_rulers_never_see_the_technical_note():
    incoming = _msg("pair:england|france", "france", "Call your diplomat home.")
    assert TECHNICAL_NOTES not in chat_prompt("p", "england", [], incoming, {})
