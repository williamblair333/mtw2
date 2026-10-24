from parley.prompt import build_prompt
from parley.protocol import OrderResult


def test_prompt_lists_ids(venice_report):
    p = build_prompt(venice_report, persona="You are Doge Enrico.")
    assert "hre (Holy Roman Empire)" in p
    assert "venice" in p


def test_prompt_includes_rejections(venice_report):
    report = venice_report.model_copy(update={"last_results": [
        OrderResult(index=0, type="send_gold", ok=False, reason="treasury too low")]})
    assert "treasury too low" in build_prompt(report, persona="p")


def test_prompt_includes_scenario_when_given(venice_report):
    assert "SCENARIO" in build_prompt(venice_report, persona="p", scenario="Humans vs LLMs.")
    assert "SCENARIO" not in build_prompt(venice_report, persona="p")


def test_prompt_states_treasury(venice_report):
    assert "5000" in build_prompt(venice_report, persona="p")


def _msg(channel, sender, text, turn=1):
    from parley.store import Message
    return Message(id=1, game_id="test", turn=turn, channel=channel, sender=sender, text=text, ts=0)


def test_prompt_shows_diplomacy_labels(venice_report):
    p = build_prompt(venice_report, persona="p", diplomacy=[
        _msg("lobby", "milan", "Milan fears no one."),
        _msg("pair:england|venice", "human:england", "Join me against the HRE?", turn=2),
    ], names={"milan": "Duke Ottone", "england": "King of England"})
    assert "[turn 1] [public] Duke Ottone (milan): Milan fears no one." in p
    assert "[turn 2] [private with england] King of England (england): Join me against the HRE?" in p


def test_prompt_says_promises_bind_nothing(venice_report):
    p = build_prompt(venice_report, persona="p", diplomacy=[_msg("lobby", "milan", "hi")])
    assert "bind nothing" in p


def test_prompt_no_diplomacy_section_when_empty(venice_report):
    assert "DIPLOMACY" not in build_prompt(venice_report, persona="p")


def test_prompt_includes_recent_notes(venice_report):
    p = build_prompt(venice_report, persona="p", notes=[(1, "Decline the bribe."), (2, "Watch Milan.")])
    assert "YOUR RECENT NOTES" in p and "[turn 1] Decline the bribe." in p and "[turn 2] Watch Milan." in p


def test_prompt_includes_events(venice_report):
    p = build_prompt(venice_report, persona="p", events=["France declared war on you."])
    assert "SINCE YOUR LAST TURN" in p and "- France declared war on you." in p


def test_prompt_says_dont_repeat(venice_report):
    assert "don't repeat" in build_prompt(venice_report, persona="p").lower()


def test_zero_income_shown_as_unknown(venice_report):
    p = build_prompt(venice_report.model_copy(update={"income": 0}), persona="p")
    assert "Income: not reported" in p and "Income: 0" not in p


def test_leaderless_field_stack_has_no_fake_position(venice_report):
    from parley.protocol import Army
    stray = Army(id="stack:8", x=0, y=0, strength=300, units=2)
    p = build_prompt(venice_report.model_copy(update={"armies": [stray]}), persona="p")
    assert "stack:8: 2 units, strength 300, position unknown (fleet, fort or no general)" in p
    assert "(0,0)" not in p


def test_prompt_starts_with_persona(venice_report):
    assert build_prompt(venice_report, persona="You are Doge Enrico.").startswith("You are Doge Enrico.")
