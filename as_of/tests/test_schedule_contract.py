"""Tests for as_of.schedule_contract.

Synthetic dates only.
"""

from datetime import date, datetime

import pytest

from as_of.core import AsOfError
from as_of.schedule_contract import ScheduleContract, expected_runs


def _contract(**overrides):
    params = dict(
        name="synthetic_daily_close",
        cadence="weekly",
        due_time="09:30",
        grace_minutes=15,
        business_days_only=False,
    )
    params.update(overrides)
    return ScheduleContract(**params)


# Acceptance tests


def test_weekly_contract_over_four_weeks_gives_four_runs():
    # 2026-01-05 is a Monday. Four weekly runs fall on Jan 5, 12, 19 and 26.
    contract = _contract(cadence="weekly", due_time="09:30")
    runs = expected_runs(contract, date(2026, 1, 5), date(2026, 2, 1))
    assert runs == [
        datetime(2026, 1, 5, 9, 30),
        datetime(2026, 1, 12, 9, 30),
        datetime(2026, 1, 19, 9, 30),
        datetime(2026, 1, 26, 9, 30),
    ]


def test_business_days_only_skips_a_saturday():
    # 2026-01-03 is a Saturday, 2026-01-05 is a Monday.
    contract = _contract(cadence="daily", business_days_only=True)
    runs = expected_runs(contract, date(2026, 1, 2), date(2026, 1, 5))
    days = [r.date() for r in runs]
    assert date(2026, 1, 3) not in days
    assert date(2026, 1, 4) not in days
    assert days == [date(2026, 1, 2), date(2026, 1, 5)]


def test_due_time_25_00_raises_as_of_error():
    with pytest.raises(AsOfError):
        _contract(due_time="25:00")


def test_grace_minutes_is_stored_unchanged():
    contract = _contract(grace_minutes=45)
    assert contract.grace_minutes == 45
    # Grace is not applied to the run times.
    runs = expected_runs(contract, date(2026, 1, 5), date(2026, 1, 5))
    assert runs == [datetime(2026, 1, 5, 9, 30)]


# Edge cases


def test_daily_cadence_without_weekend_filter_keeps_saturday_and_sunday():
    contract = _contract(cadence="daily", business_days_only=False)
    runs = expected_runs(contract, date(2026, 1, 2), date(2026, 1, 5))
    assert [r.date() for r in runs] == [
        date(2026, 1, 2),
        date(2026, 1, 3),
        date(2026, 1, 4),
        date(2026, 1, 5),
    ]


def test_weekly_business_days_only_drops_weekend_runs_without_rolling():
    # Every weekly run from a Saturday start is a Saturday, so all are dropped, none moved to Monday.
    contract = _contract(cadence="weekly", business_days_only=True)
    assert expected_runs(contract, date(2026, 1, 3), date(2026, 1, 17)) == []


def test_weekly_business_days_only_keeps_weekday_runs():
    # Friday 2026-01-02 start: runs on Jan 2, 9, 16, 23 are all Fridays and kept.
    contract = _contract(cadence="weekly", business_days_only=True)
    runs = expected_runs(contract, date(2026, 1, 2), date(2026, 1, 23))
    assert [r.date() for r in runs] == [
        date(2026, 1, 2),
        date(2026, 1, 9),
        date(2026, 1, 16),
        date(2026, 1, 23),
    ]


def test_monthly_runs_clamp_to_last_day_of_shorter_month():
    # Anchor day 31 from Jan 31, 2026. February clamps to Feb 28.
    contract = _contract(cadence="monthly")
    runs = expected_runs(contract, date(2026, 1, 31), date(2026, 3, 31))
    assert [r.date() for r in runs] == [
        date(2026, 1, 31),
        date(2026, 2, 28),
        date(2026, 3, 31),
    ]


def test_range_with_start_equal_to_end_gives_one_run_when_cadence_fires():
    contract = _contract(cadence="daily")
    runs = expected_runs(contract, date(2026, 1, 5), date(2026, 1, 5))
    assert runs == [datetime(2026, 1, 5, 9, 30)]


def test_start_after_end_raises():
    with pytest.raises(AsOfError):
        expected_runs(_contract(), date(2026, 2, 1), date(2026, 1, 1))


def test_datetime_inputs_raise():
    with pytest.raises(AsOfError):
        expected_runs(_contract(), datetime(2026, 1, 5, 0, 0), date(2026, 1, 6))


def test_unknown_cadence_raises():
    with pytest.raises(AsOfError):
        _contract(cadence="hourly")


@pytest.mark.parametrize("bad", ["9:30", "0930", "09:3", "ab:cd", "24:00", "12:60", ""])
def test_malformed_due_time_raises(bad):
    with pytest.raises(AsOfError):
        _contract(due_time=bad)


def test_due_time_non_string_raises():
    with pytest.raises(AsOfError):
        _contract(due_time=930)


def test_negative_grace_minutes_raises():
    with pytest.raises(AsOfError):
        _contract(grace_minutes=-1)


def test_bool_grace_minutes_raises():
    with pytest.raises(AsOfError):
        _contract(grace_minutes=True)


def test_non_bool_business_days_only_raises():
    with pytest.raises(AsOfError):
        _contract(business_days_only="yes")


def test_blank_name_raises():
    with pytest.raises(AsOfError):
        _contract(name="   ")
