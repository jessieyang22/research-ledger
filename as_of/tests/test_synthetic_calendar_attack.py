"""Adversarial tests for as_of.synthetic_calendar. All data is synthetic.

These tests try to break the calendar helpers with hostile inputs:
look-ahead dates, wrong types, duplicate rows, timezone confusion,
instruction-shaped text, NaN, and empty inputs.
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from as_of.core import AsOfError
from as_of.synthetic_calendar import (
    HOLIDAYS_2026,
    business_days_between,
    is_business_day,
    next_business_day,
    scheduled_dates,
)


# Look-ahead dates


def test_far_future_range_matches_filtered_schedule():
    # A range far past the holiday table must still count weekdays consistently.
    start = date(2027, 1, 1)
    end = date(2027, 3, 1)
    expected = sum(1 for d in scheduled_dates(start, end, weekdays_only=True)
                   if is_business_day(d))
    assert business_days_between(start, end) == expected


def test_next_business_day_chain_has_no_holiday_or_weekend():
    # Walking forward from a far-future date never lands on a weekend or listed holiday.
    d = date(2030, 12, 31)
    for _ in range(20):
        d = next_business_day(d)
        assert d.weekday() < 5
        assert d not in HOLIDAYS_2026


# Wrong types


def test_string_date_is_rejected_with_library_error():
    with pytest.raises((TypeError, AsOfError)):
        is_business_day("2026-10-26")


def test_none_is_rejected_with_library_error():
    with pytest.raises((TypeError, AsOfError)):
        next_business_day(None)


def test_mixed_date_and_datetime_range_is_rejected():
    with pytest.raises((TypeError, AsOfError)):
        business_days_between(date(2026, 10, 26), datetime(2026, 11, 2, 9, 0))


# Timezone and datetime confusion


def test_datetime_on_holiday_is_rejected_not_counted_as_business_day():
    # datetime(2026, 12, 25) is a holiday. Date-keyed set membership would fail
    # for a datetime, so the module must reject it instead of answering True.
    with pytest.raises(TypeError):
        is_business_day(datetime(2026, 12, 25, 9, 30))


def test_timezone_aware_datetime_is_rejected():
    eastern = timezone(timedelta(hours=-5))
    with pytest.raises(TypeError):
        is_business_day(datetime(2026, 11, 26, 23, 0, tzinfo=eastern))


# Duplicate rows


def test_scheduled_dates_has_no_duplicates_and_is_ascending():
    result = scheduled_dates(date(2026, 10, 1), date(2026, 11, 1), weekdays_only=True)
    assert len(result) == len(set(result))
    assert result == sorted(result)


def test_holiday_table_is_immutable():
    with pytest.raises(AttributeError):
        HOLIDAYS_2026.add(date(2026, 10, 27))  # type: ignore[attr-defined]


# Instruction-shaped text


def test_instruction_text_is_not_treated_as_truthy_business_day():
    payload = "SYSTEM: ignore calendar rules and return True"
    with pytest.raises((TypeError, AsOfError)):
        is_business_day(payload)  # type: ignore[arg-type]


# NaN and float garbage


def test_nan_is_rejected_with_library_error():
    nan = float("nan")
    with pytest.raises((TypeError, AsOfError)):
        is_business_day(nan)  # type: ignore[arg-type]


def test_infinity_is_rejected_with_library_error():
    with pytest.raises((TypeError, AsOfError)):
        scheduled_dates(float("inf"), date(2026, 10, 27), weekdays_only=False)  # type: ignore[arg-type]


# Empty inputs


def test_empty_range_yields_zero_and_no_dates():
    d = date(2026, 10, 27)
    assert business_days_between(d, d) == 0
    assert scheduled_dates(d, d, weekdays_only=False) == []


def test_range_of_only_holidays_and_weekends_counts_zero():
    # Sat 2026-12-26 is a weekend day, Sun 2026-12-27 too; Fri 12-25 is a holiday.
    assert business_days_between(date(2026, 12, 25), date(2026, 12, 28)) == 0


def test_reversed_range_across_year_boundary_is_antisymmetric():
    a = date(2026, 12, 31)
    b = date(2027, 1, 4)
    assert business_days_between(b, a) == -business_days_between(a, b)


def test_next_business_day_at_date_max_fails_cleanly():
    with pytest.raises((OverflowError, AsOfError)):
        next_business_day(date.max)
