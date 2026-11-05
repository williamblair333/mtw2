import datetime as dt

import pytest

from parley.qa.power import estimate_seconds, power_off_refusal, power_off_time

OFF = dt.time(23, 59)


def at(h, m):
    return dt.datetime(2026, 11, 5, h, m)


def test_no_power_off_set_never_refuses(tmp_path):
    assert power_off_time({}, env_file=tmp_path / "none.conf") is None
    assert power_off_refusal(at(23, 50), 500, None) is None


def test_a_run_that_ends_before_power_off_starts():
    assert power_off_refusal(at(12, 0), 75, OFF) is None


def test_a_run_that_would_cross_power_off_is_refused_with_the_numbers():
    why = power_off_refusal(at(23, 30), 75, OFF)
    assert why is not None
    assert "23:59" in why and "29 min from now" in why and f"{estimate_seconds(75) // 60} min" in why


def test_after_power_on_the_next_power_off_is_tomorrow():
    # 03:05, just powered back on: almost 21 h to go
    assert power_off_refusal(at(3, 5), 75, OFF) is None


def test_the_time_is_read_from_the_environment_d_file_over_ssh(tmp_path):
    f = tmp_path / "parley.conf"
    f.write_text("PARLEY_STEAM_URL=steam://launch/4700/option0\nPARLEY_POWER_OFF=23:59\n")
    assert power_off_time({}, env_file=f) == OFF
    assert power_off_time({"PARLEY_POWER_OFF": "22:30"}, env_file=f) == dt.time(22, 30)
    assert power_off_time({"PARLEY_POWER_OFF": ""}, env_file=f) is None


def test_a_malformed_time_is_an_error_not_a_silent_pass():
    with pytest.raises(ValueError, match="HH:MM"):
        power_off_time({"PARLEY_POWER_OFF": "midnight"})
