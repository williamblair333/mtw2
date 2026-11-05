import pytest

from parley.deciders.ransom import parse_ransom_value, score_captive, score_captor


def test_parse_ransom_value_patterns():
    assert parse_ransom_value("Total Ransom Value: 209") == 209
    assert parse_ransom_value("Ransom: 500") == 500
    assert parse_ransom_value("The enemy demands 300 florins to release them.") == 300
    assert parse_ransom_value("Deliver 450 gold to the envoy.") == 450


def test_parse_ransom_value_with_commas():
    assert parse_ransom_value("Total Ransom Value: 1,250") == 1250
    assert parse_ransom_value("Ransom: 2,500") == 2500
    assert parse_ransom_value("They ask 10,000 florins") == 10000
    assert parse_ransom_value("Pay 1,000,000 gold") == 1000000


def test_parse_ransom_value_case_insensitive():
    assert parse_ransom_value("total ransom value: 350") == 350
    assert parse_ransom_value("TOTAL RANSOM VALUE: 120") == 120
    assert parse_ransom_value("ransom: 800") == 800
    assert parse_ransom_value("250 FLORINS") == 250
    assert parse_ransom_value("600 GOLD") == 600


def test_parse_ransom_value_realistic_reading():
    reading = (
        "Title: Enemies Captured ... Rows: Town Militia | 5 | 19 ... "
        "Total Ransom Value: 209 ... Buttons: Ransom, Release, Execute"
    )
    assert parse_ransom_value(reading) == 209


def test_parse_ransom_value_no_match():
    assert parse_ransom_value("Enemies captured, but no gold demanded") is None
    assert parse_ransom_value("") is None
    assert parse_ransom_value("123 swordsmen") is None
    assert parse_ransom_value(None) is None


def test_score_captor_low_value():
    score = score_captor(209)
    assert score.known is True
    assert score.accept == 10.0
    assert score.decline == 0.0
    assert score.stakes == 0.2
    assert "prisoners worth 209 gold: ransomed by custom" in score.reason


def test_score_captor_threshold():
    assert score_captor(1499).known is True
    assert score_captor(1500).known is False
    assert score_captor(2500).known is False
    assert score_captor(None).known is False


def test_score_captive_unknown():
    assert score_captive(None, 1000).known is False
    assert score_captive(500, None).known is False
    assert score_captive(None, None).known is False


def test_score_captive_unaffordable():
    score = score_captive(1500, 1000)
    assert score.known is True
    assert score.accept == 0.0
    assert score.decline == 10.0
    assert score.stakes == 0.3
    assert "1500" in score.reason and "1000" in score.reason


def test_score_captive_cheap():
    # share = 100 / 1000 = 0.1 <= 0.5
    # accept = 10 * (1 - 0.1) - 3 = 6.0
    # decline = 3 + 10 * 0.1 = 4.0
    score = score_captive(100, 1000)
    assert score.known is True
    assert score.accept == pytest.approx(6.0)
    assert score.decline == pytest.approx(4.0)
    assert score.stakes == 0.3
    assert "100" in score.reason and "1000" in score.reason


def test_score_captive_expensive_below_treasury():
    # share = 600 / 1000 = 0.6 > 0.5
    # accept = 0.0
    # decline = 3 + 10 * 0.6 = 9.0
    score = score_captive(600, 1000)
    assert score.known is True
    assert score.accept == 0.0
    assert score.decline == pytest.approx(9.0)
    assert score.stakes == 0.3
    assert "600" in score.reason and "1000" in score.reason
