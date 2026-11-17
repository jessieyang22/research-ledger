"""Tests for as_of.synthetic_calendar. All dates are synthetic calendar facts."""

from datetime import date

import pytest

from as_of.core import AsOfError
from as_of.synthetic_calendar import (
    HOLIDAYS_2026,
    business_days_between,
    is_business_day,
    next_business_day,
    scheduled_dates,
)


# Acceptance tests


def test_saturday_2026_10_24_is_not_business_day():
    assert date(2026, 10, 24).weekday() == 5  # Saturday
    assert not is_business_day(date(2026, 10, 24))


def test_monday_2026_10_26_is_business_day():
    assert date(2026, 10, 26).weekday() == 0  # Monday
    assert is_business_day(date(2026, 10, 26))


def test_next_business_day_from_friday_is_monday():
    friday = date(2026, 10, 2)
    assert friday.weekday() == 4
    assert next_business_day(friday) == date(2026, 10, 5)


def test_business_days_between_monday_and_next_monday_is_five():
    # Non-holiday week: Mon 2026-10-26 to Mon 2026-11-02.
    assert business_days_between(date(2026, 10, 26), date(2026, 11, 2)) == 5


def test_new_years_day_in_holidays():
    assert date(2026, 1, 1) in HOLIDAYS_2026


# Business-day predicate edge cases


def test_ordinary_weekday_is_business_day():
    assert is_business_day(date(2026, 10, 27))  # Tuesday


def test_sunday_is_not_business_day():
    assert not is_business_day(date(2026, 10, 25))


def test_holiday_on_weekday_is_not_business_day():
    # Columbus Day 2026 falls on a Monday.
    assert date(2026, 10, 12).weekday() == 0
    assert not is_business_day(date(2026, 10, 12))


def test_good_friday_is_not_business_day():
    assert not is_business_day(date(2026, 4, 3))


def test_every_holiday_is_a_weekday_in_2026():
    # Holidays are listed on their observed weekday, so none should fall on a weekend.
    for holiday in HOLIDAYS_2026:
        assert holiday.year == 2026
        assert holiday.weekday() < 5, holiday


def test_observed_independence_day_is_july_third():
    assert date(2026, 7, 3) in HOLIDAYS_2026
    assert not is_business_day(date(2026, 7, 3))
    assert date(2026, 7, 4).weekday() == 5  # Saturday, not listed itself


# next_business_day edge cases


def test_next_business_day_from_thursday_skips_thanksgiving_only():
    # Thu 2026-11-26 is Thanksgiving; Fri 2026-11-27 is a business day.
    assert next_business_day(date(2026, 11, 25)) == date(2026, 11, 27)


def test_next_business_day_skips_holiday_and_weekend():
    # Fri 2026-12-25 is Christmas, so the next business day after Thu 12-24 is Mon 12-28.
    assert next_business_day(date(2026, 12, 24)) == date(2026, 12, 28)


def test_next_business_day_from_saturday_is_monday():
    assert next_business_day(date(2026, 10, 24)) == date(2026, 10, 26)


def test_next_business_day_is_strictly_after_input():
    # A business day input still returns the following business day, not itself.
    assert next_business_day(date(2026, 10, 27)) == date(2026, 10, 28)


def test_next_business_day_skips_holiday_on_monday():
    # Sat 2026-10-10 -> Mon 2026-10-12 is Columbus Day, so Tue 10-13 is next.
    assert next_business_day(date(2026, 10, 10)) == date(2026, 10, 13)


# business_days_between edge cases


def test_business_days_between_same_date_is_zero():
    assert business_days_between(date(2026, 10, 27), date(2026, 10, 27)) == 0


def test_business_days_between_friday_to_monday_is_one():
    # Half-open range [Fri, Mon) contains only Friday.
    assert business_days_between(date(2026, 10, 23), date(2026, 10, 26)) == 1


def test_business_days_between_excludes_holiday_inside_range():
    # Range [Mon 10-5, Mon 10-12) has five weekdays; Monday 10-12 is excluded by half-open end.
    assert business_days_between(date(2026, 10, 5), date(2026, 10, 12)) == 5
    # Range [Mon 10-5, Tue 10-13) includes holiday 10-12, so it counts 5 business days, not 6.
    assert business_days_between(date(2026, 10, 5), date(2026, 10, 13)) == 5


def test_business_days_between_reversed_is_negated():
    start = date(2026, 10, 26)
    end = date(2026, 11, 2)
    assert business_days_between(end, start) == -business_days_between(start, end)
    assert business_days_between(end, start) == -5


def test_business_days_between_weekend_only_is_zero():
    assert business_days_between(date(2026, 10, 24), date(2026, 10, 26)) == 0


# scheduled_dates edge cases


def test_scheduled_dates_all_calendar_days():
    result = scheduled_dates(date(2026, 10, 23), date(2026, 10, 27), weekdays_only=False)
    assert result == [
        date(2026, 10, 23),
        date(2026, 10, 24),
        date(2026, 10, 25),
        date(2026, 10, 26),
    ]


def test_scheduled_dates_weekdays_only_drops_weekend():
    result = scheduled_dates(date(2026, 10, 23), date(2026, 10, 27), weekdays_only=True)
    assert result == [date(2026, 10, 23), date(2026, 10, 26)]


def test_scheduled_dates_weekdays_only_keeps_holidays():
    # Columbus Day is a weekday holiday; scheduled_dates keeps it by design.
    result = scheduled_dates(date(2026, 10, 10), date(2026, 10, 14), weekdays_only=True)
    assert date(2026, 10, 12) in result
    assert result == [date(2026, 10, 12), date(2026, 10, 13)]


def test_scheduled_dates_empty_when_start_equals_end():
    assert scheduled_dates(date(2026, 10, 26), date(2026, 10, 26), weekdays_only=True) == []


def test_scheduled_dates_rejects_reversed_range():
    with pytest.raises(AsOfError):
        scheduled_dates(date(2026, 10, 27), date(2026, 10, 26), weekdays_only=False)
